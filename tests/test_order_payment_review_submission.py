from __future__ import annotations

import asyncio
from pathlib import Path

from services import order_payment_review_submission as review_submission


class FakeResponse:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple, dict]] = []

    async def send_message(self, *args, **kwargs) -> None:
        self.calls.append((args, kwargs))


class FakeInteraction:
    def __init__(self) -> None:
        self.response = FakeResponse()


def _kwargs(interaction: FakeInteraction, data: dict) -> dict:
    return {
        "interaction": interaction,
        "data": data,
        "customer_id": 1,
        "channel_id": 2,
        "amount": 500,
        "payment_method": "dummy",
        "web_order_id": 3,
        "order_category_labels": {},
        "to_int": lambda value, default=None: default if value is None else int(value),
        "taipei_now_iso": lambda: "2026-10-19T00:00:00+08:00",
        "remember_order": lambda *_: None,
        "save_data": lambda: None,
        "payment_method_embed_builder": lambda **_: None,
        "payment_method_view": lambda **_: None,
    }


def test_non_external_payment_is_not_handled(monkeypatch) -> None:
    monkeypatch.setattr(
        review_submission,
        "requires_external_payment_review",
        lambda *_: False,
    )
    interaction = FakeInteraction()

    handled = asyncio.run(
        review_submission.submit_external_payment_review_if_needed(
            **_kwargs(interaction, {})
        )
    )

    assert handled is False
    assert interaction.response.calls == []


def test_approved_external_review_continues_finalization(monkeypatch) -> None:
    monkeypatch.setattr(
        review_submission,
        "requires_external_payment_review",
        lambda *_: True,
    )
    interaction = FakeInteraction()

    handled = asyncio.run(
        review_submission.submit_external_payment_review_if_needed(
            **_kwargs(interaction, {"payment_review_approved": True})
        )
    )

    assert handled is False
    assert interaction.response.calls == []


def test_pending_external_review_stops_duplicate_submission(monkeypatch) -> None:
    monkeypatch.setattr(
        review_submission,
        "requires_external_payment_review",
        lambda *_: True,
    )
    interaction = FakeInteraction()

    handled = asyncio.run(
        review_submission.submit_external_payment_review_if_needed(
            **_kwargs(interaction, {"payment_review_pending": True})
        )
    )

    assert handled is True
    assert len(interaction.response.calls) == 1
    args, kwargs = interaction.response.calls[0]
    assert "不要重複送出" in args[0]
    assert kwargs["ephemeral"] is True


def test_runtime_delegates_external_review_submission() -> None:
    runtime_source = Path("services/order_payment_runtime.py").read_text(encoding="utf-8")
    extracted_source = Path("services/order_payment_review_submission.py").read_text(
        encoding="utf-8"
    )

    assert "submit_external_payment_review_if_needed" in runtime_source
    assert "create_payment_review(" not in runtime_source
    assert "create_payment_review(" in extracted_source
