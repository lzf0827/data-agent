# Data Agent Benchmark

This benchmark evaluates the SKU Data Insight Agent using a DeepAnalyze-style
task protocol while retaining business fail-closed gates.

It evaluates five task families:

1. `data_preparation`: intent, workbook structure, extraction and provenance;
2. `data_analysis`: quality checks, metrics and deterministic observations;
3. `data_insight`: grounded observations and evidence status;
4. `report_generation`: required report contract and artifact checks;
5. `open_ended_research`: a manifest format for future human/LLM judging.

The local runner is deterministic and has no network or LLM dependency. It
generates valid and adversarial workbook variants from the existing fixture,
keeps an oracle for every case, runs the public deterministic contracts, and
writes JSONL traces plus a Markdown scorecard.

## Run

```powershell
.\.venv\Scripts\python.exe benchmarks\run_benchmark.py --cases 60 --output .work\benchmark\latest
```

The runner reports:

- task success and completion;
- intent, plan, extraction, provenance and safety accuracy;
- interaction success, retries and invalid-step rate;
- report contract score when an analysis package is supplied;
- per-family and per-severity results.

Use `--report-package PATH` to score a generated `analysis.json` package. The
report judge is deliberately rule-based locally; an external LLM judge may be
attached later through the versioned JSONL interface, but its score must never
override hard safety failures.

## Dataset policy

The benchmark is split by task seed and mutation type. Synthetic cases are for
regression and coverage. Release claims must additionally include a frozen,
unseen real-workbook holdout and 20–30 business shadow SKU reviews. Do not put
credentials, raw customer workbooks or generated artifacts into Git.
