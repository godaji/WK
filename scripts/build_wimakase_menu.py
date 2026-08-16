#!/usr/bin/env python3
"""Build the "합정 위마카세" whisky bar menu page (self-contained, mobile-first).

CMPA-1283 (보드 요청 CMPA-1282): 위스키 바 3티어 메뉴 페이지. 메뉴가 종종 갱신되므로
버전 라벨(v2026.08.16)을 페이지에 노출한다.

산출물(둘 다 같은 HTML — 재생성 결정론적):
- blog-md/wimakase.html            : CaskCode Pages(godaji/CaskCode) 소스 미러
- deploy/menu/wimakase/index.html  : 메뉴 배포 산출물 위치

CLAUDE.md 준수:
- 모바일 우선(≈360px): 4컬럼 표 대신 카드형(제품명+ABV 헤더 / 분류 / 비고)으로 렌더 —
  좁은 화면에서 글이 잘리지 않는다.
- 카피 톤 담백하게. 독자용 저자 필명은 CaskCode(내부 호칭 "보드" 노출 금지).
- 버전 v2026.08.16 을 헤더·푸터에 명확히 노출.

메뉴 정본 = CMPA-1282 본문 마크다운. 갱신 시 아래 TIERS 데이터 + VERSION 을 고친다.
"""
from __future__ import annotations

import html
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

VERSION = "v2026.08.16"
TITLE = "합정 위마카세"

# ── 운영 프로그램 (The Night's Journey) ──────────────────────────────────────
PROGRAM = {
    "course": "1티어 5잔(각 20ml) + 2티어 5잔(각 20ml) 테이스팅 후, 3티어 프리플로우(무제한) 제공",
    "volume": "총 테이스팅 용량 200ml (프리플로우 제외)",
}

