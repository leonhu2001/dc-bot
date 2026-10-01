from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

from shared.payout import calculate_order_payout


OPEN_ACCOUNTING_ORDER_STATUSES = {"active", "stored", "closed"}
TERMINAL_ORDER_STATUSES = {"cancelled", "canceled"}
TIP_REFERENCE_RE = re.compile(r":TIP-(\d+)$", re.IGNORECASE)


def _connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(
        f"file:{path}?mode=ro",
        uri=True,
        timeout=3.0,
    )
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (str(table),),
    ).fetchone()
    return row is not None


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value if value is not None else default)
    except (TypeError, ValueError):
        return int(default)


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value if value is not None else default)
    except (TypeError, ValueError):
        return float(default)


def _money_equal(left: Any, right: Any, tolerance: float = 0.01) -> bool:
    return abs(_as_float(left) - _as_float(right)) <= float(tolerance)


def _normalize(value: Any) -> str:
    return str(value or "").strip()


def _issue(
    issues: list[dict[str, Any]],
    *,
    category: str,
    code: str,
    severity: str,
    reference: str,
    title: str,
    detail: str,
    expected: Any = None,
    actual: Any = None,
) -> None:
    issues.append(
        {
            "category": str(category),
            "code": str(code),
            "severity": str(severity),
            "reference": str(reference),
            "title": str(title),
            "detail": str(detail),
            "expected": expected,
            "actual": actual,
        }
    )


def _load_wallet_state(
    bot: sqlite3.Connection,
    issues: list[dict[str, Any]],
) -> tuple[
    dict[int, dict[str, Any]],
    dict[tuple[str, str, str], list[dict[str, Any]]],
]:
    if not _table_exists(bot, "wallet_transactions"):
        _issue(
            issues,
            category="wallet",
            code="wallet_transactions_missing",
            severity="critical",
            reference="bot.db",
            title="錢包流水表不存在",
            detail="找不到 wallet_transactions，無法執行錢包對帳。",
        )
        return {}, {}

    wallet_rows: dict[str, int] = {}
    if _table_exists(bot, "customer_wallets"):
        wallet_rows = {
            str(row["customer_discord_id"]): _as_int(row["balance"])
            for row in bot.execute(
                """
                SELECT customer_discord_id, balance
                FROM customer_wallets
                """
            ).fetchall()
        }

    tx_by_id: dict[int, dict[str, Any]] = {}
    tx_by_reference: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    tx_by_customer: dict[str, list[dict[str, Any]]] = defaultdict(list)

    rows = bot.execute(
        """
        SELECT
            id,
            customer_discord_id,
            amount,
            balance_before,
            balance_after,
            type,
            order_no,
            order_channel_id,
            created_at
        FROM wallet_transactions
        ORDER BY customer_discord_id ASC, id ASC
        """
    ).fetchall()

    for row in rows:
        tx = dict(row)
        tx_id = _as_int(tx["id"])
        customer_id = _normalize(tx["customer_discord_id"])
        tx_type = _normalize(tx["type"])
        order_no = _normalize(tx["order_no"])

        tx_by_id[tx_id] = tx
        tx_by_customer[customer_id].append(tx)

        if order_no:
            tx_by_reference[(customer_id, order_no, tx_type)].append(tx)

        before = _as_int(tx["balance_before"])
        amount = _as_int(tx["amount"])
        after = _as_int(tx["balance_after"])

        if before + amount != after:
            _issue(
                issues,
                category="wallet",
                code="wallet_transaction_math",
                severity="critical",
                reference=f"WALLET-TX-{tx_id}",
                title="錢包流水加減不成立",
                detail=(
                    f"顧客 {customer_id} 的流水 #{tx_id} 無法滿足 "
                    "balance_before + amount = balance_after。"
                ),
                expected=before + amount,
                actual=after,
            )

        if customer_id not in wallet_rows:
            _issue(
                issues,
                category="wallet",
                code="wallet_transaction_without_wallet",
                severity="critical",
                reference=f"WALLET-TX-{tx_id}",
                title="流水存在但錢包帳戶不存在",
                detail=f"顧客 {customer_id} 有錢包流水，但 customer_wallets 沒有對應帳戶。",
            )

    for customer_id, customer_txs in tx_by_customer.items():
        previous_after: int | None = None

        for tx in customer_txs:
            tx_id = _as_int(tx["id"])
            before = _as_int(tx["balance_before"])
            after = _as_int(tx["balance_after"])

            if previous_after is not None and before != previous_after:
                _issue(
                    issues,
                    category="wallet",
                    code="wallet_chain_break",
                    severity="critical",
                    reference=f"WALLET-TX-{tx_id}",
                    title="錢包流水鏈斷裂",
                    detail=(
                        f"顧客 {customer_id} 的上一筆 balance_after "
                        "與本筆 balance_before 不一致。"
                    ),
                    expected=previous_after,
                    actual=before,
                )

            previous_after = after

        if customer_txs and customer_id in wallet_rows:
            latest_after = _as_int(customer_txs[-1]["balance_after"])
            current_balance = _as_int(wallet_rows[customer_id])

            if latest_after != current_balance:
                _issue(
                    issues,
                    category="wallet",
                    code="wallet_balance_drift",
                    severity="critical",
                    reference=f"WALLET-{customer_id}",
                    title="錢包餘額與最後流水不一致",
                    detail=f"顧客 {customer_id} 的目前餘額不等於最後一筆流水結餘。",
                    expected=latest_after,
                    actual=current_balance,
                )

    for reference, reference_rows in tx_by_reference.items():
        if len(reference_rows) <= 1:
            continue

        customer_id, order_no, tx_type = reference
        _issue(
            issues,
            category="wallet",
            code="wallet_duplicate_reference",
            severity="critical",
            reference=f"{order_no}:{tx_type}",
            title="重複錢包交易識別碼",
            detail=(
                f"顧客 {customer_id} 的 {order_no} / {tx_type} "
                f"共有 {len(reference_rows)} 筆流水。"
            ),
            expected=1,
            actual=len(reference_rows),
        )

    return tx_by_id, dict(tx_by_reference)


