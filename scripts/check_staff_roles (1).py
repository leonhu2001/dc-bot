from pathlib import Path
import json
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.db import SessionLocal
from shared.staff_models import WebStaffMember

WORKER_ROLE_ID = "1503701170504339458"
COMPANION_ROLE_ID = "1503706721883783218"


def roles_of(member: WebStaffMember) -> set[str]:
    try:
        return {str(role_id) for role_id in json.loads(member.roles_json or "[]")}
    except Exception:
        return set()


def label(member: WebStaffMember) -> str:
    return member.display_name or member.global_name or member.username or member.discord_id


def main() -> None:
    db = SessionLocal()
    try:
        members = list(db.query(WebStaffMember).filter(WebStaffMember.is_active.is_(True)).all())
        workers = [m for m in members if m.is_worker]
        companions = [m for m in members if m.is_companion]
        customer_services = [m for m in members if m.is_customer_service]

        print(f"active_total={len(members)}")
        print(f"customer_service_total={len(customer_services)}")
        print(f"worker_total={len(workers)}")
        print(f"companion_total={len(companions)}")
        print("")

        print("workers:")
        for member in workers:
            roles = roles_of(member)
            status = "OK" if WORKER_ROLE_ID in roles else "BAD"
            print(f"{status} {member.discord_id} {label(member)} roles={sorted(roles)}")

        print("")
        print("companions:")
        for member in companions:
            roles = roles_of(member)
            status = "OK" if COMPANION_ROLE_ID in roles else "BAD"
            print(f"{status} {member.discord_id} {label(member)} roles={sorted(roles)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
