"""Локальный HTML-отчёт (reports/latest.html) — открывается двойным кликом в
браузере, без сервера. Обновляется поверх одного и того же файла на каждом
прогоне, чтобы всегда было куда "зайти и посмотреть" текущее состояние."""

import html
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from .excel_report import STATUS_LABELS

STATUS_COLORS = {
    "unchanged": "#4a7a4a",
    "changed": "#b8860b",
    "baseline": "#4a6a9a",
    "error": "#b03a3a",
    "blocked_by_antibot": "#b03a3a",
    "no_selector_match": "#b03a3a",
    "robots_disallowed": "#7a7a7a",
    "config_error": "#b03a3a",
    "crashed": "#b03a3a",
}


def _format_multiline(text: str) -> str:
    """Каждая строка акции — отдельный блок с отступом, а не слипшийся текст
    (было: white-space:pre-wrap без интервалов между пунктами списка)."""
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    return "".join(f'<div class="line">{html.escape(line)}</div>' for line in lines)


def _format_timestamp(iso_string: str) -> str:
    """"2026-09-14T09:04:33.736252+00:00" -> "14.09.2026 12:04" (местное время
    вместо сырого UTC ISO с микросекундами)."""
    try:
        return datetime.fromisoformat(iso_string).astimezone().strftime("%d.%m.%Y %H:%M")
    except (ValueError, TypeError):
        return iso_string


def _badge(status: str) -> str:
    label = html.escape(STATUS_LABELS.get(status, status))
    color = STATUS_COLORS.get(status, "#7a7a7a")
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:10px;font-size:12px;white-space:nowrap">{label}</span>'
    )


def build_html_report(rows: List[Dict[str, Any]], out_path: Path, include_screenshots: bool = True) -> Path:
    """include_screenshots=False — для публичной версии (GitHub Pages/шаринг):
    скриншоты лежат локально на диске (Desktop\\Result), file:// ссылки на них
    ни у кого, кроме этого ПК, не откроются, так что там их просто не показываем."""
    generated_at = rows[0]["timestamp"] if rows else ""

    body_rows = []
    for row in rows:
        site_name = html.escape(row.get("site_name", ""))
        url = html.escape(row.get("url", ""))
        old_text = _format_multiline(row.get("old_text", ""))
        new_text = _format_multiline(row.get("new_text", ""))
        timestamp = html.escape(_format_timestamp(row.get("timestamp", "")))

        screenshot_cell = ""
        screenshot_path = row.get("screenshot_path")
        if include_screenshots and screenshot_path:
            try:
                uri = html.escape(Path(screenshot_path).as_uri())
                screenshot_cell = (
                    f'<a href="{uri}" target="_blank" rel="noopener">'
                    f'<img src="{uri}" alt="скрийншот" '
                    f'style="max-width:160px;max-height:100px;border:1px solid #ddd;border-radius:4px"></a>'
                )
            except ValueError:
                pass

        screenshot_td = f"\n          <td>{screenshot_cell}</td>" if include_screenshots else ""
        body_rows.append(
            f"""
        <tr>
          <td><a href="{url}" target="_blank" rel="noopener">{site_name}</a></td>
          <td>{_badge(row.get("status", ""))}</td>
          <td class="text-cell">{old_text}</td>
          <td class="text-cell">{new_text}</td>{screenshot_td}
          <td class="ts">{timestamp}</td>
        </tr>"""
        )

    screenshot_th = "<th>Скрийншот</th>" if include_screenshots else ""
    html_doc = f"""<!doctype html>
<html lang="bg">
<head>
<meta charset="utf-8">
<title>Мониторинг на промоции на конкуренти</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", Arial, sans-serif; background:#f5f5f5;
          color:#1a1a1a; margin:0; padding:24px; }}
  h1 {{ font-size:20px; margin:0 0 4px; }}
  .meta {{ color:#666; font-size:13px; margin-bottom:20px; }}
  table {{ width:100%; border-collapse:collapse; background:#fff; box-shadow:0 1px 3px rgba(0,0,0,.1); }}
  th, td {{ text-align:left; padding:10px 12px; border-bottom:1px solid #eee; vertical-align:top; font-size:13px; }}
  th {{ background:#fafafa; font-size:12px; text-transform:uppercase; letter-spacing:.03em; color:#666; }}
  td.text-cell {{ max-width:360px; word-break:break-word; color:#333; }}
  td.text-cell .line {{ padding-block:4px; }}
  td.text-cell .line + .line {{ border-top:1px solid #f0efe9; }}
  td.ts {{ white-space:nowrap; color:#888; font-size:12px; }}
  a {{ color:#2a5db0; text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
</style>
</head>
<body>
  <h1>Мониторинг на промоции на конкуренти</h1>
  <div class="meta">Последна проверка: {html.escape(_format_timestamp(generated_at))}</div>
  <table>
    <thead>
      <tr><th>Сайт</th><th>Статус</th><th>Преди</th><th>Сега / детайли</th>{screenshot_th}<th>Час</th></tr>
    </thead>
    <tbody>
      {''.join(body_rows)}
    </tbody>
  </table>
</body>
</html>"""

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html_doc, encoding="utf-8")
    return out_path
