"""Загрузка сохранённых сессий/логинов для auth_required-сайтов.

Бот НЕ создаёт и не удаляет аккаунты сам (п.2 ограничений ТЗ). Учётные данные
(cookies или логин/пароль) заводятся вручную человеком и хранятся только в .env,
откуда этот модуль их читает по префиксу auth_env_prefix из sites.yaml.
"""

import logging
import os
from typing import Dict, Optional

logger = logging.getLogger("promo_monitor.scraper.auth")


def get_auth_credentials(prefix: str) -> Dict[str, Optional[str]]:
    """Возвращает {"cookies": str|None, "login": str|None, "password": str|None}
    для указанного префикса из переменных окружения (.env)."""
    return {
        "cookies": os.environ.get(f"{prefix}_COOKIES") or None,
        "login": os.environ.get(f"{prefix}_LOGIN") or None,
        "password": os.environ.get(f"{prefix}_PASSWORD") or None,
    }


def parse_cookie_header(cookie_str: str) -> Dict[str, str]:
    """Разбирает строку вида 'name1=value1; name2=value2' в словарь для requests/Playwright."""
    cookies = {}
    for part in cookie_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        cookies[name.strip()] = value.strip()
    return cookies


def require_credentials(site_id: str, prefix: Optional[str]) -> Dict[str, Optional[str]]:
    if not prefix:
        raise ValueError(
            f"Сайт {site_id}: access=auth_required, но auth_env_prefix не задан в sites.yaml"
        )
    creds = get_auth_credentials(prefix)
    if not creds["cookies"] and not (creds["login"] and creds["password"]):
        raise ValueError(
            f"Сайт {site_id}: не найдены ни {prefix}_COOKIES, ни пара "
            f"{prefix}_LOGIN/{prefix}_PASSWORD в .env. Заведите аккаунт вручную "
            f"и сохраните данные согласно README."
        )
    logger.debug("Сайт %s: учётные данные для %s загружены из .env", site_id, prefix)
    return creds
