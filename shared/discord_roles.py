from core.config import config_int_list


ADMIN_ROLE_IDS = {
    str(role_id)
    for role_id in config_int_list("ADMIN_ROLE_IDS", [])
}

WORKER_ROLE_IDS = {
    str(role_id)
    for role_id in config_int_list("WORKER_ROLE_IDS", [])
}


def has_admin_role(role_ids: list[str] | set[str]) -> bool:
    roles = {str(role_id) for role_id in role_ids}
    return bool(roles & ADMIN_ROLE_IDS)


def has_worker_role(role_ids: list[str] | set[str]) -> bool:
    roles = {str(role_id) for role_id in role_ids}
    return bool(roles & WORKER_ROLE_IDS)


def get_dashboard_access(role_ids: list[str] | set[str]) -> dict:
    return {
        "is_admin": has_admin_role(role_ids),
        "is_worker": has_worker_role(role_ids),
    }
