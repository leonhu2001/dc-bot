from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file = Path(path)
    text = file.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}")
    file.write_text(text.replace(old, new, 1), encoding="utf-8")


# Admin route: bulk recipients + non-transactional Discord DM notifications.
replace_once(
    "web/app/routers/admin_benefits.py",
    "from __future__ import annotations\n\nimport sqlite3\n",
    "from __future__ import annotations\n\nimport asyncio\nimport sqlite3\n",
)
replace_once(
    "web/app/routers/admin_benefits.py",
    "    revoke_issued_benefit,\n)\n\n\nrouter = APIRouter(tags=[\"admin-benefits\"])\n",
    "    revoke_issued_benefit,\n)\nfrom services.promotion_benefit_presentation import (\n    build_benefit_grant_dm,\n    list_customer_promotion_benefits,\n)\nfrom web.app.services.discord_service import send_direct_message\n\n\nrouter = APIRouter(tags=[\"admin-benefits\"])\n",
)
old_issue = '''@router.post("/admin/benefits/issue")
async def issue_customer_benefit(request: Request):
    user = _admin(request)
    if user is None:
        return RedirectResponse(url="/", status_code=303)

    form = await request.form()
    customer_id = str(form.get("customer_discord_id") or "").strip()
    template_id = str(form.get("template_id") or "").strip()
    template = get_template(template_id) if template_id else None
    if template is None:
        return _redirect("請選擇有效的福利模板。", customer_id=customer_id)
    if bool(template.get("is_high_risk")) and not bool(user.get("is_manager")):
        return _redirect("這是高風險福利模板，只能由管理員發放。", customer_id=customer_id)

    try:
        issued_id = issue_benefit(
            template_id=template_id,
            customer_discord_id=customer_id,
            actor_discord_id=user.get("id"),
            note=str(form.get("note") or ""),
            expires_at=str(form.get("expires_at") or "").strip() or None,
        )
    except ValueError as exc:
        return _redirect(str(exc), customer_id=customer_id)
    return _redirect(f"已發放福利 #{issued_id}。", customer_id=customer_id)
'''
new_issue = '''@router.post("/admin/benefits/issue")
async def issue_customer_benefit(request: Request):
    user = _admin(request)
    if user is None:
        return RedirectResponse(url="/", status_code=303)

    form = await request.form()
    customer_ids = [
        str(value or "").strip()
        for value in form.getlist("customer_discord_ids")
        if str(value or "").strip()
    ]
    legacy_customer_id = str(form.get("customer_discord_id") or "").strip()
    if legacy_customer_id:
        customer_ids.append(legacy_customer_id)
    customer_ids = list(dict.fromkeys(customer_ids))
    selected_customer = customer_ids[0] if len(customer_ids) == 1 else ""
    if not customer_ids:
        return _redirect("請至少選擇一位要發放的會員。")

    template_id = str(form.get("template_id") or "").strip()
    template = get_template(template_id) if template_id else None
    if template is None:
        return _redirect("請選擇有效的福利模板。", customer_id=selected_customer)
    if bool(template.get("is_high_risk")) and not bool(user.get("is_manager")):
        return _redirect("這是高風險福利模板，只能由管理員發放。", customer_id=selected_customer)

    note = str(form.get("note") or "")
    expires_at = str(form.get("expires_at") or "").strip() or None
    issued_count = 0
    issue_failed = 0
    dm_failed = 0

    for customer_id in customer_ids:
        try:
            issued_id = issue_benefit(
                template_id=template_id,
                customer_discord_id=customer_id,
                actor_discord_id=user.get("id"),
                note=note,
                expires_at=expires_at,
            )
        except ValueError:
            issue_failed += 1
            continue

        issued_count += 1
        try:
            item = next(
                (
                    benefit
                    for benefit in list_customer_promotion_benefits(
                        customer_id,
                        active_only=False,
                        limit=20,
                    )
                    if int(benefit.get("id") or 0) == int(issued_id)
                ),
                None,
            )
            if item is None:
                raise RuntimeError("issued benefit could not be reloaded")
            await asyncio.to_thread(
                send_direct_message,
                customer_id,
                content=build_benefit_grant_dm(item),
            )
        except Exception as exc:
            dm_failed += 1
            print(
                f"[benefits] DM failed customer={customer_id}: {type(exc).__name__}: {exc}",
                flush=True,
            )

    if issued_count == 0:
        return _redirect("福利發放失敗，請重新確認會員與模板。", customer_id=selected_customer)

    message = f"已發放福利給 {issued_count} 位會員"
    if issue_failed:
        message += f"，另有 {issue_failed} 位發放失敗"
    if dm_failed:
        message += f"；其中 {dm_failed} 位 Discord 私訊未送達，但福利仍已入帳"
    else:
        message += "；Discord 私訊通知已送出"
    return _redirect(message + "。", customer_id=selected_customer)
'''
replace_once("web/app/routers/admin_benefits.py", old_issue, new_issue)

