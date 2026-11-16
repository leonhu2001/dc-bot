"""Customer-facing labels for Delta desktop fixed orders; no key changes."""
from __future__ import annotations

import re

_FIXED_NAMES = {
    "basic_trial_500": "普通體驗單",
    "basic_trial_1000": "尊爵體驗單",
    "basic_oil_fuel": "火箭燃油",
    "basic_oil_satellite": "GTI衛星通信天線",
    "basic_oil_all": "全包",
}


def fixed_guarantee_display_label(rule_key: str, rule, fallback_label: str) -> str:
    """Use the effective price/note so approved future edits remain visible."""
    name = _FIXED_NAMES.get(str(rule_key))
    if not name or rule is None:
        return fallback_label
    match = re.search(r"(\d+)\s*[wW]\s*保底", str(getattr(rule, "note", "") or ""))
    if not match:
        return fallback_label
    guarantee = f"{match.group(1)}W"
    if str(rule_key).startswith("basic_trial_"):
        return f"{name}｜{int(rule.price)}T（保底{guarantee}）"
    return f"{name}（保底{guarantee}）"
