"""P0-1 + P0-2 · KHOÁ hai bất biến vừa được sửa, để chúng không trôi lại.

BỐI CẢNH — LỖI THẬT, KHÔNG PHẢI LỖI GIẢ ĐỊNH
--------------------------------------------
Luật "chuỗi nào phải bị loại khỏi truy vấn BM25" từng được viết ở HAI chỗ:

    pipeline.py:79          drop = alias TÊN công ty + mã     ← đúng
    evalkit/stages.py:230   drop = CHỈ mã                     ← thiếu tên

Không ngoại lệ, không sai cú pháp, không test nào đỏ. Nó sống sót ba phiên và
làm mọi số TUYỆT ĐỐI của `evalkit` thấp hơn thực tế ~9 điểm hit@1.

Tệp này khoá bốn thứ, theo đúng thứ tự nguyên nhân → hệ quả:

  1. `drop_terms` có gồm tên công ty            (luật đúng)
  2. cơ chế: tên còn lại thì kéo bảng SAI lên   (vì sao luật đó quan trọng)
  3. `pipeline.run` và stages là MỘT đường code (không còn chỗ để trôi)
  4. sửa hành vi S2 mà quên bump `SCHEMA_VERSION` thì đỏ  (checkpoint cũ
     không được âm thầm dùng lại)
"""

from __future__ import annotations

import ast
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.pipelines.retrieval.evalkit.runner import SCHEMA_VERSION  # noqa: E402
from text2pandas.pipelines.retrieval.evalkit.stages import (Bm25StructuralRanker,  # noqa: E402
                                      HardFilterGenerator)
from text2pandas.pipelines.retrieval.pipeline import run  # noqa: E402
from text2pandas.pipelines.retrieval.query_terms import content_terms, drop_terms  # noqa: E402
from text2pandas.pipelines.retrieval.question_intent import parse_intent  # noqa: E402

ALIAS = {"VNM": ["Công ty Cổ phần Sữa Việt Nam", "Vinamilk"]}
CAU = "Doanh thu thuần của Công ty Cổ phần Sữa Việt Nam năm 2023 là bao nhiêu?"


# ─────────────────────────────────────────────────────────────────────────────
# 1 · luật drop
# ─────────────────────────────────────────────────────────────────────────────

def test_drop_terms_gom_ca_ten_cong_ty_va_ma():
    d = drop_terms(("VNM",), ALIAS)
    assert "VNM" in d
    assert "Công ty Cổ phần Sữa Việt Nam" in d, "ĐÂY LÀ REGRESSION P0-1"
    assert "Vinamilk" in d


def test_drop_terms_khong_co_alias_thi_chi_co_ma():
    """Chữ ký cho phép `alias=None` để test đơn vị khỏi phải dựng alias — nhưng
    đó CHÍNH LÀ hành vi có lỗi, nên phải khai tường minh ở đây."""
    assert drop_terms(("VNM",), None) == ("VNM",)
    assert drop_terms(("VNM",), {}) == ("VNM",)


def test_ten_cong_ty_bien_khoi_terms_khi_co_alias():
    co = content_terms(CAU, drop=drop_terms(("VNM",), ALIAS))
    khong = content_terms(CAU, drop=drop_terms(("VNM",), None))
    fold = lambda xs: {x.lower() for x in xs}  # noqa: E731
    assert "sữa" not in fold(co) and "việt" not in fold(co)
    assert "sữa" in fold(khong), "thiếu alias ⇒ tên còn lại — đúng như đo được"
    assert len(khong) > len(co)          # +token nhiễu: đo thật là +2,3/câu


# ─────────────────────────────────────────────────────────────────────────────
# 2 · CƠ CHẾ · tên công ty còn lại thì kéo bảng sai lên top
# ─────────────────────────────────────────────────────────────────────────────

