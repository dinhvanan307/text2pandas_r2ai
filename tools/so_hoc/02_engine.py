"""P0-g bước 2 · ENGINE SỐ HỌC.

HỢP ĐỒNG CỦA MODULE NÀY
-----------------------
Vào : câu hỏi + danh sách bảng đã truy hồi (locator) + hàm đọc HTML thô.
Ra  : `KetQua(answer, pandas_query, evidence, operands, trang_thai, ghi_chu)`.

BẤT BIẾN (không được vi phạm, có test khoá)
  * `answer == eval(pandas_query)` với các CSV trong `evidence`
  * mọi toán hạng đều CÓ NGUỒN: bảng nào, dòng nào, cột nào, kỳ nào, đơn vị nào
  * chuẩn hoá đơn vị về VND TRƯỚC khi tính, đổi sang đơn vị câu hỏi SAU khi tính
  * thiếu toán hạng, hoặc không xác định được kỳ  ->  `UNCERTAIN`, KHÔNG đoán
  * không lấy cột `Mã số` / `Thuyết minh` / `TT` / `STT`
  * kỳ lấy từ CỘT, không lấy từ `doc_year` (docs/88 đã chứng minh doc_year sai
    21,3% và làm F2 giảm khi dùng làm khoá)
"""
from __future__ import annotations

import re
import sys
import unicodedata
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools/answer_v2"))

# Import NẶNG nằm trong `nap_bang`, không ở tầng module: mọi hàm số học phải
# kiểm được mà không cần cả `text2pandas`. Bài học từ `06_loc_cot_phi_gia_tri`.
import importlib
_loc = importlib.import_module("06_loc_cot_phi_gia_tri")
la_cot_phi_gia_tri = _loc.la_cot_phi_gia_tri

MU = {"dong": 0, "nghin": 3, "trieu": 6, "ty": 9, "tram_ty": 11, "nghin_ty": 12}


def fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower()


# ═════════════════════════════════════════════════════════════════════════════
# KỲ của một cột — cùng quy ước docs/88 §2
# ═════════════════════════════════════════════════════════════════════════════
_NGAY = re.compile(r"(?<![0-9])(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*"
                   r"((?:19|20)\d{2})(?![0-9])")
_NGAY_CHU = re.compile(r"ngay\s*(\d{1,2})\s*thang\s*(\d{1,2})\s*nam\s*((?:19|20)\d{2})(?![0-9])")
_NAM4 = re.compile(r"(?<![0-9])((?:19|20)\d{2})(?![0-9])")
_HIEN = re.compile(r"nam\s*nay|ky\s*nay|so\s*(du)?\s*cuoi\s*(nam|ky)|trong\s*nam|trong\s*ky")
_TRUOC = re.compile(r"nam\s*truoc|ky\s*truoc|so\s*(du)?\s*dau\s*(nam|ky)|dau\s*ky")


def nam_cua_cot(col_label: str, nam_tep: int) -> set[int]:
    """Năm mà một cột trỏ tới. 01/01/Y là số dư ĐẦU năm -> Y-1."""
    t = fold(col_label)
    ra: set[int] = set()
    for d, m, y in _NGAY.findall(t) + _NGAY_CHU.findall(t):
        d, m, y = int(d), int(m), int(y)
        ra.add(y - 1 if (d == 1 and m == 1) else y)
    if not ra:
        ra |= {int(y) for y in _NAM4.findall(t)}
    if _HIEN.search(t):
        ra.add(nam_tep)
    if _TRUOC.search(t):
        ra.add(nam_tep - 1)
    return ra


# ═════════════════════════════════════════════════════════════════════════════
# ĐƠN VỊ của một bảng — đọc từ chữ in trong bảng, không tin `unit_exponent`
# ═════════════════════════════════════════════════════════════════════════════
def mu_don_vi(text: str) -> int | None:
    t = fold(text)
    for mau, mu in ((r"nghin\s*ty\s*(dong|vnd)", 12), (r"tram\s*ty\s*(dong|vnd)", 11),
                    (r"\bty\s*(dong|vnd)\b", 9), (r"trieu\s*(dong|vnd)\b", 6),
                    (r"nghin\s*(dong|vnd)\b", 3), (r"\b(vnd|dong)\b", 0)):
        if re.search(mau, t):
            return mu
    return None


