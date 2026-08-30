from tools.evaluation.build_recovery_protected_sets import partition_sets


def _row(executable: bool) -> dict[str, object]:
    return {
        "answer": 1.0 if executable else None,
        "pandas_query": "float(df1.iloc[0, 0])" if executable else "",
        "evidence": [{"variable": "df1", "csv_path": "data/a.csv"}]
        if executable
        else [],
    }


def test_partition_sets_seals_disjoint_answer_and_mutation_qids() -> None:
    baseline = {1: _row(True), 2: _row(True), 3: _row(False), 4: _row(False)}

    result = partition_sets(
        baseline,
        {3, 4},
        {2},
        expected_records=4,
        expected_executable=2,
        expected_unresolved=2,
    )

    assert result == {
        "p_answer": (1, 2),
        "p_retrieval": (1, 2, 3, 4),
        "p_inherited_recovery": (2,),
        "mutation_pool": (3, 4),
    }


def test_partition_sets_rejects_inventory_drift() -> None:
    baseline = {1: _row(True), 2: _row(False), 3: _row(False)}

    try:
        partition_sets(
            baseline,
            {2},
            set(),
            expected_records=3,
            expected_executable=1,
            expected_unresolved=2,
        )
    except ValueError as error:
        assert "inventory differs" in str(error)
    else:
        raise AssertionError("inventory drift must fail closed")


def test_partition_sets_rejects_inherited_qid_outside_executable_set() -> None:
    baseline = {1: _row(True), 2: _row(False)}

    try:
        partition_sets(
            baseline,
            {2},
            {2},
            expected_records=2,
            expected_executable=1,
            expected_unresolved=1,
        )
    except ValueError as error:
        assert "not executable" in str(error)
    else:
        raise AssertionError("invalid inherited recovery QID must fail closed")


def test_partition_sets_seals_narrow_mutation_scope_and_out_of_scope_abstentions() -> None:
    baseline = {
        1: _row(True),
        2: _row(False),
        3: _row(False),
        4: _row(False),
    }

    result = partition_sets(
        baseline,
        {2, 3, 4},
        set(),
        expected_records=4,
        expected_executable=1,
        expected_unresolved=3,
        mutation_scope_qids={2, 4},
    )

    assert result["w5_mutation_scope"] == (2, 4)
    assert result["p_out_of_scope_unresolved"] == (3,)


def test_partition_sets_rejects_scope_outside_abstentions() -> None:
    baseline = {1: _row(True), 2: _row(False)}

    try:
        partition_sets(
            baseline,
            {2},
            set(),
            expected_records=2,
            expected_executable=1,
            expected_unresolved=1,
            mutation_scope_qids={1},
        )
    except ValueError as error:
        assert "outside baseline abstentions" in str(error)
    else:
        raise AssertionError("scope outside abstentions must fail closed")
