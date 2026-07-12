"""
main.py — FastAPI application entry point.

Mounts:
  - Strawberry GraphQL router at /graphql  (GraphiQL playground included)
  - CORS middleware so Streamlit (port 8501) can call the API

Usage:
  uvicorn backend.main:app --reload --port 8000
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.config import settings          # loads .env immediately on import
from backend.database import init_db
from backend.schema import graphql_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Validate config, initialise the database, then start up."""
    # ── LLM readiness check ──────────────────────────────────────────────
    if settings.llm_ready:
        logger.info(
            "LLM configured: model=%s  temperature=%s",
            settings.llm_model,
            settings.llm_temperature,
        )
    else:
        logger.warning(
            "OPENAI_API_KEY not set or is still a placeholder value. "
            "The runWorkflow mutation will raise an error until you add "
            "a valid key to .env and restart the server."
        )

    # ── Database init ────────────────────────────────────────────────────
    await init_db()
    logger.info("Database ready at: %s", settings.database_url)
    yield
    # No explicit teardown required for SQLite POC


app = FastAPI(
    title="AI Factory API",
    description="LangGraph-powered story workflow API with Strawberry GraphQL.",
    version="0.1.0",
    lifespan=lifespan,
)

# Allow Streamlit (and any local dev origin) to reach the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount the GraphQL router
app.include_router(graphql_router, prefix="/graphql")


@app.get("/health", tags=["ops"])
async def health_check():
    return {
        "status": "ok",
        "service": "ai-factory",
        "llm_model": settings.llm_model,
        "llm_ready": settings.llm_ready,
    }
