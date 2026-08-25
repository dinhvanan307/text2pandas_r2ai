#!/usr/bin/env python3
"""B5 — so hai build theo DANH TÍNH VẬT LÝ, không theo `row_path`.

Đây là chỗ `row_uid` trả cổ tức. `row_path_text` sẽ đổi diện rộng khi v1.2 hạ
cánh, nên so bằng nó thì mọi dòng đều "thay đổi" và audit vô nghĩa. So bằng
`source_cell_uid` / `row_uid` / `column_uid` thì thấy đúng cái gì thật sự đổi.

Doc 12 §5.2 đòi mọi delta có `reason class` và `unexplained delta = 0`.

CHỈ ĐỌC cả hai DB.

    python tools/differential_audit.py OLD.sqlite NEW.sqlite -o reports/
"""
from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
from pathlib import Path

# Trường ngữ nghĩa được PHÉP đổi giữa RC và Final (enrichment, doc 08 §4).
SEMANTIC = ("row_path_text", "col_path_text", "metric_label_clean")

# RC2-036/037 · TÁCH `FACTUAL` làm hai. Gộp chung là lý do một hồi quy phân
# loại nằm cùng rổ với "giá trị bị đổi", và cả rổ chỉ có một con số duy nhất.
#
#   MEASURED   — thứ ĐO ĐƯỢC từ tài liệu. Đổi = đọc sai tài liệu. Ngưỡng 0,
#                không có lớp lý do nào tha được. Đây là siết CHẶT hơn bản cũ:
#                trước đây một `value_decimal_text` bị đổi nằm chung lớp với
#                20.197 ca đổi nhãn đơn vị, nên nó vô hình.
#   CLASSIFIED — kết luận SUY RA từ ngữ cảnh. Được phép đổi khi luật suy diễn
#                đổi, nhưng phải khớp MỘT lớp lý do đã khai; không khớp thì vẫn
#                `factual_changed_NEEDS_REVIEW` và vẫn chặn.
MEASURED = ("value_decimal_text", "period_end", "is_negative")
CLASSIFIED = ("value_kind", "unit_kind", "scale_exponent", "currency")
FACTUAL = MEASURED + CLASSIFIED          # giữ tên cũ cho mã gọi ngoài

# Nhãn chất lượng ĐƯỢC KHAI là có thể xuất hiện thêm ở RC2 (RC-03 tiny money).
# Nhãn ngoài danh sách này xuất hiện = luật lạ đang chạy, và vẫn bị chặn.
DECLARED_NEW_FLAGS = frozenset({
    "tiny_money_legitimate", "tiny_money_unresolved", "tiny_money_dropped",
    "tiny_money_metric_code_false_value", "tiny_money_ordinal_false_value",
    "tiny_money_note_reference_false_value",
    "tiny_money_legitimate_per_share_or_rate_value",
    "tiny_money_legitimate_small_money",
    "tiny_money_parse_or_column_role_unresolved",
    # AMD-A4-01 · cờ RC2-039. Đo trên A4: đúng 551 ô, và cả 551 đều có
    # `execution_ready = 0` — cờ này SINH RA để chặn, nên nó xuất hiện kèm
    # readiness đổi theo. Khai ở đây vì nó là nhãn MỚI theo luật ĐÃ KHAI,
    # không phải nhãn lạ do luật lạ sinh ra.
    "unit_ambiguous_share_column",
    # AMD-A5-01 · cờ chặn ô "phần trăm" có độ lớn không thể là phần trăm.
    # Đo trên A4: 696 ô sẽ mang cờ này, 445 trong số đó là candidate. Cờ SINH
    # RA để chặn nên nó luôn đi kèm readiness đổi theo.
    "percent_value_implausible",
    # AMD-A5-02 · cờ đánh dấu kỳ suy từ trục DÒNG. Xem `_period_recovered_from_row`.
    "period_from_row_path",
})

