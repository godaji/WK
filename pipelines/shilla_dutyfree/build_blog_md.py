#!/usr/bin/env python3
"""CaskCode 블로그 — Markdown + GitHub Pages(Jekyll) 빌더 (CMPA-178/182, Phase-1.5).

build_blog.py(CMPA-176, HTML 빌더)의 **파싱/분류 로직을 100% 재사용**하고
**렌더 타깃만 HTML → Markdown(+YAML front matter) + Jekyll 사이트**로 교체한다.

재사용(이 파일에서 새로 만들지 않음 — build_blog 에서 import):
  - parse_patch_md / classify_patch / CONFIG (하이브리드 케이던스 임계치)
  - **'국내최저 돌파'(면세가 < 국내최저) 톱 정렬·강조 🏆** — 핵심 기능, 유지
  - 베이스/패치 구조, '수집일 기준값' 면책(CMPA-156), 인디·싱글캐스크 빈칸 가드
  - CaskCode 브랜드(brand.py, CMPA-144 런칭킷 @codecaskcabin·팔레트 → CMPA-182 리브랜드)

거버넌스(CMPA-178 CEO 확정 — 보드 '블로그 전용 리포'):
  1. **발행 폴더 = self-contained.** md + Jekyll(_config.yml/_layouts/CSS) **만**.
     `data/`·`pipelines/`·원천 스크랩 CSV 는 이 폴더에 **절대 미포함**(이 폴더만 별도
     public 리포로 push 될 것). → 생성기(이 코드)는 메인 리포에 두고 **출력만 분리**.
  2. **콘텐츠 = 분석/에디토리얼 md**(가공·요약·랭킹). 원천 변동표 통째 덤프 금지.
     베이스 본편은 에디토리얼 초안(reports/.../draft_면세위스키_*.md)을 소스로,
     패치는 돌파/인하만 가공·랭킹한 카드형 md 로 발행(원천 표 비덤프).
  3. **외부 발행 = c7405e7d 게이트(보드).** 그 전엔 로컬 스테이징 + noindex 만.

Jekyll 구조(출력 = blog-md/ (리포 루트), self-contained):
  _config.yml                      사이트 설정(타이틀/설명=brand, 마크다운=kramdown)
  index.md                         홈 = 본편 + 패치 아카이브(site.posts Liquid 목록)
  _layouts/default.html            3C 마스트헤드 + CSS + 푸터(게이트 문구) + noindex
  assets/css/style.css             3C 팔레트(brand.CSS_VARS/폰트에서 생성 — 단일 소스)
  _posts/<날짜>-monthly-base.md    베이스: 이달의 면세 위스키 본편(월초 1회)
  _posts/<날짜>-price-patch.md     패치: 가격변동 패치 <날짜>(돌파 톱, 하이브리드 케이던스)
  README.md / Gemfile / .gitignore 별도 리포 self-contained 보조 파일

사용법:
  python3 pipelines/shilla_dutyfree/build_blog_md.py            # blog-md/ 에 빌드(리포 루트)
  python3 pipelines/shilla_dutyfree/build_blog_md.py --out DIR  # 다른 경로로
  python3 pipelines/shilla_dutyfree/build_blog_md.py --selftest # md+front matter 유효성 자가검증
  python3 pipelines/shilla_dutyfree/build_blog_md.py --dry-run  # 무네트워크·결정론·회귀0 증명
"""
from __future__ import annotations

import argparse
import datetime
import glob
import os
import re
import sys

import brand  # 같은 디렉터리(스크립트 실행 시 sys.path[0])
import detect_rare_drops  # '오랜만의 큰 인하' 감지(CMPA-644 후속·할인가_USD 히스토리)
import whisky_story  # 보강 스토리 조회(요약 인라인 펼치기·신규 술 설명)
# 파싱/분류 로직 전부 재사용 — 새로 만들지 않는다(CMPA-178 "반드시 재사용").
import build_blog as bb
from build_blog import (
    CONFIG,
    _fmt_krw,
    _fmt_pct,
    _name_key,
    classify_patch,
    parse_patch_md,
)

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
REPORT_DIR = os.path.join(ROOT, "reports", "shilla-dutyfree")
# 블로그 전용 GitHub Pages 리포 스테이징. deploy/(=Netlify 산출물, build_deploy 가 rmtree)
# 밖의 리포 루트에 둔다 — 이 폴더만 별도 public 리포로 push 한다(CMPA-178 보드 피벗).
DEFAULT_OUT = os.path.join(ROOT, "blog-md")

# 베이스(이달의 본편) 소스 = 에디토리얼 초안(가공 콘텐츠). 원천 리포트 HTML(스크랩 표)
# 통째 덤프 금지(CMPA-178 §2)라 에디토리얼 md 를 본편으로 쓴다.
BASE_SRC_PATTERNS = ("draft_면세위스키_*.md", "콘텐츠초안_면세위스키_*.md")
DATE_IN_NAME = re.compile(r"_(\d{4}-\d{2}-\d{2})\.md$")

# CMPA-156 '수집일 기준값' 면책 — 베이스에 항상 보장(패치는 소스 md 가 자체 보유).
COLLECT_DISCLAIMER = (
    "가격은 각 스냅샷 **수집일 기준값**입니다. 면세가는 출국 시에만 구매 가능하며 "
    "주류 면세한도(2병·2L·$400)가 적용됩니다. 가격·재고는 수시 변동합니다."
)

# ── 블로그 카테고리(섹션) — CaskCode 2기둥에 정렬 ─────────────────────
# 글의 front matter `categories: [<key>]` 로 스트림(글 종류)을 정한다. 'price' 만
# 파이프라인이 자동 생성(본편+패치), 나머지는 손글. 보드가 새 카테고리를 쓰면(글에 새
# key 를 넣으면) 홈 '기타'에 자동 노출된다.
#
# 홈은 브랜드 2기둥(Code/Cask)으로 묶는다 — CMPA-182 리브랜드 → CMPA-204 재편 2026-06-07.
#   Code = CaskCode가 직접 개발한 것 + 데이터로 파헤친 것:
#          소프트웨어·사이드프로젝트·코드 이야기(dev) + 데이터 분석(data).
#   Cask = 위스키 전부: 면세 가성비 자동 리포트(price 본편/패치) + 위스키 가격정보(wprice)
#          + 시음 노트(tasting). 오크통 숙성(구 Cabin)은 별도 칸 없이 `#숙성`
#          태그로 Cask 안에 흡수.
#   ※ CMPA-204 재편: data(데이터 분석)는 Cask→Code 로 이동, wprice(위스키 가격정보)는
#     Cask 신규 스트림(국내·해외 시세 비교, reports/whisky-price 블로그화 수신 카테고리).
#   ※ CMPA-287 가르는 규칙(보드 확정 2026-06-10) — 카테고리는 '데이터냐'가 아니라
#     **독자가 뭐 하러 왔나**로 정한다. 우리 위스키 글은 거의 다 데이터 산출물이라
#     '데이터=Code' 기준은 위스키 글을 Code로 빨아들인다(보드가 느낀 위화감).
#       · "이걸 어떻게 만들었나"(파이프라인·정규화·개발기) → Code(dev/data)
#       · "어떤 위스키를 얼마에 사고 어떻게 마시나"(가격·면세·시세비교·추세·매수콜·시음·숙성)
#         → Cask(price/wprice/tasting)
#     즉 도구 '이야기'=Code, 도구가 뱉은 '위스키 산출물'=Cask. 한일/채널 가격비교처럼
#     '어디가 싼가'를 답하는 글은 data 가 아니라 **wprice(Cask)** 로 태깅한다.
#     data(Code)는 위스키 주제가 아닌 일반 방법론/build craft 글에만 쓴다.
# '일기'는 별도 칸을 두지 않는다 — 위스키 산 이야기·여정·느낀점은 각 기둥 글에 `#일기`
# 태그로 단다(글의 '종류'=기둥/스트림, '소재·성격'=태그).
STREAMS = {
    "price":   {"label": "면세 가성비",      "emoji": "🏷️",
                "desc": "데이터로 고른 면세 위스키 — 가격·국내최저 돌파 (자동 생성)"},
    "wprice":  {"label": "위스키 가격정보",   "emoji": "💰",
                "desc": "국내·해외 위스키 시세 — 트레이더스·코스트코·데일리샷·홍콩·일본 비교"},
    "tasting": {"label": "구매/시음/숙성 노트", "emoji": "🥃",
                "desc": "사서 마셔본 기록 — 구매 노트 + 시음 (오크통 숙성 실험은 `#숙성` 태그)"},
    "data":    {"label": "데이터 분석",       "emoji": "📊",
                "desc": "방법론·파이프라인 등 '어떻게 만들었나' (위스키 시세 비교는 wprice→Cask)"},
    "dev":     {"label": "개발",              "emoji": "💻",
                "desc": "직접 만든 소프트웨어·사이드프로젝트·코드 이야기"},
}
# 각 기둥은 자기 글만 모은 독립 목록 페이지(`path` permalink)로 분리(CMPA-192).
# 홈 허브 카드의 미리보기/카운트 Liquid where_exp 는 streams 로부터 파생
# (_pillar_filter) — 긍정형 `contains ... or ...`(부정형 `== false` 는
# Liquid where_exp 가 거부). 즉 Code=dev/data, Cask=price/wprice/tasting (CMPA-204).
# 순서 = 이름 'CaskCode' 와 맞춘다: Cask 먼저, Code 다음 (CMPA-198 보드 2026-06-07).
PILLARS = [
    {"emoji": "🥃", "label": "Cask", "tagline": "위스키 전부",
     "desc": "구매/시음/숙성 노트 · 면세 가성비 자동 리포트 · 위스키 가격정보.",
     "path": "/cask/",
     "streams": ["tasting", "price", "wprice"]},
    {"emoji": "💻", "label": "Code", "tagline": "직접 만든 것",
     "desc": "CaskCode가 직접 개발한 소프트웨어·사이드프로젝트·코드 이야기와 "
             "위스키 데이터 분석.",
     "path": "/code/",
     "streams": ["dev", "data"]},
]
# '기타' 폴백에서 제외할 알려진 카테고리(=모든 스트림 key).
SECTION_KEYS = list(STREAMS.keys())


# ── front matter / 인용 헬퍼 ─────────────────────────────────────────
def _yaml_str(s):
    """front matter 스칼라용 안전 인용(따옴표·콜론 포함 대비)."""
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def front_matter(fields):
    """dict → YAML front matter 블록(결정론적: 삽입 순서 유지)."""
    out = ["---"]
    for k, v in fields.items():
        if isinstance(v, list):
            out.append(f"{k}: [{', '.join(_yaml_str(x) for x in v)}]")
        elif isinstance(v, bool):
            out.append(f"{k}: {'true' if v else 'false'}")
        elif isinstance(v, (int, float)):
            out.append(f"{k}: {v}")
        else:
            out.append(f"{k}: {_yaml_str(v)}")
    out.append("---")
    return "\n".join(out)


# ── 패치 → Markdown ──────────────────────────────────────────────────
# 보드 CMPA-250(2026-06-09): 패치 글이 "눈에 안 들어온다" → 카드형(### 헤더+blockquote)
# 대신 **표**로 렌더해 한눈에 비교되게 한다. 원천 변동표 통째 덤프는 여전히 금지(거버넌스
# §2) — 헤더·컬럼을 가공본으로 새로 짜고(절약액·절약%) 가공·랭킹만 싣는다.
# 보드 CMPA-256(2026-06-09): 모바일 우선 원칙(CLAUDE.md). 5컬럼은 좁은 화면에서
# 글자가 뭉개진다 → **(위스키, 상세) 2컬럼**으로 재설계. 상세 칸에 면세가·국내최저·
# 절약·할인율을 <br> 줄바꿈으로 묶는다(절약액·% 강조는 굵게). 계산 로직/가드는 유지.
_BK_HEADER = ("| 🏆 위스키 | 상세 |\n"
              "|---|---|")
_DROP_HEADER = ("| 위스키 | 상세 |\n"
                "|---|---|")


# 보드 CMPA-273(2026-06-10): 할인율은 정수로, 직전→현재는 화살표로(예 '57%→58%').
def _pct0(v):
    """할인율 정수 표시(소수점 제거)."""
    return f"{v:.0f}%" if v is not None else "—"


def _rate_arrow(r):
    """직전→현재 할인율(정수, 예 '57%→58%'). 한쪽만 있으면 그 값, 동일하면 단일값."""
    p, l = r.get("p_rate"), r.get("l_rate")
    if p is None and l is None:
        return "—"
    if p is None:
        return _pct0(l)
    if l is None:
        return _pct0(p)
    if abs(p - l) < 0.05:
        return _pct0(l)
    return f"{_pct0(p)}→{_pct0(l)}"


def _h(s):
    """HTML 특수문자 최소 이스케이프(스토리/요약 raw HTML 삽입용)."""
    return (str(s or "").replace("&", "&amp;")
            .replace("<", "&lt;").replace(">", "&gt;"))


# 보드 CMPA-273(2026-06-10): 글 상단 '할인율 변동 요약'.
#  - 이름 옆에 할인적용 KRW 함께 표기.
#  - 변동 10%p↑ 만 '할인 심화/할증 심화' 메인 명단에. 10%p 미만은 '미세조정'으로 몰아 접이식.
#  - 보드 후속(설명 가독성): 요약의 각 술을 그 자리에서 펼치면(<details>) 설명이 인라인으로
#    뜨게 한다 — 위스키를 모르는 독자도 리스트에서 바로 무슨 술인지 본다(아래 모아두기 폐지).
_SUMMARY_MAJOR_PP = 10.0


def _summary_line(r):
    """요약 1줄: '이름: 직전%→현재% (₩할인적용가)'."""
    krw = f' ({_fmt_krw(r["krw"])})' if r.get("krw") is not None else ""
    return f'{r["name"]}: {_rate_arrow(r)}{krw}'


def _story_inner_html(row):
    """보강 행 → 펼침 내용 HTML(증류소·도수·캐스크·맛·스토리·출처)."""
    rows = []
    meta = " · ".join(x for x in [row.get("증류소", ""), row.get("지역", "")] if x)
    if meta:
        rows.append(f'<b>증류소</b> {_h(meta)}')
    for label, col in (("도수", "도수"), ("캐스크", "캐스크"),
                       ("맛", "맛_노트"), ("스토리", "스토리")):
        if row.get(col):
            rows.append(f'<b>{label}</b> {_h(row[col])}')
    asof = row.get("수집일", "")
    tail = " · ".join(x for x in [row.get("출처", ""),
                                  (f"수집일 {asof}" if asof else "")] if x)
    if tail:
        rows.append(f'<span style="color:#8a8f98">출처: {_h(tail)}</span>')
    return "<br>".join(rows)


def _card_details(summary_html, row):
    """접이식 카드 1개(single-line raw HTML — kramdown 마크다운 미처리 회피)."""
    inner = _story_inner_html(row)
    return (f'<details style="margin:5px 0;border:1px solid #2a2f3a;border-radius:8px;'
            f'padding:5px 10px"><summary style="cursor:pointer;font-weight:600">'
            f'{summary_html}</summary><div style="margin-top:6px;font-size:13px;'
            f'line-height:1.6">{inner}</div></details>')


def _item_details(r, stories):
    """요약 항목 1줄(이름·변동·KRW) — 보강 설명이 있으면 펼치기, 없으면 평문 한 줄."""
    line = _h(_summary_line(r))
    row = stories.get(whisky_story._norm(r["name"]))
    if not row:
        return f'<div style="margin:5px 0">{line}</div>'
    return _card_details(line, row)


def _rate_summary_block(parsed):
    """모든 가격변동 레코드 → 할인율 변동 요약 블록(markdown 줄 리스트).

    할인 심화 = 할인율↑(면세가 더 싸짐) · 할증 심화 = 할인율↓(가격 상승).
    |변동| ≥ 10%p 는 메인 명단, < 10%p 는 '미세조정' 접이식. 각 술은 이름을 눌러
    설명을 인라인으로 펼친다(보드 CMPA-273). 모두 비면 빈 리스트."""
    try:
        import whisky_story  # noqa: F401 (module-level 별칭 사용)
        stories = whisky_story.load_stories()
    except Exception:
        stories = {}
    recs = (parsed.get("breakthroughs", []) + parsed.get("drops", [])
            + parsed.get("others", []))
    def has_d(r):
        return r.get("d_rate") is not None
    deepen = sorted((r for r in recs if has_d(r) and r["d_rate"] >= _SUMMARY_MAJOR_PP),
                    key=lambda r: (-r["d_rate"], r["name"]))
    shrink = sorted((r for r in recs if has_d(r) and r["d_rate"] <= -_SUMMARY_MAJOR_PP),
                    key=lambda r: (r["d_rate"], r["name"]))
    fine_dn = sorted((r for r in recs if has_d(r) and 0 < r["d_rate"] < _SUMMARY_MAJOR_PP),
                     key=lambda r: (-r["d_rate"], r["name"]))
    fine_up = sorted((r for r in recs if has_d(r) and -_SUMMARY_MAJOR_PP < r["d_rate"] < 0),
                     key=lambda r: (r["d_rate"], r["name"]))
    if not any([deepen, shrink, fine_dn, fine_up]):
        return []
    out = ["## 📊 한눈에 — 할인율 변동 요약", "",
           "_각 위스키 이름을 누르면 도수·맛·스토리 설명이 펼쳐집니다._", ""]
    if deepen:
        out.append("**🔥 오늘의 핫딜 — 면세가가 더 싸짐 (10%p↑)**")
        out.append("")
        out.extend(_item_details(r, stories) for r in deepen)
        out.append("")
    if shrink:
        out.append("**🔺 할증 심화 — 할인 축소·가격 상승 (10%p↑)**")
        out.append("")
        out.extend(_item_details(r, stories) for r in shrink)
        out.append("")

    def _fine_group(title, rows):
        # 미세조정 = 그룹 접이식 안에 항목별 접이식(중첩) — 펼치면 설명까지.
        inner = "".join(_item_details(r, stories) for r in rows)
        return (f'<details style="margin:8px 0"><summary><strong>{title}</strong> '
                f'{len(rows)}건 · 10%p 미만 (펼치기)</summary>'
                f'<div style="margin-top:6px">{inner}</div></details>')
    if fine_dn:
        out.append(_fine_group("미세조정(할인)", fine_dn))
        out.append("")
    if fine_up:
        out.append(_fine_group("미세조정(할증)", fine_up))
        out.append("")
    return out


def _new_story_block(parsed):
    """신규 입고 술의 설명만 접이식 카드로(변동 요약에 안 잡히는 술 보강).

    변동 술 설명은 요약 리스트에서 인라인으로 펼치므로, 여기서는 신규 술만 다룬다."""
    try:
        import whisky_story
        stories = whisky_story.load_stories()
    except Exception:
        return []
    cards, seen = [], set()
    for r in parsed["sections"].get("new", []):
        name = _name_key(r)
        key = whisky_story._norm(name)
        if not key or key in seen:
            continue
        seen.add(key)
        row = stories.get(key)
        if not row:
            continue
        abv = row.get("도수", "")
        summ = f'🥃 {_h(name)}' + (f' · {_h(abv)}' if abv else "")
        cards.append(_card_details(summ, row))
    if not cards:
        return []
    return ["## 🆕 신규 술 설명 — 이름을 눌러 펼치기", ""] + cards + [""]


def _floor_disp(r):
    """국내최저 표시 — 데일리샷 링크 있으면 '🔗' 링크로(CMPA-334 보드)."""
    txt = _fmt_krw(r["floor"])
    url = r.get("floor_url")
    return f'[{txt} 🔗]({url})' if url else txt


def _bk_row(r):
    """국내최저 돌파 1건 → (위스키, 상세) 2컬럼 표 행(markdown). 가공·랭킹만."""
    save = r["save"]
    pct = (save / r["floor"] * 100) if (save and r["floor"]) else None
    if save is not None:
        saving = f'−{_fmt_krw(save)}' + (f' ({pct:.0f}%↓)' if pct is not None else "")
    else:
        saving = "—"
    rate = _rate_arrow(r)
    detail = (f'면세 **{_fmt_krw(r["krw"])}** · 국내최저 {_floor_disp(r)}'
              f'<br>절약 **{saving}** · 할인 {rate}')
    return f'| {r["name"]} | {detail} |'


def _drop_row(r):
    """의미있는 인하 1건 → (위스키, 상세) 2컬럼 표 행(markdown)."""
    dd = r["d_rate"]
    delta = f'+{dd:.0f}%p' if dd is not None else "—"
    rate = _rate_arrow(r)
    floor = _floor_disp(r) if r["floor"] is not None else "—"
    detail = (f'현재 **{_fmt_krw(r["krw"])}** · 할인 {rate}'
              f'<br>할인율 변동 {delta} · 국내최저 {floor}')
    return f'| {r["name"]} | {detail} |'


