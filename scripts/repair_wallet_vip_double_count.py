from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core import database
from core.vip_levels import BASE_MEMBER_LEVELS
import services.rewards as rewards
from services.topups import list_customer_topups


WALLET_PAYMENT_METHOD = "我的錢包"
TAIPEI_TZ = timezone(timedelta(hours=8))
BOT_SERVICE = "dc-bot.service"
WEB_SERVICE = "dc-bot-dashboard.service"


def _to_int(value, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _parse_datetime(value) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None

    if text.endswith("Z"):
        text = text[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=TAIPEI_TZ)

    return parsed.astimezone(TAIPEI_TZ)


def _service_is_active(service_name: str) -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", service_name],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except OSError:
        return False

    return result.returncode == 0


def _backup_database(bot_path: Path) -> Path:
    stamp = datetime.now(TAIPEI_TZ).strftime("%Y%m%d_%H%M%S")
    backup_dir = bot_path.parent / "_archive" / f"wallet_vip_repair_{stamp}"
    backup_dir.mkdir(parents=True, exist_ok=False)
    backup_path = backup_dir / bot_path.name
    shutil.copy2(bot_path, backup_path)
    return backup_path


def _configure_runtime(root: Path):
    bot_path = root / "bot.db"
    if not bot_path.exists():
        raise RuntimeError(f"找不到資料庫：{bot_path}")

    orders: dict[int, dict] = {}
    claims: dict[int, dict] = {}
    customers: dict[int, dict] = {}
    counters: dict[str, int] = {}

    database.configure_database(
        bot_path,
        database.init_database,
        backup_dir=root / "_archive",
        data_file=root / "bot_data.json",
    )
    rewards.configure_rewards(
        member_levels=[dict(level) for level in BASE_MEMBER_LEVELS],
        reward_point_divisor=100,
    )
    database.configure_data_access(
        orders,
        claims,
        customers,
        counters,
        database.save_bot_data,
        member_levels=[dict(level) for level in BASE_MEMBER_LEVELS],
        get_member_level_index_by_total_spent_func=rewards.get_member_level_index_by_total_spent,
        get_current_reward_points_func=rewards.get_current_reward_points,
        calculate_reward_points_func=rewards.calculate_reward_points,
        get_effective_member_level_func=rewards.get_effective_member_level,
    )
    rewards.configure_reward_storage(customers)
    rewards.configure_reward_order_context(orders, database.save_bot_data)

    if not database.load_bot_data_from_sqlite():
        raise RuntimeError("bot.db 內沒有可載入的 Bot 訂單／會員資料。")

    return bot_path, orders, customers


def _latest_completed_topup(customer_id: int, bot_path: Path) -> dict | None:
    rows = list_customer_topups(
        customer_id,
        limit=100,
        db_file=bot_path,
    )
    completed = [
        row
        for row in rows
        if str(row.get("status") or "").strip() == "completed"
    ]
    if not completed:
        return None

    return max(
        completed,
        key=lambda row: (
            _parse_datetime(
                row.get("completed_at")
                or row.get("updated_at")
                or row.get("approved_at")
                or row.get("created_at")
            )
            or datetime.min.replace(tzinfo=TAIPEI_TZ),
            int(row.get("id") or 0),
        ),
    )


def _order_event_time(order_data: dict) -> datetime | None:
    for key in (
        "reward_counted_at",
        "closed_at",
        "updated_at",
        "created_at",
    ):
        parsed = _parse_datetime(order_data.get(key))
        if parsed is not None:
            return parsed
    return None


def _find_candidates(
    *,
    orders: dict[int, dict],
    customer_id: int,
    cutoff: datetime | None,
) -> tuple[list[tuple[int, dict, int, datetime | None]], list[tuple[int, dict]]]:
    candidates: list[tuple[int, dict, int, datetime | None]] = []
    undated: list[tuple[int, dict]] = []

    for channel_id, order_data in orders.items():
        if not isinstance(order_data, dict):
            continue
        if _to_int(order_data.get("customer_id")) != customer_id:
            continue
        if str(order_data.get("payment_method") or "").strip() != WALLET_PAYMENT_METHOD:
            continue
        if not bool(order_data.get("reward_counted")):
            continue
        if bool(order_data.get("reward_excluded")):
            continue

        wrong_amount = max(
            0,
            int(
                _to_int(
                    order_data.get("reward_amount"),
                    _to_int(order_data.get("amount"), 0),
                )
                or 0
            ),
        )
        if wrong_amount <= 0:
            continue

        # Current order status is not authoritative for this repair. A historical
        # order can be reward-counted/closed and later move to another state such
        # as "stored". Once a wallet order has a positive reward_amount, it is a
        # double-count candidate regardless of its later status because wallet
        # principal was already counted when the topup completed.
        event_time = _order_event_time(order_data)
        if event_time is None:
            undated.append((int(channel_id), order_data))
            continue

        if cutoff is not None and event_time < cutoff:
            continue

        candidates.append((int(channel_id), order_data, wrong_amount, event_time))

    candidates.sort(
        key=lambda item: (
            item[3] or datetime.min.replace(tzinfo=TAIPEI_TZ),
            item[0],
        )
    )
    return candidates, undated


def repair(
    *,
    root: Path,
    customer_id: int,
    apply: bool,
) -> int:
    bot_path, orders, customers = _configure_runtime(root)

    customer = customers.get(customer_id)
    if not isinstance(customer, dict):
        raise RuntimeError(f"找不到會員資料：{customer_id}")

    latest_topup = _latest_completed_topup(customer_id, bot_path)
    cutoff = None
    if latest_topup is not None:
        cutoff = _parse_datetime(
            latest_topup.get("completed_at")
            or latest_topup.get("updated_at")
            or latest_topup.get("approved_at")
            or latest_topup.get("created_at")
        )

    candidates, undated = _find_candidates(
        orders=orders,
        customer_id=customer_id,
        cutoff=cutoff,
    )

    current_total = int(customer.get("total_spent", 0) or 0)
    current_points = rewards.get_current_reward_points(customer)
    current_level = rewards.get_effective_member_level(customer)

    print(f"Customer: {customer_id}")
    print(
        "Current: "
        f"total_spent={current_total:,}T, "
        f"points={current_points:,}, "
        f"level={current_level['name']}"
    )

    if latest_topup is None:
        print("Latest completed topup: none")
    else:
        print(
            "Latest completed topup: "
            f"{latest_topup.get('topup_no')} / "
            f"{int(latest_topup.get('amount') or 0):,}T / "
            f"{latest_topup.get('completed_at') or latest_topup.get('updated_at') or 'unknown time'}"
        )

    if undated:
        print("\nSkipped undated wallet orders (manual review required):")
        for channel_id, order_data in undated:
            print(
                f"- channel={channel_id} "
                f"order={order_data.get('order_no') or '-'} "
                f"reward_amount={int(_to_int(order_data.get('reward_amount'), 0) or 0):,}T"
            )

    if not candidates:
        print("\nNo post-topup wallet reward double-count candidates found.")
        return 0

    wrong_total = sum(item[2] for item in candidates)
    expected_total = max(0, current_total - wrong_total)

    print("\nRepair candidates:")
    for channel_id, order_data, wrong_amount, event_time in candidates:
        print(
            f"- {order_data.get('order_no') or channel_id}: "
            f"{wrong_amount:,}T / "
            f"status={order_data.get('status') or '-'} / "
            f"reward_counted_at={order_data.get('reward_counted_at') or '-'} / "
            f"event={event_time.isoformat(timespec='seconds') if event_time else '-'}"
        )

    print(
        f"\nPlanned correction: -{wrong_total:,}T VIP cumulative spend "
        f"({current_total:,}T -> {expected_total:,}T)."
    )

    if not apply:
        print(
            "Dry run only. No data changed. "
            "Re-run with --apply after stopping Bot/Web services."
        )
        return 0

    active_services = [
        service
        for service in (BOT_SERVICE, WEB_SERVICE)
        if _service_is_active(service)
    ]
    if active_services:
        raise RuntimeError(
            "拒絕在線修資料；請先停止服務："
            + ", ".join(active_services)
        )

    backup_path = _backup_database(bot_path)
    print(f"Backup: {backup_path}")

    for channel_id, order_data, wrong_amount, _ in candidates:
        rewards.correct_customer_reward_amount(
            customer_id,
            wrong_amount,
            0,
        )
        order_data["reward_amount"] = 0
        order_data["reward_excluded"] = True
        order_data["reward_excluded_reason"] = (
            "歷史修復：錢包付款已由儲值本金累積 VIP，不應再次累積"
        )
        order_data["wallet_vip_repaired_at"] = datetime.now(TAIPEI_TZ).isoformat(
            timespec="seconds"
        )
        orders[channel_id] = order_data

    database.save_bot_data()

    repaired_customer = customers[customer_id]
    repaired_total = int(repaired_customer.get("total_spent", 0) or 0)
    repaired_points = rewards.get_current_reward_points(repaired_customer)
    repaired_level = rewards.get_effective_member_level(repaired_customer)

    if repaired_total != expected_total:
        raise RuntimeError(
            "修復後累積金額驗證失敗："
            f"expected={expected_total}, actual={repaired_total}"
        )

    print(
        "Applied: "
        f"total_spent={repaired_total:,}T, "
        f"points={repaired_points:,}, "
        f"level={repaired_level['name']}"
    )
    print(
        f"Marked {len(candidates)} wallet order(s) as reward_excluded. "
        "Wallet balances, order prices, and topup records were not changed."
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Repair VIP cumulative spend that was double-counted by wallet-paid orders "
            "after the customer's latest completed topup."
        )
    )
    parser.add_argument("customer_id", type=int, help="Discord customer ID")
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply validated changes. Default is dry-run.",
    )
    args = parser.parse_args()

    try:
        return repair(
            root=args.root.resolve(),
            customer_id=int(args.customer_id),
            apply=bool(args.apply),
        )
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
