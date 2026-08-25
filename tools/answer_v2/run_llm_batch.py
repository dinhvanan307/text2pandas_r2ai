#!/usr/bin/env python3
"""Chạy model trên tệp prompt — ĐỘC LẬP với repo. Đem lên Kaggle/Colab được.

Tệp này cố ý **không import gì từ repo**. Đầu vào là `prompts_*.jsonl`, đầu ra là
cache JSONL cùng định dạng `llm_client` đọc. Nhờ vậy nó chạy trong một notebook
Kaggle trống, không cần `work.db` 4,2 GB, không cần `src/`.

Ba backend, chọn bằng `--backend`:

    ollama        HTTP tới Ollama đang chạy      (mặc định, hợp máy Mac)
    openai        HTTP OpenAI-compatible          (vLLM, LM Studio, llama.cpp)
    transformers  nạp model trực tiếp             (Kaggle GPU, không cần server)

Ghi **nối thêm** sau mỗi câu trả lời, nên ngắt giữa chừng không mất việc đã làm:
chạy lại sẽ bỏ qua prompt đã có.

Kaggle:
    !pip -q install transformers accelerate
    !python run_llm_batch.py --backend transformers \\
        --model Qwen/Qwen2.5-14B-Instruct --in prompts_full.jsonl --out cache.jsonl
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path


def da_co(out: Path) -> set[str]:
    if not out.is_file():
        return set()
    return {json.loads(l)["k"] for l in out.open(encoding="utf-8") if l.strip()}


def chay_http(prompts, args, url, kieu):
    import requests
    for r in prompts:
        if kieu == "ollama":
            body = {"model": args.model, "prompt": r["prompt"], "stream": False,
                    "options": {"temperature": 0.0, "num_predict": args.max_tokens,
                                "seed": 0}}
            resp = requests.post(f"{url}/api/generate", json=body, timeout=args.timeout)
            resp.raise_for_status()
            yield r, resp.json().get("response", "")
        else:
            body = {"model": args.model,
                    "messages": [{"role": "user", "content": r["prompt"]}],
                    "temperature": 0.0, "top_p": 1.0, "seed": 0,
                    "max_tokens": args.max_tokens}
            resp = requests.post(f"{url}/v1/chat/completions", json=body,
                                 timeout=args.timeout)
            resp.raise_for_status()
            yield r, resp.json()["choices"][0]["message"]["content"]


def chay_transformers(prompts, args):
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    tok = AutoTokenizer.from_pretrained(args.model)
    model = AutoModelForCausalLM.from_pretrained(
        args.model, torch_dtype=torch.float16, device_map="auto")
    model.eval()
    B = args.batch
    for i in range(0, len(prompts), B):
        lo = prompts[i:i + B]
        texts = [tok.apply_chat_template([{"role": "user", "content": r["prompt"]}],
                                         tokenize=False, add_generation_prompt=True)
                 for r in lo]
        enc = tok(texts, return_tensors="pt", padding=True,
                  truncation=True, max_length=4096).to(model.device)
        with torch.no_grad():
            # do_sample=False ⇒ greedy ⇒ tất định, khớp temperature=0 của nhánh HTTP
            out = model.generate(**enc, max_new_tokens=args.max_tokens,
                                 do_sample=False,
                                 pad_token_id=tok.pad_token_id or tok.eos_token_id)
        for r, o, n in zip(lo, out, enc["input_ids"]):
            yield r, tok.decode(o[len(n):], skip_special_tokens=True)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--backend", choices=("ollama", "openai", "transformers"),
                    default="ollama")
    ap.add_argument("--model", default="qwen2.5:14b")
    ap.add_argument("--url", default="http://localhost:11434")
    ap.add_argument("--max-tokens", type=int, default=16)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--timeout", type=float, default=180.0)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    prompts = [json.loads(l) for l in a.inp.open(encoding="utf-8") if l.strip()]
    xong = da_co(a.out)
    con_lai = [r for r in prompts if r["k"] not in xong]
    if a.limit:
        con_lai = con_lai[: a.limit]
    print(f"tổng {len(prompts)} · đã có {len(xong)} · còn {len(con_lai)}")
    if not con_lai:
        return 0

    a.out.parent.mkdir(parents=True, exist_ok=True)
    gen = (chay_transformers(con_lai, a) if a.backend == "transformers"
           else chay_http(con_lai, a, a.url, a.backend))

    t0, n = time.time(), 0
    with a.out.open("a", encoding="utf-8") as fh:
        for r, tra_loi in gen:
            fh.write(json.dumps({"k": r["k"], "v": tra_loi, "t": time.time()},
                                ensure_ascii=False) + "\n")
            fh.flush()                      # ngắt giữa chừng không mất việc
            n += 1
            if n % 25 == 0 or n == len(con_lai):
                d = time.time() - t0
                print(f"  {n}/{len(con_lai)} · {d / n:.2f}s/prompt · "
                      f"còn ~{(len(con_lai) - n) * d / n / 60:.1f} phút",
                      flush=True)
    print(f"xong {n} · {time.time() - t0:.0f}s · -> {a.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
