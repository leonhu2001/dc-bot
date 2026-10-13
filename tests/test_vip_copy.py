from pathlib import Path

from core.vip_levels import VIP_LEVEL_BENEFITS, VIP_TOPUP_REBATE_PERCENT


def test_vip_level_copy_matches_current_policy():
    assert VIP_TOPUP_REBATE_PERCENT == {
        "普通魔丸": 0,
        "銀級魔丸": 0,
        "金級魔丸": 0,
        "白金魔丸": 1,
        "鑽石魔丸": 2,
        "白鑽魔丸": 3,
        "黑鑽魔丸": 3,
    }

    silver_lines = VIP_LEVEL_BENEFITS["銀級魔丸"].splitlines()
    assert "・優先客服回覆" in silver_lines

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
    assert "儲值返利3%" not in VIP_LEVEL_BENEFITS["鑽石魔丸"]
    assert "全館98折" not in VIP_LEVEL_BENEFITS["鑽石魔丸"]
    assert "享有白金魔丸所有福利" not in VIP_LEVEL_BENEFITS["鑽石魔丸"]
    assert "・每月一次免費「機密航天保底1000w」或娛樂陪 2H" in VIP_LEVEL_BENEFITS["黑鑽魔丸"]


def test_vip_page_uses_current_public_policy_copy():
    template = (
        Path(__file__).resolve().parents[1]
        / "web" / "app" / "templates" / "vip.html"
    ).read_text(encoding="utf-8")

    for copy in ("儲值返利1%", "儲值返利2%", "儲值返利3%"):
        assert copy in template
    assert "儲值返利4%" not in template
    assert "儲值返利5%" not in template
    assert "95%" not in template
    assert "剩餘實付本金 100% 退回" in template
    assert "不得用於雞腿／打賞" in template
    assert "最近 30 天內至少完成一筆實際消費訂單" in template
    assert "銀級 30 天、金級 45 天、白金 60 天、鑽石 90 天、白鑽 120 天、黑鑽 180 天" in template
    assert "VIP 折扣可與系統點數福利、跨單累積福利依結帳規則併用" in template
