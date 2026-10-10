from __future__ import annotations

from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, text: str) -> None:
    target = ROOT / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(text, encoding="utf-8")


def replace(path: str, old: str, new: str, *, count: int = 1) -> None:
    text = read(path)
    found = text.count(old)
    if found != count:
        raise RuntimeError(f"{path}: expected {count} occurrence(s), found {found}: {old[:100]!r}")
    write(path, text.replace(old, new, count))


def insert_after(path: str, needle: str, addition: str) -> None:
    text = read(path)
    if needle not in text:
        raise RuntimeError(f"{path}: insertion needle not found: {needle[:100]!r}")
    if addition in text:
        return
    write(path, text.replace(needle, needle + addition, 1))


def patch_order_rules() -> None:
    path = "services/order_rules.py"
    replace(
        path,
        "    service_bonus_buy: int | None = None\n    service_bonus_gift: int = 0\n",
        "    # Legacy same-order buy/get fields remain for historical/custom-rule snapshots.\n"
        "    # Current built-in products no longer use them.\n"
        "    service_bonus_buy: int | None = None\n    service_bonus_gift: int = 0\n"
        "    # Cross-order customer loyalty progress. Zero/None means disabled.\n"
        "    loyalty_threshold_units: float | None = None\n    loyalty_reward_units: float = 0\n",
    )
    replace(
        path,
        '    "service_bonus_buy",\n    "service_bonus_gift",\n',
        '    "service_bonus_buy",\n    "service_bonus_gift",\n    "loyalty_threshold_units",\n    "loyalty_reward_units",\n',
    )

    # Delta absolute-bar technical service.
    replace(
        path,
        "    service_bonus_buy=5,\n    service_bonus_gift=1,\n    note=\"保底三選一：800w / 500w + 2 沙色保險 / 4 沙色保險\",\n",
        "    loyalty_threshold_units=10,\n    loyalty_reward_units=0.5,\n    note=\"保底三選一：800w / 500w + 2 沙色保險 / 4 沙色保險\",\n",
    )
    # Delta entertainment loop.
    replace(
        path,
        "        service_bonus_buy=5,\n        service_bonus_gift=1,\n    ))\n\n# 舊甜蜜單規則",
        "        loyalty_threshold_units=10,\n        loyalty_reward_units=0.5,\n    ))\n\n# 舊甜蜜單規則",
    )

    # Remove the three legacy Valorant active rules. Historical web orders keep snapshots.
    text = read(path)
    start_marker = "# ========= 特戰英豪 陪玩 =========\n"
    end_marker = "# ========= 特戰英豪 / 英雄聯盟新制陪玩 =========\n"
    start = text.find(start_marker)
    end = text.find(end_marker)
    if start < 0 or end < 0 or end <= start:
        raise RuntimeError("services/order_rules.py: legacy Valorant block markers not found")
    legacy = text[start:end]
    required_old = ("valorant_entertain", "valorant_tech", "valorant_top_tech")
    if not all(key in legacy for key in required_old):
        raise RuntimeError("services/order_rules.py: legacy Valorant block did not contain expected rules")
    replacement = (
        "# ========= 特戰英豪舊制 =========\n"
        "# 舊 valorant_entertain / valorant_tech / valorant_top_tech 已從 active rules 移除。\n"
        "# 歷史訂單使用建立當下的 rule_snapshot_json / price_snapshot_json 回查。\n\n"
    )
    write(path, text[:start] + replacement + text[end:])

    # New Valorant / LoL helper: hourly 10h -> .5h, game 20 -> 1 game.
    replace(
        path,
        "        point_benefits_allowed=True,\n        service_bonus_buy=5,\n        service_bonus_gift=1,\n    ))\n\n\n_add_game_service_rule",
        "        point_benefits_allowed=True,\n"
        "        loyalty_threshold_units=(10 if pricing_type == \"hourly\" else 20),\n"
        "        loyalty_reward_units=(0.5 if pricing_type == \"hourly\" else 1),\n"
        "    ))\n\n\n_add_game_service_rule",
    )
    # Apex helper.
    replace(
        path,
        "        point_benefits_allowed=True,\n        service_bonus_buy=5,\n        service_bonus_gift=1,\n    ))\n\n\n_APEX_SERVICE_SPECS",
        "        point_benefits_allowed=True,\n"
        "        loyalty_threshold_units=10,\n"
        "        loyalty_reward_units=0.5,\n"
        "    ))\n\n\n_APEX_SERVICE_SPECS",
    )


def patch_loyalty_service() -> None:
    path = "services/loyalty_benefits.py"
    text = read(path)
    if "def restore_coupon(" not in text:
        marker = "\ndef record_paid_service(\n"
        addition = textwrap.dedent('''
        def restore_coupon(
            coupon_id: int,
            *,
            customer_id: str | int | None = None,
            db_file: str | Path | None = None,
        ) -> bool:
            """Return a reserved/used loyalty coupon after an order cancellation."""
            ensure_loyalty_tables(db_file)
            params: list[Any] = [int(coupon_id)]
            sql = (
                "UPDATE loyalty_coupons "
                "SET status='available', reservation_key=NULL, reserved_at=NULL, "
                "used_order_key=NULL, used_at=NULL "
                "WHERE id=? AND status IN ('reserved','used')"
            )
            if customer_id is not None:
                sql += " AND customer_discord_id=?"
                params.append(str(customer_id))
            with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
                result = conn.execute(sql, params)
                conn.commit()
                return int(result.rowcount or 0) == 1

        ''')
        if marker not in text:
            raise RuntimeError("services/loyalty_benefits.py: record marker missing")
        text = text.replace(marker, "\n" + addition + "def record_paid_service(\n", 1)
        write(path, text)


def patch_staff_profile_archive() -> None:
    path = "views/staff_profiles.py"
    old = '''    channel = await _ensure_profile_thread_open_for_refresh(\n        channel,\n        staff_id=staff_id,\n    )\n\n    if channel is None or not hasattr(channel, "fetch_message"):\n        return False\n\n    try:\n        panel_message = await channel.fetch_message(panel_message_id)\n    except (discord.NotFound, discord.Forbidden, discord.HTTPException):\n        return False\n\n    view = StaffProfilePanelView(staff_id)\n    embed = build_staff_profile_embed(profile)\n\n    try:\n        await panel_message.edit(\n            embed=embed,\n            view=view,\n            allowed_mentions=discord.AllowedMentions(\n                users=False,\n                roles=False,\n                everyone=False,\n            ),\n        )\n    except (discord.Forbidden, discord.HTTPException):\n        return False\n\n    return True\n'''
    new = '''    was_archived = bool(getattr(channel, "archived", False))\n    channel = await _ensure_profile_thread_open_for_refresh(\n        channel,\n        staff_id=staff_id,\n    )\n\n    if channel is None or not hasattr(channel, "fetch_message"):\n        return False\n\n    try:\n        try:\n            panel_message = await channel.fetch_message(panel_message_id)\n        except (discord.NotFound, discord.Forbidden, discord.HTTPException):\n            return False\n\n        view = StaffProfilePanelView(staff_id)\n        embed = build_staff_profile_embed(profile)\n\n        try:\n            await panel_message.edit(\n                embed=embed,\n                view=view,\n                allowed_mentions=discord.AllowedMentions(\n                    users=False,\n                    roles=False,\n                    everyone=False,\n                ),\n            )\n        except (discord.Forbidden, discord.HTTPException):\n            return False\n\n        return True\n    finally:\n        # Background refresh must not leave an archived personal-wall thread active.\n        # Threads that were already active stay active so real conversations are not interrupted.\n        if was_archived and bool(getattr(channel, "archived", False)) is False:\n            edit_channel = getattr(channel, "edit", None)\n            if callable(edit_channel):\n                try:\n                    await edit_channel(\n                        archived=True,\n                        reason=f"Staff profile refresh complete: {int(staff_id)}",\n                    )\n                except (discord.Forbidden, discord.HTTPException):\n                    pass\n'''
    replace(path, old, new)

    test_path = "tests/test_staff_profile_archived_thread_refresh.py"
    text = read(test_path)
    text = text.replace(
        "test_archived_public_profile_thread_is_reopened_and_left_active",
        "test_archived_public_profile_thread_is_reopened_then_rearchived",
    )
    text = text.replace("assert thread.edit_calls == [False]", "assert thread.edit_calls == [False, True]")
    text = text.replace("assert thread.archived is False", "assert thread.archived is True", 1)
    write(test_path, text)


