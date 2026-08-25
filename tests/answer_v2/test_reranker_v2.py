#!/usr/bin/env python3
"""Reranker v2 — JSON contract, stable ID, abstain. KHÔNG gọi model.

Trọng tâm là ba thứ v1 không có và doc 159 §6.5 bắt buộc:
    1. stable candidate ID ĐỘC LẬP vị trí trình bày
    2. schema JSON nghiêm, whitelist ID, enum reason_codes
    3. đường ABSTAIN (`selected_candidate_id: null`)

Mọi ca hỏng phải rơi về thứ tự scorer **giữ nguyên phần tử**.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/answer_v2"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cell_reranker as CR   # noqa: E402
import llm_client as LC      # noqa: E402
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
             "period_end": "2024-12-31",
             "evidence_ref": f"D_2024_consolidated|line:{i}",
             "value": 1000 + i, "observation_uid": f"u{i}"} for i in range(n)]


def _tl(sid, conf=0.9, rc=("EXACT_METRIC_MATCH",)):
    return json.dumps({"selected_candidate_id": sid, "confidence": conf,
                       "reason_codes": list(rc)}, ensure_ascii=False)


def _client(tra_loi, question="hỏi gì đó", cands=None, trinh_bay="A", seed=""):
    c = LC.LLMClient(endpoint=None, cache_name="test_fixture_v2")
    c._cache.clear()
    if tra_loi is not None:
        cands = cands or _cands()
        vi = CR.thu_tu(cands, trinh_bay, seed or question)
        c.nap_fixture(CR.dung_prompt(question, [cands[j] for j in vi]), tra_loi)
    return c


# ── stable candidate ID ────────────────────────────────────────────────────
@ca("ID · ổn định theo NỘI DUNG, KHÔNG theo vị trí trình bày")
def _():
    """Đây là lỗi cốt lõi của v1: chỉ số là vị trí, nên cùng một ô ở hai thứ tự
    mang hai 'tên' khác nhau và không đối chiếu A/B/C được."""
    cs = _cands(5)
    a = [CR.candidate_id(c) for c in cs]
    b = [CR.candidate_id(c) for c in reversed(cs)]
    assert a == list(reversed(b))
    assert len(set(a)) == 5, "ID phải phân biệt được mọi ứng viên"


@ca("ID · hai ô KHÁC nội dung ⇒ ID khác")
def _():
    x = {"observation_uid": None, "evidence_ref": "D|1", "row_path": "A",
         "col_path": "c", "metric_label": "m"}
    y = dict(x, row_path="B")
    assert CR.candidate_id(x) != CR.candidate_id(y)


# ── che số ─────────────────────────────────────────────────────────────────
@ca("che số · giá trị ô và gold ID KHÔNG lọt vào prompt")
def _():
    cs = _cands()
    p = CR.dung_prompt("Tổng tài sản 2024?", cs)
    for c in cs:
        assert str(c["value"]) not in p, f"giá trị {c['value']} lọt vào prompt"
    assert "gold" not in p.lower()


@ca("prompt · có mã ID cho mọi ứng viên + enum reason_codes")
def _():
    cs = _cands(3)
    p = CR.dung_prompt("x", cs)
    for c in cs:
        assert CR.candidate_id(c) in p
    for r in CR.REASON_CODES:
        assert r in p


# ── schema hợp lệ ──────────────────────────────────────────────────────────
@ca("hợp lệ · chọn đúng ô, GIỮ NGUYÊN phần tử")
def _():
    cs = _cands()
    st = CR.RerankStats()
    sid = CR.candidate_id(cs[2])
    out = CR.rerank("hỏi gì đó", cs, _client(_tl(sid), cands=cs), st)
    assert out[0] is cs[2]
    assert len(out) == len(cs) and set(map(id, out)) == set(map(id, cs))
    assert st.valid_schema == 1 and st.n_doi_top1 == 1 and st.fallback == 0


@ca("hợp lệ · chọn ô top-1 sẵn ⇒ không tính là đổi top1")
def _():
    cs = _cands()
    st = CR.RerankStats()
    CR.rerank("hỏi gì đó", cs, _client(_tl(CR.candidate_id(cs[0])), cands=cs), st)
    assert st.n_doi_top1 == 0 and st.valid_schema == 1


@ca("hợp lệ · model bọc ```json ⇒ vẫn parse được")
def _():
    cs = _cands()
    st = CR.RerankStats()
    raw = "```json\n" + _tl(CR.candidate_id(cs[1])) + "\n```"
    out = CR.rerank("hỏi gì đó", cs, _client(raw, cands=cs), st)
    assert out[0] is cs[1] and st.valid_schema == 1


# ── ABSTAIN ────────────────────────────────────────────────────────────────
@ca("ABSTAIN · null ⇒ hợp lệ schema, giữ scorer, đếm riêng")
def _():
    """v1 KHÔNG có đường này — model buộc phải chọn kể cả khi không ô nào đúng."""
    cs = _cands()
    st = CR.RerankStats()
    out = CR.rerank("hỏi gì đó", cs,
                    _client(_tl(None, 0.1, ("NO_CANDIDATE_MATCHES",)), cands=cs), st)
    assert out == cs
    assert st.valid_schema == 1 and st.abstain == 1 and st.fallback == 1


# ── ADVERSARIAL ────────────────────────────────────────────────────────────
@ca("ADV · ID ngoài whitelist ⇒ ID_NOT_IN_WHITELIST, không đoán")
def _():
    cs = _cands()
    st = CR.RerankStats()
    out = CR.rerank("hỏi gì đó", cs, _client(_tl("c_khongtontai"), cands=cs), st)
    assert out == cs and st.id_not_in_whitelist == 1
    assert "ID_NOT_IN_WHITELIST" in st.ly_do_fallback


@ca("ADV · ID của ứng viên NGOÀI top-K cũng bị chặn")
def _():
    """Whitelist phải là đúng tập đã trình bày, không phải toàn pool."""
    cs = _cands(30)
    st = CR.RerankStats()
    ngoai = CR.candidate_id(cs[25])          # ngoài K=12
    # Fixture phải dựng trên ĐÚNG top-K mà `rerank` trình bày; nếu dựng trên cả
    # pool thì prompt khác nhau ⇒ cache miss ⇒ ENDPOINT_ERROR và ta đo nhầm thứ.
    cl = _client(_tl(ngoai), question="x", cands=cs[:CR.K_MAC_DINH])
    CR.rerank("x", cs, cl, st)
    assert st.id_not_in_whitelist == 1, st.tom_tat()


@ca("ADV · số nguyên trần (kiểu v1) ⇒ KHÔNG còn được chấp nhận")
def _():
    """Đây là hồi quy phải chặn: đường parse số nguyên đã bị gỡ khỏi production."""
    cs = _cands()
    st = CR.RerankStats()
    out = CR.rerank("hỏi gì đó", cs, _client("2", cands=cs), st)
    assert out == cs and st.invalid_schema == 1


@ca("ADV · JSON hỏng · thiếu trường · sai kiểu · reason lạ")
def _():
    cs = _cands()
    sid = CR.candidate_id(cs[1])
    xau = [
        ("{không phải json", "NOT_JSON") if False else ("khong co ngoac", "NOT_JSON"),
        # thiếu dấu đóng ⇒ không tách được object ⇒ NOT_JSON (không phải
        # INVALID_JSON — nhánh đó dành cho chuỗi CÓ ngoặc mà json.loads vỡ)
        ('{"selected_candidate_id":', "NOT_JSON"),
        ('{"selected_candidate_id": ,}', "INVALID_JSON"),
        ('{"confidence":0.5}', "MISSING_FIELD_selected_candidate_id"),
        (json.dumps({"selected_candidate_id": 3}), "BAD_TYPE_selected_candidate_id"),
        (json.dumps({"selected_candidate_id": sid, "confidence": 9}), "BAD_CONFIDENCE"),
        (json.dumps({"selected_candidate_id": sid, "confidence": 0.5,
                     "reason_codes": "abc"}), "BAD_REASON_CODES"),
        (json.dumps({"selected_candidate_id": sid, "confidence": 0.5,
                     "reason_codes": ["MA_LA"]}), "REASON_CODE_NOT_IN_ENUM"),
        ("", "EMPTY_RESPONSE"),
    ]
    wl = {CR.candidate_id(c) for c in cs}
    for raw, mong in xau:
        rec, err = CR.doc_json(raw, wl)
        assert rec is None and err == mong, f"{raw[:40]!r} → {err}, mong {mong}"


@ca("ADV · không endpoint ⇒ ENDPOINT_ERROR, fallback êm")
def _():
    cs = _cands()
    st = CR.RerankStats()
    out = CR.rerank("hỏi gì đó", cs, _client(None), st)
    assert out == cs and st.endpoint_error == 1 and st.fallback == 1


@ca("ADV · ít hơn 2 ứng viên ⇒ KHÔNG gọi model")
def _():
    st = CR.RerankStats()
    c1 = _cands(1)
    out = CR.rerank("x", c1, _client(None), st)
    assert out == c1 and st.attempted == 0


# ── thứ tự trình bày A/B/C ────────────────────────────────────────────────
@ca("trình bày · A/B/C cho ba thứ tự KHÁC nhau, cùng tập phần tử")
def _():
    cs = _cands(6)
    a = CR.thu_tu(cs, "A", "k")
    b = CR.thu_tu(cs, "B", "k")
    c = CR.thu_tu(cs, "C", "k")
    assert a == [0, 1, 2, 3, 4, 5] and c == [5, 4, 3, 2, 1, 0]
    assert sorted(b) == sorted(a) and b != a


@ca("trình bày · hoán vị TẤT ĐỊNH — cùng seed cho cùng kết quả")
def _():
    assert CR.thu_tu(_cands(8), "B", "x") == CR.thu_tu(_cands(8), "B", "x")
    assert CR.thu_tu(_cands(8), "B", "x") != CR.thu_tu(_cands(8), "B", "y")


@ca("trình bày · chọn CÙNG ô ở A và C ⇒ ID giống nhau (bất biến vị trí)")
def _():
    cs = _cands(5)
    sid = CR.candidate_id(cs[3])
    for tb in ("A", "C"):
        st = CR.RerankStats()
        out = CR.rerank("hỏi gì đó", cs,
                        _client(_tl(sid), cands=cs, trinh_bay=tb), st, trinh_bay=tb)
        assert out[0] is cs[3], f"trình bày {tb} chọn sai ô"


# ── log & đếm ──────────────────────────────────────────────────────────────
@ca("log · ghi raw response và ĐÚNG thứ tự ID đã trình bày")
def _():
    cs = _cands()
    st = CR.RerankStats()
    CR.rerank("hỏi gì đó", cs, _client(_tl(CR.candidate_id(cs[1])), cands=cs),
              st, seed_text="s1")
    assert len(st.raw_log) == 1
    lg = st.raw_log[0]
    assert lg["thu_tu_id"] == [CR.candidate_id(c) for c in cs]
    assert lg["trinh_bay"] == "A" and lg["seed"] == "s1"


@ca("đếm · tóm tắt có đủ mọi bộ đếm §6.8")
def _():
    st = CR.RerankStats()
    t = st.tom_tat()
    for k in ("attempted", "valid_schema", "invalid_schema", "id_not_in_whitelist",
              "endpoint_error", "timeout", "abstain", "fallback"):
        assert k in t, f"thiếu bộ đếm {k}"


@ca("hash · prompt và schema hash ổn định, 16 ký tự")
def _():
    assert len(CR.prompt_hash()) == 16 and CR.prompt_hash() == CR.prompt_hash()
    assert len(CR.schema_hash()) == 16 and CR.schema_hash() == CR.schema_hash()


def chay():
    return chay_chung(CA)


if __name__ == "__main__":
    x, n, d = chay()
    raise SystemExit(in_ket_qua(Path(__file__).stem, x, n, d))
