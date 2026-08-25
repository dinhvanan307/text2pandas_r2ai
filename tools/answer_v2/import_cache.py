#!/usr/bin/env python3
"""Nhập câu trả lời từ nơi khác vào cache của `llm_client`.

Cache là JSONL `{"k": băm_prompt, "v": câu_trả_lời}` và tên tệp gắn với
`identity.key()`. Nhập ngược = nối tệp, **nhưng phải đúng tệp**: nếu identity ở
máy chạy model khác identity ở máy chạy pipeline (khác `model_id`, khác
`temperature`, khác `prompt_template_hash`), băm khác nhau và cache thành vô
dụng — im lặng, không báo lỗi.

Vì vậy tool này **đối chiếu trước, nhập sau**, và báo rõ bao nhiêu khoá khớp với
tệp prompt đã xuất.

Chạy:
    python3 tools/answer_v2/import_cache.py \\
        --answers artifacts/llm_cache/cache_from_kaggle.jsonl \\
        --prompts artifacts/llm_cache/prompts_eval.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))

import cell_reranker as CR   # noqa: E402
import llm_client as LC      # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--answers", type=Path, required=True)
    ap.add_argument("--prompts", type=Path, default=None)
    ap.add_argument("--apply", action="store_true",
                    help="thực sự ghi; không có cờ này thì chỉ đối chiếu")
    a = ap.parse_args()

    client = LC.tu_config()
    client.identity.prompt_template_hash = CR.prompt_hash()
    # `tu_config` đã tạo path theo identity CŨ; dựng lại cho đúng identity mới.
    dich = LC.CACHE / f"rerank_v1_{client.identity.key()}.jsonl"

    ans = {}
    for l in a.answers.open(encoding="utf-8"):
        if l.strip():
            r = json.loads(l)
            ans[r["k"]] = r["v"]
    print(f"câu trả lời đọc được : {len(ans)}")

    if a.prompts and a.prompts.is_file():
        want = {json.loads(l)["k"] for l in a.prompts.open(encoding="utf-8")
                if l.strip()}
        khop = len(want & set(ans))
        print(f"prompt đã xuất       : {len(want)}")
        print(f"KHỚP                 : {khop}/{len(want)} "
              f"({khop / max(len(want), 1) * 100:.1f}%)")
        if khop == 0:
            print("\n✗ KHÔNG khớp khoá nào. Nguyên nhân gần như chắc chắn là "
                  "prompt template đổi giữa lúc xuất và lúc chạy model.\n"
                  f"  prompt_template_hash hiện tại: {CR.prompt_hash()}\n"
                  "  So với trường cùng tên trong prompts_*.meta.json.",
                  file=sys.stderr)
            return 2
        thieu = sorted(want - set(ans))[:5]
        if thieu:
            print(f"thiếu (5 đầu)        : {thieu}")

    da_co = set()
    if dich.is_file():
        da_co = {json.loads(l)["k"] for l in dich.open(encoding="utf-8") if l.strip()}
    moi = {k: v for k, v in ans.items() if k not in da_co}
    print(f"cache đích           : {dich.relative_to(ROOT)}")
    print(f"đã có {len(da_co)} · thêm mới {len(moi)}")

    if not a.apply:
        print("\n(chạy lại với --apply để thực sự ghi)")
        return 0

    dich.parent.mkdir(parents=True, exist_ok=True)
    with dich.open("a", encoding="utf-8") as f:
        for k, v in moi.items():
            f.write(json.dumps({"k": k, "v": v}, ensure_ascii=False) + "\n")
    print(f"✓ đã ghi {len(moi)} mục")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
