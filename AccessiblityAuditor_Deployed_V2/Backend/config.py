"""Local configuration for the accessibility remediation backend."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_ROOT = Path(__file__).resolve().parent
load_dotenv(BACKEND_ROOT / ".env")


def _resolve_path(value: str, default: Path) -> Path:
    raw = value.strip() if value else ""
    path = Path(raw) if raw else default
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    return path.resolve()


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "gemma3:4b")
OLLAMA_EMBEDDING_MODEL = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")

VECTOR_SOURCE_CSV = _resolve_path(
    os.getenv("VECTOR_SOURCE_CSV", "data/knowledge_base.csv"),
    BACKEND_ROOT / "data" / "knowledge_base.csv",
)
VECTOR_STORE_CSV = _resolve_path(
    os.getenv("VECTOR_STORE_CSV", "data/vector_store.csv"),
    BACKEND_ROOT / "data" / "vector_store.csv",
)
VECTOR_TOP_K = max(1, int(os.getenv("VECTOR_TOP_K", "3")))

ENGINE_TIMEOUT_SECONDS = max(60, int(os.getenv("ENGINE_TIMEOUT_SECONDS", "3600")))
MAX_UPLOAD_MB = max(1, int(os.getenv("MAX_UPLOAD_MB", "100")))
