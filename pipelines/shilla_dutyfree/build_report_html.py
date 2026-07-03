#!/usr/bin/env python3
"""면세점 위스키 추천 리포트 → 발행용 HTML 생성 (모바일 우선·탭·스토리 펼침·상품링크).

- 탭: ①국내파 ②여행파 ③취향파 ④선물파
- 상품명 클릭 → 신라면세 상품 페이지 새 탭
- 선물파 스토리 클릭(▾) → 상세 펼침(<details>)
- 데이터는 CMPA-130 콘텐츠 초안(데일리샷 실측 국내최저 기준) + 선물 스토리(CMPA-137)

출력: reports/shilla-dutyfree/면세위스키_리포트_<date>.html

의존성(CMPA-235): 이 리포트의 <date> 는 신라 오늘자 raw CSV `신라면세_위스키_<date>.csv`
수집을 단일 진실로 한다. SHILLA_DATE 미설정 시 latest_date() 는 **raw CSV 가 실재하는**
가장 최신 날짜만 고른다(JSON 만 잔존하는 날짜로 폴백해 stale-date 리포트를 내지 않음).
오케스트레이터 run_shilla_pipeline.py 가 report 전에 raw 수집을 강제한다.
"""
import html
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
P = "https://www.shilladfs.com/estore/kr/ko/p/"

# CMPA-141: 가격은 refresh_report_prices.py 가 만든 JSON(라이브)에서 로드한다.
# 픽 튜플의 가격(면세·국내·이득)은 JSON 미존재(코드 없음/리프레시 전) 시 폴백.
PRICES = {}        # 상품코드 -> {면세,국내,이득,win,...}
PRICE_META = {}    # JSON _meta (생성일·환율 등) — 폴백이면 빈 dict


def latest_date():
    """SHILLA_DATE 미설정 시, raw 신라 CSV(`신라면세_위스키_<date>.csv`)가 실재하는
    가장 최신 <date>. raw 가 수집의 단일 진실이므로, 리포트_가격_JSON 만 잔존하는 날짜로
    폴백해 stale-date 리포트를 내는 것을 막는다(CMPA-235). raw 가 하나도 없으면 오늘."""
    import glob
    import re
    d = os.path.join(ROOT, "data", "shilla-dutyfree")
    dates = sorted(re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(p)).group(1)
                   for p in glob.glob(os.path.join(d, "신라면세_위스키_*.csv"))
                   if re.search(r"\d{4}-\d{2}-\d{2}", p))
    return dates[-1] if dates else time.strftime("%Y-%m-%d")


def load_prices(date):
    """data/shilla-dutyfree/리포트_가격_<date>.json 로드(없으면 하드코딩 폴백)."""
    global PRICES, PRICE_META
    p = os.path.join(ROOT, "data", "shilla-dutyfree", f"리포트_가격_{date}.json")
    try:
        d = json.load(open(p, encoding="utf-8"))
        PRICES = d.get("prices", {})
        PRICE_META = d.get("_meta", {})
    except (OSError, ValueError):
        PRICES, PRICE_META = {}, {}
    return bool(PRICES)


def px(code, pr, dm, adv, win=True):
    """코드의 라이브 가격(면세·국내·이득·win)을 반환, 없으면 하드코딩 폴백."""
    e = PRICES.get(code)
    if not e:
        return pr, dm, adv, win
    return e.get("면세", pr), e.get("국내", dm), e.get("이득", adv), e.get("win", win)

