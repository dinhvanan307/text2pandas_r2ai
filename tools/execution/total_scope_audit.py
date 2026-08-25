#!/usr/bin/env python3
"""Kiểm tra acceptance của docs/112 §4.6 trên `answer_operation_precheck.jsonl`.

Không sửa gì, chỉ ĐO và KHẲNG ĐỊNH. Thoát 1 nếu bất kỳ assertion nào FAIL.

    python3 tools/execution/total_scope_audit.py \
        --precheck op_evidence_v3/answer_operation_precheck.jsonl \
        --out      op_evidence_v3/total_scope_audit.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import unicodedata
from collections import Counter
from pathlib import Path

TONG = r"\btong\b"
CHU_Y = (13, 60, 84, 292)


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    t = "".join("d" if c == "đ" else c
                for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9 ]", " ", t)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--precheck", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    P = Path(a.precheck).resolve()
    rows = [json.loads(l) for l in P.open(encoding="utf-8") if l.strip()]

    n_span = n_in = n_out = 0
    theo_scope: Counter = Counter()
    head_hist: Counter = Counter()
    vi_pham_containment, vi_pham_accounting = [], []
    n_multi = 0
    for r in rows:
        fq = _fold(r["question"])
        es = [tuple(s) for s in r["entity_spans"]]
        thuc_te = len(re.findall(TONG, fq))
        sig = r["total_signals"]
        if not (len(sig) == r["n_total_spans"] == thuc_te):
            vi_pham_accounting.append(
                {"qid": r["qid"], "regex": thuc_te,
                 "n_total_spans": r["n_total_spans"], "len_signals": len(sig)})
        if len(sig) > 1:
            n_multi += 1
        for s in sig:
            n_span += 1
            theo_scope[s["scope"]] += 1
            head_hist[s["head_text"].split(" ")[0] if s["head_text"] else ""] += 1
            x, y = s["span"]
            trong = any(u <= x and y <= v for u, v in es)
            n_in += trong
            n_out += not trong
            if s["scope"] == "ENTITY_NAME" and not trong:
                vi_pham_containment.append({"qid": r["qid"], "span": s["span"],
                                            "head_text": s["head_text"]})

    theo_qid = Counter(r["total_signal_scope"] for r in rows)
    dis = {}
    for q in CHU_Y:
        r = next(x for x in rows if x["qid"] == q)
        dis[f"q{q}"] = {
            "question": r["question"],
            "entity_spans": r["entity_spans"],
            "total_signals": r["total_signals"],
            "total_signal_scope": r["total_signal_scope"],
            "primary_operation": r["primary_operation"],
            "allow_a6_single_cell": r["allow_a6_single_cell"],
            "proposed_action": r["proposed_action"],
            "selected_row_path": r["selected_row_path"],
        }

    kd = {
        "assert_entity_scope_span_containment": vi_pham_containment == [],
        "assert_all_total_spans_accounted": vi_pham_accounting == [],
        "assert_q13_q60_q84_van_direct_lookup": all(
            dis[f"q{q}"]["primary_operation"] == "DIRECT_LOOKUP" for q in (13, 60, 84)),
        "assert_q292_khong_con_direct_lookup":
            dis["q292"]["primary_operation"] != "DIRECT_LOOKUP"
            and dis["q292"]["allow_a6_single_cell"] is False,
        "assert_n_in_cong_n_out_eq_n_span": n_in + n_out == n_span,
    }
    out = {
        "precheck_path": P.name,
        "precheck_sha256": hashlib.sha256(P.read_bytes()).hexdigest(),
        "n_rows": len(rows),
        "n_total_spans": n_span,
        "n_inside_entity": n_in,
        "n_outside_entity": n_out,
        "n_metric": theo_scope["METRIC"],
        "n_entity_name": theo_scope["ENTITY_NAME"],
        "n_title_lexical": theo_scope["TITLE_LEXICAL"],
        "n_unmatched_entity_name": theo_scope["UNMATCHED_ENTITY_NAME"],
        "n_unknown": theo_scope["UNKNOWN"],
        "n_multi_total_questions": n_multi,
        "by_span_scope": dict(theo_scope.most_common()),
        "by_question_scope": dict(theo_qid.most_common()),
        "head_token_histogram": dict(head_hist.most_common()),
        "violations_entity_scope_span_containment": vi_pham_containment,
        "violations_total_span_accounting": vi_pham_accounting,
        "dispositions": dis,
        "assertions": kd,
    }
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True),
                           encoding="utf-8")
    for k, v in kd.items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    print(f"spans={n_span} inside={n_in} outside={n_out} multi_total_questions={n_multi}")
    return 0 if all(kd.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
