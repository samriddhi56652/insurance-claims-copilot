"""Streamlit dashboard for insurance claims adjusters."""

from __future__ import annotations

from datetime import date
import os
from typing import Any

import requests
import streamlit as st

API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000")


st.set_page_config(page_title="Insurance Claims Copilot", layout="wide")
st.title("Insurance Claims Copilot Workbench")


@st.cache_data(ttl=10)
def fetch_tickets() -> list[dict[str, Any]]:
    response = requests.get(f"{API_BASE_URL}/api/tickets", timeout=20)
    response.raise_for_status()
    return response.json()


def fetch_draft(ticket_id: int) -> dict[str, Any] | None:
    response = requests.get(f"{API_BASE_URL}/api/drafts/{ticket_id}", timeout=20)
    if response.status_code == 404:
        return None
    response.raise_for_status()
    return response.json()


def _extract_api_error(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return response.text or response.reason or "Unknown API error"

    detail = payload.get("detail")
    if isinstance(detail, list):
        parts = []
        for item in detail:
            if isinstance(item, dict):
                loc = ".".join(str(p) for p in item.get("loc", []))
                msg = item.get("msg", "validation error")
                parts.append(f"{loc}: {msg}" if loc else msg)
            else:
                parts.append(str(item))
        return "; ".join(parts)
    if detail:
        return str(detail)
    return str(payload)


def create_ticket(payload: dict[str, Any]) -> dict[str, Any]:
    response = requests.post(f"{API_BASE_URL}/api/tickets", json=payload, timeout=20)
    if response.status_code >= 400:
        raise RuntimeError(_extract_api_error(response))
    fetch_tickets.clear()
    return response.json()


def trigger_draft(ticket_id: int) -> dict[str, Any]:
    response = requests.post(
        f"{API_BASE_URL}/api/tickets/{ticket_id}/generate-draft",
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(_extract_api_error(response))
    return response.json()["draft"]


def update_draft(draft_id: int, content: str, status: str) -> dict[str, Any]:
    response = requests.patch(
        f"{API_BASE_URL}/api/drafts/{draft_id}",
        json={"content": content, "status": status},
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(_extract_api_error(response))
    fetch_tickets.clear()
    return response.json()


def ingest_knowledge(clear_existing: bool) -> dict[str, Any]:
    response = requests.post(
        f"{API_BASE_URL}/api/knowledge/ingest",
        json={"clear_existing": clear_existing},
        timeout=60,
    )
    if response.status_code >= 400:
        raise RuntimeError(_extract_api_error(response))
    return response.json()


def search_memory(customer_id: int, query: str, limit: int = 8) -> list[dict[str, Any]]:
    response = requests.get(
        f"{API_BASE_URL}/api/customers/{customer_id}/memory-search",
        params={"query": query, "limit": limit},
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(_extract_api_error(response))
    payload = response.json()
    return payload.get("results", [])


def fetch_workflow(ticket_id: int) -> dict[str, Any]:
    response = requests.get(
        f"{API_BASE_URL}/api/tickets/{ticket_id}/workflow", timeout=20
    )
    if response.status_code >= 400:
        raise RuntimeError(_extract_api_error(response))
    return response.json()


def update_requirement(
    ticket_id: int, req_id: int, status: str, note: str
) -> dict[str, Any]:
    response = requests.patch(
        f"{API_BASE_URL}/api/tickets/{ticket_id}/requirements/{req_id}",
        json={"status": status, "note": note},
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(_extract_api_error(response))
    fetch_tickets.clear()
    return response.json()


def add_requirement(ticket_id: int, item_label: str, category: str) -> dict[str, Any]:
    response = requests.post(
        f"{API_BASE_URL}/api/tickets/{ticket_id}/requirements",
        json={"item_label": item_label, "category": category},
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(_extract_api_error(response))
    fetch_tickets.clear()
    return response.json()


def add_correspondence(
    ticket_id: int, direction: str, channel: str, body: str
) -> dict[str, Any]:
    response = requests.post(
        f"{API_BASE_URL}/api/tickets/{ticket_id}/correspondence",
        json={"direction": direction, "channel": channel, "body": body},
        timeout=20,
    )
    if response.status_code >= 400:
        raise RuntimeError(_extract_api_error(response))
    return response.json()


def generate_lifecycle_draft(ticket_id: int, kind: str) -> dict[str, Any]:
    """kind: 'followup-draft' or 'coverage-recommendation'."""
    response = requests.post(
        f"{API_BASE_URL}/api/tickets/{ticket_id}/{kind}", timeout=60
    )
    if response.status_code >= 400:
        raise RuntimeError(_extract_api_error(response))
    return response.json()["draft"]


def _compose_claim_description(
    claim_type: str,
    policy_number: str,
    incident_date: date,
    loss_location: str,
    estimated_loss_amount: float,
    narrative: str,
) -> str:
    return (
        f"Claim type: {claim_type}\n"
        f"Policy number: {policy_number.strip()}\n"
        f"Incident date: {incident_date.isoformat()}\n"
        f"Loss location: {loss_location.strip()}\n"
        f"Estimated loss amount: ${estimated_loss_amount:,.2f}\n\n"
        f"FNOL narrative:\n{narrative.strip()}"
    )


def render_context(context: dict[str, Any] | None) -> None:
    if not context:
        st.info("No context captured for this recommendation.")
        return

    if context.get("version") != 2:
        st.json(context)
        return

    signals = context.get("signals") or {}
    memory_hits = context.get("memory_hits") or []
    knowledge_hits = context.get("knowledge_hits") or []
    tool_calls = context.get("tool_calls") or []
    highlights = context.get("highlights") or {}

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Claim History Hits", signals.get("memory_hit_count", len(memory_hits)))
    c2.metric("Policy/KB Hits", signals.get("knowledge_hit_count", len(knowledge_hits)))
    c3.metric("Decision Tool Calls", signals.get("tool_call_count", len(tool_calls)))
    c4.metric(
        "Tool Errors",
        signals.get(
            "tool_error_count",
            len([call for call in tool_calls if call.get("status") != "ok"]),
        ),
    )

    sources = signals.get("knowledge_sources") or []
    if sources:
        st.caption(f"Policy/regulation sources: {', '.join(sources)}")

    if any(highlights.get(key) for key in ("memory", "knowledge", "tools")):
        st.markdown("**Highlights**")
        for label, key in (
            ("Claim History", "memory"),
            ("Policy & Regulations", "knowledge"),
            ("Tools", "tools"),
        ):
            values = [item for item in (highlights.get(key) or []) if item]
            if values:
                st.write(f"{label}:")
                for item in values:
                    st.write(f"- {item}")

    if tool_calls:
        st.markdown("**Tool Calls**")
        rows = [
            {
                "Tool": call.get("tool_name", "unknown"),
                "Status": call.get("status", "unknown"),
                "Summary": call.get("summary") or call.get("output_text", ""),
            }
            for call in tool_calls
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)

        for index, call in enumerate(tool_calls, start=1):
            title = (
                f"{index}. {call.get('tool_name', 'unknown')} "
                f"({call.get('status', 'unknown')})"
            )
            with st.expander(title):
                st.caption("Arguments")
                st.json(call.get("arguments") or {})
                output = call.get("output")
                if output:
                    st.caption("Structured Output")
                    st.json(output)
                else:
                    st.caption("Raw Output")
                    st.code(call.get("output_text", ""), language="text")

    with st.expander("Detailed Claim History Hits"):
        st.json(memory_hits)
    with st.expander("Detailed Policy/KB Hits"):
        st.json(knowledge_hits)

    errors = context.get("errors") or []
    if errors:
        with st.expander("Context Errors"):
            for err in errors:
                st.error(err)


STAGE_META: dict[str, dict[str, str]] = {
    "intake": {
        "label": "Intake - drafting the first response",
        "icon": "1/4",
    },
    "awaiting_documents": {
        "label": "Awaiting documents from the claimant",
        "icon": "2/4",
    },
    "review_ready": {
        "label": "Ready for coverage review",
        "icon": "3/4",
    },
    "resolved": {
        "label": "Resolved",
        "icon": "4/4",
    },
}

REQ_STATUSES = ["needed", "received", "verified", "waived"]
DRAFT_KIND_LABEL = {
    "intake_request": "Intake response",
    "followup_request": "Follow-up request",
    "coverage_recommendation": "Coverage recommendation",
}


def render_draft_block(
    ticket: dict[str, Any],
    draft: dict[str, Any],
    approve_label: str,
    request_label: str,
) -> None:
    """Editable draft + approve / request-info actions + the context panel."""
    kind = draft.get("kind") or "intake_request"
    status = draft.get("status")
    if status == "failed":
        st.warning(
            "Latest draft attempt failed. Check the model/key configuration and retry."
        )

    # Already acted on - show it read-only, no action buttons (re-approving would
    # log a duplicate "sent" entry).
    if status in ("accepted", "discarded"):
        note = "approved and sent" if status == "accepted" else "set aside"
        st.markdown(f"**{DRAFT_KIND_LABEL.get(kind, 'Draft')}** — {note}")
        st.write(draft["content"])
        with st.expander("Context used for this draft"):
            render_context(draft.get("context_used"))
        return

    st.markdown(f"**{DRAFT_KIND_LABEL.get(kind, 'Draft')}** (for adjuster review)")
    edited = st.text_area(
        "Edit before you act on it",
        value=draft["content"],
        height=240,
        key=f"draft_content_{draft['id']}",
    )
    st.caption("AI drafts; a licensed adjuster makes every decision and every send.")

    col_a, col_b = st.columns(2)
    with col_a:
        if st.button(approve_label, use_container_width=True, key=f"approve_{draft['id']}"):
            try:
                update_draft(draft["id"], edited, "accepted")
                st.session_state.pop(f"draft_{ticket['id']}", None)
                st.rerun()
            except Exception as exc:
                st.error(f"Approve failed: {exc}")
    with col_b:
        if st.button(request_label, use_container_width=True, key=f"reject_{draft['id']}"):
            try:
                update_draft(draft["id"], edited, "discarded")
                st.session_state.pop(f"draft_{ticket['id']}", None)
                st.rerun()
            except Exception as exc:
                st.error(f"Action failed: {exc}")

    with st.expander("Context used for this draft"):
        render_context(draft.get("context_used"))


def render_checklist(ticket_id: int, workflow: dict[str, Any]) -> None:
    requirements = workflow.get("requirements") or []
    counts = workflow.get("requirement_counts") or {}
    done = counts.get("verified", 0) + counts.get("waived", 0)
    total = counts.get("total", 0)
    st.markdown(f"**Documents checklist** — {done}/{total} cleared")
    if total:
        st.progress(done / total)

    for item in requirements:
        req_id = item["id"]
        cols = st.columns([4, 2, 3, 1])
        cols[0].markdown(
            f"{item['item_label']}  \n"
            f"<span style='color:#888;font-size:0.8em'>{item['category']}</span>",
            unsafe_allow_html=True,
        )
        status = cols[1].selectbox(
            "status",
            REQ_STATUSES,
            index=REQ_STATUSES.index(item.get("status", "needed")),
            key=f"req_status_{req_id}",
            label_visibility="collapsed",
        )
        note = cols[2].text_input(
            "note",
            value=item.get("note") or "",
            key=f"req_note_{req_id}",
            label_visibility="collapsed",
            placeholder="note (e.g. received 9/5)",
        )
        if cols[3].button("Save", key=f"req_save_{req_id}"):
            try:
                update_requirement(ticket_id, req_id, status, note)
                st.rerun()
            except Exception as exc:
                st.error(f"Save failed: {exc}")

    with st.expander("Add a checklist item"):
        new_label = st.text_input("Item", key=f"new_req_label_{ticket_id}")
        new_cat = st.selectbox(
            "Type", ["document", "information"], key=f"new_req_cat_{ticket_id}"
        )
        if st.button("Add item", key=f"new_req_add_{ticket_id}"):
            if new_label.strip():
                try:
                    add_requirement(ticket_id, new_label.strip(), new_cat)
                    st.rerun()
                except Exception as exc:
                    st.error(f"Add failed: {exc}")


def render_correspondence(ticket_id: int, workflow: dict[str, Any]) -> None:
    thread = workflow.get("correspondence") or []
    st.markdown("**Correspondence log**")
    if not thread:
        st.caption("Nothing logged yet.")
    for entry in thread:
        who = (
            "Sent to claimant"
            if entry["direction"] == "to_claimant"
            else "From claimant"
        )
        st.markdown(
            f"**{who}** - {entry['channel']} - {entry['created_at'][:16]}  \n{entry['body']}"
        )
        st.divider()

    with st.expander("Log a claimant reply / a call"):
        direction = st.radio(
            "Direction",
            ["from_claimant", "to_claimant"],
            key=f"corr_dir_{ticket_id}",
            horizontal=True,
        )
        channel = st.selectbox(
            "Channel", ["email", "phone", "portal", "note"], key=f"corr_chan_{ticket_id}"
        )
        body = st.text_area("What was said / sent", key=f"corr_body_{ticket_id}")
        if st.button("Add to log", key=f"corr_add_{ticket_id}"):
            if body.strip():
                try:
                    add_correspondence(ticket_id, direction, channel, body.strip())
                    st.rerun()
                except Exception as exc:
                    st.error(f"Log failed: {exc}")


with st.sidebar:
    st.subheader("API Settings")
    st.code(API_BASE_URL)

    if st.button("Ingest Policy & Regulation KB", use_container_width=True):
        try:
            result = ingest_knowledge(clear_existing=False)
            st.success(
                f"Indexed {result['files_indexed']} files / {result['chunks_indexed']} chunks"
            )
        except Exception as exc:
            st.error(f"Knowledge ingest failed: {exc}")


st.subheader("Register Claim (FNOL)")
with st.form("create_ticket_form"):
    col1, col2 = st.columns(2)
    with col1:
        customer_email = st.text_input("Claimant Email", placeholder="alex@acme.io")
        customer_name = st.text_input("Claimant Name", placeholder="Alex Rivera")
        customer_company = st.text_input("Insured Organization (Optional)", placeholder="Acme Logistics")

    with col2:
        priority = st.selectbox("Severity", ["low", "medium", "high", "urgent"], index=1)
        claim_type = st.selectbox(
            "Claim Type (Auto)",
            [
                "Collision",
                "Comprehensive",
                "Theft",
                "Glass Damage",
                "Bodily Injury",
                "Property Damage",
                "Other",
            ],
            index=0,
        )
        policy_number = st.text_input("Policy Number", placeholder="POL-2026-001234")

    col3, col4 = st.columns(2)
    with col3:
        incident_date = st.date_input("Incident Date")
        loss_location = st.text_input("Loss Location", placeholder="San Jose, CA")
    with col4:
        estimated_loss_amount = st.number_input(
            "Estimated Loss Amount (USD)",
            min_value=0.0,
            step=100.0,
            format="%.2f",
            value=0.0,
        )

    subject = st.text_input("Claim Summary")
    description = st.text_area("FNOL Description", height=140)
    auto_generate = st.checkbox("Auto-generate coverage recommendation", value=True)

    submitted = st.form_submit_button("Register Claim")
    if submitted:
        if not customer_email or not subject or not description:
            st.warning("Claimant email, claim summary, and FNOL description are required.")
        elif not policy_number.strip() or not loss_location.strip():
            st.warning("Policy number and loss location are required.")
        elif len(subject.strip()) < 3:
            st.warning("Claim summary must be at least 3 characters.")
        elif len(description.strip()) < 10:
            st.warning("FNOL description must be at least 10 characters.")
        else:
            try:
                claim_description = _compose_claim_description(
                    claim_type=claim_type,
                    policy_number=policy_number,
                    incident_date=incident_date,
                    loss_location=loss_location,
                    estimated_loss_amount=float(estimated_loss_amount),
                    narrative=description,
                )
                created = create_ticket(
                    {
                        "customer_email": customer_email,
                        "customer_name": customer_name or None,
                        "customer_company": customer_company or None,
                        "subject": subject,
                        "description": claim_description,
                        "claim_type": claim_type,
                        "priority": priority,
                        "auto_generate": auto_generate,
                    }
                )
                st.success(f"Claim #{created['id']} registered")
            except Exception as exc:
                st.error(f"Claim registration failed: {exc}")

st.divider()
st.subheader("Claims")

try:
    tickets = fetch_tickets()
except Exception as exc:
    tickets = []
    st.error(f"Could not load claims: {exc}")

if not tickets:
    st.info("No claims yet. Register one above.")
else:
    labels = [
        f"#{t['id']} | {t.get('lifecycle_stage', t['status'])} | "
        f"{t['customer_email']} | {t['subject']}"
        for t in tickets
    ]
    selected_label = st.selectbox("Select claim", labels)
    selected_ticket = tickets[labels.index(selected_label)]

    stage = selected_ticket.get("lifecycle_stage") or "intake"
    meta = STAGE_META.get(stage, {"label": stage, "icon": "-"})
    ticket_id = selected_ticket["id"]

    c1, c2 = st.columns([1, 1])
    with c1:
        st.markdown("**Claimant**")
        st.write(selected_ticket["customer_email"])
        st.write(selected_ticket.get("customer_name") or "-")
        st.write(selected_ticket.get("customer_company") or "-")

    with c2:
        st.markdown("**Claim**")
        st.write(f"Type: {selected_ticket.get('claim_type') or '-'}")
        st.write(f"Severity: {selected_ticket['priority']}")
        st.write(selected_ticket["description"])

    st.info(f"**Stage {meta['icon']}:** {meta['label']}")

    draft_data = st.session_state.get(f"draft_{ticket_id}") or fetch_draft(ticket_id)
    workflow_data: dict[str, Any] | None = None
    if stage != "intake":
        try:
            workflow_data = fetch_workflow(ticket_id)
        except Exception as exc:
            st.error(f"Could not load the claim workflow: {exc}")

    # ---- Stage: intake -----------------------------------------------------
    if stage == "intake":
        if st.button("Generate / Regenerate Intake Response", use_container_width=True):
            try:
                st.session_state[f"draft_{ticket_id}"] = trigger_draft(ticket_id)
                st.rerun()
            except Exception as exc:
                st.error(f"Generation failed: {exc}")
        if draft_data and draft_data.get("kind", "intake_request") == "intake_request":
            render_draft_block(
                selected_ticket,
                draft_data,
                approve_label="Approve & Send to Claimant",
                request_label="Discard & Redraft",
            )
            st.caption(
                "Approving sends this to the claimant and opens the documents "
                "checklist for this claim type."
            )

    # ---- Stage: awaiting_documents ---------------------------------------
    elif stage == "awaiting_documents":
        if workflow_data:
            render_checklist(ticket_id, workflow_data)
            st.divider()
            render_correspondence(ticket_id, workflow_data)
            st.divider()

        st.markdown("**Chase the outstanding items**")
        if st.button("Draft Follow-up Request", use_container_width=True):
            try:
                st.session_state[f"draft_{ticket_id}"] = generate_lifecycle_draft(
                    ticket_id, "followup-draft"
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Follow-up draft failed: {exc}")
        if draft_data and draft_data.get("kind") == "followup_request":
            render_draft_block(
                selected_ticket,
                draft_data,
                approve_label="Approve & Send to Claimant",
                request_label="Discard",
            )
        st.caption(
            "When every checklist item is verified or waived, the claim moves to "
            "coverage review automatically."
        )

    # ---- Stage: review_ready --------------------------------------------
    elif stage == "review_ready":
        if workflow_data:
            with st.expander("Verified checklist & correspondence", expanded=False):
                render_checklist(ticket_id, workflow_data)
                st.divider()
                render_correspondence(ticket_id, workflow_data)

        st.markdown("**Coverage review**")
        if st.button("Generate Coverage Recommendation", use_container_width=True):
            try:
                st.session_state[f"draft_{ticket_id}"] = generate_lifecycle_draft(
                    ticket_id, "coverage-recommendation"
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Coverage recommendation failed: {exc}")
        if draft_data and draft_data.get("kind") == "coverage_recommendation":
            render_draft_block(
                selected_ticket,
                draft_data,
                approve_label="Approve — Resolve Claim",
                request_label="Request Info (reopen documents)",
            )
            st.caption(
                "Approving this resolves the claim and files the outcome in "
                "customer memory."
            )

    # ---- Stage: resolved ------------------------------------------------
    else:
        st.success("This claim is resolved.")
        if workflow_data:
            with st.expander("Checklist & correspondence", expanded=False):
                render_checklist(ticket_id, workflow_data)
                st.divider()
                render_correspondence(ticket_id, workflow_data)
        if draft_data:
            st.markdown("**Final coverage recommendation**")
            st.write(draft_data["content"])
            with st.expander("Context used for this draft"):
                render_context(draft_data.get("context_used"))

    st.divider()
    st.markdown("**Claim History Probe**")
    probe_query = st.text_input(
        "Search claim history by entities/issues",
        value=f"{selected_ticket['subject']} {selected_ticket['priority']}",
        key=f"memory_probe_{selected_ticket['id']}",
    )
    if st.button("Run Claim History Probe", use_container_width=True):
        try:
            hits = search_memory(selected_ticket["customer_id"], probe_query)
            if not hits:
                st.info("No relevant claim history hits for this query yet.")
            else:
                st.success(f"Found {len(hits)} claim history hit(s).")
                for idx, hit in enumerate(hits, start=1):
                    with st.expander(f"Claim history hit {idx}"):
                        st.write(hit.get("memory", ""))
                        metadata = hit.get("metadata") or {}
                        if metadata:
                            st.caption("Metadata")
                            st.json(metadata)
        except Exception as exc:
            st.error(f"Claim history probe failed: {exc}")