def patch_checkout_preview() -> None:
    path = "web/app/services/checkout_preview.py"
    # Full list-price value, not VIP discounted value, funds worker payout for free service.
    old = '''    quantity = max(1, int(quote.get("quantity") or 1))\n    service_amount = max(0, int(quote.get("customer_pay_amount") or 0))\n    gross_extra_value = int(round((service_amount / quantity) * units))\n    rate = max(0, min(100, int(vip_pay_rate or 100)))\n    return max(0, int(round(gross_extra_value * rate / 100)))\n'''
    new = '''    quantity = max(1, int(quote.get("quantity") or 1))\n    service_amount = max(0, int(quote.get("customer_pay_amount") or 0))\n    gross_extra_value = int(round((service_amount / quantity) * units))\n    # VIP discount only affects what the customer pays for purchased service.\n    # Free service promised by the store is funded at the original unit value.\n    return max(0, gross_extra_value)\n\n\ndef calculate_loyalty_service_value(\n    *,\n    quote: dict,\n    loyalty_item: dict | None,\n) -> int:\n    if not loyalty_item:\n        return 0\n    units = float(loyalty_item.get("reward_units") or 0)\n    if units <= 0:\n        return 0\n    quantity = max(1, int(quote.get("quantity") or 1))\n    service_amount = max(0, int(quote.get("customer_pay_amount") or 0))\n    return max(0, int(round((service_amount / quantity) * units)))\n'''
    replace(path, old, new)

    # Add loyalty parameters and funding to finance helper.
    replace(
        path,
        "    point_service_value: int = 0,\n) -> dict:\n",
        "    point_service_value: int = 0,\n    loyalty_item: dict | None = None,\n    loyalty_service_value: int = 0,\n) -> dict:\n",
    )
    replace(
        path,
        "    point_service_value = max(0, int(point_service_value or 0))\n",
        "    point_service_value = max(0, int(point_service_value or 0))\n    loyalty_service_value = max(0, int(loyalty_service_value or 0))\n",
    )
    replace(
        path,
        "    effective_specify_fee = max(0, specify_fee - point_waived_specify)\n",
        '''    loyalty_service_note = ""\n    if loyalty_item:\n        pricing_type = str(loyalty_item.get("pricing_type") or "")\n        units = float(loyalty_item.get("reward_units") or 0)\n        if pricing_type == "hourly":\n            loyalty_service_note = (\n                "累積福利：服務時間 +30 分鐘"\n                if units == 0.5\n                else f"累積福利：服務時間 +{units:g} 小時"\n            )\n        elif pricing_type == "game":\n            loyalty_service_note = f"累積福利：服務局數 +{units:g} 局"\n\n    effective_specify_fee = max(0, specify_fee - point_waived_specify)\n''',
    )
    replace(
        path,
        "    payout_base = max(0, after_vip + specify_fee + point_service_value)\n",
        "    payout_base = max(0, after_vip + specify_fee + point_service_value + loyalty_service_value)\n",
    )
    replace(
        path,
        "        point_cash_discount + point_waived_specify + point_service_value,\n",
        "        point_cash_discount + point_waived_specify + point_service_value + loyalty_service_value,\n",
    )
    replace(
        path,
        '        "point_service_value": point_service_value,\n',
        '        "point_service_value": point_service_value,\n        "loyalty_service_note": loyalty_service_note,\n        "loyalty_service_value": loyalty_service_value,\n',
    )

    # Options response includes only exact rule/player-count coupons.
    insert_after(
        path,
        "    point_options = (\n        list_point_options(\n            rule_key=\n                rule_key,\n\n            point_balance=\n                customer[\n                    \"points\"\n                ],\n\n            quantity=\n                int(\n                    quote[\n                        \"quantity\"\n                    ]\n                ),\n\n            has_specified_staff=\n                bool(\n                    preselected_staff\n                ),\n        )\n    )\n",
        '''\n\n    from services.loyalty_benefits import list_available_coupons\n\n    benefit_options = list_available_coupons(\n        customer_id,\n        rule_key=str(rule_key),\n        player_count=int(quote.get("player_count") or player_count or 1),\n    )\n''',
    )
    replace(
        path,
        "        \"point_options\":\n            point_options,\n\n        \"payment_methods\":\n",
        "        \"point_options\":\n            point_options,\n\n        \"benefit_options\":\n            benefit_options,\n\n        \"payment_methods\":\n",
    )

    replace(
        path,
        "    point_item_key: str | None = None,\n    use_wallet: bool = False,\n",
        "    point_item_key: str | None = None,\n    benefit_coupon_id: int | None = None,\n    use_wallet: bool = False,\n",
    )

    # Validate loyalty coupon after point selection, before finance calculation.
    marker = "\n\n    finance = (\n        calculate_checkout_financials(\n"
    addition = '''\n\n    selected_loyalty_item = None\n    if benefit_coupon_id not in (None, ""):\n        from services.loyalty_benefits import validate_coupon_for_order\n\n        selected_loyalty_item = validate_coupon_for_order(\n            int(benefit_coupon_id),\n            customer_id=customer_id,\n            rule_key=str(rule_key),\n            player_count=int(quote.get("player_count") or player_count or 1),\n            allow_reserved=True,\n        )\n\n        if selected_point_item and str(selected_point_item.get("kind") or "") in {\n            "extra_hours",\n            "extra_games",\n        }:\n            raise ValueError("累積加時／加局券不能和點數加時／加局同張訂單使用。")\n'''
    text = read(path)
    if marker not in text:
        raise RuntimeError("checkout preview finance marker missing")
    text = text.replace(marker, addition + marker, 1)
    write(path, text)

    replace(
        path,
        "            point_service_value=\n                calculate_point_service_value(\n                    quote=quote,\n                    vip_pay_rate=vip_rate,\n                    point_item=selected_point_item,\n                ),\n\n            wallet_balance=\n",
        "            point_service_value=\n                calculate_point_service_value(\n                    quote=quote,\n                    vip_pay_rate=vip_rate,\n                    point_item=selected_point_item,\n                ),\n\n            loyalty_item=selected_loyalty_item,\n            loyalty_service_value=calculate_loyalty_service_value(\n                quote=quote,\n                loyalty_item=selected_loyalty_item,\n            ),\n\n            wallet_balance=\n",
    )

    replace(
        path,
        "        \"finance\":\n            finance,\n",
        '''        "loyalty": {\n            "id": int(selected_loyalty_item["id"]) if selected_loyalty_item else None,\n            "name": str(selected_loyalty_item.get("display_name") or "") if selected_loyalty_item else "",\n            "rule_key": str(selected_loyalty_item.get("rule_key") or "") if selected_loyalty_item else None,\n            "player_count": int(selected_loyalty_item.get("player_count") or 1) if selected_loyalty_item else None,\n            "pricing_type": str(selected_loyalty_item.get("pricing_type") or "") if selected_loyalty_item else None,\n            "reward_units": float(selected_loyalty_item.get("reward_units") or 0) if selected_loyalty_item else 0,\n        },\n\n        "finance":\n            finance,\n''',
    )

    # Old rules are no longer active; remove stale direct-order exclusion names.
    replace(
        path,
        '    "valorant_entertain",\n    "valorant_tech",\n    "valorant_top_tech",\n',
        "",
    )


