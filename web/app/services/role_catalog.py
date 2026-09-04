from __future__ import annotations

from dataclasses import dataclass

from services.game_roles import GAME_ROLE_LABEL_BY_ID, game_role_labels_from_role_ids


CUSTOMER_SERVICE_ROLE_ID = "1482084782031638548"
CUSTOMER_SERVICE_LABEL = "魔丸♫客服"


@dataclass(frozen=True)
class StaffRole:
    role_id: str
    label: str
    group: str


PROTECTOR_ROLES = [
    StaffRole("1500234130871550004", "魔丸♛頂護", "protector"),
    StaffRole("1500234170943934544", "魔丸♝女護", "protector"),
    StaffRole("1500751039060643990", "魔丸♜男護", "protector"),
]

COMPANION_ROLES = [
    StaffRole("1500751059239440575", "魔丸♞男陪", "companion"),
    StaffRole("1482080315798192210", "魔丸♟女陪", "companion"),
]

RECEIVER_ROLES = PROTECTOR_ROLES + COMPANION_ROLES

PROTECTOR_ROLE_IDS = {role.role_id for role in PROTECTOR_ROLES}
COMPANION_ROLE_IDS = {role.role_id for role in COMPANION_ROLES}
RECEIVER_ROLE_IDS = {role.role_id for role in RECEIVER_ROLES}

ROLE_LABEL_BY_ID = {
    role.role_id: role.label
    for role in RECEIVER_ROLES
}

# ???????????????? RECEIVER_ROLE_IDS?
# ??????????????????/?????
ROLE_LABEL_BY_ID.update(GAME_ROLE_LABEL_BY_ID)

STAFF_ROLE_FILTERS = [
    {"value": "", "label": "全部"},
    {"value": "customer_service", "label": CUSTOMER_SERVICE_LABEL},
    *[
        {"value": role.role_id, "label": role.label}
        for role in RECEIVER_ROLES
    ],
]


def normalize_role_ids(value) -> set[str]:
    if not value:
        return set()

    if isinstance(value, (list, tuple, set)):
        return {str(item).strip() for item in value if str(item).strip()}

    return {
        item.strip()
        for item in str(value).split(",")
        if item.strip()
    }



def game_role_labels_from_roles(role_ids) -> list[str]:
    """?? Discord ?????????????????"""
    return game_role_labels_from_role_ids(role_ids)

def receiver_labels_from_roles(role_ids) -> list[str]:
    role_set = normalize_role_ids(role_ids)
    return [
        role.label
        for role in RECEIVER_ROLES
        if role.role_id in role_set
    ]


def is_customer_service(role_ids, customer_service_role_ids=None) -> bool:
    role_set = normalize_role_ids(role_ids)

    if customer_service_role_ids:
        return bool(role_set & normalize_role_ids(customer_service_role_ids))

    return CUSTOMER_SERVICE_ROLE_ID in role_set


def is_protector(role_ids) -> bool:
    return bool(normalize_role_ids(role_ids) & PROTECTOR_ROLE_IDS)


def is_companion(role_ids) -> bool:
    return bool(normalize_role_ids(role_ids) & COMPANION_ROLE_IDS)


def is_receiver(role_ids) -> bool:
    return bool(normalize_role_ids(role_ids) & RECEIVER_ROLE_IDS)


def can_login_dashboard(role_ids, *, admin_role_ids=None, customer_service_role_ids=None) -> bool:
    role_set = normalize_role_ids(role_ids)

    is_admin = bool(role_set & normalize_role_ids(admin_role_ids))
    is_cs = is_customer_service(role_set, customer_service_role_ids)
    is_staff_receiver = is_receiver(role_set)

    return is_admin or is_cs or is_staff_receiver
