import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


NAMESPACE = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
PAIRING_TITLES = [
    "Thanksgiving and Memorial Day",
    "Christmas and July 4th",
    "New Years and Labor Day",
]


def split_entry(value: str):
    text = (value or "").strip()
    if not text:
        return None
    match = re.match(r"^(.*?)\s*\((.*?)\)\s*$", text)
    if match:
        return {"name": match.group(1).strip(), "note": match.group(2).strip()}
    return {"name": text, "note": ""}


def workbook_cells(path: Path):
    with zipfile.ZipFile(path) as archive:
        shared = []
        shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
        for item in shared_root.iter(f"{NAMESPACE}si"):
            shared.append("".join(node.text or "" for node in item.iter(f"{NAMESPACE}t")))

        worksheet = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        cells = {}
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


def parse_holiday_rotation(path: Path):
    cells, max_row = workbook_cells(path)

    years = []
    column_letters = []
    for column in "BCDEFGHIJKLMNOPQRSTUVWXYZ":
        value = (cells.get(f"{column}1", "") or "").strip()
        if value:
            try:
                year = str(int(float(value)))
            except ValueError:
                continue
            years.append(year)
            column_letters.append(column)

    sections = []
    for row_number in range(1, max_row + 1):
        title = (cells.get(f"A{row_number}", "") or "").strip()
        if title in PAIRING_TITLES:
            sections.append((title, row_number))

    sections_with_end = []
    for index, (title, start_row) in enumerate(sections):
        end_row = sections[index + 1][1] - 1 if index + 1 < len(sections) else max_row
        sections_with_end.append((title, start_row, end_row))

    years_map = {}
    for year, column in zip(years, column_letters):
        pairings = []
        for title, start_row, end_row in sections_with_end:
            physicians = []
            for row_number in range(start_row, end_row + 1):
                if row_number == start_row:
                    value = cells.get(f"{column}{row_number}", "")
                else:
                    value = cells.get(f"{column}{row_number}", "")
                parsed = split_entry(value)
                if parsed:
                    physicians.append(parsed)
            pairings.append({"title": title, "physicians": physicians})
        years_map[year] = pairings

    current_year = (cells.get("A2", "") or "").strip()
    if current_year and current_year not in years_map and years:
        current_year = years[-1]
    elif not current_year and years:
        current_year = years[-1]

    return {"years": years, "current_year": current_year, "pairings_by_year": years_map}
