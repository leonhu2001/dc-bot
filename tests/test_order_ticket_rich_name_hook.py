from __future__ import annotations

import inspect

from services import order_ticket_name_restore_runtime as names
from services import order_ticket_ui_policy as policy


def test_order_ticket_policy_installs_post_payment_rich_rename() -> None:
    source = inspect.getsource(policy.install_order_ticket_ui_policy)

    assert "from services import order_runtime" in source
    assert "install_payment_finalize_rename_policy(order_runtime)" in source
    assert source.index("install_payment_finalize_rename_policy(order_runtime)") < source.index(
        "_INSTALLED = True"
    )


def test_payment_finalize_hook_rebinds_order_runtime_alias() -> None:
    source = inspect.getsource(policy.install_payment_finalize_rename_policy)

    assert "payment_runtime.finalize_accepted_pending_payment = finalize_with_paid_ticket_rename" in source
    assert "order_runtime.finalize_accepted_pending_payment = finalize_with_paid_ticket_rename" in source
    assert "names._rename_quick_ticket_from_data" in source


def test_rich_order_prefix_keeps_game_category_and_playstyle() -> None:
    prefix = names._order_prefix(
        {
            "category": "valorant",
            "item_group": "積分",
        },
        "active",
    )

    assert "特戰英豪" in prefix
    assert "積分" in prefix
