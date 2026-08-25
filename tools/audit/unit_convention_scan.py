#!/usr/bin/env python3
"""Quét hợp đồng đơn vị trên TOÀN BỘ 1012 câu của exact P0I.

Câu hỏi cần trả lời — và không tài liệu nào từ 162 đến 167 đã trả lời:

    Phép `/1000000` trong `pandas_query` đúng trong bao nhiêu câu, sai trong
    bao nhiêu câu, và **U1-7 có phải chỉ là 7 hay là phần nổi của một lớp lớn hơn**?

Phép đo, ba đại lượng ĐỘC LẬP cho từng câu:

1. `cell_ratio`  = value / parse(value_raw) của **đúng ô mà query chọn**
                   → cột `value` đang ở đơn vị cột (×1) hay đã quy về đồng (×1e6)
2. `query_factor`= tích các hệ số nhân/chia trong `pandas_query`
3. `unit_gap`    = 10^(scale_cột − scale_câu_hỏi) — hệ số ĐÚNG phải dùng

Kết luận cho từng câu: `query_factor` có bằng `unit_gap / cell_ratio` không.
Không suy từ đáp án, không dùng gold.
"""
from __future__ import annotations

import argparse
import collections
import csv
import io
import json
import re
import unicodedata
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DV_HOI = [("nghìn tỷ", 12), ("tỷ đồng", 9), ("tỉ đồng", 9), ("triệu usd", 6),
          ("triệu đồng", 6), ("nghìn đồng", 3), ("đồng", 0)]
DV_COT = [("nghìn tỷ", 12), ("tỷ đồng", 9), ("triệu đồng", 6), ("nghìn đồng", 3),
          ("triệu", 6), ("tỷ", 9), ("nghìn", 3), ("đồng", 0), ("vnd", 0)]


def bo_dau(s):
    s = (s or "").replace("Đ", "D").replace("đ", "d")
    return "".join(c for c in unicodedata.normalize("NFD", s)
                   if unicodedata.category(c) != "Mn").lower()


def scale(text, bang):
    t = bo_dau(text)
    if "%" in (text or "") or "phan tram" in t:
        return "PERCENT"
    for k, e in bang:
        if bo_dau(k) in t:
            return e
    return None


def parse_raw(s):
    t = str(s or "").strip()
    if not t or t in {"-", "–", "—"}:
        return None
    am = t.startswith("(") and t.endswith(")")
    if am:
        t = t[1:-1].strip()
    if t.startswith("-"):
        am, t = True, t[1:].strip()
    if re.fullmatch(r"\d{1,3}(\.\d{3})*(,\d+)?", t):
        t = t.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d+(,\d+)?", t):
        t = t.replace(",", ".")
    elif not re.fullmatch(r"\d+(\.\d+)?", t):
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return -v if am else v


