#!/usr/bin/env python3
"""QuestionPlan parser v1 — D1 của plan 124 (bản 122.1), rule-based, không LLM.

Sinh:
    data/curated/evaluation/legacy/question_plans_1012.jsonl   một QuestionPlan/QID (contract 121 §3.2 rút gọn)
    reports/question_plan_v1_report.json   distribution PROVISIONAL + agreement vs `lop`
                                            + entity/year check trên gold-45
                                            + bảng chéo intent × n_evidence(C0)

Trạng thái đo (125 §5-D1): intent accuracy = NOT_YET_MEASURED (chưa có Gold
intent người gán); agreement với `lop` cũ chỉ là ĐỐI CHIẾU HAI HEURISTIC,
không phải accuracy. Entity/year check trên gold-45 là deterministic check
thật (gold-45 có tickers/years người phân xử).

Nguyên tắc v1: phân biệt TOÁN TỬ NGÔN NGỮ với TÊN METRIC. "Lỗ chênh lệch tỷ
giá là bao nhiêu" = lookup (chênh lệch nằm trong tên metric), khác "chênh lệch
giữa A và B" = difference.
"""
from __future__ import annotations

import json
import re
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# ── slot: ticker ────────────────────────────────────────────────────────────
NOT_TICKER = {
    "CTCP", "TMCP", "TNHH", "MTV", "VND", "USD", "EUR", "JPY", "CNY", "GBP",
    "CFO", "LNST", "ROE", "ROA", "EPS", "EBIT", "EBITDA", "GDP", "OCF", "FCF",
    "VAS", "BCTC", "III", "VII", "VIII", "KQKD", "TSCD", "TSCĐ", "TNDN",
    "GTGT", "BOT", "BT", "PPP", "ETF", "HNX", "HOSE", "UPCOM", "OTC", "CP",
    "DN", "XNK", "QLDA",
}
RE_TICKER = re.compile(r"\b([A-Z][A-Z0-9]{2,3})\b")
RE_YEAR = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")
RE_RANGE = re.compile(r"(19[89]\d|20[0-4]\d)\s*[-–—]\s*(19[89]\d|20[0-4]\d)")

sys.path.insert(0, str(ROOT / "src"))
try:  # alias tên công ty → ticker (dùng chung tài nguyên retrieval, read-only)
    from text2pandas.pipelines.retrieval.alias_store import load_aliases
    _ALIASES: dict[str, list[str]] = load_aliases("a6")
except Exception:  # noqa: BLE001 — packet review có thể thiếu attested file
    try:
        _ALIASES = load_aliases(False)
    except Exception:  # noqa: BLE001
        _ALIASES = {}
def _name_variants(a: str) -> list[str]:
    """Biến thể tên: bỏ tiền tố pháp nhân (CTCP/Công ty CP/Tập đoàn…) để khớp
    cách viết khác nhau. 'CTCP Tập đoàn F.I.T' → thêm 'tập đoàn f.i.t'."""
    base = a.lower()
    outs = [base]
    stripped = re.sub(r"^(ctcp|công ty cp|công ty cổ phần|tổng công ty( cổ phần)?|tập đoàn|ngân hàng tmcp)\s+", "", base)
    if stripped != base and len(stripped) >= 5:
        outs.append(stripped)
    return outs


_NAME2TICKER: list[tuple[str, str]] = sorted(
    {(v, t) for t, names in _ALIASES.items() for a in names
     if len(a) >= 6 and not a.isupper() for v in _name_variants(a)},
    key=lambda x: -len(x[0]))


def extract_tickers(q: str) -> list[str]:
    out: list[str] = []
    for m in RE_TICKER.finditer(q):
        t = m.group(1)
        if t in NOT_TICKER or t in out:
            continue
        if sum(c.isdigit() for c in t) > 1:  # cần ≥2 chữ cái
            continue
        out.append(t)
    ql = q.lower()  # bổ sung: mọi tên công ty khớp trong câu (dài nhất trước)
    for name, tk in _NAME2TICKER:
        if tk not in out and name in ql:
            out.append(tk)
    return out


def extract_years(q: str) -> tuple[list[int], bool]:
    rng = RE_RANGE.search(q)
    years = sorted({int(y) for y in RE_YEAR.findall(q)})
    return years, bool(rng)


