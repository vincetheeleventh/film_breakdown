from __future__ import annotations

import json
import zipfile
from pathlib import Path
from xml.sax.saxutils import escape

from PIL import Image

from .models import Shot, ShotAnalysis, format_timestamp


NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PACKAGE_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_DRAWING = "http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing"
NS_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
EMU_PER_PIXEL = 9525


HEADERS = [
    "Shot",
    "Shot Title",
    "Screenshot",
    "Start",
    "End",
    "Duration (s)",
    "Visual Description",
    "Audio / Dialogue",
    "Action / Camera",
    "Camera Movement",
    "Movement Intensity",
    "Movement Confidence",
    "Movement Evidence",
    "Narrative Function",
    "Notes",
]


def _col_name(index: int) -> str:
    name = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        name = chr(65 + remainder) + name
    return name


def _cell_ref(row: int, col: int) -> str:
    return f"{_col_name(col)}{row}"


def _inline_cell(row: int, col: int, value: object, style: int | None = None) -> str:
    ref = _cell_ref(row, col)
    style_attr = f' s="{style}"' if style is not None else ""
    if value is None:
        return f'<c r="{ref}"{style_attr}/>'
    if isinstance(value, (int, float)):
        return f'<c r="{ref}"{style_attr}><v>{value}</v></c>'
    text = escape(str(value))
    return (
        f'<c r="{ref}" t="inlineStr"{style_attr}>'
        f'<is><t xml:space="preserve">{text}</t></is></c>'
    )


def _rels_xml(relationships: list[tuple[str, str, str]]) -> str:
    body = "".join(
        f'<Relationship Id="{rid}" Type="{rtype}" Target="{escape(target)}"/>'
        for rid, rtype, target in relationships
    )
    return f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="{NS_PACKAGE_REL}">{body}</Relationships>'


def _image_size(path: Path) -> tuple[int, int]:
    with Image.open(path) as image:
        return image.size


def _write_zip_text(package: zipfile.ZipFile, path: str, text: str) -> None:
    package.writestr(path, text.encode("utf-8"))


