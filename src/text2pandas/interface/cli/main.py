"""CLI — điểm vào duy nhất của pipeline.

    python -m text2pandas.interface.cli.main catalog
    python -m text2pandas.interface.cli.main parse-check --limit 2000
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from text2pandas.infrastructure.builds import (
    BuildSafetyError,
    assert_not_active_snapshot,
    build_output_path,
    publish_new_file,
)
from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.snapshots import ActiveSnapshots

ROOT = Path(__file__).resolve().parents[4]
PROJECT_PATHS = ProjectPaths.from_repo_root(ROOT)
ACTIVE_SNAPSHOTS = ActiveSnapshots.load(PROJECT_PATHS)
CORPUS = PROJECT_PATHS.raw_btc / "financial_statements"
QUESTIONS = PROJECT_PATHS.raw_btc / "questions" / "questions.jsonl"
LEGACY_CATALOG_DB = PROJECT_PATHS.artifact_root / "runs" / "a6" / "bronze" / "catalog.sqlite"
SILVER_DB = ACTIVE_SNAPSHOTS.a6_path / "silver.db"
CARD_DB = ACTIVE_SNAPSHOTS.retrieval_path / "retrieval.db"
CODE_STOCK = PROJECT_PATHS.raw_btc / "metadata" / "companies.csv"
SUBMIT_DIR = PROJECT_PATHS.artifact_root / "submissions"

# Thư mục nhân bản trên đĩa CỤC BỘ. Bắt buộc: kho code nằm trên FUSE mount,
# nơi SQLite không khoá được tệp và ném "disk I/O error" ngay ở lệnh đầu tiên.
# Build ở đây rồi copy sang `artifacts/runs/a6/bronze/` khi xong.
SCRATCH = Path(os.environ.get("TEXT2PANDAS_SCRATCH", "/tmp/text2pandas_work"))


def _workdb(name: str) -> Path:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    return SCRATCH / name


def _publish(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def _legacy_output(args: argparse.Namespace, filename: str) -> Path:
    target = build_output_path(PROJECT_PATHS, "legacy-build", args.run_id, filename)
    assert_not_active_snapshot(target, ACTIVE_SNAPSHOTS)
    return target


def _source_or_run_output(
    args: argparse.Namespace,
    explicit: str | None,
    filename: str,
) -> Path:
    source = Path(explicit).expanduser().resolve() if explicit else _legacy_output(args, filename)
    if not source.is_file():
        raise BuildSafetyError(f"missing build input: {source}")
    return source


def cmd_catalog(args: argparse.Namespace) -> int:
    from text2pandas.application.usecases.build_catalog import build_catalog

    if not CORPUS.is_dir():
        print(f"LỖI: không thấy corpus tại {CORPUS}", file=sys.stderr)
        return 2

    def progress(i: int, n_tab: int) -> None:
        print(f"  ... {i} tài liệu, {n_tab:,} bảng", flush=True)

    target = _legacy_output(args, "catalog.sqlite")
    work = _workdb(f"{args.run_id}-catalog.sqlite")
    work.unlink(missing_ok=True)
    rep = build_catalog(CORPUS, work, progress=progress if args.verbose else None)
    publish_new_file(work, target)

    print("\n╔═══════════ CATALOG ═══════════╗")
    print(f"  tài liệu          : {rep.n_documents:,}")
    print(f"  bảng              : {rep.n_tables:,}")
    print(f"  trang             : {rep.n_pages:,}")
    print(f"  tài liệu lỗi      : {rep.n_failed}")
    print(f"  tài liệu 0 bảng   : {rep.docs_without_tables}")
    print(f"  basis xung đột    : {rep.basis_conflicts}  (tên tệp ≠ nội dung)")
    print(f"  mẫu định danh     : {rep.by_pattern}")
    print(f"  thời gian         : {rep.seconds}s")
    print(f"  db                : {target}")
    for name, err in rep.failures:
        print(f"  ✗ {name}: {err}")
    return 0 if rep.n_failed == 0 else 1


def cmd_parse_check(args: argparse.Namespace) -> int:
    import sqlite3
    from collections import Counter

    from text2pandas.domain.values.vn_number import (
        detect_convention,
        parse_vn_number,
    )
    from text2pandas.infrastructure.parsing.html_table import parse_table_html

    db = Path(args.catalog_db).expanduser().resolve()
    if not db.is_file():
        raise BuildSafetyError(f"missing catalog database: {db}")
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    q = "SELECT doc_id_stripped, line_no_1based, raw_html FROM tables"
    if args.limit:
        q += f" LIMIT {args.limit}"

    st = Counter()
    conv = Counter()
    cellstat = Counter()
    dims = []
    bad = []
    for doc_id, line_no, html in conn.execute(q):
        g = parse_table_html(html)
        st["tables"] += 1
        if not g.ok:
            st["parse_failed"] += 1
            if len(bad) < 10:
                bad.append((doc_id, line_no, g.parse_error))
            continue
        st["parse_ok"] += 1
        if g.had_spans:
            st["with_spans"] += 1
        st["img_stripped"] += g.n_img_stripped
        dims.append((g.n_rows, g.n_cols))
        flat = [c for row in g.cells for c in row]
        c = detect_convention(flat)
        conv[c.value] += 1
        for cell in flat:
            cellstat[parse_vn_number(cell, c).status.value] += 1

    print("\n╔═══════════ PARSE CHECK ═══════════╗")
    for k, v in st.most_common():
        print(f"  {k:<18} {v:>12,}")
    if dims:
        rows = sorted(d[0] for d in dims)
        cols = sorted(d[1] for d in dims)
        print(f"  hàng/bảng          trung vị {rows[len(rows)//2]:>4}  max {rows[-1]:>5}")
        print(f"  cột/bảng           trung vị {cols[len(cols)//2]:>4}  max {cols[-1]:>5}")
    print("  ── quy ước phân cách theo bảng ──")
    for k, v in conv.most_common():
        print(f"  {k:<18} {v:>12,}")
    tot = sum(cellstat.values()) or 1
    print(f"  ── phân loại ô ({tot:,}) ──")
    for k, v in cellstat.most_common():
        print(f"  {k:<18} {v:>12,}  {100*v/tot:5.2f}%")
    for b in bad:
        print(f"  ✗ {b}")
    return 0



def cmd_index(args: argparse.Namespace) -> int:
    from text2pandas.infrastructure.retrieval.index import build_index

    cat = _source_or_run_output(args, args.catalog_db, "catalog.sqlite")
    target = _legacy_output(args, "table_index.sqlite")
    work = _workdb(f"{args.run_id}-table_index.sqlite")
    work.unlink(missing_ok=True)
    rep = build_index(cat, work, progress=(lambda n: print(f"  ... {n:,} bảng", flush=True)) if args.verbose else None)
    publish_new_file(work, target)
    print("\n╔═══════════ INDEX ═══════════╗")
    for k, v in rep.items():
        print(f"  {k:<12} {v:,}" if isinstance(v, int) else f"  {k:<12} {v}")
    print(f"  db           {target}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    import json

    from text2pandas.application.usecases.run_pipeline import run_pipeline
    from text2pandas.application.usecases.submission import (
        SubmissionConfig,
        build_submission,
        replay_zip,
        validate_zip,
    )

    cat = _workdb("catalog.sqlite")
    idx = _workdb("card_index.sqlite")
    if not cat.exists():
        cat = LEGACY_CATALOG_DB
    if not idx.exists():
        idx = CARD_DB

    stage = SCRATCH / "stage"
    records = stage / "records.jsonl"
    if args.offset == 0 and not args.resume:
        import shutil as _sh
        if stage.exists():
            _sh.rmtree(stage)
    stage.mkdir(parents=True, exist_ok=True)
    rep = run_pipeline(
        cat, idx, QUESTIONS, CODE_STOCK, stage / "data", records,
        offset=args.offset, limit=args.limit, n_tables=args.n_tables, n_docs=args.n_docs,
        progress=(lambda i, n: print(f"  ... {i} câu, {n} có đáp án", flush=True)) if args.verbose else None,
    )
    print("\n╔═══════════ PIPELINE ═══════════╗")
    print(f"  câu hỏi              : {rep.n_questions:,}")
    print(f"  nhận diện được mã CK : {rep.n_with_ticker:,}  ({100*rep.n_with_ticker/max(rep.n_questions,1):.1f}%)")
    print(f"  nhận diện được năm   : {rep.n_with_year:,}  ({100*rep.n_with_year/max(rep.n_questions,1):.1f}%)")
    print(f"  không có tài liệu    : {rep.n_zero_docs:,}")
    print(f"  truy hồi được bảng   : {rep.n_retrieved:,}  ({100*rep.n_retrieved/max(rep.n_questions,1):.1f}%)")
    print(f"  rút được số          : {rep.n_answered:,}  ({100*rep.n_answered/max(rep.n_questions,1):.1f}%)")
    print(f"  nguồn mã CK          : {rep.ticker_sources}")
    print(f"  thời gian            : {rep.seconds}s")

    if args.no_package:
        done = sum(1 for _ in records.open(encoding="utf-8"))
        print(f"\n  đã ghi {done:,} bản ghi vào {records}")
        return 0

    questions = {}
    for line in QUESTIONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            questions[r["id"]] = r["question"]
    expected = set(questions)
    if args.limit:
        expected = {r.qid for r in rep.results}

    cfg = SubmissionConfig(doc_id_variant=args.doc_id, locator_base=args.locator_base)
    zip_path = build_submission(rep.results, questions, stage, cfg)

    val = validate_zip(zip_path, expected)
    print("\n╔═══════════ VALIDATOR ═══════════╗")
    print(f"  bản ghi              : {val.n_records:,}")
    print(f"  lỗi                  : {len(val.errors)}")
    print(f"  cảnh báo             : {len(val.warnings)}")
    for e in val.errors[:10]:
        print(f"   ✗ {e}")
    for w in val.warnings[:3]:
        print(f"   ! {w}")

    stat = replay_zip(zip_path, SCRATCH / "replay")
    print("\n╔═══════════ REPLAY (môi trường sạch) ═══════════╗")
    for k, v in stat.items():
        print(f"  {k:<12} {v:,}")
    if stat["executed"]:
        print(f"  khớp answer  {100*stat['matched']/stat['executed']:.2f}% số câu chạy được")

    SUBMIT_DIR.mkdir(parents=True, exist_ok=True)
    final = SUBMIT_DIR / zip_path.name
    _publish(zip_path, final)
    print(f"\n  ZIP: {final}  ({zip_path.stat().st_size/1e6:.1f} MB)")
    return 0 if val.ok else 1



def cmd_package(args: argparse.Namespace) -> int:
    """Gộp records.jsonl đã lưu thành ZIP, kiểm tra và chạy lại."""
    import json

    from text2pandas.application.usecases.answer import AnswerResult
    from text2pandas.application.usecases.submission import (
        SubmissionConfig,
        build_submission,
        replay_zip,
        validate_zip,
    )

    stage = SCRATCH / "stage"
    records_path = stage / "records.jsonl"
    if not records_path.exists():
        print("LỖI: chưa có records.jsonl — chạy `run` trước", file=sys.stderr)
        return 2

    seen: dict[int, AnswerResult] = {}
    for line in records_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        seen[r["qid"]] = AnswerResult(
            qid=r["qid"], answer=r["answer"], relevant_docs=r["relevant_docs"],
            relevant_tables=r["relevant_tables"], evidence=r["evidence"],
            pandas_query=r["pandas_query"], confidence=r["confidence"],
            csv_name=r["csv_name"], has_csv=r["has_csv"], notes=r["notes"],
        )
    results = [seen[k] for k in sorted(seen)]

    questions = {}
    for line in QUESTIONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            questions[r["id"]] = r["question"]

    cfg = SubmissionConfig(doc_id_variant=args.doc_id, locator_base=args.locator_base)
    out = SCRATCH / f"submission_{cfg.doc_id_variant}_{cfg.locator_base}"
    if out.exists():
        import shutil as _sh
        _sh.rmtree(out)
    out.mkdir(parents=True)
    (out / "data").mkdir()
    import shutil as _sh2
    for f in (stage / "data").iterdir():
        _sh2.copy2(f, out / "data" / f.name)

    zip_path = build_submission(results, questions, out, cfg)
    val = validate_zip(zip_path, set(questions))
    print(f"\n╔═══ BÀI NỘP  doc_id={cfg.doc_id_variant}  locator_base={cfg.locator_base} ═══╗")
    print(f"  bản ghi   : {val.n_records:,} / {len(questions):,}")
    print(f"  lỗi       : {len(val.errors)}")
    for e in val.errors[:8]:
        print(f"   ✗ {e}")
    stat = replay_zip(zip_path, SCRATCH / "replay")
    print(f"  replay    : chạy được {stat['executed']:,} · khớp {stat['matched']:,} · lỗi {stat['error']:,} · không evidence {stat['no_evidence']:,}")
    if stat["executed"]:
        print(f"  bất biến answer == eval(query): {100*stat['matched']/stat['executed']:.2f}%")
    SUBMIT_DIR.mkdir(parents=True, exist_ok=True)
    _publish(zip_path, SUBMIT_DIR / zip_path.name)
    published = SUBMIT_DIR / zip_path.name
    print(f"  ZIP       : {published.relative_to(ROOT)}  ({zip_path.stat().st_size/1e6:.2f} MB)")
    return 0 if val.ok else 1



def cmd_silver(args: argparse.Namespace) -> int:
    """Bronze -> Silver: đặc trưng bảng + ô định dạng dài."""
    from text2pandas.application.usecases.build_silver import build_silver

    cat = _source_or_run_output(args, args.catalog_db, "catalog.sqlite")
    target = _legacy_output(args, "silver.sqlite")
    work = _workdb(f"{args.run_id}-silver.sqlite")
    work.unlink(missing_ok=True)
    rep = build_silver(
        cat, CORPUS, work, offset=args.offset, limit=args.limit,
        progress=(lambda k, t, c: print(f"  ... {k} tài liệu · {t:,} bảng · {c:,} ô", flush=True))
        if args.verbose else None,
    )
    publish_new_file(work, target)
    print("\n╔═══════════ SILVER ═══════════╗")
    print(f"  tài liệu           : {rep.n_documents:,}")
    print(f"  bảng               : {rep.n_tables:,}")
    print(f"  bảng DỮ LIỆU       : {rep.n_data_tables:,}  ({100*rep.n_data_tables/max(rep.n_tables,1):.1f}%)")
    print(f"  ô số lưu lại       : {rep.n_cells:,}")
    print(f"  bảng có cột-kỳ     : {rep.n_with_period:,}  ({100*rep.n_with_period/max(rep.n_tables,1):.1f}%)")
    print(f"  bảng có cột Mã số  : {rep.n_with_ma_so:,}  ({100*rep.n_with_ma_so/max(rep.n_tables,1):.1f}%)")
    print(f"  thời gian          : {rep.seconds}s")
    print("  ── loại bảng ──")
    for k, v in sorted(rep.by_type.items(), key=lambda x: -x[1]):
        print(f"    {k:<18} {v:>8,}  {100*v/rep.n_tables:5.1f}%")
    print("  ── nguồn đơn vị ──")
    for k, v in sorted(rep.by_unit_source.items(), key=lambda x: -x[1]):
        print(f"    {k:<18} {v:>8,}  {100*v/rep.n_tables:5.1f}%")
    print(f"  db                 : {target}")
    return 0


def cmd_cards(args: argparse.Namespace) -> int:
    """Silver -> chỉ mục Table Card (thay cho index văn bản phẳng)."""
    from text2pandas.infrastructure.retrieval.index import build_card_index

    sil = _source_or_run_output(args, args.silver_db, "silver.sqlite")
    target = _legacy_output(args, "card_index.sqlite")
    work = _workdb(f"{args.run_id}-card_index.sqlite")
    work.unlink(missing_ok=True)
    rep = build_card_index(sil, work,
                           progress=(lambda n: print(f"  ... {n:,}", flush=True)) if args.verbose else None)
    publish_new_file(work, target)
    print("\n╔═══════════ CARD INDEX ═══════════╗")
    for k, v in rep.items():
        print(f"  {k:<16} {v:,}" if isinstance(v, int) else f"  {k:<16} {v}")
    print(f"  db               {target}")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    """Verify active raw, A6, and retrieval snapshot lineage."""
    from text2pandas.infrastructure.snapshots import verify_active_snapshots

    report = verify_active_snapshots(PROJECT_PATHS, scope=args.scope)
    for item in report.items:
        mark = "PASS" if item.ok else "FAIL"
        print(f"[{mark}] {item.name}: {item.detail}")
    return 0 if report.ok else 1


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="text2pandas")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    catalog = sub.add_parser("catalog", help="Quét corpus, dựng immutable legacy catalog")
    catalog.add_argument("--run-id", required=True)
    index = sub.add_parser("index", help="Dựng immutable FTS5 index legacy")
    index.add_argument("--run-id", required=True)
    index.add_argument("--catalog-db")
    sv = sub.add_parser("silver", help="Bronze -> Silver: đặc trưng bảng + ô")
    sv.add_argument("--run-id", required=True)
    sv.add_argument("--catalog-db")
    sv.add_argument("--offset", type=int, default=0)
    sv.add_argument("--limit", type=int, default=0)
    cards = sub.add_parser("cards", help="Silver -> immutable legacy Table Card index")
    cards.add_argument("--run-id", required=True)
    cards.add_argument("--silver-db")
    rn = sub.add_parser("run", help="Chạy pipeline end-to-end -> ZIP bài nộp")
    rn.add_argument("--limit", type=int, default=0)
    rn.add_argument("--offset", type=int, default=0)
    rn.add_argument("--n-tables", dest="n_tables", type=int, default=20)
    rn.add_argument("--n-docs", dest="n_docs", type=int, default=5)
    rn.add_argument("--resume", action="store_true")
    rn.add_argument("--no-package", action="store_true")
    rn.add_argument("--doc-id", dest="doc_id", choices=["stripped", "literal"], default="stripped")
    rn.add_argument("--locator-base", dest="locator_base", type=int, choices=[0, 1], default=1)
    pk = sub.add_parser("package", help="Gộp bản ghi đã lưu -> ZIP + kiểm tra + replay")
    pk.add_argument("--doc-id", dest="doc_id", choices=["stripped", "literal"], default="stripped")
    pk.add_argument("--locator-base", dest="locator_base", type=int, choices=[0, 1], default=1)
    pc = sub.add_parser("parse-check", help="Parse thử bảng, thống kê chất lượng")
    pc.add_argument("--catalog-db", required=True)
    pc.add_argument("--limit", type=int, default=0)
    vf = sub.add_parser("verify", help="Kiểm identity và lineage của active snapshots")
    vf.add_argument("scope", nargs="?", choices=["raw", "a6", "retrieval", "all"], default="all")

    args = p.parse_args(argv)
    handlers = {"catalog": cmd_catalog, "parse-check": cmd_parse_check,
                "index": cmd_index, "run": cmd_run, "package": cmd_package,
                "silver": cmd_silver, "cards": cmd_cards, "verify": cmd_verify}
    try:
        return handlers[args.cmd](args)
    except BuildSafetyError as error:
        print(f"LỖI AN TOÀN BUILD: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
