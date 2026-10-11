from pathlib import Path

from views.smart_dispatch import _merge_wave_notification_ids


def test_fully_specified_wave_only_notifies_specified_staff():
    assert _merge_wave_notification_ids(
        ["S1", "S2"],
        ["A", "B", "C"],
        unrestricted_missing=0,
    ) == ["S1", "S2"]


def test_partial_specified_wave_keeps_specified_and_open_slot_candidates():
    assert _merge_wave_notification_ids(
        ["S1"],
        ["A", "B", "C"],
        unrestricted_missing=1,
    ) == ["S1", "A", "B", "C"]


def test_wave_targets_are_deduplicated():
    assert _merge_wave_notification_ids(
        ["S1", "S1"],
        ["S1", "A", "A"],
        unrestricted_missing=1,
    ) == ["S1", "A"]


def test_first_and_repeat_waves_use_reserved_slot_targeting():
    source = Path("views/smart_dispatch.py").read_text(encoding="utf-8")

    assert "first_ids = _merge_wave_notification_ids(" in source
    assert "repeat_ids = _merge_wave_notification_ids(" in source
