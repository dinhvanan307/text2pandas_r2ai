"""Liệt kê checkpoint, đánh dấu tệp CHÍNH DANH cho từng tag.

VÌ SAO CẦN
----------
`migrate` không xoá được tệp cũ (thư mục mount không cho `unlink`), nên sau khi
`cfg_sha` đổi thì một tag có thể có nhiều tệp — hiện tại `base` có **bốn**:

    ek_base_3189bebc….jsonl     20 câu   cấu hình cũ (gold_raw_limit 4000)
    ek_base_52cd55a9….jsonl   1012 câu   ← CHÍNH DANH
    ek_base_81e7eae6….jsonl   1012 câu   bản trước migrate
    ek_base_da55067a….jsonl   1012 câu   gold builder có bug return sớm

Ba trong bốn tệp đó KHÔNG được đọc số từ. `report`/`ab` an toàn vì chúng mở đúng
`cfg.checkpoint_name`, nhưng bất kỳ công cụ nào `glob` rồi lấy phần tử đầu/cuối
sẽ đọc sai — và `diag_nogold` đã mắc đúng lỗi đó (`glob(...)[-1]` cho `base` trả
về `da55067a`, tệp có bug).

Nên chỗ nào liệt kê checkpoint cũng phải nói rõ tệp nào chính danh.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.pipelines.retrieval.evalkit.cli import OUTDIR, _ck, _load_cfg  # noqa: E402


def main() -> int:
    files = sorted(OUTDIR.glob("ek_*.jsonl"))
    if not files:
        print("    (chưa có checkpoint nào)")
        return 0
    canon: dict[str, str | None] = {}
    for f in files:
        tag = f.stem[len("ek_"):].rpartition("_")[0]
        if tag and tag not in canon:
            try:
                canon[tag] = _ck(_load_cfg(tag, {})).name
            except SystemExit:
                canon[tag] = None          # tag không còn trong eval_v1.yaml
    n_cu = 0
    for f in files:
        tag = f.stem[len("ek_"):].rpartition("_")[0]
        n = sum(1 for line in f.open(encoding="utf-8") if line.strip())
        ok = canon.get(tag) == f.name
        n_cu += 0 if ok else 1
        print(f"  {'✓' if ok else ' '} {f.name:46s} {n:5d} câu")
    if n_cu:
        print(f"    {n_cu} tệp KHÔNG chính danh — cấu hình cũ, đừng đọc số từ chúng.")
        print("    (giữ lại để đối chiếu; mount không cho xoá)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
