#!/usr/bin/env python3
"""B4 — sinh `reports/gate_report.json` theo định dạng doc 12 §5.4. CHỈ ĐỌC."""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from text2pandas.pipelines.a6.gates import evaluate_gates


# Chi ba cong nay duoc phep BLOCKED theo Plan 17 §RC-20.
ALLOWED_BLOCKED = ("SG", "C2", "C3")


def _load(path):
    if not path:
        return {"status": "MISSING", "path": None}
    p = Path(path)
    if not p.is_file():
        return {"status": "MISSING", "path": str(p)}
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"status": "UNREADABLE", "path": str(p), "error": str(e)}
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    return {"status": "OK", "path": str(p), "sha256": h, "data": d}


def _verdict_of(name, d):
    """Doc ket luan cua tung loai report theo dung truong that cua no."""
    if name == "rebuild_check":
        v = d.get("verdict") or d.get("C0") or d.get("result")
        return str(v).upper() if v is not None else None
    if name == "no_loss":
        return str((d.get("summary") or {}).get("verdict", "")).upper() or None
    if name == "unresolved":
        s = d.get("summary") or {}
        if s.get("n_query_errors"):
            return "FAIL"
        return "PASS"
    if name == "differential":
        s = d.get("summary") or d
        bad = (s.get("uid_instability") or 0) + (s.get("removed_unexplained") or 0) \
            + (s.get("unknown_reason") or 0)
        return "FAIL" if bad else "PASS"
    if name == "readiness":
        # RC-17 · bản trước KHÔNG có nhánh này, nên verdict luôn `null` và
        # `_exit_code` không có gì để chặn. RC-20 vẫn exit 0 kể cả khi readiness
        # FAIL hoặc vắng mặt. Một cổng không đọc được kết luận của input bắt
        # buộc thì không phải cổng.
        v = d.get("verdict") or (d.get("summary") or {}).get("verdict")
        return str(v).upper() if v is not None else None
    if name == "replay":
        s = d.get("summary") or d
        if s.get("failed") or s.get("errors") or s.get("skipped"):
            return "FAIL"
        return "PASS"
    return None


def _build_id_of(d):
    for k in ("build_id", "buildId"):
        if isinstance(d, dict) and d.get(k):
            return d[k]
    for k in ("summary", "meta"):
        v = d.get(k) if isinstance(d, dict) else None
        if isinstance(v, dict) and v.get("build_id"):
            return v["build_id"]
    return None


REQUIRED_INPUTS = ("rebuild_check", "no_loss", "differential", "replay",
                   "unresolved", "readiness")


def _collect_inputs(a, build_id):
    names = {"rebuild_check": a.rebuild_check, "no_loss": a.no_loss,
             "differential": a.differential, "readiness": a.readiness,
             "unresolved": a.unresolved, "replay": a.replay,
             "quality": a.quality}
    reports, mism, failing = {}, [], []
    for n, path in names.items():
        info = _load(path)
        if info["status"] == "OK":
            d = info.pop("data")
            info["build_id"] = _build_id_of(d)
            info["verdict"] = _verdict_of(n, d)
            if build_id and info["build_id"] and info["build_id"] != build_id:
                mism.append(f"{n}: {info['build_id']} != {build_id}")
            if info["verdict"] == "FAIL":
                failing.append(f"{n}")
        reports[n] = info
    missing_required = [n for n in REQUIRED_INPUTS
                        if reports[n]["status"] != "OK"]
    return {"reports": reports, "build_id_mismatches": mism,
            "failing_reports": failing, "missing_required": missing_required,
            "required_inputs": list(REQUIRED_INPUTS)}


