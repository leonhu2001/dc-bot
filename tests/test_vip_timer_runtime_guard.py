from __future__ import annotations

from types import SimpleNamespace

import pytest

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


def test_per_player_hourly_rule_uses_accepted_staff_count(monkeypatch):
    monkeypatch.setattr(guard, "ORDER_RULES", {"steam_play": _rule()})
    monkeypatch.setattr(guard, "get_allowed_role_ids", lambda rule: ["10"])
    monkeypatch.setattr(guard, "get_required_game_role_ids", lambda rule: ["20"])
    monkeypatch.setattr(guard, "ROLE_IDS", {"top_protector": "30"})
    monkeypatch.setattr(guard, "PROTECTOR_ROLES", ("top_protector",))

    guild = _Guild([
        _Member(1, [10, 20], "A"),
        _Member(2, [10, 20], "B"),
    ])

    rate = guard._rule_rate_and_validate(
        bot_instance=_Bot(guild),
        guild_id=123,
        rule_key="steam_play",
        staff_ids=["1", "2"],
    )

    assert rate == 640


def test_switch_rejects_staff_without_target_game_role(monkeypatch):
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
