from text2pandas.application.evidence_output import compose_relevant_tables


def test_evidence_tables_are_first_and_candidate_safety_net_is_bounded() -> None:
    result = compose_relevant_tables(
        ("exact-b", "exact-a", "exact-b"),
        ("candidate-a", "exact-a", "candidate-b", "candidate-c", "candidate-d"),
        expected_operands=1,
        max_tables=10,
    )

    assert result == ("exact-b", "exact-a", "candidate-a", "candidate-b")


def test_output_policy_never_drops_exact_evidence_within_hard_limit() -> None:
    result = compose_relevant_tables(
        ("a", "b", "c"),
        ("d", "e"),
        expected_operands=1,
        max_tables=3,
    )

    assert result == ("a", "b", "c")
