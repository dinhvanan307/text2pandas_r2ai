"""Test operation gate v3 (docs/110 §15). Chạy trực tiếp từ bundle evidence."""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from execution.answer_operation import (ENUM_STATUS, OPERATIONS, RULE_VERSION,  # noqa: E402
                                        TOTAL_SCOPES, EntityHit, entity_hits,
                                        phan_loai, phan_tich_ast, quet_tin_hieu_tong)

PRECHECK = ROOT / "answer_operation_precheck.jsonl"


@dataclass
class Spec:
    value_kind: str = "money"
    unit_exponent: int = 9
    unit_label: str = "tỷ đồng"
    arity: str = "scalar"
    evidence: str = "test"
    flags: list = field(default_factory=list)


class Cty:
    """CompanyIndex tối giản, đủ cho test — không cần catalog thật."""
    def __init__(self, rows):
        import re, unicodedata

        def fold(s):
            s = unicodedata.normalize("NFD", s.lower())
            s = "".join("d" if c == "đ" else c for c in s
                        if unicodedata.category(c) != "Mn")
            return re.sub(r"[^a-z0-9 ]", " ", s)

        self.by_ticker = dict(rows)
        self._folded = [(t, fold(n)) for t, n in rows]
        # mô phỏng CompanyIndex thật: bỏ tiền tố pháp lý để khớp phần lõi
        self._core = [(t, re.sub(r"^(ctcp|cong ty co phan|cong ty cp|ngan hang tmcp|tap doan)\s+",
                                 "", fold(n))) for t, n in rows]


CTY = Cty([("FOX", "Cong ty Co phan Vien thong FPT"), ("FPT", "CTCP FPT"),
           ("HNG", "Cong ty CP Nong nghiep Quoc te Hoang Anh Gia Lai"),
           ("HAG", "CTCP Hoang Anh Gia Lai"), ("SAB", "Tong Cong ty Bia Ruou Sai Gon"),
           ("VNM", "CTCP Sua Viet Nam")])
KNOWN = {"FOX", "FPT", "HNG", "HAG", "SAB", "VNM", "ACB"}
Q1O = "float(df1[(df1['row_path'] == 'a') & (df1['col_label'] == 'b')]['value'].values[0]) / 1000000000"
DIRECT = "Tiền và tương đương tiền của VNM cuối năm 2023 là bao nhiêu tỷ đồng?"


def goi(q, spec=None, *, row="Tiền", query=Q1O, ev=("df1",)):
    return phan_loai(1, q, spec or Spec(), companies=CTY, known=KNOWN,
                     selected_row_path=row, query=query, evidence_vars=list(ev))


# ═══ 15.1 · AST → allow, TÍCH HỢP trên phan_loai ══════════════════════════
@pytest.mark.parametrize("query,allow,reason", [
    (Q1O, True, "AST_OK"),
    ("", False, "AST_EMPTY_QUERY"),
    ("float(df1[", False, "AST_PARSE_FAILED"),
    ("float(df1[df1['r']=='a']['v'].sum())", False, "AST_HAS_AGGREGATION"),
    ("float(df1[df1['r']=='a']['v'].values[0]) - float(df1[df1['r']=='b']['v'].values[0])",
     False, "AST_HAS_MULTI_CELL_ARITHMETIC"),
    ("float(dfX[dfX['r']=='a']['v'].values[0])", False, "AST_UNKNOWN_VARIABLE"),
    ("float(df1['v'].values[0])", False, "AST_NOT_SINGLE_SELECTION"),
])
def test_ast_quyet_dinh_allow(query, allow, reason):
    d = goi(DIRECT, query=query)
    assert d.primary_operation == "DIRECT_LOOKUP"
    assert d.allow_a6_single_cell is allow
    assert d.ast_reason == reason
    assert d.review_required is (not allow)


