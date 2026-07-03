# -*- coding: utf-8 -*-
"""
콜키지프리 카드 카테고리 아이콘 (CMPA-101) — 제안/POC 단계.

CMPA-87 에서 외부 소스(다이닝코드) 대표사진을 IP/브랜딩 위험으로 제거하면서
카드 상단 사진 밴드(.photo, 150px)가 빈 회색으로 남았다. 이 모듈은 그 자리를
**우리가 직접 그린 인라인 SVG 일러스트**로 채운다.

설계 원칙(제안):
- 100% 자체 제작 SVG → 저작권/귀속/share-alike 의무 없음(상업 이용 무제한).
- 인라인(외부 요청 없음) → 오프라인 동작, egress 0, 프라이버시 우려 0, 바이트 작음.
- 결정론적 매핑(classify_major 와 동일 철학) → 재크롤 없이 backfill 가능.
- 한국 음식 고유(족발·곱창·막창 등)은 이모지/공개 아이콘셋에 글리프가 없어
  자체 SVG 만이 식별 가능하게 표현 가능 → 보드가 예로 든 케이스를 정확히 충족.

해상도 매칭 순서:
  1) 원문 카테고리 fine 키워드(족발/곱창/회/초밥/스테이크…) — 구체적 우선
  2) 대분류(7버킷) 폴백
  3) 범용 접시 아이콘(최종 폴백)
"""
from __future__ import annotations

# ── 카테고리 색조(밴드 배경 그라데이션). 7 대분류 + 보조 ──────────────
TINTS = {
    "meat":    ("#fde8e8", "#f7caca"),
    "gopchang":("#fbe4d8", "#f3c3a6"),
    "jokbal":  ("#f7e6dd", "#e9c3a8"),
    "hoe":     ("#e6f3fb", "#bfe0f2"),
    "sushi":   ("#fdeee2", "#f6d2b3"),
    "eel":     ("#efe9df", "#d9cab0"),
    "steak":   ("#f0e6df", "#d9c1ad"),
    "western": ("#fdf3e0", "#f3dca6"),
    "hotpot":  ("#fce6e1", "#f3bcae"),
    "soup":    ("#eef1f4", "#cdd6df"),
    "noodle":  ("#fdf6e3", "#ecdca8"),
    "chicken": ("#fdf0db", "#f2d79b"),
    "wine":    ("#f3e6ee", "#dcb9cf"),
    "beer":    ("#fdf6df", "#f0dd9b"),
    "whisky":  ("#f6ecdd", "#e4c79a"),
    "plate":   ("#eef0f2", "#d6dbe0"),
}

# ── 인라인 SVG 일러스트(자체 제작, 64x64 viewBox, 평면 스타일) ────────
# 단순/식별성 우선. 색은 음식 자연색에 가깝게.
def _svg(body: str) -> str:
    return (
        "<svg viewBox='0 0 64 64' width='62' height='62' "
        "xmlns='http://www.w3.org/2000/svg' aria-hidden='true'>" + body + "</svg>"
    )

