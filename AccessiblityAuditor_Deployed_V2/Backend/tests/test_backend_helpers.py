from backend_server import parse_tasks


def test_parse_multiple_tasks():
    assert parse_tasks(None, "image_captioning,table_summary") == ["alt_text", "table_summary"]
