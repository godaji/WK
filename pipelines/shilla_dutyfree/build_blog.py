#!/usr/bin/env python3
"""Code, Cask & Cabin 면세 가격변동 블로그 — 정적 페이지 빌더 (CMPA-176, Phase-1).

detect_price_changes.py(CMPA-168)가 만드는 `가격변동_<직전>_to_<최신>.md` 들을
**공개용 블로그 콘텐츠**(정적 HTML)로 변환한다. 베이스(월초 본편) 1 + 패치 N 구조이며
패치는 날짜별로 누적(덮어쓰지 않음, CMPA-33/156 아카이브 원칙).

설계 — 왜 md를 파싱하나:
  detector md 는 이미 (a) 양쪽 수집일, (b) '수집일 기준값' 면책문구(CMPA-156),
  (c) 변동 표 + **데일리샷 국내 최저가 floor**(CMPA-138/141 출처)를 담고 있다.
  md 는 정본 산출물로 reports/ 에 누적 보존된다. 따라서 md 만 읽으면
  **무네트워크·결정론**으로 공개판을 만들 수 있다 — build_deploy / --dry-run 안전.
  (라이브 floor 조회 같은 네트워크는 detector 루틴이 담당, 렌더는 분리.)

'국내최저 돌파' = 현재 KRW < 데일리샷 국내최저가. 최강 헤드라인이라 톱으로 정렬·강조.
케이던스는 하이브리드(평시 주간 다이제스트, 돌파 발생 시 즉시 패치) — 임계치는
CONFIG 로 분리해 후 조정 가능.

산출물(기본): deploy/blog/  ── 기존 deploy 아카이브 컨벤션 재사용(CMPA-176 CEO 확정):
  - index.html              블로그 홈 = 최신호(베이스). 이달의 본편(면세위스키 리포트)을
                            3C 아이덴티티로 래핑 + 패치 아카이브 네비를 주입(최신순).
  - <YYMMDD>/index.html     각 가격 패치 = 날짜별 영구 아카이브(패치 누적, 덮어쓰지 않음).
                            YYMMDD = 패치 최신 수집일. build_deploy EDITIONS 와 동일 폴더 규약.
새 아카이브 로직을 만들지 않는다 — index.html=최신, <YYMMDD>/index.html=영구 스냅샷.

게이트: 내부 스테이징만. 외부 발행 금지(c7405e7d).

사용법:
  python3 pipelines/shilla_dutyfree/build_blog.py            # deploy/blog/ 에 빌드
  python3 pipelines/shilla_dutyfree/build_blog.py --out DIR  # 다른 경로로
  python3 pipelines/shilla_dutyfree/build_blog.py --selftest # 픽스처 자가검증
  python3 pipelines/shilla_dutyfree/build_blog.py --dry-run  # 무네트워크·결정론 회귀0 증명
"""
from __future__ import annotations

import argparse
import glob
import html
import os
import re
import sys

import brand  # 같은 디렉터리(스크립트 실행 시 sys.path[0])

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from pipelines.common.whisky_quality import is_undersized_by_name  # CMPA-733

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
REPORT_DIR = os.path.join(ROOT, "reports", "shilla-dutyfree")
DEFAULT_OUT = os.path.join(ROOT, "deploy", "blog")

# ── 케이던스/임계치 (후 조정 가능하게 분리) ──────────────────────────
CONFIG = {
    # 하이브리드: 평시 주간 다이제스트로 묶고, 국내최저 돌파 발생 시 즉시 패치.
    "cadence": "hybrid",
    # 국내최저 돌파가 1건이라도 있으면 즉시 패치(최강 헤드라인).
    "instant_on_breakthrough": True,
    # 의미있는 인하(할인율 +Npp 이상)가 이 건수 이상이면 돌파 없이도 즉시 패치.
    "meaningful_discount_delta_pp": 5.0,
    "instant_drop_count": 3,
    # 표시 노이즈 컷(할인율 변동 |Δ| 이 값 미만은 '의미있는 인하'에서 제외).
    "min_display_delta_pp": 0.1,
}

