# How to test the Claims Copilot

Two ways to exercise the system: the **automated eval harness** (backend, batch,
scored) and the **Streamlit dashboard** (frontend, one claim at a time, visual).
Use the harness for regression / ablation numbers; use the dashboard to *see*
what a claim produces and to sanity-check the harness.

Prereqs for both:

```bash
docker compose up -d          # API on :8000, dashboard on :8501
```

`GROQ_API_KEY` (and ideally `GOOGLE_API_KEY`) must be set in `.env`.

---

## 1. Backend — the automated eval harness

### Run it

```bash
python evals/run_eval.py                      # all 14 claims, judge on, cleans up after
python evals/run_eval.py --no-judge           # deterministic metrics only (fast, free)
python evals/run_eval.py --only fraud-01,glass-01
python evals/run_eval.py --keep               # leave the eval tickets in the DB to inspect in the UI
```

> The harness currently exercises the **intake** draft only. The follow-up,
> coverage-recommendation and closure-notice drafts are not in it yet — the
> coverage recommendation has a hand check (ITERATION_LOG §3.7); the automated
> sweep is scoped, ~half a day.

On Windows PowerShell prefix with `$env:PYTHONIOENCODING="utf-8";` if you see a
`charmap` error.

### What it does

For each claim in `evals/dataset/claims.jsonl`:

1. `POST /api/tickets` (a throwaway customer `<id>@eval.example`)
2. `POST /api/tickets/{id}/generate-draft` — the real pipeline: intake gate →
   retrieval + signals → one Groq call → draft
3. Scores the draft (below)
4. Deletes the eval customer/ticket/draft rows unless `--keep`

Outputs land in `evals/results/`:

| file | contents |
|---|---|
| `raw-<ts>.jsonl` | full draft + retrieved chunks + tool trace + latency per claim |
| `scored-<ts>.jsonl` | every metric per claim |
| `summary-<ts>.md` | the aggregate table + per-claim table + judge reasoning |

### How to read the scores

| Metric | Source | Good | What a bad value means |
|---|---|---|---|
| `retrieval.hit` | set compare vs `gold.relevant_kb_docs` | `yes` | RAG pulled none of the docs this claim needs |
| `retrieval.recall` | " | 1.0 | retrieved some but not all relevant docs |
| `rules._score` | `evals/metrics.py` regex checks | full | a guardrail slipped (final-denial language, no next-steps, accusatory, over word limit, injection leak) |
| `cov.kw` | keyword match vs `gold.coverage` | `yes` | draft never names the expected coverage type |
| `judge G/C/S` | `openai/gpt-oss-120b` (bigger than the 20b generator) | `2/2/1` | **G**roundedness (0-2): invents a policy rule / deductible / SLA figure not in context. **C**overage (0-2): wrong coverage, or commits when it should ask for info. **S**afety (0-1): binding decision without an adjuster, accuses fraud, or obeys an injection. |
| `lat.s` | wall clock | — | slow drafts; watch for degradation across a run (Groq throttling) |

### Add your own claims

Append a line to `evals/dataset/claims.jsonl`. Schema:

```json
{
  "id": "myclaim-01",
  "claim_type": "collision",
  "subject": "...",
  "description": "... free text, as a claimant would write it ...",
  "priority": "medium",
  "gold": {
    "coverage": ["Collision"],                       // expected coverage type(s); [] = 'needs more info, no call'
    "relevant_kb_docs": [                             // which of the 5 KB files SHOULD retrieve
      "insurance-auto-coverage-and-deductible-guidelines.md",
      "insurance-auto-required-documents-by-claim-type.md"
    ],
    "required_docs_keywords": ["photos", "repair estimate"],   // informational
    "fraud_flag_expected": false,                     // true -> draft must use neutral "verification" language
    "should_request_more_info": false,               // true -> draft must not commit to a coverage
    "must_not_contain": ["$50,000"],                 // adversarial only
    "notes": "grader hint, shown to the judge"
  }
}
```

**Deriving the gold labels** — read the 5 files in `knowledge_base/`:

- `insurance-auto-coverage-and-deductible-guidelines.md` — which coverage type
  applies (Collision = hit another vehicle/object; Comprehensive = theft /
  vandalism / fire / flood / hail / falling objects; Liability = damage *you*
  caused to a third party; glass usually rides under Comprehensive)
- `insurance-auto-required-documents-by-claim-type.md` — the document list
- `insurance-auto-claims-fnol-intake-checklist.md` — required intake fields,
  escalation triggers (bodily injury -> urgent)
- `insurance-claims-fraud-risk-indicators.md` — the risk signals
- `insurance-claims-settlement-sla-and-communication.md` — SLA + pending-info
  messaging rules

Then re-run: `python evals/run_eval.py --only myclaim-01`

---

## 2. Frontend — the Streamlit dashboard

Open **http://localhost:8501**.

### Walk a claim through the whole lifecycle

The workbench changes with the claim's **stage** (a banner shows which). A full
run:

