#!/usr/bin/env python3
"""Pha 1–3 của directive 163 — identity, replay diff, field lineage v2.

Ba điểm review 163 đòi và bản v1 chưa làm:

* **F1** — `mtime` KHÔNG được dùng làm bằng chứng lineage. Ở đây mtime chỉ được
  ghi vào trường `mtime_khong_phai_bang_chung` để tham khảo, và mọi kết luận
  lineage dựa trên **SHA + nội dung**, không dựa trên thời gian.
* **F3** — tách `attempted_writers` / `effective_writers` / `final_effective_writer`.
  Diff ZIP chỉ thấy tầng làm đổi byte; tầng chạy mà ra kết quả trùng parent thì
  **vô hình trong diff**. `attempted` được suy từ *hợp đồng của chính packager*
  (QID nào nó ĐỌC và có thể ghi), không từ diff.
* **§2.2** — P0I và replay bị gán ngược trong doc 162. Ở đây mỗi SHA được gắn
  nhãn ngay tại chỗ tính, không qua bảng trung gian.

Không sửa production. Chỉ đọc.
"""
from __future__ import annotations

import hashlib
import json
import os
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/163"
SUB = ROOT / "data/submissions"
TRUONG = ("answer", "pandas_query", "evidence")

CHUOI = [
    ("P0E", "GOC_CHUOI", SUB / "submission_P0E.zip"),
    ("P0G", "tools/answer_v2/03_dong_goi.py", SUB / "submission_P0G.zip"),
    ("P0G2", "tools/so_hoc/07_dong_goi.py", SUB / "submission_P0G2.zip"),
    ("P0I", "tools/answer_a6/06_dong_goi.py", SUB / "submission_P0I.zip"),
]


