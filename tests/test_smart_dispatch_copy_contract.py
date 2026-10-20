from pathlib import Path

from core.discord_settings import (
    SMART_DISPATCH_FULL_EXPANSION_SECONDS,
    SMART_DISPATCH_PUBLIC_ACCEPTANCE_OPEN_SECONDS,
    SMART_DISPATCH_REPEAT_REMINDER_SECONDS,
    SMART_DISPATCH_SECOND_WAVE_SECONDS,
)


SMART_DISPATCH_SOURCE = Path("views/smart_dispatch.py")


def test_smart_dispatch_timing_contract_is_unchanged():
    assert SMART_DISPATCH_PUBLIC_ACCEPTANCE_OPEN_SECONDS == 60
    assert SMART_DISPATCH_SECOND_WAVE_SECONDS == 240
    assert SMART_DISPATCH_FULL_EXPANSION_SECONDS == 420
    assert SMART_DISPATCH_REPEAT_REMINDER_SECONDS == 600
    assert (
        SMART_DISPATCH_FULL_EXPANSION_SECONDS
        - SMART_DISPATCH_PUBLIC_ACCEPTANCE_OPEN_SECONDS
    ) == 360


def test_smart_dispatch_copy_uses_timing_based_names():
    source = SMART_DISPATCH_SOURCE.read_text(encoding="utf-8")

    assert "派單仍缺人｜中段擴大通知" in source
    assert "派單仍缺人｜6 分鐘全量通知" in source
    assert "智慧派單已進入 6 分鐘全量通知" in source
    assert "派單仍缺人｜10 分鐘提醒" in source

    assert "派單仍缺人｜第二輪擴大通知" not in source
    assert "派單仍缺人｜第三輪全量通知" not in source
    assert "智慧派單已進入第三輪全量通知" not in source
