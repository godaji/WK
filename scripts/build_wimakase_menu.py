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
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# 발행마다 자동 증가하는 빌드 카운터 — 캐시버스트 신호(CMPA-1285). 사이드카 파일에 누적 저장.
BUILD_FILE = Path(__file__).resolve().parent / "wimakase_build.txt"
VERSION = "v2026.08.16"
TITLE = "합정 두다지 위마카세"
# 상세(증류소·스토리) 메타 수집일 — CLAUDE.md 데이터 관리 원칙(수집 날짜 메타 필수, CMPA-1284).
COLLECTED = "2026-08-16"

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
            ("글렌알라키 15년", "싱글 몰트 스카치", "46%", "진득한 셰리 풍미로 최근 가장 인기 있는 바틀"),
            ("매캘란 더블우드 12년", "싱글 몰트 스카치", "40%", "싱글 몰트의 절대 강자, 훌륭한 밸런스"),
            ("에버펠디 16년", "싱글 몰트 스카치", "40%", "부드럽고 꿀 같은 달콤함"),
            ("로얄 브라크라 12년", "싱글 몰트 스카치", "46%", "올로로소 셰리 피니시, 고급스럽고 우아한 맛"),
            ("부나하벤 12년", "싱글 몰트 스카치", "46.3%", "논칠필터, 훌륭한 바디감의 아일라 몰트"),
            ("러셀 리저브 싱글배럴", "버번 위스키", "55%", "버번 매니아들의 열렬한 지지를 받는 훌륭한 바틀"),
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
            ("발베니 12년 더블우드", "싱글 몰트 스카치", "40%", "화사하고 달달한 꿀/바닐라 풍미의 정석"),
            ("글렌드로낙 12년", "싱글 몰트 스카치", "43%", "입문~중급용 셰리 캐스크의 교과서"),
            ("조니워커 그린", "블렌디드 몰트", "43%", "가성비와 퀄리티를 모두 잡은 15년 숙성 블렌딩"),
            ("이글레어 10년", "버번 위스키", "45%", "버팔로트레이스 증류소의 프리미엄 라인"),
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

