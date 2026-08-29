"""Structured Ollama adapter for an eligible open-weight local model."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence

from text2pandas.application.usecases.grounded_synthesis import (
    GroundedFact,
    GroundedPlan,
    GroundedPlanError,
    GroundedProgram,
    ProgramOperation,
)

_PLAN_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "operation": {
            "type": "string",
            "enum": [
                "lookup",
                "sum",
                "average",
                "median",
                "minimum",
                "maximum",
                "difference",
                "growth",
                "ratio",
                "count",
                "argmax_period",
                "argmin_period",
                "select_at_arg",
            ],
        },
        "operand_uids": {"type": "array", "items": {"type": "string"}},
        "selector_uids": {"type": "array", "items": {"type": "string"}},
        "value_uids": {"type": "array", "items": {"type": "string"}},
        "join_axis": {"type": ["string", "null"], "enum": ["entity", "period", None]},
        "direction": {"type": ["string", "null"], "enum": ["max", "min", None]},
        "absolute_difference": {"type": "boolean"},
        "comparator": {
            "type": ["string", "null"],
            "enum": ["gt", "gte", "lt", "lte", "eq", None],
        },
        "threshold": {"type": ["number", "null"]},
        "output_dimension": {
            "type": "string",
            "enum": [
                "money",
                "percent",
                "percent_point",
                "ratio",
                "count",
                "shares",
                "period",
            ],
        },
        "output_scale_exponent": {"type": ["integer", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "operation",
        "operand_uids",
        "selector_uids",
        "value_uids",
        "join_axis",
        "direction",
        "absolute_difference",
        "comparator",
        "threshold",
        "output_dimension",
        "output_scale_exponent",
        "confidence",
    ],
    "additionalProperties": False,
}

_PROGRAM_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "nodes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "operation": {
                        "type": "string",
                        "enum": [
                            "facts",
                            "literal",
                            "add",
                            "subtract",
                            "multiply",
                            "divide",
                            "growth",
                            "growth_by_entity",
                            "rolling_growth",
                            "change_by_entity",
                            "earliest_by_entity",
                            "latest_by_entity",
                            "rolling_average_by_entity",
                            "rolling_change_by_entity",
                            "all_by_entity",
                            "any_by_entity",
                            "average_by_entity",
                            "sum_by_entity",
                            "cagr_by_entity",
                            "drop_first_by_entity",
                            "rolling_change",
                            "top_k_mask",
                            "bottom_k_mask",
                            "shift_key",
                            "first_true_key",
                            "last_true_key",
                            "to_percent",
                            "absolute",
                            "sum",
                            "average",
                            "median",
                            "minimum",
                            "maximum",
                            "compare",
                            "logical_and",
                            "logical_or",
                            "filter",
                            "argmax_key",
                            "argmin_key",
                            "select_at_key",
                            "count_true",
                        ],
                    },
                    "input_ids": {"type": "array", "items": {"type": "string"}},
                    "fact_uids": {"type": "array", "items": {"type": "string"}},
                    "axis": {
                        "type": ["string", "null"],
                        "enum": ["entity", "period", "entity_period", None],
                    },
                    "literal": {"type": ["number", "null"]},
                    "comparator": {
                        "type": ["string", "null"],
                        "enum": ["gt", "gte", "lt", "lte", "eq", None],
                    },
                },
                "required": [
                    "id",
                    "operation",
                    "input_ids",
                    "fact_uids",
                    "axis",
                    "literal",
                    "comparator",
                ],
                "additionalProperties": False,
            },
        },
        "output_node_id": {"type": "string"},
        "output_dimension": {
            "type": "string",
            "enum": [
                "money",
                "percent",
                "percent_point",
                "ratio",
                "count",
                "shares",
                "period",
            ],
        },
        "output_scale_exponent": {"type": ["integer", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "nodes",
        "output_node_id",
        "output_dimension",
        "output_scale_exponent",
        "confidence",
    ],
    "additionalProperties": False,
}

_SEMANTIC_PROGRAM_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "nodes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "operation": {
                        "type": "string",
                        "enum": [
                            "metric",
                            "literal",
                            "add",
                            "subtract",
                            "multiply",
                            "divide",
                            "growth",
                            "growth_by_entity",
                            "rolling_growth",
                            "change_by_entity",
                            "earliest_by_entity",
                            "latest_by_entity",
                            "rolling_average_by_entity",
                            "rolling_change_by_entity",
                            "all_by_entity",
                            "any_by_entity",
                            "average_by_entity",
                            "sum_by_entity",
                            "cagr_by_entity",
                            "drop_first_by_entity",
                            "rolling_change",
                            "top_k_mask",
                            "bottom_k_mask",
                            "shift_key",
                            "first_true_key",
                            "last_true_key",
                            "to_percent",
                            "absolute",
                            "sum",
                            "average",
                            "median",
                            "minimum",
                            "maximum",
                            "compare",
                            "logical_and",
                            "logical_or",
                            "filter",
                            "argmax_key",
                            "argmin_key",
                            "select_at_key",
                            "count_true",
                        ],
                    },
                    "input_ids": {"type": "array", "items": {"type": "string"}},
                    "metric_id": {"type": ["string", "null"]},
                    "literal": {"type": ["number", "null"]},
                    "comparator": {
                        "type": ["string", "null"],
                        "enum": ["gt", "gte", "lt", "lte", "eq", None],
                    },
                },
                "required": [
                    "id",
                    "operation",
                    "input_ids",
                    "metric_id",
                    "literal",
                    "comparator",
                ],
                "additionalProperties": False,
            },
        },
        "output_node_id": {"type": "string"},
        "output_dimension": {
            "type": "string",
            "enum": [
                "money",
                "percent",
                "percent_point",
                "ratio",
                "count",
                "shares",
                "period",
            ],
        },
        "output_scale_exponent": {"type": ["integer", "null"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": [
        "nodes",
        "output_node_id",
        "output_dimension",
        "output_scale_exponent",
        "confidence",
    ],
    "additionalProperties": False,
}


_SYSTEM_PROMPT = """Bạn là program planner cho câu hỏi tài chính tiếng Việt.

