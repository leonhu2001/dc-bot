from shared.db import SessionLocal
from shared.models import WebOrder
from web.app.services.order_service import recalculate_order_payouts

db = SessionLocal()

try:
    orders = (
        db.query(WebOrder)
        .filter(WebOrder.status == "closed")
        .order_by(WebOrder.id.asc())
        .all()
    )

    ok = 0
    failed = 0

    print(f"closed orders: {len(orders)}")

    for order in orders:
        try:
            recalculate_order_payouts(db, order.id)
            ok += 1
            print(f"OK WEB-{order.id}")
        except Exception as exc:
            failed += 1
            print(f"FAILED WEB-{order.id}: {exc}")

    db.commit()

    print("done")
    print(f"ok={ok}")
    print(f"failed={failed}")

finally:
    db.close()
