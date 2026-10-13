from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    source = target.read_text(encoding="utf-8")
    count = source.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected one match, got {count}\n--- pattern ---\n{old[:500]}")
    target.write_text(source.replace(old, new, 1), encoding="utf-8")


# 1) Canonical VIP monthly cash-voucher lifecycle.
replace_once(
    "services/vip_monthly_benefits.py",
    '''BENEFIT_LABELS: dict[str, str] = {
    MONTHLY_COUPON_200: "VIP 每月 200T 折現券",
    MONTHLY_COUPON_500: "VIP 每月額外 500T 折現券",
    BLACK_DIAMOND_CHOICE: "黑鑽每月尊享福利",
}
''',
    '''BENEFIT_LABELS: dict[str, str] = {
    MONTHLY_COUPON_200: "VIP 每月 200T 折現券",
    MONTHLY_COUPON_500: "VIP 每月額外 500T 折現券",
    BLACK_DIAMOND_CHOICE: "黑鑽每月尊享福利",
}

MONTHLY_CASH_AMOUNTS: dict[str, int] = {
    MONTHLY_COUPON_200: 200,
    MONTHLY_COUPON_500: 500,
}
''',
)

replace_once(
    "services/vip_monthly_benefits.py",
    '''\ndef reserve_black_diamond_choice(
''',
    '''\ndef list_available_cash_benefits(
    customer_id: str | int,
    *,
    now: datetime | None = None,
    web_db: str | Path | None = None,
    bot_db: str | Path | None = None,
    ensure_synced: bool = True,
) -> list[dict[str, Any]]:
    """Return current-month VIP cash vouchers that can be selected now."""
    snapshot = get_customer_vip_monthly_snapshot(
        customer_id,
        now=now,
        web_db=web_db,
        bot_db=bot_db,
        ensure_synced=ensure_synced,
    )
    result: list[dict[str, Any]] = []
    for row in snapshot.get("cash_benefits") or []:
        if str(row.get("status") or "") != AVAILABLE:
            continue
        benefit_key = str(row.get("benefit_key") or "")
        amount = int(MONTHLY_CASH_AMOUNTS.get(benefit_key, 0) or 0)
        if amount <= 0:
            continue
        item = dict(row)
        item["amount"] = amount
        item["title"] = str(row.get("benefit_label") or BENEFIT_LABELS.get(benefit_key) or benefit_key)
        result.append(item)
    return result


def get_available_cash_benefit(
    benefit_id: str | int,
    *,
    customer_id: str | int,
    now: datetime | None = None,
    web_db: str | Path | None = None,
    bot_db: str | Path | None = None,
) -> dict[str, Any] | None:
    wanted = str(benefit_id)
    for row in list_available_cash_benefits(
        customer_id,
        now=now,
        web_db=web_db,
        bot_db=bot_db,
    ):
        if str(row.get("id")) == wanted:
            return row
    return None


def reserve_cash_benefit_for_channel(
    *,
    benefit_id: str | int,
    customer_id: str | int,
    channel_id: str | int,
    now: datetime | None = None,
    web_db: str | Path | None = None,
    bot_db: str | Path | None = None,
) -> dict[str, Any]:
    """Atomically reserve one current-month VIP cash voucher for an order channel."""
    current = _normalize_now(now)
    sync_current_month_vip_benefits(now=current, web_db=web_db, bot_db=bot_db)
    month = _month_key(current)
    now_text = current.isoformat(timespec="seconds")
    path = _web_db_path(web_db)
    ensure_vip_monthly_tables(path)

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            UPDATE vip_monthly_benefits
            SET status='reserved',
                reserved_at=?,
                reserved_channel_id=?,
                updated_at=?
            WHERE id=?
              AND customer_id=?
              AND month_key=?
              AND benefit_key IN (?, ?)
              AND status='available'
            """,
            (
                now_text,
                str(channel_id),
                now_text,
                int(benefit_id),
                str(customer_id),
                month,
                MONTHLY_COUPON_200,
                MONTHLY_COUPON_500,
            ),
        )
        if int(cur.rowcount or 0) != 1:
            raise ValueError("這張 VIP 每月折現券已使用、已保留或已失效。")
        conn.commit()
        row = conn.execute(
            "SELECT * FROM vip_monthly_benefits WHERE id=? LIMIT 1",
            (int(benefit_id),),
        ).fetchone()
    return dict(row)


def release_cash_benefits_for_channel(
    channel_id: str | int,
    *,
    now: datetime | None = None,
    web_db: str | Path | None = None,
    bot_db: str | Path | None = None,
) -> int:
    """Release reserved VIP cash vouchers when an order is cancelled."""
    current = _normalize_now(now)
    current_month = _month_key(current)
    now_text = current.isoformat(timespec="seconds")
    path = _web_db_path(web_db)
    ensure_vip_monthly_tables(path)

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT id, customer_id, month_key, benefit_key
            FROM vip_monthly_benefits
            WHERE reserved_channel_id=?
              AND benefit_key IN (?, ?)
              AND status='reserved'
            """,
            (str(channel_id), MONTHLY_COUPON_200, MONTHLY_COUPON_500),
        ).fetchall()

        released = 0
        for row in rows:
            member_status = _current_member_status(
                str(row["customer_id"]),
                now=current,
                bot_db=bot_db,
            )
            eligible_keys = _benefit_keys_for_level(str(member_status.get("current_level") or "普通魔丸"))
            next_status = (
                AVAILABLE
                if str(row["month_key"]) == current_month and str(row["benefit_key"]) in eligible_keys
                else REVOKED
            )
            cur = conn.execute(
                """
                UPDATE vip_monthly_benefits
                SET status=?,
                    reserved_at=NULL,
                    reserved_channel_id=NULL,
                    updated_at=?
                WHERE id=? AND status='reserved'
                """,
                (next_status, now_text, int(row["id"])),
            )
            released += int(cur.rowcount or 0)
        conn.commit()
    return released


def redeem_cash_benefits_for_channel(
    channel_id: str | int,
    *,
    now: datetime | None = None,
    web_db: str | Path | None = None,
) -> int:
    """Finalize reserved VIP cash vouchers when an order is closed."""
    current = _normalize_now(now)
    now_text = current.isoformat(timespec="seconds")
    path = _web_db_path(web_db)
    ensure_vip_monthly_tables(path)
    with sqlite3.connect(path, timeout=15) as conn:
        cur = conn.execute(
            """
            UPDATE vip_monthly_benefits
            SET status='redeemed',
                redeemed_at=?,
                updated_at=?
            WHERE reserved_channel_id=?
              AND benefit_key IN (?, ?)
              AND status='reserved'
            """,
            (now_text, now_text, str(channel_id), MONTHLY_COUPON_200, MONTHLY_COUPON_500),
        )
        conn.commit()
        return int(cur.rowcount or 0)


def reserve_black_diamond_choice(
''',
)

