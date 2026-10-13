-- Q3. Funnel: how many claims reach each stage, and where do they drop out?
--
-- Only claims registered at least 60 days before the newest claim are counted.
-- A claim registered last week hasn't had time to reach the later stages, so
-- including it would make the funnel look leakier than it is (a censoring
-- problem: "not reached yet" is not "dropped out").

WITH ref AS (
    SELECT date(MAX(registered_at), '-60 days') AS cutoff FROM v_claim_events
),
cohort AS (
    SELECT e.*
    FROM v_claim_events e, ref
    WHERE e.registered_at <= ref.cutoff
),
counts AS (
    SELECT 1 AS ord, 'registered'    AS stage, COUNT(*)                AS claims FROM cohort
    UNION ALL SELECT 2, 'intake_sent',   COUNT(intake_sent_at)   FROM cohort
    UNION ALL SELECT 3, 'docs_complete', COUNT(docs_complete_at) FROM cohort
    UNION ALL SELECT 4, 'recommended',   COUNT(recommended_at)   FROM cohort
    UNION ALL SELECT 5, 'closed',        COUNT(closed_at)        FROM cohort
)
SELECT stage,
       claims,
       ROUND(100.0 * claims / FIRST_VALUE(claims) OVER (ORDER BY ord), 1) AS pct_of_registered,
       ROUND(100.0 * claims / LAG(claims) OVER (ORDER BY ord), 1)         AS pct_of_previous_stage,
       LAG(claims) OVER (ORDER BY ord) - claims                           AS dropped_at_this_step
FROM counts
ORDER BY ord;
