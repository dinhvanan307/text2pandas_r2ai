#!/usr/bin/env python3
"""Cell reranker — test chạy ĐƯỢC KHÔNG CẦN MODEL, bằng fixture nạp vào cache.

Trọng tâm là các ca HỎNG: model trả rác, trả chỉ số ngoài khoảng, không gọi
được. Mọi ca đó phải rơi về thứ tự tất định **giữ nguyên phần tử**, vì tầng
dưới (evidence builder, renderer) giả định danh sách không đổi nội dung.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))

import cell_reranker as CR   # noqa: E402
import llm_client as LC      # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _moitruong import chay_chung, in_ket_qua  # noqa: E402
CA = []


def ca(ten):
    def deco(f):
        CA.append((ten, f))
        return f
    return deco


def _cands(n=4):
    return [{"metric_label": f"Chỉ tiêu {i}", "row_path": f"A › B{i}",
             "col_path": "31/12/2024", "statement_type": "balance_sheet",
             "period_end": "2024-12-31", "evidence_ref": f"D|line:{i}",
             "value": 1000 + i, "observation_uid": f"u{i}"} for i in range(n)]


def _client(tra_loi: str | None, question="hỏi gì đó", cands=None):
    """Client offline + fixture: nạp sẵn câu trả lời cho đúng prompt sẽ dựng."""
    c = LC.LLMClient(endpoint=None, cache_name="test_fixture")
    c._cache.clear()
    if tra_loi is not None:
        c.nap_fixture(CR.dung_prompt(question, cands or _cands()), tra_loi)
    return c


@ca("che số · giá trị ô KHÔNG được xuất hiện trong prompt")
def _():
    """Nếu số lọt vào prompt, model có thể chọn theo 'số nào trông hợp lý' —
    đúng lối tắt mà numeric masking sinh ra để chặn."""
    cands = _cands()
    p = CR.dung_prompt("Tổng tài sản 2024?", cands)
    for c in cands:
        assert str(c["value"]) not in p, f"giá trị {c['value']} lọt vào prompt"


@ca("prompt · có đủ nhãn, đường dẫn, cột, kỳ, nguồn cho mọi ứng viên")
def _():
    cands = _cands(3)
    p = CR.dung_prompt("x", cands)
    for i, c in enumerate(cands):
        assert f"[{i}]" in p
        assert c["metric_label"] in p and c["row_path"] in p
        assert c["evidence_ref"] in p


@ca("chọn đúng · model trả '2' ⇒ ứng viên 2 lên đầu, GIỮ NGUYÊN phần tử")
def _():
    cands = _cands()
    st = CR.RerankStats()
    out = CR.rerank("hỏi gì đó", cands, _client("2", cands=cands), st)
    assert out[0] is cands[2]
    assert len(out) == len(cands) and set(map(id, out)) == set(map(id, cands))
    assert st.n_llm_chon == 1 and st.n_doi_top1 == 1


@ca("chọn 0 · không đổi thứ tự, và KHÔNG tính là đổi top1")
def _():
    cands = _cands()
    st = CR.RerankStats()
    out = CR.rerank("hỏi gì đó", cands, _client("0", cands=cands), st)
    assert out[0] is cands[0] and st.n_doi_top1 == 0


@ca("ADVERSARIAL · chỉ số NGOÀI khoảng ⇒ fallback, không đoán")
def _():
    cands = _cands()
    st = CR.RerankStats()
    out = CR.rerank("hỏi gì đó", cands, _client("99", cands=cands), st)
    assert out == cands
    assert st.n_ngoai_khoang == 1 and "CHI_SO_NGOAI_KHOANG" in st.ly_do_fallback


@ca("ADVERSARIAL · chỉ số ÂM ⇒ fallback")
def _():
    cands = _cands()
    st = CR.RerankStats()
    CR.rerank("hỏi gì đó", cands, _client("-1", cands=cands), st)
    assert st.n_ngoai_khoang == 1


@ca("ADVERSARIAL · model trả văn xuôi không có số ⇒ fallback")
def _():
    cands = _cands()
    st = CR.RerankStats()
    out = CR.rerank("hỏi gì đó", cands, _client("Tôi không chắc", cands=cands), st)
    assert out == cands and st.n_fallback == 1


@ca("ADVERSARIAL · model kèm giải thích ⇒ vẫn lấy số ĐẦU TIÊN hợp lệ")
def _():
    cands = _cands()
    st = CR.RerankStats()
    out = CR.rerank("hỏi gì đó", cands, _client("3 vì dòng này là tổng",
                                                cands=cands), st)
    assert out[0] is cands[3]


@ca("ADVERSARIAL · không có endpoint và không có fixture ⇒ fallback êm")
def _():
    cands = _cands()
    st = CR.RerankStats()
    out = CR.rerank("hỏi gì đó", cands, _client(None), st)
    assert out == cands and "KHONG_GOI_DUOC" in st.ly_do_fallback


@ca("ADVERSARIAL · ít hơn 2 ứng viên ⇒ không gọi model")
def _():
    st = CR.RerankStats()
    c1 = _cands(1)
    out = CR.rerank("x", c1, _client(None), st)
    assert out == c1 and st.n_goi == 0 and "IT_HON_2_UNG_VIEN" in st.ly_do_fallback


@ca("K · chỉ K ứng viên đầu vào prompt, phần đuôi vẫn được giữ ở output")
def _():
    cands = _cands(30)
    st = CR.RerankStats()
    p = CR.dung_prompt("x", cands[:CR.K_MAC_DINH])
    cl = LC.LLMClient(endpoint=None, cache_name="test_fixture")
    cl._cache.clear()
    cl.nap_fixture(p, "1")
    out = CR.rerank("x", cands, cl, st)
    assert out[0] is cands[1]
    assert len(out) == 30, "phần tử ngoài top-K không được rơi mất"


@ca("doc_chi_so · biên")
def _():
    assert CR.doc_chi_so("0", 3) == 0
    assert CR.doc_chi_so("2", 3) == 2
    assert CR.doc_chi_so("3", 3) is None
    assert CR.doc_chi_so("", 3) is None
    assert CR.doc_chi_so(None, 3) is None


@ca("identity · đổi bất kỳ trường nào ⇒ cache key ĐỔI")
def _():
    """Hai cấu hình khác nhau không được dùng chung kết quả cache."""
    a = LC.LLMIdentity()
    for k, v in (("model_id", "khac"), ("temperature", 0.7), ("seed", 1),
                 ("quantization", "awq"), ("prompt_template_hash", "abc")):
        b = LC.LLMIdentity(**{**a.__dict__, k: v})
        assert a.key() != b.key(), f"đổi {k} mà cache key không đổi"


@ca("client · offline thì available=False nhưng cache VẪN dùng được")
def _():
    c = _client("1", cands=_cands())
    assert c.available is False
    assert c.chat(CR.dung_prompt("hỏi gì đó", _cands())) == "1"
    assert c.n_hit == 1 and c.n_call == 0


def chay():
    """Ủy quyền cho runner chung — ca thiếu DB thành SKIP, không thành PASS."""
    return chay_chung(CA)


if __name__ == "__main__":
    x, n, d = chay()
    raise SystemExit(in_ket_qua(Path(__file__).stem, x, n, d))
