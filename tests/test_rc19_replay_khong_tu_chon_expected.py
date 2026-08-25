"""B0-04 · replay không được tự chọn kỳ vọng từ output.

Khiếm khuyết bản cũ (audit 42 §B0-04): các hàm ca dùng `df.iloc[0]` chọn dòng
từ chính DB đang kiểm rồi truy vấn lại đúng dòng đó; `aggregation` và
`duplicate_label_with_dimension` trả `True` sau khi tự tính. Output sai vẫn
PASS.

Bộ test này khoá bốn tính chất:

1. Không còn `iloc[0]` trên dữ liệu chưa bị selector của hợp đồng ghim.
2. `--expected` là BẮT BUỘC.
3. DB có giá trị SAI → replay phải FAIL, không PASS.
4. Ca thiếu `expected` → ERROR, không phải SKIP.
"""
from __future__ import annotations

import ast
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "replay_report.py"
CONTRACT = ROOT / "configs" / "replay_expected_v1.yaml"

VIEW_COLS = ["doc_id", "table_uid", "row_uid", "column_uid", "observation_uid",
             "source_cell_uid", "evidence_ref", "metric_label_clean",
             "period_end", "value_source_raw", "value_decimal_text",
             "unit_kind", "currency", "scale_exponent", "row_path_text",
             "col_path_text", "execution_ready", "value", "value_raw"]

