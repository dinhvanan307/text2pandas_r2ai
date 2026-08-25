#!/usr/bin/env python3
"""RC-14 · so hai clean rebuild — cổng C0.

KHÔNG ép SQLite giống nhau từng byte. SQLite chèn page layout và freelist theo
thứ tự ghi, nên hash tệp khác nhau là bình thường và không nói lên gì. Thứ
phải giống là NỘI DUNG CHUẨN HOÁ: mọi UID, mọi locator, mọi giá trị.

Nhưng cũng KHÔNG được bỏ so nội dung chỉ vì hash tệp khác — đó là cách một
build nondeterministic đi lọt.
"""
from __future__ import annotations

import argparse, hashlib, json, sqlite3, sys
from pathlib import Path

# Trường nondeterministic — khai HẸP và khai RÕ (review 28 §RC-14).
NONDETERMINISTIC = {"created_at", "checksum_seconds", "seconds", "build_time"}

# Bảng và khoá vật lý dùng để băm nội dung chuẩn hoá.
# B0-06 · C0-CORE chi chung minh core transform giong nhau. No KHONG chung minh
# final candidate giong nhau, vi `quality` co DELETE/INSERT vao `quality_issues`
# va readiness/collision duoc dung o giai doan finalize.
CANONICAL_CORE = {
    "table_features": "table_uid",
    "rows":           "row_uid",
    "columns":        "column_uid",
    "observations":   "observation_uid",
    "dropped_cells":  "source_cell_uid",
}
# C0-FINAL: moi bang thuoc hop dong ban dung cuoi. Bang nao khong ton tai o ca
# HAI ban thi bao SKIPPED — khong im lang bo qua.
CANONICAL_FINAL = {
    **CANONICAL_CORE,
    "source_cells":           "source_cell_uid",
    "grid_cells":             "source_cell_uid",
    "quality_issues":         "issue_uid",
    "observation_readiness":  "observation_uid",
    "collision_groups":       "rowid",
    "collision_obs":          "rowid",
}

# RC2-030 · Bon bang nay KHONG BAO GIO co trong DB ban dung — do trực tiếp tren
# ca RC1 (b927c3e8f90aed74) lan RC2 (5ffc07216708d9fd): vang o ca hai. Chung do
# `src/data_pipeline/release.py` sinh ra o buoc release.
#
# De chung trong CANONICAL_FINAL khien C0-final TUYEN BO 15 bang ma chi DO duoc
# 11. Cong cu van bao "bo qua" chu khong im lang, nen no khong noi doi — nhung
# con so 15 la quang cao qua, va mot hop dong quang cao qua thi lan sau khong ai
# tin phan con lai.
#
# Chung thuoc pham vi RC-24 (`verify_package`) tren goi phat hanh, khong thuoc
# pham vi C0 tren ban dung.
RELEASE_ONLY = {
    "documents":   "document_uid",
    "pages":       "rowid",
    "tables":      "table_uid",
    "table_cards": "table_uid",
}
CANONICAL = CANONICAL_CORE


def _canonical_hash(db: Path, table: str, key: str) -> tuple[str, int]:
    """Băm nội dung theo thứ tự khoá vật lý, bỏ cột nondeterministic."""
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    cols = [r[1] for r in c.execute(f"PRAGMA table_info({table})")]
    if not cols:
        return "MISSING", 0
    use = [x for x in cols if x not in NONDETERMINISTIC]
    h = hashlib.sha256()
    n = 0
    sel = ",".join(f'"{x}"' for x in use)
    for row in c.execute(f'SELECT {sel} FROM "{table}" ORDER BY "{key}"'):
        h.update(repr(row).encode()); n += 1
    c.close()
    return h.hexdigest()[:32], n


def _resolve_db(build_dir: Path) -> Path:
    """Tìm silver.sqlite của một bản dựng: bản LÀM VIỆC trước, rồi bản ĐÃ PUBLISH.

    `publish` copy bản làm việc sang `<build>/silver/<build_id>/silver.sqlite`
    bằng `shutil.copy2`, và trên bản dựng `7aa8b4c22984bf5f` hai tệp đã được đo
    là ĐỒNG NHẤT TỪNG BYTE (`95b0245818adc156…`). Nên khi bản làm việc đã bị dọn
    để lấy đĩa, so trên bản đã publish là so ĐÚNG những byte đó.

    Đây không phải đường vòng: report ghi rõ đường dẫn thật đã dùng, nên người
    review thấy được cái gì được so — chứ không phải đoán. Doc 52 §8 Bước 1 đòi
    đúng điều đó.

    Ưu tiên bản làm việc vì nó là bản gốc; chỉ rơi xuống bản publish khi bản gốc
    không còn.
    """
    tho = build_dir / "silver.sqlite"
    if tho.is_file():
        return tho
    ung = sorted(build_dir.glob("silver/*/silver.sqlite"))
    if len(ung) == 1:
        return ung[0]
    # Nhiều hơn một bản publish trong cùng thư mục là trạng thái không xác định
    # — KHÔNG tự chọn. Trả về đường dẫn thô để thông điệp lỗi cũ vẫn hiện.
    return tho


