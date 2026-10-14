from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


# ---------------------------------------------------------------------------
# Product eligibility: only entertainment products, including entertainment
# ranked modes, participate in loyalty progress.
# ---------------------------------------------------------------------------
replace_once(
    "services/order_rules.py",
    '_add_game_service_rule(category="valorant", key="valorant_entertain_ranked", label="特戰英豪｜娛樂陪｜積分", pricing_type="game", price=250, unit_label="局", allowed_service_roles=COMPANION_ROLES, required_game_roles=VALORANT_GAME_ROLE)\n',
    '_add_game_service_rule(category="valorant", key="valorant_entertain_ranked", label="特戰英豪｜娛樂陪｜積分", pricing_type="game", price=250, unit_label="局", allowed_service_roles=COMPANION_ROLES, required_game_roles=VALORANT_GAME_ROLE, loyalty_benefits_enabled=True)\n',
)
replace_once(
    "services/order_rules.py",
    '_add_game_service_rule(category="lol", key="lol_entertain_ranked", label="英雄聯盟｜娛樂陪｜積分", pricing_type="game", price=250, unit_label="局", allowed_service_roles=COMPANION_ROLES, required_game_roles=LOL_GAME_ROLE)\n',
    '_add_game_service_rule(category="lol", key="lol_entertain_ranked", label="英雄聯盟｜娛樂陪｜積分", pricing_type="game", price=250, unit_label="局", allowed_service_roles=COMPANION_ROLES, required_game_roles=LOL_GAME_ROLE, loyalty_benefits_enabled=True)\n',
)
replace_once(
    "services/order_rules.py",
    '''    _add_apex_service_rule(\n        key=f"{_apex_prefix}_ranked",\n        label=f"APEX｜{_apex_service_label}｜積分",\n        price=_apex_ranked_price,\n        allowed_service_roles=_apex_service_roles,\n        allowed_game_roles=_apex_game_roles,\n    )\n''',
    '''    _add_apex_service_rule(\n        key=f"{_apex_prefix}_ranked",\n        label=f"APEX｜{_apex_service_label}｜積分",\n        price=_apex_ranked_price,\n        allowed_service_roles=_apex_service_roles,\n        allowed_game_roles=_apex_game_roles,\n        loyalty_benefits_enabled=(_apex_prefix == "apex_entertain"),\n    )\n''',
)

# Game-priced entertainment rewards use the same 10% economics as hourly:
# 10 service games -> 1 service-game credit.
replace_once(
    "services/loyalty_benefits.py",
    "GAME_THRESHOLD = 20.0\nGAME_BONUS = 1.0\n",
    "GAME_THRESHOLD = 10.0\nGAME_BONUS = 1.0\n",
)

# Shared snapshot parser used by preview, close-order settlement and reconciliation.
replace_once(
    "services/loyalty_benefits.py",
    '''def _loyalty_display_label(rule_key: str, fallback: object = "") -> str:\n    label = str(fallback or rule_key or "").strip()\n    for suffix in ("｜單陪", "｜雙陪", "｜三陪", "｜四陪"):\n        if label.endswith(suffix):\n            label = label[: -len(suffix)]\n            break\n    return label or str(rule_key or "")\n\n\ndef loyalty_scope_key(rule_key: str, player_count: int = 1) -> str:\n''',
    '''def _loyalty_display_label(rule_key: str, fallback: object = "") -> str:\n    label = str(fallback or rule_key or "").strip()\n    for suffix in ("｜單陪", "｜雙陪", "｜三陪", "｜四陪"):\n        if label.endswith(suffix):\n            label = label[: -len(suffix)]\n            break\n    return label or str(rule_key or "")\n\n\ndef _snapshot_preview(row: dict[str, Any]) -> dict[str, Any]:\n    try:\n        import json\n\n        snapshot = json.loads(str(row.get("price_snapshot_json") or "{}"))\n    except Exception:\n        return {}\n    if not isinstance(snapshot, dict):\n        return {}\n    preview = snapshot.get("preview")\n    return preview if isinstance(preview, dict) else snapshot\n\n\ndef _extract_same_order_benefit_count(\n    row: dict[str, Any],\n    *,\n    scope_key: str | None = None,\n) -> int:\n    preview = _snapshot_preview(row)\n    benefit = preview.get("benefit_coupon") if isinstance(preview, dict) else None\n    if not isinstance(benefit, dict):\n        return 0\n    if str(benefit.get("source") or "").strip() != "same_order":\n        return 0\n    if scope_key is not None and str(benefit.get("scope_key") or "").strip() != str(scope_key):\n        return 0\n    try:\n        return max(0, int(benefit.get("earned_count") or 0))\n    except (TypeError, ValueError):\n        return 0\n\n\ndef loyalty_scope_key(rule_key: str, player_count: int = 1) -> str:\n''',
)

