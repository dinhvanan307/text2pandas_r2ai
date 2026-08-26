"""Test khung đo — HOÀN TOÀN OFFLINE, không cần `work.db` 4,24 GB.

Mọi test ở đây dựng `QueryOutcome` bằng tay và kiểm chỉ số bằng số tính tay.
Đó là lý do `metrics.py` không được import sqlite3: một khung đo mà chính nó
không test được thì không ai kiểm được nó có đo đúng không.
"""

from __future__ import annotations

import ast
import math
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from text2pandas.pipelines.retrieval.evalkit.metrics import (QueryOutcome, candidate_hit_rate,  # noqa: E402
                                       f2_at_k, gold_size_stats, hit_rate_at_k,
                                       metric_block, mrr, ndcg_at_k,
                                       precision_at_k, precision_at_k_capped,
                                       recall_at_k)
from text2pandas.pipelines.retrieval.evalkit.taxonomy import (Bucket, NoGoldReason, classify,  # noqa: E402
                                        summarize)
from text2pandas.pipelines.retrieval.query_terms import content_terms  # noqa: E402


def oc(qid=1, n_gold=1, hits=(), n_ranked=50, in_cand=True, measurable=True,
       mode="single", n_cand=100):
    return QueryOutcome(qid=qid, mode=mode, n_gold=n_gold, n_candidates=n_cand,
                        gold_in_candidates=in_cand, n_ranked=n_ranked,
                        hits_at=tuple(hits), measurable=measurable)


# ── F2 phải là CÔNG THỨC BTC, không phải f2(P̄, R̄) ────────────────────────────

def test_f2_khop_cong_thuc_btc_g1():
    """g=1, gold ở hạng 1. F2@N = 5·1/(4·1+N)."""
    rows = [oc(n_gold=1, hits=(1,))]
    for n, want in [(1, 1.0), (2, 5 / 6), (3, 5 / 7), (5, 5 / 9), (10, 5 / 14)]:
        assert f2_at_k(rows, n) == pytest.approx(want), f"N={n}"


def test_f2_khop_dinh_nghia_goc_5PR_tren_4P_cong_R():
    """Kiểm rút gọn 5PR/(4P+R) == 5h/(4g+N) trên một ca g=2, N=5, h=2."""
    rows = [oc(n_gold=2, hits=(1, 3), n_ranked=5)]
    P, R = 2 / 5, 2 / 2
    goc = 5 * P * R / (4 * P + R)
    assert f2_at_k(rows, 5) == pytest.approx(goc)
    assert f2_at_k(rows, 5) == pytest.approx(5 * 2 / (4 * 2 + 5))


def test_f2_KHAC_f2_cua_hai_so_da_macro():
    """Bằng chứng vì sao `eval_retrieval.py:167` sai: ghép sau khi macro ≠ macro của ghép.

    Ca này chênh ~2,2 điểm — nhỏ nhưng có hệ thống, và nó lệch THEO HƯỚNG LẠC
    QUAN (0,8333 so với 0,8117 thật). Trên một bảng dùng để chọn cấu hình, một
    thiên lệch có hệ thống còn tệ hơn nhiễu.
    """
    rows = [oc(1, n_gold=1, hits=(1,), n_ranked=3),
            oc(2, n_gold=2, hits=(1, 2), n_ranked=3)]
    thuc = f2_at_k(rows, 3)                      # macro của từng câu — ĐÚNG
    p, r = precision_at_k(rows, 3), recall_at_k(rows, 3)
    sai = 5 * p * r / (4 * p + r)                # ghép hai số đã macro — SAI
    assert thuc == pytest.approx((5 / 7 + 10 / 11) / 2)
    assert sai == pytest.approx(5 / 6)
    assert thuc != pytest.approx(sai)
    assert sai > thuc                            # lệch theo hướng LẠC QUAN


