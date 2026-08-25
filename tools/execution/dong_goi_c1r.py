"""Dựng `C1R_LOCAL` = P0G2 (contract FREEZE) + đáp án A6-first ĐÃ PHÂN XỬ ĐƠN VỊ.

Khác C1: 34 câu được sửa scale theo raw evidence, 4 câu bị chặn -> fallback.
KHÔNG ghi đè bất kỳ submission nào đã tồn tại.
"""
from __future__ import annotations
import io, json, sys, zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from execution.dong_goi_tat_dinh import ghi_zip, json_chuan          # noqa: E402

NEN = ROOT / "artifacts/submissions/legacy/submission_P0G2.zip"
A6R = ROOT / "data/curated/dev-legacy/answer_a6/records_a6.jsonl"
DATA_A6, DATA_V3 = ROOT / "data/curated/dev-legacy/answer_a6/data", ROOT / "data/curated/dev-legacy/answer_v3/data"
SOHOC = ROOT / "data/curated/dev-legacy/so_hoc/records_sohoc.jsonl"


def dung(ra: Path, force: bool = False) -> dict:
    moi = {r["qid"]: r for r in (json.loads(l) for l in A6R.open(encoding="utf-8") if l.strip())}

    # ── CỔNG CỨNG B3: không record nào bị chặn/nghi ngờ được đi tiếp ────────
    xau = [q for q, r in moi.items()
           if r["nguon"] == "PRIMARY_A6" and (r.get("provenance") or {}).get("scale_UNCERTAIN")]
    if xau:
        raise SystemExit(f"CHAN: {len(xau)} cau PRIMARY_A6 con scale_UNCERTAIN -> {xau[:10]}")

    zin = zipfile.ZipFile(NEN)
    sub = json.loads(zin.read("submission.json"))
    goc = {r["id"]: r for r in json.loads(zin.read("submission.json"))}
    giu_sohoc = set()
    if SOHOC.is_file():
        for l in SOHOC.open(encoding="utf-8"):
            r = json.loads(l)
            if r.get("trang_thai") == "OK":
                giu_sohoc.add(r.get("qid") or r.get("id"))

    doi = giu = bo = 0
    for r in sub:
        qid = r["id"]
        if qid in giu_sohoc:
            bo += 1; continue
        m = moi.get(qid)
        if not m or not m.get("evidence") or m.get("answer") is None:
            giu += 1; continue
        if m["answer"] == goc[qid].get("answer") and m["pandas_query"] == goc[qid].get("pandas_query"):
            giu += 1; continue
        r["answer"], r["pandas_query"], r["evidence"] = m["answer"], m["pandas_query"], m["evidence"]
        doi += 1

    for r in sub:                       # CỔNG CỨNG hợp đồng Retrieval
        g = goc[r["id"]]
        for f in ("relevant_tables", "relevant_docs", "question"):
            if json.dumps(r.get(f), ensure_ascii=False) != json.dumps(g.get(f), ensure_ascii=False):
                raise SystemExit(f"q{r['id']}: {f} DA DOI — Retrieval dang FREEZE, dung")

    tv = {"submission.json": json_chuan(sub)}
    can = {e["csv_path"] for r in sub for e in (r.get("evidence") or []) if e.get("csv_path")}
    co_nen = set(zin.namelist())
    a = b = d = thieu = 0
    for path in sorted(can):
        name = path.split("/", 1)[1]
        if path in co_nen:
            tv[path] = zin.read(path); d += 1
        elif (DATA_A6 / name).is_file():
            tv[path] = (DATA_A6 / name).read_bytes(); a += 1
        elif (DATA_V3 / name).is_file():
            tv[path] = (DATA_V3 / name).read_bytes(); b += 1
        else:
            thieu += 1; print(f"  THIEU CSV: {path}")
    # ── CỔNG FAIL-CLOSED: KHÔNG bao giờ nộp một query không chạy được ─────
    # Chạy thử TỪNG query trên đúng bytes CSV sắp đóng gói. Câu nào vỡ thì
    # HOÀN NGUYÊN về đáp án của gói nền, không phát hành một câu lệnh hỏng.
    import pandas as pd
    B = {"float": float, "max": max, "min": min, "abs": abs, "sum": sum, "round": round, "len": len}
    cache, hoan_nguyen = {}, []
    for r in sub:
        ev = r.get("evidence") or []
        if not ev or not r.get("pandas_query") or r.get("answer") is None:
            continue
        env, vo = dict(B), False
        for e in ev:
            path = e.get("csv_path")
            if path not in tv:
                vo = True; break
            if path not in cache:
                if len(cache) > 150:
                    cache.clear()
                cache[path] = pd.read_csv(io.BytesIO(tv[path]))
            env[e["variable"]] = cache[path]
        if not vo:
            try:
                v = eval(r["pandas_query"], {"__builtins__": {}}, env)
                if abs(v - r["answer"]) > max(1e-9, abs(r["answer"]) * 1e-9):
                    vo = True
            except Exception:
                vo = True
        if vo:
            g = goc[r["id"]]
            r["answer"], r["pandas_query"], r["evidence"] = g.get("answer"), g.get("pandas_query"), g.get("evidence")
            hoan_nguyen.append(r["id"]); doi -= 1
    if hoan_nguyen:
        print(f"  HOAN NGUYEN ve goi nen (query khong chay duoc): {len(hoan_nguyen)} cau {hoan_nguyen[:10]}")
        tv["submission.json"] = json_chuan(sub)
        can2 = {e["csv_path"] for r in sub for e in (r.get("evidence") or []) if e.get("csv_path")}
        for path in sorted(can2 - set(tv)):
            name = path.split("/", 1)[1]
            if path in co_nen:
                tv[path] = zin.read(path)
            elif (DATA_A6 / name).is_file():
                tv[path] = (DATA_A6 / name).read_bytes()
            elif (DATA_V3 / name).is_file():
                tv[path] = (DATA_V3 / name).read_bytes()

    dv = ghi_zip(ra, tv, force=force)
    print(f"{ra.name}: {doi} doi · {giu} giu · {bo} giu SO HOC | CSV: nen {d} · A6 {a} · v3 {b} · thieu {thieu}")
    print(f"  zip_sha256 = {dv['zip_sha256']}  ({dv['bytes']:,} B · {dv['n_members']} member)")
    return dv


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    out = Path(args[0]) if args else ROOT / "artifacts/submissions/legacy/submission_C1R_LOCAL.zip"
    dv = dung(out, force="--force" in sys.argv)
    (ROOT / "artifacts/execution/h0" / f"dauvan_{out.stem}.json").write_text(
        json.dumps(dv, ensure_ascii=False, indent=1))