ICONS = {
    # 고기(삼겹살/구이) — 그릴 위 고기 슬라이스
    "meat": _svg(
        "<rect x='10' y='40' width='44' height='6' rx='3' fill='#8a8f98'/>"
        "<line x1='16' y1='40' x2='16' y2='46' stroke='#5f636b' stroke-width='2'/>"
        "<line x1='32' y1='40' x2='32' y2='46' stroke='#5f636b' stroke-width='2'/>"
        "<line x1='48' y1='40' x2='48' y2='46' stroke='#5f636b' stroke-width='2'/>"
        "<rect x='14' y='22' width='16' height='12' rx='4' fill='#e8806f' stroke='#c85a47' stroke-width='2'/>"
        "<rect x='34' y='26' width='16' height='12' rx='4' fill='#f0a08f' stroke='#c85a47' stroke-width='2'/>"
        "<rect x='17' y='25' width='10' height='3' rx='1.5' fill='#fbe3dc'/>"
    ),
    # 곱창 — 둘둘 말린 관 모양
    "gopchang": _svg(
        "<path d='M20 44c-8 0-10-12-2-14 6-1.5 8 6 3 7' fill='none' stroke='#d98c5f' stroke-width='5' stroke-linecap='round'/>"
        "<path d='M30 46c-7 2-12-8-5-13 7-5 14 3 9 9' fill='none' stroke='#e29a6c' stroke-width='5' stroke-linecap='round'/>"
        "<path d='M44 44c8-2 8-16-2-16-7 0-8 8-2 9' fill='none' stroke='#d98c5f' stroke-width='5' stroke-linecap='round'/>"
        "<rect x='12' y='48' width='40' height='5' rx='2.5' fill='#8a8f98'/>"
    ),
    # 족발 — 통족발 실루엣 + 뼈
    "jokbal": _svg(
        "<path d='M18 26c6-8 22-8 30 2 5 6 4 16-4 20-10 5-26 2-30-8-2-5 0-11 4-16z' "
        "fill='#b9764a' stroke='#8c5631' stroke-width='2'/>"
        "<path d='M22 30c5-4 14-4 19 1' fill='none' stroke='#8c5631' stroke-width='1.6' opacity='.6'/>"
        "<rect x='10' y='40' width='12' height='6' rx='3' fill='#f3ece0' stroke='#cdbfa6' stroke-width='1.5'/>"
        "<circle cx='12' cy='43' r='3.4' fill='#f3ece0' stroke='#cdbfa6' stroke-width='1.5'/>"
    ),
    # 회 — 잎 위 슬라이스
    "hoe": _svg(
        "<path d='M10 40c10-12 34-12 44 0-10 8-34 8-44 0z' fill='#7cc47a' opacity='.5'/>"
        "<path d='M18 36c4-5 10-5 14 0-2 4-12 4-14 0z' fill='#f48a6c'/>"
        "<path d='M30 38c4-5 10-5 14 0-2 4-12 4-14 0z' fill='#f7a98f'/>"
        "<path d='M24 31c4-5 10-5 14 0-2 4-12 4-14 0z' fill='#f06a52'/>"
    ),
    # 초밥(니기리) — 밥 + 생선
    "sushi": _svg(
        "<ellipse cx='32' cy='40' rx='20' ry='10' fill='#fbf6ef' stroke='#e3dccf' stroke-width='2'/>"
        "<path d='M14 33c8-7 28-7 36 0 1 4-4 8-18 8s-19-4-18-8z' fill='#f4885f' stroke='#d8623c' stroke-width='2'/>"
        "<line x1='20' y1='34' x2='44' y2='34' stroke='#fcd9c4' stroke-width='1.6' opacity='.8'/>"
    ),
    # 장어(구이) — 길쭉한 토막 + 윤기
    "eel": _svg(
        "<rect x='12' y='27' width='40' height='12' rx='6' fill='#6b4a2e' stroke='#4a3018' stroke-width='2'/>"
        "<line x1='22' y1='27' x2='22' y2='39' stroke='#3a2512' stroke-width='1.5' opacity='.6'/>"
        "<line x1='32' y1='27' x2='32' y2='39' stroke='#3a2512' stroke-width='1.5' opacity='.6'/>"
        "<line x1='42' y1='27' x2='42' y2='39' stroke='#3a2512' stroke-width='1.5' opacity='.6'/>"
        "<path d='M16 30c10-3 22-3 32 0' fill='none' stroke='#c9974f' stroke-width='2' opacity='.7'/>"
    ),
    # 스테이크 — 뼈 붙은 살
    "steak": _svg(
        "<path d='M20 22c12-6 26-2 28 8 2 9-8 16-20 14-12-2-18-10-14-18 1-2 3-3 6-4z' "
        "fill='#9b5a3c' stroke='#6e3b24' stroke-width='2'/>"
        "<circle cx='22' cy='20' r='4' fill='#f3ece0' stroke='#cdbfa6' stroke-width='1.6'/>"
        "<circle cx='16' cy='24' r='4' fill='#f3ece0' stroke='#cdbfa6' stroke-width='1.6'/>"
        "<path d='M30 30l8 8M38 30l-8 8' stroke='#5a2f1c' stroke-width='1.6' opacity='.5'/>"
    ),
    # 웨스턴 — 피자 한 조각
    "western": _svg(
        "<path d='M32 12l18 34c-12 6-24 6-36 0z' fill='#f2c14e' stroke='#d79a2b' stroke-width='2'/>"
        "<path d='M22 40c8 3 12 3 20 0' fill='none' stroke='#e7a92e' stroke-width='2' opacity='.6'/>"
        "<circle cx='28' cy='30' r='3' fill='#d6452f'/>"
        "<circle cx='37' cy='34' r='3' fill='#d6452f'/>"
        "<circle cx='30' cy='40' r='2.6' fill='#d6452f'/>"
    ),
    # 중식/훠궈 — 냄비 + 김
    "hotpot": _svg(
        "<path d='M12 32h40v6c0 9-9 14-20 14s-20-5-20-14z' fill='#c0392b' stroke='#8e271c' stroke-width='2'/>"
        "<rect x='8' y='30' width='48' height='5' rx='2.5' fill='#e0e3e7'/>"
        "<path d='M8 32h4M52 32h4' stroke='#9aa0a8' stroke-width='3' stroke-linecap='round'/>"
        "<path d='M24 24c-2-3 1-5 0-8M34 22c-2-3 1-5 0-8M44 24c-2-3 1-5 0-8' "
        "fill='none' stroke='#bfc6cf' stroke-width='2' stroke-linecap='round' opacity='.8'/>"
    ),
    # 한식 국물(국밥/탕/찌개) — 김 나는 그릇
    "soup": _svg(
        "<path d='M12 34h40v3c0 9-9 15-20 15s-20-6-20-15z' fill='#eef1f4' stroke='#9aa3ad' stroke-width='2'/>"
        "<path d='M16 38c6 4 26 4 32 0' fill='none' stroke='#c2956a' stroke-width='3'/>"
        "<path d='M26 28c-2-3 1-5 0-8M36 28c-2-3 1-5 0-8' "
        "fill='none' stroke='#aeb6bf' stroke-width='2' stroke-linecap='round' opacity='.8'/>"
    ),
    # 면류(라멘/냉면/국수) — 그릇 + 면 + 젓가락
    "noodle": _svg(
        "<path d='M12 32h40v3c0 9-9 15-20 15s-20-6-20-15z' fill='#fbf3da' stroke='#cdb863' stroke-width='2'/>"
        "<path d='M18 34c4 3 8-3 12 0s8-3 12 0' fill='none' stroke='#e7c84d' stroke-width='2.4'/>"
        "<line x1='40' y1='14' x2='52' y2='38' stroke='#9a6b3f' stroke-width='2.4' stroke-linecap='round'/>"
        "<line x1='46' y1='13' x2='56' y2='34' stroke='#9a6b3f' stroke-width='2.4' stroke-linecap='round'/>"
    ),
    # 닭(치킨/닭갈비) — 드럼스틱
    "chicken": _svg(
        "<path d='M40 16c8 0 12 8 7 14-4 5-12 5-15 1-3 4-2 9 2 11 3 2 2 6-2 6-7 0-12-7-9-14 1-3 4-5 7-5-2-4-1-9 3-13 2-2 5-3 0 0z' "
        "fill='#c87f3e' stroke='#9a5d27' stroke-width='2'/>"
        "<rect x='14' y='40' width='12' height='5' rx='2.5' fill='#f3ece0' stroke='#cdbfa6' stroke-width='1.5'/>"
    ),
    # 와인 — 와인잔
    "wine": _svg(
        "<path d='M22 14h20c0 12-4 18-10 18s-10-6-10-18z' fill='#8e3b5e' stroke='#5f223c' stroke-width='2'/>"
        "<line x1='32' y1='32' x2='32' y2='46' stroke='#7a7f87' stroke-width='2.4'/>"
        "<rect x='24' y='46' width='16' height='4' rx='2' fill='#7a7f87'/>"
    ),
    # 맥주 — 머그
    "beer": _svg(
        "<rect x='18' y='20' width='22' height='30' rx='3' fill='#f2c14e' stroke='#cf9a2b' stroke-width='2'/>"
        "<rect x='18' y='16' width='22' height='8' rx='4' fill='#fdfaf2' stroke='#e6ddc8' stroke-width='2'/>"
        "<path d='M40 26h6c4 0 4 12 0 12h-6' fill='none' stroke='#cf9a2b' stroke-width='3'/>"
    ),
    # 위스키 — 텀블러 + 호박색 + 얼음
    "whisky": _svg(
        "<path d='M20 22h24l-3 26H23z' fill='#e3f0f5' stroke='#9aa9b2' stroke-width='2'/>"
        "<path d='M22 34h20l-1.5 14H23.5z' fill='#cf8a2e' opacity='.85'/>"
        "<rect x='25' y='36' width='8' height='7' rx='1.5' fill='#fff' opacity='.55'/>"
    ),
    # 범용 폴백 — 접시 + 포크/나이프
    "plate": _svg(
        "<circle cx='32' cy='32' r='16' fill='#fbfbfd' stroke='#b8c0c9' stroke-width='2'/>"
        "<circle cx='32' cy='32' r='9' fill='none' stroke='#d3d9df' stroke-width='1.6'/>"
        "<line x1='12' y1='20' x2='12' y2='44' stroke='#9aa3ad' stroke-width='2.4' stroke-linecap='round'/>"
        "<line x1='52' y1='20' x2='52' y2='44' stroke='#9aa3ad' stroke-width='2.4' stroke-linecap='round'/>"
    ),
}

