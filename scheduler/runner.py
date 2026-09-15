"""Оркестрация: для каждого сайта — fetch -> diff -> save (п.3, п.4 ТЗ).

Результат прогона — список строк для Excel-отчёта, который затем main.py
отправляет письмом (см. notify/excel_report.py, notify/email_notifier.py).

Ошибка на одном сайте не должна валить весь прогон (п.7 ТЗ) — каждый сайт
обрабатывается в своём try/except.
"""

import logging
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from diff.differ import compute_hash, generate_diff, truncate
from scraper.auth_session import parse_cookie_header, require_credentials
from scraper.js_fetcher import fetch_js
from scraper.static_fetcher import fetch_static
from storage.db import (
    DEFAULT_DB_PATH,
    Snapshot,
    get_last_snapshot,
    get_version_since,
    init_db,
    save_snapshot,
)

logger = logging.getLogger("promo_monitor.runner")

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"
DEFAULT_SITES_PATH = CONFIG_DIR / "sites.yaml"

# Скриншот промо-блока сохраняется сюда только при реальном изменении акции —
# чтобы можно было визуально сверить, что именно поменялось на сайте.
RESULTS_DIR = Path.home() / "Desktop" / "Result"

# Статусы, которые не считаются "без изменений" — используются, чтобы решить,
# стоит ли слать письмо, если включён REPORT_ONLY_ON_CHANGES.
NOTABLE_STATUSES = {
    "changed",
    "error",
    "blocked_by_antibot",
    "no_selector_match",
    "config_error",
    "crashed",
}

# Пауза перед повторной проверкой сайтов, упавших с сетевой ошибкой (см.
# run_all) — не мгновенный ретрай, а расчёт на то, что нестабильный
# интернет/DNS сам восстановится за пару минут.
RETRY_PASS_DELAY_SECONDS = 120


def load_sites(path: Path = DEFAULT_SITES_PATH) -> List[Dict[str, Any]]:
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return data.get("sites", [])


def _resolve_cookies(site: Dict[str, Any]) -> Optional[Dict[str, str]]:
    if site.get("access") != "auth_required":
        return None
    prefix = site.get("auth_env_prefix")
    creds = require_credentials(site["id"], prefix)
    if creds["cookies"]:
        return parse_cookie_header(creds["cookies"])
    # Логин/пароль без готовых cookies: автоматический логин на форме сайта
    # специфичен для каждого сайта и не входит в общий MVP-флоу (см. README).
    # Проще и надёжнее — один раз вручную получить cookies залогиненной
    # сессии и положить их в .env.
    raise ValueError(
        f"Сайт {site['id']}: задан {prefix}_LOGIN/{prefix}_PASSWORD, но не "
        f"{prefix}_COOKIES. Автологин через форму не реализован (специфичен "
        f"для каждого сайта) — сохраните cookies залогиненной вручную сессии "
        f"в {prefix}_COOKIES."
    )


def _save_screenshot(site_id: str, timestamp: str, screenshot: Optional[bytes]) -> Optional[Path]:
    if not screenshot:
        return None
    safe_ts = timestamp.replace(":", "-")
    path = RESULTS_DIR / f"{site_id}_{safe_ts}.png"
    try:
        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(screenshot)
        return path
    except OSError:
        logger.exception("Не удалось сохранить скриншот в %s", path)
        return None