# (이름, 면세가, 국내최저, 이득표기, 비고, 상품코드)
DOMESTIC = [
    ("조니워커 18년", "8.4만", "14.9만", "−44%", "부드러운 고숙성 블렌디드 · 입문/선물 0순위", "3651371", "5~10만"),
    ("글렌드로낙 16년", "19.2만", "37.2만", "−48%", "묵직한 셰리몰트 · 최대 폭", "4391067", "10~20만"),
    ("글렌피딕 18년 Vat4", "12.0만", "20.2만", "−41%", "셰리·버번 매리지 18년을 절반값 가까이", "5105341", "10~20만"),
    ("발렌타인 18년 글렌버기", "10.4만", "17.0만", "−39%", "단일 증류소 한정 블렌디드", "5524471", "10~20만"),
    ("글렌파클라스 15년", "10.5만", "13.9만", "−24%", "입문 셰리밤의 정석", "5226623", "10~20만"),
    ("아벨라워 아부나흐", "12.1만", "15.0만", "−19%", "캐스크 스트렝스(60%) 셰리밤", "5887242", "10~20만"),
    ("글렌피딕 21년", "21.4만", "31.9만", "−33%", "럼 캐스크 피니시 · 바나나·토피", "275686", "20~30만"),
    ("글렌파클라스 25년", "33.5만", "45.0만", "−26%", "셰리밤 컬렉터의 25년", "5226626", "30만+"),
]
TRAP = [
    ("듀어스 12년", "7.4만", "3.5만", "트레이더스 상시할인 대중 블렌디드", "5070785"),
    ("발렌타인 10년", "6.3만", "3.4만", "마트·데일리샷 흔함", "5269996"),
    ("탈리스커 10년", "12.1만", "6.8만", "아일라 인기 싱글몰트, 국내 저렴", "5604485"),
    ("로얄 살루트 21년", "25.1만", "17.5만", "선물용 블렌디드", "5081230"),
    ("시바스 12년", "6.8만", "5.1만", "대중 블렌디드", "5070399"),
    ("조니워커 블루", "32.3만", "25.9만", "프리미엄 블렌디드, 국내 코스트코", "287148"),
]
# (이름, 면세, 국내최저, 이득, 홍콩, 비고, 코드)
TRAVEL = [
    ("발베니 12년 골든캐스크", "6.7만", "9.9만", "−32%", "홍콩 11.9만", "국내(더블우드)·홍콩보다 쌈 · 셰리/버번 더블", "5516907"),
    ("더 글렌그란트 12년 (1L)", "5.9만", "6.1만", "−2%", "", "국내와 동가, 1L라 용량당 이득", "5224926"),
    ("부쉬밀 21년 마르살라", "23.1만", "24.3만", "−5%", "홍콩 42.1만", "아이리시 21년 · 홍콩보다 −45%", "5200760"),
]
# 취향파: 카테고리별 (이름, 면세, 국내최저, 이득, 비고, 코드)
TASTE = {
    "🔥 피트": [
        ("폴 존 피티드 (1L)", "6.5만", "13.9만", "−54%", "인도산 가성비 끝판 ⭐", "5311922"),
        ("컴파스 박스 피트 몬스터", "5.1만", "9.7만", "−48%", "이름값 하는 스모크", "5229030"),
        ("암룻 피티드 캐스크 스트렝스", "8.2만", "10.3만", "−21%", "인도 캐스크 스트렝스 ⭐", "5337845"),
        ("보모어 16년", "11.6만", "15.9만", "−27%", "아일라 셰리 피트", "5524532"),
        ("보모어 19년", "21.4만", "29.5만", "−27%", "아일라 고숙성", "5524533"),
        ("라프로익 12년", "6.3만", "국내 최저가 없음", "", "국내 단종(10년이 표준) · 아일라 정석", "5917035"),
        ("캐퍼도닉 18년 피티드", "9.6만", "국내 최저가 없음", "", "스페이사이드 피트 희귀 ⭐", "5065829"),
    ],
    "🍇 셰리": [
        ("폴 존 PX 셰리", "6.8만", "13.5만", "−50%", "인도산 PX, 진한 단맛 ⭐", ""),
        ("글렌파클라스 15년", "10.5만", "13.9만", "−24%", "입문 셰리밤 정석", "5226623"),
        ("아벨라워 16년", "11.7만", "16.1만", "−27%", "셰리·버번 더블캐스크", ""),
        ("아벨라워 18년", "22.6만", "29.5만", "−23%", "묵직한 더블 캐스크", ""),
        ("글렌파클라스 25년", "33.5만", "45.0만", "−26%", "셰리밤 종착지", "5226626"),
    ],
    "🥃 버번/아메리칸": [
        ("와일드터키 켄터키 스피릿 (1L)", "6.1만", "11.9만", "−49%", "싱글 배럴 1L", "5408280"),
        ("웰러 스페셜 리저브", "8.6만", "15.9만", "−46%", "휘티드 버번, 부드러움", "5676433"),
        ("잭다니엘 골드(No.27)", "7.7만", "국내 최저가 없음", "", "테네시 프리미엄, 메이플·바닐라", "3331541"),
    ],
}
# 선물파: (가격순정렬용 숫자, 이름, 면세, 국내최저, 이득, 면세유리?, 후킹, 비고, 코드, 상세스토리)
# 가격(만원) 오름차순으로 렌더링한다. 스토리/수상 정보 기반 12종.
GIFT = [
    (6.1, "글렌리벳 12년 (1L)", "6.1만", "6.1만", "≈ 동가", True, "\"첫 싱글몰트의 표준\"", "실패 없는 입문 선물", "5615979",
     "싱글몰트 입문의 사실상 기준점. 가볍고 부드러워 누구에게 줘도 실패가 없습니다. 1L 행사판도 있어 용량당 가성비도 좋습니다."),
    (6.3, "라프로익 12년", "6.3만", "국내 없음", "면세 전용급", True, "금주법 땐 '약', 찰스 3세가 사랑한 위스키 🏅", "개성 강한 애주가", "5917035",
     "미국 금주법 시절, 강한 요오드·소독약 향 덕에 '약용'으로 분류돼 약국에서 처방 판매됐습니다. 1994년 찰스 왕세자(현 찰스 3세)의 로열 워런트를 받은 유일한 스카치. 호불호는 갈리지만 '스토리 끝판왕'이라 피트 좋아하는 사람에게 강한 인상을 남깁니다."),
    (6.7, "발베니 12년 (골든캐스크)", "6.7만", "9.9만", "−32%", True, "사라진 '다섯 손기술'을 지키는 술", "정성 강조·손윗사람", "5516907",
     "발베니는 자체 보리 농사(1,000에이커)·전통 플로어 몰팅·자체 쿠퍼리지(통 수리)·코퍼스미스(증류기 대장장이)·업계 최장수 몰트마스터까지 '다섯 가지 희귀 수공예'를 모두 유지하는 거의 유일한 증류소입니다. 2016년 몰트마스터 데이비드 스튜어트는 엘리자베스 2세에게 MBE를 받았습니다. '사람이 손으로 만든 술' 서사가 손윗사람 선물에 어울립니다."),
    (12.1, "아벨라워 아부나흐", "12.1만", "15.0만", "−19%", True, "배치마다 다른 캐스크 스트렝스 '셰리 폭탄'", "셰리 러버·컬렉터", "5887242",
     "인공 착색·냉각 여과 없이 첫 채움 올로로소 셰리 캐스크에서 캐스크 스트렝스(약 60%)로 병입합니다. 배치마다 번호가 붙고 풍미가 조금씩 달라 컬렉터가 배치를 모읍니다. 진한 건포도·다크체리의 묵직한 셰리 — 국내보다도 −19%."),
    (12.15, "탈리스커 10년", "12.1만", "6.8만", "국내 −44%", False, "스카이섬, '바다가 만든 위스키'", "여행·바다 추억(단, 국내가 더 쌈)", "5604485",
     "스코틀랜드 스카이섬의 거친 바다 옆에서 빚는 싱글몰트. 후추·바다소금·스모크의 짭짤한 개성으로 '바다가 만든 위스키'라 불립니다. 여행·섬 추억이 있는 사람에게 서사가 붙지만, 가격만 보면 국내가 더 쌉니다."),
    (12.8, "부쉬밀 15년", "12.8만", "16.3만", "−21%", True, "세계에서 가장 오래된 허가 증류소(1608)", "아이리시 테마·기념일", "5200759",
     "1608년 제임스 1세 왕이 이 지역에 증류 면허를 하사 — 라벨의 '1608'이 그 기원입니다. '현존 최古 허가 증류소'라는 한 줄 후킹. 아이리시 특유의 부드러운 삼중 증류."),
    (19.2, "글렌드로낙 16년", "19.2만", "37.2만", "−48%", True, "1826년부터의 하이랜드 셰리 명가", "셰리 좋아하는 사람", "4391067",
     "페드로 히메네스·올로로소 셰리 캐스크 장기 숙성으로 유명한 하이랜드 셰리 명가(1826년 설립). 건포도·다크초콜릿·가죽의 진한 셰리. 국내보다 −48%로 이 선물 표 최대 폭."),
    (21.4, "글렌피딕 21년", "21.4만", "31.9만", "−33%", True, "싱글몰트를 세계에 처음 알린 글렌피딕 · 럼 21년", "격식 있는 감사", "275686",
     "1963년 싱글몰트를 해외에 처음 내놓아 '현대 싱글몰트 카테고리'를 연 글렌피딕. 21년 그란 레세르바는 카리브 럼 캐스크 피니시로 바나나·토피의 달큰함이 얹힙니다."),
    (21.45, "보모어 19년", "21.4만", "29.5만", "−27%", True, "1779년 설립, 아일라에서 가장 오래된 증류소", "아일라 피트 애호가", "5524533",
     "1779년 설립된 아일라 최고(古) 증류소. 바닷가 'No.1 Vaults' 숙성고가 유명합니다. 무화과·연기·바다향이 어우러진 깊은 아일라 고숙성."),
    (25.1, "로얄 살루트 21년", "25.1만", "17.5만", "국내 −30%", False, "1953 엘리자베스 2세 대관식 선물로 태어난 술 · 21발 예포 ⭐", "최고 의전(단, 국내가 더 쌈)", "5081230",
     "1953년 6월 2일 엘리자베스 2세 대관식 헌정으로 출시. 21발 예포(21-gun salute)에서 이름을 따 모든 제품을 최소 21년 숙성합니다. 그린 도자기 플라곤은 본래 여왕께 드리는 대관식 선물로 만들어졌습니다. '선물로 만들어진 술' 그 자체 — 다만 가격은 국내가 약 30% 쌉니다."),
    (27.6, "카발란 비노바리끄 솔리스트", "27.6만", "30.9만", "−11%", True, "번즈나이트 블라인드서 스카치를 이긴 대만 위스키 🏆", "이야기 좋아하는 사람", "5101582",
     "2010년 번즈나이트 블라인드 테이스팅에서 스카치를 제치고 1위. 평론가 찰스 맥클린의 반응 'Oh. My. God.'이 별명이 됐습니다. 더운 기후로 빠르게 익어 진한 풍미 — '스카치를 이긴 신세계 위스키'라는 의외성."),
    (34.5, "옥토모어 16.3", "34.5만", "국내 없음", "면세 전용급", True, "세계에서 가장 강하게 피트한 컬트 위스키 🏆", "스모크 마니아·컬렉터", "5934209",
     "브룩라디가 만드는 옥토모어는 페놀(피트) 수치가 100ppm을 훌쩍 넘는 '세계에서 가장 강하게 피트한' 시리즈입니다. 매 릴리스가 화제가 되는 스모크 마니아의 컬트 위스키 — 강렬함을 원하는 사람에게 특별한 선물."),
]
NOT_DUTYFREE = "글렌피딕 12년(6대 가문·선물틴 원조), 맥캘란 12년 더블캐스크(\"마시지 않아도 자산\"), 달모어 12년(왕을 구한 사슴 문장), 오반 14년(잔 2개 포함) — 신라면세 미취급, 국내 트레이더스·데일리샷에서."


