"""Kiểm từng tên thương mại xem nó CÓ TRONG CHÍNH CORPUS BTC hay không.

VÌ SAO TỆP NÀY TỒN TẠI — một xung đột SSOT có thật
--------------------------------------------------
`configs/retrieval/company_brand_v1.yaml` là 53 mã / 77 tên **gõ tay**. Nguyên
tắc của dự án là *"không dùng dữ liệu ngoài A6 nếu chưa được plan/SSOT cho
phép"*. Hai câu đó mâu thuẫn nhau, và cách xử thường gặp — "tên công ty thì ai
chả biết" — là đúng loại lý lẽ mà nguyên tắc kia sinh ra để chặn.

Nhưng "dữ liệu ngoài" là một câu hỏi ĐO ĐƯỢC, không phải một câu hỏi quan điểm:

    tên xuất hiện trong chính báo cáo của mã đó  ⇒ nó nằm SẴN trong corpus BTC,
                                                   người chỉ làm việc trích ra
    tên KHÔNG xuất hiện ở đâu trong corpus       ⇒ đây là tri thức NGOÀI

Script chia 77 tên thành hai nhóm đó và ghi nhóm thứ nhất ra
`company_brand_attested_v1.yaml`, để `load_aliases(brands="a6")` chạy được một
nhánh **chỉ dùng tên chứng thực được từ corpus**. Nhờ vậy câu hỏi "giữ hay bỏ"
trở thành một phép A/B ba nhánh có số, thay vì một cuộc tranh luận.

CÁCH ĐỐI SÁNH — cố ý thô, và vì sao thế là đúng
-----------------------------------------------
So trên dạng **nén, bỏ dấu, bỏ mọi ký tự không chữ-số** của cả tên lẫn văn bản.
Nghĩa là "ACB Bank" khớp "ACBBank" và "A.C.B Bank", còn "Ngân hàng TMCP Á Châu"
thì không. Thô theo hướng **dễ chứng thực**: nếu ngay cả phép so dễ dãi này
cũng không tìm thấy, thì tên đó chắc chắn là tri thức ngoài.

    python tools/attest_brands.py            # in báo cáo, ghi tệp attested
    python tools/attest_brands.py --kiem      # chỉ kiểm, không ghi (dùng trong CI)
"""

from __future__ import annotations

import argparse
import re
import sys
import unicodedata
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
FS = ROOT / "data/raw/btc/financial_statements"
SRC = ROOT / "configs/retrieval/company_brand_v1.yaml"
DST = ROOT / "configs/retrieval/company_brand_attested_v1.yaml"

# Bao nhiêu báo cáo mỗi mã và bao nhiêu ký tự mỗi báo cáo là ĐỦ để chứng thực.
# Tên công ty nằm ở trang bìa và mục "Thông tin chung", tức ngay đầu tệp. Đọc
# hết 1.973 tệp × vài MB không đổi kết luận mà tốn hàng phút.
MAX_DOC = 6
MAX_CHAR = 400_000


def _fold(s: str) -> str:
    d = unicodedata.normalize("NFD", s)
    d = "".join(c for c in d if unicodedata.category(c) != "Mn")
    return re.sub(r"[^0-9a-z]+", "", d.replace("đ", "d").replace("Đ", "D").lower())


def attest() -> tuple[dict[str, list[str]], list[tuple[str, str]]]:
    brands = yaml.safe_load(SRC.read_text(encoding="utf-8"))["brands"]
    co: dict[str, list[str]] = {}
    khong: list[tuple[str, str]] = []
    for tk, names in sorted(brands.items()):
        d = FS / tk
        txt = ""
        if d.is_dir():
            for p in sorted(d.rglob("*_extracted.txt"))[:MAX_DOC]:
                txt += _fold(p.read_text(encoding="utf-8", errors="replace")[:MAX_CHAR])
        for n in names:
            if _fold(n) in txt:
                co.setdefault(tk, []).append(n)
            else:
                khong.append((tk, n))
    return co, khong


_HEADER = """# SINH TỰ ĐỘNG bởi `tools/attest_brands.py` — KHÔNG sửa tay.
#
# Tập con của `company_brand_v1.yaml` gồm những tên thương mại ĐÃ CHỨNG THỰC là
# có mặt trong chính báo cáo của mã đó, tức nằm sẵn trong corpus BTC. Dùng cho
# `load_aliases(brands="a6")` để chạy nhánh KHÔNG có tri thức ngoài A6.
#
# Chứng thực: {n_co}/{n_tong} tên. Không chứng thực được ({n_khong}):
{ds_khong}
version: 1
"""


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="attest_brands")
    ap.add_argument("--kiem", action="store_true", help="chỉ kiểm, không ghi tệp")
    ns = ap.parse_args(argv)

    co, khong = attest()
    n_co = sum(len(v) for v in co.values())
    n_tong = n_co + len(khong)
    print(f"chứng thực được từ corpus BTC : {n_co}/{n_tong} tên "
          f"({len(co)} mã)")
    print(f"KHÔNG chứng thực được         : {len(khong)}")
    for tk, n in khong:
        print(f"    {tk:5s} {n}")

    if ns.kiem:
        return 0
    ds = "\n".join(f"#   {tk:5s} {n}" for tk, n in khong) or "#   (không có)"
    # Dump the whole mapping. Dumping scalar strings one by one emits YAML's
    # document-end marker (`...`), which used to become a literal suffix in all
    # attested aliases and silently broke entity matching.
    body = yaml.safe_dump(
        {"brands": dict(sorted(co.items()))},
        allow_unicode=True,
        sort_keys=False,
    )
    DST.write_text(
        _HEADER.format(n_co=n_co, n_tong=n_tong, n_khong=len(khong), ds_khong=ds)
        + body, encoding="utf-8")
    # Đọc lại để chắc tệp vừa ghi là YAML hợp lệ và không mất tên nào.
    lai = yaml.safe_load(DST.read_text(encoding="utf-8"))["brands"]
    assert sum(len(v) for v in lai.values()) == n_co, "ghi/đọc lại không khớp"
    print(f"\n→ {DST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
