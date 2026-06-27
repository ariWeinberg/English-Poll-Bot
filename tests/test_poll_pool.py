import asyncio
import os

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.database import (
    count_queued_polls,
    create_poll,
    db_session,
    get_effective_poll_pool_threshold_percent,
    get_poll_pool_refill_threshold_count,
    get_poll,
    init_db,
    list_queued_polls,
)
from app.main import app
from app.question_generator import GeneratedQuestion
from app.services import fill_poll_pool, generate_and_send_poll, load_runtime_config, preview_next_pooled_poll


TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TEST_DATABASE_URL is not set")


def reset_db() -> str:
    assert TEST_DATABASE_URL is not None
    object.__setattr__(settings, "database_url", TEST_DATABASE_URL)
    init_db(TEST_DATABASE_URL)
    with db_session(TEST_DATABASE_URL) as conn:
        conn.execute("TRUNCATE poll_vote_events, poll_votes, polls, texts, tenants RESTART IDENTITY CASCADE")
    init_db(TEST_DATABASE_URL)
    return TEST_DATABASE_URL


def auth_headers(client: TestClient) -> dict[str, str]:
    response = client.post("/api/v1/auth/login", json={"username": "admin", "password": "admin"})
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def build_question(index: int) -> GeneratedQuestion:
    return GeneratedQuestion(
        question=f"Question {index}?",
        options=[f"A{index}", f"B{index}", f"C{index}", f"D{index}"],
        correct_option=f"A{index}",
        explanation=f"Explanation {index}",
    )


def test_fill_poll_pool_creates_ranked_queued_polls(monkeypatch):
    database_url = reset_db()
    runtime = load_runtime_config(database_url, 1)

    async def fake_generate_batch(_settings, _source_text, *, prior_poll_history, count):
        assert prior_poll_history == []
        return [build_question(index) for index in range(1, count + 1)]

    monkeypatch.setattr("app.services.generate_poll_batch", fake_generate_batch)

    created_ids = asyncio.run(fill_poll_pool(settings=runtime, database_url=database_url, text_id=1))

    assert len(created_ids) == 5
    with db_session(database_url) as conn:
        queued = list_queued_polls(conn, text_id=1)
    assert [poll["pool_rank"] for poll in queued] == [1, 2, 3, 4, 5]
    assert all(poll["status"] == "queued" for poll in queued)


def test_send_uses_next_queued_poll_and_refills_below_threshold(monkeypatch):
    database_url = reset_db()
    runtime = load_runtime_config(database_url, 1)
    with db_session(database_url) as conn:
        first_id = create_poll(
            conn,
            tenant_id=1,
            text_id=1,
            question="First queued?",
            options=["A", "B", "C", "D"],
            correct_option="A",
            explanation="",
            chat_id="group@g.us",
            generated_from_text="Body",
            scheduled_slot=None,
            status="queued",
            pool_rank=1,
        )
        second_id = create_poll(
            conn,
            tenant_id=1,
            text_id=1,
            question="Second queued?",
            options=["A", "B", "C", "D"],
            correct_option="A",
            explanation="",
            chat_id="group@g.us",
            generated_from_text="Body",
            scheduled_slot=None,
            status="queued",
            pool_rank=2,
        )

    async def fake_send_poll(self, *, chat_id: str, question: str, options: list[str]):
        assert chat_id == "group@g.us"
        assert question == "First queued?"
        return "green-msg-1"

    refill_calls: list[int] = []

    async def fake_refill(*, settings, database_url: str, text_id: int, count: int = 5):
        refill_calls.append(text_id)
        with db_session(database_url) as conn:
            tail = max(int(item["pool_rank"]) for item in list_queued_polls(conn, text_id=text_id))
            for offset in range(1, count + 1):
                create_poll(
                    conn,
                    tenant_id=1,
                    text_id=text_id,
                    question=f"Refill {offset}?",
                    options=["A", "B", "C", "D"],
                    correct_option="A",
                    explanation="",
                    chat_id="group@g.us",
                    generated_from_text="Body",
                    scheduled_slot=None,
                    status="queued",
                    pool_rank=tail + offset,
                )
        return []

    monkeypatch.setattr("app.greenapi.GreenAPIClient.send_poll", fake_send_poll)
    monkeypatch.setattr("app.services.fill_poll_pool", fake_refill)

    sent_poll_id = asyncio.run(
        generate_and_send_poll(settings=runtime, database_url=database_url, text_id=1, scheduled_slot="manual")
    )

    assert sent_poll_id == first_id
    assert refill_calls == [1]
    with db_session(database_url) as conn:
        first = get_poll(conn, first_id)
        second = get_poll(conn, second_id)
        queued_count = count_queued_polls(conn, text_id=1)
    assert first["status"] == "sent"
    assert first["greenapi_message_id"] == "green-msg-1"
    assert second["status"] == "queued"
    assert queued_count == 6


