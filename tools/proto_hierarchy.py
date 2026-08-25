"""Nguyên mẫu quy tắc phân cấp DỰA TRÊN BẰNG CHỨNG — chỉ để kiểm chứng, chưa vào pipeline."""
import sys; sys.path.insert(0, 'src')
from text2pandas.pipelines.a6.structure import _level_of

# Bản đồ cha-con Thông tư 200 B01-DN, TƯỜNG MINH. Không suy từ độ dài mã.
PARENT_CODE_B01DN = {
    "110":"100","111":"110","112":"110","120":"100","121":"120","122":"120",
    "130":"100","131":"130","132":"130","140":"100","141":"140","150":"100",
    "210":"200","211":"210","220":"200","221":"220","222":"221","223":"221",
    "224":"220","225":"224","226":"224","227":"220","228":"227","229":"227",
    "230":"200","240":"200","250":"200","260":"200",
    "310":"300","311":"310","312":"310","320":"300","330":"300",
    "410":"400","411":"410","412":"410","420":"400",
}

def resolve_hierarchy(rows, taxonomy=PARENT_CODE_B01DN):
    """rows: list of dict(idx,label,code,has_value). Trả parent_idx + nguồn bằng chứng."""
    by_code = {}
    out = []
    outline_stack = []          # (level, idx)
    section_idx = None          # phạm vi mở bởi dòng KHÔNG có giá trị
    for r in rows:
        idx, label, code, has_value = r["idx"], r["label"], r["code"], r["has_value"]
        parent, source = None, "none"

        lvl = _level_of(r["raw"])
        if lvl is not None:                                   # BC1: tiền tố outline
            while outline_stack and outline_stack[-1][0] >= lvl:
                outline_stack.pop()
            parent = outline_stack[-1][1] if outline_stack else None
            source = "outline_prefix" if parent is not None else "none"
            outline_stack.append((lvl, idx))
            section_idx = None
        elif code and taxonomy.get(code) in by_code:          # BC2: taxonomy Mã số
            parent, source = by_code[taxonomy[code]], "taxonomy"
        elif not has_value and label:                         # BC3: dòng mở phạm vi
            section_idx, parent, source = idx, None, "none"
        elif section_idx is not None:
            parent, source = section_idx, "section_segment"

        if code:
            by_code[code] = idx
        out.append({**r, "parent": parent, "source": source})
    return out

def path_of(rows_out, idx, sec):
    parts, seen, cur = [], set(), idx
    while cur is not None and cur not in seen:
        seen.add(cur); parts.append(rows_out[cur]["label"]); cur = rows_out[cur]["parent"]
    return " › ".join([sec] + list(reversed(parts)))