_DOC = ("VNM_financial_statements_2023_consolidated", "VNM", 2023, "consolidated")
# uid, statement_type, periods, row_labels, section_text
_CARDS = [
    ("dung", "income_statement", "2023-12-31",
     "Doanh thu thuần về bán hàng và cung cấp dịch vụ",
     "BÁO CÁO KẾT QUẢ HOẠT ĐỘNG KINH DOANH"),
    # Bảng thuyết minh NHẮC LẠI chỉ tiêu (rất phổ biến trong corpus thật) VÀ
    # chứa tên công ty. Với truy vấn đúng, hai bảng gần như hoà; token tên là
    # thứ phá thế hoà — về phía SAI. Đó là cơ chế của −9 điểm, thu nhỏ lại.
    ("nhieu", "note", "2023-12-31",
     "Doanh thu thuần Sữa Việt Nam Sữa Việt Nam",
     "THÔNG TIN CHUNG VỀ CÔNG TY Sữa Việt Nam"),
]


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    c.execute("CREATE TABLE documents (directory_doc_id TEXT PRIMARY KEY, "
              "ticker TEXT, doc_year INT, basis TEXT)")
    c.execute("INSERT INTO documents VALUES (?,?,?,?)", _DOC)
    c.execute("CREATE TABLE table_cards (table_uid TEXT PRIMARY KEY, doc_id TEXT, "
              "ticker TEXT, doc_year INT, statement_type TEXT, n_observations INT, "
              "execution_ready_obs INT, periods TEXT, units TEXT, metric_codes TEXT, "
              "retrieval_ready INT DEFAULT 1, evidence_ref TEXT)")
    c.execute("CREATE VIRTUAL TABLE table_cards_fts USING fts5("
              "table_uid UNINDEXED, ticker, section_text, context_clean, "
              "row_labels, col_labels)")
    for i, (uid, stmt, per, rows_, sec) in enumerate(_CARDS):
        c.execute("INSERT INTO table_cards VALUES (?,?,?,?,?,?,?,?,?,?,1,?)",
                  (uid, _DOC[0], "VNM", 2023, stmt, 10, 10, per, "money", "",
                   f"{_DOC[0]}|line:{100 + i}"))
        c.execute("INSERT INTO table_cards_fts VALUES (?,?,?,?,?,?)",
                  (uid, "VNM", sec, "", rows_, "2023 VND"))
    return c


def _thu_tu(conn, alias) -> list[str]:
    it = parse_intent(CAU, ALIAS)          # S0 luôn cần alias để phân giải mã
    o1 = HardFilterGenerator().generate(conn, CAU, it)
    o2 = Bm25StructuralRanker(alias, top_k=10,
                              alias_rong_co_y=not alias).rank(conn, CAU, it, o1)
    return [r.table_uid for r in o2.ranked]


def test_thieu_alias_keo_bang_thong_tin_chung_len_dau(conn):
    """Đây là CƠ CHẾ của −9 điểm hit@1, không phải một tương quan.

    Cùng một câu, cùng S1, cùng bảng — khác DUY NHẤT `alias` truyền vào S2.
    """
    assert _thu_tu(conn, ALIAS)[0] == "dung"
    assert _thu_tu(conn, {})[0] == "nhieu", \
        "nếu test này không còn tái hiện được, hãy sửa fixture chứ đừng bỏ nó"


def test_trace_phoi_ra_co_nap_alias_hay_khong(conn):
    """Lỗi cũ sống được vì KHÔNG có dấu vết nào trong dữ liệu đo."""
    it = parse_intent(CAU, ALIAS)
    o1 = HardFilterGenerator().generate(conn, CAU, it)
    co = Bm25StructuralRanker(ALIAS).rank(conn, CAU, it, o1)
    khong = Bm25StructuralRanker({}, alias_rong_co_y=True).rank(conn, CAU, it, o1)
    assert co.trace["alias_loaded"] is True and co.trace["n_drop"] == 3
    assert khong.trace["alias_loaded"] is False and khong.trace["n_drop"] == 1


# ─────────────────────────────────────────────────────────────────────────────
# 3 · MỘT đường code
# ─────────────────────────────────────────────────────────────────────────────

def test_pipeline_run_trung_khop_stages(conn):
    r = run(conn, CAU, ALIAS, top_k=10)
    assert [h.cand.table_uid for h in r.hits] == _thu_tu(conn, ALIAS)
    assert r.s1_uids == HardFilterGenerator().generate(
        conn, CAU, parse_intent(CAU, ALIAS)).uids
    assert r.n_s1 == len(r.s1_uids)


