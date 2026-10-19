"""Общие утилиты для скраперов: robots.txt, детект антибот-защиты, тип результата."""

import logging
import re
import urllib.robotparser
from dataclasses import dataclass
from typing import Dict, Iterator, List, Optional, Tuple
from urllib.parse import urljoin, urlparse

import requests

logger = logging.getLogger("promo_monitor.scraper")

# Честный User-Agent: бот не притворяется обычным браузером.
USER_AGENT = "PromoMonitorBot/1.0 (+internal competitor-promo monitoring; contact: ops)"

REQUEST_TIMEOUT = 30  # сек, п.7 ТЗ
MAX_RETRIES = 1  # одна повторная попытка перед пометкой "ошибка", п.7 ТЗ

# Маркеры активной антибот-защиты. Если встречены — сайт помечается
# blocked_by_antibot и НЕ подвергается попыткам обхода (см. п.2 ограничений ТЗ).
ANTIBOT_MARKERS = (
    "checking your browser",
    "cf-browser-verification",
    "cf-chl-",
    "attention required! | cloudflare",
    "just a moment...",
    "ddos protection by",
    "datadome",
    "perimeterx",
    "px-captcha",
    "hcaptcha",
    "g-recaptcha",
    "recaptcha",
)

# Отдельно от ANTIBOT_MARKERS: эти маркеры блокируют страницу БЕЗ учёта
# title/размера ниже (см. detect_antibot). Обнаружено на palmsbet.com —
# Cloudflare Turnstile-виджет встроен прямо в полноценную страницу сайта
# (обычный <title>, 650+ КБ HTML), а не отдаёт отдельный компактный
# challenge-экран — эвристика "маленькая страница = challenge" для такого
# случая в принципе не подходит. Сами фразы/домен настолько специфичны для
# активного челленджа, что риск ложного срабатывания на настоящей промо-
# странице пренебрежимо мал (в отличие от, например, "recaptcha" выше,
# которая может встретиться просто как виджет где-то в футере страницы).
DEFINITIVE_ANTIBOT_MARKERS = (
    "challenges.cloudflare.com",
    "cf-turnstile",
    "verify you are human",
    "please verify you are a human",
)


@dataclass
class FetchResult:
    status: str  # "ok" | "no_selector_match" | "blocked_by_antibot" | "robots_disallowed" | "error"
    text: Optional[str] = None
    error: Optional[str] = None
    screenshot: Optional[bytes] = None  # PNG промо-блока, только для render: js (см. js_fetcher.py)
    links: Optional[Dict[str, str]] = None  # строка акции -> ссылка на неё (см. extract_blocks)


def is_allowed_by_robots(url: str, user_agent: str = USER_AGENT) -> bool:
    """Проверяет разрешение robots.txt на доступ к url. При недоступности robots.txt -
    консервативно разрешает запрос (сайт может просто не публиковать robots.txt).

    robots.txt читаем с тем же честным User-Agent, что и основной запрос: у части
    сайтов WAF отдаёт 403 на запросы без нормального User-Agent (в т.ч. на дефолтный
    User-Agent, который иначе использует urllib), и голый urllib.robotparser.read()
    в этом случае трактует сайт как "запрещено всё" — ложноположительный блок.
    """
    parsed = urlparse(url)
    robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
    rp = urllib.robotparser.RobotFileParser()
    rp.set_url(robots_url)
    try:
        resp = requests.get(robots_url, headers={"User-Agent": user_agent}, timeout=REQUEST_TIMEOUT)
        if resp.status_code in (401, 403):
            rp.disallow_all = True
        elif resp.status_code >= 400:
            rp.allow_all = True
        else:
            rp.parse(resp.text.splitlines())
    except requests.RequestException as exc:  # сеть упала — не блокируем мониторинг из-за этого
        logger.warning("Не удалось прочитать %s: %s — продолжаем без ограничения robots.txt", robots_url, exc)
        return True
    return rp.can_fetch(user_agent, url)


# Настоящая промо-страница обычно весит десятки/сотни КБ HTML; challenge-страница
# антибот-системы (Cloudflare/DataDome/PerimeterX) — как правило, лёгкая заглушка.
CHALLENGE_PAGE_SIZE_THRESHOLD = 20000


