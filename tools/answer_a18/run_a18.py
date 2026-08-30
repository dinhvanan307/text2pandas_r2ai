#!/usr/bin/env python3
"""Build and solve the A18 abstention cohort with constrained local inference.

A18 is deliberately not a gold generator.  It never reads MODEL_GOLD and it
never lets the model provide a numeric answer.  The model may only compose a
small expression language over A6 observation identifiers supplied in the
packet.  This module validates the expression, recomputes the value from the
sealed A6 database, compiles a restricted Pandas query, and emits an
allowlisted patch manifest for the existing deterministic submission builder.

Commands:

    prepare          freeze the 3818 abstention cohort and A6 candidate packets
    solve            call local Qwen2.5-14B for pass A or pass B
    adjudicate       require two-pass semantic/value agreement and build manifest

Generated run data belongs under artifacts/runs/answer/a18-* and is immutable.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import math
import re
import sqlite3
import sys
import time
import unicodedata
import urllib.error
import urllib.request
import zipfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

from text2pandas.domain.metrics import MetricOntology
from text2pandas.infrastructure.ontology import load_ontology
from text2pandas.pipelines.retrieval.metric_hint import metric_codes_hint

ROOT = Path(__file__).resolve().parents[2]
BASELINE_ZIP = (
    ROOT / "artifacts/submissions/submission_tier-b9-3816-answer-3770-retrieval-20260830-01.zip"
)
A6_DB = ROOT / "data/processed/a6/c6887fb633374fad/silver.db"
RETRIEVAL_DB = ROOT / "data/indexes/retrieval/c6887fb633374fad/872ccb0dda9a2bb6/retrieval.db"
P0_RECORDS = ROOT / "artifacts/runs/answer/p0-shadow-full-1012-20260829-01/records.jsonl"
V3_RECORDS = (
    ROOT / "artifacts/runs/semantic-v3/semantic-v3-e2e-audit-aadc8f8-20260829-01/records.jsonl"
)
MODEL_ID = "qwen2.5:14b"
MODEL_DIGEST = "7cdf5a0187d5"
BASELINE_SHA256 = "679d7d80ae9e46ca6b2f11a88ca9a3550e7538599796a38556b00f3ca2265771"
A6_SHA256 = "fa6c46d6d46b4735f6a23fe1f2b8e2be16c206b712f47b8f22a5f0647f5dc3c8"
RETRIEVAL_SHA256 = "72d307f8a2bb542a40f97e112456d537b90823e7b57a20eaef04a94545ab6daf"
RETRIEVAL_OWNER_SHA256 = "15c1854d86c3be2510ae44d10eeca1ece68c8d691bcb2c84ffa280b6b008e169"
SEMANTIC_V3_SHA256 = "3e068bc697ac9d34512f16d520af5bf4d51a6e0dc3137c503a25f9acfacb54f0"

JSON = dict[str, Any]
_YEAR = re.compile(r"\b(20\d{2})\b")
_RANGE = re.compile(
    r"\b(20\d{2})\s*(?:-|đến|toi|tới|–|—)\s*(?:năm\s*)?(20\d{2})\b",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"(?<!\w)-?\d+(?:[.,]\d+)?")

_STOP = frozenset(
    [
        "bao",
        "nhieu",
        "la",
        "cua",
        "co",
        "cac",
        "cong",
        "ty",
        "doanh",
        "nghiep",
        "ma",
        "co",
        "phieu",
        "trong",
        "vao",
        "nam",
        "cuoi",
        "tai",
        "theo",
        "tu",
        "den",
        "va",
        "giua",
        "tong",
        "muc",
        "gia",
        "tri",
        "chi",
        "tieu",
        "nhom",
        "xet",
        "duoc",
        "mot",
        "hai",
        "ba",
        "bon",
        "do",
        "nay",
        "tren",
        "duoi",
        "hon",
        "thap",
        "cao",
        "nhat",
        "binh",
        "quan",
        "trung",
        "le",
        "phan",
        "tram",
        "dong",
        "trieu",
        "nghin",
        "lan",
        "me",
        "tap",
        "doan",
        "ngan",
        "hang",
    ]
)

_OUTPUT_TRANSFORMS = frozenset(
    {
        "MONEY_VND",
        "MONEY_MILLION_VND",
        "MONEY_BILLION_VND",
        "MONEY_TRILLION_VND",
        "RATIO",
        "PERCENT_FROM_RATIO",
        "PERCENT_NATIVE",
        "YEAR",
        "COUNT",
        "RAW_NUMBER",
    }
)
_COMMUTATIVE = frozenset({"add", "mult"})
_FUNCTIONS = frozenset(
    {
        "obs",
        "mean",
        "sum_",
        "median",
        "max_",
        "min_",
        "abs_",
        "percent_change",
        "argmax",
        "argmin",
        "select_at_argmax",
        "select_at_argmin",
        "count_true",
        "sum_if",
        "mean_if",
    }
)


class A18Error(RuntimeError):
    """A fail-closed A18 preparation, inference, or compilation error."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _canonical_sha(value: object) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return _sha256_text(payload)


