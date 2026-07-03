#!/usr/bin/env python3
"""Build the QR-accessible whisky gathering pages + QR codes.

CMPA-122: 합정 제이원빌딩 위스키 모임용 페이지. 행사는 반복되고 메뉴는 바뀔 수 있어서
**날짜별 이벤트 페이지** 구조로 만든다.

구조(deploy/menu/ 하위):
- <slug>/index.html : 날짜별 행사 페이지(장소 약도 + 메뉴). 예: 260604/
- <slug>/qr.{svg,png,html} : 그 행사 영구 QR
- index.html : 허브 — 최신 행사로 자동 이동(+행사 목록 폴백)
- qr.{svg,png,html} : /menu/ 를 가리키는 QR(항상 최신 행사로 연결) — 기존 인쇄물 그대로 유효

메뉴 데이터는 사용자 PDF 2종에서 옮긴 정본. 장소는 네이버 플레이스(제이원빌딩 id 1043031630).
"""
from __future__ import annotations

import datetime
import html
from pathlib import Path

import segno

ROOT = Path(__file__).resolve().parent.parent
MENU_DIR = ROOT / "deploy" / "menu"

# 사용자가 deploy 폴더를 배포하는 Netlify 루트. 메뉴는 /menu/ 하위.
SITE_ROOT = "https://effortless-piroshki-f245ef.netlify.app"
MENU_URL = f"{SITE_ROOT}/menu/"

EVENT_PLACE = "합정"

# ── 장소(네이버 플레이스 id 1043031630 에서 확인) ────────────────────────────
VENUE = {
    "name": "제이원빌딩",
    "area": "합정 · 서교동",
    "addr": "서울 마포구 서교동 395-143",
    "naver": "https://naver.me/x1m0L9p4",  # 네이버 지도 · 길찾기
    "lat": 37.5514485,
    "lon": 126.9182475,
}

# ── 공통 섹션 I: 듀어스 패밀리 (두 플라이트 동일) ───────────────────────────
DEWARS = [
    ("01", "올트모어 18", "Speyside · Single Malt", "46% ABV",
     "서양배 · 청사과 · 바닐라 · 허브. 피트 없는 깔끔한 스페이사이드. 마스터 블렌더들의 비밀 원액 — 듀어스의 뼈대",
     "Key Malt"),
    ("02", "아버펠디 16", "Highland · Single Malt", "40% ABV",
     "버번 후 올로로소 셰리 캐스크 피니시. 꿀 · 시트러스 · 정향 · 과일케이크 · 다크초콜릿. 01보다 달콤하고 풍성한 하이랜드",
     "Key Malt"),
    ("03", "로얄 브라크라 12", "Highland · Single Malt", "46% ABV",
     "1833년 영국 왕실 칙허 1호 증류소. 올로로소 셰리 피니시. 달콤한 과실 · 견과류 · 다크초콜릿. NCF 내추럴 컬러",
     "Key Malt"),
    ("04", "듀어스 15 · 로얄32 스킨", "Speyside · Blend", "40% ABV",
     "앞 세 원액이 만나 완성되는 블렌드. 각각의 향이 어떻게 하나로 녹아드는지 느껴보세요 — 꿀 · 바닐라 · 부드러운 오크",
     ""),
]

