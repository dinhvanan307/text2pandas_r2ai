import sys; sys.path.insert(0,'tools')
from hier import resolve_hierarchy, path_of
SEC = "6 TSCD"
CASES = {
"CA 1 — tiền tố outline": [
 ("A. TÀI SẢN NGẮN HẠN","100",True),("I. Tiền và tương đương tiền","110",True),
 ("B. TÀI SẢN DÀI HẠN","200",True),("I. Tiền và tương đương tiền","210",True)],
"CA 2 — không tiền tố, có dòng mở phạm vi": [
 ("Nguyên giá",None,False),("Số dư đầu năm",None,True),("Số dư cuối năm",None,True),
 ("Giá trị hao mòn lũy kế",None,False),("Số dư đầu năm",None,True),("Số dư cuối năm",None,True)],
"CA 3 — chỉ có Mã số": [
 ("Tài sản cố định hữu hình","221",True),("Nguyên giá","222",True),
 ("Giá trị hao mòn lũy kế","223",True),("Tài sản cố định vô hình","227",True),
 ("Nguyên giá","228",True),("Giá trị hao mòn lũy kế","229",True)],
"CA 4 (âm) — anh em phẳng, KHÔNG được xâu chuỗi": [
 ("Tiền mặt",None,True),("Tiền gửi ngân hàng",None,True),("Tiền đang chuyển",None,True)],
}
for title, raws in CASES.items():
    rows = [{"idx":i,"raw":r,"label":r.split(". ",1)[-1] if ". " in r else r,
             "code":c,"has_value":v} for i,(r,c,v) in enumerate(raws)]
    out = resolve_hierarchy(rows)
    paths = [path_of(out, r["idx"], SEC) for r in out]
    print("="*74); print(title)
    for r,p in zip(out,paths): print(f"   [{r['source']:<15}] {p}")
    print(f"   -> path duy nhất: {len(set(paths))}/{len(paths)}")
