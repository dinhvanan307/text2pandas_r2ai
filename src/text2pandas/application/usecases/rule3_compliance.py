"""Repair and audit submission-rule-3 compliance without changing answers.

The competition requires every emitted result to be computed from packaged CSV
data and every CSV row to be traceable to the supplied BTC corpus.  This module
turns the previously emitted ``year + 0 * data`` arg-period expressions into
runtime selections and seals UID-backed CSV rows against the active A6 database.
"""

from __future__ import annotations

import ast
import csv
import io
import json
import math
import re
import sqlite3
import zipfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast

import pandas as pd

from text2pandas.application.usecases.safe_recovery import _verify_bound_artifact
from text2pandas.application.usecases.submission import (
    SubmissionBuildError,
    write_deterministic_submission_zip,
)
from text2pandas.infrastructure.sandbox.query import execute_query, validate_query


@dataclass(frozen=True, slots=True)
class Rule3ComplianceBuild:
    zip_path: Path
    repaired_qids: tuple[int, ...]
    executable_records: int
    unresolved_records: int
    csv_members: int
    csv_rows_verified: int
    a6_uid_rows_verified: int
    raw_rows_verified: int
    source_locators_verified: int
    retrieval_rebound_qids: tuple[int, ...]
    answers_preserved: int
    evidence_preserved: int
    csv_payloads_preserved: int


def rewrite_legacy_arg_period_query(
    query: str,
    years: Sequence[int],
    *,
    direction: str,
) -> str:
    """Rewrite one recognized ``year + 0 * candidate`` expression.

    Candidate expressions are preserved byte-for-semantics through ``ast.unparse``.
    The order in ``years`` is the order of the old zero-multiplied candidates.
    A max tie selects the earliest year, matching the grounded synthesis rule.
    """

    if direction not in {"max", "min"}:
        raise SubmissionBuildError(f"unsupported arg-period direction: {direction!r}")
    try:
        tree = ast.parse(query, mode="eval")
    except SyntaxError as error:
        raise SubmissionBuildError(f"legacy query has invalid syntax: {error.msg}") from error
    body = tree.body
    if not (
        isinstance(body, ast.Call)
        and isinstance(body.func, ast.Name)
        and body.func.id == "float"
        and len(body.args) == 1
        and not body.keywords
    ):
        raise SubmissionBuildError("legacy arg-period query must be one float(...) call")

    terms = _flatten_add(body.args[0])
    constants: list[int] = []
    candidates: list[ast.expr] = []
    for term in terms:
        if isinstance(term, ast.Constant) and isinstance(term.value, int):
            constants.append(term.value)
            continue
        candidate = _zero_multiplier_operand(term)
        if candidate is None:
            raise SubmissionBuildError(
                f"unrecognized legacy arg-period term: {ast.unparse(term)!r}"
            )
        candidates.append(candidate)
    if len(constants) != 1:
        raise SubmissionBuildError("legacy arg-period query must contain exactly one year")
    if list(years) != sorted(years) or len(set(years)) != len(years):
        raise SubmissionBuildError("arg-period years must be unique and ascending")
    if len(candidates) != len(years):
        raise SubmissionBuildError(
            f"arg-period candidate/year mismatch: {len(candidates)} != {len(years)}"
        )
    if constants[0] not in years:
        raise SubmissionBuildError(
            f"stored year {constants[0]} is not in reviewed years {list(years)}"
        )

    expressions = [ast.unparse(candidate) for candidate in candidates]
    winner = f"{direction}({', '.join(expressions)})"
    ordered = list(zip(years, expressions, strict=True))
    if direction == "min":
        ordered.reverse()
    result = str(ordered[-1][0])
    for year, expression in reversed(ordered[:-1]):
        result = f"({year} if {expression} == {winner} else {result})"
    return f"float({result})"


