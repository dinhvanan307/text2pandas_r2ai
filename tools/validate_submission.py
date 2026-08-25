#!/usr/bin/env python3
"""Kiểm gói nộp bài trước khi nộp — định dạng VÀ kiểu — rồi so hai gói.

Bản 1.0 chỉ kiểm **định dạng**: `submission.json` đúng hình dạng chưa, `id` có
trùng không, `relevant_tables` đúng quy ước `<doc_id>|<line_no>` chưa. Những
kiểm đó cần thiết nhưng chúng không nói gì về việc đáp án có **hợp lý** không.

Bản 2.0 thêm tầng thứ hai theo `19_PA3_type_contract_spec.md §6`: mỗi câu hỏi
khai một KIỂU đáp án kỳ vọng, và đáp án phải nằm trong dải của kiểu đó.

Vì sao cần: đo trên `submission_CARD.zip` (1.012 câu),

    260 câu hỏi "bao nhiêu %"  →  197 trả về một SỐ TIỀN THÔ (10³ – 10²⁹)
    118 câu có |đáp án| < 1    →  sai chiều quy đổi đơn vị
      2 câu vượt 10¹⁵          →  chia hai giá trị chưa quy về cùng đơn vị

Cả ba lớp đều **lọt qua** bộ kiểm định dạng: JSON hợp lệ, `id` không trùng,
`relevant_tables` đúng quy ước. Gói "hợp lệ" mà 37,5% đáp án sai loại.

HAI TẦNG, HAI HỆ QUẢ KHÁC NHAU — và đây là quyết định thiết kế quan trọng
nhất của công cụ:

    Lỗi ĐỊNH DẠNG  →  CHẶN (exit 1). Gói không nộp được.
    Lỗi KIỂU       →  ĐO (exit 0).   Gói vẫn nộp được.

Lý do không chặn ở tầng kiểu: đường cơ sở đang là **379/1.012 = 37,5%**. Nếu
chặn thì mọi gói đều "không hợp lệ" và công cụ mất tác dụng ngay ngày đầu.
Tầng kiểu là **thước đo tiến bộ**, không phải cổng. Nó tồn tại để trả lời câu
"bản mới có tốt hơn bản cũ không" mà **không cần nhãn vàng**.

    python tools/validate_submission.py data/submissions/submission_CARD.zip
    python tools/validate_submission.py new.zip old.zip --compare
    python tools/validate_submission.py x.zip --samples 10 --json reports/v.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:
    from data_pipeline.answer_contract import (CONTRACT_VERSION,
                                               classify_question, is_plausible)
    _TYPES = True
except ImportError:                                          # pragma: no cover
    # Không có `answer_contract` thì vẫn kiểm được định dạng. Nhưng phải NÓI
    # RA, không im lặng bỏ qua rồi in một báo cáo trông như đã kiểm đủ.
    _TYPES = False
    CONTRACT_VERSION = "khong-nap-duoc"

# Định dạng C20, xác nhận trên 9.910 mục của `submission_CARD.zip` và
# 19.808 mục của `submission_N20.zip`: KHÔNG có tiền tố `line:`.
TABLE_REF = re.compile(r"^[^|]+\|\d+$")
TABLE_REF_WRONG = re.compile(r"^[^|]+\|line:\d+$")
REQUIRED = ("id", "question", "answer", "relevant_docs", "relevant_tables")
FORBIDDEN = ("__MACOSX", ".DS_Store", ".venv", "credentials", ".env")

# Ngưỡng của bốn chỉ số §6. Không phải cổng chặn — là MỤC TIÊU để so tiến bộ.
TARGETS = {
    "pct_questions_plausible": ("câu `%` có đáp án trong dải", 200, "≥"),
    "answers_below_one": ("đáp án |x| < 1", 30, "≤"),
    "answers_above_1e15": ("đáp án vượt 10¹⁵", 0, "="),
    "type_failures": ("TỔNG câu không qua kiểm kiểu", 120, "≤"),
}


def load(path: Path) -> tuple[list, set[str]]:
    with zipfile.ZipFile(path) as z:
        names = set(z.namelist())
        if "submission.json" not in names:
            raise SystemExit(f"{path.name}: thiếu `submission.json` ở gốc zip")
        return json.loads(z.read("submission.json")), names


def _dec(x):
    try:
        return Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        return None


# ─────────────────────── tầng 2 · kiểm KIỂU ───────────────────────

def check_types(sub: list, n_samples: int = 5) -> dict:
    """Phân loại kiểu từng câu rồi kiểm đáp án có thuộc dải của kiểu không.

    Không sửa gì, không đoán gì. Chỉ đếm và lưu mẫu để truy nguyên.
    """
    by_kind: Counter = Counter()
    by_kind_fail: Counter = Counter()
    by_unit: Counter = Counter()
    # Đếm hỏng theo `kiểu|đơn vị`, không chỉ theo kiểu. Bản đầu in
    # `188/749` cho MỌI dòng `money` — đúng về tổng nhưng vô dụng để chẩn
    # đoán, vì không thấy `nghìn tỷ` hỏng khác `tỷ` ra sao.
    by_unit_fail: Counter = Counter()
    reasons: Counter = Counter()
    samples: dict[str, list] = defaultdict(list)
    flags: Counter = Counter()

    below_one = above_1e15 = pct_ok = pct_total = 0

    for r in sub:
        spec = classify_question(r.get("question") or "")
        key = f"{spec.value_kind}|{spec.unit_label}"
        by_kind[spec.value_kind] += 1
        by_unit[key] += 1
        for f in spec.flags:
            flags[f] += 1

        ok, why = is_plausible(r.get("answer"), spec)
        if not ok:
            by_kind_fail[spec.value_kind] += 1
            by_unit_fail[key] += 1
            # Rút gọn lý do thành lớp để đếm được, giữ nguyên câu đầy đủ
            # trong mẫu.
            cls = ("ngoài dải kiểu" if "ngoài dải hợp lý" in why
                   else "sai chiều quy đổi" if "quá" in why
                   else "đáp án 0" if "đáp án 0" in why
                   else "ngoài dải tiền" if "ngoài dải" in why
                   else "khác")
            reasons[f"{spec.value_kind} · {cls}"] += 1
            if len(samples[spec.value_kind]) < n_samples:
                samples[spec.value_kind].append({
                    "id": r.get("id"),
                    "question": (r.get("question") or "")[:110],
                    "answer": r.get("answer"),
                    "expected_kind": spec.value_kind,
                    "expected_unit": spec.unit_label,
                    "reason": why,
                })

        # Ba chỉ số độc lập với kiểu, đo trực tiếp trên con số.
        v = _dec(r.get("answer"))
        if v is not None and v != 0:
            av = abs(v)
            if av < 1:
                below_one += 1
            if av > Decimal("1e15"):
                above_1e15 += 1
        if spec.value_kind == "percentage":
            pct_total += 1
            if ok:
                pct_ok += 1

    return {
        "contract_version": CONTRACT_VERSION,
        "by_kind": dict(by_kind.most_common()),
        "by_kind_unit": dict(by_unit.most_common()),
        "by_kind_failures": dict(by_kind_fail.most_common()),
        "by_kind_unit_failures": dict(by_unit_fail.most_common()),
        "failure_reasons": dict(reasons.most_common()),
        "question_flags": dict(flags.most_common()),
        "type_failures": sum(by_kind_fail.values()),
        "pct_questions_total": pct_total,
        "pct_questions_plausible": pct_ok,
        "answers_below_one": below_one,
        "answers_above_1e15": above_1e15,
        "samples": {k: v for k, v in samples.items()},
    }


# ─────────────────────── tầng 1 · kiểm ĐỊNH DẠNG ───────────────────────

def check(path: Path, n_samples: int = 5) -> dict:
    sub, names = load(path)
    errors: list[str] = []
    warnings: list[str] = []

    junk = [n for n in names if any(f in n for f in FORBIDDEN)]
    if junk:
        errors.append(f"{len(junk)} mục rác trong archive: {junk[:3]}")

    if not isinstance(sub, list):
        raise SystemExit(f"{path.name}: `submission.json` phải là MẢNG")

    ids: Counter = Counter()
    fmt_ok = fmt_wrong = fmt_other = 0
    missing_field: Counter = Counter()
    zero_answer = null_answer = 0
    no_tables = no_docs = 0
    kinds: Counter = Counter()
    n_tables_per_q: list[int] = []
    n_docs_per_q: list[int] = []

    csvs = {n for n in names if n.startswith("data/") and n.endswith(".csv")}

    for r in sub:
        ids[r.get("id")] += 1
        for f in REQUIRED:
            if f not in r:
                missing_field[f] += 1
        a = r.get("answer")
        kinds[type(a).__name__] += 1
        if a is None:
            null_answer += 1
        elif a == 0:
            zero_answer += 1
        tabs = r.get("relevant_tables") or []
        docs = r.get("relevant_docs") or []
        n_tables_per_q.append(len(tabs))
        n_docs_per_q.append(len(docs))
        if not tabs:
            no_tables += 1
        if not docs:
            no_docs += 1
        for t in tabs:
            if TABLE_REF.match(t):
                fmt_ok += 1
            elif TABLE_REF_WRONG.match(t):
                fmt_wrong += 1
            else:
                fmt_other += 1

    dup = [i for i, n in ids.items() if n > 1]
    if dup:
        errors.append(f"{len(dup)} `id` trùng: {dup[:5]}")
    if missing_field:
        errors.append(f"thiếu trường bắt buộc: {dict(missing_field)}")
    if fmt_wrong:
        # Đây chính là cái bẫy khi nối Silver mới vào: `evidence_ref` nội bộ
        # dùng `<doc>|line:<n>`, còn bài nộp dùng `<doc>|<n>`. Sai 100% mục.
        errors.append(f"{fmt_wrong} `relevant_tables` mang tiền tố `line:` —"
                      " định dạng bài nộp KHÔNG có tiền tố này")
    if fmt_other:
        errors.append(f"{fmt_other} `relevant_tables` sai định dạng hoàn toàn")
    if len(kinds) > 1:
        warnings.append(f"`answer` không đồng nhất kiểu: {dict(kinds)}")

    if zero_answer:
        warnings.append(
            f"{zero_answer} câu có `answer = 0` — KHÔNG phân biệt được"
            " 'giá trị thật bằng 0' với 'không trả lời được nên trả 0'."
            " Đây là chỉ số nên so giữa các gói, không phải lỗi tự thân")
    if no_tables:
        warnings.append(f"{no_tables} câu không có `relevant_tables` — mất trọn C20")

    n = max(1, len(sub))
    avg_tabs = sum(n_tables_per_q) / n

    # Precision của TABLES bị CHẶN TRÊN bởi số bảng trả về. Với ~1 bảng vàng
    # mỗi câu, trả N bảng thì precision ≤ 1/N — bất kể truy hồi tốt đến đâu.
    # Đo được trên gói CARD: 9,79 bảng/câu, TABLES PRECISION = 0,0937 ≈ 1/9,79.
    if avg_tabs > 5:
        warnings.append(
            f"{avg_tabs:.2f} bảng/câu — trần precision ≈ {1/avg_tabs:.3f}."
            " F2 ≈ 5r/(4+N): giảm N là cách rẻ nhất để tăng điểm bảng")

    res = {
        "file": path.name,
        "bytes": path.stat().st_size,
        "n_questions": len(sub),
        "n_unique_ids": len(ids),
        "answer_kinds": dict(kinds),
        "answer_zero": zero_answer,
        "answer_null": null_answer,
        "no_relevant_tables": no_tables,
        "no_relevant_docs": no_docs,
        "avg_tables_per_question": round(avg_tabs, 2),
        "avg_docs_per_question": round(sum(n_docs_per_q) / n, 2),
        "table_refs_total": fmt_ok + fmt_wrong + fmt_other,
        "table_refs_valid": fmt_ok,
        "table_refs_with_line_prefix": fmt_wrong,
        "table_refs_malformed": fmt_other,
        "csv_files": len(csvs),
        "errors": errors,
        "warnings": warnings,
        "format_valid": not errors,
    }
    if _TYPES:
        res["types"] = check_types(sub, n_samples)
    else:
        res["types"] = None
        warnings.append("KHÔNG nạp được `data_pipeline.answer_contract` —"
                        " BỎ QUA toàn bộ kiểm kiểu. Chạy với PYTHONPATH=src")
    return res


# ─────────────────────── trình bày ───────────────────────

def _bar(v: int, total: int, w: int = 22) -> str:
    k = 0 if not total else round(w * v / total)
    return "█" * k + "·" * (w - k)


def show(r: dict, samples: int) -> None:
    mark = "✓" if r["format_valid"] else "✗"
    print(f"\n╔═══ {mark} {r['file']} · {r['bytes']/1024:.0f} KB ═══╗")
    print("  ── tầng 1 · ĐỊNH DẠNG " + "─" * 34)
    for k in ("n_questions", "n_unique_ids", "answer_zero", "answer_null",
              "no_relevant_tables", "table_refs_total", "table_refs_valid",
              "csv_files"):
        print(f"  {k:<30} {r[k]:>8,}")
    print(f"  {'bảng/câu (trung bình)':<30} {r['avg_tables_per_question']:>8.2f}")
    print(f"  {'tài liệu/câu':<30} {r['avg_docs_per_question']:>8.2f}")
    for e in r["errors"]:
        print(f"  ✗ {e}")
    for w in r["warnings"]:
        print(f"  ⚠ {w}")

    t = r.get("types")
    if not t:
        return

    n = r["n_questions"]
    print(f"\n  ── tầng 2 · KIỂU (contract {t['contract_version']}) " + "─" * 20)
    print(f"  {'kiểu | đơn vị':<30}{'câu':>6}{'hỏng':>5}{'':>6}  tỷ lệ hỏng")
    fu = t.get("by_kind_unit_failures") or {}
    for key, cnt in t["by_kind_unit"].items():
        f = fu.get(key, 0)
        pct = f"{100*f/cnt:.0f}%" if cnt else "-"
        print(f"  {key:<30}{cnt:>6}{f:>5}{pct:>6}  {_bar(f, cnt)}")

    print(f"\n  {'lý do hỏng':<44}{'số câu':>7}")
    for why, cnt in list(t["failure_reasons"].items())[:8]:
        print(f"  {why:<44}{cnt:>7}")

    if t["question_flags"]:
        print(f"\n  cờ câu hỏi: {t['question_flags']}")

    print(f"\n  ── bốn chỉ số §6 · so với mục tiêu " + "─" * 22)
    vals = {
        "pct_questions_plausible": t["pct_questions_plausible"],
        "answers_below_one": t["answers_below_one"],
        "answers_above_1e15": t["answers_above_1e15"],
        "type_failures": t["type_failures"],
    }
    for k, v in vals.items():
        label, target, op = TARGETS[k]
        ok = (v >= target if op == "≥" else
              v <= target if op == "≤" else v == target)
        extra = (f" / {t['pct_questions_total']}"
                 if k == "pct_questions_plausible" else
                 f" / {n}" if k == "type_failures" else "")
        print(f"  {'✓' if ok else '✗'} {label:<36}{v:>6,}{extra:<8}"
              f" mục tiêu {op} {target:,}")

    for kind, rows in (t["samples"] or {}).items():
        if not rows:
            continue
        print(f"\n  ── mẫu hỏng · {kind} " + "─" * (36 - len(kind)))
        for s in rows[:samples]:
            print(f"    #{s['id']:<5} {s['question']}")
            print(f"           → {s['answer']}   ({s['reason']})")


def compare(pa: Path, pb: Path, ra: dict, rb: dict) -> None:
    """So hai gói. `pa` là bản MỚI, `pb` là bản CŨ làm mốc."""
    sa, _ = load(pa)
    sb, _ = load(pb)
    ma = {r["id"]: r for r in sa}
    mb = {r["id"]: r for r in sb}
    common = sorted(set(ma) & set(mb))
    diff_ans = [i for i in common if ma[i].get("answer") != mb[i].get("answer")]
    only_a = [i for i in common
              if ma[i].get("answer") not in (0, None) and mb[i].get("answer") in (0, None)]
    only_b = [i for i in common
              if mb[i].get("answer") not in (0, None) and ma[i].get("answer") in (0, None)]

    print(f"\n╔═══ SO SÁNH · MỚI {ra['file']}  ↔  CŨ {rb['file']} ═══╗")
    print(f"  câu chung                    {len(common):>6,}")
    print(f"  đáp án KHÁC nhau             {len(diff_ans):>6,}")
    print(f"  chỉ bản MỚI trả lời được     {len(only_a):>6,}")
    print(f"  chỉ bản CŨ  trả lời được     {len(only_b):>6,}")

    ta, tb = ra.get("types"), rb.get("types")
    if not (ta and tb):
        print("\n  (không có tầng kiểu để so)")
        return

    print(f"\n  ── bốn chỉ số §6 · CŨ → MỚI " + "─" * 28)
    # `higher_better` quyết định mũi tên nào là tiến bộ. Ghi tường minh vì
    # đọc nhầm chiều một chỉ số là đọc ngược toàn bộ kết luận.
    metrics = [("pct_questions_plausible", True),
               ("answers_below_one", False),
               ("answers_above_1e15", False),
               ("type_failures", False)]
    regress = []
    for key, higher_better in metrics:
        old, new = tb[key], ta[key]
        d = new - old
        better = (d > 0) if higher_better else (d < 0)
        arrow = "→" if d == 0 else ("↑" if d > 0 else "↓")
        tag = "  " if d == 0 else ("✓ tốt hơn" if better else "✗ XẤU ĐI")
        if d != 0 and not better:
            regress.append(TARGETS[key][0])
        print(f"  {TARGETS[key][0]:<36}{old:>6,} {arrow} {new:>6,}"
              f"  ({d:+,})  {tag}")

    # Điều kiện dừng §8: số câu bỏ trống KHÔNG được tăng.
    d_zero = ra["answer_zero"] - rb["answer_zero"]
    print(f"  {'câu trả 0 / bỏ trống':<36}{rb['answer_zero']:>6,}"
          f" {'→' if d_zero == 0 else ('↑' if d_zero > 0 else '↓')}"
          f" {ra['answer_zero']:>6,}  ({d_zero:+,})"
          f"  {'✗ ĐIỀU KIỆN DỪNG' if d_zero > 0 else ''}")
    if d_zero > 0:
        regress.append("câu bỏ trống tăng — lọc kiểu quá chặt (§8)")

    print("\n  Không có nhãn vàng nên KHÔNG kết luận được bản nào ĐÚNG hơn."
          "\n  Bốn chỉ số trên đo tính HỢP LÝ, không đo tính đúng.")
    if regress:
        print("\n  ✗ CÓ HỒI QUY — truy nguyên trước khi nộp:")
        for x in regress:
            print(f"      · {x}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Kiểm gói nộp bài: định dạng (chặn) + kiểu (đo).")
    ap.add_argument("zips", nargs="+", type=Path,
                    help="gói cần kiểm; với --compare thì thứ tự là MỚI CŨ")
    ap.add_argument("--compare", action="store_true")
    ap.add_argument("--samples", type=int, default=3,
                    help="số mẫu hỏng in ra mỗi kiểu")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--strict-types", action="store_true",
                    help="coi lỗi KIỂU là lỗi chặn (mặc định chỉ đo)")
    a = ap.parse_args()

    results = []
    for p in a.zips:
        if not p.exists():
            print(f"✗ không thấy {p}", file=sys.stderr)
            return 2
        r = check(p, a.samples)
        results.append(r)
        show(r, a.samples)

    if a.compare and len(a.zips) == 2:
        compare(a.zips[0], a.zips[1], results[0], results[1])

    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        a.json.write_text(json.dumps(results, ensure_ascii=False, indent=1,
                                     default=str), encoding="utf-8")
        print(f"\n  -> {a.json}")

    bad = [r["file"] for r in results if not r["format_valid"]]
    if bad:
        print(f"\n✗ ĐỊNH DẠNG không hợp lệ: {', '.join(bad)}", file=sys.stderr)
        return 1

    if a.strict_types:
        over = [r["file"] for r in results
                if (r.get("types") or {}).get("type_failures", 0)
                > TARGETS["type_failures"][1]]
        if over:
            print(f"\n✗ KIỂU vượt ngưỡng: {', '.join(over)}", file=sys.stderr)
            return 1

    print("\n✓ định dạng hợp lệ. Lỗi kiểu (nếu có) là THƯỚC ĐO, không chặn nộp.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
