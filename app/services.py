from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from typing import Any, Callable, Literal

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
    list_coverage_participants,
    list_chat_participants,
    list_tenant_group_chats,
    list_pending_texts,
    list_unsummarized_polls,
    mark_poll_failed,
    mark_poll_sent,
    mark_summary_sent,
    poll_stats,
    replace_poll_votes,
    snapshot_poll_recipients,
    sync_tenant_group_chats,
    sync_chat_participants,
    upsert_contact_profile,
)
from app.database import normalize_phone_number
from app.core.logging import get_logger
from app.greenapi import GreenAPIClient, GreenAPIConfig
from app.question_generator import GeminiQuestionGenerator, GeneratedQuestion

logger = get_logger("services")


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


@dataclass(frozen=True)
class WebhookDecision:
    handled: bool
    status: Literal["accepted", "ignored", "error"]
    reason: str
    type_webhook: str | None = None
    message_type: str | None = None
    greenapi_message_id: str | None = None
    poll_id: int | None = None
    error: str | None = None


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
    return runtime_config_from_row(tenant)


def runtime_config_from_row(
    tenant: dict[str, Any],
    *,
    debug_logger: Callable[[str, dict[str, Any]], None] | None = None,
) -> RuntimeConfig:
    tenant_name = tenant.get("name")
    if tenant_name is None:
        tenant_name = tenant.get("tenant_name")
    tenant_id = tenant.get("tenant_id")
    if tenant_id is None:
        tenant_id = tenant["id"]
    runtime = RuntimeConfig(
        tenant_id=int(tenant_id),
        tenant_name=str(tenant_name or ""),
        greenapi_api_url=str(tenant["greenapi_api_url"]).rstrip("/"),
        greenapi_id_instance=str(tenant["greenapi_id_instance"]),
        greenapi_api_token_instance=str(tenant["greenapi_api_token_instance"]),
        gemini_api_key=str(tenant["gemini_api_key"]),
        gemini_model=str(tenant["gemini_model"]),
        timezone=str(tenant["timezone"]),
        summary_enabled=_as_bool(tenant.get("summary_enabled"), True),
        scheduler_enabled=_as_bool(tenant.get("scheduler_enabled"), True),
    )
    if debug_logger is not None:
        debug_logger(
            "runtime_config_from_row",
            {
                "row": dict(tenant),
                "runtime_config": asdict(runtime),
                "greenapi_ready": runtime.greenapi_ready,
                "gemini_ready": runtime.gemini_ready,
            },
        )
    return runtime


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
    logger.info(
        "poll_pool.refill_start",
        extra={"tenant_id": settings.tenant_id, "text_id": text_id, "requested_count": count},
    )
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
    logger.info(
        "poll_pool.refill_complete",
        extra={"tenant_id": settings.tenant_id, "text_id": text_id, "created_count": len(created_ids)},
    )
    return created_ids


async def _refill_pool_if_needed(*, settings: RuntimeConfig, database_url: str, text_id: int) -> None:
    if not settings.gemini_ready:
        logger.info(
            "poll_pool.refill_skip",
            extra={"tenant_id": settings.tenant_id, "text_id": text_id, "reason": "gemini_not_ready"},
        )
        return
    with db_session(database_url) as conn:
        queued_count = count_queued_polls(conn, text_id=text_id)
        threshold_count = get_poll_pool_refill_threshold_count(conn, text_id=text_id)
    if queued_count < threshold_count:
        await fill_poll_pool(settings=settings, database_url=database_url, text_id=text_id)


