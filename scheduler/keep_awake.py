"""Не даёт Windows усыпить ПК, пока идёт прогон.

Планировщик заданий будит ПК на запуск (WakeToRun), но это разовое действие —
дальше система засыпает по обычному таймауту бездействия точно так же, как
если бы никто её не будил. Таймаут бездействия Windows считает по последнему
вводу с клавиатуры/мыши, а не по тому, что в фоне работает процесс — поэтому
незалогиненный, никем не трогаемый прогон бота ничем не отличается для
Windows от простоя, и ПК может уйти в сон на середине прогона (см. лог событий
Kernel-Power 17.09: сон уже через 32 секунды после пробуждения по будильнику).

Решение — явно попросить Windows не спать на время прогона через
SetThreadExecutionState (стандартный Win32 API для этого, не требует прав
администратора). Не трогает настройки самого пользователя/системы — только
держит один явный запрос "не спать" на время работы этого процесса и снимает
его на выходе, после чего обычный таймаут бездействия снова действует как
обычно (весь остальной день ПК спит как настроено — экономия энергии не
теряется, "не спать" держится ровно на время прогона)."""

import logging
import sys
from contextlib import contextmanager

logger = logging.getLogger("promo_monitor.keep_awake")

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001


@contextmanager
def prevent_sleep():
    if sys.platform != "win32":
        yield
        return

    import ctypes

    applied = False
    try:
        result = ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)
        applied = bool(result)
        if applied:
            logger.info("Сон ПК заблокирован на время прогона (SetThreadExecutionState)")
        else:
            logger.warning("Не удалось запросить блокировку сна — SetThreadExecutionState вернул 0")
    except Exception:
        logger.exception("Не удалось запросить блокировку сна — прогон продолжается как есть")

    try:
        yield
    finally:
        if applied:
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS)
                logger.info("Блокировка сна снята — ПК спит по обычному расписанию")
            except Exception:
                logger.exception("Не удалось снять блокировку сна")
