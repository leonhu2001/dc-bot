from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp

from services.support_calls import build_support_call_snapshot
from web.app.config import config
from web.app.routers.admin_payout_summary import build_operations_report
from web.app.services.anomaly_detection import build_anomaly_snapshot
from web.app.services.marketing_funnel import build_marketing_snapshot


_ALLOWED_PERIODS = {"month", "quarter", "year", "all"}


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[3] / "web_dashboard.db"


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type='table' AND name=?
        LIMIT 1
        """,
        (str(table_name),),
    ).fetchone()
    return row is not None


def _period_days(period: str) -> int:
    return {
        "month": 30,
        "quarter": 90,
        "year": 365,
        "all": 365,
    }.get(period, 90)


def build_recent_order_signals(
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    """
    Small, whitelisted operational aggregates for the AI analysis page.

    This deliberately exposes only counts/rates and product labels. It never
    returns customer IDs, staff IDs, order notes, credentials, payment proofs,
    wallet rows, or arbitrary SQL results.
    """
    path = _db_path(db_file)
    result: dict[str, Any] = {
        "daily": [],
        "service_change_14d": [],
        "acceptance_by_hour_30d": [],
    }

    if not path.exists():
        return result

    try:
        with sqlite3.connect(path, timeout=15) as conn:
            conn.row_factory = sqlite3.Row

            if not _table_exists(conn, "web_orders"):
                return result

            daily_rows = conn.execute(
                """
                SELECT
                    date(datetime(created_at, '+8 hours')) AS day,
                    COUNT(*) AS created_orders,
                    SUM(
                        CASE
                            WHEN LOWER(TRIM(COALESCE(status, '')))
                                 IN ('cancelled', 'canceled')
                            THEN 1 ELSE 0
                        END
                    ) AS cancelled_orders
                FROM web_orders
                WHERE datetime(created_at, '+8 hours')
                      >= datetime('now', '+8 hours', '-14 days')
                GROUP BY day
                ORDER BY day ASC
                """
            ).fetchall()

            result["daily"] = [
                {
                    "day": str(row["day"] or ""),
                    "created_orders": int(row["created_orders"] or 0),
                    "cancelled_orders": int(row["cancelled_orders"] or 0),
                    "cancellation_rate": (
                        round(
                            int(row["cancelled_orders"] or 0)
                            * 100
                            / int(row["created_orders"] or 0),
                            1,
                        )
                        if int(row["created_orders"] or 0)
                        else 0.0
                    ),
                }
                for row in daily_rows
            ]

            service_rows = conn.execute(
                """
                SELECT
                    COALESCE(
                        NULLIF(TRIM(item), ''),
                        NULLIF(TRIM(category), ''),
                        '其他'
                    ) AS label,
                    SUM(
                        CASE
                            WHEN datetime(created_at, '+8 hours')
                                 >= datetime('now', '+8 hours', '-14 days')
                            THEN 1 ELSE 0
                        END
                    ) AS current_created,
                    SUM(
                        CASE
                            WHEN datetime(created_at, '+8 hours')
                                 >= datetime('now', '+8 hours', '-14 days')
                             AND LOWER(TRIM(COALESCE(status, '')))
                                 IN ('cancelled', 'canceled')
                            THEN 1 ELSE 0
                        END
                    ) AS current_cancelled,
                    SUM(
                        CASE
                            WHEN datetime(created_at, '+8 hours')
                                 >= datetime('now', '+8 hours', '-28 days')
                             AND datetime(created_at, '+8 hours')
                                 < datetime('now', '+8 hours', '-14 days')
                            THEN 1 ELSE 0
                        END
                    ) AS previous_created,
                    SUM(
                        CASE
                            WHEN datetime(created_at, '+8 hours')
                                 >= datetime('now', '+8 hours', '-28 days')
                             AND datetime(created_at, '+8 hours')
                                 < datetime('now', '+8 hours', '-14 days')
                             AND LOWER(TRIM(COALESCE(status, '')))
                                 IN ('cancelled', 'canceled')
                            THEN 1 ELSE 0
                        END
                    ) AS previous_cancelled
                FROM web_orders
                WHERE datetime(created_at, '+8 hours')
                      >= datetime('now', '+8 hours', '-28 days')
                GROUP BY label
                HAVING current_created > 0 OR previous_created > 0
                ORDER BY (current_created + previous_created) DESC, label ASC
                LIMIT 20
                """
            ).fetchall()

            service_change: list[dict[str, Any]] = []
            for row in service_rows:
                current_created = int(row["current_created"] or 0)
                current_cancelled = int(row["current_cancelled"] or 0)
                previous_created = int(row["previous_created"] or 0)
                previous_cancelled = int(row["previous_cancelled"] or 0)

                service_change.append(
                    {
                        "label": str(row["label"] or "其他")[:160],
                        "current_14d_orders": current_created,
                        "current_14d_cancelled": current_cancelled,
                        "current_14d_cancellation_rate": (
                            round(current_cancelled * 100 / current_created, 1)
                            if current_created
                            else 0.0
                        ),
                        "previous_14d_orders": previous_created,
                        "previous_14d_cancelled": previous_cancelled,
                        "previous_14d_cancellation_rate": (
                            round(previous_cancelled * 100 / previous_created, 1)
                            if previous_created
                            else 0.0
                        ),
                    }
                )

            result["service_change_14d"] = service_change

            if (
                _table_exists(conn, "order_acceptance_meta")
                and _table_exists(conn, "order_acceptance_claims")
            ):
                hour_rows = conn.execute(
                    """
                    WITH acceptance AS (
                        SELECT
                            m.order_id,
                            CAST(
                                strftime(
                                    '%H',
                                    datetime(m.created_at, '+8 hours')
                                ) AS INTEGER
                            ) AS hour,
                            m.created_at AS created_at,
                            MIN(c.claimed_at) AS first_claimed_at
                        FROM order_acceptance_meta m
                        LEFT JOIN order_acceptance_claims c
                            ON c.order_id = m.order_id
                        WHERE datetime(m.created_at, '+8 hours')
                              >= datetime('now', '+8 hours', '-30 days')
                        GROUP BY m.order_id, hour, m.created_at
                    )
                    SELECT
                        hour,
                        COUNT(*) AS orders,
                        SUM(
                            CASE WHEN first_claimed_at IS NULL
                                 THEN 1 ELSE 0 END
                        ) AS no_claim_orders,
                        AVG(
                            CASE
                                WHEN first_claimed_at IS NOT NULL
                                THEN MAX(
                                    0,
                                    (
                                        julianday(first_claimed_at)
                                        - julianday(created_at)
                                    ) * 24 * 60
                                )
                                ELSE NULL
                            END
                        ) AS avg_first_claim_minutes
                    FROM acceptance
                    GROUP BY hour
                    ORDER BY hour ASC
                    """
                ).fetchall()

                result["acceptance_by_hour_30d"] = [
                    {
                        "hour": int(row["hour"] or 0),
                        "orders": int(row["orders"] or 0),
                        "no_claim_orders": int(row["no_claim_orders"] or 0),
                        "avg_first_claim_minutes": (
                            round(float(row["avg_first_claim_minutes"]), 1)
                            if row["avg_first_claim_minutes"] is not None
                            else None
                        ),
                    }
                    for row in hour_rows
                ]

    except sqlite3.Error as exc:
        print(
            f"[operations-ai] signal query failed {type(exc).__name__}",
            flush=True,
        )

    return result


def _compact_report(report: dict[str, Any]) -> dict[str, Any]:
    comparison = report.get("comparison")
    if not isinstance(comparison, dict):
        comparison = {}

    return {
        "period": str(report.get("period") or ""),
        "period_label": str(report.get("period_label") or ""),
        "previous_label": str(report.get("previous_label") or ""),
        "comparison_history_exists": bool(
            report.get("comparison_history_exists")
        ),
        "revenue": int(report.get("revenue") or 0),
        "payroll": int(report.get("payroll") or 0),
        "retained": int(report.get("retained") or 0),
        "retained_rate": float(report.get("retained_rate") or 0),
        "payroll_rate": float(report.get("payroll_rate") or 0),
        "order_count": int(report.get("order_count") or 0),
        "avg_order": int(report.get("avg_order") or 0),
        "customer_count": int(report.get("customer_count") or 0),
        "repeat_customers": int(report.get("repeat_customers") or 0),
        "repeat_rate": float(report.get("repeat_rate") or 0),
        "discount_total": int(report.get("discount_total") or 0),
        "created_orders": int(report.get("created_orders") or 0),
        "cancelled_orders": int(report.get("cancelled_orders") or 0),
        "cancellation_rate": float(
            report.get("cancellation_rate") or 0
        ),
        "new_customer_revenue": int(
            report.get("new_customer_revenue") or 0
        ),
        "new_customer_orders": int(
            report.get("new_customer_orders") or 0
        ),
        "new_customer_revenue_share": float(
            report.get("new_customer_revenue_share") or 0
        ),
        "repeat_customer_revenue": int(
            report.get("repeat_customer_revenue") or 0
        ),
        "repeat_customer_orders": int(
            report.get("repeat_customer_orders") or 0
        ),
        "repeat_customer_revenue_share": float(
            report.get("repeat_customer_revenue_share") or 0
        ),
        "comparison": {
            key: {
                "previous": value.get("previous"),
                "delta": value.get("delta"),
                "rate": value.get("rate"),
            }
            for key, value in comparison.items()
            if isinstance(value, dict)
            and key
            in {
                "revenue",
                "payroll",
                "retained",
                "avg_order",
                "order_count",
                "customer_count",
            }
        },
        "services": [
            {
                "label": str(item.get("label") or "")[:160],
                "orders": int(item.get("orders") or 0),
                "revenue": int(item.get("revenue") or 0),
                "payroll": int(item.get("payroll") or 0),
                "retained": int(item.get("retained") or 0),
                "retained_rate": float(
                    item.get("retained_rate") or 0
                ),
            }
            for item in (report.get("service_rows") or [])[:10]
            if isinstance(item, dict)
        ],
        "payment_methods": [
            {
                "label": str(item.get("label") or "")[:120],
                "orders": int(item.get("orders") or 0),
                "revenue": int(item.get("revenue") or 0),
                "share": float(item.get("share") or 0),
            }
            for item in (report.get("payment_rows") or [])[:10]
            if isinstance(item, dict)
        ],
        "daily_revenue": [
            {
                "day": str(day),
                "revenue": int(value or 0),
            }
            for day, value in zip(
                report.get("daily_labels") or [],
                report.get("daily_values") or [],
            )
        ][-31:],
    }


def build_safe_operations_snapshot(
    period: str | None = "quarter",
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    clean_period = str(period or "quarter").strip().lower()
    if clean_period not in _ALLOWED_PERIODS:
        clean_period = "quarter"

    report = build_operations_report(clean_period)
    days = _period_days(clean_period)

    try:
        anomaly = build_anomaly_snapshot(limit=80)
    except Exception as exc:
        print(
            f"[operations-ai] anomaly snapshot failed {type(exc).__name__}",
            flush=True,
        )
        anomaly = {
            "status": "unavailable",
            "issue_count": 0,
            "critical_count": 0,
            "warning_count": 0,
            "category_counts": {},
            "issues": [],
        }

    try:
        support = build_support_call_snapshot(
            db_file=db_file,
            days=days,
            limit=500,
        )
    except Exception as exc:
        print(
            f"[operations-ai] support snapshot failed {type(exc).__name__}",
            flush=True,
        )
        support = {}

    try:
        marketing = build_marketing_snapshot(
            days=days,
            db_file=db_file,
        )
    except Exception as exc:
        print(
            f"[operations-ai] marketing snapshot failed {type(exc).__name__}",
            flush=True,
        )
        marketing = {}

    safe_anomaly_issues = []
    for item in (anomaly.get("issues") or [])[:25]:
        if not isinstance(item, dict):
            continue
        safe_anomaly_issues.append(
            {
                "category": str(item.get("category") or "")[:80],
                "category_label": str(
                    item.get("category_label") or ""
                )[:80],
                "severity": str(item.get("severity") or "")[:40],
                "title": str(item.get("title") or "")[:200],
                "age_minutes": item.get("age_minutes"),
            }
        )

    return {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"
        ),
        "financial_orders": _compact_report(report),
        "recent_order_signals": build_recent_order_signals(
            db_file=db_file
        ),
        "anomalies": {
            "status": str(anomaly.get("status") or ""),
            "issue_count": int(anomaly.get("issue_count") or 0),
            "critical_count": int(
                anomaly.get("critical_count") or 0
            ),
            "warning_count": int(
                anomaly.get("warning_count") or 0
            ),
            "category_counts": dict(
                anomaly.get("category_counts") or {}
            ),
            "issues": safe_anomaly_issues,
        },
        "customer_service": {
            "days": int(support.get("days") or days),
            "active_count": int(support.get("active_count") or 0),
            "open_count": int(support.get("open_count") or 0),
            "claimed_count": int(
                support.get("claimed_count") or 0
            ),
            "recent_count": int(
                support.get("recent_count") or 0
            ),
            "response_count": int(
                support.get("response_count") or 0
            ),
            "within_5_rate": support.get("within_5_rate"),
            "average_response_seconds": support.get(
                "average_response_seconds"
            ),
            "median_response_seconds": support.get(
                "median_response_seconds"
            ),
        },
        "marketing": {
            "days": int(marketing.get("days") or days),
            "funnel": [
                {
                    "label": str(item.get("label") or "")[:100],
                    "events": int(item.get("events") or 0),
                    "sessions": int(item.get("sessions") or 0),
                }
                for item in (marketing.get("funnel") or [])[:10]
                if isinstance(item, dict)
            ],
            "sources": [
                {
                    "source": str(item.get("source") or "")[:100],
                    "medium": str(item.get("medium") or "")[:100],
                    "sessions": int(item.get("sessions") or 0),
                    "orders": int(item.get("orders") or 0),
                    "payments": int(item.get("payments") or 0),
                }
                for item in (marketing.get("sources") or [])[:10]
                if isinstance(item, dict)
            ],
        },
    }


def _operations_instructions() -> str:
    return (
        "你是魔丸娛樂的內部營運分析助理，只能分析使用者提供的白名單聚合資料。"
        "使用繁體中文。不要假裝你查過資料庫、不要產生或執行 SQL、不要要求額外的顧客個資。"
        "不得修改訂單、付款、退款、錢包、薪資、派單或任何後台資料。"
        "請把『資料直接支持的事實』與『合理推測』分清楚；樣本很小時必須明講。"
        "不要把相關性寫成因果。若資料不足以回答問題，直接說缺少哪一類聚合資料。"
        "優先指出：營收/留存、取消率、商品變化、客服 SLA、異常、行銷漏斗、接單時段。"
        "回答以 3~6 個重點為主，最後給 1~3 個可由人員決定是否採取的檢查方向。"
        "這些建議只能是營運檢查或觀察方向，不可自行執行任何動作。"
    )


def _extract_response_text(data: Any) -> str:
    if not isinstance(data, dict):
        return ""

    direct = str(data.get("output_text") or "").strip()
    if direct:
        return direct

    chunks: list[str] = []
    for item in data.get("output") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("type") or "") != "message":
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if str(content.get("type") or "") != "output_text":
                continue
            value = str(content.get("text") or "").strip()
            if value:
                chunks.append(value)

    return "\n".join(chunks).strip()


def _usage(data: Any) -> tuple[int, int, int]:
    if not isinstance(data, dict):
        return 0, 0, 0
    usage = data.get("usage")
    if not isinstance(usage, dict):
        return 0, 0, 0

    def _int(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    input_tokens = _int(usage.get("input_tokens"))
    output_tokens = _int(usage.get("output_tokens"))
    total_tokens = _int(usage.get("total_tokens"))
    if not total_tokens:
        total_tokens = input_tokens + output_tokens
    return input_tokens, output_tokens, total_tokens


def fallback_operations_summary(
    snapshot: dict[str, Any],
) -> str:
    report = snapshot.get("financial_orders") or {}
    anomalies = snapshot.get("anomalies") or {}
    support = snapshot.get("customer_service") or {}

    lines = [
        "目前外部 AI 沒有成功產生分析，先顯示白名單指標摘要：",
        (
            f"• {report.get('period_label') or '本期'}營收 "
            f"{int(report.get('revenue') or 0):,}，"
            f"訂單 {int(report.get('order_count') or 0)} 筆，"
            f"留存 {int(report.get('retained') or 0):,}"
            f"（{float(report.get('retained_rate') or 0):.1f}%）。"
        ),
        (
            f"• 建單 {int(report.get('created_orders') or 0)} 筆，"
            f"取消 {int(report.get('cancelled_orders') or 0)} 筆，"
            f"取消率 {float(report.get('cancellation_rate') or 0):.1f}%。"
        ),
        (
            f"• 異常中心目前 {int(anomalies.get('issue_count') or 0)} 筆，"
            f"Critical {int(anomalies.get('critical_count') or 0)} 筆。"
        ),
    ]

    if support.get("within_5_rate") is not None:
        lines.append(
            f"• 客服 5 分鐘內接手率 {float(support['within_5_rate']):.1f}%。"
        )

    lines.append("可稍後再按一次 AI 分析；系統不會因 AI 失敗而影響其他後台功能。")
    return "\n".join(lines)


async def generate_operations_analysis(
    *,
    question: str,
    snapshot: dict[str, Any],
) -> tuple[str, bool]:
    clean_question = str(question or "").strip()[:1200]
    if not clean_question:
        clean_question = "請分析目前營運狀況，指出值得注意的變化與下一步檢查方向。"

    api_url = str(config.AI_SUPPORT_API_URL or "").strip()
    api_key = str(config.AI_SUPPORT_API_KEY or "").strip()
    model = str(
        getattr(config, "AI_OPERATIONS_MODEL", "")
        or config.AI_SUPPORT_MODEL
        or ""
    ).strip()

    if not api_url or not api_key or not model:
        return fallback_operations_summary(snapshot), False

    payload = {
        "model": model,
        "instructions": _operations_instructions(),
        "input": [
            {
                "role": "user",
                "content": (
                    "問題：\n"
                    + clean_question
                    + "\n\n以下是系統事先計算好的聚合資料。"
                    "只能根據這些資料回答：\n"
                    + json.dumps(
                        snapshot,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                ),
            }
        ],
        "max_output_tokens": 900,
        "store": False,
    }

    timeout = aiohttp.ClientTimeout(
        total=int(
            getattr(config, "AI_OPERATIONS_TIMEOUT_SECONDS", 20)
            or 20
        )
    )

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                api_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                data=json.dumps(payload, ensure_ascii=False),
            ) as response:
                data = await response.json(content_type=None)

                if response.status < 200 or response.status >= 300:
                    error = data.get("error") if isinstance(data, dict) else None
                    code = (
                        str(error.get("code") or error.get("type") or "")[:80]
                        if isinstance(error, dict)
                        else "unknown"
                    )
                    print(
                        "[operations-ai] external response failed "
                        f"model={model} status={response.status} code={code}",
                        flush=True,
                    )
                    return fallback_operations_summary(snapshot), False

        reply = _extract_response_text(data)
        if not reply:
            print(
                f"[operations-ai] external response empty model={model}",
                flush=True,
            )
            return fallback_operations_summary(snapshot), False

        input_tokens, output_tokens, total_tokens = _usage(data)
        print(
            "[operations-ai] external response ok "
            f"model={model} input_tokens={input_tokens} "
            f"output_tokens={output_tokens} total_tokens={total_tokens}",
            flush=True,
        )
        return reply[:7000], True

    except Exception as exc:
        print(
            "[operations-ai] external request exception "
            f"model={model} error={type(exc).__name__}",
            flush=True,
        )
        return fallback_operations_summary(snapshot), False
