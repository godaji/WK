#!/usr/bin/env python3
"""CaskCode 블로그 — 브랜드 자산 + 설정 (CMPA-176 → CMPA-182 리브랜드).

리브랜드(CMPA-182 보드 지시 2026-06-07): 기존 'Code, Cask & Cabin'(3C, 코캐캐)에서
**Cabin 제거 + 한 단어 'CaskCode'** 로 바꾸고 기둥을 2개(Code/Cask)로 재구성한다.
  - 이름: NAME_EN = "CaskCode" (Cabin 제거, 한 단어). 닉네임 '코캐/코캐캐'는 전부 제거
    (보드: '코캐도 필요 없어, 그냥 CaskCode').
  - 핸들: 제거됨(보드 CMPA-194 → CMPA-195). 폐기된 'Cabin' 네이밍을 품은 @codecaskcabin 은
    리브랜드와 충돌해 노출을 전부 없앤다. 신규 SNS 핸들(@caskcode 등) 도입은 별도 보드 결정.
  - MONOGRAM: 3C(비행기 좌석 'SEAT 3C' 개그, CMPA-144)는 Cabin 제거로 의미 상실 →
    **칩 완전 제거**(보드 확정 CMPA-182 인터랙션 cf640730: monogram=remove). MONOGRAM=""
    이면 seat_badge_html() 가 빈 문자열을 반환해 칩이 렌더되지 않는다.
  - 컬러/타이포: 컨셉1 '보딩패스/터미널 전광판' (런칭킷 2-3) — 다크 차콜 + 앰버(위스키색)
    + 전광판 화이트, 모노스페이스 헤드라인. 플립보드 워드마크 = CASK·CODE.
  - TAGLINE/ABOUT 최종 문구 polish 는 CMPA-181(CMO) 소관 — 본 파일은 구조/이름만 정리.

이 블로그는 **내부 스테이징본**이다. 외부 발행은 보드 게이트(c7405e7d) 승인 후에만.
"""
from __future__ import annotations

import html

# ── 브랜드 텍스트 (CMPA-182 리브랜드) ─────────────────────────────────
NAME_EN = "CaskCode"
NAME_KO = ""  # 보드: 코캐 불필요. 비움(또는 '캐스크코드' — CMPA-182 인터랙션 확인).
MONOGRAM = ""  # 보드 확정(cf640730): 3C/CC 칩 완전 제거. 빈 값이면 칩 미렌더.
HANDLE = ""  # 제거됨(보드 CMPA-194 → CMPA-195). 빈 값이면 마스트헤드·푸터·사이드바·author 미렌더.
# TAGLINE/ABOUT 최종 문구 — CMPA-181(CMO), 보드 택1(인터랙션 5448c4c2): 태그라인 TC1 + About B.
# 정체성: 사업부서 소속이나 마음은 개발자(현업 ~3년 공백), 취미로 바이브코딩하며
# 위스키를 코드·데이터로 분석해 공유. 기둥 2개 Code(개발)·Cask(위스키). 톤=담백+위트.
TAGLINE = "Cask 한 잔, Code 한 줄."
ABOUT = ("CaskCode(사람)와 Dram(AI)이 함께 쓰는 블로그. "
         "위스키·여행 등을 다룹니다. #CaskCode")

# [DEPRECATED CMPA-202] 푸터 노출 폐기(보드 지시). 더 이상 어떤 페이지에도 렌더하지 않음.
# 상수는 build_blog_md selftest 의 '부재 검증'(STAGING_NOTICE not in layout)에서만 참조.
# noindex/robots 게이트(별개 SEO 보호장치)는 유지 — 본 문구와 무관.
STAGING_NOTICE = ("내부 스테이징본 — 외부 발행 전(보드 게이트 c7405e7d). "
                  "가격은 각 스냅샷 수집일 기준값.")

# ── 컬러/타이포 (런칭킷 2-3 컨셉1) ────────────────────────────────────
# 기존 면세 리포트 팔레트(--bg #0f1115, gold #ffd34e)와 한 팔레트로 묶이도록 맞춤.
CSS_VARS = {
    "bg": "#0f1115",       # 다크 차콜/네이비
    "panel": "#161922",
    "line": "#2a2e38",
    "txt": "#f2efe6",      # 전광판 화이트
    "sub": "#9aa0aa",
    "amber": "#e0a84e",    # 위스키 호박색 (포인트)
    "gold": "#ffd34e",
    "green": "#34c759",
    "red": "#ff6b6b",
}
FONT_BODY = ('-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo",'
             '"Malgun Gothic",sans-serif')
FONT_MONO = ('"JetBrains Mono","D2Coding","SFMono-Regular",Consolas,'
             '"Liberation Mono",monospace')


def _vars_css() -> str:
    return ";".join(f"--{k}:{v}" for k, v in CSS_VARS.items())


