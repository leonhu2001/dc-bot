from pathlib import Path

ROOT = Path(".")
BOT_PATH = ROOT / "bot.py"
SYNC_PATH = ROOT / "shared" / "web_order_sync.py"

bot_text = BOT_PATH.read_text(encoding="utf-8")
sync_text = SYNC_PATH.read_text(encoding="utf-8")

helper = r'''

def _sync_dispatch_claims_to_web_from_bot(dispatch_message_id, claim_data, guild):
    """Discord 派單訊息按接單/取消接單後，同步寫回網站資料庫。"""
    try:
        from shared.web_order_sync import sync_dispatch_claims_to_web

        companion_ids = sorted(int(user_id) for user_id in claim_data.get("companion", set()))
        booster_ids = sorted(int(user_id) for user_id in claim_data.get("booster", set()))

        display_names = {}

        for user_id in companion_ids + booster_ids:
            member = guild.get_member(user_id) if guild is not None else None
            display_names[str(user_id)] = (
                getattr(member, "display_name", None)
                or getattr(member, "name", None)
                or str(user_id)
            )

        sync_dispatch_claims_to_web(
            dispatch_message_id=dispatch_message_id,
            companion_ids=companion_ids,
            booster_ids=booster_ids,
            worker_display_names=display_names,
        )
    except Exception as exc:
        print(f"[web-sync] Discord 接單同步網站失敗 dispatch_message_id={dispatch_message_id}: {exc}")
'''

if "_sync_dispatch_claims_to_web_from_bot" not in bot_text:
    bot_text = bot_text.rstrip() + helper + "\n"

def patch_method(text: str, method_name: str) -> str:
    start_marker = f"    async def {method_name}"
    start = text.find(start_marker)
    if start == -1:
        raise RuntimeError(f"找不到 {method_name}")

    next_method = text.find("\n    async def ", start + len(start_marker))
    next_button = text.find("\n    @discord.ui.button", start + len(start_marker))

    candidates = [pos for pos in [next_method, next_button] if pos != -1]
    end = min(candidates) if candidates else len(text)

    block = text[start:end]

    call_line = "        _sync_dispatch_claims_to_web_from_bot(interaction.message.id, claim_data, interaction.guild)\n"

    if "_sync_dispatch_claims_to_web_from_bot(interaction.message.id" in block:
        return text

    target = "        remember_claim_data(interaction.message.id, claim_data)\n"

    index = block.find(target)
    if index == -1:
        raise RuntimeError(f"{method_name} 找不到 remember_claim_data")

    insert_at = start + index + len(target)
    return text[:insert_at] + call_line + text[insert_at:]

bot_text = patch_method(bot_text, "claim_order")
bot_text = patch_method(bot_text, "cancel_claim")

BOT_PATH.write_text(bot_text, encoding="utf-8")


sync_func = r'''

def sync_dispatch_claims_to_web(
    *,
    dispatch_message_id,
    companion_ids=None,
    booster_ids=None,
    worker_display_names=None,
) -> bool:
    """把 Discord 派單訊息上的接單狀態同步到網站資料庫。

    邏輯：
    - 用 dispatch_message_id 找 web_orders
    - companion_ids + booster_ids 寫入 order_assignments
    - 依 active 接單人重新平均計算 worker_payouts
    - 掛名 +5% 會依 order_assignments.has_named_bonus 保留
    """
    from datetime import datetime

    from sqlalchemy import select

    from shared.db import SessionLocal
    from shared.models import OrderAssignment, PayoutStatus, WebOrder, WorkerPayout

    dispatch_message_id_text = _to_text_id(dispatch_message_id)

    if dispatch_message_id_text is None:
        return False

    companion_ids = [str(user_id) for user_id in (companion_ids or [])]
    booster_ids = [str(user_id) for user_id in (booster_ids or [])]
    worker_display_names = worker_display_names or {}

    desired = {}

    for user_id in companion_ids:
        desired[user_id] = "companion"

    for user_id in booster_ids:
        desired[user_id] = "booster"

    db = SessionLocal()

    try:
        order = db.scalar(
            select(WebOrder)
            .where(WebOrder.dispatch_message_id == dispatch_message_id_text)
            .limit(1)
        )

        if order is None:
            return False

        assignments = list(
            db.scalars(
                select(OrderAssignment)
                .where(OrderAssignment.order_id == order.id)
            ).all()
        )

        assignment_by_worker = {
            assignment.worker_discord_id: assignment
            for assignment in assignments
        }

        now = datetime.utcnow()

        for worker_id, role_type in desired.items():
            display_name = worker_display_names.get(worker_id) or worker_id
            assignment = assignment_by_worker.get(worker_id)

            if assignment is None:
                assignment = OrderAssignment(
                    order_id=order.id,
                    worker_discord_id=worker_id,
                    worker_display_name=display_name,
                    role_type=role_type,
                    is_active=True,
                    has_named_bonus=False,
                )
                db.add(assignment)
            else:
                assignment.worker_display_name = display_name
                assignment.role_type = role_type
                assignment.is_active = True
                assignment.removed_at = None

        for assignment in assignments:
            if assignment.worker_discord_id not in desired:
                assignment.is_active = False
                assignment.removed_at = now

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

            for assignment in active_assignments:
                has_named_bonus = bool(assignment.has_named_bonus)

                base_payout = round(gross_share * 0.80)
                named_bonus_amount = round(gross_share * 0.05) if has_named_bonus else 0
                final_payout = base_payout + named_bonus_amount

                payout_status, paid_at, note = previous_status.get(
                    assignment.worker_discord_id,
                    (PayoutStatus.UNPAID.value, None, None),
                )

                db.add(
                    WorkerPayout(
                        order_id=order.id,
                        worker_discord_id=assignment.worker_discord_id,
                        worker_display_name=assignment.worker_display_name,
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

if "def sync_dispatch_claims_to_web(" not in sync_text:
    sync_text = sync_text.rstrip() + sync_func + "\n"

SYNC_PATH.write_text(sync_text, encoding="utf-8")

print("patched bot.py and shared/web_order_sync.py")