def _read_jsonl(path: Path) -> list[JSON]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def _write_json(path: Path, value: object) -> None:
    if path.exists():
        raise A18Error(f"immutable output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl(path: Path, rows: Iterable[JSON]) -> None:
    if path.exists():
        raise A18Error(f"immutable output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKD", value.lower().replace("đ", "d"))
    value = "".join(char for char in value if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def _tokens(value: str) -> set[str]:
    return {token for token in _normalize(value).split() if len(token) > 1 and token not in _STOP}


def _confidence_score(value: object) -> float:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return min(max(float(value), 0.0), 1.0)
    return {
        "high": 1.0,
        "medium": 0.6,
        "low": 0.2,
    }.get(str(value or "").strip().lower(), 0.0)


def _expanded_years(question: str, hints: Sequence[object]) -> list[int]:
    years = {int(value) for value in hints if str(value).isdigit()}
    years.update(int(value) for value in _YEAR.findall(question))
    for start_raw, end_raw in _RANGE.findall(question):
        start, end = int(start_raw), int(end_raw)
        if start <= end and end - start <= 15:
            years.update(range(start, end + 1))
    return sorted(years)


@dataclass(frozen=True)
class SemanticProfile:
    aliases: tuple[str, ...]
    forbidden_prefixes: tuple[str, ...]
    forbidden_contains: tuple[str, ...]
    statement_types: tuple[str, ...]


def _semantic_profiles(question: str, ontology: MetricOntology) -> tuple[SemanticProfile, ...]:
    normalized_question = _normalize(question)
    metric_ids: set[str] = set()
    for metric in ontology.metrics.values():
        if metric.review_status != "reviewed":
            continue
        if any(_normalize(alias) in normalized_question for alias in metric.aliases):
            metric_ids.add(metric.metric_id)
    for formula in ontology.formulas.values():
        if any(_normalize(alias) in normalized_question for alias in formula.aliases):
            metric_ids.update(formula.leaves)
    shorthand_metrics = {
        "cfo": "cash_flow_from_operations",
        "lnst": "profit_after_tax",
    }
    question_tokens = set(normalized_question.split())
    metric_ids.update(
        metric_id
        for shorthand, metric_id in shorthand_metrics.items()
        if shorthand in question_tokens
    )
    return tuple(
        SemanticProfile(
            aliases=tuple(_normalize(value) for value in ontology.metrics[metric_id].aliases),
            forbidden_prefixes=tuple(
                _normalize(value) for value in ontology.metrics[metric_id].forbidden_prefixes
            ),
            forbidden_contains=tuple(
                _normalize(value) for value in ontology.metrics[metric_id].forbidden_contains
            ),
            statement_types=tuple(ontology.metrics[metric_id].statement_types),
        )
        for metric_id in sorted(metric_ids)
        if metric_id in ontology.metrics
    )


def _longest_common_run(left: Sequence[str], right: Sequence[str]) -> int:
    previous = [0] * (len(right) + 1)
    best = 0
    for left_token in left:
        current = [0]
        for index, right_token in enumerate(right, start=1):
            value = previous[index - 1] + 1 if left_token == right_token else 0
            current.append(value)
            best = max(best, value)
        previous = current
    return best


def _semantic_score(
    *,
    question: str,
    leaf: str,
    statement_type: str,
    profiles: Sequence[SemanticProfile],
) -> tuple[float, str | None]:
    normalized_leaf = _normalize(leaf)
    leaf_tokens = normalized_leaf.split()
    question_tokens = _normalize(question).split()
    longest_run = _longest_common_run(question_tokens, leaf_tokens)
    score = float(longest_run * longest_run * 4)
    semantic_key: str | None = None
    for profile in profiles:
        forbidden = any(normalized_leaf.startswith(value) for value in profile.forbidden_prefixes)
        forbidden = forbidden or any(value in normalized_leaf for value in profile.forbidden_contains)
        if forbidden:
            continue
        alias_score = 0.0
        for alias in profile.aliases:
            if normalized_leaf == alias:
                alias_score = max(alias_score, 100.0)
            elif normalized_leaf.startswith(f"{alias} "):
                alias_score = max(alias_score, 85.0)
            elif alias in normalized_leaf:
                alias_score = max(alias_score, 55.0)
        if alias_score:
            if semantic_key is None:
                semantic_key = profile.aliases[0]
            score += alias_score
            if statement_type in profile.statement_types:
                score += 12.0
    return score, semantic_key


def _baseline_records() -> list[JSON]:
    if _sha256_file(BASELINE_ZIP) != BASELINE_SHA256:
        raise A18Error("3818 baseline ZIP SHA-256 mismatch")
    with zipfile.ZipFile(BASELINE_ZIP) as archive:
        records = json.loads(archive.read("submission.json"))
    if len(records) != 1012 or len({int(row["id"]) for row in records}) != 1012:
        raise A18Error("3818 baseline does not contain 1,012 unique records")
    return records


def _emitted(record: JSON) -> bool:
    return bool(record.get("evidence") and record.get("pandas_query"))


def _open_a6() -> sqlite3.Connection:
    if _sha256_file(A6_DB) != A6_SHA256:
        raise A18Error("A6 database SHA-256 mismatch")
    if _sha256_file(RETRIEVAL_DB) != RETRIEVAL_SHA256:
        raise A18Error("retrieval database SHA-256 mismatch")
    connection = sqlite3.connect(f"file:{A6_DB.resolve()}?mode=ro&immutable=1", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def _packet_candidates(
    connection: sqlite3.Connection,
    *,
    question: str,
    tickers: Sequence[str],
    years: Sequence[int],
    basis: str | None,
    profiles: Sequence[SemanticProfile],
    metric_codes: frozenset[str],
    max_per_group: int,
    max_total: int,
) -> list[JSON]:
    if not tickers or not years:
        return []
    ticker_marks = ",".join("?" for _ in tickers)
    period_marks = ",".join("?" for _ in years)
    doc_years = sorted(set(years) | {year + 1 for year in years})
    doc_marks = ",".join("?" for _ in doc_years)
    parameters: list[object] = [*tickers, *years, *doc_years]
    basis_clause = ""
    if basis in {"consolidated", "separate"}:
        basis_clause = " AND t.basis = ?"
        parameters.append(basis)
    rows = connection.execute(
        f"""
        SELECT o.observation_uid, o.table_uid, o.ticker, o.doc_year,
               t.basis, o.statement_type, t.section_text,
               o.row_path_text, o.metric_label_clean, o.metric_code, o.col_path_text,
               o.period_end, o.as_of_date, o.period_role, o.is_restated,
               o.value_decimal_text, o.value_kind, o.unit_kind, o.currency,
               o.scale_exponent, o.confidence, o.evidence_ref
          FROM observations o
          JOIN tables t USING (table_uid)
          JOIN observation_readiness r USING (observation_uid)
         WHERE o.ticker IN ({ticker_marks})
           AND (
                substr(coalesce(o.period_end, o.as_of_date, ''), 1, 4)
                    IN ({period_marks})
                OR o.doc_year IN ({doc_marks})
           )
           AND o.value_decimal_text IS NOT NULL
           AND r.execution_ready = 1
           {basis_clause}
        """,
        parameters,
    ).fetchall()
    question_tokens = _tokens(question)
    wanted_years = {str(year) for year in years}
    scored: list[tuple[float, JSON]] = []
    for row in rows:
        label = " | ".join(
            str(row[key] or "") for key in ("row_path_text", "metric_label_clean", "section_text")
        )
        leaf = str(row["row_path_text"] or row["metric_label_clean"] or "").rsplit("›", 1)[-1]
        label_tokens = _tokens(label)
        overlap = question_tokens & label_tokens
        semantic_score, semantic_key = _semantic_score(
            question=question,
            leaf=leaf,
            statement_type=str(row["statement_type"]),
            profiles=profiles,
        )
        if not overlap and semantic_key is None:
            continue
        period = str(row["period_end"] or row["as_of_date"] or "")[:4]
        score = semantic_score
        if semantic_key is not None:
            score += 500.0
        score += sum(1.0 + min(len(token), 12) / 12 for token in overlap)
        score += 8.0 * len(overlap) / max(len(label_tokens) ** 0.5, 1.0)
        score += 1.2 if period in wanted_years else 0.0
        score += 0.5 if str(row["period_role"]) in {"current", "closing"} else 0.0
        score += 0.3 if int(row["is_restated"] or 0) == 0 else 0.0
        score += _confidence_score(row["confidence"]) * 0.2
        if row["metric_code"] and str(row["metric_code"]) in metric_codes:
            score += 25.0
        item = {
            "uid": str(row["observation_uid"]),
            "table_uid": str(row["table_uid"]),
            "ticker": str(row["ticker"]),
            "doc_year": row["doc_year"],
            "basis": row["basis"],
            "statement_type": str(row["statement_type"]),
            "section": str(row["section_text"] or ""),
            "row": str(row["row_path_text"] or row["metric_label_clean"] or ""),
            "leaf": leaf,
            "metric_code": row["metric_code"],
            "semantic_key": semantic_key,
            "column": str(row["col_path_text"] or ""),
            "period": period or None,
            "period_role": str(row["period_role"]),
            "value": str(row["value_decimal_text"]),
            "value_kind": str(row["value_kind"]),
            "unit_kind": str(row["unit_kind"]),
            "currency": row["currency"],
            "scale_exponent": int(row["scale_exponent"] or 0),
            "evidence_ref": str(row["evidence_ref"]),
            "lexical_score": round(score, 6),
        }
        scored.append((score, item))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["uid"]))
    grouped: dict[tuple[str, str], int] = defaultdict(int)
    grouped_leaf: dict[tuple[str, str, str], int] = defaultdict(int)
    grouped_semantic: dict[tuple[str, str, str], int] = defaultdict(int)
    signatures: set[tuple[str, str, str, str]] = set()
    selected: list[JSON] = []
    for _, item in scored:
        key = (str(item["ticker"]), str(item["period"] or item["doc_year"]))
        signature = (*key, _normalize(str(item["leaf"])), str(item["value"]))
        leaf_key = (*key, _normalize(str(item["leaf"])))
        semantic_key = (
            (*key, str(item["semantic_key"])) if item["semantic_key"] is not None else None
        )
        if signature in signatures:
            continue
        if grouped[key] >= max_per_group:
            continue
        if grouped_leaf[leaf_key] >= 3:
            continue
        if semantic_key is not None and grouped_semantic[semantic_key] >= 1:
            continue
        selected.append(item)
        grouped[key] += 1
        grouped_leaf[leaf_key] += 1
        if semantic_key is not None:
            grouped_semantic[semantic_key] += 1
        signatures.add(signature)
        if len(selected) >= max_total:
            break
    return selected


def prepare(args: argparse.Namespace) -> int:
    out = args.out.resolve()
    if out.exists():
        raise A18Error(f"run directory already exists: {out}")
    baseline = _baseline_records()
    p0 = {int(row["qid"]): row for row in _read_jsonl(P0_RECORDS)}
    v3 = {int(row["qid"]): row for row in _read_jsonl(V3_RECORDS)}
    abstentions = [row for row in baseline if not _emitted(row)]
    if len(abstentions) != 365:
        raise A18Error(f"expected 365 baseline abstentions, got {len(abstentions)}")
    packets: list[JSON] = []
    failures: Counter[str] = Counter()
    ontology = load_ontology()
    with _open_a6() as connection:
        for index, record in enumerate(abstentions, start=1):
            qid = int(record["id"])
            trace = p0[qid]
            retrieval = trace.get("retrieval") or {}
            intent = retrieval.get("intent") or {}
            tickers = [str(value) for value in intent.get("tickers") or []]
            years = _expanded_years(
                str(record["question"]), intent.get("years") or intent.get("retrieval_years") or []
            )
            basis = intent.get("basis")
            profiles = _semantic_profiles(str(record["question"]), ontology)
            metric_codes = metric_codes_hint(str(record["question"]))
            candidates = _packet_candidates(
                connection,
                question=str(record["question"]),
                tickers=tickers,
                years=years,
                basis=str(basis) if basis else None,
                profiles=profiles,
                metric_codes=metric_codes,
                max_per_group=args.max_per_group,
                max_total=args.max_candidates,
            )
            reason = str(trace.get("reason") or "UNKNOWN")
            failures[reason] += 1
            v3_record = v3.get(qid) or {}
            packets.append(
                {
                    "qid": qid,
                    "question": str(record["question"]),
                    "question_sha256": _sha256_text(str(record["question"])),
                    "baseline_answer": record["answer"],
                    "baseline_emitted": False,
                    "failure_reason": reason,
                    "tickers": tickers,
                    "years": years,
                    "basis": basis,
                    "mode": intent.get("mode"),
                    "v2_frame": (trace.get("trace") or {}).get("frame")
                    if isinstance(trace.get("trace"), dict)
                    else None,
                    "v3_reason": v3_record.get("reason"),
                    "v3_ast": v3_record.get("ast"),
                    "semantic_profile_count": len(profiles),
                    "metric_code_hints": sorted(metric_codes),
                    "candidate_count": len(candidates),
                    "candidates": candidates,
                }
            )
            if index % 50 == 0:
                print(f"prepared {index}/{len(abstentions)}", flush=True)
    manifest = {
        "schema_version": "1.0",
        "kind": "a18_abstention_cohort",
        "created_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "baseline_submission_id": 3818,
        "baseline_zip": str(BASELINE_ZIP.relative_to(ROOT)),
        "baseline_zip_sha256": BASELINE_SHA256,
        "records": 1012,
        "baseline_emitted": 647,
        "abstentions": len(abstentions),
        "packets": len(packets),
        "packets_with_candidates": sum(bool(row["candidates"]) for row in packets),
        "failure_counts": dict(failures.most_common()),
        "a6_build_id": "c6887fb633374fad",
        "a6_db_sha256": A6_SHA256,
        "retrieval_index_id": "872ccb0dda9a2bb6",
        "retrieval_db_sha256": RETRIEVAL_SHA256,
        "model_gold_read": False,
    }
    _write_jsonl(out / "packets.jsonl", packets)
    _write_json(out / "cohort_manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def _solution_schema() -> JSON:
    return {
        "type": "object",
        "required": [
            "status",
            "expression",
            "output_transform",
            "used_observation_uids",
            "operation",
            "entities",
            "periods",
            "basis",
            "confidence",
            "reason",
        ],
        "properties": {
            "status": {"type": "string", "enum": ["SOLVED", "ABSTAIN"]},
            "expression": {"type": "string"},
            "output_transform": {"type": "string", "enum": sorted(_OUTPUT_TRANSFORMS)},
            "used_observation_uids": {
                "type": "array",
                "items": {"type": "string", "pattern": "^[0-9a-f]{16}$"},
            },
            "operation": {
                "type": "string",
                "enum": [
                    "LOOKUP",
                    "ADD",
                    "SUBTRACT",
                    "DIFFERENCE",
                    "AVG",
                    "SUM",
                    "RATIO",
                    "PERCENT_CHANGE",
                    "EXTREMUM",
                    "SELECT_AT_ARG",
                    "MEDIAN_FILTER",
                    "CONDITIONAL_SUM",
                    "CONDITIONAL_AVG",
                    "COUNT",
                    "COMPLEX",
                ],
            },
            "entities": {"type": "array", "items": {"type": "string"}},
            "periods": {"type": "array", "items": {"type": "string"}},
            "basis": {"type": ["string", "null"]},
            "confidence": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
            "reason": {"type": "string"},
        },
    }


def _prompt(packet: JSON, pass_name: str) -> str:
    order = list(packet["candidates"])
    compact = [
        {
            "uid": row["uid"],
            "ticker": row["ticker"],
            "year": row["period"],
            "doc_year": row["doc_year"],
            "basis": row["basis"],
            "statement": row["statement_type"],
            "row": row["leaf"],
            "parent": row["row"][-180:],
            "column": row["column"][-100:],
            "value": row["value"],
            "kind": row["value_kind"],
            "unit": row["unit_kind"],
            "scale": row["scale_exponent"],
            "metric_code": row["metric_code"],
            "period_role": row["period_role"],
        }
        for row in order
    ]
    return f"""Bạn là semantic planner cho câu hỏi tài chính Việt Nam. Đây KHÔNG phải gold generation.

RÀNG BUỘC CỨNG:
1. Không tự đưa ra đáp án số và không dùng observation ngoài danh sách.
2. Chỉ trả JSON theo schema. Nếu thiếu bất kỳ toán hạng, sai entity/kỳ/basis,
   hoặc nhãn cha-con mơ hồ, status=ABSTAIN.
3. expression chỉ được dùng DSL sau:
   obs("uid"), +, -, *, /, mean([...]), sum_([...]), median([...]),
   max_([...]), min_([...]), abs_(x), percent_change(old,new),
   argmax([("label",expr),...]), argmin(...),
   select_at_argmax([(rank_expr,value_expr),...]), select_at_argmin(...),
   count_true([condition,...]), sum_if([(condition,value),...]),
   mean_if([(condition,value),...]).
4. obs() là giá trị đã quy về base unit bằng value * 10^scale.
5. used_observation_uids phải đúng bằng tập UID xuất hiện trong expression.
6. Với chênh lệch, giữ đúng thứ tự được hỏi. Với chi phí/dự phòng âm, chỉ dùng
   abs_ khi câu hỏi nói số dư/mức/độ lớn chứ không hỏi giá trị có dấu.
7. output_transform: tiền VND/triệu/tỷ/nghìn tỷ; tỷ số; phần trăm từ tỷ số;
   phần trăm nguồn; năm; đếm; hoặc số thô.
8. Không chọn parent row khi câu hỏi yêu cầu child label và ngược lại.
9. operation phải dùng đúng enum trong schema; entities, periods và basis phải
   mô tả đúng scope thực sự của expression, không chép máy móc hint thừa.
10. Chỉ ABSTAIN khi thật sự thiếu toán hạng hoặc semantic mơ hồ; câu tính toán
    nhiều bước vẫn SOLVED nếu mọi toán hạng cần thiết đều có trong candidates.
11. expression KHÔNG được chia/nhân để đổi đơn vị; output_transform làm việc đó.
    percent_change(old,new) đã trả phần trăm nên phải dùng PERCENT_NATIVE.
12. AVG phải dùng mean([...]) và phải chứa đúng một toán hạng cho MỖI entity
    được câu hỏi liệt kê. Thiếu một entity thì ABSTAIN, không tính trên tập con.

PASS ĐỘC LẬP: {pass_name.upper()}
QID: {packet["qid"]}
Câu hỏi: {packet["question"]}
Entity hints: {json.dumps(packet["tickers"], ensure_ascii=False)}
Period hints: {json.dumps(packet["years"], ensure_ascii=False)}
Basis hint: {json.dumps(packet["basis"], ensure_ascii=False)}
V2 failure: {packet["failure_reason"]}
V3 failure: {packet.get("v3_reason")}

A6 candidates:
{json.dumps(compact, ensure_ascii=False, separators=(",", ":"))}
"""


def _ollama_generate(prompt: str, args: argparse.Namespace) -> JSON:
    body = {
        "model": args.model,
        "prompt": prompt,
        "stream": False,
        "format": _solution_schema(),
        "options": {
            "temperature": 0.0,
            "top_p": 1.0,
            "seed": args.seed,
            "num_ctx": args.num_ctx,
            "num_predict": args.max_tokens,
        },
        "keep_alive": args.keep_alive,
    }
    request = urllib.request.Request(
        f"{args.url.rstrip('/')}/api/generate",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            event = json.loads(response.read())
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as error:
        raise A18Error(f"Ollama request failed: {error}") from error
    raw_response = event.get("response")
    decoded: object = None
    parse_error: str | None = None
    try:
        decoded = json.loads(raw_response)
        if not isinstance(decoded, dict):
            raise TypeError("schema response root is not an object")
    except (TypeError, json.JSONDecodeError) as error:
        parse_error = f"Ollama response is not schema JSON: {error}"
    return {
        "solution": decoded if isinstance(decoded, dict) else None,
        "parse_error": parse_error,
        "raw_response": raw_response,
        "model": event.get("model"),
        "created_at": event.get("created_at"),
        "done_reason": event.get("done_reason"),
        "prompt_eval_count": event.get("prompt_eval_count"),
        "eval_count": event.get("eval_count"),
        "total_duration": event.get("total_duration"),
    }


def solve(args: argparse.Namespace) -> int:
    if args.model != MODEL_ID:
        raise A18Error(f"unsealed model requested: {args.model}; expected {MODEL_ID}")
    run_dir = args.run.resolve()
    packets_path = run_dir / "packets.jsonl"
    if not packets_path.is_file():
        raise A18Error(f"missing packets: {packets_path}")
    output = run_dir / f"solutions_{args.pass_name}.jsonl"
    attempts = run_dir / f"attempts_{args.pass_name}"
    output.parent.mkdir(parents=True, exist_ok=True)
    existing: dict[int, JSON] = {}
    if output.is_file():
        existing = {int(row["qid"]): row for row in _read_jsonl(output)}
    packets = _read_jsonl(packets_path)
    selected = [row for row in packets if row["candidates"] and int(row["qid"]) not in existing]
    if args.only_validated_from:
        source_path = run_dir / f"solutions_{args.only_validated_from}.jsonl"
        if not source_path.is_file():
            raise A18Error(f"missing prerequisite solutions: {source_path}")
        source = {int(row["qid"]): row for row in _read_jsonl(source_path)}
        eligible: set[int] = set()
        for packet in packets:
            qid = int(packet["qid"])
            if qid not in source:
                continue
            try:
                _validated_solution(packet, source[qid])
            except A18Error:
                continue
            eligible.add(qid)
        selected = [row for row in selected if int(row["qid"]) in eligible]
        print(
            f"validated_prerequisite={args.only_validated_from} eligible={len(eligible)}",
            flush=True,
        )
    if args.qids:
        wanted = {int(value) for value in args.qids.split(",") if value.strip()}
        selected = [row for row in selected if int(row["qid"]) in wanted]
    if args.limit:
        selected = selected[: args.limit]
    print(
        f"pass={args.pass_name} total={len(packets)} existing={len(existing)} "
        f"remaining={len(selected)}",
        flush=True,
    )
    if not selected:
        return 0
    attempts.mkdir(parents=True, exist_ok=True)
    solved_current = 0
    with output.open("a", encoding="utf-8") as handle:
        start = time.monotonic()
        for index, packet in enumerate(selected, start=1):
            qid = int(packet["qid"])
            prompt = _prompt(packet, args.pass_name)
            prompt_sha = _sha256_text(prompt)
            try:
                event = _ollama_generate(prompt, args)
                row = {
                    "qid": qid,
                    "pass": args.pass_name,
                    "prompt_sha256": prompt_sha,
                    "packet_sha256": _canonical_sha(packet),
                    "model_id": args.model,
                    "model_digest": MODEL_DIGEST,
                    **event,
                }
            except A18Error as error:
                row = {
                    "qid": qid,
                    "pass": args.pass_name,
                    "prompt_sha256": prompt_sha,
                    "packet_sha256": _canonical_sha(packet),
                    "model_id": args.model,
                    "model_digest": MODEL_DIGEST,
                    "error": str(error),
                }
            attempt_path = attempts / f"{qid:04d}.json"
            if attempt_path.exists():
                raise A18Error(f"attempt already exists: {attempt_path}")
            attempt_path.write_text(
                json.dumps(
                    {**row, "prompt": prompt},
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            solved_current += (row.get("solution") or {}).get("status") == "SOLVED"
            elapsed = time.monotonic() - start
            if index % 5 == 0 or index == len(selected):
                solved = sum(
                    (entry.get("solution") or {}).get("status") == "SOLVED"
                    for entry in existing.values()
                )
                solved += solved_current
                print(
                    f"{index}/{len(selected)} qid={qid} solved_seen={solved} "
                    f"avg={elapsed / index:.1f}s",
                    flush=True,
                )
    return 0


@dataclass(frozen=True)
class Quantity:
    value: Decimal
    dimension: str
    expression: str
    uids: frozenset[str]


def _float_expression(variable: str, uid: str, scale: int) -> str:
    leaf = f"float({variable}[{variable}['observation_uid'] == '{uid}']['value'].values[0])"
    if scale > 0:
        return f"({leaf} * {10**scale})"
    if scale < 0:
        return f"({leaf} / {10 ** abs(scale)})"
    return leaf


class ExpressionCompiler:
    def __init__(self, packet: JSON):
        self.packet = packet
        self.by_uid = {str(row["uid"]): row for row in packet["candidates"]}
        tables: dict[str, list[str]] = defaultdict(list)
        for row in packet["candidates"]:
            tables[str(row["table_uid"])].append(str(row["uid"]))
        self.table_variables = {
            table_uid: f"df{index}" for index, table_uid in enumerate(sorted(tables), start=1)
        }

    def compile(self, expression: str) -> Quantity:
        try:
            tree = ast.parse(expression, mode="eval")
        except SyntaxError as error:
            raise A18Error(f"invalid expression syntax: {error}") from error
        return self._node(tree.body)

    def _node(self, node: ast.AST) -> Quantity:
        if isinstance(node, ast.Call):
            return self._call(node)
        if isinstance(node, ast.BinOp):
            left, right = self._node(node.left), self._node(node.right)
            if isinstance(node.op, (ast.Add, ast.Sub)):
                self._same_dimension(left, right)
                symbol = "+" if isinstance(node.op, ast.Add) else "-"
                value = left.value + right.value if symbol == "+" else left.value - right.value
                return Quantity(
                    value,
                    left.dimension,
                    f"({left.expression} {symbol} {right.expression})",
                    left.uids | right.uids,
                )
            if isinstance(node.op, ast.Mult):
                dimension = self._multiply_dimension(left.dimension, right.dimension)
                return Quantity(
                    left.value * right.value,
                    dimension,
                    f"({left.expression} * {right.expression})",
                    left.uids | right.uids,
                )
            if isinstance(node.op, ast.Div):
                if right.value == 0:
                    raise A18Error("division by zero")
                dimension = "ratio" if left.dimension == right.dimension else "number"
                return Quantity(
                    left.value / right.value,
                    dimension,
                    f"({left.expression} / {right.expression})",
                    left.uids | right.uids,
                )
            raise A18Error(f"unsupported binary operator {node.op.__class__.__name__}")
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            value = self._node(node.operand)
            return Quantity(-value.value, value.dimension, f"(-{value.expression})", value.uids)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            self._validate_constant(Decimal(str(node.value)))
            return Quantity(Decimal(str(node.value)), "number", repr(node.value), frozenset())
        if isinstance(node, ast.Compare):
            return self._compare(node)
        raise A18Error(f"unsupported expression node {node.__class__.__name__}")

    def _call(self, node: ast.Call) -> Quantity:
        if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
            raise A18Error("expression calls an unsupported function")
        name = node.func.id
        if name == "obs":
            if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant):
                raise A18Error("obs() requires one UID string")
            uid = node.args[0].value
            if not isinstance(uid, str) or uid not in self.by_uid:
                raise A18Error(f"obs() UID is outside the packet: {uid!r}")
            row = self.by_uid[uid]
            try:
                raw = Decimal(str(row["value"]))
            except InvalidOperation as error:
                raise A18Error(f"observation {uid} is not decimal") from error
            scale = int(row["scale_exponent"] or 0)
            dimension = self._observation_dimension(str(row["value_kind"]))
            value = raw * (Decimal(10) ** scale) if dimension == "money" else raw
            variable = self.table_variables[str(row["table_uid"])]
            expression = _float_expression(variable, uid, scale if dimension == "money" else 0)
            return Quantity(value, dimension, expression, frozenset((uid,)))
        if name in {"mean", "sum_", "median", "max_", "min_"}:
            values = self._list_argument(node, name)
            self._all_same_dimension(values)
            numbers = [value.value for value in values]
            if name == "mean":
                result = sum(numbers) / Decimal(len(numbers))
                query = f"(sum([{','.join(v.expression for v in values)}]) / {len(values)})"
            elif name == "sum_":
                result = sum(numbers)
                query = f"sum([{','.join(v.expression for v in values)}])"
            elif name == "median":
                ordered = sorted(numbers)
                middle = len(ordered) // 2
                result = (
                    ordered[middle]
                    if len(ordered) % 2
                    else (ordered[middle - 1] + ordered[middle]) / Decimal(2)
                )
                query = f"float(pd.Series([{','.join(v.expression for v in values)}]).median())"
            elif name == "max_":
                result = max(numbers)
                query = f"max([{','.join(v.expression for v in values)}])"
            else:
                result = min(numbers)
                query = f"min([{','.join(v.expression for v in values)}])"
            return Quantity(
                result,
                values[0].dimension,
                query,
                frozenset().union(*(value.uids for value in values)),
            )
        if name == "abs_":
            if len(node.args) != 1:
                raise A18Error("abs_() requires one argument")
            value = self._node(node.args[0])
            return Quantity(
                abs(value.value), value.dimension, f"abs({value.expression})", value.uids
            )
        if name == "percent_change":
            if len(node.args) != 2:
                raise A18Error("percent_change() requires old,new")
            old, new = self._node(node.args[0]), self._node(node.args[1])
            self._same_dimension(old, new)
            if old.value == 0:
                raise A18Error("percent_change base is zero")
            return Quantity(
                ((new.value - old.value) / abs(old.value)) * Decimal(100),
                "percentage",
                f"((({new.expression} - {old.expression}) / abs({old.expression})) * 100)",
                old.uids | new.uids,
            )
        if name in {"argmax", "argmin", "select_at_argmax", "select_at_argmin"}:
            return self._arg_function(name, node)
        if name == "count_true":
            values = self._list_argument(node, name)
            if any(value.dimension != "boolean" for value in values):
                raise A18Error("count_true requires boolean conditions")
            return Quantity(
                Decimal(sum(value.value != 0 for value in values)),
                "count",
                f"sum([{','.join(v.expression for v in values)}])",
                frozenset().union(*(value.uids for value in values)),
            )
        if name in {"sum_if", "mean_if"}:
            return self._conditional_aggregate(name, node)
        raise A18Error(f"unsupported call {name}")

    def _list_argument(self, node: ast.Call, name: str) -> list[Quantity]:
        if len(node.args) != 1 or not isinstance(node.args[0], (ast.List, ast.Tuple)):
            raise A18Error(f"{name} requires one list argument")
        values = [self._node(value) for value in node.args[0].elts]
        if not values:
            raise A18Error(f"{name} list cannot be empty")
        return values

    def _arg_function(self, name: str, node: ast.Call) -> Quantity:
        if len(node.args) != 1 or not isinstance(node.args[0], (ast.List, ast.Tuple)):
            raise A18Error(f"{name} requires one list argument")
        items: list[tuple[str, Quantity, Quantity | None]] = []
        for item in node.args[0].elts:
            if not isinstance(item, (ast.Tuple, ast.List)):
                raise A18Error(f"{name} item must be a tuple")
            required = 2
            if len(item.elts) != required:
                raise A18Error(f"{name} item must contain two values")
            if name.startswith("select_at_"):
                rank, value = self._node(item.elts[0]), self._node(item.elts[1])
                items.append((str(len(items)), rank, value))
            else:
                label_node = item.elts[0]
                if not isinstance(label_node, ast.Constant) or not isinstance(
                    label_node.value, (str, int)
                ):
                    raise A18Error(f"{name} label must be a string or integer")
                items.append((str(label_node.value), self._node(item.elts[1]), None))
        if not items:
            raise A18Error(f"{name} list cannot be empty")
        self._all_same_dimension([item[1] for item in items])
        choose_max = name.endswith("max")
        chosen = (max if choose_max else min)(items, key=lambda item: item[1].value)
        all_uids = frozenset().union(
            *(rank.uids | (value.uids if value else frozenset()) for _, rank, value in items)
        )
        if name.startswith("select_at_"):
            values = [item[2] for item in items]
            assert all(value is not None for value in values)
            self._all_same_dimension([value for value in values if value is not None])
            selected = chosen[2]
            assert selected is not None
            pairs = ",".join(
                f"({rank.expression},{value.expression})"
                for _, rank, value in items
                if value is not None
            )
            function = "max" if choose_max else "min"
            query = f"{function}([{pairs}], key=lambda x: x[0])[1]"
            return Quantity(selected.value, selected.dimension, query, all_uids)
        label = chosen[0]
        if not re.fullmatch(r"-?\d+(?:\.\d+)?", label):
            raise A18Error("argmax/argmin output label must be numeric for submission")
        pairs = ",".join(f"({rank.expression},{label_value!r})" for label_value, rank, _ in items)
        function = "max" if choose_max else "min"
        query = f"float({function}([{pairs}], key=lambda x: x[0])[1])"
        return Quantity(Decimal(label), "year", query, all_uids)

    def _conditional_aggregate(self, name: str, node: ast.Call) -> Quantity:
        if len(node.args) != 1 or not isinstance(node.args[0], (ast.List, ast.Tuple)):
            raise A18Error(f"{name} requires one list argument")
        pairs: list[tuple[Quantity, Quantity]] = []
        for item in node.args[0].elts:
            if not isinstance(item, (ast.Tuple, ast.List)) or len(item.elts) != 2:
                raise A18Error(f"{name} item must be (condition,value)")
            condition, value = self._node(item.elts[0]), self._node(item.elts[1])
            if condition.dimension != "boolean":
                raise A18Error(f"{name} condition must be boolean")
            pairs.append((condition, value))
        selected = [value for condition, value in pairs if condition.value != 0]
        if not selected:
            raise A18Error(f"{name} selects no value")
        self._all_same_dimension([value for _, value in pairs])
        result = sum(value.value for value in selected)
        query_values = ",".join(
            f"({value.expression} if {condition.expression} else None)"
            for condition, value in pairs
        )
        if name == "mean_if":
            result /= Decimal(len(selected))
            query = (
                f"(sum(x for x in [{query_values}] if x is not None) / "
                f"sum(x is not None for x in [{query_values}]))"
            )
        else:
            query = f"sum(x for x in [{query_values}] if x is not None)"
        return Quantity(
            result,
            selected[0].dimension,
            query,
            frozenset().union(*(condition.uids | value.uids for condition, value in pairs)),
        )

    def _compare(self, node: ast.Compare) -> Quantity:
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise A18Error("only single comparisons are supported")
        left, right = self._node(node.left), self._node(node.comparators[0])
        if left.dimension != right.dimension and "number" not in {left.dimension, right.dimension}:
            raise A18Error("comparison dimensions differ")
        operator = node.ops[0]
        operations: list[tuple[type[ast.cmpop], str, bool]] = [
            (ast.Gt, ">", left.value > right.value),
            (ast.GtE, ">=", left.value >= right.value),
            (ast.Lt, "<", left.value < right.value),
            (ast.LtE, "<=", left.value <= right.value),
            (ast.Eq, "==", left.value == right.value),
        ]
        for kind, symbol, result in operations:
            if isinstance(operator, kind):
                return Quantity(
                    Decimal(int(result)),
                    "boolean",
                    f"({left.expression} {symbol} {right.expression})",
                    left.uids | right.uids,
                )
        raise A18Error("unsupported comparison")

    def evidence(self, used_uids: Iterable[str]) -> list[JSON]:
        by_table: dict[str, list[str]] = defaultdict(list)
        for uid in sorted(set(used_uids)):
            by_table[str(self.by_uid[uid]["table_uid"])].append(uid)
        return [
            {
                "variable": self.table_variables[table_uid],
                "table_uid": table_uid,
                "observation_uids": uids,
            }
            for table_uid, uids in sorted(
                by_table.items(), key=lambda item: self.table_variables[item[0]]
            )
        ]

    def _validate_constant(self, value: Decimal) -> None:
        allowed = {Decimal(0), Decimal(1), Decimal(100)}
        for raw in _NUMBER.findall(str(self.packet["question"])):
            try:
                allowed.add(Decimal(raw.replace(",", ".")))
            except InvalidOperation:
                pass
        if value not in allowed:
            raise A18Error(f"numeric constant {value} is not present in the question")

    @staticmethod
    def _observation_dimension(kind: str) -> str:
        if kind == "money":
            return "money"
        if kind in {"percentage", "percent"}:
            return "percentage"
        if kind in {"count", "integer"}:
            return "count"
        return "number"

    @staticmethod
    def _same_dimension(left: Quantity, right: Quantity) -> None:
        if left.dimension != right.dimension:
            raise A18Error(f"dimension mismatch: {left.dimension} vs {right.dimension}")

    def _all_same_dimension(self, values: Sequence[Quantity]) -> None:
        for value in values[1:]:
            self._same_dimension(values[0], value)

    @staticmethod
    def _multiply_dimension(left: str, right: str) -> str:
        if left == "number":
            return right
        if right == "number":
            return left
        if left == "ratio":
            return right
        if right == "ratio":
            return left
        return "number"


def _apply_transform(quantity: Quantity, transform: str) -> tuple[Decimal, str]:
    value, query = quantity.value, quantity.expression
    if transform.startswith("MONEY_") or transform == "MONEY_VND":
        if quantity.dimension != "money":
            raise A18Error(f"{transform} requires money, got {quantity.dimension}")
        divisors = {
            "MONEY_VND": Decimal(1),
            "MONEY_MILLION_VND": Decimal(10) ** 6,
            "MONEY_BILLION_VND": Decimal(10) ** 9,
            "MONEY_TRILLION_VND": Decimal(10) ** 12,
        }
        divisor = divisors[transform]
        if divisor != 1:
            value /= divisor
            query = f"({query} / {int(divisor)})"
    elif transform == "PERCENT_FROM_RATIO":
        if quantity.dimension not in {"ratio", "number"}:
            raise A18Error("PERCENT_FROM_RATIO requires a ratio")
        value *= Decimal(100)
        query = f"({query} * 100)"
    elif transform == "PERCENT_NATIVE":
        if quantity.dimension != "percentage":
            raise A18Error("PERCENT_NATIVE requires a percentage observation")
    elif transform == "RATIO":
        if quantity.dimension not in {"ratio", "number"}:
            raise A18Error("RATIO requires a ratio")
    elif transform == "YEAR":
        if quantity.dimension != "year":
            raise A18Error("YEAR transform requires argmax/argmin output")
    elif transform == "COUNT":
        if quantity.dimension != "count":
            raise A18Error("COUNT transform requires count_true output")
    elif transform == "RAW_NUMBER":
        if quantity.dimension not in {"number", "percentage", "ratio"}:
            raise A18Error("RAW_NUMBER received an incompatible dimension")
    else:
        raise A18Error(f"unknown output transform {transform}")
    return value, query


def _canonicalize_expression(expression: str, transform: str) -> tuple[str, tuple[str, ...]]:
    """Remove only a redundant top-level unit conversion already owned by transform."""

    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        return expression, ()
    body = tree.body
    money_divisors = {
        "MONEY_MILLION_VND": Decimal(10) ** 6,
        "MONEY_BILLION_VND": Decimal(10) ** 9,
        "MONEY_TRILLION_VND": Decimal(10) ** 12,
    }
    expected_divisor = money_divisors.get(transform)
    if (
        expected_divisor is not None
        and isinstance(body, ast.BinOp)
        and isinstance(body.op, ast.Div)
        and isinstance(body.right, ast.Constant)
        and isinstance(body.right.value, (int, float))
        and Decimal(str(body.right.value)) == expected_divisor
    ):
        return ast.unparse(body.left), ("REMOVE_REDUNDANT_MONEY_UNIT_DIVISOR",)
    if (
        transform == "PERCENT_FROM_RATIO"
        and isinstance(body, ast.BinOp)
        and isinstance(body.op, ast.Mult)
    ):
        operands = ((body.left, body.right), (body.right, body.left))
        for value, constant in operands:
            if (
                isinstance(constant, ast.Constant)
                and isinstance(constant.value, (int, float))
                and Decimal(str(constant.value)) == Decimal(100)
            ):
                return ast.unparse(value), ("REMOVE_REDUNDANT_PERCENT_MULTIPLIER",)
    return expression, ()


def _validated_solution(packet: JSON, row: JSON) -> JSON:
    solution = row.get("solution")
    if not isinstance(solution, dict) or solution.get("status") != "SOLVED":
        raise A18Error("model abstained or returned no solution")
    if solution.get("confidence") not in {"HIGH", "MEDIUM"}:
        raise A18Error("model confidence is LOW")
    expression = solution.get("expression")
    transform = solution.get("output_transform")
    if not isinstance(expression, str) or not expression.strip():
        raise A18Error("solution expression is empty")
    if transform not in _OUTPUT_TRANSFORMS:
        raise A18Error("solution output_transform is invalid")
    canonical_expression, normalizations = _canonicalize_expression(expression, str(transform))
    compiler = ExpressionCompiler(packet)
    with localcontext() as context:
        context.prec = 50
        quantity = compiler.compile(canonical_expression)
        answer, query = _apply_transform(quantity, str(transform))
    declared = solution.get("used_observation_uids")
    if not isinstance(declared, list) or set(declared) != set(quantity.uids):
        raise A18Error("declared UID set differs from compiled expression")
    if not quantity.uids:
        raise A18Error("solution uses no A6 observations")
    used_rows = [compiler.by_uid[uid] for uid in quantity.uids]
    used_entities = sorted({str(value["ticker"]) for value in used_rows})
    declared_entities = sorted(str(value) for value in solution.get("entities") or [])
    if declared_entities != used_entities:
        raise A18Error("declared entities differ from compiled UID scope")
    if not set(used_entities) <= {str(value) for value in packet.get("tickers") or []}:
        raise A18Error("compiled UID entity is outside the question scope")
    operation = str(solution.get("operation") or "UNKNOWN")
    if (
        operation == "AVG"
        and len(packet.get("tickers") or []) > 1
        and set(used_entities) != {str(value) for value in packet["tickers"]}
    ):
        raise A18Error("AVG does not cover every entity listed in the question")
    used_periods = sorted({str(value["period"]) for value in used_rows if value.get("period")})
    declared_periods = sorted(str(value) for value in solution.get("periods") or [])
    if declared_periods != used_periods:
        raise A18Error("declared periods differ from compiled UID scope")
    used_bases = sorted({str(value["basis"]) for value in used_rows if value.get("basis")})
    declared_basis = solution.get("basis")
    expected_basis: str | None = used_bases[0] if len(used_bases) == 1 else "mixed"
    if declared_basis != expected_basis:
        raise A18Error("declared basis differs from compiled UID scope")
    if not math.isfinite(float(answer)):
        raise A18Error("compiled answer is not finite")
    return {
        "answer": float(answer),
        "answer_decimal": format(answer, "f"),
        "pandas_query": query,
        "pandas_query_sha256": _sha256_text(query),
        "used_observation_uids": sorted(quantity.uids),
        "evidence": compiler.evidence(quantity.uids),
        "operation": operation,
        "entities": declared_entities,
        "periods": declared_periods,
        "basis": solution.get("basis"),
        "output_transform": transform,
        "confidence": solution.get("confidence"),
        "expression": canonical_expression,
        "raw_expression": expression,
        "expression_normalizations": list(normalizations),
        "expression_sha256": _sha256_text(canonical_expression),
    }


def _agreement(left: JSON, right: JSON) -> list[str]:
    mismatches: list[str] = []
    for field in (
        "answer_decimal",
        "used_observation_uids",
        "operation",
        "entities",
        "periods",
        "basis",
        "output_transform",
    ):
        if left[field] != right[field]:
            mismatches.append(field)
    return mismatches


def adjudicate(args: argparse.Namespace) -> int:
    run_dir = args.run.resolve()
    packets = {int(row["qid"]): row for row in _read_jsonl(run_dir / "packets.jsonl")}
    pass_a = {int(row["qid"]): row for row in _read_jsonl(run_dir / "solutions_a.jsonl")}
    pass_b = {int(row["qid"]): row for row in _read_jsonl(run_dir / "solutions_b.jsonl")}
    accepted: list[JSON] = []
    decisions: list[JSON] = []
    for qid in sorted(packets):
        packet = packets[qid]
        try:
            left = _validated_solution(packet, pass_a[qid])
            right = _validated_solution(packet, pass_b[qid])
            mismatches = _agreement(left, right)
            if mismatches:
                raise A18Error(f"independent passes disagree: {mismatches}")
            accepted.append(
                {
                    "qid": qid,
                    "question_sha256": packet["question_sha256"],
                    "expected_answer": left["answer"],
                    "rationale": (
                        "Two constrained Qwen2.5-14B passes selected the same A6 "
                        "observation set, semantic scope and compiled value; the numeric "
                        "answer is compiler-derived, not model-generated."
                    ),
                    "source": {
                        "kind": "A6_CONSTRAINED_MODEL",
                        "operation": left["operation"],
                        "evidence": left["evidence"],
                        "pandas_query": left["pandas_query"],
                        "model_id": MODEL_ID,
                        "model_digest": MODEL_DIGEST,
                        "pass_a_sha256": _canonical_sha(pass_a[qid]),
                        "pass_b_sha256": _canonical_sha(pass_b[qid]),
                        "expression_sha256": left["expression_sha256"],
                        "agreement_fields": [
                            "answer_decimal",
                            "used_observation_uids",
                            "operation",
                            "entities",
                            "periods",
                            "basis",
                            "output_transform",
                        ],
                    },
                }
            )
            decisions.append({"qid": qid, "decision": "ACCEPT", "compiled": left})
        except (A18Error, KeyError) as error:
            decisions.append({"qid": qid, "decision": "REJECT", "reason": str(error)})
    if len(accepted) < args.min_accepted:
        raise A18Error(
            f"accepted {len(accepted)} is below the predeclared minimum {args.min_accepted}"
        )
    manifest = {
        "schema_version": "1.0",
        "patch_id": args.patch_id,
        "strategy": "SAFE_3818_PLUS_A18_ABSTENTION_RECOVERY_WITH_3770_RETRIEVAL",
        "identities": {
            "raw_snapshot_id": "ca033190f2e9e99f",
            "a6_build_id": "c6887fb633374fad",
            "retrieval_index_id": "872ccb0dda9a2bb6",
            "answer_submission_id": 3818,
            "answer_zip_sha256": BASELINE_SHA256,
            "retrieval_submission_id": 3770,
            "retrieval_zip_sha256": RETRIEVAL_OWNER_SHA256,
            "semantic_v3_zip_sha256": SEMANTIC_V3_SHA256,
            "a6_silver_db_sha256": A6_SHA256,
            "retrieval_db_sha256": RETRIEVAL_SHA256,
        },
        "policy": {
            "expected_records": 1012,
            "expected_baseline_emitted": 647,
            "expected_output_emitted": 647 + len(accepted),
            "expected_corrections": 0,
            "expected_fills": len(accepted),
            "table_cap": 10,
            "p0_enabled": False,
            "model_gold_used": False,
            "semantic_v3_promoted": False,
            "fail_closed": True,
        },
        "model_policy": {
            "model_id": MODEL_ID,
            "model_digest": MODEL_DIGEST,
            "role": "CONSTRAINED_SEMANTIC_PLANNER_ONLY",
            "numeric_answer_generated_by_model": False,
            "model_gold_read": False,
            "independent_passes_required": 2,
        },
        "patches": [{"decision": "FILL", **patch} for patch in accepted],
    }
    _write_json(
        run_dir / "adjudication_report.json",
        {
            "accepted": len(accepted),
            "rejected": len(decisions) - len(accepted),
            "minimum": args.min_accepted,
            "decisions": decisions,
        },
    )
    _write_json(args.manifest.resolve(), manifest)
    print(f"accepted={len(accepted)} rejected={len(decisions) - len(accepted)}")
    print(f"manifest={args.manifest}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)
    prep = subparsers.add_parser("prepare")
    prep.add_argument("--out", type=Path, required=True)
    prep.add_argument("--max-per-group", type=int, default=10)
    prep.add_argument("--max-candidates", type=int, default=120)
    prep.set_defaults(func=prepare)

    inference = subparsers.add_parser("solve")
    inference.add_argument("--run", type=Path, required=True)
    inference.add_argument("--pass", dest="pass_name", choices=("a", "b"), required=True)
    inference.add_argument("--model", default=MODEL_ID)
    inference.add_argument("--url", default="http://127.0.0.1:11434")
    inference.add_argument("--seed", type=int, default=0)
    inference.add_argument("--num-ctx", type=int, default=32768)
    inference.add_argument("--max-tokens", type=int, default=768)
    inference.add_argument("--timeout", type=float, default=600.0)
    inference.add_argument("--keep-alive", default="30m")
    inference.add_argument("--limit", type=int, default=0)
    inference.add_argument("--qids", default="")
    inference.add_argument("--only-validated-from", choices=("a", "b"))
    inference.set_defaults(func=solve)

    judge = subparsers.add_parser("adjudicate")
    judge.add_argument("--run", type=Path, required=True)
    judge.add_argument("--manifest", type=Path, required=True)
    judge.add_argument("--patch-id", default="a18-abstention-recovery-v1")
    judge.add_argument("--min-accepted", type=int, default=170)
    judge.set_defaults(func=adjudicate)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.func(args))
    except A18Error as error:
        print(f"BLOCKED: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
