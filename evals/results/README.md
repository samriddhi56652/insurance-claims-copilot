# Eval results

`python evals/run_eval.py` writes three files here per run:

| file | contents |
|---|---|
| `raw-<ts>.jsonl` | full draft + retrieved chunks + tool trace + latency, per claim |
| `scored-<ts>.jsonl` | every metric, per claim |
| `summary-<ts>.md` | the aggregate table + per-claim table + judge reasoning |

Run artefacts are gitignored. Two summaries are kept as a before/after:

- **`summary-20260903-095739.md`** — early baseline (10 claims). Groundedness **0.8 / 2**.
- **`summary-20260903-180818.md`** — after the Phase 1 fixes (intake gate, fake-tool
  removal, no-invented-numbers rule, decision tree). Groundedness **1.71 / 2**,
  2 claims now refused before the model runs.

The narrative for every change between them is in
[`../../docs/ITERATION_LOG.md`](../../docs/ITERATION_LOG.md).