# Admin template: searchable checkbox multi-picker.
old_member = '''                <label>
                    會員
                    <select class="benefit-member-select" name="customer_discord_id" required>
                        <option value="">選擇會員</option>
                        {% if selected_customer %}
                        <option value="{{ selected_customer }}" selected>{{ selected_customer }}</option>
                        {% endif %}
                        {% for customer in customers if customer.customer_discord_id != selected_customer %}
                        <option value="{{ customer.customer_discord_id }}">
                            {{ customer.display_name }} · {{ customer.customer_discord_id }}
                        </option>
                        {% endfor %}
                    </select>
                </label>
'''
new_member = '''                <div class="benefit-picker-section">
                    <div class="benefit-picker-head">
                        <div>
                            <strong>目標會員</strong>
                            <small data-benefit-member-count>已選 0 位</small>
                        </div>
                        <input class="benefit-filter-input" type="search" placeholder="搜尋會員名稱或 Discord ID" data-benefit-filter="benefit-member-picker">
                    </div>
                    <div class="benefit-check-grid" id="benefit-member-picker">
                        {% for customer in customers %}
                        <label class="benefit-check-row" data-benefit-option="{{ customer.display_name }} {{ customer.customer_discord_id }}">
                            <input type="checkbox" name="customer_discord_ids" value="{{ customer.customer_discord_id }}" data-benefit-member-checkbox {% if customer.customer_discord_id == selected_customer %}checked{% endif %}>
                            <span><b>{{ customer.display_name }}</b><small>{{ customer.customer_discord_id }}</small></span>
                        </label>
                        {% endfor %}
                    </div>
                </div>
'''
replace_once("web/app/templates/admin_benefits.html", old_member, new_member)
replace_once(
    "web/app/templates/admin_benefits.html",
    '<form class="benefit-form" method="post" action="/admin/benefits/issue">',
    '<form class="benefit-form" method="post" action="/admin/benefits/issue" data-benefit-issue-form>',
)
replace_once(
    "web/app/templates/admin_benefits.html",
    '/static/js/pages/admin_benefits.js?v=20261018',
    '/static/js/pages/admin_benefits.js?v=20261018-2',
)

# Admin JS: selected count and client-side empty-selection guard.
replace_once(
    "web/app/static/js/pages/admin_benefits.js",
    "  document.querySelectorAll('[data-benefit-filter]').forEach((input) => {",
    '''  const memberCheckboxes = Array.from(document.querySelectorAll('[data-benefit-member-checkbox]'));
  const memberCount = document.querySelector('[data-benefit-member-count]');
  const issueForm = document.querySelector('[data-benefit-issue-form]');
  const refreshMemberCount = () => {
    if (!memberCount) return;
    const count = memberCheckboxes.filter((checkbox) => checkbox.checked).length;
    memberCount.textContent = `已選 ${count} 位`;
  };
  memberCheckboxes.forEach((checkbox) => checkbox.addEventListener('change', refreshMemberCount));
  refreshMemberCount();
  if (issueForm) {
    issueForm.addEventListener('submit', (event) => {
      if (memberCheckboxes.some((checkbox) => checkbox.checked)) return;
      event.preventDefault();
      window.alert('請至少選擇一位要發放的會員。');
    });
  }

  document.querySelectorAll('[data-benefit-filter]').forEach((input) => {''',
)