def detect_antibot(html: str) -> bool:
    """Эвристика: страница похожа на challenge-страницу антибот-системы.

    DEFINITIVE_ANTIBOT_MARKERS блокируют сразу — это специфичные фразы/домены
    активного челленджа (см. их комментарий), которые не встречаются на
    настоящей промо-странице по случайности, независимо от title/размера.

    Обычный ANTIBOT_MARKERS-маркер в <title> считаем однозначным блоком.
    Маркер где-то в теле страницы (например, само упоминание "datadome" в
    баннере cookie-согласия как названия одного из используемых сайтом
    cookie, или виджет reCAPTCHA в футере, не относящийся к нашему запросу) —
    недостаточно надёжен сам по себе на большой полноценной странице, поэтому
    там дополнительно смотрим на размер страницы: классический
    (не встроенный, см. выше) challenge почти всегда компактный.
    """
    if not html:
        return False
    lowered = html.lower()

    if any(marker in lowered for marker in DEFINITIVE_ANTIBOT_MARKERS):
        return True

    matched = [marker for marker in ANTIBOT_MARKERS if marker in lowered]
    if not matched:
        return False

    title_match = re.search(r"<title[^>]*>(.*?)</title>", lowered, re.DOTALL)
    title = title_match.group(1) if title_match else ""
    if any(marker in title for marker in matched):
        return True

    return len(html) < CHALLENGE_PAGE_SIZE_THRESHOLD


def extract_block_text(block) -> str:
    """Текст промо-блока. Некоторые сайты (напр. elitbet.bg) рисуют акции как
    баннеры-картинки без текста в DOM — в этом случае используем src/srcset
    вложенных <img> как отпечаток контента: смена акции обычно означает
    загрузку нового файла баннера с новым именем/URL, так что сравнение
    по-прежнему ловит изменение, просто без читаемого diff текста."""
    # " ".join(split()) — блок всегда ровно одна строка: текст карточки может
    # содержать внутренние переводы строк из исходной вёрстки, а ниже строка
    # используется как ключ для ссылки на акцию (см. extract_blocks), и
    # одна акция не должна распадаться на несколько строк отчёта.
    text = " ".join(block.get_text(separator=" ", strip=True).split())
    if text:
        return text

    images = list(block.find_all("img")) if hasattr(block, "find_all") else []
    if getattr(block, "name", None) == "img":
        images.append(block)
    sources = [img.get("src") or img.get("data-src") or "" for img in images]
    return " ".join(s for s in sources if s)


# Ссылки на вход/регистрацию внутри промо-карточки (кнопка "Вход" на 8888.bg и
# т.п.) — это не ссылка на саму акцию, их пропускаем.
_AUTH_PATH_RE = re.compile(r"(^|/)(login|log-in|signin|sign-in|register|registration|signup|sign-up)(/|$)", re.I)


def _candidate_hrefs(block) -> Iterator[str]:
    if getattr(block, "name", None) == "a" and block.get("href"):
        yield block["href"]
    if hasattr(block, "find_all"):
        for anchor in block.find_all("a", href=True):
            yield anchor["href"]
    parent = block.find_parent("a", href=True) if hasattr(block, "find_parent") else None
    if parent is not None:
        yield parent["href"]


def _page_key(url: str) -> Tuple[str, str]:
    parsed = urlparse(url)
    return parsed.netloc.lower(), parsed.path.rstrip("/")


def extract_block_link(block, base_url: str) -> Optional[str]:
    """Ссылка на конкретную акцию из промо-блока или None, если её нет.

    Сайты делятся на два типа: у части (inbet/winbet/sesame) сама карточка —
    <a> с deep-link на страницу акции; у остальных карточка открывается
    JS-обработчиком (button/div/Angular-компонент) и адреса акции в разметке
    просто нет. Ссылку на сам список акций (адрес страницы, которую мы и так
    мониторим) и ссылки на вход/регистрацию за "ссылку на акцию" не считаем —
    для них отчёт подставит общий fallback на страницу промоций сайта.
    Принимаются только http(s): содержимое чужих сайтов, javascript: и т.п.
    в отчёт не попадёт."""
    base_key = _page_key(base_url)
    for href in _candidate_hrefs(block):
        href = (href or "").strip()
        if not href or href.startswith("#"):
            continue
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        if _AUTH_PATH_RE.search(parsed.path):
            continue
        if _page_key(absolute) == base_key:
            continue
        return absolute
    return None


def extract_blocks(blocks, base_url: str) -> Tuple[str, Dict[str, str]]:
    """Текст всех блоков (по строке на блок) + карта "текст строки -> ссылка на акцию".

    Ссылки возвращаются отдельно от текста намеренно: текст идёт в хэш/diff,
    и смена одного только URL не должна считаться изменением акции. Ключ
    карты — сама строка блока: у двух блоков с одинаковым полным текстом
    акция одна и та же, берётся первая найденная ссылка."""
    lines: List[str] = []
    links: Dict[str, str] = {}
    for block in blocks:
        line = extract_block_text(block)
        lines.append(line)
        if not line or line in links:
            continue
        link = extract_block_link(block, base_url)
        if link:
            links[line] = link
    return "\n".join(lines), links
