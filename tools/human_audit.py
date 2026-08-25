"""P0-d · HUMAN AUDIT gold tay — dựng phiếu mù, kiểm nhãn người, đo đồng thuận.

NGUYÊN TẮC: audit là bước VALIDATION ĐỘC LẬP, không phải bước tối ưu Retrieval.
Script này KHÔNG đọc, KHÔNG sửa, KHÔNG gọi bất cứ thứ gì trong `src/text2pandas/pipelines/retrieval/**`.
Nó chỉ đọc ba tệp dữ liệu và ghi ra bốn tệp kết quả. Không đụng ranking, S2, S3,
`brands`, `stop_mode`, Answer Generation, submission.

BA LUẬT CHỐNG NHIỄM (thi hành bằng cấu trúc, có `verify` kiểm lại)
------------------------------------------------------------------
1. `human_audit_set.jsonl` KHÔNG chứa: gold AI, điểm, thứ hạng, `sources` của
   ứng viên, nhãn dự đoán của Retrieval, `proxy_tier`, `proxy_n_gold`, `tang`.
   `tang` bị giấu vì nó là tín hiệu độ khó do hệ thống sinh ra — biết trước
   "câu này T2" đã là một gợi ý. Bộ so sánh tự nối lại `tang` từ tệp mẫu.
2. Thứ tự ứng viên = `(mã, năm, phạm vi, loại báo cáo, uid)` — siêu dữ liệu,
   không phải điểm.
3. `--db` bật chế độ **nhãn dòng ĐẦY ĐỦ, xếp theo bảng chữ cái**. Tệp pool chỉ
   giữ 3 nhãn dòng ĐÃ ĐƯỢC XẾP THEO SỐ TỪ KHOÁ TRÙNG CÂU HỎI — tức bằng chứng
   đã bị chính heuristic của hệ thống lọc trước. Audit trên 3 dòng đó là audit
   một phần bằng chứng do hệ thống chọn hộ. Có `--db` thì độc lập hơn hẳn.

    python tools/human_audit.py set    --db data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db
    python tools/human_audit.py sheet  > /tmp/phieu_audit.txt
    python tools/human_audit.py form
    python tools/human_audit.py check
    python tools/human_audit.py compare
    python tools/human_audit.py verify
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data/curated/dev-legacy"
OUT = ROOT / "artifacts/runs/retrieval/audit"

MAU = DEV / "gold_tay_sample_v2.jsonl"
POOL = DEV / "gold_tay_pool_v3.jsonl"
NHAN = DEV / "gold_v1.jsonl"

AUDIT_SET = OUT / "human_audit_set.jsonl"
AUDIT_RES = OUT / "human_audit_results.jsonl"
METRICS = OUT / "human_audit_metrics.json"
PROV = OUT / "human_audit_provenance.json"

UID_RE = re.compile(r"^[0-9a-f]{16}$")

# Enum nguyên nhân bất đồng — đóng, không nhận giá trị lạ.
NGUYEN_NHAN = (
    "wrong_basis",           # cùng bảng/nội dung, sai hợp nhất vs riêng
    "wrong_year",            # sai `doc_year` của báo cáo
    "wrong_ticker",          # sai mã chứng khoán / sai thực thể
    "wrong_statement_type",  # sai loại báo cáo (KQKD vs CĐKT vs LCTT vs note)
    "wrong_table",           # đúng mã/năm/phạm vi/loại nhưng sai bảng
    "pool_miss",             # bảng đúng không có trong pool
    "ambiguous",             # bằng chứng không đủ để tách hai bảng
    "other",
)
QUYET_DINH = ("TABLE", "UNCERTAIN")


# ═════════════════════════════════════════════════════════════════════════════
# nạp dữ liệu
# ═════════════════════════════════════════════════════════════════════════════

def _doc(p: Path) -> list[dict]:
    if not p.is_file():
        sys.exit(f"✗ thiếu {p} — không tự tạo dữ liệu, dừng tại blocker")
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def _bam(p: Path) -> str:
    import hashlib
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def _troi(qids: list[int]) -> list[str]:
    """Gold tay đang được GÁN TIẾP trong lúc audit ⇒ tệp nhãn là mục tiêu động.

    Phân biệt hai trường hợp, vì hậu quả khác hẳn nhau:
      · nhãn của CHÍNH các câu trong audit set đổi ⇒ `compare` sẽ đối chiếu
        quyết định người với một gold KHÁC gold lúc dựng phiếu ⇒ kết quả SAI
        ⇒ chặn cứng (fail-closed đúng tầng: tính đúng bị đe doạ).
      · chỉ có câu MỚI được thêm ⇒ audit set cũ vẫn hợp lệ ⇒ chỉ cảnh báo.
    """
    if not PROV.is_file():
        return ["chưa có provenance — dựng lại bằng `set`"]
    pv = json.loads(PROV.read_text(encoding="utf-8"))
    if _bam(NHAN) == pv.get("sha_gold"):
        return []
    cu = pv.get("nhan_luc_dung", {})
    moi = {str(r["id"]): r for r in _doc(NHAN)}
    doi = [q for q in map(str, qids)
           if json.dumps(cu.get(q), sort_keys=True, ensure_ascii=False)
           != json.dumps({k: v for k, v in (moi.get(q) or {}).items()
                          if k != "note"}, sort_keys=True, ensure_ascii=False)]
    if doi:
        return [f"gold AI của {len(doi)} câu TRONG audit set đã đổi kể từ lúc "
                f"dựng phiếu: {sorted(int(x) for x in doi)}",
                "→ `compare` sẽ đối chiếu nhầm thế hệ gold. Sao lưu kết quả, "
                "dựng lại audit set, phân xử lại các câu đó."]
    # Chỉ có câu MỚI được thêm ⇒ audit set cũ vẫn hợp lệ. Nhưng im lặng ở đây
    # là để người ta tưởng dữ liệu đứng yên — in ra, không chặn.
    print(f"ℹ gold tay đã lớn thêm: {len(moi)} nhãn trên đĩa vs "
          f"{pv.get('n_cau')} lúc dựng phiếu. Nhãn của các câu ĐANG audit "
          f"không đổi ⇒ vẫn đo được. Muốn phủ hết thì dựng lại phiếu "
          f"TRƯỚC khi bắt đầu gán.")
    return []


def _nap() -> tuple[dict, dict, dict]:
    mau = {r["id"]: r for r in _doc(MAU)}
    pool = {r["id"]: r for r in _doc(POOL)}
    nhan = {r["id"]: r for r in _doc(NHAN)}
    thieu = sorted(set(nhan) - set(pool))
    if thieu:
        sys.exit(f"✗ {len(thieu)} câu có nhãn nhưng KHÔNG có pool: {thieu}")
    return mau, pool, nhan


# ═════════════════════════════════════════════════════════════════════════════
# set — dựng audit set mù
# ═════════════════════════════════════════════════════════════════════════════

def _rui_ro(r: dict) -> list[str]:
    """Cờ rủi ro suy từ POOL + CÂU HỎI. Không đụng gold AI ⇒ không rò đáp án.

    Mục đích: xếp câu nguy hiểm lên trước, để nếu người audit dừng sớm thì phần
    đã làm vẫn là phần đáng làm nhất. Đây là *thứ tự*, không phải *đáp án*.
    """
    c = r["candidates"]
    f = []
    if len({x["basis"] for x in c}) > 1:
        f.append("basis_mixed")
    if len({x["doc_year"] for x in c}) > 1:
        f.append("year_mixed")
    if len({x["statement_type"] for x in c}) > 1:
        f.append("stmt_mixed")
    if len({x["ticker"] for x in c}) > 1:
        f.append("ticker_mixed")
    if not r.get("explicit_scope"):
        f.append("scope_silent")     # câu im lặng về hợp nhất/riêng
    if r.get("cells_missing"):
        f.append("cell_missing")
    if len(c) >= 30:
        f.append("pool_large")
    return f


def _rows_day_du(db: Path, uids: list[str]) -> dict[str, list[str]]:
    """Nhãn dòng ĐẦY ĐỦ, xếp A→Z — cố ý KHÔNG xếp theo độ trùng câu hỏi."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    ra: dict[str, list[str]] = {}
    try:
        for i in range(0, len(uids), 800):
            lot = uids[i:i + 800]
            ph = ",".join("?" * len(lot))
            for uid, rl in con.execute(
                    f"SELECT table_uid, row_labels FROM table_cards_fts "
                    f"WHERE table_uid IN ({ph})", lot):
                nh = [x.strip() for x in str(rl or "").split("\n") if x.strip()]
                if len(nh) == 1:
                    nh = [x.strip() for x in nh[0].split(" | ") if x.strip()]
                ra[uid] = sorted(set(nh))
    finally:
        con.close()
    return ra


