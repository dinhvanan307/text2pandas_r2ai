#!/usr/bin/env python3
"""Sinh `data_preview.html` — xem và đánh giá Silver bằng trình duyệt, không mở SQLite.

    python tools/make_preview.py [silver.db] [-o data_preview.html] [--sample 20]

Vì sao cần: `silver.db` nặng 2–3 GB. Công cụ GUI mở nó rất chậm hoặc treo, mà
người cần đánh giá chất lượng dữ liệu thường không phải người dựng ra nó. Một
trang HTML tự chứa vài trăm KB trả lời được hầu hết câu hỏi mà không ai phải cài
gì.

Trang này chỉ ĐỌC. Nó không sửa, không suy diễn, không làm đẹp số liệu — mọi con
số trong trang đều truy được về một câu truy vấn trên chính tệp database.
"""

from __future__ import annotations

import argparse
import html
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

# ── Bảng màu đã kiểm bằng scripts/validate_palette.js ────────────────────────
# Chỉ dùng MỘT hue (blue) vì mọi biểu đồ ở đây là độ lớn một chuỗi — màu không
# mang thông tin phân loại, nên bảng phân loại nhiều hue sẽ là trang trí.
# Bậc ordinal cho `confidence` (high→low) đã chạy validator ở cả hai chế độ:
#   light  #1c5cab / #3987e5 / #86b6ef   — ALL CHECKS PASS
#   dark   #184f95 / #3987e5 / #9ec5f4   — ALL CHECKS PASS
ORDINAL_LIGHT = ("#1c5cab", "#3987e5", "#86b6ef")

BUSINESS_KEYS: dict[str, list[str]] = {
    "documents": ["directory_doc_id"],
    "pages": ["document_uid", "page_no"],
    "tables": ["directory_doc_id", "line_start_1based"],
    "columns": ["table_uid", "grid_col_idx"],
    "rows": ["table_uid", "grid_row_idx"],
    "observations": ["table_uid", "grid_row_idx", "grid_col_idx"],
    "quality_issues": ["rule_id", "entity_id"],
    "source_cells": ["table_uid", "source_row_idx", "source_col_idx"],
    "grid_cells": ["table_uid", "grid_row_idx", "grid_col_idx"],
}

ENTITY_LABELS = {
    "documents": "Tài liệu (= báo cáo)",
    "pages": "Trang",
    "tables": "Bảng",
    "columns": "Cột",
    "rows": "Dòng",
    "observations": "Observation (ô số)",
    "quality_issues": "Bản ghi vấn đề",
    "source_cells": "Ô nguồn",
    "grid_cells": "Ô lưới",
}

MAX_CELL = 110


def e(x) -> str:
    return html.escape("" if x is None else str(x), quote=True)


def vn(n) -> str:
    """Định dạng số theo quy ước Việt Nam: 1.234.567."""
    try:
        return f"{int(n):,}".replace(",", ".")
    except (TypeError, ValueError):
        return str(n)


def q_all(conn, sql, args=()):
    return conn.execute(sql, args).fetchall()


def q_one(conn, sql, args=()):
    r = conn.execute(sql, args).fetchone()
    return r[0] if r else None


# ─────────────────────────── thu thập ───────────────────────────

