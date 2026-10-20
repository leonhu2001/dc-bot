from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import discord

from services.order_dispatch_runtime import DispatchClaimView
from services.orders import _to_int, build_self_service_order_embed


def acceptance_public_open_timestamp(
    created_at: Any,
    lock_seconds: int,
) -> int | None:
    """Convert canonical acceptance-meta creation time into a Discord timestamp.

    This helper is presentation-only. The backend acceptance gate remains the
    source of truth for whether a member may actually claim an order.
    """
    created_text = str(created_at or "").strip()
    if not created_text:
        return None

    try:
        created = datetime.fromisoformat(created_text.replace("Z", "+00:00"))
    except ValueError:
        return None

    if created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)

    opens_at = created + timedelta(seconds=max(0, int(lock_seconds or 0)))
    return int(opens_at.timestamp())


def _normalized_ids(values: Any) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []

    for value in values or ():
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        result.append(normalized)

    return result


def _upsert_field(
    embed: discord.Embed,
    *,
    name: str,
    value: str,
    inline: bool,
) -> None:
    for index, field in enumerate(embed.fields):
        if str(field.name) == name:
            embed.set_field_at(index, name=name, value=value[:1024], inline=inline)
            return

    embed.add_field(name=name, value=value[:1024], inline=inline)


def _remove_fields(embed: discord.Embed, names: set[str]) -> None:
    """Remove obsolete UX fields before rebuilding the unified status block."""
    kept = [
        (str(field.name), str(field.value), bool(field.inline))
        for field in embed.fields
        if str(field.name) not in names
    ]
    if len(kept) == len(embed.fields):
        return

    embed.clear_fields()
    for name, value, inline in kept:
        embed.add_field(name=name, value=value, inline=inline)


def _dispatch_phase_text(
    claim_data: dict,
    *,
    now_ts: int | None = None,
) -> str:
    """Describe the visible phase without deciding whether a claim is allowed."""
    status = str(claim_data.get("status") or "").strip().lower()
    accepted_count = _to_int(claim_data.get("accepted_count"), 0) or 0
    required_staff_count = _to_int(claim_data.get("required_staff_count"), 1) or 1
    specified_staff_ids = _normalized_ids(claim_data.get("specified_staff_ids"))
    public_open_ts = _to_int(claim_data.get("public_acceptance_opens_at_unix"), None)

    if status == "accepted_pending_pay" or accepted_count >= required_staff_count:
        return "✅ 等待付款｜接單人數已滿"

    if status == "waiting_acceptance":
        current_ts = (
            int(datetime.now(timezone.utc).timestamp())
            if now_ts is None
            else int(now_ts)
        )
        if public_open_ts is not None and current_ts < public_open_ts:
            if specified_staff_ids:
                return f"🎯 等待接單｜指定優先 → 公開 <t:{public_open_ts}:R>"
            return f"🔒 等待接單｜接單保護 → 公開 <t:{public_open_ts}:R>"
        return "🟢 等待接單｜公開接單中"

    if status == "stored":
        return "🔵 已暫存｜接單暫停"
    if status in {"closed", "completed", "done"}:
        return "✅ 已結單｜接單面板已鎖定"
    if status in {"cancelled", "canceled"}:
        return "⛔ 已取消｜接單面板已停止"
    if status in {"active", "paid"}:
        return "🟢 進行中｜已付款"
    return str(claim_data.get("status") or "狀態未紀錄")


def _acceptance_status_text(claim_data: dict) -> str:
    """Backward-compatible alias for the unified dispatch phase label."""
    return _dispatch_phase_text(claim_data)