# ── 위스키 상세(팝업용) ───────────────────────────────────────────────────────
# 각 술을 탭하면 뜨는 모달의 내용. 위키피디아 등 널리 문서화된 사실 기반.
# 필드: 증류소 / 지역 / 캐스크 / 스토리(증류소·제품 배경) / 출처.
# ⚠️ 확실치 않은 항목은 빈 문자열로 둔다(위장 금지, CMPA-1282 보드 주의). 키 = 제품명(TIERS와 정확히 일치).
DETAILS = {
    "글렌드로낙 21년": {
        "distillery": "글렌드로낙 (GlenDronach)", "region": "스코틀랜드 하이랜드",
        "cask": "올로로소 & 페드로 히메네즈(PX) 셰리 캐스크",
        "story": "1826년 설립된 하이랜드 증류소로, 셰리 캐스크 숙성에 특화돼 있다. "
                 "'Parliament(팔러먼트)'는 증류소 인근 나무에 무리 지어 사는 까마귀 떼를 부르는 "
                 "영어 표현(a parliament of rooks)에서 따온 이름이다. 21년은 진한 다크 프루츠와 "
                 "초콜릿, 스파이스가 층층이 쌓인 고숙성 셰리 몰트의 대표격이다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "글렌피딕 18년": {
        "distillery": "글렌피딕 (Glenfiddich)", "region": "스코틀랜드 스페이사이드 (더프타운)",
        "cask": "올로로소 셰리 & 버번 오크",
        "story": "1886년 윌리엄 그랜트가 세운 가족 경영 증류소로, 게일어로 '사슴의 계곡(Valley of the Deer)'을 뜻한다. "
                 "전 세계에서 가장 많이 팔리는 싱글 몰트 중 하나다. 18년은 셰리와 버번 오크에서 오래 숙성해 "
                 "잘 익은 사과와 오크 스파이스의 균형이 좋다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "글렌리벳 19년": {
        "distillery": "글렌리벳 (The Glenlivet)", "region": "스코틀랜드 스페이사이드",
        "cask": "",
        "story": "1824년 조지 스미스가 세운, 글렌리벳 교구 최초의 정식 면허 증류소다. 밀주가 성행하던 시대에 "
                 "합법 면허를 받아 위협에 시달렸고, 조지 스미스가 권총을 지니고 다닌 일화로 유명하다. "
                 "정규 라인을 벗어난 고숙성·고도수 바틀이다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "올트모어 18년": {
        "distillery": "올트모어 (Aultmore)", "region": "스코틀랜드 스페이사이드 (키스)",
        "cask": "",
        "story": "1896년 설립돼 오랫동안 듀어스 블렌드의 원액으로 쓰이다가 싱글 몰트로 알려졌다. "
                 "인근 습지 'Foggie Moss'의 전설과 함께, 깔끔하고 우아한 스타일로 정평이 나 있다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "아벨라워 아브나흐": {
        "distillery": "아벨라워 (Aberlour)", "region": "스코틀랜드 스페이사이드",
        "cask": "올로로소 셰리 벗 (논칠필터·캐스크 스트렝스)",
        "story": "'A'bunadh(아브나흐)'는 게일어로 '원래의, 근원'을 뜻한다. 올로로소 셰리 벗에서만 숙성해 "
                 "배치별로 캐스크 스트렝스·논칠필터로 병입하며, 숙성년수 표기가 없는(NAS) 진한 셰리 폭탄이다. "
                 "배치마다 도수가 조금씩 다르다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "옥토모어 15.1": {
        "distillery": "브룩라디 (Bruichladdich)", "region": "스코틀랜드 아일라",
        "cask": "아메리칸 위스키 캐스크",
        "story": "옥토모어는 브룩라디 증류소가 만드는 '세계에서 가장 강하게 피트한 위스키' 시리즈다. "
                 "15.1은 108.2 PPM의 압도적인 피트 수치를 지니면서도, 비교적 짧은 숙성으로 강렬한 스모크와 "
                 "젊은 힘을 동시에 낸다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "스테그 (Stagg)": {
        "distillery": "버팔로 트레이스 (Buffalo Trace)", "region": "미국 켄터키",
        "cask": "새 그을린 아메리칸 화이트 오크",
        "story": "19세기 위스키 사업가 조지 T. 스태그(George T. Stagg)의 이름을 딴 언컷·언필터드 캐스크 "
                 "스트렝스 버번이다. 물을 타지 않고 여과도 최소화해 높은 도수와 진한 풍미를 그대로 담으며, "
                 "물량이 적어 구하기 매우 어렵다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "일라이저 크레이그 18년": {
        "distillery": "헤븐 힐 (Heaven Hill)", "region": "미국 켄터키",
        "cask": "새 그을린 아메리칸 화이트 오크",
        "story": "이름은 오크통 내부를 그을려 버번을 '발명'했다는 전설의 침례교 목사 일라이저 크레이그에서 왔다. "
                 "18년은 버번으로서는 매우 긴 숙성의 싱글 배럴로, 희소성이 높다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "카발란 올로로소": {
        "distillery": "카발란 (Kavalan)", "region": "대만 이란현",
        "cask": "올로로소 셰리 캐스크 (싱글 캐스크·캐스크 스트렝스)",
        "story": "2005년 킹카 그룹이 세운 대만의 대표 증류소다. 아열대 기후에서 빠르게 숙성해 짧은 기간에도 "
                 "진한 풍미를 낸다. 'Solist' 시리즈는 단일 캐스크·캐스크 스트렝스로 병입하며, 올로로소는 "
                 "진한 건과일과 열대 과일 뉘앙스가 특징이다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "야마자키 12년": {
        "distillery": "산토리 야마자키 (Suntory Yamazaki)", "region": "일본 (오사카 인근)",
        "cask": "아메리칸·스패니시 오크 및 미즈나라(일본 오크)",
        "story": "1923년 토리이 신지로가 세운 일본 최초의 몰트 위스키 증류소다. 물이 좋기로 이름난 야마자키에 "
                 "자리했고, 미즈나라(일본 참나무) 캐스크가 주는 특유의 향으로 유명하다. 전 세계적 품귀로 "
                 "프리미엄이 높다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "기원 타이거 (Tiger)": {
        "distillery": "쓰리소사이어티스 (Three Societies)", "region": "대한민국 남양주",
        "cask": "",
        "story": "쓰리소사이어티스는 한국 최초의 싱글 몰트 증류소로, 첫 제품 '기원(Ki One)'을 선보였다. "
                 "'타이거'는 한정 에디션으로 수집 가치가 높다.",
        "source": "증류소 공식",
    },
    "발베니 12년 더블우드": {
        "distillery": "발베니 (The Balvenie)", "region": "스코틀랜드 스페이사이드 (더프타운)",
        "cask": "전통 오크 숙성 후 올로로소 셰리 캐스크 마감",
        "story": "윌리엄 그랜트 앤 선즈가 운영하며, 지금도 자체 몰팅(플로어 몰팅)을 유지하는 몇 안 되는 증류소다. "
                 "몰트 마스터 데이비드 스튜어트가 정립한 '캐스크 피니시' 기법의 상징이 바로 더블우드로, "
                 "버번 오크에서 숙성 후 셰리 캐스크로 옮겨 꿀·바닐라의 화사한 단맛을 얹는다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "글렌알라키 15년": {
        "distillery": "글렌알라키 (GlenAllachie)", "region": "스코틀랜드 스페이사이드",
        "cask": "PX & 올로로소 셰리 캐스크",
        "story": "1967년 설립됐고, 2017년 마스터 디스틸러 빌리 워커가 인수한 뒤 셰리 중심의 캐릭터로 크게 주목받았다. "
                 "15년은 진득한 셰리 풍미로 근래 가장 인기 있는 바틀 중 하나다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "매캘란 더블우드 12년": {
        "distillery": "매캘란 (The Macallan)", "region": "스코틀랜드 스페이사이드 (크레이겔라키)",
        "cask": "셰리 시즈닝한 유럽산·미국산 오크 (더블 캐스크)",
        "story": "1824년 설립, 셰리 오크 숙성의 대명사로 불리는 증류소다. 더블 캐스크 12년은 유럽·미국산 오크의 "
                 "셰리 시즈닝 캐스크를 함께 써 밸런스가 좋아, 싱글 몰트 입문·중급의 정석으로 꼽힌다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "글렌드로낙 12년": {
        "distillery": "글렌드로낙 (GlenDronach)", "region": "스코틀랜드 하이랜드",
        "cask": "PX & 올로로소 셰리 캐스크",
        "story": "1826년 설립된 셰리 캐스크 전문 증류소의 엔트리급 12년으로, 셰리 캐스크 위스키의 교과서로 통한다. "
                 "부드러운 건포도·초콜릿 풍미가 입문에 좋다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "에버펠디 16년": {
        "distillery": "에버펠디 (Aberfeldy)", "region": "스코틀랜드 하이랜드 (퍼스셔)",
        "cask": "",
        "story": "1896년 존 듀어 앤 선즈가 세워 듀어스 블렌드의 심장부 역할을 해 온 증류소다. "
                 "꿀 같은 달콤함으로 '골든 드램'이라 불리며, 16년은 부드럽고 원숙한 편이다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "로얄 브라크라 12년": {
        "distillery": "로얄 브라크라 (Royal Brackla)", "region": "스코틀랜드 하이랜드",
        "cask": "올로로소 셰리 피니시",
        "story": "1812년 설립됐고, 1835년 윌리엄 4세로부터 위스키 최초의 왕실 인증(로열 워런트)을 받아 "
                 "'The King's Own Whisky'로 불렸다. 올로로소 셰리 피니시로 고급스럽고 우아한 맛을 낸다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "부나하벤 12년": {
        "distillery": "부나하벤 (Bunnahabhain)", "region": "스코틀랜드 아일라",
        "cask": "셰리 & 버번 캐스크 (논칠필터)",
        "story": "1881년 설립. 강한 피트로 유명한 아일라에서 이례적으로 피트가 거의 없는 스타일을 대표한다. "
                 "12년은 논칠필터·무착색으로 병입돼 훌륭한 바디감과 견과·건과일 풍미를 낸다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "조니워커 그린": {
        "distillery": "조니워커 (Johnnie Walker) · 디아지오", "region": "스코틀랜드 (블렌디드 몰트)",
        "cask": "",
        "story": "그린 라벨은 그레인 없이 여러 싱글 몰트만 섞은 15년 숙성 블렌디드 몰트다. 탈리스커·크라간모어 등 "
                 "성격이 다른 몰트들을 조화시켜 가성비와 퀄리티를 함께 잡았다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "러셀 리저브 싱글배럴": {
        "distillery": "와일드 터키 (Wild Turkey)", "region": "미국 켄터키",
        "cask": "새 그을린 아메리칸 화이트 오크 (싱글 배럴)",
        "story": "와일드 터키의 전설적 마스터 디스틸러 부자(父子) 지미 러셀·에디 러셀의 이름을 딴 라인이다. "
                 "단일 배럴에서 병입해 진한 풍미와 타격감으로 버번 매니아들의 지지를 받는다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "이글레어 10년": {
        "distillery": "버팔로 트레이스 (Buffalo Trace)", "region": "미국 켄터키",
        "cask": "새 그을린 아메리칸 화이트 오크 (싱글 배럴)",
        "story": "버팔로 트레이스 증류소의 프리미엄 싱글 배럴 버번으로, 10년 숙성이다. 바닐라·오크·토피의 "
                 "부드러운 균형으로 이름난 스테디셀러다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "와일드터키 레어브리드 라이": {
        "distillery": "와일드 터키 (Wild Turkey)", "region": "미국 켄터키",
        "cask": "새 그을린 아메리칸 화이트 오크 (배럴 프루프)",
        "story": "여러 숙성년수의 라이를 섞어 물을 거의 타지 않고 배럴 프루프로 병입한다. 라이 특유의 스파이스와 "
                 "높은 도수의 타격감, 풍미가 일품이다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "사가모어 라이 CS": {
        "distillery": "사가모어 스피릿 (Sagamore Spirit)", "region": "미국 메릴랜드 볼티모어",
        "cask": "새 그을린 아메리칸 화이트 오크 (캐스크 스트렝스)",
        "story": "메릴랜드 스타일 라이의 부활을 이끄는 볼티모어 증류소다. 캐스크 스트렝스 버전은 강렬한 타격감과 "
                 "진한 화사함이 특징이다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "탈리스커 10년": {
        "distillery": "탈리스커 (Talisker)", "region": "스코틀랜드 스카이 섬",
        "cask": "",
        "story": "1830년 설립된, 오랫동안 스카이 섬 유일의 증류소였다. '바다가 빚은 위스키'라는 말처럼 짭조름한 "
                 "바다향과 후추 같은 스파이시함이 상징이다. 10년은 그 캐릭터의 정석이다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "아드벡 10년": {
        "distillery": "아드벡 (Ardbeg)", "region": "스코틀랜드 아일라",
        "cask": "버번 캐스크 (논칠필터)",
        "story": "1815년 설립된 아일라의 대표 피트 증류소다. 강한 피트에도 시트러스·바닐라의 균형이 좋아 "
                 "'가장 완성도 높은 피트 위스키' 중 하나로 꼽힌다. 논칠필터로 병입한다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "라프로익 쿼터 캐스크": {
        "distillery": "라프로익 (Laphroaig)", "region": "스코틀랜드 아일라",
        "cask": "버번 캐스크 후 작은 쿼터 캐스크 추가 숙성 (논칠필터)",
        "story": "1815년 설립. 소독약·요오드에 비유되는 개성 강한 피트로 유명하다. 쿼터 캐스크는 작은 오크통에서 "
                 "추가 숙성해 나무·피트 향을 강하게 농축한 NAS 버전이다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "스카라버스 CS 피티드": {
        "distillery": "헌터 레잉 (Hunter Laing) 병입 · 아일라", "region": "스코틀랜드 아일라",
        "cask": "",
        "story": "'스카라버스(Scarabus)'는 증류소명을 밝히지 않는 아일라 싱글 몰트로, 헌터 레잉이 병입한다. "
                 "캐스크 스트렝스 버전은 높은 도수의 가성비 피트로 평가받는다.",
        "source": "병입사 공식",
    },
    "폴존 피티드 CS": {
        "distillery": "폴 존 (Paul John)", "region": "인도 고아",
        "cask": "캐스크 스트렝스",
        "story": "인도 고아의 아열대 기후에서 숙성하는 인디안 싱글 몰트다. 빠른 숙성으로 진한 풍미를 내며, "
                 "피티드 캐스크 스트렝스는 강한 피트와 높은 도수의 자극이 특징이다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "엔젤스 엔비 스몰배치": {
        "distillery": "엔젤스 엔비 (Angel's Envy)", "region": "미국 켄터키 루이빌",
        "cask": "버번 숙성 후 포트 와인 캐스크 마감",
        "story": "전설적 마스터 디스틸러 링컨 헨더슨이 만든 브랜드로, 버번을 포트 와인 캐스크에서 마감해 "
                 "달콤함을 더한다. 이름은 숙성 중 증발하는 '천사의 몫(Angel's Share)'에서 착안했다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "놉크릭 9년": {
        "distillery": "짐 빔 (Jim Beam)", "region": "미국 켄터키",
        "cask": "새 그을린 아메리칸 화이트 오크 (스몰배치)",
        "story": "짐 빔의 스몰배치 컬렉션 중 하나로, 이름은 링컨 대통령이 어린 시절 살던 '놉 크릭'에서 왔다. "
                 "묵직하고 진한 견과·오크 풍미가 특징이다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "일라이저 크레이그 스몰배치": {
        "distillery": "헤븐 힐 (Heaven Hill)", "region": "미국 켄터키",
        "cask": "새 그을린 아메리칸 화이트 오크 (스몰배치)",
        "story": "버번을 '발명'했다는 전설의 목사 일라이저 크레이그에서 이름을 딴 스몰배치 버번이다. "
                 "우디함과 바닐라의 정석적인 균형으로 데일리 버번의 표준으로 꼽힌다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "LOT 40": {
        "distillery": "하이람 워커 (Hiram Walker) · 코비", "region": "캐나다",
        "cask": "",
        "story": "100% 호밀(라이)을 단식 증류기로 내린 캐네디언 라이의 대표작이다. 호밀빵·허브 같은 라이 특유의 "
                 "화사함이 또렷하다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "몽키숄더": {
        "distillery": "윌리엄 그랜트 앤 선즈 (William Grant & Sons)", "region": "스코틀랜드 (블렌디드 몰트)",
        "cask": "",
        "story": "글렌피딕·발베니·키닌비 등 스페이사이드 몰트를 섞은 블렌디드 몰트다. 이름은 예전 몰트맨들이 "
                 "보리를 삽으로 뒤집다 어깨가 처지던 직업병('monkey shoulder')에서 왔다. 달콤·부드러워 "
                 "하이볼과 입문용으로 최적이다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "닛카 프론티어": {
        "distillery": "닛카 (Nikka)", "region": "일본",
        "cask": "",
        "story": "닛카는 '일본 위스키의 아버지' 타케츠루 마사타카가 세운 회사로, 요이치·미야기쿄 증류소를 운영한다. "
                 "프론티어는 몰트 원액을 넉넉히 담아 피트감과 48도의 탄탄함으로 하이볼 기주로 잘 어울린다.",
        "source": "위키피디아 · 증류소 공식",
    },
    "제임슨": {
        "distillery": "미들턴 (Midleton) · 아이리시 디스틸러스", "region": "아일랜드",
        "cask": "버번 & 셰리 캐스크",
        "story": "1780년 존 제임슨이 더블린에서 시작한, 전 세계에서 가장 많이 팔리는 아이리시 위스키다. "
                 "세 번 증류(트리플 디스틸)해 부드럽고 깔끔한 맛이 특징이며, 지금은 미들턴 증류소에서 만든다.",
        "source": "위키피디아 · 증류소 공식",
    },
}