# `value_kind` và `unit_kind` là hai cách gọi cùng một kết luận. Đổi ĐỒNG BỘ
# sang cùng một họ là re-inference hợp lệ; đổi lệch nhau là mâu thuẫn nội tại.
_KIND_FAMILY = {
    "money": "money", "share_count": "shares", "shares": "shares",
    "interest_rate": "rate", "rate": "rate", "days": "days",
    "percentage": "percent", "percent": "percent", "count": "count",
}


def _family(v) -> str | None:
    return _KIND_FAMILY.get(str(v).lower()) if v is not None else None


def _consistent(value_kind, unit_kind) -> bool:
    """Cặp (`value_kind`, `unit_kind`) có tự mâu thuẫn không?

    Dùng ĐÚNG định nghĩa của bất biến C4-10 trong `gates.py`: `unknown`/NULL là
    "chưa xác định được" — trung thực, không mâu thuẫn. Chỉ một LOẠI ĐƠN VỊ
    KHÁC mới là mâu thuẫn. Hai nơi phải dùng chung một định nghĩa, nếu không
    cổng và audit sẽ nói hai điều khác nhau về cùng một bản ghi.
    """
    u = str(unit_kind or "").strip().lower()
    if u in ("", "none", "null", "unknown"):
        return True
    return _family(u) == _family(value_kind)


# Đổi TÊN nhãn đã khai giữa RC1 và RC2 (RC-04 mục 3, xem
# `unit_resolver.UnitResolution.flags`). Bản đồ này CỐ ĐỊNH và chỉ có đúng
# những cặp đã khai — một nhãn biến mất mà không có trong đây thì vẫn bị chặn.
_FLAG_RENAMES = {"unit_assumed": "unit_scale_assumed_no_evidence"}


def _flags_delta(o, n):
    """Trả `(them, mat, co_doi_ten)`. `None` khi không đọc được — không suy đoán."""
    try:
        a = set(json.loads(o or "[]"))
        b = set(json.loads(n or "[]"))
    except (TypeError, ValueError):
        return None
    doi_ten = bool(a & set(_FLAG_RENAMES))
    a2 = {_FLAG_RENAMES.get(x, x) for x in a}
    return b - a2, a2 - b, doi_ten


def _meta(con) -> dict:
    try:
        return dict(con.execute("SELECT key, value FROM build_meta"))
    except sqlite3.Error:
        return {}


# Cột không mang ý nghĩa so sánh (thứ tự vật lý, dấu vết build).
NON_COMPARABLE = frozenset({"created_at", "build_time", "seconds"})

# AMD-A4-01 · dùng CHÍNH luật production làm bằng chứng, không chép lại regex.
# Chép lại là tạo nguồn sự thật thứ hai, và hai nguồn sẽ lệch nhau ở lần sửa
# tiếp theo mà không ai thấy.
try:
    from text2pandas.pipelines.a6.number_parser import _SHARE_COUNT_STRONG as _ROW_COUNT_SIGNAL
except Exception:                                            # pragma: no cover
    _ROW_COUNT_SIGNAL = None


def _load(con, all_columns: bool = True) -> dict:
    """B0-03 mục 4: bản cũ chỉ so 9 field; đổi ở cột ngoài danh sách KHÔNG ai
    khai. Nay so TOÀN BỘ cột chung, và cột ngoài hợp đồng đổi thì bị chặn."""
    have = [r[1] for r in con.execute("PRAGMA table_info(observations)")]
    key = ["source_cell_uid", "observation_uid", "table_uid", "row_uid", "column_uid"]
    if all_columns:
        cols = key + [c for c in have
                      if c not in key and c not in NON_COMPARABLE]
    else:
        cols = key + [*FACTUAL, *SEMANTIC]
    use = [c for c in cols if c in have]
    return {r[0]: dict(zip(use, r)) for r in con.execute(
        f"SELECT {', '.join(use)} FROM observations")}, use


