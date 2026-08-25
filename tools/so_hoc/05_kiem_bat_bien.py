"""P0-g bước 5 · KIỂM BẤT BIẾN `answer == eval(pandas_query)`.

Đây là cổng cứng, không phải phép đo. Một câu vi phạm là một câu bài nộp tự mâu
thuẫn: điểm Execution chấm bằng cách CHẠY `pandas_query` trên CSV, nên `answer`
lệch với kết quả chạy nghĩa là ta tự cho mình 0 điểm dù tìm đúng số.
"""
from __future__ import annotations
import json, math, sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
RA = ROOT / "data/curated/dev-legacy/so_hoc"
DATA = RA / "data"


def main() -> int:
    rec = [json.loads(l) for l in (RA / "records_sohoc.jsonl").open(encoding="utf-8") if l.strip()]
    ok = [r for r in rec if r["trang_thai"] == "OK"]
    dat = lech = hong = 0
    vi_pham = []
    for r in ok:
        env = {}
        thieu = False
        for e in r["evidence"]:
            p = DATA / Path(e["csv_path"]).name
            if not p.is_file():
                thieu = True
                break
            env[e["variable"]] = pd.read_csv(p)
        if thieu:
            hong += 1
            vi_pham.append((r["qid"], "thiếu CSV"))
            continue
        try:
            gt = eval(r["pandas_query"], {"abs": abs, "max": max, "min": min, "float": float}, env)
        except Exception as ex:
            hong += 1
            vi_pham.append((r["qid"], f"{type(ex).__name__}: {ex}"))
            continue
        if r["answer"] is not None and math.isclose(float(gt), float(r["answer"]),
                                                    rel_tol=1e-9, abs_tol=1e-6):
            dat += 1
        else:
            lech += 1
            vi_pham.append((r["qid"], f"answer {r['answer']} != eval {gt}"))
    print(f"câu OK: {len(ok)}")
    print(f"  giữ được bất biến : {dat}")
    print(f"  lệch giá trị      : {lech}")
    print(f"  chạy hỏng         : {hong}")
    for q, m in vi_pham[:12]:
        print(f"    q{q}: {m}")
    return 0 if lech == 0 and hong == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
