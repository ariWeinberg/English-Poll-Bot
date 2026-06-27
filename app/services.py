from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

from app.database import (
    POLL_POOL_REFILL_BATCH_SIZE,
    compact_queued_poll_ranks,
    count_queued_polls,
    create_poll,
    db_session,
    get_next_queued_poll,
    get_contact_profile,
    get_poll_by_message_id,
    get_poll_by_message_id_for_tenant,
    get_source_text,
    get_tenant,
    get_text,
    get_text_poll_history,
    get_poll_pool_refill_threshold_count,
    get_text_pool_tail_rank,
    list_pending_texts,
    list_unsummarized_polls,
    mark_poll_failed,
    mark_poll_sent,
    mark_summary_sent,
    poll_stats,
    replace_poll_votes,
    upsert_contact_profile,
)
from app.database import normalize_phone_number
from app.greenapi import GreenAPIClient, GreenAPIConfig
from app.question_generator import GeminiQuestionGenerator, GeneratedQuestion


@dataclass(frozen=True)
class RuntimeConfig:
    tenant_id: int
    tenant_name: str
    greenapi_api_url: str
    greenapi_id_instance: str
    greenapi_api_token_instance: str
    gemini_api_key: str
    gemini_model: str
    timezone: str
    summary_enabled: bool
    scheduler_enabled: bool

    @property
    def greenapi_ready(self) -> bool:
        return all(
            (
                bool(self.greenapi_api_url.strip()),
                bool(self.greenapi_id_instance.strip()),
                bool(self.greenapi_api_token_instance.strip()),
            )
        )

    @property
    def gemini_ready(self) -> bool:
        return bool(self.gemini_api_key.strip())


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def load_runtime_config(database_url: str, tenant_id: int | None = None) -> RuntimeConfig:
    with db_session(database_url) as conn:
        tenant = get_tenant(conn, tenant_id) if tenant_id is not None else None
        if tenant is None:
            from app.database import get_active_tenant

            tenant = get_active_tenant(conn)
    return RuntimeConfig(
        tenant_id=int(tenant["id"]),
        tenant_name=tenant["name"],
        greenapi_api_url=str(tenant["greenapi_api_url"]).rstrip("/"),
        greenapi_id_instance=str(tenant["greenapi_id_instance"]),
        greenapi_api_token_instance=str(tenant["greenapi_api_token_instance"]),
        gemini_api_key=str(tenant["gemini_api_key"]),
        gemini_model=str(tenant["gemini_model"]),
        timezone=str(tenant["timezone"]),
        summary_enabled=_as_bool(tenant["summary_enabled"], True),
        scheduler_enabled=_as_bool(tenant["scheduler_enabled"], True),
    )


def create_greenapi_client(settings: RuntimeConfig) -> GreenAPIClient:
    return GreenAPIClient(
        GreenAPIConfig(
            api_url=settings.greenapi_api_url,
            id_instance=settings.greenapi_id_instance,
            api_token_instance=settings.greenapi_api_token_instance,
        )
    )


def create_question_generator(settings: RuntimeConfig) -> GeminiQuestionGenerator:
    return GeminiQuestionGenerator(api_key=settings.gemini_api_key, model=settings.gemini_model)


def _poll_options(row: dict[str, Any]) -> list[str]:
    options = row.get("options")
    if isinstance(options, list):
        return [str(option) for option in options]
    raw = row.get("options_json")
    if not isinstance(raw, str):
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(option) for option in parsed]


def _history_signature(row: dict[str, Any]) -> str:
    question = str(row.get("question") or "").strip()
    if not question:
        return ""
    return question.lower()


