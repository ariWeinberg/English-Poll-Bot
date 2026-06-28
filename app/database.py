from __future__ import annotations

import csv
import io
import json
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from math import ceil
from typing import Any, Iterator

import psycopg
from psycopg.rows import dict_row

from app.auth import hash_password, is_password_hash


DbRow = dict[str, Any]


def _page_bounds(page: int = 1, page_size: int = 25) -> tuple[int, int, int]:
    safe_page = max(page, 1)
    safe_page_size = min(max(page_size, 1), 100)
    return safe_page, safe_page_size, (safe_page - 1) * safe_page_size


def _like(value: str) -> str:
    return f"%{value.strip()}%"


def _coerce_filter_datetime(value: str, *, end: bool = False) -> tuple[str, str]:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("Date filter cannot be blank")
    has_time = "T" in cleaned or " " in cleaned
    normalized = cleaned.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    if end and not has_time:
        return "<", (parsed + timedelta(days=1)).isoformat()
    return ("<=" if end else ">="), parsed.isoformat()


def paginated_response(items: list[DbRow], total: int, page: int, page_size: int) -> dict[str, Any]:
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_next": page * page_size < total,
    }


def _learner_sort_sql(sort_by: str, sort_dir: str) -> str:
    direction = "ASC" if sort_dir.lower() == "asc" else "DESC"
    mapping = {
        "display_name": "display_name",
        "first_activity": "first_activity",
        "latest_activity": "latest_activity",
        "total_counted_votes": "total_counted_votes",
        "total_polls_seen": "total_polls_seen",
        "correct_rate": "correct_rate",
        "correct_count": "correct_count",
        "incorrect_count": "incorrect_count",
        "accepted_changes_count": "accepted_changes_count",
        "ignored_changes_count": "ignored_changes_count",
    }
    column = mapping.get(sort_by, "latest_activity")
    nulls = "NULLS FIRST" if direction == "ASC" else "NULLS LAST"
    if column == "display_name":
        return f"{column} {direction}, voter_wid ASC"
    return f"{column} {direction} {nulls}, display_name ASC, voter_wid ASC"


