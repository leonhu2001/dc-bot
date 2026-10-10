from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def write(path: str, content: str) -> None:
    (ROOT / path).write_text(content, encoding="utf-8")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 match, got {count}")
    return text.replace(old, new, 1)


def regex_once(text: str, pattern: str, repl: str, *, label: str, flags: int = 0) -> str:
    result, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly 1 regex match, got {count}")
    return result


def patch_order_rules() -> None:
    path = "services/order_rules.py"
    text = read(path)
    text = text.replace("from math import floor\n", "")
    text = replace_once(
        text,
        "    vip_discount_allowed: bool = True\n    point_benefits_allowed: bool = True\n\n    min_protector_count: int = 0\n",
        "    vip_discount_allowed: bool = True\n    point_benefits_allowed: bool = True\n    # 跨訂單會員回饋。舊 service_bonus_* 僅保留歷史/後台相容，\n    # 不再直接增加同張訂單的服務數量。\n    loyalty_benefits_enabled: bool = False\n\n    min_protector_count: int = 0\n",
        label="OrderRule loyalty flag",
    )
    text = replace_once(
        text,
        '    "point_benefits_allowed",\n    "min_protector_count",\n',
        '    "point_benefits_allowed",\n    "loyalty_benefits_enabled",\n    "min_protector_count",\n',
        label="override loyalty flag",
    )
    text = regex_once(
        text,
        r"def get_service_quantity\(rule: OrderRule, quantity: int\) -> int:\n(?:    .*\n){1,4}?\n(?=\ndef calculate_price)",
        "def get_service_quantity(rule: OrderRule, quantity: int) -> int:\n    # 舊的同單買幾送幾已全面停用。會員加贈改由跨訂單福利券處理。\n    return int(quantity)\n\n",
        label="disable same-order bonus",
    )
    text, changed = re.subn(
        r"(?m)^(?P<i>\s*)service_bonus_buy=5,\n(?P=i)service_bonus_gift=1,\n",
        lambda m: f"{m.group('i')}loyalty_benefits_enabled=True,\n",
        text,
    )
    if changed < 3:
        raise RuntimeError(f"expected multiple 5-for-1 rules, changed {changed}")

    # 舊特戰三條已不在新 catalog，歷史訂單靠 rule/price snapshot 回查。
    text = regex_once(
        text,
        r"# ========= 特戰英豪 陪玩 =========\n.*?(?=# ========= 特戰英豪 / 英雄聯盟新制陪玩 =========)",
        "",
        label="remove old valorant rules",
        flags=re.S,
    )
    write(path, text)


def patch_loyalty_service() -> None:
    path = "services/loyalty_benefits.py"
    text = read(path)
    text = replace_once(
        text,
        "    ensure_loyalty_tables(db.get_bind())\n    scope = loyalty_scope_key(rule_key, player_count)\n",
        "    # Schema is initialized at application/bot startup. Avoid opening a second\n    # SQLite write transaction while this Session already owns the order transaction.\n    scope = loyalty_scope_key(rule_key, player_count)\n",
        label="avoid nested sqlite ensure",
    )
    write(path, text)


def patch_shared_db() -> None:
    path = "shared/db.py"
    text = read(path)
    text = replace_once(
        text,
        "    ensure_acceptance_tables()\n    ensure_order_cancellation_table(engine)\n",
        "    ensure_acceptance_tables()\n    ensure_order_cancellation_table(engine)\n\n    from services.loyalty_benefits import ensure_loyalty_tables\n    ensure_loyalty_tables(engine)\n",
        label="initialize loyalty schema",
    )
    write(path, text)


def patch_staff_profiles() -> None:
    path = "views/staff_profiles.py"
    text = read(path)
    # Do not unarchive just to edit. Returning handled=True prevents refresh queue retries.
    text = regex_once(
        text,
        r"async def _ensure_profile_thread_open_for_refresh\(.*?\n(?=async def refresh_staff_profile_panel_for_staff)",
        '''async def _ensure_profile_thread_open_for_refresh(\n    channel,\n    staff_id: str,\n    *,\n    reason: str,\n) -> bool:\n    """Return whether a profile panel may be edited without waking an archived thread.\n\n    Discord automatically surfaces active threads in the channel list. Profile data syncs\n    are background maintenance and must not turn an archived personal wall active again.\n    """\n    if isinstance(channel, discord.Thread) and bool(getattr(channel, "archived", False)):\n        print(\n            f"[staff-profile] archived thread left archived staff_id={staff_id} "\n            f"thread={channel.id} reason={reason}",\n            flush=True,\n        )\n        return False\n    return True\n\n\n''',
        label="archived profile helper",
        flags=re.S,
    )
    # Existing caller raises/continues after helper; convert archived skip into successful handled refresh.
    text = replace_once(
        text,
        "    await _ensure_profile_thread_open_for_refresh(\n        channel,\n        staff_id,\n        reason=reason,\n    )\n\n",
        "    can_edit = await _ensure_profile_thread_open_for_refresh(\n        channel,\n        staff_id,\n        reason=reason,\n    )\n    if not can_edit:\n        return True\n\n",
        label="skip archived profile edit",
    )
    write(path, text)


