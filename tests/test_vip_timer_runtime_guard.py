from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

import services.vip_timer_runtime_guard as guard


class _Role:
    def __init__(self, role_id: int):
        self.id = role_id


class _Member:
    def __init__(self, user_id: int, role_ids, name: str):
        self.id = user_id
        self.roles = [_Role(role_id) for role_id in role_ids]
        self.display_name = name
        self.name = name


class _Guild:
    def __init__(self, members):
        self._members = {member.id: member for member in members}

    def get_member(self, user_id: int):
        return self._members.get(user_id)


class _Bot:
    def __init__(self, guild):
        self.guild = guild

    def get_guild(self, guild_id: int):
        return self.guild if guild_id == 123 else None


def _rule(**overrides):
    data = {
        "pricing_type": "hourly",
        "price": 320,
        "required_staff_count": "player_count",
        "min_player_count": 1,
        "max_player_count": 4,
        "price_multiply_player_count": True,
        "min_protector_count": 0,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


def _allow_test_rule(monkeypatch):
    from services import vip_timer_catalog_guard

    monkeypatch.setattr(vip_timer_catalog_guard, "is_public_timer_rule", lambda key: True)


def test_per_player_hourly_rule_uses_accepted_staff_count(monkeypatch):
    _allow_test_rule(monkeypatch)
    monkeypatch.setattr(guard, "ORDER_RULES", {"steam_play": _rule()})
    monkeypatch.setattr(guard, "get_allowed_role_ids", lambda rule: ["10"])
    monkeypatch.setattr(guard, "get_required_game_role_ids", lambda rule: ["20"])
    monkeypatch.setattr(guard, "ROLE_IDS", {"top_protector": "30"})
    monkeypatch.setattr(guard, "PROTECTOR_ROLES", ("top_protector",))

    guild = _Guild([
        _Member(1, [10, 20], "A"),
        _Member(2, [10, 20], "B"),
    ])

    snapshot = guard._validated_pricing_snapshot(
        bot_instance=_Bot(guild),
        guild_id=123,
        rule_key="steam_play",
        staff_ids=["1", "2"],
    )

    assert snapshot["hourly_rate"] == 640
    assert snapshot["player_count"] == 2
    assert snapshot["required_staff_count"] == 2
    assert guard._rule_rate_and_validate(
        bot_instance=_Bot(guild),
        guild_id=123,
        rule_key="steam_play",
        staff_ids=["1", "2"],
    ) == 640


def test_switch_rejects_staff_without_target_game_role(monkeypatch):
    _allow_test_rule(monkeypatch)
    monkeypatch.setattr(guard, "ORDER_RULES", {"steam_play": _rule()})
    monkeypatch.setattr(guard, "get_allowed_role_ids", lambda rule: ["10"])
    monkeypatch.setattr(guard, "get_required_game_role_ids", lambda rule: ["20"])
    monkeypatch.setattr(guard, "ROLE_IDS", {})
    monkeypatch.setattr(guard, "PROTECTOR_ROLES", ())

    guild = _Guild([
        _Member(1, [10, 20], "A"),
        _Member(2, [10], "B"),
    ])

    with pytest.raises(ValueError, match="不符合這個玩法"):
        guard._rule_rate_and_validate(
            bot_instance=_Bot(guild),
            guild_id=123,
            rule_key="steam_play",
            staff_ids=["1", "2"],
        )


def test_fixed_staff_rule_rejects_roster_size_change(monkeypatch):
    _allow_test_rule(monkeypatch)
    monkeypatch.setattr(
        guard,
        "ORDER_RULES",
        {"single": _rule(required_staff_count=1, price_multiply_player_count=False)},
    )
    monkeypatch.setattr(guard, "get_allowed_role_ids", lambda rule: [])
    monkeypatch.setattr(guard, "get_required_game_role_ids", lambda rule: [])
    monkeypatch.setattr(guard, "ROLE_IDS", {})
    monkeypatch.setattr(guard, "PROTECTOR_ROLES", ())

    guild = _Guild([
        _Member(1, [], "A"),
        _Member(2, [], "B"),
    ])

    with pytest.raises(ValueError, match="不支援中途增減人員"):
        guard._rule_rate_and_validate(
            bot_instance=_Bot(guild),
            guild_id=123,
            rule_key="single",
            staff_ids=["1", "2"],
        )


def test_segment_snapshot_persists_effective_rate_and_roster_counts(tmp_path, monkeypatch):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'vip-runtime-guard.db'}",
        connect_args={"check_same_thread": False},
    )
    local = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    monkeypatch.setattr(guard, "SessionLocal", local)

    guard._ensure_segment_snapshot_columns()
    with local.begin() as db:
        db.execute(text("""
            INSERT INTO vip_timer_sessions(
                order_id, customer_discord_id, status, current_rule_key,
                current_rule_label, current_category_label, current_hourly_rate,
                final_amount, created_at, updated_at
            ) VALUES (
                1, '99', 'running', 'steam_play', 'STEAM', 'STEAM', 320,
                0, '2026-10-21T00:00:00+00:00', '2026-10-21T00:00:00+00:00'
            )
        """))
        db.execute(text("""
            INSERT INTO vip_timer_segments(
                order_id, seq, rule_key, rule_label, category_label, hourly_rate,
                started_at, active_started_at, billable_seconds, actor_discord_id,
                staff_ids_json, created_at, updated_at
            ) VALUES (
                1, 1, 'steam_play', 'STEAM', 'STEAM', 320,
                '2026-10-21T00:00:00+00:00', '2026-10-21T00:00:00+00:00', 0,
                '99', '["1","2"]', '2026-10-21T00:00:00+00:00', '2026-10-21T00:00:00+00:00'
            )
        """))

    guard._write_effective_snapshot(
        1,
        {
            "hourly_rate": 640,
            "player_count": 2,
            "required_staff_count": 2,
        },
        update_segment=True,
    )

    with local() as db:
        row = db.execute(text(
            "SELECT hourly_rate, player_count, required_staff_count "
            "FROM vip_timer_segments WHERE order_id=1 AND seq=1"
        )).mappings().one()
    assert int(row["hourly_rate"]) == 640
    assert int(row["player_count"]) == 2
    assert int(row["required_staff_count"]) == 2


