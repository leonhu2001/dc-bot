from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "views" / "review.py"
SERVICE = ROOT / "services" / "worker_tips.py"
VIEW = ROOT / "views" / "worker_tips.py"

PERSISTENCE_NAMES = [
    "_worker_tip_row",
    "create_worker_tip",
    "set_worker_tip_confirmation_message",
    "mark_worker_tip_paid",
    "mark_worker_tip_cancelled",
    "has_pending_worker_tips",
    "get_pending_worker_tip_confirmations",
]
VIEW_NAMES = [
    "_log_worker_tip",
    "_notify_worker_tip_paid",
    "_worker_tip_preview_text",
    "WorkerTipAmountEditModal",
    "WorkerTipAmountModal",
    "WorkerTipMemberSelect",
    "WorkerTipMemberMenuView",
    "WorkerTipPaymentMethodSelect",
    "WorkerTipPaymentMethodView",
    "WorkerTipPaymentConfirmView",
]
TARGET_NAMES = set(PERSISTENCE_NAMES + VIEW_NAMES)

source = PARENT.read_text(encoding="utf-8")
tree = ast.parse(source)
lines = source.splitlines(keepends=True)
nodes = {
    node.name: node
    for node in tree.body
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    and node.name in TARGET_NAMES
}
missing = TARGET_NAMES - nodes.keys()
if missing:
    raise RuntimeError(f"missing worker-tip definitions: {sorted(missing)}")


def block(name: str) -> str:
    node = nodes[name]
    return "".join(lines[node.lineno - 1 : node.end_lineno]).rstrip() + "\n"


service_blocks = []
for name in PERSISTENCE_NAMES:
    text = block(name)
    text = text.replace("ensure_review_tables()", "ensure_worker_tip_tables()")
    if name == "_worker_tip_row":
        text = text.replace("def _worker_tip_row(", "def get_worker_tip(", 1)
    service_blocks.append(text)

service_header = '''from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path


def _db_path() -> Path:
    return Path(__file__).resolve().parents[1] / "web_dashboard.db"


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(_db_path(), timeout=15)
    conn.row_factory = sqlite3.Row
    return conn


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def ensure_worker_tip_tables() -> None:
    conn = _connect()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS worker_tips (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                order_id INTEGER,
                ticket_channel_id TEXT NOT NULL,
                dispatch_message_id TEXT,
                receipt_id TEXT,
                customer_discord_id TEXT NOT NULL,
                customer_display_name TEXT,
                worker_discord_id TEXT NOT NULL,
                worker_display_name TEXT,
                amount INTEGER NOT NULL,
                payment_method TEXT NOT NULL,
                payment_status TEXT NOT NULL DEFAULT 'pending',
                payout_status TEXT NOT NULL DEFAULT 'unpaid',
                wallet_transaction_id INTEGER,
                confirmation_message_id TEXT,
                confirmed_by_discord_id TEXT,
                confirmed_by_display_name TEXT,
                paid_at TEXT,
                payout_paid_at TEXT,
                cancelled_at TEXT,
                note TEXT,
                source TEXT NOT NULL DEFAULT 'discord',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_worker_tips_order
                ON worker_tips(order_id);
            CREATE INDEX IF NOT EXISTS idx_worker_tips_ticket
                ON worker_tips(ticket_channel_id);
            CREATE INDEX IF NOT EXISTS idx_worker_tips_worker
                ON worker_tips(worker_discord_id);
            CREATE INDEX IF NOT EXISTS idx_worker_tips_payment
                ON worker_tips(payment_status, payout_status);
            """
        )
        conn.commit()
    finally:
        conn.close()


'''
SERVICE.write_text(service_header + "\n\n".join(service_blocks), encoding="utf-8")

view_blocks = []
for name in VIEW_NAMES:
    text = block(name)
    text = text.replace("_WORKER_TIP_WALLET_HANDLER", "_WALLET_HANDLER")
    text = text.replace("_WORKER_TIP_LOG_HANDLER", "_LOG_HANDLER")
    text = text.replace("get_review_targets", "_review_targets")
    text = text.replace("refresh_post_close_panel", "_refresh_post_close")
    text = text.replace("_worker_tip_row", "get_worker_tip")
    view_blocks.append(text)

