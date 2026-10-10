from pathlib import Path


def test_public_rules_define_objective_complaint_and_refund_policy():
    text = Path("web/app/templates/service_rules.html").read_text(encoding="utf-8")

    assert "規章版本：2026-10-10-v2" in text
    assert "不以勝率、擊殺數、段位結果或單次操作失誤" in text
    assert "顧客原因" in text
    assert "陪玩／打手原因" in text
    assert "店家調度原因" in text
    assert "不可抗力" in text
    assert "尚未履行的服務" in text
    assert "30 日、90 日及永久" in text
    assert "7 日內" in text
