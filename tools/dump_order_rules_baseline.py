from __future__ import annotations

import ast
import importlib
import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("DC_BOT_ROOT", "/opt/dc-bot"))
BASELINE_PATH = Path(os.environ.get("ORDER_RULES_BASELINE", str(ROOT / "tools" / "order_rules_baseline.json")))


def get_attr(obj: Any, names: str | list[str], default: Any = None) -> Any:
    if isinstance(names, str):
        names = [names]

    for name in names:
        if hasattr(obj, name):
            value = getattr(obj, name)
            if value is not None:
                return value

    return default


def normalize_list(value: Any) -> list[Any]:
    if value is None:
        return []

    if isinstance(value, (list, tuple, set)):
        return sorted(str(item) for item in value)

    return [str(value)]


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value or default)
    except Exception:
        return default


def load_role_ids() -> dict[str, str]:
    for module_name in ("config", "settings", "services.order_rules"):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue

        value = getattr(module, "ROLE_IDS", None)

        if isinstance(value, dict) and value:
            return {str(key): str(item) for key, item in value.items()}

    bot_path = ROOT / "bot.py"

    if bot_path.exists():
        tree = ast.parse(bot_path.read_text(encoding="utf-8", errors="replace"))

        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue

            if not any(isinstance(target, ast.Name) and target.id == "ROLE_IDS" for target in node.targets):
                continue

            try:
                value = ast.literal_eval(node.value)
            except Exception:
                continue

            if isinstance(value, dict) and value:
                return {str(key): str(item) for key, item in value.items()}

    return {}


def load_rules(order_rules: Any) -> dict[str, Any]:
    for name in ("ORDER_RULES", "RULES"):
        value = getattr(order_rules, name, None)

        if isinstance(value, dict) and value:
            return value

    raise RuntimeError("找不到 ORDER_RULES / RULES")


def load_categories(order_rules: Any, rules: dict[str, Any]) -> dict[str, str]:
    for name in ("ORDER_CATEGORIES", "CATEGORY_LABELS", "CATEGORIES", "CATEGORY_OPTIONS"):
        value = getattr(order_rules, name, None)

        if isinstance(value, dict) and value:
            return {str(key): str(item) for key, item in value.items()}

    derived: dict[str, str] = {}

    for rule in rules.values():
        category = str(get_attr(rule, ["category", "category_key"], "") or "").strip()

        if category:
            derived.setdefault(category, category)

    return derived


def infer_price_type(rule: Any) -> str:
    value = get_attr(
        rule,
        [
            "price_type",
            "pricing_type",
            "price_mode",
            "pricing_mode",
            "billing_type",
            "mode",
            "kind",
        ],
        None,
    )

    if value is not None:
        return str(value)

    price = safe_int(get_attr(rule, ["price", "amount", "base_price"], 0), 0)
    key = str(get_attr(rule, "key", "") or "")

    if price <= 0 or key.startswith("custom_"):
        return "manual"

    return "fixed"


def call_calculate_price(order_rules: Any, rule: Any) -> dict[str, Any]:
    calculate_price = getattr(order_rules, "calculate_price", None)

    if not callable(calculate_price):
        return {"error": "calculate_price missing"}

    quantity = max(1, safe_int(get_attr(rule, ["min_quantity", "minimum_quantity", "min_hours"], 1), 1))

    attempts = [
        lambda: calculate_price(rule, quantity=quantity, player_count=1),
        lambda: calculate_price(rule, quantity=quantity),
        lambda: calculate_price(rule, player_count=1),
        lambda: calculate_price(rule),
    ]

    errors = []

    for attempt in attempts:
        try:
            result = attempt()
            return {
                "base_amount": safe_int(getattr(result, "base_amount", None), 0),
                "specify_fee": safe_int(getattr(result, "specify_fee", None), 0),
                "staff_adjustment_amount": safe_int(getattr(result, "staff_adjustment_amount", None), 0),
                "total_amount": safe_int(getattr(result, "total_amount", None), 0),
                "service_quantity": safe_int(getattr(result, "service_quantity", None), quantity),
                "required_staff_count": safe_int(getattr(result, "required_staff_count", None), 1),
                "free_specify_fee": bool(getattr(result, "free_specify_fee", False)),
            }
        except TypeError as exc:
            errors.append(str(exc))
            continue
        except Exception as exc:
            return {"error": f"{type(exc).__name__}: {exc}"}

    return {"error": " | ".join(errors)}


def build_baseline() -> dict[str, Any]:
    import services.order_rules as order_rules

    role_ids = load_role_ids()
    rules = load_rules(order_rules)
    categories = load_categories(order_rules, rules)

    data: dict[str, Any] = {
        "schema_version": 1,
        "rule_count": len(rules),
        "category_count": len(categories),
        "categories": categories,
        "role_ids": role_ids,
        "rules": {},
    }

    for key in sorted(rules):
        rule = rules[key]

        allowed_roles = normalize_list(get_attr(rule, ["allowed_roles", "role_keys"], []))
        required_staff_count = get_attr(rule, "required_staff_count", None)

        try:
            resolved_required_staff_count = int(order_rules.get_required_staff_count(rule, 1))
        except Exception:
            resolved_required_staff_count = safe_int(required_staff_count, 1)

        data["rules"][key] = {
            "key": str(key),
            "category": str(get_attr(rule, ["category", "category_key"], "") or ""),
            "label": str(get_attr(rule, ["label", "name", "display_name"], "") or ""),
            "price_type": infer_price_type(rule),
            "price": safe_int(get_attr(rule, ["price", "amount", "base_price"], 0), 0),
            "unit_label": str(get_attr(rule, ["unit_label", "unit", "quantity_label"], "") or ""),
            "min_quantity": get_attr(rule, ["min_quantity", "minimum_quantity", "min_hours"], None),
            "max_quantity": get_attr(rule, "max_quantity", None),
            "allowed_roles": allowed_roles,
            "allowed_role_ids": [role_ids.get(str(role), "") for role in allowed_roles],
            "required_staff_count": str(required_staff_count),
            "resolved_required_staff_count_at_player_1": resolved_required_staff_count,
            "min_protector_count": safe_int(get_attr(rule, "min_protector_count", 0), 0),
            "allow_specify": bool(get_attr(rule, "allow_specify", False)),
            "max_specified_count": get_attr(rule, "max_specified_count", None),
            "point_benefits_allowed": bool(get_attr(rule, "point_benefits_allowed", True)),
            "price_at_min_quantity": call_calculate_price(order_rules, rule),
        }

    return data


def main() -> None:
    baseline = build_baseline()

    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(baseline, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("ORDER_RULES_BASELINE_WRITTEN=", BASELINE_PATH)
    print("RULE_COUNT=", baseline["rule_count"])
    print("CATEGORY_COUNT=", baseline["category_count"])


if __name__ == "__main__":
    main()
