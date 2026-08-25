#!/usr/bin/env python3
"""Semantic predicates — Pha 4/5/8 directive 165.

Mỗi predicate là một hàm THUẦN, trả `Verdict(status, reason, evidence)` với

    PASS · FAIL · UNCERTAIN · NOT_MEASURABLE · NOT_APPLICABLE

Bốn luật cứng, mỗi luật sửa đúng một lỗi mà review 165 chỉ ra:

* **F7** — `operation_match` so **operation đã chuẩn hoá** của gold và pred. Nếu
  gold ghi `multi` (không phải một phép cụ thể) thì trả `NOT_MEASURABLE`, KHÔNG
  trả True/False giả.
* **F8** — `unit_contract` tính từ **đơn vị ô nguồn + đơn vị câu hỏi + hệ số quy
  đổi trong query**. Tuyệt đối không lấy `pred/gold` làm nguồn sự thật; một đáp
  án sai chỉ tiêu thường cũng không phải luỹ thừa 10 của gold, nên phép cũ báo
  `PASS` cho cả những ca chưa từng kiểm đơn vị.
* **F10** — `operand_binding` so **theo vai trò, có thứ tự và bội số**, dựng từ
  AST theo TỪNG BIẾN dataframe. Không tạo tích chéo row × col toàn cục.
* **F16** — `parse_so` giữ dấu âm, ngoặc kế toán, phần thập phân và token thiếu;
  luôn trả kèm `parse_status`, không im lặng nuốt lỗi.
"""
from __future__ import annotations

import ast
import re
import unicodedata
from dataclasses import dataclass, field

PASS, FAIL, UNCERTAIN = "PASS", "FAIL", "UNCERTAIN"
NOT_MEASURABLE, NOT_APPLICABLE = "NOT_MEASURABLE", "NOT_APPLICABLE"


@dataclass
class Verdict:
    status: str
    reason: str = ""
    evidence: dict = field(default_factory=dict)

    def __bool__(self):                      # tránh dùng nhầm trong if
        raise TypeError("Verdict không có giá trị chân lý — hãy so .status")


# ── chuẩn hoá ────────────────────────────────────────────────────────────────
def bo_dau(s: str) -> str:
    s = (s or "").replace("Đ", "D").replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").lower().strip()


OP_CANON = {
    "lookup": "LOOKUP", "direct_lookup": "LOOKUP",
    "difference": "DIFFERENCE", "sum": "SUM", "average": "AVERAGE",
    "ratio": "RATIO", "ratio_multiple": "RATIO",
    "percentage": "RATIO_PERCENT", "percentage_change": "PERCENTAGE_CHANGE",
    "count": "COUNT", "max_min": "MAX_MIN", "argmin_max_filter": "MAX_MIN",
    "argmax_year": "ARGMAX_YEAR", "multi_entity_aggregate": "MULTI_ENTITY_AGG",
}
OP_KHONG_XAC_DINH = {"multi", "compound", "unknown", None, ""}


def canon_op(op) -> str | None:
    """`multi`/`compound`/`unknown` KHÔNG phải operation — trả None."""
    k = bo_dau(str(op)).replace(" ", "_")
    if k in {bo_dau(x) for x in OP_KHONG_XAC_DINH if x} or not k:
        return None
    return OP_CANON.get(k)


SCALE_TU = [("nghin ty", 12), ("ty dong", 9), ("trieu usd", 6), ("trieu dong", 6),
            ("nghin dong", 3), ("trieu", 6), ("ty", 9), ("nghin", 3),
            ("dong", 0), ("vnd", 0), ("usd", 0)]


def scale_tu_text(s: str):
    """Số mũ 10 của đơn vị đọc từ text (col_path hoặc câu hỏi). None = không rõ."""
    t = bo_dau(s)
    if "%" in (s or "") or "phan tram" in t:
        return "PERCENT"
    for k, e in SCALE_TU:
        if k in t:
            return e
    return None


def parse_so(raw: str):
    """Parse số kiểu Việt, GIỮ dấu âm/ngoặc/thập phân. Trả (giá trị, trạng thái)."""
    s = str(raw or "").strip()
    if not s or s in {"-", "–", "—", "n/a", "N/A", "..", "…"}:
        return None, "MISSING_TOKEN"
    am = s.startswith("(") and s.endswith(")")
    if am:
        s = s[1:-1].strip()
    if s.startswith("-"):
        am, s = True, s[1:].strip()
    # quy ước Việt: '.' = phân tách nghìn, ',' = thập phân
    if re.fullmatch(r"\d{1,3}(\.\d{3})*(,\d+)?", s):
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+(\.\d+)?", s):
        pass
    else:
        s2 = re.sub(r"[^\d,.\-]", "", s)
        if not s2:
            return None, "UNPARSEABLE"
        s = s2.replace(".", "").replace(",", ".")
    try:
        v = float(s)
    except ValueError:
        return None, "UNPARSEABLE"
    return (-v if am else v), "OK"