def patch_site_and_public_order_create() -> None:
    path = "web/app/routers/site.py"
    # Member hub snapshot.
    replace(
        path,
        "    portal = build_customer_portal_snapshot(\n        customer_id,\n        guild_id=config.DISCORD_GUILD_ID,\n    )\n\n    return templates.TemplateResponse(\n        request=request,\n        name=\"member_center.html\",\n",
        "    portal = build_customer_portal_snapshot(\n        customer_id,\n        guild_id=config.DISCORD_GUILD_ID,\n    )\n\n    from services.loyalty_benefits import get_customer_benefit_snapshot\n    benefits = get_customer_benefit_snapshot(customer_id)\n\n    return templates.TemplateResponse(\n        request=request,\n        name=\"member_center.html\",\n",
    )
    replace(
        path,
        "            member=member,\n            portal=portal,\n",
        "            member=member,\n            portal=portal,\n            benefits=benefits,\n",
        count=1,
    )
    # Preview route passes coupon id.
    replace(
        path,
        "            point_item_key=\n                payload.get(\n                    \"point_item_key\"\n                ),\n\n            use_wallet=\n",
        "            point_item_key=\n                payload.get(\n                    \"point_item_key\"\n                ),\n\n            benefit_coupon_id=\n                payload.get(\n                    \"benefit_coupon_id\"\n                ),\n\n            use_wallet=\n",
        count=1,
    )

    # Reserve website coupon after formal order has an ID, before DB commit.
    marker = "        order_id = int(\n            order.id\n        )\n\n\n        accepted_at = (\n"
    addition = '''        order_id = int(\n            order.id\n        )\n\n        selected_benefit_coupon_id = order_payload.get("benefit_coupon_id")\n        if selected_benefit_coupon_id not in (None, ""):\n            from services.loyalty_benefits import reserve_coupon\n            reserve_coupon(\n                int(selected_benefit_coupon_id),\n                customer_id=customer_id,\n                rule_key=str(order_payload.get("rule_key") or ""),\n                player_count=int(order_payload.get("player_count") or 1),\n                reservation_key=f"WEB-{order_id}",\n            )\n\n\n        accepted_at = (\n'''
    replace(path, marker, addition)

    # If order creation transaction fails after reservation, return reserved coupon.
    replace(
        path,
        "    except ValueError as exc:\n\n        db.rollback()\n",
        '''    except ValueError as exc:\n\n        db.rollback()\n        try:\n            coupon_id = order_payload.get("benefit_coupon_id") if "order_payload" in locals() else None\n            if coupon_id not in (None, ""):\n                from services.loyalty_benefits import release_coupon\n                release_coupon(int(coupon_id), customer_id=customer_id)\n        except Exception:\n            pass\n''',
    )
    replace(
        path,
        "    except Exception as exc:\n\n        db.rollback()\n",
        '''    except Exception as exc:\n\n        db.rollback()\n        try:\n            coupon_id = order_payload.get("benefit_coupon_id") if "order_payload" in locals() else None\n            if coupon_id not in (None, ""):\n                from services.loyalty_benefits import release_coupon\n                release_coupon(int(coupon_id), customer_id=customer_id)\n        except Exception:\n            pass\n''',
    )

    # Formal preview signature forwarding.
    path = "web/app/services/public_order_create.py"
    replace(
        path,
        "        \"point_item_key\":\n            payload.get(\n                \"point_item_key\"\n            )\n            or None,\n\n        \"use_wallet\":\n",
        "        \"point_item_key\":\n            payload.get(\n                \"point_item_key\"\n            )\n            or None,\n\n        \"benefit_coupon_id\":\n            payload.get(\n                \"benefit_coupon_id\"\n            )\n            or None,\n\n        \"use_wallet\":\n",
    )


def patch_website_templates_and_js() -> None:
    # Account menu: customer navigation goes through /me hub.
    path = "web/app/templates/site_layout.html"
    text = read(path)
    for block in (
        '''\n                            <a href="/me/orders">\n                                我的訂單\n                            </a>\n\n                            <a href="/me#favorites">\n                                我的收藏\n                            </a>\n\n                            <a href="/me#vip">\n                                點數 / VIP\n                            </a>\n''',
        '''\n                <a href="/me/orders">我的訂單</a>\n''',
    ):
        if block in text:
            text = text.replace(block, "\n", 1)
    write(path, text)

    # Member hub adds benefit stat and panel.
    path = "web/app/templates/member_center.html"
    text = read(path)
    stat_marker = '''        <article class="member-stat-card">\n            <small>\n                ORDERS\n            </small>\n'''
    benefit_stat = '''        <article class="member-stat-card">\n            <small>\n                BENEFITS\n            </small>\n\n            <strong>\n                {{ benefits.available_count }}\n            </strong>\n\n            <span>\n                目前可用福利券\n            </span>\n\n            <a\n                href="#benefits"\n                class="button button-primary"\n                style="min-height:34px;padding:0 14px;margin-top:14px;border-radius:10px;font-size:12px;"\n            >\n                查看我的福利\n            </a>\n        </article>\n\n\n'''
    if stat_marker not in text:
        raise RuntimeError("member_center: stat marker missing")
    text = text.replace(stat_marker, benefit_stat + stat_marker, 1)

    panel_marker = '''        <section\n            class="member-panel member-panel-wide"\n            id="vip"\n        >\n'''
    benefit_panel = '''        <section\n            class="member-panel member-panel-wide"\n            id="benefits"\n        >\n            <div class="member-panel-head">\n                <div>\n                    <small>LOYALTY BENEFITS</small>\n                    <h3>我的福利</h3>\n                </div>\n                <span style="opacity:.65;font-size:12px;">2026/10/10 起累積</span>\n            </div>\n\n            {% if benefits.coupons %}\n                <div class="member-order-list">\n                    {% for coupon in benefits.coupons %}\n                        <div class="member-order-row">\n                            <div>\n                                <small>AVAILABLE</small>\n                                <strong>{{ coupon.display_name }}</strong>\n                                <span>下次點同商品、同人數規格時可使用；可重新選陪玩。</span>\n                            </div>\n                            <div class="member-order-meta"><strong>可用</strong></div>\n                        </div>\n                    {% endfor %}\n                </div>\n            {% endif %}\n\n            {% if benefits.progress %}\n                <div class="member-order-list" style="margin-top:14px;">\n                    {% for item in benefits.progress %}\n                        <div class="member-order-row">\n                            <div>\n                                <small>PROGRESS</small>\n                                <strong>{{ item.label }}</strong>\n                                <span>\n                                    已累積 {{ "%g"|format(item.paid_units) }} / {{ "%g"|format(item.threshold_units) }} {{ item.unit_label }}\n                                    ・達標送 {{ item.reward_label }}\n                                </span>\n                            </div>\n                        </div>\n                    {% endfor %}\n                </div>\n            {% endif %}\n\n            {% if not benefits.coupons and not benefits.progress %}\n                <div class="member-empty">\n                    <span class="member-empty-icon">◇</span>\n                    <strong>目前還沒有累積福利</strong>\n                    <p>完成符合活動的付費服務後，這裡才會開始顯示進度，不會列出 0 進度品項。</p>\n                </div>\n            {% endif %}\n        </section>\n\n\n'''
    if panel_marker not in text:
        raise RuntimeError("member_center: vip panel marker missing")
    text = text.replace(panel_marker, benefit_panel + panel_marker, 1)
    write(path, text)

    # Checkout cumulative benefit select.
    path = "web/app/templates/order_catalog.html"
    text = read(path)
    point_control_end = '''                </label>\n\n\n                <label class="order-checkout-control" hidden aria-hidden="true" data-web-payment-hidden="1" style="display:none !important;">\n'''
    loyalty_control = '''                </label>\n\n\n                <label class="order-checkout-control">\n                    <span>累積福利</span>\n                    <select id="mw-checkout-benefit">\n                        <option value="">不使用累積福利</option>\n                    </select>\n                    <small id="mw-checkout-benefit-note">\n                        只有已持有、且符合目前商品與人數規格的福利才會顯示\n                    </small>\n                </label>\n\n\n                <label class="order-checkout-control" hidden aria-hidden="true" data-web-payment-hidden="1" style="display:none !important;">\n'''
    if point_control_end not in text:
        raise RuntimeError("order_catalog: point control marker missing")
    text = text.replace(point_control_end, loyalty_control, 1)
    text = text.replace("確認指定人員、點數福利與附加需求後，", "確認指定人員、點數／累積福利與附加需求後，", 1)
    # Force updated client JS.
    text = text.replace("/static/js/mw_order_quote.js", "/static/js/mw_order_quote.js?v=loyalty-20261010", 1)
    write(path, text)

    # JS: benefit selector participates in options, previews and formal payload.
    path = "web/app/static/js/mw_order_quote.js"
    text = read(path)
    text = text.replace(
        'const pointSelect = document.querySelector("#mw-checkout-point");',
        'const pointSelect = document.querySelector("#mw-checkout-point");\n    const benefitSelect = document.querySelector("#mw-checkout-benefit");\n    const benefitNote = document.querySelector("#mw-checkout-benefit-note");',
        1,
    )
    # Locate renderPointOptions and append sibling before next known function.
    marker = "\n    function renderStaffOptions"
    if marker not in text:
        raise RuntimeError("mw_order_quote.js: renderStaffOptions marker missing")
    benefit_function = '''\n    function renderBenefitOptions(items) {\n        if (!benefitSelect) return;\n        const previous = String(benefitSelect.value || "");\n        benefitSelect.innerHTML = '<option value="">不使用累積福利</option>';\n        (Array.isArray(items) ? items : []).forEach((item) => {\n            const option = document.createElement("option");\n            option.value = String(item.id || "");\n            option.textContent = String(item.display_name || item.benefit_label || "累積福利");\n            benefitSelect.appendChild(option);\n        });\n        if ([...benefitSelect.options].some((option) => option.value === previous)) {\n            benefitSelect.value = previous;\n        } else {\n            benefitSelect.value = "";\n        }\n        if (benefitNote) {\n            benefitNote.textContent = items && items.length\n                ? `目前有 ${items.length} 張符合這個方案的累積福利券`\n                : "目前沒有符合這個商品與人數規格的累積福利券";\n        }\n    }\n'''
    text = text.replace(marker, benefit_function + marker, 1)

    # Whenever options data renders points, render benefits too.
    point_render = "renderPointOptions(data.point_options || []);"
    if point_render not in text:
        raise RuntimeError("mw_order_quote.js: point options render missing")
    text = text.replace(point_render, point_render + "\n            renderBenefitOptions(data.benefit_options || []);", 1)

    # Add preview/formal payload key after point item key occurrences.
    text = text.replace(
        "point_item_key: pointSelect ? (pointSelect.value || null) : null,",
        "point_item_key: pointSelect ? (pointSelect.value || null) : null,\n            benefit_coupon_id: benefitSelect && benefitSelect.value ? Number(benefitSelect.value) : null,",
    )

    # Reset / selection change hooks.
    if "if (pointSelect)" in text:
        hook = '''\n    if (benefitSelect) {\n        benefitSelect.addEventListener("change", () => {\n            refreshCheckoutPreview();\n        });\n    }\n'''
        # Insert once before the first point change hook.
        first = text.find("    if (pointSelect)")
        text = text[:first] + hook + text[first:]
    # When checkout selection is reset, reset benefit if nearby point reset exists.
    text = text.replace('pointSelect.value = "";', 'pointSelect.value = "";\n            if (benefitSelect) benefitSelect.value = "";')
    write(path, text)