Bạn KHÔNG được trả lời bằng kiến thức nhớ sẵn, KHÔNG được tự tạo số, table id hay observation id.
Input gồm câu hỏi và danh sách facts lấy trực tiếp từ BCTC. Chỉ chọn uid có trong FACTS.

Hợp đồng operation:
- lookup: đúng 1 operand.
- difference: operand_uids=[số bị trừ, số trừ]; đặt absolute_difference=true nếu câu hỏi chỉ hỏi
  chênh lệch mà không chỉ rõ hướng.
- growth: operand_uids=[kỳ cũ, kỳ mới], kết quả phần trăm.
- ratio: operand_uids=[tử số, mẫu số].
- sum/average/median/minimum/maximum: toàn bộ population đúng metric và scope.
- argmax_period/argmin_period: các facts cùng metric qua các kỳ; kết quả là năm.
- count: toàn bộ population, comparator và threshold phải ở canonical unit của fact.
- select_at_arg: selector_uids là metric dùng để xếp hạng; value_uids là metric cần trả về;
  join_axis entity hoặc period, direction max hoặc min.

Quy tắc bắt buộc:
1. Khớp chính xác metric, entity, period và basis (công ty mẹ=separate; mặc định=consolidated).
2. Không trộn current-year với comparative/restated value của kỳ khác.
3. Tiền canonical_value là VND; output_scale_exponent: đồng=0, nghìn=3, triệu=6, tỷ=9.
4. Tỷ lệ tăng trưởng trả output_dimension=percent. Chênh lệch hai tỷ lệ thường là
   percent_point. Năm trả output_dimension=period.
5. Nếu facts không đủ hoặc mơ hồ, vẫn chỉ trả plan tốt nhất nhưng confidence phải phản ánh rủi ro.
6. Không đưa answer hay phép tính số vào output; chỉ plan JSON đúng schema.
"""

_PROGRAM_SYSTEM_PROMPT = """Bạn là compiler cho câu hỏi tài chính tiếng Việt.

Không được sinh answer, không được tự tạo số liệu hay UID. Chỉ chọn UID trong FACTS và dựng DAG.
FACTS không chứa giá trị số; deterministic executor sẽ đọc giá trị thật từ A6 sau khi validate.

Type system:
- facts: fact_uids cùng đúng MỘT retrieval_metric, axis=entity/period/entity_period; trả numeric series.
- literal: hằng ngưỡng có trong câu hỏi (thường 0); không có input/fact.
- add/subtract/multiply/divide/growth: 2 inputs, hỗ trợ scalar/series và align theo key.
- sum/average/median/minimum/maximum: aggregate 1 series thành scalar.
- compare: 2 numeric inputs + comparator, trả boolean scalar/series.
- logical_and/logical_or: 2 boolean inputs cùng key.
- filter: [numeric_series, boolean_series].
- argmax_key/argmin_key: 1 numeric series, trả key.
- select_at_key: [value_series, key].
- count_true: 1 boolean series.
- absolute: 1 numeric input.

Ràng buộc:
1. Mỗi facts node phải đủ toàn bộ entity/period được hỏi cho metric đó, không lấy comparative/restated sai kỳ.
   Không được trộn nhiều retrieval_metric trong cùng facts node. Không dùng cùng một facts node cho hai metric.
