#!/usr/bin/env python3
"""Đóng packet bổ sung `sync_122_2` — đúng cây thư mục review 127 §7.

KHÁC sync_122_1 ở ba điểm, cả ba đều là lỗi đã được chỉ ra:

1. **Không một byte `.pyc`.** Packet cũ chứa 242 mục bytecode trộn interpreter
   3.10/3.11/3.13/3.14 — phình gói và không phải source.
2. **Không gửi lại A6, work.db, control ZIP.** SHA đã khớp hai máy; gửi lại
   1,68 GB để chứng minh một thứ đã chứng minh rồi là lãng phí băng thông.
   Packet này là BỔ SUNG, đọc cùng sync_122_1.
3. **Chạy được từ bản giải nén sạch.** `ops/environment/bootstrap_review_env.sh`
   dựng venv, `ops/environment/verify_packet.sh` chạy 8 mục và ghi verdict máy
   đọc được.

Chạy:  python3 tools/build_sync_packet_v2.py
"""
from __future__ import annotations

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DST = ROOT / "sync_122_2"

# (nguồn, đích trong packet). Thiếu file thì BÁO, không im lặng bỏ qua —
# một packet thiếu file mà không ai biết là cách sinh ra "đã gửi rồi mà".
ITEMS: list[tuple[str, str]] = [
    ("packet_kind.json", "packet_kind.json"),
    # identity
    ("identity/source_identity.json", "identity/source_identity.json"),
    ("identity/environment_identity.json", "identity/environment_identity.json"),
    ("identity/AUDIT_SELECTION_SEAL.json", "identity/AUDIT_SELECTION_SEAL.json"),
    ("identity/access_log.json", "identity/access_log.json"),
    ("identity/final_audit_seal.json", "identity/final_audit_seal.json"),
    ("identity/SOURCE_SELECTION.json", "identity/SOURCE_SELECTION.json"),
    # môi trường
    ("ops/environment/bootstrap_review_env.sh", "ops/environment/bootstrap_review_env.sh"),
    ("ops/environment/requirements-review.txt", "ops/environment/requirements-review.txt"),
    ("ops/environment/verify_packet.sh", "ops/environment/verify_packet.sh"),
    # tools mới / đã sửa
    ("tools/build_retrieval_workdb.sh", "tools/build_retrieval_workdb.sh"),
    ("tools/build_source_identity_v1.py", "tools/build_source_identity_v1.py"),
    ("tools/question_plan_v1.py", "tools/question_plan_v1.py"),
    ("tools/build_metric_registry_v1.py", "tools/build_metric_registry_v1.py"),
    ("tools/fact_candidates_v1.py", "tools/fact_candidates_v1.py"),
    ("tools/fact_slot_report_v1.py", "tools/fact_slot_report_v1.py"),
    ("tools/select_dev_audit_v1.py", "tools/select_dev_audit_v1.py"),
    ("tools/build_label_dossier_v1.py", "tools/build_label_dossier_v1.py"),
    ("tools/build_candidate_v1.py", "tools/build_candidate_v1.py"),
    ("tools/c1_gate_calibration_v1.py", "tools/c1_gate_calibration_v1.py"),
    ("tools/c1_gate_report_v1.py", "tools/c1_gate_report_v1.py"),
    ("tools/pilot_labels_v1.py", "tools/pilot_labels_v1.py"),
    ("tools/crossmachine_check_v1.py", "tools/crossmachine_check_v1.py"),
    ("tools/eval_answer_v1.py", "tools/eval_answer_v1.py"),
    ("tools/replay_submission_v1.py", "tools/replay_submission_v1.py"),
    ("tools/validate_submission.py", "tools/validate_submission.py"),
    ("tools/execution/__init__.py", "tools/execution/__init__.py"),
    ("tools/execution/fact_rank_v1.py", "tools/execution/fact_rank_v1.py"),
    ("tools/execution/emit_lookup_v1.py", "tools/execution/emit_lookup_v1.py"),
    # configs
    ("configs/execution/metric_registry_v1.yaml", "configs/execution/metric_registry_v1.yaml"),
    ("configs/execution/formula_registry_v1.yaml", "configs/execution/formula_registry_v1.yaml"),
    ("configs/execution/a6_identity.yaml", "configs/execution/a6_identity.yaml"),
    # evaluation (per-slot evidence — thứ review 127 §7 đòi)
    ("data/curated/evaluation/legacy/question_plans_1012.jsonl", "data/curated/evaluation/legacy/question_plans_1012.jsonl"),
    ("data/curated/evaluation/legacy/fact_candidates_gold45_v10.jsonl", "data/curated/evaluation/legacy/fact_candidates_gold45_v10.jsonl"),
    ("data/curated/evaluation/legacy/fact_candidates_gold45_v11.jsonl", "data/curated/evaluation/legacy/fact_candidates_gold45_v11.jsonl"),
    ("data/curated/evaluation/legacy/fact_candidates_gold45_v12.jsonl", "data/curated/evaluation/legacy/fact_candidates_gold45_v12.jsonl"),
    ("data/curated/evaluation/legacy/run_trace_1012.jsonl", "data/curated/evaluation/legacy/run_trace_1012.jsonl"),
    # selections + schema nhãn
    ("data/curated/dev-legacy/execution_gold/dev60_selection.json", "data/curated/dev-legacy/execution_gold/dev60_selection.json"),
    ("data/curated/dev-legacy/execution_gold/audit40_selection.json", "data/curated/dev-legacy/execution_gold/audit40_selection.json"),
    ("data/curated/dev-legacy/execution_gold/label_template_schema.json", "data/curated/dev-legacy/execution_gold/label_template_schema.json"),
    ("data/curated/dev-legacy/execution_gold/dev60_labels.jsonl", "data/curated/dev-legacy/execution_gold/dev60_labels.jsonl"),
    ("data/curated/dev-legacy/gold_dap_an/gold_dap_an_v1.jsonl", "data/curated/dev-legacy/gold_dap_an/gold_dap_an_v1.jsonl"),
    # reports
    ("reports/fact_slot_evidence_v1.json", "reports/fact_slot_evidence_v1.json"),
    ("reports/question_plan_v1_report.json", "reports/question_plan_v1_report.json"),
    ("reports/metric_registry_v1_coverage.json", "reports/metric_registry_v1_coverage.json"),
    ("reports/fact_candidates_v1_recall.json", "reports/fact_candidates_v1_recall.json"),
    ("reports/labeling_batch_size_report.json", "reports/labeling_batch_size_report.json"),
    ("reports/labeling_batch_size_report_v2.json", "reports/labeling_batch_size_report_v2.json"),
    ("reports/c1_ablation_v1.json", "reports/c1_ablation_v1.json"),
    ("reports/c1_ablation_v1_det.json", "reports/c1_ablation_v1_det.json"),
    ("reports/c1_gate_calibration_v1.json", "reports/c1_gate_calibration_v1.json"),
    ("reports/c1_gate_report_C1e.json", "reports/c1_gate_report_C1e.json"),
    ("reports/reviewer_replay_report.json", "reports/reviewer_replay_report.json"),
    ("reports/crossmachine/fact_slot__linux-aarch64-py3.10.12.json",
     "reports/crossmachine/fact_slot__linux-aarch64-py3.10.12.json"),
    ("ops/environment/review_env_actual.json", "ops/environment/review_env_actual.json"),
    ("reports/primary_boost_verification.json", "reports/primary_boost_verification.json"),
    ("reports/submission_P0I_clean_replay.json", "reports/submission_P0I_clean_replay.json"),
    # rebuild
    ("artifacts/runs/retrieval/workdb_verify_report.json", "rebuild/workdb_verify_report.json"),
    ("sync_122_1/rebuild/expected_workdb_identity.json", "rebuild/expected_workdb_identity.json"),
    # docs
    ("docs/PREREGISTRATION_C1.md", "docs/PREREGISTRATION_C1.md"),
    ("docs/RUNBOOK_NEXT_3.md", "docs/RUNBOOK_NEXT_3.md"),
    ("docs/128_THI_HANH_REVIEW_127.md", "docs/128_THI_HANH_REVIEW_127.md"),
    ("docs/EXECUTION_STATUS.md", "docs/EXECUTION_STATUS.md"),
]

