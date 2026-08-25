"""P0-e buoc 3 · phan xu KY tu van ban goc, trung lap voi ca hai dac trung.

QUY TAC (viet ra truoc khi do, khong sua sau khi thay ket qua)
--------------------------------------------------------------
Moi COT cua mot bang tro toi mot NAM. Quy uoc gop:
  * so lieu phat sinh trong nam Y            -> Y
  * so du cuoi nam Y  (31/12/Y)              -> Y
  * so du dau nam Y   (01/01/Y = 31/12/Y-1)  -> Y-1
Cau hoi cung duoc quy ve mot nam theo dung quy uoc do:
  "trong nam Y" / "nam tai chinh Y"          -> Y
  "cuoi nam Y" / "den ngay 31/12/Y"          -> Y
  "dau nam Y"                                -> Y-1

`chua_ky(bang, Y)` = Y thuoc tap nam ma cac cot cua bang tro toi.

NGUON BANG CHUNG duoc phep dung:
  * dong tieu de cua bang trong van ban OCR goc
  * nhan dong, nhung CHI khi chua ngay thang tuong minh (bang bien dong von)
  * nam tai chinh cua BAO CAO, lay tu TEN TEP, va CHI de giai cac nhan tuong
    doi ("Nam nay", "So dau nam"). Day khong phai vi tu dang duoc danh gia:
    vi tu ay la `doc_year == nam_hoi`, con o day nam tep chi la mot tham so
    giai ma — va no CO THE cho ket qua nam khac nam hoi, tuc nguoc dau voi
    vi tu ay.

KHONG duoc dung: `table_cards.doc_year`, `table_cards.periods`, `sources`,
rank, score, nhan gold cu.
"""
from __future__ import annotations
import json, re, sys, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
AUD  = ROOT / "data/dev/audit"


def fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower()


# A6 in ngay thang bang ca ba dau ngan: "31/12/2021", "31.12.2021", "31-12-2021".
# Bien phai KHONG duoc dung `\b`: OCR dinh lien don vi vao nam ("2021VND"), va
# `\b` sau chu so bi chan boi `V`. Day la mot loi that da bi bat o buoc kiem tay.
_NGAY_SO  = re.compile(r"(?<![0-9])(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*"
                       r"((?:19|20)\d{2})(?![0-9])")
_NGAY_CHU = re.compile(r"ngay\s*(\d{1,2})\s*thang\s*(\d{1,2})\s*nam\s*"
                       r"((?:19|20)\d{2})(?![0-9])")
_NAM      = re.compile(r"(?<![0-9])((?:19|20)\d{2})(?![0-9])")
# Nam nam trong mot TRICH DAN HANH CHINH khong phai ky bao cao: so hieu bieu
# mau, so giay phep kinh doanh, so quyet dinh. ABB/2020 `448` va MML/2023 `950`
# la hai ca that bi tinh nham truoc khi co bo loc nay.
_BIEU_MAU = re.compile(r"mau (so )?b\s*\d|ban hanh theo|thong tu so|qd so|"
                       r"quyet dinh so|giay phep|dang ky kinh doanh|"
                       r"giay chung nhan")
# Nhan dong cua bang bien dong doi khi viet "Ngay 31 thang 12 nam 2018" khong co
# chu "tai" (BVH/2019 `1039`, `1056`) — phai nhan ca dang tran.
_DONG_KY  = re.compile(r"so du|tai ngay|ngay\s*\d|dau nam|cuoi nam|dau ky|"
                       r"cuoi ky|nam ket thuc|so cuoi|so dau")
# "trong nam" / "trong ky" o TIEU DE COT chi ky phat sinh cua chinh bao cao:
# DNH/2025 `919` co cot "So phai nop trong nam" — do la so phat sinh 2025 va la
# ve tra loi cua q809. Thieu cum nay thi bang bi loai oan.
# Dung REGEX chu khong dung danh sach chuoi con: bang BIEN DONG viet "So du dau
# nam" / "So du cuoi nam", va "so dau nam" KHONG phai chuoi con cua "so du dau
# nam". Sai nay lam 6/21 ket luan False trong mau kiem tay bi sai — no giet ca
# lop bang bien dong TSCD, bien dong thue, bien dong du phong.
# `\s*` chu khong phai dau cach cung: OCR dinh chu vao nhau — MBB/2019 `1523`
# in "So dudau namtrieu dong". Mot dau cach cung o day lam mat ca cot dau ky.
_HIEN_RE  = re.compile(r"nam\s*nay|ky\s*nay|so\s*(du)?\s*cuoi\s*(nam|ky)|"
                       r"cuoi\s*ky\s*nay|nam\s*hien\s*tai|trong\s*nam|trong\s*ky")
