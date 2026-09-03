from pathlib import Path
import sqlite3
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text

from shared.db import SessionLocal
from shared.models import CustomerServicePayout, PayoutStatus
from web.app.services.admin_service import (
    add_worker_to_order,
    remove_worker_from_order,
    set_customer_service_for_order,
    set_customer_service_payout_status,
    set_manual_worker_payout,
    set_worker_payout_status,
    toggle_named_bonus_for_assignment,
)
from web.app.services.order_service import create_demo_orders_if_empty, list_admin_orders
from web.app.services.staff_service import (
    get_staff_display_name,
    get_staff_member_by_id,
    list_customer_service_members,
    list_worker_members,
    sync_staff_members_from_discord,
)

router = APIRouter(tags=["admin"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def redirect_to_admin(**params) -> RedirectResponse:
    query = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }

    if query:
        return RedirectResponse(
            url=f"/admin?{urlencode(query)}",
            status_code=303,
        )

    return RedirectResponse(url="/admin", status_code=303)


def require_admin_user(request: Request) -> dict | None:
    user = get_current_user(request)

    if not user:
        return None

    if not user.get("is_admin"):
        return None

    return user



def dedupe_admin_worker_members(members):
    """Admin 首頁新增 / 更換護航 / 陪玩下拉：護航或陪玩都顯示，同一人只出現一次。"""
    result = {}
    for member in members or []:
        discord_id = str(getattr(member, "discord_id", "") or member.get("discord_id", "") if isinstance(member, dict) else getattr(member, "discord_id", "")).strip()
        if not discord_id:
            continue

        is_worker = bool(getattr(member, "is_worker", False) if not isinstance(member, dict) else member.get("is_worker"))
        is_companion = bool(getattr(member, "is_companion", False) if not isinstance(member, dict) else member.get("is_companion"))

        if not (is_worker or is_companion):
            continue

        result[discord_id] = member

    def member_name(member):
        if isinstance(member, dict):
            return str(member.get("display_name") or member.get("username") or member.get("discord_id") or "")
        return str(getattr(member, "display_name", "") or getattr(member, "username", "") or getattr(member, "discord_id", ""))

    return sorted(result.values(), key=member_name)


def list_admin_worker_dropdown_members() -> list[dict]:
    """Admin 首頁新增 / 更換護航 / 陪玩下拉。

    只要有護航或陪玩身分就顯示；同一人只出現一次。
    """
    db_path = Path(__file__).resolve().parents[3] / "web_dashboard.db"

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT
                discord_id,
                username,
                display_name,
                global_name,
                is_worker,
                is_companion,
                is_customer_service,
                is_active
            FROM web_staff_members
            WHERE COALESCE(is_active, 1) = 1
              AND (
                    COALESCE(is_worker, 0) = 1
                 OR COALESCE(is_companion, 0) = 1
              )
            ORDER BY
                COALESCE(display_name, ''),
                COALESCE(global_name, ''),
                COALESCE(username, ''),
                discord_id
            """
        ).fetchall()

        members = []
        seen = set()

        for row in rows:
            discord_id = str(row["discord_id"] or "").strip()
            if not discord_id or discord_id in seen:
                continue

            seen.add(discord_id)

            members.append({
                "discord_id": discord_id,
                "username": row["username"],
                "display_name": row["display_name"],
                "global_name": row["global_name"],
                "is_worker": bool(row["is_worker"]),
                "is_companion": bool(row["is_companion"]),
                "is_customer_service": bool(row["is_customer_service"]),
                "is_active": bool(row["is_active"]),
            })

        return members

    finally:
        conn.close()


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

        raw = str(
            value
            or ""
        ).strip()

        if not raw:
            return "—"

        raw = (
            raw
            .replace(
                "T",
                " ",
            )
            .replace(
                "Z",
                "",
            )
        )

        return raw[:16]


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


    today_date = ""


    try:

        if _ZoneInfo is not None:

            today_date = (
                _datetime.now(
                    _ZoneInfo(
                        "Asia/Taipei"
                    )
                )
                .date()
                .isoformat()
            )

        else:

            today_date = (
                _datetime.now()
                .date()
                .isoformat()
            )

    except Exception:

        today_date = (
            _datetime.now()
            .date()
            .isoformat()
        )


    stats = {
        "today":
            sum(
                1
                for order
                in all_orders
                if order[
                    "created_at"
                ][:10]
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




@router.post("/admin/orders/{order_id}/cancel")
async def admin_cancel_order(
    order_id: int,
    request: Request,
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse("/auth/login", status_code=303)

    db = SessionLocal()

    try:
        row = db.execute(
            text("SELECT id FROM web_orders WHERE id = :order_id"),
            {"order_id": order_id},
        ).fetchone()

        if row is None:
            return redirect_to_admin(error="找不到這筆訂單。")

        db.execute(
            text("UPDATE web_orders SET status = 'cancelled' WHERE id = :order_id"),
            {"order_id": order_id},
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        return redirect_to_admin(error=f"取消訂單失敗：{exc}")
    finally:
        db.close()

    return redirect_to_admin(message="訂單已取消，已從總控列表隱藏。")


@router.post("/admin/staff/sync")
async def admin_sync_staff(request: Request):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有客服後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        result = sync_staff_members_from_discord(db)
        db.commit()
    except Exception as e:
        db.rollback()
        return redirect_to_admin(error=f"同步成員失敗：{e}")
    finally:
        db.close()

    return redirect_to_admin(
        message=result.get("message") or f"成員同步完成：掃描 {result.get('total_seen', result.get('scanned', '?'))} 人，寫入 {result.get('synced_count', result.get('written', '?'))} 人。"
    )


@router.post("/admin/orders/{order_id}/customer-service")
async def admin_set_customer_service(
    request: Request,
    order_id: int,
    customer_service_discord_id: str = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有客服後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        staff_member = get_staff_member_by_id(db, discord_id=customer_service_discord_id)
        customer_service_display_name = (
            get_staff_display_name(staff_member)
            if staff_member is not None
            else customer_service_discord_id
        )

        set_customer_service_for_order(
            db,
            order_id=order_id,
            customer_service_discord_id=customer_service_discord_id,
            customer_service_display_name=customer_service_display_name,
            admin_user=user,
            reason=reason,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="已更新此單對接客服，客服 5% 分潤已重新計算。")


@router.post("/admin/assignments/{assignment_id}/named-bonus")
async def update_named_bonus(
    request: Request,
    assignment_id: int,
    enabled: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有客服後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        toggle_named_bonus_for_assignment(
            db,
            assignment_id=assignment_id,
            enabled=enabled == "on",
            admin_user=user,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="掛名加成已更新。")


@router.post("/admin/assignments/{assignment_id}/remove")
async def admin_remove_worker(
    request: Request,
    assignment_id: int,
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有客服後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        remove_worker_from_order(
            db,
            assignment_id=assignment_id,
            admin_user=user,
            reason=reason,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="已移除這位護航 / 陪玩，分潤已重新計算。")


@router.post("/admin/orders/{order_id}/add-worker")
async def admin_add_worker(
    request: Request,
    order_id: int,
    worker_discord_id: str = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有客服後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        staff_member = get_staff_member_by_id(db, discord_id=worker_discord_id)
        worker_display_name = (
            get_staff_display_name(staff_member)
            if staff_member is not None
            else worker_discord_id
        )

        add_worker_to_order(
            db,
            order_id=order_id,
            worker_discord_id=worker_discord_id,
            worker_display_name=worker_display_name,
            admin_user=user,
            reason=reason,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="已新增/更換護航 / 陪玩，分潤已重新計算。")


@router.post("/admin/orders/{order_id}/manual-payout")
async def admin_manual_payout(
    request: Request,
    order_id: int,
    worker_discord_id: str = Form(...),
    worker_display_name: str | None = Form(default=None),
    manual_final_payout: int = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有客服後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        set_manual_worker_payout(
            db,
            order_id=order_id,
            worker_discord_id=worker_discord_id,
            worker_display_name=worker_display_name,
            manual_final_payout=manual_final_payout,
            reason=reason,
            admin_user=user,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="已手動更新護航 / 陪玩分潤金額。")


@router.post("/admin/worker-payouts/{payout_id}/status")
async def admin_set_worker_payout_status(
    request: Request,
    payout_id: int,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有客服後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        set_worker_payout_status(
            db,
            payout_id=payout_id,
            status=status,
            admin_user=user,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="護航 / 陪玩分潤狀態已更新。")


@router.post("/admin/customer-service-payouts/{payout_id}/status")
async def admin_set_customer_service_payout_status(
    request: Request,
    payout_id: int,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_admin(error="你沒有客服後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        set_customer_service_payout_status(
            db,
            payout_id=payout_id,
            status=status,
            admin_user=user,
        )
    except ValueError as e:
        db.rollback()
        return redirect_to_admin(error=str(e))
    finally:
        db.close()

    return redirect_to_admin(message="魔丸♫魔丸♫客服分潤狀態已更新。")

# MAWAN PHASE 4A-2R6 ORDER WORKSPACE


def _mw4a2r6_table_exists(
    db,
    table_name: str,
) -> bool:

    row = db.execute(
        text(
            """
            SELECT 1

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


def _mw4a2r6_safe_int(
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


def _mw4a2r6_json(
    value,
    default=None,
):

    import json


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

        return json.loads(
            str(value)
        )

    except Exception:

        return default


def _mw4a2r6_time(
    value,
):

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


def _mw4a2r6_status_label(
    status,
):

    status = str(
        status
        or ""
    ).strip().lower()


    labels = {

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


    return labels.get(
        status,
        status or "未知",
    )


def _mw4a2r6_meta_map(
    db,
):

    if not _mw4a2r6_table_exists(
        db,
        "web_admin_order_meta",
    ):

        return {}


    rows = (
        db.execute(
            text(
                """
                SELECT *

                FROM web_admin_order_meta
                """
            )
        )
        .mappings()
        .all()
    )


    result = {}


    for row in rows:

        data = dict(
            row
        )


        order_id = (
            _mw4a2r6_safe_int(
                data.get(
                    "order_id"
                ),
                None,
            )
        )


        if order_id is not None:

            result[
                order_id
            ] = data


    return result


def _mw4a2r6_ensure_meta_table(
    db,
):

    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS
            web_admin_order_meta (

                order_id INTEGER
                    PRIMARY KEY,

                internal_note TEXT
                    NOT NULL
                    DEFAULT '',

                needs_attention INTEGER
                    NOT NULL
                    DEFAULT 0,

                attention_reason TEXT
                    NOT NULL
                    DEFAULT '',

                updated_by_discord_id TEXT,

                updated_by_display_name TEXT,

                updated_at TEXT
                    NOT NULL
                    DEFAULT CURRENT_TIMESTAMP

            )
            """
        )
    )


def _mw4a2r6_user_name(
    user,
):

    return str(

        user.get(
            "display_name"
        )

        or user.get(
            "global_name"
        )

        or user.get(
            "username"
        )

        or user.get(
            "name"
        )

        or user.get(
            "id"
        )

        or ""

    )


def _mw4a2r6_staff_map(
    db,
):

    if not _mw4a2r6_table_exists(
        db,
        "web_staff_members",
    ):

        return {}


    rows = (
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
    )


    result = {}


    for row in rows:

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


        result[
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


    return result


def _mw4a2r6_cs_members(
    db,
):

    members = list(
        list_customer_service_members(
            db
        )
    )


    result = []


    for member in members:

        if isinstance(
            member,
            dict,
        ):

            getter = member.get

        else:

            getter = lambda name, default=None: getattr(
                member,
                name,
                default,
            )


        discord_id = str(
            getter(
                "discord_id",
                "",
            )
            or ""
        ).strip()


        if not discord_id:

            continue


        result.append(
            {
                "discord_id":
                    discord_id,

                "name":
                    str(
                        getter(
                            "display_name",
                            None,
                        )

                        or getter(
                            "global_name",
                            None,
                        )

                        or getter(
                            "username",
                            None,
                        )

                        or discord_id
                    ),
            }
        )


    return result


def _mw4a2r6_load_order_bundle(
    db,
    order_id: int,
):

    raw_row = (
        db.execute(
            text(
                """
                SELECT *

                FROM web_orders

                WHERE id =
                    :order_id

                LIMIT 1
                """
            ),
            {
                "order_id":
                    int(
                        order_id
                    ),
            },
        )
        .mappings()
        .first()
    )


    if raw_row is None:

        return (
            None,
            [],
            {},
        )


    raw = dict(
        raw_row
    )


    acceptance = {}


    if _mw4a2r6_table_exists(
        db,
        "order_acceptance_meta",
    ):

        row = (
            db.execute(
                text(
                    """
                    SELECT *

                    FROM order_acceptance_meta

                    WHERE order_id =
                        :order_id

                    LIMIT 1
                    """
                ),
                {
                    "order_id":
                        int(
                            order_id
                        ),
                },
            )
            .mappings()
            .first()
        )


        if row is not None:

            acceptance = dict(
                row
            )


    submission = {}


    if _mw4a2r6_table_exists(
        db,
        "web_order_submission_meta",
    ):

        row = (
            db.execute(
                text(
                    """
                    SELECT *

                    FROM web_order_submission_meta

                    WHERE order_id =
                        :order_id

                    LIMIT 1
                    """
                ),
                {
                    "order_id":
                        int(
                            order_id
                        ),
                },
            )
            .mappings()
            .first()
        )


        if row is not None:

            submission = dict(
                row
            )


    staff_by_id = (
        _mw4a2r6_staff_map(
            db
        )
    )


    price_snapshot = (
        _mw4a2r6_json(
            raw.get(
                "price_snapshot_json"
            ),
            {},
        )
    )


    submission_payload = (
        _mw4a2r6_json(
            submission.get(
                "submission_payload_json"
            ),
            {},
        )
    )


    specified_ids = (
        _mw4a2r6_json(
            acceptance.get(
                "specified_staff_ids_json"
            ),
            [],
        )
    )


    if not isinstance(
        specified_ids,
        list,
    ):

        specified_ids = []


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

            if isinstance(
                candidate,
                list,
            ):

                specified_ids = candidate

                break


    specified_staff = []


    for value in specified_ids:

        discord_id = str(
            value
            or ""
        ).strip()


        if not discord_id:

            continue


        specified_staff.append(
            {
                "id":
                    discord_id,

                "name":
                    staff_by_id.get(
                        discord_id,
                        discord_id,
                    ),
            }
        )


    customer_id = str(
        raw.get(
            "customer_discord_id"
        )
        or ""
    ).strip()


    amount = (
        _mw4a2r6_safe_int(
            raw.get(
                "customer_pay_amount"
            ),
            None,
        )
    )


    if amount is None:

        amount = (
            _mw4a2r6_safe_int(
                raw.get(
                    "amount"
                ),
                0,
            )
        )


    status = str(
        raw.get(
            "status"
        )
        or "unknown"
    ).strip().lower()


    meta = (
        _mw4a2r6_meta_map(
            db
        )
        .get(
            int(
                order_id
            ),
            {},
        )
    )


    order = {

        "id":
            int(
                order_id
            ),

        "order_no":
            str(
                raw.get(
                    "bot_order_no"
                )
                or f"WEB-{order_id}"
            ),

        "status":
            status,

        "status_label":
            _mw4a2r6_status_label(
                status
            ),

        "customer_id":
            customer_id,

        "customer_name":
            str(
                raw.get(
                    "customer_display_name"
                )

                or raw.get(
                    "customer_username"
                )

                or customer_id

                or "未紀錄"
            ),

        "category":
            str(
                raw.get(
                    "category"
                )
                or "未分類"
            ),

        "item":
            str(
                raw.get(
                    "item"
                )
                or "未紀錄"
            ),

        "quantity":
            _mw4a2r6_safe_int(
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

        "created_display":
            _mw4a2r6_time(
                raw.get(
                    "created_at"
                )
                or raw.get(
                    "created_time"
                )
            ),

        "updated_display":
            _mw4a2r6_time(
                raw.get(
                    "updated_at"
                )
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

        "customer_service_id":
            str(
                raw.get(
                    "customer_service_discord_id"
                )
                or ""
            ),

        "customer_service":
            str(
                raw.get(
                    "customer_service_display_name"
                )

                or raw.get(
                    "customer_service_discord_id"
                )

                or ""
            ),

        "specified_staff":
            specified_staff,

        "extra_requirements":
            str(
                submission.get(
                    "extra_requirements"
                )

                or submission_payload.get(
                    "extra_requirements"
                )

                or ""
            ),

        "terms_version":
            str(
                submission.get(
                    "terms_version"
                )
                or ""
            ),

        "rule_key":
            str(
                raw.get(
                    "order_rule_key"
                )
                or ""
            ),

        "note":
            str(
                raw.get(
                    "note"
                )
                or ""
            ),

        "internal_note":
            str(
                meta.get(
                    "internal_note"
                )
                or ""
            ),

        "needs_attention":
            bool(
                _mw4a2r6_safe_int(
                    meta.get(
                        "needs_attention"
                    ),
                    0,
                )
            ),

        "attention_reason":
            str(
                meta.get(
                    "attention_reason"
                )
                or ""
            ),

        "meta_updated_by":
            str(
                meta.get(
                    "updated_by_display_name"
                )
                or ""
            ),

        "meta_updated_at":
            _mw4a2r6_time(
                meta.get(
                    "updated_at"
                )
            ),

    }


    history = []


    if customer_id:

        rows = (
            db.execute(
                text(
                    """
                    SELECT *

                    FROM web_orders

                    WHERE customer_discord_id =
                        :customer_id

                      AND id !=
                        :order_id

                    ORDER BY id DESC

                    LIMIT 8
                    """
                ),
                {
                    "customer_id":
                        customer_id,

                    "order_id":
                        int(
                            order_id
                        ),
                },
            )
            .mappings()
            .all()
        )


        for row in rows:

            data = dict(
                row
            )


            history_amount = (
                _mw4a2r6_safe_int(
                    data.get(
                        "customer_pay_amount"
                    ),
                    None,
                )
            )


            if history_amount is None:

                history_amount = (
                    _mw4a2r6_safe_int(
                        data.get(
                            "amount"
                        ),
                        0,
                    )
                )


            history_status = str(
                data.get(
                    "status"
                )
                or ""
            ).strip().lower()


            history.append(
                {
                    "id":
                        _mw4a2r6_safe_int(
                            data.get(
                                "id"
                            ),
                            0,
                        ),

                    "order_no":
                        str(
                            data.get(
                                "bot_order_no"
                            )

                            or (
                                "WEB-"
                                + str(
                                    data.get(
                                        "id"
                                    )
                                    or ""
                                )
                            )
                        ),

                    "item":
                        str(
                            data.get(
                                "item"
                            )
                            or "未紀錄"
                        ),

                    "status_label":
                        _mw4a2r6_status_label(
                            history_status
                        ),

                    "amount":
                        history_amount,
                }
            )


    return (
        order,
        history,
        meta,
    )


def _mw4a2r6_redirect(
    order_id,
    *,
    message=None,
    error=None,
):

    from urllib.parse import (
        urlencode,
    )


    params = {}


    if message:

        params[
            "message"
        ] = message


    if error:

        params[
            "error"
        ] = error


    base = (
        "/admin/order-workspace/"
        + str(
            int(
                order_id
            )
        )
    )


    if params:

        base += (
            "?"
            + urlencode(
                params
            )
        )


    return RedirectResponse(
        url=base,
        status_code=303,
    )


# BEGIN MAWAN_R8_ORDER_WORKSPACE

import re as _mw_r8_re


def _mw_r8_jsonable_row(row):
    if row is None:
        return None

    result = {}

    for key, value in dict(row).items():
        if value is not None and hasattr(value, "isoformat"):
            try:
                value = value.isoformat()
            except Exception:
                value = str(value)

        result[str(key)] = value

    return result


def _mw_r8_snapshot_payout_status(db, order_id: int) -> dict:
    snapshot = {
        "worker": {},
        "customer_service": {},
    }

    for row in db.execute(
        text(
            """
            SELECT
                worker_discord_id AS person_id,
                payout_status,
                paid_at
            FROM worker_payouts
            WHERE order_id = :order_id
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all():
        person_id = str(row.get("person_id") or "").strip()
        if person_id:
            snapshot["worker"][person_id] = {
                "payout_status": row.get("payout_status"),
                "paid_at": row.get("paid_at"),
            }

    for row in db.execute(
        text(
            """
            SELECT
                customer_service_discord_id AS person_id,
                payout_status,
                paid_at
            FROM customer_service_payouts
            WHERE order_id = :order_id
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all():
        person_id = str(row.get("person_id") or "").strip()
        if person_id:
            snapshot["customer_service"][person_id] = {
                "payout_status": row.get("payout_status"),
                "paid_at": row.get("paid_at"),
            }

    return snapshot


def _mw_r8_restore_payout_status(db, order_id: int, snapshot: dict) -> None:
    for person_id, state in (snapshot.get("worker") or {}).items():
        db.execute(
            text(
                """
                UPDATE worker_payouts
                SET payout_status = :payout_status,
                    paid_at = :paid_at
                WHERE order_id = :order_id
                  AND worker_discord_id = :person_id
                """
            ),
            {
                "payout_status": state.get("payout_status"),
                "paid_at": state.get("paid_at"),
                "order_id": int(order_id),
                "person_id": str(person_id),
            },
        )

    for person_id, state in (snapshot.get("customer_service") or {}).items():
        db.execute(
            text(
                """
                UPDATE customer_service_payouts
                SET payout_status = :payout_status,
                    paid_at = :paid_at
                WHERE order_id = :order_id
                  AND customer_service_discord_id = :person_id
                """
            ),
            {
                "payout_status": state.get("payout_status"),
                "paid_at": state.get("paid_at"),
                "order_id": int(order_id),
                "person_id": str(person_id),
            },
        )


def _mw_r8_worker_rows(db, order_id: int) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT
                oa.id AS assignment_id,
                oa.worker_discord_id,
                oa.worker_display_name,
                oa.has_named_bonus,
                oa.is_active,
                wp.id AS payout_id,
                wp.gross_share,
                wp.base_payout,
                wp.named_bonus_amount,
                wp.final_payout,
                wp.payout_status,
                wp.paid_at
            FROM order_assignments oa
            LEFT JOIN worker_payouts wp
              ON wp.id = (
                    SELECT wp2.id
                    FROM worker_payouts wp2
                    WHERE wp2.order_id = oa.order_id
                      AND wp2.worker_discord_id = oa.worker_discord_id
                    ORDER BY wp2.id DESC
                    LIMIT 1
                )
            WHERE oa.order_id = :order_id
              AND COALESCE(oa.is_active, 1) = 1
            ORDER BY oa.id ASC
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all()

    return [dict(row) for row in rows]


def _mw_r8_cs_payout_rows(db, order_id: int) -> list[dict]:
    rows = db.execute(
        text(
            """
            SELECT
                id,
                customer_service_discord_id,
                customer_service_display_name,
                rate,
                payout_amount,
                payout_status,
                paid_at
            FROM customer_service_payouts
            WHERE order_id = :order_id
            ORDER BY id DESC
            """
        ),
        {"order_id": int(order_id)},
    ).mappings().all()

    return [dict(row) for row in rows]


@router.get("/admin/orders/history")
async def admin_order_history_redirect_r8(request: Request):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    return RedirectResponse(url="/admin", status_code=303)


@router.get("/admin/order-workspace/{order_id}")
async def admin_order_workspace_r8(
    order_id: int,
    request: Request,
    message: str | None = None,
    error: str | None = None,
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    db = SessionLocal()

    try:
        order, customer_history, meta = _mw4a2r6_load_order_bundle(
            db,
            int(order_id),
        )

        if order is None:
            return RedirectResponse(
                url="/admin?error=%E6%89%BE%E4%B8%8D%E5%88%B0%E9%80%99%E7%AD%86%E8%A8%82%E5%96%AE",
                status_code=303,
            )

        financial = db.execute(
            text(
                """
                SELECT
                    closed_at,
                    updated_at,
                    amount,
                    customer_pay_amount,
                    original_amount,
                    payout_base_amount
                FROM web_orders
                WHERE id = :order_id
                LIMIT 1
                """
            ),
            {"order_id": int(order_id)},
        ).mappings().first()

        financial = dict(financial) if financial is not None else {}

        finalized_at = financial.get("closed_at")
        if (
            not finalized_at
            and str(order.get("status") or "").strip().lower()
            in {"closed", "completed", "done", "cancelled", "canceled"}
        ):
            # Historical final orders may predate closed_at-on-cancel. Display the best existing
            # timestamp without bulk-mutating old rows.
            finalized_at = financial.get("updated_at")
        order["closed_date"] = str(finalized_at or "")[:10]
        order["raw_amount"] = _mw4a2r6_safe_int(financial.get("amount"), 0)
        order["customer_pay_amount"] = _mw4a2r6_safe_int(
            financial.get("customer_pay_amount"),
            None,
        )
        order["original_amount"] = _mw4a2r6_safe_int(
            financial.get("original_amount"),
            None,
        )
        order["payout_base_amount"] = _mw4a2r6_safe_int(
            financial.get("payout_base_amount"),
            None,
        )

        customer_service_members = _mw4a2r6_cs_members(db)
        worker_members = list_admin_worker_dropdown_members()
        workspace_assignments = _mw_r8_worker_rows(db, int(order_id))
        workspace_cs_payouts = _mw_r8_cs_payout_rows(db, int(order_id))

    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="admin_order_detail.html",
        context={
            "title": order["order_no"] + "｜客服後台",
            "user": user,
            "order": order,
            "meta": meta,
            "customer_history": customer_history,
            "customer_service_members": customer_service_members,
            "worker_members": worker_members,
            "workspace_assignments": workspace_assignments,
            "workspace_cs_payouts": workspace_cs_payouts,
            "paid_status": PayoutStatus.PAID.value,
            "unpaid_status": PayoutStatus.UNPAID.value,
            "message": message,
            "error": error,
        },
    )


@router.post("/admin/order-workspace/{order_id}/edit")
async def admin_order_workspace_edit_r8(
    order_id: int,
    request: Request,
    customer_display_name: str = Form(default=""),
    customer_discord_id: str = Form(default=""),
    category: str = Form(default=""),
    item: str = Form(default=""),
    quantity: int = Form(default=1),
    amount: int = Form(default=0),
    payment_method: str = Form(default=""),
    status: str = Form(default="active"),
    closed_date: str = Form(default=""),
    closed_date_auto: str = Form(default=""),
    closed_date_touched: str = Form(default=""),
    customer_service_discord_id: str = Form(default=""),
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    allowed_statuses = {
        "pending_cs_dispatch",
        "waiting_acceptance",
        "accepted_pending_pay",
        "created",
        "paid",
        "active",
        "stored",
        "completed",
        "done",
        "closed",
        "cancelled",
        "canceled",
    }

    customer_display_name = str(customer_display_name or "").strip()
    customer_discord_id = str(customer_discord_id or "").strip()
    category = str(category or "").strip()
    item = str(item or "").strip()
    payment_method = str(payment_method or "").strip()
    status = str(status or "active").strip().lower()
    closed_date = str(closed_date or "").strip()
    closed_date_auto = str(closed_date_auto or "").strip().lower()
    closed_date_touched = str(closed_date_touched or "").strip().lower()
    customer_service_discord_id = str(customer_service_discord_id or "").strip()

    if quantity < 1:
        return _mw4a2r6_redirect(order_id, error="數量至少要是 1。")

    if amount < 0:
        return _mw4a2r6_redirect(order_id, error="金額不能小於 0。")

    if status not in allowed_statuses:
        return _mw4a2r6_redirect(order_id, error="訂單狀態不在允許清單。")

    if closed_date and not _mw_r8_re.fullmatch(r"\d{4}-\d{2}-\d{2}", closed_date):
        return _mw4a2r6_redirect(order_id, error="結案日期格式必須是 YYYY-MM-DD。")

    db = SessionLocal()

    try:
        before_row = db.execute(
            text("SELECT * FROM web_orders WHERE id = :order_id LIMIT 1"),
            {"order_id": int(order_id)},
        ).mappings().first()

        if before_row is None:
            return _mw4a2r6_redirect(order_id, error="找不到這筆訂單。")

        before = _mw_r8_jsonable_row(before_row)
        payout_snapshot = _mw_r8_snapshot_payout_status(db, int(order_id))

        if not customer_service_discord_id:
            customer_service_discord_id = str(
                before.get("customer_service_discord_id") or ""
            ).strip()

        customer_service_display_name = str(
            before.get("customer_service_display_name") or ""
        ).strip()

        if customer_service_discord_id:
            staff_member = get_staff_member_by_id(
                db,
                discord_id=customer_service_discord_id,
            )
            customer_service_display_name = (
                get_staff_display_name(staff_member)
                if staff_member is not None
                else customer_service_display_name
                or customer_service_discord_id
            )

        db.execute(
            text(
                """
                UPDATE web_orders
                SET
                    customer_display_name = :customer_display_name,
                    customer_discord_id = :customer_discord_id,
                    customer_service_discord_id = :customer_service_discord_id,
                    customer_service_display_name = :customer_service_display_name,
                    category = :category,
                    item = :item,
                    quantity = :quantity,
                    amount = :amount,
                    customer_pay_amount = CASE
                        WHEN customer_pay_amount IS NULL THEN NULL
                        ELSE :amount
                    END,
                    payment_method = :payment_method,
                    status = :status,
                    closed_at = CASE
                        WHEN COALESCE(closed_at, '') <> ''
                             AND :closed_date_touched NOT IN ('1', 'true', 'yes', 'on')
                             AND substr(closed_at, 1, 10) = :closed_date
                        THEN closed_at
                        WHEN :closed_date_auto IN ('1', 'true', 'yes', 'on')
                             AND :status IN ('closed', 'completed', 'done', 'cancelled', 'canceled')
                             AND COALESCE(closed_at, '') = ''
                        THEN datetime('now', '+8 hours')
                        WHEN :closed_date_touched IN ('1', 'true', 'yes', 'on')
                             AND :closed_date <> ''
                        THEN :closed_date
                        WHEN :status IN ('closed', 'completed', 'done', 'cancelled', 'canceled')
                             AND COALESCE(closed_at, '') = ''
                             AND :closed_date = ''
                        THEN datetime('now', '+8 hours')
                        ELSE closed_at
                    END,
                    updated_at = datetime('now')
                WHERE id = :order_id
                """
            ),
            {
                "customer_display_name": customer_display_name,
                "customer_discord_id": customer_discord_id,
                "customer_service_discord_id": customer_service_discord_id or None,
                "customer_service_display_name": customer_service_display_name or None,
                "category": category,
                "item": item,
                "quantity": int(quantity),
                "amount": int(amount),
                "payment_method": payment_method or None,
                "status": status,
                "closed_date": closed_date,
                "closed_date_auto": closed_date_auto,
                "closed_date_touched": closed_date_touched,
                "order_id": int(order_id),
            },
        )

        if _mw4a2r6_table_exists(db, "order_acceptance_meta"):
            meta_status_map = {
                "completed": "closed",
                "done": "closed",
                "canceled": "cancelled",
            }
            meta_status = meta_status_map.get(status, status)
            db.execute(
                text(
                    """
                    UPDATE order_acceptance_meta
                    SET status = :status,
                        updated_at = datetime('now')
                    WHERE order_id = :order_id
                    """
                ),
                {
                    "status": meta_status,
                    "order_id": int(order_id),
                },
            )

        db.flush()

        active_assignment = db.execute(
            text(
                """
                SELECT 1
                FROM order_assignments
                WHERE order_id = :order_id
                  AND COALESCE(is_active, 1) = 1
                LIMIT 1
                """
            ),
            {"order_id": int(order_id)},
        ).fetchone()

        if active_assignment is not None and status in {
            "active",
            "stored",
            "completed",
            "done",
            "closed",
        }:
            if not customer_service_discord_id:
                raise ValueError(
                    "這張單已有正式接單人員，請先指定客服再儲存，避免分潤產生未指定客服。"
                )

            from web.app.services.order_service import recalculate_order_payouts

            recalculate_order_payouts(db, int(order_id))
            db.flush()
            _mw_r8_restore_payout_status(db, int(order_id), payout_snapshot)

        after_row = db.execute(
            text("SELECT * FROM web_orders WHERE id = :order_id LIMIT 1"),
            {"order_id": int(order_id)},
        ).mappings().first()

        from web.app.services.admin_service import write_admin_audit_log

        write_admin_audit_log(
            db,
            admin_user=user,
            action="order_workspace_edit",
            target_type="order",
            target_id=str(order_id),
            before=before,
            after=_mw_r8_jsonable_row(after_row),
        )

        db.commit()

    except ValueError as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id, error=str(exc))

    except Exception as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id, error=f"訂單資料更新失敗：{exc}")

    finally:
        db.close()

    return _mw4a2r6_redirect(order_id, message="訂單資料已更新。")


@router.post("/admin/order-workspace/{order_id}/add-worker")
async def admin_order_workspace_add_worker_r8(
    order_id: int,
    request: Request,
    worker_discord_id: str = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    db = SessionLocal()

    try:
        payout_snapshot = _mw_r8_snapshot_payout_status(db, int(order_id))
        staff_member = get_staff_member_by_id(db, discord_id=worker_discord_id)
        worker_display_name = (
            get_staff_display_name(staff_member)
            if staff_member is not None
            else worker_discord_id
        )
        add_worker_to_order(
            db,
            order_id=order_id,
            worker_discord_id=worker_discord_id,
            worker_display_name=worker_display_name,
            admin_user=user,
            reason=reason,
        )
        _mw_r8_restore_payout_status(db, int(order_id), payout_snapshot)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id, error=str(exc))
    finally:
        db.close()

    return _mw4a2r6_redirect(order_id, message="已新增接單人員，分潤已重新計算。")


@router.post("/admin/order-workspace/{order_id}/assignments/{assignment_id}/named-bonus")
async def admin_order_workspace_named_bonus_r8(
    order_id: int,
    assignment_id: int,
    request: Request,
    enabled: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    db = SessionLocal()

    try:
        payout_snapshot = _mw_r8_snapshot_payout_status(db, int(order_id))
        toggle_named_bonus_for_assignment(
            db,
            assignment_id=assignment_id,
            enabled=enabled == "on",
            admin_user=user,
        )
        _mw_r8_restore_payout_status(db, int(order_id), payout_snapshot)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id, error=str(exc))
    finally:
        db.close()

    return _mw4a2r6_redirect(order_id, message="掛名加成已更新。")


@router.post("/admin/order-workspace/{order_id}/assignments/{assignment_id}/remove")
async def admin_order_workspace_remove_worker_r8(
    order_id: int,
    assignment_id: int,
    request: Request,
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    db = SessionLocal()

    try:
        payout_snapshot = _mw_r8_snapshot_payout_status(db, int(order_id))
        remove_worker_from_order(
            db,
            assignment_id=assignment_id,
            admin_user=user,
            reason=reason,
        )
        _mw_r8_restore_payout_status(db, int(order_id), payout_snapshot)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id, error=str(exc))
    finally:
        db.close()

    return _mw4a2r6_redirect(order_id, message="已移除接單人員，分潤已重新計算。")


@router.post("/admin/order-workspace/{order_id}/manual-payout")
async def admin_order_workspace_manual_payout_r8(
    order_id: int,
    request: Request,
    worker_discord_id: str = Form(...),
    worker_display_name: str | None = Form(default=None),
    manual_final_payout: int = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    db = SessionLocal()

    try:
        payout_snapshot = _mw_r8_snapshot_payout_status(db, int(order_id))
        set_manual_worker_payout(
            db,
            order_id=order_id,
            worker_discord_id=worker_discord_id,
            worker_display_name=worker_display_name,
            manual_final_payout=manual_final_payout,
            reason=reason,
            admin_user=user,
        )
        _mw_r8_restore_payout_status(db, int(order_id), payout_snapshot)
        db.commit()
    except ValueError as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id, error=str(exc))
    finally:
        db.close()

    return _mw4a2r6_redirect(order_id, message="接單人員分潤金額已更新。")


@router.post("/admin/order-workspace/{order_id}/worker-payouts/{payout_id}/status")
async def admin_order_workspace_worker_payout_status_r8(
    order_id: int,
    payout_id: int,
    request: Request,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    db = SessionLocal()

    try:
        set_worker_payout_status(
            db,
            payout_id=payout_id,
            status=status,
            admin_user=user,
        )
    except ValueError as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id, error=str(exc))
    finally:
        db.close()

    return _mw4a2r6_redirect(order_id, message="接單人員分潤狀態已更新。")


@router.post("/admin/order-workspace/{order_id}/customer-service-payouts/{payout_id}/status")
async def admin_order_workspace_cs_payout_status_r8(
    order_id: int,
    payout_id: int,
    request: Request,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return RedirectResponse(url="/service", status_code=303)

    db = SessionLocal()

    try:
        set_customer_service_payout_status(
            db,
            payout_id=payout_id,
            status=status,
            admin_user=user,
        )
    except ValueError as exc:
        db.rollback()
        return _mw4a2r6_redirect(order_id, error=str(exc))
    finally:
        db.close()

    return _mw4a2r6_redirect(order_id, message="客服分潤狀態已更新。")

# END MAWAN_R8_ORDER_WORKSPACE


@router.post(
    "/admin/order-workspace/{order_id}/internal-note"
)
async def admin_order_internal_note_r6(
    order_id: int,
    request: Request,
    internal_note: str = Form(
        default=""
    ),
):

    user = require_admin_user(
        request
    )


    if not user:

        return RedirectResponse(
            url="/service",
            status_code=303,
        )


    internal_note = str(
        internal_note
        or ""
    ).strip()


    if len(
        internal_note
    ) > 3000:

        return _mw4a2r6_redirect(
            order_id,
            error=
                "客服內部備註最多 3000 字。",
        )


    db = SessionLocal()


    try:

        exists = db.execute(
            text(
                """
                SELECT 1

                FROM web_orders

                WHERE id =
                    :order_id

                LIMIT 1
                """
            ),
            {
                "order_id":
                    int(
                        order_id
                    ),
            },
        ).fetchone()


        if exists is None:

            return _mw4a2r6_redirect(
                order_id,
                error=
                    "找不到這筆訂單。",
            )


        _mw4a2r6_ensure_meta_table(
            db
        )


        db.execute(
            text(
                """
                INSERT INTO
                web_admin_order_meta (

                    order_id,
                    internal_note,
                    updated_by_discord_id,
                    updated_by_display_name,
                    updated_at

                )

                VALUES (

                    :order_id,
                    :internal_note,
                    :updated_by_discord_id,
                    :updated_by_display_name,
                    CURRENT_TIMESTAMP

                )

                ON CONFLICT(order_id)
                DO UPDATE SET

                    internal_note =
                        excluded.internal_note,

                    updated_by_discord_id =
                        excluded.updated_by_discord_id,

                    updated_by_display_name =
                        excluded.updated_by_display_name,

                    updated_at =
                        CURRENT_TIMESTAMP
                """
            ),
            {
                "order_id":
                    int(
                        order_id
                    ),

                "internal_note":
                    internal_note,

                "updated_by_discord_id":
                    str(
                        user.get(
                            "id"
                        )
                        or ""
                    ),

                "updated_by_display_name":
                    _mw4a2r6_user_name(
                        user
                    ),
            },
        )


        db.commit()


    except Exception as exc:

        db.rollback()


        return _mw4a2r6_redirect(
            order_id,
            error=(
                "儲存客服內部備註失敗："
                + str(
                    exc
                )
            ),
        )


    finally:

        db.close()


    return _mw4a2r6_redirect(
        order_id,
        message=
            "客服內部備註已儲存。",
    )


@router.post(
    "/admin/order-workspace/{order_id}/attention"
)
async def admin_order_attention_r6(
    order_id: int,
    request: Request,
    enabled: str | None = Form(
        default=None
    ),
    attention_reason: str = Form(
        default=""
    ),
):

    user = require_admin_user(
        request
    )


    if not user:

        return RedirectResponse(
            url="/service",
            status_code=303,
        )


    enabled_value = (
        1

        if str(
            enabled
            or ""
        ).lower()
        in {
            "1",
            "true",
            "yes",
            "on",
        }

        else 0
    )


    attention_reason = str(
        attention_reason
        or ""
    ).strip()


    if len(
        attention_reason
    ) > 1000:

        return _mw4a2r6_redirect(
            order_id,
            error=
                "注意原因最多 1000 字。",
        )


    if not enabled_value:

        attention_reason = ""


    db = SessionLocal()


    try:

        exists = db.execute(
            text(
                """
                SELECT 1

                FROM web_orders

                WHERE id =
                    :order_id

                LIMIT 1
                """
            ),
            {
                "order_id":
                    int(
                        order_id
                    ),
            },
        ).fetchone()


        if exists is None:

            return _mw4a2r6_redirect(
                order_id,
                error=
                    "找不到這筆訂單。",
            )


        _mw4a2r6_ensure_meta_table(
            db
        )


        db.execute(
            text(
                """
                INSERT INTO
                web_admin_order_meta (

                    order_id,
                    needs_attention,
                    attention_reason,
                    updated_by_discord_id,
                    updated_by_display_name,
                    updated_at

                )

                VALUES (

                    :order_id,
                    :needs_attention,
                    :attention_reason,
                    :updated_by_discord_id,
                    :updated_by_display_name,
                    CURRENT_TIMESTAMP

                )

                ON CONFLICT(order_id)
                DO UPDATE SET

                    needs_attention =
                        excluded.needs_attention,

                    attention_reason =
                        excluded.attention_reason,

                    updated_by_discord_id =
                        excluded.updated_by_discord_id,

                    updated_by_display_name =
                        excluded.updated_by_display_name,

                    updated_at =
                        CURRENT_TIMESTAMP
                """
            ),
            {
                "order_id":
                    int(
                        order_id
                    ),

                "needs_attention":
                    enabled_value,

                "attention_reason":
                    attention_reason,

                "updated_by_discord_id":
                    str(
                        user.get(
                            "id"
                        )
                        or ""
                    ),

                "updated_by_display_name":
                    _mw4a2r6_user_name(
                        user
                    ),
            },
        )


        db.commit()


    except Exception as exc:

        db.rollback()


        return _mw4a2r6_redirect(
            order_id,
            error=(
                "更新注意標記失敗："
                + str(
                    exc
                )
            ),
        )


    finally:

        db.close()


    return _mw4a2r6_redirect(
        order_id,
        message=(
            "已標記為需注意。"

            if enabled_value

            else "已解除注意標記。"
        ),
    )
