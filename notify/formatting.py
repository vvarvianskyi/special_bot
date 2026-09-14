"""Общее форматирование для всех видов отчётов (Excel/HTML/письмо).

Внутри бот хранит время в UTC ISO с микросекундами — читать такое в отчёте
невозможно, поэтому наружу всё время идёт через format_timestamp().
"""

from datetime import datetime


def format_timestamp(iso_string: str) -> str:
    """"2026-09-14T09:04:33.736252+00:00" -> "14.09.2026 12:04" (местное время
    вместо сырого UTC ISO с микросекундами)."""
    try:
        return datetime.fromisoformat(iso_string).astimezone().strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return iso_string
