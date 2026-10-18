from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUOTE_SOURCE = (ROOT / "web/app/static/js/mw_order_quote.js").read_text(encoding="utf-8")


def test_quote_reads_rule_key_from_selected_variant():
    assert "\"mw-variant\"" in QUOTE_SOURCE
    assert ")?.value" in QUOTE_SOURCE


def test_quote_does_not_depend_on_removed_rule_key_node():
    assert "\"mw-rule-key\"" not in QUOTE_SOURCE

