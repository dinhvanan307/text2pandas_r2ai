#!/usr/bin/env python3
"""QID slice + paired table trên ĐÚNG cùng mẫu số — đóng P0-2 của doc 134.

DOC 134 P0-2: doc 133 viết `C2B numeric exact 3/12` cạnh `C0 trên cùng tập 1/24`.
Hai số ấy **không cùng mẫu số**: 12 ≠ 24. `1/24` là baseline trên toàn bộ 24 câu
non-lookup, còn C2B chỉ exercise 12 câu. Muốn nói "templates tạo gain" thì phải
báo C0 trên **đúng 12 QID đó**.

Tệp này sinh:
    evaluation/qid_slices.json     danh sách QID từng slice, khoá lại
    reports/paired_slices_v1.json  bảng paired đúng mẫu số cho mọi bậc

Slice được định nghĩa bởi **cờ intent**, không phải bởi kết quả — nên nó khoá
được TRƯỚC khi xem điểm.
"""
from __future__ import annotations

import json
import sys
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from execution.emit_arith_v1 import ARITH_INTENTS, LADDER  # noqa: E402
from build_candidate_v1 import khop, load_control  # noqa: E402

TOL = 0.01


def mcnemar(b: int, c: int) -> float:
    n = b + c
    if n == 0:
        return 1.0
    return min(1.0, 2 * sum(comb(n, i) for i in range(min(b, c) + 1)) / (2 ** n))


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / d
    return (round(max(0.0, c - h), 4), round(min(1.0, c + h), 4))


def main() -> int:
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/dev/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    sub0, _ = load_control()
    c0 = {r["id"]: r for r in sub0}
    tf = ROOT / "evaluation/arith_traces_v1.jsonl"
    traces = ([json.loads(l) for l in tf.open(encoding="utf-8") if l.strip()]
              if tf.is_file() else [])

    # FAIL TO TIẾNG nếu thiếu trace. Bản đầu chạy với file RỖNG vẫn exit 0 và in
    # một bảng trong đó candidate == C0 ở mọi bậc — tức "C2B 0/12" thay vì
    # "3/12". Một báo cáo sai mà exit 0 nguy hiểm hơn một lần crash.
    if not traces:
        print("✗ evaluation/arith_traces_v1.jsonl RỖNG hoặc không có.", file=sys.stderr)
        print("  Bảng paired sẽ sai (candidate = C0 ở mọi bậc).", file=sys.stderr)
        print("  Chạy TRƯỚC:  python3 tools/run_arith_eval_v1.py", file=sys.stderr)
        return 2

    all_arith = sorted(q for q, g in gold.items() if g["lop"] in ARITH_INTENTS)
    lookup = sorted(q for q, g in gold.items() if g["lop"] == "lookup")

    slices = {
        "S_ALL45": {"qids": sorted(gold), "mo_ta": "toàn bộ gold-45"},
        "S_LOOKUP21": {"qids": lookup, "mo_ta": "21 câu lookup"},
        "S_ARITH24": {"qids": all_arith, "mo_ta": "24 câu non-lookup"},
    }
    for rung, fl in LADDER.items():
        qs = sorted(q for q in all_arith if fl.enabled(gold[q]["lop"]))
        slices[f"S_{rung}"] = {
            "qids": qs, "mo_ta": f"câu có intent được {rung} bật cờ",
            "intents_bat": [i for i in ARITH_INTENTS if fl.enabled(i)],
        }

    (ROOT / "evaluation/qid_slices.json").write_text(json.dumps(
        {"_schema": "qid_slices v1 — slice định nghĩa bởi CỜ INTENT, khoá trước khi xem điểm",
         "date": "2026-08-21", "dataset": "gold_dap_an_v1",
         "slices": {k: v | {"n": len(v["qids"])} for k, v in slices.items()}},
        ensure_ascii=False, indent=1), encoding="utf-8")

    tables = {}
    for rung in LADDER:
        s = slices[f"S_{rung}"]
        qs = s["qids"]
        tr = {r["qid"]: r for r in traces if r["rung"] == rung}
        base = {q: khop(c0[q].get("answer"), gold[q]["dap_an_gold"], TOL) for q in qs}
        cand = {}
        for q in qs:
            r = tr.get(q)
            cand[q] = (r["numeric_exact"] if r and not r["abstain"] else base[q])
        b = sorted(q for q in qs if cand[q] and not base[q])
        c = sorted(q for q in qs if base[q] and not cand[q])
        nb, nc = sum(base.values()), sum(cand.values())
        tables[rung] = {
            "slice": f"S_{rung}", "n": len(qs), "qids": qs,
            "intents_bat": s["intents_bat"],
            "C0_tren_dung_slice": f"{nb}/{len(qs)}",
            "candidate_tren_slice": f"{nc}/{len(qs)}",
            "improved_b": b, "regressed_c": c,
            "discordant_table": {"b": len(b), "c": len(c)},
            "net": nb and (nc - nb) or (nc - nb),
            "mcnemar_p_hai_phia": round(mcnemar(len(b), len(c)), 4),
            "wilson_ci95_candidate": wilson(nc, len(qs)),
            "effect_size_delta_acc": round((nc - nb) / len(qs), 4) if qs else None,
        }

    rep = {
        "_schema": "paired_slices v1 — đóng P0-2 doc 134 (cùng mẫu số)",
        "date": "2026-08-21",
        "loi_da_sua": ("doc 133 §0 đặt `C2B 3/12` cạnh `C0 1/24` và gọi là 'cùng "
                       "tập'. Sai mẫu số. Bảng dưới báo C0 trên ĐÚNG slice của "
                       "từng bậc."),
        "dataset": "gold_dap_an_v1",
        "evaluation_mode": "TRAIN_FIT / REGRESSION-ONLY",
        "tolerance_tuong_doi": TOL,
        "bang_paired": tables,
        "command": "python3 tools/build_qid_slices_v1.py",
    }
    (ROOT / "reports/paired_slices_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{'bậc':5} {'n':>3} {'C0 trên slice':>14} {'candidate':>10} "
          f"{'b/c':>7} {'net':>5} {'p':>7}")
    for rung, t in tables.items():
        print(f"{rung:5} {t['n']:>3} {t['C0_tren_dung_slice']:>14} "
              f"{t['candidate_tren_slice']:>10} "
              f"{t['discordant_table']['b']}/{t['discordant_table']['c']:<5} "
              f"{t['net']:>+5d} {t['mcnemar_p_hai_phia']:>7}")
    print("\nQID từng slice:")
    for rung, t in tables.items():
        print(f"  S_{rung} (n={t['n']}): {t['qids']}")
    print("\n-> evaluation/qid_slices.json · reports/paired_slices_v1.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
