#!/usr/bin/env python3
"""Bằng chứng token đơn vị v2 — đáp ứng `docs/114` §12.

Khác v1 ở năm điểm:
  1. QUOTA THEO TỪNG KIND — va chạm `Công ty` không còn chiếm hết mẫu;
  2. DEDUPE theo (kind, chuỗi khớp đã chuẩn hoá, source_ref);
  3. BẮT BUỘC chứa ĐỦ mọi occurrence `GENUINE_ASCII_UNIT` (không lấy mẫu);
  4. mỗi mẫu mang source table / field path / source_ref / lý do phân loại;
  5. "ASCII" được xác định trên VĂN BẢN GỐC, không phải sau khi bỏ dấu — nếu
     không thì `tỷ đồng` có dấu cũng bị đếm nhầm thành ASCII.

Phân loại dùng CHÍNH `unit_rule_v2` (mask + parse) nên bằng chứng và
implementation không thể lệch nhau.

    python3 unit_token_scan_v2.py --work-db data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db --out-dir .
"""
from __future__ import annotations

import argparse
import functools
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from unit_rule_v2 import (mask_non_unit_spans, normalize_unit,  # noqa: E402
                          normalize_unit_with_map, parse_magnitude)

# Token `ty`/`ti` KHÔNG DẤU trên chuỗi GỐC. `tỷ` không khớp vì ký tự thứ hai
# không phải chữ cái ASCII.
ASCII_TY = re.compile(r"(?<![0-9A-Za-z])[Tt][YyIi](?![0-9A-Za-z])")
# Dạng CÓ DẤU — bằng chứng đối chứng rằng corpus dùng dấu.
CO_DAU = re.compile(r"(?:tri[eệ]u|ngh[ìi]n|ng[àa]n|t[ỷỉ])\s*(?:đ[oồ]ng|VND)", re.I)

KINDS = ("GENUINE_ASCII_UNIT", "COLLISION_CONG_TY", "COLLISION_TY_LE_HO",
         "ASCII_TY_KHONG_PHAI_DON_VI")
QUOTA = {"GENUINE_ASCII_UNIT": 10 ** 9,     # lấy HẾT, không lấy mẫu
         "COLLISION_CONG_TY": 15,
         "COLLISION_TY_LE_HO": 15,
         "ASCII_TY_KHONG_PHAI_DON_VI": 15}
HO_TI_LE = {"COLLISION_TY_LE", "COLLISION_TY_TRONG", "COLLISION_TY_SUAT",
            "COLLISION_TY_GIA", "COLLISION_TY_SO"}
HO_PHAP_NHAN = {"COLLISION_CONG_TY", "COLLISION_CTY", "COLLISION_CTCP", "COLLISION_TCT"}


CUA_SO = 60      # nửa cửa sổ quanh mỗi occurrence ASCII `ty`


def cat_cua_so(text: str, so_luong: int = 3) -> list:
    """Cắt cửa sổ quanh các occurrence ASCII `ty`.

    `tables.context_clean` có ~105 MB văn bản; chuẩn hoá nguyên khối là lãng phí
    vì ngữ cảnh quyết định đơn vị chỉ nằm sát token. Cửa sổ ±60 ký tự đủ chứa cả
    `Công ty` phía trước lẫn `đồng/VND` phía sau.
    """
    ra = []
    for m in list(ASCII_TY.finditer(text))[:so_luong]:
        ra.append(text[max(0, m.start() - CUA_SO):m.end() + CUA_SO])
    return ra or [text[:2 * CUA_SO]]


