"""A0 bước 2 · phân xử GIÁ TRỊ Ô cho gold đáp án, KHÔNG qua BM25.

Ý TƯỞNG TRUNG TÂM — ĐỒNG THUẬN GIÁ TRỊ, KHÔNG PHẢI CHỌN BẢNG
------------------------------------------------------------
Gold đáp án không cần biết ô nằm ở BẢNG nào. Nó chỉ cần biết CON SỐ. Vì vậy
thủ tục ở đây liệt kê **mọi** ô khớp ràng buộc khai báo được của câu hỏi rồi
hỏi: *các ô còn lại có đồng thuận một giá trị không?* Đồng thuận ⇒ giá trị được
xác định mà không phải chọn bảng nào cả.

Điều này quan trọng về mặt PHƯƠNG PHÁP, không chỉ tiện tay: pipeline đang được
đo hỏng ở khâu **xếp hạng bảng** (`docs/94`: S1 mất 0 bảng, S2 mất 55,6%).
Một gold quyết định bằng *đồng thuận giá trị trên toàn kho* không dùng thứ hạng
nào, nên nó không thừa hưởng lỗi của thứ hạng.

CHUỖI LỌC — mỗi bước KHAI BÁO, không bước nào là heuristic ẩn
------------------------------------------------------------
| # | lọc | tín hiệu | vì sao |
|---|---|---|---|
| 1 | nhãn dòng là chuỗi con chuẩn hoá của câu hỏi (≥10 ký tự) | `row_label` | ràng buộc mạnh nhất mà câu hỏi phát biểu tường minh |
| 2 | `documents.basis` = basis của intent | `basis` | "công ty mẹ" ⇒ separate; mặc định hợp nhất (`SCOPE_DEFAULT`) |
| 3 | `period_role = current` | `period_role` | loại cột SO SÁNH và cột ĐẦU KỲ — nguồn lệch giá trị lớn nhất |
| 4 | `doc_year ∈ years` | `doc_year` | ưu tiên báo cáo CHÍNH của năm, không phải cột so sánh ở báo cáo năm sau |
| 5 | `is_restated = 0` | `is_restated` | số trình bày lại là một fact khác |
| 6 | `confidence ≠ low` | `parse_confidence` | ô parse kém là nhiễu đo, không phải bất đồng thật |
| 7 | `row_path_text` NGẮN NHẤT | `row_path` | ô ở gốc bảng, không phải ô trong thuyết minh lồng sâu |

**Lọc mềm (`_loc`)**: bước nào làm rỗng tập thì BỎ QUA bước đó. Fail-closed đặt
ở kết luận (`UNCERTAIN`), không đặt ở từng bước lọc — đặt sai chỗ thì mất câu
mà không biết mất vì bước nào.

CHỐNG VÒNG TRÒN — khai báo thẳng, không giấu
--------------------------------------------
`signals_used` ghi đủ tín hiệu đã dùng cho TỪNG câu; `leakage_flag` bật khi
tín hiệu ấy trùng tín hiệu mà thí nghiệm sau định kiểm. Cụ thể `row_label`
trùng với thứ BM25 của S2 dùng — nhưng KHÁC CƠ CHẾ: ở đây là khớp chuỗi con
CHÍNH XÁC trên toàn bộ 2,63 triệu ô, ở S2 là xếp hạng BM25 trên top-N thẻ bảng.
Ai dùng gold này để chứng minh một feature nhãn-dòng thì phải lọc bỏ tập
`row_label ∈ signals_used` trước, y như `docs/94` đã làm cho gold bảng.

**Thiên lệch sống sót:** tập giải được KHÔNG phải mẫu ngẫu nhiên của 1.012 câu
— câu có nhãn mơ hồ vừa khó cho thủ tục này vừa khó cho pipeline. `docs/94` đo
được thiên lệch ấy trên gold BẢNG là −0,0124 F2. Bắt buộc đo lại trên gold ĐÁP
ÁN trước khi dùng nó làm mốc tuyệt đối; dùng làm mốc TƯƠNG ĐỐI (A/B) thì an toàn.

Chạy:
    python tools/gold_dap_an/02_phan_xu_o.py
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from retrieval.alias_store import load_aliases           # noqa: E402
from retrieval.question_intent import parse_intent       # noqa: E402

DB = ROOT / "artifacts/retrieval/work.db"
MAU = ROOT / "data/dev/gold_dap_an/mau_v1.jsonl"
RA_GOLD = ROOT / "data/dev/gold_dap_an/gold_dap_an_v1.jsonl"
RA_WS = ROOT / "data/dev/gold_dap_an/worksheet_uncertain_v1.jsonl"

MIN_NHAN = 10          # nhãn ngắn hơn thì khớp chuỗi con là ngẫu nhiên
COT = ("o.metric_label_clean,o.value_decimal_text,o.scale_exponent,o.directory_doc_id,"
       "o.doc_year,d.basis,o.col_path_text,o.confidence,o.row_path_text,o.period_role,"
       "o.is_restated,o.evidence_ref,o.period_end,o.value_kind,o.table_uid")
KHOA = [c.split(".")[1] for c in COT.split(",")]

# ── Ô ĐƠN vs Ô THEO SLOT ────────────────────────────────────────────────────
# BUG ĐÃ BẮT (19/08/2026, chính bản đầu của tệp này): bản đầu gộp MỌI năm vào
# một truy vấn rồi đòi "đồng thuận một giá trị". Với `difference` hay
# `average`, đồng thuận-một-giá-trị nghĩa là hai kỳ RA CÙNG MỘT SỐ — tức đúng
# cái ca suy biến, và nó được đếm là OK. Log in ra `difference 60.0%` trông rất
# thuyết phục. Bài học lặp lại của `docs/96` §3: log chạy trơn không phải bằng
# chứng chạy đúng.
#
# Sửa: phân xử theo **SLOT** = (ticker, year). Mỗi slot đồng thuận độc lập, rồi
# mới áp công thức lên tập slot.
#
# Lớp nào áp được công thức TỪ LỚP + MỘT cụm chỉ tiêu:
#   lookup                      1 slot                → chính giá trị
#   average · sum · max_min     N slot, cùng chỉ tiêu  → gộp
#   argmax_year                 N slot                → trả NĂM, không trả tiền
#   difference · %_change       đúng 2 slot           → theo thứ tự năm tăng dần
# Lớp KHÔNG áp được (→ worksheet):
#   ratio       cần HAI chỉ tiêu khác nhau (tử/mẫu) — một cụm không đủ
#   multi_table cần nhiều chỉ tiêu ở nhiều bảng
#   count       cần một vị từ đếm, không phải phép số học trên ô
LOP_TU_DONG = {"lookup", "difference", "percentage_change",
               "average", "max_min", "argmax_year", "sum"}
LOP_WORKSHEET = {"ratio", "multi_table", "count"}

# Hệ số quy đổi: đáp án phải theo ĐƠN VỊ CÂU HỎI HỎI, không theo đơn vị bảng.
QUY_DOI = {"dong": 1, "nghin": 10 ** 3, "trieu": 10 ** 6, "ty": 10 ** 9,
           "tram_ty": 10 ** 11, "nghin_ty": 10 ** 12}


def chuan(s: str | None) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def _loc(h: list[dict], f, ten: str, dung: list[str]) -> list[dict]:
    """Lọc MỀM: rỗng thì giữ nguyên và không ghi tín hiệu."""
    g = [x for x in h if f(x)]
    if g and len(g) < len(h):
        dung.append(ten)
    return g or h


def gia_tri(x: dict) -> int:
    return int(x["value_decimal_text"]) * 10 ** (x["scale_exponent"] or 0)


def phan_xu_slot(conn, ticker: str, year: int, qn: str, basis: str | None):
    """Phân xử MỘT slot = (ticker, year). Trả (giá trị | None, ly_do, ô, tín hiệu).

    Đây là đơn vị nguyên tử của gold đáp án. Mọi phép toán ở tầng trên chỉ được
    dùng slot đã đồng thuận; một slot UNCERTAIN làm cả câu UNCERTAIN.
    """
    rows = [dict(zip(KHOA, r)) for r in conn.execute(
        f"select {COT} from observations o "
        f"join documents d on d.directory_doc_id = o.directory_doc_id "
        f"where o.ticker = ? and o.period_end like ?", (ticker, f"{year}%"))]

    dung: list[str] = ["entity", "period_end"]
    h = [x for x in rows
         if len(chuan(x["metric_label_clean"])) >= MIN_NHAN
         and chuan(x["metric_label_clean"]) in qn]
    if not h:
        return None, "khong_o_nao_khop_nhan_dong", [], dung
    dung.append("row_label")

    if basis:
        h = _loc(h, lambda x: x["basis"] == basis, "basis", dung)
    h = _loc(h, lambda x: x["period_role"] == "current", "period_role", dung)
    h = _loc(h, lambda x: x["doc_year"] == year, "doc_year", dung)
    h = _loc(h, lambda x: not x["is_restated"], "is_restated", dung)
    h = _loc(h, lambda x: x["confidence"] != "low", "parse_confidence", dung)
    ngan = min(len(x["row_path_text"] or "") for x in h)
    h = _loc(h, lambda x: len(x["row_path_text"] or "") <= ngan, "row_path", dung)

    vals = sorted({gia_tri(x) for x in h})
    if len(vals) != 1:
        return None, f"lech_{len(vals)}_gia_tri", h, dung
    return vals[0], None, h, dung


def ap_cong_thuc(lop: str, slots: list[tuple[str, int, int]]):
    """`slots` = [(ticker, year, value)] đã sắp theo năm tăng dần.

    Trả (đáp án THÔ theo VND | năm, công thức, ly_do). Đáp án `argmax_year` là
    một NĂM — `docs/97` đo được 53 câu loại này đang bị trả về số tiền.
    """
    vs = [v for _, _, v in slots]
    ys = [y for _, y, _ in slots]
    n = len(slots)
    if lop == "lookup":
        return (vs[0], "A", None) if n == 1 else (None, None, f"lookup_can_1_slot_co_{n}")
    if lop in ("difference", "percentage_change"):
        if n != 2:
            return None, None, f"{lop}_can_2_slot_co_{n}"
        a, b = vs[0], vs[1]                       # a = kỳ SỚM, b = kỳ MUỘN
        if lop == "difference":
            return b - a, "B − A (A=kỳ sớm)", None
        if a == 0:
            return None, None, "percentage_change_mau_bang_0"
        return (b - a) / abs(a) * 100, "(B − A)/|A| × 100", None
    if lop == "sum":
        return sum(vs), "Σ A_i", None
    if lop == "average":
        return sum(vs) / n, "Σ A_i / n", None
    if lop == "max_min":
        return None, None, "max_min_can_biet_hoi_MAX_hay_MIN"
    if lop == "argmax_year":
        if n < 2:
            return None, None, f"argmax_year_can_>=2_slot_co_{n}"
        return float(ys[vs.index(max(vs))]), "argmax_i A_i -> năm", None
    return None, None, f"lop_{lop}_khong_co_cong_thuc"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(DB))
    a = ap.parse_args(argv)

    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-200000")
    alias = load_aliases(brands=True)
    mau = [json.loads(l) for l in MAU.open(encoding="utf-8") if l.strip()]
    meta_mau, mau = mau[0], mau[1:]

    gold, ws = [], []
    dem = collections.Counter()
    theo_lop: dict[str, collections.Counter] = collections.defaultdict(collections.Counter)

    for r in mau:
        it = parse_intent(r["question"], alias)
        qn = chuan(r["question"])
        dem["tong"] += 1
        theo_lop[r["lop"]]["n"] += 1

        ban = dict(r)
        ban.update({"tickers": sorted(it.targets), "years": list(it.years),
                    "basis": it.basis, "mode": it.mode})

        # ── giai đoạn 1 · phân xử từng SLOT ────────────────────────────────
        slots, prov, dung_all, hong = [], [], set(), []
        if r["lop"] in LOP_WORKSHEET:
            hong.append(f"lop_{r['lop']}_can_phan_xu_tay")
        elif not it.targets or not it.years:
            hong.append("khong_phan_giai_duoc_thuc_the_hoac_ky")
        else:
            for tk in sorted(it.targets):
                for y in sorted(it.years):
                    v, ld, h, dung = phan_xu_slot(conn, tk, y, qn, it.basis)
                    dung_all |= set(dung)
                    if v is None:
                        hong.append(f"{tk}/{y}:{ld}")
                        continue
                    slots.append((tk, y, v))
                    prov.append({"slot": f"{tk}/{y}", "gia_tri": v,
                                 "n_o_dong_thuan": len(h),
                                 "doc": h[0]["directory_doc_id"],
                                 "ref": h[0]["evidence_ref"],
                                 "table_uid": h[0]["table_uid"],
                                 "nhan": h[0]["metric_label_clean"],
                                 "row_path": h[0]["row_path_text"],
                                 "col": h[0]["col_path_text"],
                                 "scale_exponent": h[0]["scale_exponent"],
                                 "raw": h[0]["value_decimal_text"]})

        ban["signals_used"] = sorted(dung_all)
        ban["leakage_flag"] = "row_label_exact" if "row_label" in dung_all else "none"

        # ── giai đoạn 2 · áp công thức + quy đổi đơn vị ────────────────────
        dap_an = cong_thuc = None
        if not hong:
            slots.sort(key=lambda s: (s[1], s[0]))
            dap_an, cong_thuc, ld = ap_cong_thuc(r["lop"], slots)
            if ld:
                hong.append(ld)

        if not hong:
            he_so = QUY_DOI.get(r["don_vi_hoi"])
            if r["lop"] == "argmax_year":
                pass                                   # đáp án là NĂM, không quy đổi
            elif r["lop"] == "percentage_change" or r["don_vi_hoi"] == "%":
                if r["lop"] != "percentage_change":
                    hong.append("don_vi_%_nhung_cong_thuc_khong_sinh_%")
            elif he_so:
                dap_an = dap_an / he_so
            else:
                hong.append(f"don_vi_hoi_{r['don_vi_hoi']}_chua_co_quy_doi")

        if hong:
            dem["UNCERTAIN"] += 1
            theo_lop[r["lop"]]["uncertain"] += 1
            ban.update({"trang_thai": "UNCERTAIN", "ly_do": hong,
                        "slot_giai_duoc": prov})
            ws.append(ban)
        else:
            dem["OK"] += 1
            theo_lop[r["lop"]]["ok"] += 1
            ban.update({"trang_thai": "OK", "dap_an_gold": dap_an,
                        "cong_thuc": cong_thuc, "don_vi_dap_an": r["don_vi_hoi"],
                        "n_slot": len(slots), "provenance": prov})
            gold.append(ban)

    meta = {"_meta": True, "nguon_mau": meta_mau, "db": a.db,
            "min_nhan": MIN_NHAN, "lop_tu_dong": sorted(LOP_TU_DONG),
            "lenh": "python tools/gold_dap_an/02_phan_xu_o.py",
            "tao_luc": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    for p, rows in ((RA_GOLD, gold), (RA_WS, ws)):
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", encoding="utf-8") as f:
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")
            for x in rows:
                f.write(json.dumps(x, ensure_ascii=False) + "\n")

    print(f"{'lớp':20}{'n':>4}{'OK':>5}{'UNC':>5}{'phủ':>8}")
    for lop in sorted(theo_lop, key=lambda k: -theo_lop[k]["n"]):
        c = theo_lop[lop]
        print(f"{lop:20}{c['n']:>4}{c['ok']:>5}{c['uncertain']:>5}{100*c['ok']/c['n']:>7.1f}%")
    print(f"{'TỔNG':20}{dem['tong']:>4}{dem['OK']:>5}{dem['UNCERTAIN']:>5}"
          f"{100*dem['OK']/dem['tong']:>7.1f}%")
    print(f"-> {RA_GOLD.relative_to(ROOT)} · {RA_WS.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
