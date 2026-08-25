#!/usr/bin/env python3
"""Chọn execution DEV-60 + FINAL_AUDIT-40 (plan 124 §4, feedback 125 §P0-C).

Quy tắc:
- seed cố định, stratified proportional theo `intent_v1` (sàn 2 câu/lớp có mặt);
- LOẠI 45 QID của gold_dap_an_v1 (preregister overlap = 0 — câu 9 của 125);
- DEV và AUDIT rời nhau;
- AUDIT seal: manifest SHA ghi `identity/final_audit_seal.json`; dossier audit
  BLIND (không chứa prediction/ranking — 125 §P0-C).

Sinh:
    data/dev/execution_gold/dev60_selection.json
    data/dev/execution_gold/audit40_selection.json
    identity/final_audit_seal.json
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED = 20260820
N_DEV, N_AUDIT = 60, 40
FLOOR = 2


def stratified(pool_by_intent: dict[str, list[int]], n_total: int,
               rng: random.Random) -> list[int]:
    total_pool = sum(len(v) for v in pool_by_intent.values())
    picked: list[int] = []
    # sàn trước
    quota: dict[str, int] = {}
    for it, qids in pool_by_intent.items():
        quota[it] = min(FLOOR, len(qids))
    used = sum(quota.values())
    # phần còn lại proportional
    rem = n_total - used
    fracs = []
    for it, qids in pool_by_intent.items():
        share = rem * len(qids) / total_pool
        add = int(share)
        quota[it] += min(add, len(qids) - quota[it])
        fracs.append((share - add, it))
    # bù phần lẻ
    short = n_total - sum(quota.values())
    for _, it in sorted(fracs, reverse=True):
        if short <= 0:
            break
        if quota[it] < len(pool_by_intent[it]):
            quota[it] += 1
            short -= 1
    for it, k in quota.items():
        picked += rng.sample(pool_by_intent[it], k)
    return sorted(picked)


def main() -> int:
    plans = [json.loads(l) for l in
             (ROOT / "evaluation/question_plans_1012.jsonl").open(encoding="utf-8")]
    gold_qids = {json.loads(l)["qid"] for l in
                 (ROOT / "data/dev/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8")
                 if not json.loads(l).get("_meta")}
    pool = [p for p in plans if p["qid"] not in gold_qids]
    by_intent: dict[str, list[int]] = defaultdict(list)
    for p in pool:
        by_intent[p["intent_v1"]].append(p["qid"])

    rng = random.Random(SEED)
    dev = stratified(by_intent, N_DEV, rng)
    by_intent2 = {it: [q for q in qids if q not in set(dev)]
                  for it, qids in by_intent.items()}
    audit = stratified(by_intent2, N_AUDIT, rng)
    assert not set(dev) & set(audit) and not (set(dev) | set(audit)) & gold_qids

    pm = {p["qid"]: p for p in plans}
    out_dir = ROOT / "data/dev/execution_gold"
    out_dir.mkdir(parents=True, exist_ok=True)

    def dump(qids: list[int], name: str, note: str) -> dict:
        obj = {"seed": SEED, "n": len(qids), "note": note,
               "excluded_gold45": sorted(gold_qids),
               "intent_dist": dict(Counter(pm[q]["intent_v1"] for q in qids)),
               "qids": qids}
        (out_dir / name).write_text(json.dumps(obj, ensure_ascii=False, indent=1),
                                    encoding="utf-8")
        return obj

    d = dump(dev, "dev60_selection.json", "execution DEV — được nhìn/tune")
    a = dump(audit, "audit40_selection.json",
             "FINAL_AUDIT — SEALED, mở đúng 1 lần ở D10; directional only (n=40)")
    seal = hashlib.sha256(json.dumps(a, sort_keys=True).encode()).hexdigest()
    (ROOT / "identity/final_audit_seal.json").write_text(json.dumps({
        "sealed": "2026-08-20", "selection_sha256": seal,
        "open_policy": "mở đúng MỘT lần tại D10; tuyệt đối không đọc per-QID trước đó",
        "statistical_claim_limit": "directional only — Wilson CI n=40 quá rộng cho 0,65 (124 §4)",
        "access_log": []}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"dev_dist": d["intent_dist"], "audit_dist": a["intent_dist"],
                      "audit_seal": seal[:16]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