PATCH_RE = re.compile(r"^가격변동_(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})\.md$")
BASE_RE = re.compile(r"^면세위스키_리포트_(\d{4}-\d{2}-\d{2})\.html$")


# ── 파싱 헬퍼 ────────────────────────────────────────────────────────
def _num(s):
    """'₩256,161' / '$170.00' / '50.0%' → float. 빈칸/—/None → None.
    CMPA-334: 셀에 마크다운 링크([₩119,400 ...](url)·' [🔗데일리샷](url)' 등)가 섞여도
    링크 타깃의 숫자(URL의 id)에 오염되지 않게 링크 URL을 먼저 제거하고 선두 숫자만 취한다."""
    if s is None:
        return None
    t = re.sub(r"\]\([^)]*\)", "", str(s))      # 마크다운 링크 타깃(URL) 제거
    t = re.sub(r"[₩$,%\s]", "", t).replace("−", "-")
    m = re.search(r"-?\d[\d.]*", t)             # 선두 (부호포함) 숫자 토큰
    if not m:
        return None
    try:
        return float(m.group(0))
    except ValueError:
        return None


def _cell_url(s):
    """셀 안 마크다운 링크의 URL 추출(없으면 None). CMPA-334 데일리샷 링크."""
    if not s:
        return None
    m = re.search(r"\]\((https?://[^)]+)\)", str(s))
    return m.group(1) if m else None


def _parse_table(lines, i):
    """lines[i] 가 헤더 행(`| ... |`)일 때 표를 dict 리스트로 파싱.
    반환: (rows, next_index). 헤더가 아니면 ([], i)."""
    if i >= len(lines) or "|" not in lines[i]:
        return [], i
    headers = [c.strip() for c in lines[i].strip().strip("|").split("|")]
    j = i + 1
    if j < len(lines) and set(lines[j].strip()) <= set("|-: "):  # 구분선
        j += 1
    rows = []
    while j < len(lines) and lines[j].lstrip().startswith("|"):
        cells = [c.strip() for c in lines[j].strip().strip("|").split("|")]
        if len(cells) == len(headers):
            rows.append(dict(zip(headers, cells)))
        j += 1
    return rows, j


def parse_patch_md(path):
    """detector md → 구조화 dict."""
    text = open(path, encoding="utf-8").read()
    lines = text.splitlines()
    fname = os.path.basename(path)
    m = PATCH_RE.match(fname)
    prev_fb, latest_fb = (m.group(1), m.group(2)) if m else ("", "")

    def grab(pat):
        mm = re.search(pat, text)
        return mm.group(1).strip() if mm else None

    prev_date = grab(r"직전 스냅샷 수집일:\*\*\s*(\d{4}-\d{2}-\d{2})") or prev_fb
    latest_date = grab(r"최신 스냅샷 수집일:\*\*\s*(\d{4}-\d{2}-\d{2})") or latest_fb
    fx = grab(r"현재 환율\(USD→KRW\):\*\*\s*(.+)")
    disclaimer = next((ln.lstrip("> ").strip() for ln in lines
                       if ln.lstrip().startswith(">")), None)
    # 푸터 면책(국내최저가 정의/인디 가드) — 마지막 '---' 뒤 italic 라인.
    # CMPA-334: 컬럼이 '데일리샷 최저가'→'국내최저가'로 바뀜. 둘 다 인식(과거 글 호환).
    footer_note = next((ln.strip().strip("_") for ln in lines
                        if ("국내최저가 =" in ln or "데일리샷 최저가 =" in ln)), None)

    sections = {"price": [], "rate": [], "new": [], "removed": []}
    i = 0
    cur = None
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("## 가격(할인가"):
            cur = "price"
        elif ln.startswith("## 할인율만 변동"):
            cur = "rate"
        elif ln.startswith("## 신규"):
            cur = "new"
        elif ln.startswith("## 삭제"):
            cur = "removed"
        elif ln.lstrip().startswith("|") and cur:
            rows, i = _parse_table(lines, i)
            sections[cur] = rows
            cur = None
            continue
        i += 1

    return {
        "prev_date": prev_date, "latest_date": latest_date, "fx": fx,
        "disclaimer": disclaimer, "footer_note": footer_note,
        "sections": sections, "src": fname,
    }


