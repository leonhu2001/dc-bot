from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"

KNOWLEDGE_ACTIVE = "active"
KNOWLEDGE_ARCHIVED = "archived"

_SCHEMA_READY: set[str] = set()


def _db_path(db_file: str | Path | None = None) -> Path:
    if db_file is not None:
        return Path(db_file)
    return Path(__file__).resolve().parents[1] / "web_dashboard.db"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def ensure_ai_support_knowledge_tables(
    db_file: str | Path | None = None,
) -> None:
    path = _db_path(db_file)
    key = str(path.resolve())

    if key in _SCHEMA_READY:
        return

    with sqlite3.connect(path, timeout=15) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS ai_support_learning_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                question_message_id INTEGER NOT NULL UNIQUE,
                answer_message_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                staff_discord_id TEXT,
                staff_display_name TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                knowledge_id INTEGER,
                reviewed_by_discord_id TEXT,
                reviewed_by_display_name TEXT,
                reviewed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_ai_learning_candidates_status
                ON ai_support_learning_candidates(status, updated_at);

            CREATE TABLE IF NOT EXISTS ai_support_knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                source_type TEXT NOT NULL DEFAULT 'approved_candidate',
                source_session_id INTEGER,
                source_candidate_id INTEGER,
                created_by_discord_id TEXT,
                created_by_display_name TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                archived_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_ai_support_knowledge_status
                ON ai_support_knowledge(status, updated_at);
            """
        )
        conn.commit()

    _SCHEMA_READY.add(key)


def _clean_candidate_text(value: str, *, limit: int = 2400) -> str:
    lines: list[str] = []

    for line in str(value or "").splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("[附件]"):
            continue
        lines.append(stripped)

    return "\n".join(lines).strip()[:limit]


def capture_learning_candidate(
    *,
    session_id: int,
    answer_message_id: int,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    """
    Capture the latest customer question + staff reply for manager review.

    Repeated staff messages before the next customer message are appended to the
    same pending candidate. Nothing becomes AI knowledge automatically.
    """
    ensure_ai_support_knowledge_tables(db_file)
    path = _db_path(db_file)

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row

        answer_row = conn.execute(
            """
            SELECT *
            FROM web_support_messages
            WHERE id = ?
              AND session_id = ?
              AND sender_type = 'staff'
            LIMIT 1
            """,
            (int(answer_message_id), int(session_id)),
        ).fetchone()

        if answer_row is None:
            return None

        question_row = conn.execute(
            """
            SELECT *
            FROM web_support_messages
            WHERE session_id = ?
              AND sender_type = 'customer'
              AND id < ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (int(session_id), int(answer_message_id)),
        ).fetchone()

        if question_row is None:
            return None

        question = _clean_candidate_text(str(question_row["body"] or ""))
        answer = _clean_candidate_text(str(answer_row["body"] or ""))

        if len(question) < 2 or len(answer) < 2:
            return None

        now = _now()
        question_message_id = int(question_row["id"])

        existing = conn.execute(
            """
            SELECT *
            FROM ai_support_learning_candidates
            WHERE question_message_id = ?
            LIMIT 1
            """,
            (question_message_id,),
        ).fetchone()

        if existing is not None:
            if str(existing["status"] or "") != STATUS_PENDING:
                return dict(existing)

            old_answer = str(existing["answer"] or "").strip()
            combined = old_answer
            if answer and answer not in old_answer:
                combined = (old_answer + "\n" + answer).strip()[:4000]

            conn.execute(
                """
                UPDATE ai_support_learning_candidates
                SET answer = ?,
                    answer_message_id = ?,
                    staff_discord_id = ?,
                    staff_display_name = ?,
                    updated_at = ?
                WHERE id = ?
                  AND status = 'pending'
                """,
                (
                    combined,
                    int(answer_message_id),
                    str(answer_row["sender_discord_id"] or "").strip() or None,
                    str(answer_row["sender_display_name"] or "").strip() or None,
                    now,
                    int(existing["id"]),
                ),
            )
            candidate_id = int(existing["id"])
        else:
            cur = conn.execute(
                """
                INSERT INTO ai_support_learning_candidates (
                    session_id,
                    question_message_id,
                    answer_message_id,
                    question,
                    answer,
                    staff_discord_id,
                    staff_display_name,
                    status,
                    created_at,
                    updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    int(session_id),
                    question_message_id,
                    int(answer_message_id),
                    question,
                    answer,
                    str(answer_row["sender_discord_id"] or "").strip() or None,
                    str(answer_row["sender_display_name"] or "").strip() or None,
                    now,
                    now,
                ),
            )
            candidate_id = int(cur.lastrowid)

        conn.commit()

        return _row(
            conn.execute(
                """
                SELECT *
                FROM ai_support_learning_candidates
                WHERE id = ?
                """,
                (candidate_id,),
            ).fetchone()
        )


def get_learning_candidate(
    candidate_id: int,
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_ai_support_knowledge_tables(db_file)

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        return _row(
            conn.execute(
                """
                SELECT *
                FROM ai_support_learning_candidates
                WHERE id = ?
                LIMIT 1
                """,
                (int(candidate_id),),
            ).fetchone()
        )


def list_learning_candidates(
    *,
    status: str = STATUS_PENDING,
    limit: int = 100,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_ai_support_knowledge_tables(db_file)
    safe_limit = max(1, min(int(limit or 100), 500))

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM ai_support_learning_candidates
            WHERE status = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (str(status), safe_limit),
        ).fetchall()
        return [dict(row) for row in rows]


def list_knowledge(
    *,
    status: str = KNOWLEDGE_ACTIVE,
    limit: int = 300,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    ensure_ai_support_knowledge_tables(db_file)
    safe_limit = max(1, min(int(limit or 300), 1000))

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            """
            SELECT *
            FROM ai_support_knowledge
            WHERE status = ?
            ORDER BY updated_at DESC, id DESC
            LIMIT ?
            """,
            (str(status), safe_limit),
        ).fetchall()
        return [dict(row) for row in rows]


def approve_candidate(
    candidate_id: int,
    *,
    question: str,
    answer: str,
    reviewed_by_discord_id: str,
    reviewed_by_display_name: str,
    db_file: str | Path | None = None,
) -> dict[str, Any] | None:
    ensure_ai_support_knowledge_tables(db_file)
    question_text = _clean_candidate_text(question, limit=2400)
    answer_text = _clean_candidate_text(answer, limit=4000)

    if not question_text or not answer_text:
        raise ValueError("question and answer are required")

    path = _db_path(db_file)
    now = _now()

    with sqlite3.connect(path, timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        candidate = conn.execute(
            """
            SELECT *
            FROM ai_support_learning_candidates
            WHERE id = ?
              AND status = 'pending'
            LIMIT 1
            """,
            (int(candidate_id),),
        ).fetchone()

        if candidate is None:
            return None

        cur = conn.execute(
            """
            INSERT INTO ai_support_knowledge (
                question,
                answer,
                status,
                source_type,
                source_session_id,
                source_candidate_id,
                created_by_discord_id,
                created_by_display_name,
                created_at,
                updated_at
            )
            VALUES (?, ?, 'active', 'approved_candidate', ?, ?, ?, ?, ?, ?)
            """,
            (
                question_text,
                answer_text,
                int(candidate["session_id"]),
                int(candidate_id),
                str(reviewed_by_discord_id),
                str(reviewed_by_display_name)[:200],
                now,
                now,
            ),
        )
        knowledge_id = int(cur.lastrowid)

        conn.execute(
            """
            UPDATE ai_support_learning_candidates
            SET question = ?,
                answer = ?,
                status = 'approved',
                knowledge_id = ?,
                reviewed_by_discord_id = ?,
                reviewed_by_display_name = ?,
                reviewed_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                question_text,
                answer_text,
                knowledge_id,
                str(reviewed_by_discord_id),
                str(reviewed_by_display_name)[:200],
                now,
                now,
                int(candidate_id),
            ),
        )

        conn.commit()

        return _row(
            conn.execute(
                "SELECT * FROM ai_support_knowledge WHERE id = ?",
                (knowledge_id,),
            ).fetchone()
        )


