#!/usr/bin/env python3
"""Cổng nộp C1 — chạy ĐỦ mọi dòng của review 127 §5 rồi ra một verdict.

Review 127 viết lại cổng C1 thành bốn nhóm; doc 126 chỉ có bốn dòng và một
trong số đó ("net delta DEV/gold45 dương") mập mờ giữa "dương ở cả hai" và
"dương ở một trong hai". Tệp này hiện thực hoá bản viết lại, và quy ước rõ:

    MỌI dòng bắt buộc phải PASS. Một dòng FAIL ⇒ giữ ZIP local, KHÔNG nộp.
    Dòng nào chưa đo được thì là NOT_MEASURED, và NOT_MEASURED ≠ PASS.

Cổng cố tình KHÔNG có đường tắt "gần đạt". Lượt public ~10/ngày và private 5
TỔNG là tài nguyên không hoàn lại; một cổng nới tay sẽ tiêu chúng cho những
thay đổi chưa chứng minh được.

Chạy:  python3 tools/c1_gate_report_v1.py artifacts/execution/candidates/submission_C1e.zip
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTROL = ROOT / "sync_122_1/controls/submission_P0I.zip"
ROLLBACK = "C0_SEMANTIC_CONTROL_3241 (submission_P0I.zip)"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def load(p: Path) -> list[dict]:
    with zipfile.ZipFile(p) as z:
        return json.loads(z.read("submission.json"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("candidate")
    a = ap.parse_args()
    cand = Path(a.candidate).resolve()

    sub = load(cand)
    base = load(CONTROL)
    b = {r["id"]: r for r in base}
    ids = [r["id"] for r in sub]

    checks: list[dict] = []

    def add(nhom: str, ten: str, verdict: str, chi_tiet) -> None:
        checks.append({"nhom": nhom, "check": ten, "verdict": verdict,
                       "chi_tiet": chi_tiet})

    # ── nhóm 1 · P0 packet ──────────────────────────────────────────────────
    rr = ROOT / "reports/reviewer_replay_report.json"
    if rr.is_file():
        d = json.loads(rr.read_text(encoding="utf-8"))
        add("P0_packet", "reviewer_replay_report",
            "PASS" if d["n_fail"] == 0 else "FAIL",
            {"n_pass": d["n_pass"], "n_fail": d["n_fail"], "n_skip": d["n_skip"],
             "fail": [c["check"] for c in d["checks"] if c["verdict"] == "FAIL"]})
    else:
        add(
            "P0_packet",
            "reviewer_replay_report",
            "NOT_MEASURED",
            "chưa chạy ops/environment/verify_packet.sh",
        )

    wv = ROOT / "artifacts/retrieval/workdb_verify_report.json"
    if wv.is_file():
        d = json.loads(wv.read_text(encoding="utf-8"))
        add("P0_packet", "workdb_rebuild_query", "PASS" if d["verdict"] == "PASS" else "FAIL",
            {"indexes_missing": d["indexes_missing"], "row_counts": d["row_counts"]})
    else:
        add("P0_packet", "workdb_rebuild_query", "NOT_MEASURED", "chưa chạy --verify-only")

    # ── nhóm 2 · Contract candidate ─────────────────────────────────────────
    add("Contract", "1012_unique_ids",
        "PASS" if len(ids) == 1012 and len(set(ids)) == 1012 else "FAIL",
        {"n": len(ids), "n_unique": len(set(ids))})

    p = subprocess.run([sys.executable, "tools/validate_submission.py", str(cand)],
                       cwd=ROOT, capture_output=True, text=True)
    add("Contract", "format_valid", "PASS" if p.returncode == 0 else "FAIL",
        {"exit": p.returncode})

    # Tách "query do emitter mới viết" khỏi "query kế thừa nguyên xi từ C0".
    # Gộp hai thứ này lại thì con số 966 không nói được emitter mới có sạch
    # không — mà đó mới là thứ cổng cần biết.
    changed = [r for r in sub
               if (r.get("pandas_query") or "") != (b[r["id"]].get("pandas_query") or "")]
    n_v0_new = sum(1 for r in changed if ".values[0]" in (r.get("pandas_query") or ""))
    n_v0_all = sum(1 for r in sub if ".values[0]" in (r.get("pandas_query") or ""))
    add("Contract", "first_cell_usage_query_MOI_bang_0",
        "PASS" if n_v0_new == 0 else "FAIL",
        {"n_query_moi": len(changed), "n_query_moi_dung_.values[0]": n_v0_new})
    add("Contract", "first_cell_usage_TOAN_BAI_bang_0",
        "PASS" if n_v0_all == 0 else "FAIL",
        {"n_toan_bai_dung_.values[0]": n_v0_all,
         "ghi_chu": ("Số này KẾ THỪA từ C0: emitter mới chỉ viết lại "
                     f"{len(changed)} câu, {1012 - len(changed)} câu còn lại giữ "
                     "nguyên query cũ. Cổng vẫn tính là FAIL vì hợp đồng nói "
                     "'first-cell usage = 0' cho BÀI NỘP, không phải cho phần "
                     "mới. Muốn xanh dòng này thì phải viết lại toàn bộ 1.012 "
                     "query — một thay đổi hành vi riêng, không nhét vào C1.")})

    p2 = subprocess.run([sys.executable, "tools/replay_submission_v1.py", str(cand)],
                        cwd=ROOT, capture_output=True, text=True)
    try:
        rep = json.loads(p2.stdout[p2.stdout.index("{"):])
        s = rep["summary"]
        n_query = sum(1 for r in sub if r.get("pandas_query"))
        add("Contract", "answer_eq_eval_query_100pct",
            "PASS" if rep["invariant_answer_eq_query"] == n_query else "FAIL",
            {"invariant": rep["invariant_answer_eq_query"], "n_co_query": n_query,
             "summary": s})
        add("Contract", "dem_rieng_tung_terminal_stage", "PASS", s)
    except Exception as e:
        add("Contract", "answer_eq_eval_query_100pct", "FAIL", f"replay lỗi: {e}")

    diff_ret = sum(1 for r in sub
                   if r.get("relevant_docs") != b[r["id"]].get("relevant_docs")
                   or r.get("relevant_tables") != b[r["id"]].get("relevant_tables"))
    add("Contract", "retrieval_fields_bat_bien", "PASS" if diff_ret == 0 else "FAIL",
        {"n_cau_doi_retrieval_fields": diff_ret,
         "ghi_chu": "C1 là execution-only ⇒ relevant_docs/tables phải y hệt C0"})

    # ── nhóm 3 · Internal DEV ───────────────────────────────────────────────
    add("Internal_DEV", "paired_delta_exact_tren_DEV", "NOT_MEASURED",
        {"ly_do": "DEV-60 CHƯA có nhãn — pilot gán nhãn là việc tay người, chưa chạy",
         "he_qua": "cổng C1 KHÔNG thể xanh trong phiên này dù mọi thứ khác pass"})
    add("Internal_DEV", "regressed_P0_SIGN_UNIT_MULTIPLICITY_bang_0", "NOT_MEASURED",
        {"ly_do": "bộ regression 34 câu UNIT_SCALE (docs/103 F2) chưa được dựng thành suite chạy được"})

    # ── nhóm 4 · Gold45 TRAIN_FIT — CHẤM TRỰC TIẾP TRÊN ZIP ─────────────────
    # Bản đầu đọc `reports/c1_ablation_v1.json`. Sai: bảng ablation dựng từ
    # `decisions` TRƯỚC bộ lọc multiplicity trong `build_zip`, nên cổng chứng
    # nhận một CẤU HÌNH chứ không phải cái ZIP nó vừa băm (47 emit vs 45 câu
    # thực sự ghi). Nay chấm thẳng file.
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/dev/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}

    def khop(got, want, tol: float = 0.01) -> bool:
        try:
            x, w = float(got), float(want)
        except (TypeError, ValueError):
            return False
        if x != x or w != w:
            return False
        return abs(x) <= tol if w == 0 else abs(x - w) / abs(w) <= tol

    s = {r["id"]: r for r in sub}
    ok_c = {q: khop(s[q].get("answer"), g["dap_an_gold"]) for q, g in gold.items()}
    ok_b = {q: khop(b[q].get("answer"), g["dap_an_gold"]) for q, g in gold.items()}
    lk = [q for q, g in gold.items() if g["lop"] == "lookup"]
    n_touch = sum(1 for q in gold
                  if (s[q].get("pandas_query") or "") != (b[q].get("pandas_query") or ""))
    net = sum(ok_c.values()) - sum(ok_b.values())
    add("Gold45_TRAIN_FIT", "khong_giam_tong",
        "PASS" if sum(ok_c.values()) >= sum(ok_b.values()) else "FAIL",
        {"C0": sum(ok_b.values()), "candidate": sum(ok_c.values()), "net": net,
         "n_gold_bi_ghi_de_trong_ZIP": n_touch,
         "canh_bao": ("n_gold_bi_ghi_de nhỏ ⇒ 'net 0' là KHÔNG-ĐO-ĐƯỢC, "
                      "không phải 'trung tính'") if n_touch < 5 else None})
    add("Gold45_TRAIN_FIT", "khong_giam_lookup",
        "PASS" if sum(ok_c[q] for q in lk) >= sum(ok_b[q] for q in lk) else "FAIL",
        {"C0": sum(ok_b[q] for q in lk), "candidate": sum(ok_c[q] for q in lk),
         "n_lookup": len(lk)})
    add("Gold45_TRAIN_FIT", "co_gain_thuc_su", "PASS" if net > 0 else "FAIL",
        {"net": net, "improved": sorted(q for q in gold if ok_c[q] and not ok_b[q]),
         "regressed": sorted(q for q in gold if ok_b[q] and not ok_c[q]),
         "ghi_chu": "net = 0 KHÔNG phải PASS. Nộp một bản không đổi điểm "
                    "là tiêu một lượt để mua zero thông tin."})
    cal = ROOT / "reports/c1_gate_calibration_v1.json"
    if cal.is_file():
        d = json.loads(cal.read_text(encoding="utf-8"))
        add("Gold45_TRAIN_FIT", "gain_dat_y_nghia_thong_ke",
            "PASS" if d.get("co_nguong_dat_y_nghia_thong_ke") else "FAIL",
            {"ket_luan": d["KET_LUAN"]})

    # ── nhóm 5 · Process ────────────────────────────────────────────────────
    # Ba dòng này TỪNG là `PASS` hằng số — tức không kiểm gì mà vẫn tô xanh.
    # Một cổng có dòng luôn xanh là một cổng nói dối về số dòng nó đã kiểm.
    si = json.loads((ROOT / "identity/source_identity.json").read_text(encoding="utf-8"))
    add("Process", "hash_day_du", "PASS", {
        "candidate_zip_sha256": sha256(cand),
        "control_zip_sha256": sha256(CONTROL),
        "source_tree_sha256": si["tree_sha256"],
        "source_tree_sha256_do_luc": si.get("generated"),
        "workdb_sha256_REFERENCED_NOT_RECOMPUTED":
            "e9f62775a75794d770954ba1903f7a90c8b97467e5398b0baa2057bec8e67d5f",
        "canh_bao": ("workdb SHA là số TRÍCH từ identity, không băm lại ở đây "
                     "(4,24 GB). `tree_sha256` có thể đã đổi nếu source đổi sau "
                     "lần chạy build_source_identity_v1.py gần nhất."),
    })
    rb = ROOT / "sync_122_1/controls/submission_P0I.zip"
    add("Process", "rollback_ton_tai_va_bam_duoc", "PASS" if rb.is_file() else "FAIL",
        {"rollback": ROLLBACK, "sha256": sha256(rb) if rb.is_file() else None})
    pre = ROOT / "docs/PREREGISTRATION_C1.md"
    add("Process", "preregistration_ky_truoc_khi_xem_diem",
        "NOT_VERIFIABLE" if pre.is_file() else "FAIL",
        {"file": "docs/PREREGISTRATION_C1.md",
         "sha256": sha256(pre) if pre.is_file() else None,
         "vi_sao_khong_kiem_duoc": (
             "Không có neo thời gian độc lập (file untracked, không chữ ký, "
             "không commit). Bản thân nó chứa §5 KẾT QUẢ nên được viết CÙNG "
             "LÚC hoặc SAU khi đo. Tuyên bố 'ký trước' hiện dựa vào lời nói, "
             "không dựa vào bằng chứng."),
         "cach_sua": ("commit tệp prereg TRƯỚC khi chạy đo, hoặc băm nó vào "
                      "một artifact có timestamp bên ngoài, rồi đối chiếu.")})

    n_fail = sum(c["verdict"] == "FAIL" for c in checks)
    n_nm = sum(c["verdict"] == "NOT_MEASURED" for c in checks)
    n_nv = sum(c["verdict"] == "NOT_VERIFIABLE" for c in checks)
    verdict = ("GO_SUBMIT" if n_fail == 0 and n_nm == 0 and n_nv == 0
               else "HOLD_KHONG_NOP")

    out = {
        "_schema": "c1_gate_report v1 — cổng nộp theo review 127 §5",
        "date": "2026-08-21",
        "candidate": str(cand.relative_to(ROOT)),
        "control_rollback": ROLLBACK,
        "quy_uoc": "MỌI dòng phải PASS. NOT_MEASURED ≠ PASS.",
        "n_check": len(checks), "n_pass": sum(c["verdict"] == "PASS" for c in checks),
        "n_fail": n_fail, "n_not_measured": n_nm,
        "n_not_verifiable": sum(c["verdict"] == "NOT_VERIFIABLE" for c in checks),
        "VERDICT": verdict,
        "checks": checks,
        "command": f"python3 tools/c1_gate_report_v1.py {cand}",
    }
    dst = ROOT / f"reports/c1_gate_report_{cand.stem.replace('submission_','')}.json"
    dst.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    for c in checks:
        print(f"  {c['verdict']:13} {c['nhom']:16} {c['check']}")
    print(f"\n{verdict}   (pass {out['n_pass']} / fail {n_fail} / chưa đo {n_nm})")
    print("->", dst.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
