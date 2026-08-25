#!/usr/bin/env python3
"""Ranker FactCandidate — tách khỏi `tools/fact_candidates_v1.py` để ABLATE được.

VÌ SAO TỆP NÀY TỒN TẠI
----------------------
`fact_candidates_v1.py` gộp SQL + scoring + đo vào một hàm và được sửa TẠI CHỖ
qua ba vòng V1.0 → V1.1 → V1.2. Hệ quả: hai con số 55,2% và 70,1% trong doc 126
**không tái tạo được** — code sinh ra chúng đã bị ghi đè. Review 127 §3-D3 đòi
per-slot evidence; không tách biến thể thì không có evidence.

Ở đây mỗi biến thể là một BỘ CỜ, không phải một phiên bản file:

    V1.0  = overlap thô
    V1.1  = V1.0 + idf_pool + exact_phrase
    V1.2  = V1.1 + quota (round-robin entity × năm)

`V1.2` phải tái hiện ĐÚNG số đã báo (@1 20,7 / @3 39,1 / @10 67,8 / @20 75,9)
— đó là bài kiểm tra tính đúng của bản tách này. V1.0/V1.1 tái hiện ở đây là
**RE-DERIVED**, không phải bản đã chạy 20/08; phải ghi nhãn khi trích số.

Ngoài ra tệp này trả về POOL ĐẦY ĐỦ chứ không chỉ top-k, để phân biệt được ba
trạng thái mà báo cáo cũ gộp làm một:

    pool_sql        ô có trong kết quả SQL (đúng ticker/năm/basis, có giá trị)
    pool_scorable   ô có ÍT NHẤT một token chung với câu hỏi ⇒ mới có thể có điểm
    top_k           ô lọt vào k ứng viên cuối

"Pool recall 100%" của doc 126 là recall trên `pool_sql`. Nếu một slot nằm
trong `pool_sql` mà KHÔNG nằm trong `pool_scorable` thì nó không phải lỗi xếp
hạng — hàm điểm mù với nó, và không có cách chỉnh trọng số nào cứu được.
"""
from __future__ import annotations

import math
import re
import sqlite3
import unicodedata
from dataclasses import dataclass, field

# Giữ NGUYÊN stoplist của fact_candidates_v1.py — đổi stoplist là đổi hành vi,
# và ablation chỉ hợp lệ khi đúng một thứ đổi mỗi lần.
STOP = set("của công ty mẹ ctcp tmcp cổ phần năm cuối đầu là bao nhiêu triệu tỷ đồng "
           "trong các và đến ngày tháng theo với tại nhóm mã tính bằng đơn vị trên "
           "ghi nhận khoản mục vào bao gồm".split())


def toks(s: str) -> set[str]:
    s = unicodedata.normalize("NFC", s.lower())
    return {t for t in re.findall(r"[a-zà-ỹđ0-9]+", s) if len(t) >= 2 and t not in STOP}


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFC", (s or "").lower())).strip()


@dataclass(frozen=True)
class Flags:
    """Một cờ = một thay đổi hành vi. Tên cờ đi thẳng vào report ablation."""
    idf_pool: bool = False       # V1.1 — IDF tính trong pool của chính QID
    exact_phrase: bool = False   # V1.1 — câu chứa nguyên văn nhãn metric (+3.0)
    quota: bool = False          # V1.2 — round-robin entity × năm
    col_year: bool = True        # cột đúng năm hỏi (+0.6) — có từ V1.0
    doc_year: bool = True        # file đúng năm (+0.3)
    ready: bool = True           # execution_ready (+0.3)

    # legacy_order=True tái hiện ĐÚNG hành vi bản 20/08: không ORDER BY, tie giữ
    # thứ tự SQLite trả về. Cần cho việc CHỨNG MINH bản tách này tương đương.
    # legacy_order=False là hành vi ĐÚNG cần dùng từ D4: deterministic giữa máy.
    legacy_order: bool = True

    @property
    def name(self) -> str:
        on = [f for f in ("idf_pool", "exact_phrase", "quota") if getattr(self, f)]
        return ("+".join(on) or "overlap_only") + ("" if self.legacy_order else "+det_order")


V1_0 = Flags()
V1_1 = Flags(idf_pool=True, exact_phrase=True)
V1_2 = Flags(idf_pool=True, exact_phrase=True, quota=True)
VARIANTS = {"V1.0": V1_0, "V1.1": V1_1, "V1.2": V1_2}

SQL = """
    SELECT o.observation_uid, o.evidence_ref, o.table_uid, o.ticker, o.doc_year,
           o.metric_label_clean, o.row_path_text, o.col_path_text,
           o.value_decimal_text, o.value_kind, o.statement_type,
           COALESCE(r.execution_ready, 0) ready, o.scale_exponent, o.unit_kind,
           o.is_negative, o.period_end, o.is_restated, o.confidence
    FROM observations o
    JOIN documents d ON d.directory_doc_id = o.directory_doc_id
    LEFT JOIN observation_readiness r ON r.observation_uid = o.observation_uid
    WHERE o.ticker IN ({e}) AND o.doc_year IN ({y})
      AND o.value_decimal_text IS NOT NULL {b}
    {o}
"""
# `{o}` = "" (legacy, giống bản cũ) hoặc "ORDER BY o.observation_uid".
# Thứ tự SQLite trả về KHÔNG có bảo đảm, và `list.sort` là stable ⇒ bản cũ để
# tie phụ thuộc thứ tự quét bảng. Hai máy khác nhau có thể ra hai top-20 khác
# nhau ở các ô cùng điểm mà không ai biết. Đây là lỗi tiềm ẩn của V1, đã đo
# ảnh hưởng trong reports/fact_slot_evidence_v1.json (mục `tiebreak_effect`).


