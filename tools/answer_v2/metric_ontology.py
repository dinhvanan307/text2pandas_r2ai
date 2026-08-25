#!/usr/bin/env python3
"""Metric ontology — ánh xạ nhãn A6 → `metric_id` chuẩn.

KHÔNG dùng PyYAML: repo không đảm bảo có nó ở mọi môi trường (bài học ghost-venv,
doc 128). Parser tối giản đọc đúng cấu trúc `configs/answer_v2/metrics_v1.yaml`.

ĐIỂM QUAN TRỌNG NHẤT LÀ `forbidden_aliases`.
`"no phai tra"` là tiền tố của `"no phai tra nguoi ban ngan han"`. Khớp tiền tố
mà không chặn thì `total_liabilities` nuốt hàng chục dòng con, và D/E sai một
cách **có hệ thống** — sai kiểu nguy hiểm nhất vì nó không bao giờ ném lỗi.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = ROOT / "configs/answer_v2/metrics_v1.yaml"


def chuan(s: str | None) -> str:
    """lower + bỏ dấu + gộp khoảng trắng. Dùng CHUNG cho alias và nhãn A6."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    s = s.replace("đ", "d")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


# ══════════════════════════════════════════════════════════════════════════════
# P0 · TIỀN TỐ DÒNG TỔNG  (cờ `ontology_fix`, mặc định TẮT)
# ══════════════════════════════════════════════════════════════════════════════
# A6 gắn tiền tố "Tổng"/"Tổng cộng"/"Cộng" vào NHÃN của dòng tổng hợp. Vì
# `match_policy: prefix_normalized` so khớp TIỀN TỐ, mọi dòng tổng như
# "TỔNG NỢ PHẢI TRẢ" đều KHÔNG khớp alias "no phai tra" — lá bị báo
# `METRIC_NOT_IN_POOL` dù gold nằm ngay trong pool đã truy hồi.
#
# ĐO ĐƯỢC (`reports/p0/<run>/audit/alias_audit.json`, work.db sha e9f62775…):
# 62 nhãn chuẩn hoá / **17.232 observation** rơi vào đúng lớp lỗi này. Đây là
# lỗi CẤU TRÚC của nguồn dữ liệu, không phải đặc thù của một câu hỏi — vì vậy
# sửa bằng một luật khai báo dùng chung, KHÔNG bằng alias vá riêng cho lá đang
# hỏng (điều đó là hard-code theo gold).
#
# FAIL CLOSED: bóc tiền tố mở ra hai lớp va chạm THẬT, đã đếm trên A6:
#   · "Tổng nợ phải trả VÀ vốn chủ sở hữu" (≈2.018 obs) = TỔNG TÀI SẢN,
#     không phải nợ phải trả. Bind nhầm ở đây làm D/E sai một cách hệ thống.
#   · dòng thuyết minh theo BỘ PHẬN / "không phân bổ" / "mang sang trang sau" /
#     dòng dẫn nhập đối chiếu lưu chuyển tiền tệ — cùng tiền tố, khác nghĩa.
# Cả hai lớp được chặn tường minh trong `forbidden_aliases` của
# `metrics_v1.yaml`, và `khop()` kiểm CHẶN trên **cả nhãn gốc lẫn nhãn đã bóc
# tiền tố** — bỏ vế thứ hai là để lọt đúng những dòng vừa mở ra.
AGGREGATE_PREFIXES: tuple[str, ...] = ("tong cong ", "tong ", "cong ")

# Dấu hiệu "KHÔNG PHẢI DÒNG TỔNG CỦA DOANH NGHIỆP" — kiểm bằng CHỨA, không phải
# tiền tố, vì trong A6 chúng đứng ở đuôi nhãn ("… cung cấp dịch vụ CỦA BỘ PHẬN").
# `forbidden_aliases` dùng `startswith` nên không bắt được lớp này.
#
# PHẠM VI ÁP DỤNG hẹp có chủ đích: chỉ chặn nhãn khớp được **nhờ** bóc tiền tố.
# Nhãn vốn đã khớp trực tiếp không bị đụng tới, nên luật này chỉ có thể THÊM
# match, không bao giờ làm mất match đang có — regression = 0 theo cấu tạo, và
# ablation `ontology_fix_only` vì thế là phép thử một chiều, đọc được.
KHONG_PHAI_TONG: tuple[str, ...] = (
    "bo phan",                 # thuyết minh theo bộ phận ≠ tổng doanh nghiệp
    "khong phan bo",           # mục không phân bổ trong thuyết minh bộ phận
    "ban ra ben ngoai",        # doanh thu ngoại bộ của một bộ phận
    "mang sang",               # dòng chuyển trang, không phải chỉ tiêu
    "dieu chinh cho cac khoan",  # dòng dẫn nhập đối chiếu lưu chuyển tiền tệ
    "trinh bay lai",           # nhãn trình bày lại — đã có `is_restated`
    "hop nhat",                # dòng đối chiếu hợp nhất trong thuyết minh
    "thuyet minh so",          # dòng chi tiết thuyết minh
)


def bo_tien_to_tong(n: str) -> str:
    """Bóc MỘT tiền tố dòng-tổng. Không lặp: 'tong tong x' không phải nhãn thật."""
    for p in AGGREGATE_PREFIXES:
        if n.startswith(p):
            return n[len(p):]
    return n


