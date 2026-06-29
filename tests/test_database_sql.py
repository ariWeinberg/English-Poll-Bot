from app.database import _learner_aggregate_cte
from app.db_runtime import normalize_database_url


def test_learner_aggregate_cte_qualifies_change_rollup_voter_wid():
    sql = _learner_aggregate_cte("1 = 1")

    assert "SELECT\n                poll_vote_events.voter_wid," in sql
    assert "poll_vote_events.voter_wid\n                    )" in sql
    assert "split_part(poll_vote_events.voter_wid, '@', 1)" in sql


def test_normalize_database_url_uses_psycopg_driver():
    assert normalize_database_url("postgresql://postgres:postgres@db:5432/english_bot") == (
        "postgresql+psycopg://postgres:postgres@db:5432/english_bot"
    )
    assert normalize_database_url("postgres://postgres:postgres@db:5432/english_bot") == (
        "postgresql+psycopg://postgres:postgres@db:5432/english_bot"
    )