# Web member center: merge active promotion grants into existing loyalty display.
replace_once(
    "web/app/routers/site.py",
    "from services.loyalty_benefits import list_customer_loyalty\n",
    "from services.loyalty_benefits import list_customer_loyalty\nfrom services.promotion_benefit_presentation import list_customer_promotion_benefits\n",
)
replace_once(
    "web/app/routers/site.py",
    '''    portal = build_customer_portal_snapshot(
        customer_id,
        guild_id=config.DISCORD_GUILD_ID,
    )

    return templates.TemplateResponse(
''',
    '''    portal = build_customer_portal_snapshot(
        customer_id,
        guild_id=config.DISCORD_GUILD_ID,
    )
    benefits = dict(list_customer_loyalty(customer_id))
    promotions = list_customer_promotion_benefits(customer_id, active_only=True)
    benefits["promotions"] = promotions
    benefits["active_count"] = int(benefits.get("active_count") or 0) + len(promotions)

    return templates.TemplateResponse(
''',
)
replace_once(
    "web/app/routers/site.py",
    "            benefits=list_customer_loyalty(customer_id),\n",
    "            benefits=benefits,\n",
)

old_web_benefits = '''            {% if benefits.coupons %}
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
'''
new_web_benefits = '''            {% if benefits.promotions or benefits.coupons %}
                <div class="mc-coupon-stack">
                {% for coupon in benefits.promotions[:4] %}
                    <div class="mc-coupon">
                        <div><small>ISSUED BENEFIT</small><b>{{ coupon.title }}</b></div>
                        <span>{{ coupon.effect_text }} · 剩 {{ coupon.remaining_uses }} 次 · 有效至 {{ coupon.expires_at_text }}</span>
                    </div>
                {% endfor %}
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
'''
replace_once("web/app/templates/member_center.html", old_web_benefits, new_web_benefits)

# Discord member portal: show the same active promotion grants.
replace_once(
    "views/member_portal.py",
    "from services.loyalty_benefits import list_customer_loyalty\n",
    "from services.loyalty_benefits import list_customer_loyalty\nfrom services.promotion_benefit_presentation import list_customer_promotion_benefits\n",
)
replace_once(
    "views/member_portal.py",
    '''        coupons = benefits.get("coupons") or []
        progress = benefits.get("progress") or []
        embed = discord.Embed(
''',
    '''        coupons = benefits.get("coupons") or []
        progress = benefits.get("progress") or []
        promotions = list_customer_promotion_benefits(customer_id, active_only=True)
        embed = discord.Embed(
''',
)
replace_once(
    "views/member_portal.py",
    '''        cash_rows = monthly.get("cash_benefits") or []
''',
    '''        if promotions:
            promo_lines = [
                f"🎟️ **{item['title']}**｜{item['effect_text']}｜剩 {item['remaining_uses']} 次｜有效至 {item['expires_at_text']}"
                for item in promotions[:5]
            ]
            if len(promotions) > 5:
                promo_lines.append(f"另有 {len(promotions) - 5} 張可到網站會員中心查看。")
            embed.add_field(name="已發放福利券", value="\\n".join(promo_lines), inline=False)

        cash_rows = monthly.get("cash_benefits") or []
''',
)

# Existing source-contract test now describes the new member picker.
replace_once(
    "tests/test_promotion_benefit_admin.py",
    '''    assert 'name="scope_category_values"' in template
''',
    '''    assert 'name="customer_discord_ids"' in template
    assert 'data-benefit-filter="benefit-member-picker"' in template
    assert 'data-benefit-member-count' in template
    assert 'name="scope_category_values"' in template
''',
)