def _name_key(row):
    return row.get("위스키명") or row.get("이름") or ""


def classify_patch(parsed, cfg=CONFIG):
    """돌파/의미있는 인하 분류 + 케이던스 판정. parsed 를 in-place 보강해 반환."""
    breakthroughs, drops, others = [], [], []
    for r in parsed["sections"]["price"]:
        krw = _num(r.get("현재 KRW"))
        # CMPA-334: 통합 국내최저가 컬럼(과거 글은 '데일리샷 최저가' — 폴백).
        floor_cell = r.get("국내최저가") or r.get("데일리샷 최저가")
        floor = _num(floor_cell)
        l_rate = _num(r.get("현재 할인율"))
        p_rate = _num(r.get("직전 할인율"))
        d_rate = (l_rate - p_rate) if (l_rate is not None and p_rate is not None) else None
        rec = {
            "name": _name_key(r), "usd": _num(r.get("현재 USD")),
            "krw": krw, "floor": floor, "floor_url": _cell_url(floor_cell),
            "l_rate": l_rate, "p_rate": p_rate,
            "d_rate": d_rate,
            "save": (floor - krw) if (krw is not None and floor is not None) else None,
        }
        # CMPA-733: 500ml 미만 소용량은 면세가/국내가 용량 불일치 → 제외
        if is_undersized_by_name(rec["name"]):
            continue
        is_break = krw is not None and floor is not None and krw < floor
        is_drop = (d_rate is not None
                   and d_rate >= cfg["meaningful_discount_delta_pp"])
        if is_break:
            breakthroughs.append(rec)
        elif is_drop:
            drops.append(rec)
        else:
            others.append(rec)

    breakthroughs.sort(key=lambda x: (-(x["save"] or 0), x["name"]))
    drops.sort(key=lambda x: (-(x["d_rate"] or 0), x["name"]))

    instant = ((cfg["instant_on_breakthrough"] and breakthroughs)
               or len(drops) >= cfg["instant_drop_count"])
    parsed["breakthroughs"] = breakthroughs
    parsed["drops"] = drops
    parsed["others"] = others
    parsed["cadence"] = "instant" if instant else "digest"
    return parsed


# ── 렌더링 ───────────────────────────────────────────────────────────
def _fmt_krw(v):
    return f"₩{v:,.0f}" if v is not None else "—"


def _fmt_pct(v):
    return f"{v:.1f}%" if v is not None else "—"


def _hero_card(r):
    save = r["save"]
    pct = (save / r["floor"] * 100) if (save and r["floor"]) else None
    save_txt = ""
    if save is not None:
        save_txt = (f'<span class="save">국내최저 대비 −{_fmt_krw(save)}'
                    + (f" ({pct:.0f}%↓)" if pct is not None else "") + "</span>")
    return (
        '<div class="card hero">'
        f'<div class="n">🏆 {html.escape(r["name"])}</div>'
        '<div class="row">'
        f'<span class="price">{_fmt_krw(r["krw"])}</span>'
        f'<span class="floor">국내최저 {_fmt_krw(r["floor"])}</span>'
        f'{save_txt}</div>'
        f'<div class="meta">현재 할인율 {_fmt_pct(r["l_rate"])} '
        f'(직전 {_fmt_pct(r["p_rate"])})</div>'
        '</div>'
    )


def _drop_card(r):
    dd = r["d_rate"]
    dd_txt = f'<span class="save">할인율 +{dd:.1f}%p</span>' if dd is not None else ""
    return (
        '<div class="card">'
        f'<div class="n">{html.escape(r["name"])}</div>'
        '<div class="row">'
        f'<span class="price">{_fmt_krw(r["krw"])}</span>'
        f'{dd_txt}</div>'
        f'<div class="meta">현재 할인율 {_fmt_pct(r["l_rate"])} '
        f'(직전 {_fmt_pct(r["p_rate"])})'
        + (f' · 국내최저 {_fmt_krw(r["floor"])}' if r["floor"] is not None else "")
        + '</div></div>'
    )


