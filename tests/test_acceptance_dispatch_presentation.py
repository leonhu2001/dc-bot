from __future__ import annotations

from datetime import datetime, timezone

import discord

from services.acceptance.dispatch_presentation import (
    acceptance_public_open_timestamp,
    apply_acceptance_dispatch_fields,
)


def _field_map(embed: discord.Embed) -> dict[str, str]:
    return {str(field.name): str(field.value) for field in embed.fields}


def test_public_open_timestamp_uses_acceptance_meta_created_at():
    timestamp = acceptance_public_open_timestamp("2026-10-20T06:00:00", 60)
    expected = int(datetime(2026, 10, 20, 6, 1, 0, tzinfo=timezone.utc).timestamp())
    assert timestamp == expected


def test_public_open_timestamp_fails_open_for_legacy_bad_timestamp():
    assert acceptance_public_open_timestamp("legacy-value", 60) is None
    assert acceptance_public_open_timestamp(None, 60) is None


def test_dispatch_fields_show_specified_priority_before_public_open_without_mutating_input():
    embed = discord.Embed(title="派單")
    embed.add_field(name="狀態", value="舊狀態", inline=False)
    embed.add_field(name="接單保護", value="舊保護", inline=False)
    embed.add_field(name="指定／公開名額", value="舊名額", inline=False)
    claim_data = {
        "status": "waiting_acceptance",
        "accepted_count": 1,
        "required_staff_count": 2,
        "protector_count": 1,
        "min_protector_count": 1,
        "specified_staff_ids": ["111", "111"],
        "public_acceptance_opens_at_unix": 2000,
        "web_order_id": 321,
        "service_terms_version": "v3",
    }
    before = dict(claim_data)

    apply_acceptance_dispatch_fields(embed, claim_data, now_ts=1900)

    fields = _field_map(embed)
    assert fields["目前階段"] == "🎯 指定優先 → 🟢 公開接單 <t:2000:R>"
    assert fields["接單進度"] == "1/2 位"
    assert fields["護航需求"] == "1/1 位護級"
    assert "<@111>" in fields["接單規則"]
    assert "非指定公開名額：1 位" in fields["接單規則"]
    assert "<t:2000:T> 開放" in fields["接單規則"]
    assert "指定人員僅略過時間鎖" in fields["接單規則"]
    assert fields["網站下單資訊"] == "網站訂單：WEB-321\n服務規章：已同意｜v3"
    assert "狀態" not in fields
    assert "接單保護" not in fields
    assert "指定／公開名額" not in fields
    assert claim_data == before


def test_dispatch_fields_show_generic_protection_without_specified_staff():
    embed = discord.Embed(title="派單")
    claim_data = {
        "status": "waiting_acceptance",
        "accepted_count": 0,
        "required_staff_count": 2,
        "public_acceptance_opens_at_unix": 2000,
    }

    apply_acceptance_dispatch_fields(embed, claim_data, now_ts=1900)

    fields = _field_map(embed)
    assert fields["目前階段"] == "🔒 接單保護 → 🟢 公開接單 <t:2000:R>"
    assert "公開接單：<t:2000:T> 開放" in fields["接單規則"]


def test_dispatch_fields_show_public_acceptance_after_open_time():
    embed = discord.Embed(title="派單")
    claim_data = {
        "status": "waiting_acceptance",
        "accepted_count": 0,
        "required_staff_count": 2,
        "public_acceptance_opens_at_unix": 2000,
    }

    apply_acceptance_dispatch_fields(embed, claim_data, now_ts=2000)

    fields = _field_map(embed)
    assert fields["目前階段"] == "🟢 公開接單中｜可依現有資格規則接單"
    assert "已於 <t:2000:T> 開放" in fields["接單規則"]


def test_dispatch_fields_show_full_waiting_payment_state():
    embed = discord.Embed(title="派單")
    claim_data = {
        "status": "accepted_pending_pay",
        "accepted_count": 2,
        "required_staff_count": 2,
    }

    apply_acceptance_dispatch_fields(embed, claim_data, now_ts=2000)

    fields = _field_map(embed)
    assert fields["目前階段"] == "✅ 已滿員｜等待顧客付款"
    assert fields["接單進度"] == "2/2 位"
