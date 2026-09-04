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


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        ensure_directories(resolved_settings)
        init_db()
        _ensure_knowledge_base(resolved_settings)
        yield

    app = FastAPI(title=resolved_settings.app_name, lifespan=lifespan)

    app.include_router(health_router)
    app.include_router(tickets_router)
    app.include_router(drafts_router)
    app.include_router(workflow_router)
    app.include_router(knowledge_router)
    app.include_router(memory_router)

    return app
