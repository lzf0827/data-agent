const $ = (id) => document.getElementById(id);
let fileId = null;
let activeRun = null;

function showMessage(text, error = false) {
  const box = $("message");
  box.textContent = text;
  box.style.background = error ? "#9f2d2d" : "#17365d";
  box.classList.remove("hidden");
  setTimeout(() => box.classList.add("hidden"), 6000);
}

async function api(url, options = {}) {
  const response = await fetch(url, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof body.detail === "string" ? body.detail : body.detail?.message || body.detail?.error || "Request failed");
  return body;
}

async function upload() {
  if (fileId) return fileId;
  const file = $("file").files[0];
  if (!file) throw new Error("请先选择 raw data Excel 文件。");
  const data = new FormData();
  data.append("file", file);
  const result = await api("/api/files", { method: "POST", body: data });
  fileId = result.file_id;
  $("fileLabel").textContent = `✓ ${result.filename}`;
  return fileId;
}

function renderIntent(result) {
  const intent = result.intent;
  const targets = intent.analysis_targets || (intent.channels || []).map((channel) => ({ channel, primary_sku: intent.primary_sku }));
  $("intent").innerHTML = [
    ...targets.map((target) => `<span class="chip">${target.channel} · ${target.primary_sku}</span>`),
    `<span class="chip">Period · ${intent.months} months</span>`,
    `<span class="chip">Parser · ${result.parser || "recognized"}</span>`,
  ].join("");
  $("intent").classList.remove("hidden");
}

function renderLabels(state) {
  activeRun = state.run_id;
  const plan = state.semantic_plan;
  const groups = (plan.channel_groups || []).map((group) => {
    const competitors = (group.competitor_headers || []).map((item) => `${item.brand} (${item.label.cell})`).join(", ");
    return `<div class="label-group"><h3>${group.channel} · ${group.raw_sheet}</h3><p>Channel: <b>${group.channel_label.raw_text}</b> (${group.channel_label.cell}) · Philips header: <b>${group.primary_header.raw_text}</b> (${group.primary_header.cell})</p><p>Competitors: ${competitors || "—"}</p><small>Sandbox: rows ${group.data_start_row}–${group.data_end_row}, columns ${group.start_column}–${group.end_column}</small></div>`;
  }).join("");
  const unknown = (plan.unknown_labels || []).map((item) => `<li>${item.raw_text} · ${item.role} · ${item.cell} · ${Math.round(item.confidence * 100)}%</li>`).join("");
  $("labels").innerHTML = `${groups}${unknown ? `<h3>Labels needing approval</h3><ul>${unknown}</ul>` : ""}<p>${(plan.review_reasons || []).join(" · ")}</p>`;
  $("labelCard").classList.remove("hidden");
  $("labelCard").scrollIntoView({ behavior: "smooth" });
}

function setBusy(isBusy) {
  document.querySelectorAll("button").forEach((button) => { button.disabled = isBusy; });
}

function fmt(value) {
  if (value === null || value === undefined || value === "") return "—";
  return typeof value === "number" ? value.toLocaleString(undefined, { maximumFractionDigits: 2 }) : String(value);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (character) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[character]);
}

function normalizedKey(value) {
  return String(value ?? "").toUpperCase().replace(/[^A-Z0-9]/g, "");
}

function niceMaximum(value) {
  if (!Number.isFinite(value) || value <= 0) return 1;
  const magnitude = 10 ** Math.floor(Math.log10(value));
  const normalized = value / magnitude;
  const ceiling = normalized <= 1 ? 1 : normalized <= 2 ? 2 : normalized <= 5 ? 5 : 10;
  return ceiling * magnitude;
}

