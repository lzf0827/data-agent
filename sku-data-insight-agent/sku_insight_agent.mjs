import fs from "node:fs/promises";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  FileBlob,
  PresentationFile,
  SpreadsheetFile,
  Workbook,
} from "@oai/artifact-tool";

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (!arg.startsWith("--")) continue;
    const key = arg.slice(2);
    const next = argv[i + 1];
    out[key] = next && !next.startsWith("--") ? (i += 1, next) : true;
  }
  return out;
}

function normalize(value) {
  return String(value ?? "")
    .trim()
    .toUpperCase()
    .replace(/\s+/g, "")
    .replace(/[（）]/g, (m) => (m === "（" ? "(" : ")"));
}

function compactChineseInsight(value, primarySku, maxChars = 34) {
  const text = String(value ?? "").replace(/\s+/g, " ").trim().replace(String(primarySku ?? ""), "本品");
  const cjkCount = (text.match(/[\u3400-\u9fff]/g) ?? []).length;
  const latinCount = (text.match(/[A-Za-z]/g) ?? []).length;
  if (cjkCount < 4 || latinCount > Math.max(24, cjkCount * 3)) {
    return "该条洞察未通过中文语言校验，已从报告正文隐藏。";
  }
  if (text.length <= maxChars) return text;
  const prefix = text.slice(0, maxChars);
  const punctuation = Math.max(prefix.lastIndexOf("。"), prefix.lastIndexOf("；"), prefix.lastIndexOf("，"));
  const cut = punctuation >= Math.floor(maxChars * 0.62) ? prefix.slice(0, punctuation + 1) : prefix;
  return `${cut.replace(/[，；。\s]+$/g, "")}…`;
}

function pct(value) {
  return Number.isFinite(value) ? `${value >= 0 ? "+" : ""}${(value * 100).toFixed(1)}%` : "—";
}