def test_panel_validates_but_price_is_only_persisted_when_starting(monkeypatch):
    from services import vip_timer_runtime as runtime

    writes: list[bool] = []
    validations: list[str] = []

    async def fake_panel(*args, **kwargs):
        return "panel"

    def fake_start(order_id, actor_id, staff_ids=None):
        return {"order_id": int(order_id), "status": "running"}

    def fake_switch(order_id, new_rule_key, actor_id, staff_ids=None):
        return {"order_id": int(order_id), "status": "running"}

    monkeypatch.setattr(guard, "_INSTALLED", False)
    monkeypatch.setattr(guard, "_ensure_segment_snapshot_columns", lambda: None)
    monkeypatch.setattr(runtime, "ensure_vip_timer_panel", fake_panel)
    monkeypatch.setattr(runtime, "start_timer", fake_start)
    monkeypatch.setattr(runtime, "switch_rule", fake_switch)
    monkeypatch.setattr(runtime, "get_session", lambda order_id: {"order_id": order_id, "current_rule_key": "rule"})

    def fake_validate(**kwargs):
        validations.append(str(kwargs.get("rule_key") or ""))
        return {
            "hourly_rate": 777,
            "player_count": 2,
            "required_staff_count": 2,
        }

    monkeypatch.setattr(guard, "_validated_pricing_snapshot", fake_validate)
    monkeypatch.setattr(
        guard,
        "_write_effective_snapshot",
        lambda order_id, snapshot, *, update_segment: writes.append(bool(update_segment)),
    )

    guard.install_vip_timer_runtime_guard(bot_instance=object(), guild_id=123)

    state = SimpleNamespace(order_id=1, claims=[])
    assert asyncio.run(runtime.ensure_vip_timer_panel(state=state, data={})) == "panel"
    assert writes == []

    runtime.start_timer(1, 99, ["1", "2"])
    assert writes == [False, True]
    assert validations == ["rule", "rule"]
