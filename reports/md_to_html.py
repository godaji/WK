#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
위스키 가격 리포트 Markdown -> HTML 변환기 (CMPA-20)

reports/*.md (가격 리포트) 를 읽어 self-contained HTML 로 변환한다.
- 모든 표는 헤더 클릭으로 정렬 가능 (숫자/통화 인식 정렬)
- 외부 의존성 없음 (CSS/JS 인라인), 한 파일로 배포 가능

사용:
    python3 md_to_html.py reports/2026-05_위스키가격리포트_2026-05-30.md   # → 같은 이름 .html (날짜 박힘)
    python3 md_to_html.py <input.md> [output.html]

CMPA-45: 입력 MD 파일명에 실행일이 박혀 있으면 출력 HTML도 자동으로 날짜가 박힌다
(.md→.html). 즉 dated 입력 → dated 출력. 이 경우 _runs/ 스냅샷은 중복이라 건너뛴다.
날짜가 없는 입력(임시/수동)일 때만 CMPA-38 스냅샷을 남긴다.
"""
import os
import sys
import re
import html as _html

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from pipelines.common.dated import snapshot  # noqa: E402

# 파일명에 실행일(YYYY-MM-DD)/스냅샷 태그(__runYYYY-MM-DD)가 박혔거나, '_latest' 편의
# 포인터이면 _runs 스냅샷이 불필요(전자는 이미 정본 날짜본, 후자는 비정본 편의 사본).
_DATED_RX = re.compile(r"(?:__run)?\d{4}-\d{2}-\d{2}(?=\.[^.]+$)|_latest(?=\.[^.]+$)")


def is_dated(path):
    return bool(_DATED_RX.search(os.path.basename(path)))


def esc(s):
    return _html.escape(s, quote=True)


def render_inline(text):
    """인라인 마크다운: **bold**, `code`, 이스케이프 처리."""
    # 토큰 보호를 위해 먼저 코드 추출
    parts = []
    # `code`
    code_pat = re.compile(r"`([^`]+)`")
    bold_pat = re.compile(r"\*\*([^*]+)\*\*")

    def bold_repl(m):
        return "<strong>" + esc(m.group(1)) + "</strong>"

    # split out code spans first so their contents aren't bolded
    pos = 0
    out = []
    for m in code_pat.finditer(text):
        seg = text[pos:m.start()]
        seg = esc(seg)
        seg = re.sub(r"\*\*([^*]+)\*\*", lambda mm: "<strong>" + mm.group(1) + "</strong>", seg)
        out.append(seg)
        out.append("<code>" + esc(m.group(1)) + "</code>")
        pos = m.end()
    seg = esc(text[pos:])
    seg = re.sub(r"\*\*([^*]+)\*\*", lambda mm: "<strong>" + mm.group(1) + "</strong>", seg)
    out.append(seg)
    result = "".join(out)
    # 인라인 raw HTML 태그가 리터럴 텍스트(&lt;sub&gt; 등)로 보이지 않게 정리한다.
    # <sub>/<sup>: 태그만 제거하고 안의 글자는 일반 크기로 유지(보드 요청: sub 빼기).
    # <br>: 줄바꿈으로 복원.
    result = re.sub(r"&lt;/?(?:sub|sup)\s*&gt;", "", result, flags=re.I)
    result = re.sub(r"&lt;br\s*/?&gt;", "<br>", result, flags=re.I)
    # CMPA-54: 해외대비 배지(🇭🇰↓/🇯🇵↓)를 노란색 pill 로 강조한다(보드 요청: 이모지만으론
    # 눈에 안 들어옴). MD 토큰엔 색을 싣기 위해 🟡 가 앞에 붙는데, HTML pill 자체가 노란색이라
    # 여기선 선행 🟡 을 떼고 flag 만 pill 안에 넣는다(노란 점 + 노란 pill 중복 방지).
    # CMPA-234: 신라면세 대비 '면세↓' 배지도 동일 노란 pill 로 렌더.
    result = re.sub(r"🟡?(🇭🇰↓|🇯🇵↓|면세↓)", r'<span class="ovbadge">\1</span>', result)
    return result


def sort_key_attr(cell_text):
    """정렬용 값: 숫자(통화/퍼센트 포함)면 float, 아니면 원문 소문자."""
    t = cell_text.strip()
    # 숫자 추출 (₩, 콤마, %, 등 제거)
    cleaned = re.sub(r"[^\d.\-]", "", t)
    if cleaned not in ("", "-", ".", "-.") and re.search(r"\d", cleaned):
        try:
            return ("num", float(cleaned))
        except ValueError:
            pass
    if t in ("", "—", "-"):
        # 빈 값/대시는 정렬시 맨 뒤로
        return ("empty", "")
    return ("str", t.lower())


