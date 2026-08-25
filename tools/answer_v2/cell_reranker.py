#!/usr/bin/env python3
"""Cell reranker v2 — LLM CHỌN Ô qua JSON contract. Không sinh số, không parse số trần.

THAY ĐỔI SO VỚI v1 (doc 159 §6.5 yêu cầu)
v1 nhận câu trả lời tự do rồi `re.search(r"-?\\d+")` lấy số nguyên đầu tiên. Ba
lỗ hổng của cách đó, và đều là lỗi IM LẶNG:

  1. `"3"` trong câu *"tôi chọn dòng 3 vì năm 2023"* và trong *"2023"* không phân
     biệt được — regex bắt số đầu tiên, có thể là năm chứ không phải chỉ số.
  2. Chỉ số là **vị trí trình bày**, nên cùng một ô ở hai thứ tự khác nhau mang
     hai "tên" khác nhau ⇒ không đối chiếu được A/B/C, không cache được ổn định.
  3. Không có đường ABSTAIN. Model buộc phải chọn kể cả khi không ô nào đúng.

v2 dùng **stable candidate ID** — băm của NỘI DUNG ô, độc lập hoàn toàn với vị
trí — và schema JSON bắt buộc:

    {"selected_candidate_id": "<id> | null", "confidence": 0.0,
     "reason_codes": ["<enum>"]}

`selected_candidate_id` phải nằm trong whitelist đúng của lượt gọi đó. Ngoài
whitelist ⇒ **không đoán**, rơi về scorer tất định và ghi mã lỗi.

CHE SỐ (numeric masking, FinQA / doc 144 §11.4)
Giá trị ô **không** vào prompt, gold ID cũng **không**. Model chọn theo nhãn,
đường dẫn, cột, kỳ, phạm vi — đúng những thứ con người dùng. Có test khoá.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field

from llm_client import LLMClient

K_MAC_DINH = 12

# Enum ĐÓNG. Model trả mã ngoài danh sách ⇒ schema invalid, không cố diễn giải.
REASON_CODES = (
    "EXACT_METRIC_MATCH", "PERIOD_MATCH", "SCOPE_MATCH", "AGGREGATE_ROW",
    "DETAIL_ROW_REQUESTED", "ONLY_PLAUSIBLE_CANDIDATE",
    "NO_CANDIDATE_MATCHES", "AMBIGUOUS_BETWEEN_CANDIDATES",
)

PROMPT = """Bạn là trợ lý phân tích báo cáo tài chính Việt Nam.

CÂU HỎI:
{question}

Dưới đây là {n} dòng ứng viên trích từ báo cáo tài chính. Mỗi dòng có một mã
định danh, nhãn chỉ tiêu, đường dẫn dòng, nhãn cột (kỳ), loại báo cáo và phạm vi.

{candidates}

Chọn ĐÚNG MỘT dòng chứa số liệu mà câu hỏi yêu cầu.

Quy tắc:
- Ưu tiên đúng CHỈ TIÊU câu hỏi hỏi, không phải chỉ tiêu gần giống.
- Ưu tiên đúng KỲ. "Số đầu năm" của báo cáo năm N là số dư cuối năm N-1.
- Dòng tổng hợp thường đúng hơn dòng chi tiết, trừ khi câu hỏi nêu rõ chi tiết.
- Câu hỏi về hợp nhất thì tránh dòng của riêng công ty mẹ, và ngược lại.
- Nếu KHÔNG dòng nào khớp, trả selected_candidate_id = null.

Trả lời DUY NHẤT một đối tượng JSON, không kèm giải thích, không kèm markdown:

{{"selected_candidate_id": "<mã đã cho ở trên hoặc null>",
  "confidence": <số thực 0..1>,
  "reason_codes": ["<một hoặc nhiều mã trong danh sách>"]}}

