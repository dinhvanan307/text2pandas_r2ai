"""P0-c · khoá hợp đồng của pool v4 — hạn ngạch theo LOẠI BÁO CÁO.

Khuyết tật mà bộ test này canh, đo được ở `docs/82` §4: 44/55 câu UNCERTAIN
thất bại vì ô `(mã, năm)` có tồn tại nhưng **thiếu loại báo cáo cần dùng**.
`PER_CELL_MIN = 2` của v3 chỉ cấp hai suất cho mỗi ô, và hai suất ấy rơi vào
loại nào là chuyện may rủi của một thứ tự ưu tiên duy nhất.

Fixture cố ý dựng bảng cân đối kế toán **bị cắt làm hai thẻ** (nửa tài sản,
nửa nguồn vốn) và gán cả hai nhãn `statement_type='note'` — đúng như A6 thật.
Nếu v4 chỉ đòi `statement_type == 'balance_sheet'` thì nó sẽ xanh trên một
fixture ngây thơ và chết ngoài đời; ở đây nó phải nhận ra vai trò qua nhãn
dòng.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import gold_tay as g3                                       # noqa: E402
from gold_pool_v4 import (PER_CELL_BASE, PER_NEED, _bo_dau,  # noqa: E402
                          _co_cum, _vai_tro, build_pool_v4, nhu_cau_cua)
from retrieval.question_intent import parse_intent           # noqa: E402

ALIAS = {t: [f"Công ty Cổ phần Số {t}"] for t in
         ("VNM", "HPG", "MSN", "DBC", "QNS", "OGC", "ASM", "MPC")}

# TÁM mã · một năm ⇒ 8 ô ⇒ hạn ngạch v3 = max(2, ceil(16/8)) = 2. Đây chính là
# chế độ mà `docs/82` gặp: câu screen nhiều ô thì sàn `POOL_MIN` chia ra không
# còn nâng được hạn ngạch, và mỗi ô chỉ còn đúng hai suất.
_TK = list(ALIAS)
_NAM = [2023, 2024]
_BASIS = ["consolidated", "separate"]

# statement_type · row_labels (ĐÃ BỎ DẤU như A6) · metric_codes · ready_obs
_MAU_BANG = [
    ("income_statement",
     "doanh thu thuan ve ban hang va cung cap dich vu | gia von hang ban "
     "| loi nhuan gop | loi nhuan sau thue thu nhap doanh nghiep", "10", 30),
    # BCĐKT bị cắt đôi, và cả hai nửa mang nhãn `note` — đúng như A6.
    ("note", "tai san ngan han | hang ton kho | tai san dai han "
             "| tong cong tai san", "100", 28),
    ("note", "no phai tra | no ngan han | von chu so huu "
             "| tong cong nguon von", "300", 22),
    ("cash_flow", "luu chuyen tien thuan tu hoat dong kinh doanh "
                  "| tien chi mua sam tai san co dinh", "", 24),
    ("note", "chi phi lai vay va cac khoan tuong tu", "", 26),
]

_CAU_SCREEN = ("Trong nhóm VNM, HPG, MSN, DBC, QNS, OGC, ASM và MPC năm 2023, "
               "doanh nghiệp có hệ số thanh toán nhanh cao nhất có dòng tiền "
               "thuần từ hoạt động kinh doanh là bao nhiêu tỷ đồng?")


def _uid(i: int) -> str:
    return f"{i:016x}"


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE documents (directory_doc_id TEXT PRIMARY KEY, "
              "ticker TEXT, doc_year INT, basis TEXT)")
    c.execute("CREATE TABLE table_cards (table_uid TEXT PRIMARY KEY, doc_id TEXT, "
              "ticker TEXT, doc_year INT, statement_type TEXT, n_observations INT, "
              "execution_ready_obs INT, periods TEXT, units TEXT, metric_codes TEXT, "
              "retrieval_ready INT DEFAULT 1, evidence_ref TEXT, section_text TEXT)")
    c.execute("CREATE VIRTUAL TABLE table_cards_fts USING fts5("
              "table_uid UNINDEXED, ticker, section_text, context_clean, "
              "row_labels, col_labels)")
    n = 0
    for tk in _TK:
        for yr in _NAM:
            for bs in _BASIS:
                doc = f"{tk}_financial_statements_{yr}_{bs}"
                c.execute("INSERT INTO documents VALUES (?,?,?,?)", (doc, tk, yr, bs))
                for stmt, rows_, code, ready in _MAU_BANG:
                    n += 1
                    u = _uid(n)
                    c.execute(
                        "INSERT INTO table_cards VALUES (?,?,?,?,?,?,?,?,?,?,1,?,?)",
                        (u, doc, tk, yr, stmt, ready + 2, ready, f"{yr}-12-31",
                         "money", code, f"{doc}|line:{100 + n}", f"MỤC {n}"))
                    c.execute("INSERT INTO table_cards_fts VALUES (?,?,?,?,?,?)",
                              (u, tk, f"MỤC {n}", "", rows_, f"{yr} VND"))
    return c


def _s1(conn, it):
    return frozenset(
        u for (u,) in conn.execute(
            "SELECT t.table_uid FROM table_cards t "
            "JOIN documents d ON t.doc_id = d.directory_doc_id "
            "WHERE d.ticker IN ({})".format(",".join("?" * len(it.targets))),
            tuple(it.targets)))


def _v4(conn, q, s2=(), proxy=(), seed=frozenset()):
    it = parse_intent(q, ALIAS)
    return build_pool_v4(conn, 1, q, it, list(s2), list(proxy),
                         _s1(conn, it), ALIAS, set(seed)), it


def _v3(conn, q, s2=(), proxy=()):
    it = parse_intent(q, ALIAS)
    return g3.build_pool(conn, 1, q, it, list(s2), list(proxy),
                         _s1(conn, it), ALIAS), it


def _theo_o(pool):
    ra = {}
    for c in pool["candidates"]:
        ra.setdefault(f"{c['ticker']}/{c['doc_year']}", []).append(c)
    return ra


# ═════════════════════════════════════════════════════════════════════════════
# 1 · nhận diện nhu cầu từ CÂU HỎI
# ═════════════════════════════════════════════════════════════════════════════

def test_nhu_cau_thanh_toan_nhanh_keo_theo_ca_hai_nua_can_doi():
    """"Hệ số thanh toán nhanh" = (TSNH − HTK)/nợ NH — cần CẢ hai nửa BCĐKT.

    v3 coi đây là một nhu cầu "bảng cân đối" duy nhất và trong A6 thường chỉ
    lấy được nửa tài sản; ba câu screen ở `docs/82` chết đúng vì thế.
    """
    n = nhu_cau_cua("Hệ số thanh toán nhanh cuối năm 2024 là bao nhiêu lần?")
    assert "balance_sheet_tai_san" in n
    assert "balance_sheet_nguon_von" in n


def test_nhu_cau_cfo_tren_lnst_keo_theo_ca_luu_chuyen_tien_va_kqkd():
    n = nhu_cau_cua("Tỷ lệ dòng tiền thuần từ hoạt động kinh doanh trên lợi "
                    "nhuận sau thuế năm 2024 là bao nhiêu lần?")
    assert "cash_flow" in n and "income_statement" in n


def test_nhu_cau_khong_bat_nham_tu_loi_nhuan_thuan_tu_hoat_dong_kinh_doanh():
    """Cụm "hoạt động kinh doanh" nằm sẵn trong một dòng của BCKQKD.

    Nếu lấy nó làm dấu hiệu dòng tiền thì gần như MỌI câu sẽ phát sinh nhu cầu
    BCLCTT, hạn ngạch phình vô ích và pool loãng đi.
    """
    n = nhu_cau_cua("Lợi nhuận thuần từ hoạt động kinh doanh của VNM năm 2023?")
    assert "cash_flow" not in n


def test_cau_hoi_thuyet_minh_chuyen_de_khong_phat_sinh_nhu_cau():
    """Rỗng là câu trả lời ĐÚNG, không phải thất bại — với những câu này suất
    chung cộng thứ tự `like` mới là cách chọn đúng."""
    assert nhu_cau_cua("Chi phí mua khí từ các chủ mỏ của GAS năm 2022?") == []


# ═════════════════════════════════════════════════════════════════════════════
# 2 · nhận diện VAI TRÒ của bảng — bằng nhãn dòng, không chỉ statement_type
# ═════════════════════════════════════════════════════════════════════════════

def test_nua_can_doi_mang_nhan_note_van_duoc_nhan_dung_vai_tro():
    """Đây là điều kiện sống còn của v4. Trong A6, nửa nguồn vốn của BCĐKT
    thường là `statement_type='note'`; đòi đúng nhãn là tái lặp lỗi v3."""
    assert "balance_sheet_nguon_von" in _vai_tro(
        "note", "no phai tra | no ngan han | von chu so huu")
    assert "balance_sheet_tai_san" in _vai_tro(
        "note", "tai san ngan han | hang ton kho | tong cong tai san")


def test_nua_tai_san_khong_bi_nham_thanh_nua_nguon_von():
    v = _vai_tro("note", "tai san ngan han | hang ton kho | tong cong tai san")
    assert "balance_sheet_nguon_von" not in v


def test_thuyet_minh_khong_lien_quan_khong_nhan_vai_tro_nao():
    assert _vai_tro("note", "chi phi lai vay va cac khoan tuong tu") == set()


# ═════════════════════════════════════════════════════════════════════════════
# 3 · phủ nhu cầu trong TỪNG ô — trước/sau
# ═════════════════════════════════════════════════════════════════════════════

def _thieu_nhu_cau(conn, pool, needs) -> list[str]:
    """Ô nào thiếu vai trò nào — đo trên CHÍNH pool, dùng nhãn dòng đầy đủ."""
    day_du = {u: str(rl or "").lower() for u, rl in conn.execute(
        "SELECT table_uid, row_labels FROM table_cards_fts")}
    theo_o = _theo_o(pool)
    ra = []
    for o in pool["cells"]:
        vai = set().union(*(_vai_tro(c["statement_type"], day_du[c["table_uid"]])
                            for c in theo_o.get(o, [])), set())
        ra += [f"{o}:{n}" for n in needs if n not in vai]
    return ra


def test_v3_thieu_loai_bao_cao_trong_o(conn):
    """Ghi lại nút thắt của v3 để "trước/sau" là một phép đo, không phải lời kể.

    Không khẳng định một hành vi mong muốn — nó khoá con số nền để `docs/83`
    §1 có cơ sở. Khi v3 bị bỏ hẳn, xoá test này.
    """
    p, _ = _v3(conn, _CAU_SCREEN)
    needs = nhu_cau_cua(_CAU_SCREEN)
    assert p["quota_per_cell"] == 2, "fixture không rơi vào chế độ hạn ngạch 2"
    assert _thieu_nhu_cau(conn, p, needs), "fixture không tái hiện nút thắt v3"


def test_v4_phu_du_moi_nhu_cau_cho_moi_o(conn):
    p, it = _v4(conn, _CAU_SCREEN)
    assert set(p["needs"]) >= {"balance_sheet_tai_san", "balance_sheet_nguon_von",
                               "cash_flow"}
    assert p["needs_missing"] == [], p["needs_missing"]
    theo_o = _theo_o(p)
    for o in p["cells"]:
        cs = theo_o.get(o, [])
        assert cs, f"ô {o} rỗng"
        vai = set().union(*(set(c["roles"]) for c in cs))
        for need in p["needs"]:
            assert need in vai, f"ô {o} thiếu loại {need}"


def test_v4_hang_ngach_khong_con_la_hang_so_2(conn):
    p, _ = _v4(conn, _CAU_SCREEN)
    assert p["quota_per_cell"] == PER_CELL_BASE + PER_NEED * len(p["needs"])
    assert p["quota_per_cell"] > 2


def test_v4_o_thieu_loai_bao_cao_thi_khai_bao_chu_khong_im(conn):
    """Ô không có bảng nào đóng được vai trò cần thiết là thiếu hụt CORPUS.
    Nới hạn ngạch không cứu được, nên phải hiện ra ở `needs_missing`."""
    conn.execute("DELETE FROM table_cards WHERE ticker='MSN' "
                 "AND statement_type='cash_flow'")
    p, _ = _v4(conn, _CAU_SCREEN)
    assert any(x.startswith("MSN/") and x.endswith(":cash_flow")
               for x in p["needs_missing"]), p["needs_missing"]


# ═════════════════════════════════════════════════════════════════════════════
# 4 · guardrail của v3 phải còn nguyên
# ═════════════════════════════════════════════════════════════════════════════

def test_s2_van_bi_chan_tran(conn):
    """Pool to ra thì trần S2 to ra theo TỶ LỆ, không phải theo hằng số."""
    it = parse_intent(_CAU_SCREEN, ALIAS)
    moi = sorted(_s1(conn, it))
    p, _ = _v4(conn, _CAU_SCREEN, s2=moi)
    chi_s2 = [c for c in p["candidates"] if c["sources"] == ["s2"]]
    assert len(chi_s2) / len(p["candidates"]) <= g3.S2_SHARE_MAX + 1e-9


def test_phan_bu_cho_du_san_khong_lay_tu_s2(conn):
    it = parse_intent("Doanh thu thuần của VNM năm 2023 là bao nhiêu tỷ đồng?",
                      ALIAS)
    moi = sorted(_s1(conn, it))
    p, _ = _v4(conn, "Doanh thu thuần của VNM năm 2023 là bao nhiêu tỷ đồng?",
               s2=moi)
    doc_lap = [c for c in p["candidates"] if not g3._phu_thuoc_fts(c["sources"])]
    assert len(doc_lap) >= min(g3.POOL_MIN, len(moi))


def test_pool_khong_lo_diem_hay_thu_hang(conn):
    p, _ = _v4(conn, _CAU_SCREEN)
    for c in p["candidates"]:
        assert "score" not in c and "rank" not in c


def test_tat_dinh_chay_hai_lan_ra_cung_ket_qua(conn):
    a, _ = _v4(conn, _CAU_SCREEN)
    b, _ = _v4(conn, _CAU_SCREEN)
    assert [c["table_uid"] for c in a["candidates"]] == \
           [c["table_uid"] for c in b["candidates"]]


# ═════════════════════════════════════════════════════════════════════════════
# 5 · phạm vi và tính liên tục với nhãn đã gán
# ═════════════════════════════════════════════════════════════════════════════

def test_cau_cong_ty_me_uu_tien_ban_rieng_trong_moi_o(conn):
    """v3 không xét `basis` khi chọn, nên hai suất của ô có thể rơi cả vào bản
    hợp nhất — và câu "công ty mẹ …" thành không gán được (`docs/82` q965)."""
    q = ("Trong nhóm VNM, HPG và MSN, doanh thu thuần của công ty mẹ năm 2023 "
         "là bao nhiêu tỷ đồng?")
    p, it = _v4(conn, q)
    assert it.basis == "separate"
    for o, cs in _theo_o(p).items():
        assert any(c["basis"] == "separate" for c in cs), f"ô {o} thiếu bản riêng"


def test_hat_giong_tu_nhan_da_gan_luon_con_trong_pool(conn):
    """65 nhãn của `docs/82` trỏ tới uid chọn từ pool v3. Đánh rơi một uid là
    làm đỏ lớp kiểm "gold nằm trong pool" — một hồi quy do công cụ."""
    it = parse_intent(_CAU_SCREEN, ALIAS)
    la = sorted(_s1(conn, it))[-1]          # uid gần như chắc chắn không được chọn
    p, _ = _v4(conn, _CAU_SCREEN, seed={la})
    assert la in {c["table_uid"] for c in p["candidates"]}
    assert "gan_v3" in next(c["sources"] for c in p["candidates"]
                            if c["table_uid"] == la)


def test_bo_dau_giu_khoang_trang_de_mau_la_CUM_TU():
    """`_bo_dau` giữ khoảng trắng, khác `ascii_compact` của S0.

    Cần thiết vì mọi mẫu trong `_NHU_CAU` là cụm từ: `no ngan han` phải khớp
    "nợ ngắn hạn" chứ không được khớp "…nợ ngân hàng…" hay dính vào từ trước.
    Lưu ý: giữ khoảng trắng là ĐIỀU KIỆN CẦN, không phải điều kiện đủ để tránh
    khớp nhầm — xem `tests/test_entity_resolution_trace.py`.
    """
    assert _bo_dau("Nợ ngắn hạn") == "no ngan han"
    assert _bo_dau("Đầu tư Tân Bình") == "dau tu tan binh"


def test_khop_mau_phai_neo_bien_tu():
    """Bản đầu của `nhu_cau_cua` dùng `m in text` và mắc ĐÚNG lỗi mà `docs/83`
    §2 đang tố cáo ở `parse_intent`: `no ngan han` là chuỗi con của
    `no ngan hang`. Test này bắt được nó; giữ lại để nó không quay lại."""
    assert _co_cum("no ngan han cuoi nam", ("no ngan han",))
    assert not _co_cum("no ngan hang va no dai han", ("no ngan han",))
    assert nhu_cau_cua("Dư nợ ngân hàng của VNM năm 2023 là bao nhiêu?") == []
