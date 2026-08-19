#!/usr/bin/env python3
"""Build the "합정 위마카세 — 테마 코스" flight page (self-contained, mobile-first).

CMPA-1323 (보드 확정 CMPA-1322): 기존 wimakase.html 3티어 메뉴와 별개로, 스토리형
"테마 3잔 플라이트 → 페스티벌 브릿지" 코스를 소개하는 **별도 HTML 페이지**.

산출물(둘 다 같은 HTML — 재생성 결정론적):
- blog-md/wimakase-course.html            : CaskCode Pages(godaji/CaskCode) 소스 미러
- deploy/menu/wimakase-course/index.html  : 메뉴 배포 산출물 위치

정본 스펙 = review/2026-08-19_0857_CMPA-1322_페스티벌-테마-3잔-플라이트-제안.md +
CMPA-1323 이슈 확정(E 신세계 몰트 제외, A는 2잔, 잔 수 two_plus = 3잔 기본 + 2잔 라이트 병기).

CLAUDE.md 준수:
- 모바일 우선(≈360px) + 카톡 인앱 웹뷰 우선: 100vw/100vh/backdrop-filter 금지, dvh 사용,
  viewport 메타, flex 자식 min-width:0. 발행 전 카톡에서 링크 직접 확인.
- 카피 톤 담백하게. 독자용 저자 필명 CaskCode(내부 호칭 "보드" 노출 금지).
- 위스키 상세/모달/기록(log)/카톡 안내 JS 자산은 build_wimakase_menu 에서 재사용해 룩앤필 통일.
- 위스키 상세는 보유 위스키 데이터 기준(신규 구매 없음).
"""
from __future__ import annotations

import html
import json
from pathlib import Path

import build_wimakase_menu as menu

ROOT = Path(__file__).resolve().parent.parent

# 발행마다 자동 증가하는 빌드 카운터 — 캐시버스트 신호(코스 페이지 전용 사이드카).
BUILD_FILE = Path(__file__).resolve().parent / "wimakase_course_build.txt"
VERSION = menu.VERSION
TITLE = menu.TITLE
COLLECTED = menu.COLLECTED

