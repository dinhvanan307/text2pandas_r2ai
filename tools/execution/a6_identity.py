"""B4 · Cổng ĐỊNH DANH A6 — fail-fast TRƯỚC khi giải câu đầu tiên.

Không hard-code rải rác: kỳ vọng nằm ở `configs/execution/a6_identity.yaml`.
Sai hoặc THIẾU một trường ⇒ dừng với exit code khác 0, và log in ra
expected/actual của TỪNG trường, không chỉ nói "mismatch".
"""
from __future__ import annotations
import sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAU_HINH = ROOT / "configs/execution/a6_identity.yaml"


class A6IdentityError(RuntimeError):
    pass


def _doc_yaml(p: Path) -> dict:
    """YAML phẳng `khoa: gia tri` — đủ cho file này, không kéo thêm phụ thuộc."""
    d = {}
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, _, v = line.partition(":")
        d[k.strip()] = v.strip().strip('"').strip("'")
    return d


def kiem_dinh_danh(db: Path, cau_hinh: Path = CAU_HINH, in_log=print) -> dict:
    if not cau_hinh.is_file():
        raise A6IdentityError(f"THIEU cau hinh dinh danh: {cau_hinh}")
    ky_vong = _doc_yaml(cau_hinh)
    if not Path(db).is_file():
        raise A6IdentityError(f"THIEU DB: {db}")
    con = sqlite3.connect(f"file:{Path(db).resolve()}?mode=ro", uri=True)
    try:
        thuc = dict(con.execute("SELECT key, value FROM build_meta"))
    except sqlite3.OperationalError as e:
        raise A6IdentityError(f"DB khong co bang build_meta ({e}) — gan nhu chac chan tro nham DB")
    finally:
        con.close()

    truong = ["build_id", "corpus_id", "readiness_policy_version", "release_label", "status"]
    loi = []
    for k in truong:
        exp, act = ky_vong.get(k), thuc.get(k)
        dau = "OK " if (exp is not None and act == exp) else "SAI"
        in_log(f"  [{dau}] {k}\n        expected = {exp!r}\n        actual   = {act!r}")
        if exp is None:
            loi.append(f"{k}: cau hinh THIEU ky vong")
        elif act is None:
            loi.append(f"{k}: build_meta THIEU truong")
        elif act != exp:
            loi.append(f"{k}: expected {exp!r} != actual {act!r}")
    if loi:
        raise A6IdentityError("DINH DANH A6 KHONG KHOP:\n  - " + "\n  - ".join(loi))
    in_log("  => DINH DANH A6 KHOP")
    return thuc


if __name__ == "__main__":
    db = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "artifacts/retrieval/work.db"
    try:
        kiem_dinh_danh(db)
    except A6IdentityError as e:
        print(f"FAIL-FAST: {e}", file=sys.stderr)
        raise SystemExit(2)
    raise SystemExit(0)
