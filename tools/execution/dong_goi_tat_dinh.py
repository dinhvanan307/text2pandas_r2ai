"""B2 · Đóng gói TẤT ĐỊNH THẬT — hai lần build phải cho cùng SHA-256 TOÀN FILE.

Bản cũ chỉ tất định về NỘI DUNG (submission.json + CRC member). Timestamp,
permission và thứ tự member vẫn làm binary khác nhau. Ở đây cố định cả năm thứ:

    thứ tự member · timestamp · compression method/level · external_attr · JSON

Và: KHÔNG BAO GIỜ ghi đè file đã tồn tại (đây chính là lỗi đã làm mất exact
artifact của C1 — `10_bao_cao_h0.py` gọi lại bộ đóng gói ghi thẳng lên
`submission_P0I.zip`).
"""
from __future__ import annotations
import hashlib, json, zipfile
from pathlib import Path

NGAY_CO_DINH = (1980, 1, 1, 0, 0, 0)     # mốc ZIP tối thiểu — không phụ thuộc lúc chạy
QUYEN = (0o100644 << 16)                 # -rw-r--r--


def json_chuan(obj) -> bytes:
    return json.dumps(obj, ensure_ascii=False, indent=1, sort_keys=False).encode("utf-8")


def ghi_zip(ra: Path, thanh_vien: dict[str, bytes], *, force: bool = False) -> dict:
    if ra.exists() and not force:
        raise SystemExit(f"TU CHOI GHI DE: {ra} da ton tai. Dung duong dan moi hoac --force.")
    ra.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(ra, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        for ten in sorted(thanh_vien):                    # thứ tự cố định
            zi = zipfile.ZipInfo(ten, date_time=NGAY_CO_DINH)
            zi.compress_type = zipfile.ZIP_DEFLATED
            zi.external_attr = QUYEN
            zi.create_system = 3                          # Unix, cố định
            z.writestr(zi, thanh_vien[ten])
    return dau_van(ra)


def dau_van(p: Path) -> dict:
    z = zipfile.ZipFile(p)
    ten = sorted(z.namelist())
    return {
        "path": p.name,
        "bytes": p.stat().st_size,
        "zip_sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "n_members": len(ten),
        "submission_json_sha256": hashlib.sha256(z.read("submission.json")).hexdigest(),
        "member_sha256": {t: hashlib.sha256(z.read(t)).hexdigest() for t in ten},
    }
