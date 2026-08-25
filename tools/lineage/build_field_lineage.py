#!/usr/bin/env python3
"""official_field_lineage_1012.jsonl — doc 161 §6 Pha 0 mục 4.

Nguyên tắc: **không suy từ tên thư mục**. Lineage được đo bằng cách diff chuỗi ZIP
thật đã tồn tại trên đĩa, gán `final_writer` cho từng QID là **tầng CUỐI CÙNG thực
sự làm đổi** ít nhất một trong ba trường đáp án. Nếu không tầng nào đổi thì writer
là gốc chuỗi.

Chuỗi official (đã xác định bằng cách đọc hằng số chốt cứng trong từng packager,
rồi kiểm chéo bằng mtime):

    P0E --tools/answer_v2/03_dong_goi.py--> P0G
    P0G --tools/so_hoc/07_dong_goi.py-----> P0G2
    P0G2 --tools/answer_a6/06_dong_goi.py-> P0I   ← bài nộp ID 3241, EXECUTION 0,1225

`reason_code` lấy từ nhánh quyết định thật của packager cuối, không phải suy đoán.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SUB = ROOT / "data/submissions"

TRUONG = ("answer", "pandas_query", "evidence")

# (ten_tang, component thi hành, zip đầu ra)
CHUOI = [
    ("P0E", "GOC_CHUOI__truoc_answer_v2", SUB / "submission_P0E.zip"),
    ("P0G", "tools/answer_v2/03_dong_goi.py", SUB / "submission_P0G.zip"),
    ("P0G2", "tools/so_hoc/07_dong_goi.py", SUB / "submission_P0G2.zip"),
    ("P0I", "tools/answer_a6/06_dong_goi.py", SUB / "submission_P0I.zip"),
]


def sha_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def sha_field(v) -> str:
    return sha_text(json.dumps(v, ensure_ascii=False, sort_keys=True))


def doc_zip(p: Path) -> dict:
    z = zipfile.ZipFile(p)
    return {r["id"]: r for r in json.loads(z.read("submission.json"))}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "reports/lineage")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    thieu = [str(z) for _, _, z in CHUOI if not z.is_file()]
    if thieu:
        print("THIEU ZIP:", thieu)
        return 2

    tang = [(ten, comp, doc_zip(z), sha_file(z)) for ten, comp, z in CHUOI]
    qids = sorted(tang[-1][2])

    # ── reason_code từ nhánh quyết định THẬT của packager cuối ─────────────
    a6 = {}
    p_a6 = ROOT / "data/dev/answer_a6/records_a6.jsonl"
    if p_a6.is_file():
        a6 = {json.loads(l)["qid"]: json.loads(l)
              for l in p_a6.open(encoding="utf-8") if l.strip()}
    giu_sohoc = set()
    p_sh = ROOT / "data/dev/so_hoc/records_sohoc.jsonl"
    if p_sh.is_file():
        for l in p_sh.open(encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                if r.get("trang_thai") == "OK":
                    giu_sohoc.add(r.get("qid") or r.get("id"))

    config_sha = {
        "answer_v2_03_dong_goi": sha_file(ROOT / "tools/answer_v2/03_dong_goi.py"),
        "so_hoc_07_dong_goi": sha_file(ROOT / "tools/so_hoc/07_dong_goi.py"),
        "answer_a6_06_dong_goi": sha_file(ROOT / "tools/answer_a6/06_dong_goi.py"),
    }
    input_sha = {
        "records_a6": sha_file(p_a6) if p_a6.is_file() else None,
        "records_sohoc": sha_file(p_sh) if p_sh.is_file() else None,
    }

    rows, dem_writer, dem_reason = [], collections.Counter(), collections.Counter()
    dem_field = collections.Counter()
    for q in qids:
        lich_su, writer, comp_cuoi, changed = [], CHUOI[0][0], CHUOI[0][1], []
        for i in range(1, len(tang)):
            ten, comp, cur, _ = tang[i]
            _, _, prv, _ = tang[i - 1]
            if q not in prv or q not in cur:
                lich_su.append({"stage": ten, "trang_thai": "QID_KHONG_CO_O_TANG_NAY"})
                continue
            doi = [f for f in TRUONG
                   if sha_field(prv[q].get(f)) != sha_field(cur[q].get(f))]
            lich_su.append({"stage": ten, "component": comp, "changed_fields": doi})
            if doi:
                writer, comp_cuoi, changed = ten, comp, doi

        if writer == CHUOI[0][0]:
            reason = "KHONG_TANG_NAO_DOI__KE_THUA_P0E"
        elif writer == "P0I":
            m = a6.get(q)
            reason = "A6_" + str(m.get("nguon")) if m else "A6_KHONG_CO_RECORD"
        elif writer == "P0G2":
            reason = "SO_HOC_OK" if q in giu_sohoc else "SO_HOC_GHI_NHUNG_KHONG_OK"
        else:
            reason = "ANSWER_V2_GHI"

        cuoi = tang[-1][2][q]
        rows.append({
            "qid": q,
            "final_writer": comp_cuoi,
            "final_writer_stage": writer,
            "changed_fields": changed,
            "source_sha": config_sha,
            "config_sha": sha_text(json.dumps(config_sha, sort_keys=True)),
            "input_sha": input_sha,
            "reason_code": reason,
            "lich_su_tang": lich_su,
            "final_field_sha": {f: sha_field(cuoi.get(f)) for f in TRUONG},
        })
        dem_writer[comp_cuoi] += 1
        dem_reason[reason] += 1
        for f in changed:
            dem_field[f] += 1

    (a.out / "official_field_lineage_1012.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")

    tom = {
        "_schema": "official_field_lineage_summary v1",
        "n_qid": len(rows),
        "chuoi_official": [
            {"stage": t, "component": c, "zip": z.name, "zip_sha256": s}
            for (t, c, z), (_, _, _, s) in zip(CHUOI, tang)],
        "final_writer_counts": dict(dem_writer),
        "reason_code_counts": dict(dem_reason),
        "changed_field_counts": dict(dem_field),
        "moi_qid_co_dung_mot_final_writer": len(rows) == len(qids),
        "ghi_chu": ("final_writer = tầng CUỐI CÙNG thực sự làm đổi answer/"
                    "pandas_query/evidence, đo bằng diff ZIP, không suy từ tên."),
    }
    (a.out / "official_field_lineage_summary.json").write_text(
        json.dumps(tom, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(tom, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
