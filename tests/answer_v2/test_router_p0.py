#!/usr/bin/env python3
"""P0 · router precision + ontology contract.

Mỗi ca là MỘT DÒNG của decision table trong `router_v1` docstring, và mỗi intent
có **cả positive lẫn hard negative**. Hard negative mới là phần đắt: một regex
lấy nguyên văn từ 4 câu sai của doc 147 gần như chắc chắn sửa đúng 4 câu ấy —
câu hỏi thật là nó có kéo theo bao nhiêu câu KHÔNG nên chặn. Doc 155 §5.1 đòi
đúng điều này.

Ràng buộc bao trùm: `router_fix=False` phải tái hiện CHÍNH XÁC hành vi PRE-FIX.
Không có nó thì ablation `router_fix_only` không còn là phép thử nhân quả.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))
sys.path.insert(0, str(ROOT / "tools"))

import formula_registry as FR   # noqa: E402
import metric_ontology as MO    # noqa: E402
import router_v1 as RT          # noqa: E402

SPECS, FORMULAS = MO.load(), FR.load()
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _moitruong import chay_chung, in_ket_qua  # noqa: E402
CA = []


def ca(ten):
    def deco(f):
        CA.append((ten, f))
        return f
    return deco


def plan(ents=("HBC",), years=(2016,)):
    return {"entities": list(ents), "years": list(years)}


def r(q, p=None, fix=True):
    return RT.route(q, p or plan(), FORMULAS, router_fix=fix)[0]


def ly_do(q, p=None, fix=True):
    return RT.route(q, p or plan(), FORMULAS, router_fix=fix)[2]


# ══════════════════════════════════════════════════════════════════════════════
# 1 · Bốn QID sai gốc của doc 147 phải RỜI R2 (câu hỏi nguyên văn)
# ══════════════════════════════════════════════════════════════════════════════
Q388 = ("Trong nhóm doanh nghiệp bất động sản NVL, KBC, DIG, IJC, CEO và CRE "
        "trong năm 2024, biên lợi nhuận gộp bình quân của các doanh nghiệp có "
        "CFO margin âm là bao nhiêu phần trăm?")
Q421 = ("Từ năm 2023 sang 2024, ROA của doanh nghiệp có mức giảm biên lợi nhuận "
        "ròng mạnh nhất trong ngành Quản lý và phát triển bất động sản (Tập đoàn "
        "Vingroup, Vincom Retail, Đô thị Kinh Bắc, Văn Phú Invest, Đầu tư Hải "
        "Phát) đã thay đổi bao nhiêu điểm phần trăm?")
Q577 = ("Với CTCP Tập đoàn C.E.O trong giai đoạn 2022-2024, ở các năm có biên "
        "lợi nhuận ròng trên 10%, doanh thu thuần thấp nhất là bao nhiêu nghìn "
        "tỷ đồng?")
Q962 = ("Xin tính tỷ số nợ phải trả trên vốn chủ sở hữu trung bình của Công ty "
        "CTCP Thủy điện Đa Nhim - Hàm Thuận - Đa Mi (DNH) - công ty mẹ trong các "
        "năm 2016, 2017, 2018, 2021 và 2022.")
# Câu thứ năm: hai tầng có khoảng cách 110 ký tự — cửa sổ 80 để lọt (qid 386).
Q386 = ("Trong giai đoạn 2020-2024, ở năm Công ty Cổ phần Tập đoàn Masan (MSN) "
        "có tỷ lệ dòng tiền thuần từ hoạt động kinh doanh (CFO) trên lợi nhuận "
        "sau thuế thấp nhất trong các năm lợi nhuận sau thuế dương, hệ số thanh "
        "toán nhanh cuối năm đó là bao nhiêu lần?")
# Hai câu R2 ĐÚNG phải GIỮ.
Q674 = "Tỷ suất lợi nhuận ròng của HBC năm 2016 là bao nhiêu %?"
Q708 = "Biên lợi nhuận ròng của Công ty CP Masan MeatLife năm 2017 là bao nhiêu %?"

P_NHOM = plan(["NVL", "KBC", "DIG", "IJC", "CEO", "CRE"], [2024])
P_421 = plan(["VIC", "VRE", "KBC", "VPI", "HPX"], [2023, 2024])
P_577 = plan(["CEO"], [2022, 2023, 2024])
P_962 = plan(["DNH"], [2016, 2017, 2018, 2021, 2022])
P_386 = plan(["MSN"], [2020, 2021, 2022, 2023, 2024])


@ca("388 nhóm+điều kiện rời R2")
def t_388():
    assert r(Q388, P_NHOM) == "R0", ly_do(Q388, P_NHOM)


@ca("421 cực trị 'mạnh nhất' rời R2")
def t_421():
    assert r(Q421, P_421) == "R0", ly_do(Q421, P_421)


@ca("577 điều kiện 'ở các năm có … trên 10%' rời R2")
def t_577():
    assert r(Q577, P_577) == "R0", ly_do(Q577, P_577)


@ca("962 trung bình nhiều kỳ rời R2")
def t_962():
    assert r(Q962, P_962) == "R0", ly_do(Q962, P_962)


@ca("386 hai tầng khoảng cách xa rời R2")
def t_386():
    assert r(Q386, P_386) == "R0", ly_do(Q386, P_386)


@ca("674 một tầng GIỮ R2")
def t_674():
    assert r(Q674, plan(["HBC"], [2016])) == "R2", ly_do(Q674, plan(["HBC"], [2016]))


@ca("708 một tầng GIỮ R2")
def t_708():
    assert r(Q708, plan(["MML"], [2017])) == "R2", ly_do(Q708, plan(["MML"], [2017]))


# ══════════════════════════════════════════════════════════════════════════════
# 2 · HARD NEGATIVE — không được chặn oan
# ══════════════════════════════════════════════════════════════════════════════
@ca("hard-neg: 'bình quân' trong TÊN CHỈ TIÊU, một tầng → giữ R2")
def t_hn_ten_chi_tieu():
    q = "Tỷ suất lợi nhuận ròng trên tổng tài sản bình quân của HBC năm 2016 là bao nhiêu %?"
    assert r(q, plan(["HBC"], [2016])) == "R2", ly_do(q, plan(["HBC"], [2016]))


@ca("hard-neg: 'giảm 5%' mô tả thay đổi đơn, không cực trị → không HAI_TANG")
def t_hn_giam_don():
    q = "Biên lợi nhuận ròng của HBC năm 2016 giảm 5% là bao nhiêu %?"
    assert RT.HAI_TANG_P0.search(RT.chuan_hoa_cau_hoi(q)) is None


@ca("hard-neg: điều kiện nằm trong NHÃN chỉ tiêu, không phải mệnh đề lọc")
def t_hn_nhan_dieu_kien():
    q = "Tỷ lệ nợ phải trả trên vốn chủ sở hữu của HBC năm 2016 là bao nhiêu %?"
    assert r(q, plan(["HBC"], [2016])) == "R2", ly_do(q, plan(["HBC"], [2016]))


@ca("hard-neg: một kỳ + 'bình quân' tên chỉ tiêu → KHÔNG rơi TRUNG_BINH_DA_KY")
def t_hn_mot_ky_binh_quan():
    q = "Vốn chủ sở hữu bình quân của HBC năm 2016 là bao nhiêu?"
    assert ly_do(q, plan(["HBC"], [2016])) != "TRUNG_BINH_DA_KY_THUOC_R1"


# ══════════════════════════════════════════════════════════════════════════════
# 3 · Chuẩn hoá TRƯỚC detection (doc 155 §5.1)
# ══════════════════════════════════════════════════════════════════════════════
@ca("chuẩn hoá: '≥' và '>=' cho cùng kết quả")
def t_chuan_hoa_toan_tu():
    a = "Trong các năm có biên lợi nhuận ròng ≥ 10%, doanh thu thuần là bao nhiêu?"
    b = a.replace("≥", ">")
    assert r(a, P_577) == r(b, P_577) == "R0"


@ca("chuẩn hoá: non-breaking space và gạch nối dài không phá pattern")
def t_chuan_hoa_khoang_trang():
    q = Q421.replace(" ", " ").replace("-", "—")
    assert r(q, P_421) == "R0"


@ca("chuẩn hoá: NFD (dấu tổ hợp) và NFC cho cùng kết quả")
def t_chuan_hoa_nfc():
    import unicodedata
    assert r(unicodedata.normalize("NFD", Q421), P_421) == "R0"


# ══════════════════════════════════════════════════════════════════════════════
# 4 · Các luật precision còn lại
# ══════════════════════════════════════════════════════════════════════════════
@ca("nhiều entity → R0 (không lấy ents[0] tuỳ tiện)")
def t_nhieu_entity():
    q = "Biên lợi nhuận ròng năm 2024 là bao nhiêu %?"
    assert ly_do(q, plan(["NVL", "KBC"], [2024])) == "NHIEU_ENTITY_CHUA_HO_TRO"


@ca("phạm vi 'công ty mẹ' → R0 vì binder không nhận scope từ câu hỏi")
def t_pham_vi_rieng():
    q = "Tỷ lệ nợ trên tổng tài sản của công ty mẹ Ngân hàng TMCP Sài Gòn Công Thương cuối năm 2015 là bao nhiêu phần trăm?"
    assert ly_do(q, plan(["SGB"], [2015])) == "PHAM_VI_RIENG_CHUA_HO_TRO"


@ca("câu ĐẾM → R0")
def t_dem():
    q = "Từ 2023 sang 2024 có bao nhiêu doanh nghiệp đồng thời tăng tỷ trọng hàng tồn kho trên tổng tài sản và giảm biên lợi nhuận gộp?"
    assert r(q, plan(["HPX"], [2023, 2024])) == "R0"


@ca("lý do trả về là lý do CẤU TRÚC khi trùng với lý do phạm vi")
def t_uu_tien_ly_do():
    # 962 vừa "trung bình nhiều kỳ" vừa "công ty mẹ" → phải báo cấu trúc.
    assert ly_do(Q962, P_962) in {"TRUNG_BINH_DA_KY_THUOC_R1",
                                  "HAI_TANG_CHUA_HO_TRO",
                                  "DIEU_KIEN_CHUA_HO_TRO",
                                  "NHOM_CHUA_HO_TRO"}


# ══════════════════════════════════════════════════════════════════════════════
# 5 · BACKWARD COMPATIBILITY — cờ TẮT = hành vi PRE-FIX
# ══════════════════════════════════════════════════════════════════════════════
@ca("cờ TẮT: 4 QID sai gốc VẪN vào R2 (tái hiện PRE-FIX)")
def t_prefix_giu_nguyen():
    assert r(Q388, P_NHOM, fix=False) == "R2"
    assert r(Q421, P_421, fix=False) == "R2"
    assert r(Q577, P_577, fix=False) == "R2"
    assert r(Q962, P_962, fix=False) == "R2"


@ca("cờ TẮT: 674/708 vẫn R2")
def t_prefix_keeper():
    assert r(Q674, plan(["HBC"], [2016]), fix=False) == "R2"
    assert r(Q708, plan(["MML"], [2017]), fix=False) == "R2"


# ══════════════════════════════════════════════════════════════════════════════
# 6 · ONTOLOGY — dòng tổng, va chạm, định ngữ phân bổ
# ══════════════════════════════════════════════════════════════════════════════
@ca("ontology: 'TỔNG NỢ PHẢI TRẢ' khớp total_liabilities khi bật cờ")
def t_ont_tong_no():
    assert MO.nhan_dien(SPECS, "TỔNG NỢ PHẢI TRẢ") is None
    assert MO.nhan_dien(SPECS, "TỔNG NỘ PHẢI TRẢ",
                        ontology_fix=True) == "total_liabilities"


@ca("ontology: 'Tổng nợ phải trả và vốn chủ sở hữu' KHÔNG phải nợ phải trả")
def t_ont_va_cham_tong_tai_san():
    for n in ["Tổng Nợ phải trả và Vốn chủ sở hữu",
              "Tổng nợ phải trả và vốnchủ sở hữu",
              "Tổng cộng nợ phải trả và vốn chủ sở hữu",
              "Tổng nợ phải trả, vốn chủ sở hữu và lợi ích của cổ đông không kiểm soát"]:
        assert MO.nhan_dien(SPECS, n, ontology_fix=True) != "total_liabilities", n


@ca("ontology: dòng thuyết minh theo BỘ PHẬN không phải dòng tổng")
def t_ont_bo_phan():
    for n in ["Tổng nợ phải trả theo bộ phận",
              "Tổng doanh thu thuần của bộ phận",
              "Tổng nợ phải trả không phân bổ",
              "Tổng doanh thu thuần bán ra bên ngoài"]:
        assert MO.nhan_dien(SPECS, n, ontology_fix=True) is None, n


@ca("ontology: 'Lợi nhuận sau thuế của công ty mẹ' KHÔNG phải profit_after_tax")
def t_ont_cong_ty_me():
    for n in ["Lợi nhuận sau thuế của công ty mẹ",
              "Lợi nhuận sau thuế của cổ đông của công ty mẹ",
              "Lợi nhuận sau thuế của cổ đông công ty mẹ",
              "Lợi nhuận sau thuế công ty mẹ",
              "Lợi nhuận sau thuế phân bổ cho cổ đông sở hữu cổ phiếu phổ thông",
              "Lợi nhuận sau thuế thuộc về cổ đông công ty mẹ"]:
        assert MO.nhan_dien(SPECS, n) == "profit_after_tax", f"PRE-FIX phải khớp: {n}"
        assert MO.nhan_dien(SPECS, n, ontology_fix=True) is None, n


@ca("ontology: LNST tổng hợp nhất VẪN khớp sau khi bật cờ")
def t_ont_lnst_van_khop():
    for n in ["Lợi nhuận sau thuế TNDN", "Lợi nhuận sau thuế thu nhập doanh nghiệp"]:
        assert MO.nhan_dien(SPECS, n, ontology_fix=True) == "profit_after_tax", n


@ca("ontology: 'tổng tài sản' vẫn là total_assets, không rơi sang metric khác")
def t_ont_uu_tien_truc_tiep():
    assert MO.nhan_dien(SPECS, "Tổng tài sản", ontology_fix=True) == "total_assets"
    assert MO.nhan_dien(SPECS, "Tổng cộng tài sản", ontology_fix=True) == "total_assets"


@ca("ontology: chặn con CŨ vẫn hiệu lực khi bật cờ")
def t_ont_chan_con_cu():
    for n in ["Nợ phải trả người bán ngắn hạn", "Lợi nhuận sau thuế chưa phân phối",
              "Tổng nợ phải trả người bán"]:
        assert MO.nhan_dien(SPECS, n, ontology_fix=True) is None, n


@ca("ontology: cờ TẮT = hành vi PRE-FIX, không nhãn mới nào khớp")
def t_ont_prefix():
    for n in ["TỔNG NỢ PHẢI TRẢ", "Tổng vốn chủ sở hữu", "Tổng doanh thu thuần"]:
        assert MO.nhan_dien(SPECS, n) is None, n


def chay():
    """Ủy quyền cho runner chung — ca thiếu DB thành SKIP, không thành PASS."""
    return chay_chung(CA)


if __name__ == "__main__":
    x, n, d = chay()
    raise SystemExit(in_ket_qua(Path(__file__).stem, x, n, d))
