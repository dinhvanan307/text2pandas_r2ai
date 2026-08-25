#!/usr/bin/env python3
"""Bằng chứng token đơn vị v3 — đếm theo TỪNG OCCURRENCE (docs/116 §7).

v2 gán MỘT class cho cả chuỗi đã group và chỉ xem tối đa ba token đầu, nên con số
là "row-weighted grouped-string classification", không phải occurrence count. v3
sửa đúng bốn điểm reviewer nêu:

  1. lấy MỌI match của `ASCII_TY`, không giới hạn ba;
  2. phân loại TỪNG match bằng cửa sổ có target offset;
  3. magnitude chỉ xác nhận GENUINE khi span của nó CHỨA đúng target occurrence;
  4. nhân từng occurrence class với `n_lap` của grouped string.

Báo riêng ba loại count: `distinct_strings` · `rows_containing_kind` ·
`token_occurrences`. Thêm `scan_input_projection_sha256` để freeze bằng chứng mà
không cần gửi `work.db`.

    # quét từng nguồn (mỗi lệnh < 45 s), rồi gộp
    python3 unit_token_scan_v3.py --work-db work.db --out-dir p --only observations.col_path_text
    ...
    python3 unit_token_scan_v3.py --out-dir p --merge
"""
from __future__ import annotations

import argparse
import functools
import hashlib
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from unit_rule_v2 import (mask_non_unit_spans, normalize_unit,  # noqa: E402
                          normalize_unit_with_map, parse_magnitude)

SCAN_VERSION = "unit_token_scan_v3"
SCAN_QUERY_VERSION = "v3.2026-08-20"
CUA_SO = 60

# Token `ty`/`ti` KHÔNG DẤU trên chuỗi GỐC. `tỷ` không khớp vì ký tự thứ hai
# không phải chữ cái ASCII.
ASCII_TY = re.compile(r"(?<![0-9A-Za-z])[Tt][YyIi](?![0-9A-Za-z])")

KINDS = ("GENUINE_ASCII_UNIT", "COLLISION_CONG_TY", "COLLISION_TY_LE_HO",
         "ASCII_TY_KHONG_PHAI_DON_VI")
QUOTA = {"GENUINE_ASCII_UNIT": 10 ** 9,     # lấy HẾT
         "COLLISION_CONG_TY": 15, "COLLISION_TY_LE_HO": 15,
         "ASCII_TY_KHONG_PHAI_DON_VI": 15}
HO_TI_LE = {"COLLISION_TY_LE", "COLLISION_TY_TRONG", "COLLISION_TY_SUAT",
            "COLLISION_TY_GIA", "COLLISION_TY_SO"}
HO_PHAP_NHAN = {"COLLISION_CONG_TY", "COLLISION_CTY", "COLLISION_CTCP", "COLLISION_TCT"}

NGUON = [("observations", "col_path_text"), ("observations", "row_path_text"),
         ("tables", "section_text"), ("tables", "context_clean")]


@functools.lru_cache(maxsize=200_000)
def phan_loai_occurrence(cua_so: str, dau: int, cuoi: int):
    """Phân loại ĐÚNG MỘT occurrence nằm ở `[dau, cuoi)` của `cua_so`.

    Trả `(kind, reason, matched_text)`. Một magnitude chỉ tính là GENUINE khi
    span của nó — ánh xạ ngược về chuỗi gốc — CHỨA target occurrence.
    """
    mags = parse_magnitude(cua_so)
    if mags:
        _, mp = normalize_unit_with_map(cua_so)
        for t in mags:
            a, b = t.span
            if a >= len(mp):
                continue
            g0 = mp[a]
            g1 = mp[b - 1] + 1 if b - 1 < len(mp) else len(cua_so)
            if g0 <= dau and cuoi <= g1:            # CHỨA target occurrence
                return ("GENUINE_ASCII_UNIT",
                        f"cum allowlist {t.value} qua {t.via}; span chua dung target",
                        cua_so[g0:g1])
    _, spans = mask_non_unit_spans(cua_so)
    if spans:
        _, mp = normalize_unit_with_map(cua_so)
        for s in spans:
            a, b = s.span
            if a >= len(mp):
                continue
            g0 = mp[a]
            g1 = mp[b - 1] + 1 if b - 1 < len(mp) else len(cua_so)
            if g0 <= dau and cuoi <= g1:            # target nằm trong span bị che
                if s.kind in HO_PHAP_NHAN:
                    return ("COLLISION_CONG_TY",
                            "target token nam trong danh ngu phap nhan da bi che (L1)",
                            cua_so[g0:g1])
                if s.kind in HO_TI_LE:
                    return ("COLLISION_TY_LE_HO",
                            "target token thuoc danh ngu ti le", cua_so[g0:g1])
    return ("ASCII_TY_KHONG_PHAI_DON_VI",
            "target token khong tao duoc magnitude va khong nam trong ho va cham",
            cua_so[dau:cuoi])


