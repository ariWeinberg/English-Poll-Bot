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
        "assigned_polls_count": "assigned_polls_count",
        "responded_polls_count": "responded_polls_count",
        "missed_polls_count": "missed_polls_count",
        "response_rate": "response_rate",
    }
    column = mapping.get(sort_by, "latest_activity")
    nulls = "NULLS FIRST" if direction == "ASC" else "NULLS LAST"
    if column == "display_name":
        return f"{column} {direction}, voter_wid ASC"
    return f"{column} {direction} {nulls}, display_name ASC, voter_wid ASC"


def _learner_poll_filters(
    *,
    tenant_id: int,
    text_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> tuple[str, list[Any]]:
    where = ["polls.tenant_id = %s"]
    params: list[Any] = [tenant_id]
    scoped_timestamp = "COALESCE(polls.sent_at, polls.created_at)"
    if text_id is not None:
        where.append("polls.text_id = %s")
        params.append(text_id)
    if date_from:
        operator, value = _coerce_filter_datetime(date_from, end=False)
        where.append(f"{scoped_timestamp} {operator} %s")
        params.append(value)
    if date_to:
        operator, value = _coerce_filter_datetime(date_to, end=True)
        where.append(f"{scoped_timestamp} {operator} %s")
        params.append(value)
    return " AND ".join(where), params


def _learner_aggregate_cte(where_sql: str, *, search: str | None = None, voter_wid: str | None = None) -> str:
    final_filters = ["1 = 1"]
    if voter_wid:
        final_filters.append("voter_wid = %s")
    if search:
        final_filters.append(
            """
            (
                voter_wid ILIKE %s
                OR display_name ILIKE %s
                OR phone_number ILIKE %s
            )
            """
        )
    final_where_sql = " AND ".join(final_filters)
    return f"""
        WITH filtered_polls AS (
            SELECT
                polls.id,
                polls.tenant_id,
                polls.text_id,
                polls.question,
                polls.correct_option,
                polls.sent_at,
                polls.recipient_snapshot_source,
                polls.recipient_snapshot_synced_at
            FROM polls
            WHERE {where_sql}
        ),
        assignment_rollup AS (
            SELECT
                poll_recipient_snapshots.voter_wid,
                (ARRAY_AGG(
                    COALESCE(
                        NULLIF(poll_recipient_snapshots.display_name, ''),
                        NULLIF(poll_recipient_snapshots.phone_number, ''),
                        poll_recipient_snapshots.voter_wid
                    )
                    ORDER BY filtered_polls.sent_at DESC NULLS LAST, poll_recipient_snapshots.created_at DESC
                ))[1] AS display_name,
                (ARRAY_AGG(
                    COALESCE(
                        NULLIF(poll_recipient_snapshots.phone_number, ''),
                        NULLIF(regexp_replace(split_part(poll_recipient_snapshots.voter_wid, '@', 1), '\\D', '', 'g'), ''),
                        split_part(poll_recipient_snapshots.voter_wid, '@', 1)
                    )
                    ORDER BY filtered_polls.sent_at DESC NULLS LAST, poll_recipient_snapshots.created_at DESC
                ))[1] AS phone_number,
                COUNT(DISTINCT poll_recipient_snapshots.poll_id)::INT AS assigned_polls_count,
                MIN(filtered_polls.sent_at) AS first_assigned_at,
                MAX(filtered_polls.sent_at) AS latest_assigned_at
            FROM poll_recipient_snapshots
            JOIN filtered_polls ON filtered_polls.id = poll_recipient_snapshots.poll_id
            GROUP BY poll_recipient_snapshots.voter_wid
        ),
        response_rollup AS (
            SELECT
                poll_votes.voter_wid,
                (ARRAY_AGG(
                    COALESCE(
                        NULLIF(contact_profiles.display_name, ''),
                        NULLIF(poll_votes.voter_name, ''),
                        NULLIF(poll_votes.phone_number, ''),
                        poll_votes.voter_wid
                    )
                    ORDER BY filtered_polls.sent_at DESC NULLS LAST, poll_votes.updated_at DESC
                ))[1] AS display_name,
                (ARRAY_AGG(
                    COALESCE(
                        NULLIF(poll_votes.phone_number, ''),
                        NULLIF(regexp_replace(split_part(poll_votes.voter_wid, '@', 1), '\\D', '', 'g'), ''),
                        split_part(poll_votes.voter_wid, '@', 1)
                    )
                    ORDER BY filtered_polls.sent_at DESC NULLS LAST, poll_votes.updated_at DESC
                ))[1] AS phone_number,
                COUNT(DISTINCT poll_votes.poll_id)::INT AS responded_polls_count,
                COUNT(*)::INT AS total_counted_votes,
                COUNT(*) FILTER (
                    WHERE poll_votes.option_name = filtered_polls.correct_option
                )::INT AS correct_count,
                COUNT(*) FILTER (
                    WHERE poll_votes.option_name <> filtered_polls.correct_option
                )::INT AS incorrect_count,
                MIN(poll_votes.first_accepted_at) AS first_response_at,
                MAX(poll_votes.updated_at) AS latest_response_at
            FROM poll_votes
            JOIN filtered_polls ON filtered_polls.id = poll_votes.poll_id
            LEFT JOIN contact_profiles
                ON contact_profiles.tenant_id = filtered_polls.tenant_id
               AND contact_profiles.voter_wid = poll_votes.voter_wid
            GROUP BY poll_votes.voter_wid
        ),
        change_rollup AS (
            SELECT
                poll_vote_events.voter_wid,
                (ARRAY_AGG(
                    COALESCE(
                        NULLIF(contact_profiles.display_name, ''),
                        NULLIF(poll_vote_events.voter_name, ''),
                        NULLIF(poll_vote_events.phone_number, ''),
                        poll_vote_events.voter_wid
                    )
                    ORDER BY poll_vote_events.recorded_at DESC, poll_vote_events.id DESC
                ))[1] AS display_name,
                (ARRAY_AGG(
                    COALESCE(
                        NULLIF(poll_vote_events.phone_number, ''),
                        NULLIF(regexp_replace(split_part(poll_vote_events.voter_wid, '@', 1), '\\D', '', 'g'), ''),
                        split_part(poll_vote_events.voter_wid, '@', 1)
                    )
                    ORDER BY poll_vote_events.recorded_at DESC, poll_vote_events.id DESC
                ))[1] AS phone_number,
                COUNT(*) FILTER (
                    WHERE poll_vote_events.accepted = TRUE AND poll_vote_events.event_type = 'change'
                )::INT AS accepted_changes_count,
                COUNT(*) FILTER (
                    WHERE poll_vote_events.accepted = FALSE AND poll_vote_events.event_type = 'change'
                )::INT AS ignored_changes_count,
                MIN(poll_vote_events.recorded_at) AS first_event_at,
                MAX(poll_vote_events.recorded_at) AS latest_event_at
            FROM poll_vote_events
            JOIN filtered_polls ON filtered_polls.id = poll_vote_events.poll_id
            LEFT JOIN contact_profiles
                ON contact_profiles.tenant_id = filtered_polls.tenant_id
               AND contact_profiles.voter_wid = poll_vote_events.voter_wid
            GROUP BY poll_vote_events.voter_wid
        ),
        learners AS (
            SELECT voter_wid FROM assignment_rollup
            UNION
            SELECT voter_wid FROM response_rollup
            UNION
            SELECT voter_wid FROM change_rollup
        ),
        learner_rollup AS (
            SELECT
                learners.voter_wid,
                COALESCE(
                    assignment_rollup.display_name,
                    response_rollup.display_name,
                    change_rollup.display_name,
                    learners.voter_wid
                ) AS display_name,
                COALESCE(
                    assignment_rollup.phone_number,
                    response_rollup.phone_number,
                    change_rollup.phone_number,
                    NULLIF(regexp_replace(split_part(learners.voter_wid, '@', 1), '\\D', '', 'g'), ''),
                    split_part(learners.voter_wid, '@', 1)
                ) AS phone_number,
                COALESCE(response_rollup.total_counted_votes, 0) AS total_counted_votes,
                COALESCE(response_rollup.responded_polls_count, 0) AS total_polls_seen,
                COALESCE(response_rollup.correct_count, 0) AS correct_count,
                COALESCE(response_rollup.incorrect_count, 0) AS incorrect_count,
                COALESCE(change_rollup.accepted_changes_count, 0) AS accepted_changes_count,
                COALESCE(change_rollup.ignored_changes_count, 0) AS ignored_changes_count,
                COALESCE(assignment_rollup.assigned_polls_count, 0) AS assigned_polls_count,
                COALESCE(response_rollup.responded_polls_count, 0) AS responded_polls_count,
                GREATEST(
                    COALESCE(assignment_rollup.assigned_polls_count, 0) - COALESCE(response_rollup.responded_polls_count, 0),
                    0
                ) AS missed_polls_count,
                CASE
                    WHEN COALESCE(assignment_rollup.assigned_polls_count, 0) > 0
                        THEN ROUND(
                            COALESCE(response_rollup.responded_polls_count, 0)::numeric * 100.0
                            / assignment_rollup.assigned_polls_count,
                            2
                        )
                    ELSE 0
                END AS response_rate,
                LEAST(
                    COALESCE(assignment_rollup.first_assigned_at, '9999-12-31T00:00:00+00:00'),
                    COALESCE(response_rollup.first_response_at, '9999-12-31T00:00:00+00:00'),
                    COALESCE(change_rollup.first_event_at, '9999-12-31T00:00:00+00:00')
                ) AS first_activity,
                GREATEST(
                    COALESCE(assignment_rollup.latest_assigned_at, '0001-01-01T00:00:00+00:00'),
                    COALESCE(response_rollup.latest_response_at, '0001-01-01T00:00:00+00:00'),
                    COALESCE(change_rollup.latest_event_at, '0001-01-01T00:00:00+00:00')
                ) AS latest_activity
            FROM learners
            LEFT JOIN assignment_rollup ON assignment_rollup.voter_wid = learners.voter_wid
            LEFT JOIN response_rollup ON response_rollup.voter_wid = learners.voter_wid
            LEFT JOIN change_rollup ON change_rollup.voter_wid = learners.voter_wid
        ),
        filtered_learners AS (
            SELECT *
            FROM learner_rollup
            WHERE {final_where_sql}
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
            assigned_polls_count,
            responded_polls_count,
            missed_polls_count,
            response_rate,
            NULLIF(first_activity, '9999-12-31T00:00:00+00:00') AS first_activity,
            NULLIF(latest_activity, '0001-01-01T00:00:00+00:00') AS latest_activity
        FROM filtered_learners
    """


def _learner_segment_condition(segment: str) -> str:
    if segment == "needs_attention":
        return "assigned_polls_count > 0 AND (missed_polls_count > 0 OR response_rate < 50)"
    if segment == "inactive":
        return "assigned_polls_count > 0 AND responded_polls_count = 0"
    if segment == "engaged":
        return "assigned_polls_count > 0 AND response_rate >= 80 AND missed_polls_count = 0"
    return "1 = 1"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


POLL_POOL_TARGET_SIZE = 10
POLL_POOL_REFILL_BATCH_SIZE = 5
DEFAULT_POLL_POOL_THRESHOLD_PERCENT = 80
SCHEDULE_RULE_TYPES = {"daily_time", "weekday_time", "month_date_time", "random_window"}
SCHEDULE_DELIVERY_TYPES = {"poll", "summary"}
SCHEDULE_COUNT_MODES = {"fixed", "range"}
CHAT_POLICIES = {"allow", "neutral", "block"}
LEGACY_TEXT_TIMING_MIGRATION_CUTOFF_KEY = "migration.legacy_text_timing_cutoff"


def normalize_phone_number(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    base = stripped.split("@", 1)[0]
    digits = "".join(ch for ch in base if ch.isdigit())
    return digits or base


def _parse_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if not isinstance(value, str) or not value.strip():
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return parsed if isinstance(parsed, list) else []


def _validate_hhmm(value: str | None, *, field: str) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        datetime.strptime(cleaned, "%H:%M")
    except ValueError as exc:
        raise ValueError(f"{field} must use HH:MM format") from exc
    return cleaned


def _normalize_schedule_rule_input(
    *,
    name: str | None = None,
    delivery_type: str,
    rule_type: str,
    enabled: bool = True,
    time: str | None = None,
    weekdays: list[int] | None = None,
    month_dates: list[int] | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    count_mode: str = "fixed",
    count_value: int | None = 1,
    count_min: int | None = None,
    count_max: int | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    normalized_delivery_type = delivery_type.strip()
    normalized_rule_type = rule_type.strip()
    normalized_count_mode = count_mode.strip()
    if normalized_delivery_type not in SCHEDULE_DELIVERY_TYPES:
        raise ValueError("delivery_type must be poll or summary")
    if normalized_rule_type not in SCHEDULE_RULE_TYPES:
        raise ValueError("rule_type is invalid")
    if normalized_count_mode not in SCHEDULE_COUNT_MODES:
        raise ValueError("count_mode must be fixed or range")

    normalized_time = _validate_hhmm(time, field="time")
    normalized_window_start = _validate_hhmm(window_start, field="window_start")
    normalized_window_end = _validate_hhmm(window_end, field="window_end")

    normalized_weekdays: list[int] = []
    if weekdays:
        normalized_weekdays = sorted({int(day) for day in weekdays})
        if any(day < 0 or day > 6 for day in normalized_weekdays):
            raise ValueError("weekdays must use values from 0 to 6")

    normalized_month_dates: list[int] = []
    if month_dates:
        normalized_month_dates = sorted({int(day) for day in month_dates})
        if any(day < 1 or day > 31 for day in normalized_month_dates):
            raise ValueError("month_dates must use values from 1 to 31")

    if normalized_rule_type == "daily_time":
        if normalized_time is None:
            raise ValueError("time is required for daily_time rules")
    elif normalized_rule_type == "weekday_time":
        if normalized_time is None:
            raise ValueError("time is required for weekday_time rules")
        if not normalized_weekdays:
            raise ValueError("weekdays are required for weekday_time rules")
    elif normalized_rule_type == "month_date_time":
        if normalized_time is None:
            raise ValueError("time is required for month_date_time rules")
        if not normalized_month_dates:
            raise ValueError("month_dates are required for month_date_time rules")
    elif normalized_rule_type == "random_window":
        if normalized_window_start is None or normalized_window_end is None:
            raise ValueError("window_start and window_end are required for random_window rules")
        if normalized_window_start >= normalized_window_end:
            raise ValueError("window_end must be later than window_start")

    normalized_count_value = int(count_value) if count_value is not None else None
    normalized_count_min = int(count_min) if count_min is not None else None
    normalized_count_max = int(count_max) if count_max is not None else None
    if normalized_count_mode == "fixed":
        if normalized_count_value is None or normalized_count_value < 1:
            raise ValueError("count_value must be at least 1")
    else:
        if normalized_count_min is None or normalized_count_max is None:
            raise ValueError("count_min and count_max are required for range count mode")
        if normalized_count_min < 1 or normalized_count_max < 1:
            raise ValueError("count range must be at least 1")
        if normalized_count_min > normalized_count_max:
            raise ValueError("count_min must be less than or equal to count_max")

    return {
        "name": name.strip() if name and name.strip() else None,
        "delivery_type": normalized_delivery_type,
        "rule_type": normalized_rule_type,
        "enabled": bool(enabled),
        "time": normalized_time,
        "weekdays": normalized_weekdays,
        "month_dates": normalized_month_dates,
        "window_start": normalized_window_start,
        "window_end": normalized_window_end,
        "count_mode": normalized_count_mode,
        "count_value": normalized_count_value if normalized_count_mode == "fixed" else None,
        "count_min": normalized_count_min if normalized_count_mode == "range" else None,
        "count_max": normalized_count_max if normalized_count_mode == "range" else None,
        "label": label.strip() if label and label.strip() else None,
    }


def _default_schedule_rule_name(
    *,
    delivery_type: str,
    rule_type: str,
    time: str | None,
    window_start: str | None,
    window_end: str | None,
    label: str | None,
) -> str:
    if label:
        return label
    delivery_label = "Poll" if delivery_type == "poll" else "Summary"
    if rule_type == "random_window":
        return f"{delivery_label} {window_start or '00:00'}-{window_end or '00:01'}"
    return f"{delivery_label} {time or '00:00'}"


def _rule_name_for_text(text_title: str, rule: dict[str, Any]) -> str:
    base = _default_schedule_rule_name(
        delivery_type=str(rule["delivery_type"]),
        rule_type=str(rule["rule_type"]),
        time=rule.get("time"),
        window_start=rule.get("window_start"),
        window_end=rule.get("window_end"),
        label=rule.get("label"),
    )
    return f"{text_title.strip() or 'Text'} - {base}"


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

            CREATE TABLE IF NOT EXISTS text_schedule_rules (
                id SERIAL PRIMARY KEY,
                text_id INTEGER NOT NULL REFERENCES texts(id) ON DELETE CASCADE,
                delivery_type TEXT NOT NULL,
                rule_type TEXT NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                time TEXT,
                weekdays_json TEXT NOT NULL DEFAULT '[]',
                month_dates_json TEXT NOT NULL DEFAULT '[]',
                window_start TEXT,
                window_end TEXT,
                count_mode TEXT NOT NULL DEFAULT 'fixed',
                count_value INTEGER,
                count_min INTEGER,
                count_max INTEGER,
                label TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS schedule_rules (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                name TEXT NOT NULL,
                delivery_type TEXT NOT NULL,
                rule_type TEXT NOT NULL,
                enabled BOOLEAN NOT NULL DEFAULT TRUE,
                time TEXT,
                weekdays_json TEXT NOT NULL DEFAULT '[]',
                month_dates_json TEXT NOT NULL DEFAULT '[]',
                window_start TEXT,
                window_end TEXT,
                count_mode TEXT NOT NULL DEFAULT 'fixed',
                count_value INTEGER,
                count_min INTEGER,
                count_max INTEGER,
                label TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS text_schedule_rule_assignments (
                id SERIAL PRIMARY KEY,
                text_id INTEGER NOT NULL REFERENCES texts(id) ON DELETE CASCADE,
                rule_id INTEGER NOT NULL REFERENCES schedule_rules(id) ON DELETE CASCADE,
                created_at TEXT NOT NULL,
                UNIQUE (text_id, rule_id)
            );

            CREATE TABLE IF NOT EXISTS text_schedule_rule_random_plans (
                id SERIAL PRIMARY KEY,
                text_id INTEGER NOT NULL REFERENCES texts(id) ON DELETE CASCADE,
                rule_id INTEGER NOT NULL REFERENCES schedule_rules(id) ON DELETE CASCADE,
                local_date TEXT NOT NULL,
                planned_times_json TEXT NOT NULL DEFAULT '[]',
                executed_times_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (text_id, rule_id, local_date)
            );

            CREATE TABLE IF NOT EXISTS app_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL DEFAULT ''
            );

            CREATE TABLE IF NOT EXISTS scheduled_send_attempts (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                text_id INTEGER NOT NULL REFERENCES texts(id) ON DELETE CASCADE,
                rule_id INTEGER NOT NULL REFERENCES schedule_rules(id) ON DELETE CASCADE,
                delivery_type TEXT NOT NULL,
                scheduled_slot TEXT NOT NULL,
                local_date TEXT NOT NULL,
                timezone TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'started',
                poll_id INTEGER REFERENCES polls(id) ON DELETE SET NULL,
                summary_count INTEGER,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS incoming_webhooks (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                provider TEXT NOT NULL,
                endpoint_path TEXT NOT NULL,
                type_webhook TEXT,
                message_type TEXT,
                greenapi_message_id TEXT,
                poll_id INTEGER,
                decision_status TEXT,
                decision_reason TEXT,
                payload_json TEXT NOT NULL,
                received_at TEXT NOT NULL,
                processed_at TEXT,
                error TEXT
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

            CREATE TABLE IF NOT EXISTS chat_participants (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                chat_id TEXT NOT NULL,
                voter_wid TEXT NOT NULL,
                phone_number TEXT,
                display_name TEXT,
                is_active_in_chat BOOLEAN NOT NULL DEFAULT TRUE,
                excluded_from_coverage BOOLEAN NOT NULL DEFAULT FALSE,
                last_synced_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (tenant_id, chat_id, voter_wid)
            );

            CREATE TABLE IF NOT EXISTS tenant_group_chats (
                id SERIAL PRIMARY KEY,
                tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                chat_id TEXT NOT NULL,
                name TEXT NOT NULL,
                policy TEXT NOT NULL DEFAULT 'neutral',
                last_synced_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (tenant_id, chat_id)
            );

            CREATE TABLE IF NOT EXISTS poll_recipient_snapshots (
                id SERIAL PRIMARY KEY,
                poll_id INTEGER NOT NULL REFERENCES polls(id) ON DELETE CASCADE,
                tenant_id INTEGER NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
                chat_id TEXT NOT NULL,
                voter_wid TEXT NOT NULL,
                phone_number TEXT,
                display_name TEXT,
                created_at TEXT NOT NULL,
                UNIQUE (poll_id, voter_wid)
            );

            ALTER TABLE polls ADD COLUMN IF NOT EXISTS change_window_seconds INTEGER;
            ALTER TABLE polls ADD COLUMN IF NOT EXISTS manual_lock BOOLEAN NOT NULL DEFAULT FALSE;
            ALTER TABLE polls ADD COLUMN IF NOT EXISTS auto_lock_seconds INTEGER;
            ALTER TABLE tenants ADD COLUMN IF NOT EXISTS poll_pool_threshold_percent INTEGER NOT NULL DEFAULT 80;
            ALTER TABLE texts ADD COLUMN IF NOT EXISTS poll_pool_threshold_percent INTEGER;
            ALTER TABLE polls ADD COLUMN IF NOT EXISTS pool_rank INTEGER;
            ALTER TABLE polls ADD COLUMN IF NOT EXISTS recipient_snapshot_source TEXT;
            ALTER TABLE polls ADD COLUMN IF NOT EXISTS recipient_snapshot_synced_at TEXT;
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
            CREATE INDEX IF NOT EXISTS idx_text_schedule_rules_text ON text_schedule_rules(text_id);
            CREATE INDEX IF NOT EXISTS idx_text_schedule_rules_enabled ON text_schedule_rules(text_id, enabled);
            CREATE INDEX IF NOT EXISTS idx_schedule_rules_tenant ON schedule_rules(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_schedule_rules_enabled ON schedule_rules(tenant_id, enabled);
            CREATE INDEX IF NOT EXISTS idx_text_rule_assignments_text ON text_schedule_rule_assignments(text_id);
            CREATE INDEX IF NOT EXISTS idx_text_rule_assignments_rule ON text_schedule_rule_assignments(rule_id);
            CREATE INDEX IF NOT EXISTS idx_text_schedule_rule_random_plans_rule_date
                ON text_schedule_rule_random_plans(text_id, rule_id, local_date);
            CREATE INDEX IF NOT EXISTS idx_scheduled_send_attempts_slot
                ON scheduled_send_attempts(text_id, rule_id, local_date, scheduled_slot);
            CREATE INDEX IF NOT EXISTS idx_scheduled_send_attempts_status
                ON scheduled_send_attempts(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_incoming_webhooks_tenant_received
                ON incoming_webhooks(tenant_id, received_at DESC);
            CREATE INDEX IF NOT EXISTS idx_incoming_webhooks_status
                ON incoming_webhooks(decision_status);
            CREATE INDEX IF NOT EXISTS idx_incoming_webhooks_reason
                ON incoming_webhooks(decision_reason);
            CREATE INDEX IF NOT EXISTS idx_incoming_webhooks_greenapi_message_id
                ON incoming_webhooks(greenapi_message_id);
            CREATE INDEX IF NOT EXISTS idx_incoming_webhooks_poll_id
                ON incoming_webhooks(poll_id);
            CREATE INDEX IF NOT EXISTS idx_incoming_webhooks_type_webhook
                ON incoming_webhooks(type_webhook);
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
            CREATE INDEX IF NOT EXISTS idx_chat_participants_tenant_chat ON chat_participants(tenant_id, chat_id);
            CREATE INDEX IF NOT EXISTS idx_chat_participants_tenant_chat_active
                ON chat_participants(tenant_id, chat_id, is_active_in_chat, excluded_from_coverage);
            CREATE INDEX IF NOT EXISTS idx_tenant_group_chats_tenant ON tenant_group_chats(tenant_id);
            CREATE INDEX IF NOT EXISTS idx_tenant_group_chats_policy ON tenant_group_chats(tenant_id, policy);
            CREATE INDEX IF NOT EXISTS idx_poll_recipient_snapshots_poll ON poll_recipient_snapshots(poll_id);
            CREATE INDEX IF NOT EXISTS idx_poll_recipient_snapshots_tenant_voter
                ON poll_recipient_snapshots(tenant_id, voter_wid);
            """
        )
        timestamp = now_iso()
        tenant_count = conn.execute("SELECT COUNT(*) AS count FROM tenants").fetchone()
        if int(tenant_count["count"]) == 0:
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
        _migrate_legacy_text_schedule_rules(conn)
        _migrate_text_owned_rules_to_shared_rules(conn)
        conn.execute("SELECT setval(pg_get_serial_sequence('tenants', 'id'), COALESCE(MAX(id), 1)) FROM tenants")
        conn.execute("SELECT setval(pg_get_serial_sequence('texts', 'id'), COALESCE(MAX(id), 1)) FROM texts")
        conn.execute(
            "SELECT setval(pg_get_serial_sequence('tenant_group_chats', 'id'), COALESCE(MAX(id), 1)) FROM tenant_group_chats"
        )
        conn.execute(
            "SELECT setval(pg_get_serial_sequence('text_schedule_rules', 'id'), COALESCE(MAX(id), 1)) FROM text_schedule_rules"
        )
        conn.execute(
            "SELECT setval(pg_get_serial_sequence('schedule_rules', 'id'), COALESCE(MAX(id), 1)) FROM schedule_rules"
        )
        conn.execute(
            "SELECT setval(pg_get_serial_sequence('text_schedule_rule_assignments', 'id'), COALESCE(MAX(id), 1)) FROM text_schedule_rule_assignments"
        )
        conn.execute(
            "SELECT setval(pg_get_serial_sequence('incoming_webhooks', 'id'), COALESCE(MAX(id), 1)) FROM incoming_webhooks"
        )


def _migrate_legacy_text_schedule_rules(conn: psycopg.Connection[DbRow]) -> None:
    cutoff = get_app_config(conn, key=LEGACY_TEXT_TIMING_MIGRATION_CUTOFF_KEY)
    if cutoff is None:
        cutoff = now_iso()
        set_app_config(conn, key=LEGACY_TEXT_TIMING_MIGRATION_CUTOFF_KEY, value=cutoff)
    rows = conn.execute(
        """
        SELECT
            texts.id,
            texts.morning_time,
            texts.evening_time,
            texts.summary_time_morning,
            texts.summary_time_evening
        FROM texts
        LEFT JOIN text_schedule_rules ON text_schedule_rules.text_id = texts.id
        LEFT JOIN text_schedule_rule_assignments ON text_schedule_rule_assignments.text_id = texts.id
        WHERE texts.created_at::timestamptz <= %s::timestamptz
        GROUP BY texts.id
        HAVING COUNT(text_schedule_rules.id) = 0
           AND COUNT(text_schedule_rule_assignments.id) = 0
        ORDER BY texts.id ASC
        """,
        (cutoff,),
    ).fetchall()
    for row in rows:
        legacy_rules = [
            {
                "delivery_type": "poll",
                "rule_type": "daily_time",
                "time": str(row["morning_time"] or "08:30"),
                "count_mode": "fixed",
                "count_value": 1,
                "label": "Migrated morning poll",
            },
            {
                "delivery_type": "poll",
                "rule_type": "daily_time",
                "time": str(row["evening_time"] or "18:00"),
                "count_mode": "fixed",
                "count_value": 1,
                "label": "Migrated evening poll",
            },
            {
                "delivery_type": "summary",
                "rule_type": "daily_time",
                "time": str(row["summary_time_morning"] or "08:25"),
                "count_mode": "fixed",
                "count_value": 1,
                "label": "Migrated morning summary",
            },
            {
                "delivery_type": "summary",
                "rule_type": "daily_time",
                "time": str(row["summary_time_evening"] or "17:55"),
                "count_mode": "fixed",
                "count_value": 1,
                "label": "Migrated evening summary",
            },
        ]
        for payload in legacy_rules:
            create_text_schedule_rule(conn, text_id=int(row["id"]), **payload)


def _migrate_text_owned_rules_to_shared_rules(conn: psycopg.Connection[DbRow]) -> None:
    legacy_rows = conn.execute(
        """
        SELECT
            text_schedule_rules.*,
            texts.tenant_id,
            texts.title AS text_title
        FROM text_schedule_rules
        JOIN texts ON texts.id = text_schedule_rules.text_id
        LEFT JOIN text_schedule_rule_assignments ON text_schedule_rule_assignments.text_id = texts.id
        WHERE text_schedule_rule_assignments.id IS NULL
        ORDER BY text_schedule_rules.created_at ASC, text_schedule_rules.id ASC
        """
    ).fetchall()
    for row in legacy_rows:
        rule = _serialize_schedule_rule(row)
        rule_id = create_schedule_rule(
            conn,
            tenant_id=int(row["tenant_id"]),
            name=_rule_name_for_text(str(row["text_title"] or "Text"), rule),
            delivery_type=str(rule["delivery_type"]),
            rule_type=str(rule["rule_type"]),
            enabled=bool(rule["enabled"]),
            time=rule.get("time"),
            weekdays=rule.get("weekdays"),
            month_dates=rule.get("month_dates"),
            window_start=rule.get("window_start"),
            window_end=rule.get("window_end"),
            count_mode=str(rule["count_mode"]),
            count_value=rule.get("count_value"),
            count_min=rule.get("count_min"),
            count_max=rule.get("count_max"),
            label=rule.get("label"),
            created_at_override=str(row["created_at"]),
            updated_at_override=str(row["updated_at"]),
        )
        assign_schedule_rule_to_text(
            conn,
            text_id=int(row["text_id"]),
            rule_id=rule_id,
            created_at_override=str(row["created_at"]),
        )


def _serialize_schedule_rule(row: DbRow) -> DbRow:
    item = dict(row)
    item["weekdays"] = [int(day) for day in _parse_json_list(item.pop("weekdays_json", "[]"))]
    item["month_dates"] = [int(day) for day in _parse_json_list(item.pop("month_dates_json", "[]"))]
    return item


def serialize_webhook_event(row: DbRow) -> DbRow:
    return dict(row)


def list_schedule_rules(conn: psycopg.Connection[DbRow], *, tenant_id: int, enabled_only: bool = False) -> list[DbRow]:
    sql = "SELECT * FROM schedule_rules WHERE tenant_id = %s"
    params: list[Any] = [tenant_id]
    if enabled_only:
        sql += " AND enabled = TRUE"
    sql += " ORDER BY created_at ASC, id ASC"
    rows = conn.execute(sql, params).fetchall()
    return [_serialize_schedule_rule(row) for row in rows]


def get_schedule_rule(conn: psycopg.Connection[DbRow], *, tenant_id: int, rule_id: int) -> DbRow | None:
    row = conn.execute("SELECT * FROM schedule_rules WHERE tenant_id = %s AND id = %s", (tenant_id, rule_id)).fetchone()
    return _serialize_schedule_rule(row) if row else None


def create_schedule_rule(
    conn: psycopg.Connection[DbRow],
    *,
    tenant_id: int,
    name: str | None,
    delivery_type: str,
    rule_type: str,
    enabled: bool = True,
    time: str | None = None,
    weekdays: list[int] | None = None,
    month_dates: list[int] | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    count_mode: str = "fixed",
    count_value: int | None = 1,
    count_min: int | None = None,
    count_max: int | None = None,
    label: str | None = None,
    created_at_override: str | None = None,
    updated_at_override: str | None = None,
) -> int:
    normalized = _normalize_schedule_rule_input(
        name=name,
        delivery_type=delivery_type,
        rule_type=rule_type,
        enabled=enabled,
        time=time,
        weekdays=weekdays,
        month_dates=month_dates,
        window_start=window_start,
        window_end=window_end,
        count_mode=count_mode,
        count_value=count_value,
        count_min=count_min,
        count_max=count_max,
        label=label,
    )
    timestamp = created_at_override or now_iso()
    updated_at = updated_at_override or timestamp
    rule_name = normalized["name"] or _default_schedule_rule_name(
        delivery_type=normalized["delivery_type"],
        rule_type=normalized["rule_type"],
        time=normalized["time"],
        window_start=normalized["window_start"],
        window_end=normalized["window_end"],
        label=normalized["label"],
    )
    row = conn.execute(
        """
        INSERT INTO schedule_rules (
            tenant_id, name, delivery_type, rule_type, enabled, time, weekdays_json, month_dates_json,
            window_start, window_end, count_mode, count_value, count_min, count_max, label, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            tenant_id,
            rule_name,
            normalized["delivery_type"],
            normalized["rule_type"],
            normalized["enabled"],
            normalized["time"],
            json.dumps(normalized["weekdays"]),
            json.dumps(normalized["month_dates"]),
            normalized["window_start"],
            normalized["window_end"],
            normalized["count_mode"],
            normalized["count_value"],
            normalized["count_min"],
            normalized["count_max"],
            normalized["label"],
            timestamp,
            updated_at,
        ),
    ).fetchone()
    return int(row["id"])


def update_schedule_rule(
    conn: psycopg.Connection[DbRow],
    *,
    tenant_id: int,
    rule_id: int,
    name: str | None,
    delivery_type: str,
    rule_type: str,
    enabled: bool = True,
    time: str | None = None,
    weekdays: list[int] | None = None,
    month_dates: list[int] | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    count_mode: str = "fixed",
    count_value: int | None = 1,
    count_min: int | None = None,
    count_max: int | None = None,
    label: str | None = None,
) -> None:
    normalized = _normalize_schedule_rule_input(
        name=name,
        delivery_type=delivery_type,
        rule_type=rule_type,
        enabled=enabled,
        time=time,
        weekdays=weekdays,
        month_dates=month_dates,
        window_start=window_start,
        window_end=window_end,
        count_mode=count_mode,
        count_value=count_value,
        count_min=count_min,
        count_max=count_max,
        label=label,
    )
    rule_name = normalized["name"] or _default_schedule_rule_name(
        delivery_type=normalized["delivery_type"],
        rule_type=normalized["rule_type"],
        time=normalized["time"],
        window_start=normalized["window_start"],
        window_end=normalized["window_end"],
        label=normalized["label"],
    )
    conn.execute(
        """
        UPDATE schedule_rules
        SET name = %s,
            delivery_type = %s,
            rule_type = %s,
            enabled = %s,
            time = %s,
            weekdays_json = %s,
            month_dates_json = %s,
            window_start = %s,
            window_end = %s,
            count_mode = %s,
            count_value = %s,
            count_min = %s,
            count_max = %s,
            label = %s,
            updated_at = %s
        WHERE tenant_id = %s AND id = %s
        """,
        (
            rule_name,
            normalized["delivery_type"],
            normalized["rule_type"],
            normalized["enabled"],
            normalized["time"],
            json.dumps(normalized["weekdays"]),
            json.dumps(normalized["month_dates"]),
            normalized["window_start"],
            normalized["window_end"],
            normalized["count_mode"],
            normalized["count_value"],
            normalized["count_min"],
            normalized["count_max"],
            normalized["label"],
            now_iso(),
            tenant_id,
            rule_id,
        ),
    )
    conn.execute("DELETE FROM text_schedule_rule_random_plans WHERE rule_id = %s", (rule_id,))


def delete_schedule_rule(conn: psycopg.Connection[DbRow], *, tenant_id: int, rule_id: int) -> None:
    conn.execute("DELETE FROM schedule_rules WHERE tenant_id = %s AND id = %s", (tenant_id, rule_id))


def list_text_schedule_rules(
    conn: psycopg.Connection[DbRow], *, text_id: int, enabled_only: bool = False
) -> list[DbRow]:
    sql = """
        SELECT schedule_rules.*, text_schedule_rule_assignments.text_id
        FROM text_schedule_rule_assignments
        JOIN schedule_rules ON schedule_rules.id = text_schedule_rule_assignments.rule_id
        WHERE text_schedule_rule_assignments.text_id = %s
    """
    params: list[Any] = [text_id]
    if enabled_only:
        sql += " AND schedule_rules.enabled = TRUE"
    sql += " ORDER BY schedule_rules.created_at ASC, schedule_rules.id ASC"
    rows = conn.execute(sql, params).fetchall()
    return [_serialize_schedule_rule(row) for row in rows]


def get_text_schedule_rule(conn: psycopg.Connection[DbRow], *, text_id: int, rule_id: int) -> DbRow | None:
    row = conn.execute(
        """
        SELECT schedule_rules.*, text_schedule_rule_assignments.text_id
        FROM text_schedule_rule_assignments
        JOIN schedule_rules ON schedule_rules.id = text_schedule_rule_assignments.rule_id
        WHERE text_schedule_rule_assignments.text_id = %s AND schedule_rules.id = %s
        """,
        (text_id, rule_id),
    ).fetchone()
    return _serialize_schedule_rule(row) if row else None


def assign_schedule_rule_to_text(
    conn: psycopg.Connection[DbRow], *, text_id: int, rule_id: int, created_at_override: str | None = None
) -> None:
    timestamp = created_at_override or now_iso()
    conn.execute(
        """
        INSERT INTO text_schedule_rule_assignments (text_id, rule_id, created_at)
        VALUES (%s, %s, %s)
        ON CONFLICT (text_id, rule_id) DO NOTHING
        """,
        (text_id, rule_id, timestamp),
    )


def unassign_schedule_rule_from_text(conn: psycopg.Connection[DbRow], *, text_id: int, rule_id: int) -> None:
    conn.execute("DELETE FROM text_schedule_rule_assignments WHERE text_id = %s AND rule_id = %s", (text_id, rule_id))


def replace_text_schedule_rule_assignments(
    conn: psycopg.Connection[DbRow], *, text_id: int, tenant_id: int, rule_ids: list[int]
) -> None:
    unique_rule_ids = sorted({int(rule_id) for rule_id in rule_ids})
    if unique_rule_ids:
        placeholders = ", ".join(["%s"] * len(unique_rule_ids))
        rows = conn.execute(
            f"SELECT id FROM schedule_rules WHERE tenant_id = %s AND id IN ({placeholders})",
            [tenant_id, *unique_rule_ids],
        ).fetchall()
        found_ids = {int(row["id"]) for row in rows}
        missing = [rule_id for rule_id in unique_rule_ids if rule_id not in found_ids]
        if missing:
            raise ValueError("One or more assigned_rule_ids do not belong to this tenant")
    conn.execute("DELETE FROM text_schedule_rule_assignments WHERE text_id = %s", (text_id,))
    for rule_id in unique_rule_ids:
        assign_schedule_rule_to_text(conn, text_id=text_id, rule_id=rule_id)


def create_text_schedule_rule(
    conn: psycopg.Connection[DbRow],
    *,
    text_id: int,
    delivery_type: str,
    rule_type: str,
    enabled: bool = True,
    time: str | None = None,
    weekdays: list[int] | None = None,
    month_dates: list[int] | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    count_mode: str = "fixed",
    count_value: int | None = 1,
    count_min: int | None = None,
    count_max: int | None = None,
    label: str | None = None,
) -> int:
    normalized = _normalize_schedule_rule_input(
        delivery_type=delivery_type,
        rule_type=rule_type,
        enabled=enabled,
        time=time,
        weekdays=weekdays,
        month_dates=month_dates,
        window_start=window_start,
        window_end=window_end,
        count_mode=count_mode,
        count_value=count_value,
        count_min=count_min,
        count_max=count_max,
        label=label,
    )
    timestamp = now_iso()
    row = conn.execute("SELECT tenant_id, title FROM texts WHERE id = %s", (text_id,)).fetchone()
    if row is None:
        raise ValueError("Text not found")
    rule_id = create_schedule_rule(
        conn,
        tenant_id=int(row["tenant_id"]),
        name=_rule_name_for_text(str(row["title"] or "Text"), normalized),
        delivery_type=str(normalized["delivery_type"]),
        rule_type=str(normalized["rule_type"]),
        enabled=bool(normalized["enabled"]),
        time=normalized.get("time"),
        weekdays=normalized.get("weekdays"),
        month_dates=normalized.get("month_dates"),
        window_start=normalized.get("window_start"),
        window_end=normalized.get("window_end"),
        count_mode=str(normalized["count_mode"]),
        count_value=normalized.get("count_value"),
        count_min=normalized.get("count_min"),
        count_max=normalized.get("count_max"),
        label=normalized.get("label"),
        created_at_override=timestamp,
        updated_at_override=timestamp,
    )
    assign_schedule_rule_to_text(conn, text_id=text_id, rule_id=rule_id, created_at_override=timestamp)
    return rule_id


def update_text_schedule_rule(
    conn: psycopg.Connection[DbRow],
    *,
    text_id: int,
    rule_id: int,
    delivery_type: str,
    rule_type: str,
    enabled: bool = True,
    time: str | None = None,
    weekdays: list[int] | None = None,
    month_dates: list[int] | None = None,
    window_start: str | None = None,
    window_end: str | None = None,
    count_mode: str = "fixed",
    count_value: int | None = 1,
    count_min: int | None = None,
    count_max: int | None = None,
    label: str | None = None,
) -> None:
    row = conn.execute("SELECT tenant_id, title FROM texts WHERE id = %s", (text_id,)).fetchone()
    if row is None:
        raise ValueError("Text not found")
    update_schedule_rule(
        conn,
        tenant_id=int(row["tenant_id"]),
        rule_id=rule_id,
        name=_rule_name_for_text(
            str(row["title"] or "Text"),
            {
                "delivery_type": delivery_type,
                "rule_type": rule_type,
                "time": time,
                "window_start": window_start,
                "window_end": window_end,
                "label": label,
            },
        ),
        delivery_type=delivery_type,
        rule_type=rule_type,
        enabled=enabled,
        time=time,
        weekdays=weekdays,
        month_dates=month_dates,
        window_start=window_start,
        window_end=window_end,
        count_mode=count_mode,
        count_value=count_value,
        count_min=count_min,
        count_max=count_max,
        label=label,
    )


def delete_text_schedule_rule(conn: psycopg.Connection[DbRow], *, text_id: int, rule_id: int) -> None:
    delete_schedule_rule(conn, tenant_id=int(get_text(conn, text_id)["tenant_id"]), rule_id=rule_id)


def replace_text_schedule_rules(conn: psycopg.Connection[DbRow], *, text_id: int, rules: list[dict[str, Any]]) -> None:
    row = conn.execute("SELECT tenant_id, title FROM texts WHERE id = %s", (text_id,)).fetchone()
    if row is None:
        raise ValueError("Text not found")
    conn.execute("DELETE FROM text_schedule_rule_assignments WHERE text_id = %s", (text_id,))
    for rule in rules:
        rule_id = create_schedule_rule(
            conn,
            tenant_id=int(row["tenant_id"]),
            **{**rule, "name": _rule_name_for_text(str(row["title"] or "Text"), rule)},
        )
        assign_schedule_rule_to_text(conn, text_id=text_id, rule_id=rule_id)


def get_random_rule_plan(
    conn: psycopg.Connection[DbRow], *, text_id: int, rule_id: int, local_date: str
) -> DbRow | None:
    row = conn.execute(
        "SELECT * FROM text_schedule_rule_random_plans WHERE text_id = %s AND rule_id = %s AND local_date = %s",
        (text_id, rule_id, local_date),
    ).fetchone()
    if row is None:
        return None
    item = dict(row)
    item["planned_times"] = [str(value) for value in _parse_json_list(item.pop("planned_times_json", "[]"))]
    item["executed_times"] = [str(value) for value in _parse_json_list(item.pop("executed_times_json", "[]"))]
    return item


def upsert_random_rule_plan(
    conn: psycopg.Connection[DbRow],
    *,
    text_id: int,
    rule_id: int,
    local_date: str,
    planned_times: list[str],
    executed_times: list[str] | None = None,
) -> DbRow:
    timestamp = now_iso()
    row = conn.execute(
        """
        INSERT INTO text_schedule_rule_random_plans (
            text_id, rule_id, local_date, planned_times_json, executed_times_json, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (text_id, rule_id, local_date) DO UPDATE SET
            planned_times_json = EXCLUDED.planned_times_json,
            executed_times_json = EXCLUDED.executed_times_json,
            updated_at = EXCLUDED.updated_at
        RETURNING *
        """,
        (
            text_id,
            rule_id,
            local_date,
            json.dumps(planned_times),
            json.dumps(executed_times or []),
            timestamp,
            timestamp,
        ),
    ).fetchone()
    return get_random_rule_plan(conn, text_id=text_id, rule_id=rule_id, local_date=local_date) or dict(row)


def mark_random_rule_plan_executed(
    conn: psycopg.Connection[DbRow], *, text_id: int, rule_id: int, local_date: str, executed_times: list[str]
) -> None:
    conn.execute(
        """
        UPDATE text_schedule_rule_random_plans
        SET executed_times_json = %s, updated_at = %s
        WHERE text_id = %s AND rule_id = %s AND local_date = %s
        """,
        (json.dumps(executed_times), now_iso(), text_id, rule_id, local_date),
    )


def attach_schedule_rules(conn: psycopg.Connection[DbRow], rows: list[DbRow]) -> list[DbRow]:
    if not rows:
        return rows
    text_ids = [int(row["id"]) for row in rows]
    placeholders = ", ".join(["%s"] * len(text_ids))
    rules = conn.execute(
        f"""
        SELECT schedule_rules.*, text_schedule_rule_assignments.text_id
        FROM text_schedule_rule_assignments
        JOIN schedule_rules ON schedule_rules.id = text_schedule_rule_assignments.rule_id
        WHERE text_schedule_rule_assignments.text_id IN ({placeholders})
        ORDER BY schedule_rules.created_at ASC, schedule_rules.id ASC
        """,
        text_ids,
    ).fetchall()
    grouped: dict[int, list[DbRow]] = {text_id: [] for text_id in text_ids}
    for rule in rules:
        grouped.setdefault(int(rule["text_id"]), []).append(_serialize_schedule_rule(rule))
    for row in rows:
        row["schedule_rules"] = grouped.get(int(row["id"]), [])
    return rows


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
        rows = conn.execute(
            """
            SELECT texts.*, tenants.name AS tenant_name
            FROM texts
            JOIN tenants ON tenants.id = texts.tenant_id
            ORDER BY texts.updated_at DESC
            """
        ).fetchall()
        return attach_schedule_rules(conn, rows)
    rows = conn.execute(
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
    return attach_schedule_rules(conn, rows)


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
    items = attach_schedule_rules(conn, items)
    return paginated_response(items, int(total), page, page_size)


def get_text(conn: psycopg.Connection[DbRow], text_id: int) -> DbRow | None:
    row = conn.execute(
        """
        SELECT texts.*, tenants.name AS tenant_name
            , tenants.poll_pool_threshold_percent AS tenant_poll_pool_threshold_percent
        FROM texts
        JOIN tenants ON tenants.id = texts.tenant_id
        WHERE texts.id = %s
        """,
        (text_id,),
    ).fetchone()
    if row is None:
        return None
    row["schedule_rules"] = list_text_schedule_rules(conn, text_id=text_id)
    return row


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
    poll_pool_threshold_percent: int | None = None,
    enabled: bool = True,
    attachment_name: str | None = None,
    attachment_path: str | None = None,
    assigned_rule_ids: list[int] | None = None,
    new_rules: list[dict[str, Any]] | None = None,
) -> int:
    timestamp = now_iso()
    normalized_chat_id = chat_id.strip()
    if normalized_chat_id:
        known_chat = get_tenant_group_chat(conn, tenant_id=tenant_id, chat_id=normalized_chat_id)
        if known_chat is not None and str(known_chat["policy"]) == "block":
            raise ValueError("Blocked chats cannot be assigned to texts")
    if text_id is None:
        row = conn.execute(
            """
            INSERT INTO texts (
                tenant_id, title, body, attachment_name, attachment_path, chat_id,
                poll_pool_threshold_percent, enabled, created_at, updated_at
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                tenant_id,
                title.strip() or "Text",
                body.strip(),
                attachment_name,
                attachment_path,
                normalized_chat_id,
                max(0, min(100, int(poll_pool_threshold_percent))) if poll_pool_threshold_percent is not None else None,
                enabled,
                timestamp,
                timestamp,
            ),
        ).fetchone()
        created_id = int(row["id"])
        created_rule_ids: list[int] = []
        for rule in new_rules or []:
            created_rule_ids.append(create_schedule_rule(conn, tenant_id=tenant_id, **rule))
        if assigned_rule_ids is not None or new_rules is not None:
            replace_text_schedule_rule_assignments(
                conn,
                text_id=created_id,
                tenant_id=tenant_id,
                rule_ids=[*(assigned_rule_ids or []), *created_rule_ids],
            )
        return created_id

    existing = get_text(conn, text_id)
    conn.execute(
        """
        UPDATE texts
        SET tenant_id = %s, title = %s, body = %s, attachment_name = %s, attachment_path = %s,
            chat_id = %s, poll_pool_threshold_percent = %s, enabled = %s, updated_at = %s
        WHERE id = %s
        """,
        (
            tenant_id,
            title.strip() or "Text",
            body.strip(),
            attachment_name if attachment_name is not None else existing["attachment_name"] if existing else None,
            attachment_path if attachment_path is not None else existing["attachment_path"] if existing else None,
            normalized_chat_id,
            max(0, min(100, int(poll_pool_threshold_percent))) if poll_pool_threshold_percent is not None else None,
            enabled,
            timestamp,
            text_id,
        ),
    )
    created_rule_ids = [create_schedule_rule(conn, tenant_id=tenant_id, **rule) for rule in (new_rules or [])]
    if assigned_rule_ids is not None or new_rules is not None:
        replace_text_schedule_rule_assignments(
            conn,
            text_id=text_id,
            tenant_id=tenant_id,
            rule_ids=[*(assigned_rule_ids or []), *created_rule_ids],
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
            generated_from_text, status, scheduled_slot, change_window_seconds, manual_lock, auto_lock_seconds,
            pool_rank, recipient_snapshot_source, recipient_snapshot_synced_at, created_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
            None,
            None,
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


def list_polls(
    conn: psycopg.Connection[DbRow],
    limit: int = 25,
    tenant_id: int | None = None,
    text_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[DbRow]:
    where: list[str] = ["status = 'sent'"]
    params: list[Any] = []
    scoped_timestamp = "COALESCE(sent_at, created_at)"
    if tenant_id is not None:
        where.append("tenant_id = %s")
        params.append(tenant_id)
    if text_id is not None:
        where.append("text_id = %s")
        params.append(text_id)
    if date_from:
        operator, value = _coerce_filter_datetime(date_from, end=False)
        where.append(f"{scoped_timestamp} {operator} %s")
        params.append(value)
    if date_to:
        operator, value = _coerce_filter_datetime(date_to, end=True)
        where.append(f"{scoped_timestamp} {operator} %s")
        params.append(value)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    return conn.execute(
        f"SELECT * FROM polls {where_sql} ORDER BY {scoped_timestamp} DESC NULLS LAST, created_at DESC LIMIT %s",
        [*params, limit],
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
    recipient_snapshot_source: str | None = None,
    recipient_snapshot_synced_at: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE polls
        SET tenant_id = %s, text_id = %s, question = %s, options_json = %s,
            correct_option = %s, explanation = %s, greenapi_message_id = %s,
            chat_id = %s, generated_from_text = %s, status = %s, scheduled_slot = %s,
            sent_at = %s, summary_sent_at = %s, pool_rank = %s, change_window_seconds = %s,
            manual_lock = %s, auto_lock_seconds = %s,
            recipient_snapshot_source = %s, recipient_snapshot_synced_at = %s
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
            recipient_snapshot_source,
            recipient_snapshot_synced_at,
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


def list_scheduler_texts(conn: psycopg.Connection[DbRow], tenant_id: int | None = None) -> list[DbRow]:
    sql = """
        SELECT texts.*, tenants.name AS tenant_name, tenants.greenapi_api_url, tenants.greenapi_id_instance,
               tenants.greenapi_api_token_instance, tenants.gemini_api_key, tenants.gemini_model,
               tenants.timezone, tenants.summary_enabled, tenants.scheduler_enabled, tenants.is_active
        FROM texts
        JOIN tenants ON tenants.id = texts.tenant_id
    """
    params: tuple[Any, ...] = ()
    if tenant_id is not None:
        sql += " WHERE texts.tenant_id = %s"
        params = (tenant_id,)
    sql += " ORDER BY texts.id ASC"
    return conn.execute(sql, params).fetchall()


def set_app_config(conn: psycopg.Connection[DbRow], *, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO app_config (key, value)
        VALUES (%s, %s)
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
        """,
        (key, value),
    )


def get_app_config(conn: psycopg.Connection[DbRow], *, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_config WHERE key = %s", (key,)).fetchone()
    if row is None:
        return None
    return str(row["value"])


def set_app_config_json(conn: psycopg.Connection[DbRow], *, key: str, value: dict[str, Any]) -> None:
    set_app_config(conn, key=key, value=json.dumps(value, ensure_ascii=False))


def get_app_config_json(conn: psycopg.Connection[DbRow], *, key: str) -> dict[str, Any] | None:
    raw = get_app_config(conn, key=key)
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def create_scheduled_send_attempt(
    conn: psycopg.Connection[DbRow],
    *,
    tenant_id: int,
    text_id: int,
    rule_id: int,
    delivery_type: str,
    scheduled_slot: str,
    local_date: str,
    timezone: str,
    status: str = "started",
    poll_id: int | None = None,
    summary_count: int | None = None,
    error: str | None = None,
) -> int:
    timestamp = now_iso()
    row = conn.execute(
        """
        INSERT INTO scheduled_send_attempts (
            tenant_id, text_id, rule_id, delivery_type, scheduled_slot, local_date, timezone,
            status, poll_id, summary_count, error, created_at, updated_at
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            tenant_id,
            text_id,
            rule_id,
            delivery_type,
            scheduled_slot,
            local_date,
            timezone,
            status,
            poll_id,
            summary_count,
            error[:500] if error else None,
            timestamp,
            timestamp,
        ),
    ).fetchone()
    return int(row["id"])


def update_scheduled_send_attempt(
    conn: psycopg.Connection[DbRow],
    *,
    attempt_id: int,
    status: str,
    poll_id: int | None = None,
    summary_count: int | None = None,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE scheduled_send_attempts
        SET status = %s, poll_id = %s, summary_count = %s, error = %s, updated_at = %s
        WHERE id = %s
        """,
        (status, poll_id, summary_count, error[:500] if error else None, now_iso(), attempt_id),
    )


def create_incoming_webhook(
    conn: psycopg.Connection[DbRow],
    *,
    tenant_id: int,
    provider: str,
    endpoint_path: str,
    payload_json: str,
    type_webhook: str | None = None,
    message_type: str | None = None,
    greenapi_message_id: str | None = None,
    poll_id: int | None = None,
    decision_status: str | None = None,
    decision_reason: str | None = None,
    error: str | None = None,
    received_at: str | None = None,
    processed_at: str | None = None,
) -> int:
    timestamp = received_at or now_iso()
    row = conn.execute(
        """
        INSERT INTO incoming_webhooks (
            tenant_id, provider, endpoint_path, type_webhook, message_type, greenapi_message_id,
            poll_id, decision_status, decision_reason, payload_json, received_at, processed_at, error
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id
        """,
        (
            tenant_id,
            provider.strip(),
            endpoint_path,
            type_webhook.strip() if type_webhook else None,
            message_type.strip() if message_type else None,
            greenapi_message_id.strip() if greenapi_message_id else None,
            poll_id,
            decision_status.strip() if decision_status else None,
            decision_reason.strip() if decision_reason else None,
            payload_json,
            timestamp,
            processed_at,
            error[:500] if error else None,
        ),
    ).fetchone()
    return int(row["id"])


def update_incoming_webhook(
    conn: psycopg.Connection[DbRow],
    *,
    webhook_id: int,
    type_webhook: str | None = None,
    message_type: str | None = None,
    greenapi_message_id: str | None = None,
    poll_id: int | None = None,
    decision_status: str | None = None,
    decision_reason: str | None = None,
    processed_at: str | None = None,
    error: str | None = None,
) -> None:
    conn.execute(
        """
        UPDATE incoming_webhooks
        SET type_webhook = %s,
            message_type = %s,
            greenapi_message_id = %s,
            poll_id = %s,
            decision_status = %s,
            decision_reason = %s,
            processed_at = %s,
            error = %s
        WHERE id = %s
        """,
        (
            type_webhook.strip() if type_webhook else None,
            message_type.strip() if message_type else None,
            greenapi_message_id.strip() if greenapi_message_id else None,
            poll_id,
            decision_status.strip() if decision_status else None,
            decision_reason.strip() if decision_reason else None,
            processed_at,
            error[:500] if error else None,
            webhook_id,
        ),
    )


def get_incoming_webhook(conn: psycopg.Connection[DbRow], *, tenant_id: int, webhook_id: int) -> DbRow | None:
    row = conn.execute(
        "SELECT * FROM incoming_webhooks WHERE tenant_id = %s AND id = %s",
        (tenant_id, webhook_id),
    ).fetchone()
    return serialize_webhook_event(row) if row else None


def list_incoming_webhooks_page(
    conn: psycopg.Connection[DbRow],
    *,
    tenant_id: int,
    page: int = 1,
    page_size: int = 25,
    search: str | None = None,
    status: str | None = None,
    reason: str | None = None,
    type_webhook: str | None = None,
    greenapi_message_id: str | None = None,
    poll_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    page, page_size, offset = _page_bounds(page, page_size)
    where = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if search:
        where.append(
            """
            (
                payload_json ILIKE %s
                OR COALESCE(greenapi_message_id, '') ILIKE %s
                OR COALESCE(type_webhook, '') ILIKE %s
                OR COALESCE(decision_reason, '') ILIKE %s
                OR COALESCE(CAST(poll_id AS TEXT), '') ILIKE %s
            )
            """
        )
        params.extend([_like(search), _like(search), _like(search), _like(search), _like(search)])
    for column, value in (
        ("decision_status", status),
        ("decision_reason", reason),
        ("type_webhook", type_webhook),
        ("greenapi_message_id", greenapi_message_id),
        ("poll_id", poll_id),
    ):
        if value is not None and value != "":
            where.append(f"{column} = %s")
            params.append(value)
    if date_from:
        operator, value = _coerce_filter_datetime(date_from, end=False)
        where.append(f"received_at {operator} %s")
        params.append(value)
    if date_to:
        operator, value = _coerce_filter_datetime(date_to, end=True)
        where.append(f"received_at {operator} %s")
        params.append(value)
    where_sql = f"WHERE {' AND '.join(where)}"
    total = conn.execute(f"SELECT COUNT(*) AS count FROM incoming_webhooks {where_sql}", params).fetchone()["count"]
    items = conn.execute(
        f"""
        SELECT *
        FROM incoming_webhooks
        {where_sql}
        ORDER BY received_at DESC, id DESC
        LIMIT %s OFFSET %s
        """,
        [*params, page_size, offset],
    ).fetchall()
    return paginated_response([serialize_webhook_event(item) for item in items], int(total), page, page_size)


def count_scheduled_send_attempts(
    conn: psycopg.Connection[DbRow], *, text_id: int, rule_id: int, local_date: str, scheduled_slot: str
) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS count
        FROM scheduled_send_attempts
        WHERE text_id = %s AND rule_id = %s AND local_date = %s AND scheduled_slot = %s
        """,
        (text_id, rule_id, local_date, scheduled_slot),
    ).fetchone()
    return int(row["count"])


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


def list_tenant_group_chats(
    conn: psycopg.Connection[DbRow],
    *,
    tenant_id: int,
    policy: str | None = None,
    include_blocked: bool = True,
) -> list[DbRow]:
    where = ["tenant_id = %s"]
    params: list[Any] = [tenant_id]
    if policy:
        normalized_policy = policy.strip()
        if normalized_policy not in CHAT_POLICIES:
            raise ValueError("policy must be allow, neutral, or block")
        where.append("policy = %s")
        params.append(normalized_policy)
    elif not include_blocked:
        where.append("policy <> 'block'")
    return conn.execute(
        f"""
        SELECT chat_id, name, policy, last_synced_at, created_at, updated_at
        FROM tenant_group_chats
        WHERE {" AND ".join(where)}
        ORDER BY
            CASE policy WHEN 'allow' THEN 0 WHEN 'neutral' THEN 1 ELSE 2 END,
            LOWER(name) ASC,
            chat_id ASC
        """,
        params,
    ).fetchall()


def get_tenant_group_chat(conn: psycopg.Connection[DbRow], *, tenant_id: int, chat_id: str) -> DbRow | None:
    return conn.execute(
        """
        SELECT chat_id, name, policy, last_synced_at, created_at, updated_at
        FROM tenant_group_chats
        WHERE tenant_id = %s AND chat_id = %s
        """,
        (tenant_id, chat_id.strip()),
    ).fetchone()


def sync_tenant_group_chats(
    conn: psycopg.Connection[DbRow],
    *,
    tenant_id: int,
    chats: list[dict[str, str]],
    synced_at: str | None = None,
) -> list[DbRow]:
    timestamp = synced_at or now_iso()
    rows: list[tuple[int, str, str, str, str, str]] = []
    for chat in chats:
        chat_id = str(chat.get("chat_id") or "").strip()
        if not chat_id.endswith("@g.us"):
            continue
        name = str(chat.get("name") or chat_id).strip() or chat_id
        rows.append((tenant_id, chat_id, name, timestamp, timestamp, timestamp))
    if rows:
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO tenant_group_chats (
                    tenant_id, chat_id, name, last_synced_at, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, chat_id) DO UPDATE SET
                    name = EXCLUDED.name,
                    last_synced_at = EXCLUDED.last_synced_at,
                    updated_at = EXCLUDED.updated_at
                """,
                rows,
            )
    return list_tenant_group_chats(conn, tenant_id=tenant_id)


def update_tenant_group_chat_policy(
    conn: psycopg.Connection[DbRow], *, tenant_id: int, chat_id: str, policy: str
) -> None:
    normalized_policy = policy.strip()
    if normalized_policy not in CHAT_POLICIES:
        raise ValueError("policy must be allow, neutral, or block")
    updated = conn.execute(
        """
        UPDATE tenant_group_chats
        SET policy = %s, updated_at = %s
        WHERE tenant_id = %s AND chat_id = %s
        """,
        (normalized_policy, now_iso(), tenant_id, chat_id.strip()),
    )
    if updated.rowcount == 0:
        raise RuntimeError("Chat not found")


def list_chat_participants(
    conn: psycopg.Connection[DbRow],
    *,
    tenant_id: int,
    chat_id: str,
    active_only: bool = False,
) -> list[DbRow]:
    where = "WHERE tenant_id = %s AND chat_id = %s"
    params: list[Any] = [tenant_id, chat_id.strip()]
    if active_only:
        where += " AND is_active_in_chat = TRUE"
    return conn.execute(
        f"""
        SELECT
            voter_wid,
            COALESCE(
                NULLIF(display_name, ''),
                NULLIF(phone_number, ''),
                voter_wid
            ) AS display_name,
            COALESCE(
                NULLIF(phone_number, ''),
                NULLIF(regexp_replace(split_part(voter_wid, '@', 1), '\\D', '', 'g'), ''),
                split_part(voter_wid, '@', 1)
            ) AS phone_number,
            is_active_in_chat,
            excluded_from_coverage,
            last_synced_at
        FROM chat_participants
        {where}
        ORDER BY is_active_in_chat DESC, excluded_from_coverage ASC, display_name ASC, voter_wid ASC
        """,
        params,
    ).fetchall()


def sync_chat_participants(
    conn: psycopg.Connection[DbRow],
    *,
    tenant_id: int,
    chat_id: str,
    participants: list[dict[str, str | None]],
    synced_at: str | None = None,
) -> str:
    timestamp = synced_at or now_iso()
    normalized_chat_id = chat_id.strip()
    conn.execute(
        """
        UPDATE chat_participants
        SET is_active_in_chat = FALSE, last_synced_at = %s, updated_at = %s
        WHERE tenant_id = %s AND chat_id = %s
        """,
        (timestamp, timestamp, tenant_id, normalized_chat_id),
    )
    rows: list[tuple[int, str, str, str, str | None, str | None, str, str]] = []
    for participant in participants:
        voter_wid = str(participant.get("voter_wid") or "").strip()
        if not voter_wid:
            continue
        display_name = str(participant.get("display_name") or participant.get("voter_name") or "").strip() or None
        phone_number = str(participant.get("phone_number") or "").strip() or normalize_phone_number(voter_wid)
        rows.append(
            (tenant_id, normalized_chat_id, voter_wid, phone_number, display_name, timestamp, timestamp, timestamp)
        )
        upsert_contact_profile(
            conn,
            tenant_id=tenant_id,
            voter_wid=voter_wid,
            phone_number=phone_number,
            display_name=display_name,
        )
    if rows:
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO chat_participants (
                    tenant_id, chat_id, voter_wid, phone_number, display_name,
                    last_synced_at, created_at, updated_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (tenant_id, chat_id, voter_wid) DO UPDATE SET
                    phone_number = COALESCE(EXCLUDED.phone_number, chat_participants.phone_number),
                    display_name = COALESCE(EXCLUDED.display_name, chat_participants.display_name),
                    is_active_in_chat = TRUE,
                    last_synced_at = EXCLUDED.last_synced_at,
                    updated_at = EXCLUDED.updated_at
                """,
                rows,
            )
    return timestamp


def update_chat_participant_exclusion(
    conn: psycopg.Connection[DbRow],
    *,
    tenant_id: int,
    chat_id: str,
    voter_wid: str,
    excluded_from_coverage: bool,
) -> None:
    updated = conn.execute(
        """
        UPDATE chat_participants
        SET excluded_from_coverage = %s, updated_at = %s
        WHERE tenant_id = %s AND chat_id = %s AND voter_wid = %s
        """,
        (excluded_from_coverage, now_iso(), tenant_id, chat_id.strip(), voter_wid.strip()),
    )
    if updated.rowcount == 0:
        raise RuntimeError("Roster member not found")


def list_coverage_participants(
    conn: psycopg.Connection[DbRow],
    *,
    tenant_id: int,
    chat_id: str,
) -> list[DbRow]:
    return conn.execute(
        """
        SELECT
            voter_wid,
            COALESCE(
                NULLIF(display_name, ''),
                NULLIF(phone_number, ''),
                voter_wid
            ) AS display_name,
            COALESCE(
                NULLIF(phone_number, ''),
                NULLIF(regexp_replace(split_part(voter_wid, '@', 1), '\\D', '', 'g'), ''),
                split_part(voter_wid, '@', 1)
            ) AS phone_number,
            last_synced_at
        FROM chat_participants
        WHERE tenant_id = %s AND chat_id = %s AND is_active_in_chat = TRUE AND excluded_from_coverage = FALSE
        ORDER BY display_name ASC, voter_wid ASC
        """,
        (tenant_id, chat_id.strip()),
    ).fetchall()


def snapshot_poll_recipients(
    conn: psycopg.Connection[DbRow],
    *,
    poll_id: int,
    tenant_id: int,
    chat_id: str,
    participants: list[dict[str, Any]],
    source: str,
    synced_at: str | None,
) -> int:
    timestamp = now_iso()
    normalized_chat_id = chat_id.strip()
    conn.execute("DELETE FROM poll_recipient_snapshots WHERE poll_id = %s", (poll_id,))
    rows: list[tuple[int, int, str, str, str, str | None, str]] = []
    for participant in participants:
        voter_wid = str(participant.get("voter_wid") or "").strip()
        if not voter_wid:
            continue
        display_name = str(participant.get("display_name") or "").strip() or None
        phone_number = str(participant.get("phone_number") or "").strip() or normalize_phone_number(voter_wid)
        rows.append((poll_id, tenant_id, normalized_chat_id, voter_wid, phone_number, display_name, timestamp))
    if rows:
        with conn.cursor() as cursor:
            cursor.executemany(
                """
                INSERT INTO poll_recipient_snapshots (
                    poll_id, tenant_id, chat_id, voter_wid, phone_number, display_name, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                rows,
            )
    conn.execute(
        """
        UPDATE polls
        SET recipient_snapshot_source = %s, recipient_snapshot_synced_at = %s
        WHERE id = %s
        """,
        (source, synced_at, poll_id),
    )
    return len(rows)


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
    segment: str = "all",
    sort_by: str = "latest_activity",
    sort_dir: str = "desc",
) -> dict[str, Any]:
    page, page_size, offset = _page_bounds(page, page_size)
    where_sql, params = _learner_poll_filters(
        tenant_id=tenant_id,
        text_id=text_id,
        date_from=date_from,
        date_to=date_to,
    )
    aggregate_cte = _learner_aggregate_cte(where_sql, search=search)
    learner_params = list(params)
    if search:
        like = _like(search)
        learner_params.extend([like, like, like])
    segment_sql = _learner_segment_condition(segment)
    total = conn.execute(
        f"""
        {aggregate_cte}
        SELECT COUNT(*) AS count
        FROM filtered_learners
        WHERE {segment_sql}
        """,
        learner_params,
    ).fetchone()["count"]
    items = conn.execute(
        f"""
        {aggregate_cte}
        {_learner_select_sql()}
        WHERE {segment_sql}
        ORDER BY {_learner_sort_sql(sort_by, sort_dir)}
        LIMIT %s OFFSET %s
        """,
        [*learner_params, page_size, offset],
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
    where_sql, params = _learner_poll_filters(
        tenant_id=tenant_id,
        text_id=text_id,
        date_from=date_from,
        date_to=date_to,
    )
    aggregate_cte = _learner_aggregate_cte(where_sql, voter_wid=voter_wid)
    learner_params = [*params, voter_wid.strip()]
    row = conn.execute(
        f"""
        {aggregate_cte}
        {_learner_select_sql()}
        LIMIT 1
        """,
        learner_params,
    ).fetchone()
    return row


def get_learners_summary(
    conn: psycopg.Connection[DbRow],
    *,
    tenant_id: int,
    text_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> dict[str, Any]:
    where_sql, params = _learner_poll_filters(
        tenant_id=tenant_id,
        text_id=text_id,
        date_from=date_from,
        date_to=date_to,
    )
    aggregate_cte = _learner_aggregate_cte(where_sql)
    totals = conn.execute(
        f"""
        {aggregate_cte}
        SELECT
            COUNT(*)::INT AS learners_total,
            COALESCE(SUM(assigned_polls_count), 0)::INT AS assigned_polls_total,
            COALESCE(SUM(responded_polls_count), 0)::INT AS responded_polls_total,
            COALESCE(SUM(missed_polls_count), 0)::INT AS missed_polls_total,
            CASE
                WHEN COALESCE(SUM(assigned_polls_count), 0) > 0
                    THEN ROUND(COALESCE(SUM(responded_polls_count), 0)::numeric * 100.0 / SUM(assigned_polls_count), 2)
                ELSE 0
            END AS response_rate,
            COALESCE(SUM(total_counted_votes), 0)::INT AS total_counted_votes,
            CASE
                WHEN COALESCE(SUM(total_counted_votes), 0) > 0
                    THEN ROUND(COALESCE(SUM(correct_count), 0)::numeric * 100.0 / SUM(total_counted_votes), 2)
                ELSE 0
            END AS correct_rate,
            COALESCE(SUM(ignored_changes_count), 0)::INT AS ignored_changes_total,
            COUNT(*) FILTER (
                WHERE {_learner_segment_condition("needs_attention")}
            )::INT AS needs_attention_count,
            COUNT(*) FILTER (
                WHERE {_learner_segment_condition("inactive")}
            )::INT AS inactive_count,
            COUNT(*) FILTER (
                WHERE {_learner_segment_condition("engaged")}
            )::INT AS engaged_count
        FROM filtered_learners
        """,
        params,
    ).fetchone()

    def load_ranked(order_sql: str, where_filter: str = "1 = 1") -> list[DbRow]:
        return conn.execute(
            f"""
            {aggregate_cte}
            {_learner_select_sql()}
            WHERE {where_filter}
            ORDER BY {order_sql}
            LIMIT 5
            """,
            params,
        ).fetchall()

    return {
        **dict(totals),
        "top_missed": load_ranked(
            "missed_polls_count DESC, response_rate ASC, latest_activity DESC NULLS LAST, display_name ASC"
        ),
        "lowest_response": load_ranked(
            "response_rate ASC, missed_polls_count DESC, assigned_polls_count DESC, latest_activity DESC NULLS LAST, display_name ASC",
            "assigned_polls_count > 0",
        ),
        "most_active": load_ranked(
            "total_counted_votes DESC, responded_polls_count DESC, latest_activity DESC NULLS LAST, display_name ASC"
        ),
    }


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
    where_sql, params = _learner_poll_filters(
        tenant_id=tenant_id,
        text_id=text_id,
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
        WHERE {where_sql} AND poll_vote_events.voter_wid = %s
        ORDER BY poll_vote_events.recorded_at DESC, poll_vote_events.id DESC
        LIMIT %s
        """,
        [*params, voter_wid.strip(), safe_limit],
    ).fetchall()


def list_learner_missed_polls(
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
    where_sql, params = _learner_poll_filters(
        tenant_id=tenant_id,
        text_id=text_id,
        date_from=date_from,
        date_to=date_to,
    )
    return conn.execute(
        f"""
        SELECT
            polls.id AS poll_id,
            polls.text_id,
            polls.question,
            polls.sent_at,
            polls.recipient_snapshot_source,
            polls.recipient_snapshot_synced_at
        FROM poll_recipient_snapshots
        JOIN polls ON polls.id = poll_recipient_snapshots.poll_id
        LEFT JOIN poll_votes
            ON poll_votes.poll_id = poll_recipient_snapshots.poll_id
           AND poll_votes.voter_wid = poll_recipient_snapshots.voter_wid
        WHERE {where_sql}
          AND poll_recipient_snapshots.voter_wid = %s
          AND poll_votes.id IS NULL
        ORDER BY polls.sent_at DESC NULLS LAST, polls.id DESC
        LIMIT %s
        """,
        [*params, voter_wid.strip(), safe_limit],
    ).fetchall()


def get_poll_coverage_page(
    conn: psycopg.Connection[DbRow],
    *,
    poll_id: int,
    page: int = 1,
    page_size: int = 25,
) -> dict[str, Any]:
    page, page_size, offset = _page_bounds(page, page_size)
    poll = get_poll(conn, poll_id)
    if poll is None:
        raise RuntimeError("Poll not found")
    snapshot_source = poll.get("recipient_snapshot_source")
    snapshot_synced_at = poll.get("recipient_snapshot_synced_at")
    assigned_count = int(
        conn.execute(
            "SELECT COUNT(*) AS count FROM poll_recipient_snapshots WHERE poll_id = %s",
            (poll_id,),
        ).fetchone()["count"]
    )
    responded_count = int(
        conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM poll_recipient_snapshots
            JOIN poll_votes
              ON poll_votes.poll_id = poll_recipient_snapshots.poll_id
             AND poll_votes.voter_wid = poll_recipient_snapshots.voter_wid
            WHERE poll_recipient_snapshots.poll_id = %s
            """,
            (poll_id,),
        ).fetchone()["count"]
    )
    total = int(
        conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM poll_recipient_snapshots
            LEFT JOIN poll_votes
              ON poll_votes.poll_id = poll_recipient_snapshots.poll_id
             AND poll_votes.voter_wid = poll_recipient_snapshots.voter_wid
            WHERE poll_recipient_snapshots.poll_id = %s AND poll_votes.id IS NULL
            """,
            (poll_id,),
        ).fetchone()["count"]
    )
    items = conn.execute(
        """
        SELECT
            poll_recipient_snapshots.voter_wid,
            COALESCE(
                NULLIF(poll_recipient_snapshots.display_name, ''),
                NULLIF(poll_recipient_snapshots.phone_number, ''),
                poll_recipient_snapshots.voter_wid
            ) AS display_name,
            COALESCE(
                NULLIF(poll_recipient_snapshots.phone_number, ''),
                NULLIF(regexp_replace(split_part(poll_recipient_snapshots.voter_wid, '@', 1), '\\D', '', 'g'), ''),
                split_part(poll_recipient_snapshots.voter_wid, '@', 1)
            ) AS phone_number,
            poll_recipient_snapshots.created_at AS assigned_at
        FROM poll_recipient_snapshots
        LEFT JOIN poll_votes
          ON poll_votes.poll_id = poll_recipient_snapshots.poll_id
         AND poll_votes.voter_wid = poll_recipient_snapshots.voter_wid
        WHERE poll_recipient_snapshots.poll_id = %s AND poll_votes.id IS NULL
        ORDER BY display_name ASC, poll_recipient_snapshots.voter_wid ASC
        LIMIT %s OFFSET %s
        """,
        (poll_id, page_size, offset),
    ).fetchall()
    missed_count = max(assigned_count - responded_count, 0)
    return {
        "poll_id": poll_id,
        "coverage_available": snapshot_source != "unavailable",
        "recipient_snapshot_source": snapshot_source,
        "recipient_snapshot_synced_at": snapshot_synced_at,
        "assigned_count": assigned_count,
        "responded_count": responded_count,
        "missed_count": missed_count,
        "response_rate": round((responded_count / assigned_count * 100), 2) if assigned_count else 0.0,
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "has_next": page * page_size < total,
    }


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
    conn: psycopg.Connection[DbRow],
    limit: int = 25,
    tenant_id: int | None = None,
    text_id: int | None = None,
    date_from: str | None = None,
    date_to: str | None = None,
) -> list[dict[str, Any]]:
    return [
        poll_stats(conn, poll)
        for poll in list_polls(
            conn,
            limit=limit,
            tenant_id=tenant_id,
            text_id=text_id,
            date_from=date_from,
            date_to=date_to,
        )
    ]


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
