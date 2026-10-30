from __future__ import annotations

import json
from dataclasses import dataclass

from pywebpush import WebPushException, webpush

from services.market.push import MarketPushRepository, StoredPushSubscription
from services.market.push_dispatcher import WebPushConfig, get_web_push_config


@dataclass(frozen=True)
class PushTestResult:
    status: str
    response_status: int | None = None

    @property
    def ok(self) -> bool:
        return self.status == "sent"


def send_test_push(
    *,
    push_repository: MarketPushRepository,
    subscription: StoredPushSubscription,
    game_slug: str,
    config: WebPushConfig | None = None,
) -> PushTestResult:
    """Send one explicit test notification to one stored browser subscription.

    This path is intentionally separate from the durable alert outbox so a
    diagnostics click never mutates price-alert state or creates fake market
    events. Expired endpoints are disabled the same way as production alerts.
    """
    push_config = config or get_web_push_config()
    if not push_config.enabled:
        return PushTestResult(status="unconfigured")

    clean_slug = str(game_slug or "").strip() or "delta-force"
    payload = json.dumps(
        {
            "title": "魔丸娛樂測試通知",
            "body": "這台裝置已成功連上三角洲價格推播。",
            "url": f"/games/{clean_slug}/notifications",
            "tag": f"market-push-test-{subscription.id}",
            "data": {"kind": "push_test"},
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )

    try:
        response = webpush(
            subscription_info={
                "endpoint": subscription.endpoint,
                "keys": {
                    "p256dh": subscription.p256dh,
                    "auth": subscription.auth,
                },
            },
            data=payload,
            vapid_private_key=push_config.private_key,
            vapid_claims={"sub": push_config.subject},
            ttl=120,
            timeout=10,
        )
    except WebPushException as exc:
        response_status = getattr(getattr(exc, "response", None), "status_code", None)
        if response_status in {404, 410}:
            push_repository.disable_subscription(
                subscription.id,
                f"push endpoint returned {response_status}",
            )
            return PushTestResult(status="expired", response_status=response_status)
        return PushTestResult(status="failed", response_status=response_status)
    except Exception:
        return PushTestResult(status="failed")

    response_status = getattr(response, "status_code", None)
    push_repository.mark_subscription_success(subscription.id)
    return PushTestResult(status="sent", response_status=response_status)
