from tools import audit_order_rules


def test_order_rules_audit_accepts_game_role_only_rules(capsys):
    audit_order_rules.main()

    output = capsys.readouterr().out
    assert "ORDER_RULES_AUDIT_PASS" in output
    assert "allowed_game_roles:" in output
