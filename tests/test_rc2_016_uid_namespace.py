"""RC2-016 / AMD-04 · tách `uid_namespace_id` khỏi `corpus_content_hash`.

Khiếm khuyết gốc: `cmd_snapshot` truyền `CORPUS.parent` vào `build_manifest`,
còn `build_manifest` chỉ bỏ tệp có **TÊN** bắt đầu bằng `.` — nên toàn bộ cây
`.cache/` (3.954 tệp) đi vào `corpus_id`. Mà `corpus_id` là hạt giống của
`make_uid()`, nên một tệp cache đổi là mọi `observation_uid` đổi theo.

Bộ test này khoá ba tính chất:

1. Nhiễu ngoài corpus (`.cache/…`) **không** làm đổi `uid_namespace_id`
   lẫn `corpus_content_hash`.
2. Sửa một tệp báo cáo thật **có** làm đổi `corpus_content_hash`.
3. `document_uid` sinh từ `uid_namespace_id` đóng băng **trùng** RC1.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.pipelines.a6.manifest import (  # noqa: E402
    RC1_UID_NAMESPACE_ID, build_manifest, is_corpus_report,
)


def _corpus(tmp: Path, *, n_reports: int = 2, cache_files: int = 0) -> Path:
    """Dựng cây giống thật: `<root>/financial_statements/...` + rác cùng cây."""
    root = tmp / "vifinqa"
    fs = root / "financial_statements"
    for i in range(n_reports):
        d = fs / "AAA" / f"20{20+i}" / f"AAA_financial_statements_20{20+i}_separate"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"AAA_financial_statements_20{20+i}_separate_extracted.txt").write_text(
            f"<table><tr><td>Doanh thu</td><td>{i}00</td></tr></table>",
            encoding="utf-8")
    # nhiễu: cache của HuggingFace nằm CÙNG CÂY nhưng không thuộc corpus
    for j in range(cache_files):
        c = root / ".cache" / "huggingface" / "download"
        c.mkdir(parents=True, exist_ok=True)
        (c / f"blob{j}.lock").write_text(f"lock{j}", encoding="utf-8")
    # nhiễu khác cũng nằm cùng cây
    (root / "README.md").write_text("readme", encoding="utf-8")
    return root


def _mf(root: Path):
    return build_manifest(root, "vifinqa", "rev0",
                          uid_namespace_id=RC1_UID_NAMESPACE_ID)


# ── 1 · nhiễu ngoài corpus không được đụng tới định danh ──────────────────

def test_them_tep_cache_KHONG_doi_uid_namespace(tmp_path):
    a = _mf(_corpus(tmp_path / "a", cache_files=0))
    b = _mf(_corpus(tmp_path / "b", cache_files=25))
    assert a.uid_namespace_id == b.uid_namespace_id == RC1_UID_NAMESPACE_ID


def test_them_tep_cache_KHONG_doi_corpus_content_hash(tmp_path):
    """Đây là tính chất bản cũ KHÔNG có: cache đổi -> corpus_id đổi -> build_id
    đổi -> C0 đỏ với lý do gây hiểu nhầm."""
    a = _mf(_corpus(tmp_path / "a", cache_files=0))
    b = _mf(_corpus(tmp_path / "b", cache_files=40))
    assert a.corpus_content_hash == b.corpus_content_hash
    assert a.n_content_files == b.n_content_files == 2


def test_corpus_content_hash_chi_bam_tep_bao_cao(tmp_path):
    m = _mf(_corpus(tmp_path / "a", n_reports=3, cache_files=10))
    assert m.n_content_files == 3
    assert m.n_files > m.n_content_files, "n_files vẫn đếm cả tệp ngoài corpus"


# ── 2 · đổi corpus thật thì PHẢI đổi ──────────────────────────────────────

def test_sua_mot_bao_cao_thi_corpus_content_hash_DOI(tmp_path):
    root = _corpus(tmp_path / "a", n_reports=2)
    before = _mf(root).corpus_content_hash
    tgt = next(root.rglob("*_extracted.txt"))
    tgt.write_text(tgt.read_text(encoding="utf-8") + "<!-- đổi -->", encoding="utf-8")
    after = _mf(root).corpus_content_hash
    assert before != after, "đổi nội dung corpus mà hash không đổi là hỏng"


def test_them_mot_bao_cao_thi_corpus_content_hash_DOI(tmp_path):
    root = _corpus(tmp_path / "a", n_reports=2)
    before = _mf(root)
    d = root / "financial_statements" / "BBB" / "2021" / "BBB_financial_statements_2021_separate"
    d.mkdir(parents=True, exist_ok=True)
    (d / "BBB_financial_statements_2021_separate_extracted.txt").write_text(
        "<table><tr><td>x</td><td>1</td></tr></table>", encoding="utf-8")
    after = _mf(root)
    assert before.corpus_content_hash != after.corpus_content_hash
    assert after.n_content_files == before.n_content_files + 1


# ── 3 · UID phải trùng RC1 ────────────────────────────────────────────────

def test_document_uid_sinh_tu_namespace_dong_bang(tmp_path):
    """`document_uid = make_uid(uid_namespace_id, rel)`. Namespace đóng băng
    nên UID tái lập được bất kể cây quét có bao nhiêu tệp rác."""
    from text2pandas.pipelines.a6.models import make_uid
    rel = "financial_statements/AAA/2020/x/x_extracted.txt"
    u1 = make_uid(RC1_UID_NAMESPACE_ID, rel)
    u2 = make_uid(_mf(_corpus(tmp_path / "a", cache_files=99)).uid_namespace_id, rel)
    assert u1 == u2


def test_namespace_RC1_dung_gia_tri_da_cong_bo():
    """Giá trị này là corpus_id của bản dựng RC1 `b927c3e8f90aed74`. Đổi nó là
    đổi mọi observation_uid — phải là quyết định có contract, không phải refactor."""
    assert RC1_UID_NAMESPACE_ID == (
        "sha256:ca033190f2e9e99f8384bf59749484b0668c573e0a84e02a055d173d99de0cb9")


def test_is_corpus_report_phan_biet_dung(tmp_path):
    assert is_corpus_report("financial_statements/A/2020/x/x_extracted.txt")
    assert not is_corpus_report(".cache/huggingface/blob.lock")
    assert not is_corpus_report("README.md")
    assert not is_corpus_report("questions/questions.jsonl")
    assert not is_corpus_report("financial_statements/A/2020/x/notes.txt")


# ── 4 · manifest phải KHAI cả hai, để hậu kiểm ────────────────────────────

def test_manifest_json_khai_ca_hai_id(tmp_path):
    j = _mf(_corpus(tmp_path / "a", cache_files=5)).to_json()
    for k in ("uid_namespace_id", "corpus_content_hash", "n_content_files",
              "n_content_bytes", "identity_note"):
        assert k in j, f"manifest thiếu {k}"
    assert j["corpus_id"] == j["uid_namespace_id"], "giữ tương thích ngược"


def test_config_khai_uid_namespace_id():
    import yaml
    cfg = yaml.safe_load(
        (ROOT / "configs" / "vifinqa_silver_v1.yaml").read_text(encoding="utf-8"))
    assert (cfg.get("corpus") or {}).get("uid_namespace_id") == RC1_UID_NAMESPACE_ID


def test_AMD04_thay_the_AMD03_trong_hop_dong():
    """Quyết định đổi phương án phải nằm trong hợp đồng, nêu rõ nó thay AMD-03
    và vì sao — không được im lặng đổi hướng."""
    import yaml
    d = yaml.safe_load(
        (ROOT / "configs" / "rc2_contracts_v1.yaml").read_text(encoding="utf-8"))
    amd = {a["id"]: a for a in d["amendments"]}
    assert "AMD-04" in amd, "chưa khoá quyết định RC2-016 phương án C"
    a = amd["AMD-04"]
    assert a["supersedes"] == "AMD-03"
    assert a["decision"] == "TACH_uid_namespace_id_VA_corpus_content_hash"
    for k in ("supersede_reason", "design", "rejected_alternatives",
              "implemented_by", "tests"):
        assert a.get(k), f"AMD-04 thiếu {k}"
    assert {r["id"] for r in a["rejected_alternatives"]} == {"A", "B"}
