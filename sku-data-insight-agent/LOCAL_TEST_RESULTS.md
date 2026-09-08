# SKU Data Insight Agent — Local Test Results

Test date: 2026-09-03  
Host: Windows 11 local pilot  
Service: `http://127.0.0.1:8765`

## Automated suite

- Result: 39/39 tests passed.
- Coverage includes `AnalysisIntentV2`, explicit per-channel SKUs, compound Philips product groups, three-channel product-group governance, channel isolation, dynamic competitor counts, semantic-plan source-cell and sandbox validation, novel-label review, strict Agnes JSON Schema, fallback observability, local credential discovery, four-stage Insight orchestration, deterministic evidence ownership, missing-competitor `NOT_ASSESSABLE` handling, numeric grounding rejection, production column anchors, continuation mappings, one-to-many confirmation, empty mapping, newest-first monthly blocks, duplicate handling, provenance, DuckDB persistence, evidence-bounded claims, review API, and optional extraction review.

## Supplied workbook adapter

- Workbook accepted by adapter `shaver-pricing-v1.3-dynamic-semantics`.
- Dynamic semantic structure: ALI `B:F`, JD `H:L`, Offline `N:R`; each group has its own Philips column, competitor headers, mapping rows, and Raw Data sheet.
- JD, ALI, and Offline each expose 30 month blocks from `24-01` through `26-06`.
- S3203/08 JD preview resolves BRAUN 5603 exactly and presents FLYCO, PANASONIC, and YOOSE candidates for confirmation.
- S1115/02 JD preview preserves the two declared Raw Data candidates `FS890/FS891/FS892` and `FS903` and pauses for confirmation.
- Preview shows Value, Unit, ASP, and exact source cells.
- Real ALI compound-product check: `YQ660/02 / PQ663/02` resolves through ALI mapping representative `PQ663/02`, extracts the combined Raw Data series for all 12 months, resolves PANASONIC `ES-CM30`, and keeps YOOSE candidates pending employee confirmation. No JD or Offline mapping is reused.
- YOOSE alias safety check: selecting `MINI` matches only exact `MINI` rows, not `MINI-S` or `MINI 2.0`; identical duplicate `MINI` rows are collapsed with source-cell provenance rather than treated as conflicting products.
- The web `Extracted monthly data` verification table renders only canonical records whose role is `PH`; automatically resolved competitor records remain available to analysis but are not shown in this employee review table.

## Real end-to-end run

- Input: supplied workbook.
- Request: S3203/08, JD, latest 12 months.
- Human-selected test mappings: FLYCO FS966, PANASONIC ES-RM31, YOOSE C1 (ICE SHAVER).
- Result: completed.
- Canonical rows: 60 (12 months × Philips plus four competitor brands).
- Data-quality status: passed with zero warnings.
- Value reconciliation: all 60 rows within configured tolerance.
- Generated and verified internally: DuckDB, Excel, PDF, analysis JSON, manifest, and ZIP.
- Employee downloads expose only PDF, JSON, and ZIP; newly generated ZIP packages contain only PDF and JSON, while Excel and DuckDB remain internal validation artifacts.
- PDF insight QA now enforces Simplified-Chinese Agent narratives, renders ten compact insights in five bounded business sections with section-calibrated typography, removes the non-Agent price-elasticity methodology box, and uses a shared 15 pt style for mapping/scope annotations. The three-slide overflow check and two-page PDF render inspection passed.
- PDF and web results now group claims under `Internal Drivers`, `External Drivers`, `Online Research`, `Integrated Cause Analysis`, and `Next-step Actions`, without employee-facing evidence-state badges. PDF display text removes repeated SKU strings and applies a strict compact-summary limit; the latest visual inspection shows all five sections contained within their frames. Interactive requests reject more than one selected channel.
- Internal PowerPoint intermediate was structurally verified and removed before publication.

## Browser interaction

- Homepage, health status, intent recognition, extraction review, source-cell table, label-review contract, and mapping-confirmation card were exercised through the local API/browser workflow.
- Candidate radio buttons start unselected; the employee must make each choice.

## Web workflow corrections — 2026-09-01

- Selecting a workbook uploads and loads raw data plus mapping states automatically.
- JD, ALI, and Offline use independent SKU namespaces. Horizontally aligned `Key SKUs List` cells are not treated as aliases, and a missing SKU fails closed inside the selected channel.
- The S1115/02 ALI preview contains 12 complete Philips Value/Unit/ASP rows with D/G/J source cells.
- `Review extracted data` is optional. A direct `Generate report` action proceeds to the mandatory FLYCO mapping confirmation without an extraction-review acknowledgement.
- The web `Analysis package` now mirrors the approved PDF reading order: combined Philips sales/price chart, five Agent insight sections, and the same-channel Philips/competitor monthly price-and-sales table. The browser receives the already validated canonical records and confirmed mapping; it does not parse the workbook again.
- A real JD S3203/08 browser run produced 60 canonical rows and rendered PHILIPS plus BRAUN, FLYCO, PANASONIC, and YOOSE in the 12-month table. DOM geometry checks found all 12 warm price labels non-overlapping. At a 390 px viewport the insight sections collapsed to one column, chart/table overflow stayed inside their own horizontal scrollers, both titles fit, and the document itself had no horizontal overflow. Browser console errors: 0.
- ALI shared-suffix compound-label regression passed against the supplied workbook: the prompt `X5005/X5001/X5002/X5003/00ALI` is recognized as one ALI product group; `Key SKUs List!B27` (`X5005/X5001/00`) resolves to the Raw Data group and returns 12 Philips months plus exact BRAUN `50-M4000CS`, FLYCO `FS988`, and PANASONIC `ES-LM34` mappings. Each member label with or without `/00` resolves to that group, while two independently named Philips products are rejected at intent validation.
- Philips special-label governance now strips series descriptors without losing the product identity, expands shared suffix and omitted-prefix compound forms, and selects among same-identity lifecycle labels by unique requested-period coverage. Real-workbook checks passed for ALI/OFFLINE `SP9888/63 S9000 PRESTIGE` via the suffixless `SP9888` Key SKU, ALI/JD `SERIES 5000/9000` labels, JD `RQ890/05 / RQ892/05` against the larger Raw Data group, and the X5005 compound group. Every selected Philips series returned 12 months; unsupported Key SKUs with no Raw Data remain fail-closed.

## Agnes live integration

- The local `api.txt` credential is discovered and loaded only into process memory; it is not copied into artifacts or audit logs.
- Live intent generation has passed strict schema and channel/SKU normalization.
- The governed Insight Agent runs four API stages. The latest real-workbook run passed internal, external, and integrated validation. The final decision request encountered a host DNS resolution failure, so fail-closed behavior correctly prevented report publication.
- Exact metrics remain deterministic; API prose is qualitative and must cite locally assigned evidence IDs.

## Remaining business gate

Production readiness still requires a stable network retest completing all four live Insight stages, followed by the planned 20–30 SKU business shadow run and human adjudication of mapping, insight, and report quality.
