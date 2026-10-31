from __future__ import annotations

from pathlib import Path


def patch_once(path: str, old: str, new: str, label: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected 1 match, got {count}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


patch_once(
    "views/smart_dispatch.py",
    "from services.order_rules import role_ids_match_requirements\n",
    "from services.order_rules import (\n    AW_COLLISION_RECEIVER_ROLE_ID,\n    HALFCOIN_RECEIVER_ROLE_ID,\n    role_ids_match_requirements,\n)\n",
    "smart dispatch role imports",
)

patch_once(
    "views/smart_dispatch.py",
    '''def _customer_service_role_mention(\n    bot: discord.Client,\n    guild: discord.Guild,\n) -> str | None:\n''',
    '''_DEDICATED_RECEIVER_ROLE_IDS = frozenset({\n    AW_COLLISION_RECEIVER_ROLE_ID,\n    HALFCOIN_RECEIVER_ROLE_ID,\n})\n\n\ndef _is_dedicated_receiver_dispatch(role_ids: Iterable[str | int]) -> bool:\n    normalized = {\n        str(role_id).strip()\n        for role_id in role_ids\n        if str(role_id).strip()\n    }\n    return len(normalized) == 1 and bool(normalized & _DEDICATED_RECEIVER_ROLE_IDS)\n\n\ndef _customer_service_role_mention(\n    bot: discord.Client,\n    guild: discord.Guild,\n) -> str | None:\n''',
    "dedicated dispatch predicate",
)

patch_once(
    "views/smart_dispatch.py",
    '''                    support_mention = _customer_service_role_mention(bot, guild)\n                    if support_mention:\n''',
    '''                    dedicated_receiver_dispatch = _is_dedicated_receiver_dispatch(\n                        plan.get("allowed_role_ids") or []\n                    )\n                    support_mention = (\n                        None\n                        if dedicated_receiver_dispatch\n                        else _customer_service_role_mention(bot, guild)\n                    )\n                    if support_mention:\n''',
    "suppress CS ping for dedicated receiver orders",
)

# Add focused regression coverage to the existing smart-dispatch test module.
test_path = Path("tests/test_smart_dispatch.py")
test_text = test_path.read_text(encoding="utf-8")
marker = "def test_dedicated_receiver_dispatch_suppresses_non_receiver_role_escalation():"
if marker not in test_text:
    test_text += '''\n\n\ndef test_dedicated_receiver_dispatch_suppresses_non_receiver_role_escalation():\n    from views.smart_dispatch import _is_dedicated_receiver_dispatch\n\n    assert _is_dedicated_receiver_dispatch(["1565369029005287595"]) is True\n    assert _is_dedicated_receiver_dispatch(["1565369317929918554"]) is True\n    assert _is_dedicated_receiver_dispatch(["1500234130871550004"]) is False\n    assert _is_dedicated_receiver_dispatch([\n        "1565369029005287595",\n        "1500234130871550004",\n    ]) is False\n'''
    test_path.write_text(test_text, encoding="utf-8")

# Static guardrails: special receiver pings remain isolated and the full-wave
# customer-service ping is explicitly suppressed for those orders.
source = Path("views/smart_dispatch.py").read_text(encoding="utf-8")
assert "_is_dedicated_receiver_dispatch" in source
assert "if dedicated_receiver_dispatch" in source
print("DEDICATED_DISPATCH_NOTIFICATION_FIX_APPLIED")
