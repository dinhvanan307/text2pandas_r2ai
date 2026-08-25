"""P1-06 · C4 phải thi hành ĐỦ hợp đồng, kiểm HAI CHIỀU.

Khiếm khuyết: `configs/rc2_contracts_v1.yaml` khai 9 bất biến C4-01…C4-09,
`gates._gate_c4` chỉ đo 4 metric collision. Hợp đồng khai mà mã không thi hành
là loại khiếm khuyết im lặng nhất — không ai báo lỗi, chỉ là nó không kiểm gì.
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from data_pipeline.gates import _gate_c4  # noqa: E402

CONTRACT = yaml.safe_load(
    (ROOT / "configs" / "rc2_contracts_v1.yaml").read_text(encoding="utf-8"))
IDS = [i["id"] for i in CONTRACT["c4_gate"]["invariants"]]


def _db(**over) -> sqlite3.Connection:
    con = sqlite3.connect(":memory:")
    con.executescript("""
    CREATE TABLE observation_readiness(observation_uid TEXT, execution_ready INT,
      execution_candidate INT, confidence TEXT, blocking_reasons_json TEXT,
      warning_reasons_json TEXT, policy_version TEXT);
    CREATE TABLE collision_obs(observation_uid TEXT, group_uid TEXT,
      collision_class TEXT);
    CREATE TABLE collision_groups(group_uid TEXT, collision_class TEXT);
    CREATE TABLE quality_issues(issue_uid TEXT, rule_id TEXT);
    CREATE TABLE build_meta(key TEXT, value TEXT);
    CREATE TABLE observations(observation_uid TEXT, value_kind TEXT, unit_kind TEXT);
    """)
    con.execute("INSERT INTO build_meta VALUES('readiness_policy_version','2.1')")
    row = dict(observation_uid="o1", execution_ready=1, execution_candidate=1,
               confidence="high", blocking_reasons_json="[]",
               warning_reasons_json="[]", policy_version="2.1")
    row.update(over)
    con.execute("INSERT INTO observation_readiness VALUES(?,?,?,?,?,?,?)",
                tuple(row[k] for k in ("observation_uid", "execution_ready",
                                       "execution_candidate", "confidence",
                                       "blocking_reasons_json",
                                       "warning_reasons_json", "policy_version")))
    con.execute("INSERT INTO quality_issues VALUES('i1','Q-OBS-TINY-MONEY')")
    # C4-10 · dữ liệu sạch = ô TIỀN mang đơn vị TIỀN.
    con.execute("INSERT INTO observations VALUES('o1',?,?)",
                (over.get("value_kind", "money"), over.get("unit_kind", "money")))
    return con


def _metrics(con) -> dict:
    return {m.name: m for m in _gate_c4(con).metrics}


# ── hai chiều: hợp đồng ↔ mã ──────────────────────────────────────────────

def test_moi_bat_bien_trong_hop_dong_deu_co_metric():
    m = _metrics(_db())
    missing = [i for i in IDS if i not in m]
    assert not missing, f"hợp đồng khai nhưng mã KHÔNG thi hành: {missing}"


def test_khong_co_metric_C4_nao_ngoai_hop_dong():
    m = _metrics(_db())
    extra = [k for k in m if k.startswith("C4-") and k not in IDS]
    assert not extra, f"mã thi hành mã C4 không có trong hợp đồng: {extra}"


def test_hop_dong_du_muoi_bat_bien():
    """C4-10 vào ở RC2-036. Con số này chỉ được TĂNG, không được giảm: bỏ một
    bất biến là bỏ một lớp bảo vệ đã có lý do tồn tại bằng dữ liệu thật."""
    assert len(IDS) == 10 and IDS[0] == "C4-01" and IDS[-1] == "C4-10"


# ── mỗi bất biến phải BẮT ĐƯỢC vi phạm ────────────────────────────────────

@pytest.mark.parametrize("cid,over", [
    ("C4-01", {"execution_ready": 1, "execution_candidate": 0}),
    ("C4-02", {"confidence": "low"}),
    ("C4-03", {"blocking_reasons_json": '["period_unresolved"]'}),
    ("C4-05", {"warning_reasons_json": '["tiny_money_unresolved"]'}),
    ("C4-06", {"execution_ready": 0, "execution_candidate": 1,
               "blocking_reasons_json": "[]"}),
    ("C4-08", {"policy_version": "1.0"}),
])
def test_bat_duoc_vi_pham(cid, over):
    m = _metrics(_db(**over))
    assert m[cid].status == "FAIL", f"{cid} không bắt được vi phạm {over}"


def test_C4_04_bat_fact_mo_ho_vao_ready():
    con = _db()
    con.execute("INSERT INTO collision_obs VALUES('o1','g1','missing_dimension')")
    assert _metrics(con)["C4-04"].status == "FAIL"


def test_C4_09_bat_physical_duplicate_vao_ready():
    con = _db()
    con.execute("INSERT INTO collision_obs VALUES('o1','g1','physical_duplicate')")
    assert _metrics(con)["C4-09"].status == "FAIL"


def test_C4_07_bat_ma_rui_ro_khong_map_taxonomy():
    con = _db()
    con.execute("INSERT INTO quality_issues VALUES('i2','Q-KHONG-HE-KHAI')")
    assert _metrics(con)["C4-07"].status == "FAIL"


def test_du_lieu_sach_thi_moi_bat_bien_PASS():
    m = _metrics(_db())
    bad = [k for k, v in m.items() if k.startswith("C4-") and v.status != "PASS"]
    assert not bad, f"dữ liệu sạch mà vẫn FAIL: {bad}"


def test_C4_10_bat_duoc_o_TIEN_mang_don_vi_khac():
    """RC2-036 · 20.378 bản ghi `value_kind=money` + `unit_kind=rate/shares/days`
    đi lọt qua toàn bộ chín cổng C4 cũ. Bất biến này phải bắt được chúng."""
    assert _metrics(_db(unit_kind="rate"))["C4-10"].status == "FAIL"


def test_C4_10_KHONG_bat_don_vi_unknown():
    """`unknown` là "chưa xác định được" — trung thực, không mâu thuẫn."""
    assert _metrics(_db(unit_kind="unknown"))["C4-10"].status == "PASS"


# ── thiếu bảng phải BLOCKED, không được im lặng bỏ qua ────────────────────

def test_thieu_bang_thi_BLOCKED_chu_khong_bo_qua():
    con = sqlite3.connect(":memory:")
    con.executescript("CREATE TABLE build_meta(key TEXT, value TEXT);")
    m = _metrics(con)
    for cid in ("C4-01", "C4-02", "C4-03"):
        assert m[cid].status == "BLOCKED", f"{cid} phải BLOCKED khi thiếu bảng"
