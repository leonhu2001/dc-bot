# -*- coding: utf-8 -*-

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from services.order_rules import (
    CATEGORY_LABELS,
    ORDER_RULES,
    ROLE_IDS,
)
from shared.models import (
    SyncEvent,
    SyncEventStatus,
    SyncEventType,
    WebOrder,
)
from shared.order_acceptance import (
    WAITING_ACCEPTANCE,
    ensure_acceptance_tables,
)
from web.app.services.checkout_preview import (
    build_checkout_preview,
)


PUBLIC_ORDER_CREATE_SCHEMA_VERSION = 1


# ============================================================
# JSON helpers
# ============================================================

def _json_safe(
    value: Any,
):
    if value is None:
        return None

    if isinstance(
        value,
        (
            str,
            int,
            float,
            bool,
        ),
    ):
        return value

    if isinstance(
        value,
        dict,
    ):
        return {
            str(key):
                _json_safe(
                    item
                )

            for key, item
            in value.items()
        }

    if isinstance(
        value,
        (
            list,
            tuple,
            set,
        ),
    ):
        return [
            _json_safe(
                item
            )

            for item
            in value
        ]

    if is_dataclass(
        value
    ):
        return _json_safe(
            asdict(
                value
            )
        )

    if isinstance(
        value,
        datetime,
    ):
        return value.isoformat()

    return str(
        value
    )


def _json_text(
    value: Any,
) -> str:
    return json.dumps(
        _json_safe(
            value
        ),
        ensure_ascii=False,
        sort_keys=True,
        separators=(
            ",",
            ":",
        ),
    )


def _to_int(
    value: Any,
    default: int = 0,
) -> int:
    try:
        if (
            value is None
            or value == ""
        ):
            return int(
                default
            )

        return int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):
        return int(
            default
        )


def _text(
    value: Any,
) -> str:
    return str(
        value
        or ""
    ).strip()


# ============================================================
# Checkout preview invocation
#
# Uses signature inspection so this service follows the
# current local checkout_preview implementation rather than
# duplicating its pricing/VIP/specify validation.
# ============================================================

def final_server_preview(
    *,
    customer_id: str,
    payload: dict,
) -> dict:

    signature = inspect.signature(
        build_checkout_preview
    )

    candidates = {
        "customer_id":
            str(
                customer_id
            ),

        "rule_key":
            _text(
                payload.get(
                    "rule_key"
                )
            ),

        "quantity":
            _to_int(
                payload.get(
                    "quantity"
                ),
                1,
            ),

        "player_count":
            _to_int(
                payload.get(
                    "player_count"
                ),
                1,
            ),

        "customer_adjustments":
            payload.get(
                "customer_adjustments"
            )
            or [],

        "specified_staff_ids":
            payload.get(
                "specified_staff_ids"
            )
            or [],

        "point_item_key":
            payload.get(
                "point_item_key"
            )
            or None,

        "use_wallet":
            bool(
                payload.get(
                    "use_wallet"
                )
            ),

        "payment_method":
            payload.get(
                "payment_method"
            )
            or "轉帳",
    }


    kwargs = {
        key:
            value

        for key, value
        in candidates.items()

        if key
        in signature.parameters
    }


    required = {
        "customer_id",
        "rule_key",
    }


    missing = (
        required
        - set(
            kwargs
        )
    )


    if missing:
        raise RuntimeError(
            "build_checkout_preview "
            "缺少正式建單需要的參數："
            + ", ".join(
                sorted(
                    missing
                )
            )
        )


    result = (
        build_checkout_preview(
            **kwargs
        )
    )


    if not isinstance(
        result,
        dict,
    ):
        raise RuntimeError(
            "checkout preview "
            "沒有回傳 dict。"
        )


    return result


# ============================================================
# Idempotency
# ============================================================

