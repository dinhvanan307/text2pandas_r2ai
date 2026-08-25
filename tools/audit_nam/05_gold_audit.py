"""P0-e buoc 5 · dung GOLD AUDIT TRUNG LAP cho truc NAM.

CACH TACH HAI TRUC — day la diem then chot chong leakage
--------------------------------------------------------
Mot bang la gold khi no dong thoi:
  (a) chua DONG tra loi duoc chi tieu duoc hoi   — truc CHI TIEU
  (b) chua COT ung voi KY duoc hoi               — truc KY

Truc (a) KHONG phai thu dang danh gia, nen no duoc KE THUA tu phan xu P0-b/P0-d:
mot ung vien dat truc chi tieu neu no la mot bang gold cu, hoac nhan dong cua no
trung >= 0.5 (Jaccard) voi mot bang gold cu cua chinh cau do. Ke thua nhu vay
khong dua thong tin nam vao, vi nhan dong khong chua nam.

Truc (b) duoc PHAN XU LAI tu van ban OCR goc o buoc 3, khong dung `doc_year`
cung khong dung `periods`.

Vi the gold audit CO THE chua bang co `doc_year != nam_hoi` — va do chinh la
dieu gold cu khong bao gio co the co.
"""
from __future__ import annotations
import json, os, sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUD = ROOT / "data/dev/audit"
DB = Path(os.path.expanduser("~/fast/artifacts/retrieval/work.db"))
NGUONG = 0.5


def jac(a: str, b: str) -> float:
    A = {x for x in a.lower().split(" | ") if x}
    B = {x for x in b.lower().split(" | ") if x}
    return len(A & B) / len(A | B) if A | B else 0.0


def main() -> int:
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    ROW = {u: (r or "") for u, r in conn.execute("SELECT table_uid,row_terms FROM table_cards")}
    PXK = {r["id"]: r for r in (json.loads(l) for l in
           (AUD / "phan_xu_ky.jsonl").open(encoding="utf-8") if l.strip())}
    GOLD_CU = {r["id"]: r.get("gold_table_uids") or [] for r in (json.loads(l) for l in
               (ROOT / "data/dev/gold_v1.jsonl").open(encoding="utf-8") if l.strip())}

    ra = []
    for qid, r in sorted(PXK.items()):
        neo = [u for u in GOLD_CU.get(qid, []) if u in ROW]
        muc = {"id": qid, "tang": r["tang"], "question": r["question"],
               "nam_hoi": r["nam_hoi"], "ly_do_nam_hoi": r["ly_do_nam_hoi"],
               "neo_chi_tieu": neo, "gold": [], "uncertain": [], "loai": []}
        if not neo:
            muc["ghi_chu"] = ("UNCERTAIN toan cau — cau nay chua co gold cu nen "
                              "khong co neo cho truc CHI TIEU; khong phan xu.")
            ra.append(muc); continue
        for b in r["bang"]:
            u = b["table_uid"]
            dat_ct = u in neo or any(jac(ROW.get(u, ""), ROW.get(g, "")) >= NGUONG for g in neo)
            if not dat_ct:
                continue
            muc_bang = {"table_uid": u, "nam_cot": b.get("nam_cot"),
                        "bang_chung_ky": (b.get("bang_chung") or [])[:3],
                        "trung_nhan_dong_voi_neo": round(
                            max([1.0 if u in neo else 0.0]
                                + [jac(ROW.get(u, ""), ROW.get(g, "")) for g in neo]), 2)}
            if b["chua_ky"] is True:
                muc_bang["ly_do"] = "dat CA HAI truc: nhan dong khop neo chi tieu, cot co ky duoc hoi"
                muc["gold"].append(muc_bang)
            elif b["chua_ky"] is None:
                muc_bang["ly_do"] = ("UNCERTAIN — dat truc chi tieu nhung khong doc duoc "
                                     "ky tu van ban goc; khong doan")
                muc["uncertain"].append(muc_bang)
            else:
                muc_bang["ly_do"] = "dat truc chi tieu nhung cot KHONG co ky duoc hoi"
                muc["loai"].append(muc_bang)
        ra.append(muc)

    out = AUD / "gold_audit_nam.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in ra:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    co = [r for r in ra if r["neo_chi_tieu"]]
    print(f"{len(ra)} cau · phan xu duoc {len(co)} cau (co neo chi tieu)")
    print(f"gold      : {sum(len(r['gold']) for r in co)}")
    print(f"UNCERTAIN : {sum(len(r['uncertain']) for r in co)}")
    print(f"loai       : {sum(len(r['loai']) for r in co)}")
    print(f"-> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
