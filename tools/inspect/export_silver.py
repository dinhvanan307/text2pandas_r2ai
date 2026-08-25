"""Xuất tầng Silver ra dạng người đọc được: CSV cho Excel + trang HTML để duyệt.

Chạy:  PYTHONPATH=src python3 tools/inspect/export_silver.py
"""

from __future__ import annotations

import csv
import json
import random
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SILVER = ROOT / "data" / "silver" / "silver.sqlite"
OUT = ROOT / "data" / "silver" / "exports"
N_TABLES = 300
N_CELLS_PER_TABLE = 24

TILE_HELP = {
    "tables": "Mỗi bảng <table> trong corpus là một dòng ở table_features",
    "data_tables": "Bảng thật sự chứa số liệu — đã loại mục lục, nhân sự, danh sách công ty con",
    "cells": "Mỗi ô số đã parse thành công, giữ cả chuỗi gốc lẫn giá trị Decimal",
    "unit": "Bảng suy được đơn vị tính (từ nhãn cột, trong bảng, hoặc dòng phía trên)",
    "period": "Bảng gắn được ít nhất một cột với năm cụ thể",
    "labels": "Số nhãn chỉ tiêu khác nhau trên toàn corpus",
}


def q1(c, sql):
    return c.execute(sql).fetchone()[0]


