"""Chạy các test của P0-g mà không cần `pytest`.

Máy của anh không có mạng nên không cài được `pytest`; kho code thì nằm ở đó,
còn container có `pytest` lại không có `src/text2pandas`. Bộ chạy tối giản này
để cùng một tệp test dùng được ở cả hai nơi: `pytest tests/...` ở container,
`python3 tools/so_hoc/08_chay_test.py <tệp>` ở máy anh.
"""
from __future__ import annotations
import importlib.util, sys, traceback
from pathlib import Path

def main(argv):
    duong = Path(argv[0]).resolve()
    spec = importlib.util.spec_from_file_location(duong.stem, duong)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[duong.stem] = mod
    spec.loader.exec_module(mod)
    dat = hong = 0
    for ten in sorted(dir(mod)):
        if not ten.startswith("test_"):
            continue
        f = getattr(mod, ten)
        if not callable(f):
            continue
        try:
            f()
            dat += 1
        except Exception:
            hong += 1
            print(f"✗ {ten}")
            print("   " + traceback.format_exc().strip().splitlines()[-1])
    print(f"\n{dat} passed, {hong} failed  ({duong.name})")
    return 0 if hong == 0 else 1

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
