# SKU Data Insight Agent — Work Plan

Status: Dynamic data intent layer and Agnes evidence-bounded Insight Agent implemented; business shadow evaluation remains  
Plan version: 1.1  
Last updated: 2026-09-03  
Owner: SKU Data Insight Agent project

## 1. Objective

Build an employee-facing agent that accepts the Shaver pricing workbook, understands one or more explicit Philips SKU/channel targets, dynamically recognizes workbook labels and `Key SKUs List` structures, extracts monthly ASP and Unit without silent errors, resolves channel-specific competitor mappings for the uploaded snapshot, produces evidence-bounded insights, and renders the existing validated Excel/PDF output format.

The system optimizes for correctness and auditability before automation speed. Unknown workbook structures, ambiguous mappings, missing primary metrics, and failed reconciliations must stop publication.

## 2. Scope

### In scope

- Philips SKU analysis for JD, ALI, and Offline.
- Latest 3–24 monthly periods; default 12.
- ASP as price, Unit as sales volume, Value as sales value.
- Key SKUs List mapping, including multiple models and empty mappings.
- Dynamic recognition of channel, brand, primary-SKU, competitor, and continuation-row labels from a bounded workbook structure manifest.
- Different competitor counts and competitor models for the same Philips product across JD, ALI, and Offline.
- Snapshot-aware and period-aware competitor availability when products are listed or delisted.
- One selected competitor model per competitor brand in the final report.
- Intent recognition through Agnes AI with a deterministic fallback.
- Self analysis, competitor analysis, evidence synthesis, and decision proposals.
- Internal Excel verification workbook, DuckDB, and run manifest; employee-facing PDF, JSON, and a ZIP containing only PDF plus JSON. PowerPoint is an internal rendering intermediate only and is not published.
- Chat-like local web interface for employees.

### Out of scope for the first production-ready release

- LLM-generated SQL or direct LLM access to Excel.
- Automatic final selection of ambiguous competitor mappings.
- Treating horizontally aligned Philips SKUs in different channel groups as aliases.
- Silently stitching two competitor models into one time series under one model label.
- Causal claims based only on 12 monthly ASP/Unit observations.
- Airflow, Prefect, Dagster, dbt runtime, Great Expectations, OpenLineage server, vector database, or multi-agent orchestration.
- Fully concurrent enterprise deployment. The pilot uses one local worker; concurrency infrastructure is a later scaling decision.

## 3. Non-negotiable principles

1. Extract once: Python is the only Raw Excel extraction engine.
2. One fact layer: DuckDB is the only analytical database.
3. Render only validated data: Node never reopens Raw Excel or recomputes metrics.
4. Fail closed: unsupported layout, ambiguity, missing primary data, or reconciliation failure prevents publication.
5. No silent filling: missing metrics stay missing and receive a reason; they never become zero.
6. Every number has provenance: sheet, cell, raw value, adapter version, source hash, and run ID.
7. Every explanatory claim cites observation/evidence IDs and declares an evidence level.
8. LLM output is advisory and schema-constrained; deterministic code owns numbers and state transitions.
9. The LLM may classify labels and propose a semantic plan, but only deterministic cell/range, channel-boundary, Raw Data inventory, and period-coverage checks may commit a mapping.

## 4. Target architecture

```text
Employee request + uploaded .xlsx
        |
        v
Upload snapshot / security preflight / SHA-256
        |
        v
WorkbookLayoutAdapter.detect_version()
        |
        +--> Deterministic workbook structure manifest
        |          |
        |          v
        |    Agnes label + intent recognizer
        |          |
        |          v
        |    constrained WorkbookSemanticPlan JSON
        |          |
        |          v
        |    plan validator / channel sandbox
        |
        +--> DynamicKeySkuMappingAdapter
        |
        +--> MonthlyBlockAdapter(channel config)
        |
        v
Canonical monthly records + cell provenance
        |
        v
Pydantic/Pandera/business validation gates
        |
        v
DuckDB transaction (single fact source)
        |
        +--> statistical observations
        +--> official evidence records
        +--> four-layer insight claims
        |
        v
Hashed render_payload.json
        |
        v
Excel / PPT / PDF renderer
        |
        v
Artifact reconciliation + atomic publish
```

