from __future__ import annotations

from inspect import signature
from pathlib import Path
from urllib.parse import urlencode
import json

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select

from shared.db import SessionLocal
from shared.staff_models import WebStaffMember
from web.app.services.role_catalog import (
    COMPANION_ROLE_IDS,
    CUSTOMER_SERVICE_LABEL,
    CUSTOMER_SERVICE_ROLE_ID,
    RECEIVER_ROLE_IDS,
    STAFF_ROLE_FILTERS,
    receiver_labels_from_roles,
)
from web.app.services.staff_service import sync_staff_members_from_discord


router = APIRouter(tags=["admin-staff"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

VALID_STAFF_ROLE_FILTERS = {option["value"] for option in STAFF_ROLE_FILTERS}
VALID_STAFF_ROLE_FILTERS |= {"all", "worker", "companion"}


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def require_admin(request: Request) -> dict | None:
    user = get_current_user(request)
    if not user or not user.get("is_admin"):
        return None
    return user


def get_member_receiver_labels(member: WebStaffMember) -> list[str]:
    try:
        role_ids = json.loads(member.roles_json or "[]")
    except Exception:
        role_ids = []

    return receiver_labels_from_roles(role_ids)


def prepare_member_labels(members: list[WebStaffMember]) -> list[WebStaffMember]:
    for member in members:
        try:
            member.receiver_role_labels = get_member_receiver_labels(member)
        except Exception:
            pass

    return members


def member_matches_keyword(member: WebStaffMember, keyword: str) -> bool:
    if not keyword:
        return True

    keyword = keyword.lower()

    return (
        keyword in str(member.display_name or "").lower()
        or keyword in str(member.username or "").lower()
        or keyword in str(member.global_name or "").lower()
        or keyword in str(member.discord_id or "").lower()
        or keyword in str(member.roles_json or "").lower()
    )



def reclassify_staff_members(db) -> None:
    all_members = list(db.scalars(select(WebStaffMember)).all())

    customer_service_role_ids = {CUSTOMER_SERVICE_ROLE_ID}

    for member in all_members:
        try:
            role_ids = set(json.loads(member.roles_json or "[]"))
        except Exception:
            role_ids = set()

        member.is_customer_service = bool(role_ids & customer_service_role_ids)
        member.is_worker = bool(role_ids & RECEIVER_ROLE_IDS)
        member.is_companion = bool(role_ids & COMPANION_ROLE_IDS)
        member.is_active = bool(
            member.is_customer_service
            or member.is_worker
            or member.is_companion
        )


def build_sync_message(result) -> str:
    if isinstance(result, dict):
        if result.get("message"):
            return str(result["message"])

        scanned = (
            result.get("scanned")
            or result.get("scanned_count")
            or result.get("total")
            or result.get("total_members")
            or result.get("fetched")
            or "?"
        )
        written = (
            result.get("written")
            or result.get("written_count")
            or result.get("upserted")
            or result.get("synced")
            or result.get("saved")
            or "?"
        )

        return f"成員同步完成：掃描 {scanned} 人，寫入 {written} 人。"

    return "成員同步完成。"


@router.get("/admin/staff")
async def admin_staff_page(
    request: Request,
    role: str = "all",
    status: str = "active",
    q: str = "",
    message: str | None = None,
    error: str | None = None,
):
    user = require_admin(request)

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "你沒有客服後台權限。",
                "user": get_current_user(request),
            },
            status_code=403,
        )

    if role not in VALID_STAFF_ROLE_FILTERS:
        role = "all"

    if status not in {"active", "inactive", "all"}:
        status = "active"

    db = SessionLocal()

    try:
        all_members = list(db.scalars(select(WebStaffMember)).all())

        active_members = [member for member in all_members if member.is_active]
        inactive_members = [member for member in all_members if not member.is_active]

        if status == "inactive":
            members = inactive_members
        elif status == "all":
            members = all_members
        else:
            members = active_members

        if role == "customer_service":
            members = [member for member in members if member.is_customer_service]
        elif role in RECEIVER_ROLE_IDS:
            members = [
                member
                for member in members
                if role in str(member.roles_json or "")
            ]
        elif role == "worker":
            members = [member for member in members if member.is_worker]
        elif role == "companion":
            members = [member for member in members if member.is_companion]

        keyword = q.strip()
        if keyword:
            members = [
                member
                for member in members
                if member_matches_keyword(member, keyword)
            ]

        members.sort(
            key=lambda member: str(
                member.display_name
                or member.global_name
                or member.username
                or member.discord_id
            )
        )

        prepare_member_labels(members)

        stats = {
            "total": len(all_members),
            "active": len(active_members),
            "inactive": len(inactive_members),
            "customer_service": len([
                member for member in active_members
                if member.is_customer_service
            ]),
            "worker": len([
                member for member in active_members
                if member.is_worker
            ]),
            "companion": len([
                member for member in active_members
                if member.is_companion
            ]),
        }
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="admin_staff.html",
        context={
            "title": "人員名單",
            "user": user,
            "members": members,
            "stats": stats,
            "role": role,
            "status": status,
            "q": q,
            "message": message,
            "error": error,
            "role_filter_options": STAFF_ROLE_FILTERS,
            "staff_role_filters": STAFF_ROLE_FILTERS,
            "customer_service_label": CUSTOMER_SERVICE_LABEL,
        },
    )


