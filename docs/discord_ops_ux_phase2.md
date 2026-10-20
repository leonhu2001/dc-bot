# Discord operations UX phase 2

This phase is intentionally presentation-only around acceptance rejections and actionable customer-service review alerts.

- Acceptance eligibility continues to be decided by `shared/order_acceptance.py`.
- New website-order review alerts reuse the existing footer dedupe before notifying customer service.
- Admin deep links point to the existing order workspace and do not mutate order state.
