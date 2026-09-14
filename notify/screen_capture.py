"""Скриншот отчёта (не экрана целиком!) — сохраняется только если были
реальные изменения промо (см. main.py).

Важно: это не захват физического экрана (ImageGrab), потому что при
автоматическом/фоновом запуске на экране в момент завершения скрипта может
быть что угодно (браузер, другое окно) — а не терминал с отчётом. Вместо
этого рендерим сам HTML-отчёт (reports/latest.html) через headless Playwright
и снимаем скриншот его содержимого — так на картинке гарантированно именно
результаты прогона, а не случайный кадр рабочего стола.
"""

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger("promo_monitor.screen")


def capture_report_screenshot(html_path: Path, out_path: Path) -> Optional[Path]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright не установлен — скриншот отчёта не сделан")
        return None

    if not html_path.exists():
        logger.warning("HTML-отчёт %s не найден — скриншот не сделан", html_path)
        return None

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 800})
            page.goto(html_path.resolve().as_uri())
            out_path.parent.mkdir(parents=True, exist_ok=True)
            page.screenshot(path=str(out_path), full_page=True)
            browser.close()
        return out_path
    except Exception:
        logger.exception("Не удалось сделать скриншот отчёта")
        return None
