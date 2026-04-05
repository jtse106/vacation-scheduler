import csv
import re
import sqlite3
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db import default_email_for_username, hash_password, slugify_name

DB_PATH = ROOT / "app" / "data" / "vacation_scheduler.db"
LEGACY_DIR = ROOT / "legacy VL Calendar"
YEAR_PATTERN = re.compile(r"(20\d{2})")
MONTH_NAMES = {
    name: index
    for index, name in enumerate(
        [
            "January",
            "February",
            "March",
            "April",
            "May",
            "June",
            "July",
            "August",
            "September",
            "October",
            "November",
            "December",
        ],
        start=1,
    )
}
DATE_PATTERN = re.compile(r"^\d{1,2}/\d{1,2}$")
NOISE = {
    "2017vlcalendar",
    "2018vlcalendar",
    "2019vlcalendar",
}
NOISE.update(normalize.lower() for normalize in MONTH_NAMES)
NOISE.update(
    token.lower()
    for token in ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
)
ALIASES = {
    "gpreciado": "G Preciado",
    "kpreciado": "K Preciado",
    "ddonson": "D Donson",
    "jdonson": "J Donson",
    "dd": "D Donson",
    "jd": "J Donson",
    "manooch": "Manoochehri",
    "manooch": "Manoochehri",
    "manoochehri": "Manoochehri",
    "hanuel": "Hanudel",
    "handuel": "Hanudel",
    "hanudel": "Hanudel",
    "rezhaimehr": "Rezaimehr",
    "rezaimehr": "Rezaimehr",
    "yaravoy": "Yarovoy",
    "yarovoy": "Yarovoy",
    "rukowski": "Rutkowski",
    "rutkoswki": "Rutkowski",
    "rutkowski": "Rutkowski",
    "jlee": "Lee",
    "jasonlee": "Lee",
    "yu": "Yun",
    "nguyenpl": "Nguyen",
    "afifi": "Afifi",
}


def normalize_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def infer_date(year: int, section_month: int, token: str) -> date:
    month, day = (int(part) for part in token.split("/"))
    actual_year = year
    if section_month == 1 and month == 12:
        actual_year -= 1
    elif section_month == 12 and month == 1:
        actual_year += 1
    return date(actual_year, month, day)


def clean_label(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().strip(","))


def group_ranges(days: set[date]) -> list[tuple[str, str]]:
    ranges = []
    ordered = sorted(days)
    if not ordered:
        return ranges
    start = ordered[0]
    end = ordered[0]
    for current in ordered[1:]:
        if current == end + timedelta(days=1):
            end = current
            continue
        ranges.append((start.isoformat(), end.isoformat()))
        start = end = current
    ranges.append((start.isoformat(), end.isoformat()))
    return ranges


def load_user_maps(connection: sqlite3.Connection):
    by_norm = {}
    by_username = set()
    rows = connection.execute(
        """
        SELECT id, username, full_name
        FROM users
        WHERE role = 'physician' AND deleted_at IS NULL
        """
    ).fetchall()
    for row in rows:
        by_norm[normalize_token(row["full_name"])] = dict(row)
        by_username.add(row["username"])
    return by_norm, by_username


def ensure_physician(connection: sqlite3.Connection, full_name: str, user_map: dict, usernames: set[str]):
    normalized = normalize_token(full_name)
    existing = user_map.get(normalized)
    if existing:
        return existing
    base = slugify_name(full_name)
    candidate = base
    suffix = 2
    while candidate in usernames or connection.execute("SELECT id FROM users WHERE username = ?", (candidate,)).fetchone():
        candidate = f"{base}{suffix}"
        suffix += 1
    connection.execute(
        """
        INSERT INTO users (username, full_name, email, password_hash, role, is_active, annual_day_limit)
        VALUES (?, ?, ?, ?, 'physician', 1, 0)
        """,
        (candidate, full_name, default_email_for_username(candidate), hash_password("ChangeMe123!")),
    )
    row_id = connection.execute("SELECT last_insert_rowid()").fetchone()[0]
    row = {"id": row_id, "username": candidate, "full_name": full_name}
    user_map[normalized] = row
    usernames.add(candidate)
    return row