# 위스키별 (분류 라벨, 맛 노트) — 부분일치 키
WHISKY_META = {
    "조니워커 18": ("블렌디드", "꿀·오렌지에 은은한 스모크, 부드러운 고숙성"),
    "글렌드로낙 16": ("싱글몰트·셰리", "건포도·다크초콜릿·가죽, 진한 셰리"),
    "글렌피딕 18": ("싱글몰트", "사과·오크·꿀, 셰리·버번 균형"),
    "발렌타인 18": ("블렌디드", "꿀·바닐라·헤이즐넛, 매끈한 블렌디드"),
    "글렌파클라스 15": ("싱글몰트·셰리", "건포도·크리스마스 케이크, 셰리밤 정석"),
    "글렌파클라스 25": ("싱글몰트·셰리", "무화과·가죽·오래된 오크, 깊은 셰리"),
    "아부나흐": ("싱글몰트·셰리·CS", "진한 건포도·다크체리, 고도수 셰리폭탄"),
    "글렌피딕 21": ("싱글몰트", "바나나·토피·바닐라, 럼 캐스크 피니시"),
    "듀어스 12": ("블렌디드", "꿀·바닐라, 가벼운 데일리"),
    "발렌타인 10": ("블렌디드", "사과·바닐라, 부담 없는 입문"),
    "탈리스커 10": ("싱글몰트·피트", "후추·바다소금·연기, 짭짤한 스모크"),
    "로얄 살루트 21": ("블렌디드", "과일·꿀·오크, 부드러운 프리미엄"),
    "시바스 12": ("블렌디드", "꿀·사과·바닐라, 대중적 부드러움"),
    "조니워커 블루": ("블렌디드", "꿀·건포도·스모크, 매끈한 최상위"),
    "발베니 12": ("싱글몰트", "꿀·바닐라·오렌지, 셰리/버번 더블캐스크"),
    "글렌그란트 12": ("싱글몰트", "사과·바닐라, 가볍고 부드러운 입문"),
    "글렌그란트 15": ("싱글몰트", "사과·캐러멜, 1L 가성비 숙성"),
    "부쉬밀 21": ("아이리시 싱글몰트", "과실·견과에 마르살라 와인의 단맛"),
    "부쉬밀 15": ("아이리시 싱글몰트", "꿀·건포도, 부드러운 삼중 증류"),
    "폴 존 피티드": ("인도 싱글몰트", "열대과일에 얹은 스모크, 가성비 피트"),
    "폴 존 PX": ("인도 싱글몰트", "건포도·초콜릿, 진한 PX 셰리 단맛"),
    "컴파스 박스 피트": ("블렌디드 몰트", "모닥불·바닐라, 균형 잡힌 스모크"),
    "암룻 피티드": ("인도 싱글몰트", "훈연·다크초콜릿, 고도수 진한 피트"),
    "보모어 16": ("싱글몰트·아일라", "바다소금·셰리·스모크"),
    "보모어 19": ("싱글몰트·아일라", "무화과·연기·오크, 깊은 아일라"),
    "라프로익 12": ("싱글몰트·아일라", "요오드·소독약·강한 피트, 호불호 개성"),
    "캐퍼도닉 18": ("싱글몰트·피트", "스페이사이드에 얹은 은은한 스모크"),
    "아벨라워 16": ("싱글몰트·셰리", "건포도·오렌지, 셰리/버번 더블"),
    "아벨라워 18": ("싱글몰트·셰리", "말린 과일·가죽, 묵직한 더블캐스크"),
    "와일드터키 켄터키": ("버번", "바닐라·캐러멜·오크, 고도수 싱글배럴"),
    "웰러": ("버번·휘티드", "부드러운 바닐라·꿀, 밀(wheat) 버번"),
    "잭다니엘 골드": ("테네시 위스키", "메이플·바닐라·오크, 부드러운 프리미엄"),
    "글렌리벳 12": ("싱글몰트", "사과·꽃·바닐라, 첫 싱글몰트의 표준"),
    "카발란 비노바리끄": ("대만 싱글몰트", "열대과일·바닐라·와인, 빠른 숙성의 진한 풍미"),
    "옥토모어": ("싱글몰트·초강피트", "압도적 훈연·타르·다크초콜릿, 강렬한 스모크"),
}


