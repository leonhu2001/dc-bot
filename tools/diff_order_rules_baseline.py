from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(os.environ.get("DC_BOT_ROOT", "/opt/dc-bot"))
BASELINE_PATH = Path(os.environ.get("ORDER_RULES_BASELINE", str(ROOT / "tools" / "order_rules_baseline.json")))


def title(text: str) -> None:
    print("\n" + "=" * 100)
    print(text)
    print("=" * 100)


def load_current_snapshot() -> dict:
    from tools.dump_order_rules_baseline import build_baseline
    return build_baseline()


def normalize(value):
    if isinstance(value, dict):
        return {str(key): normalize(item) for key, item in sorted(value.items())}

    if isinstance(value, list):
        return [normalize(item) for item in value]

    return value


def main() -> None:
    title("ORDER_RULES_BASELINE_DIFF")

    if not BASELINE_PATH.exists():
        raise SystemExit(f"baseline not found: {BASELINE_PATH}")

    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    current = load_current_snapshot()

    baseline_rules = baseline.get("rules", {}) or {}
    current_rules = current.get("rules", {}) or {}

    baseline_keys = set(baseline_rules)
    current_keys = set(current_rules)

    added = sorted(current_keys - baseline_keys)
    removed = sorted(baseline_keys - current_keys)
    shared = sorted(current_keys & baseline_keys)

    changed: list[tuple[str, list[str]]] = []

    fields_to_compare = [
        "category",
        "label",
        "price_type",
        "price",
        "unit_label",
        "min_quantity",
        "max_quantity",
        "allowed_roles",
        "allowed_role_ids",
        "required_staff_count",
        "resolved_required_staff_count_at_player_1",
        "min_protector_count",
        "allow_specify",
        "max_specified_count",
        "point_benefits_allowed",
        "price_at_min_quantity",
    ]

    for key in shared:
        changed_fields = []

        for field in fields_to_compare:
            old_value = normalize(baseline_rules[key].get(field))
            new_value = normalize(current_rules[key].get(field))

            if old_value != new_value:
                changed_fields.append(field)

        if changed_fields:
            changed.append((key, changed_fields))

    title("SUMMARY")
    print("BASELINE_RULE_COUNT:", len(baseline_rules))
    print("CURRENT_RULE_COUNT:", len(current_rules))
    print("ADDED:", len(added))
    print("REMOVED:", len(removed))
    print("CHANGED:", len(changed))

    title("ADDED_RULES")
    if added:
        for key in added:
            print(key)
    else:
        print("NONE")

    title("REMOVED_RULES")
    if removed:
        for key in removed:
            print(key)
    else:
        print("NONE")

    title("CHANGED_RULES")
    if changed:
        for key, fields in changed:
            print(f"{key}: {', '.join(fields)}")

            old_rule = baseline_rules[key]
            new_rule = current_rules[key]

            for field in fields:
                print(f"  - {field}")
                print(f"    OLD: {old_rule.get(field)}")
                print(f"    NEW: {new_rule.get(field)}")

        raise SystemExit(1)

    print("NONE")

    title("REPORT_DONE")
    print("ORDER_RULES_BASELINE_DIFF_PASS")


if __name__ == "__main__":
    main()
