"""Operation gate v3.1 — trả lời "cần TÍNH gì", tách khỏi "đáp án mang KIỂU gì".

`answer_contract.classify_question` = output contract (kiểu/đơn vị đáp án).
Module này    = operation contract (phép toán). Hai câu hỏi khác nhau.

BỐN SỬA P0 CỦA VÒNG v3 (docs/110):
  P0-1  `allow` phụ thuộc thật vào AST consistency, có reason code.
  P0-2  `tổng` chỉ được xét TRONG MỆNH ĐỀ CHỈ TIÊU, sau khi CHE tên pháp nhân.
  P0-3  Sinh precheck bằng generator có đường dẫn tường minh (file riêng).
  P0-4  Bản ghi mang đủ provenance để truy ngược quyết định.

SỬA P0 CỦA VÒNG v3.1 (docs/112 §4):
  P0-5  `total_signal_scope` KHÔNG còn suy ra từ vị trí trước/sau thực thể đầu
        tiên. Với TỪNG span của chữ `tổng`:
            span ⊂ một entity_span                -> ENTITY_NAME (bỏ qua)
            span ⊄ mọi entity_span, đầu là danh từ
              pháp nhân (`công ty`, `CTCP`, …)    -> UNMATCHED_ENTITY_NAME (fail-closed)
            span ⊄ mọi entity_span, đầu là danh từ
              chỉ tiêu tài chính                  -> METRIC
            còn lại                               -> UNKNOWN (fail-closed)
        `ENTITY_NAME` CHỈ khi span thật sự nằm trong entity span.
  P0-6  MỌI span `tổng` đều được lưu trong `total_signals[]`; không còn chỉ giữ
        match đầu tiên. Một câu có thể vừa có ENTITY_NAME vừa có METRIC.

CHỈ ĐỌC. Không sửa đáp án, không nối vào resolver hay bộ đóng gói.
"""
from __future__ import annotations

import ast
import re
import unicodedata
from dataclasses import dataclass, field

RULE_VERSION = "operation_rule_v3_1"

# ── ENUM DUY NHẤT, có version ──────────────────────────────────────────────
OPERATIONS = (
    "DIRECT_LOOKUP", "DIFFERENCE", "SUM", "AVERAGE", "RATIO_MULTIPLE", "PERCENTAGE",
    "COUNT", "DURATION", "ARGMIN_MAX_FILTER", "MULTI_PERIOD", "MULTI_TABLE",
    "RATE_LOOKUP", "RATE_COMPUTE", "COMPOUND", "UNKNOWN",
)
# Trạng thái từng nhãn trong H0 — không để enum chết không giải thích (docs/110 §11).
ENUM_STATUS = {
    "DIRECT_LOOKUP": "EMITTED", "DIFFERENCE": "EMITTED", "SUM": "EMITTED",
    "AVERAGE": "EMITTED", "RATIO_MULTIPLE": "EMITTED", "PERCENTAGE": "EMITTED",
    "COUNT": "EMITTED", "ARGMIN_MAX_FILTER": "EMITTED", "MULTI_PERIOD": "EMITTED",
    "MULTI_TABLE": "EMITTED", "COMPOUND": "EMITTED", "UNKNOWN": "EMITTED",
    "DURATION": "EMITTED_IF_PRESENT",
    "RATE_COMPUTE": "EMITTED_IF_PRESENT",
    "RATE_LOOKUP": "RESERVED_FOR_PLANNER",   # H0 chưa có đường phát sinh
}
COMPLEXITY = ("SINGLE_STEP", "MULTI_STEP", "UNKNOWN")
PARSE_STATUS = ("OK", "MISSING", "NOT_APPLICABLE", "PARSE_FAILED")

AST_REASONS = ("AST_OK", "AST_EMPTY_QUERY", "AST_PARSE_FAILED", "AST_NOT_SINGLE_SELECTION",
               "AST_HAS_AGGREGATION", "AST_HAS_MULTI_CELL_ARITHMETIC",
               "AST_HAS_UNVERIFIED_SCALE_OP", "AST_UNKNOWN_VARIABLE",
               "AST_MULTIPLE_DATAFRAMES")


