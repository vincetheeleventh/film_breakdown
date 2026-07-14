import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const outputDir = process.argv[2];
if (!outputDir) {
  throw new Error("Usage: node scripts/build_film_study_workbook.mjs <output-dir>");
}

const manifestPath = path.join(outputDir, "manifest.json");
const workbookPath = path.join(outputDir, "film_study.xlsx");
const previewPath = path.join(outputDir, "workbook_preview.png");
const manifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));

const headers = [
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
];

const workbook = Workbook.create();
const sheet = workbook.worksheets.add("Shot Study");
sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);

const rows = [
  headers,
  ...manifest.map((row) => [
    row.shot,
    "",
    row.start,
    row.end,
    Number(row.duration_seconds),
    row.visual_description,
    row.audio_dialogue,
    row.action_camera,
    row.narrative_function,
    row.notes,
  ]),
];

sheet.getRangeByIndexes(0, 0, rows.length, headers.length).values = rows;

sheet.getRange("A1:J1").format = {
  fill: "#1F2937",
  font: { bold: true, color: "#FFFFFF" },
  wrapText: true,
  horizontalAlignment: "center",
  verticalAlignment: "center",
  borders: { preset: "all", style: "thin", color: "#CBD5E1" },
};
sheet.getRangeByIndexes(1, 0, Math.max(1, rows.length - 1), headers.length).format = {
  wrapText: true,
  verticalAlignment: "top",
  borders: { preset: "all", style: "thin", color: "#E5E7EB" },
};
sheet.getRangeByIndexes(1, 4, Math.max(1, rows.length - 1), 1).format.numberFormat = "0.00";

const widths = [55, 260, 95, 95, 85, 260, 260, 260, 280, 240];
for (const [index, width] of widths.entries()) {
  sheet.getRangeByIndexes(0, index, rows.length, 1).format.columnWidthPx = width;
}
sheet.getRange("A1:J1").format.rowHeightPx = 28;
for (let i = 0; i < manifest.length; i += 1) {
  sheet.getRangeByIndexes(i + 1, 0, 1, headers.length).format.rowHeightPx = 155;
}

for (const [index, row] of manifest.entries()) {
  const imageBytes = await fs.readFile(row.screenshot_path);
  const dataUrl = `data:image/jpeg;base64,${imageBytes.toString("base64")}`;
  sheet.images.add({
    dataUrl,
    anchor: {
      from: { row: index + 1, col: 1, rowOffsetPx: 8, colOffsetPx: 8 },
      extent: { widthPx: 240, heightPx: 135 },
    },
  });
}

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 300 },
  summary: "final formula error scan",
});
console.log(errors.ndjson);

const preview = await workbook.render({
  sheetName: "Shot Study",
  range: `A1:J${Math.min(rows.length, 8)}`,
  scale: 1,
  format: "png",
});
await fs.writeFile(previewPath, new Uint8Array(await preview.arrayBuffer()));

const output = await SpreadsheetFile.exportXlsx(workbook);
await output.save(workbookPath);
console.log(JSON.stringify({ workbookPath, previewPath, rows: manifest.length }, null, 2));

