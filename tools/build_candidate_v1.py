#!/usr/bin/env python3
"""D4 · Sinh + ABLATE candidate C1a–C1e. Không nộp, không chạm leaderboard.

Trả lời trực tiếp review 127 §5 ("C1 được tách thành các flag/ablation nào;
thay đổi duy nhất của mỗi dòng là gì") và §8 câu 15.

CÁCH ĐỌC BÁO CÁO
----------------
Mọi số ở đây đo trên gold-45. Gold-45 mang ba nhãn không được bỏ:
`TRAIN_FIT` (V1.1 đã tune trên chính nó), `SURVIVORSHIP_BIASED` (chỉ còn các
câu nhãn rõ), `BUILD_MACHINE_ONLY`. Vì vậy bảng này dùng để:

    ✓ bắt regression   ✓ so hướng giữa hai bậc   ✓ quyết định bậc nào đóng ZIP
    ✗ dự báo điểm official   ✗ tuyên bố "đã đạt X%"

Paired report theo đúng yêu cầu: improved / regressed / net trên CÙNG tập QID,
tách theo intent — vì một bậc có thể nâng lookup và phá arithmetic cùng lúc,
và số tổng sẽ giấu điều đó.

Chạy:
    python3 tools/build_candidate_v1.py                 # ablation, không ghi ZIP
    python3 tools/build_candidate_v1.py --zip C1e       # + đóng ZIP bậc C1e
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import sqlite3
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from execution.fact_rank_v1 import fetch_pool  # noqa: E402
from execution.emit_lookup_v1 import (  # noqa: E402
    CSV_COLS, LADDER, build_query, evidence_csv, pick)

CONTROL = ROOT / "sync_122_1/controls/submission_P0I.zip"
OUTDIR = ROOT / "artifacts/execution/candidates"
TOL = 0.01                       # ngưỡng tương đối, giống tools/eval_answer_v1.py


def load_control() -> tuple[list[dict], dict[str, bytes]]:
    with zipfile.ZipFile(CONTROL) as z:
        sub = json.loads(z.read("submission.json"))
        blobs = {n: z.read(n) for n in z.namelist() if n != "submission.json"}
    return sub, blobs


def khop(got, want, tol: float = TOL) -> bool:
    try:
        g, w = float(got), float(want)
    except (TypeError, ValueError):
        return False
    if g != g or w != w:
        return False
    return abs(g) <= tol if w == 0 else abs(g - w) / abs(w) <= tol


def registry_labels() -> list[str]:
    """Nhãn metric từ registry SINH TỪ A6 — không phải danh sách viết tay."""
    txt = (ROOT / "configs/execution/metric_registry_v1.yaml").read_text(encoding="utf-8")
    labs = []
    for line in txt.splitlines():
        s = line.strip()
        if s.startswith("- label:"):
            v = s.split(":", 1)[1].strip().strip('"').strip("'")
            if v:
                labs.append(v)
    return labs


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", dest="zip_rung", default=None,
                    help="đóng ZIP cho bậc này (C1a..C1e)")
    ap.add_argument("--det-order", action="store_true",
                    help="KHOÁ TIE-BREAK: ORDER BY observation_uid + tie-break "
                         "tất định. Đây là hành vi ĐÚNG (tái lập giữa hai máy) "
                         "nhưng làm lookup recall@1 tụt 57,1%% -> 33,3%% trên "
                         "gold-45. Ghi report ra file _det để so cạnh nhau.")
    a = ap.parse_args()

    # Một cờ, một thay đổi hành vi — kể cả cờ này. `--det-order` chỉ đổi THỨ TỰ,
    # không đổi điểm số, không đổi ngưỡng.
    ladder = LADDER
    if a.det_order:
        from dataclasses import replace as _replace
        from execution.fact_rank_v1 import Flags as _F
        det = _F(idf_pool=True, exact_phrase=True, quota=True, legacy_order=False)
        ladder = {k: _replace(v, rank_flags=det) for k, v in LADDER.items()}
    suffix = "_det" if a.det_order else ""
    print(f"thứ tự xếp hạng: {'TẤT ĐỊNH (det)' if a.det_order else 'legacy (phụ thuộc thứ tự quét bảng)'}")

    con = sqlite3.connect(
        f"file:{ROOT/'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "evaluation/question_plans_1012.jsonl").open(encoding="utf-8"))}
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/curated/dev-legacy/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    labs = registry_labels()
    print(f"metric registry: {len(labs)} nhãn")

    sub0, _ = load_control()
    c0 = {r["id"]: r for r in sub0}

    # QID mục tiêu của emitter lookup: intent_v1 == lookup. KHÔNG lọc theo gold —
    # lọc theo gold là hard-code tập đo vào tập chạy.
    targets = [q for q, p in plans.items() if p.get("intent_v1") == "lookup"]
    print(f"QID intent=lookup: {len(targets)}/1012")

    # Vòng ngoài là QID, vòng trong là bậc: pool đọc MỘT lần cho cả 5 bậc.
    decisions: dict[str, dict[int, dict]] = {r: {} for r in ladder}
    for i, q in enumerate(targets, 1):
        plan = plans[q]
        pool = fetch_pool(con, plan, legacy_order=not a.det_order)
        if not pool:
            continue
        for rung, fl in ladder.items():
            try:
                r = pick(None, plan, fl, labs, pool=pool)
            except Exception as e:                      # đo được, không nuốt
                r = {"error": f"{type(e).__name__}: {e}", "abstain": True,
                     "abstain_reason": "EXCEPTION"}
            if r:
                decisions[rung][q] = r
        if i % 100 == 0:
            print(f"    …{i}/{len(targets)}", flush=True)
    for rung, fl in ladder.items():
        d = decisions[rung]
        n_emit = sum(1 for r in d.values() if not r.get("abstain"))
        print(f"  {rung:4s} {fl.name:60s} emit {n_emit:4d} / abstain {len(d)-n_emit:4d}")

    # ── chấm paired trên gold-45 ────────────────────────────────────────────
    gold_qids = sorted(gold)
    base_ok = {q: khop(c0[q].get("answer"), gold[q]["dap_an_gold"]) for q in gold_qids}

    def answers_for(rung: str) -> dict[int, float]:
        out = {}
        for q in gold_qids:
            r = decisions[rung].get(q)
            out[q] = (r["answer"] if r and not r.get("abstain")
                      else c0[q].get("answer"))
        return out

    rungs = list(ladder)
    table = []
    prev_ok = base_ok
    for rung in rungs:
        ans = answers_for(rung)
        ok = {q: khop(ans[q], gold[q]["dap_an_gold"]) for q in gold_qids}
        imp = [q for q in gold_qids if ok[q] and not base_ok[q]]
        reg = [q for q in gold_qids if base_ok[q] and not ok[q]]
        imp_step = [q for q in gold_qids if ok[q] and not prev_ok[q]]
        reg_step = [q for q in gold_qids if prev_ok[q] and not ok[q]]
        by_intent = defaultdict(lambda: {"n": 0, "ok": 0, "base_ok": 0})
        for q in gold_qids:
            b = by_intent[gold[q]["lop"]]
            b["n"] += 1
            b["ok"] += ok[q]
            b["base_ok"] += base_ok[q]
        n_touch = sum(1 for q in gold_qids
                      if decisions[rung].get(q) and not decisions[rung][q].get("abstain"))
        table.append({
            "rung": rung, "flags": ladder[rung].name,
            "n_gold": len(gold_qids),
            "n_gold_ghi_de": n_touch,
            "exact": sum(ok.values()), "exact_pct": round(sum(ok.values()) / len(gold_qids), 4),
            "base_exact": sum(base_ok.values()),
            "net_vs_C0": sum(ok.values()) - sum(base_ok.values()),
            "improved_vs_C0": imp, "regressed_vs_C0": reg,
            "improved_vs_bac_truoc": imp_step, "regressed_vs_bac_truoc": reg_step,
            "theo_intent": {k: dict(v) for k, v in sorted(by_intent.items())},
        })
        prev_ok = ok

    for t in table:
        print(f"  {t['rung']}  exact {t['exact']:2d}/45 ({t['exact_pct']:.1%})  "
              f"net {t['net_vs_C0']:+d}  ghi đè {t['n_gold_ghi_de']:2d}  "
              f"+{len(t['improved_vs_C0'])}/−{len(t['regressed_vs_C0'])}")

    # ── phủ toàn bộ 1.012: emitter chạm bao nhiêu câu, contract có vỡ không ──
    cov = {}
    for rung in rungs:
        d = decisions[rung]
        cov[rung] = {
            "n_target_lookup": len(targets),
            "n_co_quyet_dinh": len(d),
            "n_emit": sum(1 for r in d.values() if not r.get("abstain")),
            "n_abstain": sum(1 for r in d.values() if r.get("abstain")),
            "abstain_reason": dict(Counter(r.get("abstain_reason") for r in d.values()
                                           if r.get("abstain"))),
        }

    rep = {
        "_schema": "c1_ablation v1 — paired ablation C1a→C1e (review 127 §5, §8 câu 15/22)",
        "date": "2026-08-21",
        "machine": "build machine · py3.10.12 (MEASURED_OFF_CONTRACT_PY310)",
        "control": "C0_SEMANTIC_CONTROL_3241 (submission_P0I.zip)",
        "dataset_cham": "gold_dap_an_v1 · 45 QID",
        "nhan_bat_buoc": ["TRAIN_FIT", "SURVIVORSHIP_BIASED", "BUILD_MACHINE_ONLY"],
        "tolerance_tuong_doi": TOL,
        "thang_ablation": {r: ladder[r].name for r in rungs},
        "thu_tu_xep_hang": "deterministic" if a.det_order else "legacy_table_scan_order",
        "paired_table": table,
        "coverage_1012": cov,
        "command": "python3 tools/build_candidate_v1.py" + (" --det-order" if a.det_order else ""),
    }
    (ROOT / "reports").mkdir(exist_ok=True)
    (ROOT / f"reports/c1_ablation_v1{suffix}.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> reports/c1_ablation_v1{suffix}.json")

    if a.zip_rung:
        build_zip(con, a.zip_rung, decisions[a.zip_rung], plans, sub0, suffix)
    return 0


def build_zip(con, rung: str, dec: dict[int, dict], plans: dict, sub0: list[dict],
              suffix: str = "") -> None:
    """Đóng ZIP ứng viên. CHỈ đổi execution fields; retrieval fields bất biến."""
    OUTDIR.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(CONTROL) as z:
        blobs = {n: z.read(n) for n in z.namelist() if n != "submission.json"}

    out = [dict(r) for r in sub0]
    by_id = {r["id"]: r for r in out}
    n_written = 0
    skipped: dict[str, int] = Counter()

    for q, r in sorted(dec.items()):
        if r.get("abstain") or q not in by_id:
            continue
        cell = r["cell"]
        table = evidence_csv(con, cell["evidence_ref"])
        key = (cell["row_path"] or "", cell["metric_label"] or "", cell["col_path"] or "")
        mult = sum(1 for a, b, c, _, _ in table if (a, b, c) == (key[0], key[1], key[2]))
        if mult != 1:
            # `.item()` sẽ ném — KHÔNG emit. Đây chính là cổng "first-cell = 0":
            # thay vì lặng lẽ lấy ô đầu, ta từ chối câu và đếm nó.
            skipped[f"MULTIPLICITY_{min(mult, 9)}"] += 1
            continue

        doc, _, line = cell["evidence_ref"].partition("|line:")
        path = f"data/c1_{doc}_line{line}.csv"
        if path not in blobs:
            buf = io.StringIO()
            w = csv.writer(buf, lineterminator="\n")
            w.writerow(CSV_COLS)
            w.writerows(table)
            blobs[path] = buf.getvalue().encode("utf-8")

        rec = by_id[q]
        rec["answer"] = r["answer"]
        rec["evidence"] = [{"variable": "df1", "csv_path": path}]
        rec["pandas_query"] = build_query(cell, "df1", r["unit_factor"],
                                          r["scale_exponent_applied"])
        n_written += 1

    dst = OUTDIR / f"submission_{rung}{suffix}.zip"
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("submission.json", json.dumps(out, ensure_ascii=False))
        for n, b in sorted(blobs.items()):
            z.writestr(n, b)
    print(f"-> {dst}  (ghi đè {n_written} câu; bỏ vì multiplicity: {dict(skipped)})")


if __name__ == "__main__":
    raise SystemExit(main())
