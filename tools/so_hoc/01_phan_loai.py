"""P0-g bước 1 · phân loại 1.012 câu theo PHÉP TOÁN cần thực hiện.

NGUYÊN TẮC (viết trước khi đo)
------------------------------
* Chỉ đọc CÂU HỎI. Không đọc bảng, không đọc đáp án cũ — nếu không thì lại vòng
  tròn như docs/86 §4.
* Đi từ HẸP tới RỘNG. Câu vừa có "tỷ lệ" vừa có "trong số các công ty có ..."
  thuộc lớp `multi_table`, vì phần khó nằm ở điều kiện lọc.
* `unknown` là nhãn hợp lệ. Ép nhãn cho bảng đẹp chính là cái sai của trục năm.

BÀI HỌC ĐÃ TRẢ GIÁ Ở VÒNG ĐẦU
-----------------------------
Bản đầu bắt "tổng" ở bất kỳ đâu và gán `sum`. Ba lỗi thật ngay trong mẫu 24 câu:

    q261  "TỔNG CỘNG nghĩa vụ nợ tài chính ..."      -> tên chỉ tiêu, không phải phép cộng
    q36   "lợi thế thương mại (TỔNG CỘNG) ..."       -> như trên
    q711  "... của TỔNG CÔNG TY Phân bón ..."        -> tên doanh nghiệp!

"Tổng" chỉ là PHÉP TOÁN khi có một DANH SÁCH để cộng — nhiều năm hoặc nhiều mã.
Không có danh sách thì nó là danh từ. Đây đúng là bài học `_vai_tro` của v4→v5:
một vị từ quá rộng không chỉ làm thống kê xấu, nó phân loại sai.
"""
from __future__ import annotations
import json, re, unicodedata, collections
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CAU = ROOT / "data/external/vifinqa/questions/questions.jsonl"
RA = ROOT / "data/dev/so_hoc/phan_loai.jsonl"


def fold(s: str) -> str:
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.replace("đ", "d").replace("Đ", "D").lower()


_NAM = re.compile(r"(?<![0-9])((?:19|20)\d{2})(?![0-9])")
# Điều kiện lọc: phải chọn ra một TẬP CON rồi mới tính.
# Khoảng cách 60 ký tự là quá hẹp: q567 liệt kê bốn mã trước khi nêu điều kiện
# ("trong các công ty AAA, DCM, DPM và GVR có tỷ lệ ... lớn hơn 10%") nên lọt
# lưới và bị gán `ratio`. Nới lên 90.
_LOC = re.compile(r"trong so (cac|nhung)|xet (cac|nhom|nhung)|"
                  r"(cong ty|doanh nghiep|ma|nam) (nao )?co .{0,90}"
                  r"(cao hon|thap hon|lon hon|nho hon|duong|am|vuot)|"
                  r"tai (cong ty|doanh nghiep|nam) co |o nam .{0,40}co |"
                  r"cua (cong ty|doanh nghiep) co ")
# Câu ĐẾM: đáp án là một SỐ LƯỢNG, không phải một chỉ tiêu tài chính.
_DEM = re.compile(r"co bao nhieu (doanh nghiep|cong ty|ngan hang|ma|nam)|"
                  r"^bao nhieu (doanh nghiep|cong ty|ngan hang|ma|nam)")
_CUC = re.compile(r"lon nhat|nho nhat|cao nhat|thap nhat|dung dau|dan dau")
_ARG_NAM = re.compile(r"nam nao")
_TB = re.compile(r"trung binh|binh quan")
_HIEU = re.compile(r"chenh lech|hieu so|tru di|nhieu hon|it hon|"
                   r"(cao|thap) hon .{0,40}bao nhieu|chenh bao nhieu")
_TYLE = re.compile(r"ty le|ty trong|ty suat|bien loi nhuan|bien lai|\broe\b|\broa\b|"
                   r"he so|vong quay|chiem bao nhieu")
_THAYDOI = re.compile(r"tang truong|toc do tang|muc (tang|giam)|"
                      r"tang bao nhieu|giam bao nhieu|thay doi bao nhieu")
# "tổng" là DANH TỪ trong ba ngữ cảnh này — không phải phép cộng.
_TONG_DANH_TU = re.compile(r"tong cong ty|tong (cong|so|gia tri|muc|no|von|tai san|"
                           r"doanh thu|loi nhuan|chi phi|nghia vu|du no|dien tich)\b")
_TONG_PHEP = re.compile(r"tinh tong|tong cua|cong lai|tong gia tri .{0,25}(trong|qua) cac")

LOP = ("lookup", "ratio", "percentage_change", "difference", "sum",
       "average", "max_min", "argmax_year", "count", "multi_table")


