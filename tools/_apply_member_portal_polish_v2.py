from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


# ---------------------------------------------------------------------------
# 1) Discord member portal: run immediately when StaffSyncCog is loaded.
# The cog itself is loaded from bot.py's on_ready, so its own first on_ready
# listener otherwise misses the event that loaded it.
# ---------------------------------------------------------------------------
staff_sync_path = "cogs/staff_sync.py"
staff_sync = read(staff_sync_path)
staff_sync = replace_once(
    staff_sync,
    """        self.staff_profile_refresh_event_loop.start()\n        self.loyalty_benefit_loop.start()\n\n    def cog_unload(self) -> None:\n        self.sync_staff_members_loop.cancel()\n        self.security_maintenance_loop.cancel()\n        self.staff_profile_refresh_event_loop.cancel()\n        self.loyalty_benefit_loop.cancel()\n""",
    """        self.staff_profile_refresh_event_loop.start()\n        self.loyalty_benefit_loop.start()\n        # cogs.staff_sync is loaded by bot.py during its first on_ready. A listener\n        # registered at that point does not receive the event already in progress,\n        # so schedule the panel sync explicitly as soon as this cog is constructed.\n        self.member_portal_panel_task = asyncio.create_task(\n            self._ensure_member_portal_panel()\n        )\n\n    def cog_unload(self) -> None:\n        self.sync_staff_members_loop.cancel()\n        self.security_maintenance_loop.cancel()\n        self.staff_profile_refresh_event_loop.cancel()\n        self.loyalty_benefit_loop.cancel()\n        task = getattr(self, \"member_portal_panel_task\", None)\n        if task is not None and not task.done():\n            task.cancel()\n""",
    label="staff_sync init task",
)

start_marker = "    @commands.Cog.listener()\n    async def on_ready(self) -> None:\n"
end_marker = "\n\n    @commands.Cog.listener()\n    async def on_voice_state_update(\n"
start = staff_sync.find(start_marker)
end = staff_sync.find(end_marker, start)
if start < 0 or end < 0:
    raise RuntimeError("staff_sync member portal on_ready block not found")
new_portal_block = '''    async def _ensure_member_portal_panel(self) -> None:
        await self.bot.wait_until_ready()

        if not getattr(self.bot, "_member_portal_view_registered", False):
            self.bot.add_view(MemberPortalView())
            self.bot._member_portal_view_registered = True

        channel = self.bot.get_channel(MEMBER_PORTAL_CHANNEL_ID)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(MEMBER_PORTAL_CHANNEL_ID)
            except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:
                print(
                    f"[member-portal] channel fetch failed id={MEMBER_PORTAL_CHANNEL_ID}: {exc}",
                    flush=True,
                )
                return

        if not isinstance(channel, discord.TextChannel):
            print(
                f"[member-portal] unsupported channel type id={MEMBER_PORTAL_CHANNEL_ID} "
                f"type={type(channel).__name__}",
                flush=True,
            )
            return

        if self.bot.user is None:
            return

        existing = None
        try:
            async for message in channel.history(limit=50):
                if message.author.id != self.bot.user.id or not message.embeds:
                    continue
                if str(message.embeds[0].footer.text or "") == MEMBER_PORTAL_MARKER:
                    existing = message
                    break
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(
                f"[member-portal] history read failed channel={channel.id}: {exc}",
                flush=True,
            )
            return

        try:
            if existing is None:
                message = await channel.send(
                    embed=build_member_portal_embed(),
                    view=MemberPortalView(),
                )
                print(
                    f"[member-portal] panel created channel={channel.id} message={message.id}",
                    flush=True,
                )
            else:
                await existing.edit(
                    embed=build_member_portal_embed(),
                    view=MemberPortalView(),
                )
                print(
                    f"[member-portal] panel refreshed channel={channel.id} message={existing.id}",
                    flush=True,
                )
        except (discord.Forbidden, discord.HTTPException) as exc:
            print(f"[member-portal] panel refresh failed: {exc}", flush=True)

    @commands.Cog.listener()
    async def on_ready(self) -> None:
        # Covers later Discord reconnects as well as the explicit startup task.
        await self._ensure_member_portal_panel()
'''
staff_sync = staff_sync[:start] + new_portal_block + staff_sync[end:]
write(staff_sync_path, staff_sync)


