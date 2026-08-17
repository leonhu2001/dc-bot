from __future__ import annotations

import ast
import importlib
import inspect
import os
from pathlib import Path
from typing import Any


ROOT = Path(os.environ.get("DC_BOT_ROOT", "/opt/dc-bot"))


def title(text: str) -> None:
    print("\n" + "=" * 100)
    print(text)
    print("=" * 100)


def sep(index: int | None = None) -> None:
    print("-" * 80)
    if index is not None:
        print(f"#{index}")


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
        return list(value)

    return [value]


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

    price = int(get_attr(rule, ["price", "amount", "base_price"], 0) or 0)
    key = str(get_attr(rule, "key", "") or "")

    if price <= 0 or key.startswith("custom_"):
        return "manual"

    return "fixed"


def call_calculate_price(order_rules: Any, rule: Any) -> Any:
    calculate_price = getattr(order_rules, "calculate_price", None)

    if not callable(calculate_price):
        raise RuntimeError("calculate_price missing")

    try:
        quantity = int(get_attr(rule, ["min_quantity", "minimum_quantity", "min_hours"], 1) or 1)
    except Exception:
        quantity = 1

    quantity = max(1, quantity)

    attempts = [
        lambda: calculate_price(rule, quantity=quantity, player_count=1),
        lambda: calculate_price(rule, quantity=quantity),
        lambda: calculate_price(rule, player_count=1),
        lambda: calculate_price(rule),
    ]

    errors = []

    for attempt in attempts:
        try:
            return attempt()
        except TypeError as exc:
            errors.append(str(exc))
            continue

    raise RuntimeError("calculate_price call failed: " + " | ".join(errors))


