"""V+ bước 2 · Dựng gói hiệu chuẩn CAL1 — thiết kế HAI NHÁNH X / Z.

    X (neo)        k=3, cap=30   — giữ NGUYÊN XI `relevant_tables` của P0G2
    Z (hiệu chuẩn) k=1, cap=10   — cắt từ CÙNG danh sách xếp hạng

Chia tất định theo `sha256(str(qid))`, không dùng ngẫu nhiên.

Vì sao hai nhánh, không phải ba: nhánh Y cũ (`k=5, cap=10`) tồn tại để phân biệt
phép gộp F2 (A hay B). `docs/94` §5.2 đã đóng câu hỏi ấy bằng ba đường độc lập,
**không tốn lượt nộp**. Giữ Y lại là tiêu một nửa lượt nộp cho câu hỏi đã có
đáp án.

`answer` / `pandas_query` / `evidence` / mọi CSV: **giữ nguyên xi** từ P0G2 —
chênh lệch điểm phải quy được về đúng một biến là chính sách N.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFS = ROOT / "artifacts" / "runs" / "retrieval" / "vplus" / "refs_1012.json"
NEN = ROOT / "artifacts" / "submissions" / "legacy" / "submission_P0G2.zip"
RA = ROOT / "artifacts" / "submissions" / "legacy" / "submission_CAL1.zip"
SO = ROOT / "artifacts" / "runs" / "retrieval" / "vplus" / "cal1_nhanh.json"

X_K, X_CAP = 3, 30
Z_K, Z_CAP = 1, 10


def nhanh(qid) -> str:
    """X nếu byte đầu của sha256(qid) chẵn, Z nếu lẻ. Tất định, không seed ẩn."""
    h = hashlib.sha256(str(qid).encode()).digest()[0]
    return "X" if h % 2 == 0 else "Z"


def doc_of(ref: str) -> str:
    return ref.split("|")[0]


def main(argv):
    ap = argparse.ArgumentParser(prog="vplus_build")
    ap.add_argument("--out", default=str(RA))
    ap.add_argument("--che-do", choices=("chia_doi", "thuan_z"), default="chia_doi",
                    help="chia_doi = X/Z trong CÙNG gói (KHÔNG tách được nhánh, xem docs/95 §5); "
                         "thuan_z = TOÀN BỘ 1012 câu theo Z, ghép với quan sát P0E đã có làm nhánh X")
    a = ap.parse_args(argv)

    D = json.loads(REFS.read_text())
    zin = zipfile.ZipFile(NEN)
    sub = json.loads(zin.read("submission.json"))

    # Bất biến 1: nhánh X phải TÁI HIỆN chính xác gói nền (kiểm cả ở chế độ thuần_z,
    # vì nó chứng minh danh sách xếp hạng dựng lại tương đương bộ sinh ra P0E/P0G2).
    for r in sub:
        n = min(max(1, X_K * D[str(r["id"])]["o"]), X_CAP)
        if (r.get("relevant_tables") or []) != D[str(r["id"])]["refs"][:n]:
            raise SystemExit(f"q{r['id']}: nhánh X KHÔNG tái hiện được P0G2 — dừng")

    meta = {"X": [], "Z": []}
    doi_tables = doi_docs = 0
    for r in sub:
        qid = r["id"]
        nh = "Z" if a.che_do == "thuan_z" else nhanh(qid)
        meta[nh].append(qid)
        if nh == "X":
            continue                       # giữ nguyên xi
        n = min(max(1, Z_K * D[str(qid)]["o"]), Z_CAP)
        moi = D[str(qid)]["refs"][:n]
        cu = r.get("relevant_tables") or []
        if moi != cu:
            doi_tables += 1
        docs_moi = list(dict.fromkeys(doc_of(x) for x in moi))
        if docs_moi != (r.get("relevant_docs") or []):
            doi_docs += 1
        r["relevant_tables"] = moi
        r["relevant_docs"] = docs_moi

    # Bất biến 2: đáp án không đổi một câu nào.
    goc = {x["id"]: x for x in json.loads(zin.read("submission.json"))}
    for r in sub:
        g = goc[r["id"]]
        for f in ("answer", "pandas_query", "evidence", "question"):
            if json.dumps(r.get(f), sort_keys=True) != json.dumps(g.get(f), sort_keys=True):
                raise SystemExit(f"q{r['id']}: trường {f} ĐÃ ĐỔI — dừng")

    out = Path(a.out)
    # Thư mục mount không cho `unlink`; mở chế độ "w" đã cắt cụt tệp cũ.
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zo:
        for it in zin.infolist():
            if it.filename == "submission.json":
                continue
            zo.writestr(it, zin.read(it.filename))
        zo.writestr("submission.json", json.dumps(sub, ensure_ascii=False))

    nt = {k: [len(x.get("relevant_tables") or []) for x in sub if x["id"] in set(meta[k])]
          for k in ("X", "Z")}
    SO.parent.mkdir(parents=True, exist_ok=True)
    SO.write_text(json.dumps({
        "thiet_ke": a.che_do, "X": {"k": X_K, "cap": X_CAP, "qids": sorted(meta["X"])},
        "Z": {"k": Z_K, "cap": Z_CAP, "qids": sorted(meta["Z"])},
        "N_tb": {k: (sum(nt[k]) / len(nt[k]) if nt[k] else 0.0) for k in nt},
        "tong_bang": {k: sum(nt[k]) for k in nt}}, ensure_ascii=False))

    print(f"CAL1 dựng xong · {out.name}  ({out.stat().st_size} bytes)")
    for k, kk, cap, ghi in (("X", X_K, X_CAP, "GIỮ NGUYÊN XI"),
                            ("Z", Z_K, Z_CAP, f"đổi {doi_tables} câu tables, {doi_docs} câu docs")):
        if not nt[k]:
            print(f"  nhánh {k} (k={kk}, cap={cap}) : 0 câu")
            continue
        print(f"  nhánh {k} (k={kk}, cap={cap}) : {len(meta[k])} câu · "
              f"N̄={sum(nt[k])/len(nt[k]):.3f} · tổng {sum(nt[k])} bảng  [{ghi}]")
    print(f"  N̄ toàn gói = {(sum(nt['X'])+sum(nt['Z']))/1012:.3f}  (P0G2 = 7.669)")
    print(f"  sổ nhánh: {SO.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