# RC2-046 · Ba metric C0 trong `gates.py` được khai BLOCKED kèm lý do nêu đích
# danh artifact còn thiếu:
#
#   uid_stability_two_clean_rebuilds  "cần hai lần clean rebuild cùng input"
#   output_checksum_determinism       "cần hai lần build để so"
#   unexplained_count_delta           "cần differential audit (B5)"
#
# Ba artifact đó nay ĐÃ CÓ và được truyền vào `--rebuild-check`/`--differential`,
# nhưng `evaluate_gates()` không nhận chúng — nên C0 vĩnh viễn BLOCKED, và vì C0
# không nằm trong `ALLOWED_BLOCKED`, RC-20 **không bao giờ** exit 0 được, kể cả
# khi mọi cổng khác xanh.
#
# Ở đây giải BLOCKED bằng đúng bằng chứng mà chính lý do BLOCKED nêu tên. KHÔNG
# nới lỏng: chỉ lật khi report tồn tại, verdict PASS, và build_id khớp. Thiếu
# một điều kiện thì metric giữ nguyên BLOCKED và ghi rõ vì sao.
_C0_METRIC_EVIDENCE = {
    "uid_stability_two_clean_rebuilds": "rebuild_check",
    "output_checksum_determinism": "rebuild_check",
    "unexplained_count_delta": "differential",
}


def _resolve_c0(rep: dict, a) -> dict:
    reports = rep.get("inputs", {}).get("reports", {})
    bid = rep.get("build_id")
    ket = {}
    for g in rep.get("gates", []):
        if g.get("gate") != "C0":
            continue
        for m in g.get("metrics", []):
            nguon = _C0_METRIC_EVIDENCE.get(m.get("name"))
            if not nguon or m.get("status") != "BLOCKED":
                continue
            info = reports.get(nguon) or {}
            if info.get("status") != "OK":
                ket[m["name"]] = f"{nguon}: KHÔNG ĐỌC ĐƯỢC ({info.get('status')})"
                continue
            if info.get("verdict") != "PASS":
                ket[m["name"]] = f"{nguon}: verdict={info.get('verdict')}"
                continue
            if bid and info.get("build_id") and info["build_id"] != bid:
                ket[m["name"]] = (f"{nguon}: build_id {info['build_id']} != {bid}")
                continue
            if bid and not info.get("build_id"):
                ket[m["name"]] = f"{nguon}: report KHÔNG mang build_id — không xác thực được"
                continue
            m["status"] = "PASS"
            m["blocking_reason"] = None
            m["resolved_by"] = f"{nguon} ({info.get('path')})"
            ket[m["name"]] = f"PASS ← {nguon}"
        g["status"] = ("FAIL" if any(x["status"] == "FAIL" for x in g["metrics"])
                       else "BLOCKED" if any(x["status"] == "BLOCKED" for x in g["metrics"])
                       else "PASS")
    return ket


def _resync_summary(rep: dict) -> None:
    """`summary` và `gates[]` phải nói CÙNG một điều.

    `evaluate_gates()` dựng `summary` khi C0 còn BLOCKED; `_resolve_c0()` sau
    đó nâng `gates[C0]` lên PASS nhưng không đụng tới `summary`. Kết quả trên
    build `7aa8b4c22984bf5f`: cùng một tệp báo cáo ghi `summary.C0 = BLOCKED`
    và `gates[C0].status = PASS`, còn `_exit_code()` chỉ đọc `gates[]` nên vẫn
    trả 0. Kiểm toán độc lập bắt đúng chỗ này (Doc 56 P0-02).

    Hai nguồn sự thật trong một tệp là lỗi nặng hơn cả hai nguồn sai, vì người
    đọc không có cách nào biết nên tin cái nào.
    """
    st = {g["gate"]: g["status"] for g in rep.get("gates", [])}
    rep["summary"] = {k: st.get(k, rep.get("summary", {}).get(k))
                      for k in (list(rep.get("summary") or {}) or list(st))}
    for k, v in st.items():
        rep["summary"][k] = v
    blocked = [g for g, v in st.items() if v == "BLOCKED"]
    failed = [g for g, v in st.items() if v == "FAIL"]
    # Dùng ĐÚNG vốn từ vựng của `evaluate_gates()`. Đặt tên khác ở đây là tạo
    # nhãn thứ hai cho cùng một trạng thái, đúng lỗi mà bước này đang đi sửa.
    rep["release_label"] = (
        "blocked" if failed or any(g not in ALLOWED_BLOCKED for g in blocked)
        else "silver-v1.0.0-rc2" if blocked else "silver-v1.0.0-production")
    rep["summary_resynced_after_c0_resolution"] = True


