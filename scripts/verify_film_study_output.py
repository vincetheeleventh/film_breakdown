from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from film_study_tool.video import probe_duration


NS = {
    "main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "xdr": "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing",
    "rel": "http://schemas.openxmlformats.org/package/2006/relationships",
}

EXPECTED_HEADERS = [
    "Shot",
    "Screenshot",
    "Start",
    "End",
    "Duration (s)",
    "Visual Description",
    "Audio / Dialogue",
    "Action / Camera",
    "Narrative Function",
    "Notes",
]


def parse_timecode(value: str) -> float:
    hours, minutes, seconds = value.split(":")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def inline_text(cell: ET.Element) -> str:
    text_node = cell.find(".//main:t", NS)
    return "" if text_node is None or text_node.text is None else text_node.text


def load_sheet_rows(workbook_path: Path) -> list[list[str]]:
    with zipfile.ZipFile(workbook_path) as package:
        sheet_xml = package.read("xl/worksheets/sheet1.xml")
    root = ET.fromstring(sheet_xml)
    rows: list[list[str]] = []
    for row in root.findall(".//main:sheetData/main:row", NS):
        values: list[str] = []
        for cell in row.findall("main:c", NS):
            if cell.attrib.get("t") == "inlineStr":
                values.append(inline_text(cell))
            else:
                value_node = cell.find("main:v", NS)
                values.append("" if value_node is None or value_node.text is None else value_node.text)
        rows.append(values)
    return rows


def workbook_counts(workbook_path: Path) -> dict[str, int]:
    with zipfile.ZipFile(workbook_path) as package:
        names = package.namelist()
        media = [name for name in names if name.startswith("xl/media/")]
        drawing_xml = package.read("xl/drawings/drawing1.xml")
        drawing_rels_xml = package.read("xl/drawings/_rels/drawing1.xml.rels")

    drawing_root = ET.fromstring(drawing_xml)
    rels_root = ET.fromstring(drawing_rels_xml)
    return {
        "media_files": len(media),
        "drawing_anchors": len(drawing_root.findall("xdr:oneCellAnchor", NS)),
        "drawing_relationships": len(rels_root.findall("rel:Relationship", NS)),
    }


def make_contact_sheet(screenshots: list[Path], output_path: Path, columns: int = 5) -> None:
    thumbs = []
    for path in screenshots:
        with Image.open(path) as image:
            image.thumbnail((240, 135))
            thumb = Image.new("RGB", (240, 160), "white")
            thumb.paste(image.convert("RGB"), (0, 18))
            draw = ImageDraw.Draw(thumb)
            draw.text((6, 4), path.stem.replace("shot_", "#"), fill=(0, 0, 0))
            thumbs.append(thumb)

    if not thumbs:
        return

    rows = (len(thumbs) + columns - 1) // columns
    sheet = Image.new("RGB", (columns * 240, rows * 160), "white")
    for index, thumb in enumerate(thumbs):
        x = (index % columns) * 240
        y = (index // columns) * 160
        sheet.paste(thumb, (x, y))
    sheet.save(output_path)


def verify(video_path: Path, output_dir: Path) -> tuple[bool, list[str], dict[str, object]]:
    manifest_path = output_dir / "manifest.json"
    workbook_path = output_dir / "film_study.xlsx"
    screenshots_dir = output_dir / "screenshots"
    contact_sheet_path = output_dir / "contact_sheet.jpg"

    failures: list[str] = []
    if not manifest_path.exists():
        failures.append(f"Missing manifest: {manifest_path}")
        return False, failures, {}
    if not workbook_path.exists():
        failures.append(f"Missing workbook: {workbook_path}")
        return False, failures, {}

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    screenshots = sorted(screenshots_dir.glob("shot_*.jpg"))
    rows = load_sheet_rows(workbook_path)
    counts = workbook_counts(workbook_path)

    if not rows or rows[0] != EXPECTED_HEADERS:
        failures.append("Workbook headers do not match the expected film-study schema.")

    data_rows = rows[1:]
    if len(data_rows) != len(manifest):
        failures.append(f"Workbook data rows ({len(data_rows)}) != manifest rows ({len(manifest)}).")
    if len(screenshots) != len(manifest):
        failures.append(f"Screenshot files ({len(screenshots)}) != manifest rows ({len(manifest)}).")

    for key, value in counts.items():
        if value != len(manifest):
            failures.append(f"Workbook {key} ({value}) != manifest rows ({len(manifest)}).")

    expected_numbers = list(range(1, len(manifest) + 1))
    manifest_numbers = [row["shot"] for row in manifest]
    if manifest_numbers != expected_numbers:
        failures.append("Manifest shot numbers are not consecutive from 1.")

    for row in manifest:
        screenshot_path = Path(row["screenshot_path"])
        if not screenshot_path.exists() or screenshot_path.stat().st_size == 0:
            failures.append(f"Missing or empty screenshot: {screenshot_path}")
            continue
        with Image.open(screenshot_path) as image:
            width, height = image.size
            if width <= 0 or height <= 0:
                failures.append(f"Invalid screenshot dimensions: {screenshot_path}")

    starts = [parse_timecode(row["start"]) for row in manifest]
    ends = [parse_timecode(row["end"]) for row in manifest]
    durations = [float(row["duration_seconds"]) for row in manifest]
    if starts and abs(starts[0]) > 0.01:
        failures.append(f"First shot starts at {starts[0]:.3f}, not 0.")
    for index in range(len(manifest) - 1):
        if abs(ends[index] - starts[index + 1]) > 0.02:
            failures.append(f"Timing gap/overlap between shots {index + 1} and {index + 2}.")
        if durations[index] <= 0:
            failures.append(f"Shot {index + 1} has non-positive duration.")
    if durations and durations[-1] <= 0:
        failures.append(f"Shot {len(durations)} has non-positive duration.")

    source_duration = probe_duration(video_path)
    if ends and abs(ends[-1] - source_duration) > 0.10:
        failures.append(
            f"Final shot ends at {ends[-1]:.3f}, but source duration is {source_duration:.3f}."
        )

    make_contact_sheet(screenshots, contact_sheet_path)
    summary = {
        "shots": len(manifest),
        "screenshots": len(screenshots),
        "workbook_rows": len(data_rows),
        **counts,
        "source_duration_seconds": round(source_duration, 3),
        "final_end_seconds": round(ends[-1], 3) if ends else None,
        "contact_sheet": str(contact_sheet_path),
    }
    return not failures, failures, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("output_dir", type=Path)
    args = parser.parse_args(argv)

    ok, failures, summary = verify(args.video.resolve(), args.output_dir.resolve())
    print(json.dumps({"ok": ok, "summary": summary, "failures": failures}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