function num(value, digits = 0) {
  if (!Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", { maximumFractionDigits: digits, minimumFractionDigits: digits });
}

function pearson(xs, ys) {
  const pairs = xs.map((x, i) => [x, ys[i]]).filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
  if (pairs.length < 3) return null;
  const mx = pairs.reduce((s, p) => s + p[0], 0) / pairs.length;
  const my = pairs.reduce((s, p) => s + p[1], 0) / pairs.length;
  let top = 0; let dx = 0; let dy = 0;
  for (const [x, y] of pairs) {
    top += (x - mx) * (y - my);
    dx += (x - mx) ** 2;
    dy += (y - my) ** 2;
  }
  return dx > 0 && dy > 0 ? top / Math.sqrt(dx * dy) : null;
}

function periodLabel(date) {
  return `${String(date.getUTCFullYear()).slice(2)}-${String(date.getUTCMonth() + 1).padStart(2, "0")}`;
}

function findSheet(workbook, name) {
  const sheet = workbook.worksheets.items.find((item) => item.name === name);
  if (!sheet) throw new Error(`Required sheet not found: ${name}`);
  return sheet;
}

function buildInsights(primaryRows) {
  const valid = primaryRows.filter((r) => Number.isFinite(r.price) && Number.isFinite(r.sales));
  if (valid.length < 2) return ["有效月度数据不足，暂无法生成趋势洞察。"];
  const first = valid[0];
  const last = valid[valid.length - 1];
  const priceChange = last.price / first.price - 1;
  const salesChange = last.sales / first.sales - 1;
  const peak = valid.reduce((a, b) => (b.sales > a.sales ? b : a));
  const prices = valid.map((r) => r.price);
  const sales = valid.map((r) => r.sales);
  const corr = pearson(prices, sales);
  const priceRange = (Math.max(...prices) - Math.min(...prices)) / (prices.reduce((a, b) => a + b, 0) / prices.length);
  const relationship = corr === null ? "价格与销量关系暂不显著" : corr <= -0.35 ? `价格与销量呈负相关（r=${corr.toFixed(2)}）` : corr >= 0.35 ? `价格与销量呈正相关（r=${corr.toFixed(2)}）` : `价格与销量相关性较弱（r=${corr.toFixed(2)}）`;
  return [
    `近12个月 ASP ${priceChange >= 0 ? "上升" : "下降"} ${Math.abs(priceChange * 100).toFixed(1)}%，销量 ${salesChange >= 0 ? "增长" : "下降"} ${Math.abs(salesChange * 100).toFixed(1)}%。`,
    `销量峰值出现在 ${peak.periodLabel}（${num(peak.sales)} 台）；价格波动区间约为均价的 ${(priceRange * 100).toFixed(1)}%。`,
    `${relationship}；建议结合大促、渠道活动与库存进一步验证因果。`,
  ];
}

async function createAnalysisWorkbook({ sourcePath, sourceSheetName, sourceHash, adapterVersion, dbPath, runId, channel, sku, mapping, records, periods, standardFacts, observations, claims, quality, outputPath, previewDir, insightsOverride = null }) {
  const wb = Workbook.create();
  const readme = wb.worksheets.add("README");
  const config = wb.worksheets.add("Config");
  const mapSheet = wb.worksheets.add("Competitor Mapping");
  const monthly = wb.worksheets.add("Monthly Data");
  const factSheet = wb.worksheets.add("Standard Fact Table");
  const qualitySheet = wb.worksheets.add("Data Quality");
  const elasticitySheet = wb.worksheets.add("Price Elasticity");
  const trackingSheet = wb.worksheets.add("Competitor Tracking");
  const monitoringSheet = wb.worksheets.add("Monitoring Report");
  const output = wb.worksheets.add("Analysis Output");
  const dashboard = wb.worksheets.add("Dashboard");
  for (const sheet of wb.worksheets.items) sheet.showGridLines = false;

  const navy = "#17365D";
  const teal = "#1E6A88";
  const light = "#EAF2F6";
  const border = "#C8D5DF";

  readme.getRange("A1:F1").merge();
  readme.getRange("A1").values = [["SKU Data Insight Agent | User Guide"]];
  readme.getRange("A1:F1").format = { fill: navy, font: { color: "#FFFFFF", bold: true, size: 18 }, rowHeight: 30 };
  readme.getRange("A3:B9").values = [
    ["Step", "Description"],
    ["1", "Upload a Pricing Analysis workbook with the supported structure."],
    ["2", "Specify the Philips SKU, channel and analysis period."],
    ["3", "Monthly Data stores canonical ASP, Unit and Value with cell provenance."],
    ["4", "Analysis Output preserves the agreed month-by-month comparison format."],
    ["5", "Dashboard provides a quick price and sales trend check."],
    ["Metric definitions", "Sales = Unit; Price = ASP; default window = latest 12 complete months."],
  ];
  readme.getRange("A3:B3").format = { fill: teal, font: { color: "#FFFFFF", bold: true } };
  readme.getRange("A3:B9").format.borders = { preset: "all", style: "thin", color: border };
  readme.getRange("A:B").format.columnWidth = 24;
  readme.getRange("B:B").format.columnWidth = 72;
  readme.getRange("A3:B9").format.wrapText = true;

  config.getRange("A1:B12").values = [
    ["Parameter", "Value"],
    ["Source workbook", sourcePath],
    ["Source sheet", sourceSheetName],
    ["Source SHA-256", sourceHash],
    ["Adapter version", adapterVersion],
    ["DuckDB database", dbPath],
    ["SQL run_id", runId],
    ["Channel", channel],
    ["Primary SKU", sku],
    ["Period", `${periodLabel(periods[0])} to ${periodLabel(periods[periods.length - 1])}`],
    ["Generated", new Date()],
    ["Validation query", `SELECT * FROM monthly_metric WHERE run_id='${runId}' ORDER BY period, brand;`],
  ];
  config.getRange("A1:B1").format = { fill: navy, font: { color: "#FFFFFF", bold: true } };
  config.getRange("A1:B12").format.borders = { preset: "all", style: "thin", color: border };
  config.getRange("A:A").format.columnWidth = 24;
  config.getRange("B:B").format.columnWidth = 85;
  config.getRange("B11").format.numberFormat = "yyyy-mm-dd hh:mm";

  const mapRows = [["Philips SKU", "Competitor Brand", "Competitor SKU", "Mapping Type", "Mapping State", "Raw Mapping Value", "Source", "Confidence"]];
  for (const item of mapping) {
    mapRows.push([sku, item.role === "PH" ? "" : item.brand, item.model, item.role === "PH" ? "Primary SKU" : item.source, item.mappingState, item.rawMappingValue ?? "", item.source, item.confidence ?? 1]);
  }
  mapSheet.getRangeByIndexes(0, 0, mapRows.length, mapRows[0].length).values = mapRows;
  mapSheet.getRange("A1:H1").format = { fill: navy, font: { color: "#FFFFFF", bold: true } };
  mapSheet.getRangeByIndexes(0, 0, mapRows.length, 8).format.borders = { preset: "all", style: "thin", color: border };
  mapSheet.getRange("A:H").format.columnWidth = 22;
  mapSheet.getRange("G:G").format.columnWidth = 36;
  mapSheet.freezePanes.freezeRows(1);

  const monthlyRows = [["Channel", "Period", "Period Label", "Role", "Brand", "Model", "Price (ASP)", "Sales (Unit)", "Sales Value", "Source Sheet", "ASP Cell", "Unit Cell", "Value Cell", "Mapping State"]];
  for (const r of records) monthlyRows.push([channel, r.period, r.periodLabel, r.role, r.brand, r.model, r.price, r.sales, r.salesValue, r.sourceSheet, r.sourceCells?.price?.cell ?? "", r.sourceCells?.sales?.cell ?? "", r.sourceCells?.sales_value?.cell ?? "", r.mappingState]);
  monthly.getRangeByIndexes(0, 0, monthlyRows.length, monthlyRows[0].length).values = monthlyRows;
  monthly.getRange("A1:N1").format = { fill: navy, font: { color: "#FFFFFF", bold: true } };
  monthly.getRangeByIndexes(0, 0, monthlyRows.length, 14).format.borders = { preset: "insideHorizontal", style: "thin", color: "#E2E8F0" };
  monthly.getRange(`B2:B${monthlyRows.length}`).format.numberFormat = "yyyy-mm";
  monthly.getRange(`G2:G${monthlyRows.length}`).format.numberFormat = "#,##0.0";
  monthly.getRange(`H2:I${monthlyRows.length}`).format.numberFormat = "#,##0";
  monthly.getRange("A:N").format.columnWidth = 18;
  monthly.getRange("F:F").format.columnWidth = 34;
  monthly.freezePanes.freezeRows(1);

  const changeValue = (value) => value == null ? "—" : pct(value / 100);
  const changeSummary = (fact, suffix) => `ASP ${changeValue(fact[`asp_${suffix}_change_pct`])} | Qty ${changeValue(fact[`qty_${suffix}_change_pct`])} | GMV ${changeValue(fact[`gmv_${suffix}_change_pct`])}`;
  const factRows = [["Month", "Brand", "SKU", "Category", "Platform", "ASP", "Qty", "GMV", "LM Change", "LY Change", "ASP LM %", "Qty LM %", "GMV LM %", "ASP LY %", "Qty LY %", "GMV LY %", "Mapping State", "Source Sheet"]];
  for (const fact of standardFacts) factRows.push([new Date(`${fact.month}T00:00:00Z`), fact.brand, fact.sku, fact.category, fact.platform, fact.asp, fact.qty, fact.gmv, changeSummary(fact, "lm"), changeSummary(fact, "ly"), fact.asp_lm_change_pct == null ? null : fact.asp_lm_change_pct / 100, fact.qty_lm_change_pct == null ? null : fact.qty_lm_change_pct / 100, fact.gmv_lm_change_pct == null ? null : fact.gmv_lm_change_pct / 100, fact.asp_ly_change_pct == null ? null : fact.asp_ly_change_pct / 100, fact.qty_ly_change_pct == null ? null : fact.qty_ly_change_pct / 100, fact.gmv_ly_change_pct == null ? null : fact.gmv_ly_change_pct / 100, fact.mapping_state, fact.source_sheet]);
  factSheet.getRangeByIndexes(0, 0, factRows.length, factRows[0].length).values = factRows;
  factSheet.getRange("A1:R1").format = { fill: navy, font: { color: "#FFFFFF", bold: true } };
  factSheet.getRangeByIndexes(0, 0, factRows.length, 18).format.borders = { preset: "insideHorizontal", style: "thin", color: "#E2E8F0" };
  factSheet.getRange(`A2:A${factRows.length}`).format.numberFormat = "yyyy-mm";
  factSheet.getRange(`F2:H${factRows.length}`).format.numberFormat = "#,##0.0";
  factSheet.getRange(`K2:P${factRows.length}`).format.numberFormat = "0.0%";
  factSheet.getRange("A:R").format.columnWidth = 16;
  factSheet.getRange("I:J").format.columnWidth = 34;
  factSheet.freezePanes.freezeRows(1);

  const header = ["Brand", "Model", "Metric", ...periods.map(periodLabel)];
  const wide = [header];
  for (const item of mapping) {
    const itemRows = records.filter((r) => normalize(r.brand) === normalize(item.brand) && normalize(r.model) === normalize(item.model));
    wide.push([item.brand.toLowerCase(), item.model, "prices", ...itemRows.map((r) => r.price)]);
    wide.push(["", "", "sales", ...itemRows.map((r) => r.sales)]);
  }
  output.getRangeByIndexes(0, 0, wide.length, wide[0].length).values = wide;
  output.getRangeByIndexes(0, 0, 1, wide[0].length).format = { fill: navy, font: { color: "#FFFFFF", bold: true } };
  output.getRangeByIndexes(0, 0, wide.length, wide[0].length).format.borders = { preset: "all", style: "thin", color: border };
  output.getRangeByIndexes(1, 3, wide.length - 1, periods.length).format.numberFormat = "#,##0.0";
  output.getRange("A:C").format.columnWidth = 18;
  output.getRange("B:B").format.columnWidth = 30;
  output.getRangeByIndexes(0, 3, 1, periods.length).format.columnWidth = 12;
  output.freezePanes.freezeRows(1);
  output.freezePanes.freezeColumns(3);

  const primary = records.filter((r) => r.role === "PH");
  const primaryFacts = standardFacts.filter((fact) => normalize(fact.brand) === "PHILIPS" && normalize(fact.sku) === normalize(sku));
  const latestPrimaryFact = primaryFacts.at(-1) ?? {};
  const insights = Array.isArray(insightsOverride) && insightsOverride.length >= 4
    ? insightsOverride.slice(0, 10).map((item) => String(item))
    : buildInsights(primary);
  dashboard.getRange("A1:M1").merge();
  dashboard.getRange("A1").values = [[`SKU Data Insight | ${sku} | ${channel}`]];
  dashboard.getRange("A1:M1").format = { fill: navy, font: { color: "#FFFFFF", bold: true, size: 18 }, rowHeight: 30 };
  dashboard.getRange("A3:B4").values = [["Latest ASP", "ASP LM Change"], [latestPrimaryFact.asp ?? null, latestPrimaryFact.asp_lm_change_pct == null ? null : latestPrimaryFact.asp_lm_change_pct / 100]];
  dashboard.getRange("D3:E4").values = [["Latest Qty", "Qty LM Change"], [latestPrimaryFact.qty ?? null, latestPrimaryFact.qty_lm_change_pct == null ? null : latestPrimaryFact.qty_lm_change_pct / 100]];
  dashboard.getRange("A3:B3").format = { fill: teal, font: { color: "#FFFFFF", bold: true } };
  dashboard.getRange("D3:E3").format = { fill: teal, font: { color: "#FFFFFF", bold: true } };
  dashboard.getRange("A3:B4").format.borders = { preset: "all", style: "thin", color: border };
  dashboard.getRange("D3:E4").format.borders = { preset: "all", style: "thin", color: border };
  dashboard.getRange("A4,D4").format.numberFormat = "#,##0.0";
  dashboard.getRange("B4").format.numberFormat = "0.0%";
  dashboard.getRange("E4").format.numberFormat = "0.0%";
  dashboard.getRange("A6:B7").values = [["Latest GMV", "GMV LM Change"], [latestPrimaryFact.gmv ?? null, latestPrimaryFact.gmv_lm_change_pct == null ? null : latestPrimaryFact.gmv_lm_change_pct / 100]];
  dashboard.getRange("A6:B6").format = { fill: teal, font: { color: "#FFFFFF", bold: true } };
  dashboard.getRange("A6:B7").format.borders = { preset: "all", style: "thin", color: border };
  dashboard.getRange("A7").format.numberFormat = "#,##0.0"; dashboard.getRange("B7").format.numberFormat = "0.0%";
  dashboard.getRange("G3:M3").merge();
  dashboard.getRange("G3").values = [["AI Key Insights | Top 5"]];
  dashboard.getRange("G3:M3").format = { fill: teal, font: { color: "#FFFFFF", bold: true } };
  dashboard.getRange("G4:M24").merge();
  dashboard.getRange("G4").values = [[insights.slice(0, 5).map((x, i) => `${i + 1}.${x}`).join("\n")]];
  dashboard.getRange("G4:M24").format = { fill: light, wrapText: true, verticalAlignment: "center", borders: { preset: "outside", style: "thin", color: border } };
  dashboard.getRange("G4:M24").format.font = { size: 16, color: "#1F2937" };

  const qualityRows = [
    ["Check", "Result", "Details"],
    ["Validation status", quality?.status ?? "unknown", "Canonical schema, completeness and reconciliation"],
    ["Canonical rows", quality?.row_count ?? records.length, "Rows written to Monthly Data and DuckDB"],
    ["Primary months", quality?.primary_months ?? periods.length, "Complete ASP and Unit months for the Philips SKU"],
    ["Warnings", quality?.warnings?.length ?? 0, JSON.stringify(quality?.warnings ?? [])],
    ["Reconciliation checks", quality?.reconciliation?.length ?? 0, "Value compared with ASP × Unit using allowed scale factors"],
  ];
  qualitySheet.getRangeByIndexes(0, 0, qualityRows.length, 3).values = qualityRows;
  qualitySheet.getRange("A1:C1").format = { fill: navy, font: { color: "#FFFFFF", bold: true } };
  qualitySheet.getRangeByIndexes(0, 0, qualityRows.length, 3).format.borders = { preset: "all", style: "thin", color: border };
  qualitySheet.getRange("A:B").format.columnWidth = 24;
  qualitySheet.getRange("C:C").format.columnWidth = 90;
  qualitySheet.getRange("A1:C6").format.wrapText = true;

  const elasticityRows = [["Brand", "SKU", "Latest Month", "ASP LM %", "Qty LM %", "GMV LM %", "Elasticity Pattern", "Anomaly Flag", "Interpretation"]];
  for (const item of observations.filter((entry) => entry.role)) elasticityRows.push([item.brand, item.model, item.last_period ?? "", item.asp_lm_change_pct == null ? null : item.asp_lm_change_pct / 100, item.qty_lm_change_pct == null ? null : item.qty_lm_change_pct / 100, item.gmv_lm_change_pct == null ? null : item.gmv_lm_change_pct / 100, item.elasticity_pattern ?? "Not assessable", item.anomaly ? "REVIEW" : "NORMAL", "Descriptive pattern only; causality requires promotion, traffic and inventory evidence."]);
  elasticitySheet.getRangeByIndexes(0, 0, elasticityRows.length, 9).values = elasticityRows;
  elasticitySheet.getRange("A1:I1").format = { fill: navy, font: { color: "#FFFFFF", bold: true } };
  elasticitySheet.getRangeByIndexes(0, 0, elasticityRows.length, 9).format.borders = { preset: "all", style: "thin", color: border };
  elasticitySheet.getRange(`D2:F${elasticityRows.length}`).format.numberFormat = "0.0%";
  elasticitySheet.getRange("A:H").format.columnWidth = 20; elasticitySheet.getRange("I:I").format.columnWidth = 70; elasticitySheet.freezePanes.freezeRows(1);

  const primaryObservation = observations.find((entry) => entry.role === "PH");
  const trackingRows = [["Philips SKU", "Competitor Brand", "Competitor SKU", "Latest ASP", "Latest Qty", "Latest GMV", "ASP LM %", "Qty LM %", "GMV LM %", "Philips Price Gap %", "Elasticity Pattern"]];
  for (const item of observations.filter((entry) => entry.role === "Competitor")) trackingRows.push([sku, item.brand, item.model, item.latest_asp, item.latest_qty, item.latest_gmv, item.asp_lm_change_pct == null ? null : item.asp_lm_change_pct / 100, item.qty_lm_change_pct == null ? null : item.qty_lm_change_pct / 100, item.gmv_lm_change_pct == null ? null : item.gmv_lm_change_pct / 100, primaryObservation?.latest_asp && item.latest_asp ? primaryObservation.latest_asp / item.latest_asp - 1 : null, item.elasticity_pattern ?? "Not assessable"]);
  trackingSheet.getRangeByIndexes(0, 0, trackingRows.length, 11).values = trackingRows;
  trackingSheet.getRange("A1:K1").format = { fill: navy, font: { color: "#FFFFFF", bold: true } };
  trackingSheet.getRangeByIndexes(0, 0, trackingRows.length, 11).format.borders = { preset: "all", style: "thin", color: border };
  trackingSheet.getRange(`G2:J${trackingRows.length}`).format.numberFormat = "0.0%";
  trackingSheet.getRange("A:K").format.columnWidth = 20; trackingSheet.freezePanes.freezeRows(1);

  monitoringSheet.getRange("A1:F1").merge(); monitoringSheet.getRange("A1").values = [[`Monthly Pricing Monitoring Report | ${sku} | ${channel}`]]; monitoringSheet.getRange("A1:F1").format = { fill: navy, font: { color: "#FFFFFF", bold: true, size: 18 }, rowHeight: 30 };
  const reportRows = [["Rank", "Section", "Evidence Level", "Insight", "Observation IDs", "External Evidence IDs"], ...(claims ?? []).slice(0, 10).map((claim, index) => [index + 1, claim.claim_type, claim.evidence_level, claim.text, (claim.observation_ids ?? []).join(", "), (claim.external_evidence_ids ?? []).join(", ")])];
  monitoringSheet.getRangeByIndexes(2, 0, reportRows.length, 6).values = reportRows;
  monitoringSheet.getRange("A3:F3").format = { fill: teal, font: { color: "#FFFFFF", bold: true } };
  monitoringSheet.getRangeByIndexes(2, 0, reportRows.length, 6).format.borders = { preset: "all", style: "thin", color: border };
  monitoringSheet.getRange("A:C").format.columnWidth = 18; monitoringSheet.getRange("D:D").format.columnWidth = 100; monitoringSheet.getRange("E:F").format.columnWidth = 30; monitoringSheet.getRangeByIndexes(2, 0, reportRows.length, 6).format.wrapText = true;

  dashboard.getRange("A9:C21").values = [["Month", "Sales", "Price"], ...primary.map((r) => [r.periodLabel, r.sales, r.price])];
  dashboard.getRange("A9:C9").format = { fill: navy, font: { color: "#FFFFFF", bold: true } };
  dashboard.getRange("B10:C21").format.numberFormat = "#,##0.0";
  dashboard.getRange("A:C").format.columnWidth = 14;
  dashboard.getRange("A:B").format.columnWidth = 18;
  dashboard.getRange("D:E").format.columnWidth = 18;
  dashboard.getRange("E26:M26").merge(); dashboard.getRange("E26").values = [["SKU Trend Chart"]]; dashboard.getRange("E26:M26").format = { fill: teal, font: { color: "#FFFFFF", bold: true }, horizontalAlignment: "center" };
  dashboard.getRange("E27:M42").format = { fill: "#FFFFFF", borders: { preset: "outside", style: "thin", color: border } };

  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  const xlsx = await SpreadsheetFile.exportXlsx(wb);
  await xlsx.save(outputPath);

  await fs.mkdir(previewDir, { recursive: true });
  for (const sheet of wb.worksheets.items) {
    const preview = await wb.render({ sheetName: sheet.name, autoCrop: "all", scale: 1, format: "png" });
    const safe = sheet.name.replace(/[\\/:*?\"<>|]/g, "_");
    await fs.writeFile(path.join(previewDir, `xlsx-${safe}.png`), new Uint8Array(await preview.arrayBuffer()));
  }
  return { insights, primary };
}

async function insertChartImageIntoWorkbook({ xlsxPath, chartImagePath, previewDir, sku }) {
  const wb = await SpreadsheetFile.importXlsx(await FileBlob.load(xlsxPath));
  const dashboard = findSheet(wb, "Dashboard");
  dashboard.deleteAllDrawings();
  const imageBytes = await fs.readFile(chartImagePath);
  dashboard.images.add({
    dataUrl: `data:image/png;base64,${imageBytes.toString("base64")}`,
    alt: `${sku} sales column and price line combined trend chart`,
    anchor: { from: { row: 26, col: 4 }, extent: { widthPx: 900, heightPx: 227 } },
  });
  const output = await SpreadsheetFile.exportXlsx(wb);
  await output.save(xlsxPath);
  const preview = await wb.render({ sheetName: "Dashboard", autoCrop: "all", scale: 1, format: "png" });
  await fs.writeFile(path.join(previewDir, "xlsx-Dashboard.png"), new Uint8Array(await preview.arrayBuffer()));
}

async function createPresentation({ templatePath, sourcePath, sourceSheetName, outputPath, previewPath, sku, channel, mapping, records, observations, claims, insights, primary }) {
  const deck = await PresentationFile.importPptx(await FileBlob.load(templatePath));
  const slide = deck.slides.getItem(0);
  const competitorSlide = slide.duplicate();
  competitorSlide.moveTo(1);
  const comparisonSlide = slide.duplicate();
  comparisonSlide.moveTo(2);
  const title = deck.resolve("sh/547294r6");
  const mappingHeader = deck.resolve("sh/ts7md4r2");
  const phBox = deck.resolve("sh/sryl4zqx");
  const competitorBox = deck.resolve("sh/fu94fe98");
  const insightHeader = deck.resolve("sh/utg3698n");
  const vizHeader = deck.resolve("sh/hofulsf2");

  title.text = `SKU Data Insight | ${sku} (${channel})`;
  title.text.style = { fontSize: 38, bold: true, color: "#111827" };
  title.position = { left: 88, top: 34, width: 1104, height: 60 };

  vizHeader.text = "Sales (Columns, Left Axis) & Price (Line) | Latest 12 Months";
  vizHeader.position = { left: 88, top: 104, width: 1104, height: 36 };
  vizHeader.fill = "#1E6A88";
  vizHeader.text.style = { fontSize: 21, bold: true, color: "#FFFFFF" };
  const visibleVizHeader = slide.shapes.add({
    geometry: "rect",
    name: "Visible Visualization Header",
    position: { left: 88, top: 104, width: 1104, height: 36 },
    fill: "#1E6A88",
    line: { style: "solid", fill: "#17365D", width: 1 },
  });
  visibleVizHeader.text = "Sales (Columns, Left Axis) & Price (Line) | Latest 12 Months";
  visibleVizHeader.text.style = { fontSize: 21, bold: true, color: "#FFFFFF", alignment: "center" };

  const salesValues = primary.map((r) => r.sales);
  const rawSalesMax = Math.max(...salesValues);
  const roughSalesStep = rawSalesMax / 6;
  const salesStepMagnitude = 10 ** Math.floor(Math.log10(roughSalesStep));
  const salesStepRatio = roughSalesStep / salesStepMagnitude;
  const salesAxisMajorUnit = (salesStepRatio <= 1 ? 1 : salesStepRatio <= 2 ? 2 : salesStepRatio <= 5 ? 5 : 10) * salesStepMagnitude;
  const salesAxisMax = (Math.ceil(rawSalesMax / salesAxisMajorUnit) + 1) * salesAxisMajorUnit;
  const salesBars = slide.charts.add("bar", {
    position: { left: 88, top: 146, width: 1104, height: 270 },
    title: "",
    categories: primary.map((r) => r.periodLabel),
    series: [{ name: "Sales (Unit)", values: salesValues, fill: "#17365D" }],
    hasLegend: false,
    barOptions: { direction: "column", grouping: "clustered", gapWidth: 55 },
    xAxis: { textStyle: { fontSize: 15, fill: "#475569", bold: true }, line: { style: "solid", fill: "#FFFFFF", width: 0 } },
    yAxis: { title: "", min: 0, max: salesAxisMax, majorUnit: salesAxisMajorUnit, numberFormatCode: "#,##0", position: "left", textStyle: { fontSize: 13, fill: "#C45A2A", bold: true }, line: { style: "solid", fill: "none", width: 0 }, majorGridlines: { style: "solid", fill: "#E2E8F0", width: 1 } },
    chartFill: "#FFFFFF",
    chartLine: { style: "solid", fill: "#FFFFFF", width: 0 },
    plotAreaFill: "#FFFFFF",
    plotAreaLine: { style: "solid", fill: "#FFFFFF", width: 0 },
  });
  salesBars.name = "Sales Bars";
  const priceValues = primary.map((r) => r.price);
  const rawPriceMin = Math.min(...priceValues);
  const rawPriceMax = Math.max(...priceValues);
  const priceSpan = Math.max(rawPriceMax - rawPriceMin, Math.max(rawPriceMax * 0.08, 10));
  const roughPriceStep = priceSpan / 4;
  const priceStepMagnitude = 10 ** Math.floor(Math.log10(roughPriceStep));
  const priceStepRatio = roughPriceStep / priceStepMagnitude;
  const priceAxisMajorUnit = (priceStepRatio <= 1 ? 1 : priceStepRatio <= 2 ? 2 : priceStepRatio <= 5 ? 5 : 10) * priceStepMagnitude;
  const priceAxisMin = Math.floor((rawPriceMin - priceAxisMajorUnit * 0.55) / priceAxisMajorUnit) * priceAxisMajorUnit;
  const priceAxisMax = Math.ceil((rawPriceMax + priceAxisMajorUnit * 0.55) / priceAxisMajorUnit) * priceAxisMajorUnit;
  const priceLine = slide.charts.add("scatter", {
    // Scatter plots use edge-aligned points while columns use category centers.
    // This calibrated frame makes all 12 price points land on the 12 column centers.
    position: { left: 162, top: 146, width: 1028, height: 270 },
    title: "",
    series: [{
      name: "Price (ASP)",
      xValues: primary.map((_, index) => index + 1),
      values: priceValues,
      valuesFormatCode: "0.0",
      line: { style: "solid", fill: "#2F75B5", width: 3 },
      marker: { symbol: "circle", size: 6 },
    }],
    hasLegend: false,
    dataLabels: {
      showValue: true,
      position: "outEnd",
      textStyle: { fontSize: 15, fill: "#C45A2A", bold: true },
      fill: "none",
      line: { style: "solid", fill: "none", width: 0 },
    },
    scatterOptions: { style: "smoothWithMarkers" },
    xAxis: { visible: false, min: 0.5, max: 12.5, majorUnit: 1, tickLabelPosition: "none", line: { style: "solid", fill: "none", width: 0 }, majorGridlines: null },
    yAxis: {
      visible: false,
      min: priceAxisMin,
      max: priceAxisMax,
      majorUnit: priceAxisMajorUnit,
      tickLabelPosition: "none",
      numberFormatCode: "#,##0",
      position: "right",
      majorGridlines: null,
      line: { style: "solid", fill: "none", width: 0 },
    },
    chartFill: "none",
    chartLine: { style: "solid", fill: "none", width: 0 },
    plotAreaFill: "none",
    plotAreaLine: { style: "solid", fill: "none", width: 0 },
  });
  priceLine.name = "Price Line Overlay";

  const salesAxisTitle = slide.shapes.add({
    geometry: "textbox",
    name: "Sales Axis Title Left",
    position: { left: 28, top: 255, width: 110, height: 24, rotation: 270 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  salesAxisTitle.text = "Sales (Units)";
  salesAxisTitle.text.style = { fontSize: 13, fill: "#C45A2A", bold: true };

  // Artifact-tool currently renders scatter value axes on the left even when
  // position="right". Keep the chart scale native and add a clean, editable
  // right-side price-axis annotation in the reserved margin.
  const priceAxisX = 1194;
  const priceAxisTop = 154;
  const priceAxisBottom = 384;
  slide.shapes.add({
    geometry: "line",
    name: "Price Axis Right",
    position: { left: priceAxisX, top: priceAxisTop, width: 0, height: priceAxisBottom - priceAxisTop },
    line: { style: "solid", fill: "#7FAED3", width: 1 },
  });
  for (let value = priceAxisMin; value <= priceAxisMax + priceAxisMajorUnit * 0.1; value += priceAxisMajorUnit) {
    const y = priceAxisBottom - ((value - priceAxisMin) / (priceAxisMax - priceAxisMin)) * (priceAxisBottom - priceAxisTop);
    slide.shapes.add({
      geometry: "line",
      position: { left: priceAxisX - 5, top: y, width: 5, height: 0 },
      line: { style: "solid", fill: "#7FAED3", width: 1 },
    });
    const tickLabel = slide.shapes.add({
      geometry: "textbox",
      name: `Price Axis Tick ${value}`,
      position: { left: priceAxisX + 4, top: y - 10, width: 42, height: 20 },
      fill: "none",
      line: { style: "solid", fill: "none", width: 0 },
    });
    tickLabel.text = Number.isInteger(value) ? String(value) : value.toFixed(1);
    tickLabel.text.style = { fontSize: 13, fill: "#C45A2A", bold: true };
  }
  const priceAxisTitle = slide.shapes.add({
    geometry: "textbox",
    name: "Price Axis Title Right",
    position: { left: 1205, top: 255, width: 110, height: 24, rotation: 270 },
    fill: "none",
    line: { style: "solid", fill: "none", width: 0 },
  });
  priceAxisTitle.text = "Price (ASP)";
  priceAxisTitle.text.style = { fontSize: 13, fill: "#C45A2A", bold: true };

  insightHeader.text = "Summary & Next-step Actions";
  insightHeader.position = { left: 88, top: 424, width: 1104, height: 40 };
  insightHeader.fill = "#1E6A88";
  insightHeader.text.style = { fontSize: 22, bold: true, color: "#FFFFFF" };
  const visibleInsightHeader = slide.shapes.add({
    geometry: "rect",
    name: "Visible Insight Header",
    position: { left: 88, top: 424, width: 1104, height: 40 },
    fill: "#1E6A88",
    line: { style: "solid", fill: "#17365D", width: 1 },
  });
  visibleInsightHeader.text = "Summary & Next-step Actions";
  visibleInsightHeader.text.style = { fontSize: 22, bold: true, color: "#FFFFFF", alignment: "center" };
  const rankedClaims = (claims ?? []).slice(0, 10);
  const insightGroups = [
    { title: "Internal Drivers", claims: rankedClaims.filter((claim) => claim.claim_type === "internal"), left: 88, top: 468, width: 538, height: 96, fontSize: 14 },
    { title: "Integrated Cause Analysis", claims: rankedClaims.filter((claim) => claim.claim_type === "integrated"), left: 88, top: 568, width: 538, height: 126, fontSize: 13.5 },
    { title: "External Drivers", claims: rankedClaims.filter((claim) => claim.claim_type === "external" && claim.subject !== "OFFICIAL_EVENTS"), left: 654, top: 468, width: 538, height: 110, fontSize: 13 },
    { title: "Online Research", claims: rankedClaims.filter((claim) => claim.subject === "OFFICIAL_EVENTS"), left: 654, top: 582, width: 538, height: 54, fontSize: 13 },
    { title: "Next-step Actions", claims: rankedClaims.filter((claim) => claim.claim_type === "decision"), left: 654, top: 640, width: 538, height: 54, fontSize: 14 },
  ];
  for (const group of insightGroups) {
    const sectionHeader = slide.shapes.add({
      geometry: "rect",
      name: `${group.title} Header`,
      position: { left: group.left, top: group.top, width: group.width, height: 22 },
      fill: "#D7E8F0",
      line: { style: "solid", fill: "#B8CDD8", width: 1 },
    });
    sectionHeader.text = group.title;
    sectionHeader.text.style = { fontSize: 14, bold: true, color: "#17365D", alignment: "left" };
    const sectionBody = slide.shapes.add({
      geometry: "rect",
      name: `${group.title} Content`,
      position: { left: group.left, top: group.top + 22, width: group.width, height: group.height - 22 },
      fill: "#F3F8FA",
      line: { style: "solid", fill: "#C8D5DF", width: 1 },
    });
    sectionBody.text = group.claims.map((claim) => `• ${compactChineseInsight(claim.text, sku)}`).join("\n");
    sectionBody.text.style = { fontSize: group.fontSize, color: "#1F2937" };
  }

  for (const box of [mappingHeader, phBox, competitorBox]) {
    box.text = "";
    box.position = { left: 0, top: 0, width: 1, height: 1 };
    box.fill = "#FFFFFF";
    box.line = { style: "solid", fill: "#FFFFFF", width: 0 };
  }

  const periods = primary.map((r) => r.periodLabel);
  const monthlyRows = (items) => {
    const values = [["brand", "Model", "metric", ...periods]];
    for (const item of items) {
      const rows = periods.map((periodLabel) => records.find((r) => r.periodLabel === periodLabel && normalize(r.brand) === normalize(item.brand) && normalize(r.model) === normalize(item.model)) ?? { price: null, sales: null });
      values.push([item.brand, item.model, "prices", ...rows.map((r) => num(r.price, 1))]);
      values.push(["", "", "sales", ...rows.map((r) => num(r.sales, 0))]);
    }
    return values;
  };
  const monthlyColumnWidths = [84, 148, 66, ...Array(12).fill(67.15)];
  const styleMonthlyTable = (table, values) => {
    table.styleOptions = { headerRow: true };
    table.borders.assign({ style: "solid", fill: "#C8D5DF", width: 1 });
    table.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: 15 }).assign({
      fill: "#17365D",
      textStyle: { color: "#FFFFFF", bold: true, fontSize: 18, alignment: "center" },
      margins: { left: 1, right: 1, top: 0, bottom: 0 },
      anchor: "middle",
    });
    table.cells.block({ row: 1, column: 0, rowCount: values.length - 1, columnCount: 15 }).assign({
      textStyle: { color: "#1F2937", fontSize: 20, alignment: "center" },
      margins: { left: 1, right: 1, top: 0, bottom: 0 },
      anchor: "middle",
    });
    table.cells.block({ row: 0, column: 0, rowCount: values.length, columnCount: 3 }).assign({
      textStyle: { fontSize: 16, alignment: "left" },
      margins: { left: 2, right: 1, top: 0, bottom: 0 },
      anchor: "middle",
    });
    for (let row = 1; row < values.length; row += 2) {
      table.cells.block({ row, column: 0, rowCount: 1, columnCount: 15 }).assign({ fill: "#EAF2F6" });
      table.cells.block({ row, column: 0, rowCount: 2, columnCount: 3 }).assign({ textStyle: { bold: true, color: "#17365D", fontSize: 16, alignment: "left" } });
    }
  };

  const byName = (name) => {
    const found = competitorSlide.shapes.items.find((item) => item.name === name);
    if (!found) throw new Error(`Template shape is missing on duplicated slide: ${name}`);
    return found;
  };
  const competitorHeader = byName("Title 1");
  competitorHeader.text = "PHILIPS & Competitor Monthly Price & Sales | Latest 12 Months";
  competitorHeader.position = { left: 88, top: 34, width: 1104, height: 50 };
  competitorHeader.text.style = { fontSize: 22, bold: true, color: "#FFFFFF" };
  competitorHeader.fill = "#1E6A88";
  competitorHeader.line = { style: "solid", fill: "#17365D", width: 1 };
  for (const name of ["Rectangle 5", "Rectangle 6", "Rectangle 7", "Rectangle 8", "Rectangle 10"]) {
    const inherited = byName(name);
    inherited.text = "";
    inherited.position = { left: 0, top: 0, width: 1, height: 1 };
    inherited.fill = "#FFFFFF";
    inherited.line = { style: "solid", fill: "#FFFFFF", width: 0 };
  }
  const visibleCompetitorHeader = competitorSlide.shapes.add({
    geometry: "rect",
    name: "Visible Monthly Data Header",
    position: { left: 88, top: 34, width: 1104, height: 50 },
    fill: "#1E6A88",
    line: { style: "solid", fill: "#17365D", width: 1 },
  });
  visibleCompetitorHeader.text = "PHILIPS & Competitor Monthly Price & Sales | Latest 12 Months";
  visibleCompetitorHeader.text.style = { fontSize: 22, bold: true, color: "#FFFFFF", alignment: "center" };
  const combinedValues = monthlyRows(mapping.slice(0, 5));
  const combinedTable = competitorSlide.tables.add({ rows: combinedValues.length, columns: 15, left: 88, top: 98, width: 1104, height: 440, columnWidths: monthlyColumnWidths, values: combinedValues });
  styleMonthlyTable(combinedTable, combinedValues);
  const annotationTextStyle = { fontSize: 15, color: "#475569" };
  const annotationFill = "#F8FAFC";
  const annotationLine = { style: "solid", fill: "#CBD5E1", width: 1 };
  const footnote = competitorSlide.shapes.add({
    geometry: "rect",
    name: "Competitor Mapping Note",
    position: { left: 88, top: 550, width: 1104, height: 50 },
    fill: annotationFill,
    line: annotationLine,
  });
  footnote.text = "Definitions: prices = ASP; sales = Unit. Competitor models follow the Key SKUs List mapping, with one selected model per competitor brand.";
  footnote.text.style = annotationTextStyle;
  competitorSlide.speakerNotes.textFrame.setText(`[Sources]\n- ${path.basename(sourcePath)}: ${sourceSheetName} monthly Unit and ASP blocks; Key SKUs List or confirmed mapping.\n[/Sources]`);

  const prepareReportSlide = (target, titleText) => {
    const find = (name) => {
      const found = target.shapes.items.find((item) => item.name === name);
      if (!found) throw new Error(`Template shape is missing on duplicated slide: ${name}`);
      return found;
    };
    const inheritedTitle = find("Title 1"); inheritedTitle.text = ""; inheritedTitle.position = { left: 0, top: 0, width: 1, height: 1 };
    for (const name of ["Rectangle 5", "Rectangle 6", "Rectangle 7", "Rectangle 8", "Rectangle 10"]) { const inherited = find(name); inherited.text = ""; inherited.position = { left: 0, top: 0, width: 1, height: 1 }; inherited.fill = "#FFFFFF"; inherited.line = { style: "solid", fill: "#FFFFFF", width: 0 }; }
    const headerShape = target.shapes.add({ geometry: "rect", name: `${titleText} Header`, position: { left: 88, top: 34, width: 1104, height: 50 }, fill: "#1E6A88", line: { style: "solid", fill: "#17365D", width: 1 } });
    headerShape.text = titleText; headerShape.text.style = { fontSize: 22, bold: true, color: "#FFFFFF", alignment: "center" };
  };

  prepareReportSlide(comparisonSlide, "Category Overview & Brand Comparison | Competitor Tracking");
  const percentText = (value) => value == null || !Number.isFinite(value) ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(1)}%`;
  const comparisonRows = [["Brand", "SKU", "Latest ASP", "Latest Qty", "Latest GMV", "ASP LM", "Qty LM", "GMV LM", "Elasticity"]];
  for (const item of observations.filter((entry) => entry.role && (entry.role === "PH" || ["BRAUN", "PANASONIC", "FLYCO"].includes(String(entry.brand).toUpperCase())))) comparisonRows.push([item.brand, item.model, num(item.latest_asp, 1), num(item.latest_qty, 0), num(item.latest_gmv, 0), percentText(item.asp_lm_change_pct), percentText(item.qty_lm_change_pct), percentText(item.gmv_lm_change_pct), item.elasticity_pattern ?? "Not assessable"]);
  const comparisonTable = comparisonSlide.tables.add({ rows: comparisonRows.length, columns: 9, left: 88, top: 108, width: 1104, height: 260, values: comparisonRows });
  comparisonTable.styleOptions = { headerRow: true }; comparisonTable.borders.assign({ style: "solid", fill: "#C8D5DF", width: 1 }); comparisonTable.cells.block({ row: 0, column: 0, rowCount: 1, columnCount: 9 }).assign({ fill: "#17365D", textStyle: { color: "#FFFFFF", bold: true, fontSize: 16, alignment: "center" }, anchor: "middle" }); comparisonTable.cells.block({ row: 1, column: 0, rowCount: comparisonRows.length - 1, columnCount: 9 }).assign({ textStyle: { color: "#1F2937", fontSize: 16, alignment: "center" }, anchor: "middle" });
  const scopeBox = comparisonSlide.shapes.add({ geometry: "rect", name: "Category Cohort Scope", position: { left: 88, top: 392, width: 1104, height: 92 }, fill: annotationFill, line: annotationLine }); scopeBox.text = "Category overview scope: the selected Philips SKU plus its validated mapped competitor models. It is not a full-market category total.\nTracking focus: Philips vs BRAUN, PANASONIC and FLYCO; YOOSE remains available in the standard dataset when mapped."; scopeBox.text.style = annotationTextStyle;
  comparisonSlide.speakerNotes.textFrame.setText(`[Sources]\n- ${path.basename(sourcePath)}: ${sourceSheetName} canonical ASP, Unit and Value records.\n[/Sources]`);

  const notes = deck.resolve("nt/y90nupkv");
  notes.setText(`[Sources]\n- ${path.basename(templatePath)}: visual layout template.\n- ${path.basename(sourcePath)}: ${sourceSheetName} monthly Unit and ASP blocks; Key SKUs List or confirmed mapping.\n- analysis.json: Top 10 claim evidence levels and evidence identifiers.\n[/Sources]`);

  await fs.mkdir(path.dirname(outputPath), { recursive: true });
  const pptx = await PresentationFile.exportPptx(deck);
  await pptx.save(outputPath);
  const helperPath = fileURLToPath(new URL("./restore_ppt_theme.py", import.meta.url));
  const runtimePython = process.env.RUNTIME_PYTHON ?? "C:/Users/320332974/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";
  const restored = spawnSync(runtimePython, [helperPath, templatePath, outputPath], { encoding: "utf8" });
  if (restored.status !== 0) throw new Error(`Failed to restore template theme: ${restored.stderr || restored.stdout}`);
  const finalDeck = await PresentationFile.importPptx(await FileBlob.load(outputPath));
  await fs.mkdir(path.dirname(previewPath), { recursive: true });
  for (let index = 0; index < finalDeck.slides.items.length; index += 1) {
    const preview = await finalDeck.slides.getItem(index).export({ format: "png", scale: 1.5 });
    const outputPreview = index === 0
      ? previewPath
      : path.join(path.dirname(previewPath), `${path.basename(previewPath, path.extname(previewPath))}-slide${index + 1}.png`);
    await fs.writeFile(outputPreview, new Uint8Array(await preview.arrayBuffer()));
  }
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const payloadPath = path.resolve(String(args.payload ?? ""));
  const templatePath = path.resolve(String(args.template ?? ""));
  const outputDir = path.resolve(String(args.output ?? "outputs/sku-insight-agent"));
  if (!args.payload || !args.template) throw new Error("--payload and --template are required");
  const payload = JSON.parse(await fs.readFile(payloadPath, "utf8"));
  const contractPath = fileURLToPath(new URL("./render_contract.json", import.meta.url));
  const renderContract = JSON.parse(await fs.readFile(contractPath, "utf8"));
  if (!renderContract.supported_payload_versions.includes(payload.payload_version)) {
    throw new Error(`Unsupported render payload version: ${payload.payload_version}; supported: ${renderContract.supported_payload_versions.join(", ")}`);
  }
  const sourcePath = String(payload.source_path ?? "");
  const sourceSheetName = String(payload.source_sheet ?? "");
  const dbPath = String(payload.database_path ?? "");
  const runId = String(payload.run_id ?? "");
  const sku = String(payload.sku ?? "");
  const safeSku = String(payload.safe_sku ?? sku.replace(/[^A-Za-z0-9_-]+/g, "-"));
  const channel = String(payload.channel ?? "").toUpperCase();
  const sourceHash = String(payload.source_sha256 ?? "");
  const adapterVersion = String(payload.adapter_version ?? "");
  const quality = payload.quality ?? {};
  const standardFacts = Array.isArray(payload.standard_facts) ? payload.standard_facts : [];
  const observations = Array.isArray(payload.observations) ? payload.observations : [];
  const claims = Array.isArray(payload.claims) ? payload.claims : [];
  const mapping = (payload.mapping ?? []).map((item) => ({
    brand: String(item.brand),
    model: String(item.model),
    role: item.role === "PH" ? "PH" : "Competitor",
    source: String(item.source ?? "Key SKUs List"),
    mappingState: String(item.mapping_state ?? "UNKNOWN"),
    rawMappingValue: item.raw_mapping_value == null ? null : String(item.raw_mapping_value),
  }));
  const records = (payload.records ?? []).map((item) => ({
    period: new Date(`${item.period}T00:00:00Z`),
    periodLabel: String(item.period_label),
    brand: String(item.brand),
    model: String(item.model),
    role: item.role === "PH" ? "PH" : "Competitor",
    price: item.price,
    sales: item.sales,
    salesValue: item.sales_value,
    sourceSheet: String(item.source_sheet ?? sourceSheetName),
    sourceCells: item.source_cells ?? {},
    mappingState: String(item.mapping_state ?? "UNKNOWN"),
  }));
  const periods = [...new Map(records.map((item) => [item.periodLabel, item.period])).values()].sort((a, b) => a - b);
  const insightsOverride = Array.isArray(payload.insights) ? payload.insights : null;
  if (!sku || !channel || !mapping.some((item) => item.role === "PH") || !records.length) throw new Error("Render payload is missing required canonical data");
  await fs.mkdir(outputDir, { recursive: true });
  const primary = records.filter((r) => r.role === "PH");
  if (primary.some((r) => !Number.isFinite(r.price) || !Number.isFinite(r.sales))) throw new Error(`Primary SKU ${sku} has missing monthly price/sales data`);

  const xlsxPath = path.join(outputDir, `SKU_Data_Insight_${safeSku}.xlsx`);
  const pptxPath = path.join(outputDir, `SKU_Data_Insight_${safeSku}.pptx`);
  const previewDir = path.join(outputDir, "previews");
  const { insights } = await createAnalysisWorkbook({ sourcePath, sourceSheetName, sourceHash, adapterVersion, dbPath, runId, channel, sku, mapping, records, periods, standardFacts, observations, claims, quality, outputPath: xlsxPath, previewDir, insightsOverride });
  const pptPreviewPath = path.join(previewDir, `ppt-${safeSku}.png`);
  await createPresentation({ templatePath, sourcePath, sourceSheetName, outputPath: pptxPath, previewPath: pptPreviewPath, sku, channel, mapping, records, observations, claims, insights, primary });
  const chartImagePath = path.join(previewDir, `chart-${safeSku}.png`);
  const cropHelper = fileURLToPath(new URL("./crop_ppt_chart.py", import.meta.url));
  const runtimePython = process.env.RUNTIME_PYTHON ?? "C:/Users/320332974/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe";
  const cropped = spawnSync(runtimePython, [cropHelper, pptPreviewPath, chartImagePath], { encoding: "utf8" });
  if (cropped.status !== 0) throw new Error(`Failed to crop combined chart preview: ${cropped.stderr || cropped.stdout}`);
  await insertChartImageIntoWorkbook({ xlsxPath, chartImagePath, previewDir, sku });

  const summary = { payloadPath, sourcePath, templatePath, dbPath, runId, sku, channel, periods: periods.map(periodLabel), mapping, records: records.length, xlsxPath, pptxPath, previewDir };
  await fs.writeFile(path.join(outputDir, `run-summary-${safeSku}.json`), JSON.stringify(summary, null, 2), "utf8");
  console.log(JSON.stringify(summary, null, 2));
}

await main();