# Add same-order preview after title formatting. Pending open orders are counted so
# historical progress cannot be claimed twice by two outstanding orders.
replace_once(
    "services/loyalty_benefits.py",
    '''def _coupon_title(row: dict[str, Any]) -> str:\n    kind = str(row.get("benefit_kind") or "")\n    units = float(row.get("benefit_units") or 0)\n    if kind == "extra_hours":\n        benefit = "折抵 30 分鐘額度" if abs(units - 0.5) < 0.001 else f"折抵 {units:g} 小時額度"\n    else:\n        benefit = f"折抵 {int(round(units))} 局額度"\n    label = _loyalty_display_label(str(row.get("rule_key") or ""), row.get("rule_label"))\n    return f"{label}｜{benefit}"\n\n\ndef list_customer_loyalty(customer_id: str | int) -> dict[str, Any]:\n''',
    '''def _coupon_title(row: dict[str, Any]) -> str:\n    kind = str(row.get("benefit_kind") or "")\n    units = float(row.get("benefit_units") or 0)\n    if kind == "extra_hours":\n        benefit = "折抵 30 分鐘額度" if abs(units - 0.5) < 0.001 else f"折抵 {units:g} 小時額度"\n    else:\n        benefit = f"折抵 {int(round(units))} 局額度"\n    label = _loyalty_display_label(str(row.get("rule_key") or ""), row.get("rule_label"))\n    return f"{label}｜{benefit}"\n\n\ndef _pending_same_order_claim_count(\n    conn,\n    *,\n    customer_id: str,\n    scope_key: str,\n) -> int:\n    try:\n        has_orders = conn.execute(text("""\n            SELECT 1\n            FROM sqlite_master\n            WHERE type = 'table' AND name = 'web_orders'\n            LIMIT 1\n        """)).first()\n        if has_orders is None:\n            return 0\n        rows = conn.execute(text("""\n            SELECT price_snapshot_json\n            FROM web_orders\n            WHERE customer_discord_id = :customer_id\n              AND LOWER(COALESCE(status, '')) NOT IN ('closed', 'cancelled')\n        """), {"customer_id": customer_id}).mappings().all()\n    except Exception:\n        return 0\n\n    return sum(\n        _extract_same_order_benefit_count(dict(row), scope_key=scope_key)\n        for row in rows\n    )\n\n\ndef preview_same_order_benefit(\n    customer_id: str | int,\n    *,\n    rule_key: str,\n    quantity: int,\n    player_count: int = 1,\n) -> dict[str, Any] | None:\n    """Return the loyalty reward earned by this order so it can be used now.\n\n    This is read-only. The order snapshot records the consumed reward and the\n    close-order path subtracts it before issuing any future coupon.\n    """\n    policy = loyalty_policy_for_rule(rule_key)\n    rule = _rule_for_key(rule_key)\n    customer = str(customer_id or "").strip()\n    if policy is None or rule is None or not customer:\n        return None\n\n    requested_players = max(1, int(player_count or 1))\n    companion_count = _service_companion_count(rule, requested_players)\n    paid_units = float(max(0, int(quantity or 0)) * companion_count)\n    if paid_units <= 0:\n        return None\n\n    ensure_loyalty_tables()\n    scope = loyalty_scope_key(rule_key, requested_players)\n    threshold = float(policy["threshold_units"] or 0)\n    if threshold <= 0:\n        return None\n\n    with engine.begin() as conn:\n        progress_row = conn.execute(text("""\n            SELECT progress_units, debt_units\n            FROM customer_loyalty_progress\n            WHERE customer_discord_id = :customer_id\n              AND scope_key = :scope_key\n            LIMIT 1\n        """), {\n            "customer_id": customer,\n            "scope_key": scope,\n        }).mappings().first()\n        previous = float(progress_row.get("progress_units") or 0) if progress_row else 0.0\n        debt_before = float(progress_row.get("debt_units") or 0) if progress_row else 0.0\n        credited_units = max(0.0, paid_units - debt_before)\n        projected_total = previous + credited_units\n        earned_count = max(0, int(projected_total // threshold))\n        pending_count = _pending_same_order_claim_count(\n            conn,\n            customer_id=customer,\n            scope_key=scope,\n        )\n\n    available_count = max(0, earned_count - pending_count)\n    if available_count <= 0:\n        return None\n\n    base_units = float(policy["benefit_units"] or 0)\n    benefit = {\n        "id": None,\n        "source": "same_order",\n        "same_order": True,\n        "earned_count": available_count,\n        "scope_key": scope,\n        "rule_key": str(rule_key),\n        "rule_label": _loyalty_display_label(rule_key, getattr(rule, "label", rule_key)),\n        "pricing_type": str(policy["pricing_type"]),\n        "player_count": requested_players,\n        "benefit_kind": str(policy["benefit_kind"]),\n        "benefit_units": base_units * available_count,\n        "threshold_units": threshold,\n    }\n    benefit["title"] = _coupon_title(benefit)\n    return benefit\n\n\ndef list_customer_loyalty(customer_id: str | int) -> dict[str, Any]:\n''',
)

