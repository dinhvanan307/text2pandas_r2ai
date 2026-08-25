"""Nạp bảng bí danh: lớp sinh tự động + lớp tên thương mại curated.

BA NHÁNH, VÌ CÓ MỘT XUNG ĐỘT SSOT THẬT
--------------------------------------
`company_alias_v1.yaml` sinh tự động từ `code_stock.csv` — không tranh cãi.
`company_brand_v1.yaml` là 77 tên **gõ tay** ("Đạm Phú Mỹ", "Vinamilk"), và
nguyên tắc dự án là *không dùng dữ liệu ngoài A6 khi chưa được cho phép*.

Thay vì chọn bên, tách theo BẰNG CHỨNG (`tools/attest_brands.py`):

    brands=True   ("full") · cả 77 tên — trong đó 9 tên KHÔNG có trong corpus
    brands="a6"            · chỉ 68 tên CHỨNG THỰC ĐƯỢC trong chính báo cáo của
                             mã đó ⇒ không có tri thức ngoài A6
    brands=False  ("off")  · không lớp thương mại nào — đối chứng

Ba nhánh này là ba `cfg_sha` khác nhau, nên "giữ hay bỏ" trả lời được bằng A/B
ghép cặp trên đủ 1.012 câu thay vì bằng quan điểm.
"""
from __future__ import annotations

from pathlib import Path

import yaml

__all__ = ["load_aliases", "ALIAS_V1", "BRAND_V1", "BRAND_A6"]

ROOT = Path(__file__).resolve().parents[4]
ALIAS_V1 = ROOT / "configs/retrieval/company_alias_v1.yaml"
BRAND_V1 = ROOT / "configs/retrieval/company_brand_v1.yaml"
BRAND_A6 = ROOT / "configs/retrieval/company_brand_attested_v1.yaml"

_NHANH = {True: BRAND_V1, "full": BRAND_V1, "a6": BRAND_A6,
          False: None, "off": None, None: None}


def load_aliases(brands: bool | str = True) -> dict[str, list[str]]:
    """{ticker: [tên...]}. `brands` ∈ {True/"full", "a6", False/"off"}.

    Giá trị lạ thì NỔ, không im lặng rơi về mặc định: một lỗi chính tả trong
    `eval_v1.yaml` mà lặng lẽ chạy nhánh khác là một phép đo sai không dấu vết.
    """
    if brands not in _NHANH:
        raise ValueError(
            f"brands phải là True/'full' | 'a6' | False/'off', nhận {brands!r}")
    base = yaml.safe_load(ALIAS_V1.read_text(encoding="utf-8"))["aliases"]
    out = {t: ([n] if isinstance(n, str) else list(n)) for t, n in base.items()}
    p = _NHANH[brands]
    if p is None:
        return out
    if not p.is_file():
        raise FileNotFoundError(
            f"thiếu {p.name} cho brands={brands!r}. "
            "Sinh lại bằng `python tools/attest_brands.py`.")
    extra = yaml.safe_load(p.read_text(encoding="utf-8"))["brands"]
    for t, names in extra.items():
        if t in out:
            out[t] += [n for n in names if n not in out[t]]
    return out