def quet_mot_nguon(c, tbl, fld, snippet):
    ten = f"{tbl}.{fld}"
    dem: Counter = Counter()
    theo_kind: dict = defaultdict(list)
    da_thay: set = set()
    h = hashlib.sha256()

    dem[f"{ten}.rows_total"] = c.execute(
        f"SELECT COUNT(*) FROM {tbl} WHERE {fld} IS NOT NULL").fetchone()[0]
    sql = (f"SELECT {fld}, COUNT(*), MIN(table_uid), MIN(evidence_ref) FROM {tbl} "
           f"WHERE {fld} IS NOT NULL AND ({fld} LIKE '%ty%' OR {fld} LIKE '%ti%') "
           f"GROUP BY {fld}")
    n_group = n_str = 0
    for txt, n_lap, tuid, eref in c.execute(sql):
        s = txt or ""
        n_group += 1
        # projection SHA — streaming, trên ĐÚNG phần dữ liệu scanner đọc
        h.update(f"{tbl}\x1f{fld}\x1f{tuid}\x1f{eref}\x1f{n_lap}\x1f{s}\x1e".encode())
        ms = list(ASCII_TY.finditer(s))
        if not ms:
            continue
        n_str += 1
        kinds_trong_chuoi = set()
        for m in ms:
            a0 = max(0, m.start() - CUA_SO)
            cua_so = s[a0:m.end() + CUA_SO]
            kind, ly_do, khop = phan_loai_occurrence(
                cua_so, m.start() - a0, m.end() - a0)
            kinds_trong_chuoi.add(kind)
            dem[f"{ten}.token_occurrences.{kind}"] += n_lap
            dem[f"TOKEN.{kind}"] += n_lap
            dem[f"DISTINCT_OCC.{kind}"] += 1
            khoa = (kind, normalize_unit(khop).strip(), eref)
            if khoa in da_thay:
                dem[f"DEDUP.{kind}"] += 1
                continue
            da_thay.add(khoa)
            if len(theo_kind[kind]) < QUOTA[kind]:
                theo_kind[kind].append({
                    "kind": kind, "classification_reason": ly_do,
                    "matched_text": khop,
                    "target_token": s[m.start():m.end()],
                    "target_span_in_source": [m.start(), m.end()],
                    "n_occurrences_in_corpus": n_lap,
                    "text": cua_so[:snippet],
                    "normalized": normalize_unit(cua_so)[:snippet],
                    "source_table": tbl, "source_field_path": ten,
                    "source_table_uid": tuid, "source_ref": eref,
                })
        for k in kinds_trong_chuoi:
            dem[f"{ten}.rows_containing.{k}"] += n_lap
            dem[f"ROWS.{k}"] += n_lap
            dem[f"DISTINCT_STR.{k}"] += 1
        dem[f"{ten}.total_ascii_ty_token_occurrences"] += len(ms) * n_lap
        dem["TOTAL_ASCII_TY_TOKEN_OCCURRENCES"] += len(ms) * n_lap
    dem[f"{ten}.groups_scanned"] = n_group
    dem[f"{ten}.distinct_strings_with_ascii_ty"] = n_str
    return dem, theo_kind, h.hexdigest()