# ── 공통 <style> (page_shell 전용; 베이스 래핑은 별도 scoped fragment 사용) ──
def base_style() -> str:
    return f"""
:root{{{_vars_css()}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--bg);color:var(--txt);
font-family:{FONT_BODY};line-height:1.6;font-size:16px}}
.wrap{{max-width:620px;margin:0 auto;padding:0 14px 64px}}
a{{color:var(--amber);text-decoration:none}}
a:hover{{text-decoration:underline}}
h1,h2,.flap{{font-family:{FONT_MONO}}}
.mast{{text-align:center;padding:26px 14px 14px;border-bottom:1px solid var(--line)}}
.flap{{font-size:20px;font-weight:800;letter-spacing:.14em;color:var(--gold)}}
.flap .dot{{color:var(--amber)}}
.tag{{color:var(--txt);font-size:14px;margin:8px 0 4px}}
.sub{{color:var(--sub);font-size:12.5px}}
.seat{{display:inline-block;background:var(--amber);color:#1a1300;font-family:{FONT_MONO};
font-weight:800;font-size:11px;padding:1px 7px;border-radius:4px;margin-right:6px}}
.badge{{display:inline-block;font-family:{FONT_MONO};font-weight:800;font-size:12px;
padding:3px 10px;border-radius:999px;margin:2px 0}}
.badge.instant{{background:rgba(255,211,78,.16);color:var(--gold)}}
.badge.digest{{background:rgba(154,160,170,.16);color:var(--sub)}}
.note{{background:rgba(224,168,78,.10);border-left:3px solid var(--amber);
color:#d9d2c2;font-size:13px;padding:9px 12px;border-radius:6px;margin:14px 0}}
h2{{font-size:16px;color:var(--amber);margin:26px 0 10px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:14px;
padding:13px 15px;margin:10px 0}}
.card.hero{{border-color:rgba(255,211,78,.45);
background:linear-gradient(180deg,rgba(255,211,78,.07),var(--panel))}}
.card .n{{font-weight:700;font-size:15.5px}}
.card .row{{display:flex;flex-wrap:wrap;gap:10px 16px;margin-top:7px;align-items:baseline}}
.price{{font-family:{FONT_MONO};font-weight:800;font-size:19px;color:var(--gold)}}
.floor{{font-family:{FONT_MONO};color:var(--sub);text-decoration:line-through;font-size:14px}}
.save{{font-family:{FONT_MONO};color:var(--green);font-weight:800;font-size:13.5px}}
.meta{{color:var(--sub);font-size:12.5px}}
.empty{{color:var(--sub);font-size:13.5px;margin:6px 0}}
ul.list{{list-style:none;padding:0;margin:8px 0}}
ul.list li{{padding:9px 0;border-bottom:1px solid var(--line)}}
ul.list li .when{{font-family:{FONT_MONO};color:var(--amber);font-weight:700}}
.foot{{margin-top:34px;padding-top:16px;border-top:1px solid var(--line);
color:var(--sub);font-size:12.5px}}
.foot .about{{margin:8px 0;color:#cfd3da}}
.foot .gate{{color:var(--red);font-weight:700;margin-top:8px}}
.back{{display:inline-block;margin:14px 0 0;font-family:{FONT_MONO};font-size:13px}}
""".strip()


def flap_html(flap_cls: str = "flap", dot_cls: str = "dot") -> str:
    """플립보드 워드마크 — CASK·CODE (CaskCode, 2기둥). 마스트헤드 전역 단일 소스."""
    return (f'<div class="{flap_cls}">CASK'
            f'<span class="{dot_cls}"> · </span>CODE</div>')


def seat_badge_html(cls: str = "seat") -> str:
    """모노그램 칩(CC). MONOGRAM 이 비면 칩을 렌더하지 않는다(보드가 제거 선택 시)."""
    return f'<span class="{cls}">{html.escape(MONOGRAM)}</span>' if MONOGRAM else ""


def _name_handle() -> str:
    """푸터 1행 — 'CaskCode · @핸들'. HANDLE 제거 시(CMPA-195) trailing ' · ' 없이 이름만."""
    if HANDLE:
        return f'{html.escape(NAME_EN)} · {html.escape(HANDLE)}'
    return html.escape(NAME_EN)


def masthead_html(compact: bool = False) -> str:
    """블로그 톱 마스트헤드 — 보딩패스/전광판 모티프(런칭킷 컨셉1)."""
    tag = "" if compact else f'<div class="tag">{html.escape(TAGLINE)}</div>'
    # HANDLE 제거(CMPA-195) + MONOGRAM 칩 제거(CMPA-182) → sub 내용이 비면 빈 div 미렌더.
    sub_inner = f'{seat_badge_html()}{html.escape(HANDLE)}'
    sub = f'<div class="sub">{sub_inner}</div>' if sub_inner else ""
    return (
        '<div class="mast">'
        f'{flap_html()}'
        f'{tag}'
        f'{sub}'
        '</div>'
    )