def collect(conn: sqlite3.Connection, sample_n: int) -> dict:
    names = [r[0] for r in q_all(
        conn, "SELECT name FROM sqlite_master WHERE type='table'"
        " AND name NOT LIKE 'sqlite_%' AND name NOT LIKE '%_fts_%'"
        " AND name NOT LIKE '%_config' AND name NOT LIKE '%_data'"
        " AND name NOT LIKE '%_idx' AND name NOT LIKE '%_docsize'"
        " AND name NOT LIKE '%_content' AND name NOT LIKE '%_fts'"
        " ORDER BY name")]

    meta = dict(q_all(conn, "SELECT key, value FROM build_meta")) \
        if "build_meta" in names else {}

    tables = []
    for name in names:
        cols = q_all(conn, f"PRAGMA table_info({name})")
        n_rows = q_one(conn, f"SELECT COUNT(*) FROM {name}") or 0

        col_info = []
        for _cid, cname, ctype, notnull, dflt, pk in cols:
            # Rỗng gồm cả NULL lẫn chuỗi rỗng — với dữ liệu văn bản, chuỗi rỗng
            # là "không có" y như NULL, và gộp hai thứ mới ra con số dùng được.
            n_null = q_one(
                conn,
                f"SELECT COUNT(*) FROM {name}"
                f" WHERE \"{cname}\" IS NULL OR \"{cname}\"=''") or 0 if n_rows else 0
            n_uniq = q_one(
                conn, f"SELECT COUNT(DISTINCT \"{cname}\") FROM {name}") or 0 \
                if n_rows else 0
            col_info.append({
                "name": cname, "type": ctype or "TEXT",
                "notnull": bool(notnull), "pk": bool(pk),
                "default": dflt,
                "null_pct": round(100 * n_null / n_rows, 2) if n_rows else 0.0,
                "n_null": n_null, "n_unique": n_uniq,
            })

        pk_cols = [c["name"] for c in col_info if c["pk"]]
        n_dup_pk = 0
        if pk_cols and n_rows:
            keys = ",".join(f'"{c}"' for c in pk_cols)
            n_dup_pk = n_rows - (q_one(
                conn, f"SELECT COUNT(*) FROM (SELECT DISTINCT {keys} FROM {name})") or 0)

        bkey = [c for c in BUSINESS_KEYS.get(name, []) if c in {x["name"] for x in col_info}]
        n_dup_bk = None
        if bkey and n_rows:
            keys = ",".join(f'"{c}"' for c in bkey)
            n_dup_bk = n_rows - (q_one(
                conn, f"SELECT COUNT(*) FROM (SELECT DISTINCT {keys} FROM {name})") or 0)

        fks = [{"from": f[3], "table": f[2], "to": f[4]}
               for f in q_all(conn, f"PRAGMA foreign_key_list({name})")]
        idxs = [{"name": r[1], "unique": bool(r[2])}
                for r in q_all(conn, f"PRAGMA index_list({name})")
                if not r[1].startswith("sqlite_autoindex")]

        order = f" ORDER BY {pk_cols[0]}" if pk_cols else ""
        rows = q_all(conn, f"SELECT * FROM {name}{order} LIMIT {sample_n}")

        tables.append({
            "name": name, "n_rows": n_rows, "n_cols": len(col_info),
            "columns": col_info, "pk": pk_cols, "n_dup_pk": n_dup_pk,
            "business_key": bkey, "n_dup_bk": n_dup_bk,
            "fks": fks, "indexes": idxs,
            "sample": [[None if v is None else str(v) for v in r] for r in rows],
        })

    charts = []

    def chart(title, note, sql, ordinal=False):
        try:
            data = [(str(a), int(b)) for a, b in q_all(conn, sql)]
        except sqlite3.Error:
            return
        if data:
            charts.append({"title": title, "note": note, "data": data,
                           "ordinal": ordinal})

    if "observations" in names:
        chart("Observation theo độ tin cậy",
              "high = kỳ đọc từ nhãn cột, đơn vị có bằng chứng, nhãn dòng riêng biệt. "
              "low = thiếu kỳ, hoặc đơn vị mặc định, hoặc cột chưa phân loại.",
              "SELECT confidence, COUNT(*) FROM observations GROUP BY 1"
              " ORDER BY CASE confidence WHEN 'high' THEN 1 WHEN 'medium' THEN 2"
              " ELSE 3 END", ordinal=True)
        chart("Observation theo loại giá trị", "",
              "SELECT value_kind, COUNT(*) n FROM observations GROUP BY 1"
              " ORDER BY n DESC")
        chart("Observation theo loại báo cáo", "",
              "SELECT statement_type, COUNT(*) n FROM observations GROUP BY 1"
              " ORDER BY n DESC")
        chart("Ô TIỀN theo đơn vị đã giải",
              "Ô có value_kind='money' nhưng unit_kind khác 'money' là ô KHÔNG tìm "
              "được bằng chứng đơn vị — bậc 10 bị bỏ trống.",
              "SELECT unit_kind, COUNT(*) n FROM observations"
              " WHERE value_kind='money' GROUP BY 1 ORDER BY n DESC")
        chart("Observation theo bậc đơn vị (10^n)", "0 = VND · 3 = nghìn · 6 = triệu · 9 = tỷ",
              "SELECT COALESCE(CAST(scale_exponent AS TEXT),'(trống)') s, COUNT(*) n"
              " FROM observations WHERE value_kind='money' GROUP BY 1 ORDER BY n DESC")
        chart("Observation theo năm tài liệu", "",
              "SELECT COALESCE(CAST(doc_year AS TEXT),'(trống)'), COUNT(*)"
              " FROM observations GROUP BY 1 ORDER BY 1")
        chart("Observation theo nguồn bằng chứng của kỳ",
              "column_path = đọc thẳng từ nhãn cột. table_context = SUY DIỄN từ "
              "ngữ cảnh bảng, yếu hơn một bậc.",
              "SELECT period_source, COUNT(*) n FROM observations GROUP BY 1"
              " ORDER BY n DESC")
    if "tables" in names:
        chart("Bảng theo loại báo cáo", "",
              "SELECT statement_type, COUNT(*) n FROM tables GROUP BY 1 ORDER BY n DESC")
        chart("Bảng theo trạng thái parse", "",
              "SELECT parse_status, COUNT(*) n FROM tables GROUP BY 1 ORDER BY n DESC")
    if "quality_issues" in names:
        chart("Vấn đề chất lượng theo rule (top 15)",
              "Đây là bản ghi MẪU: mỗi rule lưu tối đa 5.000 mẫu, con số tổng đầy "
              "đủ nằm trong SILVER_REPORT.md.",
              "SELECT rule_id, COUNT(*) n FROM quality_issues GROUP BY 1"
              " ORDER BY n DESC LIMIT 15")

    coverage = []
    if "tables" in names:
        try:
            rows = q_all(conn,
                "SELECT ticker, doc_year, COUNT(*) FROM tables"
                " WHERE doc_year IS NOT NULL GROUP BY 1,2")
            tickers = sorted({r[0] for r in rows})
            years = sorted({int(r[1]) for r in rows})
            cell = {(r[0], int(r[1])): int(r[2]) for r in rows}
            coverage = {"tickers": tickers, "years": years,
                        "cells": {f"{t}|{y}": cell.get((t, y), 0)
                                  for t in tickers for y in years},
                        "max": max(cell.values()) if cell else 0}
        except sqlite3.Error:
            coverage = []

    return {"tables": tables, "charts": charts, "meta": meta,
            "coverage": coverage, "sample_n": sample_n}