# ── 테마 코스 데이터 ─────────────────────────────────────────────────────────
# 각 코스: 스토리 곡선(저강도→고강도)으로 3잔을 낸 뒤 '→ 페스티벌 브릿지'로 프리플로우 전환.
# 잔 수 = two_plus(CMPA-1323): 각 코스 3잔 풀버전 + 2잔 라이트(양끝) 병기. A는 이미 2잔이라 그대로.
# glasses = [(위스키명, 잔 스토리), …]  위스키명은 build_wimakase_menu.TIERS/DETAILS 와 정확히 일치.
# light   = 2잔 라이트 버전에 남길 잔(위스키명 리스트). A는 full 과 동일.
# bridge  = '→ 페스티벌 브릿지' 한 줄.
COURSES = [
    {
        # CMPA-1329 신설(보드 필수): '내 취향 찾아보기' — 웰컴에서 스타일별 한 모금씩 탐색한 뒤
        # 끌린 갈래로 하이라이트 1잔을 고르는 분기형(choice) 게이트웨이 코스.
        # 고정 glasses 대신 welcome(3잔)+choice(버번/셰리/피트 3안) 스키마를 쓴다.
        "id": "★", "name": "내 취향 찾아보기", "tag": "스타일 탐색 → 하이라이트 선택",
        "lead": "버번·셰리·피트를 한 모금씩 맛본 뒤, 가장 끌리는 스타일로 한 잔 더 깊이 들어갑니다. 어디서부터 시작할지 모르겠다면 여기부터.",
        "welcome": [
            ("러셀 리저브 싱글배럴", "버번 갈래 · 바닐라·오크의 미국 위스키 원형."),
            ("글렌드로낙 12년", "셰리 갈래 · 다크초콜릿·건포도, 셰리 캐스크 교과서."),
            ("탈리스커 10년", "피트 갈래 · 해안 스모크·후추의 입문 피트."),
        ],
        "choice": [
            ("🥃 버번이 끌렸다면", "스테그 (Stagg)", "프리미엄 CS 버번의 압도적 타격감. → 버번 매니아 코스로."),
            ("🍇 셰리가 끌렸다면", "글렌드로낙 21년", "웰컴의 12년과 수직으로 잇는 고숙성 셰리. → 셰리 매니아 코스로."),
            ("🔥 피트가 끌렸다면", "옥토모어 15.1", "108.2 PPM, 피트의 정점. → 피트 매니아 코스로."),
        ],
        "bridge": "하우스 위스키·조니워커 그린으로 페스티벌 프리플로우.",
    },
    {
        "id": "A", "name": "셰리의 시간여행", "tag": "글렌드로낙 수직 시음",
        "lead": "같은 증류소가 오래 잠들수록 어떻게 깊어지는가. 12년과 21년을 나란히 비교하는 수직 시음.",
        "glasses": [
            ("글렌드로낙 12년", "셰리 캐스크의 교과서. 다크초콜릿·건포도의 밑그림."),
            ("글렌드로낙 21년", "같은 DNA가 9년 더 잠들면. 다크프루츠·스파이스가 층층이."),
        ],
        "light": ["글렌드로낙 12년", "글렌드로낙 21년"],
        "light_note": "이미 2잔 코스입니다.",
        "bridge": "하우스 위스키·조니워커 그린으로 부드럽게 착지.",
    },
    {
        "id": "B", "name": "버번 매니아", "tag": "켄터키 버번 사다리 · 저→중→고",
        "lead": "도수와 희소성이 한 계단씩 올라가는 버번 사다리.",
        "glasses": [
            ("이글레어 10년", "버팔로트레이스의 프리미엄 엔트리. 정석 바닐라·오크."),
            ("러셀 리저브 싱글배럴", "버번 매니아들의 지지. 싱글배럴의 진한 개성."),
            ("스테그 (Stagg)", "구하기 힘든 프리미엄 CS 버번. 압도적 타격감."),
        ],
        "light": ["이글레어 10년", "스테그 (Stagg)"],
        "bridge": "놉크릭 9년·엔젤스 엔비로 여운의 버번 프리플로우.",
    },
    {
        "id": "C", "name": "피트 매니아", "tag": "피트의 강도 여행 · 아일라→옥토모어",
        "lead": "스모크가 낮은 데서 세계 최고 수치까지. PPM 사다리.",
        "glasses": [
            ("탈리스커 10년", "해안 후추·바다향. 접근하기 좋은 피트 입문."),
            ("아드벡 10년", "강렬한 아일라 스모크의 대명사."),
            ("옥토모어 15.1", "108.2 PPM, 세계 최고 수준 피트의 정점."),
        ],
        "light": ["탈리스커 10년", "옥토모어 15.1"],
        "bridge": "몽키숄더·닛카 프론티어 하이볼로 입을 식히며 마무리.",
    },
    {
        "id": "D", "name": "호밀의 화사함", "tag": "라이 3종",
        "lead": "부드러운 캐네디언에서 배럴프루프까지. 라이 특유의 스파이시·허브 스펙트럼.",
        "glasses": [
            ("LOT 40", "호밀빵·허브의 화사함. 캐네디언 라이 입문."),
            ("사가모어 라이 CS", "CS 특유의 강렬한 타격감과 진한 화사함."),
            ("와일드터키 레어브리드 라이", "배럴프루프 라이의 타격감과 풍미."),
        ],
        "light": ["LOT 40", "와일드터키 레어브리드 라이"],
        "bridge": "제임슨·LOT 40으로 가볍게 이어가기.",
    },
    {
        "id": "F", "name": "꿀과 바닐라", "tag": "달콤 입문 코스",
        "lead": "도수·자극이 낮은, 입문자용 부드러운 여정. 40도 위주.",
        "glasses": [
            ("발베니 12년 더블우드", "꿀·바닐라의 정석. 화사한 달콤함."),
            ("에버펠디 16년", "부드럽고 꿀 같은 고숙성."),
            ("글렌피딕 18년", "잘 익은 사과·오크 스파이스로 마무리."),
        ],
        "light": ["발베니 12년 더블우드", "글렌피딕 18년"],
        "bridge": "조니워커 그린·몽키숄더로 무난하게 프리플로우.",
    },
    {
        "id": "G", "name": "셰리 매니아", "tag": "셰리 폭탄 사다리 · CS 셰리",
        "lead": "진득한 셰리에서 꾸덕한 CS 폭탄까지. 셰리 러버 특화 코스.",
        "glasses": [
            ("글렌알라키 15년", "진득한 셰리. 최근 최고 인기 바틀."),
            ("카발란 올로로소", "대만 열대 숙성 셰리 CS."),
            ("아벨라워 아브나흐", "꾸덕한 셰리 폭탄. 강력한 CS."),
        ],
        "light": ["글렌알라키 15년", "아벨라워 아브나흐"],
        "bridge": "하우스 위스키로 마무리.",
    },
]