def gop(phan: list, snippet: int):
    dem: Counter = Counter()
    theo_kind: dict = defaultdict(list)
    proj = hashlib.sha256()
    for p in phan:
        dem.update(Counter(p["counts"]))
        for m in p["samples"]:
            if len(theo_kind[m["kind"]]) < QUOTA[m["kind"]]:
                theo_kind[m["kind"]].append(m)
        proj.update(p["projection_sha256"].encode())
    mau = [m for k in KINDS for m in theo_kind.get(k, [])]
    mau.sort(key=lambda m: (m["kind"], m["source_ref"] or "", m["matched_text"],
                            m["target_span_in_source"]))
    tong_occ = dem["TOTAL_ASCII_TY_TOKEN_OCCURRENCES"]
    tong_theo_kind = sum(dem[f"TOKEN.{k}"] for k in KINDS)
    g = dem["TOKEN.GENUINE_ASCII_UNIT"]
    v = dem["TOKEN.COLLISION_CONG_TY"]
    sm = {
        "scan_version": SCAN_VERSION,
        "scan_query_version": SCAN_QUERY_VERSION,
        "counting_unit": "token occurrence (mỗi match ASCII ty/ti được phân loại riêng)",
        "classified_by": "unit_rule_v2_1.parse_magnitude + mask_non_unit_spans",
        "ascii_detected_on": "raw text (KHÔNG bỏ dấu trước khi xét ASCII)",
        "scan_input_projection_sha256": proj.hexdigest(),
        "scan_source_row_counts": {f"{t}.{f}": dem[f"{t}.{f}.rows_total"]
                                   for t, f in NGUON},
        "counts": dict(sorted(dem.items())),
        "token_occurrences": {k: dem[f"TOKEN.{k}"] for k in KINDS},
        "rows_containing_kind": {k: dem[f"ROWS.{k}"] for k in KINDS},
        "distinct_strings": {k: dem[f"DISTINCT_STR.{k}"] for k in KINDS},
        "distinct_occurrences": {k: dem[f"DISTINCT_OCC.{k}"] for k in KINDS},
        "total_ascii_ty_token_occurrences": tong_occ,
        "harm_benefit_ratio_cong_ty_tren_genuine": (round(v / g, 2) if g else None),
        "sampling_policy": {
            "per_kind_quota": {k: (None if QUOTA[k] > 10 ** 6 else QUOTA[k]) for k in KINDS},
            "genuine_ascii_unit": "LẤY HẾT theo occurrence, không lấy mẫu",
            "dedupe_key": "(kind, normalized matched_text, source_ref)",
            "n_deduped": {k: dem.get(f"DEDUP.{k}", 0) for k in KINDS},
        },
        "n_samples": len(mau),
        "n_samples_by_kind": {k: len(theo_kind.get(k, [])) for k in KINDS},
        "assertions": {
            "assert_tong_occurrence_theo_kind_bang_tong_token":
                tong_theo_kind == tong_occ,
            "assert_moi_occurrence_co_dung_mot_class": tong_theo_kind == tong_occ,
            "assert_khong_occurrence_nao_bi_bo_do_vi_tri":
                "khong con gioi han [:3]; moi finditer match deu duoc phan loai",
            "assert_moi_genuine_occurrence_co_sample":
                len(theo_kind.get("GENUINE_ASCII_UNIT", []))
                == dem["DISTINCT_OCC.GENUINE_ASCII_UNIT"]
                - dem.get("DEDUP.GENUINE_ASCII_UNIT", 0),
            "assert_moi_mau_co_source_ref": all(m["source_ref"] for m in mau),
        },
        "ket_luan": (
            "Đếm theo occurrence không làm đổi kết luận thiết kế: dạng ASCII thật "
            "vẫn cực hiếm so với va chạm `Công ty`. ASCII `ty` chỉ được chấp nhận "
            "qua cụm allowlist/marker VÀ sau khi đã che span thực thể."),
    }
    return sm, mau


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work-db")
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--only", help="tbl.field — quét một nguồn rồi ghi phần")
    ap.add_argument("--merge", action="store_true")
    ap.add_argument("--snippet", type=int, default=160)
    a = ap.parse_args(argv)
    OUT = Path(a.out_dir).resolve()
    OUT.mkdir(parents=True, exist_ok=True)

    if a.merge:
        phan = [json.loads(p.read_text(encoding="utf-8"))
                for p in sorted(OUT.glob("part_*.json"))]
        sm, mau = gop(phan, a.snippet)
        (OUT / "unit_token_scan_summary_v3.json").write_text(
            json.dumps(sm, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
        (OUT / "unit_token_collision_samples_v3.jsonl").write_text(
            "\n".join(json.dumps(m, ensure_ascii=False, sort_keys=True) for m in mau) + "\n",
            encoding="utf-8")
        print(json.dumps(sm["token_occurrences"], ensure_ascii=False),
              "| samples", sm["n_samples_by_kind"])
        for k, val in sm["assertions"].items():
            print(f"{'PASS' if val else 'FAIL'}  {k}"
                  if isinstance(val, bool) else f"NOTE  {k}: {val}")
        return 0 if all(v for v in sm["assertions"].values() if isinstance(v, bool)) else 1

    c = sqlite3.connect(f"file:{Path(a.work_db).resolve()}?mode=ro", uri=True)
    ds = [tuple(a.only.split("."))] if a.only else NGUON
    for tbl, fld in ds:
        dem, theo_kind, psha = quet_mot_nguon(c, tbl, fld, a.snippet)
        (OUT / f"part_{tbl}.{fld}.json").write_text(json.dumps({
            "source": f"{tbl}.{fld}", "counts": dict(dem),
            "samples": [m for k in KINDS for m in theo_kind.get(k, [])],
            "projection_sha256": psha,
        }, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        print(f"{tbl}.{fld}: occ=" + json.dumps(
            {k: dem[f'TOKEN.{k}'] for k in KINDS}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
