"""Independent order-bound affection game for new Our Love and Romance plans.

Legacy Love Delta sessions keep their previous rules and progress. New
sessions use the photo-approved 2026-11-18 scoring and do not mix state
between unrelated orders or permit actions before payment.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from services.order_rules import get_rule

AFFECTION_VERSION = "affection-20261118-v2"
PLANS = {
    "fun_our_love_start_75": ("our_love", "75 起始", 75, 2088),
    "fun_our_love_start_50": ("our_love", "50 起始", 50, 3088),
    "fun_our_love_start_0": ("our_love", "0 起始", 0, 3688),
    "fun_mawan_galagame_basic": ("romance", "30 起始", 30, None),
    "fun_mawan_galagame_standard": ("romance", "0 起始", 0, None),
    "fun_mawan_galagame_hard": ("romance", "-30 起始", -30, None),
    "fun_mawan_galagame_hell": ("romance", "-80 起始", -80, None),
}
EVENTS = {
    "our_love": {
        "escort_kill": ("護航擊殺 1 名幹員", 1),
        "small_red": ("摸出小紅（1～4 格）", 2),
        "big_red": ("大紅／金卡／紫卡", 5),
        "huge_red": ("大大紅／紅卡", 10),
        "heart_tear_breath": ("非洲之心／海洋之淚／復甦呼吸機", 35),
        "boss_kill": ("老闆擊殺 1 名幹員", -1),
    },
    "romance": {
        "small_gold": ("摸到小金", 2),
        "small_red": ("摸到小紅", 5),
        "big_red": ("摸到大紅", 10),
        "heart_tear": ("摸到心／淚", 30),
        "purple_card": ("紫卡", 5),
        "gold_card": ("金卡", 10),
        "red_card": ("紅卡", 15),
        "escort_kill": ("陪陪擊殺 1 人", 3),
        "boss_revived": ("老闆倒地被拉起一次", 2),
        "boss_kill": ("老闆擊殺 1 人", -5),
    },
}
OPEN_STATUSES = {"active", "stored"}
VIEW_STATUSES = OPEN_STATUSES | {"closed"}


def _connect(db_file=None):
    db = Path(db_file) if db_file is not None else Path(__file__).resolve().parents[3] / "web_dashboard.db"
    conn = sqlite3.connect(db, timeout=20)
    conn.row_factory = sqlite3.Row
    return conn


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_tables(db_file=None):
    with _connect(db_file) as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS affection_game_sessions (
            order_id INTEGER PRIMARY KEY,
            rule_key TEXT NOT NULL,
            rules_version TEXT NOT NULL,
            affection INTEGER NOT NULL,
            round_no INTEGER NOT NULL DEFAULT 1,
            started_at TEXT,
            completed_at TEXT,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS affection_game_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            order_id INTEGER NOT NULL,
            round_no INTEGER NOT NULL,
            actor_id TEXT NOT NULL,
            actor_name TEXT NOT NULL,
            event_key TEXT NOT NULL,
            label TEXT NOT NULL,
            delta INTEGER NOT NULL,
            before_score INTEGER NOT NULL,
            after_score INTEGER NOT NULL,
            undone INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_affection_game_events_order
          ON affection_game_events(order_id, id);
        """)


def legacy_romance_session_exists(order_id: int, *, db_file=None) -> bool:
    with _connect(db_file) as conn:
        try:
            row = conn.execute(
                "SELECT 1 FROM love_delta_sessions WHERE order_id=? LIMIT 1",
                (int(order_id),),
            ).fetchone()
        except sqlite3.OperationalError:
            row = None
    return bool(row)


