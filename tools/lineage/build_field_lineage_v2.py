#!/usr/bin/env python3
"""official_field_lineage_1012 v2 — F3 của review 163.

Bản v1 chỉ diff ZIP nên chỉ thấy `final_effective_writer`. Review 163 §4 F3 đòi
tách ba khái niệm; chúng KHÁC nhau và trộn chúng là cách tạo ra phát biểu
"component X quyết định 953 câu" trong khi X có thể chỉ đổi `pandas_query`.

* `attempted_writers`  — tầng ĐÃ XÉT QID này, suy từ **hợp đồng đọc được trong
  source của chính packager**, không từ diff. Một tầng chạy rồi ghi ra đúng giá
  trị cũ vẫn là `attempted` nhưng KHÔNG `effective` — diff không thấy nó.
* `effective_writers`  — tầng làm đổi ít nhất một trường so với ĐẦU VÀO của nó.
* `final_effective_writer` — phần tử cuối cùng của `effective_writers`.

Hợp đồng attempted, trích thẳng từ source:

| tầng | attempted |
|---|---|
| `answer_v2/03_dong_goi.py` | **mọi QID** — vòng `for r in sub` ghi cả nhánh `giu` (`answer=0.0`, `query=""`, `evidence=[]`) |
| `so_hoc/07_dong_goi.py` | chỉ QID có `trang_thai == "OK"`; `if not m: continue` |
| `answer_a6/06_dong_goi.py` | QID KHÔNG thuộc `giu_sohoc` **và** có record A6 dùng được |
"""
from __future__ import annotations

import collections
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/163/lineage"
SUB = ROOT / "artifacts/submissions/legacy"
TRUONG = ("answer", "pandas_query", "evidence")

TANG = [("P0E", "GOC_CHUOI", SUB / "submission_P0E.zip"),
        ("P0G", "tools/answer_v2/03_dong_goi.py", SUB / "submission_P0G.zip"),
        ("P0G2", "tools/so_hoc/07_dong_goi.py", SUB / "submission_P0G2.zip"),
        ("P0I", "tools/answer_a6/06_dong_goi.py", SUB / "submission_P0I.zip")]


def shaf(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def shaj(v) -> str:
    return hashlib.sha256(
        json.dumps(v, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def jl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    z = {t: {r["id"]: r for r in
             json.loads(zipfile.ZipFile(p).read("submission.json"))}
         for t, _, p in TANG}
    qids = sorted(z["P0I"])

    p_a6 = ROOT / "data/curated/dev-legacy/answer_a6/records_a6.jsonl"
    p_sh = ROOT / "data/curated/dev-legacy/so_hoc/records_sohoc.jsonl"
    p_v3 = ROOT / "data/curated/dev-legacy/answer_v2/records_v3.jsonl"
    a6 = {r["qid"]: r for r in jl(p_a6)} if p_a6.is_file() else {}
    sh_ok = {r.get("qid") or r.get("id") for r in jl(p_sh)
             if r.get("trang_thai") == "OK"} if p_sh.is_file() else set()
    v3 = {r["qid"]: r for r in jl(p_v3)} if p_v3.is_file() else {}

    src_sha = {t: shaf(ROOT / c) for t, c, _ in TANG
               if c != "GOC_CHUOI" and (ROOT / c).is_file()}
    in_sha = {"records_a6": shaf(p_a6) if p_a6.is_file() else None,
              "records_sohoc": shaf(p_sh) if p_sh.is_file() else None,
              "records_v3": shaf(p_v3) if p_v3.is_file() else None}
    cfg_sha = shaj(src_sha)

    rows = []
    d_final, d_eff, d_att = collections.Counter(), collections.Counter(), collections.Counter()
    for q in qids:
        att, eff, doi_theo_tang = [], [], {}
        for i in range(1, len(TANG)):
            ten, comp, _ = TANG[i]
            prv, cur = z[TANG[i - 1][0]][q], z[ten][q]
            # attempted — theo HỢP ĐỒNG SOURCE, không theo diff
            if ten == "P0G":
                da_xet = True                      # vòng lặp ghi mọi QID
            elif ten == "P0G2":
                da_xet = q in sh_ok
            else:
                m = a6.get(q)
                da_xet = (q not in sh_ok and bool(m) and bool(m.get("evidence"))
                          and m.get("answer") is not None)
            if da_xet:
                att.append(comp)
                d_att[comp] += 1
            ch = [f for f in TRUONG if shaj(prv.get(f)) != shaj(cur.get(f))]
            doi_theo_tang[comp] = ch
            if ch:
                eff.append(comp)
                d_eff[comp] += 1
        final = eff[-1] if eff else "GOC_CHUOI__khong_tang_nao_doi"
        d_final[final] += 1

        m = a6.get(q)
        if final.endswith("06_dong_goi.py"):
            rc = "A6_" + str(m.get("nguon")) if m else "A6_KHONG_RECORD"
        elif final.endswith("07_dong_goi.py"):
            rc = "SO_HOC_OK"
        elif final.endswith("03_dong_goi.py"):
            rc = "ANSWER_V2_GHI"
        else:
            rc = "KE_THUA_P0E"
        rows.append({
            "qid": q,
            "attempted_writers": att,
            "effective_writers": eff,
            "final_effective_writer": final,
            "fields_changed_by_each_writer": doi_theo_tang,
            "attempted_nhung_khong_effective": [w for w in att if w not in eff],
            "input_record_id": {
                "records_a6": f"qid:{q}" if q in a6 else None,
                "records_sohoc_OK": q in sh_ok,
                "records_v3": f"qid:{q}" if q in v3 else None},
            "input_sha": in_sha,
            "source_sha": src_sha,
            "config_sha": cfg_sha,
            "reason_code": rc,
            "final_field_sha": {f: shaj(z["P0I"][q].get(f)) for f in TRUONG},
        })

    n_am_tham = sum(1 for r in rows if r["attempted_nhung_khong_effective"])
    tom = {
        "_schema": "official_field_lineage_summary v2",
        "n_qid": len(rows),
        "chuoi": [{"stage": t, "component": c, "zip": p.name,
                   "zip_sha256": shaf(p)} for t, c, p in TANG],
        "final_effective_writer_counts": dict(d_final),
        "effective_writer_counts": dict(d_eff),
        "attempted_writer_counts": dict(d_att),
        "n_qid_co_writer_chay_nhung_khong_doi_gi": n_am_tham,
        "DINH_CHINH_953_37_21_1": (
            "953/37/21/1 là FINAL_EFFECTIVE_WRITER, KHÔNG phải 'component quyết "
            "định đáp án'. Xem effective_writer_counts và attempted_writer_counts "
            "để thấy chênh lệch."),
        "moi_qid_co_dung_mot_final_effective_writer": True,
    }
    (OUT / "official_field_lineage_1012.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    (OUT / "lineage_summary.json").write_text(
        json.dumps(tom, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(tom, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