# ─────────────────────────── dựng HTML ───────────────────────────

_CSS = """
:root{color-scheme:light;--surface:#fcfcfb;--plane:#f9f9f7;--ink:#0b0b0b;
--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;
--s1:#2a78d6;--o1:#1c5cab;--o2:#3987e5;--o3:#86b6ef;
--good:#0ca30c;--warn:#fab219;--crit:#d03b3b;--ring:rgba(11,11,11,.10)}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])){
color-scheme:dark;--surface:#1a1a19;--plane:#0d0d0d;--ink:#fff;--ink2:#c3c2b7;
--muted:#898781;--grid:#2c2c2a;--axis:#383835;--s1:#3987e5;
--o1:#184f95;--o2:#3987e5;--o3:#9ec5f4;--ring:rgba(255,255,255,.10)}}
:root[data-theme=dark]{color-scheme:dark;--surface:#1a1a19;--plane:#0d0d0d;
--ink:#fff;--ink2:#c3c2b7;--muted:#898781;--grid:#2c2c2a;--axis:#383835;
--s1:#3987e5;--o1:#184f95;--o2:#3987e5;--o3:#9ec5f4;--ring:rgba(255,255,255,.10)}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
font:14px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
a{color:var(--s1)}
nav{position:sticky;top:0;z-index:50;background:var(--surface);
border-bottom:1px solid var(--grid);padding:10px 20px;display:flex;
gap:6px;flex-wrap:wrap;align-items:center}
nav b{margin-right:8px}
nav a{display:inline-block;padding:4px 10px;border-radius:6px;
border:1px solid var(--ring);text-decoration:none;color:var(--ink2);font-size:13px}
nav a:hover{background:var(--plane);color:var(--ink)}
nav .sp{flex:1}
button.t{border:1px solid var(--ring);background:var(--surface);color:var(--ink2);
border-radius:6px;padding:4px 10px;cursor:pointer;font-size:13px}
main{max-width:1200px;margin:0 auto;padding:24px 20px 80px}
section{background:var(--surface);border:1px solid var(--ring);border-radius:10px;
padding:20px 22px;margin:0 0 20px}
h1{font-size:24px;margin:0 0 4px}h2{font-size:19px;margin:0 0 14px;
padding-bottom:8px;border-bottom:1px solid var(--grid)}
h3{font-size:15px;margin:22px 0 8px;color:var(--ink2)}
.sub{color:var(--muted);font-size:13px;margin:0 0 18px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.tile{border:1px solid var(--ring);border-radius:8px;padding:12px 14px}
.tile .v{font-size:26px;font-weight:650;letter-spacing:-.02em}
.tile .k{color:var(--muted);font-size:12px;margin-top:2px}
table{border-collapse:collapse;width:100%;font-size:13px}
th{text-align:left;font-weight:600;color:var(--ink2);border-bottom:1px solid var(--axis);
padding:6px 8px;white-space:nowrap;position:sticky;top:46px;background:var(--surface)}
td{border-bottom:1px solid var(--grid);padding:5px 8px;vertical-align:top}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
.scroll{overflow:auto;max-height:520px;border:1px solid var(--grid);border-radius:8px}
code{background:var(--plane);padding:1px 5px;border-radius:4px;font-size:12px}
.pill{display:inline-block;padding:1px 7px;border-radius:99px;font-size:11px;
border:1px solid var(--ring);color:var(--ink2)}
.ok{color:var(--good)}.bad{color:var(--crit);font-weight:600}
.warnx{color:var(--warn)}
/* biểu đồ: thanh ngang, đầu dữ liệu bo 4px, neo ở đường gốc bên trái */
.chart{display:grid;grid-template-columns:minmax(90px,190px) 1fr 92px;
gap:2px 10px;align-items:center;margin:10px 0 4px}
.chart .lab{color:var(--ink2);font-size:12.5px;text-align:right;
overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.track{background:var(--plane);border-radius:0 4px 4px 0;height:16px;position:relative}
.bar{height:16px;border-radius:0 4px 4px 0;background:var(--s1);min-width:2px}
.chart .val{font-variant-numeric:tabular-nums;font-size:12.5px;color:var(--ink2)}
.note{color:var(--muted);font-size:12.5px;margin:2px 0 14px;max-width:70ch}
#tip{position:fixed;pointer-events:none;background:var(--ink);color:var(--surface);
padding:5px 9px;border-radius:6px;font-size:12px;opacity:0;transition:opacity .1s;
z-index:99;white-space:nowrap}
.cov{overflow:auto;border:1px solid var(--grid);border-radius:8px;max-height:560px}
.cov table{font-size:11px}.cov td{padding:0;border:none}
.cov th{position:static;top:auto;padding:4px 6px}
.cov .c{width:22px;height:16px;border-radius:2px;margin:1px}
.hide{display:none}
.filt{width:100%;padding:7px 10px;border:1px solid var(--ring);border-radius:7px;
background:var(--plane);color:var(--ink);margin-bottom:10px}
.erd{width:100%;height:auto}
"""

