from __future__ import annotations

import random
from dataclasses import asdict
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.logging import get_logger
from app.services import generate_and_send_poll, runtime_config_from_row, send_pending_summaries

logger = get_logger("scheduler")

SCHEDULER_STATUS_KEY = "scheduler_worker_status"


def build_scheduler(database_url: str, *, debug_enabled: bool = False) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=timezone.utc)
    scheduler.add_job(
        run_due_jobs,
        CronTrigger(minute="*", timezone=timezone.utc),
        kwargs={"database_url": database_url, "debug_enabled": debug_enabled},
        id="due_jobs",
        replace_existing=True,
        max_instances=1,
    )
    return scheduler


def _debug_log(enabled: bool, event: str, **extra: object) -> None:
    if not enabled:
        return
    logger.info(f"scheduler.debug.{event}", extra=extra)


def _write_scheduler_status(
    *,
    database_url: str,
    status: dict[str, object],
    debug_enabled: bool,
    phase: str,
) -> None:
    from app.database import db_session, set_app_config_json

    with db_session(database_url) as conn:
        set_app_config_json(conn, key=SCHEDULER_STATUS_KEY, value=status)
    _debug_log(debug_enabled, "heartbeat_write", phase=phase, status=status)


async def run_due_jobs(*, database_url: str, now_utc: datetime | None = None, debug_enabled: bool = False) -> int:
    from app.database import db_session, list_scheduler_texts

    tick_utc = _normalize_utc(now_utc)
    sent = 0
    summary_sent = 0
    last_error: str | None = None

    _debug_log(
        debug_enabled,
        "tick_start",
        database_url_configured=bool(database_url.strip()),
        tick_input=None if now_utc is None else now_utc.isoformat(),
        tick_utc=tick_utc.isoformat(),
    )
    with db_session(database_url) as conn:
        texts = list_scheduler_texts(conn)
    initial_status = {
        "last_tick_at": tick_utc.isoformat(),
        "last_success_at": None,
        "last_error": None,
        "polls_sent": 0,
        "summaries_sent": 0,
    }
    _write_scheduler_status(
        database_url=database_url,
        status=initial_status,
        debug_enabled=debug_enabled,
        phase="tick_start",
    )
    _debug_log(debug_enabled, "texts_loaded", text_count=len(texts), texts=[dict(text) for text in texts])

    logger.info("scheduler.tick", extra={"text_count": len(texts), "tick_utc": tick_utc.isoformat()})
    for text in texts:
        text_id = int(text["id"])
        _debug_log(debug_enabled, "text_row", text_id=text_id, row=dict(text))
        runtime = runtime_config_from_row(
            text,
            debug_logger=(
                lambda event, payload, text_id=text_id: _debug_log(debug_enabled, event, text_id=text_id, **payload)
            ),
        )
        tenant_id = runtime.tenant_id
        try:
            if not bool(text.get("is_active")):
                _debug_log(
                    debug_enabled,
                    "skip_reason",
                    tenant_id=tenant_id,
                    text_id=text_id,
                    reason="inactive_tenant",
                    row=dict(text),
                    runtime_config=asdict(runtime),
                )
                logger.info(
                    "scheduler.skipped", extra={"tenant_id": tenant_id, "text_id": text_id, "reason": "inactive_tenant"}
                )
                continue
            if not bool(text.get("enabled")):
                _debug_log(
                    debug_enabled,
                    "skip_reason",
                    tenant_id=tenant_id,
                    text_id=text_id,
                    reason="disabled_text",
                    row=dict(text),
                    runtime_config=asdict(runtime),
                )
                logger.info(
                    "scheduler.skipped", extra={"tenant_id": tenant_id, "text_id": text_id, "reason": "disabled_text"}
                )
                continue
            if not runtime.scheduler_enabled:
                _debug_log(
                    debug_enabled,
                    "skip_reason",
                    tenant_id=tenant_id,
                    text_id=text_id,
                    reason="scheduler_disabled",
                    row=dict(text),
                    runtime_config=asdict(runtime),
                )
                logger.info(
                    "scheduler.skipped",
                    extra={"tenant_id": tenant_id, "text_id": text_id, "reason": "scheduler_disabled"},
                )
                continue
            if not runtime.greenapi_ready:
                _debug_log(
                    debug_enabled,
                    "skip_reason",
                    tenant_id=tenant_id,
                    text_id=text_id,
                    reason="greenapi_not_ready",
                    row=dict(text),
                    runtime_config=asdict(runtime),
                )
                logger.info(
                    "scheduler.skipped",
                    extra={"tenant_id": tenant_id, "text_id": text_id, "reason": "greenapi_not_ready"},
                )
                continue

            tenant_zone = ZoneInfo(runtime.timezone)
            now_local = tick_utc.astimezone(tenant_zone)
            minute_key = now_local.strftime("%H:%M")
            local_date = now_local.date().isoformat()
            _debug_log(
                debug_enabled,
                "timezone_conversion",
                tenant_id=tenant_id,
                text_id=text_id,
                timezone=runtime.timezone,
                tick_utc=tick_utc.isoformat(),
                now_local=now_local.isoformat(),
                minute_key=minute_key,
                local_date=local_date,
            )

            logger.info(
                "scheduler.timezone_resolved",
                extra={
                    "tenant_id": tenant_id,
                    "text_id": text_id,
                    "timezone": runtime.timezone,
                    "tick_utc": tick_utc.isoformat(),
                    "local_time": now_local.isoformat(),
                },
            )

            from app.database import db_session, list_text_schedule_rules

            with db_session(database_url) as conn:
                rules = list_text_schedule_rules(conn, text_id=text_id, enabled_only=True)
            _debug_log(
                debug_enabled,
                "rules_loaded",
                tenant_id=tenant_id,
                text_id=text_id,
                rules=[dict(rule) for rule in rules],
            )

            if not rules:
                _debug_log(
                    debug_enabled,
                    "skip_reason",
                    tenant_id=tenant_id,
                    text_id=text_id,
                    reason="no_rules",
                    runtime_config=asdict(runtime),
                )
                logger.info(
                    "scheduler.skipped", extra={"tenant_id": tenant_id, "text_id": text_id, "reason": "no_rules"}
                )
                continue

            for rule in rules:
                rule_id = int(rule["id"])
                slot = _rule_execution_label(rule, minute_key)
                _debug_log(
                    debug_enabled,
                    "rule_evaluation_start",
                    tenant_id=tenant_id,
                    text_id=text_id,
                    rule_id=rule_id,
                    scheduled_slot=slot,
                    minute_key=minute_key,
                    local_date=local_date,
                    now_local=now_local.isoformat(),
                    rule=dict(rule),
                )
                due_count = await _due_count_for_rule(
                    database_url=database_url,
                    text_id=text_id,
                    rule=rule,
                    local_date=local_date,
                    minute_key=minute_key,
                    now_local=now_local,
                    debug_enabled=debug_enabled,
                )
                _debug_log(
                    debug_enabled,
                    "rule_due_count",
                    tenant_id=tenant_id,
                    text_id=text_id,
                    rule_id=rule_id,
                    scheduled_slot=slot,
                    due_count=due_count,
                )
                if due_count <= 0:
                    continue
                logger.info(
                    "scheduler.due",
                    extra={
                        "tenant_id": tenant_id,
                        "text_id": text_id,
                        "rule_id": rule_id,
                        "scheduled_slot": slot,
                        "due_count": due_count,
                        "timezone": runtime.timezone,
                        "local_date": local_date,
                    },
                )
                for _ in range(due_count):
                    attempt_id = _create_attempt(
                        database_url=database_url,
                        tenant_id=tenant_id,
                        text_id=text_id,
                        rule_id=rule_id,
                        delivery_type=str(rule["delivery_type"]),
                        scheduled_slot=slot,
                        local_date=local_date,
                        timezone_name=runtime.timezone,
                        debug_enabled=debug_enabled,
                    )
                    try:
                        if rule["delivery_type"] == "poll":
                            _debug_log(
                                debug_enabled,
                                "poll_send_invocation",
                                tenant_id=tenant_id,
                                text_id=text_id,
                                rule_id=rule_id,
                                attempt_id=attempt_id,
                                scheduled_slot=slot,
                                runtime_config=asdict(runtime),
                            )
                            poll_id = await generate_and_send_poll(
                                settings=runtime,
                                database_url=database_url,
                                text_id=text_id,
                                scheduled_slot=slot,
                            )
                            sent += 1
                            _update_attempt(
                                database_url=database_url,
                                attempt_id=attempt_id,
                                status="sent",
                                poll_id=poll_id,
                                debug_enabled=debug_enabled,
                            )
                            _debug_log(
                                debug_enabled,
                                "poll_send_result",
                                tenant_id=tenant_id,
                                text_id=text_id,
                                rule_id=rule_id,
                                attempt_id=attempt_id,
                                poll_id=poll_id,
                                scheduled_slot=slot,
                            )
                            logger.info(
                                "scheduler.sent",
                                extra={
                                    "tenant_id": tenant_id,
                                    "text_id": text_id,
                                    "rule_id": rule_id,
                                    "scheduled_slot": slot,
                                    "poll_id": poll_id,
                                },
                            )
                        else:
                            _debug_log(
                                debug_enabled,
                                "summary_send_invocation",
                                tenant_id=tenant_id,
                                text_id=text_id,
                                rule_id=rule_id,
                                attempt_id=attempt_id,
                                scheduled_slot=slot,
                                runtime_config=asdict(runtime),
                            )
                            summary_count = await send_pending_summaries(
                                settings=runtime,
                                database_url=database_url,
                                text_id=text_id,
                            )
                            summary_sent += summary_count
                            _update_attempt(
                                database_url=database_url,
                                attempt_id=attempt_id,
                                status="sent",
                                summary_count=summary_count,
                                debug_enabled=debug_enabled,
                            )
                            _debug_log(
                                debug_enabled,
                                "summary_send_result",
                                tenant_id=tenant_id,
                                text_id=text_id,
                                rule_id=rule_id,
                                attempt_id=attempt_id,
                                summary_count=summary_count,
                                scheduled_slot=slot,
                            )
                            logger.info(
                                "scheduler.sent",
                                extra={
                                    "tenant_id": tenant_id,
                                    "text_id": text_id,
                                    "rule_id": rule_id,
                                    "scheduled_slot": slot,
                                    "summary_count": summary_count,
                                },
                            )
                    except Exception as exc:
                        last_error = str(exc)
                        _update_attempt(
                            database_url=database_url,
                            attempt_id=attempt_id,
                            status="failed",
                            error=str(exc),
                            debug_enabled=debug_enabled,
                        )
                        _debug_log(
                            debug_enabled,
                            "send_failure",
                            tenant_id=tenant_id,
                            text_id=text_id,
                            rule_id=rule_id,
                            attempt_id=attempt_id,
                            scheduled_slot=slot,
                            error=str(exc),
                        )
                        logger.exception(
                            "scheduler.failed",
                            extra={
                                "tenant_id": tenant_id,
                                "text_id": text_id,
                                "rule_id": rule_id,
                                "scheduled_slot": slot,
                                "timezone": runtime.timezone,
                            },
                        )
        except Exception as exc:
            last_error = str(exc)
            _debug_log(
                debug_enabled,
                "text_failure",
                tenant_id=tenant_id,
                text_id=text_id,
                timezone=runtime.timezone,
                error=str(exc),
                row=dict(text),
            )
            logger.exception(
                "scheduler.text_failed",
                extra={"tenant_id": tenant_id, "text_id": text_id, "timezone": runtime.timezone},
            )
            continue

    final_status = {
        "last_tick_at": tick_utc.isoformat(),
        "last_success_at": tick_utc.isoformat(),
        "last_error": last_error,
        "polls_sent": sent,
        "summaries_sent": summary_sent,
    }
    _write_scheduler_status(
        database_url=database_url,
        status=final_status,
        debug_enabled=debug_enabled,
        phase="tick_complete",
    )
    logger.info(
        "scheduler.tick_complete",
        extra={"tick_utc": tick_utc.isoformat(), "polls_sent": sent, "summaries_sent": summary_sent},
    )
    return sent


