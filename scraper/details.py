"""Полное описание акции для сайтов, где у карточки нет собственного URL.

Часть сайтов (8888.bg) открывает акцию popup'ом без смены адреса: ссылкой на
такую акцию не поделишься и из отчёта на неё не перейдёшь. Зато само описание
сайт подгружает отдельным запросом при клике — его и берём, чтобы отчёт мог
показать полный текст акции на месте (см. html_report: раскрывающаяся строка).

Это тот же запрос, который делает страница сайта при клике посетителя, а не
обход защиты: проверяем robots.txt, представляемся честным User-Agent, ходим
последовательно с паузами и сдаёмся после нескольких неудач подряд. Любая
ошибка здесь не должна ломать прогон — описание просто не появится в отчёте.
"""

import logging
import time
from typing import Any, Dict
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from .utils import REQUEST_TIMEOUT, USER_AGENT, is_allowed_by_robots

logger = logging.getLogger("promo_monitor.scraper.details")

PAUSE_BETWEEN_REQUESTS = 0.7  # сек
MAX_CONSECUTIVE_FAILURES = 3
MAX_DETAILS_PER_RUN = 60  # страховка от внезапного разрастания списка акций


def html_fragment_to_text(fragment: str, content_selector: str = "", drop_selectors=()) -> str:
    """Читаемый текст из HTML-фрагмента: по строке на абзац/пункт/строку таблицы.

    Голый get_text("\\n") тут не годится — он режет inline-теги ("Минимальная
    ставка – <strong>10</strong> евро" превращается в три строки), поэтому
    inline-теги разворачиваются, <br> становится переводом строки, а строка
    таблицы склеивается в одну через " — "."""
    soup = BeautifulSoup(fragment or "", "html.parser")
    for tag in soup.find_all(["script", "style", "svg", "img"]):
        tag.decompose()
    root = soup.select_one(content_selector) if content_selector else soup
    if root is None:
        # Нет контейнера описания — значит, ответ не про эту акцию: у карточки
        # может не быть своего popup'а (8888.bg: LIVE-акция с единственной
        # ссылкой на /login/ — эндпоинт на её id отдаёт обычную страницу
        # сайта целиком). Откатываться на "весь фрагмент" нельзя: в отчёт
        # попали бы меню и футер вместо описания.
        return ""
    for selector in drop_selectors:
        for tag in root.select(selector):
            tag.decompose()

    for br in root.find_all("br"):
        br.replace_with("\n")
    for row in root.find_all("tr"):
        cells = [" ".join(cell.get_text(" ", strip=True).split()) for cell in row.find_all(["td", "th"])]
        row.replace_with(soup.new_string("\n" + " — ".join(c for c in cells if c) + "\n"))
    for tag in root.find_all(["strong", "b", "em", "i", "span", "a", "u", "font"]):
        tag.unwrap()
    if hasattr(root, "smooth"):
        root.smooth()  # склеить соседние строки, оставшиеся после unwrap

    lines = []
    for raw in root.get_text("\n").splitlines():
        line = " ".join(raw.split())
        if line and (not lines or lines[-1] != line):
            lines.append(line)
    return "\n".join(lines)


def fetch_details(ids: Dict[str, str], cfg: Dict[str, Any]) -> Dict[str, str]:
    """{строка акции: полный текст акции} для ids ({строка акции: id на сайте}).

    cfg (секция `details` в sites.yaml): url — шаблон с {id}, content_selector
    — где в ответе описание, drop_selectors — что из него выкинуть (например,
    дубль баннера). Ответ — JSON {"html": "..."} либо сразу HTML."""
    if not ids or not cfg.get("url"):
        return {}
    template = cfg["url"]
    items = list(ids.items())[:MAX_DETAILS_PER_RUN]

    first_url = template.format(id=quote(items[0][1]))
    if not is_allowed_by_robots(first_url):
        logger.warning("robots.txt запрещает %s — описания акций не загружаем", first_url)
        return {}

    details: Dict[str, str] = {}
    failures = 0
    for index, (line, promo_id) in enumerate(items):
        url = template.format(id=quote(promo_id))
        try:
            resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
            try:
                fragment = resp.json().get("html", "")
            except ValueError:
                fragment = resp.text
            text = html_fragment_to_text(fragment, cfg.get("content_selector", ""), cfg.get("drop_selectors", ()))
            if text:
                details[line] = text
                failures = 0
            else:
                # Штатный случай, не ошибка: у части карточек своего описания нет
                # (8888.bg: LIVE-акция, клик по которой лишь просит войти).
                logger.info("У акции нет описания по %s — остаётся обычной строкой", url)
        except (requests.RequestException, AttributeError) as exc:
            failures += 1
            logger.warning("Не удалось получить описание акции %s: %s", url, exc)
            if failures >= MAX_CONSECUTIVE_FAILURES:
                logger.warning("%d неудач подряд — остальные описания пропускаем", failures)
                break
        if index < len(items) - 1:
            time.sleep(PAUSE_BETWEEN_REQUESTS)
    return details
