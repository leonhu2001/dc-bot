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
CUSTOMER_SERVICE_ROLE_IDS = {"1131128849443328030", "1482084782031638548"}


def load_roles(member: WebStaffMember) -> set[str]:
    if not member.roles_json:
        return set()
    try:
        return {str(role_id) for role_id in json.loads(member.roles_json)}
    except Exception:
        return set()


def main() -> None:
    db = SessionLocal()
    try:
        members = list(db.query(WebStaffMember).all())
        changed = 0

        for member in members:
            roles = load_roles(member)
            old = (member.is_customer_service, member.is_worker, member.is_companion, member.is_active)

            member.is_customer_service = bool(roles & CUSTOMER_SERVICE_ROLE_IDS)
            member.is_worker = WORKER_ROLE_ID in roles
            member.is_companion = COMPANION_ROLE_ID in roles
            member.is_active = bool(member.is_customer_service or member.is_worker or member.is_companion)

            new = (member.is_customer_service, member.is_worker, member.is_companion, member.is_active)
            if old != new:
                changed += 1

        db.commit()

        active_total = db.query(WebStaffMember).filter(WebStaffMember.is_active.is_(True)).count()
        customer_service_total = db.query(WebStaffMember).filter(
            WebStaffMember.is_active.is_(True),
            WebStaffMember.is_customer_service.is_(True),
        ).count()
        worker_total = db.query(WebStaffMember).filter(
            WebStaffMember.is_active.is_(True),
            WebStaffMember.is_worker.is_(True),
        ).count()
        companion_total = db.query(WebStaffMember).filter(
            WebStaffMember.is_active.is_(True),
            WebStaffMember.is_companion.is_(True),
        ).count()

        print(f"changed={changed}")
        print(f"active_total={active_total}")
        print(f"customer_service_total={customer_service_total}")
        print(f"worker_total={worker_total}")
        print(f"companion_total={companion_total}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