def test_f2_dung_n_ranked_khi_it_hon_k():
    """Câu chỉ trả 2 bảng thì N=2 kể cả khi hỏi K=10 — mẫu số 4g+N, không 4g+K."""
    rows = [oc(n_gold=1, hits=(1,), n_ranked=2)]
    assert f2_at_k(rows, 10) == pytest.approx(5 / 6)


# ── recall vs hit_rate: khác nhau khi g > 1 ──────────────────────────────────

def test_recall_khac_hit_rate_khi_g_lon_hon_1():
    rows = [oc(n_gold=4, hits=(1, 2), n_ranked=10)]
    assert hit_rate_at_k(rows, 10) == pytest.approx(1.0)   # có ≥1 gold
    assert recall_at_k(rows, 10) == pytest.approx(0.5)     # 2/4
    assert hit_rate_at_k(rows, 10) != recall_at_k(rows, 10)


def test_recall_va_hit_rate_trung_nhau_khi_g_bang_1():
    rows = [oc(n_gold=1, hits=(2,)), oc(2, n_gold=1, hits=())]
    for k in (1, 3, 10):
        assert recall_at_k(rows, k) == pytest.approx(hit_rate_at_k(rows, k))


# ── precision: hai biến thể ──────────────────────────────────────────────────

def test_precision_va_precision_capped():
    rows = [oc(n_gold=2, hits=(1, 2), n_ranked=10)]
    assert precision_at_k(rows, 10) == pytest.approx(2 / 10)
    assert precision_at_k_capped(rows, 10) == pytest.approx(2 / 2)  # trần đạt được


def test_precision_at_1_bang_hit_rate_at_1():
    rows = [oc(n_gold=8, hits=(1,)), oc(2, n_gold=8, hits=(5,))]
    assert precision_at_k(rows, 1) == pytest.approx(hit_rate_at_k(rows, 1))


# ── MRR / nDCG ───────────────────────────────────────────────────────────────

def test_mrr_dung_hang_dau_tien():
    rows = [oc(hits=(3, 7)), oc(2, hits=(1,)), oc(3, hits=())]
    assert mrr(rows) == pytest.approx((1 / 3 + 1 / 1 + 0) / 3)


def test_ndcg_bang_1_khi_gold_chiem_dung_dau_bang():
    rows = [oc(n_gold=3, hits=(1, 2, 3), n_ranked=10)]
    assert ndcg_at_k(rows, 10) == pytest.approx(1.0)


def test_ndcg_chuan_hoa_theo_min_g_k():
    """g=5 nhưng K=2: IDCG chỉ tính 2 vị trí, nên gold ở hạng 1-2 vẫn cho 1,0."""
    rows = [oc(n_gold=5, hits=(1, 2), n_ranked=10)]
    assert ndcg_at_k(rows, 2) == pytest.approx(1.0)


def test_ndcg_giam_khi_gold_tut_hang():
    tren = [oc(n_gold=1, hits=(1,))]
    duoi = [oc(n_gold=1, hits=(5,))]
    assert ndcg_at_k(tren, 10) > ndcg_at_k(duoi, 10)
    assert ndcg_at_k(duoi, 10) == pytest.approx(1 / math.log2(6))


# ── câu KHÔNG đo được phải bị loại khỏi MẪU SỐ, không bị tính là sai ─────────

def test_cau_khong_do_duoc_bi_loai_khoi_mau_so():
    rows = [oc(1, n_gold=1, hits=(1,)),
            oc(2, n_gold=0, measurable=False)]
    assert hit_rate_at_k(rows, 1) == pytest.approx(1.0)      # 1/1, KHÔNG phải 1/2
    mb = metric_block(rows, (1,), n_total=2)
    assert mb.n_measured == 1 and mb.n_total == 2
    assert mb.coverage == pytest.approx(0.5)


def test_candidate_hit_rate_do_tren_tap_day_du():
    rows = [oc(1, in_cand=True, hits=()), oc(2, in_cand=False, hits=())]
    assert candidate_hit_rate(rows) == pytest.approx(0.5)
    assert hit_rate_at_k(rows, 50) == pytest.approx(0.0)     # hai chỉ số ĐỘC LẬP