def split_row(line):
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|"):
        line = line[:-1]
    return [c.strip() for c in line.split("|")]


def is_sep_row(cells):
    return all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c != "")


def column_types(header, rows):
    """컬럼 정렬은 셀별이 아니라 '컬럼 단위'로 결정한다.
    비어있지 않은 데이터 셀 중 숫자 셀이 더 많으면 그 컬럼은 'num'(우측 정렬),
    아니면 'txt'(가운데 정렬). 이러면 '1792 스몰 배치'·'더 글랜 그란트 12년' 처럼
    이름 안에 숫자가 섞여도 같은 컬럼은 한 방향으로 정렬된다."""
    ncol = len(header)
    types = []
    for idx in range(ncol):
        num = other = 0
        for r in rows:
            if idx >= len(r):
                continue
            t = r[idx].strip()
            if t in ("", "—", "-"):
                continue
            # 숫자 셀 = 글자(한글/영문)가 전혀 없고, 숫자/통화기호/구분자만으로 이뤄진 값.
            # (이름 속 '12년' 같은 숫자에 흔들리지 않게: '글렌피딕 12년'은 한글이 남으므로 텍스트)
            residue = re.sub(r"[\d.,₩%\s\-\*★⚪()]", "", t)
            if residue == "" and re.search(r"\d", t):
                num += 1
            else:
                other += 1
        types.append("num" if num > other else "txt")
    return types


def render_table(header, rows, tid):
    coltypes = column_types(header, rows)
    th = []
    for idx, h in enumerate(header):
        cls = "col-num" if coltypes[idx] == "num" else "col-txt"
        th.append('<th scope="col" class="%s"><button class="sort-btn" type="button">'
                  % cls + render_inline(h) + '<span class="arrow"></span></button></th>')
    thead = "<thead><tr>" + "".join(th) + "</tr></thead>"

    body = []
    for r in rows:
        # pad/truncate to header length
        cells = (r + [""] * len(header))[:len(header)]
        tds = []
        for idx, c in enumerate(cells):
            cls = "col-num" if coltypes[idx] == "num" else "col-txt"
            t = c.strip()
            if t in ("", "—", "-"):
                tds.append('<td class="%s" data-type="empty" data-sort="">%s</td>'
                           % (cls, render_inline(c)))
            elif coltypes[idx] == "num":
                kind, val = sort_key_attr(c)
                if kind == "num":
                    tds.append('<td class="%s" data-type="num" data-sort="%s">%s</td>'
                               % (cls, val, render_inline(c)))
                else:  # 숫자 컬럼이지만 비정형 값 → 문자열 정렬로 폴백
                    tds.append('<td class="%s" data-type="str" data-sort="%s">%s</td>'
                               % (cls, esc(t.lower()), render_inline(c)))
            else:  # 텍스트 컬럼 → 항상 문자열 정렬 (이름 안 숫자에 흔들리지 않음)
                tds.append('<td class="%s" data-type="str" data-sort="%s">%s</td>'
                           % (cls, esc(t.lower()), render_inline(c)))
        body.append("<tr>" + "".join(tds) + "</tr>")
    tbody = "<tbody>" + "".join(body) + "</tbody>"

    return ('<div class="table-wrap"><table class="sortable" id="%s">%s%s</table>'
            '<p class="hint">↕ 헤더를 클릭하면 정렬됩니다. 다시 클릭하면 오름/내림 전환.</p></div>'
            % (tid, thead, tbody))