async def run_admin_staff_sync(request: Request):
    user = require_admin(request)

    if not user:
        return RedirectResponse(url="/no-access", status_code=303)

    db = SessionLocal()

    try:
        result = sync_staff_members_from_discord(db)
        db.commit()
        query = {"message": build_sync_message(result)}
    except Exception as exc:
        try:
            db.rollback()
        except Exception:
            pass

        print("[admin_staff_sync_error]", repr(exc))
        query = {"error": f"成員同步失敗：{exc}"}
    finally:
        db.close()

    return RedirectResponse(
        url=f"/admin/staff?{urlencode(query)}",
        status_code=303,
    )


@router.post("/admin/staff/sync")
async def admin_staff_sync(request: Request):
    return await run_admin_staff_sync(request)


@router.get("/admin/staff/sync")
async def admin_staff_sync_get(request: Request):
    return await run_admin_staff_sync(request)

# MAWAN PHASE 4B-2 V4 STAFF WORKSPACE

from sqlalchemy import (
    text as _mw4b2_text,
)


def _mw4b2_int(
    value,
    default=0,
):

    try:
        return int(value)

    except (
        TypeError,
        ValueError,
    ):
        return default


def _mw4b2_float(
    value,
    default=0.0,
):

    try:
        return float(value)

    except (
        TypeError,
        ValueError,
    ):
        return default


def _mw4b2_admin_user(
    request,
):

    checker = globals().get(
        "require_admin"
    )


    if callable(
        checker
    ):

        try:

            value = checker(
                request
            )


            if value:

                getter = globals().get(
                    "get_current_user"
                )


                if callable(
                    getter
                ):

                    try:

                        return (
                            getter(
                                request
                            )
                            or value
                        )

                    except Exception:
                        pass


                return value


        except Exception:
            pass


    getter = globals().get(
        "get_current_user"
    )


    if callable(
        getter
    ):

        try:

            user = getter(
                request
            )


            if (
                user
                and (
                    user.get(
                        "is_admin"
                    )

                    or user.get(
                        "is_owner"
                    )

                    or user.get(
                        "admin"
                    )
                )
            ):

                return user


        except Exception:
            pass


    user = (
        request.session.get(
            "user"
        )
        or {}
    )


    if (
        user.get(
            "is_admin"
        )

        or user.get(
            "is_owner"
        )

        or user.get(
            "admin"
        )
    ):

        return user


    return None


