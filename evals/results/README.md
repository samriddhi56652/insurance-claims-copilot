# Eval results

`python evals/run_eval.py` writes three files here per run:

| file | contents |
|---|---|
| `raw-<ts>.jsonl` | full draft + retrieved chunks + tool trace + latency, per claim |
| `scored-<ts>.jsonl` | every metric, per claim |
| `summary-<ts>.md` | the aggregate table + per-claim table + judge reasoning |

Run artefacts are gitignored. Three summaries are kept, in order, so the
before/after is reproducible from the files:

| file | what it is | groundedness (of 2) |
|---|---|---|
| `summary-20260903-095739.md` | the very first run — **but the judge itself had a bug**: it wasn't shown the original claim, so it flagged the claimant's own facts (policy number, report number) as fabrications. See ITERATION_LOG §1.3. | 0.8 *(measurement artifact)* |
| `summary-20260903-100140.md` | **the honest baseline** — same claims, judge fixed, before any model changes | **1.11** |
| `summary-20260903-180818.md` | after the Phase 1 fixes (intake gate, fake-tool removal, no-invented-numbers rule, decision tree) — 2 claims now refused before the model runs | **1.71** |

So the real headline is **1.11 → 1.71**, both measured with the corrected judge.
The 0.8 file is kept only to show the judge bug was caught and not counted as
progress.

The narrative for every change between these runs is in
[`../../docs/ITERATION_LOG.md`](../../docs/ITERATION_LOG.md).
