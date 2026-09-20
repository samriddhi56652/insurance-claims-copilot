"""Compare eval runs with a spread instead of a single number.

    python evals/analyze_runs.py --before 20260911-155544 20260911-161501 \\
                                 --after  20260915-174658 20260915-180437 20260915-230008

Each tag is the timestamp in a results file name (scored-<tag>.jsonl). Prints:
  1. the mean, standard deviation, range and standard error of each judge score
     across the runs in each group, and the difference between groups;
  2. a claim-by-claim before/after table on the same claims.

Why: one run is an anecdote. The judge and the drafting model both vary from
run to run (see docs/EVAL_NOISE.md), so a before/after gap is only worth
believing if it is large compared with that spread.
"""

from __future__ import annotations

import argparse
import json
import math
import pathlib
import statistics as st
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

RESULTS_DIR = pathlib.Path(__file__).resolve().parent / "results"
METRICS = (
    ("groundedness", "groundedness (of 2)"),
    ("coverage_correct", "coverage (of 2)"),
    ("safety_ok", "safety (of 1)"),
)


def load_run(tag: str) -> dict[str, dict]:
    """claim id -> judge scores, for the claims the judge actually scored."""
    path = RESULTS_DIR / f"scored-{tag}.jsonl"
    rows: dict[str, dict] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        judge = row.get("judge")
        if judge and "groundedness" in judge:
            rows[row["id"]] = judge
    return rows


def run_means(runs: list[dict[str, dict]], key: str) -> list[float]:
    return [sum(j[key] for j in run.values()) / len(run) for run in runs]


def spread(values: list[float]) -> tuple[float, float, float]:
    """mean, sample standard deviation, standard error (nan when n < 2)."""
    mean = st.mean(values)
    if len(values) < 2:
        return mean, float("nan"), float("nan")
    sd = st.stdev(values)
    return mean, sd, sd / math.sqrt(len(values))


def report(before_tags: list[str], after_tags: list[str]) -> None:
    before = [load_run(t) for t in before_tags]
    after = [load_run(t) for t in after_tags]

    print("1. Run-level mean and spread (each run = the mean over its scored claims)\n")
    for key, label in METRICS:
        b_vals, a_vals = run_means(before, key), run_means(after, key)
        b_mean, b_sd, b_se = spread(b_vals)
        a_mean, a_sd, a_se = spread(a_vals)
        print(f"  {label}")
        print(f"    before (n={len(b_vals)}): mean {b_mean:.3f}  SD {b_sd:.3f}  "
              f"range {min(b_vals):.3f}-{max(b_vals):.3f}")
        print(f"    after  (n={len(a_vals)}): mean {a_mean:.3f}  SD {a_sd:.3f}  "
              f"range {min(a_vals):.3f}-{max(a_vals):.3f}")
        se_diff = math.sqrt(
            (0 if math.isnan(b_se) else b_se ** 2) + (0 if math.isnan(a_se) else a_se ** 2)
        )
        ratio = f"{abs(a_mean - b_mean) / se_diff:.1f}x" if se_diff else "n/a"
        print(f"    difference (after - before): {a_mean - b_mean:+.3f}  "
              f"standard error of the difference {se_diff:.3f}  (gap is {ratio} its error)\n")

    print("2. Claim by claim, groundedness (mean of the runs in each group)\n")
    shared = [c for c in before[0] if all(c in r for r in before + after)]
    print(f"  {'claim':20} {'before runs':12} {'before':>6}   {'after runs':12} {'after':>6}   {'diff':>6}")
    diffs = []
    for cid in shared:
        b = [r[cid]["groundedness"] for r in before]
        a = [r[cid]["groundedness"] for r in after]
        diff = st.mean(a) - st.mean(b)
        diffs.append(diff)
        print(f"  {cid:20} {''.join(map(str, b)):12} {st.mean(b):6.2f}   "
              f"{''.join(map(str, a)):12} {st.mean(a):6.2f}   {diff:+6.2f}")
    better = sum(d > 0.001 for d in diffs)
    worse = sum(d < -0.001 for d in diffs)
    print(f"\n  better: {better}   worse: {worse}   same: {len(diffs) - better - worse}")
    if len(diffs) > 1:
        print(f"  mean per-claim difference {st.mean(diffs):+.3f}  "
              f"standard error {st.stdev(diffs) / math.sqrt(len(diffs)):.3f}")
    print("\n  Small groups: treat a gap smaller than about 2x its standard error as "
          "unproven.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--before", nargs="+", required=True, metavar="TAG")
    parser.add_argument("--after", nargs="+", required=True, metavar="TAG")
    args = parser.parse_args()
    report(args.before, args.after)


if __name__ == "__main__":
    main()
