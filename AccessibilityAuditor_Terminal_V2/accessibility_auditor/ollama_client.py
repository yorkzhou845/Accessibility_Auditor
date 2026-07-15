"""Small REST client for a locally running Ollama instance."""

from __future__ import annotations

import base64
import json
import time
from pathlib import Path
from typing import Iterable, List, Optional

import requests

from . import config as cfg


class OllamaError(RuntimeError):
    """Raised when the local Ollama API cannot complete a request."""


class OllamaClient:
    def __init__(self, base_url: str, timeout_seconds: int = 300) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def _post(self, endpoint: str, payload: dict) -> dict:
        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.post(url, json=payload, timeout=self.timeout_seconds)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaError(
                f"Could not call Ollama at {self.base_url}. "
                "Confirm that Ollama is running and the configured model is installed."
            ) from exc

        try:
            return response.json()
        except ValueError as exc:
            raise OllamaError(f"Ollama returned non-JSON data from {endpoint}.") from exc

    def chat_json(
        self,
        prompt: str,
        *,
        image_path: Optional[Path] = None,
        num_ctx: int = 4096,
        num_predict: int = 500,
    ) -> dict:
        user_message = {"role": "user", "content": prompt}

        if image_path is not None:
            image_bytes = Path(image_path).read_bytes()
            user_message["images"] = [base64.b64encode(image_bytes).decode("ascii")]

        payload = {
            "model": cfg.CHAT_MODEL,
            "messages": [
                {"role": "system", "content": cfg.SYS_PROMPT},
                user_message,
            ],
            "format": "json",
            "stream": False,
            "options": {
                "temperature": 0,
                "num_ctx": num_ctx,
                "num_predict": num_predict,
            },
        }

        print(f"Calling local Ollama model {cfg.CHAT_MODEL}...", flush=True)
        started = time.time()
        response = self._post("/api/chat", payload)
        print(f"Ollama finished in {time.time() - started:.2f} seconds.", flush=True)

        content = str(response.get("message", {}).get("content", "")).strip()
        if content.startswith("```json"):
            content = content.removeprefix("```json").removesuffix("```").strip()
        elif content.startswith("```"):
            content = content.removeprefix("```").removesuffix("```").strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError:
            return {
                "_parse_error": True,
                "raw_output": content,
                "warnings": ["Ollama did not return valid JSON."],
            }

    def embed(self, texts: Iterable[str]) -> List[List[float]]:
        inputs = [text for text in texts]
        if not inputs:
            return []

        response = self._post(
            "/api/embed",
            {
                "model": cfg.EMBED_MODEL,
                "input": inputs,
            },
        )
        embeddings = response.get("embeddings")
        if not isinstance(embeddings, list) or len(embeddings) != len(inputs):
            raise OllamaError("Ollama returned an unexpected embeddings response.")
        return embeddings


_client = OllamaClient(cfg.OLLAMA_BASE_URL, cfg.OLLAMA_TIMEOUT_SECONDS)


def ask_ollama(prompt, image_path=None, num_ctx=4096, num_predict=500):
    return _client.chat_json(
        prompt,
        image_path=Path(image_path) if image_path is not None else None,
        num_ctx=num_ctx,
        num_predict=num_predict,
    )


def embed_texts(texts: Iterable[str]) -> List[List[float]]:
    return _client.embed(texts)
