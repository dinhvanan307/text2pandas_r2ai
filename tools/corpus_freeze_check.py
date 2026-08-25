#!/usr/bin/env python3
"""P3 · corpus RC2 có ĐÚNG là corpus RC1 không — trả lời bằng băm, không bằng niềm tin.

Bước `freeze_input` trong `configs/execution_sequence_v1.yaml` đòi hai điều:

    corpus_content_hash ổn định giữa hai lần đọc
    uid_namespace_id đúng hằng số đóng băng (AMD-04)

Trước công cụ này, cả hai **không đo được bằng thứ gì có sẵn**. `dp-env-check`
chỉ băm (đường dẫn, kích thước) — nó bắt được tệp thêm/mất, nhưng KHÔNG bắt
được nội dung một tệp bị sửa mà giữ nguyên kích thước. Và `corpus_content_hash`
thì chỉ tồn tại sau khi `snapshot` chạy, tức là sau khi đã bắt đầu build.

Công cụ này chạy TRƯỚC build, chỉ đọc, và trả lời ba câu:

  1. cây corpus hôm nay có khớp từng byte với manifest RC1 không
  2. `corpus_content_hash` (chỉ 1.973 tệp báo cáo — thứ ĐI VÀO `build_id`)
  3. `uid_namespace_id` có đúng hằng số đóng băng của AMD-04 không

Dùng CHÍNH `data_pipeline.manifest` để tính, không cài lại thuật toán. Một bản
cài lại sẽ trôi khỏi bản thật đúng vào lúc nó cần chính xác nhất.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from text2pandas.pipelines.a6.manifest import (                          # noqa: E402
    RC1_UID_NAMESPACE_ID, build_manifest, compute_corpus_id, is_corpus_report,
)


def _baseline_content_hash(files: list[dict]) -> tuple[str, int, int]:
    """Suy `corpus_content_hash` của RC1 TỪ manifest RC1 đã lưu.

    RC1 được dựng trước AMD-04 nên manifest của nó không có trường này. Nhưng
    nó có sha256 của TỪNG tệp, nên giá trị suy ra là chính xác chứ không phải
    xấp xỉ — và đó là đường duy nhất để có mốc so mà không phải dựng lại RC1.
    """
    class _E:
        __slots__ = ("rel_path", "sha256", "n_bytes")

        def __init__(self, r, s, b):
            self.rel_path, self.sha256, self.n_bytes = r, s, b

    content = [_E(f["rel_path"], f["sha256"], f["bytes"]) for f in files
               if is_corpus_report(f["rel_path"])]
    return (compute_corpus_id(content), len(content),
            sum(e.n_bytes for e in content))


def _dup_split(man) -> dict:
    """Tach trung-noi-dung thanh hai quan the: bao cao, va phan con lai."""
    from collections import defaultdict

    def count(entries):
        by = defaultdict(list)
        for e in entries:
            by[e.sha256].append(e.rel_path)
        groups = {h: sorted(v) for h, v in by.items() if len(v) > 1}
        return {"n_groups": len(groups),
                "n_redundant_files": sum(len(v) - 1 for v in groups.values()),
                "groups": [v for v in sorted(groups.values())][:10]}

    content = [e for e in man.files if is_corpus_report(e.rel_path)]
    other = [e for e in man.files if not is_corpus_report(e.rel_path)]
    d_content, d_other = count(content), count(other)
    d_other.pop("groups", None)          # hang nghin duong dan cache, vo dung
    return {
        "content_reports": d_content,
        "non_content": d_other,
        "note": ("`manifest.n_duplicate_files` dem tren CA CAY nen bi `.cache` "
                 "cua HuggingFace lam phong len. Con so mo ta CORPUS la "
                 "`content_reports`."),
    }


def _uid_namespace_from_config(cfg: Path) -> str | None:
    try:
        import yaml
        d = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception:
        return None
    return ((d.get("corpus") or {}).get("uid_namespace_id")) or None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="data/raw/btc",
                    help="CORPUS.parent — gốc mà `cmd_snapshot` quét")
    ap.add_argument("--baseline", default="artifacts/runs/a6/bronze/manifest.json",
                    help="manifest RC1 dùng làm mốc")
    ap.add_argument("--config", default="configs/vifinqa_silver_v1.yaml")
    ap.add_argument("--dataset", default="AIGuruTinix/ViFinQA")
    ap.add_argument("--revision", default="0450088ab22ec946f04f097586967ca405955b3b")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    root, base = Path(a.root), Path(a.baseline)
    if not root.is_dir():
        print(f"MISSING_REQUIRED_ARTIFACT: khong thay corpus root {root}", file=sys.stderr)
        return 3

    ns_cfg = _uid_namespace_from_config(Path(a.config))
    man = build_manifest(root, a.dataset, a.revision, uid_namespace_id=ns_cfg)

    rep: dict = {
        "check": "P3 · freeze_input — corpus RC2 vs corpus RC1",
        "corpus_root": str(root),
        "config": str(a.config),
        "measured": {
            "n_files": man.n_files, "n_bytes": man.n_bytes,
            "n_reports": man.n_reports,
            "uid_namespace_id": man.uid_namespace_id,
            "corpus_content_hash": man.corpus_content_hash,
            "n_content_files": man.n_content_files,
            "n_content_bytes": man.n_content_bytes,
            "n_duplicate_files": man.n_duplicate_files,
        },
        # RC2-029 · trung noi dung phai tach theo QUAN THE.
        #
        # `manifest.n_duplicate_files` dem tren CA CAY: 1.977 tep du / 3 nhom.
        # Nhung 1.975 tep trong so do nam o `.cache/huggingface/**` — mot nhom
        # duy nhat gom 1.976 tep giong het nhau (lock/metadata cua HuggingFace).
        # Su that ve CORPUS la: 2 tep du / 2 nhom (SSH 2024 va 2025,
        # `explanations_1` ≡ `explanations_2`).
        #
        # Mot con so trong nhu da do nhung mo ta sai quan the thi nguy hiem hon
        # khong do gi: nguoi doc se tin no.
        "duplicates": _dup_split(man),
        "findings": [], "verdict": "PASS",
    }

    def bad(msg: str):
        rep["findings"].append(msg)
        rep["verdict"] = "FAIL"

    # ── AMD-04 · hạt giống UID phải là hằng số đóng băng ─────────────────
    rep["uid_namespace_frozen_constant"] = RC1_UID_NAMESPACE_ID
    rep["uid_namespace_from_config"] = ns_cfg
    if ns_cfg != RC1_UID_NAMESPACE_ID:
        bad(f"config khai uid_namespace_id={ns_cfg} != hang so dong bang "
            f"{RC1_UID_NAMESPACE_ID} — doi gia tri nay la doi MOI observation_uid")

    # ── so từng byte với manifest RC1 ────────────────────────────────────
    if not base.is_file():
        rep["baseline"] = None
        rep["findings"].append(f"NOT_VERIFIED: khong thay manifest moc {base}")
        rep["verdict"] = "NOT_VERIFIED"
    else:
        bfiles = json.loads(base.read_text(encoding="utf-8")).get("files") or []
        bmap = {f["rel_path"]: f for f in bfiles}
        cmap = {e.rel_path: e for e in man.files}
        added = sorted(set(cmap) - set(bmap))
        removed = sorted(set(bmap) - set(cmap))
        changed = sorted(r for r in set(bmap) & set(cmap)
                         if bmap[r]["sha256"] != cmap[r].sha256)
        bhash, bn, bbytes = _baseline_content_hash(bfiles)
        rep["baseline"] = {
            "path": str(base), "n_files": len(bfiles),
            "corpus_content_hash_derived": bhash,
            "n_content_files": bn, "n_content_bytes": bbytes,
            "note": ("RC1 dung truoc AMD-04 nen manifest cua no khong co "
                     "corpus_content_hash; gia tri o day SUY RA tu sha256 tung "
                     "tep trong chinh manifest do."),
        }
        rep["diff_vs_baseline"] = {
            "n_added": len(added), "n_removed": len(removed),
            "n_changed": len(changed),
            "added": added[:20], "removed": removed[:20], "changed": changed[:20],
        }
        for label, lst in (("them", added), ("mat", removed), ("doi noi dung", changed)):
            if lst:
                bad(f"corpus lech mo moc RC1: {len(lst)} tep {label} — vd {lst[:3]}")
        if man.corpus_content_hash != bhash:
            bad(f"corpus_content_hash lech: do={man.corpus_content_hash} "
                f"moc={bhash}")

    if a.out:
        Path(a.out).parent.mkdir(parents=True, exist_ok=True)
        Path(a.out).write_text(json.dumps(rep, ensure_ascii=False, indent=1),
                               encoding="utf-8")

    m = rep["measured"]
    print("╔═══════ P3 · corpus freeze ═══════╗")
    print(f"  goc                 {root}")
    print(f"  tep quet            {m['n_files']:,}   bao cao .txt {m['n_reports']:,}")
    print(f"  noi dung (content)  {m['n_content_files']:,} tep · "
          f"{m['n_content_bytes']:,} bytes")
    print(f"  uid_namespace_id    {m['uid_namespace_id']}")
    print(f"  corpus_content_hash {m['corpus_content_hash']}")
    dc = rep["duplicates"]["content_reports"]
    print(f"  trung noi dung      bao cao: {dc['n_redundant_files']} tep du "
          f"/ {dc['n_groups']} nhom   (ca cay: {m['n_duplicate_files']} — "
          f"phan chenh la .cache, KHONG phai corpus)")
    if rep.get("baseline"):
        d = rep["diff_vs_baseline"]
        print(f"  vs moc RC1          +{d['n_added']} / -{d['n_removed']} / "
              f"~{d['n_changed']} doi noi dung")
    if rep["verdict"] == "PASS":
        print("\n✓ corpus RC2 KHOP tung byte voi corpus RC1")
        return 0
    print(f"\n✗ {rep['verdict']}", file=sys.stderr)
    for f in rep["findings"]:
        print(f"  · {f}", file=sys.stderr)
    return 3


if __name__ == "__main__":
    sys.exit(main())
