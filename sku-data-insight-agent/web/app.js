const $ = (id) => document.getElementById(id);
let fileId = null;
let activeRun = null;
let documentConversation = null;
let documentTurn = null;
let excelConversation = null;
let excelTurn = null;
let liveActivityTimer = null;
let excelStage = "idle";
let excelOriginalPrompt = "";
const EXCEL_SESSION_KEY = "sku-agent-excel-session-v1";
const DOCUMENT_SESSION_KEY = "sku-agent-document-session-v1";

function hasExcelFile() { return Boolean(fileId || $("file")?.files.length); }

function saveExcelSession() {
  try { sessionStorage.setItem(EXCEL_SESSION_KEY, JSON.stringify({ fileId, activeRun, excelStage, excelOriginalPrompt, prompt: $("prompt")?.value || "", messages: $("excelMessages")?.innerHTML || "", conversation: excelConversation, turn: excelTurn })); } catch (_) {}
}

function saveDocumentSession() {
  try { sessionStorage.setItem(DOCUMENT_SESSION_KEY, JSON.stringify({ conversation: documentConversation, turn: documentTurn, messages: $("documentMessages")?.innerHTML || "" })); } catch (_) {}
}

function restoreSessions() {
  try {
    const excel = JSON.parse(sessionStorage.getItem(EXCEL_SESSION_KEY) || "null");
    if (excel) {
      fileId = excel.fileId || null; activeRun = excel.activeRun || null; excelStage = excel.excelStage || "idle"; excelOriginalPrompt = excel.excelOriginalPrompt || "";
      excelConversation = excel.conversation || null; excelTurn = excel.turn || null;
      if ($("prompt")) $("prompt").value = excel.prompt || "";
      if (fileId && $("fileLabel")) $("fileLabel").textContent = "✓ 已恢复 Excel 会话文件";
      if (excel.messages && $("excelMessages")) $("excelMessages").innerHTML = excel.messages;
      if (excelConversation && $("excelStatus")) $("excelStatus").textContent = "已恢复 Excel 对话上下文";
      setExcelStage(excelStage);
    }
    const doc = JSON.parse(sessionStorage.getItem(DOCUMENT_SESSION_KEY) || "null");
    if (doc?.conversation) {
      documentConversation = doc.conversation; documentTurn = doc.turn || null;
      if (doc.messages && $("documentMessages")) $("documentMessages").innerHTML = doc.messages;
      $("documentStatus").textContent = "已恢复当前文档会话上下文";
    }
  } catch (_) {}
}

function setExcelStage(stage) {
  excelStage = stage;
  $("intentConfirmTray").classList.toggle("hidden", stage !== "intent_confirm");
  $("dataConfirmTray").classList.toggle("hidden", stage !== "data_confirm" && stage !== "correction");
  $("excelActionTray").classList.toggle("hidden", !hasExcelFile() || !["idle", "correction"].includes(stage));
  if (stage === "correction") {
    $("prompt").placeholder = "请指出错误的月份、字段和正确值，然后点击箭头重新核对。";
    $("prompt").focus();
  } else if (stage === "idle") {
    $("prompt").placeholder = "例如：分析 Philips S3203/08 在 JD 最近 12 个月的价格与销量，并比较竞品。";
  }
  saveExcelSession();
}

function selectMode(mode) {
  const excel = mode === "excel";
  if (excel) saveDocumentSession(); else saveExcelSession();
  $("excelEntry").classList.toggle("hidden", !excel);
  $("documentEntry").classList.toggle("hidden", excel);
  $("excelActionTray").classList.toggle("hidden", !excel || !hasExcelFile());
  $("chooseExcel").classList.toggle("selected", excel);
  $("chooseDocument").classList.toggle("selected", !excel);
  $("modeContext").textContent = excel ? (excelConversation ? "Excel 对话已恢复：可继续当前任务或提交新的 Workbook 分析。" : "Excel 严格分析已开启：完成后会保存本轮对话上下文。") : (documentConversation ? "文档对话已恢复：可继续追问，工具轨迹和 Findings 会继续累积。" : "文档洞察已开启：完成后会保存本轮对话上下文。");
}