# ---------------------------------------------------------------------------
# 2) Separate customer-service payout base from gifted worker service value.
# ---------------------------------------------------------------------------
payout_path = "shared/payout.py"
payout = read(payout_path)
payout = replace_once(
    payout,
    """    named_bonus_worker_ids: list[str] | set[str] | None = None,\n    worker_base_rate: float = WORKER_BASE_PAYOUT_RATE,\n    customer_service_rate: float = CUSTOMER_SERVICE_PAYOUT_RATE,\n    named_bonus_rate: float = WORKER_NAMED_BONUS_RATE,\n) -> OrderPayoutResult:\n    if total_amount <= 0:\n        return OrderPayoutResult(\n""",
    """    named_bonus_worker_ids: list[str] | set[str] | None = None,\n    worker_base_rate: float = WORKER_BASE_PAYOUT_RATE,\n    customer_service_rate: float = CUSTOMER_SERVICE_PAYOUT_RATE,\n    named_bonus_rate: float = WORKER_NAMED_BONUS_RATE,\n    customer_service_total_amount: int | None = None,\n) -> OrderPayoutResult:\n    customer_service_amount = (\n        max(0, int(total_amount or 0))\n        if customer_service_total_amount is None\n        else max(0, int(customer_service_total_amount or 0))\n    )\n\n    if total_amount <= 0:\n        customer_service_payout = calculate_customer_service_payout(\n            customer_service_amount,\n            customer_service_rate,\n        )\n        return OrderPayoutResult(\n""",
    label="payout separate cs arg",
)
payout = replace_once(
    payout,
    """            customer_service_payout=0,\n            worker_payouts=[],\n            total_worker_payout=0,\n            total_payout=0,\n""",
    """            customer_service_payout=customer_service_payout,\n            worker_payouts=[],\n            total_worker_payout=0,\n            total_payout=customer_service_payout,\n""",
    label="payout zero worker cs result",
)
payout = payout.replace(
    """        customer_service_payout = calculate_customer_service_payout(\n            total_amount,\n            customer_service_rate,\n        )\n""",
    """        customer_service_payout = calculate_customer_service_payout(\n            customer_service_amount,\n            customer_service_rate,\n        )\n""",
)
payout = replace_once(
    payout,
    """    customer_service_payout = calculate_customer_service_payout(\n        total_amount,\n        customer_service_rate,\n    )\n""",
    """    customer_service_payout = calculate_customer_service_payout(\n        customer_service_amount,\n        customer_service_rate,\n    )\n""",
    label="payout final cs base",
)
write(payout_path, payout)

order_service_path = "web/app/services/order_service.py"
order_service = read(order_service_path)
helper = '''def _customer_service_payout_base(order: WebOrder) -> int:
    """Return the payout base for CS, excluding free service funded by the store.

    Point/cross-order benefits can increase the workers' service value, but they
    do not create additional CS commission. Existing VIP and store-funded cash
    discounts keep their current accounting behavior.
    """
    worker_base = max(
        0,
        int(
            getattr(order, "payout_base_amount", None)
            or getattr(order, "amount", 0)
            or 0
        ),
    )

    try:
        snapshot = json.loads(str(getattr(order, "price_snapshot_json", None) or "{}"))
    except Exception:
        snapshot = {}

    if not isinstance(snapshot, dict):
        return worker_base

    preview = snapshot.get("preview") if isinstance(snapshot.get("preview"), dict) else snapshot
    finance = preview.get("finance") if isinstance(preview, dict) and isinstance(preview.get("finance"), dict) else {}

    def _amount(name: str) -> int:
        try:
            return max(0, int(round(float(finance.get(name) or 0))))
        except (TypeError, ValueError):
            return 0

    gifted_service = _amount("point_service_value") + _amount("benefit_service_value")
    return max(0, worker_base - gifted_service)


'''
order_service = replace_once(
    order_service,
    "def recalculate_order_payouts(db: Session, order_id: int) -> None:\n",
    helper + "def recalculate_order_payouts(db: Session, order_id: int) -> None:\n",
    label="order_service cs helper",
)
order_service = replace_once(
    order_service,
    """        worker_discord_ids=worker_ids,\n        named_bonus_worker_ids=named_bonus_worker_ids,\n    )\n""",
    """        worker_discord_ids=worker_ids,\n        named_bonus_worker_ids=named_bonus_worker_ids,\n        customer_service_total_amount=_customer_service_payout_base(order),\n    )\n""",
    label="order_service payout call",
)
write(order_service_path, order_service)


