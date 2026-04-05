import hashlib
import hmac
import secrets
import sqlite3
from collections import defaultdict
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

from flask import current_app, g

from .excel_import import import_seed_data
from .holiday_rotation import ensure_future_rotation_years, seed_rotation_assignments


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'physician',
    is_active INTEGER NOT NULL DEFAULT 1,
    annual_day_limit INTEGER NOT NULL DEFAULT 0,
    deleted_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS user_settings (
    user_id INTEGER PRIMARY KEY,
    week_start TEXT NOT NULL DEFAULT 'sunday',
    show_week_numbers INTEGER NOT NULL DEFAULT 0,
    theme_skin TEXT NOT NULL DEFAULT 'slate',
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS vacation_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    created_by_user_id INTEGER,
    request_display_name TEXT,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'scheduled',
    request_note TEXT,
    source_type TEXT NOT NULL DEFAULT 'manual',
    source_prompt TEXT,
    source_response TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    updated_by_user_id INTEGER,
    processed_at TEXT,
    processed_by INTEGER,
    decision_note TEXT,
    canceled_at TEXT,
    canceled_by_user_id INTEGER,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (updated_by_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (canceled_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS holiday_documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    document_type TEXT NOT NULL DEFAULT 'upload',
    display_year INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS email_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    request_id INTEGER,
    purpose TEXT NOT NULL,
    recipient TEXT NOT NULL,
    subject TEXT NOT NULL,
    body TEXT NOT NULL,
    delivery_status TEXT NOT NULL,
    error_text TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (request_id) REFERENCES vacation_requests(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS user_delegations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_user_id INTEGER NOT NULL,
    delegate_user_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(owner_user_id, delegate_user_id),
    FOREIGN KEY (owner_user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (delegate_user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS holiday_definitions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    holiday_key TEXT NOT NULL,
    title TEXT NOT NULL,
    category TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    is_locked INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    UNIQUE(year, holiday_key)
);

CREATE TABLE IF NOT EXISTS holiday_rotation_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    holiday_key TEXT NOT NULL,
    holiday_title TEXT NOT NULL,
    category TEXT NOT NULL,
    user_id INTEGER NOT NULL,
    slot_order INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    source_type TEXT NOT NULL DEFAULT 'seed',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT,
    UNIQUE(year, holiday_key, user_id),
    UNIQUE(year, holiday_key, slot_order),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS holiday_trade_offers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    year INTEGER NOT NULL,
    offered_by_user_id INTEGER NOT NULL,
    offered_to_user_id INTEGER NOT NULL,
    offered_holiday_key TEXT NOT NULL,
    requested_holiday_key TEXT NOT NULL,
    note TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    responded_at TEXT,
    responded_by_user_id INTEGER,
    FOREIGN KEY (offered_by_user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (offered_to_user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (responded_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    token TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    actor_user_id INTEGER,
    event_type TEXT NOT NULL,
    message TEXT NOT NULL,
    entity_type TEXT,
    entity_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS change_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    activity_log_id INTEGER,
    actor_user_id INTEGER,
    entity_type TEXT NOT NULL,
    entity_id INTEGER,
    field_name TEXT NOT NULL,
    old_value TEXT,
    new_value TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (activity_log_id) REFERENCES activity_log(id) ON DELETE SET NULL,
    FOREIGN KEY (actor_user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS breakout_scores (
    user_id INTEGER PRIMARY KEY,
    score INTEGER NOT NULL,
    elapsed_ms INTEGER NOT NULL,
    paddle_hits INTEGER NOT NULL DEFAULT 0,
    lives_left INTEGER NOT NULL DEFAULT 0,
    brick_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);
"""


REQUEST_ACTIVE_STATUSES = ("scheduled",)


def deleted_username_placeholder(user_id: int) -> str:
    return f"deleted_user_{user_id}"


def deleted_email_placeholder(user_id: int) -> str:
    return f"deleted+user-{user_id}@deleted.local"


def iso_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def init_db(app):
    Path(app.config["DATABASE"]).parent.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        db = get_db()
        with closing(db.cursor()) as cursor:
            cursor.executescript(SCHEMA)
            _ensure_columns(db)
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_vacation_requests_dates ON vacation_requests(start_date, end_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_vacation_requests_user ON vacation_requests(user_id, status)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_holiday_definitions_dates ON holiday_definitions(start_date, end_date)")
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_breakout_scores_score ON breakout_scores(score DESC, elapsed_ms ASC, paddle_hits ASC)")
        _normalize_existing_records(db)
        ensure_holiday_definitions(date.today().year - 1, date.today().year + 2)
        db.commit()


def _ensure_columns(db: sqlite3.Connection):
    user_columns = {row["name"] for row in db.execute("PRAGMA table_info(users)").fetchall()}
    request_columns = {row["name"] for row in db.execute("PRAGMA table_info(vacation_requests)").fetchall()}
    doc_columns = {row["name"] for row in db.execute("PRAGMA table_info(holiday_documents)").fetchall()}

    if "deleted_at" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN deleted_at TEXT")
    if "annual_day_limit" not in user_columns:
        db.execute("ALTER TABLE users ADD COLUMN annual_day_limit INTEGER NOT NULL DEFAULT 0")
    settings_columns = {row["name"] for row in db.execute("PRAGMA table_info(user_settings)").fetchall()}
    if "theme_skin" not in settings_columns:
        db.execute("ALTER TABLE user_settings ADD COLUMN theme_skin TEXT NOT NULL DEFAULT 'slate'")

    additions = {
        "request_display_name": "TEXT",
        "created_by_user_id": "INTEGER",
        "source_type": "TEXT NOT NULL DEFAULT 'manual'",
        "source_prompt": "TEXT",
        "source_response": "TEXT",
        "updated_at": "TEXT",
        "updated_by_user_id": "INTEGER",
        "canceled_by_user_id": "INTEGER",
    }
    for name, definition in additions.items():
        if name not in request_columns:
            db.execute(f"ALTER TABLE vacation_requests ADD COLUMN {name} {definition}")

    if "document_type" not in doc_columns:
        db.execute("ALTER TABLE holiday_documents ADD COLUMN document_type TEXT NOT NULL DEFAULT 'upload'")
    if "display_year" not in doc_columns:
        db.execute("ALTER TABLE holiday_documents ADD COLUMN display_year INTEGER")


def _normalize_existing_records(db: sqlite3.Connection):
    _release_deleted_user_identifiers(db)
    db.execute("UPDATE vacation_requests SET status = 'scheduled' WHERE status IN ('requested', 'confirmed')")
    db.execute("UPDATE vacation_requests SET status = 'canceled' WHERE status IN ('withdrawn', 'unavailable')")
    db.execute(
        """
        UPDATE vacation_requests
        SET request_display_name = (
            SELECT users.full_name FROM users WHERE users.id = vacation_requests.user_id
        )
        WHERE request_display_name IS NULL
        """
    )
    db.execute("UPDATE vacation_requests SET created_by_user_id = COALESCE(created_by_user_id, user_id)")
    db.execute("UPDATE vacation_requests SET updated_at = COALESCE(updated_at, processed_at, created_at)")
    db.execute("UPDATE vacation_requests SET source_type = COALESCE(source_type, 'manual')")
    db.execute(
        """
        UPDATE holiday_documents
        SET display_year = CASE
            WHEN display_year IS NOT NULL THEN display_year
            WHEN file_name GLOB '*2024*' THEN 2024
            WHEN file_name GLOB '*2025*' THEN 2025
            WHEN file_name GLOB '*2026*' THEN 2026
            ELSE display_year
        END
        """
    )


def _release_deleted_user_identifiers(db: sqlite3.Connection):
    deleted_users = db.execute(
        "SELECT id, username, email FROM users WHERE deleted_at IS NOT NULL"
    ).fetchall()
    for row in deleted_users:
        archived_username = deleted_username_placeholder(row["id"])
        archived_email = deleted_email_placeholder(row["id"])
        if row["username"] == archived_username and row["email"] == archived_email:
            continue
        db.execute(
            "UPDATE users SET username = ?, email = ?, is_active = 0 WHERE id = ?",
            (archived_username, archived_email, row["id"]),
        )


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


def active_request_statuses():
    return REQUEST_ACTIVE_STATUSES


def overlapping_requests(day_iso: str, *, include_canceled: bool = False):
    statuses = active_request_statuses() if not include_canceled else ("scheduled", "canceled")
    return requests_for_day(day_iso, statuses=statuses)


def requests_for_day(day_iso: str, *, statuses: tuple[str, ...] = ("scheduled",)):
    placeholders = ",".join("?" for _ in statuses)
    return query_db(
        f"""
        SELECT vr.*, COALESCE(vr.request_display_name, u.full_name) AS full_name, u.username, u.email,
               actor.full_name AS created_by_name
        FROM vacation_requests vr
        LEFT JOIN users u ON u.id = vr.user_id
        LEFT JOIN users actor ON actor.id = vr.created_by_user_id
        WHERE vr.start_date <= ?
          AND vr.end_date >= ?
          AND vr.status IN ({placeholders})
        ORDER BY vr.status DESC, u.full_name COLLATE NOCASE ASC, vr.start_date ASC, vr.id ASC
        """,
        (day_iso, day_iso, *statuses),
    )


def requests_overlapping_range(
    user_id: int,
    start_date: str,
    end_date: str,
    *,
    statuses: tuple[str, ...] = ("scheduled", "waitlisted"),
):
    placeholders = ",".join("?" for _ in statuses)
    return query_db(
        f"""
        SELECT *
        FROM vacation_requests
        WHERE user_id = ?
          AND status IN ({placeholders})
          AND start_date <= ?
          AND end_date >= ?
        ORDER BY start_date ASC, id ASC
        """,
        (user_id, *statuses, end_date, start_date),
    )


def waitlist_counts_for_month(year: int, month: int):
    first_day = date(year, month, 1)
    next_month = date(year + (month == 12), 1 if month == 12 else month + 1, 1)
    start_iso = first_day.isoformat()
    end_iso = (next_month - timedelta(days=1)).isoformat()
    mapping = defaultdict(int)
    rows = query_db(
        """
        SELECT start_date, end_date
        FROM vacation_requests
        WHERE status = 'waitlisted'
          AND start_date <= ?
          AND end_date >= ?
        """,
        (end_iso, start_iso),
    )
    for row in rows:
        start = max(start_iso, row["start_date"])
        end = min(end_iso, row["end_date"])
        for day_iso in daterange(start, end):
            mapping[day_iso] += 1
    return mapping


def default_email_for_username(username: str) -> str:
    return f"{username}@example.com"


def slugify_name(full_name: str) -> str:
    username = "".join(ch.lower() for ch in full_name if ch.isalnum())
    return username[:24] or "physician"


def next_username(full_name: str, *, used_usernames: set[str] | None = None):
    used = used_usernames or set()
    base = slugify_name(full_name)
    candidate = base
    suffix = 2
    while candidate in used or query_db("SELECT id FROM users WHERE username = ?", (candidate,), one=True):
        candidate = f"{base}{suffix}"
        suffix += 1
    return candidate


def physician_directory():
    return query_db(
        """
        SELECT id, username, full_name, email, annual_day_limit
        FROM users
        WHERE role = 'physician' AND is_active = 1 AND deleted_at IS NULL
        ORDER BY full_name COLLATE NOCASE ASC
        """
    )


def managed_physician_rows(actor_row):
    if not actor_row:
        return []
    if actor_row["role"] == "admin":
        return physician_directory()
    return query_db(
        """
        SELECT DISTINCT u.id, u.username, u.full_name, u.email, u.annual_day_limit
        FROM users u
        LEFT JOIN user_delegations d ON d.owner_user_id = u.id
        WHERE u.role = 'physician'
          AND u.is_active = 1
          AND u.deleted_at IS NULL
          AND (
                u.id = ?
                OR d.delegate_user_id = ?
          )
        ORDER BY u.full_name COLLATE NOCASE ASC
        """,
        (actor_row["id"], actor_row["id"]),
    )


def can_manage_physician(actor_row, physician_id: int) -> bool:
    if not actor_row:
        return False
    if actor_row["role"] == "admin":
        return True
    return any(row["id"] == physician_id for row in managed_physician_rows(actor_row))


def can_manage_request(actor_row, request_row) -> bool:
    return bool(actor_row and request_row and can_manage_physician(actor_row, request_row["user_id"]))


def holiday_rows_between(start_date: str, end_date: str):
    return query_db(
        """
        SELECT *
        FROM holiday_definitions
        WHERE is_locked = 1
          AND start_date <= ?
          AND end_date >= ?
        ORDER BY start_date ASC, title ASC
        """,
        (end_date, start_date),
    )


def holiday_for_day(day_iso: str):
    return query_db(
        """
        SELECT *
        FROM holiday_definitions
        WHERE is_locked = 1 AND start_date <= ? AND end_date >= ?
        ORDER BY start_date ASC, title ASC
        """,
        (day_iso, day_iso),
        one=True,
    )


def holiday_map_for_month(year: int, month: int):
    first_day = date(year, month, 1)
    if month == 12:
        next_month = date(year + 1, 1, 1)
    else:
        next_month = date(year, month + 1, 1)
    start_iso = first_day.isoformat()
    end_iso = (next_month - timedelta(days=1)).isoformat()
    mapping = {}
    for row in holiday_rows_between(start_iso, end_iso):
        for day_iso in daterange(row["start_date"], row["end_date"]):
            mapping[day_iso] = row
    return mapping


def request_conflict_for_physician(
    user_id: int,
    start_date: str,
    end_date: str,
    *,
    statuses: tuple[str, ...] = ("scheduled", "waitlisted"),
    exclude_request_id: int | None = None,
):
    params = [user_id, *statuses, end_date, start_date]
    exclude_clause = ""
    if exclude_request_id is not None:
        exclude_clause = "AND id != ?"
        params.append(exclude_request_id)
    placeholders = ",".join("?" for _ in statuses)
    return query_db(
        f"""
        SELECT *
        FROM vacation_requests
        WHERE user_id = ?
          AND status IN ({placeholders})
          AND start_date <= ?
          AND end_date >= ?
          {exclude_clause}
        LIMIT 1
        """,
        tuple(params),
        one=True,
    )


def scheduled_count_for_day(day_iso: str, *, exclude_request_id: int | None = None):
    params = [day_iso, day_iso]
    exclude_clause = ""
    if exclude_request_id is not None:
        exclude_clause = "AND id != ?"
        params.append(exclude_request_id)
    row = query_db(
        f"""
        SELECT COUNT(*) AS count
        FROM vacation_requests
        WHERE status = 'scheduled'
          AND start_date <= ?
          AND end_date >= ?
          {exclude_clause}
        """,
        tuple(params),
        one=True,
    )
    return int(row["count"] if row else 0)


def scheduled_day_usage_by_year(user_id: int, *, exclude_request_id: int | None = None):
    params = [user_id]
    exclude_clause = ""
    if exclude_request_id is not None:
        exclude_clause = "AND id != ?"
        params.append(exclude_request_id)
    rows = query_db(
        f"""
        SELECT start_date, end_date
        FROM vacation_requests
        WHERE user_id = ?
          AND status = 'scheduled'
          {exclude_clause}
        """,
        tuple(params),
    )
    counts = defaultdict(int)
    for row in rows:
        for day_iso in daterange(row["start_date"], row["end_date"]):
            counts[int(day_iso[:4])] += 1
    return counts


def validate_request_window(
    user_id: int,
    start_date: str,
    end_date: str,
    *,
    exclude_request_id: int | None = None,
    allow_full_days: bool = False,
):
    if not start_date or not end_date:
        raise ValueError("Start and end dates are required.")
    if end_date < start_date:
        raise ValueError("End date must be on or after the start date.")
    latest_allowed = date.today() + timedelta(days=366)
    if date.fromisoformat(start_date) > latest_allowed or date.fromisoformat(end_date) > latest_allowed:
        raise ValueError("Vacation can only be added up to 1 year in advance.")

    holiday_rows = holiday_rows_between(start_date, end_date)
    if holiday_rows:
        titles = ", ".join(row["title"] for row in holiday_rows)
        raise ValueError(f"{titles} are protected holiday dates and cannot be requested.")

    existing = request_conflict_for_physician(user_id, start_date, end_date, exclude_request_id=exclude_request_id)
    if existing:
        if existing["status"] == "waitlisted":
            raise ValueError("This physician already has a waitlisted vacation request overlapping those dates.")
        raise ValueError("This physician already has scheduled vacation overlapping those dates.")

    full_days = []
    max_slots = current_app.config["MAX_DAILY_VACATION_SLOTS"]
    for day_iso in daterange(start_date, end_date):
        if scheduled_count_for_day(day_iso, exclude_request_id=exclude_request_id) >= max_slots:
            full_days.append(day_iso)
    if full_days and not allow_full_days:
        preview = ", ".join(full_days[:5])
        suffix = "..." if len(full_days) > 5 else ""
        raise ValueError(f"All vacation slots are already filled for: {preview}{suffix}")

    return {"full_days": full_days}


def record_activity(actor_user_id, event_type: str, message: str, entity_type: str | None = None, entity_id: int | None = None, changes=None):
    db = get_db()
    activity_id = db.execute(
        """
        INSERT INTO activity_log (actor_user_id, event_type, message, entity_type, entity_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (actor_user_id, event_type, message, entity_type, entity_id, iso_now()),
    ).lastrowid
    for change in changes or []:
        db.execute(
            """
            INSERT INTO change_log (activity_log_id, actor_user_id, entity_type, entity_id, field_name, old_value, new_value, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                activity_id,
                actor_user_id,
                change.get("entity_type", entity_type or ""),
                change.get("entity_id", entity_id),
                change["field_name"],
                None if change.get("old_value") is None else str(change.get("old_value")),
                None if change.get("new_value") is None else str(change.get("new_value")),
                iso_now(),
            ),
        )
    db.commit()
    return activity_id


def _fourth_thursday_of_november(year: int):
    first_day = date(year, 11, 1)
    offset = (3 - first_day.weekday()) % 7
    return first_day + timedelta(days=offset + 21)


def _last_monday_of_may(year: int):
    current = date(year, 5, 31)
    while current.weekday() != 0:
        current -= timedelta(days=1)
    return current


def _first_monday_of_september(year: int):
    current = date(year, 9, 1)
    while current.weekday() != 0:
        current += timedelta(days=1)
    return current


def default_holiday_definitions(year: int):
    thanksgiving = _fourth_thursday_of_november(year)
    memorial_day = _last_monday_of_may(year)
    labor_day = _first_monday_of_september(year)
    july_4 = date(year, 7, 4)

    if july_4.weekday() == 0:
        july_start, july_end = date(year, 7, 2), july_4
    elif july_4.weekday() == 4:
        july_start, july_end = july_4, date(year, 7, 6)
    else:
        july_start = july_end = july_4

    return [
        {
            "year": year,
            "holiday_key": "thanksgiving",
            "title": "Thanksgiving",
            "category": "major",
            "start_date": thanksgiving.isoformat(),
            "end_date": (thanksgiving + timedelta(days=3)).isoformat(),
        },
        {
            "year": year,
            "holiday_key": "christmas",
            "title": "Christmas",
            "category": "major",
            "start_date": date(year, 12, 23).isoformat(),
            "end_date": date(year, 12, 26).isoformat(),
        },
        {
            "year": year,
            "holiday_key": "new_years",
            "title": "New Year's",
            "category": "major",
            "start_date": date(year - 1, 12, 30).isoformat(),
            "end_date": date(year, 1, 2).isoformat(),
        },
        {
            "year": year,
            "holiday_key": "memorial_day",
            "title": "Memorial Day",
            "category": "minor",
            "start_date": (memorial_day - timedelta(days=2)).isoformat(),
            "end_date": memorial_day.isoformat(),
        },
        {
            "year": year,
            "holiday_key": "july_4",
            "title": "July 4th",
            "category": "minor",
            "start_date": july_start.isoformat(),
            "end_date": july_end.isoformat(),
        },
        {
            "year": year,
            "holiday_key": "labor_day",
            "title": "Labor Day",
            "category": "minor",
            "start_date": (labor_day - timedelta(days=2)).isoformat(),
            "end_date": labor_day.isoformat(),
        },
    ]


def ensure_holiday_definitions(start_year: int, through_year: int):
    db = get_db()
    for year in range(start_year, through_year + 1):
        for holiday in default_holiday_definitions(year):
            existing = db.execute(
                "SELECT id FROM holiday_definitions WHERE year = ? AND holiday_key = ?",
                (holiday["year"], holiday["holiday_key"]),
            ).fetchone()
            if existing:
                continue
            db.execute(
                """
                INSERT INTO holiday_definitions
                (year, holiday_key, title, category, start_date, end_date, is_locked, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    holiday["year"],
                    holiday["holiday_key"],
                    holiday["title"],
                    holiday["category"],
                    holiday["start_date"],
                    holiday["end_date"],
                    iso_now(),
                    iso_now(),
                ),
            )
    db.commit()


def ensure_seed_data(app):
    app.teardown_appcontext(close_db)
    with app.app_context():
        db = get_db()
        seeded_users = query_db("SELECT id FROM users LIMIT 1", one=True)
        seed = import_seed_data()

        if not seeded_users:
            admin_password = hash_password("Admin123!")
            admin_id = db.execute(
                """
                INSERT INTO users (username, full_name, email, password_hash, role, annual_day_limit)
                VALUES (?, ?, ?, ?, 'admin', 0)
                """,
                ("admin", "Scheduler Admin", "admin@example.com", admin_password),
            ).lastrowid
            db.execute(
                "INSERT INTO user_settings (user_id, week_start, show_week_numbers) VALUES (?, 'sunday', 0)",
                (admin_id,),
            )

            used_usernames = {"admin"}
            for full_name in seed["physicians"]:
                username = next_username(full_name, used_usernames=used_usernames)
                used_usernames.add(username)
                user_id = db.execute(
                    """
                    INSERT INTO users (username, full_name, email, password_hash, role, annual_day_limit)
                    VALUES (?, ?, ?, ?, 'physician', 0)
                    """,
                    (username, full_name, default_email_for_username(username), hash_password("ChangeMe123!")),
                ).lastrowid
                db.execute(
                    "INSERT INTO user_settings (user_id, week_start, show_week_numbers) VALUES (?, 'sunday', 0)",
                    (user_id,),
                )
            db.commit()

        existing_paths = {row["file_path"] for row in query_db("SELECT file_path FROM holiday_documents")}
        for document in seed["documents"]:
            if document["file_path"] in existing_paths:
                continue
            db.execute(
                """
                INSERT INTO holiday_documents (title, file_name, file_path, document_type, display_year)
                VALUES (?, ?, ?, 'upload', ?)
                """,
                (document["title"], document["file_name"], document["file_path"], document.get("display_year")),
            )
        db.commit()

        if not query_db("SELECT id FROM holiday_rotation_assignments LIMIT 1", one=True):
            user_lookup = {
                "".join(part.lower() for part in row["full_name"].split()): row["id"]
                for row in query_db("SELECT id, full_name FROM users WHERE role = 'physician' AND deleted_at IS NULL")
            }
            seed_rotation_assignments(db, user_lookup)
            db.commit()

        ensure_future_rotation_years(db, date.today().year + 2)
        ensure_holiday_definitions(date.today().year - 1, date.today().year + 2)
        db.commit()