def extract_basis(q: str) -> str:
    ql = q.lower()
    if "công ty mẹ" in ql or "riêng lẻ" in ql or "dữ liệu công ty mẹ" in ql:
        return "separate"
    if "hợp nhất" in ql:
        return "consolidated"
    return "unknown"


def extract_unit(q: str) -> str:
    ql = q.lower()
    for pat, u in [
        (r"trăm tỷ", "hundred_billion_VND"), (r"nghìn tỷ", "thousand_billion_VND"),
        (r"tỷ đồng", "billion_VND"), (r"triệu đồng", "million_VND"),
        (r"nghìn đồng", "thousand_VND"),
        (r"phần trăm|bao nhiêu %|\(%\)|là bao nhiêu %", "percent"),
        (r"bao nhiêu lần", "ratio_x"), (r"cổ phiếu", "shares"),
        (r"\bđồng\b", "VND"),
    ]:
        if re.search(pat, ql):
            return u
    return "unknown"


# ── intent rules (thứ tự = ưu tiên) ────────────────────────────────────────
def classify_intent(q: str, tickers: list[str], years: list[int],
                    has_range: bool) -> tuple[str, list[str]]:
    ql = q.lower()
    flags: list[str] = []
    multi_entity = len(tickers) >= 3
    if multi_entity:
        flags.append("multi_entity")
    if len(years) >= 3:
        flags.append("multi_year")
    if has_range:
        flags.append("period_range")
    if re.search(r"trung vị", ql):
        flags.append("median")
    screen = bool(re.search(r"(đồng thời|thỏa|duy trì|có .* dương|có .* âm|lớn hơn|nhỏ hơn|cao hơn|thấp hơn).*(trong nhóm|trong các|nhóm mã|bao gồm)", ql)) or \
        bool(re.search(r"(trong nhóm|nhóm mã|bao gồm các công ty).*(đồng thời|duy trì|dương|âm)", ql))
    if screen:
        flags.append("screen_filter")

    if re.search(r"vào năm nào|năm nào trong|đạt mức .* vào năm nào|cao nhất vào năm|thấp nhất vào năm", ql):
        return "argmax_year", flags
    if re.search(r"có bao nhiêu (doanh nghiệp|công ty|mã|ngân hàng)", ql):
        return "count", flags
    if re.search(r"tính tổng|tổng .* (trong|cho) các năm", ql):
        return "sum", flags
    if re.search(r"(phần trăm|%) tăng trưởng|tăng trưởng .* (bao nhiêu|là bao nhiêu) (%|phần trăm)|tăng/giảm bao nhiêu phần trăm|(tăng|giảm) bao nhiêu (%|phần trăm)|từ năm \d{4} (sang|đến) năm \d{4}", ql):
        return "percentage_change", flags
    if re.search(r"bình quân|trung bình", ql) and not re.search(r"bình quân gia quyền của riêng", ql):
        return "average", flags
    # difference: toán tử so sánh hai vế, không phải tên metric
    if re.search(r"chênh lệch (giữa|về)|nhiều hơn .* bao nhiêu|ít hơn .* bao nhiêu|cao hơn .* bao nhiêu|thấp hơn .* bao nhiêu|so với .* (chênh|hơn kém)", ql):
        return "difference", flags
    if re.search(r"cao nhất|thấp nhất|lớn nhất|nhỏ nhất|cực đại|cực tiểu", ql):
        return "max_min", flags
    if re.search(r"chiếm (bao nhiêu|tỷ trọng)|tỷ trọng .* (là bao nhiêu|bao nhiêu)|trên .* là bao nhiêu lần|gấp bao nhiêu lần", ql):
        return "ratio", flags
    if re.search(r"^tỷ lệ|tỷ lệ .* là bao nhiêu|hệ số .* là bao nhiêu", ql):
        # metric tên "tỷ lệ/hệ số" hỏi kiểu lookup — đánh dấu mơ hồ
        flags.append("ratio_metric_lookup")
        return "lookup", flags
    if screen or (multi_entity and len(years) >= 1 and re.search(r"nhóm|các công ty|bao gồm", ql)):
        return "multi_entity_aggregate", flags
    return "lookup", flags


