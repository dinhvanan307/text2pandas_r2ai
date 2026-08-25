"""RC-19 · hợp đồng fixture replay — kiểm HÌNH DẠNG, không kiểm giá trị.

Giá trị kỳ vọng nằm ở `configs/replay_expected_v1.yaml`, chọn bằng review độc
lập trên RC1 release DB (read-only) qua `tools/pick_replay_fixtures.py`. Bộ
kiểm này KHÔNG mở DB — nó bảo vệ đúng một thứ: fixture không được lặng lẽ
tụt về trạng thái rỗng.

Vì sao cần: một tệp `TEMPLATE_FROZEN` với `expected` để trống vẫn parse được,
vẫn nằm trong repo, và vẫn tạo cảm giác RC-19 đã có bằng chứng. Đó chính là
trạng thái tệp này nằm suốt từ P3 đến RC-02.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FIXTURE = ROOT / "configs" / "replay_expected_v1.yaml"


@pytest.fixture(scope="module")
def spec():
    return yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))


def test_khong_con_o_trang_thai_TEMPLATE(spec):
    assert spec["status"] == "VALUES_FROZEN", (
        "TEMPLATE_FROZEN nghĩa là RC-19 chưa có bằng chứng nào để so")
    assert "open_item" not in spec


def test_du_muoi_ca_va_id_khong_trung(spec):
    ids = [c["id"] for c in spec["cases"]]
    assert len(ids) == 10
    assert len(set(ids)) == 10
    assert ids == sorted(ids), "thứ tự ca phải ổn định giữa hai lần đọc"


def test_moi_ca_deu_noi_duoc_KY_VONG_hoac_ABSTAIN(spec):
    """Không ca nào được phép vừa không abstain vừa không có giá trị kỳ vọng."""
    for c in spec["cases"]:
        blob = yaml.safe_dump(c, allow_unicode=True)
        has_expected = "expected" in blob
        assert has_expected, f"ca {c['id']} không nói được kỳ vọng lẫn abstain"
        if c.get("abstain") is not True:
            assert "value_decimal_text" in blob or "_decimal" in blob, (
                f"ca {c['id']} không abstain thì PHẢI có giá trị Decimal kỳ vọng")


def test_ca_abstain_KHONG_kem_gia_tri(spec):
    """Ca bắt buộc abstain mà vẫn kèm giá trị là mời người ta trả giá trị đó."""
    for c in spec["cases"]:
        if c.get("abstain") is True:
            assert "value_decimal_text" not in yaml.safe_dump(c, allow_unicode=True), (
                f"ca {c['id']} phải abstain nhưng vẫn kèm value — bỏ giá trị đi")


def test_evidence_db_dung_baseline_RC1(spec):
    assert spec["evidence_db_sha256"] == (
        "fe4e75ce9ada37c0eb8fa6ad82fe487c196e6ef7a3ecf288da5e436ce4e00eaa")
    assert "rc1_baseline" in spec["evidence_db"]


def test_selector_ton_tai_va_tat_dinh(spec):
    sel = ROOT / spec["selector"]
    assert sel.exists(), f"MISSING ARTIFACT: {spec['selector']}"
    src = sel.read_text(encoding="utf-8")
    assert "RANDOM()" not in src.upper(), "chọn ngẫu nhiên thì không lặp lại được"
    assert "ORDER BY" in src


def test_ca_10_that_su_la_ca_mo_ho(spec):
    c10 = next(c for c in spec["cases"] if c["id"] == "10")
    assert c10["abstain"] is True
    assert c10.get("collision_class"), "ca bắt buộc abstain phải nêu ĐÍCH DANH lý do"


# ── AMD-R01 · sửa MỘT giá trị gold, có bằng chứng, không mở rộng ─────────

def _spec_amd():
    import yaml
    return yaml.safe_load(
        (ROOT / "configs" / "replay_expected_v1.yaml").read_text(encoding="utf-8"))


def test_AMD_R01_duoc_ghi_trong_chinh_hop_dong():
    """Sửa gold là việc nặng nhất trong cả chuỗi acceptance. Nó phải nằm TRONG
    hợp đồng kèm bằng chứng, không phải trong một tài liệu bên cạnh — người đọc
    hợp đồng ba tháng nữa phải thấy ngay vì sao con số này khác RC1."""
    d = _spec_amd()
    amds = {a["id"]: a for a in d.get("amendments") or []}
    assert "AMD-R01" in amds, "sửa gold mà không khai amendment"
    a = amds["AMD-R01"]
    assert a["case"] == "05" and a["field"] == "scale_exponent"
    assert (a["from"], a["to"]) == ("0", "6")
    assert a["evidence"]["col_path_text"] == "31/12/2022Trieu VND"
    assert "khong_phai_fit_theo_output" in a


def test_ca_05_mang_dung_gia_tri_da_sua():
    d = _spec_amd()
    c5 = [c for c in d["cases"] if c["id"] == "05"][0]
    assert c5["expected_cells"][0]["expect"]["scale_exponent"] == "6"


def test_CHI_MOT_amendment_khong_duoc_mo_rong_am_tham():
    """Mỗi lần sửa gold phải là một quyết định riêng, có người ký. Danh sách
    này chỉ được dài ra khi có thêm một quyết định như thế — test đỏ là nhắc
    người sửa quay lại đọc quy tắc, không phải để chặn vĩnh viễn."""
    d = _spec_amd()
    assert len(d.get("amendments") or []) == 1


def test_hop_dong_van_dong_bang_va_du_10_ca():
    d = _spec_amd()
    assert d["status"] == "VALUES_FROZEN"
    assert len(d["cases"]) == 10
    assert d["contract_version"] == "2.2"


def test_khai_HAI_snapshot_theo_Doc52_5_1():
    """Sửa `configs/*.yaml` đổi `config_hash`. Doc 52 §5.1 đòi khai riêng
    snapshot của source-đã-build và snapshot của tool-đang-chạy-acceptance."""
    import json
    p = ROOT / "artifacts" / "rc2" / "source_snapshot" / "SNAPSHOT_DECLARATION.json"
    if not p.is_file():
        pytest.skip("MISSING ARTIFACT: SNAPSHOT_DECLARATION.json không có trong cây này")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["build_source_snapshot"]["config_hash"] == "bc0b52771f8a83e6"
    assert d["acceptance_tool_snapshot"]["config_hash"] != "bc0b52771f8a83e6"
    # Bằng chứng mạnh nhất: KHÔNG một dòng semantic transform nào bị đụng.
    assert d["src_unchanged_since_build"] is True
    assert d["acceptance_tool_snapshot"]["changed_vs_build"]["source_hash"] is False
