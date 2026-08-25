#!/usr/bin/env python3
"""RC-17 · Đối chiếu readiness — Doc 52 §8 Bước 4 và §7 `readiness/`.

Vì sao tệp này ra đời: `gate_report.py` nhận `--readiness` từ lâu, nhưng **không
công cụ nào trong repo sinh ra artifact cho nó** (RC2-033). Một tham số không ai
bật được thì phép kiểm sau nó là phép kiểm rỗng.

Công cụ CHỈ ĐỌC. Nó không sửa DB, không sinh dữ liệu mới — chỉ đo bốn thứ mà
Doc 52 §8 Bước 4 đòi:

    observations = observation_readiness   1:1
    ready/candidate/not-ready theo TỪNG lý do
    lý do chặn map được vào taxonomy
    Table Card ready count đối chiếu với readiness

Và một bất biến an toàn: **không ca `unresolved` nào được nằm trong
`execution_ready`** (§6.5). Vi phạm là C4 FAIL, không phải cảnh báo.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path


def _sha(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _meta(con) -> dict:
    try:
        return dict(con.execute("SELECT key, value FROM build_meta"))
    except sqlite3.Error:
        return {}


def _reasons(con, col: str) -> Counter:
    """Đếm theo TỪNG lý do, không cộng dồn nhiều lý do thành một con số.

    Doc 52 §8 Bước 4: "Không được cộng trùng nhiều rule rồi gọi tổng đó là số
    entity unresolved." Một observation mang ba lý do sẽ được đếm ở cả ba, và
    tổng các lý do KHÁC tổng observation — nên hai con số được ghi riêng.
    """
    c: Counter = Counter()
    for (raw,) in con.execute(f"SELECT COALESCE({col},'[]') FROM observation_readiness"):
        try:
            for r in json.loads(raw) or []:
                c[str(r)] += 1
        except (TypeError, ValueError):
            c["__KHONG_DOC_DUOC__"] += 1
    return c


def _taxonomy(path: Path) -> tuple[set[str], str | None]:
    """Đọc tập mã lý do của READINESS từ taxonomy.

    RC2-053 · bản trước quét đệ quy tìm GIÁ TRỊ chuỗi ở các khoá
    `id|code|reason|rule_id`. Taxonomy lại để `D-xx` làm KHOÁ dict và không hề
    chứa namespace reason của readiness, nên tập luôn RỖNG — và chỗ dùng có
    `if tax` biến rỗng thành "không có lý do nào ngoài taxonomy". Fail-open
    hoàn hảo: `taxonomy_n_codes = 0` mà `verdict = PASS`.

    Bản này đọc đúng bảng nối `readiness_reasons` và trả kèm lý do lỗi để chỗ
    gọi FAIL thay vì đoán.
    """
    try:
        import yaml
    except Exception as exc:                                # pragma: no cover
        return set(), f"khong import duoc yaml: {exc!r}"
    try:
        d = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        return set(), f"khong doc duoc {path}: {exc!r}"
    rr = d.get("readiness_reasons")
    if not isinstance(rr, dict) or not rr:
        return set(), (f"{path} thieu bang noi `readiness_reasons` — khong co "
                       f"gi de doi chieu voi blocking_reasons cua readiness")
    codes = set(d.get("defects") or {})
    la = [r for r, c in rr.items() if c not in codes]
    if la:
        # In cả CẶP reason→mã. Chỉ in tên reason thì người sửa biết chỗ hỏng
        # mà không biết nó trỏ đi đâu, và phải mở file ra dò tay.
        cap = ", ".join(f"{r}->{rr[r]}" for r in sorted(la)[:5])
        return set(rr), f"reason tro toi defect ID khong ton tai: {cap}"
    return set(rr), None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True, help="silver.sqlite BẢN DỰNG (không phải release slim)")
    ap.add_argument("--taxonomy", default="configs/defect_taxonomy_v1.yaml")
    ap.add_argument("--report", default=None)
    ap.add_argument("--by-reason-csv", default=None)
    ap.add_argument("--label", default=None)
    a = ap.parse_args(argv)

    db = Path(a.db)
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    meta = _meta(con)
    n_obs = con.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
    n_rdy = con.execute("SELECT COUNT(*) FROM observation_readiness").fetchone()[0]
    n_join = con.execute(
        "SELECT COUNT(*) FROM observations o"
        " JOIN observation_readiness r USING(observation_uid)").fetchone()[0]
    n_obs_khong_rdy = con.execute(
        "SELECT COUNT(*) FROM observations o LEFT JOIN observation_readiness r"
        " USING(observation_uid) WHERE r.observation_uid IS NULL").fetchone()[0]
    n_rdy_mo_coi = con.execute(
        "SELECT COUNT(*) FROM observation_readiness r LEFT JOIN observations o"
        " USING(observation_uid) WHERE o.observation_uid IS NULL").fetchone()[0]

    buckets = {f"candidate={c}|ready={r}": n for c, r, n in con.execute(
        "SELECT execution_candidate, execution_ready, COUNT(*)"
        " FROM observation_readiness GROUP BY 1,2")}
    n_ready = con.execute(
        "SELECT COUNT(*) FROM observation_readiness WHERE execution_ready=1").fetchone()[0]
    n_cand = con.execute(
        "SELECT COUNT(*) FROM observation_readiness WHERE execution_candidate=1").fetchone()[0]

    blocking = _reasons(con, "blocking_reasons_json")
    warning = _reasons(con, "warning_reasons_json")
    non_cand = _reasons(con, "non_candidate_reasons_json")

    # §8 Bước 4 · bất biến an toàn: ready mà vẫn còn lý do chặn là mâu thuẫn.
    n_ready_co_blocking = con.execute(
        "SELECT COUNT(*) FROM observation_readiness WHERE execution_ready=1"
        " AND COALESCE(blocking_reasons_json,'[]') <> '[]'").fetchone()[0]
    n_ready_khong_candidate = con.execute(
        "SELECT COUNT(*) FROM observation_readiness"
        " WHERE execution_ready=1 AND execution_candidate=0").fetchone()[0]
    n_not_ready_khong_ly_do = con.execute(
        "SELECT COUNT(*) FROM observation_readiness WHERE execution_ready=0"
        " AND execution_candidate=1 AND COALESCE(blocking_reasons_json,'[]')='[]'"
    ).fetchone()[0]

    tax, tax_err = _taxonomy(Path(a.taxonomy))
    # FAIL-CLOSED. Taxonomy rỗng hoặc hỏng nghĩa là phép kiểm này KHÔNG chạy
    # được — đó là lý do để FAIL, không phải để bỏ qua.
    khong_map = sorted(r for r in blocking if r not in tax)

    # Table Card ↔ readiness: đối chiếu ở mức BẢNG, không phải mức ô.
    try:
        n_tab_co_ready = con.execute(
            "SELECT COUNT(DISTINCT o.table_uid) FROM observations o"
            " JOIN observation_readiness r USING(observation_uid)"
            " WHERE r.execution_ready=1").fetchone()[0]
        n_tab_tong = con.execute("SELECT COUNT(*) FROM table_features").fetchone()[0]
    except sqlite3.Error:
        n_tab_co_ready = n_tab_tong = None

    phat_hien = []
    if n_obs != n_rdy or n_join != n_obs:
        phat_hien.append(f"KHÔNG 1:1 — observations={n_obs} readiness={n_rdy} join={n_join}")
    if n_obs_khong_rdy or n_rdy_mo_coi:
        phat_hien.append(f"mồ côi — obs thiếu readiness={n_obs_khong_rdy}, "
                         f"readiness thừa={n_rdy_mo_coi}")
    if n_ready_co_blocking:
        phat_hien.append(f"execution_ready còn lý do chặn: {n_ready_co_blocking}")
    if n_ready_khong_candidate:
        phat_hien.append(f"execution_ready mà không phải candidate: {n_ready_khong_candidate}")
    if n_not_ready_khong_ly_do:
        phat_hien.append(f"candidate không ready mà KHÔNG có lý do: {n_not_ready_khong_ly_do}")
    if tax_err:
        phat_hien.append(f"taxonomy không dùng được: {tax_err}")
    if khong_map:
        phat_hien.append(f"lý do chặn không map được vào taxonomy: {khong_map[:5]}")

    rep = {
        "gate": "RC-17 · readiness reconciliation",
        "build_id": meta.get("build_id") or a.label,
        "db_path": str(db), "db_sha256": None,
        "corpus_id": meta.get("corpus_id"),
        "counts": {
            "observations": n_obs, "observation_readiness": n_rdy,
            "joined": n_join,
            "observations_without_readiness": n_obs_khong_rdy,
            "readiness_orphan": n_rdy_mo_coi,
            "execution_candidate": n_cand, "execution_ready": n_ready,
            "not_ready": n_cand - n_ready,
            "buckets": buckets,
        },
        "one_to_one": n_obs == n_rdy == n_join and not n_obs_khong_rdy and not n_rdy_mo_coi,
        "safety": {
            "ready_with_blocking_reason": n_ready_co_blocking,
            "ready_not_candidate": n_ready_khong_candidate,
            "not_ready_without_reason": n_not_ready_khong_ly_do,
            "blocking_reasons_unmapped": khong_map,
        },
        "reason_counts": {
            "_note": ("Đếm theo TỪNG lý do. Một observation mang ba lý do được "
                      "đếm ở cả ba, nên tổng các lý do KHÁC tổng observation — "
                      "hai con số trả lời hai câu hỏi khác nhau."),
            "blocking": dict(blocking.most_common()),
            "warning": dict(warning.most_common()),
            "non_candidate": dict(non_cand.most_common()),
        },
        "table_cards": {"tables_total": n_tab_tong,
                        "tables_with_ready_observation": n_tab_co_ready},
        "taxonomy_path": str(a.taxonomy), "taxonomy_n_codes": len(tax),
        "taxonomy_error": tax_err,
        "findings": phat_hien,
        "verdict": "PASS" if not phat_hien else "FAIL",
    }
    con.close()

    if a.by_reason_csv:
        p = Path(a.by_reason_csv); p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["reason_kind", "reason", "n_observations", "in_taxonomy"])
            for kind, c in (("blocking", blocking), ("warning", warning),
                            ("non_candidate", non_cand)):
                for r, n in c.most_common():
                    w.writerow([kind, r, n, "" if not tax else str(r in tax)])
        rep["by_reason_csv"] = str(p)
        rep["by_reason_csv_sha256"] = _sha(p)

    if a.report:
        p = Path(a.report); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print("╔═══ RC-17 · readiness reconciliation ═══╗")
    print(f"  build_id            {rep['build_id']}")
    print(f"  observations        {n_obs:,}")
    print(f"  observation_readiness {n_rdy:,}   join {n_join:,}   1:1 = {rep['one_to_one']}")
    print(f"  execution_candidate {n_cand:,}")
    print(f"  execution_ready     {n_ready:,}   not-ready {n_cand-n_ready:,}")
    print(f"  ready còn lý do chặn        {n_ready_co_blocking}   (ngưỡng 0)")
    print(f"  ready mà không candidate    {n_ready_khong_candidate}   (ngưỡng 0)")
    print(f"  not-ready không có lý do    {n_not_ready_khong_ly_do}   (ngưỡng 0)")
    print(f"  lý do chặn ngoài taxonomy   {len(khong_map)}   (ngưỡng 0)")
    print(f"  bảng có ≥1 observation ready {n_tab_co_ready:,} / {n_tab_tong:,}"
          if n_tab_tong else "")
    print(f"  RC-17 = {rep['verdict']}")
    for f in phat_hien:
        print(f"    ✗ {f}", file=sys.stderr)
    if a.report:
        print(f"  → {a.report}")
    return 0 if rep["verdict"] == "PASS" else 3


if __name__ == "__main__":
    sys.exit(main())
