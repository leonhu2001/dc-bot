from __future__ import annotations

from sqlalchemy import text

from web.app.services.staff_service import list_customer_service_members


def _mw4a2r6_table_exists(
    db,
    table_name: str,
) -> bool:

    row = db.execute(
        text(
            """
            SELECT 1

            FROM sqlite_master

            WHERE type = 'table'
              AND name = :name

            LIMIT 1
            """
        ),
        {
            "name":
                table_name,
        },
    ).fetchone()


    return (
        row is not None
    )


def _mw4a2r6_safe_int(
    value,
    default=0,
):

    try:

        return int(
            value
        )

    except (
        TypeError,
        ValueError,
    ):

        return default


def _mw4a2r6_json(
    value,
    default=None,
):

    import json


    if default is None:

        default = {}


    if isinstance(
        value,
        (
            dict,
            list,
        ),
    ):

        return value


    if not value:

        return default


    try:

        return json.loads(
            str(value)
        )

    except Exception:

        return default


def _mw4a2r6_time(
    value,
):

    raw = str(
        value
        or ""
    ).strip()


    if not raw:

        return "—"


    return (
        raw
        .replace(
            "T",
            " ",
        )
        .replace(
            "Z",
            "",
        )
    )[:16]


def _mw4a2r6_status_label(
    status,
):

    status = str(
        status
        or ""
    ).strip().lower()


    labels = {

        "pending_cs_dispatch":
            "待客服確認",

        "waiting_acceptance":
            "等待接單",

        "accepted_pending_pay":
            "等待付款",

        "active":
            "進行中",

        "created":
            "已建立",

        "paid":
            "已付款",

        "completed":
            "已完成",

        "closed":
            "已結單",

        "done":
            "已完成",

        "cancelled":
            "已取消",

        "canceled":
            "已取消",

    }


    return labels.get(
        status,
        status or "未知",
    )


def _mw4a2r6_meta_map(
    db,
):

    if not _mw4a2r6_table_exists(
        db,
        "web_admin_order_meta",
    ):

        return {}


    rows = (
        db.execute(
            text(
                """
                SELECT *

                FROM web_admin_order_meta
                """
            )
        )
        .mappings()
        .all()
    )


    result = {}


    for row in rows:

        data = dict(
            row
        )


        order_id = (
            _mw4a2r6_safe_int(
                data.get(
                    "order_id"
                ),
                None,
            )
        )


        if order_id is not None:

            result[
                order_id
            ] = data


    return result