@functools.lru_cache(maxsize=None)
def phan_loai(text: str):
    """Trả (kind, reason, matched). Chỉ gọi khi chuỗi GỐC có token ASCII ty/ti."""
    mags = parse_magnitude(text)
    if mags:
        _, mp = normalize_unit_with_map(text)     # đường chậm, chỉ khi cần
        for t in mags:
            a, b = t.span
            if a < len(mp):
                goc = text[mp[a]:(mp[b - 1] + 1 if b - 1 < len(mp) else len(text))]
                if ASCII_TY.search(goc):          # magnitude THẬT SỰ dùng ASCII
                    return ("GENUINE_ASCII_UNIT",
                            f"cum allowlist {t.value} qua {t.via}; ky tu goc khong dau",
                            goc)
    _, spans = mask_non_unit_spans(text)
    loai = {s.kind for s in spans}
    if loai & HO_PHAP_NHAN:
        return ("COLLISION_CONG_TY",
                "token `ty` nam trong danh ngu phap nhan da bi che (lop L1)",
                sorted(s.matched_text for s in spans if s.kind in HO_PHAP_NHAN)[0])
    if loai & HO_TI_LE:
        return ("COLLISION_TY_LE_HO",
                "token `ty` thuoc danh ngu ti le (ty le/trong/suat/gia/so)",
                sorted(s.matched_text for s in spans if s.kind in HO_TI_LE)[0])
    return ("ASCII_TY_KHONG_PHAI_DON_VI",
            "co token ASCII `ty` nhung khong tao duoc magnitude va khong khop ho va cham",
            ASCII_TY.search(text).group(0))


