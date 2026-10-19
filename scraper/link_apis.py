"""Адреса акций из JSON, которым сайт сам подгружает список акций.

У MrBit/Betano/AdmiralBet/efbet карточка открывается JS-обработчиком — <a href>
в разметке нет, но сама страница получает список акций вместе с адресами из
API (иначе она не смогла бы по клику перейти куда нужно). Playwright уже
открыл страницу, поэтому достаточно перехватить этот ответ: никаких лишних
запросов к сайту и никаких кликов по сотне карточек (а в каруселях часть
слайдов вообще не кликабельна — их не видно).

Каждый сайт отдаёт свою структуру, поэтому у каждого свой небольшой разбор.
Все разборы возвращают [(название акции, абсолютный адрес)]; соответствие
названия строке карточки — match_titles_to_lines. Структуры и правила сборки
адреса сверены с реальными кликами по карточкам (а не выведены по догадке), и
сломаться могут при смене API — тогда ссылка просто не найдётся, и отчёт
вернётся к ссылке на страницу промоций, ничего не ломая."""

import logging
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
from urllib.parse import quote, urljoin

logger = logging.getLogger("promo_monitor.scraper.link_apis")

Pair = Tuple[str, str]


def _walk(node: Any) -> Iterable[Any]:
    yield node
    if isinstance(node, dict):
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from _walk(value)


def parse_admiralbet(data: Any, page_url: str) -> List[Pair]:
    """Узлы type=PromotionBanner: name — название, buttons[].navigationValue —
    путь вида /promotions/<slug> (проверено: совпадает с адресом после клика)."""
    pairs: List[Pair] = []
    for node in _walk(data):
        if not (isinstance(node, dict) and node.get("type") == "PromotionBanner"):
            continue
        title = (node.get("name") or "").strip()
        for button in node.get("buttons") or []:
            target = (button.get("navigationValue") or "").strip()
            if title and target:
                pairs.append((title, urljoin(page_url, target)))
                break
    return pairs


def parse_betano(data: Any, page_url: str) -> List[Pair]:
    """storyGroups[]: thumbnail.title — название плитки, у историй
    onClickAction.navigationUrl (или cta) — либо страница, либо панель на главной
    вида /?panel=calendar&id=13194. У части плиток адреса нет вовсе (None)."""
    pairs: List[Pair] = []
    for group in (data or {}).get("storyGroups") or []:
        title = ((group.get("thumbnail") or {}).get("title") or "").strip()
        target = ""
        for story in group.get("stories") or []:
            target = ((story.get("onClickAction") or {}).get("navigationUrl") or story.get("cta") or "").strip()
            if target:
                break
        if title and target:
            pairs.append((title, urljoin(page_url, target)))
    return pairs


def parse_mrbit(data: Any, page_url: str) -> List[Pair]:
    """payload.items[]: title — название, url — slug вида trick-or-treat-cashback-117069;
    страница акции — <страница списка>/<slug> (проверено настоящим кликом)."""
    base = page_url.rstrip("/") + "/"
    pairs: List[Pair] = []
    for item in ((data or {}).get("payload") or {}).get("items") or []:
        title = (item.get("title") or "").strip()
        slug = (item.get("url") or "").strip()
        if title and slug and not item.get("hidden"):
            pairs.append((title, urljoin(base, slug)))
    return pairs


def _efbet_segment(text: str) -> str:
    """Как у сайта: нижний регистр, пробел -> "-", остальное — как
    encodeURIComponent ("!" остаётся, "&" -> %26, "€" -> %E2%82%AC, ведущий
    пробел даёт ведущий "-"). Сверено с реальными адресами после клика, в т.ч.
    с "golden-wheel-of-fortune!" и
    "-drops-%26-wins-with-%E2%82%AC25%2C000%2C000-prize-pool"."""
    return quote(text.lower().replace(" ", "-"), safe="!'()*-_.~")


def parse_efbet(data: Any, page_url: str) -> List[Pair]:
    """Список категорий; в каждой relatedPromotions[] с title (по-болгарски, как на
    карточке) и titleEn (из него строится адрес). Акция может быть в нескольких
    категориях — берём первую (так делает и сайт: клик из "Всички" вёл в
    /promotions/casino/..., хотя акция есть и в sport)."""
    pairs: List[Pair] = []
    seen = set()
    for category in data or []:
        category_en = (category.get("nameEn") or "").strip()
        for promo in category.get("relatedPromotions") or []:
            title = (promo.get("title") or "").strip()
            title_en = promo.get("titleEn") or ""
            if not (title and title_en and category_en) or promo.get("visible") is False or title in seen:
                continue
            seen.add(title)
            path = f"/promotions/{_efbet_segment(category_en)}/{_efbet_segment(title_en)}"
            pairs.append((title, urljoin(page_url, path)))
    return pairs


PARSERS: Dict[str, Callable[[Any, str], List[Pair]]] = {
    "admiralbet": parse_admiralbet,
    "betano": parse_betano,
    "mrbit": parse_mrbit,
    "efbet": parse_efbet,
}


def parse_captured(parser: str, payloads: List[Any], page_url: str) -> List[Pair]:
    """Разбор всех перехваченных ответов выбранным парсером; ошибка разбора
    одного ответа не должна ронять прогон (сайт мог поменять API)."""
    func = PARSERS.get(parser)
    if func is None:
        logger.warning("Неизвестный разбор link_api: %r", parser)
        return []
    pairs: List[Pair] = []
    for payload in payloads:
        try:
            pairs.extend(func(payload, page_url))
        except Exception:
            logger.exception("Не удалось разобрать ответ API (%s) — ссылки из него пропущены", parser)
    return pairs


def _norm(text: str) -> str:
    return " ".join((text or "").lower().split())


def match_titles_to_lines(lines: Iterable[str], pairs: List[Pair]) -> Dict[str, str]:
    """{строка карточки: адрес}: строка получает адрес акции, чьё название в неё
    входит (при нескольких — самое длинное, чтобы короткое название не
    перехватило строку другой акции). У карточек разный состав текста (у
    MrBit перед названием стоит категория, после — описание), поэтому именно
    "входит", а не "равно"."""
    prepared = sorted(((_norm(t), u) for t, u in pairs if len(_norm(t)) >= 3), key=lambda p: -len(p[0]))
    result: Dict[str, str] = {}
    for line in lines:
        normalized = _norm(line)
        if not normalized or line in result:
            continue
        for title, url in prepared:
            if title in normalized:
                result[line] = url
                break
    return result
