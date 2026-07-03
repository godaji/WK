#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""위스키 가격 "업데이트 로그(릴리스 노트)" — 누적 원장 + 단일 롤링 글 렌더 (CMPA-687 / 부모 CMPA-685).

보드 요청: 전일대비 한눈 요약을 release note 처럼 **시간 역순으로 누적**하는 단일 로그
페이지를 만든다. "데이터가 *언제* 갱신됐는지 + *무엇이* 바뀌었는지(반페이지)"를 한곳에서.

3단 구성:
  1) 누적 원장  data/changelog/updates.jsonl — append-only, **1줄=1 업데이트일**, date 멱등
     upsert(같은 날 재실행 시 그 라인만 갱신, 과거 라인 보존 — CMPA-156 누적 원칙).
  2) 오늘 엔트리 산출 — 신라=최신 `reports/shilla-dutyfree/가격변동_*.md` 요약,
     소매=최신 `reports/whisky-price/데일리샷_가격변동_*.md` 요약, 소스 freshness 날짜 =
     각 스냅샷 최신 수집일(신라 일별CSV·롯데/SSG snapshots·데일리샷 수집일·유튜브 OCR 가져온날짜).
     ※ 재크롤 0 — 이미 산출된 리포트/스냅샷 파일만 읽는다(자기완결·멱등).
  3) 페이지 렌더 — 단일 롤링 글 `blog-md/_posts/<시작일>-whisky-updates.md`
     (kind: changelog, categories:[data], robots:index,follow). 본문=날짜 내림차순,
     각 날짜 '## 📅 YYYY-MM-DD (요일) — 데이터 갱신' + 반페이지 요약. 최근 30일만 렌더
     (전체 이력은 원장·git 에 보존). 파일명 prefix=원장 최초일(고정) → URL 안정·고아글 0.

홈(메인) 맨 아래 `_HOME_CHANGELOG` 섹션은 생성기 build_blog_md.py 가 소유(이 파일은 글의
front matter 에 요약 한 줄씩(cl_sources/cl_shilla/cl_retail/log_date)을 실어 홈이 읽게 한다).

사용:
  python3 -m pipelines.changelog.build_changelog            # 오늘(KST) 엔트리 upsert + 페이지 렌더
  python3 -m pipelines.changelog.build_changelog --date 2026-06-29
  python3 -m pipelines.changelog.build_changelog --selftest # 픽스처로 파서·렌더 검증(파일 미변경)