# ---------------------------------------------------------------------------
# 3) Correct MO20261007003 CS payout after the earlier +1h worker repair.
# ---------------------------------------------------------------------------
data_repair_path = "services/data_repairs.py"
data_repair = read(data_repair_path)
data_repair = replace_once(
    data_repair,
    """from web.app.services.checkout_preview import calculate_point_service_value\nfrom web.app.services.order_service import recalculate_order_payouts\n""",
    """from web.app.services.checkout_preview import calculate_point_service_value\nfrom web.app.services.order_service import (\n    _customer_service_payout_base,\n    recalculate_order_payouts,\n)\n""",
    label="data repair imports",
)
data_repair = replace_once(
    data_repair,
    "MO20261007003_REPAIR_KEY = \"2026-10-10:MO20261007003:point-extra-hour-payout-v1\"\n",
    """MO20261007003_REPAIR_KEY = \"2026-10-10:MO20261007003:point-extra-hour-payout-v1\"\nMO20261007003_CS_REPAIR_KEY = \"2026-10-10:MO20261007003:exclude-gifted-hour-from-cs-v1\"\n""",
    label="data repair key",
)
cs_repair_func = '''\n\ndef repair_mo20261007003_customer_service_payout(db: Session) -> dict[str, Any]:
    """Remove the point-gifted hour from CS commission without touching workers."""
    repair_key = MO20261007003_CS_REPAIR_KEY
    if _repair_already_applied(db, repair_key):
        return {"status": "already_applied", "repair_key": repair_key}

    order = db.scalar(
        select(WebOrder)
        .where(WebOrder.bot_order_no == "MO20261007003")
        .limit(1)
    )
    if order is None:
        return {"status": "not_found", "repair_key": repair_key}

    rows = list(
        db.scalars(
            select(CustomerServicePayout)
            .where(CustomerServicePayout.order_id == int(order.id))
            .order_by(CustomerServicePayout.id.asc())
        ).all()
    )
    if not rows:
        return {
            "status": "skipped",
            "repair_key": repair_key,
            "order_id": int(order.id),
            "reason": "no customer-service payout row",
        }

    for row in rows:
        if str(row.payout_status or "").strip().lower() == PayoutStatus.PAID.value or row.paid_at is not None:
            return {
                "status": "skipped",
                "repair_key": repair_key,
                "order_id": int(order.id),
                "reason": "customer-service payout already paid",
            }

    cs_base = _customer_service_payout_base(order)
    before = [
        {
            "id": int(row.id),
            "rate": float(row.rate or 0),
            "payout_amount": float(row.payout_amount or 0),
        }
        for row in rows
    ]

    for row in rows:
        row.payout_amount = cs_base * float(row.rate or 0)

    db.flush()
    after = [
        {
            "id": int(row.id),
            "rate": float(row.rate or 0),
            "payout_amount": float(row.payout_amount or 0),
        }
        for row in rows
    ]

    db.add(
        AdminAuditLog(
            admin_discord_id="system",
            action="data_repair_exclude_gifted_service_from_cs_payout",
            target_type="order",
            target_id=str(int(order.id)),
            before_json=json.dumps(
                {"order_no": "MO20261007003", "customer_service_payouts": before},
                ensure_ascii=False,
            ),
            after_json=json.dumps(
                {
                    "order_no": "MO20261007003",
                    "customer_service_payout_base": cs_base,
                    "customer_service_payouts": after,
                },
                ensure_ascii=False,
            ),
            created_at=datetime.utcnow(),
        )
    )
    db.execute(
        text(
            f"INSERT INTO {REPAIR_TABLE} (repair_key, applied_at, note) "
            "VALUES (:repair_key, :applied_at, :note)"
        ),
        {
            "repair_key": repair_key,
            "applied_at": datetime.utcnow().isoformat(timespec="seconds"),
            "note": (
                "MO20261007003 CS commission reset to paid-service base; "
                f"cs_base={cs_base}T."
            ),
        },
    )

    return {
        "status": "applied",
        "repair_key": repair_key,
        "order_id": int(order.id),
        "customer_service_payout_base": cs_base,
        "before": before,
        "after": after,
    }
'''
data_repair = replace_once(
    data_repair,
    "\ndef apply_known_data_repairs() -> list[dict[str, Any]]:\n",
    cs_repair_func + "\n\ndef apply_known_data_repairs() -> list[dict[str, Any]]:\n",
    label="data repair cs function",
)
data_repair = replace_once(
    data_repair,
    """        result = repair_mo20261007003_point_hour_payout(db)\n        db.commit()\n        return [result]\n""",
    """        point_result = repair_mo20261007003_point_hour_payout(db)\n        cs_result = repair_mo20261007003_customer_service_payout(db)\n        db.commit()\n        return [point_result, cs_result]\n""",
    label="data repair runner",
)
write(data_repair_path, data_repair)


# ---------------------------------------------------------------------------
# 4) Loyalty coupon expiry: 90 days, visible on Web/Discord.
# ---------------------------------------------------------------------------
loyalty_path = "services/loyalty_benefits.py"
loyalty = read(loyalty_path)
loyalty = replace_once(
    loyalty,
    """GAME_THRESHOLD = 20.0\nGAME_BONUS = 1.0\n\nACTIVE = \"active\"\nRESERVED = \"reserved\"\nREDEEMED = \"redeemed\"\n""",
    """GAME_THRESHOLD = 20.0\nGAME_BONUS = 1.0\nCOUPON_VALID_DAYS = 90\n\nACTIVE = \"active\"\nRESERVED = \"reserved\"\nREDEEMED = \"redeemed\"\nEXPIRED = \"expired\"\n\n\ndef _parse_coupon_time(value: object) -> datetime | None:\n    raw = str(value or \"\").strip().replace(\"Z\", \"+00:00\")\n    if not raw:\n        return None\n    try:\n        dt = datetime.fromisoformat(raw)\n    except ValueError:\n        return None\n    if dt.tzinfo is None:\n        dt = dt.replace(tzinfo=TAIPEI_TZ)\n    return dt.astimezone(TAIPEI_TZ)\n\n\ndef _coupon_expiry_iso(issued_at: object = None) -> str:\n    base = _parse_coupon_time(issued_at) or datetime.now(TAIPEI_TZ)\n    return (base + timedelta(days=COUPON_VALID_DAYS)).isoformat(timespec=\"seconds\")\n\n\ndef _coupon_expiry_text(value: object) -> str:\n    dt = _parse_coupon_time(value)\n    return dt.strftime(\"%Y/%m/%d\") if dt else \"\"\n\n\ndef _expire_active_coupons(conn) -> int:\n    now = datetime.now(TAIPEI_TZ).isoformat(timespec=\"seconds\")\n    result = conn.execute(text(\"\"\"\n        UPDATE customer_benefit_coupons\n        SET status = 'expired'\n        WHERE status = 'active'\n          AND expires_at IS NOT NULL\n          AND expires_at <= :now\n    \"\"\"), {\"now\": now})\n    return int(result.rowcount or 0)\n""",
    label="loyalty expiry constants",
)
loyalty = replace_once(
    loyalty,
    """                source TEXT NOT NULL DEFAULT 'loyalty',\n                issued_at TEXT NOT NULL,\n                reserved_order_id INTEGER,\n""",
    """                source TEXT NOT NULL DEFAULT 'loyalty',\n                issued_at TEXT NOT NULL,\n                expires_at TEXT,\n                reserved_order_id INTEGER,\n""",
    label="loyalty expires column create",
)
# Add migration/backfill before leaving ensure_loyalty_tables.
needle = """        conn.execute(text(\"\"\"\n            CREATE TABLE IF NOT EXISTS loyalty_order_events (\n"""
insert = """        coupon_columns = {\n            str(row[1])\n            for row in conn.execute(text(\"PRAGMA table_info(customer_benefit_coupons)\")).fetchall()\n        }\n        if \"expires_at\" not in coupon_columns:\n            conn.execute(text(\"ALTER TABLE customer_benefit_coupons ADD COLUMN expires_at TEXT\"))\n\n        missing_expiry = conn.execute(text(\"\"\"\n            SELECT id, issued_at\n            FROM customer_benefit_coupons\n            WHERE expires_at IS NULL OR TRIM(expires_at) = ''\n        \"\"\")).mappings().all()\n        for row in missing_expiry:\n            conn.execute(text(\"\"\"\n                UPDATE customer_benefit_coupons\n                SET expires_at = :expires_at\n                WHERE id = :coupon_id\n            \"\"\"), {\n                \"coupon_id\": int(row[\"id\"]),\n                \"expires_at\": _coupon_expiry_iso(row.get(\"issued_at\")),\n            })\n        _expire_active_coupons(conn)\n\n        conn.execute(text(\"\"\"\n            CREATE TABLE IF NOT EXISTS loyalty_order_events (\n"""
loyalty = replace_once(loyalty, needle, insert, label="loyalty expiry migration")

