from __future__ import annotations

import discord

from services.staff_internal_ammo_dump_policy import (
    is_internal_ammo_dump_rule,
    selected_ammo_dump_named,
)


def render_self_service_financial_breakdown_fields(
    embed: discord.Embed,
    src: dict,
    final_label="顧客應付",
):
    # Resolve dependencies at invocation time: the legacy finance runtime
    # initializes _to_int and other callbacks during bot startup.
    from services import self_service_financials as finance

    _price_int = finance._price_int
    _price_rate = finance._price_rate
    _format_plain_amount = finance._format_plain_amount
    _format_percent_value = finance._format_percent_value
    _to_int = finance._to_int
    src = dict(src or {})
    original = max(
        0,
        _price_int(src, "service_original_amount", "original_amount", default=0),
    )
    percent_off = max(
        0,
        _price_int(src, "percent_discount_amount", "manual_discount_amount", default=0),
    )
    fixed = max(
        0,
        _price_int(src, "fixed_discount_amount", "cash_coupon_amount", default=0),
    )
    point_cash = max(0, _price_int(src, "point_discount_coupon_amount", default=0))
    specify_before = max(0, _price_int(src, "specified_fee_before_waiver", default=0))
    point_specify = max(0, _price_int(src, "point_waived_specify_fee", default=0))
    specify_effective = src.get("effective_specify_fee")
    if specify_effective is None:
        specify_effective = max(0, specify_before - point_specify)
    else:
        specify_effective = max(0, _to_int(specify_effective, 0) or 0)
    final = max(
        0,
        _price_int(src, "customer_pay_amount", "amount", "total_amount", default=0),
    )
    payout = max(0, _price_int(src, "payout_base_amount", default=0))
    rate = _price_rate(src)

    embed.add_field(name="商品原價", value=_format_plain_amount(original), inline=True)
    if rate < 100 or percent_off:
        embed.add_field(
            name="百分比折扣",
            value=(
                f"折後 {_format_percent_value(rate)}%\n-{_format_plain_amount(percent_off)}"
                "\n共同分攤，折後金額計入分潤基準"
            ),
            inline=True,
        )
    if fixed:
        reason = str(src.get("cash_coupon_reason") or "").strip()
        text = f"-{_format_plain_amount(fixed)}"
        if reason:
            text += f"\n{reason}"
        text += "\n共同分攤，折後金額計入分潤基準"
        embed.add_field(name="固定折扣", value=text, inline=True)
    if point_cash:
        embed.add_field(
            name="點數折價",
            value=f"-{_format_plain_amount(point_cash)}\n店內吸收，不扣打手分潤",
            inline=True,
        )
    if specify_before:
        if specify_effective == 0:
            text = f"原 {_format_plain_amount(specify_before)}\n已免除"
        else:
            text = f"+{_format_plain_amount(specify_effective)}"
        embed.add_field(name="指定費", value=text, inline=True)

    embed.add_field(name=final_label, value=_format_plain_amount(final), inline=True)
    embed.add_field(name="打手分潤基準", value=_format_plain_amount(payout), inline=True)
    urgent_fee = max(0, _price_int(src, "urgent_fee_amount", default=0))
    if urgent_fee:
        embed.add_field(
            name="加急費",
            value=f"+{urgent_fee:,}T（全額歸接單打手，不計入店家／客服分潤）",
            inline=True,
        )
    if is_internal_ammo_dump_rule(src.get("order_rule_key")) or (
        "staff_internal_ammo_named" in src
    ):
        named = selected_ammo_dump_named(src)
        embed.add_field(
            name="掛名狀態",
            value="有掛名" if named is True else "無掛名" if named is False else "等待客服選擇",
            inline=True,
        )
        if named is False:
            margin = _price_int(src, "store_margin_amount", default=0)
            cs_payout = _price_int(src, "customer_service_payout_amount", default=0)
            retained = max(0, margin - cs_payout)
            embed.add_field(
                name="店家抽成前差額",
                value=f"{margin:,}T",
                inline=True,
            )
            embed.add_field(
                name="客服分潤",
                value=f"{cs_payout:,}T（差額的 25%，整數 T 四捨五入）",
                inline=True,
            )
            embed.add_field(
                name="店家實留",
                value=f"{retained:,}T",
                inline=True,
            )

    benefit_name = str(src.get("point_benefit_name") or "").strip()
    bonus = str(src.get("service_bonus_text") or "").strip()
    if benefit_name:
        lines = [f"{_price_int(src, 'point_benefit_cost', default=0)} 點｜{benefit_name}"]
        if point_cash:
            lines.append(f"已直接折抵價格：-{_format_plain_amount(point_cash)}")
        if bonus:
            lines.append(f"訂單備註：{bonus}")
        embed.add_field(name="點數福利", value="\n".join(lines), inline=False)
    elif bonus:
        embed.add_field(name="訂單福利備註", value=bonus, inline=False)

    service_promotion_text = str(src.get("service_promotion_text") or "").strip()
    if service_promotion_text:
        embed.add_field(name="活動加贈", value=service_promotion_text, inline=False)
    return embed


