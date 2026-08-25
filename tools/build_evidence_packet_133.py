#!/usr/bin/env python3
"""Đóng `sync_133_evidence` — đúng cây thư mục doc 134 §3, đóng P0-1.

Doc 134 §2.2 tìm 6 report trên máy local và không thấy, nên xếp mọi claim của
133 là `REPORTED_BUILD_MACHINE`. Đúng quy trình. Gói này chuyển chúng sang
`INDEPENDENTLY_VERIFIABLE`: mỗi report kèm provenance, packet kèm lệnh replay từ
bản giải nén sạch.

KHÔNG gửi A6, work.db, model weights — đúng yêu cầu §3.

Chạy:  python3 tools/build_evidence_packet_133.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = "sync_133_evidence"

ITEMS: list[tuple[str, str]] = [
    ("identity/source_identity.json", "identity/source_identity.json"),
    ("identity/environment_identity.json", "identity/environment_identity.json"),
    ("identity/SOURCE_SELECTION.json", "identity/SOURCE_SELECTION.json"),
    ("identity/AUDIT_SELECTION_SEAL.json", "identity/AUDIT_SELECTION_SEAL.json"),
    ("identity/access_log.json", "identity/access_log.json"),

    ("reports/reference_eval_v1.json", "reports/reference_eval_v1.json"),
    ("reports/arith_eval_v1.json", "reports/arith_eval_v1.json"),
    ("reports/p0_suite_v1.json", "reports/p0_suite_v1.json"),
    ("reports/git_inventory_v1.json", "reports/git_inventory_v1.json"),
    ("reports/dev_label_status_v1.json", "reports/dev_label_status_v1.json"),
    ("reports/oracle_table_v1.json", "reports/oracle_table_v1.json"),
    ("reports/paired_slices_v1.json", "reports/paired_slices_v1.json"),
    ("reports/joint_ab_v1.json", "reports/joint_ab_v1.json"),
    ("reports/submission_gate_v1.json", "reports/submission_gate_v1.json"),
    ("reports/fact_slot_evidence_v1.json", "reports/fact_slot_evidence_v1.json"),
    ("reports/c1_ablation_v1.json", "reports/c1_ablation_v1.json"),
    ("reports/c1_ablation_v1_det.json", "reports/c1_ablation_v1_det.json"),
    ("reports/reviewer_replay_report.json", "reports/reviewer_replay_report.json"),

    ("configs/execution/promotion_rule_v1.yaml", "configs/execution/promotion_rule_v1.yaml"),
    ("configs/execution/formula_registry_v1.yaml", "configs/execution/formula_registry_v1.yaml"),
    ("configs/execution/metric_registry_v1.yaml", "configs/execution/metric_registry_v1.yaml"),
    ("configs/execution/unit_scale_overrides_v1.json", "configs/execution/unit_scale_overrides_v1.json"),

    ("tools/reference_eval_v1.py", "tools/reference_eval_v1.py"),
    ("tools/run_arith_eval_v1.py", "tools/run_arith_eval_v1.py"),
    ("tools/run_p0_suite_v1.py", "tools/run_p0_suite_v1.py"),
    ("tools/run_oracle_table_v1.py", "tools/run_oracle_table_v1.py"),
    ("tools/run_joint_ab_v1.py", "tools/run_joint_ab_v1.py"),
    ("tools/build_qid_slices_v1.py", "tools/build_qid_slices_v1.py"),
    ("tools/build_unit_overrides_v1.py", "tools/build_unit_overrides_v1.py"),
    ("tools/build_expected_p0_cases_v1.py", "tools/build_expected_p0_cases_v1.py"),
    ("tools/dev_label_status_v1.py", "tools/dev_label_status_v1.py"),
    ("tools/git_inventory_v1.py", "tools/git_inventory_v1.py"),
    ("tools/submission_gate_v1.py", "tools/submission_gate_v1.py"),
    ("tools/execution/__init__.py", "tools/execution/__init__.py"),
    ("tools/execution/fact_rank_v1.py", "tools/execution/fact_rank_v1.py"),
    ("tools/execution/operand_pipeline_v1.py", "tools/execution/operand_pipeline_v1.py"),
    ("tools/execution/emit_lookup_v1.py", "tools/execution/emit_lookup_v1.py"),
    ("tools/execution/emit_arith_v1.py", "tools/execution/emit_arith_v1.py"),
    ("tools/execution/joint_search_v1.py", "tools/execution/joint_search_v1.py"),

    ("evaluation/qid_slices.json", "evaluation/qid_slices.json"),
    ("evaluation/arith_traces_v1.jsonl", "evaluation/arith_traces_v1.jsonl"),
    ("evaluation/fact_candidates_gold45_v12.jsonl", "evaluation/fact_candidates_gold45_v12.jsonl"),

    ("tests/expected_p0_cases.jsonl", "tests/expected_p0_cases.jsonl"),
    ("tests/expected_p0_cases.meta.json", "tests/expected_p0_cases.meta.json"),
    ("tests/execution/test_p0_families_v1.py", "tests/execution/test_p0_families_v1.py"),

    ("data/dev/gold_dap_an/gold_dap_an_v1.jsonl", "data/dev/gold_dap_an/gold_dap_an_v1.jsonl"),
    ("data/dev/execution_gold/dev60_selection.json", "data/dev/execution_gold/dev60_selection.json"),
    ("data/dev/execution_gold/audit40_selection.json", "data/dev/execution_gold/audit40_selection.json"),
    ("data/dev/execution_gold/dev60_labels.jsonl", "data/dev/execution_gold/dev60_labels.jsonl"),

    ("docs/132_RESOLVE_REVIEW_131.md", "docs/132_RESOLVE_REVIEW_131.md"),
    ("docs/133_REVIEW_132B_AND_OPTIMAL_MASTER_PLAN.md", "docs/133_REVIEW_132B_AND_OPTIMAL_MASTER_PLAN.md"),
    ("docs/135_EXECUTE_PLAN_133.md", "docs/135_EXECUTE_PLAN_133.md"),
]

README = """# sync_133_evidence — gói bằng chứng cho doc 134 §3 (P0-1)