# ── AST theo TỪNG BIẾN, có vai trò (F10) ────────────────────────────────────
@dataclass
class Selection:
    variable: str | None
    row_path: str | None
    col_path: str | None
    order: int


def tach_selection(query: str) -> tuple[list[Selection], str]:
    """Bóc từng phép chọn ô `df[(df['row_path']==..)&(df['col_label']==..)]`.

    Đi theo AST nên bắt được cả nháy kép, và giữ ĐÚNG cặp (variable, row, col)
    của từng selection thay vì gom thành hai tập rồi nhân chéo.
    """
    if not (query or "").strip():
        return [], "EMPTY_QUERY"
    try:
        tree = ast.parse(query, mode="eval")
    except SyntaxError:
        return [], "PARSE_FAILED"

    sels: list[Selection] = []

    class V(ast.NodeVisitor):
        def visit_Subscript(self, node):
            base = node.value
            var = base.id if isinstance(base, ast.Name) else None
            eqs: list[tuple[str, str]] = []

            def quet(n):
                if isinstance(n, ast.Compare) and len(n.ops) == 1 and \
                        isinstance(n.ops[0], ast.Eq):
                    l, r = n.left, n.comparators[0]
                    if isinstance(l, ast.Subscript) and isinstance(
                            getattr(l, "slice", None), ast.Constant) and \
                            isinstance(r, ast.Constant):
                        eqs.append((str(l.slice.value), str(r.value)))
                for c in ast.iter_child_nodes(n):
                    quet(c)
            quet(node.slice)
            if eqs:
                d = dict(eqs)
                sels.append(Selection(
                    variable=var,
                    row_path=d.get("row_path") or d.get("row_label"),
                    col_path=d.get("col_label") or d.get("col_path"),
                    order=len(sels)))
            self.generic_visit(node)
    V().visit(tree)
    return sels, "OK"


# ── predicates ───────────────────────────────────────────────────────────────
def entity_match(gold_entities, selected_docs) -> Verdict:
    g = {bo_dau(x) for x in (gold_entities or []) if x}
    s = {bo_dau(str(d).split("_")[0]) for d in (selected_docs or []) if d}
    if not g or not s:
        return Verdict(NOT_MEASURABLE, "thiếu entity gold hoặc doc đã chọn")
    return (Verdict(PASS, "ticker chọn ∈ entity gold", {"gold": sorted(g), "sel": sorted(s)})
            if s <= g else
            Verdict(FAIL, "ticker chọn NGOÀI entity gold", {"gold": sorted(g), "sel": sorted(s)}))


def period_match(gold_periods, selected_periods) -> Verdict:
    g = {str(x)[:10] for x in (gold_periods or []) if x}
    s = {str(x)[:10] for x in (selected_periods or []) if x}
    if not g or not s:
        return Verdict(NOT_MEASURABLE, "thiếu period gold hoặc period đã chọn")
    return (Verdict(PASS, "kỳ khớp", {"gold": sorted(g), "sel": sorted(s)})
            if s <= g else
            Verdict(FAIL, "kỳ lệch", {"gold": sorted(g), "sel": sorted(s)}))


def basis_match(gold_basis, selected_docs) -> Verdict:
    if gold_basis not in ("consolidated", "separate"):
        return Verdict(NOT_MEASURABLE, f"basis gold không xác định: {gold_basis!r}")
    if not selected_docs:
        return Verdict(NOT_MEASURABLE, "không có doc đã chọn")
    ok = all(gold_basis in str(d) for d in selected_docs)
    return Verdict(PASS if ok else FAIL, f"basis gold = {gold_basis}",
                   {"docs": list(selected_docs)})


def operation_match(gold_op, pred_op) -> Verdict:
    """F7: so operation THẬT. `multi` ⇒ NOT_MEASURABLE, không đoán."""
    g, p = canon_op(gold_op), canon_op(pred_op)
    if g is None:
        return Verdict(NOT_MEASURABLE,
                       f"operation gold chưa cụ thể ({gold_op!r}) — cần OperationIR",
                       {"gold_raw": gold_op, "pred_raw": pred_op})
    if p is None:
        return Verdict(NOT_MEASURABLE, f"operation pred chưa cụ thể ({pred_op!r})",
                       {"gold_raw": gold_op, "pred_raw": pred_op})
    return Verdict(PASS if g == p else FAIL, f"gold={g} pred={p}",
                   {"gold": g, "pred": p})


