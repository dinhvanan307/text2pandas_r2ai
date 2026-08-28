"""Deterministic, scoped source-label fallback for Semantic V3 metric mentions."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from text2pandas.application.parsing import (
    MetricHypothesis,
    MetricResolutionResult,
    QuestionAnnotations,
    QuestionMetricMention,
)
from text2pandas.domain.metrics import normalize_phrase
from text2pandas.domain.semantic import Basis, Dimension, PeriodSemantics, UnitSpec
from text2pandas.infrastructure.checksums import sha256_file
from text2pandas.infrastructure.retrieval.fact_label import (
    fact_label_segments,
    normalize_fact_label,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
_DEFAULT_CONFIG = _REPO_ROOT / "configs/semantic/metric_resolution_v1.yaml"
_TOKEN = re.compile(r"[a-z0-9]+")
_NOTE_SUFFIX = re.compile(r"\s*\((?:thuyet minh\s*)?\d+[a-z]?\)\s*$")
_NORMALIZED_NOTE_SUFFIX = re.compile(r"\s+thuyet minh\s+\d+[a-z]?$")


@dataclass(frozen=True, slots=True)
class _Token:
    value: str
    start: int
    end: int


@dataclass(frozen=True, slots=True)
class _Rule:
    rule_id: str
    phrase: tuple[str, ...]
    replacement: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _Config:
    resolver_id: str
    source_build_id: str
    min_contiguous_tokens: int
    min_token_overlap: int
    min_source_coverage_milli: int
    max_hypotheses: int
    require_unique_winner_per_span: bool
    rules: tuple[_Rule, ...]
    sha256: str


@dataclass(frozen=True, slots=True)
class _SourceRow:
    label: str
    row_path: str
    metric_code: str | None
    unit_kind: str
    statement_type: str
    basis: Basis
    support: int


@dataclass(slots=True)
class _Group:
    semantic_key: str
    dimension: Dimension
    labels: set[str]
    row_paths: set[str]
    metric_codes: set[str]
    statement_types: set[str]
    bases: set[Basis]
    support: int = 0


class A6MetricMentionResolver:
    """Resolve only strict source-label evidence inside the annotated scope."""

    def __init__(
        self,
        connection: sqlite3.Connection,
        *,
        source_build_id: str,
        entity_aliases: Mapping[str, str | Sequence[str]] | None = None,
        config_path: str | Path = _DEFAULT_CONFIG,
    ):
        self.connection = connection
        self.config = _load_config(Path(config_path))
        if source_build_id != self.config.source_build_id:
            raise ValueError(
                "metric resolver source build mismatch: "
                f"config={self.config.source_build_id} active={source_build_id}"
            )
        self.source_build_id = source_build_id
        self.entity_aliases = entity_aliases or {}
        self._scope_cache: dict[
            tuple[tuple[str, ...], tuple[str, ...], str], tuple[_SourceRow, ...]
        ] = {}
        self.lookup_count = 0
        self.cache_hits = 0
        self.resolve_seconds = 0.0
        self.db_lookup_seconds = 0.0

    @property
    def fingerprint(self) -> str:
        payload = {
            "resolver_id": self.config.resolver_id,
            "config_sha256": self.config.sha256,
            "source_build_id": self.source_build_id,
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def metadata(self) -> dict[str, object]:
        return {
            "resolver_id": self.config.resolver_id,
            "fingerprint": self.fingerprint,
            "config_sha256": self.config.sha256,
            "source_build_id": self.source_build_id,
            "lookup_count": self.lookup_count,
            "cache_hits": self.cache_hits,
            "cache_misses": self.lookup_count,
            "resolve_seconds": round(self.resolve_seconds, 6),
            "db_lookup_seconds": round(self.db_lookup_seconds, 6),
        }

    def resolve(self, question: str, annotations: QuestionAnnotations) -> MetricResolutionResult:
        started = time.perf_counter()
        try:
            return self._resolve(question, annotations)
        finally:
            self.resolve_seconds += time.perf_counter() - started

    def _resolve(self, question: str, annotations: QuestionAnnotations) -> MetricResolutionResult:
        if not annotations.entities and annotations.mode != "screen_open":
            return MetricResolutionResult("ABSTAIN", reason="ENTITY_SCOPE_UNAVAILABLE")
        rows = self._source_rows(annotations)
        question_tokens, normalized_question = self._question_tokens(question, annotations.entities)
        hypotheses = self._hypotheses(rows, question_tokens, normalized_question, annotations)
        if not hypotheses:
            compatible_units = {
                row.unit_kind
                for row in rows
                if _dimension_compatible(
                    annotations.requested_unit.dimension,
                    _dimension(row.unit_kind),
                )
            }
            reason = (
                "METRIC_SOURCE_SPECIFICITY_REQUIRED"
                if annotations.requested_unit.is_known and len(compatible_units) == 1
                else "QUESTION_MENTION_NO_MAPPING"
            )
            return MetricResolutionResult(
                "ABSTAIN",
                reason=reason,
                trace=(self._trace((), (), reason),),
            )

        by_span: dict[tuple[int, int], list[MetricHypothesis]] = {}
        for hypothesis in hypotheses:
            key = (hypothesis.mention.start, hypothesis.mention.end)
            by_span.setdefault(key, []).append(hypothesis)
        winners: list[MetricHypothesis] = []
        ambiguous_spans: list[tuple[int, int]] = []
        for span, values in sorted(by_span.items()):
            ordered = sorted(
                values,
                key=lambda value: (
                    value.score,
                    value.supporting_observations,
                    value.source_metric_id,
                ),
                reverse=True,
            )
            best_score = ordered[0].score
            tied = [value for value in ordered if value.score == best_score]
            if self.config.require_unique_winner_per_span and len(tied) != 1:
                ambiguous_spans.append(span)
                continue
            winners.append(ordered[0])

        selected: list[MetricHypothesis] = []
        for hypothesis in sorted(
            winners,
            key=lambda value: (
                -(value.mention.end - value.mention.start),
                tuple(-part for part in value.score),
                value.mention.start,
                value.source_metric_id,
            ),
        ):
            if any(
                hypothesis.mention.start < other.mention.end
                and other.mention.start < hypothesis.mention.end
                for other in selected
            ):
                continue
            selected.append(hypothesis)
        selected.sort(key=lambda value: (value.mention.start, value.mention.end))
        unsafe_ambiguous_spans = [
            span
            for span in ambiguous_spans
            if not any(
                _spans_belong_to_same_phrase(
                    span,
                    (value.mention.start, value.mention.end),
                )
                for value in selected
            )
        ]
        if unsafe_ambiguous_spans:
            reason = "METRIC_HYPOTHESES_AMBIGUOUS"
            return MetricResolutionResult(
                "ABSTAIN",
                selected=tuple(selected),
                hypotheses=tuple(hypotheses[: self.config.max_hypotheses]),
                reason=reason,
                trace=(self._trace(selected, unsafe_ambiguous_spans, reason),),
            )
        if not selected:
            reason = "QUESTION_MENTION_NO_MAPPING"
            return MetricResolutionResult(
                "ABSTAIN",
                hypotheses=tuple(hypotheses[: self.config.max_hypotheses]),
                reason=reason,
                trace=(self._trace((), ambiguous_spans, reason),),
            )
        return MetricResolutionResult(
            "RESOLVED",
            selected=tuple(selected),
            hypotheses=tuple(hypotheses[: self.config.max_hypotheses]),
            trace=(self._trace(selected, ambiguous_spans, None),),
        )

    def _trace(
        self,
        selected: Sequence[MetricHypothesis],
        ambiguous_spans: Sequence[tuple[int, int]],
        reason: str | None,
    ) -> dict[str, object]:
        return {
            "stage": "SOURCE_METRIC_RESOLUTION",
            "resolver_fingerprint": self.fingerprint,
            "selected": [value.to_dict() for value in selected],
            "ambiguous_spans": [list(value) for value in ambiguous_spans],
            "reason": reason,
        }

    def _source_rows(self, annotations: QuestionAnnotations) -> tuple[_SourceRow, ...]:
        key = (
            tuple(annotations.entities),
            tuple(annotations.periods),
            annotations.basis.value,
        )
        cached = self._scope_cache.get(key)
        if cached is not None:
            self.cache_hits += 1
            return cached
        clauses = [
            "r.execution_ready = 1",
            "o.value_decimal_text IS NOT NULL",
            "o.metric_label_clean IS NOT NULL",
        ]
        parameters: list[object] = []
        if annotations.entities:
            clauses.append(f"o.ticker IN ({','.join('?' for _ in annotations.entities)})")
            parameters.extend(annotations.entities)
        if annotations.periods:
            clauses.append(
                f"substr(o.period_end, 1, 4) IN ({','.join('?' for _ in annotations.periods)})"
            )
            parameters.extend(annotations.periods)
        if annotations.basis != Basis.UNSPECIFIED:
            clauses.append("d.basis = ?")
            parameters.append(annotations.basis.value)
        started = time.perf_counter()
        try:
            result = tuple(
                _SourceRow(
                    label=str(row[0]),
                    row_path=str(row[1] or row[0]),
                    metric_code=None if row[2] in (None, "") else str(row[2]),
                    unit_kind=str(row[3]),
                    statement_type=str(row[4]),
                    basis=_basis(str(row[5])),
                    support=int(row[6]),
                )
                for row in self.connection.execute(
                    f"""
                    SELECT o.metric_label_clean, o.row_path_text, o.metric_code,
                           o.unit_kind, o.statement_type, d.basis, COUNT(*)
                    FROM observations o
                    JOIN observation_readiness r USING(observation_uid)
                    JOIN tables t USING(table_uid)
                    JOIN documents d USING(document_uid)
                    WHERE {" AND ".join(clauses)}
                    GROUP BY o.metric_label_clean, o.row_path_text, o.metric_code,
                             o.unit_kind, o.statement_type, d.basis
                    ORDER BY o.metric_label_clean, o.row_path_text, o.metric_code,
                             o.unit_kind, o.statement_type, d.basis
                    """,
                    tuple(parameters),
                )
            )
        finally:
            self.db_lookup_seconds += time.perf_counter() - started
        self.lookup_count += 1
        self._scope_cache[key] = result
        return result

    def _question_tokens(self, question: str, entities: Sequence[str]) -> tuple[list[_Token], str]:
        normalized = normalize_phrase(question)
        blocked_phrases = [normalize_phrase(entity) for entity in entities]
        for entity in entities:
            raw = self.entity_aliases.get(entity, ())
            values = (raw,) if isinstance(raw, str) else raw
            blocked_phrases.extend(normalize_phrase(str(value)) for value in values)
        blocked_spans = [
            match.span()
            for phrase in blocked_phrases
            if phrase
            for match in re.finditer(rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])", normalized)
        ]
        tokens = [
            _Token(match.group(0), match.start(), match.end())
            for match in _TOKEN.finditer(normalized)
            if not re.fullmatch(r"(?:19|20)\d{2}", match.group(0))
            and not any(
                match.start() >= start and match.end() <= end for start, end in blocked_spans
            )
        ]
        return _apply_token_rules(tokens, self.config.rules), normalized

    def _hypotheses(
        self,
        rows: Sequence[_SourceRow],
        question_tokens: list[_Token],
        normalized_question: str,
        annotations: QuestionAnnotations,
    ) -> list[MetricHypothesis]:
        groups: dict[tuple[str, Dimension], _Group] = {}
        for row in rows:
            dimension = _dimension(row.unit_kind)
            if not _dimension_compatible(annotations.requested_unit.dimension, dimension):
                continue
            semantic_key = _semantic_key(row.label)
            group = groups.setdefault(
                (semantic_key, dimension),
                _Group(semantic_key, dimension, set(), set(), set(), set(), set()),
            )
            group.labels.add(row.label)
            group.row_paths.add(row.row_path)
            if row.metric_code:
                group.metric_codes.add(row.metric_code)
            group.statement_types.add(row.statement_type)
            group.bases.add(row.basis)
            group.support += row.support

        hypotheses: list[MetricHypothesis] = []
        question_values = [value.value for value in question_tokens]
        for group in groups.values():
            if _context_free_person_name(group):
                continue
            best: tuple[int, int, int, int, int] | None = None
            # Discovery is label-led. Hierarchy is retained as binding evidence
            # but cannot make an unrelated leaf inherit its parent's meaning.
            for surface in sorted(group.labels):
                source_values = _source_tokens(surface, self.config.rules)
                match = _longest_common_run(question_values, source_values)
                if match is None:
                    continue
                run, question_start, question_end = match
                overlap = len(set(question_values).intersection(source_values))
                coverage = round(1000 * overlap / max(1, len(set(source_values))))
                candidate = (run, coverage, overlap, question_start, question_end)
                if best is None or candidate[:3] > best[:3]:
                    best = candidate
            if best is None:
                continue
            run, coverage, overlap, token_start, token_end = best
            if (
                run < self.config.min_contiguous_tokens
                or overlap < self.config.min_token_overlap
                or coverage < self.config.min_source_coverage_milli
            ):
                continue
            first = question_tokens[token_start]
            last = question_tokens[token_end - 1]
            surface = normalized_question[first.start : last.end]
            source_id = _source_id(self.source_build_id, group.semantic_key, group.dimension)
            preferred_basis: Basis
            if annotations.basis != Basis.UNSPECIFIED:
                preferred_basis = annotations.basis
            elif Basis.CONSOLIDATED in group.bases:
                preferred_basis = Basis.CONSOLIDATED
            else:
                preferred_basis = min(group.bases, key=lambda value: value.value)
            hypotheses.append(
                MetricHypothesis(
                    mention=QuestionMetricMention(
                        first.start, last.end, surface, normalize_phrase(surface)
                    ),
                    source_metric_id=source_id,
                    source_build_id=self.source_build_id,
                    aliases=tuple(sorted(group.labels)),
                    metric_codes=tuple(sorted(group.metric_codes)),
                    row_paths=tuple(sorted(group.row_paths))[:32],
                    statement_types=tuple(sorted(group.statement_types)),
                    unit=UnitSpec(group.dimension),
                    period_semantics=PeriodSemantics.UNKNOWN,
                    preferred_basis=preferred_basis,
                    match_method="a6_scoped_contiguous_ngram",
                    score=(run, coverage, overlap),
                    supporting_observations=group.support,
                )
            )
        hypotheses.sort(
            key=lambda value: (
                tuple(-part for part in value.score),
                value.mention.start,
                value.source_metric_id,
            )
        )
        return hypotheses


def _load_config(path: Path) -> _Config:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or int(raw.get("schema_version", 0)) != 1:
        raise ValueError("metric resolution config schema_version must equal 1")
    source = _mapping(raw.get("source"), "source")
    matching = _mapping(raw.get("matching"), "matching")
    rules: list[_Rule] = []
    for value in raw.get("abbreviation_rules", ()):
        rule = _mapping(value, "abbreviation rule")
        evidence = tuple(int(qid) for qid in rule.get("evidence_qids", ()))
        negatives = tuple(str(item) for item in rule.get("negative_examples", ()))
        if not evidence or not negatives:
            raise ValueError("abbreviation rules require evidence_qids and negative_examples")
        phrase = tuple(normalize_phrase(str(rule["phrase"])).split())
        replacement = tuple(normalize_phrase(str(rule["replacement"])).split())
        if not phrase or not replacement:
            raise ValueError("abbreviation rule phrase and replacement must be non-empty")
        rules.append(_Rule(str(rule["rule_id"]), phrase, replacement))
    return _Config(
        resolver_id=str(raw["resolver_id"]),
        source_build_id=str(source["a6_build_id"]),
        min_contiguous_tokens=int(matching["min_contiguous_tokens"]),
        min_token_overlap=int(matching["min_token_overlap"]),
        min_source_coverage_milli=int(matching["min_source_coverage_milli"]),
        max_hypotheses=int(matching["max_hypotheses"]),
        require_unique_winner_per_span=bool(matching.get("require_unique_winner_per_span", True)),
        rules=tuple(rules),
        sha256=sha256_file(path),
    )


def _mapping(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{label} must be a mapping")
    return value


def _apply_token_rules(tokens: list[_Token], rules: Sequence[_Rule]) -> list[_Token]:
    output = tokens
    for rule in rules:
        replaced: list[_Token] = []
        index = 0
        while index < len(output):
            values = tuple(value.value for value in output[index : index + len(rule.phrase)])
            if values == rule.phrase:
                start = output[index].start
                end = output[index + len(rule.phrase) - 1].end
                replaced.extend(_Token(value, start, end) for value in rule.replacement)
                index += len(rule.phrase)
            else:
                replaced.append(output[index])
                index += 1
        output = replaced
    return output


def _source_tokens(value: str, rules: Sequence[_Rule]) -> list[str]:
    normalized = normalize_fact_label(value)
    tokens = [
        _Token(match.group(0), match.start(), match.end()) for match in _TOKEN.finditer(normalized)
    ]
    return [token.value for token in _apply_token_rules(tokens, rules)]


def _longest_common_run(
    question: Sequence[str], source: Sequence[str]
) -> tuple[int, int, int] | None:
    best: tuple[int, int, int] | None = None
    for question_index in range(len(question)):
        for source_index in range(len(source)):
            length = 0
            while (
                question_index + length < len(question)
                and source_index + length < len(source)
                and question[question_index + length] == source[source_index + length]
            ):
                length += 1
            candidate = (length, question_index, question_index + length)
            if length and (best is None or candidate[0] > best[0]):
                best = candidate
    return best


def _spans_belong_to_same_phrase(left: tuple[int, int], right: tuple[int, int]) -> bool:
    if left[0] < right[1] and right[0] < left[1]:
        return True
    gap = max(left[0], right[0]) - min(left[1], right[1])
    return 0 <= gap <= 12


def _semantic_key(label: str) -> str:
    normalized = _NOTE_SUFFIX.sub("", normalize_fact_label(label))
    normalized = _NORMALIZED_NOTE_SUFFIX.sub("", normalized)
    # Source identity tolerates OCR word-boundary loss while retaining labels
    # and paths verbatim as binding evidence.
    return normalized.replace(" ", "")


def _context_free_person_name(group: _Group) -> bool:
    """Reject a bare proper-name leaf when A6 carries no semantic hierarchy."""

    if group.metric_codes or any(len(fact_label_segments(path)) > 1 for path in group.row_paths):
        return False
    for label in group.labels:
        words = [value for value in re.findall(r"[^\W\d_]+", label, flags=re.UNICODE)]
        if not (2 <= len(words) <= 5):
            return False
        if not all(word[0].isupper() and word[1:] == word[1:].lower() for word in words):
            return False
    return True


def _source_id(source_build_id: str, semantic_key: str, dimension: Dimension) -> str:
    payload = f"{source_build_id}\0{semantic_key}\0{dimension.value}"
    return "source_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _dimension(unit_kind: str) -> Dimension:
    return {
        "money": Dimension.MONEY,
        "percent": Dimension.PERCENT,
        "rate": Dimension.RATIO,
        "shares": Dimension.SHARES,
    }.get(unit_kind, Dimension.UNKNOWN)


def _dimension_compatible(expected: Dimension, actual: Dimension) -> bool:
    if expected == Dimension.UNKNOWN:
        return actual != Dimension.UNKNOWN
    if {expected, actual} <= {Dimension.RATIO, Dimension.PERCENT}:
        return True
    return expected == actual


def _basis(value: str) -> Basis:
    try:
        return Basis(value)
    except ValueError:
        return Basis.UNSPECIFIED
