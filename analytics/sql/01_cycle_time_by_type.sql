-- Q1. How long does a claim take from registration to close, by claim type?
--
-- Closed claims only (an open claim has no cycle time yet; including it would
-- bias the answer low). SQLite has no MEDIAN, so rank the rows with a window
-- function: ROW_NUMBER() orders them, COUNT() OVER the same partition gives n,
-- and the median is the mean of the middle one or two ranks.
-- p90 uses the nearest-rank rule: the ceil(0.9 * n)-th value, written with
-- integer arithmetic as (9n + 9) / 10.

WITH closed AS (
    SELECT claim_type,
           julianday(closed_at) - julianday(registered_at) AS days
    FROM v_claim_events
    WHERE closed_at IS NOT NULL
),
ranked AS (
    SELECT claim_type,
           days,
           ROW_NUMBER() OVER (PARTITION BY claim_type ORDER BY days) AS rn,
           COUNT(*)     OVER (PARTITION BY claim_type)               AS n
    FROM closed
)
SELECT claim_type,
       n                                                                    AS claims,
       ROUND(AVG(days), 2)                                                  AS mean_days,
       ROUND(AVG(CASE WHEN rn IN ((n + 1) / 2, (n + 2) / 2) THEN days END), 2) AS median_days,
       ROUND(MAX(CASE WHEN rn = (9 * n + 9) / 10 THEN days END), 2)         AS p90_days
FROM ranked
GROUP BY claim_type, n
ORDER BY median_days DESC;
