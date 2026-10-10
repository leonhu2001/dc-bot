import asyncio

from core.vip_levels import BASE_MEMBER_LEVELS, VIP_ROLE_TIERS
from services import rewards


class FakeRole:
    def __init__(self, role_id):
        self.id = int(role_id)


class FakeGuild:
    def __init__(self, roles):
        self._roles = {role.id: role for role in roles}

    def get_role(self, role_id):
        return self._roles.get(int(role_id))


class FakeMember:
    def __init__(self, roles):
        self.roles = list(roles)

    async def add_roles(self, *roles, reason=None):
        for role in roles:
            if role not in self.roles:
                self.roles.append(role)

    async def remove_roles(self, *roles, reason=None):
        removed = {role.id for role in roles}
        self.roles = [role for role in self.roles if role.id not in removed]


def _runtime():
    rewards.configure_rewards(member_levels=[dict(level) for level in BASE_MEMBER_LEVELS])
    rewards.configure_reward_benefits(vip_role_tiers=[dict(tier) for tier in VIP_ROLE_TIERS])
    roles = [FakeRole(tier["role_id"]) for tier in VIP_ROLE_TIERS]
    return FakeGuild(roles)


def _tier(name):
    return next(tier for tier in VIP_ROLE_TIERS if tier["name"] == name)


def test_manual_downgrade_syncs_discord_role_to_effective_vip_level():
    guild = _runtime()
    old_role = guild.get_role(_tier("白鑽魔丸")["role_id"])
    target_role_id = int(_tier("鑽石魔丸")["role_id"])
    member = FakeMember([old_role])
    data = {
        "total_spent": 50000,
        "vip_level_index": 4,
        "vip_progress_base_total_spent": 50000,
        "vip_progress_reset_active": True,
        "vip_downgrade_logs": [{"source": "manual_vip_review"}],
    }

    asyncio.run(rewards.sync_vip_tier_roles(guild, member, data))

    assert {role.id for role in member.roles} == {target_role_id}


def test_manual_downgrade_to_normal_removes_historical_high_vip_role():
    guild = _runtime()
    black_role = guild.get_role(_tier("黑鑽魔丸")["role_id"])
    member = FakeMember([black_role])
    data = {
        "total_spent": 88888,
        "vip_level_index": 0,
        "vip_progress_base_total_spent": 88888,
        "vip_progress_reset_active": True,
        "vip_downgrade_logs": [{"source": "manual_vip_review"}],
    }

    asyncio.run(rewards.sync_vip_tier_roles(guild, member, data))

    assert member.roles == []


def test_normal_cumulative_vip_role_sync_is_unchanged():
    guild = _runtime()
    member = FakeMember([])
    expected_role_id = int(_tier("白鑽魔丸")["role_id"])
    data = {
        "total_spent": 50000,
        "vip_level_index": None,
        "vip_progress_base_total_spent": None,
        "vip_progress_reset_active": False,
        "vip_downgrade_logs": [],
    }

    asyncio.run(rewards.sync_vip_tier_roles(guild, member, data))

    assert {role.id for role in member.roles} == {expected_role_id}