def cmd_set(db: Path | None) -> int:
    mau, pool, nhan = _nap()
    qids = sorted(nhan)

    # Dựng lại audit set SAU KHI đã gán là xoá nền của công đã làm: uid trong
    # `results` có thể không còn trong set mới. Chặn cứng.
    if AUDIT_RES.is_file():
        da_gan = [r for r in _doc(AUDIT_RES)
                  if (r.get("decision") or "").strip()]
        if da_gan:
            sys.exit(f"✗ {AUDIT_RES.name} đã có {len(da_gan)} quyết định — "
                     f"dựng lại audit set sẽ làm chúng mất neo. Sao lưu rồi xoá "
                     f"tệp kết quả nếu thật sự muốn dựng lại.")

    if db is not None:
        if not db.is_file():
            sys.exit(f"✗ không thấy {db}")
        moi = sorted({c["table_uid"] for q in qids
                      for c in pool[q]["candidates"]})
        day_du = _rows_day_du(db, moi)
        nguon_row = "work.db · đầy đủ · xếp A→Z"
    else:
        day_du = {}
        nguon_row = ("pool_v3 · CHỈ 3 dòng · ĐÃ xếp theo độ trùng câu hỏi "
                     "(bằng chứng bị heuristic hệ thống lọc trước)")

    ban_ghi = []
    for q in qids:
        r = pool[q]
        co = _rui_ro(r)
        ung_vien = []
        for i, c in enumerate(r["candidates"], 1):
            ung_vien.append({
                "cand_id": f"C{i:02d}",
                "table_uid": c["table_uid"],          # ĐẦY ĐỦ 16 ký tự
                "ticker": c["ticker"],
                "doc_year": c["doc_year"],
                "basis": c["basis"],
                "statement_type": c["statement_type"],
                "periods": c["periods"],
                "units": c["units"],
                "n_obs": c["n_obs"],
                "ready_obs": c["ready_obs"],
                "section_text": c["section_text"],
                "row_labels": day_du.get(c["table_uid"], c["row_labels"]),
                "metric_codes": c["metric_codes"],
                "evidence_ref": c["evidence_ref"],
            })
        ban_ghi.append({
            "qid": q,
            "question": r["question"],
            "mode": r["mode"],
            "s0_resolved_targets": r["targets"],   # S0 sinh ra — ĐƯỢC PHÉP BÁC
            "s0_resolved_years": r["years"],       # S0 sinh ra — ĐƯỢC PHÉP BÁC
            "cells_expected": r["cells"],
            "cells_missing": r["cells_missing"],
            "n_candidates": len(ung_vien),
            "risk_flags": co,
            "row_label_source": nguon_row,
            "candidates": ung_vien,
        })

    # Thứ tự audit: nhiều cờ rủi ro trước, pool lớn trước, rồi qid — TẤT ĐỊNH.
    ban_ghi.sort(key=lambda b: (-len(b["risk_flags"]), -b["n_candidates"],
                                b["qid"]))
    for i, b in enumerate(ban_ghi, 1):
        b["audit_order"] = i

    OUT.mkdir(parents=True, exist_ok=True)
    with AUDIT_SET.open("w", encoding="utf-8") as f:
        for b in ban_ghi:
            f.write(json.dumps(b, ensure_ascii=False) + "\n")

    # Ghim thế hệ dữ liệu. `gold_v1.jsonl` đang được gán tiếp bởi P0-b, nên
    # "phiếu này dựng từ gold nào" phải là dữ kiện, không phải trí nhớ.
    PROV.write_text(json.dumps({
        "sha_gold": _bam(NHAN), "sha_pool": _bam(POOL), "sha_mau": _bam(MAU),
        "n_cau": len(ban_ghi), "n_ung_vien": sum(b["n_candidates"]
                                                 for b in ban_ghi),
        "phu_tang": dict(Counter(mau[q]["tang"] for q in qids)),
        "row_label_source": nguon_row,
        # Bản chụp nhãn AI lúc dựng phiếu — CHỈ để phát hiện trôi. Tệp này KHÔNG
        # phải phiếu và người audit không đọc nó.
        "nhan_luc_dung": {str(q): {k: v for k, v in nhan[q].items()
                                   if k != "note"} for q in qids},
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"✓ {AUDIT_SET.relative_to(ROOT)} · {len(ban_ghi)} câu · "
          f"{sum(b['n_candidates'] for b in ban_ghi)} ứng viên")
    print(f"  phủ tầng: {dict(Counter(mau[q]['tang'] for q in qids))}")
    print(f"  nhãn dòng: {nguon_row}")
    print(f"  ghim gold sha={_bam(NHAN)} → {PROV.relative_to(ROOT)}")
    return 0


# ═════════════════════════════════════════════════════════════════════════════
# sheet — phiếu người đọc
# ═════════════════════════════════════════════════════════════════════════════

_BASIS = {"consolidated": "HỢP NHẤT", "separate": "RIÊNG"}


def cmd_sheet(tu: int, den: int, rows: int) -> int:
    ds = _doc(AUDIT_SET)
    if not ds:
        sys.exit("✗ chưa có audit set — chạy `set` trước")
    print("PHIẾU HUMAN AUDIT · gold tay · P0-d")
    print("Phiếu KHÔNG chứa gold AI, điểm, thứ hạng, nguồn ứng viên.")
    print("Thứ tự ứng viên là siêu dữ liệu (mã, năm, phạm vi, loại, uid).")
    print("`s0_*` là do hệ thống phân giải — BẠN ĐƯỢC PHÉP BÁC nếu câu hỏi "
          "nói khác.\n")
    for b in ds[tu - 1:den]:
        print("═" * 78)
        print(f"#{b['audit_order']:02d}  qid={b['qid']}  "
              f"pool={b['n_candidates']}  cờ={','.join(b['risk_flags']) or '-'}")
        print(f"Q: {b['question']}")
        print(f"s0_targets={b['s0_resolved_targets']}  "
              f"s0_years={b['s0_resolved_years']}  "
              f"ô={b['cells_expected']}"
              + (f"  ⚠THIẾU Ô: {b['cells_missing']}" if b["cells_missing"]
                 else ""))
        o = None
        for c in b["candidates"]:
            k = (c["ticker"], c["doc_year"])
            if k != o:
                print(f"  ── {c['ticker']} · {c['doc_year']} {'─' * 44}")
                o = k
            print(f"  [{c['cand_id']}] {c['table_uid']}  "
                  f"{_BASIS.get(c['basis'], str(c['basis'])):8s} "
                  f"{c['statement_type']:16s} obs={c['n_obs']}/{c['ready_obs']} "
                  f"kỳ={c['periods']}")
            if c["section_text"]:
                print(f"        sec: {c['section_text'][:72]}")
            for nh in c["row_labels"][:rows]:
                print(f"        row: {nh[:72]}")
            if len(c["row_labels"]) > rows:
                print(f"        … còn {len(c['row_labels']) - rows} dòng")
    return 0


# ═════════════════════════════════════════════════════════════════════════════
# form — mẫu kết quả rỗng
# ═════════════════════════════════════════════════════════════════════════════

def cmd_form() -> int:
    ds = _doc(AUDIT_SET)
    if AUDIT_RES.is_file():
        sys.exit(f"✗ {AUDIT_RES.name} đã tồn tại — không ghi đè công đã làm")
    OUT.mkdir(parents=True, exist_ok=True)
    with AUDIT_RES.open("w", encoding="utf-8") as f:
        for b in ds:
            f.write(json.dumps({
                "qid": b["qid"],
                "auditor": "",                 # tên người audit
                "decision": "",                # TABLE | UNCERTAIN
                "human_table_uids": [],        # ≥1 uid 16 ký tự nếu TABLE
                "evidence": "",                # BẮT BUỘC — dựa vào cái gì
                "reason": "",                  # BẮT BUỘC — vì sao chọn
                "disagreement_reason": "",     # điền SAU khi `compare` báo lệch
                "minutes": 0,
            }, ensure_ascii=False) + "\n")
    print(f"✓ {AUDIT_RES.relative_to(ROOT)} · {len(ds)} dòng rỗng")
    print("  Điền `decision`, `human_table_uids`, `evidence`, `reason`.")
    print("  ĐỪNG điền `disagreement_reason` trước khi chạy `compare` — "
          "biết mình lệch ở đâu rồi mới ghi nguyên nhân là hợp lệ; "
          "biết gold AI TRƯỚC khi quyết định thì không.")
    return 0


# ═════════════════════════════════════════════════════════════════════════════
# check — kiểm định dạng, fail loudly, hàm thuần
# ═════════════════════════════════════════════════════════════════════════════

def kiem(ds: list[dict], res: list[dict]) -> list[str]:
    """Hàm THUẦN: không sửa `ds`/`res`, chỉ trả danh sách lỗi."""
    loi: list[str] = []
    hop_le = {b["qid"]: {c["table_uid"] for c in b["candidates"]} for b in ds}
    thay = Counter(r.get("qid") for r in res)
    for q, n in thay.items():
        if n > 1:
            loi.append(f"qid {q}: {n} dòng trùng")
    for q in sorted(set(hop_le) - set(thay)):
        loi.append(f"qid {q}: CHƯA audit")
    for r in res:
        q = r.get("qid")
        p = f"qid {q}"
        if q not in hop_le:
            loi.append(f"{p}: không có trong audit set")
            continue
        d = (r.get("decision") or "").strip().upper()
        uids = r.get("human_table_uids") or []
        if d not in QUYET_DINH:
            loi.append(f"{p}: `decision` phải là {QUYET_DINH}, thấy {d!r}")
        if not (r.get("evidence") or "").strip():
            loi.append(f"{p}: thiếu `evidence`")
        if not (r.get("reason") or "").strip():
            loi.append(f"{p}: thiếu `reason`")
        if d == "TABLE":
            if not uids:
                loi.append(f"{p}: `decision=TABLE` nhưng không có uid")
            if len(uids) != len(set(uids)):
                loi.append(f"{p}: uid trùng trong cùng một nhãn")
            for u in uids:
                if not UID_RE.match(str(u)):
                    loi.append(f"{p}: uid {u!r} không phải 16 ký tự hex "
                               f"(uid cụt là lỗi đã xảy ra ở v2)")
                elif u not in hop_le[q]:
                    loi.append(f"{p}: uid {u} KHÔNG có trong pool của câu này")
        elif d == "UNCERTAIN" and uids:
            loi.append(f"{p}: `UNCERTAIN` mà vẫn ghi uid — mâu thuẫn")
        dr = (r.get("disagreement_reason") or "").strip()
        if dr and dr not in NGUYEN_NHAN:
            loi.append(f"{p}: `disagreement_reason`={dr!r} ngoài enum "
                       f"{NGUYEN_NHAN}")
    return loi


def cmd_check() -> int:
    ds, res = _doc(AUDIT_SET), _doc(AUDIT_RES)
    for c in _troi([b["qid"] for b in ds]):
        print(f"⚠ TRÔI DỮ LIỆU: {c}")
    truoc = json.dumps([ds, res], sort_keys=True, ensure_ascii=False)
    loi = kiem(ds, res)
    assert json.dumps([ds, res], sort_keys=True,
                      ensure_ascii=False) == truoc, "kiem() đã sửa dữ liệu vào"
    if loi:
        print(f"✗ {len(loi)} lỗi")
        for x in loi:
            print(f"  · {x}")
        return 1
    print(f"✓ sạch · {len(res)} nhãn người, 0 lỗi format/UID")
    return 0


# ═════════════════════════════════════════════════════════════════════════════
# compare — đồng thuận theo SET OVERLAP, không ép single-label
# ═════════════════════════════════════════════════════════════════════════════

def _bo(r: dict) -> set[str] | None:
    """`None` = UNCERTAIN."""
    if (r.get("decision") or "").strip().upper() == "UNCERTAIN":
        return None
    return set(r.get("human_table_uids") or [])


def _bo_ai(g: dict) -> set[str] | None:
    if g.get("uncertain"):
        return None
    return set(g.get("gold_table_uids") or [])


def _suy_nguyen_nhan(ai: set[str], hu: set[str], meta: dict) -> str:
    """Suy nguyên nhân từ SIÊU DỮ LIỆU của hai bảng — đối chứng với người ghi.

    Chỉ suy khi mỗi bên đúng một bảng; nhiều bảng thì cơ chế không đơn trị.
    """
    if len(ai) != 1 or len(hu) != 1:
        return "ambiguous"
    a, h = meta.get(next(iter(ai))), meta.get(next(iter(hu)))
    if a is None or h is None:
        return "other"
    for k, v in (("ticker", "wrong_ticker"), ("doc_year", "wrong_year"),
                 ("basis", "wrong_basis"),
                 ("statement_type", "wrong_statement_type")):
        if a[k] != h[k]:
            return v
    return "wrong_table"


def cmd_compare() -> int:
    mau, pool, nhan = _nap()
    ds, res = _doc(AUDIT_SET), _doc(AUDIT_RES)
    troi = _troi([b["qid"] for b in ds])
    if troi:
        print("✗ CHẶN: gold AI đã trôi kể từ lúc dựng phiếu")
        for c in troi:
            print(f"  · {c}")
        return 2
    loi = kiem(ds, res)
    if loi:
        print(f"✗ {len(loi)} lỗi format — sửa xong mới đo được đồng thuận")
        for x in loi:
            print(f"  · {x}")
        return 1

    meta = {c["table_uid"]: c for b in ds for c in b["candidates"]}
    tang = {q: mau[q]["tang"] for q in mau}
    rmap = {r["qid"]: r for r in res}

    hang, dem = [], Counter()
    for b in ds:
        q = b["qid"]
        ai, hu = _bo_ai(nhan[q]), _bo(rmap[q])
        if ai is None and hu is None:
            loai = "agree_both_uncertain"
        elif ai is None:
            loai = "ai_uncertain_human_labeled"
        elif hu is None:
            loai = "human_uncertain_ai_labeled"
        elif ai == hu:
            loai = "agree_exact"
        elif ai & hu:
            loai = "partial_overlap"
        else:
            loai = "disjoint"
        giao = len(ai & hu) if (ai is not None and hu is not None) else 0
        hop = len(ai | hu) if (ai is not None and hu is not None) else 0
        hang.append({
            "qid": q, "tang": tang[q], "loai": loai,
            "ai": sorted(ai) if ai is not None else "UNCERTAIN",
            "human": sorted(hu) if hu is not None else "UNCERTAIN",
            "jaccard": round(giao / hop, 4) if hop else None,
            "nguyen_nhan_nguoi": (rmap[q].get("disagreement_reason") or "")
                                 .strip() or None,
            "nguyen_nhan_suy": (
                _suy_nguyen_nhan(ai, hu, meta)
                if loai in ("disjoint", "partial_overlap")
                else ("pool_miss" if loai == "ai_uncertain_human_labeled"
                      else ("pool_miss" if loai == "human_uncertain_ai_labeled"
                            else None))),
        })
        dem[loai] += 1

    n = len(hang)
    dong_y = dem["agree_exact"] + dem["agree_both_uncertain"]
    mem = dong_y + dem["partial_overlap"]
    bat_dong = [h for h in hang if h["loai"] not in
                ("agree_exact", "agree_both_uncertain")]

    thieu_nn = [h["qid"] for h in bat_dong if not h["nguyen_nhan_nguoi"]]
    theo_tang = defaultdict(lambda: {"n": 0, "bat_dong": 0})
    for h in hang:
        theo_tang[h["tang"]]["n"] += 1
        if h in bat_dong:
            theo_tang[h["tang"]]["bat_dong"] += 1

    nn = Counter(h["nguyen_nhan_nguoi"] or "CHƯA_GHI" for h in bat_dong)
    nn_suy = Counter(h["nguyen_nhan_suy"] for h in bat_dong)
    lech_nn = [h["qid"] for h in bat_dong
               if h["nguyen_nhan_nguoi"] and h["nguyen_nhan_suy"]
               and h["nguyen_nhan_nguoi"] != h["nguyen_nhan_suy"]]

    m = {
        "n_audited": n,
        "gold_agreement": dong_y,
        "gold_disagreement": n - dong_y,
        "agreement_rate_strict": round(dong_y / n, 4) if n else None,
        "agreement_rate_lenient": round(mem / n, 4) if n else None,
        "mean_jaccard": round(
            sum(h["jaccard"] for h in hang if h["jaccard"] is not None)
            / max(1, sum(1 for h in hang if h["jaccard"] is not None)), 4),
        "phan_loai": dict(dem),
        "theo_tang": {k: dict(v) for k, v in sorted(theo_tang.items())},
        "nguyen_nhan_nguoi_ghi": dict(nn),
        "nguyen_nhan_suy_tu_metadata": {str(k): v for k, v in nn_suy.items()},
        "bat_dong_thieu_nguyen_nhan": thieu_nn,
        "nguoi_ghi_khac_suy_luan": lech_nn,
        "chi_tiet": hang,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    METRICS.write_text(json.dumps(m, ensure_ascii=False, indent=2),
                       encoding="utf-8")

    print(f"n={n}  đồng thuận={dong_y}  bất đồng={n - dong_y}")
    print(f"agreement chặt   = {m['agreement_rate_strict']}")
    print(f"agreement nới    = {m['agreement_rate_lenient']}  (tính cả trùng "
          f"một phần)")
    print(f"Jaccard trung bình = {m['mean_jaccard']}")
    print(f"phân loại: {dict(dem)}")
    print(f"theo tầng: {m['theo_tang']}")
    print(f"nguyên nhân (người ghi): {dict(nn)}")
    print(f"nguyên nhân (suy từ metadata): {m['nguyen_nhan_suy_tu_metadata']}")
    if thieu_nn:
        print(f"⚠ {len(thieu_nn)} bất đồng CHƯA có nguyên nhân: {thieu_nn}")
    if lech_nn:
        print(f"⚠ {len(lech_nn)} câu người ghi khác suy luận metadata: "
              f"{lech_nn} — đọc kỹ, đây thường là chỗ hiểu nhau lệch")
    print(f"✓ {METRICS.relative_to(ROOT)}")
    return 1 if thieu_nn else 0


# ═════════════════════════════════════════════════════════════════════════════
# verify — chứng minh audit set không rò đáp án
# ═════════════════════════════════════════════════════════════════════════════

CAM = ("gold_table_uids", "uncertain", "score", "rank", "sources",
       "proxy_tier", "proxy_n_gold", "tang", "s2", "hits_at_rank", "note")


def cmd_verify() -> int:
    ds, nhan = _doc(AUDIT_SET), {r["id"]: r for r in _doc(NHAN)}
    mau = {r["id"]: r for r in _doc(MAU)}
    loi = []

    # Quét theo KHOÁ có cấu trúc, không quét văn bản thô: `statement_type` có
    # giá trị hợp lệ là `note`, quét thô sẽ báo động giả và làm người ta quen
    # với việc bỏ qua cảnh báo.
    def _khoa(o, duong=""):
        if isinstance(o, dict):
            for k, v in o.items():
                if k in CAM:
                    loi.append(f"audit set chứa khoá cấm `{k}` tại {duong}")
                _khoa(v, f"{duong}.{k}")
        elif isinstance(o, list):
            for v in o:
                _khoa(v, f"{duong}[]")

    for b in ds:
        _khoa(b, f"qid{b['qid']}")

    for b in ds:
        for c in b["candidates"]:
            if not UID_RE.match(c["table_uid"]):
                loi.append(f"qid {b['qid']}: uid {c['table_uid']} không đủ 16")
    # thứ tự ứng viên phải là siêu dữ liệu, không phải điểm
    for b in ds:
        k = [(c["ticker"] or "", c["doc_year"] or 0, c["basis"] or "",
              c["statement_type"] or "", c["table_uid"]) for c in b["candidates"]]
        if k != sorted(k):
            loi.append(f"qid {b['qid']}: ứng viên không xếp theo siêu dữ liệu")
    # gold AI phải nằm trong pool — nếu không, `compare` sẽ vô nghĩa
    for q, g in nhan.items():
        if g.get("uncertain"):
            continue
        co = {c["table_uid"] for b in ds if b["qid"] == q
              for c in b["candidates"]}
        for u in g["gold_table_uids"]:
            if u not in co:
                loi.append(f"qid {q}: gold AI {u} ngoài audit set")
    # phủ tầng
    for c in _troi([b["qid"] for b in ds]):
        loi.append(f"TRÔI DỮ LIỆU: {c}")
    t = Counter(mau[b["qid"]]["tang"] for b in ds)
    tong = Counter(r["tang"] for r in mau.values())
    print(f"phủ tầng trong audit set: {dict(t)}  /  mẫu đầy đủ: {dict(tong)}")
    for k, n in sorted(tong.items()):
        if t.get(k, 0) == 0:
            print(f"⚠ BLOCKER: tầng `{k}` có 0 nhãn ({n} câu trong mẫu) — kết "
                  f"luận KHÔNG mở rộng được sang tầng này. Dữ liệu thiếu, "
                  f"không phải lỗi script.")
        elif t[k] < n:
            print(f"· tầng `{k}`: {t[k]}/{n} câu đã có nhãn để audit "
                  f"({t[k]/n:.0%})")
    if len(ds) < 30:
        loi.append(f"chỉ {len(ds)} nhãn < 30 — không đạt acceptance")

    if loi:
        print(f"✗ {len(loi)} lỗi")
        for x in loi:
            print(f"  · {x}")
        return 1
    print(f"✓ audit set sạch · {len(ds)} câu · không rò gold/điểm/thứ hạng/nguồn")
    return 0


# ═════════════════════════════════════════════════════════════════════════════
# bias — phân tích thiên lệch gold AI, KHÔNG cần nhãn người
# ═════════════════════════════════════════════════════════════════════════════

BIAS = OUT / "human_audit_prior_analysis.json"
_SEED = 11
_N_MC = 200_000


def _mc_p(ps: list[float], obs: int) -> float:
    """p(quan sát ≥ obs) nếu mỗi bảng gold được rút NGẪU NHIÊN trong pool câu đó.

    Poisson-binomial, ước lượng Monte Carlo với seed cố định ⇒ tất định.
    """
    import random
    r = random.Random(_SEED)
    hit = 0
    for _ in range(_N_MC):
        if sum(1 for p in ps if r.random() < p) >= obs:
            hit += 1
    return hit / _N_MC


def cmd_bias() -> int:
    mau, pool, nhan = _nap()
    lab = [(q, u) for q, g in nhan.items() if not g.get("uncertain")
           for u in g["gold_table_uids"]]
    ket = {"n_cau_co_nhan": len(nhan), "n_bang_gold": len(lab),
           "n_uncertain": sum(1 for g in nhan.values() if g.get("uncertain"))}

    def _c(q, u):
        return next(x for x in pool[q]["candidates"] if x["table_uid"] == u)

    for ten in ("s2", "proxy", "like", "code", "stmt", "period"):
        def pred(x, t=ten):
            return t in x["sources"]
        ps = [sum(1 for x in pool[q]["candidates"] if pred(x))
              / len(pool[q]["candidates"]) for q, _ in lab]
        obs = sum(1 for q, u in lab if pred(_c(q, u)))
        ket[f"nguon_{ten}"] = {
            "quan_sat": obs, "ky_vong_ngau_nhien": round(sum(ps), 2),
            "p_ge_obs": _mc_p(ps, obs),
        }

    vt = []
    for q, u in lab:
        c = pool[q]["candidates"]
        vt.append((next(i for i, x in enumerate(c)
                        if x["table_uid"] == u), len(c)))
    ket["vi_tri_trong_phieu"] = {
        "o_vi_tri_1": sum(1 for i, _ in vt if i == 0),
        "tuong_doi_tb": round(sum(i / max(1, n - 1) for i, n in vt) / len(vt), 4),
        "ghi_chu": "0=đầu phiếu, 1=cuối; thứ tự là siêu dữ liệu nên ≈0,5 là "
                   "kỳ vọng nếu không có thiên lệch vị trí",
    }

    bs = Counter()
    for q, u in lab:
        bs[(pool[q]["explicit_scope"] or "—", _c(q, u)["basis"])] += 1
    ket["basis_theo_scope"] = {f"{k[0]} → {k[1]}": v for k, v in sorted(bs.items())}
    ket["basis_trong_pool"] = dict(Counter(
        x["basis"] for q, _ in lab for x in pool[q]["candidates"]))
    ket["statement_type_gold"] = dict(Counter(_c(q, u)["statement_type"]
                                              for q, u in lab))

    sc = [q for q in mau if mau[q]["tang"] == "screen"]
    ket["screen"] = {
        "n_cau": len(sc),
        "thieu_o": sum(1 for q in sc if pool[q]["cells_missing"]),
        "o_min": min(len(pool[q]["cells"]) for q in sc),
        "o_max": max(len(pool[q]["cells"]) for q in sc),
        "da_gan_nhan": sum(1 for q in sc if q in nhan),
    }
    ket["uncertain_ly_do"] = dict(Counter(
        g.get("reason") for g in nhan.values() if g.get("uncertain")))
    ket["multi_gold"] = {str(q): len(g["gold_table_uids"])
                         for q, g in sorted(nhan.items())
                         if not g.get("uncertain")
                         and len(g["gold_table_uids"]) > 1}

    OUT.mkdir(parents=True, exist_ok=True)
    BIAS.write_text(json.dumps(ket, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(json.dumps(ket, ensure_ascii=False, indent=2))
    print(f"✓ {BIAS.relative_to(ROOT)}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("set"); s.add_argument("--db", type=Path, default=None)
    s = sub.add_parser("sheet")
    s.add_argument("--tu", type=int, default=1)
    s.add_argument("--den", type=int, default=999)
    s.add_argument("--rows", type=int, default=12)
    for t in ("form", "check", "compare", "verify", "bias"):
        sub.add_parser(t)
    a = p.parse_args()
    if a.cmd == "set":
        return cmd_set(a.db)
    if a.cmd == "sheet":
        return cmd_sheet(a.tu, a.den, a.rows)
    return {"form": cmd_form, "check": cmd_check, "compare": cmd_compare,
            "verify": cmd_verify, "bias": cmd_bias}[a.cmd]()


if __name__ == "__main__":
    raise SystemExit(main())
