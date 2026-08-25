#!/usr/bin/env python3
"""Sinh `answer_operation_precheck.jsonl` + summary + `input_identity.json`.

Đường dẫn TƯỜNG MINH, không phụ thuộc thư mục làm việc, không phụ thuộc trạng
thái ngầm của cây nguồn. Chạy hai lần cùng input phải cho cùng SHA-256.

    python3 generate_answer_operation_precheck.py \
        --questions   data/external/vifinqa/questions/questions.jsonl \
        --records     data/dev/answer_a6/records_a6.jsonl \
        --sohoc       data/dev/so_hoc/records_sohoc.jsonl \
        --code-stock  data/external/vifinqa/code_stock.csv \
        --work-db     artifacts/retrieval/work.db \
        --src         src \
        --out-dir     op_evidence_v2
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import sqlite3
import sys
from collections import Counter
from pathlib import Path


def sha(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    for k in ("questions", "records", "sohoc", "code-stock", "work-db", "src", "out-dir"):
        ap.add_argument(f"--{k}", required=True)
    ap.add_argument("--rule-src", default=None, help="đường dẫn answer_operation.py")
    a = ap.parse_args(argv)

    src = Path(a.src).resolve()
    sys.path.insert(0, str(src))
    rule_src = Path(a.rule_src).resolve() if a.rule_src else \
        Path(__file__).resolve().parent / "answer_operation.py"
    sys.path.insert(0, str(rule_src.parent.parent))

    from data_pipeline.answer_contract import CONTRACT_VERSION, classify_question
    from execution.answer_operation import (ENUM_STATUS, OPERATIONS, RULE_VERSION,
                                            entity_hits, phan_loai)
    from text2pandas.domain.rules.question import CompanyIndex

    QP, RP = Path(a.questions).resolve(), Path(a.records).resolve()
    SP, CP = Path(a.sohoc).resolve(), Path(getattr(a, "code_stock")).resolve()
    WP = Path(getattr(a, "work_db")).resolve()
    OUT = Path(getattr(a, "out_dir")).resolve()
    OUT.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(f"file:{WP}?mode=ro", uri=True)
    known = {r[0] for r in conn.execute(
        "SELECT DISTINCT ticker FROM documents WHERE ticker IS NOT NULL")}
    known_sha = hashlib.sha256(json.dumps(sorted(known)).encode()).hexdigest()
    companies = CompanyIndex.from_csv(CP)

    Q = {q["id"]: q["question"] for q in
         (json.loads(l) for l in QP.open(encoding="utf-8") if l.strip())}
    rec = {r["qid"]: r for r in
           (json.loads(l) for l in RP.open(encoding="utf-8") if l.strip())}
    sohoc = set()
    if SP.is_file():
        for l in SP.open(encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                if r.get("trang_thai") == "OK":
                    sohoc.add(r.get("qid") or r.get("id"))

    rows = []
    for qid in sorted(Q):
        spec = classify_question(Q[qid])
        r = rec.get(qid, {})
        pr = r.get("provenance") or {}
        ev = r.get("evidence") or []
        query = r.get("pandas_query") or ""
        d = dataclasses.asdict(phan_loai(
            qid, Q[qid], spec, companies=companies, known=known,
            selected_row_path=pr.get("row_path"), query=query,
            evidence_vars=[e.get("variable") for e in ev if e.get("variable")]))
        src_kind = "SOHOC" if qid in sohoc else r.get("nguon", "UNKNOWN")
        if src_kind == "SOHOC":
            act, why = "KEEP_SOHOC", "dap an tu engine so hoc P0-g"
        elif src_kind != "PRIMARY_A6":
            act, why = "KEEP_FALLBACK", f"nguon hien tai la {src_kind}"
        elif d["allow_a6_single_cell"]:
            act, why = "ALLOW_A6_CANDIDATE_PENDING_AUDIT", "DIRECT_LOOKUP + AST OK; chua qua human audit"
        else:
            act, why = "BLOCK_NON_DIRECT_LOOKUP", d["decision_reason"]
        d.update({
            # docs/112 §4.6 — audit đếm lại span `tổng` từ chính trường này,
            # nên KHÔNG cắt ngắn nữa (v3 cắt 200 ký tự làm sai phép đếm).
            "question": Q[qid],
            "current_answer_source": src_kind,
            "proposed_action": act,
            "proposed_action_reason": why,
            "source_record_ref": f"records_a6.jsonl#qid={qid}",
            "selected_evidence_ref": pr.get("evidence_ref"),
            "selected_col_path": pr.get("col_path"),
            "query_sha256": hashlib.sha256(query.encode()).hexdigest() if query else None,
        })
        rows.append(d)

    assert len(rows) == 1012 and len({r["qid"] for r in rows}) == 1012

    jl = OUT / "answer_operation_precheck.jsonl"
    jl.write_text("\n".join(json.dumps(r, ensure_ascii=False, sort_keys=True)
                            for r in rows) + "\n", encoding="utf-8")

    # summary DERIVE TỪ JSONL vừa ghi, không nhập tay
    doc = [json.loads(l) for l in jl.open(encoding="utf-8")]
    op = Counter(r["primary_operation"] for r in doc)
    act_c = Counter(r["proposed_action"] for r in doc)
    cx = Counter(r["complexity_class"] for r in doc)
    subs = Counter(s for r in doc for s in r["sub_operations"])
    astc = Counter(r["ast_reason"] for r in doc)
    summary = {
        "rule_version": RULE_VERSION, "contract_version": CONTRACT_VERSION,
        "n_rows": len(doc), "n_unique_qid": len({r["qid"] for r in doc}),
        "operations_enum": list(OPERATIONS), "enum_status": ENUM_STATUS,
        "by_primary_operation": dict(op.most_common()),
        "by_sub_operation": dict(subs.most_common()),
        "by_complexity": dict(cx.most_common()),
        "by_proposed_action": dict(act_c.most_common()),
        "by_ast_reason": dict(astc.most_common()),
        "derived_from": jl.name,
        "precheck_sha256": sha(jl),
        "assertions": {
            "rows_eq_1012": len(doc) == 1012,
            "unique_qid_eq_1012": len({r["qid"] for r in doc}) == 1012,
            "sum_operations_eq_rows": sum(op.values()) == len(doc),
            "sum_actions_eq_rows": sum(act_c.values()) == len(doc),
            "sum_complexity_eq_rows": sum(cx.values()) == len(doc),
            "primary_not_in_sub": all(r["primary_operation"] not in r["sub_operations"] for r in doc),
        },
    }
    (OUT / "answer_operation_precheck_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    ident = {
        "generated_by": "generate_answer_operation_precheck.py",
        "questions_sha256": sha(QP),
        "source_answer_records_sha256": sha(RP),
        "sohoc_records_sha256": sha(SP) if SP.is_file() else None,
        "company_alias_catalog_sha256": sha(CP),
        "known_ticker_set_sha256": known_sha,
        "operation_rule_source_sha256": sha(rule_src),
        "answer_contract_source_sha256": sha(src / "data_pipeline/answer_contract.py"),
        "answer_contract_version": CONTRACT_VERSION,
        # docs/112 §9: v3 đặt tên `parse_question_source_sha256` gây hiểu nhầm là
        # generator gọi `parse_question`. Generator CHỈ dùng `CompanyIndex` trong
        # file này; đổi tên cho đúng thứ thật sự được dùng.
        "company_index_source_sha256": sha(src / "text2pandas/domain/rules/question.py"),
        "generator_sha256": sha(Path(__file__).resolve()),
        "total_scope_audit_source_sha256": sha(
            Path(__file__).resolve().parent / "total_scope_audit.py"),
        "work_db_path": str(WP), "work_db_bytes": WP.stat().st_size,
        # docs/112 §9: KHÔNG hash lại 4,24 GB mỗi vòng. Danh tính DB đối với
        # output này được ĐẠI DIỆN bởi `known_ticker_set_sha256` — đó là toàn bộ
        # thứ generator đọc từ DB (`SELECT DISTINCT ticker FROM documents`).
        "work_db_identity_represented_by": "known_ticker_set_sha256",
        "work_db_sha256": None,
        "python": sys.version.split()[0], "sqlite": sqlite3.sqlite_version,
    }
    ident["n_sha256_fields_non_null"] = sum(
        1 for k, v in ident.items() if k.endswith("_sha256") and v)
    (OUT / "input_identity.json").write_text(
        json.dumps(ident, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")

    print(f"rows={len(doc)} unique={summary['n_unique_qid']} sha={summary['precheck_sha256'][:16]}")
    for k, v in act_c.most_common():
        print(f"  {k:<42}{v:>5}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