def patch_checkout_preview() -> None:
    path = "web/app/services/checkout_preview.py"
    text = read(path)
    text = replace_once(
        text,
        "from web.app.services.public_checkout import (\n    build_public_quote,\n)\n",
        "from web.app.services.public_checkout import (\n    build_public_quote,\n)\nfrom services.loyalty_benefits import (\n    calculate_coupon_service_value,\n    coupon_service_note,\n    get_applicable_coupon,\n    list_applicable_coupons,\n)\n",
        label="checkout loyalty imports",
    )
    # Point-added service is store-funded at normal list value, not VIP-discounted value.
    text = replace_once(
        text,
        "    gross_extra_value = int(round((service_amount / quantity) * units))\n    rate = max(0, min(100, int(vip_pay_rate or 100)))\n    return max(0, int(round(gross_extra_value * rate / 100)))\n",
        "    gross_extra_value = int(round((service_amount / quantity) * units))\n    # 額外服務是店家福利；VIP 折扣只影響顧客付款，不壓低陪玩薪資基底。\n    return max(0, gross_extra_value)\n",
        label="full-price point service value",
    )
    text = replace_once(
        text,
        "    use_wallet: bool,\n    point_service_value: int = 0,\n) -> dict:\n",
        "    use_wallet: bool,\n    point_service_value: int = 0,\n    benefit_coupon: dict | None = None,\n    benefit_service_value: int = 0,\n) -> dict:\n",
        label="checkout finance coupon args",
    )
    text = replace_once(
        text,
        "    point_service_value = max(0, int(point_service_value or 0))\n\n    after_vip = int(round(service_amount * vip_pay_rate / 100))\n",
        "    point_service_value = max(0, int(point_service_value or 0))\n    benefit_service_value = max(0, int(benefit_service_value or 0))\n\n    after_vip = int(round(service_amount * vip_pay_rate / 100))\n",
        label="normalize coupon value",
    )
    text = replace_once(
        text,
        "    payout_base = max(0, after_vip + specify_fee + point_service_value)\n    point_store_absorbed = max(\n        0,\n        point_cash_discount + point_waived_specify + point_service_value,\n    )\n",
        "    payout_base = max(\n        0,\n        after_vip + specify_fee + point_service_value + benefit_service_value,\n    )\n    point_store_absorbed = max(\n        0,\n        point_cash_discount + point_waived_specify + point_service_value,\n    )\n    benefit_store_absorbed = benefit_service_value if benefit_coupon else 0\n",
        label="coupon-funded payout",
    )
    text = replace_once(
        text,
        '        "point_store_absorbed_amount": point_store_absorbed,\n',
        '        "point_store_absorbed_amount": point_store_absorbed,\n        "benefit_coupon_id": (int(benefit_coupon.get("id")) if benefit_coupon else None),\n        "benefit_coupon_title": (str(benefit_coupon.get("title") or "") if benefit_coupon else ""),\n        "benefit_service_note": coupon_service_note(benefit_coupon),\n        "benefit_service_value": benefit_service_value,\n        "benefit_store_absorbed_amount": benefit_store_absorbed,\n',
        label="coupon finance return",
    )
    text = replace_once(
        text,
        '        "store_absorbed_amount": point_store_absorbed,\n        "store_absorbed_preview": point_store_absorbed,\n',
        '        "store_absorbed_amount": point_store_absorbed + benefit_store_absorbed,\n        "store_absorbed_preview": point_store_absorbed + benefit_store_absorbed,\n',
        label="total store absorbed coupon",
    )
    # Add available benefit coupons to checkout options.
    text = replace_once(
        text,
        '        "point_options":\n            point_options,\n\n        "payment_methods":\n',
        '        "point_options":\n            point_options,\n\n        "benefit_coupons": list_applicable_coupons(\n            customer_id,\n            rule_key=rule_key,\n            player_count=int(quote.get("player_count") or player_count or 1),\n        ),\n\n        "payment_methods":\n',
        label="checkout coupon options",
    )
    text = replace_once(
        text,
        "    point_item_key: str | None = None,\n    use_wallet: bool = False,\n",
        "    point_item_key: str | None = None,\n    benefit_coupon_id: int | str | None = None,\n    use_wallet: bool = False,\n",
        label="checkout preview coupon arg",
    )
    # Resolve coupon after point item is resolved, before finance.
    anchor = "\n\n    finance = (\n        calculate_checkout_financials(\n"
    insertion = '''\n\n    selected_benefit_coupon = None\n    if benefit_coupon_id not in (None, ""):\n        if selected_point_item is not None:\n            raise ValueError("福利券與點數福利同張訂單只能擇一使用。")\n        selected_benefit_coupon = get_applicable_coupon(\n            benefit_coupon_id,\n            customer_id=customer_id,\n            rule_key=rule_key,\n            player_count=int(quote.get("player_count") or player_count or 1),\n        )\n        if selected_benefit_coupon is None:\n            raise ValueError("這張福利券已使用、已保留，或不適用這個方案。")\n\n'''
    if text.count(anchor) != 1:
        raise RuntimeError("checkout finance anchor not unique")
    text = text.replace(anchor, insertion + anchor, 1)
    text = replace_once(
        text,
        "            point_service_value=\n                calculate_point_service_value(\n                    quote=quote,\n                    vip_pay_rate=vip_rate,\n                    point_item=selected_point_item,\n                ),\n\n            wallet_balance=\n",
        "            point_service_value=\n                calculate_point_service_value(\n                    quote=quote,\n                    vip_pay_rate=vip_rate,\n                    point_item=selected_point_item,\n                ),\n\n            benefit_coupon=selected_benefit_coupon,\n            benefit_service_value=calculate_coupon_service_value(\n                rule_key=rule_key,\n                player_count=int(quote.get(\"player_count\") or player_count or 1),\n                coupon=selected_benefit_coupon,\n            ),\n\n            wallet_balance=\n",
        label="pass coupon finance",
    )
    text = replace_once(
        text,
        '        "finance":\n            finance,\n\n        "payment": {\n',
        '        "benefit_coupon": (\n            {\n                "id": int(selected_benefit_coupon.get("id")),\n                "title": str(selected_benefit_coupon.get("title") or ""),\n                "benefit_kind": str(selected_benefit_coupon.get("benefit_kind") or ""),\n                "benefit_units": float(selected_benefit_coupon.get("benefit_units") or 0),\n            }\n            if selected_benefit_coupon\n            else None\n        ),\n\n        "finance":\n            finance,\n\n        "payment": {\n',
        label="preview coupon return",
    )
    # Old Valorant rules no longer exist.
    text = text.replace(
        '    "valorant_entertain",\n    "valorant_tech",\n    "valorant_top_tech",\n',
        '',
    )
    write(path, text)


def patch_site_router() -> None:
    path = "web/app/routers/site.py"
    text = read(path)
    text = replace_once(
        text,
        "from web.app.services.customer_portal import (\n    build_customer_portal_snapshot,\n    get_customer_order,\n)\n",
        "from web.app.services.customer_portal import (\n    build_customer_portal_snapshot,\n    get_customer_order,\n)\nfrom services.loyalty_benefits import list_customer_loyalty\n",
        label="site loyalty import",
    )
    text = replace_once(
        text,
        "            member=member,\n            portal=portal,\n",
        "            member=member,\n            portal=portal,\n            benefits=list_customer_loyalty(customer_id),\n",
        label="member benefits context",
    )
    text = replace_once(
        text,
        "            point_item_key=\n                payload.get(\n                    \"point_item_key\"\n                ),\n\n            use_wallet=\n",
        "            point_item_key=\n                payload.get(\n                    \"point_item_key\"\n                ),\n\n            benefit_coupon_id=\n                payload.get(\n                    \"benefit_coupon_id\"\n                ),\n\n            use_wallet=\n",
        label="site preview coupon arg",
    )
    write(path, text)


