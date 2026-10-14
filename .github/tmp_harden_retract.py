from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"anchor missing in {path}: {old[:120]!r}")
    if text.count(old) != 1:
        raise SystemExit(f"anchor not unique in {path}: {text.count(old)}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


# 1) Harden retract state gate and fail-safe the local ticket immediately after cancellation.
path = Path("services/self_service_runtime.py")
text = path.read_text(encoding="utf-8")
old = '''    order_id = _to_int(data.get("web_order_id"), None)
    current_status = str(data.get("status") or "").strip().lower()
    claim_staff_ids: list[str] = []

    if order_id is not None:
        from shared.order_acceptance import (
            PREPAY_ACCEPTANCE_STATUSES,
            cancel_acceptance_order,
            get_acceptance_state,
        )

        try:
            state = get_acceptance_state(int(order_id))
        except ValueError:
            state = None

        if state is not None:
            current_status = str(getattr(state, "status", None) or current_status).strip().lower()

        allowed_statuses = set(PREPAY_ACCEPTANCE_STATUSES) | {"cancelled"}
        if current_status and current_status not in allowed_statuses:
            raise ValueError("這張單已進入付款／進行中或已結束，不能用『撤回派單』回到改單。")

        if current_status in PREPAY_ACCEPTANCE_STATUSES:
            cancel_acceptance_order(
                int(order_id),
                source="dispatch_retracted",
                actor_discord_id=getattr(interaction.user, "id", None),
                cancellation_reason_code="dispatch_retracted_for_edit",
                cancellation_reason_text="客服撤回派單並返回原票口改單",
            )

        try:
'''
new = '''    order_id = _to_int(data.get("web_order_id"), None)
    current_status = str(data.get("status") or "").strip().lower()
    claim_staff_ids: list[str] = []

    from shared.order_acceptance import PREPAY_ACCEPTANCE_STATUSES

    allowed_statuses = set(PREPAY_ACCEPTANCE_STATUSES) | {"cancelled"}

    def _ensure_retractable_status(status: str) -> None:
        if status and status not in allowed_statuses:
            raise ValueError("這張單已進入付款／進行中或已結束，不能用『撤回派單』回到改單。")

    # Even if a partially-created order is missing web_order_id, never let a
    # paid/active local state bypass the retract guard.
    _ensure_retractable_status(current_status)

    if order_id is not None:
        from shared.order_acceptance import cancel_acceptance_order, get_acceptance_state

        try:
            state = get_acceptance_state(int(order_id))
        except ValueError:
            state = None

        if state is not None:
            current_status = str(getattr(state, "status", None) or current_status).strip().lower()
            _ensure_retractable_status(current_status)

        if current_status in PREPAY_ACCEPTANCE_STATUSES:
            cancel_acceptance_order(
                int(order_id),
                source="dispatch_retracted",
                actor_discord_id=getattr(interaction.user, "id", None),
                cancellation_reason_code="dispatch_retracted_for_edit",
                cancellation_reason_text="客服撤回派單並返回原票口改單",
            )

        try:
'''
if old not in text:
    raise SystemExit("retract status block anchor missing")
text = text.replace(old, new, 1)

old = '''        except Exception as exc:
            print(
                f"[dispatch-retract] claim history lookup failed order_id={order_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    warnings: list[str] = []
'''
new = '''        except Exception as exc:
            print(
                f"[dispatch-retract] claim history lookup failed order_id={order_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    # Fail safe before any best-effort Discord cleanup. If a later delete or DB
    # cleanup fails, stale payment components must not still see accepted_pending_pay.
    data["status"] = "cancelled"
    remember_order_data(channel_id, data)
    save_bot_data()

    warnings: list[str] = []
'''
if old not in text:
    raise SystemExit("retract fail-safe anchor missing")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")


# 2) Do not hold an SQLAlchemy read transaction open while benefit release helpers
# open their own SQLite write connections. Lookup -> close -> release -> delete.
path = Path("shared/web_order_sync.py")
text = path.read_text(encoding="utf-8")
start = text.find("def delete_web_order_by_ticket_channel(")
if start < 0:
    raise SystemExit("delete_web_order_by_ticket_channel not found")
# Function is intentionally the final definition in this module.
prefix = text[:start]
replacement = '''def delete_web_order_by_ticket_channel(*, ticket_channel_id=None, dispatch_message_id=None) -> bool:
    """從網站資料庫刪除對應 web_order 與相關分潤/接單資料。

    用於 DC bot /delete_order 與付款前撤回派單：
    - 網站不保留 cancelled/deleted 訂單
    - 先釋放仍在 reserved 的會員 / VIP 福利
    - 清掉付款前 acceptance / smart-dispatch lifecycle
    """
    from sqlalchemy import text

    from shared.db import SessionLocal

    ticket_channel_id_text = _to_text_id(ticket_channel_id)
    dispatch_message_id_text = _to_text_id(dispatch_message_id)

    if not ticket_channel_id_text and not dispatch_message_id_text:
        return False

    conditions = []
    params = {}

    if ticket_channel_id_text:
        conditions.append("ticket_channel_id = :ticket_channel_id")
        params["ticket_channel_id"] = ticket_channel_id_text

    if dispatch_message_id_text:
        conditions.append("dispatch_message_id = :dispatch_message_id")
        params["dispatch_message_id"] = dispatch_message_id_text

    sql = "SELECT id FROM web_orders WHERE " + " OR ".join(conditions) + " LIMIT 1"

    # Phase 1: lookup only, then close the Session before benefit helpers open
    # independent SQLite write connections. This avoids self-locking the DB.
    lookup_db = SessionLocal()
    try:
        row = lookup_db.execute(text(sql), params).first()
    finally:
        lookup_db.close()

    if row is None:
        return False

    order_id = int(row[0])

    from services.loyalty_benefits import release_coupon_for_order
    from services.vip_monthly_benefits import release_cash_benefits_for_channel

    # Both release helpers are idempotent. If later cleanup fails, retrying the
    # retract/delete operation is safe and the cancelled order remains blocked.
    release_coupon_for_order(order_id)
    if ticket_channel_id_text:
        release_cash_benefits_for_channel(ticket_channel_id_text)

    # Phase 2: delete the prepay lifecycle and WebOrder in one DB transaction.
    db = SessionLocal()
    try:
        for table_name in (
            "worker_payouts",
            "customer_service_payouts",
            "order_assignments",
            "sync_events",
            "order_acceptance_claims",
            "order_acceptance_meta",
            "smart_dispatch_notifications",
        ):
            table_exists = db.execute(
                text(
                    "SELECT 1 FROM sqlite_master "
                    "WHERE type = 'table' AND name = :table_name LIMIT 1"
                ),
                {"table_name": table_name},
            ).first()
            if table_exists is None:
                continue
            db.execute(
                text(f"DELETE FROM {table_name} WHERE order_id = :order_id"),
                {"order_id": order_id},
            )

        db.execute(
            text("DELETE FROM web_orders WHERE id = :order_id"),
            {"order_id": order_id},
        )

        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
'''
path.write_text(prefix + replacement, encoding="utf-8")


# 3) Add regressions for the status guard and fail-safe cancelled marker.
path = Path("tests/test_self_service_retract_dispatch.py")
text = path.read_text(encoding="utf-8")
if "import pytest\n" not in text:
    text = text.replace("import discord\n", "import discord\nimport pytest\n", 1)

extra = r'''


def test_retract_blocks_paid_local_state_even_without_web_order_id(monkeypatch):
    ticket = _FakeTextChannel(6101)
    dispatch = _FakeTextChannel(6102)
    dispatch.messages[7101] = _FakeMessage(7101)
    guild = _FakeGuild(ticket, dispatch)
    interaction = SimpleNamespace(
        guild=guild,
        channel=ticket,
        user=SimpleNamespace(id=8101, mention="<@8101>"),
    )
    draft = {
        "customer_id": 5101,
        "dispatch_message_id": 7101,
        "dispatch_channel_id": 6102,
        "status": "active",
    }

    monkeypatch.setattr(self_service_runtime.discord, "TextChannel", _FakeTextChannel)
    monkeypatch.setattr(self_service_runtime, "SELF_SERVICE_ORDER_SELECTIONS", {6101: draft}, raising=False)

    with pytest.raises(ValueError, match="不能用『撤回派單』"):
        asyncio.run(
            self_service_runtime.retract_waiting_acceptance_order_from_self_service(
                interaction,
                channel_id=6101,
            )
        )

    assert draft["status"] == "active"
    assert dispatch.messages[7101].deleted is False


def test_retract_marks_local_cancelled_before_later_cleanup_failure(monkeypatch):
    ticket = _FakeTextChannel(6201)
    dispatch = _FakeTextChannel(6202)
    dispatch.messages[7201] = _FakeMessage(7201)
    ticket.messages[7202] = _FakeMessage(7202)
    guild = _FakeGuild(ticket, dispatch)
    interaction = SimpleNamespace(
        guild=guild,
        channel=ticket,
        user=SimpleNamespace(id=8201, mention="<@8201>"),
    )
    draft = {
        "customer_id": 5201,
        "dispatch_message_id": 7201,
        "dispatch_channel_id": 6202,
        "web_order_id": 322,
        "status": "accepted_pending_pay",
        "payment_message_id": 7202,
    }
    remembered = []

    monkeypatch.setattr(self_service_runtime.discord, "TextChannel", _FakeTextChannel)
    monkeypatch.setattr(self_service_runtime, "SELF_SERVICE_ORDER_SELECTIONS", {6201: draft}, raising=False)
    monkeypatch.setattr(self_service_runtime, "ORDER_CLAIMS", {}, raising=False)
    monkeypatch.setattr(self_service_runtime, "DISPATCH_CHANNEL_ID", 6202, raising=False)
    monkeypatch.setattr(self_service_runtime, "remember_order_data", lambda *_args: remembered.append(dict(draft)))
    monkeypatch.setattr(self_service_runtime, "save_bot_data", lambda: None)
    monkeypatch.setattr(self_service_runtime, "get_taipei_now_iso", lambda: "2026-10-15T03:00:00+08:00")
    monkeypatch.setattr(self_service_runtime, "delete_claim_row_from_db", lambda **_kwargs: None)

    async def _noop_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(self_service_runtime, "send_order_log", _noop_log, raising=False)
    monkeypatch.setattr(order_acceptance, "get_acceptance_state", lambda _order_id: SimpleNamespace(status="accepted_pending_pay"))
    monkeypatch.setattr(order_acceptance, "cancel_acceptance_order", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(shared_db, "engine", _ClaimEngine())

    async def _revoke(_guild, _channel_id, _member):
        return True

    monkeypatch.setattr(acceptance_runtime, "revoke_order_ticket_access", _revoke)

    def _fail_delete(**_kwargs):
        raise RuntimeError("simulated cleanup failure")

    monkeypatch.setattr(web_order_sync, "delete_web_order_by_ticket_channel", _fail_delete)

    with pytest.raises(RuntimeError, match="simulated cleanup failure"):
        asyncio.run(
            self_service_runtime.retract_waiting_acceptance_order_from_self_service(
                interaction,
                channel_id=6201,
            )
        )

    assert draft["status"] == "cancelled"
    assert remembered and remembered[0]["status"] == "cancelled"
'''

if "test_retract_blocks_paid_local_state_even_without_web_order_id" not in text:
    text += extra
path.write_text(text, encoding="utf-8")