# ═════════════════════════════════════════════════════════════════════════════
# TOÁN HẠNG
# ═════════════════════════════════════════════════════════════════════════════
@dataclass(slots=True)
class ToanHang:
    ten: str                 # "A" | "B" | "A[2019]" ...
    locator: str
    row_path: str
    row_label: str
    col_label: str
    ky: int | None           # năm của cột
    gia_tri_o: Decimal       # số đọc trong ô
    mu_bang: int             # 10^mu = số nhân để ra VND
    diem_khop: float

    @property
    def vnd(self) -> float:
        return float(self.gia_tri_o) * (10 ** self.mu_bang)

    def mo_ta(self) -> str:
        return (f"{self.ten} = {self.gia_tri_o} × 10^{self.mu_bang} VND · "
                f"kỳ {self.ky} · dòng {self.row_label[:48]!r} · "
                f"cột {self.col_label[:36]!r} · {self.locator}")


@dataclass(slots=True)
class KetQua:
    trang_thai: str                   # "OK" | "UNCERTAIN"
    answer: float | None = None
    pandas_query: str = ""
    evidence: list[dict] = field(default_factory=list)
    operands: list[ToanHang] = field(default_factory=list)
    cong_thuc: str = ""
    ghi_chu: list[str] = field(default_factory=list)


# ═════════════════════════════════════════════════════════════════════════════
# KHỚP DÒNG
# ═════════════════════════════════════════════════════════════════════════════
_BO = {"cua", "va", "la", "bao", "nhieu", "ty", "dong", "trieu", "nghin", "nam",
       "cuoi", "dau", "trong", "den", "ngay", "cong", "ct", "cp", "ctcp", "cong ty",
       "me", "tai", "o", "vao", "theo", "cac", "tinh", "gia", "tri", "muc", "so"}


def tach_tu(s: str) -> list[str]:
    return [t for t in re.findall(r"[a-z0-9]+", fold(s)) if len(t) > 1 and t not in _BO]


def diem_dong(mau: list[str], nhan: str) -> float:
    """Tỷ lệ từ của cụm chỉ tiêu xuất hiện trong nhãn dòng."""
    if not mau:
        return 0.0
    tap = set(tach_tu(nhan))
    return sum(1 for t in mau if t in tap) / len(mau)


# ═════════════════════════════════════════════════════════════════════════════
# BẢNG đã nạp
# ═════════════════════════════════════════════════════════════════════════════
@dataclass(slots=True)
class Bang:
    locator: str
    nam_tep: int
    ticker: str
    rows: list                     # LongCell
    mu_mac_dinh: int | None        # đọc từ tiêu đề bảng; None = không khai


def nap_bang(locator: str, html: str, mu_card: int | None) -> Bang | None:
    from text2pandas.application.usecases.answer import to_long_format
    from text2pandas.infrastructure.parsing.html_table import parse_table_html
    grid = parse_table_html(html)
    if not grid.ok:
        return None
    rows = to_long_format(grid)
    if not rows:
        return None
    doc = locator.rpartition("|")[0]
    dau = " | ".join(r.col_label for r in rows[:40])
    mu = mu_don_vi(dau)
    if mu is None:
        mu = mu_card
    return Bang(locator, int(doc.split("_")[-2]), doc.split("_")[0], rows, mu)


# ═════════════════════════════════════════════════════════════════════════════
# TÌM TOÁN HẠNG — có nguồn, không đoán
# ═════════════════════════════════════════════════════════════════════════════
# 0.60 quá lỏng. Kiểm tay 8 câu `OK` đầu tiên: 6 câu lấy NHẦM DÒNG — "thu nhập
# từ mua bán chứng khoán KINH DOANH" bị nhận cho câu hỏi về "chứng khoán ĐẦU
# TƯ", và cả những dòng chẳng liên quan chỉ vì trùng vài từ chung. Siết lên 0.85
# và đòi ít nhất 2 từ nội dung khớp. Đây là lần thứ tư trong dự án một vị từ
# lỏng gây hại — xem docs/89 §4, docs/88 §4, docs/84.
NGUONG_DONG = 0.85
TOI_THIEU_TU = 2


