#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CMPA-165 데이터 품질 공통 모듈 — 수집·정규화·리포트가 **한 군데**서 같은 규칙을 쓴다.

배경(보드 지적): 유튜브 트레이더스 ASR 자막에서 가격을 뽑을 때, 진행자의 말(문장·
필러·광고 멘트)이 '술이름' 으로 새어 들어오고('할인해서', '잭다니엘스 마찬가지로',
'신세계 포인트 적립 시', 한 문장 통째 등), 'N천원 할인' 의 5,000/8,000 같은 숫자가
가격으로 잡히는 오수집이 다수. → 리포트 신뢰도 붕괴.

해결: 이름이 '제품명'인지, 가격이 '말이 되는지'를 판정하는 고정밀 게이트를 수집 단계
(collect_traders_prices), 정규화(normalize_dataset), 리포트(whisky_report_tables)
세 곳에서 공통으로 적용한다(같은 규칙 = 어디서 걸러도 동일 결과).

또 매장 라벨 지점명 제거(트레이더스/코스트코/롯데마트 …)도 여기로 통일(CMPA-160/165).
"""
import re

# ── 매장 라벨 정규화(지점명 제거) ─────────────────────────────────────────
# canonical_store 는 '위치(마트명)' 정규화 전용 — 지점명을 떼어 '트레이더스 구월점'→'트레이더스'.
# ⚠️ CMPA-446(보드 2026-06-17, CMPA-160 반전): 이제 트레이더스/코스트코 '지점'을 **기록**한다
# (지점별 재고 상이). 단 지점은 수집 단계에서 **떼어내기 전에 별도 추출**(ingest_ocr.branch_from_title)
# 해 `지점` 컬럼에 보존하고, 이 함수의 전역 동작(지점 제거)은 그대로 둔다 — 데일리샷 복합 라벨 등
# 다른 소비자도 마트명 정규화에 의존하기 때문. 즉 **위치=마트명, 지점=별도 컬럼**으로 분리한다.
# 순서 중요: 워크하우스(트레이더스)를 '이마트'보다 먼저 봐야 "이마트 트레이더스"→트레이더스.
_MART_BASES = ["트레이더스", "코스트코", "롯데마트", "홈플러스", "이마트"]


def canonical_store(s):
    """매장 라벨에서 지점명 제거. '트레이더스 구월점'·'트레이더스 안산점'→'트레이더스',
    '코스트코 송도점'→'코스트코', '롯데마트 송도점'→'롯데마트'. '/' 구분 복합 라벨
    (데일리샷 국내위치 등)은 세그먼트별 정규화 후 중복 제거·순서 보존. 미지 매장은 보존."""
    s = (s or "").strip()
    if not s:
        return s
    if "/" in s:
        out, seen = [], set()
        for seg in s.split("/"):
            c = canonical_store(seg)
            if c and c not in seen:
                seen.add(c)
                out.append(c)
        return " / ".join(out)
    for base in _MART_BASES:
        if base in s:
            return base
    return s


# ── 이름 품질 게이트(ASR 비-제품명 차단) ───────────────────────────────────
# 진행자 멘트/필러/광고/문장이 이름으로 새어든 행을 거른다. 고정밀(실제 제품명은 통과)
# 지향: 토큰은 '제품명에는 거의 안 나오지만 ASR 멘트엔 흔한' 것만.
_GARBAGE_TOKENS = (
    "할인", "적립", "정립", "포인트", "마찬가지", "참고", "구독", "부탁", "시작",
    "그럼", "좋아요", "바랍", "입니다", "습니다", "하고 있", "이네요", "다음은",
    "보시", "준비", "소개", "말씀", "드리", "있으니", "같은 가격", "되겠",
)
# 문장 어미(이름이 아니라 말의 끝). 짧은 제품명엔 안 나온다.
_SENTENCE_END = re.compile(r"(니다|네요|어요|아요|세요|으니|니까|군요|구요)$")


def is_garbage_name(name):
    """제품명이 아니라 ASR 멘트/필러/문장이면 True(=버린다)."""
    n = (name or "").strip()
    if not n:
        return True
    if len(n) > 35:                       # 제품명은 에디션까지 붙여도 35자 이내
        return True
    if ". " in n or n.endswith("."):      # 다중 문장/문장부호
        return True
    if any(t in n for t in _GARBAGE_TOKENS):
        return True
    if _SENTENCE_END.search(n):           # 문장 어미로 끝남
        return True
    # 주의: 짧은 순한글 이름 컷은 '진빔'(Jim Beam) 같은 실제 제품을 오탈락시켜 도입하지 않는다.
    return False


# ── 가격 상식 게이트 ───────────────────────────────────────────────────────
# 700ml+ 단품 마트 위스키의 현실적 하한. ASR 의 'N천원 할인'(5,000/8,000 등)·
# 부분 숫자 오인식을 거른다. 미니어처/세트는 별도 non_unit 플래그로 이미 제외되므로,
# 이 하한은 '단품'에만 적용한다는 전제.
PRICE_FLOOR_KRW = 15000


def is_sane_price(price, floor=PRICE_FLOOR_KRW):
    """단품 마트 위스키 가격이 상식적이면 True. 결측/0/하한 미만이면 False(=버린다)."""
    try:
        p = int(price)
    except (TypeError, ValueError):
        return False
    return p >= floor


# ── 번들/잔세트 노이즈 게이트 (CMPA-177 보드 확정 2026-06-07) ───────────────
# 보드: "잔세트 등은 무시하면 되는 정보야. 지우면 돼." — 전용잔·잔패키지·잔세트·미니어처
# 세트·메가잔·증정/기프트 세트는 '술 한 병'이 아니라 번들이라 가격이 잔값으로 부풀려져
# 동일 제품 비교를 망친다. 수집·정규화·리포트 어디서든 제외한다.
# ⚠️ '술이름 전체'가 번들 신호일 때만 잡는다 — 제품 구분 토큰(년수·CS·피티드)은 건드리지 않음.
_BUNDLE_NOISE = re.compile(
    r"전용\s*잔|잔\s*패키지|잔패키지|잔\s*세트|잔세트|메가\s*잔|"
    r"미니어[처쳐]\s*세트|미니어[처쳐]세트|두\s*개입|"
    r"전용\s*패키지|기프트\s*세트|선물\s*세트|증정"
)


def is_bundle_noise(name):
    """잔세트/전용잔/미니어처세트 등 '번들' 리스팅이면 True(=버린다). CMPA-177 보드."""
    return bool(_BUNDLE_NOISE.search((name or "").strip()))


# ── 빈티지/컬렉터블 노이즈 게이트 (CMPA-243) ───────────────────────────────
# 배경: HK/JP 동일-SKU 비교에서 글렌모렌지 '오리지널'이 'Glenmorangie 10y 1980s 2L'
# (빈티지 컬렉터블, 1,378,860원)·'Original 1974 Vintage 1999 Limited Release'(1,950,920원)
# 에 오매칭돼 '국내 94%↓' 가짜딜·가짜 🇭🇰↓ 배지를 만들었다. CEO 가 넣은 2.5x 발산 가드
# (build_overseas)는 증상 차단용 — 근본은 **매칭 후보에서 컬렉터블/빈티지 SKU 를 거르는 것**.
# bundle_glass_set 격리와 동형(이름 전체가 컬렉터블 신호일 때만 잡는다).
#
# ⚠️ 표준 소매품을 오탈락시키지 않는다 — **명시적 컬렉터블 신호**(키워드·연대·대용량·단독캐스크)
#    로만 잡고, 맨 4자리 '연도' 단독으로는 잡지 않는다:
#   · 'Double Cask 12y, 2018 release'·'2025 release' 처럼 **연차 보틀링(release/bottling) 연도**
#     는 같은 표준 제품의 배치일 뿐 컬렉터블이 아니다 → 맨 연도 규칙은 이를 오탈락시킨다(FP).
#   · 실제 컬렉터블은 늘 'Vintage'·'Limited'·'Grand Vintage'·'1980s'(연대)·'2L'·'Single Cask'
#     같은 명시적 신호를 동반한다(예: 'Original 1974 Vintage 1999 Limited Release' = vintage+limited,
#     '10 Years Old 1980s 2L' = 연대+대용량) → 키워드/연대/대용량/단독캐스크만으로 충분히 잡힌다.
#   · '100 Proof'(도수)·'1.75L/1L'(표준 대용량 소매)·'N년/N year'(숙성)는 컬렉터블 아님 → 제외.
_COLLECTIBLE = re.compile(
    r"(?:19|20)\d0\s*s"                       # 연대 표기: 1980s · 1970s · 2000s
    r"|vintage|빈티지"                          # vintage / grand vintage
    r"|limited\s*(?:release|edition)?|리미티드|한정"   # limited release/edition
    r"|collector|anniversary|기념판|컬렉터"        # 컬렉터/기념판
    r"|single\s*cask|싱글\s*캐스크|cask\s*no|#\s*\d"   # 싱글캐스크 단독(번호)
    r"|\b[2-9](?:[.,]\d)?\s*l\b",             # 2L 이상 대용량(1L·1.75L 표준 소매는 제외)
    re.I,
)


def is_collectible(name):
    """빈티지/컬렉터블/단독캐스크/대용량 등 비표준 SKU 면 True(=동일-SKU 비교 후보에서 제외).
    HK/JP 해외 비교(build_overseas / kr_jp_compare)의 후보 필터에서 호출한다. CMPA-243."""
    return bool(_COLLECTIBLE.search((name or "").strip()))


def is_quarantined(name, price):
    """이름 또는 가격이 불량이면 사유 문자열, 정상이면 ''. (정규화 exclude_reason 용)"""
    if is_garbage_name(name):
        return "asr_garbage_name"
    if is_bundle_noise(name):            # CMPA-177: 잔세트/번들 노이즈 제외(보드 "지우면 돼")
        return "bundle_glass_set"
    if not is_sane_price(price):
        return "implausible_price"
    return ""


# ── 소용량 수집 금지 게이트 (CMPA-733 보드 확정 2026-07-01) ───────────────────
# 보드: "500ml 미만 위스키는 수집 금지." 미니어처(50/100/200ml)·하프보틀(375ml)·
# 기타 소용량은 standard SKU(700/750ml)와 용량이 달라 병당 단가 비교를 왜곡한다.
# 적용: 수집 단계(Lotte/SSG 크롤러, OCR 인제스트)와 정규화(normalize_dataset) 양쪽에서
# volume_ml 숫자 또는 이름 패턴으로 차단한다.

UNDERSIZED_THRESHOLD_ML = 500  # strictly less than → 수집 금지

_SMALL_VOL_NAME_RX = re.compile(
    r"\b(\d+(?:\.\d+)?)\s*ml\b|\b(\d+(?:\.\d+)?)\s*l(?![a-z])",
    re.I,
)


def is_undersized_volume(volume_ml) -> bool:
    """volume_ml < 500 이면 True (= 수집 금지 소용량). None 은 알 수 없음 → False. CMPA-733."""
    if volume_ml is None:
        return False
    try:
        return int(volume_ml) < UNDERSIZED_THRESHOLD_ML
    except (TypeError, ValueError):
        return False


def is_undersized_by_name(name: str) -> bool:
    """상품명에서 용량을 파싱해 500ml 미만이면 True. volume_ml 숫자가 없을 때 이름 기반 폴백. CMPA-733."""
    for m in _SMALL_VOL_NAME_RX.finditer((name or "").strip()):
        raw = m.group(1) or m.group(2)
        try:
            val = float(raw)
            if m.group(2):   # L 단위 → ml 환산
                val *= 1000
            if int(round(val)) < UNDERSIZED_THRESHOLD_ML:
                return True
        except ValueError:
            continue
    return False


# ── 거짓 수집일 방지 (CMPA-243, 데이터 관리 원칙 ③ '수집날짜 메타') ──────────────
# 배경: WebSearch/WebScrape 류 수집기가 과거연도(소스기준일)의 stale 데이터를 오늘 날짜
# (가져온날짜)로 stamping 하면, 그 1~2행이 '판매처 최신 sweep' 으로 오인돼 정상 종합 sweep
# 을 통째 탈락시킨다(CMPA-241: 70종→2종 붕괴). 방지 원칙:
#   · 수집기가 소스의 '기준일'(source_asof)을 알면 가져온날짜에 **그 소스기준일**을 적는다
#     (오늘이 아니라). 그러면 stale 행이 최신 sweep 으로 위장하지 못한다.
#   · 소스기준일이 max_months↑ 과거면 아예 격리(quarantine)한다.
# 리포트 적재(whisky_report_tables.load)는 추가 방어망으로 '미래 수집일'(오늘보다 뒤)을 버린다.
_DATE_RX = re.compile(r"\d{4}-\d{2}-\d{2}$")


def resolve_collected_date(source_asof, run_today, max_months=2):
    """수집기용: 소스기준일(source_asof, 'YYYY-MM-DD')과 실행일(run_today)로 '가져온날짜'를 결정.
    반환 (stamp_date, quarantine_reason):
      · source_asof 없음/형식오류 → (run_today, '')          오늘로 스탬프(기존 동작)
      · source_asof 가 max_months↑ 과거 → ('', 'stale_source')  격리(행을 버린다)
      · 그 외(최근 소스) → (source_asof, '')                   **소스기준일로 스탬프**(오늘 아님)
    데이터 관리 원칙 ③: 가져온날짜 = 실제 그 데이터가 유효한 날짜이지, 스크립트 실행일이 아니다."""
    if not source_asof or not _DATE_RX.match(source_asof.strip()):
        return run_today, ""
    sa = source_asof.strip()
    if not _DATE_RX.match((run_today or "").strip()):
        return sa, ""
    sy, sm = int(sa[:4]), int(sa[5:7])
    ty, tm = int(run_today[:4]), int(run_today[5:7])
    if (ty - sy) * 12 + (tm - sm) >= max_months:
        return "", "stale_source"
    return sa, ""


def is_future_collected(date_str, today):
    """가져온날짜가 오늘보다 미래면 True(=거짓 수집일 → 리포트 적재에서 버린다). CMPA-243.
    미래 수집일은 정의상 불가능하므로(아직 수집하지 않음) stale 소스의 잘못된 스탬프 신호."""
    d = (date_str or "").strip()
    t = (today or "").strip()
    if not (_DATE_RX.match(d) and _DATE_RX.match(t)):
        return False
    return d > t
