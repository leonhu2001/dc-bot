from pathlib import Path

from core.vip_levels import (
    VIP_TOPUP_REBATE_PERCENT,
    build_topup_rebate_public_summary,
)


def test_public_topup_rebate_summary_uses_current_policy():
    assert VIP_TOPUP_REBATE_PERCENT == {
        "普通魔丸": 0,
        "銀級魔丸": 0,
        "金級魔丸": 0,
        "白金魔丸": 1,
        "鑽石魔丸": 2,
        "白鑽魔丸": 3,
        "黑鑽魔丸": 3,
    }
    assert build_topup_rebate_public_summary() == (
        "白金魔丸 1%｜鑽石魔丸 2%｜白鑽魔丸 3%｜黑鑽魔丸 3%"
    )


def test_discord_topup_panel_reads_public_summary_from_vip_policy():
    source = (
        Path(__file__).resolve().parents[1]
        / "cogs"
        / "setup_commands.py"
    ).read_text(encoding="utf-8")

    assert "build_topup_rebate_public_summary()" in source
    assert "白金魔丸 2%｜鑽石魔丸 3%｜白鑽魔丸 4%｜黑鑽魔丸 5%" not in source
