"""DP-006 — D3a Technical Cleaning: phép chiếu an toàn, có rule ID.

Hai ràng buộc tuyệt đối:
  DI-04  `text_source` không bao giờ bị ghi đè. `text_clean` là trường riêng.
  Idempotent: clean(clean(x)) == clean(x). Có test kiểm.

Chỉ luật SAFE nằm ở đây. Toàn bộ U1–U11 trong `DATA_CLEANING.md` §7 mặc định
tắt và không được cài đặt trong module này — sửa dấu OCR, tách chữ dính,
NFKC đều làm biến dạng nội dung.
"""

from __future__ import annotations

import html as _html
import re
import unicodedata
from dataclasses import dataclass

from data_pipeline.models import CleanStatus

__all__ = ["CleanResult", "clean_text", "CLEAN_RULES", "CLEANING_VERSION",
           "repair_mojibake", "repair_mojibake_trace"]

# 1.1 — thêm C07 (mojibake). Đây là luật DUY NHẤT trong module đụng vào chữ
# cái, nên nó cần một biện minh riêng, xem `repair_mojibake`.
CLEANING_VERSION = "1.1"

# Thực thể HTML HỢP LỆ đo được trong corpus. Chỉ giải mã đúng tập này —
# `html.unescape` toàn phần sẽ đụng tới `&IR;` `&2;` là lỗi OCR, không phải
# thực thể, và biến chúng thành thứ khác.
_VALID_ENTITIES = {
    "&quot;": '"', "&amp;": "&", "&lt;": "<", "&gt;": ">",
    "&apos;": "'", "&#x27;": "'", "&#39;": "'", "&nbsp;": " ",
}
_ENTITY_ANY = re.compile(r"&[#a-zA-Z0-9]{1,8};")
_IMG = re.compile(r"<img[^>]*>", re.I)
_WS = re.compile(r"[ \t  -   　]+")

CLEAN_RULES = {
    "C01": "chuẩn hoá NFC",
    "C02": "giải mã thực thể HTML hợp lệ",
    "C03": "gộp khoảng trắng nội ô",
    "C04": "cắt khoảng trắng đầu/cuối",
    "C05": "gỡ blob <img> base64",
    "C06": "gỡ ký tự điều khiển C0/C1",
    "C07": "khôi phục mojibake (UTF-8 bị đọc nhầm là CP1252)",
}

_CTRL = {chr(c) for c in list(range(0, 9)) + [11, 12] + list(range(14, 32))
         + list(range(0x7F, 0xA0))}

# ── C07 · mojibake ──────────────────────────────────────────────────────────
#
# RC-07. Vì sao luật này được phép nằm cạnh các luật SAFE trong khi U1–U11
# (sửa dấu OCR) thì không: sửa dấu OCR là ĐOÁN — `Mã sơ` có thể là `Mã số`
# hoặc không, và không có phép kiểm nào phân xử. Mojibake thì có: nó là một
# phép biến đổi byte XÁC ĐỊNH bị áp nhầm, và phép nghịch của nó **chứng minh
# được** — nếu `s.encode('cp1252').decode('utf-8')` chạy trót lọt thì chuỗi
# gốc đúng là ảnh của một chuỗi UTF-8 qua bảng CP1252. Không trót lọt thì
# không sửa gì.
#
# Chữ ký gồm hai phần, và phần nào cũng chưa đủ một mình:
#
#   LEAD  ảnh CP1252 của byte DẪN UTF-8 (0xC2–0xF4) → U+00C2–U+00F4.
#         Tiếng Việt cần cả dải này: `đ`/`ơ`/`ư` là chuỗi 2 byte (0xC3/0xC4/
#         0xC6 → `Ã`/`Ä`/`Æ`) còn `ề`/`ạ`/`ệ` là 3 byte mở đầu 0xE1 → `á`.
#         Bản đầu chỉ liệt kê `ÂÃÄÅ` nên bỏ sót toàn bộ nhóm 3 byte — tức là
#         gần hết dấu tiếng Việt.
#   CONT  ảnh CP1252 của byte TIẾP NỐI (0x80–0xBF) → U+0080–U+00BF, cộng các
#         mã mà CP1252 ánh xạ đi chỗ khác (`€`, `'`, `"`, `–`, …).
_LEAD = "Â-ô"
_CONT = ("-¿"
         "€‚ƒ„…†‡ˆ‰Š‹"
         "ŒŽ‘’“”•–—˜™"
         "š›œžŸ")
_MOJIBAKE = re.compile(f"[{_LEAD}][{_CONT}]")
_SUSPICIOUS = re.compile(f"[{_LEAD}{_CONT}]")

