"""Build a scorer-safe V5 candidate with grounded program synthesis.

V5 deliberately separates three concerns which previous hybrid experiments
coupled together:

* scorer-facing retrieval references come from an already measured baseline;
* an open-weight model may select facts and a closed operation, but no values;
* a deterministic executor validates and computes every promoted answer.

The source submissions remain immutable.  Evidence files are copied byte for
byte and renamed per QID, while synthesized evidence is generated solely from
active A6 observations.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import re
import sqlite3
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import asdict, dataclass, replace
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from text2pandas.application.parsing.contracts import (
    OperationKind,
    QuestionAnnotations,
    ReturnMode,
)
from text2pandas.application.usecases.answer import AnswerResult
from text2pandas.application.usecases.grounded_resolution import (
    has_hard_logical_fact_conflict,
    is_high_trust_logical_fact,
)
from text2pandas.application.usecases.grounded_synthesis import (
    GroundedExecution,
    GroundedFact,
    GroundedOperation,
    GroundedPlan,
    GroundedPlanError,
    GroundedPlanGenerator,
    GroundedProgram,
    ProgramNode,
    ProgramOperation,
    execute_grounded,
)
from text2pandas.domain.metrics import normalize_phrase
from text2pandas.domain.semantic import Basis, Dimension
from text2pandas.infrastructure.retrieval.grounded import GroundedFactRetriever

PromotionMode = Literal[
    "recover_only", "replace_trusted", "replace_all", "shadow"
]


class GroundedV5BuildError(ValueError):
    """The immutable V5 candidate cannot be built safely."""


@dataclass(frozen=True, slots=True)
class GroundedV5Config:
    run_id: str
    promotion_mode: PromotionMode = "recover_only"
    minimum_confidence: float = 0.7
    fact_limit: int = 100
    selected_qids: frozenset[int] | None = None

    def __post_init__(self) -> None:
        if self.promotion_mode not in {
            "recover_only",
            "replace_trusted",
            "replace_all",
            "shadow",
        }:
            raise GroundedV5BuildError(
                f"unsupported promotion mode: {self.promotion_mode}"
            )
        if not 0 <= self.minimum_confidence <= 1:
            raise GroundedV5BuildError("minimum_confidence must be in [0, 1]")
        if self.fact_limit < 1:
            raise GroundedV5BuildError("fact_limit must be positive")


@dataclass(frozen=True, slots=True)
class GroundedV5Report:
    n_questions: int
    n_baseline_executable: int
    n_seed_executable: int
    n_attempted: int
    n_generated: int
    n_promoted: int
    n_recovered: int
    n_replaced: int
    n_final_executable: int
    outcomes: dict[str, int]
    results: list[AnswerResult]
    records_path: Path


class SubmissionBundle:
    """Read-only access to one exact submission ZIP."""

    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        if not self.path.is_file():
            raise GroundedV5BuildError(f"submission ZIP does not exist: {self.path}")
        try:
            self.archive = zipfile.ZipFile(self.path)
        except zipfile.BadZipFile as error:
            raise GroundedV5BuildError(f"invalid submission ZIP: {self.path}") from error
        roots = [
            name
            for name in self.archive.namelist()
            if name.endswith(".json") and "/" not in name.strip("/")
        ]
        if len(roots) != 1:
            self.archive.close()
            raise GroundedV5BuildError(
                f"submission must contain exactly one root JSON: {roots}"
            )
        try:
            rows = json.loads(self.archive.read(roots[0]).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            self.archive.close()
            raise GroundedV5BuildError(f"invalid submission JSON: {self.path}") from error
        if not isinstance(rows, list):
            self.archive.close()
            raise GroundedV5BuildError("submission JSON root must be a list")
        records: dict[int, dict[str, object]] = {}
        for raw in rows:
            if not isinstance(raw, Mapping):
                self.archive.close()
                raise GroundedV5BuildError("submission record must be an object")
            row = {str(key): value for key, value in raw.items()}
            try:
                qid = int(str(row["id"]))
            except (KeyError, ValueError) as error:
                self.archive.close()
                raise GroundedV5BuildError("submission record has invalid id") from error
            if qid in records:
                self.archive.close()
                raise GroundedV5BuildError(f"duplicate QID {qid} in {self.path}")
            records[qid] = row
        self.records = records
        self.sha256 = hashlib.sha256(self.path.read_bytes()).hexdigest()

    def close(self) -> None:
        self.archive.close()

    def read_member(self, name: str) -> bytes:
        if not name.startswith("data/"):
            raise GroundedV5BuildError(f"evidence is outside data/: {name!r}")
        try:
            return self.archive.read(name)
        except KeyError as error:
            raise GroundedV5BuildError(
                f"evidence member is missing from {self.path}: {name}"
            ) from error


def build_grounded_v5_candidate(
    *,
    baseline_zip: Path,
    secondary_zip: Path | None,
    questions_path: Path,
    a6_db: Path,
    output_dir: Path,
    generator: GroundedPlanGenerator,
    annotator: Any,
    config: GroundedV5Config,
    semantic_records_path: Path | None = None,
    query_expander: Any = None,
    progress: Any = None,
) -> GroundedV5Report:
    """Build one complete candidate and a per-QID attribution ledger."""

    if output_dir.exists():
        raise GroundedV5BuildError(f"immutable V5 output already exists: {output_dir}")
    if not a6_db.is_file():
        raise GroundedV5BuildError(f"active A6 database is missing: {a6_db}")
    questions = _questions(questions_path)
    baseline = SubmissionBundle(baseline_zip)
    secondary = SubmissionBundle(secondary_zip) if secondary_zip is not None else None
    try:
        _validate_source_coverage(baseline, questions, "baseline")
        if secondary is not None:
            _validate_source_coverage(secondary, questions, "secondary")
        output_dir.mkdir(parents=True, exist_ok=False)
        data_dir = output_dir / "data"
        data_dir.mkdir()
        records_path = output_dir / "records.jsonl"
        table_by_locator, locator_by_table = _table_locator_maps(a6_db)
        semantic_priors = _semantic_priors(semantic_records_path)
        connection = sqlite3.connect(
            f"file:{a6_db.resolve()}?mode=ro&immutable=1", uri=True
        )
        retriever = GroundedFactRetriever(connection)
        results: list[AnswerResult] = []
        outcomes: Counter[str] = Counter()
        baseline_executable = seed_executable = attempted = generated = 0
        promoted = recovered = replaced = 0
        try:
            with records_path.open("x", encoding="utf-8") as records_handle:
                for index, qid in enumerate(sorted(questions), 1):
                    question = questions[qid]
                    baseline_row = baseline.records[qid]
                    secondary_row = secondary.records[qid] if secondary is not None else None
                    baseline_ok = _is_executable(baseline_row)
                    baseline_executable += int(baseline_ok)
                    seed_row, seed_bundle, seed_source = _seed_record(
                        baseline_row, baseline, secondary_row, secondary
                    )
                    seed_ok = _is_executable(seed_row)
                    seed_executable += int(seed_ok)
                    result: AnswerResult | None = None
                    attempt: dict[str, object] = {
                        "status": "NOT_SELECTED",
                        "source": seed_source,
                    }
                    selected = config.selected_qids is None or qid in config.selected_qids
                    should_attempt = selected and (
                        config.promotion_mode
                        in {"replace_trusted", "replace_all", "shadow"}
                        or not seed_ok
                    )
                    if should_attempt:
                        attempted += 1
                        annotations = _expand_period_range_annotations(
                            question, annotator.annotate(question)
                        )
                        table_priors = [
                            table_by_locator[value]
                            for value in _strings(baseline_row.get("relevant_tables"))
                            if value in table_by_locator
                        ]
                        table_priors.extend(semantic_priors.get(qid, ()))
                        table_priors = list(dict.fromkeys(table_priors))
                        documents = _strings(baseline_row.get("relevant_docs"))
                        if not documents:
                            documents = _strings(seed_row.get("relevant_docs"))
                        query_terms: tuple[str, ...] = ()
                        query_concepts: tuple[Any, ...] = ()
                        required_metric_ids: tuple[str, ...] = ()
                        required_formulas: tuple[Any, ...] = ()
                        semantic_ast: object | None = None
                        if query_expander is not None:
                            expansion = query_expander.analyze(question)
                            query_terms = expansion.phrases
                            query_concepts = expansion.concepts
                            required_metric_ids = expansion.metric_ids
                            required_formulas = expansion.formulas
                            semantic_ast = expansion.semantic_ast
                        facts = retriever.retrieve(
                            question,
                            document_ids=documents,
                            table_uids=table_priors,
                            entities=annotations.entities,
                            periods=annotations.periods,
                            basis=annotations.basis,
                            query_terms=query_terms,
                            query_concepts=query_concepts,
                            preferred_dimension=_preferred_fact_dimension(
                                annotations,
                                required_metric_ids=required_metric_ids,
                                required_formulas=required_formulas,
                            ),
                            limit=config.fact_limit,
                        )
                        facts = _coherent_basis_candidates(
                            facts,
                            required_metric_ids=required_metric_ids,
                            requested_basis=annotations.basis,
                        )
                        facts = tuple(
                            sorted(
                                facts,
                                key=lambda fact: (
                                    fact.retrieval_metric is None,
                                    fact.retrieval_metric or "",
                                    fact.entity,
                                    fact.period or "",
                                    -fact.score,
                                    fact.observation_uid,
                                ),
                            )
                        )
                        generated_plan: GroundedPlan | GroundedProgram | None = None
                        candidate_failures: list[dict[str, str]] = []
                        try:
                            if not facts:
                                raise GroundedPlanError("no grounded fact candidates")
                            hints = _annotation_hints(annotations)
                            hints["required_metric_ids"] = list(required_metric_ids)
                            hints["metric_contracts"] = [
                                {
                                    "metric_id": concept.metric_id,
                                    "aliases": list(concept.aliases),
                                    "statement_types": list(concept.statement_types),
                                    "metric_codes": list(concept.metric_codes),
                                }
                                for concept in query_concepts
                            ]
                            hints["required_formulas"] = [
                                formula.to_planner_dict()
                                for formula in required_formulas
                            ]
                            if semantic_ast is not None:
                                hints["semantic_ast"] = semantic_ast
                            accepted: tuple[
                                GroundedPlan | GroundedProgram, GroundedExecution
                            ] | None = None
                            for candidate_index, plan in enumerate(
                                _plan_candidates(
                                    generator,
                                    question,
                                    facts,
                                    hints=hints,
                                ),
                                1,
                            ):
                                generated_plan = plan
                                generated += 1
                                try:
                                    _validate_plan_context(
                                        plan,
                                        facts,
                                        annotations,
                                        question=question,
                                        required_metric_ids=required_metric_ids,
                                        required_formulas=required_formulas,
                                    )
                                    execution = execute_grounded(plan, facts)
                                    confidence = plan.confidence or 0.0
                                    if confidence < config.minimum_confidence:
                                        raise GroundedPlanError(
                                            "plan confidence below promotion threshold: "
                                            f"{confidence:.3f} < "
                                            f"{config.minimum_confidence:.3f}"
                                        )
                                except GroundedPlanError as candidate_error:
                                    candidate_failures.append(
                                        {
                                            "candidate": str(candidate_index),
                                            "reason": str(candidate_error),
                                        }
                                    )
                                    continue
                                accepted = (plan, execution)
                                break
                            if accepted is None:
                                reason = (
                                    candidate_failures[-1]["reason"]
                                    if candidate_failures
                                    else "planner produced no candidate"
                                )
                                raise GroundedPlanError(reason)
                            plan, execution = accepted
                            trusted_replacement = _is_trusted_replacement(
                                plan, execution
                            )
                            trusted_recovery = _is_trusted_recovery(plan, execution)
                            will_promote = config.promotion_mode != "shadow" and (
                                config.promotion_mode == "replace_all"
                                or (not seed_ok and trusted_recovery)
                                or (
                                    config.promotion_mode == "replace_trusted"
                                    and trusted_replacement
                                )
                            )
                            if will_promote:
                                result = _materialize_synthesized_result(
                                    qid=qid,
                                    execution=execution,
                                    data_dir=data_dir,
                                    scorer_tables=_scorer_tables(
                                        baseline_row, seed_row
                                    ),
                                    locator_by_table=locator_by_table,
                                )
                                promoted += 1
                                recovered += int(not seed_ok)
                                replaced += int(seed_ok)
                                outcome = "PROMOTED_RECOVERY" if not seed_ok else "PROMOTED_REPLACEMENT"
                            elif config.promotion_mode == "replace_trusted" and seed_ok:
                                outcome = "KEPT_SEED_UNTRUSTED_REPLACEMENT"
                            else:
                                outcome = "SHADOW_OK"
                            outcomes[outcome] += 1
                            attempt = _attempt_payload(outcome, plan, facts, execution)
                            attempt["trusted_replacement"] = trusted_replacement
                            attempt["trusted_recovery"] = trusted_recovery
                            if candidate_failures:
                                attempt["candidate_failures"] = candidate_failures
                        except GroundedPlanError as error:
                            outcome = f"REJECTED:{str(error).split(':', 1)[0]}"
                            outcomes[outcome] += 1
                            attempt = {
                                "status": "REJECTED",
                                "reason": str(error),
                                "candidate_facts": len(facts),
                                "required_metric_ids": list(required_metric_ids),
                                "candidate_metric_counts": dict(
                                    sorted(
                                        Counter(
                                            fact.retrieval_metric or "<unbound>"
                                            for fact in facts
                                        ).items()
                                    )
                                ),
                                "candidate_metric_samples": {
                                    metric_id: [
                                        {
                                            "entity": fact.entity,
                                            "period": fact.period,
                                            "basis": fact.basis.value,
                                            "statement_type": fact.statement_type,
                                            "row": fact.row_path,
                                            "reasons": list(fact.score_reasons),
                                        }
                                        for fact in facts
                                        if fact.retrieval_metric == metric_id
                                    ][:10]
                                    for metric_id in required_metric_ids
                                },
                                "candidate_failures": candidate_failures,
                                "plan": (
                                    None
                                    if generated_plan is None
                                    else json.loads(
                                        json.dumps(
                                            asdict(generated_plan),
                                            default=_json_scalar,
                                            sort_keys=True,
                                        )
                                    )
                                ),
                            }
                    else:
                        outcomes["KEPT_SEED"] += 1
                    if result is None:
                        result = _materialize_source_result(
                            qid=qid,
                            row=seed_row,
                            source=seed_bundle,
                            data_dir=data_dir,
                            relevant_tables=_scorer_tables(baseline_row, seed_row),
                            source_label=seed_source,
                        )
                    results.append(result)
                    records_handle.write(
                        json.dumps(
                            {
                                "qid": qid,
                                "question": question,
                                "status": "OK" if result.answer is not None else "ABSTAIN",
                                "answer": result.answer,
                                "relevant_docs": result.relevant_docs,
                                "relevant_tables": result.relevant_tables,
                                "evidence": result.evidence,
                                "pandas_query": result.pandas_query,
                                "confidence": result.confidence,
                                "answer_source": result.notes[0] if result.notes else seed_source,
                                "grounded_v5": attempt,
                            },
                            ensure_ascii=False,
                            sort_keys=True,
                        )
                        + "\n"
                    )
                    if progress is not None:
                        progress(index, len(questions), promoted, outcomes)
        finally:
            connection.close()
        final_executable = sum(result.answer is not None for result in results)
        return GroundedV5Report(
            n_questions=len(questions),
            n_baseline_executable=baseline_executable,
            n_seed_executable=seed_executable,
            n_attempted=attempted,
            n_generated=generated,
            n_promoted=promoted,
            n_recovered=recovered,
            n_replaced=replaced,
            n_final_executable=final_executable,
            outcomes=dict(sorted(outcomes.items())),
            results=results,
            records_path=records_path,
        )
    finally:
        baseline.close()
        if secondary is not None:
            secondary.close()


def _plan_candidates(
    generator: GroundedPlanGenerator,
    question: str,
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object],
) -> Iterator[GroundedPlan | GroundedProgram]:
    cascade = getattr(generator, "generate_candidates", None)
    if callable(cascade):
        for candidate in cascade(question, facts, hints=hints):
            if not isinstance(candidate, (GroundedPlan, GroundedProgram)):
                raise GroundedPlanError("planner cascade returned an invalid candidate")
            yield candidate
        return
    yield generator.generate(question, facts, hints=hints)


def _questions(path: Path) -> dict[int, str]:
    output: dict[int, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        output[int(row["id"])] = str(row["question"])
    return output


def _validate_source_coverage(
    bundle: SubmissionBundle, questions: Mapping[int, str], label: str
) -> None:
    if set(bundle.records) != set(questions):
        raise GroundedV5BuildError(
            f"{label} QID coverage differs from source questions"
        )
    for qid, question in questions.items():
        if str(bundle.records[qid].get("question") or "") != question:
            raise GroundedV5BuildError(f"{label} question differs for QID {qid}")


def _table_locator_maps(database: Path) -> tuple[dict[str, str], dict[str, str]]:
    connection = sqlite3.connect(f"file:{database.resolve()}?mode=ro&immutable=1", uri=True)
    try:
        rows = connection.execute("SELECT table_uid, evidence_ref FROM tables").fetchall()
    finally:
        connection.close()
    by_locator: dict[str, str] = {}
    by_table: dict[str, str] = {}
    for table_uid, evidence_ref in rows:
        locator = str(evidence_ref).replace("|line:", "|")
        by_locator[locator] = str(table_uid)
        by_table[str(table_uid)] = locator
    return by_locator, by_table


def _semantic_priors(path: Path | None) -> dict[int, tuple[str, ...]]:
    if path is None:
        return {}
    if not path.is_file():
        raise GroundedV5BuildError(f"semantic prior records are missing: {path}")
    output: dict[int, tuple[str, ...]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        qid = int(row["qid"])
        output[qid] = tuple(_strings(row.get("candidate_tables")))
    return output


def _seed_record(
    baseline_row: dict[str, object],
    baseline: SubmissionBundle,
    secondary_row: dict[str, object] | None,
    secondary: SubmissionBundle | None,
) -> tuple[dict[str, object], SubmissionBundle, str]:
    if (
        not _is_executable(baseline_row)
        and secondary_row is not None
        and secondary is not None
        and _is_executable(secondary_row)
    ):
        return secondary_row, secondary, "secondary_recovery"
    return baseline_row, baseline, "baseline"


def _is_executable(row: Mapping[str, object]) -> bool:
    evidence = row.get("evidence")
    return (
        isinstance(evidence, Sequence)
        and not isinstance(evidence, (str, bytes))
        and bool(evidence)
        and bool(str(row.get("pandas_query") or ""))
        and _finite_number(row.get("answer")) is not None
    )


def _finite_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        output = float(str(value))
    except (TypeError, ValueError, OverflowError):
        return None
    return output if math.isfinite(output) else None


def _scorer_tables(
    baseline_row: Mapping[str, object], seed_row: Mapping[str, object]
) -> list[str]:
    baseline = _strings(baseline_row.get("relevant_tables"))
    return baseline or _strings(seed_row.get("relevant_tables"))


def _materialize_source_result(
    *,
    qid: int,
    row: Mapping[str, object],
    source: SubmissionBundle,
    data_dir: Path,
    relevant_tables: list[str],
    source_label: str,
) -> AnswerResult:
    executable = _is_executable(row)
    evidence: list[dict[str, str]] = []
    if executable:
        raw_evidence = row.get("evidence")
        assert isinstance(raw_evidence, Sequence)
        for index, item in enumerate(raw_evidence, 1):
            if not isinstance(item, Mapping):
                raise GroundedV5BuildError(f"invalid evidence for QID {qid}")
            variable = str(item.get("variable") or "")
            source_path = str(item.get("csv_path") or "")
            if not variable or not source_path:
                raise GroundedV5BuildError(f"incomplete evidence for QID {qid}")
            payload = source.read_member(source_path)
            digest = hashlib.sha256(payload).hexdigest()[:12]
            target_name = f"seed_q{qid:04d}_{index}_{digest}.csv"
            target = data_dir / target_name
            if target.exists() and target.read_bytes() != payload:
                raise GroundedV5BuildError(f"evidence collision: {target}")
            target.write_bytes(payload)
            evidence.append({"variable": variable, "csv_path": f"data/{target_name}"})
    tables = list(dict.fromkeys(relevant_tables))
    documents = list(dict.fromkeys(value.rsplit("|", 1)[0] for value in tables))
    return AnswerResult(
        qid=qid,
        answer=_finite_number(row.get("answer")) if executable else None,
        relevant_docs=documents,
        relevant_tables=tables,
        evidence=evidence,
        pandas_query=str(row.get("pandas_query") or "") if executable else "",
        confidence=1.0 if executable else 0.0,
        csv_name=Path(evidence[0]["csv_path"]).name if evidence else "",
        has_csv=bool(evidence),
        notes=[source_label],
    )


def _materialize_synthesized_result(
    *,
    qid: int,
    execution: GroundedExecution,
    data_dir: Path,
    scorer_tables: list[str],
    locator_by_table: Mapping[str, str],
) -> AnswerResult:
    target_name = f"v5_q{qid:04d}.csv"
    target = data_dir / target_name
    with target.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(
            [
                "observation_uid",
                "value",
                "table_uid",
                "document_id",
                "entity",
                "period",
                "dimension",
                "scale_exponent",
                "row_path",
                "column_path",
            ]
        )
        for fact in execution.facts:
            writer.writerow(
                [
                    fact.observation_uid,
                    str(fact.value),
                    fact.table_uid,
                    fact.document_id,
                    fact.entity,
                    fact.period or "",
                    fact.dimension.value,
                    "" if fact.scale_exponent is None else fact.scale_exponent,
                    fact.row_path,
                    fact.column_path,
                ]
            )
    tables = list(dict.fromkeys(scorer_tables))
    if not tables:
        tables = list(
            dict.fromkeys(
                locator_by_table[fact.table_uid]
                for fact in execution.facts
                if fact.table_uid in locator_by_table
            )
        )
    documents = list(dict.fromkeys(value.rsplit("|", 1)[0] for value in tables))
    confidence = execution.plan.confidence or 0.0
    return AnswerResult(
        qid=qid,
        answer=execution.answer,
        relevant_docs=documents,
        relevant_tables=tables,
        evidence=[{"variable": "df1", "csv_path": f"data/{target_name}"}],
        pandas_query=execution.pandas_query,
        confidence=confidence,
        csv_name=target_name,
        has_csv=True,
        notes=["grounded_v5"],
    )


def _annotation_hints(annotation: QuestionAnnotations) -> dict[str, object]:
    return {
        "entities": list(annotation.entities),
        "periods": list(annotation.periods),
        "basis": annotation.basis.value,
        "requested_unit": annotation.requested_unit.to_dict(),
        "operation": annotation.operation.value,
        "return_mode": annotation.return_mode.value,
        "rank_direction": (
            None if annotation.rank_direction is None else annotation.rank_direction.value
        ),
        "reverse_difference": annotation.reverse_difference,
        "absolute_difference": annotation.absolute_difference,
        "operation_evidence": annotation.operation_evidence,
    }


def _preferred_fact_dimension(
    annotation: QuestionAnnotations,
    *,
    required_metric_ids: Sequence[str],
    required_formulas: Sequence[Any],
) -> Dimension:
    """Return a safe leaf-dimension prior for direct-value retrieval only."""

    if required_formulas or len(required_metric_ids) > 1:
        return Dimension.UNKNOWN
    if annotation.operation not in {
        OperationKind.LOOKUP,
        OperationKind.SUM,
        OperationKind.AVERAGE,
        OperationKind.EXTREMUM,
        OperationKind.SUBTRACT,
    }:
        return Dimension.UNKNOWN
    return annotation.requested_unit.dimension


def _expand_period_range_annotations(
    question: str, annotation: QuestionAnnotations
) -> QuestionAnnotations:
    normalized = normalize_phrase(question)
    # "Tiền thuê tối thiểu" is an accounting metric noun phrase, not a
    # request to take the minimum.  The lexical annotator otherwise routes
    # these direct-value questions into the extremum validator.
    if (
        annotation.operation is OperationKind.EXTREMUM
        and "tien thue toi thieu" in normalized
    ):
        annotation = replace(
            annotation,
            operation=OperationKind.LOOKUP,
            return_mode=ReturnMode.VALUE,
            rank_direction=None,
            operation_evidence="accounting_metric:minimal_lease_payment",
        )
    if (
        len(annotation.periods) == 1
        and "dau nam" in normalized
        and "cuoi nam" in normalized
    ):
        try:
            year = int(annotation.periods[0][:4])
        except ValueError:
            return annotation
        return replace(annotation, periods=(str(year - 1), str(year)))
    if len(annotation.periods) == 1 and "binh quan" in normalized and any(
        cue in normalized for cue in ("tong tai san", "von chu so huu")
    ):
        try:
            year = int(annotation.periods[0][:4])
        except ValueError:
            return annotation
        return replace(annotation, periods=(str(year - 1), str(year)))
    if (
        len(annotation.periods) == 2
        and ("365" in normalized or "so ngay ton kho" in normalized)
        and ("hang ton kho" in normalized or "so ngay ton kho" in normalized)
        and (
            "so ngay ton kho" in normalized
            or any(value in normalized for value in ("binh quan", "trung binh"))
        )
    ):
        try:
            start, end = (int(value[:4]) for value in annotation.periods)
        except ValueError:
            return annotation
        return replace(
            annotation,
            periods=tuple(str(year) for year in range(start - 1, end + 1)),
        )
    if len(annotation.periods) != 2 or "giai doan" not in normalized:
        return annotation
    try:
        start, end = (int(value[:4]) for value in annotation.periods)
    except ValueError:
        return annotation
    if start > end or end - start > 20:
        return annotation
    return replace(
        annotation,
        periods=tuple(str(year) for year in range(start, end + 1)),
    )


def _validate_plan_context(
    plan: GroundedPlan | GroundedProgram,
    candidates: Sequence[GroundedFact],
    annotation: QuestionAnnotations,
    *,
    question: str = "",
    required_metric_ids: Sequence[str] = (),
    required_formulas: Sequence[Any] = (),
) -> None:
    reachable_nodes: Sequence[ProgramNode] = ()
    if isinstance(plan, GroundedPlan):
        expected = _expected_operations(annotation)
        if expected and plan.operation not in expected:
            raise GroundedPlanError(
                f"operation mismatch: expected {sorted(value.value for value in expected)}, "
                f"received {plan.operation.value}"
            )
        selected_uids = tuple(
            dict.fromkeys((*plan.operand_uids, *plan.selector_uids, *plan.value_uids))
        )
    else:
        reachable_nodes = _reachable_program_nodes(plan)
        selected_uids = tuple(
            dict.fromkeys(uid for node in reachable_nodes for uid in node.fact_uids)
        )
        _validate_program_shape(plan, annotation, nodes=reachable_nodes)
        _validate_required_formula_operations(
            plan,
            required_formulas,
            candidates=candidates,
            nodes=reachable_nodes,
        )
        _validate_program_literals(plan, question, nodes=reachable_nodes)
    requested_dimension = annotation.requested_unit.dimension
    compatible_dimensions = {requested_dimension}
    if requested_dimension is Dimension.PERCENT_POINT:
        compatible_dimensions.add(Dimension.PERCENT)
    if (
        requested_dimension is not Dimension.UNKNOWN
        and plan.output_dimension not in compatible_dimensions
    ):
        raise GroundedPlanError(
            "requested output dimension mismatch: "
            f"{requested_dimension.value} vs {plan.output_dimension.value}"
        )
    if requested_dimension in {Dimension.MONEY, Dimension.SHARES}:
        expected_scale = annotation.requested_unit.scale_exponent
        if expected_scale is not None and plan.output_scale_exponent != expected_scale:
            raise GroundedPlanError(
                f"requested output scale mismatch: {expected_scale} vs "
                f"{plan.output_scale_exponent}"
            )
    facts_by_uid = {fact.observation_uid: fact for fact in candidates}
    selected = [facts_by_uid[uid] for uid in selected_uids if uid in facts_by_uid]
    partial_output_metrics = (
        _select_output_metrics(plan, candidates, reachable_nodes)
        if isinstance(plan, GroundedProgram)
        else set()
    )
    if required_metric_ids:
        _validate_required_metric_coverage(
            selected,
            annotation,
            tuple(dict.fromkeys(required_metric_ids)),
            allow_leading_period_gap=(
                isinstance(plan, GroundedProgram)
                and {
                    ProgramOperation.ROLLING_GROWTH,
                    ProgramOperation.SELECT_AT_KEY,
                }
                <= {node.operation for node in plan.nodes}
            ),
            partial_entity_metrics=partial_output_metrics,
        )
    if annotation.entities:
        selected_entities = {fact.entity for fact in selected}
        missing = set(annotation.entities) - selected_entities
        if missing:
            raise GroundedPlanError(f"selected facts miss requested entities: {sorted(missing)}")
    if annotation.periods:
        selected_periods = {
            str(fact.period_year) for fact in selected if fact.period_year is not None
        }
        required_periods = {value[:4] for value in annotation.periods}
        missing = required_periods - selected_periods
        if missing:
            raise GroundedPlanError(f"selected facts miss requested periods: {sorted(missing)}")
    if annotation.basis is not Basis.UNSPECIFIED:
        wrong_basis = [
            fact.observation_uid
            for fact in selected
            if fact.basis is not annotation.basis
        ]
        if wrong_basis:
            raise GroundedPlanError(
                f"selected facts violate requested basis: {wrong_basis[:5]}"
            )
    else:
        bases_by_entity: dict[str, set[Basis]] = defaultdict(set)
        for fact in selected:
            if fact.entity and fact.basis is not Basis.UNSPECIFIED:
                bases_by_entity[fact.entity].add(fact.basis)
        mixed = {
            entity: sorted(value.value for value in bases)
            for entity, bases in bases_by_entity.items()
            if len(bases) > 1
        }
        if mixed:
            raise GroundedPlanError(
                f"selected facts mix statement bases by entity: {mixed}"
            )


def _coherent_basis_candidates(
    facts: Sequence[GroundedFact],
    *,
    required_metric_ids: Sequence[str],
    requested_basis: Basis,
) -> tuple[GroundedFact, ...]:
    """Select one statement basis per entity for grounded computation.

    Retrieval scores are metric-local.  Without a bundle-level decision, one
    operand or lexical duplicate can come from a separate report while the
    remaining evidence comes from consolidated reports.  Choose the basis with
    the best metric-period coverage, then prefer consolidated scope and score.
    """

    required = set(required_metric_ids)
    if requested_basis is not Basis.UNSPECIFIED:
        return tuple(facts)
    coverage: dict[tuple[str, Basis], set[tuple[str, str]]] = defaultdict(set)
    scores: dict[tuple[str, Basis], float] = defaultdict(float)
    for fact in facts:
        metric = fact.retrieval_metric or normalize_phrase(
            fact.row_path.rsplit("›", 1)[-1]
        )
        year = str(fact.period_year or "")
        if (
            fact.entity
            and (not required or metric in required)
            and metric
            and year
            and fact.basis is not Basis.UNSPECIFIED
        ):
            key = (fact.entity, fact.basis)
            coverage[key].add((metric, year))
            scores[key] += fact.score
    chosen: dict[str, Basis] = {}
    entities = {entity for entity, _basis in coverage}
    for entity in entities:
        choices = [key for key in coverage if key[0] == entity]

        def choice_key(key: tuple[str, Basis]) -> tuple[int, float, float, str]:
            scope_priority = float(key[1] is Basis.CONSOLIDATED)
            second = scope_priority if required else scores[key]
            third = scores[key] if required else scope_priority
            return len(coverage[key]), second, third, key[1].value

        selected = max(
            choices,
            key=choice_key,
        )
        chosen[entity] = selected[1]
    return tuple(
        fact
        for fact in facts
        if fact.entity not in chosen
        or fact.basis is chosen[fact.entity]
    )


_TRUSTED_REPLACEMENT_METRIC_CODES: dict[str, frozenset[str]] = {
    "net_revenue": frozenset({"10"}),
    "cogs": frozenset({"11"}),
    "gross_profit": frozenset({"20"}),
    "profit_before_tax": frozenset({"50"}),
    "profit_after_tax": frozenset({"60"}),
    "interest_expense": frozenset({"23"}),
    "cash_flow_from_operations": frozenset({"20"}),
    "current_assets": frozenset({"100"}),
    "inventory": frozenset({"140", "141"}),
    "total_assets": frozenset({"270"}),
    "total_liabilities": frozenset({"300"}),
    "current_liabilities": frozenset({"310"}),
    "equity": frozenset({"400", "410"}),
}

_TRUSTED_REPLACEMENT_LABELS: dict[str, tuple[str, ...]] = {
    "net_revenue": ("doanh thu thuan",),
    "cogs": ("gia von hang ban",),
    "gross_profit": ("loi nhuan gop",),
    "profit_before_tax": ("loi nhuan truoc thue",),
    "profit_after_tax": ("loi nhuan sau thue", "loi nhuan thuan sau thue"),
    "interest_expense": ("chi phi lai vay",),
    "cash_flow_from_operations": (
        "luu chuyen tien thuan tu hoat dong kinh doanh",
    ),
    "current_assets": ("tai san ngan han",),
    "inventory": ("hang ton kho",),
    "total_assets": ("tong cong tai san", "tong tai san"),
    "total_liabilities": ("no phai tra",),
    "current_liabilities": ("no ngan han",),
    "equity": ("von chu so huu",),
}

_UNTRUSTED_REPLACEMENT_CONTEXT = (
    "bo phan",
    "khu vuc",
    "dia ly",
    "theo san pham",
    "thuyet minh",
)

_TRUSTED_REPLACEMENT_COMPOSITION = frozenset(
    {
        ProgramOperation.FILTER,
        ProgramOperation.ARGMAX_KEY,
        ProgramOperation.ARGMIN_KEY,
        ProgramOperation.SELECT_AT_KEY,
        ProgramOperation.COUNT_TRUE,
        ProgramOperation.MEDIAN,
        ProgramOperation.LOGICAL_AND,
        ProgramOperation.LOGICAL_OR,
        ProgramOperation.GROWTH_BY_ENTITY,
        ProgramOperation.ROLLING_GROWTH,
        ProgramOperation.ROLLING_CHANGE,
        ProgramOperation.CHANGE_BY_ENTITY,
        ProgramOperation.EARLIEST_BY_ENTITY,
        ProgramOperation.LATEST_BY_ENTITY,
        ProgramOperation.ALL_BY_ENTITY,
        ProgramOperation.ANY_BY_ENTITY,
        ProgramOperation.CAGR_BY_ENTITY,
        ProgramOperation.TOP_K_MASK,
        ProgramOperation.BOTTOM_K_MASK,
        ProgramOperation.FIRST_TRUE_KEY,
        ProgramOperation.LAST_TRUE_KEY,
        ProgramOperation.SHIFT_KEY,
        ProgramOperation.KEY_TO_NUMBER,
        ProgramOperation.IS_NONZERO,
        ProgramOperation.IS_ZERO,
    }
)

_TRUSTED_REPLACEMENT_ALGEBRA = frozenset(
    {
        ProgramOperation.FACTS,
        ProgramOperation.LITERAL,
        ProgramOperation.SUM,
        ProgramOperation.AVERAGE,
        ProgramOperation.MEDIAN,
        ProgramOperation.MINIMUM,
        ProgramOperation.MAXIMUM,
        ProgramOperation.ADD,
        ProgramOperation.SUBTRACT,
        ProgramOperation.MULTIPLY,
        ProgramOperation.DIVIDE,
        ProgramOperation.ABSOLUTE,
        ProgramOperation.GROWTH,
        ProgramOperation.TO_PERCENT,
    }
)


def _is_trusted_replacement(
    plan: GroundedPlan | GroundedProgram,
    execution: GroundedExecution,
) -> bool:
    """Gate replacement of an already executable seed to high-trust DAGs.

    Recovery can add a previously missing answer without destroying a correct
    seed.  Replacement has a much higher downside, so direct lexical/reported
    metrics are excluded and every selected canonical fact must carry the
    governed financial-statement code for its metric.
    """

    if not isinstance(plan, GroundedProgram):
        return False
    operations = {
        node.operation for node in _reachable_program_nodes(plan)
    }
    resolver_trusted = bool(execution.facts) and all(
        is_high_trust_logical_fact(fact) for fact in execution.facts
    )
    if resolver_trusted and (
        operations & _TRUSTED_REPLACEMENT_COMPOSITION
        or operations <= _TRUSTED_REPLACEMENT_ALGEBRA
    ):
        return True
    # The historical metric-code fallback predates logical fact resolution.
    # It must never bypass hard resolver conflicts such as collisions, missing
    # query qualifiers or period/basis mismatches.
    if any(has_hard_logical_fact_conflict(fact) for fact in execution.facts):
        return False
    if not operations & _TRUSTED_REPLACEMENT_COMPOSITION:
        return False
    for fact in execution.facts:
        metric = fact.retrieval_metric or ""
        expected_codes = _TRUSTED_REPLACEMENT_METRIC_CODES.get(metric)
        if expected_codes is None:
            return False
        if fact.metric_code in expected_codes:
            continue
        leaf = normalize_phrase(fact.row_path.rsplit("›", 1)[-1])
        labels = _TRUSTED_REPLACEMENT_LABELS.get(metric, ())
        context = normalize_phrase(f"{fact.row_path} {fact.section_text}")
        if not any(leaf.startswith(label) for label in labels) or any(
            cue in context for cue in _UNTRUSTED_REPLACEMENT_CONTEXT
        ):
            return False
    return bool(execution.facts)


def _is_trusted_recovery(
    plan: GroundedPlan | GroundedProgram,
    execution: GroundedExecution,
) -> bool:
    """Allow recovery only from structurally resolved governed facts.

    A missing seed is not permission to emit the first lexical number.  This
    gate is broader than replacement (source-resolved note metrics are useful
    recoveries) while still requiring a named metric, structural row identity,
    acceptable source quality and a decisive resolver result.
    """

    if not isinstance(plan, GroundedProgram) or not execution.facts:
        return False
    for fact in execution.facts:
        if has_hard_logical_fact_conflict(fact):
            return False
        metric = fact.retrieval_metric or ""
        governed_metric = (
            metric in _TRUSTED_REPLACEMENT_METRIC_CODES
            or metric.startswith(("source_", "reported_"))
        )
        if not governed_metric:
            return False
        reasons = set(fact.score_reasons)
        structural_identity = bool(
            {
                "metric:governed_code",
                "metric:exact_row",
                "metric:prefix_row",
                "metric:source_context_complete",
                "metric:query_qualifier_match",
                "metric:required_context_match",
                "source:movement_presentation_order_match",
            }
            & reasons
        )
        if not structural_identity:
            return False
        if fact.source_confidence is not None and fact.source_confidence < 0.65:
            return False
        if (
            "metric:governed_code" not in reasons
            and fact.resolution_margin is not None
            and fact.resolution_margin < 30.0
            and fact.corroboration_count < 2
        ):
            return False
    return True


def _validate_required_metric_coverage(
    selected: Sequence[GroundedFact],
    annotation: QuestionAnnotations,
    required_metric_ids: Sequence[str],
    *,
    allow_leading_period_gap: bool = False,
    partial_entity_metrics: set[str] | None = None,
) -> None:
    selected_metrics = {fact.retrieval_metric for fact in selected}
    missing_metrics = set(required_metric_ids) - selected_metrics
    if missing_metrics:
        raise GroundedPlanError(
            f"program misses required metrics: {sorted(missing_metrics)}"
        )
    required_entities = set(annotation.entities)
    required_periods = {value[:4] for value in annotation.periods}
    for metric_id in required_metric_ids:
        metric_facts = [
            fact for fact in selected if fact.retrieval_metric == metric_id
        ]
        if required_entities and metric_id not in (partial_entity_metrics or set()):
            missing_entities = required_entities - {
                fact.entity for fact in metric_facts
            }
            if missing_entities:
                raise GroundedPlanError(
                    f"metric {metric_id} misses entities: {sorted(missing_entities)}"
                )
        if required_periods:
            missing_periods = required_periods - {
                str(fact.period_year)
                for fact in metric_facts
                if fact.period_year is not None
            }
            allowed_gap = (
                {min(required_periods)}
                if allow_leading_period_gap and len(required_periods) > 2
                else set()
            )
            if missing_periods - allowed_gap:
                raise GroundedPlanError(
                    f"metric {metric_id} misses periods: {sorted(missing_periods)}"
                )


def _select_output_metrics(
    program: GroundedProgram,
    candidates: Sequence[GroundedFact],
    nodes: Sequence[ProgramNode],
) -> set[str]:
    nodes_by_id = {node.node_id: node for node in nodes}
    output = nodes_by_id.get(program.output_node_id)
    if output is None or output.operation is not ProgramOperation.SELECT_AT_KEY:
        return set()
    facts_by_uid = {fact.observation_uid: fact for fact in candidates}
    metrics: set[str] = set()
    visited: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in visited:
            return
        visited.add(node_id)
        node = nodes_by_id.get(node_id)
        if node is None:
            return
        for uid in node.fact_uids:
            fact = facts_by_uid.get(uid)
            if fact is not None and fact.retrieval_metric:
                metrics.add(fact.retrieval_metric)
        for input_id in node.input_ids:
            visit(input_id)

    visit(output.input_ids[0])
    return metrics


def _expected_operations(annotation: QuestionAnnotations) -> set[GroundedOperation]:
    if annotation.operation is OperationKind.LOOKUP:
        return {GroundedOperation.LOOKUP}
    if annotation.operation is OperationKind.DIVIDE:
        return {GroundedOperation.RATIO}
    if annotation.operation is OperationKind.SUBTRACT:
        return {GroundedOperation.DIFFERENCE}
    if annotation.operation is OperationKind.GROWTH:
        return {GroundedOperation.GROWTH}
    if annotation.operation is OperationKind.SUM:
        return {GroundedOperation.SUM}
    if annotation.operation is OperationKind.AVERAGE:
        return {GroundedOperation.AVERAGE}
    if annotation.operation is OperationKind.COUNT:
        return {GroundedOperation.COUNT}
    if annotation.operation is OperationKind.EXTREMUM:
        if annotation.return_mode is ReturnMode.SELECT_AT_ARG:
            return {GroundedOperation.SELECT_AT_ARG}
        if annotation.return_mode is ReturnMode.MEMBER:
            return {GroundedOperation.ARGMAX_PERIOD, GroundedOperation.ARGMIN_PERIOD}
        return {GroundedOperation.MINIMUM, GroundedOperation.MAXIMUM}
    return set()


def _validate_program_shape(
    program: GroundedProgram,
    annotation: QuestionAnnotations,
    *,
    nodes: Sequence[ProgramNode] | None = None,
) -> None:
    selected_nodes = program.nodes if nodes is None else nodes
    operations = {node.operation for node in selected_nodes}
    required: set[ProgramOperation] = set()
    if annotation.operation is OperationKind.COUNT:
        required.add(ProgramOperation.COUNT_TRUE)
    elif annotation.operation is OperationKind.GROWTH:
        if not operations.intersection(
            {
                ProgramOperation.GROWTH,
                ProgramOperation.GROWTH_BY_ENTITY,
                ProgramOperation.ROLLING_GROWTH,
                ProgramOperation.CAGR_BY_ENTITY,
            }
        ):
            raise GroundedPlanError("growth program has no temporal growth node")
    elif annotation.operation is OperationKind.AVERAGE:
        required.add(ProgramOperation.AVERAGE)
    elif annotation.operation is OperationKind.SUM:
        required.add(ProgramOperation.SUM)
    elif annotation.operation is OperationKind.DIVIDE:
        required.add(ProgramOperation.DIVIDE)
    elif annotation.operation is OperationKind.SUBTRACT:
        if not operations.intersection(
            {
                ProgramOperation.SUBTRACT,
                ProgramOperation.CHANGE_BY_ENTITY,
                ProgramOperation.ROLLING_CHANGE_BY_ENTITY,
                ProgramOperation.ROLLING_CHANGE,
            }
        ):
            required.add(ProgramOperation.SUBTRACT)
    elif (
        annotation.operation is OperationKind.EXTREMUM
        and not operations.intersection(
            {
                ProgramOperation.MINIMUM,
                ProgramOperation.MAXIMUM,
                ProgramOperation.ARGMIN_KEY,
                ProgramOperation.ARGMAX_KEY,
                ProgramOperation.SELECT_AT_KEY,
            }
        )
    ):
        raise GroundedPlanError("extremum program has no ranking/extremum node")
    missing = required - operations
    if missing:
        raise GroundedPlanError(
            f"program misses required operations: {sorted(value.value for value in missing)}"
        )


def _validate_program_literals(
    program: GroundedProgram,
    question: str,
    *,
    nodes: Sequence[ProgramNode] | None = None,
) -> None:
    selected_nodes = program.nodes if nodes is None else nodes
    literals = {
        node.literal for node in selected_nodes if node.literal is not None
    }
    if not literals:
        return
    normalized = question.lower().replace("−", "-")
    allowed: set[Decimal] = set()
    for raw in re.findall(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?", normalized):
        value = Decimal(raw.replace(",", "."))
        if value == value.to_integral() and 1900 <= value <= 2100:
            continue
        allowed.add(value)
    if any(
        cue in normalized
        for cue in (
            " âm",
            " dương",
            "không âm",
            "không dương",
            "cải thiện",
            "tăng trưởng dương",
            "giảm so với",
            "tăng so với",
        )
    ):
        allowed.add(Decimal(0))
    if "số ngày tồn kho" in normalized:
        allowed.add(Decimal(365))
    if any(cue in normalized for cue in ("năm ngay sau", "sau năm đầu tiên")):
        allowed.add(Decimal(1))
    unsupported = literals - allowed
    if unsupported:
        raise GroundedPlanError(
            "program invents literals absent from question: "
            f"{sorted(str(value) for value in unsupported)}"
        )


def _validate_required_formula_operations(
    program: GroundedProgram,
    requirements: Sequence[Any],
    *,
    candidates: Sequence[GroundedFact] = (),
    nodes: Sequence[ProgramNode] | None = None,
) -> None:
    expected: Counter[ProgramOperation] = Counter()
    for requirement in requirements:
        _collect_formula_operations(requirement.expression, expected)
    selected_nodes = program.nodes if nodes is None else nodes
    actual = Counter(node.operation for node in selected_nodes)
    missing = {
        operation.value: count - actual[operation]
        for operation, count in expected.items()
        if actual[operation] < count
    }
    if missing:
        raise GroundedPlanError(f"program misses required formula operations: {missing}")
    if not requirements or not candidates:
        return

    # Operation counts alone are insufficient: a planner could place a valid
    # divide/subtract on unrelated metrics or leave the required formula in a
    # disconnected branch.  Compare the exact typed expression tree rooted at
    # every reachable node, including operand order for divide/subtract.
    facts_by_uid = {fact.observation_uid: fact for fact in candidates}
    nodes_by_id = {node.node_id: node for node in selected_nodes}
    signatures: dict[str, tuple[object, ...] | None] = {}

    def actual_signature(node_id: str) -> tuple[object, ...] | None:
        if node_id in signatures:
            return signatures[node_id]
        node = nodes_by_id[node_id]
        signature: tuple[object, ...] | None = None
        if node.operation is ProgramOperation.FACTS:
            metrics = {
                facts_by_uid[uid].retrieval_metric
                for uid in node.fact_uids
                if uid in facts_by_uid and facts_by_uid[uid].retrieval_metric
            }
            if len(metrics) == 1:
                signature = ("metric", next(iter(metrics)))
        elif node.operation in {
            ProgramOperation.ADD,
            ProgramOperation.SUBTRACT,
            ProgramOperation.MULTIPLY,
            ProgramOperation.DIVIDE,
        } and len(node.input_ids) == 2:
            left = actual_signature(node.input_ids[0])
            right = actual_signature(node.input_ids[1])
            if left is not None and right is not None:
                signature = (node.operation.value, left, right)
        elif (
            node.operation
            in {
                ProgramOperation.ABSOLUTE,
                ProgramOperation.ROLLING_AVERAGE_BY_ENTITY,
            }
            and len(node.input_ids) == 1
        ):
            child = actual_signature(node.input_ids[0])
            if child is not None:
                signature = (node.operation.value, child)
        signatures[node_id] = signature
        return signature

    actual_signatures = {
        signature
        for node in selected_nodes
        if (signature := actual_signature(node.node_id)) is not None
    }
    for requirement in requirements:
        expression = getattr(requirement, "expression", None)
        formula_id = str(getattr(requirement, "formula_id", "unknown"))
        if not isinstance(expression, Mapping):
            raise GroundedPlanError(
                f"required formula {formula_id} has no expression contract"
            )
        expected_signature = _formula_expression_signature(expression)
        if expected_signature not in actual_signatures:
            raise GroundedPlanError(
                f"program violates required formula lineage: {formula_id}"
            )


def _formula_expression_signature(
    expression: Mapping[str, object],
) -> tuple[object, ...]:
    expression_type = str(expression.get("type") or "")
    if expression_type == "metric_ref":
        metric_id = str(expression.get("metric_id") or "")
        if not metric_id:
            raise GroundedPlanError("formula metric_ref has no metric_id")
        return ("metric", metric_id)
    if expression_type == "arithmetic":
        operation = str(expression.get("operator") or "")
        if operation not in {"add", "subtract", "multiply", "divide"}:
            raise GroundedPlanError(f"unsupported formula operator: {operation}")
        left = expression.get("left")
        right = expression.get("right")
        if not isinstance(left, Mapping) or not isinstance(right, Mapping):
            raise GroundedPlanError("formula arithmetic operands must be expressions")
        return (
            operation,
            _formula_expression_signature(left),
            _formula_expression_signature(right),
        )
    if expression_type == "unary" and str(expression.get("operator") or "") == "absolute":
        child = expression.get("expression")
        if not isinstance(child, Mapping):
            raise GroundedPlanError("formula absolute operand must be an expression")
        return ("absolute", _formula_expression_signature(child))
    if expression_type == "average_balance_ratio":
        numerator = str(expression.get("numerator_metric_id") or "")
        denominator = str(expression.get("denominator_metric_id") or "")
        if not numerator or not denominator:
            raise GroundedPlanError("average-balance formula misses metric ids")
        return (
            "divide",
            ("metric", numerator),
            ("rolling_average_by_entity", ("metric", denominator)),
        )
    raise GroundedPlanError(f"unsupported formula expression type: {expression_type}")


def _collect_formula_operations(
    expression: Mapping[str, object],
    output: Counter[ProgramOperation],
) -> None:
    expression_type = str(expression.get("type") or "")
    if expression_type == "arithmetic":
        operation = {
            "add": ProgramOperation.ADD,
            "subtract": ProgramOperation.SUBTRACT,
            "multiply": ProgramOperation.MULTIPLY,
            "divide": ProgramOperation.DIVIDE,
        }.get(str(expression.get("operator") or ""))
        if operation is not None:
            output[operation] += 1
        for child_name in ("left", "right"):
            child = expression.get(child_name)
            if isinstance(child, Mapping):
                _collect_formula_operations(child, output)
    elif expression_type == "unary":
        if str(expression.get("operator") or "") == "absolute":
            output[ProgramOperation.ABSOLUTE] += 1
        child = expression.get("expression")
        if isinstance(child, Mapping):
            _collect_formula_operations(child, output)
    elif expression_type == "average_balance_ratio":
        output[ProgramOperation.ROLLING_AVERAGE_BY_ENTITY] += 1
        output[ProgramOperation.DIVIDE] += 1


def _reachable_program_nodes(program: GroundedProgram) -> tuple[ProgramNode, ...]:
    nodes_by_id = {node.node_id: node for node in program.nodes}
    reachable: set[str] = set()
    visiting: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in reachable:
            return
        if node_id in visiting:
            raise GroundedPlanError(f"program contains a cycle at {node_id}")
        node = nodes_by_id.get(node_id)
        if node is None:
            raise GroundedPlanError(f"program references unknown node: {node_id}")
        visiting.add(node_id)
        for input_id in node.input_ids:
            visit(input_id)
        visiting.remove(node_id)
        reachable.add(node_id)

    visit(program.output_node_id)
    return tuple(node for node in program.nodes if node.node_id in reachable)


def _attempt_payload(
    status: str,
    plan: GroundedPlan | GroundedProgram,
    facts: Sequence[GroundedFact],
    execution: GroundedExecution,
) -> dict[str, object]:
    return {
        "status": status,
        "plan": json.loads(
            json.dumps(asdict(plan), default=_json_scalar, sort_keys=True)
        ),
        "answer": execution.answer,
        "pandas_query": execution.pandas_query,
        "candidate_facts": len(facts),
        "selected_facts": [fact.to_prompt_dict() for fact in execution.facts],
    }


def _json_scalar(value: object) -> object:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, StrEnum):
        return value.value
    raise TypeError(f"cannot serialize {type(value).__name__}")


def _strings(value: object) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise GroundedV5BuildError("expected a sequence of strings")
    return [str(item) for item in value]