def _patch_body_lines(p):
    """패치 parsed → 본문 markdown 줄 리스트(front matter 제외).

    CMPA-644: 단독 일일 패치(render_patch_md)와 주간 로그의 '하루 섹션'
    (render_weekly_log)이 동일한 본문을 재사용하도록 분리한다. 헤딩은 ## 기준이며,
    주간 로그는 _demote_headings 로 ###(하루 섹션 ## 아래)으로 한 단계 낮춘다."""
    bks = p["breakthroughs"]
    body = []
    # 보드 CMPA-273: 배지(⚡즉시 패치)·수집일 면책 blockquote 제거 요청.
    #   수집일 노출은 아래 직전→최신 라인 + 각 술 카드의 '수집일' 메타로 유지(CMPA-156).
    body.append(f'*직전 {p["prev_date"]} → 최신 {p["latest_date"]}*'
                + (f' · *환율 {p["fx"]}*' if p["fx"] else ""))
    body.append("")

    # 보드 CMPA-273: 상단에 할인 심화/할증 심화 한눈 요약(이름 직전→현재).
    body.extend(_rate_summary_block(p))

    body.append("## 🏆 국내최저가(데일리샷·트레이더스·코스트코) 대비 핫딜")
    body.append("")
    if bks:
        body.append(_BK_HEADER)
        for r in bks:
            body.append(_bk_row(r))
        body.append("")
    else:
        body.append("이번 패치엔 국내최저 돌파 항목이 없습니다.")
        body.append("")

    # 보드 CMPA-273: '이번 주 의미있는 인하' 섹션 삭제 — 한눈에 요약과 내용 중복.

    new = p["sections"]["new"]
    removed = p["sections"]["removed"]
    if new:
        body.append(f"## 🆕 신규 입고 ({len(new)})")
        body.append("")
        body.append("| 위스키 | 현재 KRW |")
        body.append("|---|--:|")
        for r in new:
            kw = r.get("현재 KRW", "") or "—"
            body.append(f'| {_name_key(r)} | {kw} |')
        body.append("")
    if removed:
        body.append(f"## 📦 품절/내림 ({len(removed)})")
        body.append("")
        body.append("| 위스키 |")
        body.append("|---|")
        for r in removed:
            body.append(f'| {_name_key(r)} |')
        body.append("")

    # 보드 CMPA-273: 변동 술 설명은 요약 리스트에서 인라인으로 펼침 → 여기선 신규 술만.
    body.extend(_new_story_block(p))

    if p["footer_note"]:
        body.append(f'*{p["footer_note"]}*')
        body.append("")
    # 보드 CMPA-273: 내부 생성기 정보(출처: detect_price_changes.py …) 노출 금지 — 삭제.
    return body


def render_patch_md(parsed):
    """단독 일일 패치 parsed → Jekyll 포스트(front matter + markdown).

    CMPA-644 이후 라이브 발행은 render_weekly_log(주간 로그)로 통합됐다. 이 함수는
    하위호환·단위테스트(단일 패치 렌더 검증)용으로 보존한다."""
    p = parsed
    bks = p["breakthroughs"]
    fm = front_matter({
        "layout": "post",
        "title": f'[신라면세] 가격변동 패치 {p["latest_date"]}',
        "date": f'{p["latest_date"]} 09:00:00 +0900',
        "categories": ["price"],
        "kind": "patch",
        "cadence": p["cadence"],
        "breakthroughs": len(bks),
        "prev_date": p["prev_date"],
        "latest_date": p["latest_date"],
        "description": (f'면세 위스키 가격 패치 {p["latest_date"]} — '
                        f'국내최저 돌파 {len(bks)}건. {brand.NAME_EN}'),
        "robots": "noindex,nofollow",
    })
    return "\n".join([fm, ""] + _patch_body_lines(p))


# ── 주간 로그(시간역순 append) → Markdown ────────────────────────────
# 보드 CMPA-644(2026-06-27): 매일 새 글이 쏟아져 "보기 너무 불편하다" →
# **한 주(월~일)를 한 글에 누적**한다. 하루 단위 섹션을 **최신이 맨 위**(시간역순)로
# 쌓는 로그 형태. 일일 가격변동 감지는 그대로(매일 detect) 돌되, 블로그는 그 주의
# 단일 글(_posts/<주시작(월)>-price-patch.md)을 매일 그 주 전체 일자로 재렌더한다.
_WD_KR = ["월", "화", "수", "목", "금", "토", "일"]


def _iso_week_bounds(date_str):
    """날짜 → 그 ISO 주의 (월요일, 일요일) ISO 문자열."""
    d = datetime.date.fromisoformat(date_str)
    mon = d - datetime.timedelta(days=d.weekday())
    return mon.isoformat(), (mon + datetime.timedelta(days=6)).isoformat()


def _date_label_kr(date_str):
    d = datetime.date.fromisoformat(date_str)
    return f"{d.month}월 {d.day}일 ({_WD_KR[d.weekday()]})"


def _demote_headings(text):
    """본문 markdown 헤딩을 한 단계 낮춘다(## → ###). 주간 로그에서 하루 섹션(##)
    아래에 일일 본문을 끼울 때, 일일 본문의 ## 들을 ###로 내려 계층을 맞춘다.
    HTML <details>/표 등 비-헤딩 라인은 영향 없음(라인 시작 #{2,5} 만 매칭)."""
    return re.sub(r'(?m)^(#{2,5}) ', r'#\1 ', text)


def _weekly_hotdeals(days):
    """주간 핫딜 집계 — 그 주 '돌파'(면세가 < 국내최저) 항목을 술별 1건으로 모은다.

    같은 술이 여러 날 돌파하면 **최신일 관측가**를 쓴다(days 는 최신→과거라 먼저 본 게
    최신). 절약률(절약/국내최저)↓ → 절약액↓ → 이름 순으로 정렬해 '제일 싼 딜'을 위로.
    보드 CMPA-644: '이번주 핫딜' 느낌으로 한 주 로그를 잘 정리해 모아 보여주기 위함."""
    seen, deals = set(), []
    for p in days:
        for r in p["breakthroughs"]:
            nm = r["name"]
            if nm in seen:
                continue
            seen.add(nm)
            deals.append(r)
    deals.sort(key=lambda r: (
        -((r["save"] / r["floor"]) if (r["save"] and r["floor"]) else 0),
        -(r["save"] or 0), r["name"]))
    return deals


def _hotdeal_fm_str(r):
    """핫딜 1건 → 홈 카드용 한 줄 요약(front matter 문자열). 예:
    '보모어 22년 700ml — 면세 ₩307,880 · 75%↓'."""
    pct = (r["save"] / r["floor"] * 100) if (r["save"] and r["floor"]) else None
    tail = f" · {pct:.0f}%↓" if pct is not None else ""
    return f'{r["name"]} — 면세 {_fmt_krw(r["krw"])}{tail}'


def _parse_fx_rate(fxstr):
    """'₩1,536.01 (기준일 …)' → 1536.01 (float) | None."""
    if not fxstr:
        return None
    m = re.search(r"([\d,]+\.?\d*)", fxstr)
    return float(m.group(1).replace(",", "")) if m else None


def _days_price_index(days):
    """days 의 모든 관측 행에서 name → {krw, floor, floor_url} 색인(최신일 우선).

    '오랜만의 큰 인하' 항목의 면세 KRW·국내최저를 주간 로그 표시에 재사용한다."""
    idx = {}
    for p in days:                          # days[0]=최신 → 먼저 본 게 최신
        recs = (p.get("breakthroughs", []) + p.get("drops", []) + p.get("others", []))
        for r in recs:
            nm = r.get("name")
            if nm and nm not in idx:
                idx[nm] = {"krw": r.get("krw"), "floor": r.get("floor"),
                           "floor_url": r.get("floor_url")}
    return idx


_RARE_HEADER = ("| 🕰️ 위스키 | 상세 |\n"
                "|---|---|")


def _rare_fm_str(r, info, fx_rate):
    """홈 카드용 한 줄 — 이름 → 면세 인하가(₩) (−낙폭%). 보드 CMPA-644: '할인한 가격도 적어줘'."""
    info = info or {}
    krw = info.get("krw")
    if krw is None and fx_rate:
        krw = r["current_usd"] * fx_rate
    price = f" {_fmt_krw(krw)}" if krw is not None else ""
    return f'{r["name"]} →{price} (−{r["drop"]*100:.0f}%)'


def _rare_drop_row(r, info, fx_rate):
    """'오랜만의 큰 인하' 1건 → (위스키, 상세) 2컬럼 표 행.

    상세 = 면세가 · (국내최저) <br> −낙폭% · 그동안 baseline(거의 정상가·D% 할인) N일째 →
    지금 D'% 할인 · M/D 첫 인하. baseline KRW = 할인가_USD × FX(없으면 생략)."""
    info = info or {}
    krw = info.get("krw")
    if krw is None and fx_rate:
        krw = r["current_usd"] * fx_rate
    price_txt = f'면세 **{_fmt_krw(krw)}**' if krw is not None else "면세가 확인 필요"
    floor = info.get("floor")
    if floor is not None:
        url = info.get("floor_url")
        ftxt = _fmt_krw(floor)
        price_txt += f' · 국내최저 {f"[{ftxt} 🔗]({url})" if url else ftxt}'
    mo, da = r["drop_date"][5:7].lstrip("0"), r["drop_date"][8:10].lstrip("0")
    base_krw = (f'{_fmt_krw(r["baseline_usd"] * fx_rate)} ' if fx_rate else "")
    detail = (f'{price_txt}<br>**−{r["drop"]*100:.0f}% 인하** · '
              f'그동안 {base_krw}거의 정상가({r["base_disc"]:.0f}% 할인)로 {r["flat_days"]}일째 '
              f'→ {r["cur_disc"]:.0f}% 할인 · {mo}/{da} 첫 인하')
    return f'| {r["name"]} | {detail} |'


def render_weekly_log(week_start, week_end, days):
    """한 ISO 주의 일일 패치들(최신→과거 정렬)을 시간역순 로그 1글로 렌더.

    days: classify_patch 적용된 parsed dict 리스트, **최신 latest_date 가 [0]**.
    front matter 의 kind=patch 를 유지해 기존 /cask/ 스트림·시리즈 내비·홈 최신 노출이
    그대로 동작한다(cadence=weekly 로 '주간 로그' 배지만 구분).
    본문은 ① 🔥 이번주 핫딜(주간 집계) → ② 🗓️ 날짜별 로그(시간역순) 2부 구성.
    홈 '이번주 핫딜' 카드용으로 hotdeals(상위 5줄)·hotdeals_count 를 front matter 에 싣는다."""
    ws = datetime.date.fromisoformat(week_start)
    we = datetime.date.fromisoformat(week_end)
    rng = f"{ws.month}/{ws.day}~{we.month}/{we.day}"
    newest = days[0]
    bks = newest["breakthroughs"]
    deals = _weekly_hotdeals(days)
    # CMPA-644 후속: '오랜만의 큰 인하' — 거의 정상가로 오래 고정됐다가 이번 주 처음 ≥20%
    # 떨어진 품목(잔잔한 변동·상시할인 제외). 스냅샷 히스토리(할인가_USD) 분석.
    try:
        rares = detect_rare_drops.rare_drops(week_start, week_end)
    except Exception:
        rares = []                      # 데이터 없으면 섹션 생략(비치명)
    fx_rate = _parse_fx_rate(newest.get("fx"))
    price_idx = _days_price_index(days)
    fm = front_matter({
        "layout": "post",
        "title": f"[신라면세] 가격변동 주간 로그 ({rng})",
        "date": f"{week_start} 09:00:00 +0900",
        "categories": ["price"],
        "kind": "patch",
        "cadence": "weekly",
        "breakthroughs": len(bks),
        "prev_date": days[-1]["prev_date"],
        "latest_date": newest["latest_date"],
        "weekly_start": week_start,
        "weekly_end": week_end,
        "days": len(days),
        "hotdeals": [_hotdeal_fm_str(r) for r in deals[:5]],
        "hotdeals_count": len(deals),
        "rare_drops": [_rare_fm_str(r, price_idx.get(r["name"]), fx_rate)
                       for r in rares[:5]],
        "rare_drops_count": len(rares),
        "description": (f"면세 위스키 가격 주간 로그 {rng} — 이번주 핫딜 {len(deals)}종 · "
                        f"오랜만의 큰 인하 {len(rares)}종 · 최신 {newest['latest_date']}. "
                        f"{brand.NAME_EN}"),
        "robots": "noindex,nofollow",
    })
    body = [fm, ""]
    body.append("이 글은 신라면세 위스키 가격변동을 **하루 단위로 아래에 쌓는 주간 "
                f"로그**입니다. 위에 이번주 핫딜을 모았고, 아래는 날짜별 상세(최신이 맨 위) · "
                f"기간 {week_start} ~ {week_end}.")
    body.append("")

    # ① 🔥 이번주 핫딜 — 주간 집계(면세 < 국내최저, 술별 최신가 1건).
    if deals:
        body.append(f"## 🔥 이번주 핫딜 ({len(deals)}종)")
        body.append("")
        body.append("_이번 주 면세가가 국내최저가보다 싼 위스키를 모았습니다. "
                    "각 항목은 그 주 최신 관측가 기준 · 절약률 높은 순._")
        body.append("")
        body.append(_BK_HEADER)
        for r in deals:
            body.append(_bk_row(r))
        body.append("")
        body.append("---")
        body.append("")

    # ①.5 🕰️ 오랜만의 큰 인하 — 원래 거의 정상가였다가 이번 주 처음 ≥20% 떨어진 품목.
    #     '계속 할인/잔잔한 변동'은 제외(보드 CMPA-644 후속). 드물게 잡히는 게 정상.
    if rares:
        body.append(f"## 🕰️ 신라면세 오랜만의 큰 인하 ({len(rares)}종)")
        body.append("")
        body.append("_원래 거의 정상가였다가 **이번 주 처음으로 20% 넘게 떨어진** "
                    "위스키입니다. 늘 할인하거나 잔잔히 오르내리는 건 제외 · 낙폭 큰 순._")
        body.append("")
        body.append(_RARE_HEADER)
        for r in rares:
            body.append(_rare_drop_row(r, price_idx.get(r["name"]), fx_rate))
        body.append("")
        body.append("---")
        body.append("")

    # ② 🗓️ 날짜별 로그 — 시간역순(최신 맨 위). 각 날 = ## 📅 섹션, 일일 본문은 ### 강등.
    for i, p in enumerate(days):
        head = f'## 📅 {_date_label_kr(p["latest_date"])}'
        if p["breakthroughs"]:
            head += f' — 돌파 {len(p["breakthroughs"])}건'
        body.append(head)
        body.append("")
        body.append(_demote_headings("\n".join(_patch_body_lines(p))))
        body.append("")
        if i != len(days) - 1:
            body.append("---")
            body.append("")
    return "\n".join(body).rstrip() + "\n"


# ── 베이스(이달의 본편) → Markdown ───────────────────────────────────
def _strip_h1(md_text):
    """초안 첫 '# ...' 헤더를 분리(제목은 front matter 로). (title, rest) 반환."""
    lines = md_text.splitlines()
    title = None
    rest_start = 0
    for idx, ln in enumerate(lines):
        if ln.startswith("# "):
            title = ln[2:].strip()
            rest_start = idx + 1
            break
    rest = "\n".join(lines[rest_start:]).lstrip("\n")
    return title, rest


def render_base_md(src_path, base_date):
    """에디토리얼 초안 → Jekyll 본편 포스트(front matter + 가공 콘텐츠)."""
    raw = open(src_path, encoding="utf-8").read()
    _, body = _strip_h1(raw)   # 에디토리얼 H1 은 본문에서 제거(제목은 아래 고정값).
    # 보드 CMPA-197: 면세 본편 제목은 담백하게 고정 + [신라면세] 프리픽스(매월 동일).
    title = "[신라면세] 위스키 가격 분석 및 추천"

    fm = front_matter({
        "layout": "post",
        "title": title,
        "date": f"{base_date} 08:00:00 +0900",
        "categories": ["price"],
        "kind": "base",
        "base_date": base_date,
        "description": f"{title} — {brand.NAME_EN}",
        "robots": "noindex,nofollow",
    })
    out = [fm, ""]
    # CMPA-156 면책 보장: 소스에 '수집일 기준값' 표현이 없으면 표준 면책 주입.
    if "수집일 기준값" not in raw:
        out.append(f"> {COLLECT_DISCLAIMER}")
        out.append("")
    out.append(body.rstrip())
    out.append("")
    return out_join(out)


def out_join(parts):
    return "\n".join(parts)


def _pick_base_src(report_dir):
    """가장 최신 에디토리얼 초안(날짜 in 파일명)을 본편 소스로 선택."""
    cands = []
    for pat in BASE_SRC_PATTERNS:
        for p in glob.glob(os.path.join(report_dir, pat)):
            m = DATE_IN_NAME.search(os.path.basename(p))
            if m:
                # 패턴 우선순위(draft 먼저) + 날짜로 정렬
                prio = BASE_SRC_PATTERNS.index(pat)
                cands.append((m.group(1), -prio, p))
    if not cands:
        return None
    cands.sort()  # 날짜 오름차순 → 마지막이 최신, 동일 날짜면 prio 큰(=draft) 우선
    date, _negprio, path = cands[-1]
    return date, path