def _sha256(p: Path) -> str | None:
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--build-a", required=True)
    ap.add_argument("--build-b", required=True)
    ap.add_argument("--report", default=None)
    ap.add_argument("--db-sha256", action="store_true",
                    help="băm cả hai DB và ghi báo cáo byte-identity (Doc 52 §6.2)")
    ap.add_argument("--mode", choices=("core", "final"), default="core",
                    help="core = truoc quality (phat hien som). "
                         "final = moi bang cua hop dong ban dung cuoi — "
                         "ACCEPTANCE phai dung final.")
    a = ap.parse_args()
    A, B = Path(a.build_a), Path(a.build_b)
    dbA, dbB = _resolve_db(A), _resolve_db(B)
    # SAFETY · RC2-012. Thiếu `silver.sqlite` gần như luôn là do dọn dẹp SAI
    # THỨ TỰ: bản runbook đầu bảo xoá scratch của A ngay sau `publish`, tức là
    # TRƯỚC khi C0 chạy. Cổng tất định khi đó không so được gì, và người vận
    # hành chỉ thấy "không thấy tệp" mà không biết mình vừa phá cổng nào.
    for d in (dbA, dbB):
        if not d.is_file():
            print(f"✗ không thấy {d}", file=sys.stderr)
            print("  C0 so hai bản dựng THÔ. Nếu bạn vừa xoá `silver.sqlite`"
                  " trong thư mục build để lấy đĩa: đó là thao tác PHẢI làm"
                  " SAU khi `dp-rebuild-check` chạy xong, không phải trước.",
                  file=sys.stderr)
            print("  Thứ tự đúng: build A → build B → rebuild-check →"
                  " quality/publish → dọn dẹp.", file=sys.stderr)
            return 2

    if a.mode == "final":
        # B0-06 · C0-final chi co nghia khi CA HAI ban da chay cung chuoi stage.
        marks = {}
        for lbl, d in (("A", A), ("B", B)):
            mp = d / "completion_marker.json"
            if not mp.is_file():
                print(f"LOI: {lbl} thieu completion_marker.json — ban dung nay chua "
                      f"chay `--finalize`. C0-final khong the ket luan.", file=sys.stderr)
                return 2
            try:
                marks[lbl] = json.loads(mp.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                print(f"LOI: khong doc duoc marker cua {lbl}: {e}", file=sys.stderr)
                return 2
        for lbl, m in marks.items():
            if not m.get("finalized"):
                print(f"LOI: {lbl} co marker nhung finalized=false — chua qua `quality`.",
                      file=sys.stderr)
                return 2
        if marks["A"].get("stages_completed") != marks["B"].get("stages_completed"):
            print(f"LOI: A va B chay KHAC chuoi stage: "
                  f"{marks['A'].get('stages_completed')} vs "
                  f"{marks['B'].get('stages_completed')} — so hai ban khac pha.",
                  file=sys.stderr)
            return 2
    tabset = CANONICAL_FINAL if a.mode == "final" else CANONICAL_CORE
    rep = {"build_id": None,          # điền sau khi đọc build_meta
           "build_a": str(dbA), "build_b": str(dbB), "mode": a.mode,
           "gate_name": "C0-final" if a.mode == "final" else "C0-core",
           "tables_in_scope": sorted(tabset),
           "nondeterministic_fields_excluded": sorted(NONDETERMINISTIC),
           "tables": {}, "skipped_tables": [], "build_meta": {},
           # Doc 52 §8 Buoc 1 · report phai ghi RO input identity, khong de
           # nguoi review phai doan da so tren tep nao.
           "input_identity": {
               "db_a_path": str(dbA), "db_a_bytes": dbA.stat().st_size if dbA.is_file() else None,
               "db_b_path": str(dbB), "db_b_bytes": dbB.stat().st_size if dbB.is_file() else None,
               "db_a_is_published_copy": dbA.parent != A,
               "db_b_is_published_copy": dbB.parent != B,
               "note": ("`publish` copy ban lam viec sang <build>/silver/<build_id>/ "
                        "bang shutil.copy2. Khi ban lam viec da bi don de lay dia, "
                        "cong cu so tren ban da publish va ghi ro dieu do o day."),
           }}
    if a.db_sha256:
        # Doc 52 §6.2 · bao cao byte-identity phai do bang MAY, khong chep tay.
        ha, hb = _sha256(dbA), _sha256(dbB)
        rep["byte_identity"] = {
            "path_A3": str(dbA), "bytes_A3": rep["input_identity"]["db_a_bytes"],
            "sha256_A3": ha,
            "path_B3": str(dbB), "bytes_B3": rep["input_identity"]["db_b_bytes"],
            "sha256_B3": hb,
            "identical": bool(ha and hb and ha == hb),
        }
    if a.mode == "core":
        rep["scope_warning"] = (
            "C0-core so BANG LOI TRUOC `quality`. `quality` co DELETE/INSERT vao "
            "quality_issues va chi chay tren A, nen C0-core KHONG chung minh final "
            "candidate A/B tat dinh. ACCEPTANCE phai dung --mode final.")
    ok = True
    def _has(db, t):
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            return c.execute("SELECT name FROM sqlite_master WHERE type='table'"
                             " AND name=?", (t,)).fetchone() is not None
        finally:
            c.close()
    for t, k in tabset.items():
        pa, pb = _has(dbA, t), _has(dbB, t)
        if not pa and not pb:
            rep["skipped_tables"].append({"table": t, "reason": "khong co o CA HAI ban"})
            print(f"  {t:<24} — bo qua (khong co o ca hai ban)")
            continue
        if pa != pb:
            ok = False
            rep["tables"][t] = {"identical": False,
                                "reason": f"chi co o {'A' if pa else 'B'}"}
            print(f"  {t:<24} ✗ KHÁC — chi co o {'A' if pa else 'B'}")
            continue
        ha, na = _canonical_hash(dbA, t, k)
        hb, nb = _canonical_hash(dbB, t, k)
        same = (ha == hb and na == nb)
        ok &= same
        rep["tables"][t] = {"rows_a": na, "rows_b": nb,
                            "canonical_hash_a": ha, "canonical_hash_b": hb,
                            "identical": same}
        print(f"  {t:<24} {na:>10,} vs {nb:>10,}  {'✓' if same else '✗ KHÁC'}")

    for label, db in (("a", dbA), ("b", dbB)):
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        try:
            rep["build_meta"][label] = dict(c.execute("SELECT key,value FROM build_meta"))
        except sqlite3.Error:
            rep["build_meta"][label] = {}
        c.close()
    bid_a = rep["build_meta"].get("a", {}).get("build_id")
    bid_b = rep["build_meta"].get("b", {}).get("build_id")
    # RC2-047 · Doc 52 §7: MOI report phai mang build ID o cap cao nhat, de
    # RC-20 doi chieu duoc. Thieu no, phep kiem "input build/hash mismatch = 0"
    # cua RC-20 khong bao gio noi duoc — no chi so khi ca hai ben cung co gia
    # tri, va `None` lam no im lang bo qua.
    rep["build_id"] = bid_a if bid_a and bid_a == bid_b else (bid_a or bid_b)
    rep["build_id_a"], rep["build_id_b"] = bid_a, bid_b
    rep["build_id_identical"] = bid_a == bid_b and bid_a is not None
    ok &= rep["build_id_identical"]
    print(f"  build_id         {bid_a} vs {bid_b}  {'✓' if rep['build_id_identical'] else '✗'}")

    rep["file_sha256_a"] = hashlib.sha256(dbA.read_bytes()).hexdigest()[:32] if dbA.stat().st_size < 2e9 else "SKIPPED_TOO_LARGE"
    rep["file_sha256_b"] = hashlib.sha256(dbB.read_bytes()).hexdigest()[:32] if dbB.stat().st_size < 2e9 else "SKIPPED_TOO_LARGE"
    rep["note_file_hash"] = ("Hash TỆP có thể khác do page layout của SQLite. "
                             "Cổng C0 dựa trên canonical content hash, không dựa vào nó.")
    rep["C0"] = "PASS" if ok else "FAIL"
    # `verdict` la ten chung ma RC-20 doc; giu ca "C0" cho tuong thich nguoc.
    rep["verdict"] = rep["C0"]

    if a.report:
        p = Path(a.report); p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"  → {p}")
    print(f"  C0 = {rep['C0']}")
    return 0 if ok else 3


if __name__ == "__main__":
    sys.exit(main())
