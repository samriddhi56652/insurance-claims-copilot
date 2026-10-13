"""Generate a SYNTHETIC claims history for the analytics layer.

    python analytics/seed_synthetic_claims.py                 # ~400 claims -> analytics/analytics.db
    python analytics/seed_synthetic_claims.py --customers 60  # a small one (the tests use this)

Why it exists: the real database holds a handful of demo claims, far too few to
analyse. This writes a year of invented claims, with the same tables as the app,
into a SEPARATE file so the real data is never touched.

EVERYTHING HERE IS INVENTED. Every number the queries return is a property of the
generator below (how I chose the durations, mixes and approval rates), not a fact
about real claims. What is real is the method: the SQL runs unchanged against the
app's own database.

The shape follows the app's lifecycle. Per claim: registered -> intake reply sent
-> documents verified -> coverage recommendation drafted -> adjuster decision ->
closed, with a stage left unreached where the claim is still in flight at the
snapshot date. Deterministic for a given --seed.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sqlite3
import sys
from datetime import datetime, timedelta

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DEFAULT_DB = ROOT / "analytics" / "analytics.db"
START = datetime(2025, 11, 1)
SNAPSHOT = datetime(2026, 10, 31, 23, 59, 59)

TYPES = ["Collision", "Comprehensive", "Theft", "Glass Damage",
         "Bodily Injury", "Property Damage", "Other"]
P_TYPE = [0.38, 0.18, 0.08, 0.14, 0.06, 0.12, 0.04]
# median days from "intake reply sent" to "every document verified"
MEDIAN_DOCS_DAYS = {"Collision": 4, "Comprehensive": 5, "Theft": 9, "Glass Damage": 2,
                    "Bodily Injury": 11, "Property Damage": 6, "Other": 5}
# median days from "recommendation approved" to "closed"
MEDIAN_DECISION_DAYS = {"Collision": 2, "Comprehensive": 2, "Theft": 4, "Glass Damage": 1,
                        "Bodily Injury": 5, "Property Damage": 3, "Other": 3}
P_APPROVE = {"Collision": 0.82, "Comprehensive": 0.76, "Theft": 0.58, "Glass Damage": 0.92,
             "Bodily Injury": 0.70, "Property Damage": 0.80, "Other": 0.65}
P_STALLED = 0.05  # claimant stops responding; the claim sits in awaiting_documents

# PLANTED PATTERN, so the analysis can be checked against a known answer: a storm
# month. Extra claims arrive in March 2026 and everything is handled more slowly.
SURGE_START = datetime(2026, 3, 1)
SURGE_END = datetime(2026, 3, 31, 23, 59, 59)
SURGE_SLOWDOWN = 1.6
SURGE_EXTRA_SHARE = 0.15  # extra single-claim customers, as a share of n_customers


def fmt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _hours(rng, median: float, sigma: float, floor: float) -> timedelta:
    return timedelta(hours=max(floor, float(rng.lognormal(np.log(median), sigma))))


def _days(rng, median: float, sigma: float) -> timedelta:
    return timedelta(days=float(rng.lognormal(np.log(median), sigma)))


def make_claims(rng, n_customers: int) -> list[dict]:
    """Customers with 1-4 claims; some file again soon, most much later."""
    claims: list[dict] = []
    span_days = (SNAPSHOT - START).days - 5
    for cust in range(1, n_customers + 1):
        k = int(rng.choice([1, 2, 3, 4], p=[0.62, 0.24, 0.10, 0.04]))
        t = START + timedelta(days=float(rng.uniform(0, span_days)))
        for j in range(k):
            if j:
                gap = (rng.uniform(20, 90) if rng.random() < 0.4
                       else rng.lognormal(np.log(150), 0.5))
                t = t + timedelta(days=float(gap))
            if t > SNAPSHOT - timedelta(hours=1):
                break
            claims.append({"customer": cust, "created": t.replace(microsecond=0)})
    for extra in range(int(n_customers * SURGE_EXTRA_SHARE)):
        when = SURGE_START + timedelta(
            seconds=float(rng.uniform(0, (SURGE_END - SURGE_START).total_seconds())))
        claims.append({"customer": n_customers + 1 + extra, "created": when.replace(microsecond=0)})
    claims.sort(key=lambda c: c["created"])
    return claims


def simulate(rng, claim: dict) -> dict:
    """Event times for one claim (None where the stage is never reached)."""
    typ = str(rng.choice(TYPES, p=P_TYPE))
    if typ == "Bodily Injury":
        priority = str(rng.choice(["urgent", "high", "medium"], p=[0.5, 0.4, 0.1]))
    else:
        priority = str(rng.choice(["low", "medium", "high", "urgent"], p=[0.2, 0.55, 0.2, 0.05]))
    created = claim["created"]
    intake_sent = created + _hours(rng, 2.5, 0.7, 0.2)
    surge = SURGE_START <= created <= SURGE_END
    slow = SURGE_SLOWDOWN if surge else 1.0
    docs_td = _days(rng, MEDIAN_DOCS_DAYS[typ] * slow, 0.5)
    stalled = bool(rng.random() < P_STALLED)
    docs_done = None if stalled else intake_sent + docs_td
    recommended = docs_done + _hours(rng, 6, 0.6, 0.5) if docs_done else None
    rec_approved = recommended + _hours(rng, 5, 0.6, 0.5) if recommended else None
    closed = (rec_approved + _days(rng, MEDIAN_DECISION_DAYS[typ] * slow, 0.6)
              if rec_approved else None)
    outcome = "approved" if rng.random() < P_APPROVE[typ] else "denied"
    return {**claim, "type": typ, "priority": priority, "intake_sent": intake_sent,
            "docs_td": docs_td, "stalled": stalled, "docs_done": docs_done,
            "recommended": recommended, "rec_approved": rec_approved,
            "closed": closed, "outcome": outcome}


def build(db_path: pathlib.Path, n_customers: int = 260, seed: int = 42) -> dict:
    db_path = pathlib.Path(db_path)
    if db_path.exists():
        db_path.unlink()
    db_path.parent.mkdir(parents=True, exist_ok=True)

    # Create the schema with the app's own init_db, pointed at the analytics file.
    previous = os.environ.get("DB_PATH")
    os.environ["DB_PATH"] = str(db_path)
    from customer_support_agent.core.settings import get_settings
    get_settings.cache_clear()
    from customer_support_agent.repositories.sqlite.base import init_db
    from customer_support_agent.services.requirements_catalog import requirements_for_claim

    try:
        init_db()
    finally:  # leave the process environment as we found it
        if previous is None:
            os.environ.pop("DB_PATH", None)
        else:
            os.environ["DB_PATH"] = previous
        get_settings.cache_clear()

    rng = np.random.default_rng(seed)
    claims = [simulate(rng, c) for c in make_claims(rng, n_customers)]
    snap = SNAPSHOT

    def reached(ts):  # an event only exists if it has happened by the snapshot
        return ts is not None and ts <= snap

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    # customers (including the surge month's extra single-claim customers)
    for cust in range(1, max(c["customer"] for c in claims) + 1):
        company = f"Synthetic Co {cust % 40}" if cust % 5 == 0 else None
        cur.execute(
            "INSERT INTO customers (id, email, name, company, created_at) VALUES (?, ?, ?, ?, ?)",
            (cust, f"synthetic-{cust:04d}@example.com", f"Synthetic Customer {cust}",
             company, fmt(START)),
        )

    counts = {"claims": 0, "closed": 0, "open": 0}
    for c in claims:
        created, typ = c["created"], c["type"]
        is_closed = reached(c["closed"])
        # stage at the snapshot
        if is_closed:
            stage = "closed"
        elif reached(c["rec_approved"]):
            stage = "settlement"
        elif reached(c["docs_done"]):
            stage = "review_ready"
        elif reached(c["intake_sent"]):
            stage = "awaiting_documents"
        else:
            stage = "intake"

        events = [created]
        for key in ("intake_sent", "docs_done", "recommended", "rec_approved", "closed"):
            if reached(c[key]):
                events.append(c[key])
        updated = max(events)

        approved = c["outcome"] == "approved"
        cur.execute(
            """INSERT INTO tickets (customer_id, subject, description, claim_type, status,
                   lifecycle_stage, priority, coverage_decision, decision_note,
                   repair_authorized, payment_arranged, outcome, closed_at, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (c["customer"], f"Synthetic {typ} claim",
             f"Synthetic narrative for a {typ} claim (generated data, not a real incident).",
             typ, "closed" if is_closed else "open", stage, c["priority"],
             c["outcome"] if is_closed else None,
             ("Approved: repair authorised." if approved else "Not covered under policy terms.") if is_closed else None,
             1 if (is_closed and approved) else 0, 1 if (is_closed and approved) else 0,
             c["outcome"] if is_closed else None,
             fmt(c["closed"]) if is_closed else None,
             fmt(created), fmt(updated)),
        )
        tid = cur.lastrowid
        counts["claims"] += 1
        counts["closed" if is_closed else "open"] += 1

        # correspondence
        if reached(c["intake_sent"]):
            cur.execute("INSERT INTO claim_correspondence (ticket_id, direction, channel, body, created_at) VALUES (?,?,?,?,?)",
                        (tid, "to_claimant", "email", "Synthetic intake reply", fmt(c["intake_sent"])))
            reply_at = c["intake_sent"] + c["docs_td"] * 0.5
            if reached(reply_at):
                cur.execute("INSERT INTO claim_correspondence (ticket_id, direction, channel, body, created_at) VALUES (?,?,?,?,?)",
                            (tid, "from_claimant", "email", "Synthetic claimant reply", fmt(reply_at)))
            if c["docs_td"] > timedelta(days=3):
                chase_at = c["intake_sent"] + timedelta(days=1.5)
                if reached(chase_at):
                    cur.execute("INSERT INTO claim_correspondence (ticket_id, direction, channel, body, created_at) VALUES (?,?,?,?,?)",
                                (tid, "to_claimant", "email", "Synthetic follow-up", fmt(chase_at)))

        # drafts
        def draft(kind, at, accepted):
            cur.execute("INSERT INTO drafts (ticket_id, content, context_used, kind, status, created_at) VALUES (?,?,?,?,?,?)",
                        (tid, f"SYNTHETIC DRAFT ({kind})", None, kind,
                         "accepted" if accepted else "pending", fmt(at)))

        draft("intake_request", created + timedelta(minutes=3), reached(c["intake_sent"]))
        if reached(c["intake_sent"]) and c["docs_td"] > timedelta(days=3):
            chase_at = c["intake_sent"] + timedelta(days=1.4)
            if reached(chase_at):
                draft("followup_request", chase_at, True)
        if reached(c["recommended"]):
            draft("coverage_recommendation", c["recommended"], reached(c["rec_approved"]))
        if is_closed and approved:
            draft("closure_notice", c["closed"] + timedelta(minutes=30), True)

        # checklist
        if reached(c["intake_sent"]):
            items = requirements_for_claim(typ)
            n = len(items)
            start_ts = c["intake_sent"]
            if reached(c["docs_done"]):
                done_flags = [True] * n
                end_ts = c["docs_done"]
            else:
                total = c["docs_td"].total_seconds()
                elapsed = (snap - start_ts).total_seconds()
                frac = (rng.uniform(0.2, 0.6) if c["stalled"]
                        else float(np.clip(elapsed / total, 0, 0.95)))
                k_done = int(frac * n)
                done_flags = [i < k_done for i in range(n)]
                end_ts = min(snap, start_ts + timedelta(seconds=max(1.0, frac * total)))
            span = max(1.0, (end_ts - start_ts).total_seconds())
            done_idx = [i for i, d in enumerate(done_flags) if d]
            fracs = sorted(float(x) for x in rng.uniform(0.05, 1.0, size=len(done_idx)))
            if fracs:
                fracs[-1] = 1.0  # the last verified item is the moment "documents complete"
            for i, (label, category) in enumerate(items):
                if done_flags[i]:
                    ts = start_ts + timedelta(seconds=span * fracs[done_idx.index(i)])
                    status = "waived" if ("Police report" in label and rng.random() < 0.1) else "verified"
                else:
                    ts, status = start_ts, "needed"
                cur.execute("INSERT INTO claim_requirements (ticket_id, item_label, category, status, created_at, updated_at) VALUES (?,?,?,?,?,?)",
                            (tid, label, category, status, fmt(start_ts), fmt(min(ts, snap))))

    conn.commit()
    conn.close()
    return counts


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=pathlib.Path, default=DEFAULT_DB)
    ap.add_argument("--customers", type=int, default=260)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    counts = build(args.db, args.customers, args.seed)
    print(f"wrote {args.db}")
    print(f"  claims={counts['claims']}  closed={counts['closed']}  open={counts['open']}  (SYNTHETIC)")


if __name__ == "__main__":
    main()
