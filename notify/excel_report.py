"""Формирование Excel-отчёта по итогам прогона (замена Telegram: отчёт + письмо)."""

import logging
from pathlib import Path
from typing import Any, Dict, List

from openpyxl import Workbook
from openpyxl.styles import Font

from .formatting import display_status, format_timestamp

logger = logging.getLogger("promo_monitor.report")

# Отчёты (Excel/HTML/письма) на болгарском — по требованию заказчика,
# т.к. результаты предназначены для болгароязычной команды/теста.
COLUMNS = [
    "Сайт",
    "ID",
    "Статус",
    "Последна промяна",
    "Преди",
    "Преди — от",
    "Сега / детайли",
    "Сега — от",
    "Връзка",
    "Час",
    "Скрийншот",
]

STATUS_LABELS = {
    "unchanged": "Без промяна",
    "changed": "Промяна в промоцията",
    "baseline": "Първи снапшот (база за сравнение)",
    "error": "Грешка при проверката",
    "blocked_by_antibot": "Блокирано от анти-бот защита",
    "no_selector_match": "Развален селектор — провери ръчно",
    "robots_disallowed": "Забранено от robots.txt",
    "config_error": "Грешка в конфигурацията (.env)",
    "crashed": "Необработена грешка",
}


def build_report(rows: List[Dict[str, Any]], out_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Промо мониторинг"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for row in rows:
        # "Промяна" держится 24ч от последнего реального изменения (см.
        # formatting.display_status) — не только на том единственном прогоне,
        # где сама разница была найдена, иначе при редких проверках отчёт
        # легко открыть уже ПОСЛЕ того, как статус тихо вернулся в "Без
        # промяна", и пропустить, что изменение вообще было.
        status = display_status(row)
        ws.append(
            [
                row.get("site_name", ""),
                row.get("site_id", ""),
                STATUS_LABELS.get(status, status),
                format_timestamp(row.get("last_change_at", "")),
                row.get("old_text", ""),
                format_timestamp(row.get("old_since", "")),
                row.get("new_text", ""),
                format_timestamp(row.get("new_since", "")),
                row.get("url", ""),
                format_timestamp(row.get("timestamp", "")),
                row.get("screenshot_path", ""),
            ]
        )

    for column_cells in ws.columns:
        length = max((len(str(cell.value)) if cell.value else 0) for cell in column_cells)
        ws.column_dimensions[column_cells[0].column_letter].width = min(max(length + 2, 10), 60)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out_path)
    logger.info("Отчёт сохранён: %s", out_path)
    return out_path