def esc(s):
    return html.escape(str(s))


def _norm(s):
    return s.replace(" ", "").replace("(", "").replace(")", "")


def meta(name):
    nn = _norm(name)
    for k, v in WHISKY_META.items():
        if _norm(k) in nn:
            return v
    return (None, None)


def cat_badge(name):
    cat, _ = meta(name)
    return f'<span class="cat">{esc(cat)}</span>' if cat else ""


def note_block(name):
    _, note = meta(name)
    if not note:
        return ""
    return (f'<details class="note"><summary>🥃 맛 노트</summary>'
            f'<p>{esc(note)}</p></details>')


# 위스키별 스토리(있으면) — 부분일치 키. 수상 경력은 본문에 포함.
STORIES = {
    "글렌리벳 12": "싱글몰트 입문의 사실상 표준. 1824년 정부 면허 1호 증류소 중 하나로, '진짜 글렌리벳' 상표를 두고 분쟁까지 벌인 원조 브랜드.",
    "라프로익 12": "미국 금주법 시절 강한 요오드·소독약 향 덕에 '약용'으로 분류돼 약국에서 처방 판매됐고, 1994년 찰스 왕세자(현 찰스 3세)의 로열 워런트를 받은 유일한 스카치.",
    "발베니 12": "보리 농사·플로어 몰팅·자체 통 수리·증류기 대장장이·최장수 몰트마스터까지 '다섯 가지 희귀 수공예'를 모두 지키는 거의 유일한 증류소.",
    "아부나흐": "인공 착색·냉각 여과 없이 첫 채움 올로로소 셰리 캐스크에서 캐스크 스트렝스(약 60%)로 병입. 배치마다 번호가 붙고 풍미가 조금씩 달라 컬렉터가 모은다.",
    "탈리스커 10": "스카이섬의 거친 바다 옆에서 빚는 싱글몰트. 후추·바다소금·스모크로 '바다가 만든 위스키'라 불린다.",
    "부쉬밀 15": "1608년 제임스 1세 왕이 증류 면허를 하사 — 라벨의 '1608'이 그 기원. '현존 세계 최古 허가 증류소'.",
    "부쉬밀 21": "1608년 면허의 세계 최古 허가 증류소가 만든 21년 고숙성. 마르살라 와인 캐스크 피니시.",
    "글렌드로낙 16": "1826년 설립, 페드로 히메네스·올로로소 셰리 캐스크 장기 숙성으로 유명한 하이랜드 셰리 명가.",
    "글렌피딕 18": "1963년 싱글몰트를 해외에 처음 내놓아 '현대 싱글몰트 카테고리'를 연 글렌피딕. 6대째 가족 경영.",
    "글렌피딕 21": "싱글몰트를 세계에 처음 알린 글렌피딕의 21년. 카리브 럼 캐스크 피니시로 바나나·토피의 달큰함.",
    "보모어 16": "1779년 설립된 아일라에서 가장 오래된 증류소. 바닷가 'No.1 Vaults' 숙성고로 유명.",
    "보모어 19": "1779년 설립, 아일라 최古 증류소. 바다향·스모크가 어우러진 깊은 고숙성.",
    "로얄 살루트 21": "1953년 엘리자베스 2세 대관식 헌정으로 출시. 21발 예포에서 이름을 따 모든 제품을 최소 21년 숙성하고, 도자기 플라곤은 본래 여왕께 드리는 대관식 선물이었다.",
    "카발란 비노바리끄": "🏆 2010년 번즈나이트 블라인드 테이스팅에서 스카치를 제치고 1위 — 평론가 찰스 맥클린의 'Oh. My. God.'이 별명이 됐다. 더운 기후로 빠르게 익는 대만 싱글몰트.",
    "옥토모어": "🏆 브룩라디가 만드는, 페놀 수치 100ppm을 훌쩍 넘는 '세계에서 가장 강하게 피트한' 시리즈. 매 릴리스가 화제가 되는 컬트 위스키.",
    "글렌파클라스 15": "1836년부터 6대째 그랜트 가문이 독립 경영하는 셰리 명가. 직화 증류와 전통 셰리 캐스크를 고집한다.",
    "글렌파클라스 25": "6대째 가족 경영 셰리 명가의 25년 장기 숙성. 셰리밤 컬렉터의 종착지.",
    "발렌타인 18": "1827년 조지 발렌타인이 시작한 스카치 블렌딩 명가. 17·18·30년 등 고숙성 라인으로 유명.",
    "조니워커 18": "1820년 식료품상 존 워커가 시작해 세계 1위가 된 스카치 블렌드. '계속 걷는 사람' 로고.",
    "폴 존": "🏅 인도 고아의 신생 명가. 인도산 6줄 보리로 빚어 빠르게 익는 트로피컬 싱글몰트로, 국제 주류 대회 수상 다수.",
    "암룻 피티드": "🏆 인도 위스키의 선구자. 짐 머리의 위스키 바이블에서 높은 점수를 받으며 세계에 인도 싱글몰트를 알렸다.",
    "캐퍼도닉 18": "2002년 문 닫은 '침묵의 증류소(silent still)'. 남은 원액만 풀려 갈수록 희귀해지는 스페이사이드 피트.",
    "컴파스 박스 피트": "라벨·블렌딩의 혁신가 존 글레이저의 부티크 블렌더. 캐스크 구성을 투명 공개해 업계에 파장을 일으켰다.",
    "와일드터키 켄터키": "전설적 마스터 디스틸러 지미 러셀이 60년 넘게 지킨 켄터키 버번의 자존심.",
    "웰러": "'패피 반 윙클'의 뿌리가 된 휘티드(밀) 버번. 구하기 어려워 미국에서도 컬트.",
    "잭다니엘 골드": "테네시 위스키 No.27 골드. 단풍나무 숯으로 두 번 여과한 프리미엄.",
}


