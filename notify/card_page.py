"""Страница-карточка акции с текстом правил и условий.

У 8888.bg карточка акции — popup без собственного адреса, так что ссылки,
которая открывала бы её на самом сайте, не существует. Вместо картинки с
экрана (её пользователь отверг — "не скрин") бот собирает из содержимого этой
карточки обычную HTML-страницу: настоящий текст, который можно читать и
копировать, плюс настоящие ссылки сайта, найденные внутри карточки, и кнопка
на сам сайт. Лежит в docs/promo/ и уходит на публичную страницу вместе с
отчётом.

Текст берётся с сайта в момент создания страницы; имя файла содержит хэш
содержимого (см. runner.promo_card_name), поэтому страница пересоздаётся, только
когда акция изменилась, и дата на ней — дата, с которой бот видит этот текст.
"""

import html
from pathlib import Path
from typing import List, Tuple
from urllib.parse import urlparse

from .formatting import format_timestamp

_STYLE = """
  body { font-family: -apple-system, "Segoe UI", Arial, sans-serif; background:#f5f5f5; color:#1a1a1a;
         margin:0; padding:24px 16px; line-height:1.5; }
  main { max-width:760px; margin:0 auto; background:#fff; box-shadow:0 1px 3px rgba(0,0,0,.12);
         border-radius:6px; padding:28px 32px; }
  .src { font-size:12px; color:#777; text-transform:uppercase; letter-spacing:.04em; }
  h1 { font-size:22px; margin:6px 0 18px; }
  p { margin:0 0 10px; }
  h2 { font-size:14px; text-transform:uppercase; letter-spacing:.04em; color:#555; margin:26px 0 8px; }
  ul { margin:0; padding-left:20px; }
  li { margin-bottom:4px; }
  a { color:#2a5db0; }
  .dest { color:#888; font-size:12px; margin-left:6px; }
  .btn { display:inline-block; margin-top:22px; padding:10px 16px; background:#2a5db0; color:#fff;
         text-decoration:none; border-radius:5px; font-size:14px; }
  .note { margin-top:24px; padding-top:14px; border-top:1px solid #eee; font-size:12px; color:#777; }
"""


def _short_url(url: str) -> str:
    parsed = urlparse(url)
    # Конечный слэш отбрасываем, только если за ним нет параметров: "/pages/?pr=155" —
    # настоящий адрес, и подпись не должна показывать другой.
    tail = f"{parsed.path}?{parsed.query}" if parsed.query else parsed.path.rstrip("/")
    return f"{parsed.netloc}{tail}"


def build_card_page(
    out_path: Path,
    site_name: str,
    site_url: str,
    heading: str,
    body_lines: List[str],
    links: List[Tuple[str, str]],
    created_at: str,
    has_rules: bool,
) -> Path:
    """Пишет страницу-карточку. has_rules=False — у акции нет отдельной карточки с
    правилами (на сайте вся её информация лежит на самой карточке в списке) —
    тогда body_lines это текст этой карточки, и страница честно об этом говорит."""
    paragraphs = "".join(f"<p>{html.escape(line)}</p>" for line in body_lines if line.strip())
    links_block = ""
    if links:
        # Подпись ссылки в тексте карточки часто бессмысленна вне контекста ("тук!") —
        # поэтому рядом всегда показывается, куда она ведёт.
        items = "".join(
            f'<li><a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">'
            f'{html.escape(label)}</a> <span class="dest">{html.escape(_short_url(url))}</span></li>'
            for label, url in links
        )
        links_block = f"<h2>Връзки от карточката на сайта</h2><ul>{items}</ul>"

    if has_rules:
        note = (
            "Карточката на промоцията в сайта се отваря като прозорец без собствен адрес — "
            "затова тук е същият текст на правилата и условията, взет от сайта. "
            f"Текстът е актуален към {html.escape(format_timestamp(created_at))}."
        )
    else:
        note = (
            "Тази промоция няма отделна карточка с правила — на сайта цялата информация е на самата "
            "карта в списъка с бонуси, а това е нейният текст. "
            f"Актуален към {html.escape(format_timestamp(created_at))}."
        )

    document = f"""<!doctype html>
<html lang="bg">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(heading)} — {html.escape(site_name)}</title>
<style>{_STYLE}</style>
</head>
<body>
<main>
  <div class="src">{html.escape(site_name)} · Бонуси</div>
  <h1>{html.escape(heading)}</h1>
  {paragraphs}
  {links_block}
  <a class="btn" href="{html.escape(site_url, quote=True)}" target="_blank" rel="noopener noreferrer">Отвори бонусите в {html.escape(site_name)} ↗</a>
  <p class="note">{note}</p>
</main>
</body>
</html>"""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(document, encoding="utf-8")
    return out_path