2. Basis: công ty mẹ=separate; hợp nhất/mặc định ưu tiên consolidated.
3. Vốn lưu động ròng = tài sản ngắn hạn - nợ ngắn hạn. Growth dùng [kỳ cũ, kỳ mới].
4. Câu hỏi lọc/xếp hạng/chọn giá trị phải dùng compare/filter/arg*_key/select_at_key, không rút gọn.
5. output_scale_exponent tiền/cổ phiếu: đồng=0, nghìn=3, triệu=6, tỷ=9.
6. Nếu thiếu facts, dựng DAG tốt nhất nhưng hạ confidence; tuyệt đối không dùng kiến thức nhớ sẵn.
7. Quy ước dấu bắt buộc: "âm" = compare lt literal(0), "dương" = compare gt literal(0).
   Không dùng -1 hoặc 1 thay cho ngưỡng 0. facts/literal node luôn có input_ids=[].
8. DETERMINISTIC_HINTS.required_formulas là contract bắt buộc. Compile đúng từng expression
   và leaves đã cho; không thay divide bằng subtract, không so sánh với 0 nếu đề yêu cầu median.

Ví dụ shape COUNT compound: facts(current_assets by entity), facts(current_liabilities by entity),
subtract, literal(0), compare(lt), facts(operating_cashflow by entity), compare(gt), logical_and,
count_true.
Ví dụ shape filtered select: facts(filter_metric by period), median, compare, facts(rank_metric by period),
filter, argmax_key, facts(answer_metric by period), select_at_key.
"""

_SEMANTIC_PROGRAM_SYSTEM_PROMPT = """Bạn là semantic compiler cho câu hỏi tài chính.

Chỉ dựng DAG vectorized trên canonical metric_id được cấp. Không thấy UID và không thấy số liệu.
Deterministic binder sẽ bind toàn bộ entity/period đúng scope và thực thi sau khi type-check.

Node contract:
- metric: đúng một metric_id trong REQUIRED_METRICS, input_ids=[]. Node này đại diện TOÀN BỘ
  entity/period của metric; không tách một node cho mỗi năm/doanh nghiệp.
- literal: chỉ ngưỡng xuất hiện trong câu hỏi; âm/dương dùng 0.
- add/subtract/multiply/divide/growth: 2 inputs; xử lý vector theo scope.
- growth_by_entity: 1 metric/formula series entity_period có đúng 2 kỳ mỗi entity -> growth theo entity.
- rolling_growth: 1 metric/formula series period của một entity -> growth từng kỳ so với kỳ trước.
- change_by_entity: series entity_period có đúng 2 kỳ -> (kỳ sau - kỳ trước) theo entity.
- earliest_by_entity/latest_by_entity: chiếu series entity_period về kỳ đầu/cuối theo entity.
- rolling_average_by_entity/rolling_change_by_entity: bình quân/chênh lệch từng cặp kỳ liên tiếp.
- all_by_entity/any_by_entity: rút boolean entity_period về boolean theo doanh nghiệp.
- average_by_entity/sum_by_entity: rút numeric entity_period về numeric theo doanh nghiệp.
- cagr_by_entity: CAGR từ kỳ đầu đến kỳ cuối theo doanh nghiệp; rolling_change: chênh lệch
  kỳ sau trừ kỳ trước cho chuỗi period của một doanh nghiệp.
- drop_first_by_entity: bỏ kỳ đầu tiên của từng doanh nghiệp nhưng giữ axis entity_period;
  dùng khi retrieval mở rộng thêm prior-year chỉ để tính số dư bình quân.
- top_k_mask/bottom_k_mask: 1 series + literal K xuất hiện trong câu hỏi -> boolean mask đúng K key.
- shift_key: dịch một period key theo literal số năm (ví dụ năm ngay sau dùng 1).
- first_true_key/last_true_key: lấy period key đầu/cuối có predicate boolean đúng.
- to_percent: đổi ratio sang percent bằng nhân 100, không dùng literal 100.
- sum/average/median/minimum/maximum: 1 numeric series -> scalar.
- compare: 2 numeric inputs + comparator -> boolean series.
- logical_and/logical_or: 2 boolean series.
- filter: [numeric_series, boolean_series].
- argmax_key/argmin_key: 1 numeric series -> entity/period key.
- select_at_key: [value_series, key].
- count_true: 1 boolean series.

Ràng buộc bắt buộc:
1. REQUIRED_FORMULAS là source of truth: compile đúng expression/leaves, không đổi divide/subtract.
2. Câu cohort phải dựng đủ predicate -> logical -> filter/count; không bỏ điều kiện.
3. Câu "tại năm/doanh nghiệp có X cao nhất" dùng rank X rồi select metric cần trả lời.
4. Growth scalar = [kỳ cũ, kỳ mới]. Cohort 2 kỳ dùng growth_by_entity; tìm biến động
   sâu nhất qua chuỗi năm dùng rolling_growth. Trung vị dùng median, không thay bằng 0.
5. Không tự tạo metric_id, literal, answer hay scope. Nếu contract thiếu thì hạ confidence.
6. Trả đúng một JSON theo schema; graph phải dùng node id, không dùng metric id như node id nếu
   chưa khai báo metric node.

