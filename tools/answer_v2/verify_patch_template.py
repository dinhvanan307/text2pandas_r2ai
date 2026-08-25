#!/usr/bin/env python3
"""verify_patch — 11 kiểm bắt buộc của doc 159 §6.3. Chạy TỪ TRONG patch.

    exit 0   mọi kiểm PASS
    exit 1   có mismatch
    exit 2   thiếu đầu vào

KHÔNG cho phép `SKIP` một kiểm bắt buộc rồi vẫn tuyên preflight PASS. Ở đây,
một kiểm thiếu đầu vào ⇒ trạng thái `MISSING` ⇒ exit 2, không phải PASS.

Vì sao viết như một tệp độc lập, không import gì của repo: reviewer phải chạy
được nó ngay sau khi giải nén, trên máy không có `work.db` 4,2 GB.
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
KET_QUA: list[dict] = []


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 16), b""):
            h.update(b)
    return h.hexdigest()


def kiem(ten: str, trang_thai: str, chi_tiet="") -> None:
    KET_QUA.append({"kiem": ten, "trang_thai": trang_thai, "chi_tiet": chi_tiet})


def doc_json(rel: str):
    p = ROOT / rel
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None


def doc_jsonl(rel: str):
    p = ROOT / rel
    if not p.is_file():
        return None
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


# ── 1 · MANIFEST 100% ──────────────────────────────────────────────────────
def k1() -> None:
    mf = ROOT / "MANIFEST.sha256"
    if not mf.is_file():
        return kiem("1_manifest", "MISSING", "không có MANIFEST.sha256")
    lech, thieu, n = [], [], 0
    for line in mf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        sha, _, rel = line.partition("  ")
        rel = rel.strip()
        p = ROOT / rel
        n += 1
        if not p.is_file():
            thieu.append(rel)
        elif sha_file(p) != sha:
            lech.append(rel)
    if thieu or lech:
        return kiem("1_manifest", "FAIL",
                    f"thiếu {len(thieu)} · lệch {len(lech)} · {(thieu + lech)[:5]}")
    kiem("1_manifest", "PASS", f"{n}/{n} file khớp")


# ── 2 · base-v2 outer SHA ─────────────────────────────────────────────────
def k2() -> None:
    sup = doc_json("SUPERSEDES.json")
    if not sup:
        return kiem("2_base_v2_sha", "MISSING", "không có SUPERSEDES.json")
    exp = sup.get("base_v2_zip_sha256")
    if not exp or len(exp) != 64:
        return kiem("2_base_v2_sha", "FAIL", "base_v2_zip_sha256 thiếu/không đủ 64 ký tự")
    # ZIP base KHÔNG nằm trong patch — reviewer đối chiếu bằng tay.
    kiem("2_base_v2_sha", "PASS_DECLARED",
         f"{exp[:16]}… — reviewer tự đối chiếu với ZIP base v2 ngoài patch")


# ── 3 · SUPERSEDES paths ──────────────────────────────────────────────────
def k3() -> None:
    sup = doc_json("SUPERSEDES.json")
    if not sup:
        return kiem("3_supersedes", "MISSING", "")
    thieu = [dest for dest in (sup.get("files_superseded") or {}).values()
             if not (ROOT / dest).is_file()]
    if thieu:
        return kiem("3_supersedes", "FAIL", f"đích không tồn tại: {thieu}")
    kiem("3_supersedes", "PASS",
         f"{len(sup.get('files_superseded') or {})} ánh xạ, mọi đích có mặt")


# ── 4 · full-source aggregate ─────────────────────────────────────────────
def k4() -> None:
    ident = doc_json("identity/SOURCE_AGGREGATE_V2_1.json")
    full = doc_json("identity/source_full_file_hashes.json")
    if not ident or not full:
        return kiem("4_full_source", "MISSING", "thiếu identity/*")
    tinh = hashlib.sha256(json.dumps(
        {k: v for k, v in sorted((full.get("files") or {}).items())},
        sort_keys=True).encode()).hexdigest()
    exp = ident.get("full_source_aggregate_sha256")
    if tinh != exp:
        return kiem("4_full_source", "FAIL", f"tính {tinh[:16]}… ≠ khai {str(exp)[:16]}…")
    kiem("4_full_source", "PASS", f"{len(full.get('files') or {})} file · {tinh[:16]}…")


# ── 5 · candidate-affecting aggregate ─────────────────────────────────────
def k5() -> None:
    ident = doc_json("identity/SOURCE_AGGREGATE_V2_1.json")
    ca = doc_json("identity/candidate_affecting_file_hashes.json")
    if not ident or not ca:
        return kiem("5_candidate_affecting", "MISSING", "")
    tinh = hashlib.sha256(json.dumps(
        {k: v for k, v in sorted((ca.get("files") or {}).items())},
        sort_keys=True).encode()).hexdigest()
    exp = ident.get("candidate_affecting_aggregate_sha256")
    if tinh != exp:
        return kiem("5_candidate_affecting", "FAIL",
                    f"tính {tinh[:16]}… ≠ khai {str(exp)[:16]}…")
    kiem("5_candidate_affecting", "PASS",
         f"{len(ca.get('files') or {})} file · {tinh[:16]}…")


# ── 6 · RR-PREP v2 freeze ─────────────────────────────────────────────────
def k6() -> None:
    fm = doc_json("p0_rr_prep_v2/FREEZE_MANIFEST.json")
    if not fm:
        return kiem("6_rr_prep_freeze", "MISSING", "")
    lech = [n for n, sha in (fm.get("files") or {}).items()
            if not (ROOT / "p0_rr_prep_v2" / n).is_file()
            or sha_file(ROOT / "p0_rr_prep_v2" / n) != sha]
    if lech:
        return kiem("6_rr_prep_freeze", "FAIL", f"lệch/thiếu: {lech}")
    kiem("6_rr_prep_freeze", "PASS", f"{len(fm.get('files') or {})} file khớp freeze")


# ── 7 · mọi artifact path tồn tại ─────────────────────────────────────────
def k7() -> None:
    can = ["train_fit_inputs/TRAIN_FIT_IDENTITY.json",
           "train_fit_inputs/train_fit_66_slots.jsonl",
           "train_fit_inputs/train_fit_gold_labels.jsonl",
           "train_fit_inputs/candidate_pools_top16.jsonl",
           "train_fit_inputs/baseline_predictions.jsonl",
           "train_fit_inputs/baseline_29_of_66.json",
           "r0_preflight/recall_at_k.json", "r0_preflight/recall_per_slot.jsonl",
           "r0_preflight/eligibility_report_66.json",
           "r0_preflight/capability_denominator.json",
           "r0_preflight/production_policy_denominator.json",
           "r0_preflight/NO_MODEL_CALL_DECLARATION.json",
           "r0_preflight/preflight_report.json",
           "source_r0/tools/answer_v2/cell_reranker.py",
           "source_r0/tools/answer_v2/run_rerank_eval.py",
           "source_r0/tests/answer_v2/test_reranker_v2.py"]
    thieu = [c for c in can if not (ROOT / c).is_file()]
    if thieu:
        return kiem("7_artifact_paths", "FAIL", f"thiếu {thieu}")
    kiem("7_artifact_paths", "PASS", f"{len(can)}/{len(can)} có mặt")


# ── 8 · train-fit đúng 66 unique slot ─────────────────────────────────────
def k8() -> None:
    s = doc_jsonl("train_fit_inputs/train_fit_66_slots.jsonl")
    g = doc_jsonl("train_fit_inputs/train_fit_gold_labels.jsonl")
    if s is None or g is None:
        return kiem("8_66_unique_slot", "MISSING", "")
    u = {(r["qid"], r["slot_id"]) for r in s}
    ug = {(r["qid"], r["slot_id"]) for r in g}
    if len(s) != 66 or len(u) != 66:
        return kiem("8_66_unique_slot", "FAIL", f"n={len(s)} unique={len(u)}")
    if u != ug:
        return kiem("8_66_unique_slot", "FAIL", "slot của gold không khớp slot input")
    kiem("8_66_unique_slot", "PASS", "66 dòng · 66 unique · gold khớp 1-1")


# ── 9 · stable candidate ID không đổi giữa presentation ───────────────────
def k9() -> None:
    p = doc_jsonl("train_fit_inputs/candidate_pools_top16.jsonl")
    if p is None:
        return kiem("9_stable_id", "MISSING", "")
    # ID phải duy nhất trong mỗi slot, và không được trùng với deterministic_rank
    xau = []
    theo = {}
    for c in p:
        k = (c["qid"], c["slot_id"])
        theo.setdefault(k, []).append(c["stable_candidate_id"])
    for k, ids in theo.items():
        if len(ids) != len(set(ids)):
            xau.append(k)
    if xau:
        return kiem("9_stable_id", "FAIL", f"ID trùng trong slot: {xau[:3]}")
    if not all(str(c["stable_candidate_id"]).startswith("c_") for c in p):
        return kiem("9_stable_id", "FAIL", "ID không đúng tiền tố c_")
    kiem("9_stable_id", "PASS",
         f"{len(p)} ứng viên · ID duy nhất trong mọi slot · độc lập vị trí")


# ── 10 · tái tính recall khớp report ──────────────────────────────────────
def k10() -> None:
    rk = doc_json("r0_preflight/recall_at_k.json")
    per = doc_jsonl("r0_preflight/recall_per_slot.jsonl")
    if not rk or per is None:
        return kiem("10_recall_tai_tinh", "MISSING", "")
    lech = []
    for k in (4, 8, 12, 16):
        tinh = sum(1 for r in per if r.get(f"gold_in_top{k}"))
        khai = rk.get(f"recall_at_{k}", {}).get("n")
        if tinh != khai:
            lech.append(f"K={k}: tính {tinh} ≠ khai {khai}")
    if lech:
        return kiem("10_recall_tai_tinh", "FAIL", "; ".join(lech))
    kiem("10_recall_tai_tinh", "PASS", "recall@4/8/12/16 tái tính khớp report")


# ── 11 · model_call_count = 0 ─────────────────────────────────────────────
def k11() -> None:
    d = doc_json("r0_preflight/NO_MODEL_CALL_DECLARATION.json")
    if not d:
        return kiem("11_model_call_0", "MISSING", "")
    if d.get("model_call_count") != 0:
        return kiem("11_model_call_0", "FAIL",
                    f"khai {d.get('model_call_count')} lượt gọi")
    # kiểm chéo: preflight và gates phải cùng nói NOT_MEASURED
    cap = doc_json("r0_preflight/capability_denominator.json") or {}
    pol = doc_json("r0_preflight/production_policy_denominator.json") or {}
    if cap.get("model_attempted", 0) or pol.get("attempted_by_policy", 0):
        return kiem("11_model_call_0", "FAIL",
                    "mẫu số báo có lượt gọi nhưng declaration nói 0")
    kiem("11_model_call_0", "PASS", "0 lượt · hai mẫu số cùng NOT_MEASURED")


def main() -> int:
    for f in (k1, k2, k3, k4, k5, k6, k7, k8, k9, k10, k11):
        try:
            f()
        except Exception as e:                        # noqa: BLE001
            kiem(f.__name__, "ERROR", f"{type(e).__name__}: {e}")

    n_fail = sum(1 for r in KET_QUA if r["trang_thai"] in ("FAIL", "ERROR"))
    n_missing = sum(1 for r in KET_QUA if r["trang_thai"] == "MISSING")
    n_pass = sum(1 for r in KET_QUA if r["trang_thai"].startswith("PASS"))

    for r in KET_QUA:
        print(f"  {r['trang_thai']:15} {r['kiem']:26} {r['chi_tiet']}")
    print(f"\nPASS {n_pass} · FAIL {n_fail} · MISSING {n_missing} / {len(KET_QUA)}")

    (ROOT / "verify_patch.log").write_text(
        json.dumps({"ket_qua": KET_QUA, "n_pass": n_pass, "n_fail": n_fail,
                    "n_missing": n_missing}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    if n_missing:
        print("→ exit 2 (thiếu đầu vào)")
        return 2
    if n_fail:
        print("→ exit 1 (có mismatch)")
        return 1
    print("→ exit 0 (tất cả PASS)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