def tim_toan_hang(ten: str, mau_tu: list[str], ky_can: int | None,
                  ticker_can: str | None, bangs: list[Bang],
                  basis_can: str | None = None) -> ToanHang | None:
    if len(mau_tu) < TOI_THIEU_TU:
        return None
    tot: ToanHang | None = None
    for b in bangs:
        if ticker_can and b.ticker != ticker_can:
            continue
        # Phạm vi báo cáo: "công ty mẹ" -> bản riêng. Bỏ qua thì q822 lấy bản
        # hợp nhất cho câu hỏi về công ty mẹ.
        if basis_can and f"_{basis_can}" not in b.locator:
            continue
        for c in b.rows:
            if la_cot_phi_gia_tri(c.col_label):
                continue                       # yêu cầu 6
            ky = nam_cua_cot(c.col_label, b.nam_tep)
            if not ky:
                continue                       # yêu cầu 8: không xác định kỳ -> bỏ
            if ky_can is not None and ky_can not in ky:
                continue                       # yêu cầu 7: kỳ lấy từ CỘT
            d = max(diem_dong(mau_tu, c.row_path), diem_dong(mau_tu, c.row_label))
            if d < NGUONG_DONG:
                continue
            mu = mu_don_vi(c.col_label)
            if mu is None:
                mu = b.mu_mac_dinh if b.mu_mac_dinh is not None else 0
            th = ToanHang(ten, b.locator, c.row_path, c.row_label, c.col_label,
                          ky_can if ky_can is not None else (min(ky) if ky else None),
                          c.value, mu, d)
            # ưu tiên: khớp dòng cao hơn, rồi |giá trị| lớn hơn (dòng tổng thường
            # là dòng được hỏi, còn dòng chi tiết cùng tên thì nhỏ hơn)
            if tot is None or (th.diem_khop, abs(th.vnd)) > (tot.diem_khop, abs(tot.vnd)):
                tot = th
    if tot is None:
        return None
    # BẤT BIẾN: `pandas_query` chọn ô bằng `(row_path, col_label)` rồi lấy
    # `.values[0]`. Nếu cặp khoá ấy KHÔNG duy nhất trong bảng, `eval` sẽ lấy ô
    # ĐẦU TIÊN còn engine có thể đã chọn ô thứ hai — `answer != eval(query)`.
    # Hai câu (q593, q731) đã vi phạm đúng như vậy. Buộc dùng ô đầu tiên.
    for b in bangs:
        if b.locator != tot.locator:
            continue
        for c in b.rows:
            if c.row_path == tot.row_path and c.col_label == tot.col_label:
                if c.value != tot.gia_tri_o:
                    tot.gia_tri_o = c.value
                    tot.row_label = c.row_label
                break
        break
    return tot


# ═════════════════════════════════════════════════════════════════════════════
# SINH pandas_query — giữ bất biến answer == eval(query)
# ═════════════════════════════════════════════════════════════════════════════
def _bieu_thuc(th: ToanHang, bien: str) -> str:
    rl = th.row_path.replace("\\", "\\\\").replace("'", "\\'")
    cl = th.col_label.replace("\\", "\\\\").replace("'", "\\'")
    lay = (f"float({bien}[({bien}['row_path'] == '{rl}') & "
           f"({bien}['col_label'] == '{cl}')]['value'].values[0])")
    return lay if th.mu_bang == 0 else f"({lay} * {10 ** th.mu_bang})"


def dung_query(ths: list[ToanHang], mau: str, bien_cua: dict[str, str]) -> str:
    """`mau` dùng {0},{1},... cho từng toán hạng."""
    return mau.format(*[_bieu_thuc(t, bien_cua[t.locator]) for t in ths])


def csv_ten(locator: str) -> str:
    d, _, ln = locator.rpartition("|")
    return f"{d}_line{ln}.csv"


def gan_bien(ths: list[ToanHang]) -> tuple[dict[str, str], list[dict]]:
    bien, ev = {}, []
    for t in ths:
        if t.locator not in bien:
            bien[t.locator] = f"df{len(bien) + 1}"
            ev.append({"variable": bien[t.locator], "csv_path": f"data/{csv_ten(t.locator)}"})
    return bien, ev