def footer_html() -> str:
    return (
        '<div class="foot">'
        f'<div>{_name_handle()}</div>'
        f'<div class="about">{html.escape(ABOUT)}</div>'
        '</div>'
    )


def page_shell(title: str, inner_html: str, description: str = "",
               compact_mast: bool = False) -> str:
    """브랜드 정체성을 입힌 단독 HTML 페이지(커버/패치용)."""
    desc = description or ABOUT
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{html.escape(desc)}">
<meta name="robots" content="noindex,nofollow">
<title>{html.escape(title)} — {html.escape(NAME_EN)}</title>
<style>
{base_style()}
</style>
</head>
<body>
{masthead_html(compact=compact_mast)}
<div class="wrap">
{inner_html}
{footer_html()}
</div>
</body>
</html>
"""


# ── 베이스(월초) 리포트 래핑용 scoped fragment ───────────────────────
# 기존 면세 리포트 HTML(자체 <style> 보유)을 건드리지 않고 <body> 바로 뒤/끝에
# 끼워 넣는다. 클래스는 ccc- 프리픽스로 충돌 회피.
def base_wrap_masthead() -> str:
    v = _vars_css()
    return f"""
<style>
.ccc-mast{{text-align:center;padding:22px 14px 14px;border-bottom:1px solid {CSS_VARS['line']};
font-family:{FONT_BODY};{v}}}
.ccc-flap{{font-family:{FONT_MONO};font-size:19px;font-weight:800;letter-spacing:.14em;
color:{CSS_VARS['gold']}}}
.ccc-flap .d{{color:{CSS_VARS['amber']}}}
.ccc-tag{{color:{CSS_VARS['txt']};font-size:13.5px;margin:7px 0 4px}}
.ccc-sub{{color:{CSS_VARS['sub']};font-size:12.5px}}
.ccc-seat{{display:inline-block;background:{CSS_VARS['amber']};color:#1a1300;
font-family:{FONT_MONO};font-weight:800;font-size:11px;padding:1px 7px;border-radius:4px;
margin-right:6px}}
.ccc-nav{{max-width:620px;margin:14px auto 0;padding:0 14px}}
.ccc-nav h2{{font-family:{FONT_MONO};font-size:15px;color:{CSS_VARS['amber']};margin:6px 0 8px}}
.ccc-nav ul{{list-style:none;padding:0;margin:0}}
.ccc-nav li{{padding:8px 0;border-bottom:1px solid {CSS_VARS['line']};font-size:13.5px}}
.ccc-nav .when{{font-family:{FONT_MONO};color:{CSS_VARS['amber']};font-weight:700;margin-right:6px}}
.ccc-nav .b{{display:inline-block;font-family:{FONT_MONO};font-weight:800;font-size:11.5px;
padding:2px 8px;border-radius:999px;margin-left:6px}}
.ccc-nav .b.i{{background:rgba(255,211,78,.16);color:{CSS_VARS['gold']}}}
.ccc-nav .b.d{{background:rgba(154,160,170,.16);color:{CSS_VARS['sub']}}}
.ccc-nav .m{{color:{CSS_VARS['sub']};font-size:12px}}
.ccc-nav .empty{{color:{CSS_VARS['sub']};font-size:13px}}
.ccc-foot{{max-width:620px;margin:30px auto 0;padding:16px 14px 40px;
border-top:1px solid {CSS_VARS['line']};color:{CSS_VARS['sub']};font-size:12.5px;
font-family:{FONT_BODY}}}
.ccc-foot .a{{margin:8px 0;color:#cfd3da}}
.ccc-foot .g{{color:{CSS_VARS['red']};font-weight:700;margin-top:8px}}
</style>
{_ccc_mast()}
"""


def _ccc_mast() -> str:
    # HANDLE 제거(CMPA-195) + 칩 제거 → ccc-sub 가 비면 빈 줄 미렌더.
    sub_inner = f'{seat_badge_html("ccc-seat")}{html.escape(HANDLE)}'
    sub = f'<div class="ccc-sub">{sub_inner}</div>' if sub_inner else ""
    return (
        '<div class="ccc-mast">\n'
        f'  {flap_html("ccc-flap", "d")}\n'
        f'  <div class="ccc-tag">{html.escape(TAGLINE)} · <b>이달의 본편</b></div>\n'
        f'  {sub}\n'
        '</div>'
    )


def base_wrap_footer() -> str:
    return f"""
<div class="ccc-foot">
  <div>{_name_handle()}</div>
  <div class="a">{html.escape(ABOUT)}</div>
</div>
"""
