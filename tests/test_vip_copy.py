from pathlib import Path

from core.vip_levels import VIP_LEVEL_BENEFITS


def test_vip_level_copy_matches_current_policy():
    silver_lines = VIP_LEVEL_BENEFITS["銀級魔丸"].splitlines()
    assert "・優先客服回覆" in silver_lines

    platinum_lines = VIP_LEVEL_BENEFITS["白金魔丸"].splitlines()
    assert "・儲值返利1%" in platinum_lines

    diamond_lines = VIP_LEVEL_BENEFITS["鑽石魔丸"].splitlines()
    assert diamond_lines == [
        "累積消費 25000⤴️",
        "・專屬 VIP 身分組，可使用VIP專屬包廂",
        "・優先客服回覆",
        "・每月一張折現券200T",
        "・優先排單",
        "・優先安排熟悉／收藏陪玩",
        "・儲值返利2%",
        "・體驗單、趣味單外全館96折",
        '・可根據闆闆要求製作"自訂單"',
    ]
    assert "儲值返利1%" not in VIP_LEVEL_BENEFITS["鑽石魔丸"]
    assert "全館98折" not in VIP_LEVEL_BENEFITS["鑽石魔丸"]
    assert "享有白金魔丸所有福利" not in VIP_LEVEL_BENEFITS["鑽石魔丸"]
    assert "・儲值返利3%" in VIP_LEVEL_BENEFITS["白鑽魔丸"]
    assert "・儲值返利3%" in VIP_LEVEL_BENEFITS["黑鑽魔丸"]
    assert "・每月一次免費「機密航天保底1000w」或娛樂陪 2H" in VIP_LEVEL_BENEFITS["黑鑽魔丸"]


def test_vip_page_uses_refreshed_public_policy_copy():
    template = (
        Path(__file__).resolve().parents[1]
        / "web"
        / "app"
        / "templates"
        / "vip.html"
    ).read_text(encoding="utf-8")

    assert "儲值返利 1%" in template
    assert "儲值返利 2%" in template
    assert template.count("儲值返利 3%") >= 2
    assert "儲值返利 4%" not in template
    assert "儲值返利 5%" not in template
    assert "退款以尚未消費的實付本金為上限" in template
    assert "雞腿／打賞僅能使用實付本金" in template
    assert "先使用 VIP／活動贈額，再使用實付本金" in template
    assert "200T 代金券：單筆原始服務金額滿 1,500T" in template
    assert "500T 代金券：單筆原始服務金額滿 4,000T" in template
    assert "不再要求最近 30 日消費達到 2,000T／5,000T" in template
    assert "黑鑽每月免費福利仍需最近 30 日實際訂單消費滿 8,000T" in template
    assert "儲值本身不計入這個 8,000T 門檻" in template
    assert "白金／鑽石 2,000T、白鑽 5,000T、黑鑽 8,000T" not in template
    assert "2026/10/14 起成立的新訂單與新儲值適用新版 VIP／儲值規則" in template
    assert "優先安排熟悉／收藏陪玩" in template
    assert "銀級 30 天、金級 45 天、白金 60 天、鑽石 90 天、白鑽 120 天、黑鑽 180 天" in template
    assert "VIP 專屬私人文字頻道" not in template
    assert "private_channel_rules" not in template
