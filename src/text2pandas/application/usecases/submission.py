"""Đóng gói bài nộp + kiểm tra + chạy lại trong môi trường sạch.

Module này cố tình được viết TRƯỚC khi engine trả lời tốt. Một pipeline xuất
sắc mà đóng gói sai cấu trúc ZIP thì không được chấm, và lỗi đó rẻ để loại bỏ
sớm, đắt để phát hiện muộn.

Hai tham số thăm dò:
  `doc_id_variant` : 'stripped' (khớp ví dụ BTC) | 'literal' (khớp câu chữ)
  `locator_base`   : 1 | 0
Cả hai đều chưa được xác nhận. Chúng là **tham số**, không phải hằng số nằm
rải rác trong code — để một lượt nộp public phân định được cả hai.
"""

from __future__ import annotations

import io
import json
import math
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from text2pandas.application.usecases.answer import AnswerResult
from text2pandas.infrastructure.sandbox.query import (
    QuerySafetyError,
    execute_query,
    validate_query,
)

__all__ = ["SubmissionConfig", "ValidationReport", "build_submission", "validate_zip", "replay_zip"]

_PY_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_LOCATOR = re.compile(r"^(?P<doc>[^|]+)\|(?P<line>[1-9]\d*)$")
_CSV_PATH = re.compile(r"^data/[^/]+\.csv$")
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)
_REQUIRED_FIELDS = {
    "id",
    "question",
    "answer",
    "relevant_docs",
    "relevant_tables",
    "evidence",
    "pandas_query",
}
_EVIDENCE_FIELDS = {"variable", "csv_path"}
_MAX_MEMBER_BYTES = 100 * 1024 * 1024


@dataclass(slots=True)
class SubmissionConfig:
    doc_id_variant: str = "stripped"  # 'stripped' | 'literal'
    locator_base: int = 1  # 1 | 0
    json_name: str = "submission.json"


@dataclass(slots=True)
class ValidationReport:
    n_records: int
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _apply_variants(res: AnswerResult, cfg: SubmissionConfig) -> tuple[list[str], list[str]]:
    docs = [
        d + "_extracted" if cfg.doc_id_variant == "literal" else d
        for d in res.relevant_docs
    ]
    tables: list[str] = []
    for loc in res.relevant_tables:
        doc, _, line = loc.rpartition("|")
        if cfg.doc_id_variant == "literal":
            doc += "_extracted"
        n = int(line) - (1 - cfg.locator_base)
        tables.append(f"{doc}|{n}")
    return docs, tables


def build_submission(
    results: list[AnswerResult],
    questions: dict[int, str],
    out_dir: Path,
    cfg: SubmissionConfig,
) -> Path:
    """Ghi cây thư mục bài nộp rồi nén. Trả về đường dẫn ZIP."""
    out_dir.mkdir(parents=True, exist_ok=True)
    data_dir = out_dir / "data"
    data_dir.mkdir(exist_ok=True)

    records = []
    for res in sorted(results, key=lambda item: item.qid):
        docs, tables = _apply_variants(res, cfg)
        records.append(
            {
                "id": res.qid,
                "question": questions.get(res.qid, ""),
                # C19: phải phủ MỌI id. Khi không rút được số vẫn phải có bản ghi;
                # 0.0 là giá trị giữ chỗ hợp lệ kiểu float, không phải câu trả lời.
                "answer": float(res.answer) if res.answer is not None else 0.0,
                "relevant_docs": docs,
                "relevant_tables": tables,
                "evidence": res.evidence if res.has_csv else [],
                "pandas_query": res.pandas_query,
            }
        )

    json_bytes = json.dumps(records, ensure_ascii=False, indent=1).encode("utf-8")
    (out_dir / cfg.json_name).write_bytes(json_bytes)

    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "x", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        _write_deterministic(z, cfg.json_name, json_bytes)
        for csv_file in sorted(data_dir.iterdir()):
            if not csv_file.is_file() or csv_file.suffix.lower() != ".csv":
                continue
            _write_deterministic(z, f"data/{csv_file.name}", csv_file.read_bytes())
    return zip_path


