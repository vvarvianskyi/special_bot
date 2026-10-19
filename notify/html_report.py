"""Локальный HTML-отчёт (reports/latest.html) — открывается двойным кликом в
браузере, без сервера. Обновляется поверх одного и того же файла на каждом
прогоне, чтобы всегда было куда "зайти и посмотреть" текущее состояние."""

import html
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from .excel_report import STATUS_LABELS
from .formatting import display_status, format_timestamp

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


def _is_http_url(url: str) -> bool:
    return url.lower().startswith(("http://", "https://"))


def _format_details(line: str, description: str, fallback_url: str) -> str:
    """Строка акции, раскрывающаяся в полное описание (нативный <details>, без JS
    — работает и в локальном файле, и на GitHub Pages).

    Для сайтов, где у карточки нет URL (popup без смены адреса) отдельной
    ссылкой на неё не поделишься — зато описание можно показать здесь же."""
    paragraphs = "".join(f"<p>{html.escape(p)}</p>" for p in description.splitlines() if p.strip())
    site_link = ""
    if fallback_url and _is_http_url(fallback_url):
        site_link = (
            f'<p class="promo-site-link"><a href="{html.escape(fallback_url, quote=True)}" '
            f'target="_blank" rel="noopener noreferrer">Към страницата с промоциите на сайта ↗</a></p>'
        )
    return (
        f'<div class="line"><details class="promo"><summary>{html.escape(line)}</summary>'
        f'<div class="promo-detail">{paragraphs}{site_link}</div></details></div>'
    )


def _format_multiline(
    text: str,
    links: Dict[str, str] = None,
    fallback_url: str = "",
    details: Dict[str, str] = None,
) -> str:
    """Каждая строка акции — отдельный блок с отступом, а не слипшийся текст
    (было: white-space:pre-wrap без интервалов между пунктами списка).

    Строка становится ссылкой: на саму акцию, если сайт отдал её адрес
    (links), иначе — на страницу промоций сайта (fallback_url): у части сайтов
    карточка открывается JS-обработчиком и адреса акции в разметке просто нет.
    Если для строки есть полное описание (details — сайты, где карточка это
    popup без URL), она раскрывается в это описание на месте.
    Без fallback_url (ошибочные статусы — там "строки" это текст ошибки, а не
    акции) такие строки остаются обычным текстом."""
    links = links or {}
    details = details or {}
    lines = [line.strip() for line in (text or "").splitlines() if line.strip()]
    if not lines:
        return ""
    parts = []
    for line in lines:
        if fallback_url and details.get(line):
            parts.append(_format_details(line, details[line], fallback_url))
            continue
        escaped = html.escape(line)
        own_link = links.get(line)
        target = own_link or fallback_url
        if target and _is_http_url(target):
            title = "" if own_link else ' title="Към страницата с промоциите на сайта"'
            parts.append(
                f'<div class="line"><a href="{html.escape(target, quote=True)}" '
                f'target="_blank" rel="noopener noreferrer"{title}>{escaped}</a></div>'
            )
        else:
            parts.append(f'<div class="line">{escaped}</div>')
    return "".join(parts)


def _format_cell(
    text: str,
    since: str,
    links: Dict[str, str] = None,
    fallback_url: str = "",
    details: Dict[str, str] = None,
) -> str:
    """Текст версии промо + с какой даты она стоит на сайте.

    Дата берётся не из времени проверки (бот ходит каждый час), а из момента
    появления этой версии — чтобы было видно "старая акция висела с 01.09,
    новая появилась 14.09", а не "проверено час назад" в обеих колонках."""
    body = _format_multiline(text, links, fallback_url, details)
    if not since:
        return body
    return f'<div class="since">от {html.escape(format_timestamp(since))}</div>{body}'


def _badge(status: str) -> str:
    label = html.escape(STATUS_LABELS.get(status, status))
    color = STATUS_COLORS.get(status, "#7a7a7a")
    return (
        f'<span style="background:{color};color:#fff;padding:2px 8px;'
        f'border-radius:10px;font-size:12px;white-space:nowrap">{label}</span>'
    )