# Decorate coupon rows with an expiry label.
loyalty = loyalty.replace(
    """        row[\"title\"] = _coupon_title(row)\n        coupons.append(row)\n""",
    """        row[\"title\"] = _coupon_title(row)\n        row[\"expires_at_text\"] = _coupon_expiry_text(row.get(\"expires_at\"))\n        coupons.append(row)\n""",
)
loyalty = loyalty.replace(
    """        row[\"title\"] = _coupon_title(row)\n        result.append(row)\n""",
    """        row[\"title\"] = _coupon_title(row)\n        row[\"expires_at_text\"] = _coupon_expiry_text(row.get(\"expires_at\"))\n        result.append(row)\n""",
)
loyalty = replace_once(
    loyalty,
    """    result = dict(row)\n    result[\"title\"] = _coupon_title(result)\n    return result\n""",
    """    result = dict(row)\n    result[\"title\"] = _coupon_title(result)\n    result[\"expires_at_text\"] = _coupon_expiry_text(result.get(\"expires_at\"))\n    return result\n""",
    label="loyalty get coupon expiry text",
)

# Expire before active coupon reads.
loyalty = loyalty.replace(
    """    with engine.begin() as conn:\n        coupon_rows = conn.execute(text(\"\"\"\n""",
    """    with engine.begin() as conn:\n        _expire_active_coupons(conn)\n        coupon_rows = conn.execute(text(\"\"\"\n""",
    1,
)
loyalty = loyalty.replace(
    """    with engine.begin() as conn:\n        rows = conn.execute(text(\"\"\"\n            SELECT *\n            FROM customer_benefit_coupons\n            WHERE customer_discord_id = :customer_id\n              AND scope_key = :scope_key\n              AND status = 'active'\n""",
    """    with engine.begin() as conn:\n        _expire_active_coupons(conn)\n        rows = conn.execute(text(\"\"\"\n            SELECT *\n            FROM customer_benefit_coupons\n            WHERE customer_discord_id = :customer_id\n              AND scope_key = :scope_key\n              AND status = 'active'\n""",
    1,
)
loyalty = loyalty.replace(
    """    with engine.begin() as conn:\n        row = conn.execute(text(\"\"\"\n            SELECT *\n            FROM customer_benefit_coupons\n""",
    """    with engine.begin() as conn:\n        _expire_active_coupons(conn)\n        row = conn.execute(text(\"\"\"\n            SELECT *\n            FROM customer_benefit_coupons\n""",
    1,
)

