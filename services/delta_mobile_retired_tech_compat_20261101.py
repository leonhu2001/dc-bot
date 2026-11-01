from __future__ import annotations


_LEGACY_MOBILE_TECH_DETAILS = (
    {
        "label": "機密",
        "value": "mobile_secret_single",
        "rule_key": "basic_mobile_tech_secret_single",
        "quantity_unit": "小時",
        "min_quantity": 1,
        "max_quantity": 24,
    },
    {
        "label": "絕密",
        "value": "mobile_topsecret_single",
        "rule_key": "basic_mobile_tech_topsecret_single",
        "quantity_unit": "小時",
        "min_quantity": 1,
        "max_quantity": 24,
    },
)


def install_delta_mobile_retired_tech_compat_20261101() -> None:
    """Resolve pre-deploy handheld tech selections without exposing a new entry.

    The public/self-service group itself is removed by the result-catalog installer.
    This resolver exists only so an interaction panel opened before deployment can
    still finish or be cancelled cleanly instead of becoming an unresolvable state.
    """
    from services import orders

    if getattr(orders, "_delta_mobile_retired_tech_compat_installed", False):
        return

    original = orders.get_order_item_details_for_group

    def get_order_item_details_for_group(category, group_label):
        if (
            str(category or "") == "delta_mobile_basic"
            and str(group_label or "") == "技術陪"
        ):
            return [dict(item) for item in _LEGACY_MOBILE_TECH_DETAILS]
        return original(category, group_label)

    orders.get_order_item_details_for_group = get_order_item_details_for_group
    orders._delta_mobile_retired_tech_compat_installed = True


__all__ = ["install_delta_mobile_retired_tech_compat_20261101"]
