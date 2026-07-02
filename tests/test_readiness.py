from datetime import datetime, timezone

from app.api.routes.actions import _build_readiness_payload, _parse_iso_datetime


def test_parse_iso_datetime_handles_timezone_and_naive_values():
    aware = _parse_iso_datetime("2026-07-02T12:00:00+03:00")
    naive = _parse_iso_datetime("2026-07-02T09:00:00")

    assert aware == datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)
    assert naive == datetime(2026, 7, 2, 9, 0, tzinfo=timezone.utc)


def test_readiness_payload_marks_scheduler_ready_when_heartbeat_is_recent():
    payload, status_code = _build_readiness_payload(
        database_ok=True,
        database_error=None,
        scheduler_status={
            "last_tick_at": "2026-07-02T09:00:00+00:00",
            "last_success_at": "2026-07-02T09:00:00+00:00",
            "last_error": None,
        },
        now_utc=datetime(2026, 7, 2, 9, 2, tzinfo=timezone.utc),
    )

    assert status_code == 200
    assert payload.ok is True
    assert payload.database.ok is True
    assert payload.scheduler.ok is True
    assert payload.scheduler.detail == "Scheduler heartbeat is recent"
    assert payload.warnings == []


def test_readiness_payload_reports_missing_or_stale_dependency_state():
    payload, status_code = _build_readiness_payload(
        database_ok=True,
        database_error=None,
        scheduler_status={
            "last_tick_at": "2026-07-02T08:00:00+00:00",
            "last_success_at": "2026-07-02T08:00:00+00:00",
            "last_error": "timeout",
        },
        now_utc=datetime(2026, 7, 2, 9, 2, tzinfo=timezone.utc),
    )

    assert status_code == 503
    assert payload.ok is False
    assert payload.scheduler.ok is False
    assert payload.scheduler.last_error == "timeout"
    assert "recent error" in payload.scheduler.detail
    assert "timeout" not in payload.database.detail
    assert payload.warnings
