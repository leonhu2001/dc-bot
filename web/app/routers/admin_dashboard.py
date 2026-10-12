from pathlib import Path
import json
import sqlite3
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text

from shared.db import SessionLocal
from shared.models import CustomerServicePayout, PayoutStatus, SyncEventType
from shared.order_acceptance import (
    PREPAY_ACCEPTANCE_STATUSES,
    claim_acceptance_order,
    get_acceptance_state,
    unclaim_acceptance_order,
)
from shared.order_state import (
    CANCELLED,
    CANCELLATION_REASON_LABELS,
    normalize_cancellation_reason_code,
    normalize_order_status,
    record_order_cancellation_in_connection,
    transition_order_state_in_connection,
)
from web.app.services.admin_service import (
    add_worker_to_order,
    remove_worker_from_order,
    set_customer_service_for_order,
    set_customer_service_payout_status,
    set_manual_worker_payout,
    set_worker_payout_status,
    toggle_named_bonus_for_assignment,
)
from web.app.services.order_service import (
    create_demo_orders_if_empty,
    create_sync_event,
    list_admin_orders,
)
from web.app.services.order_financial_edit import (
    preserve_order_financial_gaps,
)
from web.app.services.staff_service import (
    get_staff_display_name,
    get_staff_member_by_id,
    list_customer_service_members,
    list_worker_members,
    sync_staff_members_from_discord,
)
from core.time_utils import (
    format_taipei_datetime_from_utc,
    get_taipei_date_from_utc,
    get_taipei_now,
)

from web.app.routers.admin_common import (
    dedupe_admin_worker_members,
    get_current_user,
    list_admin_worker_dropdown_members,
    redirect_to_admin,
    require_admin_user,
)