def test_pipeline_khong_dung_gia_tri_gia(conn):
    """`Scored` trả ra phải là đối tượng THẬT của `rank_s2`, không phải bản dựng
    lại với `bm25=0.0`/`period_hit=False` — xem `RankedItem.scored`."""
    r = run(conn, CAU, ALIAS, top_k=10)
    assert r.hits
    assert any(h.bm25 != 0.0 for h in r.hits)
    assert any(h.period_hit for h in r.hits), "kỳ 2023-12-31 có trong cả hai bảng"


def test_luat_drop_chi_dinh_nghia_o_dung_mot_cho():
    """Chống trôi dạt bằng CẤU TRÚC: chỉ được có một `def drop_terms`, và không
    tệp nào khác được tự dựng lại luật đó."""
    dinh_nghia = []
    for p in sorted((ROOT / "src/text2pandas/pipelines/retrieval").rglob("*.py")):
        tree = ast.parse(p.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name in (
                    "drop_terms", "_drop_terms"):
                dinh_nghia.append(str(p.relative_to(ROOT)))
    # Không ghim `lineno`: nó đỏ mỗi lần sửa chú thích phía trên, và một test đỏ
    # vì lý do vô nghĩa là một test sẽ bị bỏ qua.
    assert dinh_nghia == ["src/text2pandas/pipelines/retrieval/query_terms.py"], dinh_nghia


def test_runner_truyen_alias_vao_ranker():
    """Sửa `stages.py` mà quên truyền `alias` ở `runner.py` = bản sửa vô tác dụng.

    Kiểm bằng AST chứ không bằng chuỗi, để không đỏ vì đổi cách xuống dòng.
    Chấp nhận CẢ HAI dạng: `alias` vị trí (dạng hiện tại, bắt buộc) hoặc
    `alias=` keyword (dạng cũ) — test này khoá SỰ CÓ MẶT, không khoá phong cách.
    """
    tree = ast.parse((ROOT / "src/text2pandas/pipelines/retrieval/evalkit/runner.py")
                     .read_text(encoding="utf-8"))
    goi = [n for n in ast.walk(tree)
           if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
           and n.func.id == "Bm25StructuralRanker"]
    assert goi, "không tìm thấy chỗ dựng ranker trong runner.py"
    for n in goi:
        assert n.args or "alias" in {k.arg for k in n.keywords}, \
            f"runner.py:{n.lineno} dựng ranker KHÔNG có alias — regression P0-1"


# ─────────────────────────────────────────────────────────────────────────────
# 4 · đổi hành vi S2 thì BẮT BUỘC bump SCHEMA_VERSION
# ─────────────────────────────────────────────────────────────────────────────

# Các module quyết định S1+S2 trả về CÁI GÌ và theo THỨ TỰ NÀO.
_MODULE_HANH_VI = (
    "src/text2pandas/pipelines/retrieval/query_terms.py",
    "src/text2pandas/pipelines/retrieval/filter_s1.py",
    "src/text2pandas/pipelines/retrieval/rank_s2.py",
    "src/text2pandas/pipelines/retrieval/metric_hint.py",
    "src/text2pandas/pipelines/retrieval/normalize.py",
    "src/text2pandas/pipelines/retrieval/question_intent.py",
    "src/text2pandas/pipelines/retrieval/subject.py",
    "src/text2pandas/pipelines/retrieval/evalkit/stages.py",
)

# fingerprint ↔ SCHEMA_VERSION. Đổi code hành vi ⇒ đổi CẢ HAI.
#
# NHẬT KÝ số ghim của `evalkit-2` — mỗi lần đổi phải kèm bằng chứng trung tính:
#   e5c8eb925e4bce04  P0-1/P0-2 (bản sửa `drop_terms`)
#   7527d06f1fccf03d  P0-3/P0-4 · `alias` thành tham số bắt buộc + `_CHUNK`
#                     assert + ghi lỗi gold. KHÔNG bump SCHEMA_VERSION vì
#                     `tools/verify_no_behavior_change.py --tag base --n 150`
#                     phát lại 150 câu trải đều và cho ĐỒNG NHẤT từng câu
#                     (s1_n, s2_n, s3_n, hits_at_rank, hits_at_final, gold).
#   dce65cd2bfaf25e0  P0-4 · thêm `stop_mode` ("fold" mặc định = hành vi cũ,
#                     "dau" sửa va chạm bỏ dấu của STOP). Trung tính ở mặc
#                     định — verify_no_behavior_change --tag base ĐỒNG NHẤT.
#   89cd3974d9ad7579  Folder refactor: chỉ đổi namespace/path module sang
#                     `text2pandas.pipelines.retrieval`; AST hành vi giữ nguyên.
_FINGERPRINT = {
    "evalkit-2": "dce65cd2bfaf25e0",
    "evalkit-3": "89cd3974d9ad7579",
    "evalkit-4": "86484532462fa1e2",
    "evalkit-5": "15d2ac63090c4be4",
    "evalkit-6": "6d98371c9d8ccda1",
    "evalkit-7": "e9546da2b2676a28",
}

_FIELD = {ast.Constant: "value", ast.Name: "id", ast.Attribute: "attr",
          ast.arg: "arg", ast.FunctionDef: "name", ast.ClassDef: "name",
          ast.keyword: "arg"}


def _strip_doc(tree: ast.AST) -> ast.AST:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef,
                             ast.AsyncFunctionDef)):
            b = node.body
            if b and isinstance(b[0], ast.Expr) and \
                    isinstance(b[0].value, ast.Constant) and \
                    isinstance(b[0].value.value, str):
                node.body = b[1:]
    return tree