def operand_binding(gold_operands, selections) -> Verdict:
    """F10: so theo VAI TRÒ, có thứ tự và bội số. Không dùng set toàn cục."""
    if not gold_operands:
        return Verdict(NOT_MEASURABLE, "gold không có ordered_operands")
    if not selections:
        return Verdict(FAIL, "query không chọn ô nào", {"n_gold": len(gold_operands)})
    if len(selections) != len(gold_operands):
        return Verdict(FAIL, "số toán hạng lệch",
                       {"n_gold": len(gold_operands), "n_pred": len(selections)})
    lech = []
    for i, (g, s) in enumerate(zip(gold_operands, selections)):
        gr, gc = bo_dau(g.get("row_path")), bo_dau(g.get("col_path"))
        if bo_dau(s.row_path) != gr or bo_dau(s.col_path) != gc:
            lech.append({"order": i, "role": g.get("role"),
                         "gold": [g.get("row_path"), g.get("col_path")],
                         "pred": [s.row_path, s.col_path]})
    return (Verdict(PASS, "khớp theo vai trò và thứ tự", {"n": len(gold_operands)})
            if not lech else
            Verdict(FAIL, f"{len(lech)}/{len(gold_operands)} toán hạng lệch",
                    {"lech": lech}))


def unit_contract(source_unit_text, question_unit_text, query) -> Verdict:
    """F8: đơn vị tính TỪ NGUỒN, không từ pred/gold.

    Hệ số kỳ vọng = 10^(scale_nguon − scale_hoi). So với hệ số nhân/chia thật
    trong `pandas_query`.
    """
    se = scale_tu_text(source_unit_text)
    qe = scale_tu_text(question_unit_text)
    if se is None or qe is None:
        return Verdict(NOT_MEASURABLE,
                       "không đọc được đơn vị nguồn hoặc đơn vị câu hỏi",
                       {"source_unit_text": source_unit_text,
                        "question_unit_text": question_unit_text})
    if se == "PERCENT" or qe == "PERCENT":
        return Verdict(NOT_MEASURABLE, "đơn vị phần trăm — cần contract riêng",
                       {"source": se, "question": qe})
    ky_vong = 10 ** (se - qe)
    chia = [float(m) for m in re.findall(r"/\s*([0-9_]+(?:\.[0-9]+)?)",
                                         str(query or "").replace("_", ""))]
    nhan = [float(m) for m in re.findall(r"\*\s*([0-9_]+(?:\.[0-9]+)?)",
                                         str(query or "").replace("_", ""))]
    he_so = 1.0
    for c in chia:
        if c:
            he_so /= c
    for n in nhan:
        he_so *= n
    ok = abs(he_so - ky_vong) <= max(abs(ky_vong) * 1e-9, 1e-12)
    return Verdict(PASS if ok else FAIL,
                   f"hệ số kỳ vọng {ky_vong:g}, query dùng {he_so:g}",
                   {"scale_source": se, "scale_question": qe,
                    "expected_factor": ky_vong, "query_factor": he_so})


def evidence_files_present(evidence, zip_names) -> Verdict:
    """E0 — chỉ kiểm file tồn tại. ĐỔI TÊN, không còn được gọi là E1."""
    if not evidence:
        return Verdict(FAIL, "evidence rỗng")
    thieu = [e.get("csv_path") for e in evidence
             if e.get("csv_path") not in set(zip_names or [])]
    return (Verdict(PASS, f"{len(evidence)} file có mặt")
            if not thieu else Verdict(FAIL, "thiếu CSV", {"thieu": thieu}))


def query_variable_resolves(selections, evidence) -> Verdict:
    """E1 — mọi biến trong query phải trỏ tới một evidence entry."""
    if not selections:
        return Verdict(NOT_MEASURABLE, "query không có selection")
    bien_ev = {e.get("variable") for e in (evidence or [])}
    thieu = sorted({s.variable for s in selections if s.variable not in bien_ev})
    return (Verdict(PASS, "mọi biến đều resolve")
            if not thieu else
            Verdict(FAIL, "biến không có evidence", {"bien_thieu": thieu}))


def gold_operands_covered(gold_operands, selections) -> Verdict:
    """E3 — evidence/query có phủ hết toán hạng gold không."""
    if not gold_operands:
        return Verdict(NOT_MEASURABLE, "gold không có operand")
    g = {(bo_dau(o.get("row_path")), bo_dau(o.get("col_path"))) for o in gold_operands}
    p = {(bo_dau(s.row_path), bo_dau(s.col_path)) for s in selections}
    thieu = sorted(g - p)
    return (Verdict(PASS, "phủ đủ")
            if not thieu else
            Verdict(FAIL, f"thiếu {len(thieu)}/{len(g)} toán hạng gold",
                    {"thieu": [list(x) for x in thieu[:5]]}))
