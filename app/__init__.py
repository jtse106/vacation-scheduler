import os

from flask import Flask

from .db import ensure_seed_data, init_db
from .routes import register_routes


def create_app() -> Flask:
    app = Flask(__name__, instance_relative_config=False)
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY", "dev-vacation-scheduler-secret"),
        DATABASE=os.environ.get("DATABASE_PATH", "app/data/vacation_scheduler.db"),
        MAX_DAILY_VACATION_SLOTS=int(os.environ.get("MAX_DAILY_VACATION_SLOTS", 6)),
        SMTP_HOST=os.environ.get("SMTP_HOST", ""),
        SMTP_PORT=int(os.environ.get("SMTP_PORT", 587)),
        SMTP_USERNAME=os.environ.get("SMTP_USERNAME", ""),
        SMTP_PASSWORD=os.environ.get("SMTP_PASSWORD", ""),
        SMTP_FROM=os.environ.get("SMTP_FROM", "Vacation Scheduler <no-reply@example.com>"),
    )

    init_db(app)
    ensure_seed_data(app)
    register_routes(app)
    return app
