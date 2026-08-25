"""Khoá hành vi của TIÊN NGHIỆM LỚP BÁO CÁO ở S2 (docs/118).

Ba thứ được khoá, mỗi thứ vì một lỗi CỤ THỂ đã hoặc có thể xảy ra:

1. `cash_flow` KHÔNG nằm trong `PRIMARY_KINDS`. Ai đó "hoàn thiện cho đủ bộ ba
   báo cáo" sẽ làm mất 0,0103 F2(A) — đã đo, xem docstring `PRIMARY_KINDS`.

2. Truyền `primary_kinds` mà QUÊN đưa độ lớn vào `bonuses` thì `reasons` vẫn
   có "primary", `trace` vẫn có `primary_boost`, và điểm KHÔNG đổi một chút
   nào. Lỗi này ĐÃ XẢY RA và chỉ lộ ra vì cả một lượt quét 4 giá trị boost trả
   về Δ = 0,0000 tuyệt đối. Test so ĐIỂM, không so `reasons`.

3. Cổng theo `mode`. Gold của `single` là thuyết minh 70%, của `compare` 81% —
   áp tiên nghiệm toàn cục làm tệ đi. `single`/`compare` phải BẤT BIẾN.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from retrieval.filter_s1 import Candidate                  # noqa: E402
from retrieval.rank_s2 import PRIMARY_KINDS, rank          # noqa: E402


def _cands():
    def c(uid, kind):
        return Candidate(table_uid=uid, doc_id="D", ticker="AAA", doc_year=2024,
                         basis="hop_nhat", statement_type=kind,
                         n_observations=10, execution_ready_obs=10,
                         periods="2024-12-31", units="VND", metric_codes=None)
    return [c("u_note", "note"), c("u_bs", "balance_sheet"),
            c("u_is", "income_statement"), c("u_cf", "cash_flow")]


def _diem(**kw):
    out = rank(None, _cands(), None, top_k=10, **kw)
    return {s.cand.table_uid: s.score for s in out}


def test_cash_flow_khong_nam_trong_tien_nghiem():
    assert PRIMARY_KINDS == frozenset({"balance_sheet", "income_statement"})
    assert "cash_flow" not in PRIMARY_KINDS


def test_do_lon_phai_di_kem_pham_vi():
    """Có `primary_kinds` mà `bonuses['primary']` = 0 ⇒ điểm KHÔNG được đổi."""
    goc = _diem()
    quen = _diem(primary_kinds=PRIMARY_KINDS)              # quên độ lớn
    assert quen == goc, "primary_kinds một mình không được đổi điểm"
    du = _diem(primary_kinds=PRIMARY_KINDS, bonuses={"primary": 0.60})
    assert du["u_bs"] > goc["u_bs"], "có độ lớn thì ĐIỂM phải tăng thật"
    assert du["u_is"] > goc["u_is"]
    assert du["u_note"] == goc["u_note"], "thuyết minh không được cộng"
    assert du["u_cf"] == goc["u_cf"], "cash_flow không được cộng"


def test_pham_vi_rong_thi_bonus_vo_hieu():
    goc = _diem()
    assert _diem(bonuses={"primary": 1.50}) == goc


def test_cong_theo_mode_o_tang_stages():
    """`single`/`compare` không được nhận tiên nghiệm — kiểm ở lớp gọi."""
    from retrieval.evalkit.stages import Bm25StructuralRanker
    r = Bm25StructuralRanker({"AAA": ["Cong ty A"]}, primary_boost=0.60)
    assert r.primary_modes == ("screen", "related")
    assert "single" not in r.primary_modes and "compare" not in r.primary_modes
    assert r.primary_kinds == PRIMARY_KINDS


def test_default_production_phai_tat():
    """Mặc định production PHẢI là 0,00 — docs/119 §5.8.

    +0,0446 là gain trên DEVELOPMENT set: chính 95 câu ấy đã được dùng để phát
    hiện feature, chọn `PRIMARY_KINDS` và quét boost. Bật mặc định trước khi có
    held-out PASS là đưa một model-selection result vào đường sản xuất.
    """
    import inspect
    from retrieval.evalkit.runner import EvalConfig
    from retrieval.pipeline import run
    cfg = EvalConfig()
    assert cfg.primary_boost == 0.00, "default production phải TẮT"
    assert inspect.signature(run).parameters["primary_boost"].default == 0.00
    assert cfg.primary_modes == ("screen", "related")
    assert cfg.sha != "489d4fed855debb5", (
        "sha trùng bản trước ⇒ checkpoint schema evalkit-2 sẽ bị trộn lẫn")
    assert EvalConfig(gold_manual_path="data/dev/gold_v1.jsonl").sha != cfg.sha


def test_profile_thi_nghiem_ton_tai_va_co_sha_rieng():
    """0,60 chỉ sống trong profile `s2_primary`, có `sha` khác `base`."""
    from retrieval.evalkit.cli import _load_cfg
    base, exp = _load_cfg("base", {}), _load_cfg("s2_primary", {})
    assert base.primary_boost == 0.00 and exp.primary_boost == 0.60
    assert base.sha != exp.sha
    null = _load_cfg("s2_primary_nullmode", {})
    assert null.primary_boost == 0.60
    assert isinstance(null.primary_modes, tuple), "YAML list phải được ép tuple"
    assert "screen" not in null.primary_modes


def test_gold_manual_tro_ve_v2():
    from retrieval.evalkit.runner import EvalConfig
    assert EvalConfig().gold_manual_path == "data/dev/gold_v2.jsonl"
    assert (ROOT / "data/dev/gold_v2.jsonl").is_file()


if __name__ == "__main__":                       # chạy được không cần pytest
    fails = 0
    for ten, fn in sorted(globals().items()):
        if ten.startswith("test_") and callable(fn):
            try:
                fn(); print(f"  ok   {ten}")
            except AssertionError as e:
                fails += 1; print(f"  FAIL {ten}: {e}")
    print("TẤT CẢ ĐẠT" if not fails else f"{fails} test HỎNG")
    raise SystemExit(1 if fails else 0)
