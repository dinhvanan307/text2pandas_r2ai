#!/usr/bin/env python3
"""Đối chiếu `submission.json` với ĐÚNG thang đo của ban tổ chức.

Khác `validate_submission.py` ở chỗ: tệp kia kiểm *hợp đồng nội bộ* (kiểu, đơn
vị, định dạng). Tệp này kiểm *thang đo bên ngoài* — nó đọc chính mã chấm điểm
trong `_codebase/src/vifinqa/evaluation/` và hỏi: với công thức đó, điểm của ta
bị chặn trên ở đâu, và vì sao.

Ba nguồn bằng chứng, không có nguồn thứ tư:

    questions.jsonl              1.012 câu hỏi, chỉ có `id` + `question`
    submission.json              đáp án + relevant_docs + relevant_tables của ta
    _codebase/.../evaluation/    công thức F₂ và `is_correct` của ban tổ chức

**KHÔNG có gold answer và KHÔNG có gold table trong bản phát hành công khai.**
Vì vậy tệp này KHÔNG tính được điểm. Nó chỉ tính được ba thứ, và mỗi thứ đều
là sự thật kiểm chứng được:

    1. TRẦN điểm — F₂ tối đa có thể đạt với số bảng ta đang trả về, giả sử
       recall hoàn hảo. Đây là chặn trên toán học, không phải ước lượng.
    2. Mâu thuẫn NỘI TẠI — câu hỏi hỏi công ty A mà ta trả tài liệu công ty B;
       hỏi năm 2018 mà không tài liệu nào thuộc 2018. Sai không cần gold.
    3. Rủi ro DUNG SAI — `ANSWER_ABS_TOL = 1e-2` với `rel_tol = 0`.

Chạy:  python tools/audit_submission_vs_metrics.py --submission <zip|json>
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import unicodedata
import zipfile
from collections import Counter
from pathlib import Path

# ── thang đo của ban tổ chức, chép lại nguyên văn công thức ─────────────────
# Không import từ `_codebase` vì gói đó không được cài; chép công thức và ghi
# rõ nguồn là cách trung thực hơn một import có thể gãy im lặng.
ANSWER_ABS_TOL = 1e-2          # constants.py
BETA = 2.0                     # retrieval_metrics.f_beta(2.0)


def f_beta(tp: int, retrieved: int, gold: int, beta: float = BETA) -> float:
    p = tp / retrieved if retrieved else 0.0
    r = tp / gold if gold else 0.0
    if p == 0.0 and r == 0.0:
        return 0.0
    b2 = beta * beta
    return (1 + b2) * p * r / (b2 * p + r)


def f2_ceiling(retrieved: int, gold: int) -> float:
    """F₂ TỐI ĐA khi mọi tài liệu vàng đều nằm trong tập trả về.

    tp = min(retrieved, gold). Đây là chặn trên đúng nghĩa: không cách nào
    vượt qua nó bằng cách xếp hạng tốt hơn, chỉ bằng cách trả về ít hơn.
    """
    return f_beta(min(retrieved, gold), retrieved, gold)


# ── chuẩn hoá tiếng Việt để so khớp tên công ty ─────────────────────────────
_SPECIAL = str.maketrans({"đ": "d", "Đ": "d", "ð": "d", "Ð": "d"})


def fold(text: str) -> str:
    t = (text or "").translate(_SPECIAL)
    t = unicodedata.normalize("NFD", t)
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", t).strip().lower()


_TICKER_PAREN = re.compile(r"\(([A-Z]{3})\)")
_YEAR = re.compile(r"\b(20[0-2]\d)\b")
_DOC_TICKER = re.compile(r"^([A-Z0-9]+)_financial_statements_(\d{4})_(\w+)")

# Đơn vị mà câu hỏi ĐÒI, lấy cụm cuối cùng sau `bao nhiêu` — tiếng Việt đặt
# yêu cầu chính ở cuối câu, nên câu ghép phải phân loại theo mệnh đề cuối.
_ASK = re.compile(
    r"bao\s*nhieu\s*(nghin\s*ty\s*dong|ty\s*dong|trieu\s*dong|nghin\s*dong"
    r"|phan\s*tram|%|lan|co\s*phieu|ngay|dong)\b")

# Dải độ lớn hợp lý cho từng đơn vị. ĐÂY LÀ PHÁN XÉT, không phải bằng chứng —
# mọi kết luận rút ra từ bảng này phải ghi rõ là *cảnh báo hình dạng*.
_BAND = {
    "ty dong":        (1e-2, 1e7),
    "trieu dong":     (1e0,  1e10),
    "nghin ty dong":  (1e-4, 1e4),
    "nghin dong":     (1e0,  1e13),
    "dong":           (1e0,  1e16),
    "phan tram":      (-1e3, 1e3),
    "%":              (-1e3, 1e3),
    "lan":            (-1e3, 1e4),
    "co phieu":       (1e0,  1e11),
    "ngay":           (0,    3.7e3),
}


def load_submission(path: Path) -> list[dict]:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as z:
            name = next(n for n in z.namelist() if n.endswith("submission.json"))
            return json.loads(z.read(name).decode("utf-8"))
    return json.loads(path.read_text(encoding="utf-8"))


def load_ticker_names(csv_path: Path) -> dict[str, str]:
    """`{tên công ty đã chuẩn hoá: mã CK}`. Nguồn: `code_stock.csv` của BTC."""
    out: dict[str, str] = {}
    if not csv_path.is_file():
        return out
    with csv_path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            code = (row.get("Mã CK") or "").strip()
            name = (row.get("Tên công ty") or "").strip()
            if code and name:
                out[fold(name)] = code
    return out


def expected_tickers(question: str, name_to_code: dict[str, str],
                     known: frozenset[str]) -> tuple[set[str], str]:
    """Mã CK mà câu hỏi TRỎ TỚI, kèm nguồn bằng chứng.

    Chỉ hai nguồn được chấp nhận, xếp theo độ mạnh:
      `paren`  mã nằm trong ngoặc VÀ có trong `code_stock.csv`
      `name`   tên công ty đầy đủ khớp nguyên văn với `code_stock.csv`

    Ràng buộc "có trong `code_stock.csv`" ở nhánh `paren` là bắt buộc: bản đầu
    không có nó và bắt nhầm `(CFO)`, `(ROE)`, `(EPS)` — chúng là viết tắt chỉ
    tiêu tài chính, không phải mã chứng khoán. Ba ca "sai công ty" đầu tiên tôi
    báo ra là do chính lỗi này, không phải do dữ liệu.

    Không có nguồn nào khớp thì trả `unknown` và câu đó bị LOẠI khỏi phép đo,
    chứ không bị đoán. Đoán ở đây sẽ tạo ra "lỗi" không tồn tại.
    """
    if hits := {t for t in _TICKER_PAREN.findall(question) if t in known}:
        return hits, "paren"
    q = fold(question)
    matched = [(n, c) for n, c in name_to_code.items() if n and n in q]
    if matched:
        best = max(len(n) for n, _ in matched)
        return {c for n, c in matched if len(n) == best}, "name"
    return set(), "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission", required=True)
    ap.add_argument("--questions", default="data/external/vifinqa/questions/questions.jsonl")
    ap.add_argument("--stock-csv", default="data/external/vifinqa/code_stock.csv")
    ap.add_argument("--json-out", default=None)
    a = ap.parse_args()

    sub = load_submission(Path(a.submission))
    qs = {json.loads(l)["id"]: json.loads(l)["question"]
          for l in Path(a.questions).read_text(encoding="utf-8").splitlines() if l.strip()}
    name_to_code = load_ticker_names(Path(a.stock_csv))
    known = frozenset(name_to_code.values())

    n = len(sub)
    rep: dict = {"submission": a.submission, "n_items": n,
                 "n_questions_official": len(qs)}

    # ═══ 1 · độ rộng truy hồi và TRẦN F₂ ═══════════════════════════════════
    n_docs = [len(r.get("relevant_docs") or []) for r in sub]
    n_tabs = [len(r.get("relevant_tables") or []) for r in sub]
    rep["retrieval"] = {
        "docs_per_question": {"min": min(n_docs), "median": sorted(n_docs)[n // 2],
                              "mean": round(sum(n_docs) / n, 2), "max": max(n_docs)},
        "tables_per_question": {"min": min(n_tabs), "median": sorted(n_tabs)[n // 2],
                                "mean": round(sum(n_tabs) / n, 2), "max": max(n_tabs)},
        "docs_hist": dict(sorted(Counter(n_docs).items())),
    }
    # Trần F₂ theo số giả định tài liệu vàng. Không biết `gold` thật, nên tính
    # cho vài giá trị và để người đọc chọn — thay vì chọn hộ rồi gọi đó là đo.
    rep["f2_ceiling_docs"] = {
        f"gold={g}": round(sum(f2_ceiling(d, g) for d in n_docs) / n, 4)
        for g in (1, 2, 3, 4)}
    rep["f2_ceiling_tables"] = {
        f"gold={g}": round(sum(f2_ceiling(t, g) for t in n_tabs) / n, 4)
        for g in (1, 2, 3, 5)}
    # Đường TRẦN theo mức cắt top-N. Đây là câu hỏi hành động được: cắt bao
    # nhiêu thì trần cao nhất. Trần KHÔNG phải điểm — cắt sâu làm rơi recall
    # thật, và không có gold thì không đo được phần rơi đó. Bảng này chỉ nói
    # "trần ở đâu", để đừng ai kỳ vọng vượt qua nó bằng cách xếp hạng khéo hơn.
    rep["f2_ceiling_by_cutoff"] = {
        f"top{k}": {f"gold={g}": round(
            sum(f2_ceiling(min(t, k), g) for t in n_tabs) / n, 4)
            for g in (1, 2, 3)}
        for k in (1, 2, 3, 5, 10)}
    rep["retrieval"]["n_empty_docs"] = sum(1 for d in n_docs if d == 0)
    rep["retrieval"]["n_empty_tables"] = sum(1 for t in n_tabs if t == 0)

    # ═══ 2 · mâu thuẫn nội tại — sai KHÔNG cần gold ════════════════════════
    ent = Counter()
    bad_entity, bad_year, bad_consistency = [], [], []
    for r in sub:
        qid = r.get("id")
        q = qs.get(qid, "")
        docs = r.get("relevant_docs") or []
        tabs = r.get("relevant_tables") or []

        want, src = expected_tickers(q, name_to_code, known)
        ent[src] += 1
        if want:
            got = {m.group(1) for d in docs if (m := _DOC_TICKER.match(d))}
            if got and not (want & got):
                ent["mismatch"] += 1
                bad_entity.append((qid, sorted(want), sorted(got), src))
            elif not got:
                ent["no_doc"] += 1

        yrs = {int(y) for y in _YEAR.findall(q)}
        if yrs and docs:
            dyr = {int(m.group(2)) for d in docs if (m := _DOC_TICKER.match(d))}
            # Báo cáo năm N chứa số so sánh năm N−1, nên {N, N+1} đều hợp lệ.
            if dyr and not any(y in dyr or (y + 1) in dyr for y in yrs):
                bad_year.append((qid, sorted(yrs), sorted(dyr)))

        tdocs = {t.rsplit("|", 1)[0] for t in tabs if "|" in t}
        if tdocs - set(docs):
            bad_consistency.append((qid, sorted(tdocs - set(docs))[:3]))

    rep["entity"] = {
        "evidence_source": {k: ent[k] for k in ("paren", "name", "unknown")},
        "n_measurable": ent["paren"] + ent["name"],
        "n_mismatch": len(bad_entity),
        "pct_mismatch": round(100 * len(bad_entity) / max(1, ent["paren"] + ent["name"]), 2),
        "samples": bad_entity[:15],
    }
    rep["year"] = {"n_mismatch": len(bad_year), "samples": bad_year[:15]}
    rep["consistency"] = {
        "n_tables_outside_docs": len(bad_consistency),
        "samples": bad_consistency[:10],
        "note": "bảng thuộc tài liệu KHÔNG có trong relevant_docs — hai trường"
                " tự mâu thuẫn, và F₂ cấp tài liệu bị phạt oan",
    }

    # ═══ 3 · đáp án ════════════════════════════════════════════════════════
    kinds = Counter()
    unit_ct, out_of_band, non_int = Counter(), [], 0
    for r in sub:
        v = r.get("answer")
        q = fold(qs.get(r.get("id"), ""))
        if v is None:
            kinds["null"] += 1
            continue
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            kinds[type(v).__name__] += 1
            continue
        kinds["number"] += 1
        if v == 0:
            kinds["zero"] += 1
        if v < 0:
            kinds["negative"] += 1
        if float(v) != int(v):
            non_int += 1
        hits = _ASK.findall(q)
        unit = hits[-1] if hits else "(không khai)"
        unit_ct[unit] += 1
        if unit in _BAND:
            lo, hi = _BAND[unit]
            if not (lo <= abs(v) <= hi or (unit in ("phan tram", "%", "lan") and lo <= v <= hi)):
                out_of_band.append((r.get("id"), unit, v))

    rep["answers"] = {
        "kinds": dict(kinds),
        "unit_requested": dict(unit_ct.most_common()),
        "n_non_integer": non_int,
        "pct_non_integer": round(100 * non_int / max(1, kinds["number"]), 2),
        "abs_tol": ANSWER_ABS_TOL,
        "tolerance_note": (
            "is_correct dùng math.isclose(rel_tol=0.0, abs_tol=1e-2). Với đáp án"
            " KHÔNG nguyên, sai số cho phép là 0,01 TUYỆT ĐỐI — không phải 1%."
            " Một giá trị 3.632.420,09 phải đúng tới hai chữ số thập phân."),
        "out_of_band": {"n": len(out_of_band), "samples": out_of_band[:20],
                        "note": "CẢNH BÁO HÌNH DẠNG, không phải kết luận sai —"
                                " dải độ lớn là phán xét, xem `_BAND`"},
    }

    # Đáp án TRÙNG NHAU giữa các câu hỏi khác nhau. Một giá trị lặp lại nhiều
    # lần là dấu hiệu tầng truy hồi sập về cùng một ô, hoặc một hằng số mặc
    # định lọt ra. Không phải bằng chứng sai, nhưng là chỗ đáng soi đầu tiên.
    vals = Counter(r.get("answer") for r in sub if isinstance(r.get("answer"), (int, float)))
    rep["answers"]["duplicate_values"] = {
        "n_distinct": len(vals),
        "top": [[v, c] for v, c in vals.most_common(10) if c > 1],
    }

    # ═══ 4 · phủ câu hỏi ═══════════════════════════════════════════════════
    ids = {r.get("id") for r in sub}
    rep["coverage"] = {
        "missing_ids": sorted(set(qs) - ids)[:20],
        "n_missing": len(set(qs) - ids),
        "extra_ids": sorted(ids - set(qs))[:20],
    }

    out = json.dumps(rep, ensure_ascii=False, indent=1)
    if a.json_out:
        Path(a.json_out).write_text(out, encoding="utf-8")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