"""
import argparse
import csv
import datetime
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

LEDGER = os.path.join(ROOT, "data", "changelog", "updates.jsonl")
POSTS_DIR = os.path.join(ROOT, "blog-md", "_posts")
SHILLA_REPORTS = os.path.join(ROOT, "reports", "shilla-dutyfree")
RETAIL_REPORTS = os.path.join(ROOT, "reports", "whisky-price")

_WD_KO = ["월", "화", "수", "목", "금", "토", "일"]
RENDER_DAYS = 30   # 본문엔 최근 30일만 (전체 이력은 원장에 누적)

# ── 소스 freshness(최신 수집일) ──────────────────────────────────────────────
# 각 소스의 '가장 최신 수집일'(YYYY-MM-DD). 데이터 3원칙 ③: 수집 날짜는 신뢰성 1차 신호.
_SNAPSHOT_GLOBS = {
    "신라": os.path.join(ROOT, "data", "shilla-dutyfree", "신라면세_위스키_????-??-??.csv"),
    "롯데": os.path.join(ROOT, "assets", "lotte_dutyfree", "snapshots",
                        "????-??-??_lotte_whisky.csv"),
    "신세계": os.path.join(ROOT, "assets", "ssg_dutyfree", "snapshots",
                         "????-??-??_ssg_whisky.csv"),
}


def _date_in(name):
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(name or ""))
    return m.group(1) if m else ""


def _max_date_in(name):
    """파일명 내 모든 YYYY-MM-DD 토큰의 최대값(리포트의 '최신 스냅샷' 끝날짜). 없으면 ""."""
    ds = re.findall(r"\d{4}-\d{2}-\d{2}", os.path.basename(name or ""))
    return max(ds) if ds else ""


def _newest_snapshot_date(pattern):
    dates = [d for f in glob.glob(pattern) if (d := _date_in(f))]
    return max(dates) if dates else ""


def _csv_max_date(path, col):
    """CSV 의 날짜 컬럼(BOM 대비) 최대값. 없으면 ""."""
    if not os.path.exists(path):
        return ""
    best = ""
    with open(path, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            v = (row.get(col) or "").strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", v) and v > best:
                best = v
    return best


def _newest_month_csv(stem):
    """data/whisky-prices/<YYYY-MM>_<stem>.csv 중 최신 월 파일 경로."""
    files = sorted(glob.glob(os.path.join(ROOT, "data", "whisky-prices",
                                          f"????-??_{stem}.csv")))
    return files[-1] if files else ""


def source_freshness():
    """소스별 최신 수집일 dict. 누락 소스는 키 생략(우아한 미노출)."""
    out = {}
    for label, pat in _SNAPSHOT_GLOBS.items():
        d = _newest_snapshot_date(pat)
        if d:
            out[label] = d
    ds = _newest_month_csv("dailyshot")
    if ds:
        d = _csv_max_date(ds, "수집일")
        if d:
            out["데일리샷"] = d
    yt = _newest_month_csv("youtube_ocr")
    if yt:
        d = _csv_max_date(yt, "가져온날짜")
        if d:
            out["트레이더스OCR"] = d
    return out


# ── 리포트 파싱(이미 산출된 md 요약 → 엔트리) ─────────────────────────────────
def _tables(text):
    """md 본문을 (heading, [row_cells,...]) 블록 리스트로 분해. 각 row=파이프 셀 리스트."""
    blocks, heading, rows = [], "", []
    for ln in text.splitlines():
        if ln.startswith("#"):
            if rows:
                blocks.append((heading, rows))
                rows = []
            heading = ln.lstrip("#").strip()
        elif ln.strip().startswith("|"):
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if set("".join(cells)) <= set("-: "):   # 구분선 행 skip
                continue
            rows.append(cells)
    if rows:
        blocks.append((heading, rows))
    return blocks


def _latest_report(folder, prefix):
    """folder 내 prefix 로 시작하는 md 중 파일명 날짜 토큰이 가장 큰 것."""
    cands = glob.glob(os.path.join(folder, f"{prefix}*.md"))
    if not cands:
        return ""
    # 끝날짜(최신 스냅샷)가 가장 늦은 리포트. 동일 끝날짜는 파일명으로 tie-break
    # (예: _am_to_27_pm < _pm_to_28_pm → 더 최신 'to' 가 이김).
    return max(cands, key=lambda p: (_max_date_in(p), os.path.basename(p)))


def _int(s, default=0):
    m = re.search(r"-?\d[\d,]*", str(s))
    return int(m.group().replace(",", "")) if m else default


def _find_int(pattern, text, default=0):
    """pattern 의 group(1)(숫자)을 int 로. 매치 없으면 default."""
    m = re.search(pattern, text)
    return _int(m.group(1), default) if m else default


def parse_shilla(path):
    """신라 가격변동 리포트 → {up,down,new,gone,top:[...]}. 못 읽으면 None."""
    if not path or not os.path.exists(path):
        return None
    text = open(path, encoding="utf-8").read()
    up = _find_int(r"상승\s*([\d,]+)", text)
    down = _find_int(r"하락\s*([\d,]+)", text)
    new = _find_int(r"신규 상품:\s*\*\*([\d,]+)", text)
    gone = _find_int(r"삭제\(사라진\) 상품:\s*\*\*([\d,]+)", text)
    top = []
    for heading, rows in _tables(text):
        if heading.startswith("가격(할인가_USD) 변동"):
            for r in rows[1:]:    # rows[0]=헤더
                if len(r) < 5:
                    continue
                name, cur_pct, prev_pct, krw = r[0], r[2], r[3], r[4]
                top.append(f"{name} {_int(prev_pct)}→{_int(cur_pct)}% {krw}")
                if len(top) >= 3:
                    break
            break
    return {"up": up, "down": down, "new": new, "gone": gone, "top": top}


def parse_retail(path):
    """데일리샷 가격변동 리포트 → {up,down,new,gone,top:[...]}. 못 읽으면 None."""
    if not path or not os.path.exists(path):
        return None
    text = open(path, encoding="utf-8").read()
    g = lambda lbl: _find_int(rf"\|\s*{lbl}\s*\|\s*([\d,]+)\s*건", text)  # noqa: E731
    up, down = g("상승"), g("하락")
    new = _find_int(r"\|\s*신규(?:\s*HIT)?\s*\|\s*([\d,]+)\s*건", text)
    gone = _find_int(r"\|\s*소실\s*\|\s*([\d,]+)\s*건", text)
    top = []
    # 우선순위: 신규 → 하락(좋은 뉴스) → 상승. 각 섹션 표에서 위스키명·현재가 추출.
    for key, tag in (("신규", "신규"), ("하락", "하락"), ("상승", "상승")):
        for heading, rows in _tables(text):
            if key not in heading:
                continue
            for r in rows[1:]:
                if len(r) < 3 or "위스키명" in r[0]:
                    continue
                name, cur = r[0], r[2]
                loc = r[6] if len(r) > 6 and r[6] not in ("", "—") else ""
                suffix = f" {tag}({loc})" if (tag == "신규" and loc) else f" {tag}"
                top.append(f"{name} {cur}{suffix}")
                if len(top) >= 3:
                    break
        if len(top) >= 3:
            break
    return {"up": up, "down": down, "new": new, "gone": gone, "top": top}


# ── 그날의 발행 링크(compare/patch/mart/dashboard) ───────────────────────────
def _post_url(name):
    """_posts 파일명(YYYY-MM-DD-slug.md) → 사이트 상대 URL (/YYYY/MM/DD/slug/)."""
    base = os.path.basename(name)[:-3]
    y, m, d, *slug = base.split("-")
    return f"/{y}/{m}/{d}/{'-'.join(slug)}/"


def _post_link(slug, on_or_before):
    """slug 글 중 날짜 <= on_or_before 인 최신본 URL. 없으면 전체 최신본. 없으면 ""."""
    cands = sorted(glob.glob(os.path.join(POSTS_DIR, f"*-{slug}.md")))
    if not cands:
        return ""
    le = [p for p in cands if (_date_in(p) or "") <= on_or_before]
    return _post_url((le or cands)[-1])


def entry_links(date):
    return {k: v for k, v in {
        "compare": _post_link("dutyfree-whisky-compare", date),
        "patch": _post_link("price-patch", date),
        "mart": _post_link("mart-cheaper-whisky", date),
        "dashboard": "/dashboard/",
    }.items() if v}


# ── 엔트리 산출 ──────────────────────────────────────────────────────────────
def build_entry(date):
    shilla = parse_shilla(_latest_report(SHILLA_REPORTS, "가격변동_")) \
        or {"up": 0, "down": 0, "new": 0, "gone": 0, "top": []}
    retail = parse_retail(_latest_report(RETAIL_REPORTS, "데일리샷_가격변동_")) \
        or {"up": 0, "down": 0, "new": 0, "gone": 0, "top": []}
    return {
        "date": date,
        "sources": source_freshness(),
        "shilla": shilla,
        "retail": retail,
        "links": entry_links(date),
    }


# ── 원장 upsert ──────────────────────────────────────────────────────────────
def load_ledger(path=LEDGER):
    rows = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if ln:
                    o = json.loads(ln)
                    rows[o["date"]] = o
    return rows


def upsert_ledger(entry, path=LEDGER):
    """date 멱등 upsert: 같은 날 라인은 교체, 과거 라인 보존. 날짜 오름차순으로 재기록."""
    rows = load_ledger(path)
    rows[entry["date"]] = entry
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for d in sorted(rows):
            f.write(json.dumps(rows[d], ensure_ascii=False) + "\n")
    return rows


# ── 페이지 렌더 ──────────────────────────────────────────────────────────────
def _fresh_line(sources):
    order = ["신라", "롯데", "신세계", "데일리샷", "트레이더스OCR"]
    short = {"트레이더스OCR": "트레이더스"}
    parts = [f"{short.get(k, k)} {sources[k][5:]}" for k in order if k in sources]
    return " · ".join(parts)


def _chg_line(c):
    bits = [f"상승 {c['up']}", f"하락 {c['down']}", f"신규 {c['new']}"]
    if c.get("gone"):
        bits.append(f"삭제 {c['gone']}")
    return " · ".join(bits)


def _entry_section(e):
    d = datetime.date.fromisoformat(e["date"])
    out = [f"## 📅 {e['date']} ({_WD_KO[d.weekday()]}) — 데이터 갱신", ""]
    fresh = _fresh_line(e.get("sources", {}))
    if fresh:
        out += [f"**🗂 갱신 시점** — {fresh}", ""]
    sh = e["shilla"]
    out.append(f"**🛫 면세(신라) 전일대비** — {_chg_line(sh)}")
    for t in sh.get("top", []):
        out.append(f"- {t}")
    out.append("")
    rt = e["retail"]
    out.append(f"**🛒 소매(데일리샷) 전일대비** — {_chg_line(rt)}")
    for t in rt.get("top", []):
        out.append(f"- {t}")
    out.append("")
    # baseurl(/CaskCode) 안전: build_blog_md 발행 게이트가 절대경로를 relative_url 로
    # 래핑한다 → 같은 형태로 직접 출력해 빌드 순서와 무관하게 byte-stable 하게 만든다.
    def _ln(label, path):
        return f"[{label}]({{{{ '{path}' | relative_url }}}})"
    links, lk = e.get("links", {}), []
    if links.get("compare"):
        lk.append(_ln("면세 비교", links["compare"]))
    if links.get("patch"):
        lk.append(_ln("신라 가격변동 로그", links["patch"]))
    if links.get("mart"):
        lk.append(_ln("마트에서 구매", links["mart"]))
    if links.get("dashboard"):
        lk.append(_ln("가격 대시보드", links["dashboard"]))
    if lk:
        out += [f"**🔗 자세히** — {' · '.join(lk)}", ""]
    out.append("---")
    out.append("")
    return out


def _fm_summary(entry):
    """홈 카드용 front matter 요약 — build_blog_md 의 _HOME_CHANGELOG 가 읽는다."""
    sh, rt = entry["shilla"], entry["retail"]
    return {
        "cl_sources": _fresh_line(entry.get("sources", {})),
        "cl_shilla": f"면세 {_chg_line(sh)}",
        "cl_retail": f"소매 {_chg_line(rt)}",
    }


def render_page(rows):
    """원장(dict by date) → 단일 롤링 글 markdown. 최신 날짜가 맨 위(시간역순)."""
    dates_desc = sorted(rows, reverse=True)
    latest = rows[dates_desc[0]]
    # front matter date = 파일명(원장 최초일)과 동일하게 고정 → URL/퍼머링크 안정
    # (/YYYY/MM/DD/whisky-updates/). '최신 갱신일'은 log_date·본문이 따로 보여준다.
    anchor = min(rows)
    fm = {
        "layout": "post",
        "title": "위스키 가격 업데이트 로그 (릴리스 노트)",
        "date": f"{anchor} 09:30:00 +0900",
        "categories": ["data"],
        "kind": "changelog",
        "cadence": "log",
        "log_date": dates_desc[0],
        "robots": "index,follow",
        "description": (f"위스키 가격 데이터 업데이트 로그 — 언제 갱신됐고 무엇이 바뀌었는지 "
                        f"시간 역순 누적. 최신 {dates_desc[0]} 기준."),
    }
    fm.update(_fm_summary(latest))
    body = [_front_matter(fm), ""]
    body.append("이 글은 위스키 가격 데이터가 **언제 갱신됐고 무엇이 바뀌었는지**를 "
                "릴리스 노트처럼 날짜별로 쌓는 로그입니다. 최신 갱신이 맨 위 · 각 날짜는 "
                "전일대비 한눈 요약(면세·소매)입니다.")
    body.append("")
    body.append("> 🗂 **갱신 시점** = 소스별 최신 *수집일*입니다(데이터 3원칙 ③: 수집 날짜는 "
                "신뢰성의 1차 신호). 가격은 각 수집일 기준값이며, 변동은 직전 수집일 대비입니다.")
    body.append("")
    rendered = dates_desc[:RENDER_DAYS]
    for d in rendered:
        body += _entry_section(rows[d])
    if len(dates_desc) > RENDER_DAYS:
        body.append(f"_이전 기록({len(dates_desc) - RENDER_DAYS}일치)은 원장"
                    f"(`data/changelog/updates.jsonl`)에 누적 보존됩니다._")
        body.append("")
    return "\n".join(body).rstrip() + "\n"


def _front_matter(fields):
    """결정론적 YAML front matter(build_blog_md.front_matter 와 동일 규약)."""
    def yv(v):
        return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'
    out = ["---"]
    for k, v in fields.items():
        if isinstance(v, list):
            out.append(f"{k}: [{', '.join(yv(x) for x in v)}]")
        else:
            out.append(f"{k}: {yv(v)}")
    out.append("---")
    return "\n".join(out)


def page_path(rows):
    """파일명 prefix = 원장 최초일(고정) → URL 안정·고아글 0."""
    first = min(rows)
    return os.path.join(POSTS_DIR, f"{first}-whisky-updates.md")


def render_to_disk(rows):
    """렌더 + 디스크 기록(멱등). 과거에 다른 날짜로 만든 changelog 글이 있으면 정리."""
    target = page_path(rows)
    os.makedirs(POSTS_DIR, exist_ok=True)
    for stale in glob.glob(os.path.join(POSTS_DIR, "*-whisky-updates.md")):
        if os.path.abspath(stale) != os.path.abspath(target):
            os.remove(stale)
            print(f"  · 고아 changelog 글 제거: {os.path.basename(stale)}")
    content = render_page(rows)
    prev = open(target, encoding="utf-8").read() if os.path.exists(target) else None
    if prev == content:
        print(f"  변경 없음(멱등): {os.path.basename(target)}")
        return target, False
    with open(target, "w", encoding="utf-8") as f:
        f.write(content)
    print(f"  ✓ 렌더: {os.path.relpath(target, ROOT)}")
    return target, True


# ── 자가검증 ─────────────────────────────────────────────────────────────────
_SELFTEST_SHILLA = """## 요약
- 가격(할인가_USD) 변동: **22건** (상승 22 · 하락 0)
- 신규 상품: **0건**
- 삭제(사라진) 상품: **2건**
## 가격(할인가_USD) 변동 — 변동폭 큰 순
| 위스키명 | 현재 USD | 현재 할인율 | 직전 할인율 | 현재 KRW | 국내최저가 |
|---|---:|---:|---:|---:|---:|
| 보모어 22년 700ml | $219.45 | 45.0% | 50.0% | ₩337,181 | ₩1,249,000 |
| 라가불린 16년 700ml | $70.70 | 42.0% | 48.0% | ₩108,628 | ₩135,000 |
| 발베니 18년 700ml | $145.34 | 48.0% | 50.0% | ₩223,315 | ₩349,000 |
"""
_SELFTEST_RETAIL = """# 데일리샷 가격변동 보고
| 항목 | 내용 |
|------|------|
| 하락 | 0건 |
| 상승 | 0건 |
| 신규 HIT | 1건 |
| 소실 | 0건 |
## 🆕 신규 HIT (1건)
| 위스키명 | 직전가 | 현재가 | Δ | Δ% | 정확도 | 국내위치 | URL |
|---|---|---|---|---|---|---|---|
| 글렌모렌지 D 오리지널 12년 | — | 66,000원 | — | — | 근접 | 코스트코 | [링크](x) |
"""


def selftest():
    ok = True

    def chk(cond, msg):
        nonlocal ok
        ok = ok and bool(cond)
        print(("  ✓ " if cond else "  ✗ ") + msg)

    import tempfile
    with tempfile.TemporaryDirectory() as td:
        sp = os.path.join(td, "가격변동_2026-06-28_to_2026-06-29.md")
        rp = os.path.join(td, "데일리샷_가격변동_x.md")
        open(sp, "w", encoding="utf-8").write(_SELFTEST_SHILLA)
        open(rp, "w", encoding="utf-8").write(_SELFTEST_RETAIL)
        sh = parse_shilla(sp)
        chk(sh["up"] == 22 and sh["down"] == 0 and sh["new"] == 0 and sh["gone"] == 2,
            f"신라 카운트 파싱 up=22/gone=2 → {sh['up']}/{sh['gone']}")
        chk(sh["top"][0] == "보모어 22년 700ml 50→45% ₩337,181",
            f"신라 top[0] 포맷 → {sh['top'][0]}")
        chk(len(sh["top"]) == 3, f"신라 top 3건 → {len(sh['top'])}")
        rt = parse_retail(rp)
        chk(rt["new"] == 1 and rt["up"] == 0 and rt["down"] == 0,
            f"소매 카운트 파싱 new=1 → {rt['new']}")
        chk(rt["top"] == ["글렌모렌지 D 오리지널 12년 66,000원 신규(코스트코)"],
            f"소매 top 포맷 → {rt['top']}")

        # 원장 멱등 upsert + 시간역순 렌더
        ledger = os.path.join(td, "updates.jsonl")
        e1 = {"date": "2026-06-28", "sources": {"신라": "2026-06-28"},
              "shilla": sh, "retail": rt, "links": {"dashboard": "/dashboard/"}}
        e2 = {"date": "2026-06-29", "sources": {"신라": "2026-06-29", "롯데": "2026-06-29"},
              "shilla": sh, "retail": rt, "links": {"dashboard": "/dashboard/"}}
        upsert_ledger(e1, ledger)
        upsert_ledger(e2, ledger)
        upsert_ledger(dict(e2, shilla=dict(sh, up=99)), ledger)   # 같은 날 재upsert
        rows = load_ledger(ledger)
        chk(len(rows) == 2, f"멱등: 2일치 유지(재upsert 중복 없음) → {len(rows)}")
        chk(rows["2026-06-29"]["shilla"]["up"] == 99, "멱등: 같은 날 라인 교체됨")
        page = render_page(rows)
        i28, i29 = page.find("📅 2026-06-28"), page.find("📅 2026-06-29")
        chk(0 <= i29 < i28, "렌더: 최신(06-29)이 06-28보다 위(시간역순)")
        chk("kind: \"changelog\"" in page and "robots: \"index,follow\"" in page,
            "front matter: kind=changelog·index,follow")
        chk("cl_shilla:" in page and "🗂 갱신 시점" in page and "🛫 면세" in page,
            "본문/요약: 소스 갱신일·면세·소매 노출")
    print("\nSELFTEST:", "PASS ✅" if ok else "FAIL ❌")
    return 0 if ok else 1


def kst_today():
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=9)).date().isoformat()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="엔트리 기준 날짜(KST 기본)")
    ap.add_argument("--selftest", action="store_true", help="픽스처 파서·렌더 검증(파일 미변경)")
    ap.add_argument("--no-render", action="store_true", help="원장 upsert 만(페이지 렌더 생략)")
    args = ap.parse_args()
    if args.selftest:
        return selftest()

    date = args.date or kst_today()
    print(f"==== 업데이트 로그 빌드 (기준 {date}, KST) ====", flush=True)
    entry = build_entry(date)
    print(f"  엔트리: 신라 {_chg_line(entry['shilla'])} · "
          f"소매 {_chg_line(entry['retail'])} · 소스 {entry['sources']}", flush=True)
    rows = upsert_ledger(entry)
    print(f"  원장: {os.path.relpath(LEDGER, ROOT)} ({len(rows)}일치)", flush=True)
    if args.no_render:
        return 0
    render_to_disk(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