**Ngày:** 21/08/2026 · **Máy build:** Linux sandbox CPython 3.10.12 · pandas 2.3.3 · numpy 2.2.6
⚠️ `MEASURED_OFF_CONTRACT_PY310` — `pyproject` đòi `>=3.11`.

## Vì sao có gói này

Doc 134 §2.2 tìm 6 report trên máy local và không thấy ⇒ xếp mọi claim của 133 là
`REPORTED_BUILD_MACHINE`. Đúng quy trình. Gói này chuyển chúng thành thứ **kiểm
được**: mỗi report có provenance, mỗi lệnh chạy lại được.

## KHÔNG gửi (đúng §3)

| | |
|---|---|
| A6 package 1,68 GB | SHA `23c3b96e…53be` đã khớp hai máy |
| `work.db` 4,24 GB | dựng lại: `bash tools/build_retrieval_workdb.sh <silver.db> <work.db>` |
| model weights | chưa dùng LLM |

## Replay từ bản giải nén sạch

Các lệnh sau **không cần work.db** — chúng đọc report/config/expectation đã có:

```bash
sha256sum -c MANIFEST.sha256
python3 tools/reference_eval_v1.py --self-check      # O6 độc lập, quét AST
python3 tools/run_p0_suite_v1.py                     # P0 suite, không cần pytest
python3 tools/build_expected_p0_cases_v1.py          # cần artifacts/execution/h0/
```

Các lệnh cần `work.db` (chạy trong repo đầy đủ):

```bash
python3 tools/run_arith_eval_v1.py
python3 tools/run_oracle_table_v1.py
python3 tools/run_joint_ab_v1.py
python3 tools/build_qid_slices_v1.py
python3 tools/submission_gate_v1.py
```

## Ba kết quả lật kết luận của Plan 133

1. **Bảng oracle** (`reports/oracle_table_v1.json`) — `O4−O2 = +15` MEASURED_DOMINANT,
   `O2−O0 = +1`, `O6−O4 = 0`. Xác nhận giả thuyết 133 bằng bảng thật, không phải suy từ 3 ca.
2. **`emitter_numeric_exact_given_gold_operands = 24/24`** trên ĐỦ 24 câu — đóng P0-3.
   Con số `≈100%` của 133 hoá ra ĐÚNG, nhưng trước đó chưa được đo hợp lệ.