def test_pool_threshold_inherits_tenant_default_and_allows_text_override():
    database_url = reset_db()
    with db_session(database_url) as conn:
        conn.execute("UPDATE tenants SET poll_pool_threshold_percent = 70 WHERE id = 1")
        assert get_effective_poll_pool_threshold_percent(conn, text_id=1) == 70
        assert get_poll_pool_refill_threshold_count(conn, text_id=1) == 3
        conn.execute("UPDATE texts SET poll_pool_threshold_percent = 40 WHERE id = 1")
        assert get_effective_poll_pool_threshold_percent(conn, text_id=1) == 40
        assert get_poll_pool_refill_threshold_count(conn, text_id=1) == 6


def test_empty_pool_falls_back_to_immediate_generation(monkeypatch):
    database_url = reset_db()
    runtime = load_runtime_config(database_url, 1)

    async def fake_generate_question(_settings, _source_text, *, prior_poll_history):
        assert prior_poll_history == []
        return build_question(99)

    async def fake_send_poll(self, *, chat_id: str, question: str, options: list[str]):
        assert question == "Question 99?"
        return "green-msg-99"

    async def fake_refill_if_needed(*, settings, database_url: str, text_id: int):
        return None

    monkeypatch.setattr("app.services.generate_question", fake_generate_question)
    monkeypatch.setattr("app.greenapi.GreenAPIClient.send_poll", fake_send_poll)
    monkeypatch.setattr("app.services._refill_pool_if_needed", fake_refill_if_needed)

    poll_id = asyncio.run(
        generate_and_send_poll(settings=runtime, database_url=database_url, text_id=1, scheduled_slot="manual")
    )

    with db_session(database_url) as conn:
        poll = get_poll(conn, poll_id)
    assert poll["status"] == "sent"
    assert poll["greenapi_message_id"] == "green-msg-99"


def test_preview_returns_next_queued_poll_without_consuming():
    database_url = reset_db()
    runtime = load_runtime_config(database_url, 1)
    with db_session(database_url) as conn:
        create_poll(
            conn,
            tenant_id=1,
            text_id=1,
            question="Preview me?",
            options=["A", "B", "C", "D"],
            correct_option="A",
            explanation="Explanation",
            chat_id="group@g.us",
            generated_from_text="Body",
            scheduled_slot=None,
            status="queued",
            pool_rank=1,
        )

    preview = asyncio.run(preview_next_pooled_poll(settings=runtime, database_url=database_url, text_id=1))

    with db_session(database_url) as conn:
        queued_count = count_queued_polls(conn, text_id=1)
    assert preview.question == "Preview me?"
    assert queued_count == 1


def test_api_supports_reordering_and_deleting_only_queued_pool_entries():
    database_url = reset_db()
    with db_session(database_url) as conn:
        first_id = create_poll(
            conn,
            tenant_id=1,
            text_id=1,
            question="Queued one?",
            options=["A", "B", "C", "D"],
            correct_option="A",
            explanation="",
            chat_id="group@g.us",
            generated_from_text="Body",
            scheduled_slot=None,
            status="queued",
            pool_rank=1,
        )
        second_id = create_poll(
            conn,
            tenant_id=1,
            text_id=1,
            question="Queued two?",
            options=["A", "B", "C", "D"],
            correct_option="A",
            explanation="",
            chat_id="group@g.us",
            generated_from_text="Body",
            scheduled_slot=None,
            status="queued",
            pool_rank=2,
        )
        sent_id = create_poll(
            conn,
            tenant_id=1,
            text_id=1,
            question="Already sent?",
            options=["A", "B", "C", "D"],
            correct_option="A",
            explanation="",
            chat_id="group@g.us",
            generated_from_text="Body",
            scheduled_slot="manual",
            status="sent",
        )

    with TestClient(app) as client:
        headers = auth_headers(client)
        moved = client.patch(f"/api/v1/polls/{second_id}/pool-rank", headers=headers, json={"pool_rank": 1})
        assert moved.status_code == 200
        deleted = client.delete(f"/api/v1/polls/{first_id}", headers=headers)
        assert deleted.status_code == 204
        pool = client.get("/api/v1/texts/1/poll-pool", headers=headers)
        assert pool.status_code == 200

    with db_session(database_url) as conn:
        queued = list_queued_polls(conn, text_id=1)
        sent = get_poll(conn, sent_id)
    assert [poll["id"] for poll in queued] == [second_id]
    assert queued[0]["pool_rank"] == 1
    assert sent is not None