# 2) Show VIP monthly vouchers in the self-service benefit picker.
replace_once(
    "services/self_service_selection_runtime.py",
    '''                default=(parent_view.selected_key is None and parent_view.selected_coupon_id is None),
            )
        ]

        for coupon in parent_view.available_coupons:
''',
    '''                default=(
                    parent_view.selected_key is None
                    and parent_view.selected_coupon_id is None
                    and parent_view.selected_vip_monthly_benefit_id is None
                ),
            )
        ]

        for benefit in parent_view.available_vip_monthly_benefits:
            amount = int(benefit.get("amount") or 0)
            options.append(
                discord.SelectOption(
                    label=_truncate_select_text(str(benefit.get("title") or "VIP 每月折現券")),
                    value=f"vip_monthly:{benefit['id']}",
                    description=_truncate_select_text(f"折抵 {amount}T；與其他福利擇一"),
                    default=str(benefit.get("id")) == str(parent_view.selected_vip_monthly_benefit_id),
                )
            )

        for coupon in parent_view.available_coupons:
''',
)

replace_once(
    "services/self_service_selection_runtime.py",
    '''            "selected_benefit_coupon_id",
            "point_benefit_key",
''',
    '''            "selected_benefit_coupon_id",
            "selected_vip_monthly_benefit_id",
            "vip_monthly_benefit_id",
            "vip_monthly_benefit_key",
            "vip_monthly_benefit_title",
            "vip_monthly_cash_amount",
            "point_benefit_key",
''',
)