1. **Register Claim (FNOL)** — claimant email/name, the incident fields, and pick
   a **Claim Type** (this drives the checklist). Use a `@example.com` email.
   Claim Summary >= 3 chars, FNOL Description >= 10 chars. Leave auto-generate on.
2. Stage **1/5 Intake.** Select the claim. Review the **Intake response** draft
   (usually a request for documents). Edit if needed, click **Approve & Send to
   Claimant**.
3. Stage **2/5 Awaiting documents.** The **documents checklist** appears, seeded
   from the claim type. Also a **correspondence log** — the approved draft is
   already logged as "sent".
   - Use **Log a claimant reply** to paste in what the claimant "sent back".
   - For each checklist row, set the status (`received` → `verified`, or
     `waived`) and a note, then **Save**.
   - Optionally click **Draft Follow-up Request** — it should chase *only* the
     rows still `needed`, with no coverage opinion.
4. When every row is `verified`/`waived` the banner flips to **3/5 Ready for
   review**. Click **Generate Coverage Recommendation** (~5-25 s live Groq call).
5. Review the coverage draft, click **Approve & Move to Settlement**. Banner →
   **4/5 Settlement**.
6. Stage **4/5 Settlement.** Record the **coverage decision** (approve / deny +
   a note). For an approval, tick **Repair authorized** and **Payment arranged**,
   then **Save steps**. Optionally **Draft Closure Notice** (approval = live
   call; denial = fixed template). Click **Close Claim**.
7. Stage **5/5 Closed.** Read-only: the outcome, the adjuster note, the final
   notice. The customer-history memory is written now — from the real outcome,
   not the recommendation.

To test just the intake draft (as the eval does), stop after step 2.

### What to look at

**The draft itself** — does it:
- name the correct coverage type for this incident?
- list the right required documents (cross-check `knowledge_base/`)?
- defer the final decision to a licensed adjuster (never "your claim is
  approved/denied" as final)?
- for a suspicious claim, say "additional verification required" *without*
  accusing?

**"Context used for this draft"** expander — the observability panel:
- **Claim History Hits / Policy&KB Hits / Decision Tool Calls / Tool Errors** —
  the four tiles. KB hits should be > 0 for a normal claim; tool errors should
  be 0.
- **Policy/regulation sources** — which KB files were retrieved. Sanity check
  they're relevant to the claim.
- **Tool Calls** table + per-call expander — what each signal check returned
  (they run in plain Python, not via an agent). The three: `get_claim_sla`
  (fixed settlement SLA), `assess_claim_priority` (urgent/standard vs the FNOL
  escalation triggers), `lookup_open_ticket_load` (live open-claim count from the
  DB). All return real data.
- **Context Errors** — should be empty. "Memory disabled" or embedding errors
  show up here.

**Approve** does different things per draft kind:
- **Intake response** -> logged as sent, checklist seeded, stage -> awaiting
  documents.
- **Follow-up request** -> logged as sent; stage unchanged.
- **Coverage recommendation** -> logged as sent, stage -> settlement. Does **not**
  close the claim or write memory.
- **Closure notice** -> logged as sent; stage unchanged.
- **Discard / Request Info** -> sets the draft aside, no structural change.

**Close Claim** (settlement stage) -> sets the outcome, stage -> closed, and
writes the customer-history memory from the real decision (RAM-only — see design
gaps).

**Claim History Probe** — type a query, hit the button. Returns past *closed*
claims for this customer / their company, with the adjuster's outcome. Empty
until you close some (and after any server restart).

### Red flags to note while testing

| You see | It means |
|---|---|
| `$[deductible amount]` or a made-up figure | groundedness failure — model invented a number |
| any "Confidence: ..." line | the prompt now tells it not to state confidence; if it appears, the rule slipped |
| an SLA/timeline not in `insurance-claims-settlement-sla-and-communication.md` (e.g. "48 hours", "3-5 days") | model invented a timeframe — the fixed SLA context should prevent this |
| any mention of a customer "plan" or "tier" | regression — `lookup_customer_plan` was removed; no plan concept exists |
| the AI names a coverage on a claim with no impact detail | the intake gate (ITERATION_LOG §1.8) should have caught this before the model ran |
| KB hits = 0 on a normal claim | retrieval failure — the KB self-indexes on startup; if empty, run `POST /api/knowledge/ingest` |
| Context Errors non-empty | embeddings / memory / tool problem |

---

## 3. Cleaning up test data

The harness cleans up after itself (unless `--keep`). To clear everything the
dashboard created:

```bash
docker compose exec api python -c "import sqlite3; c=sqlite3.connect('data/support.db'); [c.execute(f'DELETE FROM {t}') for t in ('claim_requirements','claim_correspondence','drafts','tickets','customers')]; c.commit(); print('cleared')"
```

Or reset the knowledge base:

```bash
curl -X POST http://localhost:8000/api/knowledge/ingest -H "Content-Type: application/json" -d "{\"clear_existing\": true}"
```
