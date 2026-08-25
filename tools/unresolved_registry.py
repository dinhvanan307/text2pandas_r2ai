#!/usr/bin/env python3
"""RC-18 · sổ đăng ký CÁC CA CHƯA GIẢI QUYẾT.

Mục đích: không ca nào được biến mất trong im lặng. Mỗi ca mà pipeline không
đưa được vào tập dùng được phải nằm ở đây, có phân loại, có lý do, có đường
dẫn bằng chứng.

Phân loại KHÔNG do công cụ tự nghĩ ra — nó đọc `consequence` trong
`configs/rule_inventory_v1.yaml`. Rule nào có consequence thuộc
{build_failure, blocking, blocking_until_classified, non_candidate} thì ca của
nó là CHƯA GIẢI QUYẾT. {warning, warning_conditional} là đã gắn cờ nhưng vẫn
dùng được — không tính vào đây.

Hai cái bẫy đếm mà công cụ này bắt buộc phải khai báo:

1. `quality_issues` trong build DB bị **cắt mẫu ở 5.000 ca mỗi rule**. Đếm
   `COUNT(*)` trên đó cho ra 5.000 với 7 rule của RC1, trong khi tổng thật của
   `Q-OBS-GENERIC-LABEL` là 202.557 — sai 40 lần. Tổng thật nằm ở
   `quality_rule_totals` (chỉ có trong release DB).
2. Xuất ca lẻ ra CSV có trần. Trần đó được ghi vào report cho từng nhóm, không
   cắt lặng.

CHỈ ĐỌC. Exit: 0 = chạy xong · 2 = BLOCKED (thiếu nguồn tổng) · 3 = lỗi dùng.
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import time
from pathlib import Path

UNRESOLVED_CONSEQUENCES = {
    "build_failure", "blocking", "blocking_until_classified", "non_candidate",
}
RESOLVED_CONSEQUENCES = {"warning", "warning_conditional"}

BLOCKED = "BLOCKED"


def _tables(con) -> set[str]:
    return {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}


def _has_col(con, table: str, col: str) -> bool:
    try:
        return any(r[1] == col for r in con.execute(f"PRAGMA table_info({table})"))
    except sqlite3.Error:
        return False


def _load_inventory(path: Path) -> tuple[list[dict], str]:
    try:
        import yaml
    except ImportError:
        raise SystemExit(
            "LỖI: cần PyYAML để đọc rule inventory. `pip install PyYAML`, "
            "hoặc bỏ --inventory (khi đó nhóm theo rule sẽ là BLOCKED).")
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    return doc["rules"], str(doc.get("inventory_version", "unknown"))


def _entity_col(con, have: set[str]) -> str | None:
    """Ten cot dinh danh trong `quality_issues` KHAC NHAU giua hai schema:

        build DB    (storage.py)        -> scope_uid
        release DB  (release_schema.py) -> entity_id

    Hard-code mot trong hai lam hong toan bo export tren schema con lai. Day
    chinh la khiem khuyet B0-05: ban truoc hard-code `scope_uid`, chay tren
    release DB thi 16 nhom bao `no such column` ma cong cu VAN tra exit 0.
    """
    if "quality_issues" not in have:
        return None
    cols = {r[1] for r in con.execute("PRAGMA table_info(quality_issues)")}
    for c in ("scope_uid", "entity_id"):
        if c in cols:
            return c
    return None


def _rule_totals(con, have: set[str]) -> tuple[dict, str]:
    """Tổng THẬT theo rule. Ưu tiên quality_rule_totals; nếu không có thì khai
    rõ rằng con số lấy từ bảng đã bị cắt mẫu."""
    if "quality_rule_totals" in have:
        rows = con.execute(
            "SELECT rule_id, total_count, sampled_count, sample_limit"
            " FROM quality_rule_totals").fetchall()
        return ({r[0]: {"total": r[1], "sampled": r[2], "limit": r[3]}
                 for r in rows}, "quality_rule_totals")
    if "quality_issues" in have:
        rows = con.execute(
            "SELECT rule_id, COUNT(*) FROM quality_issues GROUP BY 1").fetchall()
        return ({r[0]: {"total": None, "sampled": r[1], "limit": None}
                 for r in rows}, "quality_issues (ĐÃ CẮT MẪU — không phải tổng)")
    return {}, "không có nguồn"


def collect(con, have: set[str], rules: list[dict], totals: dict,
            totals_source: str) -> list[dict]:
    cats: list[dict] = []
    ecol = _entity_col(con, have)

    # ── A · theo rule chất lượng ───────────────────────────────────────────
    for r in rules:
        if r.get("consequence") not in UNRESOLVED_CONSEQUENCES:
            continue
        rid = r["id"]
        t = totals.get(rid)
        if t is None and totals_source == "quality_rule_totals":
            # quality_rule_totals là nguồn đầy đủ: vắng mặt = 0 ca, và đó là
            # con số CHÍNH XÁC, không phải ước lượng.
            t = {"total": 0, "sampled": 0, "limit": None}
        t = t or {}
        total, sampled, limit = t.get("total"), t.get("sampled", 0), t.get("limit")
        truncated = bool(limit) and sampled >= limit and (
            total is None or total > sampled)
        cats.append({
            "category": f"rule:{rid}",
            "kind": "quality_rule",
            "severity": r.get("severity"),
            "consequence": r.get("consequence"),
            "defect": r.get("defect"),
            "total": total if total is not None else sampled,
            "total_is_exact": total is not None,
            "total_source": totals_source,
            "sampled_in_db": sampled,
            "sample_limit": limit,
            "sampled_is_truncated": truncated,
            "downstream": r.get("downstream"),
            "entity_column": ecol,
            "query": (f"SELECT {ecol} FROM quality_issues"
                      f" WHERE rule_id = '{rid}'") if ecol else None,
            "query_blocked_reason": None if ecol else
                "khong xac dinh duoc cot dinh danh cua quality_issues",
        })

    # ── B · ô nguồn bị loại ────────────────────────────────────────────────
    if "dropped_cells" in have:
        for reason, n in con.execute(
                "SELECT COALESCE(NULLIF(TRIM(reason),''),'(KHÔNG CÓ LÝ DO)'),"
                " COUNT(*) FROM dropped_cells GROUP BY 1 ORDER BY 2 DESC"):
            cats.append({
                "category": f"dropped_cell:{reason}",
                "kind": "dropped_cell",
                "consequence": "excluded_with_reason",
                "total": n, "total_is_exact": True,
                "total_source": "dropped_cells (đếm đầy đủ, không cắt mẫu)",
                "sampled_is_truncated": False,
                "note": ("ô nguồn bị loại có lý do. KHÔNG phải mất dữ liệu "
                         "(C1 đã chứng minh), nhưng cũng KHÔNG dùng được."),
                "query": ("SELECT source_cell_uid FROM dropped_cells"
                          f" WHERE reason = '{reason}'"),
            })
    else:
        cats.append({"category": "dropped_cell:*", "kind": "dropped_cell",
                     "status": BLOCKED, "note": "thiếu bảng dropped_cells"})

    # ── C · bảng không parse được ──────────────────────────────────────────
    tbl = "tables" if "tables" in have else (
        "table_features" if "table_features" in have else None)
    if tbl and not _has_col(con, tbl, "parse_status"):
        cats.append({"category": "table_parse_status:*", "kind": "table",
                     "status": BLOCKED,
                     "note": f"bảng {tbl} không có cột parse_status"})
    elif tbl:
        for st, n in con.execute(
                f"SELECT COALESCE(NULLIF(TRIM(parse_status),''),'(RỖNG)'),"
                f" COUNT(*) FROM {tbl} WHERE COALESCE(parse_status,'') <> 'ok'"
                " GROUP BY 1 ORDER BY 2 DESC"):
            cats.append({
                "category": f"table_parse_status:{st}",
                "kind": "table", "consequence": "non_candidate",
                "total": n, "total_is_exact": True,
                "total_source": f"{tbl}.parse_status",
                "sampled_is_truncated": False,
                "query": (f"SELECT table_uid FROM {tbl}"
                          f" WHERE COALESCE(parse_status,'') = '{st}'"),
            })
    else:
        cats.append({"category": "table_parse_status:*", "kind": "table",
                     "status": BLOCKED, "note": "không có tables/table_features"})

    # ── D · readiness (chỉ RC2 trở đi) ─────────────────────────────────────
    if "observation_readiness" in have:
        n_nc = con.execute(
            "SELECT COUNT(*) FROM observation_readiness"
            " WHERE execution_candidate = 0").fetchone()[0]
        n_cnr = con.execute(
            "SELECT COUNT(*) FROM observation_readiness"
            " WHERE execution_candidate = 1 AND execution_ready = 0").fetchone()[0]
        cats.append({"category": "readiness:non_candidate", "kind": "readiness",
                     "consequence": "non_candidate", "total": n_nc,
                     "total_is_exact": True,
                     "total_source": "observation_readiness",
                     "sampled_is_truncated": False,
                     "query": "SELECT observation_uid FROM observation_readiness"
                              " WHERE execution_candidate = 0"})
        cats.append({"category": "readiness:candidate_not_ready",
                     "kind": "readiness", "consequence": "review_required",
                     "total": n_cnr, "total_is_exact": True,
                     "total_source": "observation_readiness",
                     "sampled_is_truncated": False,
                     "query": "SELECT observation_uid FROM observation_readiness"
                              " WHERE execution_candidate = 1"
                              " AND execution_ready = 0"})
    else:
        cats.append({
            "category": "readiness:*", "kind": "readiness", "status": BLOCKED,
            "note": ("thiếu bảng observation_readiness — DB này dựng bằng "
                     "policy v1.0 (RC1). Chạy lại trên build RC2."),
        })
    return cats


def export_cases(con, cats: list[dict], out_csv: Path, cap: int) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["category", "kind", "consequence", "entity_uid"])
        for c in cats:
            if c.get("status") == BLOCKED or not c.get("query"):
                c["exported"] = 0
                c["export_note"] = "BLOCKED — không xuất được"
                continue
            n = 0
            try:
                for (uid,) in con.execute(c["query"] + f" LIMIT {cap}"):
                    w.writerow([c["category"], c["kind"],
                                c.get("consequence", ""), uid])
                    n += 1
            except sqlite3.Error as e:
                # LOI TRUY VAN LA LOI THUC THI, khong phai ghi chu.
                # Ban truoc nuot loi vao export_note va van tra exit 0 -> 16
                # nhom hong ma bang chung van ghi PASS (B0-05).
                c["exported"] = 0
                c["status"] = BLOCKED
                c["export_note"] = f"LOI TRUY VAN: {e}"
                c["query_error"] = str(e)
                continue
            c["exported"] = n
            c["export_cap"] = cap
            c["export_truncated"] = n >= cap and (c.get("total") or 0) > n
            if c["export_truncated"]:
                c["export_note"] = (
                    f"CẮT: xuất {n}/{c.get('total')} ca. Đây là trần xuất, "
                    f"KHÔNG phải tổng số ca.")


def distinct_entities(con, cats: list[dict]) -> dict:
    """Union DISTINCT cac entity chua giai quyet, va do chong lan giua rule.

    Tong theo nhom la TONG LAN XUAT HIEN (issue occurrence). Mot entity co the
    dinh nhieu rule, nen cong don theo nhom KHONG phai so entity. Ban truoc goi
    149.415 la 'ca chua giai quyet' — do la occurrence, khong phai entity.
    """
    out = {"measured": False, "reason": None}
    rule_cats = [c for c in cats
                 if c["kind"] == "quality_rule" and c.get("query")
                 and c.get("status") != BLOCKED]
    if not rule_cats:
        out["reason"] = "khong co nhom rule truy van duoc"
        return out
    seen: set[str] = set()
    per_rule: dict[str, set[str]] = {}
    try:
        for c in rule_cats:
            ids = {r[0] for r in con.execute(c["query"])}
            per_rule[c["category"]] = ids
            seen |= ids
    except sqlite3.Error as e:
        out["reason"] = f"LOI TRUY VAN: {e}"
        return out
    counted = 0
    for ids in per_rule.values():
        counted += len(ids)
    multi = {}
    if per_rule:
        tally: dict[str, int] = {}
        for ids in per_rule.values():
            for i in ids:
                tally[i] = tally.get(i, 0) + 1
        multi = {"entities_in_1_rule": sum(1 for v in tally.values() if v == 1),
                 "entities_in_2plus_rules": sum(1 for v in tally.values() if v > 1),
                 "max_rules_per_entity": max(tally.values()) if tally else 0}
    out.update({
        "measured": True,
        "distinct_unresolved_entity_uids": len(seen),
        "sum_of_per_rule_counts": counted,
        "overlap_note": "sum_of_per_rule_counts >= distinct_... vi mot entity co the "
                        "dinh nhieu rule. KHONG dung so cong don lam so entity.",
        "overlap": multi,
        "caveat": "Chi tinh tren MAU trong quality_issues (bi cat o sample_limit), "
                  "nen day la CAN DUOI cua so entity that.",
    })
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description="RC-18 · sổ đăng ký ca chưa giải quyết (CHỈ ĐỌC)")
    ap.add_argument("--db", required=True)
    ap.add_argument("--inventory", default="configs/rule_inventory_v1.yaml")
    ap.add_argument("--report", default=None)
    ap.add_argument("--cases", default=None, help="xuất ca lẻ ra CSV")
    ap.add_argument("--max-cases-per-category", type=int, default=1000)
    ap.add_argument("--tiny-money-summary", default=None,
                    help="gộp phần dư RC-03 từ tiny_money_summary.json")
    ap.add_argument("--label", default=None)
    a = ap.parse_args()

    db = Path(a.db)
    if not db.exists():
        print(f"LỖI: không thấy DB: {db}", file=sys.stderr)
        return 3
    inv = Path(a.inventory)
    if not inv.exists():
        print(f"LỖI: không thấy inventory: {inv}", file=sys.stderr)
        return 3

    rules, inv_version = _load_inventory(inv)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    con.execute("PRAGMA query_only=ON")
    have = _tables(con)
    totals, totals_source = _rule_totals(con, have)
    cats = collect(con, have, rules, totals, totals_source)

    meta = {}
    if "build_meta" in have:
        try:
            meta = dict(con.execute("SELECT key, value FROM build_meta"))
        except sqlite3.Error:
            pass

    if a.cases:
        export_cases(con, cats, Path(a.cases), a.max_cases_per_category)

    tm = None
    if a.tiny_money_summary:
        p = Path(a.tiny_money_summary)
        if not p.exists():
            print(f"CẢNH BÁO: không thấy {p} — bỏ qua phần RC-03",
                  file=sys.stderr)
        else:
            try:
                s = json.loads(p.read_text(encoding="utf-8"))
                if not isinstance(s, dict):
                    raise ValueError("không phải object JSON")
            except (json.JSONDecodeError, ValueError, UnicodeDecodeError) as e:
                print(f"CẢNH BÁO: {p} không đọc được ({e}) — bỏ qua phần RC-03. "
                      "Sổ đăng ký ghi nhóm này là BLOCKED, KHÔNG ghi 0.",
                      file=sys.stderr)
                cats.append({"category": "tiny_money_residual",
                             "kind": "cohort", "status": BLOCKED,
                             "note": f"không đọc được {p}: {e}"})
            else:
                tm = {
                    "category": "tiny_money_residual",
                    "kind": "cohort", "consequence": "non_candidate",
                    "total": s.get("unclassified_count"),
                    "total_is_exact": bool(s.get("ran_on_full_cohort")),
                    "total_source": ("tiny_money_summary.json (RC-03), "
                                     f"denominator={s.get('denominator')}"),
                    "sampled_is_truncated": False,
                    "class_counts": s.get("class_counts"),
                    "note": ("ca tiny-money mà classifier RC-03 KHÔNG kết luận "
                             "được: parse_or_column_role_unresolved."),
                }
                cats.append(tm)

    dist = distinct_entities(con, cats) if a.cases else {"measured": False,
        "reason": "chi do khi co --cases (can chay truy van)"}
    n_query_err = sum(1 for c in cats if c.get("query_error"))
    n_blocked = sum(1 for c in cats if c.get("status") == BLOCKED)
    n_trunc = sum(1 for c in cats if c.get("sampled_is_truncated"))
    resolvable = [c for c in cats if c.get("status") != BLOCKED]
    total_occurrences = sum(c.get("total") or 0 for c in resolvable
                            if c["kind"] != "dropped_cell")

    rep = {
        "_schema": "RC-18 · sổ đăng ký ca chưa giải quyết. Chỉ đọc.",
        "tool": "tools/unresolved_registry.py",
        "tool_version": "1.0",
        "db_path": str(db),
        "db_label": a.label,
        "build_id": meta.get("build_id"),
        "release_profile": meta.get("release_profile", "build DB"),
        "inventory_version": inv_version,
        "rule_totals_source": totals_source,
        "unresolved_consequences": sorted(UNRESOLVED_CONSEQUENCES),
        "resolved_consequences_excluded": sorted(RESOLVED_CONSEQUENCES),
        "generated_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "categories": cats,
        "entity_column_used": _entity_col(con, have),
        "distinct_entity_analysis": dist,
        "summary": {
            "n_categories": len(cats),
            "n_blocked_categories": n_blocked,
            "n_query_errors": n_query_err,
            "n_truncated_sample_categories": n_trunc,
            "total_issue_occurrences_excl_dropped_cells": total_occurrences,
            "distinct_unresolved_entity_uids_FROM_SAMPLE_ONLY":
                dist.get("distinct_unresolved_entity_uids"),
            "counting_note":
                "HAI CON SO KHAC PHAM VI, KHONG DUOC SO TRUC TIEP VOI NHAU. "
                "`total_issue_occurrences` lay tu quality_rule_totals = tong THAT, "
                "nhung dem LUOT XUAT HIEN (mot entity dinh 2 rule = 2 luot). "
                "`distinct_..._FROM_SAMPLE_ONLY` dem entity DUY NHAT nhung chi tren "
                "MAU trong quality_issues (cat o sample_limit) -> CAN DUOI. "
                "Muon so entity that phai co full issue store, chua co o RC1.",
            "total_dropped_cells": sum(
                c.get("total") or 0 for c in cats if c["kind"] == "dropped_cell"),
        },
    }
    if n_trunc:
        rep["summary"]["truncation_warning"] = (
            f"{n_trunc} nhóm có mẫu bị cắt trong quality_issues. Cột `total` "
            "lấy từ " + totals_source + ". KHÔNG dùng `sampled_in_db` làm tổng.")

    for c in cats:
        if c.get("status") == BLOCKED:
            print(f"  ∅ {c['category']:<44} BLOCKED — {c.get('note','')}")
            continue
        flag = " ⚠CẮT-MẪU" if c.get("sampled_is_truncated") else ""
        exact = "" if c.get("total_is_exact", True) else " (~ước lượng)"
        print(f"  · {c['category']:<44} {c.get('total'):>9}"
              f"{exact}{flag}   [{c.get('consequence','')}]")
    s = rep["summary"]
    print(f"\nnhóm={s['n_categories']} · blocked={s['n_blocked_categories']}"
          f" · cắt-mẫu={s['n_truncated_sample_categories']}")
    print(f"lượt xuất hiện (không kể ô bị loại) = "
          f"{s['total_issue_occurrences_excl_dropped_cells']}")
    de = s.get("distinct_unresolved_entity_uids_FROM_SAMPLE_ONLY")
    print(f"entity DISTINCT (CHỈ trên mẫu)      = "
          f"{de if de is not None else 'chưa đo (cần --cases)'}")
    if de is not None:
        print("  ⚠ hai số trên KHÁC PHẠM VI — không so trực tiếp; xem counting_note")
    print(f"ô nguồn bị loại có lý do             = {s['total_dropped_cells']}")

    if a.report:
        rp = Path(a.report)
        rp.parent.mkdir(parents=True, exist_ok=True)
        rp.write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                      encoding="utf-8")
        print(f"report → {rp}")
    if a.cases:
        print(f"cases  → {a.cases}")

    # Phan biet ro ba muc:
    #   3 = co LOI TRUY VAN -> so lieu KHONG dung duoc
    #   2 = co nhom BLOCKED vi thieu bang (ket qua dung, chi la chua do duoc)
    #   0 = do du
    if n_query_err:
        print(f"\nLOI: {n_query_err} nhom loi truy van — so lieu KHONG dung duoc.",
              file=sys.stderr)
        return 3
    return 2 if n_blocked else 0


if __name__ == "__main__":
    sys.exit(main())
