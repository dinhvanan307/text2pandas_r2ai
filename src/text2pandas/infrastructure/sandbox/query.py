"""Restricted evaluator for machine-generated pandas expressions."""

from __future__ import annotations

import ast
import math
from dataclasses import dataclass
from typing import Mapping


_FUNCTIONS = {
    "float": float,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "round": round,
}
_ALLOWED_NODES = (
    ast.Expression,
    ast.Call,
    ast.Name,
    ast.Load,
    ast.Subscript,
    ast.Compare,
    ast.Eq,
    ast.Gt,
    ast.GtE,
    ast.Lt,
    ast.LtE,
    ast.IfExp,
    ast.BinOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.BitAnd,
    ast.UnaryOp,
    ast.USub,
    ast.UAdd,
    ast.Attribute,
    ast.Constant,
)


class QuerySafetyError(ValueError):
    """The query is outside the competition expression grammar."""


@dataclass(frozen=True, slots=True)
class QueryContract:
    tree: ast.Expression
    dataframe_variables: frozenset[str]


def validate_query(
    query: str,
    evidence_variables: set[str],
    *,
    require_all_evidence: bool = True,
) -> QueryContract:
    """Parse and verify a small expression-only pandas grammar."""

    if not query or len(query) > 10_000:
        raise QuerySafetyError("query must be non-empty and <= 10000 characters")
    try:
        tree = ast.parse(query, mode="eval")
    except SyntaxError as error:
        raise QuerySafetyError(f"query syntax error: {error.msg}") from error

    used: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise QuerySafetyError(f"disallowed AST node: {type(node).__name__}")
        if isinstance(node, ast.Name):
            if node.id in evidence_variables:
                used.add(node.id)
            elif node.id not in _FUNCTIONS:
                raise QuerySafetyError(f"unknown name: {node.id}")
        elif isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
                raise QuerySafetyError("only allowlisted numeric function calls are allowed")
            if node.keywords:
                raise QuerySafetyError("keyword arguments are not allowed")
        elif isinstance(node, ast.Attribute):
            if node.attr != "values" or node.attr.startswith("_"):
                raise QuerySafetyError(f"disallowed attribute: {node.attr}")
        elif isinstance(node, ast.Constant):
            if not isinstance(node.value, (str, int, float)):
                raise QuerySafetyError(
                    f"disallowed constant type: {type(node.value).__name__}"
                )

    if require_all_evidence and used != evidence_variables:
        missing = sorted(evidence_variables - used)
        extra = sorted(used - evidence_variables)
        raise QuerySafetyError(f"query/evidence variable mismatch: missing={missing}, extra={extra}")
    return QueryContract(tree=tree, dataframe_variables=frozenset(used))


def execute_query(query: str, frames: Mapping[str, object]) -> float:
    """Validate, execute, and return a finite numeric result."""

    contract = validate_query(query, set(frames))
    namespace = dict(_FUNCTIONS)
    namespace.update(frames)
    value = eval(  # noqa: S307 - AST and namespace are restricted above
        compile(contract.tree, "<pandas_query>", "eval"),
        {"__builtins__": {}},
        namespace,
    )
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise QuerySafetyError("query result is not numeric") from error
    if not math.isfinite(result):
        raise QuerySafetyError("query result is not finite")
    return result
