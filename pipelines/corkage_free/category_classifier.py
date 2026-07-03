# -*- coding: utf-8 -*-
"""
콜키지프리 식당 대분류(상위 카테고리) 분류기 — CMPA-65

다이닝코드 원문 `카테고리` 문자열(예: "한우, 소고기", "이자카야, 사시미",
"와인바, 생면파스타")을 결정론적 키워드 매핑으로 7개 상위 버킷 중 하나에 할당한다.
라이브 재크롤 없이 기존 카테고리 원문만으로 backfill 가능하도록 독립 모듈로 분리.

버킷(taxonomy, CEO 확정 7개 + 폴백):
  고기 / 물고기·해산물 / 웨스턴(양식) / 일식 / 중식 / 한식·기타 / 바·주류
  (매칭 실패 시 폴백 "기타" + 미매칭 토큰 로그)

설계:
- raw 문자열에 대해 각 버킷 키워드의 부분문자열 포함 여부로 매칭 집계.
- 다중 매칭 시 precedence(우선순위)로 단일 버킷 결정.
- 명시적 엣지케이스 override 두 가지(아래).
"""
from __future__ import annotations
import re
from typing import NamedTuple

# ── 버킷 이름 상수 ──────────────────────────────────────────────
B_MEAT = "고기"
B_FISH = "물고기·해산물"
B_WEST = "웨스턴(양식)"
B_JP   = "일식"
B_CN   = "중식"
B_KR   = "한식·기타"
B_BAR  = "바·주류"
B_ETC  = "기타"  # 폴백(미분류)

# 음식 버킷(이 중 하나라도 매칭되면 바·주류는 배제)
FOOD_BUCKETS = (B_MEAT, B_FISH, B_WEST, B_JP, B_CN, B_KR)

# precedence: 인덱스가 작을수록 높은 우선순위
PRECEDENCE = [B_MEAT, B_JP, B_FISH, B_CN, B_WEST, B_KR, B_BAR]

# 고기 버킷 중 "양고기 구이류" 토큰 — 중식(훠궈) 동반 시 중식으로 양보
LAMB_TOKENS = ("양꼬치", "양갈비", "양고기", "램")

# ── 키워드 사전 ─────────────────────────────────────────────────
# 부분문자열 매칭. 더 구체적인 표현(예: '갈비탕')이 엉뚱하게 잡히지 않도록
# 한식 soup 류는 별도로 강한 키워드로 두고, 고기쪽 '갈비'는 정확 토큰 위주로 관리.
KEYWORDS: dict[str, list[str]] = {
    B_MEAT: [
        "한우", "소고기", "쇠고기", "삼겹살", "오겹살", "냉삼", "돼지갈비", "소갈비",
        "생갈비", "우대갈비", "갈비살", "목살", "항정살", "가브리살", "차돌박이",
        "차돌", "등심", "안심", "채끝", "부채살", "토시살", "곱창", "대창", "막창",
        "양꼬치", "양갈비", "양고기", "정육식당", "정육점", "정육", "뭉티기", "뭉치기",
        "닭구이", "닭갈비", "닭발", "이베리코", "한돈", "흑돼지", "고기집", "고깃집",
        "구이", "주물럭", "갈매기살", "돼지고기", "스테이크하우스", "BBQ", "bbq",
        "양꼬치집", "막창집", "곱창집",
    ],
    B_FISH: [
        "횟집", "생선회", "물회", "회", "사시미",  # 주의: '회'는 일식 override로 보정
        "생선구이", "장어", "민물장어", "참치", "복어", "복", "문어", "낙지", "주꾸미",
        "쭈꾸미", "아구찜", "아귀찜", "방어", "백합", "조개", "해물", "해산물", "굴",
        "꽃게", "대게", "킹크랩", "전복", "광어", "도미", "연어",  # 연어는 일식 override 가능
        "오징어", "새우", "수산", "어시장", "해물탕", "해물찜",
    ],
    B_WEST: [
        "파스타", "피자", "스테이크", "뇨끼", "라자냐", "비스트로", "브런치",
        "레스토랑", "뉴욕스타일", "투움바", "화덕피자", "리조또", "리조토", "스파게티",
        "양식", "이탈리안", "이태리", "프렌치", "스페인", "타파스", "그릴", "버거",
        "햄버거", "스테이크집", "다이닝", "비스트로펍", "와인다이닝", "스튜",
    ],
    B_JP: [
        "이자카야", "스시", "초밥", "오마카세", "사시미", "라멘", "라면집", "사케",
        "일식", "일식당", "우동", "돈카츠", "돈가스", "텐동", "regret", "텐푸라",
        "튀김", "야키토리", "야키니쿠", "이자까야", "회전초밥", "스키야키", "샤브샤브",
        "가이세키", "소바", "규카츠",
    ],
    B_CN: [
        "중식", "중식당", "중국집", "훠궈", "마라", "마라탕", "마라샹궈", "짜장",
        "짜장면", "짬뽕", "탕수육", "어향", "어향가지", "동파육", "양꼬치집",
        "중화요리", "딤섬", "중국요리", "양꼬치전문",
    ],
    B_KR: [
        "국밥", "곰탕", "설렁탕", "육개장", "갈비탕", "감자탕", "평양냉면", "냉면",
        "막걸리", "전통주", "쌀국수", "순대", "순댓국", "족발", "보쌈", "솥밥",
        "한식", "백반", "한정식", "찌개", "김치찌개", "된장", "비빔밥", "칼국수",
        "수제비", "보리밥", "전", "부침개", "추어탕", "삼계탕", "낙지볶음", "두부",
        "쌈밥", "죽", "분식", "떡볶이",
    ],
    B_BAR: [
        "와인바", "와인", "수제맥주", "맥주", "크래프트", "칵테일", "바", "펍",
        "위스키바", "이자카야바", "포차", "포장마차", "술집", "주점", "하이볼",
    ],
}


