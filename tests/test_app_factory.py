from app.main import create_app


def test_create_app_registers_expected_routes():
    app = create_app()
    paths = set(app.openapi()["paths"])

    expected_paths = {
        "/api/v1/health",
        "/api/v1/auth/login",
        "/api/v1/auth/register",
        "/api/v1/auth/me",
        "/api/v1/docs/session",
        "/api/v1/tenants",
        "/api/v1/tenants/{tenant_id}",
        "/api/v1/tenants/{tenant_id}/activate",
        "/api/v1/texts",
        "/api/v1/texts/{text_id}",
        "/api/v1/texts/{text_id}/schedule-rules",
        "/api/v1/texts/{text_id}/schedule-rules/{rule_id}",
        "/api/v1/texts/{text_id}/roster",
        "/api/v1/texts/{text_id}/roster/sync",
        "/api/v1/texts/{text_id}/roster/{voter_wid}",
        "/api/v1/texts/{text_id}/poll-pool",
        "/api/v1/texts/{text_id}/poll-pool/refill",
        "/api/v1/polls",
        "/api/v1/polls/stats",
        "/api/v1/polls/export.csv",
        "/api/v1/polls/{poll_id}",
        "/api/v1/polls/{poll_id}/coverage",
        "/api/v1/polls/{poll_id}/vote-status",
        "/api/v1/polls/{poll_id}/pool-rank",
        "/api/v1/polls/send-now",
        "/api/v1/learners",
        "/api/v1/learners/{voter_wid}",
        "/api/v1/poll-votes",
        "/api/v1/poll-votes/{vote_id}",
        "/api/v1/poll-vote-events",
        "/api/v1/poll-vote-events/{event_id}",
        "/api/v1/questions/preview",
        "/api/v1/summaries/send-now",
        "/webhooks/greenapi/{tenant_id}",
    }

    assert expected_paths.issubset(paths)