# ── Jekyll 사이트 스캐폴드(self-contained) ──────────────────────────
def _css():
    """Satellite-스타일 스킨(CaskCode 팔레트) — CMPA-183.

    바이안코55 'Satellite' 테마의 시그니처 룩(좌측 프로필 사이드바 · 터미널 윈도우
    콘텐츠 카드[빨강·노랑·초록 신호등 닷] · 별이 흐르는 배경)을 **self-contained·
    JS 0**(CSS만)으로 재현한다. 색/이름은 CaskCode(brand.CSS_VARS) 로 오버라이드
    (이슈 '테마 위에 brand 팔레트 오버라이드'). GitHub Pages 네이티브 빌드 호환 유지.

    마크다운 렌더 결과(h1/h2/h3/p/ul/table/blockquote/strong/del)도 동일 카드 안에서
    스타일. 별 배경은 결정론(고정 좌표 radial-gradient) — Math.random 미사용."""
    v = brand.CSS_VARS
    fb, fm = brand.FONT_BODY, brand.FONT_MONO
    vars_css = ";".join(f"--{k}:{val}" for k, val in v.items())
    return f""":root{{{vars_css};--side:248px;--read:1040px}}
*{{box-sizing:border-box}}
html,body{{margin:0}}
body{{background:var(--bg);color:var(--txt);
font-family:{fb};line-height:1.65;font-size:16px}}
a{{color:var(--amber);text-decoration:none}}
a:hover{{text-decoration:underline}}
/* ── Satellite 시그니처: 별이 흐르는 배경(CSS만·결정론·JS 0) ── */
.stars{{position:fixed;inset:0;z-index:-1;background:var(--bg);overflow:hidden}}
.stars::before,.stars::after{{content:"";position:absolute;inset:-50%;
background-image:radial-gradient(1.4px 1.4px at 20% 30%,#fff 50%,transparent),
radial-gradient(1.2px 1.2px at 70% 60%,#cfd3da 50%,transparent),
radial-gradient(1.6px 1.6px at 45% 80%,var(--amber) 50%,transparent),
radial-gradient(1px 1px at 85% 25%,#fff 50%,transparent),
radial-gradient(1.3px 1.3px at 33% 50%,#aab 50%,transparent),
radial-gradient(1.1px 1.1px at 60% 15%,#fff 50%,transparent);
background-size:340px 340px;opacity:.5;
animation:drift 90s linear infinite}}
.stars::after{{background-size:520px 520px;opacity:.3;animation-duration:160s}}
@keyframes drift{{from{{transform:translateY(0)}}to{{transform:translateY(-340px)}}}}
@media (prefers-reduced-motion:reduce){{.stars::before,.stars::after{{animation:none}}}}
/* ── 좌측 프로필 사이드바 ── */
.app{{display:block}}
.sidebar{{position:fixed;top:0;left:0;bottom:0;width:var(--side);overflow-y:auto;
background:linear-gradient(180deg,var(--panel),rgba(15,17,21,.96));
border-right:1px solid var(--line);box-shadow:4px 0 18px rgba(0,0,0,.35);
text-align:center;padding:26px 16px 18px;z-index:2}}
.avatar{{display:flex;align-items:center;justify-content:center;width:96px;height:96px;
margin:6px auto 14px;border-radius:50%;background:radial-gradient(circle at 35% 30%,
var(--gold),var(--amber) 70%);color:#1a1300;font-size:42px;line-height:1;
box-shadow:0 0 0 6px rgba(224,168,78,.18),0 6px 18px rgba(0,0,0,.4);
transition:box-shadow .3s}}
.avatar:hover{{box-shadow:0 0 0 4px var(--amber),0 6px 18px rgba(0,0,0,.5);text-decoration:none}}
.sidebar .flap{{font-family:{fm};font-size:20px;font-weight:800;letter-spacing:.14em;
color:var(--gold)}}
.sidebar .flap .dot{{color:var(--amber)}}
.sidebar .handle{{color:var(--sub);font-size:12.5px;margin-top:5px}}
.snav{{list-style:none;padding:0;margin:18px 0;display:flex;flex-direction:column;gap:2px}}
.snav a{{display:block;padding:9px 12px;border-radius:8px;color:var(--txt);font-size:14px;
text-align:left}}
.snav a:hover{{background:rgba(224,168,78,.12);color:var(--gold);text-decoration:none}}
.side-foot{{margin-top:18px;padding-top:14px;border-top:1px solid var(--line);
color:var(--sub);font-size:11.5px;text-align:left}}
.side-foot .about{{color:#cfd3da;margin-bottom:8px}}
.side-foot .gate{{color:var(--red);font-weight:700}}
/* ── 메인: 터미널 윈도우 카드 ── */
.content{{margin-left:var(--side);padding:34px 22px 72px;
display:flex;flex-direction:column;align-items:center}}
.window{{width:100%;max-width:var(--read);background:rgba(22,25,34,.92);
border:1px solid var(--line);border-radius:14px;overflow:hidden;
box-shadow:0 12px 40px rgba(0,0,0,.45);backdrop-filter:blur(2px)}}
.titlebar{{display:flex;gap:8px;align-items:center;padding:11px 15px;
background:rgba(0,0,0,.25);border-bottom:1px solid var(--line)}}
.tdot{{width:12px;height:12px;border-radius:50%}}
.tdot.r{{background:#f86158}}.tdot.y{{background:#fbbf2d}}.tdot.g{{background:#2acb45}}
.titlebar .name{{margin-left:8px;font-family:{fm};font-size:12px;color:var(--sub)}}
/* 본문 글꼴 — 보드 2026-06-29 "글 폰트가 너무 크다"(2차) → 16px 상속 → 14px 로 축소.
   웹 본문 표준은 보통 15~16px(브라우저 기본 16px)이라 14px 는 '조밀한' 축에 속한다.
   가독성상 본문은 ~13.5px 아래로는 권장하지 않음(표/blockquote 13.5 와 충돌·잔글씨화).
   표(13.5)·blockquote(13.5)·제목(h1~h3 별도)·홈 카드(explicit)는 각자 크기 유지. */
.post{{padding:22px 24px 26px;font-size:14px;line-height:1.6}}
.sub{{color:var(--sub);font-size:12.5px}}
.post h1{{font-family:{fm};font-size:22px;margin:18px 0 6px;color:var(--txt)}}
.post h2{{font-family:{fm};font-size:16px;color:var(--amber);margin:26px 0 10px}}
.post h3{{font-size:15.5px;margin:16px 0 4px;color:var(--txt)}}
.post p{{margin:8px 0}}
.post strong{{color:var(--gold)}}
.post del{{color:var(--sub)}}
/* CMPA-292 보드: 데스크톱 넓은 화면에서 세로 사진이 읽기폭(1040px)만큼 커지는 문제 →
   이미지 max-width를 480px로 캡(min(100%,480px)). 좁은 모바일은 100%라 안 넘침. 가운데 정렬.
   이 규칙은 .post img 전역이라 앞으로의 모든 블로그 글 그림에 자동 적용된다. */
.post img{{display:block;max-width:min(100%,480px);height:auto;margin:12px auto;
border-radius:8px;border:1px solid var(--line)}}
.post blockquote{{background:rgba(224,168,78,.10);border-left:3px solid var(--amber);
color:#d9d2c2;font-size:13.5px;padding:9px 12px;border-radius:6px;margin:12px 0}}
/* CMPA-256 모바일 우선: 좁은 화면(≈360px)에서 표가 넓어져도 글을 가리지 않게
   가로 스크롤 폴백을 보장(overflow-x:auto). overflow:hidden 금지(글 잘림 금지). */
.post table{{display:block;overflow-x:auto;-webkit-overflow-scrolling:touch;border-collapse:collapse;width:100%;margin:12px 0;font-size:13.5px}}
.post th,.post td{{border:1px solid var(--line);padding:6px 9px;text-align:left;word-break:keep-all}}
.post th{{background:var(--panel);color:var(--amber);font-family:{fm}}}
.post hr{{border:0;border-top:1px solid var(--line);margin:22px 0}}
.post ul{{padding-left:18px}}
.post li{{margin:4px 0}}
.post code{{font-family:{fm};font-size:12.5px;background:rgba(0,0,0,.3);
padding:1px 5px;border-radius:4px}}
.archive{{list-style:none;padding:0;margin:8px 0}}
.archive li{{padding:10px 0;border-bottom:1px solid var(--line)}}
.archive .when{{font-family:{fm};color:var(--amber);font-weight:700;margin-right:6px}}
.badge{{display:inline-block;font-family:{fm};font-weight:800;font-size:11.5px;
padding:2px 9px;border-radius:999px;margin-left:6px}}
.badge.instant{{background:rgba(255,211,78,.16);color:var(--gold)}}
.badge.digest{{background:rgba(154,160,170,.16);color:var(--sub)}}
.foot{{width:100%;max-width:var(--read);margin-top:26px;padding-top:16px;
border-top:1px solid var(--line);color:var(--sub);font-size:12.5px}}
.foot .about{{margin:8px 0;color:#cfd3da}}
.foot .gate{{color:var(--red);font-weight:700;margin-top:8px}}
.back{{display:inline-block;margin:0 0 8px;font-family:{fm};font-size:13px}}
/* ── 홈 허브: 2기둥 카드(💻 Code / 🥃 Cask) — CMPA-192 ── */
.hub{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin:18px 0 6px}}
.pillar-card{{display:flex;flex-direction:column;background:rgba(15,17,21,.55);
border:1px solid var(--line);border-radius:12px;padding:18px 18px 16px;
color:var(--txt);transition:border-color .2s,transform .2s,box-shadow .2s}}
.pillar-card:hover{{border-color:var(--amber);transform:translateY(-2px);
box-shadow:0 8px 22px rgba(0,0,0,.4);text-decoration:none}}
.pc-emoji{{font-size:34px;line-height:1}}
.pc-head{{display:flex;align-items:baseline;gap:8px;margin:8px 0 2px;flex-wrap:wrap}}
.pc-title{{font-family:{fm};font-size:19px;font-weight:800;color:var(--gold)}}
.pc-tag{{font-size:12.5px;color:var(--sub)}}
.pc-desc{{font-size:13px;color:#cfd3da;margin:4px 0 8px}}
.pc-count{{font-family:{fm};font-size:12px;color:var(--amber);font-weight:700}}
.pc-prev{{list-style:none;padding:0;margin:8px 0 12px;font-size:12.5px;color:var(--sub)}}
.pc-prev li{{padding:3px 0;border-bottom:1px solid rgba(42,46,56,.6)}}
.pc-prev .when{{font-family:{fm};color:var(--amber);margin-right:5px}}
.pc-go{{margin-top:auto;font-family:{fm};font-size:13px;color:var(--gold);font-weight:700}}
/* ── 홈 ① 시그니처 핀(🏆 본편 큰 카드) — CMPA-196 ── */
.pin{{display:flex;flex-direction:column;gap:7px;margin:18px 0 14px;
padding:18px 20px;border:1.5px solid var(--amber);border-radius:14px;
background:linear-gradient(180deg,rgba(224,168,78,.10),rgba(15,17,21,.55));
transition:transform .2s,box-shadow .2s}}
.pin:hover{{transform:translateY(-2px);box-shadow:0 10px 26px rgba(224,168,78,.20)}}
.pin .badge.pin-badge{{align-self:flex-start;margin-left:0;
background:rgba(224,168,78,.18);color:var(--gold)}}
.pin .pin-title{{font-family:{fm};font-size:18px;font-weight:800;
color:var(--gold);line-height:1.4}}
.pin .pin-title:hover{{text-decoration:underline}}
.pin .pin-date{{font-family:{fm};font-size:12px;color:var(--amber)}}
/* ── 홈 ② 최신 가격 패치 띠(⚡) — CMPA-196 ── */
.patch-strip{{display:flex;align-items:center;flex-wrap:wrap;gap:7px;
margin:0 0 14px;padding:9px 14px;border-radius:10px;font-size:13px;
background:rgba(255,211,78,.08);border:1px solid rgba(224,168,78,.35)}}
.patch-strip .ps-flag{{font-family:{fm};font-weight:800;color:var(--gold)}}
.patch-strip .ps-date{{font-family:{fm};font-size:12px;color:var(--sub)}}
.patch-strip .ps-title{{color:var(--txt);font-weight:600}}
.patch-strip .ps-title:hover{{color:var(--gold);text-decoration:underline}}
/* ── 홈 섹션 머리말(🆕 읽을거리 / 📊 가격 모아보기) — CMPA-294 ── */
.sec-head{{font-family:{fm};font-size:13px;font-weight:800;color:var(--gold);
letter-spacing:.2px;margin:18px 0 8px}}
/* ── 홈 ② 읽을거리 피드(시음·데이터분석·개발 — 💻/🥃 칩) — CMPA-294 ── */
.latest-feed{{list-style:none;padding:0;margin:0 0 6px}}
/* 🆕 읽을거리 피드 — 본문(16px) 상속이라 모바일에서 제목이 두 줄로 깨짐(보드 2026-06-29).
   글꼴을 줄여 한 줄에 더 들어오게 한다(날짜는 flex-shrink:0 로 제목에 공간 양보). */
.latest-feed li{{display:flex;align-items:baseline;gap:7px;padding:7px 0;
border-bottom:1px solid var(--line);font-size:13px;line-height:1.45}}
.latest-feed li a{{color:var(--txt)}}
.latest-feed .chip{{font-size:13px;line-height:1;flex-shrink:0}}
.latest-feed .when{{font-family:{fm};color:var(--amber);font-weight:700;font-size:11px;flex-shrink:0}}
/* 최신 데이터 리포트 레일(CMPA-388) — 케이던스 꼬리표(일간/주간/월간)를 행 끝으로.
   flex-shrink:0 로 좁은 폭에서도 안 뭉개짐, margin-left:auto 로 우측 정렬. */
.latest-feed .rail-cad{{margin-left:auto;flex-shrink:0;font-family:{fm};font-size:10.5px;
font-weight:700;color:var(--sub);background:rgba(224,168,78,.12);
border:1px solid rgba(224,168,78,.3);border-radius:999px;padding:1px 7px}}
/* ── 홈 ③ 가격 모아보기(아코디언: 신라면세 가격변동 / 위스키 가격리포트) — CMPA-294 ──
   클릭하면 <details> 가 열리며 최신순 목록 펼침. JS 0(네이티브 details). */
.price-groups{{display:flex;flex-direction:column;gap:10px;margin:0 0 20px}}
.pg-acc{{border:1px solid rgba(224,168,78,.35);border-radius:11px;
background:rgba(255,211,78,.06);overflow:hidden}}
.pg-acc[open]{{border-color:var(--amber)}}
.pg-acc summary{{display:flex;align-items:center;gap:10px;padding:13px 15px;
cursor:pointer;list-style:none;user-select:none}}
.pg-acc summary::-webkit-details-marker{{display:none}}
.pg-acc summary:hover .pg-title{{text-decoration:underline}}
.pg-emoji{{font-size:24px;line-height:1}}
.pg-title{{font-family:{fm};font-size:15px;font-weight:800;color:var(--gold)}}
.pg-meta{{font-family:{fm};font-size:12px;color:var(--sub)}}
.pg-caret{{margin-left:auto;color:var(--gold);font-size:13px;transition:transform .2s}}
.pg-acc[open] .pg-caret{{transform:rotate(180deg)}}
.pg-list{{list-style:none;margin:0;padding:0 15px 10px}}
.pg-list li{{display:flex;align-items:baseline;gap:8px;padding:7px 0;
border-top:1px solid rgba(42,46,56,.6);font-size:13.5px}}
.pg-list .when{{font-family:{fm};color:var(--amber);font-weight:700;font-size:12px;flex-shrink:0}}
.pg-list a{{color:var(--txt)}}
.pg-list a:hover{{color:var(--gold);text-decoration:underline}}
.pg-bk{{font-family:{fm};font-size:11px;color:var(--gold);flex-shrink:0}}
/* ── CMPA-370: 글 작성자 byline (제목·날짜 아래 보조 텍스트) ── */
.byline{{font-family:{fm};color:var(--sub);font-size:11.5px;margin:2px 0 6px}}
/* ── 글 하단 이전/다음 글 네비 — CMPA-294 보드 후속(목록 왕복 제거) ── */
/* CMPA-301: 시리즈(같은 카테고리) 내 이동 라벨 + 같은 시리즈 prev/next. */
.pn-series{{font-family:{fm};font-size:11.5px;font-weight:700;color:var(--sub);
margin:26px 0 0;letter-spacing:.02em}}
.pn-series + .post-nav{{margin-top:8px}}
.post-nav{{display:flex;gap:10px;margin:26px 0 4px;flex-wrap:wrap}}
.pn-link{{flex:1 1 0;min-width:180px;display:flex;flex-direction:column;gap:3px;
padding:11px 14px;border:1px solid var(--line);border-radius:10px;
background:rgba(15,17,21,.55);color:var(--txt);
transition:border-color .2s,transform .2s,box-shadow .2s}}
a.pn-link:hover{{border-color:var(--amber);transform:translateY(-2px);
box-shadow:0 8px 22px rgba(0,0,0,.4);text-decoration:none}}
.pn-next{{text-align:right;align-items:flex-end}}
.pn-dir{{font-family:{fm};font-size:11.5px;font-weight:700;color:var(--amber)}}
.pn-t{{font-size:13.5px;color:var(--txt);font-weight:600;line-height:1.4}}
.pn-empty{{border:0;background:none;box-shadow:none;pointer-events:none}}
/* ── 홈 대시보드 진입 CTA 버튼 (CMPA-505) ── */
.dash-cta{{display:flex;align-items:center;gap:12px;padding:14px 18px;margin:0 0 10px;
border:1.5px solid var(--gold);border-radius:12px;background:rgba(255,211,78,.07);
color:var(--gold);font-family:{fm};font-size:14.5px;font-weight:800;text-decoration:none;transition:background .18s}}
.dash-cta:last-of-type{{margin-bottom:22px}}
.dash-cta:hover{{background:rgba(255,211,78,.15);text-decoration:none;color:var(--gold)}}
.dash-cta .dash-sub{{font-size:11.5px;font-weight:400;color:var(--sub);margin-left:auto;flex-shrink:0}}
/* ── 홈 🔥 이번주 핫딜 카드 (CMPA-644) — 최신 주간 로그의 핫딜 모음을 메인에 노출 ── */
.hotdeal-card{{display:block;padding:13px 15px;margin:0 0 22px;border:1.5px solid var(--gold);
border-radius:12px;background:rgba(255,211,78,.07);color:var(--txt);text-decoration:none;transition:background .18s}}
.hotdeal-card:hover{{background:rgba(255,211,78,.14);text-decoration:none}}
.hotdeal-card .hd-head{{display:flex;align-items:baseline;gap:8px;margin-bottom:8px;flex-wrap:wrap}}
.hotdeal-card .hd-title{{font-family:{fm};font-size:13.5px;font-weight:800;color:var(--gold)}}
.hotdeal-card .hd-when{{font-family:{fm};font-size:11px;color:var(--sub);margin-left:auto;flex-shrink:0}}
.hotdeal-list{{list-style:none;padding:0;margin:0 0 8px}}
.hotdeal-list li{{display:flex;align-items:baseline;gap:6px;padding:5px 0;
border-top:1px solid rgba(42,46,56,.6);font-size:12.5px;color:var(--txt);line-height:1.45}}
.hotdeal-list li:first-child{{border-top:0}}
.hotdeal-list .hd-fire{{flex-shrink:0}}
.hotdeal-card .hd-more{{display:inline-block;font-family:{fm};font-size:12px;font-weight:700;color:var(--gold)}}
/* ── 홈 최상단 🕰️ 오랜만의 큰 인하 카드 (CMPA-644 보드: 최상단) — 앰버/시계 강조 ── */
.rare-wrap{{margin:0 0 22px}}
.rare-card{{display:block;padding:13px 15px;border:1.5px solid var(--amber);border-radius:12px;
background:rgba(224,168,78,.09);color:var(--txt);text-decoration:none;transition:background .18s}}
.rare-card:hover{{background:rgba(224,168,78,.16);text-decoration:none}}
.rare-card .rare-head{{display:flex;align-items:baseline;gap:8px;margin-bottom:8px;flex-wrap:wrap}}
.rare-card .rare-title{{font-family:{fm};font-size:13.5px;font-weight:800;color:var(--amber)}}
.rare-card .rare-when{{font-family:{fm};font-size:11px;color:var(--sub);margin-left:auto;flex-shrink:0}}
.rare-list{{list-style:none;padding:0;margin:0 0 8px}}
.rare-list li{{display:flex;align-items:baseline;gap:6px;padding:5px 0;
border-top:1px solid rgba(42,46,56,.6);font-size:12.5px;color:var(--txt);line-height:1.45}}
.rare-list li:first-child{{border-top:0}}
.rare-list .rare-mark{{flex-shrink:0}}
.rare-card .rare-more{{display:inline-block;font-family:{fm};font-size:12px;font-weight:700;color:var(--amber)}}
/* ── 🗓️ 업데이트 로그(릴리스 노트) 카드 — 홈 맨 아래(CMPA-687) ── rare/hotdeal 패턴 동형 */
.cl-wrap{{margin:0 0 22px}}
.cl-card{{display:block;padding:13px 15px;border:1px solid var(--line);border-radius:12px;
background:rgba(255,211,78,.05);color:var(--txt);text-decoration:none;transition:background .18s}}
.cl-card:hover{{background:rgba(255,211,78,.11);text-decoration:none}}
.cl-card .cl-head{{display:flex;align-items:baseline;gap:8px;margin-bottom:8px;flex-wrap:wrap}}
.cl-card .cl-title{{font-family:{fm};font-size:13.5px;font-weight:800;color:var(--gold)}}
.cl-card .cl-when{{font-family:{fm};font-size:11px;color:var(--sub);margin-left:auto;flex-shrink:0}}
.cl-list{{list-style:none;padding:0;margin:0 0 8px}}
.cl-list li{{display:flex;align-items:baseline;gap:6px;padding:5px 0;
border-top:1px solid rgba(42,46,56,.6);font-size:12.5px;color:var(--txt);line-height:1.45}}
.cl-list li:first-child{{border-top:0}}
.cl-list .cl-ic{{flex-shrink:0}}
.cl-card .cl-more{{display:inline-block;font-family:{fm};font-size:12px;font-weight:700;color:var(--gold)}}
/* ── 💱 면세 vs 국내 gap 텍스트 캐러셀 — 홈 상단(CMPA-693 보드 2026-06-29) ──
   기본 = line 1 정적 노출, JS(모션 허용)면 4s 자동회전·호버/포커스 일시정지.
   prefers-reduced-motion(또는 JS 미동작) = 전체 정적 목록(글 안 숨김). 외부 의존 0. */
.gapc-wrap{{margin:0 0 18px;border:1px solid rgba(255,211,78,.30);border-radius:12px;
padding:11px 14px;background:linear-gradient(180deg,rgba(255,211,78,.06),rgba(15,17,21,.30))}}
.gapc-head{{display:flex;align-items:baseline;gap:8px;margin-bottom:7px;flex-wrap:wrap}}
.gapc-title{{font-family:{fm};font-size:13px;font-weight:800;color:var(--gold)}}
.gapc-when{{font-family:{fm};font-size:11px;color:var(--sub);margin-left:auto;flex-shrink:0}}
.gapc-lnk{{display:block;color:var(--txt);text-decoration:none}}
.gapc-lnk:hover{{text-decoration:none;color:inherit}}
.gapc-track{{list-style:none;margin:0;padding:0}}
/* 회전=세로 전환(한 줄씩), 긴 줄은 marquee=가로 흐름(보드 2026-06-29). 기본 1번째 줄 정적. */
.gapc-item{{display:none;font-size:13px;line-height:1.6;color:var(--txt)}}
.gapc-txt{{display:inline-block;white-space:nowrap}}
.gapc-track .gapc-item:first-child{{display:block;white-space:normal}}
.gapc-track .gapc-item:first-child .gapc-txt{{white-space:normal}}
.gapc-track.gapc-on .gapc-item{{display:none;white-space:nowrap;overflow:hidden}}
.gapc-track.gapc-on .gapc-item.gapc-cur{{display:block;animation:gapcfade .5s ease}}
.gapc-track.gapc-on .gapc-item.gapc-marq .gapc-txt{{animation:gapcmarq var(--marq-dur,8s) ease-in-out infinite alternate}}
@keyframes gapcfade{{from{{opacity:0}}to{{opacity:1}}}}
@keyframes gapcmarq{{from{{transform:translateX(0)}}to{{transform:translateX(var(--marq-shift,0))}}}}
.gapc-more{{display:inline-block;margin-top:5px;font-family:{fm};font-size:11.5px;
font-weight:700;color:var(--gold)}}
/* 모션 최소화 시 회전·marquee 끄고 전체 정적 목록(줄바꿈 허용·글 안 숨김 — CLAUDE.md). */
@media (prefers-reduced-motion:reduce){{
.gapc-item,.gapc-track.gapc-on .gapc-item{{display:block !important;white-space:normal !important;
overflow:visible !important;animation:none !important;padding:5px 0;
border-top:1px solid rgba(42,46,56,.55)}}
.gapc-txt{{white-space:normal !important;animation:none !important;transform:none !important}}
.gapc-track .gapc-item:first-child{{border-top:0}}
}}
/* ── 홈 구매상황 2대 축 패널(🛫 면세점 / 🛒 마트) — CMPA-673 보드 2026-06-28 ──
   보드: 면세점/마트가 두 개의 큰 축이니 섹션을 또렷이 구분. 각 축을 색이 다른
   테두리 패널로 묶어 한눈에 두 블록으로 읽히게 한다. (면세=하늘색, 마트=초록색) */
.buy-section{{border:1px solid var(--line);border-radius:14px;padding:14px 14px 6px;margin:0 0 18px}}
.buy-section.df{{border-color:rgba(122,182,240,.45);background:linear-gradient(180deg,rgba(122,182,240,.08),rgba(15,17,21,.30))}}
.buy-section.mart{{border-color:rgba(94,212,122,.42);background:linear-gradient(180deg,rgba(94,212,122,.07),rgba(15,17,21,.30))}}
.bs-head{{display:flex;align-items:center;gap:11px;margin:2px 0 12px}}
.bs-ic{{font-size:26px;line-height:1;flex-shrink:0}}
.bs-txt{{display:flex;flex-direction:column;min-width:0}}
.bs-title{{font-family:{fm};font-size:16px;font-weight:800;line-height:1.25}}
.buy-section.df .bs-title{{color:#8ec2f5}}
.buy-section.mart .bs-title{{color:#6fdc8c}}
.bs-sub{{font-size:12px;color:var(--sub);margin-top:2px;line-height:1.35}}
.buy-section .dash-cta,.buy-section .dash-cta:last-of-type{{margin:0 0 8px}}
.buy-section .rare-wrap,.buy-section .hotdeal-wrap{{margin:0 0 8px}}
.buy-section .sec-head{{margin:10px 0 6px}}
/* ── 반응형: 좁은 화면이면 사이드바를 상단 배너로 ── */
@media (max-width:820px){{
.sidebar{{position:static;width:auto;height:auto;bottom:auto;border-right:0;
border-bottom:1px solid var(--line);box-shadow:0 4px 12px rgba(0,0,0,.3);
padding:20px 16px 14px}}
.avatar{{width:72px;height:72px;font-size:32px}}
.snav{{flex-direction:row;flex-wrap:wrap;justify-content:center;gap:4px;margin:12px 0 6px}}
.snav a{{text-align:center}}
.side-foot{{text-align:center}}
/* CMPA-673 보드: 모바일에서 버려지는 좌우 마진을 줄여 본문 width 를 최대로 쓴다.
   .content(7px)+.window border(1px)+.post(12px) = 한쪽 20px 만 인셋(글이 가장자리에
   닿지 않는 최소). 데스크톱 값(.content 22/14·.post 24)은 그대로 두고 모바일만 좁힌다. */
.content{{margin-left:0;padding:16px 7px 56px}}
.post{{padding:18px 12px 22px}}
.buy-section{{padding:11px 9px 3px}}
.hub{{grid-template-columns:1fr}}
.post-nav{{flex-direction:column}}
/* CMPA-667: 좁은 화면에선 메인 CTA 카드를 세로로 쌓아 제목이 한 글자씩 잘리지 않게 한다.
   base 규칙의 flex row + .dash-sub flex-shrink:0 가 제목을 1글자 폭으로 짜부라뜨리던 문제 수정. */
.dash-cta{{flex-direction:column;align-items:flex-start;gap:5px;line-height:1.4}}
.dash-cta .dash-sub{{margin-left:0;font-size:12px}}
.sec-head{{font-size:13.5px;line-height:1.45}}
/* 🆕 읽을거리: 모바일에서 제목 두 줄 깨짐 완화(보드 2026-06-29) — 글꼴·여백 한 단계 더 축소. */
.latest-feed li{{font-size:12px;gap:6px;padding:6px 0}}
.latest-feed .chip{{font-size:12px}}
.latest-feed .when{{font-size:10.5px}}
}}
"""