def render_patch_html(parsed):
    p = parsed
    bks, drops = p["breakthroughs"], p["drops"]
    title = f'가격 패치 — {p["latest_date"]}'
    cad = p["cadence"]
    badge = ('<span class="badge instant">⚡ 즉시 패치 · 국내최저 돌파</span>'
             if cad == "instant"
             else '<span class="badge digest">🗓️ 주간 다이제스트</span>')

    # 패치는 deploy/blog/<YYMMDD>/index.html — 홈은 한 단계 위.
    inner = [f'<a class="back" href="../index.html">← 블로그 홈 (이달의 본편)</a>']
    inner.append(f'<h1 style="font-size:20px;margin:14px 0 4px">{html.escape(title)}</h1>')
    inner.append(f'<div class="meta">직전 {p["prev_date"]} → 최신 {p["latest_date"]}'
                 + (f' · 환율 {html.escape(p["fx"])}' if p["fx"] else "") + '</div>')
    inner.append(f'<div style="margin:8px 0">{badge}</div>')
    if p["disclaimer"]:  # CMPA-156 '수집일 기준값' 면책 — 반드시 보존
        inner.append(f'<div class="note">{html.escape(p["disclaimer"])}</div>')

    inner.append('<h2>🏆 국내최저 돌파 — 면세가가 국내 최저가보다 싸다</h2>')
    if bks:
        inner.extend(_hero_card(r) for r in bks)
    else:
        inner.append('<div class="empty">이번 패치엔 국내최저 돌파 항목이 없습니다.</div>')

    if drops:
        inner.append('<h2>📉 이번 주 의미있는 인하</h2>')
        inner.extend(_drop_card(r) for r in drops)

    new = p["sections"]["new"]
    removed = p["sections"]["removed"]
    if new:
        inner.append(f'<h2>🆕 신규 입고 ({len(new)})</h2><ul class="list">')
        for r in new:
            inner.append(f'<li>{html.escape(_name_key(r))} '
                         f'<span class="meta">{html.escape(r.get("현재 KRW","") or "")}</span></li>')
        inner.append('</ul>')
    if removed:
        inner.append(f'<h2>📦 품절/내림 ({len(removed)})</h2><ul class="list">')
        for r in removed:
            inner.append(f'<li>{html.escape(_name_key(r))}</li>')
        inner.append('</ul>')

    if p["footer_note"]:
        inner.append(f'<div class="meta" style="margin-top:22px">_{html.escape(p["footer_note"])}_</div>')
    inner.append(f'<div class="meta">출처: detect_price_changes.py (CMPA-168) · '
                 f'{p["prev_date"]} → {p["latest_date"]}</div>')

    desc = (f'면세 위스키 가격 패치 {p["latest_date"]} — 국내최저 돌파 {len(bks)}건. '
            + brand.NAME_EN)
    return brand.page_shell(title, "\n".join(inner), description=desc)


def render_index_html(base_meta, patches):
    """블로그 홈(커버): 이달의 본편 + 패치 아카이브(최신순)."""
    inner = [f'<p class="sub" style="text-align:center;margin-top:14px">'
             f'{html.escape(brand.ABOUT)}</p>']

    inner.append('<h2>📖 이달의 본편</h2>')
    if base_meta:
        inner.append('<ul class="list">'
                     f'<li><span class="when">{base_meta["date"]}</span> · '
                     f'<a href="{base_meta["file"]}">면세 위스키, 진짜 싼 것만 골랐다 '
                     f'— 가성비 큐레이션 본편</a></li></ul>')
    else:
        inner.append('<div class="empty">아직 본편이 없습니다.</div>')

    inner.append('<h2>🗞️ 가격 패치 아카이브</h2>')
    if patches:
        inner.append('<ul class="list">')
        for pm in patches:
            tag = ('<span class="badge instant">⚡ 돌파</span>'
                   if pm["cadence"] == "instant"
                   else '<span class="badge digest">다이제스트</span>')
            bk = f' · 국내최저 돌파 {pm["breaks"]}건' if pm["breaks"] else ""
            inner.append(
                f'<li><span class="when">{pm["latest_date"]}</span> '
                f'<a href="{pm["href"]}">가격 패치 (직전 {pm["prev_date"]} 대비)</a> '
                f'{tag}<span class="meta">{bk}</span></li>')
        inner.append('</ul>')
    else:
        inner.append('<div class="empty">아직 패치가 없습니다.</div>')

    return brand.page_shell("면세 위스키 가격변동 블로그", "\n".join(inner))