def patch_discord_points_and_loyalty() -> None:
    # Canonical point catalog shared with website.
    path = "bot.py"
    old = '''POINT_REDEEM_ITEMS = [\n    {"key": "discount_20", "cost": 5, "name": "20 元折價券"},\n    {"key": "discount_30", "cost": 10, "name": "30 元折價券"},\n    {"key": "extra_10", "cost": 15, "name": "加時 30 分鐘"},\n    {"key": "extra_15", "cost": 20, "name": "加場一場保撤"},\n    {"key": "free_specify_fee", "cost": 25, "name": "免指定費 1 次"},\n    {"key": "discount_100", "cost": 30, "name": "100 元折價券"},\n    {"key": "extra_30", "cost": 40, "name": "加時一小時"},\n]\n'''
    new = '''POINT_REDEEM_ITEMS = [\n    {"key": "discount_20", "cost": 10, "name": "20T 折價券"},\n    {"key": "discount_30", "cost": 15, "name": "30T 折價券"},\n    {"key": "free_specify_fee", "cost": 30, "name": "免指定費 1 次"},\n    {"key": "discount_100", "cost": 45, "name": "100T 折價券"},\n    {"key": "extra_game_1", "cost": 40, "name": "加 1 局"},\n    {"key": "extra_game_2", "cost": 70, "name": "加 2 局"},\n    {"key": "extra_hour_30m", "cost": 60, "name": "加時 30 分鐘"},\n    {"key": "extra_hour_1h", "cost": 110, "name": "加時 1 小時"},\n]\n'''
    replace(path, old, new)

    # Register member portal extension next to staff sync when present.
    text = read(path)
    if '"cogs.member_portal"' not in text:
        candidates = ['"cogs.staff_sync",', "'cogs.staff_sync',"]
        for candidate in candidates:
            if candidate in text:
                text = text.replace(candidate, candidate + '\n        "cogs.member_portal",', 1)
                break
        else:
            raise RuntimeError("bot.py: cogs.staff_sync extension entry not found")
        write(path, text)

    path = "services/self_service_runtime.py"
    # Replace entire stale point spec + adapter segment.
    text = read(path)
    start = text.find("ORDER_POINT_BENEFIT_SPECS = {")
    end = text.find("\ndef get_selected_order_point_benefit", start)
    if start < 0 or end < 0:
        raise RuntimeError("self_service_runtime: point benefit section markers missing")
    section = text[start:end]
    if "extra_15" not in section or "_adapt_order_point_benefit_for_rule" not in section:
        raise RuntimeError("self_service_runtime: stale point section unexpected")
    replacement = '''ORDER_POINT_BENEFIT_SPECS = {\n    "discount_20": {"kind": "cash_discount", "amount": 20, "summary": "20T 折價券，由店內吸收，不影響陪玩分潤"},\n    "discount_30": {"kind": "cash_discount", "amount": 30, "summary": "30T 折價券，由店內吸收，不影響陪玩分潤"},\n    "discount_100": {"kind": "cash_discount", "amount": 100, "summary": "100T 折價券，由店內吸收，不影響陪玩分潤"},\n    "free_specify_fee": {"kind": "free_specify_fee", "summary": "免指定費；顧客免付，由店內吸收，陪玩仍照原指定費計薪"},\n    "extra_hour_30m": {"kind": "extra_hours", "hours": 0.5, "summary": "服務時間 +30 分鐘，由店內按原價服務價值吸收"},\n    "extra_hour_1h": {"kind": "extra_hours", "hours": 1, "summary": "服務時間 +1 小時，由店內按原價服務價值吸收"},\n    "extra_game_1": {"kind": "extra_games", "games": 1, "summary": "服務局數 +1 局，由店內按原價服務價值吸收"},\n    "extra_game_2": {"kind": "extra_games", "games": 2, "summary": "服務局數 +2 局，由店內按原價服務價值吸收"},\n    # Hidden compatibility only: old unsettled orders may still carry this key.\n    "free_play_1h": {"kind": "free_first_hour", "hours": 1, "summary": "舊版首小時免費"},\n}\n\n\ndef _format_point_hours(hours) -> str:\n    try:\n        value = float(hours or 0)\n    except (TypeError, ValueError):\n        value = 0.0\n    if value <= 0:\n        return "0H"\n    if value == 0.5:\n        return "30 分鐘"\n    if value.is_integer():\n        return f"{int(value)}H"\n    return f"{value:g}H"\n\n\ndef get_order_point_item(key: str | None) -> dict | None:\n    if not key:\n        return None\n    try:\n        return POINT_REDEEM_ITEMS_BY_KEY.get(str(key))\n    except Exception:\n        return None\n\n\ndef get_customer_point_balance_for_order(customer_id: int) -> int:\n    try:\n        reward_data = get_customer_reward_data(int(customer_id))\n        return int(get_current_reward_points(reward_data))\n    except Exception:\n        return 0\n\n\ndef is_order_point_benefit_allowed_for_rule(rule, key: str, data: dict | None = None) -> tuple[bool, str]:\n    data = data or {}\n    key = str(key or "")\n    spec = ORDER_POINT_BENEFIT_SPECS.get(key)\n    if not spec:\n        return False, "這個點數福利不支援新下單流程。"\n    if not getattr(rule, "point_benefits_allowed", False):\n        return False, "此分類不可使用點數福利。"\n    category = str(getattr(rule, "category", "")).lower()\n    rule_key = str(getattr(rule, "key", "") or "")\n    rule_label = str(getattr(rule, "label", "") or "")\n    if category == "steam":\n        return False, "Steam遊戲目前不可使用點數福利。"\n    if category in {"fun", "delta_desktop_fun", "title"}:\n        return False, "趣味單 / 高難度稱號不可使用點數福利。"\n    if rule_key.startswith("basic_trial_") or rule_label.startswith("體驗單"):\n        return False, "體驗單不可使用點數福利。"\n    kind = str(spec.get("kind") or "")\n    pricing_type = str(getattr(rule, "pricing_type", "") or "")\n    if kind == "free_specify_fee":\n        if not getattr(rule, "allow_specify", False):\n            return False, "此項目不開放指定，因此不能使用免指定費。"\n        if not data.get("specified_staff_ids"):\n            return False, "請先指定人員，再使用免指定費。"\n        if pricing_type == "hourly" and (_to_int(data.get("quantity"), 1) or 1) >= 2:\n            return False, "2 小時以上本來就免指定費，不需要再花 30 點兌換。"\n    if kind == "free_first_hour":\n        if rule_key not in FREE_PLAY_FIRST_HOUR_RULE_KEYS or pricing_type != "hourly":\n            return False, "這是舊版相容福利，不能用於目前這個品項。"\n    if kind == "extra_hours" and pricing_type != "hourly":\n        return False, "加時福利只適用計時方案。"\n    if kind == "extra_games" and pricing_type != "game":\n        return False, "加局福利只適用計局方案。"\n    return True, ""\n\n\ndef _adapt_order_point_benefit_for_rule(rule, benefit: dict) -> dict:\n    return dict(benefit or {})\n\n'''
    write(path, text[:start] + replacement + text[end:])

    # Import loyalty service into extracted runtime.
    text = read(path)
    import_anchor = "from __future__ import annotations\n"
    if "from services.loyalty_benefits import" not in text:
        text = text.replace(
            import_anchor,
            import_anchor + "\nfrom services.loyalty_benefits import (\n    get_coupon,\n    list_available_coupons,\n    reserve_coupon,\n    validate_coupon_for_order,\n)\n",
            1,
        )
        write(path, text)

    # Finance: attach selected loyalty coupon and fund all free service/specify at original value.
    replace(
        path,
        "    point_specify = min(\n        point_specify,\n        specify_before,\n    )\n",
        '''    selected_loyalty = None\n    selected_loyalty_id = _to_int(data.get("selected_loyalty_coupon_id"), None)\n    if selected_loyalty_id is not None:\n        selected_loyalty = validate_coupon_for_order(\n            selected_loyalty_id,\n            customer_id=data.get("customer_id") or 0,\n            rule_key=str(getattr(rule, "key", "") or ""),\n            player_count=_to_int(data.get("player_count"), 1) or 1,\n            allow_reserved=True,\n        )\n        if bkind in {"extra_hours", "extra_games"}:\n            raise ValueError("累積加時／加局券不能和點數加時／加局同張訂單使用。")\n\n    point_specify = min(\n        point_specify,\n        specify_before,\n    )\n''',
    )
    # Replace payout calculation lines.
    replace(
        path,
        "    # 百分比折扣仍會降低分潤基準；\n    # 客服固定金額折扣與點數折價都由店內吸收，不影響打手分潤。\n    payout_base = allocation.payout_base_amount\n    customer_pay = allocation.customer_pay_amount\n\n    notes = []\n",
        '''    # 百分比折扣只影響顧客購買的基礎服務。店家承諾的免費服務／免指定\n    # 都用原價單位價值補進陪玩分潤，不跟著 VIP 折扣縮水。\n    purchased_service_quantity = max(1, _to_int(data.get("quantity"), 1) or 1)\n    original_unit_value = (service_original / purchased_service_quantity) if purchased_service_quantity else 0\n    point_service_value = int(round(original_unit_value * (extra_hours or extra_games or 0)))\n    loyalty_units = float(selected_loyalty.get("reward_units") or 0) if selected_loyalty else 0.0\n    loyalty_service_value = int(round(original_unit_value * loyalty_units)) if loyalty_units > 0 else 0\n\n    payout_base = max(\n        0,\n        allocation.payout_base_amount + point_specify + point_service_value + loyalty_service_value,\n    )\n    customer_pay = allocation.customer_pay_amount\n    store_absorbed = max(\n        0,\n        allocation.store_absorbed_amount + point_specify + point_service_value + loyalty_service_value,\n    )\n\n    notes = []\n''',
    )
    # Existing later purchased_service_quantity assignment duplicates; replace it with comment/no-op.
    replace(
        path,
        "    # service_promotion_calc_v1\n    purchased_service_quantity = max(\n        1,\n        _to_int(\n            data.get(\"quantity\"),\n            1,\n        )\n        or 1,\n    )\n",
        "    # service_promotion_calc_v1\n",
    )
    # Add loyalty note before promotion return.
    replace(
        path,
        "    if point_specify:\n        notes.append(\n            \"免指定費 \"\n            f\"-{_format_plain_amount(point_specify)}\"\n        )\n\n    # service_promotion_calc_v1\n",
        '''    if point_specify:\n        notes.append(\n            "免指定費 "\n            f"-{_format_plain_amount(point_specify)}"\n        )\n\n    if selected_loyalty:\n        if str(selected_loyalty.get("pricing_type") or "") == "hourly":\n            loyalty_label = "30 分鐘" if loyalty_units == 0.5 else f"{loyalty_units:g}H"\n            notes.append(f"累積福利：服務時間 +{loyalty_label}")\n        else:\n            notes.append(f"累積福利：服務局數 +{loyalty_units:g} 局")\n\n    # service_promotion_calc_v1\n''',
    )
    replace(
        path,
        '        "point_extra_games": extra_games,\n',
        '        "point_extra_games": extra_games,\n        "point_service_value": point_service_value,\n        "loyalty_coupon_id": int(selected_loyalty["id"]) if selected_loyalty else None,\n        "loyalty_coupon_name": str(selected_loyalty.get("display_name") or "") if selected_loyalty else "",\n        "loyalty_service_units": loyalty_units,\n        "loyalty_service_value": loyalty_service_value,\n',
    )
    replace(
        path,
        '        "store_absorbed_amount": (\n            allocation.store_absorbed_amount\n        ),\n',
        '        "store_absorbed_amount": (\n            store_absorbed\n        ),\n',
    )

    # Replace point-only ephemeral view with combined member benefit UI by adding loyalty select.
    marker = "\nclass SelfServiceSpecifiedStaffDropdownView(discord.ui.View):\n"
    text = read(path)
    if marker not in text:
        raise RuntimeError("self_service_runtime: specified view marker missing")
    loyalty_ui = '''\nclass SelfServiceLoyaltyBenefitSelect(discord.ui.Select):\n    def __init__(self, parent_view: "SelfServicePointBenefitView"):\n        options = [discord.SelectOption(\n            label="不使用累積福利", value="none",\n            description="清除這張單目前選擇的累積福利券",\n            default=parent_view.selected_loyalty_id is None,\n        )]\n        for item in parent_view.available_loyalty_items[:24]:\n            options.append(discord.SelectOption(\n                label=_truncate_select_text(str(item.get("display_name") or "累積福利")),\n                value=str(item["id"]),\n                description="同商品、同人數規格；可重新選陪玩",\n                default=int(item["id"]) == int(parent_view.selected_loyalty_id or 0),\n            ))\n        super().__init__(\n            placeholder="選擇累積福利券", min_values=1, max_values=1,\n            options=options, row=1,\n        )\n\n    async def callback(self, interaction: discord.Interaction):\n        view = self.view\n        if not isinstance(view, SelfServicePointBenefitView):\n            await interaction.response.send_message("會員福利選單狀態異常。", ephemeral=True)\n            return\n        data = SELF_SERVICE_ORDER_SELECTIONS.setdefault(view.channel_id, {})\n        selected = self.values[0]\n        if selected == "none":\n            data.pop("selected_loyalty_coupon_id", None)\n            data.pop("loyalty_coupon_name", None)\n        else:\n            coupon = validate_coupon_for_order(\n                int(selected), customer_id=view.customer_id,\n                rule_key=str(getattr(view.rule, "key", "") or ""),\n                player_count=_to_int(data.get("player_count"), 1) or 1,\n                allow_reserved=True,\n            )\n            point = get_selected_order_point_benefit(data, view.rule)\n            if point and str(point.get("kind") or "") in {"extra_hours", "extra_games"}:\n                await interaction.response.send_message(\n                    "累積加時／加局券不能和點數加時／加局同張使用；折價券與免指定費仍可一起用。",\n                    ephemeral=True,\n                )\n                return\n            data["selected_loyalty_coupon_id"] = int(coupon["id"])\n            data["loyalty_coupon_name"] = str(coupon.get("display_name") or "累積福利")\n        data.pop("payment_method", None)\n        remember_order_data(view.channel_id, data)\n        await view.refresh_source_panel(interaction)\n        await interaction.response.edit_message(\n            content=view.build_message_content(data),\n            view=SelfServicePointBenefitView(\n                customer_id=view.customer_id, channel_id=view.channel_id,\n                panel_message_id=view.panel_message_id, rule=view.rule,\n            ),\n        )\n\n'''
    text = text.replace(marker, loyalty_ui + marker, 1)
    write(path, text)

    # Add loyalty select to existing point benefit view.
    replace(
        path,
        "        self.selected_key = data.get(\"selected_point_benefit_key\")\n        self.point_balance = get_customer_point_balance_for_order(customer_id)\n        self.available_items = self.build_available_items(data)\n\n        self.add_item(SelfServicePointBenefitSelect(self))\n",
        '''        self.selected_key = data.get("selected_point_benefit_key")\n        self.selected_loyalty_id = _to_int(data.get("selected_loyalty_coupon_id"), None)\n        self.point_balance = get_customer_point_balance_for_order(customer_id)\n        self.available_items = self.build_available_items(data)\n        self.available_loyalty_items = list_available_coupons(\n            customer_id,\n            rule_key=str(getattr(rule, "key", "") or ""),\n            player_count=_to_int(data.get("player_count"), 1) or 1,\n        )\n\n        self.add_item(SelfServicePointBenefitSelect(self))\n        self.add_item(SelfServiceLoyaltyBenefitSelect(self))\n''',
    )
    # Point select rejects service extension if loyalty selected.
    replace(
        path,
        "            data[\"selected_point_benefit_key\"] = str(selected)\n            data[\"point_benefit_key\"] = str(selected)\n",
        '''            spec = ORDER_POINT_BENEFIT_SPECS.get(str(selected)) or {}\n            if data.get("selected_loyalty_coupon_id") and str(spec.get("kind") or "") in {"extra_hours", "extra_games"}:\n                await interaction.response.send_message(\n                    "累積加時／加局券不能和點數加時／加局同張使用；折價券與免指定費仍可一起用。",\n                    ephemeral=True,\n                )\n                return\n            data["selected_point_benefit_key"] = str(selected)\n            data["point_benefit_key"] = str(selected)\n''',
    )
    replace(
        path,
        "        return (\n            f\"請選擇這張單要使用的點數福利。\\n\"\n            f\"目前可用點數：{self.point_balance} 點\\n\"\n            f\"目前選擇：{selected_text}\\n\\n\"\n            \"提醒：這裡只是先保留在訂單上，付款成立時才會正式扣點。\"\n        )\n",
        '''        loyalty_text = str(data.get("loyalty_coupon_name") or "尚未使用")\n        return (\n            f"請選擇這張單要使用的會員福利。\\n"\n            f"目前可用點數：{self.point_balance} 點\\n"\n            f"點數福利：{selected_text}\\n"\n            f"累積福利：{loyalty_text}\\n\\n"\n            "加時／加局類的點數福利與累積福利不能同張疊加；折價與免指定費可以。"\n        )\n''',
    )
    # Rename button and remove point-only precheck.
    replace(path, 'label="選擇點數福利",', 'label="會員福利",')
    precheck = '''        allowed, reason = is_order_point_benefit_allowed_for_rule(rule, "discount_20", data)\n        if not allowed:\n            await interaction.response.send_message(reason or "這個分類不可使用點數福利。", ephemeral=True)\n            return\n\n'''
    replace(path, precheck, "")

    # Persist loyalty financial fields into order state.
    replace(
        path,
        '    data["point_extra_games"] = price_adjustment["point_extra_games"]\n',
        '    data["point_extra_games"] = price_adjustment["point_extra_games"]\n    data["point_service_value"] = price_adjustment.get("point_service_value", 0)\n    data["selected_loyalty_coupon_id"] = price_adjustment.get("loyalty_coupon_id")\n    data["loyalty_coupon_name"] = price_adjustment.get("loyalty_coupon_name")\n    data["loyalty_service_units"] = price_adjustment.get("loyalty_service_units", 0)\n    data["loyalty_service_value"] = price_adjustment.get("loyalty_service_value", 0)\n',
    )
    # Reserve DC selected coupon once order id exists.
    reserve_marker = '    data["web_order_id"] = int(web_order.id)\n'
    reserve_add = '''    data["web_order_id"] = int(web_order.id)\n    if data.get("selected_loyalty_coupon_id"):\n        coupon = reserve_coupon(\n            int(data["selected_loyalty_coupon_id"]),\n            customer_id=customer_id,\n            rule_key=str(rule.key),\n            player_count=player_count,\n            reservation_key=f"WEB-{int(web_order.id)}",\n        )\n        data["loyalty_coupon_name"] = str(coupon.get("display_name") or data.get("loyalty_coupon_name") or "累積福利")\n'''
    replace(path, reserve_marker, reserve_add)