def write_manifest_json(
    output_path: Path,
    shots: list[Shot],
    analyses: dict[int, ShotAnalysis],
) -> None:
    data = []
    for shot in shots:
        analysis = analyses[shot.number]
        data.append(
            {
                "shot": shot.number,
                "start": format_timestamp(shot.start),
                "end": format_timestamp(shot.end),
                "duration_seconds": round(shot.duration, 3),
                "screenshot_path": str(shot.screenshot_path) if shot.screenshot_path else None,
                **analysis.as_dict(),
            }
        )
    output_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def write_workbook(
    output_path: Path,
    shots: list[Shot],
    analyses: dict[int, ShotAnalysis],
    study_context: str = "",
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    media_items: list[tuple[Shot, Path, int, int]] = []

    for shot in shots:
        if shot.screenshot_path:
            width, height = _image_size(shot.screenshot_path)
            media_items.append((shot, shot.screenshot_path, width, height))

    with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as package:
        _write_zip_text(package, "[Content_Types].xml", _content_types_xml(has_drawing=bool(media_items)))
        _write_zip_text(package, "_rels/.rels", _root_rels_xml())
        _write_zip_text(package, "xl/workbook.xml", _workbook_xml())
        _write_zip_text(package, "xl/_rels/workbook.xml.rels", _workbook_rels_xml())
        _write_zip_text(package, "xl/styles.xml", _styles_xml())
        _write_zip_text(package, "xl/worksheets/sheet1.xml", _sheet_xml(shots, analyses, media_items))
        _write_zip_text(package, "xl/worksheets/sheet2.xml", _study_context_sheet_xml(study_context))
        if media_items:
            _write_zip_text(package, "xl/worksheets/_rels/sheet1.xml.rels", _sheet_rels_xml())
            _write_zip_text(package, "xl/drawings/drawing1.xml", _drawing_xml(media_items))
            _write_zip_text(package, "xl/drawings/_rels/drawing1.xml.rels", _drawing_rels_xml(media_items))
            for index, (_shot, image_path, _width, _height) in enumerate(media_items, start=1):
                package.write(image_path, f"xl/media/image{index}.jpg")


def _content_types_xml(has_drawing: bool) -> str:
    drawing_override = (
        '<Override PartName="/xl/drawings/drawing1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>'
        if has_drawing
        else ""
    )
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Default Extension="jpg" ContentType="image/jpeg"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/worksheets/sheet2.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
  {drawing_override}
</Types>"""


def _root_rels_xml() -> str:
    return _rels_xml(
        [
            (
                "rId1",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument",
                "xl/workbook.xml",
            )
        ]
    )


def _workbook_rels_xml() -> str:
    return _rels_xml(
        [
            (
                "rId1",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
                "worksheets/sheet1.xml",
            ),
            (
                "rId2",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
                "worksheets/sheet2.xml",
            ),
            (
                "rId3",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles",
                "styles.xml",
            ),
        ]
    )


def _sheet_rels_xml() -> str:
    return _rels_xml(
        [
            (
                "rId1",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing",
                "../drawings/drawing1.xml",
            )
        ]
    )


def _drawing_rels_xml(media_items: list[tuple[Shot, Path, int, int]]) -> str:
    return _rels_xml(
        [
            (
                f"rId{index}",
                "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image",
                f"../media/image{index}.jpg",
            )
            for index, _item in enumerate(media_items, start=1)
        ]
    )


def _workbook_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="{NS_MAIN}" xmlns:r="{NS_REL}">
  <sheets>
    <sheet name="Shot Study" sheetId="1" r:id="rId1"/>
    <sheet name="Study Context" sheetId="2" r:id="rId2"/>
  </sheets>
</workbook>"""


def _styles_xml() -> str:
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="{NS_MAIN}">
  <numFmts count="1"><numFmt numFmtId="164" formatCode="0.00"/></numFmts>
  <fonts count="2">
    <font><sz val="10"/><name val="Aptos"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="10"/><name val="Aptos"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1F2937"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border>
      <left style="thin"><color rgb="FFD1D5DB"/></left>
      <right style="thin"><color rgb="FFD1D5DB"/></right>
      <top style="thin"><color rgb="FFD1D5DB"/></top>
      <bottom style="thin"><color rgb="FFD1D5DB"/></bottom>
      <diagonal/>
    </border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="4">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="1" xfId="0" applyFill="1" applyFont="1" applyBorder="1" applyAlignment="1"><alignment horizontal="center" vertical="center" wrapText="1"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyBorder="1" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyBorder="1" applyAlignment="1"><alignment horizontal="right" vertical="top"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
  <dxfs count="0"/>
  <tableStyles count="0" defaultTableStyle="TableStyleMedium2" defaultPivotStyle="PivotStyleLight16"/>
</styleSheet>"""


def _sheet_xml(
    shots: list[Shot],
    analyses: dict[int, ShotAnalysis],
    media_items: list[tuple[Shot, Path, int, int]],
) -> str:
    media_by_shot = {shot.number: (width, height) for shot, _path, width, height in media_items}
    rows: list[str] = []
    header_cells = "".join(_inline_cell(1, col, header, style=1) for col, header in enumerate(HEADERS))
    rows.append(f'<row r="1" ht="24" customHeight="1">{header_cells}</row>')

    for row_index, shot in enumerate(shots, start=2):
        width, height = media_by_shot.get(shot.number, (0, 120))
        row_height = max(90, int(height * 0.75) + 8)
        analysis = analyses[shot.number]
        values: list[object] = [
            shot.number,
            analysis.shot_title,
            "",
            format_timestamp(shot.start),
            format_timestamp(shot.end),
            round(shot.duration, 2),
            analysis.visual_description,
            analysis.audio_dialogue,
            analysis.action_camera,
            analysis.camera_movement_type,
            analysis.camera_movement_intensity,
            analysis.camera_movement_confidence,
            analysis.camera_movement_evidence,
            analysis.narrative_function,
            analysis.notes,
        ]
        cells = []
        for col, value in enumerate(values):
            style = 3 if col == 5 else 2
            cells.append(_inline_cell(row_index, col, value, style=style))
        rows.append(f'<row r="{row_index}" ht="{row_height}" customHeight="1">{"".join(cells)}</row>')

    drawing = '<drawing r:id="rId1"/>' if media_items else ""
    last_row = max(1, len(shots) + 1)
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="{NS_MAIN}" xmlns:r="{NS_REL}">
  <sheetViews>
    <sheetView workbookViewId="0" showGridLines="0">
      <pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>
    </sheetView>
  </sheetViews>
  <cols>
    <col min="1" max="1" width="8" customWidth="1"/>
    <col min="2" max="2" width="24" customWidth="1"/>
    <col min="3" max="3" width="56" customWidth="1"/>
    <col min="4" max="5" width="14" customWidth="1"/>
    <col min="6" max="6" width="12" customWidth="1"/>
    <col min="7" max="11" width="38" customWidth="1"/>
  </cols>
  <sheetData>{"".join(rows)}</sheetData>
  <autoFilter ref="A1:K{last_row}"/>
  {drawing}
</worksheet>"""


def _study_context_sheet_xml(study_context: str) -> str:
    rows = [
        '<row r="1" ht="24" customHeight="1">'
        + _inline_cell(1, 0, "Your Read On The Film", style=1)
        + "</row>",
        '<row r="2" ht="220" customHeight="1">'
        + _inline_cell(2, 0, study_context or "", style=2)
        + "</row>",
    ]
    return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="{NS_MAIN}" xmlns:r="{NS_REL}">
  <sheetViews>
    <sheetView workbookViewId="0" showGridLines="0"/>
  </sheetViews>
  <cols>
    <col min="1" max="1" width="120" customWidth="1"/>
  </cols>
  <sheetData>{"".join(rows)}</sheetData>
</worksheet>"""


def _drawing_xml(media_items: list[tuple[Shot, Path, int, int]]) -> str:
    anchors = []
    for index, (shot, _path, width, height) in enumerate(media_items, start=1):
        row = shot.number
        cx = width * EMU_PER_PIXEL
        cy = height * EMU_PER_PIXEL
        anchors.append(
            f"""
  <xdr:oneCellAnchor>
    <xdr:from><xdr:col>2</xdr:col><xdr:colOff>45720</xdr:colOff><xdr:row>{row}</xdr:row><xdr:rowOff>45720</xdr:rowOff></xdr:from>
    <xdr:ext cx="{cx}" cy="{cy}"/>
    <xdr:pic>
      <xdr:nvPicPr>
        <xdr:cNvPr id="{index}" name="Shot {shot.number}"/>
        <xdr:cNvPicPr><a:picLocks noChangeAspect="1"/></xdr:cNvPicPr>
      </xdr:nvPicPr>
      <xdr:blipFill><a:blip r:embed="rId{index}"/><a:stretch><a:fillRect/></a:stretch></xdr:blipFill>
      <xdr:spPr>
        <a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm>
        <a:prstGeom prst="rect"><a:avLst/></a:prstGeom>
      </xdr:spPr>
    </xdr:pic>
    <xdr:clientData/>
  </xdr:oneCellAnchor>"""
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<xdr:wsDr xmlns:xdr="{NS_DRAWING}" xmlns:a="{NS_A}" xmlns:r="{NS_REL}">'
        + "".join(anchors)
        + "</xdr:wsDr>"
    )
