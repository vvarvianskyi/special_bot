"""Fetch для render: js — рендеринг через Playwright (headless), когда промо-блок
подгружается JS-виджетом. Это штатный рендеринг контента, а не обход защиты
(см. п.2 ограничений ТЗ) — никаких stealth-плагинов, ротации прокси или решения капч.
"""

import logging
import time
from typing import Dict, Optional

from .utils import (
    MAX_RETRIES,
    REQUEST_TIMEOUT,
    USER_AGENT,
    FetchResult,
    detect_antibot,
    is_allowed_by_robots,
)

logger = logging.getLogger("promo_monitor.scraper.js")


def fetch_js(url: str, selector: str, cookies: Optional[Dict[str, str]] = None) -> FetchResult:
    if not is_allowed_by_robots(url):
        logger.warning("robots.txt запрещает доступ к %s — пропускаем", url)
        return FetchResult(status="robots_disallowed", error="Запрещено robots.txt")

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return FetchResult(
            status="error",
            error="Playwright не установлен. Установите: pip install playwright && playwright install chromium",
        )

    last_error = None
    for attempt in range(MAX_RETRIES + 1):
        try:
            html, screenshot = _render_page(url, cookies, selector)
            break
        except Exception as exc:  # таймауты, навигационные ошибки Playwright
            last_error = str(exc)
            logger.warning("Попытка %d/%d (JS) для %s не удалась: %s", attempt + 1, MAX_RETRIES + 1, url, exc)
            if attempt < MAX_RETRIES:
                time.sleep(2)
    else:
        return FetchResult(status="error", error=last_error or "Неизвестная ошибка рендеринга")

    if detect_antibot(html):
        return FetchResult(status="blocked_by_antibot", error="Обнаружена антибот-защита (challenge-страница)")

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.select(selector)
    if not blocks:
        return FetchResult(status="no_selector_match", error=f"Селектор '{selector}' не нашёл ни одного блока")

    text = "\n".join(block.get_text(separator=" ", strip=True) for block in blocks)
    return FetchResult(status="ok", text=text, screenshot=screenshot)


def _render_page(url: str, cookies: Optional[Dict[str, str]], selector: str):
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(user_agent=USER_AGENT)
        if cookies:
            from urllib.parse import urlparse

            domain = urlparse(url).netloc
            context.add_cookies(
                [
                    {"name": name, "value": value, "domain": domain, "path": "/"}
                    for name, value in cookies.items()
                ]
            )
        page = context.new_page()
        # "networkidle" не подходит для сайтов live-ставок/казино: у них почти
        # всегда идёт фоновый поллинг коэффициентов, и networkidle просто никогда
        # не наступает. Ждём загрузки DOM, а затем — конкретно промо-блок: на
        # некоторых сайтах (palmsbet.bg) он дорендеривается заметно дольше
        # фиксированных 2-3 секунд, из-за чего блок не успевал подгрузиться.
        page.goto(url, timeout=REQUEST_TIMEOUT * 1000, wait_until="domcontentloaded")
        try:
            page.wait_for_selector(selector, timeout=15000)
        except Exception:
            logger.debug("Селектор '%s' не появился за 15с — парсим то, что успело отрендериться", selector)

        html = page.content()

        # Скриншот промо-блока для визуальной сверки при обнаруженном изменении
        # (см. runner.py). Если у селектора несколько совпадений — берём первое;
        # если сам блок почему-то не сфотографировать (не в DOM/невидим) —
        # подстраховываемся скриншотом всей страницы, лишь бы не терять снимок.
        screenshot = None
        try:
            screenshot = page.locator(selector).first.screenshot(timeout=5000)
        except Exception:
            try:
                screenshot = page.screenshot(full_page=True, timeout=10000)
            except Exception:
                logger.debug("Не удалось сделать скриншот для %s", url)

        browser.close()
        return html, screenshot