def patch_order_runtime_and_web_bridge() -> None:
    path = "services/order_runtime.py"
    # Helpers for coupon payment lifecycle.
    marker = "\ndef _order_requires_credentials(data: dict | None) -> bool:\n"
    helpers = '''\ndef precheck_order_loyalty_coupon_for_payment(data: dict, customer_id: int) -> None:\n    coupon_id = _to_int(data.get("selected_loyalty_coupon_id"), None)\n    if coupon_id is None:\n        return\n    from services.loyalty_benefits import validate_coupon_for_order\n    validate_coupon_for_order(\n        coupon_id, customer_id=customer_id,\n        rule_key=str(data.get("order_rule_key") or ""),\n        player_count=_to_int(data.get("player_count"), 1) or 1,\n        allow_reserved=True,\n    )\n\n\ndef consume_order_loyalty_coupon_on_payment(data: dict, customer_id: int, channel_id: int) -> str | None:\n    coupon_id = _to_int(data.get("selected_loyalty_coupon_id"), None)\n    if coupon_id is None:\n        return None\n    from services.loyalty_benefits import consume_coupon\n    used_order_key = (\n        f"WEB-{int(data['web_order_id'])}"\n        if _to_int(data.get("web_order_id"), None) is not None\n        else f"DC-{int(channel_id)}"\n    )\n    coupon = consume_coupon(\n        coupon_id, customer_id=customer_id, used_order_key=used_order_key,\n    )\n    data["loyalty_coupon_used"] = True\n    data["loyalty_coupon_used_at"] = get_taipei_now_iso()\n    data["loyalty_coupon_name"] = str(coupon.get("display_name") or data.get("loyalty_coupon_name") or "累積福利")\n    remember_order_data(channel_id, data)\n    save_bot_data()\n    return f"累積福利已套用：{data['loyalty_coupon_name']}"\n\n'''
    text = read(path)
    if marker not in text:
        raise RuntimeError("order_runtime: credentials marker missing")
    text = text.replace(marker, helpers + marker, 1)
    write(path, text)

    # Precheck + consume at payment establishment.
    replace(
        path,
        "        try:\n            precheck_order_point_benefit_for_payment(data, customer_id)\n        except ValueError as exc:\n",
        "        try:\n            precheck_order_point_benefit_for_payment(data, customer_id)\n            precheck_order_loyalty_coupon_for_payment(data, customer_id)\n        except ValueError as exc:\n",
    )
    replace(
        path,
        "        order_point_benefit_result = None\n",
        "        order_point_benefit_result = None\n        order_loyalty_benefit_result = None\n",
        count=1,
    )
    replace(
        path,
        "        data[\"amount\"] = amount\n        data[\"total_amount\"] = amount\n",
        '''        try:\n            order_loyalty_benefit_result = consume_order_loyalty_coupon_on_payment(\n                data, customer_id, channel_id\n            )\n        except ValueError as exc:\n            data.pop("payment_finalizing", None)\n            remember_order_data(channel_id, data)\n            save_bot_data()\n            await interaction.followup.send(str(exc), ephemeral=True)\n            return\n\n        data["amount"] = amount\n        data["total_amount"] = amount\n''',
        count=1,
    )
    replace(
        path,
        "        if order_point_benefit_result:\n            response_text += f\"\\n\\n{order_point_benefit_result}\"\n        if reward_result:\n",
        "        if order_point_benefit_result:\n            response_text += f\"\\n\\n{order_point_benefit_result}\"\n        if order_loyalty_benefit_result:\n            response_text += f\"\\n\\n{order_loyalty_benefit_result}\"\n        if reward_result:\n",
    )

    # Cancellation returns reserved or already-consumed loyalty coupon.
    replace(
        path,
        "    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel_id, {})\n    dispatch_message_id = _to_int(data.get(\"dispatch_message_id\"))\n",
        '''    data = SELF_SERVICE_ORDER_SELECTIONS.get(order_channel_id, {})\n    coupon_id = _to_int(data.get("selected_loyalty_coupon_id"), None)\n    if coupon_id is not None:\n        try:\n            from services.loyalty_benefits import restore_coupon\n            restore_coupon(coupon_id, customer_id=data.get("customer_id"))\n        except Exception as exc:\n            print(f"[loyalty] 取消訂單退回福利券失敗 channel_id={order_channel_id}: {exc}")\n    dispatch_message_id = _to_int(data.get("dispatch_message_id"))\n''',
        count=1,
    )

    # Accumulate only when service is actually closed; paid base quantity only.
    close_marker = '    data["closed_at"] = get_taipei_now_iso()\n    data["quantity"] = quantity\n'
    close_add = '''    data["closed_at"] = get_taipei_now_iso()\n    data["quantity"] = quantity\n\n    try:\n        from services.loyalty_benefits import record_paid_service\n        source_order_key = (\n            f"WEB-{int(data['web_order_id'])}"\n            if _to_int(data.get("web_order_id"), None) is not None\n            else f"DC-{int(order_channel_id)}"\n        )\n        loyalty_result = record_paid_service(\n            customer_id=customer_id or data.get("customer_id") or 0,\n            rule_key=str(data.get("order_rule_key") or ""),\n            player_count=_to_int(data.get("player_count"), 1) or 1,\n            paid_units=float(quantity),\n            source_order_key=source_order_key,\n            completed_at=data["closed_at"],\n        )\n        issued = loyalty_result.get("issued") or []\n        if issued:\n            reward_lines = "\\n".join(\n                f"・**{coupon.get('display_name') or '累積福利'}**"\n                for coupon in issued\n            )\n            await source_channel.send(\n                f"<@{customer_id}> 🎁 **累積福利已達標！**\\n{reward_lines}\\n下次點同商品、同人數規格時即可使用，陪玩可以重新選。",\n                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),\n            )\n    except Exception as exc:\n        print(f"[loyalty] 結單累積失敗 channel_id={order_channel_id}: {type(exc).__name__}: {exc}")\n'''
    replace(path, close_marker, close_add)

    # Website bridge copies loyalty selection/service notes from server snapshot into ticket state.
    path = "services/web_sync/runtime.py"
    marker = '''    data["price_snapshot_json"] = (\n        order.get(\n            "price_snapshot_json"\n        )\n    )\n'''
    addition = marker + '''\n    try:\n        import json as _json\n        _price_snapshot = _json.loads(str(data.get("price_snapshot_json") or "{}"))\n        _preview = _price_snapshot.get("preview") if isinstance(_price_snapshot, dict) else {}\n        _preview = _preview if isinstance(_preview, dict) else {}\n        _loyalty = _preview.get("loyalty") if isinstance(_preview.get("loyalty"), dict) else {}\n        _finance = _preview.get("finance") if isinstance(_preview.get("finance"), dict) else {}\n        if _loyalty.get("id"):\n            data["selected_loyalty_coupon_id"] = int(_loyalty["id"])\n            data["loyalty_coupon_name"] = str(_loyalty.get("name") or "累積福利")\n            data["loyalty_service_units"] = float(_loyalty.get("reward_units") or 0)\n            data["loyalty_service_value"] = int(_finance.get("loyalty_service_value") or 0)\n            data["service_bonus_text"] = "｜".join(\n                part for part in (\n                    str(_finance.get("point_service_note") or "").strip(),\n                    str(_finance.get("loyalty_service_note") or "").strip(),\n                ) if part\n            )\n    except Exception as exc:\n        print(f"[loyalty] website snapshot parse skipped WEB-{order_id}: {exc}")\n'''
    replace(path, marker, addition)


