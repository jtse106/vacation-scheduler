import re
import sqlite3
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import create_app


MONTHS = {
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
}

SKIP_VALUES = {
    "New Year",
    "New Years",
    "Memorial Day",
    "Labor Day",
    "Thanksgiving",
    "Christmas",
    "Sunday",
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
}

REPLACEMENTS = {
    "GPreciado": "G Preciado",
    "Gpreciado": "G Preciado",
    "KPreciado": "K Preciado",
    "JDonson": "J Donson",
    "DDonson": "D Donson",
    "MIttendorf": "Mittendorf",
    "Rutkoswki": "Rutkowski",
}

NAMESPACE = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
CURRENT_REQUEST_DATE = date(2026, 4, 1)


@dataclass
class ImportedRequest:
    full_name: str
    vacation_date: date
    slot: int
    source_file: str
    created_at: datetime


def normalize_name(value: str) -> Optional[str]:
    text = (value or "").strip()
    if not text or text in SKIP_VALUES:
        return None
    if any(character.isdigit() for character in text):
        return None
    text = re.sub(r"\s+", " ", text)
    return REPLACEMENTS.get(text, text)


def excel_date(value: str) -> Optional[date]:
    try:
        serial = int(float(value))
    except (TypeError, ValueError):
        return None
    return (datetime(1899, 12, 30) + timedelta(days=serial)).date()


def workbook_cells(path: Path) -> tuple[dict[str, str], int]:
    with zipfile.ZipFile(path) as archive:
        shared = []
        shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        for item in shared_root.iter(f"{NAMESPACE}si"):
            shared.append("".join(node.text or "" for node in item.iter(f"{NAMESPACE}t")))

        worksheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        cells: dict[str, str] = {}
        max_row = 0
        for row in worksheet.find(f"{NAMESPACE}sheetData"):
            max_row = max(max_row, int(row.attrib["r"]))
            for cell in row:
                reference = cell.attrib["r"]
                cell_type = cell.attrib.get("t")
                value_node = cell.find(f"{NAMESPACE}v")
                value = "" if value_node is None else value_node.text or ""
                if cell_type == "s" and value:
                    value = shared[int(value)]
                cells[reference] = value
        return cells, max_row


def parse_workbook(path: Path, target_year: int) -> list[ImportedRequest]:
    cells, max_row = workbook_cells(path)
    month_starts = []
    for row_number in range(1, max_row + 1):
        if cells.get(f"A{row_number}", "") in MONTHS and cells.get(f"A{row_number + 1}", "") == "Sunday":
            month_starts.append(row_number)
    month_starts.append(max_row + 1)

    imported: list[ImportedRequest] = []
    yearly_index = 0
    for start_row, next_start_row in zip(month_starts, month_starts[1:]):
        row_number = start_row + 2
        while row_number + 6 < next_start_row:
            if not any(cells.get(f"{column}{row_number}", "") for column in "ABCDEFG"):
                row_number += 1
                continue

            for column in "ABCDEFG":
                vacation_date = excel_date(cells.get(f"{column}{row_number}", ""))
                if not vacation_date or vacation_date.year != target_year:
                    continue

                for slot in range(1, 7):
                    full_name = normalize_name(cells.get(f"{column}{row_number + slot}", ""))
                    if not full_name:
                        continue

                    if target_year == 2026:
                        created_at = datetime.combine(CURRENT_REQUEST_DATE, time(9, 0, 0)) + timedelta(seconds=yearly_index)
                    else:
                        created_at = datetime.combine(vacation_date, time(9, 0, 0)) + timedelta(minutes=slot - 1)

                    imported.append(
                        ImportedRequest(
                            full_name=full_name,
                            vacation_date=vacation_date,
                            slot=slot,
                            source_file=path.name,
                            created_at=created_at,
                        )
                    )
                    yearly_index += 1
            row_number += 7
    return imported


def import_requests():
    app = create_app()
    files = [
        Path("/Users/jtse/Downloads/VL Calendar 2024.xlsx"),
        Path("/Users/jtse/Downloads/VL Calendar 2025.xlsx"),
        Path("/Users/jtse/Downloads/VL Calendar 2026.xlsx"),
    ]

    imported_rows: list[ImportedRequest] = []
    for path in files:
        target_year = int(re.search(r"(20\d{2})", path.name).group(1))
        imported_rows.extend(parse_workbook(path, target_year))

    with app.app_context():
        connection = sqlite3.connect(app.config["DATABASE"])
        connection.row_factory = sqlite3.Row
        users = {
            row["full_name"]: row["id"]
            for row in connection.execute("SELECT id, full_name FROM users").fetchall()
        }
        admin = connection.execute("SELECT id FROM users WHERE role = 'admin' ORDER BY id LIMIT 1").fetchone()
        admin_id = admin["id"] if admin else None

        missing = sorted({row.full_name for row in imported_rows if row.full_name not in users})
        if missing:
            raise RuntimeError(f"Missing users for imported names: {', '.join(missing)}")

        connection.execute("DELETE FROM notification_log")
        connection.execute("DELETE FROM vacation_requests")

        for row in imported_rows:
            connection.execute(
                """
                INSERT INTO vacation_requests (
                    user_id,
                    request_display_name,
                    start_date,
                    end_date,
                    status,
                    request_note,
                    created_at,
                    processed_at,
                    processed_by,
                    decision_note
                )
                VALUES (?, ?, ?, 'confirmed', ?, ?, ?, ?, ?)
                """,
                (
                    users[row.full_name],
                    row.full_name,
                    row.vacation_date.isoformat(),
                    row.vacation_date.isoformat(),
                    f"Imported from {row.source_file} slot {row.slot}",
                    row.created_at.isoformat(timespec="seconds"),
                    row.created_at.isoformat(timespec="seconds"),
                    admin_id,
                    f"Imported from spreadsheet slot {row.slot}",
                ),
            )

        connection.commit()
        counts = Counter(request.vacation_date.year for request in imported_rows)
        print(f"Imported {len(imported_rows)} requests.")
        for year in sorted(counts):
            print(f"{year}: {counts[year]} requests")
        print(f"Database: {app.config['DATABASE']}")


if __name__ == "__main__":
    import_requests()
