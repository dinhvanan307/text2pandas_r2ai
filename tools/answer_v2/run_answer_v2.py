#!/usr/bin/env python3
"""AG1_R2_FORMULA — chạy R2 trên 1.012 câu, đóng candidate ZIP từ parent.

CHIẾN LƯỢC TÍCH HỢP — KHÁC doc 144/145, có lý do kỹ thuật (xem DEVIATION)
Không nối vào `run_pipeline.py`. Thay vào đó theo đúng khuôn
`tools/so_hoc/07_dong_goi.py` mà đường production đang dùng:

    parent ZIP  →  chỉ thay `answer` · `pandas_query` · `evidence` của câu R2
                →  `relevant_tables` / `relevant_docs` GIỮ NGUYÊN BYTE
                →  candidate ZIP

Nhờ vậy `relevant_*` bất biến **theo cấu tạo**, không phải nhờ kiểm tra sau —
đó chính là điều kiện G4 đòi, và là điều kiện để quy mọi delta official về đúng
tầng answer generation.

Chạy:
    python3 tools/answer_v2/run_answer_v2.py                # dry-run, chỉ báo cáo
    python3 tools/answer_v2/run_answer_v2.py --build-zip    # + đóng candidate
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import sys
import tempfile
import time
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))
sys.path.insert(0, str(ROOT / "tools"))

import evidence_builder as EV          # noqa: E402
import formula_registry as FR          # noqa: E402
import ir_v1                           # noqa: E402
import metric_ontology as MO           # noqa: E402
import operand_binder as OB            # noqa: E402
import pandas_renderer as PR           # noqa: E402
import router_v1 as RT                 # noqa: E402
import verifier as VF                  # noqa: E402
from execution.answer_type_v1 import kiem, suy_hop_dong  # noqa: E402

WORK = ROOT / "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db"
PLANS = ROOT / "data/curated/evaluation/legacy/question_plans_1012.jsonl"
REPORTS = ROOT / "reports/answer_v2"
PARENT_DEFAULT = ROOT / "artifacts/submissions/legacy/submission_P0I.zip"

# `value_kind` cho dimension algebra: mọi lá wave 1 đều là tiền.
VALUE_KIND = {"money": "money"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def mot_cau(con, q: dict, plan_q: dict, specs, formulas, data_dir: Path,
            da_ghi: set[str], *, router_fix: bool = False,
            ontology_fix: bool = False) -> dict:
    """Thử R2 cho MỘT câu. → bản ghi trace; `ok=False` nghĩa là rơi về R0."""
    qid = q["id"]
    question = q.get("question", "")
    t = {"qid": qid, "route": None, "formula_id": None, "ok": False,
         "reason": None, "errs": []}

    route, sp, ly_do = RT.route(question, plan_q, formulas, router_fix=router_fix)
    t["route"], t["reason"] = route, ly_do
    if route != "R2" or sp is None:
        return t
    t["formula_id"] = sp.formula_id

    entity, year = RT.entity_nam(plan_q)
    t["entity"], t["year"] = entity, year

    # ── bind ───────────────────────────────────────────────────────────────
    ops, errs, chan = OB.bind_plan(con, plan_q, list(sp.leaves), entity, year,
                                   specs, same_entity=sp.same_entity,
                                   same_period=sp.same_period,
                                   ontology_fix=ontology_fix)
    t["leaf_status"] = chan["leaf_status"]
    t["all_operands_in_pool"] = all(v == "OK" for v in chan["leaf_status"].values())
    if errs:
        t["errs"] = errs
        t["reason"] = "BIND_FAIL"
        return t

    # ── IR ─────────────────────────────────────────────────────────────────
    binding = {mid: {"entity": o.key.entity,
                     "period": {"year": o.key.period_year},
                     "scope": o.key.scope,
                     "observation_uid": o.observation_uid}
               for mid, o in ops.items()}
    expr = FR.with_zero_policy(sp.expression, sp.zero_policy)
    try:
        plan = ir_v1.from_expression(
            expr, qid=qid, formula_id=sp.formula_id, variant_id=sp.variant_id,
            output_kind=sp.output_kind, output_unit=sp.output_unit,
            fact_binding=binding)
    except ir_v1.IRError as e:
        t["errs"] = [e.code]
        t["reason"] = "IR_BUILD_FAIL"
        return t

    vk = {mid: specs[mid].value_kind for mid in ops}
    ir_errs = ir_v1.validate(plan, vk)
    if ir_errs:
        t["errs"] = ir_errs
        t["reason"] = "IR_INVALID"
        return t

    # ── evidence ───────────────────────────────────────────────────────────
    bind, evidence, ev_errs = EV.build(con, ops, data_dir, da_ghi)
    if ev_errs:
        t["errs"] = ev_errs
        t["reason"] = "EVIDENCE_FAIL"
        return t

    # ── render ─────────────────────────────────────────────────────────────
    try:
        query, val = PR.render(plan, bind)
    except PR.RenderError as e:
        t["errs"] = [e.code]
        t["reason"] = "RENDER_FAIL"
        return t

    # ── verify ─────────────────────────────────────────────────────────────
    v_errs = VF.verify_all(plan=plan, query=query, evidence=evidence, bind=bind,
                           answer=val, question=question, data_dir=data_dir)
    if v_errs:
        t["errs"] = v_errs
        t["reason"] = "VERIFY_FAIL"
        return t

    t.update(ok=True, reason="OK", answer=val, pandas_query=query,
             evidence=evidence, n_df=len({e["variable"] for e in evidence}),
             output_kind=sp.output_kind,
             operands={mid: o.observation_uid for mid, o in ops.items()})
    return t


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent", type=Path, default=PARENT_DEFAULT)
    ap.add_argument("--build-zip", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    # BẮT BUỘC tách tên ZIP theo candidate. Trước đây tên bị chốt cứng thành
    # `submission_AG1_R2_FORMULA.zip`, nên chạy lại SAU khi vá router/ontology
    # sẽ GHI ĐÈ AG1 bằng AG1B dưới đúng tên AG1 — mất luôn khả năng diff hai
    # candidate, và doc 154 §2 đòi "Parent (exact) = exact AG1B ZIP/source".
    # Một dòng cờ rẻ hơn nhiều so với việc mất một anchor đã nộp.
    ap.add_argument("--candidate-id", default="AG1_R2_FORMULA")
    # ── P0 · feature flag (doc 155 §5.1/§5.3) ─────────────────────────────
    # Mặc định TẮT: chạy không cờ tái hiện CHÍNH XÁC hành vi PRE-FIX (AG1).
    # Nhờ vậy ba ablation `router_fix_only` / `ontology_fix_only` /
    # `router_plus_ontology` là ba phép thử nhân quả một-thay-đổi thật sự,
    # chạy trên CÙNG một cây mã — không phải so hai lần checkout khác nhau.
    ap.add_argument("--router-fix", action="store_true",
                    help="bật 6 pattern precision P0 trong router_v1")
    ap.add_argument("--ontology-fix", action="store_true",
                    help="bật luật tiền tố dòng-tổng + forbidden_contains")
    # ── P0 · cô lập output (doc 155 §4.3) ─────────────────────────────────
    # Trước đây mọi lần chạy ghi đè `reports/answer_v2/` — báo cáo gốc của
    # AG1 bị mất, và người review không đối chiếu được run nào sinh ra số nào.
    ap.add_argument("--run-id", default=None,
                    help="ghi báo cáo vào reports/p0/<run-id>/ thay vì ghi đè")
    ap.add_argument("--report-dir", type=Path, default=None,
                    help="thư mục báo cáo tường minh; thắng --run-id")
    ap.add_argument("--allow-overwrite", action="store_true",
                    help="cho phép ghi đè ZIP candidate đã tồn tại")
    a = ap.parse_args()

    global REPORTS
    if a.report_dir:
        REPORTS = a.report_dir
    elif a.run_id:
        REPORTS = ROOT / "reports/p0" / a.run_id
    REPORTS.mkdir(parents=True, exist_ok=True)
    flags = {"router_fix": a.router_fix, "ontology_fix": a.ontology_fix}
    print(f"run_id={a.run_id or '(legacy)'}  reports={REPORTS.relative_to(ROOT)}  "
          f"flags={flags}")
    con = sqlite3.connect(f"file:{WORK}?mode=ro&immutable=1", uri=True)
    specs = MO.load()
    formulas = FR.load()
    plans = {p["qid"]: p for p in (json.loads(l) for l in PLANS.open(encoding="utf-8"))}

    if not a.parent.is_file():
        print(f"✗ không có parent ZIP: {a.parent}", file=sys.stderr)
        return 2
    with zipfile.ZipFile(a.parent) as z:
        parent_sub = json.loads(z.read("submission.json"))
    print(f"parent {a.parent.name}  sha256={sha256(a.parent)[:16]}…  "
          f"n={len(parent_sub)}")

    tmp = Path(tempfile.mkdtemp(prefix="ag1_"))
    data_dir = tmp / "data"
    data_dir.mkdir()
    da_ghi: set[str] = set()

    traces, t0 = [], time.time()
    qs = parent_sub[: a.limit] if a.limit else parent_sub
    for rec in qs:
        qid = rec["id"]
        pq = plans.get(int(qid)) or plans.get(str(qid))
        if pq is None:
            traces.append({"qid": qid, "route": "R0", "ok": False,
                           "reason": "NO_PLAN"})
            continue
        traces.append(mot_cau(con, rec, pq, specs, formulas, data_dir, da_ghi,
                              router_fix=a.router_fix,
                              ontology_fix=a.ontology_fix))

    # ── báo cáo ────────────────────────────────────────────────────────────
    ok = [t for t in traces if t.get("ok")]
    r2 = [t for t in traces if t.get("route") == "R2"]
    ly_do = Counter(t.get("reason") for t in traces if not t.get("ok"))
    theo_formula = Counter(t.get("formula_id") for t in ok)
    errs = Counter(e for t in traces for e in t.get("errs", []))
    aop = [t for t in r2 if t.get("all_operands_in_pool")]

    rep = {
        "_schema": "answer_v2 AG1_R2_FORMULA · route report",
        "candidate_id": a.candidate_id,
        "run_id": a.run_id,
        "flags": flags,
        "parent": a.parent.name, "parent_sha256": sha256(a.parent),
        "config_metrics_sha256": sha256(ROOT / "configs/answer_v2/metrics_v1.yaml"),
        "config_formulas_sha256": sha256(ROOT / "configs/answer_v2/formulas_v1.yaml"),
        "work_db_sha256_note": "xem identity/input_identity.txt (4,2 GB, không hash mỗi run)",
        "plans_sha256": sha256(PLANS),
        "n_question": len(qs),
        "n_route_R2": len(r2),
        "n_R2_thanh_cong": len(ok),
        "n_df_phan_bo": dict(Counter(t.get("n_df") for t in ok)),
        "all_operands_in_pool": (f"{len(aop)}/{len(r2)}" if r2 else "0/0"),
        "all_operands_in_pool_rate": round(len(aop) / len(r2), 4) if r2 else None,
        "theo_formula": dict(theo_formula.most_common()),
        "ly_do_khong_R2": dict(ly_do.most_common()),
        "failure_code": dict(errs.most_common()),
        "latency_s": round(time.time() - t0, 1),
        "command": " ".join(["python3", "tools/answer_v2/run_answer_v2.py"] + sys.argv[1:]),
    }
    (REPORTS / "route_report_1012.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    with (REPORTS / "run_trace_answer_v2.jsonl").open("w", encoding="utf-8") as f:
        for t in traces:
            f.write(json.dumps(t, ensure_ascii=False) + "\n")

    print(f"\nR2 exercised {len(r2)} · thành công {len(ok)} · "
          f"all-operands-in-pool {rep['all_operands_in_pool']}")
    print(f"theo formula: {json.dumps(dict(theo_formula), ensure_ascii=False)}")
    print(f"lý do không R2: {json.dumps(dict(ly_do.most_common(8)), ensure_ascii=False)}")
    if errs:
        print(f"failure code: {json.dumps(dict(errs), ensure_ascii=False)}")

    # ── đóng ZIP ───────────────────────────────────────────────────────────
    if a.build_zip and ok:
        by = {t["qid"]: t for t in ok}
        out = ROOT / f"artifacts/submissions/legacy/submission_{a.candidate_id}.zip"
        if out.exists() and not a.allow_overwrite:
            # FAIL CLOSED. Ghi đè âm thầm chính là cách `submission_AG1B_…zip`
            # ra đời với SHA của AG1 (0d207332…) — một artifact mang tên
            # candidate mới nhưng nội dung candidate cũ. Doc 155 §3.3(1)/(2)
            # bắt đúng lỗi này. Muốn ghi đè thì phải nói ra.
            print(f"✗ {out.name} đã tồn tại (sha {sha256(out)[:16]}…).",
                  file=sys.stderr)
            print("  Đặt --candidate-id khác, hoặc --allow-overwrite nếu CỐ Ý.",
                  file=sys.stderr)
            return 3
        n_thay = 0
        # ZIP TẤT ĐỊNH: `zipfile` nhúng mtime của tệp vào từng entry, nên hai
        # lần đóng cùng nội dung cho HAI SHA khác nhau (đã đo: cbd7… vs 3fc8…).
        # Điều đó phá hai thứ: gate "ZIP SHA chưa từng nộp" mất ý nghĩa, và
        # người review không tái tạo được checksum trong packet. Ghim mọi entry
        # về một mốc cố định.
        MOC = (2026, 1, 1, 0, 0, 0)

        def _ghi(zout, ten: str, data: bytes) -> None:
            zi = zipfile.ZipInfo(ten, date_time=MOC)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zout.writestr(zi, data)

        with zipfile.ZipFile(a.parent) as zin, \
                zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zout:
            sub = json.loads(zin.read("submission.json"))
            for rec in sub:
                t = by.get(rec["id"])
                if not t:
                    continue
                # CHỈ ba trường. `relevant_docs`/`relevant_tables` không đụng tới.
                rec["answer"] = t["answer"]
                rec["pandas_query"] = t["pandas_query"]
                rec["evidence"] = t["evidence"]
                n_thay += 1
            _ghi(zout, "submission.json",
                 json.dumps(sub, ensure_ascii=False, indent=1).encode("utf-8"))
            co_san = set(zin.namelist())
            for n in zin.namelist():
                if n != "submission.json":
                    _ghi(zout, n, zin.read(n))
            # CHỈ thêm CSV chưa có trong parent. Ghi đè tên trùng tạo HAI entry
            # cùng đường dẫn trong ZIP — `zipfile` cảnh báo, nhưng bộ giải nén
            # của người chấm có thể lấy entry nào tuỳ hiện thực. Bài nộp không
            # được phép có chỗ mơ hồ như vậy.
            for csvf in sorted(data_dir.iterdir()):
                ten = f"data/{csvf.name}"
                if ten in co_san:
                    continue
                _ghi(zout, ten, csvf.read_bytes())
        print(f"\n-> {out.name}  thay {n_thay} câu  sha256={sha256(out)[:16]}…")
        (REPORTS / "candidate_manifest.json").write_text(json.dumps({
            "candidate_id": a.candidate_id, "parent": a.parent.name,
            "parent_sha256": sha256(a.parent),
            "candidate_sha256": sha256(out),
            "candidate_zip": str(out.relative_to(ROOT)),
            "run_id": a.run_id,
            "flags": flags,
            "config_metrics_sha256": sha256(ROOT / "configs/answer_v2/metrics_v1.yaml"),
            "config_formulas_sha256": sha256(ROOT / "configs/answer_v2/formulas_v1.yaml"),
            "plans_sha256": sha256(PLANS),
            "command": " ".join(["python3", "tools/answer_v2/run_answer_v2.py"] + sys.argv[1:]),
            "n_question_changed": n_thay,
            "changed_fields": ["answer", "pandas_query", "evidence"],
            "unchanged_fields": ["relevant_docs", "relevant_tables", "question", "id"],
            "hypothesis": ("typed deterministic formula route R2 với 8 formula "
                           "SAFE cải thiện Execution/Answer Accuracy mà không "
                           "regression route cũ"),
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    shutil.rmtree(tmp, ignore_errors=True)
    print(f"-> {REPORTS}/route_report_1012.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
