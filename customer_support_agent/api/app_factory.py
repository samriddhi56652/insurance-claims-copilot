from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from customer_support_agent.api.routers import (
    drafts_router,
    health_router,
    knowledge_router,
    memory_router,
    tickets_router,
    workflow_router,
)
from customer_support_agent.core.settings import Settings, ensure_directories, get_settings
from customer_support_agent.repositories.sqlite import init_db

logger = logging.getLogger("customer_support_agent.startup")


def _ensure_knowledge_base(settings: Settings) -> None:
    """Index the policy knowledge base on first startup.

    A fresh clone has an empty vector store, which would make every draft
    ungrounded until someone calls POST /api/knowledge/ingest by hand. This
    indexes it automatically the first time, and is a no-op on every restart
    after that. Best-effort: a failure (no network for the embedding model, a
    bad Gemini key) is logged and the app still starts.
    """
    try:
        from customer_support_agent.integrations.rag.chroma_kb import KnowledgeBaseService

        kb = KnowledgeBaseService(settings=settings)
        if kb.count() > 0:
            return
        result = kb.ingest_directory(settings.knowledge_base_path)
        logger.info(
            "Knowledge base indexed on startup: %s files / %s chunks.",
            result.get("files_indexed"),
            result.get("chunks_indexed"),
        )
    except Exception:
        logger.warning(
            "Knowledge-base auto-index skipped — drafts will be ungrounded until "
            "POST /api/knowledge/ingest is run. Reason:",
            exc_info=True,
        )


def _rebuild_customer_memory(settings: Settings) -> None:
    """Replay closed claims from SQLite back into the customer-history memory.

    The memory store (langmem) lives only in this process's RAM, so a restart
    - a redeploy, a crash, or just closing the laptop - loses it, even though
    the claims themselves are safe on disk. This rebuilds it from the claims
    already marked `closed`, using the same deterministic write path a real
    closure uses (SupportCopilot.save_claim_closure), so the rebuilt memory
    text is identical to what was originally written. No LLM call is made for
    the rebuild itself. Runs once per process start; best-effort.

    Important: this must write into the *same* SupportCopilot instance the API
    routes read from (api.dependencies.get_copilot(), @lru_cache'd) - not a
    second, throwaway one with its own empty memory store.
    """
    try:
        from customer_support_agent.api.dependencies import get_copilot
        from customer_support_agent.repositories.sqlite.drafts import DraftsRepository
        from customer_support_agent.repositories.sqlite.tickets import TicketsRepository
        from customer_support_agent.services.draft_service import DraftService

        tickets_repo = TicketsRepository()
        closed = [
            t for t in tickets_repo.list(limit=1000)
            if (t.get("lifecycle_stage") or "") == "closed"
        ]
        if not closed:
            return

        drafts_repo = DraftsRepository()
        draft_service = DraftService()
        copilot = get_copilot()  # constructs (and caches) the real singleton

        restored = 0
        for ticket in closed:
            try:
                cov = drafts_repo.latest_of_kind(ticket["id"], "coverage_recommendation")
                context_used = draft_service.parse_context_used(
                    (cov or {}).get("context_used")
                )
                copilot.save_claim_closure(
                    customer_email=ticket["customer_email"],
                    customer_company=ticket.get("customer_company"),
                    ticket=ticket,
                    coverage_rec_text=(cov or {}).get("content", ""),
                    context_used=context_used,
                )
                restored += 1
            except Exception:
                logger.warning(
                    "Memory rebuild failed for ticket_id=%s", ticket.get("id"),
                    exc_info=True,
                )
        if restored:
            logger.info(
                "Customer-history memory rebuilt from %s closed claim(s).", restored
            )
    except Exception:
        logger.warning(
            "Customer-history memory rebuild skipped (e.g. no GROQ_API_KEY yet). "
            "Reason:",
            exc_info=True,
        )


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        ensure_directories(resolved_settings)
        init_db()
        _ensure_knowledge_base(resolved_settings)
        _rebuild_customer_memory(resolved_settings)
        yield

    app = FastAPI(title=resolved_settings.app_name, lifespan=lifespan)

    app.include_router(health_router)
    app.include_router(tickets_router)
    app.include_router(drafts_router)
    app.include_router(workflow_router)
    app.include_router(knowledge_router)
    app.include_router(memory_router)

    return app
