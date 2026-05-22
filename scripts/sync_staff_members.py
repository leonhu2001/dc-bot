from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.db import SessionLocal, create_all_tables
from web.app.services.staff_service import sync_staff_members_from_discord


def main() -> None:
    create_all_tables()

    db = SessionLocal()

    try:
        result = sync_staff_members_from_discord(db)
    finally:
        db.close()

    print("Discord staff sync complete")
    print(f"total_seen={result['total_seen']}")
    print(f"synced_count={result['synced_count']}")
    print(f"disabled_count={result['disabled_count']}")


if __name__ == "__main__":
    main()