def story_block(name):
    nn = _norm(name)
    for k, v in STORIES.items():
        if _norm(k) in nn:
            return (f'<details class="note story"><summary>📖 스토리</summary>'
                    f'<p>{esc(v)}</p></details>')
    return ""


def award_badge(name):
    nn = _norm(name)
    for k in STORIES:
        if _norm(k) in nn and ("🏆" in STORIES[k] or "🏅" in STORIES[k]):
            return '<span class="award">🏆 수상</span>'
    return ""


def prod(name, code):
    n = esc(name)
    if code:
        return f'<a href="{P}{code}" target="_blank" rel="noopener">{n} <span class="ext">↗</span></a>'
    return n


def ds_link(name):
    """데일리샷 검색 링크 — 국내 최저가 직접 검증용."""
    import urllib.parse
    q = urllib.parse.quote(name.split("(")[0].strip())
    return (f'<a class="dslink" target="_blank" rel="noopener" '
            f'href="https://dailyshot.co/m/search/result?q={q}">🔎 데일리샷 보기</a>')


# 선물 멘트 추천 — 받는 사람별로 담백하게. 부분일치 키.
GIFT_MSG = {
    "글렌리벳 12": "친구에게 — 입문용으로 무난해. 부담 없이 한잔하자.",
    "라프로익 12": "애주가 친구에게 — 강한 피트라 호불호는 갈려. 너라면 좋아할 듯.",
    "발베니 12": "윗사람께 — 정성 들인 술이라 골랐습니다. 편하실 때 한 잔 하세요.",
    "아부나흐": "연인에게 — 진한 셰리 좋아하면 딱이야. 도수는 좀 세.",
    "탈리스커 10": "아랫사람에게 — 수고 많았어요. 짭짤한 스모크가 매력이에요.",
    "부쉬밀 15": "윗사람께 — 오래된 증류소 술이라 골랐습니다. 부드러워요.",
    "글렌드로낙 16": "부모님께 — 묵직한 셰리예요. 식후에 한 잔 하시기 좋아요.",
    "글렌피딕 21": "윗사람께 — 21년 숙성이라 귀한 날에 어울려서요. 축하드립니다.",
    "보모어 19": "부모님께 — 향이 깊은 섬 위스키예요. 천천히 즐기세요.",
    "로얄 살루트 21": "윗사람께 — 격식 갖춘 자리에 어울려서요. 병도 두기 좋습니다.",
    "카발란 비노바리끄": "친구에게 — 요즘 화제인 대만 위스키야. 얘깃거리로도 좋아.",
    "옥토모어": "마니아 친구에게 — 스모크 끝판왕이야. 강한 거 좋아하면 분명 좋아할 거야.",
}