async def _due_count_for_rule(
    *,
    database_url: str,
    text_id: int,
    rule: dict[str, object],
    local_date: str,
    minute_key: str,
    now_local: datetime,
    debug_enabled: bool = False,
) -> int:
    from app.database import count_scheduled_send_attempts, db_session, get_random_rule_plan, upsert_random_rule_plan

    slot = _rule_execution_label(rule, minute_key)
    with db_session(database_url) as conn:
        existing_attempts = count_scheduled_send_attempts(
            conn,
            text_id=text_id,
            rule_id=int(rule["id"]),
            local_date=local_date,
            scheduled_slot=slot,
        )
    _debug_log(
        debug_enabled,
        "existing_attempts_loaded",
        text_id=text_id,
        rule_id=int(rule["id"]),
        local_date=local_date,
        scheduled_slot=slot,
        existing_attempts=existing_attempts,
    )

    if rule["rule_type"] == "random_window":
        with db_session(database_url) as conn:
            plan = get_random_rule_plan(conn, text_id=text_id, rule_id=int(rule["id"]), local_date=local_date)
            _debug_log(
                debug_enabled,
                "random_plan_lookup",
                text_id=text_id,
                rule_id=int(rule["id"]),
                local_date=local_date,
                plan=None if plan is None else dict(plan),
            )
            if plan is None:
                planned_times = _build_random_plan(rule, now_local.date(), debug_enabled=debug_enabled)
                plan = upsert_random_rule_plan(
                    conn,
                    text_id=text_id,
                    rule_id=int(rule["id"]),
                    local_date=local_date,
                    planned_times=planned_times,
                )
                _debug_log(
                    debug_enabled,
                    "random_plan_created",
                    text_id=text_id,
                    rule_id=int(rule["id"]),
                    local_date=local_date,
                    planned_times=planned_times,
                    plan=dict(plan),
                )
        planned_count = _planned_occurrences(plan["planned_times"], minute_key)
        due_count = max(planned_count - existing_attempts, 0)
        _debug_log(
            debug_enabled,
            "random_due_count",
            text_id=text_id,
            rule_id=int(rule["id"]),
            local_date=local_date,
            minute_key=minute_key,
            planned_times=plan["planned_times"],
            planned_count=planned_count,
            existing_attempts=existing_attempts,
            due_count=due_count,
        )
        return due_count

    trigger_count = _scheduled_count_for_rule(rule)
    matches = _fixed_rule_matches(rule, now_local, debug_enabled=debug_enabled)
    if trigger_count < 1 or not matches:
        _debug_log(
            debug_enabled,
            "fixed_due_count",
            text_id=text_id,
            rule_id=int(rule["id"]),
            local_date=local_date,
            minute_key=minute_key,
            trigger_count=trigger_count,
            matches=matches,
            existing_attempts=existing_attempts,
            due_count=0,
        )
        return 0
    due_count = max(trigger_count - existing_attempts, 0)
    _debug_log(
        debug_enabled,
        "fixed_due_count",
        text_id=text_id,
        rule_id=int(rule["id"]),
        local_date=local_date,
        minute_key=minute_key,
        trigger_count=trigger_count,
        matches=matches,
        existing_attempts=existing_attempts,
        due_count=due_count,
    )
    return due_count