def test_ast_dep_khong_nang_cau_arithmetic_thanh_direct():
    d = goi("Chênh lệch vốn chủ sở hữu của VNM giữa 2024 và 2023 là bao nhiêu tỷ đồng?")
    assert d.primary_operation == "DIFFERENCE"
    assert d.ast_consistent is True and d.allow_a6_single_cell is False


def test_hai_evidence_cung_bien_khong_thanh_hai_dataframe():
    assert phan_tich_ast(Q1O, ["df1", "df1"]).la_mot_o is True


def test_hai_dataframe_that_bi_nhan_dien_du_caller_khai_mot():
    sh = phan_tich_ast("float(df1[df1['r']=='a']['v'].values[0]) / float(df2[df2['r']=='b']['v'].values[0])",
                       ["df1", "df2"])
    assert sh.la_mot_o is False and sh.n_dataframes == 2


@pytest.mark.parametrize("q,ok", [
    ("float(df1.loc[df1['r']=='a', 'value'].values[0])", True),
    ("float(df1.loc[df1['r']=='a', 'value'].iat[0])", True),
    ("float(df1.iloc[0]['value'])", False),
    ("float(df1.at[0, 'value'])", False),
])
def test_accessor_loc_iloc_at_iat(q, ok):
    assert phan_tich_ast(q, ["df1"]).la_mot_o is ok


# ═══ 15.2 · `tổng` — thực thể vs chỉ tiêu ═════════════════════════════════
def test_tong_trong_ten_phap_nhan_khong_thanh_SUM():
    d = goi("Tiền của công ty mẹ Tổng Cong ty Bia Ruou Sai Gon năm 2023 là bao nhiêu tỷ đồng?")
    assert d.total_signal_scope == "ENTITY_NAME"
    assert d.primary_operation != "SUM"
    assert "tong_thuoc_ten_phap_nhan_bo_qua" in d.negative_signals


def test_tong_chi_tieu_co_dong_tong_thi_van_direct():
    d = goi("Tổng tài sản của VNM năm 2023 là bao nhiêu tỷ đồng?", row="Tổng cộng tài sản")
    assert d.total_signal_scope == "METRIC" and d.primary_operation == "DIRECT_LOOKUP"


def test_tong_chi_tieu_khong_co_dong_tong_thi_thanh_SUM():
    d = goi("Tổng tài sản của VNM năm 2023 là bao nhiêu tỷ đồng?", row="Tiền mặt")
    assert d.primary_operation == "SUM"


def test_tong_A_va_B_la_phep_cong():
    d = goi("Tổng tiền mặt và tiền gửi của VNM năm 2023 là bao nhiêu tỷ đồng?", row="Tổng cộng")
    assert d.primary_operation == "SUM" and "tong_cua_A_va_B" in d.operation_signals


def test_dau_ngu_khong_nhan_dien_duoc_thi_fail_closed():
    """docs/112 §4.5: total ngoài mọi entity span + không parse được đầu ngữ."""
    d = goi("Tổng xyzzy của VNM năm 2023 là bao nhiêu tỷ đồng?")
    assert d.total_signal_scope == "UNKNOWN"
    assert d.primary_operation == "UNKNOWN" and d.allow_a6_single_cell is False
    assert "tong_khong_xac_dinh_pham_vi" in d.negative_signals


def test_tong_chi_tieu_khong_co_thuc_the_van_la_METRIC():
    """v3.1: phạm vi do SPAN + đầu ngữ quyết định, không do có/không có entity.

    Trước v3.1 câu này bị gán UNKNOWN chỉ vì không nhận ra pháp nhân. Nhãn mới
    đúng ngữ nghĩa hơn, và vẫn fail-closed vì thiếu bằng chứng dương thực thể.
    """
    d = goi("Tổng giá trị là bao nhiêu tỷ đồng?", row="Tiền")
    assert d.total_signal_scope == "METRIC"
    assert d.allow_a6_single_cell is False


