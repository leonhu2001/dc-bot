from __future__ import annotations

from services.review_storage import get_staff_favorites


def _truncate_select_text(value: str, limit: int = 100) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def prioritize_specified_staff_entries_for_customer(
    entries: list[dict],
    customer_id: int | str,
) -> list[dict]:
    """Put the ticket customer's eligible favorites first without changing eligibility."""
    result = [dict(entry) for entry in entries]
    staff_ids = [str(entry.get("id") or "").strip() for entry in result]
    staff_ids = [staff_id for staff_id in staff_ids if staff_id]

    try:
        favorite_ids = get_staff_favorites(customer_id, staff_ids) if staff_ids else set()
    except Exception as exc:
        print(
            f"[self-service] favorite priority lookup failed customer_id={customer_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )
        favorite_ids = set()

    for entry in result:
        staff_id = str(entry.get("id") or "").strip()
        is_favorite = staff_id in favorite_ids
        entry["is_favorite"] = is_favorite

        if is_favorite:
            description = str(entry.get("description") or "").strip()
            if not description.startswith("❤️ 收藏"):
                entry["description"] = _truncate_select_text(
                    f"❤️ 收藏｜{description}" if description else "❤️ 收藏"
                )

    result.sort(
        key=lambda item: (
            0 if item.get("is_favorite") else 1,
            int(item["role_order"]) if item.get("role_order") is not None else 999,
            str(item.get("label") or "").casefold(),
            str(item.get("id") or ""),
        )
    )
    return result