function renderTrendChart(result) {
  const records = (result.records || [])
    .filter((item) => item.role === "PH")
    .sort((left, right) => String(left.period).localeCompare(String(right.period)));
  if (!records.length) return '<p class="report-empty">No validated Philips monthly records are available for this chart.</p>';

  const width = 1120;
  const height = 410;
  const margin = { top: 58, right: 78, bottom: 62, left: 78 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const salesValues = records.map((item) => Number(item.sales)).filter(Number.isFinite);
  const priceValues = records.map((item) => Number(item.price)).filter(Number.isFinite);
  const salesMax = niceMaximum(Math.max(...salesValues, 1));
  const rawPriceMin = Math.min(...priceValues);
  const rawPriceMax = Math.max(...priceValues);
  const priceSpan = Math.max(rawPriceMax - rawPriceMin, rawPriceMax * 0.08, 1);
  const priceMin = Math.max(0, rawPriceMin - priceSpan * 0.18);
  const priceMax = rawPriceMax + priceSpan * 0.22;
  const xStep = plotWidth / records.length;
  const barWidth = Math.max(12, xStep * 0.58);
  const x = (index) => margin.left + xStep * index + xStep / 2;
  const salesY = (value) => margin.top + plotHeight - (Number(value || 0) / salesMax) * plotHeight;
  const priceY = (value) => margin.top + plotHeight - ((Number(value) - priceMin) / (priceMax - priceMin)) * plotHeight;
  const ticks = [0, 0.25, 0.5, 0.75, 1];
  const grid = ticks.map((ratio) => {
    const y = margin.top + plotHeight * (1 - ratio);
    const leftValue = salesMax * ratio;
    const rightValue = priceMin + (priceMax - priceMin) * ratio;
    return `<line x1="${margin.left}" y1="${y}" x2="${width - margin.right}" y2="${y}" class="chart-grid"/><text x="${margin.left - 12}" y="${y + 5}" text-anchor="end" class="chart-axis">${fmt(leftValue)}</text><text x="${width - margin.right + 12}" y="${y + 5}" class="chart-axis">${fmt(rightValue)}</text>`;
  }).join("");
  const bars = records.map((item, index) => {
    const y = salesY(item.sales);
    return `<rect x="${x(index) - barWidth / 2}" y="${y}" width="${barWidth}" height="${margin.top + plotHeight - y}" class="sales-bar"><title>${escapeHtml(item.period_label)} · Sales: ${escapeHtml(fmt(item.sales))}</title></rect>`;
  }).join("");
  const points = records.map((item, index) => `${x(index)},${priceY(item.price)}`).join(" ");
  const labels = records.map((item, index) => {
    const pointY = priceY(item.price);
    const previousY = index ? priceY(records[index - 1].price) : Number.POSITIVE_INFINITY;
    const nextY = index + 1 < records.length ? priceY(records[index + 1].price) : Number.POSITIVE_INFINITY;
    const crowded = Math.abs(pointY - previousY) < 22 || Math.abs(pointY - nextY) < 22;
    const labelY = Math.max(margin.top + 12, pointY - (crowded && index % 2 ? 27 : 13));
    return `<circle cx="${x(index)}" cy="${pointY}" r="4.5" class="price-point"><title>${escapeHtml(item.period_label)} · Price: ${escapeHtml(fmt(item.price))}</title></circle><text x="${x(index)}" y="${labelY}" text-anchor="middle" class="price-label">${escapeHtml(fmt(item.price))}</text><text x="${x(index)}" y="${margin.top + plotHeight + 25}" text-anchor="middle" class="chart-axis">${escapeHtml(item.period_label)}</text>`;
  }).join("");
  return `<section class="web-visualization" aria-labelledby="chart-title-${escapeHtml(result.channel)}"><h4 id="chart-title-${escapeHtml(result.channel)}">Sales (Columns, Left Axis) &amp; Price (Line) | Latest 12 Months</h4><div class="chart-scroll"><svg class="trend-chart" viewBox="0 0 ${width} ${height}" role="img" aria-label="Philips monthly sales columns and ASP price line for ${escapeHtml(result.channel)}"><title>Philips monthly sales and price trend</title><desc>Sales use the left axis and navy columns. ASP uses the right axis and a blue line with warm value labels.</desc>${grid}<line x1="${margin.left}" y1="${margin.top + plotHeight}" x2="${width - margin.right}" y2="${margin.top + plotHeight}" class="chart-axis-line"/>${bars}<polyline points="${points}" class="price-line"/>${labels}<text x="20" y="${margin.top + plotHeight / 2}" text-anchor="middle" transform="rotate(-90 20 ${margin.top + plotHeight / 2})" class="chart-axis-title">Sales (Units)</text><text x="${width - 20}" y="${margin.top + plotHeight / 2}" text-anchor="middle" transform="rotate(90 ${width - 20} ${margin.top + plotHeight / 2})" class="chart-axis-title">Price (ASP)</text><g class="chart-legend"><rect x="${width / 2 - 105}" y="20" width="14" height="14" class="sales-bar"/><text x="${width / 2 - 84}" y="32">Sales</text><line x1="${width / 2 + 15}" y1="27" x2="${width / 2 + 47}" y2="27" class="price-line"/><circle cx="${width / 2 + 31}" cy="27" r="4" class="price-point"/><text x="${width / 2 + 55}" y="32">Price</text></g></svg></div></section>`;
}

function renderMonthlyComparison(result) {
  const records = result.records || [];
  const periods = [...new Set(records.map((item) => item.period_label))].sort();
  const mappings = (result.mapping || []).filter((item) => item.role === "PH" || item.role === "Competitor");
  if (!periods.length || !mappings.length) return '<p class="report-empty">No validated monthly comparison data are available.</p>';
  const recordIndex = new Map(records.map((item) => [`${normalizedKey(item.brand)}|${normalizedKey(item.model)}|${item.period_label}`, item]));
  const rows = mappings.flatMap((mapping, mappingIndex) => {
    const values = (metric) => periods.map((period) => {
      const record = recordIndex.get(`${normalizedKey(mapping.brand)}|${normalizedKey(mapping.model)}|${period}`);
      return `<td class="num">${escapeHtml(fmt(record?.[metric]))}</td>`;
    }).join("");
    const rowClass = mappingIndex % 2 ? "comparison-pair-alt" : "";
    return [
      `<tr class="${rowClass}"><th scope="rowgroup" rowspan="2">${escapeHtml(mapping.brand)}</th><td rowspan="2" class="model-cell">${escapeHtml(mapping.model)}</td><td class="metric-cell">prices</td>${values("price")}</tr>`,
      `<tr class="${rowClass}"><td class="metric-cell">sales</td>${values("sales")}</tr>`,
    ];
  }).join("");
  return `<section class="monthly-comparison" aria-labelledby="monthly-title-${escapeHtml(result.channel)}"><h4 id="monthly-title-${escapeHtml(result.channel)}">PHILIPS &amp; Competitor Monthly Price &amp; Sales | Latest 12 Months</h4><div class="report-table-scroll"><table class="report-table"><thead><tr><th>Brand</th><th>Model</th><th>Metric</th>${periods.map((period) => `<th class="num">${escapeHtml(period)}</th>`).join("")}</tr></thead><tbody>${rows}</tbody></table></div><p class="report-definition">Definitions: prices = ASP; sales = Unit. Competitor models follow the validated same-channel mapping, with one selected model per competitor brand.</p></section>`;
}

function renderReview(result) {
  renderIntent(result);
  const sections = Object.entries(result.channels).map(([channel, data]) => {
    const primary = data.mappings.find((item) => item.role === "PH");
    const mappings = data.mapping_resolutions.map((item) => `<tr><td>${item.brand}</td><td>${item.state}</td><td>${item.selected_model || "—"}</td><td>${(item.present_candidates || []).join(", ") || "—"}</td><td>${item.reason}</td></tr>`).join("");
    const primaryRecords = data.records.filter((item) => item.role === "PH");
    const rows = primaryRecords.map((item) => {
      const cells = item.source_cells || {};
      return `<tr><td>${item.period_label}</td><td>${item.brand}</td><td>${item.model}</td><td class="num">${fmt(item.sales_value)}</td><td class="num">${fmt(item.sales)}</td><td class="num">${fmt(item.price)}</td><td>${cells.sales_value?.cell || "—"} / ${cells.sales?.cell || "—"} / ${cells.price?.cell || "—"}</td></tr>`;
    }).join("");
    return `<div class="review-channel"><div class="review-heading"><h3>${channel}</h3><span>${data.source_sheet} · ${data.available_range.join(" to ")} · ${data.available_months} months</span></div><div class="primary-model"><b>Philips model used:</b> ${primary?.model || "—"} <span>${primary?.mapping_state || "—"}${primary?.raw_mapping_value && primary.mapping_state === "CHANNEL_ALIAS" ? ` · ${primary.raw_mapping_value}` : ""}</span></div><h4>Mapping states</h4><div class="table-wrap"><table><thead><tr><th>Brand</th><th>State</th><th>Selected model</th><th>Present candidates</th><th>Reason</th></tr></thead><tbody>${mappings}</tbody></table></div><h4>Extracted monthly data</h4><div class="table-wrap data-preview"><table><thead><tr><th>Month</th><th>Brand</th><th>SKU</th><th class="num">Value</th><th class="num">Unit</th><th class="num">ASP</th><th>Source cells (V/U/A)</th></tr></thead><tbody>${rows}</tbody></table></div></div>`;
  }).join("");
  const intentNotice = result.intent_warning ? '<p class="review-notice">Agnes intent service is temporarily unavailable. This preview used the validated local parser; Excel values and mappings were still extracted deterministically.</p>' : "";
  $("reviewSummary").innerHTML = `<div class="review-meta"><span class="chip">Workbook · ${result.workbook.filename}</span><span class="chip">Adapter · ${result.workbook.adapter_version}</span><span class="chip">Mapping confirmation · ${result.requires_mapping_confirmation ? "required" : "not required"}</span></div>${intentNotice}${sections}`;
  $("reviewCard").classList.remove("hidden");
  $("reviewCard").scrollIntoView({ behavior: "smooth" });
}

function renderMapping(state) {
  activeRun = state.run_id;
  const root = $("mapping");
  root.innerHTML = "";
  for (const [channel, candidates] of Object.entries(state.mapping_candidates)) {
    const group = document.createElement("div");
    group.className = "mapping-group";
    group.dataset.channel = channel;
    group.innerHTML = `<h3>${channel}</h3>`;
    const byBrand = candidates.reduce((groups, item) => {
      (groups[item.brand] ||= []).push(item);
      return groups;
    }, {});
    for (const [brand, items] of Object.entries(byBrand)) {
      const heading = document.createElement("strong");
      heading.textContent = brand;
      group.appendChild(heading);
      items.forEach((item, index) => {
        const label = document.createElement("label");
        label.className = "candidate";
        label.innerHTML = `<input type="radio" name="${channel}-${brand}" value="${encodeURIComponent(item.model)}"><span>${item.model}<br><small>${item.reasons.join(" · ")}</small></span><b>${Math.round(item.confidence * 100)}%</b>`;
        group.appendChild(label);
      });
    }
    root.appendChild(group);
  }
  $("mappingCard").classList.remove("hidden");
  $("mappingCard").scrollIntoView({ behavior: "smooth" });
}

function renderResults(state) {
  activeRun = state.run_id;
  $("mappingCard").classList.add("hidden");
  $("labelCard").classList.add("hidden");
  const downloads = [
    { kind: "pdf", label: "PDF" },
    { kind: "json", label: "JSON" },
    { kind: "zip", label: "ZIP" },
  ];
  $("results").innerHTML = state.results.map((result) => {
    const warnings = result.quality?.warnings?.length || 0;
    const allClaims = result.claims || [];
    const insightSections = [
      ["Internal Drivers", allClaims.filter((claim) => claim.claim_type === "internal")],
      ["External Drivers", allClaims.filter((claim) => claim.claim_type === "external" && claim.subject !== "OFFICIAL_EVENTS")],
      ["Online Research", allClaims.filter((claim) => claim.subject === "OFFICIAL_EVENTS")],
      ["Integrated Cause Analysis", allClaims.filter((claim) => claim.claim_type === "integrated")],
      ["Next-step Actions", allClaims.filter((claim) => claim.claim_type === "decision")],
    ];
    const insights = insightSections.map(([title, items]) => `<section class="insight-section"><h4>${title}</h4><ul>${items.map((claim) => `<li>${escapeHtml(claim.text)}</li>`).join("")}</ul></section>`).join("");
    const visualization = renderTrendChart(result);
    const monthlyComparison = renderMonthlyComparison(result);
    return `<div class="channel-output"><div class="result-heading"><h3>${escapeHtml(result.channel)}</h3><span class="quality ${warnings ? "warning" : "passed"}">${warnings ? `${warnings} warning(s)` : "Quality checks passed"}</span></div>${visualization}<p class="report-meta-line">${result.quality?.row_count || 0} canonical rows were reconciled and published as PDF and JSON.</p><div class="insight-sections">${insights}</div>${monthlyComparison}<div class="downloads">${downloads.map((item) => `<a class="download" href="/api/analysis-runs/${state.run_id}/files/${encodeURIComponent(result.channel)}/${item.kind}">${item.label}</a>`).join("")}</div></div>`;
  }).join("");
  $("resultCard").classList.remove("hidden");
  $("resultCard").scrollIntoView({ behavior: "smooth" });
}

function invalidateReview() {
  $("reviewCard").classList.add("hidden");
  $("intent").classList.add("hidden");
}

async function loadReview({ scroll = true } = {}) {
  await upload();
  const result = await api("/api/reviews", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file_id: fileId, prompt: $("prompt").value }) });
  renderReview(result);
  if (!scroll) window.scrollTo({ top: 0, behavior: "smooth" });
}

