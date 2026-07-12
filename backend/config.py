"""
config.py — Centralised settings loaded from .env via python-dotenv.

Usage (anywhere in the backend):
    from backend.config import settings
    key = settings.groq_api_key
"""
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from the project root (one level above the backend/ package)
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(dotenv_path=_env_path, override=False)


class Settings:
    # ── LLM (Groq) ───────────────────────────────────────────
    groq_api_key: str   = os.getenv("GROQ_API_KEY", "")
    llm_model: str      = os.getenv("LLM_MODEL", "llama-3.3-70b-versatile")
    llm_temperature: float = float(os.getenv("LLM_TEMPERATURE", "0.4"))

    # ── Database ─────────────────────────────────────────────
    database_url: str = os.getenv(
        "DATABASE_URL", "sqlite+aiosqlite:///./aifactory.db"
    )

    # ── Backend ───────────────────────────────────────────────
    api_host: str = os.getenv("API_HOST", "127.0.0.1")
    api_port: int = int(os.getenv("API_PORT", "8000"))

    @property
    def llm_ready(self) -> bool:
        """True when a Groq API key is present and looks valid (starts with gsk_)."""
        return bool(self.groq_api_key and self.groq_api_key.startswith("gsk_"))


settings = Settings()
