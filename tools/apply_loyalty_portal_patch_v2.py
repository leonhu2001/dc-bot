from __future__ import annotations

import tools.apply_loyalty_portal_patch as patch


_original_replace = patch.replace


def replace_v2(path: str, old: str, new: str, *, count: int = 1) -> None:
    legacy_keys = '    "valorant_entertain",\n    "valorant_tech",\n    "valorant_top_tech",\n'
    if path == "web/app/services/checkout_preview.py" and old == legacy_keys:
        text = patch.read(path)
        found = text.count(old)
        if found != 2:
            raise RuntimeError(f"{path}: expected 2 legacy Valorant exclusion blocks, found {found}")
        patch.write(path, text.replace(old, new))
        return
    _original_replace(path, old, new, count=count)


patch.replace = replace_v2


def patch_staff_profile_archive_v2() -> None:
    path = "views/staff_profiles.py"
    old = '''    channel = await _ensure_profile_thread_open_for_refresh(
        channel,
        staff_id=staff_id_text,
        reason=reason,
    )
    if channel is None:
        return False

    if not hasattr(channel, "fetch_message"):
        return False

    try:
        panel_message = await channel.fetch_message(message_id)
    except (
        discord.NotFound,
        discord.Forbidden,
        discord.HTTPException,
    ):
        return False

    latest_profile = get_staff_profile(staff_id_text)
    if latest_profile is None:
        return False

    try:
        await panel_message.edit(
            embed=build_staff_profile_embed(latest_profile),
            view=StaffProfilePanelView(staff_id_text),
            allowed_mentions=discord.AllowedMentions(
                users=False,
                roles=False,
                everyone=False,
            ),
        )
    except discord.HTTPException as exc:
        print(
            f"[staff-profile] refresh failed "
            f"staff_id={staff_id_text} "
            f"reason={reason}: {exc}"
        )
        return False

    print(
        f"[staff-profile] refreshed "
        f"staff_id={staff_id_text} "
        f"reason={reason}"
    )
    return True
'''
    new = '''    was_archived = bool(getattr(channel, "archived", False))
    channel = await _ensure_profile_thread_open_for_refresh(
        channel,
        staff_id=staff_id_text,
        reason=reason,
    )
    if channel is None:
        return False

    try:
        if not hasattr(channel, "fetch_message"):
            return False

        try:
            panel_message = await channel.fetch_message(message_id)
        except (
            discord.NotFound,
            discord.Forbidden,
            discord.HTTPException,
        ):
            return False

        latest_profile = get_staff_profile(staff_id_text)
        if latest_profile is None:
            return False

        try:
            await panel_message.edit(
                embed=build_staff_profile_embed(latest_profile),
                view=StaffProfilePanelView(staff_id_text),
                allowed_mentions=discord.AllowedMentions(
                    users=False,
                    roles=False,
                    everyone=False,
                ),
            )
        except discord.HTTPException as exc:
            print(
                f"[staff-profile] refresh failed "
                f"staff_id={staff_id_text} "
                f"reason={reason}: {exc}"
            )
            return False

        print(
            f"[staff-profile] refreshed "
            f"staff_id={staff_id_text} "
            f"reason={reason}"
        )
        return True
    finally:
        # Background refresh may temporarily reopen an archived thread so the
        # saved panel can be edited. Put it back immediately; genuinely active
        # conversations are never auto-archived.
        if was_archived and not bool(getattr(channel, "archived", False)):
            edit_channel = getattr(channel, "edit", None)
            if callable(edit_channel):
                try:
                    restored = await edit_channel(
                        archived=True,
                        reason=f"Staff profile refresh complete: {reason}"[:512],
                    )
                    if restored is not None:
                        channel = restored
                except (
                    discord.NotFound,
                    discord.Forbidden,
                    discord.HTTPException,
                ) as exc:
                    print(
                        f"[staff-profile] rearchive thread failed "
                        f"staff_id={staff_id_text} reason={reason}: {exc}"
                    )
'''
    patch.replace(path, old, new)

    test_path = "tests/test_staff_profile_archived_thread_refresh.py"
    text = patch.read(test_path)
    text = text.replace(
        "test_archived_public_profile_thread_is_reopened_and_left_active",
        "test_archived_public_profile_thread_is_reopened_then_rearchived",
    )
    text = text.replace("assert thread.edit_calls == [False]", "assert thread.edit_calls == [False, True]")
    text = text.replace("assert thread.archived is False", "assert thread.archived is True", 1)
    patch.write(test_path, text)