# CỬA SỔ ỨNG VIÊN — đây là thay đổi cốt lõi của RC-07.
#
# Bản trước áp phép đảo cho TOÀN BỘ chuỗi. Ca thật của RC1 là chuỗi HỖN HỢP:
#
#     "7 J1001 C TRÁC HÃ¹ Tổng Công ty Viglacera - CTCP"
#                    ▲▲                ▲
#                    hỏng              `ổ` U+1ED5 — ngoài Latin-1
#
# `_sloppy_encode` gặp `ổ` là ném lỗi, hàm trả nguyên văn, và mojibake sống sót.
# Nới ra thành "từng đoạn mã hoá được" cũng sai: đoạn đó là
# `"7 J1001 C TRÁC HÃ¹ "`, mà `Á` (U+00C1) mã hoá thành 0xC1 — một byte dẫn
# UTF-8 KHÔNG hợp lệ — nên cả đoạn vẫn hỏng, và nếu ép sửa thì `TRÁC` đúng
# cũng bị đụng vào.
#
# Cửa sổ đúng là một CHUỖI SEQUENCE UTF-8 hoàn chỉnh đã bị đọc sai: một byte
# dẫn kèm 1–3 byte tiếp nối, lặp lại. `Ã¹` khớp; `TRÁC` không, vì `Á` không
# nằm trong tập byte dẫn và `R`/`C` không phải byte tiếp nối. Vùng tiếng Việt
# đúng nằm ngoài cửa sổ theo CẤU TẠO, không phải nhờ một phép kiểm bổ sung.
_UTF8_WINDOW = re.compile(f"(?:[{_LEAD}][{_CONT}]{{1,3}})+")
_MOJIBAKE_PASSES = 3

# CP1252 "dễ dãi" — năm byte 0x81 0x8D 0x8F 0x90 0x9D không được định nghĩa
# trong bảng chuẩn, và codec của Python từ chối chúng. Nhưng chính Windows lại
# cho chúng đi thẳng thành U+0081…, nên mojibake ngoài đời LUÔN chứa chúng:
# `ề` là 0xE1 0xBB 0x81, và 0x81 nằm đúng trong nhóm đó.
_SLOPPY_CP1252: dict[str, int] = {}
for _b in range(0x100):
    try:
        _SLOPPY_CP1252[bytes([_b]).decode("cp1252")] = _b
    except UnicodeDecodeError:
        _SLOPPY_CP1252[chr(_b)] = _b
del _b


def _sloppy_encode(s: str) -> bytes:
    try:
        return bytes(_SLOPPY_CP1252[c] for c in s)
    except KeyError as exc:      # ký tự không nằm trong bảng → không phải mojibake
        raise UnicodeEncodeError("sloppy-cp1252", s, 0, 1, str(exc)) from None


def _suspicion(s: str) -> int:
    """Điểm mojibake — đếm ký tự nằm trong tập byte dẫn/tiếp nối."""
    return len(_SUSPICIOUS.findall(s))


def _repair_window(win: str) -> str | None:
    """Thử sửa MỘT cửa sổ. Trả `None` nếu không chứng minh được.

    Bốn cổng, phải qua CẢ BỐN:
      1. vòng `sloppy-cp1252 → utf-8` chạy trót lọt          — phép chứng minh
      2. điểm mojibake GIẢM THẬT SỰ ở mỗi lượt                — chặn đứng yên
      3. KẾT QUẢ CUỐI không chứa ký tự điều khiển             — chặn rác
      4. kết quả khác đầu vào                                 — hiển nhiên

    Cổng "không ký tự điều khiển" áp cho KẾT QUẢ CUỐI, không phải từng lượt.
    Với mã hoá sai chồng hai lớp, lượt trung gian ĐÚNG LÀ chuỗi mojibake một
    lớp và nó chứa byte tiếp nối 0x81 — một ký tự điều khiển C1. Chặn ở lượt
    trung gian sẽ dừng ngay trước khi tới kết quả đúng: `TiÃ¡Â»Â\x81n` kẹt ở
    `á»\x81` thay vì về `ề`.
    """
    cur = win
    for _ in range(_MOJIBAKE_PASSES):
        try:
            nxt = _sloppy_encode(cur).decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            break
        if nxt == cur or _suspicion(nxt) >= _suspicion(cur):
            break
        cur = nxt
    if cur == win or any(ch in _CTRL for ch in cur):
        return None
    return cur


def _repair_pass(s: str) -> str:
    """Một lượt quét cửa sổ trên toàn chuỗi."""
    if not s or not _MOJIBAKE.search(s):
        return s
    out: list[str] = []
    last = 0
    changed = False
    for m in _UTF8_WINDOW.finditer(s):
        fixed = _repair_window(m.group(0))
        if fixed is None:
            continue
        out.append(s[last:m.start()])
        out.append(fixed)
        last = m.end()
        changed = True
    if not changed:
        return s
    out.append(s[last:])
    return "".join(out)