PAGE_CSS = """*{box-sizing:border-box}
body{margin:0;background:#0f1115;color:#e8eaed;
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif;
 line-height:1.55;font-size:16px;-webkit-text-size-adjust:100%}
.wrap{max-width:680px;margin:0 auto;padding:10px 12px 40px}
header{text-align:center;margin:0 0 2px}
h1{font-size:1.32rem;margin:.15em 0;color:#e8eaed}
h1 .gold{color:#e0a84e}
/* ── 티어 탭 (한 번에 한 티어만) · 상단 고정 ── */
.tabs{position:sticky;top:0;z-index:20;display:flex;gap:6px;background:#0f1115;
 padding:8px 0 7px;margin:4px 0 0;border-bottom:1px solid #20242e}
.tab{flex:1;background:#141821;border:1px solid #20242e;border-radius:10px;color:#cdd2da;
 font:inherit;font-size:.9rem;font-weight:700;padding:7px 4px;cursor:pointer;line-height:1.2;
 -webkit-tap-highlight-color:transparent;transition:border-color .15s,background .15s,color .15s}
.tab b{font-size:.72rem;font-weight:600;color:#6b7280;margin-left:.3em}
.tab.active{border-color:#e0a84e;background:#1a1508;color:#e0a84e}
.tab.active b{color:#e0a84e}
.tier{display:none;margin-top:8px;scroll-margin-top:8px}
.tier.active{display:block}
.thead{border-bottom:1px solid #2a2e37;padding-bottom:.35em;margin-bottom:2px}
.tname{color:#e0a84e;font-size:1rem;font-weight:700}
.tsub{color:#9aa0aa;font-size:.78rem;margin-top:.1em}
.tserve{color:#9aa0aa;font-size:.75rem;margin-top:.3em}
.tcount{color:#6b7280;font-size:.76rem;font-weight:600}
/* ── 한 줄 목록 (이름 + 도수) · 탭하면 상세 팝업, ＋ 누르면 기록 ── */
.list{display:flex;flex-direction:column}
.row{display:flex;align-items:center;gap:8px;border-bottom:1px solid #1c202a}
.rtap{display:flex;align-items:center;justify-content:space-between;gap:10px;flex:1;min-width:0;
 text-align:left;color:inherit;font:inherit;background:transparent;border:0;padding:8px 2px;cursor:pointer;
 -webkit-tap-highlight-color:transparent;transition:background .12s}
.rtap:hover,.rtap:focus-visible{background:#171c26;outline:none}
.radd{flex:none;background:#1a1508;border:1px solid #3a2f1a;color:#e0a84e;
 width:36px;height:36px;border-radius:9px;font-size:1.35rem;font-weight:700;line-height:1;
 cursor:pointer;-webkit-tap-highlight-color:transparent;transition:transform .1s,background .12s,color .12s}
.radd:active{transform:scale(.84)}
.radd.added{background:#e0a84e;color:#1a1508;transform:scale(1.05)}
.rmain{display:flex;flex-direction:column;gap:1px;min-width:0}
.rname{font-weight:600;font-size:.95rem;line-height:1.3;word-break:keep-all}
.rcat{color:#8a909a;font-size:.72rem;line-height:1.3}
.rabv{color:#e0a84e;font-size:.85rem;font-weight:700;white-space:nowrap;font-variant-numeric:tabular-nums;flex:none}
.note{margin:20px 0 0;color:#8a909a;font-size:.78rem;text-align:center;line-height:1.6}
footer{margin-top:18px;text-align:center;color:#5b616b;font-size:.73rem;line-height:1.6}
/* ── 상세 팝업(모달) — 모바일 우선 바텀시트, 데스크톱에선 가운데 카드 ── */
/* 카톡/구형 안드로이드 웹뷰 검은화면·버벅임 방지 — blur 대신 반투명 rgba 만 사용(CLAUDE.md). */
.mask{position:fixed;inset:0;background:rgba(6,8,11,.82);
 display:none;z-index:50;align-items:flex-end;justify-content:center}
.mask.open{display:flex}
.modal{background:#141821;border:1px solid #2a2e37;width:100%;max-width:560px;
 border-radius:18px 18px 0 0;max-height:88vh;max-height:88dvh;overflow-y:auto;-webkit-overflow-scrolling:touch;
 padding:20px 18px calc(22px + max(env(safe-area-inset-bottom), 12px));
 box-shadow:0 -12px 40px rgba(0,0,0,.5);animation:slideup .22s ease}
@keyframes slideup{from{transform:translateY(24px);opacity:.4}to{transform:translateY(0);opacity:1}}
.mgrip{width:38px;height:4px;border-radius:999px;background:#2a2e37;margin:0 auto 14px}
.mtop{display:flex;align-items:flex-start;gap:10px}
.mname{font-size:1.28rem;font-weight:800;line-height:1.3;flex:1}
.mx{flex:none;background:#20242e;border:none;color:#cdd2da;width:32px;height:32px;border-radius:50%;
 font-size:1.1rem;cursor:pointer;line-height:1}
.mx:hover{background:#2a2e37}
.mtags{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0 4px}
.tag{font-size:.76rem;padding:.24em .7em;border-radius:999px;border:1px solid #2a2e37;color:#cdd2da;background:#0f1115}
.tag.gold{color:#e0a84e;border-color:#3a2f1a;background:#1a1508}
.mgrid{margin:14px 0 2px;border-top:1px solid #20242e}
.mrow{display:flex;gap:12px;padding:9px 0;border-bottom:1px solid #20242e;font-size:.9rem}
.mrow .k{color:#9aa0aa;flex:0 0 68px}
.mrow .v{color:#e8eaed;flex:1}
.msec{margin-top:16px}
.msec h4{color:#e0a84e;font-size:.82rem;letter-spacing:.02em;margin:0 0 .5em;text-transform:none}
.msec p{margin:0;color:#cdd2da;font-size:.94rem;line-height:1.65}
.msrc{margin-top:16px;color:#6b7280;font-size:.74rem}
/* ── 구글 이미지 검색 버튼 (상세 팝업 하단) ── */
.mgoogle{display:flex;align-items:center;justify-content:center;gap:8px;margin-top:18px;
 background:#1a1508;border:1px solid #3a2f1a;color:#e0a84e;border-radius:12px;padding:12px;
 font-size:.92rem;font-weight:700;text-decoration:none;-webkit-tap-highlight-color:transparent;
 transition:background .12s,transform .1s}
.mgoogle:hover{background:#221a0a}
.mgoogle:active{transform:scale(.98)}
/* ── 플로팅 '내 기록' 버튼 · 토스트 · 기록 목록 ── */
.fab{position:fixed;right:14px;bottom:calc(14px + max(env(safe-area-inset-bottom), 12px));z-index:40;
 display:flex;align-items:center;gap:8px;background:#e0a84e;color:#0f1115;border:none;border-radius:999px;
 padding:11px 16px;font:inherit;font-weight:800;font-size:.9rem;cursor:pointer;
 box-shadow:0 6px 20px rgba(0,0,0,.45);-webkit-tap-highlight-color:transparent}
.fab .cnt{background:#0f1115;color:#e0a84e;border-radius:999px;padding:1px 8px;min-width:22px;
 text-align:center;font-size:.82rem;font-variant-numeric:tabular-nums}
.toast{position:fixed;left:50%;bottom:calc(74px + max(env(safe-area-inset-bottom), 12px));
 transform:translateX(-50%) translateY(10px);background:#1a1508;color:#e0a84e;border:1px solid #3a2f1a;
 border-radius:10px;padding:9px 16px;font-size:.86rem;font-weight:600;white-space:nowrap;
 opacity:0;pointer-events:none;transition:opacity .2s,transform .2s;z-index:60}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
.logempty{color:#8a909a;font-size:.9rem;text-align:center;line-height:1.7;margin:28px 0}
.logsum{color:#9aa0aa;font-size:.82rem;margin:10px 0 4px}
.logday{margin-top:14px}
.logdate{color:#e0a84e;font-size:.86rem;font-weight:700;border-bottom:1px solid #20242e;padding-bottom:.3em}
.logdate span{color:#6b7280;font-weight:600;font-size:.78rem}
.logrow{display:flex;align-items:center;justify-content:space-between;gap:10px;
 padding:8px 2px}
.lgname{font-size:.92rem}
.lgabv{color:#e0a84e;font-size:.8rem;font-weight:700;margin-left:.5em;font-variant-numeric:tabular-nums}
.lgbtns{display:flex;gap:6px;flex:none}
.lgmemo{flex:none;background:#20242e;border:none;color:#9aa0aa;width:28px;height:28px;border-radius:7px;
 font-size:.85rem;cursor:pointer;line-height:1;-webkit-tap-highlight-color:transparent}
.lgmemo:hover{background:#2a2e37;color:#e0a84e}
.lgmemo.has{background:#1a1508;color:#e0a84e;border:1px solid #3a2f1a}
.lgx{flex:none;background:#20242e;border:none;color:#9aa0aa;width:28px;height:28px;border-radius:7px;
 font-size:.9rem;cursor:pointer;line-height:1;-webkit-tap-highlight-color:transparent}
.lgx:hover{background:#3a2222;color:#e88}
/* ── 기록 메모 (담은 위스키에 남기는 한줄 메모) ── */
.lgmemotext{color:#cdd2da;font-size:.84rem;line-height:1.55;padding:0 2px 9px;
 border-bottom:1px solid #171c26;white-space:pre-wrap;word-break:break-word}
.lgmemotext::before{content:"✏️ ";opacity:.7}
.lgedit{padding:2px 2px 11px;border-bottom:1px solid #171c26}
.lgedit textarea{width:100%;box-sizing:border-box;max-width:100%;min-width:0;background:#0f1115;border:1px solid #2a2e37;border-radius:8px;color:#e8eaed;
 font:inherit;font-size:.86rem;padding:8px;resize:vertical;min-height:52px;display:block}
.lgeditbtns{display:flex;gap:8px;margin-top:6px}
.lgsave{background:#e0a84e;color:#1a1508;border:none;border-radius:8px;padding:6px 16px;
 font:inherit;font-weight:700;font-size:.82rem;cursor:pointer}
.lgcancel{background:transparent;color:#9aa0aa;border:1px solid #2a2e37;border-radius:8px;
 padding:6px 16px;font:inherit;font-size:.82rem;cursor:pointer}
.logclear{display:block;width:100%;margin-top:20px;background:transparent;border:1px solid #3a2222;
 color:#c98;border-radius:10px;padding:10px;font:inherit;font-size:.86rem;cursor:pointer}
.logclear:hover{background:#2a1616}
@media(min-width:600px){.mask{align-items:center}.modal{border-radius:18px}.mgrip{display:none}}"""


