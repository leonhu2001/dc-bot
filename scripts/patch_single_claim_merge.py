from pathlib import Path

BOT_PATH = Path("bot.py")
SYNC_PATH = Path("shared/web_order_sync.py")

bot_text = BOT_PATH.read_text(encoding="utf-8")
sync_text = SYNC_PATH.read_text(encoding="utf-8")

sync_func = r'''

def apply_discord_claim_event_to_web(
    *,
    dispatch_message_id,
    worker_discord_id,
    worker_display_name,
    role_type="booster",
    action="claim",
) -> bool:
    """Discord 按接單/取消接單時，同步到網站。

    重點：這裡只新增/移除「目前操作的這個人」。
    不會用 DC 當下名單覆蓋網站，避免網站接單的人被吃掉。
    """
    from datetime import datetime

    from sqlalchemy import select

    from shared.db import SessionLocal
    from shared.models import OrderAssignment, PayoutStatus, WebOrder, WorkerPayout

    dispatch_message_id_text = _to_text_id(dispatch_message_id)
    worker_discord_id_text = _to_text_id(worker_discord_id)

    if dispatch_message_id_text is None or worker_discord_id_text is None:
        return False

    db = SessionLocal()

    try:
        order = db.scalar(
            select(WebOrder)
            .where(WebOrder.dispatch_message_id == dispatch_message_id_text)
            .limit(1)
        )

        if order is None:
            return False

        assignment = db.scalar(
            select(OrderAssignment)
            .where(OrderAssignment.order_id == order.id)
            .where(OrderAssignment.worker_discord_id == worker_discord_id_text)
            .limit(1)
        )

        if action == "claim":
            if assignment is None:
                assignment = OrderAssignment(
                    order_id=order.id,
                    worker_discord_id=worker_discord_id_text,
                    worker_display_name=worker_display_name or worker_discord_id_text,
                    role_type=role_type or "booster",
                    is_active=True,
                    has_named_bonus=False,
                )
                db.add(assignment)
            else:
                assignment.worker_display_name = worker_display_name or assignment.worker_display_name or worker_discord_id_text
                assignment.role_type = role_type or assignment.role_type or "booster"
                assignment.is_active = True
                assignment.removed_at = None

        elif action == "unclaim":
            if assignment is not None:
                assignment.is_active = False
                assignment.removed_at = datetime.utcnow()

        else:
            raise ValueError(f"unknown action: {action}")

        db.flush()

        active_assignments = list(
            db.scalars(
                select(OrderAssignment)
                .where(OrderAssignment.order_id == order.id)
                .where(OrderAssignment.is_active.is_(True))
                .order_by(OrderAssignment.id.asc())
            ).all()
        )

        previous_payouts = list(
            db.scalars(
                select(WorkerPayout)
                .where(WorkerPayout.order_id == order.id)
            ).all()
        )

        previous_status = {
            payout.worker_discord_id: (
                payout.payout_status,
                payout.paid_at,
                payout.note,
            )
            for payout in previous_payouts
        }

        for payout in previous_payouts:
            db.delete(payout)

        amount = int(order.amount or 0)
        count = len(active_assignments)

        if count > 0:
            gross_share = amount // count

            for active_assignment in active_assignments:
                has_named_bonus = bool(active_assignment.has_named_bonus)

                base_payout = round(gross_share * 0.80)
                named_bonus_amount = round(gross_share * 0.05) if has_named_bonus else 0
                final_payout = base_payout + named_bonus_amount

                payout_status, paid_at, note = previous_status.get(
                    active_assignment.worker_discord_id,
                    (PayoutStatus.UNPAID.value, None, None),
                )

                db.add(
                    WorkerPayout(
                        order_id=order.id,
                        worker_discord_id=active_assignment.worker_discord_id,
                        worker_display_name=active_assignment.worker_display_name,
                        gross_share=gross_share,
                        base_rate=0.80,
                        base_payout=base_payout,
                        named_bonus_rate=0.05,
                        named_bonus_amount=named_bonus_amount,
                        has_named_bonus=has_named_bonus,
                        final_payout=final_payout,
                        payout_status=payout_status or PayoutStatus.UNPAID.value,
                        paid_at=paid_at,
                        note=note,
                    )
                )

        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
'''

if "def apply_discord_claim_event_to_web(" not in sync_text:
    sync_text = sync_text.rstrip() + sync_func + "\n"
    SYNC_PATH.write_text(sync_text, encoding="utf-8")
    print("patched shared/web_order_sync.py")
else:
    print("shared/web_order_sync.py already patched")


helper = r'''

def sync_single_discord_claim_event_to_web(interaction, claim_type: str, action: str) -> None:
    """把 Discord 接單按鈕單一操作同步到網站。

    action:
    - claim：只新增目前這個人
    - unclaim：只移除目前這個人
    """
    try:
        from shared.web_order_sync import apply_discord_claim_event_to_web

        if interaction.message is None:
            return

        role_type = "companion" if claim_type == "companion" else "booster"

        apply_discord_claim_event_to_web(
            dispatch_message_id=interaction.message.id,
            worker_discord_id=interaction.user.id,
            worker_display_name=getattr(interaction.user, "display_name", None) or getattr(interaction.user, "name", None) or str(interaction.user.id),
            role_type=role_type,
            action=action,
        )
    except Exception as exc:
        print(
            f"[web-sync] Discord 接單事件同步網站失敗 "
            f"message_id={getattr(getattr(interaction, 'message', None), 'id', None)} "
            f"user_id={getattr(getattr(interaction, 'user', None), 'id', None)} "
            f"claim_type={claim_type} action={action}: {exc}"
        )
'''

if "def sync_single_discord_claim_event_to_web(" not in bot_text:
    insert_pos = bot_text.find("class DispatchClaimView")
    if insert_pos == -1:
        raise RuntimeError("找不到 DispatchClaimView")
    bot_text = bot_text[:insert_pos] + helper + "\n\n" + bot_text[insert_pos:]
    print("inserted helper into bot.py")
else:
    print("bot.py helper already exists")


old_claim = """        claim_data[claim_type].add(interaction.user.id)
        remember_claim_data(interaction.message.id, claim_data)
"""

new_claim = """        claim_data[claim_type].add(interaction.user.id)
        remember_claim_data(interaction.message.id, claim_data)
        sync_single_discord_claim_event_to_web(interaction, claim_type, "claim")
"""

if old_claim in bot_text and new_claim not in bot_text:
    bot_text = bot_text.replace(old_claim, new_claim, 1)
    print("patched claim_order")
else:
    print("claim_order already patched or pattern not found")


old_cancel = """        remember_claim_data(interaction.message.id, claim_data)

        await send_order_log(
"""

new_cancel = """        remember_claim_data(interaction.message.id, claim_data)
        sync_single_discord_claim_event_to_web(interaction, "booster", "unclaim")
        sync_single_discord_claim_event_to_web(interaction, "companion", "unclaim")

        await send_order_log(
"""

if old_cancel in bot_text and new_cancel not in bot_text:
    bot_text = bot_text.replace(old_cancel, new_cancel, 1)
    print("patched cancel_claim")
else:
    print("cancel_claim already patched or pattern not found")

BOT_PATH.write_text(bot_text, encoding="utf-8")
print("done")