def _check_topups(
    bot: sqlite3.Connection,
    tx_by_id: dict[int, dict[str, Any]],
    issues: list[dict[str, Any]],
) -> None:
    if not _table_exists(bot, "topup_orders"):
        return

    rows = bot.execute(
        """
        SELECT
            id,
            topup_no,
            customer_discord_id,
            amount,
            status,
            rebate_amount,
            credited_amount,
            wallet_transaction_id,
            bonus_transaction_id
        FROM topup_orders
        WHERE status = 'completed'
        ORDER BY id ASC
        """
    ).fetchall()

    for row in rows:
        topup = dict(row)
        topup_id = _as_int(topup["id"])
        topup_no = _normalize(topup["topup_no"])
        customer_id = _normalize(topup["customer_discord_id"])
        amount = _as_int(topup["amount"])
        rebate = _as_int(topup["rebate_amount"])
        credited = _as_int(topup["credited_amount"])
        principal_id = _as_int(topup["wallet_transaction_id"], 0)
        bonus_id = _as_int(topup["bonus_transaction_id"], 0)
        reference = topup_no or f"TOPUP-ID-{topup_id}"

        if credited != amount + rebate:
            _issue(
                issues,
                category="topup",
                code="topup_credited_amount_mismatch",
                severity="critical",
                reference=reference,
                title="儲值實得金額不一致",
                detail="credited_amount 應等於儲值本金 + 儲值回饋。",
                expected=amount + rebate,
                actual=credited,
            )

        principal = tx_by_id.get(principal_id) if principal_id else None
        if principal is None:
            _issue(
                issues,
                category="topup",
                code="topup_principal_tx_missing",
                severity="critical",
                reference=reference,
                title="完成儲值缺少本金錢包流水",
                detail="completed 儲值單找不到 wallet_transaction_id 對應的流水。",
                expected=amount,
                actual=None,
            )
        else:
            checks = (
                ("customer_discord_id", customer_id, _normalize(principal["customer_discord_id"])),
                ("type", "topup", _normalize(principal["type"])),
                ("order_no", topup_no, _normalize(principal["order_no"])),
                ("amount", amount, _as_int(principal["amount"])),
            )
            for field, expected, actual in checks:
                if expected != actual:
                    _issue(
                        issues,
                        category="topup",
                        code=f"topup_principal_{field}_mismatch",
                        severity="critical",
                        reference=reference,
                        title="儲值本金流水資料不一致",
                        detail=f"本金流水的 {field} 與儲值單不一致。",
                        expected=expected,
                        actual=actual,
                    )

        if rebate > 0:
            bonus = tx_by_id.get(bonus_id) if bonus_id else None
            if bonus is None:
                _issue(
                    issues,
                    category="topup",
                    code="topup_bonus_tx_missing",
                    severity="critical",
                    reference=reference,
                    title="儲值回饋缺少錢包流水",
                    detail="有 rebate_amount，但找不到 bonus_transaction_id 對應流水。",
                    expected=rebate,
                    actual=None,
                )
            else:
                checks = (
                    ("customer_discord_id", customer_id, _normalize(bonus["customer_discord_id"])),
                    ("type", "topup_bonus", _normalize(bonus["type"])),
                    ("order_no", topup_no, _normalize(bonus["order_no"])),
                    ("amount", rebate, _as_int(bonus["amount"])),
                )
                for field, expected, actual in checks:
                    if expected != actual:
                        _issue(
                            issues,
                            category="topup",
                            code=f"topup_bonus_{field}_mismatch",
                            severity="critical",
                            reference=reference,
                            title="儲值回饋流水資料不一致",
                            detail=f"回饋流水的 {field} 與儲值單不一致。",
                            expected=expected,
                            actual=actual,
                        )
        elif bonus_id:
            _issue(
                issues,
                category="topup",
                code="topup_unexpected_bonus_tx",
                severity="warning",
                reference=reference,
                title="零回饋儲值卻綁定 bonus 流水",
                detail="rebate_amount 為 0，但 bonus_transaction_id 有值，請人工確認。",
                expected=None,
                actual=bonus_id,
            )