# 위스키명 → (name, cat, abv, notes) 튜플 조회 — 도수/분류/특징을 정본 TIERS 에서 가져온다.
_BY_NAME: dict[str, tuple[str, str, str, str]] = {}
for _t in menu.TIERS:
    for _it in _t["items"]:
        _BY_NAME[_it[0]] = _it

def _course_names(course: dict) -> list[str]:
    """코스에 등장하는 모든 위스키명(검증·key 생성용, 등장 순서 보존)."""
    if course.get("welcome") is not None:  # 분기형(내 취향 찾아보기)
        names = [g[0] for g in course["welcome"]]
        names += [c[1] for c in course["choice"]]
        return names
    names = [g[0] for g in course["glasses"]]
    names += course["light"]
    return names


# 코스에 등장하는 모든 위스키를 검증(오탈자·미보유 조기 발견).
for _c in COURSES:
    for _n in _course_names(_c):
        if _n not in _BY_NAME:
            raise KeyError(f"코스 {_c['id']} 위스키 미매칭(TIERS 에 없음): {_n}")


# ── 코스 페이지 전용 추가 CSS (기존 PAGE_CSS 룩앤필에 얹는다) ────────────────────
COURSE_CSS = """
/* ── 코스 페이지 전용 — 기존 위마카세 다크 테마에 얹음(CMPA-1323) ── */
.lead{color:#cdd2da;font-size:.9rem;line-height:1.65;margin:8px 0 2px;
 word-break:keep-all;overflow-wrap:anywhere}
.backlink{display:inline-flex;align-items:center;gap:6px;margin:8px 0 2px;
 color:#e0a84e;font-size:.86rem;font-weight:700;text-decoration:none;
 background:#1a1508;border:1px solid #3a2f1a;border-radius:10px;padding:8px 13px;
 -webkit-tap-highlight-color:transparent}
.backlink:active{transform:scale(.97)}
.course{background:#12100a;border:1px solid #2e2712;border-radius:14px;
 padding:14px 13px 12px;margin:14px 0 0;min-width:0}
.chead{border-bottom:1px solid #2a2413;padding-bottom:.5em;margin-bottom:2px}
.cid{display:inline-block;background:#1a1508;color:#e0a84e;border:1px solid #3a2f1a;
 border-radius:8px;font-size:.78rem;font-weight:800;padding:1px 8px;margin-right:.4em;
 vertical-align:middle;font-variant-numeric:tabular-nums}
.cname{color:#e0a84e;font-size:1.06rem;font-weight:800;line-height:1.3;word-break:keep-all}
.ctag{display:inline-block;color:#cdbf9a;font-size:.74rem;font-weight:700;
 margin-left:.4em;vertical-align:middle;word-break:keep-all}
.clead{color:#cdd2da;font-size:.83rem;line-height:1.6;margin:7px 0 2px;
 word-break:keep-all;overflow-wrap:anywhere}
/* 잔 스토리 한 줄(카드 아래 회색) */
.rstory{color:#9aa0aa;font-size:.76rem;line-height:1.45;margin:1px 0 0;
 word-break:keep-all;overflow-wrap:anywhere}
/* 순서 번호 배지 — .rtap 의 첫 flex 자식 */
.cstep{flex:none;width:22px;height:22px;border-radius:50%;background:#1a1508;
 border:1px solid #3a2f1a;color:#e0a84e;font-size:.78rem;font-weight:800;line-height:22px;
 text-align:center;font-variant-numeric:tabular-nums;margin-right:2px}
/* 2잔 라이트 버전 안내 */
.clight{margin:11px 0 0;padding:9px 11px;background:#0f1115;border:1px solid #24242e;
 border-radius:10px;color:#9fd8e6;font-size:.8rem;line-height:1.55;
 word-break:keep-all;overflow-wrap:anywhere;min-width:0}
.clight b{color:#7fd0e0;font-weight:700}
/* 페스티벌 브릿지 한 줄 */
.cbridge{margin:10px 0 0;color:#cdbf9a;font-size:.8rem;line-height:1.55;
 border-top:1px solid #2a2413;padding-top:9px;word-break:keep-all;overflow-wrap:anywhere}
.cbridge b{color:#e0a84e;font-weight:700}
/* 내 취향 찾아보기(분기형) — 웰컴/하이라이트 소제목 + 선택지 블록 */
.csub{color:#e0a84e;font-size:.82rem;font-weight:800;margin:12px 0 4px;
 word-break:keep-all;overflow-wrap:anywhere}
.cchoice{margin:7px 0 0;padding:8px 10px 6px;background:#0f0e08;border:1px solid #241f10;
 border-radius:11px;min-width:0}
.cbranch{color:#cdbf9a;font-size:.79rem;font-weight:800;margin:0 0 2px;
 word-break:keep-all;overflow-wrap:anywhere}
.cchoice .row{border-bottom:none}
"""


