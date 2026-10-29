# Claims analytics

Eight business questions about the claims pipeline, answered in SQL (CTEs and
window functions), cross-checked in pandas, and exported as CSV files for a BI
tool (Power BI, Metabase, Looker Studio).

> **Read this first: the data is invented.** The app's own database holds a handful
> of demo claims, far too few to analyse, so `seed_synthetic_claims.py` writes a
> year of made-up claims (about 370) into a separate file. Every number below is a
> property of how I built the generator, **not a finding about real claims**. What
> is real is the method: the SQL runs unchanged against the app's own schema.

## Run it

```bash
python analytics/seed_synthetic_claims.py     # writes analytics/analytics.db (seed 42, repeatable)
python analytics/run_queries.py               # runs the 8 queries, prints them, writes analytics/exports/*.csv
python analytics/pandas_check.py              # re-derives 6 of them in pandas and compares
python -m pytest tests/test_analytics.py      # 8 tests on a small generated database
```

`run_queries.py --db data/support.db` runs the same SQL on the app's real
database. It writes nothing into it (the helper view is a `TEMP` view that
disappears when the connection closes).

The scripts need `numpy` and `pandas`, which are not in `requirements.txt`:
`pip install numpy pandas`.

### Run one query at a time

The query files read from the temporary view built by `sql/00_views.sql`, so a
query file cannot run on its own. This command builds the view, then runs one file
and prints the result as a table. Run it from the project root; it works in cmd,
PowerShell, bash and zsh. Change only the file name at the end (use
`.venv\Scripts\python.exe` instead of `python` if the virtual environment is not
active):

```bash
python -c "import sqlite3,sys,pandas as pd; c=sqlite3.connect('analytics/analytics.db'); c.executescript(open('analytics/sql/00_views.sql').read()); pd.set_option('display.width',250); pd.set_option('display.max_columns',20); pd.set_option('display.max_rows',200); print(pd.read_sql(open(sys.argv[1]).read(), c))" analytics/sql/03_funnel.sql
```

| File name to put at the end | What it prints |
|---|---|
| `analytics/sql/01_cycle_time_by_type.sql` | mean, median and 90th percentile days, by claim type |
| `analytics/sql/02_stage_durations.sql` | hours spent between stages |
| `analytics/sql/03_funnel.sql` | claims reaching each stage, and where they drop out |
| `analytics/sql/04_approval_rate.sql` | approval rate by claim type and priority |
| `analytics/sql/05_repeat_within_90_days.sql` | repeat claims within 90 days, by claim type |
| `analytics/sql/06_cohort_retention.sql` | repeat-claim table by first-claim month (46 rows) |
| `analytics/sql/07_weekly_backlog.sql` | weekly registered, closed and open claims (53 rows) |
| `analytics/sql/08_slow_claims.sql` | the slowest 5% of claims in each type |

`NaN` in the output means "empty" (for example the first funnel stage has no
previous stage to compare with). To see the view itself, `00_views.sql` has no
output of its own, so print it:

```bash
python -c "import sqlite3, pandas as pd; c=sqlite3.connect('analytics/analytics.db'); c.executescript(open('analytics/sql/00_views.sql').read()); pd.set_option('display.width',250); pd.set_option('display.max_columns',20); print(pd.read_sql('SELECT * FROM v_claim_events LIMIT 6', c))"
```

## The data model, and one honest limit

The app stores each claim as a ticket plus its checklist, its correspondence and
its drafts. It does **not** store a "stage history" table, so the moment a claim
reached a stage has to be *inferred*. `sql/00_views.sql` builds one row per claim
with these proxies:

| Stage | Proxy for "when it got there" |
|---|---|
| registered | `tickets.created_at` |
| intake_sent | first message logged to the claimant |
| docs_complete | last checklist update, **only if** every item is verified or waived |
| recommended | first `coverage_recommendation` draft |
| closed | `tickets.closed_at` |

A stage that has not happened is `NULL`. These are good enough for durations and
funnels, but they are approximations: a checklist item re-touched after the fact
would move `docs_complete` later. A real deployment would add an event table.

## The eight questions

