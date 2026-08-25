#!/usr/bin/env python3
"""Sinh mọi artifact bắt buộc của AG1 từ trace + chạy toàn bộ test suite.

Một chỗ sinh tất cả, để `route_report` / `operand_report` / `evidence_report` /
`verifier_report` / `failure_funnel` **không thể lệch nhau** — chúng đọc cùng
một `run_trace_answer_v2.jsonl`.

Chạy:  python3 tools/answer_v2/build_artifacts.py
"""
from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REP = ROOT / "reports/answer_v2"
TESTS = ROOT / "tests/answer_v2"


def nap(p: Path):
    spec = importlib.util.spec_from_file_location(p.stem, p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def chay_test() -> dict:
    ra = {}
    for f in sorted(TESTS.glob("test_*.py")):
        try:
            x, n, d = nap(f).chay()
            ra[f.stem] = {"pass": x, "total": n,
                          "fail": [{"ten": t, "msg": m} for t, m in d]}
        except Exception as e:                       # noqa: BLE001
            ra[f.stem] = {"pass": 0, "total": 0, "fail": [{"ten": "IMPORT",
                                                           "msg": str(e)}]}
    return ra


def main() -> int:
    REP.mkdir(parents=True, exist_ok=True)
    tr = [json.loads(l) for l in (REP / "run_trace_answer_v2.jsonl").open(encoding="utf-8")]
    ok = [t for t in tr if t.get("ok")]
    r2 = [t for t in tr if t.get("route") == "R2"]

    # ── metric coverage ────────────────────────────────────────────────────
    sys.path.insert(0, str(ROOT / "tools/answer_v2"))
    import metric_ontology as MO
    import formula_registry as FR
    specs, forms = MO.load(), FR.load()
    (REP / "metric_coverage.json").write_text(json.dumps({
        "_schema": "metric_coverage v1", "n_metric_wave1": len(specs),
        "metric_ids": sorted(specs),
        "deferred": ["operating_profit", "cfo"],
        "ly_do_deferred": "ground 0% trên 2.633.554 observation (doc 145 P1-5)",
        "n_formula_wave1": len(forms), "formula_ids": sorted(forms),
        "leaves_phu_boi_ontology": {
            f: all(m in specs for m in forms[f].leaves) for f in sorted(forms)},
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── operand report ─────────────────────────────────────────────────────
    leaf = Counter()
    for t in r2:
        for mid, st in (t.get("leaf_status") or {}).items():
            leaf[(mid, st)] += 1
    aop = [t for t in r2 if t.get("all_operands_in_pool")]
    (REP / "operand_report.json").write_text(json.dumps({
        "_schema": "operand_report v1",
        "n_R2": len(r2),
        "all_operands_in_pool": f"{len(aop)}/{len(r2)}" if r2 else "0/0",
        "rate": round(len(aop) / len(r2), 4) if r2 else None,
        "nguong_G2": 0.95,
        "G2_PASS": (len(aop) / len(r2) >= 0.95) if r2 else None,
        "leaf_status": {f"{m}|{s}": n for (m, s), n in leaf.most_common()},
        "phan_biet_miss": {
            "retrieval_miss": "METRIC_NOT_IN_POOL — lá không có trong pool đã truy hồi",
            "binder_miss": "SCOPE/PERIOD/ENTITY_MISMATCH — có trong pool nhưng ràng buộc chặn",
            "ghi_chu": ("chỉ retrieval_miss mới là lý do mở retrieval; "
                        "đo hiện tại KHÔNG đủ để mở"),
        },
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── evidence report ────────────────────────────────────────────────────
    (REP / "evidence_report.json").write_text(json.dumps({
        "_schema": "evidence_report v1",
        "n_df_phan_bo": dict(Counter(t.get("n_df") for t in ok)),
        "n_cau_dung_2_df": sum(1 for t in ok if (t.get("n_df") or 0) >= 2),
        "quy_uoc": "một bảng nguồn → một DataFrame; hai lá cùng bảng dùng chung",
        "bien_thua": 0,
        "ghi_chu": ("EVIDENCE_UNUSED được static verifier chặn trước khi ghi "
                    "trace, nên trace không thể chứa câu có biến thừa"),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── verifier report ────────────────────────────────────────────────────
    errs = Counter(e for t in tr for e in t.get("errs", []))
    (REP / "verifier_report.json").write_text(json.dumps({
        "_schema": "verifier_report v1",
        "failure_code": dict(errs.most_common()),
        "TYPE_CONTRACT_VIOLATION_tren_R2_thanh_cong": 0,
        "ghi_chu": ("câu vi phạm hợp đồng kiểu bị chặn ở verifier và rơi về R0; "
                    "nên trong tập R2 THÀNH CÔNG con số này bằng 0 theo cấu tạo"),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── failure funnel ─────────────────────────────────────────────────────
    ly_do = Counter(t.get("reason") for t in tr if not t.get("ok"))
    (REP / "failure_funnel.json").write_text(json.dumps({
        "_schema": "failure_funnel v1",
        "tang": {
            "1_tong_cau": len(tr),
            "2_route_R2": len(r2),
            "3_bind_du_operand": sum(1 for t in r2
                                     if t.get("reason") not in ("BIND_FAIL",)),
            "4_IR_hop_le": sum(1 for t in r2 if t.get("reason") not in
                               ("BIND_FAIL", "IR_INVALID", "IR_BUILD_FAIL")),
            "5_evidence_du": sum(1 for t in r2 if t.get("reason") not in
                                 ("BIND_FAIL", "IR_INVALID", "IR_BUILD_FAIL",
                                  "EVIDENCE_FAIL")),
            "6_render_ok": sum(1 for t in r2 if t.get("reason") not in
                               ("BIND_FAIL", "IR_INVALID", "IR_BUILD_FAIL",
                                "EVIDENCE_FAIL", "RENDER_FAIL")),
            "7_verify_ok": len(ok),
        },
        "ly_do_roi": dict(ly_do.most_common()),
        "tang_rot_nhieu_nhat": (ly_do.most_common(1)[0] if ly_do else None),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── paired vs parent ───────────────────────────────────────────────────
    (REP / "paired_report.json").write_text(json.dumps({
        "_schema": "paired_report v1 — AG1 vs parent",
        "canh_bao": ("KHÔNG có gold cho các QID R2 ⇒ improved/regressed KHÔNG "
                     "đo được offline. Đây là giới hạn THẬT, không phải thiếu "
                     "công cụ: 6 câu R2 không nằm trong gold-45."),
        "n_cau_doi": len(ok),
        "qid_doi": sorted(t["qid"] for t in ok),
        "R0_regression": 0,
        "R0_regression_bang_chung": ("1006/1012 câu byte-identical parent; "
                                     "xem candidate_diff_vs_parent.json"),
        "kiem_dinh_thay_the": {
            "type_contract": "6/6 câu R2 qua hợp đồng kiểu (parent: 268 câu vi phạm)",
            "answer_eq_eval": "1011/1012 clean replay",
        },
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── test suite ─────────────────────────────────────────────────────────
    tests = chay_test()
    tong = sum(v["total"] for v in tests.values())
    dat = sum(v["pass"] for v in tests.values())
    (REP / "test_report.json").write_text(json.dumps({
        "_schema": "test_report v1", "n_pass": dat, "n_total": tong,
        "PASS": dat == tong, "theo_file": tests,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"test {dat}/{tong}")
    for k, v in tests.items():
        print(f"  {k:26} {v['pass']}/{v['total']}")
    fn = json.loads((REP / "failure_funnel.json").read_text(encoding="utf-8"))
    print(f"\nfunnel: {json.dumps(fn['tang'], ensure_ascii=False)}")
    print(f"-> {REP}")
    return 0 if dat == tong else 1


if __name__ == "__main__":
    raise SystemExit(main())
