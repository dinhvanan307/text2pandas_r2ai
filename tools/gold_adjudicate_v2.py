"""Phân xử gold v2 = gold v1 + 12 câu gỡ chặn bởi RC-1..RC-4, KÈM PROVENANCE.

Hai điều tệp này làm mà `gold_v1.jsonl` không làm:

1. **Provenance có cấu trúc.** Mỗi bảng gold mang: ô `(mã, năm)` nó phục vụ,
   vai trò/nhu cầu nó đáp, tiêu đề mục, nhãn dòng neo, và **danh sách TÍN HIỆU
   đã dùng để quyết định**. `gold_v1.jsonl` chỉ có `note` văn xuôi, nên không
   lọc được nhãn theo tín hiệu — `docs/87`/`docs/91` vì thế chỉ tách được
   leakage theo *lượt phân xử* (P0-b vs P0-d), quá thô.

2. **Cờ leakage theo TỪNG NHÃN.** `signals_used` cho phép một thí nghiệm sau
   này chọn đúng tập nhãn KHÔNG dùng tín hiệu đang được kiểm. Ví dụ muốn đo
   `statement_type` thì lấy tập `"statement_type" not in signals_used`.

Hai chế độ quyết định, khai báo rõ trên từng nhãn:
  * `doc`   — người đọc bằng chứng (tiêu đề mục + nhãn dòng) rồi chốt.
  * `luat`  — áp luật khai báo của `docs/84` §3 khi ô × nhu cầu chỉ còn MỘT
              ứng viên hợp lệ. Nhiều hơn một mà không tách được ⇒ UNCERTAIN,
              KHÔNG phá thế bằng `ready_obs` (đó là tín hiệu nhiễm).

Không dùng proxy_gold. Không dùng thứ hạng S2. Không đoán.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "src"))
from gold_pool_v5 import vai_tro_chat                        # noqa: E402

DEV = ROOT / "data" / "dev"
POOL = DEV / "gold_tay_pool_v7.jsonl"
GOLD_V1 = DEV / "gold_v1.jsonl"
GOLD_V2 = DEV / "gold_v2.jsonl"

BASIS = {"công ty mẹ": "separate", "hợp nhất": "consolidated"}

# ── Quyết định ĐỌC BẰNG CHỨNG (chế độ `doc`) ────────────────────────────────
# Mỗi mục: uid → (ô, vai trò, nhãn dòng neo / tiêu đề mục làm bằng chứng)
DOC: dict[int, dict] = {
    767: {"tables": {
        "56ea7bf86ca034bd": ("ACV/2015", "balance_sheet_tai_san",
                             "§'15 BẢNG CÂN ĐỐI KẾ TOÁN Tại ngày 31/12/2015'; dòng 'tien va cac khoan tuong duong tien'"),
        "82b0b913efa6cae8": ("DLG/2015", "balance_sheet_tai_san",
                             "dòng 2 = 'tien va cac khoan tuong duong tien'; periods 2015-12-31; bản RIÊNG"),
    }, "signals": ["row_label", "basis", "doc_year"],
        "note": "Câu nêu 'công ty mẹ' ⇒ separate. Cả hai bảng là nửa TÀI SẢN của BCĐKT."},
    774: {"tables": {
        "621b733c182a7c83": ("VIB/2022", "note_chuyen_de",
                             "§'4 Tiền mặt và vàng'; dòng 'tien mat bang vnd | tien mat bang ngoai te | vang'"),
        "e51d84c01e60e3f8": ("SHB/2022", "note_chuyen_de",
                             "§'4 Tiền mặt và vàng'; dòng 'tien mat bang vnd | tien mat bang ngoai te'"),
    }, "signals": ["section_text", "basis", "doc_year"],
        "note": "Đối xứng tiêu đề mục §4 giữa hai ngân hàng. Bảng SHB CHỈ vào pool "
                "nhờ nguồn ext_doi_xung_muc — năm nguồn cũ đều trượt nó (nó đứng hạng 22 của S2)."},
    790: {"tables": {
        "634a36e4691f68a0": ("BID/2023", "note_chuyen_de",
                             "§'11 CHO VAY KHÁCH HÀNG Phân tích chất lượng nợ'; dòng 'cong nghiep che bien, che tao'"),
        "e4069afe8179c403": ("VIB/2023", "note_chuyen_de",
                             "dòng 'cong nghiep che bien, che tao' trong bảng dư nợ theo ngành; bản RIÊNG"),
    }, "signals": ["row_label", "basis", "doc_year"],
        "note": "Câu ghi 'trên BCTC riêng' ⇒ separate cho CẢ HAI vế."},
    791: {"tables": {
        "7113b99239e90cef": ("GAS/2017", "note_chuyen_de",
                             "§'10 HÀNG TỔN KHO'; dòng 'nguyen lieu, vat lieu'"),
        "0968b3f6a136081b": ("GEG/2017", "note_chuyen_de",
                             "§'9 HÀNG TÔN KHO'; dòng 'nguyen vat lieu'"),
    }, "signals": ["section_text", "row_label", "basis", "doc_year"],
        "note": "Câu im lặng về phạm vi ⇒ mặc định hợp nhất (quy ước docs/81 §4, "
                "GHI RÕ đây là giả định của ta, không phải luật BTC)."},
}

# Câu áp LUẬT khai báo cho từng (ô × nhu cầu).
LUAT = [542, 413, 386, 439, 549, 561, 425, 429]


def full_rows(conn, uids):
    out = {}
    for i in range(0, len(uids), 400):
        lot = uids[i:i + 400]
        ph = ",".join("?" * len(lot))
        for u, rl in conn.execute(
                f"SELECT table_uid,row_labels FROM table_cards_fts WHERE table_uid IN ({ph})", lot):
            out[u] = str(rl or "")
    return out


def main(argv):
    p = argparse.ArgumentParser(prog="gold_adjudicate_v2")
    p.add_argument("--db", required=True)
    a = p.parse_args(argv)
    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-200000")

    P = {r["id"]: r for r in (json.loads(l) for l in POOL.open(encoding="utf-8"))}
    V1 = {r["id"]: r for r in (json.loads(l) for l in GOLD_V1.open(encoding="utf-8"))}
    out: dict[int, dict] = {}

    # 1) Giữ nguyên 89 nhãn cũ, gắn provenance TỐI THIỂU (chế độ `ke_thua`).
    for qid, r in V1.items():
        if r.get("gold_table_uids"):
            out[qid] = {"id": qid, "gold_table_uids": r["gold_table_uids"],
                        "che_do": "ke_thua_v1", "note": r.get("note", ""),
                        "provenance": [], "signals_used": ["KHÔNG GHI — nhãn P0-b/P0-d"],
                        "leakage_flag": "signals_unknown"}
        else:
            out[qid] = {"id": qid, "gold_table_uids": [], "uncertain": True,
                        "reason": r.get("reason"), "missing_evidence": r.get("missing_evidence", ""),
                        "che_do": "ke_thua_v1", "provenance": [],
                        "signals_used": [], "leakage_flag": "n/a"}

    # 2) Chế độ ĐỌC BẰNG CHỨNG.
    for qid, spec in DOC.items():
        pool_uids = {c["table_uid"] for c in P[qid]["candidates"]}
        prov = []
        for u, (cell, vt, ev) in spec["tables"].items():
            if u not in pool_uids:
                raise SystemExit(f"q{qid}: {u} KHÔNG có trong pool v7 — từ chối gán")
            prov.append({"table_uid": u, "cell": cell, "vai_tro": vt, "evidence": ev})
        out[qid] = {"id": qid, "gold_table_uids": sorted(spec["tables"]),
                    "che_do": "doc_bang_chung", "note": spec["note"],
                    "provenance": prov, "signals_used": spec["signals"],
                    "leakage_flag": "basis_rule" if "basis" in spec["signals"] else "clean"}

    # 3) Chế độ LUẬT — chỉ nhận khi ô × nhu cầu còn ĐÚNG MỘT ứng viên hợp lệ.
    for qid in LUAT:
        r = P[qid]
        want = BASIS.get(r.get("explicit_scope") or "hợp nhất")
        needs = r.get("needs") or []
        fr = full_rows(conn, [c["table_uid"] for c in r["candidates"]])
        if not needs:
            out[qid] = {"id": qid, "gold_table_uids": [], "uncertain": True,
                        "reason": "khong_suy_duoc_nhu_cau", "che_do": "luat_khai_bao",
                        "missing_evidence": "Câu không phát sinh nhu cầu loại báo cáo ⇒ luật không áp được.",
                        "provenance": [], "signals_used": [], "leakage_flag": "n/a"}
            continue
        gold, prov, mo = [], [], []
        for cell in r["cells"]:
            tk, yr = cell.split("/")
            yr = int(yr)
            hop = [c for c in r["candidates"]
                   if c.get("ticker") == tk and c.get("doc_year") == yr
                   and (c.get("basis") == want or c.get("basis") is None)]
            for nd in needs:
                cand = [c for c in hop
                        if nd in vai_tro_chat(c.get("statement_type"), fr.get(c["table_uid"], ""))
                        and (c.get("ready_obs") or 0) > 0]
                if len(cand) == 1:
                    c = cand[0]
                    gold.append(c["table_uid"])
                    prov.append({"table_uid": c["table_uid"], "cell": cell, "vai_tro": nd,
                                 "evidence": f"ứng viên DUY NHẤT hợp lệ cho ({cell} × {nd}); "
                                             f"§{str(c.get('section_text'))[:48]!r}"})
                elif len(cand) == 0:
                    mo.append(f"{cell}:{nd}=0 ứng viên")
                else:
                    mo.append(f"{cell}:{nd}={len(cand)} ứng viên không tách được")
        if mo:
            out[qid] = {"id": qid, "gold_table_uids": [], "uncertain": True,
                        "reason": "luat_khong_tach_duoc", "che_do": "luat_khai_bao",
                        "missing_evidence": "; ".join(mo)[:400],
                        "provenance": prov, "signals_used": [], "leakage_flag": "n/a",
                        "gold_mot_phan": sorted(set(gold))}
        else:
            out[qid] = {"id": qid, "gold_table_uids": sorted(set(gold)),
                        "che_do": "luat_khai_bao",
                        "note": f"Luật docs/84 §3, mỗi (ô × nhu cầu) đúng một ứng viên hợp lệ.",
                        "provenance": prov,
                        "signals_used": ["vai_tro_chat", "statement_type", "ready_obs",
                                         "basis", "doc_year"],
                        "leakage_flag": "role_and_ready_obs"}

    GOLD_V2.write_text("".join(json.dumps(out[k], ensure_ascii=False) + "\n"
                               for k in sorted(out)), encoding="utf-8")
    lab = [r for r in out.values() if r.get("gold_table_uids")]
    print(f"gold v2: {len(lab)}/120 gán được · {sum(len(r['gold_table_uids']) for r in lab)} bảng")
    for m in ("ke_thua_v1", "doc_bang_chung", "luat_khai_bao"):
        n = sum(1 for r in out.values() if r["che_do"] == m and r.get("gold_table_uids"))
        u = sum(1 for r in out.values() if r["che_do"] == m and not r.get("gold_table_uids"))
        print(f"   {m:<16} gán {n:>3} · UNCERTAIN {u:>3}")
    print(f"   {GOLD_V2.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