# AMD-A5-02 · trường đi kèm khi kỳ được giải lại. Chúng đổi CÙNG `period_end`
# hoặc không đổi gì — không có trường hợp thứ ba.
_PERIOD_COMPANION = ("period_start", "as_of_date", "period_type", "period_role",
                     "period_source", "quarter", "is_restated")


def _period_recovered_from_row(o: dict, n: dict,
                               fields: list[str] | None = None) -> bool:
    """AMD-A5-02 · `period_end` đi từ NULL sang một ngày, nhờ luật A5-B1.

    `period_end` nằm trong `MEASURED`, và `MEASURED` đổi là chặn cứng — cố ý,
    vì ở đó "đổi" nghĩa là đọc sai tài liệu. Nhưng NULL → giá trị KHÔNG phải
    đọc sai: trước đây không có kết luận nào, nay có một kết luận rút từ ngày
    tuyệt đối trong nhãn dòng.

    Vị từ này CỐ Ý hẹp đến mức gần như không thể khớp nhầm. Nó đòi ĐỦ SÁU điều:

      1. cũ `period_end` NULL, mới KHÔNG NULL          (không phải sửa giá trị)
      2. cũ `period_source` = 'none'                   (đúng cohort chưa giải)
      3. mới `period_source` = 'row_context'           (đúng luật A5-B1)
      4. cờ `period_from_row_path` được THÊM           (production tự khai)
      5. mọi `MEASURED` khác giữ nguyên                (giá trị đo không đụng)
      6. mọi `CLASSIFIED` và `SEMANTIC` giữ nguyên     (phân loại không đụng)

    Và mọi trường còn lại có đổi phải nằm trong `_PERIOD_COMPANION` hoặc là
    `quality_flags_json`. Một trường lạ đổi kèm thì vị từ trả False và bản ghi
    rơi lại vào `measured_value_changed_BLOCKING` như cũ.

    `period_end` đi từ giá trị này sang giá trị KHÁC vẫn chặn cứng — điều kiện
    1 loại thẳng. Đây là thu hẹp phạm vi, không phải nới ngưỡng.
    """
    if o.get("period_end") is not None or n.get("period_end") is None:
        return False
    if str(o.get("period_source") or "") != "none":
        return False
    if str(n.get("period_source") or "") != "row_context":
        return False
    d = _flags_delta(o.get("quality_flags_json"), n.get("quality_flags_json"))
    if d is None:
        return False
    them, mat, _ = d
    if "period_from_row_path" not in them or not (them <= DECLARED_NEW_FLAGS):
        return False
    # Cờ DUY NHẤT được phép biến mất ở đây, và nó BẮT BUỘC phải biến mất:
    # `period_unresolved` do production phát ra khi ô không có kỳ. Ô vừa nhận
    # được kỳ mà vẫn mang cờ "chưa giải được kỳ" là dữ liệu tự mâu thuẫn.
    #
    # Bản đầu của vị từ này từ chối MỌI cờ bị mất, nên cả 21.438 ô rơi xuống
    # `measured_value_changed_BLOCKING` ở lần chạy differential A4→A5 đầu
    # tiên. Bài test đi kèm không bắt được vì tôi viết nó với `period_unresolved`
    # có mặt ở CẢ HAI vế — một giả định, không phải một quan sát. Xem
    # `test_co_period_unresolved_PHAI_bien_mat`.
    # BẰNG chứ không phải TẬP CON: `period_unresolved` phải biến mất, đúng nó,
    # và không cờ nào khác được biến mất. Ô cũ chắc chắn mang cờ này (kỳ NULL
    # thì production luôn phát ra nó), nên đây là vân tay chính xác của luật
    # A5-B1. Nếu một ngày production thôi gỡ cờ, differential đỏ ngay thay vì
    # lặng lẽ cho qua một bản ghi tự mâu thuẫn.
    if mat != {"period_unresolved"}:
        return False
    if any(o.get(f) != n.get(f) for f in MEASURED if f != "period_end"):
        return False
    if any(o.get(f) != n.get(f) for f in (*CLASSIFIED, *SEMANTIC)):
        return False
    if fields:
        cho_phep = set(_PERIOD_COMPANION) | {"quality_flags_json"} | set(FACTUAL)
        if any(f not in cho_phep for f in fields if o.get(f) != n.get(f)):
            return False
    return True