$("chooseExcel").addEventListener("click", () => selectMode("excel"));
$("chooseDocument").addEventListener("click", () => selectMode("document"));

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
  saveExcelSession();
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

function renderPlan(state) {
  activeRun = state.run_id;
  saveExcelSession();
  const plan = state.analysis_plan || {};
  const steps = (plan.steps || []).map((step, index) => `<li><b>${index + 1}. ${escapeHtml(step.operation)}</b>${step.depends_on?.length ? ` · depends on ${escapeHtml(step.depends_on.join(", "))}` : ""}${step.approval_required ? " · approval required" : ""}</li>`).join("");
  $("analysisPlan").innerHTML = `<p><b>Goal:</b> ${escapeHtml(plan.objective || "—")}</p><ol>${steps}</ol><p>${escapeHtml((plan.risks || []).join(" · ") || "No additional planner risks")}</p>`;
  $("planCard").classList.remove("hidden");
  $("planCard").scrollIntoView({ behavior: "smooth" });
}

function setBusy(isBusy) {
  document.querySelectorAll("button").forEach((button) => { button.disabled = isBusy; });
}

const activityLabels = {
  planning: "正在制定分析步骤",
  context: "正在整理上下文",
  tool_call: "正在调用分析工具",
  success: "工具调用成功",
  retrying: "工具调用失败，准备重试",
  retry_succeeded: "重试成功，继续上一个节点",
  failed: "工具调用失败，已安全停止",
  intercepted: "安全策略拦截，已返回上一个节点",
  insight: "正在生成带证据的 Insight",
};

function renderActivity(targetId, events = [], running = false) {
  const target = $(targetId);
  if (!target) return;
  const normalized = events.map((event) => {
    const status = event.status || (event.step === "insight_generation" ? "insight" : "success");
    const label = activityLabels[status] || status;
    const name = event.action || event.tool || event.operation || event.step || "system";
    const detail = event.error_type ? ` · ${event.error_type}` : event.output_summary ? ` · ${String(event.output_summary).slice(0, 100)}` : "";
    return `<div class="activity-row ${escapeHtml(status)}"><span class="activity-dot"></span><span><b>${escapeHtml(label)}</b><small>${escapeHtml(name)}${escapeHtml(detail)}</small></span></div>`;
  });
  if (running && !normalized.length) normalized.push(`<div class="activity-row running"><span class="activity-dot"></span><span><b>正在准备工具上下文</b><small>等待受限工具返回结果</small></span></div>`);
  target.innerHTML = `<div class="activity-heading"><span>LIVE TRACE</span><small>${running ? "执行中" : "已记录"}</small></div>${normalized.join("")}`;
  target.classList.toggle("hidden", !running && !events.length);
}

function showRunningActivity(targetId) { renderActivity(targetId, [], true); }

function startLiveActivity(targetId) {
  stopLiveActivity();
  const phases = [
    ["context", "正在整理当前文件和对话上下文", "读取已选文件的可用证据"],
    ["tool_call", "正在调用工具", "检查文件内容与可用分析能力"],
    ["tool_call", "正在调用数据分析工具", "计算摘要并检索相关证据"],
    ["insight", "正在生成 Insight", "等待模型返回结构化回答"],
  ];
  let index = 0;
  const tick = () => {
    const [status, title, detail] = phases[index % phases.length];
    renderActivity(targetId, [{ status, action: "agent", output_summary: detail, live_title: title }], true);
    const row = $(targetId)?.querySelector(".activity-row");
    if (row) row.querySelector("b").textContent = title;
    index += 1;
  };
  tick();
  liveActivityTimer = setInterval(tick, 1100);
}

function stopLiveActivity() {
  if (liveActivityTimer) clearInterval(liveActivityTimer);
  liveActivityTimer = null;
}