loyalty = replace_once(
    loyalty,
    """          AND scope_key = :scope_key\n          AND status = 'active'\n    \"\"\"), {\n        \"order_id\": int(order_id),\n        \"coupon_id\": int(coupon_id),\n        \"customer_id\": str(customer_id),\n        \"scope_key\": scope,\n    })\n""",
    """          AND scope_key = :scope_key\n          AND status = 'active'\n          AND (expires_at IS NULL OR expires_at > :now)\n    \"\"\"), {\n        \"order_id\": int(order_id),\n        \"coupon_id\": int(coupon_id),\n        \"customer_id\": str(customer_id),\n        \"scope_key\": scope,\n        \"now\": datetime.now(TAIPEI_TZ).isoformat(timespec=\"seconds\"),\n    })\n""",
    label="loyalty reserve expiry guard",
)
loyalty = replace_once(
    loyalty,
    """        result = conn.execute(text(\"\"\"\n            UPDATE customer_benefit_coupons\n            SET status = 'active', reserved_order_id = NULL\n            WHERE reserved_order_id = :order_id\n              AND status = 'reserved'\n        \"\"\"), {\"order_id\": int(order_id)})\n""",
    """        now = datetime.now(TAIPEI_TZ).isoformat(timespec=\"seconds\")\n        result = conn.execute(text(\"\"\"\n            UPDATE customer_benefit_coupons\n            SET status = CASE\n                    WHEN expires_at IS NOT NULL AND expires_at <= :now THEN 'expired'\n                    ELSE 'active'\n                END,\n                reserved_order_id = NULL\n            WHERE reserved_order_id = :order_id\n              AND status = 'reserved'\n        \"\"\"), {\"order_id\": int(order_id), \"now\": now})\n""",
    label="loyalty release expiry",
)
loyalty = replace_once(
    loyalty,
    """            for _ in range(issued_count):\n                result = conn.execute(text(\"\"\"\n                    INSERT INTO customer_benefit_coupons (\n                        customer_discord_id, scope_key, rule_key, rule_label,\n                        pricing_type, player_count, benefit_kind, benefit_units,\n                        status, source, issued_at\n                    ) VALUES (\n                        :customer_id, :scope_key, :rule_key, :rule_label,\n                        :pricing_type, :player_count, :benefit_kind, :benefit_units,\n                        'active', 'loyalty', :issued_at\n                    )\n                \"\"\"), {\n""",
    """            expires_at = _coupon_expiry_iso(now)\n            for _ in range(issued_count):\n                result = conn.execute(text(\"\"\"\n                    INSERT INTO customer_benefit_coupons (\n                        customer_discord_id, scope_key, rule_key, rule_label,\n                        pricing_type, player_count, benefit_kind, benefit_units,\n                        status, source, issued_at, expires_at\n                    ) VALUES (\n                        :customer_id, :scope_key, :rule_key, :rule_label,\n                        :pricing_type, :player_count, :benefit_kind, :benefit_units,\n                        'active', 'loyalty', :issued_at, :expires_at\n                    )\n                \"\"\"), {\n""",
    label="loyalty issue expiry sql",
)
loyalty = replace_once(
    loyalty,
    """                    \"benefit_units\": policy[\"benefit_units\"],\n                    \"issued_at\": now,\n                })\n""",
    """                    \"benefit_units\": policy[\"benefit_units\"],\n                    \"issued_at\": now,\n                    \"expires_at\": expires_at,\n                })\n""",
    label="loyalty issue expiry params",
)
loyalty = replace_once(
    loyalty,
    """                    \"benefit_kind\": policy[\"benefit_kind\"],\n                    \"benefit_units\": policy[\"benefit_units\"],\n                }\n""",
    """                    \"benefit_kind\": policy[\"benefit_kind\"],\n                    \"benefit_units\": policy[\"benefit_units\"],\n                    \"expires_at\": expires_at,\n                    \"expires_at_text\": _coupon_expiry_text(expires_at),\n                }\n""",
    label="loyalty issue coupon response",
)
write(loyalty_path, loyalty)


# ---------------------------------------------------------------------------
# 5) Discord benefit display includes expiry date.
# ---------------------------------------------------------------------------
member_portal_path = "views/member_portal.py"
member_portal = read(member_portal_path)
member_portal = replace_once(
    member_portal,
    """                value=\"\\n\".join(f\"• {item.get('title')}\" for item in coupons[:10]),\n""",
    """                value=\"\\n\".join(\n                    f\"• {item.get('title')}｜有效至 {item.get('expires_at_text') or '—'}\"\n                    for item in coupons[:10]\n                ),\n""",
    label="discord coupon expiry display",
)
write(member_portal_path, member_portal)


