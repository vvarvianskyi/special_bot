"""Отправка Excel-отчёта на почту по SMTP."""

import logging
import smtplib
from email.message import EmailMessage
from pathlib import Path

logger = logging.getLogger("promo_monitor.notify.email")

XLSX_MIME_SUBTYPE = "vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def send_report_email(
    smtp_host: str,
    smtp_port: int,
    smtp_user: str,
    smtp_password: str,
    email_from: str,
    email_to: str,
    subject: str,
    body: str,
    attachment_path: Path,
    use_tls: bool = True,
) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = email_from
    msg["To"] = email_to
    msg.set_content(body)

    with open(attachment_path, "rb") as f:
        data = f.read()
    msg.add_attachment(
        data,
        maintype="application",
        subtype=XLSX_MIME_SUBTYPE,
        filename=attachment_path.name,
    )

    if use_tls:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
    else:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as server:
            server.login(smtp_user, smtp_password)
            server.send_message(msg)

    logger.info("Отчёт отправлен на %s", email_to)