def test_metric_block_rong_khong_no():
    mb = metric_block([], (1, 10), n_total=0)
    assert mb.n_measured == 0 and mb.coverage == 0.0


# ── phân bố gold ─────────────────────────────────────────────────────────────

def test_gold_size_stats_dem_dung_slice_g1():
    rows = [oc(1, n_gold=1, hits=(1,)), oc(2, n_gold=8, hits=(1,)),
            oc(3, n_gold=1, hits=())]
    st = gold_size_stats(rows)
    assert st["n_exactly_one"] == 2
    assert st["pct_exactly_one"] == pytest.approx(200 / 3)


# ── taxonomy: phủ kín, mỗi câu đúng một nhãn ─────────────────────────────────

def test_taxonomy_phu_kin_va_doi_mot_roi_nhau():
    cases = [
        dict(n_gold=0, n_candidates=5, gold_in_candidates=False, hits_at=()),
        dict(n_gold=2, n_candidates=0, gold_in_candidates=False, hits_at=()),
        dict(n_gold=2, n_candidates=9, gold_in_candidates=False, hits_at=()),
        dict(n_gold=2, n_candidates=9, gold_in_candidates=True, hits_at=(30,)),
        dict(n_gold=2, n_candidates=9, gold_in_candidates=True, hits_at=(3,)),
    ]
    want = [Bucket.NO_GOLD, Bucket.NO_CANDIDATE, Bucket.HARD_FILTER_DROP,
            Bucket.RANK_MISS, Bucket.SUCCESS]
    ds = [classify(qid=i, mode="single", top_k=10, **c)
          for i, c in enumerate(cases)]
    assert [d.bucket for d in ds] == want
    assert sum(summarize(ds).values()) == len(ds)


def test_no_gold_uu_tien_hon_no_candidate_nhung_giu_co():
    d = classify(qid=1, mode="single", n_candidates=0, n_gold=0,
                 gold_in_candidates=False, hits_at=())
    assert d.bucket is Bucket.NO_GOLD
    assert d.also_no_candidate is True          # thông tin KHÔNG bị mất


def test_rerank_miss_tach_khoi_rank_miss():
    d = classify(qid=1, mode="single", n_candidates=9, n_gold=1,
                 gold_in_candidates=True, hits_at=(30,),
                 hits_at_pre_rerank=(4,), top_k=10)
    assert d.bucket is Bucket.RERANK_MISS


def test_runner_phan_biet_vi_tri_truoc_va_sau_rerank():
    """Regression: runner must not feed S2 positions into both inputs."""
    runner_path = (Path(__file__).resolve().parents[1] / "src/text2pandas/"
                   "pipelines/retrieval/evalkit/runner.py")
    tree = ast.parse(runner_path.read_text(encoding="utf-8"))
    calls = [node for node in ast.walk(tree)
             if isinstance(node, ast.Call)
             and isinstance(node.func, ast.Name)
             and node.func.id == "classify"]
    assert len(calls) == 1
    keywords = {kw.arg: kw.value for kw in calls[0].keywords}
    assert isinstance(keywords["hits_at"], ast.Name)
    assert keywords["hits_at"].id == "pos_final"
    assert isinstance(keywords["hits_at_pre_rerank"], ast.Name)
    assert keywords["hits_at_pre_rerank"].id == "pos_rank"


def test_no_gold_reason_duoc_giu():
    d = classify(qid=1, mode="single", n_candidates=5, n_gold=0,
                 gold_in_candidates=False, hits_at=(),
                 no_gold_reason=NoGoldReason.SATURATED)
    assert d.no_gold_reason is NoGoldReason.SATURATED
    assert d.is_measurable is False


# ── D-03 · xoá alias phải tôn trọng biên từ ─────────────────────────────────

