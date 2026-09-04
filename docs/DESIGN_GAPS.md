# Design Gaps & Next Steps

A deliberate catalogue of what this system does **not** do well yet, found in a
full-codebase review. Nothing here is a surprise — each item is a conscious
trade-off for a prototype, listed with the fix and its rough cost.

Priority is for **"before real adjusters or a public URL touch it"**, not for a
local demo.

---

## Tier 1 — blocks a real deployment

### 1. No authentication or authorisation
The API listens on all interfaces with no login, no API key, no notion of *which
adjuster*. Anyone who reaches it can create claims, **approve** them (the legally
meaningful action), read every customer's memory, and wipe the knowledge base.
The approval record even hardcodes *"approved by licensed adjuster"* — no name, no
licence number.
**Fix:** shared bearer token first (~2 h), then per-adjuster accounts so the
approval carries a real identity (~half a day). Network boundary (Tailscale /
Cloudflare Access) in front regardless.

### 2. Customer memory is RAM-only
`CustomerMemoryStore` always builds a LangGraph `InMemoryStore`. The resolution
notes written on approval — filed under both the claimant and their company — are
**lost on every restart / redeploy / crash**. The feature is meant to accumulate
over time; it silently can't. It also only works with exactly one backend process.
**Fix:** rebuild the index from `drafts WHERE status='accepted'` on startup (small,
no new deps), or swap in a disk-backed store. The source data is safe on disk
either way.

### 3. SQLite write concurrency
Background draft generation writes while API requests write. SQLite locks the whole
file; there's no `busy_timeout`, no WAL mode, no retry — concurrent users will see
random 500s. A check-then-insert in `create_or_get` can also race two new-customer
requests into a `UNIQUE` violation.
**Fix:** `PRAGMA busy_timeout` + WAL (~15 min); `INSERT OR IGNORE` then read
(~15 min). Postgres for a real deployment.

### 4. ~~The plan-lookup tool returns fabricated data~~ — FIXED (2026-09-03)
`lookup_customer_plan` derived a "plan tier" and "SLA" from a hash of the email
and handed it to the model as fact; the eval showed it leaking into 7/10 drafts.
**Resolved:** deleted and replaced with `get_claim_sla` (real SLA constant from
the KB) and `assess_claim_priority` (rule check against the FNOL escalation
triggers). SLA standards are also now injected as fixed prompt context. See
`docs/ITERATION_LOG.md` §1.5.

---

## Tier 2 — will cause confusing bugs under load

- **DB connections are never closed** — `with connect()` commits but doesn't close;
  no pooling. Latent handle leak.
- **`except Exception: pass`** around the memory save on approval — a broken memory
  system fails completely silently. Log it.
- **Frontend timeout < backend work** — Streamlit's draft call times out at 60 s;
  a slower generation shows a false failure while the server finishes and saves.
- **LLM rate limits — backoff added, not solved (2026-09-03).** A Groq `429`
  used to leave `generate_draft` as a raw HTTP `500`. Now `ChatGroq` runs with
  `max_retries=5` (SDK exponential backoff honouring `Retry-After`), and the
  manual endpoint returns a clean `503` if retries are exhausted.
  **The hard number (measured 2026-09-03):** the free tier is **8,000 tokens /
  minute**. The old agentic draft — system prompt + KB context + 2-3 agent tool
  rounds + final generation — was **~10-15k tokens in a ~10 s burst**, over budget
  on its own. The agent→direct-call refactor (ITERATION_LOG §1.11) cut a draft to
  **~4k tokens / ~6 s**, so a draft now fits one minute's budget from a cold
  start — but a full 14-claim eval run still exhausts the day's headroom and then
  throttles hard, and `max_retries` does not rescue it (the SDK sees a ~60 s
  Retry-After and gives up). The real fix is a request queue that paces calls
  under the TPM limit, or a paid tier. Retry is the floor, not the ceiling.

### Findings from the evaluation (see `docs/ITERATION_LOG.md` §1.4)

- **Groundedness** — the model fabricates SLA/timeline figures and process
  details absent from retrieved context. Fixes: always inject a curated SLA
  snippet into the prompt (it's needed for every draft but rarely retrieved);
  add a prompt rule forbidding unsourced specific numbers.
- **Stub-tool contamination** — `lookup_customer_plan`'s fabricated plan/SLA
  data appears in most drafts as fact (this is Tier-1 item 4, now with evidence).
- **Insufficient-information handling** — ~~the model requests missing fields but
  still commits to a coverage guess~~ FIXED (2026-09-03): a deterministic intake
  gate (`intake_check.py`) returns a fixed reply for claims with no impact
  detail; the model never runs. Also neutralises pure-injection inputs.

---

## Tier 3 — rough edges

- **Chroma collection name flips with the Gemini key** (`support_kb_gemini` vs
  `support_kb`). Toggle the key and the ingested KB appears to vanish.
- **`GET /api/drafts/{ticket_id}` vs `PATCH /api/drafts/{draft_id}`** — same path,
  different ID meaning.
- **Approving is not idempotent at the API** — the Streamlit UI now hides the
  approve button once a draft is `accepted`, but a direct `PATCH` re-accepting a
  `coverage_recommendation` still re-resolves the ticket, re-writes the memory
  note, and logs a duplicate "sent" correspondence row. Needs an
  already-accepted guard in `update_draft_route`.
- **Dead config** — `openai_api_key`, `dashboard_api_url`, `enable_local_embeddings`,
  `chroma_mem0_dir` are defined and used nowhere.
- **`/health` is static** — checks nothing (DB, Chroma, model reachability).
- **Prompt injection** — the claimant's `description` goes verbatim into the LLM
  prompt. Human-in-the-loop is the only mitigation today.

---

## Claim workflow — mostly built (Phase 2), gaps remain

The two-state "registered → resolved" model is gone (ITERATION_LOG Phase 2). A
claim now has a real lifecycle, a per-claim documents checklist, a correspondence
log, and three kinds of draft (intake / follow-up / coverage recommendation).
What is still missing:

- **No email integration.** "Send to claimant" is manual — an approved draft is
  logged as sent and the adjuster records the reply by hand. Real outbound email
  (and inbound capture) is a separate build and deliberately out of scope for a
  portfolio project.
- **The Phase 2 drafts are unevaluated.** `followup_request` and
  `coverage_recommendation` have no labelled eval cases and no judge pass yet —
  they lean entirely on the human review every draft gets. ~half a day to close
  once the Groq quota allows repeated runs.
- **Checklist seeding keys off the claimant-stated claim type**, not the coverage
  the adjuster actually determines. The adjuster can add/waive items, but a
  mis-stated type produces a slightly wrong starting list.
- **Stage transitions are not audited.** `lifecycle_stage` is overwritten in
  place; there is no history of when a claim moved between stages or who moved it.

---

## Explicitly out of scope for this project

Full auth stack, Postgres migration, prompt-injection hardening, rate limiting,
multi-tenancy, real claimant email/portal. Called out here so the boundary is a
decision, not an oversight.
