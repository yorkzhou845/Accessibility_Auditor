"""Small wrapper around the local Ollama HTTP API."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ollama import Client

from config import OLLAMA_BASE_URL, OLLAMA_CHAT_MODEL, OLLAMA_EMBEDDING_MODEL

_client = Client(host=OLLAMA_BASE_URL)


def embed_text(text: str) -> list[float]:
    """Return one embedding vector from the configured local Ollama model."""
    cleaned = text.strip()
    if not cleaned:
        raise ValueError("Cannot embed empty text.")

    try:
        response = _client.embed(model=OLLAMA_EMBEDDING_MODEL, input=cleaned)
        vectors = response.get("embeddings", [])
        if vectors:
            return [float(value) for value in vectors[0]]
    except AttributeError:
        # Compatibility with older ollama-python clients.
        pass

    response = _client.embeddings(model=OLLAMA_EMBEDDING_MODEL, prompt=cleaned)
    vector = response.get("embedding", [])
    if not vector:
        raise RuntimeError("Ollama returned an empty embedding vector.")
    return [float(value) for value in vector]


def chat_json(
    system_prompt: str,
    user_prompt: str,
    image_path: str | Path | None = None,
    num_ctx: int = 4096,
    num_predict: int = 500,
) -> dict[str, Any]:
    """Call the configured local Ollama chat model and parse a JSON response."""
    user_message: dict[str, Any] = {"role": "user", "content": user_prompt}
    if image_path is not None:
        user_message["images"] = [str(image_path)]

    response = _client.chat(
        model=OLLAMA_CHAT_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            user_message,
        ],
        format="json",
        options={
            "temperature": 0,
            "num_ctx": num_ctx,
            "num_predict": num_predict,
        },
    )

    content = str(response["message"]["content"]).strip()
    if content.startswith("```json"):
        content = content.removeprefix("```json").removesuffix("```").strip()
    elif content.startswith("```"):
        content = content.removeprefix("```").removesuffix("```").strip()

    try:
        parsed = json.loads(content)
    except json.JSONDecodeError:
        return {
            "_parse_error": True,
            "raw_output": content,
            "warnings": ["Ollama did not return valid JSON."],
        }

    if not isinstance(parsed, dict):
        return {
            "_parse_error": True,
            "raw_output": content,
            "warnings": ["Ollama returned JSON, but not a JSON object."],
        }

    return parsed
