#!/usr/bin/env python3
"""Canonical build wrapper cho official submission — doc 161 §6 Pha 0.

Vì sao tồn tại: packager chính thức `tools/answer_a6/06_dong_goi.py` **chốt cứng**
đường vào `submission_P0G2.zip` và đường ra `submission_P0I.zip`. Không nhận tham
số, không xuất trace, không thể replay có kiểm soát. Wrapper này bọc ĐÚNG logic
đó thành một command nhận tham số và ghi lineage, KHÔNG đổi một nhánh quyết định
nào — nếu đổi thì `feature_off` sẽ không tái lập được parent, và đó chính là phép
thử của chính nó.

  python3 tools/lineage/official_build_wrapper.py \
      --parent-zip data/submissions/submission_P0G2.zip \
      --output-zip /tmp/replay_P0I.zip \
      --trace-jsonl reports/lineage/stage_trace_P0I.jsonl \
      --expect-zip data/submissions/submission_P0I.zip

`--candidate-records` để trống = **feature_off** = tái dựng đúng P0I.

Ghi chú tất định: ZIP không được so bằng byte vì `zipfile` ghi mtime hiện tại vào
header. Đại lượng so sánh là **canonical SHA của `submission.json`** cộng inventory
tên file — đúng như doc 161 §6 Pha 0 mục 3 cho phép.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# Ba trường mà tầng đáp án được phép ghi. Mọi trường khác là hợp đồng Retrieval.
TRUONG_DAP_AN = ("answer", "pandas_query", "evidence")
TRUONG_KHOA = ("relevant_tables", "relevant_docs", "question")


def ten_ngan(p: Path) -> str:
    """Đường dẫn tương đối với ROOT nếu được, còn không thì giữ nguyên."""
    try:
        return str(Path(p).resolve().relative_to(ROOT))
    except ValueError:
        return str(p)


def sha_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sha_field(v) -> str:
    """SHA ổn định của một trường — dùng cùng một phép tuần tự hoá ở mọi tầng."""
    return sha_text(json.dumps(v, ensure_ascii=False, sort_keys=True))


def doc_jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def canonical_submission_bytes(sub: list) -> str:
    """ĐÚNG phép tuần tự hoá mà packager gốc dùng — không được đổi."""
    return json.dumps(sub, ensure_ascii=False, indent=1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent-zip", type=Path,
                    default=ROOT / "data/submissions/submission_P0G2.zip")
    ap.add_argument("--candidate-records", type=Path, default=None,
                    help="overlay thêm; để trống = feature_off")
    ap.add_argument("--output-zip", type=Path, required=True)
    ap.add_argument("--trace-jsonl", type=Path, required=True)
    ap.add_argument("--expect-zip", type=Path, default=None,
                    help="ZIP kỳ vọng để đối chiếu canonical SHA")
    ap.add_argument("--a6-records", type=Path,
                    default=ROOT / "data/dev/answer_a6/records_a6.jsonl")
    ap.add_argument("--sohoc-records", type=Path,
                    default=ROOT / "data/dev/so_hoc/records_sohoc.jsonl")
    ap.add_argument("--data-a6", type=Path, default=ROOT / "data/dev/answer_a6/data")
    ap.add_argument("--data-v3", type=Path, default=ROOT / "data/dev/answer_v3/data")
    a = ap.parse_args()

    a.trace_jsonl.parent.mkdir(parents=True, exist_ok=True)
    a.output_zip.parent.mkdir(parents=True, exist_ok=True)

    # ── identity đầu vào ───────────────────────────────────────────────────
    identity = {
        "parent_zip": ten_ngan(a.parent_zip),
        "parent_sha256": sha_file(a.parent_zip),
        "a6_records_sha256": sha_file(a.a6_records),
        "sohoc_records_sha256": sha_file(a.sohoc_records),
        "wrapper_sha256": sha_file(Path(__file__)),
        "packager_goc_sha256": sha_file(ROOT / "tools/answer_a6/06_dong_goi.py"),
        "feature_off": a.candidate_records is None,
    }

    moi = {r["qid"]: r for r in doc_jsonl(a.a6_records)}
    zin = zipfile.ZipFile(a.parent_zip)
    sub = json.loads(zin.read("submission.json"))
    goc = {r["id"]: r for r in json.loads(zin.read("submission.json"))}

    giu_sohoc = {r.get("qid") or r.get("id")
                 for r in doc_jsonl(a.sohoc_records) if r.get("trang_thai") == "OK"}

    overlay = {}
    if a.candidate_records is not None:
        overlay = {r["qid"]: r for r in doc_jsonl(a.candidate_records)}
        identity["candidate_records_sha256"] = sha_file(a.candidate_records)

    # ── vòng ghi đáp án — SAO CHÉP nguyên nhánh quyết định của packager gốc ─
    trace = []
    dem = {"OVERLAY": 0, "SO_HOC_P0G2": 0, "ANSWER_A6": 0,
           "A6_TRUNG_PARENT": 0, "A6_THIEU_RECORD": 0}
    for r in sub:
        qid = r["id"]
        truoc = {f: sha_field(goc[qid].get(f)) for f in TRUONG_DAP_AN}

        if qid in overlay:
            m = overlay[qid]
            r["answer"] = m["answer"]
            r["pandas_query"] = m["pandas_query"]
            r["evidence"] = m["evidence"]
            writer, reason = "OVERLAY", "OVERLAY_APPLIED"
        elif qid in giu_sohoc:
            # so_hoc đã ghi ô này ở tầng P0G→P0G2; packager A6 CỐ Ý bỏ qua
            writer, reason = "SO_HOC", "GIU_SO_HOC_P0G"
        else:
            m = moi.get(qid)
            if not m or not m.get("evidence") or m.get("answer") is None:
                writer, reason = "PARENT_INHERIT", "A6_RECORD_KHONG_DUNG_DUOC"
                dem["A6_THIEU_RECORD"] += 1
            elif (m["answer"] == goc[qid].get("answer")
                  and m["pandas_query"] == goc[qid].get("pandas_query")):
                writer, reason = "PARENT_INHERIT", "A6_TRUNG_PARENT"
                dem["A6_TRUNG_PARENT"] += 1
            else:
                r["answer"] = m["answer"]
                r["pandas_query"] = m["pandas_query"]
                r["evidence"] = m["evidence"]
                writer = "ANSWER_A6"
                reason = ("A6_" + str(m.get("nguon")))
        if writer == "SO_HOC":
            dem["SO_HOC_P0G2"] += 1
        elif writer == "ANSWER_A6":
            dem["ANSWER_A6"] += 1
        elif writer == "OVERLAY":
            dem["OVERLAY"] += 1

        sau = {f: sha_field(r.get(f)) for f in TRUONG_DAP_AN}
        trace.append({
            "qid": qid,
            "stage": "P0G2->P0I",
            "final_writer": writer,
            "reason_code": reason,
            "changed_fields": [f for f in TRUONG_DAP_AN if truoc[f] != sau[f]],
            "field_sha_truoc": truoc,
            "field_sha_sau": sau,
        })

    # ── CỔNG CỨNG hợp đồng Retrieval — giữ nguyên từ packager gốc ──────────
    for r in sub:
        g = goc[r["id"]]
        for f in TRUONG_KHOA:
            if (json.dumps(r.get(f), ensure_ascii=False)
                    != json.dumps(g.get(f), ensure_ascii=False)):
                print(f"CHAN q{r['id']}: {f} ĐÃ ĐỔI — Retrieval FREEZE", file=sys.stderr)
                return 2

    # ── ghi ZIP — thứ tự ưu tiên CSV giữ nguyên chủ đích của bản gốc ───────
    canon = canonical_submission_bytes(sub)
    with zipfile.ZipFile(a.output_zip, "w", zipfile.ZIP_DEFLATED) as zo:
        zo.writestr("submission.json", canon)
        can = {e["csv_path"] for r in sub for e in (r.get("evidence") or [])
               if e.get("csv_path")}
        co_nen = set(zin.namelist())
        csv_dem = {"nen": 0, "a6": 0, "v3": 0, "thieu": 0}
        for path in sorted(can):
            name = path.split("/", 1)[1]
            if path in co_nen:
                zo.writestr(path, zin.read(path)); csv_dem["nen"] += 1
            elif (a.data_a6 / name).is_file():
                zo.write(a.data_a6 / name, path); csv_dem["a6"] += 1
            elif (a.data_v3 / name).is_file():
                zo.write(a.data_v3 / name, path); csv_dem["v3"] += 1
            else:
                csv_dem["thieu"] += 1

    canon_sha = sha_text(canon)
    inventory = sorted(zipfile.ZipFile(a.output_zip).namelist())

    ket = {
        "_schema": "official_build_wrapper v1",
        "identity": identity,
        "writer_counts": dem,
        "csv_source_counts": csv_dem,
        "canonical_submission_sha256": canon_sha,
        "n_file_trong_zip": len(inventory),
        "output_zip": str(a.output_zip),
    }

    if a.expect_zip:
        ze = zipfile.ZipFile(a.expect_zip)
        exp_canon = ze.read("submission.json").decode("utf-8")
        exp_sha = sha_text(exp_canon)
        exp_inv = sorted(ze.namelist())
        ket["expect"] = {
            "zip": ten_ngan(a.expect_zip),
            "canonical_submission_sha256": exp_sha,
            "n_file": len(exp_inv),
            "CANONICAL_SHA_MATCH": exp_sha == canon_sha,
            "INVENTORY_MATCH": exp_inv == inventory,
            "chi_thua": [p for p in inventory if p not in set(exp_inv)][:10],
            "chi_thieu": [p for p in exp_inv if p not in set(inventory)][:10],
        }

    a.trace_jsonl.write_text(
        "\n".join(json.dumps(t, ensure_ascii=False) for t in trace) + "\n",
        encoding="utf-8")
    (a.trace_jsonl.parent / (a.trace_jsonl.stem + "_summary.json")).write_text(
        json.dumps(ket, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps(ket, ensure_ascii=False, indent=1))
    if a.expect_zip:
        ok = ket["expect"]["CANONICAL_SHA_MATCH"] and ket["expect"]["INVENTORY_MATCH"]
        print("REPLAY:", "PASS" if ok else "FAIL")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
