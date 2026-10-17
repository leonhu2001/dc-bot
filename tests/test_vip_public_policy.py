from pathlib import Path


def test_public_vip_page_matches_current_monthly_cash_policy():
    root = Path(__file__).resolve().parents[1]
    text = (root / "web/app/templates/vip.html").read_text(encoding="utf-8")

    assert "200T 代金券：單筆原始服務金額滿 1,500T" in text
    assert "500T 代金券：單筆原始服務金額滿 4,000T" in text
    assert "不再要求最近 30 日消費達到 2,000T／5,000T" in text
    assert "黑鑽每月免費福利仍需最近 30 日實際訂單消費滿 8,000T" in text
    assert "先使用 VIP／活動贈額，再使用實付本金" in text
    assert "VIP 每月代金券、點數福利與跨單累積福利券同張訂單只能擇一" in text

    assert "白金／鑽石 2,000T、白鑽 5,000T、黑鑽 8,000T" not in text