def _mw4b2_load_staff(
    db,
    discord_id,
):

    member_row = db.execute(
        _mw4b2_text(
            """
            SELECT *

            FROM web_staff_members

            WHERE discord_id =
                :discord_id

            LIMIT 1
            """
        ),
        {
            "discord_id":
                str(
                    discord_id
                ),
        },
    ).mappings().first()


    if member_row is None:

        return None


    member = dict(
        member_row
    )


    member[
        "name"
    ] = str(

        member.get(
            "display_name"
        )

        or member.get(
            "global_name"
        )

        or member.get(
            "username"
        )

        or member.get(
            "discord_id"
        )

        or "未命名"

    )


    member[
        "active"
    ] = bool(
        _mw4b2_int(
            member.get(
                "is_active"
            ),
            0,
        )
    )


    try:

        role_ids = json.loads(
            member.get(
                "roles_json"
            )
            or "[]"
        )

    except Exception:

        role_ids = []


    role_labels = []


    try:

        role_labels = list(
            receiver_labels_from_roles(
                role_ids
            )
        )

    except Exception:

        role_labels = []


    if (
        member.get(
            "is_customer_service"
        )

        and CUSTOMER_SERVICE_LABEL
        not in role_labels
    ):

        role_labels.insert(
            0,
            CUSTOMER_SERVICE_LABEL,
        )


    if (
        member.get(
            "is_worker"
        )

        and not any(
            "護"
            in str(value)
            for value
            in role_labels
        )
    ):

        role_labels.append(
            "護航"
        )


    if (
        member.get(
            "is_companion"
        )

        and not any(
            "陪"
            in str(value)
            for value
            in role_labels
        )
    ):

        role_labels.append(
            "陪玩"
        )


    member[
        "role_labels"
    ] = role_labels


    profile_row = db.execute(
        _mw4b2_text(
            """
            SELECT *

            FROM staff_profiles

            WHERE staff_discord_id =
                :discord_id

            LIMIT 1
            """
        ),
        {
            "discord_id":
                str(
                    discord_id
                ),
        },
    ).mappings().first()


    profile = (
        dict(
            profile_row
        )
        if profile_row
        else {}
    )


    order_rows = db.execute(
        _mw4b2_text(
            """
            SELECT DISTINCT
                wo.id,
                wo.bot_order_no,
                wo.customer_discord_id,
                wo.customer_display_name,
                wo.category,
                wo.item,
                wo.status,
                wo.amount,
                wo.customer_pay_amount,
                wo.created_at,
                wo.closed_at

            FROM order_assignments oa

            JOIN web_orders wo
              ON wo.id =
                 oa.order_id

            WHERE oa.worker_discord_id =
                :discord_id

            ORDER BY
                wo.id DESC
            """
        ),
        {
            "discord_id":
                str(
                    discord_id
                ),
        },
    ).mappings().all()


    completed_statuses = {
        "closed",
        "completed",
        "done",
    }


    cancelled_statuses = {
        "cancelled",
        "canceled",
    }


    status_labels = {
        "pending_cs_dispatch":
            "待客服確認",

        "waiting_acceptance":
            "等待接單",

        "accepted_pending_pay":
            "等待付款",

        "active":
            "進行中",

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


    order_stats = {
        "total":
            len(
                order_rows
            ),

        "completed":
            0,

        "active":
            0,

        "cancelled":
            0,
    }


    recent_orders = []


    for raw in order_rows:

        row = dict(
            raw
        )


        status = str(
            row.get(
                "status"
            )
            or ""
        ).strip().lower()


        if status in completed_statuses:

            order_stats[
                "completed"
            ] += 1


        elif status in cancelled_statuses:

            order_stats[
                "cancelled"
            ] += 1


        else:

            order_stats[
                "active"
            ] += 1


        if len(
            recent_orders
        ) >= 10:

            continue


        amount = row.get(
            "customer_pay_amount"
        )


        if amount in (
            None,
            "",
        ):

            amount = row.get(
                "amount"
            )


        recent_orders.append(
            {
                "id":
                    _mw4b2_int(
                        row.get(
                            "id"
                        ),
                        0,
                    ),

                "order_no":
                    str(
                        row.get(
                            "bot_order_no"
                        )

                        or (
                            "WEB-"
                            + str(
                                row.get(
                                    "id"
                                )
                                or ""
                            )
                        )
                    ),

                "customer_name":
                    str(
                        row.get(
                            "customer_display_name"
                        )

                        or row.get(
                            "customer_discord_id"
                        )

                        or "未紀錄"
                    ),

                "item":
                    str(
                        row.get(
                            "item"
                        )
                        or "未紀錄"
                    ),

                "amount":
                    _mw4b2_int(
                        amount,
                        0,
                    ),

                "status_label":
                    status_labels.get(
                        status,
                        status or "未知",
                    ),

                "created_at":
                    str(
                        row.get(
                            "created_at"
                        )
                        or ""
                    )[:16],
            }
        )


    review_rows = db.execute(
        _mw4b2_text(
            """
            SELECT
                id,
                order_id,
                rating,
                comment,
                created_at

            FROM order_reviews

            WHERE staff_discord_id =
                :discord_id

              AND COALESCE(
                    is_public,
                    1
                  ) = 1

              AND COALESCE(
                    is_hidden,
                    0
                  ) = 0

            ORDER BY
                id DESC
            """
        ),
        {
            "discord_id":
                str(
                    discord_id
                ),
        },
    ).mappings().all()


    ratings = [
        _mw4b2_float(
            row.get(
                "rating"
            ),
            0.0,
        )

        for row
        in review_rows

        if row.get(
            "rating"
        )
        not in (
            None,
            "",
        )
    ]


    average_rating = (
        round(
            sum(
                ratings
            )
            / len(
                ratings
            ),
            1,
        )

        if ratings

        else 0.0
    )


    recent_reviews = [
        {
            "rating":
                row.get(
                    "rating"
                ),

            "comment":
                str(
                    row.get(
                        "comment"
                    )
                    or ""
                ),

            "created_at":
                str(
                    row.get(
                        "created_at"
                    )
                    or ""
                )[:16],
        }

        for row
        in review_rows[:6]
    ]


    favorite_count = (
        db.execute(
            _mw4b2_text(
                """
                SELECT COUNT(*)

                FROM staff_favorites

                WHERE staff_discord_id =
                    :discord_id
                """
            ),
            {
                "discord_id":
                    str(
                        discord_id
                    ),
            },
        ).scalar()
        or 0
    )


    return {
        "member":
            member,

        "profile":
            profile,

        "order_stats":
            order_stats,

        "recent_orders":
            recent_orders,

        "review_stats":
            {
                "count":
                    len(
                        review_rows
                    ),

                "average":
                    average_rating,

                "recent":
                    recent_reviews,
            },

        "favorite_count":
            int(
                favorite_count
            ),
    }


@router.get(
    "/admin/staff/{discord_id}"
)
async def admin_staff_detail_v4(
    discord_id: str,
    request: Request,
):

    user = _mw4b2_admin_user(
        request
    )


    if not user:

        return RedirectResponse(
            url="/admin",
            status_code=303,
        )


    db = SessionLocal()


    try:

        bundle = (
            _mw4b2_load_staff(
                db,
                str(
                    discord_id
                ),
            )
        )


    finally:

        db.close()


    if bundle is None:

        return RedirectResponse(
            url=(
                "/admin/staff"
                "?error="
                "%E6%89%BE%E4%B8%8D%E5%88%B0%E9%80%99%E4%BD%8D%E4%BA%BA%E5%93%A1"
            ),
            status_code=303,
        )


    return templates.TemplateResponse(
        request=request,
        name=
            "admin_staff_detail.html",
        context={
            "title":
                (
                    bundle[
                        "member"
                    ][
                        "name"
                    ]
                    + "｜人員管理"
                ),

            "user":
                user,

            **bundle,
        },
    )

# MAWAN WEBSITE FINAL NON-ORDER V1 - CUSTOMER MANAGEMENT

@router.get("/admin/customers")
async def admin_customers_final(request: Request, q: str = ""):
    user=_mw4b2_admin_user(request)
    if not user: return RedirectResponse(url="/admin",status_code=303)
    key=str(q or "").strip().lower(); db=SessionLocal()
    try:
        rows=db.execute(_mw4b2_text("""
            SELECT customer_discord_id,MAX(customer_display_name) customer_display_name,
                   COUNT(*) order_count,
                   SUM(CASE WHEN status IN ('closed','completed','done') THEN 1 ELSE 0 END) completed_count,
                   SUM(CASE WHEN status IN ('cancelled','canceled') THEN 1 ELSE 0 END) cancelled_count,
                   MAX(created_at) last_order_at
            FROM web_orders
            WHERE customer_discord_id IS NOT NULL AND TRIM(customer_discord_id)<>''
            GROUP BY customer_discord_id ORDER BY last_order_at DESC
        """)).mappings().all()
        customers=[]
        for x in rows:
            x=dict(x); cid=str(x.get("customer_discord_id") or ""); name=str(x.get("customer_display_name") or cid)
            if key and key not in cid.lower() and key not in name.lower(): continue
            spend=db.execute(_mw4b2_text("""
                SELECT COALESCE(SUM(CASE WHEN status NOT IN ('cancelled','canceled')
                    THEN COALESCE(customer_pay_amount,amount,0) ELSE 0 END),0)
                FROM web_orders WHERE customer_discord_id=:cid
            """),{"cid":cid}).scalar() or 0
            fav=db.execute(_mw4b2_text("SELECT COUNT(*) FROM staff_favorites WHERE customer_discord_id=:cid"),{"cid":cid}).scalar() or 0
            rev=db.execute(_mw4b2_text("SELECT COUNT(*) FROM order_reviews WHERE customer_discord_id=:cid"),{"cid":cid}).scalar() or 0
            customers.append(dict(
                customer_discord_id=cid,customer_display_name=name,
                order_count=int(x.get("order_count") or 0),completed_count=int(x.get("completed_count") or 0),
                cancelled_count=int(x.get("cancelled_count") or 0),total_spend=int(spend),
                favorite_count=int(fav),review_count=int(rev),last_order_at=str(x.get("last_order_at") or "")[:16]
            ))
    finally: db.close()
    return templates.TemplateResponse(request=request,name="admin_customers.html",context={
        "title":"客戶管理｜魔丸娛樂","user":user,"q":q,"customers":customers})

@router.get("/admin/customers/{customer_discord_id}")
async def admin_customer_detail_final(customer_discord_id: str, request: Request):
    user=_mw4b2_admin_user(request)
    if not user: return RedirectResponse(url="/admin",status_code=303)
    cid=str(customer_discord_id or "").strip(); db=SessionLocal()
    try:
        orders=[dict(r) for r in db.execute(_mw4b2_text(
            "SELECT * FROM web_orders WHERE customer_discord_id=:cid ORDER BY id DESC LIMIT 80"),{"cid":cid}).mappings().all()]
        if not orders: return RedirectResponse(url="/admin/customers?error=not_found",status_code=303)
        name=str(orders[0].get("customer_display_name") or cid)
        favorites=[dict(r) for r in db.execute(_mw4b2_text("""
            SELECT f.staff_discord_id,COALESCE(p.display_name,f.staff_display_name,f.staff_discord_id) staff_name,
                   p.profile_type,p.role_title,f.created_at
            FROM staff_favorites f LEFT JOIN staff_profiles p ON p.staff_discord_id=f.staff_discord_id
            WHERE f.customer_discord_id=:cid ORDER BY f.id DESC
        """),{"cid":cid}).mappings().all()]
        reviews=[dict(r) for r in db.execute(_mw4b2_text("""
            SELECT id,order_id,staff_discord_id,staff_display_name,rating,comment,is_public,is_hidden,created_at
            FROM order_reviews WHERE customer_discord_id=:cid ORDER BY id DESC LIMIT 50
        """),{"cid":cid}).mappings().all()]
        wallet=[dict(r) for r in db.execute(_mw4b2_text(
            "SELECT * FROM web_checkout_wallet_transactions WHERE customer_discord_id=:cid ORDER BY id DESC LIMIT 30"),{"cid":cid}).mappings().all()]
        points=[dict(r) for r in db.execute(_mw4b2_text(
            "SELECT * FROM web_checkout_point_transactions WHERE customer_discord_id=:cid ORDER BY id DESC LIMIT 30"),{"cid":cid}).mappings().all()]
        done=sum(str(o.get("status") or "").lower() in {"closed","completed","done"} for o in orders)
        cancel=sum(str(o.get("status") or "").lower() in {"cancelled","canceled"} for o in orders)
        spend=sum(int(o.get("customer_pay_amount") or o.get("amount") or 0) for o in orders
                  if str(o.get("status") or "").lower() not in {"cancelled","canceled"})
    finally: db.close()
    return templates.TemplateResponse(request=request,name="admin_customer_detail.html",context={
        "title":name+"｜客戶管理","user":user,"customer_id":cid,"customer_name":name,
        "orders":orders,"favorites":favorites,"reviews":reviews,"wallet_transactions":wallet,"point_transactions":points,
        "wallet_balance":wallet[0].get("balance_after") if wallet else None,
        "point_balance":points[0].get("balance_after") if points else None,
        "stats":{"orders":len(orders),"completed":done,"cancelled":cancel,"total_spend":spend,
                 "favorites":len(favorites),"reviews":len(reviews)}})
