"""Điểm vào duy nhất của khung đo.

    python3 src/text2pandas/pipelines/retrieval/evalkit/cli.py collect --tag base        (gọi lại tới hết)
    python3 src/text2pandas/pipelines/retrieval/evalkit/cli.py collect --tag base --loop  (tự lặp tới hết)
    python3 src/text2pandas/pipelines/retrieval/evalkit/cli.py report  --tag base
    python3 src/text2pandas/pipelines/retrieval/evalkit/cli.py ab --a base --b nobrand

Cấu hình nạp từ `configs/retrieval/eval_v1.yaml`; cờ dòng lệnh ghi đè. Mọi biến
quyết định kết quả đều đi vào `cfg_sha` → checkpoint không thể trộn hai cấu hình.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "src"))


def _preflight() -> None:
    """Kiểm môi trường TRƯỚC khi import, để lỗi thiếu gói ra thông báo hành động
    được thay vì `ModuleNotFoundError` từ tận `alias_store.py`.

    Vì sao cần: dự án có NHIỀU interpreter cùng lúc (venv của người dùng, python
    Homebrew, python hệ thống, máy build). `PyYAML` là dependency LÕI đã khai ở
    `pyproject.toml`, nhưng traceback mặc định trỏ vào `import yaml` ở một tệp
    không liên quan gì tới lệnh người dùng vừa gõ, và **không nói đang chạy bằng
    interpreter nào** — mà đó chính là thông tin quyết định.

    BA ĐIỀU HÀM NÀY PHẢI LÀM ĐÚNG, học từ ba lần chẩn đoán sai liên tiếp
    -------------------------------------------------------------------
    1. In lệnh cài **gắn với interpreter đang chạy**: `{sys.executable} -m pip`.
       Bản đầu in trần "pip install pyyaml" — sai và gây mất thời gian, vì khi
       `python3` và `pip` trỏ vào hai môi trường khác nhau thì cài đúng lệnh đó
       vẫn không sửa được gì. Đã xảy ra thật: `python3` →
       `/opt/homebrew/opt/python@3.14/bin/python3.14` trong khi env
       `(text2pandas)` đang bật.

    2. Phát hiện **môi trường đang bật nhưng KHÔNG được dùng** — và phát hiện
       ĐÚNG. `sys.prefix != sys.base_prefix` là phép thử **venv**, KHÔNG phải
       conda: một **conda env luôn có `sys.prefix == sys.base_prefix`** vì nó là
       một bản Python đầy đủ, không phải lớp phủ. Dùng phép thử venv cho conda
       cho ra **false positive 100%** — bản trước chặn đúng interpreter đúng của
       dự án (`/opt/anaconda3/envs/text2pandas/bin/python`) và báo nó "ngoài
       venv". Phép thử đúng: so `sys.prefix` với `$CONDA_PREFIX`/`$VIRTUAL_ENV`.

    3. **KHÔNG fatal khi không có gì thiếu.** Bản trước biến một gợi ý chẩn đoán
       thành cổng chặn cứng: `yaml` có đủ, mọi thứ chạy được, mà vẫn `SystemExit`.
       Fail-closed thuộc về nơi TÍNH ĐÚNG bị đe doạ; ở đây nếu `yaml` import
       được thì lần đo là hợp lệ, nên chỉ **cảnh báo ra stderr rồi chạy tiếp**.

    Evalkit KHÔNG thêm dependency nào: ngoài `yaml`, mọi thứ nó dùng là stdlib
    (sqlite3, json, csv, math, hashlib, argparse, dataclasses, enum, pathlib).
    """
    if sys.version_info < (3, 10):
        raise SystemExit(
            f"✗ cần Python ≥ 3.10, đang chạy {sys.version_info.major}."
            f"{sys.version_info.minor}\n"
            "  (mã tránh cú pháp 3.11+ có chủ đích — xem taxonomy._StrEnum)")

    env_dir, env_kind = _active_env()
    dung_env = _dang_dung(env_dir)
    lech_env = env_dir is not None and not dung_env

    missing = [m for m in ("yaml",) if importlib.util.find_spec(m) is None]

    # ── không thiếu gì: im lặng, hoặc CẢNH BÁO (không chặn) nếu lệch môi trường ──
    if not missing:
        if lech_env:
            print(f"⚠ {env_kind} đang bật là `{env_dir}` nhưng đang chạy bằng "
                  f"`{sys.executable}`.\n"
                  "  Mọi gói cần thiết đều có nên vẫn chạy tiếp. Nếu về sau thiếu gói, "
                  "đây là chỗ cần xem trước.", file=sys.stderr)
        return

    # ── thiếu gói: đây mới là lỗi chặn ────────────────────────────────────────
    L = ["✗ thiếu gói: " + ", ".join(missing),
         f"  interpreter: {sys.executable}  (Python "
         f"{sys.version_info.major}.{sys.version_info.minor})"]
    if lech_env:
        L += [f"  ⚠ {env_kind} đang bật là `{env_dir}` — KHÁC interpreter đang chạy.",
              "    Rất có thể gói đã cài vào đó rồi, chỉ là không được dùng."]
    # Lệnh GẮN với interpreter — `pip` trần có thể trỏ môi trường khác.
    goi_y = f"{env_dir}/bin/python" if lech_env else sys.executable
    L += [f'  sửa:  "{goi_y}" -m pip install pyyaml pytest',
          "  (PyYAML là dependency LÕI ở pyproject.toml, không phải của evalkit;",
          "   pytest để chạy 47 test offline + `make dp-test`)",
          "  hoặc: tools/evalkit doctor   # xem interpreter nào có gói gì"]
    if sys.version_info >= (3, 14):
        L += ["",
              "  ⚠ Python 3.14: `requirements.lock` ghim pandas==2.3.3 · numpy==2.4.6",
              "    pyarrow==25.0.0 · lxml==6.1.1 — nhóm này có thể chưa có wheel cho",
              "    3.14. Evalkit chạy được (chỉ cần yaml), nhưng `make dp-test` sẽ vỡ.",
              "    `requires-python` của dự án là >=3.11."]
    raise SystemExit("\n".join(L))


def _active_env() -> tuple[str | None, str]:
    """Môi trường Python đang bật, nếu có. Trả `(đường dẫn, loại)`."""
    if os.environ.get("VIRTUAL_ENV"):
        return os.environ["VIRTUAL_ENV"], "venv"
    if os.environ.get("CONDA_PREFIX"):
        return os.environ["CONDA_PREFIX"], "conda env"
    return None, ""


def _dang_dung(env_dir: str | None) -> bool:
    """Interpreter đang chạy có THUỘC `env_dir` không.

    Phép thử duy nhất đúng cho CẢ venv VÀ conda: so `sys.prefix` với đường dẫn
    môi trường. `sys.prefix != sys.base_prefix` chỉ đúng cho venv — conda env là
    một bản Python đầy đủ nên hai giá trị đó BẰNG NHAU, và dùng nó cho conda cho
    ra false positive 100%.
    """
    if env_dir is None:
        return True
    try:
        return Path(sys.prefix).resolve() == Path(env_dir).resolve()
    except OSError:
        return str(sys.prefix).rstrip("/") == str(env_dir).rstrip("/")


_preflight()

from text2pandas.pipelines.retrieval.evalkit.report import (guard_single_config, load_rows,  # noqa: E402
                                      render, write_artifacts)
from text2pandas.pipelines.retrieval.evalkit.runner import EvalConfig, collect  # noqa: E402

CFG_PATH = ROOT / "configs/retrieval/eval_v1.yaml"
OUTDIR = ROOT / "artifacts/runs/retrieval/evalkit"


def _load_cfg(tag: str, overrides: dict) -> EvalConfig:
    base: dict = {}
    if CFG_PATH.is_file():
        import yaml
        doc = yaml.safe_load(CFG_PATH.read_text(encoding="utf-8")) or {}
        base.update(doc.get("defaults") or {})
        base.update((doc.get("profiles") or {}).get(tag) or {})
    base.update({k: v for k, v in overrides.items() if v is not None})
    base["tag"] = tag
    if "ks" in base and base["ks"]:
        base["ks"] = tuple(base["ks"])
    if base.get("weights"):
        base["weights"] = tuple(float(x) for x in base["weights"])
    # YAML trả về list; `EvalConfig` khai tuple. Không ép kiểu thì `sha` của
    # cùng một cấu hình sẽ khác nhau tuỳ nó đến từ YAML hay từ code.
    if base.get("primary_modes") is not None:
        base["primary_modes"] = tuple(base["primary_modes"])
    known = set(EvalConfig.__dataclass_fields__)
    unknown = set(base) - known
    if unknown:
        raise SystemExit(f"✗ khoá cấu hình không nhận ra: {sorted(unknown)}")
    return EvalConfig(**base)


def _ck(cfg: EvalConfig) -> Path:
    return OUTDIR / cfg.checkpoint_name


def cmd_collect(cfg: EvalConfig, loop: bool, limit: int | None) -> int:
    if not loop:
        return collect(ROOT, cfg, limit=limit)
    # Tự lặp: mỗi vòng tự dừng ở `budget_s`, vòng sau tiếp tục. Dùng khi chạy
    # trực tiếp trên máy không bị cắt tiến trình.
    for i in range(200):
        rc = collect(ROOT, cfg, limit=limit)
        if rc != 0:
            return rc
        ck = _ck(cfg)
        if ck.is_file():
            n = sum(1 for l in ck.open(encoding="utf-8") if l.strip())
            if n >= 1012:
                return 0
        time.sleep(0.2)
    return 0


def cmd_report(cfg: EvalConfig) -> int:
    ck = _ck(cfg)
    if not ck.is_file():
        print(f"✗ chưa có checkpoint {ck.name} — chạy `collect --tag {cfg.tag}`")
        return 2
    rows = load_rows(ck)
    print(render(rows, cfg.ks, cfg.top_k_rerank))
    paths = write_artifacts(rows, OUTDIR, cfg.ks, cfg.top_k_rerank, cfg.tag)
    for k, v in paths.items():
        print(f"  {k:4s} → {v.relative_to(ROOT)}")
    return 0


def cmd_ab(tag_a: str, tag_b: str, paired: bool = True) -> int:
    """So HAI cấu hình trên CÙNG tập câu.

    `paired=True` (mặc định) giao tập `id` của hai checkpoint trước khi tính chỉ
    số. Đó là điều kiện để delta quy được cho cấu hình: một cấu hình chạy 350
    câu và một cấu hình chạy 1.012 câu KHÔNG so được với nhau, vì 662 câu chênh
    lệch có độ khó khác hẳn — chính là cái bẫy đã làm doc 74 báo R@1 = 0,7551
    trên một tập con dễ hơn toàn đề.

    Ngoài ra chỉ giữ câu mà CẢ HAI cấu hình dựng được gold. Một cấu hình đo được
    nhiều câu hơn thì nó đo thêm phần khó, và trung bình sẽ tụt — đọc như "tệ
    hơn" là đọc sai.
    """
    from text2pandas.pipelines.retrieval.evalkit.metrics import (candidate_hit_rate, f2_at_k,
                                           f2_at_policy, hit_rate_at_k,
                                           hit_rate_at_policy, mrr, ndcg_at_k)
    from text2pandas.pipelines.retrieval.evalkit.report import policy_n_map, to_outcomes

    raw: dict[str, dict[int, dict]] = {}
    for tag in (tag_a, tag_b):
        cfg = _load_cfg(tag, {})
        ck = _ck(cfg)
        if not ck.is_file():
            print(f"✗ thiếu checkpoint cho tag={tag} ({ck.name})")
            print(f"  chạy: cli.py collect --tag {tag}")
            return 2
        rows = load_rows(ck)
        guard_single_config(rows)
        raw[tag] = {r["id"]: r for r in rows}

    ids_a, ids_b = set(raw[tag_a]), set(raw[tag_b])
    common = ids_a & ids_b
    if paired:
        ok = {i for i in common
              if raw[tag_a][i].get("gold_ok") and raw[tag_b][i].get("gold_ok")}
    else:
        ok = common
    print(f"tập so sánh: |A|={len(ids_a)} |B|={len(ids_b)} "
          f"giao={len(common)} · cả hai có gold={len(ok)}"
          + ("   (PAIRED)" if paired else "   (KHÔNG paired)"))
    if len(common) < min(len(ids_a), len(ids_b)):
        print(f"  ⚠ {min(len(ids_a),len(ids_b))-len(common)} câu chỉ có ở một bên — đã loại")
    if not ok:
        print("✗ không có câu chung nào dựng được gold ở cả hai cấu hình")
        return 1

    out = {}
    for tag in (tag_a, tag_b):
        rows = [raw[tag][i] for i in sorted(ok)]
        oc = to_outcomes(rows)
        nmap = policy_n_map(rows)
        g1 = [r for r in rows if r.get("n_gold") == 1]
        oc_g1 = to_outcomes(g1)
        out[tag] = {
            "n": len(rows),
            # Hai số QUYẾT ĐỊNH, đặt lên đầu: F2 dưới chính sách N thật, và F2
            # trên slice |gold|=1 (nơi proxy gold ít lạc quan nhất).
            "F2@N*": f2_at_policy(oc, nmap),
            "hit@N*": hit_rate_at_policy(oc, nmap),
            "F2@1_g1": f2_at_k(oc_g1, 1) if g1 else 0.0,
            "hit@1_g1": hit_rate_at_k(oc_g1, 1) if g1 else 0.0,
            "n_g1": len(g1),
            "cand_hit": candidate_hit_rate(oc),
            "hit@1": hit_rate_at_k(oc, 1), "hit@3": hit_rate_at_k(oc, 3),
            "hit@10": hit_rate_at_k(oc, 10), "mrr": mrr(oc),
            "ndcg@10": ndcg_at_k(oc, 10),
            "F2@1": f2_at_k(oc, 1), "F2@3": f2_at_k(oc, 3),
            "F2@10": f2_at_k(oc, 10),
            "n_s1_median": sorted(r.get("s1_n", 0) for r in rows)[len(rows) // 2],
        }
    a, b = out[tag_a], out[tag_b]
    print()
    print(f"{'chỉ số':12s} {tag_a:>14s} {tag_b:>14s} {'delta':>10s}")
    for k in ("F2@N*", "hit@N*", "F2@1_g1", "hit@1_g1", "n_g1",
              "cand_hit", "hit@1", "hit@3", "hit@10", "mrr", "ndcg@10",
              "F2@1", "F2@3", "F2@10", "n_s1_median"):
        va, vb = a[k], b[k]
        d = vb - va
        mark = " ↑" if d > 1e-9 else (" ↓" if d < -1e-9 else "  ")
        print(f"{k:12s} {va:>14.4f} {vb:>14.4f} {d:>+10.4f}{mark}")

    # Câu đổi chiều — nơi đọc ra CƠ CHẾ, không chỉ đọc ra con số.
    flip_up, flip_dn = [], []
    for i in sorted(ok):
        ha = raw[tag_a][i].get("hits_at_rank") or []
        hb = raw[tag_b][i].get("hits_at_rank") or []
        ra = min(ha) if ha else 10**6
        rb = min(hb) if hb else 10**6
        if ra > 10 >= rb:
            flip_up.append((i, ra, rb))
        elif rb > 10 >= ra:
            flip_dn.append((i, ra, rb))
    print("\n  ĐỌC CHO ĐÚNG — hai số, hai vai trò khác nhau:")
    print("  · F2@N*   = so SÁNH TƯƠNG ĐỐI tốt nhất (dùng đúng N bài nộp sẽ nộp).")
    print("              KHÔNG phải dự báo điểm tuyệt đối: proxy gold có |gold|")
    print("              median 8 nên mẫu số 4g bị phồng ⇒ F2@N* BI QUAN có hệ thống.")
    print("  · F2@1_g1 = ước lượng TUYỆT ĐỐI đáng tin nhất (slice |gold|=1).")
    print("  · F2@K cố định giả định nộp cùng K mọi câu — không phải chính sách thật.")
    print(f"\nvào được top-10 nhờ {tag_b}: {len(flip_up)} câu"
          f"  ·  rớt khỏi top-10 vì {tag_b}: {len(flip_dn)} câu")
    for lbl, v in (("+", flip_up), ("−", flip_dn)):
        for i, ra, rb in v[:8]:
            print(f"  {lbl} q{i:<5d} hạng {('-' if ra>10**5 else ra)} → "
                  f"{('-' if rb>10**5 else rb)}")

    (OUTDIR / f"ab_{tag_a}_vs_{tag_b}.json").write_text(
        json.dumps({"paired_ids": len(ok), "a": a, "b": b,
                    "flip_in": flip_up[:60], "flip_out": flip_dn[:60]},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="evalkit")
    sub = ap.add_subparsers(dest="cmd", required=True)

    for name in ("collect", "report"):
        s = sub.add_parser(name)
        s.add_argument("--tag", default="base")
        s.add_argument("--basis-mode", choices=("soft", "hard"))
        s.add_argument("--use-hints",
                       choices=("none", "stmt", "code", "both", "code_single"))
        s.add_argument("--brands", type=int, choices=(0, 1))
        s.add_argument("--top-k-rank", type=int)
        s.add_argument("--top-k-rerank", type=int)
        s.add_argument("--gold-source",
                       choices=("proxy_v2", "manual", "manual_then_proxy"))
        s.add_argument("--free-scan", type=int, choices=(0, 1))
        s.add_argument("--budget-s", type=float)
        if name == "collect":
            s.add_argument("--loop", action="store_true")
            s.add_argument("--limit", type=int)

    s = sub.add_parser("ab")
    s.add_argument("--a", required=True)
    s.add_argument("--b", required=True)
    s.add_argument("--no-paired", action="store_true",
                   help="KHÔNG giao tập id (chỉ dùng khi biết rõ mình đang làm gì)")

    ns = ap.parse_args(argv)
    if ns.cmd == "ab":
        return cmd_ab(ns.a, ns.b, paired=not ns.no_paired)

    ov = {
        "basis_mode": ns.basis_mode, "use_hints": ns.use_hints,
        "brands": None if ns.brands is None else bool(ns.brands),
        "top_k_rank": ns.top_k_rank, "top_k_rerank": ns.top_k_rerank,
        "gold_source": ns.gold_source,
        "free_scan": None if ns.free_scan is None else bool(ns.free_scan),
        "budget_s": ns.budget_s,
    }
    cfg = _load_cfg(ns.tag, ov)
    if ns.cmd == "collect":
        return cmd_collect(cfg, ns.loop, ns.limit)
    return cmd_report(cfg)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
