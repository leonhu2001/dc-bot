import re
from pathlib import Path


def test_payment_panel_repair_command_has_readable_copy():
    source = Path("bot.py").read_text(encoding="utf-8")
    start_match = re.search(r"name=['\"]補送付款面板['\"]", source)
    end_match = re.search(r"name=['\"]建立個人牆面板['\"]", source)

    assert start_match is not None
    assert end_match is not None
    assert end_match.start() > start_match.start()

    block = source[start_match.start():end_match.start()]

    assert "???" not in block
    assert "依票口 ID 補送等待付款 Panel" in block
    assert "只有客服、店長或管理員可以補送付款 Panel" in block


def test_repeat_reminders_only_start_after_second_round_and_keep_stage_two():
    source = Path("views/smart_dispatch.py").read_text(encoding="utf-8")
    assert "if stage >= 3:" in source
    assert "第三輪全量通知完成後，才進入每 10 分鐘持續提醒" in source
    assert "循環提醒不可讓 stage 倒退" in source