PEATED = [
    ("05", "탈리스커 10", "Isle of Skye · Single Malt", "45.8% ABV",
     "피트 입문의 교과서. 바다 짠맛 · 스모키 피트 · 후추 스파이시 · 달콤한 긴 여운. 2008 세계 최고 위스키 수상", ""),
    ("06", "탈리스커 와일드블루", "Isle of Skye · Limited Edition", "48% ABV",
     "남아프리카 레드 와인 캐스크 16개월 피니시. 건포도 · 무화과 · 스모크. 탈리스커 최초 와인 캐스크 — 같은 DNA, 더 달콤한 변주", ""),
    ("07", "아드벡 10", "Islay · Single Malt", "46% ABV",
     "아일라 피트의 왕. 라임 · 레몬 · 다크초콜릿 · 훈제향 · 요오드. 강렬하지만 의외로 달콤한 피니시", ""),
    ("08", "라프로익 PX", "Islay · Single Malt", "48% ABV",
     "버번 → 쿼터캐스크 → PX 셰리 3단 숙성. 셰리의 강렬한 단맛 위로 은은한 피트. 아일라에서 가장 달콤한 피트", ""),
    ("09", "옥토모어 15.1", "Islay · Bruichladdich · Cask Strength", "59.1% ABV",
     "세계에서 가장 피티한 위스키. 108 PPM. 퍼스트필 + 리차 버번 캐스크. 압도적 스모크 속 캐러멜과 바닐라", "108 PPM"),
    ("10", "합정쉐리 피티드", "Homemade · Finale", "59% ABV",
     "합정동 · 루비포트 시즈닝 오크통 · 산삼 인퓨전. 기원 피티드 원액을 루비포트 시즈닝 오크통에 직접 숙성. "
     "오크통 안에 산삼 한 뿌리가 함께 잠들어 있습니다. 스모키한 피트 위로 포트의 달콤함, "
     "그리고 산삼의 깊고 이국적인 여운 — 세상에 단 하나뿐인 한 잔", "★ Finale"),
]

SHERRY = [
    ("05", "기원 호랑이", "Namyangju · Korean Single Malt", "46% ABV",
     "한국 최초 싱글몰트. 셰리 + 와인 캐스크. 농익은 과일 · 꿀 · 카라멜 · 버터스카치. SF 국제주류품평회 더블골드 수상", ""),
    ("06", "맥켈란 12", "Speyside · Single Malt", "40% ABV",
     "셰리 오크 캐스크의 교과서. 말린 과일 · 오렌지 · 구운 견과류 · 바닐라 · 초콜릿. 부드럽고 균형 잡힌 스페이사이드의 클래식", ""),
    ("07", "부나하벤 12", "Islay · Single Malt · Unpeated", "46.3% ABV",
     "아일라의 이단아 — 피트 없음. 셰리 · 다크초콜릿 · 해초 · 짭조름한 미네랄. 바다를 피트 없이 담아낸 독특한 아일라", ""),
    ("08", "더 글렌드로낙 21 · Parliament", "Highland · Single Malt", "48% ABV",
     "올로로소 + PX 셰리 풀 매추레이션 21년. 블랙베리 · 자두 · 오렌지 · 시나몬. 셰리 세계의 정점 — 깊고 긴 여운", ""),
    ("09", "아벨라워 아브나흐 · CS", "Speyside · Cask Strength", "58–62% ABV",
     "올로로소 셰리 캐스크 스트렝스. 오렌지 · 블랙체리 · 다크초콜릿 · 이국적 향신료. 원액 그대로 — 물 몇 방울 권장", ""),
    ("10", "합정쉐리", "Homemade · Finale", "?? % ABV",
     "합정동 · 직접 숙성 · 단 한 오크통. 오늘 자리의 주인이 직접 오크통에 숙성시킨 세상에 단 하나뿐인 위스키. "
     "스코틀랜드의 거장들을 따라온 여정의 끝, 합정에서 완성됩니다", "★ Finale"),
]

FLIGHTS = [
    {
        "id": "peated", "label": "🔥 PEATED", "tag": "II — PEATED",
        "blurb": "피트(이탄) 스모키 계열. 입문용 탈리스커에서 108 PPM 옥토모어까지, 그리고 산삼 인퓨전 피티드 피날레.",
        "pdf": "menu_peated.pdf", "items2": PEATED,
    },
    {
        "id": "sherry", "label": "🍷 SHERRY & FRUIT", "tag": "II — SHERRY & FRUIT",
        "blurb": "셰리 · 과실 계열. 한국 싱글몰트 기원부터 글렌드로낙 21년 셰리의 정점, 직접 숙성한 합정쉐리 피날레.",
        "pdf": "menu_sherry.pdf", "items2": SHERRY,
    },
]

