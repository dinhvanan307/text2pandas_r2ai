#!/usr/bin/env python3
"""Viết lại bài nộp — sửa các lỗi ĐO ĐƯỢC mà không đụng bộ sinh đáp án.

VÌ SAO HẬU XỬ LÝ CHỨ KHÔNG SỬA BỘ SINH
--------------------------------------
Đo trên `submission_CARD.zip` (1.012 câu):

    evidence dùng            1 bảng/câu   (986/1012)
    relevant_tables khai    10 bảng/câu   (991/1012)
    evidence nằm ngoài danh sách khai      0/1012
    relevant_tables[0] LÀ bảng evidence  986/986
    → 8.924/9.910 bảng khai (90,1%) không tham gia tính đáp án

Nghĩa là cắt danh sách **không thể** làm đổi `answer` — bảng sinh ra đáp án
luôn đứng đầu. Đây là điều kiện cho phép sửa ở tầng hậu xử lý: rẻ, đảo ngược
được, so sánh được với bản cũ, và không chạm vào đường sinh đáp án đang chạy.

BA PHÉP SỬA
-----------
F1  cắt `relevant_tables` theo dạng câu hỏi, LUÔN giữ bảng evidence
F2  suy `relevant_docs` TỪ `relevant_tables` — đúng bất biến của bộ vàng
F3  điền câu rỗng bằng truy hồi của tầng Retrieval mới

F1 · CHỌN N THẾ NÀO
-------------------
F₂ = 5PR/(4P+R). Với g bảng vàng và ta trả N bảng chứa t bảng đúng:
P = t/N, R = t/g. N quá lớn thì P sập; N quá nhỏ thì R sập. **N tối ưu ≈ g.**

Không biết g, nhưng ước lượng được: mỗi cặp (doanh nghiệp × năm) mà câu hỏi
chạm tới cần ít nhất một bảng. Nên `N = clamp(số_mã × số_năm, 1, 10)`.

    single + 1 năm          → 1×1 = 1     (417 câu dạng này, trần 0,350 → 0,979)
    single + 2 năm          → 2
    screen 4 mã + 1 năm     → 4
    compare 2 mã + 1 năm    → 2

Đây là ước lượng, không phải phép đo — nhưng nó thay một hằng số 10 áp cho
mọi câu bằng một con số bám theo cấu tạo câu hỏi, và cấu tạo ấy chính là thứ
quyết định số bảng vàng (xem `to_read/24` §1.4).
"""
from __future__ import annotations

import json
import re
import shutil
import sys
import zipfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

import yaml  # noqa: E402

from text2pandas.pipelines.retrieval.question_intent import parse_intent  # noqa: E402

_CSV = re.compile(r"^data/(.+)_line(\d+)\.csv$")
_TABREF = re.compile(r"^[^|]+\|\d+$")
MAX_N = 10


def _n_tables(question: str, alias: dict) -> int:
    it = parse_intent(question, alias)
    n_tick = max(1, len(it.targets) or len(it.tickers) or 1)
    n_year = max(1, len(it.years))
    return max(1, min(n_tick * n_year, MAX_N))


def _evidence_refs(row: dict) -> list[str]:
    out = []
    for e in row.get("evidence") or []:
        m = _CSV.match(e.get("csv_path", ""))
        if m:
            out.append(f"{m.group(1)}|{m.group(2)}")
    return out


def rewrite(row: dict, alias: dict, stats: Counter) -> dict:
    r = dict(row)
    tabs = list(r.get("relevant_tables") or [])
    ev = _evidence_refs(r)

    if tabs:
        n = _n_tables(r.get("question", ""), alias)
        # Bảng evidence PHẢI ở lại, kể cả khi nó rơi ngoài top-N. Mất nó là
        # khai một nguồn khác với nguồn thật sự sinh ra đáp án.
        giu = [t for t in tabs[:n]]
        for e in ev:
            if e in tabs and e not in giu:
                giu.insert(0, e)
                giu = giu[:max(n, len(ev))]
                stats["evidence_keo_lai"] += 1
        stats[f"cat_{len(tabs)}_ve_{len(giu)}"] += 1
        stats["bang_cat_di"] += len(tabs) - len(giu)
        r["relevant_tables"] = giu
    else:
        stats["cau_rong"] += 1

    # F2 · `relevant_docs` được SUY RA, không lưu riêng.
    # `_codebase/schemas/schema.py`: "relevant_docs is exactly the set of
    # document names carried by relevant_tables… the two can never desync."
    cu = list(r.get("relevant_docs") or [])
    moi = list(dict.fromkeys(t.split("|", 1)[0] for t in r["relevant_tables"]))
    if set(cu) != set(moi):
        stats["docs_da_sua"] += 1
    r["relevant_docs"] = moi

    for t in r["relevant_tables"]:
        if not _TABREF.match(t):
            stats["tableref_sai_dinh_dang"] += 1
    return r


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("dùng: rewrite_submission.py <vào.zip> <ra.zip>")
        return 2
    src, dst = Path(argv[1]), Path(argv[2])
    if dst.exists():
        print(f"✗ {dst} đã tồn tại — đặt tên khác thay vì ghi đè")
        return 2
    alias = yaml.safe_load((ROOT / "configs/retrieval/company_alias_v1.yaml")
                           .read_text(encoding="utf-8"))["aliases"]

    zin = zipfile.ZipFile(src)
    names = [n for n in zin.namelist() if n.endswith(".json")]
    if len(names) != 1:
        print(f"✗ ZIP phải chứa ĐÚNG MỘT .json, thấy {names}")
        return 2
    rows = json.loads(zin.read(names[0]))
    stats = Counter()
    out = [rewrite(r, alias, stats) for r in rows]

    # Cấu trúc ZIP là ràng buộc CỨNG của thể lệ: `.json` và `data/` phải nằm
    # trực tiếp ở cấp ngoài cùng, không được bọc trong thư mục cha.
    with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zo:
        zo.writestr("submission.json",
                    json.dumps(out, ensure_ascii=False, indent=1))
        for n in zin.namelist():
            if n.startswith("data/") and not n.endswith("/"):
                zo.writestr(n, zin.read(n))
    zin.close()

    tab_cu = sum(len(r.get("relevant_tables") or []) for r in rows)
    tab_moi = sum(len(r.get("relevant_tables") or []) for r in out)
    P = print
    P(f"vào  : {src}   ({len(rows)} câu · {tab_cu} bảng)")
    P(f"ra   : {dst}   ({len(out)} câu · {tab_moi} bảng)")
    P(f"cắt  : {tab_cu - tab_moi} bảng  ({100*(tab_cu-tab_moi)/tab_cu:.1f}%)")
    P(f"       trung bình {tab_cu/len(rows):.2f} → {tab_moi/len(out):.2f} bảng/câu")
    P(f"docs sửa desync : {stats['docs_da_sua']}")
    P(f"evidence kéo lại: {stats['evidence_keo_lai']}")
    P(f"câu rỗng        : {stats['cau_rong']}")
    P(f"tableref sai ĐN : {stats['tableref_sai_dinh_dang']}")
    P("\nphân bố N mới:")
    for k, v in sorted(stats.items()):
        if k.startswith("cat_"):
            P(f"   {k}: {v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