def render_base_patch_nav(patches):
    """베이스(index.html)에 주입하는 '가격 패치 아카이브' 네비 — 각 <YYMMDD>/index.html 링크.
    ccc-nav 스타일은 brand.base_wrap_masthead() <style> 에 정의돼 있다."""
    out = ['<div class="ccc-nav">', '<h2>🗞️ 가격 패치 아카이브</h2>']
    if patches:
        out.append('<ul>')
        for pm in patches:
            tag = ('<span class="b i">⚡ 돌파</span>' if pm["cadence"] == "instant"
                   else '<span class="b d">다이제스트</span>')
            bk = f' · 국내최저 돌파 {pm["breaks"]}건' if pm["breaks"] else ""
            out.append(
                f'<li><span class="when">{pm["latest_date"]}</span>'
                f'<a href="{pm["href"]}">가격 패치 (직전 {pm["prev_date"]} 대비)</a>'
                f'{tag}<span class="m">{bk}</span></li>')
        out.append('</ul>')
    else:
        out.append('<div class="empty">아직 패치가 없습니다.</div>')
    out.append('</div>')
    return "\n".join(out)


def wrap_base_report(base_html_path, patches):
    """기존 면세 리포트 HTML 을 3C 아이덴티티로 래핑(원본 비파괴) + 패치 아카이브 네비 주입.
    이 결과가 deploy/blog/index.html (= 최신호/베이스/홈) 이 된다."""
    src = open(base_html_path, encoding="utf-8").read()
    # 외부 비발행 가드(c7405e7d): 베이스도 patch 와 동일하게 noindex 보장(방어적).
    if "noindex" not in src and "</head>" in src:
        src = src.replace(
            "</head>", '<meta name="robots" content="noindex,nofollow">\n</head>', 1)
    if "<body>" in src:
        # 마스트헤드 + '가격 패치 아카이브' 네비를 <body> 바로 뒤에 끼운다.
        head = brand.base_wrap_masthead() + render_base_patch_nav(patches)
        src = src.replace("<body>", "<body>\n" + head, 1)
    if "</body>" in src:
        src = src.replace("</body>", brand.base_wrap_footer() + "\n</body>", 1)
    return src


# ── 빌드 ─────────────────────────────────────────────────────────────
def _latest_base(report_dir=REPORT_DIR):
    files = []
    for p in glob.glob(os.path.join(report_dir, "면세위스키_리포트_*.html")):
        m = BASE_RE.match(os.path.basename(p))
        if m:
            files.append((m.group(1), p))
    files.sort()
    return files[-1] if files else None


def _all_patch_mds(report_dir=REPORT_DIR):
    out = []
    for p in sorted(glob.glob(os.path.join(report_dir, "가격변동_*.md"))):
        if PATCH_RE.match(os.path.basename(p)):
            out.append(p)
    return out


def is_noop_patch(parsed):
    """변동 0건(가격·할인율·신규·삭제 전부 빈) 패치인지 — 멱등 게이트(CMPA-156/250).

    detect_price_changes.py 는 변동이 없어도 '_변동 없음._' 리포트를 항상 쓴다.
    그런 no-op 리포트로는 빈/중복 블로그 글을 만들지 않는다(데이터 3원칙). 빌더와
    오케스트레이터가 같은 판정을 쓰도록 단일 소스로 둔다."""
    sec = parsed.get("sections", {})
    return not any(sec.get(k) for k in ("price", "rate", "new", "removed"))


def _yymmdd(date_str):
    """'2026-06-07' → '260607' (build_deploy EDITIONS 폴더 규약과 동일)."""
    return date_str[2:4] + date_str[5:7] + date_str[8:10]


