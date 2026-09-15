"""Общее форматирование для всех видов отчётов (Excel/HTML/письмо).

Внутри бот хранит время в UTC ISO с микросекундами — читать такое в отчёте
невозможно, поэтому наружу всё время идёт через format_timestamp().
"""

from datetime import datetime, timezone
from typing import Any, Dict

# Сколько часов после реального изменения статус "Промяна" остаётся видимым
# в отчётах, даже если следующий(е) прогон(ы) уже не находят новой разницы.
# Без этого при редких проверках (например, раз в сутки) изменение легко не
# заметить: сайт меняется между двумя прогонами, один прогон честно ловит
# "changed", а на СЛЕДУЮЩЕМ прогоне статус уже тихо возвращается в
# "unchanged" — и если отчёт открыли именно после этого, разницу уже не видно.
RECENT_CHANGE_HOURS = 24


def format_timestamp(iso_string: str) -> str:
    """"2026-09-14T09:04:33.736252+00:00" -> "14.09.2026 12:04" (местное время
    вместо сырого UTC ISO с микросекундами)."""
    try:
        return datetime.fromisoformat(iso_string).astimezone().strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return iso_string


def is_within_hours(iso_string: str, hours: float) -> bool:
    """Не старше ли этот момент, чем `hours` часов назад — используется, чтобы
    держать статус "Промяна" видимым сутки после реального изменения (см.
    display_status в html_report.py/excel_report.py), а не только на том
    единственном прогоне, где diff его обнаружил."""
    if not iso_string:
        return False
    try:
        moment = datetime.fromisoformat(iso_string)
    except (ValueError, TypeError):
        return False
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - moment).total_seconds() <= hours * 3600


def display_status(row: Dict[str, Any]) -> str:
    """Статус для отображения в отчёте: "changed" держится RECENT_CHANGE_HOURS
    часов от row["last_change_at"], даже если ЭТОТ конкретный прогон снова
    видит unchanged (ничего нового с прошлого прогона). Ошибочные статусы
    (error, no_selector_match и т.п.) никогда не переопределяются — это про
    текущее состояние проверки, а не про историю изменений промо."""
    status = row.get("status", "")
    if status not in ("unchanged", "changed"):
        return status
    if is_within_hours(row.get("last_change_at", ""), RECENT_CHANGE_HOURS):
        return "changed"
    return status