function appendConversationMessage(role, text, meta = "", targetId = "documentMessages") {
  const messages = $(targetId);
  if (!messages) return;
  messages.querySelector(".empty-conversation")?.remove();
  const item = document.createElement("article");
  item.className = `conversation-message ${role}`;
  item.innerHTML = `<div class="message-avatar">${role === "user" ? "我" : "AI"}</div><div class="message-body"><div class="message-meta">${role === "user" ? "You" : "Agent"}${meta ? ` · ${escapeHtml(meta)}` : ""}</div><div class="message-text">${escapeHtml(text).replaceAll("\n", "<br>")}</div></div>`;
  messages.appendChild(item);
  messages.parentElement.scrollTop = messages.parentElement.scrollHeight;
  if (targetId === "excelMessages") saveExcelSession(); else saveDocumentSession();
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
  saveExcelSession();
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
  saveExcelSession();
  $("mappingCard").classList.add("hidden");
  $("labelCard").classList.add("hidden");
  $("planCard").classList.add("hidden");
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
  const trace = state.insight_agent_trace || state.results.flatMap((item) => item.insight_agent_trace || []);
  renderActivity("excelResultActivity", trace);
  $("resultCard").classList.remove("hidden");
  $("resultCard").scrollIntoView({ behavior: "smooth" });
}

function invalidateReview() {
  $("reviewCard").classList.add("hidden");
  $("intent").classList.add("hidden");
}

async function loadReview({ scroll = true } = {}) {
  await upload();
  const prompt = excelOriginalPrompt || $("prompt").value.trim();
  const result = await api("/api/reviews", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file_id: fileId, prompt }) });
  renderReview(result);
  setExcelStage("data_confirm");
  appendConversationMessage("assistant", "数据已提取并展示，请确认表格是否准确。", "data", "excelMessages");
  if (!scroll) window.scrollTo({ top: 0, behavior: "smooth" });
}

async function saveCompletedExcelTurn(state) {
  if (!state || state.status !== "completed" || !state.run_id) return;
  if (!excelConversation) {
    const channelNames = (state.results || []).map((item) => item.channel).join(" / ") || "Excel";
    const workspace = await api("/api/workspaces", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title: `Excel analysis · ${channelNames}` }) });
    excelConversation = await api(`/api/workspaces/${workspace.workspace_id}/conversations`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "strict_excel", title: `Excel · ${channelNames}` }) });
  }
  if (excelTurn?.plan?.run_id === state.run_id) return;
  const claims = (state.results || []).flatMap((item) => (item.claims || []).map((claim) => claim.text)).slice(0, 20);
  const answer = claims.length ? claims.join("\n") : `Excel 分析已完成：${(state.results || []).map((item) => `${item.channel} ${item.quality?.row_count || 0} 条 canonical records`).join("；")}`;
  const saved = await api(`/api/conversations/${excelConversation.conversation_id}/excel-turns`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message: state.prompt || excelOriginalPrompt || "Excel 分析", run_id: state.run_id, answer, intent: state.intent || {}, plan: state.analysis_plan || {}, artifact_ids: [], summary: { channels: (state.results || []).map((item) => item.channel), status: state.status, quality: (state.results || []).map((item) => item.quality || {}) } }) });
  excelTurn = saved.turn;
  if ($("excelStatus")) $("excelStatus").textContent = "已保存本轮结果与上下文，可继续追问";
  appendConversationMessage("assistant", "Excel 分析已完成。本轮结果、洞察和工具轨迹已保存，可切换到文档洞察或稍后继续。", "completed", "excelMessages");
  saveExcelSession();
}

$("file").addEventListener("change", () => {
  fileId = null;
  excelOriginalPrompt = "";
  setExcelStage("idle");
  invalidateReview();
  $("fileLabel").textContent = $("file").files[0]?.name || "Choose .xlsx";
  $("excelActionTray").classList.toggle("hidden", !$("file").files.length);
  saveExcelSession();
  if ($("file").files[0]) showMessage("Excel 已添加，请输入分析目标后发送。", false);
});
$("prompt").addEventListener("input", () => { invalidateReview(); saveExcelSession(); });

