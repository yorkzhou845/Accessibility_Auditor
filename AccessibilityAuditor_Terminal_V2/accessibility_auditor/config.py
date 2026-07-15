"""Runtime configuration loaded from environment variables and an optional .env file."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_env_file(path: Path) -> None:
    """Load simple KEY=VALUE entries without adding another dependency."""
    if not path.exists():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


_load_env_file(PROJECT_ROOT / ".env")


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _env_optional_int(name: str, default: Optional[int]) -> Optional[int]:
    value = os.getenv(name)
    if value is None or value.strip() == "":
        return default
    if value.strip().lower() in {"none", "null", "all"}:
        return None
    return int(value)


def _path_from_env(name: str, default: Path) -> Path:
    value = os.getenv(name)
    return Path(value).expanduser().resolve() if value else default.resolve()


OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
CHAT_MODEL = os.getenv("OLLAMA_CHAT_MODEL", "gemma3:4b")
EMBED_MODEL = os.getenv("OLLAMA_EMBED_MODEL", "embeddinggemma")
OLLAMA_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_TIMEOUT_SECONDS", "300"))

INPUT_FOLDER = _path_from_env("INPUT_DIRECTORY", PROJECT_ROOT / "input")
OUTPUT_FOLDER = _path_from_env("OUTPUT_DIRECTORY", PROJECT_ROOT / "output")
KNOWLEDGE_FOLDER = _path_from_env("KNOWLEDGE_DIRECTORY", PROJECT_ROOT / "knowledge_base")
VECTOR_CSV = _path_from_env("VECTOR_CSV_PATH", PROJECT_ROOT / "data" / "vector_store.csv")

USE_RETRIEVAL = _env_bool("USE_RETRIEVAL", True)
REBUILD_VECTOR_STORE = _env_bool("REBUILD_VECTOR_STORE", False)
RETRIEVAL_TOP_K = int(os.getenv("RETRIEVAL_TOP_K", "3"))
CHUNK_SIZE = int(os.getenv("KNOWLEDGE_CHUNK_SIZE", "1200"))

USE_LLM_FOR_SEMANTIC = _env_bool("USE_LLM_FOR_SEMANTIC", False)
RENDER_SCALE = float(os.getenv("RENDER_SCALE", "1.0"))
MAX_PAGES = _env_optional_int("MAX_PAGES", None)
MAX_IMAGES_PER_PAGE = _env_optional_int("MAX_IMAGES_PER_PAGE", 2)
MAX_HEADING_CANDIDATES = int(os.getenv("MAX_HEADING_CANDIDATES", "80"))
FAILURE_REPORT_CHAR_LIMIT = int(os.getenv("FAILURE_REPORT_CHAR_LIMIT", "1200"))

SEMANTIC_NUM_CTX = int(os.getenv("SEMANTIC_NUM_CTX", "8192"))
SEMANTIC_NUM_PREDICT = int(os.getenv("SEMANTIC_NUM_PREDICT", "2000"))
ALT_TEXT_NUM_CTX = int(os.getenv("ALT_TEXT_NUM_CTX", "4096"))
ALT_TEXT_NUM_PREDICT = int(os.getenv("ALT_TEXT_NUM_PREDICT", "250"))
TABLE_NUM_CTX = int(os.getenv("TABLE_NUM_CTX", "4096"))
TABLE_NUM_PREDICT = int(os.getenv("TABLE_NUM_PREDICT", "600"))

SYS_PROMPT = """
You are a local PDF accessibility analysis assistant.

The supported tasks are:
1. Suggested alternative text for meaningful images.
2. Suggested semantic heading structure.
3. Suggested table summaries and Markdown representations.

Do not claim that a PDF is legally compliant. Do not attempt low-level PDF repair.
Return only valid JSON for the requested schema.
""".strip()


def refresh_output_paths() -> None:
    global RENDERED_FOLDER, CROPPED_FOLDER, COMBINED_OUTPUT_JSON
    OUTPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    RENDERED_FOLDER = OUTPUT_FOLDER / "rendered_pages"
    CROPPED_FOLDER = OUTPUT_FOLDER / "cropped_images"
    RENDERED_FOLDER.mkdir(parents=True, exist_ok=True)
    CROPPED_FOLDER.mkdir(parents=True, exist_ok=True)
    COMBINED_OUTPUT_JSON = OUTPUT_FOLDER / "all_results.json"


def configure_runtime(
    *,
    input_folder: Optional[Path] = None,
    output_folder: Optional[Path] = None,
    max_pages: Optional[int] = None,
    rebuild_vector_store: Optional[bool] = None,
    use_retrieval: Optional[bool] = None,
) -> None:
    """Apply command-line overrides after module import."""
    global INPUT_FOLDER, OUTPUT_FOLDER, MAX_PAGES, REBUILD_VECTOR_STORE, USE_RETRIEVAL

    if input_folder is not None:
        INPUT_FOLDER = input_folder.expanduser().resolve()
    if output_folder is not None:
        OUTPUT_FOLDER = output_folder.expanduser().resolve()
    if max_pages is not None:
        MAX_PAGES = max_pages
    if rebuild_vector_store is not None:
        REBUILD_VECTOR_STORE = rebuild_vector_store
    if use_retrieval is not None:
        USE_RETRIEVAL = use_retrieval

    INPUT_FOLDER.mkdir(parents=True, exist_ok=True)
    KNOWLEDGE_FOLDER.mkdir(parents=True, exist_ok=True)
    VECTOR_CSV.parent.mkdir(parents=True, exist_ok=True)
    refresh_output_paths()


refresh_output_paths()
