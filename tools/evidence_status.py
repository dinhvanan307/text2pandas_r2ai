#!/usr/bin/env python3
"""P1-01 + P1-02 · ràng buộc cho `RC_STATUS.json` và `EVIDENCE_MANIFEST.json`.

Hai khiếm khuyết mà module này chặn:

**P1-01** — `acceptance_met = true` từng được gán theo "đã chạy được", không
theo "đã đạt ở đúng phạm vi acceptance đòi". RC-00/RC-04/RC-11/RC-23/RC-24 đều
`PASS` trong khi bằng chứng chỉ là fixture hoặc unit test.

**P1-02** — mọi claim dùng chung một khối `environment` và lấy
`started_at/finished_at` từ `test_report.json`, tức **thời gian đóng gói**,
không phải thời gian chạy lệnh của chính claim đó. Reviewer bắt được: C1 report
sinh `03:22:56Z` còn claim ghi `03:48:13Z`.

Dùng như thư viện (bộ sinh gọi `validate_*`) hoặc như CLI để kiểm artifact có
sẵn:

    python tools/evidence_status.py --rc-status status/RC_STATUS.json \\
                                    --evidence-manifest EVIDENCE_MANIFEST.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Phạm vi bằng chứng, xếp từ yếu tới mạnh. Một RC đòi `full_data` mà bằng chứng
# chỉ ở `unit` thì KHÔNG được `acceptance_met`.
SCOPE_RANK = {"none": 0, "static": 1, "unit": 2, "fixture": 3,
              "baseline_rc1": 4, "full_data": 5}

PROVENANCE_CLASSES = {"machine_generated", "operator_copied", "reviewer_reproduced"}
HOST_ROLES = {"build_host", "evidence_host", "device_bridge"}

# Nhãn KHÔNG được mang `acceptance_met = true`.
NON_PASSING = {"NOT_RUN", "IMPLEMENTED_NOT_RUN", "OPEN", "BLOCKED",
               "FIXED_NOT_RERUN", "FIXED_PARTIAL"}


def validate_rc_status(doc: dict) -> list[str]:
    """Trả danh sách vi phạm. Rỗng = hợp lệ."""
    errs: list[str] = []
    for rc in doc.get("rc", []):
        rid = rc.get("id", "?")
        met = bool(rc.get("acceptance_met"))
        if not met:
            continue
        if not rc.get("evidence_paths"):
            errs.append(f"{rid}: acceptance_met=true nhưng evidence_paths rỗng")
        st = str(rc.get("status", ""))
        if st in NON_PASSING:
            errs.append(f"{rid}: acceptance_met=true mà status={st}")
        need = str(rc.get("acceptance_scope", "")) or None
        have = str(rc.get("evidence_scope", "")) or None
        if need or have:
            if need not in SCOPE_RANK or have not in SCOPE_RANK:
                errs.append(f"{rid}: scope không hợp lệ (cần={need}, có={have})")
            elif SCOPE_RANK[have] < SCOPE_RANK[need]:
                errs.append(f"{rid}: acceptance đòi `{need}` nhưng bằng chứng "
                            f"chỉ ở `{have}` — không được PASS")
    return errs


def validate_evidence_manifest(doc: dict) -> list[str]:
    errs: list[str] = []
    for c in doc.get("claims", []):
        cid = c.get("claim_id", "?")
        st = str(c.get("status", ""))
        if st in ("NOT_RUN",):
            continue
        for k in ("executed_on_host_role", "executed_at_utc", "packaged_at_utc",
                  "provenance_class"):
            if not c.get(k):
                errs.append(f"{cid}: thiếu `{k}`")
        role = c.get("executed_on_host_role")
        if role and role not in HOST_ROLES:
            errs.append(f"{cid}: host_role lạ `{role}`")
        pc = c.get("provenance_class")
        if pc and pc not in PROVENANCE_CLASSES:
            errs.append(f"{cid}: provenance_class lạ `{pc}`")
        if pc == "operator_copied" and st == "PASS":
            errs.append(f"{cid}: `operator_copied` KHÔNG được mang nhãn PASS — "
                        f"đó là lời khai, không phải artifact máy sinh")
        ex, pk = c.get("executed_at_utc"), c.get("packaged_at_utc")
        if ex and pk and str(ex) > str(pk):
            errs.append(f"{cid}: executed_at ({ex}) SAU packaged_at ({pk})")
        if st == "PASS" and not c.get("machine_readable_report") \
                and not c.get("stdout_stderr_path"):
            errs.append(f"{cid}: PASS nhưng không có report lẫn log")
    return errs


def main() -> int:
    ap = argparse.ArgumentParser(description="P1-01/P1-02 · kiểm ràng buộc status")
    ap.add_argument("--rc-status")
    ap.add_argument("--evidence-manifest")
    a = ap.parse_args()
    if not a.rc_status and not a.evidence_manifest:
        print("LỖI: cần --rc-status hoặc --evidence-manifest", file=sys.stderr)
        return 2
    errs: list[str] = []
    for path, fn, lbl in ((a.rc_status, validate_rc_status, "RC_STATUS"),
                          (a.evidence_manifest, validate_evidence_manifest,
                           "EVIDENCE_MANIFEST")):
        if not path:
            continue
        p = Path(path)
        if not p.is_file():
            print(f"MISSING ARTIFACT: {p}", file=sys.stderr)
            return 2
        e = fn(json.loads(p.read_text(encoding="utf-8")))
        print(f"  {lbl}: {len(e)} vi phạm")
        for x in e:
            print(f"    ✗ {x}")
        errs += e
    print(f"\n  {'ĐẠT' if not errs else 'KHÔNG ĐẠT'} — {len(errs)} vi phạm")
    return 0 if not errs else 3


if __name__ == "__main__":
    sys.exit(main())