$("inspect").addEventListener("click", async () => {
  try {
    if (!$("file").files.length) throw new Error("请先通过左下角＋添加 Excel 文件。");
    if (!$("prompt").value.trim()) throw new Error("请先输入分析目标。");
    setBusy(true);
    excelOriginalPrompt = $("prompt").value.trim();
    saveExcelSession();
    const result = await api("/api/intents", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ prompt: excelOriginalPrompt }) });
    renderIntent(result);
    appendConversationMessage("assistant", `已提取：${result.intent.analysis_targets?.map((item) => `${item.primary_sku} · ${item.channel}`).join("；")} · ${result.intent.months} 个月`, "intent", "excelMessages");
    setExcelStage("intent_confirm");
  } catch (error) { showMessage(error.message, true); } finally { setBusy(false); }
});

$("review").addEventListener("click", async () => {
  try {
    setBusy(true);
    await loadReview();
  } catch (error) { showMessage(error.message, true); } finally { setBusy(false); }
});

$("confirmIntent").addEventListener("click", async () => {
  try {
    setBusy(true);
    setExcelStage("extracting");
    appendConversationMessage("assistant", "已确认提取结果，正在提取并展示数据表格。", "extract", "excelMessages");
    await loadReview();
  } catch (error) { setExcelStage("intent_confirm"); showMessage(error.message, true); } finally { setBusy(false); }
});

$("rejectIntent").addEventListener("click", () => {
  setExcelStage("idle");
  $("intent").classList.add("hidden");
  appendConversationMessage("assistant", "流程已暂停，请回到输入框修正 SKU、渠道或时间范围。", "核对", "excelMessages");
  $("prompt").focus();
});

$("confirmData").addEventListener("click", () => $("run").click());
$("correctData").addEventListener("click", () => {
  setExcelStage("correction");
  appendConversationMessage("assistant", "请指出错误的月份、字段和正确值。提交后将重新核对数据。", "修正", "excelMessages");
});

$("run").addEventListener("click", async () => {
  try {
    setBusy(true);
    showRunningActivity("excelActivity");
    appendConversationMessage("user", $("prompt").value, $("file").files[0]?.name || "Excel", "excelMessages");
    await upload();
    const state = await api("/api/analysis-runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ file_id: fileId, prompt: $("prompt").value, human_reviewed: !$("reviewCard").classList.contains("hidden") }) });
    renderIntent({ intent: state.intent });
    if (state.status === "awaiting_plan_approval") renderPlan(state);
    else if (state.status === "awaiting_label_confirmation") renderLabels(state);
    else if (state.status === "awaiting_mapping_confirmation") renderMapping(state);
    else renderResults(state);
    await saveCompletedExcelTurn(state);
  } catch (error) { showMessage(error.message, true); } finally { setBusy(false); }
});

$("confirmPlan").addEventListener("click", async () => {
  try {
    setBusy(true);
    showRunningActivity("excelActivity");
    const state = await api(`/api/analysis-runs/${activeRun}/confirm-plan`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approved: true }) });
    $("planCard").classList.add("hidden");
    if (state.status === "awaiting_label_confirmation") renderLabels(state);
    else if (state.status === "awaiting_mapping_confirmation") renderMapping(state);
    else renderResults(state);
    await saveCompletedExcelTurn(state);
  } catch (error) { showMessage(error.message, true); } finally { setBusy(false); }
});

$("confirmLabels").addEventListener("click", async () => {
  try {
    setBusy(true);
    showRunningActivity("excelActivity");
    const state = await api(`/api/analysis-runs/${activeRun}/confirm-labels`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ approved: true }) });
    $("labelCard").classList.add("hidden");
    if (state.status === "awaiting_mapping_confirmation") renderMapping(state);
    else if (state.status === "awaiting_plan_approval") renderPlan(state);
    else renderResults(state);
    await saveCompletedExcelTurn(state);
  } catch (error) { showMessage(error.message, true); } finally { setBusy(false); }
});