def write_member_portal_cog() -> None:
    write("cogs/member_portal.py", textwrap.dedent('''
    from __future__ import annotations

    import os
    from urllib.parse import quote

    import discord
    from discord.ext import commands
    from sqlalchemy import text

    from services.loyalty_benefits import get_customer_benefit_snapshot
    from services.rewards import (
        get_current_reward_points,
        get_customer_reward_data,
        get_effective_member_level,
    )
    from services.wallet_service import get_wallet_balance
    from shared.db import engine
    from views.staff_profiles import get_staff_profile, list_customer_favorites


    MEMBER_PORTAL_CHANNEL_ID = int(os.getenv("MEMBER_PORTAL_CHANNEL_ID", "1558395213406412801"))
    MEMBER_PORTAL_MARKER = "MAWAN_MEMBER_PORTAL_V1"
    WEBSITE_PORTAL_URL = "https://mowanentertainment.com/me"


    def _embed(title: str, description: str = "") -> discord.Embed:
        return discord.Embed(title=title, description=description, color=discord.Color.gold())


    class MemberPortalView(discord.ui.View):
        def __init__(self):
            super().__init__(timeout=None)

        @discord.ui.button(label="會員 / 點數", style=discord.ButtonStyle.secondary, custom_id="member_portal:member")
        async def member(self, interaction: discord.Interaction, button: discord.ui.Button):
            data = get_customer_reward_data(interaction.user.id)
            level = get_effective_member_level(data)
            points = get_current_reward_points(data)
            try:
                wallet = get_wallet_balance(interaction.user.id)
            except Exception:
                wallet = 0
            embed = _embed("我的會員資料")
            embed.add_field(name="VIP", value=str(level.get("name") or "普通魔丸"), inline=True)
            embed.add_field(name="點數", value=f"{int(points):,} 點", inline=True)
            embed.add_field(name="錢包", value=f"{int(wallet):,}T", inline=True)
            embed.add_field(name="累積有效消費", value=f"{int(data.get('total_spent') or 0):,}T", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)

        @discord.ui.button(label="我的福利", style=discord.ButtonStyle.primary, custom_id="member_portal:benefits")
        async def benefits(self, interaction: discord.Interaction, button: discord.ui.Button):
            snapshot = get_customer_benefit_snapshot(interaction.user.id)
            embed = _embed("我的福利", "只顯示已開始累積的項目；新制自 2026/10/10 起計。")
            coupons = snapshot.get("coupons") or []
            progress = snapshot.get("progress") or []
            embed.add_field(
                name=f"可用福利券 · {len(coupons)}",
                value=("\\n".join(f"・{item.get('display_name')}" for item in coupons[:10]) or "目前沒有可用福利券"),
                inline=False,
            )
            if progress:
                lines = []
                for item in progress[:10]:
                    current = float(item.get("paid_units") or 0)
                    threshold = float(item.get("threshold_units") or 0)
                    current_text = f"{current:g}"
                    threshold_text = f"{threshold:g}"
                    lines.append(
                        f"・{item.get('label')}：{current_text}/{threshold_text} {item.get('unit_label')} → {item.get('reward_label')}"
                    )
                embed.add_field(name="累積進度", value="\\n".join(lines), inline=False)
            else:
                embed.add_field(name="累積進度", value="完成第一筆符合活動的付費服務後才會顯示。", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)

        @discord.ui.button(label="我的訂單", style=discord.ButtonStyle.secondary, custom_id="member_portal:orders")
        async def orders(self, interaction: discord.Interaction, button: discord.ui.Button):
            try:
                with engine.begin() as conn:
                    rows = conn.execute(text("""
                        SELECT id, bot_order_no, item, status,
                               COALESCE(customer_pay_amount, amount, 0) AS amount
                        FROM web_orders
                        WHERE CAST(customer_discord_id AS TEXT)=:customer_id
                        ORDER BY id DESC
                        LIMIT 5
                    """), {"customer_id": str(interaction.user.id)}).mappings().all()
            except Exception:
                rows = []
            if rows:
                body = "\\n".join(
                    f"・{row.get('bot_order_no') or 'WEB-' + str(row.get('id'))}｜{row.get('item') or '未紀錄'}｜{int(row.get('amount') or 0):,}T｜{row.get('status') or '未紀錄'}"
                    for row in rows
                )
            else:
                body = "目前沒有可顯示的訂單。"
            embed = _embed("最近訂單", body)
            embed.add_field(name="完整訂單", value="到網站「我的專區」可查看完整進度與明細。", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)

        @discord.ui.button(label="我的收藏", style=discord.ButtonStyle.secondary, custom_id="member_portal:favorites")
        async def favorites(self, interaction: discord.Interaction, button: discord.ui.Button):
            try:
                ids = list_customer_favorites(interaction.user.id)
            except Exception:
                ids = []
            lines = []
            for staff_id in ids[:15]:
                profile = get_staff_profile(staff_id) or {}
                name = str(profile.get("display_name") or profile.get("name") or staff_id)
                lines.append(f"・{name}")
            embed = _embed("我的收藏", "\\n".join(lines) if lines else "目前還沒有收藏陪玩。")
            await interaction.response.send_message(embed=embed, ephemeral=True)

        @discord.ui.button(label="網站我的專區", style=discord.ButtonStyle.link, url=WEBSITE_PORTAL_URL, row=1)
        async def website(self, interaction: discord.Interaction, button: discord.ui.Button):
            pass


    def build_panel_embed() -> discord.Embed:
        embed = _embed(
            "我的專區",
            "不用輸入指令。按下方按鈕即可私人查看會員資料、累積福利、訂單與收藏。\\n查詢結果只有你自己看得到。",
        )
        embed.add_field(name="累積福利", value="計時 10 個付費小時送 30 分鐘；計局 20 個付費局送 1 局。", inline=False)
        embed.set_footer(text=MEMBER_PORTAL_MARKER)
        return embed


    async def ensure_member_portal_panel(bot: commands.Bot) -> None:
        await bot.wait_until_ready()
        channel = bot.get_channel(MEMBER_PORTAL_CHANNEL_ID)
        if channel is None:
            try:
                channel = await bot.fetch_channel(MEMBER_PORTAL_CHANNEL_ID)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return
        if not isinstance(channel, discord.TextChannel):
            return
        existing = None
        try:
            async for message in channel.history(limit=50):
                if message.author.id != bot.user.id:
                    continue
                if any(str(getattr(embed.footer, "text", "") or "") == MEMBER_PORTAL_MARKER for embed in message.embeds):
                    existing = message
                    break
        except (discord.Forbidden, discord.HTTPException):
            return
        if existing is not None:
            try:
                await existing.edit(embed=build_panel_embed(), view=MemberPortalView())
                return
            except discord.HTTPException:
                pass
        try:
            await channel.send(embed=build_panel_embed(), view=MemberPortalView())
        except (discord.Forbidden, discord.HTTPException):
            return


    class MemberPortalCog(commands.Cog):
        def __init__(self, bot: commands.Bot):
            self.bot = bot
            self.bot.add_view(MemberPortalView())
            self.bot.loop.create_task(ensure_member_portal_panel(bot))


    async def setup(bot: commands.Bot) -> None:
        await bot.add_cog(MemberPortalCog(bot))
    ''').lstrip())


