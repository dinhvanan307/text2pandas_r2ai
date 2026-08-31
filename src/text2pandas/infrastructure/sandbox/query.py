"""Restricted evaluator for machine-generated pandas expressions."""

from __future__ import annotations

import ast
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass

_FUNCTIONS: dict[str, Callable[..., object]] = {
    "float": float,
    "abs": abs,
    "min": min,
    "max": max,
    "sum": sum,
    "len": len,
    "round": round,
    "pow": pow,
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
    ast.BoolOp,
    ast.And,
    ast.Or,
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
    effective_dataframe_variables: frozenset[str]


_NOT_CONSTANT = object()
_STORED_OUTPUT_COLUMNS = {
    "answer",
    "expected_answer",
    "predicted_answer",
    "prediction",
    "result",
}


def _merge_dependencies(*items: tuple[frozenset[str], object]) -> frozenset[str]:
    merged: set[str] = set()
    for variables, _constant in items:
        merged.update(variables)
    return frozenset(merged)


def _constant_binary(operator: ast.operator, left: object, right: object) -> object:
    try:
        if isinstance(operator, ast.Add):
            return left + right  # type: ignore[operator]
        if isinstance(operator, ast.Sub):
            return left - right  # type: ignore[operator]
        if isinstance(operator, ast.Mult):
            return left * right  # type: ignore[operator]
        if isinstance(operator, ast.Div):
            return left / right  # type: ignore[operator]
        if isinstance(operator, ast.BitAnd):
            return left & right  # type: ignore[operator]
    except (ArithmeticError, TypeError, ValueError):
        return _NOT_CONSTANT
    return _NOT_CONSTANT


def _constant_compare(operator: ast.cmpop, left: object, right: object) -> object:
    try:
        if isinstance(operator, ast.Eq):
            return left == right
        if isinstance(operator, ast.Gt):
            return left > right  # type: ignore[operator]
        if isinstance(operator, ast.GtE):
            return left >= right  # type: ignore[operator]
        if isinstance(operator, ast.Lt):
            return left < right  # type: ignore[operator]
        if isinstance(operator, ast.LtE):
            return left <= right  # type: ignore[operator]
    except (TypeError, ValueError):
        return _NOT_CONSTANT
    return _NOT_CONSTANT


def _data_dependencies(
    node: ast.AST,
    evidence_variables: set[str],
) -> tuple[frozenset[str], object]:
    """Return dataframe variables which can affect the expression value.

    This is deliberately stricter than finding ``ast.Name`` nodes.  A variable
    mentioned only below ``0 * (...)`` does not influence the result and cannot
    make a stored constant into a grounded Pandas computation.
    """

    if isinstance(node, ast.Expression):
        return _data_dependencies(node.body, evidence_variables)
    if isinstance(node, ast.Constant):
        return frozenset(), node.value
    if isinstance(node, ast.Name):
        variables = frozenset({node.id}) if node.id in evidence_variables else frozenset()
        return variables, _NOT_CONSTANT
    if isinstance(node, ast.Attribute):
        variables, _constant = _data_dependencies(node.value, evidence_variables)
        return variables, _NOT_CONSTANT
    if isinstance(node, ast.Subscript):
        base = _data_dependencies(node.value, evidence_variables)
        index = _data_dependencies(node.slice, evidence_variables)
        return _merge_dependencies(base, index), _NOT_CONSTANT
    if isinstance(node, ast.UnaryOp):
        variables, constant = _data_dependencies(node.operand, evidence_variables)
        if constant is not _NOT_CONSTANT:
            try:
                if isinstance(node.op, ast.UAdd):
                    return frozenset(), +constant  # type: ignore[operator]
                if isinstance(node.op, ast.USub):
                    return frozenset(), -constant  # type: ignore[operator]
            except (TypeError, ValueError):
                pass
        return variables, _NOT_CONSTANT
    if isinstance(node, ast.BinOp):
        left = _data_dependencies(node.left, evidence_variables)
        right = _data_dependencies(node.right, evidence_variables)
        if isinstance(node.op, ast.Mult) and (
            (left[1] is not _NOT_CONSTANT and left[1] == 0)
            or (right[1] is not _NOT_CONSTANT and right[1] == 0)
        ):
            return frozenset(), 0
        if isinstance(node.op, ast.Div) and left[1] is not _NOT_CONSTANT and left[1] == 0:
            return frozenset(), 0
        if ast.dump(node.left) == ast.dump(node.right):
            if isinstance(node.op, ast.Sub):
                return frozenset(), 0
            if isinstance(node.op, ast.Div):
                return frozenset(), 1
        if left[1] is not _NOT_CONSTANT and right[1] is not _NOT_CONSTANT:
            value = _constant_binary(node.op, left[1], right[1])
            if value is not _NOT_CONSTANT:
                return frozenset(), value
        return _merge_dependencies(left, right), _NOT_CONSTANT
    if isinstance(node, ast.Call):
        arguments = [_data_dependencies(argument, evidence_variables) for argument in node.args]
        variables = _merge_dependencies(*arguments)
        if (
            isinstance(node.func, ast.Name)
            and node.func.id == "pow"
            and len(arguments) == 2
            and arguments[1][1] is not _NOT_CONSTANT
            and arguments[1][1] == 0
        ):
            return frozenset(), 1
        if (
            isinstance(node.func, ast.Name)
            and not variables
            and all(item[1] is not _NOT_CONSTANT for item in arguments)
        ):
            try:
                function = _FUNCTIONS[node.func.id]
                return frozenset(), function(*(item[1] for item in arguments))
            except (ArithmeticError, KeyError, TypeError, ValueError):
                pass
        return variables, _NOT_CONSTANT
    if isinstance(node, ast.Compare):
        if (
            len(node.ops) == 1
            and len(node.comparators) == 1
            and ast.dump(node.left) == ast.dump(node.comparators[0])
        ):
            if isinstance(node.ops[0], (ast.Eq, ast.GtE, ast.LtE)):
                return frozenset(), True
            if isinstance(node.ops[0], (ast.Gt, ast.Lt)):
                return frozenset(), False
        items = [
            _data_dependencies(node.left, evidence_variables),
            *(
                _data_dependencies(comparator, evidence_variables)
                for comparator in node.comparators
            ),
        ]
        variables = _merge_dependencies(*items)
        if not variables and all(item[1] is not _NOT_CONSTANT for item in items):
            comparisons = [
                _constant_compare(operator, items[index][1], items[index + 1][1])
                for index, operator in enumerate(node.ops)
            ]
            if all(value is not _NOT_CONSTANT for value in comparisons):
                return frozenset(), all(bool(value) for value in comparisons)
        return variables, _NOT_CONSTANT
    if isinstance(node, ast.IfExp):
        test = _data_dependencies(node.test, evidence_variables)
        body = _data_dependencies(node.body, evidence_variables)
        alternative = _data_dependencies(node.orelse, evidence_variables)
        if (
            body[1] is not _NOT_CONSTANT
            and alternative[1] is not _NOT_CONSTANT
            and body[1] == alternative[1]
        ):
            return frozenset(), body[1]
        if test[1] is not _NOT_CONSTANT:
            return body if bool(test[1]) else alternative
        return _merge_dependencies(test, body, alternative), _NOT_CONSTANT
    if isinstance(node, ast.BoolOp):
        items = [_data_dependencies(value, evidence_variables) for value in node.values]
        first = items[0]
        if first[1] is not _NOT_CONSTANT:
            if isinstance(node.op, ast.And):
                return first if not bool(first[1]) else items[-1]
            if isinstance(node.op, ast.Or):
                return first if bool(first[1]) else items[-1]
        return _merge_dependencies(*items), _NOT_CONSTANT
    children = [_data_dependencies(child, evidence_variables) for child in ast.iter_child_nodes(node)]
    return _merge_dependencies(*children), _NOT_CONSTANT


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
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            discarded: ast.expr | None = None
            if isinstance(node.left, ast.Constant) and node.left.value == 0:
                discarded = node.right
            elif isinstance(node.right, ast.Constant) and node.right.value == 0:
                discarded = node.left
            if discarded is not None and _data_dependencies(
                discarded, evidence_variables
            )[0]:
                raise QuerySafetyError(
                    "query discards packaged CSV data with a zero multiplier"
                )
        elif isinstance(node, ast.Attribute):
            if node.attr != "values" or node.attr.startswith("_"):
                raise QuerySafetyError(f"disallowed attribute: {node.attr}")
        elif (
            isinstance(node, ast.Subscript)
            and isinstance(node.slice, ast.Constant)
            and isinstance(node.slice.value, str)
            and node.slice.value.casefold() in _STORED_OUTPUT_COLUMNS
        ):
            raise QuerySafetyError(
                f"stored output column is not allowed: {node.slice.value!r}"
            )
        elif isinstance(node, ast.Constant) and not isinstance(
            node.value, (str, int, float)
        ):
            raise QuerySafetyError(
                f"disallowed constant type: {type(node.value).__name__}"
            )

    effective, _constant = _data_dependencies(tree, evidence_variables)
    if not effective:
        raise QuerySafetyError("query result does not depend on packaged CSV data")
    if require_all_evidence and used != evidence_variables:
        missing = sorted(evidence_variables - used)
        extra = sorted(used - evidence_variables)
        raise QuerySafetyError(f"query/evidence variable mismatch: missing={missing}, extra={extra}")
    if require_all_evidence and effective != evidence_variables:
        missing = sorted(evidence_variables - effective)
        extra = sorted(effective - evidence_variables)
        raise QuerySafetyError(
            "query/evidence effective dependency mismatch: "
            f"missing={missing}, extra={extra}"
        )
    return QueryContract(
        tree=tree,
        dataframe_variables=frozenset(used),
        effective_dataframe_variables=effective,
    )


def execute_query(query: str, frames: Mapping[str, object]) -> float:
    """Validate, execute, and return a finite numeric result."""

    contract = validate_query(query, set(frames))
    namespace: dict[str, object] = dict(_FUNCTIONS)
    namespace.update(frames)
    value = eval(
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
