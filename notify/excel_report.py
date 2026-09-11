"""Формирование Excel-отчёта по итогам прогона (замена Telegram: отчёт + письмо)."""

import logging
from pathlib import Path
from typing import Any, Dict, List

from openpyxl import Workbook
from openpyxl.styles import Font

logger = logging.getLogger("promo_monitor.report")

COLUMNS = ["Сайт", "ID", "Статус", "Было", "Стало / детали", "Ссылка", "Время", "Скриншот"]

STATUS_LABELS = {
    "unchanged": "Без изменений",
    "changed": "Изменение промо",
    "baseline": "Первый снапшот (базовая линия)",
    "error": "Ошибка мониторинга",
    "blocked_by_antibot": "Заблокировано антибот-защитой",
    "no_selector_match": "Сломан селектор — проверь вручную",
    "robots_disallowed": "Запрещено robots.txt",
    "config_error": "Ошибка конфигурации (.env)",
    "crashed": "Необработанная ошибка",
}


def build_report(rows: List[Dict[str, Any]], out_path: Path) -> Path:
    wb = Workbook()
    ws = wb.active
    ws.title = "Промо-мониторинг"
    ws.append(COLUMNS)
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for row in rows:
        status = row.get("status", "")
        ws.append(
            [
                row.get("site_name", ""),
                row.get("site_id", ""),
                STATUS_LABELS.get(status, status),
                row.get("old_text", ""),
                row.get("new_text", ""),
                row.get("url", ""),
                row.get("timestamp", ""),
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
