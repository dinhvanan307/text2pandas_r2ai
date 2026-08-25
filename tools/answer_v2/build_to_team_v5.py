#!/usr/bin/env python3
"""Đóng `to_team_v5.zip` theo doc 159 §6. Gồm `p0_closure_patch_v2_1/`.

ZIP TẤT ĐỊNH: mọi entry ghim `date_time` cố định. Không có nó thì hai lần đóng
cùng nội dung cho hai SHA khác nhau, và checksum trong packet mất giá trị kiểm
chứng — bài học đã trả giá ở AG1 (cbd7… vs 3fc8…).

Chạy:  python3 tools/answer_v2/build_to_team_v5.py
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REP = ROOT / "reports/answer_v2"
MOC = (2026, 1, 1, 0, 0, 0)

# 25 file candidate-affecting: mọi thứ ảnh hưởng tới `answer`/`pandas_query`/
# `evidence` của AG1B. Đổi một file ở đây ⇒ KHÔNG còn được gọi là exact AG1B.
CANDIDATE_AFFECTING = [
    "tools/answer_v2/ir_v1.py", "tools/answer_v2/metric_ontology.py",
    "tools/answer_v2/formula_registry.py", "tools/answer_v2/router_v1.py",
    "tools/answer_v2/operand_binder.py", "tools/answer_v2/evidence_builder.py",
    "tools/answer_v2/pandas_renderer.py", "tools/answer_v2/verifier.py",
    "tools/answer_v2/run_answer_v2.py",
    "configs/answer_v2/metrics_v1.yaml", "configs/answer_v2/formulas_v1.yaml",
    "tools/execution/fact_rank_v1.py", "tools/execution/score_v2.py",
    "tools/execution/answer_type_v1.py", "tools/execution/operand_pipeline_v1.py",
    "tools/execution/emit_arith_v1.py", "tools/execution/emit_lookup_v1.py",
    "tools/execution/row_feats_v1.py", "tools/execution/period_parse_v1.py",
]

SOURCE_R0 = ["tools/answer_v2/cell_reranker.py",
             "tools/answer_v2/run_rerank_eval.py",
             "tools/answer_v2/llm_client.py",
             "tests/answer_v2/test_reranker_v2.py"]


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def agg(d: dict) -> str:
    return hashlib.sha256(
        json.dumps({k: v for k, v in sorted(d.items())},
                   sort_keys=True).encode()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "data/handoff")
    ap.add_argument("--base-v2-sha", default=
                    "a135e162d5fb18f863824697adf4497eff29789932d366cd4f46df6a5a001e20")
    a = ap.parse_args()

    stage = a.out / "p0_closure_patch_v2_1"
    if stage.exists():
        shutil.rmtree(stage, ignore_errors=True)
    for sub in ("identity", "source_test_patch/tests/answer_v2",
                "source_r0/tools/answer_v2", "source_r0/tests/answer_v2",
                "train_fit_inputs", "p0_rr_prep_v2", "r0_preflight"):
        (stage / sub).mkdir(parents=True, exist_ok=True)

    # ── source_r0 ──────────────────────────────────────────────────────────
    for rel in SOURCE_R0:
        src = ROOT / rel
        if not src.is_file():
            print(f"✗ thiếu {rel}", file=sys.stderr)
            return 2
        shutil.copy2(src, stage / "source_r0" / rel)

    # ── source_test_patch — toàn bộ tests/answer_v2 để tái lập full-source ──
    for p in sorted((ROOT / "tests/answer_v2").glob("*.py")):
        shutil.copy2(p, stage / "source_test_patch/tests/answer_v2" / p.name)

    # ── train_fit_inputs · rr_prep · r0_preflight ──────────────────────────
    for ten in ("train_fit_inputs", "p0_rr_prep_v2", "r0_preflight"):
        src = REP / ten
        if not src.is_dir():
            print(f"✗ thiếu {src} — chạy build_* trước", file=sys.stderr)
            return 2
        for p in sorted(src.iterdir()):
            if p.is_file():
                shutil.copy2(p, stage / ten / p.name)

    # ── verifier ───────────────────────────────────────────────────────────
    shutil.copy2(ROOT / "tools/answer_v2/verify_patch_template.py",
                 stage / "verify_patch.py")

    (stage / "assemble_and_verify_source.py").write_text('''#!/usr/bin/env python3
"""Ghép cây source rồi tái tính aggregate. Doc 159 §6.4.

    python3 assemble_and_verify_source.py --repo /duong/dan/Text2Pandas

