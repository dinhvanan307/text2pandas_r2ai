"""RC-15 (cổng C1 no-loss) và RC-18 (sổ đăng ký ca chưa giải quyết).

Nguyên tắc của bộ test này: mỗi kiểm phải **hỏng đúng chỗ** khi ta cố tình
làm hỏng dữ liệu. Một test chỉ chứng minh "chạy không lỗi" thì không chứng
minh cổng có tác dụng.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NO_LOSS = ROOT / "tools" / "no_loss_check.py"
REGISTRY = ROOT / "tools" / "unresolved_registry.py"
INVENTORY = ROOT / "configs" / "rule_inventory_v1.yaml"


def _run(script: Path, *args: str) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(script), *args],
                       capture_output=True, text=True, cwd=str(ROOT))
    return p.returncode, p.stdout + p.stderr


def _make_db(path: Path, *, unaccounted=0, overlap=0, non_digit=0,
             dup_obs=0, slim=False, no_reason=0) -> Path:
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript("""
    CREATE TABLE source_cells(source_cell_uid TEXT PRIMARY KEY, table_uid TEXT,
                              text_clean TEXT);
    CREATE TABLE grid_cells(table_uid TEXT, grid_row_idx INT, grid_col_idx INT,
                            source_cell_uid TEXT, is_span_anchor INT);
    CREATE TABLE observations(observation_uid TEXT PRIMARY KEY, table_uid TEXT,
                              source_cell_uid TEXT);
    CREATE TABLE dropped_cells(source_cell_uid TEXT PRIMARY KEY, table_uid TEXT,
                               reason TEXT);
    CREATE TABLE tables(table_uid TEXT PRIMARY KEY, parse_status TEXT);
    CREATE TABLE quality_issues(issue_uid TEXT, scope_type TEXT, scope_uid TEXT,
                                severity TEXT, rule_id TEXT, message TEXT,
                                details_json TEXT);
    """)
    con.execute("INSERT INTO tables VALUES('T1','ok')")
    n = 0

    def cell(txt: str, kind: str | None, anchor: int = 1) -> str:
        nonlocal n
        n += 1
        uid = f"c{n}"
        con.execute("INSERT INTO source_cells VALUES(?,?,?)", (uid, "T1", txt))
        con.execute("INSERT INTO grid_cells VALUES('T1',?,0,?,?)",
                    (n, uid, anchor))
        if kind == "obs":
            con.execute("INSERT INTO observations VALUES(?,?,?)",
                        (f"o{n}", "T1", uid))
        elif kind == "drop":
            con.execute("INSERT INTO dropped_cells VALUES(?,?,?)",
                        (uid, "T1", "parse_not_a_number"))
        return uid

    for i in range(5):
        cell(f"1{i}00", "obs")
    for i in range(3):
        cell(f"2{i}00", "drop")
    cell("Tổng cộng", None)          # không chữ số → không thuộc U_digit
    cell("4500", None, anchor=0)     # có chữ số nhưng KHÔNG phải anchor → loại

    for i in range(unaccounted):     # có chữ số, không xử lý → MẤT
        cell(f"9{i}99", None)
    for i in range(non_digit):       # xử lý ô không có chữ số
        uid = cell("Chỉ tiêu", None)
        con.execute("INSERT INTO observations VALUES(?,?,?)",
                    (f"x{i}", "T1", uid))
    for i in range(overlap):         # vừa giữ vừa bỏ
        uid = cell(f"3{i}00", "obs")
        con.execute("INSERT INTO dropped_cells VALUES(?,?,?)",
                    (uid, "T1", "trùng"))
    for i in range(dup_obs):         # một ô sinh hai observation
        uid = cell(f"7{i}00", "obs")
        con.execute("INSERT INTO observations VALUES(?,?,?)",
                    (f"d{i}", "T1", uid))
    for i in range(no_reason):
        uid = cell(f"8{i}00", None)
        con.execute("INSERT INTO dropped_cells VALUES(?,?,?)", (uid, "T1", "  "))

    con.commit()
    if slim:
        con.executescript("DROP TABLE source_cells; DROP TABLE grid_cells;")
        con.commit()
    con.close()
    return path


def _report(tmp_path: Path, db: Path, *extra: str) -> tuple[int, dict]:
    rep = tmp_path / "c1.json"
    code, _ = _run(NO_LOSS, "--db", str(db), "--report", str(rep), *extra)
    return code, json.loads(rep.read_text(encoding="utf-8"))


def _chk(rep: dict, cid: str) -> dict:
    return next(c for c in rep["checks"] if c["id"] == cid)


# ── RC-15 · cổng C1 ────────────────────────────────────────────────────────

def test_C1_du_lieu_sach_thi_PASS(tmp_path):
    db = _make_db(tmp_path / "clean.db")
    code, rep = _report(tmp_path, db)
    assert code == 0
    assert rep["summary"]["verdict"] == "PASS"
    assert rep["summary"]["n_fail"] == 0


def test_C1_o_so_bien_mat_thi_C1_07_FAIL(tmp_path):
    db = _make_db(tmp_path / "loss.db", unaccounted=2)
    code, rep = _report(tmp_path, db)
    assert code == 1, "mất dữ liệu mà không FAIL là cổng vô dụng"
    assert _chk(rep, "C1-07")["status"] == "FAIL"
    assert _chk(rep, "C1-07")["value"] == 2


def test_C1_o_vua_giu_vua_bo_thi_C1_03_FAIL(tmp_path):
    db = _make_db(tmp_path / "ov.db", overlap=1)
    code, rep = _report(tmp_path, db)
    assert code == 1
    assert _chk(rep, "C1-03")["status"] == "FAIL"


def test_C1_xu_ly_o_khong_co_chu_so_thi_C1_08_FAIL(tmp_path):
    db = _make_db(tmp_path / "ex.db", non_digit=3)
    code, rep = _report(tmp_path, db)
    assert code == 1
    assert _chk(rep, "C1-08")["status"] == "FAIL"
    assert _chk(rep, "C1-08")["value"] == 3


def test_C1_mot_o_sinh_hai_observation_thi_C1_02_FAIL(tmp_path):
    db = _make_db(tmp_path / "dup.db", dup_obs=2)
    code, rep = _report(tmp_path, db)
    assert code == 1
    assert _chk(rep, "C1-02")["status"] == "FAIL"


def test_C1_o_bi_bo_khong_co_ly_do_thi_C1_04_FAIL(tmp_path):
    db = _make_db(tmp_path / "nr.db", no_reason=2)
    code, rep = _report(tmp_path, db)
    assert code == 1
    assert _chk(rep, "C1-04")["status"] == "FAIL"


def test_C1_o_KHONG_phai_span_anchor_khong_bi_tinh_la_mat(tmp_path):
    """Ô gộp có bản sao mang chữ số; chỉ anchor mới sinh observation.

    Nếu công cụ quên điều kiện anchor, bản sao sẽ trông như dữ liệu bị mất.
    """
    db = _make_db(tmp_path / "anchor.db")
    code, rep = _report(tmp_path, db)
    assert code == 0
    assert _chk(rep, "C1-07")["value"] == 0


def test_C1_tren_DB_slim_phai_BLOCKED_chu_KHONG_duoc_PASS(tmp_path):
    """Đây là bẫy nguy hiểm nhất: DB slim thiếu source_cells, mọi mệnh đề
    cốt lõi không đo được. Trả PASS ở đây là tuyên bố sai."""
    db = _make_db(tmp_path / "slim.db", slim=True)
    code, rep = _report(tmp_path, db)
    assert code == 2
    assert rep["summary"]["verdict"] == "BLOCKED"
    assert rep["summary"]["verdict"] != "PASS"
    assert set(rep["summary"]["core_blocked"]) >= {"C1-07", "C1-08", "C1-09"}
    assert "why_blocked" in rep["summary"]


def test_C1_slim_van_kiem_duoc_cac_bat_bien_KHONG_can_source_cells(tmp_path):
    db = _make_db(tmp_path / "slim2.db", overlap=1, slim=True)
    code, rep = _report(tmp_path, db)
    assert code == 1, "C1-03 vẫn đo được trên slim nên phải FAIL, không BLOCKED"
    assert _chk(rep, "C1-03")["status"] == "FAIL"


def test_C1_KHONG_ghi_gi_vao_DB_dau_vao(tmp_path):
    db = _make_db(tmp_path / "ro.db")
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    _report(tmp_path, db)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


def test_C1_dem_bang_nhau_KHONG_du_de_ket_luan(tmp_path):
    """|U_obs|+|U_drop| == |U_digit| nhưng hai tập vẫn khác nhau.

    Bỏ 1 ô số khỏi xử lý, đồng thời xử lý thêm 1 ô không có chữ số → lực lượng
    vẫn khớp, nhưng tập thì không. C1-09 sẽ xanh; C1-07/08 phải đỏ.
    """
    db = _make_db(tmp_path / "trap.db", unaccounted=1, non_digit=1)
    code, rep = _report(tmp_path, db)
    assert _chk(rep, "C1-09")["value"] == 0, "bẫy chưa dựng đúng"
    assert _chk(rep, "C1-09")["status"] == "PASS"
    assert _chk(rep, "C1-07")["status"] == "FAIL"
    assert _chk(rep, "C1-08")["status"] == "FAIL"
    assert code == 1


# ── RC-18 · sổ đăng ký ────────────────────────────────────────────────────

def _registry(tmp_path: Path, db: Path, *extra: str) -> tuple[int, dict]:
    rep = tmp_path / "reg.json"
    code, _ = _run(REGISTRY, "--db", str(db), "--inventory", str(INVENTORY),
                   "--report", str(rep), *extra)
    return code, json.loads(rep.read_text(encoding="utf-8"))


def _cat(rep: dict, name: str) -> dict:
    return next(c for c in rep["categories"] if c["category"] == name)


def test_registry_dem_o_bi_bo_chinh_xac(tmp_path):
    db = _make_db(tmp_path / "r1.db")
    _, rep = _registry(tmp_path, db)
    c = _cat(rep, "dropped_cell:parse_not_a_number")
    assert c["total"] == 3
    assert c["total_is_exact"] is True


def test_registry_readiness_BLOCKED_khi_thieu_bang(tmp_path):
    db = _make_db(tmp_path / "r2.db")
    code, rep = _registry(tmp_path, db)
    assert _cat(rep, "readiness:*")["status"] == "BLOCKED"
    assert code == 2, "còn nhóm BLOCKED thì exit phải khác 0"


def test_registry_chi_lay_rule_CHUA_giai_quyet(tmp_path):
    """Rule có consequence `warning` là đã gắn cờ nhưng vẫn dùng được —
    không được đưa vào sổ ca chưa giải quyết."""
    db = _make_db(tmp_path / "r3.db")
    _, rep = _registry(tmp_path, db)
    names = {c["category"] for c in rep["categories"]}
    assert "rule:Q-COL-PERIOD-UNRESOLVED" in names   # non_candidate
    assert "rule:Q-TAB-NO-HEADER" not in names       # warning
    assert "rule:Q-OBS-GENERIC-LABEL" not in names   # warning_conditional


def test_registry_KHAI_BAO_mau_bi_cat_chu_khong_im_lang(tmp_path):
    """quality_issues bị cắt ở sample_limit. Nếu công cụ báo `sampled` như
    thể là tổng, con số sai tới 40 lần trên RC1."""
    db = _make_db(tmp_path / "r4.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE quality_rule_totals(rule_id TEXT,"
                " total_count INT, sampled_count INT, sample_limit INT)")
    con.execute("INSERT INTO quality_rule_totals"
                " VALUES('Q-COL-ROLE-UNKNOWN',121407,5000,5000)")
    con.commit()
    con.close()
    _, rep = _registry(tmp_path, db)
    c = _cat(rep, "rule:Q-COL-ROLE-UNKNOWN")
    assert c["total"] == 121407, "phải lấy tổng thật, không phải số mẫu"
    assert c["sampled_in_db"] == 5000
    assert c["sampled_is_truncated"] is True
    assert rep["summary"]["n_truncated_sample_categories"] >= 1
    assert "truncation_warning" in rep["summary"]


def test_registry_khai_bao_tran_xuat_CSV(tmp_path):
    db = _make_db(tmp_path / "r5.db")
    con = sqlite3.connect(db)
    for i in range(12):
        con.execute("INSERT INTO quality_issues VALUES(?,?,?,?,?,?,?)",
                    (f"i{i}", "observation", f"u{i}", "warning",
                     "Q-COL-PERIOD-UNRESOLVED", "", "{}"))
    con.execute("CREATE TABLE quality_rule_totals(rule_id TEXT,"
                " total_count INT, sampled_count INT, sample_limit INT)")
    con.execute("INSERT INTO quality_rule_totals"
                " VALUES('Q-COL-PERIOD-UNRESOLVED',12,12,5000)")
    con.commit()
    con.close()
    csv_path = tmp_path / "cases.csv"
    _, rep = _registry(tmp_path, db, "--cases", str(csv_path),
                       "--max-cases-per-category", "5")
    c = _cat(rep, "rule:Q-COL-PERIOD-UNRESOLVED")
    assert c["exported"] == 5
    assert c["export_cap"] == 5
    assert c["export_truncated"] is True
    assert "KHÔNG phải tổng số ca" in c["export_note"]
    assert csv_path.exists()


def test_registry_KHONG_ghi_gi_vao_DB_dau_vao(tmp_path):
    db = _make_db(tmp_path / "r6.db")
    before = hashlib.sha256(db.read_bytes()).hexdigest()
    _registry(tmp_path, db)
    assert hashlib.sha256(db.read_bytes()).hexdigest() == before


def test_registry_gop_phan_du_tiny_money_RC03(tmp_path):
    db = _make_db(tmp_path / "r7.db")
    summ = tmp_path / "tm.json"
    summ.write_text(json.dumps({
        "denominator": 2836, "unclassified_count": 137,
        "ran_on_full_cohort": True,
        "class_counts": {"parse_or_column_role_unresolved": 137},
    }), encoding="utf-8")
    _, rep = _registry(tmp_path, db, "--tiny-money-summary", str(summ))
    c = _cat(rep, "tiny_money_residual")
    assert c["total"] == 137
    assert c["total_is_exact"] is True


def test_ca_hai_cong_cu_deu_co_trong_repo():
    assert NO_LOSS.exists(), "MISSING ARTIFACT: tools/no_loss_check.py"
    assert REGISTRY.exists(), "MISSING ARTIFACT: tools/unresolved_registry.py"


def test_registry_rule_vang_mat_khoi_totals_la_0_CHINH_XAC(tmp_path):
    """quality_rule_totals là nguồn đầy đủ. Rule không có dòng nào ở đó nghĩa
    là 0 ca — con số chính xác, KHÔNG được gắn nhãn ước lượng."""
    db = _make_db(tmp_path / "r8.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE quality_rule_totals(rule_id TEXT,"
                " total_count INT, sampled_count INT, sample_limit INT)")
    con.execute("INSERT INTO quality_rule_totals"
                " VALUES('Q-COL-ROLE-UNKNOWN',121407,5000,5000)")
    con.commit()
    con.close()
    _, rep = _registry(tmp_path, db)
    c = _cat(rep, "rule:Q-TAB-PARSE-FAIL")     # không có trong totals
    assert c["total"] == 0
    assert c["total_is_exact"] is True, "0 từ nguồn đầy đủ là chính xác"


def test_registry_khong_co_totals_thi_KHONG_duoc_noi_la_chinh_xac(tmp_path):
    """Chỉ có quality_issues (đã cắt mẫu) thì mọi con số phải bị đánh dấu
    là không chính xác — kể cả số 0."""
    db = _make_db(tmp_path / "r9.db")
    con = sqlite3.connect(db)
    con.execute("INSERT INTO quality_issues VALUES('i','observation','u',"
                "'warning','Q-COL-ROLE-UNKNOWN','','{}')")
    con.commit()
    con.close()
    _, rep = _registry(tmp_path, db)
    assert "CẮT MẪU" in rep["rule_totals_source"]
    assert _cat(rep, "rule:Q-COL-ROLE-UNKNOWN")["total_is_exact"] is False


# ── RC2-016 · AMD-03 corpus_id scope ──────────────────────────────────────

def test_AMD03_corpus_id_scope_da_duoc_chot_trong_hop_dong():
    """Quyết định giữ nguyên scope `corpus_id` phải nằm trong hợp đồng kèm
    rủi ro đã nhận và mốc xét lại — không được là quyết định miệng."""
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(
        (ROOT / "configs" / "rc2_contracts_v1.yaml").read_text(encoding="utf-8"))
    amd = {a["id"]: a for a in doc["amendments"]}
    assert "AMD-03" in amd, "RC2-016 chưa được chốt vào hợp đồng"
    a = amd["AMD-03"]
    assert a["decision"] == "GIU_NGUYEN_SCOPE_VA_KHAI_RUI_RO"
    assert a["open_issue"] == "RC2-016"
    assert a["revisit_at"] == "RC3"
    for k in ("finding", "why_it_matters", "decision_rationale",
              "risk_accepted", "mitigation"):
        assert a.get(k), f"AMD-03 thiếu trường bắt buộc: {k}"
    assert any("1973" in m for m in a["mitigation"]), \
        "phải có biện pháp kiểm corpus_file_count"


# ── B0-05 · schema quality_issues khác nhau giữa build DB và release DB ────

def _mk_qi_db(path: Path, entity_col: str) -> Path:
    """`quality_issues` dùng `scope_uid` ở build DB, `entity_id` ở release DB."""
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript(f"""
    CREATE TABLE quality_issues(issue_uid TEXT PRIMARY KEY, entity_type TEXT,
      {entity_col} TEXT NOT NULL, severity TEXT, rule_id TEXT, message TEXT,
      details_json TEXT);
    CREATE TABLE quality_rule_totals(rule_id TEXT, total_count INT,
      sampled_count INT, sample_limit INT);
    CREATE TABLE dropped_cells(source_cell_uid TEXT PRIMARY KEY, table_uid TEXT,
      reason TEXT);
    CREATE TABLE tables(table_uid TEXT PRIMARY KEY, parse_status TEXT);
    """)
    rows = [("Q-COL-ROLE-UNKNOWN", "E1"), ("Q-COL-ROLE-UNKNOWN", "E2"),
            ("Q-OBS-SCALE-REJECTED", "E1"), ("Q-OBS-SCALE-REJECTED", "E3")]
    for i, (rid, uid) in enumerate(rows):
        con.execute(
            f"INSERT INTO quality_issues(issue_uid,entity_type,{entity_col},"
            "severity,rule_id,message,details_json) VALUES(?,?,?,?,?,?,?)",
            (f"i{i}", "observation", uid, "warning", rid, "", "{}"))
    con.execute("INSERT INTO quality_rule_totals VALUES('Q-COL-ROLE-UNKNOWN',2,2,5000)")
    con.execute("INSERT INTO quality_rule_totals VALUES('Q-OBS-SCALE-REJECTED',2,2,5000)")
    con.execute("INSERT INTO dropped_cells VALUES('d1','T','header_row')")
    con.commit()
    con.close()
    return path


@pytest.mark.parametrize("entity_col", ["scope_uid", "entity_id"])
def test_registry_chay_duoc_tren_CA_HAI_schema(tmp_path, entity_col):
    """B0-05: bản trước hard-code `scope_uid`; chạy trên release DB thì 16 nhóm
    báo `no such column` mà công cụ VẪN trả exit 0 và evidence ghi PASS."""
    db = _mk_qi_db(tmp_path / f"{entity_col}.db", entity_col)
    code, rep = _registry(tmp_path, db, "--cases", str(tmp_path / "c.csv"))
    assert rep["entity_column_used"] == entity_col
    assert rep["summary"]["n_query_errors"] == 0, "không được có lỗi truy vấn"
    assert code != 3, "exit 3 nghĩa là số liệu không dùng được"


def test_loi_truy_van_lam_EXIT_KHAC_0_chu_khong_phai_ghi_chu(tmp_path):
    """Lỗi truy vấn là lỗi THỰC THI. Nuốt nó vào note rồi trả exit 0 chính là
    cách một evidence PASS giả được sinh ra."""
    db = _mk_qi_db(tmp_path / "x.db", "entity_id")
    con = sqlite3.connect(db)
    con.execute("ALTER TABLE quality_issues RENAME COLUMN entity_id TO wat")
    con.commit()
    con.close()
    code, rep = _registry(tmp_path, db, "--cases", str(tmp_path / "c.csv"))
    assert rep["entity_column_used"] is None
    assert code != 0, "schema lạ mà vẫn exit 0 là false-positive"


def test_occurrence_KHAC_so_entity_distinct(tmp_path):
    """4 lượt xuất hiện trên 3 entity: E1 dính hai rule. Cộng dồn theo nhóm
    KHÔNG phải số entity — đó là lỗi đọc số 149.415."""
    db = _mk_qi_db(tmp_path / "ov.db", "entity_id")
    _, rep = _registry(tmp_path, db, "--cases", str(tmp_path / "c.csv"))
    s = rep["summary"]
    assert s["total_issue_occurrences_excl_dropped_cells"] == 4
    assert s["distinct_unresolved_entity_uids_FROM_SAMPLE_ONLY"] == 3
    ov = rep["distinct_entity_analysis"]["overlap"]
    assert ov["entities_in_2plus_rules"] == 1