def _glass_row(key: str, item: tuple[str, str, str, str], marker, story: str) -> str:
    """코스 잔 한 줄 — 탭하면 상세 팝업(MODAL_JS), ＋ 누르면 기록(LOG_JS). 기존 .row 구조 재사용.
    marker: 순서 배지에 넣을 문자(숫자 스텝 또는 '→' 등). 빈 문자면 배지 생략."""
    name, cat, abv, _notes = item
    e = html.escape
    badge = f'<span class="cstep" aria-hidden="true">{e(str(marker))}</span>' if marker else ""
    return (
        '<div class="row">'
        f'<button type="button" class="rtap" data-w="{e(key)}">'
        f'{badge}'
        '<span class="rmain">'
        f'<span class="rname">{e(name)}</span>'
        f'<span class="rstory">{e(story)}</span></span>'
        f'<span class="rabv">{e(abv)}</span></button>'
        f'<button type="button" class="radd" data-w="{e(key)}" '
        f'aria-label="{e(name)} 마신 목록에 담기" title="마신 목록에 담기">＋</button>'
        '</div>'
    )


def _choice_course_section(course: dict, keys: dict) -> str:
    """분기형 코스(내 취향 찾아보기) — 웰컴 탐색 3잔 + 하이라이트 선택 3안."""
    e = html.escape
    wrows = "\n  ".join(
        _glass_row(keys[name], _BY_NAME[name], i, story)
        for i, (name, story) in enumerate(course["welcome"], start=1)
    )
    choices = []
    for label, name, story in course["choice"]:
        row = _glass_row(keys[name], _BY_NAME[name], "→", story)
        choices.append(
            f'<div class="cchoice"><div class="cbranch">{e(label)}</div>'
            f'<div class="list">{row}</div></div>'
        )
    choices_html = "\n  ".join(choices)
    return f"""<section class="course">
  <div class="chead">
    <span class="cid">{e(course['id'])}</span><span class="cname">{e(course['name'])}</span>
    <span class="ctag">{e(course['tag'])}</span>
  </div>
  <p class="clead">{e(course['lead'])}</p>
  <div class="csub">① 웰컴 탐색 · 종류별로 한 모금씩</div>
  <div class="list">
  {wrows}
  </div>
  <div class="csub">② 하이라이트 · 끌린 스타일로 한 잔 더</div>
  {choices_html}
  <div class="cbridge">→ <b>페스티벌 브릿지</b> · {e(course['bridge'])}</div>
</section>"""