NOTE = "고도수(55%+) 제품은 소량의 물을 더하면 풍미가 열립니다 · 다음 잔 전 입 안을 물로 헹궈주세요 · 각 20 ml"

# ── 행사(이벤트) — 날짜별 페이지. 메뉴가 바뀌면 새 dict 를 추가한다(최신=마지막). ──
EVENTS = [
    {
        "slug": "260604",
        "date": "2026-06-04",
        "title": "피티드 & 셰리 테이스팅",
        "venue": VENUE,
        "dewars": DEWARS,
        "flights": FLIGHTS,
        "note": NOTE,
    },
]

_WD = ["월", "화", "수", "목", "금", "토", "일"]


def _date_label(iso: str) -> str:
    d = datetime.date.fromisoformat(iso)
    return f"{d.year}.{d.month:02d}.{d.day:02d} ({_WD[d.weekday()]})"


# ── 간략 약도(SVG) — 양화로(합정↔홍대) 메인도로 + 4지점 ────────────────────────
# 보드 요청: 메인도로는 합정-홍대 길(양화로). 합정역·홍대입구·합정역 3번 출구·회사 표시.
# 실측 지오: 합정→홍대 bearing 57°(1.3km)=양화로 축. 회사(제이원빌딩)는 합정에서
# bearing 68°·446m → 양화로보다 약간 남(우)·홍대 방향 약 1/3 지점. 3번 출구는 양화로변.
VENUE_MAP_SVG = """<svg class="map" viewBox="0 0 600 360" role="img"
 aria-label="양화로(합정역↔홍대입구) 약도: 합정역 3번 출구에서 두다지 회사(제이원빌딩)까지" xmlns="http://www.w3.org/2000/svg">
  <rect width="600" height="360" fill="#10141c"/>
  <!-- 방위 -->
  <g transform="translate(46,48)">
    <line x1="0" y1="15" x2="0" y2="-12" stroke="#9aa0aa" stroke-width="2"/>
    <polygon points="0,-20 -5,-9 5,-9" fill="#9aa0aa"/>
    <text x="0" y="33" fill="#9aa0aa" font-size="13" text-anchor="middle">N</text>
  </g>
  <!-- 양화로 = 합정↔홍대 메인도로 -->
  <path d="M55 300 Q300 200 552 100" stroke="#39414e" stroke-width="28" fill="none" stroke-linecap="round"/>
  <path d="M55 300 Q300 200 552 100" stroke="#5b6675" stroke-width="2.5" stroke-dasharray="13 13" fill="none"/>
  <text x="402" y="138" fill="#aeb6c2" font-size="15" font-weight="700" text-anchor="middle"
   transform="rotate(-21 402 138)">양화로</text>
  <text x="402" y="156" fill="#7c8492" font-size="11" text-anchor="middle"
   transform="rotate(-21 402 156)">합정 ↔ 홍대 메인도로</text>
  <!-- 도보 경로: 3번 출구 → 회사 -->
  <path d="M166 258 Q232 286 298 260" stroke="#7fd1b9" stroke-width="3.5"
   stroke-dasharray="2 10" stroke-linecap="round" fill="none"/>
  <text x="214" y="302" fill="#7fd1b9" font-size="13" font-weight="600" text-anchor="middle">도보 약 5분 · 450m</text>
  <!-- 합정역 -->
  <g transform="translate(104,278)">
    <circle r="22" fill="#10141c" stroke="#2db400" stroke-width="5"/>
    <text x="0" y="7" fill="#2db400" font-size="19" font-weight="800" text-anchor="middle">M</text>
    <text x="0" y="49" fill="#e8eaed" font-size="15" font-weight="700" text-anchor="middle">합정역</text>
    <text x="0" y="67" fill="#9aa0aa" font-size="11" text-anchor="middle">2 · 6호선</text>
  </g>
  <!-- 홍대입구역 -->
  <g transform="translate(524,108)">
    <circle r="22" fill="#10141c" stroke="#2db400" stroke-width="5"/>
    <text x="0" y="7" fill="#2db400" font-size="19" font-weight="800" text-anchor="middle">M</text>
    <text x="0" y="49" fill="#e8eaed" font-size="15" font-weight="700" text-anchor="middle">홍대입구역</text>
    <text x="0" y="67" fill="#9aa0aa" font-size="11" text-anchor="middle">홍대 방면</text>
  </g>
  <!-- 3번 출구 -->
  <g transform="translate(165,255)">
    <rect x="-19" y="-16" width="38" height="32" rx="7" fill="#e0a84e"/>
    <text x="0" y="7" fill="#1a1205" font-size="17" font-weight="800" text-anchor="middle">3</text>
    <text x="0" y="-24" fill="#e0a84e" font-size="12" font-weight="700" text-anchor="middle">3번 출구</text>
  </g>
  <!-- 회사 핀 (라벨은 오른쪽 빈 공간으로) -->
  <g transform="translate(300,258)">
    <path d="M0 6 C -15 -13 -15 -30 0 -38 C 15 -30 15 -13 0 6 Z" fill="#e0584e" stroke="#fff" stroke-width="1.6"/>
    <circle cx="0" cy="-24" r="6" fill="#fff"/>
    <text x="14" y="-13" fill="#e8eaed" font-size="15" font-weight="700">두다지 (회사)</text>
    <text x="14" y="4" fill="#9aa0aa" font-size="12">제이원빌딩 1층</text>
  </g>
</svg>"""