# Same-order benefits are described differently from stored coupons.
replace_once(
    "services/loyalty_benefits.py",
    '''def coupon_service_note(coupon: dict[str, Any] | None) -> str:\n    if not coupon:\n        return ""\n    kind = str(coupon.get("benefit_kind") or "")\n    units = float(coupon.get("benefit_units") or 0)\n    if kind == "extra_hours":\n        amount = "30 分鐘" if abs(units - 0.5) < 0.001 else f"{units:g} 小時"\n        return f"福利券：折抵 {amount} 服務額度"\n    return f"福利券：折抵 {int(round(units))} 局服務額度"\n''',
    '''def coupon_service_note(coupon: dict[str, Any] | None) -> str:\n    if not coupon:\n        return ""\n    prefix = "本單累積福利" if str(coupon.get("source") or "") == "same_order" else "福利券"\n    kind = str(coupon.get("benefit_kind") or "")\n    units = float(coupon.get("benefit_units") or 0)\n    if kind == "extra_hours":\n        amount = "30 分鐘" if abs(units - 0.5) < 0.001 else f"{units:g} 小時"\n        return f"{prefix}：折抵 {amount} 服務額度"\n    return f"{prefix}：折抵 {int(round(units))} 局服務額度"\n''',
)

# A current-order loyalty reward may reduce payable service to zero. In that
# case the order still supplied the units that crossed the threshold. Existing
# stored coupons retain the old behavior and do not create circular progress.
replace_once(
    "services/loyalty_benefits.py",
    '''            finance = (\n                preview.get("finance")\n                if isinstance(preview, dict)\n                and isinstance(preview.get("finance"), dict)\n                else {}\n            )\n            if "subtotal_before_wallet" in finance:\n                return max(0, int(finance.get("subtotal_before_wallet") or 0))\n            if "customer_pay_amount" in snapshot:\n                return max(0, int(snapshot.get("customer_pay_amount") or 0))\n''',
    '''            finance = (\n                preview.get("finance")\n                if isinstance(preview, dict)\n                and isinstance(preview.get("finance"), dict)\n                else {}\n            )\n            benefit = preview.get("benefit_coupon") if isinstance(preview, dict) else None\n            if isinstance(benefit, dict) and str(benefit.get("source") or "") == "same_order":\n                return max(0, int(\n                    finance.get("service_after_vip")\n                    or finance.get("service_amount")\n                    or amount\n                    or 0\n                ))\n            if "subtotal_before_wallet" in finance:\n                return max(0, int(finance.get("subtotal_before_wallet") or 0))\n            if "customer_pay_amount" in snapshot:\n                return max(0, int(snapshot.get("customer_pay_amount") or 0))\n''',
)

