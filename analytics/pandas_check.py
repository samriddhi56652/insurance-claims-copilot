"""Re-derive five of the SQL answers in pandas and compare.

    python analytics/pandas_check.py
    python analytics/pandas_check.py --db data/support.db

Two independent implementations of the same question is the cheapest way to catch
a wrong join or a mis-written window frame: if SQL and pandas disagree, one of them
is wrong. Checked: Q1 cycle time, Q2 stage durations (medians), Q3 funnel, Q4
approval rate, Q5 repeat-within-90-days, Q7 weekly backlog.
"""

from __future__ import annotations

import argparse
import math
import pathlib
import sqlite3
import sys

import numpy as np
import pandas as pd

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from run_queries import run_all  # noqa: E402

TOL = 0.0051  # SQL rounds to 2 dp (or 1 dp); allow the rounding


def load_events(db_path: pathlib.Path) -> pd.DataFrame:
    """One row per claim with the stage times - the same proxies as 00_views.sql."""
    conn = sqlite3.connect(db_path)
    try:
        t = pd.read_sql("SELECT id AS ticket_id, customer_id, claim_type, priority, outcome, "
                        "created_at AS registered_at, closed_at FROM tickets", conn)
        corr = pd.read_sql("SELECT ticket_id, direction, created_at FROM claim_correspondence", conn)
        reqs = pd.read_sql("SELECT ticket_id, status, updated_at FROM claim_requirements", conn)
        drafts = pd.read_sql("SELECT ticket_id, kind, created_at FROM drafts", conn)
    finally:
        conn.close()

    for df, cols in ((t, ["registered_at", "closed_at"]), (corr, ["created_at"]),
                     (reqs, ["updated_at"]), (drafts, ["created_at"])):
        for c in cols:
            df[c] = pd.to_datetime(df[c])

    sent = (corr[corr["direction"] == "to_claimant"].groupby("ticket_id")["created_at"].min()
            .rename("intake_sent_at"))
    grp = reqs.groupby("ticket_id")
    n_items = grp.size()
    n_done = (reqs[reqs["status"].isin(["verified", "waived"])].groupby("ticket_id").size()
              .reindex(n_items.index, fill_value=0))
    docs = grp["updated_at"].max().where(n_items == n_done).rename("docs_complete_at")
    rec = (drafts[drafts["kind"] == "coverage_recommendation"].groupby("ticket_id")["created_at"].min()
           .rename("recommended_at"))
    ev = t.set_index("ticket_id").join([sent, docs, rec]).reset_index()
    return ev


def _close(a, b) -> bool:
    return (a is None and b is None) or (a is not None and b is not None and abs(float(a) - float(b)) <= TOL)


def _nearest_rank(values: np.ndarray, p: float) -> float:
    v = np.sort(values)
    return float(v[int(math.ceil(p * len(v))) - 1])