Ví dụ compound count: metric(current_assets), metric(current_liabilities), subtract, literal(0),
compare(lt), metric(cash_flow_from_operations), compare(gt), logical_and, count_true.
Ví dụ filtered select: compile filter formula series, median, compare, compile rank formula series,
filter, argmax_key, compile output formula series, select_at_key.
"""


class OllamaPlanGenerator:
    def __init__(
        self,
        *,
        model: str = "qwen3:8b",
        endpoint: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 300.0,
        seed: int = 17,
        context_tokens: int = 16_384,
    ) -> None:
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.seed = seed
        self.context_tokens = context_tokens

    def generate(
        self,
        question: str,
        facts: Sequence[GroundedFact],
        *,
        hints: Mapping[str, object],
    ) -> GroundedPlan:
        if not facts:
            raise GroundedPlanError("cannot generate a plan without candidate facts")
        compact_facts = "\n".join(
            json.dumps(fact.to_planner_dict(), ensure_ascii=False, separators=(",", ":"))
            for fact in facts
        )
        user = (
            f"QUESTION:\n{question}\n\n"
            f"DETERMINISTIC_HINTS:\n{json.dumps(dict(hints), ensure_ascii=False)}\n\n"
            f"FACTS_JSONL ({len(facts)} facts):\n{compact_facts}\n\n"
            "Chọn grounded plan tốt nhất. Chỉ trả JSON."
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "think": False,
            "format": _PLAN_SCHEMA,
            "options": {
                "temperature": 0,
                "seed": self.seed,
                "num_ctx": self.context_tokens,
            },
        }
        request = urllib.request.Request(
            f"{self.endpoint}/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw_response = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            raise GroundedPlanError(f"Ollama request failed: {error}") from error
        message = raw_response.get("message")
        if not isinstance(message, Mapping):
            raise GroundedPlanError("Ollama response has no message object")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise GroundedPlanError("Ollama response has no structured content")
        try:
            plan_raw = json.loads(content)
        except json.JSONDecodeError as error:
            raise GroundedPlanError(f"Ollama plan is not JSON: {error}") from error
        if not isinstance(plan_raw, Mapping):
            raise GroundedPlanError("Ollama plan root must be an object")
        return GroundedPlan.from_mapping(plan_raw)


class OllamaProgramGenerator:
    """Generate a compositional DAG while keeping every numeric value hidden."""

    def __init__(
        self,
        *,
        model: str = "qwen3:8b",
        endpoint: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 300.0,
        seed: int = 17,
        context_tokens: int = 16_384,
    ) -> None:
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.seed = seed
        self.context_tokens = context_tokens

    def generate(
        self,
        question: str,
        facts: Sequence[GroundedFact],
        *,
        hints: Mapping[str, object],
    ) -> GroundedProgram:
        if not facts:
            raise GroundedPlanError("cannot generate a program without candidate facts")
        compact_facts = "\n".join(
            json.dumps(fact.to_planner_dict(), ensure_ascii=False, separators=(",", ":"))
            for fact in facts
        )
        user = (
            f"QUESTION:\n{question}\n\n"
            f"DETERMINISTIC_HINTS:\n{json.dumps(dict(hints), ensure_ascii=False)}\n\n"
            f"FACTS_JSONL ({len(facts)} facts):\n{compact_facts}\n\n"
            "Compile grounded DAG tốt nhất. Chỉ trả JSON đúng schema."
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _PROGRAM_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "think": False,
            "format": _PROGRAM_SCHEMA,
            "options": {
                "temperature": 0,
                "seed": self.seed,
                "num_ctx": self.context_tokens,
            },
        }
        request = urllib.request.Request(
            f"{self.endpoint}/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw_response = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            raise GroundedPlanError(f"Ollama request failed: {error}") from error
        message = raw_response.get("message")
        if not isinstance(message, Mapping):
            raise GroundedPlanError("Ollama response has no message object")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise GroundedPlanError("Ollama response has no structured content")
        try:
            program_raw = json.loads(content)
        except json.JSONDecodeError as error:
            raise GroundedPlanError(f"Ollama program is not JSON: {error}") from error
        if not isinstance(program_raw, Mapping):
            raise GroundedPlanError("Ollama program root must be an object")
        return GroundedProgram.from_mapping(program_raw)


class OllamaSemanticProgramGenerator:
    """Generate only a value-free metric DAG, then bind facts deterministically."""

    def __init__(
        self,
        *,
        model: str = "qwen3:8b",
        endpoint: str = "http://127.0.0.1:11434",
        timeout_seconds: float = 300.0,
        seed: int = 17,
        context_tokens: int = 4_096,
    ) -> None:
        self.model = model
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.seed = seed
        self.context_tokens = context_tokens

    def generate(
        self,
        question: str,
        facts: Sequence[GroundedFact],
        *,
        hints: Mapping[str, object],
    ) -> GroundedProgram:
        metric_summary = _metric_summary(facts)
        if not metric_summary:
            raise GroundedPlanError("cannot generate semantic program without metrics")
        user = (
            f"QUESTION:\n{question}\n\n"
            f"DETERMINISTIC_HINTS:\n{json.dumps(dict(hints), ensure_ascii=False)}\n\n"
            f"AVAILABLE_METRIC_SCOPES:\n{json.dumps(metric_summary, ensure_ascii=False)}\n\n"
            "Compile semantic DAG vectorized tốt nhất. Chỉ trả JSON đúng schema."
        )
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SEMANTIC_PROGRAM_SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "think": False,
            "format": _SEMANTIC_PROGRAM_SCHEMA,
            "options": {
                "temperature": 0,
                "seed": self.seed,
                "num_ctx": self.context_tokens,
            },
        }
        request = urllib.request.Request(
            f"{self.endpoint}/api/chat",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                raw_response = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as error:
            raise GroundedPlanError(f"Ollama request failed: {error}") from error
        message = raw_response.get("message")
        if not isinstance(message, Mapping):
            raise GroundedPlanError("Ollama response has no message object")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise GroundedPlanError("Ollama response has no structured content")
        try:
            program_raw = json.loads(content)
        except json.JSONDecodeError as error:
            raise GroundedPlanError(f"Ollama semantic program is not JSON: {error}") from error
        if not isinstance(program_raw, Mapping):
            raise GroundedPlanError("Ollama semantic program root must be an object")
        normalized_program = _normalize_semantic_literals(program_raw, question)
        _normalize_percent_scaling(normalized_program)
        requested_unit = hints.get("requested_unit")
        if isinstance(requested_unit, Mapping):
            requested_dimension = requested_unit.get("dimension")
            if requested_dimension is not None:
                normalized_program["output_dimension"] = str(requested_dimension)
            requested_scale = requested_unit.get("scale_exponent")
            normalized_program["output_scale_exponent"] = requested_scale
        return compile_semantic_program(
            normalized_program, facts, hints=hints
        )


def compile_semantic_program(
    raw: Mapping[str, object],
    facts: Sequence[GroundedFact],
    *,
    hints: Mapping[str, object] | None = None,
) -> GroundedProgram:
    """Lower metric nodes to immutable fact UIDs without semantic guessing."""

    grouped: dict[str, list[GroundedFact]] = {}
    for fact in facts:
        if fact.retrieval_metric:
            grouped.setdefault(fact.retrieval_metric, []).append(fact)
    normalized_raw = _normalize_semantic_graph(raw, frozenset(grouped))
    nodes_raw = normalized_raw.get("nodes")
    if not isinstance(nodes_raw, Sequence) or isinstance(nodes_raw, (str, bytes)):
        raise GroundedPlanError("semantic program nodes must be a list")
    semantic_nodes = [dict(item) for item in nodes_raw if isinstance(item, Mapping)]
    if len(semantic_nodes) != len(nodes_raw):
        raise GroundedPlanError("semantic program node must be an object")
    known_ids = {str(item.get("id") or "") for item in semantic_nodes}
    inferred_sources: list[dict[str, object]] = []
    for item in semantic_nodes:
        for input_id in _strings(item.get("input_ids")):
            if input_id in known_ids or not input_id.startswith("metric_"):
                continue
            metric_id = input_id.removeprefix("metric_")
            if metric_id not in grouped:
                continue
            inferred_sources.append(
                {
                    "id": input_id,
                    "operation": "metric",
                    "input_ids": [],
                    "metric_id": metric_id,
                    "literal": None,
                    "comparator": None,
                }
            )
            known_ids.add(input_id)
    semantic_nodes = inferred_sources + semantic_nodes
    lowered: list[dict[str, object]] = []
    axis_by_node: dict[str, str | None] = {}
    for item in semantic_nodes:
        operation = str(item.get("operation") or "")
        node_id = str(item.get("id") or "")
        if operation == "metric":
            metric_id = str(item.get("metric_id") or "")
            metric_facts = grouped.get(metric_id, [])
            if not metric_facts:
                raise GroundedPlanError(
                    f"semantic program references unavailable metric: {metric_id}"
                )
            lowered.append(
                {
                    "id": node_id,
                    "operation": ProgramOperation.FACTS.value,
                    "input_ids": [],
                    "fact_uids": [
                        fact.observation_uid
                        for fact in sorted(metric_facts, key=_semantic_fact_key)
                    ],
                    "axis": _semantic_axis(metric_facts),
                    "literal": None,
                    "comparator": None,
                }
            )
            axis_by_node[node_id] = _semantic_axis(metric_facts)
            continue
        input_ids = _strings(item.get("input_ids"))
        if operation == ProgramOperation.GROWTH.value and len(input_ids) == 1:
            input_axis = axis_by_node.get(input_ids[0])
            if input_axis == "entity_period":
                operation = ProgramOperation.GROWTH_BY_ENTITY.value
            elif input_axis == "period":
                operation = ProgramOperation.ROLLING_GROWTH.value
        elif (
            operation == ProgramOperation.ROLLING_GROWTH.value
            and len(input_ids) == 1
            and axis_by_node.get(input_ids[0]) == "entity_period"
        ):
            operation = ProgramOperation.GROWTH_BY_ENTITY.value
        try:
            lowered_operation = ProgramOperation(operation)
        except ValueError as error:
            raise GroundedPlanError(
                f"invalid semantic program operation: {operation}"
            ) from error
        lowered.append(
            {
                "id": node_id,
                "operation": lowered_operation.value,
                "input_ids": list(input_ids),
                "fact_uids": [],
                "axis": None,
                "literal": item.get("literal"),
                "comparator": item.get("comparator"),
            }
        )
        input_axes = {
            axis_by_node.get(value)
            for value in input_ids
            if axis_by_node.get(value) is not None
        }
        vector_preserving = {
            ProgramOperation.ADD,
            ProgramOperation.SUBTRACT,
            ProgramOperation.MULTIPLY,
            ProgramOperation.DIVIDE,
            ProgramOperation.ABSOLUTE,
            ProgramOperation.TO_PERCENT,
            ProgramOperation.COMPARE,
            ProgramOperation.LOGICAL_AND,
            ProgramOperation.LOGICAL_OR,
            ProgramOperation.FILTER,
            ProgramOperation.TOP_K_MASK,
            ProgramOperation.BOTTOM_K_MASK,
        }
        if lowered_operation in vector_preserving and len(input_axes) == 1:
            axis_by_node[node_id] = next(iter(input_axes))
        elif lowered_operation in {
            ProgramOperation.GROWTH_BY_ENTITY,
            ProgramOperation.CHANGE_BY_ENTITY,
            ProgramOperation.EARLIEST_BY_ENTITY,
            ProgramOperation.LATEST_BY_ENTITY,
            ProgramOperation.ALL_BY_ENTITY,
            ProgramOperation.ANY_BY_ENTITY,
            ProgramOperation.AVERAGE_BY_ENTITY,
            ProgramOperation.SUM_BY_ENTITY,
            ProgramOperation.CAGR_BY_ENTITY,
        }:
            axis_by_node[node_id] = "entity"
        elif lowered_operation in {
            ProgramOperation.ROLLING_AVERAGE_BY_ENTITY,
            ProgramOperation.ROLLING_CHANGE_BY_ENTITY,
            ProgramOperation.DROP_FIRST_BY_ENTITY,
        }:
            axis_by_node[node_id] = "entity_period"
        elif lowered_operation in {
            ProgramOperation.ROLLING_GROWTH,
            ProgramOperation.ROLLING_CHANGE,
        }:
            axis_by_node[node_id] = "period"
        else:
            axis_by_node[node_id] = None
    payload = dict(normalized_raw)
    payload["nodes"] = lowered
    output_node_id = str(payload.get("output_node_id") or "")
    aggregate = _semantic_output_aggregate(
        hints or {}, axis_by_node.get(output_node_id)
    )
    if aggregate is not None:
        scalar_id = output_node_id + "_scalar"
        known_lowered_ids = {str(item["id"]) for item in lowered}
        while scalar_id in known_lowered_ids:
            scalar_id += "_"
        lowered.append(
            {
                "id": scalar_id,
                "operation": aggregate.value,
                "input_ids": [output_node_id],
                "fact_uids": [],
                "axis": None,
                "literal": None,
                "comparator": None,
            }
        )
        payload["output_node_id"] = scalar_id
    return GroundedProgram.from_mapping(payload)


_SEMANTIC_METRIC_ALIASES = {
    "net_income": "profit_after_tax",
    "operating_cash_flow": "cash_flow_from_operations",
    "operating_cashflow": "cash_flow_from_operations",
    "revenue": "net_revenue",
}


def _normalize_semantic_graph(
    raw: Mapping[str, object], available_metrics: frozenset[str]
) -> dict[str, object]:
    """Canonicalize value-free model syntax before strict typed lowering."""

    nodes_raw = raw.get("nodes")
    if not isinstance(nodes_raw, Sequence) or isinstance(nodes_raw, (str, bytes)):
        return dict(raw)
    nodes = [dict(item) if isinstance(item, Mapping) else item for item in nodes_raw]
    aliased: list[object] = []
    for item in nodes:
        if not isinstance(item, dict):
            aliased.append(item)
            continue
        if str(item.get("operation") or "") == "metric":
            metric_id = str(item.get("metric_id") or "")
            item["metric_id"] = _SEMANTIC_METRIC_ALIASES.get(metric_id, metric_id)
        aliased.append(item)
    nodes = _expand_inventory_days_nodes(aliased, available_metrics)

    replacements: dict[str, str] = {}
    canonical_source: dict[str, str] = {}
    unique_nodes: list[object] = []
    for item in nodes:
        if not isinstance(item, dict) or str(item.get("operation") or "") != "metric":
            unique_nodes.append(item)
            continue
        node_id = str(item.get("id") or "")
        metric_id = str(item.get("metric_id") or "")
        existing = canonical_source.get(metric_id)
        if existing is not None and node_id:
            replacements[node_id] = existing
            continue
        canonical_source[metric_id] = node_id
        unique_nodes.append(item)

    def resolve(node_id: str) -> str:
        visited: set[str] = set()
        while node_id in replacements and node_id not in visited:
            visited.add(node_id)
            node_id = replacements[node_id]
        return node_id

    collapsed: list[object] = []
    unary_temporal = {
        ProgramOperation.GROWTH_BY_ENTITY.value,
        ProgramOperation.ROLLING_GROWTH.value,
        ProgramOperation.CHANGE_BY_ENTITY.value,
        ProgramOperation.EARLIEST_BY_ENTITY.value,
        ProgramOperation.LATEST_BY_ENTITY.value,
        ProgramOperation.ROLLING_AVERAGE_BY_ENTITY.value,
        ProgramOperation.ROLLING_CHANGE_BY_ENTITY.value,
        ProgramOperation.ALL_BY_ENTITY.value,
        ProgramOperation.ANY_BY_ENTITY.value,
        ProgramOperation.AVERAGE_BY_ENTITY.value,
        ProgramOperation.SUM_BY_ENTITY.value,
        ProgramOperation.CAGR_BY_ENTITY.value,
        ProgramOperation.DROP_FIRST_BY_ENTITY.value,
        ProgramOperation.ROLLING_CHANGE.value,
    }
    for item in unique_nodes:
        if not isinstance(item, dict):
            collapsed.append(item)
            continue
        node = dict(item)
        input_ids = tuple(resolve(value) for value in _strings(node.get("input_ids")))
        operation = str(node.get("operation") or "")
        unique_inputs = tuple(dict.fromkeys(input_ids))
        node_id = str(node.get("id") or "")
        if len(unique_inputs) < len(input_ids):
            if operation in unary_temporal:
                node["input_ids"] = list(unique_inputs[:1])
            elif operation in {
                ProgramOperation.LOGICAL_AND.value,
                ProgramOperation.LOGICAL_OR.value,
            } and len(unique_inputs) == 1:
                replacements[node_id] = unique_inputs[0]
                continue
            else:
                node["input_ids"] = list(input_ids)
        else:
            node["input_ids"] = list(input_ids)
        collapsed.append(node)

    for item in collapsed:
        if isinstance(item, dict):
            item["input_ids"] = [
                resolve(value) for value in _strings(item.get("input_ids"))
            ]
    output = dict(raw)
    output["nodes"] = collapsed
    output["output_node_id"] = resolve(str(raw.get("output_node_id") or ""))
    return output


def _expand_inventory_days_nodes(
    nodes: Sequence[object], available_metrics: frozenset[str]
) -> list[object]:
    """Lower the common virtual inventory-days metric to canonical leaves."""

    if not {"inventory", "cogs"} <= available_metrics:
        return list(nodes)
    output: list[object] = []
    for item in nodes:
        if not isinstance(item, dict) or not (
            str(item.get("operation") or "") == "metric"
            and str(item.get("metric_id") or "") == "inventory_days"
        ):
            output.append(item)
            continue
        node_id = str(item.get("id") or "inventory_days")
        inventory = node_id + "_inventory"
        cogs = node_id + "_cogs"
        average_inventory = node_id + "_average_inventory"
        absolute_cogs = node_id + "_absolute_cogs"
        ratio = node_id + "_ratio"
        days = node_id + "_days"
        output.extend(
            [
                {
                    "id": inventory,
                    "operation": "metric",
                    "input_ids": [],
                    "metric_id": "inventory",
                    "literal": None,
                    "comparator": None,
                },
                {
                    "id": cogs,
                    "operation": "metric",
                    "input_ids": [],
                    "metric_id": "cogs",
                    "literal": None,
                    "comparator": None,
                },
                {
                    "id": average_inventory,
                    "operation": ProgramOperation.ROLLING_AVERAGE_BY_ENTITY.value,
                    "input_ids": [inventory],
                    "metric_id": None,
                    "literal": None,
                    "comparator": None,
                },
                {
                    "id": absolute_cogs,
                    "operation": ProgramOperation.ABSOLUTE.value,
                    "input_ids": [cogs],
                    "metric_id": None,
                    "literal": None,
                    "comparator": None,
                },
                {
                    "id": ratio,
                    "operation": ProgramOperation.DIVIDE.value,
                    "input_ids": [average_inventory, absolute_cogs],
                    "metric_id": None,
                    "literal": None,
                    "comparator": None,
                },
                {
                    "id": days,
                    "operation": ProgramOperation.LITERAL.value,
                    "input_ids": [],
                    "metric_id": None,
                    "literal": 365,
                    "comparator": None,
                },
                {
                    "id": node_id,
                    "operation": ProgramOperation.MULTIPLY.value,
                    "input_ids": [ratio, days],
                    "metric_id": None,
                    "literal": None,
                    "comparator": None,
                },
            ]
        )
    return output


def _semantic_output_aggregate(
    hints: Mapping[str, object], output_axis: str | None
) -> ProgramOperation | None:
    if output_axis is None:
        return None
    operation = str(hints.get("operation") or "")
    if operation in {"lookup", "sum"}:
        return ProgramOperation.SUM
    if operation == "average":
        return ProgramOperation.AVERAGE
    if operation == "extremum":
        return (
            ProgramOperation.MINIMUM
            if str(hints.get("rank_direction") or "") == "ascending"
            else ProgramOperation.MAXIMUM
        )
    return None


def _normalize_percent_scaling(raw: dict[str, object]) -> None:
    """Replace planner-created ``* 100`` with the typed percent operator."""

    nodes_raw = raw.get("nodes")
    if not isinstance(nodes_raw, Sequence) or isinstance(nodes_raw, (str, bytes)):
        return
    literals: dict[str, object] = {}
    for item in nodes_raw:
        if isinstance(item, Mapping) and str(item.get("operation") or "") == "literal":
            literals[str(item.get("id") or "")] = item.get("literal")
    for item in nodes_raw:
        if not isinstance(item, dict) or str(item.get("operation") or "") != "multiply":
            continue
        input_ids = _strings(item.get("input_ids"))
        if len(input_ids) != 2:
            continue
        literal_inputs = [
            input_id
            for input_id in input_ids
            if str(literals.get(input_id)) in {"100", "100.0"}
        ]
        if len(literal_inputs) != 1:
            continue
        item["operation"] = ProgramOperation.TO_PERCENT.value
        item["input_ids"] = [
            input_id for input_id in input_ids if input_id != literal_inputs[0]
        ]


def _metric_summary(facts: Sequence[GroundedFact]) -> list[dict[str, object]]:
    grouped: dict[str, list[GroundedFact]] = {}
    for fact in facts:
        if fact.retrieval_metric:
            grouped.setdefault(fact.retrieval_metric, []).append(fact)
    return [
        {
            "metric_id": metric_id,
            "entities": sorted({fact.entity for fact in metric_facts}),
            "periods": sorted(
                {
                    str(fact.period_year)
                    for fact in metric_facts
                    if fact.period_year is not None
                }
            ),
            "dimensions": sorted({fact.dimension.value for fact in metric_facts}),
            "fact_count": len(metric_facts),
        }
        for metric_id, metric_facts in sorted(grouped.items())
    ]


def _semantic_axis(facts: Sequence[GroundedFact]) -> str:
    entities = {fact.entity for fact in facts if fact.entity}
    periods = {fact.period_year for fact in facts if fact.period_year is not None}
    if len(entities) <= 1 and len(periods) > 1:
        return "period"
    if len(periods) <= 1 and len(entities) > 1:
        return "entity"
    return "entity_period"


def _semantic_fact_key(fact: GroundedFact) -> tuple[str, int, str]:
    return (fact.entity, fact.period_year or -1, fact.observation_uid)


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(str(item) for item in value)


def _normalize_semantic_literals(
    raw: Mapping[str, object], question: str
) -> dict[str, object]:
    """Normalize the model's common +/-1 encoding of qualitative sign to zero."""

    normalized = question.lower().replace("−", "-")
    explicit_values = {
        value
        for token in re.findall(r"(?<![\w])[-+]?\d+(?:[.,]\d+)?", normalized)
        if not (value := float(token.replace(",", "."))).is_integer()
        or not 1900 <= value <= 2100
    }
    if not any(cue in normalized for cue in (" âm", " dương", "không âm", "không dương")):
        return dict(raw)
    nodes_raw = raw.get("nodes")
    if not isinstance(nodes_raw, Sequence) or isinstance(nodes_raw, (str, bytes)):
        return dict(raw)
    nodes: list[object] = []
    for item in nodes_raw:
        if not isinstance(item, Mapping):
            nodes.append(item)
            continue
        node = dict(item)
        literal = node.get("literal")
        try:
            value = float(str(literal))
        except (TypeError, ValueError):
            nodes.append(node)
            continue
        if (
            str(node.get("operation") or "") == ProgramOperation.LITERAL.value
            and value in {-1.0, 1.0}
            and value not in explicit_values
        ):
            node["literal"] = 0
        nodes.append(node)
    output = dict(raw)
    output["nodes"] = nodes
    return output
