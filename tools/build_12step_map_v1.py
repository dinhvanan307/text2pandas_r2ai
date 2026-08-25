#!/usr/bin/env python3
"""Bản đồ đủ 12 bước — đóng doc 140 §2.1.

Doc 137 viết "11/12 bước khớp artifact" nhưng bảng chỉ liệt kê 6 dòng. Từ bảng
ấy không ai xác định được bước nào là bước thứ 12, "khớp" nghĩa là gì, và
artifact nào sinh ra bởi lệnh nào. Doc 140 đòi bảng 12 dòng đủ cột.

Quy ước "khớp" ở đây — nói rõ để không ai phải đoán:

    PASS          artifact tồn tại VÀ số quan sát được == số kỳ vọng đã khai
    MISMATCH      artifact tồn tại nhưng số quan sát ≠ số kỳ vọng
    MISSING       không có artifact
    NOT_MEASURED  bước không sinh artifact để đối chiếu (chỉ in ra màn hình)

Bước nào không PASS thì KHÔNG được đếm vào "n bước khớp".

`code_sha256` là băm của chính script sinh artifact — để biết artifact được tạo
bởi phiên bản code nào. `input_identity` là băm của các đầu vào chính.

Chạy:  python3 tools/build_12step_map_v1.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# (step_id, lệnh, script, artifact, đường dẫn số quan sát, số kỳ vọng)
# `duong_dan` dùng dấu chấm để đi vào JSON; None ⇒ không đối chiếu số.
STEPS = [
    # ⚠️ doc 140 §1.3 liệt kê `reports/unit_overrides_v1.json` là artifact thiếu.
    # Nó không thiếu — nó KHÔNG BAO GIỜ mang tên đó. Bước 1 ghi vào
    # `configs/execution/unit_scale_overrides_v1.json`, bước 2 ghi vào
    # `tests/expected_p0_cases.meta.json`. Doc 137 đặt tên sai trong bảng, và
    # người review dò theo tên sai nên báo MISSING. Đây là lỗi của tài liệu,
    # không phải lỗi của pipeline — nhưng hậu quả giống hệt nhau: reviewer
    # không tìm được bằng chứng.
    (1, "python3 tools/build_unit_overrides_v1.py",
     "tools/build_unit_overrides_v1.py", "configs/execution/unit_scale_overrides_v1.json",
     "n_override_uid", 34),
    (2, "python3 tools/build_expected_p0_cases_v1.py",
     "tools/build_expected_p0_cases_v1.py", "tests/expected_p0_cases.meta.json",
     "n_case", 47),
    (3, "python3 tools/run_p0_suite_v1.py",
     "tools/run_p0_suite_v1.py", "reports/p0_suite_v1.json",
     "VERDICT", "P0_GREEN"),
    (4, "python3 tools/reference_eval_v1.py --self-check && python3 tools/reference_eval_v1.py",
     "tools/reference_eval_v1.py", "reports/reference_eval_v1.json",
     "phan_1_O6_cham_GOLD.khop", 45),
    (5, "python3 tools/run_arith_eval_v1.py",
     "tools/run_arith_eval_v1.py", "reports/arith_eval_v1.json",
     "summary.C3.numeric_exact", "8/24"),
    (6, "python3 tools/run_oracle_table_v1.py",
     "tools/run_oracle_table_v1.py", "reports/oracle_table_v1.json",
     "bang_oracle.O4.correct", 24),
    (7, "python3 tools/build_qid_slices_v1.py",
     "tools/build_qid_slices_v1.py", "reports/paired_slices_v1.json",
     "bang_paired.C3.mcnemar_p_hai_phia", 0.0391),
    (8, "python3 tools/run_joint_ab_v1.py",
     "tools/run_joint_ab_v1.py", "reports/joint_ab_v1.json",
     "GATE_2.ket_qua", "FAIL"),
    (9, "python3 tools/diag_slot_scoring_v1.py",
     "tools/diag_slot_scoring_v1.py", "reports/diag_slot_scoring_v1.json",
     "tom_tat.gold_top1", 19),
    (10, "python3 tools/run_scoring_ablation_v2.py",
     "tools/run_scoring_ablation_v2.py", "reports/scoring_ablation_v2.json",
     "ablation.S5.slot_top1", "29/66"),
    (11, "bash ops/environment/verify_packet.sh",
     "ops/environment/verify_packet.sh", "reports/reviewer_replay_report.json",
     "n_fail", 0),
    (12, "python3 tools/submission_gate_v1.py",
     "tools/submission_gate_v1.py", "reports/submission_gate_v1.json",
     "VERDICT", "HOLD_KHONG_NOP"),
]


def sha256(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def dig(o, path: str):
    for k in path.split("."):
        if isinstance(o, dict) and k in o:
            o = o[k]
        else:
            return None
    return o


def main() -> int:
    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip() or None
    except Exception:
        head = None

    inputs = {p: sha256(ROOT / p) for p in (
        "artifacts/retrieval/work.db",
        "evaluation/question_plans_1012.jsonl",
        "data/dev/gold_dap_an/gold_dap_an_v1.jsonl")}

    rows, n_pass = [], 0
    for sid, cmd, script, art, path, want in STEPS:
        ap, sp = ROOT / art, ROOT / script
        art_sha = sha256(ap)
        obs = None
        if art_sha and ap.suffix == ".json":
            try:
                obs = dig(json.loads(ap.read_text(encoding="utf-8")), path) if path else None
            except Exception:
                obs = "PARSE_ERROR"
        if art_sha is None:
            verdict = "MISSING"
        elif path is None:
            verdict = "NOT_MEASURED"
        elif isinstance(want, float) and isinstance(obs, (int, float)):
            verdict = "PASS" if abs(obs - want) < 1e-9 else "MISMATCH"
        else:
            verdict = "PASS" if obs == want else "MISMATCH"
        n_pass += verdict == "PASS"
        rows.append({
            "step_id": sid, "command": cmd,
            "script": script, "code_sha256": sha256(sp),
            "artifact": art, "artifact_sha256": art_sha,
            "artifact_mtime_utc": (datetime.fromtimestamp(
                ap.stat().st_mtime, timezone.utc).isoformat() if art_sha else None),
            "duong_dan_so": path, "expected": want, "observed": obs,
            "verdict": verdict})

    rep = {
        "_schema": "12_step_execution_map v1 — đóng doc 140 §2.1",
        "date": "2026-08-21",
        "dinh_nghia_khop": {
            "PASS": "artifact tồn tại VÀ observed == expected",
            "MISMATCH": "artifact tồn tại nhưng observed ≠ expected",
            "MISSING": "không có artifact",
            "NOT_MEASURED": "bước không sinh số để đối chiếu — KHÔNG tính là khớp",
        },
        "source_commit_HEAD": head,
        "canh_bao_HEAD": ("HEAD là fbd36c8 (17/08) trong khi cây làm việc đã đổi "
                          "nhiều. code_sha256 dưới đây là băm FILE THỰC TẾ trên đĩa, "
                          "KHÔNG phải file tại commit HEAD. Chưa commit thì artifact "
                          "không neo được vào lịch sử."),
        "input_identity": inputs,
        "n_step": len(rows),
        "n_pass": n_pass,
        "n_mismatch": sum(r["verdict"] == "MISMATCH" for r in rows),
        "n_missing": sum(r["verdict"] == "MISSING" for r in rows),
        "n_not_measured": sum(r["verdict"] == "NOT_MEASURED" for r in rows),
        "dinh_chinh_doc_137": ("doc 137 viết '11/12 bước khớp artifact' nhưng chỉ "
                               "liệt kê 6 dòng và không định nghĩa 'khớp'. Con số "
                               "đúng theo định nghĩa ở trên là n_pass dưới đây."),
        "steps": rows,
        "command": "python3 tools/build_12step_map_v1.py",
    }
    (ROOT / "reports/12_step_execution_map.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"{'#':>2} {'verdict':13} {'expected':>16} {'observed':>16}  artifact")
    for r in rows:
        print(f"{r['step_id']:>2} {r['verdict']:13} {str(r['expected'])[:16]:>16} "
              f"{str(r['observed'])[:16]:>16}  {r['artifact']}")
    print(f"\nPASS {n_pass}/{len(rows)} · MISMATCH {rep['n_mismatch']} · "
          f"MISSING {rep['n_missing']} · NOT_MEASURED {rep['n_not_measured']}")
    print("-> reports/12_step_execution_map.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