_TRUOC_RE = re.compile(r"nam\s*truoc|ky\s*truoc|so\s*(du)?\s*dau\s*(nam|ky)|"
                       r"dau\s*ky")


def _tu_ngay(t: str) -> list[tuple[int, str]]:
    """Ngay thang tuong minh. 01/01/Y la so du DAU nam -> tro toi Y-1."""
    ra = []
    for d, m, y in _NGAY_SO.findall(t) + [(a, b, c) for a, b, c in _NGAY_CHU.findall(t)]:
        d, m, y = int(d), int(m), int(y)
        ra.append((y - 1 if (d == 1 and m == 1) else y,
                   f"ngay {d}/{m}/{y}" + (" = so du dau nam" if d == 1 and m == 1 else "")))
    return ra


def nam_cua_cot(tieu_de: list[str], dong2: list[str], nhan: list[str],
                nam_tep: int) -> tuple[set[int], list[str]]:
    """Tap nam ma cac cot tro toi, kem BANG CHUNG tung nam."""
    nam: set[int] = set()
    bc: list[str] = []

    def nhan_vao(y: int, ly: str, nguon: str) -> None:
        if y not in nam:
            nam.add(y); bc.append(f"{y} ← {nguon}: {ly}")

    # Doc CA HAI dong tieu de roi moi ket luan. Ban dau toi dung lai ngay khi
    # dong 1 cho mot nam — sai: VPI/2025 `1906` co "Nam nay" o dong 1 va
    # "Nam truoc" o dong 2, nen bang bi ket luan chi tro toi 2025 va bi loai oan
    # khoi cau hoi 2024. Kiem tay bat duoc; xem docs/88 §4.
    for nguon, khoi in (("tieu de", tieu_de), ("dong 2", dong2)):
        t = fold(" | ".join(khoi))
        if _BIEU_MAU.search(t):        # "Mau B09-DN ban hanh theo Thong tu .../2014"
            continue                   # nam trong trich dan bieu mau khong phai ky
        for y, ly in _tu_ngay(t):
            nhan_vao(y, ly, nguon)
        if not _tu_ngay(t):
            for y in _NAM.findall(t):
                nhan_vao(int(y), f"nam roi {y} trong tieu de", nguon)
        m = _HIEN_RE.search(t)
        if m:
            nhan_vao(nam_tep, f"{m.group(0)!r} = nam tai chinh cua bao cao", nguon)
        m = _TRUOC_RE.search(t)
        if m:
            nhan_vao(nam_tep - 1, f"{m.group(0)!r} = nam lien truoc", nguon)

    # Bang BIEN DONG (bien dong von, bien dong du phong, bien dong TSCD) dat ky o
    # NHAN DONG chu khong o tieu de: cot la loai quy / loai du phong, con dong la
    # "So du tai ngay 1/1/2019 ... So du tai ngay 31/12/2019".
    #
    # Ban dau toi chi quet nhan dong KHI tieu de khong cho gi. Sai: o CTG/2019
    # `3df582ade86783c8` dong dau tien lot vao `dong_dau_2` va chi cho "1/1/2019",
    # nen bang bi ket luan la chi tro toi 2018 va bi loai oan. Quet nhan dong
    # LUON, nhung chi lay NGAY THANG TUONG MINH — khong lay nam roi, de "trai
    # phieu dao han 2025" khong bi tinh la mot ky cua bang.
    for x in nhan[:60]:
        t = fold(x)
        # Chi nhan dong co DANG SO DU / KY moi duoc coi la bang chung ky. Neu lay
        # moi ngay thang trong nhan dong thi "giay phep kinh doanh so ... nam
        # 2010" (ABB/2023) hay "Thong tu 202/2014" (MML/2023) se bi tinh la ky.
        # Bang bo phan hai khoi ("Nam nay" o dau bang, "Nam truoc" o giua bang):
        # DPM/2025 `1229` la mot ca that. Nhan tuong doi cung phai duoc doc o
        # nhan dong, nhung chi khi nhan NGAN — de "chi phi tra truoc nam truoc"
        # khong bi tinh la mot khoi ky rieng.
        if len(t) <= 30:
            m = _HIEN_RE.search(t)
            if m:
                nhan_vao(nam_tep, f"{m.group(0)!r} o nhan dong", "nhan dong")
            m = _TRUOC_RE.search(t)
            if m:
                nhan_vao(nam_tep - 1, f"{m.group(0)!r} o nhan dong", "nhan dong")
        if not _DONG_KY.search(t):
            continue
        for y, ly in _tu_ngay(t):
            nhan_vao(y, ly, "nhan dong")
    return nam, bc


# ── ky duoc hoi ────────────────────────────────────────────────────────────────
_DAU  = re.compile(r"dau nam\s*((?:19|20)\d{2})")
_CUOI = re.compile(r"cuoi nam\s*((?:19|20)\d{2})")


