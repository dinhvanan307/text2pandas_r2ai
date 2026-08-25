"""Dựng các artifact bắt buộc của packet H0 (docs/100 §5, §19)."""
from __future__ import annotations
import hashlib, json, os, re, sqlite3, subprocess, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/execution/h0"
OUT.mkdir(parents=True, exist_ok=True)
W = sqlite3.connect('file:' + os.path.abspath(ROOT/'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db') + '?mode=ro', uri=True)
CARD = sqlite3.connect('file:' + os.path.abspath(ROOT/'artifacts/legacy/silver-pre-a6/card_index.sqlite') + '?mode=ro', uri=True)
OCR = ROOT / "data/raw/btc/financial_statements"
_TAB = re.compile(r"<table.*?</table>", re.S)


def raw_snip(doc_id: str, line: int, n: int = 40) -> str:
    p = OCR / doc_id.split("_")[0] / doc_id.split("_")[-2] / doc_id / f"{doc_id}_extracted.txt"
    if not p.is_file():
        return ""
    ls = p.read_text(encoding="utf-8", errors="replace").splitlines()
    if not (1 <= line <= len(ls)):
        return ""
    m = _TAB.search("\n".join(ls[line-1:line+n]))
    return m.group(0) if m else ""


def hang_dau(html: str, k: int = 2) -> list[str]:
    rows = re.findall(r"<tr.*?</tr>", html, re.S)[:k]
    return [re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", r)).strip()[:300] for r in rows]


A6 = {r["qid"]: r for r in (json.loads(l) for l in (ROOT/"data/curated/dev-legacy/answer_a6/records_a6.jsonl").open(encoding="utf-8"))}
LG = {r["qid"]: r for r in (json.loads(l) for l in (ROOT/"data/curated/dev-legacy/answer_a6/resolve_log.jsonl").open(encoding="utf-8"))}
zg = zipfile.ZipFile(ROOT/"artifacts/submissions/legacy/submission_P0G2.zip")
zi = zipfile.ZipFile(ROOT/"artifacts/submissions/legacy/submission_P0I.zip")
G = {r["id"]: r for r in json.loads(zg.read("submission.json"))}
I = {r["id"]: r for r in json.loads(zi.read("submission.json"))}
SOHOC = set()
p = ROOT/"data/curated/dev-legacy/so_hoc/records_sohoc.jsonl"
if p.is_file():
    for l in p.open(encoding="utf-8"):
        r = json.loads(l)
        if r.get("trang_thai") == "OK":
            SOHOC.add(r.get("qid") or r.get("id"))

# ── 1 · changed_qids ────────────────────────────────────────────────────────
FIELDS = ("answer", "pandas_query", "evidence", "relevant_tables", "relevant_docs", "question")
n_doi = 0
with (OUT/"changed_qids.jsonl").open("w", encoding="utf-8") as f:
    for qid in sorted(G):
        doi = [k for k in FIELDS
               if json.dumps(G[qid].get(k), ensure_ascii=False) != json.dumps(I[qid].get(k), ensure_ascii=False)]
        if not doi:
            continue
        n_doi += 1
        a = A6.get(qid, {})
        f.write(json.dumps({
            "qid": qid, "changed_fields": doi,
            "reason_code": ("SOHOC_GIU_NGUYEN" if qid in SOHOC else a.get("nguon", "KHONG_RO")),
            "old_answer": G[qid].get("answer"), "new_answer": I[qid].get("answer"),
            "old_query": (G[qid].get("pandas_query") or "")[:200],
            "new_query": (I[qid].get("pandas_query") or "")[:200],
            "provenance": a.get("provenance"),
        }, ensure_ascii=False) + "\n")

# ── 2 · resolver_trace ──────────────────────────────────────────────────────
with (OUT/"resolver_trace_1012.jsonl").open("w", encoding="utf-8") as f:
    for qid in sorted(A6):
        r, lg = A6[qid], LG.get(qid, {})
        f.write(json.dumps({
            "qid": qid, "nguon": r["nguon"], "ly_do_fallback": lg.get("ly_do"),
            "n_uid_ung_vien": lg.get("n_uid"), "n_obs_ready": lg.get("n_ready"),
            "loc_ky": lg.get("loc_ky"), "loc_kind": lg.get("loc_kind"),
            "diem_nhan": lg.get("diem_nhan"), "n_dong_bang_diem": lg.get("n_dong_bang_diem"),
            "n_gia_tri_khac_nhau": lg.get("n_gia_tri"), "pha_hoa": lg.get("pha_hoa"),
            "nhap_nhang": bool(lg.get("nhap_nhang")), "scale_UNCERTAIN": bool(lg.get("scale_UNCERTAIN")),
            "collision_class": lg.get("collision_class"),
            "answer": r.get("answer"), "provenance": r.get("provenance"),
        }, ensure_ascii=False) + "\n")

# ── 3 · unit_evidence_conflicts (CÓ raw evidence span) ─────────────────────
UEXP = {f"{d}|{ln}": ue for d, ln, ue in CARD.execute("SELECT doc_id,line_no,unit_exponent FROM card_meta")}
n_xd = 0
with (OUT/"unit_evidence_conflicts.jsonl").open("w", encoding="utf-8") as f:
    for qid in sorted(A6):
        pr = A6[qid].get("provenance")
        if not pr or not pr.get("scale_UNCERTAIN"):
            continue
        ev = (pr["evidence_ref"] or "")
        doc, _, ln = ev.partition("|line:")
        html = raw_snip(doc, int(ln)) if ln else ""
        sec = W.execute("SELECT section_text, context_clean FROM tables WHERE table_uid=?",
                        (pr["table_uid"],)).fetchone() or ("", "")
        n_xd += 1
        f.write(json.dumps({
            "qid": qid, "observation_uid": pr["observation_uid"], "source_cell_uid": pr["source_cell_uid"],
            "table_uid": pr["table_uid"], "evidence_ref": ev,
            "A6": {"scale_exponent": pr["scale_exponent"], "scale_source": pr["scale_source"],
                   "unit_kind": pr["unit_kind"], "currency": pr["currency"],
                   "readiness_policy_version": "2.2"},
            "legacy_table_unit": {"unit_exponent": UEXP.get(ev.replace("|line:", "|")),
                                  "source": "card_index.sqlite/card_meta"},
            "raw_evidence": {"value_source_raw": pr["value_source_raw"],
                             "col_path_text": pr["col_path"], "row_path_text": pr["row_path"],
                             "section_text": (sec[0] or "")[:300],
                             "context_clean": (sec[1] or "")[:300],
                             "html_header_rows": hang_dau(html)},
            "normalized_interpretation_A6_vnd": pr["value_vnd"],
            "decision": "KEEP_A6_FLAGGED",
            "decision_reason": "A6 co scale_source la bang chung truc tiep; chua co phan xu tay",
            "status": "blocked_pending_adjudication",
        }, ensure_ascii=False) + "\n")

# ── 4 · retrieval_contract_diff ─────────────────────────────────────────────
diff = {k: sum(1 for q in G if json.dumps(G[q].get(k), ensure_ascii=False) != json.dumps(I[q].get(k), ensure_ascii=False))
        for k in ("relevant_tables", "relevant_docs", "question")}
(OUT/"retrieval_contract_diff.json").write_text(json.dumps({
    "parent": "submission_P0G2.zip", "child": "submission_P0I.zip",
    "n_questions": len(G), "diff_counts": diff,
    "verdict": "CONTRACT_INTACT" if sum(diff.values()) == 0 else "CONTRACT_BROKEN",
    "official_tables_f2_parent": 0.3538, "official_tables_f2_child": 0.3538,
}, ensure_ascii=False, indent=1))

print(f"changed_qids {n_doi} · trace {len(A6)} · unit_conflicts {n_xd} · contract {diff}")
