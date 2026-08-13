import sqlite3
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, or_
from sqlalchemy.orm import selectinload

from shared.db import SessionLocal
from shared.models import CustomerServicePayout, OrderAssignment, OrderStatus, PayoutStatus, WebOrder
from web.app.services.admin_service import (
    add_worker_to_order,
    remove_worker_from_order,
    set_customer_service_for_order,
    set_customer_service_payout_status,
    set_manual_worker_payout,
    set_worker_payout_status,
    toggle_named_bonus_for_assignment,
)
from web.app.services.staff_service import (
    get_staff_display_name,
    get_staff_member_by_id,
    list_customer_service_members,
    list_worker_members,
)

router = APIRouter(tags=["order-history"])

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def get_current_user(request: Request) -> dict | None:
    return request.session.get("user")


def require_admin_user(request: Request) -> dict | None:
    user = get_current_user(request)

    if not user:
        return None

    if not user.get("is_admin"):
        return None

    return user


def redirect_to_history(**params) -> RedirectResponse:
    query = {
        key: value
        for key, value in params.items()
        if value is not None and value != ""
    }

    if query:
        return RedirectResponse(
            url=f"/admin/orders/history?{urlencode(query)}",
            status_code=303,
        )


    conn = sqlite3.connect(history_db_path())

    try:
        for key, value in form.multi_items():
            if key.startswith("worker_payout_"):
                payout_id = history_to_int(key.replace("worker_payout_", ""), 0)
                amount = history_to_int(value, 0)

                if payout_id > 0:
                    conn.execute(
                        """
                        UPDATE worker_payouts
                        SET
                            gross_share = ?,
                            base_payout = ?,
                            named_bonus_amount = 0,
                            final_payout = ?
                        WHERE id = ?
                        """,
                        (amount, amount, amount, payout_id),
                    )

            if key.startswith("cs_payout_"):
                payout_id = history_to_int(key.replace("cs_payout_", ""), 0)
                amount = history_to_int(value, 0)

                if payout_id > 0:
                    conn.execute(
                        """
                        UPDATE customer_service_payouts
                        SET payout_amount = ?
                        WHERE id = ?
                        """,
                        (amount, payout_id),
                    )

        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(
        url=f"/admin/orders/history?page={form.get('page') or 1}",
        status_code=303,
    )



def parse_history_month_filter(month_filter: str | None):
    """把 2026-06 轉成當月起訖 datetime。"""
    month_text = str(month_filter or "").strip()

    if not month_text:
        return None

    try:
        start = datetime.strptime(month_text, "%Y-%m")
    except ValueError:
        return None

    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)

    return start, end


def list_history_orders(
    *,
    status_filter: str = "all",
    keyword: str | None = None,
    month_filter: str | None = None,
) -> list[WebOrder]:
    db = SessionLocal()

    try:
        statement = (
            select(WebOrder)
            .where(WebOrder.status != OrderStatus.ACTIVE.value)
            .options(selectinload(WebOrder.assignments))
            .options(selectinload(WebOrder.payouts))
            .order_by(WebOrder.updated_at.desc(), WebOrder.created_at.desc(), WebOrder.id.desc())
        )

        if status_filter and status_filter != "all":
            statement = statement.where(WebOrder.status == status_filter)

        if keyword:
            like_keyword = f"%{keyword.strip()}%"
            statement = statement.where(
                WebOrder.bot_order_no.like(like_keyword)
                | WebOrder.customer_display_name.like(like_keyword)
                | WebOrder.customer_discord_id.like(like_keyword)
                | WebOrder.category.like(like_keyword)
                | WebOrder.item.like(like_keyword)
            )

        month_range = parse_history_month_filter(month_filter)
        if month_range is not None:
            month_start, month_end = month_range
            statement = statement.where(
                or_(
                    (WebOrder.closed_at >= month_start) & (WebOrder.closed_at < month_end),
                    (
                        WebOrder.closed_at.is_(None)
                        & (WebOrder.updated_at >= month_start)
                        & (WebOrder.updated_at < month_end)
                    ),
                    (
                        WebOrder.closed_at.is_(None)
                        & WebOrder.updated_at.is_(None)
                        & (WebOrder.created_at >= month_start)
                        & (WebOrder.created_at < month_end)
                    ),
                )
            )

        return list(db.scalars(statement).all())
    finally:
        db.close()





def history_order_month_value(order) -> str:
    """歷史訂單月份：優先 closed_at，沒有才用 updated_at / created_at。"""
    for attr in ("closed_at", "updated_at", "created_at"):
        value = getattr(order, attr, None)

        if value is None:
            continue

        if isinstance(value, datetime):
            return value.strftime("%Y-%m")

        value_text = str(value).strip()

        if len(value_text) >= 7:
            return value_text[:7]

    return ""


def filter_history_orders_by_month(orders, month_filter: str | None):
    month_text = str(month_filter or "").strip()

    if not month_text:
        return orders

    return [
        order for order in orders
        if history_order_month_value(order) == month_text
    ]



def list_history_month_options() -> list[dict[str, str]]:
    """月份選單只顯示歷史訂單實際存在的月份。"""
    db = SessionLocal()

    try:
        statement = (
            select(WebOrder)
            .where(WebOrder.status != OrderStatus.ACTIVE.value)
            .order_by(WebOrder.updated_at.desc(), WebOrder.created_at.desc(), WebOrder.id.desc())
        )
        orders = db.scalars(statement).all()
    finally:
        db.close()

    month_values = sorted(
        {
            month_value
            for order in orders
            if (month_value := history_order_month_value(order))
        },
        reverse=True,
    )

    options: list[dict[str, str]] = []

    for month_value in month_values:
        try:
            year_text, month_text = month_value.split("-", 1)
            label = f"{int(year_text)} 年 {int(month_text)} 月"
        except Exception:
            label = month_value

        options.append({
            "value": month_value,
            "label": label,
        })

    return options