def main() -> int:
    if not SILVER.exists():
        print(f"LỖI: không thấy {SILVER}", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(f"file:{SILVER}?mode=ro", uri=True)

    stats = {
        "tables": q1(c, "SELECT COUNT(*) FROM table_features"),
        "data_tables": q1(c, "SELECT COUNT(*) FROM table_features WHERE is_data_table=1"),
        "cells": q1(c, "SELECT COUNT(*) FROM cells"),
        "unit": q1(c, "SELECT COUNT(*) FROM table_features WHERE unit_source<>'default'"),
        "period": q1(c, "SELECT COUNT(*) FROM table_features WHERE years<>''"),
        "labels": q1(c, "SELECT COUNT(DISTINCT row_label) FROM cells"),
    }
    by_type = c.execute(
        "SELECT statement_type, COUNT(*) FROM table_features GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()
    by_unit = c.execute(
        "SELECT unit_source, COUNT(*) FROM table_features GROUP BY 1 ORDER BY 2 DESC"
    ).fetchall()

    # ── CSV cho Excel/Numbers ────────────────────────────────────────────────
    tf_cols = [r[1] for r in c.execute("PRAGMA table_info(table_features)")]
    with (OUT / "table_features_sample.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(tf_cols)
        w.writerows(c.execute("SELECT * FROM table_features ORDER BY doc_id, line_no LIMIT 5000"))

    cell_cols = [r[1] for r in c.execute("PRAGMA table_info(cells)")]
    with (OUT / "cells_sample.csv").open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(cell_cols)
        w.writerows(c.execute("SELECT * FROM cells ORDER BY doc_id, line_no, row_idx LIMIT 20000"))

    # ── mẫu để duyệt trên trang HTML ─────────────────────────────────────────
    pool = c.execute(
        "SELECT doc_id, line_no, ticker, doc_year, basis, statement_type,"
        " is_data_table, numeric_ratio, unit_exponent, unit_source, unit_raw,"
        " n_rows, n_cols, years, col_labels, context, flags"
        " FROM table_features WHERE is_data_table=1"
    ).fetchall()
    random.seed(42)
    sample = random.sample(pool, min(N_TABLES, len(pool)))

    rows = []
    for r in sample:
        cells = c.execute(
            "SELECT row_label, col_label, period_year, ma_so, value_raw, value"
            " FROM cells WHERE doc_id=? AND line_no=? ORDER BY row_idx, col_idx LIMIT ?",
            (r[0], r[1], N_CELLS_PER_TABLE),
        ).fetchall()
        n_all = c.execute(
            "SELECT COUNT(*) FROM cells WHERE doc_id=? AND line_no=?", (r[0], r[1])
        ).fetchone()[0]
        rows.append({
            "doc": r[0], "line": r[1], "tick": r[2], "yr": r[3], "basis": r[4],
            "type": r[5], "nr": r[11], "nc": r[12], "uexp": r[8], "usrc": r[9],
            "uraw": r[10] or "", "years": r[13], "cols": r[14] or "",
            "ctx": (r[15] or "")[:300], "flags": r[16] or "",
            "ncells": n_all, "cells": cells,
        })

    payload = {
        "stats": stats, "help": TILE_HELP,
        "by_type": by_type, "by_unit": by_unit, "rows": rows,
    }
    (OUT / "silver_explorer.html").write_text(
        HTML.replace("__DATA__", json.dumps(payload, ensure_ascii=False)),
        encoding="utf-8",
    )
    print(f"  ✓ {OUT/'table_features_sample.csv'}   (5.000 dòng)")
    print(f"  ✓ {OUT/'cells_sample.csv'}            (20.000 dòng)")
    print(f"  ✓ {OUT/'silver_explorer.html'}        ({len(rows)} bảng để duyệt)")
    return 0


HTML = r"""<!DOCTYPE html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Silver Explorer — Text2Pandas</title>
<style>
:root{color-scheme:light;
--surface-1:#fcfcfb; --plane:#f9f9f7;
--ink:#0b0b0b; --ink-2:#52514e; --muted:#898781;
--grid:#e1e0d9; --axis:#c3c2b7; --ring:rgba(11,11,11,.10);
--blue:#2a78d6; --blue-200:#9ec5f4; --good:#0ca30c; --warn:#fab219; --crit:#d03b3b;}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme=light])){
color-scheme:dark; --surface-1:#1a1a19; --plane:#0d0d0d;
--ink:#fff; --ink-2:#c3c2b7; --muted:#898781;
--grid:#2c2c2a; --axis:#383835; --ring:rgba(255,255,255,.10);
--blue:#3987e5; --blue-200:#184f95;}}
*{box-sizing:border-box}
body{margin:0;background:var(--plane);color:var(--ink);
font:14px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif;padding:28px 22px 60px}
.wrap{max-width:1180px;margin:0 auto}
h1{font-size:21px;margin:0 0 4px;letter-spacing:-.01em}
.sub{color:var(--ink-2);margin:0 0 22px;font-size:13px}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(168px,1fr));gap:10px;margin-bottom:24px}
.tile{background:var(--surface-1);border:1px solid var(--ring);border-radius:10px;padding:13px 14px}
.tile .v{font-size:25px;font-weight:600;letter-spacing:-.02em}
.tile .k{color:var(--ink-2);font-size:12px;margin-top:1px}
.tile .h{color:var(--muted);font-size:11px;margin-top:6px;line-height:1.4}
.panel{background:var(--surface-1);border:1px solid var(--ring);border-radius:10px;padding:16px 17px;margin-bottom:18px}
.panel h2{font-size:13px;margin:0 0 13px;color:var(--ink-2);font-weight:600;
text-transform:uppercase;letter-spacing:.05em}
.bar-row{display:grid;grid-template-columns:150px 1fr 84px;align-items:center;gap:10px;margin-bottom:5px}
.bar-lab{color:var(--ink-2);font-size:12.5px;text-align:right;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.bar-track{height:15px;background:var(--grid);border-radius:4px;overflow:hidden}
.bar-fill{height:100%;background:var(--blue);border-radius:0 4px 4px 0}
.bar-val{font-size:12.5px;color:var(--ink-2);font-variant-numeric:tabular-nums}
input[type=search]{width:100%;padding:9px 12px;border:1px solid var(--axis);border-radius:8px;
background:var(--surface-1);color:var(--ink);font:inherit;font-size:13.5px}
.hint{color:var(--muted);font-size:12px;margin:7px 0 0}
.cnt{color:var(--ink-2);font-size:12.5px;margin:11px 0 8px}
.card{background:var(--surface-1);border:1px solid var(--ring);border-radius:10px;
padding:13px 15px;margin-bottom:11px}
.card h3{margin:0 0 3px;font-size:13.5px;font-weight:600;word-break:break-all}
.meta{color:var(--ink-2);font-size:12px;margin-bottom:8px}
.chips{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:9px}
.chip{font-size:11px;padding:2px 8px;border-radius:20px;border:1px solid var(--ring);
color:var(--ink-2);background:var(--plane)}
.chip.f{border-color:var(--warn);color:var(--ink)}
.ctx{color:var(--ink-2);font-size:12px;background:var(--plane);padding:8px 10px;
border-radius:6px;border-left:2px solid var(--blue-200);margin-bottom:9px}
table{width:100%;border-collapse:collapse;font-size:12.5px}
th{text-align:left;color:var(--muted);font-weight:600;padding:4px 8px 5px;
border-bottom:1px solid var(--grid);white-space:nowrap;font-size:11.5px}
td{padding:3px 8px;border-bottom:1px solid var(--grid);vertical-align:top}
td.n{text-align:right;font-variant-numeric:tabular-nums;white-space:nowrap}
.more{color:var(--muted);font-size:11.5px;padding-top:6px}
details summary{cursor:pointer;color:var(--blue);font-size:12.5px;padding:2px 0}
</style></head><body><div class="wrap">
<h1>Silver Explorer</h1>
<p class="sub">Dữ liệu sau khi chuyển từ Bronze lên Silver — đặc trưng bảng và ô số đã chuẩn hoá.</p>
<div class="tiles" id="tiles"></div>
<div class="panel"><h2>Loại bảng</h2><div id="bt"></div></div>
<div class="panel"><h2>Nguồn suy ra đơn vị tính</h2><div id="bu"></div></div>
<div class="panel">
  <h2>Duyệt bảng</h2>
  <input type="search" id="q" placeholder="Gõ để lọc: mã CK, năm, loại bảng, nhãn chỉ tiêu…">
  <p class="hint">Ví dụ: <b>VJC</b> · <b>cash_flow</b> · <b>Lãi tiền gửi</b> · <b>2023</b> · <b>unit_assumed</b></p>
  <p class="cnt" id="cnt"></p><div id="list"></div>
</div></div>
<script>
const D=__DATA__;
const fmt=n=>n.toLocaleString('vi-VN');
const esc=s=>String(s??'').replace(/[&<>"]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[m]));
const T=[['tables','Bảng có đặc trưng'],['data_tables','Bảng dữ liệu'],['cells','Ô số đã parse'],
         ['unit','Bảng có đơn vị'],['period','Bảng có cột-kỳ'],['labels','Nhãn chỉ tiêu']];
document.getElementById('tiles').innerHTML=T.map(([k,lab])=>
 `<div class="tile"><div class="v">${fmt(D.stats[k])}</div><div class="k">${lab}</div>
  <div class="h">${esc(D.help[k])}</div></div>`).join('');
function bars(el,data){const mx=Math.max(...data.map(d=>d[1]));const tot=data.reduce((a,b)=>a+b[1],0);
 el.innerHTML=data.map(([k,v])=>`<div class="bar-row"><div class="bar-lab" title="${esc(k)}">${esc(k)}</div>
  <div class="bar-track"><div class="bar-fill" style="width:${(v/mx*100).toFixed(1)}%"></div></div>
  <div class="bar-val">${fmt(v)} · ${(v/tot*100).toFixed(1)}%</div></div>`).join('');}
bars(document.getElementById('bt'),D.by_type);
bars(document.getElementById('bu'),D.by_unit);
function card(r){
 const chips=[`<span class="chip">${esc(r.type)}</span>`,
  `<span class="chip">${r.nr}×${r.nc}</span>`,
  `<span class="chip">đơn vị 10^${r.uexp} · ${esc(r.usrc)}</span>`,
  r.years?`<span class="chip">năm ${esc(r.years)}</span>`:'',
  ...(r.flags?r.flags.split(',').filter(Boolean).map(f=>`<span class="chip f">⚠ ${esc(f)}</span>`):[])].join('');
 const rowsHtml=r.cells.map(c=>`<tr><td>${esc(c[0])}</td><td>${esc(c[1])}</td>
  <td class="n">${c[2]??'—'}</td><td class="n">${esc(c[3]||'—')}</td>
  <td class="n">${esc(c[4])}</td><td class="n">${esc(c[5])}</td></tr>`).join('');
 return `<div class="card"><h3>${esc(r.doc)}<span style="color:var(--muted)"> | dòng ${r.line}</span></h3>
  <div class="meta">${esc(r.tick)} · ${r.yr??'—'} · ${esc(r.basis||'không khai báo')} · ${fmt(r.ncells)} ô số</div>
  <div class="chips">${chips}</div>
  ${r.ctx?`<div class="ctx">${esc(r.ctx)}</div>`:''}
  <details><summary>Xem ${Math.min(r.cells.length,24)}/${fmt(r.ncells)} ô</summary>
   <table><thead><tr><th>row_label</th><th>col_label</th><th>năm</th><th>mã số</th>
   <th>value_raw</th><th>value</th></tr></thead><tbody>${rowsHtml}</tbody></table>
   ${r.ncells>r.cells.length?`<p class="more">… còn ${fmt(r.ncells-r.cells.length)} ô nữa trong silver.sqlite</p>`:''}
  </details></div>`;}
const list=document.getElementById('list'),cnt=document.getElementById('cnt'),q=document.getElementById('q');
function render(){const s=q.value.trim().toLowerCase();
 const hit=!s?D.rows:D.rows.filter(r=>(r.doc+' '+r.type+' '+r.tick+' '+r.yr+' '+r.years+' '+r.flags+' '+
  r.ctx+' '+r.cols+' '+r.cells.map(c=>c[0]).join(' ')).toLowerCase().includes(s));
 cnt.textContent=`${fmt(hit.length)} / ${fmt(D.rows.length)} bảng mẫu`;
 list.innerHTML=hit.slice(0,60).map(card).join('')||'<p class="hint">Không khớp bảng nào.</p>';}
q.addEventListener('input',render);render();
</script></body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
