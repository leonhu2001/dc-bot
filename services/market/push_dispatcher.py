from __future__ import annotations

import json
import os
from dataclasses import dataclass
from urllib.parse import quote

from pywebpush import WebPushException, webpush

from services.game_registry import list_game_hubs
from services.market.push import MarketPushRepository, StoredOutboxEvent
from services.market.storage import MarketRepository


@dataclass(frozen=True)
class WebPushConfig:
    public_key: str
    private_key: str
    subject: str

    @property
    def enabled(self) -> bool:
        return bool(self.public_key and self.private_key and self.subject)


@dataclass(frozen=True)
class PushDispatchSummary:
    processed: int = 0
    sent: int = 0
    retried: int = 0
    no_subscription: int = 0


def get_web_push_config() -> WebPushConfig:
    return WebPushConfig(
        public_key=os.getenv("WEB_PUSH_VAPID_PUBLIC_KEY", "").strip(),
        private_key=os.getenv("WEB_PUSH_VAPID_PRIVATE_KEY", "").strip(),
        subject=os.getenv("WEB_PUSH_VAPID_SUBJECT", "").strip(),
    )


def _game_slug(game_key: str) -> str | None:
    for game in list_game_hubs():
        if game.key == game_key:
            return game.slug
    return None


def _payload(event: StoredOutboxEvent, market_repository: MarketRepository) -> str:
    game_slug = _game_slug(event.game_key)
    item = market_repository.get_item(event.game_key, event.item_key)
    item_name = item.name if item is not None else event.item_key
    relation = "低於或等於" if event.condition_type == "below" else "高於或等於"
    url = (
        f"/games/{game_slug}/market/items/{quote(event.item_key, safe='')}"
        if game_slug
        else "/games"
    )
    payload = {
        "title": f"{item_name} 價格提醒",
        "body": (
            f"目前 ${event.current_price:,}，已{relation}你的目標 "
            f"${event.target_price:,}。"
        ),
        "url": url,
        "tag": f"market-alert-{event.alert_id}",
        "data": {
            "game_key": event.game_key,
            "item_key": event.item_key,
            "alert_id": event.alert_id,
        },
    }
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def dispatch_pending_pushes(
    *,
    market_repository: MarketRepository,
    push_repository: MarketPushRepository,
    config: WebPushConfig | None = None,
    limit: int = 50,
) -> PushDispatchSummary:
    """Deliver durable outbox events to all active browser subscriptions.

    Successful device deliveries are remembered, so an outbox retry only
    targets devices that have not already succeeded. HTTP 404/410 disables an
    expired endpoint permanently; transient errors use bounded backoff.
    """
    push_config = config or get_web_push_config()
    if not push_config.enabled:
        return PushDispatchSummary()

    processed = sent = retried = no_subscription = 0
    events = push_repository.list_pending_outbox(limit=limit)
    for event in events:
        processed += 1
        subscriptions = push_repository.list_active_subscriptions(event.discord_user_id)
        previously_sent = push_repository.successful_subscription_ids(event.id)
        pending_subscriptions = tuple(
            subscription
            for subscription in subscriptions
            if subscription.id not in previously_sent
        )

        if not subscriptions:
            push_repository.mark_outbox_no_subscription(event.id)
            no_subscription += 1
            continue

        if not pending_subscriptions:
            push_repository.mark_outbox_sent(event.id)
            sent += 1
            continue

        data = _payload(event, market_repository)
        transient_errors: list[str] = []
        successful_this_attempt = 0
        permanent_failures = 0

        for subscription in pending_subscriptions:
            try:
                response = webpush(
                    subscription_info={
                        "endpoint": subscription.endpoint,
                        "keys": {
                            "p256dh": subscription.p256dh,
                            "auth": subscription.auth,
                        },
                    },
                    data=data,
                    vapid_private_key=push_config.private_key,
                    vapid_claims={"sub": push_config.subject},
                    ttl=600,
                    timeout=10,
                )
            except WebPushException as exc:
                response_status = getattr(getattr(exc, "response", None), "status_code", None)
                if response_status in {404, 410}:
                    permanent_failures += 1
                    push_repository.disable_subscription(
                        subscription.id,
                        f"push endpoint returned {response_status}",
                    )
                    push_repository.record_delivery(
                        outbox_id=event.id,
                        subscription_id=subscription.id,
                        status="expired",
                        response_status=response_status,
                        error_text=f"push endpoint returned {response_status}",
                    )
                else:
                    message = f"web push failed ({response_status or 'no status'})"
                    transient_errors.append(message)
                    push_repository.record_delivery(
                        outbox_id=event.id,
                        subscription_id=subscription.id,
                        status="retry",
                        response_status=response_status,
                        error_text=message,
                    )
            except Exception as exc:
                message = f"web push error: {type(exc).__name__}"
                transient_errors.append(message)
                push_repository.record_delivery(
                    outbox_id=event.id,
                    subscription_id=subscription.id,
                    status="retry",
                    error_text=message,
                )
            else:
                response_status = getattr(response, "status_code", None)
                successful_this_attempt += 1
                push_repository.mark_subscription_success(subscription.id)
                push_repository.record_delivery(
                    outbox_id=event.id,
                    subscription_id=subscription.id,
                    status="success",
                    response_status=response_status,
                )

        if transient_errors:
            push_repository.mark_outbox_retry(
                event.id,
                error_text="; ".join(transient_errors)[:512],
            )
            retried += 1
            continue

        total_successes = len(previously_sent) + successful_this_attempt
        if total_successes > 0:
            push_repository.mark_outbox_sent(event.id)
            sent += 1
        elif permanent_failures >= len(pending_subscriptions):
            push_repository.mark_outbox_no_subscription(event.id)
            no_subscription += 1
        else:
            push_repository.mark_outbox_retry(
                event.id,
                error_text="push delivery did not complete",
            )
            retried += 1

    return PushDispatchSummary(
        processed=processed,
        sent=sent,
        retried=retried,
        no_subscription=no_subscription,
    )