DOSSIER_DIRS = [
    ("data/curated/dev-legacy/execution_gold/dossiers_dev60", "data/curated/dev-legacy/execution_gold/dossiers_dev60"),
    ("data/curated/dev-legacy/execution_gold/dossiers_audit40_blind",
     "data/curated/dev-legacy/execution_gold/dossiers_audit40_blind"),
]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _mirror(stage: Path, dst: Path) -> None:
    """Chép staging → thư mục repo mà KHÔNG xoá gì.

    Thư mục làm việc được mount chỉ cho ghi/tạo, không cho `unlink`. `rmtree`
    và `rm -rf` đều trả `Operation not permitted`. Vì vậy packet được dựng SẠCH
    trong `/tmp` (xoá thoải mái) rồi mới soi chiếu sang repo bằng cách ghi đè.
    Hệ quả phải biết: file đã bị GỠ khỏi danh sách ITEMS sẽ vẫn còn sót lại
    trong `repo/sync_122_2/`. Nguồn sự thật là **ZIP** và **MANIFEST**, không
    phải thư mục mở.
    """
    import os
    import stat
    for p in sorted(stage.rglob("*")):
        if not p.is_file():
            continue
        d = dst / p.relative_to(stage)
        d.parent.mkdir(parents=True, exist_ok=True)
        if d.exists():
            os.chmod(d, stat.S_IWUSR | stat.S_IRUSR)
        shutil.copyfile(p, d)


