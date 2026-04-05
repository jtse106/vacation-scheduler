import csv
import re
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path


LEGACY_DIR = Path("legacy VL Calendar")
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
NOISE = {"2017vlcalendar", "2018vlcalendar", "2019vlcalendar"}
NOISE.update(name.lower() for name in MONTH_NAMES)
NOISE.update(day.lower() for day in ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"])
ALIASES = {
    "gpreciado": "G Preciado",
    "kpreciado": "K Preciado",
    "ddonson": "D Donson",
    "jdonson": "J Donson",
    "dd": "D Donson",
    "jd": "J Donson",
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


def _title_for_path(path: Path) -> str:
    stem = path.stem.replace("_", " ").replace("  ", " ").strip()
    return stem


def legacy_documents():
    documents = []
    for path in sorted(LEGACY_DIR.glob("*.csv")):
        match = YEAR_PATTERN.search(path.name)
        doc_type = "rotation" if "rotation" in path.name.lower() else "calendar"
        documents.append(
            {
                "title": _title_for_path(path),
                "path": path,
                "file_name": path.name,
                "year": int(match.group(1)) if match else None,
                "doc_type": doc_type,
            }
        )
    return documents


def legacy_calendar_years():
    return sorted({document["year"] for document in legacy_documents() if document["doc_type"] == "calendar" and document["year"]})


def legacy_calendar_for_year(year: int):
    for document in legacy_documents():
        if document["doc_type"] == "calendar" and document["year"] == year:
            with document["path"].open("r", encoding="utf-8-sig", newline="") as handle:
                rows = list(csv.reader(handle))
            column_count = max((len(row) for row in rows), default=0)
            normalized_rows = [row + [""] * (column_count - len(row)) for row in rows]
            return {
                "title": document["title"],
                "year": year,
                "path": document["path"],
                "rows": normalized_rows,
                "column_count": column_count,
            }
    return None


def legacy_snapshot_path(year: int) -> Path:
    return LEGACY_DIR / f"VL Calendar {year} - Sheet1.csv"


def write_legacy_calendar_matrix(year: int, matrix: dict):
    LEGACY_DIR.mkdir(parents=True, exist_ok=True)
    path = legacy_snapshot_path(year)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["Physician", *matrix["dates"]])
        for row in matrix["rows"]:
            writer.writerow([row["physician"], *row["cells"]])
    return path


def normalize_legacy_token(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (value or "").strip().lower())


def clean_legacy_label(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().strip(","))


def infer_legacy_date(year: int, section_month: int, token: str) -> date:
    month, day = (int(part) for part in token.split("/"))
    actual_year = year
    if section_month == 1 and month == 12:
        actual_year -= 1
    elif section_month == 12 and month == 1:
        actual_year += 1
    return date(actual_year, month, day)


def group_legacy_ranges(days: set[date]) -> list[tuple[str, str]]:
    ordered = sorted(days)
    if not ordered:
        return []
    ranges = []
    start = end = ordered[0]
    for current in ordered[1:]:
        if current == end + timedelta(days=1):
            end = current
            continue
        ranges.append((start.isoformat(), end.isoformat()))
        start = end = current
    ranges.append((start.isoformat(), end.isoformat()))
    return ranges


def parse_legacy_schedule_documents(known_names: dict[str, str] | None = None):
    known_names = known_names or {}
    aggregate_days = defaultdict(set)
    unresolved_labels = defaultdict(int)
    placeholder_labels: dict[str, str] = {}

    for document in legacy_documents():
        if document["doc_type"] != "calendar" or not document["year"]:
            continue
        with document["path"].open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.reader(handle))
        if not rows or max(len(row) for row in rows) > 20:
            continue

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
            is_date_row = False
            for cell in row[:7]:
                token = cell.strip()
                if DATE_PATTERN.fullmatch(token):
                    is_date_row = True
                    week_dates.append(infer_legacy_date(document["year"], current_month, token))
                else:
                    week_dates.append(None)
            if not is_date_row:
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
                    normalized = normalize_legacy_token(raw)
                    if not normalized or normalized.isdigit() or normalized in NOISE:
                        continue
                    canonical = ALIASES.get(normalized) or known_names.get(normalized)
                    if canonical is None:
                        canonical = placeholder_labels.setdefault(normalized, clean_legacy_label(raw))
                        unresolved_labels[canonical] += 1
                    aggregate_days[canonical].add(week_dates[day_index])
                index += 1

    return {
        "days_by_name": aggregate_days,
        "ranges_by_name": {name: group_legacy_ranges(days) for name, days in aggregate_days.items()},
        "unresolved_labels": dict(unresolved_labels),
    }
