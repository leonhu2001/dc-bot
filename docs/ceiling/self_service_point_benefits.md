# Self-service point benefit boundary

`services/self_service_point_benefits.py` owns point-benefit catalog compatibility, eligibility checks, customer point balance lookup, and selected-benefit resolution for Discord self-service orders.

`services/self_service_financials.py` remains the pricing engine and re-exports the legacy helper names so callers do not need to change during this extraction.

The financial runtime configures the extracted module explicitly at startup; the extracted service must not import `bot.py`.
