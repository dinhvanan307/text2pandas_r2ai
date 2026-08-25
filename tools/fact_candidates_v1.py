#!/usr/bin/env python3
"""D3 · FactCandidate MVP (plan 124 §8-D3, gate Q05) — KHÔNG sửa work.db.

MVP đúng scope 125 §5-D3: entity + period + metric-token-overlap + readiness.
Mở work.db chế độ READ-ONLY (immutable=1) — file SHA là identity, cấm ghi.
Không copy 2,6M rows; mỗi QID một query có filter ticker/year.

Đo trên gold-45 (A/B-only, survivorship đã khai):
    fact recall@1/@3/@10/@20 theo SLOT (mỗi slot gold một fact cần tìm)
    all-slot recall@20 theo QID
Hit = candidate.evidence_ref == gold.ref VÀ value_decimal_text == gold.raw.
Hit lỏng (chỉ ref) báo riêng để tách lỗi chọn Ô vs chọn BẢNG.

Sinh:
    reports/fact_candidates_v1_recall.json
    data/curated/evaluation/legacy/operand_candidates_sample.jsonl (top-20 của 45 QID gold)
"""
from __future__ import annotations

import json
import re
import sqlite3
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
K_LIST = [1, 3, 10, 20]

STOP = set("của công ty mẹ ctcp tmcp cổ phần năm cuối đầu là bao nhiêu triệu tỷ đồng "
           "trong các và đến ngày tháng theo với tại nhóm mã tính bằng đơn vị trên "
           "ghi nhận khoản mục vào bao gồm".split())


def toks(s: str) -> set[str]:
    s = unicodedata.normalize("NFC", s.lower())
    return {t for t in re.findall(r"[a-zà-ỹđ0-9]+", s) if len(t) >= 2 and t not in STOP}


def candidates_for(con: sqlite3.Connection, plan: dict, k: int = 20) -> list[dict]:
    ents = plan["entities"] or []
    years = plan["years"] or []
    if not ents or not years:
        return []
    year_pool = sorted({str(y) for y in years} | {str(y + 1) for y in years})
    qmarks_e = ",".join("?" * len(ents))
    qmarks_y = ",".join("?" * len(year_pool))
    basis = plan.get("basis", "unknown")
    basis_sql = " AND d.basis = ?" if basis in ("separate", "consolidated") else ""
    params: list = [*ents, *year_pool] + ([basis] if basis_sql else [])
    rows = con.execute(f"""
        SELECT o.observation_uid, o.evidence_ref, o.table_uid, o.ticker, o.doc_year,
               o.metric_label_clean, o.row_path_text, o.col_path_text,
               o.value_decimal_text, o.value_kind, o.statement_type,
               COALESCE(r.execution_ready, 0) ready
        FROM observations o
        JOIN documents d ON d.directory_doc_id = o.directory_doc_id
        LEFT JOIN observation_readiness r ON r.observation_uid = o.observation_uid
        WHERE o.ticker IN ({qmarks_e}) AND o.doc_year IN ({qmarks_y})
          AND o.value_decimal_text IS NOT NULL {basis_sql}
    """, params).fetchall()
    import math
    qt = toks(plan["question"])
    qnorm = re.sub(r"\s+", " ", unicodedata.normalize("NFC", plan["question"].lower()))
    tgt_years = {str(y) for y in years}

    # IDF trong pool ứng viên của chính QID: token phổ biến (tổng, cộng, số dư…)
    # gần như hết trọng số — chống nhãn aggregate ngắn leo hạng.
    pre = []
    df: dict[str, int] = {}
    for r in rows:
        lt = toks((r[5] or "") + " " + (r[6] or ""))
        pre.append((r, lt))
        for t in lt:
            df[t] = df.get(t, 0) + 1
    n_pool = max(len(pre), 1)

    scored = []
    for r, lt in pre:
        (uid, ref, tuid, tk, dy, lab, rp, cp, val, vk, st, ready) = r
        if not lt:
            continue
        inter = qt & lt
        if not inter:
            continue
        score = sum(math.log(1 + n_pool / df[t]) for t in inter) / (len(lt) ** 0.5)
        labn = re.sub(r"\s+", " ", unicodedata.normalize("NFC", (lab or "").lower())).strip()
        if len(labn) >= 8 and labn in qnorm:
            score += 3.0                           # câu chứa nguyên văn nhãn metric
        if any(y in (cp or "") for y in tgt_years):
            score += 0.6                           # cột đúng năm hỏi
        if str(dy) in tgt_years:
            score += 0.3                           # file đúng năm
        score += 0.3 * ready
        scored.append((score, {"observation_uid": uid, "evidence_ref": ref,
                               "table_uid": tuid, "ticker": tk, "doc_year": dy,
                               "metric_label": lab, "row_path": (rp or "")[:80],
                               "col_path": (cp or "")[:40], "value": val,
                               "ready": ready, "score": round(score, 4)}))
    scored.sort(key=lambda x: -x[0])

    # Quota theo năm hỏi (F2-aware N — plan 124/121 §4.4): câu nhiều năm không để
    # một năm "hot" chiếm hết top-k; round-robin mỗi năm lấy ứng viên tốt nhất.
    if len(tgt_years) > 1 or len(ents) > 1:
        def served(c: dict) -> str | None:
            for y in tgt_years:
                if y in (c["col_path"] or ""):
                    return y
            dy = str(c["doc_year"])
            if dy in tgt_years:
                return dy
            if str(int(dy) - 1) in tgt_years:
                return str(int(dy) - 1)
            return None
        buckets: dict[tuple, list] = {}
        for s, c in scored:
            buckets.setdefault((c["ticker"], served(c)), []).append(c)
        out: list[dict] = []
        seen: set[str] = set()
        years_rr = sorted({(e, y) for e in ents for y in (tgt_years or {None})})
        idx = {cell: 0 for cell in years_rr}
        while len(out) < k:
            progressed = False
            for y in years_rr:
                b = buckets.get(y, [])
                while idx[y] < len(b) and b[idx[y]]["observation_uid"] in seen:
                    idx[y] += 1
                if idx[y] < len(b) and len(out) < k:
                    c = b[idx[y]]
                    out.append(c)
                    seen.add(c["observation_uid"])
                    idx[y] += 1
                    progressed = True
            if not progressed:
                break
        for _, c in scored:  # lấp phần còn lại theo score toàn cục
            if len(out) >= k:
                break
            if c["observation_uid"] not in seen:
                out.append(c)
                seen.add(c["observation_uid"])
        return out
    return [c for _, c in scored[:k]]


