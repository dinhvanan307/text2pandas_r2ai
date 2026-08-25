#!/usr/bin/env python3
"""Replay a whole submission through the general answer pipeline and diff it
against the parent, per cohort, per QID.

    python3 tools/measure_v4/run_pipeline_e2e.py \
        --submission-zip data/submissions/submission_P0I.zip \
        --out-dir artifacts/pipeline_e2e_v4

The parent's ``evidence`` list is used as the *candidate pool* (this round is
explicitly not a retrieval experiment). Everything downstream of the pool --
frame, IR, binding, units, rendering, execution, validation, evidence -- is
recomputed by the new path with no QID knowledge.
"""
from __future__ import annotations

import argparse, collections, hashlib, json, sys, tempfile, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from text2pandas.answer_pipeline import answer_question  # noqa: E402
from text2pandas.answer_pipeline.adapters import (  # noqa: E402
    load_cells, load_frames, requested_unit_of,
)
from text2pandas.answer_pipeline.frame import classify_operation  # noqa: E402
from text2pandas.answer_pipeline.binding import Selector  # noqa: E402
from cellref import extract_cellrefs  # noqa: E402

REL_TOL = 1e-6


class PinnedSelector(Selector):
    """Binds slots to the cells the parent query already referenced, in order.

    This makes the run an ablation of the *answer-generation* layer alone:
    identical cells in, so any answer difference is attributable to the IR and
    the Unit Contract rather than to selection or retrieval.
    """

    def pick(self, slot, pool):
        # ``bind`` consumes cells from the pool, so the next slot's cell is
        # always the head of what remains -- an external index would overrun.
        return pool[0] if pool else None


def pin_pool(parent_query: str, pool):
    """Sub-pool restricted to the cells the parent query selected, in order."""
    refs, ok, _err = extract_cellrefs(parent_query or "")
    if not ok or not refs:
        return None
    picked = []
    for ref in refs:
        want_row = ref.filters.get("row_path")
        want_col = ref.filters.get("col_label")
        for c in pool:
            if c.df_var == ref.df_var and c.row_path == want_row and c.col_label == want_col:
                picked.append(c)
                break
    return picked or None


def cohort_of(op: str, factors) -> str:
    """direct_lookup vs unit_conversion is decided by whether the Unit Contract
    actually had to apply a factor, not by guesswork."""
    if op != "LOOKUP":
        return (op or "none").lower()
    if factors and any(f != 1.0 for f in factors.values()):
        return "unit_conversion"
    return "direct_lookup"


def close(a, b, tol=REL_TOL):
    if a is None or b is None:
        return a is None and b is None
    try:
        a, b = float(a), float(b)
    except (TypeError, ValueError):
        return False
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--submission-zip", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--pin-parent-cells", action="store_true",
                    help="bind operands to the cells the parent query used, so "
                         "the run isolates answer generation from selection")
    a = ap.parse_args()

    out = Path(a.out_dir).resolve()
    out.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="e2e_"))
    with zipfile.ZipFile(Path(a.submission_zip).resolve()) as zf:
        zf.extractall(work)
    recs = json.loads((work / "submission.json").read_text(encoding="utf-8"))
    if a.limit:
        recs = recs[: a.limit]

    pool_cache: dict[str, list] = {}
    rows = []
    for r in recs:
        qid = r["id"]
        question = r.get("question", "")
        evidence = r.get("evidence") or []
        pool = []
        for e in evidence:
            key = f"{e.get('variable')}|{e.get('csv_path')}"
            if key not in pool_cache:
                try:
                    pool_cache[key] = load_cells(e["csv_path"], e["variable"], root=work)
                except Exception:
                    pool_cache[key] = []
            pool.extend(pool_cache[key])

        try:
            frames = load_frames(evidence, root=work)
        except Exception:
            frames = {}

        selector = None
        pinned = None
        if a.pin_parent_cells:
            pinned = pin_pool(r.get("pandas_query"), pool)
            if pinned:
                pool, selector = pinned, PinnedSelector()

        res = answer_question(question, pool, frames, qid=qid,
                              requested_unit=requested_unit_of(question),
                              selector=selector)
        d = res.to_dict()
        d["pinned_cells"] = len(pinned) if pinned else 0
        parent_answer = r.get("answer")
        d["parent_answer"] = parent_answer
        d["parent_query"] = r.get("pandas_query")
        d["parent_n_evidence"] = len(evidence)
        d["answer_matches_parent"] = close(res.answer, parent_answer)
        factors = next((t.get("factors") for t in res.trace
                        if t.get("stage") == "RENDER"), None)
        d["cohort"] = cohort_of(res.ir.op if res.ir else classify_operation(question).op,
                                factors)
        # a question whose pinned pool offers more cells than the IR consumed is
        # an operation-recall miss: we answered a multi-operand question with a
        # single operand. Surfaced explicitly so it cannot look like a clean pass.
        d["operand_pool_underused"] = bool(
            pinned and res.ir and len(pinned) > res.ir.arity)
        d["evidence_complete"] = (
            res.status == "OK"
            and {e["variable"] for e in res.evidence}
            == {o.cell.df_var for o in res.operands}
        )
        rows.append(d)

    rows.sort(key=lambda x: x["qid"])
    with open(out / "pipeline_per_qid.jsonl", "w", encoding="utf-8") as fh:
        for d in rows:
            fh.write(json.dumps(d, ensure_ascii=False, sort_keys=True, default=str) + "\n")

    # ------------------------------------------------------------- metrics
    n = len(rows)
    produced = [d for d in rows if d["status"] == "OK"]
    by_stage = collections.Counter(d["stage_failed"] for d in rows if d["stage_failed"])
    by_reason = collections.Counter(
        (d["stage_failed"], (d["reason"] or "").split(":")[0]) for d in rows if d["stage_failed"])
    by_op = collections.Counter(d["operation"] or "NONE" for d in rows)
    by_cohort = collections.Counter(d["cohort"] for d in rows)

    multi = [d for d in produced if len(d["operands"]) > 1]
    summary = {
        "n_questions": n,
        "answer_produced": len(produced),
        "answer_produced_rate": round(len(produced) / n, 4) if n else 0.0,
        "abstained": n - len(produced),
        "operand_binding_rate": round(
            sum(1 for d in rows if d["operands"]) / n, 4) if n else 0.0,
        "multi_operand_answers": len(multi),
        "parent_multi_evidence": sum(1 for d in rows if d["parent_n_evidence"] > 1),
        "evidence_compliance": round(
            sum(1 for d in produced if d["evidence_complete"]) / len(produced), 4)
        if produced else 0.0,
        "agrees_with_parent": sum(1 for d in produced if d["answer_matches_parent"]),
        "differs_from_parent": sum(1 for d in produced if not d["answer_matches_parent"]),
        "operand_pool_underused": sum(1 for d in rows if d.get("operand_pool_underused")),
        "differs_and_pool_underused": sum(
            1 for d in produced
            if not d["answer_matches_parent"] and d.get("operand_pool_underused")),
        "failed_stage": dict(sorted(by_stage.items())),
        "failed_reason": {f"{k[0]}:{k[1]}": v for k, v in sorted(by_reason.items())},
        "operations": dict(sorted(by_op.items())),
        "cohorts": dict(sorted(by_cohort.items())),
    }
    (out / "pipeline_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