view_header = '''from __future__ import annotations

from collections.abc import Awaitable, Callable

import discord

from core.permissions import is_customer_staff
from services.worker_tips import (
    create_worker_tip,
    get_worker_tip,
    mark_worker_tip_cancelled,
    mark_worker_tip_paid,
    set_worker_tip_confirmation_message,
)


_WALLET_HANDLER = None
_LOG_HANDLER = None
_REVIEW_TARGET_GETTER: Callable | None = None
_REFRESH_POST_CLOSE_HANDLER: Callable[..., Awaitable] | None = None

WORKER_TIP_POLICY_TEXT = (
    "🍗 **加雞腿說明**\\n"
    "• 雞腿金額 100% 給你指定的打手／陪玩。\\n"
    "• 雞腿採獨立帳務，不併入原訂單金額。\\n"
    "• 雞腿不計原單抽成，也不影響原訂單分潤。\\n"
    "• 雞腿不列入 VIP 累積消費，也不增加會員點數。\\n"
    "• 使用「我的錢包」會立即扣款；街口／轉帳送出後會進網站審核，請在票口貼付款截圖，客服確認後才會入帳。"
)


def configure_worker_tip_views(
    *,
    wallet_handler=None,
    log_handler=None,
    review_target_getter: Callable,
    refresh_post_close_handler: Callable[..., Awaitable],
) -> None:
    global _WALLET_HANDLER, _LOG_HANDLER
    global _REVIEW_TARGET_GETTER, _REFRESH_POST_CLOSE_HANDLER
    _WALLET_HANDLER = wallet_handler
    _LOG_HANDLER = log_handler
    _REVIEW_TARGET_GETTER = review_target_getter
    _REFRESH_POST_CLOSE_HANDLER = refresh_post_close_handler


def _review_targets(ticket_channel_id, dispatch_message_id=None):
    if _REVIEW_TARGET_GETTER is None:
        raise RuntimeError("worker-tip views are not configured: review target getter missing")
    return _REVIEW_TARGET_GETTER(ticket_channel_id, dispatch_message_id)


async def _refresh_post_close(channel, customer_id: int):
    if _REFRESH_POST_CLOSE_HANDLER is None:
        raise RuntimeError("worker-tip views are not configured: post-close refresh missing")
    return await _REFRESH_POST_CLOSE_HANDLER(channel, customer_id)


'''
VIEW.write_text(view_header + "\n\n".join(view_blocks), encoding="utf-8")

# Remove extracted definitions from review.py.
for node in sorted(nodes.values(), key=lambda item: item.lineno, reverse=True):
    del lines[node.lineno - 1 : node.end_lineno]
parent = "".join(lines)

# Remove old callback globals + policy text; the new view module owns them.
parent = parent.replace("_WORKER_TIP_WALLET_HANDLER = None\n_WORKER_TIP_LOG_HANDLER = None\n", "")
policy_pattern = re.compile(
    r"WORKER_TIP_POLICY_TEXT = \(\n(?:.*\n)*?\)\n\n",
    re.MULTILINE,
)
parent, count = policy_pattern.subn("", parent, count=1)
if count != 1:
    raise RuntimeError("worker-tip policy block not removed exactly once")

# Remove worker_tips schema ownership from ensure_review_tables.
ddl_pattern = re.compile(
    r"\n\s*CREATE TABLE IF NOT EXISTS worker_tips \(.*?"
    r"CREATE INDEX IF NOT EXISTS idx_worker_tips_payment\n"
    r"\s*ON worker_tips\(payment_status, payout_status\);",
    re.DOTALL,
)
parent, count = ddl_pattern.subn("", parent, count=1)
if count != 1:
    raise RuntimeError("worker_tips DDL block not removed exactly once")

import_anchor = "from services.ticket_archives import save_ticket_archive\n"
imports = '''from services.worker_tips import (
    ensure_worker_tip_tables,
    get_pending_worker_tip_confirmations,
    has_pending_worker_tips,
)
from views.worker_tips import (
    WORKER_TIP_POLICY_TEXT,
    WorkerTipMemberMenuView,
    WorkerTipPaymentConfirmView,
    configure_worker_tip_views,
)
'''
if import_anchor not in parent:
    raise RuntimeError("review import anchor missing")