| # | File | Question | Techniques |
|---|---|---|---|
| 1 | `01_cycle_time_by_type` | How long does a closed claim take, by type? Mean, median, 90th percentile. | `ROW_NUMBER` / `COUNT` over a partition, nearest-rank percentile |
| 2 | `02_stage_durations` | Which stage is the slowest? | `UNION ALL` unpivot, `LAG` per claim |
| 3 | `03_funnel` | How many claims reach each stage, and where do they drop out? | `FIRST_VALUE`, `LAG`, matured cohort |
| 4 | `04_approval_rate` | Approval rate by claim type and priority. | conditional aggregation, `HAVING COUNT(*) >= 5` |
| 5 | `05_repeat_within_90_days` | Which claim types are followed by another claim within 90 days? | `LEAD` per customer, matured cohort |
| 6 | `06_cohort_retention` | Of customers whose first claim was in month M, how many claim again in M+1 ... M+6? | cohort by first-claim month, month arithmetic |
| 7 | `07_weekly_backlog` | Per week: claims registered, closed, and still open. | recursive CTE for the calendar |
| 8 | `08_slow_claims` | Which closed claims were unusually slow for their type? | `PERCENT_RANK`, `AVG() OVER` |

### Definitions that are easy to get wrong

- **Median and 90th percentile** are computed by hand (SQLite has no `MEDIAN`):
  rank the rows, take the middle one (or the mean of the middle two), and the row at
  rank `(9n+9)/10` for the 90th percentile (nearest-rank method).
- **Matured cohort (Q3, Q5).** Only claims registered at least 60 days (Q3) or 90
  days (Q5) before the newest claim are counted. A claim registered last week has not
  had time to reach the later stages or to be followed by a repeat, so counting it
  would make the funnel look leakier than it is. "Not reached *yet*" is not "dropped
  out". This is right-censoring.
- **Open at week end (Q7)** is reconstructed from timestamps (registered on or
  before the date, not closed by then). It is not a stored column.
- **Approval rate (Q4)** counts decided claims only (approved + denied).

## Known-answer validation

Because I wrote the generator, I planted patterns and can check the queries
recover them. If a query were wrong (a bad join, a mis-framed window), these would
not come out right.

| Planted in the generator | What the queries return |
|---|---|
| Per-type durations: Glass Damage fastest, Bodily Injury slowest | Q1 median days: Glass Damage 3.9, Collision 7.1, Bodily Injury 21.1 |
| Documents are the slow stage (days to verify, not hours to reply) | Q2: median 2.5 h to send intake vs about 110 h to complete documents |
| 5% of claimants go silent in `awaiting_documents` | Q3: 17 of 312 matured claims (5.4%) never leave that stage |
| A "storm month": 15% extra claims in March 2026, handled 1.6x slower | Q7: 15-17 claims registered in the early-March weeks vs a typical 6; open backlog peaks at 34 (typical 22) |

Two independent implementations (SQL and pandas) agree on Q1-Q5 and Q7. **Q6 and
Q8 have no second implementation**: the tests only check that they run and return
rows, so treat those two as less verified than the rest.

## Loading it into Power BI (or Metabase)

Get Data -> Text/CSV, load each file from `analytics/exports/`. No relationships are
needed: each file answers one question and stands alone.

| CSV | Suggested visual |
|---|---|
| `01_cycle_time_by_type` | Clustered bar: `median_days` and `p90_days` by `claim_type` (the gap between them is the story) |
| `02_stage_durations` | Bar: `median_hours_since_previous` by `stage_reached` |
| `03_funnel` | Funnel chart: `claims` by `stage`; add `pct_of_registered` as a label |
| `04_approval_rate` | Matrix: `claim_type` rows, `priority` columns, `approval_pct` values with conditional colour; hide cells with a small `decided_claims` |
| `05_repeat_within_90_days` | Bar: `repeat_within_90d_pct` by `claim_type` |
| `06_cohort_retention` | Matrix heatmap: `cohort` rows, `month_offset` columns, `retention_pct` values |
| `07_weekly_backlog` | Line and clustered column: `registered` and `closed` as columns, `open_at_week_end` as the line |
| `08_slow_claims` | Table sorted by `times_the_type_mean` |

A one-page layout: KPI cards on top (claims, median cycle time, approval rate, open
backlog), the weekly backlog line beneath, then the funnel and the by-type bars.

## What this does not tell you

- **Nothing here is evidence about real claims.** Change the generator's constants
  and the answers change; that is the point of using it for validation and the
  reason it cannot support a business claim.
- **Small groups.** Some type-by-priority cells in Q4 have 5-15 decided claims.
  Percentages on groups that size swing wildly; read them with the `decided_claims`
  column beside them.
- **Cohort retention (Q6)** has few customers per monthly cohort (about 25), so a
  cohort's percentage can move by several points on one customer.
- **Proxy timestamps** (above), and the snapshot date is fixed in the generator
  (2026-10-31), so "open" means open at that date.
