from pathlib import Path


def test_payment_panel_repair_command_has_readable_copy():
    source = Path("bot.py").read_text(encoding="utf-8")
    start = source.index('name="fix_acceptance_payment_panel"')
    end = source.index('name="staff_profile_panel"', start)
    block = source[start:end]

    assert "???" not in block
    assert "依票口 ID 補送等待付款 Panel" in block
    assert "只有客服、店長或管理員可以補送付款 Panel" in block


def test_repeat_reminders_only_start_after_second_round_and_keep_stage_two():
    source = Path("views/smart_dispatch.py").read_text(encoding="utf-8")
    assert "if stage >= 2:" in source
    assert "第三次通知起才進入每 10 分鐘循環" in source
    assert "不可降回 1" in source
