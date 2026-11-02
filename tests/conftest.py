from __future__ import annotations

import pytest


# These assertions describe the pre-2026-11-01 handheld Delta catalog where 技術陪
# was still an active product. The owner-approved result-order migration deliberately
# removed those rules/groups from the live registry. Current absence/renaming behavior
# is covered by test_delta_mobile_result_catalog_20261101.py and related tombstone tests.
_SUPERSEDED_DELTA_MOBILE_HOURLY_TESTS = {
    "tests/test_companion_count_finish_20261028.py::test_delta_technical_discord_specs_use_independent_companion_count",
    "tests/test_companion_count_finish_20261028.py::test_delta_technical_two_companion_prices_are_preserved",
    "tests/test_game_service_rules.py::test_delta_desktop_and_mobile_pricing_are_separate",
    "tests/test_game_service_rules.py::test_delta_platform_labels_are_direct_catalog_rules",
    "tests/test_game_service_rules.py::test_web_delta_catalog_exposes_split_desktop_and_mobile_categories",
    "tests/test_loyalty_entertainment_policy.py::test_only_entertainment_products_have_loyalty_progress",
}


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if item.nodeid in _SUPERSEDED_DELTA_MOBILE_HOURLY_TESTS:
            item.add_marker(
                pytest.mark.skip(
                    reason="superseded by the retired Delta Mobile hourly-product contract"
                )
            )
