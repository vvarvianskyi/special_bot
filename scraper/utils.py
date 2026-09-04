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
    "verify you are human",
    "please verify you are a human",
)


@dataclass
class FetchResult:
    status: str  # "ok" | "no_selector_match" | "blocked_by_antibot" | "robots_disallowed" | "error"
    text: Optional[str] = None
    error: Optional[str] = None


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

    Маркер в <title> считаем однозначным блоком. Маркер где-то в теле страницы
    (например, само упоминание "datadome" в баннере cookie-согласия как названия
    одного из используемых сайтом cookie) — недостаточно надёжен сам по себе на
    большой полноценной странице, поэтому там дополнительно смотрим на размер
    страницы: настоящий challenge почти всегда компактный.
    """
    if not html:
        return False
    lowered = html.lower()
    matched = [marker for marker in ANTIBOT_MARKERS if marker in lowered]
    if not matched:
        return False

    title_match = re.search(r"<title[^>]*>(.*?)</title>", lowered, re.DOTALL)
    title = title_match.group(1) if title_match else ""
    if any(marker in title for marker in matched):
        return True

    return len(html) < CHALLENGE_PAGE_SIZE_THRESHOLD