def ensure_public_order_create_tables(
    db: Session,
) -> None:

    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS
            web_order_create_requests (
                request_key TEXT PRIMARY KEY,
                customer_discord_id TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                order_id INTEGER,
                status TEXT NOT NULL
                    DEFAULT 'processing',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
    )


    db.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS
            idx_web_order_create_customer
            ON web_order_create_requests(
                customer_discord_id,
                created_at
            )
            """
        )
    )


def _payload_hash(
    *,
    customer_id: str,
    payload: dict,
) -> str:

    canonical = {
        "customer_id":
            str(
                customer_id
            ),

        "payload":
            _json_safe(
                payload
            ),
    }


    encoded = (
        _json_text(
            canonical
        )
        .encode(
            "utf-8"
        )
    )


    return hashlib.sha256(
        encoded
    ).hexdigest()


def _reserve_request_key(
    db: Session,
    *,
    request_key: str,
    customer_id: str,
    payload_hash: str,
) -> int | None:

    now = (
        datetime.utcnow()
        .isoformat(
            timespec="seconds"
        )
    )


    db.execute(
        text(
            """
            INSERT OR IGNORE INTO
            web_order_create_requests (
                request_key,
                customer_discord_id,
                payload_hash,
                order_id,
                status,
                created_at,
                updated_at
            )
            VALUES (
                :request_key,
                :customer_id,
                :payload_hash,
                NULL,
                'processing',
                :created_at,
                :updated_at
            )
            """
        ),
        {
            "request_key":
                str(
                    request_key
                ),

            "customer_id":
                str(
                    customer_id
                ),

            "payload_hash":
                str(
                    payload_hash
                ),

            "created_at":
                now,

            "updated_at":
                now,
        },
    )


    inserted = int(
        db.execute(
            text(
                "SELECT changes()"
            )
        ).scalar_one()
        or 0
    )


    row = db.execute(
        text(
            """
            SELECT
                customer_discord_id,
                payload_hash,
                order_id,
                status
            FROM web_order_create_requests
            WHERE request_key = :request_key
            LIMIT 1
            """
        ),
        {
            "request_key":
                str(
                    request_key
                ),
        },
    ).mappings().first()


    if row is None:
        raise RuntimeError(
            "建立防重複 request 失敗。"
        )


    if (
        str(
            row[
                "customer_discord_id"
            ]
        )
        != str(
            customer_id
        )
    ):
        raise ValueError(
            "這個 request key "
            "已由其他帳號使用。"
        )


    if (
        str(
            row[
                "payload_hash"
            ]
        )
        != str(
            payload_hash
        )
    ):
        raise ValueError(
            "同一個 request key "
            "不能用於不同訂單內容。"
        )


    if inserted == 1:
        return None


    existing_order_id = row[
        "order_id"
    ]


    if existing_order_id:
        return int(
            existing_order_id
        )


    raise ValueError(
        "這筆訂單目前正在建立，"
        "請勿重複送出。"
    )


# ============================================================
# Rule snapshots
# ============================================================

def _rule_version() -> int:
    try:
        import services.order_rules as module

        for name in (
            "ORDER_RULE_VERSION",
            "RULE_VERSION",
            "PRICE_RULE_VERSION",
        ):
            value = getattr(
                module,
                name,
                None,
            )

            if value is not None:
                return int(
                    value
                )

    except Exception:
        pass

    return 1


def _rule_snapshot(
    rule,
) -> dict:

    if is_dataclass(
        rule
    ):
        snapshot = asdict(
            rule
        )

    else:
        snapshot = dict(
            vars(
                rule
            )
        )


    snapshot[
        "_snapshot_schema_version"
    ] = (
        PUBLIC_ORDER_CREATE_SCHEMA_VERSION
    )


    snapshot[
        "_captured_at"
    ] = (
        datetime.utcnow()
        .isoformat(
            timespec="seconds"
        )
    )


    return _json_safe(
        snapshot
    )


# ============================================================
# Preview extraction
# ============================================================

def _extract_finance(
    preview: dict,
) -> dict:

    finance = preview.get(
        "finance"
    )


    if not isinstance(
        finance,
        dict,
    ):
        finance = {}


    return finance


def _extract_quote(
    preview: dict,
) -> dict:

    quote = preview.get(
        "quote"
    )


    if not isinstance(
        quote,
        dict,
    ):
        quote = {}


    return quote


def _extract_selected_staff(
    preview: dict,
) -> list[dict]:

    selected = preview.get(
        "selected_staff"
    )


    if not isinstance(
        selected,
        list,
    ):
        return []


    return [
        item

        for item
        in selected

        if isinstance(
            item,
            dict,
        )
    ]


def _staff_id(
    item: dict,
) -> str:

    for key in (
        "staff_id",
        "staff_discord_id",
        "discord_id",
        "worker_discord_id",
    ):
        value = _text(
            item.get(
                key
            )
        )

        if value:
            return value


    return ""


def _staff_role_key(
    item: dict,
) -> str:

    for key in (
        "role_key",
        "staff_role_key",
        "role",
    ):
        value = _text(
            item.get(
                key
            )
        )

        if value:
            return value


    return ""


# ============================================================
# Amount mapping
# ============================================================

def _first_int(
    source: dict,
    names,
    *,
    default=0,
):

    for name in names:

        if (
            name in source
            and source[
                name
            ]
            is not None
        ):

            return _to_int(
                source[
                    name
                ],
                default,
            )


    return int(
        default
    )


def _amounts_from_preview(
    preview: dict,
) -> dict:

    quote = (
        _extract_quote(
            preview
        )
    )


    finance = (
        _extract_finance(
            preview
        )
    )


    service_amount = (
        _first_int(
            finance,
            (
                "service_amount",
                "service_total",
            ),
            default=
                _first_int(
                    quote,
                    (
                        "customer_pay_amount",
                        "total_amount",
                        "base_amount",
                    ),
                    default=0,
                ),
        )
    )


    specify_fee = (
        _first_int(
            finance,
            (
                "specify_fee",
                "specified_fee",
            ),
            default=
                _first_int(
                    quote,
                    (
                        "specify_fee",
                    ),
                    default=0,
                ),
        )
    )


    original_amount = (
        _first_int(
            finance,
            (
                "original_amount",
                "gross_amount",
                "before_discount_amount",
            ),
            default=(
                service_amount
                + specify_fee
            ),
        )
    )


    customer_pay_amount = (
        _first_int(
            finance,
            (
                "remaining_pay_amount",
                "customer_pay_amount",
                "final_pay_amount",
                "pay_amount",
            ),
            default=original_amount,
        )
    )


    payout_base_amount = (
        _first_int(
            finance,
            (
                "payout_base_amount",
                "worker_payout_base_amount",
            ),
            default=original_amount,
        )
    )


    manual_discount_amount = (
        _first_int(
            finance,
            (
                "manual_discount_amount",
            ),
            default=0,
        )
    )


    cash_coupon_amount = (
        _first_int(
            finance,
            (
                "cash_coupon_amount",
                "point_cash_discount",
            ),
            default=0,
        )
    )


    store_absorbed_amount = (
        _first_int(
            finance,
            (
                "store_absorbed_amount",
            ),
            default=0,
        )
    )


    return {
        "service_amount":
            service_amount,

        "specify_fee":
            specify_fee,

        "original_amount":
            original_amount,

        "payout_base_amount":
            payout_base_amount,

        "customer_pay_amount":
            max(
                0,
                customer_pay_amount,
            ),

        "manual_discount_amount":
            max(
                0,
                manual_discount_amount,
            ),

        "cash_coupon_amount":
            max(
                0,
                cash_coupon_amount,
            ),

        "store_absorbed_amount":
            max(
                0,
                store_absorbed_amount,
            ),
    }


# ============================================================
# Acceptance metadata
# ============================================================

def _ensure_acceptance_schema() -> None:
    ensure_acceptance_tables()


def _write_acceptance_meta(
    db: Session,
    *,
    order_id: int,
    rule,
    rule_version: int,
    rule_snapshot_json: str,
    price_snapshot_json: str,
    specified_staff_ids: list[str],
) -> None:

    required_staff_count = int(
        getattr(
            rule,
            "required_staff_count",
            1,
        )
        if getattr(
            rule,
            "required_staff_count",
            1,
        )
        != "player_count"
        else 1
    )


    # Prefer final quote value for player_count based rules.
    try:
        price_data = json.loads(
            price_snapshot_json
        )

        final_required = (
            price_data
            .get(
                "quote",
                {}
            )
            .get(
                "required_staff_count"
            )
        )

        if final_required is not None:
            required_staff_count = int(
                final_required
            )

    except Exception:
        pass


    min_protector_count = int(
        getattr(
            rule,
            "min_protector_count",
            0,
        )
        or 0
    )


    allowed_role_ids = [
        str(
            ROLE_IDS[
                role_key
            ]
        )

        for role_key
        in getattr(
            rule,
            "allowed_roles",
            ()
        )

        if role_key
        in ROLE_IDS
    ]


    now = (
        datetime.utcnow()
        .isoformat(
            timespec="seconds"
        )
    )


    db.execute(
        text(
            """
            INSERT INTO order_acceptance_meta (
                order_id,
                order_rule_key,
                required_staff_count,
                min_protector_count,
                allowed_role_ids_json,
                specified_staff_ids_json,
                point_benefits_allowed,
                rule_version,
                rule_snapshot_json,
                price_snapshot_json,
                status,
                created_at,
                updated_at
            )
            VALUES (
                :order_id,
                :order_rule_key,
                :required_staff_count,
                :min_protector_count,
                :allowed_role_ids_json,
                :specified_staff_ids_json,
                :point_benefits_allowed,
                :rule_version,
                :rule_snapshot_json,
                :price_snapshot_json,
                :status,
                :created_at,
                :updated_at
            )
            ON CONFLICT(order_id)
            DO UPDATE SET
                order_rule_key =
                    excluded.order_rule_key,

                required_staff_count =
                    excluded.required_staff_count,

                min_protector_count =
                    excluded.min_protector_count,

                allowed_role_ids_json =
                    excluded.allowed_role_ids_json,

                specified_staff_ids_json =
                    excluded.specified_staff_ids_json,

                point_benefits_allowed =
                    excluded.point_benefits_allowed,

                rule_version =
                    excluded.rule_version,

                rule_snapshot_json =
                    excluded.rule_snapshot_json,

                price_snapshot_json =
                    excluded.price_snapshot_json,

                status =
                    excluded.status,

                updated_at =
                    excluded.updated_at
            """
        ),
        {
            "order_id":
                int(
                    order_id
                ),

            "order_rule_key":
                str(
                    rule.key
                ),

            "required_staff_count":
                int(
                    required_staff_count
                ),

            "min_protector_count":
                int(
                    min_protector_count
                ),

            "allowed_role_ids_json":
                _json_text(
                    allowed_role_ids
                ),

            "specified_staff_ids_json":
                _json_text(
                    specified_staff_ids
                ),

            "point_benefits_allowed":
                (
                    1
                    if bool(
                        getattr(
                            rule,
                            "point_benefits_allowed",
                            True,
                        )
                    )
                    else 0
                ),

            "rule_version":
                int(
                    rule_version
                ),

            "rule_snapshot_json":
                str(
                    rule_snapshot_json
                ),

            "price_snapshot_json":
                str(
                    price_snapshot_json
                ),

            "status":
                WAITING_ACCEPTANCE,

            "created_at":
                now,

            "updated_at":
                now,
        },
    )


# ============================================================
# Persist final order
# ============================================================

def persist_final_order(
    db: Session,
    *,
    customer_id: str,
    customer_display_name: str,
    payload: dict,
    preview: dict,
    request_key: str,
) -> WebOrder:

    customer_id = _text(
        customer_id
    )


    if not customer_id:
        raise ValueError(
            "缺少登入顧客 Discord ID。"
        )


    rule_key = _text(
        payload.get(
            "rule_key"
        )
    )


    rule = ORDER_RULES.get(
        rule_key
    )


    if rule is None:
        raise ValueError(
            "正式建單找不到商品規則。"
        )


    # ========================================================
    # IMPORTANT:
    # Point / wallet final deductions are NOT enabled in 3C-1.
    #
    # This keeps Phase 3C-1 impossible to misuse before
    # atomic balance deduction is connected in Phase 3C-2.
    # ========================================================



    payload_hash = (
        _payload_hash(
            customer_id=
                customer_id,

            payload=
                payload,
        )
    )


    ensure_public_order_create_tables(
        db
    )


    existing_order_id = (
        _reserve_request_key(
            db,
            request_key=
                request_key,

            customer_id=
                customer_id,

            payload_hash=
                payload_hash,
        )
    )


    if existing_order_id:

        existing = db.get(
            WebOrder,
            int(
                existing_order_id
            ),
        )


        if existing is None:
            raise RuntimeError(
                "防重複 request 指向不存在的訂單。"
            )


        return existing


    amounts = (
        _amounts_from_preview(
            preview
        )
    )


    quote = (
        _extract_quote(
            preview
        )
    )


    selected_staff = (
        _extract_selected_staff(
            preview
        )
    )


    specified_staff_ids = []


    for item in selected_staff:

        staff_id = (
            _staff_id(
                item
            )
        )


        if (
            staff_id
            and staff_id
            not in specified_staff_ids
        ):

            specified_staff_ids.append(
                staff_id
            )


    rule_version = (
        _rule_version()
    )


    rule_snapshot = (
        _rule_snapshot(
            rule
        )
    )


    price_snapshot = {
        "schema_version":
            PUBLIC_ORDER_CREATE_SCHEMA_VERSION,

        "created_at":
            (
                datetime.utcnow()
                .isoformat(
                    timespec="seconds"
                )
            ),

        "input":
            _json_safe(
                payload
            ),

        "preview":
            _json_safe(
                preview
            ),
    }


    rule_snapshot_json = (
        _json_text(
            rule_snapshot
        )
    )


    price_snapshot_json = (
        _json_text(
            price_snapshot
        )
    )


    quantity = (
        _first_int(
            quote,
            (
                "quantity",
                "service_quantity",
            ),
            default=
                _to_int(
                    payload.get(
                        "quantity"
                    ),
                    1,
                ),
        )
    )


    payment_method = _text(
        payload.get(
            "payment_method"
        )
        or (
            preview
            .get(
                "payment",
                {}
            )
            .get(
                "method"
            )
            if isinstance(
                preview.get(
                    "payment"
                ),
                dict,
            )
            else ""
        )
        or "轉帳"
    )


    order = WebOrder(
        bot_order_no=None,

        ticket_channel_id=None,

        dispatch_channel_id=None,

        dispatch_message_id=None,

        customer_discord_id=
            customer_id,

        customer_display_name=
            _text(
                customer_display_name
            )
            or customer_id,

        category=
            CATEGORY_LABELS.get(
                str(
                    rule.category
                ),
                str(
                    rule.category
                ),
            ),

        item=
            str(
                rule.label
            ),

        quantity=
            max(
                1,
                int(
                    quantity
                ),
            ),

        # Legacy amount remains customer-facing payable amount.
        amount=
            int(
                amounts[
                    "customer_pay_amount"
                ]
            ),

        original_amount=
            int(
                amounts[
                    "original_amount"
                ]
            ),

        payout_base_amount=
            int(
                amounts[
                    "payout_base_amount"
                ]
            ),

        customer_pay_amount=
            int(
                amounts[
                    "customer_pay_amount"
                ]
            ),

        order_rule_key=
            str(
                rule.key
            ),

        rule_version=
            int(
                rule_version
            ),

        rule_snapshot_json=
            rule_snapshot_json,

        price_snapshot_json=
            price_snapshot_json,

        manual_discount_amount=
            int(
                amounts[
                    "manual_discount_amount"
                ]
            ),

        cash_coupon_amount=
            int(
                amounts[
                    "cash_coupon_amount"
                ]
            ),

        store_absorbed_amount=
            int(
                amounts[
                    "store_absorbed_amount"
                ]
            ),

        payment_method=
            payment_method,

        status=
            WAITING_ACCEPTANCE,

        customer_service_discord_id=
            None,

        customer_service_display_name=
            None,

        note=
            "網站正式建單｜付款前接單",
    )


    db.add(
        order
    )


    db.flush()


    if (
        order.id is None
    ):
        raise RuntimeError(
            "WebOrder flush 後沒有 order id。"
        )


    _write_acceptance_meta(
        db,
        order_id=
            int(
                order.id
            ),

        rule=
            rule,

        rule_version=
            int(
                rule_version
            ),

        rule_snapshot_json=
            rule_snapshot_json,

        price_snapshot_json=
            price_snapshot_json,

        specified_staff_ids=
            specified_staff_ids,
    )


    sync_payload = {
        "source":
            "website",

        "order_id":
            int(
                order.id
            ),

        "customer_discord_id":
            customer_id,

        "customer_display_name":
            _text(
                customer_display_name
            )
            or customer_id,

        "order_rule_key":
            str(
                rule.key
            ),

        "category":
            str(
                order.category
            ),

        "item":
            str(
                order.item
            ),

        "quantity":
            int(
                order.quantity
            ),

        "original_amount":
            int(
                order.original_amount
                or 0
            ),

        "customer_pay_amount":
            int(
                order.customer_pay_amount
                or 0
            ),

        "payout_base_amount":
            int(
                order.payout_base_amount
                or 0
            ),

        "payment_method":
            str(
                payment_method
            ),

        "specified_staff_ids":
            specified_staff_ids,

        "required_staff_count":
            _first_int(
                quote,
                (
                    "required_staff_count",
                ),
                default=1,
            ),

        "min_protector_count":
            int(
                getattr(
                    rule,
                    "min_protector_count",
                    0,
                )
                or 0
            ),

        "rule_version":
            int(
                rule_version
            ),

        "prepay_acceptance":
            True,
    }


    db.add(
        SyncEvent(
            event_type=
                SyncEventType
                .ORDER_CREATED
                .value,

            status=
                SyncEventStatus
                .PENDING
                .value,

            order_id=
                int(
                    order.id
                ),

            payload_json=
                _json_text(
                    sync_payload
                ),
        )
    )


    # === PHASE 3C-1R SYNC EVENT FLUSH ===
    #
    # SessionLocal uses autoflush=False.
    # Flush ORDER_CREATED inside the current transaction so
    # subsequent SQL reads can see the event immediately.
    db.flush()
    # === /PHASE 3C-1R SYNC EVENT FLUSH ===


    now = (
        datetime.utcnow()
        .isoformat(
            timespec="seconds"
        )
    )



    # === PHASE 3C-2R2 APPLY FINANCE ===
    finance_transaction = (
        apply_customer_finance(
            db,
            customer_id=
                customer_id,

            order_id=
                int(
                    order.id
                ),

            request_key=
                request_key,

            payload=
                payload,

            preview=
                preview,
        )
    )
    # === /PHASE 3C-2R2 APPLY FINANCE ===

    db.execute(
        text(
            """
            UPDATE web_order_create_requests
            SET
                order_id = :order_id,
                status = 'created',
                updated_at = :updated_at
            WHERE request_key = :request_key
            """
        ),
        {
            "order_id":
                int(
                    order.id
                ),

            "updated_at":
                now,

            "request_key":
                str(
                    request_key
                ),
        },
    )


    return order


# ============================================================
# Public service entry point
#
# Not wired to customer UI until Phase 3C-2.
# ============================================================

# === PHASE 3C-2R2 ATOMIC CUSTOMER FINANCE ===

from sqlalchemy import inspect as sa_inspect


MW_POINT_ID_CANDIDATES = (
    "customer_discord_id",
    "discord_id",
    "user_id",
    "member_id",
)


MW_POINT_VALUE_CANDIDATES = (
    "points",
    "point_balance",
    "points_balance",
)


def _mw_existing_tables(
    db: Session,
) -> list[str]:

    inspector = sa_inspect(
        db.get_bind()
    )

    return [
        str(name)

        for name
        in inspector.get_table_names()
    ]


def _mw_table_columns(
    db: Session,
    table_name: str,
) -> list[str]:

    inspector = sa_inspect(
        db.get_bind()
    )

    try:

        return [
            str(
                column[
                    "name"
                ]
            )

            for column
            in inspector.get_columns(
                table_name
            )
        ]

    except Exception:

        return []


def _mw_discover_point_storage(
    db: Session,
    customer_id: str,
) -> dict | None:

    customer_id = str(
        customer_id
    )


    preferred_tables = (
        "customers",
        "customer_profiles",
        "customer_data",
        "customer_stats",
        "web_customers",
        "members",
        "users",
    )


    tables = (
        _mw_existing_tables(
            db
        )
    )


    ordered = [
        name

        for name
        in preferred_tables

        if name in tables
    ]


    ordered.extend(
        name

        for name
        in tables

        if name not in ordered
    )


    candidates = []


    for table_name in ordered:

        columns = set(
            _mw_table_columns(
                db,
                table_name,
            )
        )


        id_column = next(
            (
                column

                for column
                in MW_POINT_ID_CANDIDATES

                if column in columns
            ),
            None,
        )


        point_column = next(
            (
                column

                for column
                in MW_POINT_VALUE_CANDIDATES

                if column in columns
            ),
            None,
        )


        if (
            not id_column
            or not point_column
        ):
            continue


        try:

            row = db.execute(
                text(
                    f"""
                    SELECT {point_column}
                    FROM {table_name}
                    WHERE CAST(
                        {id_column}
                        AS TEXT
                    ) = :customer_id
                    LIMIT 1
                    """
                ),
                {
                    "customer_id":
                        customer_id,
                },
            ).first()

        except Exception:

            continue


        if row is None:
            continue


        candidates.append(
            {
                "table":
                    table_name,

                "id_column":
                    id_column,

                "point_column":
                    point_column,

                "balance":
                    _to_int(
                        row[0],
                        0,
                    ),
            }
        )


    if not candidates:

        return None


    candidates.sort(
        key=lambda item: (
            0
            if "customer"
            in item[
                "table"
            ].lower()
            else 1,

            ordered.index(
                item[
                    "table"
                ]
            )
            if item[
                "table"
            ]
            in ordered
            else 999,
        )
    )


    return candidates[0]


def _mw_point_cost(
    preview: dict,
) -> int:

    point = preview.get(
        "point"
    )


    if not isinstance(
        point,
        dict,
    ):
        point = {}


    for key in (
        "cost",
        "point_cost",
        "points_cost",
        "required_points",
    ):

        if point.get(
            key
        ) is not None:

            return max(
                0,
                _to_int(
                    point.get(
                        key
                    ),
                    0,
                ),
            )


    finance = (
        _extract_finance(
            preview
        )
    )


    return max(
        0,
        _first_int(
            finance,
            (
                "point_cost",
                "points_cost",
                "required_points",
            ),
            default=0,
        ),
    )


def _mw_wallet_use_amount(
    preview: dict,
) -> int:

    finance = (
        _extract_finance(
            preview
        )
    )


    return max(
        0,
        _first_int(
            finance,
            (
                "wallet_use_amount",
                "wallet_amount",
                "wallet_discount_amount",
                "wallet_applied_amount",
            ),
            default=0,
        ),
    )


def ensure_checkout_finance_tables(
    db: Session,
) -> None:

    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS
            web_checkout_point_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_discord_id TEXT NOT NULL,
                order_id INTEGER,
                request_key TEXT NOT NULL,
                point_item_key TEXT,
                points_delta INTEGER NOT NULL,
                balance_before INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                source_table TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
    )


    db.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_checkout_point_request
            ON web_checkout_point_transactions(
                request_key
            )
            """
        )
    )


    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS
            web_checkout_wallet_transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_discord_id TEXT NOT NULL,
                order_id INTEGER,
                request_key TEXT NOT NULL,
                amount_delta INTEGER NOT NULL,
                balance_before INTEGER NOT NULL,
                balance_after INTEGER NOT NULL,
                created_at TEXT NOT NULL
            )
            """
        )
    )


    db.execute(
        text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS
            idx_checkout_wallet_request
            ON web_checkout_wallet_transactions(
                request_key
            )
            """
        )
    )