# ═══ 15.2b · docs/112 §4 — exact span containment + multi-total ═══════════
def test_tong_trong_ten_phap_nhan_theo_span_chua_tron():
    """(1) `Tổng Công ty ABC có doanh thu …` -> entity total, bị bỏ qua."""
    d = goi("Tổng Cong ty Bia Ruou Sai Gon có doanh thu năm 2023 là bao nhiêu tỷ đồng?")
    assert [s["scope"] for s in d.total_signals] == ["ENTITY_NAME"]
    assert d.total_signals[0]["linked_entity_id"] == "SAB"
    assert d.total_signal_scope == "ENTITY_NAME" and d.primary_operation != "SUM"


def test_tong_metric_dung_sau_thuc_the_van_la_METRIC():
    """(2)+(5) `Công ty ABC có tổng doanh thu …` — `tổng` ĐỨNG SAU entity."""
    d = goi("CTCP Sua Viet Nam có tổng doanh thu năm 2023 là bao nhiêu tỷ đồng?", row="Tiền")
    assert [s["scope"] for s in d.total_signals] == ["METRIC"]
    assert d.total_signals[0]["linked_metric"] == "doanh thu"
    assert d.total_signal_scope == "METRIC" and d.primary_operation == "SUM"


def test_tong_metric_dung_truoc_thuc_the():
    """(4) metric đứng trước entity."""
    d = goi("Tổng doanh thu của VNM năm 2023 là bao nhiêu tỷ đồng?", row="Tiền")
    assert [s["scope"] for s in d.total_signals] == ["METRIC"]
    assert d.total_signal_scope == "METRIC"


def test_multi_total_giu_ca_hai_signal_khong_ghi_de():
    """(3) `Tổng Công ty ABC … tổng doanh thu …` -> 1 ENTITY_NAME + 1 METRIC."""
    d = goi("Tổng Cong ty Bia Ruou Sai Gon có tổng doanh thu năm 2023 là bao nhiêu tỷ đồng?",
            row="Tiền")
    sc = [s["scope"] for s in d.total_signals]
    assert sc == ["ENTITY_NAME", "METRIC"], sc
    assert d.n_total_spans == 2
    assert d.total_signal_scope == "METRIC"          # gộp fail-closed
    assert "tong_thuoc_ten_phap_nhan_bo_qua" in d.negative_signals
    assert d.primary_operation == "SUM"


def test_ENTITY_NAME_chi_khi_span_nam_trong_entity_span():
    """docs/112 §17.3 — bất biến cốt lõi của vòng này."""
    for q in ("Tổng Cong ty Bia Ruou Sai Gon có tổng doanh thu năm 2023 là bao nhiêu tỷ đồng?",
              "Công ty mẹ VNM có tổng chi phí năm 2023 là bao nhiêu tỷ đồng?",
              "Tổng doanh thu của VNM năm 2023 là bao nhiêu tỷ đồng?"):
        d = goi(q, row="Tiền")
        es = [tuple(s) for s in d.entity_spans]
        for s in d.total_signals:
            a, b = s["span"]
            trong = any(x <= a and b <= y for x, y in es)
            assert (s["scope"] == "ENTITY_NAME") == trong, (q, s, es)


def test_tong_cong_ty_ngoai_catalog_khong_thanh_ENTITY_NAME():
    """Đầu ngữ pháp nhân nhưng KHÔNG khớp catalog -> fail-closed, không bỏ qua."""
    d = goi("Tổng Công ty Không Có Trong Danh Mục có doanh thu 2023 là bao nhiêu tỷ đồng?")
    assert [s["scope"] for s in d.total_signals] == ["UNMATCHED_ENTITY_NAME"]
    assert d.total_signal_scope == "UNMATCHED_ENTITY_NAME"
    assert d.primary_operation == "UNKNOWN" and d.allow_a6_single_cell is False


