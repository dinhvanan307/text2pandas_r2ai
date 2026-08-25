"""B4 — Cổng phát hành SG và C0–C5 (doc 12 §7, doc 06 §8).

**Không viết lại G1–G5.** Chúng vẫn là chẩn đoán tốt và đã đo trên toàn corpus;
điều chúng thiếu là quyền quyết định phát hành, vì chúng đo tính nhất quán nội
tại của con số chứ không đo tính dùng được. Module này ánh xạ chúng thành
sub-metric của C0–C5 và bổ sung những thước C mà G không có.

Ba luật cứng của tầng này:

1. **Mọi cổng phải xuất hiện, kể cả khi `BLOCKED`.** Doc 12 §5.4: "không bỏ
   gate khỏi report chỉ vì chưa đo được". Một cổng vắng mặt đọc như một cổng
   đã qua.
2. **`BLOCKED` không bao giờ được quy đổi thành `pass`.** Đây là lỗi đã xảy ra
   một lần trong dự án: `NOT_MEASURABLE` từng được tính là đạt, và một build
   có G4 FAIL đã được publish.
3. **Mỗi thước mang `numerator`/`denominator`, không chỉ phần trăm.** Doc 12
   §11: "không chấp nhận báo cáo chỉ có phần trăm". Một tỷ lệ không có mẫu số
   thì không so được giữa hai build, và mẫu số là chỗ lỗi hay nấp nhất — E2
   trong `02_bronze_to_silver.md` báo 97,88% trong khi sự thật là 5,0% vì sai
   mẫu số, không sai ngưỡng.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass, field

__all__ = ["GATES_VERSION", "Metric", "Gate", "evaluate_gates",
           "legacy_check_status", "split_legacy_gates",
           "PASS", "FAIL", "BLOCKED"]

GATES_VERSION = "1.1"

PASS, FAIL, BLOCKED = "PASS", "FAIL", "BLOCKED"


@dataclass(slots=True)
class Metric:
    name: str
    numerator: int | None = None
    denominator: int | None = None
    value: float | None = None
    threshold: str = ""
    status: str = BLOCKED
    stratum: str = "all"
    evidence_path: str = ""
    blocking_reason: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(slots=True)
class Gate:
    gate: str
    title: str
    metrics: list[Metric] = field(default_factory=list)

    @property
    def status(self) -> str:
        """FAIL thắng BLOCKED, BLOCKED thắng PASS.

        Thứ tự này có chủ đích: một cổng có cả thước đạt lẫn thước chưa đo thì
        KHÔNG phải cổng đạt.
        """
        st = {m.status for m in self.metrics}
        if FAIL in st:
            return FAIL
        if BLOCKED in st:
            return BLOCKED
        return PASS

    def as_dict(self) -> dict:
        return {
            "gate": self.gate, "title": self.title, "status": self.status,
            "metrics": [m.as_dict() for m in self.metrics],
            "blocking_reasons": sorted(
                {m.blocking_reason for m in self.metrics if m.blocking_reason}),
        }


def _num(n: int, d: int, thr: float, name: str, *, higher_is_better: bool = True,
         thr_text: str = "", evidence: str = "") -> Metric:
    """Tỷ lệ có mẫu số. Mẫu số 0 là ĐẠT RỖNG, không phải thất bại.

    `0/0` cho `0.0%` rồi so với `≥ 100%` ra FAIL — một build sạch không có
    đụng độ nào sẽ bị báo hỏng. Đây là lớp lỗi chia-cho-không kinh điển và nó
    nguy hiểm ở đây vì nó FAIL đúng lúc dữ liệu tốt nhất.
    """
    if not d:
        return Metric(name, n, d, None, thr_text or f"≥ {thr}%", PASS,
                      evidence_path=evidence,
                      blocking_reason="mẫu số 0 — đạt rỗng, không có gì để đo")
    v = 100.0 * n / d
    ok = (v >= thr) if higher_is_better else (v <= thr)
    return Metric(name, n, d, round(v, 3), thr_text or f"≥ {thr}%",
                  PASS if ok else FAIL, evidence_path=evidence)


def _count(n: int, thr: int, name: str, evidence: str = "") -> Metric:
    return Metric(name, n, None, float(n), f"= {thr}",
                  PASS if n == thr else FAIL, evidence_path=evidence)


def _blocked(name: str, reason: str, threshold: str = "") -> Metric:
    return Metric(name, threshold=threshold, status=BLOCKED, blocking_reason=reason)


# ── cầu nối sang G1–G5 cũ ───────────────────────────────────────────────────
#
# `quality_report.json` chỉ có cờ nhị phân `pass`, nên "chưa đo được" và "đo
# rồi, hỏng" trông giống hệt nhau ở phía người đọc. Hai thứ đó KHÔNG cùng
# hạng: một cái là dữ liệu sai, một cái là thiếu dụng cụ đo. Gộp chúng lại
# thì cổng vừa chặn nhầm (RC không phát hành được vì thiếu Structure Gold),
# vừa có nguy cơ bị người vận hành tắt cả cụm cho xong việc — và lần sau một
# FAIL thật đi lọt cùng.
#
# Doc 12 §7: RC ĐƯỢC PHÉP có gate `BLOCKED` miễn khai rõ trong release notes;
# chỉ `FAIL` mới chặn. Hàm này là chỗ duy nhất phán định điều đó, để `publish`
# và `release` không tự diễn giải mỗi nơi một kiểu.

def legacy_check_status(check: dict) -> str:
    """PASS / BLOCKED / FAIL cho một check kiểu G1–G5 trong `quality_report`."""
    if check.get("pass"):
        return PASS
    if check.get("blocked") or str(check.get("value", "")).startswith("BLOCKED"):
        return BLOCKED
    return FAIL


def split_legacy_gates(gates: dict | None) -> tuple[list[str], list[str]]:
    """Tách (`failed`, `blocked`) từ khối `quality["gates"]`.

    `failed` chặn phát hành. `blocked` không chặn nhưng BẮT BUỘC được in ra và
    ghi vào manifest — một cổng chưa đo được mà im lặng thì đọc như đã qua.
    """
    failed, blocked = [], []
    for gate, checks in (gates or {}).items():
        for c in checks:
            st = legacy_check_status(c)
            if st is PASS:
                continue
            line = (f"{gate} · {c.get('name')} = {c.get('value')}"
                    f" (ngưỡng {c.get('threshold')})")
            (blocked if st is BLOCKED else failed).append(line)
    return failed, blocked


def _q(con, sql: str, default: int = 0) -> int:
    try:
        return con.execute(sql).fetchone()[0] or 0
    except sqlite3.Error:
        return default


def _has(con, name: str) -> bool:
    return bool(con.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE name=?", (name,)).fetchone()[0])


# ── các cổng ────────────────────────────────────────────────────────────────

def _gate_sg() -> Gate:
    g = Gate("SG", "Structure Gold đủ tin cậy để làm chuẩn")
    r = ("chưa có Structure Gold. Doc 12 §6.4 đòi overlap ≥90% agreement, mà "
         "overlap cần HAI người gán nhãn độc lập — một người không tự kiểm "
         "chéo được. Đây là bất khả thi theo định nghĩa, không phải chậm lịch.")
    for n, t in (("mandatory_field_completeness", "= 100%"),
                 ("source_anchor_validity", "= 100%"),
                 ("ambiguous_double_reviewed", "= 100%"),
                 ("overlap_exact_agreement", "≥ 90%")):
        g.metrics.append(_blocked(n, r, t))
    return g


def _gate_c0(con, meta: dict) -> Gate:
    g = Gate("C0", "Tái lập được")
    need = ("build_id", "schema_version", "source_hash", "config_hash")
    have = [k for k in need if meta.get(k)]
    g.metrics.append(Metric(
        "manifest_completeness", len(have), len(need),
        round(100 * len(have) / len(need), 3), "= 100%",
        PASS if len(have) == len(need) else FAIL,
        evidence_path="build_meta"))
    g.metrics.append(_blocked(
        "uid_stability_two_clean_rebuilds",
        "cần hai lần clean rebuild cùng input — chạy ở B6", "= 100%"))
    g.metrics.append(_blocked(
        "output_checksum_determinism", "cần hai lần build để so", "= 100%"))
    g.metrics.append(_blocked(
        "unexplained_count_delta", "cần differential audit (B5)", "= 0"))
    return g


def _gate_c1(con) -> Gate:
    g = Gate("C1", "Catalog · toàn vẹn vật lý · provenance")
    n_tab = _q(con, "SELECT COUNT(*) FROM table_features")
    g.metrics.append(_num(
        _q(con, "SELECT COUNT(*) FROM table_features WHERE parse_status IS NOT NULL"),
        n_tab, 100.0, "tables_with_parse_status", thr_text="= 100%"))
    g.metrics.append(_num(
        _q(con, "SELECT COUNT(*) FROM table_features WHERE parse_status='ok'"),
        n_tab, 95.0, "data_table_parse_success"))
    n_obs = _q(con, "SELECT COUNT(*) FROM observations")
    g.metrics.append(_num(
        _q(con, "SELECT COUNT(*) FROM observations WHERE source_cell_uid IS NOT NULL"
                " AND row_uid IS NOT NULL AND column_uid IS NOT NULL"
                " AND table_uid IS NOT NULL"),
        n_obs, 100.0, "observation_uid_coverage", thr_text="= 100%"))
    g.metrics.append(_count(
        _q(con, "SELECT COUNT(*) FROM (SELECT source_cell_uid FROM observations"
                " GROUP BY 1 HAVING COUNT(*)>1)"), 0, "span_replica_duplicate"))
    g.metrics.append(_count(
        _q(con, "SELECT COUNT(*) FROM observations o WHERE NOT EXISTS"
                " (SELECT 1 FROM source_cells sc"
                "  WHERE sc.source_cell_uid=o.source_cell_uid)"), 0, "orphan_fk"))
    if _has(con, "dropped_cells"):
        elig = _q(con, _ELIG_SQL)
        mapped = _q(con, _ELIG_SQL.replace("/*P*/", _MAPPED_P))
        excl = _q(con, _ELIG_SQL.replace("/*P*/", _EXCL_P))
        g.metrics.append(Metric(
            "unexplained_financial_drop_count", elig - mapped - excl, elig,
            float(elig - mapped - excl), "= 0",
            PASS if elig - mapped - excl == 0 else FAIL,
            evidence_path="dropped_cells"))
    else:
        g.metrics.append(_blocked("unexplained_financial_drop_count",
                                  "bảng dropped_cells chưa tồn tại", "= 0"))
    return g


_DIGITS = "".join(str(i) for i in range(10))
_DC = "sc.text_clean"
for _d in _DIGITS:
    _DC = f"REPLACE({_DC},'{_d}','')"
_ELIG_SQL = f"""
SELECT COUNT(DISTINCT sc.source_cell_uid)
FROM source_cells sc
JOIN grid_cells g ON g.source_cell_uid = sc.source_cell_uid AND g.is_span_anchor = 1
WHERE TRIM(sc.text_clean) <> ''
  AND (LENGTH(sc.text_clean) - LENGTH({_DC})) >= 4 /*P*/"""
_MAPPED_P = ("AND EXISTS (SELECT 1 FROM observations o"
             " WHERE o.source_cell_uid = sc.source_cell_uid)")
_EXCL_P = ("AND NOT EXISTS (SELECT 1 FROM observations o"
           " WHERE o.source_cell_uid = sc.source_cell_uid)"
           " AND EXISTS (SELECT 1 FROM dropped_cells d"
           "  WHERE d.source_cell_uid = sc.source_cell_uid)")


def _gate_c2(con, quality: dict) -> Gate:
    g = Gate("C2", "Số · đơn vị · kỳ")
    ar = (quality or {}).get("arithmetic") or {}
    if ar:
        ev, ok = ar.get("evaluated", 0), ar.get("passed", 0)
        g.metrics.append(_num(ok, ev, 97.0, "arithmetic_pass_tt200_scope",
                              evidence="quality.arithmetic"))
        g.metrics.append(Metric("arithmetic_checks", ev, None, float(ev),
                                "≥ 10000", PASS if ev >= 10_000 else FAIL))
        g.metrics.append(_count(ar.get("n_implausible_magnitude", 0), 0,
                                "implausible_final_magnitude"))
    else:
        for n in ("arithmetic_pass_tt200_scope", "arithmetic_checks",
                  "implausible_final_magnitude"):
            g.metrics.append(_blocked(n, "chưa chạy quality trên build này"))
    n_obs = _q(con, "SELECT COUNT(*) FROM observations")
    g.metrics.append(_num(
        _q(con, "SELECT COUNT(*) FROM observations WHERE value_source IS NOT NULL"),
        n_obs, 100.0, "provenance_coverage", thr_text="= 100%"))
    g.metrics.append(_count(
        _q(con, "SELECT COUNT(*) FROM observations WHERE"
                " (period_end IS NOT NULL AND date(period_end) IS NOT period_end)"),
        0, "invalid_iso_date"))
    n_money = _q(con, "SELECT COUNT(*) FROM observations WHERE value_kind='money'")
    g.metrics.append(_num(
        _q(con, "SELECT COUNT(*) FROM observations WHERE value_kind='money'"
                " AND unit_kind='money'"), n_money, 93.0,
        "unit_coverage_money_cells",
        thr_text="≥ 93% (trần đo được 95,21%)"))
    # Accuracy — khác COVERAGE. Doc 12 §7 C2: "không dùng coverage thay accuracy".
    for n in ("numeric_parse_exact_accuracy", "sign_accuracy",
              "unit_scale_accuracy", "period_resolution_accuracy"):
        g.metrics.append(_blocked(n, "accuracy chỉ đo được trên Structure Gold",
                                  "≥ 98%"))
    return g


def _gate_c3() -> Gate:
    g = Gate("C3", "Ngữ nghĩa cấu trúc")
    r = "cần Structure Gold v1 (300 bảng phân tầng)"
    for n, t in (("header_boundary_exact_accuracy", "≥ 98%"),
                 ("role_accuracy", "≥ 98%"),
                 ("column_path_group_exactness", "≥ 98%"),
                 ("row_parent_accuracy", "≥ 97%"),
                 ("row_path_exactness", "≥ 95%")):
        g.metrics.append(_blocked(n, r, t))
    return g


# P1-06 · C4 phai THI HANH DU hop dong.
#
# Hop dong `configs/rc2_contracts_v1.yaml` khai 10 bat bien C4-01..C4-10 (C4-10
# vao o RC2-036), nhung
# ban truoc chi do 4 metric — toan bo xoay quanh collision. Khong mot bat bien
# readiness-safety nao duoc thi hanh. Do la "hop dong khai ma ma khong thi
# hanh", cung loai khiem khuyet voi RC-02 hoi truoc.
#
# Moi muc duoi day map 1-1 vao mot `id` trong hop dong. Test hai chieu
# (tests/test_rc17_c4_day_du_hop_dong.py) bat buoc hai tap `id` phai BANG NHAU.
_C4_SQL = {
    "C4-01": ("SELECT COUNT(*) FROM observation_readiness"
              " WHERE execution_ready=1 AND execution_candidate=0",
              {"observation_readiness"}),
    "C4-02": ("SELECT COUNT(*) FROM observation_readiness"
              " WHERE execution_ready=1 AND confidence='low'",
              {"observation_readiness"}),
    "C4-03": ("SELECT COUNT(*) FROM observation_readiness"
              " WHERE execution_ready=1"
              " AND COALESCE(blocking_reasons_json,'[]') <> '[]'",
              {"observation_readiness"}),
    "C4-04": ("SELECT COUNT(*) FROM collision_obs co"
              " JOIN observation_readiness r USING(observation_uid)"
              " WHERE r.execution_ready=1 AND co.collision_class IS NOT NULL",
              {"collision_obs", "observation_readiness"}),
    "C4-05": ("SELECT COUNT(*) FROM observation_readiness"
              " WHERE execution_ready=1"
              " AND (blocking_reasons_json LIKE '%tiny_money_unresolved%'"
              "   OR warning_reasons_json  LIKE '%tiny_money_unresolved%')",
              {"observation_readiness"}),
    "C4-06": ("SELECT COUNT(*) FROM observation_readiness"
              " WHERE execution_ready=0 AND execution_candidate=1"
              " AND COALESCE(blocking_reasons_json,'[]') = '[]'",
              {"observation_readiness"}),
    "C4-08": ("SELECT COUNT(*) FROM observation_readiness"
              " WHERE COALESCE(policy_version,'') <> "
              "  (SELECT COALESCE(MAX(value),'') FROM build_meta"
              "    WHERE key='readiness_policy_version')",
              {"observation_readiness", "build_meta"}),
    "C4-09": ("SELECT COUNT(*) FROM collision_obs co"
              " JOIN observation_readiness r USING(observation_uid)"
              " WHERE r.execution_ready=1"
              "   AND co.collision_class IN ('unknown','physical_duplicate')",
              {"collision_obs", "observation_readiness"}),
    # RC2-036 · BẤT BIẾN NỘI TẠI. Một ô mang TIỀN không thể có đơn vị là lãi
    # suất, số ngày, số cổ phiếu hay số lượng.
    #
    # Bất biến này lẽ ra phải có từ đầu, và việc nó vắng mặt là lý do 20.378
    # bản ghi tự mâu thuẫn đi lọt qua toàn bộ chín cổng C4 trên bản dựng
    # `4c86c9e43915694a`. Cổng G4 ("ô TIỀN mang unit_kind = money") có đo,
    # nhưng nó là một TỶ LỆ có ngưỡng 93% — nó không thể phân biệt "chưa biết"
    # với "biết sai", nên 93,41% vẫn PASS trong khi RC1 đạt 94,11%.
    #
    # `unknown`/NULL KHÔNG vi phạm: "chưa xác định được đơn vị" là một trạng
    # thái hợp lệ và trung thực. Chỉ một loại đơn vị KHÁC mới là mâu thuẫn.
    "C4-10": ("SELECT COUNT(*) FROM observations"
              " WHERE value_kind='money'"
              "   AND unit_kind IS NOT NULL"
              "   AND unit_kind NOT IN ('money','unknown')",
              {"observations"}),
}


def _c4_taxonomy_unmapped(con) -> tuple[int, set]:
    """C4-07 · moi ma rui ro DANG PHAT RA phai map duoc vao taxonomy."""
    need = {"quality_issues"}
    try:
        emitted = {r[0] for r in con.execute(
            "SELECT DISTINCT rule_id FROM quality_issues") if r[0]}
    except sqlite3.Error:
        return -1, need
    try:
        import yaml
        from pathlib import Path as _P
        inv = yaml.safe_load(
            (_P(__file__).resolve().parents[2] / "configs" / "rule_inventory_v1.yaml")
            .read_text(encoding="utf-8"))
        declared = {r["id"] for r in inv["rules"]}
    except Exception:                                          # pragma: no cover
        return -1, need
    return len(emitted - declared), need


def _gate_c4(con) -> Gate:
    g = Gate("C4", "Quản trị mơ hồ và đụng độ")
    have = {r[0] for r in con.execute(
        "SELECT name FROM sqlite_master WHERE type IN ('table','view')")}
    for cid in sorted(_C4_SQL):
        sql, need = _C4_SQL[cid]
        missing = sorted(need - have)
        if missing:
            g.metrics.append(_blocked(
                cid, f"thiếu bảng: {', '.join(missing)}", "= 0"))
            continue
        g.metrics.append(_count(_q(con, sql), 0, cid, evidence=sql))
    n_unmapped, need = _c4_taxonomy_unmapped(con)
    if n_unmapped < 0:
        g.metrics.append(_blocked("C4-07", "không đọc được quality_issues/inventory", "= 0"))
    else:
        g.metrics.append(_count(n_unmapped, 0, "C4-07",
                                evidence="rule_id ∉ rule_inventory_v1"))
    # Giu lai cac metric collision cu — chung van co gia tri chan doan.
    if _has(con, "collision_groups"):
        tot = _q(con, "SELECT COUNT(*) FROM collision_groups")
        unk = _q(con, "SELECT COUNT(*) FROM collision_groups"
                      " WHERE collision_class='unknown'")
        g.metrics.append(_num(tot - unk, tot, 100.0, "collision_groups_classified",
                              thr_text="= 100%", evidence="collision_groups"))
        g.metrics.append(_count(
            _q(con, "SELECT COUNT(*) FROM collision_groups"
                    " WHERE collision_class='physical_duplicate'"),
            0, "physical_duplicate"))
    else:
        g.metrics.append(_blocked("collision_groups_classified",
                                  "classifier chưa chạy"))
    return g


def _gate_c5(replay: dict | None) -> Gate:
    g = Gate("C5", "Hợp đồng tiêu thụ và replay")
    if not replay:
        for n in ("long_dataframe_loads", "locator_join", "replay_acceptance"):
            g.metrics.append(_blocked(n, "chưa chạy bộ replay (B3)", "= 100%"))
        return g
    ev = "reports/replay_report.json"
    g.metrics.append(_num(replay.get("passed", 0), replay.get("total", 0),
                          100.0, "replay_acceptance_cases",
                          thr_text="= 100%", evidence=ev))
    g.metrics.append(_count(replay.get("failed", 0), 0, "replay_failed", ev))
    # Ca SKIP không phải PASS. Doc 12: `NOT_MEASURABLE` không được thành đạt.
    nskip = replay.get("skipped", 0)
    g.metrics.append(Metric(
        "replay_skipped", nskip, replay.get("total", 0), float(nskip), "= 0",
        PASS if nskip == 0 else BLOCKED, evidence_path=ev,
        blocking_reason="" if nskip == 0 else
        "ca bị bỏ qua vì dữ liệu mẫu không có hình dạng cần thiết — "
        "chưa chứng minh được hợp đồng ở những ca đó"))
    # B4 · DANH TÍNH từng ca phải còn nguyên.
    #
    # Bản trước đọc `c.get('case')` trong khi report ghi `case_id`, nên mười
    # metric cùng mang tên `replay::None`. Tổng 10/10 vẫn đúng, nhưng truy vết
    # "ca nào yếu" thì hỏng hoàn toàn — và một cổng mất khả năng truy vết chỉ
    # còn là một con số.
    cases = replay.get("cases", [])
    ids = [str(c.get("case_id") or c.get("case") or c.get("name") or "")
           for c in cases]
    thieu_id = sum(1 for i in ids if not i)
    g.metrics.append(_count(thieu_id, 0, "replay_case_missing_id", ev))
    g.metrics.append(_count(len(ids) - len(set(ids)), 0,
                            "replay_case_duplicate_id", ev))
    n_exp = replay.get("total", len(ids))
    g.metrics.append(Metric(
        "replay_case_id_count", len(set(ids)), n_exp, float(len(set(ids))),
        f"= {n_exp}", PASS if len(set(ids)) == n_exp else FAIL,
        evidence_path=ev,
        blocking_reason="" if len(set(ids)) == n_exp else
        f"{len(set(ids))} ID phân biệt trên {n_exp} ca — không truy vết được từng ca"))

    # Từng ca một, để người review thấy ca nào yếu chứ không chỉ thấy tổng.
    for c in replay.get("cases", []):
        st = {"PASS": PASS, "FAIL": FAIL}.get(c.get("status"), BLOCKED)
        g.metrics.append(Metric(
            f"replay::{c.get('case_id') or c.get('case') or c.get('name')}",
            status=st, threshold="PASS",
            evidence_path=ev,
            blocking_reason=c.get("reason", "") if st is BLOCKED else ""))
    return g


def evaluate_gates(silver_con, quality: dict | None = None,
                   replay: dict | None = None) -> dict:
    meta = {}
    if _has(silver_con, "build_meta"):
        meta = dict(silver_con.execute("SELECT key, value FROM build_meta"))
    gates = [
        _gate_sg(),
        _gate_c0(silver_con, meta),
        _gate_c1(silver_con),
        _gate_c2(silver_con, quality or {}),
        _gate_c3(),
        _gate_c4(silver_con),
        _gate_c5(replay),
    ]
    out = [g.as_dict() for g in gates]
    st = {g["status"] for g in out}
    # Nhãn phát hành suy ra từ cổng, KHÔNG do người đặt. Đây là chỗ một build
    # từng được publish với G4 FAIL vì nhãn và cổng là hai đường độc lập.
    if FAIL in st:
        label = "blocked"
    elif BLOCKED in st:
        # Doc 56 P0-05 · nhãn cũ là `silver-v1.0.0-rc1`. Con số ở đây nghĩa là
        # "release candidate thứ mấy của v1.0.0", nhưng nó trùng chữ với RC1
        # baseline `b927c3e8f90aed74`, và người nhận gói đọc `rc1` trên một
        # gói tên RC2 thì không có cách nào đoán đúng. Đổi theo đúng vòng phát
        # hành hiện tại.
        label = "silver-v1.0.0-rc2"
    else:
        label = "silver-v1.0.0-production"
    return {
        "gates_version": GATES_VERSION,
        "build_id": meta.get("build_id"),
        "schema_version": meta.get("schema_version"),
        "source_hash": meta.get("source_hash"),
        "config_hash": meta.get("config_hash"),
        "release_label": label,
        "summary": {g["gate"]: g["status"] for g in out},
        "gates": out,
    }
