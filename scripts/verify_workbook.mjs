import fs from "node:fs/promises";
import path from "node:path";
import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const workbookPath = process.argv[2];
if (!workbookPath) {
  throw new Error("Usage: node scripts/verify_workbook.mjs <workbook.xlsx>");
}

const outputDir = path.dirname(workbookPath);
const blob = await FileBlob.load(workbookPath);
const workbook = await SpreadsheetFile.importXlsx(blob);

const overview = await workbook.inspect({
  kind: "workbook,sheet,region",
  range: "A1:J8",
  tableMaxRows: 8,
  tableMaxCols: 10,
  maxChars: 3000,
});
console.log(overview.ndjson);

const errors = await workbook.inspect({
  kind: "match",
  searchTerm: "#REF!|#DIV/0!|#VALUE!|#NAME\\?|#N/A",
  options: { useRegex: true, maxResults: 50 },
  summary: "formula error scan",
});
console.log(errors.ndjson);

const preview = await workbook.render({
  sheetName: "Shot Study",
  range: "A1:J5",
  scale: 1,
  format: "png",
});
await fs.writeFile(
  path.join(outputDir, "workbook_preview.png"),
  new Uint8Array(await preview.arrayBuffer()),
);

