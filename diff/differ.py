"""Нормализация текста, хэширование и генерация diff (п.3.3, п.3.4 ТЗ)."""

import difflib
import hashlib
import re


def normalize_text(text: str) -> str:
    """Схлопывает пробелы/переносы строк, чтобы косметические изменения вёрстки
    (лишний пробел, перенос строки) не считались изменением промо."""
    return re.sub(r"\s+", " ", text or "").strip()


def compute_hash(text: str) -> str:
    normalized = normalize_text(text)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def generate_diff(old_text: str, new_text: str) -> str:
    old_lines = (old_text or "").splitlines()
    new_lines = (new_text or "").splitlines()
    diff = difflib.unified_diff(old_lines, new_lines, lineterm="", fromfile="было", tofile="стало")
    return "\n".join(diff)


def truncate(text: str, limit: int = 300) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"