# Reconciliation treats already-used same-order rewards like redeemed coupons.
replace_once(
    "services/loyalty_benefits.py",
    '''        "benefit_units": float(policy["benefit_units"]),\n        "paid_units": float(\n            max(0, int(row.get("quantity") or 0)) * companion_count\n        ),\n    }\n''',
    '''        "benefit_units": float(policy["benefit_units"]),\n        "paid_units": float(\n            max(0, int(row.get("quantity") or 0)) * companion_count\n        ),\n        "same_order_consumed_count": _extract_same_order_benefit_count(row),\n    }\n''',
)
replace_once(
    "services/loyalty_benefits.py",
    '''            if aggregate is None:\n                aggregate = dict(bucket)\n                aggregate["paid_units"] = 0.0\n                buckets[scope] = aggregate\n            aggregate["paid_units"] = float(aggregate.get("paid_units") or 0) + paid_units\n''',
    '''            if aggregate is None:\n                aggregate = dict(bucket)\n                aggregate["paid_units"] = 0.0\n                aggregate["same_order_consumed_count"] = 0\n                buckets[scope] = aggregate\n            aggregate["paid_units"] = float(aggregate.get("paid_units") or 0) + paid_units\n            aggregate["same_order_consumed_count"] = int(\n                aggregate.get("same_order_consumed_count") or 0\n            ) + int(bucket.get("same_order_consumed_count") or 0)\n''',
)
# There are two metadata-only bucket constructors in reconciliation.
path = ROOT / "services/loyalty_benefits.py"
text_value = path.read_text(encoding="utf-8")
meta_old = '''            "benefit_units": float(row.get("benefit_units") or 0),\n            "paid_units": 0.0,\n        }\n'''
if text_value.count(meta_old) != 1:
    raise RuntimeError(f"progress metadata constructor expected once, found {text_value.count(meta_old)}")
text_value = text_value.replace(
    meta_old,
    '''            "benefit_units": float(row.get("benefit_units") or 0),\n            "paid_units": 0.0,\n            "same_order_consumed_count": 0,\n        }\n''',
    1,
)
meta_coupon_old = '''            "benefit_units": float(row.get("benefit_units") or policy["benefit_units"]),\n            "paid_units": 0.0,\n        }\n'''
if text_value.count(meta_coupon_old) != 1:
    raise RuntimeError(f"coupon metadata constructor expected once, found {text_value.count(meta_coupon_old)}")
text_value = text_value.replace(
    meta_coupon_old,
    '''            "benefit_units": float(row.get("benefit_units") or policy["benefit_units"]),\n            "paid_units": 0.0,\n            "same_order_consumed_count": 0,\n        }\n''',
    1,
)
path.write_text(text_value, encoding="utf-8")

replace_once(
    "services/loyalty_benefits.py",
    '''        target_nonprotected = max(0, earned_count - len(protected))\n        keep_expired = min(len(expired), target_nonprotected)\n''',
    '''        same_order_consumed = max(\n            0,\n            int((buckets.get(scope) or {}).get("same_order_consumed_count") or 0),\n        )\n        protected_count = len(protected) + same_order_consumed\n        target_nonprotected = max(0, earned_count - protected_count)\n        keep_expired = min(len(expired), target_nonprotected)\n''',
)
replace_once(
    "services/loyalty_benefits.py",
    '''        debt_units = max(0.0, len(protected) * threshold - total_units)\n''',
    '''        debt_units = max(0.0, protected_count * threshold - total_units)\n''',
)

# Close-order settlement subtracts any reward already consumed on this order
# before deciding how many coupons to issue for later use.
replace_once(
    "services/loyalty_benefits.py",
    '''            debt_after = max(0.0, debt_before - paid_units)\n            credited_units = max(0.0, paid_units - debt_before)\n            total = previous + credited_units\n            issued_count = max(0, int(total // threshold))\n            remainder = total - issued_count * threshold\n            rule_label = _loyalty_display_label(\n''',
    '''            debt_after = max(0.0, debt_before - paid_units)\n            credited_units = max(0.0, paid_units - debt_before)\n            total = previous + credited_units\n            same_order_consumed = _extract_same_order_benefit_count(row)\n            consumed_units = float(same_order_consumed) * threshold\n            if consumed_units > total:\n                debt_after += consumed_units - total\n                rewardable_total = 0.0\n            else:\n                rewardable_total = total - consumed_units\n            issued_count = max(0, int(rewardable_total // threshold))\n            remainder = rewardable_total - issued_count * threshold\n            rule_label = _loyalty_display_label(\n''',
)

