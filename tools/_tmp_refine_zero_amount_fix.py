from pathlib import Path

root = Path(__file__).resolve().parents[1]


def replace_once(path, old, new):
    p = root / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise RuntimeError(f"missing anchor: {path}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "services/rewards.py",
    '''    if amount <= 0:\n        # 0T is a valid final customer-pay amount (for example a fully covered\n        # member coupon), not a parse failure. Mark reward handling complete so\n        # closing the order does not warn that reward processing was skipped.\n        # Keep reward_excluded=False so a later amount correction can still add\n        # the proper spend/points through sync_reward_counted_order_amount().\n        order_data["reward_counted"] = True\n        order_data["reward_amount"] = 0\n        order_data["reward_zero_amount"] = True\n        order_data["reward_excluded"] = False\n        order_data["reward_excluded_reason"] = ""\n        order_data["reward_counted_at"] = get_taipei_now_iso()\n        if _SAVE_BOT_DATA is not None:\n            _SAVE_BOT_DATA()\n        return "顧客實付為 0T，本單不增加會員累積消費或點數。"\n''',
    '''    if amount <= 0:\n        # 0T is a valid completed order (for example a fully covered member\n        # coupon). It counts as an order, but it must add neither spend nor\n        # points. Keep reward_excluded=False so a later amount correction can\n        # still add the proper spend/points without incrementing order_count twice.\n        data = get_customer_reward_data(customer_id)\n        data["order_count"] = int(data.get("order_count", 0) or 0) + 1\n        data["last_order_at"] = get_taipei_now_iso()\n        data["points"] = get_current_reward_points(data)\n\n        order_data["reward_counted"] = True\n        order_data["reward_amount"] = 0\n        order_data["reward_zero_amount"] = True\n        order_data["reward_excluded"] = False\n        order_data["reward_excluded_reason"] = ""\n        order_data["reward_counted_at"] = get_taipei_now_iso()\n        _ORDER_SELECTIONS[order_channel_id] = order_data\n        if _SAVE_BOT_DATA is not None:\n            _SAVE_BOT_DATA()\n        return "會員紀錄已更新：完成訂單 +1；顧客實付為 0T，不增加累積消費或點數。"\n''',
)

replace_once(
    "services/rewards.py",
    '''        order_data["reward_amount"] = new_amount\n\n    order_data["amount"] = new_amount\n''',
    '''        order_data["reward_amount"] = new_amount\n        if new_amount <= 0:\n            order_data["reward_zero_amount"] = True\n        else:\n            order_data.pop("reward_zero_amount", None)\n\n    order_data["amount"] = new_amount\n''',
)

replace_once(
    "services/order_payment_runtime.py",
    '''                dispatch_embed.add_field(name="付款狀態", value="已付款，接單人員已確認", inline=False)\n''',
    '''                dispatch_embed.add_field(\n                    name="付款狀態",\n                    value=(\n                        "免付款，接單人員已確認"\n                        if zero_amount_order\n                        else "已付款，接單人員已確認"\n                    ),\n                    inline=False,\n                )\n''',
)

p = root / "tests/test_zero_amount_checkout.py"
text = p.read_text(encoding="utf-8")
text = text.replace(
    '''    assert reward_data["total_spent"] == 2000\n    assert rewards.get_current_reward_points(reward_data) == 20\n''',
    '''    assert reward_data["total_spent"] == 2000\n    assert reward_data["order_count"] == 1\n    assert reward_data["last_order_at"]\n    assert rewards.get_current_reward_points(reward_data) == 20\n''',
    1,
)
text = text.replace(
    '''    assert order_data["reward_amount"] == 500\n''',
    '''    assert order_data["reward_amount"] == 500\n    assert "reward_zero_amount" not in order_data\n''',
    1,
)
p.write_text(text, encoding="utf-8")
