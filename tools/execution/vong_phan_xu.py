"""Chạy vòng: resolver -> gom xung đột MỚI -> phân xử -> lặp, tới khi cổng B3 = 0.

Vì chặn một observation làm resolver chọn observation KHÁC, xung đột mới có thể
xuất hiện. Một lượt phân xử là không đủ — phải lặp tới điểm bất động.
"""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
H0 = ROOT / "artifacts/execution/h0"
XD, PX = H0 / "unit_evidence_conflicts.jsonl", H0 / "unit_conflict_adjudication.jsonl"


def chay(*cmd, env=None):
    e = dict(os.environ); e.update(env or {})
    r = subprocess.run([sys.executable, *cmd], cwd=ROOT, capture_output=True, text=True, env=e)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def con_uncertain() -> int:
    n = 0
    for l in (ROOT / "data/curated/dev-legacy/answer_a6/records_a6.jsonl").open(encoding="utf-8"):
        r = json.loads(l)
        if (r.get("provenance") or {}).get("scale_UNCERTAIN"):
            n += 1
    return n


def main() -> int:
    for vong in range(1, 7):
        rc, out = chay("tools/answer_a6/01_resolver.py", env={"RESET": "1"})
        print(f"[vong {vong}] resolver rc={rc} · {out.strip().splitlines()[-1] if out.strip() else ''}")
        if rc:
            print(out[-800:]); return rc
        n = con_uncertain()
        print(f"[vong {vong}] con scale_UNCERTAIN = {n}")
        if n == 0:
            print("=> CONG B3 DAT: 0 record PRIMARY_A6 mang scale_UNCERTAIN")
            return 0
        da = {json.loads(l)["observation_uid"] for l in PX.open(encoding="utf-8")} if PX.is_file() else set()
        cu = list(PX.open(encoding="utf-8")) if PX.is_file() else []
        rc, out = chay("tools/answer_a6/09_dung_h0.py")     # dựng lại file xung đột
        if rc: print(out[-500:]); return rc
        rc, out = chay("tools/execution/phan_xu_don_vi.py")
        print(f"[vong {vong}] phan xu: {out.strip().splitlines()[-1]}")
        moi = [l for l in PX.open(encoding="utf-8") if json.loads(l)["observation_uid"] not in da]
        with PX.open("w", encoding="utf-8") as f:          # GIỮ phán quyết cũ + thêm mới
            f.writelines(cu); f.writelines(moi)
        print(f"[vong {vong}] them {len(moi)} phan quyet moi · tong {len(cu)+len(moi)}")
    print("KHONG HOI TU sau 6 vong"); return 1


if __name__ == "__main__":
    raise SystemExit(main())
