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


def _page_bounds(page: int = 1, page_size: int = 25) -> tuple[int, int, int]:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), 100)
    return safe_page, safe_page_size, (safe_page - 1) * safe_page_size


def _like(value: str) -> str:
    return f"%{value.strip()}%"


def paginated_response(items: list[DbRow], total: int, page: int, page_size: int) -> dict[str, Any]:
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_next": page * page_size < total,
    }


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

            CREATE TABLE IF NOT EXISTS poll_vote_events (
                id SERIAL PRIMARY KEY,
                poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
                option_name TEXT NOT NULL,
                voter_wid TEXT NOT NULL,
                recorded_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_tenants_active ON tenants(is_active);
            CREATE INDEX IF NOT EXISTS idx_tenants_username ON tenants(username);
            CREATE INDEX IF NOT EXISTS idx_texts_tenant ON texts(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_polls_tenant ON polls(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_polls_text ON polls(text_id);
            CREATE INDEX IF NOT EXISTS idx_polls_status ON polls(status);
            CREATE INDEX IF NOT EXISTS idx_polls_sent_at ON polls(sent_at);
            CREATE INDEX IF NOT EXISTS idx_polls_greenapi_message_id ON polls(greenapi_message_id);
            CREATE INDEX IF NOT EXISTS idx_votes_poll_id ON poll_votes(poll_id);
            CREATE INDEX IF NOT EXISTS idx_votes_option_name ON poll_votes(option_name);
            CREATE INDEX IF NOT EXISTS idx_votes_voter_wid ON poll_votes(voter_wid);
            CREATE INDEX IF NOT EXISTS idx_vote_events_poll_id ON poll_vote_events(poll_id);
            CREATE INDEX IF NOT EXISTS idx_vote_events_voter_wid ON poll_vote_events(voter_wid);
            CREATE INDEX IF NOT EXISTS idx_vote_events_recorded_at ON poll_vote_events(recorded_at);
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


def list_tenants_page(
    conn: psycopg.Connection[DbRow],
    *,
    page: int = 1,
    page_size: int = 25,
    is_active: bool | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    page, page_size, offset = _page_bounds(page, page_size)
    where: list[str] = []
    params: list[Any] = []
    if is_active is not None:
        where.append("is_active = %s")
        params.append(is_active)
    if search:
        where.append("(name ILIKE %s OR username ILIKE %s)")
        params.extend([_like(search), _like(search)])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(f"SELECT COUNT(*) AS count FROM tenants {where_sql}", params).fetchone()["count"]
    items = conn.execute(
        f"SELECT * FROM tenants {where_sql} ORDER BY is_active DESC, id ASC LIMIT %s OFFSET %s",
        [*params, page_size, offset],
    ).fetchall()
    return paginated_response(items, int(total), page, page_size)


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


def list_texts_page(
    conn: psycopg.Connection[DbRow],
    *,
    page: int = 1,
    page_size: int = 25,
    tenant_id: int | None = None,
    enabled: bool | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    page, page_size, offset = _page_bounds(page, page_size)
    where: list[str] = []
    params: list[Any] = []
    if tenant_id is not None:
        where.append("texts.tenant_id = %s")
        params.append(tenant_id)
    if enabled is not None:
        where.append("texts.enabled = %s")
        params.append(enabled)
    if search:
        where.append("(texts.title ILIKE %s OR texts.body ILIKE %s OR texts.chat_id ILIKE %s)")
        params.extend([_like(search), _like(search), _like(search)])
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(
        f"SELECT COUNT(*) AS count FROM texts JOIN tenants ON tenants.id = texts.tenant_id {where_sql}",
        params,
    ).fetchone()["count"]
    items = conn.execute(
        f"""
        SELECT texts.*, tenants.name AS tenant_name
        FROM texts
        JOIN tenants ON tenants.id = texts.tenant_id
        {where_sql}
        ORDER BY texts.updated_at DESC
        LIMIT %s OFFSET %s
        """,
        [*params, page_size, offset],
    ).fetchall()
    return paginated_response(items, int(total), page, page_size)


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


def get_poll_by_message_id_for_tenant(
    conn: psycopg.Connection[DbRow],
    *,
    message_id: str,
    tenant_id: int,
) -> DbRow | None:
    return conn.execute(
        "SELECT * FROM polls WHERE greenapi_message_id = %s AND tenant_id = %s",
        (message_id, tenant_id),
    ).fetchone()


def get_poll(conn: psycopg.Connection[DbRow], poll_id: int) -> DbRow | None:
    return conn.execute("SELECT * FROM polls WHERE id = %s", (poll_id,)).fetchone()


def list_polls(conn: psycopg.Connection[DbRow], limit: int = 25, tenant_id: int | None = None) -> list[DbRow]:
    if tenant_id is None:
        return conn.execute("SELECT * FROM polls ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall()
    return conn.execute(
        "SELECT * FROM polls WHERE tenant_id = %s ORDER BY created_at DESC LIMIT %s",
        (tenant_id, limit),
    ).fetchall()


def list_polls_page(
    conn: psycopg.Connection[DbRow],
    *,
    page: int = 1,
    page_size: int = 25,
    tenant_id: int | None = None,
    text_id: int | None = None,
    status: str | None = None,
    scheduled_slot: str | None = None,
    sent_from: str | None = None,
    sent_to: str | None = None,
) -> dict[str, Any]:
    page, page_size, offset = _page_bounds(page, page_size)
    where: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("tenant_id", tenant_id),
        ("text_id", text_id),
        ("status", status),
        ("scheduled_slot", scheduled_slot),
    ):
        if value is not None:
            where.append(f"{column} = %s")
            params.append(value)
    if sent_from:
        where.append("sent_at >= %s")
        params.append(sent_from)
    if sent_to:
        where.append("sent_at <= %s")
        params.append(sent_to)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(f"SELECT COUNT(*) AS count FROM polls {where_sql}", params).fetchone()["count"]
    items = conn.execute(
        f"SELECT * FROM polls {where_sql} ORDER BY created_at DESC LIMIT %s OFFSET %s",
        [*params, page_size, offset],
    ).fetchall()
    return paginated_response(items, int(total), page, page_size)


def update_poll(
    conn: psycopg.Connection[DbRow],
    *,
    poll_id: int,
    tenant_id: int,
    text_id: int,
    question: str,
    options: list[str],
    correct_option: str,
    explanation: str,
    greenapi_message_id: str | None,
    chat_id: str,
    generated_from_text: str,
    status: str,
    scheduled_slot: str | None,
    sent_at: str | None,
    summary_sent_at: str | None,
) -> None:
    conn.execute(
        """
        UPDATE polls
        SET tenant_id = %s, text_id = %s, question = %s, options_json = %s,
            correct_option = %s, explanation = %s, greenapi_message_id = %s,
            chat_id = %s, generated_from_text = %s, status = %s, scheduled_slot = %s,
            sent_at = %s, summary_sent_at = %s
        WHERE id = %s
        """,
        (
            tenant_id,
            text_id,
            question,
            json.dumps(options, ensure_ascii=False),
            correct_option,
            explanation,
            greenapi_message_id,
            chat_id,
            generated_from_text,
            status,
            scheduled_slot,
            sent_at,
            summary_sent_at,
            poll_id,
        ),
    )


def delete_poll(conn: psycopg.Connection[DbRow], poll_id: int) -> None:
    conn.execute("DELETE FROM polls WHERE id = %s", (poll_id,))


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
    existing_rows = conn.execute("SELECT option_name, voter_wid FROM poll_votes WHERE poll_id = %s", (poll_id,)).fetchall()
    current_by_voter = {str(row["voter_wid"]): str(row["option_name"]) for row in existing_rows}
    target_by_voter: dict[str, str] = {}
    event_rows: list[tuple[int, str, str, str]] = []
    timestamp = now_iso()
    for option_name, voters in option_voters.items():
        for voter in voters:
            voter_id = voter.strip()
            option = option_name.strip()
            if not voter_id or not option:
                continue
            target_by_voter[voter_id] = option
            if current_by_voter.get(voter_id) != option:
                event_rows.append((poll_id, option, voter_id, timestamp))
    with conn.cursor() as cursor:
        cursor.executemany(
            """
            INSERT INTO poll_votes (poll_id, option_name, voter_wid, updated_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (poll_id, voter_wid) DO UPDATE SET
                option_name = EXCLUDED.option_name,
                updated_at = EXCLUDED.updated_at
            """,
            [(poll_id, option_name, voter_wid, timestamp) for voter_wid, option_name in target_by_voter.items()],
        )
    if target_by_voter:
        conn.execute(
            "DELETE FROM poll_votes WHERE poll_id = %s AND voter_wid <> ALL(%s)",
            (poll_id, list(target_by_voter.keys())),
        )
    else:
        conn.execute("DELETE FROM poll_votes WHERE poll_id = %s", (poll_id,))
    if event_rows:
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO poll_vote_events (poll_id, option_name, voter_wid, recorded_at)
                VALUES (%s, %s, %s, %s)
                """,
                event_rows,
            )


def list_poll_votes_page(
    conn: psycopg.Connection[DbRow],
    *,
    page: int = 1,
    page_size: int = 25,
    poll_id: int | None = None,
    option_name: str | None = None,
    voter_wid: str | None = None,
) -> dict[str, Any]:
    page, page_size, offset = _page_bounds(page, page_size)
    where: list[str] = []
    params: list[Any] = []
    if poll_id is not None:
        where.append("poll_id = %s")
        params.append(poll_id)
    if option_name:
        where.append("option_name = %s")
        params.append(option_name)
    if voter_wid:
        where.append("voter_wid ILIKE %s")
        params.append(_like(voter_wid))
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(f"SELECT COUNT(*) AS count FROM poll_votes {where_sql}", params).fetchone()["count"]
    items = conn.execute(
        f"SELECT * FROM poll_votes {where_sql} ORDER BY updated_at DESC, id DESC LIMIT %s OFFSET %s",
        [*params, page_size, offset],
    ).fetchall()
    return paginated_response(items, int(total), page, page_size)


def list_poll_vote_events_page(
    conn: psycopg.Connection[DbRow],
    *,
    page: int = 1,
    page_size: int = 25,
    tenant_id: int | None = None,
    poll_id: int | None = None,
    option_name: str | None = None,
    voter_wid: str | None = None,
) -> dict[str, Any]:
    page, page_size, offset = _page_bounds(page, page_size)
    where: list[str] = []
    params: list[Any] = []
    if tenant_id is not None:
        where.append("polls.tenant_id = %s")
        params.append(tenant_id)
    if poll_id is not None:
        where.append("poll_vote_events.poll_id = %s")
        params.append(poll_id)
    if option_name:
        where.append("poll_vote_events.option_name = %s")
        params.append(option_name)
    if voter_wid:
        where.append("poll_vote_events.voter_wid ILIKE %s")
        params.append(_like(voter_wid))
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    total = conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM poll_vote_events
        JOIN polls ON polls.id = poll_vote_events.poll_id
        {where_sql}
        """,
        params,
    ).fetchone()["count"]
    items = conn.execute(
        f"""
        SELECT poll_vote_events.*
        FROM poll_vote_events
        JOIN polls ON polls.id = poll_vote_events.poll_id
        {where_sql}
        ORDER BY poll_vote_events.recorded_at DESC, poll_vote_events.id DESC
        LIMIT %s OFFSET %s
        """,
        [*params, page_size, offset],
    ).fetchall()
    return paginated_response(items, int(total), page, page_size)


def get_poll_vote(conn: psycopg.Connection[DbRow], vote_id: int) -> DbRow | None:
    return conn.execute("SELECT * FROM poll_votes WHERE id = %s", (vote_id,)).fetchone()


def get_poll_vote_event(conn: psycopg.Connection[DbRow], event_id: int) -> DbRow | None:
    return conn.execute("SELECT * FROM poll_vote_events WHERE id = %s", (event_id,)).fetchone()


def record_poll_vote_event(
    conn: psycopg.Connection[DbRow],
    *,
    poll_id: int,
    option_name: str,
    voter_wid: str,
    recorded_at: str | None = None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO poll_vote_events (poll_id, option_name, voter_wid, recorded_at)
        VALUES (%s, %s, %s, %s)
        RETURNING id
        """,
        (poll_id, option_name.strip(), voter_wid.strip(), recorded_at or now_iso()),
    ).fetchone()
    return int(row["id"])


def create_poll_vote(conn: psycopg.Connection[DbRow], *, poll_id: int, option_name: str, voter_wid: str) -> int:
    timestamp = now_iso()
    row = conn.execute(
        """
        INSERT INTO poll_votes (poll_id, option_name, voter_wid, updated_at)
        VALUES (%s, %s, %s, %s)
        ON CONFLICT (poll_id, voter_wid) DO UPDATE SET
            option_name = EXCLUDED.option_name,
            updated_at = EXCLUDED.updated_at
        RETURNING id
        """,
        (poll_id, option_name.strip(), voter_wid.strip(), timestamp),
    ).fetchone()
    record_poll_vote_event(
        conn,
        poll_id=poll_id,
        option_name=option_name,
        voter_wid=voter_wid,
        recorded_at=timestamp,
    )
    return int(row["id"])


def update_poll_vote(conn: psycopg.Connection[DbRow], *, vote_id: int, poll_id: int, option_name: str, voter_wid: str) -> None:
    timestamp = now_iso()
    conn.execute(
        """
        UPDATE poll_votes
        SET poll_id = %s, option_name = %s, voter_wid = %s, updated_at = %s
        WHERE id = %s
        """,
        (poll_id, option_name.strip(), voter_wid.strip(), timestamp, vote_id),
    )
    record_poll_vote_event(
        conn,
        poll_id=poll_id,
        option_name=option_name,
        voter_wid=voter_wid,
        recorded_at=timestamp,
    )


def delete_poll_vote(conn: psycopg.Connection[DbRow], vote_id: int) -> None:
    conn.execute("DELETE FROM poll_votes WHERE id = %s", (vote_id,))


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