# ═════════════════════════════════════════════════════════════════════════════
# TÁCH CỤM CHỈ TIÊU từ câu hỏi
# ═════════════════════════════════════════════════════════════════════════════
_CAT = re.compile(
    r"\s+(cua|cuoi nam|dau nam|trong nam|vao nam|vao cuoi nam|den ngay|den cuoi nam|"
    r"tai ngay|nam \d{4}|la bao nhieu|o muc|ghi nhan|tinh bang|theo don vi)\b")
_MO_DAU = re.compile(r"^(tinh|xac dinh|cho biet|hay tinh|tong hop)\s+")


def cum_chi_tieu(question: str) -> str:
    """Cụm chữ mô tả CHỈ TIÊU, cắt trước phần nêu doanh nghiệp/kỳ/đơn vị."""
    t = fold(question)
    t = _MO_DAU.sub("", t)
    t = re.sub(r"^(trong|vao|nam|giai doan)[^,]{0,60},\s*", "", t)   # bỏ mệnh đề dẫn
    for tu_khoa in ("ty le ", "ty trong ", "chenh lech ", "hieu so ",
                    "toc do tang truong ", "tang truong ", "gia tri trung binh ",
                    "trung binh ", "tong "):
        if t.startswith(tu_khoa):
            t = t[len(tu_khoa):]
            break
    m = _CAT.search(t)
    return (t[:m.start()] if m else t).strip(" ,.?")


def tach_tu_so_mau(question: str) -> tuple[str, str] | None:
    """"tỷ lệ A TRÊN B" -> (A, B). Không có ' tren ' thì không phải tỷ lệ hai vế."""
    t = cum_chi_tieu(question)
    i = t.find(" tren ")
    if i < 0:
        return None
    return t[:i].strip(), t[i + 6:].strip()


# ═════════════════════════════════════════════════════════════════════════════
# CÁC PHÉP TOÁN
# ═════════════════════════════════════════════════════════════════════════════
def _pham_vi(locator: str) -> str:
    return "separate" if "_separate" in locator else "consolidated"


def _hoan_tat(ths, mau_query, cong_thuc, gia_tri, ghi_chu):
    # Mọi toán hạng của MỘT phép tính phải cùng phạm vi báo cáo. q705 lấy tử ở
    # bản RIÊNG và mẫu ở bản HỢP NHẤT của cùng KBC/2022 — tỷ lệ giữa hai phạm vi
    # khác nhau không có nghĩa kế toán nào. Câu không nêu "công ty mẹ" thì
    # `basis` là None và bộ lọc ở `tim_toan_hang` không chặn được; chặn ở đây.
    if len({_pham_vi(t.locator) for t in ths}) > 1:
        return KetQua("UNCERTAIN", operands=ths,
                      ghi_chu=["toán hạng lẫn bản riêng và bản hợp nhất — không so được"])
    bien, ev = gan_bien(ths)
    return KetQua("OK", gia_tri, dung_query(ths, mau_query, bien), ev, ths,
                  cong_thuc, ghi_chu)


def _chia(a: float, b: float) -> float | None:
    return None if b == 0 else a / b


def tinh_ratio(question, bangs, ticker, nam, don_vi, basis=None):
    tach = tach_tu_so_mau(question)
    nguon = "cụm 'A trên B' trong câu hỏi"
    if not tach:
        # Tỷ lệ CÓ TÊN: định nghĩa kế toán chuẩn, tra từ `CONG_THUC_TEN`. Đây là
        # kiến thức ngành, không phải khớp theo gold — mọi công thức đều là định
        # nghĩa sách giáo khoa và được liệt kê tường minh trong mã.
        tach = cong_thuc_co_ten(question)
        nguon = "định nghĩa kế toán chuẩn"
    if not tach:
        return KetQua("UNCERTAIN", ghi_chu=["không tách được 'A trên B' và không "
                                            "phải tỷ lệ có tên đã định nghĩa"])
    ta, tb = tach_tu(tach[0]), tach_tu(tach[1])
    A = tim_toan_hang("A (tử)", ta, nam, ticker, bangs, basis)
    B = tim_toan_hang("B (mẫu)", tb, nam, ticker, bangs, basis)
    if A is None or B is None:
        thieu = " và ".join(x for x, v in (("tử", A), ("mẫu", B)) if v is None)
        return KetQua("UNCERTAIN", ghi_chu=[f"thiếu toán hạng: {thieu}"])
    if B.vnd == 0:
        return KetQua("UNCERTAIN", operands=[A, B], ghi_chu=["mẫu số bằng 0 — không chia"])
    he_so = 100 if don_vi == "%" else 1
    gt = A.vnd / B.vnd * he_so
    mau = "{0} / {1}" + (" * 100" if he_so == 100 else "")
    return _hoan_tat([A, B], mau, f"A / B{' × 100' if he_so == 100 else ''}", gt,
                     [f"tử/mẫu lấy từ {nguon}"])