def _write_deterministic(archive: zipfile.ZipFile, name: str, payload: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    info.create_system = 3
    archive.writestr(info, payload)


def validate_zip(
    zip_path: Path,
    expected: set[int] | Mapping[int, str],
    *,
    corpus_root: Path | None = None,
    strict: bool = True,
) -> ValidationReport:
    """Validate the exact submission, grounding, and execution contracts."""

    rep = ValidationReport(0)
    expected_ids = set(expected)
    expected_questions = expected if isinstance(expected, Mapping) else None
    try:
        archive = zipfile.ZipFile(zip_path)
    except (OSError, zipfile.BadZipFile) as error:
        rep.errors.append(f"C13: ZIP không hợp lệ — {error}")
        return rep
    with archive as z:
        names = z.namelist()
        if len(names) != len(set(names)):
            rep.errors.append("C13: ZIP chứa member trùng tên")
        for name in names:
            parts = Path(name).parts
            if name.startswith(("/", "\\")) or "\\" in name or ".." in parts:
                rep.errors.append(f"C13: đường dẫn ZIP không an toàn: {name!r}")
        for info in z.infolist():
            if info.is_dir() or (
                not info.filename.lower().endswith(".json")
                and not info.filename.lower().endswith(".csv")
            ):
                rep.errors.append(f"C13: member không được phép: {info.filename!r}")
            if info.file_size > _MAX_MEMBER_BYTES:
                rep.errors.append(
                    f"C13: member vượt giới hạn {_MAX_MEMBER_BYTES} bytes: {info.filename!r}"
                )

        jsons = [n for n in names if n.lower().endswith(".json")]
        if len(jsons) != 1:
            rep.errors.append(f"C15: ZIP phải chứa đúng 1 file .json, thấy {len(jsons)}")
            return rep
        json_name = jsons[0]
        if "/" in json_name:
            rep.errors.append(f"C13: .json phải ở cấp ngoài cùng, thấy '{json_name}'")
        for n in names:
            if n != json_name and not n.startswith("data/"):
                rep.errors.append(f"C13: '{n}' không nằm trong data/ ở cấp ngoài cùng")

        try:
            records = json.loads(z.read(json_name).decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            rep.errors.append(f"C11: JSON không hợp lệ — {exc!r}")
            return rep
        if not isinstance(records, list):
            rep.errors.append("C11: gốc JSON phải là mảng")
            return rep
        rep.n_records = len(records)

        members = set(names)
        csv_members = {name for name in members if name.lower().endswith(".csv")}
        referenced_csvs: set[str] = set()
        seen_ids: set[int] = set()
        document_cache: dict[str, list[str] | None] = {}

        for i, r in enumerate(records):
            if not isinstance(r, dict):
                rep.errors.append(f"C11 [{i}]: record phải là object")
                continue
            tag = f"[{i}] id={r.get('id')}"
            missing = _REQUIRED_FIELDS - r.keys()
            if missing:
                rep.errors.append(f"C11 {tag}: thiếu trường {sorted(missing)}")
            extra = r.keys() - _REQUIRED_FIELDS
            if extra:
                message = f"C11 {tag}: có trường thừa {sorted(extra)}"
                (rep.errors if strict else rep.warnings).append(message)
            if not isinstance(r.get("id"), int):
                rep.errors.append(f"C11 {tag}: id phải là integer")
            elif r["id"] in seen_ids:
                rep.errors.append(f"C19 {tag}: id trùng")
            else:
                seen_ids.add(r["id"])
            if not isinstance(r.get("question"), str):
                rep.errors.append(f"C11 {tag}: question phải là string")
            elif expected_questions is not None and r.get("id") in expected_questions:
                if r["question"] != expected_questions[r["id"]]:
                    rep.errors.append(f"C19 {tag}: question không khớp dữ liệu gốc")
            if not isinstance(r.get("answer"), (int, float)) or isinstance(
                r.get("answer"), bool
            ):
                rep.errors.append(f"C11 {tag}: answer phải là số")
            elif not math.isfinite(float(r["answer"])):
                rep.errors.append(f"C11 {tag}: answer phải là số hữu hạn")

            docs = r.get("relevant_docs")
            tables = r.get("relevant_tables")
            evidence = r.get("evidence")
            query = r.get("pandas_query")
            if not isinstance(docs, list) or not all(isinstance(value, str) for value in docs):
                rep.errors.append(f"C11 {tag}: relevant_docs phải là list[string]")
                docs = []
            if len(docs) != len(set(docs)):
                rep.errors.append(f"C20 {tag}: relevant_docs chứa phần tử trùng")
            if not isinstance(tables, list) or not all(isinstance(value, str) for value in tables):
                rep.errors.append(f"C11 {tag}: relevant_tables phải là list[string]")
                tables = []
            if len(tables) != len(set(tables)):
                rep.errors.append(f"C20 {tag}: relevant_tables chứa phần tử trùng")
            if not isinstance(evidence, list):
                rep.errors.append(f"C11 {tag}: evidence phải là list")
                evidence = []
            if not isinstance(query, str):
                rep.errors.append(f"C11 {tag}: pandas_query phải là string")
                query = ""

            for doc in docs:
                if corpus_root is not None:
                    _validate_document(doc, corpus_root, document_cache, rep, tag)

            for loc in tables:
                match = _LOCATOR.fullmatch(loc)
                if not match:
                    rep.errors.append(f"C20 {tag}: locator sai định dạng: {loc!r}")
                    continue
                if corpus_root is not None:
                    lines = _validate_document(
                        match["doc"], corpus_root, document_cache, rep, tag
                    )
                    line = int(match["line"])
                    if lines is not None and not (1 <= line <= len(lines)):
                        rep.errors.append(f"C20 {tag}: locator vượt số dòng: {loc!r}")
                    elif lines is not None and not lines[line - 1].lstrip().startswith("<table"):
                        rep.errors.append(f"C20 {tag}: locator không trỏ dòng mở table: {loc!r}")

            names_seen: set[str] = set()
            for ev in evidence:
                if not isinstance(ev, dict):
                    rep.errors.append(f"C12 {tag}: evidence item phải là object")
                    continue
                if set(ev) != _EVIDENCE_FIELDS:
                    rep.errors.append(
                        f"C12 {tag}: evidence phải có đúng trường {sorted(_EVIDENCE_FIELDS)}"
                    )
                v, p = ev.get("variable", ""), ev.get("csv_path", "")
                if not _PY_NAME.match(v):
                    rep.errors.append(f"C12 {tag}: '{v}' không phải tên biến Python hợp lệ")
                if v in names_seen:
                    rep.errors.append(f"C12 {tag}: biến '{v}' bị trùng")
                names_seen.add(v)
                if not isinstance(p, str) or not _CSV_PATH.fullmatch(p):
                    rep.errors.append(f"C14 {tag}: csv_path sai định dạng: {p!r}")
                if p and p not in members:
                    rep.errors.append(f"C14 {tag}: '{p}' không có trong ZIP")
                if isinstance(p, str) and p:
                    referenced_csvs.add(p)

            if evidence and not query:
                rep.errors.append(f"C12 {tag}: có evidence nhưng pandas_query rỗng")
            elif query and not evidence:
                rep.errors.append(f"C12 {tag}: có pandas_query nhưng evidence rỗng")
            elif evidence and query:
                try:
                    validate_query(query, names_seen)
                except QuerySafetyError as error:
                    rep.errors.append(f"C12 {tag}: {error}")

        if missing_ids := expected_ids - seen_ids:
            rep.errors.append(
                f"C19: thiếu {len(missing_ids)} câu hỏi, ví dụ {sorted(missing_ids)[:5]}"
            )
        if unexpected_ids := seen_ids - expected_ids:
            rep.errors.append(
                f"C19: thừa {len(unexpected_ids)} id, ví dụ {sorted(unexpected_ids)[:5]}"
            )
        orphan_csvs = csv_members - referenced_csvs
        if orphan_csvs:
            message = f"C14: {len(orphan_csvs)} CSV không được evidence tham chiếu"
            (rep.errors if strict else rep.warnings).append(message)
    return rep


def _validate_document(
    doc_id: str,
    corpus_root: Path,
    cache: dict[str, list[str] | None],
    report: ValidationReport,
    tag: str,
) -> list[str] | None:
    canonical = doc_id.removesuffix("_extracted")
    if canonical in cache:
        return cache[canonical]
    match = re.match(r"^(?P<ticker>[^_]+)_financial_statements_(?P<year>\d{4})_", canonical)
    if not match:
        report.errors.append(f"C20 {tag}: document id sai định dạng: {doc_id!r}")
        cache[canonical] = None
        return None
    path = (
        corpus_root
        / match["ticker"]
        / match["year"]
        / canonical
        / f"{canonical}_extracted.txt"
    )
    if not path.is_file():
        report.errors.append(f"C20 {tag}: document không tồn tại: {doc_id!r}")
        cache[canonical] = None
        return None
    cache[canonical] = path.read_text(encoding="utf-8").splitlines()
    return cache[canonical]


def replay_zip(zip_path: Path, workdir: Path, tolerance: float = 1e-6) -> dict[str, int]:
    """Giải nén vào thư mục sạch, chạy lại MỌI pandas_query, so với answer.

    Đây là phép kiểm C10. Nếu bước này không đạt thì Execution Accuracy sẽ
    hỏng ngoài đời thật — và ta biết trước khi nộp, không phải sau.
    """
    import pandas as pd

    _ = workdir  # compatibility with the former extract-to-disk API
    archive = zipfile.ZipFile(zip_path)
    json_name = next(name for name in archive.namelist() if name.endswith(".json"))
    records = json.loads(archive.read(json_name))

    stat = {"total": 0, "executed": 0, "matched": 0, "no_evidence": 0, "error": 0}
    cache: dict[str, "pd.DataFrame"] = {}
    for r in records:
        stat["total"] += 1
        ev = r.get("evidence") or []
        if not ev:
            stat["no_evidence"] += 1
            continue
        env: dict[str, object] = {}
        try:
            for e in ev:
                p = e["csv_path"]
                if p not in cache:
                    cache[p] = pd.read_csv(io.BytesIO(archive.read(p)))
                env[e["variable"]] = cache[p]
            value = execute_query(r["pandas_query"], env)
            stat["executed"] += 1
            expected = r["answer"]
            if abs(value - float(expected)) <= tolerance * max(1.0, abs(float(expected))):
                stat["matched"] += 1
        except Exception:  # noqa: BLE001
            stat["error"] += 1
    archive.close()
    return stat
