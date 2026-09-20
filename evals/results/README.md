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

## Phase 4 files (September 11-15)

These back the numbers in [`../../docs/EVAL_NOISE.md`](../../docs/EVAL_NOISE.md) and
ITERATION_LOG §4. All are the 14-claim test set (12 scored by the judge). The tag
is the timestamp in the file name.

| tag | what it is | groundedness (of 2) | retrieval recall |
|---|---|---|---|
| `20260911-155544` | before the retrieval fix | 1.417 | 0.847 |
| `20260911-161501` | before the retrieval fix (same code, second run) | 1.667 | 0.847 |
| `20260915-174658` | after the retrieval fix | 1.667 | 1.0 |
| `20260915-180437` | after the retrieval fix | 1.75 | 1.0 |
| `20260915-230008` | after the retrieval fix | 1.75 | 1.0 |

For each tag the `summary-`, `scored-` and `raw-` files are kept where noted in
`.gitignore` (`scored-` for all five so `evals/analyze_runs.py` runs; `raw-` for the
first and last, which hold the retrieved chunks and drafts).

- `raw-20260911-155544.jsonl` shows the retrieval gap directly: for
  `multi-coverage-01` the four chunks are two from the required-documents file and
  two from the coverage guidelines, with none from the intake checklist the claim
  also needs.
- `judge-stability-20260915-230008.json` is the judge re-scoring test: the 12 drafts
  in `raw-20260915-230008.jsonl`, each scored five more times. It was produced with
  a throwaway script before `evals/judge_stability.py` existed, using the same
  procedure; re-running will not reproduce these exact numbers.

Other runs from those days (prompt-rule and temperature experiments) are not kept.
