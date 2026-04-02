import re
import zipfile
from pathlib import Path
from typing import Optional
from xml.etree import ElementTree as ET


UPLOADS_DIR = Path("app/uploads")

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

DAYS = {"Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sun"}

NOISE = {
    "Current Year",
    "PROTECTED HOLIDAYS",
    "needed for main sheet",
    "remaining docs",
    "total docs",
    "Shifts",
    "Pain",
    "New Year",
    "New Years",
    "New Year's",
    "Memorial Day",
    "Labor Day",
    "Thanksgiving",
    "Christmas",
    "Thanksgiving and Memorial Day",
    "Christmas and July 4th",
    "New Years and Labor Day",
    "and Memorial Day",
    "and July 4th",
    "and Labor Day",
    "tg",
    "xm",
    "ny",
    "TG",
    "WE",
    "NYE",
    "NYD",
    "XME",
    "XMD",
}

NAME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z .'\-()]{1,60}$")


def normalize_name(value: str) -> Optional[str]:
    text = value.strip()
    if not text or text in MONTHS or text in DAYS or text in NOISE:
        return None
    if any(char.isdigit() for char in text):
        return None
    if not NAME_PATTERN.match(text):
        return None

    text = re.sub(r"\((.*?)\)", "", text).strip()
    text = re.sub(r"\s+", " ", text)
    replacements = {
        "GPreciado": "G Preciado",
        "Gpreciado": "G Preciado",
        "KPreciado": "K Preciado",
        "DDonson": "D Donson",
        "JDonson": "J Donson",
        "MIttendorf": "Mittendorf",
        "Rutkoswki": "Rutkowski",
    }
    text = replacements.get(text, text)
    if text in {"Sun"}:
        return "Sun"
    parts = [part.capitalize() if part.islower() or part.isupper() else part for part in text.split()]
    normalized = " ".join(parts)
    if normalized in NOISE or normalized in MONTHS or normalized in DAYS:
        return None
    return normalized


def workbook_strings(path: Path) -> list[str]:
    with zipfile.ZipFile(path) as archive:
        if "xl/sharedStrings.xml" not in archive.namelist():
            return []
        root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        values = []
        for node in root.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}si"):
            parts = []
            for text in node.iter("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}t"):
                parts.append(text.text or "")
            values.append("".join(parts).strip())
        return values


def import_seed_data():
    documents = [
        {
            "title": "Holiday Rotation Schedule",
            "file_name": "holiday_rotation_schedule.xlsx",
            "file_path": str(UPLOADS_DIR / "holiday_rotation_schedule.xlsx"),
        },
        {
            "title": "Vacation Calendar 2024",
            "file_name": "vl_calendar_2024.xlsx",
            "file_path": str(UPLOADS_DIR / "vl_calendar_2024.xlsx"),
        },
        {
            "title": "Vacation Calendar 2025",
            "file_name": "vl_calendar_2025.xlsx",
            "file_path": str(UPLOADS_DIR / "vl_calendar_2025.xlsx"),
        },
        {
            "title": "Vacation Calendar 2026",
            "file_name": "vl_calendar_2026.xlsx",
            "file_path": str(UPLOADS_DIR / "vl_calendar_2026.xlsx"),
        },
    ]

    physicians = set()
    for document in documents:
        for raw in workbook_strings(Path(document["file_path"])):
            normalized = normalize_name(raw)
            if normalized:
                physicians.add(normalized)

    return {
        "physicians": sorted(physicians),
        "documents": documents,
    }
