#!/usr/bin/env python3
"""Unit test nhóm feature row_path — doc 140 §3.5.

Mỗi feature: ≥3 ca POSITIVE (feature phải phản ứng đúng chiều) và ≥3 ca
ADVERSARIAL/NO-CHANGE (feature phải im lặng hoặc không bị lừa).

Ca adversarial quan trọng hơn ca positive. Một feature chỉ có ca positive là
feature chưa được kiểm — nó có thể đang thưởng mọi thứ.

Chạy không cần pytest:  python3 tools/run_row_feats_tests_v1.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from execution.row_feats_v1 import (  # noqa: E402
    REGISTRY, bo_sung_ctx, do_sau, doan, row_depth_prior, row_path_overlap,
    row_path_specificity, row_sibling_penalty, tok_noi_dung)
from execution.fact_rank_v1 import toks  # noqa: E402


def _o(label="", row="", table="T1"):
    return {"metric_label": label, "row_path": row, "table_uid": table}


def _ctx(cau: str, pool):
    return bo_sung_ctx({"qt": toks(cau), "n_pool": max(len(pool), 1)}, pool)


CA = []


def ca(ten):
    def deco(f):
        CA.append((ten, f))
        return f
    return deco


# ── tiện ích ───────────────────────────────────────────────────────────────
@ca("util · doan() bỏ đoạn rỗng và cắt đúng dấu ›")
def _():
    assert doan("A › B › C") == ["A", "B", "C"]
    assert doan("") == [] and doan(None) == []
    assert do_sau("A › B") == 2


@ca("util · tok_noi_dung bỏ hư từ, GIỮ token số")
def _():
    t = tok_noi_dung("Phải thu của khách hàng năm 2024")
    assert "cua" not in t, "hư từ 'của' phải bị loại"
    assert "2024" in t, "token số mang thông tin kỳ, không được loại"


# ── row_path_overlap ───────────────────────────────────────────────────────
@ca("row_path_overlap · POSITIVE đoạn path được câu hỏi nhắc thì > 0")
def _():
    pool = [_o("Phải thu khác", "Ngắn hạn › Phải thu"), _o("Phải thu khác", "Dài hạn")]
    c = _ctx("phải thu khác ngắn hạn", pool)
    assert row_path_overlap(pool[0], c) > 0


@ca("row_path_overlap · POSITIVE path khớp nhiều hơn thì điểm cao hơn")
def _():
    pool = [_o("X", "Ngắn hạn › Hợp nhất"), _o("X", "Dài hạn › Riêng")]
    c = _ctx("chỉ tiêu ngắn hạn hợp nhất", pool)
    assert row_path_overlap(pool[0], c) > row_path_overlap(pool[1], c)


@ca("row_path_overlap · POSITIVE token hiếm được thưởng nhiều hơn token phổ biến")
def _():
    pool = [_o("X", "Hợp nhất"), _o("X", "Ngắn hạn"), _o("Y", "Ngắn hạn"),
            _o("Z", "Ngắn hạn"), _o("W", "Ngắn hạn")]
    c = _ctx("hợp nhất ngắn hạn", pool)
    assert row_path_overlap(pool[0], c) > row_path_overlap(pool[1], c), \
        "'hợp nhất' hiếm hơn 'ngắn hạn' trong pool ⇒ IDF cao hơn"


@ca("row_path_overlap · ADVERSARIAL token đã nằm trong metric_label KHÔNG cộng đôi")
def _():
    pool = [_o("Phải thu ngắn hạn", "Phải thu ngắn hạn")]
    c = _ctx("phải thu ngắn hạn", pool)
    assert row_path_overlap(pool[0], c) == 0.0, \
        "R = tok(row) − tok(label) = ∅ ⇒ không được cộng thêm lần nữa"


@ca("row_path_overlap · ADVERSARIAL path rỗng ⇒ 0, không lỗi")
def _():
    pool = [_o("X", ""), _o("X", None)]
    c = _ctx("bất kỳ", pool)
    assert row_path_overlap(pool[0], c) == 0.0
    assert row_path_overlap(pool[1], c) == 0.0


@ca("row_path_overlap · ADVERSARIAL không giao với câu hỏi ⇒ 0, không âm")
def _():
    pool = [_o("X", "Thuyết minh › Bảng phụ")]
    c = _ctx("doanh thu thuần", pool)
    assert row_path_overlap(pool[0], c) == 0.0


# ── row_path_specificity ───────────────────────────────────────────────────
@ca("row_path_specificity · POSITIVE phủ toàn bộ ⇒ 1.0")
def _():
    pool = [_o("X", "Ngắn hạn")]
    assert abs(row_path_specificity(pool[0], _ctx("ngắn hạn", pool)) - 1.0) < 1e-9


@ca("row_path_specificity · POSITIVE token thừa kéo điểm xuống")
def _():
    pool = [_o("X", "Ngắn hạn"), _o("X", "Ngắn hạn › Bên liên quan")]
    c = _ctx("ngắn hạn", pool)
    assert row_path_specificity(pool[0], c) > row_path_specificity(pool[1], c)


@ca("row_path_specificity · POSITIVE hoàn toàn thừa ⇒ −0.5 (biên dưới)")
def _():
    pool = [_o("X", "Bên liên quan")]
    assert abs(row_path_specificity(pool[0], _ctx("tiền mặt", pool)) + 0.5) < 1e-9


@ca("row_path_specificity · ADVERSARIAL path NGẮN không được lợi thế miễn phí")
def _():
    """Doc 140 §3.5 cảnh báo đúng chỗ này: nếu chuẩn hoá sai thì path 1 token
    luôn thắng. Ở đây path ngắn KHÔNG khớp câu hỏi phải thua path dài có khớp."""
    pool = [_o("X", "Khác"), _o("X", "Ngắn hạn › Phải thu › Khách hàng")]
    c = _ctx("phải thu khách hàng ngắn hạn", pool)
    assert row_path_specificity(pool[1], c) > row_path_specificity(pool[0], c)


@ca("row_path_specificity · ADVERSARIAL R rỗng ⇒ 0 trung tính, không phạt")
def _():
    pool = [_o("Tiền mặt", "Tiền mặt")]
    assert row_path_specificity(pool[0], _ctx("tiền mặt", pool)) == 0.0


@ca("row_path_specificity · ADVERSARIAL path toàn hư từ ⇒ 0, không nhiễu")
def _():
    pool = [_o("X", "của › và › các")]
    assert row_path_specificity(pool[0], _ctx("doanh thu", pool)) == 0.0


# ── row_sibling_penalty ────────────────────────────────────────────────────
@ca("row_sibling_penalty · POSITIVE nhãn lặp nhiều trong 1 bảng ⇒ phạt")
def _():
    pool = [_o("Phải thu khác", f"Dòng {i}", "T1") for i in range(8)]
    assert row_sibling_penalty(pool[0], _ctx("phải thu khác", pool)) < 0


@ca("row_sibling_penalty · POSITIVE lặp càng nhiều phạt càng nặng")
def _():
    it = [_o("A", f"r{i}", "T1") for i in range(8)] + [_o("B", "r", "T2")]
    c = _ctx("x", it)
    assert row_sibling_penalty(it[0], c) < row_sibling_penalty(it[-1], c)


@ca("row_sibling_penalty · POSITIVE nhãn duy nhất trong bảng ⇒ 0")
def _():
    pool = [_o("A", "r1", "T1"), _o("B", "r2", "T1")]
    assert row_sibling_penalty(pool[0], _ctx("x", pool)) == 0.0


@ca("row_sibling_penalty · ADVERSARIAL cùng nhãn nhưng KHÁC bảng ⇒ không phạt")
def _():
    pool = [_o("A", "r", f"T{i}") for i in range(8)]
    assert row_sibling_penalty(pool[0], _ctx("x", pool)) == 0.0, \
        "phân rã là hiện tượng TRONG một bảng; khác bảng là bản sao, không phải anh em"


@ca("row_sibling_penalty · ADVERSARIAL nhãn khác hoa/thường vẫn tính là một")
def _():
    pool = [_o("Phải Thu", "r1", "T1"), _o("phải thu", "r2", "T1")]
    assert row_sibling_penalty(pool[0], _ctx("x", pool)) < 0


@ca("row_sibling_penalty · ADVERSARIAL table_uid None không làm vỡ")
def _():
    pool = [{"metric_label": "A", "row_path": "r", "table_uid": None}]
    assert row_sibling_penalty(pool[0], _ctx("x", pool)) == 0.0


# ── row_depth_prior ────────────────────────────────────────────────────────
@ca("row_depth_prior · POSITIVE path sâu mà câu hỏi không nhắc ⇒ phạt")
def _():
    pool = [_o("X", "A › B › C › D")]
    assert row_depth_prior(pool[0], _ctx("doanh thu", pool)) < 0


@ca("row_depth_prior · POSITIVE path 1 đoạn ⇒ 0")
def _():
    pool = [_o("X", "A")]
    assert row_depth_prior(pool[0], _ctx("doanh thu", pool)) == 0.0


@ca("row_depth_prior · POSITIVE sâu hơn thì phạt nặng hơn")
def _():
    pool = [_o("X", "A › B"), _o("X", "A › B › C › D")]
    c = _ctx("doanh thu", pool)
    assert row_depth_prior(pool[1], c) < row_depth_prior(pool[0], c)


@ca("row_depth_prior · ADVERSARIAL đoạn sâu ĐƯỢC câu hỏi nhắc thì miễn phạt")
def _():
    """Khác biệt duy nhất với `section_depth` sẵn có. Nếu test này đỏ thì feature
    không mang thông tin mới và phải bị gỡ."""
    pool = [_o("X", "Ngắn hạn › Phải thu › Khách hàng")]
    c = _ctx("phải thu khách hàng ngắn hạn", pool)
    assert row_depth_prior(pool[0], c) == 0.0


@ca("row_depth_prior · ADVERSARIAL path rỗng ⇒ 0")
def _():
    pool = [_o("X", ""), _o("X", None)]
    c = _ctx("x", pool)
    assert row_depth_prior(pool[0], c) == 0.0 and row_depth_prior(pool[1], c) == 0.0


@ca("row_depth_prior · ADVERSARIAL không phạt sâu hơn mức miễn 1 đoạn")
def _():
    pool = [_o("X", "A › B")]
    assert row_depth_prior(pool[0], _ctx("khong lien quan", pool)) == -0.25


# ── hợp đồng chung ─────────────────────────────────────────────────────────
@ca("hợp đồng · mọi feature trả float và khai đủ metadata")
def _():
    pool = [_o("A", "B › C", "T1")]
    c = _ctx("x", pool)
    for ten, m in REGISTRY.items():
        assert isinstance(m["ham"](pool[0], c), float), ten
        for k in ("weight", "mien", "sua_failure", "circular_with_gold", "hand_tuned"):
            assert k in m, f"{ten} thiếu khai báo {k}"


@ca("hợp đồng · row_depth_prior PHẢI được đánh dấu vòng tròn")
def _():
    assert REGISTRY["row_depth_prior"]["circular_with_gold"] is True, \
        "luật 7 bộ sinh gold chọn row_path ngắn nhất — không khai là tự lừa mình"
    for t in ("row_path_overlap", "row_path_specificity", "row_sibling_penalty"):
        assert REGISTRY[t]["circular_with_gold"] is False


def chay() -> tuple[int, int, list]:
    xanh, do = 0, []
    for ten, f in CA:
        try:
            f()
            xanh += 1
        except AssertionError as e:
            do.append((ten, str(e) or "assert failed"))
        except Exception as e:
            do.append((ten, f"{type(e).__name__}: {e}"))
    return xanh, len(CA), do


if __name__ == "__main__":
    x, n, d = chay()
    for ten, msg in d:
        print(f"✗ {ten}\n    {msg}")
    print(f"\n{x}/{n} xanh")
    raise SystemExit(0 if not d else 1)