def test_moi_span_tong_deu_duoc_account():
    q = "Tổng Cong ty Bia Ruou Sai Gon có tổng tài sản và tổng nợ phải trả năm 2023 là bao nhiêu?"
    d = goi(q, row="Tiền")
    import re as _re, unicodedata as _ud

    def fold(s):
        s = _ud.normalize("NFD", s.lower())
        s = "".join("d" if c == "đ" else c for c in s if _ud.category(c) != "Mn")
        return _re.sub(r"[^a-z0-9 ]", " ", s)
    assert d.n_total_spans == len(_re.findall(r"\btong\b", fold(q))) == 3
    assert len(d.total_signals) == 3
    assert all(s["scope"] in TOTAL_SCOPES for s in d.total_signals)


def test_span_tong_khong_chong_lan_va_tang_dan():
    d = goi("Tổng Cong ty Bia Ruou Sai Gon có tổng tài sản và tổng nợ năm 2023 là bao nhiêu?",
            row="Tiền")
    sp = [tuple(s["span"]) for s in d.total_signals]
    assert sp == sorted(sp) and all(sp[i][1] <= sp[i + 1][0] for i in range(len(sp) - 1))


def test_tong_cong_la_dau_ngu_chi_tieu_khong_phai_cong_ty():
    """`Tổng cộng tài sản` ≠ `Tổng Công ty` — khớp đầu ngữ theo ranh giới từ."""
    d = goi("Tổng cộng tài sản của VNM cuối năm 2021 là bao nhiêu tỷ đồng?",
            row="Tổng cộng tài sản")
    assert [s["scope"] for s in d.total_signals] == ["METRIC"]
    assert d.total_signals[0]["linked_metric"] == "cong"
    assert d.primary_operation == "DIRECT_LOOKUP" and d.allow_a6_single_cell is True


def test_tong_giam_doc_la_danh_ngu_chuc_danh():
    """`Tổng Giám đốc` là chức danh: không cộng, không phải tên pháp nhân."""
    d = goi("Thu nhập Ban Tổng giám đốc của CTCP Sua Viet Nam năm 2023 là bao nhiêu tỷ đồng?",
            row="Thu nhập Ban Tổng giám đốc")
    assert [s["scope"] for s in d.total_signals] == ["TITLE_LEXICAL"]
    assert d.primary_operation == "DIRECT_LOOKUP"
    assert "tong_thuoc_danh_ngu_chuc_danh_bo_qua" in d.negative_signals


def test_quet_tin_hieu_tong_khong_co_tong_thi_rong():
    assert quet_tin_hieu_tong("Doanh thu của VNM năm 2023 là bao nhiêu?", []) == []


# ═══ 15.3 · từ vựng phép toán ═════════════════════════════════════════════
@pytest.mark.parametrize("q,op", [
    ("Hiệu giữa doanh thu của VNM năm 2023 và 2022 là bao nhiêu tỷ đồng?", "DIFFERENCE"),
    ("Hiệu số nợ vay của VNM năm 2023 là bao nhiêu tỷ đồng?", "DIFFERENCE"),
    ("Doanh thu VNM năm 2023 trừ đi chi phí là bao nhiêu tỷ đồng?", "DIFFERENCE"),
    ("Doanh thu của VNM lớn hơn của HAG bao nhiêu tỷ đồng năm 2023?", "DIFFERENCE"),
    ("Nợ của VNM kém hơn HAG mấy tỷ đồng năm 2023?", "DIFFERENCE"),
    ("Tính tỷ số nợ trên vốn của VNM năm 2023?", "RATIO_MULTIPLE"),
    ("Tỉ số thanh toán của VNM năm 2023 là bao nhiêu?", "RATIO_MULTIPLE"),
    ("Doanh thu VNM thay đổi giữa hai kỳ bao nhiêu tỷ đồng?", "DIFFERENCE"),
])
def test_tu_vung_phep_toan(q, op):
    assert goi(q).primary_operation == op