def co_liet_ke(t: str) -> tuple[bool, int, int]:
    """Câu có DANH SÁCH để gộp không? Trả (có, số năm, số mã ước lượng)."""
    nam = len(set(_NAM.findall(t)))
    # mã CK viết hoa trong bản gốc; ở bản fold thì đếm bằng dấu hiệu liệt kê.
    ma = len(re.findall(r"\b[a-z]{3,4}\b(?=\s*[,)]|\s+va\b)", t))
    nhieu = bool(re.search(r"cac nam|qua cac nam|trong cac nam|"
                           r"cac (cong ty|doanh nghiep|ma)|nhom", t))
    return (nam >= 2 or (nhieu and ma >= 2)), nam, ma


def phan_loai(question: str) -> tuple[str, list[str]]:
    t = fold(question)
    liet_ke, n_nam, n_ma = co_liet_ke(t)
    dh = []
    if _DEM.search(t):
        dh.append("cau DEM")
    if _LOC.search(t):
        dh.append("dieu kien loc")
    if _ARG_NAM.search(t):
        dh.append("hoi NAM NAO")
    if _CUC.search(t):
        dh.append("cuc tri")
    if _TB.search(t):
        dh.append("trung binh")
    # `sum` CHỈ khi có lời gọi phép cộng tường minh. Thử nới ra "tổng + có danh
    # sách" thì q655 ("tốc độ tăng trưởng % TỔNG TIỀN ... từ 2019 đến 2021") bị
    # gán `sum` — "tổng tiền" là tên chỉ tiêu. Danh sách các danh từ bắt đầu
    # bằng "tổng" là vô hạn; chỉ có lời gọi tường minh mới đếm được.
    if _TONG_PHEP.search(t):
        dh.append("tong (goi tuong minh)")
    if _THAYDOI.search(t):
        dh.append("thay doi theo thoi gian")
    if _HIEU.search(t):
        dh.append("so sanh hai ve")
    if _TYLE.search(t):
        dh.append("ty le")
    if liet_ke:
        dh.append(f"danh sach: {n_nam} nam")

    if "cau DEM" in dh:
        return "count", dh
    if "dieu kien loc" in dh:
        return "multi_table", dh
    if "hoi NAM NAO" in dh:
        return "argmax_year", dh
    if "cuc tri" in dh and liet_ke:
        return "max_min", dh
    if "trung binh" in dh:
        return "average", dh
    if "tong (goi tuong minh)" in dh:
        return "sum", dh
    if "thay doi theo thoi gian" in dh:
        return "percentage_change", dh
    if "so sanh hai ve" in dh:
        return "difference", dh
    if "ty le" in dh:
        return "ratio", dh
    return "lookup", dh


def don_vi_hoi(t: str) -> str:
    """Đơn vị mà CÂU HỎI đòi. Phải khớp có ngữ cảnh.

    Bản đầu bắt chuỗi `dong` trần nên q971 ("chi phí hoa hồng môi giới BẤT ĐỘNG
    SẢN") bị gán đơn vị `đồng`. `bat dong san`, `hoat dong`, `lao dong` đều chứa
    `dong`. Đây là lần thứ ba cùng một loại lỗi trong dự án — xem docs/89 §4.
    """
    for mau, v in ((r"nghin ty (dong|vnd)", "nghin_ty"), (r"tram ty (dong|vnd)", "tram_ty"),
                   (r"\bty (dong|vnd)\b", "ty"), (r"trieu (dong|vnd)\b", "trieu"),
                   (r"nghin (dong|vnd)\b", "nghin"),
                   (r"phan tram|bao nhieu %|\(%\)|% la bao nhieu", "%"),
                   (r"bao nhieu lan|\blan\b\?*$", "lan"),
                   (r"co phieu", "co_phieu"),
                   (r"bao nhieu dong|dong\?$|bang dong\b", "dong")):
        if re.search(mau, t):
            return v
    return "?"


def main() -> int:
    qs = [json.loads(l) for l in CAU.open(encoding="utf-8") if l.strip()]
    ra = []
    for q in qs:
        lop, dh = phan_loai(q["question"])
        ra.append({"id": q["id"], "question": q["question"], "lop": lop,
                   "dau_hieu": dh, "don_vi_hoi": don_vi_hoi(fold(q["question"]))})
    RA.parent.mkdir(parents=True, exist_ok=True)
    with RA.open("w", encoding="utf-8") as f:
        for r in ra:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    c = collections.Counter(r["lop"] for r in ra)
    print(f"{'lớp':<20}{'số câu':>8}{'tỷ lệ':>9}{'trong đó % / lần':>20}")
    for k in LOP:
        if c[k]:
            pl = sum(1 for r in ra if r["lop"] == k and r["don_vi_hoi"] in ("%", "lan"))
            print(f"{k:<20}{c[k]:>8}{c[k]/len(ra):>9.1%}{pl:>20}")
    print(f"{'TỔNG':<20}{len(ra):>8}")
    print(f"-> {RA.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