def main() -> None:
    title("ORDER_RULES_AUDIT")

    import services.order_rules as order_rules

    ROLE_IDS = load_role_ids()
    rules = load_rules(order_rules)
    categories = load_categories(order_rules, rules)
    role_labels = getattr(order_rules, "ROLE_LABELS", {})
    all_receiver_roles = set(getattr(order_rules, "ALL_RECEIVER_ROLES", set()) or set())

    helper_names = [
        "calculate_price",
        "get_required_staff_count",
        "build_order_rule_snapshot",
    ]

    errors: list[str] = []
    warnings: list[str] = []

    print("ROOT:", ROOT)
    print("RULE_COUNT:", len(rules))
    print("CATEGORY_COUNT:", len(categories))
    print("ROLE_IDS_COUNT:", len(ROLE_IDS))

    title("HELPERS")
    for name in helper_names:
        helper = getattr(order_rules, name, None)
        print(f"{name}:", "OK" if callable(helper) else "MISSING")

        if not callable(helper):
            errors.append(f"missing helper: {name}")

    title("CATEGORIES")
    if not categories:
        errors.append("categories empty after fallback")
    else:
        for key, label in categories.items():
            sep()
            print("key:", key)
            print("label:", label)

            if not str(key or "").strip():
                errors.append("category key is empty")

            if not str(label or "").strip():
                warnings.append(f"category {key} label is empty")

    title("ROLE_MAP")
    for role_key in sorted(all_receiver_roles):
        role_id = ROLE_IDS.get(role_key)
        print(f"{role_key}: {role_id} / {role_labels.get(role_key)}")

        if not role_id:
            errors.append(f"receiver role missing ROLE_IDS mapping: {role_key}")

    title("RULES")
    seen_keys = set()

    for index, (key, rule) in enumerate(rules.items(), 1):
        sep(index)

        category = str(get_attr(rule, ["category", "category_key"], "") or "")
        label = str(get_attr(rule, ["label", "name", "display_name"], "") or "")
        price_type = infer_price_type(rule)
        price = get_attr(rule, ["price", "amount", "base_price"], 0)
        unit_label = get_attr(rule, ["unit_label", "unit", "quantity_label"], "")
        allowed_roles = normalize_list(get_attr(rule, ["allowed_roles", "role_keys"], []))
        required_staff_count = get_attr(rule, "required_staff_count", None)
        min_protector_count = int(get_attr(rule, "min_protector_count", 0) or 0)
        max_quantity = get_attr(rule, "max_quantity", None)
        min_quantity = get_attr(rule, "min_quantity", None)
        allow_specify = bool(get_attr(rule, "allow_specify", False))
        max_specified_count = get_attr(rule, "max_specified_count", None)
        point_benefits_allowed = bool(get_attr(rule, "point_benefits_allowed", True))

        print("key:", key)
        print("category:", category)
        print("label:", label)
        print("price_type:", price_type)
        print("price:", price)
        print("unit_label:", unit_label)
        print("allowed_roles:", allowed_roles)
        print("required_staff_count:", required_staff_count)
        print("min_protector_count:", min_protector_count)
        print("allow_specify:", allow_specify)
        print("max_specified_count:", max_specified_count)
        print("point_benefits_allowed:", point_benefits_allowed)

        if key in seen_keys:
            errors.append(f"duplicate rule key: {key}")
        seen_keys.add(key)

        if not str(key or "").strip():
            errors.append("rule key is empty")

        if get_attr(rule, "key", key) != key:
            errors.append(f"rule dict key != rule.key: dict={key}, rule.key={get_attr(rule, 'key', None)}")

        if category not in categories:
            errors.append(f"{key}: category not in derived categories: {category}")

        if not str(label or "").strip():
            warnings.append(f"{key}: label is empty")

        try:
            price_int = int(price or 0)
        except Exception:
            errors.append(f"{key}: price is not int-compatible: {price}")
            price_int = 0

        if price_type in {"fixed", "unit"} and price_int <= 0:
            errors.append(f"{key}: {price_type} price must be > 0")

        if price_type == "manual" and price_int != 0:
            warnings.append(f"{key}: manual price usually should be 0, current={price_int}")

        if not allowed_roles:
            errors.append(f"{key}: allowed_roles is empty")

        for role_key in allowed_roles:
            if role_key not in ROLE_IDS:
                errors.append(f"{key}: allowed role missing ROLE_IDS mapping: {role_key}")

            if all_receiver_roles and role_key not in all_receiver_roles:
                errors.append(f"{key}: allowed role is not receiver role: {role_key}")

        try:
            if callable(getattr(order_rules, "get_required_staff_count", None)):
                resolved_required = int(order_rules.get_required_staff_count(rule, 1))
            else:
                resolved_required = int(required_staff_count or 1)
        except Exception as exc:
            errors.append(f"{key}: get_required_staff_count failed: {type(exc).__name__}: {exc}")
            resolved_required = 1

        if resolved_required <= 0:
            errors.append(f"{key}: resolved required_staff_count must be > 0")

        if min_protector_count < 0:
            errors.append(f"{key}: min_protector_count must be >= 0")

        if min_protector_count > resolved_required:
            errors.append(f"{key}: min_protector_count > required_staff_count")

        if max_quantity is not None and min_quantity is not None:
            try:
                if int(max_quantity) < int(min_quantity):
                    errors.append(f"{key}: max_quantity < min_quantity")
            except Exception:
                errors.append(f"{key}: invalid quantity range min={min_quantity}, max={max_quantity}")

        if max_specified_count is not None:
            try:
                max_specified_count_int = int(max_specified_count)

                if max_specified_count_int < 0:
                    errors.append(f"{key}: max_specified_count < 0")

                is_player_count_rule = str(required_staff_count) == "player_count"
                is_custom_rule = key.startswith("custom_") or category == "custom"

                if (
                    max_specified_count_int > resolved_required
                    and not is_player_count_rule
                    and not is_custom_rule
                ):
                    warnings.append(f"{key}: max_specified_count > required_staff_count")
            except Exception:
                errors.append(f"{key}: invalid max_specified_count={max_specified_count}")

        if allow_specify and max_specified_count is not None and int(max_specified_count or 0) == 0:
            warnings.append(f"{key}: allow_specify=True but max_specified_count=0")

        try:
            calculated = call_calculate_price(order_rules, rule)
            print("calculate_price_min_quantity:", calculated)
        except Exception as exc:
            errors.append(f"{key}: calculate_price failed: {type(exc).__name__}: {exc}")

        if callable(getattr(order_rules, "build_order_rule_snapshot", None)):
            try:
                snapshot = order_rules.build_order_rule_snapshot(
                    rule,
                    quantity=1,
                    player_count=1,
                    required_staff_count=resolved_required,
                    allowed_role_ids=[str(ROLE_IDS.get(role_key, "")) for role_key in allowed_roles],
                    specified_staff_ids=[],
                )

                if not isinstance(snapshot, dict):
                    errors.append(f"{key}: snapshot is not dict")

                if int(snapshot.get("version", 0) or 0) <= 0:
                    errors.append(f"{key}: snapshot version missing")

                if "rule" not in snapshot:
                    errors.append(f"{key}: snapshot missing rule")

                if "resolved" not in snapshot:
                    errors.append(f"{key}: snapshot missing resolved")

            except Exception as exc:
                errors.append(f"{key}: build_order_rule_snapshot failed: {type(exc).__name__}: {exc}")

    title("SOURCE_LOCATION")
    print("services.order_rules:", inspect.getfile(order_rules))

    title("WARNINGS")
    if warnings:
        for warning in warnings:
            print("WARNING:", warning)
    else:
        print("NONE")

    title("ERRORS")
    if errors:
        for error in errors:
            print("ERROR:", error)

        raise SystemExit(1)

    print("NONE")

    title("REPORT_DONE")
    print("ORDER_RULES_AUDIT_PASS")


if __name__ == "__main__":
    main()