def _reason(o: dict, n: dict, fields: list[str] | None = None) -> str:
    """Gán LỚP LÝ DO cho một thay đổi. `unexplained` là lớp phải bằng 0.

    B0-03 mục 3: bản cũ đặt `continue` khi mọi field FACTUAL+SEMANTIC bằng nhau,
    nên nhánh `unexplained` KHÔNG THỂ TỚI và `unexplained_changed = 0` không
    chứng minh được gì. Nay vòng lặp gọi hàm này cho MỌI bản ghi có ít nhất một
    cột khác, kể cả cột ngoài hai danh sách — nên `unexplained` có nghĩa thật.
    """
    # 0 · AMD-A5-02 · kỳ giải được lần đầu từ trục dòng. Xét TRƯỚC bước 1 vì
    # vị từ này tự kiểm toàn bộ bản ghi — nó không cho lọt thứ gì mà bước 1
    # đến bước 3 lẽ ra phải chặn.
    if _period_recovered_from_row(o, n, fields):
        return "period_recovered_from_row_path"

    # 1 · ĐO ĐƯỢC đổi -> chặn cứng, không lớp lý do nào tha.
    if any(o.get(f) != n.get(f) for f in MEASURED):
        return "measured_value_changed_BLOCKING"

    # 2 · SUY RA đổi -> phải khớp một lớp lý do đã khai.
    if any(o.get(f) != n.get(f) for f in CLASSIFIED):
        changed = [f for f in CLASSIFIED if o.get(f) != n.get(f)]
        if changed == ["scale_exponent"]:
            return "scale_reconciled"
        # RC2-036 · CHỐT CHẶN DUY NHẤT của cả nhóm này: bản ghi MỚI không được
        # tự mâu thuẫn. Kết thúc ở trạng thái mâu thuẫn thì không lớp lý do nào
        # tha — kể cả khi thay đổi trông có vẻ hợp lý.
        cu_on = _consistent(o.get("value_kind"), o.get("unit_kind"))
        moi_on = _consistent(n.get("value_kind"), n.get("unit_kind"))
        if not moi_on:
            return "factual_changed_NEEDS_REVIEW"

        # AMD-A4-01 · suy lại từ nhãn DÒNG. Lớp riêng, không gộp vào lớp
        # "suy từ nhãn cột", vì gộp lại thì báo cáo nói sai bằng chứng nào đã
        # dùng — và bằng chứng là thứ reviewer kiểm.
        #
        # Điều kiện hẹp có chủ đích: chỉ money → share_count, và nhãn dòng phải
        # thật sự mang tín hiệu đếm MẠNH theo đúng luật production. Mọi hình
        # dạng khác vẫn rơi xuống NEEDS_REVIEW.
        if ("value_kind" in changed
                and o.get("value_kind") == "money"
                and n.get("value_kind") == "share_count"
                and _ROW_COUNT_SIGNAL is not None
                and _ROW_COUNT_SIGNAL.search(n.get("row_path_text") or "")):
            return "unit_kind_from_row_path_count_signal"

        # `value_kind` được suy lại từ nhãn cột, và đơn vị mới không mâu thuẫn.
        if "value_kind" in changed:
            return "unit_reinferred_from_column_path"

        # SỬA CHỮA: `value_kind` giữ nguyên, `unit_kind` đi từ MÂU THUẪN sang
        # NHẤT QUÁN. Đây chính là hình dạng của bản vá RC2-036 khi nó hạ cánh —
        # `money`+`rate` trở thành `money`+`money` hoặc `money`+`unknown`.
        #
        # Lớp này KHÔNG nới lỏng gì: nó đòi trạng thái CŨ phải mâu thuẫn và
        # trạng thái MỚI phải nhất quán. Một bản ghi vốn đã đúng mà bị đổi đơn
        # vị sang thứ khác vẫn rơi xuống NEEDS_REVIEW.
        if "unit_kind" in changed and not cu_on:
            return "unit_kind_repaired_to_match_value_kind"
        return "factual_changed_NEEDS_REVIEW"

    if any(o.get(f) != n.get(f) for f in SEMANTIC):
        return "semantic_enrichment"

    # 3 · Ngoài hợp đồng. Nhãn chất lượng thêm theo LUẬT ĐÃ KHAI là hợp lệ;
    # nhãn lạ hoặc trường lạ thì vẫn chặn.
    if fields:
        out = [f for f in fields
               if f not in FACTUAL and f not in SEMANTIC and o.get(f) != n.get(f)]
        # Xét TỪNG trường một. Mọi trường phải tự giải thích được; chỉ cần một
        # trường không có vị từ nào nhận là cả bản ghi bị chặn.
        #
        # Trước đây chỉ khớp khi out ĐÚNG BẰNG một tên, nên 4 ca đổi ĐỒNG THỜI
        # `quality_flags_json` + `scale_source` — mà mỗi vế đều đã khai — vẫn bị
        # chặn. Chặn vì "chưa xét tới" khác với chặn vì "có vấn đề"; gộp hai
        # thứ đó lại làm phán quyết mất nghĩa.
        nhan: list[str] = []
        for f in out:
            if f == "quality_flags_json":
                d = _flags_delta(o.get(f), n.get(f))
                if d is None:
                    break
                them, mat, doi_ten = d
                # Mất một nhãn mà không phải do đổi tên đã khai -> vẫn chặn.
                if mat or not (them <= DECLARED_NEW_FLAGS):
                    break
                nhan.append("quality_flag_renamed_by_declared_rule" if doi_ten
                            else "quality_flag_added_by_declared_rule")
            elif f == "scale_source":
                # Chỉ NGUỒN BẰNG CHỨNG đổi mà GIÁ TRỊ nó dẫn ra thì không: cùng
                # một bậc 10, nay quy cho một tầng nhãn khác.
                if o.get("scale_exponent") != n.get("scale_exponent"):
                    break
                nhan.append("evidence_source_changed_same_value")
            else:
                break
        else:
            if nhan:
                return (nhan[0] if len(nhan) == 1
                        else "out_of_contract_declared_changes")
        if out:
            return "out_of_contract_field_changed"
    return "unexplained"


