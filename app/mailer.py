import base64
import smtplib
from email.message import EmailMessage

from flask import current_app
import requests

from .db import execute_db, record_activity


def _gmail_api_result(message: EmailMessage):
    client_id = (current_app.config.get("GMAIL_CLIENT_ID") or "").strip()
    client_secret = (current_app.config.get("GMAIL_CLIENT_SECRET") or "").strip()
    refresh_token = (current_app.config.get("GMAIL_REFRESH_TOKEN") or "").strip()
    if not any([client_id, client_secret, refresh_token]):
        return None
    if not all([client_id, client_secret, refresh_token]):
        return {
            "status": "logged-only",
            "error": "Incomplete Gmail API credentials. Set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, and GMAIL_REFRESH_TOKEN to enable Gmail delivery.",
        }

    try:
        token_response = requests.post(
            current_app.config.get("GMAIL_TOKEN_URL", "https://oauth2.googleapis.com/token"),
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=20,
        )
        token_response.raise_for_status()
        access_token = token_response.json()["access_token"]
        raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode().rstrip("=")
        send_response = requests.post(
            current_app.config.get("GMAIL_SEND_URL", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"),
            headers={"Authorization": f"Bearer {access_token}"},
            json={"raw": raw_message},
            timeout=20,
        )
        send_response.raise_for_status()
        return {"status": "sent", "error": ""}
    except Exception as exc:  # pragma: no cover - network-specific behavior
        return {"status": "error", "error": str(exc)}


def send_email(*, to_email: str, subject: str, body: str, purpose: str, user_id=None, request_id=None):
    smtp_host = (current_app.config.get("SMTP_HOST") or "").strip()
    smtp_port = int(current_app.config.get("SMTP_PORT", 587))
    smtp_username = (current_app.config.get("SMTP_USERNAME") or "").strip()
    smtp_password = (current_app.config.get("SMTP_PASSWORD") or "").strip()
    from_address = current_app.config.get("GMAIL_FROM") or current_app.config.get("SMTP_FROM", "gmittendorf+VLCalendar@gmail.com")

    status = "logged-only"
    error_text = ""
    provider = "log-only"
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = from_address
    message["To"] = to_email
    message.set_content(body)

    gmail_result = _gmail_api_result(message)
    if gmail_result is not None:
        status = gmail_result["status"]
        error_text = gmail_result["error"]
        provider = "gmail-api"
    elif smtp_host and smtp_username and smtp_password:
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
            provider = "smtp"
        except Exception as exc:  # pragma: no cover - network-specific behavior
            status = "error"
            error_text = str(exc)
            provider = "smtp"

    execute_db(
        """
        INSERT INTO email_log (user_id, request_id, purpose, recipient, subject, body, delivery_status, error_text)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (user_id, request_id, purpose, to_email, subject, body, status, error_text),
    )
    record_activity(
        None,
        f"email-{status}",
        f"Email {status} for {purpose} to {to_email}.",
        "vacation_request" if request_id else "user",
        request_id or user_id,
        changes=[
            {"field_name": "purpose", "old_value": None, "new_value": purpose},
            {"field_name": "recipient", "old_value": None, "new_value": to_email},
            {"field_name": "subject", "old_value": None, "new_value": subject},
            {"field_name": "delivery_status", "old_value": None, "new_value": status},
            {"field_name": "delivery_provider", "old_value": None, "new_value": provider},
            {"field_name": "from_address", "old_value": None, "new_value": from_address},
            {"field_name": "body", "old_value": None, "new_value": body},
            {"field_name": "error_text", "old_value": None, "new_value": error_text},
            {"field_name": "gmail_client_id_present", "old_value": None, "new_value": bool((current_app.config.get('GMAIL_CLIENT_ID') or '').strip())},
            {"field_name": "gmail_client_secret_present", "old_value": None, "new_value": bool((current_app.config.get('GMAIL_CLIENT_SECRET') or '').strip())},
            {"field_name": "gmail_refresh_token_present", "old_value": None, "new_value": bool((current_app.config.get('GMAIL_REFRESH_TOKEN') or '').strip())},
            {"field_name": "smtp_host_present", "old_value": None, "new_value": bool(smtp_host)},
            {"field_name": "smtp_username_present", "old_value": None, "new_value": bool(smtp_username)},
            {"field_name": "smtp_password_present", "old_value": None, "new_value": bool(smtp_password)},
        ],
    )
    return {"status": status, "error": error_text}
