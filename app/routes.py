import calendar
from datetime import date, datetime
from functools import wraps
from pathlib import Path

from flask import (
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
    active_request_statuses,
    daterange,
    execute_db,
    get_db,
    hash_password,
    overlapping_requests,
    query_db,
    recalculate_request_statuses,
    request_is_eligible,
    verify_password,
)
from .holiday_rotation import parse_holiday_rotation


def current_user():
    user_id = session.get("user_id")
    if not user_id:
        return None
    return query_db(
        """
        SELECT u.*, s.week_start, s.show_week_numbers
        FROM users u
        LEFT JOIN user_settings s ON s.user_id = u.id
        WHERE u.id = ? AND u.is_active = 1 AND u.deleted_at IS NULL
        """,
        (user_id,),
        one=True,
    )


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not current_user():
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)

    return wrapped


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = current_user()
        if not user:
            return redirect(url_for("login", next=request.path))
        if user["role"] != "admin":
            abort(403)
        return view(*args, **kwargs)

    return wrapped


def last_name(full_name: str) -> str:
    return (full_name or "").split()[-1] if full_name else ""


def build_month_payload(year: int, month: int, week_start: str, show_week_numbers: bool):
    cal = calendar.Calendar(firstweekday=6 if week_start == "sunday" else 0)
    weeks = []
    max_slots = current_app.config["MAX_DAILY_VACATION_SLOTS"]
    today = date.today().isoformat()
    for week in cal.monthdatescalendar(year, month):
        week_payload = []
        for day in week:
            rows = overlapping_requests(day.isoformat())
            slots = []
            for index in range(max_slots):
                row = rows[index] if index < len(rows) else None
                slots.append(
                    {
                        "occupied": bool(row),
                        "label": last_name(row["full_name"]) if row else "",
                        "name": row["full_name"] if row else "",
                    }
                )
            week_payload.append(
                {
                    "date": day.isoformat(),
                    "day": day.day,
                    "isCurrentMonth": day.month == month,
                    "isToday": day.isoformat() == today,
                    "filledSlots": min(len(rows), max_slots),
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
        "physician": row["full_name"],
        "username": row["username"],
        "email": row["email"],
        "startDate": row["start_date"],
        "endDate": row["end_date"],
        "status": row["status"],
        "createdAt": row["created_at"],
        "decisionNote": row["decision_note"],
    }


def register_routes(app):
    @app.context_processor
    def inject_user():
        return {"nav_user": current_user()}

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
                SELECT u.*, s.week_start, s.show_week_numbers
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

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("index"))

    @app.route("/history")
    @login_required
    def history():
        return render_template("history.html")

    @app.route("/holiday-rotation")
    def holiday_rotation():
        rotation = parse_holiday_rotation(Path("app/uploads/holiday_rotation_schedule.xlsx"))
        selected_year = request.args.get("year", rotation["current_year"])
        if selected_year not in rotation["pairings_by_year"]:
            selected_year = rotation["current_year"]
        return render_template(
            "holiday_rotation.html",
            rotation_years=rotation["years"],
            selected_year=selected_year,
            rotation_pairings=rotation["pairings_by_year"][selected_year],
        )

    @app.route("/vacation-guidelines")
    def vacation_guidelines():
        return render_template("vacation_guidelines.html")

    @app.route("/admin")
    @admin_required
    def admin():
        return render_template("admin.html")

    @app.get("/downloads/<int:document_id>")
    def download_document(document_id: int):
        doc = query_db("SELECT * FROM holiday_documents WHERE id = ?", (document_id,), one=True)
        if not doc:
            abort(404)
        return send_file(Path(doc["file_path"]), as_attachment=True, download_name=doc["file_name"])

    @app.get("/api/session")
    def api_session():
        user = current_user()
        if not user:
            return jsonify({"user": None})
        return jsonify(
            {
                "user": {
                    "id": user["id"],
                    "username": user["username"],
                    "fullName": user["full_name"],
                    "email": user["email"],
                    "role": user["role"],
                    "weekStart": user["week_start"],
                    "showWeekNumbers": bool(user["show_week_numbers"]),
                }
            }
        )

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
        rows = overlapping_requests(day_iso)
        payload = []
        for index, row in enumerate(rows, start=1):
            payload.append(
                {
                    "rank": index,
                    "status": row["status"],
                    "physician": row["full_name"],
                    "username": row["username"],
                    "requestedAt": row["created_at"],
                    "startDate": row["start_date"],
                    "endDate": row["end_date"],
                }
            )
        return jsonify({"date": day_iso, "requests": payload})

    @app.get("/api/requests")
    @login_required
    def api_requests():
        user = current_user()
        rows = query_db(
            """
            SELECT vr.*, COALESCE(vr.request_display_name, u.full_name) AS full_name, u.username, u.email
            FROM vacation_requests vr
            LEFT JOIN users u ON u.id = vr.user_id
            WHERE vr.user_id = ?
            ORDER BY vr.created_at DESC, vr.id DESC
            """,
            (user["id"],),
        )
        return jsonify({"requests": [serialize_request(row) for row in rows]})

    @app.post("/api/requests")
    @login_required
    def api_create_request():
        user = current_user()
        start_date = request.form.get("start_date", "")
        end_date = request.form.get("end_date", "")
        note = request.form.get("request_note", "").strip()
        if not start_date or not end_date:
            return jsonify({"error": "Start and end dates are required."}), 400
        if end_date < start_date:
            return jsonify({"error": "End date must be after start date."}), 400

        request_id = execute_db(
            """
            INSERT INTO vacation_requests (user_id, request_display_name, start_date, end_date, status, request_note)
            VALUES (?, ?, ?, ?, 'requested', ?)
            """,
            (user["id"], user["full_name"], start_date, end_date, note),
        )
        recalculate_request_statuses()
        row = query_db(
            """
            SELECT vr.*, COALESCE(vr.request_display_name, u.full_name) AS full_name, u.username, u.email
            FROM vacation_requests vr LEFT JOIN users u ON u.id = vr.user_id WHERE vr.id = ?
            """,
            (request_id,),
            one=True,
        )
        return jsonify({"request": serialize_request(row)})

    @app.post("/api/requests/<int:request_id>/cancel")
    @login_required
    def api_cancel_request(request_id: int):
        user = current_user()
        row = query_db("SELECT * FROM vacation_requests WHERE id = ? AND user_id = ?", (request_id, user["id"]), one=True)
        if not row:
            abort(404)
        execute_db(
            """
            UPDATE vacation_requests
            SET status = 'withdrawn', canceled_at = ?, processed_at = ?
            WHERE id = ?
            """,
            (datetime.utcnow().isoformat(timespec="seconds"), datetime.utcnow().isoformat(timespec="seconds"), request_id),
        )
        recalculate_request_statuses()
        return jsonify({"ok": True})

    @app.post("/api/settings")
    @login_required
    def api_settings():
        user = current_user()
        week_start = request.form.get("week_start", "sunday")
        show_week_numbers = 1 if request.form.get("show_week_numbers") == "true" else 0
        if week_start not in {"sunday", "monday"}:
            return jsonify({"error": "Invalid week start."}), 400
        execute_db(
            """
            UPDATE user_settings
            SET week_start = ?, show_week_numbers = ?
            WHERE user_id = ?
            """,
            (week_start, show_week_numbers, user["id"]),
        )
        return jsonify({"ok": True})

    @app.get("/api/admin/requests")
    @admin_required
    def api_admin_requests():
        rows = query_db(
            """
            SELECT vr.*, COALESCE(vr.request_display_name, u.full_name) AS full_name, u.username, u.email
            FROM vacation_requests vr
            LEFT JOIN users u ON u.id = vr.user_id
            ORDER BY vr.created_at DESC, vr.id DESC
            """
        )
        return jsonify({"requests": [serialize_request(row) for row in rows]})

    @app.post("/api/admin/requests/<int:request_id>/status")
    @admin_required
    def api_admin_request_status(request_id: int):
        admin_user = current_user()
        new_status = request.form.get("status", "")
        if new_status not in {"confirmed", "unavailable"}:
            return jsonify({"error": "Invalid status."}), 400
        row = query_db(
            """
            SELECT vr.*, COALESCE(vr.request_display_name, u.full_name) AS full_name, u.username, u.email
            FROM vacation_requests vr LEFT JOIN users u ON u.id = vr.user_id WHERE vr.id = ?
            """,
            (request_id,),
            one=True,
        )
        if not row:
            abort(404)
        if row["status"] == "withdrawn":
            return jsonify({"error": "Withdrawn requests cannot be changed."}), 400
        if new_status == "confirmed" and not request_is_eligible(row):
            return jsonify({"error": "This request is not currently in the top 6 for every selected day."}), 400

        execute_db(
            """
            UPDATE vacation_requests
            SET status = ?, processed_at = ?, processed_by = ?
            WHERE id = ?
            """,
            (new_status, datetime.utcnow().isoformat(timespec="seconds"), admin_user["id"], request_id),
        )
        recalculate_request_statuses()
        return jsonify({"ok": True})

    @app.get("/api/admin/users")
    @admin_required
    def api_admin_users():
        users = query_db(
            """
            SELECT u.*, s.week_start, s.show_week_numbers
            FROM users u
            LEFT JOIN user_settings s ON s.user_id = u.id
            WHERE u.deleted_at IS NULL
            ORDER BY u.role DESC, u.full_name ASC
            """
        )
        return jsonify(
            {
                "users": [
                    {
                        "id": row["id"],
                        "username": row["username"],
                        "fullName": row["full_name"],
                        "email": row["email"],
                        "role": row["role"],
                        "isActive": bool(row["is_active"]),
                    }
                    for row in users
                ]
            }
        )

    @app.post("/api/admin/users")
    @admin_required
    def api_admin_create_user():
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "").strip()
        role = request.form.get("role", "physician").strip()
        if not all([full_name, username, email, password]) or role not in {"physician", "admin"}:
            return jsonify({"error": "All fields are required."}), 400

        db = get_db()
        try:
            cur = db.execute(
                """
                INSERT INTO users (username, full_name, email, password_hash, role)
                VALUES (?, ?, ?, ?, ?)
                """,
                (username, full_name, email, hash_password(password), role),
            )
            user_id = cur.lastrowid
            db.execute(
                "INSERT INTO user_settings (user_id, week_start, show_week_numbers) VALUES (?, 'sunday', 0)",
                (user_id,),
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            return jsonify({"error": f"Unable to create user: {exc}"}), 400
        return jsonify({"ok": True})

    @app.post("/api/admin/users/<int:user_id>")
    @admin_required
    def api_admin_update_user(user_id: int):
        user = query_db("SELECT * FROM users WHERE id = ? AND deleted_at IS NULL", (user_id,), one=True)
        if not user:
            abort(404)
        full_name = request.form.get("full_name", "").strip()
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip()
        role = request.form.get("role", "").strip()
        password = request.form.get("password", "").strip()
        if not all([full_name, username, email]) or role not in {"physician", "admin"}:
            return jsonify({"error": "Full name, username, email, and role are required."}), 400

        db = get_db()
        try:
            if password:
                db.execute(
                    """
                    UPDATE users
                    SET full_name = ?, username = ?, email = ?, role = ?, password_hash = ?
                    WHERE id = ?
                    """,
                    (full_name, username, email, role, hash_password(password), user_id),
                )
            else:
                db.execute(
                    """
                    UPDATE users
                    SET full_name = ?, username = ?, email = ?, role = ?
                    WHERE id = ?
                    """,
                    (full_name, username, email, role, user_id),
                )
            db.execute(
                """
                UPDATE vacation_requests
                SET request_display_name = ?
                WHERE user_id = ?
                """,
                (full_name, user_id),
            )
            db.commit()
        except Exception as exc:
            db.rollback()
            return jsonify({"error": f"Unable to update user: {exc}"}), 400
        return jsonify({"ok": True})

    @app.post("/api/admin/users/<int:user_id>/toggle")
    @admin_required
    def api_admin_toggle_user(user_id: int):
        user = query_db("SELECT * FROM users WHERE id = ?", (user_id,), one=True)
        if not user:
            abort(404)
        new_state = 0 if user["is_active"] else 1
        execute_db("UPDATE users SET is_active = ? WHERE id = ?", (new_state, user_id))
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

        archived_name = user["full_name"]
        archived_username = f"deleted-user-{user_id}"
        archived_email = f"deleted-user-{user_id}@invalid.local"
        execute_db(
            """
            UPDATE vacation_requests
            SET request_display_name = ?
            WHERE user_id = ?
            """,
            (archived_name, user_id),
        )
        execute_db(
            """
            UPDATE users
            SET deleted_at = ?, is_active = 0, username = ?, email = ?, password_hash = ?, full_name = ?
            WHERE id = ?
            """,
            (
                datetime.utcnow().isoformat(timespec="seconds"),
                archived_username,
                archived_email,
                hash_password("deleted-account"),
                f"Deleted User {user_id}",
                user_id,
            ),
        )
        return jsonify({"ok": True})
