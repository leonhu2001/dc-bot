from pathlib import Path

path = Path("services/self_service_runtime.py")
source = path.read_text(encoding="utf-8")

replacements = [
    ('        "POINT_REDEEM_ITEMS_BY_KEY",\n        "_to_int",\n        "allocate_store_absorbed_fixed_discount",\n',
     '        "POINT_REDEEM_ITEMS_BY_KEY",\n        "allocate_store_absorbed_fixed_discount",\n'),
    ('            to_int=namespace["_to_int"],\n',
     '            to_int=_to_int,\n'),
    ('        "ORDER_CATEGORY_LABELS",\n        "ORDER_ITEM_GROUPS_BY_CATEGORY",\n',
     '        "ORDER_ITEM_GROUPS_BY_CATEGORY",\n'),
    ('        "_get_order_rule_by_item_label",\n        "_to_int",\n        "build_ticket_channel_name",\n',
     '        "_get_order_rule_by_item_label",\n        "build_ticket_channel_name",\n'),
    ('        "get_self_service_quantity_meta",\n        "get_taipei_now_iso",\n        "remember_order_data",\n        "save_bot_data",\n        "send_order_log",\n',
     '        "get_self_service_quantity_meta",\n        "send_order_log",\n'),
    ('            order_category_labels=namespace["ORDER_CATEGORY_LABELS"],\n',
     '            order_category_labels=ORDER_CATEGORY_LABELS,\n'),
    ('            to_int=namespace["_to_int"],\n',
     '            to_int=_to_int,\n'),
    ('            taipei_now_iso=namespace["get_taipei_now_iso"],\n',
     '            taipei_now_iso=get_taipei_now_iso,\n'),
    ('            remember_data=namespace["remember_order_data"],\n            save_data=namespace["save_bot_data"],\n',
     '            remember_data=remember_order_data,\n            save_data=save_bot_data,\n'),
    ('        "SELF_SERVICE_ORDER_SELECTIONS",\n        "POINT_REDEEM_ITEMS",\n        "_to_int",\n        "remember_order_data",\n',
     '        "SELF_SERVICE_ORDER_SELECTIONS",\n        "POINT_REDEEM_ITEMS",\n'),
    ('            remember_data=namespace["remember_order_data"],\n',
     '            remember_data=remember_order_data,\n'),
    ('            to_int=namespace["_to_int"],\n',
     '            to_int=_to_int,\n'),
]

for old, new in replacements:
    if old not in source:
        raise SystemExit(f"expected block not found: {old!r}")
    source = source.replace(old, new, 1)

path.write_text(source, encoding="utf-8")
