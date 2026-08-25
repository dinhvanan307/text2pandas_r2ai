"""Đo độ phân giải thực thể trên 1.012 câu hỏi thật.

Không cần gold: 229 câu có nêu mã trong ngoặc là một tập TỰ CÓ NHÃN. Che mã đi
rồi hỏi bộ phân giải xem có ra đúng mã đó không — nhãn đến từ chính câu hỏi,
không phải từ output của hệ thống.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from retrieval.question_intent import parse_intent          # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
QS = ROOT / "data/raw/btc/questions/questions.jsonl"
CS = ROOT / "data/raw/btc/metadata/companies.csv"
_PAREN_TICKER = re.compile(r"\(([A-Z]{3})\)")


def load():
    comp = {r["Mã CK"].strip(): r["Tên công ty"].strip()
            for r in csv.DictReader(CS.open(encoding="utf-8"))}
    qs = [json.loads(l) for l in QS.open(encoding="utf-8")]
    return comp, qs


def main(alias_path: str | None = None) -> int:
    comp, qs = load()
    if alias_path:                       # bảng alias mở rộng, dạng {ticker: [tên...]}
        import yaml
        ext = yaml.safe_load(Path(alias_path).read_text(encoding="utf-8"))["aliases"]
    else:
        ext = None

    how = Counter(); nres = 0; years = 0
    labelled = ok = miss = wrong = 0
    sai = []
    for q in qs:
        text = q["question"]
        it = parse_intent(text, ext or comp)
        tickers = set(it.tickers)
        how[it.resolved_by] += 1
        if len(tickers) == 1: nres += 1
        if it.years: years += 1

        m = _PAREN_TICKER.search(text)
        if m and m.group(1) in comp:
            labelled += 1
            gold = m.group(1)
            masked = _PAREN_TICKER.sub("", text)          # che mã đi
            got = set(parse_intent(masked, ext or comp).tickers)
            if got == {gold}: ok += 1
            elif not got: miss += 1; sai.append(("MISS", gold, masked[:70]))
            else: wrong += 1; sai.append(("WRONG->" + ",".join(sorted(got)), gold, masked[:70]))

    P = print
    P(f"tong cau hoi                 : {len(qs)}")
    P(f"phan giai duoc DUNG MOT ma   : {nres}  ({100*nres/len(qs):.1f}%)")
    P(f"trich duoc nam               : {years}  ({100*years/len(qs):.1f}%)")
    P(f"nguon phan giai              : {dict(how)}")
    P("")
    P(f"-- tu kiem tren cau CO ma trong ngoac (che ma di) --")
    P(f"so cau co nhan               : {labelled}")
    P(f"  dung                       : {ok}   ({100*ok/labelled:.1f}%)")
    P(f"  khong ra ma nao (MISS)     : {miss}")
    P(f"  ra ma KHAC (WRONG)         : {wrong}")
    if sai:
        P("\n  20 ca dau:")
        for k, g, t in sai[:20]: P(f"   [{k}] gold={g}  {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