def main() -> int:
    import tempfile
    stage_root = Path(tempfile.mkdtemp(prefix="sync_122_2_"))
    global DST
    real_dst, DST = DST, stage_root / "sync_122_2"
    DST.mkdir(parents=True)

    copied: list[str] = []
    missing: list[str] = []
    for src, rel in ITEMS:
        s = ROOT / src
        if not s.is_file():
            missing.append(src)
            continue
        d = DST / rel
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(s, d)
        copied.append(rel)

    for src, rel in DOSSIER_DIRS:
        s = ROOT / src
        if not s.is_dir():
            missing.append(src + "/")
            continue
        for p in sorted(s.rglob("*")):
            if p.is_file() and p.suffix not in {".pyc", ".pyo"}:
                d = DST / rel / p.relative_to(s)
                d.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, d)
                copied.append(str(d.relative_to(DST)))

    assert not any(c.endswith(".pyc") or "__pycache__" in c for c in copied), \
        "packet KHÔNG được chứa bytecode"

    lines = []
    for rel in sorted(copied):
        lines.append(f"{sha256(DST / rel)}  {rel}")
    (DST / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")

    n_files = len(copied)
    readme = f"""# sync_122_2 — packet BỔ SUNG (D1–D3 evidence + hotfix D0)

**Ngày:** 21/08/2026 · **Căn cứ:** review 127 §7 và §9.
**Đọc CÙNG** `sync_122_1` — packet này không thay thế nó.

## Không gửi lại (SHA đã khớp hai máy)

| | |
|---|---|
| A6 package 1,68 GB | `23c3b96e…53be` — review 127 §2 xác nhận khớp |
| `work.db` 4,24 GB | `e9f62775…67d5f` — dựng lại bằng `tools/build_retrieval_workdb.sh` |
| `controls/*.zip` | đã có trong sync_122_1 |

## Verify từ bản giải nén SẠCH (copy-paste, không đoán)

```bash
sha256sum -c MANIFEST.sha256          # {n_files} file
bash ops/environment/bootstrap_review_env.sh  # dựng venv 3.11 + pandas/numpy
. .venv-review/bin/activate
bash ops/environment/verify_packet.sh         # 8 mục, ghi reports/reviewer_replay_report.json
```

`verify_packet.sh` **không dừng ở lỗi đầu tiên** — chạy hết rồi mới ra verdict,
để người review thấy toàn bộ bức tranh trong một lần chạy.

## Hợp đồng rebuild work.db — ĐÃ SỬA (review 127 §2.6, "Cách A")

Bản cũ không đọc `$1/$2` nên lệnh trong README luôn thất bại. Nay ba cách gọi
tương đương, và `--verify-only` kiểm **đủ bốn index** chứ không chỉ row counts:

```bash
bash tools/build_retrieval_workdb.sh <silver.db> <work.db> [<a6.zip>]
SRC=… OUT=… PKG=… bash tools/build_retrieval_workdb.sh
bash tools/build_retrieval_workdb.sh --verify-only <work.db>
```

## Per-slot evidence (thứ §7 của review 127 đòi)

`data/curated/evaluation/legacy/fact_candidates_gold45_v1{{0,1,2}}.jsonl` — mỗi dòng một slot, đủ
`qid · slot_id · target_ref · target_label · leakage_flag · pool_sql_present ·
pool_scorable_present · rank@V1.0/V1.1/V1.2 · top20_candidate_ids ·
miss_reason`. Tổng hợp + kiểm chứng số cũ: `reports/fact_slot_evidence_v1.json`.

## Ba điều packet này LẬT hoặc HẠ CẤP so với doc 126

1. `75,9%@20` và `20,7%@1` **phụ thuộc thứ tự quét bảng** (39/45 QID có tie tại
   ngưỡng cắt). Khoá thứ tự: @1 → 12,6%, @20 → 78,2%.
2. Pool recall 87/87 **giữ nguyên** và mạnh hơn (`pool_scorable` cũng 87/87),
   nhưng hệ quả đúng là **tăng độ sâu**, không phải tune trọng số.
3. C1 = **HOLD**. Ablation C1a→C1e cho net −1/−3/0/0/0; không ngưỡng nào đạt
   McNemar p ≤ 0,05; trên toàn 1.012 câu thì xấu đi cả ba chỉ số kiểu.

Chi tiết: `docs/128_THI_HANH_REVIEW_127.md`.
"""
    (DST / "README.md").write_text(readme, encoding="utf-8")

    zpath = ROOT / "dist" / "sync_122_2.zip"
    zpath.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(DST.rglob("*")):
            if p.is_file():
                z.write(p, str(p.relative_to(DST)))

    _mirror(DST, real_dst)
    shutil.rmtree(stage_root, ignore_errors=True)

    # SHA của ZIP phải nằm NGOÀI ZIP. Nếu viết nó vào một tệp bên trong thì mỗi
    # lần cập nhật con số lại làm đổi chính con số ấy — vòng lặp không hội tụ.
    zsha = sha256(ROOT / "dist" / "sync_122_2.zip")
    (ROOT / "dist" / "sync_122_2.sha256").write_text(f"{zsha}  sync_122_2.zip\n", encoding="utf-8")

    print(f"staging             : {stage_root} (đã xoá)")
    print(f"file trong manifest : {n_files}")
    print(f"file trong ZIP      : {n_files + 2}  (+ MANIFEST.sha256 + README.md)")
    print(f"bytecode            : 0")
    print(f"thiếu               : {missing or 'không'}")
    print(f"zip                 : {zpath.name}  {zpath.stat().st_size:,} bytes")
    print(f"zip sha256          : {sha256(zpath)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