def _learner_filters(
    *,
    tenant_id: int,
    text_id: int | None = None,
    search: str | None = None,
    voter_wid: str | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[str, list[Any]]:
    where = ["polls.tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if text_id is not None:
        where.append("polls.text_id = %s")
        params.append(text_id)
    if voter_wid:
        where.append("poll_vote_events.voter_wid = %s")
        params.append(voter_wid.strip())
    if search:
        where.append(
            """
            (
                poll_vote_events.voter_wid ILIKE %s
                OR COALESCE(contact_profiles.display_name, poll_vote_events.voter_name, poll_vote_events.phone_number, poll_vote_events.voter_wid) ILIKE %s
                OR COALESCE(poll_vote_events.phone_number, '') ILIKE %s
            )
            """
        )
        like = _like(search)
        params.extend([like, like, like])
    if date_from:
        operator, value = _coerce_filter_datetime(date_from, end=False)
        where.append(f"poll_vote_events.recorded_at {operator} %s")
        params.append(value)
    if date_to:
        operator, value = _coerce_filter_datetime(date_to, end=True)
        where.append(f"poll_vote_events.recorded_at {operator} %s")
        params.append(value)
    return " AND ".join(where), params


def _learner_aggregate_cte(where_sql: str) -> str:
    return f"""
        WITH filtered_events AS (
            SELECT
                poll_vote_events.id,
                poll_vote_events.poll_id,
                poll_vote_events.option_name,
                poll_vote_events.voter_wid,
                poll_vote_events.voter_name,
                poll_vote_events.phone_number,
                poll_vote_events.event_type,
                poll_vote_events.previous_option_name,
                poll_vote_events.accepted,
                poll_vote_events.ignored_reason,
                poll_vote_events.recorded_at,
                polls.text_id,
                polls.question,
                polls.correct_option,
                contact_profiles.display_name AS profile_display_name
            FROM poll_vote_events
            JOIN polls ON polls.id = poll_vote_events.poll_id
            LEFT JOIN contact_profiles
                ON contact_profiles.tenant_id = polls.tenant_id
               AND contact_profiles.voter_wid = poll_vote_events.voter_wid
            WHERE {where_sql}
        ),
        learner_rollup AS (
            SELECT
                voter_wid,
                (ARRAY_AGG(
                    COALESCE(
                        NULLIF(profile_display_name, ''),
                        NULLIF(voter_name, ''),
                        NULLIF(phone_number, ''),
                        voter_wid
                    )
                    ORDER BY recorded_at DESC, id DESC
                ))[1] AS display_name,
                (ARRAY_AGG(
                    COALESCE(
                        NULLIF(phone_number, ''),
                        NULLIF(regexp_replace(split_part(voter_wid, '@', 1), '\\D', '', 'g'), ''),
                        split_part(voter_wid, '@', 1)
                    )
                    ORDER BY recorded_at DESC, id DESC
                ))[1] AS phone_number,
                COUNT(*) FILTER (
                    WHERE accepted = TRUE AND event_type IN ('vote', 'change')
                )::INT AS total_counted_votes,
                COUNT(DISTINCT poll_id)::INT AS total_polls_seen,
                COUNT(*) FILTER (
                    WHERE accepted = TRUE AND event_type IN ('vote', 'change') AND option_name = correct_option
                )::INT AS correct_count,
                COUNT(*) FILTER (
                    WHERE accepted = TRUE AND event_type IN ('vote', 'change') AND option_name <> correct_option
                )::INT AS incorrect_count,
                COUNT(*) FILTER (
                    WHERE accepted = TRUE AND event_type = 'change'
                )::INT AS accepted_changes_count,
                COUNT(*) FILTER (
                    WHERE accepted = FALSE AND event_type = 'change'
                )::INT AS ignored_changes_count,
                MIN(recorded_at) AS first_activity,
                MAX(recorded_at) AS latest_activity
            FROM filtered_events
            GROUP BY voter_wid
        )
    """


def _learner_select_sql() -> str:
    return """
        SELECT
            voter_wid,
            display_name,
            phone_number,
            total_counted_votes,
            total_polls_seen,
            correct_count,
            incorrect_count,
            CASE
                WHEN total_counted_votes > 0
                    THEN ROUND(correct_count::numeric * 100.0 / total_counted_votes, 2)
                ELSE 0
            END AS correct_rate,
            accepted_changes_count,
            ignored_changes_count,
            first_activity,
            latest_activity
        FROM learner_rollup
    """


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


POLL_POOL_TARGET_SIZE = 10
POLL_POOL_REFILL_BATCH_SIZE = 5
DEFAULT_POLL_POOL_THRESHOLD_PERCENT = 80


def normalize_phone_number(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    base = stripped.split("@", 1)[0]
    digits = "".join(ch for ch in base if ch.isdigit())
    return digits or base


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
                poll_pool_threshold_percent INTEGER NOT NULL DEFAULT 80,
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
                poll_pool_threshold_percent INTEGER,
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
                change_window_seconds INTEGER,
                manual_lock BOOLEAN NOT NULL DEFAULT FALSE,
                auto_lock_seconds INTEGER,
                pool_rank INTEGER,
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS poll_votes (
                id SERIAL PRIMARY KEY,
                poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
                option_name TEXT NOT NULL,
                voter_wid TEXT NOT NULL,
                voter_name TEXT,
                phone_number TEXT,
                first_accepted_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (poll_id, voter_wid)
            );

            CREATE TABLE IF NOT EXISTS poll_vote_events (
                id SERIAL PRIMARY KEY,
                poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
                option_name TEXT NOT NULL,
                voter_wid TEXT NOT NULL,
                voter_name TEXT,
                phone_number TEXT,
                event_type TEXT NOT NULL DEFAULT 'vote',
                previous_option_name TEXT,
                accepted BOOLEAN NOT NULL DEFAULT TRUE,
                ignored_reason TEXT,
                recorded_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS contact_profiles (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                voter_wid TEXT NOT NULL,
                phone_number TEXT,
                display_name TEXT,
                updated_at TEXT NOT NULL,
                UNIQUE (tenant_id, voter_wid)
            );

            ALTER TABLE polls ADD COLUMN IF NOT EXISTS change_window_seconds INTEGER;
            ALTER TABLE polls ADD COLUMN IF NOT EXISTS manual_lock BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE polls ADD COLUMN IF NOT EXISTS auto_lock_seconds INTEGER;
            ALTER TABLE tenants ADD COLUMN IF NOT EXISTS poll_pool_threshold_percent INTEGER NOT NULL DEFAULT 80;
            ALTER TABLE texts ADD COLUMN IF NOT EXISTS poll_pool_threshold_percent INTEGER;
            ALTER TABLE polls ADD COLUMN IF NOT EXISTS pool_rank INTEGER;
            ALTER TABLE poll_votes ADD COLUMN IF NOT EXISTS voter_name TEXT;
            ALTER TABLE poll_votes ADD COLUMN IF NOT EXISTS phone_number TEXT;
            ALTER TABLE poll_votes ADD COLUMN IF NOT EXISTS first_accepted_at TEXT;
            ALTER TABLE poll_vote_events ADD COLUMN IF NOT EXISTS event_type TEXT NOT NULL DEFAULT 'vote';
            ALTER TABLE poll_vote_events ADD COLUMN IF NOT EXISTS previous_option_name TEXT;
            ALTER TABLE poll_vote_events ADD COLUMN IF NOT EXISTS voter_name TEXT;
            ALTER TABLE poll_vote_events ADD COLUMN IF NOT EXISTS phone_number TEXT;
            ALTER TABLE poll_vote_events ADD COLUMN IF NOT EXISTS accepted BOOLEAN NOT NULL DEFAULT TRUE;
            ALTER TABLE poll_vote_events ADD COLUMN IF NOT EXISTS ignored_reason TEXT;

            UPDATE poll_votes SET first_accepted_at = updated_at WHERE first_accepted_at IS NULL;
            ALTER TABLE poll_votes ALTER COLUMN first_accepted_at SET NOT NULL;

            CREATE INDEX IF NOT EXISTS idx_tenants_active ON tenants(is_active);
            CREATE INDEX IF NOT EXISTS idx_tenants_username ON tenants(username);
            CREATE INDEX IF NOT EXISTS idx_texts_tenant ON texts(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_polls_tenant ON polls(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_polls_text ON polls(text_id);
            CREATE INDEX IF NOT EXISTS idx_polls_status ON polls(status);
            CREATE INDEX IF NOT EXISTS idx_polls_sent_at ON polls(sent_at);
            CREATE INDEX IF NOT EXISTS idx_polls_greenapi_message_id ON polls(greenapi_message_id);
            CREATE INDEX IF NOT EXISTS idx_polls_text_status_rank ON polls(text_id, status, pool_rank);
            CREATE INDEX IF NOT EXISTS idx_votes_poll_id ON poll_votes(poll_id);
            CREATE INDEX IF NOT EXISTS idx_votes_option_name ON poll_votes(option_name);
            CREATE INDEX IF NOT EXISTS idx_votes_voter_wid ON poll_votes(voter_wid);
            CREATE INDEX IF NOT EXISTS idx_vote_events_poll_id ON poll_vote_events(poll_id);
            CREATE INDEX IF NOT EXISTS idx_vote_events_voter_wid ON poll_vote_events(voter_wid);
            CREATE INDEX IF NOT EXISTS idx_vote_events_recorded_at ON poll_vote_events(recorded_at);
            CREATE INDEX IF NOT EXISTS idx_contact_profiles_tenant_voter ON contact_profiles(tenant_id, voter_wid);
            """
        )
        timestamp = now_iso()
        conn.execute(
            """
            INSERT INTO tenants
                (id, name, username, password, greenapi_api_url, greenapi_id_instance, greenapi_api_token_instance,
                 gemini_api_key, gemini_model, timezone, poll_pool_threshold_percent, summary_enabled, scheduler_enabled,
                 is_active, created_at, updated_at)
            VALUES
                (1, 'Default tenant', 'admin', 'admin', 'https://api.green-api.com', '', '',
                 '', 'gemini-3.5-flash', 'Asia/Jerusalem', 80, TRUE, TRUE,
                 TRUE, %s, %s)
            ON CONFLICT (id) DO NOTHING
            """,
            (timestamp, timestamp),
        )
        existing_tenants = conn.execute("SELECT id, password FROM tenants").fetchall()
        for tenant in existing_tenants:
            password = str(tenant["password"] or "")
            if not password or is_password_hash(password):
                continue
            conn.execute(
                "UPDATE tenants SET password = %s, updated_at = %s WHERE id = %s",
                (hash_password(password), now_iso(), tenant["id"]),
            )
        conn.execute(
            """
            INSERT INTO texts
                (id, tenant_id, title, body, chat_id, morning_time, evening_time,
                 summary_time_morning, summary_time_evening, poll_pool_threshold_percent, enabled, created_at, updated_at)
            VALUES
                (1, 1, 'Default text', '', '', '08:30', '18:00', '08:25', '17:55', NULL, TRUE, %s, %s)
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


def get_tenant_by_username(conn: psycopg.Connection[DbRow], username: str) -> DbRow | None:
    return conn.execute("SELECT * FROM tenants WHERE username = %s", (username.strip(),)).fetchone()


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
            , tenants.poll_pool_threshold_percent AS tenant_poll_pool_threshold_percent
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
            , tenants.poll_pool_threshold_percent AS tenant_poll_pool_threshold_percent
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
            , tenants.poll_pool_threshold_percent AS tenant_poll_pool_threshold_percent
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
    password: str | None,
    greenapi_api_url: str,
    greenapi_id_instance: str,
    greenapi_api_token_instance: str,
    gemini_api_key: str,
    gemini_model: str,
    timezone: str,
    poll_pool_threshold_percent: int = DEFAULT_POLL_POOL_THRESHOLD_PERCENT,
    summary_enabled: bool = True,
    scheduler_enabled: bool = True,
    is_active: bool = True,
) -> int:
    timestamp = now_iso()
    normalized_password = (password or "").strip()
    if tenant_id is None:
        row = conn.execute(
            """
            INSERT INTO tenants (
                name, username, password, greenapi_api_url, greenapi_id_instance, greenapi_api_token_instance,
                gemini_api_key, gemini_model, timezone, poll_pool_threshold_percent, summary_enabled, scheduler_enabled,
                is_active, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                name.strip() or "Tenant",
                username.strip(),
                hash_password(normalized_password),
                greenapi_api_url.strip().rstrip("/"),
                greenapi_id_instance.strip(),
                greenapi_api_token_instance.strip(),
                gemini_api_key.strip(),
                gemini_model.strip() or "gemini-3.5-flash",
                timezone.strip() or "Asia/Jerusalem",
                max(0, min(100, int(poll_pool_threshold_percent))),
                summary_enabled,
                scheduler_enabled,
                is_active,
                timestamp,
                timestamp,
            ),
        ).fetchone()
        return int(row["id"])

    existing = get_tenant(conn, tenant_id)
    if existing is None:
        raise RuntimeError("Tenant not found")
    stored_password = str(existing["password"] or "")
    next_password = hash_password(normalized_password) if normalized_password else stored_password
    conn.execute(
        """
        UPDATE tenants
        SET name = %s, username = %s, password = %s, greenapi_api_url = %s,
            greenapi_id_instance = %s, greenapi_api_token_instance = %s,
            gemini_api_key = %s, gemini_model = %s, timezone = %s, poll_pool_threshold_percent = %s, summary_enabled = %s,
            scheduler_enabled = %s, is_active = %s, updated_at = %s
        WHERE id = %s
        """,
        (
            name.strip() or "Tenant",
            username.strip(),
            next_password,
            greenapi_api_url.strip().rstrip("/"),
            greenapi_id_instance.strip(),
            greenapi_api_token_instance.strip(),
            gemini_api_key.strip(),
            gemini_model.strip() or "gemini-3.5-flash",
            timezone.strip() or "Asia/Jerusalem",
            max(0, min(100, int(poll_pool_threshold_percent))),
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
    poll_pool_threshold_percent: int | None = None,
    enabled: bool = True,
    attachment_name: str | None = None,
    attachment_path: str | None = None,
) -> int:
    timestamp = now_iso()
    if text_id is None:
        row = conn.execute(
            """
            INSERT INTO texts (
                tenant_id, title, body, attachment_name, attachment_path, chat_id,
                morning_time, evening_time, summary_time_morning, summary_time_evening, poll_pool_threshold_percent,
                enabled, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                max(0, min(100, int(poll_pool_threshold_percent))) if poll_pool_threshold_percent is not None else None,
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
            summary_time_evening = %s, poll_pool_threshold_percent = %s, enabled = %s, updated_at = %s
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
            max(0, min(100, int(poll_pool_threshold_percent))) if poll_pool_threshold_percent is not None else None,
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
    status: str = "draft",
    pool_rank: int | None = None,
    change_window_seconds: int | None = None,
    manual_lock: bool = False,
    auto_lock_seconds: int | None = None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO polls (
            tenant_id, text_id, question, options_json, correct_option, explanation, chat_id,
            generated_from_text, status, scheduled_slot, change_window_seconds, manual_lock, auto_lock_seconds, pool_rank, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            status,
            scheduled_slot,
            change_window_seconds,
            manual_lock,
            auto_lock_seconds,
            pool_rank,
            now_iso(),
        ),
    ).fetchone()
    return int(row["id"])


def mark_poll_sent(
    conn: psycopg.Connection[DbRow],
    poll_id: int,
    message_id: str,
    *,
    scheduled_slot: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE polls
        SET greenapi_message_id = %s, status = 'sent', sent_at = %s, scheduled_slot = %s, pool_rank = NULL
        WHERE id = %s
        """,
        (message_id, now_iso(), scheduled_slot, poll_id),
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


def get_text_poll_history(conn: psycopg.Connection[DbRow], *, text_id: int) -> list[DbRow]:
    return conn.execute(
        "SELECT * FROM polls WHERE text_id = %s ORDER BY created_at ASC, id ASC",
        (text_id,),
    ).fetchall()


def list_queued_polls(conn: psycopg.Connection[DbRow], *, text_id: int) -> list[DbRow]:
    return conn.execute(
        """
        SELECT * FROM polls
        WHERE text_id = %s AND status = 'queued'
        ORDER BY pool_rank ASC NULLS LAST, id ASC
        """,
        (text_id,),
    ).fetchall()


def count_queued_polls(conn: psycopg.Connection[DbRow], *, text_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS count FROM polls WHERE text_id = %s AND status = 'queued'",
        (text_id,),
    ).fetchone()
    return int(row["count"])


def get_next_queued_poll(conn: psycopg.Connection[DbRow], *, text_id: int) -> DbRow | None:
    return conn.execute(
        """
        SELECT * FROM polls
        WHERE text_id = %s AND status = 'queued'
        ORDER BY pool_rank ASC NULLS LAST, id ASC
        LIMIT 1
        """,
        (text_id,),
    ).fetchone()


def get_text_pool_tail_rank(conn: psycopg.Connection[DbRow], *, text_id: int) -> int:
    row = conn.execute(
        "SELECT COALESCE(MAX(pool_rank), 0) AS max_rank FROM polls WHERE text_id = %s AND status = 'queued'",
        (text_id,),
    ).fetchone()
    return int(row["max_rank"])


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
    pool_rank: int | None,
    change_window_seconds: int | None,
    manual_lock: bool,
    auto_lock_seconds: int | None,
) -> None:
    conn.execute(
        """
        UPDATE polls
        SET tenant_id = %s, text_id = %s, question = %s, options_json = %s,
            correct_option = %s, explanation = %s, greenapi_message_id = %s,
            chat_id = %s, generated_from_text = %s, status = %s, scheduled_slot = %s,
            sent_at = %s, summary_sent_at = %s, pool_rank = %s, change_window_seconds = %s,
            manual_lock = %s, auto_lock_seconds = %s
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
            pool_rank,
            change_window_seconds,
            manual_lock,
            auto_lock_seconds,
            poll_id,
        ),
    )


def delete_poll(conn: psycopg.Connection[DbRow], poll_id: int) -> None:
    poll = get_poll(conn, poll_id)
    conn.execute("DELETE FROM polls WHERE id = %s", (poll_id,))
    if poll is not None and str(poll.get("status")) == "queued":
        compact_queued_poll_ranks(conn, text_id=int(poll["text_id"]))


def update_poll_pool_ranks(conn: psycopg.Connection[DbRow], *, text_id: int, ordered_poll_ids: list[int]) -> None:
    with conn.cursor() as cursor:
        cursor.executemany(
            "UPDATE polls SET pool_rank = %s WHERE id = %s AND text_id = %s AND status = 'queued'",
            [(rank, poll_id, text_id) for rank, poll_id in enumerate(ordered_poll_ids, start=1)],
        )


def compact_queued_poll_ranks(conn: psycopg.Connection[DbRow], *, text_id: int) -> None:
    update_poll_pool_ranks(
        conn, text_id=text_id, ordered_poll_ids=[int(item["id"]) for item in list_queued_polls(conn, text_id=text_id)]
    )


def reorder_queued_poll(conn: psycopg.Connection[DbRow], *, poll_id: int, pool_rank: int) -> DbRow:
    poll = get_poll(conn, poll_id)
    if poll is None or str(poll.get("status")) != "queued":
        raise RuntimeError("Queued poll not found")
    text_id = int(poll["text_id"])
    ordered_ids = [int(item["id"]) for item in list_queued_polls(conn, text_id=text_id)]
    if poll_id not in ordered_ids:
        raise RuntimeError("Queued poll not found")
    ordered_ids.remove(poll_id)
    insert_at = max(0, min(len(ordered_ids), pool_rank - 1))
    ordered_ids.insert(insert_at, poll_id)
    update_poll_pool_ranks(conn, text_id=text_id, ordered_poll_ids=ordered_ids)
    refreshed = get_poll(conn, poll_id)
    if refreshed is None:
        raise RuntimeError("Queued poll not found")
    return refreshed


def get_effective_poll_pool_threshold_percent(conn: psycopg.Connection[DbRow], *, text_id: int) -> int:
    row = conn.execute(
        """
        SELECT COALESCE(texts.poll_pool_threshold_percent, tenants.poll_pool_threshold_percent, %s) AS threshold
        FROM texts
        JOIN tenants ON tenants.id = texts.tenant_id
        WHERE texts.id = %s
        """,
        (DEFAULT_POLL_POOL_THRESHOLD_PERCENT, text_id),
    ).fetchone()
    if row is None:
        raise RuntimeError("Text not found")
    return max(0, min(100, int(row["threshold"])))


def get_poll_pool_refill_threshold_count(conn: psycopg.Connection[DbRow], *, text_id: int) -> int:
    threshold_percent = get_effective_poll_pool_threshold_percent(conn, text_id=text_id)
    remaining_percent = max(0, 100 - threshold_percent)
    return ceil(POLL_POOL_TARGET_SIZE * remaining_percent / 100)


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


def get_contact_profile(conn: psycopg.Connection[DbRow], *, tenant_id: int, voter_wid: str) -> DbRow | None:
    return conn.execute(
        "SELECT * FROM contact_profiles WHERE tenant_id = %s AND voter_wid = %s",
        (tenant_id, voter_wid.strip()),
    ).fetchone()


def upsert_contact_profile(
    conn: psycopg.Connection[DbRow],
    *,
    tenant_id: int,
    voter_wid: str,
    phone_number: str | None = None,
    display_name: str | None = None,
) -> None:
    conn.execute(
        """
        INSERT INTO contact_profiles (tenant_id, voter_wid, phone_number, display_name, updated_at)
        VALUES (%s, %s, %s, %s, %s)
        ON CONFLICT (tenant_id, voter_wid) DO UPDATE SET
            phone_number = COALESCE(EXCLUDED.phone_number, contact_profiles.phone_number),
            display_name = COALESCE(EXCLUDED.display_name, contact_profiles.display_name),
            updated_at = EXCLUDED.updated_at
        """,
        (
            tenant_id,
            voter_wid.strip(),
            phone_number.strip() if phone_number else None,
            display_name.strip() if display_name else None,
            now_iso(),
        ),
    )


def replace_poll_votes(
    conn: psycopg.Connection[DbRow],
    *,
    poll: DbRow,
    option_voters: dict[str, list[dict[str, str | None]]],
) -> None:
    poll_id = int(poll["id"])
    existing_rows = conn.execute(
        "SELECT option_name, voter_wid, first_accepted_at FROM poll_votes WHERE poll_id = %s",
        (poll_id,),
    ).fetchall()
    current_by_voter = {
        str(row["voter_wid"]): {
            "option_name": str(row["option_name"]),
            "first_accepted_at": str(row["first_accepted_at"]),
        }
        for row in existing_rows
    }
    target_by_voter: dict[str, tuple[str, str | None, str, str]] = {}
    event_rows: list[tuple[int, str, str, str | None, str, str, str | None, bool, str | None, str]] = []
    timestamp = now_iso()
    manual_lock = bool(poll.get("manual_lock"))
    auto_lock_seconds = poll.get("auto_lock_seconds")
    change_window_seconds = poll.get("change_window_seconds")
    sent_at = str(poll.get("sent_at") or "").strip() or None

    def ignored_reason_for(voter_id: str) -> str | None:
        if manual_lock:
            return "manual_lock"
        if auto_lock_seconds is not None and sent_at:
            sent_dt = datetime.fromisoformat(sent_at)
            event_dt = datetime.fromisoformat(timestamp)
            if (event_dt - sent_dt).total_seconds() > int(auto_lock_seconds):
                return "auto_lock_expired"
        if change_window_seconds is not None:
            existing = current_by_voter.get(voter_id)
            if existing is not None:
                first_dt = datetime.fromisoformat(existing["first_accepted_at"])
                event_dt = datetime.fromisoformat(timestamp)
                if (event_dt - first_dt).total_seconds() > int(change_window_seconds):
                    return "change_window_expired"
        return None

    for option_name, voter_records in option_voters.items():
        for voter in voter_records:
            voter_id = str(voter.get("voter_wid") or "").strip()
            option = option_name.strip()
            if not voter_id or not option:
                continue
            voter_name = str(voter.get("voter_name") or "").strip() or None
            phone_number = str(voter.get("phone_number") or "").strip() or normalize_phone_number(voter_id)
            previous = current_by_voter.get(voter_id)
            previous_option = previous["option_name"] if previous else None
            ignored_reason = ignored_reason_for(voter_id)
            accepted = ignored_reason is None
            if accepted:
                first_accepted_at = previous["first_accepted_at"] if previous else timestamp
                target_by_voter[voter_id] = (option, voter_name, phone_number, first_accepted_at)
            if previous_option != option or not accepted:
                event_rows.append(
                    (
                        poll_id,
                        option,
                        voter_id,
                        voter_name,
                        phone_number,
                        "change" if previous_option else "vote",
                        previous_option,
                        accepted,
                        ignored_reason,
                        timestamp,
                    )
                )
    if target_by_voter:
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO poll_votes (poll_id, option_name, voter_wid, voter_name, phone_number, first_accepted_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (poll_id, voter_wid) DO UPDATE SET
                    option_name = EXCLUDED.option_name,
                    voter_name = EXCLUDED.voter_name,
                    phone_number = EXCLUDED.phone_number,
                    updated_at = EXCLUDED.updated_at
                """,
                [
                    (poll_id, option_name, voter_wid, voter_name, phone_number, first_accepted_at, timestamp)
                    for voter_wid, (option_name, voter_name, phone_number, first_accepted_at) in target_by_voter.items()
                ],
            )
    if event_rows:
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO poll_vote_events (
                    poll_id, option_name, voter_wid, voter_name, phone_number, event_type,
                    previous_option_name, accepted, ignored_reason, recorded_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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


def list_poll_vote_status(conn: psycopg.Connection[DbRow], *, poll_id: int) -> list[DbRow]:
    votes = conn.execute(
        """
        SELECT id, poll_id, option_name, voter_wid, voter_name, phone_number, first_accepted_at, updated_at
        FROM poll_votes
        WHERE poll_id = %s
        ORDER BY updated_at DESC, id DESC
        """,
        (poll_id,),
    ).fetchall()
    ignored_events = conn.execute(
        """
        SELECT DISTINCT ON (voter_wid)
            voter_wid, voter_name, phone_number, option_name, previous_option_name,
            event_type, ignored_reason, recorded_at
        FROM poll_vote_events
        WHERE poll_id = %s AND accepted = FALSE
        ORDER BY voter_wid, recorded_at DESC, id DESC
        """,
        (poll_id,),
    ).fetchall()
    ignored_by_voter = {str(row["voter_wid"]): row for row in ignored_events}
    items: list[DbRow] = []
    seen_voters: set[str] = set()
    for vote in votes:
        voter_wid = str(vote["voter_wid"])
        ignored = ignored_by_voter.get(voter_wid)
        items.append(
            {
                "poll_id": poll_id,
                "voter_wid": voter_wid,
                "voter_name": vote["voter_name"],
                "phone_number": vote["phone_number"],
                "counted_option_name": vote["option_name"],
                "first_accepted_at": vote["first_accepted_at"],
                "updated_at": vote["updated_at"],
                "latest_ignored_option_name": ignored["option_name"] if ignored else None,
                "latest_ignored_reason": ignored["ignored_reason"] if ignored else None,
                "latest_ignored_at": ignored["recorded_at"] if ignored else None,
            }
        )
        seen_voters.add(voter_wid)
    for voter_wid, ignored in ignored_by_voter.items():
        if voter_wid in seen_voters:
            continue
        items.append(
            {
                "poll_id": poll_id,
                "voter_wid": voter_wid,
                "voter_name": ignored["voter_name"],
                "phone_number": ignored["phone_number"],
                "counted_option_name": None,
                "first_accepted_at": None,
                "updated_at": None,
                "latest_ignored_option_name": ignored["option_name"],
                "latest_ignored_reason": ignored["ignored_reason"],
                "latest_ignored_at": ignored["recorded_at"],
            }
        )
    return items


def list_learners_page(
    conn: psycopg.Connection[DbRow],
    *,
    tenant_id: int,
    page: int = 1,
    page_size: int = 25,
    text_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    search: str | None = None,
    sort_by: str = "latest_activity",
    sort_dir: str = "desc",
) -> dict[str, Any]:
    page, page_size, offset = _page_bounds(page, page_size)
    where_sql, params = _learner_filters(
        tenant_id=tenant_id,
        text_id=text_id,
        search=search,
        date_from=date_from,
        date_to=date_to,
    )
    aggregate_cte = _learner_aggregate_cte(where_sql)
    total = conn.execute(
        f"""
        {aggregate_cte}
        SELECT COUNT(*) AS count
        FROM learner_rollup
        """,
        params,
    ).fetchone()["count"]
    items = conn.execute(
        f"""
        {aggregate_cte}
        {_learner_select_sql()}
        ORDER BY {_learner_sort_sql(sort_by, sort_dir)}
        LIMIT %s OFFSET %s
        """,
        [*params, page_size, offset],
    ).fetchall()
    return paginated_response(items, int(total), page, page_size)


def get_learner_summary(
    conn: psycopg.Connection[DbRow],
    *,
    tenant_id: int,
    voter_wid: str,
    text_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> DbRow | None:
    where_sql, params = _learner_filters(
        tenant_id=tenant_id,
        text_id=text_id,
        voter_wid=voter_wid,
        date_from=date_from,
        date_to=date_to,
    )
    row = conn.execute(
        f"""
        {_learner_aggregate_cte(where_sql)}
        {_learner_select_sql()}
        LIMIT 1
        """,
        params,
    ).fetchone()
    return row


def list_learner_history(
    conn: psycopg.Connection[DbRow],
    *,
    tenant_id: int,
    voter_wid: str,
    text_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
    limit: int = 25,
) -> list[DbRow]:
    safe_limit = min(max(limit, 1), 100)
    where_sql, params = _learner_filters(
        tenant_id=tenant_id,
        text_id=text_id,
        voter_wid=voter_wid,
        date_from=date_from,
        date_to=date_to,
    )
    return conn.execute(
        f"""
        SELECT
            poll_vote_events.id,
            poll_vote_events.poll_id,
            polls.text_id,
            polls.question,
            polls.correct_option,
            poll_vote_events.voter_wid,
            COALESCE(
                contact_profiles.display_name,
                poll_vote_events.voter_name,
                poll_vote_events.phone_number,
                poll_vote_events.voter_wid
            ) AS display_name,
            COALESCE(
                poll_vote_events.phone_number,
                NULLIF(regexp_replace(split_part(poll_vote_events.voter_wid, '@', 1), '\\D', '', 'g'), ''),
                split_part(poll_vote_events.voter_wid, '@', 1)
            ) AS phone_number,
            NULLIF(poll_vote_events.option_name, '') AS selected_option_name,
            poll_vote_events.previous_option_name,
            poll_vote_events.event_type,
            poll_vote_events.accepted,
            poll_vote_events.ignored_reason,
            poll_vote_events.recorded_at
        FROM poll_vote_events
        JOIN polls ON polls.id = poll_vote_events.poll_id
        LEFT JOIN contact_profiles
            ON contact_profiles.tenant_id = polls.tenant_id
           AND contact_profiles.voter_wid = poll_vote_events.voter_wid
        WHERE {where_sql}
        ORDER BY poll_vote_events.recorded_at DESC, poll_vote_events.id DESC
        LIMIT %s
        """,
        [*params, safe_limit],
    ).fetchall()


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
    voter_name: str | None = None,
    phone_number: str | None = None,
    recorded_at: str | None = None,
    event_type: str = "vote",
    previous_option_name: str | None = None,
    accepted: bool = True,
    ignored_reason: str | None = None,
) -> int:
    row = conn.execute(
        """
        INSERT INTO poll_vote_events (
            poll_id, option_name, voter_wid, voter_name, phone_number, event_type,
            previous_option_name, accepted, ignored_reason, recorded_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            poll_id,
            option_name.strip(),
            voter_wid.strip(),
            voter_name.strip() if voter_name else None,
            (phone_number.strip() if phone_number else normalize_phone_number(voter_wid)),
            event_type.strip() or "vote",
            previous_option_name.strip() if previous_option_name else None,
            accepted,
            ignored_reason.strip() if ignored_reason else None,
            recorded_at or now_iso(),
        ),
    ).fetchone()
    return int(row["id"])


def create_poll_vote(
    conn: psycopg.Connection[DbRow],
    *,
    poll_id: int,
    option_name: str,
    voter_wid: str,
    voter_name: str | None = None,
    phone_number: str | None = None,
) -> int:
    timestamp = now_iso()
    existing = conn.execute(
        "SELECT option_name FROM poll_votes WHERE poll_id = %s AND voter_wid = %s",
        (poll_id, voter_wid.strip()),
    ).fetchone()
    row = conn.execute(
        """
        INSERT INTO poll_votes (poll_id, option_name, voter_wid, voter_name, phone_number, first_accepted_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (poll_id, voter_wid) DO UPDATE SET
            option_name = EXCLUDED.option_name,
            voter_name = EXCLUDED.voter_name,
            phone_number = EXCLUDED.phone_number,
            updated_at = EXCLUDED.updated_at
        RETURNING id
        """,
        (
            poll_id,
            option_name.strip(),
            voter_wid.strip(),
            voter_name.strip() if voter_name else None,
            phone_number.strip() if phone_number else normalize_phone_number(voter_wid),
            timestamp,
            timestamp,
        ),
    ).fetchone()
    previous_option = str(existing["option_name"]) if existing else None
    if previous_option != option_name.strip():
        record_poll_vote_event(
            conn,
            poll_id=poll_id,
            option_name=option_name,
            voter_wid=voter_wid,
            voter_name=voter_name,
            phone_number=phone_number,
            recorded_at=timestamp,
            event_type="change" if previous_option else "vote",
            previous_option_name=previous_option,
        )
    return int(row["id"])


def update_poll_vote(
    conn: psycopg.Connection[DbRow],
    *,
    vote_id: int,
    poll_id: int,
    option_name: str,
    voter_wid: str,
    voter_name: str | None = None,
    phone_number: str | None = None,
) -> None:
    timestamp = now_iso()
    existing = conn.execute("SELECT option_name FROM poll_votes WHERE id = %s", (vote_id,)).fetchone()
    conn.execute(
        """
        UPDATE poll_votes
        SET poll_id = %s, option_name = %s, voter_wid = %s, voter_name = %s, phone_number = %s, updated_at = %s
        WHERE id = %s
        """,
        (
            poll_id,
            option_name.strip(),
            voter_wid.strip(),
            voter_name.strip() if voter_name else None,
            phone_number.strip() if phone_number else normalize_phone_number(voter_wid),
            timestamp,
            vote_id,
        ),
    )
    previous_option = str(existing["option_name"]) if existing else None
    if previous_option != option_name.strip():
        record_poll_vote_event(
            conn,
            poll_id=poll_id,
            option_name=option_name,
            voter_wid=voter_wid,
            voter_name=voter_name,
            phone_number=phone_number,
            recorded_at=timestamp,
            event_type="change" if previous_option else "vote",
            previous_option_name=previous_option,
        )


def delete_poll_vote(conn: psycopg.Connection[DbRow], vote_id: int) -> None:
    existing = conn.execute(
        "SELECT poll_id, option_name, voter_wid, voter_name, phone_number FROM poll_votes WHERE id = %s",
        (vote_id,),
    ).fetchone()
    conn.execute("DELETE FROM poll_votes WHERE id = %s", (vote_id,))
    if existing is not None:
        record_poll_vote_event(
            conn,
            poll_id=int(existing["poll_id"]),
            option_name="",
            voter_wid=str(existing["voter_wid"]),
            voter_name=str(existing["voter_name"]) if existing["voter_name"] else None,
            phone_number=str(existing["phone_number"]) if existing["phone_number"] else None,
            event_type="unvote",
            previous_option_name=str(existing["option_name"]),
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


def all_poll_stats(
    conn: psycopg.Connection[DbRow], limit: int = 25, tenant_id: int | None = None
) -> list[dict[str, Any]]:
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