router = APIRouter(tags=["admin"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

@router.get("/admin")
async def admin_dashboard(
    request: Request,
    message: str | None = None,
    error: str | None = None,
):
    # MAWAN PHASE 4A-1 NEW ADMIN DASHBOARD

    import json as _json

    from datetime import (
        datetime as _datetime,
    )

    from urllib.parse import (
        urlencode as _urlencode,
    )

    try:
        from zoneinfo import (
            ZoneInfo as _ZoneInfo,
        )
    except Exception:
        _ZoneInfo = None


    user = get_current_user(
        request
    )


    if not user:

        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title":
                    "請先登入",

                "message":
                    "請先使用 Discord 登入。",

                "user":
                    None,
            },
            status_code=401,
        )


    if not user.get(
        "is_admin"
    ):

        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title":
                    "沒有權限",

                "message":
                    "你沒有客服後台權限。",

                "user":
                    user,
            },
            status_code=403,
        )


    def _safe_int(
        value,
        default=0,
    ):

        try:
            return int(
                value
            )

        except (
            TypeError,
            ValueError,
        ):
            return default


    def _safe_json(
        value,
        default=None,
    ):

        if default is None:
            default = {}

        if isinstance(
            value,
            (
                dict,
                list,
            ),
        ):
            return value

        if not value:
            return default

        try:
            return _json.loads(
                str(value)
            )

        except Exception:
            return default


    def _table_exists(
        db,
        table_name: str,
    ) -> bool:

        row = db.execute(
            text(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = :name
                LIMIT 1
                """
            ),
            {
                "name":
                    table_name,
            },
        ).fetchone()

        return (
            row is not None
        )


    def _display_time(
        value,
    ) -> str:

        converted = format_taipei_datetime_from_utc(
            str(value or "").strip()
        )

        if converted:
            return converted

        raw = str(
            value
            or ""
        ).strip()

        if not raw:
            return "—"

        return (
            raw
            .replace(
                "T",
                " ",
            )
            .replace(
                "Z",
                "",
            )
        )[:16]


    status_labels = {
        "pending_cs_dispatch":
            "待客服確認",

        "waiting_acceptance":
            "等待接單",

        "accepted_pending_pay":
            "等待付款",

        "active":
            "進行中",

        "created":
            "已建立",

        "paid":
            "已付款",

        "completed":
            "已完成",

        "closed":
            "已結單",

        "done":
            "已完成",

        "cancelled":
            "已取消",

        "canceled":
            "已取消",
    }


    status_classes = {
        "pending_cs_dispatch":
            "pending",

        "waiting_acceptance":
            "waiting",

        "accepted_pending_pay":
            "payment",

        "active":
            "active",

        "paid":
            "active",

        "completed":
            "done",

        "closed":
            "done",

        "done":
            "done",

        "cancelled":
            "cancelled",

        "canceled":
            "cancelled",
    }


    db = SessionLocal()


    try:

        raw_orders = [
            dict(row)
            for row
            in db.execute(
                text(
                    """
                    SELECT *
                    FROM web_orders
                    ORDER BY id DESC
                    """
                )
            )
            .mappings()
            .all()
        ]


        acceptance_by_order = {}


        if _table_exists(
            db,
            "order_acceptance_meta",
        ):

            for row in (
                db.execute(
                    text(
                        """
                        SELECT *
                        FROM order_acceptance_meta
                        """
                    )
                )
                .mappings()
                .all()
            ):

                data = dict(
                    row
                )

                order_id = _safe_int(
                    data.get(
                        "order_id"
                    ),
                    None,
                )

                if order_id is not None:
                    acceptance_by_order[
                        order_id
                    ] = data


        submission_by_order = {}


        if _table_exists(
            db,
            "web_order_submission_meta",
        ):

            for row in (
                db.execute(
                    text(
                        """
                        SELECT *
                        FROM web_order_submission_meta
                        """
                    )
                )
                .mappings()
                .all()
            ):

                data = dict(
                    row
                )

                order_id = _safe_int(
                    data.get(
                        "order_id"
                    ),
                    None,
                )

                if order_id is not None:
                    submission_by_order[
                        order_id
                    ] = data


        staff_by_id = {}


        if _table_exists(
            db,
            "web_staff_members",
        ):

            for row in (
                db.execute(
                    text(
                        """
                        SELECT
                            discord_id,
                            username,
                            display_name,
                            global_name
                        FROM web_staff_members
                        """
                    )
                )
                .mappings()
                .all()
            ):

                data = dict(
                    row
                )

                discord_id = str(
                    data.get(
                        "discord_id"
                    )
                    or ""
                ).strip()

                if not discord_id:
                    continue

                staff_by_id[
                    discord_id
                ] = (
                    data.get(
                        "display_name"
                    )
                    or data.get(
                        "global_name"
                    )
                    or data.get(
                        "username"
                    )
                    or discord_id
                )


    finally:

        db.close()


    orders = []


    for raw in raw_orders:

        order_id = _safe_int(
            raw.get(
                "id"
            ),
            0,
        )


        status = str(
            raw.get(
                "status"
            )
            or "unknown"
        ).strip().lower()


        acceptance = (
            acceptance_by_order.get(
                order_id,
                {}
            )
        )


        submission = (
            submission_by_order.get(
                order_id,
                {}
            )
        )


        price_snapshot = _safe_json(
            raw.get(
                "price_snapshot_json"
            ),
            {},
        )


        submission_payload = _safe_json(
            submission.get(
                "submission_payload_json"
            ),
            {},
        )


        specified_ids = []


        raw_specified = acceptance.get(
            "specified_staff_ids_json"
        )


        parsed_specified = _safe_json(
            raw_specified,
            [],
        )


        if isinstance(
            parsed_specified,
            list,
        ):

            specified_ids = [
                str(value).strip()
                for value
                in parsed_specified
                if str(
                    value
                ).strip()
            ]


        if not specified_ids:

            for candidate in (
                price_snapshot.get(
                    "specified_staff_ids"
                ),
                submission_payload.get(
                    "specified_staff_ids"
                ),
                submission_payload.get(
                    "selected_staff_ids"
                ),
            ):

                if not isinstance(
                    candidate,
                    list,
                ):
                    continue

                specified_ids = [
                    str(value).strip()
                    for value
                    in candidate
                    if str(
                        value
                    ).strip()
                ]

                if specified_ids:
                    break


        specified_staff = [
            {
                "id":
                    staff_id,

                "name":
                    staff_by_id.get(
                        staff_id,
                        staff_id,
                    ),
            }
            for staff_id
            in specified_ids
        ]


        customer_id = str(
            raw.get(
                "customer_discord_id"
            )
            or ""
        ).strip()


        customer_name = str(
            raw.get(
                "customer_display_name"
            )
            or raw.get(
                "customer_username"
            )
            or customer_id
            or "未紀錄"
        ).strip()


        category = str(
            raw.get(
                "category"
            )
            or "未分類"
        ).strip()


        item = str(
            raw.get(
                "item"
            )
            or "未紀錄"
        ).strip()


        amount = _safe_int(
            raw.get(
                "customer_pay_amount"
            ),
            None,
        )


        if amount is None:

            amount = _safe_int(
                raw.get(
                    "amount"
                ),
                0,
            )


        created_at = (
            raw.get(
                "created_at"
            )
            or raw.get(
                "created_time"
            )
            or ""
        )


        updated_at = (
            raw.get(
                "updated_at"
            )
            or ""
        )


        bot_order_no = str(
            raw.get(
                "bot_order_no"
            )
            or ""
        ).strip()


        display_order_no = (
            bot_order_no
            if bot_order_no
            else f"WEB-{order_id}"
        )


        extra_requirements = str(
            submission.get(
                "extra_requirements"
            )
            or submission_payload.get(
                "extra_requirements"
            )
            or ""
        ).strip()


        terms_version = str(
            submission.get(
                "terms_version"
            )
            or ""
        ).strip()


        customer_service = str(
            raw.get(
                "customer_service_display_name"
            )
            or raw.get(
                "customer_service_discord_id"
            )
            or ""
        ).strip()


        note = str(
            raw.get(
                "note"
            )
            or ""
        ).strip()


        orders.append(
            {
                "id":
                    order_id,

                "order_no":
                    display_order_no,

                "status":
                    status,

                "status_label":
                    status_labels.get(
                        status,
                        status or "未知",
                    ),

                "status_class":
                    status_classes.get(
                        status,
                        "default",
                    ),

                "customer_id":
                    customer_id,

                "customer_name":
                    customer_name,

                "category":
                    category,

                "item":
                    item,

                "quantity":
                    _safe_int(
                        raw.get(
                            "quantity"
                        ),
                        1,
                    ),

                "amount":
                    amount,

                "payment_method":
                    str(
                        raw.get(
                            "payment_method"
                        )
                        or "待付款"
                    ),

                "created_at":
                    str(
                        created_at
                        or ""
                    ),

                "created_display":
                    _display_time(
                        created_at
                    ),

                "updated_display":
                    _display_time(
                        updated_at
                    ),

                "ticket_channel_id":
                    str(
                        raw.get(
                            "ticket_channel_id"
                        )
                        or ""
                    ),

                "dispatch_channel_id":
                    str(
                        raw.get(
                            "dispatch_channel_id"
                        )
                        or ""
                    ),

                "dispatch_message_id":
                    str(
                        raw.get(
                            "dispatch_message_id"
                        )
                        or ""
                    ),

                "customer_service":
                    customer_service,

                "specified_staff":
                    specified_staff,

                "extra_requirements":
                    extra_requirements,

                "terms_version":
                    terms_version,

                "note":
                    note,

                "rule_key":
                    str(
                        raw.get(
                            "order_rule_key"
                        )
                        or ""
                    ),

                "search_text":
                    " ".join(
                        [
                            str(order_id),
                            display_order_no,
                            customer_id,
                            customer_name,
                            category,
                            item,
                            customer_service,
                            " ".join(
                                staff[
                                    "name"
                                ]
                                for staff
                                in specified_staff
                            ),
                        ]
                    ).lower(),
            }
        )


    all_orders = list(
        orders
    )


    # MAWAN 4A-2R6 dashboard meta
    _mw_meta_db = SessionLocal()


    try:

        admin_meta_by_order = (
            _mw4a2r6_meta_map(
                _mw_meta_db
            )
        )


    finally:

        _mw_meta_db.close()


    for _mw_order in all_orders:

        _mw_meta = (
            admin_meta_by_order.get(
                int(
                    _mw_order.get(
                        "id"
                    )
                    or 0
                ),
                {},
            )
        )


        _mw_order[
            "internal_note"
        ] = str(
            _mw_meta.get(
                "internal_note"
            )
            or ""
        )


        _mw_order[
            "needs_attention"
        ] = bool(
            int(
                _mw_meta.get(
                    "needs_attention"
                )
                or 0
            )
        )


        _mw_order[
            "attention_reason"
        ] = str(
            _mw_meta.get(
                "attention_reason"
            )
            or ""
        )


    pending_cs_orders = [
        _mw_order

        for _mw_order
        in all_orders

        if _mw_order.get(
            "status"
        )
        == "pending_cs_dispatch"
    ][:8]


    attention_orders = [
        _mw_order

        for _mw_order
        in all_orders

        if (
            _mw_order.get(
                "needs_attention"
            )

            and _mw_order.get(
                "status"
            )
            not in {
                "cancelled",
                "canceled",
                "completed",
                "closed",
                "done",
            }
        )
    ][:8]


    # ========================================================
    # Statistics
    # ========================================================

    active_statuses = {
        "pending_cs_dispatch",
        "waiting_acceptance",
        "accepted_pending_pay",
        "active",
        "created",
        "paid",
    }


    today_date = (
        get_taipei_now()
        .date()
        .isoformat()
    )


    stats = {
        "today":
            sum(
                1
                for order
                in all_orders
                if get_taipei_date_from_utc(
                    order[
                        "created_at"
                    ]
                )
                == today_date
            ),

        "active":
            sum(
                1
                for order
                in all_orders
                if order[
                    "status"
                ]
                in active_statuses
            ),

        "pending_cs":
            sum(
                1
                for order
                in all_orders
                if order[
                    "status"
                ]
                == "pending_cs_dispatch"
            ),

        "customers":
            len(
                {
                    order[
                        "customer_id"
                    ]
                    for order
                    in all_orders
                    if order[
                        "customer_id"
                    ]
                }
            ),

        "total":
            len(
                all_orders
            ),
    }


    # ========================================================
    # Filters
    # ========================================================

    query = str(
        request.query_params.get(
            "q"
        )
        or ""
    ).strip()


    selected_status = str(
        request.query_params.get(
            "status"
        )
        or "all"
    ).strip().lower()


    if query:

        query_lower = (
            query.lower()
        )

        orders = [
            order
            for order
            in orders
            if query_lower
            in order[
                "search_text"
            ]
        ]


    if (
        selected_status
        and selected_status
        != "all"
    ):

        orders = [
            order
            for order
            in orders
            if order[
                "status"
            ]
            == selected_status
        ]


    # ========================================================
    # Pagination
    # ========================================================

    page = max(
        1,
        _safe_int(
            request.query_params.get(
                "page"
            ),
            1,
        ),
    )


    page_size = 40


    filtered_count = len(
        orders
    )


    page_count = max(
        1,
        (
            filtered_count
            + page_size
            - 1
        )
        // page_size,
    )


    if page > page_count:
        page = page_count


    start = (
        page - 1
    ) * page_size


    visible_orders = orders[
        start:
        start + page_size
    ]


    def _page_url(
        target_page,
    ):

        params = {
            "page":
                target_page,
        }

        if query:
            params["q"] = query

        if (
            selected_status
            and selected_status
            != "all"
        ):
            params[
                "status"
            ] = selected_status

        return (
            "/admin?"
            + _urlencode(
                params
            )
        )


    status_values = {
        order[
            "status"
        ]
        for order
        in all_orders
        if order[
            "status"
        ]
    }


    canonical_statuses = [
        "pending_cs_dispatch",
        "waiting_acceptance",
        "accepted_pending_pay",
        "active",
        "completed",
        "closed",
        "cancelled",
    ]


    ordered_statuses = []


    for status in canonical_statuses:

        if status in status_values:

            ordered_statuses.append(
                status
            )


    for status in sorted(
        status_values
    ):

        if (
            status
            not in ordered_statuses
        ):

            ordered_statuses.append(
                status
            )


    status_options = [
        {
            "value":
                status,

            "label":
                status_labels.get(
                    status,
                    status,
                ),
        }
        for status
        in ordered_statuses
    ]


    return templates.TemplateResponse(
        request=request,
        name="admin.html",
        context={
            "title":
                "客服後台｜魔丸娛樂",

            "user":
                user,

            "orders":
                visible_orders,

            "pending_cs_orders":
                pending_cs_orders,

            "attention_orders":
                attention_orders,

            "admin_meta_by_order":
                admin_meta_by_order,

            "stats":
                stats,

            "q":
                query,

            "selected_status":
                selected_status,

            "status_options":
                status_options,

            "filtered_count":
                filtered_count,

            "page":
                page,

            "page_count":
                page_count,

            "prev_url":
                (
                    _page_url(
                        page - 1
                    )
                    if page > 1
                    else None
                ),

            "next_url":
                (
                    _page_url(
                        page + 1
                    )
                    if page < page_count
                    else None
                ),

            "message":
                message,

            "error":
                error,
        },
    )
