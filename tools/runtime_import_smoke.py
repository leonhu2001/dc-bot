from __future__ import annotations

import importlib


CRITICAL_RUNTIME_MODULES = (
    "services.payment_review_runtime",
    "services.vip_voice_runtime",
    "services.order_runtime",
    "services.order_storage_runtime",
    "services.order_payment_runtime",
    "services.order_credential_runtime",
    "services.order_point_redemption",
    "services.self_service_runtime",
    "services.self_service_reorder",
    "services.self_service_financials",
    "services.worker_tips",
    "views.review",
)


def main() -> None:
    for module_name in CRITICAL_RUNTIME_MODULES:
        importlib.import_module(module_name)
    print(f"PASS: imported {len(CRITICAL_RUNTIME_MODULES)} critical runtime modules")


if __name__ == "__main__":
    main()
