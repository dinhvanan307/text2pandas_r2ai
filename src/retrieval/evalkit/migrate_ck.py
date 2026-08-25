"""Gán lại `cfg_sha` cho checkpoint cũ sau khi cách băm đổi — KHÔNG chạy lại đo.

VÌ SAO CẦN
----------
`EvalConfig.sha` đổi từ "băm toàn bộ dict" sang "băm chỉ độ lệch khỏi mặc định"
(xem docstring của nó). Việc đó làm mồ côi các checkpoint đã chạy đủ 1.012 câu.

PHÉP KIỂM AN TOÀN · CHỨNG MINH, KHÔNG PHỎNG ĐOÁN
-----------------------------------------------
Bản đầu của script này kiểm bằng heuristic ("hai trường mới có ở trong `deviations`
không"). Dry-run cho thấy heuristic đó **SAI và nguy hiểm**: nó đề nghị gán cả ba
tệp `ek_base_*` về cùng một sha, và vì xử lý theo thứ tự sorted thì tệp
`ek_base_3189bebc…` chỉ có **20 câu** sẽ thắng, còn checkpoint đủ **1.012 câu**
bị từ chối vì "đích đã tồn tại". Kết quả: `base` âm thầm tụt từ 1.012 xuống 20
câu, và mọi A/B sau đó so trên 20 câu mà không ai biết.

Phép kiểm đúng là một **chứng minh**: tính lại `sha` theo CÔNG THỨC CŨ cho cấu
hình HIỆN TẠI; nếu nó trùng đúng sha trong tên tệp thì checkpoint đó đã được chạy
bằng chính cấu hình này — gán lại là bảo toàn ngữ nghĩa. Không trùng thì đó là
một cấu hình KHÁC (gold builder khác, `raw_limit` khác, …) và phải để nguyên.

Phép kiểm này xử lý cả hai chiều bằng một luật: nó cứu `s2_rank_norm` (chạy
đúng `norm=rank`, heuristic cũ từ chối oan) và loại `ek_base_3189bebc…` +
`ek_base_da55067a…` (chạy bằng gold builder cũ có bug return sớm).

Thêm hai chốt: mỗi tag chỉ được có **đúng một** tệp đủ điều kiện, và **không bao
giờ ghi đè** tệp đích đã tồn tại.

Đây là việc CHỈ LÀM MỘT LẦN. Sau bản này, thêm trường mới với mặc định trung
tính không còn làm mồ côi checkpoint nào nữa.

    tools/evalkit migrate --dry-run
    tools/evalkit migrate
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "src"))

from retrieval.evalkit.cli import _load_cfg, _preflight  # noqa: E402
from retrieval.evalkit.runner import SCHEMA_VERSION  # noqa: E402

_preflight()

OUT = ROOT / "artifacts/retrieval/evalkit"


# THỜI KỲ LƯỢC ĐỒ · tập trường KHÔNG tồn tại ở thời kỳ đó.
#
# Vì sao cần nhiều thời kỳ: công thức cũ băm TOÀN BỘ dict, nên hash phụ thuộc
# vào chính TẬP TRƯỜNG của dataclass lúc chạy. Thêm `norm`/`per_ticker_k` đổi tập
# trường ⇒ không thể tái lập hash cũ nếu chỉ thử một thời kỳ. Bản trước mắc đúng
# lỗi này và từ chối SẠCH mọi tệp, kể cả tệp hợp lệ.
_THOI_KY = {
    "E2_hien_tai": frozenset(),                         # sau khi thêm 2 trường
    "E1_truoc_norm": frozenset({"norm", "per_ticker_k"}),
}


def sha_legacy(cfg, bo: frozenset[str]) -> str:
    """CÔNG THỨC CŨ (băm toàn bộ dict, KÈM `tag`) cho một thời kỳ lược đồ.

    `bo` = tập trường chưa tồn tại ở thời kỳ đó, phải loại khỏi dict để tái lập
    đúng hash lịch sử. Tồn tại CHỈ để chứng minh một checkpoint cũ được sinh bởi
    đúng cấu hình hiện tại; xoá được sau khi migrate xong.
    """
    from dataclasses import asdict

    d = {k: v for k, v in asdict(cfg).items() if k not in bo}
    d.pop("budget_s", None)
    d["_schema"] = SCHEMA_VERSION
    blob = json.dumps(d, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha256(blob.encode()).hexdigest()[:16]


def khop_thoi_ky(cfg, sha_cu: str) -> str | None:
    """Tên thời kỳ mà công thức cũ tái lập đúng `sha_cu`, hoặc None.

    Khớp ở thời kỳ E1 chứng minh: mọi trường TỒN TẠI lúc đó đều trùng cấu hình
    hiện tại, và hai trường thêm sau có giá trị hiệu lực = mặc định (vì chúng
    chưa tồn tại). Đúng bằng điều kiện cần để gán lại bảo toàn ngữ nghĩa.
    """
    for ten, bo in _THOI_KY.items():
        if sha_legacy(cfg, bo) == sha_cu:
            return ten
    return None


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="migrate")
    ap.add_argument("--dry-run", action="store_true")
    ns = ap.parse_args(argv)

    files = sorted(OUT.glob("ek_*.jsonl"))
    if not files:
        print("không có checkpoint nào")
        return 0

    # ── PHA 1 · xét từng tệp, chưa ghi gì ────────────────────────────────────
    ke_hoach: list[tuple[Path, str, str, str, int]] = []   # f, tag, sha_cu, sha_moi, n
    print(f"{'tệp':50s} {'câu':>5s}  kết luận")
    for f in files:
        # ek_<tag>_<sha>.jsonl — tag có thể chứa `_`, sha là đoạn CUỐI.
        tag, _, sha_cu = f.stem[len("ek_"):].rpartition("_")
        rows = [json.loads(l) for l in f.open(encoding="utf-8") if l.strip()]
        n = len({r["id"] for r in rows})
        if not tag:
            print(f"{f.name:50s} {n:5d}  bỏ qua · không phân giải được tag")
            continue
        try:
            cfg = _load_cfg(tag, {})
        except SystemExit:
            print(f"{f.name:50s} {n:5d}  bỏ qua · tag không có trong eval_v1.yaml")
            continue
        if sha_cu == cfg.sha:
            print(f"{f.name:50s} {n:5d}  đã đúng sha")
            continue
        # ── CHỨNG MINH: công thức cũ trên cấu hình HIỆN TẠI phải cho đúng sha
        #    trong tên tệp. Không trùng ⇒ checkpoint này thuộc cấu hình KHÁC.
        ky = khop_thoi_ky(cfg, sha_cu)
        if ky is None:
            print(f"{f.name:50s} {n:5d}  ✗ ĐỂ NGUYÊN · cấu hình KHÁC "
                  "(không thời kỳ nào tái lập được sha này)")
            continue
        print(f"{f.name:50s} {n:5d}  ✓ khớp {ky}")
        ke_hoach.append((f, tag, sha_cu, cfg.sha, n))

    # ── PHA 2 · chốt chặn: mỗi tag đúng MỘT tệp, đích chưa tồn tại ───────────
    theo_tag: dict[str, list] = {}
    for item in ke_hoach:
        theo_tag.setdefault(item[1], []).append(item)
    an: list = []
    for tag, v in sorted(theo_tag.items()):
        if len(v) > 1:
            print(f"\n✗ tag `{tag}` có {len(v)} tệp cùng đủ điều kiện — DỪNG, "
                  "không đoán tệp nào là đúng:")
            for f, _, sc, _, n in v:
                print(f"    {f.name}  ({n} câu)")
            return 2
        f, _, sha_cu, sha_moi, n = v[0]
        dest = OUT / f"ek_{tag}_{sha_moi}.jsonl"
        if dest.exists():
            print(f"\n✗ {dest.name} đã tồn tại — KHÔNG ghi đè. Bỏ qua {f.name}.")
            continue
        an.append((f, dest, sha_cu, sha_moi, n))

    print(f"\n{'sẽ gán lại':50s} {'câu':>5s}  {'sha cũ':>16s} → {'sha mới':>16s}")
    for f, dest, sha_cu, sha_moi, n in an:
        print(f"{f.name:50s} {n:5d}  {sha_cu:>16s} → {sha_moi:>16s}"
              + ("   [dry-run]" if ns.dry_run else ""))
        if ns.dry_run:
            continue
        with dest.open("w", encoding="utf-8") as g:
            for line in f.open(encoding="utf-8"):
                if not line.strip():
                    continue
                r = json.loads(line)
                r["cfg_sha"] = sha_moi
                r["cfg_sha_truoc_migrate"] = sha_cu     # giữ dấu vết truy nguyên
                g.write(json.dumps(r, ensure_ascii=False) + "\n")

    print(f"\ngán lại: {len(an)}/{len(files)} tệp")
    if not ns.dry_run and an:
        print("Tệp CŨ giữ nguyên (không xoá) — đối chiếu được nếu cần.")
        print("Mỗi dòng mới mang `cfg_sha_truoc_migrate`.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
