"""P0-f · LOẠI cột phi giá trị trước khi chọn ô.

BẰNG CHỨNG
----------
162/1012 đáp án (16,0%) được lấy từ một cột **không chứa giá trị**: `Mã số`,
`Thuyết minh`, `TT`. Đó là số hiệu chỉ tiêu (100, 110, 300) hoặc số hiệu thuyết
minh (13.1, 20), không phải số tiền. Mọi câu ấy chắc chắn sai, không cần gold
cũng khẳng định được. Kiểm tay bắt tận tay:

    q492  "lưu chuyển tiền thuần ..."      -> 20.0      (mã số 20)
    q664  "tỷ lệ hao mòn TSCĐ hữu hình"    -> 221.0     (mã số 221)
    q235  "dự phòng rủi ro cho vay ..."    -> 13.1      (số hiệu thuyết minh)

Đây là bản GHI ĐÈ, không sửa `src/`. Nếu số liệu ủng hộ thì mới đề xuất đưa vào.
"""
from __future__ import annotations
import re, unicodedata

# `answer` KHÔNG được import ở tầng module: vị từ `la_cot_phi_gia_tri` phải
# kiểm được mà không cần cả pipeline. Import nằm trong `bat()`.

# `Mã số` / `Thuyết minh` / `TT` / `STT`. Cột `c0`, `c1` ... là nhãn tự sinh khi
# bảng không có tiêu đề — KHÔNG loại, vì ở nhiều bảng đó là cột giá trị thật.
_PHI_GIA_TRI = re.compile(r"(^|\s)(ma ?so|thuyet ?minh|stt|tt)(\s|$)")


def _fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower().strip()


def la_cot_phi_gia_tri(col_label: str) -> bool:
    t = _fold(col_label)
    if not t:
        return False
    # Nhãn cột của corpus này hay bị dính cả dữ liệu vào ("Mã số NGUỒN VỐN",
    # "Thuyết minh TÀI SẢN"). Chỉ xét PHẦN ĐẦU nhãn, và chỉ khi nhãn ngắn —
    # một nhãn dài kèm năm/đơn vị thì phần "Mã số" chỉ là rác dính vào.
    # Dấu hiệu "đây là cột giá trị" phải là dấu hiệu ĐƠN VỊ hoặc KỲ, không phải
    # bất kỳ chữ nào. Bản đầu nhận cả `dong` trần, nên nhãn "Mã số I. LƯU CHUYỂN
    # TIỀN TỪ HOẠT ĐỘNG KINH DOANH" (có "hoat dong") bị coi là cột giá trị và
    # thoát lọc — q492 vẫn trả về mã số 20. Xem docs/89 §5.
    if re.search(r"\d{4}|nam nay|nam truoc|so cuoi nam|so dau nam|31/12|01/01|"
                 r"\bvnd\b|(trieu|ty|nghin|tram ty)\s*(dong|vnd)", t):
        return False
    return bool(_PHI_GIA_TRI.search(t[:40]))


def to_long_format_loc(grid):
    rows = _GOC[0](grid)
    giu = [r for r in rows if not la_cot_phi_gia_tri(r.col_label)]
    # Không bao giờ làm bảng rỗng: nếu lọc hết thì trả nguyên bản và để
    # `_pick_cell` tự xoay xở — mất một ô đúng còn hơn mất cả bảng.
    return giu or rows


_GOC: list = []


def bat():
    """Cài bản ghi đè vào module `answer`."""
    from text2pandas.application.usecases import answer as A
    if not _GOC:
        _GOC.append(A.to_long_format)
    A.to_long_format = to_long_format_loc
