from __future__ import annotations

import discord


CUSTOMER_ROLE_ID: int | None = None
EXAMINER_ROLE_ID: int | None = None
MANAGER_ROLE_ID: int | None = None


def configure_permissions(
    *,
    customer_role_id: int,
    examiner_role_id: int,
    manager_role_id: int,
) -> None:
    """設定權限判斷需要用到的身分組 ID。"""
    global CUSTOMER_ROLE_ID, EXAMINER_ROLE_ID, MANAGER_ROLE_ID

    CUSTOMER_ROLE_ID = int(customer_role_id)
    EXAMINER_ROLE_ID = int(examiner_role_id)
    MANAGER_ROLE_ID = int(manager_role_id)


def has_role(member: discord.Member, role_id: int | None) -> bool:
    if role_id is None:
        return False

    return any(role.id == int(role_id) for role in member.roles)


def is_customer_staff(member: discord.Member) -> bool:
    return has_role(member, CUSTOMER_ROLE_ID)


def is_exam_staff(member: discord.Member) -> bool:
    return has_role(member, EXAMINER_ROLE_ID) or has_role(member, MANAGER_ROLE_ID)


def is_complaint_staff(member: discord.Member) -> bool:
    return has_role(member, CUSTOMER_ROLE_ID) or has_role(member, MANAGER_ROLE_ID)


def is_manager_or_admin(member: discord.Member) -> bool:
    return has_role(member, MANAGER_ROLE_ID) or member.guild_permissions.administrator


def can_operate_self_service_order(user, customer_id: int) -> bool:
    """允許開票老闆本人、客服、店長或管理員代操作自助下單。

    客服代操作時，訂單仍會記在原本 customer_id 身上，
    不會把客服當成下單顧客。
    """
    if user.id == customer_id:
        return True

    if not isinstance(user, discord.Member):
        return False

    return is_customer_staff(user) or is_manager_or_admin(user)
