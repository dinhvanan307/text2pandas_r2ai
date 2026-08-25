"""NGUỒN ỨNG VIÊN THỨ SÁU cho pool gold: ĐỐI XỨNG TIÊU ĐỀ MỤC giữa các ô.

Vì sao cần. Năm nguồn của pool v3–v6 (`s2`, `proxy`, `like`, `code`, `stmt`,
`period`) đều đi qua **từ khoá của câu hỏi**: bốn nguồn đầu truy FTS, `like`
khớp cụm sinh từ `content_terms`. Hệ quả đo được: q774 hỏi "tiền mặt và vàng"
của VIB và SHB; pool có đúng thuyết minh §4 "Tiền mặt và vàng" của VIB
(`621b733c182a7c83`) nhưng **thiếu** thuyết minh cùng tên của SHB
(`e51d84c01e60e3f8`) — dù A6 CÓ nó. Gold dựng trên pool ấy sẽ **loại đúng bảng
mà Retrieval trượt**, tức đẩy Recall đo được lên cao giả tạo (docs/81 B5).

Luật của nguồn này — cố ý KHÔNG dùng từ khoá câu hỏi:

    Với câu có nhiều ô, nếu một TIÊU ĐỀ MỤC S xuất hiện ở ô Ci thì nạp mọi bảng
    có tiêu đề mục S ở MỌI ô Cj khác của cùng câu.

Đây là phép đối xứng CẤU TRÚC ("tìm đúng thuyết minh số 4 trong báo cáo của
công ty kia"), không phải phép khớp ngữ nghĩa. Nó không đọc câu hỏi, không đọc
điểm S2, không đọc gold. Vì thế nó là nguồn duy nhất trong pool **không đi qua
BM25** — đúng thứ `docs/91` §8-(1) và `docs/92` P1-3 đòi hỏi để phá trần pool.

Phạm vi mặc định: chỉ các câu có trong `gold_entity_override_v1.json` (12 câu
đang phân xử). Mở rộng cho cả 120 câu là việc của P1-3, không thuộc task này.

Chuẩn hoá tiêu đề: bỏ dấu, hạ chữ, bỏ số thứ tự mục ở đầu và số rác ở đuôi.
Chỉ nhận tiêu đề ≥ 8 ký tự (tránh khớp "23", "Đơn vị: VND").
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "data" / "dev"
POOL_IN = DEV / "gold_tay_pool_v6.jsonl"
POOL_OUT = DEV / "gold_tay_pool_v7.jsonl"
GHI_DE = DEV / "gold_entity_override_v1.json"
MIN_LEN = 8
# Tiêu đề quá phổ biến: nạp theo chúng là nạp cả báo cáo.
CAM = ("don vi vnd", "don vi trieu vnd", "thang 12 nam", "bang can doi ke toan",
       "thuyet minh bao cao tai chinh", "bao cao tai chinh", "don vi tinh")


def chuan(s: str | None) -> str:
    if not s:
        return ""
    d = unicodedata.normalize("NFD", s)
    t = "".join(c for c in d if unicodedata.category(c) != "Mn").replace("đ", "d").lower()
    t = re.sub(r"^[\s\d.,)(]+", "", t)
    t = re.sub(r"[^a-z0-9]+", " ", t).strip()
    t = re.sub(r"\s+\d+$", "", t)
    return t


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="gold_pool_ext_v1")
    p.add_argument("--db", required=True)
    p.add_argument("--max-them", type=int, default=6,
                   help="trần bảng thêm mỗi (ô × tiêu đề)")
    p.add_argument("--tat-ca", action="store_true",
                   help="áp cho cả 120 câu thay vì chỉ 12 câu ghi đè")
    a = p.parse_args(argv)

    conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-200000")
    rows = [json.loads(l) for l in POOL_IN.open(encoding="utf-8") if l.strip()]
    trong_pv = ({int(k) for k in json.loads(GHI_DE.read_text(encoding="utf-8"))["overrides"]}
                if not a.tat_ca else {r["id"] for r in rows})

    can: set[tuple] = set()
    for r in rows:
        if r["id"] in trong_pv and len(r.get("cells") or []) >= 2:
            for cell in r["cells"]:
                tk, yr = cell.split("/")
                can.add((tk, int(yr)))
    print(f"  phạm vi: {len(trong_pv)} câu · {len(can)} ô cần lập chỉ mục", flush=True)

    # MỘT lần quét toàn corpus rồi lập chỉ mục trong bộ nhớ. Truy vấn theo từng
    # ô làm SQLite quét lại 146k dòng mỗi lần — đo được ~27 s/ô.
    kho: dict[tuple, dict[str, list]] = {}
    n_row = 0
    for (u, sec, st, per, un, mc, no, ro, ev, bs, tk, yr) in conn.execute(
            """SELECT t.table_uid,t.section_text,t.statement_type,t.periods,t.units,
                      t.metric_codes,t.n_observations,t.execution_ready_obs,t.evidence_ref,
                      d.basis,d.ticker,d.doc_year
               FROM table_cards t JOIN documents d ON t.doc_id=d.directory_doc_id
               WHERE t.evidence_ref IS NOT NULL"""):
        n_row += 1
        if (tk, yr) not in can:
            continue
        k = chuan(sec)
        if len(k) < MIN_LEN or any(x in k for x in CAM):
            continue
        kho.setdefault((tk, yr), {}).setdefault(k, []).append(
            {"table_uid": u, "ticker": tk, "doc_year": yr, "basis": bs,
             "statement_type": st, "periods": per, "units": un,
             "metric_codes": mc or "", "section_text": sec, "n_obs": no,
             "ready_obs": ro, "evidence_ref": ev, "row_labels": [],
             "sources": ["ext_doi_xung_muc"], "roles": []})
    print(f"  quét {n_row} bảng · lập chỉ mục {len(kho)}/{len(can)} ô", flush=True)

    tong = 0
    for r in rows:
        r.setdefault("ext_them", 0)
        if r["id"] not in trong_pv or len(r.get("cells") or []) < 2:
            continue
        co = {c["table_uid"] for c in r["candidates"]}
        tieu_de: dict[str, set] = {}
        for c in r["candidates"]:
            k = chuan(c.get("section_text"))
            if len(k) >= MIN_LEN and not any(x in k for x in CAM):
                tieu_de.setdefault(k, set()).add((c.get("ticker"), c.get("doc_year")))
        them = []
        for k, o_co in tieu_de.items():
            for cell in r["cells"]:
                tk, yr = cell.split("/")
                oo = (tk, int(yr))
                if oo in o_co:
                    continue
                n = 0
                for cand in kho.get(oo, {}).get(k, []):
                    if cand["table_uid"] in co or n >= a.max_them:
                        continue
                    them.append(dict(cand))
                    co.add(cand["table_uid"])
                    n += 1
        r["candidates"] = r["candidates"] + them
        r["ext_them"] = len(them)
        tong += len(them)
        if them:
            print(f"  q{r['id']:<5} +{len(them):>3} ứng viên (đối xứng tiêu đề mục)", flush=True)

    moi = [c for r in rows for c in r["candidates"]
           if c.get("sources") == ["ext_doi_xung_muc"]]
    uids = sorted({c["table_uid"] for c in moi})
    rl: dict[str, str] = {}
    for i in range(0, len(uids), 400):
        lot = uids[i:i + 400]
        ph = ",".join("?" * len(lot))
        for u, v in conn.execute(
                f"SELECT table_uid,row_labels FROM table_cards_fts WHERE table_uid IN ({ph})", lot):
            rl[u] = str(v or "")
    for c in moi:
        c["row_labels"] = rl.get(c["table_uid"], "").split(" | ")[:3]

    POOL_OUT.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows),
                        encoding="utf-8")
    print(f"pool v7 = v6 + {tong} ứng viên từ nguồn ĐỐI XỨNG TIÊU ĐỀ · "
          f"{POOL_OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