def build(out_dir=DEFAULT_OUT, report_dir=REPORT_DIR):
    """블로그 정적 페이지를 out_dir 에 결정론적으로 (재)생성.

    구조(기존 deploy 아카이브 컨벤션 재사용 — CEO 확정):
      out_dir/index.html          = 최신호(베이스): 본편 래핑 + 패치 아카이브 네비
      out_dir/<YYMMDD>/index.html = 각 가격 패치(날짜별 영구 아카이브, 누적)
    누적은 reports/ 의 md 가 담당하므로 매번 전부 재생성해도 byte-identical."""
    written = []
    os.makedirs(out_dir, exist_ok=True)
    # 우리가 소유하는 산출물만 정리(결정론): 루트 index.html + 날짜(YYMMDD) 폴더.
    root_index = os.path.join(out_dir, "index.html")
    if os.path.exists(root_index):
        os.remove(root_index)
    for d in glob.glob(os.path.join(out_dir, "*")):
        if os.path.isdir(d) and re.fullmatch(r"\d{6}", os.path.basename(d)):
            for f in glob.glob(os.path.join(d, "*")):
                os.remove(f)
            os.rmdir(d)

    # 패치 → <YYMMDD>/index.html (날짜별 영구 아카이브)
    patches = []
    for md in _all_patch_mds(report_dir):
        parsed = parse_patch_md(md)
        if is_noop_patch(parsed):   # 멱등(CMPA-250): 변동 0건 리포트는 글 생성 안 함.
            print(f"  no-op(변동 0건) → 패치 글 생략: {os.path.basename(md)}")
            continue
        parsed = classify_patch(parsed)
        ymd = _yymmdd(parsed["latest_date"])
        date_dir = os.path.join(out_dir, ymd)
        os.makedirs(date_dir, exist_ok=True)
        with open(os.path.join(date_dir, "index.html"), "w", encoding="utf-8") as fh:
            fh.write(render_patch_html(parsed))
        patches.append({
            "latest_date": parsed["latest_date"], "prev_date": parsed["prev_date"],
            "yymmdd": ymd, "href": f"{ymd}/index.html", "cadence": parsed["cadence"],
            "breaks": len(parsed["breakthroughs"]),
        })
        written.append(f"{ymd}/index.html")
    patches.sort(key=lambda x: x["latest_date"], reverse=True)

    # 홈(index.html) = 최신호(베이스). 본편이 있으면 래핑+네비, 없으면 커버 폴백.
    base = _latest_base(report_dir)
    base_meta = None
    if base:
        date, path = base
        with open(root_index, "w", encoding="utf-8") as fh:
            fh.write(wrap_base_report(path, patches))
        base_meta = {"date": date}
    else:
        with open(root_index, "w", encoding="utf-8") as fh:
            fh.write(render_index_html(None, patches))
    written.append("index.html")
    return {"out": out_dir, "base": base_meta, "patches": patches, "written": written}


# ── 자가검증 / dry-run ───────────────────────────────────────────────
_FIXTURE_MD = """# 신라면세 위스키 가격변동 리포트 (달러기준)

- **직전 스냅샷 수집일:** 2026-06-06 (위스키 656종)
- **최신 스냅샷 수집일:** 2026-06-07 (위스키 656종)
- **현재 환율(USD→KRW):** ₩1,506.83 (기준일 2026-06-01)
- **조인 키:** 상품코드 · **가격 기준:** USD

> 수집 날짜는 데이터 신뢰성의 1차 신호입니다. 아래 가격은 각 스냅샷 **수집일 기준값**이며, 변동은 두 수집일 사이의 차이입니다.

## 요약

- 가격(할인가_USD) 변동: **3건** (상승 1 · 하락 2)
- 할인율만 변동(가격 동일): **0건**
- 신규 상품: **0건**
- 삭제(사라진) 상품: **0건**

## 가격(할인가_USD) 변동 — 변동폭 큰 순

| 위스키명 | 현재 USD | 현재 할인율 | 직전 할인율 | 현재 KRW | 데일리샷 최저가 |
|---|---:|---:|---:|---:|---:|
| 더 글렌그란트 21년 700ml | $170.00 | 50.0% | 20.0% | ₩256,161 | ₩359,000 |
| 시그나토리 글렌그란트 1995 CS 30년 #88231 700ml | $420.00 | 25.0% | 10.0% | ₩632,868 |  |
| 시그나토리 쿨일라 2007 캐스크 스트렝스 17년 #3 700ml | $304.00 | 5.0% | 30.0% | ₩458,076 |  |

## 할인율만 변동 (할인가_USD 동일) — 변동폭 큰 순

_변동 없음._

## 신규 상품 (0건) — 가격 높은 순

_없음._

## 삭제(사라진) 상품 (0건) — 가격 높은 순

_없음._

---
_데일리샷 최저가 = 데일리샷 국내 소매가(면세·해외 리스팅 제외) 브랜드+숙성 근사매칭 · 매칭 실패/인디·싱글캐스크는 비움._
_생성: detect_price_changes.py (CMPA-168) · 2026-06-06 → 2026-06-07_
"""


