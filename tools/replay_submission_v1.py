#!/usr/bin/env python3
"""Clean replay bài nộp từ ZIP + sinh runtime trace cho đủ 1.012 QID.

Sinh ra (plan 124 §3.3, feedback 125 §8.1 mục 11–12):

1. `reports/<zip>_clean_replay.json` — bất biến `answer == eval(pandas_query)`
   chạy lại TỪ ZIP SẠCH (giải nén tạm, không đọc workspace).
2. `data/curated/evaluation/legacy/run_trace_1012.jsonl` — mỗi QID một dòng với
   `runtime_terminal_stage`. KHÔNG sinh `first_correctness_failure` ở đây:
   trường đó chỉ tồn tại trên execution Gold (124 §3.3).

runtime_terminal_stage (thứ tự kiểm):
    NO_ANSWER      thiếu answer
    NO_QUERY       thiếu pandas_query
    NO_EVIDENCE    evidence rỗng
    CSV_MISSING    csv_path khai trong evidence không có trong ZIP
    QUERY_ERROR    eval ném exception
    NON_SCALAR     kết quả không phải số hữu hạn
    ANSWER_MISMATCH|answer != eval(query) (rel tol --tol)
    OK             toàn bộ khớp

Chạy:
    python3 tools/replay_submission_v1.py artifacts/submissions/legacy/submission_P0I.zip
Exit 0 = mọi QID có trace; số liệu in ra stdout. Không exit lỗi theo mismatch —
đây là dụng cụ ĐO (giống triết lý validate_submission tầng kiểu).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import math
import platform
import socket
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def _may_that() -> str:
    """Danh tính máy THẬT — không phải hằng số 'build'."""
    return f"{socket.gethostname()}|{platform.system()}|{platform.machine()}"


def _sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def _safe_env(dfs: dict) -> dict:
    env = {
        "pd": pd, "np": np,
        "float": float, "int": int, "abs": abs, "round": round,
        "min": min, "max": max, "sum": sum, "len": len, "str": str,
        "__builtins__": {},
    }
    env.update(dfs)
    return env


def replay(zip_path: Path, tol: float) -> tuple[list[dict], dict]:
    rows: list[dict] = []
    with zipfile.ZipFile(zip_path) as z:
        names = set(z.namelist())
        sub = json.loads(z.read("submission.json"))
        for rec in sub:
            qid = rec.get("id")
            t = {"qid": qid, "runtime_terminal_stage": None,
                 "n_evidence": len(rec.get("evidence") or []),
                 "has_query": bool(rec.get("pandas_query"))}
            ans = rec.get("answer")
            q = rec.get("pandas_query")
            ev = rec.get("evidence") or []
            if ans is None:
                t["runtime_terminal_stage"] = "NO_ANSWER"; rows.append(t); continue
            if not q:
                t["runtime_terminal_stage"] = "NO_QUERY"; rows.append(t); continue
            if not ev:
                t["runtime_terminal_stage"] = "NO_EVIDENCE"; rows.append(t); continue
            dfs = {}
            missing = [e["csv_path"] for e in ev if e.get("csv_path") not in names]
            if missing:
                t["runtime_terminal_stage"] = "CSV_MISSING"
                t["missing"] = missing; rows.append(t); continue
            for e in ev:
                dfs[e["variable"]] = pd.read_csv(io.BytesIO(z.read(e["csv_path"])))
            try:
                val = eval(q, _safe_env(dfs))  # noqa: S307 — query của chính bài nộp
            except Exception as ex:  # noqa: BLE001
                t["runtime_terminal_stage"] = "QUERY_ERROR"
                t["error"] = f"{type(ex).__name__}: {ex}"[:200]
                rows.append(t); continue
            try:
                fval = float(val)
            except Exception:
                t["runtime_terminal_stage"] = "NON_SCALAR"; rows.append(t); continue
            if not math.isfinite(fval):
                t["runtime_terminal_stage"] = "NON_SCALAR"; rows.append(t); continue
            fans = float(ans)
            denom = max(abs(fans), abs(fval), 1e-12)
            if abs(fans - fval) / denom <= tol:
                t["runtime_terminal_stage"] = "OK"
            else:
                t["runtime_terminal_stage"] = "ANSWER_MISMATCH"
                t["answer"] = fans; t["replayed"] = fval
            rows.append(t)
    from collections import Counter
    summ = dict(Counter(r["runtime_terminal_stage"] for r in rows))
    return rows, summ


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("zip")
    ap.add_argument("--tol", type=float, default=1e-9)
    ap.add_argument("--trace-out", default="data/curated/evaluation/legacy/run_trace_1012.jsonl")
    ap.add_argument("--report-out", default=None)
    ap.add_argument("--machine", default=None,
                    help="nhãn máy; mặc định lấy hostname+OS+arch THẬT")
    ap.add_argument("--run-id", default=None)
    a = ap.parse_args()
    zp = Path(a.zip)
    rows, summ = replay(zp, a.tol)
    (ROOT / "evaluation").mkdir(exist_ok=True)
    (ROOT / "reports").mkdir(exist_ok=True)
    tout = ROOT / a.trace_out
    with tout.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    rep = {"zip": str(zp), "n": len(rows), "tol": a.tol, "summary": summ,
           "invariant_answer_eq_query": summ.get("OK", 0),
           # PROVENANCE (doc 155 §3.3 mục 6): trường này trước đây bị chốt cứng
           # thành "build", nên báo cáo do REVIEWER chạy trên máy khác vẫn tự
           # khai là chạy trên máy build. Một artifact nói sai nó sinh ra ở đâu
           # thì mọi so sánh chéo máy đều mất nghĩa. Lấy danh tính thật; cho
           # phép ghi đè qua --machine khi cần dán nhãn run.
           "machine": a.machine or _may_that(),
           "run_id": a.run_id,
           "runtime": {"python": platform.python_version(),
                       "implementation": platform.python_implementation(),
                       "os": f"{platform.system()} {platform.release()}",
                       "arch": platform.machine(),
                       "pandas": pd.__version__, "numpy": np.__version__},
           "zip_sha256": _sha256(Path(a.zip)),
           "command": " ".join(sys.argv)}
    rout = ROOT / (a.report_out or f"reports/{zp.stem}_clean_replay.json")
    rout.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