def _check_wallet_paid_orders(
    web: sqlite3.Connection,
    tx_by_reference: dict[tuple[str, str, str], list[dict[str, Any]]],
    issues: list[dict[str, Any]],
) -> None:
    if not _table_exists(web, "web_orders"):
        return

    rows = web.execute(
        """
        SELECT
            id,
            bot_order_no,
            customer_discord_id,
            amount,
            customer_pay_amount,
            payment_method,
            status
        FROM web_orders
        WHERE payment_method = '我的錢包'
          AND LOWER(COALESCE(status, '')) IN ('active', 'stored', 'closed')
        ORDER BY id ASC
        """
    ).fetchall()

    for row in rows:
        order = dict(row)
        order_id = _as_int(order["id"])
        order_no = _normalize(order["bot_order_no"])
        customer_id = _normalize(order["customer_discord_id"])
        expected_amount = -_as_int(
            order["customer_pay_amount"]
            if order["customer_pay_amount"] is not None
            else order["amount"]
        )
        reference = order_no or f"WEB-{order_id}"

        if not order_no or not customer_id:
            _issue(
                issues,
                category="order_payment",
                code="wallet_order_reference_missing",
                severity="warning",
                reference=f"WEB-{order_id}",
                title="錢包訂單缺少可對帳識別碼",
                detail="找不到 bot_order_no 或 customer_discord_id，無法比對錢包流水。",
            )
            continue

        txs = tx_by_reference.get((customer_id, order_no, "payment"), [])
        if not txs:
            _issue(
                issues,
                category="order_payment",
                code="wallet_order_tx_missing",
                severity="critical",
                reference=reference,
                title="錢包付款訂單缺少扣款流水",
                detail="訂單標記為「我的錢包」付款，但找不到 payment 流水。",
                expected=expected_amount,
                actual=None,
            )
            continue

        tx = txs[0]
        actual_amount = _as_int(tx["amount"])
        if actual_amount != expected_amount:
            _issue(
                issues,
                category="order_payment",
                code="wallet_order_amount_mismatch",
                severity="critical",
                reference=reference,
                title="訂單金額與錢包扣款不一致",
                detail="payment 流水金額與 customer_pay_amount 不一致。",
                expected=expected_amount,
                actual=actual_amount,
            )


