"""P0-g bước 4 · truy hồi THEO Ô (mã × năm), không phải top-N toàn cục.

VÌ SAO
------
`/tmp/refs.json` được dựng để TỐI ƯU F2 của bài nộp: top-N toàn cục, N = 3×số ô.
Dùng nó để TRẢ LỜI thì hỏng, vì phép toán cần **một ô cho mỗi (mã, năm)**. Lý do
`UNCERTAIN` nhiều nhất ở lớp `max_min`/`argmax_year` đúng là "thiếu kỳ YYYY":
bảng của năm ấy không lọt vào top-N.

docs/76 §1 đã khuyến nghị fan-out theo mã cho `screen` từ lâu. Ở đây áp dụng cho
tầng đáp án, KHÔNG đụng `src/retrieval/**` và KHÔNG đổi `relevant_tables`.
"""
from __future__ import annotations
import dataclasses, json, os, sqlite3, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
from retrieval.alias_store import load_aliases                     # noqa: E402
from retrieval.evalkit.cli import _load_cfg                        # noqa: E402
from retrieval.evalkit.stages import Bm25StructuralRanker, HardFilterGenerator  # noqa: E402
from retrieval.question_intent import parse_intent                 # noqa: E402

RA = Path("/tmp/refs_cell.json")
MOI_O = 4


def main(argv):
    tu, den = (int(argv[0]), int(argv[1])) if len(argv) >= 2 else (1, 10 ** 9)
    cfg = _load_cfg("base", {})
    alias = load_aliases(brands=cfg.brands)
    conn = sqlite3.connect(f"file:{os.path.expanduser('~/fast/artifacts/retrieval/work.db')}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-200000")
    s1 = HardFilterGenerator(basis_mode=cfg.basis_mode, year_slack=cfg.year_slack)
    s2 = Bm25StructuralRanker(alias, top_k=cfg.top_k_rank, use_hints=cfg.use_hints,
                              basis_mode=cfg.basis_mode, stop_mode=cfg.stop_mode)
    u2r = {u: (e or "").replace("|line:", "|") for u, e in
           conn.execute("SELECT table_uid,evidence_ref FROM table_cards WHERE evidence_ref IS NOT NULL")}
    qs = [json.loads(l) for l in
          (ROOT / "data/external/vifinqa/questions/questions.jsonl").open(encoding="utf-8") if l.strip()]
    # Chỉ fan-out cho các lớp THỰC SỰ cần nhiều ô. `lookup`/`multi_table`/`count`
    # dùng lại `/tmp/refs.json` — fan-out cho chúng chỉ tốn thời gian.
    LOP_CAN = {"ratio", "percentage_change", "difference", "sum", "average",
               "max_min", "argmax_year"}
    PL = {r["id"]: r["lop"] for r in (json.loads(l) for l in
          (ROOT / "data/dev/so_hoc/phan_loai.jsonl").open(encoding="utf-8") if l.strip())}
    cu_refs = json.loads(Path("/tmp/refs.json").read_text())
    done = json.loads(RA.read_text()) if RA.is_file() else {}
    n = 0
    for q in qs[tu - 1:den]:
        if str(q["id"]) in done:
            continue
        if PL.get(q["id"]) not in LOP_CAN:
            done[str(q["id"])] = cu_refs.get(str(q["id"]), [])
            continue
        it = parse_intent(q["question"], alias)
        nams = sorted(it.years) or [None]
        ra: list[str] = []
        for y in nams:
            # `Intent` là dataclass đông cứng — phải dùng `dataclasses.replace`.
            # Bản đầu thử `it.__dict__` nên rơi hết về nhánh `else` và mọi năm
            # đều dùng chung một intent: 3 ref/câu, đúng bằng lúc chưa fan-out.
            it2 = dataclasses.replace(it, years=frozenset([y])) if y else it
            try:
                o1 = s1.generate(conn, q["question"], it2)
                o2 = s2.rank(conn, q["question"], it2, o1)
            except Exception:
                continue
            for x in o2.ranked[:MOI_O * max(1, len(it.targets or it.tickers or [1]))]:
                r = u2r.get(x.table_uid)
                if r and r not in ra:
                    ra.append(r)
        done[str(q["id"])] = ra
        n += 1
        if n % 8 == 0:
            RA.write_text(json.dumps(done))
    RA.write_text(json.dumps(done))
    import statistics as S
    L = [len(v) for v in done.values()]
    print(f"xong {n} cau · tong {len(done)}/1012 · ref/cau median {S.median(L):.0f} max {max(L)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