def tinh_percentage_change(question, bangs, ticker, nam_list, don_vi, basis=None):
    if len(nam_list) < 2:
        return KetQua("UNCERTAIN", ghi_chu=["cần hai kỳ, câu chỉ nêu %d" % len(nam_list)])
    a_nam, b_nam = min(nam_list), max(nam_list)
    mau_tu = tach_tu(cum_chi_tieu(question))
    A = tim_toan_hang(f"A[{a_nam}] (gốc)", mau_tu, a_nam, ticker, bangs, basis)
    B = tim_toan_hang(f"B[{b_nam}] (sau)", mau_tu, b_nam, ticker, bangs, basis)
    if A is None or B is None:
        return KetQua("UNCERTAIN", ghi_chu=[f"thiếu kỳ {a_nam if A is None else b_nam}"])
    if A.vnd == 0:
        return KetQua("UNCERTAIN", operands=[A, B], ghi_chu=["kỳ gốc bằng 0 — không chia"])
    he_so = 100 if don_vi in ("%", "?") else 1
    gt = (B.vnd - A.vnd) / abs(A.vnd) * he_so
    mau = "({1} - {0}) / abs({0})" + (" * 100" if he_so == 100 else "")
    return _hoan_tat([A, B], mau, "(B − A) / |A| × 100", gt,
                     ["mẫu số lấy |A| để dấu của kết quả là dấu của mức thay đổi"])


def _doi_don_vi(gt_vnd: float, don_vi: str) -> tuple[float, str]:
    mu = MU.get(don_vi)
    if mu is None:
        return gt_vnd, ""
    return gt_vnd / (10 ** mu), (f" / 10**{mu}" if mu else "")


def tinh_difference(question, bangs, tickers, nam_list, don_vi, basis=None):
    mau_tu = tach_tu(cum_chi_tieu(question))
    if len(tickers) >= 2:
        A = tim_toan_hang(f"A[{tickers[0]}]", mau_tu, nam_list[0] if nam_list else None,
                          tickers[0], bangs, basis)
        B = tim_toan_hang(f"B[{tickers[1]}]", mau_tu, nam_list[0] if nam_list else None,
                          tickers[1], bangs, basis)
    elif len(nam_list) >= 2:
        a_nam, b_nam = max(nam_list), min(nam_list)
        tk = tickers[0] if tickers else None
        A = tim_toan_hang(f"A[{a_nam}]", mau_tu, a_nam, tk, bangs, basis)
        B = tim_toan_hang(f"B[{b_nam}]", mau_tu, b_nam, tk, bangs, basis)
    else:
        return KetQua("UNCERTAIN", ghi_chu=["chênh lệch cần hai vế: hai mã hoặc hai kỳ"])
    if A is None or B is None:
        return KetQua("UNCERTAIN", ghi_chu=["thiếu một vế của phép trừ"])
    gt, hau = _doi_don_vi(A.vnd - B.vnd, don_vi)
    return _hoan_tat([A, B], "({0} - {1})" + hau, "A − B", gt, [])


