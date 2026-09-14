"""Точка входа.

Режимы:
  python main.py            — один прогон по всем сайтам (для запуска из
                               Планировщика заданий Windows / cron).
  python main.py --schedule — долгоживущий процесс с APScheduler: ежедневный
                               прогон в заданное время (п.3.6 ТЗ).

По итогам прогона формируется Excel-отчёт (reports/) и, если настроен SMTP
в .env, отправляется письмом. Без Telegram — бот работает локально на ПК.
"""

import argparse
import logging
import logging.handlers
import os
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
LOG_PATH = BASE_DIR / "logs" / "monitor.log"
ENV_PATH = BASE_DIR / "config" / ".env"
REPORTS_DIR = BASE_DIR / "reports"

logger = logging.getLogger("promo_monitor.main")


def setup_logging() -> None:
    # На некоторых Windows-консолях кодировка по умолчанию не покрывает все
    # символы кириллицы/типографики в логах — переключаем на UTF-8, чтобы
    # вывод в консоль не падал с UnicodeEncodeError.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    file_handler = logging.handlers.RotatingFileHandler(
        LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    root.addHandler(file_handler)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(fmt)
    root.addHandler(console_handler)


def _maybe_send_email(rows, report_path: Path) -> None:
    only_on_changes = os.environ.get("REPORT_ONLY_ON_CHANGES", "false").strip().lower() == "true"
    from scheduler.runner import NOTABLE_STATUSES

    notable = any(r["status"] in NOTABLE_STATUSES for r in rows)
    if only_on_changes and not notable:
        logger.info("Изменений/ошибок нет, письмо не отправлено (REPORT_ONLY_ON_CHANGES=true)")
        return

    smtp_host = os.environ.get("SMTP_HOST")
    if not smtp_host:
        logger.warning("SMTP не настроен в .env — письмо не отправлено, отчёт сохранён локально: %s", report_path)
        return

    from notify.email_notifier import send_report_email

    from notify.excel_report import STATUS_LABELS

    changed = sum(1 for r in rows if r["status"] == "changed")
    errors = sum(1 for r in rows if r["status"] not in ("unchanged", "changed", "baseline"))
    subject = f"Мониторинг на промоции: {changed} промени, {errors} грешки ({datetime.now():%Y-%m-%d})"
    body = "Отчётът е прикачен.\n\n" + "\n".join(
        f"{r['site_name']}: {STATUS_LABELS.get(r['status'], r['status'])}" for r in rows
    )

    smtp_user = os.environ["SMTP_USER"]
    send_report_email(
        smtp_host=smtp_host,
        smtp_port=int(os.environ.get("SMTP_PORT", "587")),
        smtp_user=smtp_user,
        smtp_password=os.environ["SMTP_PASSWORD"],
        email_from=os.environ.get("EMAIL_FROM", smtp_user),
        email_to=os.environ["EMAIL_TO"],
        subject=subject,
        body=body,
        attachment_path=report_path,
        use_tls=os.environ.get("SMTP_USE_TLS", "true").strip().lower() == "true",
    )


def run_once(stagger_seconds: int) -> None:
    from notify.excel_report import build_report
    from notify.html_report import build_html_report
    from scheduler.runner import run_all

    rows = run_all(stagger_seconds=stagger_seconds)

    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    report_path = REPORTS_DIR / f"promo_report_{datetime.now():%Y-%m-%d_%H-%M-%S}.xlsx"
    build_report(rows, report_path)

    html_path = REPORTS_DIR / "latest.html"
    build_html_report(rows, html_path)
    logger.info("HTML-отчёт обновлён: %s", html_path)

    try:
        _maybe_send_email(rows, report_path)
    except Exception:
        logger.exception("Не удалось отправить письмо с отчётом — отчёт сохранён локально: %s", report_path)

    if any(r["status"] == "changed" for r in rows):
        from notify.screen_capture import capture_report_screenshot
        from scheduler.runner import RESULTS_DIR

        screen_path = RESULTS_DIR / f"report_{datetime.now():%Y-%m-%d_%H-%M-%S}.png"
        if capture_report_screenshot(html_path, screen_path):
            logger.info("Скриншот отчёта с результатами сохранён: %s", screen_path)


def run_scheduled(stagger_seconds: int, hour: int, minute: int) -> None:
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(lambda: run_once(stagger_seconds), "cron", hour=hour, minute=minute, id="daily_run")
    logger.info("Запланирован ежедневный прогон на %02d:%02d UTC", hour, minute)
    scheduler.start()


def main() -> None:
    parser = argparse.ArgumentParser(description="Мониторинг промоакций конкурентов")
    parser.add_argument("--schedule", action="store_true", help="Запустить долгоживущий процесс с APScheduler")
    parser.add_argument(
        "--stagger-seconds",
        type=int,
        default=300,
        help="Пауза между проверками сайтов внутри одного прогона, сек (п.3.6 ТЗ: 5–10 мин)",
    )
    parser.add_argument("--hour", type=int, default=6, help="Час (UTC) ежедневного прогона (только с --schedule)")
    parser.add_argument("--minute", type=int, default=0, help="Минута ежедневного прогона (только с --schedule)")
    args = parser.parse_args()

    load_dotenv(ENV_PATH)
    setup_logging()

    if args.schedule:
        run_scheduled(args.stagger_seconds, args.hour, args.minute)
    else:
        run_once(args.stagger_seconds)


if __name__ == "__main__":
    main()
