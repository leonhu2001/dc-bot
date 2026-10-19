from pathlib import Path


def test_self_service_point_benefits_do_not_import_bot_entrypoint():
    source = Path("services/self_service_point_benefits.py").read_text(encoding="utf-8")
    assert "import bot" not in source
    assert "from bot import" not in source