def _check_worker_tips(
    web: sqlite3.Connection,
    tx_by_id: dict[int, dict[str, Any]],
    issues: list[dict[str, Any]],
) -> set[int]:
    referenced_wallet_tx_ids: set[int] = set()

    if not _table_exists(web, "worker_tips"):
        return referenced_wallet_tx_ids

    rows = web.execute(
        """
        SELECT
            id,
            receipt_id,
            customer_discord_id,
            worker_discord_id,
            amount,
            payment_method,
            payment_status,
            payout_status,
            wallet_transaction_id
        FROM worker_tips
        ORDER BY id ASC
        """
    ).fetchall()

    for row in rows:
        tip = dict(row)
        tip_id = _as_int(tip["id"])
        reference = f"TIP-{tip_id}"
        payment_method = _normalize(tip["payment_method"])
        payment_status = _normalize(tip["payment_status"]).lower()
        customer_id = _normalize(tip["customer_discord_id"])
        amount = _as_int(tip["amount"])
        tx_id = _as_int(tip["wallet_transaction_id"], 0)

        if tx_id:
            referenced_wallet_tx_ids.add(tx_id)

        if payment_method == "我的錢包" and payment_status == "paid":
            tx = tx_by_id.get(tx_id) if tx_id else None
            if tx is None:
                _issue(
                    issues,
                    category="tip",
                    code="tip_wallet_tx_missing",
                    severity="critical",
                    reference=reference,
                    title="已付款雞腿缺少錢包流水",
                    detail="我的錢包雞腿已標記 paid，但 wallet_transaction_id 無效。",
                    expected=-amount,
                    actual=None,
                )
                continue

            tx_order_no = _normalize(tx["order_no"])
            checks = (
                ("customer_discord_id", customer_id, _normalize(tx["customer_discord_id"])),
                ("type", "tip_payment", _normalize(tx["type"])),
                ("amount", -amount, _as_int(tx["amount"])),
            )
            for field, expected, actual in checks:
                if expected != actual:
                    _issue(
                        issues,
                        category="tip",
                        code=f"tip_wallet_{field}_mismatch",
                        severity="critical",
                        reference=reference,
                        title="雞腿錢包流水資料不一致",
                        detail=f"雞腿流水的 {field} 與 worker_tips 不一致。",
                        expected=expected,
                        actual=actual,
                    )

            match = TIP_REFERENCE_RE.search(tx_order_no)
            actual_tip_id = _as_int(match.group(1)) if match else 0
            if actual_tip_id != tip_id:
                _issue(
                    issues,
                    category="tip",
                    code="tip_wallet_reference_mismatch",
                    severity="critical",
                    reference=reference,
                    title="雞腿錢包 reference 不一致",
                    detail="tip_payment 的 order_no 尾碼沒有指向這筆 TIP。",
                    expected=tip_id,
                    actual=actual_tip_id or tx_order_no,
                )

        elif payment_status in {"pending", "pending_review", "cancelled"} and tx_id:
            _issue(
                issues,
                category="tip",
                code="tip_unsettled_has_wallet_tx",
                severity="critical",
                reference=reference,
                title="未完成雞腿卻綁定錢包扣款",
                detail=f"payment_status={payment_status}，但 wallet_transaction_id={tx_id}。",
                expected=None,
                actual=tx_id,
            )

    return referenced_wallet_tx_ids


def _check_orphan_tip_wallet_transactions(
    tx_by_id: dict[int, dict[str, Any]],
    referenced_wallet_tx_ids: set[int],
    issues: list[dict[str, Any]],
) -> None:
    for tx_id, tx in tx_by_id.items():
        if _normalize(tx["type"]) != "tip_payment":
            continue

        if tx_id in referenced_wallet_tx_ids:
            continue

        _issue(
            issues,
            category="tip",
            code="orphan_tip_wallet_transaction",
            severity="critical",
            reference=f"WALLET-TX-{tx_id}",
            title="雞腿扣款流水沒有對應 worker_tip",
            detail=(
                f"tip_payment 流水 reference={_normalize(tx['order_no']) or '-'} "
                "沒有任何 worker_tips.wallet_transaction_id 指向它。"
            ),
        )


