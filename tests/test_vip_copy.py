from core.vip_levels import VIP_LEVEL_BENEFITS
from web.app.services.site_data import (
    VIP_GENERAL_RULES,
    VIP_LEVELS_PUBLIC,
    VIP_PRIVATE_CHANNEL_RULES,
    VIP_REBATE_RULES,
)


def _public_level(name: str) -> dict:
    return next(level for level in VIP_LEVELS_PUBLIC if level["name"] == name)


def test_vip_level_copy_matches_current_policy():
    assert _public_level("白金魔丸")["benefits"] == [
        "享有金級魔丸所有福利",
        "儲值返利2%",
        "每月一張折現券200T",
        "優先排單",
    ]
    assert _public_level("黑鑽魔丸")["benefits"] == [
        "享有白鑽魔丸所有福利",
        "每月一次免費「機密航天保底1000w」或娛樂陪 2H",
        "儲值返利5%",
        "體驗單、趣味單外全館94折",
    ]

    assert "・享有金級魔丸所有福利" in VIP_LEVEL_BENEFITS["白金魔丸"]
    assert "可建立 VIP 專屬私人文字頻道" not in VIP_LEVEL_BENEFITS["白金魔丸"]
    assert "・每月一次免費「機密航天保底1000w」或娛樂陪 2H" in VIP_LEVEL_BENEFITS["黑鑽魔丸"]


def test_vip_rule_copy_matches_current_policy():
    assert VIP_REBATE_RULES == [
        "儲值後如需退款僅能退錢包總金額的95%",
        "儲值達VIP標準也可使用返利，但若後續取出致使額度未到仍會降級",
    ]
    assert "頻道成員包含：VIP 客人、指定打手、客服／管理員。" in VIP_PRIVATE_CHANNEL_RULES
    assert "體驗單、趣味單不適用 VIP 折扣。" in VIP_GENERAL_RULES