async def sync_text_roster(
    *,
    settings: RuntimeConfig,
    database_url: str,
    text_id: int,
) -> dict[str, Any]:
    if not settings.greenapi_ready:
        raise ValueError("GreenAPI configuration is incomplete.")
    with db_session(database_url) as conn:
        text = get_text(conn, text_id)
        if text is None:
            raise ValueError("Text not found.")
        if int(text["tenant_id"]) != settings.tenant_id:
            raise ValueError("Text not found.")
    chat_id = str(text["chat_id"] or "").strip()
    if not chat_id:
        raise ValueError("Text chat ID is required for roster sync.")
    participants = await create_greenapi_client(settings).get_group_participants(chat_id=chat_id)
    with db_session(database_url) as conn:
        synced_at = sync_chat_participants(
            conn,
            tenant_id=settings.tenant_id,
            chat_id=chat_id,
            participants=participants,
        )
        items = list_chat_participants(conn, tenant_id=settings.tenant_id, chat_id=chat_id)
    active_count = sum(1 for item in items if item["is_active_in_chat"])
    excluded_count = sum(1 for item in items if item["excluded_from_coverage"])
    return {
        "text_id": text_id,
        "chat_id": chat_id,
        "last_synced_at": synced_at,
        "active_count": active_count,
        "excluded_count": excluded_count,
        "items": items,
    }


async def refresh_tenant_group_chats(
    *,
    settings: RuntimeConfig,
    database_url: str,
) -> list[dict[str, Any]]:
    if not settings.greenapi_ready:
        raise ValueError("GreenAPI configuration is incomplete.")
    chats = await create_greenapi_client(settings).get_group_chats()
    with db_session(database_url) as conn:
        return sync_tenant_group_chats(conn, tenant_id=settings.tenant_id, chats=chats)


def list_known_tenant_group_chats(
    *,
    database_url: str,
    tenant_id: int,
    include_blocked: bool = True,
) -> list[dict[str, Any]]:
    with db_session(database_url) as conn:
        return list_tenant_group_chats(conn, tenant_id=tenant_id, include_blocked=include_blocked)


async def prepare_poll_recipient_snapshot(
    *,
    settings: RuntimeConfig,
    database_url: str,
    poll_id: int,
    text_id: int,
    chat_id: str,
) -> dict[str, Any]:
    snapshot_source = "unavailable"
    snapshot_synced_at: str | None = None
    participants: list[dict[str, Any]] = []
    if settings.greenapi_ready:
        try:
            roster = await sync_text_roster(settings=settings, database_url=database_url, text_id=text_id)
            snapshot_source = "live_sync"
            snapshot_synced_at = roster["last_synced_at"]
            participants = [
                item for item in roster["items"] if item["is_active_in_chat"] and not item["excluded_from_coverage"]
            ]
        except Exception:
            logger.exception(
                "poll_roster.sync_failed",
                extra={"tenant_id": settings.tenant_id, "text_id": text_id, "poll_id": poll_id},
            )
    if snapshot_source == "unavailable":
        with db_session(database_url) as conn:
            cached = list_coverage_participants(conn, tenant_id=settings.tenant_id, chat_id=chat_id)
            if cached:
                snapshot_source = "cached_roster"
                snapshot_synced_at = str(cached[0]["last_synced_at"]) if "last_synced_at" in cached[0] else None
                participants = cached
    with db_session(database_url) as conn:
        snapshot_count = snapshot_poll_recipients(
            conn,
            poll_id=poll_id,
            tenant_id=settings.tenant_id,
            chat_id=chat_id,
            participants=participants,
            source=snapshot_source,
            synced_at=snapshot_synced_at,
        )
    return {
        "recipient_snapshot_source": snapshot_source,
        "recipient_snapshot_synced_at": snapshot_synced_at,
        "assigned_count": snapshot_count,
    }


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
    logger.info(
        "poll_send.start",
        extra={"tenant_id": settings.tenant_id, "text_id": text_id, "scheduled_slot": scheduled_slot},
    )
    with db_session(database_url) as conn:
        text = get_text(conn, text_id)
        if text is None:
            raise ValueError("Text not found.")
        if int(text["tenant_id"]) != settings.tenant_id:
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
    snapshot = await prepare_poll_recipient_snapshot(
        settings=settings,
        database_url=database_url,
        poll_id=poll_id,
        text_id=text_id,
        chat_id=str(text["chat_id"]),
    )
    try:
        message_id = await create_greenapi_client(settings).send_poll(
            chat_id=text["chat_id"],
            question=generated.question,
            options=generated.options,
        )
    except Exception as exc:
        logger.exception(
            "poll_send.failed",
            extra={"tenant_id": settings.tenant_id, "text_id": text_id, "poll_id": poll_id},
        )
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
    logger.info(
        "poll_send.complete",
        extra={
            "tenant_id": settings.tenant_id,
            "text_id": text_id,
            "poll_id": poll_id,
            "used_pool": used_pool,
            "greenapi_message_id": message_id,
            "recipient_snapshot_source": snapshot["recipient_snapshot_source"],
            "assigned_count": snapshot["assigned_count"],
        },
    )
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


