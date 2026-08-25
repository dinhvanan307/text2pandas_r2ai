"""A6 · manifest và build_meta phải nói cùng một điều.

Lỗi gốc: gói `5ade9ae9d5f68b6a` phát hành với
`manifest.readiness_policy_version = 2.1` trong khi
`build_meta.readiness_policy_version = 2.2`. Cùng tên khoá, hai giá trị, một
gói. Người nhận tra chính sách 2.1 sẽ đọc luật nói ô phần trăm không bao giờ
ready — ngược hẳn dữ liệu trong chính gói đó.

Nó sống sót vì hai lý do, và bộ test này đóng cả hai:
  1. luật nằm rải trong một dict 30 khoá, không gọi riêng được  -> tách hàm
  2. không cổng nào so manifest với build_meta                  -> thêm cổng
"""
import importlib.util as _u
from pathlib import Path

import pytest
import yaml

from text2pandas.pipelines.a6.release import READINESS_VERSION, _identity_from_build_meta

_sp = _u.spec_from_file_location(
    "_vp", Path(__file__).resolve().parents[1] / "tools" / "verify_package.py")
VP = _u.module_from_spec(_sp)
_sp.loader.exec_module(VP)

BM = {"source_commit": "abc123", "source_hash": "sh", "config_hash": "ch",
      "readiness_policy_version": "2.2"}


# ── luật lấy danh tính ───────────────────────────────────────────────────
def test_readiness_policy_version_lay_tu_build_meta_khong_phai_hang_so_module():
    """Đây CHÍNH LÀ lỗi. Hằng số module là 2.1; chính sách thật là 2.2."""
    got = _identity_from_build_meta(BM, {})["readiness_policy_version"]
    assert got == "2.2"
    assert got != READINESS_VERSION, (
        "hằng số module KHÔNG được thắng build_meta — đó là lỗi của gói "
        "5ade9ae9d5f68b6a")


@pytest.mark.parametrize("k", ["source_commit", "source_hash", "config_hash",
                               "readiness_policy_version"])
def test_moi_truong_danh_tinh_deu_uu_tien_build_meta(k):
    assert _identity_from_build_meta(BM, {})[k] == BM[k]


def test_vang_khoa_thi_moi_dung_phuong_an_du_phong():
    got = _identity_from_build_meta({}, {"source_hash": "x", "config_hash": "y"})
    assert got["readiness_policy_version"] == READINESS_VERSION
    assert got["source_hash"] == "x" and got["config_hash"] == "y"


def test_defect_taxonomy_version_doc_tu_tep_taxonomy():
    want = str(yaml.safe_load(
        open("configs/defect_taxonomy_v1.yaml", encoding="utf-8"))["taxonomy_version"])
    assert _identity_from_build_meta({}, {})["defect_taxonomy_version"] == want


def test_taxonomy_version_da_tang_khi_noi_dung_tang():
    """A5 thêm D-11 và D-12. Số phiên bản không đổi thì nó chỉ là trang trí."""
    d = yaml.safe_load(open("configs/defect_taxonomy_v1.yaml", encoding="utf-8"))
    assert {"D-11", "D-12"} <= set(d["defects"])
    assert str(d["taxonomy_version"]) != "1.0"


# ── cổng so hai nguồn ────────────────────────────────────────────────────
def test_cong_bat_dung_lech_that():
    lech = VP.manifest_vs_build_meta({"readiness_policy_version": "2.1"},
                                     {"readiness_policy_version": "2.2"})
    assert len(lech) == 1 and "readiness_policy_version" in lech[0]


def test_giong_nhau_thi_khong_bao():
    assert VP.manifest_vs_build_meta({"build_id": "x"}, {"build_id": "x"}) == []


def test_khong_bao_dong_gia_khi_mang_vs_chuoi_JSON():
    """`build_meta` lưu TEXT nên mảng ở đó là chuỗi JSON. Coi là lệch thì cổng
    đỏ mỗi lần chạy, và một cổng báo động giả là một cổng sắp bị tắt."""
    assert VP.manifest_vs_build_meta(
        {"blocked_gates": ["G3 Structure"]},
        {"blocked_gates": '["G3 Structure"]'}) == []


def test_khong_bao_dong_gia_khi_khac_thu_tu_khoa_trong_object():
    assert VP.manifest_vs_build_meta(
        {"x": {"a": 1, "b": 2}}, {"x": '{"b": 2, "a": 1}'}) == []


def test_so_ca_kieu_so_va_chuoi_cung_gia_tri():
    assert VP.manifest_vs_build_meta({"n": 1973}, {"n": "1973"}) == []


def test_khoa_chi_co_o_mot_ben_thi_khong_xet():
    assert VP.manifest_vs_build_meta({"chi_manifest": 1}, {"chi_bm": 2}) == []


def test_bao_nhieu_lech_thi_bao_bay_nhieu():
    lech = VP.manifest_vs_build_meta(
        {"a": "1", "b": "2", "c": "3"}, {"a": "9", "b": "2", "c": "8"})
    assert len(lech) == 2
