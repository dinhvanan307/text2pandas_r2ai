"""GOLD GÁN TAY v3 · mẫu phân tầng · POOL bền vững · phiếu · kiểm chặt.

VÌ SAO v3 — hai khuyết tật của v2 đã chặn chính công việc gán
-------------------------------------------------------------
1. **Pool phụ thuộc S2.** v2 lấy top-8 của S2 rồi mới độn thêm. Hệ quả đo được
   ở `docs/80` §4.3: `hit@10` trên gold tay = 1,0000 — một con số **không đọc
   được như recall**, vì bảng gold gần như luôn đến từ trong top-10 của chính
   hệ thống đang bị đo. Đó là thiên lệch *pooling* kinh điển.
2. **`screen` không gán được câu nào.** Câu sàng lọc cần gold cỡ
   `n_mã × n_năm` = 8–14 bảng; trần pool 10 không chứa nổi, và phiếu không in
   `ticker` nên không phân biệt được báo cáo KQKD của mã nào.

v3 đổi ba thứ:

  · **Pool dựng theo Ô `(mã, năm)`**, mỗi ô có hạn ngạch riêng ⇒ câu `screen`
    luôn có chỗ cho mọi mã. Không còn trần cứng 10.
  · **S2 bị giới hạn ≤ 34% pool.** Phần còn lại đến từ tín hiệu KHÔNG dùng
    BM25: `row_labels LIKE`, mã chỉ tiêu, `statement_type`, kỳ, và chính siêu
    dữ liệu `(mã, năm, phạm vi)`.
  · **Pool được GHI RA TỆP** (`gold_tay_pool_v3.jsonl`) trước khi gán. Nhờ vậy
    "gold có nằm trong pool không" trở thành một phép kiểm được, thay vì một
    giả định. Phiếu và bộ kiểm đọc CÙNG một đối tượng.

BA LUẬT CHỐNG NHIỄM — giữ nguyên từ v2, thi hành bằng cấu trúc
--------------------------------------------------------------
1. **Phiếu không có điểm, không có thứ hạng, không cho biết ứng viên đến từ
   nguồn nào.** Nhãn nguồn (`sources`) có trong tệp pool để thống kê thiên
   lệch, nhưng `sheet` KHÔNG in chúng. Người gán nhìn thấy thứ hạng của hệ
   thống là đóng dấu "đúng" lên chính lỗi của hệ thống.
2. **Thứ tự hiển thị là siêu dữ liệu, không phải điểm**: `(mã, năm, phạm vi,
   loại báo cáo, uid)`. Nó nhóm theo ô — thứ mà câu `screen` bắt buộc phải có —
   và không rò rỉ thứ hạng.
3. **Lấy mẫu và dựng pool đều TẤT ĐỊNH.** Trộn bằng `sha256(qid)`; mọi phép
   chọn trong ô đều sắp xếp có thứ tự đầy đủ. Cùng lệnh cho cùng kết quả.

THIÊN LỆCH CÒN LẠI — phải đọc kèm mọi con số
--------------------------------------------
Pool vẫn là pool: bảng đúng nằm ngoài **cả năm** nguồn thì không vào gold, nên
`Recall` trên gold tay là **cận trên**. v3 giảm phụ thuộc S2 chứ không xoá được
trần pool. `stats` in ra tỷ lệ ứng viên đến từ nguồn ngoài FTS để con số này
luôn ở trước mắt.

    python tools/gold_tay.py sample --n 120
    python tools/gold_tay.py pool  --db …/work.db      # dựng + ghi pool
    python tools/gold_tay.py stats                     # thống kê pool
    python tools/gold_tay.py sheet --tu 1 --den 20     # phiếu để gán
    python tools/gold_tay.py resolve --db …/work.db    # nở tiền tố uid
    python tools/gold_tay.py check   --db …/work.db    # kiểm chặt, fail loudly
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.pipelines.retrieval.alias_store import load_aliases            # noqa: E402
from text2pandas.pipelines.retrieval.evalkit.cli import OUTDIR, _load_cfg       # noqa: E402
from text2pandas.pipelines.retrieval.evalkit.goldset import ProxyGoldV2         # noqa: E402
from text2pandas.pipelines.retrieval.evalkit.runner import _questions           # noqa: E402
from text2pandas.pipelines.retrieval.evalkit.stages import (Bm25StructuralRanker,  # noqa: E402
                                      HardFilterGenerator)
from text2pandas.pipelines.retrieval.metric_hint import metric_codes_hint, statement_hint  # noqa: E402
from text2pandas.pipelines.retrieval.query_terms import _fold, content_terms, drop_terms  # noqa: E402
from text2pandas.pipelines.retrieval.question_intent import (BASIS_OF_SCOPE,  # noqa: E402
                                       parse_intent)

DEV = ROOT / "data/curated/dev-legacy"
MAU = DEV / "gold_tay_sample_v2.jsonl"
# P0-c: `sheet`/`stats`/`resolve`/`check` đọc pool v4 (hạn ngạch theo loại
# báo cáo — xem `tools/gold_pool_v4.py` và `docs/83`). v3 giữ lại nguyên vẹn
# để so sánh trước/sau; không tệp nào ghi đè nó.
POOL_V3 = DEV / "gold_tay_pool_v3.jsonl"
POOL_V4 = DEV / "gold_tay_pool_v4.jsonl"
# P0-d: pool v5 = v4 voi phep nhan VAI TRO da siet lai. Phan xu that cho
# thay v4 tieu han ngach vao nham bang (BCLCTT bi tinh la nua bang can doi),
# nen 89/90 slot thieu la do CHON sai chu khong phai do A6 thieu. Xem docs/84.
POOL = DEV / "gold_tay_pool_v5.jsonl"
NHAN = DEV / "gold_v1.jsonl"

# ── tham số dựng pool ────────────────────────────────────────────────────────
POOL_MIN = 16          # sàn cho MỌI câu, kể cả câu một mã một năm
PER_CELL_MIN = 2       # mỗi ô (mã, năm) tối thiểu bấy nhiêu ứng viên
S2_SHARE_MAX = 0.34    # S2 không được chiếm quá ngần này của pool
ROWS_SHOW = 3          # số nhãn dòng in trên phiếu cho mỗi ứng viên
LIKE_CUM_MAX = 10      # số cụm tối đa đưa vào một truy vấn LIKE
LIKE_CAP = 400         # đủ ứng viên `like` thì dừng quét — pool cần ≤ vài chục

# Nguồn nào là "dẫn xuất từ FTS" — dùng để báo cáo thiên lệch cho trung thực.
#
# `sources` của một ứng viên liệt kê MỌI lý do nó có mặt, nên một bảng có thể
# vừa `like` vừa `s2`. Thống kê thiên lệch phải hỏi "việc nó có mặt có PHỤ THUỘC
# vào FTS không", tức `sources ⊆ {s2, proxy}` — chứ không phải "có nhãn s2 nào
# không". Hỏi sai cách sẽ báo 0% ứng viên độc lập ngay cả khi pool hoàn toàn
# dựng được mà không cần S2.
NGUON_FTS = {"s2", "proxy"}


def _phu_thuoc_fts(sources) -> bool:
    """Ứng viên này CHỈ có mặt nhờ FTS (S2/proxy) hay không."""
    return set(sources) <= NGUON_FTS


def _tat_dinh(qid: int) -> str:
    return hashlib.sha256(str(qid).encode()).hexdigest()


# ═════════════════════════════════════════════════════════════════════════════
# sample
# ═════════════════════════════════════════════════════════════════════════════

def cmd_sample(tag: str, n: int) -> int:
    cfg = _load_cfg(tag, {})
    ck = OUTDIR / cfg.checkpoint_name
    if not ck.is_file():
        print(f"✗ chưa có checkpoint {ck.name} — chạy `collect --tag {tag}`")
        return 2
    rows = {}
    for line in ck.open(encoding="utf-8"):
        if line.strip():
            r = json.loads(line)
            rows[r["id"]] = r
    tang: dict[str, list[dict]] = {"T1": [], "T2": [], "screen": []}
    for r in rows.values():
        if r.get("mode") == "screen":
            tang["screen"].append(r)
        elif r.get("gold_tier") == "T1_row_ngram":
            tang["T1"].append(r)
        elif r.get("gold_tier") == "T2_row_2gram":
            tang["T2"].append(r)
    moi_tang = n // 3
    q_by_id = {q["id"]: q["question"] for q in _questions(ROOT)}
    ra = []
    for ten, ds in tang.items():
        ds.sort(key=lambda r: _tat_dinh(r["id"]))
        lay = ds[:moi_tang]
        if len(lay) < moi_tang:
            print(f"⚠ tầng {ten} chỉ có {len(ds)} câu, cần {moi_tang}")
        for r in lay:
            ra.append({"id": r["id"], "tang": ten, "question": q_by_id[r["id"]],
                       "mode": r.get("mode"), "targets": r.get("targets"),
                       "years": r.get("years"),
                       "proxy_n_gold": r.get("n_gold"),
                       "proxy_tier": r.get("gold_tier")})
    ra.sort(key=lambda r: r["id"])
    DEV.mkdir(parents=True, exist_ok=True)
    MAU.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ra),
                   encoding="utf-8")
    print(f"{len(ra)} câu → {MAU.relative_to(ROOT)}")
    print("   " + " · ".join(f"{k}={sum(1 for r in ra if r['tang']==k)}"
                             for k in tang))
    return 0


# ═════════════════════════════════════════════════════════════════════════════
# pool
# ═════════════════════════════════════════════════════════════════════════════

_SQL_META = """
SELECT t.table_uid, d.ticker, d.doc_year, d.basis, t.statement_type,
       t.periods, t.units, t.metric_codes, t.section_text,
       t.n_observations, t.execution_ready_obs, t.evidence_ref
