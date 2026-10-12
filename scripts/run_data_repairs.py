#!/usr/bin/env python3
"""Run idempotent historical data repairs explicitly.

This command is intentionally separate from application startup. It is safe to
run after the deployment backup has been taken; each repair implementation is
responsible for its own idempotency marker and transaction rollback.
"""

from __future__ import annotations

import argparse
import json

from services.authorized_order_cleanup import purge_authorized_test_orders
from services.data_repairs import apply_known_data_repairs
from shared.db import engine


def run_known_repairs() -> list[dict]:
    return list(apply_known_data_repairs())


def run_authorized_test_cleanup() -> dict:
    return dict(purge_authorized_test_orders(engine))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run explicit idempotent production data repairs.",
    )
    parser.add_argument(
        "--include-authorized-test-cleanup",
        action="store_true",
        help=(
            "Also run the owner-authorized historical test-order cleanup. "
            "This is kept opt-in so normal repair runs never delete orders."
        ),
    )
    args = parser.parse_args()

    results: dict[str, object] = {
        "known_repairs": run_known_repairs(),
    }

    if args.include_authorized_test_cleanup:
        results["authorized_test_cleanup"] = run_authorized_test_cleanup()

    print(json.dumps(results, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