def convert(md):
    lines = md.split("\n")
    out = []
    i = 0
    n = len(lines)
    table_idx = 0
    para = []

    def flush_para():
        if para:
            txt = " ".join(p.strip() for p in para).strip()
            if txt:
                out.append("<p>" + render_inline(txt) + "</p>")
            para.clear()

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # table detection: a line with | followed by separator row
        if stripped.startswith("|") and i + 1 < n and "|" in lines[i + 1]:
            sep_cells = split_row(lines[i + 1])
            if is_sep_row(sep_cells):
                flush_para()
                header = split_row(stripped)
                rows = []
                j = i + 2
                while j < n and lines[j].strip().startswith("|"):
                    cells = split_row(lines[j])
                    if not is_sep_row(cells):
                        rows.append(cells)
                    j += 1
                table_idx += 1
                out.append(render_table(header, rows, "tbl%d" % table_idx))
                i = j
                continue

        # headings
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush_para()
            level = len(m.group(1))
            out.append("<h%d>%s</h%d>" % (level, render_inline(m.group(2)), level))
            i += 1
            continue

        # hr
        if re.fullmatch(r"-{3,}", stripped):
            flush_para()
            out.append("<hr>")
            i += 1
            continue

        # blockquote (collect consecutive)
        if stripped.startswith(">"):
            flush_para()
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                q = lines[i].strip()[1:].strip()
                quote.append(q)
                i += 1
            # 각 라인을 개별 <p> 로 (리포트의 > 라인은 항목별 의미가 있음)
            qhtml = []
            for q in quote:
                if q == "":
                    continue
                qhtml.append("<p>" + render_inline(q) + "</p>")
            out.append("<blockquote>" + "".join(qhtml) + "</blockquote>")
            continue

        # list item (simple, unordered "- ")
        if re.match(r"^[-*]\s+", stripped):
            flush_para()
            items = []
            while i < n and re.match(r"^[-*]\s+", lines[i].strip()):
                items.append(re.sub(r"^[-*]\s+", "", lines[i].strip()))
                i += 1
            out.append("<ul>" + "".join("<li>" + render_inline(it) + "</li>" for it in items) + "</ul>")
            continue

        # blank line
        if stripped == "":
            flush_para()
            i += 1
            continue

        para.append(line)
        i += 1

    flush_para()
    return "\n".join(out)


CSS = """
:root{--bg:#0f1115;--card:#171a21;--ink:#e8eaed;--muted:#9aa0aa;--line:#2a2f3a;
--accent:#e0a84e;--accent2:#7fd1b9;--row:#1b1f27;--rowalt:#161a21;--good:#7fd1b9;}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif;
line-height:1.6;font-size:15px}
.container{max-width:1180px;margin:0 auto;padding:32px 20px 80px}
html,body{overflow-x:hidden}
h1{font-size:1.9rem;margin:.2em 0 .4em;border-bottom:2px solid var(--accent);padding-bottom:.3em}
h2{font-size:1.35rem;margin:1.6em 0 .5em;color:var(--accent)}
h3{font-size:1.1rem;margin:1.3em 0 .4em;color:var(--accent2)}
a{color:var(--accent2)}
hr{border:0;border-top:1px solid var(--line);margin:1.8em 0}
blockquote{margin:1em 0;padding:.6em 1em;background:var(--card);
border-left:3px solid var(--accent);border-radius:6px;color:var(--muted);font-size:.93rem}
blockquote p{margin:.35em 0}
code{background:#22262f;padding:.1em .4em;border-radius:4px;font-size:.88em;color:var(--accent2)}
strong{color:#fff}
ul{margin:.6em 0 .6em 1.2em}
.table-wrap{width:100vw;position:relative;left:50%;right:50%;margin:1em -50vw;
padding:0 24px;overflow-x:auto;background:var(--card);
border-top:1px solid var(--line);border-bottom:1px solid var(--line)}
table.sortable{border-collapse:collapse;width:100%;font-size:.9rem}
table.sortable th,table.sortable td{padding:9px 12px;border-bottom:1px solid var(--line);
white-space:nowrap}
/* 정렬(가로 방향)은 컬럼 단위로 일관 적용: 숫자=우측, 텍스트=가운데 */
table.sortable .col-num{text-align:right;font-variant-numeric:tabular-nums}
table.sortable .col-txt{text-align:center}
table.sortable thead th{position:sticky;top:0;background:#1f242e;z-index:1}
table.sortable tbody tr:nth-child(odd){background:var(--rowalt)}
table.sortable tbody tr:nth-child(even){background:var(--row)}
table.sortable tbody tr:hover{background:#222835}
.sort-btn{all:unset;cursor:pointer;font-weight:600;color:var(--ink);display:inline-flex;
align-items:center;gap:5px;width:100%}
.col-num .sort-btn{justify-content:flex-end}
.col-txt .sort-btn{justify-content:center}
.sort-btn:hover{color:var(--accent)}
.sort-btn .arrow{font-size:.7em;color:var(--muted);min-width:1em}
th[aria-sort="ascending"] .arrow::after{content:"▲";color:var(--accent)}
th[aria-sort="descending"] .arrow::after{content:"▼";color:var(--accent)}
.hint{margin:.4em 12px .7em;font-size:.78rem;color:var(--muted)}
.report-meta{font-size:.82rem;color:var(--muted);margin-top:2em}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:.6em 0}
.toolbar input{background:#22262f;border:1px solid var(--line);color:var(--ink);
padding:7px 10px;border-radius:6px;font-size:.9rem;min-width:220px}
.toolbar input::placeholder{color:var(--muted)}
/* CMPA-54: 해외대비 배지 — 노란색 하이라이트(보드 요청: 잘 보이게) */
.ovbadge{display:inline-block;background:#ffd400;color:#181818;font-weight:800;
border-radius:5px;padding:0 6px;margin-left:4px;font-size:.82em;line-height:1.55;
white-space:nowrap;vertical-align:middle;box-shadow:0 0 0 1px rgba(0,0,0,.25)}
"""

