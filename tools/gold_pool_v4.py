"""POOL GOLD v4 · hạn ngạch theo LOẠI BÁO CÁO mà câu hỏi thực sự cần.

VÌ SAO v4 — `PER_CELL_MIN = 2` là nút thắt đã đo được
-----------------------------------------------------
`docs/82` §4: **44/55 câu UNCERTAIN** quy về đúng một nguyên nhân. Ô
`(mã, năm)` có tồn tại, đúng mã đúng năm, nhưng thiếu **loại báo cáo** cần để
trả lời. Câu sàng lọc điển hình cần 2–4 loại cho MỖI ô (BCKQKD + BCĐKT, hoặc
thêm BCLCTT), trong khi v3 chỉ cấp 2 ứng viên/ô theo một thứ tự ưu tiên duy
nhất. Hai suất đó rơi vào loại nào là chuyện may rủi.

v4 bỏ hằng số ấy. Hạn ngạch của một ô = `cơ_bản + Σ (hạn ngạch của từng nhu
cầu mà câu hỏi phát sinh)`.

HAI QUYẾT ĐỊNH CẦN NÓI RÕ
-------------------------
1. **`balance_sheet` được tách làm HAI nhu cầu**, không phải một.
   Trong A6, bảng cân đối kế toán thường bị cắt thành hai thẻ: nửa TÀI SẢN và
   nửa NGUỒN VỐN — và nửa còn lại nhiều khi mang `statement_type='note'` chứ
   không phải `'balance_sheet'`. Ba câu screen trong `docs/82` (q470, q376,
   q457) chết đúng vì lý do này: pool có nửa tài sản, thiếu nửa nguồn vốn, nên
   không tính nổi một tỷ số thanh khoản nào. Nếu chỉ đòi
   `statement_type == 'balance_sheet'` thì v4 sẽ lặp lại y hệt lỗi của v3.
   Vì vậy nhu cầu được nhận diện bằng **vai trò của nội dung** (nhãn dòng),
   không chỉ bằng nhãn `statement_type`.
2. **Nhu cầu suy từ CÂU HỎI, không suy từ đáp án.** Bộ mẫu ở `_NHU_CAU` rút từ
   chính 44 câu trong `docs/82` §3, và chỉ đọc chữ trong câu hỏi. Không có
   bước nào nhìn vào nhãn đã gán, thứ hạng S2, hay proxy_gold.

GIỮ NGUYÊN MỌI GUARDRAIL CỦA v3
-------------------------------
· S2 nạp **sau cùng** và bị chặn trần `S2_SHARE_MAX` — trần tính trên số ứng
  viên độc lập, nên pool to ra thì trần cũng to ra theo đúng tỷ lệ cũ.
· Phần bù cho đủ `POOL_MIN` **không bao giờ** lấy từ S2.
· `sources` chỉ để thống kê; `sheet` vẫn không in nguồn/điểm/thứ hạng.
· Chọn trong ô bằng tín hiệu độc lập (`like`/`code`/`stmt`/`period`), không
  bằng điểm BM25.
· Tất định: mọi phép chọn đều sắp thứ tự đầy đủ, kết thúc bằng `table_uid`.

MỘT ĐIỂM KHÁC v3 CẦN GHI: HẠT GIỐNG TỪ NHÃN ĐÃ GÁN
--------------------------------------------------
65 nhãn của `docs/82` trỏ tới 152 `table_uid` **được chọn từ pool v3**. Nếu v4
đổi hạn ngạch rồi đánh rơi một trong số đó thì lớp kiểm "gold nằm trong pool"
sẽ đỏ và 65 nhãn hợp lệ bỗng thành không hợp lệ — một hồi quy do công cụ gây
ra, không phải do dữ liệu. Nên v4 **gieo sẵn** đúng 152 uid ấy với nguồn
`gan_v3`. Đây là tính liên tục, không phải thiên lệch: chúng đã được một người
phân xử bằng bằng chứng, và chúng không đến từ S2 của lượt dựng này.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import gold_tay as g3                                     # noqa: E402
from retrieval.alias_store import load_aliases            # noqa: E402
from retrieval.evalkit.cli import _load_cfg               # noqa: E402
from retrieval.evalkit.goldset import ProxyGoldV2         # noqa: E402
from retrieval.evalkit.stages import (Bm25StructuralRanker,  # noqa: E402
                                      HardFilterGenerator)
from retrieval.metric_hint import metric_codes_hint, statement_hint  # noqa: E402
from retrieval.query_terms import content_terms, drop_terms  # noqa: E402
from retrieval.question_intent import parse_intent        # noqa: E402

DEV = ROOT / "data/dev"
MAU = DEV / "gold_tay_sample_v2.jsonl"
POOL_V3 = DEV / "gold_tay_pool_v3.jsonl"
POOL_V4 = DEV / "gold_tay_pool_v4.jsonl"
NHAN = DEV / "gold_v1.jsonl"

PER_CELL_BASE = 2      # suất chung mỗi ô — dành cho chỉ tiêu nằm ở thuyết minh
PER_NEED = 2           # suất riêng cho MỖI nhu cầu loại báo cáo, mỗi ô
POOL_MIN = g3.POOL_MIN
S2_SHARE_MAX = g3.S2_SHARE_MAX


def _bo_dau(s: str) -> str:
    """Bỏ dấu, hạ chữ thường, nén khoảng trắng thừa — nhưng GIỮ khoảng trắng.

    Khác `ascii_compact` của S0, vốn xoá sạch mọi ký tự không alnum. Ở đây phải
    giữ, vì mọi mẫu trong `_NHU_CAU` là CỤM TỪ: `no ngan han` không được khớp
    vào "nợ ngân hàng". Giữ khoảng trắng là điều kiện CẦN chứ chưa đủ — muốn
    đủ còn phải neo biên từ, xem `docs/83` §2.
    """
    d = unicodedata.normalize("NFD", s)
    d = "".join(c for c in d if unicodedata.category(c) != "Mn")
    d = d.replace("đ", "d").replace("Đ", "D").lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%/ ]", " ", d)).strip()


# ═════════════════════════════════════════════════════════════════════════════
# nhu cầu loại báo cáo
# ═════════════════════════════════════════════════════════════════════════════
#
# Mỗi mục: tên nhu cầu · mẫu nhận diện trong CÂU HỎI · mẫu nhận diện trong
# NHÃN DÒNG của bảng · các `statement_type` tự nó đã thoả nhu cầu.
#
# Mẫu câu hỏi cố ý HẸP. Ví dụ nhu cầu dòng tiền không dùng `hoat dong kinh
# doanh` — cụm ấy nằm trong "lợi nhuận thuần từ hoạt động kinh doanh" của
# BCKQKD, và dùng nó sẽ phát sinh nhu cầu BCLCTT cho gần như mọi câu.
_NHU_CAU: tuple[tuple[str, tuple[str, ...], tuple[str, ...], tuple[str, ...]], ...] = (
    # Mẫu NGÂN HÀNG nằm chung ở đây, không tách thành nhu cầu riêng: BCKQKD của
    # tổ chức tín dụng là cùng một loại báo cáo, chỉ khác bộ chỉ tiêu. Bỏ chúng
    # ra khỏi mẫu là lý do lượt dựng đầu vẫn hụt `MBB/2020:income_statement`
    # (q671) — A6 gán bảng ấy nhãn `note`, và nó không có dòng "doanh thu thuần"
    # nào để nhận ra bằng bộ mẫu doanh nghiệp phi tài chính.
    ("income_statement",
     ("doanh thu thuan", "doanh thu ban hang", "tong doanh thu", "loi nhuan gop",
      "bien loi nhuan", "bien lai", "gia von", "loi nhuan sau thue", "lnst",
      "loi nhuan truoc thue", "loi nhuan rong", "loi nhuan thuan",
      "chi phi ban hang", "chi phi quan ly", "lai co ban tren co phieu", "eps",
      "tang truong doanh thu", "roe", "roa", "ty suat sinh loi",
      "doanh thu hoat dong tai chinh", "lai thuan", "thu nhap lai thuan"),
     ("doanh thu thuan", "loi nhuan gop", "gia von hang ban",
      "gia von hang ban va dich vu cung cap", "doanh thu hoat dong tai chinh",
      "thu nhap lai thuan", "tong loi nhuan truoc thue",
      "loi nhuan thuan tu hoat dong kinh doanh truoc chi phi du phong rui ro"),
     ("income_statement",)),

    ("balance_sheet_tai_san",
     ("tai san ngan han", "tong tai san", "hang ton kho", "tai san co dinh",
      "thanh toan hien hanh", "thanh toan nhanh", "vong quay tong tai san",
      "vong quay tai san", "so ngay ton kho", "roa", "tsc d", "tscd",
      "tien va cac khoan tuong duong tien", "co cau tai san", "tai san dai han"),
     ("tai san ngan han", "tong cong tai san", "tai san dai han",
      "hang ton kho", "tai san co dinh huu hinh"),
     ()),

    # `vay …` và `vốn cổ phần` cũng là chỉ tiêu nửa NGUỒN VỐN. Thiếu chúng ở
    # lượt đầu nên q500 ("số dư vay ngân hàng tại 31/12") và q328 ("số dư vốn
    # cổ phần") không phát sinh nhu cầu nào — xem `docs/83` §3.
    ("balance_sheet_nguon_von",
     ("no ngan han", "no phai tra", "von chu so huu", "roe", "he so no",
      "no tren von", "don bay", "thanh toan hien hanh", "thanh toan nhanh",
      "co cau von", "vcsh", "vay ngan hang", "vay ngan han", "vay dai han",
      "du no vay", "vay va no thue tai chinh", "von co phan",
      "von gop cua chu so huu"),
     ("no phai tra", "no ngan han", "von chu so huu", "tong cong nguon von",
      "vay ngan han", "vay dai han", "vay va no thue tai chinh ngan han",
      "von gop cua chu so huu", "von co phan"),
     ()),

    ("cash_flow",
     ("cfo", "luu chuyen tien", "dong tien thuan", "dong tien hoat dong",
      "dong tien tu hoat dong", "dong tien kinh doanh", "capex",
      "dau tu von", "tien thuan tu hoat dong"),
     ("luu chuyen tien thuan tu hoat dong kinh doanh",
      "luu chuyen tien thuan (su dung vao)/tu hoat dong kinh doanh"),
     ("cash_flow",)),
)


def _co_cum(text: str, mau: tuple[str, ...]) -> bool:
    """Có cụm nào xuất hiện như một CỤM TỪ TRỌN VẸN không — neo biên từ.

    Neo biên là bắt buộc, không phải chải chuốt. Chính việc thiếu nó ở
    `parse_intent` đã sinh ra hai ca `→ ABB` của `docs/82` (`an binh` khớp vào
    `tan binh`). Bản đầu của hàm này dùng `m in text` và lập tức mắc đúng lỗi
    ấy ở quy mô nhỏ hơn: `no ngan han` khớp vào `no ngan hang`, làm mọi câu
    nhắc "nợ ngân hàng" phát sinh nhu cầu nửa nguồn vốn. Test bắt được.
    """
    return any(re.search(rf"(?<![a-z0-9]){re.escape(m)}(?![a-z0-9])", text)
               for m in mau)


def nhu_cau_cua(question: str) -> list[str]:
    """Các loại báo cáo mà CÂU HỎI đòi hỏi. Rỗng nghĩa là không suy được.

    Rỗng KHÔNG phải lỗi: rất nhiều câu T1/T2 hỏi một chỉ tiêu chỉ có trong một
    thuyết minh chuyên đề ("chi phí mua khí từ các chủ mỏ"), và với chúng suất
    chung `PER_CELL_BASE` cộng thứ tự ưu tiên `like` đã là cách chọn đúng.
    """
    q = _bo_dau(question)
    return [ten for ten, mau_q, _, _ in _NHU_CAU if _co_cum(q, mau_q)]


def _vai_tro(stmt: str | None, row_text: str) -> set[str]:
    """Nhu cầu mà một bảng CÓ THỂ đáp ứng, đọc từ nhãn dòng + `statement_type`."""
    return {ten for ten, _, mau_row, stmts in _NHU_CAU
            if (stmt in stmts) or _co_cum(row_text, mau_row)}


def _row_text(conn, uids: list[str]) -> dict[str, str]:
    """Toàn bộ `row_labels` (đã bỏ dấu sẵn trong A6) — để nhận vai trò.

    `g3._rows_of` chỉ trả `ROWS_SHOW = 3` nhãn cho phiếu; nhận vai trò bằng 3
    nhãn đầu là bỏ sót, vì dòng `no phai tra` nằm giữa bảng.
    """
    ra: dict[str, str] = {}
    for i in range(0, len(uids), 800):
        lot = uids[i:i + 800]
        ph = ",".join("?" * len(lot))
        for uid, rl in conn.execute(
                f"SELECT table_uid, row_labels FROM table_cards_fts "
                f"WHERE table_uid IN ({ph})", lot):
            ra[uid] = str(rl or "").lower()
    return ra


def _uu_tien(m: dict, co: dict, basis_can: str | None) -> tuple:
    """Thứ tự chọn trong ô. Giống v3, thêm PHẠM VI lên đầu khi câu hỏi nêu rõ.

    Một bảng đúng loại nhưng sai phạm vi thì không trả lời được câu "công ty
    mẹ …" — `docs/82` q965/q913 hỏng đúng kiểu đó. v3 không xét `basis` khi
    chọn nên hai suất của ô có thể rơi cả vào bản hợp nhất.
    """
    hop_basis = 0 if (basis_can is None or m["basis"] == basis_can) else 1
    return (hop_basis,
            0 if co["like"] else 1,
            0 if co["code"] else 1,
            0 if co["stmt"] else 1,
            0 if co["period"] else 1,
            -m["ready_obs"],
            m["table_uid"])


def build_pool_v4(conn, qid: int, question: str, intent, s2_uids: list[str],
                  proxy_uids: list[str], s1_uids: frozenset[str],
                  alias: dict, hat_giong: set[str]) -> dict:
    terms = content_terms(question, drop=drop_terms(intent.targets, alias))
    codes = metric_codes_hint(question)
    stmt_goi = statement_hint(question)
    ends = {f"{y}-12-31" for y in intent.years}
    basis_can = intent.basis if intent.explicit_scope else None

    uids = sorted(s1_uids)
    meta = g3._meta_of(conn, uids)
    like = g3._like_hits(conn, uids, terms)
    rtext = _row_text(conn, uids)

    co: dict[str, dict] = {}
    vai: dict[str, set[str]] = {}
    for u, m in meta.items():
        co[u] = {
            "like": u in like,
            "code": bool(codes) and bool(
                {c for c in m["metric_codes"].split(",") if c} & set(codes)),
            "stmt": bool(stmt_goi) and m["statement_type"] == stmt_goi,
            "period": bool(ends) and any(e in m["periods"] for e in ends),
        }
        vai[u] = _vai_tro(m["statement_type"], rtext.get(u, ""))

    needs = nhu_cau_cua(question)
    cells = g3._cells_of(intent, meta)

    theo_o: dict[tuple, list[str]] = defaultdict(list)
    for u, m in meta.items():
        theo_o[(m["ticker"], m["doc_year"])].append(u)

    chon: dict[str, list[str]] = {}
    thieu_o: list[str] = []
    thieu_nhu_cau: list[str] = []

    def _lay(ung: list[str], n: int, loc=None) -> list[str]:
        pool = [u for u in ung if loc is None or loc(u)]
        pool.sort(key=lambda u: _uu_tien(meta[u], co[u], basis_can))
        return pool[:n]

    def _ghi(u: str, extra: str | None = None) -> None:
        ng = [k for k in ("like", "code", "stmt", "period") if co[u][k]] or ["meta"]
        if extra:
            ng.append(extra)
        chon.setdefault(u, []).extend(ng)

    for tk, yr in cells:
        ung = ([u for (t, y), us in theo_o.items() if t == tk for u in us]
               if yr is None else list(theo_o.get((tk, yr), [])))
        if not ung:
            thieu_o.append(f"{tk}/{yr}")
            continue
        for u in _lay(ung, PER_CELL_BASE):
            _ghi(u)
        for need in needs:
            got = _lay(ung, PER_NEED, lambda u: need in vai[u])
            if not got:
                # Ô này KHÔNG có bảng nào đóng được vai trò ấy trong toàn bộ
                # tập S1 — mở rộng hạn ngạch cũng vô ích. Đây là thiếu hụt của
                # CORPUS (hoặc của S1), phải khai báo chứ không được im.
                thieu_nhu_cau.append(f"{tk}/{yr}:{need}")
                continue
            for u in got:
                _ghi(u, f"need:{need}")

    if len(chon) < POOL_MIN:
        con_lai = sorted((u for u in meta if u not in chon),
                         key=lambda u: _uu_tien(meta[u], co[u], basis_can))
        for u in con_lai[:POOL_MIN - len(chon)]:
            _ghi(u)

    for u in sorted(hat_giong & set(meta)):
        chon.setdefault(u, []).append("gan_v3")

    for u in proxy_uids[:max(2, (PER_CELL_BASE + PER_NEED * len(needs)) // 2)]:
        if u in meta:
            chon.setdefault(u, []).append("proxy")

    doc_lap = len(chon)
    tran_s2 = int(doc_lap * S2_SHARE_MAX / (1 - S2_SHARE_MAX))
    them = 0
    for u in s2_uids:
        if them >= tran_s2:
            break
        if u in meta and u not in chon:
            chon[u] = ["s2"]
            them += 1
        elif u in chon:
            chon[u].append("s2")

    ds = sorted(chon, key=lambda u: (meta[u]["ticker"] or "",
                                     meta[u]["doc_year"] or 0,
                                     meta[u]["basis"] or "",
                                     meta[u]["statement_type"] or "", u))
    nhan_dong = g3._rows_of(conn, ds, terms)
    ung_vien = []
    for u in ds:
        m = dict(meta[u])
        m["row_labels"] = nhan_dong.get(u, [])
        m["sources"] = sorted(set(chon[u]))
        m["roles"] = sorted(vai[u])
        ung_vien.append(m)
    return {
        "id": qid, "question": question, "mode": intent.mode,
        "targets": list(intent.targets), "years": list(intent.years),
        "explicit_scope": intent.explicit_scope,
        "terms": terms[:12], "codes": sorted(codes),
        "n_s1": len(s1_uids), "cells": [f"{t}/{y}" for t, y in cells],
        "cells_missing": thieu_o,
        "needs": needs, "needs_missing": thieu_nhu_cau,
        "quota_per_cell": PER_CELL_BASE + PER_NEED * len(needs),
        "candidates": ung_vien,
    }


def _hat_giong() -> set[str]:
    """`table_uid` đã được gán làm gold ở `docs/82` — phải còn trong pool v4."""
    if not NHAN.is_file():
        return set()
    ra: set[str] = set()
    for line in NHAN.open(encoding="utf-8"):
        if line.strip():
            ra.update(json.loads(line).get("gold_table_uids", []))
    return ra


def cmd_pool_v4(db: Path, tu: int, den: int) -> int:
    mau = [json.loads(l) for l in MAU.open(encoding="utf-8") if l.strip()]
    cfg = _load_cfg("base", {})
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    conn.execute("PRAGMA cache_size=-200000")
    alias = load_aliases(brands=cfg.brands)
    s1 = HardFilterGenerator(basis_mode=cfg.basis_mode, year_slack=cfg.year_slack)
    s2 = Bm25StructuralRanker(alias, top_k=cfg.top_k_rank, use_hints=cfg.use_hints,
                              basis_mode=cfg.basis_mode, stop_mode=cfg.stop_mode)
    proxy = ProxyGoldV2(raw_limit=cfg.gold_raw_limit,
                        max_trusted=cfg.gold_max_trusted, alias=alias,
                        max_tier=cfg.gold_max_tier)
    seed = _hat_giong()
    cu = {}
    if POOL_V4.is_file():
        for line in POOL_V4.open(encoding="utf-8"):
            if line.strip():
                r = json.loads(line)
                cu[r["id"]] = r
    n = 0
    for r in mau[tu - 1:den]:
        qid, q = r["id"], r["question"]
        it = parse_intent(q, alias)
        o1 = s1.generate(conn, q, it)
        o2 = s2.rank(conn, q, it, o1)
        gg = proxy.gold_for(conn, qid, q, frozenset(it.targets) or it.tickers,
                            it.years, it.explicit_scope)
        cu[qid] = build_pool_v4(conn, qid, q, it, [x.table_uid for x in o2.ranked],
                                sorted(gg.tables), o1.uids, alias, seed)
        n += 1
        POOL_V4.write_text("".join(json.dumps(cu[k], ensure_ascii=False) + "\n"
                                   for k in sorted(cu)), encoding="utf-8")
    print(f"dựng pool v4 cho {n} câu · tổng {len(cu)} câu trong "
          f"{POOL_V4.relative_to(ROOT)}")
    return 0


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="gold_pool_v4")
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--tu", type=int, default=1)
    p.add_argument("--den", type=int, default=10**9)
    a = p.parse_args(argv)
    return cmd_pool_v4(a.db, a.tu, a.den)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