def reject_candidate(
    candidate_id: int,
    *,
    reviewed_by_discord_id: str,
    reviewed_by_display_name: str,
    db_file: str | Path | None = None,
) -> bool:
    ensure_ai_support_knowledge_tables(db_file)
    now = _now()

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        cur = conn.execute(
            """
            UPDATE ai_support_learning_candidates
            SET status = 'rejected',
                reviewed_by_discord_id = ?,
                reviewed_by_display_name = ?,
                reviewed_at = ?,
                updated_at = ?
            WHERE id = ?
              AND status = 'pending'
            """,
            (
                str(reviewed_by_discord_id),
                str(reviewed_by_display_name)[:200],
                now,
                now,
                int(candidate_id),
            ),
        )
        conn.commit()
        return cur.rowcount > 0


def create_manual_knowledge(
    *,
    question: str,
    answer: str,
    created_by_discord_id: str,
    created_by_display_name: str,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_ai_support_knowledge_tables(db_file)
    question_text = _clean_candidate_text(question, limit=2400)
    answer_text = _clean_candidate_text(answer, limit=4000)

    if not question_text or not answer_text:
        raise ValueError("question and answer are required")

    now = _now()

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.execute(
            """
            INSERT INTO ai_support_knowledge (
                question,
                answer,
                status,
                source_type,
                created_by_discord_id,
                created_by_display_name,
                created_at,
                updated_at
            )
            VALUES (?, ?, 'active', 'manual', ?, ?, ?, ?)
            """,
            (
                question_text,
                answer_text,
                str(created_by_discord_id),
                str(created_by_display_name)[:200],
                now,
                now,
            ),
        )
        knowledge_id = int(cur.lastrowid)
        conn.commit()

        return _row(
            conn.execute(
                "SELECT * FROM ai_support_knowledge WHERE id = ?",
                (knowledge_id,),
            ).fetchone()
        ) or {}


def archive_knowledge(
    knowledge_id: int,
    *,
    db_file: str | Path | None = None,
) -> bool:
    ensure_ai_support_knowledge_tables(db_file)
    now = _now()

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        cur = conn.execute(
            """
            UPDATE ai_support_knowledge
            SET status = 'archived',
                archived_at = COALESCE(archived_at, ?),
                updated_at = ?
            WHERE id = ?
              AND status = 'active'
            """,
            (now, now, int(knowledge_id)),
        )
        conn.commit()
        return cur.rowcount > 0


def build_knowledge_snapshot(
    *,
    db_file: str | Path | None = None,
) -> dict[str, Any]:
    ensure_ai_support_knowledge_tables(db_file)

    with sqlite3.connect(_db_path(db_file), timeout=15) as conn:
        conn.row_factory = sqlite3.Row

        counts = {
            str(row["status"]): int(row["c"] or 0)
            for row in conn.execute(
                """
                SELECT status, COUNT(*) AS c
                FROM ai_support_learning_candidates
                GROUP BY status
                """
            ).fetchall()
        }

        active_count = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM ai_support_knowledge
                WHERE status = 'active'
                """
            ).fetchone()[0]
            or 0
        )

    return {
        "pending_count": counts.get(STATUS_PENDING, 0),
        "approved_count": counts.get(STATUS_APPROVED, 0),
        "rejected_count": counts.get(STATUS_REJECTED, 0),
        "active_count": active_count,
        "pending": list_learning_candidates(
            status=STATUS_PENDING,
            limit=100,
            db_file=db_file,
        ),
        "knowledge": list_knowledge(
            status=KNOWLEDGE_ACTIVE,
            limit=300,
            db_file=db_file,
        ),
    }


def _search_terms(value: str) -> set[str]:
    text = re.sub(r"\s+", "", str(value or "").lower())
    ascii_words = set(re.findall(r"[a-z0-9_\-]{2,}", text))
    cjk = "".join(re.findall(r"[\u3400-\u9fff]", text))

    cjk_terms: set[str] = set()
    for size in (2, 3):
        if len(cjk) < size:
            continue
        for index in range(len(cjk) - size + 1):
            cjk_terms.add(cjk[index:index + size])

    return ascii_words | cjk_terms


def find_relevant_knowledge(
    query: str,
    *,
    limit: int = 5,
    db_file: str | Path | None = None,
) -> list[dict[str, Any]]:
    """
    Lightweight local retrieval: scan at most 500 active approved rows and rank
    by lexical overlap. No embedding model or background vector service runs on
    the VPS.
    """
    query_text = str(query or "").strip()
    if not query_text:
        return []

    query_terms = _search_terms(query_text)
    if not query_terms:
        return []

    rows = list_knowledge(
        status=KNOWLEDGE_ACTIVE,
        limit=500,
        db_file=db_file,
    )

    scored: list[tuple[int, int, dict[str, Any]]] = []
    normalized_query = re.sub(r"\s+", "", query_text.lower())

    for row in rows:
        question = str(row.get("question") or "")
        answer = str(row.get("answer") or "")
        q_terms = _search_terms(question)
        a_terms = _search_terms(answer)

        question_overlap = len(query_terms & q_terms)
        answer_overlap = len(query_terms & a_terms)
        score = question_overlap * 4 + answer_overlap

        normalized_question = re.sub(r"\s+", "", question.lower())
        if normalized_query and normalized_query in normalized_question:
            score += 20
        elif normalized_question and normalized_question in normalized_query:
            score += 12

        if score > 0:
            scored.append((score, int(row.get("id") or 0), row))

    scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
    safe_limit = max(1, min(int(limit or 5), 8))

    return [row for _, _, row in scored[:safe_limit]]
