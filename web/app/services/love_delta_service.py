from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


LOVE_DELTA_RULES_VERSION = "love-delta-v1-2026-10-12"
LOVE_DELTA_RULE_KEYS = {
    "fun_mawan_galagame_basic": {
        "key": "basic",
        "label": "基礎",
        "price": 1688,
        "initial_affection": 30.0,
    },
    "fun_mawan_galagame_standard": {
        "key": "standard",
        "label": "標準",
        "price": 2688,
        "initial_affection": 0.0,
    },
    "fun_mawan_galagame_hard": {
        "key": "hard",
        "label": "困難",
        "price": 4688,
        "initial_affection": -30.0,
    },
    "fun_mawan_galagame_hell": {
        "key": "hell",
        "label": "地獄",
        "price": 6688,
        "initial_affection": -80.0,
    },
}
LOVE_DELTA_ALLOWED_STATUSES = {"active", "stored"}
LOVE_DELTA_VIEW_STATUSES = LOVE_DELTA_ALLOWED_STATUSES | {"closed"}
LOVE_DELTA_ITEM_HINT = "戀與三角洲"

EVENT_SCORES = {
    "item_gold": ("金色物資 / 紫卡", 3.0),
    "item_small_red": ("小紅 / 金卡", 8.0),
    "item_big_red": ("大紅 / 紅卡", 15.0),
    "item_heart_tear": ("心 / 淚", 30.0),
    "squad_wipe": ("女陪一打三滅隊", 10.0),
    "ban_1": ("觸發禁語 1", -2.0),
    "ban_2": ("觸發禁語 2", -2.0),
    "ban_3": ("觸發禁語 3", -2.0),
    "miss_suffix": ("忘記句末助詞", -2.0),
}
EXTRACTION_TIERS = {0: 0.0, 300: 4.0, 600: 8.0, 900: 12.0}


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[3] / "web_dashboard.db"