def repair_mojibake(s: str) -> str:
    """Sửa mojibake THEO CỬA SỔ. Ngoài cửa sổ không một ký tự nào bị đụng.

    Lặp Ở CẤP CHUỖI, không chỉ trong cửa sổ. Mã hoá sai chồng hai lớp làm ranh
    giới cửa sổ ĐỔI sau mỗi lớp được gỡ: `Tiền` hai lớp cho `TiÃ¡Â»Ân`, và
    cửa sổ của lớp ngoài không trùng cửa sổ của lớp trong. Lặp lại phép quét
    cho tới khi chuỗi đứng yên.

    An toàn không đổi: mỗi lượt vẫn phải qua đủ bốn cổng của `_repair_window`,
    nên một lượt không chứng minh được sẽ không đổi gì và vòng lặp dừng.

    Giữ `text_source` bất biến là việc của `clean_text` (DI-04); ở đây bảo đảm
    thứ hẹp hơn nhưng quan trọng không kém: phần văn bản ĐANG ĐÚNG không nằm
    trong bất kỳ cửa sổ nào, nên nó đi qua nguyên vẹn.
    """
    for _ in range(_MOJIBAKE_PASSES):
        nxt = _repair_pass(s)
        if nxt == s:
            return s
        s = nxt
    return s


def repair_mojibake_trace(s: str) -> list[dict]:
    """Vết kiểm toán: mỗi cửa sổ đã sửa, kèm vị trí và điểm trước/sau.

    RC-07 đòi `audit trace`. Tách khỏi `repair_mojibake` để đường nóng của
    build không phải cấp phát thêm gì.
    """
    trace: list[dict] = []
    if not s or not _MOJIBAKE.search(s):
        return trace
    for m in _UTF8_WINDOW.finditer(s):
        fixed = _repair_window(m.group(0))
        if fixed is None:
            continue
        trace.append({"start": m.start(), "end": m.end(),
                      "before": m.group(0), "after": fixed,
                      "suspicion_before": _suspicion(m.group(0)),
                      "suspicion_after": _suspicion(fixed),
                      "rule": "C07", "rule_version": CLEANING_VERSION})
    return trace


@dataclass(slots=True)
class CleanResult:
    text_clean: str
    rules: list[str]
    status: CleanStatus


def clean_text(text_source: str) -> CleanResult:
    """Phép chiếu an toàn. Không bao giờ trả về thứ làm mất thông tin nghiệp vụ."""
    if text_source is None:
        return CleanResult("", [], CleanStatus.UNCHANGED)

    s = text_source
    rules: list[str] = []
    has_broken = False

    if _IMG.search(s):
        s = _IMG.sub(" ", s)
        rules.append("C05")

    # ── Thứ tự C01 → C07 → C06 là BẮT BUỘC, không phải sở thích ────────────
    #
    # C07 sau C01: `Ã` ở dạng NFD là `A` + dấu ngã tổ hợp, mà CP1252 không mã
    # hoá được dấu tổ hợp — chữ ký sẽ không khớp và mojibake lọt lưới.
    #
    # C07 TRƯỚC C06: byte tiếp nối 0x80–0x9F hiện ra thành ký tự điều khiển
    # C1. Đặt C06 trước sẽ **xoá mất** chúng và phá huỷ chính bằng chứng cần
    # để khôi phục — `Tiá»n` (tức `Tiền`, byte 0xE1 0xBB 0x81) mất hẳn 0x81
    # rồi thì không còn đảo ngược được nữa. Đây đúng là lỗi của bản đầu.
    if not unicodedata.is_normalized("NFC", s):
        s = unicodedata.normalize("NFC", s)
        rules.append("C01")

    if (repaired := repair_mojibake(s)) != s:
        s = repaired
        rules.append("C07")
        if not unicodedata.is_normalized("NFC", s):
            # Chuỗi sau khi khôi phục là UTF-8 thật, nhưng chưa chắc NFC.
            s = unicodedata.normalize("NFC", s)
            if "C01" not in rules:
                rules.append("C01")

    if any(c in s for c in _CTRL):
        s = "".join(c for c in s if c not in _CTRL)
        rules.append("C06")

    if "&" in s:
        found = _ENTITY_ANY.findall(s)
        if found:
            decoded = False
            for ent in set(found):
                if ent in _VALID_ENTITIES:
                    s = s.replace(ent, _VALID_ENTITIES[ent])
                    decoded = True
                elif ent.startswith("&#") and ent[2:-1].lstrip("xX").isalnum():
                    try:
                        rep = _html.unescape(ent)
                        if rep != ent:
                            s = s.replace(ent, rep)
                            decoded = True
                    except Exception:  # noqa: BLE001
                        has_broken = True
                else:
                    # `&IR;` `&2;` — lỗi OCR, KHÔNG phải thực thể. Giữ nguyên.
                    has_broken = True
            if decoded:
                rules.append("C02")

    if _WS.search(s):
        t = _WS.sub(" ", s)
        if t != s:
            s = t
            rules.append("C03")

    t = s.strip()
    if t != s:
        s = t
        rules.append("C04")

    if has_broken:
        status = CleanStatus.HAS_BROKEN_ENTITY
    elif rules:
        status = CleanStatus.CLEANED
    else:
        status = CleanStatus.UNCHANGED
    return CleanResult(s, rules, status)