def _layout_default():
    """Jekyll 기본 레이아웃 — Satellite-스타일 스킨(좌측 프로필 사이드바 + 터미널
    윈도우 콘텐츠 카드 + 별 배경) + CaskCode 브랜딩 + noindex 게이트(CMPA-183).
    CSS 는 외부 파일(assets/css/style.css). 별/사이드바는 CSS만(JS 0)."""
    e = brand.html.escape
    # HANDLE 제거(CMPA-195) → 빈 값이면 사이드바 handle div·푸터 ' · 핸들' 꼬리 미렌더.
    handle_div = f'<div class="handle">{e(brand.HANDLE)}</div>' if brand.HANDLE else ""
    foot_name = (f"{e(brand.NAME_EN)} · {e(brand.HANDLE)}"
                 if brand.HANDLE else e(brand.NAME_EN))
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{{{{ page.description | default: site.description }}}}">
<meta name="robots" content="{{{{ page.robots | default: 'noindex,nofollow' }}}}">
<title>{{{{ page.title }}}} — {e(brand.NAME_EN)}</title>
<link rel="stylesheet" href="{{{{ '/assets/css/style.css' | relative_url }}}}">
<link rel="manifest" href="{{{{ '/site.webmanifest' | relative_url }}}}">
<meta name="theme-color" content="#0f1115">
<link rel="icon" type="image/svg+xml" href="{{{{ '/assets/icons/icon.svg' | relative_url }}}}">
<link rel="icon" type="image/png" sizes="32x32" href="{{{{ '/assets/icons/favicon-32.png' | relative_url }}}}">
<link rel="icon" type="image/png" sizes="16x16" href="{{{{ '/assets/icons/favicon-16.png' | relative_url }}}}">
<link rel="apple-touch-icon" sizes="180x180" href="{{{{ '/assets/icons/apple-touch-icon-180.png' | relative_url }}}}">
<meta name="apple-mobile-web-app-title" content="CaskCode">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
</head>
<body>
<div class="stars" aria-hidden="true"></div>
<div class="app">
<aside class="sidebar">
  <a class="avatar" href="{{{{ '/' | relative_url }}}}" aria-label="홈">🥃</a>
  <a href="{{{{ '/' | relative_url }}}}" style="text-decoration:none">{brand.flap_html()}</a>
  {handle_div}
  <ul class="snav">
    <li><a href="{{{{ '/cask/' | relative_url }}}}">🥃 Cask</a></li>
    <li><a href="{{{{ '/code/' | relative_url }}}}">💻 Code</a></li>
    <li><a href="{{{{ '/dj/' | relative_url }}}}">🐷 Dram Jar</a></li>
    <li><a href="{{{{ '/about/' | relative_url }}}}">👤 About</a></li>
  </ul>
  <div class="side-foot">
    <div class="about">{e(brand.ABOUT)}</div>
  </div>
</aside>
<main class="content">
{{% unless page.url == '/' %}}<a class="back" href="{{{{ '/' | relative_url }}}}">← 블로그 홈</a>{{% endunless %}}
<div class="window">
  <div class="titlebar"><span class="tdot r"></span><span class="tdot y"></span><span class="tdot g"></span><span class="name">{e(brand.NAME_EN)}</span></div>
  <div class="post">
{{{{ content }}}}
  </div>
</div>
<div class="foot">
  <div>{foot_name}</div>
</div>
</main>
</div>
</body>
</html>
"""


def _layout_post():
    """글 레이아웃 — default(사이드바·noindex 메타·창 크롬)를 상속하고 제목/날짜만 덧붙인다.
    posts/drafts 가 `layout: post` 를 쓰므로 반드시 존재해야 한다. 없으면 Jekyll 4.x 빌드가
    'Layout post does not exist' 경고와 함께 크롬·noindex 없이 맨 HTML 조각으로 렌더한다
    (CMPA-188: github-pages/minima 의 post 레이아웃에 의존하던 잠복 버그).

    CMPA-294 보드 후속: 글 하단에 이전/다음 글 네비게이션 — 목록으로 안 돌아가도
    바로 옆 글로 이동.

    CMPA-301 보드 후속(CMPA-300): 네비를 **같은 시리즈(카테고리) 안으로 스코프**한다.
    기존엔 Jekyll 기본 page.previous/next 가 site.posts 전체를 시간순으로 가로질러
    가격변동 패치의 '다음 글'이 시음노트·개발글로 튀었다. 이제 같은 series 글만 모아
    그 안에서 이전/다음을 잇는다(별도 데이터·JS 0, 테마/플러그인 의존 없음).

    시리즈 키 규칙(결정론):
      kind=='patch' → 'shilla-patch' (신라면세 가격변동 패치)
      kind=='base'  → 'price-base'   (이달의 면세 본편 — patch 와 둘 다 categories=[price]라 kind로 가른다)
      그 외          → categories[0]  (wprice/tasting/data/dev — 손글 포함)
    front matter 에 page.series 가 명시돼 있으면 그것을 우선 사용(향후 확장 여지).
    site.posts 는 최신→과거 순이므로 시리즈 배열에서 prev(과거)=idx+1, next(최신)=idx-1."""
    return ("---\n"
            "layout: default\n"
            "---\n"
            "<h1>{{ page.title }}</h1>\n"
            '{% if page.date %}<p class="when">{{ page.date | date: "%Y-%m-%d" }}</p>{% endif %}\n'
            # ── CMPA-370: 작성자 byline — tasting(사람 취미)=CaskCode, 그 외(AI 자동산출)=Dram ──
            # (CMPA-400: invest 버킷 전면 제거 — 더는 byline 조건에 포함하지 않음)
            # (CMPA-406: front matter 의 `byline:` 명시값이 있으면 카테고리 기본값을 덮는다 —
            #  사람이 쓴 1인칭 일기(예: 캐스크 적금)를 dev 버킷에 두면서도 by CaskCode 로 표기하기 위함.
            #  보드 결정 2026-06-15.)
            "{% if page.byline %}"
            '<p class="byline">by {{ page.byline }}</p>'
            "{% elsif page.categories contains 'tasting' %}"
            '<p class="byline">by CaskCode</p>{% else %}<p class="byline">by Dram</p>{% endif %}\n'
            "{{ content }}\n"
            # ── CMPA-301: 현재 글의 시리즈 키 산출 ──
            "{% assign _cs = page.series %}\n"
            "{% if _cs == nil or _cs == '' %}\n"
            "  {% if page.kind == 'patch' %}{% assign _cs = 'shilla-patch' %}\n"
            "  {% elsif page.kind == 'base' %}{% assign _cs = 'price-base' %}\n"
            "  {% else %}{% assign _cs = page.categories | first %}{% endif %}\n"
            "{% endif %}\n"
            # ── 같은 시리즈 글만 모은다(최신→과거 순 유지) ──
            "{% assign _series = '' | split: '' %}\n"
            "{% for p in site.posts %}\n"
            "  {% assign _ps = p.series %}\n"
            "  {% if _ps == nil or _ps == '' %}\n"
            "    {% if p.kind == 'patch' %}{% assign _ps = 'shilla-patch' %}\n"
            "    {% elsif p.kind == 'base' %}{% assign _ps = 'price-base' %}\n"
            "    {% else %}{% assign _ps = p.categories | first %}{% endif %}\n"
            "  {% endif %}\n"
            "  {% if _ps == _cs %}{% assign _series = _series | push: p %}{% endif %}\n"
            "{% endfor %}\n"
            # ── 현재 글 인덱스 → 양옆 글 선택 ──
            "{% assign _idx = -1 %}\n"
            "{% for p in _series %}{% if p.url == page.url %}{% assign _idx = forloop.index0 %}{% break %}{% endif %}{% endfor %}\n"
            "{% assign _prev = nil %}{% assign _next = nil %}\n"
            "{% if _idx >= 0 %}\n"
            "  {% assign _pi = _idx | plus: 1 %}{% assign _ni = _idx | minus: 1 %}\n"
            "  {% if _pi < _series.size %}{% assign _prev = _series[_pi] %}{% endif %}\n"
            "  {% if _ni >= 0 %}{% assign _next = _series[_ni] %}{% endif %}\n"
            "{% endif %}\n"
            # ── 시리즈 라벨(독자에게 '무슨 글들 사이를 이동하나' 안내) ──
            "{% case _cs %}\n"
            "  {% when 'shilla-patch' %}{% assign _slabel = '신라면세 가격변동' %}\n"
            "  {% when 'price-base' %}{% assign _slabel = '면세 가성비 본편' %}\n"
            "  {% when 'wprice' %}{% assign _slabel = '위스키 가격정보' %}\n"
            "  {% when 'tasting' %}{% assign _slabel = '구매/시음/숙성 노트' %}\n"
            "  {% when 'data' %}{% assign _slabel = '데이터 분석' %}\n"
            "  {% when 'dev' %}{% assign _slabel = '개발' %}\n"
            "  {% else %}{% assign _slabel = nil %}{% endcase %}\n"
            "{% if _prev or _next %}\n"
            '{% if _slabel %}<p class="pn-series">📚 {{ _slabel }} 시리즈</p>{% endif %}\n'
            '<nav class="post-nav">\n'
            '  {% if _prev %}<a class="pn-link pn-prev" href="{{ _prev.url | relative_url }}">'
            '<span class="pn-dir">← 이전 글</span>'
            '<span class="pn-t">{{ _prev.title }}</span></a>'
            '{% else %}<span class="pn-link pn-empty"></span>{% endif %}\n'
            '  {% if _next %}<a class="pn-link pn-next" href="{{ _next.url | relative_url }}">'
            '<span class="pn-dir">다음 글 →</span>'
            '<span class="pn-t">{{ _next.title }}</span></a>'
            '{% else %}<span class="pn-link pn-empty"></span>{% endif %}\n'
            '</nav>\n'
            '{% endif %}\n')


def _robots_txt():
    """CMPA-270: 보드 승인 2026-06-09 — 선택 noindex go-live. 실효 게이트=페이지별 robots 메타.
    에디토리얼 글·홈·About·기둥 페이지는 index,follow; 데이터 앱·가격 글은 noindex 유지."""
    return ("---\n"
            "# CMPA-270: 선택 noindex go-live (보드 승인 2026-06-09).\n"
            "# 실효 게이트=페이지별 robots 메타(default.html 기본값=noindex,nofollow).\n"
            "# layout:none — 전역 defaults(layout:default)가 robots.txt 를 HTML 로 감싸지 않게.\n"
            "layout: none\n"
            "permalink: /robots.txt\n"
            "sitemap: false\n"
            "---\n"
            "User-agent: *\n"
            "Allow: /\n"
            "Sitemap: https://godaji.github.io/CaskCode/sitemap.xml\n")


def _config_yml():
    e = lambda s: str(s).replace('"', '\\"')
    # HANDLE 제거(CMPA-195) → 빈 author 줄을 두지 않고 키 자체를 생략.
    author_line = f'author: "{e(brand.HANDLE)}"\n' if brand.HANDLE else ""
    return f"""# {e(brand.NAME_EN)} — Jekyll 사이트 설정 (CMPA-178/182, 내부 스테이징)
# 외부 발행은 보드 게이트 c7405e7d 승인 후에만(현재 noindex 유지).
title: "{e(brand.NAME_EN)}"
description: "{e(brand.ABOUT)}"
{author_line}lang: ko
# GitHub Pages 프로젝트 사이트(godaji/CaskCode) — https://godaji.github.io/CaskCode/ (CMPA-188).
# Actions 빌드는 configure-pages 가 base_path 를 자동 주입해 baseurl 을 덮어쓴다.
# 아래 값은 로컬/Docker 빌드 패리티용(레포명·도메인 변경 시 함께 수정).
url: "https://godaji.github.io"
baseurl: "/CaskCode"
# 포스트 날짜(+0900)와 permalink 날짜가 어긋나지 않도록 KST 고정
# (미설정 시 Jekyll 기본 UTC → 06-07 +0900 글이 06-06 으로 하루 밀림).
timezone: Asia/Seoul
# 오늘 날짜(+0900)로 쓴 글이 '미래 글'로 분류돼 사라지지 않게(로컬/스테이징 편의).
future: true
markdown: kramdown
# GitHub 렌더러와 동일하게 GFM(테이블·자동링크 등). 취소선은 인라인 <del> 사용.
kramdown:
  input: GFM
  hard_wrap: false
permalink: /:year/:month/:day/:title/
# GitHub Pages 기본 빌드와 호환(테마 미사용 — 자체 _layouts).
defaults:
  - scope: {{ path: "" }}
    values: {{ layout: "default" }}
exclude:
  - README.md
  - Gemfile
  - Gemfile.lock
"""


# 기둥(##) 머리말 — 브랜드 2기둥. f-string 아님(Liquid 없음).
# 사이드바 nav 가 가리킬 안정적 앵커(__ID__) — HTML <span id> 라 kramdown/python-markdown
# 양쪽에서 그대로 통과(자동생성 id 의 이모지·em-dash 변형 의존 회피).
_PILLAR_HEAD = """
<span id="__ID__"></span>
## __EMOJI__ __LABEL__ — __TAGLINE__
*__DESC__*
"""

# 스트림(###) 공통 목록(data/tasting/cabin) — Liquid 리터럴(브레이스 비-f-string).
_STREAM_LIST = """
### __EMOJI__ __LABEL__
*__DESC__*

{% assign items = site.posts | where_exp: "p", "p.categories contains '__KEY__'" | sort: "date" | reverse %}
{% if items.size > 0 %}
<ul class="archive">
{% for p in items %}
  <li><span class="when">{{ p.date | date: "%Y-%m-%d" }}</span>
  <a href="{{ p.url | relative_url }}">{{ p.title }}</a></li>
{% endfor %}
</ul>
{% else %}
<div class="empty">아직 글이 없습니다.</div>
{% endif %}
"""

# 가격 스트림 — 본편/패치/주간을 Code 기둥 아래 ### 칸으로(####  과한 들여쓰기 제거,
# CMPA-180 보드 피드백 2026-06-07). kind 로 구분.
# CMPA-334: 주간 리포트(kind=weekly)도 이 목록에 포함 — 안 그러면 /cask/ 에 안 보인다
#           (보드 지적: 발행됐는데 /cask/ 목록 필터가 base/patch 만 잡아 누락).
_STREAM_PRICE = """
### 🏷️ 신라면세 위스키 정보
*면세 가성비 본편 + 주간 리포트 + 가격 패치 — 국내최저 돌파 (자동 생성)*

{% assign _bases = site.posts | where_exp: "p", "p.kind == 'base'" %}
{% assign _patches = site.posts | where_exp: "p", "p.kind == 'patch'" %}
{% assign _weeklies = site.posts | where_exp: "p", "p.kind == 'weekly'" %}
{% assign shilla_posts = _bases | concat: _weeklies | concat: _patches | sort: "date" | reverse %}
{% if shilla_posts.size > 0 %}
<ul class="archive">
{% for p in shilla_posts %}
  {% if p.kind == 'base' %}
  <li><span class="when">{{ p.base_date | default: p.date | date: "%Y-%m-%d" }}</span>
  <a href="{{ p.url | relative_url }}">{{ p.title }}</a></li>
  {% elsif p.kind == 'weekly' %}
  <li><span class="when">{{ p.weekly_end | default: p.date | date: "%Y-%m-%d" }}</span>
  <a href="{{ p.url | relative_url }}">{{ p.title }}</a>
  <span class="badge digest">📅 주간</span></li>
  {% elsif p.cadence == 'weekly' %}
  <li><span class="when">{{ p.latest_date | default: p.date | date: "%Y-%m-%d" }}</span>
  <a href="{{ p.url | relative_url }}">{{ p.title }}</a>
  <span class="badge digest">📅 주간 로그</span>
  {% if p.days %}<span class="sub">· {{ p.days }}일치 누적</span>{% endif %}</li>
  {% else %}
  <li><span class="when">{{ p.latest_date | default: p.date | date: "%Y-%m-%d" }}</span>
  <a href="{{ p.url | relative_url }}">{{ p.title }}</a>
  {% if p.cadence == 'instant' %}<span class="badge instant">⚡ 돌파</span>{% else %}<span class="badge digest">다이제스트</span>{% endif %}
  {% if p.breakthroughs > 0 %}<span class="sub">· 국내최저 돌파 {{ p.breakthroughs }}건</span>{% endif %}</li>
  {% endif %}
{% endfor %}
</ul>
{% else %}
<div class="empty">아직 글이 없습니다.</div>
{% endif %}
"""

# CMPA-289 보드: 라이브 /cask/ 하단 일기·숙성 태그 안내박스 제거(블로그 깔끔하게).
# (작성자용 동일 문구는 README.md 내부 가이드에만 남는다 — 독자에겐 안 보임.)

# 알려진 섹션 외 카테고리는 '기타'로 자동 노출(보드가 새 카테고리 쓰면 바로 보임).
# 표준 Liquid 만 사용(push 필터 없음) — capture 로 존재여부 판정.
_SECTION_OTHER = """
{% assign known = "__KNOWN__" | split: "," %}
{% capture _extras %}{% for cat in site.categories %}{% unless known contains cat[0] %}{{ cat[0] }},{% endunless %}{% endfor %}{% endcapture %}
{% if _extras != "" %}
## 🗂️ 기타 카테고리
{% for cat in site.categories %}{% unless known contains cat[0] %}
### {{ cat[0] }}
<ul class="archive">
{% for p in cat[1] %}
  <li><span class="when">{{ p.date | date: "%Y-%m-%d" }}</span>
  <a href="{{ p.url | relative_url }}">{{ p.title }}</a></li>
{% endfor %}
</ul>
{% endunless %}{% endfor %}
{% endif %}
"""


# 홈 허브 카드 1개(💻 Code / 🥃 Cask) — 기둥 페이지로 링크 + 최신 미리보기.
# baseurl(/CaskCode) 안전: 링크는 relative_url. f-string 아님(Liquid 리터럴).
_HUB_CARD = """  <a class="pillar-card" href="{{ '__PATH__' | relative_url }}">
    <div class="pc-emoji">__EMOJI__</div>
    <div class="pc-head"><span class="pc-title">__LABEL__</span><span class="pc-tag">__TAGLINE__</span></div>
    <p class="pc-desc">__DESC__</p>
    {% assign __VAR__ = site.posts | where_exp: "p", "__FILTER__" %}
    <div class="pc-count">글 {{ __VAR__.size }}편</div>
    <ul class="pc-prev">
    {% for p in __VAR__ limit: 3 %}
      <li><span class="when">{{ p.date | date: "%Y-%m-%d" }}</span> {{ p.title }}</li>
    {% endfor %}
    </ul>
    <span class="pc-go">목록 보기 →</span>
  </a>
