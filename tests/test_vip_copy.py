from pathlib import Path

from core.vip_levels import VIP_LEVEL_BENEFITS
from web.app.services.site_data import (
    VIP_GENERAL_RULES,
    VIP_LEVELS_PUBLIC,
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

    diamond_lines = VIP_LEVEL_BENEFITS["鑽石魔丸"].splitlines()
    assert diamond_lines == [
        "累積消費 25000⤴️",
        "・專屬 VIP 身分組，可使用VIP專屬包廂",
        "・優先客服回覆",
        "・每月一張折現券200T",
        "・優先排單",
        "・優先安排熟悉打手",
        "・儲值返利3%",
        "・體驗單、趣味單外全館96折",
        '・可根據闆闆要求製作"自訂單"',
    ]
    assert "儲值返利2%" not in VIP_LEVEL_BENEFITS["鑽石魔丸"]
    assert "全館98折" not in VIP_LEVEL_BENEFITS["鑽石魔丸"]
    assert "享有白金魔丸所有福利" not in VIP_LEVEL_BENEFITS["鑽石魔丸"]
    assert "可建立 VIP 專屬私人文字頻道" not in VIP_LEVEL_BENEFITS["白金魔丸"]
    assert "・每月一次免費「機密航天保底1000w」或娛樂陪 2H" in VIP_LEVEL_BENEFITS["黑鑽魔丸"]


def test_vip_rule_copy_matches_current_policy():
    assert VIP_REBATE_RULES == [
        "儲值後如需退款僅能退錢包總金額的95%",
        "儲值達VIP標準也可使用返利，但若後續取出致使額度未到仍會降級",
    ]
    assert "體驗單、趣味單不適用 VIP 折扣。" in VIP_GENERAL_RULES


def test_vip_page_does_not_show_private_channel_section():
    template = (
        Path(__file__).resolve().parents[1]
        / "web"
        / "app"
        / "templates"
        / "vip.html"
    ).read_text(encoding="utf-8")

    assert "VIP 專屬私人文字頻道" not in template
    assert "private_channel_rules" not in template
