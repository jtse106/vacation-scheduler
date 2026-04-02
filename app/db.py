import hashlib
import hmac
import secrets
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from flask import current_app, g

from .excel_import import import_seed_data


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'physician',
    is_active INTEGER NOT NULL DEFAULT 1,
    deleted_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER PRIMARY KEY,
    week_start TEXT NOT NULL DEFAULT 'sunday',
    show_week_numbers INTEGER NOT NULL DEFAULT 0,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vacation_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    request_display_name TEXT,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'requested',
    request_note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at TEXT,
    processed_by INTEGER,
    decision_note TEXT,
    canceled_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (processed_by) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS holiday_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS notification_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    request_id INTEGER NOT NULL,
    channel TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    delivery_status TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (request_id) REFERENCES vacation_requests(id) ON DELETE CASCADE
);
"""


def init_db(app):
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        db = get_db()
        with closing(db.cursor()) as cursor:
            cursor.executescript(SCHEMA)
            existing_user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}
            if "deleted_at" not in existing_user_columns:
                cursor.execute("ALTER TABLE users ADD COLUMN deleted_at TEXT")
            existing_request_columns = {row["name"] for row in db.execute("PRAGMA table_info(vacation_requests)").fetchall()}
            if "request_display_name" not in existing_request_columns:
                cursor.execute("ALTER TABLE vacation_requests ADD COLUMN request_display_name TEXT")
                cursor.execute(
                    """
                    UPDATE vacation_requests
                    SET request_display_name = (
                        SELECT users.full_name FROM users WHERE users.id = vacation_requests.user_id
                    )
                    WHERE request_display_name IS NULL
                    """
                )
        db.commit()


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


def close_db(_=None):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query_db(query, params=(), one=False):
    cur = get_db().execute(query, params)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def execute_db(query, params=()):
    db = get_db()
    cur = db.execute(query, params)
    db.commit()
    return cur.lastrowid


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200000)
    return f"{salt}${digest.hex()}"


def verify_password(password: str, password_hash: str) -> bool:
    salt, digest = password_hash.split("$", 1)
    candidate = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 200000)
    return hmac.compare_digest(candidate.hex(), digest)


def daterange(start_value: str, end_value: str):
    current = date.fromisoformat(start_value)
    end = date.fromisoformat(end_value)
    while current <= end:
        yield current.isoformat()
        current += timedelta(days=1)


def request_sort_key(row):
    return (row["created_at"], row["id"])


def active_request_statuses():
    return ("requested", "confirmed", "unavailable")


def overlapping_requests(day_iso: str):
    placeholders = ",".join("?" for _ in active_request_statuses())
    return query_db(
        f"""
        SELECT vr.*, COALESCE(vr.request_display_name, u.full_name) AS full_name, u.username, u.email
        FROM vacation_requests vr
        LEFT JOIN users u ON u.id = vr.user_id
        WHERE vr.start_date <= ?
          AND vr.end_date >= ?
          AND vr.status IN ({placeholders})
        ORDER BY vr.created_at ASC, vr.id ASC
        """,
        (day_iso, day_iso, *active_request_statuses()),
    )


def request_rank_for_day(request_id: int, day_iso: str) -> Optional[int]:
    rows = overlapping_requests(day_iso)
    for index, row in enumerate(rows, start=1):
        if row["id"] == request_id:
            return index
    return None


def request_is_eligible(request_row) -> bool:
    max_slots = current_app.config["MAX_DAILY_VACATION_SLOTS"]
    for day_iso in daterange(request_row["start_date"], request_row["end_date"]):
        rank = request_rank_for_day(request_row["id"], day_iso)
        if rank is None or rank > max_slots:
            return False
    return True


def log_notification(user_id: int, request_id: int, subject: str, body: str, delivery_status: str):
    execute_db(
        """
        INSERT INTO notification_log (user_id, request_id, channel, subject, body, delivery_status)
        VALUES (?, ?, 'email', ?, ?, ?)
        """,
        (user_id, request_id, subject, body, delivery_status),
    )


def maybe_send_approval_email(request_row):
    subject = "Vacation approved"
    body = (
        f"Hello {request_row['full_name']},\n\n"
        f"Your vacation request for {request_row['start_date']} through {request_row['end_date']} "
        "has moved into the top 6 and is now approved."
    )
    smtp_host = current_app.config.get("SMTP_HOST", "").strip()
    if smtp_host:
        import smtplib
        from email.message import EmailMessage

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = current_app.config["SMTP_FROM"]
        msg["To"] = request_row["email"]
        msg.set_content(body)

        with smtplib.SMTP(smtp_host, current_app.config.get("SMTP_PORT", 587)) as server:
            server.starttls()
            username = current_app.config.get("SMTP_USERNAME", "").strip()
            password = current_app.config.get("SMTP_PASSWORD", "").strip()
            if username:
                server.login(username, password)
            server.send_message(msg)
        log_notification(request_row["user_id"], request_row["id"], subject, body, "sent")
    else:
        log_notification(request_row["user_id"], request_row["id"], subject, body, "logged-only")


def recalculate_request_statuses():
    rows = query_db(
        """
        SELECT vr.*, u.full_name, u.email
        FROM vacation_requests vr
        LEFT JOIN users u ON u.id = vr.user_id
        WHERE vr.status != 'withdrawn'
        ORDER BY vr.created_at ASC, vr.id ASC
        """
    )

    for row in rows:
        eligible = request_is_eligible(row)
        status = row["status"]
        if eligible and status == "unavailable":
            execute_db(
                """
                UPDATE vacation_requests
                SET status = 'confirmed', processed_at = ?, decision_note = COALESCE(decision_note, 'Auto-promoted into top 6')
                WHERE id = ?
                """,
                (datetime.utcnow().isoformat(timespec="seconds"), row["id"]),
            )
            refreshed = query_db(
                """
                SELECT vr.*, COALESCE(vr.request_display_name, u.full_name) AS full_name, u.email
                FROM vacation_requests vr LEFT JOIN users u ON u.id = vr.user_id WHERE vr.id = ?
                """,
                (row["id"],),
                one=True,
            )
            maybe_send_approval_email(refreshed)
        elif not eligible and status in {"requested", "unavailable"}:
            execute_db("UPDATE vacation_requests SET status = 'unavailable' WHERE id = ?", (row["id"],))


def default_email_for_username(username: str) -> str:
    return f"{username}@example.com"


def slugify_name(full_name: str) -> str:
    username = "".join(ch.lower() for ch in full_name if ch.isalnum())
    return username[:24] or "physician"


def ensure_seed_data(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        if not query_db("SELECT id FROM users LIMIT 1", one=True):
            admin_password = hash_password("Admin123!")
            admin_id = execute_db(
                """
                INSERT INTO users (username, full_name, email, password_hash, role)
                VALUES (?, ?, ?, ?, 'admin')
                """,
                ("admin", "Scheduler Admin", "admin@example.com", admin_password),
            )
            execute_db(
                "INSERT INTO user_settings (user_id, week_start, show_week_numbers) VALUES (?, 'sunday', 0)",
                (admin_id,),
            )

            seed = import_seed_data()
            used_usernames = {"admin"}
            for full_name in seed["physicians"]:
                base = slugify_name(full_name)
                username = base
                suffix = 2
                while username in used_usernames:
                    username = f"{base}{suffix}"
                    suffix += 1
                used_usernames.add(username)
                user_id = execute_db(
                    """
                    INSERT INTO users (username, full_name, email, password_hash, role)
                    VALUES (?, ?, ?, ?, 'physician')
                    """,
                    (username, full_name, default_email_for_username(username), hash_password("ChangeMe123!")),
                )
                execute_db(
                    "INSERT INTO user_settings (user_id, week_start, show_week_numbers) VALUES (?, 'sunday', 0)",
                    (user_id,),
                )

            for doc in seed["documents"]:
                execute_db(
                    """
                    INSERT INTO holiday_documents (title, file_name, file_path)
                    VALUES (?, ?, ?)
                    """,
                    (doc["title"], doc["file_name"], doc["file_path"]),
                )
