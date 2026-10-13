-- Q8. Which closed claims were unusually slow for their type?
--
-- PERCENT_RANK() ranks each claim within its type (0 = fastest, 1 = slowest);
-- the top 5% are listed with how many times the type's average they took.
-- AVG() as a window function puts the type average on every row without a join.

WITH closed AS (
    SELECT ticket_id,
           claim_type,
           priority,
           julianday(closed_at) - julianday(registered_at) AS days
    FROM v_claim_events
    WHERE closed_at IS NOT NULL
),
scored AS (
    SELECT *,
           PERCENT_RANK() OVER (PARTITION BY claim_type ORDER BY days) AS pct_rank,
           AVG(days)      OVER (PARTITION BY claim_type)               AS type_mean_days
    FROM closed
)
SELECT ticket_id,
       claim_type,
       priority,
       ROUND(days, 1)                   AS days,
       ROUND(type_mean_days, 1)         AS type_mean_days,
       ROUND(days / type_mean_days, 1)  AS times_the_type_mean
FROM scored
WHERE pct_rank >= 0.95
ORDER BY times_the_type_mean DESC, ticket_id
LIMIT 25;
