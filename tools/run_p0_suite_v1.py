#!/usr/bin/env python3
"""Chạy P0 suite KHÔNG cần pytest — `PYTEST = NOT VERIFIED` là trạng thái thật.

Dự án ghi `PYTEST = NOT VERIFIED` từ doc 126 và sandbox không cài được pytest.
Một cổng P0 phụ thuộc công cụ chưa chạy được là một cổng không tồn tại. Runner
này gọi thẳng các hàm `test_*` bằng stdlib, nên P0 chạy được ở MỌI môi trường;
`pytest` vẫn dùng được cho cùng bộ test khi có.

Exit 0 = tất cả xanh. Exit 1 = có test đỏ ⇒ `PRE_SUBMISSION_BLOCKER` chặn nộp.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUITES = [
    ("P0_FAMILIES", "tests/execution/test_p0_families_v1.py"),
]


def load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    results = []
    for suite, rel in SUITES:
        p = ROOT / rel
        if not p.is_file():
            results.append({"suite": suite, "test": "-", "verdict": "MISSING",
                            "detail": rel})
            continue
        try:
            mod = load(p)
        except Exception as e:
            results.append({"suite": suite, "test": "<import>", "verdict": "FAIL",
                            "detail": f"{type(e).__name__}: {e}"})
            continue
        for name in sorted(n for n in dir(mod) if n.startswith("test_")):
            fn = getattr(mod, name)
            try:
                fn()
                results.append({"suite": suite, "test": name, "verdict": "PASS",
                                "detail": None})
            except AssertionError as e:
                results.append({"suite": suite, "test": name, "verdict": "FAIL",
                                "detail": str(e)[:400] or "assertion"})
            except Exception as e:
                results.append({"suite": suite, "test": name, "verdict": "ERROR",
                                "detail": f"{type(e).__name__}: {e}",
                                "trace": traceback.format_exc()[-800:]})

    n_fail = sum(r["verdict"] in ("FAIL", "ERROR", "MISSING") for r in results)
    fam = {}
    for r in results:
        key = ("UNIT_SCALE" if "unit_scale" in r["test"] or "scale" in r["test"]
               else "SIGN" if "sign" in r["test"]
               else "PERCENT" if "percent" in r["test"]
               else "ZERO_DENOM" if "zero_denominator" in r["test"] or "unresolved" in r["test"]
               else "ARGMAX" if "argmax" in r["test"]
               else "GOLD_SIGN_CONVENTION" if "gold" in r["test"] or "qid760" in r["test"]
               else "KHAC")
        b = fam.setdefault(key, {"pass": 0, "fail": 0})
        b["pass" if r["verdict"] == "PASS" else "fail"] += 1

    rep = {
        "_schema": "p0_suite v1 — PRE_SUBMISSION_BLOCKER (review 131 §6.2)",
        "date": "2026-08-21",
        "vi_sao_khong_dung_pytest": ("PYTEST = NOT VERIFIED trong dự án; sandbox "
                                     "không cài được. Cổng P0 phải chạy ở mọi môi trường."),
        "n_test": len(results),
        "n_pass": sum(r["verdict"] == "PASS" for r in results),
        "n_fail": n_fail,
        "theo_ho_loi": fam,
        "VERDICT": "P0_GREEN" if n_fail == 0 else "P0_RED_CHAN_NOP",
        "results": results,
    }
    (ROOT / "reports/p0_suite_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    for r in results:
        mark = "✓" if r["verdict"] == "PASS" else "✗"
        print(f"  {mark} {r['test']}" + (f"   {r['detail']}" if r["detail"] else ""))
    print(f"\n{rep['VERDICT']}  ({rep['n_pass']}/{rep['n_test']} xanh)")
    print("theo họ:", json.dumps(fam, ensure_ascii=False))
    print("-> reports/p0_suite_v1.json")
    return 1 if n_fail else 0


if __name__ == "__main__":
    raise SystemExit(main())