def simplify_zero_multiplier_query(query: str) -> str:
    """Remove discarded CSV expressions and fold the resulting constants."""

    try:
        tree = ast.parse(query, mode="eval")
    except SyntaxError as error:
        raise SubmissionBuildError(f"legacy query has invalid syntax: {error.msg}") from error
    original = ast.unparse(tree)
    simplified = _ZeroMultiplierSimplifier().visit(tree)
    assert isinstance(simplified, ast.Expression)
    ast.fix_missing_locations(simplified)
    rendered = ast.unparse(simplified)
    if rendered == original:
        raise SubmissionBuildError("query contains no recognized zero-multiplier term")
    return rendered


def build_rule3_compliance_candidate(
    *,
    baseline_zip: Path,
    a6_database: Path,
    corpus_root: Path,
    repair_ledger: Path,
    output_zip: Path,
) -> Rule3ComplianceBuild:
    """Build an immutable compliance candidate from a SHA-bound baseline."""

    if output_zip.exists():
        raise FileExistsError(f"immutable candidate already exists: {output_zip}")
    ledger = _load_object(repair_ledger)
    _verify_bound_artifact(
        baseline_zip,
        cast(Mapping[str, object], ledger.get("baseline")),
        label="baseline ZIP",
        path_key="zip_path",
        sha_key="zip_sha256",
    )
    _verify_bound_artifact(
        a6_database,
        cast(Mapping[str, object], ledger.get("a6_database")),
        label="A6 database",
        path_key="database_path",
        sha_key="database_sha256",
    )
    repairs = _index_repairs(ledger.get("repairs"))
    simplifications = _index_qids(ledger.get("simplifications"), label="simplifications")
    overlap = sorted(set(repairs) & simplifications)
    if overlap:
        raise SubmissionBuildError(f"repair modes overlap for QIDs: {overlap}")

    with zipfile.ZipFile(baseline_zip) as archive:
        json_names = [name for name in archive.namelist() if name.endswith(".json")]
        if len(json_names) != 1:
            raise SubmissionBuildError("baseline ZIP must contain exactly one JSON file")
        json_name = json_names[0]
        records = json.loads(archive.read(json_name).decode("utf-8"))
        if not isinstance(records, list) or not all(isinstance(row, dict) for row in records):
            raise SubmissionBuildError("baseline submission JSON must be a list of objects")
        baseline_records = [dict(row) for row in records]
        csv_payloads = {
            name: archive.read(name)
            for name in archive.namelist()
            if name.lower().endswith(".csv")
        }

    by_qid = _index_records(baseline_records)
    reviewed_qids = set(repairs) | simplifications
    missing = sorted(reviewed_qids - set(by_qid))
    if missing:
        raise SubmissionBuildError(f"repair QIDs are absent from baseline: {missing}")
    for qid, repair in repairs.items():
        row = by_qid[qid]
        query = row.get("pandas_query")
        if not isinstance(query, str) or not query:
            raise SubmissionBuildError(f"QID {qid} has no baseline query to repair")
        row["pandas_query"] = rewrite_legacy_arg_period_query(
            query,
            cast(Sequence[int], repair["years"]),
            direction=cast(str, repair["direction"]),
        )
    for qid in sorted(simplifications):
        row = by_qid[qid]
        query = row.get("pandas_query")
        if not isinstance(query, str) or not query:
            raise SubmissionBuildError(f"QID {qid} has no baseline query to simplify")
        row["pandas_query"] = simplify_zero_multiplier_query(query)

    connection = sqlite3.connect(f"file:{a6_database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    csv_rows_verified = 0
    a6_rows_verified = 0
    raw_rows_verified = 0
    source_locators: set[str] = set()
    source_tables: dict[str, str] = {}
    rebound: list[int] = []
    executable = 0
    try:
        for row in baseline_records:
            qid = cast(int, row["id"])
            evidence = row.get("evidence")
            query = row.get("pandas_query")
            if not evidence:
                continue
            if not isinstance(evidence, list) or not isinstance(query, str) or not query:
                raise SubmissionBuildError(f"QID {qid} has malformed executable fields")
            frames: dict[str, pd.DataFrame] = {}
            uid_locators: list[str] = []
            evidence_kinds: set[str] = set()
            for item in evidence:
                if not isinstance(item, dict):
                    raise SubmissionBuildError(f"QID {qid} has malformed evidence")
                variable = item.get("variable")
                csv_path = item.get("csv_path")
                if not isinstance(variable, str) or not isinstance(csv_path, str):
                    raise SubmissionBuildError(f"QID {qid} has malformed evidence fields")
                payload = csv_payloads.get(csv_path)
                if payload is None:
                    raise SubmissionBuildError(f"QID {qid} references missing CSV {csv_path!r}")
                frames[variable] = pd.read_csv(io.BytesIO(payload))
                rows = list(csv.DictReader(io.StringIO(payload.decode("utf-8-sig"))))
                if not rows:
                    raise SubmissionBuildError(f"QID {qid} CSV is empty: {csv_path}")
                csv_rows_verified += len(rows)
                fields = set(rows[0])
                if "observation_uid" in fields:
                    evidence_kinds.add("a6")
                    for csv_row in rows:
                        locator, source_raw = _verify_uid_row(connection, qid, csv_row)
                        uid_locators.append(locator)
                        table = source_tables.get(locator)
                        if table is None:
                            table = _read_source_table(corpus_root, locator)
                            source_tables[locator] = table
                        if not source_raw or source_raw not in table:
                            raise SubmissionBuildError(
                                f"QID {qid} A6 source token is absent from BTC table "
                                f"{locator!r}: {source_raw!r}"
                            )
                        source_locators.add(locator)
                        a6_rows_verified += 1
                elif "value_raw" in fields:
                    evidence_kinds.add("raw")
                    verified = _verify_raw_rows(qid, csv_row_values=rows, record=row, corpus_root=corpus_root)
                    raw_rows_verified += verified
                    source_locators.update(cast(list[str], row["relevant_tables"]))
                else:
                    raise SubmissionBuildError(
                        f"QID {qid} CSV lacks observation_uid or value_raw: {csv_path}"
                    )
            if len(evidence_kinds) != 1:
                raise SubmissionBuildError(f"QID {qid} mixes incompatible CSV lineage formats")
            if evidence_kinds == {"a6"}:
                tables = list(dict.fromkeys(uid_locators))
                docs = list(dict.fromkeys(locator.rsplit("|", 1)[0] for locator in tables))
                if row.get("relevant_tables") != tables or row.get("relevant_docs") != docs:
                    rebound.append(qid)
                row["relevant_tables"] = tables
                row["relevant_docs"] = docs
            validate_query(query, set(frames))
            replayed = execute_query(query, frames)
            expected = row.get("answer")
            if not isinstance(expected, (int, float)) or isinstance(expected, bool):
                raise SubmissionBuildError(f"QID {qid} has a non-numeric answer")
            if not math.isclose(replayed, float(expected), rel_tol=1e-12, abs_tol=1e-12):
                raise SubmissionBuildError(
                    f"QID {qid} answer changed under compliant replay: {expected!r} != {replayed!r}"
                )
            executable += 1
    finally:
        connection.close()

    repaired_qids = tuple(sorted(reviewed_qids))
    _verify_preservation(
        baseline_records=cast(list[dict[str, object]], records),
        candidate_records=baseline_records,
        repaired_qids=set(repaired_qids),
    )
    output_zip.parent.mkdir(parents=True, exist_ok=True)
    write_deterministic_submission_zip(
        output_zip,
        json_name=json_name,
        json_bytes=json.dumps(baseline_records, ensure_ascii=False, indent=1).encode("utf-8"),
        csv_payloads=csv_payloads,
    )
    return Rule3ComplianceBuild(
        zip_path=output_zip,
        repaired_qids=repaired_qids,
        executable_records=executable,
        unresolved_records=len(baseline_records) - executable,
        csv_members=len(csv_payloads),
        csv_rows_verified=csv_rows_verified,
        a6_uid_rows_verified=a6_rows_verified,
        raw_rows_verified=raw_rows_verified,
        source_locators_verified=len(source_locators),
        retrieval_rebound_qids=tuple(rebound),
        answers_preserved=len(baseline_records),
        evidence_preserved=len(baseline_records),
        csv_payloads_preserved=len(csv_payloads),
    )


def _flatten_add(node: ast.expr) -> list[ast.expr]:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return [*_flatten_add(node.left), *_flatten_add(node.right)]
    return [node]


class _ZeroMultiplierSimplifier(ast.NodeTransformer):
    def visit_BinOp(self, node: ast.BinOp) -> ast.expr:  # noqa: N802
        transformed = cast(ast.BinOp, self.generic_visit(node))
        if isinstance(transformed.op, ast.Mult) and (
            _is_zero(transformed.left) or _is_zero(transformed.right)
        ):
            return ast.copy_location(ast.Constant(0), transformed)
        if isinstance(transformed.op, ast.Add):
            if _is_zero(transformed.left):
                return transformed.right
            if _is_zero(transformed.right):
                return transformed.left
        if isinstance(transformed.op, ast.Sub) and _is_zero(transformed.right):
            return transformed.left
        folded = _fold_constant_binary(transformed)
        return folded if folded is not None else transformed

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.expr:  # noqa: N802
        transformed = cast(ast.UnaryOp, self.generic_visit(node))
        if isinstance(transformed.operand, ast.Constant):
            value = transformed.operand.value
            if not isinstance(value, (int, float)):
                return transformed
            try:
                if isinstance(transformed.op, ast.UAdd):
                    return ast.copy_location(ast.Constant(+value), transformed)
                if isinstance(transformed.op, ast.USub):
                    return ast.copy_location(ast.Constant(-value), transformed)
            except (TypeError, ValueError):
                pass
        return transformed

    def visit_Compare(self, node: ast.Compare) -> ast.expr:  # noqa: N802
        transformed = cast(ast.Compare, self.generic_visit(node))
        if (
            len(transformed.ops) == 1
            and len(transformed.comparators) == 1
            and isinstance(transformed.left, ast.Constant)
            and isinstance(transformed.comparators[0], ast.Constant)
            and isinstance(transformed.left.value, (int, float))
            and isinstance(transformed.comparators[0].value, (int, float))
        ):
            value = _fold_constant_comparison(
                transformed.ops[0],
                transformed.left.value,
                transformed.comparators[0].value,
            )
            if value is not None:
                return ast.copy_location(ast.Constant(value), transformed)
        return transformed

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.expr:  # noqa: N802
        transformed = cast(ast.BoolOp, self.generic_visit(node))
        values = transformed.values
        if isinstance(transformed.op, ast.And):
            if any(_is_false(value) for value in values):
                return ast.copy_location(ast.Constant(False), transformed)
            kept = [value for value in values if not _is_true(value)]
        else:
            if any(_is_true(value) for value in values):
                return ast.copy_location(ast.Constant(True), transformed)
            kept = [value for value in values if not _is_false(value)]
        if not kept:
            return ast.copy_location(
                ast.Constant(isinstance(transformed.op, ast.And)), transformed
            )
        if len(kept) == 1:
            return kept[0]
        transformed.values = kept
        return transformed

    def visit_Call(self, node: ast.Call) -> ast.expr:  # noqa: N802
        transformed = cast(ast.Call, self.generic_visit(node))
        if (
            isinstance(transformed.func, ast.Name)
            and transformed.func.id == "float"
            and len(transformed.args) == 1
            and isinstance(transformed.args[0], ast.Constant)
            and isinstance(transformed.args[0].value, (int, float))
        ):
            try:
                return ast.copy_location(
                    ast.Constant(float(transformed.args[0].value)), transformed
                )
            except (TypeError, ValueError, OverflowError):
                pass
        return transformed


def _is_zero(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value == 0


def _is_true(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is True


def _is_false(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is False


def _fold_constant_binary(node: ast.BinOp) -> ast.Constant | None:
    if not isinstance(node.left, ast.Constant) or not isinstance(node.right, ast.Constant):
        return None
    left = node.left.value
    right = node.right.value
    if not isinstance(left, (int, float)) or not isinstance(right, (int, float)):
        return None
    try:
        if isinstance(node.op, ast.Add):
            value = left + right
        elif isinstance(node.op, ast.Sub):
            value = left - right
        elif isinstance(node.op, ast.Mult):
            value = left * right
        elif isinstance(node.op, ast.Div):
            value = left / right
        else:
            return None
    except (ArithmeticError, TypeError, ValueError):
        return None
    return ast.copy_location(ast.Constant(value), node)


def _fold_constant_comparison(
    operator: ast.cmpop,
    left: int | float,
    right: int | float,
) -> bool | None:
    try:
        if isinstance(operator, ast.Eq):
            return left == right
        if isinstance(operator, ast.Gt):
            return left > right
        if isinstance(operator, ast.GtE):
            return left >= right
        if isinstance(operator, ast.Lt):
            return left < right
        if isinstance(operator, ast.LtE):
            return left <= right
    except (TypeError, ValueError):
        return None
    return None


def _zero_multiplier_operand(node: ast.expr) -> ast.expr | None:
    if not isinstance(node, ast.BinOp) or not isinstance(node.op, ast.Mult):
        return None
    if isinstance(node.left, ast.Constant) and node.left.value == 0:
        return node.right
    if isinstance(node.right, ast.Constant) and node.right.value == 0:
        return node.left
    return None


def _load_object(path: Path) -> dict[str, object]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise SubmissionBuildError(f"expected JSON object: {path}")
    return payload


def _index_repairs(payload: object) -> dict[int, dict[str, object]]:
    if not isinstance(payload, list) or not payload:
        raise SubmissionBuildError("repair ledger must contain a non-empty repairs list")
    indexed: dict[int, dict[str, object]] = {}
    for raw in payload:
        if not isinstance(raw, dict):
            raise SubmissionBuildError("repair ledger entries must be objects")
        qid = raw.get("qid")
        years = raw.get("years")
        direction = raw.get("direction")
        if not isinstance(qid, int) or isinstance(qid, bool) or qid in indexed:
            raise SubmissionBuildError(f"invalid or duplicate repair QID: {qid!r}")
        if not isinstance(years, list) or not all(
            isinstance(year, int) and not isinstance(year, bool) for year in years
        ):
            raise SubmissionBuildError(f"QID {qid} has invalid years")
        if direction not in {"max", "min"}:
            raise SubmissionBuildError(f"QID {qid} has invalid direction")
        indexed[qid] = {"years": years, "direction": direction}
    return indexed


def _index_qids(payload: object, *, label: str) -> set[int]:
    if not isinstance(payload, list):
        raise SubmissionBuildError(f"repair ledger must contain a {label} list")
    if not all(isinstance(qid, int) and not isinstance(qid, bool) for qid in payload):
        raise SubmissionBuildError(f"repair ledger {label} must contain integer QIDs")
    qids = cast(list[int], payload)
    if len(qids) != len(set(qids)):
        raise SubmissionBuildError(f"repair ledger {label} contains duplicate QIDs")
    return set(qids)


def _index_records(records: list[dict[str, object]]) -> dict[int, dict[str, object]]:
    indexed: dict[int, dict[str, object]] = {}
    for row in records:
        qid = row.get("id")
        if not isinstance(qid, int) or isinstance(qid, bool) or qid in indexed:
            raise SubmissionBuildError(f"invalid or duplicate submission QID: {qid!r}")
        indexed[qid] = row
    return indexed


def _verify_uid_row(
    connection: sqlite3.Connection,
    qid: int,
    row: Mapping[str, str],
) -> tuple[str, str]:
    uid = row.get("observation_uid", "")
    value = row.get("value", "")
    source = connection.execute(
        """
        SELECT o.value_decimal_text, o.value_source_raw,
               o.directory_doc_id, t.line_start_1based
        FROM observations o
        JOIN tables t USING (table_uid)
        WHERE o.observation_uid = ?
        """,
        (uid,),
    ).fetchone()
    if source is None:
        raise SubmissionBuildError(f"QID {qid} CSV UID is absent from active A6: {uid!r}")
    try:
        csv_value = Decimal(value)
        source_value = Decimal(source["value_decimal_text"])
    except (InvalidOperation, TypeError) as error:
        raise SubmissionBuildError(f"QID {qid} has a non-decimal traced value: {uid!r}") from error
    if not csv_value.is_finite() or csv_value != source_value:
        raise SubmissionBuildError(
            f"QID {qid} CSV value differs from active A6 for UID {uid!r}: "
            f"{value!r} != {source['value_decimal_text']!r}"
        )
    return (
        f"{source['directory_doc_id']}|{source['line_start_1based']}",
        str(source["value_source_raw"] or ""),
    )


def _verify_raw_rows(
    qid: int,
    *,
    csv_row_values: list[dict[str, str]],
    record: Mapping[str, object],
    corpus_root: Path,
) -> int:
    tables = record.get("relevant_tables")
    if not isinstance(tables, list) or not tables or not all(
        isinstance(locator, str) for locator in tables
    ):
        raise SubmissionBuildError(f"QID {qid} raw CSV has no valid source locator")
    table_lines = [_read_source_table(corpus_root, locator) for locator in tables]
    for row in csv_row_values:
        raw_value = row.get("value_raw", "")
        if not raw_value or not any(raw_value in table for table in table_lines):
            raise SubmissionBuildError(
                f"QID {qid} raw CSV value is absent from its source table: {raw_value!r}"
            )
    return len(csv_row_values)


def _read_source_table(corpus_root: Path, locator: str) -> str:
    match = re.fullmatch(r"(?P<doc>[^|]+)\|(?P<line>[1-9]\d*)", locator)
    if match is None:
        raise SubmissionBuildError(f"invalid source locator: {locator!r}")
    document_id = match["doc"].removesuffix("_extracted")
    document = re.match(
        r"^(?P<ticker>[^_]+)_financial_statements_(?P<year>\d{4})(?:_|$)",
        document_id,
    )
    if document is None:
        raise SubmissionBuildError(f"invalid source document id: {document_id!r}")
    path = (
        corpus_root
        / document["ticker"]
        / document["year"]
        / document_id
        / f"{document_id}_extracted.txt"
    )
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
        table = lines[int(match["line"]) - 1]
    except (IndexError, OSError) as error:
        raise SubmissionBuildError(f"cannot read source locator {locator!r}") from error
    if not table.lstrip().startswith("<table"):
        raise SubmissionBuildError(f"source locator does not point to a table: {locator!r}")
    return table


def _verify_preservation(
    *,
    baseline_records: list[dict[str, object]],
    candidate_records: list[dict[str, object]],
    repaired_qids: set[int],
) -> None:
    baseline = _index_records(baseline_records)
    candidate = _index_records(candidate_records)
    if set(baseline) != set(candidate):
        raise SubmissionBuildError("candidate question scope differs from baseline")
    for qid in baseline:
        old = baseline[qid]
        new = candidate[qid]
        for field in ("id", "question", "answer", "evidence"):
            if old.get(field) != new.get(field):
                raise SubmissionBuildError(f"QID {qid} changed protected field {field!r}")
        if qid not in repaired_qids and old.get("pandas_query") != new.get("pandas_query"):
            raise SubmissionBuildError(f"QID {qid} changed an unreviewed pandas query")
