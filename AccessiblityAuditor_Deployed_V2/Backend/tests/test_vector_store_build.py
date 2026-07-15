import csv
import json
from pathlib import Path

import vector_store


def test_build_vector_store_writes_embeddings(tmp_path, monkeypatch):
    source = tmp_path / "source.csv"
    store = tmp_path / "store.csv"
    source.write_text(
        'id,title,content,source\n1,Example,Useful guidance,Test source\n',
        encoding='utf-8',
    )
    monkeypatch.setattr(vector_store, "embed_text", lambda text: [0.25, 0.75])

    count = vector_store.build_vector_store(source, store)

    assert count == 1
    with store.open("r", encoding="utf-8", newline="") as handle:
        row = next(csv.DictReader(handle))
    assert row["title"] == "Example"
    assert json.loads(row["embedding"]) == [0.25, 0.75]
