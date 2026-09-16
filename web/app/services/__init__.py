"""Web-service package initialization.

Keep public checkout copy aligned with the shared pricing rules applied by the
root services package.
"""

from __future__ import annotations

from . import order_groups as _order_groups


for _spec in _order_groups.GROUP_SPECS:
    _description = str(_spec.get("description") or "")
    if not _description:
        continue

    # Shared specify fee is now 100T.
    _description = _description.replace("+150T", "+100T")

    _category = str(_spec.get("category") or "")
    _key = str(_spec.get("key") or "")

    if _category == "valorant":
        _description = _description.replace(
            "2 局以上免指定費。",
            "NG 2 小時 / 積分 2 局以上免指定費。",
        )
    elif _category == "lol":
        if _key == "lol_entertain":
            _description = _description.replace(
                "2 小時 / 2 局以上免指定費。",
                "ARAM / NG 2 小時，積分 2 局以上免指定費。",
            )
        else:
            _description = _description.replace(
                "2 局以上免指定費。",
                "NG 2 小時 / 積分 2 局以上免指定費。",
            )

    _spec["description"] = _description


del _spec, _description, _category, _key
