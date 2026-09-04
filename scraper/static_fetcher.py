"""Fetch для render: static — обычный HTTP GET + BeautifulSoup."""

import logging
import time
from typing import Dict, Optional

import requests
from bs4 import BeautifulSoup

from .utils import (
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    USER_AGENT,
    FetchResult,
    detect_antibot,
    is_allowed_by_robots,
)

logger = logging.getLogger("promo_monitor.scraper.static")


def fetch_static(url: str, selector: str, cookies: Optional[Dict[str, str]] = None) -> FetchResult:
    if not is_allowed_by_robots(url):
        logger.warning("robots.txt запрещает доступ к %s — пропускаем", url)
        return FetchResult(status="robots_disallowed", error="Запрещено robots.txt")

    headers = {"User-Agent": USER_AGENT}
    last_error = None

    for attempt in range(MAX_RETRIES + 1):
        try:
            resp = requests.get(
                url,
                headers=headers,
                cookies=cookies,
                timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            html = resp.text
            break
        except requests.RequestException as exc:
            last_error = str(exc)
            logger.warning("Попытка %d/%d для %s не удалась: %s", attempt + 1, MAX_RETRIES + 1, url, exc)
            if attempt < MAX_RETRIES:
                time.sleep(2)
    else:
        return FetchResult(status="error", error=last_error or "Неизвестная ошибка запроса")

    if detect_antibot(html):
        return FetchResult(status="blocked_by_antibot", error="Обнаружена антибот-защита (challenge-страница)")

    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.select(selector)
    if not blocks:
        return FetchResult(status="no_selector_match", error=f"Селектор '{selector}' не нашёл ни одного блока")

    text = "\n".join(block.get_text(separator=" ", strip=True) for block in blocks)
    return FetchResult(status="ok", text=text)