# ── fine 키워드 → 아이콘 키(구체적 우선, 위에서부터 매칭) ───────────
FINE_RULES = [
    ("gopchang", ["곱창", "막창", "대창", "양깃머리", "양곱창"]),
    ("jokbal",   ["족발", "보쌈", "수육", "편육"]),
    ("eel",      ["장어", "민물장어", "풍천장어", "아나고"]),
    ("sushi",    ["초밥", "스시", "오마카세", "회전초밥", "스시오마카세"]),
    ("hoe",      ["횟집", "생선회", "물회", "사시미", "숙성회", "방어", "참치", "광어", "연어회"]),
    ("steak",    ["스테이크"]),
    ("western",  ["파스타", "피자", "리조또", "리조토", "스파게티", "라자냐", "뇨끼",
                  "브런치", "레스토랑", "비스트로", "양식", "이탈리안", "프렌치", "버거", "타파스"]),
    ("hotpot",   ["훠궈", "마라", "마라탕", "마라샹궈", "짜장", "짬뽕", "탕수육", "중식",
                  "중국", "딤섬", "어향", "동파육", "양꼬치"]),
    ("noodle",   ["라멘", "우동", "소바", "냉면", "쌀국수", "국수", "칼국수"]),
    ("chicken",  ["치킨", "닭갈비", "닭구이", "닭발", "닭한마리"]),
    ("soup",     ["국밥", "곰탕", "설렁탕", "육개장", "감자탕", "추어탕", "삼계탕",
                  "찌개", "전골", "해장", "순대", "순댓국", "갈비탕"]),
    ("meat",     ["삼겹살", "오겹살", "냉삼", "한우", "소고기", "쇠고기", "돼지갈비",
                  "소갈비", "갈비살", "목살", "항정", "차돌", "등심", "안심", "채끝",
                  "고깃집", "고기집", "정육", "흑돼지", "한돈", "이베리코", "구이",
                  "양갈비", "양고기", "주물럭", "뭉티기", "갈매기살"]),
    ("whisky",   ["위스키", "하이볼"]),
    ("wine",     ["와인", "샴페인"]),
    ("beer",     ["수제맥주", "맥주", "크래프트", "펍", "호프"]),
]