def _cell(r) -> dict:
    (uid, ref, tuid, tk, dy, lab, rp, cp, val, vk, st, ready,
     scale, unit, isneg, pend, restated, conf) = r
    return {"observation_uid": uid, "evidence_ref": ref, "table_uid": tuid,
            "ticker": tk, "doc_year": dy, "metric_label": lab,
            "row_path": rp or "", "col_path": cp or "", "value": val,
            "value_kind": vk, "statement_type": st, "ready": ready,
            "scale_exponent": scale, "unit_kind": unit, "is_negative": isneg,
            "period_end": pend, "is_restated": restated, "confidence": conf}


def fetch_pool(con: sqlite3.Connection, plan: dict,
               legacy_order: bool = True) -> list[dict]:
    """POOL SQL — trước mọi scoring. Đây là mẫu số của 'pool recall'."""
    ents = plan.get("entities") or []
    years = plan.get("years") or []
    if not ents or not years:
        return []
    year_pool = sorted({str(y) for y in years} | {str(y + 1) for y in years})
    basis = plan.get("basis", "unknown")
    bsql = " AND d.basis = ?" if basis in ("separate", "consolidated") else ""
    q = SQL.format(e=",".join("?" * len(ents)), y=",".join("?" * len(year_pool)),
                   b=bsql, o="" if legacy_order else "ORDER BY o.observation_uid")
    params = [*ents, *year_pool] + ([basis] if bsql else [])
    return [_cell(r) for r in con.execute(q, params)]


def score_pool(pool: list[dict], plan: dict, fl: Flags) -> list[dict]:
    """Gắn `score` + `scorable`. Trả về BẢN SAO đã sắp xếp giảm dần."""
    qt = toks(plan["question"])
    qnorm = norm(plan["question"])
    tgt_years = {str(y) for y in (plan.get("years") or [])}

    # GIỮ NGUYÊN cách ghép của bản gốc: nhãn + row_path nối bằng dấu cách rồi
    # mới tách token. Tách riêng hai trường rồi hợp tập cho kết quả KHÁC ở các
    # token nằm vắt qua ranh giới — không đổi ở đây vì đang ablate thứ khác.
    lts = [toks((c["metric_label"] or "") + " " + c["row_path"]) for c in pool]

    df: dict[str, int] = {}
    for lt in lts:
        for t in lt:
            df[t] = df.get(t, 0) + 1
    n_pool = max(len(pool), 1)

    out = []
    for c, lt in zip(pool, lts):
        inter = qt & lt
        c = dict(c)
        c["n_token_overlap"] = len(inter)
        c["scorable"] = bool(lt and inter)
        if not c["scorable"]:
            c["score"] = None
            out.append(c)
            continue
        if fl.idf_pool:
            s = sum(math.log(1 + n_pool / df[t]) for t in inter) / (len(lt) ** 0.5)
        else:
            s = len(inter) / (len(lt) ** 0.5)          # V1.0 overlap thô
        if fl.exact_phrase:
            labn = norm(c["metric_label"])
            if len(labn) >= 8 and labn in qnorm:
                s += 3.0
                c["exact_phrase_hit"] = True
        if fl.col_year and any(y in c["col_path"] for y in tgt_years):
            s += 0.6
        if fl.doc_year and str(c["doc_year"]) in tgt_years:
            s += 0.3
        if fl.ready:
            s += 0.3 * c["ready"]
        c["score"] = round(s, 6)
        out.append(c)

    scored = [c for c in out if c["score"] is not None]
    if fl.legacy_order:
        scored.sort(key=lambda c: -c["score"])                  # stable, tie = thứ tự SQL
    else:
        scored.sort(key=lambda c: (-c["score"], str(c["observation_uid"])))
    return scored


def apply_quota(scored: list[dict], plan: dict, k: int) -> list[dict]:
    """V1.2 — round-robin (entity × năm hỏi). Giữ nguyên logic bản gốc."""
    ents = plan.get("entities") or []
    tgt_years = {str(y) for y in (plan.get("years") or [])}
    if not (len(tgt_years) > 1 or len(ents) > 1):
        return scored[:k]

    def served(c: dict):
        for y in tgt_years:
            if y in c["col_path"]:
                return y
        dy = str(c["doc_year"])
        if dy in tgt_years:
            return dy
        if str(int(dy) - 1) in tgt_years:
            return str(int(dy) - 1)
        return None

    buckets: dict[tuple, list] = {}
    for c in scored:
        buckets.setdefault((c["ticker"], served(c)), []).append(c)
    cells = sorted({(e, y) for e in ents for y in (tgt_years or {None})})
    idx = {c: 0 for c in cells}
    out: list[dict] = []
    seen: set = set()
    while len(out) < k:
        progressed = False
        for cell in cells:
            b = buckets.get(cell, [])
            while idx[cell] < len(b) and b[idx[cell]]["observation_uid"] in seen:
                idx[cell] += 1
            if idx[cell] < len(b) and len(out) < k:
                c = b[idx[cell]]
                out.append(c); seen.add(c["observation_uid"]); idx[cell] += 1
                progressed = True
        if not progressed:
            break
    for c in scored:
        if len(out) >= k:
            break
        if c["observation_uid"] not in seen:
            out.append(c); seen.add(c["observation_uid"])
    return out


def rank(con: sqlite3.Connection, plan: dict, k: int = 20,
         fl: Flags = V1_2) -> tuple[list[dict], list[dict]]:
    """→ (top_k, pool_sql). Trả cả pool để đo được mẫu số."""
    pool = fetch_pool(con, plan, legacy_order=fl.legacy_order)
    scored = score_pool(pool, plan, fl)
    top = apply_quota(scored, plan, k) if fl.quota else scored[:k]
    return top, pool
