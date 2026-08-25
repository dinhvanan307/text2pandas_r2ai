#!/usr/bin/env python3
"""Đối chiếu blind recheck 20% và hợp nhất — doc 161 §6 Pha 1 bước 2.

Luật hợp nhất **bảo thủ**: bất kỳ lượt nào nói không chắc thì nhãn cuối là không
chắc. Lý do: một nhãn `OK` sai sẽ được Pha 2 tin và tạo ra chẩn đoán sai; một nhãn
`GOLD_UNCERTAIN` đúng chỉ làm giảm cỡ mẫu. Hai hậu quả không đối xứng.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GD = ROOT / "data/dev/answer_gold"


def doc(p: Path) -> dict:
    return {r["qid"]: r for r in (json.loads(l) for l in p.open(encoding="utf-8")
                                  if l.strip())}


def bang_nhau(a, b) -> bool:
    if a is None or b is None:
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        m = max(abs(float(a)), abs(float(b)), 1e-12)
        return abs(float(a) - float(b)) / m < 1e-3       # khớp tới 0,1%
    return str(a).strip().lower() == str(b).strip().lower()


def main() -> int:
    g = doc(GD / "answer_gold_wave1.jsonl")
    r = doc(GD / "recheck_blind.jsonl")

    so, doi = [], 0
    for q in sorted(r):
        p1, p2 = g[q], r[q]
        khop = bang_nhau(p1.get("normalized_answer_gold") or p1.get("answer_gold"),
                         p2.get("normalized_answer_gold") or p2.get("answer_gold"))
        ts_khac = p1.get("trang_thai") != p2.get("trang_thai")
        so.append({"qid": q,
                   "pass1_answer": p1.get("answer_gold"),
                   "recheck_answer": p2.get("answer_gold"),
                   "answer_khop": khop,
                   "pass1_trang_thai": p1.get("trang_thai"),
                   "recheck_trang_thai": p2.get("trang_thai"),
                   "trang_thai_khac": ts_khac})
        # hợp nhất bảo thủ
        if p2.get("trang_thai") != "OK" and p1.get("trang_thai") == "OK":
            p1["trang_thai"] = p2["trang_thai"]
            p1["uncertain_reason"] = (
                "HOP_NHAT_BAO_THU: blind recheck báo không chắc — "
                + str(p2.get("uncertain_reason") or ""))
            p1["label_confidence"] = "low"
            doi += 1
        p1["blind_recheck"] = {"da_kiem": True, "answer_khop": khop,
                               "recheck_answer": p2.get("answer_gold"),
                               "recheck_trang_thai": p2.get("trang_thai")}
        if not khop:
            p1["trang_thai"] = "GOLD_UNCERTAIN"
            p1["uncertain_reason"] = "BAT_DONG_GIUA_HAI_LUOT_GAN_NHAN"
            p1["label_confidence"] = "low"

    for q, v in g.items():
        v.setdefault("blind_recheck", {"da_kiem": False})

    hop = [g[q] for q in sorted(g)]
    p_out = GD / "answer_gold_wave1_final.jsonl"
    p_out.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in hop) + "\n",
                     encoding="utf-8")

    n_khop = sum(1 for s in so if s["answer_khop"])
    tt = {}
    for x in hop:
        tt[x["trang_thai"]] = tt.get(x["trang_thai"], 0) + 1
    kq = {
        "_schema": "blind_recheck_report v1",
        "n_gold": len(hop),
        "n_recheck": len(so),
        "ty_le_recheck": round(len(so) / len(hop), 4),
        "answer_khop": f"{n_khop}/{len(so)}",
        "ty_le_bat_dong_answer": round(1 - n_khop / len(so), 4),
        "nguong_doc161": 0.05,
        "GATE_BAT_DONG": "PASS" if (1 - n_khop / len(so)) <= 0.05 else "FAIL",
        "n_ha_cap_sau_hop_nhat": doi,
        "trang_thai_cuoi": tt,
        "chi_tiet": so,
        "sha256_final": hashlib.sha256(p_out.read_bytes()).hexdigest(),
    }
    (GD / "blind_recheck_report.json").write_text(
        json.dumps(kq, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(kq, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
