#!/usr/bin/env python3
"""Multi-operand binder — `OperandKey(metric_id, entity, period, role, scope)`.

ĐÂY LÀ CHỖ SỬA NÚT THẮT GỐC (doc 143 §1.1)
`operand_pipeline_v1.SlotKey` là `(ticker, year, role)` — **không có chiều
metric** — nên hai chỉ tiêu khác nhau cùng công ty/năm là **một** khoá, và
`enforce_metric_consistency` ép chúng về cùng nhãn. D/E vì thế bất khả thi
*theo thiết kế*. `OperandKey` ở đây thêm `metric_id`, và guard cũ **không** được
gọi trên đường R2.

NGUỒN DỮ LIỆU: `observations` của A6 — **cùng nguồn** mà
`tools/answer_a6/01_resolver.py` (đường production thật) đang dùng. Không phải
`to_long_format(parse_table_html())` như `answer.py` (đó là FALLBACK_HTML).
Chọn cùng nguồn với production là điều kiện để evidence CSV và `pandas_query`
khớp nhau — nếu bind từ A6 mà xuất CSV từ HTML thì `.values[0]` sẽ IndexError.

TÁI SỬ DỤNG: `fact_rank_v1.fetch_pool` cho candidate generation. Không viết lại.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from execution.fact_rank_v1 import fetch_pool  # noqa: E402
from metric_ontology import MetricSpec, nhan_dien  # noqa: E402


@dataclass(frozen=True)
class OperandKey:
    metric_id: str
    entity: str
    period_year: int
    role: str = "x"
    scope: str = "consolidated_preferred"

    @property
    def name(self) -> str:
        return f"{self.metric_id}@{self.entity}/{self.period_year}"


@dataclass
class BoundOperand:
    key: OperandKey
    observation_uid: str
    evidence_ref: str
    table_uid: str
    row_path: str
    col_path: str
    metric_label: str
    statement_type: str
    value_decimal_text: str
    scale_exponent: int
    period_end: str | None
    basis: str | None
    diem: float
    n_ung_vien: int


def _basis_cua(evidence_ref: str) -> str:
    r = (evidence_ref or "").lower()
    if "_consolidated" in r:
        return "consolidated"
    if "_separate" in r:
        return "separate"
    return "unknown"


def _diem(c: dict, spec: MetricSpec, want_year: int, scope: str) -> float:
    """Điểm chọn ứng viên cho MỘT lá. Nhỏ, có chủ đích, giải thích được.

    Không dùng `score_v2.rank_pool` ở đây: hàm ấy chấm theo mức độ khớp CÂU HỎI
    (idf overlap với cả câu), trong khi ở R2 lá đã được `metric_id` xác định
    cứng — thứ còn phải chọn là **kỳ · phạm vi · loại báo cáo**, không phải nhãn.
    Dùng nhầm scorer ở đây làm điểm nhãn lấn át điểm kỳ, đúng cơ chế đã đo được
    ở D1(a) (doc 141 §3.2: `col_year` quyết định 12/33 khoảng cách).
    """
    s = 0.0
    pe = str(c.get("period_end") or "")
    if pe[:4] == str(want_year):
        s += 3.0
    elif str(want_year) in (c.get("col_path") or ""):
        s += 1.0
    else:
        s -= 2.0                                  # sai kỳ: phạt, không chỉ bỏ thưởng

    if spec.statement_types and c.get("statement_type") in spec.statement_types:
        s += 1.5
    if c.get("statement_type") == "balance_sheet" and spec.period_semantics == "point_in_time":
        s += 0.5

    b = _basis_cua(c.get("evidence_ref") or "")
    if scope.startswith("consolidated") and b == "consolidated":
        s += 1.0
    elif scope.startswith("separate") and b == "separate":
        s += 1.0

    if not c.get("is_restated"):
        s += 0.4
    if c.get("confidence") not in ("low", None):
        s += 0.3
    if c.get("ready"):
        s += 0.3
    # row_path NÔNG hơn = dòng tổng. Với chỉ tiêu tổng hợp (mọi lá wave 1 đều
    # là dòng tổng của một mục), nông hơn gần như luôn đúng hơn.
    s -= 0.25 * (c.get("row_path") or "").count("›")
    return round(s, 4)


def bind_leaf(con, plan_q: dict, key: OperandKey,
              specs: dict[str, MetricSpec], *,
              ontology_fix: bool = False) -> tuple[BoundOperand | None, str]:
    """Bind MỘT lá. → (operand, mã lỗi). Mã rỗng = thành công."""
    spec = specs.get(key.metric_id)
    if spec is None:
        return None, "UNKNOWN_METRIC"

    sub = dict(plan_q)
    sub["entities"], sub["years"] = [key.entity], [key.period_year]
    pool = fetch_pool(con, sub, legacy_order=False)
    if not pool:
        return None, "EMPTY_POOL"

    ung_vien = [c for c in pool
                if nhan_dien(specs, c.get("metric_label") or "",
                             ontology_fix=ontology_fix) == key.metric_id]
    if not ung_vien:
        return None, "METRIC_NOT_IN_POOL"

    ung_vien.sort(key=lambda c: (-_diem(c, spec, key.period_year, key.scope),
                                 str(c["observation_uid"])))
    top = ung_vien[0]
    return BoundOperand(
        key=key,
        observation_uid=str(top["observation_uid"]),
        evidence_ref=str(top["evidence_ref"]),
        table_uid=str(top["table_uid"]),
        row_path=str(top.get("row_path") or ""),
        col_path=str(top.get("col_path") or ""),
        metric_label=str(top.get("metric_label") or ""),
        statement_type=str(top.get("statement_type") or ""),
        value_decimal_text=str(top["value"]),
        scale_exponent=int(top.get("scale_exponent") or 0),
        period_end=top.get("period_end"),
        basis=_basis_cua(str(top["evidence_ref"])),
        diem=_diem(top, spec, key.period_year, key.scope),
        n_ung_vien=len(ung_vien),
    ), ""


def kiem_rang_buoc(ops: dict[str, BoundOperand], same_entity: bool,
                   same_period: bool) -> list[str]:
    """Ràng buộc THEO FORMULA — thay `enforce_metric_consistency`.

    Guard cũ đòi mọi operand **cùng metric**; đó chính là giả định làm D/E bất
    khả thi. Ở đây đòi cùng **entity/kỳ/phạm vi** — điều mà công thức tài chính
    thật sự yêu cầu — và **cho phép** metric khác nhau.
    """
    errs: list[str] = []
    if not ops:
        return ["NO_OPERANDS"]
    if same_entity and len({o.key.entity for o in ops.values()}) != 1:
        errs.append("ENTITY_MISMATCH")
    if same_period and len({o.key.period_year for o in ops.values()}) != 1:
        errs.append("PERIOD_MISMATCH")
    if len({o.basis for o in ops.values()}) != 1:
        # Trộn hợp nhất với riêng lẻ tạo tỷ số vô nghĩa: tử của tập đoàn chia
        # mẫu của công ty mẹ. Không đoán — báo lỗi.
        errs.append("SCOPE_MISMATCH")
    nam = {str(o.period_end or "")[:4] for o in ops.values() if o.period_end}
    if same_period and len(nam) > 1:
        errs.append("PERIOD_END_MISMATCH")
    return errs


def bind_plan(con, plan_q: dict, leaves: list[str], entity: str, year: int,
              specs: dict[str, MetricSpec], *, same_entity=True,
              same_period=True,
              ontology_fix: bool = False,
              ) -> tuple[dict[str, BoundOperand], list[str], dict]:
    """Bind mọi lá của một formula. → (ops, errs, chẩn đoán)."""
    ops: dict[str, BoundOperand] = {}
    errs: list[str] = []
    chan_doan = {"leaf_status": {}, "n_ung_vien": {}}
    for mid in leaves:
        key = OperandKey(metric_id=mid, entity=entity, period_year=year)
        op, err = bind_leaf(con, plan_q, key, specs, ontology_fix=ontology_fix)
        chan_doan["leaf_status"][mid] = err or "OK"
        if op is None:
            errs.append(f"{err}:{mid}")
            continue
        chan_doan["n_ung_vien"][mid] = op.n_ung_vien
        ops[mid] = op
    if not errs:
        errs += kiem_rang_buoc(ops, same_entity, same_period)
    return ops, errs, chan_doan