def _extract_poll_message_data(payload: dict[str, Any]) -> dict[str, Any] | None:
    top_level_poll = payload.get("pollMessageData")
    if isinstance(top_level_poll, dict):
        return top_level_poll
    candidates: list[Any] = [
        payload.get("messageData"),
        payload.get("editedMessageData"),
        payload.get("quotedMessageData"),
    ]
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        if isinstance(candidate.get("pollMessageData"), dict):
            return candidate["pollMessageData"]
        if candidate.get("typeMessage") == "pollUpdateMessage":
            return candidate
    return None


def extract_greenapi_webhook_metadata(payload: dict[str, Any]) -> dict[str, str | None]:
    type_webhook = payload.get("typeWebhook")
    message_type: str | None = None
    for candidate in (
        payload.get("messageData"),
        payload.get("editedMessageData"),
        payload.get("quotedMessageData"),
        payload,
    ):
        if isinstance(candidate, dict):
            raw_message_type = candidate.get("typeMessage")
            if isinstance(raw_message_type, str) and raw_message_type.strip():
                message_type = raw_message_type.strip()
                break
    parsed = parse_poll_update(payload)
    return {
        "type_webhook": str(type_webhook).strip() if isinstance(type_webhook, str) and type_webhook.strip() else None,
        "message_type": message_type,
        "greenapi_message_id": parsed[0] if parsed is not None else None,
    }


