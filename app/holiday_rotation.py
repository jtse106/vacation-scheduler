import csv
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from .excel_import import normalize_name


SEED_PATH = Path("legacy VL Calendar/Holiday Rotation Schedule - Holiday_Rotation_Schedule.csv")

PAIRING_TO_HOLIDAYS = {
    "Thanksgiving and Memorial Day": (
        {"key": "thanksgiving", "title": "Thanksgiving", "category": "major"},
        {"key": "memorial_day", "title": "Memorial Day", "category": "minor"},
    ),
    "Christmas and July 4th": (
        {"key": "christmas", "title": "Christmas", "category": "major"},
        {"key": "july_4", "title": "July 4th", "category": "minor"},
    ),
    "New Years and Labor Day": (
        {"key": "new_years", "title": "New Year's", "category": "major"},
        {"key": "labor_day", "title": "Labor Day", "category": "minor"},
    ),
}

MAJOR_ROTATION = ["thanksgiving", "christmas", "new_years"]
MINOR_ROTATION = ["memorial_day", "july_4", "labor_day"]


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds")


def _split_entry(value: str):
    text = (value or "").strip()
    if not text:
        return None
    match = re.match(r"^(.*?)\s*\((.*?)\)\s*$", text)
    if match:
        return {"name": match.group(1).strip(), "note": match.group(2).strip()}
    alt_match = re.match(r"^(.*?)(?:\s+(July 4th|July 4|Mem|Mem Day|MD|LD|J4))$", text, re.IGNORECASE)
    if alt_match:
        return {"name": alt_match.group(1).strip(), "note": alt_match.group(2).strip()}
    return {"name": text, "note": ""}


def _normalized_lookup_key(full_name: str) -> str:
    normalized = normalize_name(full_name) or full_name.strip()
    return re.sub(r"\s+", "", normalized).lower()


def parse_rotation_seed(path: Path | None = None):
    rotation_path = path or SEED_PATH
    with rotation_path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))

    if not rows:
        return {"years": [], "assignments_by_year": {}}

    year_columns = []
    for index, value in enumerate(rows[0][1:], start=1):
        text = (value or "").strip()
        if text.isdigit():
            year_columns.append((index, int(text)))

    assignments_by_year = {year: defaultdict(list) for _, year in year_columns}
    current_section = None
    slot_counter = 0

    for row in rows[1:]:
        title = (row[0] if row else "").strip()
        if title in PAIRING_TO_HOLIDAYS:
            current_section = title
            slot_counter = 0
        if not current_section:
            continue

        row_has_entries = False
        for column_index, year in year_columns:
            raw_value = row[column_index] if column_index < len(row) else ""
            parsed = _split_entry(raw_value)
            if not parsed:
                continue
            row_has_entries = True
            normalized_name = normalize_name(parsed["name"]) or parsed["name"].strip()
            for holiday in PAIRING_TO_HOLIDAYS[current_section]:
                assignments_by_year[year][holiday["key"]].append(
                    {
                        "holiday_key": holiday["key"],
                        "holiday_title": holiday["title"],
                        "category": holiday["category"],
                        "full_name": normalized_name,
                        "slot_order": slot_counter + 1,
                        "note": parsed["note"],
                    }
                )
        if row_has_entries:
            slot_counter += 1

    return {
        "years": sorted(assignments_by_year),
        "assignments_by_year": {year: dict(assignments) for year, assignments in assignments_by_year.items()},
    }


def seed_rotation_assignments(connection: sqlite3.Connection, user_lookup: dict[str, int], path: Path | None = None):
    parsed = parse_rotation_seed(path)
    for year, assignments in parsed["assignments_by_year"].items():
        for holiday_key, rows in assignments.items():
            for row in rows:
                user_id = user_lookup.get(_normalized_lookup_key(row["full_name"]))
                if not user_id:
                    continue
                connection.execute(
                    """
                    INSERT OR IGNORE INTO holiday_rotation_assignments
                    (year, holiday_key, holiday_title, category, user_id, slot_order, note, source_type, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'legacy-seed', ?, ?)
                    """,
                    (
                        year,
                        holiday_key,
                        row["holiday_title"],
                        row["category"],
                        user_id,
                        row["slot_order"],
                        row["note"],
                        _now_iso(),
                        _now_iso(),
                    ),
                )


def _next_holiday_key(category: str, holiday_key: str) -> str:
    rotation = MAJOR_ROTATION if category == "major" else MINOR_ROTATION
    index = rotation.index(holiday_key)
    return rotation[(index + 1) % len(rotation)]


def ensure_future_rotation_years(connection: sqlite3.Connection, through_year: int):
    row = connection.execute("SELECT MAX(year) AS max_year FROM holiday_rotation_assignments").fetchone()
    max_year = row["max_year"] if row and row["max_year"] is not None else None
    if max_year is None:
        return

    while max_year < through_year:
        source_rows = connection.execute(
            """
            SELECT year, holiday_key, holiday_title, category, user_id, slot_order, note
            FROM holiday_rotation_assignments
            WHERE year = ?
            ORDER BY category ASC, holiday_key ASC, slot_order ASC
            """,
            (max_year,),
        ).fetchall()
        if not source_rows:
            break

        next_year = max_year + 1
        created_any = False
        for source_row in source_rows:
            next_key = _next_holiday_key(source_row["category"], source_row["holiday_key"])
            title = {
                "thanksgiving": "Thanksgiving",
                "christmas": "Christmas",
                "new_years": "New Year's",
                "memorial_day": "Memorial Day",
                "july_4": "July 4th",
                "labor_day": "Labor Day",
            }[next_key]
            connection.execute(
                """
                INSERT OR IGNORE INTO holiday_rotation_assignments
                (year, holiday_key, holiday_title, category, user_id, slot_order, note, source_type, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'auto-rotation', ?, ?)
                """,
                (
                    next_year,
                    next_key,
                    title,
                    source_row["category"],
                    source_row["user_id"],
                    source_row["slot_order"],
                    source_row["note"],
                    _now_iso(),
                    _now_iso(),
                ),
            )
            created_any = True
        if not created_any:
            break
        max_year = next_year