# ---------------------------------------------------------------------------
# 6) Recompose /me into a clearer member dashboard.
# ---------------------------------------------------------------------------
member_template = r'''{% extends "site_layout.html" %}

{% block head %}
<link rel="stylesheet" href="/static/css/member_center_v2.css?v=20261010-1">
{% endblock %}

{% block content %}
<section class="mc-hero">
    <div class="mc-shell mc-hero-grid">
        <div class="mc-identity">
            <div class="mc-avatar">
                {% if user.avatar %}
                    <img src="https://cdn.discordapp.com/avatars/{{ user.id }}/{{ user.avatar }}.png?size=256" alt="">
                {% else %}
                    <span>{{ (user.display_name or user.global_name or user.username or 'M')[:1] }}</span>
                {% endif %}
            </div>
            <div class="mc-identity-copy">
                <div class="mc-kicker">MY MOWAN</div>
                <h1>{{ user.display_name or user.global_name or user.username }}</h1>
                <p>把訂單、會員、錢包與福利集中在同一個地方。</p>
                <div class="mc-chip-row">
                    <span class="mc-chip mc-chip-gold">{{ member.vip_name }}</span>
                    {% if user.is_worker or user.is_companion %}<span class="mc-chip">員工</span>{% endif %}
                    {% if user.is_customer_service %}<span class="mc-chip">客服</span>{% endif %}
                </div>
            </div>
        </div>

        <aside class="mc-status-card">
            <div class="mc-status-head">
                <div>
                    <small>MEMBERSHIP</small>
                    <strong>{{ member.vip_name }}</strong>
                </div>
                <span>{{ member.total_spent_text }}</span>
            </div>
            <div class="mc-progress"><i style="width: {{ member.vip_progress.percent }}%"></i></div>
            {% if member.vip_progress.next_name %}
                <p>距 {{ member.vip_progress.next_name }} 尚差 <b>{{ "{:,}".format(member.vip_progress.remaining) }}T</b></p>
            {% else %}
                <p>已達最高 VIP 等級</p>
            {% endif %}
            <div class="mc-mini-stats">
                <div><small>錢包</small><strong>{{ member.wallet_balance_text }}</strong></div>
                <div><small>點數</small><strong>{{ "{:,}".format(member.points) }}</strong></div>
                <div><small>福利券</small><strong>{{ benefits.active_count }}</strong></div>
            </div>
        </aside>
    </div>
</section>

<section class="mc-shell mc-main">
    {% if request.query_params.get('denied') %}
        <div class="mc-alert">目前 Discord 身分組沒有該入口權限，系統已重新確認你的伺服器身分。</div>
    {% endif %}

    <nav class="mc-shortcuts" aria-label="會員功能">
        <a href="/order"><span>＋</span><b>立即下單</b><small>選服務與陪玩</small></a>
        <a href="/me/orders"><span>▣</span><b>我的訂單</b><small>{{ portal.open_count }} 張進行中</small></a>
        <a href="/me/wallet"><span>◈</span><b>錢包・儲值</b><small>{{ member.wallet_balance_text }}</small></a>
        <a href="#benefits"><span>◇</span><b>我的福利</b><small>{{ benefits.active_count }} 張可用</small></a>
        <a href="#favorites"><span>♡</span><b>我的收藏</b><small>{{ member.favorite_count }} 位</small></a>
        <a href="#vip"><span>◆</span><b>點數 / VIP</b><small>{{ "{:,}".format(member.points) }} 點</small></a>
    </nav>

    {% if user.is_employee or user.is_worker or user.is_companion or user.is_customer_service %}
    <div class="mc-staff-strip">
        <span>你同時擁有店內身分</span>
        <div>
            <a href="/employee">員工中心 →</a>
            {% if user.is_customer_service %}<a href="/service">客服後台 →</a>{% endif %}
        </div>
    </div>
    {% endif %}

    <div class="mc-section-title">
        <div><small>AT A GLANCE</small><h2>現在最重要的</h2></div>
    </div>

    <div class="mc-focus-grid">
        <section class="mc-card mc-card-primary">
            <div class="mc-card-head">
                <div><small>ORDERS</small><h3>訂單狀態</h3></div>
                <a href="/me/orders">查看全部 →</a>
            </div>
            <div class="mc-order-count">
                <strong>{{ portal.open_count }}</strong>
                <span>目前進行中</span>
            </div>
            {% if member.recent_orders %}
                <div class="mc-order-list">
                {% for order in member.recent_orders[:3] %}
                    <a href="/me/orders/{{ order.id }}" class="mc-order-row">
                        <div><small>{{ order.order_no }}</small><b>{{ order.item }}</b><span>{{ order.created_at }}</span></div>
                        <div><em class="status-{{ order.status }}">{{ order.status_label }}</em><strong>{{ order.amount_text }}</strong></div>
                    </a>
                {% endfor %}
                </div>
            {% else %}
                <div class="mc-empty"><b>還沒有訂單</b><span>第一次下單後，進度會直接出現在這裡。</span><a href="/order">去看看服務 →</a></div>
            {% endif %}
        </section>

        <section class="mc-card" id="benefits">
            <div class="mc-card-head">
                <div><small>BENEFITS</small><h3>我的福利</h3></div>
                <a href="/order">使用福利 →</a>
            </div>
            {% if benefits.coupons %}
                <div class="mc-coupon-stack">
                {% for coupon in benefits.coupons[:4] %}
                    <div class="mc-coupon">
                        <div><small>AVAILABLE</small><b>{{ coupon.title }}</b></div>
                        <span>有效至 {{ coupon.expires_at_text or '—' }}</span>
                    </div>
                {% endfor %}
                </div>
            {% elif benefits.progress %}
                <div class="mc-empty compact"><b>還差一點就有福利</b><span>完成付費服務後會自動累積，不需要另外登記。</span></div>
            {% else %}
                <div class="mc-empty compact"><b>目前沒有福利紀錄</b><span>開始消費後才顯示累積中的商品，不會列一排 0 進度。</span></div>
            {% endif %}

            {% if benefits.progress %}
                <div class="mc-progress-list">
                {% for item in benefits.progress[:4] %}
                    <div>
                        <span>{{ item.title }}</span>
                        <b>{{ item.progress_text }} {{ '局' if item.pricing_type == 'game' else '小時' }}</b>
                        <small>達標送 {{ '+1 局' if item.pricing_type == 'game' else '+30 分鐘' }}</small>
                    </div>
                {% endfor %}
                </div>
            {% endif %}
        </section>
    </div>

    <div class="mc-lower-grid">
        <section class="mc-card" id="favorites">
            <div class="mc-card-head">
                <div><small>FAVORITES</small><h3>我的收藏</h3></div>
                <a href="/staff">找陪玩 →</a>
            </div>
            {% if member.favorite_profiles %}
                <div class="mc-favorite-grid">
                {% for staff in member.favorite_profiles[:6] %}
                    <a href="/staff/{{ staff.staff_id }}">
                        <img src="{{ staff.avatar_url }}" alt="">
                        <div><b>{{ staff.display_name }}</b><span>{{ staff.role_title }}</span></div>
                        <i>→</i>
                    </a>
                {% endfor %}
                </div>
            {% else %}
                <div class="mc-empty compact"><b>還沒有收藏陪玩</b><span>收藏後，下次找人會快很多。</span></div>
            {% endif %}
        </section>

        <section class="mc-card" id="vip">
            <div class="mc-card-head">
                <div><small>VIP & POINTS</small><h3>會員進度</h3></div>
                <a href="/vip">完整制度 →</a>
            </div>
            <div class="mc-vip-summary">
                <div><span>目前等級</span><b>{{ member.vip_name }}</b></div>
                <div><span>累積有效消費</span><b>{{ member.total_spent_text }}</b></div>
                <div><span>目前可用點數</span><b>{{ "{:,}".format(member.points) }} 點</b></div>
                <div><span>已完成訂單</span><b>{{ member.completed_orders }}</b></div>
            </div>
        </section>
    </div>
</section>
{% endblock %}
'''
write("web/app/templates/member_center.html", member_template)

