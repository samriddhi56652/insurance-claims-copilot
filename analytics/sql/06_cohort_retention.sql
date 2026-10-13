-- Q6. Cohort retention: of the customers whose FIRST claim fell in a given month,
--     what share files again k months later?
--
-- Output is "long" (one row per cohort and month offset); pivot it in the BI tool
-- or pandas to get the usual triangle. Late cohorts have fewer observable offsets,
-- so their right-hand cells are missing, not zero.
--
-- Month arithmetic: year * 12 + month, so the difference of two dates is a whole
-- number of months.

WITH firsts AS (
    SELECT customer_id,
           strftime('%Y-%m', MIN(registered_at)) AS cohort
    FROM v_claim_events
    GROUP BY customer_id
),
activity AS (
    SELECT DISTINCT
           e.customer_id,
           f.cohort,
           (CAST(strftime('%Y', e.registered_at) AS INTEGER) * 12
            + CAST(strftime('%m', e.registered_at) AS INTEGER))
         - (CAST(substr(f.cohort, 1, 4) AS INTEGER) * 12
            + CAST(substr(f.cohort, 6, 2) AS INTEGER)) AS month_offset
    FROM v_claim_events e
    JOIN firsts f ON f.customer_id = e.customer_id
),
sizes AS (
    SELECT cohort, COUNT(*) AS cohort_size FROM firsts GROUP BY cohort
)
SELECT a.cohort,
       s.cohort_size,
       a.month_offset,
       COUNT(DISTINCT a.customer_id)                                  AS active_customers,
       ROUND(100.0 * COUNT(DISTINCT a.customer_id) / s.cohort_size, 1) AS retention_pct
FROM activity a
JOIN sizes s ON s.cohort = a.cohort
WHERE a.month_offset BETWEEN 0 AND 6
GROUP BY a.cohort, s.cohort_size, a.month_offset
ORDER BY a.cohort, a.month_offset;