def parse_legacy_days(path: Path, year: int, user_map: dict, placeholder_labels: dict[str, str]):
    rows = list(csv.reader(path.open("r", encoding="utf-8-sig", newline="")))
    if not rows:
        return defaultdict(set), {}, {path.name: "empty file"}
    if max(len(row) for row in rows) > 20:
        return defaultdict(set), {}, {path.name: "unexpected matrix format"}

    assignments = defaultdict(set)
    unresolved = defaultdict(int)
    current_month = None
    index = 0
    while index < len(rows):
        row = rows[index]
        first = (row[0] if row else "").strip()
        if first in MONTH_NAMES:
            current_month = MONTH_NAMES[first]
            index += 1
            continue

        week_dates = []
        date_row = False
        for cell in row[:7]:
            cell = cell.strip()
            if DATE_PATTERN.fullmatch(cell):
                date_row = True
                week_dates.append(infer_date(year, current_month, cell))
            else:
                week_dates.append(None)
        if not date_row:
            index += 1
            continue

        index += 1
        while index < len(rows):
            row = rows[index]
            first = (row[0] if row else "").strip()
            if first in MONTH_NAMES:
                break
            if any(DATE_PATTERN.fullmatch((cell or "").strip()) for cell in row[:7]):
                break
            for day_index, cell in enumerate(row[:7]):
                raw = cell.strip()
                if not raw or not week_dates[day_index]:
                    continue
                normalized = normalize_token(raw)
                if not normalized or normalized.isdigit() or normalized in NOISE:
                    continue
                canonical = ALIASES.get(normalized)
                if canonical is None and normalized in user_map:
                    canonical = user_map[normalized]["full_name"]
                if canonical is None:
                    canonical = placeholder_labels.setdefault(normalized, clean_label(raw))
                    unresolved[canonical] += 1
                assignments[canonical].add(week_dates[day_index])
            index += 1
    return assignments, unresolved, {}


def main():
    if not DB_PATH.exists():
        raise SystemExit(f"Database not found: {DB_PATH}")

    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        user_map, usernames = load_user_maps(connection)

        aggregate_days = defaultdict(set)
        unresolved = defaultdict(int)
        skipped = {}
        placeholder_labels = {}
        for path in sorted(LEGACY_DIR.glob("*.csv")):
            if "rotation" in path.name.lower():
                continue
            match = YEAR_PATTERN.search(path.name)
            if not match:
                continue
            year = int(match.group(1))
            assignments, unresolved_tokens, skipped_info = parse_legacy_days(path, year, user_map, placeholder_labels)
            for full_name, days in assignments.items():
                aggregate_days[full_name].update(days)
            for token, count in unresolved_tokens.items():
                unresolved[token] += count
            skipped.update(skipped_info)

        if "Afifi" in aggregate_days and normalize_token("Afifi") not in user_map:
            ensure_physician(connection, "Afifi", user_map, usernames)

        imported_users = {}
        for full_name in sorted(aggregate_days):
            imported_users[full_name] = ensure_physician(connection, full_name, user_map, usernames)

        connection.execute("DELETE FROM vacation_requests")
        inserted = 0
        for full_name, days in sorted(aggregate_days.items()):
            user_row = imported_users[full_name]
            for start_iso, end_iso in group_ranges(days):
                connection.execute(
                    """
                    INSERT INTO vacation_requests (
                        user_id,
                        created_by_user_id,
                        request_display_name,
                        start_date,
                        end_date,
                        status,
                        request_note,
                        source_type,
                        source_prompt,
                        source_response,
                        created_at,
                        updated_at,
                        processed_at
                    )
                    VALUES (?, NULL, ?, ?, ?, 'scheduled', ?, 'legacy-import', ?, ?, ?, ?, ?)
                    """,
                    (
                        user_row["id"],
                        full_name,
                        start_iso,
                        end_iso,
                        "Imported from legacy calendar CSVs",
                        "",
                        "",
                        datetime.now().isoformat(timespec="seconds"),
                        datetime.now().isoformat(timespec="seconds"),
                        datetime.now().isoformat(timespec="seconds"),
                    ),
                )
                inserted += 1
        connection.commit()

        print(f"Imported {inserted} request ranges for {len(imported_users)} physicians.")
        if skipped:
            print("Skipped files:")
            for file_name, reason in skipped.items():
                print(f"  {file_name}: {reason}")
        if unresolved:
            print("Unresolved tokens:")
            for token, count in sorted(unresolved.items(), key=lambda item: (-item[1], item[0]))[:20]:
                print(f"  {token!r}: {count}")
    finally:
        connection.close()


if __name__ == "__main__":
    main()