def patch_public_order_create() -> None:
    path = "web/app/services/public_order_create.py"
    text = read(path)
    text = replace_once(
        text,
        "        \"point_item_key\":\n            payload.get(\n                \"point_item_key\"\n            )\n            or None,\n\n        \"use_wallet\":\n",
        "        \"point_item_key\":\n            payload.get(\n                \"point_item_key\"\n            )\n            or None,\n\n        \"benefit_coupon_id\":\n            payload.get(\n                \"benefit_coupon_id\"\n            )\n            or None,\n\n        \"use_wallet\":\n",
        label="formal preview coupon candidate",
    )
    # Reserve coupon in the same DB transaction after order id exists.
    anchor = "\n\n    _write_acceptance_meta(\n        db,\n"
    insertion = '''\n\n    selected_coupon = preview.get("benefit_coupon") if isinstance(preview, dict) else None\n    if isinstance(selected_coupon, dict) and selected_coupon.get("id"):\n        from services.loyalty_benefits import reserve_coupon_in_session\n        reserve_coupon_in_session(\n            db,\n            coupon_id=int(selected_coupon["id"]),\n            customer_id=customer_id,\n            order_id=int(order.id),\n            rule_key=str(rule.key),\n            player_count=_first_int(\n                quote,\n                ("player_count",),\n                default=_to_int(payload.get("player_count"), 1),\n            ),\n        )\n'''
    if text.count(anchor) != 1:
        raise RuntimeError("formal order acceptance anchor not unique")
    text = text.replace(anchor, insertion + anchor, 1)
    write(path, text)


def patch_site_layout() -> None:
    path = "web/app/templates/site_layout.html"
    text = read(path)
    # Desktop account menu: /me becomes single member hub entry.
    text = regex_once(
        text,
        r'''\n                            <a href="/me/orders">\n                                我的訂單\n                            </a>\n\n                            <a href="/me#favorites">\n                                我的收藏\n                            </a>\n\n                            <a href="/me#vip">\n                                點數 / VIP\n                            </a>\n''',
        "\n",
        label="simplify desktop member menu",
    )
    text = text.replace('                <a href="/me/orders">我的訂單</a>\n', '')
    write(path, text)


def patch_member_center() -> None:
    path = "web/app/templates/member_center.html"
    text = read(path)
    # Add member hub shortcuts after existing order shortcut.
    anchor = '''            <a\n                class="member-action-card"\n                href="/order"\n            >\n                <small>ORDER</small>\n                <strong>前往點單</strong>\n                <span>\n                    查看服務與方案 →\n                </span>\n            </a>\n'''
    extra = anchor + '''\n            <a class="member-action-card" href="/me/wallet">\n                <small>WALLET</small><strong>錢包・儲值</strong>\n                <span>查看餘額、儲值與紀錄 →</span>\n            </a>\n\n            <a class="member-action-card" href="/me#favorites">\n                <small>FAVORITES</small><strong>我的收藏</strong>\n                <span>查看收藏的陪玩 →</span>\n            </a>\n\n            <a class="member-action-card" href="/me#vip">\n                <small>MEMBERSHIP</small><strong>點數 / VIP</strong>\n                <span>查看點數、等級與升級進度 →</span>\n            </a>\n\n            <a class="member-action-card" href="/me#benefits">\n                <small>BENEFITS</small><strong>我的福利</strong>\n                <span>查看福利券與累積進度 →</span>\n            </a>\n'''
    text = replace_once(text, anchor, extra, label="member hub shortcuts")

    # Add a benefit count stat before ORDERS stat.
    marker = '''        <article class="member-stat-card">\n            <small>\n                ORDERS\n            </small>\n'''
    benefit_stat = '''        <article class="member-stat-card">\n            <small>\n                BENEFITS\n            </small>\n\n            <strong>\n                {{ benefits.active_count }}\n            </strong>\n\n            <span>\n                可用福利券\n            </span>\n\n            <a href="/me#benefits" class="button button-primary" style="min-height:34px;padding:0 14px;margin-top:14px;border-radius:10px;font-size:12px;">\n                查看我的福利\n            </a>\n        </article>\n\n\n'''
    if text.count(marker) != 1:
        raise RuntimeError("member order stat marker not unique")
    text = text.replace(marker, benefit_stat + marker, 1)

    # Insert benefit panel before VIP panel.
    vip_marker = '''        <section\n            class="member-panel member-panel-wide"\n            id="vip"\n        >\n'''
    benefits_panel = '''        <section class="member-panel member-panel-wide" id="benefits">\n            <div class="member-panel-head">\n                <div>\n                    <small>BENEFITS</small>\n                    <h3>我的福利</h3>\n                </div>\n                <a href="/order">前往點單 →</a>\n            </div>\n\n            {% if benefits.coupons %}\n                <div class="member-order-list">\n                    {% for coupon in benefits.coupons %}\n                        <div class="member-order-row">\n                            <div>\n                                <small>AVAILABLE COUPON</small>\n                                <strong>{{ coupon.title }}</strong>\n                                <span>獲得時間 · {{ coupon.issued_at }}</span>\n                            </div>\n                            <div class="member-order-meta"><strong>可使用</strong></div>\n                        </div>\n                    {% endfor %}\n                </div>\n            {% endif %}\n\n            {% if benefits.progress %}\n                <div class="member-benefit-row" style="margin-top:14px;">\n                    {% for item in benefits.progress %}\n                        <div>\n                            <span>{{ item.title }}</span>\n                            <strong>{{ item.progress_text }} {{ '局' if item.pricing_type == 'game' else '小時' }}</strong>\n                            <span>達標自動發 {{ '+1 局' if item.pricing_type == 'game' else '+30 分鐘' }}</span>\n                        </div>\n                    {% endfor %}\n                </div>\n            {% endif %}\n\n            {% if not benefits.has_anything %}\n                <div class="member-empty">\n                    <span class="member-empty-icon">◇</span>\n                    <strong>目前還沒有累積進度</strong>\n                    <p>完成符合活動的付費服務後，才會開始顯示進度；0 進度的商品不會全部列在這裡。</p>\n                </div>\n            {% endif %}\n        </section>\n\n\n'''
    if text.count(vip_marker) != 1:
        raise RuntimeError("member vip marker not unique")
    text = text.replace(vip_marker, benefits_panel + vip_marker, 1)
    write(path, text)