def behavior_fingerprint() -> str:
    """Băm DẠNG THU GỌN của AST, không phải `ast.dump`.

    `ast.dump` in mọi trường của mọi node, nên đầu ra ĐỔI THEO PHIÊN BẢN Python
    (3.12 thêm `type_params`, …). Máy build chạy 3.10.12; test này phải cho cùng
    kết quả ở mọi 3.10+, nếu không nó sẽ đỏ vì lý do vô nghĩa và bị bỏ qua.

    Nên chỉ lấy: tên lớp node + đúng một trường mang ngữ nghĩa. Chú thích và
    docstring KHÔNG tính (sửa chú thích không đổi hành vi).

    GIỚI HẠN ĐÃ BIẾT: không phủ `alias_store.py` và tệp dữ liệu alias. Alias là
    DỮ LIỆU; `brands` đã nằm trong `cfg.sha`, còn nội dung tệp alias đổi thì
    fingerprint này KHÔNG bắt được.
    """
    import hashlib
    h = hashlib.sha256()
    for rel in _MODULE_HANH_VI:
        h.update(rel.encode())
        tree = _strip_doc(ast.parse((ROOT / rel).read_text(encoding="utf-8")))
        for node in ast.walk(tree):
            h.update(type(node).__name__.encode())
            f = _FIELD.get(type(node))
            if f is not None:
                h.update(repr(getattr(node, f, None)).encode())
    return h.hexdigest()[:16]


def test_behavior_fingerprint():
    """Nếu test này đỏ, KHÔNG được chỉ cập nhật con số.

    `cfg_sha` băm cấu hình, KHÔNG băm code. `_done()` bỏ qua mọi câu đã có dòng
    cùng `cfg_sha`, nên sửa hành vi xếp hạng mà không bump `SCHEMA_VERSION` sẽ
    khiến `collect` báo "đã đo đủ 1.012 câu" và `report` in lại số của bản CŨ.

    Quy trình đúng khi đỏ:
      1. thay đổi có đổi hành vi S1/S2 không?
         CÓ    → bump `SCHEMA_VERSION` trong `runner.py`, rồi cập nhật số ở đây,
                 rồi CHẠY LẠI `collect` cho mọi tag.
         KHÔNG → (đổi tên biến, tách hàm, …) chỉ cập nhật số ở đây.
      2. ghi vào `docs/` lý do bump, để đọc checkpoint cũ còn biết nó đo cái gì.
    """
    assert _FINGERPRINT.get(SCHEMA_VERSION) == behavior_fingerprint(), (
        f"code hành vi và SCHEMA_VERSION không khớp.\n"
        f"  SCHEMA_VERSION = {SCHEMA_VERSION}\n"
        f"  fingerprint ghim = {_FINGERPRINT.get(SCHEMA_VERSION)}\n"
        f"  fingerprint thật = {behavior_fingerprint()}\n"
        f"đọc docstring của test này trước khi sửa."
    )