$("confirm").addEventListener("click", async () => {
  try {
    setBusy(true);
    showRunningActivity("excelActivity");
    const confirmed_mappings = {};
    const missing = [];
    document.querySelectorAll(".mapping-group").forEach((group) => {
      const brands = new Set([...group.querySelectorAll("input[type=radio]")].map((input) => input.name));
      brands.forEach((name) => { if (!group.querySelector(`input[name="${name}"]:checked`)) missing.push(name); });
      confirmed_mappings[group.dataset.channel] = [...group.querySelectorAll("input:checked")].map((input) => ({ brand: input.name.split("-").slice(1).join("-"), model: decodeURIComponent(input.value) }));
    });
    if (missing.length) throw new Error(`请选择竞品型号：${missing.join(", ")}`);
    const state = await api(`/api/analysis-runs/${activeRun}/confirm`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ confirmed_mappings }) });
    if (state.status === "awaiting_plan_approval") renderPlan(state); else renderResults(state);
    await saveCompletedExcelTurn(state);
  } catch (error) { showMessage(error.message, true); } finally { setBusy(false); }
});

fetch("/api/health").then((r) => r.json()).then((health) => {
  const llm = health.llm || {};
  $("health").textContent = llm.configured ? `Agnes configured · ${llm.last_status}` : "Local fallback · add API key";
}).catch(() => { $("health").textContent = "Offline"; });

async function runDocumentTurn() {
  const files = [...$("documentFiles").files];
  if (!files.length && !documentConversation) throw new Error("请先选择 PDF、PPTX、DOCX 或文本文件。");
  const message = $("documentPrompt").value.trim();
  if (!message) throw new Error("请输入文档分析问题。");
  if (!documentConversation) {
    const types = [...new Set(files.map((file) => file.name.split(".").pop().toUpperCase()))].join(" / ");
    const title = `Document analysis · ${types}`;
    const workspace = await api("/api/workspaces", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ title }) });
    documentConversation = await api(`/api/workspaces/${workspace.workspace_id}/conversations`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ mode: "document_analysis", title }) });
    saveDocumentSession();
  }
  const artifactIds = [];
  for (const file of files) {
    const data = new FormData(); data.append("file", file);
    const artifact = await api(`/api/workspaces/${documentConversation.workspace_id}/artifacts`, { method: "POST", body: data });
    artifactIds.push(artifact.artifact_id);
  }
  appendConversationMessage("user", message, files.length ? files.map((file) => file.name).join(" · ") : "继续当前对话");
  const result = await api(`/api/conversations/${documentConversation.conversation_id}/turns`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ message, artifact_ids: artifactIds }) });
  stopLiveActivity();
  documentTurn = result.turn;
  $("documentStatus").textContent = `${artifactIds.length} 个文件 · 已保存本轮上下文与工具轨迹`;
  renderActivity("documentActivity", result.tool_trace || result.turn?.tool_events || []);
  appendConversationMessage("assistant", result.answer, `${(result.findings || []).length} findings · ${(result.tool_trace || []).length} tool events`);
  $("documentExport").disabled = false;
  saveDocumentSession();
}

$("documentSend").addEventListener("click", async () => { try { setBusy(true); startLiveActivity("documentActivity"); await runDocumentTurn(); showMessage("文档分析完成，已保存本轮轨迹与 Findings。"); } catch (error) { stopLiveActivity(); renderActivity("documentActivity", [{ status: "failed", action: "agent", error_type: error.message }]); showMessage(error.message, true); } finally { setBusy(false); } });
$("documentExport").addEventListener("click", async () => { try { const output = await api(`/api/conversations/${documentConversation.conversation_id}/outputs`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ turn_id: documentTurn?.turn_id, output_type: "markdown" }) }); window.open(output.download_url, "_blank"); } catch (error) { showMessage(error.message, true); } });
$("documentFiles").addEventListener("change", () => {
  const files = [...$("documentFiles").files];
  const types = [...new Set(files.map((file) => file.name.split(".").pop().toUpperCase()))];
  $("documentFileLabel").textContent = files.length ? `${files.length} 个文件已添加` : "添加文件";
  $("documentFileHint").textContent = files.length ? `Detected format: ${types.join(" · ")}` : "PDF · PPTX · DOCX · CSV · JSON · TXT · MD";
});

$("excelSend").addEventListener("click", () => $("run").click());