JS = """
(function(){
  function val(td){
    var d=td.getAttribute('data-sort');
    if(td.getAttribute('data-type')==='num'){var f=parseFloat(d);return isNaN(f)?null:f;}
    if(td.getAttribute('data-type')==='empty')return null;
    return (d||'').toString();
  }
  function sortTable(table,colIdx,dir){
    var tbody=table.tBodies[0];
    var rows=Array.prototype.slice.call(tbody.rows);
    rows.sort(function(a,b){
      var av=val(a.cells[colIdx]),bv=val(b.cells[colIdx]);
      // 빈 값/대시는 항상 맨 뒤
      var ae=(av===null),be=(bv===null);
      if(ae&&be)return 0; if(ae)return 1; if(be)return -1;
      var r;
      if(typeof av==='number'&&typeof bv==='number')r=av-bv;
      else r=String(av).localeCompare(String(bv),'ko');
      return dir==='asc'?r:-r;
    });
    rows.forEach(function(r){tbody.appendChild(r);});
  }
  document.querySelectorAll('table.sortable').forEach(function(table){
    var ths=table.tHead.rows[0].cells;
    Array.prototype.forEach.call(ths,function(th,idx){
      var btn=th.querySelector('.sort-btn'); if(!btn)return;
      btn.addEventListener('click',function(){
        var cur=th.getAttribute('aria-sort');
        var dir=(cur==='ascending')?'descending':'ascending';
        Array.prototype.forEach.call(ths,function(o){o.removeAttribute('aria-sort');});
        th.setAttribute('aria-sort',dir);
        sortTable(table,idx,dir==='ascending'?'asc':'desc');
      });
    });
  });
  // 핵심표(첫 표) 검색 필터
  var core=document.getElementById('tbl1');
  if(core){
    var bar=document.createElement('div');bar.className='toolbar';
    var inp=document.createElement('input');
    inp.type='search';inp.placeholder='\\uD83D\\uDD0D \\uD575\\uC2EC\\uD45C \\uAC80\\uC0C9 (\\uC704\\uC2A4\\uD0A4\\uBA85\\u00B7\\uC720\\uD615\\u00B7\\uD310\\uB9E4\\uCC98)';
    bar.appendChild(inp);
    core.parentNode.parentNode.insertBefore(bar,core.parentNode);
    inp.addEventListener('input',function(){
      var q=inp.value.trim().toLowerCase();
      Array.prototype.forEach.call(core.tBodies[0].rows,function(r){
        r.style.display=(r.textContent.toLowerCase().indexOf(q)>=0)?'':'none';
      });
    });
  }
})();
"""


def build_html(title, body):
    return ("<!DOCTYPE html>\n<html lang=\"ko\">\n<head>\n"
            "<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            "<title>%s</title>\n<style>%s</style>\n</head>\n<body>\n"
            "<div class=\"container\">\n%s\n</div>\n<script>%s</script>\n</body>\n</html>\n"
            % (esc(title), CSS, body, JS))


def main():
    if len(sys.argv) < 2:
        print("usage: python3 md_to_html.py <input.md> [output.html]", file=sys.stderr)
        sys.exit(1)
    inp = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else re.sub(r"\.md$", ".html", inp)
    with open(inp, encoding="utf-8") as f:
        md = f.read()
    # title = first heading
    m = re.search(r"^#\s+(.*)$", md, re.M)
    title = re.sub(r"[#*`>🥃🎯📐🛒🌏🗓️]", "", m.group(1)).strip() if m else "위스키 가격 리포트"
    body = convert(md)
    htmlout = build_html(title, body)
    with open(out, "w", encoding="utf-8") as f:
        f.write(htmlout)
    print("wrote", out, "(%d bytes)" % len(htmlout.encode("utf-8")))
    # CMPA-45: 출력명이 이미 날짜 박힌 정본이면(dated 입력→dated 출력) _runs 스냅샷은 중복 → 생략.
    # 날짜 없는 입력일 때만 CMPA-38 스냅샷으로 누적 추적을 남긴다.
    if is_dated(out):
        print("dated/latest output — _runs snapshot skipped (canonical name already carries run-date, or is a _latest pointer)")
    else:
        snap = snapshot(out)
        if snap:
            print("snapshot", snap)


if __name__ == "__main__":
    main()