def history_to_int(value, default: int = 0) -> int:
    try:
        return int(str(value or "").strip())
    except Exception:
        return default


def history_safe_status(value) -> str:
    """歷史訂單狀態正規化。取消代表已退款，不進分潤。"""
    status = str(value or "").strip().lower()

    aliases = {
        "active": "active",
        "ongoing": "active",
        "進行中": "active",

        "stored": "stored",
        "saved": "stored",
        "存單": "stored",
        "審核中": "stored",

        "closed": "closed",
        "done": "closed",
        "已結單": "closed",
        "結單": "closed",

        "cancelled": "cancelled",
        "canceled": "cancelled",
        "cancel": "cancelled",
        "取消": "cancelled",
        "已取消": "cancelled",
        "退款": "cancelled",
        "已退款": "cancelled",
    }

    status = aliases.get(status, status)

    if status in {"active", "stored", "closed", "cancelled"}:
        return status

    return "closed"


def history_db_path() -> str:
    return str(Path.cwd() / "web_dashboard.db")



def fetch_history_payouts(order_ids: list[int]) -> dict[int, list[dict]]:
    """抓歷史訂單的打手/客服分潤，給歷史頁批量修改用。"""
    if not order_ids:
        return {}

    placeholders = ",".join("?" for _ in order_ids)
    result: dict[int, list[dict]] = {}

    conn = sqlite3.connect(history_db_path())
    conn.row_factory = sqlite3.Row

    try:
        worker_rows = conn.execute(
            f"""
            SELECT
                id,
                order_id,
                worker_discord_id AS person_id,
                worker_display_name AS person_name,
                final_payout AS amount,
                payout_status
            FROM worker_payouts
            WHERE order_id IN ({placeholders})
            ORDER BY id ASC
            """,
            order_ids,
        ).fetchall()

        for row in worker_rows:
            order_id = int(row["order_id"])
            result.setdefault(order_id, []).append(
                {
                    "kind": "worker",
                    "label": "護級 / 陪級",
                    "id": int(row["id"]),
                    "person_id": row["person_id"],
                    "person_name": row["person_name"] or row["person_id"],
                    "amount": int(row["amount"] or 0),
                    "payout_status": row["payout_status"],
                    "input_name": f"worker_payout_{int(row['id'])}",
                }
            )

        cs_rows = conn.execute(
            f"""
            SELECT
                id,
                order_id,
                customer_service_discord_id AS person_id,
                customer_service_display_name AS person_name,
                payout_amount AS amount,
                payout_status
            FROM customer_service_payouts
            WHERE order_id IN ({placeholders})
            ORDER BY id ASC
            """,
            order_ids,
        ).fetchall()

        for row in cs_rows:
            order_id = int(row["order_id"])
            result.setdefault(order_id, []).append(
                {
                    "kind": "customer_service",
                    "label": "客服",
                    "id": int(row["id"]),
                    "person_id": row["person_id"],
                    "person_name": row["person_name"] or row["person_id"],
                    "amount": int(row["amount"] or 0),
                    "payout_status": row["payout_status"],
                    "input_name": f"cs_payout_{int(row['id'])}",
                }
            )
    finally:
        conn.close()

    return result



def history_to_int(value, default: int = 0) -> int:
    try:
        return int(str(value or "").strip())
    except Exception:
        return default


def history_safe_status(value: str | None) -> str:
    value = str(value or "").strip()
    return value if value in {"active", "stored", "closed", "cancelled"} else "closed"


def history_effective_closed_date(order) -> str:
    """給歷史訂單頁顯示用：優先 closed_at，沒有就 updated_at，再沒有 created_at。"""
    value = (
        getattr(order, "closed_at", None)
        or getattr(order, "updated_at", None)
        or getattr(order, "created_at", None)
        or ""
    )
    return str(value)[:10] if str(value or "").strip() else ""



def history_closed_date_input_value(order) -> str:
    """給歷史訂單編輯欄位使用：只使用真正 closed_at，不用 updated_at / created_at fallback。"""
    return history_normalize_date(getattr(order, "closed_at", None))


def history_should_update_closed_at(current_closed_at, submitted_closed_at: str) -> bool:
    """只有使用者真的提交了結單日期，且和目前 closed_at 不同時，才更新 closed_at。"""
    submitted = history_normalize_date(submitted_closed_at)
    if not submitted:
        return False

    current = history_normalize_date(current_closed_at)
    return submitted != current

def history_normalize_date(value: str | None) -> str:
    """把 input type=date 的 YYYY-MM-DD 轉成可存進 SQLite 的 datetime 字串。"""
    value = str(value or "").strip()

    if not value:
        return ""

    # input type=date 正常只會送 YYYY-MM-DD；這裡保守檢查避免亂字串進 DB。
    parts = value.split("-")

    if len(parts) != 3:
        return ""

    year, month, day = parts

    if not (year.isdigit() and month.isdigit() and day.isdigit()):
        return ""

    if len(year) != 4 or len(month) != 2 or len(day) != 2:
        return ""

    return f"{year}-{month}-{day} 23:59:59"


def history_db_path() -> str:
    return str(Path.cwd() / "web_dashboard.db")