def he_so_query(q):
    """Hệ số nhân/chia THẬT của query, lấy bằng AST.

    Bản regex đầu tiên đếm cả dấu `/` nằm trong **chuỗi** — `col_label ==
    '31/12/2018'` bị hiểu thành chia cho 12 rồi chia cho 2018, làm 84 câu bị
    gán sai hệ số `~4,1e-11`. Đây là lỗi đo thứ ba cùng họ trong tài liệu này;
    ghi lại để không ai dùng lại regex cho việc này.
    """
    import ast as _ast
    s = str(q or "").strip()
    if not s:
        return None
    try:
        tree = _ast.parse(s, mode="eval")
    except SyntaxError:
        return None
    f = 1.0

    def di(n):
        nonlocal f
        if isinstance(n, _ast.BinOp) and isinstance(n.op, (_ast.Div, _ast.Mult)):
            r = n.right
            if isinstance(r, _ast.Constant) and isinstance(r.value, (int, float)):
                v = float(r.value)
                if v:
                    f = f / v if isinstance(n.op, _ast.Div) else f * v
        for c in _ast.iter_child_nodes(n):
            di(c)
    di(tree)
    return f


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path,
                    default=ROOT / "data/submissions/submission_P0I.zip")
    ap.add_argument("--out", type=Path, default=ROOT / "reports/167")
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)

    z = zipfile.ZipFile(a.zip)
    sub = json.loads(z.read("submission.json"))
    cache = {}

    rows, dem = [], collections.Counter()
    for r in sub:
        q = r["id"]
        qry = str(r.get("pandas_query") or "")
        evs = r.get("evidence") or []
        rp = re.findall(r"row_path'\]\s*==\s*'([^']*)'", qry)
        cp = re.findall(r"col_label'\]\s*==\s*'([^']*)'", qry)
        rec = {"qid": q, "n_evidence": len(evs), "n_selection": len(rp),
               "query_factor": he_so_query(qry) if qry.strip() else None,
               "question_scale": scale(r.get("question"), DV_HOI)}

        if len(evs) == 1 and len(rp) == 1 and len(cp) == 1:
            p = evs[0].get("csv_path")
            if p not in cache:
                try:
                    cache[p] = list(csv.DictReader(io.StringIO(
                        z.read(p).decode("utf-8", "replace"))))
                except Exception:
                    cache[p] = None
            tb = cache[p]
            hit = ([x for x in tb if x.get("row_path") == rp[0]
                    and x.get("col_label") == cp[0]] if tb else [])
            if hit:
                raw = parse_raw(hit[0].get("value_raw"))
                try:
                    val = float(hit[0].get("value"))
                except (TypeError, ValueError):
                    val = None
                rec["value_raw"] = hit[0].get("value_raw")
                rec["value"] = hit[0].get("value")
                rec["cell_ratio"] = (round(val / raw, 10)
                                     if (raw not in (None, 0) and val is not None)
                                     else None)
                rec["col_scale"] = scale(cp[0], DV_COT)
        cr, qf = rec.get("cell_ratio"), rec.get("query_factor")
        cs, qs = rec.get("col_scale"), rec.get("question_scale")

        if rec["n_selection"] != 1 or rec["n_evidence"] != 1:
            k = "KHONG_PHAI_MOT_O_DON"
        elif cr is None or cs is None or qs is None or qf is None:
            k = "KHONG_DO_DUOC"
        elif qs == "PERCENT" or cs == "PERCENT":
            k = "PERCENT_CAN_CONTRACT_RIENG"
        else:
            can = (10 ** (cs - qs)) / cr           # hệ số ĐÚNG phải dùng
            rec["expected_query_factor"] = can
            k = ("QUERY_FACTOR_DUNG"
                 if abs(qf - can) <= abs(can) * 1e-9 else "QUERY_FACTOR_SAI")
            rec["sai_bao_nhieu_lan"] = round(qf / can, 10) if can else None
        rec["ket_luan"] = k
        dem[k] += 1
        rows.append(rec)

    sai = [r for r in rows if r["ket_luan"] == "QUERY_FACTOR_SAI"]
    tom = {
        "_schema": "unit_convention_scan v1 — exact P0I, KHÔNG dùng gold",
        "zip": str(a.zip.name), "n_qid": len(rows),
        "phan_loai": dict(dem),
        "n_QUERY_FACTOR_SAI": len(sai),
        "phan_bo_sai_bao_nhieu_lan": dict(collections.Counter(
            f"x{r['sai_bao_nhieu_lan']:g}" for r in sai
            if r.get("sai_bao_nhieu_lan"))),
        "qid_sai": sorted(r["qid"] for r in sai),
        "cell_ratio_cua_o_duoc_chon": dict(collections.Counter(
            f"x{r['cell_ratio']:g}" for r in rows if r.get("cell_ratio"))),
        "GHI_CHU": ("`QUERY_FACTOR_SAI` = hệ số trong query khác hệ số suy ra từ "
                    "đơn vị cột + đơn vị câu hỏi + thang lưu của ô. Đây là điều "
                    "kiện CẦN, chưa phải điều kiện ĐỦ để nói đáp án sai — ô có "
                    "thể sai chỉ tiêu/kỳ (xem semantic audit)."),
    }
    (a.out / "unit_convention_per_qid.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")
    (a.out / "unit_convention_summary.json").write_text(
        json.dumps(tom, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in tom.items() if k != "qid_sai"},
                     ensure_ascii=False, indent=1))
    print("n qid_sai:", len(tom["qid_sai"]), "· 30 đầu:", tom["qid_sai"][:30])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