def gift_msg(name):
    nn = _norm(name)
    for k, v in GIFT_MSG.items():
        if _norm(k) in nn:
            return v
    return None


def badge(adv, win=True):
    if not adv:
        return ""
    cls = "adv" if win else "advx"
    return f'<span class="{cls}">{esc(adv)}</span>'


def card(name, code, price, dom, adv, note, dom_label="국내 최저", win=True, msg=None):
    msg_html = f'<div class="gift-msg">💌 {esc(msg)}</div>' if msg else ""
    return f"""<div class="card">
  <div class="card-h">{prod(name, code)} {cat_badge(name)} {award_badge(name)} {badge(adv, win)}</div>
  <div class="card-p"><b>면세 {esc(price)}</b> · {esc(dom_label)} {esc(dom)}</div>
  <div class="card-n">{esc(note)}</div>
  {msg_html}
  <div class="expanders">{note_block(name)}{story_block(name)}{ds_link(name)}</div>
</div>"""


def trap_card(name, code, price, dom, note):
    return f"""<div class="card trap">
  <div class="card-h">{prod(name, code)} {cat_badge(name)} {award_badge(name)} <span class="advx">국내 더 쌈</span></div>
  <div class="card-p">면세 {esc(price)} · <b>국내 {esc(dom)}</b></div>
  <div class="card-n">{esc(note)}</div>
  <div class="expanders">{note_block(name)}{story_block(name)}{ds_link(name)}</div>
</div>"""


def gift_card(name, code, price, dom, adv, win, hook, note, story):
    _, taste = meta(name)
    taste_html = f'<p class="g-taste">🥃 맛: {esc(taste)}</p>' if taste else ""
    return f"""<details class="gift">
  <summary>
  <div class="g-top">{prod(name, code)} {cat_badge(name)} {badge(adv, win)}</div>
  <div class="card-p"><b>면세 {esc(price)}</b> · 국내 최저 {esc(dom)}</div>
  <div class="g-hook">{esc(hook)}</div>
  <div class="story-btn">📖 스토리 · 맛 노트 보기</div>
  </summary>
  <div class="g-body">{taste_html}<p>{esc(story)}</p><p class="g-note">🎁 {esc(note)}</p></div>
</details>"""


def main():
    date = os.environ.get("SHILLA_DATE") or latest_date()
    live = load_prices(date)
    print(f"가격 소스: {'라이브 JSON ('+str(len(PRICES))+'종, 생성 '+PRICE_META.get('generated','?')+')' if live else '하드코딩 폴백(JSON 없음)'}")
    # 국내파 (예산대 그룹)
    dom_html = ""
    for band in ["5~10만", "10~20만", "20~30만", "30만+"]:
        picks = [x for x in DOMESTIC if x[6] == band]
        if not picks:
            continue
        dom_html += f'<div class="band">{esc(band)} 원</div>'
        for n, pr, dm, adv, note, code, _ in picks:
            pr, dm, adv, _w = px(code, pr, dm, adv)
            dom_html += card(n, code, pr, dm, adv, note)
    trap_html = ""
    for n, pr, dm, note, code in TRAP:
        pr, dm, _adv, _w = px(code, pr, dm, "")
        trap_html += trap_card(n, code, pr, dm, note)
    travel_html = ""
    for n, pr, dm, adv, hk, note, code in TRAVEL:
        pr, dm, adv, _w = px(code, pr, dm, adv)
        travel_html += card(n, code, pr, dm, adv, (note + (" · " + hk if hk else "")))
    taste_html = ""
    for cat, picks in TASTE.items():
        taste_html += f'<div class="band">{esc(cat)}</div>'
        for n, pr, dm, adv, note, code in picks:
            pr, dm, adv, _w = px(code, pr, dm, adv)
            taste_html += card(n, code, pr, dm, adv, note)
    gift_html = '<div class="band">스토리·수상 기반 추천 12종 (가격순) — 📖 스토리 · 💌 멘트 추천</div>'
    for _, n, pr, dm, adv, win, hk, note, code, st in sorted(GIFT, key=lambda x: x[0]):
        pr, dm, adv, win = px(code, pr, dm, adv, win)
        gift_html += card(n, code, pr, dm, adv, hk, "국내 최저", win, gift_msg(n))
    gift_html += f'<div class="note-box">🎁 <b>면세엔 없지만 \'선물 명작\'</b>: {esc(NOT_DUTYFREE)}</div>'

    doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="신라면세 위스키 656종을 가성비순으로 분석 — 면세가가 오히려 비싼 함정과, 상 받은 술을 면세가로 사는 진짜 이득만 골랐습니다.">