@pytest.mark.parametrize("cau,ma,phai_con", [
    ("Chi phí khí GAS của nhà máy", "GAS", "khí"),
    ("Lương của CEO công ty", "CEO", "Lương"),
    ("Doanh thu bán hàng same-store", "SAM", "same"),
    ("Lợi nhuận benefit ròng", "FIT", "benefit"),
])
def test_ma_ngan_khong_bi_xoa_nhu_chuoi_con(cau, ma, phai_con):
    """Mã ≤5 ký tự chỉ được xoá khi có biên từ hai bên."""
    terms = content_terms(cau, drop=(ma,))
    joined = " ".join(terms).lower()
    assert phai_con.lower() in joined, f"{ma} đã ăn mòn {phai_con!r}: {terms}"


def test_ma_dung_le_van_bi_xoa():
    terms = content_terms("Doanh thu thuần của GAS", drop=("GAS",))
    assert "GAS" not in " ".join(terms).upper()
    assert any("thu" in t.lower() for t in terms)


def test_ten_dai_van_xoa_tu_do():
    terms = content_terms("Doanh thu của Hoàng Anh Gia Lai",
                          drop=("Hoàng Anh Gia Lai",))
    assert "hoàng" not in " ".join(terms).lower()


def test_alias_dai_xoa_truoc_alias_ngan():
    """Thứ tự xoá không được làm đổi kết quả — dài trước, ngắn sau."""
    a = content_terms("Doanh thu Hoàng Anh Gia Lai HAG",
                      drop=("HAG", "Hoàng Anh Gia Lai"))
    b = content_terms("Doanh thu Hoàng Anh Gia Lai HAG",
                      drop=("Hoàng Anh Gia Lai", "HAG"))
    assert a == b


def test_khong_cat_chi_tieu_that():
    """`doanh thu`, `giá trị`, `hàng tồn kho` là chỉ tiêu — không được vào STOP."""
    terms = [t.lower() for t in content_terms("Giá trị hàng tồn kho và doanh thu")]
    for phai_co in ("giá", "trị", "hàng", "tồn", "kho", "doanh", "thu"):
        assert phai_co in terms, f"mất {phai_co!r}: {terms}"


# ── preflight · phát hiện môi trường (venv VÀ conda) ────────────────────────
# Bản trước dùng `sys.prefix != sys.base_prefix` làm phép thử "trong môi trường".
# Đúng cho venv, SAI 100% cho conda — conda env là bản Python đầy đủ nên
# sys.prefix == sys.base_prefix. Hệ quả: chặn đúng interpreter đúng của dự án.

def test_dang_dung_khong_co_env_thi_luon_dung():
    from text2pandas.pipelines.retrieval.evalkit.cli import _dang_dung
    assert _dang_dung(None) is True


def test_dang_dung_nhan_ra_conda_du_prefix_bang_base_prefix(monkeypatch):
    """Ca thật: /opt/anaconda3/envs/text2pandas — conda, prefix == base_prefix."""
    import sys as _s
    from text2pandas.pipelines.retrieval.evalkit.cli import _dang_dung
    monkeypatch.setattr(_s, "prefix", "/opt/anaconda3/envs/text2pandas")
    monkeypatch.setattr(_s, "base_prefix", "/opt/anaconda3/envs/text2pandas")
    assert _dang_dung("/opt/anaconda3/envs/text2pandas") is True


def test_dang_dung_bat_duoc_lech_that(monkeypatch):
    import sys as _s
    from text2pandas.pipelines.retrieval.evalkit.cli import _dang_dung
    monkeypatch.setattr(_s, "prefix", "/opt/homebrew/opt/python@3.14/Frameworks/x")
    assert _dang_dung("/opt/anaconda3/envs/text2pandas") is False