# ── 대분류(7버킷) → 아이콘 키 폴백 ───────────────────────────────
MAJOR_FALLBACK = {
    "고기": "meat",
    "물고기·해산물": "hoe",
    "일식": "sushi",
    "중식": "hotpot",
    "웨스턴(양식)": "western",
    "바·주류": "wine",
    "한식·기타": "soup",
}


def icon_key_for(category: str, major: str = "") -> str:
    """원문 카테고리(+대분류)를 아이콘 키로 결정론 매핑."""
    text = (category or "")
    for key, kws in FINE_RULES:
        if any(kw in text for kw in kws):
            return key
    return MAJOR_FALLBACK.get((major or "").strip(), "plate")


def icon_band_html(category: str, major: str = "") -> str:
    """카드 .photo 밴드용 인라인 SVG 아이콘 + 카테고리 색조 배경 div.

    기존 빈 `<div class=thumb></div>` 를 대체. 오버레이(순위/페어링/미니지도)는
    호출부(_render_html)에서 그대로 위에 얹힌다.
    """
    key = icon_key_for(category, major)
    c1, c2 = TINTS.get(key, TINTS["plate"])
    return (
        f"<div class=thumb style=\"display:flex;align-items:center;justify-content:center;"
        f"background:linear-gradient(135deg,{c1},{c2})\">{ICONS[key]}</div>"
    )


if __name__ == "__main__":
    # 셀프테스트: 보드가 예로 든 케이스 + 대표 케이스 매핑 확인
    samples = [
        ("족발, 보쌈", "한식·기타"),
        ("곱창, 소곱창", "고기"),
        ("막창, 곱창", "고기"),
        ("한우, 소고기", "고기"),
        ("삼겹살, 고기집", "고기"),
        ("스시오마카세", "일식"),
        ("횟집, 방어", "물고기·해산물"),
        ("장어", "물고기·해산물"),
        ("훠궈", "중식"),
        ("파스타, 레스토랑", "웨스턴(양식)"),
        ("육개장, 한우육개장", "한식·기타"),
        ("와인바", "바·주류"),
        ("", "한식·기타"),       # fine 미매칭 → 대분류 폴백
        ("정체불명", ""),         # 전부 미매칭 → plate
    ]
    print("category / major -> icon_key")
    for cat, maj in samples:
        print(f"  {cat or '(빈값)':16s} / {maj or '(빈값)':8s} -> {icon_key_for(cat, maj)}")
    print(f"\n아이콘 종류: {len(ICONS)}개 ->", ", ".join(ICONS))
