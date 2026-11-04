from __future__ import annotations

import unicodedata


def _game_identity(label: object) -> str:
    """Compare current/old VIP game labels, not gameplay or rule identifiers."""
    text = unicodedata.normalize("NFKC", str(label or "")).casefold().strip()
    text = text.replace("三角洲行動", "三角洲")
    text = text.replace("steam遊戲", "steam").replace("steam 遊戲", "steam")
    return "".join(character for character in text if character.isalnum())


def resolve_vip_timer_game_label(selected: object) -> str | None:
    """Map a historical Discord Select value to an active timer game label.

    Only labels belonging to an active catalog entry may be resolved. A removed
    game returns None rather than creating a broken ticket with an empty selector.
    """
    from services import orders
    from services.vip_timer import VIP_TIMER_CATEGORY

    identity = _game_identity(selected)
    if not identity:
        return None

    for row in orders.SELF_SERVICE_ORDER_CATALOG.get(VIP_TIMER_CATEGORY, ()) or ():
        if not isinstance(row, dict) or not list(row.get("details") or ()):
            continue
        label = str(row.get("label") or "").strip()
        if label and _game_identity(label) == identity:
            return label
    return None


__all__ = ["resolve_vip_timer_game_label"]
