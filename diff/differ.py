"""Нормализация текста, хэширование и генерация diff (п.3.3, п.3.4 ТЗ)."""

import difflib
import hashlib
import re

# Тикающий обратный отсчёт вида "26д. 23ч. 45м." (сколько осталось до конца
# акции) — не содержательное изменение промо, а просто ход времени. Без
# вычитания он даёт ложное "изменение" почти на каждом прогоне (см. winbet.bg).
COUNTDOWN_RE = re.compile(r"\d+\s*д\.\s*\d+\s*ч\.\s*\d+\s*м\.")


def strip_countdown(text: str) -> str:
    text = COUNTDOWN_RE.sub(" ", text or "")
    return re.sub(r"[ \t]+", " ", text)


def normalize_text(text: str) -> str:
    """Вырезает тикающие таймеры и схлопывает пробелы/переносы строк, чтобы
    косметические изменения вёрстки и просто ход времени не считались
    изменением промо."""
    text = strip_countdown(text)
    return re.sub(r"\s+", " ", text).strip()


def compute_hash(text: str) -> str:
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def generate_diff(old_text: str, new_text: str) -> str:
    old_lines = strip_countdown(old_text or "").splitlines()
    new_lines = strip_countdown(new_text or "").splitlines()
    diff = difflib.unified_diff(old_lines, new_lines, lineterm="", fromfile="было", tofile="стало")
    return "\n".join(diff)


def truncate(text: str, limit: int = 300) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"