def _card(item: tuple[str, str, str, str, str, str]) -> str:
    no, name, meta, abv, notes, badge = item
    e = html.escape
    finale = " finale" if "Finale" in badge else ""
    badge_html = f'<span class="badge">{e(badge)}</span>' if badge else ""
    return f"""<div class="card{finale}">
  <div class="chead">
    <span class="cno">{e(no)}</span>
    <span class="cname">{e(name)} {badge_html}</span>
    <span class="cabv">{e(abv)}</span>
  </div>
  <div class="cmeta">{e(meta)}</div>
  <div class="cnotes">{e(notes)}</div>
</div>"""


def _flight_section(flight: dict) -> str:
    """PART 2 — 취향별 플라이트(공통 듀어스 섹션은 위에 한 번만 표시)."""
    cards_ii = "\n".join(_card(x) for x in flight["items2"])
    active = " active" if flight["id"] == "peated" else ""
    return f"""<section class="flight{active}" id="flight-{flight['id']}">
  <p class="blurb">{html.escape(flight['blurb'])}</p>
  {cards_ii}
</section>"""


PAGE_CSS = """*{box-sizing:border-box}
body{margin:0;background:#0f1115;color:#e8eaed;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif;
 line-height:1.55;font-size:16px;-webkit-text-size-adjust:100%}
.wrap{max-width:680px;margin:0 auto;padding:28px 18px 72px}
header{text-align:center;margin-bottom:18px}
.kicker{letter-spacing:.28em;font-size:.72rem;color:#9aa0aa;text-transform:uppercase}
h1{font-size:1.7rem;margin:.25em 0 .1em;color:#e8eaed}
h1 .gold{color:#e0a84e}
.sub{color:#9aa0aa;font-size:.92rem;margin:.2em 0}
.flight-line{display:inline-block;margin-top:.5em;padding:.25em .8em;border:1px solid #2a2e37;border-radius:999px;
 color:#cfd3da;font-size:.82rem}
.tabs{position:sticky;top:0;z-index:5;display:flex;gap:8px;margin:8px 0 14px;
 padding:10px 0 12px;background:#0f1115;box-shadow:0 8px 12px -8px #0f1115}
.tab{flex:1;padding:11px 8px;border:1px solid #2a2e37;background:#161922;color:#cfd3da;
 border-radius:12px;font-size:.95rem;font-weight:600;cursor:pointer}
.tab.active{background:#e0a84e;color:#1a1205;border-color:#e0a84e}
.flight{display:none}
.flight.active{display:block}
.blurb{color:#b6bcc6;font-size:.9rem;background:#141821;border-left:3px solid #e0a84e;
 padding:10px 13px;border-radius:0 8px 8px 0;margin:0 0 18px}
.sec{color:#e0a84e;font-size:1.05rem;letter-spacing:.04em;margin:1.5em 0 .2em;
 border-bottom:1px solid #2a2e37;padding-bottom:.3em;scroll-margin-top:6px}
.sec .seng{color:#8a909a;font-size:.76rem;font-weight:500;letter-spacing:.04em}
.sechint{color:#8a909a;font-size:.82rem;margin:.1em 0 1em}
.howto{background:#141821;border:1px solid #2a2e37;border-radius:14px;padding:15px 16px;margin:8px 0 6px}
.howto .ht-title{color:#e0a84e;font-weight:700;font-size:.98rem;margin-bottom:.5em}
.howto p{margin:.45em 0;color:#cdd2da;font-size:.92rem}
.howto ol{margin:.6em 0;padding-left:1.3em}
.howto li{margin:.6em 0;color:#cdd2da;font-size:.92rem;line-height:1.6}
.howto b{color:#f0d9a8}
.howto .ht-hint{color:#7fd1b9;font-weight:600;margin-top:.7em}
.card{background:#141821;border:1px solid #20242e;border-radius:14px;padding:14px 15px;margin:10px 0}
.card.finale{border-color:#e0a84e;background:#1a1812;box-shadow:0 0 0 1px #e0a84e33}
.chead{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.cno{color:#6b7280;font-variant-numeric:tabular-nums;font-weight:700;font-size:.9rem;min-width:1.6em}
.cname{font-weight:700;font-size:1.05rem;flex:1 1 60%}
.cabv{color:#e0a84e;font-size:.85rem;font-weight:600;white-space:nowrap;font-variant-numeric:tabular-nums}
.badge{display:inline-block;font-size:.66rem;font-weight:700;letter-spacing:.04em;color:#1a1205;
 background:#e0a84e;border-radius:6px;padding:1px 7px;vertical-align:middle}
.cmeta{color:#9aa0aa;font-size:.82rem;margin:.25em 0 .5em}
.cnotes{color:#cdd2da;font-size:.9rem}
.seclabel{color:#e0a84e;font-size:.72rem;letter-spacing:.22em;text-transform:uppercase;
 text-align:center;margin:34px 0 2px}
.venue{background:#141821;border:1px solid #20242e;border-radius:16px;overflow:hidden;margin:8px 0 4px}
.venue .map{width:100%;height:auto;display:block;background:#10141c}
.venue .vbody{padding:15px 16px 17px}
.vname{font-size:1.2rem;font-weight:700}
.varea{color:#e0a84e;font-size:.82rem;margin:.15em 0 .5em}
.vaddr{color:#b6bcc6;font-size:.9rem}
.vbtns{display:flex;gap:8px;margin-top:13px}
.btn{flex:1;text-align:center;padding:12px;border-radius:11px;text-decoration:none;font-weight:600;font-size:.92rem}
.btn.primary{background:#03c75a;color:#06210f}
.btn.ghost{border:1px solid #2a2e37;color:#cfd3da}
.btn:active{opacity:.85}
.note{margin:26px 0 0;color:#8a909a;font-size:.8rem;text-align:center;line-height:1.7}
footer{margin-top:30px;text-align:center;color:#5b616b;font-size:.75rem}"""


