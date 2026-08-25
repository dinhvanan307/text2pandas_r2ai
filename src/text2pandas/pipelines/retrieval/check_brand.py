"""Kiểm luật của lớp tên thương mại trước khi tin nó.

Một bí danh sai không báo lỗi ở đâu cả — nó âm thầm gán câu hỏi cho SAI công
ty, rồi mọi tầng sau vẫn chạy trơn tru và trả về một con số rất thuyết phục.
Nên luật phải được kiểm bằng máy.

PHÂN BIỆT HAI LOẠI ĐỤNG ĐỘ — bản đầu của file này gộp chúng làm một và báo sai
5 lỗi, trong đó 3 là vô hại:

  LỖI · hai mã có bí danh nén GIỐNG HỆT nhau. Không luật nào gỡ được; câu hỏi
        dùng tên đó là không phân giải được, phải bỏ một trong hai.

  CẢNH BÁO · bí danh A là chuỗi con THỰC SỰ của bí danh B ("datxanh" ⊂
        "dichvubatdongsandatxanh"). `parse_intent._bi_bao` đã xử: khớp DÀI NHẤT
        thắng, nên nhắc tên đầy đủ của B không kéo theo A. Đây là thiết kế, đo
        được trên cặp HAG/HNG, không phải lỗi.

Ngưỡng độ dài là proxy cho an toàn; đụng độ mới là tính chất an toàn thật. Nên
ngưỡng để ở 4 và đụng độ mới chặn.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from text2pandas.pipelines.retrieval.alias_store import BRAND_V1, load_aliases   # noqa: E402
from text2pandas.pipelines.retrieval.normalize import company_aliases            # noqa: E402

MIN_LEN = 4


def kiem() -> tuple[list[str], list[str]]:
    tat = load_aliases(brands=True)
    goc = load_aliases(brands=False)
    them = {t: [n for n in tat[t] if n not in goc.get(t, [])] for t in tat}
    nen_cua = {t: {a for n in tat[t] for a in company_aliases(n)} for t in tat}
    loi, canh = [], []
    for t, names in them.items():
        for n in names:
            for a in company_aliases(n):
                if len(a) < MIN_LEN:
                    loi.append(f"{t}: {n!r} → {a!r} ngắn hơn {MIN_LEN} ký tự")
                for u, nen in nen_cua.items():
                    if u == t:
                        continue
                    if a in nen:
                        loi.append(f"{t}: {a!r} TRÙNG HỆT bí danh của {u}")
                    elif any(a != b and a in b for b in nen):
                        canh.append(f"{t}: {a!r} nằm trong bí danh của {u} "
                                    f"(khớp dài nhất thắng — đã xử)")
    return sorted(set(loi)), sorted(set(canh))


if __name__ == "__main__":
    errs, warns = kiem()
    n = sum(len(v) for v in
            yaml.safe_load(BRAND_V1.read_text(encoding="utf-8"))["brands"].values())
    print(f"tên thương mại: {n}  ·  LỖI: {len(errs)}  ·  cảnh báo: {len(warns)}")
    for e in errs:
        print("  ✗", e)
    for w in warns:
        print("  ~", w)
    raise SystemExit(1 if errs else 0)