replace_once(
    "services/self_service_selection_runtime.py",
    '''        if selected.startswith("coupon:"):
            try:
                data["selected_benefit_coupon_id"] = int(selected.split(":", 1)[1])
            except (TypeError, ValueError):
                await interaction.response.send_message("福利券格式錯誤，請重新選擇。", ephemeral=True)
                return
        elif selected.startswith("point:"):
''',
    '''        if selected.startswith("vip_monthly:"):
            try:
                data["selected_vip_monthly_benefit_id"] = int(selected.split(":", 1)[1])
            except (TypeError, ValueError):
                await interaction.response.send_message("VIP 每月福利券格式錯誤，請重新選擇。", ephemeral=True)
                return
        elif selected.startswith("coupon:"):
            try:
                data["selected_benefit_coupon_id"] = int(selected.split(":", 1)[1])
            except (TypeError, ValueError):
                await interaction.response.send_message("福利券格式錯誤，請重新選擇。", ephemeral=True)
                return
        elif selected.startswith("point:"):
''',
)

replace_once(
    "services/self_service_selection_runtime.py",
    '''        self.selected_key = data.get("selected_point_benefit_key")
        self.selected_coupon_id = data.get("selected_benefit_coupon_id")
        self.point_balance = get_customer_point_balance_for_order(customer_id)
        self.available_items = self.build_available_items(data)
        from services.loyalty_benefits import list_applicable_coupons
        self.available_coupons = list_applicable_coupons(
''',
    '''        self.selected_key = data.get("selected_point_benefit_key")
        self.selected_coupon_id = data.get("selected_benefit_coupon_id")
        self.selected_vip_monthly_benefit_id = data.get("selected_vip_monthly_benefit_id")
        self.point_balance = get_customer_point_balance_for_order(customer_id)
        self.available_items = self.build_available_items(data)
        from services.loyalty_benefits import list_applicable_coupons
        from services.vip_monthly_benefits import list_available_cash_benefits
        self.available_vip_monthly_benefits = list_available_cash_benefits(customer_id)
        self.available_coupons = list_applicable_coupons(
''',
)

replace_once(
    "services/self_service_selection_runtime.py",
    '''        if data.get("selected_benefit_coupon_id"):
            coupon = next(
''',
    '''        if data.get("selected_vip_monthly_benefit_id"):
            monthly = next(
                (
                    item
                    for item in self.available_vip_monthly_benefits
                    if str(item.get("id")) == str(data.get("selected_vip_monthly_benefit_id"))
                ),
                None,
            )
            if monthly:
                selected_text = str(monthly.get("title") or "VIP 每月折現券")
        elif data.get("selected_benefit_coupon_id"):
            coupon = next(
''',
)

replace_once(
    "services/self_service_selection_runtime.py",
    '''            f"可用福利券：{len(self.available_coupons)} 張\\n"
''',
    '''            f"可用福利券：{len(self.available_vip_monthly_benefits) + len(self.available_coupons)} 張\\n"
''',
)

# 3) Treat monthly VIP cash vouchers as a store-funded fixed discount.
replace_once(
    "services/self_service_financials.py",
    '''    point_cash = max(
        0,
        min(
            point_cash,
            after_fixed,
        ),
    )

    allocation = allocate_store_absorbed_fixed_discount(
        after_percent_amount=after_percent,
        fixed_discount_amount=fixed,
        additional_store_discount_amount=point_cash,
        extra_customer_charge_amount=specify_effective,
    )

    from services.loyalty_benefits import (
''',
    '''    point_cash = max(
        0,
        min(
            point_cash,
            after_fixed,
        ),
    )

    selected_vip_monthly = None
    vip_monthly_cash = 0
    selected_vip_monthly_id = data.get("selected_vip_monthly_benefit_id")
    if selected_vip_monthly_id not in (None, ""):
        if benefit is not None:
            raise ValueError("VIP 每月福利券與點數福利同張訂單只能擇一使用。")
        customer_id = data.get("customer_id")
        if not customer_id:
            raise ValueError("無法確認 VIP 每月福利券的會員身分，請重新開啟福利選單。")
        from services.vip_monthly_benefits import get_available_cash_benefit
        selected_vip_monthly = get_available_cash_benefit(
            selected_vip_monthly_id,
            customer_id=customer_id,
        )
        if selected_vip_monthly is None:
            raise ValueError("這張 VIP 每月折現券已使用、已保留或已失效。")
        vip_monthly_cash = max(
            0,
            min(
                int(selected_vip_monthly.get("amount") or 0),
                after_fixed,
            ),
        )

    allocation = allocate_store_absorbed_fixed_discount(
        after_percent_amount=after_percent,
        fixed_discount_amount=fixed,
        additional_store_discount_amount=point_cash + vip_monthly_cash,
        extra_customer_charge_amount=specify_effective,
    )

    from services.loyalty_benefits import (
''',
)