def patch_website_templates_and_js_v2() -> None:
    # Account menu: customer navigation goes through /me hub.
    path = "web/app/templates/site_layout.html"
    text = patch.read(path)
    for block in (
        '''\n                            <a href="/me/orders">\n                                我的訂單\n                            </a>\n\n                            <a href="/me#favorites">\n                                我的收藏\n                            </a>\n\n                            <a href="/me#vip">\n                                點數 / VIP\n                            </a>\n''',
        '''\n                <a href="/me/orders">我的訂單</a>\n''',
    ):
        if block in text:
            text = text.replace(block, "\n", 1)
    patch.write(path, text)

    # Member hub adds benefit stat and panel.
    path = "web/app/templates/member_center.html"
    text = patch.read(path)
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
    patch.write(path, text)

    # Checkout cumulative-benefit control.
    path = "web/app/templates/order_catalog.html"
    text = patch.read(path)
    point_control_end = '''                </label>\n\n\n                <label class="order-checkout-control" hidden aria-hidden="true" data-web-payment-hidden="1" style="display:none !important;">\n'''
    loyalty_control = '''                </label>\n\n\n                <label class="order-checkout-control">\n                    <span>累積福利</span>\n                    <select id="mw-checkout-benefit">\n                        <option value="">不使用累積福利</option>\n                    </select>\n                    <small id="mw-checkout-benefit-note">\n                        只有已持有、且符合目前商品與人數規格的福利才會顯示\n                    </small>\n                </label>\n\n\n                <label class="order-checkout-control" hidden aria-hidden="true" data-web-payment-hidden="1" style="display:none !important;">\n'''
    if point_control_end not in text:
        raise RuntimeError("order_catalog: point control marker missing")
    text = text.replace(point_control_end, loyalty_control, 1)
    text = text.replace("確認指定人員、點數福利與附加需求後，", "確認指定人員、點數／累積福利與附加需求後，", 1)
    if "/static/js/mw_order_quote.js?v=loyalty-20261010" not in text:
        text = text.replace("/static/js/mw_order_quote.js", "/static/js/mw_order_quote.js?v=loyalty-20261010", 1)
    patch.write(path, text)

    # Current checkout script uses byId + renderStaff rather than the older
    # renderStaffOptions shape the first patcher targeted.
    path = "web/app/static/js/mw_order_quote.js"
    text = patch.read(path)

    point_decl = '''    const pointSelect =\n        byId(\n            "mw-checkout-point"\n        );\n\n\n    const pointNote =\n'''
    benefit_decl = '''    const pointSelect =\n        byId(\n            "mw-checkout-point"\n        );\n\n\n    const benefitSelect =\n        byId(\n            "mw-checkout-benefit"\n        );\n\n\n    const benefitNote =\n        byId(\n            "mw-checkout-benefit-note"\n        );\n\n\n    const pointNote =\n'''
    if point_decl not in text:
        raise RuntimeError("mw_order_quote.js: point selector declaration missing")
    text = text.replace(point_decl, benefit_decl, 1)

    render_marker = "\n\n    function renderCheckoutOptions(\n"
    benefit_function = '''\n\n    function renderBenefitOptions(\n        items\n    ) {\n\n        if (!benefitSelect) {\n            return;\n        }\n\n        const previous =\n            String(\n                benefitSelect.value\n                || ""\n            );\n\n        benefitSelect.innerHTML =\n            '<option value="">不使用累積福利</option>';\n\n        (items || []).forEach(\n            item => {\n                const option =\n                    document.createElement(\n                        "option"\n                    );\n                option.value =\n                    String(\n                        item.id\n                        || ""\n                    );\n                option.textContent =\n                    String(\n                        item.display_name\n                        || item.benefit_label\n                        || "累積福利"\n                    );\n                benefitSelect.append(\n                    option\n                );\n            }\n        );\n\n        if (\n            Array.from(benefitSelect.options)\n                .some(option => option.value === previous)\n        ) {\n            benefitSelect.value =\n                previous;\n        } else {\n            benefitSelect.value =\n                "";\n        }\n\n        if (benefitNote) {\n            benefitNote.textContent =\n                items && items.length\n                    ? `目前有 ${items.length} 張符合這個方案的累積福利券`\n                    : "目前沒有符合這個商品與人數規格的累積福利券";\n        }\n    }\n'''
    if render_marker not in text:
        raise RuntimeError("mw_order_quote.js: checkout options marker missing")
    text = text.replace(render_marker, benefit_function + render_marker, 1)

    point_render = '''        renderPointOptions(\n            data.point_options\n        );\n'''
    if point_render not in text:
        raise RuntimeError("mw_order_quote.js: point option renderer call missing")
    text = text.replace(
        point_render,
        point_render + '''\n\n        renderBenefitOptions(\n            data.benefit_options\n            || []\n        );\n''',
        1,
    )

    preview_point = '''            point_item_key:\n                pointSelect.value\n                || null,\n\n            use_wallet:\n'''
    preview_with_benefit = '''            point_item_key:\n                pointSelect.value\n                || null,\n\n            benefit_coupon_id:\n                benefitSelect?.value\n                    ? Number(benefitSelect.value)\n                    : null,\n\n            use_wallet:\n'''
    if preview_point not in text:
        raise RuntimeError("mw_order_quote.js: preview point payload missing")
    text = text.replace(preview_point, preview_with_benefit, 1)

    formal_point = '''            point_item_key:\n                pointSelect?.value\n                || null,\n\n            use_wallet:\n'''
    formal_with_benefit = '''            point_item_key:\n                pointSelect?.value\n                || null,\n\n            benefit_coupon_id:\n                benefitSelect?.value\n                    ? Number(benefitSelect.value)\n                    : null,\n\n            use_wallet:\n'''
    if formal_point not in text:
        raise RuntimeError("mw_order_quote.js: formal point payload missing")
    text = text.replace(formal_point, formal_with_benefit, 1)

    # Show selected loyalty service in the checkout notes.
    loyalty_note_marker = '''        if (\n            finance.wallet_use_amount\n            > 0\n        ) {\n'''
    loyalty_note = '''        if (\n            finance.loyalty_service_note\n        ) {\n            notes.push(\n                finance.loyalty_service_note\n            );\n        }\n\n\n'''
    if loyalty_note_marker not in text:
        raise RuntimeError("mw_order_quote.js: wallet note marker missing")
    text = text.replace(loyalty_note_marker, loyalty_note + loyalty_note_marker, 1)

    event_marker = '''\n\n    useWallet?.addEventListener(\n'''
    event_hook = '''\n\n    benefitSelect?.addEventListener(\n        "change",\n        async () => {\n            await refreshCheckoutPreview();\n        }\n    );\n'''
    if event_marker not in text:
        raise RuntimeError("mw_order_quote.js: wallet change listener marker missing")
    text = text.replace(event_marker, event_hook + event_marker, 1)

    reset_marker = '''            if (useWallet) {\n\n                useWallet.checked =\n                    false;\n            }\n'''
    reset_benefit = '''            if (benefitSelect) {\n\n                benefitSelect.value =\n                    "";\n            }\n\n\n'''
    if reset_marker not in text:
        raise RuntimeError("mw_order_quote.js: wallet reset marker missing")
    text = text.replace(reset_marker, reset_benefit + reset_marker, 1)
    patch.write(path, text)


patch.patch_staff_profile_archive = patch_staff_profile_archive_v2
patch.patch_website_templates_and_js = patch_website_templates_and_js_v2
patch.main()