def render_event(ev: dict) -> str:
    venue = ev["venue"]
    flights = ev["flights"]
    common_html = "\n".join(_card(x) for x in ev["dewars"])
    flights_html = "\n".join(_flight_section(f) for f in flights)
    tabs = "\n".join(
        f'<button class="tab{" active" if i == 0 else ""}" data-target="flight-{f["id"]}">{html.escape(f["label"])}</button>'
        for i, f in enumerate(flights)
    )
    e = html.escape
    date_label = _date_label(ev["date"])
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Whisky Tasting · {e(date_label)}</title>
<meta name="description" content="{e(EVENT_PLACE)} 위스키 테이스팅 {e(date_label)} — 20 ml × 10 드램, 피티드 & 셰리">
<style>
{PAGE_CSS}
</style>
</head>
<body><div class="wrap">
<header>
  <div class="kicker">Whisky Night · {e(EVENT_PLACE)}</div>
  <h1>The <span class="gold">Collection</span></h1>
  <p class="sub">{e(date_label)} · {e(venue['area'])} · {e(venue['name'])}</p>
  <span class="flight-line">20 ml × 10 Drams</span>
</header>

<div class="seclabel">장소 · Venue</div>
<div class="venue">
  {VENUE_MAP_SVG}
  <div class="vbody">
    <div class="vname">{e(venue['name'])}</div>
    <div class="varea">{e(venue['area'])}</div>
    <div class="vaddr">{e(venue['addr'])}</div>
    <div class="vbtns">
      <a class="btn primary" href="{e(venue['naver'])}" target="_blank" rel="noopener">📍 네이버 지도</a>
      <a class="btn ghost" href="#menu">메뉴 보기 ↓</a>
    </div>
  </div>