def _create_attempt(
    *,
    database_url: str,
    tenant_id: int,
    text_id: int,
    rule_id: int,
    delivery_type: str,
    scheduled_slot: str,
    local_date: str,
    timezone_name: str,
    debug_enabled: bool = False,
) -> int:
    from app.database import create_scheduled_send_attempt, db_session

    with db_session(database_url) as conn:
        attempt_id = create_scheduled_send_attempt(
            conn,
            tenant_id=tenant_id,
            text_id=text_id,
            rule_id=rule_id,
            delivery_type=delivery_type,
            scheduled_slot=scheduled_slot,
            local_date=local_date,
            timezone=timezone_name,
        )
    _debug_log(
        debug_enabled,
        "attempt_created",
        attempt_id=attempt_id,
        tenant_id=tenant_id,
        text_id=text_id,
        rule_id=rule_id,
        delivery_type=delivery_type,
        scheduled_slot=scheduled_slot,
        local_date=local_date,
        timezone=timezone_name,
    )
    return attempt_id


def _update_attempt(
    *,
    database_url: str,
    attempt_id: int,
    status: str,
    poll_id: int | None = None,
    summary_count: int | None = None,
    error: str | None = None,
    debug_enabled: bool = False,
) -> None:
    from app.database import db_session, update_scheduled_send_attempt

    with db_session(database_url) as conn:
        update_scheduled_send_attempt(
            conn,
            attempt_id=attempt_id,
            status=status,
            poll_id=poll_id,
            summary_count=summary_count,
            error=error,
        )
    _debug_log(
        debug_enabled,
        "attempt_updated",
        attempt_id=attempt_id,
        status=status,
        poll_id=poll_id,
        summary_count=summary_count,
        error=error,
    )


