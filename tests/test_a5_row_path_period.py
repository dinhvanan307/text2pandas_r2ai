"""A5-B · kỳ đọc từ trục DÒNG, và miễn trừ differential đi kèm.

Nguyên tắc của bộ test này: mỗi lần mở một cánh cửa thì phải có một test
chứng minh những cánh cửa còn lại vẫn đóng. `period_end` nằm trong MEASURED —
nhóm mà "đổi" nghĩa là đọc sai tài liệu — nên miễn trừ ở đây là chỗ dễ hỏng
nhất của cả A5.
"""
import importlib.util as _u
from pathlib import Path

import pytest

from data_pipeline.models import EvidenceSource, PeriodRole, PeriodType
from data_pipeline.period_resolver import PERIOD_VERSION, resolve_row_period
from data_pipeline.readiness import load_policy

_spec = _u.spec_from_file_location(
    "_da", Path(__file__).resolve().parents[1] / "tools" / "differential_audit.py")
DA = _u.module_from_spec(_spec)
_spec.loader.exec_module(DA)


# ── B1 · bộ phân giải trục dòng ──────────────────────────────────────────
def test_period_version_da_tang():
    assert PERIOD_VERSION == "1.7"


def test_ngay_tuyet_doi_trong_nhan_dong_duoc_doc():
    r = resolve_row_period("18 Vốn chủ sở hữu a › Số dư tại ngày 31/12/2015")
    assert r.period_end == "2015-12-31"
    assert r.period_role is PeriodRole.CLOSING
    assert r.period_type is PeriodType.INSTANT
    assert r.source is EvidenceSource.ROW_CONTEXT
    assert r.rule == "P-ROW-EXPLICIT-DMY"


def test_0101_van_la_so_cuoi_ky_truoc_giong_truc_cot():
    """Lệch ngữ nghĩa giữa hai trục thì cùng một khái niệm sẽ mang hai kỳ."""
    r = resolve_row_period("Số dư tại ngày 01/01/2014")
    assert r.period_end == "2013-12-31"
    assert r.period_role is PeriodRole.OPENING
    assert r.rule == "P-ROW-OPENING-0101"


def test_dang_viet_chu_cung_doc_duoc():
    r = resolve_row_period("Số dư tại ngày 31 tháng 12 năm 2018")
    assert r.period_end == "2018-12-31"


@pytest.mark.parametrize("t", [
    "18 Vốn chủ sở hữu a › Vốn góp tăng trong năm",
    "Lợi nhuận tăng trong năm",
    "Phân phối lợi nhuận",
    "Áp dụng chính sách kế toán mới (i)",
])
def test_dong_bien_dong_khong_co_ngay_thi_KHONG_doan(t):
    """157.465 ô thuộc nhóm này. Gán doc_year cho chúng là SAI với các dòng
    thuộc năm trước trong bảng trải nhiều năm — xem AMD-A5-02."""
    r = resolve_row_period(t)
    assert not r.resolved
    assert r.rule == "P-ROW-UNRESOLVED"


def test_so_hieu_van_ban_khong_bi_doc_thanh_ky():
    r = resolve_row_period("Nghị định 12/2015/NĐ-CP về thuế thu nhập")
    assert not r.resolved


def test_nam_tran_KHONG_du_de_ket_luan():
    """Tầng 2 (18.057 ô) cố ý chưa mở. Test này khoá quyết định đó lại."""
    assert not resolve_row_period("Số dư năm 2015").resolved


def test_ngay_khong_hop_le_bi_tu_choi():
    assert not resolve_row_period("Số dư tại ngày 45/45/2015").resolved


def test_nhan_rong_khong_no():
    r = resolve_row_period("", "")
    assert not r.resolved and r.rule == "P-ROW-EMPTY"


# ── chính sách · cờ có điều kiện ─────────────────────────────────────────
def test_co_period_from_row_path_la_co_DIEU_KIEN_khong_phai_warning_phang():
    cf = [c for c in load_policy().conditional if c["flag"] == "period_from_row_path"]
    assert len(cf) == 1
    assert cf[0]["requires_col_path_discriminative"] is True, (
        "bằng chứng kỳ mạnh KHÔNG miễn phép kiểm địa chỉ hoá")
    assert cf[0]["confidence_allowed"] == ["high", "medium"]


# ── C1 · miễn trừ differential ───────────────────────────────────────────
BASE = dict(period_end=None, period_source="none",
            quality_flags_json='["period_unresolved"]',
            value_decimal_text="1", is_negative=0, value_kind="money",
            unit_kind="money", scale_exponent=0, currency="VND",
            row_path_text="r", col_path_text="c", metric_label_clean="m")
