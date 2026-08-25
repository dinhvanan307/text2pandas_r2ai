#!/usr/bin/env python3
"""Inventory + kế hoạch commit theo TẦNG — đóng doc 140 §2.7 và Phase 0.

Doc 140 nói rõ: **không được hiểu "commit 199+ path" là `git add -A`**. Phải
tách source/config/test khỏi generated artifact và packet evidence, rồi commit
theo thứ tự: baseline sạch → preregistration neo vào baseline SHA → mới sửa code.

Tệp này **KHÔNG chạy git commit**. Nó chỉ:
  1. liệt kê đầy đủ mọi path đang thay đổi (mở cả thư mục untracked),
  2. phân loại từng path,
  3. gắn cờ path đáng ngờ (cache, .bak, file lớn, khoá/bí mật),
  4. sinh `scripts/commit_plan_d1a.sh` gồm 4 commit tách bạch để người đọc,
     sửa nếu cần, rồi tự chạy.

Vì sao không tự commit: commit là hành động ghi vào lịch sử dự án và quyết định
cái gì thuộc về baseline. Doc 140 §2.7 liệt kê "loại cache, dữ liệu tạm, secret,
output lớn" — đó là những phán đoán mà người chủ repo phải tự làm.

Chạy:  python3 tools/build_commit_plan_v1.py
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

RAC = ("__pycache__", ".pyc", ".DS_Store", ".ipynb_checkpoints", ".bak",
       ".egg-info", ".pytest_cache", ".mypy_cache")
NGHI_BI_MAT = (".env", "id_rsa", ".pem", "credentials", "secret", "token",
               ".netrc", ".htpasswd")
LON_MB = 5.0


def phan_loai(p: str) -> str:
    if any(s in p for s in RAC):
        return "RAC_KHONG_COMMIT"
    if p.startswith(("reports/", "artifacts/", "data/curated/evaluation/legacy/", "identity/",
                     "submissions/", "logs/", "verify_out/")) or p.endswith(
                         (".sha256", ".zip")) or p == "packet_kind.json":
        return "GENERATED_artifact"
    if p.startswith("data/"):
        return "DATA"
    if p.startswith("docs/"):
        return "DOC"
    if p.startswith("configs/"):
        return "CONFIG"
    if p.startswith(("src/", "tools/", "tests/", "env/", "scripts/")):
        return "SOURCE_TEST"
    return "KHAC_CAN_NGUOI_XEM"


def liet_ke() -> list[tuple[str, str]]:
    """Mở cả thư mục untracked — `git status --porcelain` gộp chúng thành 1 dòng."""
    ra = []
    for l in subprocess.run(["git", "status", "--porcelain", "-uall"], cwd=ROOT,
                            capture_output=True, text=True).stdout.splitlines():
        st, p = l[:2].strip(), l[3:].strip().strip('"')
        ra.append((st, p))
    return ra


def main() -> int:
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                          capture_output=True, text=True).stdout.strip()
    paths = liet_ke()
    nhom: dict[str, list] = {}
    canh_bao = []
    for st, p in paths:
        k = phan_loai(p)
        f = ROOT / p
        mb = round(f.stat().st_size / 1e6, 2) if f.is_file() else None
        nhom.setdefault(k, []).append({"status": st, "path": p, "size_mb": mb})
        if mb and mb > LON_MB:
            canh_bao.append({"path": p, "ly_do": f"file lớn {mb} MB", "size_mb": mb})
        if any(s in p.lower() for s in NGHI_BI_MAT):
            canh_bao.append({"path": p, "ly_do": "tên gợi ý bí mật/khoá"})

    def lay(*ks):
        return sorted(d["path"] for k in ks for d in nhom.get(k, []))

    c1 = lay("SOURCE_TEST", "CONFIG")
    c2 = lay("DOC")
    c3 = lay("GENERATED_artifact")
    c4 = lay("DATA")

    sh = ROOT / "scripts/commit_plan_d1a.sh"
    sh.parent.mkdir(parents=True, exist_ok=True)
    L = ["#!/usr/bin/env bash",
         "# Kế hoạch commit D1(a) — SINH TỰ ĐỘNG bởi tools/build_commit_plan_v1.py",
         "# ĐỌC TRƯỚC KHI CHẠY. Đây là đề xuất, không phải lệnh đã được duyệt.",
         "#",
         "# Thứ tự bắt buộc theo doc 140 §2.7:",
         "#   1. baseline source/config/test  ← neo mọi thứ về sau",
         "#   2. tài liệu",
         "#   3. preregistration  ← PHẢI trước lần đo đầu tiên",
         "#   4. artifact sinh ra (cân nhắc .gitignore thay vì commit)",
         "#",
         f"# HEAD hiện tại: {head}",
         f"# Tổng path đang thay đổi: {len(paths)}",
         "",
         "set -euo pipefail",
         f'cd "$(dirname "$0")/.."',
         "",
         "# ── 0 · rác, KHÔNG commit ───────────────────────────────────────────",
         "# " + (" ".join(lay("RAC_KHONG_COMMIT")) or "(không có)"),
         "",
         "# ── 1 · baseline source/config/test ────────────────────────────────"]
    L += [f"git add {p!r}" for p in c1]
    L += ['git commit -m "baseline(d1a): source/config/test trước vòng D1(a)"', "",
          "# ── 2 · tài liệu ───────────────────────────────────────────────────"]
    L += [f"git add {p!r}" for p in c2]
    L += ['git commit -m "docs(d1a): 137/138/140 + báo cáo thi hành"', "",
          "# ── 3 · preregistration — neo vào baseline SHA ở bước 1 ───────────",
          "git add 'docs/PREREGISTRATION_D1A.md'",
          'git commit -m "prereg(d1a): đăng ký giả thuyết/ngưỡng TRƯỚC khi đo"',
          "",
          "# ── 4 · artifact sinh ra ──────────────────────────────────────────",
          "# ⚠️ CÂN NHẮC: artifact tái sinh được bằng lệnh. Commit chúng làm phình",
          "#    lịch sử và dễ lệch với code. Lựa chọn khác: thêm vào .gitignore và",
          "#    chỉ đóng gói trong packet evidence có MANIFEST.sha256.",
          "#    Quyết định này là của người chủ repo — script để sẵn cả hai đường."]
    L += [f"# git add {p!r}" for p in c3]
    L += ['# git commit -m "artifacts(d1a): báo cáo đo vòng D1(a)"', "",
          "# ── 5 · dữ liệu ───────────────────────────────────────────────────"]
    L += [f"# git add {p!r}" for p in c4]
    L += ["", 'echo "Xong. Kiểm: git log --oneline -5"']
    sh.write_text("\n".join(L) + "\n", encoding="utf-8")
    sh.chmod(0o755)

    rep = {
        "_schema": "commit_plan v1 — đóng doc 140 §2.7 / Phase 0",
        "date": "2026-08-21",
        "HEAD": head,
        "n_path_thay_doi": len(paths),
        "dem_theo_nhom": {k: len(v) for k, v in sorted(
            nhom.items(), key=lambda x: -len(x[1]))},
        "canh_bao": canh_bao,
        "thu_tu_commit": ["source/config/test", "docs", "preregistration",
                          "artifact (tuỳ chọn)", "data (tuỳ chọn)"],
        "KHONG_TU_CHAY": ("Tệp này KHÔNG chạy git. `scripts/commit_plan_d1a.sh` là "
                          "đề xuất để người đọc và tự chạy. Quyết định cái gì thuộc "
                          "baseline là của chủ repo."),
        "chi_tiet": nhom,
        "command": "python3 tools/build_commit_plan_v1.py",
    }
    (ROOT / "reports/commit_plan_v1.json").write_text(
        json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"HEAD {head}  ·  {len(paths)} path đang thay đổi\n")
    for k, v in sorted(nhom.items(), key=lambda x: -len(x[1])):
        print(f"  {k:22} {len(v):4}")
    if canh_bao:
        print(f"\n⚠️ {len(canh_bao)} cảnh báo:")
        for c in canh_bao[:10]:
            print(f"   {c['path']} — {c['ly_do']}")
    print("\n-> scripts/commit_plan_d1a.sh (ĐỌC rồi tự chạy) · reports/commit_plan_v1.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
