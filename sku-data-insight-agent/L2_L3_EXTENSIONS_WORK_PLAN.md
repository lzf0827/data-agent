# SKU Data Insight Agent — L2→L3 Extensions Work Plan

Status: Design approved; incremental enhancement planned  
Plan version: 1.0  
Last updated: 2026-09-07  
Owner: SKU Data Insight Agent project

## 1. Objective

Elevate the agent from L2 (procedural executor, stateless per-run) toward L3 (conditional autonomy with human oversight) under the [awesome-data-agents](https://github.com/hkustdial/awesome-data-agents) autonomy taxonomy. The upgrade adds **session memory**, **cross-run experience reuse**, and **automatic context carry-over** while preserving the existing fail-closed guarantees: unconfirmed structures, ambiguous mappings, and price decisions always stop for human confirmation.

## 2. Scope

### In scope

- **Session memory**: persist each run's intent, confirmed mappings, reviewed labels, conclusions, and decisions; enable multi-turn follow-up on the same SKU without forcing the employee to restate prior context.
- **Experience reuse**: cross-run capture of human-approved semantic plans and confirmed mappings; reuse them on identical structural fingerprints to reduce repeated confirmation.
- **Context carry-over**: on upload, compare the current structural fingerprint against the run history and inject relevant prior context into intent insight generation where applicable.
- **Moderate orchestration**: route a run with known structure/mapping straight to analysis; only unknown or ambiguous structures pause at a review gate.

### Out of scope for this extension

- Full autonomous decision-making without human confirmation.
- Multi-agent framework migration (e.g., LangGraph) or a second agent runtime.
- Vector/graph memory for workbook mapping semantics; structural fingerprinted reuse remains the authoritative mechanism.
- Concurrent multi-worker scaling; a durable job queue remains a later decision.

## 3. Non-negotiable principles (unchanged)

1. Extract once: Python is the only Raw Excel extraction engine.
2. One fact layer: DuckDB remains the single analytical database.
3. Render only validated data: Node never reopens Raw Excel or recomputes metrics.
4. Fail closed: unsupported layout, ambiguity, missing primary data, or reconciliation failure prevents publication.
5. No silent filling: missing metrics stay missing with a reason.
6. Every number keeps provenance: sheet, cell, raw value, adapter version, source hash, run ID.
7. Every explanatory claim cites observation/evidence IDs and declares an evidence level.
8. **Memory/experience never silently overrides a fresh snapshot.** Reused plans and mappings must be validated against the current upload before being applied.
9. LLM output remains advisory and schema-constrained; deterministic code owns numbers and state transitions.

## 4. Architecture additions

Three new modules, embedded as thin layers over the existing pipeline. No change to `pipeline.run`, `adapters`, `semantic`, or the renderer's public contracts.

```text
Existing:  Raw XLSX → manifest → semantic plan → extract → validate → DuckDB → render → publish
                         (fingerprinted layout fingerprint, e.g. SHA-256 of structure)

New:       + SessionStore  (memory_store.py)   → conversation/run history
           + ExperienceStore (experience_store.py) → approved-plan & confirmed-mapping reuse
           + ContextProvider (context.py)        → inject prior context into insight generation
```

### 4.1 `memory_store.py` — SessionStore

Persist run/session records under `.work/sessions/` (one JSON per run, then DuckDB for cross-run facts).

Record schema (`SessionRecord`):

| Field | Purpose |
| --- | --- |
| `run_id` | stable run identity |
| `session_id` | optional grouping for multi-turn conversation |
| `prompt` | original natural-language request |
| `intent` | parsed `AnalysisIntent` |
| `semantic_fingerprint` | layout fingerprint of the source workbook |
| `confirmed_mappings` | human-approved mapping decisions |
| `reviewed_labels` | approved novel labels |
| `result` | channel results (claims, decision) |
| `created_at` | timestamp |

### 4.2 `experience_store.py` — ExperienceStore

Build on the existing `SemanticPlanCache`:

- Cache approved `WorkbookSemanticPlan` by `(layout_fingerprint, prompt_version, recognizer_model)`.
- Add a `confirmed_mapping` cache keyed by `(semantic_fingerprint, channel, primary_sku, brand)` so an already-approved model mapping is reused when the exact structure returns.
- Reuse only after re-validating against the current manifest (fingerprint equality + deterministic bounds check). Cache miss or validation failure falls through to normal review.

### 4.3 `context.py` — ContextProvider

- Reads recent `SessionRecord`s for the same SKU / fingerprint.
- Builds a bounded context payload (never raw values, only summaries + prior approved decisions) injected into `synthesize_insights` as grounded prior context.
- Enforces a hard size cap and strips numbers not present in current-run observations (reusing the deterministic number-grounding rule, so prior conclusions cannot inject ungrounded metrics).

## 5. Integration points

- `app.py`: on `/api/analysis-runs` start, persist a `SessionRecord`; on follow-up (`session_id` provided), have `ContextProvider` load prior context.
- `pipeline.py`: `InsightPipeline.prepare` first consults `ExperienceStore` for a validated approved plan/mapping; `run` writes the session record and passes prior context to `synthesize_insights`.
- `semantic.py`: `SemanticPlanCache` is extended (or wrapped) by `ExperienceStore`; no change to its public read/write semantics.

## 6. Fail-closed behavior for reused context

- Reused plan/mapping must match the current upload's fingerprint and pass deterministic bounds.
- Any reuse that references a cell/model absent from the current snapshot is discarded and triggers normal review.
- Prior-context injection that would introduce an ungrounded number or stale brand is rejected by the existing deterministic validation.
- Memory never bypasses `LABEL_REVIEW_REQUIRED` or `MAPPING_CONFIRMATION_REQUIRED`.

## 7. Tests

- SessionStore write/read round-trip; missing run returns None.
- ExperienceStore reuse only on exact fingerprint match; fingerprint drift invalidates cache.
- Confirmed-mapping reuse: same structure reuses mapping; changed structure forces confirmation.
- ContextProvider: bounded context, no ungrounded numbers injected, stale brand filtered.
- Integration: two sequential runs on identical workbook — second skips confirmation.
- Regression: existing pytest suite still passes unchanged.

## 8. Definition of done

1. Three modules added and wired into `app.py` / `pipeline.py` without changing public render contracts.
2. Reused plans/mappings are validated against the current snapshot before application.
3. Fail-closed invariant: no unconfirmed ambiguous mapping or novel label enters a published report.
4. New tests pass; full `python -m pytest -q` passes.
5. This work plan is committed alongside the code.