def build_plans() -> list[dict]:
    rows = [json.loads(l) for l in
            (ROOT / "data/curated/dev-legacy/so_hoc/phan_loai.jsonl").open(encoding="utf-8")]
    plans = []
    for r in rows:
        q = r["question"]
        tickers = extract_tickers(q)
        years, has_range = extract_years(q)
        intent, flags = classify_intent(q, tickers, years, has_range)
        plans.append({
            "qid": r["id"], "question": q,
            "entities": tickers, "years": years,
            "basis": extract_basis(q), "output_unit": extract_unit(q),
            "intent_v1": intent, "flags": flags,
            "lop_legacy": r.get("lop"), "don_vi_hoi_legacy": r.get("don_vi_hoi"),
            "confidence": 0.5, "ambiguities": ["ratio_metric_lookup"] if "ratio_metric_lookup" in flags else [],
        })
    return plans


def main() -> int:
    plans = build_plans()
    (ROOT / "evaluation").mkdir(exist_ok=True)
    with (ROOT / "data/curated/evaluation/legacy/question_plans_1012.jsonl").open("w", encoding="utf-8") as f:
        for p in plans:
            f.write(json.dumps(p, ensure_ascii=False) + "\n")

    dist = Counter(p["intent_v1"] for p in plans)
    agree = sum(1 for p in plans if p["intent_v1"] == p["lop_legacy"])
    conf = defaultdict(Counter)
    for p in plans:
        conf[p["lop_legacy"]][p["intent_v1"]] += 1

    # entity/year deterministic check trên gold-45
    gold = [json.loads(l) for l in
            (ROOT / "data/curated/dev-legacy/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8")]
    gold = [g for g in gold if not g.get("_meta")]
    by_qid = {p["qid"]: p for p in plans}
    ent_ok = yr_ok = basis_ok = n45 = 0
    ent_fail = []
    for g in gold:
        p = by_qid.get(g["qid"])
        if not p:
            continue
        n45 += 1
        if set(g.get("tickers") or []) <= set(p["entities"]):
            ent_ok += 1
        else:
            ent_fail.append({"qid": g["qid"], "gold": g.get("tickers"), "parsed": p["entities"]})
        if set(g.get("years") or []) <= set(p["years"]):
            yr_ok += 1
        if g.get("basis") in (p["basis"], None) or p["basis"] == "unknown":
            basis_ok += 1

    # bảng chéo intent × n_evidence của C0
    zp = ROOT / "artifacts/submissions/legacy/submission_P0I.zip"
    with zipfile.ZipFile(zp) as z:
        sub = {r["id"]: len(r.get("evidence") or [])
               for r in json.loads(z.read("submission.json"))}
    cross = defaultdict(Counter)
    for p in plans:
        ne = sub.get(p["qid"], 0)
        cross[p["intent_v1"]][f"ev{min(ne,3)}{'+' if ne>=3 else ''}"] += 1

    report = {
        "status": "PROVISIONAL — intent accuracy NOT_YET_MEASURED (chưa có Gold intent)",
        "machine": "build", "date": "2026-08-20",
        "n": len(plans),
        "intent_distribution_v1": dict(dist.most_common()),
        "agreement_with_lop_legacy": {"n_agree": agree, "rate": round(agree / len(plans), 4),
                                       "note": "đối chiếu 2 heuristic, KHÔNG phải accuracy"},
        "confusion_lop_vs_v1": {k: dict(v.most_common()) for k, v in conf.items()},
        "gold45_deterministic_checks": {
            "n": n45,
            "entity_superset_ok": ent_ok, "entity_rate": round(ent_ok / max(n45, 1), 4),
            "year_superset_ok": yr_ok, "year_rate": round(yr_ok / max(n45, 1), 4),
            "basis_compatible": basis_ok,
            "entity_failures": ent_fail[:10],
        },
        "cross_intent_x_n_evidence_C0": {k: dict(v) for k, v in cross.items()},
        "command": " ".join(sys.argv),
    }
    (ROOT / "reports/question_plan_v1_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in
                      ["n", "intent_distribution_v1", "agreement_with_lop_legacy",
                       "gold45_deterministic_checks"]}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
