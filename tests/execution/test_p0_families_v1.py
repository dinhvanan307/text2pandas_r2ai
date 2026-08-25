"""P0 regression suite — PRE_SUBMISSION_BLOCKER (review 131 §6.2).

Bốn họ lỗi đã có bằng chứng lịch sử, nay thành test chạy được:

    UNIT_SCALE   34 ca `A6_DEFECT` (docs/103 F2) — scale A6 sai 10³/10⁶
    SIGN         không được `abs()` kết quả difference/percentage_change
    PERCENT      quy ước "15 nghĩa là 15%", không phải 0,15 và không ×100 hai lần
    ZERO_DENOM   mẫu bằng 0 → abstain, KHÔNG emit inf/nan

Cộng một họ MỚI phát hiện trong phiên này:

    SIGN_CONVENTION_GOLD_DEFECT
        Bộ sinh gold (`02_phan_xu_o.py`) lặp `for tk in sorted(targets)` rồi áp
        công thức "B − A (A=kỳ sớm)" cho CẢ câu so hai công ty. Với 5 câu
        cross-entity của gold-45, dấu do THỨ TỰ ALPHABET của mã CK quyết định,
        không do câu hỏi. qid 760 hỏi "BAB so với NVB" — đọc tự nhiên là
        BAB − NVB = +447.660, gold ghi −447.660.
        ⇒ Khớp gold ở lớp này là fit vào thứ tự vòng lặp của bộ sinh, KHÔNG phải
        đúng ngữ nghĩa. Test này KHOÁ phát hiện đó lại để không ai vô tình
        "sửa" emitter cho khớp gold.

Chạy được cả hai đường (pytest không bắt buộc — sandbox không có nó):
    python3 tools/run_p0_suite_v1.py
    pytest tests/execution/test_p0_families_v1.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from execution.emit_arith_v1 import compute  # noqa: E402
from execution.emit_lookup_v1 import (asked_unit, effective_scale,  # noqa: E402
                                      unit_overrides)

TOL = 1e-9


def _cell(value, scale=0, uid=None):
    return {"value": str(value), "scale_exponent": scale, "observation_uid": uid,
            "metric_label": "X", "col_path": "c"}


# ── UNIT_SCALE ──────────────────────────────────────────────────────────────

def test_unit_scale_34_overrides_ton_tai():
    ov = unit_overrides()
    assert len(ov) == 34, f"cần đúng 34 override A6_DEFECT, có {len(ov)}"


def test_unit_scale_moi_override_duoc_ap_dung():
    """Từng ca một. Đếm tổng rồi bảo 'đã sửa' là chưa kiểm gì cả."""
    ov = unit_overrides()
    bad = []
    for uid, o in ov.items():
        got = effective_scale(_cell(1, scale=o["a6_scale_exponent"], uid=uid))
        if got != o["final_scale_exponent"]:
            bad.append((uid, got, o["final_scale_exponent"]))
    assert not bad, f"override không được áp: {bad[:5]}"


def test_unit_scale_khong_dung_cham_o_khong_lien_quan():
    """Override phải hẹp. Một ô lạ phải giữ nguyên scale của A6."""
    assert effective_scale(_cell(1, scale=6, uid="uid-khong-ton-tai")) == 6
    assert effective_scale(_cell(1, scale=0, uid=None)) == 0


def test_unit_scale_TUNG_CA_theo_expectation_file():
    """Chấm TỪNG DÒNG của `tests/expected_p0_cases.jsonl` — doc 134 P0-5.

    Một vòng lặp bên trong một test là hộp đen với người đọc report: không ai
    kiểm được "34 ca" từ con số "5 test". File expectation làm mỗi ca thành một
    dòng có `case_id`, `expected_scale_exponent`, `decision_reason` và nguồn.

    Ba `kind`, ba kỳ vọng KHÁC nhau — thiếu nhóm đối chứng thì một override
    "áp cho tất cả" cũng sẽ pass:
        OVERRIDE_EXPECTED              phải đổi sang scale đã phân xử
        MUST_NOT_OVERRIDE              A6 đúng ⇒ KHÔNG được đụng
        UNRESOLVED_MUST_NOT_OVERRIDE   chưa đủ bằng chứng ⇒ giữ nguyên
    """
    f = ROOT / "tests/expected_p0_cases.jsonl"
    assert f.is_file(), "chưa sinh expectation — chạy tools/build_expected_p0_cases_v1.py"
    cases = [json.loads(l) for l in f.open(encoding="utf-8") if l.strip()]
    assert len(cases) == 47, f"phải có 47 ca đã phân xử, có {len(cases)}"
    n_override = sum(1 for c in cases if c["kind"] == "OVERRIDE_EXPECTED")
    assert n_override == 34, f"phải có đúng 34 ca A6_DEFECT, có {n_override}"

    bad = []
    for c in cases:
        got = effective_scale(_cell(c.get("raw_value") or 1,
                                    scale=c["a6_scale_exponent"] if "a6_scale_exponent" in c else 0,
                                    uid=c["observation_uid"]))
        if got != c["expected_scale_exponent"]:
            bad.append({"case_id": c["case_id"], "kind": c["kind"],
                        "got": got, "want": c["expected_scale_exponent"]})
    assert not bad, f"{len(bad)}/{len(cases)} ca sai: {bad[:5]}"


def test_unit_scale_delta_dung_chieu():
    """28 ca A6 THIẾU 10^6, 5 ca THỪA 10^3, 1 ca THỪA 10^6 — theo docs/103 F2."""
    d = {}
    for o in unit_overrides().values():
        d[o["delta_exponent"]] = d.get(o["delta_exponent"], 0) + 1
    assert d == {6: 28, -3: 5, -6: 1}, d


# ── SIGN ────────────────────────────────────────────────────────────────────

def test_sign_difference_giu_dau_am():
    r = compute("difference", {"old": _cell(100), "new": _cell(40)}, 1.0)
    assert r["answer"] == -60.0, r


def test_sign_percentage_change_giu_dau_am():
    r = compute("percentage_change", {"old": _cell(200), "new": _cell(150)}, 1.0)
    assert abs(r["answer"] - (-25.0)) < TOL, r


def test_sign_khong_abs_ket_qua():
    """Chiều tăng/giảm là THÔNG TIN. `abs()` làm mất nó và không báo lỗi."""
    down = compute("difference", {"old": _cell(10), "new": _cell(1)}, 1.0)["answer"]
    up = compute("difference", {"old": _cell(1), "new": _cell(10)}, 1.0)["answer"]
    assert down < 0 < up and down == -up


def test_sign_operand_am_van_tinh_dung():
    r = compute("difference", {"old": _cell(-50), "new": _cell(-20)}, 1.0)
    assert r["answer"] == 30.0, r


# ── PERCENT ─────────────────────────────────────────────────────────────────

def test_percent_15_nghia_la_15_khong_phai_0_15():
    r = compute("percentage_change", {"old": _cell(100), "new": _cell(115)}, 1.0)
    assert abs(r["answer"] - 15.0) < TOL, r


def test_percent_khong_nhan_100_hai_lan():
    r = compute("percentage_change", {"old": _cell(100), "new": _cell(200)}, 1.0)
    assert abs(r["answer"] - 100.0) < TOL, r


def test_percent_cau_hoi_phan_tram_khong_bi_coi_la_tien():
    """`asked_unit` phải trả None cho câu %/lần, không được đoán 'đồng'."""
    for q in ("Tỷ lệ sở hữu X là bao nhiêu %?",
              "Y gấp bao nhiêu lần Z?",
              "Tỷ trọng nợ ngắn hạn là bao nhiêu?"):
        name, f = asked_unit({"question": q})
        assert f is None, (q, name, f)


def test_percent_nghin_dong_khong_bi_nuot_boi_dong():
    """'nghìn đồng' phải ra 1e3. Bản đầu khớp `\\bđồng\\b` trước ⇒ sai 1.000 lần."""
    name, f = asked_unit({"question": "X là bao nhiêu nghìn đồng?"})
    assert (name, f) == ("nghin", 1e3), (name, f)
    name, f = asked_unit({"question": "X là bao nhiêu nghìn tỷ đồng?"})
    assert (name, f) == ("nghin_ty", 1e12), (name, f)


# ── ZERO DENOMINATOR ────────────────────────────────────────────────────────

def test_zero_denominator_abstain_khong_emit_inf():
    r = compute("percentage_change", {"old": _cell(0), "new": _cell(50)}, 1.0)
    assert r["abstain"] and r["abstain_reason"] == "ZERO_DENOMINATOR", r
    assert "answer" not in r


def test_zero_denominator_khong_ap_cho_difference():
    """difference với old=0 hoàn toàn hợp lệ — không được abstain nhầm."""
    r = compute("difference", {"old": _cell(0), "new": _cell(50)}, 1.0)
    assert not r["abstain"] and r["answer"] == 50.0, r


def test_unit_unresolved_thi_abstain():
    r = compute("sum", {"x0": _cell(1), "x1": _cell(2)}, None)
    assert r["abstain"] and r["abstain_reason"] == "UNIT_UNRESOLVED", r


# ── ARGMAX ──────────────────────────────────────────────────────────────────

def test_argmax_tra_ve_nam_khong_phai_so_tien():
    ops = {"x0": _cell(10) | {"_year": 2020}, "x1": _cell(30) | {"_year": 2022}}
    r = compute("argmax_year", ops, None)
    assert r["answer"] == 2022.0, r


def test_argmax_hoa_diem_thi_abstain():
    ops = {"x0": _cell(30) | {"_year": 2020}, "x1": _cell(30) | {"_year": 2022}}
    r = compute("argmax_year", ops, None)
    assert r["abstain"] and r["abstain_reason"] == "ARGMAX_TIE", r


# ── UNIT: scale phải áp TRƯỚC khi trừ ───────────────────────────────────────

def test_hai_operand_khac_scale_duoc_quy_ve_cung_don_vi():
    """1 triệu (scale 6) − 500.000 đồng (scale 0) = 500.000 đồng."""
    r = compute("difference",
                {"old": _cell(500000, scale=0), "new": _cell(1, scale=6)}, 1.0)
    assert r["answer"] == 500000.0, r


# ── SIGN_CONVENTION: khoá phát hiện gold defect ─────────────────────────────

def test_gold_difference_cross_entity_theo_thu_tu_ALPHABET():
    """KHOÁ phát hiện: dấu gold do alphabet mã CK, không do câu hỏi.

    Test này KHÔNG khẳng định emitter phải khớp gold. Nó khẳng định GOLD có
    quy ước ẩn ấy — để khi ai đó thấy emitter lệch dấu thì biết đây là vấn đề
    ĐẶC TẢ, không phải bug emitter.
    """
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/dev/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    div = {"trieu": 1e6, "ty": 1e9, "dong": 1.0}
    n = ok = 0
    for g in gold.values():
        if g["lop"] != "difference":
            continue
        prov = g["provenance"]
        if len({s["slot"].split("/")[0] for s in prov}) < 2:
            continue
        n += 1
        d = div.get(g["don_vi_hoi"], 1.0)
        val = {s["slot"].split("/")[0]:
               float(s["raw"]) * (10 ** int(s.get("scale_exponent") or 0))
               for s in prov}
        a, b = sorted(val)
        if abs((val[b] - val[a]) / d - g["dap_an_gold"]) < 1e-6 * max(1, abs(g["dap_an_gold"])):
            ok += 1
    assert n == 5, f"gold-45 phải có 5 câu difference cross-entity, có {n}"
    assert ok == 5, (
        f"{ok}/{n} khớp quy ước alphabet. Nếu con số này đổi, quy ước ẩn của "
        "gold đã đổi — phải phân xử lại trước khi tin bất kỳ số difference nào.")


def test_qid760_gold_nguoc_voi_cach_doc_tu_nhien():
    """Ca cụ thể: 'BAB so với NVB' → đọc tự nhiên là BAB − NVB = +447.660."""
    gold = {g["qid"]: g for g in (json.loads(l) for l in
            (ROOT / "data/dev/gold_dap_an/gold_dap_an_v1.jsonl").open(encoding="utf-8"))
            if not g.get("_meta")}
    g = gold[760]
    v = {s["slot"].split("/")[0]:
         float(s["raw"]) * (10 ** int(s.get("scale_exponent") or 0))
         for s in g["provenance"]}
    tu_nhien = (v["BAB"] - v["NVB"]) / 1e6
    assert abs(tu_nhien - 447660.0) < 1e-6
    assert abs(g["dap_an_gold"] - (-447660.0)) < 1e-6, g["dap_an_gold"]