def _exit_code(rep, require_all) -> int:
    """0 = cho phat hanh · 2 = thieu/khong khop input · 3 = co cong FAIL."""
    ii = rep["inputs"]
    hard_fail = [g for g in rep["gates"] if g["status"] == "FAIL"]
    if hard_fail or ii["failing_reports"]:
        return 3
    if ii["build_id_mismatches"]:
        return 2
    if require_all and ii["missing_required"]:
        return 2
    blocked = [g["gate"] for g in rep["gates"] if g["status"] == "BLOCKED"]
    if any(g not in ALLOWED_BLOCKED for g in blocked):
        return 3
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("-o", "--out", default="reports")
    ap.add_argument("--quality", help="quality_report.json nếu có")
    ap.add_argument("--replay", help="replay_report.json nếu có")
    # B0-02 · RC-20 phai la CONG PHAT HANH, nen no phai DOC duoc moi report
    # dau vao, doi chieu chung build_id, va CHAN bang exit code.
    ap.add_argument("--rebuild-check", help="rebuild_check.json (C0)")
    ap.add_argument("--no-loss", help="no_loss_check report (C1)")
    ap.add_argument("--differential", help="differential_audit report (RC-16)")
    ap.add_argument("--readiness", help="readiness reconciliation (RC-17)")
    ap.add_argument("--unresolved", help="unresolved_registry report (RC-18)")
    ap.add_argument("--require-all", action="store_true",
                    help="thieu bat ky report bat buoc nao -> exit 2")
    a = ap.parse_args()

    con = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
    q = json.loads(Path(a.quality).read_text()) if a.quality else None
    r = json.loads(Path(a.replay).read_text()) if a.replay else None
    rep = evaluate_gates(con, q, r)
    rep["inputs"] = _collect_inputs(a, rep.get("build_id"))
    rep["c0_resolution"] = _resolve_c0(rep, a)
    _resync_summary(rep)
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    f = out / "gate_report.json"
    f.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"╔═══ CỔNG PHÁT HÀNH · build {rep['build_id']} ═══╗")
    for g in rep["gates"]:
        mark = {"PASS": "✓", "FAIL": "✗", "BLOCKED": "▪"}[g["status"]]
        print(f"  {mark} {g['gate']:<3} {g['status']:<8} {g['title']}")
        for m in g["metrics"]:
            if m["status"] == "PASS":
                continue
            num = "" if m["numerator"] is None else f"{m['numerator']:,}"
            den = "" if m["denominator"] is None else f"/{m['denominator']:,}"
            why = f"   ← {m['blocking_reason']}" if m["blocking_reason"] else ""
            print(f"      {m['status']:<8}{m['name']:<38}{num}{den:<14}"
                  f"{m['threshold']}{why}")
    print(f"\n  NHÃN PHÁT HÀNH SUY RA TỪ CỔNG: {rep['release_label']}")
    print(f"  -> {f}")
    ii = rep["inputs"]
    for k, v in sorted(ii["reports"].items()):
        print(f"  input {k:<14} {v['status']:<8} {v.get('path') or '—'}")
    if ii["build_id_mismatches"]:
        for m in ii["build_id_mismatches"]:
            print(f"  ✗ build_id lệch: {m}")
    if ii["failing_reports"]:
        for m in ii["failing_reports"]:
            print(f"  ✗ report FAIL: {m}")

    code = _exit_code(rep, a.require_all)
    print(f"\n  RC-20 EXIT = {code}  "
          f"({ {0:'cho phep phat hanh',2:'thieu/khong khop input',3:'co cong FAIL'}[code] })")
    con.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