member_css = r'''.mc-shell{width:min(1180px,calc(100% - 32px));margin:0 auto}.mc-hero{padding:72px 0 26px;background:radial-gradient(circle at 82% 5%,rgba(223,183,92,.16),transparent 32%),linear-gradient(180deg,#0d0c0a 0%,#090909 100%)}.mc-hero-grid{display:grid;grid-template-columns:minmax(0,1.25fr) minmax(330px,.75fr);gap:22px;align-items:stretch}.mc-identity{display:flex;align-items:center;gap:24px;padding:32px;border:1px solid rgba(255,255,255,.08);border-radius:24px;background:rgba(255,255,255,.025)}.mc-avatar{width:96px;height:96px;border-radius:28px;overflow:hidden;display:grid;place-items:center;flex:0 0 auto;background:#1d1a14;border:1px solid rgba(223,183,92,.28);font-size:34px;font-weight:900}.mc-avatar img{width:100%;height:100%;object-fit:cover}.mc-kicker,.mc-card-head small,.mc-section-title small,.mc-status-head small{font-size:10px;font-weight:900;letter-spacing:.18em;color:#d9b55d}.mc-identity h1{margin:7px 0 4px;font-size:clamp(30px,5vw,48px);line-height:1.05}.mc-identity p{margin:0;color:rgba(235,232,222,.62);font-size:14px}.mc-chip-row{display:flex;gap:8px;flex-wrap:wrap;margin-top:17px}.mc-chip{padding:6px 10px;border-radius:999px;background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.08);font-size:11px}.mc-chip-gold{background:rgba(223,183,92,.12);border-color:rgba(223,183,92,.28);color:#edcf83}.mc-status-card{padding:26px;border:1px solid rgba(223,183,92,.2);border-radius:24px;background:linear-gradient(145deg,rgba(31,27,18,.95),rgba(15,14,12,.98))}.mc-status-head{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.mc-status-head div{display:grid;gap:5px}.mc-status-head strong{font-size:22px}.mc-status-head>span{font-size:12px;color:rgba(235,232,222,.55)}.mc-status-card p{margin:10px 0 0;font-size:12px;color:rgba(235,232,222,.62)}.mc-progress{height:7px;margin-top:20px;overflow:hidden;border-radius:999px;background:rgba(255,255,255,.07)}.mc-progress i{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,#b98c35,#efd580)}.mc-mini-stats{display:grid;grid-template-columns:repeat(3,1fr);gap:8px;margin-top:22px}.mc-mini-stats>div{padding:13px 12px;border-radius:14px;background:rgba(255,255,255,.04)}.mc-mini-stats small,.mc-mini-stats strong{display:block}.mc-mini-stats small{color:rgba(235,232,222,.48);font-size:10px}.mc-mini-stats strong{margin-top:5px;font-size:16px}.mc-main{padding:26px 0 84px}.mc-alert{margin-bottom:18px;padding:13px 16px;border-radius:14px;border:1px solid rgba(223,183,92,.24);background:rgba(223,183,92,.08);font-size:13px}.mc-shortcuts{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:10px}.mc-shortcuts a{min-height:112px;padding:16px;border:1px solid rgba(255,255,255,.075);border-radius:17px;background:#111;display:flex;flex-direction:column;justify-content:space-between;text-decoration:none;color:inherit;transition:.16s ease}.mc-shortcuts a:hover{transform:translateY(-2px);border-color:rgba(223,183,92,.35);background:#15130f}.mc-shortcuts span{font-size:18px;color:#d9b55d}.mc-shortcuts b{font-size:14px}.mc-shortcuts small{font-size:10px;color:rgba(235,232,222,.48)}.mc-staff-strip{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-top:12px;padding:13px 16px;border:1px solid rgba(114,154,255,.14);border-radius:14px;background:rgba(114,154,255,.055);font-size:12px}.mc-staff-strip div{display:flex;gap:14px}.mc-staff-strip a{color:#d9c27e;text-decoration:none;font-weight:800}.mc-section-title{display:flex;justify-content:space-between;align-items:end;margin:44px 0 16px}.mc-section-title h2{margin:4px 0 0;font-size:26px}.mc-focus-grid{display:grid;grid-template-columns:minmax(0,1.35fr) minmax(320px,.65fr);gap:14px}.mc-lower-grid{display:grid;grid-template-columns:1.15fr .85fr;gap:14px;margin-top:14px}.mc-card{padding:22px;border:1px solid rgba(255,255,255,.075);border-radius:20px;background:linear-gradient(180deg,#111,#0d0d0d)}.mc-card-primary{min-height:390px}.mc-card-head{display:flex;align-items:flex-start;justify-content:space-between;gap:14px}.mc-card-head h3{margin:4px 0 0;font-size:20px}.mc-card-head a{color:#d6bc74;text-decoration:none;font-size:11px;font-weight:800}.mc-order-count{display:flex;align-items:baseline;gap:10px;margin:24px 0 14px}.mc-order-count strong{font-size:44px;line-height:1}.mc-order-count span{font-size:12px;color:rgba(235,232,222,.5)}.mc-order-list{display:grid;gap:8px}.mc-order-row{display:flex;justify-content:space-between;gap:16px;align-items:center;padding:13px 14px;border-radius:14px;background:rgba(255,255,255,.035);text-decoration:none;color:inherit}.mc-order-row>div:first-child{display:grid;gap:3px}.mc-order-row small,.mc-order-row span{font-size:10px;color:rgba(235,232,222,.48)}.mc-order-row b{font-size:13px}.mc-order-row>div:last-child{display:grid;gap:6px;justify-items:end}.mc-order-row em{font-style:normal;font-size:10px}.mc-order-row strong{font-size:12px}.mc-empty{min-height:160px;display:flex;flex-direction:column;justify-content:center;align-items:flex-start;gap:8px;color:rgba(235,232,222,.62)}.mc-empty.compact{min-height:112px}.mc-empty b{color:#eee9df}.mc-empty span{font-size:12px}.mc-empty a{color:#d6bc74;text-decoration:none;font-size:12px;font-weight:800}.mc-coupon-stack{display:grid;gap:8px;margin-top:20px}.mc-coupon{padding:14px;border-radius:14px;border:1px solid rgba(223,183,92,.17);background:rgba(223,183,92,.06);display:flex;justify-content:space-between;gap:12px;align-items:center}.mc-coupon div{display:grid;gap:4px}.mc-coupon small{font-size:9px;letter-spacing:.13em;color:#d8b35c}.mc-coupon b{font-size:12px}.mc-coupon>span{font-size:10px;color:rgba(235,232,222,.48);white-space:nowrap}.mc-progress-list{display:grid;gap:8px;margin-top:14px}.mc-progress-list>div{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:2px 12px;padding:11px 0;border-top:1px solid rgba(255,255,255,.06)}.mc-progress-list span{font-size:11px}.mc-progress-list b{font-size:11px}.mc-progress-list small{grid-column:1/-1;color:rgba(235,232,222,.44);font-size:10px}.mc-favorite-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px;margin-top:18px}.mc-favorite-grid a{display:flex;align-items:center;gap:11px;padding:11px;border-radius:14px;background:rgba(255,255,255,.035);text-decoration:none;color:inherit}.mc-favorite-grid img{width:40px;height:40px;border-radius:12px;object-fit:cover}.mc-favorite-grid div{display:grid;gap:2px;min-width:0;flex:1}.mc-favorite-grid b{font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.mc-favorite-grid span{font-size:10px;color:rgba(235,232,222,.46)}.mc-favorite-grid i{font-style:normal;color:#d6bc74}.mc-vip-summary{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;margin-top:18px}.mc-vip-summary>div{padding:15px;border-radius:14px;background:rgba(255,255,255,.035)}.mc-vip-summary span,.mc-vip-summary b{display:block}.mc-vip-summary span{font-size:10px;color:rgba(235,232,222,.46)}.mc-vip-summary b{margin-top:6px;font-size:14px}@media(max-width:980px){.mc-hero-grid,.mc-focus-grid,.mc-lower-grid{grid-template-columns:1fr}.mc-shortcuts{grid-template-columns:repeat(3,1fr)}}@media(max-width:620px){.mc-shell{width:min(100% - 22px,1180px)}.mc-hero{padding-top:34px}.mc-identity{padding:21px;align-items:flex-start}.mc-avatar{width:70px;height:70px;border-radius:20px}.mc-identity h1{font-size:28px}.mc-status-card{padding:20px}.mc-mini-stats{grid-template-columns:repeat(3,1fr)}.mc-shortcuts{grid-template-columns:repeat(2,1fr)}.mc-shortcuts a{min-height:94px;padding:14px}.mc-staff-strip{align-items:flex-start;flex-direction:column}.mc-section-title{margin-top:34px}.mc-card{padding:17px}.mc-favorite-grid,.mc-vip-summary{grid-template-columns:1fr}.mc-order-row{align-items:flex-start}.mc-coupon{align-items:flex-start;flex-direction:column}.mc-coupon>span{white-space:normal}}'''
write("web/app/static/css/member_center_v2.css", member_css)