def _normalize_utc(now_utc: datetime | None) -> datetime:
    if now_utc is None:
        return datetime.now(timezone.utc).replace(second=0, microsecond=0)
    if now_utc.tzinfo is None:
        return now_utc.replace(tzinfo=timezone.utc, second=0, microsecond=0)
    return now_utc.astimezone(timezone.utc).replace(second=0, microsecond=0)


def _scheduled_count_for_rule(rule: dict[str, object]) -> int:
    if str(rule.get("count_mode")) == "range":
        return random.randint(int(rule.get("count_min") or 1), int(rule.get("count_max") or 1))
    return int(rule.get("count_value") or 1)


def _fixed_rule_matches(rule: dict[str, object], now_local: datetime, *, debug_enabled: bool = False) -> bool:
    minute_key = now_local.strftime("%H:%M")
    if str(rule.get("time") or "") != minute_key:
        _debug_log(
            debug_enabled,
            "fixed_rule_match",
            rule_id=int(rule["id"]),
            rule_type=str(rule.get("rule_type")),
            configured_time=str(rule.get("time") or ""),
            minute_key=minute_key,
            now_local=now_local.isoformat(),
            matched=False,
            reason="time_mismatch",
        )
        return False
    rule_type = str(rule.get("rule_type"))
    if rule_type == "daily_time":
        _debug_log(
            debug_enabled,
            "fixed_rule_match",
            rule_id=int(rule["id"]),
            rule_type=rule_type,
            configured_time=str(rule.get("time") or ""),
            minute_key=minute_key,
            now_local=now_local.isoformat(),
            matched=True,
        )
        return True
    if rule_type == "weekday_time":
        weekdays = {int(day) for day in rule.get("weekdays", []) if isinstance(day, int)}
        matched = now_local.weekday() in weekdays
        _debug_log(
            debug_enabled,
            "fixed_rule_match",
            rule_id=int(rule["id"]),
            rule_type=rule_type,
            configured_time=str(rule.get("time") or ""),
            minute_key=minute_key,
            now_local=now_local.isoformat(),
            weekdays=sorted(weekdays),
            matched=matched,
        )
        return matched
    if rule_type == "month_date_time":
        month_dates = {int(day) for day in rule.get("month_dates", []) if isinstance(day, int)}
        matched = now_local.day in month_dates
        _debug_log(
            debug_enabled,
            "fixed_rule_match",
            rule_id=int(rule["id"]),
            rule_type=rule_type,
            configured_time=str(rule.get("time") or ""),
            minute_key=minute_key,
            now_local=now_local.isoformat(),
            month_dates=sorted(month_dates),
            matched=matched,
        )
        return matched
    _debug_log(
        debug_enabled,
        "fixed_rule_match",
        rule_id=int(rule["id"]),
        rule_type=rule_type,
        configured_time=str(rule.get("time") or ""),
        minute_key=minute_key,
        now_local=now_local.isoformat(),
        matched=False,
        reason="unsupported_rule_type",
    )
    return False


def _planned_occurrences(values: list[str], minute_key: str) -> int:
    return sum(1 for value in values if value == minute_key)


def _build_random_plan(rule: dict[str, object], local_date: date, *, debug_enabled: bool = False) -> list[str]:
    start = datetime.combine(local_date, _parse_hhmm(str(rule["window_start"])))
    end = datetime.combine(local_date, _parse_hhmm(str(rule["window_end"])))
    minute_span = int((end - start).total_seconds() // 60)
    count = _scheduled_count_for_rule(rule)
    planned: list[str] = []
    for _ in range(count):
        offset = random.randint(0, max(minute_span - 1, 0))
        planned.append((start + timedelta(minutes=offset)).strftime("%H:%M"))
    planned.sort()
    _debug_log(
        debug_enabled,
        "random_plan_built",
        rule_id=int(rule["id"]),
        local_date=local_date.isoformat(),
        window_start=str(rule["window_start"]),
        window_end=str(rule["window_end"]),
        minute_span=minute_span,
        count=count,
        planned_times=planned,
    )
    return planned


def _parse_hhmm(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def _rule_execution_label(rule: dict[str, object], minute_key: str) -> str:
    return f"rule:{int(rule['id'])}:{rule['delivery_type']}:{minute_key}"