def _course_section(course: dict, keys: dict) -> str:
    if course.get("welcome") is not None:
        return _choice_course_section(course, keys)
    e = html.escape
    rows = []
    for i, (name, story) in enumerate(course["glasses"], start=1):
        rows.append(_glass_row(keys[name], _BY_NAME[name], i, story))
    rows_html = "\n  ".join(rows)
    n = len(course["glasses"])
    # 2잔 라이트 안내
    if course.get("light_note"):
        light_html = (
            f'<div class="clight">🥂 <b>2잔 라이트</b> · {e(course["light_note"])}</div>'
        )
    else:
        light_html = (
            '<div class="clight">🥂 <b>2잔 라이트</b> · '
            + " → ".join(e(x) for x in course["light"])
            + "</div>"
        )
    return f"""<section class="course">
  <div class="chead">
    <span class="cid">{e(course['id'])}</span><span class="cname">{e(course['name'])}</span>
    <span class="ctag">{e(course['tag'])}</span>
  </div>
  <p class="clead">{e(course['lead'])}</p>
  <div class="list">
  {rows_html}
  </div>
  {light_html}
  <div class="cbridge">→ <b>페스티벌 브릿지</b> · {e(course['bridge'])}</div>
</section>"""


def _build_data(keys: dict) -> dict:
    """카드 key → 팝업(MODAL_JS)·기록(LOG_JS)에 뿌릴 상세 데이터. build_wimakase_menu.DETAILS 재사용."""
    data = {}
    for name, key in keys.items():
        item = _BY_NAME[name]
        _n, cat, abv, notes = item
        d = menu.DETAILS.get(name, {})
        # 이 위스키가 원래 어느 티어인지 라벨(모달 태그에 노출).
        tier_name = ""
        for t in menu.TIERS:
            if any(x[0] == name for x in t["items"]):
                tier_name = t["name"]
                break
        data[key] = {
            "name": name, "cat": cat, "abv": abv, "notes": notes,
            "tier": tier_name,
            "distillery": d.get("distillery", ""),
            "region": d.get("region", ""),
            "cask": d.get("cask", ""),
            "story": d.get("story", ""),
            "source": d.get("source", ""),
            "noimg": name in menu.NO_IMAGE_SEARCH,
        }
    return data


