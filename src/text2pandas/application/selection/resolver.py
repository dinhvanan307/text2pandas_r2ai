"""Fail-closed reviewed metric resolver for Canonical V2 P0."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass

from text2pandas.application.parsing import (
    MetricHypothesis,
    MetricMentionResolver,
    QuestionAnnotations,
)
from text2pandas.domain.metrics import MetricOntology, MetricSpec, normalize_phrase
from text2pandas.domain.semantic import Dimension

from .contracts import MetricResolution, ResolvedMetricMention

_WORD = r"a-z0-9"


@dataclass(frozen=True, slots=True)
class MetricResolverPolicy:
    policy_id: str
    exact_confidence: float
    normalized_confidence: float
    source_confidence: float
    ambiguous_phrases: tuple[str, ...]
    supported_operations: tuple[str, ...]
    config_sha256: str

    @property
    def fingerprint(self) -> str:
        payload = {
            "policy_id": self.policy_id,
            "exact_confidence": self.exact_confidence,
            "normalized_confidence": self.normalized_confidence,
            "source_confidence": self.source_confidence,
            "ambiguous_phrases": list(self.ambiguous_phrases),
            "supported_operations": list(self.supported_operations),
            "config_sha256": self.config_sha256,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ReviewedMetricResolver:
    """Resolve question-only aliases, then adapt scoped A6 source evidence.

    The A6 adapter may enrich labels and metric codes, but it cannot promote a
    metric outside the 28 reviewed ontology entries.
    """

    def __init__(
        self,
        ontology: MetricOntology,
        policy: MetricResolverPolicy,
        source_fallback: MetricMentionResolver | None = None,
    ):
        self.ontology = ontology
        self.policy = policy
        self.source_fallback = source_fallback
        self.reviewed = tuple(
            sorted(
                (
                    metric
                    for metric in ontology.metrics.values()
                    if metric.review_status == "reviewed"
                ),
                key=lambda metric: metric.metric_id,
            )
        )
        if len(self.reviewed) != 28:
            raise ValueError(f"P0 requires exactly 28 reviewed metrics, found {len(self.reviewed)}")

    @property
    def fingerprint(self) -> str:
        payload = {
            "ontology": self.ontology.fingerprint,
            "policy": self.policy.fingerprint,
            "source_fallback": (
                self.source_fallback.fingerprint if self.source_fallback is not None else None
            ),
        }
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    def resolve(self, question: str, annotations: QuestionAnnotations) -> MetricResolution:
        normalized, offsets = _normalize_with_offsets(question)
        exact, rejected = self._reviewed_mentions(question, normalized, offsets)
        if exact:
            return self._finalize_exact(exact, rejected, annotations)
        if rejected:
            return self._result(
                "UNRESOLVED",
                reason="FORBIDDEN_QUALIFIER",
                method="REVIEWED_ALIAS_REJECTED",
                trace=(
                    {"stage": "P0_METRIC_RESOLUTION", "rejected": rejected},
                ),
            )
        ambiguous_cues = tuple(
            phrase
            for phrase in self.policy.ambiguous_phrases
            if _contains_phrase(normalized, phrase)
        )
        if ambiguous_cues:
            return self._result(
                "AMBIGUOUS",
                reason="GENERIC_METRIC_PHRASE",
                method="AMBIGUITY_RULE",
                trace=(
                    {
                        "stage": "P0_METRIC_RESOLUTION",
                        "ambiguous_phrases": list(ambiguous_cues),
                        "rejected": rejected,
                    },
                ),
            )
        if self.source_fallback is None:
            return self._result(
                "UNRESOLVED",
                reason="QUESTION_MENTION_NO_MAPPING",
                method="NONE",
            )
        return self._resolve_source(question, annotations)

    def _reviewed_mentions(
        self,
        question: str,
        normalized: str,
        offsets: tuple[int, ...],
    ) -> tuple[list[ResolvedMetricMention], list[dict[str, object]]]:
        raw: list[tuple[int, int, str, MetricSpec, str, float]] = []
        rejected: list[dict[str, object]] = []
        raw_casefold = unicodedata.normalize("NFC", question.casefold())
        for metric in self.reviewed:
            for alias in metric.aliases:
                for match in re.finditer(
                    rf"(?<![{_WORD}]){re.escape(alias)}(?![{_WORD}])",
                    normalized,
                ):
                    start, end = match.span()
                    original_start = offsets[start]
                    original_end = offsets[end - 1] + 1
                    surface = question[original_start:original_end]
                    context_rejection = _metric_context_rejection(metric, normalized)
                    if context_rejection is not None:
                        rejected.append(
                            {
                                "metric_id": metric.metric_id,
                                "alias": alias,
                                "reason": context_rejection,
                            }
                        )
                        continue
                    exact_raw = _contains_phrase(raw_casefold, alias)
                    raw.append(
                        (
                            start,
                            end,
                            surface,
                            metric,
                            "EXACT_ALIAS" if exact_raw else "NORMALIZED_ALIAS",
                            (
                                self.policy.exact_confidence
                                if exact_raw
                                else self.policy.normalized_confidence
                            ),
                        )
                    )
        selected: list[tuple[int, int, str, MetricSpec, str, float]] = []
        for candidate in sorted(
            raw,
            key=lambda value: (
                -(value[1] - value[0]),
                value[0],
                value[3].metric_id,
            ),
        ):
            if any(
                candidate[0] >= other[0] and candidate[1] <= other[1]
                for other in selected
            ):
                continue
            selected.append(candidate)
        mentions = [
            ResolvedMetricMention(
                start=offsets[start],
                end=offsets[end - 1] + 1,
                surface=surface,
                normalized_surface=normalized[start:end],
                candidate_metric_ids=(metric.metric_id,),
                selected_metric_id=metric.metric_id,
                match_method=method,
                confidence=confidence,
            )
            for start, end, surface, metric, method, confidence in sorted(
                selected, key=lambda value: (value[0], value[1], value[3].metric_id)
            )
        ]
        return mentions, rejected

    def _finalize_exact(
        self,
        mentions: list[ResolvedMetricMention],
        rejected: list[dict[str, object]],
        annotations: QuestionAnnotations,
    ) -> MetricResolution:
        candidates = tuple(
            sorted(
                {
                    metric_id
                    for mention in mentions
                    for metric_id in mention.candidate_metric_ids
                }
            )
        )
        if len(candidates) != 1:
            return self._result(
                "AMBIGUOUS",
                mentions=tuple(mentions),
                candidates=candidates,
                confidence=max(mention.confidence for mention in mentions),
                reason="MULTIPLE_REVIEWED_METRICS",
                method="REVIEWED_ALIAS",
                trace=(
                    {
                        "stage": "P0_METRIC_RESOLUTION",
                        "metric_ids": list(candidates),
                        "rejected": rejected,
                    },
                ),
            )
        metric = self.ontology.metrics[candidates[0]]
        method = (
            "EXACT_ALIAS"
            if all(mention.match_method == "EXACT_ALIAS" for mention in mentions)
            else "NORMALIZED_ALIAS"
        )
        eligible = self._operation_eligible(metric, annotations)
        return self._result(
            "RESOLVED",
            selected_metric_id=metric.metric_id,
            mentions=tuple(mentions),
            candidates=candidates,
            confidence=min(mention.confidence for mention in mentions),
            method=method,
            reason=None if eligible else "OPERATION_NOT_ELIGIBLE",
            operation_eligible=eligible,
            trace=(
                {
                    "stage": "P0_METRIC_RESOLUTION",
                    "metric_id": metric.metric_id,
                    "method": method,
                    "operation_eligible": eligible,
                    "rejected": rejected,
                },
            ),
        )

    def _resolve_source(
        self, question: str, annotations: QuestionAnnotations
    ) -> MetricResolution:
        assert self.source_fallback is not None
        source = self.source_fallback.resolve(question, annotations)
        if source.status != "RESOLVED":
            status = (
                "AMBIGUOUS"
                if source.reason == "METRIC_HYPOTHESES_AMBIGUOUS"
                else "UNRESOLVED"
            )
            return self._result(
                status,
                reason=source.reason or "SOURCE_LABEL_UNRESOLVED",
                method="SOURCE_LABEL",
                trace=source.trace,
            )
        mapped: list[tuple[MetricHypothesis, MetricSpec]] = []
        ambiguous_metric_ids: set[str] = set()
        for hypothesis in source.selected:
            matches = self._map_source_hypothesis(hypothesis, question)
            ambiguous_metric_ids.update(metric.metric_id for metric in matches)
            if len(matches) == 1:
                mapped.append((hypothesis, matches[0]))
        mapped_metric_ids = {metric.metric_id for _, metric in mapped}
        if len(mapped) != len(source.selected) or len(mapped_metric_ids) != 1:
            status = "AMBIGUOUS" if len(ambiguous_metric_ids) > 1 else "UNRESOLVED"
            return self._result(
                status,
                candidates=tuple(sorted(ambiguous_metric_ids)),
                reason=(
                    "SOURCE_LABEL_MAP_AMBIGUOUS"
                    if status == "AMBIGUOUS"
                    else "SOURCE_LABEL_OUTSIDE_REVIEWED_METRICS"
                ),
                method="SOURCE_LABEL",
                trace=source.trace,
            )
        metric_id = next(iter(mapped_metric_ids))
        metric = self.ontology.metrics[metric_id]
        mentions = tuple(
            ResolvedMetricMention(
                start=hypothesis.mention.start,
                end=hypothesis.mention.end,
                surface=hypothesis.mention.surface,
                normalized_surface=hypothesis.mention.normalized_surface,
                candidate_metric_ids=(metric.metric_id,),
                selected_metric_id=metric.metric_id,
                match_method="SOURCE_LABEL",
                confidence=self.policy.source_confidence,
                metric_codes=hypothesis.metric_codes,
            )
            for hypothesis, metric in mapped
        )
        eligible = self._operation_eligible(metric, annotations)
        return self._result(
            "RESOLVED",
            selected_metric_id=metric_id,
            mentions=mentions,
            candidates=(metric_id,),
            confidence=self.policy.source_confidence,
            method="SOURCE_LABEL",
            reason=None if eligible else "OPERATION_NOT_ELIGIBLE",
            operation_eligible=eligible,
            trace=source.trace,
        )

    def _map_source_hypothesis(
        self, hypothesis: MetricHypothesis, question: str
    ) -> tuple[MetricSpec, ...]:
        contexts = tuple(
            normalize_phrase(value)
            for value in (*hypothesis.aliases, *hypothesis.row_paths, question)
        )
        matches: list[MetricSpec] = []
        for metric in self.reviewed:
            if not _dimension_compatible(metric.expected_dimension, hypothesis.unit.dimension):
                continue
            if (
                metric.statement_types
                and hypothesis.statement_types
                and not set(metric.statement_types).intersection(hypothesis.statement_types)
            ):
                continue
            if metric.required_context_any and not any(
                required in context
                for required in metric.required_context_any
                for context in contexts
            ):
                continue
            labels = tuple(normalize_phrase(value.rsplit("›", 1)[-1]) for value in contexts)
            if any(_source_label_matches(metric, label) for label in labels):
                matches.append(metric)
        return tuple(matches)

    def _operation_eligible(
        self, metric: MetricSpec, annotations: QuestionAnnotations
    ) -> bool:
        operation = annotations.operation.value
        return (
            operation in self.policy.supported_operations
            and operation in metric.legal_aggregations
        )

    def _result(
        self,
        status: str,
        *,
        selected_metric_id: str | None = None,
        mentions: tuple[ResolvedMetricMention, ...] = (),
        candidates: tuple[str, ...] = (),
        confidence: float = 0.0,
        method: str,
        reason: str | None = None,
        operation_eligible: bool = False,
        trace: tuple[dict[str, object], ...] = (),
    ) -> MetricResolution:
        return MetricResolution(
            status=status,
            selected_metric_id=selected_metric_id,
            mentions=mentions,
            candidates=candidates,
            confidence=confidence,
            resolution_method=method,
            reason=reason,
            ontology_fingerprint=self.ontology.fingerprint,
            resolver_fingerprint=self.fingerprint,
            operation_eligible=operation_eligible,
            trace=trace,
        )


def _normalize_with_offsets(value: str) -> tuple[str, tuple[int, ...]]:
    output: list[str] = []
    offsets: list[int] = []
    for index, character in enumerate(unicodedata.normalize("NFC", value)):
        decomposed = unicodedata.normalize("NFD", character.casefold())
        plain = "".join(
            part for part in decomposed if unicodedata.category(part) != "Mn"
        ).replace("đ", "d")
        for part in plain:
            if part.isspace():
                if output and output[-1] != " ":
                    output.append(" ")
                    offsets.append(index)
            else:
                output.append(part)
                offsets.append(index)
    if output and output[-1] == " ":
        output.pop()
        offsets.pop()
    return "".join(output), tuple(offsets)


def _contains_phrase(text: str, phrase: str) -> bool:
    return re.search(rf"(?<![{_WORD}]){re.escape(phrase)}(?![{_WORD}])", text) is not None


def _metric_context_rejection(metric: MetricSpec, normalized_question: str) -> str | None:
    if any(_contains_phrase(normalized_question, value) for value in metric.forbidden_prefixes):
        return "FORBIDDEN_PREFIX"
    if any(_contains_phrase(normalized_question, value) for value in metric.forbidden_contains):
        return "FORBIDDEN_CONTAINS"
    return None


def _source_label_matches(metric: MetricSpec, label: str) -> bool:
    if any(label.startswith(value) for value in metric.forbidden_prefixes):
        return False
    if any(value in label for value in metric.forbidden_contains):
        return False
    return any(label == alias or label.startswith(f"{alias} ") for alias in metric.aliases)


def _dimension_compatible(expected: Dimension, actual: Dimension) -> bool:
    if actual == Dimension.UNKNOWN:
        return True
    if expected == actual:
        return True
    return {expected, actual} == {Dimension.PERCENT, Dimension.RATIO}