def _fold(s: str) -> str:
    """Bỏ dấu + hạ chữ — GIỮ NGUYÊN ĐỘ DÀI để span còn ánh xạ được."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    out = []
    for ch in s:
        if unicodedata.category(ch) == "Mn":
            continue
        out.append("d" if ch == "đ" else ch)
    t = "".join(out)
    return re.sub(r"[^a-z0-9 ]", " ", t)


def _chuan(s: str) -> str:
    return unicodedata.normalize("NFC", (s or "")).lower()


# ═══ 1 · THỰC THỂ — chuẩn hoá theo SPAN ════════════════════════════════════
@dataclass(frozen=True)
class EntityHit:
    canonical_id: str
    span: tuple
    matched_text: str
    kind: str            # company_name | core_name | literal_ticker


def entity_hits(question: str, companies, known: set) -> tuple[list, list, str]:
    """Trả (hits đã chuẩn hoá, ứng viên thô, parse_status).

    Vì sao cần: `len(slots.tickers)` đếm ALIAS thành nhiều doanh nghiệp.
      q112 "Công ty Cổ phần Viễn thông FPT (FOX)" -> FPT + FOX  (thực ra MỘT)
      q212 "…Hoàng Anh Gia Lai" (HNG) chứa "Hoàng Anh Gia Lai" (HAG) -> hai
    Luật: bỏ ứng viên có span NẰM TRONG span của ứng viên khác.
    """
    fq = _fold(question)
    tho: list[EntityHit] = []
    for ticker, folded in getattr(companies, "_folded", []):
        if folded and folded in fq:
            i = fq.index(folded)
            tho.append(EntityHit(ticker, (i, i + len(folded)), folded, "company_name"))
    for ticker, core in getattr(companies, "_core", []):
        if len(core) >= 8 and core in fq:
            i = fq.index(core)
            tho.append(EntityHit(ticker, (i, i + len(core)), core, "core_name"))
    for m in re.finditer(r"\b([a-z][a-z0-9]{2,3})\b", fq):
        t = m.group(1).upper()
        if t in known:
            tho.append(EntityHit(t, m.span(1), m.group(1), "literal_ticker"))

    # bỏ span bị CHỨA TRONG span khác của ticker KHÁC
    giu = []
    for h in tho:
        bi_chua = any(o.canonical_id != h.canonical_id
                      and o.span[0] <= h.span[0] and h.span[1] <= o.span[1]
                      and (o.span[1] - o.span[0]) > (h.span[1] - h.span[0])
                      for o in tho)
        if not bi_chua:
            giu.append(h)
    # gộp theo canonical_id, giữ span dài nhất
    theo_id: dict[str, EntityHit] = {}
    for h in giu:
        cu = theo_id.get(h.canonical_id)
        if cu is None or (h.span[1] - h.span[0]) > (cu.span[1] - cu.span[0]):
            theo_id[h.canonical_id] = h
    hits = sorted(theo_id.values(), key=lambda h: h.span)
    st = "OK" if hits else ("PARSE_FAILED" if not tho else "MISSING")
    return hits, sorted({h.canonical_id for h in tho}), st


def che_thuc_the(question: str, hits: list) -> str:
    """Thay span tên pháp nhân bằng khoảng trắng — CHE trước khi tìm `tổng`."""
    fq = _fold(question)
    ky_tu = list(fq)
    for h in hits:
        for i in range(h.span[0], min(h.span[1], len(ky_tu))):
            ky_tu[i] = " "
    return "".join(ky_tu)


# ═══ 2 · TỪ VỰNG PHÉP TOÁN ═════════════════════════════════════════════════
TIN_HIEU: list[tuple[str, str, str]] = [
    ("COUNT",       "dem_thuc_the",  r"co bao nhieu (nam|cong ty|doanh nghiep|ma|don vi|khoan)|"
                                     r"bao nhieu (nam|cong ty|doanh nghiep|ma) (nao|sau|thoa|dap)|"
                                     r"\bco may\b|so luong (cong ty|doanh nghiep|ma)"),
    ("DURATION",    "khoang_tg",     r"bao nhieu ngay|bao nhieu thang|keo dai"),
    ("PERCENTAGE",  "phan_tram",     r"phan tram|\bty le\b|\bty trong\b|chiem bao nhieu|%"),
    ("RATIO_MULTIPLE", "bao_nhieu_lan", r"bao nhieu lan|gap bao nhieu|gap may"),
    ("RATIO_MULTIPLE", "ty_so",      r"\bty so\b|\bti so\b|\btinh (ty|ti) so\b"),
    ("RATE_COMPUTE","lai_suat_tinh", r"lai suat (binh quan|trung binh|thuc)"),
    ("DIFFERENCE",  "chenh_lech",    r"chenh lech|chenh nhau"),
    ("DIFFERENCE",  "hieu_so",       r"\bhieu so\b|\btinh hieu\b|\bhieu giua\b|\btru di\b"),
    # Cửa sổ 80 ký tự: "lớn hơn CỦA CTCP Phát triển Bất động sản Văn Phú bao nhiêu"
    # dài hơn 40 (q736). Và "hơn" TRẦN cũng là so sánh: "…Eximbank hơn MBBank mấy…" (q792).
    ("DIFFERENCE",  "hon_kem",       r"(lon hon|be hon|nho hon|kem hon|nhieu hon|it hon|cao hon|thap hon)"
                                     r"[^.?]{0,80}?\b(bao nhieu|may)\b"),
    ("DIFFERENCE",  "hon_tran",      r"\bhon\b[^.?]{0,80}?\b(bao nhieu|may)\b"),
    ("DIFFERENCE",  "so_voi_hon",    r"so voi[^.?]{0,60}?(cao hon|thap hon|lon hon|nho hon)"),
    ("DIFFERENCE",  "muc_tang_giam", r"muc tang|muc giam|\btang bao nhieu\b|\bgiam bao nhieu\b|"
                                     r"thay doi giua hai ky|bien dong giua hai ky"),
    ("AVERAGE",     "binh_quan",     r"binh quan|trung binh"),
    ("ARGMIN_MAX_FILTER", "cuc_tri", r"cao nhat|thap nhat|lon nhat|nho nhat|nhieu nhat|it nhat"),
    ("MULTI_TABLE", "loc_nhom",      r"trong (cac|nhom|so) (doanh nghiep|cong ty|ma)|thoa man|dap ung|"
                                     r"nhung (cong ty|doanh nghiep|ma) (co|ma)"),
]
HOI_MOT_GIA_TRI = r"(la|bang|dat|o muc) bao nhieu|bao nhieu (dong|trieu|ty|nghin)"
TONG = r"\btong\b"
CONG_DON = r"tong (cua )?[^.?]{0,40}\bva\b"     # "tổng A và B" -> phép cộng thật


# ═══ 2b · PHẠM VI CỦA CHỮ `tổng` — exact span (docs/112 §4) ════════════════
TOTAL_SCOPES = ("ENTITY_NAME", "METRIC", "TITLE_LEXICAL",
                "UNMATCHED_ENTITY_NAME", "UNKNOWN")
# Thứ tự GỘP nhiều signal — fail-closed trước, `ENTITY_NAME` sau cùng.
UU_TIEN_GOP = ("METRIC", "UNKNOWN", "UNMATCHED_ENTITY_NAME",
               "TITLE_LEXICAL", "ENTITY_NAME")

# Đầu ngữ PHÁP NHÂN: `Tổng Công ty`, `Tổng Cục`… KHÔNG phải phép cộng, nhưng
# cũng KHÔNG được gán ENTITY_NAME khi span nằm ngoài mọi entity span đã nhận
# diện — pháp nhân chưa khớp catalog ⇒ fail-closed.
DAU_NGU_PHAP_NHAN = (
    "cong ty", "cong ti", "cty", "ctcp", "ngan hang", "tap doan",
    "cong doan", "lien doan", "hop tac xa", "cuc", "hoi dong", "kho bac",
)
# Đầu ngữ CHỨC DANH: `Tổng Giám đốc`, `Tổng Thư ký`… `tổng` bị RÀNG BUỘC TỪ
# VỰNG trong một danh ngữ cố định, không bao giờ là toán tử cộng và cũng không
# phải tên pháp nhân ⇒ bỏ qua như ENTITY_NAME nhưng ghi nhãn riêng để audit.
DAU_NGU_CHUC_DANH = (
    "giam doc", "thu ky", "bien tap", "thanh tra", "lanh su", "cong trinh su",
    "tham muu truong", "chi huy", "quan ly",
)
# Đầu ngữ CHỈ TIÊU tài chính. Danh sách rút từ chính corpus 1.012 câu hỏi:
# histogram token đứng ngay sau mọi span `tổng` nằm ngoài entity span
# (xem `total_scope_audit.json` → `head_token_histogram`).
DAU_NGU_CHI_TIEU = (
    "cong", "cua",          # `tổng cộng …`, `tổng của A và B` — phải sau PHÁP NHÂN
    "tai san", "chi phi", "doanh thu", "gia tri", "gia von", "gia goc",
    "so du", "so tien", "so luong", "so tra", "so phai", "so thue", "so tai",
    "so cong", "so no", "loi nhuan", "loi ich", "du no", "du phong", "du tien",
    "du luong", "no phai", "no ngan", "no dai", "no vay", "no tai",
    "nguon von", "phai thu", "phai tra", "thu lao", "thu nhap", "tien",
    "von", "cam ket", "quy", "thue", "luu chuyen", "ty le", "ty trong",
    "trai phieu", "cac khoan", "khoan", "nguyen gia", "tra truoc", "cho vay",
    "dau tu", "chung khoan", "han muc", "phat hanh", "muc tang", "muc giam",
    "vay", "giay to", "lai", "co tuc", "hang ton kho", "cong no", "muc",
    "gia", "tien luong",
)


@dataclass(frozen=True)
class TotalSignal:
    span: tuple           # (đầu, cuối) trong toạ độ _fold(question)
    scope: str            # ∈ TOTAL_SCOPES
    linked_entity_id: str | None
    linked_metric: str | None
    head_text: str        # tối đa 3 token ngay sau `tổng`, để audit


def _dau_ngu(head: str, tu_dien: tuple) -> str | None:
    """Khớp đầu ngữ theo RANH GIỚI TỪ, ưu tiên cụm dài nhất — tránh `cong` nuốt
    `cong ty`. Trả về đầu ngữ khớp, hoặc None."""
    kq = [p for p in tu_dien if head == p or head.startswith(p + " ")]
    return max(kq, key=len) if kq else None


def quet_tin_hieu_tong(question: str, hits: list) -> list:
    """Trả về MỌI span của `tổng` kèm phạm vi, quyết định bằng span containment.

    docs/112 §4.3: `ENTITY_NAME` chỉ hợp lệ khi span nằm TRỌN trong một
    entity span. Span nằm ngoài mọi entity span KHÔNG được tự bỏ qua.
    """
    fq = _fold(question)
    ra: list[TotalSignal] = []
    for m in re.finditer(TONG, fq):
        s, e = m.span()
        chua = next((h for h in hits if h.span[0] <= s and e <= h.span[1]), None)
        head = " ".join(fq[e:e + 40].split()[:3])
        if chua is not None:
            ra.append(TotalSignal((s, e), "ENTITY_NAME", chua.canonical_id, None, head))
            continue
        if _dau_ngu(head, DAU_NGU_PHAP_NHAN):
            ra.append(TotalSignal((s, e), "UNMATCHED_ENTITY_NAME", None, None, head))
            continue
        if _dau_ngu(head, DAU_NGU_CHUC_DANH):
            ra.append(TotalSignal((s, e), "TITLE_LEXICAL", None, None, head))
            continue
        chi_tieu = _dau_ngu(head, DAU_NGU_CHI_TIEU)
        if chi_tieu:
            ra.append(TotalSignal((s, e), "METRIC", None, chi_tieu, head))
        else:
            ra.append(TotalSignal((s, e), "UNKNOWN", None, None, head))
    return ra


def gop_pham_vi_tong(signals: list) -> str:
    """Gộp nhiều signal thành một nhãn tương thích ngược.

    Ưu tiên fail-closed theo `UU_TIEN_GOP`. Nhờ vậy `ENTITY_NAME` chỉ xuất hiện
    khi TẤT CẢ span đều nằm trong entity span — đúng acceptance docs/112 §4.6.
    """
    sc = {s.scope for s in signals}
    for uu in UU_TIEN_GOP:
        if uu in sc:
            return uu
    return "NONE"


# ═══ 3 · AST — cổng NHẤT QUÁN PHỤ ══════════════════════════════════════════
AGG = {"sum", "mean", "count", "min", "max", "median", "std", "groupby", "sort_values", "agg", "len"}
LUY_THUA_10 = {1, 10, 100, 1000, 10**6, 10**9, 10**12, 1e1, 1e2, 1e3, 1e6, 1e9, 1e12}


@dataclass(slots=True)
class QueryShape:
    n_dataframes: int = 0
    n_selections: int = 0
    n_aggregations: int = 0
    n_scale_ops: int = 0
    n_other_arith: int = 0
    accessors: tuple = ()
    variables: tuple = ()
    unknown_variables: tuple = ()
    parse_ok: bool = False
    empty: bool = True
    reason: str = "AST_EMPTY_QUERY"

    @property
    def la_mot_o(self) -> bool:
        return self.reason == "AST_OK"


def phan_tich_ast(query: str, evidence_vars=None) -> QueryShape:
    """PARSE, không eval. Tên biến LẤY TỪ AST rồi đối chiếu evidence —
    không tin con số do người gọi khai (docs/110 §12)."""
    cho_phep = set(evidence_vars or [])
    qs = QueryShape()
    if not (query or "").strip():
        return qs
    qs.empty = False
    try:
        tree = ast.parse(query, mode="eval")
    except SyntaxError:
        qs.reason = "AST_PARSE_FAILED"
        return qs
    qs.parse_ok = True

    def _mat_na(x) -> bool:
        return isinstance(x, (ast.Compare, ast.BoolOp)) or (
            isinstance(x, ast.BinOp) and isinstance(x.op, (ast.BitAnd, ast.BitOr, ast.BitXor)))

    acc, bien = [], set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Name):
            if n.id not in ("float", "int", "abs", "round"):
                bien.add(n.id)
        if isinstance(n, ast.Subscript):
            sl = n.slice
            if _mat_na(sl) or (isinstance(sl, ast.Tuple) and any(_mat_na(e) for e in sl.elts)):
                qs.n_selections += 1
        if isinstance(n, ast.Attribute):
            if n.attr in AGG:
                qs.n_aggregations += 1
            if n.attr in ("loc", "iloc", "at", "iat", "values"):
                acc.append(n.attr)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in AGG:
            qs.n_aggregations += 1
        if isinstance(n, ast.BinOp):
            if isinstance(n.op, (ast.BitAnd, ast.BitOr, ast.BitXor)):
                continue                      # mặt nạ boolean, không phải số học
            hs = getattr(n, "right", None)
            l10 = (isinstance(hs, ast.Constant) and isinstance(hs.value, (int, float))
                   and hs.value != 0 and abs(hs.value) in LUY_THUA_10)
            if isinstance(n.op, (ast.Div, ast.Mult)) and l10:
                qs.n_scale_ops += 1
            elif isinstance(n.op, (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow,
                                   ast.Mod, ast.FloorDiv)):
                qs.n_other_arith += 1
    qs.accessors = tuple(sorted(set(acc)))
    qs.variables = tuple(sorted(bien))
    qs.unknown_variables = tuple(sorted(bien - cho_phep)) if cho_phep else ()
    qs.n_dataframes = len(bien)

    if qs.unknown_variables:
        qs.reason = "AST_UNKNOWN_VARIABLE"
    elif qs.n_dataframes > 1:
        qs.reason = "AST_MULTIPLE_DATAFRAMES"
    elif qs.n_aggregations:
        qs.reason = "AST_HAS_AGGREGATION"
    elif qs.n_other_arith:
        qs.reason = "AST_HAS_MULTI_CELL_ARITHMETIC"
    elif qs.n_selections != 1:
        qs.reason = "AST_NOT_SINGLE_SELECTION"
    elif qs.n_scale_ops > 1:
        qs.reason = "AST_HAS_UNVERIFIED_SCALE_OP"
    else:
        qs.reason = "AST_OK"
    return qs


# ═══ 4 · QUYẾT ĐỊNH ════════════════════════════════════════════════════════
@dataclass(slots=True)
class AnswerOperationDecision:
    qid: int
    output_spec: dict
    primary_operation: str
    sub_operations: list = field(default_factory=list)
    complexity_class: str = "UNKNOWN"
    operation_signals: list = field(default_factory=list)
    negative_signals: list = field(default_factory=list)
    positive_evidence: list = field(default_factory=list)
    entity_candidates: list = field(default_factory=list)
    canonical_entity_ids: list = field(default_factory=list)
    entity_spans: list = field(default_factory=list)
    entity_count: int = 0
    entity_parse_status: str = "PARSE_FAILED"
    period_values: list = field(default_factory=list)
    period_spans: list = field(default_factory=list)
    period_count: int = 0
    period_parse_status: str = "PARSE_FAILED"
    metric_span: list = field(default_factory=list)
    metric_span_confidence: str = "LOW"
    total_signal_span: list = field(default_factory=list)
    total_signal_scope: str = "NONE"
    total_signals: list = field(default_factory=list)
    n_total_spans: int = 0
    selected_row_path: str = ""
    query_shape: dict = field(default_factory=dict)
    ast_consistent: bool = False
    ast_reason: str = "AST_EMPTY_QUERY"
    allow_a6_single_cell: bool = False
    decision_reason: str = ""
    review_required: bool = True
    rule_version: str = RULE_VERSION


def _sap_xep(subs: set) -> list:
    return [o for o in OPERATIONS if o in subs]


def phan_loai(qid, question, spec, *, companies=None, known=None,
              years=None, selected_row_path=None, query=None, evidence_vars=None,
              entity_override=None):
    hits, tho, e_st = ((entity_override, [h.canonical_id for h in entity_override], "OK")
                       if entity_override is not None
                       else entity_hits(question, companies, known or set()))
    n_entity = len(hits)
    che = che_thuc_the(question, hits)              # ← tên pháp nhân ĐÃ BỊ CHE

    years = sorted(set(years or [int(y) for y in re.findall(r"\b(20[0-2]\d)\b", question)]))
    p_st = "OK" if years else "PARSE_FAILED"
    n_period = len(years)

    out = {"question_output_kind": spec.value_kind, "arity": spec.arity,
           "unit_exponent": spec.unit_exponent, "unit_label": spec.unit_label,
           "flags": list(spec.flags), "evidence": spec.evidence}

    # ── mệnh đề CHỈ TIÊU = phần trước tên pháp nhân đầu tiên ───────────────
    m_end = hits[0].span[0] if hits else len(che)
    metric_span = [0, m_end]
    metric_clause = che[:m_end]
    # docs/112 §6: heuristic prefix chỉ đúng với dạng `<metric> của <company>`.
    # Ghi rõ độ tin cậy để audit theo rủi ro, KHÔNG dùng để nới allow gate.
    if not hits or not metric_clause.strip():
        metric_conf = "LOW"
    elif any(p in metric_clause for p in DAU_NGU_CHI_TIEU):
        metric_conf = "HIGH"
    else:
        metric_conf = "MEDIUM"

    # ── P0-5/P0-6 · phạm vi của TỪNG chữ `tổng`, theo exact span ──────────
    tin_hieu_tong = quet_tin_hieu_tong(question, hits)
    tong_scope = gop_pham_vi_tong(tin_hieu_tong)
    tong_span = next((list(s.span) for s in tin_hieu_tong if s.scope == tong_scope), [])
    tong_ds = [{"span": list(s.span), "scope": s.scope,
                "linked_entity_id": s.linked_entity_id,
                "linked_metric": s.linked_metric, "head_text": s.head_text}
               for s in tin_hieu_tong]

    qshape = phan_tich_ast(query or "", evidence_vars)
    qd = {"n_dataframes": qshape.n_dataframes, "n_selections": qshape.n_selections,
          "n_aggregations": qshape.n_aggregations, "n_scale_ops": qshape.n_scale_ops,
          "n_other_arith": qshape.n_other_arith, "accessors": list(qshape.accessors),
          "variables": list(qshape.variables), "unknown_variables": list(qshape.unknown_variables),
          "parse_ok": qshape.parse_ok, "single_cell_shape": qshape.la_mot_o}

    hits_sig = [(op, ten) for op, ten, pat in TIN_HIEU if re.search(pat, che)]
    am: list = []
    ev_co_tong = bool(selected_row_path and re.search(TONG, _fold(selected_row_path)))
    for s in tin_hieu_tong:                    # XỬ LÝ TỪNG span, không ghi đè
        if s.scope == "ENTITY_NAME":
            am.append("tong_thuoc_ten_phap_nhan_bo_qua")
        elif s.scope == "TITLE_LEXICAL":
            am.append("tong_thuoc_danh_ngu_chuc_danh_bo_qua")
        elif s.scope == "UNMATCHED_ENTITY_NAME":
            am.append("tong_dang_ten_phap_nhan_ngoai_catalog")
        elif s.scope == "UNKNOWN":
            am.append("tong_khong_xac_dinh_pham_vi")
        elif re.match(CONG_DON, che[s.span[0]:]):
            hits_sig.append(("SUM", "tong_cua_A_va_B"))
        elif ev_co_tong:
            am.append("co_dong_tong_trong_evidence")
        else:
            hits_sig.append(("SUM", "noi_tong_nhung_evidence_khong_co_dong_tong"))
    am = sorted(set(am))
    hits_sig = list(dict.fromkeys(hits_sig))

    subs_ct = set()
    if n_period > 1:
        subs_ct.add("MULTI_PERIOD")
    if n_entity > 1:
        subs_ct.add("MULTI_TABLE")
    if "compound_question" in spec.flags:
        subs_ct.add("COMPOUND")

    def ra(prim, subs, cx, ly, allow=False, rev=True, pos=()):
        s = set(subs) | subs_ct
        s.discard(prim)
        return AnswerOperationDecision(
            qid, out, prim, _sap_xep(s), cx, [h[1] for h in hits_sig], am, list(pos),
            tho, [h.canonical_id for h in hits], [list(h.span) for h in hits], n_entity, e_st,
            years, [], n_period, p_st, metric_span, metric_conf, tong_span, tong_scope,
            tong_ds, len(tong_ds),
            selected_row_path or "", qd, qshape.la_mot_o, qshape.reason, allow, ly, rev)

    if hits_sig:
        prim = hits_sig[0][0]
        subs = {op for op, _ in hits_sig[1:]}
        cx = "MULTI_STEP" if (subs or subs_ct) else "SINGLE_STEP"
        return ra(prim, subs, cx, f"tin hieu phep toan: {[h[1] for h in hits_sig]}")

    if tong_scope in ("UNKNOWN", "UNMATCHED_ENTITY_NAME"):
        return ra("UNKNOWN", set(), "UNKNOWN",
                  f"co chu `tong` nhung pham vi = {tong_scope} (fail-closed)")
    if n_period > 1:
        return ra("MULTI_PERIOD", set(), "MULTI_STEP", f"{n_period} ky")
    if n_entity > 1:
        return ra("MULTI_TABLE", set(), "MULTI_STEP", f"{n_entity} thuc the")
    if "compound_question" in spec.flags:
        return ra("COMPOUND", set(), "MULTI_STEP", "cau ghep")

    pos = []
    if re.search(HOI_MOT_GIA_TRI, che):
        pos.append("hoi_mot_gia_tri")
    if e_st == "OK" and n_entity == 1:
        pos.append("dung_1_thuc_the")
    if p_st == "OK" and n_period == 1:
        pos.append("dung_1_ky")
    if "unit_unstated" not in spec.flags:
        pos.append("don_vi_khai_ro")
    if spec.arity == "scalar" and spec.value_kind in ("money", "share_count"):
        pos.append("output_scalar_tuong_thich")
    thieu = {"hoi_mot_gia_tri", "dung_1_thuc_the", "dung_1_ky",
             "don_vi_khai_ro", "output_scalar_tuong_thich"} - set(pos)
    if thieu:
        return ra("UNKNOWN", set(), "UNKNOWN", f"thieu bang chung duong: {sorted(thieu)}")

    # ── P0-1 · AST GIỜ THẬT SỰ QUYẾT ĐỊNH `allow` ─────────────────────────
    ok = qshape.la_mot_o
    return ra("DIRECT_LOOKUP", set(), "SINGLE_STEP",
              ("du bang chung duong; AST OK" if ok
               else f"du bang chung duong NHUNG AST chan: {qshape.reason}"),
              allow=ok, rev=not ok, pos=pos)