def patch_order_template() -> None:
    path = "web/app/templates/order_catalog.html"
    text = read(path)
    point_control = '''                <label class="order-checkout-control">\n\n                    <span>\n                        點數福利\n                    </span>\n\n                    <select\n                        id="mw-checkout-point"\n                    >\n                        <option value="">\n                            不使用點數\n                        </option>\n                    </select>\n\n                    <small id="mw-checkout-point-note">\n                        選擇後由伺服器重新驗證資格\n                    </small>\n\n                </label>\n'''
    benefit_control = point_control + '''\n\n                <label class="order-checkout-control">\n                    <span>我的福利</span>\n                    <select id="mw-checkout-benefit">\n                        <option value="">不使用福利券</option>\n                    </select>\n                    <small id="mw-checkout-benefit-note">\n                        福利券與點數福利同張訂單擇一使用\n                    </small>\n                </label>\n'''
    text = replace_once(text, point_control, benefit_control, label="web benefit selector")
    text = text.replace(
        "/static/js/mw_order_quote.js?v=3c3b2r3-simple-checkout",
        "/static/js/mw_order_quote.js?v=member-benefits-v1",
    )
    write(path, text)


def patch_order_js() -> None:
    path = "web/app/static/js/mw_order_quote.js"
    text = read(path)
    text = replace_once(
        text,
        '''    const pointNote =\n        byId(\n            "mw-checkout-point-note"\n        );\n\n\n    const useWallet =\n''',
        '''    const pointNote =\n        byId(\n            "mw-checkout-point-note"\n        );\n\n\n    const benefitSelect =\n        byId(\n            "mw-checkout-benefit"\n        );\n\n\n    const benefitNote =\n        byId(\n            "mw-checkout-benefit-note"\n        );\n\n\n    const useWallet =\n''',
        label="JS benefit elements",
    )
    # Add renderer before renderCheckoutOptions.
    anchor = "\n\n    function renderCheckoutOptions(\n        data\n    ) {\n"
    renderer = '''\n\n    function renderBenefitCoupons(items) {\n        if (!benefitSelect) {\n            return;\n        }\n        benefitSelect.innerHTML = "";\n        const empty = document.createElement("option");\n        empty.value = "";\n        empty.textContent = "不使用福利券";\n        benefitSelect.append(empty);\n        (items || []).forEach(item => {\n            const option = document.createElement("option");\n            option.value = String(item.id || "");\n            option.textContent = item.title || "會員福利券";\n            benefitSelect.append(option);\n        });\n        if (benefitNote) {\n            benefitNote.textContent = (items || []).length\n                ? "福利券與點數福利同張訂單擇一使用"\n                : "這個方案目前沒有可用福利券";\n        }\n    }\n'''
    if text.count(anchor) != 1:
        raise RuntimeError("render checkout options anchor not unique")
    text = text.replace(anchor, renderer + anchor, 1)
    text = replace_once(
        text,
        "        renderPointOptions(\n            data.point_options\n        );\n\n\n        if (\n",
        "        renderPointOptions(\n            data.point_options\n        );\n\n        renderBenefitCoupons(\n            data.benefit_coupons\n        );\n\n\n        if (\n",
        label="render benefit options",
    )
    text = replace_once(
        text,
        "            point_item_key:\n                pointSelect.value\n                || null,\n\n            use_wallet: false,\n",
        "            point_item_key:\n                pointSelect.value\n                || null,\n\n            benefit_coupon_id:\n                benefitSelect?.value\n                || null,\n\n            use_wallet: false,\n",
        label="preview benefit payload",
    )
    # Formal payload has an identical block later; replace second occurrence too.
    if '            point_item_key:\n                pointSelect?.value\n                || null,\n\n            use_wallet: false,\n' in text:
        text = text.replace(
            '            point_item_key:\n                pointSelect?.value\n                || null,\n\n            use_wallet: false,\n',
            '            point_item_key:\n                pointSelect?.value\n                || null,\n\n            benefit_coupon_id:\n                benefitSelect?.value\n                || null,\n\n            use_wallet: false,\n',
            1,
        )
    else:
        raise RuntimeError("formal benefit payload anchor missing")

    text = replace_once(
        text,
        "        if (\n            finance.point_service_note\n        ) {\n\n            notes.push(\n                finance.point_service_note\n            );\n        }\n",
        "        if (\n            finance.point_service_note\n        ) {\n\n            notes.push(\n                finance.point_service_note\n            );\n        }\n\n        if (finance.benefit_service_note) {\n            notes.push(finance.benefit_service_note);\n        }\n",
        label="benefit summary note",
    )
    # Enforce one-of-two client side; server validates again.
    point_listener = '''    pointSelect?.addEventListener(\n        "change",\n        async () => {\n\n            const option =\n                pointSelect.options[\n                    pointSelect.selectedIndex\n                ];\n'''
    point_listener_new = '''    pointSelect?.addEventListener(\n        "change",\n        async () => {\n\n            if (pointSelect.value && benefitSelect) {\n                benefitSelect.value = "";\n            }\n\n            const option =\n                pointSelect.options[\n                    pointSelect.selectedIndex\n                ];\n'''
    text = replace_once(text, point_listener, point_listener_new, label="point clears benefit")
    benefit_listener_anchor = '''    useWallet?.addEventListener(\n        "change",\n        refreshCheckoutPreview\n    );\n'''
    benefit_listener = '''    benefitSelect?.addEventListener(\n        "change",\n        async () => {\n            if (benefitSelect.value && pointSelect) {\n                pointSelect.value = "";\n            }\n            await refreshCheckoutPreview();\n        }\n    );\n\n\n''' + benefit_listener_anchor
    text = replace_once(text, benefit_listener_anchor, benefit_listener, label="benefit change listener")
    text = replace_once(
        text,
        "            if (pointSelect) {\n\n                pointSelect.value =\n                    \"\";\n            }\n",
        "            if (pointSelect) {\n\n                pointSelect.value =\n                    \"\";\n            }\n\n            if (benefitSelect) {\n                benefitSelect.value = \"\";\n            }\n",
        label="reset benefit select",
    )
    write(path, text)


def patch_public_order_create_coupon_comment() -> None:
    # no-op hook kept so the script remains easy to extend if CI reveals old-order assumptions.
    return


