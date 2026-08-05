"""Sends the daily summary email via SMTP (Gmail App Password by default)."""
import os
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path

from src.logging_setup import get_logger

logger = get_logger(__name__)


def send_email(subject: str, html_body: str, markdown_path: str | None = None):
    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_pass = os.environ["SMTP_PASS"]
    to_addrs = [a.strip() for a in os.environ["EMAIL_TO"].split(",") if a.strip()]

    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = smtp_user
    msg["To"] = ", ".join(to_addrs)

    msg.attach(MIMEText(html_body, "html"))

    if markdown_path and Path(markdown_path).exists():
        with open(markdown_path, "rb") as f:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(f.read())
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{Path(markdown_path).name}"')
        msg.attach(part)

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to_addrs, msg.as_string())
        logger.info("Email sent to %s", to_addrs)
    except Exception as e:
        logger.error("Failed to send email: %s", e)
        raise