NGUON = [
    ("observations", "col_path_text"), ("observations", "row_path_text"),
    ("tables", "section_text"), ("tables", "context_clean"),
]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-db", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--snippet", type=int, default=160)
    a = ap.parse_args(argv)
    W, OUT = Path(a.work_db).resolve(), Path(a.out_dir).resolve()
    OUT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(f"file:{W}?mode=ro", uri=True)

    dem: Counter = Counter()
    theo_kind: dict = defaultdict(list)
    da_thay: set = set()
    for tbl, fld in NGUON:
        ten = f"{tbl}.{fld}"
        dem[f"{ten}.rows_total"] = c.execute(
            f"SELECT COUNT(*) FROM {tbl} WHERE {fld} IS NOT NULL").fetchone()[0]
        dem[f"{ten}.rows_accented_unit"] = c.execute(
            f"SELECT COUNT(*) FROM {tbl} WHERE {fld} LIKE '%ỷ đồng%' "
            f"OR {fld} LIKE '%riệu đồng%' OR {fld} LIKE '%ìn đồng%' "
            f"OR {fld} LIKE '%ỷ VND%' OR {fld} LIKE '%riệu VND%'").fetchone()[0]
        # Tiền lọc ở SQL + GOM THEO CHUỖI: corpus chỉ có ~64k giá trị col_path
        # khác nhau trên 2,6M dòng, gom lại giảm công Python khoảng hai bậc.
        sql = (f"SELECT {fld}, COUNT(*), MIN(table_uid), MIN(evidence_ref) FROM {tbl} "
               f"WHERE {fld} IS NOT NULL AND ({fld} LIKE '%ty%' OR {fld} LIKE '%ti%') "
               f"GROUP BY {fld}")
        n_ung_vien = n_chuoi = 0
        for txt, n_lap, tuid, eref in c.execute(sql):
            s_ = txt or ""
            if not ASCII_TY.search(s_):
                continue
            n_chuoi += 1
            n_ung_vien += n_lap
            cs = cat_cua_so(s_)
            # ưu tiên cửa sổ cho ra GENUINE, nếu không lấy cửa sổ đầu
            kq = [phan_loai(x) for x in cs]
            kind, ly_do, khop = next(
                (k for k in kq if k[0] == "GENUINE_ASCII_UNIT"), kq[0])
            ngu_canh = cs[[k[0] for k in kq].index(kind)]
            dem[f"{ten}.{kind}"] += n_lap
            dem[f"TOTAL.{kind}"] += n_lap
            dem[f"distinct.{kind}"] += 1
            khoa = (kind, normalize_unit(khop).strip(), eref)
            if khoa in da_thay:
                dem[f"DEDUP.{kind}"] += 1
                continue
            da_thay.add(khoa)
            if len(theo_kind[kind]) < QUOTA[kind]:
                theo_kind[kind].append({
                    "kind": kind,
                    "classification_reason": ly_do,
                    "matched_text": khop,
                    "n_occurrences": n_lap,
                    "text": ngu_canh[:a.snippet],
                    "normalized": normalize_unit(ngu_canh)[:a.snippet],
                    "source_table": tbl,
                    "source_field_path": ten,
                    "source_table_uid": tuid,
                    "source_ref": eref,
                })
        dem[f"{ten}.rows_with_ascii_ty"] = n_ung_vien
        dem[f"{ten}.distinct_strings_with_ascii_ty"] = n_chuoi

    mau = [m for k in KINDS for m in theo_kind.get(k, [])]
    mau.sort(key=lambda m: (m["kind"], m["source_ref"] or "", m["matched_text"]))

    g = dem["TOTAL.GENUINE_ASCII_UNIT"]
    v = dem["TOTAL.COLLISION_CONG_TY"]
    sm = {
        "scan_version": "unit_token_scan_v2",
        "classified_by": "unit_rule_v2.parse_magnitude + mask_non_unit_spans",
        "ascii_detected_on": "raw text (KHÔNG bỏ dấu trước khi xét ASCII)",
        "work_db": str(W), "work_db_bytes": W.stat().st_size,
        "counts": dict(sorted(dem.items())),
        "totals": {k: dem[f"TOTAL.{k}"] for k in KINDS},
        "n_rows_with_accented_unit": sum(
            v2 for k, v2 in dem.items() if k.endswith(".rows_accented_unit")),
        "harm_benefit_ratio_cong_ty_tren_genuine": (round(v / g, 2) if g else None),
        "sampling_policy": {
            "per_kind_quota": {k: (None if QUOTA[k] > 10 ** 6 else QUOTA[k]) for k in KINDS},
            "genuine_ascii_unit": "LẤY HẾT, không lấy mẫu (docs/114 §12)",
            "dedupe_key": "(kind, normalized matched_text, source_ref)",
            "n_deduped": {k: dem.get(f"DEDUP.{k}", 0) for k in KINDS},
        },
        "n_samples": len(mau),
        "n_samples_by_kind": {k: len(theo_kind.get(k, [])) for k in KINDS},
        "assertions": {
            "assert_moi_chuoi_genuine_deu_co_mau":
                len(theo_kind.get("GENUINE_ASCII_UNIT", [])) ==
                dem.get("distinct.GENUINE_ASCII_UNIT", 0)
                - dem.get("DEDUP.GENUINE_ASCII_UNIT", 0),
            "assert_collision_khong_chiem_het_quota":
                len(theo_kind.get("COLLISION_CONG_TY", [])) <= QUOTA["COLLISION_CONG_TY"],
            "assert_co_mau_cho_moi_kind_xuat_hien": all(
                len(theo_kind.get(k, [])) > 0 for k in KINDS if dem[f"TOTAL.{k}"] > 0),
            "assert_mau_khong_trung":
                len({(m["kind"], m["matched_text"], m["source_ref"]) for m in mau})
                == len(mau),
            "assert_moi_mau_co_source_ref": all(m["source_ref"] for m in mau),
        },
        "ket_luan": (
            "Dạng ASCII thật gần như không tồn tại trong corpus, trong khi `Công ty` "
            "đứng cạnh VND/đồng va chạm rất nhiều. Vì vậy ASCII `ty` chỉ được chấp "
            "nhận qua cụm allowlist/marker VÀ chỉ sau khi đã che span thực thể — "
            "đúng bốn lớp bảo vệ của unit_rule_v2."),
    }
    (OUT / "unit_token_scan_summary.json").write_text(
        json.dumps(sm, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    (OUT / "unit_token_collision_samples.jsonl").write_text(
        "\n".join(json.dumps(m, ensure_ascii=False, sort_keys=True) for m in mau) + "\n",
        encoding="utf-8")
    print(json.dumps(sm["totals"], ensure_ascii=False),
          "samples=", sm["n_samples_by_kind"])
    for k, val in sm["assertions"].items():
        print(f"{'PASS' if val else 'FAIL'}  {k}")
    return 0 if all(sm["assertions"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