</div>

<div class="seclabel" id="menu">메뉴 · Tasting Menu</div>

<div class="howto">
  <div class="ht-title">🥃 오늘의 테이스팅 안내</div>
  <p>오늘 시음은 <b>두 파트</b>로 진행됩니다.</p>
  <ol>
    <li><b>다 함께 — 듀어스 키몰트 &amp; 듀어스</b><br>
      먼저 모두 같이 듀어스의 키몰트 3종과 그것이 어우러진 블렌드 ‘듀어스’를 차례로 음미합니다.
      원액에서 블렌드로 이어지는 여정을 함께 느껴봐요.</li>
    <li><b>취향대로 — 피트 or 셰리</b><br>
      이후엔 입맛 따라 나뉩니다. <b>스모키한 피트</b>가 좋으시면 🔥 피티드,
      <b>달콤한 셰리·과실</b>이 좋으시면 🍷 셰리 플라이트로 이어집니다.</li>
  </ol>
  <p class="ht-hint">아래 PART 1을 먼저 보시고, PART 2에서 원하시는 탭을 선택하세요 👇</p>
</div>

<h3 class="sec">PART 1 · 다 함께 <span class="seng">Dewar's Family</span></h3>
<p class="sechint">올트모어 → 아버펠디 → 로얄 브라크라 → 듀어스 : 원액에서 블렌드로 거슬러 올라가는 여정</p>
{common_html}

<h3 class="sec" id="part2">PART 2 · 취향대로 <span class="seng">Choose Your Path</span></h3>
<div class="tabs">
{tabs}
</div>

{flights_html}

<p class="note">{e(ev['note'])}</p>

<footer>{e(date_label)} · Tasting Flight 10 Drams &nbsp;·&nbsp; 즐거운 한 잔 되세요 🥃</footer>
</div>
<script>
document.querySelectorAll('.tab').forEach(function(t){{
  t.addEventListener('click',function(){{
    document.querySelectorAll('.tab').forEach(function(x){{x.classList.remove('active')}});
    document.querySelectorAll('.flight').forEach(function(x){{x.classList.remove('active')}});
    t.classList.add('active');
    document.getElementById(t.dataset.target).classList.add('active');
    var p2=document.getElementById('part2');
    if(p2) p2.scrollIntoView({{behavior:'smooth',block:'start'}});
  }});
}});
</script>
</body>
</html>
"""


def build_events() -> list[Path]:
    out = []
    for ev in EVENTS:
        d = MENU_DIR / ev["slug"]
        d.mkdir(parents=True, exist_ok=True)
        p = d / "index.html"
        p.write_text(render_event(ev), encoding="utf-8")
        out.append(p)
    return out


def build_hub() -> Path:
    """/menu/ 허브 — 최신 행사로 자동 이동 + 행사 목록 폴백."""
    latest = EVENTS[-1]
    items = "\n".join(
        f'<li><a href="{e["slug"]}/">{_date_label(e["date"])} · {html.escape(e["title"])}</a></li>'
        for e in reversed(EVENTS)
    )
    doc = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="0; url={latest['slug']}/">
<title>위스키 모임 · {html.escape(EVENT_PLACE)}</title>
<style>
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
 background:#0f1115;color:#e8eaed;font-family:-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}}
.box{{text-align:center;padding:30px 24px;max-width:460px}}
h1{{color:#e0a84e;font-size:1.3rem;margin:0 0 .4em}}
.msg{{color:#9aa0aa;font-size:.92rem}}
ul{{list-style:none;padding:0;margin:18px 0 0}}
li{{margin:8px 0}}
a{{color:#7fd1b9;text-decoration:none;font-weight:600}}
</style></head>
<body><div class="box">
<h1>🥃 위스키 모임</h1>
<p class="msg">최신 행사 페이지로 이동합니다…</p>
<ul>
{items}
</ul>
</div>
<script>location.replace("{latest['slug']}/");</script>
</body></html>
"""
    out = MENU_DIR / "index.html"
    out.write_text(doc, encoding="utf-8")
    return out


