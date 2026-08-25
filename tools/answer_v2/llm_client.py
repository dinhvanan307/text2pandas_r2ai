#!/usr/bin/env python3
"""Client LLM — tách HẲN khỏi logic, có cache đĩa, chạy được cả khi KHÔNG có model.

BA RÀNG BUỘC THIẾT KẾ, đều xuất phát từ bài học đã trả giá trong dự án này:

1. **Offline-first.** Máy build không có GPU/runtime. Nếu logic reranker chỉ chạy
   được khi có model thì không ai test được nó, và lỗi chỉ lộ ra lúc chạy thật.
   Ở đây: không có endpoint ⇒ `available=False` ⇒ tầng trên rơi về scorer tất
   định và ghi `not_exercised`. Không ném, không treo.

2. **Cache đĩa theo băm prompt.** Một lần gọi model, vĩnh viễn replay được. Nhờ
   vậy `run_rerank_eval` chạy lại không tốn GPU, và người review kiểm được đúng
   thứ ta đã đo. Cache là JSONL nối thêm — an toàn khi bị ngắt giữa chừng.

3. **Ghim danh tính.** `model_id · revision · quantization · runtime · nhiệt độ ·
   seed · băm prompt template`. Không ghim thì hai lần chạy khác nhau và mọi so
   sánh A/B mất nghĩa. Doc 144 §11.6 đòi đúng điều này.

Giao thức: OpenAI-compatible `/v1/chat/completions` — vLLM, Ollama, LM Studio,
llama.cpp server đều nói được. Không khoá vào một runtime cụ thể.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CACHE = ROOT / "artifacts/llm_cache"


@dataclass
class LLMIdentity:
    """Mọi thứ ảnh hưởng tới output. Đổi bất kỳ trường nào ⇒ cache miss."""

    model_id: str = "Qwen/Qwen2.5-14B-Instruct"
    revision: str = "unknown"
    quantization: str = "none"
    runtime: str = "openai-compatible"
    temperature: float = 0.0
    top_p: float = 1.0
    seed: int = 0
    max_tokens: int = 16
    prompt_template_hash: str = ""

    def key(self) -> str:
        d = {k: v for k, v in self.__dict__.items()}
        return hashlib.sha256(
            json.dumps(d, sort_keys=True).encode()).hexdigest()[:16]


@dataclass
class LLMClient:
    endpoint: str | None = None
    identity: LLMIdentity = field(default_factory=LLMIdentity)
    cache_name: str = "rerank_v1"
    timeout: float = 60.0
    _cache: dict = field(default_factory=dict, init=False)
    _cache_path: Path = field(init=False, default=None)
    n_hit: int = field(default=0, init=False)
    n_call: int = field(default=0, init=False)
    n_loi: int = field(default=0, init=False)

    def __post_init__(self):
        self.endpoint = self.endpoint or os.environ.get("ANSWER_V2_LLM_ENDPOINT")
        CACHE.mkdir(parents=True, exist_ok=True)
        self._cache_path = CACHE / f"{self.cache_name}_{self.identity.key()}.jsonl"
        if self._cache_path.is_file():
            for line in self._cache_path.open(encoding="utf-8"):
                if line.strip():
                    r = json.loads(line)
                    self._cache[r["k"]] = r["v"]

    # ── trạng thái ─────────────────────────────────────────────────────────
    @property
    def available(self) -> bool:
        """Có endpoint để gọi không. Cache vẫn dùng được kể cả khi không có."""
        return bool(self.endpoint)

    def stats(self) -> dict:
        return {"endpoint": self.endpoint or None,
                "identity": dict(self.identity.__dict__),
                "identity_key": self.identity.key(),
                "n_call": self.n_call, "n_cache_hit": self.n_hit,
                "n_loi": self.n_loi, "n_cache_entry": len(self._cache),
                "cache_path": str(self._cache_path.relative_to(ROOT))}

    # ── gọi ────────────────────────────────────────────────────────────────
    def chat(self, prompt: str) -> str | None:
        """→ nội dung trả lời, hoặc None nếu không gọi được.

        Thứ tự: cache → endpoint → None. KHÔNG bao giờ ném ra ngoài; tầng trên
        phải luôn có đường lui tất định.
        """
        k = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
        if k in self._cache:
            self.n_hit += 1
            return self._cache[k]
        if not self.available:
            return None

        body = {
            "model": self.identity.model_id,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": self.identity.temperature,
            "top_p": self.identity.top_p,
            "max_tokens": self.identity.max_tokens,
            "seed": self.identity.seed,
        }
        try:
            import requests
            self.n_call += 1
            r = requests.post(f"{self.endpoint.rstrip('/')}/v1/chat/completions",
                              json=body, timeout=self.timeout)
            r.raise_for_status()
            out = r.json()["choices"][0]["message"]["content"]
        except Exception:                                    # noqa: BLE001
            self.n_loi += 1
            return None

        self._cache[k] = out
        with self._cache_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps({"k": k, "v": out, "t": time.time()},
                               ensure_ascii=False) + "\n")
        return out

    # ── nạp cache thủ công — dùng cho test fixture ─────────────────────────
    def nap_fixture(self, prompt: str, tra_loi: str) -> None:
        self._cache[hashlib.sha256(prompt.encode("utf-8")).hexdigest()] = tra_loi


def tu_config(path: Path | None = None) -> LLMClient:
    """Đọc `configs/answer_v2/llm_v1.yaml`. Thiếu file ⇒ client offline."""
    p = path or (ROOT / "configs/answer_v2/llm_v1.yaml")
    d: dict = {}
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("#") or ":" not in s:
                continue
            k, _, v = s.partition(":")
            d[k.strip()] = v.strip().strip('"').strip("'")
    ident = LLMIdentity(
        model_id=d.get("model_id", "Qwen/Qwen2.5-14B-Instruct"),
        revision=d.get("revision", "unknown"),
        quantization=d.get("quantization", "none"),
        runtime=d.get("runtime", "openai-compatible"),
        temperature=float(d.get("temperature", 0.0)),
        top_p=float(d.get("top_p", 1.0)),
        seed=int(d.get("seed", 0)),
        max_tokens=int(d.get("max_tokens", 16)),
    )
    return LLMClient(endpoint=d.get("endpoint") or None, identity=ident)
