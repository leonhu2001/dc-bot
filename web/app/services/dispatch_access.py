from services.dispatch_presence import (
    touch_dispatch_presence,
    touch_dispatch_support_presence,
)


def can_use_dispatch(user: dict | None) -> bool:
    if not user:
        return False

    return bool(
        user.get("is_admin")
        or user.get("is_worker")
        or user.get("is_companion")
        or user.get("is_customer_service")
    )


def get_dispatch_presence_flags(user: dict | None) -> tuple[bool, bool]:
    user = user or {}
    companion_online = bool(
        user.get("is_worker")
        or user.get("is_companion")
    )
    support_online = bool(
        user.get("is_manager")
        or user.get("is_customer_service")
    )
    return companion_online, support_online


def touch_dispatch_user_presence(
    user: dict | None,
) -> tuple[bool, bool]:
    user = user or {}
    companion_online, support_online = get_dispatch_presence_flags(user)

    display_name = (
        user.get("global_name")
        or user.get("display_name")
        or user.get("username")
        or user.get("id")
    )
    discord_id = str(user.get("id") or "")

    if companion_online:
        touch_dispatch_presence(
            discord_id,
            display_name=display_name,
        )

    if support_online:
        touch_dispatch_support_presence(
            discord_id,
            display_name=display_name,
        )

    return companion_online, support_online
