# SKU Data Insight Agent — Local Test Plan

## Stage 1 — Automated baseline

1. Run unit and property tests.
2. Confirm the fixture uses the production column anchors: Philips B/D/G/J and competitors M/N/O/R/U.
3. Run continuation-row, one-to-many, empty-mapping, identical-duplicate, conflicting-duplicate, and channel-boundary tests.
4. Record pass/fail counts and retain failing inputs.

## Stage 2 — Supplied-workbook adapter test

1. Copy the workbook to the run upload area so an open Excel session cannot mutate the tested snapshot.
2. Validate XLSX container, required sheets, anchors, and 30 monthly blocks for ALI/JD/Offline.
3. Preview S3203/08 and S1115/02 for each requested channel.
4. Verify Value, Unit, ASP, month labels, source cells, and duplicate-row handling.
5. Verify continuation mappings such as S1115/02 to FLYCO FS903 are visible as candidates.

## Stage 3 — API and human-review workflow

1. Start FastAPI on `127.0.0.1:8765`.
2. Check `/api/health`.
3. Upload the supplied workbook.
4. Review recognized intent and extracted-data preview.
5. Verify selecting/uploading a workbook automatically loads raw data and mapping states for the current prompt.
6. Verify report generation can start without opening the optional extraction review.
7. Confirm an ambiguous competitor mapping and resume the same run.
8. Confirm a novel/low-confidence semantic label plan and resume the same run.
9. Verify `/api/health` and run JSON expose Agnes success/fallback/failure without exposing the API key.
10. Download Excel, PDF, DuckDB, analysis JSON, and ZIP.

## Stage 4 — Artifact reconciliation

1. Compare DuckDB canonical rows with Excel `Monthly Data` and `Standard Fact Table`.
2. Verify chart series use the same values.
3. Verify the PDF contains the combined sales-bar/price-line chart, `Summary & Next-step Actions`, and subsequent tables.
4. Confirm temporary PowerPoint files are not published.

## Stage 5 — Negative and red-team tests

- Missing/renamed sheets and metric anchors.
- Conflicting duplicate competitor rows.
- Formula with missing cached value.
- Empty and cross-channel mappings.
- Prompt injection in cell text and user request.
- File/path traversal and artifact-download authorization.
- Interrupted rendering and OneDrive atomic-publish lock.

## Stage 6 — Business shadow run

Business users select 20–30 SKUs spanning JD, ALI, Offline, exact mappings, one-to-many mappings, empty mappings, complete months, and sparse competitor coverage. Each result receives a signed review outcome: accepted, data defect, mapping defect, insight defect, or visual defect.