Danh sách mã lý do cho phép: {reasons}"""


def prompt_hash() -> str:
    return hashlib.sha256(PROMPT.encode("utf-8")).hexdigest()[:16]


def schema_hash() -> str:
    return hashlib.sha256(
        json.dumps({"fields": ["selected_candidate_id", "confidence", "reason_codes"],
                    "reason_codes": list(REASON_CODES)},
                   sort_keys=True).encode()).hexdigest()[:16]


# ── stable candidate ID ────────────────────────────────────────────────────

def candidate_id(c: dict) -> str:
    """Băm NỘI DUNG ô → mã ổn định, độc lập vị trí trình bày.

    Dùng `observation_uid` khi có (khoá thật của A6); nếu không thì băm bộ
    trường định danh. KHÔNG bao giờ dùng chỉ số vị trí — đó chính là lỗi của v1.
    """
    ouid = c.get("observation_uid")
    base = str(ouid) if ouid else "|".join(str(c.get(k) or "") for k in (
        "evidence_ref", "row_path", "col_path", "metric_label"))
    return "c_" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:12]


def _cat(s: str | None, n: int) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())[:n]


def dung_prompt(question: str, cands: list[dict]) -> str:
    """Dựng prompt. KHÔNG đưa `value` và KHÔNG đưa gold ID vào."""
    dong = []
    for c in cands:
        dong.append(
            f"- mã: {candidate_id(c)}\n"
            f"  chỉ tiêu: {_cat(c.get('metric_label'), 90)}\n"
            f"  đường dẫn: {_cat(c.get('row_path'), 90)}\n"
            f"  cột: {_cat(c.get('col_path'), 70)}\n"
            f"  loại báo cáo: {c.get('statement_type') or '?'}"
            f" · kỳ: {c.get('period_end') or '?'}"
            f" · phạm vi: {_cat(c.get('evidence_ref'), 60)}")
    return PROMPT.format(question=_cat(question, 600), n=len(cands),
                         candidates="\n".join(dong),
                         reasons=", ".join(REASON_CODES))


# ── parse + validate schema ────────────────────────────────────────────────

def doc_json(tra_loi: str | None, whitelist: set[str]) -> tuple[dict | None, str]:
    """→ (bản ghi hợp lệ, mã lỗi). Mã rỗng = hợp lệ.

    Không "sửa" câu trả lời hỏng. Một output sai schema nghĩa là model không làm
    đúng việc được giao; đoán ý nó là tự tạo thêm một tầng lỗi không kiểm được.
    """
    if not tra_loi or not tra_loi.strip():
        return None, "EMPTY_RESPONSE"
    s = tra_loi.strip()
    # Gỡ rào markdown nếu model bọc ```json ... ```
    m = re.search(r"```(?:json)?\s*(.+?)\s*```", s, re.S)
    if m:
        s = m.group(1).strip()
    # Lấy object JSON đầu tiên — model có thể nói thêm trước/sau.
    i, j = s.find("{"), s.rfind("}")
    if i < 0 or j <= i:
        return None, "NOT_JSON"
    try:
        d = json.loads(s[i:j + 1])
    except json.JSONDecodeError:
        return None, "INVALID_JSON"
    if not isinstance(d, dict):
        return None, "NOT_JSON_OBJECT"

    if "selected_candidate_id" not in d:
        return None, "MISSING_FIELD_selected_candidate_id"
    sid = d["selected_candidate_id"]
    if sid is not None and not isinstance(sid, str):
        return None, "BAD_TYPE_selected_candidate_id"
    if sid is not None and sid not in whitelist:
        return None, "ID_NOT_IN_WHITELIST"

    conf = d.get("confidence", 0.0)
    if not isinstance(conf, (int, float)) or not (0.0 <= float(conf) <= 1.0):
        return None, "BAD_CONFIDENCE"

    rc = d.get("reason_codes", [])
    if not isinstance(rc, list) or any(not isinstance(x, str) for x in rc):
        return None, "BAD_REASON_CODES"
    if any(x not in REASON_CODES for x in rc):
        return None, "REASON_CODE_NOT_IN_ENUM"

    return {"selected_candidate_id": sid, "confidence": float(conf),
            "reason_codes": rc}, ""


# ── thống kê ───────────────────────────────────────────────────────────────

@dataclass
class RerankStats:
    """Bộ đếm theo đúng §6.8 — mọi tỉ lệ phải nói rõ mẫu số nào."""

    n_slot: int = 0
    attempted: int = 0
    valid_schema: int = 0
    invalid_schema: int = 0
    id_not_in_whitelist: int = 0
    endpoint_error: int = 0
    timeout: int = 0
    abstain: int = 0
    fallback: int = 0
    n_doi_top1: int = 0
    ly_do_fallback: dict = field(default_factory=dict)
    vi_tri_chon: dict = field(default_factory=dict)
    raw_log: list = field(default_factory=list)

    def ghi(self, ly_do: str) -> None:
        self.ly_do_fallback[ly_do] = self.ly_do_fallback.get(ly_do, 0) + 1

    def tom_tat(self) -> dict:
        return {
            "n_slot": self.n_slot, "attempted": self.attempted,
            "valid_schema": self.valid_schema, "invalid_schema": self.invalid_schema,
            "id_not_in_whitelist": self.id_not_in_whitelist,
            "endpoint_error": self.endpoint_error, "timeout": self.timeout,
            "abstain": self.abstain, "fallback": self.fallback,
            "n_doi_top1": self.n_doi_top1,
            "ly_do_fallback": self.ly_do_fallback,
            "phan_bo_vi_tri_chon": dict(sorted(self.vi_tri_chon.items())),
        }


# ── thứ tự trình bày ───────────────────────────────────────────────────────

def hoan_vi(n: int, seed_text: str) -> list[int]:
    """Hoán vị TẤT ĐỊNH theo băm khoá — tái lập được từ trace, không cần lưu."""
    h = hashlib.sha256(seed_text.encode("utf-8")).digest()
    idx = list(range(n))
    b, bi = h, 0
    for i in range(n - 1, 0, -1):
        if bi >= len(b):
            b, bi = hashlib.sha256(b).digest(), 0
        j = b[bi] % (i + 1)
        bi += 1
        idx[i], idx[j] = idx[j], idx[i]
    return idx


def thu_tu(cands: list[dict], trinh_bay: str, seed_text: str) -> list[int]:
    """A = thứ tự scorer · B = hoán vị tất định · C = đảo ngược."""
    n = len(cands)
    if trinh_bay in ("B", "hoan_vi"):
        return hoan_vi(n, seed_text)
    if trinh_bay in ("C", "dao"):
        return list(range(n))[::-1]
    return list(range(n))


# ── điểm vào chính ─────────────────────────────────────────────────────────

def rerank(question: str, ranked: list[dict], client: LLMClient,
           stats: RerankStats, k: int = K_MAC_DINH,
           trinh_bay: str = "A", seed_text: str = "",
           luu_raw: bool = True) -> list[dict]:
    """Đưa ô model chọn lên đầu. MỌI trường hợp hỏng → giữ nguyên thứ tự scorer.

    Hợp đồng: trả về **cùng phần tử**, chỉ đổi thứ tự. Nhờ vậy binder/evidence/
    renderer/verifier không cần biết có LLM.
    """
    stats.n_slot += 1
    if len(ranked) < 2:
        stats.fallback += 1
        stats.ghi("IT_HON_2_UNG_VIEN")
        return ranked

    cands = ranked[:k]
    vi = thu_tu(cands, trinh_bay, seed_text or question)
    bay = [cands[j] for j in vi]
    whitelist = {candidate_id(c) for c in bay}
    id2cell = {candidate_id(c): c for c in bay}

    p = dung_prompt(question, bay)
    stats.attempted += 1
    tra_loi = client.chat(p)

    if luu_raw:
        stats.raw_log.append({
            "seed": seed_text, "trinh_bay": trinh_bay,
            "thu_tu_id": [candidate_id(c) for c in bay],
            "raw": (tra_loi[:400] if isinstance(tra_loi, str) else None)})

    if tra_loi is None:
        stats.endpoint_error += 1
        stats.fallback += 1
        stats.ghi("ENDPOINT_ERROR")
        return ranked

    rec, err = doc_json(tra_loi, whitelist)
    if err:
        if err == "ID_NOT_IN_WHITELIST":
            stats.id_not_in_whitelist += 1
        else:
            stats.invalid_schema += 1
        stats.fallback += 1
        stats.ghi(err)
        return ranked

    stats.valid_schema += 1
    sid = rec["selected_candidate_id"]
    if sid is None:
        # ABSTAIN hợp lệ — model nói "không ô nào khớp". Dùng scorer tất định.
        stats.abstain += 1
        stats.fallback += 1
        stats.ghi("ABSTAIN")
        return ranked

    chon = id2cell[sid]
    stats.vi_tri_chon[vi.index(cands.index(chon))] = \
        stats.vi_tri_chon.get(vi.index(cands.index(chon)), 0) + 1
    if chon is not ranked[0]:
        stats.n_doi_top1 += 1
    return [chon] + [c for c in ranked if c is not chon]
