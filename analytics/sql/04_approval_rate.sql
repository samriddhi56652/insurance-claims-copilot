-- Q4. What share of decided claims is approved, by claim type and priority?
--
-- Conditional aggregation: SUM(CASE WHEN ...) counts the approvals inside each
-- group. Groups with fewer than 5 decided claims are hidden - a percentage of
-- 3 claims looks precise and means nothing.

SELECT claim_type,
       priority,
       COUNT(*)                                                            AS decided_claims,
       SUM(CASE WHEN outcome = 'approved' THEN 1 ELSE 0 END)               AS approved,
       ROUND(100.0 * SUM(CASE WHEN outcome = 'approved' THEN 1 ELSE 0 END)
                   / COUNT(*), 1)                                          AS approval_pct
FROM v_claim_events
WHERE outcome IN ('approved', 'denied')
GROUP BY claim_type, priority
HAVING COUNT(*) >= 5
ORDER BY claim_type, priority;