def _mw_debit_points(
    db: Session,
    *,
    customer_id: str,
    order_id: int,
    request_key: str,
    point_item_key: str | None,
    point_cost: int,
) -> dict:

    point_cost = max(
        0,
        int(
            point_cost
        ),
    )


    if point_cost <= 0:

        return {
            "used":
                0,

            "before":
                None,

            "after":
                None,

            "storage":
                None,
        }


    storage = (
        _mw_discover_point_storage(
            db,
            customer_id,
        )
    )


    if storage is None:

        raise RuntimeError(
            "找不到顧客點數資料來源，無法安全扣除點數。"
        )


    before = int(
        storage[
            "balance"
        ]
    )


    if before < point_cost:

        raise ValueError(
            f"點數不足，目前只有 {before} 點。"
        )


    table_name = storage[
        "table"
    ]

    id_column = storage[
        "id_column"
    ]

    point_column = storage[
        "point_column"
    ]


    result = db.execute(
        text(
            f"""
            UPDATE {table_name}
            SET
                {point_column}
                    = {point_column}
                    - :point_cost
            WHERE CAST(
                {id_column}
                AS TEXT
            ) = :customer_id
              AND {point_column}
                    >= :point_cost
            """
        ),
        {
            "point_cost":
                point_cost,

            "customer_id":
                str(
                    customer_id
                ),
        },
    )


    if int(
        result.rowcount
        or 0
    ) != 1:

        raise ValueError(
            "點數餘額已變更，請重新取得價格。"
        )


    after = (
        before
        - point_cost
    )


    db.execute(
        text(
            """
            INSERT INTO
            web_checkout_point_transactions (
                customer_discord_id,
                order_id,
                request_key,
                point_item_key,
                points_delta,
                balance_before,
                balance_after,
                source_table,
                created_at
            )
            VALUES (
                :customer_id,
                :order_id,
                :request_key,
                :point_item_key,
                :points_delta,
                :balance_before,
                :balance_after,
                :source_table,
                :created_at
            )
            """
        ),
        {
            "customer_id":
                str(
                    customer_id
                ),

            "order_id":
                int(
                    order_id
                ),

            "request_key":
                str(
                    request_key
                ),

            "point_item_key":
                (
                    str(
                        point_item_key
                    )
                    if point_item_key
                    else None
                ),

            "points_delta":
                -point_cost,

            "balance_before":
                before,

            "balance_after":
                after,

            "source_table":
                str(
                    table_name
                ),

            "created_at":
                datetime.utcnow()
                    .isoformat(
                        timespec="seconds"
                    ),
        },
    )


    return {
        "used":
            point_cost,

        "before":
            before,

        "after":
            after,

        "storage":
            str(
                table_name
            ),
    }


