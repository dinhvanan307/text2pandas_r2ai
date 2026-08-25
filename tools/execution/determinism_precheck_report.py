#!/usr/bin/env python3
"""docs/112 §9 — chạy generator HAI LẦN vào hai thư mục khác nhau rồi ghi
`determinism_precheck_report.json`: SHA precheck/summary/identity + exit code.

Không sửa gì trong cây nguồn. Không ghi đè artifact đã có.

    python3 tools/execution/determinism_precheck_report.py \
        --generator tools/execution/generate_answer_operation_precheck.py \
        --run1 /tmp/run1 --run2 /tmp/run2 \
        --out  op_evidence_v3/determinism_precheck_report.json \
        -- --questions ... --records ... (tham số của generator, trừ --out-dir)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

TEP = ("answer_operation_precheck.jsonl",
       "answer_operation_precheck_summary.json",
       "input_identity.json")


def sha(p: Path) -> str | None:
    return hashlib.sha256(p.read_bytes()).hexdigest() if p.is_file() else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--generator", required=True)
    ap.add_argument("--run1", required=True)
    ap.add_argument("--run2", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("rest", nargs=argparse.REMAINDER)
    a = ap.parse_args(argv)
    dt = [x for x in a.rest if x != "--"]

    lan = []
    for i, d in enumerate((a.run1, a.run2), 1):
        Path(d).mkdir(parents=True, exist_ok=True)
        cp = subprocess.run([sys.executable, a.generator, *dt, "--out-dir", d],
                            capture_output=True, text=True)
        lan.append({"run": i, "out_dir": str(Path(d).resolve()),
                    "exit_code": cp.returncode,
                    "stdout_tail": cp.stdout.strip().splitlines()[-5:],
                    "stderr_tail": cp.stderr.strip().splitlines()[-5:],
                    **{f"{t.split('.')[0]}_sha256": sha(Path(d) / t) for t in TEP}})

    khop = {t.split(".")[0]: lan[0][f"{t.split('.')[0]}_sha256"]
            == lan[1][f"{t.split('.')[0]}_sha256"] for t in TEP}
    kd = {"assert_exit_codes_zero": all(x["exit_code"] == 0 for x in lan),
          "assert_precheck_identical": khop["answer_operation_precheck"],
          "assert_summary_identical": khop["answer_operation_precheck_summary"],
          "assert_identity_identical": khop["input_identity"]}
    out = {"generator": str(Path(a.generator).resolve()),
           "generator_sha256": sha(Path(a.generator)),
           "generator_args": dt, "runs": lan,
           "identical": khop, "assertions": kd}
    Path(a.out).write_text(json.dumps(out, ensure_ascii=False, indent=1, sort_keys=True),
                           encoding="utf-8")
    for k, v in kd.items():
        print(f"{'PASS' if v else 'FAIL'}  {k}")
    return 0 if all(kd.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