FROM table_cards t JOIN documents d ON t.doc_id = d.directory_doc_id
WHERE t.table_uid IN ({ph})
"""


def _meta_of(conn, uids: list[str]) -> dict[str, dict]:
    """Siêu dữ liệu của ứng viên. Chia lô để không vượt trần tham số SQLite."""
    ra: dict[str, dict] = {}
    for i in range(0, len(uids), 800):
        lot = uids[i:i + 800]
        ph = ",".join("?" * len(lot))
        for row in conn.execute(_SQL_META.format(ph=ph), lot):
            (uid, tk, yr, basis, stmt, per, unit, codes, sec,
             nobs, ready, ref) = row
            ra[uid] = {"table_uid": uid, "ticker": tk, "doc_year": yr,
                       "basis": basis, "statement_type": stmt,
                       "periods": per or "", "units": unit or "",
                       "metric_codes": codes or "", "section_text": sec or "",
                       "n_obs": nobs, "ready_obs": ready,
                       "evidence_ref": ref or ""}
    return ra


def _rows_of(conn, uids: list[str], terms: list[str]) -> dict[str, list[str]]:
    """Nhãn dòng, ưu tiên dòng chứa nhiều từ nội dung của câu hỏi nhất."""
    low = [_fold(t) for t in terms]      # `row_labels` lưu dạng bỏ dấu — xem `_cum`
    ra: dict[str, list[str]] = {}
    for i in range(0, len(uids), 800):
        lot = uids[i:i + 800]
        ph = ",".join("?" * len(lot))
        for uid, rl in conn.execute(
                f"SELECT table_uid, row_labels FROM table_cards_fts "
                f"WHERE table_uid IN ({ph})", lot):
            nhan = [x.strip() for x in str(rl or "").split("\n") if x.strip()]
            if len(nhan) == 1:
                nhan = [x.strip() for x in nhan[0].split(" | ") if x.strip()]
            nhan.sort(key=lambda s: -sum(1 for t in low if t in s.lower()))
            # `nhan` đã ở dạng bỏ dấu nên `low` cũng phải bỏ dấu, nếu không thứ
            # tự nhãn dòng in ra phiếu là ngẫu nhiên chứ không phải "khớp nhất".
            ra[uid] = nhan[:ROWS_SHOW]
    return ra


def _cum(terms: list[str]) -> list[str]:
    """Cụm 3 rồi 2 từ liên tiếp, **ĐÃ BỎ DẤU** — dài trước để khớp chặt hơn.

    BỎ DẤU LÀ BẮT BUỘC, không phải tuỳ chọn. `table_cards_fts.row_labels` lưu ở
    dạng đã bỏ dấu và hạ chữ thường (`doanh thu thuan ban hang…`). Đo trên
    work.db thật: `LIKE '%doanh thu thuần%'` khớp **0** bảng, `LIKE
    '%doanh thu thuan%'` khớp **3.234** bảng.

    Bản đầu của v3 quên điều này và nguồn `like` — nguồn ĐỘC LẬP quan trọng
    nhất, lý do chính khiến pool bớt phụ thuộc S2 — chỉ đóng góp 1,6% ứng viên.
    Nó không nổ, không cảnh báo; nó chỉ lặng lẽ không tìm thấy gì.
    """
    fold = [_fold(t) for t in terms]
    out = []
    for n in (3, 2):
        out += [" ".join(fold[i:i + n]) for i in range(len(fold) - n + 1)]
    return [c for c in out if c.strip()]


def _like_hits(conn, uids: list[str], terms: list[str]) -> set[str]:
    """Bảng có `row_labels` CHỨA một cụm của câu hỏi — bằng LIKE, KHÔNG FTS.

    Đây là nguồn độc lập quan trọng nhất: `Bm25StructuralRanker` và
    `ProxyGoldV2` đều hỏi cùng một chỉ mục FTS5 với cùng phép chuẩn hoá, nên
    hai nguồn ấy mù ở cùng chỗ. Một pool chỉ gồm chúng KHÔNG phải pool đa nguồn.
    """
    ra: set[str] = set()
    cums = _cum(terms)[:LIKE_CUM_MAX]
    if not cums or not uids:
        return ra
    # MỘT truy vấn cho mỗi lô, OR mọi cụm — không phải một truy vấn cho mỗi
    # (cụm × lô). Câu `screen` có tới 3.403 ứng viên; cách cũ là 10 cụm × 5 lô
    # = 50 lần quét `row_labels`, và nó làm `pool` không chạy nổi trong một
    # lượt. Kết quả trả về y hệt, chỉ khác số vòng.
    dk = " OR ".join(["lower(row_labels) LIKE ?"] * len(cums))
    mau = [f"%{c}%" for c in cums]
    for i in range(0, len(uids), 800):
        lot = uids[i:i + 800]
        ph = ",".join("?" * len(lot))
        for (u,) in conn.execute(
                f"SELECT table_uid FROM table_cards_fts "
                f"WHERE table_uid IN ({ph}) AND ({dk})", (*lot, *mau)):
            ra.add(u)
        if len(ra) >= LIKE_CAP:
            break          # đủ để lấp mọi ô; quét tiếp không đổi pool
    return ra


def _cells_of(intent, meta: dict[str, dict]) -> list[tuple[str, int | None]]:
    """Ô `(mã, năm)` mà pool phải phủ.

    Với `screen`, đây chính là lý do v3 tồn tại: câu "trong nhóm A, B, C…" cần
    một bảng cho MỖI mã MỖI năm, nên pool phải cấp hạn ngạch theo ô chứ không
    xếp chung một rổ rồi cắt ở 10 — cắt như thế thì vài mã biến mất khỏi phiếu
    và người gán không thể gán đúng dù muốn.
    """
    tk = list(intent.targets) or sorted({m["ticker"] for m in meta.values()})
    yrs: list[int | None] = list(intent.years) or [None]
    return [(t, y) for t in tk for y in yrs]


def _uu_tien(m: dict, co: dict) -> tuple:
    """Thứ tự chọn TRONG ô — bằng tín hiệu độc lập, KHÔNG bằng điểm S2.

    Chỉ dùng để CHỌN ai vào pool. Thứ tự này không bao giờ lộ ra phiếu.
    """
    return (0 if co["like"] else 1,
            0 if co["code"] else 1,
            0 if co["stmt"] else 1,
            0 if co["period"] else 1,
            -m["ready_obs"],
            m["table_uid"])


def build_pool(conn, qid: int, question: str, intent, s2_uids: list[str],
               proxy_uids: list[str], s1_uids: frozenset[str],
               alias: dict) -> dict:
    """Dựng pool cho một câu. Trả về bản ghi ghi thẳng ra `gold_tay_pool_v3`."""
    terms = content_terms(question, drop=drop_terms(intent.targets, alias))
    codes = metric_codes_hint(question)
    stmt_goi = statement_hint(question)
    ends = {f"{y}-12-31" for y in intent.years}

    uids = sorted(s1_uids)
    meta = _meta_of(conn, uids)
    like = _like_hits(conn, uids, terms)

    co: dict[str, dict] = {}
    for u, m in meta.items():
        co[u] = {
            "like": u in like,
            "code": bool(codes) and bool(
                {c for c in m["metric_codes"].split(",") if c} & set(codes)),
            "stmt": bool(stmt_goi) and m["statement_type"] == stmt_goi,
            "period": bool(ends) and any(e in m["periods"] for e in ends),
        }

    cells = _cells_of(intent, meta)
    n_cell = max(1, len(cells))
    quota = max(PER_CELL_MIN, math.ceil(POOL_MIN / n_cell))

    theo_o: dict[tuple, list[str]] = defaultdict(list)
    for u, m in meta.items():
        theo_o[(m["ticker"], m["doc_year"])].append(u)

    chon: dict[str, list[str]] = {}          # uid → nguồn
    thieu_o: list[str] = []
    for tk, yr in cells:
        # Năm `None` (câu không nêu năm) ⇒ gộp mọi năm của mã đó.
        ung = ([u for (t, y), us in theo_o.items() if t == tk for u in us]
               if yr is None else list(theo_o.get((tk, yr), [])))
        if not ung:
            thieu_o.append(f"{tk}/{yr}")
            continue
        ung.sort(key=lambda u: _uu_tien(meta[u], co[u]))
        for u in ung[:quota]:
            ng = [k for k in ("like", "code", "stmt", "period") if co[u][k]] or ["meta"]
            chon.setdefault(u, []).extend(ng)

    # Bù cho đủ SÀN. Hạn ngạch theo ô có thể không lấp đủ `POOL_MIN` khi vài ô
    # nghèo ứng viên. Bù bằng CHÍNH thứ tự ưu tiên độc lập ở trên, quét mọi ô —
    # tuyệt đối không bù bằng S2, vì bù bằng S2 là đưa thiên lệch quay lại qua
    # cửa sau.
    if len(chon) < POOL_MIN:
        con_lai = sorted((u for u in meta if u not in chon),
                         key=lambda u: _uu_tien(meta[u], co[u]))
        for u in con_lai[:POOL_MIN - len(chon)]:
            ng = [k for k in ("like", "code", "stmt", "period") if co[u][k]] or ["meta"]
            chon[u] = ng

    # Proxy: nguồn thứ tư, tính vào rổ FTS khi thống kê thiên lệch.
    for u in proxy_uids[:max(2, quota // 2)]:
        if u in meta:
            chon.setdefault(u, []).append("proxy")

    # S2 vào SAU CÙNG và bị chặn trần: S ≤ 0,515·I giữ S/(I+S) ≤ 34%.
    doc_lap = len(chon)
    tran_s2 = int(doc_lap * S2_SHARE_MAX / (1 - S2_SHARE_MAX))
    them = 0
    for u in s2_uids:
        if them >= tran_s2:
            break
        if u in meta and u not in chon:
            chon[u] = ["s2"]
            them += 1
        elif u in chon:
            chon[u].append("s2")

    ds = sorted(chon, key=lambda u: (meta[u]["ticker"] or "",
                                     meta[u]["doc_year"] or 0,
                                     meta[u]["basis"] or "",
                                     meta[u]["statement_type"] or "", u))
    nhan_dong = _rows_of(conn, ds, terms)
    ung_vien = []
    for u in ds:
        m = dict(meta[u])
        m["row_labels"] = nhan_dong.get(u, [])
        m["sources"] = sorted(set(chon[u]))          # CHỈ để thống kê
        ung_vien.append(m)
    return {
        "id": qid, "question": question, "mode": intent.mode,
        "targets": list(intent.targets), "years": list(intent.years),
        "explicit_scope": intent.explicit_scope,
        "terms": terms[:12], "codes": sorted(codes),
        "n_s1": len(s1_uids), "cells": [f"{t}/{y}" for t, y in cells],
        "cells_missing": thieu_o, "quota_per_cell": quota,
        "candidates": ung_vien,
    }


def cmd_pool(db: Path, tu: int, den: int) -> int:
    if not MAU.is_file():
        print(f"✗ chưa có {MAU.name} — chạy `sample` trước")
        return 2
    mau = [json.loads(l) for l in MAU.open(encoding="utf-8") if l.strip()]
    cfg = _load_cfg("base", {})
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-200000")
    alias = load_aliases(brands=cfg.brands)
    s1 = HardFilterGenerator(basis_mode=cfg.basis_mode, year_slack=cfg.year_slack)
    s2 = Bm25StructuralRanker(alias, top_k=cfg.top_k_rank, use_hints=cfg.use_hints,
                              basis_mode=cfg.basis_mode, stop_mode=cfg.stop_mode)
    proxy = ProxyGoldV2(raw_limit=cfg.gold_raw_limit,
                        max_trusted=cfg.gold_max_trusted, alias=alias,
                        max_tier=cfg.gold_max_tier)
    cu = {}
    if POOL.is_file():
        for line in POOL.open(encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                cu[r["id"]] = r

    n = 0
    for r in mau[tu - 1:den]:
        qid, q = r["id"], r["question"]
        it = parse_intent(q, alias)
        o1 = s1.generate(conn, q, it)
        o2 = s2.rank(conn, q, it, o1)
        g = proxy.gold_for(conn, qid, q, frozenset(it.targets) or it.tickers,
                           it.years, it.explicit_scope)
        cu[qid] = build_pool(conn, qid, q, it,
                             [x.table_uid for x in o2.ranked],
                             sorted(g.tables), o1.uids, alias)
        n += 1
        # Ghi lại SAU MỖI CÂU. Máy build cắt tiến trình ~45 s; gom hết rồi mới
        # ghi nghĩa là một lần cắt xoá sạch công của cả lượt.
        POOL.write_text("".join(json.dumps(cu[k], ensure_ascii=False) + "\n"
                                for k in sorted(cu)), encoding="utf-8")
    print(f"dựng pool cho {n} câu · tổng {len(cu)} câu trong "
          f"{POOL.relative_to(ROOT)}")
    return 0


# ═════════════════════════════════════════════════════════════════════════════
# stats
# ═════════════════════════════════════════════════════════════════════════════

def cmd_stats() -> int:
    if not POOL.is_file():
        print(f"✗ chưa có {POOL.name} — chạy `pool` trước")
        return 2
    ds = [json.loads(l) for l in POOL.open(encoding="utf-8") if l.strip()]
    mau = {r["id"]: r for r in
           (json.loads(l) for l in MAU.open(encoding="utf-8") if l.strip())}
    kich = sorted(len(r["candidates"]) for r in ds)
    thieu = [r for r in ds if r["cells_missing"]]
    rong = [r for r in ds if not r["candidates"]]
    nguon = Counter()
    n_ung = 0
    ngoai_fts = 0
    for r in ds:
        for c in r["candidates"]:
            n_ung += 1
            nguon.update(c["sources"])
            if not _phu_thuoc_fts(c["sources"]):
                ngoai_fts += 1
    screen = [r for r in ds if r["mode"] == "screen"]
    screen_du = [r for r in screen if not r["cells_missing"]]

    print(f"\nPOOL v3 · {len(ds)} câu")
    print(f"  theo tầng: " + " · ".join(
        f"{k}={v}" for k, v in Counter(
            mau[r['id']]['tang'] for r in ds if r['id'] in mau).items()))
    print(f"\n  kích thước pool  min={kich[0]} · median={kich[len(kich)//2]} "
          f"· max={kich[-1]} · trung bình={sum(kich)/len(kich):.1f}")
    print(f"  câu đủ điều kiện gán (pool ≥ 1 ứng viên) : {len(ds) - len(rong)}/{len(ds)}")
    print(f"  câu pool RỖNG (không gán được)           : {len(rong)}")
    print(f"  câu thiếu ô (mã,năm) nào đó              : {len(thieu)}")
    print(f"\n  screen: {len(screen)} câu · đủ MỌI ô (mã × năm): "
          f"{len(screen_du)}/{len(screen)}")
    if screen:
        sk = sorted(len(r["candidates"]) for r in screen)
        print(f"  screen · pool min={sk[0]} median={sk[len(sk)//2]} max={sk[-1]}")
    chi_fts = n_ung - ngoai_fts
    chi_s2 = sum(1 for r in ds for c in r["candidates"] if c["sources"] == ["s2"])
    print(f"\n  ứng viên: {n_ung}")
    print(f"    có ít nhất một lý do NGOÀI FTS : {ngoai_fts} ({ngoai_fts/n_ung:.1%})")
    print(f"    CHỈ có mặt nhờ FTS (s2/proxy)  : {chi_fts} ({chi_fts/n_ung:.1%})")
    # Con số quyết định cho thiên lệch pooling: bao nhiêu ứng viên có mặt CHỈ
    # vì S2 xếp chúng cao. Đây là phần mà `hit@K` trên gold tay sẽ bị thổi lên.
    print(f"    CHỈ vì S2 xếp cao (trần {S2_SHARE_MAX:.0%})  : "
          f"{chi_s2} ({chi_s2/n_ung:.1%})")
    print("  theo nhãn nguồn (một ứng viên có thể mang nhiều nhãn):")
    for k, v in nguon.most_common():
        print(f"      {k:8s} {v:5d}  ({v/n_ung:.1%})")
    for r in thieu[:5]:
        print(f"  ! q{r['id']} thiếu ô: {r['cells_missing'][:6]}")
    return 0


# ═════════════════════════════════════════════════════════════════════════════
# sheet — đọc TỪ POOL, không hỏi lại DB
# ═════════════════════════════════════════════════════════════════════════════

_BASIS = {"consolidated": "HN", "separate": "RIENG"}


def _phieu_gon(r: dict, tang: str) -> None:
    """Phiếu GỌN, nhóm theo ô `(mã, năm)`, mỗi ứng viên đúng MỘT dòng.

    Vì sao cần bản gọn: câu `screen` có tới 14 ô và 45 ứng viên; phiếu đầy đủ
    tốn ~4 dòng mỗi ứng viên nên một câu chiếm gần 200 dòng. Người gán phải
    thấy CẢ câu cùng lúc mới đối chiếu được ô này với ô kia — cuộn qua bốn màn
    hình là cách chắc chắn để bỏ sót một mã.

    Vẫn KHÔNG in `sources`, không in điểm, không in thứ hạng.
    """
    print(f"\n### q{r['id']} [{tang}] {len(r['targets'])} mã × "
          f"{len(r['years'])} năm = {len(r['cells'])} ô · pool "
          f"{len(r['candidates'])} · scope={r['explicit_scope'] or '-'}")
    print(f"Q: {r['question'][:200]}")
    print(f"terms: {r['terms'][:10]}"
          + (f"  codes: {r['codes']}" if r["codes"] else ""))
    if r["cells_missing"]:
        print(f"⚠ THIẾU Ô: {r['cells_missing']}")
    o_hien = None
    for c in r["candidates"]:
        o = f"{c['ticker']}/{c['doc_year']}"
        dau = f"{o:12s}" if o != o_hien else " " * 12
        o_hien = o
        per = "K" if any(f"{y}-12-31" in c["periods"]
                         for y in (r["years"] or [])) else "·"
        ma = "M" if r["codes"] and (
            {x for x in c["metric_codes"].split(",") if x} & set(r["codes"])) \
            else "·"
        bs = {"consolidated": "HN ", "separate": "RIE"}.get(c["basis"], "?? ")
        row = (c["row_labels"] or [""])[0][:54]
        print(f"{dau}{c['table_uid']} {bs} {c['statement_type'][:16]:16s} "
              f"{per}{ma} {row}")


def cmd_sheet(tu: int, den: int, gon: bool = False) -> int:
    if not POOL.is_file():
        print(f"✗ chưa có {POOL.name} — chạy `pool` trước")
        return 2
    ds = {r["id"]: r for r in
          (json.loads(l) for l in POOL.open(encoding="utf-8") if l.strip())}
    mau = [json.loads(l) for l in MAU.open(encoding="utf-8") if l.strip()]
    for m in mau[tu - 1:den]:
        r = ds.get(m["id"])
        if r is None:
            print(f"\n### q{m['id']} — CHƯA DỰNG POOL")
            continue
        if gon:
            _phieu_gon(r, m["tang"])
            continue
        print(f"\n### q{r['id']} [{m['tang']}] mode={r['mode']} "
              f"targets={r['targets']} years={r['years']} "
              f"scope={r['explicit_scope'] or '-'} "
              f"ô={len(r['cells'])} pool={len(r['candidates'])}")
        print(f"Q: {r['question']}")
        print(f"terms: {r['terms']}"
              + (f"  codes: {r['codes']}" if r["codes"] else ""))
        if r["cells_missing"]:
            print(f"⚠ THIẾU Ô: {r['cells_missing']}")
        o_hien = None
        for c in r["candidates"]:
            o = (c["ticker"], c["doc_year"])
            if o != o_hien:
                print(f"  ── {c['ticker']} · {c['doc_year']} "
                      f"{'─' * 40}")
                o_hien = o
            per_hit = any(f"{y}-12-31" in c["periods"] for y in (r["years"] or []))
            code_hit = bool(r["codes"]) and bool(
                {x for x in c["metric_codes"].split(",") if x} & set(r["codes"]))
            print(f"  {c['table_uid']} {_BASIS.get(c['basis'], str(c['basis']))[:5]:5s} "
                  f"{c['statement_type']:16s} {'KỲ✓' if per_hit else 'kỳ✗'} "
                  f"{'MÃ✓' if code_hit else '   '} obs={c['n_obs']}/{c['ready_obs']}")
            if c["section_text"]:
                print(f"     sec: {c['section_text'][:66]}")
            for nh in c["row_labels"]:
                print(f"     row: {nh[:66]}")
    return 0


# ═════════════════════════════════════════════════════════════════════════════
# resolve
# ═════════════════════════════════════════════════════════════════════════════

def cmd_resolve(db: Path) -> int:
    """Nở tiền tố `table_uid` thành uid ĐẦY ĐỦ; NỔ khi nhập nhằng.

    Phiếu v2 in `uid[:8]` cho gọn và người gán chép đúng cái nhìn thấy — 28/28
    dòng nhãn mang uid cụt. v3 in uid đầy đủ nên lỗi này không tái diễn, nhưng
    lệnh vẫn ở lại để nở những nhãn đã lỡ ghi cụt.
    """
    if not NHAN.is_file():
        print(f"✗ chưa có {NHAN.name}")
        return 2
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    theo: dict[str, list[str]] = {}
    for (u,) in conn.execute("SELECT table_uid FROM table_cards"):
        theo.setdefault(u[:8], []).append(u)
    ra, doi, loi = [], 0, []
    for line in NHAN.open(encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        uids = r.get("gold_table_uids")
        if uids:
            moi = []
            for u in uids:
                if len(u) >= 16:
                    moi.append(u)
                    continue
                kp = theo.get(u[:8], [])
                if len(kp) == 1:
                    moi.append(kp[0])
                    doi += 1
                else:
                    loi.append((r["id"], u, len(kp)))
                    moi.append(u)
            r["gold_table_uids"] = moi
        ra.append(r)
    if loi:
        print(f"✗ {len(loi)} tiền tố KHÔNG nở được (0 hoặc >1 bảng khớp):")
        for qid, u, n in loi[:10]:
            print(f"    q{qid}: {u} → {n} bảng khớp")
        return 1
    NHAN.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in ra),
                    encoding="utf-8")
    print(f"✓ nở {doi} tiền tố thành table_uid đầy đủ")
    return 0


# ═════════════════════════════════════════════════════════════════════════════
# check — KIỂM CHẶT, fail loudly, KHÔNG tự sửa dữ liệu
# ═════════════════════════════════════════════════════════════════════════════

def kiem(nhan: list[dict], pool: dict[int, dict], meta_all: dict[str, dict],
         tien_to: dict[str, list[str]], year_slack: int = 1) -> list[str]:
    """Trả về DANH SÁCH LỖI. Rỗng = sạch. Không sửa gì, không bỏ qua gì.

    Chín lớp lỗi, mỗi lớp là một cách gold có thể sai mà bảng số vẫn in ra
    bình thường:

      1. `table_uid` cụt (không nở được / nhập nhằng)
      2. `table_uid` không tồn tại
      3. nhãn trùng — cùng `id` hai lần, hoặc cùng uid hai lần trong một nhãn
      4. bảng gold KHÔNG có `ticker`
      5. `ticker` của bảng gold không nằm trong mã đã phân giải
      6. `doc_year` ngoài khoảng câu hỏi hỏi (kể cả `year_slack`)
      7. `basis` mâu thuẫn với phạm vi câu hỏi NÊU RÕ
      8. câu `screen` thiếu ứng viên ở một ô (mã, năm)
      9. bảng gold nằm NGOÀI pool đã dựng
    """
    loi: list[str] = []
    da_thay: set[int] = set()

    for r in nhan:
        qid = r.get("id")
        if qid is None:
            loi.append("một dòng nhãn thiếu khoá `id`")
            continue
        if qid in da_thay:
            loi.append(f"q{qid}: NHÃN TRÙNG — `id` xuất hiện nhiều hơn một lần")
            continue
        da_thay.add(qid)

        p = pool.get(qid)
        if p is None:
            loi.append(f"q{qid}: chưa dựng pool cho câu này — chạy `pool` trước")
            continue

        if r.get("uncertain"):
            if not r.get("reason"):
                loi.append(f"q{qid}: đánh dấu UNCERTAIN nhưng thiếu `reason`")
            continue

        uids = r.get("gold_table_uids") or []
        if not uids:
            loi.append(f"q{qid}: không UNCERTAIN mà cũng không có gold_table_uids")
            continue
        if len(set(uids)) != len(uids):
            loi.append(f"q{qid}: NHÃN TRÙNG — cùng một table_uid ghi hai lần")

        trong_pool = {c["table_uid"] for c in p["candidates"]}
        muc_tieu = set(p["targets"])
        nam = p["years"]
        lo = min(nam) if nam else None
        hi = (max(nam) + year_slack) if nam else None
        scope = p.get("explicit_scope")
        basis_can = BASIS_OF_SCOPE.get(scope) if scope else None

        for u in uids:
            if len(u) < 16:
                kp = tien_to.get(u[:8], [])
                loi.append(f"q{qid}: table_uid CỤT {u!r} ({len(kp)} bảng khớp "
                           f"tiền tố) — chạy `resolve`")
                continue
            m = meta_all.get(u)
            if m is None:
                loi.append(f"q{qid}: table_uid KHÔNG TỒN TẠI trong work.db: {u}")
                continue
            if not m["ticker"]:
                loi.append(f"q{qid}: bảng {u} KHÔNG có ticker")
            elif muc_tieu and m["ticker"] not in muc_tieu:
                loi.append(f"q{qid}: ticker LỆCH — bảng {u} thuộc {m['ticker']}, "
                           f"câu hỏi về {sorted(muc_tieu)}")
            if lo is not None and m["doc_year"] is not None \
                    and not (lo <= m["doc_year"] <= hi):
                loi.append(f"q{qid}: doc_year LỆCH — bảng {u} năm "
                           f"{m['doc_year']}, câu hỏi {nam} (slack {year_slack})")
            if basis_can and m["basis"] and m["basis"] != basis_can:
                loi.append(f"q{qid}: basis LỆCH — câu nêu rõ {scope!r} "
                           f"(={basis_can}) nhưng bảng {u} là {m['basis']}")
            if u not in trong_pool:
                loi.append(f"q{qid}: gold NẰM NGOÀI POOL — {u}. Gold phải là một "
                           f"ứng viên đã được đưa ra để gán, nếu không thì "
                           f"`Recall` trên gold này không có nghĩa")

    for qid, p in sorted(pool.items()):
        if p["mode"] == "screen" and p["cells_missing"]:
            loi.append(f"q{qid}: SCREEN thiếu ứng viên ở ô "
                       f"{p['cells_missing'][:8]} — không gán đủ được")
    return loi


def cmd_check(db: Path) -> int:
    if not NHAN.is_file():
        print(f"✗ chưa có {NHAN.name}")
        return 2
    if not POOL.is_file():
        print(f"✗ chưa có {POOL.name} — chạy `pool` trước")
        return 2
    nhan = [json.loads(l) for l in NHAN.open(encoding="utf-8") if l.strip()]
    pool = {r["id"]: r for r in
            (json.loads(l) for l in POOL.open(encoding="utf-8") if l.strip())}
    mau = {r["id"]: r for r in
           (json.loads(l) for l in MAU.open(encoding="utf-8") if l.strip())}
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    meta_all, tien_to = {}, {}
    for uid, tk, yr, basis in conn.execute(
            "SELECT t.table_uid, d.ticker, d.doc_year, d.basis FROM table_cards t "
            "JOIN documents d ON t.doc_id = d.directory_doc_id"):
        meta_all[uid] = {"ticker": tk, "doc_year": yr, "basis": basis}
        tien_to.setdefault(uid[:8], []).append(uid)

    loi = kiem(nhan, pool, meta_all, tien_to)

    gan = [r for r in nhan if not r.get("uncertain")]
    kt = sorted(len(r.get("gold_table_uids") or []) for r in gan)
    print(f"nhãn: {len(nhan)} dòng · UNCERTAIN "
          f"{sum(1 for r in nhan if r.get('uncertain'))} · gán được {len(gan)}")
    print("theo tầng: " + str(dict(Counter(
        mau[r["id"]]["tang"] for r in gan if r["id"] in mau))))
    if kt:
        print(f"|gold| tay: median={kt[len(kt)//2]} mean={sum(kt)/len(kt):.2f} "
              f"max={kt[-1]} · số câu đúng 1 bảng={sum(1 for x in kt if x == 1)}")
    if loi:
        print(f"\n✗ {len(loi)} LỖI — KHÔNG tự sửa, phải xử tay:")
        for e in loi[:40]:
            print(f"    {e}")
        if len(loi) > 40:
            print(f"    … còn {len(loi) - 40} lỗi nữa")
        return 1
    print("\n✓ sạch: uid đầy đủ và tồn tại · ticker/doc_year/basis khớp câu hỏi "
          "· không nhãn trùng · gold nằm trong pool · screen đủ ô")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="gold_tay")
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample"); s.add_argument("--tag", default="base")
    s.add_argument("--n", type=int, default=120)
    for ten in ("pool", "resolve", "check"):
        s = sub.add_parser(ten)
        s.add_argument("--db", default="data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db")
        if ten == "pool":
            s.add_argument("--tu", type=int, default=1)
            s.add_argument("--den", type=int, default=120)
    s = sub.add_parser("sheet"); s.add_argument("--tu", type=int, default=1)
    s.add_argument("--den", type=int, default=20)
    s.add_argument("--gon", action="store_true",
                   help="phiếu gọn một dòng/ứng viên, nhóm theo ô (mã, năm)")
    sub.add_parser("stats")
    ns = ap.parse_args(argv)

    if ns.cmd == "sample":
        return cmd_sample(ns.tag, ns.n)
    if ns.cmd == "sheet":
        return cmd_sheet(ns.tu, ns.den, ns.gon)
    if ns.cmd == "stats":
        return cmd_stats()
    db = Path(ns.db) if str(ns.db).startswith("/") else ROOT / ns.db
    if ns.cmd == "pool":
        return cmd_pool(db, ns.tu, ns.den)
    if ns.cmd == "resolve":
        return cmd_resolve(db)
    return cmd_check(db)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