# ---------------------------------------------------------------------------
# 7) Regression tests for the policy split and startup behavior.
# ---------------------------------------------------------------------------
test_content = r'''from pathlib import Path

from shared.payout import calculate_order_payout


ROOT = Path(__file__).resolve().parents[1]


def test_gifted_service_can_raise_worker_payout_without_raising_cs():
    result = calculate_order_payout(
        total_amount=1750,
        worker_discord_ids=["worker"],
        customer_service_total_amount=1000,
    )
    assert result.worker_payouts[0].final_payout == 1400
    assert result.customer_service_payout == 50


def test_member_portal_panel_is_scheduled_when_staff_sync_cog_loads():
    source = (ROOT / "cogs/staff_sync.py").read_text(encoding="utf-8")
    assert "asyncio.create_task(" in source
    assert "self._ensure_member_portal_panel()" in source
    assert "[member-portal] panel created" in source


def test_loyalty_coupons_have_ninety_day_expiry():
    source = (ROOT / "services/loyalty_benefits.py").read_text(encoding="utf-8")
    assert "COUPON_VALID_DAYS = 90" in source
    assert "expires_at TEXT" in source
    assert "SET status = 'expired'" in source


def test_cs_payout_base_excludes_point_and_loyalty_service_value():
    source = (ROOT / "web/app/services/order_service.py").read_text(encoding="utf-8")
    assert 'finance.get("point_service_value")' in source
    assert 'finance.get("benefit_service_value")' in source
    assert "customer_service_total_amount=_customer_service_payout_base(order)" in source


def test_member_center_uses_recomposed_dashboard():
    source = (ROOT / "web/app/templates/member_center.html").read_text(encoding="utf-8")
    assert "mc-shortcuts" in source
    assert "現在最重要的" in source
    assert "有效至 {{ coupon.expires_at_text" in source
'''
write("tests/test_member_portal_polish.py", test_content)

print("member portal polish patch applied")