# ---------------------------------------------------------------------------
# Checkout: automatically use a reward earned by this order when the customer
# did not explicitly select a point reward or an existing loyalty coupon.
# ---------------------------------------------------------------------------
replace_once(
    "web/app/services/checkout_preview.py",
    '''from services.loyalty_benefits import (\n    calculate_coupon_service_value,\n    coupon_service_note,\n    get_applicable_coupon,\n    list_applicable_coupons,\n)\n''',
    '''from services.loyalty_benefits import (\n    calculate_coupon_service_value,\n    coupon_service_note,\n    get_applicable_coupon,\n    list_applicable_coupons,\n    preview_same_order_benefit,\n)\n''',
)
replace_once(
    "web/app/services/checkout_preview.py",
    '''        "benefit_coupon_id": (int(benefit_coupon.get("id")) if benefit_coupon else None),\n''',
    '''        "benefit_coupon_id": (\n            int(benefit_coupon.get("id"))\n            if benefit_coupon and benefit_coupon.get("id") not in (None, "")\n            else None\n        ),\n''',
)
replace_once(
    "web/app/services/checkout_preview.py",
    '''        if selected_benefit_coupon is None:\n            raise ValueError("這張福利券已使用、已保留，或不適用這個方案。")\n\n\n\n    finance = (\n''',
    '''        if selected_benefit_coupon is None:\n            raise ValueError("這張福利券已使用、已保留，或不適用這個方案。")\n\n    if selected_point_item is None and selected_benefit_coupon is None:\n        selected_benefit_coupon = preview_same_order_benefit(\n            customer_id,\n            rule_key=rule_key,\n            quantity=int(quote.get("quantity") or quantity or 1),\n            player_count=int(quote.get("player_count") or player_count or 1),\n        )\n\n\n    finance = (\n''',
)
replace_once(
    "web/app/services/checkout_preview.py",
    '''        "benefit_coupon": (\n            {\n                "id": int(selected_benefit_coupon.get("id")),\n                "title": str(selected_benefit_coupon.get("title") or ""),\n                "benefit_kind": str(selected_benefit_coupon.get("benefit_kind") or ""),\n                "benefit_units": float(selected_benefit_coupon.get("benefit_units") or 0),\n            }\n            if selected_benefit_coupon\n            else None\n        ),\n''',
    '''        "benefit_coupon": (\n            {\n                "id": (\n                    int(selected_benefit_coupon.get("id"))\n                    if selected_benefit_coupon.get("id") not in (None, "")\n                    else None\n                ),\n                "title": str(selected_benefit_coupon.get("title") or ""),\n                "benefit_kind": str(selected_benefit_coupon.get("benefit_kind") or ""),\n                "benefit_units": float(selected_benefit_coupon.get("benefit_units") or 0),\n                "source": str(selected_benefit_coupon.get("source") or "loyalty"),\n                "same_order": bool(selected_benefit_coupon.get("same_order")),\n                "earned_count": int(selected_benefit_coupon.get("earned_count") or 0),\n                "scope_key": str(selected_benefit_coupon.get("scope_key") or ""),\n            }\n            if selected_benefit_coupon\n            else None\n        ),\n''',
)

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------
policy_test = ROOT / "tests/test_loyalty_entertainment_policy.py"
policy_test.write_text(
    '''from services import loyalty_benefits as loyalty\nfrom services.order_rules import ORDER_RULES\n\n\nELIGIBLE_RULES = (\n    "basic_entertain_single",\n    "basic_entertain_double",\n    "basic_mobile_entertain_single",\n    "basic_mobile_entertain_double",\n    "steam_play",\n    "valorant_entertain_ng",\n    "valorant_entertain_ranked",\n    "lol_entertain_aram",\n    "lol_entertain_ng",\n    "lol_entertain_ranked",\n    "apex_entertain_ng",\n    "apex_entertain_ranked",\n)\n\nINELIGIBLE_RULES = (\n    "basic_exbar_tech",\n    "basic_tech_secret_single",\n    "basic_tech_secret_double",\n    "basic_tech_topsecret_single",\n    "basic_tech_topsecret_double",\n    "basic_mobile_tech_secret_single",\n    "basic_mobile_tech_secret_double",\n    "basic_mobile_tech_topsecret_single",\n    "basic_mobile_tech_topsecret_double",\n    "valorant_ascendant_ng",\n    "valorant_ascendant_ranked",\n    "valorant_immortal_ng",\n    "valorant_immortal_ranked",\n    "valorant_radiant_ng",\n    "valorant_radiant_ranked",\n    "lol_master_ng",\n    "lol_master_ranked",\n    "lol_grandmaster_ng",\n    "lol_grandmaster_ranked",\n    "lol_elite_ng",\n    "lol_elite_ranked",\n    "apex_diamond_ng",\n    "apex_diamond_ranked",\n    "apex_master_ng",\n    "apex_master_ranked",\n    "apex_predator_ng",\n    "apex_predator_ranked",\n)\n\n\ndef test_only_entertainment_products_have_loyalty_progress():\n    for rule_key in ELIGIBLE_RULES:\n        rule = ORDER_RULES[rule_key]\n        assert rule.loyalty_benefits_enabled is True\n        assert "娛樂陪" in rule.label\n        policy = loyalty.loyalty_policy_for_rule(rule_key)\n        assert policy is not None\n        assert policy["threshold_units"] == 10.0\n        assert policy["benefit_units"] == 1.0\n\n    for rule_key in INELIGIBLE_RULES:\n        assert ORDER_RULES[rule_key].loyalty_benefits_enabled is False\n        assert loyalty.loyalty_policy_for_rule(rule_key) is None\n\n\ndef test_ranked_entertainment_keeps_ten_percent_reward_rate():\n    assert loyalty.loyalty_policy_for_rule("valorant_entertain_ranked") == {\n        "pricing_type": "game",\n        "threshold_units": 10.0,\n        "benefit_kind": "extra_games",\n        "benefit_units": 1.0,\n        "unit_label": "局",\n        "benefit_label": "+1 局",\n    }\n    assert loyalty.loyalty_policy_for_rule("apex_entertain_ranked")["pricing_type"] == "hourly"\n''',
    encoding="utf-8",
)