def _status_cell(row: Dict[str, Any]) -> str:
    last_change_at = row.get("last_change_at", "")
    badge = _badge(display_status(row))
    if not last_change_at:
        return badge
    return (
        f'{badge}<div class="last-change">Последна промяна:<br>'
        f'{html.escape(format_timestamp(last_change_at))}</div>'
    )


def build_html_report(rows: List[Dict[str, Any]], out_path: Path, include_screenshots: bool = True) -> Path:
    """include_screenshots=False — для публичной версии (GitHub Pages/шаринг):
    скриншоты лежат локально на диске (Desktop\\Result), file:// ссылки на них
    ни у кого, кроме этого ПК, не откроются, так что там их просто не показываем."""
    # НЕ rows[0]["timestamp"] — это момент проверки ПЕРВОГО сайта в списке
    # (c8888), а прогон растянут по стаггеру на ~45 минут для 10 сайтов.
    # Шапка "Последна проверка" должна отвечать на вопрос "насколько свежа
    # эта страница", а не "когда проверился самый первый сайт" — иначе она
    # всегда выглядит устаревшей почти на час, даже сразу после публикации.
    generated_at = datetime.now(timezone.utc).isoformat()

    body_rows = []
    for row in rows:
        site_name = html.escape(row.get("site_name", ""))
        url = html.escape(row.get("url", ""))
        # Строки колонок — акции только при успешной проверке; при ошибке в
        # "Сега" лежит текст ошибки, его кликабельным делать нельзя.
        fetched_ok = row.get("status") in ("unchanged", "changed", "baseline")
        fallback_url = row.get("url", "") if fetched_ok else ""
        new_links = row.get("new_links") or {}
        # В "Преди" берём ссылки из старого снапшота, а где их там не сохранено
        # (снапшот до появления ссылок или акция осталась прежней) — из текущих.
        old_links = {**new_links, **(row.get("old_links") or {})}
        # Описания есть только у текущих акций; для строк "Преди", которые
        # остались прежними, подходят те же (совпадение по тексту строки).
        details = row.get("new_details") or {}
        old_text = _format_cell(row.get("old_text", ""), row.get("old_since", ""), old_links, fallback_url, details)
        new_text = _format_cell(row.get("new_text", ""), row.get("new_since", ""), new_links, fallback_url, details)
        timestamp = html.escape(format_timestamp(row.get("timestamp", "")))

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
          <td>{_status_cell(row)}</td>
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
  td.text-cell .line a {{ display:block; }}
  td.text-cell details.promo summary {{ color:#2a5db0; cursor:pointer; }}
  td.text-cell details.promo summary:hover {{ text-decoration:underline; }}
  td.text-cell .promo-detail {{ margin:6px 0 4px; padding:8px 10px; background:#f7f6f2;
                                border-left:3px solid #d9d6cb; border-radius:3px;
                                font-size:12px; color:#444; }}
  td.text-cell .promo-detail p {{ margin:0 0 6px; }}
  td.text-cell .promo-detail .promo-site-link {{ margin:8px 0 0; }}
  td.text-cell .line + .line {{ border-top:1px solid #f0efe9; }}
  td.text-cell .since {{ display:inline-block; margin-bottom:8px; padding:2px 8px;
                         background:#f0efe9; border-radius:10px; color:#6b6b6b;
                         font-size:11px; white-space:nowrap; }}
  td.ts {{ white-space:nowrap; color:#888; font-size:12px; }}
  .last-change {{ margin-top:6px; color:#888; font-size:11px; line-height:1.4; white-space:nowrap; }}
  a {{ color:#2a5db0; text-decoration:none; }}
  a:hover {{ text-decoration:underline; }}
</style>
</head>
<body>
  <h1>Мониторинг на промоции на конкуренти</h1>
  <div class="meta">Последна проверка: {html.escape(format_timestamp(generated_at))}</div>
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