def test_active_env_uu_tien_virtualenv_truoc_conda(monkeypatch):
    from text2pandas.pipelines.retrieval.evalkit.cli import _active_env
    monkeypatch.setenv("VIRTUAL_ENV", "/a/venv")
    monkeypatch.setenv("CONDA_PREFIX", "/b/conda")
    assert _active_env() == ("/a/venv", "venv")
    monkeypatch.delenv("VIRTUAL_ENV")
    assert _active_env() == ("/b/conda", "conda env")


def test_preflight_KHONG_fatal_khi_du_goi_du_lech_env(monkeypatch, capsys):
    """Lệch môi trường mà không thiếu gì ⇒ CẢNH BÁO rồi chạy tiếp, KHÔNG chặn.

    Fail-closed thuộc nơi tính đúng bị đe doạ. `yaml` import được thì lần đo
    hợp lệ; chặn nó là biến gợi ý chẩn đoán thành cổng chặn cứng.
    """
    import sys as _s
    from text2pandas.pipelines.retrieval.evalkit.cli import _preflight
    monkeypatch.setenv("CONDA_PREFIX", "/opt/anaconda3/envs/text2pandas")
    monkeypatch.setattr(_s, "prefix", "/somewhere/else")
    _preflight()                       # KHÔNG được raise
    assert "vẫn chạy tiếp" in capsys.readouterr().err


def test_preflight_im_lang_khi_moi_thu_dung(monkeypatch, capsys):
    from text2pandas.pipelines.retrieval.evalkit.cli import _preflight
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    _preflight()
    assert capsys.readouterr().err == ""


def test_preflight_van_chan_khi_thieu_goi(monkeypatch):
    import importlib.util as iu
    from text2pandas.pipelines.retrieval.evalkit.cli import _preflight
    o = iu.find_spec
    monkeypatch.setattr(iu, "find_spec",
                        lambda n, *a, **k: None if n == "yaml" else o(n, *a, **k))
    with pytest.raises(SystemExit, match="thiếu gói"):
        _preflight()


# ── F2 dưới CHÍNH SÁCH N thật ────────────────────────────────────────────────

def test_f2_at_policy_dung_n_rieng_tung_cau():
    """Câu A nộp N=1, câu B nộp N=3. F2 phải dùng đúng N của từng câu."""
    from text2pandas.pipelines.retrieval.evalkit.metrics import f2_at_policy
    rows = [oc(1, n_gold=1, hits=(1,), n_ranked=50),
            oc(2, n_gold=3, hits=(2, 5), n_ranked=50)]
    got = f2_at_policy(rows, {1: 1, 2: 3})
    want = (5 * 1 / (4 * 1 + 1) + 5 * 1 / (4 * 3 + 3)) / 2
    assert got == pytest.approx(want)


def test_f2_at_policy_khac_f2_at_k_co_dinh():
    """Bằng chứng vì sao cần chỉ số này: hai chính sách cho hai con số khác nhau."""
    from text2pandas.pipelines.retrieval.evalkit.metrics import f2_at_policy
    rows = [oc(1, n_gold=1, hits=(1,), n_ranked=50),
            oc(2, n_gold=7, hits=(3, 9), n_ranked=50)]
    assert f2_at_policy(rows, {1: 1, 2: 7}) != pytest.approx(f2_at_k(rows, 10))
    assert f2_at_policy(rows, {1: 1, 2: 7}) != pytest.approx(f2_at_k(rows, 1))


def test_f2_at_policy_khong_vuot_n_ranked():
    from text2pandas.pipelines.retrieval.evalkit.metrics import f2_at_policy
    rows = [oc(1, n_gold=1, hits=(1,), n_ranked=2)]
    assert f2_at_policy(rows, {1: 10}) == pytest.approx(5 / 6)   # N bị kẹp về 2