def _check_payouts(
    web: sqlite3.Connection,
    issues: list[dict[str, Any]],
) -> None:
    required_tables = {
        "web_orders",
        "order_assignments",
        "worker_payouts",
        "customer_service_payouts",
    }
    if not all(_table_exists(web, table) for table in required_tables):
        return

    overrides_by_order: dict[int, dict[str, int]] = defaultdict(dict)
    if _table_exists(web, "worker_payout_overrides"):
        for row in web.execute(
            """
            SELECT order_id, worker_discord_id, manual_final_payout
            FROM worker_payout_overrides
            """
        ).fetchall():
            overrides_by_order[_as_int(row["order_id"])][
                _normalize(row["worker_discord_id"])
            ] = _as_int(row["manual_final_payout"])

    orders = web.execute(
        """
        SELECT
            id,
            bot_order_no,
            status,
            amount,
            payout_base_amount,
            payment_method
        FROM web_orders
        WHERE LOWER(COALESCE(status, '')) IN (
            'active',
            'stored',
            'closed',
            'cancelled',
            'canceled'
        )
        ORDER BY id ASC
        """
    ).fetchall()

    for order_row in orders:
        order = dict(order_row)
        order_id = _as_int(order["id"])
        status = _normalize(order["status"]).lower()
        reference = _normalize(order["bot_order_no"]) or f"WEB-{order_id}"

        stored_from_status = ""
        if status == "stored" and _table_exists(web, "order_state_history"):
            history_row = web.execute(
                """
                SELECT from_status
                FROM order_state_history
                WHERE order_id = ?
                  AND to_status = 'stored'
                ORDER BY id DESC
                LIMIT 1
                """,
                (order_id,),
            ).fetchone()
            if history_row is not None:
                stored_from_status = _normalize(history_row["from_status"]).lower()

        assignments = [
            dict(row)
            for row in web.execute(
                """
                SELECT worker_discord_id, has_named_bonus
                FROM order_assignments
                WHERE order_id = ?
                  AND COALESCE(is_active, 1) = 1
                ORDER BY id ASC
                """,
                (order_id,),
            ).fetchall()
        ]

        payment_method = _normalize(order["payment_method"]).lower()
        stored_was_prepay = (
            status == "stored"
            and (
                stored_from_status in {
                    "pending_cs_dispatch",
                    "waiting_acceptance",
                    "accepted_pending_pay",
                }
                or (
                    not assignments
                    and payment_method in {
                        "",
                        "待付款",
                        "未紀錄",
                        "未记录",
                        "pending",
                        "unpaid",
                    }
                )
            )
        )

        worker_payouts = [
            dict(row)
            for row in web.execute(
                """
                SELECT
                    id,
                    worker_discord_id,
                    final_payout,
                    payout_status,
                    paid_at
                FROM worker_payouts
                WHERE order_id = ?
                ORDER BY id ASC
                """,
                (order_id,),
            ).fetchall()
        ]

        cs_payouts = [
            dict(row)
            for row in web.execute(
                """
                SELECT
                    id,
                    customer_service_discord_id,
                    payout_amount,
                    payout_status,
                    paid_at
                FROM customer_service_payouts
                WHERE order_id = ?
                ORDER BY id ASC
                """,
                (order_id,),
            ).fetchall()
        ]

        if status in TERMINAL_ORDER_STATUSES:
            non_void_workers = [
                row for row in worker_payouts
                if _normalize(row["payout_status"]).lower() != "void"
            ]
            non_void_cs = [
                row for row in cs_payouts
                if _normalize(row["payout_status"]).lower() != "void"
            ]
            if non_void_workers or non_void_cs:
                _issue(
                    issues,
                    category="payout",
                    code="cancelled_order_has_live_payout",
                    severity="critical",
                    reference=reference,
                    title="已取消訂單仍有有效分潤",
                    detail=(
                        f"worker={len(non_void_workers)}、客服={len(non_void_cs)} "
                        "筆分潤不是 void。"
                    ),
                    expected=0,
                    actual=len(non_void_workers) + len(non_void_cs),
                )
            continue

        if status not in OPEN_ACCOUNTING_ORDER_STATUSES:
            continue

        if stored_was_prepay:
            continue

        worker_ids = [
            _normalize(row["worker_discord_id"])
            for row in assignments
            if _normalize(row["worker_discord_id"])
        ]
        named_bonus_ids = [
            _normalize(row["worker_discord_id"])
            for row in assignments
            if row["has_named_bonus"] and _normalize(row["worker_discord_id"])
        ]
        payout_base = _as_int(
            order["payout_base_amount"]
            or order["amount"]
            or 0
        )

        expected = calculate_order_payout(
            total_amount=payout_base,
            worker_discord_ids=worker_ids,
            named_bonus_worker_ids=named_bonus_ids,
        )

        expected_by_worker = {
            str(row.worker_discord_id): float(row.final_payout)
            for row in expected.worker_payouts
        }

        for worker_id, manual_amount in overrides_by_order.get(order_id, {}).items():
            if worker_id in expected_by_worker:
                expected_by_worker[worker_id] = float(manual_amount)

        actual_by_worker: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for payout in worker_payouts:
            actual_by_worker[_normalize(payout["worker_discord_id"])].append(payout)

        for worker_id, expected_amount in expected_by_worker.items():
            actual_rows = actual_by_worker.get(worker_id, [])
            if not actual_rows:
                _issue(
                    issues,
                    category="payout",
                    code="worker_payout_missing",
                    severity="critical",
                    reference=reference,
                    title="接單人員缺少分潤資料",
                    detail=f"worker {worker_id} 有有效 assignment，但沒有 worker_payout。",
                    expected=expected_amount,
                    actual=None,
                )
                continue

            if len(actual_rows) > 1:
                _issue(
                    issues,
                    category="payout",
                    code="worker_payout_duplicate",
                    severity="critical",
                    reference=reference,
                    title="同一接單人員有重複分潤資料",
                    detail=f"worker {worker_id} 在同一訂單共有 {len(actual_rows)} 筆 worker_payout。",
                    expected=1,
                    actual=len(actual_rows),
                )

            actual_amount = _as_float(actual_rows[0]["final_payout"])
            if not _money_equal(expected_amount, actual_amount):
                _issue(
                    issues,
                    category="payout",
                    code="worker_payout_amount_mismatch",
                    severity="critical",
                    reference=reference,
                    title="接單人員分潤金額不一致",
                    detail=f"worker {worker_id} 的分潤與目前 assignment / 規則重算結果不同。",
                    expected=expected_amount,
                    actual=actual_amount,
                )

        for worker_id, actual_rows in actual_by_worker.items():
            if worker_id not in expected_by_worker:
                _issue(
                    issues,
                    category="payout",
                    code="worker_payout_without_assignment",
                    severity="critical",
                    reference=reference,
                    title="分潤存在但已無有效 assignment",
                    detail=f"worker {worker_id} 有 worker_payout，但不在目前有效接單名單。",
                    expected=None,
                    actual=sum(_as_float(row["final_payout"]) for row in actual_rows),
                )

        if len(cs_payouts) != 1:
            _issue(
                issues,
                category="payout",
                code="customer_service_payout_count",
                severity="critical",
                reference=reference,
                title="客服分潤筆數異常",
                detail="有效訂單理論上應有且只有一筆 customer_service_payout。",
                expected=1,
                actual=len(cs_payouts),
            )
        elif not _money_equal(expected.customer_service_payout, cs_payouts[0]["payout_amount"]):
            _issue(
                issues,
                category="payout",
                code="customer_service_payout_amount_mismatch",
                severity="critical",
                reference=reference,
                title="客服分潤金額不一致",
                detail="客服分潤與 payout_base_amount 重算結果不同。",
                expected=expected.customer_service_payout,
                actual=_as_float(cs_payouts[0]["payout_amount"]),
            )

        for payout in worker_payouts:
            status_text = _normalize(payout["payout_status"]).lower()
            if status_text == "paid" and payout["paid_at"] is None:
                _issue(
                    issues,
                    category="payout",
                    code="worker_paid_without_paid_at",
                    severity="warning",
                    reference=reference,
                    title="打手分潤已付款但缺少付款時間",
                    detail=f"worker payout #{payout['id']} status=paid，但 paid_at 為空。",
                )

        for payout in cs_payouts:
            status_text = _normalize(payout["payout_status"]).lower()
            if status_text == "paid" and payout["paid_at"] is None:
                _issue(
                    issues,
                    category="payout",
                    code="cs_paid_without_paid_at",
                    severity="warning",
                    reference=reference,
                    title="客服分潤已付款但缺少付款時間",
                    detail=f"customer service payout #{payout['id']} status=paid，但 paid_at 為空。",
                )