def _mw_debit_wallet(
    db: Session,
    *,
    customer_id: str,
    order_id: int,
    request_key: str,
    wallet_amount: int,
) -> dict:

    wallet_amount = max(
        0,
        int(
            wallet_amount
        ),
    )


    if wallet_amount <= 0:

        return {
            "used":
                0,

            "before":
                None,

            "after":
                None,
        }


    tables = set(
        _mw_existing_tables(
            db
        )
    )


    if (
        "customer_wallets"
        not in tables
    ):

        raise RuntimeError(
            "customer_wallets 不存在。"
        )


    columns = set(
        _mw_table_columns(
            db,
            "customer_wallets",
        )
    )


    if not {
        "customer_discord_id",
        "balance",
    }.issubset(
        columns
    ):

        raise RuntimeError(
            "customer_wallets schema 不完整。"
        )


    row = db.execute(
        text(
            """
            SELECT balance
            FROM customer_wallets
            WHERE CAST(
                customer_discord_id
                AS TEXT
            ) = :customer_id
            LIMIT 1
            """
        ),
        {
            "customer_id":
                str(
                    customer_id
                ),
        },
    ).first()


    before = (
        _to_int(
            row[0],
            0,
        )
        if row
        else 0
    )


    if before < wallet_amount:

        raise ValueError(
            f"錢包餘額不足，目前只有 {before}T。"
        )


    set_sql = (
        "balance = balance - :wallet_amount"
    )


    params = {
        "wallet_amount":
            wallet_amount,

        "customer_id":
            str(
                customer_id
            ),
    }


    if (
        "updated_at"
        in columns
    ):

        set_sql += (
            ", updated_at = :updated_at"
        )

        params[
            "updated_at"
        ] = (
            datetime.utcnow()
            .isoformat(
                timespec="seconds"
            )
        )


    result = db.execute(
        text(
            f"""
            UPDATE customer_wallets
            SET {set_sql}
            WHERE CAST(
                customer_discord_id
                AS TEXT
            ) = :customer_id
              AND balance
                    >= :wallet_amount
            """
        ),
        params,
    )


    if int(
        result.rowcount
        or 0
    ) != 1:

        raise ValueError(
            "錢包餘額已變更，請重新取得價格。"
        )


    after = (
        before
        - wallet_amount
    )


    db.execute(
        text(
            """
            INSERT INTO
            web_checkout_wallet_transactions (
                customer_discord_id,
                order_id,
                request_key,
                amount_delta,
                balance_before,
                balance_after,
                created_at
            )
            VALUES (
                :customer_id,
                :order_id,
                :request_key,
                :amount_delta,
                :balance_before,
                :balance_after,
                :created_at
            )
            """
        ),
        {
            "customer_id":
                str(
                    customer_id
                ),

            "order_id":
                int(
                    order_id
                ),

            "request_key":
                str(
                    request_key
                ),

            "amount_delta":
                -wallet_amount,

            "balance_before":
                before,

            "balance_after":
                after,

            "created_at":
                datetime.utcnow()
                .isoformat(
                    timespec="seconds"
                ),
        },
    )


    return {
        "used":
            wallet_amount,

        "before":
            before,

        "after":
            after,
    }


