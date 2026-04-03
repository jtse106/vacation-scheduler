import smtplib
from email.message import EmailMessage

from flask import current_app

from .db import execute_db


def send_email(*, to_email: str, subject: str, body: str, purpose: str, user_id=None, request_id=None):
    smtp_host = (current_app.config.get("SMTP_HOST") or "").strip()
    smtp_port = int(current_app.config.get("SMTP_PORT", 587))
    smtp_username = (current_app.config.get("SMTP_USERNAME") or "").strip()
    smtp_password = (current_app.config.get("SMTP_PASSWORD") or "").strip()

    status = "logged-only"
    error_text = ""
    if smtp_host and smtp_username and smtp_password:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = current_app.config.get("SMTP_FROM", "gmittendorf+VLCalendar@gmail.com")
        message["To"] = to_email
        message.set_content(body)
        try:
            if smtp_port == 465:
                with smtplib.SMTP_SSL(smtp_host, smtp_port) as server:
                    server.login(smtp_username, smtp_password)
                    server.send_message(message)
            else:
                with smtplib.SMTP(smtp_host, smtp_port) as server:
                    server.starttls()
                    server.login(smtp_username, smtp_password)
                    server.send_message(message)
            status = "sent"
        except Exception as exc:  # pragma: no cover - network-specific behavior
            status = "error"
            error_text = str(exc)

    execute_db(
        """
        INSERT INTO email_log (user_id, request_id, purpose, recipient, subject, body, delivery_status, error_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, request_id, purpose, to_email, subject, body, status, error_text),
    )
    return {"status": status, "error": error_text}
