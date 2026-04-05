import csv
import re
from pathlib import Path


LEGACY_DIR = Path("legacy VL Calendar")
YEAR_PATTERN = re.compile(r"(20\d{2})")


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
