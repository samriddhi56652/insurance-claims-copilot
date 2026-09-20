# Why eval scores move between runs — and what to do about it

Running the same evaluation twice on the same code gave two different
groundedness scores: **1.42, then 1.67 out of 2**. This note is what I found when
I asked why, what I measured in this project, and what it changes about how the
numbers should be read.

Think of the eval as an exam. A student (the drafting model) never writes the
same answer twice, a marker (the judge) is not perfectly consistent, and there
are only 12 questions. Each of those three adds noise.

---

## 1. What the research says

I read the abstracts of the papers below (and the source post for the first
item). Where I quote, the words are copied from the abstract.

**The drafting model is not repeatable, even when set to be deterministic.**
- Atil et al., [*Non-Determinism of "Deterministic" LLM Settings*](https://arxiv.org/abs/2408.04667)
  (2024): five models set to be deterministic, eight tasks, ten runs each.
  *"none of the LLMs consistently delivers repeatable accuracy across all tasks,
  much less identical output strings."* Accuracy varied by up to 15% between runs.
- Thinking Machines,
  [*Defeating Nondeterminism in LLM Inference*](https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/)
  (2025, a blog post, not a paper): 1,000 identical requests at temperature 0 gave
  80 different completions. Their explanation is that the servers' calculation
  kernels are not batch-invariant, so results shift with server load.
- Groq's own API documentation says of its `seed` option: *"Determinism is not
  guaranteed."* ([API reference](https://console.groq.com/docs/api-reference)).
  I found no source explaining Groq's specific cause; the batch-invariance
  explanation is about GPU servers, so treat it as a strong hint here, not proof.

**The judge is noisy too.**
- Haldar & Hockenmaier, [*Rating Roulette: Self-Inconsistency in LLM-As-A-Judge Frameworks*](https://arxiv.org/abs/2510.27106)
  (2025): *"LLM judges have low intra-rater reliability in their assigned scores
  across different runs. This variance makes their ratings inconsistent, almost
  arbitrary in the worst case."*
- Related: Zheng et al., [*Judging LLM-as-a-Judge*](https://arxiv.org/abs/2306.05685)
  (2023) find position, verbosity and self-enhancement biases; Wang et al.,
  [*Large Language Models are not Fair Evaluators*](https://arxiv.org/abs/2305.17926)
  (2023) show that reordering two answers alone let a weaker model "win" 66 of 80
  comparisons. Those are pairwise setups, so they only loosely apply here.

**Small test sets cannot resolve small differences.**
- Miller, [*Adding Error Bars to Evals*](https://arxiv.org/abs/2411.00640) (2024):
  treat an eval as a statistical experiment; give standard errors, compare two
  systems on the same questions, and plan the sample size.
- Card et al., [*With Little Power Comes Great Responsibility*](https://arxiv.org/abs/2010.06595)
  (2020): many NLP test sets are too small to detect the differences people
  report.

**Prompt wording matters a lot, but that is a separate issue.** Sclar et al.
([2023](https://arxiv.org/abs/2310.11324)) found accuracy swings of up to 76
points from formatting alone, and Liu et al.
([2023](https://arxiv.org/abs/2307.03172)) found models use information in the
middle of long prompts less well. Both suggest long, rule-heavy prompts are
fragile; neither explains run-to-run noise.

---

## 2. What I measured here

All numbers below come from files in `evals/results/`; the commands to reproduce
them are at the end. The test set is the 14 labelled claims; the judge scores 12
of them (two are stopped by the intake check before reaching the model).

### 2.1 Mean and spread, before and after the retrieval fix

Groundedness (out of 2), one number per run:

| | runs | mean | spread |
|---|---|---|---|
| before the retrieval fix | 2 | 1.54 | SD 0.18, range 1.42–1.67 |
| after the retrieval fix | 3 | 1.72 | SD 0.05, range 1.67–1.75 |

The gap is +0.18, but its standard error is 0.13 — **not conclusive**. Coverage
(1.79 → 1.83) and safety (1.00 → 0.97) show no real change. See ITERATION_LOG §4.1
for the fix.

### 2.2 The same claims, before and after

Comparing each claim with itself removes the differences in claim difficulty:
**7 claims scored higher, 1 lower, 4 the same** (mean +0.18, standard error 0.095).
The biggest gains are on claims whose retrieval improved — for example
`multi-coverage-01` (+1.0) and `comp-theft-01` (+0.33). That fits the retrieval
explanation, but it is a handful of claims: consistent with the idea, not proof.

### 2.3 How much is the judge?

I took the 12 saved drafts from one run and asked the judge to score each one
five more times. The drafts do not change, so any difference is the judge alone.

- On **9 of 12 drafts** the judge gave the same groundedness score all five times;
  on **3 of 12** (`liability-01`, `liability-02`, `multi-coverage-01`) it changed.
  Coverage changed on 2 drafts; safety on none.
- Across the three runs on the same code, the judge alone is about **28%** of the
  run-to-run variance in groundedness; changes in the drafts themselves account for
  **at most about 72%**.
- This is a floor for the judge, not a fair estimate: the five re-scores ran back
  to back, and on 2 of 12 drafts the judge's original verdict differed from the
  majority of its re-scores (`comp-hail-01` was first scored 0, then 1 five times).
  Noise between separate occasions is probably larger than noise within one burst.
- Separately, in those same three runs **7 of the 12 claims** got a different
  groundedness score at least once. The claims that never moved were the simple
  ones (three collision claims and the glass claim) plus `multi-coverage-01`.

### 2.4 Speed

Median time for the draft request was **2.6–3.3 seconds** across 12 runs of the
14-claim set (`latency_p50_s` in each summary), which is where "about 3 seconds"
comes from.

---

## 3. What this changes

1. **Report a mean with a spread over several runs, not one run.** A single run is
   an anecdote. `evals/analyze_runs.py` does the arithmetic.
2. **Compare before and after claim by claim on the same claims**, not just the
   overall average.
3. **Do not read a single claim flipping as an effect of the change you just made.**
   With this much per-claim movement, several apparent "regressions" from prompt
   experiments were probably noise (I saw this while trying prompt rules and
   temperature 0, all of which were reverted; those runs' files are not kept here).
4. **Keep the judge in mind as a noise source.** Re-scoring saved drafts
   (`evals/judge_stability.py`) is cheap and separates it from the drafts.
5. **More claims, especially borderline ones**, is the real fix for the small
   sample. It is not done.

## 4. Limits of these measurements

- Two runs before, three after: the standard errors are themselves rough.
- The judge test used one run's drafts, and its five repeats were back to back.
- The runs being compared differ only in the retrieval search, but they were made
  on different days, so anything else that drifted (the service, server load) is
  mixed in.
- I read the papers' abstracts, not every paper in full.

## 5. Reproduce

```bash
# mean and spread, and the claim-by-claim table
python evals/analyze_runs.py --before 20260911-155544 20260911-161501 \
    --after 20260915-174658 20260915-180437 20260915-230008

# re-score saved drafts (needs GROQ_API_KEY; 12 claims x 5 = 60 judge calls)
python evals/judge_stability.py --raw 20260915-230008 --repeats 5 \
    --across-runs 20260915-174658 20260915-180437 20260915-230008
```

Re-running the second command will not give exactly the same numbers. The saved
result is in `evals/results/judge-stability-20260915-230008.json`.
