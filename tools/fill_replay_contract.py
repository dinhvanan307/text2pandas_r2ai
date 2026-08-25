#!/usr/bin/env python3
"""B0-04b · điền `expected` cho 10 ca replay TỪ RC1, không từ output RC2.

Đầu vào là output của `tools/pick_replay_fixtures.py` — công cụ chọn ca bằng
review độc lập trên RC1 release DB (read-only), sắp xếp tất định theo UID.

Đầu ra là `configs/replay_expected_v1.yaml` với selector + kỳ vọng đã khoá.
Từ lúc này, `replay_report.py` chỉ được đọc hợp đồng; nó KHÔNG bao giờ được
suy kỳ vọng từ DB đang kiểm.

    python tools/fill_replay_contract.py --picked <picked.json> \\
        --out configs/replay_expected_v1.yaml --db-sha256 <sha256 cua RC1>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

# Trường được ghim cho mỗi ô. Chỉ ghim thứ ổn định và có ý nghĩa đối chiếu.
CELL_FIELDS = ("observation_uid", "source_cell_uid", "evidence_ref",
               "metric_label_clean", "period_end", "value_decimal_text",
               "unit_kind", "currency", "scale_exponent")


def _sel(r: dict) -> dict:
    """Selector của một ô — CHỈ dùng khoá vật lý, không dùng nhãn."""
    out = {}
    if r.get("directory_doc_id"):
        out["doc_id"] = r["directory_doc_id"]
    for k in ("table_uid", "row_uid", "column_uid"):
        if r.get(k):
            out[k] = r[k]
    return out


def _cell(r: dict) -> dict:
    return {**_sel(r),
            "expect": {k: (str(r[k]) if r.get(k) is not None else None)
                       for k in CELL_FIELDS if r.get(k) is not None}}


def build(picked: dict) -> list[dict]:
    C: list[dict] = []

    def add(cid, name, intent, **kw):
        C.append({"id": cid, "name": name, "intent": intent, **kw})

    # 01 · một chỉ tiêu, một kỳ — ca cơ bản nhất
    r = picked["01"]
    add("01", "lookup_one_metric_one_period", "một chỉ tiêu một kỳ",
        abstain=False, **_sel(r),
        expected={k: str(r[k]) for k in CELL_FIELDS if r.get(k) is not None},
        selection_rule="nhãn xuất hiện ĐÚNG MỘT LẦN trong bảng, và bảng chỉ có "
                       "ĐÚNG MỘT kỳ — không có cách lấy nhầm ô mà vẫn đúng nhãn")

    # 02 · so hai kỳ — hai ô, cùng dòng
    p = picked["02"]
    add("02", "compare_two_periods", "cùng chỉ tiêu, hai kỳ",
        abstain=False, expected_cells=[_cell(p["earlier"]), _cell(p["later"])],
        selection_rule="cùng (table_uid,row_uid), đúng 2 kỳ, mỗi (dòng,kỳ) một ô")

    # 03 · tăng trưởng — hai ô + khẳng định suy ra
    g = picked["03"]
    add("03", "growth", "tăng trưởng giữa hai kỳ",
        abstain=False, expected_cells=[_cell(g["earlier"]), _cell(g["later"])],
        derived={"kind": "growth",
                 "formula": "(later - earlier) / earlier",
                 "expected_decimal": g.get("expected_growth_decimal")},
        selection_rule="mẫu số khác 0; giá trị Decimal, không làm tròn")

    # 04 · tỷ số hai chỉ tiêu cùng bảng/kỳ/cột
    q = picked["04"]
    add("04", "ratio", "tỷ số hai chỉ tiêu",
        abstain=False,
        expected_cells=[_cell(q["numerator"]), _cell(q["denominator"])],
        derived={"kind": "ratio", "formula": "numerator / denominator",
                 "expected_decimal": q.get("expected_ratio_decimal")},
        selection_rule="HAI DÒNG KHÁC NHAU, giá trị khác nhau, mẫu số ≠ 0 — "
                       "tỷ số = 1 không kiểm được gì")

    # 05 · cộng dòng con, LOẠI dòng tổng
    s5 = picked["05"]
    add("05", "aggregation_excluding_totals", "cộng dòng con, loại subtotal",
        abstain=False, expected_cells=[_cell(s5["total_row"])],
        derived={"kind": "sum_children",
                 "expected_decimal": s5.get("expected_sum_decimal"),
                 "n_children": len(s5.get("child_rows") or []),
                 "children_observation_uids": [c["observation_uid"]
                                               for c in s5.get("child_rows") or []],
                 "rule": s5.get("rule")},
        selection_rule="đúng một dòng tổng; tổng các dòng con KHỚP CHÍNH XÁC")

    # 06 · hai bảng cùng tài liệu
    s6 = picked["06"]
    add("06", "multi_table_same_document", "hai bảng trong cùng tài liệu",
        abstain=False, expected_cells=[_cell(t) for t in s6["tables"][:2]],
        derived={"kind": "join_by_table_uid", "rule": s6.get("rule")},
        selection_rule="join theo table_uid; CẤM trộn kỳ giữa hai bảng")

    # 07 · nhiều tài liệu cùng ticker
    s7 = picked["07"]
    add("07", "multi_document", "nhiều tài liệu cùng doanh nghiệp",
        abstain=False, expected_cells=[_cell(d) for d in s7["documents"][:2]],
        derived={"kind": "key_by_ticker_year_basis", "rule": s7.get("rule")},
        selection_rule="khoá theo (ticker, doc_year, basis)")

    # 08 · bảng không header → PHẢI abstain
    r8 = picked["08"]
    add("08", "no_header_table", "bảng không có header",
        abstain=True, **_sel(r8),
        expected_abstain_reason="bảng không có header nên nhãn cột không địa chỉ hoá được "
                       "một ô duy nhất — hệ thống phải TỪ CHỐI thay vì đoán",
        evidence_ref=r8.get("evidence_ref"))

    # 09 · nhãn trùng, phân biệt bằng dimension
    s9 = picked["09"]
    add("09", "duplicate_label_with_dimension", "nhãn trùng, phân biệt bằng chiều",
        abstain=False,
        expected_cells=[_cell(s9["variant_a"]), _cell(s9["variant_b"])],
        derived={"kind": "must_distinguish_by_row_path",
                 "rule": s9.get("rule")},
        selection_rule="hai ô CÙNG nhãn CÙNG kỳ nhưng KHÁC row_path — phải phân "
                       "biệt được, không phân biệt được thì abstain")

    # 10 · mơ hồ có chủ đích → PHẢI abstain
    r10 = picked["10"]
    add("10", "unresolved_must_abstain", "fact mơ hồ phải từ chối trả lời",
        abstain=True, **_sel(r10),
        expected_abstain_reason=f"collision_class={r10.get('collision_class')} — fact mơ hồ "
                       f"KHÔNG được vào execution_ready; hệ thống phải từ chối",
        collision_class=r10.get("collision_class"),
        evidence_ref=r10.get("evidence_ref"))
    return C


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--picked", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--db-sha256", required=True)
    ap.add_argument("--filled-at", required=True,
                    help="timestamp UTC của lần điền (truyền vào để tất định)")
    a = ap.parse_args()

    picked = json.loads(a.picked.read_text(encoding="utf-8"))
    missing = [k for k in (f"{i:02d}" for i in range(1, 11))
               if not picked.get(k)]
    if missing:
        print(f"LỖI: selector chưa chọn được ca {missing} — KHÔNG điền thiếu",
              file=sys.stderr)
        return 3

    cases = build(picked)
    doc = {
        "contract_version": "2.1",
        "status": "VALUES_FROZEN",
        "supersedes": "2.0 (khung đóng băng, 1/10 ca có expected)",
        "frozen_at_phase": "P3 (khung) · RC-02 (giá trị) · B0-04b (điền đủ 10 ca)",
        "fixture_version": "1.1",
        "evidence_db": "artifacts/rc1_baseline/silver.db",
        "evidence_db_sha256": a.db_sha256,
        # RC2-027 · Ten truong phai noi dung ban chat cua gia tri.
        #
        # Day KHONG phai mot phep do — no la mot HANG SO KHAI BAO, va no bat
        # buoc phai la hang so: tep hop dong nay di vao `config_hash`, nen mot
        # dau thoi gian THAT se lam `build_id` doi moi lan sinh lai contract.
        # Ten cu `filled_at_utc` doc nhu mot phep do, va gia tri dang nam o
        # TUONG LAI so voi luc sinh — dung dau hieu cua mot so duoc khai chu
        # khong duoc do.
        "frozen_at_declared": a.filled_at,
        "frozen_at_note": ("HANG SO KHAI BAO, khong phai phep do. Phai co dinh "
                           "de contract sinh lai cho ra tep y het — tep nay di "
                           "vao config_hash."),
        "filled_from_db_sha256": a.db_sha256,
        "selector": "tools/pick_replay_fixtures.py",
        "selector_determinism": "sắp xếp theo UID rồi lấy đầu; chạy lại cho cùng kết quả",
        "provenance": ("Kỳ vọng lấy TỪ RC1 release DB, KHÔNG từ output RC2. "
                       "Đây là điều kiện để C5 không phải bài thi tự ra đề."),
        "cases": cases,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False,
                                    width=100), encoding="utf-8")
    n_exp = sum(1 for c in cases if c.get("expected") or c.get("expected_cells"))
    n_abs = sum(1 for c in cases if c.get("abstain"))
    print(f"  ghi {a.out}")
    print(f"  {len(cases)} ca · {n_exp} có kỳ vọng · {n_abs} abstain")
    for c in cases:
        kind = "abstain" if c.get("abstain") else (
            f"{len(c.get('expected_cells', []))} ô" if c.get("expected_cells") else "1 ô")
        print(f"    {c['id']} {c['name'][:40]:<42}{kind}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
