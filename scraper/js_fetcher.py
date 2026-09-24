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
    extract_block_text,
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

    from bs4 import BeautifulSoup

    last_error = None
    rendered_but_empty = False  # рендер хоть раз прошёл успешно, но блок не нашёлся
    antibot_seen = False  # ...и хотя бы раз это сопровождалось маркером антибота
    for attempt in range(MAX_RETRIES + 1):
        try:
            html, screenshot = _render_page(url, cookies, selector)
        except Exception as exc:  # таймауты, навигационные ошибки Playwright
            last_error = str(exc)
            logger.warning("Попытка %d/%d (JS) для %s не удалась: %s", attempt + 1, MAX_RETRIES + 1, url, exc)
            if attempt < MAX_RETRIES:
                time.sleep(2)
            continue

        soup = BeautifulSoup(html, "html.parser")
        blocks = soup.select(selector)
        if blocks:
            # Реальный контент найден — значит, страница точно не заблокирована,
            # независимо от того, что где-то на ней (например, в скрипте формы
            # входа) может упоминаться Cloudflare Turnstile. detect_antibot
            # здесь намеренно НЕ проверяем: у него самого есть широкие маркеры
            # (recaptcha, datadome...), которые легко встретить на совершенно
            # рабочей странице по не связанной с блокировкой причине (см. ниже).
            text = "\n".join(extract_block_text(block) for block in blocks)
            return FetchResult(status="ok", text=text, screenshot=screenshot)

        # Пустой результат — тут уже стоит спросить detect_antibot, ПОЧЕМУ:
        # либо блок на этом прогоне отрисовался медленнее, чем wait_for_selector
        # внутри _render_page (см. palmsbet.com — раньше это давало ложный
        # no_selector_match), либо страницу реально закрывает антибот-чэлендж
        # (тоже видели на palmsbet.com — просто в другой раз). Проверять маркеры
        # ТОЛЬКО здесь, а не до селектора — иначе страницы, где Cloudflare
        # Turnstile просто подключён скриптом для формы входа/регистрации, но
        # промо-контент на месте (inbet/winbet/sesame — тот же общий движок),
        # ложно помечались бы заблокированными.
        rendered_but_empty = True
        if detect_antibot(html):
            antibot_seen = True
            last_error = "Обнаружена антибот-защита (challenge-страница)"
        else:
            last_error = f"Селектор '{selector}' не нашёл ни одного блока"
        logger.warning("Попытка %d/%d (JS) для %s: %s", attempt + 1, MAX_RETRIES + 1, url, last_error)
        if attempt < MAX_RETRIES:
            time.sleep(2)

    if antibot_seen:
        return FetchResult(status="blocked_by_antibot", error=last_error)
    if rendered_but_empty:
        return FetchResult(status="no_selector_match", error=last_error)
    return FetchResult(status="error", error=last_error or "Неизвестная ошибка рендеринга")


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
