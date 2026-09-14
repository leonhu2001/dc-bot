from __future__ import annotations

import discord


# 總管：客服之上的整店管理層。即使舊 bot.py 仍把歷史 MANAGER_ROLE_ID
# 指向客服，這個固定角色仍可作為客服權限的 superset 使用。
GENERAL_MANAGER_ROLE_ID = 1537067761141030972

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


def is_general_manager(member: discord.Member) -> bool:
    return has_role(member, GENERAL_MANAGER_ROLE_ID)


def is_customer_staff(member: discord.Member) -> bool:
    # 總管可執行所有客服日常操作。
    return has_role(member, CUSTOMER_ROLE_ID) or is_general_manager(member)


def is_exam_staff(member: discord.Member) -> bool:
    return is_customer_staff(member)


def is_complaint_staff(member: discord.Member) -> bool:
    return is_customer_staff(member)


def is_manager_or_admin(member: discord.Member) -> bool:
    return (
        is_general_manager(member)
        or has_role(member, MANAGER_ROLE_ID)
        or member.guild_permissions.administrator
    )


def can_operate_self_service_order(user, customer_id: int) -> bool:
    """允許開票老闆本人、客服、總管或管理員代操作自助下單。

    員工代操作時，訂單仍會記在原本 customer_id 身上，
    不會把操作人員當成下單顧客。
    """
    if user.id == customer_id:
        return True

    if not isinstance(user, discord.Member):
        return False

    return is_customer_staff(user) or is_manager_or_admin(user)
