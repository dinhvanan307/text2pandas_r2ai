#!/usr/bin/env bash
# Dựng môi trường SẠCH trên máy review từ một bản giải nén mới.
#
# Trả lời câu hỏi §8 số 3 của review 127: "Lệnh nào dựng environment sạch trên
# máy review mà KHÔNG dựa vào state có sẵn?"
#
# Nguyên tắc: không đụng python hệ thống, không đụng conda của người dùng,
# không giả định có sẵn pandas. venv nằm TRONG thư mục packet, xoá là sạch.
#
# Chạy từ packet root:
#     bash ops/environment/bootstrap_review_env.sh
#     . .venv-review/bin/activate
#     bash ops/environment/verify_packet.sh
set -eu

PY=${PY:-}
if [ -z "$PY" ]; then
  for c in python3.13 python3.12 python3.11; do
    command -v "$c" >/dev/null 2>&1 && { PY=$c; break; }
  done
fi
if [ -z "$PY" ]; then
  cat >&2 <<'MSG'
✗ không tìm thấy python3.11+ trên PATH.

  Contract của dự án là CPython >= 3.11 (pyproject.requires-python).
  Cài một bản 3.11+ rồi chạy lại, hoặc chỉ định:
  PY=/duong/dan/python3.11 bash ops/environment/bootstrap_review_env.sh

  Nếu BẮT BUỘC dùng 3.10: đặt PY=python3.10 ALLOW_OFF_CONTRACT=1. Mọi số đo ra
  phải mang nhãn MEASURED_OFF_CONTRACT_PY310 khi báo cáo.
MSG
  exit 2
fi

VER=$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')
case "$VER" in
  3.1[1-9]|3.[2-9]*) : ;;
  *)
    if [ "${ALLOW_OFF_CONTRACT:-0}" != "1" ]; then
      echo "✗ $PY là $VER, contract yêu cầu >=3.11. Đặt ALLOW_OFF_CONTRACT=1 nếu cố ý." >&2
      exit 2
    fi
    echo "⚠ chạy OFF-CONTRACT trên $VER — mọi số phải ghi MEASURED_OFF_CONTRACT_PY${VER%.*}${VER#*.}" >&2 ;;
esac

echo "• interpreter: $PY ($VER)"
"$PY" -m venv .venv-review
. .venv-review/bin/activate
python -m pip install -q -U pip
python -m pip install -q -r ops/environment/requirements-review.txt

python - <<'PY'
import json, platform, sys
import numpy, pandas
rep = {
    "python": sys.version,
    "python_short": "%d.%d.%d" % sys.version_info[:3],
    "platform": platform.platform(),
    "machine": platform.machine(),
    "pandas": pandas.__version__,
    "numpy": numpy.__version__,
    "on_contract_py311_plus": sys.version_info[:2] >= (3, 11),
}
open("ops/environment/review_env_actual.json", "w").write(json.dumps(rep, indent=1) + "\n")
print(json.dumps(rep, indent=1))
PY

echo "✓ môi trường sẵn sàng · ghi ops/environment/review_env_actual.json"
echo "  tiếp:  . .venv-review/bin/activate && bash ops/environment/verify_packet.sh"