"""


# 홈 본문(CMPA-294 grouping) — 히어로 .sub 다음, .hub 카드 앞에 삽입.
# 새 데이터·새 크롤 0 — 전부 site.posts 기존 필드(kind/base_date/latest_date/
# breakthroughs/categories) 재사용. f-string 아님(Liquid 리터럴). 빈 섹션은
# {% if %} 가드로 graceful 미렌더. div/ul 블록래퍼로 kramdown 안전(허브와 동일).

# ① 🗞️ 최신 데이터 리포트 — 케이던스별(일간·주간·월간) **가장 최신 1건**을 날짜와 함께
#   한 줄씩 (CMPA-388 보드: "오늘 만든 price-patch 같은 생생한 글을 홈에 바로 노출").
#   - 🗞️ 일간 = kind:patch 최신 1건(latest_date) — 매일 생성되는 신라면세 가격변동 패치.
#   - 📅 주간 = kind:weekly 최신 1건(weekly_end).
#   - 📆 월간 = kind:base 최신 1건(base_date) — **있을 때만**(CMPA-376에서 월간 정기발행
#     폐지 → 신규 월간 없음. 과거 base 글이 있으면 노출, 없으면 그 줄만 우아하게 생략).
#   - 📈 위스키시세 = kind:wprice 최신 1건(data_date) — CMPA-432 보드: 신규 wprice가
#     데이터 지문 게이트로 새로 써지면 홈 '최신 데이터 리포트'에도 자동 노출. noindex는 유지.
#   신선도 신호 = 각 줄에 날짜 노출. '오늘(== site.time)' 동등비교에 의존하지 않고 '최신 1건을
#   날짜와 함께' 보여줘 빌드 지연에도 빈 칸이 안 생기게 한다(CMPA-388 조사노트 Option A 함정 회피).
#   CMPA-334 보드: 큰 핀 카드는 과하다 → 읽을거리 피드(.latest-feed)처럼 작은 ul/li 목록.
#   balanced HTML(ul/li) — kramdown 안전(블록 div 중첩 회피). 새 데이터·크롤 0(site.posts 기존 필드만).
# ⓪ 메인 구매상황별 2섹션 — '면세점에서 구매할 때' / '마트에서 구매할 때' (CMPA-667 보드 2026-06-28).
#   보드: 면세 가격비교가 좋은 서비스가 됐으니 메인을 구매 상황으로 구분한다.
#     ① 맨 위 '면세점에서 구매할 때' → 신라-롯데-신세계 면세점 가격 비교(compare 글) +
#        기존 면세 하이라이트 카드(🕰️ 오랜만의 큰 인하 · 🔥 이번주 핫딜)를 이 섹션에 묶는다.
#     ② '마트에서 구매할 때' → 위스키 가격 대시보드(/dashboard/, 소매 floor).
#     ③ 브랜드 대시보드는 읽을거리로 이동(제목 '위스키 브랜드별 구매 팁') → _HOME_LATEST.
#   compare 글 파일명은 매 수집 날짜(prefix)라 정적 링크가 깨진다 → url 매칭으로 최신 1건 동적 링크.
#   정본(생성기)에 둔다 — 재생성 때 안 사라지게. kramdown 안전: sec-head <div> 앞 빈 줄 보존(트림 금지).
_HOME_DUTYFREE = """<div class="bs-head"><span class="bs-ic">🛫</span><div class="bs-txt"><div class="bs-title">면세점에서 구매할 때</div><div class="bs-sub">출국·입국 예정이라면 — 신라·롯데·신세계 면세 가격 비교</div></div></div>
{% assign _cmp = site.posts | where_exp: "p","p.url contains 'dutyfree-whisky-compare'" | sort: "date" | reverse %}
{% if _cmp.size > 0 %}<a class="dash-cta" href="{{ _cmp[0].url | relative_url }}">🥃 신라-롯데-신세계 면세점 가격 비교 →<span class="dash-sub">세 면세점 100ml당 최저가 비교</span></a>
{% endif %}
"""

# ②  '마트에서 구매할 때' — 위스키 가격 대시보드(국내 소매 floor) +
#     '면세점보다 싸거나 비슷한 위스키' 큐레이션 글(CMPA-669, 마트·국내가가 면세 이하).
#     compare/mart 글은 파일명에 수집날짜 prefix가 붙어 정적 링크가 깨지므로 url 매칭으로 최신 1건 동적 링크.
_HOME_MART = """<div class="bs-head"><span class="bs-ic">🛒</span><div class="bs-txt"><div class="bs-title">마트에서 구매할 때</div><div class="bs-sub">트레이더스·코스트코·이마트 등 국내 소매가</div></div></div>
<a class="dash-cta" href="{{ '/dashboard/' | relative_url }}">📊 위스키 가격 대시보드 →<span class="dash-sub">소매가 · 면세가 · 해외가 비교</span></a>
{% assign _mart = site.posts | where_exp: "p","p.url contains 'mart-cheaper-whisky'" | sort: "date" | reverse %}
{% if _mart.size > 0 %}<a class="dash-cta" href="{{ _mart[0].url | relative_url }}">🥃 면세점보다 싸거나 비슷한 위스키 →<span class="dash-sub">마트·국내가가 면세가 이하인 위스키</span></a>
{% endif %}
"""

# ① 🕰️ 오랜만의 큰 인하 — 홈 **최상단**(CMPA-644 보드 2026-06-27 "최상단으로 올려줘").
#   최신 주간 로그의 rare_drops(거의 정상가였다가 첫 ≥20% 인하)를 별도 카드로 맨 위에.
#   ⚠️ kramdown 안전: 카드는 **블록 <div> 래퍼 + 단일 라인 <a>**(빈 줄 0)로 둔다 — <a> 안에
#   블록 자식(div/ul)이 있을 때 빈 줄/인라인 시작이면 kramdown 이 <a></a> 를 빈 채로 닫아
#   '빈 버튼'이 된다(보드 지적). Liquid 제어태그는 {%- -%} 로 화이트스페이스 트림.
#   ⚠️ kramdown 2중 안전(보드 2026-06-27 재지적):
#     (a) 카드 <a> 는 **블록 <div class="*-wrap"> 래퍼 + 단일 물리 라인**(빈 줄 0) → <a> 가
#         빈 채로 닫히는 '빈 버튼' 방지(HTML5 transparent: <a> 안 블록 자식 OK).
#     (b) 제어 Liquid 는 **트림하지 않는다({% %}, {%- %} 금지)** → sec-head <div> 앞 빈 줄이
#         보존돼 kramdown 이 HTML 블록으로 인식. (트림하면 앞 블록에 붙어 &lt;div&gt; 로 escape.)
#   for/if 는 카드 단일 라인 '안'에서 인라인이라 빈 줄을 안 만든다.
_HOME_RARE = """{% assign _wl = site.posts | where_exp: "p","p.kind == 'patch' and p.cadence == 'weekly'" | sort: "date" | reverse %}
{% if _wl.size > 0 and _wl[0].rare_drops_count > 0 %}{% assign _r = _wl[0] %}
<div class="sec-head">🕰️ 신라면세 오랜만의 큰 인하 — 거의 정상가였다가 모처럼 큰 폭 인하</div>
<div class="rare-wrap"><a class="rare-card" href="{{ _r.url | relative_url }}"><div class="rare-head"><span class="rare-title">이번 주 {{ _r.rare_drops_count }}종 인하</span><span class="rare-when">{{ _r.latest_date | default: _r.weekly_end }} 기준</span></div><ul class="rare-list">{% for d in _r.rare_drops %}<li><span class="rare-mark">🕰️</span><span>{{ d }}</span></li>{% endfor %}</ul><span class="rare-more">자세히 보기 →</span></a></div>
{% endif %}
"""

# ①.5 🔥 이번주 핫딜 — 최신 주간 로그(kind=patch·cadence=weekly)의 핫딜 모음을 메인에 노출.
#   카드 클릭 → 그 주 로그 전문. 딜 줄 = 주간 로그 front matter 의 hotdeals(상위 5)·count 재사용.
#   kramdown 안전 규칙은 _HOME_RARE 위 주석 참조(블록 래퍼 + 단일 라인 + 트림 금지).
#   '오랜만의 큰 인하'는 _HOME_RARE 로 최상단 분리(보드).
_HOME_HOTDEALS = """{% assign _wlogs = site.posts | where_exp: "p","p.kind == 'patch' and p.cadence == 'weekly'" | sort: "date" | reverse %}
{% if _wlogs.size > 0 %}{% assign _w = _wlogs[0] %}
<div class="sec-head">🔥 이번주 핫딜 — 면세가가 국내최저보다 싼 위스키</div>
<div class="hotdeal-wrap"><a class="hotdeal-card" href="{{ _w.url | relative_url }}"><div class="hd-head"><span class="hd-title">{{ _w.title }}</span><span class="hd-when">{{ _w.latest_date | default: _w.weekly_end }} 기준</span></div>{% if _w.hotdeals and _w.hotdeals.size > 0 %}<ul class="hotdeal-list">{% for d in _w.hotdeals %}<li><span class="hd-fire">🔥</span><span>{{ d }}</span></li>{% endfor %}</ul>{% assign _rest = _w.hotdeals_count | minus: _w.hotdeals.size %}<span class="hd-more">{% if _rest > 0 %}+ {{ _rest }}종 더 · {% endif %}주간 로그 전체 보기 →</span>{% else %}<span class="hd-more">이번 주 가격 변동 로그 보기 →</span>{% endif %}</a></div>
{% endif %}
"""

# ② 🆕 읽을거리 피드 — 간헐 글(시음·데이터분석·개발)만 날짜 desc 5편 (CMPA-294).
#   고빈도 가격 글(price 패치/본편·wprice 리포트)은 제외 → 아래 ③ 그룹 카드로 묶음.
#   이렇게 해야 매일 쏟아지는 가격 글이 피드를 독식하지 않고 간헐 글이 항상 노출됨.
_HOME_LATEST = """<div class="sec-head">🆕 읽을거리</div>
<a class="dash-cta" href="{{ '/dashboard/brands/' | relative_url }}">🥃 위스키 브랜드별 구매 팁 →<span class="dash-sub">브랜드별 가치 추천 · 등급 사다리</span></a>
{% assign _editorial = site.posts | where_exp: "p","p.categories contains 'tasting' or p.categories contains 'data' or p.categories contains 'dev'" %}
{% if _editorial.size > 0 %}
<ul class="latest-feed">
{% for p in _editorial limit: 5 %}
  <li><span class="chip">{% if p.categories contains 'dev' or p.categories contains 'data' %}💻{% else %}🥃{% endif %}</span>
  <span class="when">{{ p.date | date: "%-m/%-d" }}</span>
  <a href="{{ p.url | relative_url }}">{{ p.title }}</a></li>
{% endfor %}
</ul>
{% endif %}
"""

# ③ 🗓️ 업데이트 로그(릴리스 노트) — 홈 **맨 아래**(CMPA-687 보드 2026-06-29 "메인 화면의 맨 아래").
#   데이터가 *언제* 갱신됐고(소스별 최신 수집일) *무엇이* 바뀌었는지(면세·소매 전일대비)를
#   release note 처럼 시간 역순으로 누적한 단일 로그 글(kind:changelog)의 최신 엔트리를 카드로.
#   요약 문자열(cl_sources/cl_shilla/cl_retail/log_date)은 changelog 글 front matter 에서 읽는다
#   (생성기 = pipelines/changelog/build_changelog.py). 새 데이터·크롤 0(site.posts 기존 필드만).
#   ⚠️ kramdown 안전: _HOME_RARE 패턴 그대로 — (a) 카드 <a> 는 **블록 <div class="cl-wrap"> 래퍼
#   + 단일 물리 라인**(빈 줄 0)로 '빈 버튼' 방지, (b) 제어 Liquid 는 **트림하지 않는다**
#   ({%- -%} 금지) → sec-head <div> 앞 빈 줄 보존 → kramdown 이 HTML 블록으로 인식.
_HOME_CHANGELOG = """{% assign _cl = site.posts | where_exp: "p","p.kind == 'changelog'" | sort: "date" | reverse %}
{% if _cl.size > 0 %}{% assign _c = _cl[0] %}
<div class="sec-head">🗓️ 업데이트 로그 — 데이터가 언제 갱신됐고 무엇이 바뀌었나</div>
<div class="cl-wrap"><a class="cl-card" href="{{ _c.url | relative_url }}"><div class="cl-head"><span class="cl-title">최근 업데이트</span><span class="cl-when">{{ _c.log_date }} 기준</span></div><ul class="cl-list">{% if _c.cl_sources %}<li><span class="cl-ic">🗂</span><span>{{ _c.cl_sources }}</span></li>{% endif %}{% if _c.cl_shilla %}<li><span class="cl-ic">🛫</span><span>{{ _c.cl_shilla }}</span></li>{% endif %}{% if _c.cl_retail %}<li><span class="cl-ic">🛒</span><span>{{ _c.cl_retail }}</span></li>{% endif %}</ul><span class="cl-more">업데이트 로그 전체 보기 →</span></a></div>
{% endif %}
"""

# 💱 면세 vs 국내 'gap' 텍스트 캐러셀 — 홈 **상단**(CMPA-693 보드 2026-06-29).
#   '국내최저 − 면세최저'(100ml당) gap 을 핵심 지표로, 인기 밴드(병당 5~30만원)에서
#   🟢면세 이득 TOP·🔴소매 이득·🔀오늘 큰 변동(+원인)·🏆스코어보드를 한 줄씩 회전 노출.
#   데이터(carousel 리스트·carousel_date)는 compare 글(url contains dutyfree-whisky-compare)
#   front matter 에서 읽는다 — 생성기 = pipelines/dutyfree_compare/build_compare.py
#   (build_carousel_items). 새 크롤 0(site.posts 기존 필드만).
#   UI: 기본 = line 1 정적 노출 → 인라인 JS 가 모션 허용 시 4s 자동회전(호버/포커스 일시정지).
#   prefers-reduced-motion 또는 JS 미동작 시 = 전체 정적 목록(글 안 숨김 — CLAUDE.md 모바일 원칙).
#   ⚠️ kramdown 안전(_HOME_RARE/CHANGELOG 패턴 동형): (a) 카드 <a> 는 **블록 <div class="gapc-wrap">
#   래퍼 + 단일 물리 라인**(빈 줄 0)로 '빈 버튼' 방지, (b) 제어 Liquid 는 **트림 금지**({%- -%} 금지)
#   → 앞 빈 줄 보존 → HTML 블록 인식. <script> 는 raw 블록(Liquid/kramdown 미처리). 외부 의존 0.
_HOME_CAROUSEL = """{% assign _gc = site.posts | where_exp: "p","p.url contains 'dutyfree-whisky-compare'" | sort: "date" | reverse %}
{% if _gc.size > 0 and _gc[0].carousel and _gc[0].carousel.size > 0 %}{% assign _g = _gc[0] %}
<div class="gapc-wrap"><div class="gapc-head"><span class="gapc-title">💱 면세점 vs 국내, 어디가 더 쌀까</span><span class="gapc-when">{{ _g.carousel_date }} 기준</span></div><ul class="gapc-track">{% for it in _g.carousel %}<li class="gapc-item"><a class="gapc-lnk" href="{{ it.url | relative_url }}"><span class="gapc-txt">{{ it.text }}</span></a></li>{% endfor %}</ul><a class="gapc-more" href="{{ _g.url | relative_url }}">면세 vs 국내 전체 비교 보기 →</a></div>
<script>(function(){var R=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;if(R){return;}var ts=document.querySelectorAll('.gapc-track');for(var k=0;k<ts.length;k++){(function(tr){var items=tr.querySelectorAll('.gapc-item');if(items.length<2){return;}var cur=0,timer=null,paused=false;tr.classList.add('gapc-on');function measure(li){var t=li.querySelector('.gapc-txt');li.classList.remove('gapc-marq');li.style.removeProperty('--marq-shift');li.style.removeProperty('--marq-dur');if(!t){return false;}var over=t.scrollWidth-li.clientWidth;if(over>4){li.style.setProperty('--marq-shift',(-(over+8))+'px');li.style.setProperty('--marq-dur',Math.max(5,(over+8)/35).toFixed(1)+'s');li.classList.add('gapc-marq');return true;}return false;}function schedule(m){timer=setTimeout(next,m?9000:4000);}function next(){items[cur].classList.remove('gapc-cur');cur=(cur+1)%items.length;var li=items[cur];li.classList.add('gapc-cur');var m=measure(li);if(!paused){schedule(m);}}items[0].classList.add('gapc-cur');schedule(measure(items[0]));function pause(){paused=true;if(timer){clearTimeout(timer);timer=null;}}function play(){if(paused){paused=false;if(!timer){schedule(items[cur].classList.contains('gapc-marq'));}}}var w=tr.closest('.gapc-wrap')||tr;w.addEventListener('mouseenter',pause);w.addEventListener('mouseleave',play);w.addEventListener('focusin',pause);w.addEventListener('focusout',play);})(ts[k]);}})();</script>
{% endif %}
"""


def _pillar_filter(pil):
    """기둥 글만 추리는 Liquid where_exp(허브 카드 카운트/미리보기용).
    streams 의 각 카테고리를 `or` 로 묶은 긍정형 — Liquid 가 안전하게 평가.
    (price 는 base/patch 둘 다 categories=[price] 라 한 항으로 커버.)"""
    return " or ".join(f"p.categories contains '{k}'" for k in pil["streams"])


def _pillar_body(pil):
    """기둥 1개의 머리말(##) + 스트림(###) 목록 블록. 홈이 아니라 기둥
    독립 페이지(/code/·/cask/)가 이 목록을 소유한다(CMPA-192)."""
    parts = [_PILLAR_HEAD
             .replace("__ID__", pil["label"].lower())
             .replace("__EMOJI__", pil["emoji"])
             .replace("__LABEL__", pil["label"])
             .replace("__TAGLINE__", pil["tagline"])
             .replace("__DESC__", pil["desc"])]
    for key in pil["streams"]:
        if key == "price":
            parts.append(_STREAM_PRICE)
        else:
            s = STREAMS[key]
            parts.append(_STREAM_LIST
                         .replace("__EMOJI__", s["emoji"])
                         .replace("__LABEL__", s["label"])
                         .replace("__DESC__", s["desc"])
                         .replace("__KEY__", key))
    return "\n".join(parts)


def _pillar_page(pil):
    """기둥 독립 목록 페이지 — permalink(/code/·/cask/) + layout default.
    Cask 페이지에만 '기타' 카테고리 폴백을 덧붙인다(미분류 카테고리 자동 노출).
    일기/숙성 태그 안내박스는 CMPA-289 보드 지시로 제거됨. (CMPA-192)"""
    fm = front_matter({
        "layout": "default",
        "title": f"{pil['emoji']} {pil['label']} — {pil['tagline']}",
        "description": pil["desc"],
        "permalink": pil["path"],
        "robots": "index,follow",
    })
    parts = [_pillar_body(pil)]
    if pil["label"] == "Cask":
        parts.append(_SECTION_OTHER.replace("__KNOWN__", ",".join(SECTION_KEYS)))
    return fm + "\n" + "\n".join(parts).rstrip() + "\n"


def _pillar_by_label(label):
    """라벨로 기둥 선택 — PILLARS 순서(Cask 먼저/Code 먼저)와 무관하게 동작.
    홈 표시 순서는 바뀔 수 있으나 /code/·/cask/ 페이지 내용은 라벨로 고정한다."""
    return next(p for p in PILLARS if p["label"] == label)


def _code_md():
    return _pillar_page(_pillar_by_label("Code"))


def _cask_md():
    return _pillar_page(_pillar_by_label("Cask"))


def _index_md():
    """홈 = 4단(CMPA-294 grouping): 히어로 → ①시그니처 핀(최신 본편) →
    ②🆕 읽을거리 피드(간헐 글=시음·데이터분석·개발 5편) → ③📊 가격 모아보기
    (신라면세 가격변동·위스키 가격리포트 두 그룹 카드) → ④2기둥 카드(현행 유지).
    핵심: 매일 쏟아지는 고빈도 가격 글을 ③ 그룹 카드로 묶어 ②의 간헐 글이 홈
    상단에서 묻히지 않게 한다(보드 CMPA-294). 빈 섹션은 graceful 미렌더
    ({% if %} 가드). 새 데이터·새 크롤 0 — site.posts 기존 필드만."""
    fm = front_matter({
        "layout": "default",
        "title": brand.NAME_EN + " — 블로그",
        "description": brand.ABOUT,
        "robots": "index,follow",
    })
    cards = []
    for pil in PILLARS:
        cards.append(_HUB_CARD
                     .replace("__PATH__", pil["path"])
                     .replace("__EMOJI__", pil["emoji"])
                     .replace("__LABEL__", pil["label"])
                     .replace("__TAGLINE__", pil["tagline"])
                     # 카드 설명은 raw HTML 블록 안 → kramdown 미처리. 백틱 제거.
                     .replace("__DESC__", pil["desc"].replace("`", ""))
                     .replace("__VAR__", "posts_" + pil["label"].lower())
                     .replace("__FILTER__", _pillar_filter(pil)))
    # 보드 CMPA-667 2026-06-28: 메인을 구매 상황별 2섹션으로. 순서 =
    #   ① 🛫 면세점에서 구매할 때(신라-롯데-신세계 면세 비교 + 🕰️ 오랜만의 큰 인하 + 🔥 이번주 핫딜)
    #   → ② 🛒 마트에서 구매할 때(위스키 가격 대시보드)
    #   → ③ 🆕 읽을거리(위스키 브랜드별 구매 팁 + 시음·데이터·개발 피드) → ④ 허브.
    #   (면세 하이라이트 카드 RARE/HOTDEALS 는 면세점 섹션 안으로 묶어 맨 위 면세 섹션을 채운다.)
    #   CMPA-673 보드: 두 개의 큰 축(면세점/마트)을 색이 다른 패널(<section>)로 또렷이 구분.
    #   kramdown 안전: <section> 은 블록 HTML 요소라 닫힐 때까지(</section>) 안쪽을 raw 로 통과시킨다
    #   → 빈 줄·내부 <a>/<ul> 모두 그대로 보존(오히려 '빈 버튼' 위험이 사라짐). 앞 빈 줄 보존(트림 금지).
    # CMPA-693 보드: 메인 **상단**(히어로 직하·면세 섹션 위)에 면세 vs 국내 gap 텍스트 캐러셀.
    #   위치(상단 vs 다른 곳)는 발행 전 보드 확정 — 기본 제안 = 상단 attention hook(설계 §3).
    #   캐러셀 블록(</script>) 다음 빈 줄 보존(트림 금지) → 뒤따르는 <section> 이 HTML 블록 인식.
    home = (_HOME_CAROUSEL + "\n"
            + '<section class="buy-section df">\n'
            + _HOME_DUTYFREE + "\n" + _HOME_RARE + "\n" + _HOME_HOTDEALS + "\n"
            + "</section>\n\n"
            + '<section class="buy-section mart">\n'
            + _HOME_MART + "\n"
            + "</section>\n\n"
            + _HOME_LATEST + "\n"
            + '<div class="hub">\n' + "".join(cards) + "</div>\n"
            # CMPA-687 보드: 메인 **맨 아래**에 업데이트 로그(릴리스 노트) 링크 섹션.
            #   허브 카드(</div>) 다음 빈 줄 보존(트림 금지) → sec-head 가 HTML 블록으로 인식.
            + "\n" + _HOME_CHANGELOG + "\n")
    return fm + "\n" + home


def _readme():
    return f"""# {brand.NAME_EN} — 블로그 (Jekyll / GitHub Pages)

이 폴더는 **블로그 전용 self-contained Jekyll 사이트**입니다(CMPA-178). 생성기 코드·원천
데이터(`data/`·`pipelines/`·스크랩 CSV)는 **포함하지 않습니다** — 이 폴더만 별도 public
리포로 push 하면 됩니다. 생성기는 메인 리포 `pipelines/shilla_dutyfree/build_blog_md.py`.

## 로컬에서 띄워보기 (3가지 — 위에서부터 추천)

### A. 즉시 미리보기 (설치 0, Python만) — 추천
Ruby 설치 없이 바로 본다. 메인 리포 루트에서:
```bash
python3 pipelines/shilla_dutyfree/preview_blog_md.py
# → http://127.0.0.1:4000 자동 안내. Ctrl+C 로 종료.
```
빌드(`build_blog_md.py`)를 먼저 돌려 최신 md 를 만들고, CaskCode·Satellite-스타일
레이아웃(좌측 프로필 사이드바·터미널 윈도우 카드·별 배경)으로 렌더해 로컬 서버로
띄운다. (Liquid/kramdown 근사 — 콘텐츠 확인용. 최종 픽셀은 B/C 로.)

### B. 진짜 Jekyll, 설치 없이 (Docker)
GitHub Pages 와 동일한 Jekyll 결과. **반드시 `blog-md/` 안에서** 실행:
```bash
cd blog-md   # ← 중요: 이 폴더에서 실행해야 _config.yml 이 잡힌다
docker run --rm -v "$PWD":/srv/jekyll -v ccc_bundle:/usr/local/bundle \
  -p 4000:4000 jekyll/jekyll:4 jekyll serve --host 0.0.0.0 --no-watch
# → http://localhost:4000  (홈에서 글 링크 클릭)
```
- **첫 실행은 1~2분** 걸린다(gem 98개 설치). `Installing ...` 가 멈춘 게 아니라 진행 중.
  `Server address: http://0.0.0.0:4000` 가 뜨면 준비 완료 → 브라우저에서 접속.
- `-v ccc_bundle:...` 로 gem 을 캐시 → **다음 실행부터는 빠름**.
- `--no-watch` 는 Windows/WSL 자동재생성 경고·불안정을 피한다(글 바꾸면 컨테이너 재시작).
- 그래도 안 뜨면 → **방법 A(파이썬 미리보기)** 를 쓰면 설치·대기 없이 즉시 보인다.

### C. 네이티브 Ruby/Jekyll
```bash
# WSL/Ubuntu: sudo apt install -y ruby-full build-essential
gem install jekyll bundler   # 또는 bundle install (Gemfile=github-pages)
bundle exec jekyll serve
```

## 카테고리(섹션)와 글 쓰기
홈은 **브랜드 2기둥(Code / Cask)** 으로 묶여 나옵니다(CMPA-182 리브랜드):
{chr(10).join(f"- **{p['emoji']} {p['label']} — {p['tagline']}**: " + ", ".join(f"{STREAMS[k]['label']}(`{k}`)" for k in p['streams']) for p in PILLARS)}

> 📓 **일기**·🛢️ **숙성**은 별도 칸이 아니라 **태그**입니다 — 위스키 산 이야기·여정·느낀점은
> **`#일기`**, 오크통 숙성·블렌딩 실험은 **`#숙성`** 태그로 Cask 글에 답니다(`tags: [일기]`).

새 글은 front matter 의 `categories: [<key>]` 로 스트림을 정합니다(`dev`/`data`=Code, `price`/`wprice`/`tasting`=Cask).
**새 key 를 쓰면 '기타 카테고리'에 자동으로 나타납니다**(설정 변경 불필요).

### 직접 글 쓰는 법 (개발·데이터·가격정보·시음 등)
1. 기존 글(예: `_posts/*-monthly-base.md`)의 front matter 구조를 참고해 새 파일을 만든다.
2. 내용·front matter(`title`/`date`/`categories`/`tags`) 채우기.
3. **`_posts/YYYY-MM-DD-제목.md`** 로 저장(파일명 날짜 = 발행일).
4. 미리보기: `python3 pipelines/shilla_dutyfree/preview_blog_md.py`
   (`_drafts` 만 보려면 `--drafts`). 또는 `jekyll serve` 재시작.

> ⚠️ `build_blog_md.py` 는 **자동 생성 포스트(`*-monthly-base.md`/`*-price-patch.md`)만**
> 다시 만듭니다. 손으로 쓴 글은 건드리지 않으니 안심하고 `_posts/` 에 두세요.
> **`_drafts/` 에 두면 라이브에 안 나옵니다**(프로덕션 빌드는 `--drafts` 미사용) — 발행하려면 `_posts/`.
> 사진은 **VSCode 에서 그냥 스크린샷을 붙여넣으면 됩니다**(보드 결정 에디터 — CMPA-223).
> `.vscode/settings.json` 의 `markdown.copyFiles.destination` 가 `assets/img/<글파일명>/` 에 저장하고
> `![](../assets/img/<글파일명>/x.png)` 같은 상대경로를 삽입합니다. `assets/img/` 에 직접 넣고
> `![설명](assets/img/파일.jpg)`·`![설명](/assets/img/파일.jpg)` 로 써도 됩니다.
> ✅ 사이트가 `baseurl: /CaskCode` 아래 있지만, 이제 `build_blog_md.py` 가 발행 시 절대·베어·`../` 상대 경로를
> **자동으로 `{{{{ '...' | relative_url }}}}` 로 래핑**(CMPA-224)하므로 직접 감쌀 필요가 없습니다.
> 이미 `relative_url` 로 감쌌거나 외부 URL(`http(s)://`)·스킴-상대(`//cdn`)는 그대로 둡니다.
> (Obsidian 위키링크 `![[파일.png]]` 는 범위 밖 — 에디터에서 '위키링크' 옵션을 끄고 일반 마크다운으로 붙여넣으세요.)

## 발행 게이트
외부 발행은 보드 게이트(c7405e7d) 승인 후에만. 그 전까지 모든 페이지 `robots: noindex`.
콘텐츠는 가공·에디토리얼(랭킹·요약)이며 원천 스크랩 표는 덤프하지 않습니다.
가격은 각 스냅샷 **수집일 기준값**(CMPA-156).
"""


def _draft_tasting():
    return """---
layout: post
title: "글렌피딕 15년 — 셰리 한 스푼의 균형"
date: 2026-06-07 20:00:00 +0900
categories: [tasting]
tags: [글렌피딕, 스페이사이드, 셰리]
rating: 4.0
robots: noindex,nofollow
---

> 개인 시음 기록 — 맛은 주관적입니다.

## 한 줄
달큰한 솔레라 셰리 위에 사과·바닐라. 입문자에게 부담 없는 균형형.

## 노트
- **향(Nose)**: 꿀, 잘 익은 배, 옅은 오크.
- **맛(Palate)**: 부드러운 셰리 단맛 → 시나몬, 가벼운 견과.
- **여운(Finish)**: 중간 길이, 깔끔.

## 메모
- 마신 날 / 장소 / 가격(있으면) ·  함께한 안주.
- (사진은 `assets/img/` 에 넣고 `![설명](assets/img/파일.jpg)` 로 삽입 — 경로는 발행 시 자동 교정됨, CMPA-224)
"""


def _draft_data():
    return """---
layout: post
title: "면세가 vs 국내최저 — 656종 가격 격차 분포"
date: 2026-06-07 21:00:00 +0900
categories: [data]
tags: [데이터분석, 면세, 가격]
robots: noindex,nofollow
---

> 데이터: 신라면세 위스키 656종(수집일 기준값). 가공·요약·랭킹만 — 원천 표는 싣지 않음(CMPA-156).

## 질문
면세가가 국내 최저가보다 싼 위스키는 전체의 몇 %일까? 어디서 격차가 가장 클까?

## 방법
- `detect_price_changes.py`(CMPA-168) 산출물에서 면세 KRW vs 데일리샷 국내최저를 비교.
- 요약 통계·구간 분포·상위 N만 제시(개별 원천 행 비공개).

## 발견 (예시 — 실제 수치로 교체)
- 국내최저 돌파: **N건 (x%)**
- 격차 중앙값: **₩XX,XXX**
- 톱: 더 글렌그란트 21년 (−₩102,839)

## 결론
한 줄 요약 + 다음에 볼 것.
"""


def _draft_wprice():
    return """---
layout: post
title: "위스키 가격정보 — 이번 달 국내 마트 최저가 (예시)"
date: 2026-06-07 19:00:00 +0900
categories: [wprice]
tags: [트레이더스, 코스트코, 데일리샷, 가격]
robots: noindex,nofollow
---

> 데이터 기준일 / 리포트 작성일을 항상 밝힙니다(수집일 기준값). 가공·요약·랭킹만 — 원천 표는 통째로 싣지 않음.

## 들어가며
국내 대형마트(트레이더스·코스트코) 위스키를 모아 **지금 가장 싸게 사는 곳**과 **과거·해외 대비 얼마나 좋은 값인지** 한눈에 정리.

## 이번 달 베스트 (예시 — 실제 수치로 교체)
| 위스키 | 최저가(₩) | 매력도 | 최저 판매처 |
|---|--:|:--:|---|
| (예) 글렌피딕 12년 | 69,800 | 100 | 트레이더스 |

## 한 줄 결론
역대급 딜 N종 · 해외(홍콩/일본) 대비 저렴 M종. (다음 달 업데이트 예정)
"""


def _draft_dev():
    return """---
layout: post
title: "이 블로그를 만든 도구 — md → Jekyll 정적 생성기"
date: 2026-06-07 22:00:00 +0900
categories: [dev]
tags: [사이드프로젝트, python, jekyll]
robots: noindex,nofollow
---

> 직접 개발한 것 이야기 — 코드/사이드프로젝트/도구.

## 무엇을
한 줄 소개: 무엇을 왜 만들었나.

## 어떻게
- 스택: (예) Python + Jekyll(GitHub Pages) 정적 생성.
- 핵심 결정: 결정론적 재생성, self-contained 발행 폴더.

## 배운 것
- 짧게 1~3개.

## 다음
- 다음에 붙일 것 / 열린 질문.
"""


def _gemfile():
    # CMPA-188: GitHub Actions 빌드용 Jekyll 4.x(네이티브 Pages 3.9 화이트리스트 회피).
    # Satellite 테마(jekyll-loading-lazy 의존, CMPA-183)가 4.x 를 요구하므로 4.x 고정.
    return ('source "https://rubygems.org"\n'
            '# CMPA-188: Jekyll 4.x 직접 빌드(Actions). 로컬은 `bundle exec jekyll serve`.\n'
            'gem "jekyll", "~> 4.3"\n'
            '# Ruby 3+ 에는 webrick 미포함 → jekyll serve 로컬 미리보기에 필요.\n'
            'gem "webrick", "~> 1.8"\n'
            'group :jekyll_plugins do\n'
            '  # CMPA-183 테마 통합 시 활성화:\n'
            '  # gem "jekyll-theme-satellite"\n'
            '  # gem "jekyll-loading-lazy"\n'
            'end\n')


def _gitignore():
    return "_site/\n.jekyll-cache/\n.sass-cache/\nGemfile.lock\n"


def _sitemap_xml():
    """CMPA-270: robots=index,follow 인 글·페이지만 색인 등록. Liquid 템플릿이라 Jekyll 빌드 시
    자동으로 site.posts/site.pages 를 순회 — 새 에디토리얼 글을 추가하고 robots: index,follow 를
    설정하면 sitemap 에 자동 포함된다(수동 갱신 불필요)."""
    return """---
layout: none
permalink: /sitemap.xml
sitemap: false
---
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
{%- for post in site.posts -%}
  {%- if post.robots == 'index,follow' -%}
  <url>
    <loc>{{ post.url | absolute_url }}</loc>
    <lastmod>{{ post.date | date_to_xmlschema }}</lastmod>
    <changefreq>monthly</changefreq>
  </url>
  {%- endif -%}
{%- endfor -%}
{%- for page in site.pages -%}
  {%- if page.robots == 'index,follow' -%}
  <url>
    <loc>{{ page.url | absolute_url }}</loc>
    <changefreq>weekly</changefreq>
  </url>
  {%- endif -%}
{%- endfor -%}
</urlset>
"""


def _site_webmanifest():
    """PWA 매니페스트(CMPA-358). 경로는 매니페스트(사이트 루트)에 대해 상대 —
    baseurl(/CaskCode) 하위에서도 브라우저가 알아서 해석한다. theme/bg = 다크 토큰."""
    return """{
  "name": "CaskCode",
  "short_name": "CaskCode",
  "description": "CaskCode(사람)와 Dram(AI)이 함께 쓰는 블로그 — 위스키·여행 등을 다룹니다.",
  "lang": "ko",
  "start_url": ".",
  "scope": ".",
  "display": "standalone",
  "background_color": "#0f1115",
  "theme_color": "#0f1115",
  "icons": [
    { "src": "assets/icons/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any" },
    { "src": "assets/icons/icon-192.png", "sizes": "192x192", "type": "image/png", "purpose": "any" },
    { "src": "assets/icons/icon-512.png", "sizes": "512x512", "type": "image/png", "purpose": "any" },
    { "src": "assets/icons/icon-maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable" }
  ]
}
"""


# ── 빌드 ─────────────────────────────────────────────────────────────
# self-contained 발행 폴더가 소유하는 정적 파일(매 빌드 결정론적 재생성).
def _static_files():
    return {
        "_config.yml": _config_yml(),
        "index.md": _index_md(),
        # 2기둥 독립 목록 페이지(/code/·/cask/) — 홈 허브가 링크(CMPA-192).
        "code.md": _code_md(),
        "cask.md": _cask_md(),
        "_layouts/default.html": _layout_default(),
        "_layouts/post.html": _layout_post(),
        # PWA 매니페스트(CMPA-358) — 아이콘 PNG/SVG 는 blog-md/assets/icons/ 에
        # 커밋된 정적 자산(icon.svg 마스터→render_icons.mjs 로 PNG 생성). 생성기는
        # 바이너리를 비우지 않으므로 재생성 때 보존된다(apps/frugal/icons 와 동일 패턴).
        "site.webmanifest": _site_webmanifest(),
        "robots.txt": _robots_txt(),
        "sitemap.xml": _sitemap_xml(),
        "assets/css/style.css": _css(),
        "README.md": _readme(),
        "Gemfile": _gemfile(),
        ".gitignore": _gitignore(),
        # 보드 CMPA-197: 예시(_drafts/*-예시.md) 템플릿은 생성하지 않는다(실제 글만 노출).
        # 새 글은 기존 글 구조를 참고해 _posts/ 에 직접 작성.
    }


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(content)


def build(out_dir=DEFAULT_OUT, report_dir=REPORT_DIR, latest_only=False):
    """self-contained Jekyll 블로그를 out_dir 에 결정론적으로 (재)생성.

    누적은 reports/ 의 md 가 담당하므로 매번 전부 재생성해도 byte-identical.
    `.git`(별도 리포)·_site·**손글 포스트**는 건드리지 않는다 — 생성기 소유 포스트
    (`*-monthly-base.md`/`*-price-patch.md`)만 비우고 정적 스캐폴드는 덮어쓴다.

    latest_only=True(루틴 자동실행, CMPA-264): 과거 패치/베이스 글은 '누적 기록'
    이므로 보존(CMPA-156)하고, **오늘자/최신 패치 1건만** 렌더한다. 전체 rm·전체
    재생성을 하지 않아 매 루틴 실행마다 과거 글 수십 개를 반복 재작성·재발행하던
    낭비를 없앤다. 기본값(latest_only=False)은 현행 full rebuild 그대로(수동 전체
    재생성 경로 보존, 회귀 0)."""
    written = []
    os.makedirs(out_dir, exist_ok=True)

    # 생성기 소유 포스트만 정리(손글 카테고리 글·.git 보존). 패턴 매칭으로 한정.
    # latest_only 모드는 과거 글을 보존해야 하므로 전체 rm 하지 않는다 — 아래에서
    # 오늘자(최신) 패치 1건만 동일 파일로 덮어쓴다(전체 rm 금지, CMPA-264).
    posts_dir = os.path.join(out_dir, "_posts")
    if os.path.isdir(posts_dir) and not latest_only:
        for f in (glob.glob(os.path.join(posts_dir, "*-monthly-base.md"))
                  + glob.glob(os.path.join(posts_dir, "*-price-patch.md"))):
            os.remove(f)
    os.makedirs(posts_dir, exist_ok=True)

    # 정적 스캐폴드(_config/index/layout/css/보조파일)
    for rel, content in _static_files().items():
        _write(os.path.join(out_dir, rel), content)
        written.append(rel)

    # 패치 → _posts/<주시작(월요일)>-price-patch.md (CMPA-644 주간 로그)
    #   매일 새 글 대신 **한 주(ISO 월~일)를 한 글에 시간역순으로 누적**한다. 일일 패치
    #   리포트(reports/.../가격변동_*.md)는 그대로 소스로 두고, 같은 주에 속한 날들을 한
    #   글로 묶어 render_weekly_log 로 렌더한다.
    # latest_only: 가장 최신 패치가 속한 **그 주 글만** (그 주 전체 일자로) 재렌더하고,
    #   나머지 과거 주 글은 디스크에 그대로 보존(미접촉 → 내용·바이트·mtime 불변).
    patches = []
    parsed_patches = []
    for md in bb._all_patch_mds(report_dir):
        parsed = parse_patch_md(md)
        if bb.is_noop_patch(parsed):   # 멱등(CMPA-250): 변동 0건 → 글 생성 안 함.
            print(f"  no-op(변동 0건) → 패치 글 생략: {os.path.basename(md)}")
            continue
        parsed_patches.append(parsed)

    # 같은 날짜(latest_date)에 리포트가 2개 이상이면(예: 06-10→06-12 백필 + 06-11→06-12
    # 연속) 하루 섹션이 중복된다. **연속 일일 델타**(prev_date 가 가장 최신=갭 최소)를
    # 1건만 남긴다(CMPA-644).
    by_date = {}
    for parsed in parsed_patches:
        d = parsed["latest_date"]
        if d not in by_date or parsed["prev_date"] > by_date[d]["prev_date"]:
            by_date[d] = parsed
    parsed_patches = list(by_date.values())

    # ISO 주(월요일 시작)로 그룹핑.
    weeks = {}   # week_start -> {"end": .., "days": [parsed,...]}
    for parsed in parsed_patches:
        ws, we = _iso_week_bounds(parsed["latest_date"])
        weeks.setdefault(ws, {"end": we, "days": []})["days"].append(parsed)

    week_starts = sorted(weeks)
    if latest_only and parsed_patches:
        newest_date = max(p["latest_date"] for p in parsed_patches)
        cur_ws, _ = _iso_week_bounds(newest_date)
        for ws in week_starts:
            if ws != cur_ws:
                print(f"  latest-only: 과거 주 로그 보존(미재생성): "
                      f"_posts/{ws}-price-patch.md")
        week_starts = [cur_ws]

    for ws in week_starts:
        we = weeks[ws]["end"]
        days = [classify_patch(p) for p in weeks[ws]["days"]]
        days.sort(key=lambda p: p["latest_date"], reverse=True)   # 최신이 맨 위(시간역순)
        rel = os.path.join("_posts", f"{ws}-price-patch.md")
        _write(os.path.join(out_dir, rel), render_weekly_log(ws, we, days))
        written.append(rel)
        newest = days[0]
        patches.append({
            "latest_date": newest["latest_date"], "prev_date": days[-1]["prev_date"],
            "cadence": "weekly", "breaks": len(newest["breakthroughs"]),
            "week_start": ws, "week_end": we, "days": len(days), "rel": rel,
        })
    patches.sort(key=lambda x: x["latest_date"], reverse=True)

    # 베이스 → _posts/<날짜>-monthly-base.md (에디토리얼 초안 소스)
    # latest_only: 이번 달 base 가 이미 있으면 건드리지 않는다(불필요 재작성 금지).
    # 없을 때만 생성.
    base_meta = None
    picked = _pick_base_src(report_dir)
    if picked:
        base_date, src = picked
        rel = os.path.join("_posts", f"{base_date}-monthly-base.md")
        existing_month = glob.glob(
            os.path.join(posts_dir, f"{base_date[:7]}-*-monthly-base.md"))
        if latest_only and existing_month:
            print(f"  latest-only: 이번 달({base_date[:7]}) base 보존(미재생성): "
                  f"{os.path.basename(existing_month[0])}")
            base_meta = {"date": base_date, "src": os.path.basename(src),
                         "skipped": True}
        else:
            _write(os.path.join(out_dir, rel), render_base_md(src, base_date))
            written.append(rel)
            base_meta = {"date": base_date, "src": os.path.basename(src)}

    return {"out": out_dir, "base": base_meta, "patches": patches,
            "written": sorted(written), "latest_only": latest_only}


# ── 자가검증 / dry-run ───────────────────────────────────────────────
_FIXTURE_BASE = """# 이달의 면세 위스키 — 진짜 싼 것 vs 함정

> 데이터: 신라면세점 위스키 656종, 2026-06-06 수집 · 환율 1 USD = 1,500원

## 들어가며

면세 = 무조건 싸다는 착각. 환율 적용하면 국내가 더 싼 경우가 많습니다.

### ✅ 면세 이득
| 위스키 | 면세가 | 국내최저 |
|---|--:|--:|
| 아벨라워 아부나흐 | 12.1만 | 23.6만 |
"""

_FIXTURE_PATCH = bb._FIXTURE_MD  # build_blog 픽스처 재사용(돌파 1건 포함)


def _split_front_matter(text):
    """('---\\n...\\n---\\n본문') → (front_matter_dict, body). 유효성 위해 yaml 파싱."""
    import yaml
    if not text.startswith("---"):
        return None, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None, text
    fm = yaml.safe_load(parts[1])
    return fm, parts[2]


# ── 발행 전 게이트(CMPA-221) ─────────────────────────────────────────
# 손글 글이 라이브에서 깨지는 흔한 두 실수를 발행 전에 자동으로 잡는다:
#   (1) 사이트-절대경로 링크/이미지(`](/assets/...)` 등) — 사이트가 baseurl:/CaskCode
#       아래 서빙돼 절대경로는 호스트 루트로 해석→404(스샷 깨짐). Liquid relative_url 필수.
#   (2) _drafts/ 에 남은 글 — 프로덕션 빌드(--drafts 미사용)는 배포 안 함→라이브 404.
# Liquid 로 감싼 경로(`]({{ '/x' | relative_url }})`)는 '/'로 시작하지 않아 매칭되지 않는다.
_ABS_MD_LINK_RE = re.compile(r'!?\[[^\]]*\]\(\s*(/[^)\s]*)')      # 마크다운 [..](/..)·![..](/..)
_ABS_HTML_ATTR_RE = re.compile(r'(?:src|href)\s*=\s*["\'](/[^"\']*)["\']')  # 생 HTML src/href="/.."


def _abs_path_violations(body):
    """본문에서 baseurl 을 깨는 사이트-절대경로(/..) 참조 목록을 반환.
    스킴-상대(//cdn)는 제외. Liquid relative_url 로 감싼 경로는 애초에 매칭 안 됨."""
    hits = [m.group(1) for m in _ABS_MD_LINK_RE.finditer(body)]
    hits += [m.group(1) for m in _ABS_HTML_ATTR_RE.finditer(body)]
    return [h for h in hits if not h.startswith("//")]


# ── 자동 교정(CMPA-224) ──────────────────────────────────────────────
# 보드가 위지윅 에디터(보드 결정: VSCode — CMPA-223)로 스크린샷을 붙여넣으면 경로가 생긴다:
#   `](/assets/..)`(사이트-절대) · `](assets/..)`(베어 상대) ·
#   `](../assets/img/<글파일명>/x.png)`(VSCode markdown.copyFiles 가 문서 기준 상대경로로 삽입;
#    permalink `/:year/:month/:day/:title/` 라 ../ 접두가 붙고 ../ 가 여러 번일 수도 있음).
# baseurl(/CaskCode) 때문에 어느 형태든 라이브 404 가 나므로 발행 게이트를 '실패'가 아니라
# '자동 래핑'으로 처리한다 — 보드가 손으로 relative_url 을 감쌀 필요가 없다('편하게 쓰기').
# 정규화 목표: 어떤 접두든 `assets/...` 부터 site-absolute 로 잡아 relative_url 래핑.
# 무변(오탐 0): 이미 Liquid 로 감싼 경로, 외부 URL(http/https), 스킴-상대(//cdn),
# assets/ 로 귀결되지 않는 일반 베어 링크(`](other.md)`·`](#top)`·`](../foo.md)`).
# 자동 생성 포스트는 템플릿이 이미 relative_url 을 쓰므로 무대상(no-op) → 손글만 실질 교정.
_DOTSLASH_RE = re.compile(r'^(?:\.\.?/)+')                          # 선행 ./ · ../ (1회 이상)
_MD_LINK_RE = re.compile(r'(!?\[[^\]]*\]\(\s*)([^)\s]+)')          # ![label](URL  또는  [label](URL
_HTML_ATTR_RE = re.compile(
    r'((?:src|href)\s*=\s*["\'])(/[^"\']*|(?:\.\.?/)*assets/[^"\']*)(["\'])')


def _wrap_target(path):
    """경로 1개를 `{{ '/..' | relative_url }}` 로 래핑한 문자열 반환. 무대상이면 None.
    외부/스킴-상대·이미 Liquid·assets/ 로 귀결 안 되는 베어 경로는 None(손대지 않음)."""
    if path.startswith(("http://", "https://", "//")):
        return None                                   # 외부/스킴-상대 — 손대지 않음
    if path.startswith("{{") or path.startswith("{%"):
        return None                                   # 이미 Liquid 로 감쌈
    if path.startswith("/"):
        norm = path                                   # 사이트-절대경로 → 그대로
    else:
        stripped = _DOTSLASH_RE.sub("", path)         # 선행 ./ · ../ (VSCode 산출) 제거
        if stripped.startswith("assets/"):
            norm = "/" + stripped                     # assets/ 로 귀결 → 절대화(leading slash)
        else:
            return None                               # 그 외 베어 상대경로는 범위 밖
    return "{{ '%s' | relative_url }}" % norm


def wrap_baseurl_paths(body):
    """본문의 baseurl-깨짐 이미지/링크 경로를 relative_url 로 래핑.
    (new_body, fixes[(orig, wrapped)]) 반환. 멱등(이미 감싼 경로 재실행 무변)."""
    fixes = []

    def _md(m):
        wrapped = _wrap_target(m.group(2))
        if wrapped is None:
            return m.group(0)
        fixes.append((m.group(2), wrapped))
        return m.group(1) + wrapped

    def _html(m):
        wrapped = _wrap_target(m.group(2))
        if wrapped is None:
            return m.group(0)
        fixes.append((m.group(2), wrapped))
        return m.group(1) + wrapped + m.group(3)

    body = _MD_LINK_RE.sub(_md, body)
    body = _HTML_ATTR_RE.sub(_html, body)
    return body, fixes


def autofix_published(out_dir=DEFAULT_OUT):
    """_posts/ 손글 글의 baseurl-깨짐 경로를 relative_url 로 제자리 교정.
    front matter 는 YAML 파손을 피해 본문만 변형. 교정한 (rel, [(orig,wrapped)..]) 목록 반환."""
    fixed = []
    for p in sorted(glob.glob(os.path.join(out_dir, "_posts", "*.md"))):
        text = open(p, encoding="utf-8").read()
        fm, body = _split_front_matter(text)
        new_body, changes = wrap_baseurl_paths(body)
        if not changes:
            continue
        # 본문만 재조립(front matter 원문 보존). fm 없으면 전체가 본문.
        if fm is None:
            new_text = new_body
        else:
            head = text.split("---", 2)[1]            # 원본 front matter 블록 그대로
            new_text = "---" + head + "---" + new_body
        with open(p, "w", encoding="utf-8") as f:
            f.write(new_text)
        fixed.append((os.path.relpath(p, out_dir), changes))
    return fixed


def lint_published(out_dir=DEFAULT_OUT):
    """발행 전 게이트. (errors, warnings) 반환 — errors 있으면 빌드 실패시켜야 한다.
      ERROR: _posts 글의 사이트-절대경로 링크/이미지(baseurl 404 — CMPA-221 스샷 깨짐).
      WARN : _drafts 에 남은 글(라이브 미노출 — 발행하려면 _posts/ 로 이동)."""
    errors, warnings = [], []
    for p in sorted(glob.glob(os.path.join(out_dir, "_posts", "*.md"))):
        body = open(p, encoding="utf-8").read()
        rel = os.path.relpath(p, out_dir)
        for tgt in _abs_path_violations(body):
            errors.append(f"{rel}: 절대경로 '{tgt}' → baseurl(/CaskCode) 누락 404. "
                          f"`{{{{ '{tgt}' | relative_url }}}}` 로 감싸세요.")
    for p in sorted(glob.glob(os.path.join(out_dir, "_drafts", "*.md"))):
        rel = os.path.relpath(p, out_dir)
        warnings.append(f"{rel}: _drafts 에 있음 → 라이브 미노출. 발행하려면 _posts/ 로 이동.")
    return errors, warnings


def selftest():
    import tempfile
    fails = []

    def check(cond, msg):
        print(("  ✓ " if cond else "  ✗ ") + msg)
        if not cond:
            fails.append(msg)

    with tempfile.TemporaryDirectory() as rd, tempfile.TemporaryDirectory() as out:
        # 픽스처 report_dir: 베이스 초안 + 패치 md
        _write(os.path.join(rd, "draft_면세위스키_test_2026-06-06.md"), _FIXTURE_BASE)
        _write(os.path.join(rd, "가격변동_2026-06-06_to_2026-06-07.md"), _FIXTURE_PATCH)

        res = build(out_dir=out, report_dir=rd)

        # 1) 구조: 포스트 2개(베이스 + 주간 로그) + 정적 파일
        #    CMPA-644: 패치는 주간 로그로 통합 — 06-07(일)은 ISO 주 06-01(월)~06-07(일)
        #    이므로 파일은 _posts/2026-06-01-price-patch.md.
        base_p = os.path.join(out, "_posts", "2026-06-06-monthly-base.md")
        patch_p = os.path.join(out, "_posts", "2026-06-01-price-patch.md")
        check(os.path.isfile(base_p), "베이스 포스트 _posts/<날짜>-monthly-base.md 생성")
        check(os.path.isfile(patch_p),
              "주간 로그 포스트 _posts/<주시작(월)>-price-patch.md 생성")
        check(os.path.isfile(os.path.join(out, "_config.yml")), "_config.yml 생성")
        check(os.path.isfile(os.path.join(out, "index.md")), "index.md(홈) 생성")
        check(os.path.isfile(os.path.join(out, "_layouts", "default.html")),
              "_layouts/default.html 생성")
        # CMPA-188: posts 가 layout:post 를 쓰므로 post.html 필수(없으면 Jekyll4 가
        # 크롬·noindex 없이 맨 조각 렌더). robots.txt = noindex 보조 게이트.
        check(os.path.isfile(os.path.join(out, "_layouts", "post.html")),
              "_layouts/post.html 생성(layout:post 렌더 보장)")
        check(os.path.isfile(os.path.join(out, "robots.txt")),
              "robots.txt(noindex 보조 게이트) 생성")
        check(os.path.isfile(os.path.join(out, "assets", "css", "style.css")),
              "assets/css/style.css 생성")

        # 2) front matter 유효성(yaml 파싱) + 필수 키
        ptext = open(patch_p, encoding="utf-8").read()
        pfm, pbody = _split_front_matter(ptext)
        check(pfm is not None, "패치 front matter YAML 파싱 성공")
        check(pfm and pfm.get("layout") == "post"
              and pfm.get("title", "").startswith("[신라면세] 가격변동 주간 로그")
              and "price" in (pfm.get("categories") or [])
              and pfm.get("kind") == "patch",
              "주간 로그 front matter 필수 키(layout/title/categories=price/kind=patch)")
        check(pfm and pfm.get("breakthroughs") == 1
              and pfm.get("cadence") == "weekly"
              and pfm.get("weekly_start") == "2026-06-01"
              and pfm.get("weekly_end") == "2026-06-07"
              and pfm.get("latest_date") == "2026-06-07",
              "주간 로그 front matter: 최신일 돌파 1건 · 주간 케이던스 · 주 경계")
        # 시간역순 로그: 하루 섹션 헤더(## 📅) + 일일 본문은 한 단계 낮춘 ###.
        check("## 📅 6월 7일 (일)" in pbody, "주간 로그: 하루 섹션 헤더(## 📅 …)")
        check("\n### 🏆" in pbody and "\n## 🏆" not in pbody,
              "주간 로그: 일일 본문 헤딩 한 단계 강등(## → ###)")
        # CMPA-644: 🔥 이번주 핫딜 — 주간 집계 섹션 + 홈 카드용 front matter.
        check("## 🔥 이번주 핫딜 (1종)" in pbody,
              "주간 로그: 🔥 이번주 핫딜 집계 섹션(돌파 1건)")
        check(pfm.get("hotdeals_count") == 1
              and isinstance(pfm.get("hotdeals"), list)
              and len(pfm["hotdeals"]) == 1
              and "더 글렌그란트" in pfm["hotdeals"][0]
              and "면세 ₩" in pfm["hotdeals"][0],
              "주간 로그 front matter: hotdeals(상위 N줄)·hotdeals_count(홈 카드용)")
        # 핫딜 섹션이 날짜별 로그(## 📅)보다 위에 온다(메인 핫딜 먼저).
        check(pbody.find("## 🔥 이번주 핫딜") < pbody.find("## 📅 6월 7일"),
              "주간 로그: 🔥 이번주 핫딜이 날짜별 로그보다 먼저")

        # CMPA-644 후속: '오랜만의 큰 인하' 감지 — 합성 히스토리(결정론, 실데이터 무의존).
        # baseline 8일 flat(5% 할인) → 마지막날 −40% 큰 인하 = 정확히 1건 잡혀야.
        synth = {"C1": {}}
        for i, d in enumerate(["2026-07-13", "2026-07-14", "2026-07-15", "2026-07-16",
                               "2026-07-17", "2026-07-18", "2026-07-19"]):
            synth["C1"][d] = (100.0, 5.0, "테스트 위스키 700ml")  # 7일 flat(=월~일 직전)
        synth["C1"]["2026-07-20"] = (60.0, 40.0, "테스트 위스키 700ml")  # 다음주 월: −40%
        rdrops = detect_rare_drops.rare_drops("2026-07-20", "2026-07-26", history=synth,
                                              min_flat_days=6)
        check(len(rdrops) == 1 and rdrops[0]["name"] == "테스트 위스키 700ml"
              and abs(rdrops[0]["drop"] - 0.40) < 1e-6 and rdrops[0]["base_disc"] == 5.0,
              "오랜만의 큰 인하: flat 후 −40% 단일 인하 정확 감지")
        # 상시 할인(쭉 60$)은 미감지(=잔잔/상시할인 제외).
        always = {"C2": {d: (60.0, 40.0, "상시할인 700ml")
                         for d in [f"2026-07-{x:02d}" for x in range(13, 27)]}}
        check(detect_rare_drops.rare_drops("2026-07-20", "2026-07-26", history=always,
                                           min_flat_days=6) == [],
              "오랜만의 큰 인하: 상시 할인(변동 없음)은 미감지")
        # 렌더 행: 면세가·낙폭·'거의 정상가'·첫 인하 날짜 포함.
        row = _rare_drop_row(rdrops[0], {"krw": 92000, "floor": 120000, "floor_url": "u"}, 1500.0)
        check("**−40% 인하**" in row and "거의 정상가" in row and "7/20 첫 인하" in row
              and "면세 **₩92,000**" in row and "국내최저" in row,
              "오랜만의 큰 인하: 표 행 렌더(면세/국내최저/낙폭/첫 인하일)")

        btext = open(base_p, encoding="utf-8").read()
        bfm, bbody = _split_front_matter(btext)
        check(bfm is not None and bfm.get("layout") == "post"
              and "price" in (bfm.get("categories") or [])
              and bfm.get("kind") == "base",
              "베이스 front matter 유효 + categories=price/kind=base")

        # 3) 핵심 기능 유지: 돌파 톱 강조(표) + 면책 (CMPA-250: 카드→표)
        check("🏆" in pbody and "더 글렌그란트" in pbody,
              "패치 본문: 국내최저 돌파 🏆 + 위스키명 렌더")
        # CMPA-256: 모바일 우선 → (위스키, 상세) 2컬럼 헤더.
        check("| 🏆 위스키 | 상세 |" in pbody,
              "패치 본문: 국내최저 돌파 (위스키, 상세) 2컬럼 헤더 렌더")
        # 상세 칸에 면세가·국내최저·절약·할인율이 <br> 줄바꿈으로 묶였는지.
        check("면세 **" in pbody and "<br>절약 **" in pbody and "할인 " in pbody,
              "패치 본문: 돌파 상세 칸(면세/국내최저<br>절약/할인) 합본 렌더")
        check("−₩102,839" in pbody,
              "돌파 절감액 계산(₩359,000−₩256,161)")
        # 돌파 섹션(### 🏆 … 다음 헤딩 전까지)에 인디·싱글캐스크(floor 빈칸) 미포함 가드.
        # CMPA-644: 주간 로그에서 일일 본문은 ###로 강등 → 헤더/구분자 기준 갱신.
        _bk_start = pbody.find("### 🏆")
        _bk_rest = pbody[_bk_start:] if _bk_start >= 0 else pbody
        _bk_sec = _bk_rest.split("\n### ", 1)[0].split("\n## ", 1)[0]
        check("시그나토리" not in _bk_sec,
              "인디·싱글캐스크(floor 빈칸)는 돌파 표 미포함(가드 유지)")
        # 보드 CMPA-273: 패치에서 '수집일 기준값' 면책 blockquote 제거 요청.
        #   CMPA-156 실질(수집일 노출)은 직전→최신 라인 + 술 카드 '수집일' 메타로 유지.
        check(("직전 " in pbody and "최신 " in pbody),
              "CMPA-156 수집일 노출 보존(패치: 직전→최신 스냅샷일)")
        check("수집일 기준값" in btext, "CMPA-156 면책 보장(베이스)")

        # 4) 거버넌스 §2: 원천 변동표 통째 덤프 금지
        check("| 위스키명 | 현재 USD" not in pbody,
              "거버넌스: 원천 변동표 헤더 미덤프(가공·랭킹만)")

        # 5) 거버넌스 §1: 발행 폴더 self-contained(코드/데이터/CSV 미포함)
        bad = []
        for f in glob.glob(os.path.join(out, "**", "*"), recursive=True):
            if os.path.isfile(f) and f.lower().endswith((".py", ".csv")):
                bad.append(os.path.relpath(f, out))
        check(not bad, f"발행 폴더에 .py/.csv 미포함(self-contained){' — '+str(bad) if bad else ''}")

        # 6) 레이아웃: noindex 게이트 + CaskCode 브랜딩 (CMPA-182: 3C/SEAT/코캐 제거)
        layout = open(os.path.join(out, "_layouts", "default.html"),
                      encoding="utf-8").read()
        check("noindex" in layout, "레이아웃 noindex 게이트(외부 비발행)")
        check(brand.NAME_EN == "CaskCode" and brand.NAME_EN in layout,
              "레이아웃 CaskCode 브랜딩(이름)")
        # CMPA-194/195: 폐기된 'Cabin' 핸들 @codecaskcabin 완전 제거 — 레이아웃에 흔적 0.
        check(brand.HANDLE == "" and "codecaskcabin" not in layout,
              "구 SNS 핸들 @codecaskcabin 흔적 0(보드 CMPA-194)")
        check("CASK" in layout and "CODE" in layout and "CABIN" not in layout,
              "워드마크 CASK·CODE (CABIN 제거)")
        check(not brand.MONOGRAM and "SEAT" not in layout
              and 'class="seat"' not in layout,
              "모노그램/좌석 칩 완전 제거(보드 cf640730: monogram=remove)")
        check("코캐" not in layout and "3C" not in layout,
              "구 닉네임 '코캐'·모노그램 '3C' 흔적 0")
        check(brand.TAGLINE not in layout,
              "태그라인 문구 제거(보드 요청 2026-06-07)")
        check(brand.STAGING_NOTICE not in layout, "레이아웃 푸터에 스테이징 문구 없음")
        # CMPA-183: Satellite-스타일 스킨 시그니처(좌측 프로필 사이드바 + 터미널
        # 윈도우 콘텐츠 카드[신호등 닷] + 별 배경) — self-contained·JS 0(CSS만).
        check('class="sidebar"' in layout and 'class="avatar"' in layout
              and 'class="snav"' in layout,
              "Satellite 스킨: 좌측 프로필 사이드바(아바타·nav)")
        check('class="window"' in layout and 'class="titlebar"' in layout
              and layout.count('class="tdot') >= 3,
              "Satellite 스킨: 터미널 윈도우 카드 + 신호등 닷 3개")
        check('class="stars"' in layout, "Satellite 스킨: 별 배경 레이어")
        # CMPA-192: nav 의 Code/Cask 가 앵커 점프(#code/#cask)가 아니라 기둥
        # 페이지(/code/·/cask/)로 연결돼야 한다.
        check("'/code/'" in layout and "'/cask/'" in layout
              and "#code" not in layout and "#cask" not in layout,
              "nav: Code/Cask → 기둥 페이지 링크(앵커 점프 제거)")
        # CMPA-284: 사이드바 nav 에서 '앱'(/apps/) 항목 제거.
        # CMPA-358: 순서=홈/Cask/Code/Dram Jar/About (보드 요청 — 앱 메뉴 추가).
        # CMPA-365: 앱 정식 이름=Dram Jar(보드 확정) → nav 라벨 '🐷 Dram Jar', 경로 /dj/.
        _snav = layout[layout.index('class="snav"'):layout.index("</ul>",
                       layout.index('class="snav"'))]
        check("/apps/" not in layout and "🧰" not in layout,
              "nav: '앱' 항목(/apps/ 링크) 제거(CMPA-284)")
        check(_snav.index("/cask/") < _snav.index("/code/")
              < _snav.index("/dj/") < _snav.index("/about/"),
              "nav: 순서 Cask → Code → Dram Jar → About (CMPA-358)")
        check("🐷 Dram Jar" in layout and "🐷 Frugal App" not in layout,
              "nav: 앱 라벨 'Dram Jar'(CMPA-365)")
        css = open(os.path.join(out, "assets", "css", "style.css"),
                   encoding="utf-8").read()
        check(".stars::before" in css and "radial-gradient" in css
              and "@media" in css and "Math.random" not in css,
              "스킨 CSS: 별 배경(CSS만·결정론) + 반응형, JS 0")
        js_files = [f for f in glob.glob(os.path.join(out, "**", "*"), recursive=True)
                    if os.path.isfile(f) and f.endswith(".js")]
        check(not js_files,
              "self-contained·JS 0(스킨에 .js 파일 미생성 — Pages 네이티브 호환)")

        # 7) _config.yml / index.md 유효성
        import yaml
        cfg = yaml.safe_load(open(os.path.join(out, "_config.yml"),
                                  encoding="utf-8").read())
        check(isinstance(cfg, dict) and cfg.get("markdown") == "kramdown"
              and "title" in cfg, "_config.yml 유효 YAML + 필수 키")
        # CMPA-192: 홈은 깔끔한 허브(히어로 + Code/Cask 두 카드). 긴 목록 로직은
        # 기둥 독립 페이지(/code/·/cask/)로 이동.
        idx = open(os.path.join(out, "index.md"), encoding="utf-8").read()
        check(len(PILLARS) == 2
              # 표시 순서는 무관(Cask 먼저든 Code 먼저든) — 두 기둥 존재만 확인.
              and {p["label"] for p in PILLARS} == {"Code", "Cask"}
              and 'class="hub"' in idx and 'class="pillar-card"' in idx
              and "/code/" in idx and "/cask/" in idx
              and all(p["emoji"] in idx and p["label"] in idx for p in PILLARS)
              # 긴 스트림 목록은 기둥 페이지로 이동(허브엔 카운트/미리보기만).
              and "신라면세 위스키 정보" not in idx,
              "홈 index.md: 2기둥 허브(카드+페이지 링크, 긴 목록 제거)")
        # 기둥 독립 페이지: permalink + 자기 글 목록만.
        code_md = open(os.path.join(out, "code.md"), encoding="utf-8").read()
        cask_md = open(os.path.join(out, "cask.md"), encoding="utf-8").read()
        # CMPA-204: data(데이터 분석)=Code 로 이동, wprice(위스키 가격정보)=Cask 신규.
        check('permalink: "/code/"' in code_md
              and "site.posts" in code_md
              and STREAMS["dev"]["label"] in code_md
              and STREAMS["data"]["label"] in code_md      # data → Code 이동
              and "신라면세 위스키 정보" not in code_md       # 위스키 가격 목록 미포함
              and STREAMS["wprice"]["label"] not in code_md
              and STREAMS["tasting"]["label"] not in code_md,
              "/code/ 페이지: permalink + 개발·데이터분석(Cask 글 미포함)")
        check('permalink: "/cask/"' in cask_md
              and "site.posts" in cask_md
              and "신라면세 위스키 정보" in cask_md
              and STREAMS["wprice"]["label"] in cask_md     # wprice → Cask 신규
              and STREAMS["tasting"]["label"] in cask_md
              and "따로 칸을 두지 않습니다" not in cask_md   # CMPA-289 안내박스 제거
              and "기타 카테고리" in cask_md
              and "####" not in cask_md
              and STREAMS["dev"]["label"] not in cask_md     # Code 글 미포함
              and STREAMS["data"]["label"] not in cask_md,   # data → Code 로 이동
              "/cask/ 페이지: permalink + 면세/패치/가격정보/시음 + 기타")
        # Liquid 태그 밸런스(미닫힌 if/for/unless/capture → Pages 빌드 실패) — 전 페이지.
        for name, txt in (("index.md", idx), ("code.md", code_md),
                          ("cask.md", cask_md), ("default.html", layout)):
            # {%- if … -%} 화이트스페이스 트림(CMPA-644 홈 카드)도 세도록 정규식 카운트.
            opens = len(re.findall(r"\{%-?\s*(?:if|for|unless|capture)\b", txt))
            closes = len(re.findall(r"\{%-?\s*(?:endif|endfor|endunless|endcapture)\b", txt))
            check(opens == closes,
                  f"Liquid 밸런스: {name} 블록 태그 짝 맞음({opens}={closes})")

        # 8) 카테고리 확장: 손글 포스트 보존 + 섹션 자동 분류
        hand = os.path.join(out, "_posts", "2026-06-07-내손글시음.md")
        _write(hand, "---\nlayout: post\ntitle: 손글 시음\n"
                     "date: 2026-06-07 18:00:00 +0900\ncategories: [tasting]\n"
                     "robots: noindex,nofollow\n---\n맛있었다.\n")
        res2 = build(out_dir=out, report_dir=rd)   # 재빌드
        check(os.path.isfile(hand), "재빌드해도 손글 포스트 보존(생성기 비파괴)")
        check(all(not w.endswith("내손글시음.md") for w in res2["written"]),
              "손글 포스트는 생성기 written 목록에 미포함")
        check(not glob.glob(os.path.join(out, "_drafts", "*-예시.md")),
              "_drafts 예시 템플릿 미생성(보드 CMPA-197: 예시 글 제거)")
        os.remove(hand)  # 결정론 비교 전 정리

        # 9) 결정론: 재빌드 byte-identical 트리(생성기 소유분)
        with tempfile.TemporaryDirectory() as out2:
            build(out_dir=out2, report_dir=rd)
            snap = lambda d: {os.path.relpath(p, d): open(p, encoding="utf-8").read()
                              for p in glob.glob(os.path.join(d, "**", "*"),
                                                 recursive=True) if os.path.isfile(p)}
            check(snap(out) == snap(out2), "결정론: 동일 소스 → 동일 트리(재빌드)")

        # 9.5) 발행 전 게이트(CMPA-221): 절대경로 링크/이미지·스트랜디드 드래프트 차단.
        #   정상 트리는 에러 0. 손글 fixture 로 위반/안전 케이스를 양방향 검증.
        errs0, _ = lint_published(out)
        check(errs0 == [], "발행게이트: 정상 빌드 트리 위반 0")
        # (a) 절대경로 이미지 → ERROR
        bad = os.path.join(out, "_posts", "2026-06-07-bad-img.md")
        _write(bad, "---\nlayout: post\ntitle: bad\ndate: 2026-06-07 10:00:00 +0900\n"
                    "categories: [dev]\nrobots: noindex,nofollow\n---\n"
                    "![스샷](/assets/img/x.png)\n")
        errs_bad, _ = lint_published(out)
        check(any("x.png" in e for e in errs_bad),
              "발행게이트: 절대경로 이미지(`](/assets/..)`) 탐지(baseurl 404 차단)")
        os.remove(bad)
        # (b) Liquid relative_url 로 감싼 이미지 → 안전(위반 0)
        good = os.path.join(out, "_posts", "2026-06-07-good-img.md")
        _write(good, "---\nlayout: post\ntitle: good\ndate: 2026-06-07 10:00:00 +0900\n"
                     "categories: [dev]\nrobots: noindex,nofollow\n---\n"
                     "![스샷]({{ '/assets/img/x.png' | relative_url }})\n")
        errs_good, _ = lint_published(out)
        check(errs_good == [], "발행게이트: relative_url 로 감싼 이미지는 통과(오탐 0)")
        os.remove(good)
        # (c) _drafts 에 남은 글 → WARN(라이브 미노출 경고)
        strand = os.path.join(out, "_drafts", "2026-06-07-strand.md")
        _write(strand, "---\nlayout: post\ntitle: strand\n---\n본문\n")
        _, warns = lint_published(out)
        check(any("strand" in w for w in warns),
              "발행게이트: _drafts 스트랜디드 글 경고(라이브 미노출)")
        os.remove(strand)

        # 9.6) 자동 교정(CMPA-224): 경로를 '실패' 대신 relative_url 로 자동 래핑.
        # (i) 단위: 베어→래핑 · 절대→래핑 · 이미감쌈→무변 · 외부URL→무변(오탐 0).
        w_bare, f_bare = wrap_baseurl_paths("![s](assets/img/x.png)")
        check("{{ '/assets/img/x.png' | relative_url }}" in w_bare and len(f_bare) == 1,
              "자동교정: 베어 상대경로(`](assets/..)`) → relative_url 래핑")
        w_abs, f_abs = wrap_baseurl_paths("![s](/assets/img/x.png)")
        check("{{ '/assets/img/x.png' | relative_url }}" in w_abs and len(f_abs) == 1,
              "자동교정: 사이트-절대경로(`](/assets/..)`) → relative_url 래핑")
        # VSCode markdown.copyFiles 산출(CMPA-223): ../ 접두 + 하위폴더(<글파일명>/).
        w_vsc, f_vsc = wrap_baseurl_paths("![](../assets/img/2026-06-08-foo/image.png)")
        check("{{ '/assets/img/2026-06-08-foo/image.png' | relative_url }}" in w_vsc
              and len(f_vsc) == 1,
              "자동교정: VSCode 상대경로(`](../assets/img/<sub>/x.png)`) → relative_url 래핑")
        # ../ 가 여러 번이어도 assets/ 부터 site-absolute 로 정규화.
        w_vsc2, f_vsc2 = wrap_baseurl_paths("![](../../assets/img/sub/y.png)")
        check("{{ '/assets/img/sub/y.png' | relative_url }}" in w_vsc2 and len(f_vsc2) == 1,
              "자동교정: 다중 ../ 접두(`](../../assets/..)`) → relative_url 래핑")
        # ../ 로 시작하지만 assets/ 로 귀결 안 되는 베어 링크는 범위 밖(무변·오탐 0).
        nonassets = "[m](../notes/other.md)"
        w_na, f_na = wrap_baseurl_paths(nonassets)
        check(w_na == nonassets and f_na == [],
              "자동교정: assets/ 아닌 ../ 베어링크(`](../notes/..)`) → 무변(오탐 0)")
        already = "![s]({{ '/assets/img/x.png' | relative_url }})"
        w_wrap, f_wrap = wrap_baseurl_paths(already)
        check(w_wrap == already and f_wrap == [],
              "자동교정: 이미 relative_url 로 감싼 경로 → 무변(멱등·오탐 0)")
        ext = "![logo](https://cdn.example.com/a.png) [x](//cdn/y) [m](other.md)"
        w_ext, f_ext = wrap_baseurl_paths(ext)
        check(w_ext == ext and f_ext == [],
              "자동교정: 외부 URL·스킴-상대·일반 베어링크 → 무변(오탐 0)")
        # (ii) 통합: 베어/절대 경로 손글 글이 빌드 게이트를 '실패 없이' 통과(수용기준 1).
        bad2 = os.path.join(out, "_posts", "2026-06-07-paste.md")
        _write(bad2, "---\nlayout: post\ntitle: paste\ndate: 2026-06-07 10:00:00 +0900\n"
                     "categories: [dev]\nrobots: noindex,nofollow\n---\n"
                     "![베어](assets/img/a.png)\n\n![절대](/assets/img/b.png)\n\n"
                     "![VSCode](../assets/img/2026-06-07-paste/c.png)\n")
        autofix_published(out)
        body2 = open(bad2, encoding="utf-8").read()
        errs2, _ = lint_published(out)
        check(errs2 == []
              and "{{ '/assets/img/a.png' | relative_url }}" in body2
              and "{{ '/assets/img/b.png' | relative_url }}" in body2
              and "{{ '/assets/img/2026-06-07-paste/c.png' | relative_url }}" in body2,
              "자동교정→게이트: 붙여넣기(베어·절대·VSCode ../) 경로 글이 실패 없이 통과 + relative_url 래핑")
        # front matter 보존(YAML 무파손) 확인.
        fm2, _ = _split_front_matter(body2)
        check(fm2 and fm2.get("title") == "paste",
              "자동교정: front matter 원형 보존(본문만 변형)")
        os.remove(bad2)

    print(("\nSELFTEST PASS" if not fails else f"\nSELFTEST FAIL ({len(fails)})"))
    return 0 if not fails else 1


def dry_run():
    """무네트워크·결정론 회귀0 증명: 임시 디렉터리 2회 빌드 → 상호 동일 +
    현행 blog-md/ 와도 동일(회귀 0)인지 비교(있을 때만)."""
    import tempfile

    def owned(d, written):
        # 생성기 소유 파일만 비교(손글 포스트·_site·.git·캐시는 제외 — 자연 무시).
        return {rel: open(os.path.join(d, rel), encoding="utf-8").read()
                for rel in written if os.path.isfile(os.path.join(d, rel))}

    with tempfile.TemporaryDirectory() as a, tempfile.TemporaryDirectory() as b:
        r1 = build(out_dir=a)
        r2 = build(out_dir=b)
        sa, sb = owned(a, r1["written"]), owned(b, r2["written"])
        deterministic = sa == sb and set(r1["written"]) == set(r2["written"])
        print(f"  빌드1 파일 {len(r1['written'])}개 · 빌드2 파일 {len(r2['written'])}개")
        print(f"  결정론(2회 빌드 동일): {'OK' if deterministic else 'FAIL'}")

        regression = None
        if os.path.isdir(DEFAULT_OUT):
            cur = owned(DEFAULT_OUT, r1["written"])
            same = cur == sa
            changed = sorted(set(cur) ^ set(sa))
            diff_files = [k for k in (set(cur) & set(sa)) if cur[k] != sa[k]]
            regression = same
            print(f"  현행 blog-md 대비: "
                  f"{'회귀 0 (동일)' if same else '차이 있음'}")
            if not same:
                if changed:
                    print(f"    파일 목록 차이: {changed}")
                if diff_files:
                    print(f"    내용 차이: {diff_files}")
        else:
            print("  (현행 blog-md 산출물 없음 — 첫 빌드)")
        print("  네트워크: 호출 없음(설계상 md 로컬 파싱만)")

    ok = deterministic and (regression is not False)
    print("\nDRY-RUN " + ("OK — 무네트워크·결정론·회귀0" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=DEFAULT_OUT, help="출력 디렉터리")
    ap.add_argument("--selftest", action="store_true",
                    help="md+front matter 유효성 자가검증")
    ap.add_argument("--dry-run", action="store_true",
                    help="무네트워크·결정론 회귀0 증명(파일 미변경)")
    ap.add_argument("--lint", action="store_true",
                    help="발행 전 게이트만 실행(절대경로 링크/이미지·스트랜디드 드래프트 검사)")
    ap.add_argument("--latest-only", action="store_true",
                    help="루틴 자동실행용(CMPA-264): 오늘자/최신 패치 1건만 (재)생성하고 "
                         "과거 패치·이번 달 base 글은 디스크에 보존(전체 rm·재생성 금지). "
                         "미지정 시 현행 full rebuild(수동 전체 재생성).")
    args = ap.parse_args()

    if args.selftest:
        sys.exit(selftest())
    if args.dry_run:
        sys.exit(dry_run())
    if args.lint:
        errors, warnings = lint_published(args.out)
        for w in warnings:
            print(f"  ⚠️  {w}")
        for e in errors:
            print(f"  ✗ {e}")
        print("발행 게이트 OK" if not errors else f"발행 게이트 실패({len(errors)})")
        sys.exit(1 if errors else 0)

    res = build(out_dir=args.out, latest_only=args.latest_only)
    if args.latest_only:
        print("  [latest-only] 오늘자/최신 패치만 생성 · 과거 글 보존(CMPA-264)")
    nb = len(res["patches"])
    print(f"{brand.NAME_EN} 블로그(md/Jekyll) 빌드 → {res['out']}")
    print(f"  본편(베이스): "
          + (f"{res['base']['date']} ({res['base']['src']})"
             if res["base"] else "없음"))
    print(f"  패치: {nb}개"
          + (f" (최신 {res['patches'][0]['latest_date']})" if nb else ""))
    for pm in res["patches"]:
        print(f"    - {pm['rel']} [{pm['cadence']}] 돌파 {pm['breaks']}건")
    print(f"  Jekyll: _config.yml · _layouts/default.html · assets/css/style.css · index.md")

    # 발행 전 자동 교정(CMPA-224): 손글 글의 절대/베어 이미지·링크 경로를 relative_url 로
    # 자동 래핑(에디터 붙여넣기 친화) — 보드가 손으로 감쌀 필요 없음. 무대상이면 no-op.
    fixed = autofix_published(args.out)
    for rel, changes in fixed:
        print(f"  🔧 경로 자동교정: {rel} — {len(changes)}건")
        for orig, _wrapped in changes:
            print(f"       '{orig}' → relative_url 래핑")

    # 발행 전 게이트(CMPA-221): 자동교정 후에도 남는 baseurl-깨짐 경로가 있으면 차단(안전망).
    errors, warnings = lint_published(args.out)
    for w in warnings:
        print(f"  ⚠️  발행경고: {w}")
    if errors:
        print(f"\n발행 게이트 실패({len(errors)}) — 자동교정 후에도 남은 baseurl 404 경로:")
        for e in errors:
            print(f"  ✗ {e}")
        print("  → 경로 형식을 확인하세요(예: front matter 내 경로는 자동교정 범위 밖). (참고: CMPA-224)")
        sys.exit(1)
    print("  발행 게이트: 손글 글 링크/이미지 OK(baseurl 안전, 필요시 자동교정 완료)")


if __name__ == "__main__":
    main()