def _next_build() -> int:
    try:
        n = int(BUILD_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        n = 0
    n += 1
    BUILD_FILE.write_text(f"{n}\n", encoding="utf-8")
    return n


def render(build: int) -> str:
    e = html.escape
    cache_tag = f"{VERSION}-c{build}"  # 코스 페이지 캐시버스트 라벨(메뉴 b# 와 구분해 c#)
    # 위스키명 → 안정 key(w1..) — 같은 위스키가 여러 코스에 나와도 key 하나로 공유.
    keys: dict[str, str] = {}
    for c in COURSES:
        for name in _course_names(c):
            if name not in keys:
                keys[name] = f"w{len(keys) + 1}"
    courses_html = "\n".join(_course_section(c, keys) for c in COURSES)
    data_json = json.dumps(_build_data(keys), ensure_ascii=False)
    collected_json = json.dumps(COLLECTED, ensure_ascii=False)
    n_courses = len(COURSES)
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<!-- 캐시버스트(CMPA-1285 패턴): 카톡/iOS 웹뷰가 옛 버전을 붙잡지 않게 no-cache 신호 + 빌드 라벨 {e(cache_tag)} -->
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<meta name="build" content="{e(cache_tag)}">
<link rel="canonical" href="wimakase-course.html?v={e(cache_tag)}">
<!-- 카톡 인앱 → 강제 외부 브라우저 리다이렉트(CMPA-1286). 깨진 렌더 전에 즉시 실행하려 head에 둔다. -->
<script>{menu.REDIRECT_JS}</script>
<title>{e(TITLE)} · 테마 코스 {e(VERSION)}</title>
<meta name="description" content="{e(TITLE)} 테마 3잔 플라이트 코스 {n_courses}종 — 스토리형 저강도→고강도 시음 후 페스티벌 프리플로우로. {e(VERSION)}">
<style>
{menu.PAGE_CSS}
{COURSE_CSS}
</style>
</head>
<body><div class="wrap">
<header>
  <h1>합정 두다지 <span class="gold">위마카세</span> · 테마 코스</h1>
</header>
<div class="extbar" id="extbar">
  <span class="extmsg">📱 화면이 깨져 보이면</span>
  <button type="button" id="extbtn">🔗 새 창(기본 브라우저)에서 열기</button>
</div>

<a class="backlink" href="wimakase.html">← 전체 메뉴(웰컴·하이라이트·페스티벌)로</a>
<p class="lead">테마 하나를 고르면 그 스토리를 따라 <b style="color:#e0a84e">저강도 → 고강도</b>로 잔을 냅니다. 3잔 풀버전이 기본이고, 가볍게 즐기실 분을 위한 <b style="color:#7fd0e0">2잔 라이트</b>도 함께 안내합니다. 마지막엔 <b style="color:#e0a84e">페스티벌 프리플로우(무제한)</b>로 자연스럽게 이어집니다. 잔을 탭하면 상세가 열리고, ＋ 로 내 기록에 담을 수 있어요.</p>

{courses_html}

<p class="note">위스키를 탭하면 상세·구글 이미지 검색이 열리고, 옆의 ＋ 를 누르면 그날 마신 목록에 담깁니다 · 📒 내 기록에서 ✏️ 로 메모도 남길 수 있어요</p>

<footer>합정 위마카세 · 테마 코스 {e(VERSION)} &nbsp;·&nbsp; CaskCode<br>메뉴는 수시로 업데이트됩니다 — 버전을 확인하세요 🥃<br>상세 정보는 위키피디아 등 공개 자료를 요약한 참고용입니다 · 수집 {e(COLLECTED)}<br><span style="color:#3b414b;font-size:.68rem">build {e(cache_tag)}</span></footer>
</div>

<div class="mask" id="mask" role="dialog" aria-modal="true" aria-label="위스키 상세">
  <div class="modal"><div class="mgrip"></div><div id="mbody"></div></div>
</div>

<button type="button" class="fab" id="fab" aria-label="내가 마신 목록 열기">📒 내 기록 <span class="cnt" id="fabcnt">0</span></button>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
<div class="mask" id="logmask" role="dialog" aria-modal="true" aria-label="내가 마신 목록">
  <div class="modal"><div class="mgrip"></div><div id="logbody"></div></div>
</div>

<div class="kkomask" id="kkomask" role="dialog" aria-modal="true" aria-label="다른 브라우저로 열기 안내">
  <div class="kkobox">
    <div class="kkoicon">🔗</div>
    <h2>다른 브라우저로 열어주세요</h2>
    <p>카카오톡 안에서는 화면이 깨져 보일 수 있어요.<br>크롬·사파리에서 열면 편하게 보실 수 있습니다.</p>
    <ol class="kkosteps">
      <li>화면 <b>우측 하단 ⁝</b>(더보기)를 누르세요</li>
      <li><b>다른 브라우저로 열기</b>를 선택하세요</li>
    </ol>
    <button type="button" class="kkoopen" id="kkoopen">🔗 기본 브라우저에서 다시 열기</button>
    <button type="button" class="kkoclose" id="kkoclose">그냥 여기서 볼게요</button>
    <div class="kkofoot">CaskCode</div>
  </div>
</div>

<script>window.__WIMAKASE__={data_json};window.__WM_COLLECTED__={collected_json};</script>
<script>
{menu.MODAL_JS}
{menu.LOG_JS}
{menu.EXT_JS}
</script>
</body>
</html>
"""


def build() -> tuple[list[Path], int]:
    build_no = _next_build()
    doc = render(build_no)
    outs = [
        ROOT / "blog-md" / "wimakase-course.html",
        ROOT / "deploy" / "menu" / "wimakase-course" / "index.html",
    ]
    written = []
    for p in outs:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(doc, encoding="utf-8")
        written.append(p)
    return written, build_no


if __name__ == "__main__":
    paths, build_no = build()
    n_glass = sum(
        len(c["welcome"]) + len(c["choice"]) if c.get("welcome") is not None
        else len(c["glasses"])
        for c in COURSES
    )
    print(f"built 위마카세 테마 코스 {VERSION}-c{build_no} — {len(COURSES)}코스 · {n_glass}잔")
    for p in paths:
        print(f"  {p.relative_to(ROOT)}")
