"""Build the generated local CSV vector store."""

from config import OLLAMA_EMBEDDING_MODEL, VECTOR_SOURCE_CSV, VECTOR_STORE_CSV
from vector_store import build_vector_store


if __name__ == "__main__":
    count = build_vector_store()
    print(f"Embedded {count} guidance entries with {OLLAMA_EMBEDDING_MODEL}.")
    print(f"Source: {VECTOR_SOURCE_CSV}")
    print(f"Generated vector store: {VECTOR_STORE_CSV}")
