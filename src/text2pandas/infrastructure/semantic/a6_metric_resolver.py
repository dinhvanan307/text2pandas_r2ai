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
    OperationKind,
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
_DEFAULT_CONFIG = _REPO_ROOT / "configs/semantic/metric_resolution_v2.yaml"
_TOKEN = re.compile(r"[a-z0-9]+")
_NOTE_SUFFIX = re.compile(r"\s*\((?:thuyet minh\s*)?\d+[a-z]?\)\s*$")
_NORMALIZED_NOTE_SUFFIX = re.compile(r"\s+thuyet minh\s+\d+[a-z]?$")

# These tokens describe the requested aggregation/shape, not the leaf metric.
# They are ignored only when scoring how completely one source label explains
# the local metric phrase; they remain in the retained question surface for
# retrieval provenance.
_METRIC_PHRASE_NOISE = frozenset(
    {
        "cac",
        "tieu",
        "gia",
        "tri",
        "khoan",
        "muc",
        "so",
        "du",
        "tong",
    }
)
_LEFT_PHRASE_BOUNDARIES = frozenset(
    {
        "bao",
        "chenh",
        "co",
        "cong",
        "cp",
        "ctcp",
        "cua",
        "do",
        "giua",
        "ghi",
        "hang",
        "la",
        "lech",
        "ngan",
        "nhieu",
        "nam",
        "nao",
        "nhan",
        "tai",
        "tap",
        "tmcp",
        "tong",
        "tren",
        "tinh",
        "trung",
        "trong",
        "ty",
        "ve",
    }
)
_RIGHT_PHRASE_BOUNDARIES = frozenset(
    {
        "bao",
        "cong",
        "ctcp",
        "cao",
        "cuoi",
        "dau",
        "den",
        "giua",
        "khi",
        "ky",
        "la",
        "ma",
        "nam",
        "ngay",
        "nhat",
        "nho",
        "so",
        "tai",
        "tap",
        "theo",
        "tmcp",
        "tong",
        "tren",
        "trong",
        "tu",
        "vao",
        "voi",
        "lon",
        "thap",
    }
)
_CORPORATE_PREFIX_TOKENS = frozenset(
    {
        "co",
        "cong",
        "ctcp",
        "doan",
        "hang",
        "ngan",
        "phan",
        "tap",
        "tmcp",
        "tong",
        "ty",
    }
)


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
    blocked_scope_tokens: frozenset[str]
    exclude_entity_tokens_from_scoring: bool
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
        question_tokens, normalized_question, entity_spans = self._question_tokens(
            question, annotations.entities
        )
        hypotheses = self._hypotheses(
            rows,
            question_tokens,
            normalized_question,
            entity_spans,
            annotations,
        )
        if not hypotheses:
            expected_dimension = _source_metric_dimension(annotations)
            compatible_units = {
                row.unit_kind
                for row in rows
                if _dimension_compatible(
                    expected_dimension,
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
                tuple(-part for part in value.score),
                -(value.mention.end - value.mention.start),
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

    def _question_tokens(
        self,
        question: str,
        entities: Sequence[str],
    ) -> tuple[list[_Token], str, tuple[tuple[int, int], ...]]:
        normalized = normalize_phrase(question)
        blocked_spans: list[tuple[int, int]] = []
        scoring_spans: list[tuple[int, int]] = []
        for entity in entities:
            entity_phrases = [normalize_phrase(entity)]
            raw = self.entity_aliases.get(entity, ())
            values = (raw,) if isinstance(raw, str) else raw
            for value in values:
                entity_phrases.extend(_entity_phrase_variants(str(value)))
            entity_spans = [
                match.span()
                for phrase in entity_phrases
                if phrase
                for match in re.finditer(
                    rf"(?<![a-z0-9]){re.escape(phrase)}(?![a-z0-9])",
                    normalized,
                )
            ]
            blocked_spans.extend(entity_spans)
            ticker = normalize_phrase(entity)
            ticker_spans = [
                match.span()
                for match in re.finditer(
                    rf"(?<![a-z0-9]){re.escape(ticker)}(?![a-z0-9])",
                    normalized,
                )
            ]
            if ticker_spans:
                scoring_spans.extend(ticker_spans)
            elif entity_spans:
                longest = max(end - start for start, end in entity_spans)
                scoring_spans.extend(
                    (start, end)
                    for start, end in entity_spans
                    if end - start == longest
                )
        tokens = [
            _Token(match.group(0), match.start(), match.end())
            for match in _TOKEN.finditer(normalized)
            if not re.fullmatch(r"(?:19|20)\d{2}", match.group(0))
            and not any(
                match.start() >= start and match.end() <= end for start, end in blocked_spans
            )
        ]
        return (
            _apply_token_rules(tokens, self.config.rules),
            normalized,
            tuple(sorted(set(scoring_spans))),
        )

    def _hypotheses(
        self,
        rows: Sequence[_SourceRow],
        question_tokens: list[_Token],
        normalized_question: str,
        entity_spans: tuple[tuple[int, int], ...],
        annotations: QuestionAnnotations,
    ) -> list[MetricHypothesis]:
        groups: dict[tuple[str, Dimension], _Group] = {}
        expected_dimension = _source_metric_dimension(annotations)
        for row in rows:
            dimension = _dimension(row.unit_kind)
            if not _dimension_compatible(expected_dimension, dimension):
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
        scoring_question = (
            _mask_spans(normalized_question, entity_spans)
            if self.config.exclude_entity_tokens_from_scoring
            else normalized_question
        )
        for group in groups.values():
            if _context_free_person_name(group):
                continue
            best: tuple[int, int, int, int, int, int, int, int, str] | None = None
            # Discovery is label-led. Hierarchy is retained as binding evidence
            # but cannot make an unrelated leaf inherit its parent's meaning.
            for surface in sorted(group.labels):
                source_values = _source_tokens(surface, self.config.rules)
                match = _longest_common_run(
                    question_tokens,
                    source_values,
                    normalized_question,
                )
                if match is None:
                    continue
                run, question_start, question_end = match
                first = question_tokens[question_start]
                last = question_tokens[question_end - 1]
                phrase_start, phrase_end = _metric_phrase_span(
                    normalized_question, first.start, last.end
                )
                phrase = normalized_question[phrase_start:phrase_end]
                scoring_phrase = scoring_question[phrase_start:phrase_end]
                phrase_values = _semantic_metric_tokens(scoring_phrase)
                source_semantic_values = _semantic_metric_tokens(" ".join(source_values))
                short_exact_label = (
                    0 < len(source_semantic_values) <= 2
                    and source_semantic_values == phrase_values
                    and normalize_fact_label(surface) == normalize_fact_label(scoring_phrase)
                )
                if _introduces_unrequested_accounting_qualifier(
                    frozenset(source_values),
                    frozenset(_TOKEN.findall(phrase)),
                ):
                    continue
                if (
                    len(source_semantic_values - phrase_values) >= 2
                    and len(phrase_values - source_semantic_values) >= 2
                ):
                    # A broad shared head (e.g. ``tiền gửi tại ngân hàng``)
                    # cannot reconcile mutually exclusive geographic/product
                    # qualifiers on the two noun phrases.
                    continue
                context_values = set(source_semantic_values)
                for path in group.row_paths:
                    for segment in fact_label_segments(path)[-2:]:
                        context_values.update(_semantic_metric_tokens(segment))
                overlap = len(phrase_values.intersection(source_semantic_values))
                evidence_overlap = len(
                    frozenset(_TOKEN.findall(scoring_phrase)).intersection(source_values)
                )
                context_overlap = len(phrase_values.intersection(context_values))
                query_coverage = round(1000 * context_overlap / max(1, len(phrase_values)))
                source_coverage = round(1000 * overlap / max(1, len(source_semantic_values)))
                method = (
                    "a6_scoped_contiguous_ngram"
                    if run >= self.config.min_contiguous_tokens
                    else "a6_scoped_metric_token_set"
                )
                candidate = (
                    int(short_exact_label),
                    query_coverage,
                    source_coverage,
                    overlap,
                    run,
                    evidence_overlap,
                    phrase_start,
                    phrase_end,
                    method,
                )
                if best is None or candidate[:6] > best[:6]:
                    best = candidate
            if best is None:
                continue
            (
                short_exact_score,
                query_coverage,
                source_coverage,
                overlap,
                run,
                evidence_overlap,
                phrase_start,
                phrase_end,
                match_method,
            ) = best
            ordered_match = run >= self.config.min_contiguous_tokens
            complete_token_set_match = (
                query_coverage >= 600
                and source_coverage >= 800
                and evidence_overlap >= self.config.min_token_overlap
            )
            if not ordered_match and not complete_token_set_match and not short_exact_score:
                continue
            if (
                evidence_overlap < self.config.min_token_overlap
                and not short_exact_score
            ) or (
                source_coverage < self.config.min_source_coverage_milli
            ):
                continue
            surface = normalized_question[phrase_start:phrase_end]
            scoring_surface = scoring_question[phrase_start:phrase_end]
            surface_tokens = frozenset(
                match.group(0) for match in _TOKEN.finditer(scoring_surface)
            )
            if surface_tokens and surface_tokens <= self.config.blocked_scope_tokens:
                continue
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
                        phrase_start,
                        phrase_end,
                        surface,
                        normalize_phrase(surface),
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
                    match_method=match_method,
                    score=(query_coverage, source_coverage, overlap),
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
        blocked_scope_tokens=frozenset(
            normalize_phrase(str(value))
            for value in matching.get("blocked_scope_tokens", ())
            if normalize_phrase(str(value))
        ),
        exclude_entity_tokens_from_scoring=bool(
            matching.get("exclude_entity_tokens_from_scoring", False)
        ),
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


def _entity_phrase_variants(value: str) -> tuple[str, ...]:
    """Return safe full/suffix variants for blocking one annotated entity.

    Questions often elide a shared legal prefix, e.g. ``các ngân hàng ...,
    TMCP Sài Gòn Thương Tín``. Exact full-name blocking misses that suffix and
    lets a subsidiary row with the same proper name masquerade as a metric.
    Only suffixes with at least three non-corporate tokens are admitted.
    """

    normalized = normalize_phrase(value)
    tokens = normalized.split()
    variants = [normalized] if normalized else []
    if tokens[:1] == ["ctcp"]:
        remainder = " ".join(tokens[1:])
        variants.extend(
            (
                f"cong ty cp {remainder}",
                f"cong ty co phan {remainder}",
            )
        )
    if tokens[:2] == ["ngan", "hang"] and "tmcp" in tokens[:4]:
        suffix_index = tokens.index("tmcp") + 1
        remainder = " ".join(tokens[suffix_index:])
        variants.append(f"ngan hang thuong mai co phan {remainder}")
    first_semantic = 0
    while first_semantic < len(tokens) and tokens[first_semantic] in _CORPORATE_PREFIX_TOKENS:
        first_semantic += 1
    suffix = tokens[first_semantic:]
    if len(suffix) >= 3:
        variants.append(" ".join(suffix))
    return tuple(dict.fromkeys(variants))


def _metric_phrase_span(normalized_question: str, start: int, end: int) -> tuple[int, int]:
    """Expand an evidence run to its local noun phrase, bounded by grammar."""

    tokens = [
        _Token(match.group(0), match.start(), match.end())
        for match in _TOKEN.finditer(normalized_question)
    ]
    if not tokens:
        return start, end
    first_index = next(
        (index for index, token in enumerate(tokens) if token.end > start),
        0,
    )
    last_index = next(
        (index for index in range(len(tokens) - 1, -1, -1) if tokens[index].start < end),
        first_index,
    )
    left = first_index
    for index in range(first_index - 1, max(-1, first_index - 9), -1):
        if tokens[index].value in _LEFT_PHRASE_BOUNDARIES or re.fullmatch(
            r"(?:19|20)\d{2}", tokens[index].value
        ):
            break
        left = index
    right = last_index
    for index in range(last_index + 1, min(len(tokens), last_index + 7)):
        value = tokens[index].value
        current_values = {token.value for token in tokens[left : right + 1]}
        if (
            value == "trong"
            and index + 1 < len(tokens)
            and tokens[index + 1].value == "nam"
            and {"khau", "hao"} <= current_values
        ):
            right = index
            continue
        if value == "nam" and tokens[right].value == "trong":
            right = index
            continue
        if value == "nam" and tokens[right].value == "viet":
            right = index
            continue
        if value == "cua":
            if tokens[right].value == "nha":
                right = index
                continue
            break
        if value in _RIGHT_PHRASE_BOUNDARIES or re.fullmatch(r"(?:19|20)\d{2}", value):
            break
        right = index
    return tokens[left].start, tokens[right].end


def _mask_spans(value: str, spans: Sequence[tuple[int, int]]) -> str:
    """Blank annotated entity spans without changing character offsets."""

    characters = list(value)
    for start, end in spans:
        characters[start:end] = " " * (end - start)
    return "".join(characters)


def _semantic_metric_tokens(value: str) -> frozenset[str]:
    tokens = frozenset(
        token
        for token in _TOKEN.findall(normalize_phrase(value))
        if token not in _METRIC_PHRASE_NOISE
    )
    if "usd" in tokens:
        tokens = tokens.difference({"do", "la", "my"})
    if "vnd" in tokens and "dong" in tokens:
        tokens = tokens.difference({"dong", "viet", "nam"})
    if {"khau", "hao"} <= tokens:
        tokens = tokens.difference({"chi", "phi"})
    return tokens


def _longest_common_run(
    question: Sequence[_Token],
    source: Sequence[str],
    normalized_question: str,
) -> tuple[int, int, int] | None:
    best: tuple[int, int, int] | None = None
    for question_index in range(len(question)):
        for source_index in range(len(source)):
            length = 0
            while (
                question_index + length < len(question)
                and source_index + length < len(source)
                and question[question_index + length].value == source[source_index + length]
            ):
                if length:
                    previous = question[question_index + length - 1]
                    current = question[question_index + length]
                    if current.start != previous.start and _TOKEN.search(
                        normalized_question[previous.end : current.start]
                    ):
                        break
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


_DISTINCTIVE_ACCOUNTING_QUALIFIERS = (
    frozenset({"thang", "du"}),
    frozenset({"ngan", "han"}),
    frozenset({"dai", "han"}),
    frozenset({"hien", "hanh"}),
    frozenset({"hoan", "lai"}),
    frozenset({"cu", "the"}),
    frozenset({"khong", "kiem", "soat"}),
)


def _introduces_unrequested_accounting_qualifier(
    source: frozenset[str], query: frozenset[str]
) -> bool:
    """Protect accounting identities whose qualifier changes the metric."""

    return any(
        qualifier <= source and not qualifier <= query
        for qualifier in _DISTINCTIVE_ACCOUNTING_QUALIFIERS
    )


def _semantic_key(label: str) -> str:
    normalized = _NOTE_SUFFIX.sub("", normalize_fact_label(label))
    normalized = _NORMALIZED_NOTE_SUFFIX.sub("", normalized)
    # A token multiset unifies source labels whose qualifiers were reordered
    # across report years. Joining without separators also preserves the prior
    # tolerance for OCR word-boundary loss (``lien quan`` vs ``lienquan``).
    tokens = list(_TOKEN.findall(normalized))
    # Vietnamese reports alternate between the legal and abbreviated name of
    # the same central-bank balance-sheet line.  Geography is not a product
    # qualifier in this institution name, so both labels share one identity.
    if {"ngan", "hang", "nha", "nuoc", "viet", "nam"} <= set(tokens):
        tokens.remove("viet")
        tokens.remove("nam")
    return "".join(sorted(tokens))


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


def _source_metric_dimension(annotations: QuestionAnnotations) -> Dimension:
    """Return the leaf dimension, which can differ from the answer dimension."""

    if annotations.operation in {
        OperationKind.GROWTH,
        OperationKind.COUNT,
        OperationKind.EXTREMUM,
    }:
        return Dimension.UNKNOWN
    return annotations.requested_unit.dimension


def _basis(value: str) -> Basis:
    try:
        return Basis(value)
    except ValueError:
        return Basis.UNSPECIFIED