def test_cau_truc_khong_ghi_de_nghiep_vu():
    d = goi("Hiệu giữa doanh thu của VNM năm 2023 và năm 2022 là bao nhiêu tỷ đồng?")
    assert d.primary_operation == "DIFFERENCE" and "MULTI_PERIOD" in d.sub_operations


def test_primary_khong_nam_trong_sub_operations():
    for q in ("Hiệu giữa doanh thu VNM năm 2023 và 2022 là bao nhiêu?",
              "Doanh thu VNM và HAG năm 2023 chênh lệch bao nhiêu?"):
        d = goi(q)
        assert d.primary_operation not in d.sub_operations


def test_sub_operations_thu_tu_tat_dinh():
    d = goi("Doanh thu VNM và HAG năm 2023 và 2022 chênh lệch bao nhiêu tỷ đồng?")
    assert d.sub_operations == [o for o in OPERATIONS if o in set(d.sub_operations)]


# ═══ 15.4 · chuẩn hoá thực thể ════════════════════════════════════════════
def test_ten_day_du_cong_ticker_la_MOT_thuc_the():
    h, tho, st = entity_hits("Tiền gửi của Cong ty Co phan Vien thong FPT (FOX) năm 2022", CTY, KNOWN)
    assert [x.canonical_id for x in h] == ["FOX"] and st == "OK"
    assert set(tho) >= {"FOX", "FPT"}


def test_ten_dai_chua_ten_ngan_la_MOT_thuc_the():
    h, tho, _ = entity_hits("Lợi nhuận của Cong ty CP Nong nghiep Quoc te Hoang Anh Gia Lai năm 2015",
                            CTY, KNOWN)
    assert [x.canonical_id for x in h] == ["HNG"] and set(tho) >= {"HNG", "HAG"}


def test_hai_doanh_nghiep_that_su_la_HAI_thuc_the():
    h, _, _ = entity_hits("So sánh VNM và ACB năm 2023", CTY, KNOWN)
    assert len({x.canonical_id for x in h}) == 2


def test_khong_nhan_ra_thuc_the_thi_PARSE_FAILED():
    _, _, st = entity_hits("Doanh thu năm 2023 là bao nhiêu?", CTY, set())
    assert st == "PARSE_FAILED"


# ═══ enum contract ════════════════════════════════════════════════════════
def test_enum_va_trang_thai_day_du():
    assert len(OPERATIONS) == 15 and len(set(OPERATIONS)) == 15
    assert set(ENUM_STATUS) == set(OPERATIONS), "mọi nhãn phải khai trạng thái"
    assert set(ENUM_STATUS.values()) <= {"EMITTED", "EMITTED_IF_PRESENT", "RESERVED_FOR_PLANNER"}
    assert RULE_VERSION == "operation_rule_v3_1"


# ═══ 15.6 · regression trên QID thật ══════════════════════════════════════
KY_VONG = {
    13: ("DIRECT_LOOKUP", None), 60: ("DIRECT_LOOKUP", None), 84: ("DIRECT_LOOKUP", None),
    112: ("DIRECT_LOOKUP", 1), 212: ("DIRECT_LOOKUP", 1),
    580: ("DIFFERENCE", None), 599: ("DIFFERENCE", None), 600: ("DIFFERENCE", None),
    601: ("DIFFERENCE", None), 602: ("DIFFERENCE", None),
    736: ("DIFFERENCE", None), 739: ("DIFFERENCE", None), 743: ("DIFFERENCE", None),
    744: ("DIFFERENCE", None), 745: ("DIFFERENCE", None), 746: ("DIFFERENCE", None),
    756: ("DIFFERENCE", None), 792: ("DIFFERENCE", None), 794: ("DIFFERENCE", None),
    800: ("DIFFERENCE", None), 804: ("DIFFERENCE", None),
}


