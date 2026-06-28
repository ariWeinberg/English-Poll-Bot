from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.core.logging import get_logger
from app.services import generate_and_send_poll, runtime_config_from_row, send_pending_summaries

logger = get_logger("scheduler")


def build_scheduler(database_url: str) -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=timezone.utc)

    scheduler.add_job(
        run_due_jobs,
        CronTrigger(minute="*", timezone=timezone.utc),
        kwargs={"database_url": database_url},
        id="due_jobs",
        replace_existing=True,
        max_instances=1,
    )
    return scheduler


async def run_due_jobs(*, database_url: str) -> int:
    from zoneinfo import ZoneInfo

    from app.database import (
        db_session,
        get_random_rule_plan,
        list_pending_texts,
        list_text_schedule_rules,
        mark_random_rule_plan_executed,
        upsert_random_rule_plan,
    )

    sent = 0
    summary_sent = 0
    with db_session(database_url) as conn:
        texts = list_pending_texts(conn)
    logger.info("scheduler.tick", extra={"text_count": len(texts)})
    for text in texts:
        runtime = runtime_config_from_row(text)
        if not runtime.scheduler_enabled or not runtime.greenapi_ready:
            logger.info(
                "scheduler.skip_text",
                extra={
                    "tenant_id": runtime.tenant_id,
                    "text_id": int(text["id"]),
                    "scheduler_enabled": runtime.scheduler_enabled,
                    "greenapi_ready": runtime.greenapi_ready,
                },
            )
            continue
        now_local = datetime.now(ZoneInfo(runtime.timezone))
        minute_key = now_local.strftime("%H:%M")
        local_date = now_local.date()
        with db_session(database_url) as conn:
            rules = list_text_schedule_rules(conn, text_id=int(text["id"]), enabled_only=True)
        for rule in rules:
            if rule["rule_type"] == "random_window":
                with db_session(database_url) as conn:
                    plan = get_random_rule_plan(conn, rule_id=int(rule["id"]), local_date=local_date.isoformat())
                    if plan is None:
                        planned_times = _build_random_plan(rule, local_date)
                        plan = upsert_random_rule_plan(
                            conn,
                            text_id=int(text["id"]),
                            rule_id=int(rule["id"]),
                            local_date=local_date.isoformat(),
                            planned_times=planned_times,
                        )
                due_count = _planned_occurrences(plan["planned_times"], minute_key) - _planned_occurrences(
                    plan["executed_times"], minute_key
                )
                if due_count <= 0:
                    continue
                actual_count = due_count
                if rule["delivery_type"] == "poll":
                    for _ in range(actual_count):
                        slot = _rule_execution_label(rule, minute_key)
                        logger.info(
                            "scheduler.send_poll_due",
                            extra={"tenant_id": runtime.tenant_id, "text_id": int(text["id"]), "scheduled_slot": slot},
                        )
                        await generate_and_send_poll(
                            settings=runtime,
                            database_url=database_url,
                            text_id=int(text["id"]),
                            scheduled_slot=slot,
                        )
                        sent += 1
                else:
                    for _ in range(actual_count):
                        summary_count = await send_pending_summaries(
                            settings=runtime, database_url=database_url, text_id=int(text["id"])
                        )
                        summary_sent += summary_count
                with db_session(database_url) as conn:
                    mark_random_rule_plan_executed(
                        conn,
                        rule_id=int(rule["id"]),
                        local_date=local_date.isoformat(),
                        executed_times=[*plan["executed_times"], *([minute_key] * actual_count)],
                    )
                continue

            trigger_count = _scheduled_count_for_rule(rule)
            if trigger_count < 1:
                continue
            if not _fixed_rule_matches(rule, now_local):
                continue
            if rule["delivery_type"] == "poll":
                for _ in range(trigger_count):
                    slot = _rule_execution_label(rule, minute_key)
                    logger.info(
                        "scheduler.send_poll_due",
                        extra={"tenant_id": runtime.tenant_id, "text_id": int(text["id"]), "scheduled_slot": slot},
                    )
                    await generate_and_send_poll(
                        settings=runtime,
                        database_url=database_url,
                        text_id=int(text["id"]),
                        scheduled_slot=slot,
                    )
                    sent += 1
            else:
                for _ in range(trigger_count):
                    summary_count = await send_pending_summaries(
                        settings=runtime, database_url=database_url, text_id=int(text["id"])
                    )
                    summary_sent += summary_count
                    logger.info(
                        "scheduler.summary_due",
                        extra={"tenant_id": runtime.tenant_id, "text_id": int(text["id"]), "sent_count": summary_count},
                    )
    logger.info("scheduler.tick_complete", extra={"polls_sent": sent, "summaries_sent": summary_sent})
    return sent


def _scheduled_count_for_rule(rule: dict[str, object]) -> int:
    if str(rule.get("count_mode")) == "range":
        return random.randint(int(rule.get("count_min") or 1), int(rule.get("count_max") or 1))
    return int(rule.get("count_value") or 1)


def _fixed_rule_matches(rule: dict[str, object], now_local: datetime) -> bool:
    minute_key = now_local.strftime("%H:%M")
    if str(rule.get("time") or "") != minute_key:
        return False
    rule_type = str(rule.get("rule_type"))
    if rule_type == "daily_time":
        return True
    if rule_type == "weekday_time":
        weekdays = {int(day) for day in rule.get("weekdays", []) if isinstance(day, int)}
        return now_local.weekday() in weekdays
    if rule_type == "month_date_time":
        month_dates = {int(day) for day in rule.get("month_dates", []) if isinstance(day, int)}
        return now_local.day in month_dates
    return False


def _planned_occurrences(values: list[str], minute_key: str) -> int:
    return sum(1 for value in values if value == minute_key)


def _build_random_plan(rule: dict[str, object], local_date: date) -> list[str]:
    start = datetime.combine(local_date, _parse_hhmm(str(rule["window_start"])))
    end = datetime.combine(local_date, _parse_hhmm(str(rule["window_end"])))
    minute_span = int((end - start).total_seconds() // 60)
    count = _scheduled_count_for_rule(rule)
    planned: list[str] = []
    for _ in range(count):
        offset = random.randint(0, max(minute_span - 1, 0))
        planned.append((start + timedelta(minutes=offset)).strftime("%H:%M"))
    planned.sort()
    return planned


def _parse_hhmm(value: str) -> time:
    return datetime.strptime(value, "%H:%M").time()


def _rule_execution_label(rule: dict[str, object], minute_key: str) -> str:
    return f"rule:{int(rule['id'])}:{rule['delivery_type']}:{minute_key}"
