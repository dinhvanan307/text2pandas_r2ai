"""Sinh bảng alias tên công ty → mã, từ `code_stock.csv`.

Vì sao cần: luật của BTC đòi GẦN TRỌN tên xuất hiện trong câu hỏi
(`alias in compact_query`), nên "Hòa Phát" không khớp "CTCP Tập đoàn Hòa Phát".
Đo trên 1.012 câu, luật gốc chỉ phân giải được 73,0% về đúng một mã.

Nguyên tắc sinh: cắt dần các cụm định danh loại hình từ TRÁI sang, mỗi lần cắt
tạo một biến thể. Không bịa tên thị trường — `code_stock.csv` là tên BTC dùng
trong câu hỏi, và họ đã thay đổi một số tên so với thực tế (STB = "Sài Gòn Tài
Lộc"), nên mọi thứ ngoài bảng đó là suy đoán.

CHỐT CHẶN: một biến thể chỉ được giữ nếu nó KHÔNG khớp nhầm sang công ty khác.
Biến thể mơ hồ bị loại chứ không được cho điểm thấp hơn — fail closed. Một mã
sai ở S0 hỏng từ gốc mà mọi tầng sau vẫn chạy trơn.
"""

from __future__ import annotations

import csv
from pathlib import Path

from text2pandas.pipelines.retrieval.normalize import ascii_compact                # noqa: E402

ROOT = Path(__file__).resolve().parents[4]
CS = ROOT / "data/raw/btc/metadata/companies.csv"
OUT = ROOT / "configs/retrieval/company_alias_v1.yaml"

# Cụm loại hình, cắt từ TRÁI. Xếp dài trước ngắn để "ngân hàng tmcp" được cắt
# trọn thay vì chỉ "ngân hàng".
_LEAD = ("ngan hang thuong mai co phan", "ngan hang tmcp", "tong cong ty co phan",
         "tong cong ty", "cong ty co phan", "cong ty tnhh", "tap doan",
         "ctcp", "tnhh", "ngan hang", "cong ty")
# Đuôi hay bị bỏ khi người hỏi viết tắt.
_TRAIL = ("viet nam", "- ctcp", "ctcp")
_MIN = 6                                   # ngưỡng của BTC


def _plain(s: str) -> str:
    """Bỏ dấu, lower, GIỮ khoảng trắng — để cắt được theo cụm từ."""
    import re
    import unicodedata
    d = unicodedata.normalize("NFD", s)
    d = "".join(c for c in d if unicodedata.category(c) != "Mn")
    d = d.replace("đ", "d").replace("Đ", "D").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", d)).strip()


def variants(name: str) -> list[str]:
    """Tên gốc + các biến thể đã cắt cụm loại hình, theo thứ tự dài → ngắn."""
    out, seen = [name], {ascii_compact(name)}
    cur = _plain(name)
    changed = True
    while changed:
        changed = False
        for lead in _LEAD:
            if cur.startswith(lead + " "):
                cur = cur[len(lead) + 1:]; changed = True; break
    for cand in (cur, *(cur[: -len(t)].strip() for t in _TRAIL if cur.endswith(t))):
        c = ascii_compact(cand)
        if len(c) >= _MIN and c not in seen:
            seen.add(c); out.append(cand)
    return out


def build() -> dict[str, list[str]]:
    comp = {r["Mã CK"].strip(): r["Tên công ty"].strip()
            for r in csv.DictReader(CS.open(encoding="utf-8"))}
    raw = {t: variants(n) for t, n in comp.items()}

    # Chốt chặn duy nhất: một biến thể của mã A mà là chuỗi con của biến thể
    # nào đó thuộc mã B ≠ A thì mơ hồ -> loại khỏi A.
    keep: dict[str, list[str]] = {}
    bo: list[tuple[str, str, str]] = []
    for t, names in raw.items():
        ok = []
        for n in names:
            c = ascii_compact(n)
            dung = next((u for u, m in raw.items() if u != t
                         and any(c in ascii_compact(x) for x in m)), None)
            if dung: bo.append((t, n, dung))
            else: ok.append(n)
        keep[t] = ok or [comp[t]]          # không bao giờ để rỗng
    return keep, bo, comp


def main() -> int:
    keep, bo, comp = build()
    n = sum(len(v) for v in keep.values())
    lines = ["# Sinh bởi src/text2pandas/pipelines/retrieval/build_alias.py — KHÔNG sửa tay.",
             "# Nguồn: data/raw/btc/metadata/companies.csv (100 mã).",
             "# Biến thể mơ hồ đã bị loại; xem `rejected` ở cuối.",
             f"version: 1", f"n_tickers: {len(keep)}", f"n_aliases: {n}", "aliases:"]
    for t in sorted(keep):
        lines.append(f"  {t}:")
        for x in keep[t]:
            lines.append(f'    - "{x}"')
    lines.append("rejected:")
    for t, x, u in bo:
        lines.append(f'  - {{ticker: {t}, alias: "{x}", clashes_with: {u}}}')
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"{len(keep)} mã · {n} biến thể · loại {len(bo)} biến thể mơ hồ")
    print(f"-> {OUT.relative_to(ROOT)}")
    for t in ("HPG", "VCB", "VIC", "ACB", "STB"):
        print(f"   {t}: {keep[t]}")
    if bo:
        print("   loại (5 đầu):", [(t, x, u) for t, x, u in bo[:5]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
