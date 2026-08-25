#!/usr/bin/env python3
"""Test hợp đồng kiểu đáp án.

Ca ADVERSARIAL quan trọng hơn ca positive: một hợp đồng đoán bừa gây hồi quy
IM LẶNG ở tầng trọng tài, tệ hơn là không có hợp đồng. Nên phần lớn test dưới
đây kiểm rằng nó biết **im lặng đúng lúc**.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from execution.answer_type_v1 import kiem, suy_hop_dong, trong_tai  # noqa: E402

CA = []


def ca(ten):
    def deco(f):
        CA.append((ten, f))
        return f
    return deco


# ── suy hợp đồng ───────────────────────────────────────────────────────────
@ca("NAM · 'năm nào có … cao nhất' → kind NAM, nguyên, 1990..2035")
def _():
    h = suy_hop_dong("Trong các năm 2015, 2020, năm nào có tổng nợ cao nhất?")
    assert h.kind == "NAM" and h.phai_nguyen and h.lo == 1990 and h.hi == 2035


@ca("DEM · 'bao nhiêu công ty' → DEM, phải nguyên")
def _():
    assert suy_hop_dong("Có bao nhiêu công ty có ROE dương?").kind == "DEM"


@ca("LAN · 'là bao nhiêu lần' và 'D/E' → LAN")
def _():
    assert suy_hop_dong("hệ số khả năng thanh toán lãi vay là bao nhiêu lần?").kind == "LAN"
    assert suy_hop_dong("Tỷ số D/E của KBC năm 2020?").kind == "LAN"


@ca("PCT · 'bao nhiêu phần trăm' và 'tỷ trọng … là bao nhiêu' → PCT")
def _():
    assert suy_hop_dong("Doanh thu tăng bao nhiêu phần trăm?").kind == "PCT"
    assert suy_hop_dong("Tỷ trọng nợ ngắn hạn trên tổng nợ là bao nhiêu?").kind == "PCT"


@ca("TIEN · bắt đúng hệ số đơn vị")
def _():
    assert suy_hop_dong("… là bao nhiêu tỷ đồng?").don_vi == 1e9
    assert suy_hop_dong("… là bao nhiêu triệu đồng?").don_vi == 1e6
    assert suy_hop_dong("… là bao nhiêu đồng?").don_vi == 1.0


@ca("ADVERSARIAL · TIEN KHÔNG đặt ngưỡng độ lớn")
def _():
    """Bản nháp đầu dùng |v| ≥ 1000 và luật ấy SAI: hỏi 'bao nhiêu tỷ đồng' mà
    đáp án 5,2 (tỷ) là hoàn toàn hợp lệ. Ràng buộc duy nhất kiểm được là ĐƠN VỊ."""
    h = suy_hop_dong("Lợi nhuận là bao nhiêu tỷ đồng?")
    assert h.lo is None and h.hi is None
    assert kiem(h, 5.2)["ok"] is True


@ca("ADVERSARIAL · độ đặc hiệu — '% ' thắng 'đồng' khi có cả hai")
def _():
    h = suy_hop_dong("Chi phí (đơn vị: triệu đồng) tăng bao nhiêu phần trăm?")
    assert h.kind == "PCT", "cụm hỏi là phần trăm; 'triệu đồng' chỉ là đơn vị cột"


@ca("ADVERSARIAL · câu không có tín hiệu → UNKNOWN, im lặng")
def _():
    for q in ("Chi phí dự phòng của ngân hàng X trong năm 2020?",
              "Nêu tổng tài sản.", "", None):
        h = suy_hop_dong(q)
        assert h.kind in ("UNKNOWN", "TIEN"), q
        if h.kind == "UNKNOWN":
            assert kiem(h, 123)["ok"] is None, "UNKNOWN phải trả None, không phải False"


@ca("ADVERSARIAL · 'năm 2020' KHÔNG kích hoạt NAM (chỉ 'năm nào' mới)")
def _():
    assert suy_hop_dong("Doanh thu năm 2020 là bao nhiêu đồng?").kind != "NAM"


# ── kiểm đáp án ────────────────────────────────────────────────────────────
@ca("kiểm · ca thật qid 501 — hỏi năm nào, trả 8e11 ⇒ VI PHẠM")
def _():
    h = suy_hop_dong("Trong các năm 2015, 2020, 2021 và 2023, năm nào có tổng "
                     "giá gốc nợ phải thu quá hạn cao nhất?")
    r = kiem(h, 800000000000.0)
    assert r["ok"] is False and r["ly_do"] == "VUOT_NGUONG_NAM"


@ca("kiểm · ca thật qid 362 — hỏi tỷ trọng, trả 3,7e12 ⇒ VI PHẠM")
def _():
    h = suy_hop_dong("Tỷ trọng tổng nợ ngắn hạn là bao nhiêu?")
    assert kiem(h, 3777947515921.0)["ok"] is False


@ca("kiểm · năm hợp lệ ⇒ OK")
def _():
    assert kiem(suy_hop_dong("năm nào cao nhất?"), 2021)["ok"] is True


@ca("kiểm · năm dạng 2021.0 vẫn nguyên ⇒ OK")
def _():
    assert kiem(suy_hop_dong("năm nào cao nhất?"), "2021.0")["ok"] is True


@ca("kiểm · năm 2021.5 ⇒ VI PHẠM tính nguyên")
def _():
    assert kiem(suy_hop_dong("năm nào?"), 2021.5)["ly_do"] == "KHONG_NGUYEN_NAM"


@ca("kiểm · đáp án rỗng / không parse được ⇒ VI PHẠM, không ném lỗi")
def _():
    h = suy_hop_dong("năm nào?")
    assert kiem(h, None)["ly_do"] == "TRONG"
    assert kiem(h, "")["ly_do"] == "TRONG"
    assert kiem(h, "không rõ")["ly_do"] == "KHONG_PARSE_DUOC_SO"


@ca("kiểm · nan/inf ⇒ VI PHẠM")
def _():
    h = suy_hop_dong("bao nhiêu lần?")
    assert kiem(h, float("inf"))["ok"] is False
    assert kiem(h, float("nan"))["ok"] is False


@ca("kiểm · PCT cho phép ÂM và cho phép > 100")
def _():
    h = suy_hop_dong("tăng bao nhiêu phần trăm?")
    assert kiem(h, -37.5)["ok"] is True, "tăng trưởng âm là hợp lệ"
    assert kiem(h, 250.0)["ok"] is True, "tăng gấp 2,5 lần là hợp lệ"


# ── trọng tài ──────────────────────────────────────────────────────────────
@ca("trọng tài · đúng một nhánh khớp kiểu ⇒ chọn nhánh đó")
def _():
    h = suy_hop_dong("năm nào có doanh thu cao nhất?")
    r = trong_tai(h, [("C0", 5344660910.0), ("C3", 2020)])
    assert r["nhanh"] == "C3" and r["ly_do"] == "DUY_NHAT_KHOP_KIEU"


@ca("trọng tài · hợp đồng UNKNOWN ⇒ giữ nhánh ưu tiên đầu, KHÔNG can thiệp")
def _():
    h = suy_hop_dong("Tổng tài sản?")
    r = trong_tai(h, [("C0", 123), ("C3", 456)])
    assert r["nhanh"] == "C0" and r["ly_do"] in ("HOP_DONG_IM_LANG", "NHIEU_NHANH_KHOP")


@ca("trọng tài · KHÔNG nhánh nào khớp ⇒ VẪN trả đáp án, chỉ gắn cờ")
def _():
    """Abstain và sai đều 0 điểm (COMPETITION_SPEC §4.3). Bỏ trống một đáp án
    sai kiểu chỉ mất cơ hội nó tình cờ đúng, mà không được gì."""
    h = suy_hop_dong("năm nào?")
    r = trong_tai(h, [("C0", 5e9), ("C3", 9e9)])
    assert r["chon"] is not None and r.get("co_canh_bao") is True


@ca("trọng tài · nhiều nhánh khớp ⇒ giữ ưu tiên đầu, không đảo thứ tự")
def _():
    h = suy_hop_dong("năm nào?")
    r = trong_tai(h, [("C0", 2019), ("C3", 2021)])
    assert r["nhanh"] == "C0" and r["ly_do"] == "NHIEU_NHANH_KHOP"


@ca("trọng tài · danh sách rỗng không làm vỡ")
def _():
    assert trong_tai(suy_hop_dong("năm nào?"), [])["chon"] is None


def chay() -> tuple[int, int, list]:
    xanh, do = 0, []
    for ten, f in CA:
        try:
            f()
            xanh += 1
        except AssertionError as e:
            do.append((ten, str(e) or "assert failed"))
        except Exception as e:
            do.append((ten, f"{type(e).__name__}: {e}"))
    return xanh, len(CA), do


if __name__ == "__main__":
    x, n, d = chay()
    for ten, msg in d:
        print(f"✗ {ten}\n    {msg}")
    print(f"\n{x}/{n} xanh")
    raise SystemExit(0 if not d else 1)