def patch_cog() -> None:
    path = "cogs/staff_sync.py"
    text = read(path)
    text = replace_once(
        text,
        "from views.staff_profiles import (\n    get_staff_profile,\n    refresh_staff_profile_panel_for_staff,\n)\n",
        "from views.staff_profiles import (\n    get_staff_profile,\n    get_staff_profile_panel_rows,\n    refresh_staff_profile_panel_for_staff,\n)\nfrom services.loyalty_benefits import (\n    ensure_loyalty_tables,\n    process_closed_orders_since_start,\n    reconcile_coupon_reservations,\n)\nfrom views.member_portal import (\n    MEMBER_PORTAL_CHANNEL_ID,\n    MEMBER_PORTAL_MARKER,\n    MemberPortalView,\n    build_member_portal_embed,\n)\n",
        label="staff sync benefit imports",
    )
    text = replace_once(
        text,
        "STAFF_PROFILE_EVENT_INTERVAL_SECONDS = 5\n",
        "STAFF_PROFILE_EVENT_INTERVAL_SECONDS = 5\nLOYALTY_BENEFIT_INTERVAL_SECONDS = 15\n",
        label="loyalty interval",
    )
    text = replace_once(
        text,
        "        ensure_staff_profile_refresh_sync()\n",
        "        ensure_staff_profile_refresh_sync()\n        ensure_loyalty_tables()\n",
        label="ensure loyalty in cog",
    )
    text = replace_once(
        text,
        "        self.staff_profile_refresh_event_loop.start()\n",
        "        self.staff_profile_refresh_event_loop.start()\n        self.loyalty_benefit_loop.start()\n",
        label="start loyalty loop",
    )
    text = replace_once(
        text,
        "        self.staff_profile_refresh_event_loop.cancel()\n",
        "        self.staff_profile_refresh_event_loop.cancel()\n        self.loyalty_benefit_loop.cancel()\n",
        label="cancel loyalty loop",
    )

    # Insert real-reopen listener before voice state listener.
    marker = '''    @commands.Cog.listener()\n    async def on_voice_state_update(\n'''
    listener = '''    @commands.Cog.listener()\n    async def on_thread_update(\n        self,\n        before: discord.Thread,\n        after: discord.Thread,\n    ) -> None:\n        # Background sync no longer wakes archived profile threads. If Discord/users\n        # genuinely reopen one, refresh it once so the visible panel is current.\n        if not bool(getattr(before, "archived", False)) or bool(getattr(after, "archived", False)):\n            return\n        for profile in get_staff_profile_panel_rows():\n            if str(profile.get("forum_thread_id") or "") != str(after.id):\n                continue\n            staff_id = str(profile.get("staff_discord_id") or "").strip()\n            if not staff_id:\n                return\n            try:\n                await refresh_staff_profile_panel_for_staff(\n                    after.guild,\n                    staff_id,\n                    reason="thread_reopened",\n                )\n            except Exception as exc:\n                print(\n                    f"[staff-profile] reopen refresh failed staff_id={staff_id}: "\n                    f"{type(exc).__name__}: {exc}",\n                    flush=True,\n                )\n            return\n\n\n''' + marker
    text = replace_once(text, marker, listener, label="thread reopen listener")

    # Insert loyalty loop before staff profile event loop.
    marker2 = '''    @tasks.loop(seconds=STAFF_PROFILE_EVENT_INTERVAL_SECONDS)\n    async def staff_profile_refresh_event_loop(self) -> None:\n'''
    loyalty_loop = '''    async def _notify_issued_benefits(self, result: dict) -> None:\n        coupons = result.get("issued_coupons") or []\n        if not coupons:\n            return\n        channel_id = str(result.get("ticket_channel_id") or "").strip()\n        customer_id = str(result.get("customer_id") or "").strip()\n        if not channel_id or not customer_id:\n            return\n        try:\n            channel = self.bot.get_channel(int(channel_id))\n            if channel is None:\n                channel = await self.bot.fetch_channel(int(channel_id))\n            if not isinstance(channel, discord.TextChannel):\n                return\n            lines = "\\n".join(f"• {item.get('title')}" for item in coupons)\n            await channel.send(\n                f"<@{customer_id}> 🎁 **會員累積福利已入帳**\\n{lines}\\n"\n                "已放進「我的福利」，下次點同方案即可使用。",\n                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),\n            )\n        except (discord.Forbidden, discord.NotFound, discord.HTTPException) as exc:\n            print(f"[loyalty] ticket notification failed order={result.get('order_id')}: {exc}", flush=True)\n\n    @tasks.loop(seconds=LOYALTY_BENEFIT_INTERVAL_SECONDS)\n    async def loyalty_benefit_loop(self) -> None:\n        try:\n            results = await asyncio.to_thread(process_closed_orders_since_start, 200)\n            await asyncio.to_thread(reconcile_coupon_reservations, 200)\n        except Exception as exc:\n            print(f"[loyalty] reconcile failed: {type(exc).__name__}: {exc}", flush=True)\n            return\n        for result in results:\n            await self._notify_issued_benefits(result)\n\n    @loyalty_benefit_loop.before_loop\n    async def before_loyalty_benefit_loop(self) -> None:\n        await self.bot.wait_until_ready()\n\n\n''' + marker2
    text = replace_once(text, marker2, loyalty_loop, label="loyalty event loop")

    # Ensure the fixed member portal panel and persistent callbacks on ready.
    marker3 = '''    @commands.Cog.listener()\n    async def on_voice_state_update(\n'''
    onready = '''    @commands.Cog.listener()\n    async def on_ready(self) -> None:\n        if not getattr(self.bot, "_member_portal_view_registered", False):\n            self.bot.add_view(MemberPortalView())\n            self.bot._member_portal_view_registered = True\n\n        channel = self.bot.get_channel(MEMBER_PORTAL_CHANNEL_ID)\n        if channel is None:\n            try:\n                channel = await self.bot.fetch_channel(MEMBER_PORTAL_CHANNEL_ID)\n            except (discord.Forbidden, discord.NotFound, discord.HTTPException):\n                channel = None\n        if not isinstance(channel, discord.TextChannel) or self.bot.user is None:\n            return\n\n        existing = None\n        try:\n            async for message in channel.history(limit=50):\n                if message.author.id != self.bot.user.id or not message.embeds:\n                    continue\n                if str(message.embeds[0].footer.text or "") == MEMBER_PORTAL_MARKER:\n                    existing = message\n                    break\n        except (discord.Forbidden, discord.HTTPException):\n            return\n\n        try:\n            if existing is None:\n                await channel.send(embed=build_member_portal_embed(), view=MemberPortalView())\n            else:\n                await existing.edit(embed=build_member_portal_embed(), view=MemberPortalView())\n        except (discord.Forbidden, discord.HTTPException) as exc:\n            print(f"[member-portal] panel refresh failed: {exc}", flush=True)\n\n\n''' + marker3
    # marker3 now exists once after prior replacement as part of inserted listener.
    text = replace_once(text, marker3, onready, label="member portal on ready")
    write(path, text)