def _tokenize(raw: str) -> list[str]:
    """원문을 토큰 리스트로. 구분자: 쉼표 / 가운뎃점 / 슬래시 / 공백."""
    parts = re.split(r"[,/·∙•|\s]+", raw or "")
    return [p.strip() for p in parts if p.strip()]


class Classified(NamedTuple):
    bucket: str
    matched: dict[str, list[str]]   # 버킷별 적중 키워드
    unmatched_tokens: list[str]     # 어떤 버킷에도 기여하지 못한 토큰(사전 보강용)


def classify_category(raw: str) -> Classified:
    """원문 카테고리 문자열 → 단일 상위 버킷."""
    text = (raw or "").lower()
    matched: dict[str, list[str]] = {}
    for bucket, kws in KEYWORDS.items():
        hits = [kw for kw in kws if kw.lower() in text]
        if hits:
            matched[bucket] = hits

    # ── 엣지케이스 override ──────────────────────────────────
    # (1) 일식 vs 물고기: 일식 신호가 있으면 물고기보다 일식 우선
    #     ("이자카야, 사시미" → 일식). precedence(일식 idx1 < 물고기 idx2)로도
    #     커버되지만, '회/연어/사시미' 같은 양쪽 공유 토큰을 명시적으로 처리.
    #     → precedence가 이미 일식>물고기 이므로 추가 조치 불필요.

    # (2) 양고기구이 vs 중식: 고기 매칭이 '양*' 토큰에서만 왔고 중식도 매칭되면
    #     중식으로 양보 ("양꼬치, 훠궈" → 중식). 단 다른 육류 신호가 있으면 고기 유지.
    if B_MEAT in matched and B_CN in matched:
        meat_hits = matched[B_MEAT]
        if all(any(l in h for l in LAMB_TOKENS) for h in meat_hits):
            del matched[B_MEAT]

    # (3) 바·주류 배제: 음식 버킷이 하나라도 매칭되면 바·주류 후보 제거
    if any(b in matched for b in FOOD_BUCKETS) and B_BAR in matched:
        del matched[B_BAR]

    # ── 단일 버킷 결정 ──────────────────────────────────────
    if matched:
        bucket = min(matched.keys(), key=lambda b: PRECEDENCE.index(b))
    else:
        bucket = B_ETC

    # ── 미매칭 토큰 산출(폴백/사전보강 로그용) ──────────────
    matched_kw_all = [kw for hits in matched.values() for kw in hits]
    unmatched = []
    for tok in _tokenize(raw):
        if not any(kw.lower() in tok.lower() or tok.lower() in kw.lower()
                   for kw in matched_kw_all):
            unmatched.append(tok)

    return Classified(bucket=bucket, matched=matched, unmatched_tokens=unmatched)


# 편의 함수: 버킷 문자열만
def category_bucket(raw: str) -> str:
    return classify_category(raw).bucket