def _extract_poll_votes(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        nested = value.get("votes") or value.get("items") or value.get("results")
        if isinstance(nested, list):
            return [item for item in nested if isinstance(item, dict)]
        rows: list[dict[str, Any]] = []
        for option_name, voters in value.items():
            if isinstance(option_name, str):
                rows.append({"optionName": option_name, "optionVoters": voters})
        return rows
    return []


def parse_poll_update(payload: dict[str, Any]) -> tuple[str, dict[str, list[dict[str, str | None]]]] | None:
    poll_data = _extract_poll_message_data(payload)
    if poll_data is None:
        return None
    stanza_id = poll_data.get("stanzaId") or poll_data.get("idMessage") or poll_data.get("messageId")
    votes = _extract_poll_votes(poll_data.get("votes"))
    if not stanza_id or not votes:
        return None

    option_voters: dict[str, list[dict[str, str | None]]] = {}
    for vote in votes:
        option = str(vote.get("optionName", "")).strip()
        raw_voters = vote.get("optionVoters")
        if raw_voters is None:
            raw_voters = vote.get("voters")
        if raw_voters is None:
            raw_voters = vote.get("participants")
        voters = raw_voters if isinstance(raw_voters, list) else []
        if option:
            option_voters[option] = [record for voter in voters if (record := _parse_voter_record(voter)) is not None]
    if not option_voters:
        return None
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
    settings = runtime_config_from_row(tenant)
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
) -> WebhookDecision:
    metadata = extract_greenapi_webhook_metadata(payload)
    parsed = parse_poll_update(payload)
    if parsed is None:
        logger.info(
            "webhook.ignored",
            extra={"tenant_id": tenant_id, "reason": "not_poll_update", "type": payload.get("typeWebhook")},
        )
        return WebhookDecision(
            handled=False,
            status="ignored",
            reason="not_poll_update",
            type_webhook=metadata["type_webhook"],
            message_type=metadata["message_type"],
            greenapi_message_id=metadata["greenapi_message_id"],
        )
    message_id, option_voters = parsed
    logger.info("webhook.poll_update", extra={"tenant_id": tenant_id, "greenapi_message_id": message_id})
    with db_session(database_url) as conn:
        poll = (
            get_poll_by_message_id_for_tenant(conn, message_id=message_id, tenant_id=tenant_id)
            if tenant_id is not None
            else get_poll_by_message_id(conn, message_id)
        )
    if poll is None:
        logger.info(
            "webhook.ignored",
            extra={"tenant_id": tenant_id, "reason": "poll_not_found", "greenapi_message_id": message_id},
        )
        return WebhookDecision(
            handled=False,
            status="ignored",
            reason="poll_not_found",
            type_webhook=metadata["type_webhook"],
            message_type=metadata["message_type"],
            greenapi_message_id=message_id,
        )
    tenant_key = int(poll["tenant_id"])
    poll_id = int(poll["id"])
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
            logger.info(
                "webhook.ignored",
                extra={
                    "tenant_id": tenant_id,
                    "reason": "poll_not_found_after_enrichment",
                    "greenapi_message_id": message_id,
                },
            )
            return WebhookDecision(
                handled=False,
                status="ignored",
                reason="poll_not_found_after_enrichment",
                type_webhook=metadata["type_webhook"],
                message_type=metadata["message_type"],
                greenapi_message_id=message_id,
            )
        replace_poll_votes(conn, poll=live_poll, option_voters=enriched)
    logger.info(
        "webhook.handled",
        extra={
            "tenant_id": tenant_key,
            "poll_id": poll_id,
            "greenapi_message_id": message_id,
            "option_count": len(enriched),
        },
    )
    return WebhookDecision(
        handled=True,
        status="accepted",
        reason="handled",
        type_webhook=metadata["type_webhook"],
        message_type=metadata["message_type"],
        greenapi_message_id=message_id,
        poll_id=poll_id,
    )


def handle_greenapi_webhook(*, database_url: str, payload: dict[str, Any], tenant_id: int | None = None) -> bool:
    return asyncio.run(handle_greenapi_webhook_async(database_url=database_url, payload=payload, tenant_id=tenant_id)).handled


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
        logger.info(
            "summary.skip",
            extra={
                "tenant_id": settings.tenant_id,
                "text_id": text_id,
                "summary_enabled": settings.summary_enabled,
                "greenapi_ready": settings.greenapi_ready,
            },
        )
        return 0
    logger.info("summary.start", extra={"tenant_id": settings.tenant_id, "text_id": text_id})
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
        logger.info("summary.sent", extra={"tenant_id": settings.tenant_id, "poll_id": int(poll["id"])})
    logger.info("summary.complete", extra={"tenant_id": settings.tenant_id, "text_id": text_id, "sent_count": sent})
    return sent


def texts_due_now(database_url: str, minute_key: str) -> list[tuple[RuntimeConfig, Any]]:
    from app.database import list_text_schedule_rules

    due: list[tuple[RuntimeConfig, Any]] = []
    with db_session(database_url) as conn:
        texts = list_pending_texts(conn)
        for text in texts:
            runtime = runtime_config_from_row(text)
            if not runtime.scheduler_enabled or not runtime.greenapi_ready or not runtime.gemini_ready:
                continue
            rules = list_text_schedule_rules(conn, text_id=int(text["id"]), enabled_only=True)
            if any(
                str(rule.get("time") or "") == minute_key for rule in rules if rule.get("rule_type") != "random_window"
            ):
                due.append((runtime, text))
    return due