replace_once(
    "services/self_service_financials.py",
    '''    if selected_coupon_id not in (None, ""):
        if benefit is not None:
            raise ValueError("福利券與點數福利同張訂單只能擇一使用。")
''',
    '''    if selected_coupon_id not in (None, ""):
        if benefit is not None or selected_vip_monthly is not None:
            raise ValueError("福利券、VIP 每月福利券與點數福利同張訂單只能擇一使用。")
''',
)

replace_once(
    "services/self_service_financials.py",
    '''    if point_specify:
        notes.append(
            "免指定費 "
            f"-{_format_plain_amount(point_specify)}"
        )

    # service_promotion_calc_v1
''',
    '''    if point_specify:
        notes.append(
            "免指定費 "
            f"-{_format_plain_amount(point_specify)}"
        )

    if vip_monthly_cash:
        notes.append(
            f"{str(selected_vip_monthly.get('title') or 'VIP 每月折現券')} "
            f"-{_format_plain_amount(vip_monthly_cash)}"
        )

    # service_promotion_calc_v1
''',
)

replace_once(
    "services/self_service_financials.py",
    '''        "point_discount_coupon_amount": (
            point_cash
        ),

        "specified_fee_before_waiver": (
''',
    '''        "point_discount_coupon_amount": (
            point_cash
        ),

        "vip_monthly_benefit_id": (
            int(selected_vip_monthly.get("id")) if selected_vip_monthly else None
        ),
        "vip_monthly_benefit_key": (
            str(selected_vip_monthly.get("benefit_key") or "") if selected_vip_monthly else ""
        ),
        "vip_monthly_benefit_title": (
            str(selected_vip_monthly.get("title") or "") if selected_vip_monthly else ""
        ),
        "vip_monthly_cash_amount": vip_monthly_cash,

        "specified_fee_before_waiver": (
''',
)

# 4) Bind the reservation when a self-service order is created.
replace_once(
    "services/self_service_runtime.py",
    '''    data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(channel_id, {})

    if data.get("dispatch_message_id") is not None:
''',
    '''    data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(channel_id, {})
    data["customer_id"] = int(customer_id)

    if data.get("dispatch_message_id") is not None:
''',
)

replace_once(
    "services/self_service_runtime.py",
    '''        "point_discount_coupon_amount": price_adjustment.get("point_discount_coupon_amount"),
        "point_waived_specify_fee": price_adjustment.get("point_waived_specify_fee"),
''',
    '''        "point_discount_coupon_amount": price_adjustment.get("point_discount_coupon_amount"),
        "vip_monthly_benefit_id": price_adjustment.get("vip_monthly_benefit_id"),
        "vip_monthly_benefit_key": price_adjustment.get("vip_monthly_benefit_key"),
        "vip_monthly_benefit_title": price_adjustment.get("vip_monthly_benefit_title"),
        "vip_monthly_cash_amount": price_adjustment.get("vip_monthly_cash_amount"),
        "point_waived_specify_fee": price_adjustment.get("point_waived_specify_fee"),
''',
)