def write_tests() -> None:
    write("tests/test_loyalty_benefits.py", textwrap.dedent('''
    from pathlib import Path

    from services.loyalty_benefits import (
        get_customer_benefit_snapshot,
        list_available_coupons,
        record_paid_service,
        reserve_coupon,
        consume_coupon,
        restore_coupon,
    )
    from services.order_rules import ORDER_RULES, OrderRule


    def _install_rule(monkeypatch, key="test_loyalty_hourly", pricing_type="hourly", threshold=10, reward=0.5):
        rule = OrderRule(
            category="basic", key=key, label="測試福利", pricing_type=pricing_type,
            price=300, point_benefits_allowed=True,
            loyalty_threshold_units=threshold, loyalty_reward_units=reward,
        )
        monkeypatch.setitem(ORDER_RULES, key, rule)
        return rule


    def test_hourly_progress_starts_only_after_paid_service_and_issues_at_ten(monkeypatch, tmp_path):
        _install_rule(monkeypatch)
        db = tmp_path / "loyalty.db"
        assert get_customer_benefit_snapshot("1", db_file=db)["progress"] == []
        first = record_paid_service(
            customer_id="1", rule_key="test_loyalty_hourly", player_count=1,
            paid_units=9, source_order_key="WEB-1", completed_at="2026-10-10T10:00:00+08:00", db_file=db,
        )
        assert first["issued"] == []
        snapshot = get_customer_benefit_snapshot("1", db_file=db)
        assert len(snapshot["progress"]) == 1
        assert snapshot["progress"][0]["paid_units"] == 9
        second = record_paid_service(
            customer_id="1", rule_key="test_loyalty_hourly", player_count=1,
            paid_units=1, source_order_key="WEB-2", completed_at="2026-10-10T11:00:00+08:00", db_file=db,
        )
        assert len(second["issued"]) == 1
        assert second["progress"]["paid_units"] == 0


    def test_game_twenty_to_one_and_duplicate_order_is_idempotent(monkeypatch, tmp_path):
        _install_rule(monkeypatch, key="test_game", pricing_type="game", threshold=20, reward=1)
        db = tmp_path / "loyalty.db"
        result = record_paid_service(
            customer_id="2", rule_key="test_game", player_count=2,
            paid_units=20, source_order_key="DC-99", completed_at="2026-10-11T00:00:00+08:00", db_file=db,
        )
        assert len(result["issued"]) == 1
        duplicate = record_paid_service(
            customer_id="2", rule_key="test_game", player_count=2,
            paid_units=20, source_order_key="DC-99", completed_at="2026-10-11T00:00:00+08:00", db_file=db,
        )
        assert duplicate["duplicate"] is True
        assert len(list_available_coupons("2", rule_key="test_game", player_count=2, db_file=db)) == 1


    def test_pre_program_orders_do_not_backfill(monkeypatch, tmp_path):
        _install_rule(monkeypatch)
        db = tmp_path / "loyalty.db"
        result = record_paid_service(
            customer_id="3", rule_key="test_loyalty_hourly", player_count=1,
            paid_units=100, source_order_key="OLD", completed_at="2026-10-09T23:59:59+08:00", db_file=db,
        )
        assert result["eligible"] is False
        assert get_customer_benefit_snapshot("3", db_file=db)["progress"] == []


    def test_coupon_reserve_consume_restore_lifecycle(monkeypatch, tmp_path):
        _install_rule(monkeypatch, key="test_game", pricing_type="game", threshold=20, reward=1)
        db = tmp_path / "loyalty.db"
        issued = record_paid_service(
            customer_id="4", rule_key="test_game", player_count=3,
            paid_units=20, source_order_key="WEB-4", completed_at="2026-10-12T10:00:00+08:00", db_file=db,
        )["issued"][0]
        reserve_coupon(
            issued["id"], customer_id="4", rule_key="test_game", player_count=3,
            reservation_key="WEB-5", db_file=db,
        )
        consume_coupon(issued["id"], customer_id="4", used_order_key="WEB-5", db_file=db)
        assert list_available_coupons("4", db_file=db) == []
        assert restore_coupon(issued["id"], customer_id="4", db_file=db) is True
        assert len(list_available_coupons("4", rule_key="test_game", player_count=3, db_file=db)) == 1
    ''').lstrip())

    write("tests/test_loyalty_order_rules.py", textwrap.dedent('''
    from services.order_rules import ORDER_RULES


    def test_current_builtin_rules_no_longer_use_same_order_buy_get():
        active = [
            rule.key for rule in ORDER_RULES.values()
            if rule.service_bonus_buy or rule.service_bonus_gift
        ]
        assert active == []


    def test_legacy_valorant_rules_are_not_active():
        assert "valorant_entertain" not in ORDER_RULES
        assert "valorant_tech" not in ORDER_RULES
        assert "valorant_top_tech" not in ORDER_RULES


    def test_loyalty_thresholds_are_split_by_hour_and_game():
        hourly = ORDER_RULES["basic_entertain_single"]
        assert hourly.loyalty_threshold_units == 10
        assert hourly.loyalty_reward_units == 0.5
        game = ORDER_RULES["valorant_entertain_ranked"]
        assert game.loyalty_threshold_units == 20
        assert game.loyalty_reward_units == 1
        apex = ORDER_RULES["apex_entertain_platinum"]
        assert apex.loyalty_threshold_units == 10
        assert apex.loyalty_reward_units == 0.5
        assert ORDER_RULES["steam_play"].loyalty_threshold_units is None
    ''').lstrip())

    # Extend existing checkout test for VIP-independent free-service funding.
    path = "tests/test_checkout_point_benefits.py"
    text = read(path)
    addition = textwrap.dedent('''

    def test_point_added_service_uses_original_value_even_for_vip_discount():
        point_item = {"kind": "extra_hours", "hours": 0.5}
        value = checkout.calculate_point_service_value(
            quote={"quantity": 2, "customer_pay_amount": 600},
            vip_pay_rate=94,
            point_item=point_item,
        )
        assert value == 150


    def test_loyalty_added_service_is_store_funded_at_original_value():
        loyalty = {"pricing_type": "game", "reward_units": 1}
        value = checkout.calculate_loyalty_service_value(
            quote={"quantity": 5, "customer_pay_amount": 1000},
            loyalty_item=loyalty,
        )
        finance = checkout.calculate_checkout_financials(
            service_amount=1000,
            vip_pay_rate=94,
            specify_fee=0,
            point_item=None,
            point_service_value=0,
            loyalty_item=loyalty,
            loyalty_service_value=value,
            wallet_balance=0,
            use_wallet=False,
        )
        assert value == 200
        assert finance["customer_pay_amount"] == 940
        assert finance["payout_base_amount"] == 1140
        assert finance["store_absorbed_amount"] == 200
    ''')
    if "test_point_added_service_uses_original_value_even_for_vip_discount" not in text:
        write(path, text + addition)


def main() -> None:
    patch_order_rules()
    patch_loyalty_service()
    patch_staff_profile_archive()
    patch_checkout_preview()
    patch_site_and_public_order_create()
    patch_website_templates_and_js()
    patch_discord_points_and_loyalty()
    patch_order_runtime_and_web_bridge()
    write_member_portal_cog()
    write_tests()
    print("loyalty/member portal patch applied")


if __name__ == "__main__":
    main()