_JS = """
const tip=document.getElementById('tip');
document.addEventListener('mouseover',ev=>{
  const t=ev.target.closest('[data-tip]');
  if(!t){tip.style.opacity=0;return}
  tip.textContent=t.dataset.tip;tip.style.opacity=1;
});
document.addEventListener('mousemove',ev=>{
  if(tip.style.opacity==='1'){
    tip.style.left=Math.min(ev.clientX+14,innerWidth-tip.offsetWidth-8)+'px';
    tip.style.top=(ev.clientY+18)+'px';}
});
document.querySelectorAll('nav a[data-go]').forEach(a=>a.onclick=ev=>{
  ev.preventDefault();show(a.dataset.go);});
function show(id){
  document.querySelectorAll('main > section[data-panel]').forEach(s=>
    s.classList.toggle('hide', s.dataset.panel!==id && id!=='__all__'));
  location.hash=id;
  window.scrollTo({top:0});
}
window.addEventListener('load',()=>show(location.hash.slice(1)||'overview'));
document.getElementById('theme').onclick=()=>{
  const d=document.documentElement;
  d.dataset.theme = d.dataset.theme==='dark' ? 'light' : 'dark';
};
function filt(id,inp){
  const q=inp.value.toLowerCase();
  document.querySelectorAll('#'+id+' tbody tr').forEach(tr=>{
    tr.style.display = tr.textContent.toLowerCase().includes(q) ? '' : 'none';});
}
"""


