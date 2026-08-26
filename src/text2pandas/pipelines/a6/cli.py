"""CLI của data pipeline — chạy từng stage hoặc toàn bộ.

    python -m text2pandas.pipelines.a6.cli snapshot
    python -m text2pandas.pipelines.a6.cli catalog  [--offset N --limit M]
    python -m text2pandas.pipelines.a6.cli silver   [--offset N --limit M]
    python -m text2pandas.pipelines.a6.cli quality
    python -m text2pandas.pipelines.a6.cli publish

Mọi stage đều **resume được**: tiến trình nền trên máy chạy bị giết sau khoảng
45 giây, nên chạy một mạch toàn corpus là không khả thi. `--offset/--limit`
biến ràng buộc đó thành thuộc tính kiến trúc có ích.

Build diễn ra ở đĩa CỤC BỘ rồi copy sang thư mục dự án — SQLite không khoá
được tệp trên FUSE mount và ném `disk I/O error` ngay lệnh đầu.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

from text2pandas.infrastructure.paths import ProjectPaths

ROOT = Path(__file__).resolve().parents[4]
PROJECT_PATHS = ProjectPaths.from_repo_root(ROOT)

# ── SAFETY · RC2-017 · `CONFIG=` / `INPUT=` phải THẬT SỰ tới được pipeline ──
#
# `make dp-build CONFIG= INPUT= OUTPUT=` là hợp đồng §3.2 của RC-00, và
# `build_runner` kiểm cả ba trong preflight rồi ghi vào `build_invocation.json`
# — nhưng nó chạy `python -m text2pandas.pipelines.a6.cli <stage>` mà KHÔNG truyền gì
# xuống, còn `cli.py` thì suy mọi đường dẫn từ `ROOT`. Kết quả: người vận hành
# truyền `INPUT=` trỏ sang corpus khác, preflight xanh, log ghi đúng đường dẫn
# đó, và build vẫn quét corpus mặc định.
#
# Đây là lỗi im lặng đúng nghĩa: không có thông báo nào sai, chỉ có một tham số
# không có tác dụng. Sửa bằng biến môi trường vì đó là kênh mà `build_runner`
# đã dùng cho `DATA_PIPELINE_SCRATCH`.
def _env_path(name: str, default: Path) -> Path:
    v = os.environ.get(name)
    return Path(v).expanduser().resolve() if v else default


CORPUS = _env_path(
    "DATA_PIPELINE_CORPUS",
    PROJECT_PATHS.raw_btc / "financial_statements")
CONFIG_PATH = _env_path("DATA_PIPELINE_CONFIG",
                        ROOT / "configs" / "vifinqa_silver_v1.yaml")
# ── SAFETY · RC2-005 · thư mục làm việc không được ngầm định ──────────────
#
# `DATA_PIPELINE_SCRATCH` được `build_runner` đặt cho ba stage của nó, nhưng
# `quality`/`publish` chạy bằng lệnh riêng. Không đặt lại biến thì chúng lặng
# lẽ đọc `/tmp/dp_work` — có thể là RÁC CỦA MỘT BUILD KHÁC, và `publish` sẽ
# đóng dấu một `silver.sqlite` không thuộc build đang chạy.
#
# Mặc định vẫn giữ để không phá lệnh cũ, nhưng nay nó KHAI RA khi rơi về mặc
# định, và `_work()` từ chối đọc tệp trong một scratch không do lần chạy này
# tạo (xem `assert_scratch_explicit`).
_SCRATCH_EXPLICIT = "DATA_PIPELINE_SCRATCH" in os.environ
SCRATCH = Path(os.environ.get("DATA_PIPELINE_SCRATCH", "/tmp/dp_work"))
BRONZE_OUT = _env_path("DATA_PIPELINE_BRONZE",
                       PROJECT_PATHS.artifact_root / "runs" / "a6" / "bronze"
                       / "catalog_v2.sqlite")
SILVER_DIR = _env_path("DATA_PIPELINE_SILVER_DIR",
                       PROJECT_PATHS.data_root / "processed" / "a6")
MANIFEST_OUT = BRONZE_OUT.parent / "manifest.json"

DATASET = "AIGuruTinix/ViFinQA"
REVISION = "0450088ab22ec946f04f097586967ca405955b3b"


def assert_scratch_explicit(stage: str) -> None:
    """SAFETY · RC2-005. Nói TO khi thư mục làm việc là mặc định ngầm.

    Đọc nhầm scratch của build khác là lỗi im lặng tệ nhất trong chuỗi build:
    `publish` sẽ đóng dấu một `silver.sqlite` không thuộc lần chạy này, và
    `build_id` trong manifest vẫn trông hợp lệ.
    """
    if _SCRATCH_EXPLICIT:
        return
    stale = SCRATCH.exists() and any(SCRATCH.iterdir())
    print(f"CẢNH BÁO [{stage}]: DATA_PIPELINE_SCRATCH chưa đặt — dùng mặc "
          f"định {SCRATCH}", file=sys.stderr)
    if stale:
        raise SystemExit(
            f"LỖI [{stage}]: {SCRATCH} đã có sẵn nội dung và biến "
            "DATA_PIPELINE_SCRATCH KHÔNG được đặt.\n"
            "  Đây có thể là rác của một build khác. Đặt biến rồi chạy lại:\n"
            f"    export DATA_PIPELINE_SCRATCH=<thư mục build đang chạy>")


def _work(name: str) -> Path:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    return SCRATCH / name


def _ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


# ──────────────────────────── stages ────────────────────────────

def _uid_namespace_from_config() -> str | None:
    """Đọc `corpus.uid_namespace_id` từ config. Không có -> None (build_manifest
    sẽ tự suy từ cây quét, giữ hành vi cũ)."""
    try:
        import yaml
        d = yaml.safe_load(Path(CONFIG_PATH).read_text(encoding="utf-8")) or {}
    except (OSError, ImportError, Exception):  # noqa: B014
        return None
    v = ((d.get("corpus") or {}) if isinstance(d, dict) else {}).get("uid_namespace_id")
    return v or None


def _expected_report_count() -> int | None:
    """So tai lieu KY VONG, doc tu manifest cua snapshot — KHONG hard-code.

    P1-05: truoc day dung hang so 1973. Corpus khac kich thuoc se khong bao gio
    thoa dieu kien, nen build im lang khong publish. Nguon su that duy nhat cho
    con so nay la `n_reports` trong manifest do chinh buoc snapshot sinh ra.
    """
    for cand in (_work("manifest.json"), MANIFEST_OUT):
        try:
            d = json.loads(Path(cand).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            continue
        n = d.get("n_reports")
        if isinstance(n, int) and n > 0:
            return n
    return None


def cmd_snapshot(args) -> int:
    from text2pandas.pipelines.a6.manifest import (
        build_manifest, validate_corpus, write_manifest,
    )

    root = CORPUS.parent
    print(f"  quét {root} …", flush=True)
    # RC2-016 / AMD-04 · hạt giống UID đọc từ config và ĐÓNG BĂNG; nó KHÔNG
    # phụ thuộc nội dung cây đang quét. `corpus_content_hash` mới là thứ phản
    # ánh corpus và mới đi vào build_id.
    ns = _uid_namespace_from_config()
    man = build_manifest(root, DATASET, REVISION, uid_namespace_id=ns)
    val = validate_corpus(root, man)

    write_manifest(man, _work("manifest.json"))
    write_manifest(man, MANIFEST_OUT)
    (_work("source_validation.json")).write_text(
        json.dumps(val.to_json(), ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n╔═══════════ D0 SNAPSHOT ═══════════╗")
    print(f"  corpus_id     : {man.corpus_id}")
    print(f"  tệp           : {man.n_files:,}   báo cáo .txt: {man.n_reports:,}")
    print(f"  dung lượng    : {man.n_bytes/1e6:.1f} MB")
    # RC-05 · trùng nội dung. KHÔNG loại tệp ở đây, và đó là quyết định có chủ
    # ý: bỏ một tệp làm lệch mọi số đếm mà các cổng chất lượng đang neo vào,
    # đổi lấy 0,1% corpus. Chỗ khử trùng đúng là tầng TRUY HỒI — hai bảng y hệt
    # cùng được trả về mới là chỗ điểm bị chia đôi. Ở đây chỉ khai báo.
    if man.duplicate_groups:
        print(f"  trùng nội dung: {man.n_duplicate_files} tệp dư"
              f" / {len(man.duplicate_groups)} nhóm  ⚠ không loại, xem manifest")
        for g in man.duplicate_groups[:5]:
            print(f"    ≡ {' ≡ '.join(g['files'])}")
    else:
        print("  trùng nội dung: 0  ✓")
    print("  ── cổng khẳng định (kỳ vọng 0 hết) ──")
    for k in ("n_bom", "n_utf8_error", "n_nul", "n_crlf", "n_lone_cr", "n_tab",
              "n_nbsp", "n_zero_width", "n_empty", "n_not_nfc",
              "n_table_not_line_start", "n_page_marker_variant"):
        v = getattr(val, k)
        print(f"    {k:<26} {v:>6}  {'✓' if v == 0 else '⚠'}")
    for f in val.failures[:5]:
        print(f"    ✗ {f}")
    print(f"  G0: {'PASS' if val.ok else 'FAIL'}")
    return 0 if val.ok else 1


def cmd_catalog(args) -> int:
    from text2pandas.pipelines.a6.catalog import build_catalog
    from text2pandas.pipelines.a6.manifest import read_manifest
    from text2pandas.pipelines.a6.storage import BRONZE_DDL, connect, integrity_check, publish_db

    man = read_manifest(_work("manifest.json"))
    db = _work("catalog.sqlite")
    conn = connect(db, BRONZE_DDL, fresh=(args.offset == 0))
    conn.execute("INSERT OR REPLACE INTO meta VALUES('corpus_id',?)", (man.corpus_id,))
    conn.execute("INSERT OR REPLACE INTO meta VALUES('revision',?)", (REVISION,))

    rep = build_catalog(
        CORPUS, conn, man.corpus_id, offset=args.offset, limit=args.limit,
        progress=(lambda i, t: print(f"  ... {i} tài liệu, {t:,} bảng", flush=True))
        if args.verbose else None,
    )
    errs = integrity_check(conn)
    n_doc = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    n_tab = conn.execute("SELECT COUNT(*) FROM tables").fetchone()[0]
    n_pag = conn.execute("SELECT COUNT(*) FROM pages").fetchone()[0]
    # RC-06 · tám tài liệu PRT không có `<table>`. Đây KHÔNG phải orphan FK và
    # cũng không phải parser failure — nếu để chúng lẫn vào cột `lỗi` thì mỗi
    # lần chạy lại có người đi truy một sự cố không tồn tại.
    nontab = conn.execute(
        "SELECT rel_path, retrieval_route FROM document_classification"
        " WHERE document_kind='non_tabular' ORDER BY rel_path").fetchall()
    conn.close()

    print("\n╔═══════════ D1 CATALOG ═══════════╗")
    print(f"  lô này        : {rep.n_documents:,} tài liệu · {rep.n_tables:,} bảng · {rep.seconds}s")
    print(f"  tích luỹ      : {n_doc:,} tài liệu · {n_tab:,} bảng · {n_pag:,} trang")
    print(f"  không markup  : {rep.n_no_markup}   nhiều dòng: {rep.n_multiline}   chưa đóng: {rep.n_unclosed}")
    print(f"  lỗi           : {rep.n_failed}")
    for name, err in rep.failures[:5]:
        print(f"    ✗ {name}: {err}")
    print(f"  non-tabular   : {len(nontab)} tài liệu"
          f"  (no_table_markup — KHÔNG phải lỗi parser)")
    for relp, route in nontab[:10]:
        print(f"    ○ {relp}  → {route}")
    print(f"  toàn vẹn      : {'PASS' if not errs else 'FAIL'}")
    for e in errs[:5]:
        print(f"    ✗ {e}")
    # P1-05 · KHONG dung kich thuoc corpus lam dieu kien luong.
    # `n_doc >= 1973` khien corpus khac kich thuoc KHONG BAO GIO publish — im
    # lang, khong bao loi. Dieu kien dung la: da duyet het tai lieu ma manifest
    # khai, va khong con loi toan ven.
    expected = _expected_report_count()
    complete = (expected is None) or (n_doc >= expected)
    if complete and not errs:
        publish_db(db, BRONZE_OUT)
        print(f"  đã publish    : {BRONZE_OUT}"
              f"   (đủ {n_doc:,}/{expected if expected is not None else n_doc:,} tài liệu)")
    else:
        why = "còn lỗi toàn vẹn" if errs else \
              f"mới {n_doc:,}/{expected:,} tài liệu"
        print(f"  CHƯA publish  : {why}")
    return 0 if not errs and rep.n_failed == 0 else 1


def cmd_silver(args) -> int:
    from text2pandas.pipelines.a6.observation_builder import build_silver_tables
    from text2pandas.pipelines.a6.readiness import apply_policy, load_policy
    from text2pandas.pipelines.a6.storage import (
        SCHEMA_VERSION, SILVER_DDL, connect, integrity_check,
        make_build_id, stamp_schema_version)

    bronze = _ro(_work("catalog.sqlite"))
    sdb = _work("silver.sqlite")
    silver = connect(sdb, SILVER_DDL, fresh=(args.offset == 0))

    rep = build_silver_tables(
        bronze, silver, CORPUS, offset=args.offset, limit=args.limit,
        progress=(lambda k, t, o: print(f"  ... {k} tài liệu · {t:,} bảng · {o:,} obs",
                                        flush=True)) if args.verbose else None,
    )
    q = lambda s: silver.execute(s).fetchone()[0]  # noqa: E731
    n_drop = q("SELECT COUNT(*) FROM dropped_cells")
    tot_tf, tot_obs = q("SELECT COUNT(*) FROM table_features"), q("SELECT COUNT(*) FROM observations")
    tot_sc, tot_gc = q("SELECT COUNT(*) FROM source_cells"), q("SELECT COUNT(*) FROM grid_cells")

    # Data Contract v1: đóng dấu phiên bản hợp đồng và sinh view readiness từ
    # CHÍNH SÁCH. View là phép chiếu, không phải dữ liệu — sửa chính sách thì
    # sinh lại trong vài giây, không rebuild.
    # build_id = hash nội dung xác định build. Doc 12 §3.6: MỌI con số phải
    # mang build_id, nếu không hai lần đo trên hai build khác nhau trông giống
    # hệt nhau. Trước đây báo cáo ra `measure_nobuild.json`.
    from text2pandas.pipelines.a6.observation_builder import SEMANTIC_VERSION
    from text2pandas.pipelines.a6.structure import STRUCTURE_VERSION
    from text2pandas.pipelines.a6.unit_resolver import UNIT_VERSION
    from text2pandas.pipelines.a6.period_resolver import PERIOD_VERSION
    from text2pandas.pipelines.a6.number_parser import NUMBER_VERSION
    from text2pandas.pipelines.a6.tiny_money import TINY_MONEY_VERSION
    from text2pandas.pipelines.a6.cleaning import CLEANING_VERSION
    comp = {"semantic": SEMANTIC_VERSION, "structure": STRUCTURE_VERSION,
            "unit": UNIT_VERSION, "period": PERIOD_VERSION,
            "number": NUMBER_VERSION, "schema": SCHEMA_VERSION,
            # RC-07 — `cleaning` sinh `text_clean`, tức là sinh đầu vào của
            # MỌI thứ phía sau. Nó vắng mặt ở đây từ đầu, nghĩa là sửa luật
            # làm sạch mà `build_id` không đổi. Thêm vào cùng lượt với C07.
            "cleaning": CLEANING_VERSION,
            # RC-03 — luật phân loại tiny-money quyết định ô nào thành
            # observation và ô nào vào `dropped_cells`, nên nó là thành phần
            # SINH nội dung. Đổi luật mà `build_id` không đổi là ID nói dối.
            "tiny_money": TINY_MONEY_VERSION}
    bid, parts = make_build_id(
        {"tables": tot_tf, "observations": tot_obs, "source_cells": tot_sc,
         "dropped_cells": n_drop}, comp)
    stamp_schema_version(silver, {"build_id": bid, **parts})
    # Phân loại đụng độ NGAY trong build: doc 12 §7 từ chối RC nếu còn
    # ambiguity `unknown` trong execution_ready. Đây là phép chiếu, không sửa
    # dữ liệu — sinh lại vài giây khi luật phân loại đổi.
    from text2pandas.pipelines.a6.collision import build_collisions
    coll = build_collisions(silver)
    try:
        pol = apply_policy(silver, load_policy())
        pol_v = pol.policy_version
    except (FileNotFoundError, ValueError) as e:
        pol_v = f"KHÔNG NẠP ĐƯỢC ({e.__class__.__name__})"
    silver.commit()

    print("\n╔═══════════ D2–D4 SILVER ═══════════╗")
    print(f"  lô này      : {rep.n_tables:,} bảng · {rep.n_observations:,} obs · {rep.seconds}s")
    print(f"  tích luỹ    : {tot_tf:,} bảng · {tot_sc:,} source cell · {tot_gc:,} grid cell · {tot_obs:,} obs")
    print(f"  parse ok    : {rep.n_parsed:,}   quá lớn: {rep.n_too_large}   lỗi: {rep.n_failed}")
    print(f"  mơ hồ số    : {rep.n_ambiguous:,}   dash: {rep.n_dash:,}   đơn vị assumed: {rep.n_unit_assumed:,}")
    print(f"  bậc bị bác  : {rep.n_scale_rejected:,}   (lời khai đơn vị mâu thuẫn với chữ số của ô)")
    print(f"  ô số bỏ qua : {n_drop:,}   (đã ghi LÝ DO — không còn vứt im lặng)")
    for r_, n_ in silver.execute(
            "SELECT reason, COUNT(*) FROM dropped_cells GROUP BY 1 ORDER BY 2 DESC"):
        print(f"    {r_:<26}{n_:>10,}")
    print(f"  cột có kỳ   : {rep.n_period_resolved:,}   (suy từ ngữ cảnh bảng: {rep.n_period_from_table:,})")
    print(f"  ô suy kỳ từ trục dòng (A5-B1): {rep.n_period_from_row_path:,}")
    print(f"  hợp đồng    : schema v{SCHEMA_VERSION} · readiness policy v{pol_v}")
    print(f"  build_id    : {bid}")
    print(f"  vân tay mã  : source {parts['source_hash']} · config {parts['config_hash']}")
    print(f"  đụng độ     : {coll['groups']:,} nhóm · {coll['observations']:,} obs"
          f"   chưa phân loại: {coll['unclassified']:,}")
    for k, v in sorted(coll["groups_by_class"].items(), key=lambda x: -x[1]):
        print(f"    {k:<26}{v:>9,} nhóm{coll['observations_by_class'].get(k,0):>12,} obs")
    if rep.by_statement:
        print("  ── loại bảng ──")
        for k, v in sorted(rep.by_statement.items(), key=lambda x: -x[1]):
            print(f"    {k:<18} {v:>8,}")
    if rep.by_value_kind:
        print("  ── value kind ──")
        for k, v in sorted(rep.by_value_kind.items(), key=lambda x: -x[1]):
            print(f"    {k:<18} {v:>8,}")
    if rep.n_tiny_money_flagged:
        # In cả ba con số vì chúng trả lời ba câu khác nhau: luật CŨ bắt bao
        # nhiêu, trong đó bao nhiêu thật sự là giá trị giả (bị loại), và bao
        # nhiêu chưa đủ bằng chứng nên chỉ bị chặn khỏi `execution_ready`.
        print(f"  ── tiny money (RC-03) — luật cũ bắt {rep.n_tiny_money_flagged:,} ca ──")
        for k, v in sorted(rep.by_tiny_money_class.items(), key=lambda x: -x[1]):
            print(f"    {k:<38} {v:>8,}")
        print(f"    → loại khỏi observations{rep.n_tiny_money_dropped:>21,}")
        print(f"    → giữ nhưng chặn execution_ready{rep.n_tiny_money_unresolved:>13,}")
    _exp = _expected_report_count()
    if _exp is None or args.offset + (args.limit or 10**9) >= _exp:
        errs = integrity_check(silver)
        print(f"  toàn vẹn    : {'PASS' if not errs else 'FAIL'}")
        for e in errs[:5]:
            print(f"    ✗ {e}")
    silver.close()
    return 0


def cmd_quality(args) -> int:
    assert_scratch_explicit("quality")
    from text2pandas.pipelines.a6.quality import run_quality

    silver = sqlite3.connect(_work("silver.sqlite"))
    report = run_quality(silver)
    (_work("quality_report.json")).write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    silver.close()

    print("\n╔═══════════ D5 QUALITY ═══════════╗")
    for gate, checks in report["gates"].items():
        status = "PASS" if all(c["pass"] for c in checks) else "FAIL"
        print(f"  {gate}: {status}")
        for c in checks:
            mark = "✓" if c["pass"] else "✗"
            print(f"    {mark} {c['name']:<44} {c['value']}  (ngưỡng {c['threshold']})")
    print(f"\n  vấn đề: {report['n_issues']:,}  (critical {report['n_critical']})")
    for k, v in sorted(report["by_rule"].items(), key=lambda x: -x[1])[:8]:
        print(f"    {k:<34} {v:>9,}")
    return 0 if report["n_critical"] == 0 else 1


def cmd_publish(args) -> int:
    assert_scratch_explicit("publish")
    from text2pandas.pipelines.a6.catalog import CATALOG_VERSION
    from text2pandas.pipelines.a6.gates import split_legacy_gates
    from text2pandas.pipelines.a6.cleaning import CLEANING_VERSION
    from text2pandas.pipelines.a6.html_parser import PARSER_VERSION
    from text2pandas.pipelines.a6.manifest import read_manifest
    from text2pandas.pipelines.a6.number_parser import NUMBER_VERSION
    from text2pandas.pipelines.a6.observation_builder import SEMANTIC_VERSION
    from text2pandas.pipelines.a6.period_resolver import PERIOD_VERSION
    from text2pandas.pipelines.a6.storage import integrity_check, publish_db
    from text2pandas.pipelines.a6.structure import STRUCTURE_VERSION
    from text2pandas.pipelines.a6.unit_resolver import UNIT_VERSION

    man = read_manifest(_work("manifest.json"))
    qpath = _work("quality_report.json")
    if not qpath.exists():
        print("LỖI: chưa chạy quality — không được publish", file=sys.stderr)
        return 2
    quality = json.loads(qpath.read_text(encoding="utf-8"))
    if quality["n_critical"] > 0:
        print(f"LỖI: còn {quality['n_critical']} vấn đề critical — không publish",
              file=sys.stderr)
        return 2

    # DI-10: Silver chỉ được publish SAU khi quality gate đạt. Bản đầu chỉ kiểm
    # `n_critical`, nên build a94013318c97ad30 đã publish trong lúc G4 FAIL —
    # đúng thứ mà bất biến này sinh ra để chặn. Gate không chặn được thì nó là
    # báo cáo, không phải gate.
    #
    # Nhưng DI-10 chặn CHẤT LƯỢNG SAI, không chặn CHƯA ĐO ĐƯỢC. G3 "độ chính
    # xác role trên gold" không có Structure Gold nên vĩnh viễn `pass=False`;
    # gộp nó vào `failed` thì RC không bao giờ ra được và Retrieval đứng chờ
    # một dụng cụ đo mà nó không cần. Doc 12 §7 cho phép RC mang gate BLOCKED
    # miễn KHAI RÕ — nên ở đây tách đôi, và bản có BLOCKED bị hạ nhãn xuống
    # `release-candidate` chứ không được gọi là `published`.
    failed, blocked = split_legacy_gates(quality.get("gates"))
    if failed:
        print("LỖI: quality gate chưa đạt — không publish (DI-10)", file=sys.stderr)
        for f in failed:
            print(f"  ✗ {f}", file=sys.stderr)
        print("  → sửa rule rồi build lại. KHÔNG vá thẳng vào database.",
              file=sys.stderr)
        return 2

    status = "release-candidate" if blocked else "published"
    if blocked:
        print("CẢNH BÁO: có cổng BLOCKED — publish với nhãn"
              " `release-candidate`, KHÔNG phải `published`:")
        for b in blocked:
            print(f"  ⊘ {b}")
        print("  → BLOCKED = chưa đo được, không phải đã đạt. Khai rõ trong"
              " HANDOFF.md và không tuyên bố 'mọi cổng xanh'.")

    versions = {
        "schema": "1.0", "catalog": CATALOG_VERSION, "parser": PARSER_VERSION,
        "cleaning": CLEANING_VERSION, "structure": STRUCTURE_VERSION,
        "number": NUMBER_VERSION, "semantic": SEMANTIC_VERSION,
        "period": PERIOD_VERSION, "unit": UNIT_VERSION,
        "quality": quality["quality_version"],
    }
    sdb = _work("silver.sqlite")
    conn = sqlite3.connect(sdb)

    # `build_id` LẤY TỪ `build_meta`, không tính lại. `cmd_silver` đã băm nội
    # dung mã nguồn + cấu hình + số đếm (`make_build_id`); tính lại ở đây từ
    # `corpus_id + versions` cho một ID KHÁC rồi ghi đè lên — đúng lỗi va chạm
    # ID đã sửa một lần: hai build khác nhau về nội dung nhưng cùng số phiên
    # bản sẽ trùng ID. Publish là bước ĐÓNG DẤU, không phải bước ĐẶT TÊN.
    bid_row = conn.execute(
        "SELECT value FROM build_meta WHERE key='build_id'").fetchone()
    if not bid_row or not bid_row[0]:
        print("LỖI: silver.sqlite không có build_id — chạy lại `silver`"
              " (make_build_id chưa đóng dấu)", file=sys.stderr)
        conn.close()
        return 2
    build_id = bid_row[0]

    out = SILVER_DIR / build_id
    out.mkdir(parents=True, exist_ok=True)
    errs = integrity_check(conn)
    counts = {
        t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        for t in ("table_features", "source_cells", "grid_cells", "rows",
                  "columns", "observations", "quality_issues")
    }
    conn.execute("INSERT OR REPLACE INTO build_meta VALUES('status',?)", (status,))
    conn.execute("INSERT OR REPLACE INTO build_meta VALUES('blocked_gates',?)",
                 (json.dumps(blocked, ensure_ascii=False),))
    conn.commit()
    conn.close()

    if errs:
        print("LỖI: toàn vẹn không đạt — không publish", file=sys.stderr)
        for e in errs[:5]:
            print(f"  {e}", file=sys.stderr)
        return 2

    checksum = publish_db(sdb, out / "silver.sqlite")
    (out / "manifest.json").write_text(json.dumps({
        "build_id": build_id, "status": status, "corpus_id": man.corpus_id,
        "revision": REVISION, "versions": versions, "counts": counts,
        "silver_sha256": checksum,
        # Cổng BLOCKED đi vào manifest, không chỉ ra màn hình: người nhận gói
        # không xem log của người dựng. Doc 12 §7 số 12 đòi "khai rõ".
        "blocked_gates": blocked,
        "quality_summary": {"n_issues": quality["n_issues"],
                            "n_critical": quality["n_critical"],
                            "n_blocked_gates": len(blocked)},
    }, ensure_ascii=False, sort_keys=True, indent=1), encoding="utf-8")
    (out / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=1), encoding="utf-8")

    print("\n╔═══════════ D6 PUBLISH ═══════════╗")
    print(f"  build_id : {build_id}")
    print(f"  nhãn     : {status}"
          + (f"   ({len(blocked)} cổng BLOCKED đã khai)" if blocked else ""))
    print(f"  đường dẫn: {out}")
    for k, v in counts.items():
        print(f"    {k:<18} {v:>10,}")
    print(f"  sha256   : {checksum[:32]}…")
    return 0


def _build_id_of_db(path) -> str | None:
    try:
        c = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            r = c.execute("SELECT value FROM build_meta WHERE key='build_id'").fetchone()
            return r[0] if r else None
        finally:
            c.close()
    except sqlite3.Error:
        return None


def _release_inputs_same_build(args) -> list[str]:
    """Ba artifact (silver DB, bronze catalog, quality report) phai cung build.

    B0-01: truoc day release lay bronze tu bien global BRONZE_OUT, nen no co the
    doc catalog cua MOT BUILD KHAC ma khong ai biet.
    """
    errs: list[str] = []
    bid = _build_id_of_db(args.db)
    if bid is None:
        errs.append(f"--db {args.db} không đọc được build_id")
    b = getattr(args, "bronze", None)
    if b:
        if not Path(b).is_file():
            errs.append(f"--bronze không tồn tại: {b}")
    q = getattr(args, "quality", None)
    if q:
        if not Path(q).is_file():
            errs.append(f"--quality không tồn tại: {q}")
        else:
            try:
                d = json.loads(Path(q).read_text(encoding="utf-8"))
                qb = d.get("build_id")
                if qb and bid and qb != bid:
                    errs.append(f"--quality thuộc build {qb}, --db thuộc {bid}")
            except (OSError, json.JSONDecodeError):
                errs.append(f"--quality không đọc được: {q}")
    return errs


def _is_build_manifest(path: Path, build_id: str | None) -> tuple[bool, str]:
    """Manifest CORPUS va manifest BAN DUNG trung ten tep `manifest.json`.

    `snapshot` ghi manifest corpus vao goc OUTPUT; `publish` ghi manifest ban
    dung vao `<silver_dir>/<build_id>/`. Neu release tro vao `<OUT>/silver.sqlite`
    ma chua `publish`, no doc phai manifest corpus — khong co `build_id`, nen
    `build_release` dat `build_id = "unknown"` va di tiep KHONG BAO LOI.

    Mot goi phat hanh mang `build_id: unknown` la goi khong quy duoc ve ban
    dung nao. Chan o day, khong de no thanh mot dong trong manifest gui di.
    """
    if not path.is_file():
        return False, f"khong thay manifest ban dung: {path}"
    try:
        d = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"manifest khong doc duoc: {path} ({exc})"
    if not isinstance(d, dict) or not d.get("build_id"):
        extra = " — day la manifest CORPUS (do `snapshot` ghi), khong phai " \
                "manifest BAN DUNG. Chay stage `publish` truoc, roi tro --db " \
                "vao <silver_dir>/<build_id>/silver.sqlite" \
            if isinstance(d, dict) and ("files" in d or "corpus_id" in d) else ""
        return False, f"manifest thieu `build_id`: {path}{extra}"
    if build_id and d["build_id"] != build_id:
        return False, (f"manifest khai build {d['build_id']} nhung --db thuoc "
                       f"build {build_id}")
    return True, ""


def cmd_release(args) -> int:
    from text2pandas.pipelines.a6.release import build_release

    # B0-01 · GIAO DIEN EXPLICIT. Uu tien --db/--bronze/--quality do nguoi goi
    # chi dinh; ba artifact phai THUOC CUNG MOT BUILD. Che do "latest build"
    # chi con la duong lui va bi canh bao.
    if getattr(args, "db", None):
        src = Path(args.db).parent
        if not Path(args.db).is_file():
            print(f"LỖI: không thấy --db {args.db}", file=sys.stderr)
            return 2
        bad = _release_inputs_same_build(args)
        if bad:
            for b in bad:
                print(f"LỖI: {b}", file=sys.stderr)
            return 2
        return _do_release(args, src)
    src = SILVER_DIR / args.build_id if args.build_id else None
    if src is None:
        print("CẢNH BÁO: không có --db/--build-id → dùng bản dựng MỚI NHẤT. "
              "Đây là đường lui, không phải giao diện chuẩn.", file=sys.stderr)
        builds = sorted(SILVER_DIR.glob("*/silver.sqlite"),
                        key=lambda p: p.stat().st_mtime)
        if not builds:
            print(f"LỖI: chưa có bản dựng nào trong {SILVER_DIR}", file=sys.stderr)
            return 2
        src = builds[-1].parent
    if not (src / "silver.sqlite").exists():
        print(f"LỖI: không thấy {src / 'silver.sqlite'}", file=sys.stderr)
        return 2

    # SAFETY · RC2-004. `--out` nay la required o argparse; dong nay giu lai
    # mot lop chan thu hai cho nguoi goi `cmd_release` truc tiep tu Python.
    if not getattr(args, "out", None):
        print("LỖI: `--out` là BẮT BUỘC. Mặc định cũ ghi đè baseline RC1.",
              file=sys.stderr)
        return 2
    out = Path(args.out)
    rep = build_release(
        src_silver=src / "silver.sqlite",
        src_bronze=BRONZE_OUT,
        src_manifest_path=src / "manifest.json",
        src_quality_path=src / "quality_report.json",
        out_dir=out, profile=args.profile, per_table=args.per_table,
        gate_report_path=getattr(args, "gate_report", None),
    )

    print("\n╔═══════════ D7 RELEASE ═══════════╗")
    print(f"  nguồn    : {rep.build_id}")
    print(f"  đích     : {out}")
    print(f"  hồ sơ    : {rep.profile}")
    for k, v in rep.counts.items():
        print(f"    {k:<20} {v:>12,}")
    print("  ── giai đoạn ──")
    for name, secs, note in rep.stages:
        print(f"    {name:<26} {secs:>7.1f}s  {note}")
    print(f"  kiểm gói : {rep.dq.get('n_checks')} kiểm tra · "
          f"{rep.dq.get('n_failed')} không đạt")
    for w in rep.warnings[:8]:
        print(f"    ✗ {w}")
    print(f"  tổng     : {rep.seconds}s")
    return 0 if not rep.warnings else 1


def _do_release(args, src):
    """Duong EXPLICIT: dung dung DB/bronze/quality nguoi goi chi dinh."""
    from text2pandas.pipelines.a6.release import build_release
    if not getattr(args, "out", None):
        print("LỖI: `--out` là BẮT BUỘC.", file=sys.stderr)
        return 2
    db = Path(args.db)
    bronze = Path(args.bronze) if getattr(args, "bronze", None) else BRONZE_OUT
    manifest = db.parent / "manifest.json"
    ok, why = _is_build_manifest(manifest, _build_id_of_db(str(db)))
    if not ok:
        print(f"LỖI: {why}", file=sys.stderr)
        return 2
    quality = Path(args.quality) if getattr(args, "quality", None) else \
        db.parent / "quality_report.json"
    missing = [str(x) for x in (db, bronze) if not x.exists()]
    if missing:
        for m in missing:
            print(f"LỖI: không thấy {m}", file=sys.stderr)
        return 2
    rep = build_release(src_silver=db, src_bronze=bronze,
                        src_manifest_path=manifest, src_quality_path=quality,
                        out_dir=Path(args.out),
                        gate_report_path=getattr(args, "gate_report", None),
                        profile=getattr(args, "profile", "slim"),
                        per_table=getattr(args, "per_table", "primary"))
    print(f"  release → {args.out}  (build {rep.build_id})")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="data_pipeline")
    p.add_argument("-v", "--verbose", action="store_true")

    # `-v` nhận được ở CẢ HAI vị trí: `cli -v silver` và `cli silver -v`.
    #
    # argparse mặc định chỉ chấp nhận cờ chung TRƯỚC lệnh con, và `cli silver -v`
    # thì báo "unrecognized arguments" — một thất bại vô nghĩa với người dùng,
    # vì cả hai cách viết đều rõ ý. Bắt con người nhớ thứ tự tham số là chuyển
    # chi phí sai lệch của công cụ sang cho họ.
    #
    # `default=SUPPRESS` là phần bắt buộc: không có nó, mặc định `False` của
    # subparser sẽ GHI ĐÈ giá trị `True` do parser cha đặt, và `cli -v silver`
    # lại im lặng mất tác dụng.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("-v", "--verbose", action="store_true",
                        default=argparse.SUPPRESS)

    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("snapshot", parents=[common])
    for name in ("catalog", "silver"):
        s = sub.add_parser(name, parents=[common])
        s.add_argument("--offset", type=int, default=0)
        s.add_argument("--limit", type=int, default=0)
    sub.add_parser("quality", parents=[common])
    sub.add_parser("publish", parents=[common])
    r = sub.add_parser("release", parents=[common])
    r.add_argument("--build-id", default=None,
                   help="mặc định: bản dựng publish gần nhất")
    # ── SAFETY · RC2-004 · `--out` BẮT BUỘC ────────────────────────────
    #
    # Trước bản này `--out` mặc định `None`, và `cmd_release` rơi về
    # `ROOT / "silver_release"` — ĐÚNG thư mục baseline RC1. Một lệnh gõ
    # thiếu tham số sẽ ghi đè baseline mà không hỏi gì. Không có lý do nào
    # để một thao tác phá huỷ là hành vi MẶC ĐỊNH.
    r.add_argument("--db", help="silver.sqlite CU THE (giao dien explicit B0-01)")
    r.add_argument("--bronze", help="catalog.sqlite CUNG BUILD voi --db")
    r.add_argument("--quality", help="quality_report.json CUNG BUILD voi --db")
    r.add_argument("--report-dir", dest="report_dir", help="thu muc report")
    r.add_argument("--gate-report", dest="gate_report",
                   help="gate_report.json cua RC-20 — nguon DUY NHAT cua "
                        "release_label va acceptance_status (Doc 56 P0-05)")
    r.add_argument("--out", required=True,
                   help="thư mục đích. BẮT BUỘC — không có mặc định, vì mặc "
                        "định cũ ghi đè baseline RC1")
    r.add_argument("--profile", choices=("slim", "full"), default="slim",
                   help="slim bỏ source_cells/grid_cells (tiết kiệm ~1,9 GB)")
    r.add_argument("--per-table", choices=("none", "primary", "all"),
                   default="primary",
                   help="CSV theo từng bảng: primary = 3 báo cáo chính")

    args = p.parse_args(argv)
    return {
        "snapshot": cmd_snapshot, "catalog": cmd_catalog, "silver": cmd_silver,
        "quality": cmd_quality, "publish": cmd_publish, "release": cmd_release,
    }[args.cmd](args)


if __name__ == "__main__":
    raise SystemExit(main())
