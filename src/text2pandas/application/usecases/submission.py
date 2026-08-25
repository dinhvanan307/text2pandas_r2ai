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

import json
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from text2pandas.application.usecases.answer import AnswerResult, write_long_csv

__all__ = ["SubmissionConfig", "ValidationReport", "build_submission", "validate_zip", "replay_zip"]

_PY_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


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
    for res in results:
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

    (out_dir / cfg.json_name).write_text(
        json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8"
    )

    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    zip_path.unlink(missing_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.write(out_dir / cfg.json_name, cfg.json_name)
        for csv_file in sorted(data_dir.iterdir()):
            z.write(csv_file, f"data/{csv_file.name}")
    return zip_path


def validate_zip(zip_path: Path, expected_ids: set[int]) -> ValidationReport:
    """Kiểm mọi ràng buộc C11–C15, C19 trực tiếp trên nội dung ZIP."""
    rep = ValidationReport(0)
    with zipfile.ZipFile(zip_path) as z:
        names = z.namelist()

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
        seen_ids: set[int] = set()
        required = {"id", "question", "answer", "relevant_docs",
                    "relevant_tables", "evidence", "pandas_query"}

        for i, r in enumerate(records):
            tag = f"[{i}] id={r.get('id')}"
            missing = required - r.keys()
            if missing:
                rep.errors.append(f"C11 {tag}: thiếu trường {sorted(missing)}")
            extra = r.keys() - required
            if extra:
                rep.warnings.append(f"{tag}: có trường thừa {sorted(extra)}")
            if not isinstance(r.get("id"), int):
                rep.errors.append(f"C11 {tag}: id phải là integer")
            elif r["id"] in seen_ids:
                rep.errors.append(f"C19 {tag}: id trùng")
            else:
                seen_ids.add(r["id"])
            if not isinstance(r.get("answer"), (int, float)) or isinstance(
                r.get("answer"), bool
            ):
                rep.errors.append(f"C11 {tag}: answer phải là số")

            for loc in r.get("relevant_tables", []):
                if "|" not in loc:
                    rep.errors.append(f"C20 {tag}: locator '{loc}' thiếu dấu |")

            names_seen: set[str] = set()
            for ev in r.get("evidence", []):
                v, p = ev.get("variable", ""), ev.get("csv_path", "")
                if not _PY_NAME.match(v):
                    rep.errors.append(f"C12 {tag}: '{v}' không phải tên biến Python hợp lệ")
                if v in names_seen:
                    rep.errors.append(f"C12 {tag}: biến '{v}' bị trùng")
                names_seen.add(v)
                if v and v not in (r.get("pandas_query") or ""):
                    rep.errors.append(f"C12 {tag}: '{v}' không xuất hiện trong pandas_query")
                if not p.startswith("data/"):
                    rep.errors.append(f"C14 {tag}: csv_path '{p}' không bắt đầu bằng data/")
                if ".." in p:
                    rep.errors.append(f"C14 {tag}: csv_path '{p}' thoát khỏi data/")
                if p and p not in members:
                    rep.errors.append(f"C14 {tag}: '{p}' không có trong ZIP")

        if missing_ids := expected_ids - seen_ids:
            rep.errors.append(
                f"C19: thiếu {len(missing_ids)} câu hỏi, ví dụ {sorted(missing_ids)[:5]}"
            )
    return rep


def replay_zip(zip_path: Path, workdir: Path, tolerance: float = 1e-6) -> dict[str, int]:
    """Giải nén vào thư mục sạch, chạy lại MỌI pandas_query, so với answer.

    Đây là phép kiểm C10. Nếu bước này không đạt thì Execution Accuracy sẽ
    hỏng ngoài đời thật — và ta biết trước khi nộp, không phải sau.
    """
    import shutil

    import pandas as pd

    if workdir.exists():
        shutil.rmtree(workdir)
    workdir.mkdir(parents=True)
    with zipfile.ZipFile(zip_path) as z:
        z.extractall(workdir)

    json_name = next(p for p in workdir.iterdir() if p.suffix == ".json")
    records = json.loads(json_name.read_text(encoding="utf-8"))

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
                    cache[p] = pd.read_csv(workdir / p)
                env[e["variable"]] = cache[p]
            value = eval(r["pandas_query"], {"__builtins__": {"float": float, "len": len}}, env)  # noqa: S307
            stat["executed"] += 1
            expected = r["answer"]
            if value == value and (  # loại NaN
                abs(float(value) - float(expected))
                <= tolerance * max(1.0, abs(float(expected)))
            ):
                stat["matched"] += 1
        except Exception:  # noqa: BLE001
            stat["error"] += 1
    return stat
