#!/usr/bin/env python3
"""Overlay wrapper trên EXACT P0I — F2/F17 review 163.

`official_build_wrapper.py` dựng lại P0I từ P0G2 + records, và điều đó **không
thể** tái lập P0I vì records lịch sử đã mất (`NOT_REBUILDABLE`). F2 chỉ ra cách
đóng Phase 0 đúng: **đừng dựng lại lịch sử**. Lấy P0I ZIP làm parent bất biến,
overlay chỉ *vá* các QID trong whitelist.

    feature_off  = không đọc lại 953 record, không diễn giải gì → canonical diff 0
    feature_on   = chỉ patch QID/field trong whitelist, phần còn lại copy nguyên

Đây là điều kiện để mọi candidate sau này (U1, E1) có rollback thật: tắt cờ là
ra lại đúng `fa27e15d…`.

    python3 tools/lineage/overlay_wrapper.py --parent-zip artifacts/submissions/legacy/submission_P0I.zip \
        --output-zip /tmp/p0i_noop.zip --report reports/163/lineage/overlay_noop_report.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TRUONG = ("answer", "pandas_query", "evidence")
KHOA = ("relevant_tables", "relevant_docs", "question", "id")
NGAY = (2026, 1, 1, 0, 0, 0)


def shab(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def shaf(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def canon(rows) -> bytes:
    """ĐÚNG phép tuần tự hoá của packager gốc — đã kiểm trùng byte với raw P0I."""
    return json.dumps(rows, ensure_ascii=False, indent=1).encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--parent-zip", type=Path,
                    default=ROOT / "artifacts/submissions/legacy/submission_P0I.zip")
    ap.add_argument("--overlay", type=Path, default=None,
                    help="JSONL {qid, answer?, pandas_query?, evidence?}; "
                         "để trống = feature_off")
    ap.add_argument("--whitelist", type=Path, default=None,
                    help="JSON có khoá whitelist_qids; bắt buộc khi có --overlay")
    ap.add_argument("--output-zip", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    a = ap.parse_args()
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.output_zip.parent.mkdir(parents=True, exist_ok=True)

    zin = zipfile.ZipFile(a.parent_zip)
    raw_parent = zin.read("submission.json")
    rows = json.loads(raw_parent)
    parent_canon = shab(canon(rows))
    parent_raw = shab(raw_parent)

    wl, ov = set(), {}
    if a.overlay is not None:
        if a.whitelist is None:
            print("CHAN: có --overlay thì BẮT BUỘC --whitelist"); return 2
        wl = set(json.loads(a.whitelist.read_text(encoding="utf-8"))["whitelist_qids"])
        ov = {r["qid"]: r for r in (json.loads(l) for l in
              a.overlay.open(encoding="utf-8") if l.strip())}
        ngoai = sorted(set(ov) - wl)
        if ngoai:
            print(f"CHAN: overlay chạm {len(ngoai)} QID NGOÀI whitelist: {ngoai[:10]}")
            return 2

    doi, chi_tiet = 0, []
    for r in rows:
        q = r["id"]
        if q not in ov:
            continue
        m, ch = ov[q], []
        for f in TRUONG:
            if f in m and json.dumps(m[f], ensure_ascii=False, sort_keys=True) != \
                          json.dumps(r.get(f), ensure_ascii=False, sort_keys=True):
                r[f] = m[f]
                ch.append(f)
        if ch:
            doi += 1
            chi_tiet.append({"qid": q, "changed_fields": ch})

    # CỔNG CỨNG: overlay không được chạm hợp đồng Retrieval
    goc = {x["id"]: x for x in json.loads(raw_parent)}
    for r in rows:
        for f in KHOA:
            if json.dumps(r.get(f), ensure_ascii=False) != \
               json.dumps(goc[r["id"]].get(f), ensure_ascii=False):
                print(f"CHAN q{r['id']}: overlay đã đổi trường khoá {f}")
                return 2

    out = canon(rows)
    names = zin.namelist()
    with zipfile.ZipFile(a.output_zip, "w", zipfile.ZIP_DEFLATED) as zo:
        for n in names:
            zi = zipfile.ZipInfo(n, date_time=NGAY)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = 0o644 << 16
            zo.writestr(zi, out if n == "submission.json" else zin.read(n))

    noop = (a.overlay is None)
    kq = {
        "_schema": "overlay_wrapper_report v1",
        "che_do": "feature_off" if noop else "feature_on",
        "parent_zip": str(a.parent_zip),
        "parent_zip_sha256": shaf(a.parent_zip),
        "parent_submission_raw_sha256": parent_raw,
        "parent_submission_canonical_sha256": parent_canon,
        "output_submission_canonical_sha256": shab(out),
        "CANONICAL_DIFF_0": shab(out) == parent_canon,
        "n_qid_doi": doi, "changed": chi_tiet,
        "n_member_parent": len(names),
        "n_member_output": len(zipfile.ZipFile(a.output_zip).namelist()),
        "MEMBER_SET_KHOP": sorted(names) == sorted(
            zipfile.ZipFile(a.output_zip).namelist()),
        "whitelist_n": len(wl),
        "changes_outside_whitelist": 0,
        "GATE": ("FEATURE_OFF_NOOP_PASS" if noop and shab(out) == parent_canon
                 else "FEATURE_OFF_NOOP_FAIL" if noop
                 else "FEATURE_ON"),
    }
    a.report.write_text(json.dumps(kq, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(kq, ensure_ascii=False, indent=1))
    return 0 if (not noop or kq["CANONICAL_DIFF_0"]) else 1


if __name__ == "__main__":
    raise SystemExit(main())