def test_policy_n_map_khop_rewrite_submission():
    """Khoá công thức `clamp(n_mã × n_năm, 1, 10)` — cùng công thức với
    `tools/rewrite_submission.py._n_tables`. Hai nơi cùng một luật là rủi ro
    trôi dạt; test này tồn tại để bắt nó."""
    from text2pandas.pipelines.retrieval.evalkit.report import policy_n_map
    rows = [
        {"id": 1, "n_targets": 1, "years": [2023]},          # single 1 năm  → 1
        {"id": 2, "n_targets": 1, "years": [2022, 2023]},    # single 2 năm  → 2
        {"id": 3, "n_targets": 4, "years": [2023]},          # screen 4 mã   → 4
        {"id": 4, "n_targets": 7, "years": [2022, 2023]},    # 14 → kẹp 10
        {"id": 5, "n_targets": 0, "years": []},              # rỗng → 1
    ]
    assert policy_n_map(rows) == {1: 1, 2: 2, 3: 4, 4: 10, 5: 1}


# ── chuẩn hoá theo HẠNG · bất biến với kích thước pool ───────────────────────
# Đây là điểm yếu đã ĐO ĐƯỢC của min-max: `basis_hard` giảm pool 470→245 và mua
# hit@1 +0,0080 chỉ nhờ bớt loãng, nhưng phải trả −0,0219 candidate hit rate.
# `_norm_rank` phải lấy được phần lợi đó mà không trả giá gì.

def test_norm_rank_bat_bien_voi_so_ung_vien_khong_khop():
    """Thêm 1.000 ứng viên `raw=0` KHÔNG được đổi điểm của nhóm có khớp."""
    from text2pandas.pipelines.retrieval.rank_s2 import _norm, _norm_rank
    nho = [5.0, 3.0, 1.0]
    to = nho + [0.0] * 1000
    assert _norm_rank(to)[:3] == pytest.approx(_norm_rank(nho))
    # min-max thì KHÔNG bất biến — đó chính là vấn đề.
    assert _norm(to)[:3] != pytest.approx(_norm(nho))


def test_norm_rank_ung_vien_khong_khop_nhan_0():
    from text2pandas.pipelines.retrieval.rank_s2 import _norm_rank
    out = _norm_rank([5.0, 0.0, 2.0])
    assert out[1] == 0.0
    assert out[0] == pytest.approx(1.0)      # khớp tốt nhất luôn được 1,0


def test_norm_rank_tot_nhat_luon_bang_1_bat_ke_pool():
    from text2pandas.pipelines.retrieval.rank_s2 import _norm_rank
    for extra in (0, 10, 3000):
        v = [9.9, 4.0] + [0.0] * extra
        assert _norm_rank(v)[0] == pytest.approx(1.0)


def test_norm_rank_dong_hang_nhan_cung_diem():
    """Nếu không dùng hạng trung bình thì thứ tự CHÈN quyết định điểm."""
    from text2pandas.pipelines.retrieval.rank_s2 import _norm_rank
    out = _norm_rank([3.0, 3.0, 1.0])
    assert out[0] == pytest.approx(out[1])
    assert out[0] > out[2]


def test_norm_rank_giu_thu_tu_tuong_doi():
    from text2pandas.pipelines.retrieval.rank_s2 import _norm_rank
    v = [1.0, 7.0, 3.0]
    out = _norm_rank(v)
    assert out[1] > out[2] > out[0]


def test_norm_rank_rong_va_mot_phan_tu():
    from text2pandas.pipelines.retrieval.rank_s2 import _norm_rank
    assert _norm_rank([]) == []
    assert _norm_rank([0.0]) == [0.0]
    assert _norm_rank([4.0]) == [1.0]


# ── fan-out theo mã · sửa "top-K toàn cục sai đơn vị đo" ─────────────────────
# `screen` có F2@10 = 0,299 — thấp nhất mọi mode — dù cand_hit = 1,000. Recall
# bị chặn bởi HÌNH DẠNG đầu ra, không bởi chất lượng điểm.

def _sc(uid, ticker, score):
    from text2pandas.pipelines.retrieval.filter_s1 import Candidate
    from text2pandas.pipelines.retrieval.rank_s2 import Scored
    c = Candidate(uid, "d", ticker, 2023, None, None, 10, 10, None, None, None)
    return Scored(c, 0.0, False, False, False, score, (), False)