_GIAI_DOAN = re.compile(r"(?:giai doan|tu nam|qua cac nam|trong giai doan)\s*"
                        r"((?:19|20)\d{2})\s*[-–—]\s*((?:19|20)\d{2})")


def nam_duoc_hoi(question: str, years: list[int]) -> tuple[list[int], str]:
    """Quy nam trong cau hoi ve dung quy uoc tren. Ghi lai ly do.

    "giai doan 2018-2024" duoc NO RA thanh 2018..2024. `parse_intent` khong no
    (RC-4, xem docs/83), nhung day la mot khiem khuyet cua BEN CAU HOI, doc lap
    voi hai dac trung dang danh gia — de nguyen thi cau q439 bi cham oan.
    """
    t = fold(question)
    gd = _GIAI_DOAN.search(t)
    if gd:
        a, b = int(gd.group(1)), int(gd.group(2))
        if 0 < b - a <= 15:
            return list(range(a, b + 1)), f"'giai doan {a}-{b}' -> no ra {b-a+1} nam"
    dau = {int(y) for y in _DAU.findall(t)}
    if dau:
        con = sorted({y - 1 for y in dau} | {y for y in years if y not in dau})
        return con, f"'dau nam {sorted(dau)}' -> so du cuoi nam lien truoc"
    if _CUOI.search(t) or _NGAY_SO.search(t) or "den ngay" in t:
        return sorted(years), "so du cuoi ky -> giu nguyen nam"
    return sorted(years), "phat sinh trong ky -> giu nguyen nam"


def main() -> int:
    mau = {r["id"]: r for r in (json.loads(l) for l in
           (ROOT / "data/dev/gold_tay_sample_v2.jsonl").open(encoding="utf-8") if l.strip())}
    pool = {r["id"]: r for r in (json.loads(l) for l in
            (ROOT / "data/dev/gold_tay_pool_v5.jsonl").open(encoding="utf-8") if l.strip())}
    tho = {r["table_uid"]: r for r in (json.loads(l) for l in
           (AUD / "bang_tho.jsonl").open(encoding="utf-8") if l.strip())}
    ids = json.loads((AUD / "mau_audit_nam.json").read_text())

    ra = []
    for tang, qs in sorted(ids.items()):
        for qid in qs:
            p, m = pool[qid], mau[qid]
            nam_hoi, ly_do = nam_duoc_hoi(m["question"], p["years"])
            muc = {"id": qid, "tang": tang, "question": m["question"],
                   "nam_hoi": nam_hoi, "ly_do_nam_hoi": ly_do, "bang": []}
            for c in p["candidates"]:
                u = c["table_uid"]; t = tho.get(u)
                if t is None:
                    muc["bang"].append({"table_uid": u, "chua_ky": None,
                                        "ghi_chu": "UNCERTAIN — khong doc duoc bang trong van ban goc"})
                    continue
                nam_tep = int(t["doc_id"].split("_")[-2])
                nam, bc = nam_cua_cot(t["tieu_de_cot"], t["dong_dau_2"],
                                      t["nhan_dong"], nam_tep)
                # BAT DOI XUNG CO CHU DINH: bang chung o NHAN DONG du de ket
                # luan CO mot ky, nhung khong du de ket luan KHONG co ky khac —
                # bang bo phan BSR/2021 `1752` chi lo mot moc 31/12/2020 trong
                # nhan dong nhung so lieu doanh thu la cua 2021. Khi moi bang
                # chung deu den tu nhan dong ma khong trung ky hoi, ghi
                # UNCERTAIN chu khong ghi False.
                co = bool(set(nam_hoi) & nam)
                chi_nhan_dong = bool(bc) and all("← nhan dong" in x for x in bc)
                muc["bang"].append({
                    "table_uid": u,
                    "nam_cot": sorted(nam),
                    "chua_ky": (None if not nam else
                                (True if co else (None if chi_nhan_dong else False))),
                    "bang_chung": bc[:6],
                    "tieu_de_cot": t["tieu_de_cot"][:8],
                    "ghi_chu": "" if nam else "UNCERTAIN — bang khong lo ky nao",
                })
            ra.append(muc)

    out = AUD / "phan_xu_ky.jsonl"
    with out.open("w", encoding="utf-8") as f:
        for r in ra:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    n = sum(len(r["bang"]) for r in ra)
    kd = sum(1 for r in ra for b in r["bang"] if b["chua_ky"] is None)
    co = sum(1 for r in ra for b in r["bang"] if b["chua_ky"] is True)
    print(f"{len(ra)} cau · {n} bang · chua ky: {co} · khong ky/UNCERTAIN: {kd}")
    print(f"-> {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
