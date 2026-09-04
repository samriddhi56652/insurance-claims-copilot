# What this prototype does not do yet — and what production would take

This is a working prototype, built to prove one idea: that you can develop a
GenAI copilot **by measuring whether its output is actually good**, not by
assuming it. It runs end to end — a claim goes from first notice of loss to a
closed decision — but it is not production software.

This document is the honest gap between the two: what was deliberately left out,
why it matters, and roughly what it would take to close. Nothing here is a
surprise; every item was a conscious call for a portfolio build. The fixes that
have already been made are in [`ITERATION_LOG.md`](ITERATION_LOG.md).

---

## 1. Measuring the AI — the core idea, and where it currently stops

**What's there.** Every change to this system was driven by an evaluation
harness: a hand-labelled set of test claims (including the hard cases — suspected
fraud, a claim too vague to assess, a manipulative submission), automated rule
checks, and an AI judge that scores each draft on whether it stays grounded in
real policy facts, picks the right coverage, and never oversteps into a binding
decision. Across a documented series of fixes, the "stays grounded" score moved
from **1.1 to 1.7 out of 2**, and two classes of claim are now refused before the
model runs at all.

**The gap.**

- **Only the first draft is measured automatically.** The copilot now drafts at
  four points in a claim's life (the initial request for documents, the follow-up
  chases, the coverage recommendation, the closing notice). Only the first is in
  the automated harness. The other three are built to the same rules; the
  coverage recommendation has been hand-checked against the judge's rubric on a
  small sample (see ITERATION_LOG §3.7), but "are they *reliably* good?" needs the
  automated sweep — **~half a day** once the AI service quota allows repeated runs.
- **The adjuster's edits are thrown away.** When an adjuster edits a draft before
  approving it, the difference between what the AI wrote and what a human was
  willing to sign is the single most valuable signal for improving the system.
  Today the AI's original text is overwritten and that signal is lost. **~half a
  day** to start capturing it; a feedback loop that actually uses it is a larger
  piece of work.

---

## 2. Trust, governance, and regulatory readiness

The largest gap for anything a regulated business would run.

- **No user identity or access control.** Anyone who can reach the system can act
  on claims — including approving a coverage decision, which is the legally
  meaningful step. The approval is recorded as "approved by a licensed adjuster"
  with no actual name or licence number behind it.
  → *Basic shared login: hours. Per-adjuster accounts so each decision carries a
  real identity: ~1 day.*
- **No audit trail.** Stage changes and decisions are overwritten in place. There
  is no immutable, time-stamped record of who did what — which a regulator, an
  auditor, or a disputed claim would require.
  → *Append-only event log tied to adjuster identity: ~1–2 days (needs the
  identity work above first).*
- **Claimant input goes straight to the model.** The mandatory human review is
  the only thing between a manipulative submission and a bad draft. Acceptable
  for a prototype with a person in the loop; a production system needs input
  screening and monitoring.

---

## 3. Reliability and scale

Built to be run by one person, on one machine.

- **Single-file database.** Fine for a demo; several adjusters working at once
  would hit lock errors and intermittent failures. → *Move to a proper database
  (Postgres) for production.*
- **Customer memory is held in memory and lost on restart.** The feature is meant
  to accumulate a customer's history over time; today it silently resets.
  → *Persistent store: ~half a day.*
- **The AI service has a hard rate limit on the free tier.** A single draft can
  exceed the per-minute budget; the system retries but cannot always recover.
  → *A paid tier, or a request queue that paces calls under the limit.*

---

## 4. Capability gaps vs. a commercial claims platform

Benchmarked against three products in this space —
[Shift Technology](https://shift-technology.com/products/claims-document-decisions),
[Five Sigma (Clive)](https://fivesigmalabs.com/), and
[Lorikeet](https://www.lorikeetcx.ai/articles/best-ai-insurance-claims-fnol-2026).
All three share this prototype's core principle: **the AI assists and drafts, the
human decides coverage.** Lorikeet makes the same architectural choice this
project did — the fact-gathering / coverage-decision boundary is built into the
system, not left to a prompt instruction — and calls it "the single clearest
reason regulated carriers shortlist the platform."

Where a funded product with a team behind it goes further:

| Capability | This prototype | A commercial platform |
|---|---|---|
| Fraud / urgency detection | Rule-based pattern matching — flag or no flag | Trained models on real claims data, with risk scoring |
| Reading documents | Takes typed text only | Extracts data from police reports, photos, and PDFs |
| Coverage rules | Fixed for one set of policies | Configurable per carrier |
| Claimant contact | None — adjuster-facing only | One continuous conversation across phone, chat, email, SMS |
| Integration | Standalone application | Embeds into core claims systems (e.g. Guidewire, Duck Creek) |
| Knowledge base | 5 synthetic policy documents | Real carrier policy and procedure libraries |

None of these are oversights. They are the distance between a two-phase portfolio
build and a product with funding and a roadmap.

---

## 5. Deliberately out of scope

Named so the boundary reads as a decision, not a blind spot: a full
authentication stack, migrating the database to Postgres, hardening against
manipulative input, rate-limit engineering, multi-carrier configuration, a
claimant-facing channel, document extraction (OCR), and a model-retraining
pipeline.

---

## Smaller engineering notes (for a technical reviewer)

- Re-sending the same "approve" request runs its side effects twice — the UI
  prevents it, the close action is guarded, but the API is not fully idempotent.
- A few configuration values are defined but unused; the health check does not
  actually verify the database or the AI services are reachable.
- The knowledge-base collection name changes with the embedding provider, so
  toggling the optional Gemini key can make an already-loaded knowledge base
  appear empty until it is re-indexed.
- Database connections are committed but not explicitly closed (no pooling).
