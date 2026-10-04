from __future__ import annotations

import json
from typing import Any

from services.orders import ORDER_CATEGORY_LABELS, _to_int


def build_receiver_text(assignments: list[dict[str, Any]]) -> str:
    companions: list[str] = []
    boosters: list[str] = []

    for row in assignments:
        user_id = str(row.get("worker_discord_id") or "").strip()
        role_type = str(row.get("role_type") or "booster").strip()

        if not user_id:
            continue

        text = f"<@{user_id}>"

        if role_type == "companion":
            companions.append(text)
        else:
            boosters.append(text)

    parts: list[str] = []

    if boosters:
        parts.extend(boosters)

    if companions:
        parts.extend(companions)

    if not parts:
        return "尚未有人接單"

    return "\n".join(parts)


def parse_json_object(value: Any, default: dict[str, Any] | None = None) -> dict[str, Any]:
    if default is None:
        default = {}

    if isinstance(value, dict):
        return dict(value)

    if not value:
        return dict(default)

    try:
        parsed = json.loads(str(value))
    except Exception:
        return dict(default)

    if not isinstance(parsed, dict):
        return dict(default)

    return parsed


def parse_json_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple, set)):
        return [
            str(item).strip()
            for item in value
            if str(item).strip()
        ]

    if not value:
        return []

    try:
        parsed = json.loads(str(value))
    except Exception:
        return []

    if not isinstance(parsed, list):
        return []

    return [
        str(item).strip()
        for item in parsed
        if str(item).strip()
    ]


def build_order_created_details(bundle: dict[str, Any]) -> dict[str, Any]:
    order = bundle.get("order") or {}
    acceptance = bundle.get("acceptance") or {}
    submission = bundle.get("submission") or {}

    rule_snapshot = parse_json_object(order.get("rule_snapshot_json"))
    price_snapshot = parse_json_object(order.get("price_snapshot_json"))
    submission_payload = parse_json_object(
        submission.get("submission_payload_json")
    )

    specified_staff_ids = parse_json_list(
        acceptance.get("specified_staff_ids_json")
    )
    allowed_role_ids = parse_json_list(
        acceptance.get("allowed_role_ids_json")
    )
    required_game_role_ids = parse_json_list(
        acceptance.get("required_game_role_ids_json")
    )

    if not required_game_role_ids:
        required_game_role_ids = parse_json_list(
            rule_snapshot.get("required_game_role_ids")
        )

    if not specified_staff_ids:
        specified_staff_ids = parse_json_list(
            price_snapshot.get("specified_staff_ids")
        )

    if not specified_staff_ids:
        for candidate_key in (
            "specified_staff_ids",
            "selected_staff_ids",
            "staff_ids",
        ):
            specified_staff_ids = parse_json_list(
                submission_payload.get(candidate_key)
            )
            if specified_staff_ids:
                break

    rule_key = str(
        rule_snapshot.get("key")
        or price_snapshot.get("order_rule_key")
        or order.get("order_rule_key")
        or ""
    ).strip()

    category_key = str(
        rule_snapshot.get("category")
        or price_snapshot.get("category")
        or order.get("category")
        or ""
    ).strip()

    raw_category = str(
        order.get("category")
        or category_key
        or "未紀錄"
    ).strip()

    category_label = ORDER_CATEGORY_LABELS.get(
        category_key,
        raw_category,
    )

    amount_value = order.get("customer_pay_amount")
    if amount_value is None:
        amount_value = price_snapshot.get("customer_pay_amount")
    if amount_value is None:
        amount_value = order.get("amount")

    amount = _to_int(amount_value, 0)
    if amount is None:
        amount = 0

    player_count = _to_int(
        price_snapshot.get("player_count"),
        None,
    )
    if player_count is None:
        player_count = _to_int(
            rule_snapshot.get("player_count"),
            1,
        )
    player_count = max(1, int(player_count or 1))

    website_payment_method = str(
        submission_payload.get("payment_method")
        or submission_payload.get("payment_method_key")
        or order.get("payment_method")
        or ""
    ).strip()

    service_terms_version = str(
        submission.get("terms_version")
        or submission_payload.get("terms_version")
        or ""
    ).strip()

    terms_accepted_at = str(
        submission.get("terms_accepted_at")
        or ""
    ).strip()

    extra_requirements = str(
        submission.get("extra_requirements")
        or submission_payload.get("extra_requirements")
        or ""
    ).strip()

    request_key = str(
        submission.get("request_key")
        or submission_payload.get("request_key")
        or ""
    ).strip()

    required_staff_count = _to_int(
        acceptance.get("required_staff_count"),
        1,
    )

    return {
        "rule_snapshot": rule_snapshot,
        "price_snapshot": price_snapshot,
        "submission_payload": submission_payload,
        "rule_key": rule_key,
        "category_key": category_key,
        "category_label": category_label,
        "item": str(order.get("item") or "未紀錄"),
        "quantity": max(
            1,
            int(_to_int(order.get("quantity"), 1) or 1),
        ),
        "player_count": player_count,
        "amount": int(amount),
        "website_payment_method": website_payment_method,
        "service_terms_version": service_terms_version,
        "terms_accepted_at": terms_accepted_at,
        "extra_requirements": extra_requirements[:500],
        "request_key": request_key,
        "specified_staff_ids": specified_staff_ids,
        "allowed_role_ids": allowed_role_ids,
        "required_game_role_ids": required_game_role_ids,
        "required_staff_count": max(
            1,
            int(required_staff_count or 1),
        ),
    }
