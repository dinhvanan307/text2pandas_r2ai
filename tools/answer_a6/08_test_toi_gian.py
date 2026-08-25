"""Runner TỐI GIẢN cho resolver. ĐÂY KHÔNG PHẢI PYTEST — xem docs/97 §Testing."""
import importlib.util, sys
from decimal import Decimal
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
spec = importlib.util.spec_from_file_location("r", ROOT / "tools/answer_a6/01_resolver.py")
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
T = []
def ok(ten, dk):
    T.append((ten, bool(dk)))
ok("vnd scale 6", m.vnd("153234", 6) == Decimal("153234000000"))
ok("vnd scale 0", m.vnd("1523377869886", 0) == Decimal("1523377869886"))
ok("vnd scale None -> 10^0", m.vnd("12", None) == Decimal("12"))
ok("vnd am", m.vnd("-208253201298", 0) == Decimal("-208253201298"))
ok("vnd hong -> None", m.vnd("abc", 0) is None)
ok("neo nhan so thuan", m._khong_thanh_so("2018", "2018-12-31") == "2018 (2018-12-31)")
ok("khong neo nhan chu", m._khong_thanh_so("2018VND", "2018-12-31") == "2018VND")
ok("neo nhan thap phan", m._khong_thanh_so("31,5", None) == "31,5 (ky)")
ok("diem nhan rong = 0", m.diem_nhan({"a"}, "") == 0.0)
ok("diem nhan co khop > 0", m.diem_nhan(set(m.tokenize("chi phi ban hang")), "Chi phí bán hàng") > 0)
ok("_f chuoi", m._f("0.83") == 0.83)
ok("_f None -> 0", m._f(None) == 0.0)
ok("thu tu role", m.UU_TIEN_ROLE["current"] < m.UU_TIEN_ROLE["prior"])
do = [t for t, k in T if not k]
print(f"RUNNER TOI GIAN: {len(T)-len(do)} xanh · {len(do)} do")
for t in do: print("   DO:", t)
sys.exit(1 if do else 0)