def history_parse_worker_option(value: str) -> tuple[str, str]:
    raw = str(value or "").strip()

    if "|" in raw:
        discord_id, role_type = raw.split("|", 1)
        discord_id = discord_id.strip()
        role_type = role_type.strip().lower()

        if role_type not in {"worker", "companion"}:
            role_type = "worker"

        return discord_id, role_type

    return raw, "worker"



def history_staff_options() -> dict:
    """歷史訂單頁可選人員。

    workers：只要是打手或陪玩就顯示，同一人只顯示一次。
    customer_services：客服獨立顯示。
    """
    workers = {}
    customer_services = {}

    conn = sqlite3.connect(history_db_path())
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT
                discord_id,
                display_name,
                username,
                is_worker,
                is_companion,
                is_customer_service,
                is_active
            FROM web_staff_members
            WHERE COALESCE(is_active, 1) = 1
            ORDER BY display_name, username, discord_id
            """
        ).fetchall()

        for row in rows:
            discord_id = str(row["discord_id"] or "").strip()
            if not discord_id:
                continue

            name = (
                str(row["display_name"] or "").strip()
                or str(row["username"] or "").strip()
                or discord_id
            )

            is_customer_service = int(row["is_customer_service"] or 0) == 1
            is_worker = int(row["is_worker"] or 0) == 1
            is_companion = int(row["is_companion"] or 0) == 1

            if is_customer_service:
                customer_services[discord_id] = {
                    "id": discord_id,
                    "value": discord_id,
                    "name": name,
                    "role_type": "customer_service",
                }

            if is_worker or is_companion:
                workers[discord_id] = {
                    "id": discord_id,
                    "value": discord_id,
                    "name": name,
                    # 後端仍需要 role_type 時給 worker 當預設，不影響派單 embed 顯示。
                    "role_type": "worker",
                }

    finally:
        conn.close()

    return {
        "workers": sorted(workers.values(), key=lambda item: item["name"]),
        "customer_services": sorted(customer_services.values(), key=lambda item: item["name"]),
    }


def history_assignments_by_order(order_ids: list[int]) -> dict[int, list[dict]]:
    if not order_ids:
        return {}

    placeholders = ",".join("?" for _ in order_ids)
    result: dict[int, list[dict]] = {}

    conn = sqlite3.connect(history_db_path())
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            f"""
            SELECT
                id,
                order_id,
                worker_discord_id,
                worker_display_name,
                role_type,
                has_named_bonus,
                is_active
            FROM order_assignments
            WHERE order_id IN ({placeholders})
              AND is_active = 1
            ORDER BY id ASC
            """,
            order_ids,
        ).fetchall()

        for row in rows:
            order_id = int(row["order_id"])
            result.setdefault(order_id, []).append(
                {
                    "id": int(row["id"]),
                    "worker_discord_id": str(row["worker_discord_id"] or ""),
                    "worker_display_name": str(row["worker_display_name"] or row["worker_discord_id"] or ""),
                    "role_type": str(row["role_type"] or "worker"),
                    "has_named_bonus": bool(row["has_named_bonus"]),
                }
            )
    finally:
        conn.close()

    return result


def fetch_history_payouts(order_ids: list[int]) -> dict[int, list[dict]]:
    """分潤輸入用 person key，不用 payout id，因為保存時可能會重算刪掉重建。"""
    if not order_ids:
        return {}

    placeholders = ",".join("?" for _ in order_ids)
    result: dict[int, list[dict]] = {}

    conn = sqlite3.connect(history_db_path())
    conn.row_factory = sqlite3.Row

    try:
        worker_rows = conn.execute(
            f"""
            SELECT
                order_id,
                worker_discord_id AS person_id,
                worker_display_name AS person_name,
                final_payout AS amount,
                payout_status,
                paid_at
            FROM worker_payouts
            WHERE order_id IN ({placeholders})
            ORDER BY id ASC
            """,
            order_ids,
        ).fetchall()

        for row in worker_rows:
            order_id = int(row["order_id"])
            person_id = str(row["person_id"] or "").strip()

            if not person_id:
                continue

            result.setdefault(order_id, []).append(
                {
                    "kind": "worker",
                    "label": "護級 / 陪級",
                    "person_id": person_id,
                    "person_name": row["person_name"] or person_id,
                    "amount": int(row["amount"] or 0),
                    "payout_status": row["payout_status"],
                    "paid_at": row["paid_at"],
                    "input_name": f"manual_worker_{order_id}_{person_id}",
                    "original_name": f"original_worker_{order_id}_{person_id}",
                }
            )

        cs_rows = conn.execute(
            f"""
            SELECT
                order_id,
                customer_service_discord_id AS person_id,
                customer_service_display_name AS person_name,
                payout_amount AS amount,
                payout_status,
                paid_at
            FROM customer_service_payouts
            WHERE order_id IN ({placeholders})
            ORDER BY id ASC
            """,
            order_ids,
        ).fetchall()

        for row in cs_rows:
            order_id = int(row["order_id"])
            person_id = str(row["person_id"] or "").strip()

            if not person_id:
                continue

            result.setdefault(order_id, []).append(
                {
                    "kind": "customer_service",
                    "label": "客服",
                    "person_id": person_id,
                    "person_name": row["person_name"] or person_id,
                    "amount": int(row["amount"] or 0),
                    "payout_status": row["payout_status"],
                    "paid_at": row["paid_at"],
                    "input_name": f"manual_cs_{order_id}_{person_id}",
                    "original_name": f"original_cs_{order_id}_{person_id}",
                }
            )
    finally:
        conn.close()

    # 客服排上面
    for order_id, rows in result.items():
        rows.sort(key=lambda item: 0 if item["kind"] == "customer_service" else 1)

    return result









def fetch_history_closed_dates(order_ids: list[int]) -> dict[int, str]:
    """從 SQLite 直接抓 web_orders.closed_at；有值就回傳 YYYY-MM-DD。"""
    clean_ids = []
    for order_id in order_ids:
        try:
            order_id = int(order_id)
        except Exception:
            continue
        if order_id > 0:
            clean_ids.append(order_id)

    if not clean_ids:
        return {}

    conn = sqlite3.connect(history_db_path())
    conn.row_factory = sqlite3.Row

    try:
        columns = {
            str(row["name"])
            for row in conn.execute("PRAGMA table_info(web_orders)").fetchall()
        }

        if "closed_at" not in columns:
            return {}

        placeholders = ",".join("?" for _ in clean_ids)
        rows = conn.execute(
            f"""
            SELECT id, closed_at
            FROM web_orders
            WHERE id IN ({placeholders})
            """,
            clean_ids,
        ).fetchall()

        result = {}
        for row in rows:
            value = str(row["closed_at"] or "").strip()
            if value:
                result[int(row["id"])] = value[:10]

        return result
    finally:
        conn.close()


def build_customer_options_from_db():
    """從 web_orders 建立老闆下拉選項；同 Discord ID 自動合併名稱，選項只顯示名稱。"""
    by_key = {}

    conn = sqlite3.connect(history_db_path() if "history_db_path" in globals() else str(Path.cwd() / "web_dashboard.db"))
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            """
            SELECT
                customer_discord_id,
                customer_display_name
            FROM web_orders
            WHERE COALESCE(customer_discord_id, '') <> ''
               OR COALESCE(customer_display_name, '') <> ''
            ORDER BY customer_display_name COLLATE NOCASE, customer_discord_id
            """
        ).fetchall()
    finally:
        conn.close()

    name_by_id = {}

    for row in rows:
        customer_id = str(row["customer_discord_id"] or "").strip()
        customer_name = str(row["customer_display_name"] or "").strip()

        if customer_id and customer_name and customer_name != customer_id:
            name_by_id[customer_id] = customer_name

    for row in rows:
        customer_id = str(row["customer_discord_id"] or "").strip()
        customer_name = str(row["customer_display_name"] or "").strip()

        key = customer_id or customer_name

        if not key:
            continue

        label = name_by_id.get(customer_id) or customer_name or customer_id or "未知老闆"

        if key not in by_key:
            by_key[key] = {
                "value": key,
                "label": label,
                "customer_id": customer_id,
            }

    options = list(by_key.values())
    options.sort(key=lambda item: str(item["label"] or ""))

    return options


def filter_orders_by_customer(orders, customer_key: str | None):
    customer_key = str(customer_key or "").strip()

    if not customer_key:
        return orders

    return [
        order
        for order in orders
        if str(getattr(order, "customer_discord_id", "") or "").strip() == customer_key
        or str(getattr(order, "customer_display_name", "") or "").strip() == customer_key
    ]





def ensure_manual_payout_override_table() -> None:
    conn = sqlite3.connect(history_db_path())

    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS manual_payout_overrides (
                order_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                person_id TEXT NOT NULL,
                amount INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (order_id, kind, person_id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def history_manual_payout_overrides(order_ids: list[int]) -> dict[str, int]:
    """只回傳後台手動指定的分潤；沒有紀錄就代表走公式。"""
    if not order_ids:
        return {}

    ensure_manual_payout_override_table()

    placeholders = ",".join("?" for _ in order_ids)
    overrides: dict[str, int] = {}

    conn = sqlite3.connect(history_db_path())
    conn.row_factory = sqlite3.Row

    try:
        rows = conn.execute(
            f"""
            SELECT order_id, kind, person_id, amount
            FROM manual_payout_overrides
            WHERE order_id IN ({placeholders})
              AND amount > 0
            """,
            order_ids,
        ).fetchall()

        for row in rows:
            key = f"{row['kind']}:{int(row['order_id'])}:{str(row['person_id'])}"
            overrides[key] = int(row["amount"] or 0)
    finally:
        conn.close()

    return overrides


def snapshot_payout_status(order_ids: list[int]) -> dict[tuple[str, int, str], tuple[str, str | None]]:
    if not order_ids:
        return {}

    placeholders = ",".join("?" for _ in order_ids)
    snapshot = {}

    conn = sqlite3.connect(history_db_path())
    conn.row_factory = sqlite3.Row

    try:
        for row in conn.execute(
            f"""
            SELECT order_id, worker_discord_id AS person_id, payout_status, paid_at
            FROM worker_payouts
            WHERE order_id IN ({placeholders})
            """,
            order_ids,
        ).fetchall():
            snapshot[("worker", int(row["order_id"]), str(row["person_id"]))] = (
                row["payout_status"],
                row["paid_at"],
            )

        for row in conn.execute(
            f"""
            SELECT order_id, customer_service_discord_id AS person_id, payout_status, paid_at
            FROM customer_service_payouts
            WHERE order_id IN ({placeholders})
            """,
            order_ids,
        ).fetchall():
            snapshot[("customer_service", int(row["order_id"]), str(row["person_id"]))] = (
                row["payout_status"],
                row["paid_at"],
            )
    finally:
        conn.close()

    return snapshot


def restore_payout_status(snapshot: dict[tuple[str, int, str], tuple[str, str | None]]) -> None:
    if not snapshot:
        return

    conn = sqlite3.connect(history_db_path())

    try:
        for (kind, order_id, person_id), (status, paid_at) in snapshot.items():
            if kind == "worker":
                conn.execute(
                    """
                    UPDATE worker_payouts
                    SET payout_status = ?, paid_at = ?
                    WHERE order_id = ? AND worker_discord_id = ?
                    """,
                    (status, paid_at, order_id, person_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE customer_service_payouts
                    SET payout_status = ?, paid_at = ?
                    WHERE order_id = ? AND customer_service_discord_id = ?
                    """,
                    (status, paid_at, order_id, person_id),
                )

        conn.commit()
    finally:
        conn.close()