<title>면세 위스키, 진짜 싼 것만 골랐다 — WK 가성비 면세 위스키</title>
<style>
:root{{--bg:#0f1115;--card:#1a1d24;--line:#2a2e38;--txt:#e8eaed;--sub:#9aa0aa;--green:#34c759;--blue:#0a84ff;--purple:#bf5af2;--gold:#ffd34e;--red:#ff6b6b}}
*{{box-sizing:border-box;-webkit-tap-highlight-color:transparent}}
body{{margin:0;background:var(--bg);color:var(--txt);font-family:-apple-system,BlinkMacSystemFont,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;line-height:1.55;font-size:16px}}
.wrap{{max-width:620px;margin:0 auto;padding:0 14px 60px}}
header{{padding:26px 14px 14px;text-align:center;max-width:620px;margin:0 auto}}
header h1{{font-size:22px;margin:0 0 6px;font-weight:800}}
header p{{color:var(--sub);font-size:13px;margin:4px 0}}
header p.gen{{color:var(--gold);font-size:12px;font-weight:700;margin:2px 0 6px}}
.tabs{{position:sticky;top:0;z-index:9;background:var(--bg);display:flex;flex-wrap:wrap;gap:6px;padding:10px 0;border-bottom:1px solid var(--line)}}
.tab{{flex:1 1 0;min-width:0;text-align:center;padding:9px 6px;border-radius:999px;background:var(--card);border:1px solid var(--line);color:var(--sub);font-size:14px;font-weight:700;cursor:pointer;white-space:nowrap}}
@media (max-width:400px){{.tab{{font-size:12.5px;padding:8px 4px}}}}
@media (max-width:330px){{.tab{{flex:1 1 44%}}}}
.tab.on{{color:#fff}}
.tab.t1.on{{background:var(--green);border-color:var(--green)}}
.tab.t2.on{{background:var(--blue);border-color:var(--blue)}}
.tab.t3.on{{background:var(--purple);border-color:var(--purple)}}
.tab.t4.on{{background:#6b5400;border-color:var(--gold);color:var(--gold)}}
.panel{{display:none;padding-top:14px}}
.panel.on{{display:block;animation:f .2s}}
@keyframes f{{from{{opacity:.3}}to{{opacity:1}}}}
.lead{{color:var(--sub);font-size:13.5px;margin:2px 0 12px}}
.band{{font-weight:800;font-size:15px;margin:18px 0 8px;color:var(--gold)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:12px 14px;margin:8px 0}}
.card-h{{font-weight:700;font-size:15.5px;display:flex;align-items:center;flex-wrap:wrap;gap:6px}}
.card-h a{{color:var(--txt);text-decoration:none;border-bottom:1px dashed var(--blue)}}
.ext{{color:var(--blue);font-size:12px}}
.card-p{{font-size:14px;margin:4px 0;color:#cfd3da}}
.card-n{{font-size:12.5px;color:var(--sub)}}
.adv{{background:rgba(52,199,89,.16);color:var(--green);font-size:12px;font-weight:800;padding:2px 8px;border-radius:999px}}
.advx{{background:rgba(255,107,107,.16);color:var(--red);font-size:12px;font-weight:800;padding:2px 8px;border-radius:999px}}
.card.trap{{border-color:rgba(255,107,107,.35)}}
.cat{{background:#262a33;color:#aeb4bf;font-size:11px;font-weight:700;padding:2px 7px;border-radius:6px;white-space:nowrap}}
.award{{background:rgba(255,211,78,.16);color:var(--gold);font-size:11px;font-weight:800;padding:2px 7px;border-radius:6px;white-space:nowrap}}
.expanders{{margin-top:8px;display:flex;gap:16px;flex-wrap:wrap}}
.note summary{{list-style:none;cursor:pointer;color:var(--blue);font-size:12.5px;font-weight:700;padding:3px 0}}
.note.story summary{{color:var(--gold)}}
.note[open]{{flex:1 1 100%}}
.note summary::-webkit-details-marker{{display:none}}
.note summary::after{{content:" ▾"}}
.note[open] summary::after{{content:" ▴"}}
.note p{{margin:4px 0 2px;font-size:12.5px;color:#cfd3da}}
.g-taste{{color:var(--gold);font-size:13px}}
.dslink{{color:#7fd1b9;font-size:12.5px;font-weight:700;text-decoration:none;padding:3px 0;border-bottom:1px solid rgba(127,209,185,.4)}}
.gift-msg{{margin-top:7px;background:rgba(255,211,78,.08);border-left:3px solid var(--gold);border-radius:6px;padding:7px 10px;font-size:13px;color:#e8eaed;font-style:italic}}
.gift{{background:var(--card);border:1px solid var(--line);border-radius:14px;margin:8px 0;overflow:hidden}}
.gift summary{{list-style:none;cursor:pointer;padding:12px 14px}}
.gift summary::-webkit-details-marker{{display:none}}
.g-top{{display:flex;justify-content:space-between;align-items:center;gap:8px;font-weight:700;font-size:15.5px}}
.g-top a{{color:var(--txt);text-decoration:none;border-bottom:1px dashed var(--blue)}}
.g-price{{color:var(--gold);font-size:13.5px;white-space:nowrap}}
.g-hook{{color:#cfd3da;font-size:13.5px;margin-top:6px}}
.story-btn{{margin-top:10px;background:var(--gold);color:#1a1400;font-weight:800;font-size:14px;text-align:center;padding:11px;border-radius:10px}}
.story-btn::after{{content:" ▾"}}
.gift[open] .story-btn{{background:#3a3320;color:var(--gold)}}
.gift[open] .story-btn::after{{content:" ▴ 접기"}}
.g-body{{padding:0 14px 14px;font-size:13.5px;color:#cfd3da}}
.g-body p{{margin:10px 0 0}}
.g-note{{color:var(--gold)}}
.note-box{{background:rgba(255,211,78,.08);border:1px solid rgba(255,211,78,.25);border-radius:12px;padding:11px 13px;font-size:12.5px;color:#cfd3da;margin:14px 0}}
.foot{{color:var(--sub);font-size:11px;margin-top:26px;border-top:1px solid var(--line);padding-top:14px}}
.warn{{background:rgba(255,107,107,.08);border:1px solid rgba(255,107,107,.22);border-radius:12px;padding:11px 13px;font-size:12.5px;margin:10px 0}}
</style>
</head>
<body>
<header>
  <h1>🥃 면세점 위스키, 진짜 싼 것 vs 함정</h1>
  <p class="gen">📅 생성일 {date} · 가격·재고는 수시 변동</p>
  <p>신라면세 656종 · 환율 1 USD = 1,500원 · 국내 최저가 = min(데일리샷·트레이더스·코스트코)</p>
  <p>당신은 어떤 타입? 탭을 눌러보세요. <b>상품명 클릭 = 신라면세 바로가기</b></p>
</header>
<div class="wrap">
  <div class="tabs">
    <div class="tab t1 on" data-t="1">🟢 국내파</div>
    <div class="tab t3" data-t="3">🟣 취향파</div>
    <div class="tab t4" data-t="4">🎁 선물파</div>
    <div class="tab t2" data-t="2">🔵 여행파</div>
  </div>

  <section class="panel on" data-p="1">
    <p class="lead">국내(데일리샷·트레이더스·코스트코)서도 쉽지만 <b>면세가 ≥8% 더 싼 것</b>.</p>
    {dom_html}
    <div class="band" style="color:var(--red)">⚠️ 함정 — 국내가 더 쌉니다 (사지 마세요)</div>
    {trap_html}
  </section>

  <section class="panel" data-p="2">
    <p class="lead">일·홍·대 자주 가는 분. 면세가가 <b>국내와 비슷하거나 홍콩보다 싼</b> 것 — 사도 손해 없음.</p>
    {travel_html}
    <div class="warn">데일리샷에 뜨는 11~12만 원대 '아부나흐·글렌파클라스'는 사실 <b>면세/해외 리스팅</b>. 국내 정식 소매가로 보면 ① 국내파처럼 면세가 더 쌉니다.</div>
  </section>

  <section class="panel" data-p="3">
    <p class="lead">취향(피트·셰리·버번)대로. 각 픽에 <b>국내 최저가</b> 표기(없으면 '없음'). 대부분 면세가 −21~54% 쌈.</p>
    {taste_html}
  </section>

  <section class="panel" data-p="4">
    <p class="lead">받는 사람에게 <b>들려줄 이야기</b>가 있는 술. <b>카드를 누르면 스토리</b>가 펼쳐집니다.</p>
    {gift_html}
  </section>

  <div class="foot">
    데이터: 신라면세 shilladfs.com · 국내 최저가=데일리샷(면세 리스팅 제외)·트레이더스·코스트코 중 최저 · 홍콩=HK 소매 · 선물 스토리=웹 검증 리서치.<br>
    ⚠️ 가격·재고는 수시 변동. 면세는 출국 시 구매 가능(한도 2병·2L·$400). 본 페이지는 내부 검토용 초안입니다.
  </div>
</div>
<script>
document.querySelectorAll('.tab').forEach(function(t){{
  t.addEventListener('click',function(){{
    var n=t.dataset.t;
    document.querySelectorAll('.tab').forEach(function(x){{x.classList.toggle('on',x.dataset.t===n)}});
    document.querySelectorAll('.panel').forEach(function(p){{p.classList.toggle('on',p.dataset.p===n)}});
    window.scrollTo({{top:0,behavior:'smooth'}});
  }});
}});
</script>
</body>
</html>"""

    out_dir = os.path.join(ROOT, "reports", "shilla-dutyfree")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"면세위스키_리포트_{date}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(doc)
    print(f"HTML -> {out} ({len(doc):,} bytes)")


if __name__ == "__main__":
    main()
