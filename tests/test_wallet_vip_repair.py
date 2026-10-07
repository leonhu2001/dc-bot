from datetime import datetime, timedelta, timezone

from scripts.repair_wallet_vip_double_count import _find_candidates


TAIPEI = timezone(timedelta(hours=8))


def test_wallet_vip_repair_only_targets_post_topup_double_counts():
    cutoff = datetime(2026, 10, 7, 18, 0, tzinfo=TAIPEI)
    customer_id = 518091739156971520
    orders = {
        1: {
            "customer_id": customer_id,
            "order_no": "MO-WRONG",
            "payment_method": "我的錢包",
            "status": "closed",
            "reward_counted": True,
            "reward_excluded": False,
            "reward_amount": 600,
            "reward_counted_at": "2026-10-07T18:05:00+08:00",
        },
        2: {
            "customer_id": customer_id,
            "order_no": "MO-BEFORE",
            "payment_method": "我的錢包",
            "status": "closed",
            "reward_counted": True,
            "reward_excluded": False,
            "reward_amount": 300,
            "reward_counted_at": "2026-10-07T17:55:00+08:00",
        },
        3: {
            "customer_id": customer_id,
            "order_no": "MO-ALREADY-EXCLUDED",
            "payment_method": "我的錢包",
            "status": "closed",
            "reward_counted": True,
            "reward_excluded": True,
            "reward_amount": 0,
            "reward_counted_at": "2026-10-07T18:06:00+08:00",
        },
        4: {
            "customer_id": customer_id,
            "order_no": "MO-BANK",
            "payment_method": "銀行轉帳",
            "status": "closed",
            "reward_counted": True,
            "reward_excluded": False,
            "reward_amount": 900,
            "reward_counted_at": "2026-10-07T18:07:00+08:00",
        },
        5: {
            "customer_id": customer_id,
            "order_no": "MO-UNDATED",
            "payment_method": "我的錢包",
            "status": "closed",
            "reward_counted": True,
            "reward_excluded": False,
            "reward_amount": 200,
        },
    }

    candidates, undated = _find_candidates(
        orders=orders,
        customer_id=customer_id,
        cutoff=cutoff,
    )

    assert [(channel_id, amount) for channel_id, _, amount, _ in candidates] == [
        (1, 600),
    ]
    assert [channel_id for channel_id, _ in undated] == [5]