def selftest():
    import tempfile
    fails = []

    def check(cond, msg):
        print(("  ✓ " if cond else "  ✗ ") + msg)
        if not cond:
            fails.append(msg)

    with tempfile.TemporaryDirectory() as td:
        mdp = os.path.join(td, "가격변동_2026-06-06_to_2026-06-07.md")
        open(mdp, "w", encoding="utf-8").write(_FIXTURE_MD)
        parsed = classify_patch(parse_patch_md(mdp))

        check(parsed["prev_date"] == "2026-06-06"
              and parsed["latest_date"] == "2026-06-07", "양쪽 수집일 파싱")
        check(len(parsed["sections"]["price"]) == 3, "가격변동 표 3행 파싱")
        bks = parsed["breakthroughs"]
        check(len(bks) == 1 and bks[0]["name"].startswith("더 글렌그란트"),
              "국내최저 돌파 1건 검출(₩256,161 < ₩359,000)")
        check(bks[0]["save"] == 359000 - 256161, "절감액 계산 정확")
        check(parsed["cadence"] == "instant", "돌파 발생 → 즉시 패치 케이던스")
        # 시그나토리(인디/싱글캐스크)는 floor 빈칸 → 돌파 아님(현행 가드 유지)
        check(all("시그나토리" not in r["name"] for r in bks),
              "인디·싱글캐스크(floor 빈칸)는 돌파 미포함")
        check(parsed["disclaimer"] and "수집일 기준값" in parsed["disclaimer"],
              "CMPA-156 '수집일 기준값' 면책 보존")

        html_out = render_patch_html(parsed)
        check("국내최저 돌파" in html_out and "더 글렌그란트" in html_out,
              "패치 HTML 에 돌파 헤드라인 렌더")
        check("수집일 기준값" in html_out, "패치 HTML 면책문구 보존")
        check(brand.HANDLE in html_out and brand.TAGLINE in html_out,
              "런칭킷 브랜딩(핸들·태그라인) 적용")
        check('content="noindex' in html_out, "robots noindex (외부 비발행 가드)")

        check("../index.html" in html_out,
              "패치 백링크 = ../index.html (날짜폴더에서 홈으로)")

        # 결정론: 동일 입력 → 동일 출력
        check(render_patch_html(classify_patch(parse_patch_md(mdp))) == html_out,
              "결정론: 동일 md → byte-identical HTML")

        # 빌드 구조(헤르메틱): 픽스처 report_dir 에 베이스 html + 패치 md 를 두고
        # 기존 deploy 아카이브 컨벤션(index.html + <YYMMDD>/index.html)을 검증.
        base_fx = os.path.join(td, "면세위스키_리포트_2026-06-01.html")
        open(base_fx, "w", encoding="utf-8").write(
            "<!DOCTYPE html><html><head></head><body>\n<h1>면세 리포트</h1>\n</body></html>")
        with tempfile.TemporaryDirectory() as out:
            res = build(out_dir=out, report_dir=td)
            check(os.path.isfile(os.path.join(out, "index.html")),
                  "홈: <out>/index.html 생성")
            check(os.path.isfile(os.path.join(out, "260607", "index.html")),
                  "패치 아카이브: <out>/260607/index.html (날짜폴더)")
            check(not glob.glob(os.path.join(out, "patch_*.html"))
                  and not glob.glob(os.path.join(out, "base_*.html")),
                  "구(舊) flat 산출물(base_/patch_) 미생성")
            home = open(os.path.join(out, "index.html"), encoding="utf-8").read()
            check("가격 패치 아카이브" in home and "260607/index.html" in home,
                  "홈 index.html(=베이스 래핑)에 패치 아카이브 네비(→260607/index.html) 주입")
            check(brand.TAGLINE in home and 'content="noindex' in home,
                  "홈(베이스)도 3C 브랜딩 + noindex 가드")
            check([w for w in res["written"] if w.endswith("260607/index.html")],
                  "written 목록에 날짜폴더 패치 포함")
            # 결정론: 동일 소스 → 동일 트리(재빌드 byte-identical)
            with tempfile.TemporaryDirectory() as out2:
                build(out_dir=out2, report_dir=td)
                snap = lambda d: {os.path.relpath(p, d): open(p, encoding="utf-8").read()
                                  for p in glob.glob(os.path.join(d, "**", "*.html"),
                                                     recursive=True)}
                check(snap(out) == snap(out2), "결정론: 동일 소스 → 동일 트리(재빌드)")

    print(("\nSELFTEST PASS" if not fails else f"\nSELFTEST FAIL ({len(fails)})"))
    return 0 if not fails else 1


