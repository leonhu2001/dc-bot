from pathlib import Path


def test_credential_messages_do_not_render_literal_newline_tokens():
    source = (
        Path(__file__).resolve().parents[1]
        / "services"
        / "order_credential_runtime.py"
    ).read_text(encoding="utf-8")

    assert "\\\\n" not in source
