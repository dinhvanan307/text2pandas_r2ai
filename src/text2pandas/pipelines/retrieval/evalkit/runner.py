"""Chạy đo end-to-end, hai pha, checkpoint có DẤU VẾT CẤU HÌNH.

VÌ SAO HAI PHA
--------------
Máy build cắt tiến trình sau ~45 s. `collect` ghi tiếp vào checkpoint và bỏ qua
câu đã đo → gọi lại nhiều lần là xong. `report` chỉ đọc checkpoint → đổi cách
tính chỉ số không phải quét lại DB 4,24 GB.

VÌ SAO CHECKPOINT PHẢI MANG FINGERPRINT — LỖI CŨ VÀ CÁCH CHẶN
-------------------------------------------------------------
`eval_retrieval.py` đặt tên checkpoint theo 3 biến môi trường và không ghi gì
khác. Sửa một trọng số trong `rank_s2.py` rồi chạy `collect`: các câu cũ **bị
BỎ QUA** (đã có `id` trong tệp), câu mới chạy với trọng số mới, và `report`
trộn hai cấu hình lại thành một bảng số — **không có gì phát hiện được**.

Ở đây mỗi dòng mang `cfg_sha` = sha256 của cấu hình hiệu lực VÀ identity của
retrieval snapshot (A6 build, index ID, DB digest). `report` ĐẾM số `cfg_sha`
khác nhau và **từ chối in bảng** nếu > 1, kèm hướng dẫn. Trộn cấu hình hoặc
dataset là lỗi im lặng đắt nhất của một khung đo — nó làm mọi A/B sau đó vô
nghĩa mà không ai biết.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from text2pandas.pipelines.retrieval import rank_s2
from text2pandas.pipelines.retrieval.alias_store import load_aliases
from text2pandas.pipelines.retrieval.question_intent import parse_intent
from text2pandas.infrastructure.paths import ProjectPaths
from text2pandas.infrastructure.snapshots import ActiveSnapshots

from . import goldset
from .goldset import GoldProvider, GoldSet, ManualGold, ProxyGoldV2, free_ticker_histogram
from .stages import (Bm25StructuralRanker, HardFilterGenerator, IdentityReranker,
                     period_ends_of)
from .taxonomy import NoGoldReason, classify

__all__ = [
    "EvalConfig",
    "EvaluationDataset",
    "checkpoint_path",
    "collect",
    "resolve_evaluation_dataset",
    "SCHEMA_VERSION",
]

# Phiên bản này vào `EvalConfig.sha`, nên đổi nó là VÔ HIỆU HOÁ mọi checkpoint cũ.
#
#   evalkit-1 → evalkit-2   P0-1: `drop` ở S2 nay gồm cả TÊN công ty, không chỉ mã.
#   evalkit-3 → evalkit-4   S1 giữ legal name độc lập trước nested short brand;
#                         nhận `hiệu số` là comparison (ADR 0004).
#   evalkit-4 → evalkit-5   nhận `tổng số công ty` là entity-screen cue và đưa
#                         subject classifier vào behavior fingerprint (ADR 0005).
#   evalkit-5 → evalkit-6   boundary-safe aliases, merge ticker/name matches và
#                         hoàn thiện comparison cues (ADR 0006).
#   evalkit-6 → evalkit-7   maximal overlapping metric phrases prevent a short
#                         VAS code hint from overriding a specific metric (ADR 0007).
#   evalkit-7 → evalkit-8   bind checkpoints to active A6/retrieval identities;
#                         ranking behavior is unchanged.
#
# VÌ SAO PHẢI BUMP, KHÔNG PHẢI CHỈ SỬA CODE
# -----------------------------------------
# `cfg_sha` băm CẤU HÌNH, không băm CODE. `_done()` coi mọi dòng cùng `cfg_sha`
# là "đã đo" và bỏ qua. Nếu sửa hành vi xếp hạng mà không bump, `collect` sẽ
# tuyên bố "đã đo đủ 1.012 câu" và `report` in lại y nguyên số của bản CÓ LỖI —
# một bản sửa đúng biến thành không có tác dụng gì, im lặng.
#
# Kỷ luật con người không giữ được bất biến này (đã hỏng một lần rồi), nên
# `tests/test_p0_unify.py::test_behavior_fingerprint` băm AST của các module
# quyết định hành vi S2 và đỏ lên nếu chúng đổi mà hằng số này không đổi.
SCHEMA_VERSION = "evalkit-8"


@dataclass(frozen=True, slots=True)
class EvalConfig:
    """Toàn bộ biến quyết định một lần đo. `sha` băm đúng tệp này."""

    basis_mode: str = "soft"
    use_hints: str = "code_single"
    brands: bool | str = True   # True/"full" | "a6" | False — xem alias_store
    top_k_rank: int = 50
    top_k_rerank: int = 10
    year_slack: int = 1
    gold_source: str = "proxy_v2"       # proxy_v2 | manual | manual_then_proxy
    gold_manual_path: str = "data/curated/dev-legacy/gold_v2.jsonl"
    gold_raw_limit: int = 400
    gold_max_trusted: int = 60
    gold_max_tier: str = "T4_anycol_2gram"   # T1|T2|T3|T4 — nới tới đâu
    free_scan: bool = False             # bật histogram mã (chậm, chỉ khi audit)
    ks: tuple[int, ...] = (1, 2, 3, 5, 10, 20, 50)
    budget_s: float = 35.0
    weights: tuple[float, ...] | None = None
    bonuses: dict | None = None
    norm: str = "minmax"              # minmax | rank | maxnorm — xem rank_s2
    stop_mode: str = "fold"           # fold | dau — xem query_terms.STOP_DAU
    per_ticker_k: int | None = None   # quota theo mã cho screen/compare
    # Tiên nghiệm lớp báo cáo cho câu `screen`/`related` — docs/118 §4.
    # ĐO trên gold_v2 (95 câu): F2(A) 0,4549 → 0,4994 · R̄ 0,5981 → 0,6545 ·
    # hit@10 0,8737 → 0,9368 · 13 câu tốt lên / 2 câu xấu đi · `single` và
    # `compare` BẤT BIẾN tuyệt đối (cổng theo mode).
    # CẢNH BÁO: cùng phép đo này chấm bằng proxy_v2 cho ra −0,0248 F2(A).
    # Mâu thuẫn ĐÃ TRUY ĐƯỢC NGUYÊN NHÂN, không phải nhiễu — nhãn proxy sinh
    # bằng khớp cụm nên nghiêng về thuyết minh (58,9% note) trong khi gold
    # nghiêng về báo cáo chính (67,1%). Xem docs/118 §3.
    # MẶC ĐỊNH 0,00 = TẮT. Feedback docs/119 §5.8: +0,0446 là gain trên
    # DEVELOPMENT set (chính 95 câu đã dùng để tìm feature, chọn kinds và quét
    # boost). Không đổi default production trước khi có held-out PASS theo
    # acceptance §7.3. Cấu hình thí nghiệm: profile `s2_primary` (0,60).
    primary_boost: float = 0.00
    primary_modes: tuple[str, ...] = ("screen", "related")
    tag: str = "default"

    @property
    def sha(self) -> str:
        """Băm NGỮ NGHĨA của phép đo — chỉ những gì LỆCH KHỎI mặc định.

        VÌ SAO KHÔNG BĂM TOÀN BỘ DICT — lỗi đã xảy ra thật
        --------------------------------------------------
        Bản đầu băm cả `asdict(self)`. Hệ quả: **thêm một trường mới với giá trị
        mặc định trung tính cũng đổi `sha`**, và làm mồ côi mọi checkpoint cũ.
        Đã xảy ra: thêm `norm="minmax"` + `per_ticker_k=None` — đúng bằng hành vi
        trước đó, không đổi một con số nào — mà 4 lần chạy đủ 1.012 câu
        (`base`, `basis_hard`, `slack0`, `hints_none`) mất hiệu lực và `ab` báo
        thiếu checkpoint.

        Băm theo ĐỘ LỆCH giải quyết trọn vẹn: cấu hình mặc định luôn cho cùng
        một `sha` bất kể sau này thêm bao nhiêu trường, và một cấu hình chỉ đổi
        `sha` khi thứ THẬT SỰ ảnh hưởng kết quả bị đổi.

        Hai trường bị loại khỏi băm, mỗi cái một lý do:
          `budget_s` · ngân sách thời gian, không đổi kết quả;
          `tag`      · chỉ là nhãn, đã nằm trong tên tệp. Loại nó ra còn cho
                       phép hai tag có cùng thiết lập nhận diện được là TRÙNG
                       NGỮ NGHĨA thay vì bị coi là hai phép đo khác nhau.
        """
        goc = asdict(EvalConfig())
        d = {k: v for k, v in asdict(self).items()
             if k not in ("budget_s", "tag") and v != goc[k]}
        d["_schema"] = SCHEMA_VERSION
        blob = json.dumps(d, sort_keys=True, default=str, ensure_ascii=False)
        return hashlib.sha256(blob.encode()).hexdigest()[:16]

    @property
    def deviations(self) -> dict:
        """Những gì cấu hình này LỆCH khỏi mặc định — in ra để đọc được `sha`."""
        goc = asdict(EvalConfig())
        return {k: v for k, v in asdict(self).items()
                if k not in ("budget_s", "tag") and v != goc[k]}

    @property
    def checkpoint_name(self) -> str:
        """Legacy config-only name; production callers use ``checkpoint_path``."""
        return f"ek_{self.tag}_{self.sha}.jsonl"


@dataclass(frozen=True, slots=True)
class EvaluationDataset:
    database: Path
    source_a6_build_id: str
    retrieval_index_id: str
    database_sha256: str

    @property
    def sha(self) -> str:
        payload = {
            "source_a6_build_id": self.source_a6_build_id,
            "retrieval_index_id": self.retrieval_index_id,
            "database_sha256": self.database_sha256,
        }
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]


def resolve_evaluation_dataset(
    root: Path,
    db_path: Path | None = None,
) -> EvaluationDataset:
    """Resolve and verify the immutable retrieval identity used by one eval."""

    if db_path is None:
        paths = ProjectPaths.from_repo_root(root)
        active = ActiveSnapshots.load(paths)
        database = active.retrieval_path / "retrieval.db"
    else:
        database = db_path if db_path.is_absolute() else root / db_path
        database = database.resolve(strict=False)
    if not database.is_file():
        raise FileNotFoundError(f"missing retrieval database: {database}")
    manifest_path = database.parent / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"retrieval evaluation requires a snapshot manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("retrieval snapshot manifest must be an object")
    source_build = str(manifest.get("source_a6_build_id") or "").strip()
    index_id = str(manifest.get("index_id") or "").strip()
    database_sha = str(manifest.get("database_sha256") or "").strip()
    if not source_build or not index_id or len(database_sha) != 64:
        raise ValueError("retrieval snapshot manifest has incomplete identity")
    if manifest.get("database", "retrieval.db") != database.name:
        raise ValueError("retrieval snapshot manifest points to a different database")
    if manifest.get("database_bytes") != database.stat().st_size:
        raise ValueError("retrieval snapshot database size does not match manifest")
    with sqlite3.connect(f"file:{database}?mode=ro", uri=True) as connection:
        meta = dict(connection.execute("SELECT key, value FROM build_meta"))
    if meta.get("build_id") != source_build:
        raise ValueError("retrieval database build_id does not match snapshot manifest")
    return EvaluationDataset(database, source_build, index_id, database_sha)


def checkpoint_path(
    root: Path,
    cfg: EvalConfig,
    db_path: Path | None = None,
) -> tuple[Path, EvaluationDataset, str]:
    dataset = resolve_evaluation_dataset(root, db_path)
    effective = hashlib.sha256(f"{cfg.sha}:{dataset.sha}".encode("ascii")).hexdigest()[:16]
    path = root / "artifacts/runs/retrieval/evalkit" / f"ek_{cfg.tag}_{effective}.jsonl"
    return path, dataset, effective


# ─────────────────────────────────────────────────────────────────────────────
# Quy trách nhiệm mất gold cho ĐÚNG mệnh đề lọc cứng
# ─────────────────────────────────────────────────────────────────────────────

_SQL_GOLD_META = """
SELECT t.table_uid, d.ticker, d.doc_year, d.basis, t.retrieval_ready
FROM table_cards t JOIN documents d ON t.doc_id = d.directory_doc_id
WHERE t.table_uid IN ({ph})
"""


def attribute_drop(conn, gold_uids: frozenset[str], intent, cfg: EvalConfig,
                   cap: int = 40) -> tuple[list[str], list[dict]]:
    """Với mỗi bảng gold BỊ LOẠI, kiểm TỪNG mệnh đề WHERE của S1 xem cái nào loại nó.

    Không đoán, không suy diễn từ tên biến: đọc thẳng `ticker`/`doc_year`/`basis`/
    `retrieval_ready` của chính bảng gold rồi so với vị từ đang hiệu lực. Đây là
    thứ `diag_s1_miss.py` định làm nhưng làm sai (nó in `basis` như nguyên nhân
    kể cả khi `basis_mode="soft"` — lúc đó `basis` KHÔNG nằm trong WHERE).
    """
    uids = sorted(gold_uids)[:cap]
    if not uids:
        return [], []
    ph = ",".join("?" * len(uids))
    rows = conn.execute(_SQL_GOLD_META.format(ph=ph), uids).fetchall()

    tk = set(intent.targets)
    lo = min(intent.years) if intent.years else None
    hi = (max(intent.years) + cfg.year_slack) if intent.years else None
    want_basis = intent.basis if cfg.basis_mode == "hard" else None

    clauses: list[str] = []
    detail: list[dict] = []
    for uid, ticker, year, basis, ready in rows:
        bad = []
        if tk and ticker not in tk:
            bad.append("ticker")
        if lo is not None and not (lo <= year <= hi):
            bad.append("doc_year")
        if want_basis and basis is not None and basis != want_basis:
            bad.append("basis")
        if not ready:
            bad.append("retrieval_ready")
        if bad:
            clauses.extend(bad)
            detail.append({"uid": uid, "ticker": ticker, "year": year,
                           "basis": basis, "clauses": bad})
    return clauses, detail


# ─────────────────────────────────────────────────────────────────────────────
# collect
# ─────────────────────────────────────────────────────────────────────────────

def _questions(root: Path) -> list[dict]:
    p = root / "data/raw/btc/questions/questions.jsonl"
    return [json.loads(l) for l in p.open(encoding="utf-8") if l.strip()]


def _done(ck: Path, cfg_sha: str) -> set[int]:
    """Count rows only when configuration and retrieval identity both match."""
    if not ck.is_file():
        return set()
    out = set()
    for line in ck.open(encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
            if row.get("cfg_sha") == cfg_sha:
                out.add(row["id"])
        except (ValueError, KeyError):
            pass
    return out


def _build_gold_provider(cfg: EvalConfig, root: Path, conn, alias: dict):
    proxy = ProxyGoldV2(raw_limit=cfg.gold_raw_limit,
                        max_trusted=cfg.gold_max_trusted, alias=alias,
                        max_tier=cfg.gold_max_tier)
    if cfg.gold_source == "proxy_v2":
        return proxy, None
    manual = ManualGold(root / cfg.gold_manual_path, conn)
    if cfg.gold_source == "manual":
        return manual, manual
    return proxy, manual      # manual_then_proxy: manual thắng nếu có


def collect(root: Path, cfg: EvalConfig, db_path: Path | None = None,
            limit: int | None = None) -> int:
    try:
        ck, dataset, evaluation_sha = checkpoint_path(root, cfg, db_path)
    except (FileNotFoundError, ValueError, sqlite3.Error, json.JSONDecodeError) as error:
        print(f"✗ retrieval snapshot không hợp lệ: {error}")
        return 2
    db = dataset.database
    outdir = root / "artifacts/runs/retrieval/evalkit"
    outdir.mkdir(parents=True, exist_ok=True)

    alias = load_aliases(brands=cfg.brands)
    qs = _questions(root)
    xong = _done(ck, evaluation_sha)
    todo = [q for q in qs if q["id"] not in xong]
    if limit:
        todo = todo[:limit]
    if not todo:
        print(
            f"đã đo đủ {len(xong)}/{len(qs)} câu cho eval={evaluation_sha} "
            "→ chạy `report`"
        )
        return 0

    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-300000")

    gold_primary, gold_manual = _build_gold_provider(cfg, root, conn, alias)
    s1 = HardFilterGenerator(basis_mode=cfg.basis_mode, year_slack=cfg.year_slack)
    # `alias` là tham số VỊ TRÍ ĐẦU TIÊN của ranker và không có mặc định: quên
    # nó là `TypeError` ngay, không phải một phép đo sai âm thầm (P0-1/P0-3).
    s2 = Bm25StructuralRanker(alias,
                              top_k=cfg.top_k_rank, use_hints=cfg.use_hints,
                              basis_mode=cfg.basis_mode, weights=cfg.weights,
                              bonuses=cfg.bonuses, norm=cfg.norm,
                              per_ticker_k=cfg.per_ticker_k,
                              stop_mode=cfg.stop_mode,
                              primary_boost=cfg.primary_boost,
                              primary_modes=cfg.primary_modes)
    s3 = IdentityReranker(top_k=cfg.top_k_rerank)

    fh = ck.open("a", encoding="utf-8")
    t0 = time.time()
    n = 0
    for q in todo:
        tq = time.time()
        qid, question = q["id"], q["question"]
        intent = parse_intent(question, alias)
        tickers = frozenset(intent.targets) or intent.tickers

        gold: GoldSet | None = None
        if gold_manual is not None and gold_manual.has(qid):
            gold = gold_manual.gold_for(conn, qid, question, tickers,
                                        intent.years, intent.explicit_scope)
        if gold is None or not gold.tables:
            gold = gold_primary.gold_for(conn, qid, question, tickers,
                                         intent.years, intent.explicit_scope)

        o1 = s1.generate(conn, question, intent)
        o2 = s2.rank(conn, question, intent, o1)
        o3 = s3.rerank(conn, question, intent, o2)

        pos_rank = o2.positions_of(gold.tables) if gold.tables else ()
        pos_final = o3.positions_of(gold.tables) if gold.tables else ()
        gold_in_cand = bool(gold.tables & o1.uids) if gold.tables else False

        clauses, detail = ([], [])
        if gold.tables and not gold_in_cand:
            clauses, detail = attribute_drop(conn, gold.tables - o1.uids,
                                            intent, cfg)

        # `entity_suspect` CHỈ đến từ `ProxyGoldV2`, nơi nó được xác lập bằng
        # `COUNT(*) GROUP BY ticker` KHÔNG LIMIT trên đúng cụm đã thử — tức là
        # một phép kiểm không thiên lệch. Không tự suy ra ở đây.
        ent_suspect = bool(gold.trace.get("entity_suspect"))
        free_hist = gold.trace.get("free_top")

        d = classify(
            qid=qid, mode=intent.mode, n_candidates=o1.n,
            n_gold=len(gold.tables) if gold.ok else 0,
            gold_in_candidates=gold_in_cand,
            # ``hits_at`` is the post-rerank position. Passing ``pos_rank``
            # here as well makes a real reranker look harmless: a gold table
            # pushed out by S3 is still classified SUCCESS and
            # F4_RERANK_MISS can never fire. Identity S3 masked that wiring
            # defect because both tuples happen to be equal.
            hits_at=pos_final, hits_at_pre_rerank=pos_rank,
            top_k=cfg.top_k_rerank,
            no_gold_reason=None if gold.ok else (gold.reason or NoGoldReason.NO_PHRASE_MATCH),
            drop_clauses=tuple(clauses), entity_suspect=ent_suspect,
        )

        row = {
            "schema": SCHEMA_VERSION,
            "cfg_sha": evaluation_sha,
            "config_sha": cfg.sha,
            "dataset_sha": dataset.sha,
            "source_a6_build_id": dataset.source_a6_build_id,
            "retrieval_index_id": dataset.retrieval_index_id,
            "cfg_tag": cfg.tag,
            "id": qid, "mode": intent.mode,
            "resolved_by": intent.resolved_by,
            "n_targets": len(intent.targets), "targets": list(intent.targets),
            "years": list(intent.years),
            # ── theo TẦNG, tách bạch ──────────────────────────────────────
            "s1_n": o1.n, "s1_clauses": o1.trace.get("active_clauses"),
            "s2_n": len(o2.ranked), "s3_n": len(o3.ranked),
            "gold_source": gold.source, "gold_how": gold.how,
            "gold_phrase": gold.phrase, "n_gold": len(gold.tables),
            "gold_ok": gold.ok, "gold_strict": gold.strict,
            "gold_tier": gold.tier, "gold_saturated": gold.saturated,
            "gold_raw_hits": gold.n_raw_hits, "gold_free_hits": gold.n_free_hits,
            "gold_reason": gold.reason.value if gold.reason else None,
            "gold_in_s1": gold_in_cand,
            "hits_at_rank": list(pos_rank), "hits_at_final": list(pos_final),
            # ── chẩn đoán ──────────────────────────────────────────────────
            "bucket": d.bucket.value,
            "drop_clauses": sorted(set(clauses)),
            "drop_detail": detail[:5],
            "entity_suspect": ent_suspect,
            "free_ticker_hist": free_hist or None,
            "ms": round(1000 * (time.time() - tq)),
        }
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
        n += 1
        if time.time() - t0 > cfg.budget_s:
            break
    fh.close()
    da = len(xong) + n
    print(f"đo thêm {n} câu · tổng {da}/{len(qs)} · eval={evaluation_sha} · "
          f"{time.time()-t0:.0f}s" + ("" if da >= len(qs) else "  → gọi lại `collect`"))
    _keu_neu_co_loi(outdir, cfg, evaluation_sha)
    return 0


def _keu_neu_co_loi(outdir: Path, cfg: EvalConfig, evaluation_sha: str) -> None:
    """Lỗi truy vấn trong lượt chạy phải KÊU TO và để lại tệp.

    Hai danh sách này (`rank_s2.LAST_ERRORS`, `goldset.GOLD_ERRORS`) trước đây
    chỉ tồn tại trong bộ nhớ tiến trình. Một lô BM25 hỏng làm điểm THIẾU chứ
    không làm chương trình dừng, và một truy vấn gold hỏng làm câu đó thành
    `F0_NO_GOLD` — cả hai đều trông y hệt "kết quả bình thường" ở bảng cuối.

    Đây là lớp lỗi đắt nhất của một khung đo: nó không sai to, nó sai ÍT và im.
    """
    loi = ([f"S2/bm25 · {e}" for e in rank_s2.LAST_ERRORS]
           + [f"GOLD · {e}" for e in goldset.GOLD_ERRORS])
    if not loi:
        return
    p = outdir / f"errors_{cfg.tag}_{evaluation_sha}.txt"
    p.write_text("\n".join(loi) + "\n", encoding="utf-8")
    print(f"\n⚠ {len(loi)} LỖI TRUY VẤN trong lượt chạy — số đo KHÔNG đầy đủ.")
    for e in loi[:5]:
        print(f"    {e}")
    if len(loi) > 5:
        print(f"    … còn {len(loi) - 5} lỗi nữa")
    print(f"    đầy đủ → {p}")
