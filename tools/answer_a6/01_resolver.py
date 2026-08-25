"""S4-A6 · FACT RESOLVER — A6 là NGUỒN CHÍNH cho evidence/cell resolution.

KIẾN TRÚC (thay cho đường cũ, không phải thêm nhánh song song):

    cũ:  Question → Retrieval → HTML gốc → parse_table_html → to_long_format
         → token matching (nhãn dòng + NĂM trong chuỗi cột) → answer
    mới: Question → Retrieval P0G2 (FREEZE) → relevant_tables → A6 Fact Resolver
         → Evidence → pandas_query → answer          [HTML chỉ là FALLBACK]

VÌ SAO: A6 đã chuẩn hoá sẵn `row_path_text`, `col_path_text`, `period_end`,
`period_source`, `value_kind`, `unit_kind`, `currency`, `scale_exponent`,
`collision_class`, `source_cell_uid` và một chính sách `execution_ready` có
`blocking_reasons`. Đường cũ vứt hết và suy diễn lại KỲ + ĐƠN VỊ từ chuỗi ký tự.

RANH GIỚI CÒN TOKEN MATCHING (khai báo thẳng, không giấu):
    * KỲ, ĐƠN VỊ, SCALE, CURRENCY: **không** suy diễn — lấy trường A6. (Yêu cầu 6)
    * NHÃN DÒNG: vẫn phải khớp văn bản, vì câu hỏi là văn bản tự do. A6 không
      có ánh xạ "câu hỏi → metric". Khác biệt: khớp trên `row_path_text` đã được
      A6 làm sạch/dựng phân cấp, không phải chuỗi OCR thô.

BẤT BIẾN:
    * `relevant_tables` / `relevant_docs` lấy NGUYÊN XI từ P0G2 — Retrieval FREEZE.
    * `answer == eval(pandas_query)` — kiểm ngay trong tool, câu nào vỡ thì hạ
      xuống FALLBACK chứ không nộp.
    * Không sửa A6, không sửa `src/**`, không dựng fact store mới.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from text2pandas.domain.rules.question import CompanyIndex, parse_question   # noqa: E402
from text2pandas.infrastructure.retrieval.index import tokenize              # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
from execution.a6_identity import A6IdentityError, kiem_dinh_danh            # noqa: E402

WORK = ROOT / "artifacts/retrieval/work.db"
CARD = ROOT / "data/silver/card_index.sqlite"
PHAN_XU = ROOT / "artifacts/execution/h0/unit_conflict_adjudication.jsonl"
SUBG = ROOT / "data/submissions/submission_P0G2.zip"
V4 = ROOT / "data/dev/answer_v3/records_v4.jsonl"          # đường HTML — FALLBACK
RA = ROOT / "data/dev/answer_a6"
DATA = RA / "data"
GHI = RA / "records_a6.jsonl"
LOG = RA / "resolve_log.jsonl"

# ưu tiên vai trò kỳ khi còn nhiều ứng viên cùng nhãn + cùng năm
UU_TIEN_ROLE = {"current": 0, "closing": 1, "prior": 2, "opening": 3, "unknown": 4}


def nap_phan_xu() -> tuple[dict, dict, set]:
    """B3 · nạp kết quả phân xử `unit_evidence_conflict`.

    `KEEP_A6_FLAGGED` đã bị loại bỏ: một record đã bị chặn thì KHÔNG được đi
    tiếp qua release path. Ở đây chỉ còn hai hành vi — sửa scale, hoặc chặn.
    """
    sua, chan, xac_nhan = {}, {}, set()
    if not PHAN_XU.is_file():
        return sua, chan, xac_nhan
    for line in PHAN_XU.open(encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        u, st = r["observation_uid"], r["final_status"]
        if st == "A6_DEFECT" and r.get("final_scale_exponent") is not None:
            sua[u] = (int(r["final_scale_exponent"]), r["decision_reason"])
        elif st in ("UNRESOLVED_BLOCKED", "FALLBACK_REQUIRED"):
            chan[u] = (st, r["decision_reason"])
        elif st == "CONFIRMED_A6":
            xac_nhan.add(u)                  # raw evidence xác nhận A6 ⇒ hết UNCERTAIN
    return sua, chan, xac_nhan


SUA_SCALE, CHAN_OBS, XAC_NHAN_A6 = nap_phan_xu()


def _f(x) -> float:
    """`confidence` lưu dạng TEXT trong A6 — ép an toàn, thiếu thì 0."""
    try:
        return float(x)
    except Exception:
        return 0.0


def _q(x: str) -> str:
    return x.replace("'", "\\'")


def diem_nhan(qt: set[str], nhan: str) -> float:
    lt = set(tokenize(nhan or ""))
    if not lt:
        return 0.0
    return len(qt & lt) / (len(lt) ** 0.5)


def vnd(dec_text: str, scale) -> Decimal | None:
    """Giá trị thật = value_decimal_text × 10^scale_exponent (đã kiểm hướng)."""
    try:
        return Decimal(dec_text) * (Decimal(10) ** int(scale or 0))
    except Exception:
        return None


class Resolver:
    COT = ("o.observation_uid, o.source_cell_uid, o.row_path_text, o.metric_label_clean,"
           " o.metric_code, o.col_path_text, o.grid_row_idx, o.grid_col_idx, o.period_end,"
           " o.period_role, o.period_source, o.value_decimal_text, o.value_source_raw,"
           " o.value_kind, o.unit_kind, o.currency, o.scale_exponent, o.scale_source,"
           " o.collision_class, o.confidence, o.table_uid, o.evidence_ref")

    def __init__(self, conn: sqlite3.Connection):
        self.c = conn

    def obs(self, uids: list[str], chi_ready: bool):
        if not uids:
            return []
        ph = ",".join("?" * len(uids))
        sql = (f"SELECT {self.COT}, r.execution_ready, r.blocking_reasons_json"
               f" FROM observations o JOIN observation_readiness r USING(observation_uid)"
               f" WHERE o.table_uid IN ({ph})")
        if chi_ready:
            sql += " AND r.execution_ready = 1"
        cols = [x.strip().split(".")[-1] for x in self.COT.split(",")] + ["execution_ready", "blocking"]
        return [dict(zip(cols, r)) for r in self.c.execute(sql, uids)]

    def giai(self, slots, uids: list[str]) -> tuple[dict | None, dict]:
        """Trả (observation đã chọn, nhật ký lý do)."""
        ghi = {"n_uid": len(uids)}
        hang = {u: i for i, u in enumerate(uids)}   # thu tu Retrieval, KHONG doi hop dong
        pool = self.obs(uids, chi_ready=True)
        ghi["n_ready"] = len(pool)
        if not pool:
            ghi["ly_do"] = "khong_co_observation_ready"
            return None, ghi

        # ── 1 · KỲ: lấy thẳng period_end của A6, KHÔNG dò năm trong chuỗi cột ──
        if slots.years:
            nam = {str(y) for y in slots.years}
            dich = str(max(slots.years))
            uu = [o for o in pool if (o["period_end"] or "")[:4] == dich]
            pool = uu or [o for o in pool if (o["period_end"] or "")[:4] in nam] or pool
            ghi["loc_ky"] = "khop_nam_dich" if uu else ("khop_nam_bat_ky" if pool else "khong")

        # ── 2 · LOẠI GIÁ TRỊ: dùng value_kind của A6 ─────────────────────────
        muon = "percentage" if slots.wants_percent else "money"
        hop = [o for o in pool if o["value_kind"] == muon]
        pool = hop or pool
        ghi["loc_kind"] = muon if hop else "khong_loc"

        # ── 3 · NHÃN DÒNG: chỗ DUY NHẤT còn khớp văn bản ─────────────────────
        qt = set(tokenize(slots.text))
        cham = []
        for o in pool:
            s = diem_nhan(qt, o["row_path_text"] or o["metric_label_clean"])
            if s > 0:
                cham.append((s, o))
        if not cham:
            ghi["ly_do"] = "khong_khop_nhan_dong"
            return None, ghi
        top = max(s for s, _ in cham)
        dong = [o for s, o in cham if s >= top - 1e-9]
        ghi["diem_nhan"] = round(top, 4)
        ghi["n_dong_bang_diem"] = len(dong)

        # ── 4 · VA CHẠM: phân giải bằng period_role rồi col_path ─────────────
        gt = {str(vnd(o["value_decimal_text"], o["scale_exponent"])) for o in dong}
        ghi["collision_class"] = sorted({str(o["collision_class"]) for o in dong})
        ghi["n_gia_tri"] = len(gt)

        # Thứ tự phá hoà — TOÀN BỘ bằng tín hiệu A6 + thứ hạng Retrieval đã FREEZE,
        # KHÔNG suy diễn lại kỳ/đơn vị từ chuỗi:
        #   1. vai trò kỳ (current > closing > prior > opening)
        #   2. thứ hạng bảng trong `relevant_tables` (đầu ra Retrieval, không đổi hợp đồng)
        #   3. confidence của A6
        #   4. cột trái hơn
        dong.sort(key=lambda o: (UU_TIEN_ROLE.get(o["period_role"] or "unknown", 9),
                                 hang.get(o["table_uid"], 99),
                                 -_f(o["confidence"]), o["grid_col_idx"] or 0))

        # CHỈ trả về FALLBACK khi chính A6 tuyên bố va chạm ngữ nghĩa và nó còn
        # sống sau khi phá hoà — tức ta thật sự không có căn cứ để chọn.
        # ── CỔNG B3: observation bị chặn thì KHÔNG được chọn ──────────────
        dong = [o for o in dong if o["observation_uid"] not in CHAN_OBS] or None
        if dong is None:
            ghi["ly_do"] = "don_vi_bi_chan_sau_phan_xu"
            return None, ghi

        cc = [o for o in dong if o["collision_class"]]
        if len(gt) > 1 and cc and len({str(vnd(o["value_decimal_text"], o["scale_exponent"])) for o in cc}) > 1:
            ghi["ly_do"] = "A6_bao_va_cham_khong_phan_giai_duoc"
            return None, ghi
        if len(gt) > 1:
            ghi["pha_hoa"] = "period_role+hang_retrieval+confidence"
            ghi["nhap_nhang"] = True
        return dong[0], ghi


_SO = __import__("re").compile(r"^\d+([.,]\d+)?$")


def _khong_thanh_so(nhan: str, pe: str | None) -> str:
    """pandas ĐOÁN KIỂU khi đọc CSV: cột toàn '2018' thành int64, và khi ấy
    `df['col_label'] == '2018'` (chuỗi) luôn False ⇒ bất biến vỡ ngầm.
    Neo thêm kỳ để nhãn không bao giờ là số thuần. (Bắt được ở q339.)"""
    return f"{nhan} ({pe or 'ky'})" if _SO.match(nhan.strip()) else nhan


def bang_dai(c: sqlite3.Connection, uid: str) -> tuple[list[tuple], dict]:
    """CSV evidence dựng THẲNG từ A6 — không parse lại HTML.

    `value` xuất theo VND thật (đã nhân 10^scale) ⇒ câu lệnh pandas chỉ còn một
    phép chia theo đơn vị câu hỏi. Đây là điểm giết lớp lỗi 10^3/10^12: không
    còn "đơn vị mức bảng" nào để đoán sai.

    Trả thêm `khoa[observation_uid] = (row_path, col_label)` — BẮT BUỘC, vì
    `.values[0]` chỉ nhìn dòng khớp ĐẦU TIÊN. Nếu hai ô khác giá trị lại rơi vào
    cùng một khoá, ta nới khoá cột (` #k`) để câu lệnh trỏ đúng ô đã chọn.
    Không có bước này thì bất biến `answer == eval(query)` vỡ ngầm.
    """
    ra: list[tuple] = []
    khoa: dict[str, tuple[str, str]] = {}
    dat: dict[tuple[str, str], str] = {}
    for ouid, rp, ml, cp, pe, vr, vd_, sc in c.execute(
            "SELECT observation_uid, row_path_text, metric_label_clean, col_path_text,"
            " period_end, value_source_raw, value_decimal_text, scale_exponent"
            " FROM observations WHERE table_uid=? ORDER BY grid_row_idx, grid_col_idx", (uid,)):
        rpath = rp or ml or ""
        if not rpath:
            continue
        if ouid in SUA_SCALE:
            sc = SUA_SCALE[ouid][0]          # scale đã phân xử từ raw evidence
        v = vnd(vd_, sc)
        if v is None:
            continue
        vs = format(v, "f")
        clab0 = _khong_thanh_so((cp or "").strip() or f"period:{pe or '?'}", pe)
        rpath = _khong_thanh_so(rpath, pe)
        clab, k = clab0, 0
        while dat.get((rpath, clab), vs) != vs:      # trùng khoá nhưng KHÁC giá trị
            k += 1
            clab = f"{clab0} #{k}"
        if (rpath, clab) not in dat:
            dat[(rpath, clab)] = vs
            ra.append((rpath, ml or rpath, clab, vr or "", vs))
        khoa[ouid] = (rpath, clab)
    return ra, khoa


def main(argv):
    tu, den = (int(argv[0]), int(argv[1])) if len(argv) >= 2 else (1, 10 ** 9)
    import zipfile
    zin = zipfile.ZipFile(SUBG)
    P0G2 = {r["id"]: r for r in json.loads(zin.read("submission.json"))}
    HTML = {}
    if V4.is_file():
        for l in V4.open(encoding="utf-8"):
            if l.strip():
                r = json.loads(l)
                HTML[r["qid"]] = r

    # ── B4 · CỔNG ĐỊNH DANH: dừng TRƯỚC câu đầu tiên nếu sai build ────────
    print("[A6-IDENTITY]")
    try:
        kiem_dinh_danh(WORK, in_log=lambda m: print(m))
    except A6IdentityError as e:
        print(f"FAIL-FAST: {e}", file=sys.stderr)
        return 2

    c = sqlite3.connect(f"file:{WORK}?mode=ro", uri=True)
    # đơn vị khai ở MỨC BẢNG — dùng làm ĐỐI CHỨNG cho scale của A6, không dùng
    # để ghi đè. Hai nguồn mâu thuẫn thì ta KHÔNG được tự phong ai đúng.
    cd = sqlite3.connect(f"file:{CARD}?mode=ro", uri=True)
    UEXP = {f"{d}|{ln}": ue for d, ln, ue in
            cd.execute("SELECT doc_id, line_no, unit_exponent FROM card_meta")}
    ev2uid, uid2doc = {}, {}
    for u, ev, doc in c.execute("SELECT table_uid, evidence_ref, doc_id FROM table_cards"
                                " WHERE evidence_ref IS NOT NULL"):
        ev2uid[ev.replace("|line:", "|")] = u
        uid2doc[u] = doc
    R = Resolver(c)

    qs = [json.loads(l) for l in (ROOT / "data/external/vifinqa/questions/questions.jsonl")
          .open(encoding="utf-8") if l.strip()]
    companies = CompanyIndex.from_csv(ROOT / "data/external/vifinqa/code_stock.csv")
    known = {r[0] for r in c.execute("SELECT DISTINCT ticker FROM documents WHERE ticker IS NOT NULL")}

    DATA.mkdir(parents=True, exist_ok=True)
    cu, lg = {}, {}
    for p, d in ((GHI, cu), (LOG, lg)):
        if p.is_file() and os.environ.get("RESET") != "1":
            for l in p.open(encoding="utf-8"):
                if l.strip():
                    r = json.loads(l)
                    d[r["qid"]] = r
    da_ghi = {r["csv_name"] for r in cu.values() if r.get("csv_name")}

    n = 0
    for q in qs[tu - 1:den]:
        qid = q["id"]
        if qid in cu:
            continue
        slots = parse_question(qid, q["question"], companies, known)
        locs = P0G2[qid].get("relevant_tables") or []
        uids = [ev2uid[x] for x in locs if x in ev2uid]
        o, ghi = R.giai(slots, uids)
        ghi.update({"qid": qid, "n_loc": len(locs)})

        if o is None:
            h = HTML.get(qid) or {}
            cu[qid] = {"qid": qid, "nguon": "FALLBACK_HTML",
                       "answer": h.get("answer"), "pandas_query": h.get("pandas_query", ""),
                       "evidence": h.get("evidence", []), "csv_name": h.get("csv_name", ""),
                       "confidence": h.get("confidence", 0.0), "provenance": None,
                       "notes": (h.get("notes") or []) + [f"A6 khong giai duoc: {ghi.get('ly_do')}"]}
            ghi["nguon"] = "FALLBACK_HTML"
            lg[qid] = ghi
            n += 1
            continue

        uid = o["table_uid"]
        doc = uid2doc[uid]
        line = (o["evidence_ref"] or "").rsplit("|line:", 1)[-1]
        # TIỀN TỐ `a6_` là BẮT BUỘC: CSV của A6 và của đường HTML có cùng lược đồ
        # nhưng KHÁC nội dung nhãn. Trùng tên file ⇒ câu lệnh nhiều-df của engine
        # số học trỏ vào CSV A6 và vỡ ngầm (đã dính 15 câu ở lần đóng gói đầu).
        csv_name = f"a6_{doc}_line{line}.csv"
        rows, khoa = bang_dai(c, uid)
        if csv_name not in da_ghi:
            import csv as _csv
            with (DATA / csv_name).open("w", encoding="utf-8", newline="") as fh:
                w = _csv.writer(fh)
                w.writerow(["row_path", "row_label", "col_label", "value_raw", "value"])
                w.writerows(rows)
            da_ghi.add(csv_name)

        if o["observation_uid"] not in khoa:
            # ô đã chọn không xuất được ra CSV ⇒ KHÔNG nộp đoán mò, hạ về HTML
            h = HTML.get(qid) or {}
            cu[qid] = {"qid": qid, "nguon": "FALLBACK_HTML", "answer": h.get("answer"),
                       "pandas_query": h.get("pandas_query", ""), "evidence": h.get("evidence", []),
                       "csv_name": h.get("csv_name", ""), "confidence": h.get("confidence", 0.0),
                       "provenance": None,
                       "notes": (h.get("notes") or []) + ["A6: o chon khong xuat duoc ra CSV"]}
            lg[qid] = {**ghi, "nguon": "FALLBACK_HTML", "ly_do": "o_chon_khong_xuat_duoc_csv"}
            n += 1
            continue
        # ── CỔNG SCALE: A6 vs đơn vị khai ở mức bảng ─────────────────────
        ue = UEXP.get((o["evidence_ref"] or "").replace("|line:", "|"))
        a6s = o["scale_exponent"]
        sua = SUA_SCALE.get(o["observation_uid"])
        if sua:
            a6s = sua[0]                      # A6_DEFECT đã sửa ⇒ hết xung đột
        la_tien = o["value_kind"] == "money"
        khong_chac = False
        # Đã phân xử từ raw evidence (sửa hoặc xác nhận) thì KHÔNG so lại với bộ
        # suy đơn vị mức bảng nữa — đó chính là thứ vừa bị bằng chứng out-rank.
        da_phan_xu = (o["observation_uid"] in XAC_NHAN_A6) or (o["observation_uid"] in SUA_SCALE)
        if (la_tien and ue is not None and ue != (a6s if a6s is not None else 0)
                and not da_phan_xu):
            if a6s is None or (o["scale_source"] or "none") == "none":
                # A6 KHÔNG có bằng chứng scale, bảng thì có khai ⇒ không đoán, hạ về HTML
                h = HTML.get(qid) or {}
                cu[qid] = {"qid": qid, "nguon": "FALLBACK_HTML", "answer": h.get("answer"),
                           "pandas_query": h.get("pandas_query", ""), "evidence": h.get("evidence", []),
                           "csv_name": h.get("csv_name", ""), "confidence": h.get("confidence", 0.0),
                           "provenance": None,
                           "notes": (h.get("notes") or []) + [f"A6 khong co bang chung scale (A6={a6s}, bang=10^{ue})"]}
                lg[qid] = {**ghi, "nguon": "FALLBACK_HTML", "ly_do": "scale_khong_co_bang_chung"}
                n += 1
                continue
            khong_chac = True          # A6 CÓ bằng chứng nhưng lệch bảng ⇒ UNCERTAIN

        rpath, clab = khoa[o["observation_uid"]]
        v = vnd(o["value_decimal_text"], a6s)
        want = slots.unit_exponent
        base = (f"df1[(df1['row_path'] == '{_q(rpath)}') & "
                f"(df1['col_label'] == '{_q(clab)}')]['value'].values[0]")
        if want:
            query = f"float({base}) / {10 ** want}"
            val = float(v / (Decimal(10) ** want))
        else:
            query = f"float({base})"
            val = float(v)

        cu[qid] = {
            "qid": qid, "nguon": "PRIMARY_A6", "answer": val, "pandas_query": query,
            "evidence": [{"variable": "df1", "csv_path": f"data/{csv_name}"}],
            "csv_name": csv_name, "confidence": _f(o["confidence"]),
            # ── PROVENANCE giữ xuyên suốt tới đáp án ──
            "provenance": {
                "observation_uid": o["observation_uid"], "source_cell_uid": o["source_cell_uid"],
                "table_uid": uid, "evidence_ref": o["evidence_ref"],
                "row_path": rpath, "metric_code": o["metric_code"], "col_path": o["col_path_text"],
                "period_end": o["period_end"], "period_role": o["period_role"],
                "period_source": o["period_source"], "value_kind": o["value_kind"],
                "unit_kind": o["unit_kind"], "currency": o["currency"],
                "scale_exponent": a6s, "scale_source": (f"ADJUDICATED({o['scale_source']})" if sua else o["scale_source"]),
                "collision_class": o["collision_class"], "value_vnd": format(v, "f"),
                "value_source_raw": o["value_source_raw"], "execution_ready": 1,
                "unit_adjudication": ("A6_DEFECT_FIXED" if sua else None),
                "unit_adjudication_reason": (sua[1] if sua else None),
                "nhap_nhang": bool(ghi.get("nhap_nhang")),
                "scale_bang_khai": ue,
                "scale_UNCERTAIN": khong_chac,
                "n_ung_vien_dong_diem": ghi.get("n_dong_bang_diem"),
            },
            "notes": [f"A6: scale 10^{o['scale_exponent']} tu {o['scale_source']}"
                      f" · ky {o['period_end']} tu {o['period_source']}"]
                     + ([f"UNCERTAIN scale: A6=10^{a6s} vs bang=10^{ue}"] if khong_chac else []),
        }
        lg[qid] = {**ghi, "nguon": "PRIMARY_A6", "table_uid": uid, "scale_UNCERTAIN": khong_chac,
                   "period_source": o["period_source"], "scale_source": o["scale_source"]}
        n += 1
        if n % 50 == 0:
            _ghi(cu, lg)
            print(f"  ..{n}", flush=True)
    _ghi(cu, lg)
    a6 = sum(1 for r in cu.values() if r["nguon"] == "PRIMARY_A6")
    print(f"tong {len(cu)}/1012 · PRIMARY_A6 {a6} · FALLBACK_HTML {len(cu)-a6}")
    return 0


def _ghi(cu, lg):
    GHI.parent.mkdir(parents=True, exist_ok=True)
    for p, d in ((GHI, cu), (LOG, lg)):
        with p.open("w", encoding="utf-8") as f:
            for k in sorted(d):
                f.write(json.dumps(d[k], ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
