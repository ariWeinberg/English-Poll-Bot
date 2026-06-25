from __future__ import annotations

import csv
import io
import json
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row


DbRow = dict[str, Any]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(database_url: str) -> psycopg.Connection[DbRow]:
    return psycopg.connect(database_url, row_factory=dict_row)


@contextmanager
def db_session(database_url: str) -> Iterator[psycopg.Connection[DbRow]]:
    conn = connect(database_url)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db(database_url: str) -> None:
    with db_session(database_url) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tenants (
                id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                username TEXT NOT NULL DEFAULT '',
                password TEXT NOT NULL DEFAULT '',
                greenapi_api_url TEXT NOT NULL DEFAULT 'https://api.green-api.com',
                greenapi_id_instance TEXT NOT NULL DEFAULT '',
                greenapi_api_token_instance TEXT NOT NULL DEFAULT '',
                gemini_api_key TEXT NOT NULL DEFAULT '',
                gemini_model TEXT NOT NULL DEFAULT 'gemini-3.5-flash',
                timezone TEXT NOT NULL DEFAULT 'Asia/Jerusalem',
                summary_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                scheduler_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                is_active BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS texts (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                attachment_name TEXT,
                attachment_path TEXT,
                chat_id TEXT NOT NULL DEFAULT '',
                morning_time TEXT NOT NULL DEFAULT '08:30',
                evening_time TEXT NOT NULL DEFAULT '18:00',
                summary_time_morning TEXT NOT NULL DEFAULT '08:25',
                summary_time_evening TEXT NOT NULL DEFAULT '17:55',
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS app_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS polls (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                text_id INTEGER NOT NULL REFERENCES texts(id) ON DELETE CASCADE,
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
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS poll_votes (
                id SERIAL PRIMARY KEY,
                poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
                option_name TEXT NOT NULL,
                voter_wid TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (poll_id, voter_wid)
            );

            CREATE INDEX IF NOT EXISTS idx_tenants_active ON tenants(is_active);
            CREATE INDEX IF NOT EXISTS idx_tenants_username ON tenants(username);
            CREATE INDEX IF NOT EXISTS idx_texts_tenant ON texts(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_polls_tenant ON polls(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_polls_text ON polls(text_id);
            CREATE INDEX IF NOT EXISTS idx_polls_greenapi_message_id ON polls(greenapi_message_id);
            CREATE INDEX IF NOT EXISTS idx_votes_poll_id ON poll_votes(poll_id);
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
                (1, 'Default tenant', 'admin', 'admin', 'https://api.green-api.com', '', '',
                 '', 'gemini-3.5-flash', 'Asia/Jerusalem', TRUE, TRUE,
                 TRUE, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (timestamp, timestamp),
        )
        conn.execute(
            """
            INSERT INTO texts
                (id, tenant_id, title, body, chat_id, morning_time, evening_time,
                 summary_time_morning, summary_time_evening, enabled, created_at, updated_at)
            VALUES
                (1, 1, 'Default text', '', '', '08:30', '18:00', '08:25', '17:55', TRUE, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (timestamp, timestamp),
        )
        conn.execute("SELECT setval(pg_get_serial_sequence('tenants', 'id'), COALESCE(MAX(id), 1)) FROM tenants")
        conn.execute("SELECT setval(pg_get_serial_sequence('texts', 'id'), COALESCE(MAX(id), 1)) FROM texts")


def list_tenants(conn: psycopg.Connection[DbRow]) -> list[DbRow]:
    return conn.execute("SELECT * FROM tenants ORDER BY is_active DESC, id ASC").fetchall()


def get_active_tenant(conn: psycopg.Connection[DbRow]) -> DbRow:
    row = conn.execute("SELECT * FROM tenants WHERE is_active = TRUE ORDER BY id LIMIT 1").fetchone()
    if row is None:
        row = conn.execute("SELECT * FROM tenants ORDER BY id LIMIT 1").fetchone()
    if row is None:
        raise RuntimeError("No tenant exists. Database initialization did not seed the default tenant.")
    return row


def get_tenant(conn: psycopg.Connection[DbRow], tenant_id: int) -> DbRow | None:
    return conn.execute("SELECT * FROM tenants WHERE id = %s", (tenant_id,)).fetchone()


def list_texts(conn: psycopg.Connection[DbRow], tenant_id: int | None = None) -> list[DbRow]:
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
        WHERE texts.tenant_id = %s
        ORDER BY texts.updated_at DESC
        """,
        (tenant_id,),
    ).fetchall()


def get_text(conn: psycopg.Connection[DbRow], text_id: int) -> DbRow | None:
    return conn.execute(
        """
        SELECT texts.*, tenants.name AS tenant_name
        FROM texts
        JOIN tenants ON tenants.id = texts.tenant_id
        WHERE texts.id = %s
        """,
        (text_id,),
    ).fetchone()


def upsert_tenant(
    conn: psycopg.Connection[DbRow],
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
        row = conn.execute(
            """
            INSERT INTO tenants (
                name, username, password, greenapi_api_url, greenapi_id_instance, greenapi_api_token_instance,
                gemini_api_key, gemini_model, timezone, summary_enabled, scheduler_enabled,
                is_active, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
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
                summary_enabled,
                scheduler_enabled,
                is_active,
                timestamp,
                timestamp,
            ),
        ).fetchone()
        return int(row["id"])

    conn.execute(
        """
        UPDATE tenants
        SET name = %s, username = %s, password = %s, greenapi_api_url = %s,
            greenapi_id_instance = %s, greenapi_api_token_instance = %s,
            gemini_api_key = %s, gemini_model = %s, timezone = %s, summary_enabled = %s,
            scheduler_enabled = %s, is_active = %s, updated_at = %s
        WHERE id = %s
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
            summary_enabled,
            scheduler_enabled,
            is_active,
            timestamp,
            tenant_id,
        ),
    )
    return tenant_id


def set_active_tenant(conn: psycopg.Connection[DbRow], tenant_id: int) -> None:
    conn.execute("UPDATE tenants SET is_active = CASE WHEN id = %s THEN TRUE ELSE FALSE END", (tenant_id,))


def delete_tenant(conn: psycopg.Connection[DbRow], tenant_id: int) -> None:
    conn.execute("DELETE FROM tenants WHERE id = %s", (tenant_id,))


def upsert_text(
    conn: psycopg.Connection[DbRow],
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
        row = conn.execute(
            """
            INSERT INTO texts (
                tenant_id, title, body, attachment_name, attachment_path, chat_id,
                morning_time, evening_time, summary_time_morning, summary_time_evening,
                enabled, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
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
                enabled,
                timestamp,
                timestamp,
            ),
        ).fetchone()
        return int(row["id"])

    existing = get_text(conn, text_id)
    conn.execute(
        """
        UPDATE texts
        SET tenant_id = %s, title = %s, body = %s, attachment_name = %s, attachment_path = %s,
            chat_id = %s, morning_time = %s, evening_time = %s, summary_time_morning = %s,
            summary_time_evening = %s, enabled = %s, updated_at = %s
        WHERE id = %s
        """,
        (
            tenant_id,
            title.strip() or "Text",
            body.strip(),
            attachment_name if attachment_name is not None else existing["attachment_name"] if existing else None,
            attachment_path if attachment_path is not None else existing["attachment_path"] if existing else None,
            chat_id.strip(),
            morning_time or "08:30",
            evening_time or "18:00",
            summary_time_morning or "08:25",
            summary_time_evening or "17:55",
            enabled,
            timestamp,
            text_id,
        ),
    )
    return text_id


def delete_text(conn: psycopg.Connection[DbRow], text_id: int) -> None:
    conn.execute("DELETE FROM texts WHERE id = %s", (text_id,))


def get_source_text(conn: psycopg.Connection[DbRow], text_id: int) -> str:
    row = conn.execute("SELECT body FROM texts WHERE id = %s", (text_id,)).fetchone()
    return row["body"] if row else ""


def get_text_attachment(conn: psycopg.Connection[DbRow], text_id: int) -> tuple[str | None, str | None]:
    row = conn.execute("SELECT attachment_name, attachment_path FROM texts WHERE id = %s", (text_id,)).fetchone()
    if not row:
        return None, None
    return row["attachment_name"], row["attachment_path"]


def create_poll(
    conn: psycopg.Connection[DbRow],
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
    row = conn.execute(
        """
        INSERT INTO polls (
            tenant_id, text_id, question, options_json, correct_option, explanation, chat_id,
            generated_from_text, scheduled_slot, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
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
    ).fetchone()
    return int(row["id"])


def mark_poll_sent(conn: psycopg.Connection[DbRow], poll_id: int, message_id: str) -> None:
    conn.execute(
        """
        UPDATE polls
        SET greenapi_message_id = %s, status = 'sent', sent_at = %s
        WHERE id = %s
        """,
        (message_id, now_iso(), poll_id),
    )


def mark_poll_failed(conn: psycopg.Connection[DbRow], poll_id: int, error: str) -> None:
    conn.execute("UPDATE polls SET status = %s WHERE id = %s", (f"failed: {error[:180]}", poll_id))


def get_poll_by_message_id(conn: psycopg.Connection[DbRow], message_id: str) -> DbRow | None:
    return conn.execute("SELECT * FROM polls WHERE greenapi_message_id = %s", (message_id,)).fetchone()


def list_polls(conn: psycopg.Connection[DbRow], limit: int = 25, tenant_id: int | None = None) -> list[DbRow]:
    if tenant_id is None:
        return conn.execute("SELECT * FROM polls ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall()
    return conn.execute(
        "SELECT * FROM polls WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s",
        (tenant_id, limit),
    ).fetchall()


def list_pending_texts(conn: psycopg.Connection[DbRow], tenant_id: int | None = None) -> list[DbRow]:
    sql = """
        SELECT texts.*, tenants.name AS tenant_name, tenants.greenapi_api_url, tenants.greenapi_id_instance,
               tenants.greenapi_api_token_instance, tenants.gemini_api_key, tenants.gemini_model,
               tenants.timezone, tenants.summary_enabled, tenants.scheduler_enabled
        FROM texts
        JOIN tenants ON tenants.id = texts.tenant_id
        WHERE texts.enabled = TRUE AND tenants.is_active = TRUE
    """
    params: tuple[Any, ...] = ()
    if tenant_id is not None:
        sql += " AND texts.tenant_id = %s"
        params = (tenant_id,)
    return conn.execute(sql, params).fetchall()


def list_unsummarized_polls(conn: psycopg.Connection[DbRow], tenant_id: int | None = None) -> list[DbRow]:
    sql = """
        SELECT * FROM polls
        WHERE status = 'sent' AND summary_sent_at IS NULL
    """
    params: tuple[Any, ...] = ()
    if tenant_id is not None:
        sql += " AND tenant_id = %s"
        params = (tenant_id,)
    sql += " ORDER BY sent_at ASC"
    return conn.execute(sql, params).fetchall()


def mark_summary_sent(conn: psycopg.Connection[DbRow], poll_id: int) -> None:
    conn.execute("UPDATE polls SET summary_sent_at = %s WHERE id = %s", (now_iso(), poll_id))


def replace_poll_votes(
    conn: psycopg.Connection[DbRow],
    *,
    poll_id: int,
    option_voters: dict[str, list[str]],
) -> None:
    conn.execute("DELETE FROM poll_votes WHERE poll_id = %s", (poll_id,))
    rows: list[tuple[int, str, str, str]] = []
    for option_name, voters in option_voters.items():
        for voter in voters:
            rows.append((poll_id, option_name, voter, now_iso()))
    if not rows:
        return
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO poll_votes (poll_id, option_name, voter_wid, updated_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (poll_id, voter_wid) DO UPDATE SET
                option_name = EXCLUDED.option_name,
                updated_at = EXCLUDED.updated_at
            """,
            rows,
        )


def poll_stats(conn: psycopg.Connection[DbRow], poll: DbRow) -> dict[str, Any]:
    options = json.loads(poll["options_json"])
    counts = {option: 0 for option in options}
    rows = conn.execute(
        """
        SELECT option_name, COUNT(*) AS vote_count
        FROM poll_votes
        WHERE poll_id = %s
        GROUP BY option_name
        """,
        (poll["id"],),
    ).fetchall()
    for row in rows:
        counts[row["option_name"]] = int(row["vote_count"])
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


def all_poll_stats(conn: psycopg.Connection[DbRow], limit: int = 25, tenant_id: int | None = None) -> list[dict[str, Any]]:
    return [poll_stats(conn, poll) for poll in list_polls(conn, limit, tenant_id)]


def export_stats_csv(conn: psycopg.Connection[DbRow], tenant_id: int | None = None) -> str:
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
