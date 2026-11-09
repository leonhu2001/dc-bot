#!/usr/bin/env python3
"""One-time, read-only-DB backfill of already paid staff-profile tip receipts.

Preview by default. --apply POSTs only the missing Discord receipt and persistent
close button; it never approves payments, touches wallet balances, or updates DB.
Run from /opt/dc-bot while the main bot remains running.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path.cwd()
API = "https://discord.com/api/v10"
CLOSE_CUSTOM_ID = "worker_tip_profile_paid_close"


def api(method: str, path: str, token: str, payload: dict | None = None):
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    for attempt in range(3):
        req = urllib.request.Request(
            API + path, data=body, method=method,
            headers={
                "Authorization": "Bot " + token,
                "Content-Type": "application/json",
                "User-Agent": "MWProfileTipReceiptRepair/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                response_body = response.read()
                return json.loads(response_body) if response_body else {}
        except urllib.error.HTTPError as exc:
            if exc.code == 429 and attempt < 2:
                try:
                    retry = float(json.loads(exc.read()).get("retry_after", 1))
                except (ValueError, TypeError):
                    retry = 1
                time.sleep(min(max(retry, 0.5), 10))
                continue
            raise RuntimeError(f"Discord API {method} {path.split('?')[0]}: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError) as exc:
            raise RuntimeError(f"Discord API {method} {path.split('?')[0]}: connection failed") from exc
    raise RuntimeError("Discord API rate limit retry exceeded")


def connect_db():
    path = ROOT / "web_dashboard.db"
    if not path.is_file():
        raise RuntimeError(f"Database not found: {path}")
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def verified_tips(db, selected_channel: str | None):
    where = "AND ticket_channel_id=?" if selected_channel else ""
    args = (selected_channel,) if selected_channel else ()
    sql = (
        "SELECT * FROM worker_tips WHERE order_id IS NULL "
        "AND payment_status='paid' AND paid_at IS NOT NULL "
        "AND CAST(amount AS INTEGER)>0 AND ticket_channel_id <> '' "
        + where + " ORDER BY id"
    )
    tips = [dict(row) for row in db.execute(sql, args)]
    grouped = defaultdict(list)
    for tip in tips:
        grouped[str(tip["ticket_channel_id"])].append(tip)
    for channel_id, rows in grouped.items():
        if len(rows) != 1:
            yield channel_id, None, "同票口有多筆已付款雞腿，為避免合併或重複顯示，需人工確認"
            continue
        row = rows[0]
        cid = str(row["customer_discord_id"] or "")
        wid = str(row["worker_discord_id"] or "")
        if not all(x.isdigit() for x in (channel_id, cid, wid)):
            yield channel_id, None, "票口或用戶 ID 無效"
            continue
        method = str(row["payment_method"] or "")
        if method == "我的錢包":
            if not row.get("wallet_transaction_id"):
                yield channel_id, None, "錢包已付款但缺少交易 ID，需人工確認"
                continue
        elif method in ("街口", "轉帳"):
            reviews = [
                dict(r) for r in db.execute(
                    "SELECT * FROM payment_reviews "
                    "WHERE source_type='worker_tip' AND source_id=? "
                    "AND status='applied' ORDER BY id DESC",
                    (str(row["id"]),),
                )
            ]
            if not any(
                str(r["ticket_channel_id"] or "") == channel_id
                and str(r["customer_discord_id"] or "") == cid
                and str(r["target_discord_id"] or "") == wid
                and int(r["amount"] or 0) == int(row["amount"])
                and str(r["payment_method"] or "") == method
                for r in reviews
            ):
                yield channel_id, None, "未找到內容一致且已套用的付款審核"
                continue
        else:
            yield channel_id, None, "不支援的付款方式"
            continue
        yield channel_id, row, ""


def prior_receipt(messages: list[dict], bot_id: str, row: dict) -> bool:
    marker = f"TIP-{row['id']}"
    for message in messages:
        if str((message.get("author") or {}).get("id", "")) != bot_id:
            continue
        content = str(message.get("content") or "")
        for component in message.get("components") or []:
            for button in component.get("components") or []:
                if button.get("custom_id") == CLOSE_CUSTOM_ID:
                    return True
        if "✅ **雞腿付款完成**" in content:
            # Older receipts did not include a TIP identifier.
            if marker in content or (
                f"<@{row['customer_discord_id']}>" in content
                and f"<@{row['worker_discord_id']}>" in content
                and f"{int(row['amount']):,}T 已付款" in content
                and f"付款方式：{row['payment_method']}" in content
            ):
                return True
    return False


def ticket_messages(channel_id: str, token: str) -> tuple[list[dict], bool]:
    found = []
    before = None
    for _ in range(5):  # Fail closed on extremely long tickets.
        suffix = f"?limit=100&before={before}" if before else "?limit=100"
        batch = api("GET", f"/channels/{channel_id}/messages{suffix}", token)
        found.extend(batch)
        if len(batch) < 100:
            return found, True
        before = str(batch[-1]["id"])
    return found, False


def receipt_payload(row: dict) -> dict:
    amount = int(row["amount"])
    content = (
        "✅ **雞腿付款完成**\n"
        f"老闆：<@{row['customer_discord_id']}>\n"
        f"指定陪玩：<@{row['worker_discord_id']}>\n"
        f"🍗 **雞腿**｜{amount:,}T 已付款\n"
        f"🍗 **雞腿總覽**｜已付款 {amount:,}T\n"
        f"付款方式：{row['payment_method']}\n"
        "此筆雞腿 100% 歸指定陪玩，已列入薪資明細。\n"
        f"雞腿紀錄：TIP-{row['id']}\n"
        "確認紀錄無誤後，可按下方按鈕關閉票口。"
    )
    return {
        "content": content,
        "allowed_mentions": {"parse": []},  # Backfill must not ping again.
        "components": [{
            "type": 1, "components": [{
                "type": 2, "style": 4,
                "label": "🔒 關閉票口",
                "custom_id": CLOSE_CUSTOM_ID,
            }],
        }],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Send missing panels")
    parser.add_argument("--channel", help="Restrict to one Discord channel ID")
    parser.add_argument("--max-posts", type=int, default=10)
    args = parser.parse_args()
    if args.channel and not args.channel.isdigit():
        parser.error("--channel must be a numeric Discord channel ID")
    if not 1 <= args.max_posts <= 100:
        parser.error("--max-posts must be 1..100")
    load_dotenv(ROOT / ".env")
    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        raise RuntimeError("No DISCORD_TOKEN in process environment or /opt/dc-bot/.env")

    bot_id = str(api("GET", "/users/@me", token)["id"])
    db = connect_db()
    ready = []
    skipped = []
    try:
        for channel_id, tip, reason in verified_tips(db, args.channel):
            if reason:
                skipped.append((channel_id, reason))
                continue
            try:
                channel = api("GET", f"/channels/{channel_id}", token)
                expected_topic = (
                    f"profile_tip_customer_id={tip['customer_discord_id']};"
                    f"profile_tip_staff_id={tip['worker_discord_id']}"
                )
                if channel.get("type") != 0 or channel.get("topic") != expected_topic:
                    skipped.append((channel_id, "票口類型、老闆或陪玩身分不一致"))
                    continue
                messages, complete = ticket_messages(channel_id, token)
                if prior_receipt(messages, bot_id, tip):
                    skipped.append((channel_id, "已有付款完成摘要／關閉按鈕"))
                    continue
                if not complete:
                    skipped.append((channel_id, "訊息歷史超過 500 則，無法證明未曾補發"))
                    continue
                ready.append((channel_id, tip))
            except RuntimeError as exc:
                skipped.append((channel_id, str(exc)))
    finally:
        db.close()

    print("MODE:", "APPLY" if args.apply else "PREVIEW (READ ONLY)")
    for channel_id, tip in ready:
        print(f"READY: channel={channel_id} TIP-{tip['id']} amount={tip['amount']}T")
    for channel_id, reason in skipped:
        print(f"SKIP: channel={channel_id} {reason}")
    print(f"ready_count={len(ready)} skipped_count={len(skipped)}")

    if not args.apply:
        return 0
    if len(ready) > args.max_posts:
        print("BLOCKED: exceeds --max-posts; no messages sent", file=sys.stderr)
        return 2

    sent = 0
    for channel_id, tip in ready:
        try:
            # Recheck immediately before posting, to prevent a duplicate from a
            # concurrent approval or another repair operator.
            messages, complete = ticket_messages(channel_id, token)
            if not complete or prior_receipt(messages, bot_id, tip):
                print(f"SKIP: channel={channel_id} changed before send")
                continue
            result = api("POST", f"/channels/{channel_id}/messages", token, receipt_payload(tip))
            print(f"SENT: channel={channel_id} TIP-{tip['id']} message={result['id']}")
            sent += 1
        except RuntimeError as exc:
            print(f"ERROR: channel={channel_id} {exc}; check channel before retrying")
    print(f"sent_count={sent}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (RuntimeError, sqlite3.Error, KeyError, ValueError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        raise SystemExit(1)