def _origin(name: str, cat: str) -> str:
    """카드 앞면에 노출할 짧은 '원산지/증류소' 라벨 — region의 국가·지역 (괄호 상세 제거)."""
    region = DETAILS.get(name, {}).get("region", "")
    if region:
        return region.split("(")[0].strip()
    return cat


def _card(key: str, item: tuple[str, str, str, str]) -> str:
    name, cat, abv, notes = item
    e = html.escape
    return f'<div class="row">' \
           f'<button type="button" class="rtap" data-w="{e(key)}">' \
           f'<span class="rmain"><span class="rname">{e(name)}</span>' \
           f'<span class="rcat">{e(cat)}</span></span>' \
           f'<span class="rabv">{e(abv)}</span></button>' \
           f'<button type="button" class="radd" data-w="{e(key)}" ' \
           f'aria-label="{e(name)} 마신 목록에 담기" title="마신 목록에 담기">＋</button>' \
           f'</div>'


def _tabs() -> str:
    e = html.escape
    btns = []
    for i, t in enumerate(TIERS):
        cls = "tab active" if i == 0 else "tab"
        n = len(t["items"])
        btns.append(
            f'<button type="button" class="{cls}" data-tier="{e(t["id"])}">'
            f'{e(t["medal"])} {i + 1}티어<b>{n}종</b></button>'
        )
    return '<div class="tabs" role="tablist">' + "".join(btns) + "</div>"


