-- Q5. After a claim of each type, how often does the same customer file again
--     within 90 days?
--
-- LEAD() over each customer's claims (oldest first) gives the NEXT claim's date.
-- Only claims registered at least 90 days before the newest claim are counted: a
-- recent claim hasn't had 90 days to be followed by another, and counting it as
-- "no repeat" would understate the rate.

WITH ref AS (
    SELECT date(MAX(registered_at), '-90 days') AS cutoff FROM v_claim_events
),
sequenced AS (
    SELECT ticket_id,
           claim_type,
           registered_at,
           LEAD(registered_at) OVER (PARTITION BY customer_id ORDER BY registered_at) AS next_at
    FROM v_claim_events
),
observed AS (
    SELECT s.*,
           julianday(next_at) - julianday(registered_at) AS days_to_next
    FROM sequenced s, ref
    WHERE s.registered_at <= ref.cutoff
)
SELECT claim_type,
       COUNT(*)                                                         AS claims_observed,
       SUM(CASE WHEN days_to_next <= 90 THEN 1 ELSE 0 END)              AS followed_within_90d,
       ROUND(100.0 * SUM(CASE WHEN days_to_next <= 90 THEN 1 ELSE 0 END)
                   / COUNT(*), 1)                                       AS repeat_within_90d_pct
FROM observed
GROUP BY claim_type
ORDER BY repeat_within_90d_pct DESC;
