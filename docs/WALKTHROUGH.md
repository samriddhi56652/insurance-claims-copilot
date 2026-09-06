# A claim, end to end

One real claim run through the whole system, stage by stage — what the AI drafts,
what it checks, and where a human has to step in. Every quote below is the
system's actual output on this claim, not a mock-up.

The claimant, **Jordan Blake**, has filed with this insurer three times before.
All three are closed. This is his fourth. (The fence incident is dated earlier
than some of those three — claims sit in history by when they were *filed and
closed*, not when the incident happened, and this one was reported last.)

---

## The claim

> **Claimant:** Jordan Blake · **Policy:** POL-2026-004417 · **Type:** Property Damage
> **Incident:** 12 August 2026, Salem, OR · **Estimated loss:** \$1,800
>
> *On August 12, 2026 I was reversing out of a shared driveway near my home in
> Salem and backed into my neighbour's wooden fence, damaging two fence panels
> and a post. My own vehicle was not damaged. No injuries. My neighbour was
> present and we exchanged information; no police report was filed since it was a
> minor property matter between neighbours.*

This is the one coverage situation Jordan's earlier claims haven't hit: he
damaged **someone else's** property and his own car is untouched. The right
answer is **Liability (Property Damage)**, not Collision or Comprehensive.

---

## Stage 1 / 5 — Intake

The claim passes a deterministic pre-check (does the narrative actually describe
an impact? — yes, "backed into… fence"), so it reaches the model. The AI drafts
the first reply — a request for the documents a fence-damage claim needs:

> **Confirmed facts** — Incident: August 12 2026, Salem, OR · Vehicle: no damage ·
> Property: neighbour's wooden fence (two panels & a post) damaged · No injuries,
> no police report filed · Policy: POL-2026-004417
> **Pending verification** — photographic evidence of the fence damage · a repair
> estimate for the panels & post · the neighbour's statement
> **Next actions** — request clear photos of the fence, a written repair estimate,
> and the neighbour's contact details and statement…

It also notes the likely direction — Liability, since the insured's own vehicle
wasn't touched — but the considered recommendation comes later, against verified
evidence (Stage 3).

**The history is already in the draft.** Generating this reply runs a search of
Jordan's prior claims: the draft is written with **3 prior claims** in context,
and the adjuster can also probe that history directly. His most recent:

> **PRIOR CLOSED CLAIM for this customer** — a past claim decided and closed by a
> licensed adjuster. This is a record, not an open task. Subject: *T-boned at
> 12th & Alder by a driver who ran the light.* Type: Collision · Incident:
> 2026-09-04 · Location: Portland, OR · **Adjuster decision: APPROVED.**

That history normally lives in a closed file that nobody re-reads. Here it
travels with the customer, not with the adjuster who last touched the account.

The adjuster reviews the draft, edits if needed, and clicks **Approve & Send**.
That records it as sent and opens the documents checklist.

---

## Stage 2 / 5 — Awaiting documents

Approving the intake reply seeds the **documents checklist** automatically — the
items a Property Damage claim needs, transcribed from the policy manual for that
claim type. No adjuster compiled the list.

Jordan replies:

> *Attaching photos of the damaged fence panels and post, my neighbour's contact
> details, and a repair quote from a fencing company for \$1,750. No police
> report was filed — there was no dispute about fault.*

The adjuster logs that reply against the claim, marks the photos, contact
details, and repair quote **verified**, and **waives** the police-report item
(none was filed, legitimately).

If items were still outstanding, the AI can draft a follow-up that chases
**only what's still marked needed** — not a generic "please resend everything".
On an earlier run of this claim, before the photos and estimate had arrived, that
draft read:

> Dear Jordan, thank you for the information you've already shared. To move
> forward, we still need: (1) police report status and report number, (2) a copy
> of the police report, (3) clear photographs of the damaged fence, (4) a written
> estimate or invoice for the fence repair…

No coverage opinion, no re-request of anything already verified.

When every checklist item is verified or waived, the claim advances to review.

---

## Stage 3 / 5 — Coverage review

With the file complete, the AI drafts the **coverage recommendation** — the first
point at which the system states a coverage position:

> The claim is covered under **Liability (Property Damage)**. The insured's
> vehicle was not damaged, and the loss consists solely of the neighbour's wooden
> fence panels and post that were damaged when the insured backed into the fence.
> The verified evidence — incident date, location, description of damage, and the
> neighbour's statement — confirms that the insured caused third-party property
> damage. **Collision and Comprehensive coverages do not apply.**
>
> The policy deductible applies; the adjuster will confirm the exact amount.
>
> **Next step toward settlement:** the adjuster will finalise the coverage
> decision, authorise the fence repair estimate, and arrange payment.

It names the right coverage, explains why the other two don't apply, and states
the deductible applies **without inventing a figure** — if it can't back up a
number, it says the adjuster will confirm it. It is framed as a *recommendation*
throughout.

The adjuster approves it. The claim moves to settlement — it is **not** closed
yet.

---

## Stage 4 / 5 — Settlement (the part the AI never touches)

This screen has no AI on it. The adjuster:

1. records the **coverage decision** — approve or deny, with a reason note;
2. for an approval, confirms **repair / replacement authorised** and **payment
   arranged**.

The **Close Claim** button only activates once the decision and both steps are
done. On this claim: **approved**, repair authorised, payment arranged.

---

## Stage 5 / 5 — Closed

> **Stage 5/5: Closed** — Claim closed, outcome: **APPROVED**

The outcome, the reasoning, and the verified documents are filed. A short record
is written to Jordan's customer history — same shape as the ones that resurfaced
in Stage 1: subject line, claim type (Property Damage), incident date and
location (2026-08-12, Salem OR), the adjuster's decision (**APPROVED**), the
coverage recommendation that informed it, and tags (`claim_type:Property Damage`,
`coverage:Liability`).

Crucially, that record is built from **what the adjuster actually decided**, not
from what the AI recommended — if the adjuster had overridden the recommendation,
the history would show the override. It is exactly what the next adjuster sees
automatically the next time Jordan's name comes up.

---

## What this run shows

- **The AI drafts at four points** (document request, follow-up chase, coverage
  recommendation, closing notice) and **decides at none.**
- **Customer history is automatic** — 3 prior claims surfaced before this claim's
  first draft was written.
- **The checklist and the SLA figures come from the policy documents**, not from
  the model's imagination.
- **Coverage was classified correctly** — Liability, not Collision or
  Comprehensive — with the reasoning shown.
- **The claim only closed when a human recorded the decision and the money
  moved.**

How the drafts are checked for quality — a labelled test set and an
independent AI judge — is in [`ITERATION_LOG.md`](ITERATION_LOG.md) (Phase 1) and
summarised in [`../README.md`](../README.md). The gap between this prototype and
production is in [`DESIGN_GAPS.md`](DESIGN_GAPS.md).