def patch_self_service_runtime() -> None:
    path = "services/self_service_runtime.py"
    text = read(path)
    # Replace stale Discord point spec catalog with current canonical keys.
    text = regex_once(
        text,
        r"ORDER_POINT_BENEFIT_SPECS = \{.*?\n\}\n\n",
        '''ORDER_POINT_BENEFIT_SPECS = {\n    "discount_20": {"kind": "cash_discount", "amount": 20, "summary": "20T 折價券，店內吸收，不影響陪玩分潤"},\n    "discount_30": {"kind": "cash_discount", "amount": 30, "summary": "30T 折價券，店內吸收，不影響陪玩分潤"},\n    "free_specify_fee": {"kind": "free_specify_fee", "summary": "免指定費，指定費由店內吸收，陪玩應得不減少"},\n    "discount_100": {"kind": "cash_discount", "amount": 100, "summary": "100T 折價券，店內吸收，不影響陪玩分潤"},\n    "extra_hour_30m": {"kind": "extra_hours", "hours": 0.5, "pricing_types": ("hourly",), "summary": "服務時間 +30 分鐘，由店內吸收額外服務成本"},\n    "extra_hour_1h": {"kind": "extra_hours", "hours": 1, "pricing_types": ("hourly",), "summary": "服務時間 +1 小時，由店內吸收額外服務成本"},\n    "extra_game_1": {"kind": "extra_games", "games": 1, "pricing_types": ("game",), "summary": "服務局數 +1 局，由店內吸收額外服務成本"},\n    "extra_game_2": {"kind": "extra_games", "games": 2, "pricing_types": ("game",), "summary": "服務局數 +2 局，由店內吸收額外服務成本"},\n}\n\n''',
        label="Discord point benefit specs",
        flags=re.S,
    )
    # Replace allow logic tail to respect pricing_types/current keys.
    old = '''    if kind == "free_first_hour":\n        if str(getattr(rule, "key", "")) not in FREE_PLAY_FIRST_HOUR_RULE_KEYS:\n            return False, "免費陪玩 1 小時只適用娛樂陪單/雙陪與機密技術單/雙護。"\n        if pricing_type != "hourly":\n            return False, "免費陪玩 1 小時只適用小時計價項目。"\n\n    if kind == "extra_game" and category in {"valorant", "lol"}:\n        return False, "特戰英豪 / 英雄聯盟不可使用加場一場保撤。"\n\n    if kind == "extra_hours" and pricing_type not in {"hourly", "game"}:\n        return False, "加時只適用小時或局數計價項目。"\n\n    if kind == "extra_game" and pricing_type != "game":\n        return False, "加場保撤只適用局數計價項目。"\n\n    return True, ""\n'''
    new = '''    pricing_types = tuple(spec.get("pricing_types") or ())\n    if pricing_types and pricing_type not in pricing_types:\n        return False, "這個點數福利不適用此計價方式。"\n\n    if kind == "extra_hours" and pricing_type != "hourly":\n        return False, "加時只適用計時方案。"\n\n    if kind == "extra_games" and pricing_type != "game":\n        return False, "加局只適用計局方案。"\n\n    return True, ""\n'''
    text = replace_once(text, old, new, label="Discord point eligibility")
    text = regex_once(
        text,
        r"def _adapt_order_point_benefit_for_rule\(rule, benefit: dict\) -> dict:\n.*?\n(?=def get_selected_order_point_benefit)",
        "def _adapt_order_point_benefit_for_rule(rule, benefit: dict) -> dict:\n    return dict(benefit or {})\n\n\n",
        label="remove hidden point transforms",
        flags=re.S,
    )
    text = text.replace("不需要再花 25 點兌換。", "不需要再使用免指定費福利。")

    # Add coupon helpers inside finance before allocation result.
    point_anchor = '''    allocation = allocate_store_absorbed_fixed_discount(\n        after_percent_amount=after_percent,\n        fixed_discount_amount=fixed,\n        additional_store_discount_amount=point_cash,\n        extra_customer_charge_amount=specify_effective,\n    )\n\n    # 百分比折扣仍會降低分潤基準；\n    # 客服固定金額折扣與點數折價都由店內吸收，不影響打手分潤。\n    payout_base = allocation.payout_base_amount\n    customer_pay = allocation.customer_pay_amount\n'''
    finance_new = '''    allocation = allocate_store_absorbed_fixed_discount(\n        after_percent_amount=after_percent,\n        fixed_discount_amount=fixed,\n        additional_store_discount_amount=point_cash,\n        extra_customer_charge_amount=specify_effective,\n    )\n\n    from services.loyalty_benefits import (\n        calculate_coupon_service_value,\n        coupon_service_note,\n        get_applicable_coupon,\n    )\n\n    selected_coupon = None\n    selected_coupon_id = data.get("selected_benefit_coupon_id")\n    if selected_coupon_id not in (None, ""):\n        if benefit is not None:\n            raise ValueError("福利券與點數福利同張訂單只能擇一使用。")\n        customer_id = data.get("customer_id")\n        if customer_id:\n            selected_coupon = get_applicable_coupon(\n                selected_coupon_id,\n                customer_id=customer_id,\n                rule_key=str(getattr(rule, "key", "")),\n                player_count=_to_int(data.get("player_count"), 1) or 1,\n            )\n        if selected_coupon is None:\n            raise ValueError("這張福利券已使用、已保留，或不適用這個方案。")\n\n    quantity_for_extra = max(1, _to_int(data.get("quantity"), 1) or 1)\n    point_service_value = 0\n    if extra_hours > 0:\n        point_service_value = max(0, int(round((service_original / quantity_for_extra) * extra_hours)))\n    elif extra_games > 0:\n        point_service_value = max(0, int(round((service_original / quantity_for_extra) * extra_games)))\n\n    benefit_service_value = calculate_coupon_service_value(\n        rule_key=str(getattr(rule, "key", "")),\n        player_count=_to_int(data.get("player_count"), 1) or 1,\n        coupon=selected_coupon,\n    )\n\n    # 百分比/VIP折扣只影響顧客付款。點數、免指定費與福利券都由店內吸收，\n    # 額外服務用商品正常原價補進陪玩分潤基底。\n    payout_base = (\n        allocation.payout_base_amount\n        + point_specify\n        + point_service_value\n        + benefit_service_value\n    )\n    customer_pay = allocation.customer_pay_amount\n'''
    text = replace_once(text, point_anchor, finance_new, label="Discord funded benefits finance")
    text = replace_once(
        text,
        '        "store_absorbed_amount": (\n            allocation.store_absorbed_amount\n        ),\n',
        '        "benefit_coupon_id": (int(selected_coupon.get("id")) if selected_coupon else None),\n        "benefit_coupon_title": (str(selected_coupon.get("title") or "") if selected_coupon else ""),\n        "benefit_service_note": coupon_service_note(selected_coupon),\n        "benefit_service_value": benefit_service_value,\n        "point_service_value": point_service_value,\n\n        "store_absorbed_amount": (\n            allocation.store_absorbed_amount\n            + point_specify\n            + point_service_value\n            + benefit_service_value\n        ),\n',
        label="Discord benefit finance return",
    )

    # Combine point/coupon selection in existing ephemeral selector.
    text = replace_once(
        text,
        '''        for item in parent_view.available_items:\n            options.append(\n                discord.SelectOption(\n                    label=_truncate_select_text(f"{item['cost']} 點｜{item['name']}"),\n                    value=str(item["key"]),\n                    description=_truncate_select_text(item.get("summary") or f"兌換 {item['name']}"),\n                    default=str(item["key"]) == str(parent_view.selected_key),\n                )\n            )\n''',
        '''        for coupon in parent_view.available_coupons:\n            options.append(\n                discord.SelectOption(\n                    label=_truncate_select_text(str(coupon.get("title") or "會員福利券")),\n                    value=f"coupon:{coupon['id']}",\n                    description="使用累積福利券；與點數福利擇一",\n                    default=str(coupon.get("id")) == str(parent_view.selected_coupon_id),\n                )\n            )\n\n        for item in parent_view.available_items:\n            options.append(\n                discord.SelectOption(\n                    label=_truncate_select_text(f"{item['cost']} 點｜{item['name']}"),\n                    value=f"point:{item['key']}",\n                    description=_truncate_select_text(item.get("summary") or f"兌換 {item['name']}"),\n                    default=str(item["key"]) == str(parent_view.selected_key),\n                )\n            )\n''',
        label="Discord combined benefit options",
    )
    # Rewrite select callback choice dispatch.
    text = replace_once(
        text,
        '''        if selected == "none":\n            for key in (\n                "selected_point_benefit_key",\n                "point_benefit_key",\n                "point_benefit_name",\n                "point_benefit_cost",\n                "point_discount_coupon_amount",\n                "point_waived_specify_fee",\n                "point_extra_hours",\n                "point_extra_games",\n                "service_bonus_text",\n            ):\n                data.pop(key, None)\n        else:\n            item = get_order_point_item(selected)\n\n            if item is None:\n                await interaction.response.send_message("找不到這個點數福利，請重新選擇。", ephemeral=True)\n                return\n\n            data["selected_point_benefit_key"] = str(selected)\n            data["point_benefit_key"] = str(selected)\n            data["point_benefit_name"] = str(item.get("name") or selected)\n            data["point_benefit_cost"] = int(item.get("cost") or 0)\n''',
        '''        clear_keys = (\n            "selected_point_benefit_key",\n            "selected_benefit_coupon_id",\n            "point_benefit_key",\n            "point_benefit_name",\n            "point_benefit_cost",\n            "point_discount_coupon_amount",\n            "point_waived_specify_fee",\n            "point_extra_hours",\n            "point_extra_games",\n            "service_bonus_text",\n            "benefit_coupon_id",\n            "benefit_coupon_title",\n            "benefit_service_note",\n        )\n        for key in clear_keys:\n            data.pop(key, None)\n\n        if selected.startswith("coupon:"):\n            try:\n                data["selected_benefit_coupon_id"] = int(selected.split(":", 1)[1])\n            except (TypeError, ValueError):\n                await interaction.response.send_message("福利券格式錯誤，請重新選擇。", ephemeral=True)\n                return\n        elif selected.startswith("point:"):\n            point_key = selected.split(":", 1)[1]\n            item = get_order_point_item(point_key)\n            if item is None:\n                await interaction.response.send_message("找不到這個點數福利，請重新選擇。", ephemeral=True)\n                return\n            data["selected_point_benefit_key"] = point_key\n            data["point_benefit_key"] = point_key\n            data["point_benefit_name"] = str(item.get("name") or point_key)\n            data["point_benefit_cost"] = int(item.get("cost") or 0)\n''',
        label="Discord combined selection callback",
    )
    text = replace_once(
        text,
        "        self.selected_key = data.get(\"selected_point_benefit_key\")\n        self.point_balance = get_customer_point_balance_for_order(customer_id)\n        self.available_items = self.build_available_items(data)\n",
        "        self.selected_key = data.get(\"selected_point_benefit_key\")\n        self.selected_coupon_id = data.get(\"selected_benefit_coupon_id\")\n        self.point_balance = get_customer_point_balance_for_order(customer_id)\n        self.available_items = self.build_available_items(data)\n        from services.loyalty_benefits import list_applicable_coupons\n        self.available_coupons = list_applicable_coupons(\n            customer_id,\n            rule_key=str(getattr(rule, \"key\", \"\")),\n            player_count=_to_int(data.get(\"player_count\"), 1) or 1,\n        )\n",
        label="Discord coupon options state",
    )
    text = replace_once(
        text,
        '''        benefit = get_selected_order_point_benefit(data, self.rule)\n        selected_text = "尚未使用"\n\n        if benefit:\n            selected_text = f"{benefit['cost']} 點｜{benefit['name']}"\n\n        return (\n            f"請選擇這張單要使用的點數福利。\\n"\n            f"目前可用點數：{self.point_balance} 點\\n"\n            f"目前選擇：{selected_text}\\n\\n"\n            "提醒：這裡只是先保留在訂單上，付款成立時才會正式扣點。"\n        )\n''',
        '''        benefit = get_selected_order_point_benefit(data, self.rule)\n        selected_text = "尚未使用"\n\n        if data.get("selected_benefit_coupon_id"):\n            coupon = next(\n                (item for item in self.available_coupons if str(item.get("id")) == str(data.get("selected_benefit_coupon_id"))),\n                None,\n            )\n            if coupon:\n                selected_text = str(coupon.get("title") or "會員福利券")\n        elif benefit:\n            selected_text = f"{benefit['cost']} 點｜{benefit['name']}"\n\n        return (\n            f"請選擇這張單要使用的點數福利或會員福利券。\\n"\n            f"目前可用點數：{self.point_balance} 點\\n"\n            f"可用福利券：{len(self.available_coupons)} 張\\n"\n            f"目前選擇：{selected_text}\\n\\n"\n            "同張訂單只能擇一；福利券會在訂單建立時先保留，結單後正式核銷。"\n        )\n''',
        label="Discord benefit selector message",
    )
    # Add benefit note to quote preview after point benefit line.
    text = replace_once(
        text,
        '''        if adjustment["point_benefit_name"]:\n            point_text = f"{adjustment['point_benefit_cost']} 點｜{adjustment['point_benefit_name']}"\n            if adjustment["service_bonus_text"]:\n                point_text += f"｜{adjustment['service_bonus_text']}"\n            lines.append(("點數福利", point_text))\n''',
        '''        if adjustment["point_benefit_name"]:\n            point_text = f"{adjustment['point_benefit_cost']} 點｜{adjustment['point_benefit_name']}"\n            if adjustment["service_bonus_text"]:\n                point_text += f"｜{adjustment['service_bonus_text']}"\n            lines.append(("點數福利", point_text))\n\n        if adjustment.get("benefit_coupon_title"):\n            lines.append(("我的福利", str(adjustment["benefit_coupon_title"])))\n''',
        label="Discord quote benefit display",
    )
    # Persist fields in price snapshot/data.
    text = replace_once(
        text,
        '        "store_absorbed_amount": price_adjustment.get("store_absorbed_amount"),\n',
        '        "benefit_coupon_id": price_adjustment.get("benefit_coupon_id"),\n        "benefit_coupon_title": price_adjustment.get("benefit_coupon_title"),\n        "benefit_service_value": price_adjustment.get("benefit_service_value"),\n        "benefit_service_note": price_adjustment.get("benefit_service_note"),\n        "store_absorbed_amount": price_adjustment.get("store_absorbed_amount"),\n',
        label="Discord price snapshot coupon",
    )
    # There are later data assignments too; add after service bonus assignment.
    text = replace_once(
        text,
        '    data["service_bonus_text"] = price_adjustment["service_bonus_text"]\n    data["store_absorbed_amount"] = price_adjustment["store_absorbed_amount"]\n',
        '    data["service_bonus_text"] = price_adjustment["service_bonus_text"]\n    data["benefit_coupon_id"] = price_adjustment.get("benefit_coupon_id")\n    data["benefit_coupon_title"] = price_adjustment.get("benefit_coupon_title")\n    data["benefit_service_value"] = price_adjustment.get("benefit_service_value")\n    data["benefit_service_note"] = price_adjustment.get("benefit_service_note")\n    data["store_absorbed_amount"] = price_adjustment["store_absorbed_amount"]\n',
        label="Discord order data coupon",
    )
    # Reserve the selected coupon after web order id is known.
    reserve_anchor = '''    try:\n        from shared.db import engine as _rule_snapshot_engine\n        from sqlalchemy import text as _rule_snapshot_sql_text\n\n        with _rule_snapshot_engine.begin() as _rule_snapshot_conn:\n'''
    reserve_code = '''    if price_adjustment.get("benefit_coupon_id"):\n        from services.loyalty_benefits import reserve_coupon_for_order\n        reserve_coupon_for_order(\n            coupon_id=int(price_adjustment["benefit_coupon_id"]),\n            customer_id=customer_id,\n            order_id=int(web_order.id),\n            rule_key=str(rule.key),\n            player_count=player_count,\n        )\n\n'''
    if text.count(reserve_anchor) < 1:
        raise RuntimeError("Discord rule snapshot anchor missing")
    text = text.replace(reserve_anchor, reserve_code + reserve_anchor, 1)
    write(path, text)