def build_accounting_reconciliation_snapshot(
    root: Path | None = None,
    *,
    detail_limit: int = 200,
) -> dict[str, Any]:
    root = Path(root or Path(__file__).resolve().parents[3])
    bot_path = root / "bot.db"
    web_path = root / "web_dashboard.db"

    issues: list[dict[str, Any]] = []
    availability = {
        "bot_db": bot_path.exists(),
        "web_db": web_path.exists(),
    }

    if not bot_path.exists():
        _issue(
            issues,
            category="system",
            code="bot_db_missing",
            severity="critical",
            reference="bot.db",
            title="Bot 資料庫不存在",
            detail="無法執行錢包、儲值與雞腿錢包對帳。",
        )

    if not web_path.exists():
        _issue(
            issues,
            category="system",
            code="web_db_missing",
            severity="critical",
            reference="web_dashboard.db",
            title="Web 資料庫不存在",
            detail="無法執行訂單、雞腿與分潤對帳。",
        )

    bot: sqlite3.Connection | None = None
    web: sqlite3.Connection | None = None

    try:
        if bot_path.exists():
            bot = _connect_readonly(bot_path)
        if web_path.exists():
            web = _connect_readonly(web_path)

        tx_by_id: dict[int, dict[str, Any]] = {}
        tx_by_reference: dict[tuple[str, str, str], list[dict[str, Any]]] = {}

        if bot is not None:
            tx_by_id, tx_by_reference = _load_wallet_state(bot, issues)
            _check_topups(bot, tx_by_id, issues)

        if web is not None:
            _check_wallet_paid_orders(web, tx_by_reference, issues)
            referenced_tip_tx_ids = _check_worker_tips(web, tx_by_id, issues)
            _check_payouts(web, issues)
        else:
            referenced_tip_tx_ids = set()

        if (
            bot is not None
            and web is not None
            and _table_exists(web, "worker_tips")
        ):
            _check_orphan_tip_wallet_transactions(
                tx_by_id,
                referenced_tip_tx_ids,
                issues,
            )
    except sqlite3.Error as exc:
        _issue(
            issues,
            category="system",
            code="sqlite_reconciliation_error",
            severity="critical",
            reference="accounting",
            title="帳務對帳查詢失敗",
            detail=f"{type(exc).__name__}: {str(exc)[:240]}",
        )
    finally:
        if bot is not None:
            bot.close()
        if web is not None:
            web.close()

    category_counts: dict[str, int] = defaultdict(int)
    severity_counts: dict[str, int] = defaultdict(int)
    for item in issues:
        category_counts[str(item["category"])] += 1
        severity_counts[str(item["severity"])] += 1

    critical_count = int(severity_counts.get("critical", 0))
    warning_count = int(severity_counts.get("warning", 0))

    if critical_count:
        status = "critical"
        status_text = "需要處理"
    elif warning_count:
        status = "warning"
        status_text = "有注意事項"
    else:
        status = "ok"
        status_text = "帳務一致"

    return {
        "status": status,
        "status_text": status_text,
        "issue_count": len(issues),
        "critical_count": critical_count,
        "warning_count": warning_count,
        "category_counts": dict(category_counts),
        "availability": availability,
        "issues": issues[: max(0, int(detail_limit))],
        "truncated": len(issues) > max(0, int(detail_limit)),
        "checked_paths": {
            "bot_db": str(bot_path),
            "web_db": str(web_path),
        },
    }