def dry_run():
    """무네트워크·결정론 회귀0 증명: 임시 디렉터리에 2회 빌드 → 상호 동일 +
    현행 deploy/ 산출물과도 동일(회귀 0)인지 비교."""
    import tempfile

    def snapshot(d):
        # 중첩(<YYMMDD>/index.html)까지 상대경로 키로 스냅샷.
        return {os.path.relpath(f, d): open(f, encoding="utf-8").read()
                for f in glob.glob(os.path.join(d, "**", "*.html"), recursive=True)}

    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        r1 = build(out_dir=a)
        r2 = build(out_dir=b)
        sa, sb = snapshot(a), snapshot(b)
        deterministic = sa == sb
        print(f"  빌드1 파일 {len(r1['written'])}개 · 빌드2 파일 {len(r2['written'])}개")
        print(f"  결정론(2회 빌드 동일): {'OK' if deterministic else 'FAIL'}")

        # 현행 deploy/ 와의 회귀 비교(있을 때만)
        regression = None
        if os.path.isdir(DEFAULT_OUT):
            cur = snapshot(DEFAULT_OUT)
            same = cur == sa
            changed = sorted(set(cur) ^ set(sa))
            diff_files = [k for k in (set(cur) & set(sa)) if cur[k] != sa[k]]
            regression = same
            print(f"  현행 deploy/blog 대비: "
                  f"{'회귀 0 (동일)' if same else '차이 있음'}")
            if not same:
                if changed:
                    print(f"    파일 목록 차이: {changed}")
                if diff_files:
                    print(f"    내용 차이: {diff_files}")
        else:
            print("  (현행 deploy 산출물 없음 — 첫 빌드)")

        print("  네트워크: 호출 없음(설계상 md/html 로컬 파싱만)")
    ok = deterministic and (regression is not False)
    print("\nDRY-RUN " + ("OK — 무네트워크·결정론·회귀0" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT, help="출력 디렉터리")
    ap.add_argument("--selftest", action="store_true", help="픽스처 자가검증")
    ap.add_argument("--dry-run", action="store_true",
                    help="무네트워크·결정론 회귀0 증명(파일 미변경)")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())
    if args.dry_run:
        sys.exit(dry_run())

    res = build(out_dir=args.out)
    nb = len(res["patches"])
    print(f"Code, Cask & Cabin 블로그 빌드 → {res['out']}")
    print(f"  홈(index.html=최신호/베이스): "
          f"{('본편 ' + res['base']['date'] + ' 래핑') if res['base'] else '커버(본편 없음)'}")
    print(f"  패치: {nb}개" + (f" (최신 {res['patches'][0]['latest_date']})" if nb else ""))
    for pm in res["patches"]:
        print(f"    - {pm['href']} [{pm['cadence']}] 돌파 {pm['breaks']}건")


if __name__ == "__main__":
    main()