def main() -> int:
    con = sqlite3.connect(f"file:{ROOT/'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db'}?mode=ro&immutable=1",
                          uri=True)
    plans = {p["qid"]: p for p in
             (json.loads(l) for l in
              (ROOT / "data/curated/evaluation/legacy/question_plans_1012.jsonl").open(encoding="utf-8"))}
    gold = [json.loads(l) for l in
            (ROOT / "data/curated/dev-legacy/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8")]
    gold = [g for g in gold if not g.get("_meta")]

    slot_tot = 0
    slot_hit = {k: 0 for k in K_LIST}
    slot_hit_ref_only = {k: 0 for k in K_LIST}
    qid_all20 = 0
    lat = []
    sample_out = (ROOT / "data/curated/evaluation/legacy/operand_candidates_sample.jsonl").open(
        "w", encoding="utf-8")
    misses = []
    for g in gold:
        p = plans[g["qid"]]
        t0 = time.time()
        cands = candidates_for(con, p, k=max(K_LIST))
        lat.append(time.time() - t0)
        sample_out.write(json.dumps({"qid": g["qid"], "candidates": cands},
                                    ensure_ascii=False) + "\n")
        slots = g.get("provenance") or []
        ok_all = True
        for s in slots:
            slot_tot += 1
            ref, raw = s.get("ref"), str(s.get("raw"))
            hit_at = None
            ref_at = None
            for i, c in enumerate(cands):
                if c["evidence_ref"] == ref and ref_at is None:
                    ref_at = i
                if c["evidence_ref"] == ref and c["value"] == raw:
                    hit_at = i
                    break
            for k in K_LIST:
                if hit_at is not None and hit_at < k:
                    slot_hit[k] += 1
                if ref_at is not None and ref_at < k:
                    slot_hit_ref_only[k] += 1
            if hit_at is None or hit_at >= 20:
                ok_all = False
                misses.append({"qid": g["qid"], "ref": ref, "raw": raw,
                               "nhan": s.get("nhan"), "ref_found_at": ref_at,
                               "top1": cands[0]["row_path"] if cands else None})
        if ok_all and slots:
            qid_all20 += 1
    lat.sort()
    rep = {
        "machine": "build", "date": "2026-08-20",
        "dataset": "gold_dap_an_v1 (45 QID, A/B-only, survivorship)",
        "n_qids": len(gold), "n_slots": slot_tot,
        "slot_recall": {f"@{k}": round(slot_hit[k] / slot_tot, 4) for k in K_LIST},
        "slot_recall_ref_only": {f"@{k}": round(slot_hit_ref_only[k] / slot_tot, 4)
                                  for k in K_LIST},
        "qid_all_slots_in_top20": qid_all20,
        "latency_s": {"p50": round(lat[len(lat)//2], 3), "p95": round(lat[int(len(lat)*0.95)], 3)},
        "misses_sample": misses[:12],
        "gate_Q05_dev_target": "fact recall@20 >= 0.95 (trên DEV thật; số ở đây là gold-45)",
        "command": " ".join(sys.argv),
    }
    (ROOT / "reports/fact_candidates_v1_recall.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: rep[k] for k in ["n_qids", "n_slots", "slot_recall",
                      "slot_recall_ref_only", "qid_all_slots_in_top20",
                      "latency_s"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