def _added_reason(uid: str, row: dict, con_old, con_new) -> str:
    """LỚP LÝ DO cho observation MỚI XUẤT HIỆN ở RC2.

    B0-03 mục 2: bản cũ chỉ ĐẾM added, không phân loại — nên không ai biết
    2 triệu dòng mới là khôi phục đúng hay sinh sai.
    """
    tu = row.get("table_uid")
    if tu and not _exists(con_old, "SELECT 1 FROM observations WHERE table_uid=? LIMIT 1", (tu,)):
        return "new_table"
    if _exists(con_old, "SELECT 1 FROM dropped_cells WHERE source_cell_uid=? LIMIT 1", (uid,)):
        return "previously_dropped_now_parsed"
    if _exists(con_old, "SELECT 1 FROM source_cells WHERE source_cell_uid=? LIMIT 1", (uid,)):
        return "source_cell_existed_not_emitted"
    return "unknown"


def _exists(con, sql: str, args: tuple) -> bool:
    try:
        return con.execute(sql, args).fetchone() is not None
    except sqlite3.Error:
        return False


def _removed_reason(uid: str, con_new) -> str:
    if _exists(con_new, "SELECT 1 FROM dropped_cells WHERE source_cell_uid=? LIMIT 1", (uid,)):
        return "now_dropped_with_reason"
    return "unknown"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("old"); ap.add_argument("new")
    ap.add_argument("-o", "--out", default="reports")
    ap.add_argument("--samples", type=int, default=10)
    ap.add_argument("--cases", default=None,
                    help="xuất TỪNG thay đổi ra CSV (Doc 52 §7 differential_cases.csv). "
                         "Đây là hàng trăm nghìn dòng — chỉ bật khi đóng gói bằng chứng.")
    a = ap.parse_args()
    co = sqlite3.connect(f"file:{a.old}?mode=ro", uri=True)
    cn = sqlite3.connect(f"file:{a.new}?mode=ro", uri=True)
    old, _ = _load(co)
    new, use = _load(cn)

    ko, kn = set(old), set(new)
    added, removed, common = kn - ko, ko - kn, ko & kn
    cmp_fields = [c for c in use if c not in
                  ("source_cell_uid", "observation_uid", "row_uid", "column_uid")]
    reasons: dict[str, int] = {}
    uid_unstable = 0
    n_unchanged = 0
    samples: dict[str, list] = {}
    # RC2-035 · "22.337 ca NEEDS_REVIEW" khong noi duoc gi cho nguoi doc: ho
    # khong biet DOI CAI GI. Mau 10 dong khong tra loi duoc cau "co bao nhieu
    # kieu thay doi khac nhau trong lop nay". Hai bo dem duoi day tra loi:
    #   field_change_histogram   moi truong bi doi bao nhieu lan (toan bo)
    #   changed_field_signatures chu ky (bo truong cung doi) theo tung lop
    # Day la BAO CAO, khong dong toi phan quyet.
    field_hist: dict[str, int] = {}
    signatures: dict[str, dict[str, int]] = {}
    cases_f = cases_w = None
    if a.cases:
        Path(a.cases).parent.mkdir(parents=True, exist_ok=True)
        cases_f = open(a.cases, "w", newline="", encoding="utf-8")
        cases_w = csv.writer(cases_f)
        # Khoá join là `source_cell_uid` — DANH TÍNH VẬT LÝ, đúng như Doc 52
        # §6.4 đòi. KHÔNG dùng row_path/label làm identity.
        cases_w.writerow(["source_cell_uid", "old_observation_uid",
                          "new_observation_uid", "reason", "fields_changed",
                          "old_values_json", "new_values_json"])
    for k in common:
        o, n = old[k], new[k]
        # Bất biến quan trọng nhất: cùng ô nguồn thì cùng row_uid/column_uid.
        # Vi phạm nghĩa là công thức UID đã đổi -> BREAKING, không phải patch.
        if o.get("row_uid") != n.get("row_uid") or \
           o.get("column_uid") != n.get("column_uid"):
            uid_unstable += 1
        diff = [f for f in cmp_fields if o.get(f) != n.get(f)]
        if not diff:
            n_unchanged += 1
            continue
        r = _reason(o, n, cmp_fields)
        reasons[r] = reasons.get(r, 0) + 1
        for f in diff:
            field_hist[f] = field_hist.get(f, 0) + 1
        sig = " + ".join(sorted(diff))
        signatures.setdefault(r, {})
        signatures[r][sig] = signatures[r].get(sig, 0) + 1
        if cases_w is not None:
            cases_w.writerow([k, o.get("observation_uid"), n.get("observation_uid"),
                              r, sig,
                              json.dumps({f: o.get(f) for f in diff}, ensure_ascii=False),
                              json.dumps({f: n.get(f) for f in diff}, ensure_ascii=False)])
        if len(samples.setdefault(r, [])) < a.samples:
            samples[r].append({
                "source_cell_uid": k, "fields_changed": diff,
                "old": {f: o.get(f) for f in diff},
                "new": {f: n.get(f) for f in diff}})

    if cases_w is not None:
        for k in sorted(removed):
            cases_w.writerow([k, old[k].get("observation_uid"), None,
                              "removed", "", json.dumps(
                                  {f: old[k].get(f) for f in ("value_kind", "unit_kind",
                                   "value_decimal_text")}, ensure_ascii=False), ""])
        for k in sorted(added):
            cases_w.writerow([k, None, new[k].get("observation_uid"),
                              "added", "", "", json.dumps(
                                  {f: new[k].get(f) for f in ("value_kind", "unit_kind",
                                   "value_decimal_text")}, ensure_ascii=False)])
        cases_f.close()

    # B0-03 mục 2 · MỌI added/removed phải có lớp lý do.
    added_reasons: dict[str, int] = {}
    for k in added:
        r = _added_reason(k, new[k], co, cn)
        added_reasons[r] = added_reasons.get(r, 0) + 1
    removed_reasons: dict[str, int] = {}
    for k in removed:
        r = _removed_reason(k, cn)
        removed_reasons[r] = removed_reasons.get(r, 0) + 1

    # Ô thêm/mất cũng phải có lý do. `dropped_cells` của build MỚI giải thích
    # được phần mất; phần còn lại là unexplained.
    rm_explained = 0
    if removed:
        try:
            q = ",".join("?" * min(len(removed), 900))
            for chunk in [list(removed)[i:i + 900] for i in range(0, len(removed), 900)]:
                rm_explained += cn.execute(
                    f"SELECT COUNT(*) FROM dropped_cells WHERE source_cell_uid IN "
                    f"({','.join('?' * len(chunk))})", chunk).fetchone()[0]
        except sqlite3.Error:
            pass

    rep = {
        # RC2-047 · `build_id` cap cao nhat = build DANG DUOC KIEM (ban moi).
        # RC-20 doi chieu truong nay; thieu no thi phep kiem im lang.
        "build_id": _meta(cn).get("build_id"),
        "old_build": _meta(co).get("build_id"), "new_build": _meta(cn).get("build_id"),
        "compared_by": "source_cell_uid (danh tính vật lý)",
        "counts": {"old": len(old), "new": len(new),
                   "added": len(added), "removed": len(removed),
                   "common": len(common)},
        "removed_explained_by_dropped_cells": rm_explained,
        "removed_unexplained": len(removed) - rm_explained,
        "uid_instability": uid_unstable,
        "changed_by_reason": reasons,
        "field_change_histogram": dict(sorted(field_hist.items(),
                                              key=lambda x: -x[1])),
        "changed_field_signatures": {
            r: dict(sorted(v.items(), key=lambda x: -x[1])[:20])
            for r, v in signatures.items()},
        "added_by_reason": added_reasons,
        "removed_by_reason": removed_reasons,
        "n_unchanged": n_unchanged,
        "compared_fields": cmp_fields,
        "unexplained_changed": reasons.get("unexplained", 0),
        "out_of_contract_field_changed": reasons.get("out_of_contract_field_changed", 0),
        "samples": samples,
    }
    # B0-03 · BA dang thuc phai dung dong thoi. Neu khong, con so
    # "unexplained = 0" khong chung minh duoc dieu gi.
    n_changed = len(common) - n_unchanged
    acc = {
        "changed": {"sum_of_reasons": sum(reasons.values()), "total": n_changed,
                    "reconciles": sum(reasons.values()) == n_changed},
        "added": {"sum_of_reasons": sum(added_reasons.values()), "total": len(added),
                  "reconciles": sum(added_reasons.values()) == len(added)},
        "removed": {"sum_of_reasons": sum(removed_reasons.values()),
                    "total": len(removed),
                    "reconciles": sum(removed_reasons.values()) == len(removed)},
    }
    acc["all_reconcile"] = all(v["reconciles"] for v in
                               (acc["changed"], acc["added"], acc["removed"]))
    rep["reason_accounting"] = acc
    blocking = {
        "measured_value_changed": reasons.get("measured_value_changed_BLOCKING", 0),
        "uid_instability": uid_unstable,
        "removed_unexplained": rep["removed_unexplained"],
        "unexplained_changed": reasons.get("unexplained", 0),
        "out_of_contract_field_changed": reasons.get("out_of_contract_field_changed", 0),
        "factual_changed_NEEDS_REVIEW": reasons.get("factual_changed_NEEDS_REVIEW", 0),
        "added_unknown_reason": added_reasons.get("unknown", 0),
        "removed_unknown_reason": removed_reasons.get("unknown", 0),
        "reason_accounting_broken": (not acc["all_reconcile"]),
    }
    rep["blocking_findings"] = {k: v for k, v in blocking.items() if v}
    rep["verdict"] = "FAIL" if rep["blocking_findings"] else "PASS"
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    f = out / "differential_audit.json"
    f.write_text(json.dumps(rep, ensure_ascii=False, indent=2), encoding="utf-8")

    p = print
    p(f"╔═══ DIFFERENTIAL AUDIT · {rep['old_build']} -> {rep['new_build']} ═══╗")
    p(f"  observation   cũ {len(old):,}  mới {len(new):,}"
      f"   +{len(added):,}  −{len(removed):,}")
    p(f"  UID không ổn định        {uid_unstable:>10,}   (ngưỡng 0 — khác 0 là BREAKING)")
    p(f"  mất KHÔNG giải thích     {rep['removed_unexplained']:>10,}   (ngưỡng 0)")
    for r, n in sorted(reasons.items(), key=lambda x: -x[1]):
        canh = ("  <-- PHẢI XEM" if r in ("unexplained", "factual_changed_NEEDS_REVIEW",
                                          "measured_value_changed_BLOCKING") else "")
        p(f"    {r:<32}{n:>10,}{canh}")
    # RC2-035 · in CHU KY thay doi, khong chi con so tong. Mot lop mang
    # 22.337 ca ma khong noi doi cai gi thi nguoi doc khong lam gi duoc voi no.
    for r in ("measured_value_changed_BLOCKING", "factual_changed_NEEDS_REVIEW",
              "out_of_contract_field_changed", "unexplained"):
        sigs = rep["changed_field_signatures"].get(r)
        if not sigs:
            continue
        p(f"  ── chu ky cua `{r}` ──")
        for sig, n in list(sigs.items())[:8]:
            p(f"    {n:>10,}  {sig}")
        con_lai = reasons.get(r, 0) - sum(list(sigs.values())[:8])
        if con_lai > 0:
            p(f"    {con_lai:>10,}  (cac chu ky con lai)")
    for grp in ("changed", "added", "removed"):
        g = rep["reason_accounting"][grp]
        p(f"  accounting {grp:<8} sum={g['sum_of_reasons']:>10,}"
          f"  total={g['total']:>10,}  khop={g['reconciles']}")
    for lbl, dd in (("added", added_reasons), ("removed", removed_reasons)):
        for r, n in sorted(dd.items(), key=lambda x: -x[1]):
            canh = "  <-- PHAI XEM" if r == "unknown" else ""
            p(f"    {lbl}:{r:<34}{n:>10,}{canh}")
    p(f"  VERDICT = {rep['verdict']}")
    if rep["blocking_findings"]:
        for k, v in rep["blocking_findings"].items():
            p(f"    ✗ {k} = {v}")
    p(f"  -> {f}")
    co.close(); cn.close()
    # exit 3 khi co phat hien chan; 0 khi sach.
    return 3 if rep["verdict"] == "FAIL" else 0


if __name__ == "__main__":
    sys.exit(main())