def recalculate_history_orders(order_ids: list[int]) -> None:
    """歷史訂單保存後安全重算已結單分潤；不直接刪除分潤表。"""
    clean_order_ids = []

    for order_id in order_ids:
        try:
            order_id = int(order_id)
        except Exception:
            continue

        if order_id > 0:
            clean_order_ids.append(order_id)

    if not clean_order_ids:
        return

    try:
        from shared.db import SessionLocal
        from shared.models import WebOrder
        from web.app.services.order_service import recalculate_order_payouts

        db = SessionLocal()

        try:
            for order_id in clean_order_ids:
                order = db.get(WebOrder, order_id)

                if order is None:
                    continue

                if str(order.status) == "closed":
                    recalculate_order_payouts(db, order_id)

            db.commit()
        finally:
            db.close()
    except Exception as exc:
        print(f"[order-history] recalculate history orders failed: {exc}")


def apply_manual_payout_edits(form, order_ids: list[int]) -> None:
    """
    歷史訂單分潤規則：
    - 空白 / 0：刪除手動覆蓋，強制重建公式分潤
    - 非 0：寫入手動覆蓋，最後實拿就是這個數字
    """
    ensure_manual_payout_override_table()

    clean_order_ids = [int(order_id) for order_id in order_ids if int(order_id) > 0]

    if not clean_order_ids:
        return

    # 先記住已發放狀態，避免重建分潤後變回未支付。
    status_snapshot = snapshot_payout_status(clean_order_ids)

    conn = sqlite3.connect(history_db_path())

    try:
        # 先更新 manual_payout_overrides。
        for key, value in form.multi_items():
            if key.startswith("manual_worker_"):
                raw = key.replace("manual_worker_", "", 1)

                if "_" not in raw:
                    continue

                order_id_text, person_id = raw.split("_", 1)
                order_id = history_to_int(order_id_text)
                person_id = str(person_id or "").strip()
                amount = history_to_int(value)

                if order_id <= 0 or not person_id:
                    continue

                if amount <= 0:
                    conn.execute(
                        """
                        DELETE FROM manual_payout_overrides
                        WHERE order_id = ? AND kind = 'worker' AND person_id = ?
                        """,
                        (order_id, person_id),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO manual_payout_overrides (order_id, kind, person_id, amount, updated_at)
                        VALUES (?, 'worker', ?, ?, datetime('now'))
                        ON CONFLICT(order_id, kind, person_id)
                        DO UPDATE SET amount = excluded.amount, updated_at = datetime('now')
                        """,
                        (order_id, person_id, amount),
                    )

            elif key.startswith("manual_cs_"):
                raw = key.replace("manual_cs_", "", 1)

                if "_" not in raw:
                    continue

                order_id_text, person_id = raw.split("_", 1)
                order_id = history_to_int(order_id_text)
                person_id = str(person_id or "").strip()
                amount = history_to_int(value)

                if order_id <= 0 or not person_id:
                    continue

                if amount <= 0:
                    conn.execute(
                        """
                        DELETE FROM manual_payout_overrides
                        WHERE order_id = ? AND kind = 'customer_service' AND person_id = ?
                        """,
                        (order_id, person_id),
                    )
                else:
                    conn.execute(
                        """
                        INSERT INTO manual_payout_overrides (order_id, kind, person_id, amount, updated_at)
                        VALUES (?, 'customer_service', ?, ?, datetime('now'))
                        ON CONFLICT(order_id, kind, person_id)
                        DO UPDATE SET amount = excluded.amount, updated_at = datetime('now')
                        """,
                        (order_id, person_id, amount),
                    )

        conn.commit()

        # 已停用：不要在歷史訂單保存時直接刪除分潤 rows。
        conn.commit()
    finally:
        conn.close()

    # 刪完舊分潤後重新跑公式。
    recalculate_history_orders(clean_order_ids)

    # 回復已發放狀態。
    
    # 客服選「無」或測試客服時，不計客服分潤
    conn = sqlite3.connect(history_db_path())
    try:
        for order_id in order_ids:
            cs_id = str(form.get(f"customer_service_{order_id}") or "").strip()

            if not cs_id or cs_id == "demo_customer_service":
                conn.execute(
                    """
                    DELETE FROM customer_service_payouts
                    WHERE order_id = ?
                    """,
                    (order_id,),
                )
        conn.commit()
    finally:
        conn.close()

    restore_payout_status(status_snapshot)

    # 最後再套用目前仍存在的手動覆蓋。
    overrides = history_manual_payout_overrides(clean_order_ids)
    conn = sqlite3.connect(history_db_path())

    try:
        for key, amount in overrides.items():
            kind, order_id_text, person_id = key.split(":", 2)
            order_id = history_to_int(order_id_text)

            if order_id <= 0 or amount <= 0 or not person_id:
                continue

            if kind == "worker":
                conn.execute(
                    """
                    UPDATE worker_payouts
                    SET
                        gross_share = ?,
                        base_payout = ?,
                        named_bonus_amount = 0,
                        final_payout = ?
                    WHERE order_id = ? AND worker_discord_id = ?
                    """,
                    (amount, amount, amount, order_id, person_id),
                )
            else:
                conn.execute(
                    """
                    UPDATE customer_service_payouts
                    SET payout_amount = ?
                    WHERE order_id = ? AND customer_service_discord_id = ?
                    """,
                    (amount, order_id, person_id),
                )

        conn.commit()
    finally:
        conn.close()

    print(f"[order-history] rebuilt payouts for orders={clean_order_ids}, overrides={len(overrides)}")


def build_customer_groups(orders):
    """依老闆 Discord ID 分組；同 ID 有名稱就補給只有 ID 的舊單。"""
    name_by_customer_id = {}

    for order in orders:
        customer_id = str(getattr(order, "customer_discord_id", "") or "").strip()
        customer_name = str(getattr(order, "customer_display_name", "") or "").strip()

        if customer_id and customer_name and customer_name != customer_id:
            name_by_customer_id[customer_id] = customer_name

    groups_by_key = {}

    for order in orders:
        customer_id = str(getattr(order, "customer_discord_id", "") or "").strip()
        raw_name = str(getattr(order, "customer_display_name", "") or "").strip()

        key = customer_id or raw_name or "unknown"
        display_name = raw_name or name_by_customer_id.get(customer_id) or customer_id or "未知老闆"

        if customer_id and customer_id in name_by_customer_id:
            display_name = name_by_customer_id[customer_id]

        if key not in groups_by_key:
            groups_by_key[key] = {
                "customer_id": customer_id,
                "customer_name": display_name,
                "orders": [],
                "order_count": 0,
                "total_amount": 0,
            }

        group = groups_by_key[key]
        group["orders"].append(order)
        group["order_count"] += 1
        group["total_amount"] += int(getattr(order, "amount", 0) or 0)

        if group["customer_name"] == group["customer_id"] and display_name:
            group["customer_name"] = display_name

    groups = list(groups_by_key.values())
    groups.sort(key=lambda group: (str(group["customer_name"] or ""), str(group["customer_id"] or "")))
    return groups


@router.get("/admin/orders/history")
async def admin_order_history(
    request: Request,
    status: str = "all",
    keyword: str | None = None,
    message: str | None = None,
    error: str | None = None,
    customer: str | None = "",
    page: int = 1,
):
    month_filter = str(request.query_params.get("month") or "").strip()
    user = get_current_user(request)

    if not user:
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "請先登入",
                "message": "請先使用 Discord 登入。",
                "user": None,
            },
            status_code=401,
        )

    if not user.get("is_admin"):
        return templates.TemplateResponse(
            request=request,
            name="no_access.html",
            context={
                "title": "沒有權限",
                "message": "你沒有總控後台權限。",
                "user": user,
            },
            status_code=403,
        )

    db = SessionLocal()

    try:
        all_orders = list_history_orders(status_filter=status, keyword=keyword)
        closed_dates_by_order_id = fetch_history_closed_dates([int(order.id) for order in all_orders])

        if month_filter:
            all_orders = [
                order for order in all_orders
                if str(closed_dates_by_order_id.get(int(order.id), "")).replace("/", "-").startswith(month_filter)
            ]
            closed_dates_by_order_id = {
                int(order.id): closed_dates_by_order_id.get(int(order.id), "")
                for order in all_orders
            }

        # 有結單日期就優先照結單日期新到舊；沒有才用 updated_at / created_at / id。
        all_orders.sort(
            key=lambda order: (
                closed_dates_by_order_id.get(int(order.id), ""),
                str(getattr(order, "updated_at", "") or ""),
                str(getattr(order, "created_at", "") or ""),
                int(getattr(order, "id", 0) or 0),
            ),
            reverse=True,
        )

        # 歷史訂單改成卷宗列表，不再依老闆分組。
        per_page = 10
        page = max(1, int(page or 1))
        total_orders = len(all_orders)
        total_pages = max(1, (total_orders + per_page - 1) // per_page)
        page = min(page, total_pages)
        offset = (page - 1) * per_page
        orders = all_orders[offset:offset + per_page]

        customer = ""
        customer_options = []
        customer_service_members = list_customer_service_members(db)
        worker_members = list_worker_members(db)

        history_closed_count = sum(1 for order in all_orders if str(order.status) == OrderStatus.CLOSED.value)
        history_stored_count = sum(1 for order in all_orders if str(order.status) == OrderStatus.STORED.value)
        history_active_count = sum(1 for order in all_orders if str(order.status) == OrderStatus.ACTIVE.value)
        history_total_amount = sum(int(getattr(order, "amount", 0) or 0) for order in all_orders)

        order_ids = [order.id for order in orders]
        customer_service_payouts_by_order: dict[int, list[CustomerServicePayout]] = {}

        if order_ids:
            service_payouts = list(
                db.scalars(
                    select(CustomerServicePayout)
                    .where(CustomerServicePayout.order_id.in_(order_ids))
                    .order_by(CustomerServicePayout.id.asc())
                ).all()
            )

            for payout in service_payouts:
                customer_service_payouts_by_order.setdefault(payout.order_id, []).append(payout)
    finally:
        db.close()

    return templates.TemplateResponse(
        request=request,
        name="order_history.html",
        context={
            "title": "歷史訂單",
            "user": user,
            "orders": orders,
            "customer_groups": [],
            "customer_options": customer_options,
            "customer": customer or "",
            "page": page,
            "per_page": per_page,
            "total_orders": total_orders,
            "total_pages": total_pages,
            "history_closed_count": history_closed_count,
            "history_stored_count": history_stored_count,
            "history_active_count": history_active_count,
            "history_total_amount": history_total_amount,
            "closed_dates_by_order_id": closed_dates_by_order_id,
            "has_prev_page": page > 1,
            "has_next_page": page < total_pages,
            "prev_page": max(1, page - 1),
            "next_page": min(total_pages, page + 1),
            "history_staff_options": history_staff_options(),
            "history_effective_closed_date": history_effective_closed_date,
            "history_closed_date_input_value": history_closed_date_input_value,
            "assignments_by_order_id": history_assignments_by_order([int(order.id) for order in orders]),
            "payouts_by_order_id": fetch_history_payouts([int(order.id) for order in orders]),
            "manual_payout_overrides": history_manual_payout_overrides([int(order.id) for order in orders]),
            "payouts_by_order_id": fetch_history_payouts([int(order.id) for order in orders]),
            "current_status": status,
            "month_filter": month_filter,
            "month_options": list_history_month_options(),
            "keyword": keyword or "",
            "message": message,
            "error": error,
            "customer_service_members": customer_service_members,
            "worker_members": worker_members,
            "customer_service_payouts_by_order": customer_service_payouts_by_order,
            "paid_status": PayoutStatus.PAID.value,
            "unpaid_status": PayoutStatus.UNPAID.value,
            "status_options": [
                ("all", "全部"),
                (OrderStatus.CLOSED.value, "已結單"),
                (OrderStatus.STORED.value, "存單"),
                (OrderStatus.CANCELLED.value, "取消"),
            ],
        },
    )


@router.post("/admin/orders/history/{order_id}/customer-service")
async def history_set_customer_service(
    request: Request,
    order_id: int,
    customer_service_discord_id: str = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="已更新歷史訂單對接客服，分潤已重新計算。")


@router.post("/admin/orders/history/{order_id}/add-worker")
async def history_add_worker(
    request: Request,
    order_id: int,
    worker_discord_id: str = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="已新增歷史訂單打手/陪玩，分潤已重新計算。")


@router.post("/admin/orders/history/assignments/{assignment_id}/named-bonus")
async def history_update_named_bonus(
    request: Request,
    assignment_id: int,
    enabled: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="歷史訂單掛名加成已更新。")


@router.post("/admin/orders/history/assignments/{assignment_id}/remove")
async def history_remove_worker(
    request: Request,
    assignment_id: int,
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="已移除歷史訂單打手/陪玩，分潤已重新計算。")


@router.post("/admin/orders/history/{order_id}/manual-payout")
async def history_manual_payout(
    request: Request,
    order_id: int,
    worker_discord_id: str = Form(...),
    worker_display_name: str | None = Form(default=None),
    manual_final_payout: int = Form(...),
    reason: str | None = Form(default=None),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="已手動更新歷史訂單分潤。")


@router.post("/admin/orders/history/worker-payouts/{payout_id}/status")
async def history_set_worker_payout_status(
    request: Request,
    payout_id: int,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

    db = SessionLocal()

    try:
        set_worker_payout_status(db, payout_id=payout_id, status=status, admin_user=user)
    except ValueError as e:
        db.rollback()
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="打手/陪玩分潤狀態已更新。")


@router.post("/admin/orders/history/customer-service-payouts/{payout_id}/status")
async def history_set_customer_service_payout_status(
    request: Request,
    payout_id: int,
    status: str = Form(...),
):
    user = require_admin_user(request)

    if not user:
        return redirect_to_history(error="你沒有總控後台權限，或登入狀態已過期。")

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
        return redirect_to_history(error=str(e))
    finally:
        db.close()

    return redirect_to_history(message="客服分潤狀態已更新。")


@router.post("/admin/orders/history/bulk-update")
async def bulk_update_order_history(request: Request):
    user = request.session.get("user")

    if not user or not user.get("is_admin"):
        return RedirectResponse(url="/login", status_code=303)

    form = await request.form()
    order_ids = [
        history_to_int(order_id)
        for order_id in form.getlist("order_id")
        if history_to_int(order_id) > 0
    ]

    if not order_ids:
        return RedirectResponse(url="/admin/orders/history", status_code=303)

    payout_status_snapshot = snapshot_payout_status(order_ids)

    staff_options = history_staff_options()
    worker_name_map = {item.get("value") or item["id"]: item["name"] for item in staff_options["workers"]}
    worker_role_map = {item.get("value") or item["id"]: item.get("role_type") or "worker" for item in staff_options["workers"]}
    cs_name_map = {item["id"]: item["name"] for item in staff_options["customer_services"]}

    conn = sqlite3.connect(history_db_path())

    try:
        for order_id in order_ids:
            customer_display_name = str(form.get(f"customer_display_name_{order_id}") or "").strip()
            customer_discord_id = str(form.get(f"customer_discord_id_{order_id}") or "").strip()
            category = str(form.get(f"category_{order_id}") or "").strip()
            item = str(form.get(f"item_{order_id}") or "").strip()
            amount = history_to_int(form.get(f"amount_{order_id}"), 0)
            status = history_safe_status(form.get(f"status_{order_id}"))
            submitted_closed_at = history_normalize_date(form.get(f"closed_date_{order_id}"))

            original_row = conn.execute(
                "SELECT closed_at FROM web_orders WHERE id = ?",
                (order_id,),
            ).fetchone()

            original_closed_at = history_normalize_date(original_row[0]) if original_row else ""
            should_update_closed_at = bool(
                submitted_closed_at and submitted_closed_at != original_closed_at
            )

            cs_id = str(form.get(f"customer_service_{order_id}") or "").strip()
            cs_name = cs_name_map.get(cs_id, "") if cs_id else ""

            conn.execute(
                """
                UPDATE web_orders
                SET
                    customer_display_name = ?,
                    customer_discord_id = ?,
                    customer_service_discord_id = ?,
                    customer_service_display_name = ?,
                    category = ?,
                    item = ?,
                    amount = ?,
                    status = ?,
                    closed_at = CASE WHEN ? THEN ? ELSE closed_at END,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    customer_display_name,
                    customer_discord_id,
                    cs_id,
                    cs_name,
                    category,
                    item,
                    amount,
                    status,
                    1 if should_update_closed_at else 0,
                    submitted_closed_at,
                    order_id,
                ),
            )

            # 現有接單人：可刪除或改人
            for assignment_id_text in form.getlist(f"assignment_id_{order_id}"):
                assignment_id = history_to_int(assignment_id_text)
                selected_worker_id = str(form.get(f"assignment_worker_{assignment_id}") or "").strip()

                selected_worker_id, parsed_role_type = history_parse_worker_option(selected_worker_id)
                delete_flag = str(form.get(f"delete_assignment_{assignment_id}") or "").strip() == "1"
                named_bonus = 1 if str(form.get(f"assignment_named_bonus_{assignment_id}") or "").strip() == "1" else 0

                if assignment_id <= 0:
                    continue

                if delete_flag or not selected_worker_id:
                    conn.execute(
                        """
                        UPDATE order_assignments
                        SET is_active = 0, removed_at = datetime('now')
                        WHERE id = ?
                        """,
                        (assignment_id,),
                    )
                    continue

                conn.execute(
                    """
                    UPDATE order_assignments
                    SET
                        worker_discord_id = ?,
                        worker_display_name = ?,
                        role_type = ?,
                        has_named_bonus = ?,
                        is_active = 1
                    WHERE id = ?
                    """,
                    (
                        selected_worker_id,
                        worker_name_map.get(selected_worker_id, selected_worker_id),
                        worker_role_map.get(selected_worker_id, "worker"),
                        named_bonus,
                        assignment_id,
                    ),
                )

            # 新增接單人，預留 3 格
            existing_active = {
                str(row[0])
                for row in conn.execute(
                    """
                    SELECT worker_discord_id
                    FROM order_assignments
                    WHERE order_id = ? AND is_active = 1
                    """,
                    (order_id,),
                ).fetchall()
            }

            for index in range(0, 3):
                raw_new_worker_id = str(form.get(f"new_worker_{order_id}_{index}") or "").strip()
                new_worker_id, parsed_role_type = history_parse_worker_option(raw_new_worker_id)
                new_named_bonus = 1 if str(form.get(f"new_worker_named_bonus_{order_id}_{index}") or "").strip() == "1" else 0

                if not new_worker_id or new_worker_id in existing_active:
                    continue

                worker_display_name = (
                    worker_name_map.get(raw_new_worker_id)
                    or worker_name_map.get(new_worker_id)
                    or new_worker_id
                )
                worker_role_type = (
                    parsed_role_type
                    or worker_role_map.get(raw_new_worker_id)
                    or worker_role_map.get(new_worker_id)
                    or "worker"
                )

                conn.execute(
                    """
                    INSERT INTO order_assignments (
                        order_id,
                        worker_discord_id,
                        worker_display_name,
                        role_type,
                        is_active,
                        has_named_bonus,
                        assigned_at
                    )
                    VALUES (?, ?, ?, ?, 1, ?, datetime('now'))
                    """,
                    (
                        order_id,
                        new_worker_id,
                        worker_display_name,
                        worker_role_type,
                        new_named_bonus,
                    ),
                )

                existing_active.add(new_worker_id)

        conn.commit()
    finally:
        conn.close()

    # 只對結單重新公式計算；active/stored 清掉分潤。
    try:
        from shared.db import SessionLocal
        from shared.models import WebOrder
        from web.app.services.order_service import recalculate_order_payouts

        db = SessionLocal()

        try:
            for order_id in order_ids:
                order = db.get(WebOrder, order_id)

                if order is None:
                    continue

                if str(order.status) == "closed":
                    recalculate_order_payouts(db, order_id)
                else:
                    conn = sqlite3.connect(history_db_path())

                    try:
                        conn.commit()
                    finally:
                        conn.close()

            db.commit()
        finally:
            db.close()
    except Exception as exc:
        print(f"[order-history] recalculate payouts failed: {exc}")

    restore_payout_status(payout_status_snapshot)
    apply_manual_payout_edits(form, order_ids)

    return RedirectResponse(url="/admin/orders/history", status_code=303)

    conn = sqlite3.connect(history_db_path())

    try:
        for order_id in order_ids:
            customer_display_name = str(form.get(f"customer_display_name_{order_id}") or "").strip()
            customer_discord_id = str(form.get(f"customer_discord_id_{order_id}") or "").strip()
            category = str(form.get(f"category_{order_id}") or "").strip()
            item = str(form.get(f"item_{order_id}") or "").strip()
            amount = history_to_int(form.get(f"amount_{order_id}"), 0)
            status = history_safe_status(form.get(f"status_{order_id}"))

            conn.execute(
                """
                UPDATE web_orders
                SET
                    customer_display_name = ?,
                    customer_discord_id = ?,
                    category = ?,
                    item = ?,
                    amount = ?,
                    status = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    customer_display_name,
                    customer_discord_id,
                    category,
                    item,
                    amount,
                    status,
                    order_id,
                ),
            )

        conn.commit()
    finally:
        conn.close()

    return RedirectResponse(url="/admin/orders/history", status_code=303)