### 4.1 Open-source design review and adoption decision

Star counts are a 2026-09-01 snapshot and are selection signals, not correctness guarantees.

| Project | Relevant capability | Decision for this agent |
| --- | --- | --- |
| [Docling](https://github.com/docling-project/docling) (~64.1k stars) | Local document parsing, XLSX support, and a normalized document representation | Borrow the normalized semantic-manifest idea. Do not add Docling to the runtime because `openpyxl` preserves the exact merged ranges, formulas, and source-cell coordinates required by this workbook. |
| [LangGraph](https://github.com/langchain-ai/langgraph) (~40.1k stars) | Explicit state graphs, durable execution, and human-in-the-loop interrupts | Borrow explicit states and review interrupts. Keep the current lightweight FastAPI/Pydantic state machine until concurrency or long-running recovery requires LangGraph. |
| [Promptfoo](https://github.com/promptfoo/promptfoo) (~22.2k stars) | Local LLM evaluation, model/prompt comparison, CI checks, and red teaming | Add a versioned label/intent regression suite and prompt-injection tests; keep deterministic pytest checks as the publication gate. |
| [Pydantic AI](https://github.com/pydantic/pydantic-ai) (~18.6k stars) | Typed tools, schema-constrained outputs, output validators, retries, and human approval | Use its typed-output and validator pattern with the existing Pydantic models. Do not introduce a second agent runtime in the first implementation. |
| [Instructor](https://github.com/567-labs/instructor) (~13.7k stars) | Focused schema-first extraction with validation feedback and retries | Preferred optional provider adapter if Agnes cannot natively guarantee strict JSON Schema. Use either native Agnes structured output or Instructor, never two retry layers. |
| [Pandera](https://github.com/unionai-oss/pandera) (~4.4k stars) | DataFrame schemas and data-quality checks | Validate the canonical mapping and monthly fact tables after deterministic execution; Pandera does not decide label meaning. |

Deliberately excluded: GraphRAG/vector search for workbook mapping, a general multi-agent framework, and fuzzy entity-resolution libraries. The authoritative relationship is structural cell evidence inside the selected channel group, not semantic similarity between model names.

### 4.2 Runtime API call sequence

1. `POST /api/files` stores an immutable upload and builds a deterministic structure manifest.
2. `recognize_semantics(manifest)` calls Agnes only when the structural fingerprint is new or the cached plan version is stale. Agnes returns `WorkbookSemanticPlan` JSON.
3. `validate_semantic_plan(plan, manifest)` verifies every cell, range, channel boundary, header role, and confidence rule. Invalid output receives at most two schema-feedback retries, then fails closed or requests label review.
4. `recognize_intent(prompt, semantic_summary)` returns `AnalysisIntentV2` with explicit `(channel, primary_sku)` targets. It cannot create a SKU that is absent from the selected channel inventory.
5. `resolve_dynamic_mapping(target, plan, snapshot)` deterministically groups the Philips block, enumerates all declared competitors, and computes monthly availability from the selected channel only.
6. `validate_mapping_snapshot(...)` auto-accepts only an exact single viable model; ambiguity, novel labels, and lifecycle splits interrupt for employee confirmation.
7. Only validated mapping snapshots and canonical monthly records enter DuckDB and the existing analysis/rendering pipeline.

The API stores the prompt/model/schema versions, validation attempts, raw structured response hash, accepted semantic plan, and source-cell evidence. It never stores a free-text LLM answer as an executable mapping.

## 5. Data contracts

### 5.1 Intent contract

Required fields: `analysis_targets`, `months`, `metrics`, `mapping_policy`, `competitor_policy`, and `output_template`.

Each `analysis_targets` item contains exactly one `channel` and one `primary_sku` expression. A single-channel compound product expression such as `YQ660/02 / PQ663/02` remains one target and preserves every member. A multi-channel request must preserve an explicit SKU expression per channel; one expression may be reused only when that exact SKU or validated Raw Data product group exists independently in every requested channel.

- Channels are limited to `JD`, `ALI`, and `OFFLINE`.
- Months are limited to 3–24.
- Metrics are limited to `ASP` and `Unit` for this report.
- Agnes receives prompt text, allowed enums, and bounded summaries only.
- Agnes never infers that two Philips SKUs in different channel columns are related.
- Output is rejected unless it validates against the versioned `AnalysisIntentV2` Pydantic schema.

### 5.2 Canonical monthly record

Primary key: `(run_id, channel, period, brand, model)`.

Required analytical fields: `period`, `period_label`, `brand`, `model`, `role`, `price`, `sales`, `sales_value`.

Required provenance fields: `source_sheet`, `source_cells`, `raw_values`, `adapter_version`, `source_sha256`, and `mapping_id`.

### 5.3 Mapping contract

Mapping states:

- `EXACT_SINGLE`
- `PRODUCT_GROUP_ALIAS`
- `MULTIPLE_CANDIDATES`
- `NO_MAPPING_DECLARED`
- `PRIMARY_SKU_NOT_FOUND_IN_CHANNEL`
- `PRIMARY_SKU_NOT_FOUND_IN_RAW_DATA`
- `RAW_MODEL_NOT_FOUND`
- `CONFIRMED_OVERRIDE`
- `LABEL_REVIEW_REQUIRED`
- `MODEL_NOT_AVAILABLE_FOR_PERIOD`
- `LIFECYCLE_SPLIT_REQUIRED`

Multiple values are parsed into explicit candidates and verified against the selected channel's Raw Data inventory. A previously approved override may be reused. Otherwise, a multiple-candidate or inferred mapping requires human confirmation.

An empty Key SKUs List cell is preserved as `NO_MAPPING_DECLARED`; inference is only offered after the employee explicitly requests candidates for the empty brand.

The number of competitor brands, candidate rows, and selected competitor series is not fixed. Each channel is resolved from its own header cells and Philips SKU block in the current workbook snapshot.

When a channel Raw Data sheet reports several Philips labels as one combined series, the adapter first resolves the complete same-channel product group, then finds the member declared as that channel's `Key SKUs List` mapping representative. The combined Raw Data label owns ASP/Unit/Value extraction; the mapping representative owns competitor selection. A representative from JD, ALI, or Offline may never be borrowed by another channel. More than one mapping representative for the same product group is ambiguous and fails closed.

### 5.4 Workbook semantic plan contract

The LLM returns labels and structure only; it never returns prices, units, SQL, or a final mapping decision.

Required fields:

- `plan_version`, `layout_fingerprint`, and `channel_groups`.
- For each group: canonical channel, channel-label cell, header row, bounded column range, primary-SKU header cell, competitor header cells with normalized brands, and the continuation-row rule.
- For every classified label: exact source cell, raw label text, semantic role, confidence, and alternative role when ambiguous.
- `unknown_labels`, `review_required`, and concise reasons.

The plan is valid only when every cited cell exists in the uploaded snapshot, group ranges do not overlap, the group stays inside one channel sandbox, and deterministic anchors support the proposed roles. Accepted plans may be cached by structural fingerprint and prompt/model version, but SKU-to-competitor values are always reparsed from each uploaded snapshot.

### 5.5 Dynamic mapping snapshot contract

Primary key: `(source_sha256, channel, primary_sku, competitor_brand, competitor_model, period)`.

Required fields: declared mapping cells, raw mapping text, grouping span, monthly Raw Data presence, requested-period coverage, mapping state, selection source, confirmation identity/time when applicable, and source workbook observation time.

If the workbook has no explicit effective dates, the system must not invent them. The declaration is valid “as observed in this uploaded snapshot”; monthly availability is calculated only from model presence in the selected channel's Raw Data blocks.

### 5.6 Insight contract

The report uses four sections:

1. Internal drivers.
2. External drivers.
3. Integrated conclusion.
4. Recommended next action with guardrails and validation method.

Each claim contains `claim_id`, `claim_type`, `text`, `observation_ids`, `external_evidence_ids`, `evidence_level`, `alternative_explanations`, and `missing_data`.

Allowed evidence levels: `OBSERVED`, `SUPPORTED`, `HYPOTHESIS`, and `NOT_ASSESSABLE`.

## 6. Workbook adapters

### WorkbookLayoutAdapter

- Confirms required sheet inventory and anchor labels.
- Detects a known layout version from a versioned structural fingerprint.
- Allows only non-breaking drift such as inserted blank rows.
- Rejects moved/renamed measures, missing brand headers, duplicate month blocks, or unknown layouts.

### WorkbookSemanticProfiler

- Builds a bounded manifest from sheet names, non-empty label cells, merged ranges, styles, row/column positions, and structural anchors.
- Excludes metric values and formula results from the LLM request.
- Uses Agnes to classify unfamiliar channel/header labels into the semantic-plan schema.
- Reuses a previously approved semantic plan only when the structural fingerprint, prompt version, and model version match.

### DynamicKeySkuMappingAdapter

- Locates JD/ALI/Offline groups independently.
- Prevents a SKU lookup, continuation scan, competitor cell, or Raw Data lookup from crossing the selected channel sandbox.
- Derives competitor-brand columns from the recognized header band instead of `brands_per_group` or fixed brand names.
- Groups one Philips SKU with its competitor rows using the explicit merged range when present; otherwise it uses blank-primary continuation rows only until the next non-empty Philips cell inside the same group.
- Parses multi-model cells using the Raw Data model inventory to avoid incorrect slash splitting.
- Parses Philips shorthand/family expressions such as `X5005/X5003/00` into candidates only when candidate members are supported by exact same-channel Raw Data inventory evidence; semantic similarity alone is insufficient.
- Resolves multi-label Philips Raw Data groups and their channel-local mapping representative without dropping product members or crossing channel boundaries.
- Preserves every non-empty competitor cell in the Philips block, so JD may yield four competitors while ALI yields three.
- Preserves raw mapping text and candidate order.
- Emits explicit mapping states and confirmation requirements.
- Builds a per-period availability matrix from the selected channel's Raw Data before ranking candidates.

### MonthlyBlockAdapter

- Uses one implementation with channel sheet configuration.
- Discovers month blocks from anchors rather than fixed row numbers.
- Extracts Philips and competitor values from declared column roles.
- Records the exact source cell for each Value, Unit, and ASP.

## 7. Validation and release gates

### File gate

- `.xlsx` only, maximum 100 MB.
- ZIP container validation, expansion-size limit, and disallowed embedded macro check.
- Immutable upload copy named by UUID and SHA-256.
- External links are not followed.

### Structural gate

- Known workbook version.
- Required sheets and anchors present exactly once per group.
- Requested channel exists.
- Selected month count is exact, unique, continuous, and ordered.

### Mapping gate

- Philips SKU is present in the selected channel.
- Every recognized label and group boundary is backed by source-cell evidence in the current upload.
- A novel/low-confidence label pauses at `LABEL_REVIEW_REQUIRED`; it is never silently added to the ontology.
- Every auto-selected competitor is an exact single declared model found in Raw Data.
- Ambiguous or inferred mappings have a persisted human confirmation.
- Missing competitor data is explicit and never zero-filled.
- Mapping candidates from another channel: zero.
- One published competitor series contains one physical model. A model change requires an explicitly labeled lifecycle split and human approval.

### Metric gate

- Philips ASP and Unit are complete for every requested month.
- Measures are numeric, finite, and non-negative.
- Composite key is unique.
- `Value` and `ASP × Unit` reconcile within the documented rounding tolerance.
- Formula cells have usable cached values; unresolved formula data stops the run.

### Persistence and artifact gate

- DuckDB writes occur in a transaction.
- Counts and aggregates are read back after commit.
- Excel values equal the validated DuckDB render query values.
- PPT/PDF tables and chart series derive from the same render payload.
- Outputs are created in a temporary run directory and moved to the published directory only after all checks pass.
- Every artifact receives a hash in `run_manifest.json`.

## 8. Analytical method

### Internal drivers

- Price and sales changes, extrema, volatility, Pearson/Spearman association, one-period lead/lag, and persistence after material price moves.
- Promotion, traffic, inventory, rating, listing, and media evidence when supplied.
- Price/Unit alone produces observations or hypotheses, never causal conclusions.

### External drivers

- Competitor price/sales movements and relative price gap.
- Platform events and competitor official announcements aligned to sales months.
- Only allow-listed official domains are accepted as official evidence.
- Every page stores title, URL, domain, publication date, retrieval date, content hash, and relevant excerpt.

### Dynamic competitor selection policy

1. Rebuild the declared candidate set from the current upload for each `(channel, primary_sku)`; never reuse another channel's set.
2. Compute candidate presence and metric completeness for every requested month.
3. Auto-select only when exactly one declared model for a brand is present with sufficient period coverage.
4. When multiple viable models remain, rank them with deterministic coverage/quality features; the LLM may explain the ranking but cannot approve it. Human confirmation remains mandatory.
5. When no single model covers the requested window, emit `LIFECYCLE_SPLIT_REQUIRED`. The employee may approve explicitly labeled time segments; the system must not splice models into one unlabeled line.
6. Store every decision as a snapshot tied to source hash, channel, requested period, semantic-plan version, and confirmation record. A later workbook may legitimately produce a different competitor count or candidate set.

### Integrated conclusion

- Combines internal and external observations.
- Lists alternative explanations and missing evidence.
- Downgrades to `NOT_ASSESSABLE` when essential driver data is absent.

### Decision recommendation

- Includes action, channel, timing, proposed range, target metric, guardrail, stop condition, and validation design.
- Uses a controlled test recommendation when causality is unproven.

## 9. Employee experience

The existing clean Philips-style web interface remains the visual baseline.

Core states:

1. Upload workbook.
2. Enter a natural-language request.
3. Review the recognized SKU, channels, months, and metrics.
4. Review per-channel SKU targets and any novel label classifications.
5. Review workbook compatibility, mapping changes versus the previous snapshot, period coverage, and quality status.
6. Confirm only ambiguous mappings or lifecycle splits; exact mappings require no extra work.
7. Run analysis with visible stage/status feedback.
8. Review completed channel packages and download Excel/PDF/DuckDB/audit JSON/ZIP.
9. On failure, show the precise blocking rule and actionable resolution; never show a generic success with partial data.

Accessibility and UX requirements:

- Keyboard-operable upload, mapping controls, and downloads.
- Clear labels and visible focus states.
- Status is communicated by text, not color alone.
- Long model names wrap without clipping.
- No raw exception trace is shown to employees.
- API key and internal paths never appear in the browser.

## 10. Implementation phases

Implementation checkpoint (2026-09-01): Phase 1 dynamic semantic manifest/plan validation, `AnalysisIntentV2`, channel-isolated dynamic mapping, period availability, fingerprinted approval cache, strict Agnes structured output, API observability, and label-review UI are implemented. The real workbook structure was recognized as ALI `B:F`, JD `H:L`, and Offline `N:R`, with independent mappings. Automated release tests cover dynamic brand counts, source-cell citations, channel-specific SKUs, strict JSON schema, and fallback observability. Production Agnes calls require a user-provided local credential source.

Insight/API checkpoint (2026-09-03): the local `api.txt` credential source is loaded in process without copying the token into artifacts or logs. Live Agnes intent calls pass. Insight generation is split into four strict agent stages: Philips internal drivers, competitor/external drivers, integrated conclusion, and decision recommendation. Deterministic local code owns numerical calculations, Top 10 ordering, brand/evidence bindings, causality downgrades, and final validation; Agnes supplies qualitative interpretation and may not calculate report numbers. A configured Agnes failure is fail-closed. In the latest live run the first three Insight stages passed; the decision-stage request was stopped by a host DNS resolution failure and no report was published. `输出规则.md` governs only the Insight taxonomy (Level 1 ASP/Qty/GMV, Level 2 elasticity/anomaly, Level 3 Philips-vs-BRAUN/PANASONIC/FLYCO, and Monthly Report Top 10); every non-Insight extraction, mapping, storage, visualization, and PDF contract remains governed by this Work Plan.

### Phase 0 — Freeze baseline

Deliverables:

- This work plan.
- Current v20 artifact inventory and visual reference.
- Existing behavior test results and known limitations.

Exit gate: work plan exists, is internally consistent, and defines acceptance criteria.

### Phase 1 — Single extraction and data contract

Deliverables:

- `data_contract.yaml`.
- Versioned channel/layout configuration.
- Workbook, Key SKU, and monthly block adapters.
- Bounded workbook structure manifest and `WorkbookSemanticPlan` schema.
- Dynamic channel/header label recognition with strict validation and fingerprinted cache.
- Cell-level provenance.
- Variable-brand, continuation-row, multi-model, empty-mapping, period-availability, and lifecycle state machine.

Exit gate: synthetic and real-compatible fixtures pass extraction tests; changed labels and brand counts are recognized without source changes; cross-channel and unsupported semantic plans fail closed; Node no longer reads Raw Excel.

### Phase 2 — Fact layer and validation

Deliverables:

- DuckDB schema and transactional repository.
- Pandera and business reconciliation checks.
- Quality result tables and run manifest.
- Deterministic render payload.

Exit gate: any injected structural, mapping, metric, formula, or reconciliation defect stops publication with the expected error code.

### Phase 3 — Agnes and evidence-bounded analysis

Deliverables:

- Agnes intent contract and fallback parser.
- `AnalysisIntentV2` with explicit per-channel SKU targets.
- Strict structured-output validation, bounded retry budget, and label-review interrupt.
- OfficialEvidenceProvider interface and allow-list registry.
- Observation and claim schemas.
- Four-layer analysis output.

Exit gate: Agnes cannot introduce an unknown SKU/model/channel, numerical fact, SQL statement, or unreferenced causal claim into a published report.

### Phase 4 — Employee web experience

Deliverables:

- Upload, intent review, data quality, mapping review, run status, and download states.
- Persisted run state with safe file access.
- Accessible, responsive UI aligned with the existing visual baseline.

Exit gate: the complete employee journey works without command-line access and every blocked state gives a specific recovery action.

### Phase 5 — Rendering and compatibility

Deliverables:

- Node renderer consumes only `render_payload.json`.
- Existing Excel and template-based report visual behavior preserved; PowerPoint remains an unpublished rendering intermediate.
- Combined one-page PDF and package ZIP.
- English chart/title requirements, combined sales bars and price line, non-overlapping warm price labels, aligned axes, and no white seam regressions.

Exit gate: visual and structural QA pass for both slides, spreadsheet, and PDF.

### Phase 6 — Verification and pilot

Deliverables:

- Unit, integration, property, golden, mutation-fixture, API, and end-to-end tests.
- S3203/08 and S1115/02/FS903 golden cases.
- JD, ALI, and Offline multi-channel run.
- X5005-family cases with different competitor counts in JD and ALI.
- Listing, delisting, and lifecycle-split mapping fixtures.
- Promptfoo label/intent regression and prompt-injection suite.
- Shadow-run checklist for 20–30 business-reviewed SKUs.

Exit gate: all automated tests pass and no acceptance invariant is violated. Employee rollout remains gated on the business shadow run.

## 11. Test matrix

### Unit tests

- Channel-name alias and per-channel SKU intent parsing.
- Semantic-plan cell/range validation.
- Month discovery and ordering.
- Mapping group boundary isolation.
- Merged and blank-primary continuation block detection.
- Variable competitor-brand column counts.
- Prefix-aware multi-model parsing.
- Empty mapping state.
- Source-cell provenance.
- Value/Unit/ASP reconciliation.
- Evidence-level enforcement.

### Property tests

- Random spacing, casing, delimiters, inserted blank rows, and model variants.
- Random channel-label wording, header order, competitor counts, and continuation lengths.
- The mapping parser never returns a model absent from both the declared candidates and Raw Data inventory.
- No adapter can return a record from another channel sheet.
- No LLM semantic plan can cite a missing cell, overlap channel sandboxes, or introduce an uncited brand/model.
- Missing values remain null and never become zero.

### Golden workbook tests

- S3203/08 mapping and 12-month records.
- S1115/02 maps to FLYCO FS903 when exactly declared.
- Multi-candidate mapping pauses for confirmation.
- Empty mapping does not infer automatically.
- Same Philips family with different JD/ALI competitor counts remains channel-specific.
- Delisted models change period coverage without rewriting historical source evidence.
- Model lifecycle changes are segmented and labeled, never silently stitched.
- Repeated runs produce the same canonical payload hash.

### End-to-end tests

- Upload through web API.
- Agnes configured and local fallback modes.
- Native strict-output and optional Instructor-adapter modes produce the same validated intent/semantic contract.
- Mapping confirmation and resume.
- Label review and lifecycle-split confirmation and resume.
- Per-channel artifact creation.
- Safe artifact download authorization.
- PPT structural test, spreadsheet inspection/render, PDF render, and visual review.

## 12. Acceptance invariants

- Philips numeric reconciliation: 100%.
- Confirmed competitor numeric reconciliation: 100%.
- Cross-channel records: 0.
- Cross-channel mapping candidates: 0.
- Cross-channel Philips SKU alias inference: 0.
- LLM-classified label without exact source-cell evidence: 0.
- Unlabeled multi-model time-series stitching: 0.
- Unconfirmed ambiguous mapping in a published report: 0.
- Missing value silently converted to zero: 0.
- Published number without source-cell provenance: 0.
- Cause claim without evidence IDs or an explicit `NOT_ASSESSABLE`: 0.
- Artifact published after any critical validation failure: 0.
- Same input/config/version producing different canonical payloads: 0.

## 13. Operational model

- Pilot: local FastAPI service bound to localhost, one analysis worker, per-run DuckDB, atomic run directories.
- Secrets: `AGNES_API_KEY` only in environment or `.env`; never committed, logged, embedded, or sent to the browser.
- Retention: uploads and generated runs have a configurable retention period; deletion is a separate explicit maintenance operation.
- Versioning: exact dependency lock, adapter version, contract version, renderer version, and prompt version stored in every run manifest.
- Scaling trigger: add a durable job queue and shared metadata database only when concurrent employee usage requires it.

## 14. Delivery package

- Source code and locked dependencies.
- `WORK_PLAN.md` and `data_contract.yaml`.
- Employee web application and launcher.
- Versioned adapters and mapping registry.
- DuckDB, Excel, PPT, PDF, JSON audit files, and ZIP package per channel.
- Automated test suite and golden fixtures.
- README with local setup, Agnes configuration, run instructions, error catalog, and pilot checklist.

## 15. Definition of done

Development is complete only when:

1. All six implementation phases pass their exit gates.
2. The automated test suite passes from a clean environment.
3. S3203/08 and S1115/02 pass the declared golden cases across required channels.
4. Final Excel/PDF artifacts are structurally and visually inspected; the temporary PowerPoint rendering intermediate is structurally checked before removal.
5. The web flow is locally verified from upload through download.
6. Known limitations are documented.
7. The project is ready for the business-owned shadow run; broad employee release is not claimed before that shadow run succeeds.

## 16. Approved output change — 2026-09-01

The input/output amendment changes presentation and analytical outputs only. Intent recognition, workbook version detection, channel adapters, mapping confirmation gates, canonical extraction, DuckDB validation, provenance, and atomic publishing remain unchanged.

- Add `Standard Fact Table` with Month, Brand, SKU, Category, Platform, ASP, Qty, GMV, compact LM/LY change summaries, metric-specific numerical LM/LY fields, mapping state, and source sheet.
- Make the first four `Competitor Mapping` fields exactly Philips SKU, Competitor Brand, Competitor SKU, and Mapping Type; retain audit fields after them.
- Add descriptive ASP/Qty/GMV movement, price-elasticity quadrant, anomaly flag, focused Philips-vs-BRAUN/PANASONIC/FLYCO comparison, official-evidence status, risk, opportunity, and decision outputs.
- Expand the evidence-bounded insight contract from four layers to a ranked Top 10 while preserving the same `internal → external → integrated → decision` logic and evidence IDs.
- Add five dashboard views: Category Overview (explicitly the mapped cohort, not full market), Brand Comparison, SKU Trend, Price Elasticity, and Competitor Tracking.
- Publish PDF, JSON, and ZIP as the only employee-facing downloads. The PDF page sequence starts with the combined chart and one consolidated `Summary & Next-step Actions` block directly below it. That block includes Philips analysis, competitor analysis, integrated summary, risk/opportunity, and the next-step decision. Monthly and competitor/category tables follow it. JSON contains the inspectable grounded analysis; ZIP contains only the PDF and JSON. Excel, DuckDB, and the run manifest remain internal validation/provenance artifacts. The internal template-rendering intermediate contains three slides and is removed before publication.
- Require every user-visible Agent insight and decision narrative to pass a Simplified-Chinese language gate. The PDF Summary uses bounded text lengths and section-specific typography; overflow is a release failure. Repeated SKU names may be rendered as `本品` in the compact PDF summary while the complete text remains available in web and JSON. Remove the non-Agent price-elasticity methodology box from the final page, and apply one shared typography/style token to mapping and scope annotations.
- Present insights in five business-readable sections with English headings in both PDF and web: `Internal Drivers`, `External Drivers`, `Online Research`, `Integrated Cause Analysis`, and `Next-step Actions`. Official-event findings belong only to `Online Research`; competitor movement belongs to `External Drivers`. Do not expose evidence-state badges such as `OBSERVED` in the employee narrative. Each employee request analyzes exactly one of JD, ALI, or Offline; channel adapters remain isolated and multi-channel batch execution is outside the interactive workflow.
- Keep LY changes nullable when the requested period does not include the prior-year month; never fabricate or silently replace missing LY values with zero.
- Mirror the approved PDF information order in the web `Analysis package`: validated Philips sales/price combination chart first, the five Agent insight sections second, and the validated Philips-plus-competitor monthly price/sales table third. Both web visuals consume the same canonical `records` and same-channel confirmed `mapping` used by the PDF renderer; no browser-side workbook extraction or metric recalculation is allowed.
- Treat one slash-connected Philips compound label as one same-channel product while rejecting requests that name two separate Philips products. Canonicalize shared suffix notation such as `X5005/X5001/X5002/X5003/00` to member-level identities for mapping comparison, so a channel-specific representative such as ALI `X5005/X5001/00` can match its Raw Data product group without creating any cross-channel alias.
- Govern Philips labels by parsed model identities rather than the complete display string: ignore series descriptors (`S9000`, `I9000`, `SERIES ####`, `PRESTIGE`), accept prefix/suffix shorthand inside one slash-connected product group, and let a suffixless Key SKUs representative match one unique suffixed Raw Data model. If that representative matches more than one same-channel Raw Data group, fail as ambiguous instead of guessing.
- Resolve multiple same-channel Raw Data labels for one parsed Philips identity against the requested month window. Select only a uniquely highest-coverage label; retain the candidate labels and per-period availability in ambiguity errors. This handles lifecycle display-name changes without merging two time series or preferring an obsolete exact string from older months.