def _tier_section(tier: dict, keys: dict, active: bool) -> str:
    e = html.escape
    cards = "\n  ".join(_card(keys[id(x)], x) for x in tier["items"])
    n = len(tier["items"])
    cls = "tier active" if active else "tier"
    return f"""<section class="{cls}" id="{e(tier['id'])}" role="tabpanel">
  <div class="thead">
    <div class="tname">{e(tier['medal'])} {e(tier['name'])} <span class="tcount">· {n}종</span></div>
    <div class="tserve">{e(tier['serve'])}</div>
  </div>
  <div class="list">
  {cards}
  </div>
</section>"""


def _build_data(keys: dict) -> dict:
    """카드 key → 팝업에 뿌릴 상세 데이터(JS). DETAILS에 없거나 빈 값은 생략(위장 금지)."""
    data = {}
    for tier in TIERS:
        for item in tier["items"]:
            name, cat, abv, notes = item
            d = DETAILS.get(name, {})
            data[keys[id(item)]] = {
                "name": name, "cat": cat, "abv": abv, "notes": notes,
                "tier": tier["name"],
                "distillery": d.get("distillery", ""),
                "region": d.get("region", ""),
                "cask": d.get("cask", ""),
                "story": d.get("story", ""),
                "source": d.get("source", ""),
            }
    return data


