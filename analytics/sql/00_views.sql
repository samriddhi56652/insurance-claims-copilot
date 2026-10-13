-- One row per claim, with the moment it reached each stage.
--
-- The app has no stage-history table, so each stage time is a PROXY derived from
-- rows that already exist:
--   registered      tickets.created_at
--   intake_sent     the first message logged to the claimant
--   docs_complete   the last checklist update, but ONLY if every item is verified/waived
--   recommended     the first coverage_recommendation draft
--   closed          tickets.closed_at
-- A stage that has not happened is NULL, which is what the funnel and the
-- "still open" logic rely on.

-- A TEMP view lives only for the connection that creates it, so running the
-- analytics never writes anything into the database it reads from.
DROP VIEW IF EXISTS temp.v_claim_events;

CREATE TEMP VIEW v_claim_events AS
WITH reqs AS (
    SELECT ticket_id,
           COUNT(*)                                                         AS n_items,
           SUM(CASE WHEN status IN ('verified', 'waived') THEN 1 ELSE 0 END) AS n_done,
           MAX(updated_at)                                                  AS last_update
    FROM claim_requirements
    GROUP BY ticket_id
),
sent AS (
    SELECT ticket_id, MIN(created_at) AS first_sent
    FROM claim_correspondence
    WHERE direction = 'to_claimant'
    GROUP BY ticket_id
),
rec AS (
    SELECT ticket_id, MIN(created_at) AS first_rec
    FROM drafts
    WHERE kind = 'coverage_recommendation'
    GROUP BY ticket_id
)
SELECT t.id          AS ticket_id,
       t.customer_id,
       t.claim_type,
       t.priority,
       t.lifecycle_stage,
       t.outcome,
       t.created_at  AS registered_at,
       sent.first_sent AS intake_sent_at,
       CASE WHEN reqs.n_items > 0 AND reqs.n_items = reqs.n_done
            THEN reqs.last_update END AS docs_complete_at,
       rec.first_rec AS recommended_at,
       t.closed_at
FROM tickets t
LEFT JOIN reqs ON reqs.ticket_id = t.id
LEFT JOIN sent ON sent.ticket_id = t.id
LEFT JOIN rec  ON rec.ticket_id  = t.id;
