"""Local CSV-backed semantic retrieval using embeddings from Ollama."""

from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List

from . import config as cfg
from .ollama_client import embed_texts


_VECTOR_STORE_READY = False


@dataclass(frozen=True)
class KnowledgeChunk:
    chunk_id: str
    source: str
    text: str


def _chunk_text(text: str, max_chars: int) -> List[str]:
    paragraphs = [" ".join(part.split()) for part in text.split("\n\n")]
    paragraphs = [part for part in paragraphs if part]
    chunks: List[str] = []
    current = ""

    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(paragraph), max_chars):
                chunks.append(paragraph[start : start + max_chars])
            continue

        candidate = paragraph if not current else f"{current}\n\n{paragraph}"
        if len(candidate) <= max_chars:
            current = candidate
        else:
            chunks.append(current)
            current = paragraph

    if current:
        chunks.append(current)

    return chunks


def load_knowledge_chunks(folder: Path) -> List[KnowledgeChunk]:
    chunks: List[KnowledgeChunk] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".md", ".txt"}:
            continue
        relative = path.relative_to(folder).as_posix()
        text = path.read_text(encoding="utf-8", errors="replace")
        for index, chunk_text in enumerate(_chunk_text(text, cfg.CHUNK_SIZE), start=1):
            chunks.append(
                KnowledgeChunk(
                    chunk_id=f"{relative}#{index}",
                    source=relative,
                    text=chunk_text,
                )
            )
    return chunks


def _knowledge_is_newer(folder: Path, csv_path: Path) -> bool:
    if not csv_path.exists():
        return True
    csv_mtime = csv_path.stat().st_mtime
    return any(
        path.is_file()
        and path.suffix.lower() in {".md", ".txt"}
        and path.stat().st_mtime > csv_mtime
        for path in folder.rglob("*")
    )


def build_vector_store(folder: Path | None = None, csv_path: Path | None = None) -> int:
    folder = folder or cfg.KNOWLEDGE_FOLDER
    csv_path = csv_path or cfg.VECTOR_CSV
    chunks = load_knowledge_chunks(folder)

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    if not chunks:
        csv_path.write_text("chunk_id,source,text,embedding\n", encoding="utf-8")
        return 0

    embeddings = embed_texts(chunk.text for chunk in chunks)
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["chunk_id", "source", "text", "embedding"],
        )
        writer.writeheader()
        for chunk, embedding in zip(chunks, embeddings):
            writer.writerow(
                {
                    "chunk_id": chunk.chunk_id,
                    "source": chunk.source,
                    "text": chunk.text,
                    "embedding": json.dumps(embedding, separators=(",", ":")),
                }
            )
    return len(chunks)


def ensure_vector_store() -> int:
    global _VECTOR_STORE_READY

    if not cfg.USE_RETRIEVAL:
        return 0
    if _VECTOR_STORE_READY and cfg.VECTOR_CSV.exists():
        return sum(1 for _ in _read_rows(cfg.VECTOR_CSV))

    if cfg.REBUILD_VECTOR_STORE or _knowledge_is_newer(cfg.KNOWLEDGE_FOLDER, cfg.VECTOR_CSV):
        print("Building local CSV vector store...", flush=True)
        count = build_vector_store()
        print(f"Stored {count} knowledge chunks in {cfg.VECTOR_CSV}.", flush=True)
        cfg.REBUILD_VECTOR_STORE = False
        _VECTOR_STORE_READY = True
        return count

    _VECTOR_STORE_READY = True
    return sum(1 for _ in _read_rows(cfg.VECTOR_CSV))


def _read_rows(csv_path: Path) -> Iterable[dict]:
    if not csv_path.exists():
        return []
    with csv_path.open("r", newline="", encoding="utf-8") as handle:
        yield from csv.DictReader(handle)


def _cosine_similarity(left: List[float], right: List[float]) -> float:
    if len(left) != len(right) or not left:
        return -1.0
    dot = sum(a * b for a, b in zip(left, right))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return -1.0
    return dot / (left_norm * right_norm)


def retrieve(query: str, top_k: int | None = None) -> List[dict]:
    if not cfg.USE_RETRIEVAL or not query.strip():
        return []

    ensure_vector_store()
    query_embedding = embed_texts([query])[0]
    scored = []

    for row in _read_rows(cfg.VECTOR_CSV):
        try:
            embedding = json.loads(row["embedding"])
        except (KeyError, json.JSONDecodeError, TypeError):
            continue
        scored.append(
            {
                "source": row.get("source", "unknown"),
                "text": row.get("text", ""),
                "score": _cosine_similarity(query_embedding, embedding),
            }
        )

    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[: (top_k or cfg.RETRIEVAL_TOP_K)]


def format_reference_context(query: str) -> str:
    matches = retrieve(query)
    if not matches:
        return "No local reference context was retrieved."

    sections = []
    for match in matches:
        sections.append(
            f"Source: {match['source']}\n"
            f"Similarity: {match['score']:.3f}\n"
            f"{match['text']}"
        )
    return "\n\n".join(sections)
