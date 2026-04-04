import calendar
import csv
import io
import re
import secrets
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import (
    Response,
    abort,
    current_app,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

from .db import (
    can_manage_physician,
    can_manage_request,
    daterange,
    execute_db,
    get_db,
    hash_password,
    holiday_for_day,
    holiday_map_for_month,
    iso_now,
    managed_physician_rows,
    overlapping_requests,
    physician_directory,
    query_db,
    record_activity,
    requests_for_day,
    requests_overlapping_range,
    validate_request_window,
    verify_password,
    waitlist_counts_for_month,
)
from .legacy_calendar import legacy_calendar_for_year, legacy_calendar_years, legacy_documents
from .llm import explain_conflict_naturally, parse_natural_language_request
from .mailer import send_email
from .themes import THEME_CHOICES, theme_options_payload


MAJOR_HOLIDAYS = ["thanksgiving", "christmas", "new_years"]
MINOR_HOLIDAYS = ["memorial_day", "july_4", "labor_day"]


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return query_db(
        """
        SELECT u.*, s.week_start, s.show_week_numbers, s.theme_skin
        FROM users u
        LEFT JOIN user_settings s ON s.user_id = u.id
        WHERE u.id = ? AND u.is_active = 1 AND u.deleted_at IS NULL
        """,
        (user_id,),
        one=True,
    )


def serialize_physician(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "fullName": row["full_name"],
        "email": row["email"],
        "annualDayLimit": row["annual_day_limit"],
    }


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required."}), 401
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            if request.path.startswith("/api/"):
                return jsonify({"error": "Authentication required."}), 401
            return redirect(url_for("login", next=request.path))
        if user["role"] != "admin":
            if request.path.startswith("/api/"):
                return jsonify({"error": "Admin access required."}), 403
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def _current_user_payload():
    user = current_user()
    if not user:
        return None
    return {
        "id": user["id"],
        "username": user["username"],
        "fullName": user["full_name"],
        "email": user["email"],
        "role": user["role"],
        "weekStart": user["week_start"],
        "showWeekNumbers": bool(user["show_week_numbers"]),
        "themeSkin": user["theme_skin"] or "slate",
        "annualDayLimit": user["annual_day_limit"],
    }


def _manageable_physicians_payload():
    user = current_user()
    return [serialize_physician(row) for row in managed_physician_rows(user)]


def _physician_directory_payload():
    return [serialize_physician(row) for row in physician_directory()]


def _holiday_badge(day_iso: str, holiday_lookup: dict[str, dict]):
    holiday_row = holiday_lookup.get(day_iso)
    if not holiday_row:
        return None
    return {"title": holiday_row["title"], "category": holiday_row["category"]}


def build_month_payload(year: int, month: int, week_start: str, show_week_numbers: bool):
    cal = calendar.Calendar(firstweekday=6 if week_start == "sunday" else 0)
    weeks = []
    max_slots = current_app.config["MAX_DAILY_VACATION_SLOTS"]
    today = date.today().isoformat()
    holiday_lookup = holiday_map_for_month(year, month)
    waitlist_lookup = waitlist_counts_for_month(year, month)
    for week in cal.monthdatescalendar(year, month):
        week_payload = []
        for day in week:
            day_iso = day.isoformat()
            holiday = _holiday_badge(day_iso, holiday_lookup)
            rows = [] if holiday else overlapping_requests(day_iso)
            slots = []
            for index in range(max_slots):
                row = rows[index] if index < len(rows) else None
                slots.append(
                    {
                        "occupied": bool(row),
                        "label": row["full_name"].split()[-1] if row else "",
                        "name": row["full_name"] if row else "",
                    }
                )
            week_payload.append(
                {
                    "date": day_iso,
                    "day": day.day,
                    "isCurrentMonth": day.month == month,
                    "isToday": day_iso == today,
                    "isHoliday": bool(holiday),
                    "holiday": holiday,
                    "waitlistCount": waitlist_lookup.get(day_iso, 0),
                    "slots": slots,
                }
            )
        weeks.append(
            {
                "weekNumber": week[0].isocalendar()[1] if show_week_numbers else None,
                "days": week_payload,
            }
        )
    return weeks


def serialize_request(row):
    return {
        "id": row["id"],
        "physicianId": row["user_id"],
        "physician": row["full_name"],
        "username": row["username"],
        "email": row["email"],
        "startDate": row["start_date"],
        "endDate": row["end_date"],
        "status": row["status"],
        "note": row["request_note"] or "",
        "decisionNote": row["decision_note"] or "",
        "sourceType": row["source_type"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
        "createdBy": row["created_by_name"] or row["full_name"],
    }


def serialize_holiday(row):
    return {
        "id": row["id"],
        "year": row["year"],
        "holidayKey": row["holiday_key"],
        "title": row["title"],
        "category": row["category"],
        "startDate": row["start_date"],
        "endDate": row["end_date"],
        "isLocked": bool(row["is_locked"]),
    }


def serialize_user(row):
    return {
        "id": row["id"],
        "username": row["username"],
        "fullName": row["full_name"],
        "email": row["email"],
        "role": row["role"],
        "isActive": bool(row["is_active"]),
        "annualDayLimit": row["annual_day_limit"],
    }


def serialize_delegation(row):
    return {
        "id": row["id"],
        "ownerUserId": row["owner_user_id"],
        "ownerName": row["owner_name"],
        "delegateUserId": row["delegate_user_id"],
        "delegateName": row["delegate_name"],
        "createdAt": row["created_at"],
    }


def _issue_password_reset_token(user_id: int, *, lifetime_hours: int = 2):
    token = secrets.token_urlsafe(32)
    expires_at = (datetime.utcnow() + timedelta(hours=lifetime_hours)).isoformat(timespec="seconds")
    execute_db(
        """
        INSERT INTO password_reset_tokens (user_id, token, expires_at, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (user_id, token, expires_at, iso_now()),
    )
    return token, expires_at


def _generate_temporary_password(length: int = 14):
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%^&*"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _active_user_by_identifier(identifier: str):
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    return query_db(
        """
        SELECT *
        FROM users
        WHERE deleted_at IS NULL AND is_active = 1 AND (username = ? OR email = ?)
        """,
        (identifier, identifier),
        one=True,
    )


def _email_delivery_feedback(result: dict | None, *, sent_message: str, fallback_message: str):
    status = (result or {}).get("status", "")
    error_text = ((result or {}).get("error") or "").strip()
    if status == "sent":
        return {"message": sent_message, "toastType": "success", "deliveryStatus": "sent"}
    suffix = f" {error_text}" if error_text else ""
    return {
        "message": f"{fallback_message}{suffix}",
        "toastType": "warning",
        "deliveryStatus": status or "logged-only",
    }


def _send_password_reset_email(user, *, lifetime_hours: int = 2):
    token, _ = _issue_password_reset_token(user["id"], lifetime_hours=lifetime_hours)
    reset_link = url_for("reset_password", token=token, _external=True)
    result = send_email(
        to_email=user["email"],
        subject="South Bay ED VL Schedule password reset",
        body=(
            f"Hello {user['full_name']},\n\n"
            "A password reset was requested for your South Bay ED VL Schedule account.\n"
            f"Use this link to reset your password: {reset_link}\n\n"
            "If you did not request this, you can ignore this email."
        ),
        purpose="password-reset",
        user_id=user["id"],
    )
    record_activity(
        user["id"],
        "password-reset-requested",
        f"Password reset requested for {user['username']}.",
        "user",
        user["id"],
    )
    return result


def _password_reset_feedback(result: dict | None):
    return _email_delivery_feedback(
        result,
        sent_message="If that account exists, a password reset email was sent.",
        fallback_message=(
            "If that account exists, a password reset link was generated, but email delivery is not fully configured. "
            "Check Gmail or SMTP settings, or retrieve the link from email_log."
        ),
    )


def _prompt_mentions_unauthorized_physician(actor, prompt_text: str, managed_physicians: list[dict]):
    if not actor or actor["role"] == "admin" or not prompt_text:
        return None
    managed_ids = {item["id"] for item in managed_physicians}
    prompt_lower = f" {prompt_text.lower()} "
    for physician in physician_directory():
        if physician["id"] in managed_ids:
            continue
        username = physician["username"].lower()
        full_name = " ".join(physician["full_name"].lower().split())
        if re.search(rf"(?<![\w@]){re.escape(username)}(?![\w@])", prompt_lower):
            return physician
        if full_name and f" {full_name} " in prompt_lower:
            return physician
    return None


def serialize_trade(row):
    return {
        "id": row["id"],
        "year": row["year"],
        "offeredByUserId": row["offered_by_user_id"],
        "offeredByName": row["offered_by_name"],
        "offeredToUserId": row["offered_to_user_id"],
        "offeredToName": row["offered_to_name"],
        "offeredHolidayKey": row["offered_holiday_key"],
        "offeredHolidayTitle": row["offered_holiday_title"],
        "requestedHolidayKey": row["requested_holiday_key"],
        "requestedHolidayTitle": row["requested_holiday_title"],
        "note": row["note"] or "",
        "status": row["status"],
        "createdAt": row["created_at"],
        "respondedAt": row["responded_at"],
    }


def _rotation_years():
    years = query_db("SELECT DISTINCT year FROM holiday_rotation_assignments ORDER BY year ASC")
    return [row["year"] for row in years]


def _breakout_score_payload(actor=None):
    high_score_row = query_db(
        """
        SELECT bs.*, u.username, u.full_name
        FROM breakout_scores bs
        JOIN users u ON u.id = bs.user_id
        WHERE u.deleted_at IS NULL
        ORDER BY bs.score DESC, bs.elapsed_ms ASC, bs.paddle_hits ASC, bs.updated_at ASC
        LIMIT 1
        """,
        one=True,
    )
    personal_row = None
    if actor:
        personal_row = query_db(
            """
            SELECT bs.*, u.username, u.full_name
            FROM breakout_scores bs
            JOIN users u ON u.id = bs.user_id
            WHERE bs.user_id = ?
            """,
            (actor["id"],),
            one=True,
        )
    return {
        "highScore": (
            {
                "userId": high_score_row["user_id"],
                "username": high_score_row["username"],
                "fullName": high_score_row["full_name"],
                "score": high_score_row["score"],
                "elapsedMs": high_score_row["elapsed_ms"],
                "paddleHits": high_score_row["paddle_hits"],
                "livesLeft": high_score_row["lives_left"],
                "brickCount": high_score_row["brick_count"],
                "updatedAt": high_score_row["updated_at"],
            }
            if high_score_row
            else None
        ),
        "personalBest": (
            {
                "score": personal_row["score"],
                "elapsedMs": personal_row["elapsed_ms"],
                "paddleHits": personal_row["paddle_hits"],
                "livesLeft": personal_row["lives_left"],
                "brickCount": personal_row["brick_count"],
                "updatedAt": personal_row["updated_at"],
            }
            if personal_row
            else None
        ),
    }


def _default_selected_year(years: list[int]):
    current_year = date.today().year
    if current_year in years:
        return current_year
    future_years = [year for year in years if year >= current_year]
    if future_years:
        return future_years[0]
    return years[-1] if years else current_year


def _rotation_view_model(selected_year: int):
    rows = query_db(
        """
        SELECT hra.*, u.full_name
        FROM holiday_rotation_assignments hra
        JOIN users u ON u.id = hra.user_id
        WHERE hra.year = ?
        ORDER BY hra.category ASC, hra.slot_order ASC, u.full_name COLLATE NOCASE ASC
        """,
        (selected_year,),
    )
    group = {
        "major": {key: {"key": key, "title": "", "category": "major", "assignments": []} for key in MAJOR_HOLIDAYS},
        "minor": {key: {"key": key, "title": "", "category": "minor", "assignments": []} for key in MINOR_HOLIDAYS},
    }
    for row in rows:
        holiday = group[row["category"]][row["holiday_key"]]
        holiday["title"] = row["holiday_title"]
        holiday["assignments"].append({"fullName": row["full_name"], "userId": row["user_id"], "note": row["note"] or ""})
    return [
        {"category": "major", "title": "Major Holidays", "holidays": [group["major"][key] for key in MAJOR_HOLIDAYS]},
        {"category": "minor", "title": "Minor Holidays", "holidays": [group["minor"][key] for key in MINOR_HOLIDAYS]},
    ]


def _trade_candidate_holidays(user_id: int, year: int):
    return query_db(
        """
        SELECT holiday_key, holiday_title, category
        FROM holiday_rotation_assignments
        WHERE year = ? AND user_id = ?
        ORDER BY category ASC, holiday_key ASC
        """,
        (year, user_id),
    )


def _parse_int(value, default=None):
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _holiday_key_from_title(title: str):
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


def _requests_for_managed_physicians(actor):
    managed = managed_physician_rows(actor)
    if not managed:
        return []
    placeholders = ",".join("?" for _ in managed)
    physician_ids = [row["id"] for row in managed]
    return query_db(
        f"""
        SELECT vr.*, COALESCE(vr.request_display_name, u.full_name) AS full_name, u.username, u.email,
               actor.full_name AS created_by_name
        FROM vacation_requests vr
        LEFT JOIN users u ON u.id = vr.user_id
        LEFT JOIN users actor ON actor.id = vr.created_by_user_id
        WHERE vr.user_id IN ({placeholders})
        ORDER BY vr.start_date DESC, vr.id DESC
        """,
        tuple(physician_ids),
    )


def _delegations_for_actor(actor):
    owned = query_db(
        """
        SELECT d.*, owner.full_name AS owner_name, delegate.full_name AS delegate_name
        FROM user_delegations d
        JOIN users owner ON owner.id = d.owner_user_id
        JOIN users delegate ON delegate.id = d.delegate_user_id
        WHERE d.owner_user_id = ?
        ORDER BY delegate.full_name COLLATE NOCASE ASC
        """,
        (actor["id"],),
    )
    incoming = query_db(
        """
        SELECT d.*, owner.full_name AS owner_name, delegate.full_name AS delegate_name
        FROM user_delegations d
        JOIN users owner ON owner.id = d.owner_user_id
        JOIN users delegate ON delegate.id = d.delegate_user_id
        WHERE d.delegate_user_id = ?
        ORDER BY owner.full_name COLLATE NOCASE ASC
        """,
        (actor["id"],),
    )
    return {"owned": [serialize_delegation(row) for row in owned], "incoming": [serialize_delegation(row) for row in incoming]}


def _trades_for_actor(actor):
    base_query = """
        SELECT hto.*, offered_by.full_name AS offered_by_name, offered_to.full_name AS offered_to_name,
               offered.holiday_title AS offered_holiday_title, requested.holiday_title AS requested_holiday_title
        FROM holiday_trade_offers hto
        LEFT JOIN users offered_by ON offered_by.id = hto.offered_by_user_id
        LEFT JOIN users offered_to ON offered_to.id = hto.offered_to_user_id
        LEFT JOIN holiday_rotation_assignments offered
          ON offered.year = hto.year AND offered.holiday_key = hto.offered_holiday_key AND offered.user_id = hto.offered_by_user_id
        LEFT JOIN holiday_rotation_assignments requested
          ON requested.year = hto.year AND requested.holiday_key = hto.requested_holiday_key AND requested.user_id = hto.offered_to_user_id
    """
    if actor["role"] == "admin":
        rows = query_db(f"{base_query} ORDER BY hto.created_at DESC, hto.id DESC")
    else:
        rows = query_db(
            f"{base_query} WHERE hto.offered_by_user_id = ? OR hto.offered_to_user_id = ? ORDER BY hto.created_at DESC, hto.id DESC",
            (actor["id"], actor["id"]),
        )
    return [serialize_trade(row) for row in rows]


def _export_matrix(year: int):
    physicians = query_db(
        """
        SELECT id, full_name
        FROM users
        WHERE role = 'physician' AND deleted_at IS NULL
        ORDER BY full_name COLLATE NOCASE ASC
        """
    )
    dates = []
    current_day = date(year, 1, 1)
    while current_day.year == year:
        dates.append(current_day.isoformat())
        current_day += timedelta(days=1)

    requests = query_db(
        """
        SELECT user_id, start_date, end_date
        FROM vacation_requests
        WHERE status = 'scheduled'
          AND start_date <= ?
          AND end_date >= ?
        """,
        (date(year, 12, 31).isoformat(), date(year, 1, 1).isoformat()),
    )
    by_user = {}
    for row in requests:
        user_days = by_user.setdefault(row["user_id"], set())
        for day_iso in daterange(max(row["start_date"], f"{year}-01-01"), min(row["end_date"], f"{year}-12-31")):
            user_days.add(day_iso)

    matrix = []
    for physician in physicians:
        scheduled_days = by_user.get(physician["id"], set())
        matrix.append({"physician": physician["full_name"], "cells": ["VL" if day_iso in scheduled_days else "" for day_iso in dates]})
    return {"year": year, "dates": dates, "rows": matrix}


def _request_row(request_id: int):
    return query_db(
        """
        SELECT vr.*, COALESCE(vr.request_display_name, u.full_name) AS full_name, u.username, u.email,
               actor.full_name AS created_by_name
        FROM vacation_requests vr
        LEFT JOIN users u ON u.id = vr.user_id
        LEFT JOIN users actor ON actor.id = vr.created_by_user_id
        WHERE vr.id = ?
        """,
        (request_id,),
        one=True,
    )


def _waitlist_decision_note(full_days: list[str]):
    preview = ", ".join(full_days[:5])
    suffix = "..." if len(full_days) > 5 else ""
    return f"Waitlisted because all vacation slots were filled for: {preview}{suffix}"


def _resolve_request_status(user_id: int, start_date: str, end_date: str, *, exclude_request_id: int | None = None):
    validation = validate_request_window(
        user_id,
        start_date,
        end_date,
        exclude_request_id=exclude_request_id,
        allow_full_days=True,
    )
    if validation["full_days"]:
        return {"status": "waitlisted", "decision_note": _waitlist_decision_note(validation["full_days"])}
    return {"status": "scheduled", "decision_note": ""}


def _promote_waitlisted_requests():
    promoted = []
    rows = query_db(
        """
        SELECT vr.*, COALESCE(vr.request_display_name, u.full_name) AS full_name, u.username, u.email
        FROM vacation_requests vr
        JOIN users u ON u.id = vr.user_id
        WHERE vr.status = 'waitlisted'
        ORDER BY vr.created_at ASC, vr.id ASC
        """
    )
    for row in rows:
        try:
            validate_request_window(row["user_id"], row["start_date"], row["end_date"], exclude_request_id=row["id"])
        except ValueError:
            continue
        now = iso_now()
        decision_note = "Promoted automatically from the waitlist when space became available."
        execute_db(
            """
            UPDATE vacation_requests
            SET status = 'scheduled', decision_note = ?, processed_at = ?, updated_at = ?, updated_by_user_id = NULL
            WHERE id = ?
            """,
            (decision_note, now, now, row["id"]),
        )
        send_email(
            to_email=row["email"],
            subject="Vacation waitlist promoted",
            body=(
                f"Hello {row['full_name']},\n\n"
                f"Your waitlisted vacation from {row['start_date']} to {row['end_date']} is now scheduled.\n"
                "A slot opened and the scheduler promoted your request automatically."
            ),
            purpose="waitlist-promoted",
            user_id=row["user_id"],
            request_id=row["id"],
        )
        record_activity(
            None,
            "waitlist-promoted",
            f"{row['full_name']} was promoted from the waitlist for {row['start_date']} to {row['end_date']}.",
            "vacation_request",
            row["id"],
            changes=[
                {"field_name": "status", "old_value": "waitlisted", "new_value": "scheduled"},
                {"field_name": "decision_note", "old_value": row["decision_note"] or "", "new_value": decision_note},
            ],
        )
        promoted.append(row["id"])
    return promoted


def _remove_range_from_requests(actor, target_user_id: int, start_date: str, end_date: str):
    rows = requests_overlapping_range(target_user_id, start_date, end_date)
    if not rows:
        return {"affectedCount": 0, "message": "No vacation entries overlapped that selection."}

    db = get_db()
    now = iso_now()
    affected_count = 0
    for row in rows:
        overlap_start = max(start_date, row["start_date"])
        overlap_end = min(end_date, row["end_date"])
        if overlap_start > overlap_end:
            continue
        affected_count += 1
        if overlap_start == row["start_date"] and overlap_end == row["end_date"]:
            db.execute(
                """
                UPDATE vacation_requests
                SET status = 'canceled', decision_note = ?, canceled_at = ?, canceled_by_user_id = ?, updated_at = ?, updated_by_user_id = ?
                WHERE id = ?
                """,
                (f"Removed {overlap_start} to {overlap_end} from the schedule.", now, actor["id"], now, actor["id"], row["id"]),
            )
        elif overlap_start == row["start_date"]:
            db.execute(
                """
                UPDATE vacation_requests
                SET start_date = ?, decision_note = ?, updated_at = ?, updated_by_user_id = ?
                WHERE id = ?
                """,
                ((date.fromisoformat(overlap_end) + timedelta(days=1)).isoformat(), f"Removed {overlap_start} to {overlap_end} from the selected range.", now, actor["id"], row["id"]),
            )
        elif overlap_end == row["end_date"]:
            db.execute(
                """
                UPDATE vacation_requests
                SET end_date = ?, decision_note = ?, updated_at = ?, updated_by_user_id = ?
                WHERE id = ?
                """,
                ((date.fromisoformat(overlap_start) - timedelta(days=1)).isoformat(), f"Removed {overlap_start} to {overlap_end} from the selected range.", now, actor["id"], row["id"]),
            )
        else:
            leading_end = (date.fromisoformat(overlap_start) - timedelta(days=1)).isoformat()
            trailing_start = (date.fromisoformat(overlap_end) + timedelta(days=1)).isoformat()
            db.execute(
                """
                UPDATE vacation_requests
                SET end_date = ?, decision_note = ?, updated_at = ?, updated_by_user_id = ?
                WHERE id = ?
                """,
                (leading_end, f"Removed {overlap_start} to {overlap_end} from the selected range.", now, actor["id"], row["id"]),
            )
            db.execute(
                """
                INSERT INTO vacation_requests
                (user_id, created_by_user_id, request_display_name, start_date, end_date, status, request_note, source_type, source_prompt, source_response,
                 decision_note, created_at, updated_at, updated_by_user_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["user_id"],
                    row["created_by_user_id"],
                    row["request_display_name"],
                    trailing_start,
                    row["end_date"],
                    row["status"],
                    row["request_note"],
                    row["source_type"],
                    row["source_prompt"],
                    row["source_response"],
                    f"Split automatically after removing {overlap_start} to {overlap_end}.",
                    now,
                    now,
                    actor["id"],
                ),
            )
        record_activity(
            actor["id"],
            "vacation-range-removed",
            f"{actor['full_name']} removed {overlap_start} to {overlap_end} from vacation entry #{row['id']}.",
            "vacation_request",
            row["id"],
            changes=[{"field_name": "removed_range", "old_value": f"{overlap_start} to {overlap_end}", "new_value": None}],
        )
    db.commit()
    _promote_waitlisted_requests()
    return {"affectedCount": affected_count, "message": f"Removed the selected range from {affected_count} vacation entr{'y' if affected_count == 1 else 'ies'}."}


def register_routes(app):
    @app.context_processor
    def inject_user():
        return {
            "nav_user": current_user(),
            "nav_managed_physicians": _manageable_physicians_payload(),
            "nav_physician_directory": _physician_directory_payload(),
            "theme_options": theme_options_payload(),
            "nav_breakout_scores": _breakout_score_payload(current_user()),
        }

    @app.route("/")
    def index():
        user = current_user()
        today = date.today()
        week_start = user["week_start"] if user else "sunday"
        show_week_numbers = bool(user["show_week_numbers"]) if user else False
        return render_template(
            "index.html",
            current_year=today.year,
            current_month=today.month,
            month_name=today.strftime("%B"),
            week_start=week_start,
            show_week_numbers=show_week_numbers,
            max_slots=app.config["MAX_DAILY_VACATION_SLOTS"],
        )

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            user = query_db(
                """
                SELECT u.*, s.week_start, s.show_week_numbers, s.theme_skin
                FROM users u
                LEFT JOIN user_settings s ON s.user_id = u.id
                WHERE u.username = ? AND u.is_active = 1 AND u.deleted_at IS NULL
                """,
                (username,),
                one=True,
            )
            if user and verify_password(password, user["password_hash"]):
                session["user_id"] = user["id"]
                destination = request.args.get("next") or url_for("index")
                return redirect(destination)
            flash("Invalid username or password.", "error")
        return render_template("login.html")

    @app.route("/forgot-password", methods=["GET", "POST"])
    def forgot_password():
        if request.method == "POST":
            identifier = request.form.get("identifier", "").strip()
            user = _active_user_by_identifier(identifier)
            result = None
            if user:
                result = _send_password_reset_email(user, lifetime_hours=2)
            feedback = _password_reset_feedback(result)
            flash(feedback["message"], "info" if feedback["toastType"] == "success" else "warning")
            return redirect(url_for("login"))
        return render_template("forgot_password.html")

    @app.post("/api/password-reset-request")
    def api_password_reset_request():
        identifier = request.form.get("identifier", "").strip()
        user = _active_user_by_identifier(identifier)
        result = _send_password_reset_email(user, lifetime_hours=2) if user else None
        feedback = _password_reset_feedback(result)
        return jsonify({"ok": True, **feedback})

    @app.route("/reset-password/<token>", methods=["GET", "POST"])
    def reset_password(token: str):
        token_row = query_db(
            """
            SELECT prt.*, u.full_name, u.username
            FROM password_reset_tokens prt
            JOIN users u ON u.id = prt.user_id
            WHERE prt.token = ? AND prt.used_at IS NULL AND prt.expires_at > ?
            """,
            (token, datetime.utcnow().isoformat(timespec="seconds")),
            one=True,
        )
        if not token_row:
            flash("That password reset link is invalid or has expired.", "error")
            return redirect(url_for("forgot_password"))

        if request.method == "POST":
            password = request.form.get("password", "")
            confirm_password = request.form.get("confirm_password", "")
            if len(password) < 8:
                flash("Use a password with at least 8 characters.", "error")
            elif password != confirm_password:
                flash("Passwords do not match.", "error")
            else:
                db = get_db()
                db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(password), token_row["user_id"]))
                db.execute("UPDATE password_reset_tokens SET used_at = ? WHERE id = ?", (iso_now(), token_row["id"]))
                db.commit()
                record_activity(
                    token_row["user_id"],
                    "password-reset-completed",
                    f"Password reset completed for {token_row['username']}.",
                    "user",
                    token_row["user_id"],
                )
                flash("Password updated. You can log in now.", "success")
                return redirect(url_for("login"))
        return render_template("reset_password.html", username=token_row["username"])

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.route("/history")
    @login_required
    def history():
        return render_template("history.html", rotation_years=_rotation_years(), current_year=date.today().year)

    @app.route("/holiday-rotation")
    def holiday_rotation():
        years = _rotation_years()
        selected_year = _parse_int(request.args.get("year"), _default_selected_year(years))
        if years and selected_year not in years:
            selected_year = _default_selected_year(years)
        return render_template(
            "holiday_rotation.html",
            rotation_years=years,
            selected_year=selected_year,
            rotation_groups=_rotation_view_model(selected_year) if years else [],
        )

    @app.route("/legacy-calendars")
    def legacy_calendars():
        years = legacy_calendar_years()
        selected_year = _parse_int(request.args.get("year"), years[-1] if years else date.today().year)
        if years and selected_year not in years:
            selected_year = years[-1]
        calendar_data = legacy_calendar_for_year(selected_year) if years else None
        return render_template(
            "legacy_calendars.html",
            legacy_years=years,
            selected_year=selected_year,
            calendar_data=calendar_data,
            legacy_documents=legacy_documents(),
        )

    @app.route("/vacation-guidelines")
    def vacation_guidelines():
        return render_template("vacation_guidelines.html")

    @app.route("/instructions")
    def instructions():
        return render_template("instructions.html")

    @app.route("/admin")
    @admin_required
    def admin():
        return render_template("admin.html", export_year=date.today().year)

    @app.get("/downloads/<int:document_id>")
    def download_document(document_id: int):
        doc = query_db("SELECT * FROM holiday_documents WHERE id = ?", (document_id,), one=True)
        if not doc:
            abort(404)
        return send_file(Path(doc["file_path"]), as_attachment=True, download_name=doc["file_name"])

    @app.get("/legacy-download/<path:file_name>")
    def download_legacy_document(file_name: str):
        for document in legacy_documents():
            if document["file_name"] == file_name:
                return send_file(document["path"], as_attachment=True, download_name=document["file_name"])
        abort(404)

    @app.get("/api/session")
    def api_session():
        actor = current_user()
        breakout_scores = _breakout_score_payload(actor)
        return jsonify(
            {
                "user": _current_user_payload(),
                "managedPhysicians": _manageable_physicians_payload(),
                "physicianDirectory": _physician_directory_payload(),
                "rotationYears": _rotation_years(),
                "gameHighScore": breakout_scores["highScore"],
                "gamePersonalBest": breakout_scores["personalBest"],
            }
        )

    @app.get("/api/game-score")
    def api_game_score():
        return jsonify(_breakout_score_payload(current_user()))

    @app.post("/api/game-score")
    @login_required
    def api_game_score_submit():
        actor = current_user()
        score = _parse_int(request.form.get("score"), None)
        elapsed_ms = _parse_int(request.form.get("elapsed_ms"), None)
        paddle_hits = _parse_int(request.form.get("paddle_hits"), 0)
        lives_left = _parse_int(request.form.get("lives_left"), 0)
        brick_count = _parse_int(request.form.get("brick_count"), 0)
        if score is None or elapsed_ms is None or score < 0 or elapsed_ms <= 0:
            return jsonify({"error": "Valid breakout score details are required."}), 400
        if paddle_hits is None or paddle_hits < 0 or lives_left is None or lives_left < 0 or brick_count is None or brick_count <= 0:
            return jsonify({"error": "Breakout stats were incomplete."}), 400

        existing = query_db("SELECT * FROM breakout_scores WHERE user_id = ?", (actor["id"],), one=True)

        def is_better(candidate, baseline):
            if not baseline:
                return True
            if candidate["score"] != baseline["score"]:
                return candidate["score"] > baseline["score"]
            if candidate["elapsed_ms"] != baseline["elapsed_ms"]:
                return candidate["elapsed_ms"] < baseline["elapsed_ms"]
            if candidate["paddle_hits"] != baseline["paddle_hits"]:
                return candidate["paddle_hits"] < baseline["paddle_hits"]
            if candidate["lives_left"] != baseline["lives_left"]:
                return candidate["lives_left"] > baseline["lives_left"]
            return candidate["brick_count"] > baseline["brick_count"]

        candidate = {
            "score": score,
            "elapsed_ms": elapsed_ms,
            "paddle_hits": paddle_hits,
            "lives_left": lives_left,
            "brick_count": brick_count,
        }
        improved = is_better(candidate, existing)
        if improved:
            now = iso_now()
            if existing:
                execute_db(
                    """
                    UPDATE breakout_scores
                    SET score = ?, elapsed_ms = ?, paddle_hits = ?, lives_left = ?, brick_count = ?, updated_at = ?
                    WHERE user_id = ?
                    """,
                    (score, elapsed_ms, paddle_hits, lives_left, brick_count, now, actor["id"]),
                )
            else:
                execute_db(
                    """
                    INSERT INTO breakout_scores (user_id, score, elapsed_ms, paddle_hits, lives_left, brick_count, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (actor["id"], score, elapsed_ms, paddle_hits, lives_left, brick_count, now, now),
                )

        payload = _breakout_score_payload(actor)
        is_global_high_score = payload["highScore"] and payload["highScore"]["userId"] == actor["id"] and payload["highScore"]["score"] == score
        if improved and is_global_high_score:
            message = f"New breakout high score: {score} by {actor['username']}."
        elif improved:
            message = f"Personal best updated to {score}."
        else:
            message = f"Score recorded. Personal best remains {payload['personalBest']['score']}."
        return jsonify({"ok": True, "improved": improved, "message": message, **payload})

    @app.get("/api/calendar")
    def api_calendar():
        user = current_user()
        today = date.today()
        year = int(request.args.get("year", today.year))
        month = int(request.args.get("month", today.month))
        week_start = request.args.get("weekStart") or (user["week_start"] if user else "sunday")
        show_week_numbers = request.args.get("showWeekNumbers")
        if show_week_numbers is None:
            show_week_numbers = bool(user["show_week_numbers"]) if user else False
        else:
            show_week_numbers = show_week_numbers.lower() == "true"
        return jsonify(
            {
                "year": year,
                "month": month,
                "monthName": calendar.month_name[month],
                "weekStart": week_start,
                "showWeekNumbers": show_week_numbers,
                "weeks": build_month_payload(year, month, week_start, show_week_numbers),
                "weekdayLabels": list(calendar.day_abbr[6:]) + list(calendar.day_abbr[:6])
                if week_start == "sunday"
                else list(calendar.day_abbr),
            }
        )

    @app.get("/api/day/<day_iso>")
    def api_day_details(day_iso: str):
        actor = current_user()
        holiday = holiday_for_day(day_iso)
        scheduled_rows = requests_for_day(day_iso, statuses=("scheduled",))
        waitlisted_rows = requests_for_day(day_iso, statuses=("waitlisted",))
        return jsonify(
            {
                "date": day_iso,
                "holiday": serialize_holiday(holiday) if holiday else None,
                "requests": [
                    {
                        "requestId": row["id"],
                        "physicianId": row["user_id"],
                        "physician": row["full_name"],
                        "username": row["username"],
                        "requestedBy": row["created_by_name"] or row["full_name"],
                        "startDate": row["start_date"],
                        "endDate": row["end_date"],
                        "status": row["status"],
                        "note": row["request_note"] or "",
                        "canManage": can_manage_request(actor, row),
                    }
                    for row in scheduled_rows
                ],
                "waitlistRequests": [
                    {
                        "requestId": row["id"],
                        "physicianId": row["user_id"],
                        "physician": row["full_name"],
                        "username": row["username"],
                        "requestedBy": row["created_by_name"] or row["full_name"],
                        "startDate": row["start_date"],
                        "endDate": row["end_date"],
                        "status": row["status"],
                        "note": row["request_note"] or "",
                        "canManage": can_manage_request(actor, row),
                    }
                    for row in waitlisted_rows
                ],
            }
        )

    @app.get("/api/requests")
    @login_required
    def api_requests():
        actor = current_user()
        rows = _requests_for_managed_physicians(actor)
        return jsonify({"requests": [serialize_request(row) for row in rows]})

    @app.get("/api/requests/<int:request_id>")
    @login_required
    def api_request_detail(request_id: int):
        actor = current_user()
        row = _request_row(request_id)
        if not row:
            abort(404)
        if not can_manage_request(actor, row):
            return jsonify({"error": "You cannot view that vacation entry."}), 403
        return jsonify({"request": serialize_request(row)})

    @app.post("/api/requests")
    @login_required
    def api_create_request():
        actor = current_user()
        target_user_id = _parse_int(request.form.get("physician_id"), actor["id"])
        if not can_manage_physician(actor, target_user_id):
            return jsonify({"error": "You cannot manage that physician's schedule."}), 403

        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()
        note = request.form.get("request_note", "").strip()
        try:
            resolution = _resolve_request_status(target_user_id, start_date, end_date)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        target_user = query_db("SELECT * FROM users WHERE id = ?", (target_user_id,), one=True)
        request_id = execute_db(
            """
            INSERT INTO vacation_requests
            (user_id, created_by_user_id, request_display_name, start_date, end_date, status, request_note, source_type, decision_note, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'manual', ?, ?, ?)
            """,
            (
                target_user_id,
                actor["id"],
                target_user["full_name"],
                start_date,
                end_date,
                resolution["status"],
                note,
                resolution["decision_note"],
                iso_now(),
                iso_now(),
            ),
        )
        record_activity(
            actor["id"],
            "vacation-created" if resolution["status"] == "scheduled" else "vacation-waitlisted",
            (
                f"{actor['full_name']} scheduled vacation for {target_user['full_name']} from {start_date} to {end_date}."
                if resolution["status"] == "scheduled"
                else f"{actor['full_name']} waitlisted vacation for {target_user['full_name']} from {start_date} to {end_date}."
            ),
            "vacation_request",
            request_id,
            changes=[
                {"field_name": "user_id", "old_value": None, "new_value": target_user_id},
                {"field_name": "start_date", "old_value": None, "new_value": start_date},
                {"field_name": "end_date", "old_value": None, "new_value": end_date},
                {"field_name": "request_note", "old_value": None, "new_value": note},
                {"field_name": "status", "old_value": None, "new_value": resolution["status"]},
                {"field_name": "decision_note", "old_value": None, "new_value": resolution["decision_note"]},
            ],
        )
        row = _request_row(request_id)
        return jsonify(
            {
                "request": serialize_request(row),
                "message": "Vacation scheduled." if resolution["status"] == "scheduled" else resolution["decision_note"],
            }
        )

    def _record_assistant_failure(actor, event_type: str, message: str, prompt_text: str, *, selected_physician_id=None, entity_id=None, parsed=None, error=None, extra_changes=None):
        changes = [
            {"field_name": "source_prompt", "old_value": None, "new_value": prompt_text},
            {"field_name": "selected_physician_id", "old_value": None, "new_value": selected_physician_id},
        ]
        if parsed is not None:
            changes.append({"field_name": "parsed_payload", "old_value": None, "new_value": str(parsed)})
        if error is not None:
            changes.append({"field_name": "error", "old_value": None, "new_value": str(error)})
        if extra_changes:
            changes.extend(extra_changes)
        record_activity(actor["id"], event_type, message, "vacation_request", entity_id, changes=changes)

    @app.post("/api/requests/assistant")
    @login_required
    def api_assistant_request():
        actor = current_user()
        selected_user_id = _parse_int(request.form.get("physician_id"))
        if selected_user_id and not can_manage_physician(actor, selected_user_id):
            return jsonify({"error": "You do not have permission to add vacation for that physician. Ask them to delegate scheduling access first."}), 403
        managed = _manageable_physicians_payload()
        if not managed:
            return jsonify({"error": "No physicians are available for this account."}), 400
        default_physician = next((item for item in managed if item["id"] == selected_user_id), managed[0])
        prompt_text = request.form.get("prompt", "").strip()
        unauthorized_physician = _prompt_mentions_unauthorized_physician(actor, prompt_text, managed)
        if unauthorized_physician:
            message = (
                f"You do not have permission to add vacation for {unauthorized_physician['full_name']}. "
                "Ask them to delegate scheduling access first."
            )
            _record_assistant_failure(
                actor,
                "assistant-request-permission-denied",
                f"Assistant request referenced unauthorized physician {unauthorized_physician['username']}.",
                prompt_text,
                selected_physician_id=selected_user_id or default_physician["id"],
                extra_changes=[
                    {"field_name": "attempted_physician_id", "old_value": None, "new_value": unauthorized_physician["id"]},
                ],
            )
            return jsonify({"error": message}), 403
        existing_requests = [serialize_request(row) for row in _requests_for_managed_physicians(actor)]

        try:
            parsed = parse_natural_language_request(prompt_text, managed, default_physician, existing_requests)
        except ValueError as exc:
            _record_assistant_failure(
                actor,
                "assistant-request-parse-failed",
                f"Assistant request failed for {default_physician['fullName']}: {exc}",
                prompt_text,
                selected_physician_id=default_physician["id"],
                error=exc,
            )
            return jsonify({"error": str(exc)}), 400
        except Exception as exc:
            current_app.logger.exception("Assistant request crashed during parsing.")
            _record_assistant_failure(
                actor,
                "assistant-request-system-error",
                f"Assistant request crashed for {default_physician['fullName']}: {exc}",
                prompt_text,
                selected_physician_id=default_physician["id"],
                error=exc,
            )
            return jsonify({"error": "The assistant request failed unexpectedly. Review the detailed admin log and try again."}), 500

        if not can_manage_physician(actor, parsed["physicianId"]):
            _record_assistant_failure(
                actor,
                "assistant-request-permission-denied",
                f"Assistant request attempted to manage unauthorized physician #{parsed['physicianId']}.",
                prompt_text,
                selected_physician_id=selected_user_id or default_physician["id"],
                parsed=parsed,
                extra_changes=[
                    {"field_name": "attempted_physician_id", "old_value": None, "new_value": parsed["physicianId"]},
                ],
            )
            return jsonify({"error": "You do not have permission to add vacation for that physician. Ask them to delegate scheduling access first.", "parsed": parsed}), 403

        action = parsed["action"]
        if action == "create":
            try:
                resolution = _resolve_request_status(parsed["physicianId"], parsed["startDate"], parsed["endDate"])
            except ValueError as exc:
                message = explain_conflict_naturally(prompt_text, str(exc))
                record_activity(
                    actor["id"],
                    "assistant-request-blocked",
                    f"Assistant request blocked for {parsed['physicianName']}: {exc}",
                    "vacation_request",
                    None,
                    changes=[
                        {"field_name": "source_prompt", "old_value": None, "new_value": prompt_text},
                        {"field_name": "physician_id", "old_value": None, "new_value": parsed["physicianId"]},
                        {"field_name": "start_date", "old_value": None, "new_value": parsed["startDate"]},
                        {"field_name": "end_date", "old_value": None, "new_value": parsed["endDate"]},
                        {"field_name": "error", "old_value": None, "new_value": str(exc)},
                    ],
                )
                return jsonify({"error": message, "parsed": parsed}), 400

            target_user = query_db("SELECT * FROM users WHERE id = ?", (parsed["physicianId"],), one=True)
            request_id = execute_db(
                """
                INSERT INTO vacation_requests
                (user_id, created_by_user_id, request_display_name, start_date, end_date, status, request_note, source_type, source_prompt, source_response, decision_note, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'assistant', ?, ?, ?, ?, ?)
                """,
                (
                    parsed["physicianId"],
                    actor["id"],
                    target_user["full_name"],
                    parsed["startDate"],
                    parsed["endDate"],
                    resolution["status"],
                    parsed["note"],
                    prompt_text,
                    parsed["explanation"],
                    resolution["decision_note"],
                    iso_now(),
                    iso_now(),
                ),
            )
            record_activity(
                actor["id"],
                "assistant-request-created" if resolution["status"] == "scheduled" else "assistant-request-waitlisted",
                (
                    f"Assistant scheduled vacation for {target_user['full_name']} from {parsed['startDate']} to {parsed['endDate']}."
                    if resolution["status"] == "scheduled"
                    else f"Assistant waitlisted vacation for {target_user['full_name']} from {parsed['startDate']} to {parsed['endDate']}."
                ),
                "vacation_request",
                request_id,
                changes=[
                    {"field_name": "source_type", "old_value": None, "new_value": "assistant"},
                    {"field_name": "source_prompt", "old_value": None, "new_value": prompt_text},
                    {"field_name": "start_date", "old_value": None, "new_value": parsed["startDate"]},
                    {"field_name": "end_date", "old_value": None, "new_value": parsed["endDate"]},
                    {"field_name": "status", "old_value": None, "new_value": resolution["status"]},
                    {"field_name": "decision_note", "old_value": None, "new_value": resolution["decision_note"]},
                ],
            )
            row = _request_row(request_id)
            return jsonify(
                {
                    "request": serialize_request(row),
                    "parsed": parsed | {"explanation": resolution["decision_note"] or parsed["explanation"]},
                    "message": "Vacation scheduled." if resolution["status"] == "scheduled" else resolution["decision_note"],
                }
            )

        request_row = _request_row(parsed["requestId"])
        if not request_row:
            return jsonify({"error": "The assistant selected a vacation entry that no longer exists.", "parsed": parsed}), 400
        if not can_manage_request(actor, request_row):
            return jsonify({"error": "You cannot manage that vacation entry.", "parsed": parsed}), 403

        if action == "update":
            target_user_id = parsed["physicianId"] or request_row["user_id"]
            if not can_manage_physician(actor, target_user_id):
                return jsonify({"error": "You cannot move that vacation entry to the selected physician.", "parsed": parsed}), 403
            try:
                resolution = _resolve_request_status(target_user_id, parsed["startDate"], parsed["endDate"], exclude_request_id=request_row["id"])
            except ValueError as exc:
                message = explain_conflict_naturally(prompt_text, str(exc))
                record_activity(
                    actor["id"],
                    "assistant-request-blocked",
                    f"Assistant update blocked for request #{request_row['id']}: {exc}",
                    "vacation_request",
                    request_row["id"],
                    changes=[
                        {"field_name": "source_prompt", "old_value": request_row["source_prompt"] or "", "new_value": prompt_text},
                        {"field_name": "start_date", "old_value": request_row["start_date"], "new_value": parsed["startDate"]},
                        {"field_name": "end_date", "old_value": request_row["end_date"], "new_value": parsed["endDate"]},
                        {"field_name": "error", "old_value": None, "new_value": str(exc)},
                    ],
                )
                return jsonify({"error": message, "parsed": parsed}), 400

            target_user = query_db("SELECT * FROM users WHERE id = ?", (target_user_id,), one=True)
            db = get_db()
            db.execute(
                """
                UPDATE vacation_requests
                SET user_id = ?, request_display_name = ?, start_date = ?, end_date = ?, status = ?, request_note = ?, source_type = 'assistant',
                    source_prompt = ?, source_response = ?, decision_note = ?, canceled_at = NULL, canceled_by_user_id = NULL,
                    updated_at = ?, updated_by_user_id = ?
                WHERE id = ?
                """,
                (
                    target_user_id,
                    target_user["full_name"],
                    parsed["startDate"],
                    parsed["endDate"],
                    resolution["status"],
                    parsed["note"],
                    prompt_text,
                    parsed["explanation"],
                    resolution["decision_note"],
                    iso_now(),
                    actor["id"],
                    request_row["id"],
                ),
            )
            db.commit()
            _promote_waitlisted_requests()
            record_activity(
                actor["id"],
                "assistant-request-updated",
                f"Assistant updated vacation entry #{request_row['id']}.",
                "vacation_request",
                request_row["id"],
                changes=[
                    {"field_name": "start_date", "old_value": request_row["start_date"], "new_value": parsed["startDate"]},
                    {"field_name": "end_date", "old_value": request_row["end_date"], "new_value": parsed["endDate"]},
                    {"field_name": "status", "old_value": request_row["status"], "new_value": resolution["status"]},
                    {"field_name": "source_prompt", "old_value": request_row["source_prompt"] or "", "new_value": prompt_text},
                ],
            )
            row = _request_row(request_row["id"])
            return jsonify(
                {
                    "request": serialize_request(row),
                    "parsed": parsed | {"explanation": resolution["decision_note"] or parsed["explanation"]},
                    "message": "Vacation updated." if resolution["status"] == "scheduled" else resolution["decision_note"],
                }
            )

        if action == "cancel":
            if request_row["status"] != "canceled":
                execute_db(
                    """
                    UPDATE vacation_requests
                    SET status = 'canceled', decision_note = ?, canceled_at = ?, canceled_by_user_id = ?, updated_at = ?, updated_by_user_id = ?
                    WHERE id = ?
                    """,
                    ("Canceled by assistant instruction.", iso_now(), actor["id"], iso_now(), actor["id"], request_row["id"]),
                )
                record_activity(
                    actor["id"],
                    "assistant-request-canceled",
                    f"Assistant canceled vacation entry #{request_row['id']}.",
                    "vacation_request",
                    request_row["id"],
                    changes=[{"field_name": "status", "old_value": request_row["status"], "new_value": "canceled"}],
                )
                _promote_waitlisted_requests()
            return jsonify({"ok": True, "parsed": parsed, "message": "Vacation removed."})

        if action == "remove_days":
            result = _remove_range_from_requests(actor, request_row["user_id"], parsed["removeStartDate"], parsed["removeEndDate"])
            record_activity(
                actor["id"],
                "assistant-request-range-removed",
                f"Assistant removed {parsed['removeStartDate']} to {parsed['removeEndDate']} from request #{request_row['id']}.",
                "vacation_request",
                request_row["id"],
                changes=[
                    {"field_name": "source_prompt", "old_value": request_row["source_prompt"] or "", "new_value": prompt_text},
                    {"field_name": "remove_start_date", "old_value": None, "new_value": parsed["removeStartDate"]},
                    {"field_name": "remove_end_date", "old_value": None, "new_value": parsed["removeEndDate"]},
                ],
            )
            return jsonify({"ok": True, "parsed": parsed, "message": result["message"]})

        return jsonify({"error": "The assistant returned an unsupported action.", "parsed": parsed}), 400

    @app.post("/api/requests/<int:request_id>")
    @login_required
    def api_update_request(request_id: int):
        actor = current_user()
        row = query_db(
            """
            SELECT vr.*, COALESCE(vr.request_display_name, u.full_name) AS full_name, u.username, u.email
            FROM vacation_requests vr
            LEFT JOIN users u ON u.id = vr.user_id
            WHERE vr.id = ?
            """,
            (request_id,),
            one=True,
        )
        if not row:
            abort(404)
        if not can_manage_request(actor, row):
            return jsonify({"error": "You cannot edit that vacation entry."}), 403

        target_user_id = _parse_int(request.form.get("physician_id"), row["user_id"])
        if not can_manage_physician(actor, target_user_id):
            return jsonify({"error": "You cannot move that vacation entry to the selected physician."}), 403

        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()
        note = request.form.get("request_note", "").strip()
        try:
            resolution = _resolve_request_status(target_user_id, start_date, end_date, exclude_request_id=request_id)
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

        target_user = query_db("SELECT * FROM users WHERE id = ?", (target_user_id,), one=True)
        db = get_db()
        db.execute(
            """
            UPDATE vacation_requests
            SET user_id = ?, request_display_name = ?, start_date = ?, end_date = ?, status = ?, request_note = ?, decision_note = ?,
                canceled_at = NULL, canceled_by_user_id = NULL, updated_at = ?, updated_by_user_id = ?
            WHERE id = ?
            """,
            (
                target_user_id,
                target_user["full_name"],
                start_date,
                end_date,
                resolution["status"],
                note,
                resolution["decision_note"],
                iso_now(),
                actor["id"],
                request_id,
            ),
        )
        db.commit()
        _promote_waitlisted_requests()
        changes = []
        if row["user_id"] != target_user_id:
            changes.append({"field_name": "user_id", "old_value": row["user_id"], "new_value": target_user_id})
        if row["start_date"] != start_date:
            changes.append({"field_name": "start_date", "old_value": row["start_date"], "new_value": start_date})
        if row["end_date"] != end_date:
            changes.append({"field_name": "end_date", "old_value": row["end_date"], "new_value": end_date})
        if row["status"] != resolution["status"]:
            changes.append({"field_name": "status", "old_value": row["status"], "new_value": resolution["status"]})
        if (row["request_note"] or "") != note:
            changes.append({"field_name": "request_note", "old_value": row["request_note"] or "", "new_value": note})
        if (row["decision_note"] or "") != resolution["decision_note"]:
            changes.append({"field_name": "decision_note", "old_value": row["decision_note"] or "", "new_value": resolution["decision_note"]})
        record_activity(
            actor["id"],
            "vacation-updated",
            f"{actor['full_name']} updated vacation entry #{request_id}.",
            "vacation_request",
            request_id,
            changes=changes,
        )
        refreshed = _request_row(request_id)
        return jsonify(
            {
                "request": serialize_request(refreshed),
                "message": "Vacation scheduled." if resolution["status"] == "scheduled" else resolution["decision_note"],
            }
        )

    @app.post("/api/requests/<int:request_id>/cancel")
    @login_required
    def api_cancel_request(request_id: int):
        actor = current_user()
        row = query_db("SELECT * FROM vacation_requests WHERE id = ?", (request_id,), one=True)
        if not row:
            abort(404)
        if not can_manage_request(actor, row):
            return jsonify({"error": "You cannot cancel that vacation entry."}), 403
        if row["status"] == "canceled":
            return jsonify({"ok": True})
        execute_db(
            """
            UPDATE vacation_requests
            SET status = 'canceled', canceled_at = ?, canceled_by_user_id = ?, updated_at = ?, updated_by_user_id = ?
            WHERE id = ?
            """,
            (iso_now(), actor["id"], iso_now(), actor["id"], request_id),
        )
        record_activity(
            actor["id"],
            "vacation-canceled",
            f"{actor['full_name']} canceled vacation entry #{request_id}.",
            "vacation_request",
            request_id,
            changes=[{"field_name": "status", "old_value": row["status"], "new_value": "canceled"}],
        )
        _promote_waitlisted_requests()
        return jsonify({"ok": True, "message": "Vacation removed."})

    @app.post("/api/requests/<int:request_id>/remove-day/<day_iso>")
    @login_required
    def api_remove_request_day(request_id: int, day_iso: str):
        actor = current_user()
        row = query_db("SELECT * FROM vacation_requests WHERE id = ?", (request_id,), one=True)
        if not row:
            abort(404)
        if not can_manage_request(actor, row):
            return jsonify({"error": "You cannot remove that physician from this day."}), 403
        if row["status"] != "scheduled":
            return jsonify({"error": "Only scheduled vacation can be removed from a specific day."}), 400
        if day_iso < row["start_date"] or day_iso > row["end_date"]:
            return jsonify({"error": "That day is not inside the selected vacation range."}), 400

        current_day = date.fromisoformat(day_iso)
        now = iso_now()
        db = get_db()
        created_split_request_id = None
        if row["start_date"] == row["end_date"] == day_iso:
            db.execute(
                """
                UPDATE vacation_requests
                SET status = 'canceled', decision_note = ?, canceled_at = ?, canceled_by_user_id = ?, updated_at = ?, updated_by_user_id = ?
                WHERE id = ?
                """,
                (f"Removed {day_iso} from the schedule.", now, actor["id"], now, actor["id"], request_id),
            )
        elif day_iso == row["start_date"]:
            db.execute(
                """
                UPDATE vacation_requests
                SET start_date = ?, decision_note = ?, updated_at = ?, updated_by_user_id = ?
                WHERE id = ?
                """,
                ((current_day + timedelta(days=1)).isoformat(), f"Removed {day_iso} from the scheduled range.", now, actor["id"], request_id),
            )
        elif day_iso == row["end_date"]:
            db.execute(
                """
                UPDATE vacation_requests
                SET end_date = ?, decision_note = ?, updated_at = ?, updated_by_user_id = ?
                WHERE id = ?
                """,
                ((current_day - timedelta(days=1)).isoformat(), f"Removed {day_iso} from the scheduled range.", now, actor["id"], request_id),
            )
        else:
            first_end = (current_day - timedelta(days=1)).isoformat()
            second_start = (current_day + timedelta(days=1)).isoformat()
            db.execute(
                """
                UPDATE vacation_requests
                SET end_date = ?, decision_note = ?, updated_at = ?, updated_by_user_id = ?
                WHERE id = ?
                """,
                (first_end, f"Removed {day_iso} from the scheduled range.", now, actor["id"], request_id),
            )
            created_split_request_id = db.execute(
                """
                INSERT INTO vacation_requests
                (user_id, created_by_user_id, request_display_name, start_date, end_date, status, request_note, source_type, source_prompt, source_response,
                 decision_note, created_at, updated_at, updated_by_user_id)
                VALUES (?, ?, ?, ?, ?, 'scheduled', ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["user_id"],
                    row["created_by_user_id"],
                    row["request_display_name"],
                    second_start,
                    row["end_date"],
                    row["request_note"],
                    row["source_type"],
                    row["source_prompt"],
                    row["source_response"],
                    f"Split automatically after removing {day_iso}.",
                    now,
                    now,
                    actor["id"],
                ),
            ).lastrowid
        db.commit()
        record_activity(
            actor["id"],
            "vacation-day-removed",
            f"{actor['full_name']} removed {day_iso} from vacation entry #{request_id}.",
            "vacation_request",
            request_id,
            changes=[{"field_name": "removed_day", "old_value": day_iso, "new_value": None}],
        )
        if created_split_request_id:
            record_activity(
                actor["id"],
                "vacation-split-created",
                f"{actor['full_name']} created split vacation entry #{created_split_request_id} after removing {day_iso}.",
                "vacation_request",
                created_split_request_id,
                changes=[
                    {"field_name": "start_date", "old_value": None, "new_value": second_start},
                    {"field_name": "end_date", "old_value": None, "new_value": row["end_date"]},
                ],
            )
        _promote_waitlisted_requests()
        return jsonify({"ok": True, "message": f"Removed {day_iso} from the vacation schedule."})

    @app.post("/api/requests/unassign-range")
    @login_required
    def api_unassign_range():
        actor = current_user()
        target_user_id = _parse_int(request.form.get("physician_id"), actor["id"])
        if not can_manage_physician(actor, target_user_id):
            return jsonify({"error": "You cannot manage that physician's schedule."}), 403

        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()
        if not start_date or not end_date:
            return jsonify({"error": "Start and end dates are required."}), 400
        if end_date < start_date:
            return jsonify({"error": "End date must be on or after the start date."}), 400
        result = _remove_range_from_requests(actor, target_user_id, start_date, end_date)
        return jsonify({"ok": True, **result})

    @app.post("/api/settings")
    @login_required
    def api_settings():
        user = current_user()
        week_start = request.form.get("week_start", "sunday")
        show_week_numbers = 1 if request.form.get("show_week_numbers") == "true" else 0
        theme_skin = request.form.get("theme_skin", user["theme_skin"] or "slate").strip() or "slate"
        if week_start not in {"sunday", "monday"}:
            return jsonify({"error": "Invalid week start."}), 400
        if theme_skin not in THEME_CHOICES:
            return jsonify({"error": "Invalid theme selection."}), 400
        execute_db(
            """
            UPDATE user_settings
            SET week_start = ?, show_week_numbers = ?, theme_skin = ?
            WHERE user_id = ?
            """,
            (week_start, show_week_numbers, theme_skin, user["id"]),
        )
        record_activity(
            user["id"],
            "settings-updated",
            f"{user['full_name']} updated calendar settings.",
            "user",
            user["id"],
            changes=[
                {"field_name": "week_start", "old_value": user["week_start"], "new_value": week_start},
                {"field_name": "show_week_numbers", "old_value": user["show_week_numbers"], "new_value": show_week_numbers},
                {"field_name": "theme_skin", "old_value": user["theme_skin"] or "slate", "new_value": theme_skin},
            ],
        )
        return jsonify({"ok": True, "message": "Settings updated."})

    @app.post("/api/settings/password")
    @login_required
    def api_settings_password():
        user = current_user()
        current_password = request.form.get("current_password", "")
        new_password = request.form.get("new_password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not verify_password(current_password, user["password_hash"]):
            return jsonify({"error": "Current password is incorrect."}), 400
        if len(new_password) < 8:
            return jsonify({"error": "Use a password with at least 8 characters."}), 400
        if new_password != confirm_password:
            return jsonify({"error": "Passwords do not match."}), 400
        execute_db("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password(new_password), user["id"]))
        record_activity(
            user["id"],
            "password-changed",
            f"{user['full_name']} changed their password.",
            "user",
            user["id"],
            changes=[{"field_name": "password_hash", "old_value": "<redacted>", "new_value": "<updated>"}],
        )
        return jsonify({"ok": True, "message": "Password updated."})

    @app.get("/api/delegations")
    @login_required
    def api_delegations():
        return jsonify(_delegations_for_actor(current_user()))

    @app.post("/api/delegations")
    @login_required
    def api_create_delegation():
        actor = current_user()
        delegate_user_id = _parse_int(request.form.get("delegate_user_id"))
        if not delegate_user_id:
            return jsonify({"error": "Select a delegate physician."}), 400
        if delegate_user_id == actor["id"]:
            return jsonify({"error": "You cannot delegate to yourself."}), 400
        delegate = query_db(
            "SELECT * FROM users WHERE id = ? AND role = 'physician' AND is_active = 1 AND deleted_at IS NULL",
            (delegate_user_id,),
            one=True,
        )
        if not delegate:
            return jsonify({"error": "That delegate physician is not available."}), 400
        db = get_db()
        try:
            delegation_id = db.execute(
                """
                INSERT INTO user_delegations (owner_user_id, delegate_user_id, created_at)
                VALUES (?, ?, ?)
                """,
                (actor["id"], delegate_user_id, iso_now()),
            ).lastrowid
            db.commit()
        except Exception as exc:
            db.rollback()
            return jsonify({"error": f"Unable to save delegation: {exc}"}), 400
        record_activity(
            actor["id"],
            "delegation-created",
            f"{actor['full_name']} delegated schedule access to {delegate['full_name']}.",
            "delegation",
            delegation_id,
            changes=[{"field_name": "delegate_user_id", "old_value": None, "new_value": delegate_user_id}],
        )
        return jsonify(_delegations_for_actor(actor))

    @app.post("/api/delegations/<int:delegation_id>/delete")
    @login_required
    def api_delete_delegation(delegation_id: int):
        actor = current_user()
        delegation = query_db("SELECT * FROM user_delegations WHERE id = ?", (delegation_id,), one=True)
        if not delegation:
            abort(404)
        if actor["role"] != "admin" and delegation["owner_user_id"] != actor["id"]:
            return jsonify({"error": "Only the physician who granted delegation can remove it."}), 403
        execute_db("DELETE FROM user_delegations WHERE id = ?", (delegation_id,))
        record_activity(
            actor["id"],
            "delegation-deleted",
            f"{actor['full_name']} removed delegation #{delegation_id}.",
            "delegation",
            delegation_id,
            changes=[{"field_name": "delegate_user_id", "old_value": delegation["delegate_user_id"], "new_value": None}],
        )
        owner = actor if actor["role"] != "admin" else query_db("SELECT * FROM users WHERE id = ?", (delegation["owner_user_id"],), one=True)
        return jsonify(_delegations_for_actor(owner))

    @app.get("/api/rotation")
    def api_rotation():
        years = _rotation_years()
        selected_year = _parse_int(request.args.get("year"), _default_selected_year(years))
        if years and selected_year not in years:
            selected_year = _default_selected_year(years)
        actor = current_user()
        user_holidays = []
        if actor and actor["role"] == "physician":
            user_holidays = [
                {"holidayKey": row["holiday_key"], "holidayTitle": row["holiday_title"], "category": row["category"]}
                for row in _trade_candidate_holidays(actor["id"], selected_year)
            ]
        return jsonify({"years": years, "selectedYear": selected_year, "groups": _rotation_view_model(selected_year), "myHolidays": user_holidays})

    @app.get("/api/trades")
    @login_required
    def api_trades():
        return jsonify({"trades": _trades_for_actor(current_user())})

    @app.post("/api/trades")
    @login_required
    def api_create_trade():
        actor = current_user()
        year = _parse_int(request.form.get("year"), date.today().year)
        offered_to_user_id = _parse_int(request.form.get("offered_to_user_id"))
        offered_holiday_key = request.form.get("offered_holiday_key", "").strip()
        requested_holiday_key = request.form.get("requested_holiday_key", "").strip()
        note = request.form.get("note", "").strip()

        if not offered_to_user_id or not offered_holiday_key or not requested_holiday_key:
            return jsonify({"error": "Trade year, target physician, and both holidays are required."}), 400

        my_assignment = query_db(
            """
            SELECT *
            FROM holiday_rotation_assignments
            WHERE year = ? AND holiday_key = ? AND user_id = ?
            """,
            (year, offered_holiday_key, actor["id"]),
            one=True,
        )
        their_assignment = query_db(
            """
            SELECT *
            FROM holiday_rotation_assignments
            WHERE year = ? AND holiday_key = ? AND user_id = ?
            """,
            (year, requested_holiday_key, offered_to_user_id),
            one=True,
        )
        if not my_assignment:
            return jsonify({"error": "You do not currently hold that holiday for the selected year."}), 400
        if not their_assignment:
            return jsonify({"error": "The selected physician does not hold the requested holiday for that year."}), 400
        if my_assignment["category"] != their_assignment["category"]:
            return jsonify({"error": "Holiday trades must stay within the same category (major for major, minor for minor)."}), 400

        trade_id = execute_db(
            """
            INSERT INTO holiday_trade_offers
            (year, offered_by_user_id, offered_to_user_id, offered_holiday_key, requested_holiday_key, note, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)
            """,
            (year, actor["id"], offered_to_user_id, offered_holiday_key, requested_holiday_key, note, iso_now()),
        )
        offered_to = query_db("SELECT full_name, email FROM users WHERE id = ?", (offered_to_user_id,), one=True)
        send_email(
            to_email=offered_to["email"],
            subject="Holiday trade offer",
            body=(
                f"Hello {offered_to['full_name']},\n\n"
                f"{actor['full_name']} offered a holiday trade for {year}.\n"
                f"Offered: {my_assignment['holiday_title']}\n"
                f"Requested: {their_assignment['holiday_title']}\n"
                f"Note: {note or 'No note provided.'}\n\n"
                "Log in to South Bay ED VL Schedule to accept or reject the trade."
            ),
            purpose="holiday-trade-offer",
            user_id=offered_to_user_id,
        )
        record_activity(
            actor["id"],
            "trade-offered",
            f"{actor['full_name']} offered a holiday trade to {offered_to['full_name']} for {year}.",
            "holiday_trade",
            trade_id,
            changes=[
                {"field_name": "offered_holiday_key", "old_value": None, "new_value": offered_holiday_key},
                {"field_name": "requested_holiday_key", "old_value": None, "new_value": requested_holiday_key},
            ],
        )
        return jsonify({"trades": _trades_for_actor(actor)})

    @app.post("/api/trades/<int:trade_id>/respond")
    @login_required
    def api_respond_trade(trade_id: int):
        actor = current_user()
        action = request.form.get("action", "").strip().lower()
        if action not in {"accept", "reject", "cancel"}:
            return jsonify({"error": "Invalid trade response."}), 400
        trade = query_db("SELECT * FROM holiday_trade_offers WHERE id = ?", (trade_id,), one=True)
        if not trade:
            abort(404)
        if trade["status"] != "pending":
            return jsonify({"error": "That trade is no longer pending."}), 400

        db = get_db()
        now = iso_now()
        if action == "accept":
            if actor["role"] != "admin" and trade["offered_to_user_id"] != actor["id"]:
                return jsonify({"error": "Only the invited physician can respond to this trade."}), 403
            offered_assignment = db.execute(
                """
                SELECT * FROM holiday_rotation_assignments
                WHERE year = ? AND holiday_key = ? AND user_id = ?
                """,
                (trade["year"], trade["offered_holiday_key"], trade["offered_by_user_id"]),
            ).fetchone()
            requested_assignment = db.execute(
                """
                SELECT * FROM holiday_rotation_assignments
                WHERE year = ? AND holiday_key = ? AND user_id = ?
                """,
                (trade["year"], trade["requested_holiday_key"], trade["offered_to_user_id"]),
            ).fetchone()
            if not offered_assignment or not requested_assignment:
                return jsonify({"error": "The underlying holiday assignments no longer match this trade."}), 400
            db.execute(
                "UPDATE holiday_rotation_assignments SET user_id = ?, updated_at = ? WHERE id = ?",
                (trade["offered_to_user_id"], now, offered_assignment["id"]),
            )
            db.execute(
                "UPDATE holiday_rotation_assignments SET user_id = ?, updated_at = ? WHERE id = ?",
                (trade["offered_by_user_id"], now, requested_assignment["id"]),
            )
            db.execute(
                """
                UPDATE holiday_trade_offers
                SET status = 'accepted', responded_at = ?, responded_by_user_id = ?
                WHERE id = ?
                """,
                (now, actor["id"], trade_id),
            )
            db.commit()
            record_activity(
                actor["id"],
                "trade-accepted",
                f"{actor['full_name']} accepted holiday trade #{trade_id}.",
                "holiday_trade",
                trade_id,
                changes=[{"field_name": "status", "old_value": "pending", "new_value": "accepted"}],
            )
        elif action == "reject":
            if actor["role"] != "admin" and trade["offered_to_user_id"] != actor["id"]:
                return jsonify({"error": "Only the invited physician can respond to this trade."}), 403
            db.execute(
                """
                UPDATE holiday_trade_offers
                SET status = 'rejected', responded_at = ?, responded_by_user_id = ?
                WHERE id = ?
                """,
                (now, actor["id"], trade_id),
            )
            db.commit()
            record_activity(
                actor["id"],
                "trade-rejected",
                f"{actor['full_name']} rejected holiday trade #{trade_id}.",
                "holiday_trade",
                trade_id,
                changes=[{"field_name": "status", "old_value": "pending", "new_value": "rejected"}],
            )
        else:
            if actor["role"] != "admin" and trade["offered_by_user_id"] != actor["id"]:
                return jsonify({"error": "Only the physician who sent the offer can cancel it."}), 403
            db.execute(
                """
                UPDATE holiday_trade_offers
                SET status = 'canceled', responded_at = ?, responded_by_user_id = ?
                WHERE id = ?
                """,
                (now, actor["id"], trade_id),
            )
            db.commit()
            record_activity(
                actor["id"],
                "trade-canceled",
                f"{actor['full_name']} canceled holiday trade #{trade_id}.",
                "holiday_trade",
                trade_id,
                changes=[{"field_name": "status", "old_value": "pending", "new_value": "canceled"}],
            )
        return jsonify({"trades": _trades_for_actor(actor)})

    @app.post("/api/admin/trades/cancel-pending")
    @admin_required
    def api_admin_cancel_pending_trades():
        admin_user = current_user()
        pending_trades = query_db("SELECT id FROM holiday_trade_offers WHERE status = 'pending' ORDER BY id ASC")
        if not pending_trades:
            return jsonify({"ok": True, "canceledCount": 0})
        now = iso_now()
        execute_db(
            """
            UPDATE holiday_trade_offers
            SET status = 'canceled', responded_at = ?, responded_by_user_id = ?
            WHERE status = 'pending'
            """,
            (now, admin_user["id"]),
        )
        for trade in pending_trades:
            record_activity(
                admin_user["id"],
                "trade-canceled",
                f"{admin_user['full_name']} canceled holiday trade #{trade['id']} from the admin console.",
                "holiday_trade",
                trade["id"],
                changes=[{"field_name": "status", "old_value": "pending", "new_value": "canceled"}],
            )
        return jsonify({"ok": True, "canceledCount": len(pending_trades)})

    @app.get("/api/admin/users")
    @admin_required
    def api_admin_users():
        users = query_db(
            """
            SELECT u.*, s.week_start, s.show_week_numbers
            FROM users u
            LEFT JOIN user_settings s ON s.user_id = u.id
            WHERE u.deleted_at IS NULL
            ORDER BY u.role DESC, u.full_name COLLATE NOCASE ASC
            """
        )
        return jsonify({"users": [serialize_user(row) for row in users]})

    @app.post("/api/admin/users")
    @admin_required
    def api_admin_create_user():
        admin_user = current_user()
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        role = request.form.get("role", "physician").strip()
        provisioning_mode = request.form.get("provisioning_mode", "reset_link").strip() or "reset_link"
        if not all([full_name, username, email]) or role not in {"physician", "admin"}:
            return jsonify({"error": "Full name, username, email, and role are required."}), 400
        if provisioning_mode not in {"reset_link", "manual_password", "random_password"}:
            return jsonify({"error": "Choose how the new user should set their password."}), 400

        if provisioning_mode == "manual_password":
            if not password:
                return jsonify({"error": "Enter a password or choose a different setup option."}), 400
            if len(password) < 8:
                return jsonify({"error": "Use a password with at least 8 characters."}), 400
            if password != confirm_password:
                return jsonify({"error": "Passwords do not match."}), 400
            issued_password = password
        elif provisioning_mode == "random_password":
            issued_password = _generate_temporary_password()
        else:
            issued_password = _generate_temporary_password(18)

        db = get_db()
        try:
            user_id = db.execute(
                """
                INSERT INTO users (username, full_name, email, password_hash, role, annual_day_limit)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (username, full_name, email, hash_password(issued_password), role, 0),
            ).lastrowid
            db.execute(
                "INSERT INTO user_settings (user_id, week_start, show_week_numbers, theme_skin) VALUES (?, 'sunday', 0, 'slate')",
                (user_id,),
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            return jsonify({"error": f"Unable to create user: {exc}"}), 400

        email_result = None
        if provisioning_mode == "reset_link":
            token, _ = _issue_password_reset_token(user_id, lifetime_hours=72)
            reset_link = url_for("reset_password", token=token, _external=True)
            email_result = send_email(
                to_email=email,
                subject="Set up your South Bay ED VL Schedule password",
                body=(
                    f"Hello {full_name},\n\n"
                    "A South Bay ED VL Schedule account has been created for you.\n"
                    f"Username: {username}\n"
                    f"Use this link to choose your password: {reset_link}\n\n"
                    "This setup link expires automatically. If it expires, use the Forgot Password page to request a new one."
                ),
                purpose="new-user-reset-link",
                user_id=user_id,
            )
        elif provisioning_mode == "random_password":
            email_result = send_email(
                to_email=email,
                subject="Your South Bay ED VL Schedule account",
                body=(
                    f"Hello {full_name},\n\n"
                    "A South Bay ED VL Schedule account has been created for you.\n"
                    f"Username: {username}\n"
                    f"Temporary password: {issued_password}\n"
                    "Please log in and change it using the password reset flow if needed."
                ),
                purpose="new-user-password",
                user_id=user_id,
            )
        record_activity(
            admin_user["id"],
            "user-created",
            f"{admin_user['full_name']} created user {username}.",
            "user",
            user_id,
            changes=[
                {"field_name": "username", "old_value": None, "new_value": username},
                {"field_name": "email", "old_value": None, "new_value": email},
                {"field_name": "role", "old_value": None, "new_value": role},
                {"field_name": "provisioning_mode", "old_value": None, "new_value": provisioning_mode},
            ],
        )
        if provisioning_mode == "manual_password":
            return jsonify(
                {
                    "ok": True,
                    "message": f"Created {full_name} with a manually set password.",
                    "toastType": "success",
                    "deliveryStatus": "not-requested",
                }
            )

        if provisioning_mode == "reset_link":
            feedback = _email_delivery_feedback(
                email_result,
                sent_message=f"Created {full_name} and emailed a password setup link.",
                fallback_message=(
                    f"Created {full_name}, but the password setup email was not sent. "
                    "Check Gmail or SMTP settings, or retrieve the link from email_log."
                ),
            )
        else:
            feedback = _email_delivery_feedback(
                email_result,
                sent_message=f"Created {full_name} and emailed a temporary password.",
                fallback_message=(
                    f"Created {full_name}, but the temporary password email was not sent. "
                    "Check Gmail or SMTP settings, or retrieve it from email_log."
                ),
            )
        return jsonify({"ok": True, **feedback})

    @app.post("/api/admin/users/<int:user_id>")
    @admin_required
    def api_admin_update_user(user_id: int):
        admin_user = current_user()
        user = query_db("SELECT * FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,), one=True)
        if not user:
            abort(404)
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        role = request.form.get("role", "").strip()
        password = request.form.get("password", "").strip()
        confirm_password = request.form.get("confirm_password", "").strip()
        if not all([full_name, username, email]) or role not in {"physician", "admin"}:
            return jsonify({"error": "Full name, username, email, and role are required."}), 400
        if password and password != confirm_password:
            return jsonify({"error": "Passwords do not match."}), 400

        db = get_db()
        try:
            if password:
                db.execute(
                    """
                    UPDATE users
                    SET full_name = ?, username = ?, email = ?, role = ?, annual_day_limit = 0, password_hash = ?
                    WHERE id = ?
                    """,
                    (full_name, username, email, role, hash_password(password), user_id),
                )
            else:
                db.execute(
                    """
                    UPDATE users
                    SET full_name = ?, username = ?, email = ?, role = ?, annual_day_limit = 0
                    WHERE id = ?
                    """,
                    (full_name, username, email, role, user_id),
                )
            db.execute("UPDATE vacation_requests SET request_display_name = ? WHERE user_id = ?", (full_name, user_id))
            db.commit()
        except Exception as exc:
            db.rollback()
            return jsonify({"error": f"Unable to update user: {exc}"}), 400

        changes = []
        for field_name, old_value, new_value in [
            ("full_name", user["full_name"], full_name),
            ("username", user["username"], username),
            ("email", user["email"], email),
            ("role", user["role"], role),
        ]:
            if old_value != new_value:
                changes.append({"field_name": field_name, "old_value": old_value, "new_value": new_value})
        if user["annual_day_limit"] != 0:
            changes.append({"field_name": "annual_day_limit", "old_value": user["annual_day_limit"], "new_value": 0})
        if password:
            changes.append({"field_name": "password_hash", "old_value": "<redacted>", "new_value": "<updated>"})
        record_activity(
            admin_user["id"],
            "user-updated",
            f"{admin_user['full_name']} updated user {username}.",
            "user",
            user_id,
            changes=changes,
        )
        return jsonify({"ok": True, "message": f"Updated {full_name}."})

    @app.post("/api/admin/users/<int:user_id>/toggle")
    @admin_required
    def api_admin_toggle_user(user_id: int):
        admin_user = current_user()
        user = query_db("SELECT * FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,), one=True)
        if not user:
            abort(404)
        if admin_user["id"] == user_id:
            return jsonify({"error": "You cannot disable the currently logged-in admin."}), 400
        new_state = 0 if user["is_active"] else 1
        execute_db("UPDATE users SET is_active = ? WHERE id = ?", (new_state, user_id))
        record_activity(
            admin_user["id"],
            "user-toggled",
            f"{admin_user['full_name']} {'enabled' if new_state else 'disabled'} {user['username']}.",
            "user",
            user_id,
            changes=[{"field_name": "is_active", "old_value": user["is_active"], "new_value": new_state}],
        )
        return jsonify({"ok": True})

    @app.post("/api/admin/users/<int:user_id>/delete")
    @admin_required
    def api_admin_delete_user(user_id: int):
        admin_user = current_user()
        if admin_user["id"] == user_id:
            return jsonify({"error": "You cannot delete the currently logged-in admin."}), 400
        user = query_db("SELECT * FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,), one=True)
        if not user:
            abort(404)
        deleted_at = iso_now()
        execute_db("UPDATE users SET deleted_at = ?, is_active = 0 WHERE id = ?", (deleted_at, user_id))
        record_activity(
            admin_user["id"],
            "user-deleted",
            f"{admin_user['full_name']} deleted {user['username']}.",
            "user",
            user_id,
            changes=[
                {"field_name": "deleted_at", "old_value": None, "new_value": deleted_at},
                {"field_name": "is_active", "old_value": user["is_active"], "new_value": 0},
            ],
        )
        return jsonify({"ok": True})

    @app.get("/api/admin/holidays")
    @admin_required
    def api_admin_holidays():
        year = _parse_int(request.args.get("year"), date.today().year)
        rows = query_db("SELECT * FROM holiday_definitions WHERE year = ? ORDER BY category ASC, start_date ASC", (year,))
        return jsonify({"holidays": [serialize_holiday(row) for row in rows]})

    @app.post("/api/admin/holidays")
    @admin_required
    def api_admin_create_holiday():
        admin_user = current_user()
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()
        year = _parse_int(request.form.get("year"), date.today().year)
        is_locked = 1 if request.form.get("is_locked", "true") == "true" else 0
        if not title or category not in {"major", "minor"} or not start_date or not end_date:
            return jsonify({"error": "Title, category, and dates are required."}), 400
        if end_date < start_date:
            return jsonify({"error": "Holiday end date must be on or after the start date."}), 400
        holiday_key = request.form.get("holiday_key", "").strip() or _holiday_key_from_title(title)
        try:
            holiday_id = execute_db(
                """
                INSERT INTO holiday_definitions (year, holiday_key, title, category, start_date, end_date, is_locked, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (year, holiday_key, title, category, start_date, end_date, is_locked, iso_now(), iso_now()),
            )
        except Exception as exc:
            return jsonify({"error": f"Unable to create holiday: {exc}"}), 400
        record_activity(
            admin_user["id"],
            "holiday-created",
            f"{admin_user['full_name']} created holiday {title} for {year}.",
            "holiday_definition",
            holiday_id,
            changes=[
                {"field_name": "title", "old_value": None, "new_value": title},
                {"field_name": "start_date", "old_value": None, "new_value": start_date},
                {"field_name": "end_date", "old_value": None, "new_value": end_date},
            ],
        )
        return jsonify({"ok": True})

    @app.post("/api/admin/holidays/<int:holiday_id>")
    @admin_required
    def api_admin_update_holiday(holiday_id: int):
        admin_user = current_user()
        holiday = query_db("SELECT * FROM holiday_definitions WHERE id = ?", (holiday_id,), one=True)
        if not holiday:
            abort(404)
        title = request.form.get("title", "").strip()
        category = request.form.get("category", "").strip()
        start_date = request.form.get("start_date", "").strip()
        end_date = request.form.get("end_date", "").strip()
        is_locked = 1 if request.form.get("is_locked", "true") == "true" else 0
        if not title or category not in {"major", "minor"} or not start_date or not end_date:
            return jsonify({"error": "Title, category, and dates are required."}), 400
        if end_date < start_date:
            return jsonify({"error": "Holiday end date must be on or after the start date."}), 400
        execute_db(
            """
            UPDATE holiday_definitions
            SET title = ?, category = ?, start_date = ?, end_date = ?, is_locked = ?, updated_at = ?
            WHERE id = ?
            """,
            (title, category, start_date, end_date, is_locked, iso_now(), holiday_id),
        )
        changes = []
        for field_name, old_value, new_value in [
            ("title", holiday["title"], title),
            ("category", holiday["category"], category),
            ("start_date", holiday["start_date"], start_date),
            ("end_date", holiday["end_date"], end_date),
            ("is_locked", holiday["is_locked"], is_locked),
        ]:
            if old_value != new_value:
                changes.append({"field_name": field_name, "old_value": old_value, "new_value": new_value})
        record_activity(
            admin_user["id"],
            "holiday-updated",
            f"{admin_user['full_name']} updated holiday {title}.",
            "holiday_definition",
            holiday_id,
            changes=changes,
        )
        return jsonify({"ok": True})

    @app.post("/api/admin/holidays/<int:holiday_id>/delete")
    @admin_required
    def api_admin_delete_holiday(holiday_id: int):
        admin_user = current_user()
        holiday = query_db("SELECT * FROM holiday_definitions WHERE id = ?", (holiday_id,), one=True)
        if not holiday:
            abort(404)
        execute_db("DELETE FROM holiday_definitions WHERE id = ?", (holiday_id,))
        record_activity(
            admin_user["id"],
            "holiday-deleted",
            f"{admin_user['full_name']} deleted holiday {holiday['title']}.",
            "holiday_definition",
            holiday_id,
            changes=[{"field_name": "title", "old_value": holiday["title"], "new_value": None}],
        )
        return jsonify({"ok": True})

    @app.get("/api/admin/logs")
    @admin_required
    def api_admin_logs():
        kind = request.args.get("kind", "activity").strip().lower()
        page_size = min(max(_parse_int(request.args.get("page_size"), 100) or 100, 1), 100)
        page = max(_parse_int(request.args.get("page"), 1) or 1, 1)

        if kind == "changes":
            total_row = query_db("SELECT COUNT(*) AS count FROM change_log", one=True)
            total = int(total_row["count"] if total_row else 0)
            page_count = max(1, (total + page_size - 1) // page_size)
            page = min(page, page_count)
            offset = (page - 1) * page_size
            rows = query_db(
                """
                SELECT cl.*, u.full_name AS actor_name
                FROM change_log cl
                LEFT JOIN users u ON u.id = cl.actor_user_id
                ORDER BY cl.created_at DESC, cl.id DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, offset),
            )
            items = [
                {
                    "id": row["id"],
                    "actor": row["actor_name"] or "System",
                    "entityType": row["entity_type"],
                    "entityId": row["entity_id"],
                    "fieldName": row["field_name"],
                    "oldValue": row["old_value"],
                    "newValue": row["new_value"],
                    "createdAt": row["created_at"],
                }
                for row in rows
            ]
        else:
            kind = "activity"
            total_row = query_db("SELECT COUNT(*) AS count FROM activity_log", one=True)
            total = int(total_row["count"] if total_row else 0)
            page_count = max(1, (total + page_size - 1) // page_size)
            page = min(page, page_count)
            offset = (page - 1) * page_size
            rows = query_db(
                """
                SELECT al.*, u.full_name AS actor_name
                FROM activity_log al
                LEFT JOIN users u ON u.id = al.actor_user_id
                ORDER BY al.created_at DESC, al.id DESC
                LIMIT ? OFFSET ?
                """,
                (page_size, offset),
            )
            items = [
                {
                    "id": row["id"],
                    "actor": row["actor_name"] or "System",
                    "eventType": row["event_type"],
                    "message": row["message"],
                    "entityType": row["entity_type"],
                    "entityId": row["entity_id"],
                    "createdAt": row["created_at"],
                }
                for row in rows
            ]
        return jsonify({"kind": kind, "page": page, "pageSize": page_size, "pageCount": page_count, "total": total, "items": items})

    @app.get("/api/admin/export")
    @admin_required
    def api_admin_export():
        year = _parse_int(request.args.get("year"), date.today().year)
        return jsonify(_export_matrix(year))

    @app.get("/api/admin/export.csv")
    @admin_required
    def api_admin_export_csv():
        year = _parse_int(request.args.get("year"), date.today().year)
        matrix = _export_matrix(year)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Physician", *matrix["dates"]])
        for row in matrix["rows"]:
            writer.writerow([row["physician"], *row["cells"]])
        return Response(
            buffer.getvalue(),
            mimetype="text/csv",
            headers={"Content-Disposition": f'attachment; filename="vl_export_{year}.csv"'},
        )