def _mod():
    """Nạp `replay_report` như một module để test hàm, không qua subprocess."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("replay_report_mod", TOOL)
    m = importlib.util.module_from_spec(spec)
    sys.modules["replay_report_mod"] = m
    spec.loader.exec_module(m)
    return m


ROW = {"doc_id": "D1", "table_uid": "T1", "row_uid": "R1", "column_uid": "K1",
       "observation_uid": "OBS1", "source_cell_uid": "SC1",
       "evidence_ref": "D1|line:10", "metric_label_clean": "Doanh thu",
       "period_end": "2020-12-31", "value_source_raw": "1.000",
       "value_decimal_text": "1000", "unit_kind": "money", "currency": "VND",
       "scale_exponent": "0", "row_path_text": "Doanh thu",
       "col_path_text": "2020", "execution_ready": "1", "value": "1000",
       "value_raw": "1.000"}


def _db(path: Path, rows: list[dict]) -> Path:
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE v_long_dataframe(%s)"
                % ",".join(f"{c} TEXT" for c in VIEW_COLS))
    for r in rows:
        v = {**ROW, **r}
        con.execute(f"INSERT INTO v_long_dataframe({','.join(VIEW_COLS)}) "
                    f"VALUES({','.join('?' * len(VIEW_COLS))})",
                    [v[c] for c in VIEW_COLS])
    con.commit()
    con.close()
    return path


def _contract(path: Path, cases: list[dict]) -> Path:
    import yaml
    path.write_text(yaml.safe_dump(
        {"contract_version": "test", "evidence_db": "rc1",
         "evidence_db_sha256": "deadbeef", "selector": "tools/pick_replay_fixtures.py",
         "cases": cases}, allow_unicode=True), encoding="utf-8")
    return path


def _run(db: Path, contract: Path, out: Path) -> tuple[int, dict]:
    p = subprocess.run([sys.executable, str(TOOL), str(db), "--expected",
                        str(contract), "-o", str(out)],
                       capture_output=True, text=True)
    f = out / "replay_report.json"
    rep = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else {}
    return p.returncode, rep


# ── 1 · không còn tự chọn dòng ────────────────────────────────────────────

def test_KHONG_con_iloc0_ngoai_vung_da_ghim():
    """Mỗi `iloc` phải nằm SAU khi selector của hợp đồng đã lọc còn đúng một
    dòng — và phải nói ra điều đó ngay tại chỗ."""
    src = TOOL.read_text(encoding="utf-8")
    tree = ast.parse(src)
    # Đếm trong MÃ THẬT, không đếm docstring/comment — bài học từ test 1973.
    hits = [n.lineno for n in ast.walk(tree)
            if isinstance(n, ast.Subscript)
            and isinstance(n.value, ast.Attribute) and n.value.attr == "iloc"]
    # Quy tắc KHÔNG phải "tối đa một", mà là: MỖI chỗ dùng iloc đều phải chứng
    # minh được dòng đã bị selector của hợp đồng ghim còn đúng một.
    lines = src.splitlines()
    unjustified = [n for n in hits
                   if "an toàn" not in lines[n - 1] and "đã bị selector" not in lines[n - 1]]
    assert not unjustified, \
        f"dùng .iloc[...] mà không chứng minh dòng đã bị ghim, ở dòng {unjustified}"


def test_khong_con_ham_tra_True_vo_dieu_kien():
    """`c_duplicate_label_dimension` bản cũ `return True` vô điều kiện."""
    tree = ast.parse(TOOL.read_text(encoding="utf-8"))
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        consts = [n.value for n in ast.walk(fn)
                  if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)]
        assert not any(c.value is True for c in consts if isinstance(c, ast.Constant)), \
            f"hàm {fn.name} trả True vô điều kiện"


# ── 2 · --expected bắt buộc ───────────────────────────────────────────────

def test_thieu_expected_thi_KHONG_chay(tmp_path):
    db = _db(tmp_path / "x.db", [{}])
    p = subprocess.run([sys.executable, str(TOOL), str(db), "-o", str(tmp_path)],
                       capture_output=True, text=True)
    assert p.returncode != 0
    assert "--expected" in (p.stderr + p.stdout)


# ── 3 · giá trị sai phải FAIL ─────────────────────────────────────────────

def test_DB_dung_gia_tri_thi_PASS(tmp_path):
    db = _db(tmp_path / "ok.db", [{}])
    c = _contract(tmp_path / "c.yaml", [{
        "id": "01", "name": "lookup", "doc_id": "D1", "table_uid": "T1",
        "row_uid": "R1", "column_uid": "K1",
        "expected": {"observation_uid": "OBS1", "value_decimal_text": "1000",
                     "period_end": "2020-12-31"}}])
    code, rep = _run(db, c, tmp_path / "o1")
    assert rep["passed"] == 1 and rep["failed"] == 0 and rep["errors"] == 0
    assert code == 0


def test_DB_SAI_gia_tri_thi_FAIL_chu_khong_PASS(tmp_path):
    """Đây là test then chốt: bản cũ tự lấy giá trị từ DB nên luôn PASS."""
    db = _db(tmp_path / "bad.db", [{"value_decimal_text": "9999"}])
    c = _contract(tmp_path / "c.yaml", [{
        "id": "01", "name": "lookup", "doc_id": "D1", "table_uid": "T1",
        "row_uid": "R1", "column_uid": "K1",
        "expected": {"value_decimal_text": "1000"}}])
    code, rep = _run(db, c, tmp_path / "o2")
    assert rep["failed"] == 1, "giá trị sai mà không FAIL là self-fulfilling test"
    assert "value_decimal_text" in rep["cases"][0]["mismatched_fields"]
    assert code == 3


def test_selector_khop_nhieu_dong_thi_FAIL(tmp_path):
    db = _db(tmp_path / "dup.db", [{}, {"observation_uid": "OBS2"}])
    c = _contract(tmp_path / "c.yaml", [{
        "id": "01", "name": "lookup", "table_uid": "T1", "row_uid": "R1",
        "expected": {"value_decimal_text": "1000"}}])
    code, rep = _run(db, c, tmp_path / "o3")
    assert rep["failed"] == 1
    assert "ĐÚNG MỘT ô" in rep["cases"][0]["trace"]
    assert code == 3


# ── 4 · thiếu expected là ERROR, không phải SKIP ──────────────────────────

def test_ca_thieu_expected_la_ERROR_khong_phai_SKIP(tmp_path):
    db = _db(tmp_path / "x.db", [{}])
    c = _contract(tmp_path / "c.yaml", [{
        "id": "03", "name": "growth", "table_uid": "T1"}])
    code, rep = _run(db, c, tmp_path / "o4")
    assert rep["errors"] == 1 and rep["skipped"] == 0
    assert code == 3, "ca không kiểm được mà exit 0 là cổng vô dụng"


def test_ca_abstain_ma_he_thong_TRA_LOI_thi_FAIL(tmp_path):
    db = _db(tmp_path / "a.db", [{"execution_ready": "1"}])
    c = _contract(tmp_path / "c.yaml", [{
        "id": "10", "name": "unresolved_must_abstain", "table_uid": "T1",
        "abstain": True, "abstain_reason": "kỳ chưa giải được"}])
    code, rep = _run(db, c, tmp_path / "o5")
    assert rep["failed"] == 1
    assert code == 3


def test_ca_abstain_dung_thi_PASS(tmp_path):
    db = _db(tmp_path / "a.db", [{"execution_ready": "0"}])
    c = _contract(tmp_path / "c.yaml", [{
        "id": "10", "name": "unresolved_must_abstain", "table_uid": "T1",
        "abstain": True, "abstain_reason": "kỳ chưa giải được"}])
    code, rep = _run(db, c, tmp_path / "o6")
    assert rep["passed"] == 1 and code == 0


def test_ca_abstain_thieu_reason_la_ERROR(tmp_path):
    db = _db(tmp_path / "a.db", [{"execution_ready": "0"}])
    c = _contract(tmp_path / "c.yaml", [{
        "id": "10", "name": "x", "table_uid": "T1", "abstain": True}])
    code, rep = _run(db, c, tmp_path / "o7")
    assert rep["errors"] == 1 and code == 3


# ── 5 · hợp đồng thật phải ghim vào RC1 ───────────────────────────────────

def test_hop_dong_that_ghim_vao_RC1():
    import yaml
    spec = yaml.safe_load(CONTRACT.read_text(encoding="utf-8"))
    assert spec["evidence_db"] == "artifacts/rc1_baseline/silver.db"
    assert spec["evidence_db_sha256"].startswith("fe4e75ce")
    assert len(spec["cases"]) == 10


# ── RC2-042 · hợp đồng và view gọi khác tên cùng một giá trị ──────────────

def test_alias_chi_THEM_khi_cot_hop_dong_VANG():
    """Không bao giờ ghi đè: nếu DB đã có cột đúng tên hợp đồng thì giữ nguyên,
    vì cột đó là nguồn gốc còn alias chỉ là cầu nối."""
    import pandas as pd
    m = _mod()
    df = pd.DataFrame({"row_label": ["A"], "metric_label_clean": ["GOC"],
                       "value": ["1"], "unit": ["money"], "scale": ["0"]})
    da = m.apply_view_aliases(df)
    assert df["metric_label_clean"].iloc[0] == "GOC"
    assert "metric_label_clean <- row_label" not in da
    assert df["value_decimal_text"].iloc[0] == "1"
    assert df["unit_kind"].iloc[0] == "money"


def test_evidence_ref_duoc_GHEP_chu_khong_doan():
    import pandas as pd
    m = _mod()
    df = pd.DataFrame({"doc_id": ["SCR_x"], "table_locator": ["line:849"]})
    m.apply_view_aliases(df)
    assert df["evidence_ref"].iloc[0] == "SCR_x|line:849"


def test_bang_alias_la_KHAI_BAO_khong_suy_doan_luc_chay():
    m = _mod()
    assert m.VIEW_ALIASES["value_decimal_text"] == "value"
    assert m.VIEW_ALIASES["unit_kind"] == "unit"
    assert m.VIEW_ALIASES["scale_exponent"] == "scale"
    assert m.VIEW_ALIASES["metric_label_clean"] == "row_label"


def test_report_ghi_RO_da_anh_xa_nhung_gi():
    src = (ROOT / "tools" / "replay_report.py").read_text(encoding="utf-8")
    assert '"view_aliases_applied": aliases' in src


# ── RC2-043 · abstain phải đo trên ĐÚNG quần thể mơ hồ ────────────────────

def _abstain_case(**over):
    c = {"id": "10", "name": "unresolved_must_abstain", "abstain": True,
         "table_uid": "T", "expected_abstain_reason": "fact mơ hồ phải bị từ chối",
         "collision_class": "missing_label_or_split"}
    c.update(over)
    return c


def _df(rows):
    import pandas as pd
    return pd.DataFrame(rows)


def test_dong_KHONG_mo_ho_duoc_phep_execution_ready():
    """Ca thật của `7aa8b4c22984bf5f`: bảng có 41 dòng, 14 mang collision_class,
    27 dòng ready — và ready ∩ collision = 0. Đếm ready trên cả 41 là đếm nhầm
    quần thể; 27 dòng kia là fact KHÔNG mơ hồ, chúng được phép trả lời."""
    m = _mod()
    df = _df([{"table_uid": "T", "collision_class": "missing_label_or_split",
               "execution_ready": "0"}] * 14
             + [{"table_uid": "T", "collision_class": None,
                 "execution_ready": "1"}] * 27)
    r = m._run_case(df, _abstain_case())
    assert r["status"] == "PASS", r
    assert r["n_rows_ambiguous"] == 14


def test_dong_MO_HO_ma_ready_thi_VAN_FAIL():
    """Chốt chặn thật: đúng một fact mơ hồ lọt vào execution_ready là đủ đỏ."""
    m = _mod()
    df = _df([{"table_uid": "T", "collision_class": "missing_label_or_split",
               "execution_ready": "1"}]
             + [{"table_uid": "T", "collision_class": None, "execution_ready": "1"}] * 27)
    r = m._run_case(df, _abstain_case())
    assert r["status"] == "FAIL"
    assert "MƠ HỒ" in r["trace"]


def test_fact_mo_ho_BIEN_MAT_thi_la_ERROR_khong_phai_PASS():
    """Không còn dòng nào mang lớp mơ hồ nghĩa là không kiểm được — im lặng
    cho PASS ở đây là biến cổng thành đồ trang trí."""
    m = _mod()
    df = _df([{"table_uid": "T", "collision_class": None, "execution_ready": "1"}] * 5)
    r = m._run_case(df, _abstain_case())
    assert r["status"] == "ERROR" and "biến mất" in r["reason"]


def test_khong_khai_collision_class_thi_giu_hanh_vi_cu():
    m = _mod()
    df = _df([{"table_uid": "T", "execution_ready": "1"}])
    r = m._run_case(df, _abstain_case(collision_class=None))
    assert r["status"] == "FAIL"


# ── RC2-044 · `0` và `0.0` là cùng một bậc 10 ─────────────────────────────

def test_so_nguyen_viet_dang_thap_phan_duoc_gop():
    """`scale` có NULL nên pandas nạp cả cột thành float64: `0` thành `0.0`.
    Tám trong mười ca của `7aa8b4c22984bf5f` FAIL chỉ vì dấu chấm đó."""
    m = _mod()
    assert m._norm("0.0") == "0"
    assert m._norm("6.000") == "6"
    assert m._norm("-3.0") == "-3"
    assert m._norm(0.0) == "0"


def test_KHONG_gop_so_co_phan_thap_phan_that():
    """Chuẩn hoá chỉ gộp hai cách VIẾT của cùng một số nguyên. `0.5` khác `0`."""
    m = _mod()
    assert m._norm("0.5") == "0.5"
    assert m._norm("1.05") == "1.05"
    assert m._norm("1e3") == "1e3"
    assert m._norm("0.0.0") == "0.0.0"


def test_cot_so_co_NULL_duoc_ep_chuoi_ngay_tu_SQL():
    """Ép ở tầng SQL, không phải `astype` sau khi nạp: đến lúc đó float64 đã
    sinh ra dấu chấm rồi, `astype("string")` chỉ đóng băng cái sai."""
    src = (ROOT / "tools" / "replay_report.py").read_text(encoding="utf-8")
    i = src.index("ep_chuoi = {")
    khoi = src[i:i + 400]
    for c in ("value", "value_raw", "scale", "row_idx", "col_idx"):
        assert f'"{c}"' in khoi, f"thiếu ép chuỗi cho {c}"
    assert "PRAGMA table_info(v_long_dataframe)" in src, (
        "phải chỉ khai dtype cho cột CÓ THẬT — pandas ném KeyError với khoá lạ")
    assert "dtype=ep_chuoi or None" in src