same_order_test = ROOT / "tests/test_loyalty_same_order.py"
same_order_test.write_text(
    '''from __future__ import annotations\n\nimport json\nfrom pathlib import Path\n\nfrom sqlalchemy import create_engine, text\n\nfrom services import loyalty_benefits as loyalty\nfrom web.app.services.checkout_preview import calculate_checkout_financials\n\n\ndef _setup(monkeypatch, tmp_path: Path):\n    engine = create_engine(\n        f"sqlite:///{tmp_path / 'same-order.db'}",\n        connect_args={"check_same_thread": False},\n    )\n    monkeypatch.setattr(loyalty, "engine", engine)\n    loyalty.ensure_loyalty_tables(engine)\n    with engine.begin() as conn:\n        conn.execute(text("""\n            CREATE TABLE web_orders (\n                id INTEGER PRIMARY KEY,\n                customer_discord_id TEXT,\n                order_rule_key TEXT,\n                quantity INTEGER,\n                amount INTEGER,\n                original_amount INTEGER,\n                customer_pay_amount INTEGER,\n                status TEXT,\n                created_at TEXT,\n                updated_at TEXT,\n                closed_at TEXT,\n                price_snapshot_json TEXT,\n                ticket_channel_id TEXT\n            )\n        """))\n        conn.execute(text("""\n            INSERT INTO customer_loyalty_progress (\n                customer_discord_id, scope_key, rule_key, rule_label,\n                pricing_type, player_count, progress_units, debt_units,\n                threshold_units, benefit_kind, benefit_units, updated_at\n            ) VALUES (\n                'owner-a', 'delta_desktop_basic|basic_entertain',\n                'basic_entertain_single', '娛樂陪〈端遊〉',\n                'hourly', 1, 9, 0, 10, 'extra_hours', 1,\n                '2026-10-14T10:00:00+08:00'\n            )\n        """))\n    return engine\n\n\ndef test_current_order_can_use_reward_when_it_crosses_threshold(monkeypatch, tmp_path: Path):\n    _setup(monkeypatch, tmp_path)\n    reward = loyalty.preview_same_order_benefit(\n        'owner-a',\n        rule_key='basic_entertain_single',\n        quantity=1,\n        player_count=1,\n    )\n    assert reward is not None\n    assert reward['source'] == 'same_order'\n    assert reward['earned_count'] == 1\n    assert reward['benefit_units'] == 1.0\n\n    finance = calculate_checkout_financials(\n        service_amount=320,\n        vip_pay_rate=100,\n        specify_fee=0,\n        point_item=None,\n        wallet_balance=0,\n        use_wallet=False,\n        benefit_coupon=reward,\n        benefit_service_value=320,\n    )\n    assert finance['benefit_coupon_id'] is None\n    assert finance['customer_pay_amount'] == 0\n    assert finance['payout_base_amount'] == 320\n\n\ndef test_same_order_reward_is_not_issued_again_on_close(monkeypatch, tmp_path: Path):\n    engine = _setup(monkeypatch, tmp_path)\n    scope = 'delta_desktop_basic|basic_entertain'\n    snapshot = json.dumps({\n        'preview': {\n            'finance': {\n                'service_after_vip': 320,\n                'service_amount': 320,\n                'subtotal_before_wallet': 0,\n            },\n            'benefit_coupon': {\n                'id': None,\n                'source': 'same_order',\n                'same_order': True,\n                'earned_count': 1,\n                'scope_key': scope,\n                'benefit_kind': 'extra_hours',\n                'benefit_units': 1.0,\n            },\n        }\n    })\n    with engine.begin() as conn:\n        conn.execute(text("""\n            INSERT INTO web_orders (\n                id, customer_discord_id, order_rule_key, quantity, amount,\n                original_amount, customer_pay_amount, status, created_at,\n                updated_at, closed_at, price_snapshot_json, ticket_channel_id\n            ) VALUES (\n                1, 'owner-a', 'basic_entertain_single', 1, 0, 320, 0,\n                'closed', '2026-10-14 10:00:00', '2026-10-14 10:00:00',\n                '2026-10-14 10:00:00', :snapshot, NULL\n            )\n        """), {'snapshot': snapshot})\n\n    result = loyalty.process_closed_order(1)\n    assert result is not None\n    assert result['issued_coupon_count'] == 0\n    with engine.begin() as conn:\n        progress = conn.execute(text("""\n            SELECT progress_units, debt_units\n            FROM customer_loyalty_progress\n            WHERE customer_discord_id = 'owner-a'\n        """)).mappings().one()\n        coupon_count = conn.execute(text("""\n            SELECT COUNT(*) FROM customer_benefit_coupons\n            WHERE customer_discord_id = 'owner-a'\n        """)).scalar_one()\n    assert float(progress['progress_units']) == 0.0\n    assert float(progress['debt_units']) == 0.0\n    assert coupon_count == 0\n\n\ndef test_pending_order_claim_blocks_duplicate_same_order_reward(monkeypatch, tmp_path: Path):\n    engine = _setup(monkeypatch, tmp_path)\n    scope = 'delta_desktop_basic|basic_entertain'\n    snapshot = json.dumps({\n        'preview': {\n            'benefit_coupon': {\n                'source': 'same_order',\n                'earned_count': 1,\n                'scope_key': scope,\n            }\n        }\n    })\n    with engine.begin() as conn:\n        conn.execute(text("""\n            INSERT INTO web_orders (\n                id, customer_discord_id, order_rule_key, quantity, amount,\n                original_amount, customer_pay_amount, status, created_at,\n                updated_at, closed_at, price_snapshot_json, ticket_channel_id\n            ) VALUES (\n                2, 'owner-a', 'basic_entertain_single', 1, 0, 320, 0,\n                'waiting_acceptance', '2026-10-14 10:00:00',\n                '2026-10-14 10:00:00', NULL, :snapshot, NULL\n            )\n        """), {'snapshot': snapshot})\n\n    assert loyalty.preview_same_order_benefit(\n        'owner-a',\n        rule_key='basic_entertain_single',\n        quantity=1,\n        player_count=1,\n    ) is None\n''',
    encoding="utf-8",
)

# Self-delete one-shot patch mechanism so the final PR contains only product,
# loyalty, checkout and test changes.
(ROOT / "scripts/apply_loyalty_instant_patch.py").unlink(missing_ok=True)
(ROOT / ".github/workflows/apply-loyalty-instant-patch.yml").unlink(missing_ok=True)