def _nhieu_o(question, bangs, tickers, nam_list, mau_tu, basis=None):
    """Lấy một toán hạng cho MỖI phần tử của danh sách (nhiều năm hoặc nhiều mã)."""
    ra = []
    if len(nam_list) >= 2:
        tk = tickers[0] if tickers else None
        for y in sorted(nam_list):
            t = tim_toan_hang(f"A[{y}]", mau_tu, y, tk, bangs, basis)
            if t is None:
                return None, f"thiếu kỳ {y}"
            ra.append(t)
    elif len(tickers) >= 2:
        y = nam_list[0] if nam_list else None
        for tk in tickers:
            t = tim_toan_hang(f"A[{tk}]", mau_tu, y, tk, bangs, basis)
            if t is None:
                return None, f"thiếu mã {tk}"
            ra.append(t)
    else:
        return None, "không có danh sách để gộp"
    return ra, ""


def tinh_gop(question, bangs, tickers, nam_list, don_vi, phep, basis=None):
    mau_tu = tach_tu(cum_chi_tieu(question))
    if don_vi == "%":
        # Gộp mà đơn vị hỏi là `%` nghĩa là câu thật ra hỏi một TỶ LỆ (q844:
        # "tỷ trọng vốn chủ sở hữu trung bình ... bao nhiêu %"). Cộng thẳng số
        # tiền rồi chia n cho ra 7,4e12 — sai hoàn toàn về kiểu.
        return KetQua("UNCERTAIN", ghi_chu=["đơn vị hỏi `%` nhưng phép là gộp — "
                                            "câu thực chất là tỷ lệ, chưa xử lý"])
    ths, loi = _nhieu_o(question, bangs, tickers, nam_list, mau_tu, basis)
    if ths is None:
        return KetQua("UNCERTAIN", ghi_chu=[loi])
    dau = {1 if t.vnd > 0 else (-1 if t.vnd < 0 else 0) for t in ths}
    if len(dau - {0}) > 1:
        # q954: chi phí lãi vay của DPM/VIF dương còn HSG âm (lấy từ BCLCTT).
        # Cộng chúng lại là cộng hai quy ước dấu khác nhau.
        return KetQua("UNCERTAIN", operands=ths,
                      ghi_chu=["toán hạng lẫn dấu âm/dương — nghi khác quy ước, không gộp"])
    n = len(ths)
    tong = sum(t.vnd for t in ths)
    if phep == "sum":
        gt_vnd, mau, ct = tong, "(" + " + ".join("{%d}" % i for i in range(n)) + ")", "Σ A_i"
    elif phep == "average":
        gt_vnd, ct = tong / n, "Σ A_i / n"
        mau = "(" + " + ".join("{%d}" % i for i in range(n)) + f") / {n}"
    elif phep in ("max", "min"):
        f = max if phep == "max" else min
        gt_vnd = f(t.vnd for t in ths)
        mau = f"{phep}(" + ", ".join("{%d}" % i for i in range(n)) + ")"
        ct = f"{phep} A_i"
    else:
        return KetQua("UNCERTAIN", ghi_chu=[f"phép chưa hỗ trợ: {phep}"])
    gt, hau = _doi_don_vi(gt_vnd, don_vi)
    return _hoan_tat(ths, mau + hau, ct, gt, [])


def tinh_argmax_year(question, bangs, tickers, nam_list, basis=None):
    """Đáp án là một NĂM. `answer` vẫn là float — 2023.0."""
    mau_tu = tach_tu(cum_chi_tieu(question))
    ths, loi = _nhieu_o(question, bangs, tickers, nam_list, mau_tu, basis)
    if ths is None:
        return KetQua("UNCERTAIN", ghi_chu=[loi])
    tot = max(ths, key=lambda t: t.vnd)
    bien, ev = gan_bien(ths)
    bt = [_bieu_thuc(t, bien[t.locator]) for t in ths]
    nams = sorted(nam_list)
    cap = ", ".join(f"({b}, {y})" for b, y in zip(bt, nams))
    q = f"float(max([{cap}])[1])"
    return KetQua("OK", float(tot.ky), q, ev, ths, "argmax_i A_i -> năm", [])