def _lookup(conn, actor_id, order_id, *, game=None, require_paid=True, customer_only=False):
    row = conn.execute(
        "SELECT * FROM web_orders WHERE id=? LIMIT 1", (int(order_id),)
    ).fetchone()
    if row is None:
        raise LookupError("找不到這張訂單。")
    order = dict(row)
    rule_key = str(order.get("order_rule_key") or "")
    if rule_key not in PLANS:
        raise ValueError("這張訂單不屬於好感度活動。")
    kind, label, initial, guarantee = PLANS[rule_key]
    if game is not None and kind != game:
        raise ValueError("此訂單屬於另一種趣味單。")
    if kind == "romance" and legacy_romance_session_exists(order_id, db_file=_db_for_connection(conn)):
        raise ValueError("本單已有舊版戀與三角洲攻略紀錄，請使用原攻略頁面。")
    actor_id = str(actor_id or "").strip()
    boss_id = str(order.get("customer_discord_id") or "").strip()
    role = "boss" if actor_id and actor_id == boss_id else None
    if role is None and not customer_only:
        try:
            rows = conn.execute(
                """SELECT worker_discord_id FROM order_assignments
                   WHERE order_id=? AND COALESCE(is_active,1)=1""",
                (int(order_id),),
            ).fetchall()
        except sqlite3.OperationalError:
            rows = []
        if any(str(x["worker_discord_id"] or "") == actor_id for x in rows):
            role = "companion"
    if role is None:
        raise PermissionError("你不是這張訂單的參與者。")
    status = str(order.get("status") or "").lower().strip()
    if require_paid and status not in VIEW_STATUSES:
        raise PermissionError("訂單付款完成後才會開放專屬網站。")
    price = int(get_rule(rule_key).price)
    return order, {
        "key": rule_key,
        "game": kind,
        "label": label,
        "initial_affection": initial,
        "guarantee_w": guarantee,
        "price": price,
        "title": "我們的愛" if kind == "our_love" else "戀與三角洲",
    }, role, status


def _db_for_connection(conn):
    # PRAGMA returns the actual SQLite filename even when tests use temp DBs.
    return conn.execute("PRAGMA database_list").fetchone()["file"]


def _session(conn, order_id, plan, *, create=False):
    row = conn.execute("SELECT * FROM affection_game_sessions WHERE order_id=?",
                       (int(order_id),)).fetchone()
    if row is None and create:
        conn.execute(
            """INSERT INTO affection_game_sessions
               (order_id,rule_key,rules_version,affection,round_no,updated_at)
               VALUES (?,?,?,?,1,?)""",
            (int(order_id), plan["key"], AFFECTION_VERSION, plan["initial_affection"], _now()),
        )
        row = conn.execute("SELECT * FROM affection_game_sessions WHERE order_id=?",
                           (int(order_id),)).fetchone()
    return dict(row) if row else None


def _state(conn, order, plan, role, status):
    row = _session(conn, order["id"], plan, create=status in OPEN_STATUSES)
    records = conn.execute(
        """SELECT * FROM affection_game_events WHERE order_id=? ORDER BY id DESC LIMIT 24""",
        (int(order["id"]),),
    ).fetchall()
    return {
        "ok": True,
        "order": {"id": int(order["id"]),
                  "no": str(order.get("bot_order_no") or f"WEB-{order['id']}"),
                  "status": status},
        "plan": plan,
        "viewer": {"role": role},
        "state": {
            "affection": int(row["affection"]) if row else plan["initial_affection"],
            "round_no": int(row["round_no"]) if row else 1,
            "started": bool(row and row["started_at"]),
            "completed": bool(row and row["completed_at"]),
            "rules_version": AFFECTION_VERSION,
        },
        "events": [
            {"id": int(event["id"]), "label": str(event["label"]),
             "delta": int(event["delta"]), "actor": str(event["actor_name"]),
             "round": int(event["round_no"]), "undone": bool(event["undone"])}
            for event in records
        ],
        "rules": [{"key": key, "label": label, "points": delta}
                  for key, (label, delta) in EVENTS[plan["game"]].items()],
        "read_only": status == "closed",
    }


def get_context(actor_id, order_id, *, game=None, db_file=None):
    ensure_tables(db_file)
    with _connect(db_file) as conn:
        order, plan, role, status = _lookup(conn, actor_id, order_id, game=game)
        return _state(conn, order, plan, role, status)


