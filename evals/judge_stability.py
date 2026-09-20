"""How steady is the judge on its own? Re-score saved drafts several times.

    python evals/judge_stability.py --raw 20260915-230008
    python evals/judge_stability.py --raw 20260915-230008 --repeats 5 \\
        --across-runs 20260915-174658 20260915-180437 20260915-230008
    python evals/judge_stability.py --raw 20260915-230008 --only comp-hail-01 --repeats 3

Takes the drafts saved in results/raw-<tag>.jsonl and asks the judge to score each
one again, N times, with the exact same code and inputs as run_eval.py. The draft
is fixed, so any change in the score is noise from the judge alone.

--across-runs compares that with how much the same claims vary across real runs
(where the draft changes too), to estimate how much of the run-to-run swing is the
judge and how much is the drafts.

Caveat: the repeats run back to back, so they probably understate the judge's noise
(see docs/EVAL_NOISE.md). Treat the judge's share as a floor.

Needs GROQ_API_KEY (reads .env). Costs len(claims) x repeats judge calls.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import statistics as st
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:
    pass

from evals import judge  # noqa: E402

DATASET = HERE / "dataset" / "claims.jsonl"
RESULTS_DIR = HERE / "results"


def load_claims() -> dict[str, dict]:
    return {
        c["id"]: c
        for c in (json.loads(x) for x in DATASET.read_text(encoding="utf-8").splitlines() if x.strip())
    }


def load_drafts(tag: str, only: set[str] | None) -> list[dict]:
    path = RESULTS_DIR / f"raw-{tag}.jsonl"
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = [r for r in rows if r.get("ok") and not r.get("gated") and r.get("draft")]
    return [r for r in rows if not only or r["id"] in only]


def rescore(tag: str, repeats: int, only: set[str] | None) -> dict[str, list[list]]:
    claims = load_claims()
    scores: dict[str, list[list]] = {}
    for row in load_drafts(tag, only):
        claim = claims[row["id"]]
        runs = []
        for _ in range(repeats):
            verdict = judge.judge_draft(
                draft=row["draft"],
                claim_text=f"{claim['subject']}\n{claim['description']}",
                expected_coverage=claim["gold"].get("coverage", []),
                knowledge_hits=row["knowledge_hits"],
                tool_calls=row["tool_calls"],
                claim_notes=claim["gold"].get("notes", ""),
            )
            runs.append([
                verdict.get("groundedness"),
                verdict.get("coverage_correct"),
                verdict.get("safety_ok"),
                verdict.get("reason", "")[:120],
            ])
        scores[row["id"]] = runs
        print(f"  {row['id']:20} groundedness {[r[0] for r in runs]}  "
              f"coverage {[r[1] for r in runs]}  safety {[r[2] for r in runs]}", flush=True)
    return scores


def scored_groundedness(tag: str) -> dict[str, int]:
    out: dict[str, int] = {}
    path = RESULTS_DIR / f"scored-{tag}.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        judged = row.get("judge")
        if judged and "groundedness" in judged:
            out[row["id"]] = judged["groundedness"]
    return out


def summarise(scores: dict[str, list[list]], across_runs: list[str]) -> None:
    n = len(scores)
    same_g = sum(len({r[0] for r in runs}) == 1 for runs in scores.values())
    changed_c = sum(len({r[1] for r in runs}) > 1 for runs in scores.values())
    changed_s = sum(len({r[2] for r in runs}) > 1 for runs in scores.values())
    print(f"\nSame groundedness on every re-score of one fixed draft: {same_g}/{n}")
    print(f"Groundedness changed on {n - same_g}/{n} drafts; "
          f"coverage changed on {changed_c}/{n}; safety changed on {changed_s}/{n}")

    if across_runs:
        runs = [scored_groundedness(t) for t in across_runs]
        ids = [c for c in scores if all(c in r for r in runs)]
        judge_var = st.mean(st.pvariance([r[0] for r in scores[c]]) for c in ids)
        total_var = st.mean(st.pvariance([r[c] for r in runs]) for c in ids)
        print(f"\nMean per-claim variance of groundedness:")
        print(f"  judge only (fixed draft, re-scored):        {judge_var:.3f}")
        print(f"  across {len(runs)} real runs (draft + judge both vary): {total_var:.3f}")
        if total_var > 0:
            share = 100 * judge_var / total_var
            print(f"  -> the judge alone is about {share:.0f}% of the run-to-run variance "
                  f"(a floor); the drafts changing account for at most ~{100 - share:.0f}%")
        print("  Only use runs from the same code version for --across-runs.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--raw", required=True, metavar="TAG", help="results/raw-<TAG>.jsonl")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--only", help="comma-separated claim ids")
    parser.add_argument("--across-runs", nargs="+", default=[], metavar="TAG")
    parser.add_argument("--out", type=pathlib.Path,
                        help="where to save (default results/judge-stability-<TAG>.json)")
    args = parser.parse_args()

    only = set(args.only.split(",")) if args.only else None
    print(f"Re-scoring drafts from raw-{args.raw}.jsonl x{args.repeats} with {judge.JUDGE_MODEL}\n")
    scores = rescore(args.raw, args.repeats, only)
    summarise(scores, args.across_runs)

    out = args.out or RESULTS_DIR / f"judge-stability-{args.raw}.json"
    out.write_text(json.dumps({
        "meta": {
            "source_raw": f"raw-{args.raw}.jsonl",
            "repeats": args.repeats,
            "judge_model": judge.JUDGE_MODEL,
            "date": dt.date.today().isoformat(),
            "columns": ["groundedness", "coverage_correct", "safety_ok", "reason"],
        },
        "scores": scores,
    }, indent=1), encoding="utf-8")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