def check(db_path: pathlib.Path) -> list[tuple[str, bool, str]]:
    sql = run_all(db_path)
    ev = load_events(db_path)
    out: list[tuple[str, bool, str]] = []

    # Q1 cycle time by type ---------------------------------------------------
    closed = ev[ev["closed_at"].notna()].copy()
    closed["days"] = (closed["closed_at"] - closed["registered_at"]).dt.total_seconds() / 86400
    exp = {r.claim_type: (len(g), g.days.mean(), g.days.median(), _nearest_rank(g.days.to_numpy(), 0.9))
           for r in closed.drop_duplicates("claim_type").itertuples()
           for g in [closed[closed.claim_type == r.claim_type]]}
    cols, rows = sql["01_cycle_time_by_type"]
    ok = len(rows) == len(exp) and all(
        r[1] == exp[r[0]][0] and _close(r[2], exp[r[0]][1]) and _close(r[3], exp[r[0]][2])
        and _close(r[4], exp[r[0]][3]) for r in rows)
    out.append(("Q1 cycle time by type (n, mean, median, p90)", ok, f"{len(rows)} types"))

    # Q2 stage durations (medians) ----------------------------------------------
    order = [("intake_sent", "registered_at", "intake_sent_at"),
             ("docs_complete", "intake_sent_at", "docs_complete_at"),
             ("recommended", "docs_complete_at", "recommended_at"),
             ("closed", "recommended_at", "closed_at")]
    exp2 = {}
    for stage, prev, cur in order:
        d = ev[ev[cur].notna() & ev[prev].notna()]
        hrs = (d[cur] - d[prev]).dt.total_seconds() / 3600
        exp2[stage] = (len(hrs), hrs.mean(), hrs.median())
    cols, rows = sql["02_stage_durations"]
    ok = all(r[1] == exp2[r[0]][0] and abs(r[2] - exp2[r[0]][1]) <= 0.051
             and abs(r[3] - exp2[r[0]][2]) <= 0.051 for r in rows) and len(rows) == len(exp2)
    out.append(("Q2 stage durations (n, mean, median hours)", ok, f"{len(rows)} stages"))

    # Q3 funnel (matured cohort) ----------------------------------------------
    cutoff = ev["registered_at"].max().normalize() - pd.Timedelta(days=60)
    cohort = ev[ev["registered_at"] <= cutoff]
    exp3 = [len(cohort), cohort["intake_sent_at"].notna().sum(), cohort["docs_complete_at"].notna().sum(),
            cohort["recommended_at"].notna().sum(), cohort["closed_at"].notna().sum()]
    cols, rows = sql["03_funnel"]
    out.append(("Q3 funnel counts", [r[1] for r in rows] == [int(x) for x in exp3], f"{exp3}"))

    # Q4 approval rate -----------------------------------------------------------
    decided = ev[ev["outcome"].isin(["approved", "denied"])]
    g = decided.groupby(["claim_type", "priority"])["outcome"].agg(
        n="size", approved=lambda s: int((s == "approved").sum()))
    g = g[g["n"] >= 5]
    cols, rows = sql["04_approval_rate"]
    # Compare against the EXACT percentage: SQLite rounds half up (13/16 = 81.25 -> 81.3)
    # while Python's round() goes half-to-even (-> 81.2). Both are right; rounding the
    # pandas side first would report a bug that isn't one.
    exp4 = {(i[0], i[1]): (int(r.n), int(r.approved), 100.0 * r.approved / r.n)
            for i, r in g.iterrows()}
    ok = len(rows) == len(exp4) and all(
        exp4[(r[0], r[1])][0] == r[2] and exp4[(r[0], r[1])][1] == r[3]
        and abs(exp4[(r[0], r[1])][2] - r[4]) <= 0.0501 for r in rows)
    out.append(("Q4 approval rate by type and priority", ok, f"{len(rows)} groups"))

    # Q5 repeat within 90 days ------------------------------------------------------
    s = ev.sort_values(["customer_id", "registered_at"]).copy()
    s["next_at"] = s.groupby("customer_id")["registered_at"].shift(-1)
    cut5 = ev["registered_at"].max().normalize() - pd.Timedelta(days=90)
    obs = s[s["registered_at"] <= cut5].copy()
    obs["followed"] = ((obs["next_at"] - obs["registered_at"]).dt.total_seconds() / 86400) <= 90
    exp5 = {k: (len(v), int(v["followed"].sum())) for k, v in obs.groupby("claim_type")}
    cols, rows = sql["05_repeat_within_90_days"]
    ok = len(rows) == len(exp5) and all(exp5[r[0]] == (r[1], r[2]) for r in rows)
    out.append(("Q5 repeat within 90 days by type", ok, f"{len(rows)} types"))

    # Q7 weekly backlog ----------------------------------------------------------------
    first_day = ev["registered_at"].min().normalize()
    last_day = ev["registered_at"].max().normalize()
    week_end = first_day + pd.Timedelta(days=6)
    exp7 = []
    reg_d = ev["registered_at"].dt.normalize()
    clo_d = ev["closed_at"].dt.normalize()
    while True:
        lo = week_end - pd.Timedelta(days=7)
        registered = int(((reg_d > lo) & (reg_d <= week_end)).sum())
        closed_n = int((clo_d.notna() & (clo_d > lo) & (clo_d <= week_end)).sum())
        open_n = int(((reg_d <= week_end) & (clo_d.isna() | (clo_d > week_end))).sum())
        exp7.append((week_end.strftime("%Y-%m-%d"), registered, closed_n, open_n))
        if week_end >= last_day:
            break
        week_end += pd.Timedelta(days=7)
    cols, rows = sql["07_weekly_backlog"]
    out.append(("Q7 weekly registered / closed / open", [tuple(r) for r in rows] == exp7, f"{len(rows)} weeks"))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=pathlib.Path, default=HERE / "analytics.db")
    args = ap.parse_args()
    results = check(args.db)
    for name, ok, detail in results:
        print(f"{'PASS' if ok else 'FAIL'}  {name}   [{detail}]")
    if not all(ok for _, ok, _ in results):
        sys.exit(1)
    print("\nSQL and pandas agree on every checked question.")


if __name__ == "__main__":
    main()