def get_entry_info(customer_id, order_id, *, game=None, db_file=None):
    ensure_tables(db_file)
    with _connect(db_file) as conn:
        order, plan, role, status = _lookup(
            conn, customer_id, order_id, game=game, require_paid=False,
            customer_only=True,
        )
        row = _session(conn, order_id, plan, create=False)
    slug = "our-love" if plan["game"] == "our_love" else "romance-delta"
    return {
        "eligible": True, "order_id": int(order_id), "plan": plan,
        "available": status in OPEN_STATUSES,
        "view_only": status == "closed" and bool(row and row["started_at"]),
        "expired": status == "closed" and not bool(row and row["started_at"]),
        "started": bool(row and row["started_at"]),
        "completed": bool(row and row["completed_at"]),
        "href": f"/me/orders/{int(order_id)}/{slug}",
    }


def mutate(actor_id, order_id, operation, *, event_key=None,
           result=None, extra=False, expected_round=None, db_file=None):
    ensure_tables(db_file)
    with _connect(db_file) as conn:
        conn.execute("BEGIN IMMEDIATE")
        order, plan, role, status = _lookup(conn, actor_id, order_id)
        if role != "boss":
            raise PermissionError("只有下單老闆能操作好感度進度。")
        if status not in OPEN_STATUSES:
            raise PermissionError("這張訂單目前不允許更改攻略進度。")
        row = _session(conn, order_id, plan, create=True)
        if operation == "start":
            if not row["started_at"]:
                conn.execute(
                    "UPDATE affection_game_sessions SET started_at=?,updated_at=? WHERE order_id=?",
                    (_now(), _now(), int(order_id)),
                )
        else:
            if not row["started_at"]:
                raise PermissionError("請先開始攻略。")
            if row["completed_at"] and operation != "undo":
                raise PermissionError("好感度已滿，請勿再重複計分。")
            current_round = int(row["round_no"])
            if expected_round is not None and int(expected_round) != current_round:
                raise ValueError("本局已更新，請重新整理。")
            before = int(row["affection"])
            label = ""
            delta = 0
            if operation == "event":
                choice = EVENTS[plan["game"]].get(str(event_key or ""))
                if choice is None:
                    raise ValueError("未知的計分事件。")
                label, delta = choice
            elif operation == "settle":
                if result not in {"success", "fail"}:
                    raise ValueError("請選擇成功或失敗撤離。")
                if plan["game"] == "our_love":
                    if extra and result != "success":
                        raise ValueError("千萬撤離額外加分僅限成功撤離。")
                    delta = (5 if result == "success" else -10) + (3 if extra else 0)
                    label = "撤離成功" if result == "success" else "撤離失敗"
                    if extra:
                        label += "｜千萬撤離 +3"
                else:
                    if extra and result != "success":
                        raise ValueError("500W 撤離加分僅限成功撤離。")
                    delta = 3 if extra else 0
                    label = "撤離成功" if result == "success" else "撤離失敗"
                    if extra:
                        label += "｜500W 撤離 +3（不可疊加）"
            elif operation == "undo":
                event = conn.execute(
                    """SELECT * FROM affection_game_events
                       WHERE order_id=? AND undone=0 AND event_key!='undo'
                       ORDER BY id DESC LIMIT 1""",
                    (int(order_id),),
                ).fetchone()
                if event is None or event["event_key"] == "settle" or int(event["round_no"]) != current_round:
                    raise ValueError("此局沒有可撤銷的計分操作。")
                delta = -int(event["delta"])
                label = "撤銷：" + str(event["label"])
                conn.execute("UPDATE affection_game_events SET undone=1 WHERE id=?", (int(event["id"]),))
            else:
                raise ValueError("未知的操作。")
            after = min(100, max(-999, before + int(delta)))
            real_delta = after - before
            now = _now()
            next_round = current_round + (1 if operation == "settle" else 0)
            completed_at = now if after >= 100 else None
            conn.execute(
                """UPDATE affection_game_sessions
                   SET affection=?,round_no=?,completed_at=?,updated_at=?
                   WHERE order_id=?""",
                (after, next_round, completed_at, now, int(order_id)),
            )
            conn.execute(
                """INSERT INTO affection_game_events
                   (order_id,round_no,actor_id,actor_name,event_key,label,delta,
                    before_score,after_score,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                (int(order_id), current_round, str(actor_id),
                 str(order.get("customer_display_name") or actor_id),
                 "settle" if operation == "settle" else (
                     "undo" if operation == "undo" else str(event_key)),
                 label, real_delta, before, after, now),
            )
    return get_context(actor_id, order_id, db_file=db_file)
