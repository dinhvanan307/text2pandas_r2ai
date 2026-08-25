"""Cổng H0 (docs/102 §9). KHÔNG skip — mọi test ở đây phải chạy thật.

Chúng dùng artifact nhỏ (JSONL/JSON/ZIP) và một SQLite tổng hợp cho cổng định
danh, nên không phụ thuộc `work.db` 4,2 GB.
"""
from __future__ import annotations

import json
import sqlite3
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from execution.a6_identity import A6IdentityError, kiem_dinh_danh  # noqa: E402

H0 = ROOT / "artifacts/execution/h0"
CAU_HINH = ROOT / "configs/execution/a6_identity.yaml"
REC = ROOT / "data/curated/dev-legacy/answer_a6/records_a6.jsonl"
PX = H0 / "unit_conflict_adjudication.jsonl"
C1R = ROOT / "artifacts/submissions/legacy/submission_C1R_LOCAL.zip"
NEN = ROOT / "artifacts/submissions/legacy/submission_P0G2.zip"

TRUONG = ("build_id", "corpus_id", "readiness_policy_version", "release_label", "status")


def _cau_hinh() -> dict:
    d = {}
    for line in CAU_HINH.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if ":" in line:
            k, _, v = line.partition(":")
            d[k.strip()] = v.strip()
    return d


def _db(tmp_path: Path, meta: dict | None, ten="w.db") -> Path:
    p = tmp_path / ten
    con = sqlite3.connect(p)
    if meta is not None:
        con.execute("CREATE TABLE build_meta(key TEXT, value TEXT)")
        con.executemany("INSERT INTO build_meta VALUES(?,?)", list(meta.items()))
    else:
        con.execute("CREATE TABLE khac(x INT)")
    con.commit(); con.close()
    return p


# ── G8 · cổng định danh A6 ────────────────────────────────────────────────
def test_g8_dung_build_thi_pass(tmp_path):
    assert kiem_dinh_danh(_db(tmp_path, _cau_hinh()), in_log=lambda *_: None)


def test_g8_sai_build_id_thi_fail(tmp_path):
    m = _cau_hinh(); m["build_id"] = "deadbeefdeadbeef"
    with pytest.raises(A6IdentityError, match="build_id"):
        kiem_dinh_danh(_db(tmp_path, m), in_log=lambda *_: None)


@pytest.mark.parametrize("thieu", TRUONG)
def test_g8_thieu_metadata_thi_fail(tmp_path, thieu):
    m = {k: v for k, v in _cau_hinh().items() if k != thieu}
    with pytest.raises(A6IdentityError, match=thieu):
        kiem_dinh_danh(_db(tmp_path, m), in_log=lambda *_: None)


def test_g8_sai_readiness_policy_thi_fail(tmp_path):
    m = _cau_hinh(); m["readiness_policy_version"] = "9.9"
    with pytest.raises(A6IdentityError, match="readiness_policy_version"):
        kiem_dinh_danh(_db(tmp_path, m), in_log=lambda *_: None)


def test_g8_tro_nham_db_thi_fail_truoc_khi_resolve(tmp_path):
    with pytest.raises(A6IdentityError, match="build_meta"):
        kiem_dinh_danh(_db(tmp_path, None), in_log=lambda *_: None)


def test_g8_thieu_db_thi_fail(tmp_path):
    with pytest.raises(A6IdentityError, match="THIEU DB"):
        kiem_dinh_danh(tmp_path / "khong-ton-tai.db", in_log=lambda *_: None)


# ── G9 · phân xử đơn vị: không còn trạng thái treo ─────────────────────────
HOP_LE = {"CONFIRMED_A6", "A6_DEFECT", "FALLBACK_REQUIRED", "UNRESOLVED_BLOCKED"}


def _phan_xu() -> list[dict]:
    return [json.loads(l) for l in PX.open(encoding="utf-8") if l.strip()]


def test_g9_moi_conflict_co_trang_thai_cuoi_hop_le():
    rs = _phan_xu()
    assert rs, "chưa có bản phân xử"
    assert all(r["final_status"] in HOP_LE for r in rs)
    assert not any(r.get("final_status") == "KEEP_A6_FLAGGED" for r in rs)


def test_g9_a6_defect_phai_co_scale_cuoi_va_ly_do():
    for r in _phan_xu():
        if r["final_status"] == "A6_DEFECT":
            assert r["final_scale_exponent"] is not None
            assert r["decision_reason"] and r["evidence_found"]


def _records() -> list[dict]:
    return [json.loads(l) for l in REC.open(encoding="utf-8") if l.strip()]


