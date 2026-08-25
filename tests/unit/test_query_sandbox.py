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
