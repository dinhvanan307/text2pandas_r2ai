#!/usr/bin/env python3
"""D2 · Sinh `configs/execution/metric_registry_v1.yaml` DATA-DRIVEN từ A6 (work.db).

Nguyên tắc (124 §8-D2, 125 §5-D2): coverage phải ĐO, không hardcode "top 60 phủ
80%". Registry v1 = inventory nhãn metric thật của A6 + đối chiếu 1.012 câu hỏi.
Canonical hóa sâu (gộp alias, VAS code, forbidden confusions đầy đủ) là việc lặp
tiếp — v1 chỉ khai những gì đo được.

Sinh:
    configs/execution/metric_registry_v1.yaml
    reports/metric_registry_v1_coverage.json
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOP_N = 400


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.lower()).strip()


def main() -> int:
    con = sqlite3.connect(ROOT / "artifacts/retrieval/work.db")
    rows = con.execute(
        """SELECT metric_label_clean, COUNT(*) c, COUNT(DISTINCT ticker) nt
           FROM observations
           WHERE metric_label_clean IS NOT NULL AND length(metric_label_clean)>=4
           GROUP BY metric_label_clean ORDER BY c DESC LIMIT ?""",
        (TOP_N,)).fetchall()

    qs = [json.loads(l) for l in
          (ROOT / "data/dev/so_hoc/phan_loai.jsonl").open(encoding="utf-8")]
    lab_n = [(norm(l), l) for l, _, _ in rows if len(norm(l)) >= 8]
    covered, unresolved = [], []
    for q in qs:
        qn = norm(q["question"])
        hits = [l for ln, l in lab_n if ln in qn]
        (covered if hits else unresolved).append(
            {"qid": q["id"], "hits": hits[:3]} if hits else
            {"qid": q["id"], "question": q["question"][:100]})

    # YAML thủ công (tránh phụ thuộc thư viện khi replay packet)
    out = [
        "# metric_registry_v1 — SINH TỰ ĐỘNG từ A6 work.db (KHÔNG sửa tay file này;",
        "# sửa generator tools/build_metric_registry_v1.py rồi sinh lại).",
        f"# nguồn: observations.metric_label_clean top {TOP_N} theo tần suất.",
        f"# coverage đo được: {len(covered)}/1012 câu chứa >=1 nhãn (substring, xem report).",
        "version: 1",
        "generated_by: tools/build_metric_registry_v1.py",
        "workdb_sha256: e9f62775a75794d770954ba1903f7a90c8b97467e5398b0baa2057bec8e67d5f",
        "regression_defects:  # docs/120 §fresh_holdout_v2 — PHẢI thành test, không chữa bằng nới similarity",
        "  metric_different_concept_false_blocks: [18, 31, 144, 252, 284]",
        "  derived_quantity_leak: [104]",
        "  register: artifacts/retrieval/bundles/verify_117_v1/fresh_holdout_v2_defect_register.jsonl",
        "metrics:",
    ]
    for label, c, nt in rows:
        lab = label.replace('"', "'")
        out.append(f'  - label: "{lab}"')
        out.append(f"    n_obs: {c}")
        out.append(f"    n_tickers: {nt}")
    (ROOT / "configs/execution").mkdir(parents=True, exist_ok=True)
    (ROOT / "configs/execution/metric_registry_v1.yaml").write_text(
        "\n".join(out) + "\n", encoding="utf-8")

    rep = {
        "machine": "build", "date": "2026-08-20",
        "top_n_labels": TOP_N,
        "question_coverage_substring": {
            "covered": len(covered), "unresolved": len(unresolved),
            "rate": round(len(covered) / len(qs), 4),
            "note": "substring nhãn-trong-câu; hướng ngược (câu ngắn hơn nhãn VAS dài) "
                    "chưa tính — resolver dùng token overlap nên coverage thực tế cao hơn",
        },
        "unresolved_sample": unresolved[:25],
        "command": " ".join(sys.argv),
    }
    (ROOT / "reports/metric_registry_v1_coverage.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rep["question_coverage_substring"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
