"""RC2 · Bộ kiểm cho readiness hai mức, tiny-money và chuẩn hoá tiếng Việt.

Ba module này là critical path của RC2 và chúng bảo vệ những thứ khác nhau:

* `text_normalize`  — audit A-06: FTS không dấu SAI với chữ `đ`. Lỗi im lặng:
  truy vấn không báo lỗi, chỉ trả ít kết quả hơn.
* `tiny_money`      — audit A-04: 1.789 fact đáng ngờ được phép tính tự động,
  chạm 849 bảng / 651 tài liệu.
* `readiness`       — audit A-04: 181.160 observation `confidence='low'` nằm
  trong `execution_ready`.

Mỗi test dưới đây neo vào một số đo thật trên build `b927c3e8f90aed74`, không
vào một lo ngại giả định.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.pipelines.a6.readiness import (  # noqa: E402
    build_readiness, load_policy)
from text2pandas.pipelines.a6.storage import SILVER_DDL  # noqa: E402
from text2pandas.pipelines.a6.text_normalize import (  # noqa: E402
    ACCENT_PAIRS, fold_vietnamese, normalize_search_text, normalize_token)
from text2pandas.pipelines.a6.tiny_money import (  # noqa: E402
    CLASSES, FALSE_VALUE_CLASSES, classify_tiny_money, is_reference_header)

POLICY = ROOT / "configs" / "readiness_policy_v1.yaml"


# ══════════════════ RC-05 · chuẩn hoá tiếng Việt ══════════════════

@pytest.mark.parametrize("accented, plain", ACCENT_PAIRS)
def test_cap_co_dau_va_khong_dau_cho_cung_dang_chuan(accented, plain):
    """Bộ hồi quy §RC-05. Đây chính là ca RC1 làm sai."""
    assert normalize_search_text(accented) == normalize_search_text(plain)


def test_chu_d_gach_ngang_thanh_d():
    """`đ` KHÔNG phải `d` + dấu phụ, nên NFD không tách được nó.

    Đây là gốc rễ của A-06: `unicode61 remove_diacritics 2` giữ nguyên `đ`,
    nên `đầu tư` → `đau tu` còn người dùng gõ `dau tu`. Không khớp, không lỗi.
    """
    assert fold_vietnamese("đ") == "d"
    assert fold_vietnamese("Đ") == "d"
    assert "đ" not in normalize_search_text("Đầu tư dài hạn")
    assert normalize_search_text("Đầu tư") == "dau tu"


def test_khong_pha_hong_van_ban_goc():
    """Chuẩn hoá sinh trường SONG SONG, không thay văn bản hiển thị."""
    src = "Tiền và các khoản tương đương tiền"
    assert normalize_search_text(src) != src
    assert src == "Tiền và các khoản tương đương tiền"


def test_multi_token_giu_ranh_gioi_tu():
    assert normalize_search_text("  Dòng   tiền \n thuần ") == "dong tien thuan"


def test_normalize_token_bo_dau_cau_ocr():
    """OCR hay chèn dấu chấm/gạch vào giữa nhãn: `Mã.số`, `Mã-số`."""
    for v in ("Mã số", "Mã.số", "Mã-số", "Másố", "MÃ  SỐ"):
        assert "ma" in normalize_token(v).split() or normalize_token(v).startswith("ma")


def test_ca_am_khong_double_decode():
    """Chữ tiếng Việt đúng phải sống sót, không bị giải mã hai lần."""
    assert fold_vietnamese("Công ty Cổ phần") == "Cong ty Co phan"


# ══════════════════ RC-03 · tiny-money ══════════════════

def _c(**kw):
    base = dict(value_decimal_text="3", value_source="3", scale_exponent=0,
                unit_kind="money", scale_source="cell", header_path_text="Năm nay",
                row_label="Tiền mặt")
    base.update(kw)
    return classify_tiny_money(**base)


def test_740_ca_la_loi_cua_RULE_khong_phai_cua_du_lieu():
    """Đo được: 740/2.836 đạt ≥1.000 VND SAU khi áp scale.

    Rule cũ so `ABS(value) < 1000` trên giá trị THÔ. Bảng khai `triệu đồng`,
    ô ghi `3` → 3.000.000 VND. Đây là lần thứ ba cùng lớp lỗi này xuất hiện
    (sau `Q-OBS-IMPLAUSIBLE` và `arithmetic.n_implausible_magnitude`).
    """
    cls, why = _c(value_decimal_text="3", scale_exponent=6)
    assert cls == "legitimate_small_money"
    assert "3,000,000" in why


def test_khong_co_scale_thi_van_dang_ngo():
    cls, _ = _c(value_decimal_text="3", scale_exponent=0,
                header_path_text="CHỈ TIÊU")
    assert cls not in ("legitimate_small_money",)


@pytest.mark.parametrize("header, want", [
    ("Mã số", "metric_code"),
    ("Másố", "metric_code"),          # OCR: mất khoảng trắng
    ("Mã sơ", "metric_code"),         # OCR: mất dấu
    ("M8 số", "metric_code"),         # OCR: ã → 8
    ("MS › TÀI SẢN NGẮN HẠN", "metric_code"),
    ("Thuyết minh", "note_reference"),
    ("TM › TÀI SAN NGAN HẠN", "note_reference"),
    ("STT", "ordinal"),
    ("Năm nay", None),
    ("Năm trước", None),
    ("NGUỒN VỐN", None),
    ("", None),
])
def test_nhan_dien_cot_tham_chieu_chiu_duoc_OCR(header, want):
    """Không liệt kê biến thể chính tả sai — chuẩn hoá rồi khớp mẫu.

    Bảy biến thể trên đều đo được trong 2.836 ca thật.
    """
    assert is_reference_header(header) == want


def test_so_hieu_muc_51_khong_phai_tien():
    """`5.1`, `5.18` là số hiệu thuyết minh bị dấu chấm làm trông như thập phân."""
    cls, _ = _c(value_source="5.18", value_decimal_text="5.18",
                header_path_text="TM › TÀI SAN NGAN HẠN")
    assert cls == "note_reference_false_value"


def test_tin_hieu_cap_COT_khi_nhan_khong_noi_gi():
    """Cột toàn số ≤3 chữ số cạnh cột ≥6 chữ số thì không phải cột tiền.

    Đây là tín hiệu CẤP CỘT nên nó sửa vai trò cột, không vá từng ô — đúng
    ràng buộc RC-03 mục 5.
    """
    cls, _ = _c(header_path_text="c0", col_max_digits=3, peer_max_digits=13)
    assert cls == "metric_code_false_value"


def test_eps_nho_van_la_gia_tri_hop_le():
    cls, _ = _c(value_decimal_text="850", header_path_text="Năm nay",
                row_label="Lãi cơ bản trên cổ phiếu")
    assert cls == "legitimate_per_share_or_rate_value"


def test_khong_du_bang_chung_thi_TU_CHOI_phan_loai():
    """DI-07: không đoán. Chưa chắc thì `unresolved`, không phải `false_value`."""
    cls, why = _c(header_path_text="CHỈ TIÊU", row_label="Chi phí khác",
                  col_max_digits=None, peer_max_digits=None)
    assert cls == "parse_or_column_role_unresolved"
    assert "unresolved registry" in why


def test_moi_lop_deu_nam_trong_danh_sach_khai_bao():
    for kw in ({}, {"scale_exponent": 6}, {"value_source": "5.1"},
               {"header_path_text": "Mã số"}, {"row_label": "EPS"},
               {"header_path_text": "c0", "col_max_digits": 2, "peer_max_digits": 9}):
        cls, _ = _c(**kw)
        assert cls in CLASSES


def test_ba_lop_false_value_khong_duoc_ton_tai_sau_RC2():
    assert FALSE_VALUE_CLASSES == {
        "metric_code_false_value", "note_reference_false_value",
        "ordinal_false_value"}


# ══════════════════ RC-02 · readiness hai mức ══════════════════

class _DB:
    """Bọc connection thay vì gắn thuộc tính — `sqlite3.Connection` là kiểu C,
    không nhận attribute động."""

    def __init__(self, con, ins):
        self._con, self.ins = con, ins

    def __getattr__(self, k):
        return getattr(self._con, k)


@pytest.fixture
def db():
    con = sqlite3.connect(":memory:")
    con.executescript(SILVER_DDL)
    cols = [d[1] for d in con.execute("PRAGMA table_info(observations)")]
    notnull = {d[1] for d in con.execute("PRAGMA table_info(observations)") if d[3]}

    def ins(uid, **kw):
        d = dict.fromkeys(cols)
        for c in notnull:
            d[c] = ""
        d.update(
            observation_uid=uid, table_uid="T", source_cell_uid=uid,
            grid_row_idx=1, grid_col_idx=1, value_source="1",
            value_decimal_text="1", value_kind="money", parse_status="ok",
            parse_rule="N", is_negative=0, unit_kind="money",
            scale_source="cell", period_end="2023-12-31", period_type="instant",
            period_role="closing", period_source="column_path", is_restated=0,
            quality_flags_json="[]", metric_label_clean="Tiền",
            row_uid="R", column_uid="C", row_path_text="x")
        d.update(kw)
        con.execute("INSERT INTO observations VALUES("
                    + ",".join("?" * len(cols)) + ")", [d[c] for c in cols])

    yield _DB(con, ins)
    con.close()


def _rdy(con, uid):
    return con.execute(
        "SELECT execution_candidate, execution_ready, confidence,"
        " blocking_reasons_json, warning_reasons_json"
        " FROM observation_readiness WHERE observation_uid=?", (uid,)).fetchone()


def test_hai_muc_tach_biet_that_su(db):
    """`candidate` = chạy được. `ready` = chạy được VÀ dám tin. Khác nhau."""
    db.ins("ok")
    db.ins("role_unknown", quality_flags_json='["column_role_unknown"]')
    db.commit()
    build_readiness(db, load_policy(POLICY))
    assert _rdy(db, "ok")[:2] == (1, 1)
    # Đủ field để tính -> candidate. Nhưng vai trò cột chưa rõ -> KHÔNG ready.
    # Ở RC1 chính 34.098 ca như thế này được phép tính tự động.
    assert _rdy(db, "role_unknown")[:2] == (1, 0)


def test_low_confidence_khong_bao_gio_ready(db):
    """Bất biến A-04. RC1 có 181.160 ca vi phạm."""
    db.ins("lo", scale_source="assumed")
    db.commit()
    build_readiness(db, load_policy(POLICY))
    cand, ready, conf, blk, _ = _rdy(db, "lo")
    assert conf == "low" and ready == 0


@pytest.mark.parametrize("kw, reason", [
    ({"period_end": None}, "period_unresolved"),
    ({"unit_kind": "unknown"}, "unit_unknown"),
    ({"metric_label_clean": "  "}, "label_empty"),
    ({"quality_flags_json": '["scale_rejected_implausible"]'}, "scale_conflict"),
    ({"quality_flags_json": '["tiny_money_unresolved"]'}, "tiny_money_unconfirmed"),
])
def test_moi_fact_not_ready_deu_co_LY_DO(db, kw, reason):
    """View cũ trả `0` rồi im lặng. Người nhận gói không debug được.

    v2.1: lý do nằm ở HAI mảng theo precedence — thiếu field là
    `non_candidate_reasons_json`, còn rủi ro đã biết là `blocking_reasons_json`.
    Bất biến vẫn là *"mọi fact not-ready đều nói được vì sao"*, nên test xét
    HỢP của hai mảng chứ không nới lỏng thành một.
    """
    db.ins("x", **kw)
    db.commit()
    build_readiness(db, load_policy(POLICY))
    _, ready, _, blk, _ = _rdy(db, "x")
    nc = db.execute("SELECT non_candidate_reasons_json FROM observation_readiness"
                    " WHERE observation_uid='x'").fetchone()[0]
    assert ready == 0
    assert reason in blk or reason in nc, (
        f"kỳ vọng lý do {reason!r}, nhận blocking={blk!r} non_candidate={nc!r}")


def test_precedence_tach_non_candidate_khoi_blocking(db):
    """Thiếu field và rủi ro đã biết là HAI chuyện — precedence đòi tách."""
    db.ins("nc", period_end=None)                       # thiếu field → NON_CANDIDATE
    db.ins("bl", quality_flags_json='["column_role_unknown"]')   # → BLOCKING
    db.commit()
    build_readiness(db, load_policy(POLICY))
    g = lambda u: db.execute(
        "SELECT execution_candidate, blocking_reasons_json,"
        " non_candidate_reasons_json FROM observation_readiness"
        " WHERE observation_uid=?", (u,)).fetchone()
    cand_nc, blk_nc, non_nc = g("nc")
    cand_bl, blk_bl, non_bl = g("bl")
    assert cand_nc == 0 and "period_unresolved" in non_nc
    assert cand_bl == 1 and "column_role_unknown" in blk_bl and non_bl == "[]"


def test_mang_ly_do_la_JSON_canonical(db):
    """Sort + khử trùng. Không có nó, RC-16 báo khác nhau chỉ vì thứ tự."""
    import json as _json
    db.ins("c", quality_flags_json='["column_role_unknown","unit_assumed",'
                                   '"scale_rejected_implausible"]')
    db.commit()
    build_readiness(db, load_policy(POLICY))
    for col in ("blocking_reasons_json", "warning_reasons_json",
                "non_candidate_reasons_json"):
        raw = db.execute(f"SELECT {col} FROM observation_readiness"
                         " WHERE observation_uid='c'").fetchone()[0]
        arr = _json.loads(raw)
        assert arr == sorted(arr), f"{col} chưa sort: {arr}"
        assert len(arr) == len(set(arr)), f"{col} có phần tử trùng: {arr}"


def test_co_dieu_kien_phan_biet_theo_BANG_CHUNG(db):
    """`generic_row_label` — warning khi row_path phân biệt được, blocking khi không.

    Đây là điểm khác cốt lõi giữa v2.0 và v2.1. v2.0 cho qua CẢ 202.557 ca
    bằng một dòng `allowed_if` viết bằng văn xuôi mà không ai thi hành.
    """
    db.ins("co_path", quality_flags_json='["generic_row_label"]',
           row_path_text="Tài sản ngắn hạn > Tiền mặt",
           metric_label_clean="Tiền mặt", period_source="table_context")
    db.ins("khong_path", quality_flags_json='["generic_row_label"]',
           row_path_text="Tiền mặt", metric_label_clean="Tiền mặt",
           period_source="table_context")
    db.commit()
    build_readiness(db, load_policy(POLICY))
    g = lambda u: db.execute(
        "SELECT execution_ready, blocking_reasons_json, warning_reasons_json"
        " FROM observation_readiness WHERE observation_uid=?", (u,)).fetchone()
    r1, b1, w1 = g("co_path")
    r0, b0, w0 = g("khong_path")
    assert r1 == 1 and b1 == "[]" and "generic_label_with_distinct_path" in w1
    assert r0 == 0 and "generic_label_not_discriminative" in b0


def test_bat_bien_ready_keo_theo_candidate(db):
    """`ready ⇒ candidate`. Ready mà không candidate là mâu thuẫn logic."""
    for i, kw in enumerate([{}, {"period_end": None}, {"unit_kind": "unknown"},
                            {"quality_flags_json": '["tiny_money_unresolved"]'}]):
        db.ins(f"i{i}", **kw)
    db.commit()
    r = build_readiness(db, load_policy(POLICY))
    assert r["violation_ready_not_candidate"] == 0
    assert db.execute("SELECT COUNT(*) FROM observation_readiness"
                      " WHERE execution_ready=1 AND execution_candidate=0"
                      ).fetchone()[0] == 0


def test_canh_bao_khong_chan(db):
    """`generic_row_label` là cảnh báo, không phải cấm. Chặn nó là loại oan."""
    db.ins("w", quality_flags_json='["generic_row_label"]',
           period_source="table_context")
    db.commit()
    build_readiness(db, load_policy(POLICY))
    _, ready, conf, blk, warn = _rdy(db, "w")
    assert ready == 1 and conf == "medium" and blk == "[]"
    assert warn != "[]"


def test_bat_bien_duoc_bao_cao_thanh_SO(db):
    """Ba số này phải bằng 0. Chúng là điều kiện phát hành, không phải thống kê."""
    for i, kw in enumerate([{}, {"period_end": None}, {"scale_source": "assumed"},
                            {"quality_flags_json": '["column_role_unknown"]'}]):
        db.ins(f"o{i}", **kw)
    db.commit()
    r = build_readiness(db, load_policy(POLICY))
    assert r["violation_low_confidence_in_ready"] == 0
    assert r["violation_blocking_in_ready"] == 0
    assert r["violation_not_ready_without_reason"] == 0
    assert r["execution_ready"] <= r["execution_candidate"] <= r["total"]


def test_policy_version_duoc_ghi_vao_tung_dong(db):
    db.ins("v")
    db.commit()
    pol = load_policy(POLICY)
    build_readiness(db, pol)
    got = db.execute("SELECT DISTINCT policy_version FROM observation_readiness").fetchall()
    assert got == [(pol.policy_version,)]


def test_chinh_sach_khai_du_hai_muc_va_bat_bien():
    """Chính sách là DỮ LIỆU — nên hình dạng của nó cũng phải kiểm được."""
    pol = load_policy(POLICY)
    assert pol.raw.get("execution_candidate") and pol.raw.get("execution_ready")
    assert pol.confidence_allowed == ("high", "medium")
    flags = {f for f, _ in pol.blocking}
    for must in ("column_role_unknown", "scale_rejected_implausible",
                 "tiny_money_unresolved", "physical_duplicate"):
        assert must in flags, f"cờ chặn {must!r} biến mất khỏi chính sách"
    assert len(pol.raw.get("invariants") or []) >= 5


# ── RC-02 · điều kiện PHÂN BIỆT của `generic_row_label` ─────────────────────

def test_row_path_trung_trong_cung_cot_thi_KHONG_phan_biet(db):
    """Hợp đồng P3 đòi ba điều kiện, `collision_class` chỉ bắt được hai.

    Hai DÒNG khác nhau, cùng một cột, cùng `row_path_text` — không hề có
    collision (collision là cùng bảng/dòng/cột), nhưng câu hỏi "lấy dòng nào"
    vẫn không có đáp án duy nhất. Nếu bỏ điều kiện thứ ba thì cả hai đều được
    tự động dùng, và Text-to-Pandas sẽ chọn bừa một trong hai.
    """
    common = dict(quality_flags_json='["generic_row_label"]',
                  row_path_text="Tài sản > Cộng", metric_label_clean="Cộng")
    db.ins("dup_a", row_uid="RA", column_uid="C", **common)
    db.ins("dup_b", row_uid="RB", column_uid="C", **common)
    # Cùng nhãn chung, nhưng nằm ở CỘT khác -> không ai tranh chấp với nó.
    db.ins("solo", row_uid="RC", column_uid="C2", **common)
    db.commit()
    build_readiness(db, load_policy(POLICY))

    for uid in ("dup_a", "dup_b"):
        cand, ready, _, blk, _ = _rdy(db, uid)
        assert (cand, ready) == (1, 0), f"{uid} phải bị chặn"
        assert "generic_label_not_discriminative" in blk

    cand, ready, _, blk, warn = _rdy(db, "solo")
    assert (cand, ready) == (1, 1), "row_path duy nhất trong cột -> vẫn dùng được"
    assert "generic_label_with_distinct_path" in warn
    assert blk == "[]"


def test_bao_cao_do_TUNG_menh_de_cua_C4(db):
    """C4-04/05/08 phải là SỐ RIÊNG, không suy ra từ C4-03.

    Khi `violation_blocking_in_ready` > 0 mà không tách, người đọc biết có vi
    phạm nhưng không biết thuộc loại nào — đúng lúc cần biết nhất.
    """
    db.ins("v")
    db.commit()
    r = build_readiness(db, load_policy(POLICY))
    for k in ("violation_collision_in_ready", "violation_tiny_money_in_ready",
              "violation_policy_version_mismatch", "violation_ready_not_candidate"):
        assert k in r, f"cổng C4 thiếu mệnh đề {k}"
        assert r[k] == 0


# ── RC-02 · sửa đổi AMD-01 · điều kiện phân biệt của `period_from_table` ────

def test_cot_trung_nhan_trong_cung_dong_va_ky_thi_KHONG_dia_chi_hoa_duoc(db):
    """1.550 ca trên RC1. `collision_class` KHÔNG bắt được chúng.

    Đụng độ định nghĩa trên (bảng, dòng, cột) VẬT LÝ. Đây là hai CỘT khác nhau
    mang cùng nhãn, trong cùng một dòng, cùng một kỳ — khoá ngữ nghĩa
    `(row_path, col_path, period)` trỏ tới ≥2 ô. Chọn ô nào cũng là tung đồng
    xu, và exact-match không cho điểm một nửa.
    """
    common = dict(quality_flags_json='["period_from_table"]', row_uid="R",
                  period_end="2023-12-31", col_path_text="Số tiền")
    db.ins("col_a", column_uid="CA", **common)
    db.ins("col_b", column_uid="CB", **common)
    # Cùng nhãn cột nhưng ở DÒNG khác -> không ai tranh chấp với nó.
    db.ins("row_khac", column_uid="CC", **{**common, "row_uid": "R2"})
    db.commit()
    build_readiness(db, load_policy(POLICY))

    for uid in ("col_a", "col_b"):
        cand, ready, _, blk, _ = _rdy(db, uid)
        assert (cand, ready) == (1, 0), f"{uid} phải bị chặn"
        assert "period_inferred_without_evidence" in blk

    cand, ready, _, blk, warn = _rdy(db, "row_khac")
    assert (cand, ready) == (1, 1)
    assert "period_inferred_from_table_context" in warn
    assert blk == "[]"


def test_dieu_kien_period_KHONG_con_ve_hang_dung(db):
    """Chống hồi quy cho AMD-01.

    Ba vế cũ (`period_end IS NOT NULL`, `period_source <> ''`,
    `NOT value_unit_period_conflict`) đều luôn đúng nên cho qua 100%. Nếu ai đó
    đưa chúng trở lại, test này đỏ.
    """
    pol = load_policy(POLICY)
    cf = next(c for c in pol.conditional if c["flag"] == "period_from_table")
    assert cf.get("requires_col_path_discriminative") is True
    joined = " ".join(cf.get("warning_if") or [])
    assert "value_unit_period_conflict" not in joined
    assert "period_source" not in joined


def test_rule_da_nghi_huu_KHONG_con_trong_blocking(db):
    """Nước 1 · `value_unit_period_conflict` chặn 0 ca — giữ nó là giả vờ."""
    pol = load_policy(POLICY)
    assert "value_unit_period_conflict" not in {f for f, _ in pol.blocking}


def test_ba_assertion_nghi_huu_CHAY_o_moi_build(db):
    """Nước 1 · nghỉ hưu kèm bằng chứng, không xoá âm thầm.

    Cờ cũ chặn 0 ca và không ai biết. Ba số này thay nó canh gác — và khác nó
    ở chỗ chúng CHẠY. Khác 0 nghĩa là giả định "đã bị thâu tóm" sai trên RC2.
    """
    db.ins("v")
    db.commit()
    r = build_readiness(db, load_policy(POLICY))
    got = r["retired_rule_assertions"]
    # Fixture không có bảng `columns` -> phải nói rõ là BỎ QUA, không im lặng
    # trả 0 rồi để người đọc tưởng đã kiểm.
    assert "skipped" in got or set(got) == {"RET-01_period", "RET-02_scale",
                                            "RET-03_unit"}


# ── RC-04 · biên trái của lời khai bậc đơn vị ──────────────────────────────

@pytest.mark.parametrize("text, want", [
    # Dạng phổ biến nhất của corpus: bộ trích xuất nối đơn vị vào ngay sau
    # năm, nên KHÔNG có ranh giới từ giữa `0` và `T`.
    ("2020Triệu VND", 6),
    ("31/12/2021Triệu VND", 6),
    ("Năm 2016Triệu đồng", 6),
    ("1/1/2020Nghìn đồng", 3),
    ("31/12/2019Tỷ đồng", 9),
    # Vẫn phải nhận dạng thường.
    ("Đơn vị: triệu đồng", 6),
    ("tỷ đồng", 9),
    # Dấu phụ Thái lọt vào giữa (ca thật, 1/591.775). Nó KHÔNG phải chữ cái,
    # nên lời khai vẫn hợp lệ. Bản liệt kê `[a-zà-ỹ]` chặn nhầm ca này.
    ("Dự phòng cụthe์Triệu đồng › -", 6),
    # ── phải TỪ CHỐI ────────────────────────────────────────────────────
    ("batriệu đồng", None),      # chữ cái đứng trước → từ khác
    ("Xtriệu đồng", None),
    ("Tỷ lệ sở hữu 51%", None),  # `tỷ` một mình không phải bậc
    ("Đơn vị: VND", None),       # tiền tệ ≠ bậc
    ("Tỷ trọng (%)", None),
])
def test_bien_trai_nhan_chu_so_nhung_tu_choi_chu_cai(text, want):
    """Đo trên RC1: 26.515 cột (4,48%) mất bậc chỉ vì `\\b` giữa số và chữ."""
    from text2pandas.pipelines.a6.unit_resolver import _find_scale
    assert _find_scale(text) == want


def test_lop_bien_la_CHU_CAI_unicode_khong_phai_dai_liet_ke():
    """Chống hồi quy cho chính lỗi tôi vừa mắc.

    `[a-zà-ỹ]` trông đủ cho tiếng Việt nhưng `à-ỹ` = U+00E0–U+1EF9 nuốt cả
    khối Thái/Hy Lạp/Kirin. Lớp đúng là `[^\\W\\d_]`.
    """
    from text2pandas.pipelines.a6 import unit_resolver as U
    assert U._NL == r"(?<![^\W\d_])"
    assert "à-ỹ" not in U._NL