def process_site(site: Dict[str, Any], db_path: Path) -> Dict[str, Any]:
    """Обрабатывает один сайт целиком. Возвращает строку для отчёта."""
    site_id = site["id"]
    site_name = site.get("name", site_id)
    url = site["url"]
    selector = site["selector"]
    render = site.get("render", "static")
    now = datetime.now(timezone.utc).isoformat()

    row: Dict[str, Any] = {
        "site_id": site_id,
        "site_name": site_name,
        "url": url,
        "timestamp": now,
        "old_text": "",
        "new_text": "",
        # "Преди" — дата последнего РЕАЛЬНОГО изменения (когда появилась версия
        # в колонке "Преди"); проставляется ниже, только когда есть с чем
        # сравнивать. "Сега / детайли" — дата последней ПРОВЕРКИ бота, поэтому
        # она всегда равна текущему прогону и нигде дальше не переопределяется.
        "old_since": "",
        "new_since": now,
        # Когда текущая (актуальная прямо сейчас) версия промо реально
        # появилась — единое поле независимо от status ниже. Отчёты держат
        # бейдж "Промяна" видимым 24ч от этого момента (см. formatting.py:
        # is_within_hours), чтобы редкие проверки не давали пропустить
        # изменение, если отчёт открыли уже после того, как статус на
        # следующем прогоне вернулся в "Без промяна".
        "last_change_at": "",
    }

    try:
        cookies = _resolve_cookies(site)
    except ValueError as exc:
        logger.error(str(exc))
        row["status"] = "config_error"
        row["new_text"] = str(exc)
        return row

    fetcher = fetch_js if render == "js" else fetch_static
    result = fetcher(url, selector, cookies=cookies)

    if result.status != "ok":
        logger.warning("%s: %s (%s)", site_id, result.status, result.error)
        row["status"] = result.status
        row["new_text"] = result.error or ""
        return row

    new_text = result.text
    new_hash = compute_hash(new_text)
    last = get_last_snapshot(site_id, db_path)

    # Считаем ДО save_snapshot: после вставки нового снапшота "последним
    # другим хэшем" станет текущий, и дата появления старой версии потеряется.
    since = get_version_since(site_id, last.hash, db_path) if last is not None else None

    if last is not None and last.hash == new_hash:
        logger.info("%s: изменений нет", site_id)
        save_snapshot(Snapshot(site_id=site_id, timestamp=now, raw_text=new_text, hash=new_hash), db_path)
        row["status"] = "unchanged"
        row["old_text"] = truncate(last.raw_text, 300)
        row["new_text"] = truncate(new_text, 300)
        # Изменений нет — "Преди" показывает, с какой даты висит эта (та же
        # самая) версия. "Сега" остаётся дефолтным now: даже без изменений
        # бот только что её проверил.
        row["old_since"] = since or ""
        row["last_change_at"] = since or ""
        return row

    if last is not None:
        diff_text = generate_diff(last.raw_text, new_text)
        logger.info("%s: обнаружено изменение промо\n%s", site_id, diff_text)
        row["status"] = "changed"
        row["old_text"] = truncate(last.raw_text, 300)
        row["new_text"] = truncate(new_text, 300)
        # "Преди" — с какой даты висела старая версия (когда сменилась в
        # последний раз до этого). "Сега" — дефолтный now (см. выше).
        row["old_since"] = since or ""
        row["last_change_at"] = now  # это и есть момент изменения
        screenshot_path = _save_screenshot(site_id, now, result.screenshot)
        if screenshot_path:
            row["screenshot_path"] = str(screenshot_path)
            logger.info("%s: скриншот изменения сохранён в %s", site_id, screenshot_path)
    else:
        logger.info("%s: первый снапшот сохранён (базовая линия)", site_id)
        row["status"] = "baseline"
        row["new_text"] = truncate(new_text, 300)
        # Нет предыдущей версии для сравнения — "Преди" остаётся пустым.

    save_snapshot(Snapshot(site_id=site_id, timestamp=now, raw_text=new_text, hash=new_hash), db_path)
    return row


def run_all(
    sites_path: Path = DEFAULT_SITES_PATH,
    db_path: Optional[Path] = None,
    stagger_seconds: int = 0,
) -> List[Dict[str, Any]]:
    db_path = db_path or DEFAULT_DB_PATH
    init_db(db_path)

    sites = load_sites(sites_path)
    rows: List[Dict[str, Any]] = []
    for index, site in enumerate(sites):
        site_id = site.get("id", f"<unknown_{index}>")
        try:
            rows.append(process_site(site, db_path))
        except Exception:
            logger.exception("%s: необработанная ошибка при обработке сайта — пропускаем и идём дальше", site_id)
            rows.append(
                {
                    "site_id": site_id,
                    "site_name": site.get("name", site_id),
                    "url": site.get("url", ""),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "status": "crashed",
                    "old_text": "",
                    "new_text": "",
                }
            )
        if stagger_seconds and index < len(sites) - 1:
            time.sleep(stagger_seconds)

    # Короткая повторная попытка для сайтов с сетевой ошибкой (error) —
    # большинство таких сбоев это секунды-минуты нестабильного интернета на
    # самом ПК (DNS/таймаут), а не реальная недоступность сайта конкурента.
    # process_site уже делает 1 повтор почти сразу (см. MAX_RETRIES в
    # scraper/utils.py) — этого достаточно для мгновенного сбоя, но не для
    # сбоя длиной в пару минут. Даём ещё один шанс после паузы, прежде чем
    # показывать ошибку в отчёте на весь час до следующего прогона.
    #
    # НЕ трогаем no_selector_match/blocked_by_antibot/config_error/
    # robots_disallowed/crashed — там ждать бессмысленно (либо нужна ручная
    # проверка, либо повтор даст тот же результат).
    error_indices = [i for i, r in enumerate(rows) if r.get("status") == "error"]
    if error_indices:
        retry_site_ids = [rows[i]["site_id"] for i in error_indices]
        logger.info(
            "Повторная проверка через %dс для сайтов с сетевой ошибкой: %s",
            RETRY_PASS_DELAY_SECONDS,
            retry_site_ids,
        )
        time.sleep(RETRY_PASS_DELAY_SECONDS)
        for i in error_indices:
            site = sites[i]
            try:
                retried_row = process_site(site, db_path)
            except Exception:
                logger.exception("%s: необработанная ошибка при повторной проверке", site.get("id", i))
                continue
            if retried_row["status"] != "error":
                logger.info("%s: повторная проверка удалась (%s)", site["id"], retried_row["status"])
            else:
                logger.info("%s: повторная проверка снова не удалась — оставляем error", site["id"])
            rows[i] = retried_row

    logger.info("Итог прогона: %s", {r["site_id"]: r["status"] for r in rows})
    return rows