def apply_customer_finance(
    db: Session,
    *,
    customer_id: str,
    order_id: int,
    request_key: str,
    payload: dict,
    preview: dict,
) -> dict:

    ensure_checkout_finance_tables(
        db
    )


    point_item_key = (
        payload.get(
            "point_item_key"
        )
        or None
    )


    point_cost = (
        _mw_point_cost(
            preview
        )
        if point_item_key
        else 0
    )


    if (
        point_item_key
        and point_cost <= 0
    ):

        raise RuntimeError(
            "已選擇點數福利，但最終驗價沒有提供點數成本。"
        )


    use_wallet = bool(
        payload.get(
            "use_wallet"
        )
    )


    wallet_amount = (
        _mw_wallet_use_amount(
            preview
        )
        if use_wallet
        else 0
    )


    point_result = (
        _mw_debit_points(
            db,
            customer_id=
                customer_id,

            order_id=
                order_id,

            request_key=
                request_key,

            point_item_key=
                (
                    str(
                        point_item_key
                    )
                    if point_item_key
                    else None
                ),

            point_cost=
                point_cost,
        )
    )


    wallet_result = (
        _mw_debit_wallet(
            db,
            customer_id=
                customer_id,

            order_id=
                order_id,

            request_key=
                request_key,

            wallet_amount=
                wallet_amount,
        )
    )


    db.flush()


    return {
        "points":
            point_result,

        "wallet":
            wallet_result,
    }

