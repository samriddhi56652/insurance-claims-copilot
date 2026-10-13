"""Run the analytics SQL against a claims database and export each result to CSV.

    python analytics/run_queries.py                       # analytics/analytics.db (synthetic)
    python analytics/run_queries.py --db data/support.db  # the app's real database (tiny)
    python analytics/run_queries.py --no-export           # print only

The CSVs in analytics/exports/ are what a BI tool (Power BI, Metabase, Looker...)
loads: one file per question. The SQL is plain SQLite (window functions and CTEs,
SQLite >= 3.25), so it runs against the app's own schema unchanged.
"""

from __future__ import annotations

import argparse
import csv
import pathlib
import sqlite3
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

HERE = pathlib.Path(__file__).resolve().parent
SQL_DIR = HERE / "sql"
EXPORT_DIR = HERE / "exports"


def run_all(db_path: pathlib.Path) -> dict[str, tuple[list[str], list[tuple]]]:
    """Create the view, then run every NN_*.sql. Returns {name: (columns, rows)}."""
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript((SQL_DIR / "00_views.sql").read_text(encoding="utf-8"))
        results: dict[str, tuple[list[str], list[tuple]]] = {}
        for path in sorted(SQL_DIR.glob("[0-9][0-9]_*.sql")):
            if path.name.startswith("00_"):
                continue
            cur = conn.execute(path.read_text(encoding="utf-8"))
            cols = [d[0] for d in cur.description]
            results[path.stem] = (cols, cur.fetchall())
        return results
    finally:
        conn.close()


def show(name: str, cols: list[str], rows: list[tuple], limit: int = 8) -> None:
    print(f"\n== {name}  ({len(rows)} rows)")
    shown = rows[:limit]
    widths = [max(len(str(c)), *(len(str(r[i])) for r in shown)) if shown else len(str(c))
              for i, c in enumerate(cols)]
    print("  " + "  ".join(str(c).ljust(w) for c, w in zip(cols, widths)))
    for r in shown:
        print("  " + "  ".join(str(v).ljust(w) for v, w in zip(r, widths)))
    if len(rows) > limit:
        print(f"  ... {len(rows) - limit} more")


def export(results: dict[str, tuple[list[str], list[tuple]]]) -> None:
    EXPORT_DIR.mkdir(exist_ok=True)
    for name, (cols, rows) in results.items():
        with open(EXPORT_DIR / f"{name}.csv", "w", newline="", encoding="utf-8") as fh:
            writer = csv.writer(fh)
            writer.writerow(cols)
            writer.writerows(rows)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--db", type=pathlib.Path, default=HERE / "analytics.db")
    ap.add_argument("--no-export", action="store_true")
    args = ap.parse_args()
    if not args.db.exists():
        sys.exit(f"{args.db} not found - run analytics/seed_synthetic_claims.py first.")
    results = run_all(args.db)
    for name, (cols, rows) in results.items():
        show(name, cols, rows)
    if not args.no_export:
        export(results)
        print(f"\nexported {len(results)} CSVs to {EXPORT_DIR}")


if __name__ == "__main__":
    main()