@dataclass(frozen=True)
class MetricSpec:
    metric_id: str
    aliases: tuple[str, ...]
    statement_types: tuple[str, ...]
    value_kind: str
    period_semantics: str
    sign_policy: str
    preferred_scope: str
    forbidden_aliases: tuple[str, ...]
    # Chặn theo CHỨA, không theo tiền tố. Cần thiết vì định ngữ phân bổ nằm ở
    # ĐUÔI nhãn ("lợi nhuận sau thuế … CỦA CỔ ĐÔNG CÔNG TY MẸ"), nơi
    # `forbidden_aliases` (startswith) không với tới. Chỉ hiệu lực khi
    # `ontology_fix=True`.
    forbidden_contains: tuple[str, ...] = ()


def _doc_list(raw: str) -> list[str]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()]
    return []


def load(path: Path = CFG) -> dict[str, MetricSpec]:
    """Parser tối giản cho đúng cấu trúc metrics_v1.yaml. Dừng ở `deferred:`."""
    out: dict[str, MetricSpec] = {}
    cur: dict = {}
    in_metrics = False
    khoa_cuoi = None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("metrics:"):
            in_metrics = True
            continue
        if line and not line[0].isspace() and in_metrics:
            break                                   # sang khoá cấp 1 khác
        if not in_metrics:
            continue
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        if s.startswith("- metric_id:"):
            if cur.get("metric_id"):
                out[cur["metric_id"]] = _build(cur)
            cur = {"metric_id": s.split(":", 1)[1].strip()}
            khoa_cuoi = None
            continue
        if s.startswith("- "):                       # phần tử list nhiều dòng
            if khoa_cuoi:
                cur.setdefault(khoa_cuoi, []).append(s[2:].strip().strip('"').strip("'"))
            continue
        if ":" in s:
            k, _, v = s.partition(":")
            k, v = k.strip(), v.strip()
            if v.startswith("["):
                cur[k] = _doc_list(v)
                khoa_cuoi = None
            elif v == "":
                cur[k] = []
                khoa_cuoi = k
            else:
                cur[k] = v.strip('"').strip("'")
                khoa_cuoi = None
    if cur.get("metric_id"):
        out[cur["metric_id"]] = _build(cur)
    return out


def _build(d: dict) -> MetricSpec:
    return MetricSpec(
        metric_id=d["metric_id"],
        aliases=tuple(chuan(a) for a in d.get("aliases", [])),
        statement_types=tuple(d.get("statement_types", [])),
        value_kind=d.get("value_kind", "money"),
        period_semantics=d.get("period_semantics", "point_in_time"),
        sign_policy=d.get("sign_policy", "signed_as_reported"),
        preferred_scope=d.get("preferred_scope", "consolidated"),
        forbidden_aliases=tuple(chuan(a) for a in d.get("forbidden_aliases", [])),
        forbidden_contains=tuple(chuan(a) for a in d.get("forbidden_contains", [])),
    )


def _bi_chan(spec: MetricSpec, n: str) -> bool:
    return any(n.startswith(f) for f in spec.forbidden_aliases)


def _khop_alias(spec: MetricSpec, n: str) -> bool:
    return any(n == a or n.startswith(a + " ") for a in spec.aliases)


def khop(spec: MetricSpec, nhan: str, *, ontology_fix: bool = False) -> bool:
    """Nhãn A6 có phải là `spec.metric_id` không? prefix_normalized + chặn con.

    Thứ tự kiểm BẮT BUỘC: chặn trước, khớp sau. Đảo lại thì
    `"no phai tra nguoi ban"` khớp tiền tố `"no phai tra"` rồi mới bị chặn —
    cùng kết quả ở đây, nhưng đảo thứ tự làm người đọc tưởng chặn là tuỳ chọn.

    `ontology_fix=True` cho phép nhãn dòng-tổng ("Tổng nợ phải trả") khớp, sau
    khi đã kiểm chặn trên CẢ hai dạng — xem khối ghi chú AGGREGATE_PREFIXES.
    """
    n = chuan(nhan)
    if not n:
        return False
    if _bi_chan(spec, n):
        return False
    if ontology_fix and any(m in n for m in spec.forbidden_contains):
        return False
    if _khop_alias(spec, n):
        return True
    if not ontology_fix:
        return False
    s = bo_tien_to_tong(n)
    if s == n or _bi_chan(spec, s):
        return False
    if any(m in n for m in KHONG_PHAI_TONG):
        return False
    return _khop_alias(spec, s)


def nhan_dien(specs: dict[str, MetricSpec], nhan: str, *,
              ontology_fix: bool = False) -> str | None:
    """Nhãn A6 → metric_id, hoặc None.

    Khi nhiều spec cùng khớp, chọn spec có alias khớp DÀI NHẤT — alias dài là
    alias cụ thể hơn. Nhãn khớp TRỰC TIẾP luôn thắng nhãn chỉ khớp sau khi bóc
    tiền tố: "tổng tài sản" phải là `total_assets` (alias trực tiếp), không
    được rơi về một metric khác chỉ vì bóc "tong " ra cũng khớp được cái gì đó.
    """
    tot, best = None, (-1, -1)
    n = chuan(nhan)
    s = bo_tien_to_tong(n) if ontology_fix else n
    for mid, sp in specs.items():
        if not khop(sp, nhan, ontology_fix=ontology_fix):
            continue
        truc_tiep = _khop_alias(sp, n) and not _bi_chan(sp, n)
        goc = n if truc_tiep else s
        dai = max((len(a) for a in sp.aliases if goc.startswith(a)), default=0)
        hang = (1 if truc_tiep else 0, dai)
        if hang > best:
            best, tot = hang, mid
    return tot
