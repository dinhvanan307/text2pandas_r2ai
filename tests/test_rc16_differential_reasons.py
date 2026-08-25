"""B0-03 · differential phải phân loại ĐỦ delta và chặn bằng exit code.

Ba khiếm khuyết bản cũ, mỗi cái một nhóm test:

1. `added` chỉ được đếm, không có lớp lý do.
2. Nhánh `unexplained` không thể tới vì vòng lặp `continue` khi mọi field
   FACTUAL+SEMANTIC bằng nhau → `unexplained_changed = 0` vô nghĩa.
3. Chỉ so 9 field; đổi ở cột ngoài danh sách không ai khai.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "differential_audit.py"

OBS_COLS = """observation_uid TEXT, source_cell_uid TEXT, table_uid TEXT,
    row_uid TEXT, column_uid TEXT, value_decimal_text TEXT, unit_kind TEXT,
    scale_exponent INTEGER, period_end TEXT, is_negative INTEGER,
    value_kind TEXT, row_path_text TEXT, col_path_text TEXT,
    metric_label_clean TEXT, confidence TEXT"""

DEFAULTS = dict(observation_uid="o1", source_cell_uid="c1", table_uid="T1",
                row_uid="r1", column_uid="k1", value_decimal_text="100",
                unit_kind="money", scale_exponent=0, period_end="2020-12-31",
                is_negative=0, value_kind="number", row_path_text="Doanh thu",
                col_path_text="2020", metric_label_clean="Doanh thu",
                confidence="high")


def _db(path: Path, rows: list[dict], *, dropped: list[str] = (),
        source_cells: list[str] = ()) -> Path:
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.execute(f"CREATE TABLE observations({OBS_COLS})")
    con.execute("CREATE TABLE dropped_cells(source_cell_uid TEXT, table_uid TEXT,"
                " reason TEXT)")
    con.execute("CREATE TABLE source_cells(source_cell_uid TEXT, table_uid TEXT,"
                " text_clean TEXT)")
    con.execute("CREATE TABLE build_meta(key TEXT, value TEXT)")
    con.execute("INSERT INTO build_meta VALUES('build_id',?)", (path.stem,))
    cols = list(DEFAULTS)
    for r in rows:
        v = {**DEFAULTS, **r}
        con.execute(f"INSERT INTO observations({','.join(cols)}) "
                    f"VALUES({','.join('?' * len(cols))})", [v[c] for c in cols])
    for u in dropped:
        con.execute("INSERT INTO dropped_cells VALUES(?,?,?)", (u, "T1", "header_row"))
    for u in source_cells:
        con.execute("INSERT INTO source_cells VALUES(?,?,?)", (u, "T1", "x"))
    con.commit()
    con.close()
    return path


def _run(tmp: Path, old: Path, new: Path) -> tuple[int, dict]:
    out = tmp / "rep"
    p = subprocess.run([sys.executable, str(TOOL), str(old), str(new), "-o", str(out)],
                       capture_output=True, text=True)
    rep = json.loads((out / "differential_audit.json").read_text(encoding="utf-8"))
    return p.returncode, rep


# ── 1 · added phải có lớp lý do ───────────────────────────────────────────

def test_added_co_lop_ly_do_khong_chi_dem(tmp_path):
    old = _db(tmp_path / "old.db", [{"source_cell_uid": "c1"}],
              source_cells=["c1", "c2"], dropped=["c2"])
    new = _db(tmp_path / "new.db", [{"source_cell_uid": "c1"},
                                    {"source_cell_uid": "c2", "observation_uid": "o2"}])
    code, rep = _run(tmp_path, old, new)
    assert rep["counts"]["added"] == 1
    assert rep["added_by_reason"].get("previously_dropped_now_parsed") == 1
    assert rep["added_by_reason"].get("unknown", 0) == 0
    assert code == 0


def test_added_khong_giai_thich_duoc_thi_CHAN(tmp_path):
    old = _db(tmp_path / "old.db", [{"source_cell_uid": "c1"}])
    new = _db(tmp_path / "new.db", [{"source_cell_uid": "c1"},
                                    {"source_cell_uid": "cZ", "observation_uid": "oZ"}])
    code, rep = _run(tmp_path, old, new)
    assert rep["added_by_reason"].get("unknown") == 1
    assert rep["verdict"] == "FAIL"
    assert code == 3, "added không rõ nguồn gốc mà vẫn exit 0 là cổng vô dụng"


def test_added_do_bang_moi(tmp_path):
    old = _db(tmp_path / "old.db", [{"source_cell_uid": "c1"}])
    new = _db(tmp_path / "new.db", [{"source_cell_uid": "c1"},
                                    {"source_cell_uid": "c9", "observation_uid": "o9",
                                     "table_uid": "T_NEW"}])
    _, rep = _run(tmp_path, old, new)
    assert rep["added_by_reason"].get("new_table") == 1


# ── 2 · unexplained phải có nghĩa ─────────────────────────────────────────

def test_ban_ghi_KHONG_doi_khong_bi_tinh_la_changed(tmp_path):
    old = _db(tmp_path / "old.db", [{"source_cell_uid": "c1"}])
    new = _db(tmp_path / "new.db", [{"source_cell_uid": "c1"}])
    _, rep = _run(tmp_path, old, new)
    assert rep["n_unchanged"] == 1
    assert rep["reason_accounting"]["changed"]["total"] == 0


def test_doi_cot_NGOAI_hop_dong_bi_khai_va_CHAN(tmp_path):
    """`confidence` không thuộc FACTUAL lẫn SEMANTIC. Bản cũ so 9 field nên đổi
    ở đây hoàn toàn vô hình."""
    old = _db(tmp_path / "old.db", [{"source_cell_uid": "c1", "confidence": "high"}])
    new = _db(tmp_path / "new.db", [{"source_cell_uid": "c1", "confidence": "low"}])
    code, rep = _run(tmp_path, old, new)
    assert rep["changed_by_reason"].get("out_of_contract_field_changed") == 1
    assert code == 3
    assert "confidence" in rep["compared_fields"]


# ── 3 · ba đẳng thức accounting ───────────────────────────────────────────

def test_ba_dang_thuc_accounting_dung(tmp_path):
    old = _db(tmp_path / "old.db",
              [{"source_cell_uid": "c1"},
               {"source_cell_uid": "c2", "observation_uid": "o2"}],
              source_cells=["c1", "c2", "c3"])
    new = _db(tmp_path / "new.db",
              [{"source_cell_uid": "c1", "metric_label_clean": "Doanh thu thuần"},
               {"source_cell_uid": "c3", "observation_uid": "o3"}],
              dropped=["c2"])
    _, rep = _run(tmp_path, old, new)
    acc = rep["reason_accounting"]
    assert acc["changed"]["reconciles"] and acc["added"]["reconciles"] \
        and acc["removed"]["reconciles"]
    assert acc["all_reconcile"] is True


def test_removed_co_ly_do_thi_KHONG_chan(tmp_path):
    old = _db(tmp_path / "old.db", [{"source_cell_uid": "c1"},
                                    {"source_cell_uid": "c2", "observation_uid": "o2"}])
    new = _db(tmp_path / "new.db", [{"source_cell_uid": "c1"}], dropped=["c2"])
    code, rep = _run(tmp_path, old, new)
    assert rep["removed_by_reason"].get("now_dropped_with_reason") == 1
    assert code == 0


def test_removed_khong_ly_do_thi_CHAN(tmp_path):
    old = _db(tmp_path / "old.db", [{"source_cell_uid": "c1"},
                                    {"source_cell_uid": "c2", "observation_uid": "o2"}])
    new = _db(tmp_path / "new.db", [{"source_cell_uid": "c1"}])
    code, rep = _run(tmp_path, old, new)
    assert rep["removed_by_reason"].get("unknown") == 1
    assert code == 3


def test_uid_khong_on_dinh_thi_CHAN(tmp_path):
    """Cùng ô nguồn mà row_uid đổi = công thức UID đã đổi = BREAKING."""
    old = _db(tmp_path / "old.db", [{"source_cell_uid": "c1", "row_uid": "r1"}])
    new = _db(tmp_path / "new.db", [{"source_cell_uid": "c1", "row_uid": "r_KHAC"}])
    code, rep = _run(tmp_path, old, new)
    assert rep["uid_instability"] == 1
    assert code == 3


def test_thay_doi_ngu_nghia_thuan_tuy_KHONG_chan(tmp_path):
    old = _db(tmp_path / "old.db", [{"source_cell_uid": "c1",
                                     "metric_label_clean": "Doanh thu"}])
    new = _db(tmp_path / "new.db", [{"source_cell_uid": "c1",
                                     "metric_label_clean": "Doanh thu thuần"}])
    code, rep = _run(tmp_path, old, new)
    assert rep["changed_by_reason"].get("semantic_enrichment") == 1
    assert code == 0, "enrichment ngữ nghĩa là hợp lệ, không được chặn"


def test_doi_gia_tri_that_thi_CHAN(tmp_path):
    old = _db(tmp_path / "old.db", [{"source_cell_uid": "c1",
                                     "value_decimal_text": "100"}])
    new = _db(tmp_path / "new.db", [{"source_cell_uid": "c1",
                                     "value_decimal_text": "999"}])
    code, rep = _run(tmp_path, old, new)
    # RC2-036 · giá trị ĐO ĐƯỢC bị đổi nay có lớp riêng, ngưỡng 0. Đây là siết
    # CHẶT hơn: trước đây nó nằm chung rổ với thay đổi phân loại, nên một ô đổi
    # số vô hình giữa 22.337 ca đổi nhãn đơn vị.
    assert rep["changed_by_reason"].get("measured_value_changed_BLOCKING") == 1
    assert rep["blocking_findings"].get("measured_value_changed") == 1
    assert code == 3