3. **Joint search KHÔNG thắng top-1 độc lập** (`reports/joint_ab_v1.json`):
   `operand_set_exact 3/24` ở **cả hai** nhánh, delta `0,0` điểm %. Bảy biến thể
   ràng buộc đều cho cùng kết quả. **Gate 2 FAIL** ⇒ M6 của Plan 133 bị bác bằng đo.

## Trạng thái nộp bài

`reports/submission_gate_v1.json` → **`HOLD_KHONG_NOP`**. Không có official
submission nào được thực hiện trong vòng này.
"""


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def main() -> int:
    import tempfile
    stage = Path(tempfile.mkdtemp(prefix=f"{NAME}_")) / NAME
    stage.mkdir(parents=True)

    copied, missing = [], []
    for src, rel in ITEMS:
        s = ROOT / src
        if not s.is_file():
            missing.append(src)
            continue
        d = stage / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(s, d)
        copied.append(rel)

    # provenance chung cho cả gói
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    sid = json.loads((ROOT / "identity/source_identity.json").read_text(encoding="utf-8"))
    prov = {
        "_schema": "provenance chung cho sync_133_evidence",
        "date": "2026-08-21",
        "source_commit": head,
        "source_tree_sha256": sid["tree_sha256"],
        "n_source_files": sid["n_files"],
        "dirty": sid["dirty"],
        "python": "3.10.12", "pandas": "2.3.3", "numpy": "2.2.6",
        "platform": "Linux aarch64 sandbox",
        "nhan_bat_buoc": ["MEASURED_OFF_CONTRACT_PY310"],
        "workdb_sha256": "e9f62775a75794d770954ba1903f7a90c8b97467e5398b0baa2057bec8e67d5f",
        "a6_package_sha256": "23c3b96e4338e8785c2dcfcdfebf147dc7b7dfb6438c46c590be1ecbfe2453be",
        "parent_candidate": "C0_SEMANTIC_CONTROL_3241 (ID 3241, Execution 0,1225)",
        "gold_dataset": "gold_dap_an_v1 (45 câu, 45/45 row_label_exact, TRAIN_FIT)",
        "tolerance_tuong_doi": 0.01,
        "official_submission_thuc_hien": False,
    }
    (stage / "identity/parent_candidate_identity.json").write_text(
        json.dumps(prov, ensure_ascii=False, indent=1), encoding="utf-8")
    copied.append("identity/parent_candidate_identity.json")

    (stage / "logs").mkdir(exist_ok=True)
    (stage / "logs/commands.md").write_text(
        "# Lệnh đã chạy để sinh các report trong gói này\n\n"
        "```bash\n"
        "python3 tools/build_unit_overrides_v1.py\n"
        "python3 tools/build_expected_p0_cases_v1.py\n"
        "python3 tools/run_p0_suite_v1.py\n"
        "python3 tools/reference_eval_v1.py --self-check\n"
        "python3 tools/reference_eval_v1.py\n"
        "python3 tools/run_arith_eval_v1.py\n"
        "python3 tools/run_oracle_table_v1.py\n"
        "python3 tools/build_qid_slices_v1.py\n"
        "python3 tools/run_joint_ab_v1.py\n"
        "python3 tools/dev_label_status_v1.py\n"
        "python3 tools/git_inventory_v1.py\n"
        "python3 tools/submission_gate_v1.py\n"
        "```\n", encoding="utf-8")
    copied.append("logs/commands.md")

    (stage / "README.md").write_text(README, encoding="utf-8")
    lines = [f"{sha256(stage / r)}  {r}" for r in sorted(copied)]
    (stage / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")

    zp = ROOT / f"{NAME}.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                z.write(p, str(p.relative_to(stage)))
    zsha = sha256(zp)
    (ROOT / f"{NAME}.sha256").write_text(f"{zsha}  {NAME}.zip\n", encoding="utf-8")
    shutil.rmtree(stage.parent, ignore_errors=True)

    print(f"file trong manifest : {len(copied)}")
    print(f"thiếu               : {missing or 'không'}")
    print(f"zip                 : {zp.name}  {zp.stat().st_size:,} bytes")
    print(f"zip sha256          : {zsha}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
