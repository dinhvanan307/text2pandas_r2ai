"""`unit_rule_v2` — HÀM THUẦN, không phụ thuộc DB / resolver / trạng thái toàn cục.

Đặc tả đã duyệt: `docs/109` §2 (P0-1…P0-6, bảng quyết định §2.7).
Yêu cầu bổ sung của `docs/114` §10–§11.

MÔ HÌNH HAI TRỤC — tuyệt đối không trộn:
    currency   ∈ {VND, USD, EUR, …}      "tiền gì"
    magnitude  ∈ {10^0, 10^3, 10^6, 10^9, 10^12}   "gấp bao nhiêu"

BỐN LỚP BẢO VỆ TOKEN ASCII `ty` (docs/114 §11 — KHÔNG dùng fixed lookbehind):
    L1  entity masking     — xoá span `công ty / cong ty / cty / ctcp / c.ty` và
                             các danh ngữ âm tính (`tỷ lệ`, `tỷ trọng`, `tỷ suất`,
                             `tỷ giá`) TRƯỚC khi dò đơn vị. Bền với nhiều khoảng
                             trắng, gạch nối, dấu chấm, hoa/thường, có/không dấu.
    L2  allowlist phrase   — magnitude CHỈ khớp cụm nằm trong danh sách trắng,
                             không bao giờ khớp một token trần.
    L3  explicit marker    — magnitude trần (`nghìn tỷ` không kèm tiền tệ) chỉ
                             hợp lệ khi đứng sau marker `Đơn vị/ĐVT/unit`.
    L4  context validation — evidence chỉ vào quyết định khi cùng bảng nguồn và
                             hạng ≥ 3 (header cột / khai báo đơn vị của bảng).

FAIL-CLOSED: thiếu bằng chứng, lệch scope, hoặc mâu thuẫn ⇒ KHÔNG mutate.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

RULE_VERSION = "unit_rule_v2_1"

# ═══ 0 · HẰNG SỐ CÔNG KHAI ═════════════════════════════════════════════════
MAGNITUDE_CODES = {"M0": 0, "M3": 3, "M6": 6, "M9": 9, "M12": 12}
CURRENCIES = ("VND", "USD", "EUR", "JPY", "CNY", "KRW", "GBP", "SGD", "AUD")
SUPPORTED_CURRENCY = "VND"

DECISION_CODES = (
    "EXPLICIT_MAGNITUDE_CONFIRMED", "WEAK_EVIDENCE_REVIEW", "SCOPE_MISMATCH",
    "CONFLICTING_MAGNITUDES", "CURRENCY_ONLY_NO_MAGNITUDE", "NON_VND_UNSUPPORTED",
    "CURRENCY_UNRESOLVED", "NO_EVIDENCE", "NOT_APPLICABLE",
    # v2.1 — docs/116 §6
    "OTHER_COLUMN_MAGNITUDE_IGNORED", "SCOPE_METADATA_INVALID",
    "TABLE_DECLARATION_NOT_TABLE_WIDE",
)
FINAL_STATUSES = (
    "CONFIRMED_A6", "A6_DEFECT", "UNRESOLVED_BLOCKED",
    "CONSISTENT_BUT_UNVERIFIED", "FALLBACK_REQUIRED", "NOT_APPLICABLE",
)
CURRENCY_SCOPE = ("SAME_COLUMN", "SAME_TABLE", "OFF_SCOPE", "UNRESOLVED")

# Hạng bằng chứng. ≥ 3 mới đủ tư cách quyết định (docs/109 §2.4).
EVIDENCE_RANK = {
    "column_header": 4,        # header lineage của chính ô nguồn
    "table_unit_declaration": 3,   # "Đơn vị tính: …" của bảng nguồn
    "table_header": 3,
    "section_text": 2,
    "document_context": 1,
    "other_table": 0,
}
RANK_TOI_THIEU = 3


# ═══ 1 · CHUẨN HOÁ ═════════════════════════════════════════════════════════
def _can_tach(t: str, ch: str) -> bool:
    """RANH GIỚI DÍNH — chỉ xét sau khi ĐÃ bỏ dấu, nên chỉ còn chữ ASCII.

    Header trong corpus thường bị dính khi trích: `31.12.2022Triệu VND`,
    `Năm nayTriệu đồng`, `Số cuối nămVND`. Không tách thì `\\b` không bao giờ khớp.
    """
    return ((t.isdigit() and ch.isalpha()) or (t.isalpha() and ch.isdigit())
            or (t.islower() and ch.isupper()))


def _bang_bo_dau() -> dict:
    """Bảng dịch bỏ dấu, dựng một lần lúc import."""
    b = {}
    for cp in range(0x00C0, 0x1EFA):
        ch = chr(cp)
        goc = "".join(c for c in unicodedata.normalize("NFD", ch)
                      if unicodedata.category(c) != "Mn")
        if goc and goc != ch:
            b[cp] = goc
    b[ord("đ")], b[ord("Đ")] = "d", "D"
    return b


_BANG = _bang_bo_dau()
_DAU_PHU = re.compile("[̀-ͯ]")
_KHONG_PHAI = re.compile(r"[^a-z0-9:]")
# Sau khi bỏ dấu chỉ còn chữ ASCII nên ba pattern dưới là CHÍNH XÁC.
_DINH = (
    re.compile(r"(?<=[0-9])(?=[A-Za-z])"),      # số → chữ
    re.compile(r"(?<=[A-Za-z])(?=[0-9])"),      # chữ → số
    re.compile(r"(?<=[a-z])(?=[A-Z])"),         # thường → HOA
)


def normalize_unit(text: str) -> str:
    """Bỏ dấu → tách ranh giới dính → hạ chữ → ký tự khác thành khoảng trắng.

    Nhờ vậy `Công-ty`, `Công   ty`, `CONG TY`, `Cong.ty`, `Công.Ty` đều quy về
    `cong ty` và MỘT pattern bắt được mọi biến thể — không cần lookbehind.

    Đường nhanh, toàn thao tác mức C. Kết quả PHẢI trùng với
    `normalize_unit_with_map(...)[0]` — có test khoá lại điều đó.
    """
    s = _DAU_PHU.sub("", (text or "").translate(_BANG))
    for pat in _DINH:
        s = pat.sub(" ", s)
    return _KHONG_PHAI.sub(" ", s.lower())


def normalize_unit_with_map(text: str) -> tuple[str, list]:
    """Như `normalize_unit` nhưng trả kèm bản đồ về offset chuỗi gốc.

    Mọi `span` mà module này phát ra đều tính trên chuỗi ĐÃ CHUẨN HOÁ
    (`span_basis = "normalized"`). Dùng bản đồ này để ánh xạ ngược khi cần.
    """
    # (1) bỏ dấu TỪNG ký tự, giữ chỉ số gốc
    co_so, mp = [], []
    for i, ch0 in enumerate(text or ""):
        for ch in unicodedata.normalize("NFD", ch0):
            if unicodedata.category(ch) == "Mn":
                continue
            co_so.append("d" if ch == "đ" else ("D" if ch == "Đ" else ch))
            mp.append(i)
    # (2) chèn dấu tách ở ranh giới dính — CÙNG THỨ TỰ với đường nhanh
    out, mp2 = [], []
    for j, ch in enumerate(co_so):
        if j and _can_tach(co_so[j - 1], ch):
            out.append(" ")
            mp2.append(mp[j])
        out.append(ch)
        mp2.append(mp[j])
    # (3) hạ chữ + thay ký tự lạ — cả hai giữ nguyên độ dài
    return _KHONG_PHAI.sub(" ", "".join(out).lower()), mp2


# ═══ 2 · L1 · CHE SPAN KHÔNG PHẢI ĐƠN VỊ ═══════════════════════════════════
# Danh ngữ pháp nhân. `\s+` nuốt mọi số lượng khoảng trắng do gạch nối/dấu
# chấm đã bị normalize_unit đưa về khoảng trắng.
CHAN_PHAP_NHAN = (
    ("COLLISION_CONG_TY", r"\bcong\s+t[yi]\b"),
    ("COLLISION_CONG_TY", r"\bc\s+ty\b"),
    ("COLLISION_CTY", r"\bcty\b"),
    ("COLLISION_CTCP", r"\bctcp\b"),
    ("COLLISION_TCT", r"\btct\b"),
)
# Danh ngữ tỉ lệ: `tỷ` ở đây là "tỉ" trong "tỉ lệ", không phải 10^9.
CHAN_TI_LE = (
    ("COLLISION_TY_LE", r"\bt[yi]\s+le\b"),
    ("COLLISION_TY_TRONG", r"\bt[yi]\s+trong\b"),
    ("COLLISION_TY_SUAT", r"\bt[yi]\s+suat\b"),
    ("COLLISION_TY_GIA", r"\bt[yi]\s+gia\b"),
    ("COLLISION_TY_SO", r"\bt[yi]\s+so\b"),
)
CHAN_TU = CHAN_PHAP_NHAN + CHAN_TI_LE


@dataclass(frozen=True)
class MaskedSpan:
    span: tuple
    kind: str
    matched_text: str


def mask_non_unit_spans(text: str) -> tuple[str, list]:
    """Trả (chuỗi đã chuẩn hoá + CHE, danh sách span bị che).

    Che bằng khoảng trắng nên độ dài không đổi và span còn ánh xạ ngược được.
    """
    chuan = normalize_unit(text)
    ky_tu = list(chuan)
    spans: list[MaskedSpan] = []
    for kind, pat in CHAN_TU:
        for m in re.finditer(pat, chuan):
            spans.append(MaskedSpan(m.span(), kind, m.group(0)))
    for s in spans:
        for i in range(s.span[0], s.span[1]):
            ky_tu[i] = " "
    return "".join(ky_tu), sorted(spans, key=lambda s: s.span)


# ═══ 3 · L2/L3 · TIỀN TỆ VÀ ĐỘ LỚN ═════════════════════════════════════════
TIEN_TE = (
    ("VND", r"\b(?:vnd|dong)\b"),
    ("USD", r"\b(?:usd|dola|do\s+la|us\s+dollar)\b"),
    ("EUR", r"\b(?:eur|euro)\b"),
    ("JPY", r"\b(?:jpy|yen)\b"),
    ("CNY", r"\b(?:cny|rmb|nhan\s+dan\s+te)\b"),
    ("KRW", r"\b(?:krw|won)\b"),
    ("GBP", r"\b(?:gbp|bang\s+anh)\b"),
    ("SGD", r"\bsgd\b"),
    ("AUD", r"\baud\b"),
)

# L2 — allowlist: magnitude LUÔN đi kèm tiền tệ. Không có mục nào là token trần.
CUM_DO_LON = (
    ("M12", r"\b(?:nghin|ngan)\s+t[yi]\s+(?:dong|vnd)\b", 12),
    ("M9", r"\bt[yi]\s+(?:dong|vnd)\b", 9),
    ("M6", r"\btrieu\s+(?:dong|vnd)\b", 6),
    ("M3", r"\b(?:nghin|ngan)\s+(?:dong|vnd)\b", 3),
)
# CHỦ Ý: KHÔNG có mục M0 dạng allowlist. `đồng`/`VND` trần chỉ là TIỀN TỆ, không
# phải khai báo độ lớn — muốn ra 10^0 phải có marker (`Đơn vị: đồng`). Nếu thêm
# `dong viet nam` vào đây thì `Đơn vị tính: Triệu Đồng Việt Nam` sẽ vừa ra M6
# vừa ra M0 và bị chặn nhầm là CONFLICTING_MAGNITUDES.
# L3 — marker cho phép magnitude TRẦN (không kèm tiền tệ).
MARKER = r"(?:don\s+vi(?:\s+tinh)?|dvt|unit)\s*:?\s*"
CUM_MARKER = (
    ("M12", rf"{MARKER}(?:nghin|ngan)\s+t[yi]\b", 12),
    ("M9", rf"{MARKER}t[yi]\b", 9),
    ("M6", rf"{MARKER}trieu\b", 6),
    ("M3", rf"{MARKER}(?:nghin|ngan)\b", 3),
    ("M0", rf"{MARKER}(?:dong|vnd)\b", 0),
)


@dataclass(frozen=True)
class UnitToken:
    kind: str          # "currency" | "magnitude"
    value: str         # "VND" | "M9" | …
    exponent: int | None
    span: tuple
    matched_text: str
    via: str           # "allowlist_phrase" | "explicit_marker"


def parse_explicit_unit(text: str) -> list:
    """Tìm mọi token TIỀN TỆ sau khi đã che span không phải đơn vị."""
    che, _ = mask_non_unit_spans(text)
    ra = []
    for cur, pat in TIEN_TE:
        for m in re.finditer(pat, che):
            ra.append(UnitToken("currency", cur, None, m.span(), m.group(0),
                                "allowlist_phrase"))
    return sorted(ra, key=lambda t: t.span)


def parse_magnitude(text: str) -> list:
    """Tìm mọi token ĐỘ LỚN. Ưu tiên cụm dài nhất; không trả token trần."""
    che, _ = mask_non_unit_spans(text)
    tho = []
    for code, pat, mu in CUM_DO_LON:
        for m in re.finditer(pat, che):
            tho.append(UnitToken("magnitude", code, mu, m.span(), m.group(0),
                                 "allowlist_phrase"))
    for code, pat, mu in CUM_MARKER:
        for m in re.finditer(pat, che):
            tho.append(UnitToken("magnitude", code, mu, m.span(), m.group(0),
                                 "explicit_marker"))
    # Giải CHỒNG LẤN (không chỉ chứa nhau): trái nhất → dài nhất → mũ lớn nhất.
    # `nghìn tỷ đồng` nuốt `tỷ đồng`; `Đơn vị tính: Triệu` nuốt `Triệu Đồng`.
    tho.sort(key=lambda t: (t.span[0], -(t.span[1] - t.span[0]), -(t.exponent or 0)))
    giu, het = [], -1
    for t in tho:
        if t.span[0] >= het:
            giu.append(t)
            het = t.span[1]
    return sorted(giu, key=lambda t: t.span)


# ═══ 4 · BẰNG CHỨNG VÀ NGỮ CẢNH ════════════════════════════════════════════
# v2.1 — mặc định suy từ `field`. `column_scoped` = văn bản gắn với MỘT cột cụ
# thể; `table_wide` = khai báo áp cho cả bảng. Người gọi ghi đè khi biết rõ hơn.
MAC_DINH_SCOPE = {
    "column_header": {"column_scoped": True, "table_wide": False},
    "table_unit_declaration": {"column_scoped": False, "table_wide": True},
    "table_header": {"column_scoped": False, "table_wide": True},
    "section_text": {"column_scoped": False, "table_wide": False},
    "document_context": {"column_scoped": False, "table_wide": False},
    "other_table": {"column_scoped": False, "table_wide": False},
}


@dataclass(frozen=True)
class UnitEvidence:
    """Một mẩu văn bản có thể chứa khai báo đơn vị.

    `field` quyết định hạng; `same_table_as_source` / `same_column_as_source`
    quyết định scope. Người gọi cung cấp — hàm này KHÔNG đọc DB.

    v2.1 (docs/116 §6): thêm `column_scoped` và `table_wide`. Header của MỘT CỘT
    KHÁC trong cùng bảng KHÔNG còn được dùng để sửa scale của ô nguồn.
    """
    text: str
    field: str                       # khoá của EVIDENCE_RANK
    same_table_as_source: bool
    same_column_as_source: bool = False
    column_scoped: bool | None = None    # None -> suy từ `field`
    table_wide: bool | None = None       # None -> suy từ `field`
    source_table: str | None = None
    source_field_path: str | None = None
    source_ref: str | None = None

    @property
    def rank(self) -> int:
        return EVIDENCE_RANK.get(self.field, 0)

    @property
    def la_cot_rieng(self) -> bool:
        if self.column_scoped is not None:
            return self.column_scoped
        return MAC_DINH_SCOPE.get(self.field, {}).get("column_scoped", False)

    @property
    def la_toan_bang(self) -> bool:
        if self.table_wide is not None:
            return self.table_wide
        return MAC_DINH_SCOPE.get(self.field, {}).get("table_wide", False)

    @property
    def scope_hop_le(self) -> bool:
        """Bất biến docs/116 §6.3: `same_column ⇒ same_table`."""
        return not (self.same_column_as_source and not self.same_table_as_source)

    @property
    def du_tu_cach(self) -> tuple:
        """Trả (eligible, ly_do). Lọc scope TRƯỚC, rồi hạng, rồi cột."""
        if not self.scope_hop_le:
            return False, "SCOPE_METADATA_INVALID"
        if not self.same_table_as_source:
            return False, "OFF_SCOPE"
        if self.rank < RANK_TOI_THIEU:
            return False, "WEAK_RANK"
        if self.la_cot_rieng and not self.same_column_as_source:
            return False, "OTHER_COLUMN"
        if self.field == "table_unit_declaration" and not self.la_toan_bang:
            return False, "DECLARATION_NOT_TABLE_WIDE"
        return True, "ELIGIBLE"


@dataclass
class ContextValidation:
    eligible: list = field(default_factory=list)      # đủ tư cách quyết định
    off_scope: list = field(default_factory=list)     # bảng khác
    other_column: list = field(default_factory=list)  # v2.1 — header cột KHÁC
    weak: list = field(default_factory=list)          # hạng < 3
    invalid: list = field(default_factory=list)       # v2.1 — metadata mâu thuẫn
    diagnostics: list = field(default_factory=list)
    status: str = "OK"
    # OK | SCOPE_METADATA_INVALID | SCOPE_MISMATCH | OTHER_COLUMN | WEAK_EVIDENCE | NO_EVIDENCE


def validate_unit_context(evidences: list) -> ContextValidation:
    """L4 — lọc metadata hợp lệ → scope → hạng → cột (docs/116 §6.3).

    Bất biến: header của một CỘT KHÁC trong cùng bảng KHÔNG được dùng để xác
    nhận hay sửa scale của ô nguồn. Nó chỉ nằm trong `diagnostics`.
    """
    v = ContextValidation()
    thung = {"SCOPE_METADATA_INVALID": v.invalid, "OFF_SCOPE": v.off_scope,
             "WEAK_RANK": v.weak, "OTHER_COLUMN": v.other_column,
             "DECLARATION_NOT_TABLE_WIDE": v.other_column}
    for ev in evidences or []:
        du, ly_do = ev.du_tu_cach
        for tok in parse_magnitude(ev.text):
            muc = {"field": ev.field, "rank": ev.rank, "magnitude": tok.value,
                   "exponent": tok.exponent, "via": tok.via,
                   "matched_text": tok.matched_text, "span": list(tok.span),
                   "same_table_as_source": ev.same_table_as_source,
                   "same_column_as_source": ev.same_column_as_source,
                   "column_scoped": ev.la_cot_rieng, "table_wide": ev.la_toan_bang,
                   "eligibility": ly_do,
                   "source_table": ev.source_table,
                   "source_field_path": ev.source_field_path,
                   "source_ref": ev.source_ref}
            v.diagnostics.append(muc)
            (v.eligible if du else thung[ly_do]).append(muc)
    if v.invalid:
        v.status = "SCOPE_METADATA_INVALID"     # fail-closed, ưu tiên cao nhất
    elif v.eligible:
        v.status = "OK"
    elif v.off_scope:
        v.status = "SCOPE_MISMATCH"
    elif v.other_column:
        v.status = "OTHER_COLUMN"
    elif v.weak:
        v.status = "WEAK_EVIDENCE"
    else:
        v.status = "NO_EVIDENCE"
    return v


# ═══ 5 · TIỀN TỆ THEO CỘT NGUỒN (P0-6) ═════════════════════════════════════
@dataclass
class SelectedUnit:
    selected_source_currency: str | None = None
    currency_scope_alignment: str = "UNRESOLVED"
    currency_candidates: list = field(default_factory=list)


def select_source_unit(evidences: list) -> SelectedUnit:
    """Chọn currency GẦN NHẤT theo header lineage của ô nguồn.

    Ưu tiên: cùng cột > cùng bảng (hạng cao hơn trước) > không chọn.
    Currency ở cột khác chỉ là diagnostic, KHÔNG vào quyết định.
    """
    s = SelectedUnit()
    co_invalid = False
    for ev in evidences or []:
        if not ev.scope_hop_le:
            co_invalid = True
        for tok in parse_explicit_unit(ev.text):
            s.currency_candidates.append({
                "currency": tok.value, "field": ev.field, "rank": ev.rank,
                "span": list(tok.span), "matched_text": tok.matched_text,
                "same_table_as_source": ev.same_table_as_source,
                "same_column_as_source": ev.same_column_as_source,
                "column_scoped": ev.la_cot_rieng,
                "scope_hop_le": ev.scope_hop_le,
                "source_table": ev.source_table,
                "source_field_path": ev.source_field_path,
                "source_ref": ev.source_ref})
    if co_invalid:
        # docs/116 §6.2 — `same_column=True, same_table=False` là mâu thuẫn logic.
        # Không được tin `same_column` một cách độc lập.
        return SelectedUnit(None, "UNRESOLVED", s.currency_candidates)
    # Chỉ bằng chứng hạng >= RANK_TOI_THIEU mới thuộc "header lineage" của ô
    # nguồn. Currency nhặt từ section/document là ngữ cảnh rộng, chỉ diagnostic.
    du_hang = [c for c in s.currency_candidates if c["rank"] >= RANK_TOI_THIEU]
    cot = [c for c in du_hang if c["same_column_as_source"]]
    # v2.1 — header của CỘT KHÁC không còn được coi là "cùng bảng"
    bang = [c for c in du_hang
            if c["same_table_as_source"] and not c["same_column_as_source"]
            and not c["column_scoped"]]
    if cot:
        chon, s.currency_scope_alignment = cot, "SAME_COLUMN"
    elif bang:
        chon, s.currency_scope_alignment = bang, "SAME_TABLE"
    elif s.currency_candidates and not any(
            c["same_table_as_source"] for c in s.currency_candidates):
        return SelectedUnit(None, "OFF_SCOPE", s.currency_candidates)
    else:
        # không có ứng viên, hoặc có nhưng hạng < RANK_TOI_THIEU ⇒ không đoán
        return SelectedUnit(None, "UNRESOLVED", s.currency_candidates)
    loai = {c["currency"] for c in chon}
    if len(loai) != 1:
        # nhiều tiền tệ ở cùng phạm vi -> không đoán
        return SelectedUnit(None, "UNRESOLVED", s.currency_candidates)
    s.selected_source_currency = loai.pop()
    return s


# ═══ 6 · QUYẾT ĐỊNH (bảng docs/109 §2.7) ═══════════════════════════════════
@dataclass
class UnitDecision:
    rule_version: str = RULE_VERSION
    decision_code: str = "NO_EVIDENCE"
    final_status: str = "UNRESOLVED_BLOCKED"
    final_scale_exponent: int | None = None
    may_mutate: bool = False
    source_value_kind: str | None = None
    a6_scale_exponent: int | None = None
    selected_source_currency: str | None = None
    currency_scope_alignment: str = "UNRESOLVED"
    currency_candidates: list = field(default_factory=list)
    eligible_magnitudes: list = field(default_factory=list)
    diagnostics: list = field(default_factory=list)
    reason: str = ""


def apply_unit_rule(*, source_value_kind: str, a6_scale_exponent: int | None,
                    evidences: list, question_output_kind: str | None = None
                    ) -> UnitDecision:
    """Hàm thuần duy nhất được gọi từ ngoài.

    `question_output_kind` CHỈ để ghi nhật ký. Điều kiện `NOT_APPLICABLE` bám
    vào `source_value_kind` (P0-5): một câu PERCENTAGE vẫn cần hai ô money
    đúng scale, nên không được lấy kiểu output làm cớ bỏ kiểm scale nguồn.
    """
    d = UnitDecision(source_value_kind=source_value_kind,
                     a6_scale_exponent=a6_scale_exponent)
    if source_value_kind != "money":
        d.decision_code = "NOT_APPLICABLE"
        d.final_status = "NOT_APPLICABLE"
        d.reason = f"source_value_kind={source_value_kind!r} khong phai money"
        return d

    # v2.1 · docs/116 §6.2 — chặn metadata scope mâu thuẫn TRƯỚC mọi thứ khác
    xau = [e for e in (evidences or []) if not e.scope_hop_le]
    if xau:
        d.decision_code = "SCOPE_METADATA_INVALID"
        d.final_status = "UNRESOLVED_BLOCKED"
        d.diagnostics = [{"field": e.field, "same_table_as_source": e.same_table_as_source,
                          "same_column_as_source": e.same_column_as_source,
                          "source_ref": e.source_ref,
                          "vi_pham": "same_column_as_source=True nhung same_table_as_source=False"}
                         for e in xau]
        d.reason = ("metadata scope mau thuan: same_column => same_table bi vi pham "
                    f"o {len(xau)} evidence; fail-closed, khong doc tiep")
        return d

    cur = select_source_unit(evidences)
    d.selected_source_currency = cur.selected_source_currency
    d.currency_scope_alignment = cur.currency_scope_alignment
    d.currency_candidates = cur.currency_candidates

    if cur.selected_source_currency is None:
        d.decision_code = "CURRENCY_UNRESOLVED"
        d.final_status = "UNRESOLVED_BLOCKED"
        d.reason = (f"khong xac dinh duoc currency cua cot nguon "
                    f"(alignment={cur.currency_scope_alignment}); fail-closed")
        return d
    if cur.selected_source_currency != SUPPORTED_CURRENCY:
        d.decision_code = "NON_VND_UNSUPPORTED"
        d.final_status = "FALLBACK_REQUIRED"
        d.reason = f"currency cot nguon = {cur.selected_source_currency}, chua ho tro"
        return d

    ctx = validate_unit_context(evidences)
    d.diagnostics = ctx.diagnostics
    d.eligible_magnitudes = ctx.eligible

    if ctx.status == "SCOPE_METADATA_INVALID":
        d.decision_code = "SCOPE_METADATA_INVALID"
        d.final_status = "UNRESOLVED_BLOCKED"
        d.reason = "metadata scope mau thuan trong evidence magnitude"
        return d
    if ctx.status == "SCOPE_MISMATCH":
        d.decision_code = "SCOPE_MISMATCH"
        d.final_status = "UNRESOLVED_BLOCKED"
        d.reason = "magnitude chi den tu BANG KHAC; khong duoc dung de sua scale"
        return d
    if ctx.status == "OTHER_COLUMN":
        # docs/116 §6 — P0 của v2: header cột KHÁC từng được cho vào eligible và
        # có thể trả A6_DEFECT + may_mutate=True. v2.1 chặn hẳn.
        cd = ("TABLE_DECLARATION_NOT_TABLE_WIDE"
              if all(m["eligibility"] == "DECLARATION_NOT_TABLE_WIDE"
                     for m in ctx.other_column)
              else "OTHER_COLUMN_MAGNITUDE_IGNORED")
        d.decision_code = cd
        d.final_status = "UNRESOLVED_BLOCKED"
        d.reason = ("magnitude chi den tu header CUA COT KHAC (hoac khai bao khong "
                    "toan bang); khong duoc dung cho o nguon")
        return d
    if ctx.status == "WEAK_EVIDENCE":
        d.decision_code = "WEAK_EVIDENCE_REVIEW"
        d.final_status = "UNRESOLVED_BLOCKED"
        d.reason = f"chi co bang chung hang < {RANK_TOI_THIEU} (section/document)"
        return d
    if ctx.status == "NO_EVIDENCE":
        d.decision_code = "CURRENCY_ONLY_NO_MAGNITUDE"
        d.final_status = ("CONSISTENT_BUT_UNVERIFIED" if a6_scale_exponent == 0
                          else "UNRESOLVED_BLOCKED")
        d.reason = ("chi thay currency, khong thay magnitude hop le; "
                    f"a6_scale_exponent={a6_scale_exponent}")
        return d

    mu = {m["exponent"] for m in ctx.eligible}
    if len(mu) > 1:
        d.decision_code = "CONFLICTING_MAGNITUDES"
        d.final_status = "UNRESOLVED_BLOCKED"
        d.reason = f"nhieu magnitude cung hang hop le: {sorted(mu)}"
        return d

    m = mu.pop()
    d.decision_code = "EXPLICIT_MAGNITUDE_CONFIRMED"
    d.final_scale_exponent = m
    if a6_scale_exponent == m:
        d.final_status = "CONFIRMED_A6"
        d.may_mutate = True
        d.reason = f"bang chung hang >= {RANK_TOI_THIEU} xac nhan scale 10^{m} cua A6"
    else:
        d.final_status = "A6_DEFECT"
        d.may_mutate = True
        d.reason = (f"bang chung hang >= {RANK_TOI_THIEU} cho scale 10^{m}, "
                    f"A6 dang ghi 10^{a6_scale_exponent}")
    return d
