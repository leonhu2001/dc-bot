from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:120]!r}")
    if text.count(old) != 1:
        raise SystemExit(f"anchor not unique in {path}: count={text.count(old)}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


path = Path("services/self_service_runtime.py")
text = path.read_text(encoding="utf-8")
old = "from core.database import remember_claim_data, remember_order_data, save_bot_data\nfrom core.permissions import is_customer_staff\n"
new = """from core.database import (
    delete_claim_row_from_db,
    remember_claim_data,
    remember_order_data,
    save_bot_data,
)
from core.permissions import is_customer_staff, is_manager_or_admin
"""
if old not in text:
    raise SystemExit("self_service_runtime import anchor missing")
text = text.replace(old, new, 1)
text = text.replace(
    '        "build_self_service_order_embed",\n        "remember_claim_data",',
    '        "build_self_service_order_embed",\n        "delete_claim_row_from_db",\n        "remember_claim_data",',
    1,
)
text = text.replace(
    '        "is_customer_staff",\n        "get_taipei_now_iso",',
    '        "is_customer_staff",\n        "is_manager_or_admin",\n        "get_taipei_now_iso",',
    1,
)

retract_function = r'''

async def retract_waiting_acceptance_order_from_self_service(
    interaction: discord.Interaction,
    *,
    channel_id: int,
) -> str:
    """撤回付款前派單，但保留票口自助下單草稿供客服修改後重送。"""
    guild = interaction.guild

    if guild is None:
        raise ValueError("這個功能只能在伺服器內使用。")

    if not isinstance(interaction.channel, discord.TextChannel):
        raise ValueError("無法確認目前票口頻道。")

    channel_id = int(channel_id)
    data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id)

    if not isinstance(data, dict):
        raise ValueError("找不到這張票口的自助下單資料。")

    dispatch_message_id = _to_int(data.get("dispatch_message_id"), None)
    if dispatch_message_id is None:
        raise ValueError("這張單目前沒有可撤回的派單。")

    order_id = _to_int(data.get("web_order_id"), None)
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
            from sqlalchemy import text as sql_text
            from shared.db import engine as acceptance_engine

            with acceptance_engine.begin() as conn:
                rows = conn.execute(
                    sql_text("""
                        SELECT DISTINCT staff_discord_id
                        FROM order_acceptance_claims
                        WHERE order_id = :order_id
                    """),
                    {"order_id": int(order_id)},
                ).mappings().all()
            claim_staff_ids = [
                str(row.get("staff_discord_id") or "").strip()
                for row in rows
                if str(row.get("staff_discord_id") or "").strip()
            ]
        except Exception as exc:
            print(
                f"[dispatch-retract] claim history lookup failed order_id={order_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )

    warnings: list[str] = []

    payment_message_id = _to_int(data.get("payment_message_id"), None)
    if payment_message_id is not None:
        try:
            payment_message = await interaction.channel.fetch_message(payment_message_id)
            await payment_message.delete()
        except discord.NotFound:
            pass
        except (discord.Forbidden, discord.HTTPException) as exc:
            warnings.append(f"付款 Panel 未能自動刪除：{type(exc).__name__}")

    if claim_staff_ids:
        from services.acceptance.runtime import revoke_order_ticket_access

        for staff_id_text in claim_staff_ids:
            staff_id = _to_int(staff_id_text, None)
            if staff_id is None:
                continue
            member = guild.get_member(staff_id)
            if member is None:
                try:
                    member = await guild.fetch_member(staff_id)
                except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                    member = None
            if member is not None:
                await revoke_order_ticket_access(guild, channel_id, member)

    dispatch_channel_id = _to_int(data.get("dispatch_channel_id"), DISPATCH_CHANNEL_ID) or DISPATCH_CHANNEL_ID
    dispatch_channel = guild.get_channel(dispatch_channel_id)

    if not isinstance(dispatch_channel, discord.TextChannel):
        try:
            fetched_channel = await guild.fetch_channel(dispatch_channel_id)
            dispatch_channel = fetched_channel if isinstance(fetched_channel, discord.TextChannel) else None
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            dispatch_channel = None

    if isinstance(dispatch_channel, discord.TextChannel):
        try:
            dispatch_message = await dispatch_channel.fetch_message(dispatch_message_id)
            await dispatch_message.delete()
        except discord.NotFound:
            pass
        except (discord.Forbidden, discord.HTTPException) as exc:
            warnings.append(f"派單訊息未能自動刪除：{type(exc).__name__}")
    else:
        warnings.append("找不到原派單頻道，派單訊息可能需要人工確認")

    from shared.web_order_sync import delete_web_order_by_ticket_channel

    delete_web_order_by_ticket_channel(
        ticket_channel_id=channel_id,
        dispatch_message_id=dispatch_message_id,
    )

    claim_message_ids: set[int] = {int(dispatch_message_id)}
    for raw_message_id, claim_data in list(ORDER_CLAIMS.items()):
        if _to_int((claim_data or {}).get("source_channel_id"), None) == channel_id:
            parsed_message_id = _to_int(raw_message_id, None)
            if parsed_message_id is not None:
                claim_message_ids.add(int(parsed_message_id))

    for message_id in claim_message_ids:
        ORDER_CLAIMS.pop(message_id, None)
        delete_claim_row_from_db(
            message_id=message_id,
            source_channel_id=channel_id,
        )

    for key in (
        "dispatch_message_id",
        "dispatch_channel_id",
        "web_order_id",
        "status",
        "waiting_acceptance_created_at",
        "accepted_staff_display_text",
        "payment_message_id",
        "payment_channel_id",
        "payment_finalizing",
        "payment_finalized_at",
        "payment_finalized_by",
        "rule_version",
        "rule_snapshot_json",
        "price_snapshot_json",
        "web_order_note",
    ):
        data.pop(key, None)

    data.pop("payment_method", None)
    data["closed"] = False
    data["dispatch_retracted_at"] = get_taipei_now_iso()
    data["dispatch_retracted_by"] = getattr(interaction.user, "id", None)

    remember_order_data(channel_id, data)
    save_bot_data()

    try:
        await send_order_log(
            guild,
            title="撤回派單｜返回改單",
            fields=[
                ("操作人員", getattr(interaction.user, "mention", str(getattr(interaction.user, "id", "未知"))), True),
                ("顧客", f"<@{data.get('customer_id')}>" if data.get("customer_id") else "未紀錄", True),
                ("項目", str(data.get("item") or "未紀錄"), True),
                ("票口", interaction.channel.mention, False),
            ],
            color=discord.Color.orange(),
        )
    except Exception as exc:
        print(
            f"[dispatch-retract] order log failed channel_id={channel_id}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )

    result = "已撤回派單，原票口已恢復可改單；修改完成後可重新送出等待接單。"
    if warnings:
        result += "\n" + "\n".join(f"⚠️ {warning}" for warning in warnings)
    return result
'''

marker = "\nPRICE_FORMULA_VERSION = 2\n"
if marker not in text:
    raise SystemExit("PRICE_FORMULA_VERSION marker missing")
text = text.replace(marker, retract_function + marker, 1)

dispatched_view = r'''

class SelfServiceDispatchedView(discord.ui.View):
    """送出後只保留撤回操作；使用固定 custom_id，重啟後可重新註冊。"""

    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(
        label="撤回派單",
        style=discord.ButtonStyle.danger,
        custom_id="self_service_retract_dispatch_button",
    )
    async def retract_dispatch(self, interaction: discord.Interaction, button: discord.ui.Button):
        if (
            not isinstance(interaction.user, discord.Member)
            or not (
                is_customer_staff(interaction.user)
                or is_manager_or_admin(interaction.user)
            )
        ):
            await interaction.response.send_message("只有客服、店長或管理員可以撤回派單。", ephemeral=True)
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await interaction.response.send_message("無法確認目前票口頻道。", ephemeral=True)
            return

        channel_id = int(interaction.channel.id)
        data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
        customer_id = _to_int(data.get("customer_id"), None)

        if customer_id is None:
            await interaction.response.send_message("找不到這張票口的顧客資料。", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)

        try:
            response_text = await retract_waiting_acceptance_order_from_self_service(
                interaction,
                channel_id=channel_id,
            )
        except ValueError as exc:
            await interaction.followup.send(str(exc), ephemeral=True)
            return
        except Exception as exc:
            print(
                f"[dispatch-retract] failed channel_id={channel_id}: "
                f"{type(exc).__name__}: {exc}",
                flush=True,
            )
            await interaction.followup.send(
                "撤回派單失敗，原訂單狀態未確認完成，請通知客服主管查看後台紀錄。",
                ephemeral=True,
            )
            return

        panel_refreshed = False
        if interaction.message is not None:
            try:
                updated_data = SELF_SERVICE_ORDER_SELECTIONS.get(channel_id, {})
                await interaction.message.edit(
                    embed=build_self_service_panel_embed(customer_id, updated_data, interaction.guild),
                    view=SelfServiceOrderView(
                        customer_id=customer_id,
                        channel_id=channel_id,
                        selected_category=updated_data.get("category"),
                    ),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )
                panel_refreshed = True
            except discord.HTTPException:
                panel_refreshed = False

        if not panel_refreshed:
            response_text += "\n⚠️ 自助下單 Panel 未能自動刷新，請重新開啟票口 Panel 後再修改。"

        await interaction.followup.send(response_text, ephemeral=True)
'''

view_marker = "\nclass SelfServiceOrderView(discord.ui.View):\n"
if view_marker not in text:
    raise SystemExit("SelfServiceOrderView marker missing")
text = text.replace(view_marker, dispatched_view + view_marker, 1)

old_panel_edit = "                await panel_message.edit(view=None)"
new_panel_edit = """                await panel_message.edit(
                    embed=build_self_service_panel_embed(self.customer_id, data, interaction.guild),
                    view=SelfServiceDispatchedView(),
                    allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
                )"""
if old_panel_edit not in text:
    raise SystemExit("submit modal panel edit anchor missing")
text = text.replace(old_panel_edit, new_panel_edit, 1)
path.write_text(text, encoding="utf-8")

replace_once(
    "bot.py",
    "    SelfServiceSubmitNoteModal,\n    SelfServiceOrderView,",
    "    SelfServiceSubmitNoteModal,\n    SelfServiceDispatchedView,\n    SelfServiceOrderView,",
)
replace_once(
    "bot.py",
    "    bot.add_view(StaffOrderOperationView())\n    bot.add_view(RecruitControlView())",
    "    bot.add_view(StaffOrderOperationView())\n    bot.add_view(SelfServiceDispatchedView())\n    bot.add_view(RecruitControlView())",
)

web = Path("shared/web_order_sync.py")
web_text = web.read_text(encoding="utf-8")
old_cleanup = '''        order_id = int(row[0])

        for table_name in (
            "worker_payouts",
            "customer_service_payouts",
            "order_assignments",
            "sync_events",
        ):
            db.execute(
                text(f"DELETE FROM {table_name} WHERE order_id = :order_id"),
                {"order_id": order_id},
            )

        db.execute(
            text("DELETE FROM web_orders WHERE id = :order_id"),
            {"order_id": order_id},
        )'''
new_cleanup = '''        order_id = int(row[0])

        from services.loyalty_benefits import release_coupon_for_order
        from services.vip_monthly_benefits import release_cash_benefits_for_channel

        release_coupon_for_order(order_id)
        if ticket_channel_id_text:
            release_cash_benefits_for_channel(ticket_channel_id_text)

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
        )'''
if old_cleanup not in web_text:
    raise SystemExit("web_order_sync delete cleanup anchor missing")
web.write_text(web_text.replace(old_cleanup, new_cleanup, 1), encoding="utf-8")

test_text = r'''from __future__ import annotations

import asyncio
from contextlib import contextmanager
from types import SimpleNamespace

import discord

from services import self_service_runtime
from services.acceptance import runtime as acceptance_runtime
from services import loyalty_benefits, vip_monthly_benefits
from shared import db as shared_db
from shared import order_acceptance, web_order_sync


class _FakeResult:
    def __init__(self, *, first=None, rows=None):
        self._first = first
        self._rows = rows or []

    def first(self):
        return self._first

    def mappings(self):
        return self

    def all(self):
        return list(self._rows)


class _ClaimConnection:
    def execute(self, _statement, _params=None):
        return _FakeResult(rows=[{"staff_discord_id": "9001"}])


class _ClaimEngine:
    @contextmanager
    def begin(self):
        yield _ClaimConnection()


class _FakeMessage:
    def __init__(self, message_id: int):
        self.id = int(message_id)
        self.deleted = False
        self.edits = []

    async def delete(self):
        self.deleted = True

    async def edit(self, **kwargs):
        self.edits.append(kwargs)


class _FakeTextChannel:
    def __init__(self, channel_id: int):
        self.id = int(channel_id)
        self.mention = f"<#{channel_id}>"
        self.messages = {}

    async def fetch_message(self, message_id: int):
        message_id = int(message_id)
        if message_id not in self.messages:
            raise RuntimeError("message missing")
        return self.messages[message_id]


class _FakeGuild:
    def __init__(self, *channels):
        self._channels = {int(channel.id): channel for channel in channels}
        self.member = SimpleNamespace(id=9001)

    def get_channel(self, channel_id):
        return self._channels.get(int(channel_id))

    async def fetch_channel(self, channel_id):
        return self.get_channel(channel_id)

    def get_member(self, member_id):
        return self.member if int(member_id) == 9001 else None

    async def fetch_member(self, member_id):
        return self.get_member(member_id)


class _FakeDeleteSession:
    def __init__(self):
        self.statements = []
        self.committed = False

    def execute(self, statement, params=None):
        sql = str(statement)
        self.statements.append((sql, dict(params or {})))
        if sql.startswith("SELECT id FROM web_orders"):
            return _FakeResult(first=(321,))
        if "sqlite_master" in sql:
            return _FakeResult(first=(1,))
        return _FakeResult()

    def commit(self):
        self.committed = True

    def rollback(self):
        raise AssertionError("rollback should not be called")

    def close(self):
        pass


def test_retract_dispatch_keeps_draft_and_cleans_prepay_state(monkeypatch):
    ticket = _FakeTextChannel(6001)
    dispatch = _FakeTextChannel(6002)
    dispatch_message = _FakeMessage(7001)
    payment_message = _FakeMessage(7002)
    dispatch.messages[7001] = dispatch_message
    ticket.messages[7002] = payment_message
    guild = _FakeGuild(ticket, dispatch)
    interaction = SimpleNamespace(
        guild=guild,
        channel=ticket,
        user=SimpleNamespace(id=8001, mention="<@8001>"),
    )

    draft = {
        "customer_id": 5001,
        "category": "delta",
        "item": "娛樂陪",
        "quantity": 3,
        "dispatch_message_id": 7001,
        "dispatch_channel_id": 6002,
        "web_order_id": 321,
        "status": "waiting_acceptance",
        "payment_message_id": 7002,
        "payment_method": "待付款",
    }
    claims = {
        7001: {
            "source_channel_id": 6001,
            "booster": {9001},
            "companion": set(),
        }
    }
    remembered = []
    deleted_claim_rows = []
    cancelled = []
    revoked = []
    deleted_web = []

    monkeypatch.setattr(self_service_runtime.discord, "TextChannel", _FakeTextChannel)
    monkeypatch.setattr(self_service_runtime, "SELF_SERVICE_ORDER_SELECTIONS", {6001: draft}, raising=False)
    monkeypatch.setattr(self_service_runtime, "ORDER_CLAIMS", claims, raising=False)
    monkeypatch.setattr(self_service_runtime, "DISPATCH_CHANNEL_ID", 6002, raising=False)
    monkeypatch.setattr(self_service_runtime, "remember_order_data", lambda *args: remembered.append(args))
    monkeypatch.setattr(self_service_runtime, "save_bot_data", lambda: None)
    monkeypatch.setattr(
        self_service_runtime,
        "delete_claim_row_from_db",
        lambda **kwargs: deleted_claim_rows.append(kwargs),
    )
    monkeypatch.setattr(self_service_runtime, "get_taipei_now_iso", lambda: "2026-10-15T02:45:00+08:00")

    async def _noop_log(*_args, **_kwargs):
        return None

    monkeypatch.setattr(self_service_runtime, "send_order_log", _noop_log, raising=False)
    monkeypatch.setattr(
        order_acceptance,
        "get_acceptance_state",
        lambda _order_id: SimpleNamespace(status="waiting_acceptance"),
    )
    monkeypatch.setattr(
        order_acceptance,
        "cancel_acceptance_order",
        lambda order_id, **kwargs: cancelled.append((order_id, kwargs)),
    )
    monkeypatch.setattr(shared_db, "engine", _ClaimEngine())

    async def _revoke(_guild, channel_id, member):
        revoked.append((channel_id, member.id))
        return True

    monkeypatch.setattr(acceptance_runtime, "revoke_order_ticket_access", _revoke)
    monkeypatch.setattr(
        web_order_sync,
        "delete_web_order_by_ticket_channel",
        lambda **kwargs: deleted_web.append(kwargs) or True,
    )

    result = asyncio.run(
        self_service_runtime.retract_waiting_acceptance_order_from_self_service(
            interaction,
            channel_id=6001,
        )
    )

    assert "已撤回派單" in result
    assert dispatch_message.deleted is True
    assert payment_message.deleted is True
    assert cancelled and cancelled[0][0] == 321
    assert revoked == [(6001, 9001)]
    assert deleted_web == [{"ticket_channel_id": 6001, "dispatch_message_id": 7001}]
    assert 7001 not in claims
    assert deleted_claim_rows
    assert draft["item"] == "娛樂陪"
    assert draft["quantity"] == 3
    assert draft["category"] == "delta"
    assert draft["closed"] is False
    assert draft["dispatch_retracted_by"] == 8001
    assert "dispatch_message_id" not in draft
    assert "dispatch_channel_id" not in draft
    assert "web_order_id" not in draft
    assert "status" not in draft
    assert "payment_message_id" not in draft
    assert "payment_method" not in draft
    assert remembered


def test_deleted_web_order_releases_benefits_and_purges_prepay_tables(monkeypatch):
    session = _FakeDeleteSession()
    released_coupon = []
    released_vip = []

    monkeypatch.setattr(web_order_sync, "SessionLocal", lambda: session)
    monkeypatch.setattr(loyalty_benefits, "release_coupon_for_order", lambda order_id: released_coupon.append(order_id) or 1)
    monkeypatch.setattr(vip_monthly_benefits, "release_cash_benefits_for_channel", lambda channel_id: released_vip.append(str(channel_id)) or 1)

    assert web_order_sync.delete_web_order_by_ticket_channel(
        ticket_channel_id=6001,
        dispatch_message_id=7001,
    ) is True

    sql_text = "\n".join(sql for sql, _params in session.statements)
    assert released_coupon == [321]
    assert released_vip == ["6001"]
    assert "DELETE FROM order_acceptance_claims" in sql_text
    assert "DELETE FROM order_acceptance_meta" in sql_text
    assert "DELETE FROM smart_dispatch_notifications" in sql_text
    assert "DELETE FROM web_orders" in sql_text
    assert session.committed is True


def test_dispatched_view_is_persistent_and_has_retract_button():
    view = self_service_runtime.SelfServiceDispatchedView()
    assert view.timeout is None
    retract_buttons = [
        child for child in view.children
        if getattr(child, "custom_id", None) == "self_service_retract_dispatch_button"
    ]
    assert len(retract_buttons) == 1
    assert retract_buttons[0].label == "撤回派單"
'''
Path("tests/test_self_service_retract_dispatch.py").write_text(test_text, encoding="utf-8")
