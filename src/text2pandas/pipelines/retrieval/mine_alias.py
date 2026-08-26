"""Khai thác tên thương mại còn thiếu — bằng BẰNG CHỨNG TRONG CORPUS, không đoán.

VẤN ĐỀ ĐO ĐƯỢC
--------------
`company_alias_v1.yaml` chỉ có TÊN PHÁP LÝ ("Tổng Công ty Phân bón và Hoá chất
Dầu khí - CTCP"). Câu hỏi lại dùng TÊN THƯƠNG MẠI ("Đạm Phú Mỹ"). Không khớp
được thì S1 không có ứng viên nào và câu đó mất trắng — không tầng nào sau cứu
được.

CÁCH LÀM — KHÔNG ĐOÁN
---------------------
1. Lấy các cụm hoa-đầu-từ trong câu hỏi mà KHÔNG alias nào phủ.
2. Với mỗi cụm, quét FTS toàn corpus, KHÔNG lọc mã.
3. Chỉ nhận ánh xạ cụm→mã khi một mã CHIẾM ƯU THẾ áp đảo trong kết quả.

Cụm nào corpus không xác nhận thì để lại cho người đọc quyết định, không tự
thêm vào bảng alias.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

import yaml

from text2pandas.pipelines.retrieval.normalize import ascii_compact, company_aliases   # noqa: E402
from text2pandas.pipelines.retrieval.question_intent import parse_intent               # noqa: E402

ROOT = Path(__file__).resolve().parents[4]

# Cụm hoa-đầu-từ tiếng Việt, 1-6 từ.
_HOA = re.compile(r"\b([A-ZÀ-Ỹ][a-zà-ỹ]*(?:\s+[A-ZÀ-Ỹ][a-zà-ỹ]*){0,5})")
# Từ mở đầu câu / từ khung — hoa vì đứng đầu câu, không phải tên riêng.
_KHUNG = {
    "trong", "tinh", "xet", "cuoi", "nam", "vao", "tai", "cho", "voi", "theo",
    "gia", "tong", "chenh", "so", "ty", "he", "loi", "doanh", "ket", "du",
    "hang", "khoan", "no", "von", "chi", "thu", "tien", "luu", "bao", "cong",
    "neu", "khi", "moi", "hay", "xin", "cau", "hoi", "den", "tu", "va", "cac",
    "kinh", "quy", "dau", "muc", "phan", "tram", "trieu", "nghin",
    "dong", "lan", "bao nhieu", "la", "cua", "co", "nhom", "giai", "doan",
    "cp", "ctcp", "tmcp", "tnhh", "cfo", "var", "ebit", "ebitda", "roa", "roe",
}
_DUNG_RIENG = {"ngan hang", "cong ty", "tap doan", "tong cong ty"}


def _dominant(conn, phrase: str, limit: int = 300):
    """Cụm này xuất hiện trong tài liệu của mã nào — quét toàn corpus."""
    try:
        rows = conn.execute(
            "SELECT d.ticker, COUNT(*) FROM table_cards_fts f "
            "JOIN table_cards t ON t.rowid=f.rowid "
            "LEFT JOIN documents d ON d.directory_doc_id=t.doc_id "
            "WHERE table_cards_fts MATCH ? GROUP BY d.ticker "
            "ORDER BY 2 DESC LIMIT ?", (f'"{phrase}"', limit)).fetchall()
    except sqlite3.OperationalError:
        return []
    return [(t, n) for t, n in rows if t]


def main() -> int:
    alias = yaml.safe_load((ROOT / "configs/retrieval/company_alias_v1.yaml")
                           .read_text(encoding="utf-8"))["aliases"]
    qs = [json.loads(l) for l in
          (ROOT / "data/raw/btc/questions/questions.jsonl").open(encoding="utf-8")]
    tat_ca_alias = {a for names in alias.values()
                    for n in ([names] if isinstance(names, str) else names)
                    for a in company_aliases(n)}
    conn = sqlite3.connect("file:" + str(ROOT / "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db")
                           + "?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-200000")

    ung_vien: Counter = Counter()
    trong_cau: defaultdict[str, set] = defaultdict(set)
    for q in qs:
        it = parse_intent(q["question"], alias)
        for m in _HOA.finditer(q["question"]):
            cum = m.group(1).strip()
            nen = ascii_compact(cum)
            tho = " ".join(w for w in re.split(r"\s+", cum.lower()))
            if len(nen) < 5 or tho in _DUNG_RIENG:
                continue
            if all(w in _KHUNG for w in tho.split()):
                continue
            if any(nen in a or a in nen for a in tat_ca_alias if len(a) >= 5):
                continue
            if any(nen in ascii_compact(x) for x in it.tickers):
                continue
            ung_vien[cum] += 1
            trong_cau[cum].add(q["id"])

    print(f"cụm chưa phân giải được: {len(ung_vien)} loại\n")
    print(f"{'cụm':38s} {'#câu':>5s}  mã ưu thế (số bảng)")
    nhan = {}
    for cum, n in ung_vien.most_common(70):
        top = _dominant(conn, cum)
        if not top:
            print(f"{cum[:38]:38s} {n:5d}  — corpus không có cụm này")
            continue
        tong = sum(v for _, v in top)
        t0, n0 = top[0]
        uu_the = n0 / tong
        dau = "✓" if uu_the >= 0.80 and n0 >= 3 else " "
        if dau == "✓":
            nhan[cum] = t0
        print(f"{cum[:38]:38s} {n:5d}  {dau} {t0} {n0}/{tong} ({100*uu_the:.0f}%)"
              f"   {', '.join(f'{a}:{b}' for a, b in top[1:4])}")
    print(f"\nCORPUS XÁC NHẬN {len(nhan)} ánh xạ:")
    print(json.dumps(nhan, ensure_ascii=False, indent=2))
    (ROOT / "artifacts/runs/retrieval/alias_candidates.json").write_text(
        json.dumps({"xac_nhan": nhan,
                    "tan_suat": dict(ung_vien.most_common(200))},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