# ── 3티어 메뉴 데이터 ─────────────────────────────────────────────────────────
# 각 항목: (제품명, 분류, 도수 ABV, 비고 특징)
TIERS = [
    {
        "id": "tier1",
        "medal": "🥇",
        "name": "Tier 1 · The Masterpieces",
        "sub": "하이엔드 & 한정판",
        "serve": "바텐더 추천 또는 고객 선택으로 5잔(각 20ml) 제공",
        "items": [
            ("글렌드로낙 21년", "싱글 몰트 스카치", "48%", "고숙성 셰리 캐스크의 대표 주자"),
            ("글렌피딕 18년", "싱글 몰트 스카치", "48%", "고숙성 및 48도 특별 에디션"),
            ("글렌리벳 19년", "싱글 몰트 스카치", "48%", "정규 라인을 벗어난 고숙성/고도수 바틀"),
            ("올트모어 18년", "싱글 몰트 스카치", "46%", "깔끔하고 우아한 고숙성 스페이사이드 몰트"),
            ("아벨라워 아브나흐", "싱글 몰트 스카치", "61%", "꾸덕한 셰리 폭탄, 강력한 타격감의 CS"),
            ("옥토모어 15.1", "싱글 몰트 스카치", "59.1%",
             "108.2 PPM의 세계 최고 수준의 강력한 피트 수치, 압도적인 스모키함"),
            ("스테그 (Stagg)", "버번 위스키", "63~65%", "구하기 매우 힘든 프리미엄 CS 버번"),
            ("일라이저 크레이그 18년", "버번 위스키", "45%", "초고숙성 버번, 높은 희소성"),
            ("카발란 올로로소", "타이완 싱글 몰트", "55%", "대만 특유의 진한 열대 숙성 셰리 (CS)"),
            ("야마자키 12년", "재패니즈 싱글 몰트", "43%", "전 세계적인 품귀 현상, 높은 프리미엄"),
            ("기원 타이거 (Tiger)", "코리안 싱글 몰트", "46%", "쓰리소사이어티스 한정판, 수집 가치 높음"),
        ],
    },
    {
        "id": "tier2",
        "medal": "🥈",
        "name": "Tier 2 · The Enthusiasts",
        "sub": "고도수 & 매니아픽",
        "serve": "바텐더 추천 또는 고객 선택으로 5잔(각 20ml) 제공",
        "items": [
            ("발베니 12년 더블우드", "싱글 몰트 스카치", "40%", "화사하고 달달한 꿀/바닐라 풍미의 정석"),
            ("글렌알라키 15년", "싱글 몰트 스카치", "46%", "진득한 셰리 풍미로 최근 가장 인기 있는 바틀"),
            ("매캘란 더블우드 12년", "싱글 몰트 스카치", "40%", "싱글 몰트의 절대 강자, 훌륭한 밸런스"),
            ("글렌드로낙 12년", "싱글 몰트 스카치", "43%", "입문~중급용 셰리 캐스크의 교과서"),
            ("에버펠디 16년", "싱글 몰트 스카치", "40%", "부드럽고 꿀 같은 달콤함"),
            ("로얄 브라크라 12년", "싱글 몰트 스카치", "46%", "올로로소 셰리 피니시, 고급스럽고 우아한 맛"),
            ("부나하벤 12년", "싱글 몰트 스카치", "46.3%", "논칠필터, 훌륭한 바디감의 아일라 몰트"),
            ("조니워커 그린", "블렌디드 몰트", "43%", "가성비와 퀄리티를 모두 잡은 15년 숙성 블렌딩"),
            ("러셀 리저브 싱글배럴", "버번 위스키", "55%", "버번 매니아들의 열렬한 지지를 받는 훌륭한 바틀"),
            ("이글레어 10년", "버번 위스키", "45%", "버팔로트레이스 증류소의 프리미엄 라인"),
            ("와일드터키 레어브리드 라이", "라이 위스키", "56.1%", "타격감과 풍미가 일품인 배럴 프루프 라이"),
            ("사가모어 라이 CS", "라이 위스키", "56%", "CS 특유의 강렬한 타격감과 진한 화사함"),
            ("탈리스커 10년", "싱글 몰트 스카치", "45.8%", "바다향과 후추향이 일품인 대표 피트 위스키"),
            ("아드벡 10년", "싱글 몰트 스카치", "46%", "스모키하고 강렬한 아일라 피트 위스키"),
            ("라프로익 쿼터 캐스크", "싱글 몰트 스카치", "48%", "작은 오크통 숙성으로 강렬하게 농축된 나무/피트 향"),
            ("스카라버스 CS 피티드", "싱글 몰트 스카치", "57%", "강력한 도수의 가성비 아일라 피트"),
            ("폴존 피티드 CS", "인디안 싱글 몰트", "55.5%", "열대 기후 숙성 특유의 진한 피트와 자극"),
        ],
    },
    {
        "id": "tier3",
        "medal": "🥉",
        "name": "Tier 3 · The Endless Night",
        "sub": "프리플로우 · 무제한",
        "serve": "1, 2티어 코스 완료 후 니트, 온더락, 하이볼 등으로 무제한 제공",
        "items": [
            ("엔젤스 엔비 스몰배치", "버번 위스키", "50%", "포트 캐스크 피니시의 달콤함과 스몰배치의 타격감"),
            ("놉크릭 9년", "버번 위스키", "50%", "짐빔 가문 스몰배치, 묵직하고 진한 땅콩/견과류 풍미"),
            ("일라이저 크레이그 스몰배치", "버번 위스키", "47%", "우디함과 바닐라의 정석적인 밸런스"),
            ("LOT 40", "캐네디언 라이", "43%", "호밀빵, 허브 등 라이 특유의 화사함"),
            ("몽키숄더", "블렌디드 몰트", "40%", "달콤하고 부드러워 하이볼 및 입문용으로 최적"),
            ("닛카 프론티어", "재패니즈 블렌디드", "48%", "요이치 몰트 베이스, 피트감과 48도의 탄탄한 하이볼 기주"),
            ("제임슨", "아이리시 위스키", "40%", "깔끔한 맛, 전 세계에서 가장 대중적인 아이리시"),
        ],
    },
]

