from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.database import (
    create_poll,
    db_session,
    get_poll_by_message_id,
    get_poll_by_message_id_for_tenant,
    get_source_text,
    get_tenant,
    get_text,
    list_pending_texts,
    list_unsummarized_polls,
    mark_poll_failed,
    mark_poll_sent,
    mark_summary_sent,
    poll_stats,
    replace_poll_votes,
)
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


async def generate_question(settings: RuntimeConfig, source_text: str) -> GeneratedQuestion:
    if not source_text.strip():
        raise ValueError("Add source text before generating a question.")
    if not settings.gemini_ready:
        raise ValueError("Gemini configuration is incomplete.")
    generator = create_question_generator(settings)
    return await asyncio.to_thread(generator.generate, source_text)


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
        source_text = get_source_text(conn, text_id)
    generated = await generate_question(settings, source_text)
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
    try:
        message_id = await create_greenapi_client(settings).send_poll(
            chat_id=text["chat_id"],
            question=generated.question,
            options=generated.options,
        )
    except Exception as exc:
        with db_session(database_url) as conn:
            mark_poll_failed(conn, poll_id, str(exc))
        raise
    with db_session(database_url) as conn:
        mark_poll_sent(conn, poll_id, message_id)
    return poll_id


def parse_poll_update(payload: dict[str, Any]) -> tuple[str, dict[str, list[str]]] | None:
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

    option_voters: dict[str, list[str]] = {}
    for vote in votes:
        if not isinstance(vote, dict):
            continue
        option = str(vote.get("optionName", "")).strip()
        voters = vote.get("optionVoters") or []
        if option:
            option_voters[option] = [str(voter) for voter in voters]
    return str(stanza_id), option_voters


def handle_greenapi_webhook(*, database_url: str, payload: dict[str, Any], tenant_id: int | None = None) -> bool:
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
        replace_poll_votes(conn, poll_id=poll["id"], option_voters=option_voters)
    return True


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
            if text["enabled"] and minute_key in {text["morning_time"], text["evening_time"], text["summary_time_morning"], text["summary_time_evening"]}:
                due.append((runtime, text))
    return due