$("file").addEventListener("change", async () => {
  fileId = null;
  invalidateReview();
  $("fileLabel").textContent = $("file").files[0]?.name || "Choose .xlsx";
  if (!$("file").files[0]) return;
  try {
    setBusy(true);
    await loadReview({ scroll: false });
    showMessage("Workbook uploaded. Raw data and mappings are ready.");
  } catch (error) { showMessage(error.message, true); } finally { setBusy(false); }
});
$("prompt").addEventListener("input", invalidateReview);

$("inspect").addEventListener("click", async () => {
  try { setBusy(true); renderIntent(await api("/api/intents", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: $("prompt").value }) })); }
  catch (error) { showMessage(error.message, true); } finally { setBusy(false); }
});

$("review").addEventListener("click", async () => {
  try {
    setBusy(true);
    await loadReview();
  } catch (error) { showMessage(error.message, true); } finally { setBusy(false); }
});

$("run").addEventListener("click", async () => {
  try {
    setBusy(true);
    await upload();
    const state = await api("/api/analysis-runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file_id: fileId, prompt: $("prompt").value, human_reviewed: !$("reviewCard").classList.contains("hidden") }) });
    renderIntent({ intent: state.intent });
    if (state.status === "awaiting_label_confirmation") renderLabels(state);
    else if (state.status === "awaiting_mapping_confirmation") renderMapping(state);
    else renderResults(state);
  } catch (error) { showMessage(error.message, true); } finally { setBusy(false); }
});

$("confirmLabels").addEventListener("click", async () => {
  try {
    setBusy(true);
    const state = await api(`/api/analysis-runs/${activeRun}/confirm-labels`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approved: true }) });
    $("labelCard").classList.add("hidden");
    if (state.status === "awaiting_mapping_confirmation") renderMapping(state); else renderResults(state);
  } catch (error) { showMessage(error.message, true); } finally { setBusy(false); }
});

$("confirm").addEventListener("click", async () => {
  try {
    setBusy(true);
    const confirmed_mappings = {};
    const missing = [];
    document.querySelectorAll(".mapping-group").forEach((group) => {
      const brands = new Set([...group.querySelectorAll("input[type=radio]")].map((input) => input.name));
      brands.forEach((name) => { if (!group.querySelector(`input[name="${name}"]:checked`)) missing.push(name); });
      confirmed_mappings[group.dataset.channel] = [...group.querySelectorAll("input:checked")].map((input) => ({ brand: input.name.split("-").slice(1).join("-"), model: decodeURIComponent(input.value) }));
    });
    if (missing.length) throw new Error(`请选择竞品型号：${missing.join(", ")}`);
    const state = await api(`/api/analysis-runs/${activeRun}/confirm`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirmed_mappings }) });
    renderResults(state);
  } catch (error) { showMessage(error.message, true); } finally { setBusy(false); }
});

fetch("/api/health").then((r) => r.json()).then((health) => {
  const llm = health.llm || {};
  $("health").textContent = llm.configured ? `Agnes configured · ${llm.last_status}` : "Local fallback · add API key";
}).catch(() => { $("health").textContent = "Offline"; });
