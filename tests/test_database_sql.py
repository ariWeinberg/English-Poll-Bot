from app.database import _learner_aggregate_cte


def test_learner_aggregate_cte_qualifies_change_rollup_voter_wid():
    sql = _learner_aggregate_cte("1 = 1")

    assert "SELECT\n                poll_vote_events.voter_wid," in sql
    assert "poll_vote_events.voter_wid\n                    )" in sql
    assert "split_part(poll_vote_events.voter_wid, '@', 1)" in sql
