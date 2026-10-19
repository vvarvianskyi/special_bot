"""Снимок итогового блока акции для сайтов, где у карточки нет своего URL.

8888.bg открывает акцию popup'ом без смены адреса — ссылкой на неё не поделишься
(проверено: в 46 JS-файлах сайта нет открытия popup по параметру адреса).
Единственный способ "дойти до конца" — открыть popup в браузере и снять
получившийся блок. Снимок лежит рядом с отчётом, и клик по акции в отчёте
открывает его.

Снимается ТОЛЬКО то, чего ещё нет на диске: имя файла содержит хэш содержимого
акции (см. runner.promo_shot_name), поэтому картинка пересоздаётся, лишь когда
акция реально изменилась. Иначе каждый прогон давал бы новые байты (таймеры,
анимации) и репозиторий с публичной страницей рос бы на мегабайты в сутки.

Любая ошибка здесь не должна ломать прогон — акция просто останется без снимка
и в отчёте откроется иначе (см. html_report)."""

import logging
from pathlib import Path
from typing import Any, Dict

from .utils import REQUEST_TIMEOUT, USER_AGENT, is_allowed_by_robots

logger = logging.getLogger("promo_monitor.scraper.popup_shots")

VIEWPORT_WIDTH = 1280
VIEWPORT_HEIGHT = 900
MAX_VIEWPORT_HEIGHT = 6000  # страховка: popup с нестандартно длинным текстом
JPEG_QUALITY = 75


def capture_popup_shots(
    url: str,
    selector: str,
    id_attr: str,
    cfg: Dict[str, Any],
    wanted: Dict[str, Path],
) -> Dict[str, Path]:
    """Снимает popup акций. wanted = {id акции на сайте: путь файла}; возвращает
    {id: путь} для реально снятых.

    cfg: open_selector — кликабельный элемент внутри карточки; ready_selector —
    что появляется, когда popup загрузился; popup_selector — что снимать;
    id_selector — элемент внутри popup'а с атрибутом id_attr (сверка, что открыт
    именно запрошенный popup, а не остаток предыдущего)."""
    if not wanted:
        return {}
    if not is_allowed_by_robots(url):
        logger.warning("robots.txt запрещает %s — снимки popup'ов пропущены", url)
        return {}
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.warning("Playwright не установлен — снимки popup'ов пропущены")
        return {}

    from .js_fetcher import _dismiss_cookie_banner

    open_selector = cfg.get("open_selector", "a")
    ready_selector = cfg["ready_selector"]
    popup_selector = cfg["popup_selector"]
    id_selector = cfg.get("id_selector", f"[{id_attr}]")

    shots: Dict[str, Path] = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=USER_AGENT, viewport={"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT}
            )
            page = context.new_page()
            page.goto(url, timeout=REQUEST_TIMEOUT * 1000, wait_until="domcontentloaded")
            _dismiss_cookie_banner(page)
            page.wait_for_selector(selector, timeout=20000)
            page.wait_for_timeout(2500)  # фреймворк сайта навешивает обработчики на карточки не мгновенно

            for promo_id, path in wanted.items():
                try:
                    card = page.locator(f'{selector}[{id_attr}="{promo_id}"]').first
                    opener = card.locator(open_selector)
                    if opener.count() == 0:
                        # Штатный случай: у части карточек popup'а нет (8888.bg: LIVE-акция,
                        # клик по которой лишь просит войти). Не ждём таймаут впустую.
                        logger.info("У акции %s нет popup'а — снимать нечего", promo_id)
                        continue
                    # dispatch_event, а не click(): карточки лежат в карусели, и обычный
                    # клик мышью по ним "съедается" — карусель принимает его за
                    # перетаскивание (проверено: click() не вызывал popup, dispatch — всегда).
                    opener.first.dispatch_event("click")
                    _wait_for_popup_of(page, ready_selector, id_selector, id_attr, promo_id)

                    popup = page.locator(popup_selector).first
                    height = popup.evaluate("el => Math.ceil(el.scrollHeight)")
                    # Popup прокручивается внутри окна: растягиваем окно на всю высоту
                    # содержимого, иначе снимок отрежет всё, что ниже первого экрана.
                    page.set_viewport_size(
                        {"width": VIEWPORT_WIDTH, "height": min(max(height + 60, VIEWPORT_HEIGHT), MAX_VIEWPORT_HEIGHT)}
                    )
                    page.wait_for_timeout(400)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    popup.screenshot(path=str(path), type="jpeg", quality=JPEG_QUALITY)
                    shots[promo_id] = path
                except Exception as exc:
                    logger.warning("Не удалось снять popup акции %s: %s", promo_id, str(exc).splitlines()[0][:150])
                finally:
                    try:
                        page.set_viewport_size({"width": VIEWPORT_WIDTH, "height": VIEWPORT_HEIGHT})
                    except Exception:
                        pass
                    # Открытый popup НЕ заменяется кликом по другой карточке (проверено:
                    # остаётся предыдущая акция) — закрываем после каждого снимка.
                    _close_popup(page, ready_selector, cfg.get("close_selector", ""))
            browser.close()
    except Exception:
        logger.exception("Снимки popup'ов не удались — акции останутся без снимков")
    return shots


def _wait_for_popup_of(page, ready_selector: str, id_selector: str, id_attr: str, promo_id: str) -> None:
    """Ждёт, пока popup откроется именно для promo_id. Escape его не закрывает, и
    после предыдущей акции на экране остаётся её popup — без сверки id мы бы
    сняли чужое содержимое и сохранили под именем этой акции."""
    page.wait_for_selector(ready_selector, state="visible", timeout=10000)
    deadline_ms = 8000
    step_ms = 250
    waited = 0
    while waited <= deadline_ms:
        current = page.evaluate(
            """([ready, idSel, attr]) => {
                const root = document.querySelector(ready);
                const el = root && root.querySelector(idSel);
                return el ? el.getAttribute(attr) : null;
            }""",
            [ready_selector, id_selector, id_attr],
        )
        if current == promo_id:
            page.wait_for_timeout(300)  # дорисовка картинок/шрифтов
            return
        page.wait_for_timeout(step_ms)
        waited += step_ms
    raise RuntimeError(f"popup не показал акцию {promo_id} за {deadline_ms // 1000}с")


def _close_popup(page, ready_selector: str, close_selector: str) -> None:
    """Закрывает открытый popup: Escape, а если он не скрылся — клик по кнопке
    закрытия. Признак "закрыт" — скрытое содержимое, а не пропавший класс
    active у оверлея: он остаётся и после закрытия (из-за этого первая версия
    проверки считала закрытый popup открытым)."""
    for attempt in ("escape", "button"):
        try:
            if attempt == "escape":
                page.keyboard.press("Escape")
            elif close_selector:
                page.locator(close_selector).first.dispatch_event("click")
            else:
                break
            page.wait_for_selector(ready_selector, state="hidden", timeout=3000)
            return
        except Exception:
            continue
    logger.warning("Popup не закрылся — следующие снимки могут показать предыдущую акцию")