MODAL_JS = """(function(){
 var data=window.__WIMAKASE__||{};
 var mask=document.getElementById('mask');
 var m=document.getElementById('mbody');
 var last=null;
 function esc(s){var d=document.createElement('div');d.textContent=s==null?'':s;return d.innerHTML;}
 function row(k,v){return v?'<div class="mrow"><span class="k">'+k+'</span><span class="v">'+esc(v)+'</span></div>':'';}
 function open(key){
  var d=data[key];if(!d)return;
  var h='<div class="mtop"><div class="mname">'+esc(d.name)+'</div>'+
        '<button type="button" class="mx" aria-label="닫기" onclick="__wmClose()">✕</button></div>'+
        '<div class="mtags"><span class="tag gold">'+esc(d.abv)+' ABV</span>'+
        '<span class="tag">'+esc(d.cat)+'</span>'+
        (d.tier?'<span class="tag">'+esc(d.tier)+'</span>':'')+'</div>'+
        '<div class="mgrid">'+row('증류소',d.distillery)+row('지역',d.region)+
        row('캐스크',d.cask)+row('도수',d.abv)+row('분류',d.cat)+'</div>';
  if(d.notes)h+='<div class="msec"><h4>특징</h4><p>'+esc(d.notes)+'</p></div>';
  if(d.story)h+='<div class="msec"><h4>스토리</h4><p>'+esc(d.story)+'</p></div>';
  h+='<a class="mgoogle" href="https://www.google.com/search?tbm=isch&q='+encodeURIComponent(d.name+' 위스키')+'" target="_blank" rel="noopener">🔍 구글 이미지로 사진 보기</a>';
  if(d.source)h+='<div class="msrc">출처 · '+esc(d.source)+' (요약) · 수집 '+esc(window.__WM_COLLECTED__||'')+'</div>';
  m.innerHTML=h;
  mask.classList.add('open');document.body.style.overflow='hidden';
  m.parentNode.scrollTop=0;
 }
 window.__wmClose=function(){mask.classList.remove('open');document.body.style.overflow='';
  if(last){last.focus();last=null;}};
 document.querySelectorAll('button.rtap').forEach(function(b){
  b.addEventListener('click',function(){last=b;open(b.getAttribute('data-w'));});
 });
 mask.addEventListener('click',function(e){if(e.target===mask)window.__wmClose();});
 document.addEventListener('keydown',function(e){if(e.key==='Escape'&&mask.classList.contains('open'))window.__wmClose();});
})();"""