replace_once(
    "services/self_service_runtime.py",
    '''    if price_adjustment.get("benefit_coupon_title"):
        benefit_note = str(price_adjustment.get("benefit_service_note") or "").strip()
        web_note_parts.append(
            "會員福利："
            f"{price_adjustment['benefit_coupon_title']}"
            + (f"｜{benefit_note}" if benefit_note else "")
        )

    # service_promotion_web_note_v1
''',
    '''    if price_adjustment.get("benefit_coupon_title"):
        benefit_note = str(price_adjustment.get("benefit_service_note") or "").strip()
        web_note_parts.append(
            "會員福利："
            f"{price_adjustment['benefit_coupon_title']}"
            + (f"｜{benefit_note}" if benefit_note else "")
        )

    if price_adjustment.get("vip_monthly_benefit_title"):
        web_note_parts.append(
            "VIP 月福利："
            f"{price_adjustment['vip_monthly_benefit_title']}"
            f"｜折抵 {int(price_adjustment.get('vip_monthly_cash_amount') or 0)}T"
        )

    # service_promotion_web_note_v1
''',
)

replace_once(
    "services/self_service_runtime.py",
    '''    if price_adjustment.get("benefit_coupon_id"):
        from services.loyalty_benefits import reserve_coupon_for_order
        reserve_coupon_for_order(
            coupon_id=int(price_adjustment["benefit_coupon_id"]),
            customer_id=customer_id,
            order_id=int(web_order.id),
            rule_key=str(rule.key),
            player_count=player_count,
        )

    try:
''',
    '''    if price_adjustment.get("benefit_coupon_id"):
        from services.loyalty_benefits import reserve_coupon_for_order
        reserve_coupon_for_order(
            coupon_id=int(price_adjustment["benefit_coupon_id"]),
            customer_id=customer_id,
            order_id=int(web_order.id),
            rule_key=str(rule.key),
            player_count=player_count,
        )

    if price_adjustment.get("vip_monthly_benefit_id"):
        from services.vip_monthly_benefits import reserve_cash_benefit_for_channel
        reserve_cash_benefit_for_channel(
            benefit_id=int(price_adjustment["vip_monthly_benefit_id"]),
            customer_id=customer_id,
            channel_id=interaction.channel.id,
        )

    try:
''',
)

# 5) Finalize/release the monthly cash voucher with the canonical order lifecycle.
replace_once(
    "shared/web_order_sync.py",
    '''def update_web_order_status_by_ticket_channel(
''',
    '''def _sync_vip_monthly_cash_benefit_lifecycle(ticket_channel_id: str, status: str) -> None:
    if status not in {"closed", "cancelled"}:
        return
    try:
        if status == "closed":
            from services.vip_monthly_benefits import redeem_cash_benefits_for_channel
            redeem_cash_benefits_for_channel(ticket_channel_id)
        else:
            from services.vip_monthly_benefits import release_cash_benefits_for_channel
            release_cash_benefits_for_channel(ticket_channel_id)
    except Exception as exc:
        print(
            f"[vip-monthly] lifecycle sync failed channel={ticket_channel_id} status={status}: "
            f"{type(exc).__name__}: {exc}",
            flush=True,
        )


def update_web_order_status_by_ticket_channel(
''',
)

replace_once(
    "shared/web_order_sync.py",
    '''        db.commit()
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# --- Discord claim -> Web dashboard sync ---------------------------------
''',
    '''        db.commit()
        _sync_vip_monthly_cash_benefit_lifecycle(ticket_channel_id_text, next_status)
        return True
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

# --- Discord claim -> Web dashboard sync ---------------------------------
''',
)

# 6) Individual payout notification: support the actual canonical audit snapshot.
replace_once(
    "web/app/services/payout_notifications.py",
    '''    worker, cs = _role_targets(after_data.get("person_role"))
    changed = 0
''',
    '''    totals = dict((before or {}).get("totals") or {})
    if "unpaid_count" in totals:
        try:
            return int(totals.get("unpaid_count") or 0) > 0
        except (TypeError, ValueError):
            return False

    worker, cs = _role_targets(after_data.get("person_role"))
    changed = 0
''',
)

# 7) Regression tests.
replace_once(
    "tests/test_vip_monthly_benefits.py",
    '''    REVOKED,
    get_customer_vip_monthly_snapshot,
''',
    '''    REVOKED,
    get_customer_vip_monthly_snapshot,
    list_available_cash_benefits,
    redeem_cash_benefits_for_channel,
    release_cash_benefits_for_channel,
    reserve_cash_benefit_for_channel,
''',
)

