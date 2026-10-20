from pathlib import Path


def test_discord_self_service_dispatch_uses_unified_acceptance_presentation():
    source = Path("services/self_service_dispatch_runtime.py").read_text(encoding="utf-8")

    assert "AcceptanceDispatchView" in source
    assert "apply_acceptance_dispatch_fields(" in source
    assert "acceptance_public_open_timestamp(" in source
    assert '"public_acceptance_opens_at_unix"' in source
    assert "PUBLIC_ACCEPTANCE_LOCK_SECONDS" in source
    assert "await dispatch_message.edit(\n            embed=embed," in source
    assert "view=AcceptanceDispatchView(" in source


def test_discord_self_service_dispatch_does_not_duplicate_specified_staff_field():
    source = Path("services/self_service_dispatch_runtime.py").read_text(encoding="utf-8")

    # 指定人員現在由統一的「接單規則」區塊呈現，避免舊欄位和新版欄位重複。
    assert 'name="指定人員"' not in source
    assert '"specified_staff_ids": specified_staff_ids' in source
