#!/usr/bin/env python3
"""Xuất prompt ra JSONL — chạy KHÔNG cần model, để đem đi nơi khác chạy.

VÌ SAO TÁCH PROMPT KHỎI DỮ LIỆU
`work.db` nặng **4,2 GB**; toàn bộ prompt của cả 1.012 câu chỉ khoảng **5,6 MB**.
Đem 4 GB lên Kaggle mỗi phiên là vô lý; đem 5,6 MB thì tầm thường. Vì vậy:

    máy có DỮ LIỆU  →  xuất prompt (nhẹ)  →  máy có GPU  →  trả lời (nhẹ)
                    ←──────── nhập vào cache ────────────

`llm_client` vốn cache theo **băm prompt** dạng JSONL `{"k": hash, "v": answer}`,
nên nhập ngược chỉ là nối tệp. Không cần đồng bộ gì khác.

Chạy:
    python3 tools/answer_v2/export_prompts.py --scope eval    # 66 slot có gold
    python3 tools/answer_v2/export_prompts.py --scope full    # ~1539 slot
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))
sys.path.insert(0, str(ROOT / "tools"))

import cell_reranker as CR                     # noqa: E402
from execution.emit_arith_v1 import ARITH_INTENTS  # noqa: E402
from execution.emit_lookup_v1 import metric_phrase, spec_text  # noqa: E402
from execution.fact_rank_v1 import fetch_pool  # noqa: E402
from execution.operand_pipeline_v1 import load_aliases, slots_for  # noqa: E402
from execution.score_v2 import LADDER as SL, rank_pool  # noqa: E402
from build_candidate_v1 import registry_labels  # noqa: E402

WORK = ROOT / "artifacts/retrieval/work.db"
OUT = ROOT / "artifacts/llm_cache"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scope", choices=("eval", "full"), default="eval")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(f"file:{WORK}?mode=ro&immutable=1", uri=True)
    plans = {p["qid"]: p for p in (json.loads(l) for l in
             (ROOT / "evaluation/question_plans_1012.jsonl").open(encoding="utf-8"))}
    labs, al, fl = registry_labels(), load_aliases(), SL["S5"]

    if a.scope == "eval":
        gold = {g["qid"]: g for g in (json.loads(l) for l in
                (ROOT / "data/dev/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
                if not g.get("_meta")}
        qids = sorted(q for q, g in gold.items() if g["lop"] in ARITH_INTENTS)
    else:
        gold = {}
        qids = sorted(plans)
    if a.limit:
        qids = qids[: a.limit]

    ra, t0, n_bo = [], time.time(), 0
    for q in qids:
        plan = plans.get(q)
        if plan is None:
            continue
        it = (gold.get(q) or {}).get("lop") or plan.get("intent_v1") or "lookup"
        st = spec_text(plan, metric_phrase(plan, labs))
        ents, yrs = list(plan.get("entities") or []), sorted(plan.get("years") or [])
        if not ents or not yrs:
            n_bo += 1
            continue

        slots = (slots_for(plan, it, al) if it in ARITH_INTENTS else None)
        if not slots:
            # lookup: một slot = (entity đầu, năm cuối) — đúng cách production chọn
            class S:
                ticker, year, name = ents[0], yrs[-1], f"{ents[0]}/{yrs[-1]}"
            slots = [S()]

        for s in slots:
            sub = dict(plan)
            sub["entities"], sub["years"] = [s.ticker], [s.year]
            ranked = rank_pool(fetch_pool(con, sub, legacy_order=False),
                               sub, st, fl, None)
            if len(ranked) < 2:
                n_bo += 1
                continue
            p = CR.dung_prompt(plan.get("question", ""), ranked[:CR.K_MAC_DINH])
            ra.append({
                "k": hashlib.sha256(p.encode("utf-8")).hexdigest(),
                "prompt": p, "qid": q, "slot": s.name,
                "n_cand": min(len(ranked), CR.K_MAC_DINH),
            })

    # Trùng prompt là chuyện thường (hai slot cùng câu hỏi + cùng pool). Khử
    # trùng ở đây tiết kiệm đúng số lần gọi model.
    thay, uniq = set(), []
    for r in ra:
        if r["k"] in thay:
            continue
        thay.add(r["k"])
        uniq.append(r)

    f = OUT / f"prompts_{a.scope}.jsonl"
    with f.open("w", encoding="utf-8") as fh:
        for r in uniq:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    mb = f.stat().st_size / 1e6
    tok = sum(len(r["prompt"]) for r in uniq) // 3
    meta = {
        "scope": a.scope, "n_slot": len(ra), "n_prompt_duy_nhat": len(uniq),
        "n_bo_qua": n_bo, "file": str(f.relative_to(ROOT)),
        "size_mb": round(mb, 2), "uoc_luong_token_vao": tok,
        "prompt_template_hash": CR.prompt_hash(), "K": CR.K_MAC_DINH,
        "latency_s": round(time.time() - t0, 1),
        "luu_y": ("prompt_template_hash PHẢI khớp khi nhập cache ngược, nếu không "
                  "băm khác và mọi câu trả lời thành vô dụng"),
    }
    (OUT / f"prompts_{a.scope}.meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
    for k, v in meta.items():
        print(f"  {k:24} {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