def _qr_print_html(url: str, caption: str) -> str:
    e = html.escape
    return f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>위스키 모임 · QR</title>
<style>
@media print{{body{{background:#fff}}}}
body{{margin:0;min-height:100vh;display:flex;align-items:center;justify-content:center;
 background:#0f1115;color:#1a1205;font-family:-apple-system,"Apple SD Gothic Neo","Malgun Gothic",sans-serif}}
.card{{background:#fff;border-radius:24px;padding:40px 44px;text-align:center;max-width:380px;
 box-shadow:0 20px 60px #0008}}
.kick{{letter-spacing:.26em;font-size:.72rem;color:#9a7b3a;text-transform:uppercase}}
h1{{margin:.2em 0 .1em;font-size:1.6rem}}
.h1 .g{{color:#c8902f}}
.sub{{color:#6b6256;font-size:.9rem;margin:0 0 18px}}
img{{width:260px;height:260px}}
.scan{{margin-top:14px;font-weight:700;color:#c8902f;letter-spacing:.04em}}
.url{{margin-top:6px;color:#9a9488;font-size:.72rem;word-break:break-all}}
</style></head>
<body><div class="card">
<div class="kick">Whisky Tasting · {e(EVENT_PLACE)}</div>
<h1 class="h1">The <span class="g">Collection</span></h1>
<p class="sub">{e(caption)}</p>
<img src="qr.svg" alt="QR 코드">
<div class="scan">📷 카메라로 스캔하세요</div>
<div class="url">{e(url)}</div>
</div></body></html>
"""


def _write_qr(url: str, outdir: Path, caption: str) -> list[Path]:
    outdir.mkdir(parents=True, exist_ok=True)
    qr = segno.make(url, error="m")
    svg, png = outdir / "qr.svg", outdir / "qr.png"
    qr.save(str(svg), scale=10, dark="#1a1205", light="#ffffff", border=4)
    qr.save(str(png), scale=12, dark="#1a1205", light="#ffffff", border=4)
    qhtml = outdir / "qr.html"
    qhtml.write_text(_qr_print_html(url, caption), encoding="utf-8")
    return [svg, png, qhtml]


def build_qr() -> list[Path]:
    # 메인 QR: /menu/ → 항상 최신 행사로 연결(기존 인쇄물 그대로 유효).
    paths = _write_qr(MENU_URL, MENU_DIR, "20 ml × 10 Drams · 피티드 & 셰리")
    # 행사별 영구 QR.
    for ev in EVENTS:
        url = f"{SITE_ROOT}/menu/{ev['slug']}/"
        paths += _write_qr(url, MENU_DIR / ev["slug"], f"{_date_label(ev['date'])} · {ev['title']}")
    return paths


if __name__ == "__main__":
    evs = build_events()
    hub = build_hub()
    qrs = build_qr()
    print(f"events built — {len(evs)} · hub + {len(qrs)} qr files")
    for p in evs:
        print(f"  event: {p.relative_to(ROOT)}")
    print(f"  hub:   {hub.relative_to(ROOT)}  → 최신 {EVENTS[-1]['slug']}/")
    print(f"  main QR → {MENU_URL}")