def test_fanout_moi_ma_duoc_phuc_vu_truoc_khi_ma_nao_duoc_lan_hai():
    """Ca thật: 1 mã chiếm hết top-10 trong khi 6 mã khác không có bảng nào."""
    from text2pandas.pipelines.retrieval.rank_s2 import _fanout_by_ticker
    scored = [_sc(f"A{i}", "AAA", 10.0 - i * 0.1) for i in range(8)]
    scored += [_sc("B1", "BBB", 1.0), _sc("C1", "CCC", 0.9)]
    truoc = [s.cand.ticker for s in scored[:3]]
    assert truoc == ["AAA", "AAA", "AAA"]            # top-3 toàn cục: 1 mã
    sau = _fanout_by_ticker(scored, per_k=1, top_k=10)
    assert [s.cand.ticker for s in sau[:3]] == ["AAA", "BBB", "CCC"]


def test_fanout_khong_lam_mat_ung_vien_nao():
    from text2pandas.pipelines.retrieval.rank_s2 import _fanout_by_ticker
    scored = [_sc(f"A{i}", "AAA", 5.0 - i) for i in range(4)]
    scored += [_sc(f"B{i}", "BBB", 4.5 - i) for i in range(3)]
    sau = _fanout_by_ticker(scored, per_k=2, top_k=99)
    assert {s.cand.table_uid for s in sau} == {s.cand.table_uid for s in scored}
    assert len(sau) == len(scored)


def test_fanout_mot_ma_thi_khong_doi_gi():
    """Câu `single` chỉ có một mã ⇒ fan-out phải là no-op, không xáo thứ tự."""
    from text2pandas.pipelines.retrieval.rank_s2 import _fanout_by_ticker
    scored = [_sc(f"A{i}", "AAA", 5.0 - i) for i in range(5)]
    assert _fanout_by_ticker(scored, per_k=1, top_k=10) is scored


def test_fanout_trong_cung_vong_sap_theo_diem():
    from text2pandas.pipelines.retrieval.rank_s2 import _fanout_by_ticker
    scored = [_sc("A1", "AAA", 1.0), _sc("B1", "BBB", 9.0), _sc("C1", "CCC", 5.0)]
    sau = _fanout_by_ticker(scored, per_k=1, top_k=10)
    assert [s.cand.table_uid for s in sau[:3]] == ["B1", "C1", "A1"]


def test_fanout_tat_dinh():
    """Cùng điểm ⇒ tie-break `table_uid` ⇒ kết quả tái lập."""
    from text2pandas.pipelines.retrieval.rank_s2 import _fanout_by_ticker
    a = [_sc("Z1", "ZZZ", 1.0), _sc("A1", "AAA", 1.0)]
    b = [_sc("A1", "AAA", 1.0), _sc("Z1", "ZZZ", 1.0)]
    assert ([s.cand.table_uid for s in _fanout_by_ticker(a, 1, 9)]
            == [s.cand.table_uid for s in _fanout_by_ticker(b, 1, 9)])


# ── cfg_sha phải băm ĐỘ LỆCH, không băm toàn bộ dict ─────────────────────────
# Lỗi đã xảy ra: thêm `norm="minmax"` + `per_ticker_k=None` (đúng bằng hành vi
# cũ, không đổi một con số) mà 4 lần chạy đủ 1.012 câu bị mồ côi.

def test_sha_bo_qua_tag_va_budget():
    from text2pandas.pipelines.retrieval.evalkit.runner import EvalConfig
    a = EvalConfig(tag="base", budget_s=35.0)
    b = EvalConfig(tag="khac_hoan_toan", budget_s=300.0)
    assert a.sha == b.sha, "tag/budget_s không được ảnh hưởng ngữ nghĩa phép đo"


