from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.db import SessionLocal
from shared.staff_models import WebStaffMember


def main() -> None:
    db = SessionLocal()
    try:
        members = db.query(WebStaffMember).filter(WebStaffMember.is_active.is_(True)).all()
        customer_service = [member for member in members if member.is_customer_service]
        workers = [member for member in members if member.is_worker and not member.is_companion]
        companions = [member for member in members if member.is_companion]

        print(f"active_total={len(members)}")
        print(f"customer_service={len(customer_service)}")
        print(f"worker_only={len(workers)}")
        print(f"companion={len(companions)}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
