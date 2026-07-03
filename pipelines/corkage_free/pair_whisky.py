#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
pair_whisky.py — 콜키지프리 식당 × 가성비 위스키 페어링 엔진 (CMPA-61)

흐름:
  1) data/corkage-free/{역}_콜키지프리.csv 읽기 (CMPA-55 finder 산출물)
  2) DiningCode 카테고리 = '대표 메뉴' 신호 → 음식 프로필 분류(규칙 기반)
     (웹 검증: 먼데이블루스/이자카야 열은 카테고리=실제 대표메뉴 일치 확인. CMPA-61)
  3) 음식 프로필 → 페어링 원리 → 사내 가성비 위스키 카탈로그(assets/whisky-list.csv)에서
     1순위/대안 추천 + 서빙법 + '근거(왜 어울리나)' 생성
  4) data/restaurant-pairings/{역}_위스키페어링.{csv,md,html} 저장 (+ _runs/ 날짜 스냅샷)

근거의 출처는 고전 푸드페어링 원리: 지방절단(고도수·탄산), 마이야르/훈연 동조(피트),
감칠맛 보완(셰리 건과일), 매운맛 완화(버번 옥수수 단맛/희석), 담백함 보존(피트無 경량 몰트).
가격은 assets/whisky-list.csv 기준(2026-05-31, 국내 트레이더스/코스트코/데일리샷 교차) — 변동성 주의.
"""
import csv
import os
import sys
import argparse
import datetime
import html

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
WHISKY_CSV = os.path.join(ROOT, "assets", "whisky-list.csv")
CORKAGE_DIR = os.path.join(ROOT, "data", "corkage-free")
OUT_DIR = os.path.join(ROOT, "data", "restaurant-pairings")
PRICE_DATE = "2026-05-31"

# ---------------------------------------------------------------------------
# 위스키 카탈로그 로드
# ---------------------------------------------------------------------------
def load_whiskies():
    by_id = {}
    with open(WHISKY_CSV, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            by_id[r["id"]] = r
    return by_id

def price_str(w):
    lo, hi = w.get("price_krw_low", ""), w.get("price_krw_high", "")
    def fmt(v):
        try:
            return f"{int(float(v)):,}원"
        except Exception:
            return ""
    flo, fhi = fmt(lo), fmt(hi)
    if flo and fhi and flo != fhi:
        return f"{flo}~{fhi}"
    return flo or fhi or "가격미상"

# ---------------------------------------------------------------------------
# 음식 프로필 규칙 (우선순위 = 위에서 아래로 첫 매칭 승리; 구체적 키워드 먼저)
#   keys: name(프로필), menu(대표메뉴 라벨), kw(카테고리 매칭 키워드),
#         primary/alt(위스키 id), serve(서빙), reason(근거 템플릿)
# ---------------------------------------------------------------------------
PROFILES = [
    dict(
        name="양고기·향신료",
        menu="양갈비·양꼬치 (구운 양고기)",
        kw=["양갈비", "양고기", "양꼬치"],
        primary="w035", alt="w036", serve="니트 또는 물 몇 방울",
        reason="양고기 특유의 진한 누린향·쯔란(커민) 향신료에는 아일라 피트의 훈연·요오드가 "
               "'훈제 양고기'처럼 동조하며 기름기를 깔끔히 정리한다(훈연 동조).",
    ),
    dict(
        name="장어·양념구이",
        menu="장어구이 (단짠 양념·기름)",
        kw=["장어"],
        primary="w032", alt="w069", serve="하이볼 또는 니트",
        reason="장어 양념구이의 단짠 소스와 기름진 살에는 탈리스커의 후추·바다향 훈연이 대비를 "
               "주며 느끼함을 끊고, 대안 버번의 옥수수 단맛은 양념과 결이 맞는다(지방절단·대비).",
    ),
    dict(
        name="곱창·막창(소내장)",
        menu="곱창·막창·대창 (불향 내장구이)",
        kw=["곱창", "막창", "대창", "양대창"],
        primary="w069", alt="w035", serve="니트 또는 하이볼",
        reason="기름지고 풍미가 강한 내장구이에는 버번의 옥수수 단맛+높은 도수가 기름·잡내를 "
               "정리하고, 대안 아일라 피트는 숯불 불향과 훈연으로 동조한다(지방절단·훈연 동조).",
    ),
    dict(
        name="회·사시미·스시(담백)",
        menu="모듬회·사시미·스시 (담백한 생선)",
        kw=["사시미", "생선회", "횟집", "스시", "일식", "복어", "복국", "도미", "숙성회", "문어", "백합샤브", "샤브샤브"],
        primary="w025", alt="w001", serve="하이볼 또는 니트(소량)",
        reason="섬세한 흰살·붉은살 생선의 감칠맛을 덮지 않도록 피트 없는 경량 몰트가 정답. "
               "클라이넬리시의 해풍·왁시한 질감이 회의 바다향과 동조하고, 대안 글렌리벳은 "
               "사과·꽃향으로 입을 가볍게 정리한다(담백함 보존).",
    ),
    dict(
        name="참치·방어(기름진 생선)",
        menu="참치·방어 (지방 오른 생선)",
        kw=["참치", "방어"],
        primary="w032", alt="w025", serve="하이볼 또는 니트(소량)",
        reason="대뱃살·방어처럼 지방이 오른 생선에는 탈리스커의 옅은 훈연·후추·바다향이 "
               "기름을 정리하면서 풍미를 끌어올린다(지방절단·바다향 동조).",
    ),
    dict(
        name="숙성 한우·소고기구이",
        menu="한우·숙성 소고기구이 (마블링·마이야르)",
        kw=["한우", "소고기", "등심", "갈비살", "안창", "특수부위", "드라이에이징", "뭉티기",
            "생갈비", "꽃살", "왕갈비", "마늘갈비", "소갈비", "정육", "흑우", "솥밥", "장어, 소고기"],
        primary="w018", alt="w069", serve="니트",
        reason="숙성 한우의 진한 감칠맛과 마이야르(불맛)에는 셰리캐스크의 건과일·견과 단맛이 "
               "풍미의 층을 더하고, 대안 버번의 높은 도수가 마블링 기름을 정리한다(감칠맛 보완·지방절단).",
    ),
    dict(
        name="삼겹살·돼지구이",
        menu="삼겹살·목살·돼지구이 (기름진 구이)",
        kw=["삼겹살", "목살", "돼지갈비", "흑돼지", "이베리코", "돼지고기", "항정", "오돌갈비", "꽃삼겹", "한돈", "고기집", "고깃집"],
        primary="w083", alt="w032", serve="하이볼",
        reason="기름진 삼겹·목살에는 하이볼의 탄산이 느끼함을 끊어주는 클래식 조합(가쿠빈 하이볼). "
               "대안 탈리스커는 숯불 불향과 훈연으로 동조한다(지방절단·훈연 동조).",
    ),
    dict(
        name="냉면·평양냉면(담백)",
        menu="평양냉면·어복쟁반 (슴슴한 육수)",
        kw=["평양냉면", "냉면", "어복쟁반"],
        primary="w038", alt="w001", serve="니트(소량) 또는 하이볼",
        reason="슴슴한 메밀과 맑은 육수의 섬세함을 해치지 않는 가벼운 로우랜드/스페이사이드가 적합. "
               "꽃·맥아의 깔끔함이 식사를 무겁게 하지 않는다(담백함 보존).",
    ),
    dict(
        name="국밥·곰탕·탕류(한식 보양)",
        menu="국밥·곰탕·갈비탕·족발 (진한 국물)",
        kw=["국밥", "곰탕", "갈비탕", "육개장", "수육", "족발", "순대", "막걸리", "곰탕", "갈비탕", "한식"],
        primary="w055", alt="w065", serve="하이볼",
        reason="진한 국물·마늘·기름진 고기에는 듀어스의 꿀향·부드러움이 무난히 어울리고, "
               "하이볼로 내면 입가심까지 된다(부드러움 매칭·지방절단).",
    ),
    dict(
        name="중식(매운/마라)",
        menu="훠궈·마라 (얼얼·매운 중식)",
        kw=["훠궈", "마라"],
        primary="w071", alt="w055", serve="온더락 또는 하이볼",
        reason="얼얼하고 매운 마라·훠궈에는 밀(휘티드) 버번 메이커스 마크의 둥근 단맛이 "
               "캡사이신 자극을 누그러뜨린다. 고도수 니트는 매운맛을 키우니 희석 권장(매운맛 완화).",
    ),
    dict(
        name="중식(기름진 볶음)",
        menu="짜장·동파육·어향 (기름진 중식)",
        kw=["중식", "짜장", "동파육", "어향"],
        primary="w043", alt="w065", serve="하이볼",
        reason="기름진 볶음·소스 중식에는 하이볼 탄산이 느끼함을 정리한다. 가벼운 블렌디드(발렌타인) "
               "베이스가 음식의 풍미를 누르지 않는다(지방절단).",
    ),
    dict(
        name="아구찜·매운 해물찜",
        menu="아구찜·매운탕 (칼칼한 해물찜)",
        kw=["아구찜", "지리탕", "매운탕", "아구"],
        primary="w020", alt="w055", serve="하이볼",
        reason="고춧가루·콩나물의 칼칼한 매운맛에는 글렌모렌지의 부드러운 과일·바닐라 향과 "
               "하이볼의 희석이 자극을 진정시킨다(매운맛 완화).",
    ),
    dict(
        name="등푸른생선·생선구이",
        menu="고등어·생선구이 (기름진 등푸른생선)",
        kw=["생선구이", "고등어"],
        primary="w032", alt="w025", serve="니트 또는 하이볼",
        reason="구운 등푸른생선의 기름과 바다향에는 탈리스커의 해풍·후추·옅은 훈연이 "
               "동조하며 비린맛을 정리한다(바다향 동조·지방절단).",
    ),
    dict(
        name="닭구이",
        menu="닭구이·닭특수부위 (불향 닭)",
        kw=["닭구이", "닭"],
        primary="w066", alt="w065", serve="하이볼",
        reason="담백한 닭 불구이에는 잭다니엘의 가벼운 단맛·바닐라가 양념과 어울리고 "
               "하이볼로 부담 없이 즐긴다(가벼운 단맛 매칭).",
    ),
    dict(
        name="동남아(쌀국수·팟타이)",
        menu="쌀국수·팟타이 (허브·향신료)",
        kw=["쌀국수", "팟타이"],
        primary="w020", alt="w055", serve="하이볼",
        reason="허브·라임·약한 매운맛의 동남아 면요리에는 글렌모렌지의 시트러스·과일향이 "
               "산뜻하게 맞고 하이볼이 가볍게 받쳐준다(향 동조).",
    ),
    dict(
        name="스테이크·양식 고기",
        menu="스테이크 (드라이에이징·양식 육요리)",
        kw=["스테이크", "투움바", "드라이에이징스테이크"],
        primary="w018", alt="w072", serve="니트",
        reason="육즙 가득한 스테이크에는 셰리캐스크 몰트의 건과일·견과가 마이야르 풍미와 층을 "
               "이루고, 대안 우드포드 버번의 단맛·바닐라가 시즈닝과 어울린다(감칠맛 보완).",
    ),
    dict(
        name="양식·파스타·피자",
        menu="파스타·피자·리조또 (양식)",
        kw=["파스타", "피자", "양식", "뇨끼", "라자냐", "비스트로", "브런치", "호주", "뉴욕", "레스토랑", "퓨전", "화덕"],
        primary="w005", alt="w083", serve="니트 또는 하이볼",
        reason="토마토·치즈·크림의 산미와 감칠맛에는 글렌피딕의 가벼운 배·사과향이 식사주로 "
               "무난하고, 하이볼로 내면 가벼운 식전·식중주가 된다(과일향 매칭).",
    ),
    dict(
        name="와인바·샴페인(디제스티프)",
        menu="와인바·샴페인 (안주+식후주)",
        kw=["와인바", "샴페인", "와인"],
        primary="w008", alt="w018", serve="니트(식후)",
        reason="와인바의 치즈·차콘류 안주와 식후 한 잔에는 발베니 더블우드의 셰리·꿀·오크가 "
               "디저트처럼 마무리된다(디제스티프).",
    ),
    dict(
        name="이자카야·사케·라멘(일식주점)",
        menu="이자카야·사케·라멘 (일식 주점)",
        kw=["이자카야", "사케", "라멘", "온면"],
        primary="w083", alt="w001", serve="하이볼",
        reason="야키토리·꼬치·라멘 등 기름지고 짭짤한 일식 주점 안주에는 일본식 하이볼(가쿠빈)이 "
               "정석이다. 탄산이 기름을 끊고 가볍게 이어 마실 수 있다(지방절단·문화적 정합).",
    ),
    dict(
        name="칵테일바",
        menu="칵테일바 (믹솔로지)",
        kw=["칵테일"],
        primary="w070", alt="w065", serve="온더락 또는 칵테일 베이스",
        reason="칵테일바에서는 1792·짐빔 같은 버번이 올드패션드/위스키사워 등 클래식 칵테일 "
               "베이스로 가성비 좋게 어울린다(베이스 정합).",
    ),
    dict(
        name="수제맥주·술집",
        menu="수제맥주·술집 (가벼운 안주)",
        kw=["수제맥주", "술집"],
        primary="w065", alt="w043", serve="하이볼 또는 보일러메이커",
        reason="펍 안주와 맥주 곁들임에는 짐빔 하이볼이 가볍고, 맥주+위스키(보일러메이커)로도 "
               "부담 없이 즐길 수 있다(가벼운 곁들임).",
    ),
]

# 최후 폴백
FALLBACK = dict(
    name="기타(범용)",
    menu="대표메뉴 확인 필요",
    kw=[],
    primary="w050", alt="w083", serve="하이볼 또는 니트",
    reason="메뉴 특성이 분류 밖이라 범용 추천. 조니워커 블랙은 가벼운 훈연·과일의 밸런스로 "
           "대부분의 식사와 무난하고, 하이볼로도 좋다(올라운더).",
)

def classify(category):
    cat = category or ""
    for p in PROFILES:
        for k in p["kw"]:
            if k in cat:
                return p
    return FALLBACK

# ---------------------------------------------------------------------------
# 위스키 '종류(스타일)' 분류 체계 — CMPA-61 보드 요청: 보틀이 아닌 *종류* 단위 페어링이 1차 산출물.
#   (오늘의 추천 보틀은 후속. 이 스타일 매트릭스가 변하지 않는 기준선.)
# ---------------------------------------------------------------------------
STYLES = {
    "버번":        dict(en="Bourbon", 특징="옥수수 단맛·바닐라·오크, 비교적 高도수", 역할="기름 절단·매운맛 완화·단짠 양념과 정합"),
    "라이":        dict(en="Rye", 특징="스파이시·드라이·후추감", 역할="기름진 음식 컷, 클래식 칵테일 베이스"),
    "피트(스모키)": dict(en="Peated / Islay·Island", 특징="훈연·요오드·바다향(아일라/스카이)", 역할="숯불 구이·양고기·기름진 생선과 훈연 동조"),
    "셰리":        dict(en="Sherried", 특징="건과일·견과·초콜릿 단맛", 역할="숙성육 감칠맛 보완·식후 디제스티프"),
    "스페이사이드(과일몰트)": dict(en="Speyside (unpeated)", 특징="사과·배·꽃·맥아의 가벼운 단맛", 역할="가벼운 식사·양식·담백한 안주의 식중주"),
    "하이랜드(균형/시트러스)": dict(en="Highland", 특징="시트러스·꿀·은은한 과일, 균형형", 역할="매운/향신 음식 완화, 올라운드"),
    "코스탈(해안 몰트)": dict(en="Coastal (unpeated/lightly)", 특징="해풍·미네랄·왁시함, 피트 약하거나 無", 역할="회·해산물의 바다향과 동조하되 덮지 않음"),
    "로우랜드(라이트)": dict(en="Lowland", 특징="플로럴·라이트·드라이", 역할="냉면 등 슴슴·섬세한 음식 보존"),
    "블렌디드(하이볼)": dict(en="Blended", 특징="부드러운 밸런스, 하이볼 베이스로 무난", 역할="국물·기름진 볶음·범용, 탄산 희석"),
    "재패니즈(하이볼)": dict(en="Japanese / Highball", 특징="가볍고 깔끔, 탄산과 궁합", 역할="이자카야·삼겹살 등 하이볼 정석"),
    "테네시":      dict(en="Tennessee", 특징="버번계, 차콜필터로 둥근 단맛", 역할="닭·가벼운 양념 구이 하이볼"),
}

# 음식 프로필(이름) → (1순위 위스키종류, 대안 종류, 종류기반 근거 한 줄)
PROFILE_STYLE = {
    "양고기·향신료":        ("피트(스모키)", "셰리", "누린향·쯔란(커민)에 피트 훈연이 '훈제양고기'처럼 동조; 셰리는 풍미를 받쳐줌."),
    "장어·양념구이":        ("피트(스모키)", "버번", "단짠 양념·기름을 피트의 후추·훈연이 대비로 끊고, 버번 단맛은 양념과 결이 맞음."),
    "곱창·막창(소내장)":     ("버번", "피트(스모키)", "버번 단맛+도수로 기름·잡내 정리; 피트는 숯불 불향과 훈연 동조."),
    "회·사시미·스시(담백)":   ("코스탈(해안 몰트)", "스페이사이드(과일몰트)", "해안 몰트의 해풍·미네랄이 회의 바다향과 동조; 피트 없는 경량 몰트로 담백함 보존."),
    "참치·방어(기름진 생선)":  ("피트(스모키)", "코스탈(해안 몰트)", "지방 오른 생선엔 옅은 피트의 후추·훈연이 기름 정리."),
    "숙성 한우·소고기구이":    ("셰리", "버번", "셰리 건과일·견과가 숙성육 감칠맛·마이야르에 층을 더함; 버번 도수로 마블링 절단."),
    "삼겹살·돼지구이":       ("재패니즈(하이볼)", "피트(스모키)", "하이볼 탄산이 기름 절단(클래식); 피트는 숯불 훈연 동조."),
    "냉면·평양냉면(담백)":    ("로우랜드(라이트)", "스페이사이드(과일몰트)", "슴슴한 메밀·맑은 육수의 섬세함을 라이트 몰트로 보존."),
    "국밥·곰탕·탕류(한식 보양)": ("블렌디드(하이볼)", "버번", "진한 국물·마늘·기름엔 부드러운 블렌디드, 하이볼로 입가심."),
    "중식(매운/마라)":       ("버번", "블렌디드(하이볼)", "버번(특히 휘티드) 둥근 단맛이 캡사이신 완화; 고도수 니트보다 희석 권장."),
    "중식(기름진 볶음)":      ("블렌디드(하이볼)", "버번", "기름진 볶음·소스엔 하이볼 탄산이 느끼함 정리."),
    "아구찜·매운 해물찜":     ("하이랜드(균형/시트러스)", "블렌디드(하이볼)", "부드러운 과일·시트러스+희석으로 칼칼한 매운맛 진정."),
    "등푸른생선·생선구이":     ("피트(스모키)", "코스탈(해안 몰트)", "구운 등푸른생선 기름·바다향에 피트의 해풍·후추 동조."),
    "닭구이":              ("테네시", "버번", "차콜필터 둥근 단맛·바닐라가 양념 닭구이와 매칭, 하이볼."),
    "동남아(쌀국수·팟타이)":   ("하이랜드(균형/시트러스)", "블렌디드(하이볼)", "허브·라임·약한 매운맛에 시트러스 과일향이 산뜻."),
    "스테이크·양식 고기":     ("셰리", "버번", "셰리 건과일·견과가 마이야르와 층; 버번 바닐라가 시즈닝과 정합."),
    "양식·파스타·피자":      ("스페이사이드(과일몰트)", "재패니즈(하이볼)", "토마토·치즈·크림에 가벼운 배·사과향 식사주; 하이볼로도 무난."),
    "와인바·샴페인(디제스티프)": ("셰리", "스페이사이드(과일몰트)", "치즈·차콘 안주와 식후 한 잔, 셰리 단맛이 디저트처럼 마무리."),
    "이자카야·사케·라멘(일식주점)": ("재패니즈(하이볼)", "스페이사이드(과일몰트)", "야키토리·라멘 등 기름·짭짤한 안주에 일본식 하이볼 정석."),
    "칵테일바":            ("버번", "라이", "올드패션드·위스키사워 등 클래식 칵테일 베이스로 버번/라이."),
    "수제맥주·술집":        ("버번", "블렌디드(하이볼)", "펍 안주·맥주 곁들임에 버번 하이볼/보일러메이커가 가벼움."),
    "기타(범용)":          ("블렌디드(하이볼)", "스페이사이드(과일몰트)", "분류 밖 범용; 가벼운 훈연·과일 밸런스의 블렌디드가 올라운더."),
}

def styles_for(profile_name):
    return PROFILE_STYLE.get(profile_name, PROFILE_STYLE["기타(범용)"])

# ---------------------------------------------------------------------------
# 페어링 행 생성
# ---------------------------------------------------------------------------
def build_pairings(station, whiskies):
    src = os.path.join(CORKAGE_DIR, f"{station}_콜키지프리.csv")
    if not os.path.exists(src):
        raise SystemExit(f"입력 없음: {src} (먼저 find_corkage_free.py 실행)")
    out = []
    with open(src, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            prof = classify(r["카테고리"])
            pstyle, astyle, _ = styles_for(prof["name"])
            w1 = whiskies.get(prof["primary"], {})
            w2 = whiskies.get(prof["alt"], {})
            signal = (r.get("위스키신호") or "").strip()
            out.append({
                "역": station,
                "순위": r.get("순위", ""),
                "식당명": r["식당명"],
                "카테고리": r["카테고리"],
                "대표메뉴(추정)": prof["menu"],
                "음식프로필": prof["name"],
                "추천_위스키종류": pstyle,
                "대안_위스키종류": astyle,
                "예시보틀(후속)": w1.get("name_ko", prof["primary"]),
                "예시보틀_가격": price_str(w1) if w1 else "",
                "서빙": prof["serve"],
                "페어링근거": prof["reason"],
                "위스키신호": "있음" if signal else "",
                "네이버지도": r.get("네이버지도", ""),
                "대표사진": r.get("대표사진", ""),
                "confidence": "메뉴=카테고리 추정·페어링=원리기반(매장 위스키정책 전화확인 권장)",
            })
    return out

# ---------------------------------------------------------------------------
# 출력
# ---------------------------------------------------------------------------
CSV_COLS = ["역", "순위", "식당명", "카테고리", "대표메뉴(추정)", "음식프로필",
            "추천_위스키종류", "대안_위스키종류", "예시보틀(후속)", "예시보틀_가격", "서빙",
            "페어링근거", "위스키신호", "네이버지도", "대표사진", "confidence"]

def write_csv(path, rows):
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLS)
        w.writeheader()
        for r in rows:
            w.writerow(r)

def write_md(path, station, rows):
    lines = [f"# {station} 콜키지프리 식당 × 위스키 *종류* 페어링\n",
             f"_DiningCode 카테고리(대표메뉴 신호) → 어울리는 위스키 **종류(스타일)** + 근거 · CMPA-61_\n",
             f"\n총 **{len(rows)}곳**. 1차 산출물은 **음식↔위스키종류** 페어링이며, 예시보틀은 후속 '오늘의 추천' 참고용.\n",
             "\n| # | 식당 | 대표메뉴(추정) | 추천 위스키종류 | 대안 종류 | 서빙 | 근거 | 예시보틀(후속) |",
             "|---|------|----------------|------------------|-----------|------|------|----------------|"]
    for r in rows:
        flag = " 🥃" if r["위스키신호"] else ""
        lines.append(
            f'| {r["순위"]} | {r["식당명"]}{flag} | {r["대표메뉴(추정)"]} | '
            f'**{r["추천_위스키종류"]}** | {r["대안_위스키종류"]} | {r["서빙"]} | {r["페어링근거"]} | '
            f'{r["예시보틀(후속)"]} ({r["예시보틀_가격"]}) |'
        )
    lines.append("\n> 🥃 = DiningCode 위스키 취급 신호가 있는 매장(페어링 실현 가능성 높음).")
    lines.append("> 위스키 *종류*가 기준선(불변). 예시보틀/가격은 후속 '오늘의 추천' 단계 산출물.")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

def write_html(path, station, rows):
    h = [f"<!doctype html><html lang=ko><meta charset=utf-8>",
         f"<title>{station} 식당×위스키 페어링</title>",
         "<style>body{font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;margin:24px;background:#faf8f5;color:#222}"
         "h1{font-size:20px}.sub{color:#777;font-size:13px;margin-bottom:16px}"
         ".card{background:#fff;border:1px solid #eee;border-radius:12px;padding:14px 16px;margin:10px 0;display:flex;gap:14px;box-shadow:0 1px 3px rgba(0,0,0,.04)}"
         ".thumb{width:84px;height:84px;border-radius:10px;object-fit:cover;flex:none;background:#eee}"
         ".body{flex:1}.name{font-weight:700;font-size:16px}.menu{color:#555;font-size:13px;margin:2px 0 8px}"
         ".pair{background:#fff8e7;border:1px solid #ffe9a8;border-radius:8px;padding:8px 10px;font-size:14px}"
         ".w1{font-weight:700;color:#8a6d00}.price{color:#b8860b;font-weight:600}.serve{color:#666;font-size:12px}"
         ".reason{font-size:13px;color:#444;margin-top:6px;line-height:1.5}"
         ".alt{font-size:12px;color:#888;margin-top:4px}.badge{display:inline-block;background:#5b2a86;color:#fff;font-size:11px;"
         "padding:1px 7px;border-radius:10px;margin-left:6px}.rank{color:#aaa;font-size:12px}"
         "a.map{font-size:12px;color:#2a6;text-decoration:none}</style>",
         f"<h1>🥃 {station} 콜키지프리 식당 × 위스키 종류 페어링</h1>",
         f"<div class=sub>대표메뉴(카테고리 추정) → 어울리는 위스키 <b>종류(스타일)</b> + 근거 · {len(rows)}곳 · CMPA-61<br>"
         "1차 산출물=음식↔위스키종류. 예시보틀은 후속 '오늘의 추천' 참고용. 🟣배지=위스키 취급 신호 매장.</div>"]
    for r in rows:
        thumb = f'<img class=thumb src="{html.escape(r["대표사진"])}" onerror="this.style.visibility=\'hidden\'">' if r["대표사진"] else '<div class=thumb></div>'
        badge = '<span class=badge>위스키 취급</span>' if r["위스키신호"] else ''
        mapl = f'<a class=map href="{html.escape(r["네이버지도"])}" target=_blank>📍네이버지도</a>' if r["네이버지도"] else ''
        h.append(
            f'<div class=card>{thumb}<div class=body>'
            f'<div class=name><span class=rank>#{html.escape(str(r["순위"]))}</span> {html.escape(r["식당명"])}{badge} {mapl}</div>'
            f'<div class=menu>대표메뉴(추정): {html.escape(r["대표메뉴(추정)"])} · <i>{html.escape(r["카테고리"])}</i></div>'
            f'<div class=pair><span class=w1>🥃 {html.escape(r["추천_위스키종류"])}</span> '
            f'<span class=serve>· {html.escape(r["서빙"])} · 대안: {html.escape(r["대안_위스키종류"])}</span>'
            f'<div class=reason>{html.escape(r["페어링근거"])}</div>'
            f'<div class=alt>예시보틀(후속): {html.escape(r["예시보틀(후속)"])} ({html.escape(r["예시보틀_가격"])})</div></div>'
            f'</div></div>'
        )
    h.append('<div class=sub>위스키 종류가 기준선(불변). 예시보틀/가격은 후속 단계 산출물. 매장 위스키 반입정책은 확인 필요.</div></html>')
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(h))

def write_style_matrix(out_dir):
    """1차 산출물: 음식 카테고리 ↔ 위스키 종류(스타일) 페어링 기준표 (보틀 무관)."""
    # 음식 프로필 순서 = PROFILES 순서 + 폴백
    order = [p["name"] for p in PROFILES] + ["기타(범용)"]
    menu_of = {p["name"]: p["menu"] for p in PROFILES}
    menu_of["기타(범용)"] = FALLBACK["menu"]
    serve_of = {p["name"]: p["serve"] for p in PROFILES}
    serve_of["기타(범용)"] = FALLBACK["serve"]

    # --- CSV ---
    cols = ["음식프로필", "대표메뉴(예)", "추천_위스키종류", "대안_위스키종류", "서빙", "근거"]
    csv_path = os.path.join(out_dir, "음식-위스키종류_페어링.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for name in order:
            ps, as_, reason = styles_for(name)
            w.writerow([name, menu_of.get(name, ""), ps, as_, serve_of.get(name, ""), reason])

    # --- 위스키 종류 사전 CSV ---
    sty_path = os.path.join(out_dir, "위스키종류_사전.csv")
    with open(sty_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["위스키종류", "영문", "풍미특징", "페어링역할"])
        for k, v in STYLES.items():
            w.writerow([k, v["en"], v["특징"], v["역할"]])

    # --- MD ---
    md = ["# 음식 ↔ 위스키 종류(스타일) 페어링 기준표 (CMPA-61 · 1차 산출물)\n",
          "_보드 요청: 보틀이 아닌 **위스키 종류(버번/피트/쉐리 등)** 단위 페어링을 우선 정립._",
          "_'오늘의 추천 위스키(보틀)'는 이 기준표를 따르는 후속 단계._\n",
          "## A. 위스키 종류 사전",
          "| 위스키종류 | 영문 | 풍미특징 | 페어링 역할 |",
          "|---|---|---|---|"]
    for k, v in STYLES.items():
        md.append(f'| **{k}** | {v["en"]} | {v["특징"]} | {v["역할"]} |')
    md += ["\n## B. 음식 → 위스키 종류 페어링",
           "| 음식 프로필 | 대표메뉴(예) | 추천 종류 | 대안 종류 | 서빙 | 근거 |",
           "|---|---|---|---|---|---|"]
    for name in order:
        ps, as_, reason = styles_for(name)
        md.append(f'| {name} | {menu_of.get(name,"")} | **{ps}** | {as_} | {serve_of.get(name,"")} | {reason} |')
    md.append("\n> 페어링 원리: 지방절단(버번 도수·하이볼 탄산) · 마이야르/훈연 동조(피트) · "
              "감칠맛 보완(셰리) · 매운맛 완화(버번 단맛/희석) · 담백함 보존(라이트 몰트) · 디제스티프(셰리).")
    md_path = os.path.join(out_dir, "음식-위스키종류_페어링.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    # --- HTML ---
    h = ["<!doctype html><html lang=ko><meta charset=utf-8><title>음식↔위스키종류 페어링</title>",
         "<style>body{font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;margin:24px;background:#faf8f5;color:#222}"
         "h1{font-size:21px}h2{font-size:16px;margin-top:24px}.sub{color:#777;font-size:13px;margin-bottom:8px}"
         "table{border-collapse:collapse;width:100%;font-size:13px;background:#fff}"
         "th,td{border:1px solid #eee;padding:7px 9px;text-align:left;vertical-align:top}"
         "th{background:#f3ece0}td.s{font-weight:700;color:#8a6d00;white-space:nowrap}</style>",
         "<h1>🥃 음식 ↔ 위스키 종류(스타일) 페어링 기준표</h1>",
         "<div class=sub>CMPA-61 1차 산출물 — 보틀이 아닌 <b>위스키 종류</b>(버번·피트·쉐리 등) 단위. '오늘의 추천 보틀'은 후속.</div>",
         "<h2>A. 위스키 종류 사전</h2><table><tr><th>종류</th><th>영문</th><th>풍미특징</th><th>페어링 역할</th></tr>"]
    for k, v in STYLES.items():
        h.append(f'<tr><td class=s>{html.escape(k)}</td><td>{html.escape(v["en"])}</td>'
                 f'<td>{html.escape(v["특징"])}</td><td>{html.escape(v["역할"])}</td></tr>')
    h.append("</table><h2>B. 음식 → 위스키 종류 페어링</h2>"
             "<table><tr><th>음식 프로필</th><th>대표메뉴(예)</th><th>추천 종류</th><th>대안</th><th>서빙</th><th>근거</th></tr>")
    for name in order:
        ps, as_, reason = styles_for(name)
        h.append(f'<tr><td>{html.escape(name)}</td><td>{html.escape(menu_of.get(name,""))}</td>'
                 f'<td class=s>{html.escape(ps)}</td><td>{html.escape(as_)}</td>'
                 f'<td>{html.escape(serve_of.get(name,""))}</td><td>{html.escape(reason)}</td></tr>')
    h.append("</table><div class=sub style='margin-top:14px'>원리: 지방절단·훈연동조·감칠맛보완·매운맛완화·담백보존·디제스티프.</div></html>")
    html_path = os.path.join(out_dir, "음식-위스키종류_페어링.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write("\n".join(h))
    return csv_path, md_path, html_path, sty_path

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stations", nargs="*", default=["강남역", "합정역"])
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    whiskies = load_whiskies()
    os.makedirs(OUT_DIR, exist_ok=True)
    runs = os.path.join(OUT_DIR, "_runs")
    os.makedirs(runs, exist_ok=True)
    today = datetime.date.fromisoformat(PRICE_DATE).isoformat()

    # 1차 산출물: 음식↔위스키종류 기준표 (역과 무관, 보틀 무관)
    if not args.dry_run:
        sm = write_style_matrix(OUT_DIR)
        for p in sm:
            snap = os.path.join(runs, os.path.basename(p).replace(".", f"__run{today}.", 1))
            with open(p, encoding="utf-8") as fi, open(snap, "w", encoding="utf-8") as fo:
                fo.write(fi.read())
        print(f"[기준표] 음식↔위스키종류 페어링 저장: {os.path.basename(sm[0])} 외 {len(sm)-1}건 (+스냅샷)")

    for st in args.stations:
        rows = build_pairings(st, whiskies)
        sig = sum(1 for r in rows if r["위스키신호"])
        print(f"[{st}] {len(rows)}곳 페어링 (위스키 취급 신호 {sig}곳)")
        from collections import Counter
        prof_counts = Counter(r["음식프로필"] for r in rows)
        for p, n in prof_counts.most_common():
            print(f"    - {p}: {n}")
        if args.dry_run:
            continue
        base = os.path.join(OUT_DIR, f"{st}_위스키페어링")
        write_csv(base + ".csv", rows)
        write_md(base + ".md", st, rows)
        write_html(base + ".html", st, rows)
        for ext in ("csv", "md", "html"):
            snap = os.path.join(runs, f"{st}_위스키페어링__run{today}.{ext}")
            with open(base + "." + ext, encoding="utf-8") as fi, open(snap, "w", encoding="utf-8") as fo:
                fo.write(fi.read())
        print(f"    저장: {base}.{{csv,md,html}} (+ _runs 스냅샷)")

if __name__ == "__main__":
    main()
