"""RC2-036 · taxonomy differential: tách ĐO ĐƯỢC khỏi SUY RA.

Gộp chung là lý do một hồi quy phân loại nằm cùng rổ với "giá trị bị đổi", và
cả rổ chỉ có một con số. Trên bản dựng `4c86c9e43915694a`, 22.337 ca
`factual_changed_NEEDS_REVIEW` không nói được ca nào là đổi số, ca nào là đổi
nhãn — hoá ra 0 ca đổi số, nhưng phải đo mới biết.

Điểm mấu chốt của các lớp lý do mới: chúng mô tả trạng thái ĐÚNG. Đúng 20.197
ca hỏng của bản dựng đó vẫn KHÔNG khớp lớp nào và vẫn bị chặn.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_S = importlib.util.spec_from_file_location(
    "diff_audit_mod", ROOT / "tools" / "differential_audit.py")
da = importlib.util.module_from_spec(_S)
sys.modules["diff_audit_mod"] = da
_S.loader.exec_module(da)

FIELDS = ["value_decimal_text", "period_end", "is_negative", "value_kind",
          "unit_kind", "scale_exponent", "currency", "unit_kind_source",
          "scale_source", "currency_source", "quality_flags_json",
          "row_path_text"]


def _r(old: dict, new: dict) -> str:
    base = {f: None for f in FIELDS}
    return da._reason({**base, **old}, {**base, **new}, FIELDS)


# ── 1 · ĐO ĐƯỢC đổi = chặn cứng ───────────────────────────────────────────

@pytest.mark.parametrize("f,a,b", [
    ("value_decimal_text", "100", "200"),
    ("period_end", "2023-12-31", "2024-12-31"),
    ("is_negative", 0, 1),
])
def test_truong_DO_DUOC_doi_thi_chan_cung(f, a, b):
    assert _r({f: a}, {f: b}) == "measured_value_changed_BLOCKING"


def test_truong_DO_DUOC_thang_moi_lop_ly_do_khac():
    """Kể cả khi đi kèm một thay đổi phân loại hợp lệ, giá trị đổi vẫn thắng.
    Trước đây nó bị lớp `scale_reconciled` che mất."""
    assert _r({"value_decimal_text": "1", "scale_exponent": 0},
              {"value_decimal_text": "2", "scale_exponent": 6}) \
        == "measured_value_changed_BLOCKING"


def test_measured_nam_trong_danh_sach_chan():
    src = (ROOT / "tools" / "differential_audit.py").read_text(encoding="utf-8")
    i = src.index("blocking = {")
    assert "measured_value_changed" in src[i:i + 400]


# ── 2 · SUY RA đổi phải khớp lớp lý do đã khai ────────────────────────────

def test_HOI_QUY_THAT_van_bi_chan():
    """Đúng chữ ký 20.197 ca của `4c86c9e43915694a`: `value_kind` sang money,
    `unit_kind` giữ nguyên `rate`. Lớp lý do mới KHÔNG được tha ca này."""
    assert _r({"value_kind": "interest_rate", "unit_kind": "rate",
               "unit_kind_source": "cell"},
              {"value_kind": "money", "unit_kind": "rate",
               "unit_kind_source": "column_path"}) \
        == "factual_changed_NEEDS_REVIEW"


@pytest.mark.parametrize("uk_cu,uk_moi", [
    ("rate", "money"), ("shares", "money"), ("days", "money"),
])
def test_doi_DONG_BO_cung_ho_thi_hop_le(uk_cu, uk_moi):
    assert _r({"value_kind": "interest_rate", "unit_kind": uk_cu},
              {"value_kind": "money", "unit_kind": uk_moi}) \
        == "unit_reinferred_from_column_path"


def test_doi_LECH_ho_thi_van_chan():
    """`value_kind=money` + `unit_kind=shares` là mâu thuẫn, dù cả hai cùng đổi."""
    assert _r({"value_kind": "days", "unit_kind": "days"},
              {"value_kind": "money", "unit_kind": "shares"}) \
        == "factual_changed_NEEDS_REVIEW"


def test_value_kind_doi_mot_minh_ma_don_vi_van_nhat_quan_thi_hop_le():
    """`unknown` không mâu thuẫn với bất cứ gì — đó là "chưa xác định"."""
    assert _r({"value_kind": "interest_rate", "unit_kind": "unknown"},
              {"value_kind": "money", "unit_kind": "unknown"}) \
        == "unit_reinferred_from_column_path"


def test_scale_reconciled_giu_nguyen():
    assert _r({"scale_exponent": 0}, {"scale_exponent": 6}) == "scale_reconciled"


# ── 3 · nhãn chất lượng thêm theo luật ĐÃ KHAI ────────────────────────────

def test_nhan_da_khai_thi_hop_le():
    assert _r({"quality_flags_json": json.dumps(["period_from_table"])},
              {"quality_flags_json": json.dumps(
                  ["period_from_table", "tiny_money_legitimate"])}) \
        == "quality_flag_added_by_declared_rule"


def test_nhan_LA_thi_van_chan():
    """Nhãn ngoài danh sách = một luật lạ đang chạy mà không ai khai."""
    assert _r({"quality_flags_json": "[]"},
              {"quality_flags_json": json.dumps(["luat_bi_mat"])}) \
        == "out_of_contract_field_changed"


def test_MAT_nhan_cu_khong_phai_la_them_nhan():
    assert _r({"quality_flags_json": json.dumps(["period_from_table"])},
              {"quality_flags_json": json.dumps(["tiny_money_legitimate"])}) \
        == "out_of_contract_field_changed"


def test_truong_ngoai_hop_dong_khac_van_chan():
    assert _r({"unit_kind_source": "cell"},
              {"unit_kind_source": "column_path"}) \
        == "out_of_contract_field_changed"


# ── 4 · hai danh sách phải rời nhau và phủ hết FACTUAL cũ ─────────────────

def test_MEASURED_va_CLASSIFIED_roi_nhau_va_phu_het():
    assert set(da.MEASURED) & set(da.CLASSIFIED) == set()
    assert set(da.FACTUAL) == set(da.MEASURED) | set(da.CLASSIFIED)
    for f in ("value_decimal_text", "period_end", "is_negative"):
        assert f in da.MEASURED
    for f in ("value_kind", "unit_kind", "scale_exponent", "currency"):
        assert f in da.CLASSIFIED


# ── 5 · lớp SỬA CHỮA · chốt chặn là trạng thái MỚI phải nhất quán ─────────

def test_sua_chua_unit_kind_ve_nhat_quan_la_hop_le():
    """Hình dạng của bản vá RC2-036 khi hạ cánh: `value_kind` giữ nguyên
    `money`, `unit_kind` đi từ `rate` (mâu thuẫn) sang `money` (nhất quán)."""
    assert _r({"value_kind": "money", "unit_kind": "rate", "currency": None},
              {"value_kind": "money", "unit_kind": "money", "currency": "VND"}) \
        == "unit_kind_repaired_to_match_value_kind"


def test_sua_chua_ve_unknown_cung_la_nhat_quan():
    """`unknown` là "chưa xác định" — đúng định nghĩa C4-10 dùng trong gates."""
    assert _r({"value_kind": "money", "unit_kind": "count"},
              {"value_kind": "money", "unit_kind": "unknown"}) \
        == "unit_kind_repaired_to_match_value_kind"


def test_ban_ghi_VON_DA_DUNG_ma_bi_doi_don_vi_thi_VAN_CHAN():
    """Chốt chặn thật của lớp sửa chữa: trạng thái CŨ phải mâu thuẫn. Một bản
    ghi vốn đã nhất quán mà bị đổi đơn vị sang thứ khác KHÔNG được tha."""
    assert _r({"value_kind": "money", "unit_kind": "money"},
              {"value_kind": "money", "unit_kind": "unknown"}) \
        == "factual_changed_NEEDS_REVIEW"


def test_ket_thuc_o_trang_thai_MAU_THUAN_thi_khong_lop_nao_tha():
    for cu, moi in (
        ({"value_kind": "money", "unit_kind": "money"},
         {"value_kind": "money", "unit_kind": "rate"}),
        ({"value_kind": "days", "unit_kind": "days"},
         {"value_kind": "money", "unit_kind": "shares"}),
        ({"value_kind": "money", "unit_kind": "rate"},
         {"value_kind": "money", "unit_kind": "days"}),
    ):
        assert _r(cu, moi) == "factual_changed_NEEDS_REVIEW", (cu, moi)


def test_dinh_nghia_nhat_quan_KHOP_voi_C4_10_trong_gates():
    """Hai nơi phải dùng CÙNG một định nghĩa; lệch nhau là cổng và audit nói
    hai điều khác nhau về cùng một bản ghi."""
    g = (ROOT / "src" / "text2pandas" / "pipelines" / "a6" / "gates.py").read_text(encoding="utf-8")
    i = g.index('"C4-10"')
    sql = g[i:i + 400]
    assert "value_kind='money'" in sql
    assert "'money','unknown'" in sql
    for uk in (None, "", "unknown", "money"):
        assert da._consistent("money", uk) is True
    for uk in ("rate", "shares", "days", "count"):
        assert da._consistent("money", uk) is False


# ── 6 · nhãn ĐỔI TÊN đã khai ──────────────────────────────────────────────

def test_doi_ten_nhan_da_khai_thi_hop_le():
    """RC-04 mục 3 · `unit_assumed` -> `unit_scale_assumed_no_evidence`."""
    assert _r({"quality_flags_json": json.dumps(["period_from_table", "unit_assumed"])},
              {"quality_flags_json": json.dumps(
                  ["period_from_table", "unit_scale_assumed_no_evidence"])}) \
        == "quality_flag_renamed_by_declared_rule"


def test_MAT_nhan_khong_nam_trong_bang_doi_ten_thi_van_chan():
    assert _r({"quality_flags_json": json.dumps(["period_from_table", "unit_assumed"])},
              {"quality_flags_json": json.dumps(["unit_scale_assumed_no_evidence"])}) \
        == "out_of_contract_field_changed"


def test_bang_doi_ten_chi_co_cap_DA_KHAI():
    assert da._FLAG_RENAMES == {"unit_assumed": "unit_scale_assumed_no_evidence"}


# ── 7 · nguồn bằng chứng đổi mà giá trị không đổi ─────────────────────────

def test_scale_source_doi_ma_scale_khong_doi_thi_hop_le():
    assert _r({"scale_source": "cell", "scale_exponent": 6},
              {"scale_source": "column_path", "scale_exponent": 6}) \
        == "evidence_source_changed_same_value"


def test_scale_source_doi_KEM_scale_doi_thi_khong_phai_lop_nay():
    assert _r({"scale_source": "cell", "scale_exponent": 0},
              {"scale_source": "column_path", "scale_exponent": 6}) \
        == "scale_reconciled"


# ── 8 · nhiều trường ngoài hợp đồng cùng đổi ──────────────────────────────

def test_hai_truong_ngoai_hop_dong_deu_da_khai_thi_hop_le():
    """4 ca thật của `7aa8b4c22984bf5f`: `scale_source` đổi tầng bằng chứng
    (bậc 10 KHÔNG đổi) đồng thời với `quality_flags_json` thêm nhãn đã khai.
    Mỗi vế đều hợp lệ; trước đây tổ hợp vẫn bị chặn vì luật chỉ khớp khi có
    ĐÚNG một trường. Chặn vì "chưa xét tới" khác với chặn vì "có vấn đề"."""
    assert _r({"scale_source": "section_context", "scale_exponent": 6,
               "quality_flags_json": "[]"},
              {"scale_source": "column_path", "scale_exponent": 6,
               "quality_flags_json": json.dumps(["tiny_money_legitimate"])}) \
        == "out_of_contract_declared_changes"


def test_mot_truong_LA_di_kem_thi_ca_ban_ghi_van_chan():
    """Chốt chặn: chỉ cần MỘT trường không có vị từ nào nhận."""
    assert _r({"scale_source": "cell", "scale_exponent": 6,
               "unit_kind_source": "cell"},
              {"scale_source": "column_path", "scale_exponent": 6,
               "unit_kind_source": "column_path"}) \
        == "out_of_contract_field_changed"


def test_to_hop_co_nhan_LA_thi_van_chan():
    assert _r({"scale_source": "cell", "scale_exponent": 6,
               "quality_flags_json": "[]"},
              {"scale_source": "column_path", "scale_exponent": 6,
               "quality_flags_json": json.dumps(["luat_bi_mat"])}) \
        == "out_of_contract_field_changed"
