"""Run the claims-copilot evaluation set through the running backend.

    python evals/run_eval.py                 # run all, judge on, clean up test data
    python evals/run_eval.py --no-judge      # deterministic metrics only
    python evals/run_eval.py --keep          # leave the eval tickets in the DB
    python evals/run_eval.py --api http://localhost:8000
    python evals/run_eval.py --only fraud-01,glass-01

Needs the backend up (docker compose up -d) and GROQ_API_KEY in the environment
for the judge. Reads the dev venv's .env automatically if present.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import pathlib
import sqlite3
import statistics
import sys
import time

import requests

# Windows consoles default to cp1252; make our output UTF-8 safe.
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

from evals import metrics  # noqa: E402

DATASET = HERE / "dataset" / "claims.jsonl"
RESULTS_DIR = HERE / "results"
DB_PATH = ROOT / "data" / "support.db"
EVAL_EMAIL_DOMAIN = "eval.example"


def load_claims(only: set[str] | None) -> list[dict]:
    rows = [json.loads(line) for line in DATASET.read_text(encoding="utf-8").splitlines() if line.strip()]
    return [r for r in rows if not only or r["id"] in only]


def run_one(api: str, claim: dict) -> dict:
    email = f"{claim['id']}@{EVAL_EMAIL_DOMAIN}"
    payload = {
        "customer_email": email,
        "customer_name": f"Eval {claim['id']}",
        "subject": claim["subject"],
        "description": claim["description"],
        "priority": claim.get("priority", "medium"),
        "auto_generate": False,
    }
    t0 = time.perf_counter()
    tk = requests.post(f"{api}/api/tickets", json=payload, timeout=30)
    tk.raise_for_status()
    ticket_id = tk.json()["id"]

    # The app has no backoff on Groq 429s (it surfaces them as a 500 - see
    # docs/DESIGN_GAPS.md). Retry here so a rate limit doesn't abort the run.
    g0 = time.perf_counter()
    for attempt in range(4):
        gd = requests.post(f"{api}/api/tickets/{ticket_id}/generate-draft", timeout=180)
        if gd.status_code != 500 or "429" not in gd.text:
            break
        wait = 8 * (attempt + 1)
        print(f"[429 backoff {wait}s] ", end="", flush=True)
        time.sleep(wait)
    latency = time.perf_counter() - g0
    total = time.perf_counter() - t0

    if gd.status_code != 200:
        return {"id": claim["id"], "ok": False, "http": gd.status_code,
                "error": gd.text[:300], "latency_s": round(latency, 2)}

    draft = gd.json()["draft"]
    ctx = draft.get("context_used") or {}
    return {
        "id": claim["id"],
        "ok": True,
        "ticket_id": ticket_id,
        "latency_s": round(latency, 2),
        "total_s": round(total, 2),
        "draft": draft["content"],
        "gated": ctx.get("gated"),          # e.g. "insufficient_information" - AI never ran
        "signals": ctx.get("signals", {}),
        "knowledge_hits": ctx.get("knowledge_hits", []),
        "tool_calls": ctx.get("tool_calls", []),
        "errors": ctx.get("errors", []),
    }


def score(claim: dict, result: dict, use_judge: bool) -> dict:
    if not result["ok"]:
        return {"id": claim["id"], "ok": False, "http": result.get("http"), "error": result.get("error")}

    gold = claim["gold"]
    draft = result["draft"]
    sources = result["signals"].get("knowledge_sources", [])
    gated = result.get("gated")

    row: dict = {
        "id": claim["id"],
        "claim_type": claim["claim_type"],
        "ok": True,
        "gated": gated,
        "latency_s": result["latency_s"],
        # A gated claim never reaches retrieval or the model - score only the
        # deterministic rule checks on the fixed reply.
        "retrieval": ({"applicable": False, "gated": True} if gated
                      else metrics.retrieval_scores(sources, gold.get("relevant_kb_docs", []))),
        "rules": metrics.rule_checks(draft, gold),
        "coverage_kw": metrics.coverage_keyword_match(draft, gold.get("coverage", [])),
        "tools": metrics.tool_summary(result["tool_calls"]),
        "runtime_errors": result["errors"],
    }
    if use_judge and not gated:
        from evals import judge
        row["judge"] = judge.judge_draft(
            draft=draft,
            claim_text=f"{claim['subject']}\n{claim['description']}",
            expected_coverage=gold.get("coverage", []),
            knowledge_hits=result["knowledge_hits"],
            tool_calls=result["tool_calls"],
            claim_notes=gold.get("notes", ""),
        )
    elif gated:
        row["judge"] = {"gated": True, "reason": "intake gate - fixed reply, not model output"}
    return row


def cleanup(claim_ids: list[str]) -> int:
    if not DB_PATH.exists():
        return 0
    emails = [f"{cid}@{EVAL_EMAIL_DOMAIN}" for cid in claim_ids]
    q = ",".join("?" * len(emails))
    c = sqlite3.connect(DB_PATH)
    c.execute(f"DELETE FROM drafts WHERE ticket_id IN (SELECT t.id FROM tickets t "
              f"JOIN customers c ON c.id=t.customer_id WHERE c.email IN ({q}))", emails)
    c.execute(f"DELETE FROM tickets WHERE customer_id IN (SELECT id FROM customers WHERE email IN ({q}))", emails)
    cur = c.execute(f"DELETE FROM customers WHERE email IN ({q})", emails)
    c.commit()
    n = cur.rowcount
    c.close()
    return n


def summarise(scored: list[dict]) -> str:
    ok = [s for s in scored if s["ok"]]
    lines = ["| id | type | ret.hit | ret.recall | rules | cov.kw | tools | lat.s | judge G/C/S |",
             "|---|---|---|---|---|---|---|---|---|"]
    for s in scored:
        if not s["ok"]:
            lines.append(f"| {s['id']} | — | — | — | HTTP {s.get('http')} | — | — | — | — |")
            continue
        r = s["retrieval"]
        cov = s["coverage_kw"]
        j = s.get("judge", {})
        if s.get("gated"):
            jcell = "GATE"
        elif j and "error" not in j:
            jcell = f"{j.get('groundedness','-')}/{j.get('coverage_correct','-')}/{j.get('safety_ok','-')}"
        else:
            jcell = "err" if j else "off"
        lines.append(
            f"| {s['id']} | {s['claim_type']}{' (gated)' if s.get('gated') else ''} | "
            f"{'yes' if r.get('hit') else ('n/a' if not r.get('applicable') else 'NO')} | "
            f"{r.get('recall') if r.get('applicable') else 'n/a'} | "
            f"{s['rules']['_score']} | "
            f"{'yes' if cov.get('any_correct') else ('n/a' if not cov.get('applicable') else 'NO')} | "
            f"{s['tools']['count']}{' err' if s['tools']['errors'] else ''} | "
            f"{s['latency_s']} | {jcell} |"
        )

    def _mean(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.mean(xs), 3) if xs else None

    def _median(xs):
        xs = [x for x in xs if x is not None]
        return round(statistics.median(xs), 2) if xs else None

    applic_ret = [s["retrieval"] for s in ok if s["retrieval"].get("applicable")]
    non_gated = [s for s in ok if not s.get("gated")]
    agg = {
        "claims_run": len(scored),
        "http_ok": len(ok),
        "gated": sum(1 for s in ok if s.get("gated")),
        "retrieval_hit_rate": _mean([1.0 if r["hit"] else 0.0 for r in applic_ret]),
        "retrieval_recall": _mean([r["recall"] for r in applic_ret]),
        "rule_pass_rate": _mean([s["rules"]["_pass_rate"] for s in ok]),
        "coverage_kw_any_correct": _mean(
            [1.0 if s["coverage_kw"]["any_correct"] else 0.0
             for s in ok if s["coverage_kw"].get("applicable")]
        ),
        # gated claims (0.1 s, no model call) excluded from latency stats
        "latency_p50_s": _median([s["latency_s"] for s in non_gated]),
        "latency_max_s": max((s["latency_s"] for s in non_gated), default=None),
    }
    judged = [s["judge"] for s in ok
              if s.get("judge") and "error" not in s["judge"] and "gated" not in s["judge"]]
    if judged:
        agg["judge_groundedness_mean_of_2"] = _mean([j["groundedness"] for j in judged])
        agg["judge_coverage_mean_of_2"] = _mean([j["coverage_correct"] for j in judged])
        agg["judge_safety_pass_rate"] = _mean([j["safety_ok"] for j in judged])

    out = ["# Evaluation run", "", f"_generated {dt.datetime.now().isoformat(timespec='seconds')}_", ""]
    out += ["## Aggregate", "", "```json", json.dumps(agg, indent=2), "```", ""]
    out += ["## Per-claim", ""] + lines + [""]
    out += ["## Judge reasoning", ""]
    for s in ok:
        j = s.get("judge") or {}
        if j.get("reason"):
            out.append(f"- **{s['id']}** — {j['reason']}")
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--keep", action="store_true", help="don't delete eval tickets afterwards")
    ap.add_argument("--only", default="", help="comma-separated claim ids")
    args = ap.parse_args()

    only = {x.strip() for x in args.only.split(",") if x.strip()} or None
    claims = load_claims(only)
    print(f"Running {len(claims)} claim(s) against {args.api} "
          f"(judge {'off' if args.no_judge else 'on'})")

    # Groq free tier is ~8k tokens/min; one agentic draft is well over that, so
    # pace non-gated claims. Override with EVAL_CLAIM_PACING_S.
    pacing = float(os.environ.get("EVAL_CLAIM_PACING_S", "75"))

    raw, scored = [], []
    for i, c in enumerate(claims):
        if i:
            time.sleep(pacing)
        print(f"  {c['id']:16} ", end="", flush=True)
        res = run_one(args.api, c)
        raw.append(res)
        row = score(c, res, use_judge=not args.no_judge)
        scored.append(row)
        if res["ok"] and row.get("gated"):
            print(f"GATED  {res['latency_s']:5.1f}s  rules {row['rules']['_score']}  (no model call)")
        elif res["ok"]:
            j = row.get("judge", {})
            jt = (f" judge {j.get('groundedness','-')}/{j.get('coverage_correct','-')}/{j.get('safety_ok','-')}"
                  if j and "gated" not in j else "")
            print(f"ok  {res['latency_s']:5.1f}s  rules {row['rules']['_score']}{jt}")
        else:
            print(f"FAIL  HTTP {res.get('http')}  {res.get('error','')[:80]}")

    RESULTS_DIR.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    (RESULTS_DIR / f"raw-{stamp}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in raw), encoding="utf-8")
    (RESULTS_DIR / f"scored-{stamp}.jsonl").write_text(
        "\n".join(json.dumps(r) for r in scored), encoding="utf-8")
    report = summarise(scored)
    (RESULTS_DIR / f"summary-{stamp}.md").write_text(report, encoding="utf-8")

    if not args.keep:
        n = cleanup([c["id"] for c in claims])
        print(f"\ncleaned up {n} eval customer row(s) from the DB")

    print(f"\nwrote evals/results/summary-{stamp}.md\n")
    print(report)


if __name__ == "__main__":
    main()