def apply_acceptance_dispatch_fields(
    embed: discord.Embed,
    claim_data: dict,
    *,
    now_ts: int | None = None,
) -> discord.Embed:
    """Apply one unified, read-only status hierarchy to a dispatch embed."""
    accepted_count = _to_int(claim_data.get("accepted_count"), 0) or 0
    required_staff_count = _to_int(claim_data.get("required_staff_count"), 1) or 1
    protector_count = _to_int(claim_data.get("protector_count"), 0) or 0
    min_protector_count = _to_int(claim_data.get("min_protector_count"), 0) or 0
    specified_staff_ids = _normalized_ids(claim_data.get("specified_staff_ids"))
    public_open_ts = _to_int(claim_data.get("public_acceptance_opens_at_unix"), None)

    # Phase 1 used separate status/protection/specified-slot fields. Remove them
    # first so refreshed messages do not accumulate stale sections.
    _remove_fields(
        embed,
        {
            "狀態",
            "目前階段",
            "接單保護",
            "指定／公開名額",
            "接單規則",
        },
    )

    _upsert_field(
        embed,
        name="目前階段",
        value=_dispatch_phase_text(claim_data, now_ts=now_ts),
        inline=False,
    )
    _upsert_field(
        embed,
        name="接單進度",
        value=f"{accepted_count}/{required_staff_count} 位",
        inline=True,
    )

    if min_protector_count > 0:
        _upsert_field(
            embed,
            name="護航需求",
            value=f"{protector_count}/{min_protector_count} 位護級",
            inline=True,
        )

    rule_lines: list[str] = []
    if specified_staff_ids:
        public_slots = max(0, required_staff_count - len(set(specified_staff_ids)))
        rule_lines.append(
            "指定人員："
            + "、".join(f"<@{staff_id}>" for staff_id in specified_staff_ids)
        )
        rule_lines.append(f"非指定公開名額：{public_slots} 位")

    if public_open_ts is not None:
        current_ts = (
            int(datetime.now(timezone.utc).timestamp())
            if now_ts is None
            else int(now_ts)
        )
        if current_ts < public_open_ts:
            rule_lines.append(
                f"公開接單：<t:{public_open_ts}:T> 開放（<t:{public_open_ts}:R>）"
            )
        else:
            rule_lines.append(f"公開接單：已於 <t:{public_open_ts}:T> 開放")

        if specified_staff_ids:
            rule_lines.append(
                "指定人員僅略過時間鎖；遊戲身分與職位／階級資格仍照原規則。"
            )

    if rule_lines:
        _upsert_field(
            embed,
            name="接單規則",
            value="\n".join(rule_lines),
            inline=False,
        )

    web_order_id = _to_int(claim_data.get("web_order_id"), None)
    if web_order_id is not None:
        website_lines = [f"網站訂單：WEB-{web_order_id}"]
        terms_version = str(claim_data.get("service_terms_version") or "").strip()
        if terms_version:
            website_lines.append(f"服務規章：已同意｜{terms_version}")
        _upsert_field(
            embed,
            name="網站下單資訊",
            value="\n".join(website_lines),
            inline=False,
        )

    return embed


def _replace_receiver_field(embed: discord.Embed, receiver_text: str | None) -> None:
    text = str(receiver_text or "").strip() or "尚未接單"
    _upsert_field(
        embed,
        name="目前接單",
        value=text,
        inline=False,
    )


class AcceptanceDispatchView(DispatchClaimView):
    """Discord-only UX wrapper; acceptance decisions stay in the shared backend."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        status = str(getattr(self, "status", "") or "").strip().lower()
        is_full = status == "accepted_pending_pay"

        for child in self.children:
            custom_id = str(getattr(child, "custom_id", "") or "")
            if custom_id == "dispatch_claim_booster":
                child.label = "等待付款｜已滿員" if is_full else "我要接單"
                if is_full:
                    child.disabled = True
            elif custom_id == "dispatch_cancel_claim":
                child.label = "取消我的接單"

    async def refresh_panel(
        self,
        interaction: discord.Interaction,
        locked: bool | None = None,
    ) -> None:
        guild = interaction.guild

        async def send_ephemeral(message: str) -> None:
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)

        if guild is None:
            await send_ephemeral("這個功能只能在伺服器內使用。")
            return

        if not isinstance(interaction.channel, discord.TextChannel):
            await send_ephemeral("這個功能只能在派單文字頻道使用。")
            return

        source_channel = guild.get_channel(self.source_channel_id)
        if source_channel is None or not isinstance(source_channel, discord.TextChannel):
            await send_ephemeral("找不到來源票口，請通知客服檢查訂單票口。")
            return

        if interaction.message is None:
            await send_ephemeral("找不到這張派單訊息，請通知客服重新整理派單面板。")
            return

        claim_data = self.get_claim_data(interaction.message.id)
        if locked is not None:
            claim_data["locked"] = locked

        try:
            from core.database import remember_claim_data

            remember_claim_data(interaction.message.id, claim_data)
        except Exception:
            pass

        receiver_text = self.build_receiver_text(claim_data)

        if interaction.message.embeds:
            new_embed = interaction.message.embeds[0].copy()
        else:
            new_embed = build_self_service_order_embed(
                customer_mention=f"<@{self.customer_id}>",
                category_label=self.category_label,
                item=self.item,
                quantity=_to_int(claim_data.get("quantity"), self.quantity) or 1,
                payment_method=self.payment_method,
                source_channel=source_channel,
                companion_preference=self.companion_preference,
                receiver_text=receiver_text,
            )

        _replace_receiver_field(new_embed, receiver_text)
        apply_acceptance_dispatch_fields(new_embed, claim_data)

        updated_view = AcceptanceDispatchView(
            customer_id=self.customer_id,
            category_label=self.category_label,
            item=self.item,
            quantity=_to_int(claim_data.get("quantity"), self.quantity) or 1,
            payment_method=self.payment_method,
            source_channel_id=self.source_channel_id,
            companion_preference=self.companion_preference,
            locked=bool(claim_data.get("locked")),
            status=str(claim_data.get("status") or "active"),
        )

        edit_kwargs = {
            "embed": new_embed,
            "view": updated_view,
            "allowed_mentions": discord.AllowedMentions(
                users=True,
                roles=False,
                everyone=False,
            ),
        }

        if interaction.response.is_done():
            await interaction.edit_original_response(**edit_kwargs)
        else:
            await interaction.response.edit_message(**edit_kwargs)
