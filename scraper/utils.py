"""Общие утилиты для скраперов: robots.txt, детект антибот-защиты, тип результата."""

import logging
import re
import urllib.robotparser
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

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
    text = block.get_text(separator=" ", strip=True)
    if text:
        return text

    images = list(block.find_all("img")) if hasattr(block, "find_all") else []
    if getattr(block, "name", None) == "img":
        images.append(block)
    sources = [img.get("src") or img.get("data-src") or "" for img in images]
    return " ".join(s for s in sources if s)
