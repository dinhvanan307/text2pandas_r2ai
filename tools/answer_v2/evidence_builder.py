#!/usr/bin/env python3
"""Evidence builder — CSV `a6_*` + biến `df1..dfN`, khớp ĐÚNG production.

HỢP ĐỒNG PHẢI KHỚP TUYỆT ĐỐI VỚI `tools/answer_a6/01_resolver.py`
    tên tệp   `a6_{doc_id}_line{line}.csv`
    cột       row_path, row_label, col_label, value_raw, value
    `value`   đã quy về VND thật (raw × 10^scale) NGAY TRONG CSV
Tiền tố `a6_` là bắt buộc và có lý do đã trả giá: CSV của đường A6 và đường HTML
cùng lược đồ nhưng **khác nội dung nhãn**; trùng tên thì câu lệnh nhiều-df trỏ
nhầm và vỡ ngầm (resolver ghi rõ: đã dính 15 câu ở lần đóng gói đầu).

KHOÁ `(row_path, col_label)` PHẢI TRỎ ĐÚNG MỘT Ô. `.values[0]` chỉ lấy dòng
khớp ĐẦU TIÊN, nên nếu hai ô khác giá trị rơi vào cùng khoá thì bất biến
`answer == eval(query)` vỡ **ngầm**. Cách xử lý giống resolver: nới khoá cột
bằng hậu tố ` #k`.

MỘT BẢNG → MỘT DataFrame. Hai lá cùng bảng dùng chung `df`. Đây là điểm doc 143
§5.3 nói quá mạnh ("cần ≥2 DataFrame") và doc 144 §10.1 sửa đúng.
"""
from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from pathlib import Path


def vnd(value_text: str | None, scale: int | None) -> Decimal | None:
    """Giá trị VND thật = raw × 10^scale. Trả None nếu không parse được."""
    if value_text in (None, ""):
        return None
    try:
        v = Decimal(str(value_text))
    except (InvalidOperation, ValueError):
        return None
    return v * (Decimal(10) ** int(scale or 0))


_SO = re.compile(r"^\s*-?[\d.,]+\s*$")


def _khong_thanh_so(s: str, period_end: str | None) -> str:
    """Nhãn thuần số bị pandas đọc thành số ⇒ so sánh chuỗi trượt.

    Giữ nguyên hành vi của resolver: nhãn chỉ gồm chữ số/dấu phân cách được gắn
    thêm ngữ cảnh kỳ để thành chuỗi thật.
    """
    s = (s or "").strip()
    if s and _SO.match(s):
        return f"{s} (kỳ {period_end or '?'})"
    return s


@dataclass
class BangDai:
    csv_name: str
    rows: list[tuple]
    khoa: dict[str, tuple[str, str]]      # observation_uid → (row_path, col_label)


def bang_dai(con, table_uid: str, evidence_ref: str) -> BangDai:
    """Dựng bảng dài cho MỘT bảng nguồn, thẳng từ A6."""
    doc, _, line = (evidence_ref or "").partition("|line:")
    csv_name = f"a6_{doc}_line{line}.csv"

    rows: list[tuple] = []
    khoa: dict[str, tuple[str, str]] = {}
    dat: dict[tuple[str, str], str] = {}
    q = ("SELECT observation_uid, row_path_text, metric_label_clean, col_path_text,"
         " period_end, value_source_raw, value_decimal_text, scale_exponent"
         " FROM observations WHERE table_uid=? ORDER BY grid_row_idx, grid_col_idx")
    for ouid, rp, ml, cp, pe, vr, vd, sc in con.execute(q, (table_uid,)):
        rpath = rp or ml or ""
        if not rpath:
            continue
        v = vnd(vd, sc)
        if v is None:
            continue
        vs = format(v, "f")
        clab0 = _khong_thanh_so((cp or "").strip() or f"period:{pe or '?'}", pe)
        rpath = _khong_thanh_so(rpath, pe)
        clab, k = clab0, 0
        while dat.get((rpath, clab), vs) != vs:      # trùng khoá, KHÁC giá trị
            k += 1
            clab = f"{clab0} #{k}"
        dat[(rpath, clab)] = vs
        khoa[str(ouid)] = (rpath, clab)
        rows.append((rpath, ml or rpath, clab, vr or "", vs))
    return BangDai(csv_name, rows, khoa)


def ghi_csv(data_dir: Path, b: BangDai, da_ghi: set[str]) -> str:
    """Ghi CSV nếu chưa có. → csv_path tương đối `data/...`."""
    if b.csv_name not in da_ghi:
        data_dir.mkdir(parents=True, exist_ok=True)
        with (data_dir / b.csv_name).open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["row_path", "row_label", "col_label", "value_raw", "value"])
            w.writerows(b.rows)
        da_ghi.add(b.csv_name)
    return f"data/{b.csv_name}"


def build(con, ops: dict, data_dir: Path, da_ghi: set[str]) -> tuple[dict, list[dict], list[str]]:
    """→ (bind[metric_id] = {variable,row_path,col_label,csv_path}, evidence[], errs)

    Biến cấp TẤT ĐỊNH theo `evidence_ref` đã sort — replay hai lần cho cùng tên.
    """
    theo_bang: dict[str, list] = {}
    for mid, op in ops.items():
        theo_bang.setdefault(op.evidence_ref, []).append((mid, op))

    bind: dict[str, dict] = {}
    evidence: list[dict] = []
    errs: list[str] = []
    for i, ref in enumerate(sorted(theo_bang), start=1):
        var = f"df{i}"
        mid_ops = theo_bang[ref]
        b = bang_dai(con, mid_ops[0][1].table_uid, ref)
        if not b.rows:
            errs.append(f"EMPTY_TABLE:{ref}")
            continue
        csv_path = ghi_csv(data_dir, b, da_ghi)
        evidence.append({"variable": var, "csv_path": csv_path})
        for mid, op in mid_ops:
            k = b.khoa.get(op.observation_uid)
            if k is None:
                # Ô đã chọn không xuất được ra CSV ⇒ KHÔNG đoán, báo lỗi để
                # cả câu rơi về fallback. Giữ đúng kỷ luật của resolver.
                errs.append(f"OBS_NOT_IN_CSV:{mid}")
                continue
            bind[mid] = {"variable": var, "row_path": k[0], "col_label": k[1],
                         "csv_path": csv_path,
                         "value_vnd": float(vnd(op.value_decimal_text, op.scale_exponent) or 0)}
    if len(bind) != len(ops):
        errs.append("EVIDENCE_INCOMPLETE")
    return bind, evidence, errs
