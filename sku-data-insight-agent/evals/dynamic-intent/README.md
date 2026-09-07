# Dynamic intent evaluation

This suite checks the public `AnalysisIntentV2` contract through the local API. It covers one-channel intent, explicit per-channel SKUs, prompt-injection text, and channel-isolated SKU identity.

Run the web service first, then run:

```powershell
npx promptfoo@latest eval -c evals/dynamic-intent/promptfooconfig.yaml
```

The suite is supplemental. The Python tests remain the release gate because they also validate workbook cells, channel sandboxes, mapping availability, and fail-closed behavior without network access.
