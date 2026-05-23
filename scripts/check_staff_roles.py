from pathlib import Path
import json
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.db import SessionLocal
from shared.staff_models import WebStaffMember


def load_roles(member: WebStaffMember) -> list[str]:
    if not member.roles_json:
        return []

    try:
        roles = json.loads(member.roles_json)
    except json.JSONDecodeError:
        return []

    return [str(role_id) for role_id in roles]


def main() -> None:
    db = SessionLocal()

    try:
        members = db.query(WebStaffMember).order_by(WebStaffMember.display_name.asc()).all()

        customer_service_members = [
            member for member in members
            if member.is_active and member.is_customer_service
        ]
        worker_members = [
            member for member in members
            if member.is_active and member.is_worker
        ]
        companion_members = [
            member for member in members
            if member.is_active and member.is_companion
        ]

        print(f"total_staff={len(members)}")
        print(f"active_customer_service={len(customer_service_members)}")
        print(f"active_workers={len(worker_members)}")
        print(f"active_companions={len(companion_members)}")
        print("")

        print("workers:")
        for member in worker_members:
            print(f"- {member.display_name or member.username or member.discord_id} ({member.discord_id}) roles={','.join(load_roles(member))}")

        print("")
        print("companions:")
        for member in companion_members:
            print(f"- {member.display_name or member.username or member.discord_id} ({member.discord_id}) roles={','.join(load_roles(member))}")

        print("")
        print("customer_service:")
        for member in customer_service_members:
            print(f"- {member.display_name or member.username or member.discord_id} ({member.discord_id}) roles={','.join(load_roles(member))}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