PAGE_CSS = """*{box-sizing:border-box}
body{margin:0;background:#0f1115;color:#e8eaed;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif;
 line-height:1.55;font-size:16px;-webkit-text-size-adjust:100%}
.wrap{max-width:680px;margin:0 auto;padding:28px 18px 72px}
header{text-align:center;margin-bottom:16px}
.kicker{letter-spacing:.28em;font-size:.72rem;color:#9aa0aa;text-transform:uppercase}
h1{font-size:1.85rem;margin:.25em 0 .12em;color:#e8eaed}
h1 .gold{color:#e0a84e}
.ver{display:inline-block;margin-top:.5em;padding:.24em .8em;border:1px solid #2a2e37;border-radius:999px;
 color:#e0a84e;font-size:.8rem;font-weight:600;letter-spacing:.04em}
.sub{color:#9aa0aa;font-size:.9rem;margin:.35em 0 0}
.program{background:#141821;border:1px solid #2a2e37;border-radius:14px;padding:15px 16px;margin:18px 0 8px}
.program .pt{color:#e0a84e;font-weight:700;font-size:.98rem;margin-bottom:.55em}
.program p{margin:.4em 0;color:#cdd2da;font-size:.9rem}
.program .vol{color:#7fd1b9;font-weight:600;margin-top:.5em;font-size:.9rem}
.tier{margin-top:30px;scroll-margin-top:8px}
.thead{border-bottom:1px solid #2a2e37;padding-bottom:.5em;margin-bottom:12px}
.tname{color:#e0a84e;font-size:1.18rem;font-weight:700}
.tsub{color:#9aa0aa;font-size:.82rem;margin-top:.15em}
.tserve{color:#b6bcc6;font-size:.82rem;margin-top:.5em;background:#141821;border-left:3px solid #e0a84e;
 padding:8px 12px;border-radius:0 8px 8px 0}
.tcount{color:#6b7280;font-size:.78rem;font-weight:600}
.card{background:#141821;border:1px solid #20242e;border-radius:14px;padding:13px 15px;margin:9px 0}
.chead{display:flex;align-items:baseline;gap:8px;flex-wrap:wrap}
.cname{font-weight:700;font-size:1.05rem;flex:1 1 60%;min-width:0}
.cabv{color:#e0a84e;font-size:.85rem;font-weight:700;white-space:nowrap;font-variant-numeric:tabular-nums}
.cmeta{color:#9aa0aa;font-size:.8rem;margin:.28em 0 .45em}
.cnotes{color:#cdd2da;font-size:.9rem}
.note{margin:30px 0 0;color:#8a909a;font-size:.8rem;text-align:center;line-height:1.7}
footer{margin-top:26px;text-align:center;color:#5b616b;font-size:.75rem;line-height:1.7}"""


def _card(item: tuple[str, str, str, str]) -> str:
    name, cat, abv, notes = item
    e = html.escape
    return f"""<div class="card">
  <div class="chead">
    <span class="cname">{e(name)}</span>
    <span class="cabv">{e(abv)} ABV</span>
  </div>
  <div class="cmeta">{e(cat)}</div>
  <div class="cnotes">{e(notes)}</div>
</div>"""


def _tier_section(tier: dict) -> str:
    e = html.escape
    cards = "\n".join(_card(x) for x in tier["items"])
    n = len(tier["items"])
    return f"""<section class="tier" id="{e(tier['id'])}">
  <div class="thead">
    <div class="tname">{e(tier['medal'])} {e(tier['name'])} <span class="tcount">· {n}종</span></div>
    <div class="tsub">{e(tier['sub'])}</div>
    <div class="tserve">제공 방식 — {e(tier['serve'])}</div>
  </div>
  {cards}
</section>"""


def render() -> str:
    e = html.escape
    tiers_html = "\n".join(_tier_section(t) for t in TIERS)
    total = sum(len(t["items"]) for t in TIERS)
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>{e(TITLE)} · 위스키 메뉴 {e(VERSION)}</title>
<meta name="description" content="{e(TITLE)} 위스키 바 메뉴 — 3티어 {total}종. 1·2티어 테이스팅 200ml + 3티어 프리플로우. {e(VERSION)}">
<style>
{PAGE_CSS}
</style>
</head>
<body><div class="wrap">
<header>
  <div class="kicker">Whisky Bar · 합정</div>
  <h1>합정 <span class="gold">위마카세</span></h1>
  <div class="ver">MENU {e(VERSION)}</div>
  <p class="sub">3티어 위스키 테이스팅 · 총 {total}종</p>
</header>

<div class="program">
  <div class="pt">🥃 운영 프로그램 · The Night's Journey</div>
  <p>{e(PROGRAM['course'])}</p>
  <p class="vol">{e(PROGRAM['volume'])}</p>
</div>

{tiers_html}

<p class="note">고도수(55%+) 제품은 소량의 물을 더하면 풍미가 열립니다 · 다음 잔 전 입 안을 물로 헹궈주세요 · 테이스팅 각 20 ml</p>

<footer>합정 위마카세 · 메뉴 {e(VERSION)} &nbsp;·&nbsp; CaskCode<br>메뉴는 수시로 업데이트됩니다 — 버전을 확인하세요 🥃</footer>
</div>
</body>
</html>
"""


def build() -> list[Path]:
    doc = render()
    outs = [
        ROOT / "blog-md" / "wimakase.html",
        ROOT / "deploy" / "menu" / "wimakase" / "index.html",
    ]
    written = []
    for p in outs:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(doc, encoding="utf-8")
        written.append(p)
    return written


if __name__ == "__main__":
    paths = build()
    total = sum(len(t["items"]) for t in TIERS)
    print(f"built 합정 위마카세 {VERSION} — {total}종 ({', '.join(str(len(t['items'])) for t in TIERS)})")
    for p in paths:
        print(f"  {p.relative_to(ROOT)}")