@pytest.mark.skipif(not PRECHECK.is_file(), reason="cần answer_operation_precheck.jsonl trong bundle")
@pytest.mark.parametrize("qid", sorted(KY_VONG))
def test_regression_qid_that(qid):
    rows = {r["qid"]: r for r in
            (json.loads(l) for l in PRECHECK.open(encoding="utf-8") if l.strip())}
    r = rows[qid]
    op, n_ent = KY_VONG[qid]
    assert r["primary_operation"] == op
    if n_ent is not None:
        assert r["entity_count"] == n_ent
    if op != "DIRECT_LOOKUP":
        assert r["allow_a6_single_cell"] is False
    assert r["primary_operation"] not in r["sub_operations"]
    assert r["ast_reason"] in ("AST_OK", "AST_EMPTY_QUERY")


@pytest.mark.skipif(not PRECHECK.is_file(), reason="cần precheck")
def test_precheck_accounting():
    rows = [json.loads(l) for l in PRECHECK.open(encoding="utf-8") if l.strip()]
    assert len(rows) == 1012 and len({r["qid"] for r in rows}) == 1012
    assert all(r["primary_operation"] in OPERATIONS for r in rows)
    assert all(set(r["sub_operations"]) <= set(OPERATIONS) for r in rows)


@pytest.mark.skipif(not PRECHECK.is_file(), reason="cần precheck")
def test_khong_con_tong_cong_ty_bi_gan_SUM_do_ten():
    rows = [json.loads(l) for l in PRECHECK.open(encoding="utf-8") if l.strip()]
    xau = [r["qid"] for r in rows
           if r["primary_operation"] == "SUM" and r["total_signal_scope"] == "ENTITY_NAME"]
    assert xau == []


# ═══ 15.7 · docs/112 §4.6 — acceptance trên toàn precheck ═════════════════
def _rows():
    return [json.loads(l) for l in PRECHECK.open(encoding="utf-8") if l.strip()]


@pytest.mark.skipif(not PRECHECK.is_file(), reason="cần precheck")
def test_precheck_ENTITY_NAME_luon_nam_trong_entity_span():
    xau = []
    for r in _rows():
        es = [tuple(s) for s in r["entity_spans"]]
        for s in r["total_signals"]:
            if s["scope"] != "ENTITY_NAME":
                continue
            a, b = s["span"]
            if not any(x <= a and b <= y for x, y in es):
                xau.append((r["qid"], s["span"]))
    assert xau == [], xau


@pytest.mark.skipif(not PRECHECK.is_file(), reason="cần precheck")
def test_precheck_moi_span_tong_deu_duoc_luu():
    import re as _re
    import unicodedata as _ud

    def fold(s):
        s = _ud.normalize("NFD", (s or "").lower())
        s = "".join("d" if c == "đ" else c for c in s if _ud.category(c) != "Mn")
        return _re.sub(r"[^a-z0-9 ]", " ", s)
    for r in _rows():
        n = len(_re.findall(r"\btong\b", fold(r["question"])))
        assert r["n_total_spans"] == len(r["total_signals"]) == n, r["qid"]


@pytest.mark.skipif(not PRECHECK.is_file(), reason="cần precheck")
def test_precheck_scope_hop_le_va_gop_dung():
    from execution.answer_operation import UU_TIEN_GOP as uu
    for r in _rows():
        sc = {s["scope"] for s in r["total_signals"]}
        assert sc <= set(TOTAL_SCOPES)
        mong = next((u for u in uu if u in sc), "NONE")
        assert r["total_signal_scope"] == mong, r["qid"]


@pytest.mark.skipif(not PRECHECK.is_file(), reason="cần precheck")
def test_q292_khong_con_auto_direct():
    r = {x["qid"]: x for x in _rows()}[292]
    assert r["total_signal_scope"] == "METRIC"
    assert r["primary_operation"] != "DIRECT_LOOKUP"
    assert r["allow_a6_single_cell"] is False
    assert r["proposed_action"] == "BLOCK_NON_DIRECT_LOOKUP"