# ═════════════════════════════════════════════════════════════════════════════
# PHÂN GIẢI MÃ — hợp nhất mã viết tường minh VÀ mã suy từ tên, theo thứ tự xuất
# hiện trong câu.
#
# `parse_question` (src/text2pandas) mắc ĐÚNG lỗi RC-2 mà docs/83 đã trace trong
# `src/text2pandas/pipelines/retrieval/question_intent.py`:
#
#     if literal:  tickers = literal
#     else:        tickers = name_matches
#
# Một mã viết tường minh làm mất TOÀN BỘ mã suy từ tên. Câu "chênh lệch ... giữa
# Ngân hàng TMCP Quốc tế Việt Nam và ... (SHB)" chỉ còn SHB, nên phép trừ mất
# một vế. Đây là nguyên nhân lớn nhất của `UNCERTAIN` ở lớp `difference`.
#
# Ở đây KHÔNG sửa `src/` — chỉ hợp nhất lại ở tầng gọi.
# ═════════════════════════════════════════════════════════════════════════════
_UPPER = re.compile(r"\b[A-Z]{3,4}\b")
_KHONG_PHAI_MA = {"CTCP", "TMCP", "BCTC", "VND", "USD", "EUR", "CTY", "TNHH",
                  "MTV", "HOSE", "HNX", "UPCOM", "ROE", "ROA", "CFO", "TSCD",
                  "TSCĐ", "BOT", "GTGT", "TNDN", "NHNN", "TCTD"}


def phan_giai_ma(question: str, companies, known: set[str]) -> list[str]:
    """Mã CK theo THỨ TỰ XUẤT HIỆN TRONG CÂU, hợp nhất hai nguồn.

    Thứ tự là bắt buộc, không phải trang trí: `chênh lệch A và B` = A − B, đảo
    thứ tự thì đổi dấu. Mã suy từ TÊN phải được định vị bằng vị trí của chính
    cái tên trong câu, không phải xếp cuối — nếu không thì "giữa <tên VIB> và
    <tên SHB> (SHB)" cho ra [SHB, VIB] và kết quả đổi dấu.
    """
    fq = fold(question)
    vi_tri: dict[str, int] = {}
    for m in _UPPER.finditer(question):
        t = m.group(0)
        if t not in _KHONG_PHAI_MA and t in known:
            vi_tri.setdefault(t, m.start())
    for t in companies.lookup(question):
        if t not in known:
            continue
        ten = fold(companies.by_ticker.get(t, ""))
        i = fq.find(ten) if ten else -1
        if i < 0:                                  # thử phần lõi của tên
            loi = re.sub(r"^(ctcp|cong ty co phan|ngan hang tmcp|tap doan)\s+", "", ten)
            i = fq.find(loi) if len(loi) >= 8 else -1
        if t in vi_tri:
            if i >= 0:
                vi_tri[t] = min(vi_tri[t], i)      # tên đứng trước mã trong ngoặc
        else:
            vi_tri[t] = i if i >= 0 else 10 ** 6 + len(vi_tri)
    return [t for t, _ in sorted(vi_tri.items(), key=lambda x: x[1])]


# ═════════════════════════════════════════════════════════════════════════════
# TỶ LỆ CÓ TÊN — định nghĩa kế toán chuẩn, không phải khớp theo gold
# ═════════════════════════════════════════════════════════════════════════════
CONG_THUC_TEN = {
    "bien loi nhuan gop": ("loi nhuan gop", "doanh thu thuan"),
    "bien loi nhuan rong": ("loi nhuan sau thue", "doanh thu thuan"),
    "bien lai gop": ("loi nhuan gop", "doanh thu thuan"),
    "roe": ("loi nhuan sau thue", "von chu so huu"),
    "roa": ("loi nhuan sau thue", "tong cong tai san"),
    "he so thanh toan hien hanh": ("tai san ngan han", "no ngan han"),
    "he so thanh toan ngan han": ("tai san ngan han", "no ngan han"),
    "vong quay tong tai san": ("doanh thu thuan", "tong cong tai san"),
    "ty le no tren von chu so huu": ("no phai tra", "von chu so huu"),
    "ty le no tren tong tai san": ("no phai tra", "tong cong tai san"),
}


def cong_thuc_co_ten(question: str) -> tuple[str, str] | None:
    t = fold(question)
    for ten, (a, b) in sorted(CONG_THUC_TEN.items(), key=lambda x: -len(x[0])):
        if ten in t:
            return a, b
    return None
