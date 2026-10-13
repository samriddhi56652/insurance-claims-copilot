-- Q2. Where do claims wait? Time spent between consecutive stages.
--
-- Unpivot the stage timestamps into one row per (claim, stage), then LAG() over
-- each claim's stages in order gives the time since the previous stage. A claim
-- that has not reached a stage simply has no row for it.

WITH stages AS (
    SELECT ticket_id, 1 AS ord, 'registered'    AS stage, registered_at    AS ts FROM v_claim_events
    UNION ALL
    SELECT ticket_id, 2, 'intake_sent',   intake_sent_at   FROM v_claim_events WHERE intake_sent_at   IS NOT NULL
    UNION ALL
    SELECT ticket_id, 3, 'docs_complete', docs_complete_at FROM v_claim_events WHERE docs_complete_at IS NOT NULL
    UNION ALL
    SELECT ticket_id, 4, 'recommended',   recommended_at   FROM v_claim_events WHERE recommended_at   IS NOT NULL
    UNION ALL
    SELECT ticket_id, 5, 'closed',        closed_at        FROM v_claim_events WHERE closed_at        IS NOT NULL
),
gaps AS (
    SELECT ticket_id,
           ord,
           stage,
           (julianday(ts) - julianday(LAG(ts) OVER (PARTITION BY ticket_id ORDER BY ord))) * 24.0
               AS hours_since_previous
    FROM stages
),
ranked AS (
    SELECT stage,
           ord,
           hours_since_previous AS hrs,
           ROW_NUMBER() OVER (PARTITION BY stage ORDER BY hours_since_previous) AS rn,
           COUNT(*)     OVER (PARTITION BY stage)                               AS n
    FROM gaps
    WHERE hours_since_previous IS NOT NULL
)
SELECT stage                                                           AS stage_reached,
       n                                                               AS claims,
       ROUND(AVG(hrs), 1)                                              AS mean_hours_since_previous,
       ROUND(AVG(CASE WHEN rn IN ((n + 1) / 2, (n + 2) / 2) THEN hrs END), 1) AS median_hours_since_previous
FROM ranked
GROUP BY stage, ord, n
ORDER BY ord;
