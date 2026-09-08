import { FileBlob, SpreadsheetFile } from "@oai/artifact-tool";

const sourcePath = "C:/Users/320332974/OneDrive - Philips/Documents/Pricing analysis_SHAVER (June 2026)_sent.xlsx";
const workbook = await SpreadsheetFile.importXlsx(await FileBlob.load(sourcePath));
const sheet = workbook.worksheets.items.find((item) => item.name === "3.2 Shaver SKU(JD)");
if (!sheet) throw new Error("Sheet not found");
const values = sheet.getUsedRange(true).values;
const monthRows = [];
const lowEndRows = [];
for (let index = 0; index < values.length; index += 1) {
  const cell = String(values[index]?.[2] ?? "").trim();
  if (/^[A-Z][a-z]{2}\d{4} Value$/.test(cell)) monthRows.push(index);
  if (cell.toLowerCase() === "low-end") lowEndRows.push(index);
}
const selected = [...new Set([
  ...monthRows.flatMap((row) => [row, row + 1, row + 2]),
  ...lowEndRows.flatMap((row) => [row - 1, row, row + 1]),
])].filter((row) => row >= 0 && row < values.length).sort((a, b) => a - b);
const targetRows = values
  .map((row, index) => ({ row, index }))
  .filter(({ row }) => String(row?.[0] ?? "").trim().toUpperCase() === "S3203/08")
  .map(({ row, index }) => ({ excelRow: index + 1, cellsAtoT: row.slice(0, 20) }));
console.log(JSON.stringify({
  sheet: sheet.name,
  usedRows: values.length,
  usedColumns: Math.max(...values.map((row) => row.length)),
  monthHeaderRows: monthRows.map((row) => ({ excelRow: row + 1, value: values[row][2] })),
  lowEndRows: lowEndRows.map((row) => ({ excelRow: row + 1, value: values[row][2], columnA: values[row][0], columnL: values[row][11], columnM: values[row][12] })),
  targetRows,
}, null, 2));