# `period_unresolved` BIẾN MẤT ở vế mới — đây là hình dạng THẬT, đo trên
# 21.438 ô của A4→A5, không phải hình dạng tôi đoán. Bản đầu của tệp test này
# giữ cờ đó ở cả hai vế, nên nhánh "cờ bị mất" không bao giờ được chạm và cả
# 21.438 ô rơi xuống `measured_value_changed_BLOCKING` khi chạy thật.
NEW = dict(BASE, period_end="2015-12-31", period_source="row_context",
           quality_flags_json='["period_from_row_path"]')
F = list(BASE)


def test_null_sang_ngay_duoc_nhan_lop_ly_do_rieng():
    assert DA._reason(BASE, NEW, F) == "period_recovered_from_row_path"


def test_ngay_sang_ngay_KHAC_van_chan_cung():
    o = dict(BASE, period_end="2014-12-31", period_source="column_path")
    assert DA._reason(o, NEW, F) == "measured_value_changed_BLOCKING"


def test_kem_doi_gia_tri_do_duoc_thi_chan():
    assert DA._reason(BASE, dict(NEW, value_decimal_text="2"),
                      F) == "measured_value_changed_BLOCKING"


def test_kem_doi_dau_am_thi_chan():
    assert DA._reason(BASE, dict(NEW, is_negative=1),
                      F) == "measured_value_changed_BLOCKING"


def test_thieu_co_production_thi_khong_duoc_mien():
    """Miễn trừ phải do CHÍNH production khai, không phải do audit suy đoán."""
    assert DA._reason(BASE, dict(NEW, quality_flags_json='["period_unresolved"]'),
                      F) == "measured_value_changed_BLOCKING"


def test_sai_period_source_thi_khong_duoc_mien():
    assert DA._reason(BASE, dict(NEW, period_source="table_context"),
                      F) == "measured_value_changed_BLOCKING"


def test_cohort_sai_o_ban_CU_thi_khong_duoc_mien():
    o = dict(BASE, period_source="column_path")
    assert DA._reason(o, NEW, F) == "measured_value_changed_BLOCKING"


def test_co_period_unresolved_PHAI_bien_mat():
    """Hình dạng thật, 21.428/21.438 ô: thêm `period_from_row_path`, mất
    `period_unresolved`."""
    assert DA._reason(BASE, NEW, F) == "period_recovered_from_row_path"


def test_hinh_dang_thu_hai_co_them_co_percent():
    """10/21.438 ô: ô vừa nhận kỳ vừa bị gắn cờ phần trăm bất hợp lý."""
    n = dict(NEW, quality_flags_json='["percent_value_implausible","period_from_row_path"]')
    assert DA._reason(BASE, n, F) == "period_recovered_from_row_path"


def test_van_giu_period_unresolved_thi_KHONG_duoc_mien():
    """Ô có kỳ mà vẫn khai "chưa giải được kỳ" là dữ liệu tự mâu thuẫn."""
    n = dict(NEW, quality_flags_json='["period_from_row_path","period_unresolved"]')
    assert DA._reason(BASE, n, F) == "measured_value_changed_BLOCKING"


def test_mat_co_KHAC_thi_khong_duoc_mien():
    o = dict(BASE, quality_flags_json='["period_unresolved","generic_row_label"]')
    assert DA._reason(o, NEW, F) == "measured_value_changed_BLOCKING"


def test_kem_doi_phan_loai_thi_khong_duoc_mien():
    assert DA._reason(BASE, dict(NEW, value_kind="percentage", unit_kind="percent"),
                      F) == "measured_value_changed_BLOCKING"


def test_kem_doi_nhan_ngu_nghia_thi_khong_duoc_mien():
    assert DA._reason(BASE, dict(NEW, row_path_text="r2"),
                      F) == "measured_value_changed_BLOCKING"


def test_truong_la_doi_kem_thi_khong_duoc_mien():
    o = dict(BASE, ticker="AAA")
    n = dict(NEW, ticker="BBB")
    assert DA._reason(o, n, list(o)) == "measured_value_changed_BLOCKING"


def test_truong_di_kem_ky_duoc_phep_doi():
    n = dict(NEW, period_type="instant", period_role="closing",
             as_of_date="2015-12-31", quarter=None, is_restated=0,
             period_start=None)
    o = dict(BASE, period_type="unknown", period_role="unknown",
             as_of_date=None, quarter=None, is_restated=0, period_start=None)
    assert DA._reason(o, n, list(o)) == "period_recovered_from_row_path"


def test_hai_co_moi_deu_da_duoc_khai():
    assert "percent_value_implausible" in DA.DECLARED_NEW_FLAGS
    assert "period_from_row_path" in DA.DECLARED_NEW_FLAGS