def test_g9_khong_con_primary_a6_mang_scale_uncertain():
    xau = [r["qid"] for r in _records()
           if r["nguon"] == "PRIMARY_A6" and (r.get("provenance") or {}).get("scale_UNCERTAIN")]
    assert xau == []


def test_g9_observation_bi_chan_khong_duoc_dung():
    chan = {r["observation_uid"] for r in _phan_xu()
            if r["final_status"] in ("UNRESOLVED_BLOCKED", "FALLBACK_REQUIRED")}
    dung = {(r.get("provenance") or {}).get("observation_uid") for r in _records()
            if r["nguon"] == "PRIMARY_A6"}
    assert not (chan & dung)


# ── G10 · regression q42 ──────────────────────────────────────────────────
def test_g10_q42_duoc_phan_xu_la_a6_defect():
    r = next(x for x in _phan_xu() if x["qid"] == 42)
    assert r["final_status"] == "A6_DEFECT"
    assert r["a6_scale_exponent"] == 0 and r["final_scale_exponent"] == 6
    assert "triệu" in (r["raw_col_path"] or "").lower()


def test_g10_q42_dap_an_dung_don_vi_trieu_dong():
    """Cột in 'Triệu đồng', ô in 1.855.837, câu hỏi hỏi 'triệu đồng'
    ⇒ đáp án phải là chính con số đó, không phải 1,855837."""
    s = {r["id"]: r for r in json.loads(zipfile.ZipFile(C1R).read("submission.json"))}
    assert s[42]["answer"] == pytest.approx(1_855_837.0, rel=1e-9)


def test_g10_khong_tai_dien_lech_10_mu_6():
    s = {r["id"]: r for r in json.loads(zipfile.ZipFile(C1R).read("submission.json"))}
    for r in _phan_xu():
        if r["final_status"] == "A6_DEFECT" and r["qid"] in s:
            a = s[r["qid"]]["answer"]
            if a is not None:
                assert abs(a) > 1e-6, f"q{r['qid']} vẫn nhỏ bất thường sau khi sửa scale"


# ── G4 · hợp đồng Retrieval vẫn FREEZE ────────────────────────────────────
def test_g4_retrieval_contract_khong_doi():
    g = {r["id"]: r for r in json.loads(zipfile.ZipFile(NEN).read("submission.json"))}
    c = {r["id"]: r for r in json.loads(zipfile.ZipFile(C1R).read("submission.json"))}
    assert set(g) == set(c)
    for f in ("relevant_tables", "relevant_docs", "question"):
        assert all(g[q].get(f) == c[q].get(f) for q in g), f


# ── G2/G3 · định dạng + replay ────────────────────────────────────────────
def test_g2_submission_du_va_unique():
    s = json.loads(zipfile.ZipFile(C1R).read("submission.json"))
    ids = [r["id"] for r in s]
    assert len(s) == 1012 and len(set(ids)) == 1012 and sorted(ids) == list(range(1, 1013))


def test_g2_khong_co_duong_dan_khong_an_toan():
    for n in zipfile.ZipFile(C1R).namelist():
        assert not n.startswith("/") and ".." not in n.split("/")


def test_g3_replay_toan_bo_query_chay_va_khop_answer():
    pd = pytest.importorskip("pandas")
    import io
    z = zipfile.ZipFile(C1R)
    B = {"float": float, "max": max, "min": min, "abs": abs, "sum": sum, "round": round, "len": len}
    cache, do = {}, []
    for r in json.loads(z.read("submission.json")):
        ev = r.get("evidence") or []
        if not ev or not r.get("pandas_query") or r.get("answer") is None:
            continue
        env = dict(B)
        for e in ev:
            p = e["csv_path"]
            if p not in cache:
                if len(cache) > 150:
                    cache.clear()
                cache[p] = pd.read_csv(io.BytesIO(z.read(p)))
            env[e["variable"]] = cache[p]
        try:
            v = eval(r["pandas_query"], {"__builtins__": {}}, env)
            if abs(v - r["answer"]) > max(1e-9, abs(r["answer"]) * 1e-9):
                do.append(r["id"])
        except Exception:
            do.append(r["id"])
    assert do == []


# ── G5 · đóng gói tất định (đọc báo cáo đã sinh) ──────────────────────────
def test_g5_full_zip_sha256_tat_dinh():
    rep = json.loads((H0 / "determinism_report_v2.json").read_text(encoding="utf-8"))
    assert rep["deterministic_full_zip_sha256"] is True
    assert rep["run_1"]["zip_sha256"] == rep["run_2"]["zip_sha256"]
    assert rep["run_1"]["path"] != rep["run_2"]["path"], "phải build sang HAI đường dẫn khác nhau"