TAB_JS = """(function(){
 var tabs=document.querySelectorAll('.tab');
 var tiers=document.querySelectorAll('.tier');
 tabs.forEach(function(t){
  t.addEventListener('click',function(){
   var id=t.getAttribute('data-tier');
   tabs.forEach(function(x){x.classList.toggle('active',x===t);});
   tiers.forEach(function(s){s.classList.toggle('active',s.id===id);});
  });
 });
})();"""


# ── '내가 마신 목록' — ＋ 버튼으로 그날 마신 술을 날짜와 함께 localStorage에 기록 ──
LOG_JS = """(function(){
 var LS='wm_log_v1';
 var data=window.__WIMAKASE__||{};
 var fab=document.getElementById('fab');
 var cnt=document.getElementById('fabcnt');
 var mask=document.getElementById('logmask');
 var body=document.getElementById('logbody');
 var toastEl=document.getElementById('toast');var toastT=null;
 var editing=null;
 // iOS/카톡 웹뷰 키보드 보정 — 메모 편집 시 바텀시트를 VisualViewport(키보드 위) 높이에 맞춰
 // 하단이 키보드에 가리지 않게 한다(CLAUDE.md 카톡 웹뷰 원칙).
 var vv=window.visualViewport;
 function vvFit(){
  if(!vv)return;
  if(mask.classList.contains('open')){
   mask.style.top=vv.offsetTop+'px';mask.style.bottom='auto';mask.style.height=vv.height+'px';
  }else{mask.style.top='';mask.style.bottom='';mask.style.height='';}
 }
 if(vv){vv.addEventListener('resize',vvFit);vv.addEventListener('scroll',vvFit);}
 function load(){try{return JSON.parse(localStorage.getItem(LS))||[];}catch(e){return [];}}
 function save(a){try{localStorage.setItem(LS,JSON.stringify(a));}catch(e){}}
 function today(){var d=new Date(),m=('0'+(d.getMonth()+1)).slice(-2),dd=('0'+d.getDate()).slice(-2);
  return d.getFullYear()+'-'+m+'-'+dd;}
 function esc(s){var x=document.createElement('div');x.textContent=s==null?'':s;return x.innerHTML;}
 function updateFab(){cnt.textContent=load().length;}
 function toast(msg){toastEl.textContent=msg;toastEl.classList.add('show');
  if(toastT)clearTimeout(toastT);toastT=setTimeout(function(){toastEl.classList.remove('show');},1400);}
 function add(key){
  var d=data[key];if(!d)return;
  var a=load();a.push({k:key,name:d.name,cat:d.cat,abv:d.abv,date:today()});save(a);
  updateFab();toast('담김 · '+d.name);
 }
 window.__wmRemove=function(i){var a=load();a.splice(i,1);save(a);editing=null;updateFab();renderLog();};
 window.__wmClearLog=function(){if(!confirm('내가 마신 목록을 모두 지울까요?'))return;
  save([]);editing=null;updateFab();renderLog();};
 window.__wmMemo=function(i){editing=(editing===i?null:i);renderLog();};
 window.__wmMemoCancel=function(){editing=null;renderLog();};
 window.__wmMemoSave=function(i){var ta=document.getElementById('lgmemoinput');
  var v=ta?ta.value.trim():'';var a=load();if(a[i]){a[i].memo=v;save(a);}editing=null;renderLog();};
 function renderLog(){
  var a=load();
  var h='<div class="mtop"><div class="mname">📒 내가 마신 목록</div>'+
        '<button type="button" class="mx" aria-label="닫기" onclick="__wmCloseLog()">✕</button></div>';
  if(!a.length){h+='<p class="logempty">아직 담은 위스키가 없습니다.<br>'+
    '메뉴에서 각 위스키 옆 ＋ 를 눌러 그날 마신 술을 기록하세요.<br>'+
    '담은 뒤 ✏️ 를 눌러 맛·느낌 메모를 남길 수 있어요.</p>';body.innerHTML=h;return;}
  var byDate={},order=[];
  a.forEach(function(e,i){if(!byDate[e.date]){byDate[e.date]=[];order.push(e.date);}
   byDate[e.date].push({e:e,i:i});});
  order.sort().reverse();
  h+='<div class="logsum">총 '+a.length+'잔 · '+order.length+'일 기록</div>';
  order.forEach(function(dt){
   h+='<div class="logday"><div class="logdate">'+esc(dt)+' <span>('+byDate[dt].length+'잔)</span></div>';
   byDate[dt].forEach(function(o){
    var e=o.e,i=o.i,memo=e.memo||'';
    h+='<div class="logrow"><span class="lgname">'+esc(e.name)+
       '<span class="lgabv">'+esc(e.abv)+'</span></span><div class="lgbtns">'+
       '<button type="button" class="lgmemo'+(memo?' has':'')+'" aria-label="메모" '+
       'title="메모" onclick="__wmMemo('+i+')">✏️</button>'+
       '<button type="button" class="lgx" aria-label="삭제" onclick="__wmRemove('+i+')">✕</button>'+
       '</div></div>';
    if(editing===i){
     h+='<div class="lgedit"><textarea id="lgmemoinput" '+
        'placeholder="이 위스키의 맛·향·느낌을 메모하세요">'+esc(memo)+'</textarea>'+
        '<div class="lgeditbtns"><button type="button" class="lgsave" '+
        'onclick="__wmMemoSave('+i+')">저장</button>'+
        '<button type="button" class="lgcancel" onclick="__wmMemoCancel()">취소</button></div></div>';
    }else if(memo){
     h+='<div class="lgmemotext">'+esc(memo)+'</div>';
    }
   });
   h+='</div>';
  });
  h+='<button type="button" class="logclear" onclick="__wmClearLog()">전체 지우기</button>';
  body.innerHTML=h;
  if(editing!==null){var ta=document.getElementById('lgmemoinput');
   if(ta){ta.focus();ta.setSelectionRange(ta.value.length,ta.value.length);
    setTimeout(function(){try{ta.scrollIntoView({block:'center'});}catch(e){}vvFit();},300);}}
 }
 function openLog(){editing=null;renderLog();mask.classList.add('open');document.body.style.overflow='hidden';
  var md=mask.querySelector('.modal');if(md)md.scrollTop=0;vvFit();}
 window.__wmCloseLog=function(){mask.classList.remove('open');document.body.style.overflow='';vvFit();};
 fab.addEventListener('click',openLog);
 mask.addEventListener('click',function(e){if(e.target===mask)window.__wmCloseLog();});
 document.addEventListener('keydown',function(e){
  if(e.key==='Escape'&&mask.classList.contains('open'))window.__wmCloseLog();});
 document.querySelectorAll('button.radd').forEach(function(b){
  b.addEventListener('click',function(ev){ev.stopPropagation();add(b.getAttribute('data-w'));
   b.classList.add('added');setTimeout(function(){b.classList.remove('added');},260);});
 });
 updateFab();
})();"""


