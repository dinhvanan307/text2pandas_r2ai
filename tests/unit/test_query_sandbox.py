from __future__ import annotations

import pandas as pd
import pytest

from text2pandas.infrastructure.sandbox.query import (
    QuerySafetyError,
    execute_query,
    validate_query,
)


def test_generated_pandas_expression_executes() -> None:
    frame = pd.DataFrame([{"row_path": "Doanh thu", "col_label": "2023", "value": 25.0}])
    query = (
        "float(df1[(df1['row_path'] == 'Doanh thu') & "
        "(df1['col_label'] == '2023')]['value'].values[0]) / 5"
    )
    assert execute_query(query, {"df1": frame}) == 5.0


@pytest.mark.parametrize(
    "query",
    [
        "__import__('os').system('id')",
        "df1.to_csv('/tmp/leak')",
        "open('/etc/passwd').read()",
        "(lambda: 1)()",
        "df1.__class__",
    ],
)
def test_unsafe_queries_are_rejected(query: str) -> None:
    with pytest.raises(QuerySafetyError):
        validate_query(query, {"df1"})


def test_query_must_use_every_and_only_evidence_variable() -> None:
    with pytest.raises(QuerySafetyError, match="variable mismatch"):
        validate_query("float(df1['value'].values[0])", {"df1", "df2"})


def test_internal_execution_can_select_a_safe_subset_of_candidate_frames() -> None:
    contract = validate_query(
        "float(df1['value'].values[0])",
        {"df1", "df2"},
        require_all_evidence=False,
    )

    assert contract.dataframe_variables == frozenset({"df1"})
    assert contract.effective_dataframe_variables == frozenset({"df1"})


@pytest.mark.parametrize(
    "query",
    [
        "2.06",
        "1.03 * 2",
        "float(2021 + 0 * float(df1['value'].values[0]))",
        "float(df1['value'].values[0] - df1['value'].values[0] + 2021)",
        "float(pow(float(df1['value'].values[0]), 0) + 2020)",
        "float(2021 if df1['value'].values[0] == df1['value'].values[0] else 2022)",
        "float(0 and df1['value'].values[0])",
        "float(1 or df1['value'].values[0])",
    ],
)
def test_query_result_must_effectively_depend_on_csv_data(query: str) -> None:
    with pytest.raises(QuerySafetyError, match="does not depend|zero multiplier"):
        validate_query(query, {"df1"})


@pytest.mark.parametrize("column", ["answer", "result", "expected_answer", "prediction"])
def test_query_cannot_read_a_stored_output_column(column: str) -> None:
    with pytest.raises(QuerySafetyError, match="stored output column"):
        validate_query(f"float(df1['{column}'].values[0])", {"df1"})


def test_data_driven_period_selection_is_allowed_and_changes_with_csv() -> None:
    query = (
        "float(2021 if float(df1[df1['period'] == '2021']['value'].values[0]) == "
        "max(float(df1[df1['period'] == '2021']['value'].values[0]), "
        "float(df1[df1['period'] == '2022']['value'].values[0])) else 2022)"
    )
    frame = pd.DataFrame(
        [
            {"period": "2021", "value": 20.0},
            {"period": "2022", "value": 10.0},
        ]
    )

    assert execute_query(query, {"df1": frame}) == 2021.0
    frame.loc[frame["period"] == "2022", "value"] = 30.0
    assert execute_query(query, {"df1": frame}) == 2022.0


def test_partially_data_driven_query_cannot_discard_other_csv_data() -> None:
    query = (
        "float(df1['value'].values[0] + "
        "0 * df1['value'].values[1])"
    )

    with pytest.raises(QuerySafetyError, match="zero multiplier"):
        validate_query(query, {"df1"})
