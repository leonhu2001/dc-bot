from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.db import SessionLocal
from shared.models import WebOrder


def main() -> None:
    db = SessionLocal()

    try:
        demo_orders = (
            db.query(WebOrder)
            .filter(WebOrder.bot_order_no.like("DEMO-%"))
            .all()
        )

        count = len(demo_orders)

        for order in demo_orders:
            db.delete(order)

        db.commit()
        print(f"deleted_demo_orders={count}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