def _next_build() -> int:
    """빌드 카운터를 1 증가시켜 반환(발행마다 캐시버스트 쿼리·라벨이 달라지게)."""
    try:
        n = int(BUILD_FILE.read_text(encoding="utf-8").strip())
    except Exception:
        n = 0
    n += 1
    BUILD_FILE.write_text(f"{n}\n", encoding="utf-8")
    return n


def render(build: int) -> str:
    e = html.escape
    cache_tag = f"{VERSION}-b{build}"  # 예: v2026.08.16-b3 (발행마다 증가)
    # 각 아이템 객체에 안정적인 key(w1..wN) 부여 — id() 로 매핑
    keys, n = {}, 0
    for tier in TIERS:
        for item in tier["items"]:
            n += 1
            keys[id(item)] = f"w{n}"
    tabs_html = _tabs()
    tiers_html = "\n".join(_tier_section(t, keys, i == 0) for i, t in enumerate(TIERS))
    data_json = json.dumps(_build_data(keys), ensure_ascii=False)
    collected_json = json.dumps(COLLECTED, ensure_ascii=False)
    total = sum(len(t["items"]) for t in TIERS)
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<!-- 캐시버스트(CMPA-1285): 카톡/iOS 웹뷰가 옛 버전을 붙잡지 않게 no-cache 신호 + 빌드 라벨 {e(cache_tag)} -->
<meta http-equiv="Cache-Control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="Pragma" content="no-cache">
<meta http-equiv="Expires" content="0">
<meta name="build" content="{e(cache_tag)}">
<link rel="canonical" href="wimakase.html?v={e(cache_tag)}">
<title>{e(TITLE)} · 위스키 메뉴 {e(VERSION)}</title>
<meta name="description" content="{e(TITLE)} 위스키 바 메뉴 — 3티어 {total}종. 1·2티어 테이스팅 200ml + 3티어 프리플로우. {e(VERSION)}">
<style>
{PAGE_CSS}
</style>
</head>
<body><div class="wrap">
<header>
  <h1>합정 두다지 <span class="gold">위마카세</span></h1>
</header>

{tabs_html}
{tiers_html}

<p class="note">위스키를 탭하면 상세·구글 이미지 검색이 열리고, 옆의 ＋ 를 누르면 그날 마신 목록에 담깁니다 · 📒 내 기록에서 ✏️ 로 메모도 남길 수 있어요 · 테이스팅 각 20ml</p>

<footer>합정 위마카세 · 메뉴 {e(VERSION)} &nbsp;·&nbsp; CaskCode<br>메뉴는 수시로 업데이트됩니다 — 버전을 확인하세요 🥃<br>상세 정보는 위키피디아 등 공개 자료를 요약한 참고용입니다 · 수집 {e(COLLECTED)}<br><span style="color:#3b414b;font-size:.68rem">build {e(cache_tag)}</span></footer>
</div>

<div class="mask" id="mask" role="dialog" aria-modal="true" aria-label="위스키 상세">
  <div class="modal"><div class="mgrip"></div><div id="mbody"></div></div>
</div>

<button type="button" class="fab" id="fab" aria-label="내가 마신 목록 열기">📒 내 기록 <span class="cnt" id="fabcnt">0</span></button>
<div class="toast" id="toast" role="status" aria-live="polite"></div>
<div class="mask" id="logmask" role="dialog" aria-modal="true" aria-label="내가 마신 목록">
  <div class="modal"><div class="mgrip"></div><div id="logbody"></div></div>
</div>

<script>window.__WIMAKASE__={data_json};window.__WM_COLLECTED__={collected_json};</script>
<script>
{MODAL_JS}
{TAB_JS}
{LOG_JS}
</script>
</body>
</html>
"""


def build() -> tuple[list[Path], int]:
    build_no = _next_build()
    doc = render(build_no)
    outs = [
        ROOT / "blog-md" / "wimakase.html",
        ROOT / "deploy" / "menu" / "wimakase" / "index.html",
    ]
    written = []
    for p in outs:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(doc, encoding="utf-8")
        written.append(p)
    return written, build_no


if __name__ == "__main__":
    paths, build_no = build()
    total = sum(len(t["items"]) for t in TIERS)
    print(f"built 합정 위마카세 {VERSION}-b{build_no} — {total}종 ({', '.join(str(len(t['items'])) for t in TIERS)})")
    for p in paths:
        print(f"  {p.relative_to(ROOT)}")
