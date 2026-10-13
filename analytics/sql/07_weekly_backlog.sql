-- Q7. Week by week: claims registered, claims closed, and claims still open at
--     the end of the week (the backlog).
--
-- A recursive CTE generates the list of week-end dates; each week is a 7-day
-- window ending on that date. "Open at week end" = registered on or before the
-- date and not closed by then (closed_at is NULL or later). This is a state
-- reconstructed from timestamps, not a stored column.

WITH RECURSIVE bounds AS (
    SELECT date(MIN(registered_at)) AS first_day,
           date(MAX(registered_at)) AS last_day
    FROM v_claim_events
),
weeks(week_end) AS (
    SELECT date(first_day, '+6 days') FROM bounds
    UNION ALL
    SELECT date(week_end, '+7 days')
    FROM weeks, bounds
    WHERE week_end < bounds.last_day
)
SELECT w.week_end,
       (SELECT COUNT(*) FROM v_claim_events e
         WHERE date(e.registered_at) >  date(w.week_end, '-7 days')
           AND date(e.registered_at) <= w.week_end)                         AS registered,
       (SELECT COUNT(*) FROM v_claim_events e
         WHERE e.closed_at IS NOT NULL
           AND date(e.closed_at) >  date(w.week_end, '-7 days')
           AND date(e.closed_at) <= w.week_end)                             AS closed,
       (SELECT COUNT(*) FROM v_claim_events e
         WHERE date(e.registered_at) <= w.week_end
           AND (e.closed_at IS NULL OR date(e.closed_at) > w.week_end))     AS open_at_week_end
FROM weeks w
ORDER BY w.week_end;
