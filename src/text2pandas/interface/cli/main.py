"""CLI — điểm vào duy nhất của pipeline.

python -m text2pandas.interface.cli.main catalog
python -m text2pandas.interface.cli.main parse-check --limit 2000
"""

from __future__ import annotations

import argparse
import csv
import json
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
from text2pandas.pipelines.retrieval.policy import MAX_RELEVANT_TABLES

ROOT = Path(__file__).resolve().parents[4]
PROJECT_PATHS = ProjectPaths.from_repo_root(ROOT)
ACTIVE_SNAPSHOTS = ActiveSnapshots.load(PROJECT_PATHS)
CORPUS = PROJECT_PATHS.raw_btc / "financial_statements"
QUESTIONS = PROJECT_PATHS.raw_btc / "questions" / "questions.jsonl"
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

    st: Counter[str] = Counter()
    conv: Counter[str] = Counter()
    cellstat: Counter[str] = Counter()
    dims: list[tuple[int, int]] = []
    bad: list[tuple[str, int, str | None]] = []
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
        print(f"  hàng/bảng          trung vị {rows[len(rows) // 2]:>4}  max {rows[-1]:>5}")
        print(f"  cột/bảng           trung vị {cols[len(cols) // 2]:>4}  max {cols[-1]:>5}")
    print("  ── quy ước phân cách theo bảng ──")
    for k, v in conv.most_common():
        print(f"  {k:<18} {v:>12,}")
    tot = sum(cellstat.values()) or 1
    print(f"  ── phân loại ô ({tot:,}) ──")
    for k, v in cellstat.most_common():
        print(f"  {k:<18} {v:>12,}  {100 * v / tot:5.2f}%")
    for b in bad:
        print(f"  ✗ {b}")
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    from text2pandas.infrastructure.retrieval.index import build_index

    cat = _source_or_run_output(args, args.catalog_db, "catalog.sqlite")
    target = _legacy_output(args, "table_index.sqlite")
    work = _workdb(f"{args.run_id}-table_index.sqlite")
    work.unlink(missing_ok=True)
    rep = build_index(
        cat,
        work,
        progress=(lambda n: print(f"  ... {n:,} bảng", flush=True)) if args.verbose else None,
    )
    publish_new_file(work, target)
    print("\n╔═══════════ INDEX ═══════════╗")
    for k, v in rep.items():
        print(f"  {k:<12} {v:,}" if isinstance(v, int) else f"  {k:<12} {v}")
    print(f"  db           {target}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    import json

    from text2pandas.application.usecases.canonical_run import run_canonical_pipeline
    from text2pandas.application.usecases.run_manifest import (
        pipeline_manifest,
        submission_manifest,
        write_manifest,
    )
    from text2pandas.application.usecases.submission import (
        SubmissionConfig,
        build_submission,
        replay_zip,
        validate_zip,
    )
    from text2pandas.infrastructure.snapshots import verify_active_snapshots
    from text2pandas.infrastructure.source_identity import git_source_identity

    if args.question_id and (args.limit or args.offset):
        raise BuildSafetyError("--question-id cannot be combined with --limit/--offset")
    if (args.limit or args.offset or args.question_id) and not args.no_package:
        raise BuildSafetyError("partial run requires --no-package")
    verification = verify_active_snapshots(PROJECT_PATHS, scope="all")
    failures = [item for item in verification.items if not item.ok]
    if failures:
        detail = "; ".join(f"{item.name}: {item.detail}" for item in failures)
        raise BuildSafetyError(f"active snapshot preflight failed: {detail}")

    # Freeze provenance before executing the pipeline.  Reading HEAD only at
    # the end of a long run can attribute in-memory code to a later commit.
    source_identity = git_source_identity(ROOT)
    stage = PROJECT_PATHS.run_dir("answer", args.run_id)
    rep = run_canonical_pipeline(
        ACTIVE_SNAPSHOTS.a6_path / "silver.db",
        ACTIVE_SNAPSHOTS.retrieval_path / "retrieval.db",
        QUESTIONS,
        stage,
        question_ids=(frozenset(args.question_id) if args.question_id else None),
        offset=args.offset,
        limit=args.limit,
        max_tables=args.n_tables,
        answer_pool_tables=args.answer_pool_tables,
        progress=(lambda i, n: print(f"  ... {i} câu, {n} có đáp án", flush=True))
        if args.verbose
        else None,
    )
    pipeline_manifest_path = stage / "manifest.json"
    write_manifest(
        pipeline_manifest_path,
        pipeline_manifest(
            PROJECT_PATHS,
            ACTIVE_SNAPSHOTS,
            args.run_id,
            {
                "offset": args.offset,
                "limit": args.limit,
                "question_ids": sorted(args.question_id),
                "max_tables": args.n_tables,
                "answer_pool_tables": args.answer_pool_tables,
                "package_requested": not args.no_package,
                "doc_id_variant": args.doc_id,
                "locator_base": args.locator_base,
            },
            rep,
            verification,
            source_identity,
            stage / "records.jsonl",
        ),
    )
    print("\n╔═══════════ PIPELINE ═══════════╗")
    print(f"  câu hỏi              : {rep.n_questions:,}")
    print(
        f"  nhận diện thực thể   : {rep.n_with_entity:,}  ({100 * rep.n_with_entity / max(rep.n_questions, 1):.1f}%)"
    )
    print(
        f"  nhận diện được năm   : {rep.n_with_year:,}  ({100 * rep.n_with_year / max(rep.n_questions, 1):.1f}%)"
    )
    print(
        f"  truy hồi được bảng   : {rep.n_retrieved:,}  ({100 * rep.n_retrieved / max(rep.n_questions, 1):.1f}%)"
    )
    print(
        f"  answer qua đủ gate   : {rep.n_answered:,}  ({100 * rep.n_answered / max(rep.n_questions, 1):.1f}%)"
    )
    print(f"  abstain              : {rep.n_abstained:,}")
    print(f"  thời gian            : {rep.seconds}s")
    for reason, count in list(rep.abstain_reasons.items())[:8]:
        print(f"    {reason:<48} {count:>5}")

    if args.no_package:
        print(f"\n  run artifacts: {stage}")
        print(f"  manifest     : {pipeline_manifest_path}")
        return 0

    questions = {}
    for line in QUESTIONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            questions[r["id"]] = r["question"]
    cfg = SubmissionConfig(doc_id_variant=args.doc_id, locator_base=args.locator_base)
    zip_path = build_submission(rep.results, questions, stage, cfg)

    val = validate_zip(zip_path, questions, corpus_root=CORPUS)
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
        print(f"  khớp answer  {100 * stat['matched'] / stat['executed']:.2f}% số câu chạy được")

    package_ok = val.ok and stat["error"] == 0 and stat["matched"] == stat["executed"]
    final = SUBMIT_DIR / f"submission_{args.run_id}.zip"
    published = None
    if package_ok:
        publish_new_file(zip_path, final)
        published = final
        print(f"\n  ZIP: {final}  ({zip_path.stat().st_size / 1e6:.1f} MB)")
    else:
        print("\n  CHẶN PUBLISH: submission chưa qua validator/replay", file=sys.stderr)
    submission_manifest_path = stage / "submission_manifest.json"
    write_manifest(
        submission_manifest_path,
        submission_manifest(
            PROJECT_PATHS,
            args.run_id,
            pipeline_manifest_path,
            zip_path,
            published,
            val,
            stat,
        ),
    )
    print(f"  submission manifest: {submission_manifest_path}")
    return 0 if package_ok else 1


def cmd_package(args: argparse.Namespace) -> int:
    """Re-package one immutable canonical run, then validate and replay it."""
    import json

    from text2pandas.application.usecases.answer import AnswerResult
    from text2pandas.application.usecases.run_manifest import (
        submission_manifest,
        write_manifest,
    )
    from text2pandas.application.usecases.submission import (
        SubmissionConfig,
        build_submission,
        replay_zip,
        validate_zip,
    )

    stage = PROJECT_PATHS.run_dir("answer", args.run_id)
    records_path = stage / "records.jsonl"
    if not records_path.exists():
        print(
            f"LỖI: run {args.run_id!r} không có records.jsonl — chạy `run` trước",
            file=sys.stderr,
        )
        return 2

    seen: dict[int, AnswerResult] = {}
    for line in records_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        evidence = r.get("evidence") or []
        seen[r["qid"]] = AnswerResult(
            qid=r["qid"],
            answer=r["answer"],
            relevant_docs=r["relevant_docs"],
            relevant_tables=r["relevant_tables"],
            evidence=evidence,
            pandas_query=r["pandas_query"],
            confidence=r["confidence"],
            csv_name=(Path(evidence[0]["csv_path"]).name if evidence else ""),
            has_csv=bool(evidence),
            notes=([r["reason"]] if r.get("reason") else []),
        )
    results = [seen[k] for k in sorted(seen)]

    questions = {}
    for line in QUESTIONS.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            questions[r["id"]] = r["question"]

    cfg = SubmissionConfig(doc_id_variant=args.doc_id, locator_base=args.locator_base)
    out = stage / f"package-{cfg.doc_id_variant}-{cfg.locator_base}"
    try:
        out.mkdir(parents=True)
    except FileExistsError as error:
        raise BuildSafetyError(f"immutable package stage already exists: {out}") from error
    (out / "data").mkdir()
    for source in (stage / "data").iterdir():
        if source.is_file() and source.suffix.lower() == ".csv":
            shutil.copy2(source, out / "data" / source.name)

    zip_path = build_submission(results, questions, out, cfg)
    val = validate_zip(zip_path, questions, corpus_root=CORPUS)
    print(f"\n╔═══ BÀI NỘP  doc_id={cfg.doc_id_variant}  locator_base={cfg.locator_base} ═══╗")
    print(f"  bản ghi   : {val.n_records:,} / {len(questions):,}")
    print(f"  lỗi       : {len(val.errors)}")
    for e in val.errors[:8]:
        print(f"   ✗ {e}")
    stat = replay_zip(zip_path, SCRATCH / "replay")
    print(
        f"  replay    : chạy được {stat['executed']:,} · khớp {stat['matched']:,} · lỗi {stat['error']:,} · không evidence {stat['no_evidence']:,}"
    )
    if stat["executed"]:
        print(f"  bất biến answer == eval(query): {100 * stat['matched'] / stat['executed']:.2f}%")
    package_ok = val.ok and stat["error"] == 0 and stat["matched"] == stat["executed"]
    published = None
    if package_ok:
        published = SUBMIT_DIR / f"submission_{args.run_id}.zip"
        publish_new_file(zip_path, published)
        print(
            f"  ZIP       : {published.relative_to(ROOT)}  ({zip_path.stat().st_size / 1e6:.2f} MB)"
        )
    else:
        print("  CHẶN PUBLISH: submission chưa qua validator/replay", file=sys.stderr)

    manifest_path = stage / f"submission_manifest_{cfg.doc_id_variant}_{cfg.locator_base}.json"
    write_manifest(
        manifest_path,
        submission_manifest(
            PROJECT_PATHS,
            args.run_id,
            stage / "manifest.json",
            zip_path,
            published,
            val,
            stat,
        ),
    )
    print(f"  manifest  : {manifest_path.relative_to(ROOT)}")
    return 0 if package_ok else 1


def cmd_package_v3(args: argparse.Namespace) -> int:
    """Package a Semantic V3 shadow run under the official submission contract."""
    from text2pandas.application.usecases.answer import AnswerResult
    from text2pandas.application.usecases.submission import (
        SubmissionConfig,
        build_submission,
        replay_zip,
        validate_zip,
    )
    from text2pandas.infrastructure.checksums import sha256_file

    stage = PROJECT_PATHS.run_dir("semantic-v3", args.run_id)
    records_path = stage / "records.jsonl"
    if not records_path.is_file():
        raise BuildSafetyError(f"missing Semantic V3 records: {records_path}")
    table_cards = ACTIVE_SNAPSHOTS.a6_path / "dataframe/csv/table_cards.csv"
    with table_cards.open(encoding="utf-8", newline="") as handle:
        locators = {
            str(row["table_uid"]): str(row["evidence_ref"]).replace("|line:", "|")
            for row in csv.DictReader(handle)
        }
    results: list[AnswerResult] = []
    for line in records_path.read_text(encoding="utf-8").splitlines():
        if not line:
            continue
        record = json.loads(line)
        evidence = [
            {
                "variable": str(item["variable"]),
                "csv_path": f"data/{Path(str(item['csv_path'])).name}",
            }
            for item in record.get("evidence") or []
        ]
        table_uids = [str(value) for value in record.get("relevant_tables") or []]
        try:
            tables = [locators[value] for value in table_uids]
        except KeyError as error:
            raise BuildSafetyError(f"A6 table locator missing: {error.args[0]}") from error
        documents = list(dict.fromkeys(value.rsplit("|", 1)[0] for value in tables))
        answer = record.get("answer")
        results.append(
            AnswerResult(
                qid=int(record["qid"]),
                answer=None if answer is None else float(answer),
                relevant_docs=documents,
                relevant_tables=tables,
                evidence=evidence,
                pandas_query=str(record.get("pandas_query") or ""),
                confidence=float(record.get("binding_score") or 0.0),
                csv_name=Path(evidence[0]["csv_path"]).name if evidence else "",
                has_csv=bool(evidence),
                notes=[str(record["reason"])] if record.get("reason") else [],
            )
        )
    questions = {
        int(row["id"]): str(row["question"])
        for row in (
            json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line
        )
    }
    cfg = SubmissionConfig(doc_id_variant=args.doc_id, locator_base=args.locator_base)
    output = stage / f"package-{cfg.doc_id_variant}-{cfg.locator_base}"
    try:
        output.mkdir(parents=True)
    except FileExistsError as error:
        raise BuildSafetyError(f"immutable V3 package already exists: {output}") from error
    (output / "data").mkdir()
    for source in sorted((stage / "data").glob("*.csv")):
        shutil.copy2(source, output / "data" / source.name)
    zip_path = build_submission(results, questions, output, cfg)
    validation = validate_zip(zip_path, questions, corpus_root=CORPUS)
    replay = replay_zip(zip_path, SCRATCH / f"replay-{args.run_id}")
    replay_mismatches = replay["executed"] - replay["matched"]
    report = {
        "schema_version": 1,
        "kind": "text2pandas.semantic_v3_submission_validation",
        "run_id": args.run_id,
        "zip": {"path": str(zip_path.relative_to(ROOT)), "sha256": sha256_file(zip_path)},
        "validation": {
            "records": validation.n_records,
            "errors": validation.errors,
            "warnings": validation.warnings,
        },
        "replay": replay,
        "replay_mismatches": replay_mismatches,
    }
    report_path = stage / f"package-{cfg.doc_id_variant}-{cfg.locator_base}.report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print("\n╔═══════════ SEMANTIC V3 SUBMISSION ═══════════╗")
    print(f"  records          : {validation.n_records:,} / {len(questions):,}")
    print(f"  validation errors: {len(validation.errors):,}")
    print(
        f"  replay           : {replay['executed']:,} executed · "
        f"{replay['matched']:,} matched · {replay['error']:,} errors · "
        f"{replay_mismatches:,} mismatches"
    )
    print(f"  zip              : {zip_path}")
    print(f"  report           : {report_path}")
    return 0 if not validation.errors and not replay["error"] and not replay_mismatches else 1


def cmd_silver(args: argparse.Namespace) -> int:
    """Bronze -> Silver: đặc trưng bảng + ô định dạng dài."""
    from text2pandas.application.usecases.build_silver import build_silver

    cat = _source_or_run_output(args, args.catalog_db, "catalog.sqlite")
    target = _legacy_output(args, "silver.sqlite")
    work = _workdb(f"{args.run_id}-silver.sqlite")
    work.unlink(missing_ok=True)
    rep = build_silver(
        cat,
        CORPUS,
        work,
        offset=args.offset,
        limit=args.limit,
        progress=(lambda k, t, c: print(f"  ... {k} tài liệu · {t:,} bảng · {c:,} ô", flush=True))
        if args.verbose
        else None,
    )
    publish_new_file(work, target)
    print("\n╔═══════════ SILVER ═══════════╗")
    print(f"  tài liệu           : {rep.n_documents:,}")
    print(f"  bảng               : {rep.n_tables:,}")
    print(
        f"  bảng DỮ LIỆU       : {rep.n_data_tables:,}  ({100 * rep.n_data_tables / max(rep.n_tables, 1):.1f}%)"
    )
    print(f"  ô số lưu lại       : {rep.n_cells:,}")
    print(
        f"  bảng có cột-kỳ     : {rep.n_with_period:,}  ({100 * rep.n_with_period / max(rep.n_tables, 1):.1f}%)"
    )
    print(
        f"  bảng có cột Mã số  : {rep.n_with_ma_so:,}  ({100 * rep.n_with_ma_so / max(rep.n_tables, 1):.1f}%)"
    )
    print(f"  thời gian          : {rep.seconds}s")
    print("  ── loại bảng ──")
    for k, v in sorted(rep.by_type.items(), key=lambda x: -x[1]):
        print(f"    {k:<18} {v:>8,}  {100 * v / rep.n_tables:5.1f}%")
    print("  ── nguồn đơn vị ──")
    for k, v in sorted(rep.by_unit_source.items(), key=lambda x: -x[1]):
        print(f"    {k:<18} {v:>8,}  {100 * v / rep.n_tables:5.1f}%")
    print(f"  db                 : {target}")
    return 0


def cmd_cards(args: argparse.Namespace) -> int:
    """Silver -> chỉ mục Table Card (thay cho index văn bản phẳng)."""
    from text2pandas.infrastructure.retrieval.index import build_card_index

    sil = _source_or_run_output(args, args.silver_db, "silver.sqlite")
    target = _legacy_output(args, "card_index.sqlite")
    work = _workdb(f"{args.run_id}-card_index.sqlite")
    work.unlink(missing_ok=True)
    rep = build_card_index(
        sil, work, progress=(lambda n: print(f"  ... {n:,}", flush=True)) if args.verbose else None
    )
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


def cmd_coverage(args: argparse.Namespace) -> int:
    """Audit static semantic routes without claiming end-to-end accuracy."""
    from text2pandas.application.usecases.semantic_coverage import analyze_semantic_coverage
    from text2pandas.pipelines.retrieval.alias_store import load_aliases

    source = Path(args.questions).expanduser().resolve()
    if not source.is_file():
        raise BuildSafetyError(f"missing questions file: {source}")
    questions = [
        json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()
    ]
    report = analyze_semantic_coverage(questions, load_aliases("a6"))
    document = json.dumps(
        report.to_dict(include_records=not args.summary_only),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as handle:
            handle.write(document + "\n")
        print(output)
    else:
        print(document)
    return 0


def cmd_shadow_v3(args: argparse.Namespace) -> int:
    """Run Semantic Query Engine v3 without changing the canonical V2 path."""
    import platform
    import resource
    import sqlite3
    import time
    from collections import Counter
    from datetime import UTC, datetime

    from text2pandas.application.parsing import SemanticParser
    from text2pandas.application.usecases.run_manifest import write_manifest
    from text2pandas.application.usecases.semantic_v3 import (
        SemanticV3Engine,
        classify_differential,
    )
    from text2pandas.application.usecases.semantic_v3_readiness import (
        PromotionMetrics,
        evaluate_promotion,
    )
    from text2pandas.infrastructure.checksums import sha256_file
    from text2pandas.infrastructure.execution import PandasSandboxReplay
    from text2pandas.infrastructure.ontology import load_ontology
    from text2pandas.infrastructure.retrieval import (
        FACT_RETRIEVAL_POLICY_VERSION,
        SqliteOperandRetriever,
    )
    from text2pandas.infrastructure.semantic import (
        A6MetricMentionResolver,
        LegacyVietnameseAnnotator,
        load_promotion_policy,
    )
    from text2pandas.infrastructure.snapshots import verify_active_snapshots
    from text2pandas.infrastructure.source_identity import git_source_identity
    from text2pandas.pipelines.retrieval.alias_store import load_aliases

    verification = verify_active_snapshots(PROJECT_PATHS, scope="a6")
    if not verification.ok:
        detail = "; ".join(item.detail for item in verification.items if not item.ok)
        raise BuildSafetyError(f"active A6 snapshot preflight failed: {detail}")
    source_identity = git_source_identity(ROOT)
    stage = PROJECT_PATHS.run_dir("semantic-v3", args.run_id)
    try:
        stage.mkdir(parents=True)
    except FileExistsError as error:
        raise BuildSafetyError(f"immutable semantic-v3 run already exists: {stage}") from error
    records_path = stage / "records.jsonl"
    questions = [
        json.loads(line)
        for line in QUESTIONS.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    questions = questions[args.offset :]
    if args.limit:
        questions = questions[: args.limit]
    legacy: dict[int, dict[str, object]] = {}
    if args.legacy_run_id:
        legacy_path = PROJECT_PATHS.run_dir("answer", args.legacy_run_id) / "records.jsonl"
        if not legacy_path.is_file():
            raise BuildSafetyError(f"missing legacy records: {legacy_path}")
        for line in legacy_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                record = json.loads(line)
                legacy[int(record["qid"])] = record

    ontology = load_ontology()
    aliases = load_aliases("a6")
    connection = sqlite3.connect(
        f"file:{(ACTIVE_SNAPSHOTS.a6_path / 'silver.db').resolve()}?mode=ro&immutable=1",
        uri=True,
    )
    resolver = A6MetricMentionResolver(
        connection,
        source_build_id=ACTIVE_SNAPSHOTS.a6_build_id,
        entity_aliases=aliases,
    )
    parser = SemanticParser(
        ontology,
        LegacyVietnameseAnnotator(aliases),
        resolver,
    )
    engine = SemanticV3Engine(
        parser,
        SqliteOperandRetriever(
            connection,
            ontology,
            top_k=args.operand_k,
            source_build_id=ACTIVE_SNAPSHOTS.a6_build_id,
        ),
        PandasSandboxReplay(),
    )
    statuses: Counter[str] = Counter()
    reasons: Counter[str] = Counter()
    differentials: Counter[str] = Counter()
    started = time.time()
    evidence_values: dict[str, dict[str, object]] = {}
    try:
        with records_path.open("x", encoding="utf-8") as handle:
            for index, item in enumerate(questions, 1):
                qid = int(item["id"])
                question = str(item["question"])
                result = engine.answer(question, qid=qid)
                differential = classify_differential(legacy.get(qid), result)
                statuses[result.status] += 1
                reasons[result.reason or "OK"] += 1
                differentials[differential] += 1
                record = {
                    "question": question,
                    **result.to_dict(),
                    "differential": differential,
                }
                for evidence in record["evidence"]:
                    table_uid = str(evidence["table_uid"])
                    uids = [str(value) for value in evidence["observation_uids"]]
                    placeholders = ",".join("?" for _ in uids)
                    rows = connection.execute(
                        f"SELECT observation_uid, value_decimal_text FROM observations "
                        f"WHERE observation_uid IN ({placeholders})",
                        uids,
                    ).fetchall()
                    if len(rows) != len(set(uids)):
                        raise BuildSafetyError(
                            f"A6 evidence observations missing: {table_uid}:{uids}"
                        )
                    values = evidence_values.setdefault(table_uid, {})
                    for observation_uid, value in rows:
                        previous = values.setdefault(str(observation_uid), value)
                        if previous != value:
                            raise BuildSafetyError(f"A6 evidence value drift: {observation_uid}")
                    evidence["csv_path"] = str(
                        (stage / "data" / f"{table_uid}.csv").relative_to(ROOT)
                    )
                handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                if args.verbose and index % 25 == 0:
                    print(f"  ... {index:,} câu · {statuses['OK']:,} V3 OK", flush=True)
        evidence_dir = stage / "data"
        evidence_dir.mkdir()
        for table_uid, values in sorted(evidence_values.items()):
            with (evidence_dir / f"{table_uid}.csv").open(
                "x", encoding="utf-8", newline=""
            ) as evidence_handle:
                writer = csv.writer(evidence_handle)
                writer.writerow(("observation_uid", "value"))
                writer.writerows(sorted(values.items()))
    finally:
        connection.close()
    seconds = round(time.time() - started, 3)
    peak_rss_raw = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_rss_bytes = int(peak_rss_raw if platform.system() == "Darwin" else peak_rss_raw * 1024)
    promotion = evaluate_promotion(
        PromotionMetrics(
            questions=len(questions),
            replay_mismatches=sum(
                count
                for reason, count in reasons.items()
                if reason.startswith("TYPED_PANDAS_MISMATCH")
            ),
        ),
        load_promotion_policy(),
    )
    manifest_path = stage / "manifest.json"
    write_manifest(
        manifest_path,
        {
            "schema_version": "3.0",
            "kind": "text2pandas.semantic_v3_shadow_run",
            "run_id": args.run_id,
            "generated_at_utc": datetime.now(UTC).isoformat(),
            "source": source_identity,
            "a6": {
                "build_id": ACTIVE_SNAPSHOTS.a6_build_id,
                "path": str(ACTIVE_SNAPSHOTS.a6_path.relative_to(ROOT)),
            },
            "semantic_schema_version": 3,
            "ontology_fingerprint": ontology.fingerprint,
            "retrieval_policy": FACT_RETRIEVAL_POLICY_VERSION,
            "metric_resolution": resolver.metadata,
            "parameters": {
                "offset": args.offset,
                "limit": args.limit,
                "operand_k": args.operand_k,
                "legacy_run_id": args.legacy_run_id,
            },
            "metrics": {
                "questions": len(questions),
                "statuses": dict(statuses),
                "reasons": dict(reasons.most_common()),
                "differentials": dict(differentials),
                "seconds": seconds,
                "peak_rss_bytes": peak_rss_bytes,
            },
            "promotion": promotion.to_dict(),
            "outputs": {
                "records_jsonl": {
                    "path": str(records_path.relative_to(ROOT)),
                    "sha256": sha256_file(records_path),
                    "records": len(questions),
                },
                "evidence_csvs": [
                    {
                        "path": str(path.relative_to(ROOT)),
                        "sha256": sha256_file(path),
                        "table_uid": path.stem,
                    }
                    for path in sorted((stage / "data").glob("*.csv"))
                ],
            },
        },
    )
    print("\n╔═══════════ SEMANTIC V3 SHADOW ═══════════╗")
    print(f"  câu hỏi          : {len(questions):,}")
    print(f"  V3 OK            : {statuses['OK']:,}")
    print(f"  V3 abstain       : {statuses['ABSTAIN']:,}")
    print(f"  thời gian        : {seconds}s")
    print(f"  promotion        : {promotion.status}")
    for reason, count in reasons.most_common(8):
        print(f"    {reason:<52} {count:>5}")
    if legacy:
        print("  ── differential với canonical V2 ──")
        for reason, count in differentials.most_common():
            print(f"    {reason:<52} {count:>5}")
    print(f"  records          : {records_path}")
    print(f"  manifest         : {manifest_path}")
    return 0


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
    rn = sub.add_parser("run", help="Chạy canonical A6/retrieval pipeline -> ZIP")
    rn.add_argument("--run-id", required=True)
    rn.add_argument("--limit", type=int, default=0)
    rn.add_argument("--offset", type=int, default=0)
    rn.add_argument(
        "--question-id",
        type=int,
        action="append",
        default=[],
        help="Run one source question ID; repeat for an explicit evaluation slice",
    )
    rn.add_argument(
        "--n-tables",
        dest="n_tables",
        type=int,
        default=MAX_RELEVANT_TABLES,
    )
    rn.add_argument("--answer-pool-tables", type=int, default=50)
    rn.add_argument("--no-package", action="store_true")
    rn.add_argument("--doc-id", dest="doc_id", choices=["stripped", "literal"], default="stripped")
    rn.add_argument("--locator-base", dest="locator_base", type=int, choices=[0, 1], default=1)
    pk = sub.add_parser("package", help="Gộp bản ghi đã lưu -> ZIP + kiểm tra + replay")
    pk.add_argument("--run-id", required=True)
    pk.add_argument("--doc-id", dest="doc_id", choices=["stripped", "literal"], default="stripped")
    pk.add_argument("--locator-base", dest="locator_base", type=int, choices=[0, 1], default=1)
    pc = sub.add_parser("parse-check", help="Parse thử bảng, thống kê chất lượng")
    pc.add_argument("--catalog-db", required=True)
    pc.add_argument("--limit", type=int, default=0)
    vf = sub.add_parser("verify", help="Kiểm identity và lineage của active snapshots")
    vf.add_argument("scope", nargs="?", choices=["raw", "a6", "retrieval", "all"], default="all")
    cv = sub.add_parser("coverage", help="Đo static semantic-route coverage, không đo accuracy")
    cv.add_argument(
        "--questions",
        default=str(
            PROJECT_PATHS.repo_root / "data/curated/evaluation/legacy/question_plans_1012.jsonl"
        ),
    )
    cv.add_argument("--output")
    cv.add_argument("--summary-only", action="store_true")
    shadow = sub.add_parser("shadow-v3", help="Chạy Semantic Query Engine v3 ở chế độ shadow")
    shadow.add_argument("--run-id", required=True)
    shadow.add_argument("--limit", type=int, default=0)
    shadow.add_argument("--offset", type=int, default=0)
    shadow.add_argument("--operand-k", type=int, default=20)
    shadow.add_argument("--legacy-run-id")
    package_v3 = sub.add_parser(
        "package-v3", help="Đóng gói, validate và replay một Semantic V3 shadow run"
    )
    package_v3.add_argument("--run-id", required=True)
    package_v3.add_argument(
        "--doc-id", dest="doc_id", choices=["stripped", "literal"], default="stripped"
    )
    package_v3.add_argument(
        "--locator-base", dest="locator_base", type=int, choices=[0, 1], default=1
    )

    args = p.parse_args(argv)
    handlers = {
        "catalog": cmd_catalog,
        "parse-check": cmd_parse_check,
        "index": cmd_index,
        "run": cmd_run,
        "package": cmd_package,
        "silver": cmd_silver,
        "cards": cmd_cards,
        "verify": cmd_verify,
        "coverage": cmd_coverage,
        "shadow-v3": cmd_shadow_v3,
        "package-v3": cmd_package_v3,
    }
    try:
        return handlers[args.cmd](args)
    except BuildSafetyError as error:
        print(f"LỖI AN TOÀN BUILD: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