def _build_duplicate_context(rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in rows:
        question = str(row.get("question") or "").strip()
        if not question:
            continue
        status = str(row.get("status") or "").strip() or "unknown"
        options_text = ", ".join(
            option.strip() for option in row.get("options", []) if isinstance(option, str) and option.strip()
        )
        if not options_text:
            lines.append(f"- [{status}] {question}")
        else:
            lines.append(f"- [{status}] {question} | options: {options_text}")
    return "\n".join(lines)


def _serialize_generated_history(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    history: list[dict[str, Any]] = []
    for row in rows:
        history.append(
            {
                "question": row.get("question"),
                "options": _poll_options(row),
                "status": row.get("status"),
            }
        )
    return history


async def generate_question(
    settings: RuntimeConfig,
    source_text: str,
    *,
    prior_poll_history: list[dict[str, Any]] | None = None,
) -> GeneratedQuestion:
    if not source_text.strip():
        raise ValueError("Add source text before generating a question.")
    if not settings.gemini_ready:
        raise ValueError("Gemini configuration is incomplete.")
    generator = create_question_generator(settings)
    history = _serialize_generated_history(prior_poll_history or [])
    return await asyncio.to_thread(
        generator.generate,
        source_text,
        duplicate_context=_build_duplicate_context(history),
    )


async def generate_poll_batch(
    settings: RuntimeConfig,
    source_text: str,
    *,
    prior_poll_history: list[dict[str, Any]],
    count: int,
) -> list[GeneratedQuestion]:
    if not source_text.strip():
        raise ValueError("Add source text before generating a question.")
    if not settings.gemini_ready:
        raise ValueError("Gemini configuration is incomplete.")
    generator = create_question_generator(settings)
    history = _serialize_generated_history(prior_poll_history)
    return await asyncio.to_thread(
        generator.generate_batch,
        source_text,
        count=count,
        duplicate_context=_build_duplicate_context(history),
        existing_signatures={_history_signature(row) for row in history},
    )


async def fill_poll_pool(
    *,
    settings: RuntimeConfig,
    database_url: str,
    text_id: int,
    count: int = POLL_POOL_REFILL_BATCH_SIZE,
) -> list[int]:
    with db_session(database_url) as conn:
        text = get_text(conn, text_id)
        if text is None:
            raise ValueError("Text not found.")
        history = get_text_poll_history(conn, text_id=text_id)
        source_text = get_source_text(conn, text_id)
        tail_rank = get_text_pool_tail_rank(conn, text_id=text_id)

    generated_batch = await generate_poll_batch(
        settings,
        source_text,
        prior_poll_history=history,
        count=count,
    )

    created_ids: list[int] = []
    with db_session(database_url) as conn:
        next_rank = tail_rank
        for generated in generated_batch:
            next_rank += 1
            created_ids.append(
                create_poll(
                    conn,
                    tenant_id=settings.tenant_id,
                    text_id=text_id,
                    question=generated.question,
                    options=generated.options,
                    correct_option=generated.correct_option,
                    explanation=generated.explanation,
                    chat_id=text["chat_id"],
                    generated_from_text=source_text,
                    scheduled_slot=None,
                    status="queued",
                    pool_rank=next_rank,
                )
            )
    return created_ids


async def _refill_pool_if_needed(*, settings: RuntimeConfig, database_url: str, text_id: int) -> None:
    if not settings.gemini_ready:
        return
    with db_session(database_url) as conn:
        queued_count = count_queued_polls(conn, text_id=text_id)
        threshold_count = get_poll_pool_refill_threshold_count(conn, text_id=text_id)
    if queued_count < threshold_count:
        await fill_poll_pool(settings=settings, database_url=database_url, text_id=text_id)


async def preview_next_pooled_poll(*, settings: RuntimeConfig, database_url: str, text_id: int) -> GeneratedQuestion:
    with db_session(database_url) as conn:
        text = get_text(conn, text_id)
        if text is None:
            raise ValueError("Text not found.")
        queued = get_next_queued_poll(conn, text_id=text_id)
    if queued is None:
        await fill_poll_pool(settings=settings, database_url=database_url, text_id=text_id)
        with db_session(database_url) as conn:
            queued = get_next_queued_poll(conn, text_id=text_id)
    if queued is None:
        raise ValueError("Unable to prepare a preview poll.")
    return GeneratedQuestion(
        question=str(queued["question"]),
        options=_poll_options(queued),
        correct_option=str(queued["correct_option"]),
        explanation=str(queued.get("explanation") or ""),
    )


async def generate_and_send_poll(
    *,
    settings: RuntimeConfig,
    database_url: str,
    text_id: int,
    scheduled_slot: str | None = None,
) -> int:
    if not settings.greenapi_ready:
        raise ValueError("GreenAPI configuration is incomplete.")
    with db_session(database_url) as conn:
        text = get_text(conn, text_id)
        if text is None:
            raise ValueError("Text not found.")
        queued = get_next_queued_poll(conn, text_id=text_id)
        source_text = get_source_text(conn, text_id)
        history = get_text_poll_history(conn, text_id=text_id)

    used_pool = queued is not None
    if queued is None:
        generated = await generate_question(settings, source_text, prior_poll_history=history)
        with db_session(database_url) as conn:
            poll_id = create_poll(
                conn,
                tenant_id=settings.tenant_id,
                text_id=text_id,
                question=generated.question,
                options=generated.options,
                correct_option=generated.correct_option,
                explanation=generated.explanation,
                chat_id=text["chat_id"],
                generated_from_text=source_text,
                scheduled_slot=scheduled_slot,
            )
    else:
        poll_id = int(queued["id"])
        generated = GeneratedQuestion(
            question=str(queued["question"]),
            options=_poll_options(queued),
            correct_option=str(queued["correct_option"]),
            explanation=str(queued.get("explanation") or ""),
        )
    try:
        message_id = await create_greenapi_client(settings).send_poll(
            chat_id=text["chat_id"],
            question=generated.question,
            options=generated.options,
        )
    except Exception as exc:
        with db_session(database_url) as conn:
            mark_poll_failed(conn, poll_id, str(exc))
            if used_pool:
                compact_queued_poll_ranks(conn, text_id=text_id)
        raise
    with db_session(database_url) as conn:
        mark_poll_sent(conn, poll_id, message_id, scheduled_slot=scheduled_slot)
        if used_pool:
            compact_queued_poll_ranks(conn, text_id=text_id)
    if used_pool or settings.gemini_ready:
        await _refill_pool_if_needed(settings=settings, database_url=database_url, text_id=text_id)
    return poll_id


def _parse_voter_record(value: Any) -> dict[str, str | None] | None:
    if isinstance(value, str):
        voter_wid = value.strip()
        if not voter_wid:
            return None
        return {
            "voter_wid": voter_wid,
            "voter_name": None,
            "phone_number": normalize_phone_number(voter_wid),
        }
    if not isinstance(value, dict):
        return None
    voter_wid = str(
        value.get("voterWid")
        or value.get("wid")
        or value.get("voterId")
        or value.get("chatId")
        or value.get("id")
        or ""
    ).strip()
    if not voter_wid:
        return None
    voter_name = (
        str(
            value.get("contactName") or value.get("senderName") or value.get("name") or value.get("pushName") or ""
        ).strip()
        or None
    )
    phone_number = str(value.get("phoneNumber") or value.get("phone") or "").strip() or normalize_phone_number(
        voter_wid
    )
    return {
        "voter_wid": voter_wid,
        "voter_name": voter_name,
        "phone_number": phone_number,
    }


def parse_poll_update(payload: dict[str, Any]) -> tuple[str, dict[str, list[dict[str, str | None]]]] | None:
    if payload.get("typeWebhook") != "incomingMessageReceived":
        return None
    message_data = payload.get("messageData") or {}
    if message_data.get("typeMessage") != "pollUpdateMessage":
        return None
    poll_data = message_data.get("pollMessageData") or {}
    stanza_id = poll_data.get("stanzaId")
    votes = poll_data.get("votes")
    if not stanza_id or not isinstance(votes, list):
        return None

    option_voters: dict[str, list[dict[str, str | None]]] = {}
    for vote in votes:
        if not isinstance(vote, dict):
            continue
        option = str(vote.get("optionName", "")).strip()
        voters = vote.get("optionVoters") or []
        if option:
            option_voters[option] = [record for voter in voters if (record := _parse_voter_record(voter)) is not None]
    return str(stanza_id), option_voters


async def _resolve_contact_name(
    *,
    database_url: str,
    tenant_id: int,
    voter_wid: str,
    voter_name: str | None,
    phone_number: str | None,
) -> str | None:
    cleaned_name = voter_name.strip() if voter_name else ""
    cleaned_phone = phone_number.strip() if phone_number else normalize_phone_number(voter_wid)
    with db_session(database_url) as conn:
        cached = get_contact_profile(conn, tenant_id=tenant_id, voter_wid=voter_wid)
        cached_name = str(cached["display_name"]).strip() if cached and cached["display_name"] else None
        if cleaned_name:
            upsert_contact_profile(
                conn,
                tenant_id=tenant_id,
                voter_wid=voter_wid,
                phone_number=cleaned_phone,
                display_name=cleaned_name,
            )
            return cleaned_name
        if cached_name:
            upsert_contact_profile(conn, tenant_id=tenant_id, voter_wid=voter_wid, phone_number=cleaned_phone)
            return cached_name
        tenant = get_tenant(conn, tenant_id)
    if tenant is None:
        return None
    settings = RuntimeConfig(
        tenant_id=int(tenant["id"]),
        tenant_name=str(tenant["name"]),
        greenapi_api_url=str(tenant["greenapi_api_url"]).rstrip("/"),
        greenapi_id_instance=str(tenant["greenapi_id_instance"]),
        greenapi_api_token_instance=str(tenant["greenapi_api_token_instance"]),
        gemini_api_key=str(tenant["gemini_api_key"]),
        gemini_model=str(tenant["gemini_model"]),
        timezone=str(tenant["timezone"]),
        summary_enabled=_as_bool(tenant["summary_enabled"], True),
        scheduler_enabled=_as_bool(tenant["scheduler_enabled"], True),
    )
    resolved_name: str | None = None
    if settings.greenapi_ready:
        try:
            resolved_name = await create_greenapi_client(settings).get_contact_name(chat_id=voter_wid)
        except Exception:
            resolved_name = None
    with db_session(database_url) as conn:
        upsert_contact_profile(
            conn,
            tenant_id=tenant_id,
            voter_wid=voter_wid,
            phone_number=cleaned_phone,
            display_name=resolved_name,
        )
    return resolved_name


async def handle_greenapi_webhook_async(
    *, database_url: str, payload: dict[str, Any], tenant_id: int | None = None
) -> bool:
    parsed = parse_poll_update(payload)
    if parsed is None:
        return False
    message_id, option_voters = parsed
    with db_session(database_url) as conn:
        poll = (
            get_poll_by_message_id_for_tenant(conn, message_id=message_id, tenant_id=tenant_id)
            if tenant_id is not None
            else get_poll_by_message_id(conn, message_id)
        )
    if poll is None:
        return False
    tenant_key = int(poll["tenant_id"])
    enriched: dict[str, list[dict[str, str | None]]] = {}
    for option_name, voters in option_voters.items():
        enriched[option_name] = []
        for voter in voters:
            voter_wid = str(voter.get("voter_wid") or "").strip()
            if not voter_wid:
                continue
            phone_number = str(voter.get("phone_number") or "").strip() or normalize_phone_number(voter_wid)
            voter_name = await _resolve_contact_name(
                database_url=database_url,
                tenant_id=tenant_key,
                voter_wid=voter_wid,
                voter_name=voter.get("voter_name"),
                phone_number=phone_number,
            )
            enriched[option_name].append(
                {
                    "voter_wid": voter_wid,
                    "voter_name": voter_name,
                    "phone_number": phone_number,
                }
            )
    with db_session(database_url) as conn:
        live_poll = (
            get_poll_by_message_id_for_tenant(conn, message_id=message_id, tenant_id=tenant_id)
            if tenant_id is not None
            else get_poll_by_message_id(conn, message_id)
        )
        if live_poll is None:
            return False
        replace_poll_votes(conn, poll=live_poll, option_voters=enriched)
    return True


def handle_greenapi_webhook(*, database_url: str, payload: dict[str, Any], tenant_id: int | None = None) -> bool:
    return asyncio.run(handle_greenapi_webhook_async(database_url=database_url, payload=payload, tenant_id=tenant_id))


def build_summary_text(stats: dict[str, Any]) -> str:
    poll = stats["poll"]
    lines = [
        f"Poll summary: {poll['question']}",
        f"Total votes: {stats['total']}",
        f"Correct answer: {poll['correct_option']}",
        f"Correct rate: {stats['correct_rate']:.1f}%",
        "",
        "Results:",
    ]
    total = stats["total"] or 1
    for option, count in stats["counts"].items():
        percent = count / total * 100
        marker = " (correct)" if option == poll["correct_option"] else ""
        lines.append(f"- {option}: {count} ({percent:.1f}%){marker}")
    if poll["explanation"]:
        lines.extend(["", f"Explanation: {poll['explanation']}"])
    return "\n".join(lines)


async def send_pending_summaries(*, settings: RuntimeConfig, database_url: str, text_id: int | None = None) -> int:
    if not settings.summary_enabled or not settings.greenapi_ready:
        return 0
    sent = 0
    client = create_greenapi_client(settings)
    with db_session(database_url) as conn:
        polls = list_unsummarized_polls(conn, tenant_id=settings.tenant_id)
        if text_id is not None:
            polls = [poll for poll in polls if poll["text_id"] == text_id]
    for poll in polls:
        with db_session(database_url) as conn:
            stats = poll_stats(conn, poll)
        await client.send_message(chat_id=poll["chat_id"], message=build_summary_text(stats))
        with db_session(database_url) as conn:
            mark_summary_sent(conn, poll["id"])
        sent += 1
    return sent


def texts_due_now(database_url: str, minute_key: str) -> list[tuple[RuntimeConfig, Any]]:
    due: list[tuple[RuntimeConfig, Any]] = []
    with db_session(database_url) as conn:
        texts = list_pending_texts(conn)
        for text in texts:
            runtime = load_runtime_config(database_url, int(text["tenant_id"]))
            if not runtime.scheduler_enabled or not runtime.greenapi_ready or not runtime.gemini_ready:
                continue
            if text["enabled"] and minute_key in {
                text["morning_time"],
                text["evening_time"],
                text["summary_time_morning"],
                text["summary_time_evening"],
            }:
                due.append((runtime, text))
    return due
