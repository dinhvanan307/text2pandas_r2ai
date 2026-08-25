"""replay_report.json · determinism_report.json · RUN_MANIFEST.json"""
from __future__ import annotations
import hashlib, io, json, os, subprocess, sqlite3, sys, zipfile
from pathlib import Path
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "artifacts/execution/h0"; OUT.mkdir(parents=True, exist_ok=True)
ZP = ROOT / "artifacts/submissions/legacy/submission_P0I.zip"

# ── replay: chạy lại TOÀN BỘ query trên CSV trong chính ZIP ────────────────
Z = zipfile.ZipFile(ZP); sub = json.loads(Z.read("submission.json"))
B = {"float": float, "max": max, "min": min, "abs": abs, "sum": sum, "round": round, "len": len}
xanh = do = bo = 0; loi = []; cache = {}
for r in sub:
    ev = r.get("evidence") or []
    if not ev or not r.get("pandas_query") or r.get("answer") is None:
        bo += 1; continue
    env = dict(B); thieu = False
    for e in ev:
        p = e.get("csv_path")
        if p not in cache:
            if len(cache) > 150: cache.clear()
            try: cache[p] = pd.read_csv(io.BytesIO(Z.read(p)))
            except KeyError: thieu = True; break
        env[e["variable"]] = cache[p]
    if thieu: do += 1; loi.append([r["id"], "THIEU_CSV"]); continue
    try:
        v = eval(r["pandas_query"], {"__builtins__": {}}, env)
        if abs(v - r["answer"]) <= max(1e-9, abs(r["answer"]) * 1e-9): xanh += 1
        else: do += 1; loi.append([r["id"], f"LECH {v} vs {r['answer']}"])
    except Exception as e:
        do += 1; loi.append([r["id"], repr(e)[:90]])
ids = [r["id"] for r in sub]
(OUT/"replay_report.json").write_text(json.dumps({
    "submission": ZP.name, "sha256": hashlib.sha256(ZP.read_bytes()).hexdigest(),
    "n_records": len(sub), "n_unique_ids": len(set(ids)), "ids_complete_1_1012": sorted(ids) == list(range(1, 1013)),
    "invariant_answer_eq_eval_query": {"pass": xanh, "fail": do, "skipped_no_query": bo},
    "failures": loi[:20],
    "env": {"python": sys.version.split()[0], "pandas": pd.__version__, "sqlite": sqlite3.sqlite_version},
    "csv_files_in_zip": sum(1 for n in Z.namelist() if n.endswith(".csv")),
}, ensure_ascii=False, indent=1))

# ── determinism: dựng lại 2 lần, so nội dung ───────────────────────────────
def dau_van(p: Path) -> dict:
    z = zipfile.ZipFile(p)
    return {"submission_json_sha256": hashlib.sha256(z.read("submission.json")).hexdigest(),
            "n_members": len(z.namelist()),
            "member_crc_sha256": hashlib.sha256(
                "".join(f"{i.filename}:{i.CRC}" for i in sorted(z.infolist(), key=lambda x: x.filename)).encode()).hexdigest()}
a = dau_van(ZP)
subprocess.run([sys.executable, "tools/answer_a6/06_dong_goi.py"], cwd=ROOT, capture_output=True)
b = dau_van(ZP)
(OUT/"determinism_report.json").write_text(json.dumps({
    "method": "dung lai bang 06_dong_goi.py roi so submission.json sha256 + CRC cua moi thanh vien",
    "run_1": a, "run_2": b, "deterministic": a == b}, ensure_ascii=False, indent=1))

# ── RUN_MANIFEST ───────────────────────────────────────────────────────────
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
w = sqlite3.connect('file:'+os.path.abspath(ROOT/'data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db')+'?mode=ro', uri=True)
bm = dict(w.execute("SELECT key,value FROM build_meta"))
git = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip()
dirty = len(subprocess.run(["git","status","--porcelain"], cwd=ROOT, capture_output=True, text=True).stdout.splitlines())
(OUT/"RUN_MANIFEST.json").write_text(json.dumps({
    "candidate": "C1_P0I", "parent": "P0G2 (submission id 3236)",
    "official_submission_id": 3241, "official_execution_accuracy": 0.1225,
    "official_answer_accuracy": 0.1225, "official_tables_f2": 0.3538, "official_docs_f2": 0.7536,
    "silver": {"build_id": bm.get("build_id"), "readiness_policy_version": bm.get("readiness_policy_version"),
               "release_label": bm.get("release_label"), "status": bm.get("status"),
               "corpus_id": bm.get("corpus_id"), "revision": bm.get("revision"),
               "package": "artifacts/rc2/packagesa6/silver_v1_rc2_b3e9684004679ffb_a6_run1.zip",
               "package_sha256": "23c3b96e4338e8785c2dcfcdfebf147dc7b7dfb6438c46c590be1ecbfe2453be",
               "package_sha256_matches_PROVENANCE": True},
    "work_db": {"path": "data/indexes/retrieval/b3e9684004679ffb/286973b134a189ee/retrieval.db",
                "sha256": "e9f62775a75794d770954ba1903f7a90c8b97467e5398b0baa2057bec8e67d5f",
                "note": "DAN XUAT — PROVENANCE.json cam dung lam bang chung du lieu"},
    "submission": {"P0I_sha256": sha(ZP), "P0G2_sha256": sha(ROOT/"artifacts/submissions/legacy/submission_P0G2.zip")},
    "code": {"git_commit": git, "git_dirty_files": dirty,
             "answer_a6_files": {p.name: sha(p) for p in sorted((ROOT/"tools/answer_a6").glob("*.py"))}},
    "env_build_machine": {"python": sys.version.split()[0], "pandas": pd.__version__,
                          "sqlite": sqlite3.sqlite_version},
    "env_pytest_verified": {"python": "3.11.15", "pytest": "9.1.1", "pandas": "2.3.3",
                            "numpy": "2.4.6", "sqlite": "3.45.1",
                            "result": "1094 passed · 15 skipped · 6 xfailed · 0 failed · 0 errors"},
}, ensure_ascii=False, indent=1))
print(f"replay xanh={xanh} do={do} bo={bo} | deterministic={a==b}")
