from __future__ import annotations

import csv
import io
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_session(path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with db_session(path) as conn:
        existing_tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        poll_columns = {
            row["name"] for row in conn.execute("PRAGMA table_info(polls)").fetchall()
        } if "polls" in existing_tables else set()
        legacy_schema = "tenants" not in existing_tables or "tenant_id" not in poll_columns

        if legacy_schema:
            old_config = {}
            if "app_config" in existing_tables:
                old_config = {
                    row["key"]: row["value"]
                    for row in conn.execute("SELECT key, value FROM app_config").fetchall()
                }
            old_text = ""
            old_chat_id = ""
            if "source_text" in existing_tables:
                row = conn.execute("SELECT text FROM source_text WHERE id = 1").fetchone()
                old_text = row["text"] if row else ""
            if "polls" in existing_tables:
                try:
                    row = conn.execute("SELECT chat_id FROM polls ORDER BY id LIMIT 1").fetchone()
                    old_chat_id = row["chat_id"] if row else ""
                except sqlite3.OperationalError:
                    old_chat_id = ""

            conn.executescript(
                """
                DROP TABLE IF EXISTS poll_votes;
                DROP TABLE IF EXISTS polls;
                DROP TABLE IF EXISTS texts;
                DROP TABLE IF EXISTS tenants;
                DROP TABLE IF EXISTS app_config;
                """
            )

            conn.executescript(
                """
                CREATE TABLE tenants (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    username TEXT NOT NULL DEFAULT '',
                    password TEXT NOT NULL DEFAULT '',
                    greenapi_api_url TEXT NOT NULL DEFAULT 'https://api.green-api.com',
                    greenapi_id_instance TEXT NOT NULL DEFAULT '',
                    greenapi_api_token_instance TEXT NOT NULL DEFAULT '',
                    gemini_api_key TEXT NOT NULL DEFAULT '',
                    gemini_model TEXT NOT NULL DEFAULT 'gemini-3.5-flash',
                    timezone TEXT NOT NULL DEFAULT 'Asia/Jerusalem',
                    summary_enabled INTEGER NOT NULL DEFAULT 1,
                    scheduler_enabled INTEGER NOT NULL DEFAULT 1,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE texts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL DEFAULT '',
                    attachment_name TEXT,
                    attachment_path TEXT,
                    chat_id TEXT NOT NULL DEFAULT '',
                    morning_time TEXT NOT NULL DEFAULT '08:30',
                    evening_time TEXT NOT NULL DEFAULT '18:00',
                    summary_time_morning TEXT NOT NULL DEFAULT '08:25',
                    summary_time_evening TEXT NOT NULL DEFAULT '17:55',
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
                );

                CREATE TABLE app_config (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL DEFAULT ''
                );

                CREATE TABLE polls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id INTEGER NOT NULL,
                    text_id INTEGER NOT NULL,
                    question TEXT NOT NULL,
                    options_json TEXT NOT NULL,
                    correct_option TEXT NOT NULL,
                    explanation TEXT NOT NULL DEFAULT '',
                    greenapi_message_id TEXT,
                    chat_id TEXT NOT NULL,
                    generated_from_text TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'draft',
                    scheduled_slot TEXT,
                    sent_at TEXT,
                    summary_sent_at TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                    FOREIGN KEY (text_id) REFERENCES texts(id) ON DELETE CASCADE
                );

                CREATE TABLE poll_votes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    poll_id INTEGER NOT NULL,
                    option_name TEXT NOT NULL,
                    voter_wid TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (poll_id, voter_wid),
                    FOREIGN KEY (poll_id) REFERENCES polls(id) ON DELETE CASCADE
                );

                CREATE INDEX idx_tenants_active ON tenants(is_active);
                CREATE INDEX idx_texts_tenant ON texts(tenant_id);
                CREATE INDEX idx_polls_tenant ON polls(tenant_id);
                CREATE INDEX idx_polls_text ON polls(text_id);
                CREATE INDEX idx_polls_greenapi_message_id ON polls(greenapi_message_id);
                CREATE INDEX idx_votes_poll_id ON poll_votes(poll_id);
                """
            )

            timestamp = now_iso()
            conn.execute(
                """
                INSERT INTO tenants
                    (id, name, username, password, greenapi_api_url, greenapi_id_instance, greenapi_api_token_instance,
                     gemini_api_key, gemini_model, timezone, summary_enabled, scheduler_enabled,
                     is_active, created_at, updated_at)
                VALUES
                    (1, 'Default tenant', 'admin', 'admin', ?, ?, ?, ?, ?, ?, 1, 1, 1, ?, ?)
                """,
                (
                    old_config.get("greenapi_api_url", "https://api.green-api.com"),
                    old_config.get("greenapi_id_instance", ""),
                    old_config.get("greenapi_api_token_instance", ""),
                    old_config.get("gemini_api_key", ""),
                    old_config.get("gemini_model", "gemini-3.5-flash"),
                    old_config.get("timezone", "Asia/Jerusalem"),
                    timestamp,
                    timestamp,
                ),
            )
            conn.execute(
                """
                INSERT INTO texts
                    (id, tenant_id, title, body, chat_id, morning_time, evening_time,
                     summary_time_morning, summary_time_evening, enabled, created_at, updated_at)
                VALUES
                    (1, 1, 'Default text', ?, ?, '08:30', '18:00', '08:25', '17:55', 1, ?, ?)
                """,
                (old_text, old_chat_id, timestamp, timestamp),
            )
            conn.execute(
                """
                INSERT INTO app_config (key, value) VALUES
                    ('greenapi_api_url', ?),
                    ('greenapi_id_instance', ?),
                    ('greenapi_api_token_instance', ?),
                    ('gemini_api_key', ?),
                    ('gemini_model', ?),
                    ('timezone', ?),
                    ('summary_enabled', 'true'),
                    ('scheduler_enabled', 'true')
                """,
                (
                    old_config.get("greenapi_api_url", "https://api.green-api.com"),
                    old_config.get("greenapi_id_instance", ""),
                    old_config.get("greenapi_api_token_instance", ""),
                    old_config.get("gemini_api_key", ""),
                    old_config.get("gemini_model", "gemini-3.5-flash"),
                    old_config.get("timezone", "Asia/Jerusalem"),
                ),
            )
            return

        if "tenants" in existing_tables:
            tenant_columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(tenants)").fetchall()
            }
            if "username" not in tenant_columns:
                conn.execute("ALTER TABLE tenants ADD COLUMN username TEXT NOT NULL DEFAULT ''")
            if "password" not in tenant_columns:
                conn.execute("ALTER TABLE tenants ADD COLUMN password TEXT NOT NULL DEFAULT ''")
            conn.execute(
                """
                UPDATE tenants
                SET username = COALESCE(NULLIF(username, ''), 'admin'),
                    password = COALESCE(NULLIF(password, ''), 'admin')
                WHERE id = 1
                """
            )

        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                password TEXT NOT NULL DEFAULT '',
                greenapi_api_url TEXT NOT NULL DEFAULT 'https://api.green-api.com',
                greenapi_id_instance TEXT NOT NULL DEFAULT '',
                greenapi_api_token_instance TEXT NOT NULL DEFAULT '',
                gemini_api_key TEXT NOT NULL DEFAULT '',
                gemini_model TEXT NOT NULL DEFAULT 'gemini-3.5-flash',
                timezone TEXT NOT NULL DEFAULT 'Asia/Jerusalem',
                summary_enabled INTEGER NOT NULL DEFAULT 1,
                scheduler_enabled INTEGER NOT NULL DEFAULT 1,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS texts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                attachment_name TEXT,
                attachment_path TEXT,
                chat_id TEXT NOT NULL DEFAULT '',
                morning_time TEXT NOT NULL DEFAULT '08:30',
                evening_time TEXT NOT NULL DEFAULT '18:00',
                summary_time_morning TEXT NOT NULL DEFAULT '08:25',
                summary_time_evening TEXT NOT NULL DEFAULT '17:55',
                enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS app_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS polls (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tenant_id INTEGER NOT NULL,
                text_id INTEGER NOT NULL,
                question TEXT NOT NULL,
                options_json TEXT NOT NULL,
                correct_option TEXT NOT NULL,
                explanation TEXT NOT NULL DEFAULT '',
                greenapi_message_id TEXT,
                chat_id TEXT NOT NULL,
                generated_from_text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'draft',
                scheduled_slot TEXT,
                sent_at TEXT,
                summary_sent_at TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
                FOREIGN KEY (text_id) REFERENCES texts(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS poll_votes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                poll_id INTEGER NOT NULL,
                option_name TEXT NOT NULL,
                voter_wid TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (poll_id, voter_wid),
                FOREIGN KEY (poll_id) REFERENCES polls(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_tenants_active ON tenants(is_active);
            CREATE INDEX IF NOT EXISTS idx_texts_tenant ON texts(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_polls_tenant ON polls(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_polls_text ON polls(text_id);
            CREATE INDEX IF NOT EXISTS idx_polls_greenapi_message_id ON polls(greenapi_message_id);
            CREATE INDEX IF NOT EXISTS idx_votes_poll_id ON poll_votes(poll_id);
            """
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO tenants
                (id, name, username, password, greenapi_api_url, greenapi_id_instance, greenapi_api_token_instance,
                 gemini_api_key, gemini_model, timezone, summary_enabled, scheduler_enabled,
                 is_active, created_at, updated_at)
            VALUES
                (1, 'Default tenant', 'admin', 'admin', 'https://api.green-api.com', '', '',
                 '', 'gemini-3.5-flash', 'Asia/Jerusalem', 1, 1,
                 1, ?, ?)
            """,
            (now_iso(), now_iso()),
        )
        conn.execute(
            """
            INSERT OR IGNORE INTO texts
                (id, tenant_id, title, body, chat_id, morning_time, evening_time,
                 summary_time_morning, summary_time_evening, enabled, created_at, updated_at)
            VALUES
                (1, 1, 'Default text', '', '', '08:30', '18:00', '08:25', '17:55', 1, ?, ?)
            """,
            (now_iso(), now_iso()),
        )


def list_tenants(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM tenants ORDER BY is_active DESC, id ASC").fetchall()


def get_active_tenant(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM tenants WHERE is_active = 1 ORDER BY id LIMIT 1").fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM tenants ORDER BY id LIMIT 1").fetchone()
    return row


def get_tenant(conn: sqlite3.Connection, tenant_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM tenants WHERE id = ?", (tenant_id,)).fetchone()


def list_texts(conn: sqlite3.Connection, tenant_id: int | None = None) -> list[sqlite3.Row]:
    if tenant_id is None:
        return conn.execute(
            """
            SELECT texts.*, tenants.name AS tenant_name
            FROM texts
            JOIN tenants ON tenants.id = texts.tenant_id
            ORDER BY texts.updated_at DESC
            """
        ).fetchall()
    return conn.execute(
        """
        SELECT texts.*, tenants.name AS tenant_name
        FROM texts
        JOIN tenants ON tenants.id = texts.tenant_id
        WHERE texts.tenant_id = ?
        ORDER BY texts.updated_at DESC
        """,
        (tenant_id,),
    ).fetchall()


def get_text(conn: sqlite3.Connection, text_id: int) -> sqlite3.Row | None:
    return conn.execute(
        """
        SELECT texts.*, tenants.name AS tenant_name
        FROM texts
        JOIN tenants ON tenants.id = texts.tenant_id
        WHERE texts.id = ?
        """,
        (text_id,),
    ).fetchone()


def upsert_tenant(
    conn: sqlite3.Connection,
    *,
    tenant_id: int | None,
    name: str,
    username: str,
    password: str,
    greenapi_api_url: str,
    greenapi_id_instance: str,
    greenapi_api_token_instance: str,
    gemini_api_key: str,
    gemini_model: str,
    timezone: str,
    summary_enabled: bool,
    scheduler_enabled: bool,
    is_active: bool,
) -> int:
    timestamp = now_iso()
    if tenant_id is None:
        cursor = conn.execute(
            """
            INSERT INTO tenants (
                name, username, password, greenapi_api_url, greenapi_id_instance, greenapi_api_token_instance,
                gemini_api_key, gemini_model, timezone, summary_enabled, scheduler_enabled,
                is_active, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name.strip() or "Tenant",
                username.strip(),
                password.strip(),
                greenapi_api_url.strip().rstrip("/"),
                greenapi_id_instance.strip(),
                greenapi_api_token_instance.strip(),
                gemini_api_key.strip(),
                gemini_model.strip() or "gemini-3.5-flash",
                timezone.strip() or "Asia/Jerusalem",
                int(summary_enabled),
                int(scheduler_enabled),
                int(is_active),
                timestamp,
                timestamp,
            ),
        )
        return int(cursor.lastrowid)

    conn.execute(
        """
        UPDATE tenants
        SET name = ?, username = ?, password = ?, greenapi_api_url = ?, greenapi_id_instance = ?, greenapi_api_token_instance = ?,
            gemini_api_key = ?, gemini_model = ?, timezone = ?, summary_enabled = ?,
            scheduler_enabled = ?, is_active = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            name.strip() or "Tenant",
            username.strip(),
            password.strip(),
            greenapi_api_url.strip().rstrip("/"),
            greenapi_id_instance.strip(),
            greenapi_api_token_instance.strip(),
            gemini_api_key.strip(),
            gemini_model.strip() or "gemini-3.5-flash",
            timezone.strip() or "Asia/Jerusalem",
            int(summary_enabled),
            int(scheduler_enabled),
            int(is_active),
            timestamp,
            tenant_id,
        ),
    )
    return tenant_id


def set_active_tenant(conn: sqlite3.Connection, tenant_id: int) -> None:
    conn.execute("UPDATE tenants SET is_active = CASE WHEN id = ? THEN 1 ELSE 0 END", (tenant_id,))


def delete_tenant(conn: sqlite3.Connection, tenant_id: int) -> None:
    conn.execute("DELETE FROM tenants WHERE id = ?", (tenant_id,))


def upsert_text(
    conn: sqlite3.Connection,
    *,
    text_id: int | None,
    tenant_id: int,
    title: str,
    body: str,
    chat_id: str,
    morning_time: str,
    evening_time: str,
    summary_time_morning: str,
    summary_time_evening: str,
    enabled: bool,
    attachment_name: str | None = None,
    attachment_path: str | None = None,
) -> int:
    timestamp = now_iso()
    if text_id is None:
        cursor = conn.execute(
            """
            INSERT INTO texts (
                tenant_id, title, body, attachment_name, attachment_path, chat_id,
                morning_time, evening_time, summary_time_morning, summary_time_evening,
                enabled, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tenant_id,
                title.strip() or "Text",
                body.strip(),
                attachment_name,
                attachment_path,
                chat_id.strip(),
                morning_time or "08:30",
                evening_time or "18:00",
                summary_time_morning or "08:25",
                summary_time_evening or "17:55",
                int(enabled),
                timestamp,
                timestamp,
            ),
        )
        return int(cursor.lastrowid)

    conn.execute(
        """
        UPDATE texts
        SET tenant_id = ?, title = ?, body = ?, attachment_name = ?, attachment_path = ?,
            chat_id = ?, morning_time = ?, evening_time = ?, summary_time_morning = ?,
            summary_time_evening = ?, enabled = ?, updated_at = ?
        WHERE id = ?
        """,
        (
            tenant_id,
            title.strip() or "Text",
            body.strip(),
            attachment_name,
            attachment_path,
            chat_id.strip(),
            morning_time or "08:30",
            evening_time or "18:00",
            summary_time_morning or "08:25",
            summary_time_evening or "17:55",
            int(enabled),
            timestamp,
            text_id,
        ),
    )
    return text_id


def delete_text(conn: sqlite3.Connection, text_id: int) -> None:
    conn.execute("DELETE FROM texts WHERE id = ?", (text_id,))


def get_source_text(conn: sqlite3.Connection, text_id: int) -> str:
    row = conn.execute("SELECT body FROM texts WHERE id = ?", (text_id,)).fetchone()
    return row["body"] if row else ""


def get_text_attachment(conn: sqlite3.Connection, text_id: int) -> tuple[str | None, str | None]:
    row = conn.execute("SELECT attachment_name, attachment_path FROM texts WHERE id = ?", (text_id,)).fetchone()
    if not row:
        return None, None
    return row["attachment_name"], row["attachment_path"]


def create_poll(
    conn: sqlite3.Connection,
    *,
    tenant_id: int,
    text_id: int,
    question: str,
    options: list[str],
    correct_option: str,
    explanation: str,
    chat_id: str,
    generated_from_text: str,
    scheduled_slot: str | None,
) -> int:
    cursor = conn.execute(
        """
        INSERT INTO polls (
            tenant_id, text_id, question, options_json, correct_option, explanation, chat_id,
            generated_from_text, scheduled_slot, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            tenant_id,
            text_id,
            question,
            json.dumps(options, ensure_ascii=False),
            correct_option,
            explanation,
            chat_id,
            generated_from_text,
            scheduled_slot,
            now_iso(),
        ),
    )
    return int(cursor.lastrowid)


def mark_poll_sent(conn: sqlite3.Connection, poll_id: int, message_id: str) -> None:
    conn.execute(
        """
        UPDATE polls
        SET greenapi_message_id = ?, status = 'sent', sent_at = ?
        WHERE id = ?
        """,
        (message_id, now_iso(), poll_id),
    )


def mark_poll_failed(conn: sqlite3.Connection, poll_id: int, error: str) -> None:
    conn.execute(
        """
        UPDATE polls
        SET status = ?
        WHERE id = ?
        """,
        (f"failed: {error[:180]}", poll_id),
    )


def get_poll_by_message_id(conn: sqlite3.Connection, message_id: str) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM polls WHERE greenapi_message_id = ?",
        (message_id,),
    ).fetchone()


def list_polls(conn: sqlite3.Connection, limit: int = 25, tenant_id: int | None = None) -> list[sqlite3.Row]:
    if tenant_id is None:
        return conn.execute("SELECT * FROM polls ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return conn.execute(
        "SELECT * FROM polls WHERE tenant_id = ? ORDER BY created_at DESC LIMIT ?",
        (tenant_id, limit),
    ).fetchall()


def list_pending_texts(conn: sqlite3.Connection, tenant_id: int | None = None) -> list[sqlite3.Row]:
    sql = """
        SELECT texts.*, tenants.name AS tenant_name, tenants.greenapi_api_url, tenants.greenapi_id_instance,
               tenants.greenapi_api_token_instance, tenants.gemini_api_key, tenants.gemini_model,
               tenants.timezone, tenants.summary_enabled, tenants.scheduler_enabled
        FROM texts
        JOIN tenants ON tenants.id = texts.tenant_id
        WHERE texts.enabled = 1 AND tenants.is_active = 1
    """
    params: tuple[Any, ...] = ()
    if tenant_id is not None:
        sql += " AND texts.tenant_id = ?"
        params = (tenant_id,)
    return conn.execute(sql, params).fetchall()


def list_unsummarized_polls(conn: sqlite3.Connection, tenant_id: int | None = None) -> list[sqlite3.Row]:
    sql = """
        SELECT * FROM polls
        WHERE status = 'sent' AND summary_sent_at IS NULL
    """
    params: tuple[Any, ...] = ()
    if tenant_id is not None:
        sql += " AND tenant_id = ?"
        params = (tenant_id,)
    sql += " ORDER BY sent_at ASC"
    return conn.execute(sql, params).fetchall()


def mark_summary_sent(conn: sqlite3.Connection, poll_id: int) -> None:
    conn.execute("UPDATE polls SET summary_sent_at = ? WHERE id = ?", (now_iso(), poll_id))


def replace_poll_votes(
    conn: sqlite3.Connection,
    *,
    poll_id: int,
    option_voters: dict[str, list[str]],
) -> None:
    conn.execute("DELETE FROM poll_votes WHERE poll_id = ?", (poll_id,))
    rows: list[tuple[int, str, str, str]] = []
    for option_name, voters in option_voters.items():
        for voter in voters:
            rows.append((poll_id, option_name, voter, now_iso()))
    conn.executemany(
        """
        INSERT INTO poll_votes (poll_id, option_name, voter_wid, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(poll_id, voter_wid) DO UPDATE SET
            option_name = excluded.option_name,
            updated_at = excluded.updated_at
        """,
        rows,
    )


def poll_stats(conn: sqlite3.Connection, poll: sqlite3.Row) -> dict[str, Any]:
    options = json.loads(poll["options_json"])
    counts = {option: 0 for option in options}
    rows = conn.execute(
        """
        SELECT option_name, COUNT(*) AS vote_count
        FROM poll_votes
        WHERE poll_id = ?
        GROUP BY option_name
        """,
        (poll["id"],),
    ).fetchall()
    for row in rows:
        counts[row["option_name"]] = row["vote_count"]
    total = sum(counts.values())
    correct_count = counts.get(poll["correct_option"], 0)
    return {
        "poll": poll,
        "options": options,
        "counts": counts,
        "total": total,
        "correct_count": correct_count,
        "correct_rate": (correct_count / total * 100) if total else 0.0,
    }


def all_poll_stats(conn: sqlite3.Connection, limit: int = 25, tenant_id: int | None = None) -> list[dict[str, Any]]:
    return [poll_stats(conn, poll) for poll in list_polls(conn, limit, tenant_id)]


def export_stats_csv(conn: sqlite3.Connection, tenant_id: int | None = None) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "poll_id",
            "sent_at",
            "question",
            "option",
            "votes",
            "total_votes",
            "correct_option",
            "correct_rate_percent",
        ]
    )
    for item in all_poll_stats(conn, limit=10000, tenant_id=tenant_id):
        poll = item["poll"]
        for option, votes in item["counts"].items():
            writer.writerow(
                [
                    poll["id"],
                    poll["sent_at"] or "",
                    poll["question"],
                    option,
                    votes,
                    item["total"],
                    poll["correct_option"],
                    f"{item['correct_rate']:.2f}",
                ]
            )
    return output.getvalue()
