import tempfile
import unittest
from pathlib import Path

from accessibility_auditor import vector_store


def fake_embed_texts(texts):
    vectors = []
    for text in texts:
        lower = text.lower()
        vectors.append(
            [
                float("image" in lower or "alternative" in lower),
                float("table" in lower or "header" in lower),
                float("heading" in lower or "hierarchy" in lower),
                0.1,
            ]
        )
    return vectors


class VectorStoreTests(unittest.TestCase):
    def test_build_and_retrieve_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            knowledge = root / "knowledge"
            knowledge.mkdir()
            (knowledge / "guide.md").write_text(
                "Alternative text describes a meaningful image.\n\n"
                "Table headers identify row and column relationships.",
                encoding="utf-8",
            )
            csv_path = root / "vector_store.csv"

            original_embed = vector_store.embed_texts
            original_folder = vector_store.cfg.KNOWLEDGE_FOLDER
            original_csv = vector_store.cfg.VECTOR_CSV
            original_chunk_size = vector_store.cfg.CHUNK_SIZE
            original_rebuild = vector_store.cfg.REBUILD_VECTOR_STORE
            original_use = vector_store.cfg.USE_RETRIEVAL
            try:
                vector_store.embed_texts = fake_embed_texts
                vector_store.cfg.KNOWLEDGE_FOLDER = knowledge
                vector_store.cfg.VECTOR_CSV = csv_path
                vector_store.cfg.CHUNK_SIZE = 80
                vector_store.cfg.REBUILD_VECTOR_STORE = False
                vector_store.cfg.USE_RETRIEVAL = True

                count = vector_store.build_vector_store(knowledge, csv_path)
                self.assertEqual(count, 2)
                matches = vector_store.retrieve("image alternative text", top_k=1)
                self.assertEqual(len(matches), 1)
                self.assertIn("Alternative text", matches[0]["text"])
            finally:
                vector_store.embed_texts = original_embed
                vector_store.cfg.KNOWLEDGE_FOLDER = original_folder
                vector_store.cfg.VECTOR_CSV = original_csv
                vector_store.cfg.CHUNK_SIZE = original_chunk_size
                vector_store.cfg.REBUILD_VECTOR_STORE = original_rebuild
                vector_store.cfg.USE_RETRIEVAL = original_use


if __name__ == "__main__":
    unittest.main()