# === /PHASE 3C-2R2 ATOMIC CUSTOMER FINANCE ===


def create_public_order(
    db: Session,
    *,
    customer_id: str,
    customer_display_name: str,
    payload: dict,
    request_key: str,
) -> WebOrder:

    customer_id = _text(
        customer_id
    )


    request_key = _text(
        request_key
    )


    if not customer_id:
        raise ValueError(
            "請先登入 Discord。"
        )


    if not request_key:
        raise ValueError(
            "缺少 request key。"
        )


    rule_key = _text(
        payload.get(
            "rule_key"
        )
    )


    if rule_key not in ORDER_RULES:
        raise ValueError(
            "找不到這個商品方案。"
        )


    # Always recalculate one last time.
    preview = (
        final_server_preview(
            customer_id=
                customer_id,

            payload=
                payload,
        )
    )


    _ensure_acceptance_schema()


    order = (
        persist_final_order(
            db,
            customer_id=
                customer_id,

            customer_display_name=
                customer_display_name,

            payload=
                payload,

            preview=
                preview,

            request_key=
                request_key,
        )
    )


    return order


# ============================================================
# Schema / dry-run validation
#
# This uses an actual WebOrder + acceptance meta + sync event,
# then CALLER ROLLS THE TRANSACTION BACK.
# ============================================================