def bar_chart(data, ordinal=False) -> str:
    if not data:
        return "<p class='note'>(không có dữ liệu)</p>"
    mx = max(v for _, v in data) or 1
    total = sum(v for _, v in data) or 1
    ramp = ("var(--o1)", "var(--o2)", "var(--o3)")
    out = ["<div class='chart'>"]
    for i, (label, v) in enumerate(data):
        pct = 100 * v / mx
        color = ramp[min(i, 2)] if ordinal else "var(--s1)"
        tip = f"{label}: {vn(v)} ({100*v/total:.1f}%)"
        out.append(
            f"<div class='lab' title='{e(label)}'>{e(label)}</div>"
            f"<div class='track' data-tip='{e(tip)}'>"
            f"<div class='bar' style='width:{pct:.3f}%;background:{color}'></div></div>"
            f"<div class='val'>{vn(v)}</div>")
    out.append("</div>")
    return "".join(out)


def erd_svg(tables: list[dict]) -> str:
    present = {t["name"] for t in tables}
    boxes = [("documents", 40, 30), ("pages", 40, 130), ("tables", 300, 30),
             ("columns", 580, 20), ("rows", 580, 110), ("observations", 580, 205),
             ("quality_issues", 300, 205)]
    links = [(40, 30, 40, 130), (300, 30, 40, 30), (580, 20, 300, 30),
             (580, 110, 300, 30), (580, 205, 300, 30)]
    svg = ['<svg class="erd" viewBox="0 0 820 290" role="img" '
           'aria-label="Sơ đồ quan hệ giữa các bảng">']
    for x1, y1, x2, y2 in links:
        svg.append(f'<path d="M{x2+150} {y2+18} C{x2+210} {y2+18}, {x1-60} {y1+18}, '
                   f'{x1} {y1+18}" fill="none" stroke="var(--axis)" stroke-width="2"/>')
    for name, x, y in boxes:
        if name not in present:
            continue
        n = next(t["n_rows"] for t in tables if t["name"] == name)
        primary = name in ("observations", "tables")
        svg.append(
            f'<g><rect x="{x}" y="{y}" width="190" height="52" rx="8" '
            f'fill="var(--surface)" stroke="{"var(--s1)" if primary else "var(--axis)"}" '
            f'stroke-width="{2 if primary else 1.5}"/>'
            f'<text x="{x+12}" y="{y+22}" fill="var(--ink)" font-size="13" '
            f'font-weight="600" font-family="system-ui">{e(name)}</text>'
            f'<text x="{x+12}" y="{y+40}" fill="var(--muted)" font-size="11.5" '
            f'font-family="system-ui">{vn(n)} dòng</text></g>')
    svg.append('</svg>')
    return "".join(svg)


def coverage_grid(cov: dict) -> str:
    if not cov or not cov.get("tickers"):
        return ""
    mx = cov["max"] or 1
    years = cov["years"]
    out = ["<div class='cov'><table><thead><tr><th>Mã</th>"]
    out += [f"<th class='num'>{y}</th>" for y in years]
    out.append("</tr></thead><tbody>")
    for t in cov["tickers"]:
        out.append(f"<tr><td><code>{e(t)}</code></td>")
        for y in years:
            n = cov["cells"].get(f"{t}|{y}", 0)
            # Thang tuần tự MỘT hue: đậm = nhiều bảng. Ô trống dùng nền phẳng,
            # không dùng màu nhạt nhất — "không có dữ liệu" khác "có rất ít".
            if n == 0:
                style = "background:var(--plane);border:1px dashed var(--grid)"
                tip = f"{t} {y}: không có tài liệu"
            else:
                a = 0.18 + 0.82 * (n / mx) ** 0.5
                style = f"background:color-mix(in oklab,var(--s1) {a*100:.0f}%,transparent)"
                tip = f"{t} {y}: {vn(n)} bảng"
            out.append(f"<td><div class='c' style='{style}' data-tip='{e(tip)}'></div></td>")
        out.append("</tr>")
    out.append("</tbody></table></div>")
    return "".join(out)


