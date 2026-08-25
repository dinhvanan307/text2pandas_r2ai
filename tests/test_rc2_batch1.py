"""Đợt 1 của RC2 — ba task chạm vào dữ liệu, khoá hành vi trước khi rebuild.

    RC-05  trùng nội dung tệp    → khai báo, KHÔNG loại
    RC-06  tám tài liệu phi bảng → phân loại, KHÔNG coi là lỗi parser
    RC-07  mojibake              → khôi phục CÓ CHỨNG MINH, không đoán

Ba task này gộp một tệp vì chúng chia chung một nguyên tắc: mỗi cái đều có một
phiên bản "làm cho gọn" hấp dẫn và sai — xoá tệp trùng, dựng bảng giả từ văn
xuôi, sửa dấu theo cảm giác. Test ở đây khoá đúng ranh giới đó.
"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from text2pandas.pipelines.a6.cleaning import (
    CLEAN_RULES, _SLOPPY_CP1252, clean_text, repair_mojibake)
from text2pandas.pipelines.a6.manifest import build_manifest, read_manifest, write_manifest
from text2pandas.pipelines.a6.storage import BRONZE_DDL, connect

# ════════════════════════ RC-07 · mojibake ════════════════════════

_INV = {v: k for k, v in _SLOPPY_CP1252.items()}


def _mojibake(s: str) -> str:
    """Mô phỏng đúng cách mojibake sinh ra: UTF-8 bị đọc bằng CP1252 dễ dãi."""
    return "".join(_INV[b] for b in s.encode("utf-8"))


_VIETNAMESE = [
    "Tiền và các khoản tương đương tiền",
    "Lợi nhuận sau thuế thu nhập doanh nghiệp",
    "Đơn vị tính: triệu đồng",
    "Chi phí quản lý doanh nghiệp",
    "Người lập biểu",
    "Vay và nợ thuê tài chính dài hạn",
]


@pytest.mark.parametrize("real", _VIETNAMESE)
def test_mojibake_roundtrip_is_exact(real):
    """Khôi phục phải trả về ĐÚNG chuỗi gốc, không phải một chuỗi gần giống."""
    assert repair_mojibake(_mojibake(real)) == real


@pytest.mark.parametrize("real", _VIETNAMESE)
def test_clean_text_records_c07(real):
    res = clean_text(_mojibake(real))
    assert res.text_clean == real
    assert "C07" in res.rules
    assert "C07" in CLEAN_RULES


@pytest.mark.parametrize("s", [
    "Tiền và các khoản tương đương tiền",   # tiếng Việt ĐÚNG — không được đụng
    "Đơn vị tính: triệu đồng",
    "Mã số", "M8 số", "20.559.756.794.837", "(1.234)", "-",
    "Nhiệt độ 40°C", "Chi phí « khác »", "Tỷ lệ ± 2%",
    "Résumé", "naïve", "Ø 12mm", "±", "©2024 ABC", "",
])
def test_no_false_positive_on_clean_text(s):
    """Chuỗi không phải mojibake phải đi qua C07 nguyên vẹn.

    Đây là test quan trọng nhất của luật này: một luật sửa chữ mà bắt nhầm
    còn tệ hơn không có luật, vì nó làm hỏng dữ liệu ĐANG đúng.
    """
    assert repair_mojibake(s) == s
    assert "C07" not in clean_text(s).rules


def test_double_encoded_is_fully_recovered():
    """Mã hoá sai hai lớp (`ÃƒÂ¡`) phải gỡ hết, không dừng ở giữa."""
    assert repair_mojibake(_mojibake(_mojibake("Tiền"))) == "Tiền"


def test_idempotent_after_repair():
    """`clean(clean(x)) == clean(x)` — bất biến của cả module, DI-04."""
    for real in _VIETNAMESE:
        once = clean_text(_mojibake(real)).text_clean
        assert clean_text(once).text_clean == once


def test_control_strip_runs_after_repair():
    """C06 chạy trước C07 sẽ XOÁ MẤT bằng chứng — khoá đúng thứ tự đó.

    `ề` là 0xE1 0xBB 0x81; byte 0x81 hiện ra thành ký tự điều khiển C1. Nếu
    C06 quét trước, chuỗi mất byte đó và không còn khôi phục được.
    """
    moji = _mojibake("Tiền")
    assert any(ord(c) < 0xA0 and ord(c) >= 0x7F for c in moji), (
        "ca thử không còn chứa ký tự C1 — test đã mất ý nghĩa")
    assert clean_text(moji).text_clean == "Tiền"


def test_sloppy_table_is_a_bijection():
    """Bảng CP1252 dễ dãi phải là song ánh, nếu không phép đảo mơ hồ."""
    assert len(_SLOPPY_CP1252) == 256
    assert len(set(_SLOPPY_CP1252.values())) == 256


def test_undefined_cp1252_bytes_are_covered():
    """Năm byte mà codec chuẩn từ chối — chính chúng làm bản đầu bó tay."""
    for b in (0x81, 0x8D, 0x8F, 0x90, 0x9D):
        assert _SLOPPY_CP1252[chr(b)] == b


# ════════════════════════ RC-05 · tệp trùng nội dung ════════════════════════


@pytest.fixture
def corpus(tmp_path: Path) -> Path:
    root = tmp_path / "vifinqa"
    fs = root / "financial_statements" / "SSH" / "2024"
    fs.mkdir(parents=True)
    body = "===== PAGE 1 =====\nBÁO CÁO\n<table><tr><td>a</td></tr></table>\n"
    (fs / "financial_statement_explanations_1.txt").write_text(body, encoding="utf-8")
    (fs / "financial_statement_explanations_2.txt").write_text(body, encoding="utf-8")
    (fs / "balance_sheet.txt").write_text(body + "khác\n", encoding="utf-8")
    return root


def test_duplicates_are_detected(corpus):
    man = build_manifest(corpus, "vifinqa", "r1")
    assert man.n_duplicate_files == 1          # ba tệp, một nhóm hai bản → 1 dư
    assert len(man.duplicate_groups) == 1
    g = man.duplicate_groups[0]
    assert len(g["files"]) == 2
    assert g["canonical"] == min(g["files"])


def test_duplicates_are_not_removed(corpus):
    """Khai báo, KHÔNG loại. Loại tệp làm lệch mọi số đếm mà cổng đang neo vào."""
    man = build_manifest(corpus, "vifinqa", "r1")
    assert man.n_files == 3
    assert sum(1 for f in man.files if f.duplicate_of) == 1
    assert sum(1 for f in man.files if not f.duplicate_of) == 2


def test_corpus_id_still_hashes_every_file(corpus):
    """`corpus_id` phải mô tả thứ ĐÃ NHẬN, kể cả phần trùng.

    Nếu khử trùng trước khi băm thì ID không còn nhận ra một corpus bị thêm
    hoặc bớt bản trùng — mà đó chính là loại thay đổi cần phát hiện.
    """
    man = build_manifest(corpus, "vifinqa", "r1")
    before = man.corpus_id
    (corpus / "financial_statements" / "SSH" / "2024"
     / "financial_statement_explanations_3.txt").write_text(
        (corpus / "financial_statements" / "SSH" / "2024"
         / "financial_statement_explanations_1.txt").read_text(encoding="utf-8"),
        encoding="utf-8")
    assert build_manifest(corpus, "vifinqa", "r1").corpus_id != before


def test_canonical_choice_is_deterministic(corpus):
    a = build_manifest(corpus, "vifinqa", "r1")
    b = build_manifest(corpus, "vifinqa", "r1")
    assert [f.duplicate_of for f in a.files] == [f.duplicate_of for f in b.files]


def test_manifest_roundtrip_keeps_duplicate_of(corpus, tmp_path):
    man = build_manifest(corpus, "vifinqa", "r1")
    p = tmp_path / "manifest.json"
    write_manifest(man, p)
    back = read_manifest(p)
    assert {f.rel_path: f.duplicate_of for f in back.files} == \
           {f.rel_path: f.duplicate_of for f in man.files}


def test_old_manifest_without_duplicate_of_still_reads(tmp_path):
    """Gói đã phát hành trước RC-05 vẫn phải mở được."""
    import json
    p = tmp_path / "old.json"
    p.write_text(json.dumps({
        "dataset": "vifinqa", "revision": "r0", "corpus_id": "sha256:x",
        "n_files": 1, "n_reports": 1, "n_bytes": 10,
        "files": [{"rel_path": "a.txt", "bytes": 10, "sha256": "h"}],
    }), encoding="utf-8")
    assert read_manifest(p).files[0].duplicate_of is None


# ════════════════════ RC-06 · tài liệu phi bảng ════════════════════


COLS = ("document_uid, literal_file_stem, directory_doc_id, ticker_path,"
        " year_path, basis_path, rel_path, n_bytes, n_lines, n_pages,"
        " n_tables, sha256, corpus_id, scan_status, discovery_status,"
        " n_table_markup, n_numeric_tokens, n_grouped_numbers")


@pytest.fixture
def bronze(tmp_path: Path) -> sqlite3.Connection:
    conn = connect(tmp_path / "bronze.sqlite", BRONZE_DDL, fresh=True)
    # Cột liệt kê TƯỜNG MINH. Chèn theo vị trí làm mọi fixture vỡ mỗi lần
    # schema thêm một cột append-only — và cái vỡ đó không nói lên điều gì về
    # hành vi đang kiểm.
    #
    # Ba tài liệu, ba trạng thái RC-06:
    #   D1 có bảng · D2 không markup (ngoài phạm vi) · D3 CÓ markup mà 0 bảng
    rows = [
        ("D1", "bs", "ABC_2024", "ABC", 2024, "consolidated",
         "ABC_2024/bs.txt", 100, 5, 1, 7, "h1", "c", "ok", "ok", 7, 400, 120),
        ("D2", "prt", "ABC_2024", "ABC", 2024, "consolidated",
         "ABC_2024/prt.txt", 80, 4, 1, 0, "h2", "c", "ok", "no_markup", 0, 150, 9),
        ("D3", "broken", "ABC_2024", "ABC", 2024, "consolidated",
         "ABC_2024/broken.txt", 90, 6, 1, 0, "h3", "c", "ok", "no_markup", 4, 300, 80),
    ]
    conn.executemany(
        "INSERT INTO documents (" + COLS + ") VALUES (" + ",".join("?" * 18) + ")",
        rows)
    conn.commit()
    return conn


def test_classification_view_exists_and_splits(bronze):
    """RC-06 bản 2 · BA trạng thái, không phải hai.

    `D3` là ca mà bản 1 KHÔNG THỂ nhìn thấy: văn bản gốc CÓ 4 chỗ mở thẻ bảng
    nhưng bộ phân tích không dựng được bảng nào. Bản 1 gộp nó chung với `D2`
    và dán nhãn `no_table_markup` — một lời khẳng định về văn bản gốc được suy
    ra từ kết quả phân tích, tức là sai cả về logic lẫn về sự thật.
    """
    got = dict(bronze.execute(
        "SELECT document_uid, document_kind FROM document_classification"))
    assert got == {"D1": "tabular", "D2": "non_tabular",
                   "D3": "tabular_parse_failed"}


def test_markup_co_ma_khong_ra_bang_la_LOI_chu_khong_phai_ngoai_pham_vi(bronze):
    row = bronze.execute(
        "SELECT table_exclusion_reason, retrieval_route"
        " FROM document_classification WHERE document_uid='D3'").fetchone()
    assert row == ("markup_present_but_no_table_parsed", "blocked_defect")


def test_tom_tat_noi_dung_so_phan_loai_duoc_theo_MAT_DO(bronze):
    """Người nhận gói phải tự trả lời được "bỏ tài liệu này ra thì mất gì"."""
    got = dict(bronze.execute(
        "SELECT document_uid, numeric_content FROM document_classification"))
    assert got == {"D1": "dense", "D2": "sparse", "D3": "dense"}


def test_moi_tai_lieu_khong_co_bang_deu_noi_duoc_LY_DO(bronze):
    """Bất biến review 28: `unclassified no-table document = 0`."""
    n = bronze.execute(
        "SELECT COUNT(*) FROM document_classification"
        " WHERE document_kind <> 'tabular'"
        "   AND table_exclusion_reason IS NULL").fetchone()[0]
    assert n == 0


def test_non_tabular_carries_reason_and_route(bronze):
    row = bronze.execute(
        "SELECT table_exclusion_reason, retrieval_route"
        " FROM document_classification WHERE document_uid='D2'").fetchone()
    assert row == ("no_table_markup", "explicit_out_of_scope")


def test_tabular_has_no_exclusion_reason(bronze):
    row = bronze.execute(
        "SELECT table_exclusion_reason, retrieval_route"
        " FROM document_classification WHERE document_uid='D1'").fetchone()
    assert row == (None, "table")


def test_classification_is_a_view_not_a_table(bronze):
    """Phải là VIEW. Ba cột lưu sẵn sẽ là nguồn sự thật thứ hai của `n_tables`."""
    kind = bronze.execute(
        "SELECT type FROM sqlite_master WHERE name='document_classification'"
    ).fetchone()
    assert kind == ("view",)


def test_view_follows_n_tables_without_rebuild(bronze):
    """Sửa `n_tables` là phân loại đổi theo ngay — đó là điểm của việc dùng view."""
    bronze.execute("UPDATE documents SET n_tables=3 WHERE document_uid='D2'")
    assert bronze.execute(
        "SELECT document_kind FROM document_classification"
        " WHERE document_uid='D2'").fetchone() == ("tabular",)


def test_no_table_document_is_not_counted_as_failure(bronze):
    """RC-06 nói rõ: KHÔNG coi tám tệp này là orphan FK hay parser failure."""
    from text2pandas.pipelines.a6.storage import integrity_check
    assert integrity_check(bronze) == []
    assert hashlib.sha256  # giữ import dùng thật ở fixture khác


# ════════════════ RC-13 · vân tay cấu hình đi vào `build_id` ════════════════


def test_fingerprint_hashes_the_directory_actually_used(tmp_path, monkeypatch):
    """`config_hash` phải phản ứng với `configs/` — thư mục pipeline THẬT SỰ đọc.

    Đo được trên build RC1 `b927c3e8f90aed74`: `config_hash` đã ghi vào
    `build_id` là `02ee1eeb3114c749`, băm của `config/` (số ít) — một thư mục
    chỉ chứa bản readiness policy v1.0 mà `load_policy` không bao giờ chọn.
    Băm đúng `configs/` cho `2e370bc63f795a1b`.

    Nghĩa là sửa ngưỡng trong `configs/vifinqa_silver_v1.yaml` KHÔNG đổi
    `build_id`. Test này khoá lại điều ngược lại.
    """
    from text2pandas.pipelines.a6 import storage
    root = tmp_path / "repo"
    (root / "src" / "text2pandas" / "pipelines" / "a6").mkdir(parents=True)
    (root / "pyproject.toml").write_text("[project]\nname='fixture'\n", encoding="utf-8")
    (root / "configs").mkdir()
    (root / "config").mkdir()
    (root / "src" / "text2pandas" / "pipelines" / "a6" / "x.py").write_text("# noop", encoding="utf-8")
    (root / "configs" / "a.yaml").write_text("threshold: 1\n", encoding="utf-8")
    (root / "config" / "old.yaml").write_text("legacy: true\n", encoding="utf-8")

    monkeypatch.setattr(storage, "__file__",
                        str(root / "src" / "text2pandas" / "pipelines" / "a6" / "storage.py"))
    before = storage.source_fingerprint()["config_hash"]

    # Sửa thư mục CHẾT → vân tay KHÔNG được đổi.
    (root / "config" / "old.yaml").write_text("legacy: false\n", encoding="utf-8")
    assert storage.source_fingerprint()["config_hash"] == before, (
        "`config/` (số ít) không được ảnh hưởng tới build_id")

    # Sửa thư mục ĐANG DÙNG → vân tay PHẢI đổi.
    (root / "configs" / "a.yaml").write_text("threshold: 2\n", encoding="utf-8")
    assert storage.source_fingerprint()["config_hash"] != before, (
        "sửa `configs/*.yaml` mà build_id không đổi — ID đang nói dối")


def test_env_check_reports_both_config_hashes():
    """`config_file_hash` và `config_hash` là hai thứ khác nhau, phải khác tên."""
    import importlib.util
    from pathlib import Path as _P
    spec = importlib.util.spec_from_file_location(
        "env_check", _P(__file__).resolve().parents[1] / "tools" / "env_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fp = mod._build_id_fingerprint()
    assert set(fp) == {"source_hash", "config_hash"}


# ═══════════ RC-07 · cửa sổ ứng viên — ca THẬT của RC1 và tập âm mở rộng ══════

_RC1_REAL_MOJIBAKE = "7 J1001 C TRÁC HÃ¹ Tổng Công ty Viglacera - CTCP Địa chỉ: Tò"


def test_mj01_real_rc1_case_is_repaired():
    """MJ-01 — ca duy nhất `DQ-ENC-MOJIBAKE` của RC1.

    Bản trước TRẢ NGUYÊN VĂN ca này: `_sloppy_encode` đòi TOÀN BỘ chuỗi mã hoá
    được, mà `ổ` (U+1ED5) nằm ngoài Latin-1. Đây là test khoá lại đúng chỗ đó.
    """
    from text2pandas.pipelines.a6.cleaning import clean_text
    res = clean_text(_RC1_REAL_MOJIBAKE)
    assert "HÃ¹" not in res.text_clean
    assert "Hù" in res.text_clean
    assert "C07" in res.rules


def test_mj01_leaves_neighbouring_vietnamese_untouched():
    """Ngoài cửa sổ KHÔNG một ký tự nào được đổi — đây là điều kiện an toàn."""
    from text2pandas.pipelines.a6.cleaning import repair_mojibake
    got = repair_mojibake(_RC1_REAL_MOJIBAKE)
    for keep in ("7 J1001 C TRÁC ", " Tổng Công ty Viglacera - CTCP Địa chỉ: Tò"):
        assert keep in got, keep
    # `TRÁC` chứa `Á` (U+00C1) → mã hoá thành 0xC1, byte dẫn UTF-8 KHÔNG hợp lệ.
    # Nếu ai đó nới cửa sổ thành "đoạn mã hoá được", `TRÁC` sẽ bị đụng.
    assert "TRÁC" in got


def test_mojibake_audit_trace_records_window():
    from text2pandas.pipelines.a6.cleaning import repair_mojibake_trace
    tr = repair_mojibake_trace(_RC1_REAL_MOJIBAKE)
    assert len(tr) == 1
    e = tr[0]
    assert e["before"] == "Ã¹" and e["after"] == "ù"
    assert e["suspicion_after"] < e["suspicion_before"]
    assert e["rule"] == "C07" and e["rule_version"]


@pytest.mark.parametrize("clean_part", ["Doanh thu", "năm 2023", "Số dư", "của Tổng công ty"])
def test_mixed_string_keeps_clean_part(clean_part):
    """MJ-02 — chuỗi hỗn hợp: phần đúng phải sống sót nguyên vẹn."""
    from text2pandas.pipelines.a6.cleaning import repair_mojibake
    src = {"Doanh thu": "Doanh thu " + _mojibake("thuần") + " năm 2023",
           "năm 2023": "Doanh thu " + _mojibake("thuần") + " năm 2023",
           "Số dư": "Số dư " + _mojibake("đầu kỳ") + " của Tổng công ty",
           "của Tổng công ty": "Số dư " + _mojibake("đầu kỳ") + " của Tổng công ty"}[clean_part]
    assert clean_part in repair_mojibake(src)


@pytest.mark.parametrize("s", [
    "α β γ", "™ ® ©", "A/B ÷ C × D", "Số dư đầu kỳ — Số dư cuối kỳ",
    "CTCP Tập đoàn Hòa Phát", "31/12/2023", "Ø 12mm", "±",
])
def test_extended_negative_set_untouched(s):
    """MJ-03/04/05 — tập âm mở rộng ngoài 16 ca ban đầu."""
    from text2pandas.pipelines.a6.cleaning import repair_mojibake
    assert repair_mojibake(s) == s