parent = parent.replace(import_anchor, import_anchor + imports, 1)

old_config = '''def configure_worker_tip_callbacks(*, wallet_handler=None, log_handler=None) -> None:
    global _WORKER_TIP_WALLET_HANDLER, _WORKER_TIP_LOG_HANDLER
    _WORKER_TIP_WALLET_HANDLER = wallet_handler
    _WORKER_TIP_LOG_HANDLER = log_handler
    ensure_review_tables()
'''
new_config = '''def configure_worker_tip_callbacks(*, wallet_handler=None, log_handler=None) -> None:
    ensure_worker_tip_tables()
    configure_worker_tip_views(
        wallet_handler=wallet_handler,
        log_handler=log_handler,
        review_target_getter=get_review_targets,
        refresh_post_close_handler=refresh_post_close_panel,
    )
'''
if old_config not in parent:
    raise RuntimeError("worker-tip callback config block changed")
parent = parent.replace(old_config, new_config, 1)

old_review_config = '''def configure_review_views(*, review_channel_id: int) -> None:
    global _REVIEW_CHANNEL_ID
    _REVIEW_CHANNEL_ID = review_channel_id
    ensure_review_tables()
'''
new_review_config = '''def configure_review_views(*, review_channel_id: int) -> None:
    global _REVIEW_CHANNEL_ID
    _REVIEW_CHANNEL_ID = review_channel_id
    ensure_review_tables()
    ensure_worker_tip_tables()
'''
if old_review_config not in parent:
    raise RuntimeError("review view config block changed")
parent = parent.replace(old_review_config, new_review_config, 1)
PARENT.write_text(parent, encoding="utf-8")

# Add focused architecture tests.
test_path = ROOT / "tests" / "test_worker_tip_extraction.py"
test_path.write_text(
    '''from pathlib import Path


def test_worker_tip_persistence_has_single_canonical_owner():
    review = Path("views/review.py").read_text(encoding="utf-8")
    service = Path("services/worker_tips.py").read_text(encoding="utf-8")

    assert "CREATE TABLE IF NOT EXISTS worker_tips" not in review
    assert "CREATE TABLE IF NOT EXISTS worker_tips" in service
    assert "def create_worker_tip" not in review
    assert "def create_worker_tip" in service
    assert "def mark_worker_tip_paid" not in review
    assert "def mark_worker_tip_paid" in service


def test_worker_tip_discord_ui_is_not_implemented_in_review_module():
    review = Path("views/review.py").read_text(encoding="utf-8")
    tip_views = Path("views/worker_tips.py").read_text(encoding="utf-8")

    assert "class WorkerTipPaymentMethodSelect" not in review
    assert "class WorkerTipPaymentConfirmView" not in review
    assert "class WorkerTipPaymentMethodSelect" in tip_views
    assert "class WorkerTipPaymentConfirmView" in tip_views
    assert "def configure_worker_tip_views" in tip_views
    assert "from views.review import" not in tip_views


def test_review_composes_worker_tips_through_explicit_callbacks():
    review = Path("views/review.py").read_text(encoding="utf-8")
    assert "configure_worker_tip_views(" in review
    assert "review_target_getter=get_review_targets" in review
    assert "refresh_post_close_handler=refresh_post_close_panel" in review
''',
    encoding="utf-8",
)

budget_path = ROOT / "tests" / "test_architecture_growth_budget.py"
budget = budget_path.read_text(encoding="utf-8")
review_size = PARENT.stat().st_size
service_size = SERVICE.stat().st_size
view_size = VIEW.stat().st_size
round_up = lambda size: ((size + 1999) // 1000) * 1000
review_limit = round_up(review_size)
service_limit = round_up(service_size)
view_limit = round_up(view_size)
budget = budget.replace(
    '    "views/review.py": 95_500,\n',
    f'    "views/review.py": {review_limit:_},\n'
    f'    "services/worker_tips.py": {service_limit:_},\n'
    f'    "views/worker_tips.py": {view_limit:_},\n',
    1,
)
budget_path.write_text(budget, encoding="utf-8")

print(f"review.py bytes={review_size} ceiling={review_limit}")
print(f"worker_tips service bytes={service_size} ceiling={service_limit}")
print(f"worker_tips views bytes={view_size} ceiling={view_limit}")