def table_panel(t: dict, sample_n: int) -> str:
    o = [f"<section data-panel='{e(t['name'])}' class='hide'>",
         f"<h2><code>{e(t['name'])}</code></h2>"]

    dup_bk = t["n_dup_bk"]
    o.append("<div class='tiles'>")
    for label, val, cls in (
        ("Số dòng", vn(t["n_rows"]), ""),
        ("Số cột", vn(t["n_cols"]), ""),
        ("Trùng khoá chính", vn(t["n_dup_pk"]),
         "ok" if t["n_dup_pk"] == 0 else "bad"),
        ("Trùng khoá nghiệp vụ", "—" if dup_bk is None else vn(dup_bk),
         "" if dup_bk is None else ("ok" if dup_bk == 0 else "bad")),
    ):
        o.append(f"<div class='tile'><div class='v {cls}'>{val}</div>"
                 f"<div class='k'>{label}</div></div>")
    o.append("</div>")
    if t["business_key"]:
        o.append(f"<p class='note'>Khoá nghiệp vụ: "
                 f"{', '.join('<code>'+e(c)+'</code>' for c in t['business_key'])}"
                 f" — khoá chính đã chặn trùng dòng, con số này bắt trùng ở tầng "
                 f"ý nghĩa mà khoá chính không phủ.</p>")

    o.append("<h3>Lược đồ và tỷ lệ rỗng theo cột</h3>")
    o.append("<div class='scroll'><table><thead><tr>"
             "<th>Cột</th><th>Kiểu</th><th>Khoá</th><th class='num'>Rỗng</th>"
             "<th>Rỗng (%)</th><th class='num'>Giá trị khác nhau</th></tr></thead><tbody>")
    for c in t["columns"]:
        pct = c["null_pct"]
        cls = "bad" if pct >= 50 else ("warnx" if pct >= 10 else "")
        w = min(100.0, pct)
        o.append(
            f"<tr><td><code>{e(c['name'])}</code></td><td>{e(c['type'])}</td>"
            f"<td>{'<span class=pill>PK</span>' if c['pk'] else ''}"
            f"{'<span class=pill>NOT NULL</span>' if c['notnull'] else ''}</td>"
            f"<td class='num {cls}'>{vn(c['n_null'])}</td>"
            f"<td><div class='track' style='width:120px;display:inline-block'"
            f" data-tip='{e(c['name'])}: rỗng {pct}%'>"
            f"<div class='bar' style='width:{w:.2f}%'></div></div>"
            f" <span class='val {cls}'>{pct}%</span></td>"
            f"<td class='num'>{vn(c['n_unique'])}</td></tr>")
    o.append("</tbody></table></div>")

    if t["fks"]:
        o.append("<h3>Khoá ngoại</h3><p class='note'>" + " · ".join(
            f"<code>{e(f['from'])}</code> → <code>{e(f['table'])}.{e(f['to'])}</code>"
            for f in t["fks"]) + "</p>")
    if t["indexes"]:
        o.append("<h3>Chỉ mục</h3><p class='note'>" + " · ".join(
            f"<code>{e(i['name'])}</code>" + (" <span class=pill>UNIQUE</span>"
                                              if i["unique"] else "")
            for i in t["indexes"]) + "</p>")

    tid = f"s_{t['name']}"
    o.append(f"<h3>{sample_n} dòng mẫu</h3>")
    o.append(f"<input class='filt' placeholder='Lọc trong {sample_n} dòng mẫu…' "
             f"oninput=\"filt('{tid}',this)\">")
    o.append(f"<div class='scroll' id='{tid}'><table><thead><tr>")
    o += [f"<th>{e(c['name'])}</th>" for c in t["columns"]]
    o.append("</tr></thead><tbody>")
    for row in t["sample"]:
        o.append("<tr>")
        for v in row:
            if v is None:
                o.append("<td><span class='pill'>NULL</span></td>")
            else:
                short = v if len(v) <= MAX_CELL else v[:MAX_CELL] + "…"
                full = v if len(v) <= 400 else v[:400] + "…"
                o.append(f"<td data-tip='{e(full)}'>{e(short)}</td>")
        o.append("</tr>")
    o.append("</tbody></table></div></section>")
    return "".join(o)


