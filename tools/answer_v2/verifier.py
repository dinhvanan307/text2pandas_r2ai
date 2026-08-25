#!/usr/bin/env python3
"""Verifier ba tầng. Mỗi luật một failure code — không có "should be safe".

    STATIC    đọc IR + query, không chạy gì
    DYNAMIC   chạy query trong ĐÚNG `_safe_env` của replay, hai lần
    SEMANTIC  hợp đồng kiểu đáp án — `answer_type_v1`, đã có 22 test xanh

Tầng SEMANTIC là thứ bắt được lớp lỗi mà 268/1.012 câu của bài nộp hiện hành
đang mắc (doc 142): hỏi "bao nhiêu lần" trả về 5.344.660.910. Không tầng nào
khác bắt được nó, vì query vẫn chạy và vẫn trả scalar hữu hạn.
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import ir_v1  # noqa: E402
from execution.answer_type_v1 import kiem, suy_hop_dong  # noqa: E402
from pandas_renderer import CAM  # noqa: E402

TOL = 1e-9

# BẢN SAO CHÍNH XÁC của `replay_submission_v1._safe_env`. Nếu file kia đổi mà
# đây không đổi, test `test_renderer::safe_env_la_SSOT` sẽ đỏ — đó là mục đích.
def safe_env(dfs: dict) -> dict:
    env = {
        "pd": pd, "np": np,
        "float": float, "int": int, "abs": abs, "round": round,
        "min": min, "max": max, "sum": sum, "len": len, "str": str,
        "__builtins__": {},
    }
    env.update(dfs)
    return env


def static(plan: ir_v1.Plan, query: str, evidence: list[dict],
           bind: dict[str, dict]) -> list[str]:
    errs: list[str] = []
    if CAM.search(query or ""):
        errs.append("AST_FORBIDDEN_NODE")

    khai = {e["variable"] for e in evidence}
    dung = {b["variable"] for b in bind.values()}
    if dung - khai:
        errs.append("EVIDENCE_VAR_MISSING")
    # Biến khai mà query không nhắc tới ⇒ evidence thừa. BTC định nghĩa evidence
    # là "bảng ĐƯỢC SỬ DỤNG để thực thi pandas_query" — thừa là sai hợp đồng.
    for v in khai:
        if v not in (query or ""):
            errs.append("EVIDENCE_UNUSED")
            break

    for lit in ir_v1.literals(plan):
        if lit.get("source") not in ir_v1.LITERAL_SOURCES:
            errs.append("LITERAL_UNSOURCED")
            break
    return errs


def dynamic(query: str, evidence: list[dict], answer: float,
            zip_read=None, data_dir: Path | None = None) -> list[str]:
    """Chạy query hai lần trên CSV thật. `zip_read` hoặc `data_dir` — một trong hai."""
    errs: list[str] = []
    dfs = {}
    for e in evidence:
        p = e["csv_path"]
        try:
            if zip_read is not None:
                dfs[e["variable"]] = pd.read_csv(io.BytesIO(zip_read(p)))
            else:
                dfs[e["variable"]] = pd.read_csv(data_dir.parent / p)
        except Exception:
            return ["CSV_MISSING"]

    vals = []
    for _ in range(2):
        try:
            v = eval(query, safe_env(dfs))       # noqa: S307 — query của chính ta
        except Exception:
            return ["EXEC_ERROR"]
        try:
            v = float(v)
        except Exception:
            return ["NON_FINITE"]
        if v != v or v in (float("inf"), float("-inf")):
            return ["NON_FINITE"]
        vals.append(v)

    if vals[0] != vals[1]:
        errs.append("NON_DETERMINISTIC")
    if answer is None or abs(vals[0] - float(answer)) > max(
            TOL, TOL * abs(float(answer or 0))):
        errs.append("ANSWER_MISMATCH")
    return errs


def semantic(question: str, answer: float) -> list[str]:
    hd = suy_hop_dong(question or "")
    r = kiem(hd, answer)
    return ["TYPE_CONTRACT_VIOLATION"] if r["ok"] is False else []


def verify_all(*, plan, query, evidence, bind, answer, question,
               zip_read=None, data_dir=None) -> list[str]:
    errs = static(plan, query, evidence, bind)
    errs += dynamic(query, evidence, answer, zip_read=zip_read, data_dir=data_dir)
    errs += semantic(question, answer)
    ra, thay = [], set()
    for c in errs:
        if c not in thay:
            thay.add(c)
            ra.append(c)
    return ra