def validate_persistence_dry_run(
    db: Session,
) -> dict:

    _ensure_acceptance_schema()


    ensure_public_order_create_tables(
        db
    )


    rule = (
        ORDER_RULES.get(
            "basic_entertain_single"
        )
    )


    if rule is None:

        # Find any non-manual formal rule.
        rule = next(
            (
                candidate

                for candidate
                in ORDER_RULES.values()

                if str(
                    candidate.pricing_type
                )
                != "manual"
            ),
            None,
        )


    if rule is None:

        raise RuntimeError(
            "找不到可用於 dry-run 的商品規則。"
        )


    request_key = (
        "phase3c1-dry-run-"
        + datetime.utcnow()
            .strftime(
                "%Y%m%d%H%M%S%f"
            )
    )


    payload = {
        "rule_key":
            str(
                rule.key
            ),

        "quantity":
            1,

        "player_count":
            1,

        "customer_adjustments":
            [],

        "specified_staff_ids":
            [],

        "point_item_key":
            None,

        "use_wallet":
            False,

        "payment_method":
            "轉帳",
    }


    preview = {
        "quote": {
            "quantity":
                1,

            "required_staff_count":
                (
                    1
                    if getattr(
                        rule,
                        "required_staff_count",
                        1,
                    )
                    == "player_count"
                    else int(
                        getattr(
                            rule,
                            "required_staff_count",
                            1,
                        )
                    )
                ),

            "customer_pay_amount":
                max(
                    1,
                    int(
                        getattr(
                            rule,
                            "price",
                            1,
                        )
                        or 1
                    ),
                ),
        },

        "finance": {
            "service_amount":
                max(
                    1,
                    int(
                        getattr(
                            rule,
                            "price",
                            1,
                        )
                        or 1
                    ),
                ),

            "specify_fee":
                0,

            "original_amount":
                max(
                    1,
                    int(
                        getattr(
                            rule,
                            "price",
                            1,
                        )
                        or 1
                    ),
                ),

            "payout_base_amount":
                max(
                    1,
                    int(
                        getattr(
                            rule,
                            "price",
                            1,
                        )
                        or 1
                    ),
                ),

            "remaining_pay_amount":
                max(
                    1,
                    int(
                        getattr(
                            rule,
                            "price",
                            1,
                        )
                        or 1
                    ),
                ),
        },

        "selected_staff":
            [],

        "payment": {
            "method":
                "轉帳",
        },
    }


    order = (
        persist_final_order(
            db,
            customer_id=
                "999999999999999999",

            customer_display_name=
                "PHASE3C1_DRY_RUN",

            payload=
                payload,

            preview=
                preview,

            request_key=
                request_key,
        )
    )


    order_id = int(
        order.id
    )


    meta = db.execute(
        text(
            """
            SELECT
                order_rule_key,
                status,
                rule_version,
                rule_snapshot_json,
                price_snapshot_json
            FROM order_acceptance_meta
            WHERE order_id = :order_id
            LIMIT 1
            """
        ),
        {
            "order_id":
                order_id,
        },
    ).mappings().first()


    if meta is None:

        raise RuntimeError(
            "dry-run acceptance metadata missing"
        )


    sync = db.execute(
        text(
            """
            SELECT
                event_type,
                status,
                payload_json
            FROM sync_events
            WHERE order_id = :order_id
            ORDER BY id DESC
            LIMIT 1
            """
        ),
        {
            "order_id":
                order_id,
        },
    ).mappings().first()


    if sync is None:

        raise RuntimeError(
            "dry-run sync event missing"
        )


    if (
        str(
            sync[
                "event_type"
            ]
        )
        != SyncEventType
            .ORDER_CREATED
            .value
    ):

        raise RuntimeError(
            "dry-run event type mismatch"
        )


    if (
        str(
            meta[
                "status"
            ]
        )
        != WAITING_ACCEPTANCE
    ):

        raise RuntimeError(
            "dry-run acceptance status mismatch"
        )


    return {
        "order_id":
            order_id,

        "rule_key":
            str(
                rule.key
            ),

        "order_status":
            str(
                order.status
            ),

        "meta_status":
            str(
                meta[
                    "status"
                ]
            ),

        "event_type":
            str(
                sync[
                    "event_type"
                ]
            ),

        "event_status":
            str(
                sync[
                    "status"
                ]
            ),

        "snapshots":
            bool(
                meta[
                    "rule_snapshot_json"
                ]
                and meta[
                    "price_snapshot_json"
                ]
            ),
    }
