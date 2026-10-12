from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVICE = ROOT / "services" / "worker_tips.py"
REVIEW = ROOT / "views" / "review.py"

service = SERVICE.read_text(encoding="utf-8")
service = service.replace(
    "import sqlite3\nfrom datetime import datetime\nfrom pathlib import Path\n",
    "import sqlite3\nfrom collections.abc import Callable\nfrom datetime import datetime\nfrom pathlib import Path\n",
    1,
)
old_db = '''def _db_path() -> Path:
    return Path(__file__).resolve().parents[1] / "web_dashboard.db"


def _connect() -> sqlite3.Connection:
'''
new_db = '''_DB_PATH_PROVIDER: Callable[[], str | Path] | None = None


def configure_worker_tip_store(*, db_path_provider: Callable[[], str | Path]) -> None:
    global _DB_PATH_PROVIDER
    _DB_PATH_PROVIDER = db_path_provider


def _db_path() -> Path:
    if _DB_PATH_PROVIDER is not None:
        return Path(_DB_PATH_PROVIDER())
    return Path(__file__).resolve().parents[1] / "web_dashboard.db"


def _connect() -> sqlite3.Connection:
'''
if old_db not in service:
    raise RuntimeError("worker-tip service db-path anchor changed")
SERVICE.write_text(service.replace(old_db, new_db, 1), encoding="utf-8")

review = REVIEW.read_text(encoding="utf-8")
review = review.replace(
    "from services.worker_tips import (\n    ensure_worker_tip_tables,\n",
    "from services.worker_tips import (\n    configure_worker_tip_store,\n    ensure_worker_tip_tables,\n",
    1,
)
old_ensure = '''def ensure_review_tables() -> None:
    conn = _connect()
'''
new_ensure = '''def ensure_review_tables() -> None:
    # Review/favorite/tip tables are one operational schema group. Keep the
    # historical one-call ensure contract while worker_tips owns its own DDL.
    configure_worker_tip_store(db_path_provider=_web_db_path)
    ensure_worker_tip_tables()
    conn = _connect()
'''
if old_ensure not in review:
    raise RuntimeError("review table ensure anchor changed")
review = review.replace(old_ensure, new_ensure, 1)
review = review.replace(
    '''def configure_review_views(*, review_channel_id: int) -> None:
    global _REVIEW_CHANNEL_ID
    _REVIEW_CHANNEL_ID = review_channel_id
    ensure_review_tables()
    ensure_worker_tip_tables()
''',
    '''def configure_review_views(*, review_channel_id: int) -> None:
    global _REVIEW_CHANNEL_ID
    _REVIEW_CHANNEL_ID = review_channel_id
    ensure_review_tables()
''',
    1,
)
REVIEW.write_text(review, encoding="utf-8")
