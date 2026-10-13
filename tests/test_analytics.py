"""The analytics layer: seed -> SQL -> pandas cross-check, plus invariants."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

ANALYTICS = Path(__file__).resolve().parent.parent / "analytics"
sys.path.insert(0, str(ANALYTICS))

import pandas_check  # noqa: E402
import run_queries  # noqa: E402
import seed_synthetic_claims as seed  # noqa: E402


@pytest.fixture(scope="module")
def db(tmp_path_factory):
    path = tmp_path_factory.mktemp("analytics") / "analytics.db"
    seed.build(path, n_customers=70, seed=7)
    return path


def test_every_query_runs_and_returns_rows(db):
    results = run_queries.run_all(db)
    assert len(results) == 8
    for name, (cols, rows) in results.items():
        assert cols and rows, name


def test_sql_and_pandas_agree_on_every_checked_question(db):
    results = pandas_check.check(db)
    assert len(results) == 6
    assert all(ok for _, ok, _ in results), [(n, d) for n, ok, d in results if not ok]


def test_the_cross_check_can_actually_fail(db, monkeypatch):
    """Guard against a check that always passes: corrupt one SQL result."""
    real = pandas_check.run_all

    def corrupted(path):
        out = real(path)
        cols, rows = out["03_funnel"]
        rows = [tuple(r) for r in rows]
        rows[2] = (rows[2][0], rows[2][1] + 1, *rows[2][2:])   # one extra claim at docs_complete
        out["03_funnel"] = (cols, rows)
        return out

    monkeypatch.setattr(pandas_check, "run_all", corrupted)
    results = dict((n, ok) for n, ok, _ in pandas_check.check(db))
    assert results["Q3 funnel counts"] is False


def test_funnel_never_gains_claims_and_durations_are_not_negative(db):
    results = run_queries.run_all(db)
    funnel = [r[1] for r in results["03_funnel"][1]]
    assert funnel == sorted(funnel, reverse=True)
    for r in results["01_cycle_time_by_type"][1]:
        assert r[2] >= 0 and r[3] >= 0 and r[4] >= r[3]     # mean, median >= 0; p90 >= median
    for r in results["02_stage_durations"][1]:
        assert r[2] >= 0 and r[3] >= 0


def test_backlog_is_never_negative_and_weeks_increase(db):
    rows = run_queries.run_all(db)["07_weekly_backlog"][1]
    weeks = [r[0] for r in rows]
    assert weeks == sorted(set(weeks))
    assert all(r[3] >= 0 for r in rows)


def test_the_planted_march_surge_shows_up_in_the_weekly_numbers(db):
    rows = run_queries.run_all(db)["07_weekly_backlog"][1]
    march = sum(r[1] for r in rows if r[0].startswith("2026-03") or r[0].startswith("2026-04-0"))
    typical = sorted(sum(r[1] for r in rows if r[0].startswith(m)) for m in
                     ("2025-12", "2026-01", "2026-02", "2026-05", "2026-06", "2026-07"))
    assert march > 1.5 * typical[len(typical) // 2]


def test_seeding_is_deterministic(tmp_path):
    a, b = tmp_path / "a.db", tmp_path / "b.db"
    assert seed.build(a, n_customers=40, seed=3) == seed.build(b, n_customers=40, seed=3)


def test_seeding_leaves_the_environment_alone(tmp_path):
    import os
    before = os.environ.get("DB_PATH")
    seed.build(tmp_path / "x.db", n_customers=20, seed=1)
    assert os.environ.get("DB_PATH") == before
