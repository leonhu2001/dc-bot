from pathlib import Path

path = Path("services/self_service_runtime.py")
text = path.read_text(encoding="utf-8")

import_anchor = "from services.smart_dispatch import create_smart_dispatch_plan, set_specified_dm_results\n"
import_line = "from services.self_service_retract import retract_self_service_dispatch\n"
if import_line not in text:
    if import_anchor not in text:
        raise SystemExit("smart dispatch import anchor missing")
    text = text.replace(import_anchor, import_anchor + import_line, 1)

owned_anchor = '        "set_specified_dm_results",\n'
if '        "retract_self_service_dispatch",\n' not in text:
    if owned_anchor not in text:
        raise SystemExit("module owned anchor missing")
    text = text.replace(
        owned_anchor,
        owned_anchor + '        "retract_self_service_dispatch",\n',
        1,
    )

start_marker = "async def retract_waiting_acceptance_order_from_self_service(\n"
end_marker = "PRICE_FORMULA_VERSION = 2\n"
start = text.find(start_marker)
end = text.find(end_marker, start)
if start < 0 or end < 0:
    raise SystemExit(f"retract function markers missing start={start} end={end}")

wrapper = '''async def retract_waiting_acceptance_order_from_self_service(
    interaction: discord.Interaction,
    *,
    channel_id: int,
) -> str:
    """Adapter from the legacy self-service runtime into the retract lifecycle."""
    return await retract_self_service_dispatch(
        interaction,
        channel_id=channel_id,
        order_selections=SELF_SERVICE_ORDER_SELECTIONS,
        order_claims=ORDER_CLAIMS,
        dispatch_channel_id=DISPATCH_CHANNEL_ID,
        remember_order=remember_order_data,
        save_data=save_bot_data,
        delete_claim_row=delete_claim_row_from_db,
        order_log_sender=send_order_log,
        now_iso=get_taipei_now_iso,
    )


'''
text = text[:start] + wrapper + text[end:]
path.write_text(text, encoding="utf-8")