def _connect(db_file: str | Path | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(db_file), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _score(value: Any) -> float:
    try:
        return round(float(value or 0), 1)
    except (TypeError, ValueError):
        return 0.0


def _display_score(value: Any) -> int | float:
    number = _score(value)
    if number.is_integer():
        return int(number)
    return number


def _normalize_answer(value: Any) -> str:
    return "".join(str(value or "").strip().lower().split())


def ensure_love_delta_tables(db_file: str | Path | None = None) -> None:
    path = _db_path(db_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS love_delta_sessions (
                order_id INTEGER PRIMARY KEY,
                rule_key TEXT NOT NULL,
                rules_version TEXT NOT NULL,
                initial_affection REAL NOT NULL,
                affection REAL NOT NULL,
                theme_affection REAL NOT NULL,
                round_no INTEGER NOT NULL DEFAULT 1,
                round_positive REAL NOT NULL DEFAULT 0,
                started_at TEXT,
                completed_at TEXT,
                boss_hint_category TEXT,
                boss_hint_quality TEXT,
                boss_answer TEXT,
                boss_answer_locked INTEGER NOT NULL DEFAULT 0,
                companion_guess TEXT,
                companion_guess_locked INTEGER NOT NULL DEFAULT 0,
                ban_1 TEXT,
                ban_2 TEXT,
                ban_3 TEXT,
                bans_editable INTEGER NOT NULL DEFAULT 1,
                suffix TEXT,
                nickname TEXT,
                loadout_unlocked INTEGER NOT NULL DEFAULT 0,
                designated_round INTEGER,
                designated_agent TEXT,
                designated_weapon TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS love_delta_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER NOT NULL,
                round_no INTEGER NOT NULL,
                actor_discord_id TEXT NOT NULL,
                actor_display_name TEXT,
                actor_role TEXT NOT NULL,
                event_type TEXT NOT NULL,
                label TEXT NOT NULL,
                delta REAL NOT NULL DEFAULT 0,
                score_before REAL NOT NULL,
                score_after REAL NOT NULL,
                payload_json TEXT,
                is_undone INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_love_delta_events_order
            ON love_delta_events(order_id, id DESC);

            CREATE TABLE IF NOT EXISTS love_delta_companion_state (
                order_id INTEGER NOT NULL,
                companion_discord_id TEXT NOT NULL,
                first_rescue_scored INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(order_id, companion_discord_id)
            );
            """
        )
        conn.commit()


def _load_order(conn: sqlite3.Connection, order_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT * FROM web_orders WHERE id = ? LIMIT 1",
        (int(order_id),),
    ).fetchone()
    return dict(row) if row is not None else None


def _plan_from_order(order: dict[str, Any]) -> dict[str, Any] | None:
    rule_key = str(order.get("order_rule_key") or "").strip()
    plan = LOVE_DELTA_RULE_KEYS.get(rule_key)
    if plan is not None:
        return {**plan, "rule_key": rule_key}

    item = str(order.get("item") or "")
    category = str(order.get("category") or "")
    if LOVE_DELTA_ITEM_HINT not in item and LOVE_DELTA_ITEM_HINT not in category:
        return None

    label_text = f"{item} {category}"
    for key, data in LOVE_DELTA_RULE_KEYS.items():
        if data["label"] in label_text:
            return {**data, "rule_key": key}
    return None


def is_love_delta_order(order: dict[str, Any]) -> bool:
    return _plan_from_order(order) is not None


def _active_companions(conn: sqlite3.Connection, order_id: int) -> list[dict[str, str]]:
    table = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='order_assignments' LIMIT 1"
    ).fetchone()
    if table is None:
        return []

    rows = conn.execute(
        """
        SELECT worker_discord_id, worker_display_name, role_type
        FROM order_assignments
        WHERE order_id = ?
          AND COALESCE(is_active, 1) = 1
        ORDER BY id ASC
        """,
        (int(order_id),),
    ).fetchall()
    result: list[dict[str, str]] = []
    for row in rows:
        worker_id = str(row["worker_discord_id"] or "").strip()
        if not worker_id:
            continue
        result.append(
            {
                "id": worker_id,
                "name": str(row["worker_display_name"] or worker_id),
                "role_type": str(row["role_type"] or "").strip().lower(),
            }
        )
    return result


def _actor_role(
    order: dict[str, Any],
    companions: list[dict[str, str]],
    actor_discord_id: str | int,
) -> str | None:
    actor_id = str(actor_discord_id or "").strip()
    if not actor_id:
        return None
    if actor_id == str(order.get("customer_discord_id") or "").strip():
        return "boss"
    if any(item["id"] == actor_id for item in companions):
        return "companion"
    return None


def _ensure_session(
    conn: sqlite3.Connection,
    order: dict[str, Any],
    plan: dict[str, Any],
) -> sqlite3.Row:
    order_id = int(order["id"])
    row = conn.execute(
        "SELECT * FROM love_delta_sessions WHERE order_id = ? LIMIT 1",
        (order_id,),
    ).fetchone()
    if row is not None:
        return row

    now = _now_iso()
    initial = float(plan["initial_affection"])
    conn.execute(
        """
        INSERT INTO love_delta_sessions (
            order_id, rule_key, rules_version,
            initial_affection, affection, theme_affection,
            round_no, round_positive,
            bans_editable, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, 1, 0, 1, ?, ?)
        """,
        (order_id, str(plan["rule_key"]), LOVE_DELTA_RULES_VERSION, initial, initial, initial, now, now),
    )
    row = conn.execute(
        "SELECT * FROM love_delta_sessions WHERE order_id = ? LIMIT 1",
        (order_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError("戀與三角洲進度初始化失敗。")
    return row


def _recent_events(conn: sqlite3.Connection, order_id: int, limit: int = 12) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT id, round_no, actor_display_name, actor_discord_id, actor_role,
               event_type, label, delta, score_before, score_after, payload_json,
               is_undone, created_at
        FROM love_delta_events
        WHERE order_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (int(order_id), max(1, min(int(limit), 50))),
    ).fetchall()
    result = []
    for row in rows:
        data = dict(row)
        try:
            payload = json.loads(str(data.get("payload_json") or "{}"))
        except (TypeError, ValueError):
            payload = {}
        result.append(
            {
                "id": int(data["id"]),
                "round_no": int(data["round_no"]),
                "actor_name": str(data.get("actor_display_name") or data.get("actor_discord_id") or ""),
                "actor_role": str(data.get("actor_role") or ""),
                "event_type": str(data.get("event_type") or ""),
                "label": str(data.get("label") or ""),
                "delta": _display_score(data.get("delta")),
                "score_before": _display_score(data.get("score_before")),
                "score_after": _display_score(data.get("score_after")),
                "payload": payload,
                "is_undone": bool(data.get("is_undone")),
                "created_at": str(data.get("created_at") or ""),
            }
        )
    return result


def _rescue_state(
    conn: sqlite3.Connection,
    order_id: int,
    companions: list[dict[str, str]],
) -> dict[str, bool]:
    rows = conn.execute(
        """
        SELECT companion_discord_id, first_rescue_scored
        FROM love_delta_companion_state
        WHERE order_id = ?
        """,
        (int(order_id),),
    ).fetchall()
    state = {str(row["companion_discord_id"]): bool(row["first_rescue_scored"]) for row in rows}
    return {item["id"]: bool(state.get(item["id"], False)) for item in companions}


def _session_public(
    row: sqlite3.Row | dict[str, Any],
    *,
    actor_role: str,
    companions: list[dict[str, str]],
    rescue_state: dict[str, bool],
) -> dict[str, Any]:
    data = dict(row)
    round_no = int(data.get("round_no") or 1)
    designated_round = data.get("designated_round")
    try:
        designated_round = int(designated_round) if designated_round is not None else None
    except (TypeError, ValueError):
        designated_round = None

    boss_answer = str(data.get("boss_answer") or "")
    boss_answer_locked = bool(data.get("boss_answer_locked"))
    companion_guess = str(data.get("companion_guess") or "")
    companion_guess_locked = bool(data.get("companion_guess_locked"))

    current_designation = None
    if designated_round == round_no:
        current_designation = {
            "round_no": round_no,
            "agent": str(data.get("designated_agent") or ""),
            "weapon": str(data.get("designated_weapon") or ""),
        }
    next_designation = None
    if designated_round == round_no + 1:
        next_designation = {
            "round_no": designated_round,
            "agent": str(data.get("designated_agent") or ""),
            "weapon": str(data.get("designated_weapon") or ""),
        }

    state = {
        "order_id": int(data.get("order_id") or 0),
        "rules_version": str(data.get("rules_version") or LOVE_DELTA_RULES_VERSION),
        "initial_affection": _display_score(data.get("initial_affection")),
        "affection": _display_score(data.get("affection")),
        "theme_affection": _display_score(data.get("theme_affection")),
        "round_no": round_no,
        "round_positive": _display_score(data.get("round_positive")),
        "started": bool(str(data.get("started_at") or "").strip()),
        "started_at": str(data.get("started_at") or ""),
        "completed": bool(str(data.get("completed_at") or "").strip()),
        "completed_at": str(data.get("completed_at") or ""),
        "hint_category": str(data.get("boss_hint_category") or ""),
        "hint_quality": str(data.get("boss_hint_quality") or ""),
        "boss_answer_locked": boss_answer_locked,
        "companion_guess_locked": companion_guess_locked,
        "bans": [str(data.get("ban_1") or ""), str(data.get("ban_2") or ""), str(data.get("ban_3") or "")],
        "bans_editable": bool(data.get("bans_editable")),
        "suffix": str(data.get("suffix") or ""),
        "nickname": str(data.get("nickname") or ""),
        "suffix_unlocked": _score(data.get("affection")) >= 30,
        "nickname_unlocked": _score(data.get("affection")) >= 60,
        "loadout_unlocked": bool(data.get("loadout_unlocked")),
        "current_designation": current_designation,
        "next_designation": next_designation,
        "companions": [
            {**item, "first_rescue_scored": bool(rescue_state.get(item["id"], False))}
            for item in companions
        ],
    }

    if actor_role == "boss":
        state["boss_answer"] = boss_answer
        state["companion_guess"] = companion_guess if companion_guess_locked else ""
    else:
        state["boss_answer"] = ""
        state["companion_guess"] = companion_guess

    return state


def get_love_delta_entry_info(
    customer_discord_id: str | int,
    order_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_love_delta_tables(db_file)
    with _connect(db_file) as conn:
        order = _load_order(conn, order_id)
        if order is None:
            raise LookupError("找不到這張訂單。")
        if str(order.get("customer_discord_id") or "").strip() != str(customer_discord_id or "").strip():
            raise LookupError("找不到這張訂單。")
        plan = _plan_from_order(order)
        if plan is None:
            raise ValueError("這張訂單不是戀與三角洲。")
        session_row = conn.execute(
            "SELECT started_at, completed_at FROM love_delta_sessions WHERE order_id = ? LIMIT 1",
            (int(order_id),),
        ).fetchone()

    status = str(order.get("status") or "").strip().lower()
    started = bool(session_row and str(session_row["started_at"] or "").strip())
    completed = bool(session_row and str(session_row["completed_at"] or "").strip())
    return {
        "eligible": True,
        "order_id": int(order_id),
        "order_no": str(order.get("bot_order_no") or f"WEB-{order_id}"),
        "status": status,
        "available": status in LOVE_DELTA_ALLOWED_STATUSES,
        "view_only": status == "closed" and started,
        "expired": status == "closed" and not started,
        "started": started,
        "completed": completed,
        "plan": plan,
        "href": f"/me/orders/{int(order_id)}/love-delta",
    }


def get_love_delta_context(
    actor_discord_id: str | int,
    order_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_love_delta_tables(db_file)
    with _connect(db_file) as conn:
        order = _load_order(conn, order_id)
        if order is None:
            raise LookupError("找不到這張訂單。")
        plan = _plan_from_order(order)
        if plan is None:
            raise ValueError("這張訂單不是戀與三角洲。")
        companions = _active_companions(conn, order_id)
        role = _actor_role(order, companions, actor_discord_id)
        if role is None:
            raise PermissionError("你不是這張訂單的參與者。")
        status = str(order.get("status") or "").strip().lower()
        if status not in LOVE_DELTA_VIEW_STATUSES:
            raise PermissionError("付款完成後才會開放攻略面板。")
        session = _ensure_session(conn, order, plan)
        rescue = _rescue_state(conn, order_id, companions)
        state = _session_public(session, actor_role=role, companions=companions, rescue_state=rescue)
        events = _recent_events(conn, order_id)

    return {
        "order": {
            "id": int(order["id"]),
            "order_no": str(order.get("bot_order_no") or f"WEB-{order_id}"),
            "item": str(order.get("item") or "戀與三角洲"),
            "status": status,
            "ticket_channel_id": str(order.get("ticket_channel_id") or ""),
        },
        "plan": plan,
        "viewer": {"id": str(actor_discord_id), "role": role},
        "state": state,
        "events": events,
        "read_only": status == "closed",
    }


def _mutation_context(
    conn: sqlite3.Connection,
    actor_discord_id: str | int,
    order_id: int,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, str]], str, sqlite3.Row]:
    order = _load_order(conn, order_id)
    if order is None:
        raise LookupError("找不到這張訂單。")
    plan = _plan_from_order(order)
    if plan is None:
        raise ValueError("這張訂單不是戀與三角洲。")
    companions = _active_companions(conn, order_id)
    role = _actor_role(order, companions, actor_discord_id)
    if role is None:
        raise PermissionError("你不是這張訂單的參與者。")
    status = str(order.get("status") or "").strip().lower()
    if status not in LOVE_DELTA_ALLOWED_STATUSES:
        raise PermissionError("這張攻略目前不能操作。")
    session = _ensure_session(conn, order, plan)
    return order, plan, companions, role, session


def _actor_name(order: dict[str, Any], companions: list[dict[str, str]], actor_id: str) -> str:
    if actor_id == str(order.get("customer_discord_id") or "").strip():
        return str(order.get("customer_display_name") or actor_id)
    for item in companions:
        if item["id"] == actor_id:
            return item["name"]
    return actor_id


def _insert_event(
    conn: sqlite3.Connection,
    *,
    order_id: int,
    round_no: int,
    actor_id: str,
    actor_name: str,
    actor_role: str,
    event_type: str,
    label: str,
    delta: float,
    before: float,
    after: float,
    payload: dict[str, Any] | None = None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO love_delta_events (
            order_id, round_no, actor_discord_id, actor_display_name,
            actor_role, event_type, label, delta, score_before, score_after,
            payload_json, is_undone, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        """,
        (
            int(order_id), int(round_no), actor_id, actor_name, actor_role, event_type,
            label, float(delta), float(before), float(after),
            json.dumps(payload or {}, ensure_ascii=False, separators=(",", ":")), _now_iso(),
        ),
    )
    return int(cursor.lastrowid)


def _assert_started(session: sqlite3.Row | dict[str, Any]) -> None:
    if not str(dict(session).get("started_at") or "").strip():
        raise PermissionError("請先開始攻略。")


def _assert_not_completed(session: sqlite3.Row | dict[str, Any]) -> None:
    if str(dict(session).get("completed_at") or "").strip():
        raise PermissionError("好感度已滿，這張攻略已完成。")


def start_love_delta(
    actor_discord_id: str | int,
    order_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_love_delta_tables(db_file)
    actor_id = str(actor_discord_id or "").strip()
    with _connect(db_file) as conn:
        order, plan, companions, role, session = _mutation_context(conn, actor_id, order_id)
        if role != "boss":
            raise PermissionError("攻略要由老闆開始。")
        if not str(session["started_at"] or "").strip():
            now = _now_iso()
            conn.execute(
                "UPDATE love_delta_sessions SET started_at = ?, updated_at = ? WHERE order_id = ?",
                (now, now, int(order_id)),
            )
            conn.commit()
    return get_love_delta_context(actor_id, order_id, db_file=db_file)


def apply_love_delta_event(
    actor_discord_id: str | int,
    order_id: int,
    event_type: str,
    *,
    target_companion_id: str | None = None,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_love_delta_tables(db_file)
    actor_id = str(actor_discord_id or "").strip()
    event_type = str(event_type or "").strip()

    with _connect(db_file) as conn:
        conn.execute("BEGIN IMMEDIATE")
        order, _plan, companions, role, session = _mutation_context(conn, actor_id, order_id)
        _assert_started(session)
        _assert_not_completed(session)
        data = dict(session)
        before = _score(data.get("affection"))
        round_no = int(data.get("round_no") or 1)
        round_positive = _score(data.get("round_positive"))
        actor_name = _actor_name(order, companions, actor_id)
        payload: dict[str, Any] = {}

        if event_type == "first_rescue":
            target_id = actor_id if role == "companion" else str(target_companion_id or "").strip()
            target = next((item for item in companions if item["id"] == target_id), None)
            if target is None:
                raise ValueError("請選擇實際完成救援的女陪。")
            rescue_row = conn.execute(
                """
                SELECT first_rescue_scored FROM love_delta_companion_state
                WHERE order_id = ? AND companion_discord_id = ? LIMIT 1
                """,
                (int(order_id), target_id),
            ).fetchone()
            if rescue_row is not None and bool(rescue_row["first_rescue_scored"]):
                raise ValueError(f"{target['name']} 的首次救援分數已計算。")
            label, delta = f"{target['name']} 第一次救起老闆", 5.0
            now = _now_iso()
            conn.execute(
                """
                INSERT INTO love_delta_companion_state (
                    order_id, companion_discord_id, first_rescue_scored, updated_at
                ) VALUES (?, ?, 1, ?)
                ON CONFLICT(order_id, companion_discord_id)
                DO UPDATE SET first_rescue_scored = 1, updated_at = excluded.updated_at
                """,
                (int(order_id), target_id, now),
            )
            payload["target_companion_id"] = target_id
            payload["target_companion_name"] = target["name"]
        elif event_type == "four_same":
            label, delta = "四個同款小金 / 紅", 0.0
            conn.execute(
                "UPDATE love_delta_sessions SET loadout_unlocked = 1, updated_at = ? WHERE order_id = ?",
                (_now_iso(), int(order_id)),
            )
        else:
            spec = EVENT_SCORES.get(event_type)
            if spec is None:
                raise ValueError("未知的攻略事件。")
            label, delta = spec
            if event_type.startswith("ban_"):
                index = int(event_type.split("_", 1)[1])
                ban_text = str(data.get(f"ban_{index}") or "").strip()
                if not ban_text:
                    raise ValueError("這個禁語尚未設定。")
                label = f"講到禁語「{ban_text}」"
            if event_type == "miss_suffix":
                suffix = str(data.get("suffix") or "").strip()
                if before < 30 or not suffix:
                    raise ValueError("句末助詞尚未解鎖或設定。")
                label = f"忘記句末助詞「{suffix}」"

        after = round(min(100.0, before + float(delta)), 1)
        actual_delta = round(after - before, 1)
        if actual_delta > 0:
            round_positive = round(round_positive + actual_delta, 1)
        completed_at = str(data.get("completed_at") or "")
        if after >= 100 and not completed_at:
            completed_at = _now_iso()

        conn.execute(
            """
            UPDATE love_delta_sessions
            SET affection = ?, round_positive = ?, completed_at = ?, updated_at = ?
            WHERE order_id = ?
            """,
            (after, round_positive, completed_at or None, _now_iso(), int(order_id)),
        )
        _insert_event(
            conn, order_id=order_id, round_no=round_no, actor_id=actor_id,
            actor_name=actor_name, actor_role=role, event_type=event_type, label=label,
            delta=actual_delta, before=before, after=after, payload=payload,
        )
        conn.commit()

    return get_love_delta_context(actor_id, order_id, db_file=db_file)


def save_bans(
    actor_discord_id: str | int,
    order_id: int,
    bans: list[str],
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    actor_id = str(actor_discord_id or "").strip()
    clean = [str(value or "").strip() for value in bans[:3]]
    while len(clean) < 3:
        clean.append("")
    if any(not value for value in clean):
        raise ValueError("請設定三個不同禁語。")
    normalized = [_normalize_answer(value) for value in clean]
    if len(set(normalized)) != 3:
        raise ValueError("三個禁語不能重複。")

    with _connect(db_file) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _order, _plan, _companions, role, session = _mutation_context(conn, actor_id, order_id)
        _assert_started(session)
        _assert_not_completed(session)
        if role != "boss":
            raise PermissionError("只有老闆可以設定禁語。")
        data = dict(session)
        if not bool(data.get("bans_editable")):
            raise PermissionError("禁語要在成功撤離後才能更換。")
        reserved = {_normalize_answer(data.get("suffix")), _normalize_answer(data.get("nickname"))} - {""}
        if any(value in reserved for value in normalized):
            raise ValueError("禁語不能和句末助詞或特殊稱呼重複。")
        conn.execute(
            """
            UPDATE love_delta_sessions
            SET ban_1 = ?, ban_2 = ?, ban_3 = ?, bans_editable = 0, updated_at = ?
            WHERE order_id = ?
            """,
            (*clean, _now_iso(), int(order_id)),
        )
        conn.commit()
    return get_love_delta_context(actor_id, order_id, db_file=db_file)


def save_unlock_text(
    actor_discord_id: str | int,
    order_id: int,
    *,
    kind: str,
    value: str,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    actor_id = str(actor_discord_id or "").strip()
    value = str(value or "").strip()
    if not value:
        raise ValueError("內容不能空白。")
    if kind not in {"suffix", "nickname"}:
        raise ValueError("未知的解鎖設定。")

    with _connect(db_file) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _order, _plan, _companions, role, session = _mutation_context(conn, actor_id, order_id)
        _assert_started(session)
        _assert_not_completed(session)
        if role != "boss":
            raise PermissionError("只有老闆可以設定。")
        data = dict(session)
        affection = _score(data.get("affection"))
        threshold = 30 if kind == "suffix" else 60
        if affection < threshold:
            raise PermissionError(f"好感度達 {threshold} 才會解鎖。")
        reserved = {
            _normalize_answer(data.get("ban_1")),
            _normalize_answer(data.get("ban_2")),
            _normalize_answer(data.get("ban_3")),
        } - {""}
        other = data.get("nickname" if kind == "suffix" else "suffix")
        if _normalize_answer(other):
            reserved.add(_normalize_answer(other))
        if _normalize_answer(value) in reserved:
            raise ValueError("不能和禁語或另一個自訂稱呼重複。")
        conn.execute(
            f"UPDATE love_delta_sessions SET {kind} = ?, updated_at = ? WHERE order_id = ?",
            (value, _now_iso(), int(order_id)),
        )
        conn.commit()
    return get_love_delta_context(actor_id, order_id, db_file=db_file)


def save_boss_guess(
    actor_discord_id: str | int,
    order_id: int,
    *,
    answer: str,
    hint_category: str = "",
    hint_quality: str = "",
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    actor_id = str(actor_discord_id or "").strip()
    answer = str(answer or "").strip()
    if not answer:
        raise ValueError("請先填老闆最想要的物資。")
    with _connect(db_file) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _order, _plan, _companions, role, session = _mutation_context(conn, actor_id, order_id)
        _assert_started(session)
        _assert_not_completed(session)
        if role != "boss":
            raise PermissionError("只有老闆可以設定本局答案。")
        if bool(session["companion_guess_locked"]):
            raise PermissionError("女陪已鎖定答案，本局不能再更改老闆答案。")
        conn.execute(
            """
            UPDATE love_delta_sessions
            SET boss_hint_category = ?, boss_hint_quality = ?, boss_answer = ?,
                boss_answer_locked = 1, updated_at = ?
            WHERE order_id = ?
            """,
            (str(hint_category or "").strip(), str(hint_quality or "").strip(), answer, _now_iso(), int(order_id)),
        )
        conn.commit()
    return get_love_delta_context(actor_id, order_id, db_file=db_file)


def clear_boss_guess(
    actor_discord_id: str | int,
    order_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    actor_id = str(actor_discord_id or "").strip()
    with _connect(db_file) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _order, _plan, _companions, role, session = _mutation_context(conn, actor_id, order_id)
        _assert_started(session)
        if role != "boss":
            raise PermissionError("只有老闆可以清除本局答案。")
        if bool(session["companion_guess_locked"]):
            raise PermissionError("女陪已鎖定答案，本局不能再清除老闆答案。")
        conn.execute(
            """
            UPDATE love_delta_sessions
            SET boss_hint_category = NULL, boss_hint_quality = NULL, boss_answer = NULL,
                boss_answer_locked = 0, updated_at = ?
            WHERE order_id = ?
            """,
            (_now_iso(), int(order_id)),
        )
        conn.commit()
    return get_love_delta_context(actor_id, order_id, db_file=db_file)


def save_companion_guess(
    actor_discord_id: str | int,
    order_id: int,
    *,
    guess: str,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    actor_id = str(actor_discord_id or "").strip()
    guess = str(guess or "").strip()
    if not guess:
        raise ValueError("請先填女陪共同答案。")
    with _connect(db_file) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _order, _plan, _companions, role, session = _mutation_context(conn, actor_id, order_id)
        _assert_started(session)
        _assert_not_completed(session)
        if role != "companion":
            raise PermissionError("女陪共同答案要由本單女陪鎖定。")
        if not bool(session["boss_answer_locked"]):
            raise PermissionError("老闆尚未鎖定本局答案。")
        conn.execute(
            """
            UPDATE love_delta_sessions
            SET companion_guess = ?, companion_guess_locked = 1, updated_at = ?
            WHERE order_id = ?
            """,
            (guess, _now_iso(), int(order_id)),
        )
        conn.commit()
    return get_love_delta_context(actor_id, order_id, db_file=db_file)


def clear_companion_guess(
    actor_discord_id: str | int,
    order_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    actor_id = str(actor_discord_id or "").strip()
    with _connect(db_file) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _order, _plan, _companions, role, session = _mutation_context(conn, actor_id, order_id)
        _assert_started(session)
        if role != "companion":
            raise PermissionError("只有本單女陪可以清除共同答案。")
        conn.execute(
            """
            UPDATE love_delta_sessions
            SET companion_guess = NULL, companion_guess_locked = 0, updated_at = ?
            WHERE order_id = ?
            """,
            (_now_iso(), int(order_id)),
        )
        conn.commit()
    return get_love_delta_context(actor_id, order_id, db_file=db_file)


def save_next_loadout(
    actor_discord_id: str | int,
    order_id: int,
    *,
    agent: str,
    weapon: str,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    actor_id = str(actor_discord_id or "").strip()
    agent = str(agent or "").strip()
    weapon = str(weapon or "").strip()
    if not agent or not weapon:
        raise ValueError("請同時填寫下局指定幹員與槍械。")
    with _connect(db_file) as conn:
        conn.execute("BEGIN IMMEDIATE")
        _order, _plan, _companions, role, session = _mutation_context(conn, actor_id, order_id)
        _assert_started(session)
        _assert_not_completed(session)
        if role != "boss":
            raise PermissionError("只有老闆可以指定下局裝備。")
        if not bool(session["loadout_unlocked"]):
            raise PermissionError("本局尚未達成四個同款小金 / 紅。")
        designated_round = int(session["round_no"] or 1) + 1
        conn.execute(
            """
            UPDATE love_delta_sessions
            SET loadout_unlocked = 0, designated_round = ?, designated_agent = ?,
                designated_weapon = ?, updated_at = ?
            WHERE order_id = ?
            """,
            (designated_round, agent, weapon, _now_iso(), int(order_id)),
        )
        conn.commit()
    return get_love_delta_context(actor_id, order_id, db_file=db_file)


def settle_love_delta_round(
    actor_discord_id: str | int,
    order_id: int,
    *,
    expected_round: int,
    result: str,
    extraction_tier: int,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    actor_id = str(actor_discord_id or "").strip()
    result = str(result or "").strip().lower()
    if result not in {"success", "fail"}:
        raise ValueError("撤離結果不正確。")
    try:
        tier = int(extraction_tier)
    except (TypeError, ValueError) as exc:
        raise ValueError("撤離價值不正確。") from exc
    if tier not in EXTRACTION_TIERS:
        raise ValueError("撤離價值不正確。")

    with _connect(db_file) as conn:
        conn.execute("BEGIN IMMEDIATE")
        order, _plan, companions, role, session = _mutation_context(conn, actor_id, order_id)
        _assert_started(session)
        _assert_not_completed(session)
        data = dict(session)
        round_no = int(data.get("round_no") or 1)
        if int(expected_round) != round_no:
            raise ValueError("這局已被其他人結算，請重新整理。")

        before = _score(data.get("affection"))
        positive = _score(data.get("round_positive"))
        success_bonus = 5.0 if result == "success" else 0.0
        extraction_bonus = float(EXTRACTION_TIERS[tier])
        positive_for_multiplier = round(positive + success_bonus + extraction_bonus, 1)
        boss_answer = str(data.get("boss_answer") or "")
        companion_guess = str(data.get("companion_guess") or "")
        guess_hit = bool(
            data.get("boss_answer_locked")
            and data.get("companion_guess_locked")
            and _normalize_answer(boss_answer)
            and _normalize_answer(boss_answer) == _normalize_answer(companion_guess)
        )
        guess_bonus = round(positive_for_multiplier * 0.2, 1) if guess_hit else 0.0
        total_bonus = round(success_bonus + extraction_bonus + guess_bonus, 1)
        after = round(min(100.0, before + total_bonus), 1)
        actual_delta = round(after - before, 1)
        completed_at = _now_iso() if after >= 100 else None

        designated_round = data.get("designated_round")
        try:
            clear_current_designation = int(designated_round) == round_no
        except (TypeError, ValueError):
            clear_current_designation = False

        conn.execute(
            """
            UPDATE love_delta_sessions
            SET affection = ?,
                theme_affection = CASE WHEN ? = 'success' THEN ? ELSE theme_affection END,
                round_no = ?,
                round_positive = 0,
                completed_at = COALESCE(?, completed_at),
                boss_hint_category = NULL,
                boss_hint_quality = NULL,
                boss_answer = NULL,
                boss_answer_locked = 0,
                companion_guess = NULL,
                companion_guess_locked = 0,
                bans_editable = CASE WHEN ? = 'success' THEN 1 ELSE bans_editable END,
                designated_round = CASE WHEN ? THEN NULL ELSE designated_round END,
                designated_agent = CASE WHEN ? THEN NULL ELSE designated_agent END,
                designated_weapon = CASE WHEN ? THEN NULL ELSE designated_weapon END,
                updated_at = ?
            WHERE order_id = ?
            """,
            (
                after, result, after, round_no + 1, completed_at, result,
                1 if clear_current_designation else 0,
                1 if clear_current_designation else 0,
                1 if clear_current_designation else 0,
                _now_iso(), int(order_id),
            ),
        )
        actor_name = _actor_name(order, companions, actor_id)
        result_label = "成功撤離" if result == "success" else "撤離失敗"
        tier_label = "未達 300W" if tier == 0 else f"{tier}W+"
        label = f"{result_label}｜{tier_label}"
        if guess_hit:
            label += f"｜猜中「{boss_answer}」"
        _insert_event(
            conn, order_id=order_id, round_no=round_no, actor_id=actor_id,
            actor_name=actor_name, actor_role=role, event_type="round_settle", label=label,
            delta=actual_delta, before=before, after=after,
            payload={
                "result": result,
                "extraction_tier": tier,
                "success_bonus": _display_score(success_bonus),
                "extraction_bonus": _display_score(extraction_bonus),
                "positive_before_settle": _display_score(positive),
                "guess_hit": guess_hit,
                "boss_answer": boss_answer,
                "companion_guess": companion_guess,
                "guess_bonus": _display_score(guess_bonus),
            },
        )
        conn.commit()

    return get_love_delta_context(actor_id, order_id, db_file=db_file)


def undo_last_love_delta_event(
    actor_discord_id: str | int,
    order_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    actor_id = str(actor_discord_id or "").strip()
    with _connect(db_file) as conn:
        conn.execute("BEGIN IMMEDIATE")
        order, _plan, companions, role, session = _mutation_context(conn, actor_id, order_id)
        _assert_started(session)
        data = dict(session)
        current_round = int(data.get("round_no") or 1)
        event = conn.execute(
            """
            SELECT * FROM love_delta_events
            WHERE order_id = ? AND is_undone = 0 AND event_type != 'undo'
            ORDER BY id DESC LIMIT 1
            """,
            (int(order_id),),
        ).fetchone()
        if event is None:
            raise ValueError("目前沒有可撤銷的事件。")
        if str(event["event_type"] or "") == "round_settle" or int(event["round_no"] or 0) != current_round:
            raise ValueError("本局結算後不能撤銷上一局事件。")

        delta = _score(event["delta"])
        before_current = _score(data.get("affection"))
        after = round(before_current - delta, 1)
        round_positive = _score(data.get("round_positive"))
        if delta > 0:
            round_positive = max(0.0, round(round_positive - delta, 1))
        completed_at = str(data.get("completed_at") or "")
        if after < 100:
            completed_at = ""

        event_type = str(event["event_type"] or "")
        if event_type == "first_rescue":
            try:
                payload = json.loads(str(event["payload_json"] or "{}"))
            except (TypeError, ValueError):
                payload = {}
            target_id = str(payload.get("target_companion_id") or "").strip()
            if target_id:
                conn.execute(
                    """
                    UPDATE love_delta_companion_state
                    SET first_rescue_scored = 0, updated_at = ?
                    WHERE order_id = ? AND companion_discord_id = ?
                    """,
                    (_now_iso(), int(order_id), target_id),
                )
        elif event_type == "four_same":
            conn.execute(
                "UPDATE love_delta_sessions SET loadout_unlocked = 0 WHERE order_id = ?",
                (int(order_id),),
            )

        conn.execute(
            """
            UPDATE love_delta_sessions
            SET affection = ?, round_positive = ?, completed_at = ?, updated_at = ?
            WHERE order_id = ?
            """,
            (after, round_positive, completed_at or None, _now_iso(), int(order_id)),
        )
        conn.execute("UPDATE love_delta_events SET is_undone = 1 WHERE id = ?", (int(event["id"]),))
        actor_name = _actor_name(order, companions, actor_id)
        _insert_event(
            conn, order_id=order_id, round_no=current_round, actor_id=actor_id,
            actor_name=actor_name, actor_role=role, event_type="undo",
            label=f"撤銷：{str(event['label'] or '')}", delta=round(after - before_current, 1),
            before=before_current, after=after, payload={"undone_event_id": int(event["id"])},
        )
        conn.commit()

    return get_love_delta_context(actor_id, order_id, db_file=db_file)