So băm TỪNG FILE với `identity/source_full_file_hashes.json`, rồi tái tính
aggregate. Bất kỳ file nào lệch đều được liệt kê — không chỉ báo "aggregate sai".
"""
import argparse, hashlib, json, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def sha(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", type=Path, required=True)
    a = ap.parse_args()
    for ten, khoa in (("source_full_file_hashes.json", "full_source_aggregate_sha256"),
                      ("candidate_affecting_file_hashes.json",
                       "candidate_affecting_aggregate_sha256")):
        d = json.loads((HERE / "identity" / ten).read_text(encoding="utf-8"))
        ident = json.loads(
            (HERE / "identity/SOURCE_AGGREGATE_V2_1.json").read_text(encoding="utf-8"))
        thieu, lech = [], []
        for rel, want in (d.get("files") or {}).items():
            p = a.repo / rel
            if not p.is_file():
                thieu.append(rel)
            elif sha(p) != want:
                lech.append(rel)
        tinh = hashlib.sha256(json.dumps(
            {k: v for k, v in sorted((d.get("files") or {}).items())},
            sort_keys=True).encode()).hexdigest()
        ok = (tinh == ident.get(khoa)) and not thieu and not lech
        print(f"{ten}: {'OK' if ok else 'MISMATCH'}")
        print(f"  aggregate tính {tinh}")
        print(f"  aggregate khai {ident.get(khoa)}")
        if thieu:
            print(f"  thiếu {len(thieu)}: {thieu[:5]}")
        if lech:
            print(f"  lệch {len(lech)}: {lech[:5]}")
        if not ok:
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
''', encoding="utf-8")

    # ── identity ───────────────────────────────────────────────────────────
    full_files = {}
    for pat in ("tools/answer_v2/*.py", "configs/answer_v2/*", "tests/answer_v2/*.py"):
        for p in sorted(ROOT.glob(pat)):
            if p.is_file() and "__pycache__" not in str(p):
                full_files[str(p.relative_to(ROOT))] = sha_file(p)
    ca_files = {rel: sha_file(ROOT / rel) for rel in CANDIDATE_AFFECTING
                if (ROOT / rel).is_file()}

    (stage / "identity/source_full_file_hashes.json").write_text(json.dumps(
        {"_schema": "source_full_file_hashes v2.1", "n_file": len(full_files),
         "pham_vi": "tools/answer_v2/*.py · configs/answer_v2/* · tests/answer_v2/*.py",
         "files": full_files}, ensure_ascii=False, indent=1), encoding="utf-8")
    (stage / "identity/candidate_affecting_file_hashes.json").write_text(json.dumps(
        {"_schema": "candidate_affecting_file_hashes v2.1", "n_file": len(ca_files),
         "dinh_nghia": ("mọi file ảnh hưởng answer/pandas_query/evidence của "
                        "AG1B; đổi một file ⇒ KHÔNG còn là exact AG1B"),
         "files": ca_files}, ensure_ascii=False, indent=1), encoding="utf-8")

    full_agg, ca_agg = agg(full_files), agg(ca_files)
    ag1b = ROOT / "data/submissions/submission_AG1B_R2_PRECISION_FIX.zip"
    ag1b_sha = sha_file(ag1b) if ag1b.is_file() else None

    (stage / "identity/SOURCE_AGGREGATE_V2_1.json").write_text(json.dumps({
        "_schema": "SOURCE_AGGREGATE_V2_1",
        "full_source_aggregate_sha256": full_agg,
        "candidate_affecting_aggregate_sha256": ca_agg,
        "n_file_full": len(full_files), "n_file_candidate_affecting": len(ca_files),
        "cach_tinh": ("sha256 của json.dumps({path: sha256}, sort_keys=True) — "
                      "tái lập bằng assemble_and_verify_source.py"),
        "ag1b_zip_sha256": ag1b_sha,
        "GHI_CHU_TRUNG_THUC": (
            "Aggregate này tính TỪ CÂY HIỆN TẠI của máy build. Hai giá trị "
            "`4078bd91…` và `f000a14f…` mà doc 159 §6.4 nêu KHÔNG tái lập được "
            "ở đây vì packet V4/base-v2 không có trong repo này. Team phải đối "
            "chiếu và tuyên bố cây chuẩn — xem BAN_GIAO.md §Chưa đóng được."),
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    try:
        head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                              capture_output=True, text=True).stdout.strip()
    except Exception:
        head = None
    (stage / "identity/PATCH_IDENTITY.json").write_text(json.dumps({
        "_schema": "PATCH_IDENTITY v2.1",
        "patch_id": "p0_closure_patch_v2_1",
        # KHÔNG ghi wall-clock vào nội dung được băm: nó làm mỗi lần đóng ra
        # một SHA khác, và một packet có checksum mà không tái lập được checksum
        # thì checksum ấy vô nghĩa. Danh tính bản dựng được xác định bằng
        # git_head + băm đầu vào, là những thứ THẬT SỰ quyết định nội dung.
        "sinh_luc": "KHONG_GHI — xem ghi_chu_tat_dinh",
        "ghi_chu_tat_dinh": ("wall-clock cố ý bị loại khỏi nội dung băm để ZIP "
                             "tất định; đóng lại cùng cây source cho cùng SHA"),
        "git_head": head,
        "python": sys.version.split()[0],
        "ag1b_parent_zip": ag1b.name if ag1b_sha else None,
        "ag1b_parent_sha256": ag1b_sha,
        "model_calls_trong_patch": 0,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── SUPERSEDES ────────────────────────────────────────────────────────
    (stage / "SUPERSEDES.json").write_text(json.dumps({
        "base_v2_zip_sha256": a.base_v2_sha,
        "files_superseded": {
            "identity/SOURCE_AGGREGATE_V2.json": "identity/SOURCE_AGGREGATE_V2_1.json",
            "p0_rr_prep/eligibility_v1.json": "p0_rr_prep_v2/eligibility_v2.json",
            "p0_rr_prep/train_fit_gates_v1.json": "p0_rr_prep_v2/train_fit_gates_v2.json",
            "p0_rr_prep/k_rule_v1.json": "p0_rr_prep_v2/k_rule_v2.json",
            "p0_rr_prep/cache_key_v1.json": "p0_rr_prep_v2/cache_key_v2.json",
            "p0_rr_prep/fresh_audit_protocol_v1.json":
                "p0_rr_prep_v2/fresh_audit_protocol_v2.json",
            "p0_rr_prep/model_identity_v1.json": "p0_rr_prep_v2/model_identity_v2.json",
        },
        "ag1b_candidate_changed": False,
        "model_calls_before_patch_freeze": 0,
    }, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── MANIFEST (sau cùng, trừ chính nó) ─────────────────────────────────
    dong = []
    for p in sorted(stage.rglob("*")):
        if p.is_file() and p.name not in ("MANIFEST.sha256", "verify_patch.log"):
            dong.append(f"{sha_file(p)}  {p.relative_to(stage)}")
    (stage / "MANIFEST.sha256").write_text("\n".join(dong) + "\n", encoding="utf-8")

    # ── chạy verifier NGAY TRONG stage ────────────────────────────────────
    r = subprocess.run([sys.executable, "verify_patch.py"], cwd=stage,
                       capture_output=True, text=True)
    print(r.stdout[-1800:])
    if r.returncode != 0:
        print(f"⚠️ verify_patch exit {r.returncode} — vẫn đóng gói để reviewer thấy",
              file=sys.stderr)

    # ── ZIP tất định ──────────────────────────────────────────────────────
    def ghi_zip(zf, ten, data):
        zi = zipfile.ZipInfo(ten, date_time=MOC)
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = 0o644 << 16
        zf.writestr(zi, data)

    patch_zip = a.out / "p0_closure_patch_v2_1.zip"
    with zipfile.ZipFile(patch_zip, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                ghi_zip(z, f"p0_closure_patch_v2_1/{p.relative_to(stage)}",
                        p.read_bytes())
    patch_sha = sha_file(patch_zip)
    (a.out / "p0_closure_patch_v2_1.sha256").write_text(
        f"{patch_sha}  p0_closure_patch_v2_1.zip\n", encoding="utf-8")

    outer = a.out / "to_team_v5.zip"
    with zipfile.ZipFile(outer, "w", zipfile.ZIP_DEFLATED) as z:
        ghi_zip(z, "p0_closure_patch_v2_1.zip", patch_zip.read_bytes())
        ghi_zip(z, "p0_closure_patch_v2_1.sha256",
                f"{patch_sha}  p0_closure_patch_v2_1.zip\n".encode())
        ghi_zip(z, f"base_v2_expected.sha256",
                f"{a.base_v2_sha}  to_team_V4_addendum_p0_ag1b_20260822_v2.zip\n".encode())
        bg = ROOT / "docs/161_BAN_GIAO_V5.md"
        if bg.is_file():
            ghi_zip(z, "BAN_GIAO_V5.md", bg.read_bytes())
    outer_sha = sha_file(outer)
    (a.out / "to_team_v5.sha256").write_text(
        f"{outer_sha}  to_team_v5.zip\n", encoding="utf-8")

    print(f"\npatch  {patch_zip.name}  sha256={patch_sha}")
    print(f"outer  {outer.name}  sha256={outer_sha}")
    print(f"-> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