def patch_bot_point_catalog() -> None:
    path = "bot.py"
    text = read(path)
    # Keep standalone redeem panel and Discord order flow on the same current catalog.
    pattern = r"POINT_REDEEM_ITEMS = \[.*?\n\]\n\nPOINT_REDEEM_ITEMS_BY_KEY ="
    replacement = '''POINT_REDEEM_ITEMS = [\n    {"key": "discount_20", "cost": 10, "name": "20T 折價券"},\n    {"key": "discount_30", "cost": 15, "name": "30T 折價券"},\n    {"key": "free_specify_fee", "cost": 30, "name": "免指定費 1 次"},\n    {"key": "discount_100", "cost": 45, "name": "100T 折價券"},\n    {"key": "extra_hour_30m", "cost": 60, "name": "加時 30 分鐘"},\n    {"key": "extra_hour_1h", "cost": 110, "name": "加時 1 小時"},\n    {"key": "extra_game_1", "cost": 40, "name": "加 1 局"},\n    {"key": "extra_game_2", "cost": 70, "name": "加 2 局"},\n]\n\nPOINT_REDEEM_ITEMS_BY_KEY ='''
    text, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"bot point catalog: expected 1 block, got {count}")
    write(path, text)


def patch_tests() -> None:
    # Archived profile test should now guarantee background sync never wakes a wall.
    path = "tests/test_staff_profile_archived_thread_refresh.py"
    if (ROOT / path).exists():
        text = read(path)
        text = text.replace(
            "test_archived_public_profile_thread_is_reopened_and_left_active",
            "test_archived_public_profile_thread_stays_archived_during_background_refresh",
        )
        text = text.replace("assert channel.edit_calls", "assert not channel.edit_calls")
        text = text.replace("assert channel.archived is False", "assert channel.archived is True")
        write(path, text)

    (ROOT / "tests/test_loyalty_benefits.py").write_text('''from __future__ import annotations\n\nfrom pathlib import Path\n\nfrom sqlalchemy import create_engine, text\n\nfrom services import loyalty_benefits as loyalty\nfrom services.order_rules import ORDER_RULES, get_service_quantity\n\n\ndef test_same_order_five_for_one_is_disabled():\n    assert get_service_quantity(ORDER_RULES["basic_entertain_single"], 5) == 5\n    assert ORDER_RULES["basic_entertain_single"].loyalty_benefits_enabled is True\n\n\ndef test_old_valorant_rules_are_removed():\n    assert "valorant_entertain" not in ORDER_RULES\n    assert "valorant_tech" not in ORDER_RULES\n    assert "valorant_top_tech" not in ORDER_RULES\n\n\ndef test_zero_progress_is_not_listed(monkeypatch, tmp_path: Path):\n    db = tmp_path / "loyalty.db"\n    test_engine = create_engine(f"sqlite:///{db}", connect_args={"check_same_thread": False})\n    monkeypatch.setattr(loyalty, "engine", test_engine)\n    loyalty.ensure_loyalty_tables(test_engine)\n    assert loyalty.list_customer_loyalty("1")["progress"] == []\n\n\ndef test_coupon_value_uses_normal_list_price_not_vip_discount():\n    coupon = {"benefit_kind": "extra_hours", "benefit_units": 0.5}\n    value = loyalty.calculate_coupon_service_value(\n        rule_key="basic_entertain_single",\n        player_count=1,\n        coupon=coupon,\n    )\n    assert value == 160\n''', encoding="utf-8")


def main() -> None:
    patch_order_rules()
    patch_loyalty_service()
    patch_shared_db()
    patch_staff_profiles()
    patch_checkout_preview()
    patch_site_router()
    patch_public_order_create()
    patch_site_layout()
    patch_member_center()
    patch_order_template()
    patch_order_js()
    patch_cog()
    patch_self_service_runtime()
    patch_bot_point_catalog()
    patch_tests()
    print("member benefits portal patch applied")


if __name__ == "__main__":
    main()