def test_sha_doi_khi_ngu_nghia_doi():
    from text2pandas.pipelines.retrieval.evalkit.runner import EvalConfig
    assert EvalConfig().sha != EvalConfig(norm="rank").sha
    assert EvalConfig().sha != EvalConfig(per_ticker_k=2).sha
    assert EvalConfig().sha != EvalConfig(basis_mode="hard").sha


def test_sha_KHONG_doi_khi_dat_lai_dung_gia_tri_mac_dinh():
    """Khai tường minh giá trị mặc định phải cho CÙNG sha."""
    from text2pandas.pipelines.retrieval.evalkit.runner import EvalConfig
    assert EvalConfig().sha == EvalConfig(norm="minmax", per_ticker_k=None).sha


def test_deviations_chi_liet_ke_phan_lech():
    from text2pandas.pipelines.retrieval.evalkit.runner import EvalConfig
    d = EvalConfig(tag="x", norm="rank", per_ticker_k=2).deviations
    assert d == {"norm": "rank", "per_ticker_k": 2}
    assert EvalConfig().deviations == {}


# ── maxnorm · bản thứ ba, sau khi `rank` bị dữ liệu bác bỏ (−0,17 hit@1) ─────

def test_maxnorm_bat_bien_voi_ung_vien_khong_khop():
    from text2pandas.pipelines.retrieval.rank_s2 import _norm_max
    nho = [5.0, 4.9, 1.0]
    to = nho + [0.0] * 2000
    assert _norm_max(to)[:3] == pytest.approx(_norm_max(nho))


def test_maxnorm_GIU_ty_le_do_lon_con_rank_thi_NEN():
    """Cơ chế `rank` thất bại: nó nén ĐỈNH phân bố xuống dưới mức bonus.

    Phải dựng ca THẬT mới thấy: median 470 ứng viên, phần lớn khớp BM25 ở mức
    thấp. Với 3 ứng viên thì `rank` giãn rộng (1,00/0,67/0,33) và hiện tượng nén
    không xuất hiện — bản test đầu của tôi dùng đúng ca đó nên chứng minh sai.

    Ở đây: 1 bảng khớp vượt trội (10,0), 1 bảng khá (9,0), rồi 198 bảng lẹt đẹt.
    Đó là hình dạng phân bố BM25 thật.
    """
    from text2pandas.pipelines.retrieval.rank_s2 import _norm_max, _norm_rank
    v = [10.0, 9.0] + [0.5] * 198
    mx, rk = _norm_max(v), _norm_rank(v)

    # maxnorm: khoảng cách hạng-1 ↔ hạng-2 là 0,10 — CÙNG BẬC với bonus, nên
    # BM25 còn quyền quyết định.
    assert mx[0] - mx[1] == pytest.approx(0.10, abs=1e-6)
    assert mx[0] - mx[2] == pytest.approx(0.95, abs=1e-6)

    # rank: khoảng cách hạng-1 ↔ hạng-2 chỉ 1/200 = 0,005 — NHỎ HƠN bonus
    # period (0,35) tới 70 lần. Bất kỳ bonus nào cũng lật được thứ hạng.
    assert rk[0] - rk[1] == pytest.approx(1 / 200, abs=1e-9)
    assert (mx[0] - mx[1]) / (rk[0] - rk[1]) > 15


def test_maxnorm_tot_nhat_bang_1_khong_khop_bang_0():
    from text2pandas.pipelines.retrieval.rank_s2 import _norm_max
    out = _norm_max([3.0, 0.0, 1.5])
    assert out == pytest.approx([1.0, 0.0, 0.5])


def test_maxnorm_toan_khong_thi_tra_0():
    from text2pandas.pipelines.retrieval.rank_s2 import _norm_max
    assert _norm_max([0.0, 0.0]) == [0.0, 0.0]
    assert _norm_max([]) == []


def test_ba_cach_chuan_hoa_deu_dang_ky():
    from text2pandas.pipelines.retrieval.rank_s2 import _NORMS
    assert set(_NORMS) == {"minmax", "rank", "maxnorm"}
