from __future__ import annotations

from web.app.services.marketing_funnel import (
    MARKETING_ATTRIBUTION_KEY,
    MARKETING_SESSION_KEY,
    build_marketing_snapshot,
    capture_first_touch,
    ensure_marketing_session,
    export_marketing_session,
    record_marketing_event,
    restore_marketing_session,
)
from web.app.services.seo import (
    build_robots_txt,
    build_seo,
    build_sitemap_xml,
    delta_force_schema,
)


class QueryParams(dict):
    def get(self, key, default=None):
        return super().get(key, default)


def test_dynamic_seo_builds_canonical_and_noindex():
    seo = build_seo(
        path="/games/delta-force?utm_source=test",
        title="三角洲陪玩｜魔丸娛樂",
        description="Delta page",
    )

    assert seo["canonical"] == "https://mowanentertainment.com/games/delta-force"
    assert seo["robots"] == "index, follow"
    assert seo["title"] == "三角洲陪玩｜魔丸娛樂"

    private = build_seo(
        path="/me/orders",
        title="我的訂單",
        description="private",
        noindex=True,
    )
    assert private["robots"] == "noindex, nofollow"


def test_sitemap_and_robots_cover_public_and_private_boundaries():
    sitemap = build_sitemap_xml()
    robots = build_robots_txt()

    assert "https://mowanentertainment.com/" in sitemap
    assert "https://mowanentertainment.com/games/delta-force" in sitemap
    assert "https://mowanentertainment.com/order" in sitemap
    assert "/admin" not in sitemap
    assert "/me" not in sitemap

    assert "Disallow: /admin" in robots
    assert "Disallow: /me" in robots
    assert "Sitemap: https://mowanentertainment.com/sitemap.xml" in robots


def test_delta_schema_contains_service_and_faq():
    schemas = delta_force_schema(
        faq_items=[
            {
                "question": "可以指定嗎？",
                "answer": "支援指定的商品可以選指定人員。",
            }
        ]
    )

    types = {item["@type"] for item in schemas}
    assert "Organization" in types
    assert "WebSite" in types
    assert "Service" in types
    assert "FAQPage" in types


def test_first_touch_attribution_is_not_overwritten():
    session = {}

    first = capture_first_touch(
        session,
        query_params=QueryParams(
            {
                "utm_source": "streamer_a",
                "utm_medium": "creator",
                "utm_campaign": "delta_launch",
            }
        ),
        referrer="https://example.com/video",
    )

    second = capture_first_touch(
        session,
        query_params=QueryParams(
            {
                "utm_source": "internal",
                "utm_campaign": "should_not_replace",
            }
        ),
        referrer="https://mowanentertainment.com/games/delta-force",
    )

    assert first["source"] == "streamer_a"
    assert first["medium"] == "creator"
    assert first["campaign"] == "delta_launch"
    assert second == first
    assert session[MARKETING_ATTRIBUTION_KEY]["source"] == "streamer_a"


def test_external_referrer_becomes_source_when_utm_missing():
    session = {}

    attribution = capture_first_touch(
        session,
        query_params=QueryParams({}),
        referrer="https://www.google.com/search?q=delta",
    )

    assert attribution["source"] == "www.google.com"


def test_marketing_identity_and_attribution_survive_oauth_session_rotation():
    session = {}
    session_id = ensure_marketing_session(session)

    capture_first_touch(
        session,
        query_params=QueryParams(
            {
                "utm_source": "threads",
                "utm_campaign": "delta_october",
            }
        ),
        referrer=None,
    )

    preserved = export_marketing_session(session)

    session.clear()
    session["user"] = {"id": "123"}
    restore_marketing_session(session, preserved)

    assert session[MARKETING_SESSION_KEY] == session_id
    assert session[MARKETING_ATTRIBUTION_KEY]["source"] == "threads"
    assert session[MARKETING_ATTRIBUTION_KEY]["campaign"] == "delta_october"


def test_marketing_events_roll_up_into_funnel_sources_and_campaigns(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    session = {}

    ensure_marketing_session(session)
    capture_first_touch(
        session,
        query_params=QueryParams(
            {
                "utm_source": "streamer_a",
                "utm_medium": "creator",
                "utm_campaign": "delta_launch",
            }
        ),
        referrer=None,
    )

    for event_name in (
        "landing_view",
        "view_item",
        "quote",
        "checkout",
        "order_created",
    ):
        record_marketing_event(
            session=session,
            event_name=event_name,
            path="/games/delta-force",
            customer_discord_id="100",
            properties={
                "rule_key": "basic_entertain_single",
            },
            db_file=db_path,
        )

    snapshot = build_marketing_snapshot(
        days=30,
        db_file=db_path,
    )

    assert [item["sessions"] for item in snapshot["funnel"]] == [1, 1, 1, 1, 1]
    assert snapshot["sources"][0]["source"] == "streamer_a"
    assert snapshot["sources"][0]["medium"] == "creator"
    assert snapshot["sources"][0]["sessions"] == 1
    assert snapshot["sources"][0]["orders"] == 1
    assert snapshot["campaigns"][0]["campaign"] == "delta_launch"
    assert snapshot["campaigns"][0]["orders"] == 1


def test_order_conversion_event_is_deduplicated_by_event_key(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    session = {}

    ensure_marketing_session(session)
    capture_first_touch(
        session,
        query_params=QueryParams(
            {
                "utm_source": "google",
                "utm_campaign": "delta",
            }
        ),
        referrer=None,
    )

    for _ in range(2):
        record_marketing_event(
            session=session,
            event_name="order_created",
            event_key="order:42",
            path="/order/create",
            customer_discord_id="100",
            properties={"order_id": 42},
            db_file=db_path,
        )

    snapshot = build_marketing_snapshot(
        days=30,
        db_file=db_path,
    )

    assert snapshot["event_map"]["order_created"]["events"] == 1
    assert snapshot["sources"][0]["orders"] == 1


def test_marketing_event_properties_are_bounded_and_unknown_event_rejected(tmp_path):
    db_path = tmp_path / "web_dashboard.db"
    session = {}

    try:
        record_marketing_event(
            session=session,
            event_name="arbitrary_user_input",
            path="/",
            db_file=db_path,
        )
    except ValueError as exc:
        assert "unsupported" in str(exc)
    else:
        raise AssertionError("unknown event should be rejected")
