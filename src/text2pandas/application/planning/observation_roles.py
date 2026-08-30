"""Compile question/source semantics into hard observation-role requirements."""

from __future__ import annotations

from text2pandas.domain.metrics import normalize_phrase
from text2pandas.domain.semantic import (
    Dimension,
    MetricRef,
    ObservationColumnRole,
    ObservationRoleSpec,
    ObservationRowRole,
)

STRICT_MONEY_SCALE_SOURCES = (
    "cell",
    "column_path",
    "row_context",
    "table_context",
    "section_context",
)

_ROW_CUES: tuple[tuple[ObservationRowRole, tuple[str, ...]], ...] = (
    (ObservationRowRole.ALLOWANCE, ("du phong", "hao mon luy ke", "khau hao luy ke")),
    (ObservationRowRole.COST, ("gia goc", "nguyen gia")),
    (
        ObservationRowRole.NET,
        ("gia tri con lai", "gia tri ghi so", "gia tri thuan"),
    ),
    (ObservationRowRole.TOTAL, ("tong cong", "tong so")),
)

_COLUMN_CUES: tuple[tuple[ObservationColumnRole, tuple[str, ...]], ...] = (
    (ObservationColumnRole.CLOSING, ("so cuoi nam", "cuoi nam", "so cuoi ky", "cuoi ky")),
    (ObservationColumnRole.OPENING, ("so dau nam", "dau nam", "so dau ky", "dau ky")),
    (ObservationColumnRole.CURRENT, ("nam nay", "ky nay", "hien tai")),
    (ObservationColumnRole.PRIOR, ("nam truoc", "ky truoc")),
    (ObservationColumnRole.AS_OF, ("tai ngay",)),
)


def infer_observation_role_spec(
    ref: MetricRef,
    *,
    question: str,
    entity: str | None,
) -> ObservationRoleSpec:
    """Infer only explicit/general roles; missing evidence stays unconstrained."""

    source = ref.source_binding
    surfaces = [question, *ref.qualifiers, *ref.required_context_phrases]
    if source is not None:
        surfaces.extend((source.question_surface, *source.labels, *source.row_paths))
    context = normalize_phrase(" ".join(value for value in surfaces if value))
    row_roles = tuple(
        role for role, cues in _ROW_CUES if any(_contains(context, cue) for cue in cues)
    )
    column_roles = tuple(
        role
        for role, cues in _COLUMN_CUES
        if any(_contains(context, cue) for cue in cues)
    )
    required_tokens = tuple(
        cue
        for _, cues in (*_ROW_CUES, *_COLUMN_CUES)
        for cue in cues
        if _contains(context, cue)
    )
    forbidden_tokens: tuple[str, ...] = ()
    if ObservationRowRole.COST in row_roles:
        forbidden_tokens = ("du phong", "hao mon luy ke", "khau hao luy ke")
    elif ObservationRowRole.ALLOWANCE in row_roles:
        forbidden_tokens = ("gia goc", "nguyen gia")
    exact_rows = source.row_paths if source is not None else ()
    return ObservationRoleSpec(
        source_metric_id=source.source_metric_id if source is not None else None,
        accepted_source_metric_codes=source.metric_codes if source is not None else (),
        exact_row_labels=exact_rows,
        required_row_path_tokens=required_tokens,
        forbidden_row_path_tokens=forbidden_tokens,
        allowed_row_roles=row_roles,
        allowed_column_roles=column_roles,
        allowed_period_roles=tuple(
            role.value
            for role in column_roles
            if role is not ObservationColumnRole.AS_OF
        ),
        allowed_scale_sources=(
            STRICT_MONEY_SCALE_SOURCES
            if ref.expected_unit is not None
            and ref.expected_unit.dimension is Dimension.MONEY
            else ()
        ),
        entity_membership=(entity,) if entity else ref.entities,
    )


def _contains(value: str, token: str) -> bool:
    return token == value or f" {token} " in f" {value} "