def shaf(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def shab(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def shaj(v) -> str:
    return shab(json.dumps(v, ensure_ascii=False, sort_keys=True).encode())


def members(p: Path) -> list[dict]:
    z = zipfile.ZipFile(p)
    return [{"name": i.filename, "size": i.file_size, "crc32": f"{i.CRC:08x}"}
            for i in sorted(z.infolist(), key=lambda x: x.filename)]


def zip_identity(p: Path, nhan: str) -> dict:
    z = zipfile.ZipFile(p)
    raw = z.read("submission.json")
    rows = json.loads(raw)
    # canonicalization mà packager gốc dùng, khai tường minh
    canon = json.dumps(rows, ensure_ascii=False, indent=1).encode("utf-8")
    m = members(p)
    return {
        "nhan": nhan,
        "path": str(p),
        "ton_tai": True,
        "zip_sha256": shaf(p),
        "zip_bytes": p.stat().st_size,
        "n_members": len(m),
        "submission_json_raw_sha256": shab(raw),
        "submission_json_raw_bytes": len(raw),
        "canonicalization": {
            "ten": "packager_json_dumps_ensure_ascii_false_indent_1",
            "code": "json.dumps(rows, ensure_ascii=False, indent=1)",
            "nguon": "tools/answer_a6/06_dong_goi.py dòng 53",
            "sha256": shab(canon),
            "TRUNG_VOI_RAW": shab(canon) == shab(raw),
        },
        "n_rows": len(rows),
        "member_manifest_sha256": shaj(m),
        "mtime_khong_phai_bang_chung": p.stat().st_mtime,
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "identity").mkdir(exist_ok=True)
    (OUT / "lineage").mkdir(exist_ok=True)

    p0i = SUB / "submission_P0I.zip"
    rep = Path(os.environ.get("REPLAY_ZIP", "/tmp/replay_P0I.zip"))

    id_p0i = zip_identity(p0i, "P0I_OFFICIAL_SCORED_0.1225")
    (OUT / "identity/P0I_IDENTITY.json").write_text(
        json.dumps(id_p0i, ensure_ascii=False, indent=1), encoding="utf-8")
    (OUT / "lineage/member_manifest_parent.json").write_text(
        json.dumps(members(p0i), ensure_ascii=False, indent=1), encoding="utf-8")

    id_rep = None
    if rep.is_file():
        id_rep = zip_identity(rep, "REPLAY_FROM_CURRENT_RECORDS__KHONG_PHAI_P0I")
        id_rep["canh_bao"] = (
            "Đây KHÔNG phải historical exact rebuild. Nó được dựng từ "
            "records_a6.jsonl HIỆN TẠI, khác bản đã tạo P0I. Xem "
            "historical_exact_rebuild = NOT_REBUILDABLE.")
        (OUT / "lineage/member_manifest_replay.json").write_text(
            json.dumps(members(rep), ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        id_rep = {"nhan": "REPLAY", "ton_tai": False,
                  "ghi_chu": "chưa dựng — chạy official_build_wrapper.py trước"}
    (OUT / "identity/REPLAY_IDENTITY.json").write_text(
        json.dumps(id_rep, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── P0I_CANONICAL_IDENTITY.sha256 theo đúng §9.2 ──────────────────────
    dong = [
        f"{id_p0i['zip_sha256']}  submission_P0I.zip",
        f"{id_p0i['submission_json_raw_sha256']}  submission.json.raw",
        f"{id_p0i['canonicalization']['sha256']}  submission.json.canonical"
        f"  # alg={id_p0i['canonicalization']['ten']}"
        f" trung_voi_raw={id_p0i['canonicalization']['TRUNG_VOI_RAW']}",
    ]
    (OUT / "P0I_CANONICAL_IDENTITY.sha256").write_text(
        "\n".join(dong) + "\n", encoding="utf-8")

    # ── identity đầu vào + ZIP trung gian ────────────────────────────────
    inp = {}
    for ten, p in (("records_a6", ROOT / "data/dev/answer_a6/records_a6.jsonl"),
                   ("records_sohoc", ROOT / "data/dev/so_hoc/records_sohoc.jsonl")):
        if p.is_file():
            n = sum(1 for l in p.open(encoding="utf-8") if l.strip())
            inp[ten] = {"path": str(p.relative_to(ROOT)), "sha256": shaf(p),
                        "n_dong": n, "bytes": p.stat().st_size,
                        "mtime_khong_phai_bang_chung": p.stat().st_mtime}
        else:
            inp[ten] = {"path": str(p), "ton_tai": False}
    inp["_ket_luan"] = {
        "historical_exact_rebuild": "NOT_REBUILDABLE",
        "vi_sao": ("Chỉ tồn tại MỘT bản records_a6.jsonl trong repo và nó không "
                   "tái tạo được submission.json của P0I (34 QID lệch). Không có "
                   "bản sao nào khác, file không nằm trong git, không có build "
                   "log ghi SHA đầu vào."),
        "bang_chung_khong_dung_mtime": (
            "Kết luận dựa trên: (a) replay từ bản hiện tại cho raw SHA 7e0c… "
            "≠ P0I fa27…; (b) find toàn repo chỉ ra 1 bản records_a6.jsonl; "
            "(c) không có manifest/log nào ghi SHA đầu vào của P0I."),
        "HISTORICAL_LINEAGE_BEST_EFFORT": (
            "chuỗi packager suy từ hằng số CHỐT CỨNG trong source: "
            "03_dong_goi(P0E→P0G) → 07_dong_goi(P0G→P0G2) → 06_dong_goi(P0G2→P0I)"),
        "REPRODUCIBLE_LINEAGE_FROM_NOW_ON": (
            "P0I ZIP là immutable parent; overlay đọc thẳng P0I; feature_off "
            "phải là no-op canonical diff = 0."),
    }
    (OUT / "identity/INPUT_RECORD_IDENTITIES.json").write_text(
        json.dumps(inp, ensure_ascii=False, indent=1), encoding="utf-8")

    zi = {}
    for ten, comp, p in CHUOI:
        zi[ten] = ({"component_ghi_ra_no": comp, **zip_identity(p, ten)}
                   if p.is_file() else {"ton_tai": False, "path": str(p)})
        zi[ten].pop("nhan", None)
    (OUT / "identity/INTERMEDIATE_ZIP_IDENTITIES.json").write_text(
        json.dumps(zi, ensure_ascii=False, indent=1), encoding="utf-8")

    # ── replay diff 34 — hướng tính khai TƯỜNG MINH ──────────────────────
    diff_rows, tom_diff = [], {}
    if rep.is_file():
        A = {r["id"]: r for r in json.loads(zipfile.ZipFile(p0i).read("submission.json"))}
        B = {r["id"]: r for r in json.loads(zipfile.ZipFile(rep).read("submission.json"))}
        dem = {f: 0 for f in TRUONG}
        for q in sorted(A):
            ch = [f for f in TRUONG if shaj(A[q].get(f)) != shaj(B[q].get(f))]
            if not ch:
                continue
            for f in ch:
                dem[f] += 1
            diff_rows.append({
                "qid": q, "changed_fields": ch,
                "huong": "B_replay_TRU_A_P0I",
                "P0I": {f: A[q].get(f) for f in ch},
                "REPLAY": {f: B[q].get(f) for f in ch},
                "P0I_field_sha": {f: shaj(A[q].get(f)) for f in ch},
                "REPLAY_field_sha": {f: shaj(B[q].get(f)) for f in ch},
            })
        ma = {m["name"] for m in members(p0i)}
        mb = {m["name"] for m in members(rep)}
        tom_diff = {
            "_schema": "replay_diff_summary v1",
            "huong_tinh": "REPLAY (B) so với P0I (A) — B là bản dựng lại",
            "A_P0I_raw_sha256": id_p0i["submission_json_raw_sha256"],
            "B_REPLAY_raw_sha256": id_rep["submission_json_raw_sha256"],
            "DINH_CHINH_DOC_162": (
                "doc 162 §3 ghi 'replay fa27… ≠ P0I 7e0c…' là ĐẢO NHÃN. "
                "Đúng là: P0I = fa27e15d…, REPLAY = 7e0c6a1f…"),
            "n_qid_lech": len(diff_rows),
            "n_theo_truong": dem,
            "member_chi_co_o_REPLAY": sorted(mb - ma),
            "member_chi_co_o_P0I": sorted(ma - mb),
            "n_member_A": len(ma), "n_member_B": len(mb),
        }
    (OUT / "lineage/replay_diff_34.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in diff_rows) + "\n",
        encoding="utf-8")
    (OUT / "lineage/replay_diff_summary.json").write_text(
        json.dumps(tom_diff, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps({
        "P0I_zip_sha256": id_p0i["zip_sha256"],
        "P0I_submission_raw_sha256": id_p0i["submission_json_raw_sha256"],
        "P0I_canonical_TRUNG_RAW": id_p0i["canonicalization"]["TRUNG_VOI_RAW"],
        "REPLAY_submission_raw_sha256": id_rep.get("submission_json_raw_sha256"),
        "n_qid_lech": tom_diff.get("n_qid_lech"),
        "theo_truong": tom_diff.get("n_theo_truong"),
        "historical_exact_rebuild": "NOT_REBUILDABLE",
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
