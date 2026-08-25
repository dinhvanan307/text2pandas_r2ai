"""S3 · KHOÁ phát hiện: `doc_year == năm hỏi` KHÔNG phải bằng chứng.

VÌ SAO CẦN FILE NÀY
-------------------
docs/86 §4 báo cáo rằng trong 340 ứng viên gold, tỉ lệ `doc_year` khớp năm hỏi
là **1.000**, so với 0.593 ở ứng viên không-gold, và đề xuất dùng nó làm khoá
xếp hạng đầu tiên cho S3. Con số ấy **không có giá trị chứng minh**.

Nguyên nhân: quy tắc phân xử ghi ở docs/82 (§quy tắc dùng bằng chứng) nói

    "`doc_year`: lấy **năm báo cáo**, không suy từ cột năm so sánh."

Nghĩa là nhãn gold bị RÀNG BUỘC phải khớp năm ngay từ lúc gán. Đo lại chính
ràng buộc ấy rồi gọi nó là "tín hiệu" là lập luận vòng tròn.

Bằng chứng phụ trợ (đo ở `tools/chan_doan/audit_year_leakage.py`):

    933/3159 ứng viên lệch năm ĐÃ được chào trong phiếu — và bị loại 100%,
    đều tăm tắp ở cả T1, T2 lẫn screen. Đều tuyệt đối ở mọi tầng là dấu vân
    của một QUY TẮC, không phải của một hiện tượng.

FILE NÀY KHOÁ ĐIỀU GÌ
---------------------
Rằng **công cụ không hề ép** điều đó — `kiem()` chấp nhận nhãn gold lệch năm
trong phạm vi `year_slack`. Cho nên 0% nhãn lệch năm là lựa chọn của người
phân xử, không phải giới hạn của hệ thống. Ai muốn kiểm chứng lại giả thuyết
năm chỉ cần phân xử lại với quy tắc trung lập; `gold_tay.py check` sẽ không
chặn.

Nếu một ngày `kiem()` bị siết thành "phải khớp năm tuyệt đối", test 1 sẽ đỏ —
và đó đúng là lúc cần dừng lại, vì khi ấy gold vĩnh viễn không thể phản chứng
được bộ lọc năm nữa.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from gold_tay import kiem  # noqa: E402

UID_2020 = "a" * 16
UID_2021 = "b" * 16
UID_2022 = "c" * 16

META = {
    UID_2020: {"ticker": "EIB", "doc_year": 2020, "basis": "consolidated"},
    UID_2021: {"ticker": "EIB", "doc_year": 2021, "basis": "consolidated"},
    UID_2022: {"ticker": "EIB", "doc_year": 2022, "basis": "consolidated"},
}

POOL = {
    105: {
        "mode": "t1",
        "targets": ["EIB"],
        "years": [2020],
        "explicit_scope": None,
        "cells_missing": [],
        # cả ba đều NẰM TRONG pool: người phân xử thật sự được chào cả ba.
        "candidates": [{"table_uid": u} for u in (UID_2020, UID_2021, UID_2022)],
    }
}


def _loi_nam(uid: str, slack: int = 1) -> list[str]:
    loi = kiem([{"id": 105, "gold_table_uids": [uid]}], POOL, META, {},
               year_slack=slack)
    return [x for x in loi if "doc_year" in x]


# ═════════════════════════════════════════════════════════════════════════════
# 1 · công cụ CHẤP NHẬN nhãn lệch năm — nên 0% lệch năm là quy tắc, không phải
#     ràng buộc kỹ thuật
# ═════════════════════════════════════════════════════════════════════════════

def test_kiem_chap_nhan_nhan_gold_lech_nam_mot_nam():
    """Báo cáo 2021 chứa cột so sánh 2020, nên nó TRẢ LỜI ĐƯỢC câu hỏi 2020.

    `kiem()` không phản đối. Việc gold hiện tại không có một nhãn nào như vậy
    là do quy tắc phân xử, không phải do `check` chặn.
    """
    assert _loi_nam(UID_2021) == []


def test_kiem_van_chap_nhan_nhan_gold_dung_nam():
    assert _loi_nam(UID_2020) == []


# ═════════════════════════════════════════════════════════════════════════════
# 2 · nhưng `kiem()` vẫn có khái niệm năm — biên `year_slack` là thật
# ═════════════════════════════════════════════════════════════════════════════

def test_kiem_chan_nhan_gold_lech_hai_nam():
    """+2 vượt `year_slack=1` ⇒ bị chặn. Bộ kiểm không hề mù về năm."""
    loi = _loi_nam(UID_2022)
    assert len(loi) == 1 and "2022" in loi[0]


def test_noi_rong_slack_thi_lech_hai_nam_duoc_chap_nhan():
    assert _loi_nam(UID_2022, slack=2) == []


# ═════════════════════════════════════════════════════════════════════════════
# 3 · năm hỏi trống ⇒ không áp ràng buộc năm nào
# ═════════════════════════════════════════════════════════════════════════════

def test_cau_khong_neu_nam_thi_khong_rang_buoc_nam():
    pool = {105: dict(POOL[105], years=[])}
    loi = kiem([{"id": 105, "gold_table_uids": [UID_2022]}], pool, META, {})
    assert [x for x in loi if "doc_year" in x] == []