with Path("tests/test_vip_monthly_benefits.py").open("a", encoding="utf-8") as fh:
    fh.write(r'''


def test_monthly_cash_benefit_reserve_release_and_redeem_by_channel(tmp_path):
    bot_db = tmp_path / "bot.db"
    web_db = tmp_path / "web_dashboard.db"
    customer_id = "monthly-cash-user"
    _make_bot_db(
        bot_db,
        [(
            customer_id,
            {
                "total_spent": 30000,
                "vip_level_index": 3,
                "last_order_at": "2026-11-05T10:00:00+08:00",
            },
        )],
    )
    now = datetime(2026, 11, 5, 12, tzinfo=TAIPEI_TZ)

    available = list_available_cash_benefits(
        customer_id,
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert len(available) == 1
    assert available[0]["benefit_key"] == MONTHLY_COUPON_200
    assert available[0]["amount"] == 200

    benefit_id = available[0]["id"]
    reserved = reserve_cash_benefit_for_channel(
        benefit_id=benefit_id,
        customer_id=customer_id,
        channel_id="ticket-1",
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert reserved["status"] == "reserved"
    assert reserved["reserved_channel_id"] == "ticket-1"

    with pytest.raises(ValueError, match="已使用、已保留或已失效"):
        reserve_cash_benefit_for_channel(
            benefit_id=benefit_id,
            customer_id=customer_id,
            channel_id="ticket-2",
            now=now,
            bot_db=bot_db,
            web_db=web_db,
        )

    assert release_cash_benefits_for_channel(
        "ticket-1",
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    ) == 1
    assert list_available_cash_benefits(
        customer_id,
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )[0]["id"] == benefit_id

    reserve_cash_benefit_for_channel(
        benefit_id=benefit_id,
        customer_id=customer_id,
        channel_id="ticket-3",
        now=now,
        bot_db=bot_db,
        web_db=web_db,
    )
    assert redeem_cash_benefits_for_channel(
        "ticket-3",
        now=now,
        web_db=web_db,
    ) == 1
    assert list_available_cash_benefits(
        customer_id,
        now=now,
        bot_db=bot_db,
        web_db=web_db,
        ensure_synced=False,
    ) == []
''')

with Path("tests/test_self_service_financial_runtime_contract.py").open("a", encoding="utf-8") as fh:
    fh.write(r'''


def test_vip_monthly_cash_coupon_is_wired_as_store_absorbed_self_service_discount():
    selection = (ROOT / "services" / "self_service_selection_runtime.py").read_text(encoding="utf-8")
    financial = (ROOT / "services" / "self_service_financials.py").read_text(encoding="utf-8")
    runtime = (ROOT / "services" / "self_service_runtime.py").read_text(encoding="utf-8")
    lifecycle = (ROOT / "shared" / "web_order_sync.py").read_text(encoding="utf-8")

    assert 'list_available_cash_benefits(customer_id)' in selection
    assert 'value=f"vip_monthly:{benefit[\'id\']}"' in selection
    assert 'selected_vip_monthly_benefit_id' in selection
    assert 'additional_store_discount_amount=point_cash + vip_monthly_cash' in financial
    assert 'vip_monthly_cash_amount' in financial
    assert 'reserve_cash_benefit_for_channel' in runtime
    assert '_sync_vip_monthly_cash_benefit_lifecycle' in lifecycle
    assert 'redeem_cash_benefits_for_channel' in lifecycle
    assert 'release_cash_benefits_for_channel' in lifecycle
''')

replace_once(
    "tests/test_payout_notifications.py",
    '''def test_paid_notification_is_skipped_when_nothing_was_unpaid_before():
''',
    '''def test_individual_paid_notification_accepts_canonical_payout_summary_snapshot():
    before = {
        "month": "2026-10",
        "role": "worker",
        "person_id": "123",
        "totals": {
            "person_count": 1,
            "unpaid_total": 800,
            "unpaid_count": 2,
            "paid_total": 0,
            "paid_count": 0,
        },
        "people": [],
    }
    after = {"target_status": "paid", "person_role": "worker"}
    assert payout_notifications.should_send_payout_paid_notification(before=before, after=after) is True

    before["totals"]["unpaid_count"] = 0
    assert payout_notifications.should_send_payout_paid_notification(before=before, after=after) is False


def test_paid_notification_is_skipped_when_nothing_was_unpaid_before():
''',
)
