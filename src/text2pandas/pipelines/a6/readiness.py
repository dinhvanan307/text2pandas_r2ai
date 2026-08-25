"""RC-02 · Readiness — MATERIALIZE, không rải logic trong SQL view.

Bản 1.0 sinh ra `v_execution_ready` bằng cách ghép biểu thức SQL từ chính sách.
Nó đúng về nguyên tắc "chính sách là dữ liệu", nhưng sai ở ba chỗ mà audit A-04
đã bắt được:

1. **Chỉ có MỘT mức.** Không phân biệt "không đủ field để tính" với "đủ field
   nhưng chưa đủ tin". Người tiêu thụ cần cả hai — cái đầu là giới hạn của dữ
   liệu, cái sau là quyết định quản trị.
2. **Không xét `confidence` và hard-risk flag.** Kết quả đo trên RC1: 181.160
   observation `confidence='low'` và 1.789 ca tiny-money chưa xác nhận vẫn nằm
   trong `execution_ready`. Chúng chạm 849 bảng / 651 tài liệu.
3. **Không nói được VÌ SAO một fact không ready.** View trả `0` và im lặng.
   Người nhận gói không debug được, và ta không kiểm được bất biến *"mọi fact
   not-ready đều có lý do"*.

Bản này materialize một bảng thật:

    observation_readiness
    ├── observation_uid
    ├── execution_candidate      đủ field để phép tính CHẠY
    ├── execution_ready          candidate + đủ AN TOÀN để tự động dùng
    ├── confidence               tính MỘT lần ở đây, không lặp lại ở release
    ├── blocking_reasons_json    vì sao KHÔNG ready — mảng, không phải cờ
    ├── warning_reasons_json     ready nhưng cần biết hệ quả
    └── policy_version

Materialize thay vì view vì ba lý do đo được: `NOT EXISTS quality_issues` trên
mỗi consumer query là quét lại 2,6 triệu dòng cho từng câu hỏi; lý do phải lưu
được thành mảng chứ không suy lại; và bảng thì join được, view lồng nhau thì
query planner mất dấu chỉ mục.

Sinh lại bảng này mất vài giây khi chính sách đổi — vẫn giữ nguyên tính chất
"sửa chính sách không phải rebuild Silver".
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

__all__ = ["ReadinessPolicy", "load_policy", "apply_policy", "build_readiness",
           "READINESS_VERSION", "READINESS_DDL", "CONFIDENCE_EXPR",
           "retired_rule_assertions", "retrieval_ready_expr", "PRECEDENCE"]

# Precedence là CHÍNH SÁCH, không phải thứ tự `if`. Đọc từ YAML; hằng số này
# chỉ là mặc định khi chính sách cũ không khai.
PRECEDENCE = ("NON_CANDIDATE", "BLOCKING", "WARNING", "PASS")

READINESS_VERSION = "2.1"

_SEARCH = (
    Path(__file__).resolve().parents[4] / "configs" / "readiness_policy_v1.yaml",
    Path(__file__).resolve().parents[4] / "config" / "readiness_policy_v1.yaml",
)

READINESS_DDL = """
CREATE TABLE IF NOT EXISTS observation_readiness (
    observation_uid      TEXT PRIMARY KEY,
    execution_candidate  INTEGER NOT NULL,
    execution_ready      INTEGER NOT NULL,
    confidence           TEXT    NOT NULL,
    blocking_reasons_json TEXT   NOT NULL,
    warning_reasons_json  TEXT   NOT NULL,
    -- v2.1 · APPEND-ONLY. Tách khỏi `blocking_reasons_json` vì precedence
    -- phân biệt hai thứ: thiếu field là NON_CANDIDATE (dữ liệu không đủ để
    -- tính), còn blocking là CANDIDATE nhưng chưa đủ an toàn. Gộp chung làm
    -- mất chính thông tin mà người tiêu thụ cần để quyết định.
    non_candidate_reasons_json TEXT NOT NULL DEFAULT '[]',
    policy_version       TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_rdy_ready ON observation_readiness(execution_ready);
CREATE INDEX IF NOT EXISTS ix_rdy_cand  ON observation_readiness(execution_candidate);
CREATE INDEX IF NOT EXISTS ix_rdy_conf  ON observation_readiness(confidence);
"""

# `confidence` định nghĩa ĐÚNG MỘT LẦN, ở đây. Trước đây nó nằm trong
# `release.py` dưới dạng `_CONFIDENCE_SQL`, nên Silver và gói phát hành có thể
# lệch nhau mà không ai biết — và readiness thì không thấy nó ở đâu cả.
CONFIDENCE_EXPR = """
CASE
  WHEN o.period_end IS NULL
    OR o.scale_source IN ('assumed','none')
    OR o.quality_flags_json LIKE '%unit_assumed%'
    OR o.quality_flags_json LIKE '%unit_scale_assumed_no_evidence%'
    OR o.quality_flags_json LIKE '%column_role_unknown%'
  THEN 'low'
  WHEN o.period_source <> 'column_path'
    OR o.quality_flags_json LIKE '%generic_row_label%'
    OR o.quality_flags_json LIKE '%table_not_classified_as_data%'
  THEN 'medium'
  ELSE 'high'
END
"""


class ReadinessPolicy:
    """Chính sách đã nạp. Không giữ trạng thái nào ngoài nội dung tệp."""

    __slots__ = ("raw", "policy_version", "path")

    def __init__(self, raw: dict, path: Path):
        self.raw = raw
        self.path = path
        self.policy_version = str(raw.get("policy_version", "?"))

    # ── đọc chính sách ──────────────────────────────────────────────────
    @property
    def confidence_allowed(self) -> tuple[str, ...]:
        return tuple((self.raw.get("execution_ready") or {}).get(
            "confidence_allowed", ["high", "medium"]))

    @property
    def blocking(self) -> tuple[tuple[str, str], ...]:
        """`(tên cờ, mã lý do)` — thứ tự giữ nguyên để báo cáo ổn định."""
        return tuple(
            (b["flag"], b.get("reason", b["flag"]))
            for b in (self.raw.get("execution_ready") or {}).get("blocking_flags", []))

    @property
    def warnings(self) -> tuple[tuple[str, str], ...]:
        return tuple(
            (w["flag"], w.get("rule_id", w["flag"]))
            for w in (self.raw.get("execution_ready") or {}).get("warning_flags", []))

    @property
    def conditional(self) -> tuple[dict, ...]:
        """Cờ xét THEO BẰNG CHỨNG — v2.1.

        v2.0 để `period_from_table` và `generic_row_label` là warning PHẲNG với
        một dòng `allowed_if` bằng văn xuôi mà không ai thi hành. Hệ quả đo
        được trên RC1: 377.406 + 94.071 fact được cho qua bất kể bằng chứng.
        """
        return tuple((self.raw.get("execution_ready") or {}).get("conditional_flags", []))

    @property
    def precedence(self) -> tuple[str, ...]:
        return tuple((self.raw.get("precedence") or {}).get("order", PRECEDENCE))

    def candidate_rules(self, resolve=None) -> tuple[tuple[str, str], ...]:
        """`(biểu thức SQL, mã lý do)` cho từng điều kiện candidate.

        `resolve(field) -> "alias.column"` để chính sách không phải biết field
        nằm ở bảng nào. `collision_class` là ví dụ: trong Silver nó ở
        `collision_obs`, trong gói phát hành nó đã được phi chuẩn hoá vào
        `observations`. Chính sách nói *ý nghĩa*, tầng này lo *chỗ*.
        """
        res = resolve or (lambda f: f"o.{f}")
        out = []
        for r in (self.raw.get("execution_candidate") or {}).get("require", []):
            f, op = res(r["field"]), r["op"]
            reason = r.get("reason", r["field"])
            if op == "is_null":
                out.append((f"{f} IS NULL", reason))
            elif op == "is_not_null":
                out.append((f"{f} IS NOT NULL", reason))
            elif op == "not_blank":
                out.append((f"TRIM(COALESCE({f},'')) <> ''", reason))
            elif op == "not_in":
                vals = ",".join(f"'{v}'" for v in r.get("values", []))
                out.append((f"COALESCE({f},'') NOT IN ({vals})", reason))
            else:                                            # pragma: no cover
                raise ValueError(f"toán tử readiness chưa hỗ trợ: {op!r}")
        return tuple(out)

    def confidence_expr(self) -> str:
        """Dựng biểu thức `confidence` TỪ CHÍNH SÁCH.

        Đây là chỗ `CONFIDENCE_EXPR` hằng số từng nằm. Chuyển sang chính sách
        vì một cờ có thể vừa chặn vừa hạ confidence — nếu hai thứ đó ở hai
        nơi thì nới một cái không nới được cái kia, và kế hoạch
        `planned_relaxations` trở thành lời hứa không thi hành được.
        """
        c = self.raw.get("confidence") or {}
        if not c:
            return CONFIDENCE_EXPR                    # tương thích ngược
        def branch(flags_key, cond_key):
            parts = [f"({e})" for e in c.get(cond_key, []) or []]
            parts += [f"({self.flag_pred(f)})" for f in c.get(flags_key, []) or []]
            return " OR ".join(parts)
        lo = branch("low_if_flags", "low_if_conditions")
        me = branch("medium_if_flags", "medium_if_conditions")
        out = ["CASE"]
        if lo:
            out.append(f"  WHEN {lo} THEN 'low'")
        if me:
            out.append(f"  WHEN {me} THEN 'medium'")
        out.append(f"  ELSE '{c.get('default', 'high')}' END")
        return "\n".join(out)

    @staticmethod
    def flag_pred(flag: str, alias: str = "o") -> str:
        """Cờ nằm trong mảng JSON. LIKE rẻ hơn `json_each` nhiều lần ở quy mô này,
        và dấu nháy kép hai bên chặn khớp nhầm cờ có tiền tố giống nhau."""
        return f"{alias}.quality_flags_json LIKE '%\"{flag}\"%'"


def load_policy(path: str | Path | None = None) -> ReadinessPolicy:
    if path:
        p = Path(path)
    else:
        p = next((c for c in _SEARCH if c.exists()), _SEARCH[0])
    text = p.read_text(encoding="utf-8")
    try:
        import yaml
        raw = yaml.safe_load(text)
    except ImportError:                                      # pragma: no cover
        raw = json.loads(text)
    if not isinstance(raw, dict) or "policy_version" not in raw:
        raise ValueError(f"chính sách readiness không hợp lệ: {p}")
    return ReadinessPolicy(raw, p)


def _has(conn, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE name=? AND type IN ('table','view')",
        (name,)).fetchone())


def build_readiness(conn, policy: ReadinessPolicy | None = None) -> dict:
    """Dựng lại `observation_readiness` từ đầu. Idempotent, không đụng observations."""
    pol = policy or load_policy()
    conn.executescript(READINESS_DDL)
    conn.execute("DELETE FROM observation_readiness")

    has_coll_tbl = _has(conn, "collision_obs")
    obs_cols = {d[1] for d in conn.execute("PRAGMA table_info(observations)")}

    def _resolve(field: str) -> str:
        # `collision_class` sống ở hai chỗ khác nhau tuỳ tầng. Giải ở đây thay
        # vì bắt chính sách biết cấu trúc lưu trữ.
        if field == "collision_class" and field not in obs_cols:
            return "co.collision_class" if has_coll_tbl else "NULL"
        return f"o.{field}"

    cand = pol.candidate_rules(_resolve)
    cand_sql = " AND ".join(f"({e})" for e, _ in cand) or "1"

    # Lý do bị loại ghi thành MẢNG, không phải một cờ. Bất biến "mọi fact
    # not-ready đều có lý do" chỉ kiểm được khi lý do là dữ liệu.
    def json_arr(pairs: tuple[tuple[str, str], ...], pred) -> str:
        if not pairs:
            return "'[]'"
        parts = [f"CASE WHEN {pred(flag)} THEN '\"{reason}\",' ELSE '' END"
                 for flag, reason in pairs]
        inner = " || ".join(parts)
        return (f"'[' || RTRIM({inner}, ',') || ']'")

    # Sort theo MÃ LÝ DO để mảng JSON ra đã có thứ tự ổn định ngay từ đầu.
    cand_reasons = json_arr(
        tuple(sorted(((e, r) for e, r in cand), key=lambda x: x[1])),
        lambda e: f"NOT ({e})")
    blk_reasons = json_arr(tuple(sorted(pol.blocking, key=lambda x: x[1])),
                           lambda f: ReadinessPolicy.flag_pred(f))
    warn_reasons = json_arr(tuple(sorted(pol.warnings, key=lambda x: x[1])),
                            lambda f: ReadinessPolicy.flag_pred(f))

    conf_low = "','".join(c for c in pol.confidence_allowed)
    coll_join = ("LEFT JOIN collision_obs co ON co.observation_uid = o.observation_uid"
                 if has_coll_tbl and "collision_class" not in obs_cols else "")

    conn.execute(f"""
        INSERT INTO observation_readiness
        SELECT o.observation_uid,
               CASE WHEN ({cand_sql}) THEN 1 ELSE 0 END,
               0,                                   -- điền ở bước 2
               {pol.confidence_expr()},
               {blk_reasons},
               {warn_reasons},
               {cand_reasons},
               '{pol.policy_version}'
        FROM observations o
        {coll_join}""")

    # ── Bước 1a · cờ CÓ ĐIỀU KIỆN (v2.1) ────────────────────────────────
    #
    # Chạy SAU bước 1 vì điều kiện tham chiếu `confidence`, mà cột đó vừa được
    # vật chất hoá xong. Viết gộp vào một biểu thức duy nhất sẽ phải nhân đôi
    # cả biểu thức confidence — hai bản sao của một định nghĩa là đúng thứ dự
    # án này đã trả giá ba lần.
    if any(cf.get("requires_col_path_discriminative") for cf in pol.conditional):
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS ix_obs_colpath_scope"
                         " ON observations(table_uid, row_uid, period_end,"
                         " col_path_text)")
        except sqlite3.OperationalError:
            pass
    if any(cf.get("requires_row_path_discriminative") for cf in pol.conditional):
        # Điều kiện phân biệt là một truy vấn TƯƠNG QUAN trên chính
        # `observations`. Không có chỉ mục này, mỗi dòng trong 2,6 triệu dòng
        # phải quét lại cả bảng — build sẽ không kết thúc trong ngày.
        # Bọc try: nguồn có thể mở chỉ-đọc trong một số đường gọi kiểm toán,
        # và thiếu chỉ mục làm CHẬM chứ không làm SAI.
        try:
            conn.execute("CREATE INDEX IF NOT EXISTS ix_obs_rowpath_scope"
                         " ON observations(table_uid, column_uid, row_path_text)")
        except sqlite3.OperationalError:
            pass

    for cf in pol.conditional:
        flag = cf["flag"]
        warn_r = cf.get("warning_reason", flag)
        block_r = cf.get("blocking_reason", f"{flag}_unverified")
        conds = list(cf.get("warning_if", []) or [])
        allowed = cf.get("confidence_allowed") or list(pol.confidence_allowed)
        conds.append("r.confidence IN ('%s')" % "','".join(allowed))
        if cf.get("requires_no_collision"):
            conds.append(f"({_resolve('collision_class')} IS NULL)")
        if cf.get("requires_col_path_discriminative"):
            # Đối xứng với điều kiện dòng ở dưới, đổi trục: nhãn CỘT phải phân
            # biệt được ô trong phạm vi (bảng, dòng, kỳ). Hai cột cùng nhãn,
            # cùng dòng, cùng kỳ nghĩa là khoá ngữ nghĩa
            # `(row_path, col_path, period)` trỏ tới ≥2 ô — chọn ô nào cũng là
            # tung đồng xu, và exact-match không cho điểm một nửa.
            conds.append("""NOT EXISTS (
                SELECT 1 FROM observations o3
                 WHERE o3.table_uid   = o.table_uid
                   AND o3.row_uid     = o.row_uid
                   AND o3.period_end  IS o.period_end
                   AND TRIM(COALESCE(o3.col_path_text,''))
                       = TRIM(COALESCE(o.col_path_text,''))
                   AND o3.column_uid <> o.column_uid)""")
        if cf.get("requires_row_path_discriminative"):
            # Hợp đồng P3 · generic_row_label: "row_path đủ PHÂN BIỆT trong
            # phạm vi (table_uid, column_uid)". Đây là điều kiện thứ ba mà
            # `collision_class` KHÔNG bắt được: collision là hai ô cùng
            # (bảng, dòng, cột); còn ở đây là hai DÒNG KHÁC NHAU mang cùng
            # `row_path_text` trong cùng một cột. Khi đó câu hỏi "lấy dòng
            # nào" không có đáp án duy nhất, nên nhãn chung KHÔNG được coi là
            # đã phân biệt — dù không hề có collision.
            conds.append("""NOT EXISTS (
                SELECT 1 FROM observations o2
                 WHERE o2.table_uid   = o.table_uid
                   AND o2.column_uid  = o.column_uid
                   AND TRIM(COALESCE(o2.row_path_text,''))
                       = TRIM(COALESCE(o.row_path_text,''))
                   AND o2.row_uid    <> o.row_uid)""")
        ok = " AND ".join(f"({c})" for c in conds)
        pred = ReadinessPolicy.flag_pred(flag)
        # Cờ có mặt VÀ đủ bằng chứng → warning. Có mặt mà thiếu → blocking.
        conn.execute(f"""
            UPDATE observation_readiness AS r
               SET warning_reasons_json =
                     CASE WHEN r.warning_reasons_json='[]' THEN '["{warn_r}"]'
                          ELSE RTRIM(r.warning_reasons_json,']')||',"{warn_r}"]' END
             WHERE EXISTS (SELECT 1 FROM observations o {coll_join}
                            WHERE o.observation_uid=r.observation_uid
                              AND {pred} AND {ok})""")
        conn.execute(f"""
            UPDATE observation_readiness AS r
               SET blocking_reasons_json =
                     CASE WHEN r.blocking_reasons_json='[]' THEN '["{block_r}"]'
                          ELSE RTRIM(r.blocking_reasons_json,']')||',"{block_r}"]' END
             WHERE EXISTS (SELECT 1 FROM observations o {coll_join}
                            WHERE o.observation_uid=r.observation_uid
                              AND {pred} AND NOT ({ok}))""")

    # Bước 1b · `confidence` thấp TỰ NÓ là một lý do chặn, và phải được ghi ra.
    #
    # Bỏ sót chỗ này làm thủng đúng bất biến quan trọng nhất của RC-17:
    # *"mọi observation not-ready đều có lý do"*. Một fact bị loại chỉ vì
    # confidence thấp sẽ có `blocking_reasons = []` — người nhận gói thấy nó
    # không ready mà không biết vì sao, và bộ kiểm bất biến báo vi phạm.
    conf_reason = ((pol.raw.get("execution_ready") or {})
                   .get("confidence_reason", "confidence_low"))
    conn.execute(f"""
        UPDATE observation_readiness
           SET blocking_reasons_json =
                 CASE WHEN blocking_reasons_json = '[]'
                      THEN '["{conf_reason}"]'
                      ELSE RTRIM(blocking_reasons_json, ']')
                           || ',"{conf_reason}"]' END
         WHERE confidence NOT IN ('{"','".join(pol.confidence_allowed)}')""")

    # ── Bước 1c · CHUẨN HOÁ mảng lý do: sort + khử trùng ────────────────
    #
    # Sau các bước nối chuỗi ở trên, thứ tự có thể lệch và một mã lý do có thể
    # xuất hiện hai lần. Hợp đồng P3 đòi "JSON array đã sort, không trùng" —
    # nếu không, so sánh differential ở RC-16 sẽ báo khác nhau giữa hai build
    # chỉ vì thứ tự phần tử.
    for col in ("blocking_reasons_json", "warning_reasons_json",
                "non_candidate_reasons_json"):
        conn.execute(f"""
            UPDATE observation_readiness
               SET {col} = COALESCE((
                     SELECT '[' || GROUP_CONCAT('"' || v || '"', ',') || ']'
                       FROM (SELECT DISTINCT value AS v
                               FROM json_each(observation_readiness.{col})
                              ORDER BY value)), '[]')
             WHERE {col} <> '[]'""")

    # Bước 2 · ready = candidate ∧ confidence cho phép ∧ không lý do chặn nào.
    # Tách hai bước có chủ đích: biểu thức một lượt sẽ dài tới mức không ai
    # đọc lại được, và bất biến `ready ⊆ candidate` phải nhìn thấy được.
    conn.execute(f"""
        UPDATE observation_readiness
           SET execution_ready = 1
         WHERE execution_candidate = 1
           AND confidence IN ('{conf_low}')
           AND blocking_reasons_json = '[]'""")
    conn.commit()

    q = lambda s: conn.execute(s).fetchone()[0]  # noqa: E731
    return {
        "readiness_version": READINESS_VERSION,
        "policy_version": pol.policy_version,
        "total": q("SELECT COUNT(*) FROM observation_readiness"),
        "execution_candidate": q("SELECT COUNT(*) FROM observation_readiness"
                                 " WHERE execution_candidate=1"),
        "execution_ready": q("SELECT COUNT(*) FROM observation_readiness"
                             " WHERE execution_ready=1"),
        "by_confidence": dict(conn.execute(
            "SELECT confidence, COUNT(*) FROM observation_readiness"
            " GROUP BY 1 ORDER BY 2 DESC").fetchall()),
        # Ba số dưới đây là BẤT BIẾN. Khác 0 nghĩa là chính sách không được
        # thi hành, và gói không được phát hành.
        "violation_low_confidence_in_ready": q(
            "SELECT COUNT(*) FROM observation_readiness"
            " WHERE execution_ready=1 AND confidence='low'"),
        "violation_blocking_in_ready": q(
            "SELECT COUNT(*) FROM observation_readiness"
            " WHERE execution_ready=1 AND blocking_reasons_json<>'[]'"),
        "violation_not_ready_without_reason": q(
            "SELECT COUNT(*) FROM observation_readiness"
            " WHERE execution_ready=0 AND blocking_reasons_json='[]'"
            "   AND non_candidate_reasons_json='[]'"),
        # v2.1 · bất biến cốt lõi của contract P3. `ready` mà không `candidate`
        # là mâu thuẫn logic: fact không đủ field mà vẫn được phép tính tự động.
        "violation_ready_not_candidate": q(
            "SELECT COUNT(*) FROM observation_readiness"
            " WHERE execution_ready=1 AND execution_candidate=0"),
        # C4-04 / C4-05 / C4-08 · đo TRỰC TIẾP thay vì suy ra từ C4-03.
        # Hai cờ này đã nằm trong `blocking_flags`, nên về lý thuyết C4-03 = 0
        # kéo theo chúng = 0. Nhưng cổng C4 phải kiểm được từng mệnh đề một:
        # khi C4-03 > 0 mà không tách ra thì không biết vi phạm thuộc loại nào,
        # và đó chính là lúc cần biết nhất.
        "violation_collision_in_ready": q(
            "SELECT COUNT(*) FROM observation_readiness"
            " WHERE execution_ready=1"
            "   AND blocking_reasons_json LIKE '%collision%'"),
        "violation_tiny_money_in_ready": q(
            "SELECT COUNT(*) FROM observation_readiness"
            " WHERE execution_ready=1"
            "   AND blocking_reasons_json LIKE '%tiny_money%'"),
        "violation_policy_version_mismatch": q(
            "SELECT COUNT(*) FROM observation_readiness"
            f" WHERE policy_version <> '{pol.policy_version}'"),
        "precedence": list(pol.precedence),
        "conditional_flags": [c["flag"] for c in pol.conditional],
        "by_blocking_reason": dict(conn.execute(
            "SELECT value, COUNT(*) FROM observation_readiness,"
            " json_each(blocking_reasons_json) GROUP BY 1 ORDER BY 2 DESC").fetchall()),
        # RET-01..03 · bằng chứng nghỉ hưu, chạy ở MỌI build (xem
        # `rc2_contracts_v1.yaml::retired_rules`). Ba số này thay cho một cờ
        # blocking chặn 0 ca.
        "retired_rule_assertions": retired_rule_assertions(conn),
        "by_non_candidate_reason": dict(conn.execute(
            "SELECT value, COUNT(*) FROM observation_readiness,"
            " json_each(non_candidate_reasons_json) GROUP BY 1 ORDER BY 2 DESC").fetchall()),
    }


# ── RC-08 · `retrieval_ready` — MỘT định nghĩa, một chỗ ────────────────────
#
# Trước RC-08 có HAI nơi tự định nghĩa nó:
#
#   readiness.py::v_retrieval_ready   locator ≠ '' ∧ evidence_ref ≠ ''
#   release.py::_build_cards          parse_status='ok' ∧ statement_type ≠ 'toc'
#
# Đo trên RC1: cả hai cùng cho 146.246/146.246. Nên nói cho đúng — chúng chưa
# MÂU THUẪN, chúng chỉ ĐỘC LẬP. Đó vẫn là khiếm khuyết cần sửa, nhưng là khiếm
# khuyết bảo trì chứ không phải một lỗi dữ liệu đang xảy ra: hai định nghĩa
# trùng nhau hôm nay sẽ lệch vào ngày một đầu vào đổi, và lúc đó không ai biết
# bên nào là bản chính.
#
# Định nghĩa hợp nhất giữ TRỌN cả hai ý, vì chúng nói về hai điều kiện khác
# nhau chứ không phải hai phiên bản của cùng một điều kiện:
#
#   địa chỉ hoá được  locator ∧ evidence_ref   — không có thì trích dẫn không nổi
#   tìm được nội dung parse ok ∧ ≠ 'toc'       — mục lục không phải dữ liệu
#
# ĐỘC LẬP với execution, đúng như `table_readiness_contract` khai. Một bảng có
# thể tìm được mà không ô nào đủ tin để tự động tính — hai trục khác nhau, và
# `must_end` của hợp đồng chính là việc người tiêu thụ không phân biệt được.
def retrieval_ready_expr(alias: str = "t") -> str:
    """Biểu thức SQL cho `retrieval_ready`. Gọi từ MỌI nơi cần nó."""
    a = alias
    return (f"CASE WHEN TRIM(COALESCE({a}.locator,'')) <> ''"
            f"      AND TRIM(COALESCE({a}.evidence_ref,'')) <> ''"
            f"      AND COALESCE({a}.parse_status,'') = 'ok'"
            f"      AND COALESCE({a}.statement_type,'') <> 'toc'"
            f"     THEN 1 ELSE 0 END")


def retired_rule_assertions(conn) -> dict:
    """RET-01..03 · bằng chứng cho việc `value_unit_period_conflict` nghỉ hưu.

    Nghỉ hưu một rule mà không để lại gì thì lần sau không ai biết vì sao nó
    biến mất, và người ta sẽ cài lại. Ba số dưới đây thay nó canh gác — và
    khác nó ở chỗ: chúng CHẠY.

    Cả ba phải bằng 0. Khác 0 nghĩa là giả định "đã bị thâu tóm" sai trên RC2,
    và rule thật sự cần được viết lại.
    """
    if not (_has(conn, "columns") and _has(conn, "observation_readiness")):
        return {"skipped": "thiếu `columns` hoặc `observation_readiness`"}
    J = ("FROM observations o"
         " JOIN columns k ON k.table_uid = o.table_uid"
         "               AND k.grid_col_idx = o.grid_col_idx")
    R = (" JOIN observation_readiness r"
         " ON r.observation_uid = o.observation_uid AND r.execution_ready = 1")
    q = lambda s: conn.execute(s).fetchone()[0]  # noqa: E731
    return {
        # Trục period: hai tầng thực ra là MỘT tầng (observation sao từ column),
        # nên bất kỳ số nào khác 0 đều nghĩa là giả định cấu trúc đã đổi.
        "RET-01_period": q(
            f"SELECT COUNT(*) {J} WHERE o.period_end IS NOT NULL"
            " AND k.period_end IS NOT NULL AND o.period_end <> k.period_end"),
        "RET-02_scale": q(
            f"SELECT COUNT(*) {J}{R} WHERE o.scale_exponent IS NOT NULL"
            " AND k.scale_exponent IS NOT NULL"
            " AND o.scale_exponent <> k.scale_exponent"),
        "RET-03_unit": q(
            f"SELECT COUNT(*) {J}{R} WHERE o.unit_kind <> 'unknown'"
            " AND k.unit_kind IS NOT NULL AND k.unit_kind <> 'unknown'"
            " AND o.unit_kind <> k.unit_kind"),
    }


def apply_policy(conn, policy: ReadinessPolicy | None = None) -> ReadinessPolicy:
    """Tương thích ngược: dựng bảng readiness rồi phủ view cũ lên trên nó."""
    pol = policy or load_policy()
    build_readiness(conn, pol)
    # `v_retrieval_ready` GIỮ NGUYÊN TÊN. Nó là hợp đồng cấp bảng mà Retrieval
    # đã dùng; bỏ nó đi là breaking change không nằm trong phạm vi RC2 (§1.3).
    # Nhưng ĐỊNH NGHĨA nay đọc từ `retrieval_ready_expr` — xem RC-08.
    conn.execute("DROP VIEW IF EXISTS v_retrieval_ready")
    conn.execute(f"""
        CREATE VIEW v_retrieval_ready AS
        SELECT t.table_uid, {retrieval_ready_expr('t')} AS retrieval_ready
        FROM table_features t""" if _has(conn, "table_features") else
        "CREATE VIEW v_retrieval_ready AS SELECT NULL AS table_uid,"
        " 0 AS retrieval_ready WHERE 0")
    conn.execute("DROP VIEW IF EXISTS v_execution_ready")
    conn.execute("""
        CREATE VIEW v_execution_ready AS
        SELECT observation_uid, execution_ready, execution_candidate,
               confidence, blocking_reasons_json, warning_reasons_json,
               non_candidate_reasons_json,
               CASE WHEN execution_candidate=1 AND execution_ready=0
                    THEN 1 ELSE 0 END AS review_required
        FROM observation_readiness""")
    if _has(conn, "build_meta"):
        conn.execute(
            "INSERT OR REPLACE INTO build_meta(key, value) VALUES (?, ?)",
            ("readiness_policy_version", pol.policy_version))
    conn.commit()
    return pol
