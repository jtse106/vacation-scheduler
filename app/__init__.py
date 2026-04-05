import os

from dotenv import load_dotenv
from flask import Flask
from werkzeug.middleware.proxy_fix import ProxyFix

from .db import ensure_seed_data, init_db
from .routes import register_routes


def create_app() -> Flask:
    load_dotenv()

    app = Flask(__name__, instance_relative_config=False)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-vacation-scheduler-secret"),
        DATABASE=os.environ.get("DATABASE_PATH", "app/data/vacation_scheduler.db"),
        MAX_DAILY_VACATION_SLOTS=int(os.environ.get("MAX_DAILY_VACATION_SLOTS", 6)),
        SMTP_HOST=os.environ.get("SMTP_HOST", ""),
        SMTP_PORT=int(os.environ.get("SMTP_PORT", 587)),
        SMTP_USERNAME=os.environ.get("SMTP_USERNAME", ""),
        SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD", ""),
        SMTP_FROM=os.environ.get("SMTP_FROM", "gmittendorf+VLCalendar@gmail.com"),
        GMAIL_CLIENT_ID=os.environ.get("GMAIL_CLIENT_ID", os.environ.get("gmail_credentials", "")),
        GMAIL_CLIENT_SECRET=os.environ.get("GMAIL_CLIENT_SECRET", ""),
        GMAIL_REFRESH_TOKEN=os.environ.get("GMAIL_REFRESH_TOKEN", ""),
        GMAIL_FROM=os.environ.get("GMAIL_FROM", os.environ.get("SMTP_FROM", "gmittendorf+VLCalendar@gmail.com")),
        GMAIL_TOKEN_URL=os.environ.get("GMAIL_TOKEN_URL", "https://oauth2.googleapis.com/token"),
        GMAIL_SEND_URL=os.environ.get("GMAIL_SEND_URL", "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"),
        ZEN_API_KEY=os.environ.get("ZEN_API_KEY", os.environ.get("zen_api_key", "")),
        ZEN_API_URL=os.environ.get("ZEN_API_URL", "https://opencode.ai/zen/v1/responses"),
        ZEN_MODEL=os.environ.get(
            "ZEN_MODEL",
            os.environ.get("MODEL_ID", os.environ.get("model_ID", "gpt-5.4-nano")),
        ),
    )
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)

    init_db(app)
    ensure_seed_data(app)
    register_routes(app)
    return app