def build_html(d: dict, db_path: Path) -> str:
    tabs = d["tables"]
    by = {t["name"]: t for t in tabs}
    meta = d["meta"]
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    nav = ["<nav><b>Silver</b>",
           "<a href='#overview' data-go='overview'>Tổng quan</a>",
           "<a href='#charts' data-go='charts'>Biểu đồ</a>",
           "<a href='#erd' data-go='erd'>Quan hệ</a>"]
    nav += [f"<a href='#{e(t['name'])}' data-go='{e(t['name'])}'>{e(t['name'])}"
            f" <span class='pill'>{vn(t['n_rows'])}</span></a>" for t in tabs]
    nav += ["<span class='sp'></span>",
            "<button class='t' id='theme'>Sáng / Tối</button></nav>"]

    ov = ["<section data-panel='overview'><h1>Silver Layer — xem nhanh dữ liệu</h1>",
          f"<p class='sub'>Bản dựng <code>{e(meta.get('build_id','—'))}</code> · "
          f"lược đồ phát hành <code>{e(meta.get('release_schema_version','—'))}</code> · "
          f"hồ sơ <code>{e(meta.get('release_profile','—'))}</code> · "
          f"sinh lúc {now} từ <code>{e(db_path.name)}</code></p>",
          "<div class='tiles'>"]
    for name in ("documents", "pages", "tables", "columns", "rows",
                 "observations", "quality_issues"):
        if name in by:
            ov.append(f"<div class='tile'><div class='v'>{vn(by[name]['n_rows'])}</div>"
                      f"<div class='k'>{ENTITY_LABELS.get(name, name)}</div></div>")
    ov.append("</div>")

    ov.append("<h3>Danh sách bảng trong SQLite</h3><table><thead><tr>"
              "<th>Bảng</th><th class='num'>Dòng</th><th class='num'>Cột</th>"
              "<th class='num'>Trùng PK</th><th class='num'>Trùng khoá NV</th>"
              "<th class='num'>Cột rỗng > 50%</th><th>Ý nghĩa</th>"
              "</tr></thead><tbody>")
    for t in tabs:
        bad_cols = sum(1 for c in t["columns"] if c["null_pct"] >= 50)
        dup_bk = t["n_dup_bk"]
        ov.append(
            f"<tr><td><a href='#{e(t['name'])}' onclick=\"show('{e(t['name'])}')\">"
            f"<code>{e(t['name'])}</code></a></td>"
            f"<td class='num'>{vn(t['n_rows'])}</td>"
            f"<td class='num'>{t['n_cols']}</td>"
            f"<td class='num {'ok' if t['n_dup_pk']==0 else 'bad'}'>{vn(t['n_dup_pk'])}</td>"
            f"<td class='num {'' if dup_bk is None else ('ok' if dup_bk==0 else 'bad')}'>"
            f"{'—' if dup_bk is None else vn(dup_bk)}</td>"
            f"<td class='num {'warnx' if bad_cols else ''}'>{bad_cols}</td>"
            f"<td>{e(ENTITY_LABELS.get(t['name'], ''))}</td></tr>")
    ov.append("</tbody></table>")

    ov.append("<h3>Ba điều phải biết trước khi dùng số liệu</h3>"
              "<p class='note'><b>1.</b> <code>value_decimal_text</code> là "
              "<b>chuỗi</b>, không phải số. Corpus có giá trị tới 10¹⁵ VND; "
              "<code>float64</code> chỉ giữ chính xác 15–16 chữ số. Đọc bằng "
              "<code>Decimal(...)</code>.<br>"
              "<b>2.</b> Ô trống <b>không phải số 0</b>. Dấu gạch ngang trong báo "
              "cáo tài chính nghĩa là <i>khuyết dữ liệu</i>; những ô đó cố ý không "
              "có mặt ở đây.<br>"
              "<b>3.</b> Cột <code>confidence</code> có thật. <code>low</code> nghĩa "
              "là thiếu kỳ, hoặc đơn vị mặc định, hoặc cột chưa phân loại được vai "
              "trò — nên hạ trọng số thay vì tin ngang <code>high</code>.</p>")

    if d["coverage"]:
        ov.append("<h3>Độ phủ corpus: mã chứng khoán × năm</h3>"
                  "<p class='note'>Đậm = nhiều bảng. Ô gạch đứt = <b>không có tài "
                  "liệu</b>, khác hẳn với ô có rất ít dữ liệu — nên nó dùng nền "
                  "phẳng chứ không dùng bước màu nhạt nhất.</p>")
        ov.append(coverage_grid(d["coverage"]))
    ov.append("</section>")

    ch = ["<section data-panel='charts' class='hide'><h2>Biểu đồ thống kê</h2>",
          "<p class='sub'>Mọi biểu đồ ở đây là độ lớn một chuỗi, nên chỉ dùng một "
          "màu — màu không mang thông tin phân loại. Con số in ngay cạnh thanh, "
          "nên bảng số và biểu đồ là một.</p>"]
    for c in d["charts"]:
        ch.append(f"<h3>{e(c['title'])}</h3>")
        if c["note"]:
            ch.append(f"<p class='note'>{e(c['note'])}</p>")
        ch.append(bar_chart(c["data"], c["ordinal"]))
    ch.append("</section>")

    erd = ["<section data-panel='erd' class='hide'><h2>Quan hệ giữa các bảng</h2>",
           "<p class='sub'><code>observations</code> là bảng trung tâm: mỗi dòng là "
           "một ô số, neo về đúng một <code>(table_uid, grid_row_idx, grid_col_idx)</code>, "
           "và mang sẵn <code>ticker</code>/<code>doc_year</code>/"
           "<code>statement_type</code> phi chuẩn hoá để lọc không cần JOIN.</p>",
           erd_svg(tabs)]
    erd.append("<h3>Danh sách quan hệ</h3><table><thead><tr><th>Từ</th><th>Cột</th>"
               "<th>Tới</th><th>Cột</th></tr></thead><tbody>")
    for t in tabs:
        for f in t["fks"]:
            erd.append(f"<tr><td><code>{e(t['name'])}</code></td>"
                       f"<td><code>{e(f['from'])}</code></td>"
                       f"<td><code>{e(f['table'])}</code></td>"
                       f"<td><code>{e(f['to'])}</code></td></tr>")
    erd.append("</tbody></table></section>")

    panels = "".join(table_panel(t, d["sample_n"]) for t in tabs)

    return (f"<!doctype html><html lang='vi'><head><meta charset='utf-8'>"
            f"<meta name='viewport' content='width=device-width,initial-scale=1'>"
            f"<title>Silver Layer — xem nhanh dữ liệu</title><style>{_CSS}</style>"
            f"</head><body>{''.join(nav)}<main>{''.join(ov)}{''.join(ch)}"
            f"{''.join(erd)}{panels}</main><div id='tip'></div>"
            f"<script>{_JS}</script></body></html>")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("db", nargs="?", default="silver.db")
    ap.add_argument("-o", "--out", default="data_preview.html")
    ap.add_argument("--sample", type=int, default=20)
    args = ap.parse_args()

    db = Path(args.db)
    if not db.exists():
        print(f"không thấy {db}", file=sys.stderr)
        return 2
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    print(f"  đọc {db} ({db.stat().st_size / 1e9:.2f} GB) …", flush=True)
    data = collect(conn, args.sample)
    conn.close()

    out = Path(args.out)
    out.write_text(build_html(data, db), encoding="utf-8")
    print(f"  {out}  ·  {out.stat().st_size / 1e6:.2f} MB  ·  "
          f"{len(data['tables'])} bảng  ·  {len(data['charts'])} biểu đồ")
    print(f"  mở bằng: open {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