def _mw4a2r6_ensure_meta_table(
    db,
):

    db.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS
            web_admin_order_meta (

                order_id INTEGER
                    PRIMARY KEY,

                internal_note TEXT
                    NOT NULL
                    DEFAULT '',

                needs_attention INTEGER
                    NOT NULL
                    DEFAULT 0,

                attention_reason TEXT
                    NOT NULL
                    DEFAULT '',

                updated_by_discord_id TEXT,

                updated_by_display_name TEXT,

                updated_at TEXT
                    NOT NULL
                    DEFAULT CURRENT_TIMESTAMP

            )
            """
        )
    )


def _mw4a2r6_user_name(
    user,
):

    return str(

        user.get(
            "display_name"
        )

        or user.get(
            "global_name"
        )

        or user.get(
            "username"
        )

        or user.get(
            "name"
        )

        or user.get(
            "id"
        )

        or ""

    )


def _mw4a2r6_staff_map(
    db,
):

    if not _mw4a2r6_table_exists(
        db,
        "web_staff_members",
    ):

        return {}


    rows = (
        db.execute(
            text(
                """
                SELECT
                    discord_id,
                    username,
                    display_name,
                    global_name

                FROM web_staff_members
                """
            )
        )
        .mappings()
        .all()
    )


    result = {}


    for row in rows:

        data = dict(
            row
        )


        discord_id = str(
            data.get(
                "discord_id"
            )
            or ""
        ).strip()


        if not discord_id:

            continue


        result[
            discord_id
        ] = (

            data.get(
                "display_name"
            )

            or data.get(
                "global_name"
            )

            or data.get(
                "username"
            )

            or discord_id

        )


    return result


def _mw4a2r6_cs_members(
    db,
):

    members = list(
        list_customer_service_members(
            db
        )
    )


    result = []


    for member in members:

        if isinstance(
            member,
            dict,
        ):

            getter = member.get

        else:

            getter = lambda name, default=None: getattr(
                member,
                name,
                default,
            )


        discord_id = str(
            getter(
                "discord_id",
                "",
            )
            or ""
        ).strip()


        if not discord_id:

            continue


        result.append(
            {
                "discord_id":
                    discord_id,

                "name":
                    str(
                        getter(
                            "display_name",
                            None,
                        )

                        or getter(
                            "global_name",
                            None,
                        )

                        or getter(
                            "username",
                            None,
                        )

                        or discord_id
                    ),
            }
        )


    return result


def _mw4a2r6_load_order_bundle(
    db,
    order_id: int,
):

    raw_row = (
        db.execute(
            text(
                """
                SELECT *

                FROM web_orders

                WHERE id =
                    :order_id

                LIMIT 1
                """
            ),
            {
                "order_id":
                    int(
                        order_id
                    ),
            },
        )
        .mappings()
        .first()
    )


    if raw_row is None:

        return (
            None,
            [],
            {},
        )


    raw = dict(
        raw_row
    )


    acceptance = {}


    if _mw4a2r6_table_exists(
        db,
        "order_acceptance_meta",
    ):

        row = (
            db.execute(
                text(
                    """
                    SELECT *

                    FROM order_acceptance_meta

                    WHERE order_id =
                        :order_id

                    LIMIT 1
                    """
                ),
                {
                    "order_id":
                        int(
                            order_id
                        ),
                },
            )
            .mappings()
            .first()
        )


        if row is not None:

            acceptance = dict(
                row
            )


    submission = {}


    if _mw4a2r6_table_exists(
        db,
        "web_order_submission_meta",
    ):

        row = (
            db.execute(
                text(
                    """
                    SELECT *

                    FROM web_order_submission_meta

                    WHERE order_id =
                        :order_id

                    LIMIT 1
                    """
                ),
                {
                    "order_id":
                        int(
                            order_id
                        ),
                },
            )
            .mappings()
            .first()
        )


        if row is not None:

            submission = dict(
                row
            )


    staff_by_id = (
        _mw4a2r6_staff_map(
            db
        )
    )


    price_snapshot = (
        _mw4a2r6_json(
            raw.get(
                "price_snapshot_json"
            ),
            {},
        )
    )


    submission_payload = (
        _mw4a2r6_json(
            submission.get(
                "submission_payload_json"
            ),
            {},
        )
    )


    specified_ids = (
        _mw4a2r6_json(
            acceptance.get(
                "specified_staff_ids_json"
            ),
            [],
        )
    )


    if not isinstance(
        specified_ids,
        list,
    ):

        specified_ids = []


    if not specified_ids:

        for candidate in (

            price_snapshot.get(
                "specified_staff_ids"
            ),

            submission_payload.get(
                "specified_staff_ids"
            ),

            submission_payload.get(
                "selected_staff_ids"
            ),

        ):

            if isinstance(
                candidate,
                list,
            ):

                specified_ids = candidate

                break


    specified_staff = []


    for value in specified_ids:

        discord_id = str(
            value
            or ""
        ).strip()


        if not discord_id:

            continue


        specified_staff.append(
            {
                "id":
                    discord_id,

                "name":
                    staff_by_id.get(
                        discord_id,
                        discord_id,
                    ),
            }
        )


    customer_id = str(
        raw.get(
            "customer_discord_id"
        )
        or ""
    ).strip()


    amount = (
        _mw4a2r6_safe_int(
            raw.get(
                "customer_pay_amount"
            ),
            None,
        )
    )


    if amount is None:

        amount = (
            _mw4a2r6_safe_int(
                raw.get(
                    "amount"
                ),
                0,
            )
        )


    status = str(
        raw.get(
            "status"
        )
        or "unknown"
    ).strip().lower()


    meta = (
        _mw4a2r6_meta_map(
            db
        )
        .get(
            int(
                order_id
            ),
            {},
        )
    )

    cancellation = {}
    if _mw4a2r6_table_exists(
        db,
        "order_cancellations",
    ):
        cancellation_row = (
            db.execute(
                text(
                    """
                    SELECT *
                    FROM order_cancellations
                    WHERE order_id = :order_id
                    LIMIT 1
                    """
                ),
                {"order_id": int(order_id)},
            )
            .mappings()
            .first()
        )
        if cancellation_row is not None:
            cancellation = dict(cancellation_row)


    order = {

        "id":
            int(
                order_id
            ),

        "order_no":
            str(
                raw.get(
                    "bot_order_no"
                )
                or f"WEB-{order_id}"
            ),

        "status":
            status,

        "status_label":
            _mw4a2r6_status_label(
                status
            ),

        "customer_id":
            customer_id,

        "customer_name":
            str(
                raw.get(
                    "customer_display_name"
                )

                or raw.get(
                    "customer_username"
                )

                or customer_id

                or "未紀錄"
            ),

        "category":
            str(
                raw.get(
                    "category"
                )
                or "未分類"
            ),

        "item":
            str(
                raw.get(
                    "item"
                )
                or "未紀錄"
            ),

        "quantity":
            _mw4a2r6_safe_int(
                raw.get(
                    "quantity"
                ),
                1,
            ),

        "amount":
            amount,

        "payment_method":
            str(
                raw.get(
                    "payment_method"
                )
                or "待付款"
            ),

        "created_display":
            _mw4a2r6_time(
                raw.get(
                    "created_at"
                )
                or raw.get(
                    "created_time"
                )
            ),

        "updated_display":
            _mw4a2r6_time(
                raw.get(
                    "updated_at"
                )
            ),

        "ticket_channel_id":
            str(
                raw.get(
                    "ticket_channel_id"
                )
                or ""
            ),

        "dispatch_channel_id":
            str(
                raw.get(
                    "dispatch_channel_id"
                )
                or ""
            ),

        "dispatch_message_id":
            str(
                raw.get(
                    "dispatch_message_id"
                )
                or ""
            ),

        "customer_service_id":
            str(
                raw.get(
                    "customer_service_discord_id"
                )
                or ""
            ),

        "customer_service":
            str(
                raw.get(
                    "customer_service_display_name"
                )

                or raw.get(
                    "customer_service_discord_id"
                )

                or ""
            ),

        "specified_staff":
            specified_staff,

        "extra_requirements":
            str(
                submission.get(
                    "extra_requirements"
                )

                or submission_payload.get(
                    "extra_requirements"
                )

                or ""
            ),

        "terms_version":
            str(
                submission.get(
                    "terms_version"
                )
                or ""
            ),

        "rule_key":
            str(
                raw.get(
                    "order_rule_key"
                )
                or ""
            ),

        "note":
            str(
                raw.get(
                    "note"
                )
                or ""
            ),

        "internal_note":
            str(
                meta.get(
                    "internal_note"
                )
                or ""
            ),

        "needs_attention":
            bool(
                _mw4a2r6_safe_int(
                    meta.get(
                        "needs_attention"
                    ),
                    0,
                )
            ),

        "attention_reason":
            str(
                meta.get(
                    "attention_reason"
                )
                or ""
            ),

        "cancellation_reason_code":
            str(
                cancellation.get(
                    "reason_code"
                )
                or "unspecified"
            ),

        "cancellation_reason_text":
            str(
                cancellation.get(
                    "reason_text"
                )
                or ""
            ),

        "cancellation_source":
            str(
                cancellation.get(
                    "source"
                )
                or ""
            ),

        "meta_updated_by":
            str(
                meta.get(
                    "updated_by_display_name"
                )
                or ""
            ),

        "meta_updated_at":
            _mw4a2r6_time(
                meta.get(
                    "updated_at"
                )
            ),

    }


    history = []


    if customer_id:

        rows = (
            db.execute(
                text(
                    """
                    SELECT *

                    FROM web_orders

                    WHERE customer_discord_id =
                        :customer_id

                      AND id !=
                        :order_id

                    ORDER BY id DESC

                    LIMIT 8
                    """
                ),
                {
                    "customer_id":
                        customer_id,

                    "order_id":
                        int(
                            order_id
                        ),
                },
            )
            .mappings()
            .all()
        )


        for row in rows:

            data = dict(
                row
            )


            history_amount = (
                _mw4a2r6_safe_int(
                    data.get(
                        "customer_pay_amount"
                    ),
                    None,
                )
            )


            if history_amount is None:

                history_amount = (
                    _mw4a2r6_safe_int(
                        data.get(
                            "amount"
                        ),
                        0,
                    )
                )


            history_status = str(
                data.get(
                    "status"
                )
                or ""
            ).strip().lower()


            history.append(
                {
                    "id":
                        _mw4a2r6_safe_int(
                            data.get(
                                "id"
                            ),
                            0,
                        ),

                    "order_no":
                        str(
                            data.get(
                                "bot_order_no"
                            )

                            or (
                                "WEB-"
                                + str(
                                    data.get(
                                        "id"
                                    )
                                    or ""
                                )
                            )
                        ),

                    "item":
                        str(
                            data.get(
                                "item"
                            )
                            or "未紀錄"
                        ),

                    "status_label":
                        _mw4a2r6_status_label(
                            history_status
                        ),

                    "amount":
                        history_amount,
                }
            )


    return (
        order,
        history,
        meta,
    )
