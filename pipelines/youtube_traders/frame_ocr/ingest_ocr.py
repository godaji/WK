#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ingest_ocr.py — CMPA-424 (1/2) 프레임OCR 결과 → 품질게이트 → 월별 CSV 적재.

CMPA-423 이 만든 frame_ocr 파이프라인(extract_still_frames → crop_price_tag →
extract_price_ocr)의 산출물 `result.csv`(name,price,volume_ml,n_frames,t_start,t_end)를
**회사 정본 스키마**(술이름,가격_KRW,위치,가져온날짜,출처,신뢰도,비고)로 적재한다.

핵심 리스크 = OCR 노이즈. 데모 result.csv 에 섞인 실제 오염:
  · 매대 안내문 오인  : "만 19세미만청소년에게는절대 판매하지요", "해산물", "과일·채소"
  · 제품명 오자       : "글렌피릭"=글렌피딕, "포로지스 싱글배털"=싱글배럴, "이글레어"=이글 레어
  · 비위스키/꼬냑    : "레이아린V.S.0.P"(레미마틴 VSOP), "다카라 미야자키망고"
정제 없이 canonical floor 에 넣으면 데이터 오염(CLAUDE.md 데이터 품질) → **품질 게이트 필수**.

품질 게이트(통과해야 floor 반영):
  1) 노이즈 blocklist  — 19세 경고·매대 카테고리(해산물/과일/채소…)·점포명·숫자뭉치 제거.
  2) 가격 상식 게이트  — is_sane_price(단품 15,000원↑) + 번들(잔세트) is_bundle_noise 제외.
  3) **canonical SKU 퍼지매칭** — 브랜드-앵커 매처(SkuMatcher)로 OCR 오자를 정본 id 로 보정.
       · 브랜드부를 master-sku 의 브랜드 그룹과 fuzzy 매칭(difflib) → 후보 SKU 집합.
       · 숙성년수(N년) 비대칭이면 다른 제품(CMPA-177) → 거절. 잔여(서브라벨)로 disambiguate.
       · 저신뢰/모호/미매칭은 **격리(quarantine)** — floor 미반영, 별도 CSV 로 감사 보존.
     보수적 설계: 오매칭(가짜 딜)을 막는 게 1순위, 격리(미수집)는 허용.

산출:
  · data/whisky-prices/{YM}_youtube_ocr.csv            — 통과분(정본 name_ko, 신뢰도=중)
  · data/whisky-prices/{YM}_youtube_ocr_quarantine.csv — 격리분(사유 포함, 감사용)
  · .state/ocr_processed.json                          — 처리한 video_id (멱등 skip)

용법:
  python3 ingest_ocr.py --result _demo/k3GQq_-rD1k/result.csv \
      --video k3GQq_-rD1k --channel-label @whiskeypick \
      --title "트레이더스 위스키 가격 정보 (2026.06.08 구월점)" --upload-date 20260608
  (--dry-run 으로 적재 없이 게이트 결과만 확인)
"""
import argparse
import csv
import difflib
import json
import os
import re
import sys
from collections import defaultdict

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
sys.path.insert(0, ROOT)
from pipelines.common.dated import snapshot, kst_today  # noqa: E402
from pipelines.common.whisky_quality import (  # noqa: E402
    canonical_store, is_bundle_noise, is_sane_price)

PRICES_DIR = os.path.join(ROOT, "data", "whisky-prices")
ASSETS = os.path.join(ROOT, "assets")
STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".state")
PROCESSED_FILE = os.path.join(STATE_DIR, "ocr_processed.json")

SCHEMA = ["술이름", "가격_KRW", "위치", "지점", "가져온날짜", "출처", "신뢰도", "비고"]
QSCHEMA = ["raw_name", "가격_KRW", "사유", "video_id", "t_start", "비고"]

AGE_RE = re.compile(r"(\d{1,2})\s*년")
VOL_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(ml|밀리|l|리터)\b", re.I)

# ── 노이즈 blocklist(비-제품 행) ───────────────────────────────────────────
# 가격표 OCR 에 매대 안내문/카테고리/경고문이 제품명으로 새어든다. 제품명엔 거의 안 나오고
# 매대/안내엔 흔한 토큰만 고른다(고정밀). 매칭 실패는 어차피 격리되지만, 노이즈는 매칭
# 시도 전에 명시 차단해 감사 로그(사유)를 또렷하게 남긴다.
_NOISE_TOKENS = (
    "19세", "미성년", "청소년", "판매하", "음주", "주류는",
    "해산물", "수산", "축산", "정육", "과일", "채소", "체소", "야채", "농산",
    "행사", "매대", "코너", "안내", "영수증", "포인트적립", "신세계",
    "delivery", "택배", "배송",
)
_NOISE_RE = re.compile("|".join(map(re.escape, _NOISE_TOKENS)))
# 이름이 사실상 숫자/기호뭉치(예: "더그127000", "남두15")면 제품명이 아니다.
_MOSTLY_DIGITS = re.compile(r"^[\W\d_]*$")

# 코스트코/슬라이드형 영상(CMPA-547)의 '카테고리 구분 슬라이드' + Kirkland 하우스브랜드
# 가격표는 제품명이 **브랜드 없이 일반 주류 카테고리**("스카치 위스키", "버번 위스키",
# "블렌디드 스카치 위스키")로만 찍힌다. 이걸 특정 브랜드로 퍼지매칭하면 오매칭이다
# (실측: '스카치위스키' 36,990원[실제 Kirkland Signature 블렌디드 스카치 1.75L] → 스카파
# 스키렌으로 오매칭, floor 오염). 브랜드 없는 카테고리 단독 라벨은 식별 불가 → 노이즈 차단.
# **정확매칭**(용량·공백 제거 후 == )이라 브랜드가 붙은 실제 제품명("글렌피딕 12년")은 무영향.
_GENERIC_CATEGORY = {
    "스카치위스키", "블렌디드스카치위스키", "블렌드스카치위스키", "블렌디드위스키",
    "블렌드위스키", "버번위스키", "버본위스키", "아이리쉬위스키", "아이리시위스키",
    "테네시위스키", "싱글몰트위스키", "싱글몰트", "몰트위스키", "위스키",
    "아이리쉬크림", "캐리비안럼", "슈페리에럼", "프렌치보드카", "보드카",
    "런던드라이진", "드라이진", "데킬라블랑코", "데킬라",
}
# OCR 이 이름 끝에 붙여 적는 용량 꼬리(700ml/1l/1750 등) 제거 후 카테고리 정확매칭.
_GEN_VOL_TAIL = re.compile(r"\s*(?:1\.?75\s*l|1\s*l|\d{3,4}\s*m\s*l?|\d{3,4})\s*$", re.I)


def is_generic_category(name):
    """브랜드 없는 일반 주류 카테고리 단독 라벨이면 True(코스트코 슬라이드/Kirkland 노이즈)."""
    s = re.sub(r"[^0-9a-z가-힣]+", "", _GEN_VOL_TAIL.sub(" ", str(name or "").lower()))
    return s in _GENERIC_CATEGORY


def noise_reason(name):
    """비-제품 노이즈면 사유 문자열, 아니면 ''."""
    n = (name or "").strip()
    if not n:
        return "empty_name"
    if _NOISE_RE.search(n):
        return "noise_blocklist"
    if is_generic_category(n):
        return "generic_category"      # 브랜드 없는 카테고리 단독 라벨(CMPA-547)
    # 한글 글자 수가 2 미만이면 제품명으로 보기 어렵다(브랜드 최소 2자).
    hangul = re.sub(r"[^가-힣]", "", n)
    if len(hangul) < 2:
        return "noise_blocklist"
    return ""


# ── 매장(위치) 판별 — 영상 제목 ────────────────────────────────────────────
_STORE_KEYS = [
    ("트레이더스", "트레이더스"), ("trader", "트레이더스"),
    ("코스트코", "코스트코"), ("costco", "코스트코"),
    ("홈플러스", "홈플러스"), ("롯데마트", "롯데마트"),
    # "우성 그린 마트"·"우성 식자재 마트" 등 띄어쓰기 변형 → 브랜드 "우성"으로 포착.
    ("우성마트", "우성마트"), ("우성", "우성마트"),
    ("이마트", "이마트"),
]


_MONTHS_EN = {m: i for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"], 1)}
# 한글: (2026. 06. 16 / 2026.06.16 / 2026년 6월 16일
_DT_KO = re.compile(r"(20\d{2})\s*[.\-년]\s*(\d{1,2})\s*[.\-월]\s*(\d{1,2})")
# 영문 월명: June 9, 2026 / May 26, '26
_DT_EN = re.compile(r"([A-Za-z]{3,9})\s+(\d{1,2}),?\s*'?(\d{2,4})")
# 슬래시: 05/27/2026 (MM/DD/YYYY)
_DT_SLASH = re.compile(r"(\d{1,2})/(\d{1,2})/(20\d{2})")


def date_from_title(title):
    """영상 제목에서 촬영/업로드일(YYYY-MM-DD) 추정. upload_date 가 비어있을 때 폴백.
    데이터 관리 원칙③(수집날짜 메타 정확성): 제목의 날짜가 영상이 다루는 가격 기준일이다."""
    t = title or ""
    m = _DT_KO.search(t)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    m = _DT_EN.search(t)
    if m:
        mon = _MONTHS_EN.get(m.group(1).lower())
        if mon:
            d = int(m.group(2))
            y = int(m.group(3))
            y = 2000 + y if y < 100 else y
            if 1 <= d <= 31:
                return f"{y:04d}-{mon:02d}-{d:02d}"
    m = _DT_SLASH.search(t)
    if m:
        mo, d, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
    return ""


def store_from_title(title):
    """영상 제목에서 매장 **기본 라벨**(마트명) 판별. canonical_store 로 지점명 제거.
    못 찾으면 '마트(미상)' — 위치 위장 금지(CLAUDE.md): 모르는 매장을 트레이더스로 단정하지 않는다.
    CMPA-446 반전: 위치(마트명)는 정규화/floor 연속성을 위해 기본 마트명을 유지하되, **지점(매장)**
    은 branch_from_title 로 별도 추출해 `지점` 컬럼·출처에 보존한다(트레이더스 지점별 재고 상이)."""
    t = (title or "").lower()
    for key, label in _STORE_KEYS:
        if key.lower() in t:
            return canonical_store(label)
    return "마트(미상)"


# ── 지점(매장) 판별 — 영상 제목 (CMPA-446 정책 반전) ─────────────────────────
# CMPA-160 은 "위치는 항상 마트명, 지점 미표기"였으나, 보드(CMPA-446)가 "트레이더스점에
# 따라 상품이 다른 경우가 있다 → 어느 지점인지 함께 적어라"로 **반전**했다. 위치(마트명)는
# floor 연속성을 위해 기본 마트명을 유지하고, 지점은 여기서 별도 추출해 provenance 로 보존한다.
# 제목 패턴(실측): '트레이더스 구월점', '코스트코 송도점'(괄호 안 '(날짜. 매장 지점)'),
# '우성 그린 마트'·'우성 식자재 마트'(점 없는 매장 구분), 영어 제목(지점 없음 → 빈값).
_BRANCH_PAREN = re.compile(r"\(([^)]*)\)")
# 'OO점'(구월점·송도점·안산점 …) — 한글/영숫자 1~8 + 점. 단 비-지점 일반어(지점/장점 등)는 제외.
_BRANCH_JEOM = re.compile(r"([가-힣A-Za-z0-9]{1,8}점)")
_BRANCH_STOP = {
    "지점", "시점", "관점", "장점", "단점", "초점", "정점", "중점", "허점",
    "약점", "강점", "요점", "공통점", "차이점", "이점", "출발점", "기준점",
}
# 우성 식자재/그린 마트 등 '점' 없는 매장 구분(우성마트 안의 서로 다른 점포).
_USEONG_VAR = re.compile(r"(우성\s*(?:그린|식자재|농수산|청과|식품|마트)\s*마트?)")


def _jeom_branch(text):
    """문자열에서 비-지점 일반어를 제외한 'OO점' 지점 토큰 추출(없으면 '')."""
    for m in _BRANCH_JEOM.finditer(text or ""):
        tok = m.group(1)
        if tok not in _BRANCH_STOP:
            return tok
    return ""


_DESC_LOCATION = re.compile(r"촬영\s*장소\s*[:：]\s*(.+)", re.MULTILINE)


def branch_from_title(title, description=None):
    """영상 제목(+설명 폴백)에서 트레이더스/코스트코 등 **지점(매장)** 추출. 못 찾으면 '' (미상).
    위치 위장 금지(CLAUDE.md): 모르는 지점을 임의 단정하지 않고 빈값으로 둔다.
    반환 예: '트레이더스 구월점'→'구월점', '코스트코 송도점'→'송도점',
            '우성 식자재 마트'→'우성 식자재 마트', 영어 제목→''.
    @whiskeykey 처럼 제목엔 지점 없고 설명에 '촬영 장소 : 트레이더스  동탄점' 형식으로
    노출하는 채널을 위해 description 폴백을 지원한다(CMPA-446)."""
    t = title or ""
    # 1) 괄호 안 '(날짜. 매장 지점)' 우선 — 'OO점' 토큰
    for seg in _BRANCH_PAREN.findall(t):
        b = _jeom_branch(seg)
        if b:
            return b
    # 2) 우성 식자재/그린 마트 변형(점 없는 매장 구분)
    m = _USEONG_VAR.search(t)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    # 3) 괄호 밖 폴백 — 본문 어디든 'OO점'
    b = _jeom_branch(t)
    if b:
        return b
    # 4) 설명(description) 폴백 — '촬영 장소 : 매장 지점' (@whiskeykey 패턴)
    if description:
        m2 = _DESC_LOCATION.search(description)
        if m2:
            loc_line = re.sub(r"\s+", " ", m2.group(1)).strip()
            # 우성 변형 먼저
            m3 = _USEONG_VAR.search(loc_line)
            if m3:
                return re.sub(r"\s+", " ", m3.group(1)).strip()
            b2 = _jeom_branch(loc_line)
            if b2:
                return b2
    return ""


def store_display(location, branch):
    """위치(마트명)+지점을 reader-visible 라벨로 결합. 지점이 마트명을 이미 포함하면(우성 식자재
    마트) 지점만, 아니면 '마트명 지점'(트레이더스 구월점). 지점 없으면 마트명만."""
    b = (branch or "").strip()
    if not b:
        return location
    if any(base in b for base in ("트레이더스", "코스트코", "롯데마트", "홈플러스",
                                   "이마트", "우성", "마트")):
        return b
    return f"{location} {b}".strip()


# ── 매장(지점) 수집 제외 — OCR 품질 문제로 통째 드롭 (CMPA-497 보드 2026-06-19) ────────
# 우성식자재마트는 프레임OCR 품질이 나빠 신뢰할 수 없다(보드 지시). 격리(감사보존)가 아니라
# 명시적 store-exclusion 으로 **영상 전체를 드롭**한다 — 파서(_USEONG_VAR/_STORE_KEYS)만
# 지우면 영상이 일반 매장으로 오귀속될 수 있으므로, 반드시 명시 제외 리스트로 막는다.
# 범위 = '우성식자재마트'(식자재 변형만; 우성그린마트 등 다른 우성 변형은 이번 범위 밖).
_EXCLUDED_STORES = {"우성식자재마트"}


def _norm_store(s):
    """매장/지점 라벨 정규화(공백 제거) — '우성 식자재 마트' == '우성식자재마트'."""
    return re.sub(r"\s+", "", s or "")


def is_excluded_store(location, branch):
    """위치(마트명) 또는 지점(매장)이 수집 제외 매장이면 True. 띄어쓰기 변형 흡수."""
    return any(_norm_store(v) in _EXCLUDED_STORES for v in (branch, location))


# ── 브랜드-앵커 canonical SKU 퍼지매처 ──────────────────────────────────────
def _squash(s):
    return re.sub(r"[^0-9a-z가-힣]+", "", str(s).lower())


def _age(s):
    m = AGE_RE.search(str(s) or "")
    return m.group(1) if m else None


# OCR 가 용량을 자주 잘라 적는다(700ml→'700m'/'700', 1L→'1l'). 동의어 매칭 전 꼬리 용량 제거.
_VOL_TAIL = re.compile(r"\s*(?:1\.?75\s*l|1\s*l|\d{3,4}\s*m\s*l?|\d{3,4})\s*$", re.I)


def _strip_vol_loose(s):
    """VOL_RE(표준 용량) + OCR 절단 용량 꼬리까지 제거(동의어 키 정규화 전용)."""
    return _VOL_TAIL.sub(" ", VOL_RE.sub(" ", str(s or ""))).strip()


def _brand_key(name_ko):
    """정본 name_ko 에서 브랜드부(숙성년수/용량 토큰 이전) 추출."""
    return VOL_RE.sub(" ", AGE_RE.split(name_ko)[0]).strip()


def _edition_extra(name_ko):
    """정본 name_ko 의 브랜드·년수·용량을 뺀 '서브라벨/에디션' 잔여(squash)."""
    rem = _squash(VOL_RE.sub(" ", AGE_RE.sub(" ", name_ko)))
    return rem.replace(_squash(_brand_key(name_ko)), "")


class SkuMatcher:
    """whisky-list.csv(회사 위스키 마스터)의 정본 SKU 로 OCR 오자를 보정해 canonical id 를
    찾는다. 보수적: 오매칭보다 격리(미매칭)를 선호한다(CMPA-177 가짜 딜 방지).
    브랜드앵커 정본을 whisky-list 로 둔 이유는 __init__ 주석 참고(CMPA-491)."""

    BRAND_MIN = 0.62      # 브랜드부 fuzzy 하한
    SHORT_FRAG = 0.6      # OCR 브랜드부가 매칭 브랜드 길이의 이 비율 미만이면 단편 의심 → 거절
    REM_MIN = 0.34        # 서브라벨 disambiguation 하한
    REM_MARGIN = 0.10     # 1·2위 서브라벨 점수 격차(모호 방지)

    def __init__(self, master_path=None):
        # 브랜드앵커 정본 = whisky-list.csv(회사 위스키 마스터). 과거엔 master-sku.csv 를
        # 읽었으나, master-sku 는 normalize_dataset 이 '이미 매칭된 id'만 추려 **재생성**하는
        # 파생 집계라, 새 SKU(아직 관측 0)는 매칭 앵커로 못 쓰는 닭-달걀 문제가 있었다
        # (CMPA-491 과소수집 근본원인 ①). whisky-list 를 직접 읽으면 새 위스키를 추가하는
        # 즉시 앵커가 되고 재생성에도 보존된다. ref 가격(price_plausible)과 단일 정본을 공유.
        master_path = master_path or os.path.join(ASSETS, "whisky-list.csv")
        self.master = []
        with open(master_path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                cid = (r.get("canonical_id") or r.get("id") or "").strip()
                nm = (r.get("name_ko") or "").strip()
                if cid and nm:
                    self.master.append((cid, nm))
        self.brands = defaultdict(list)
        for cid, nm in self.master:
            self.brands[_squash(_brand_key(nm))].append((cid, nm))
        self.brand_keys = list(self.brands.keys())
        self._load_aliases()
        self.ocr_fixes = self._load_fixes()
        self.ref_price = self._load_ref_prices()

    @staticmethod
    def _load_ref_prices(list_path=None):
        """whisky-list.csv 의 정본 도메스틱 참고가(price_krw_low/high) 적재 → 가격 타당성 가드용."""
        path = list_path or os.path.join(ASSETS, "whisky-list.csv")
        ref = {}
        if not os.path.exists(path):
            return ref
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                cid = (r.get("id") or "").strip()

                def _i(k):
                    try:
                        return int(float(r.get(k) or 0))
                    except (TypeError, ValueError):
                        return 0
                lo, hi = _i("price_krw_low"), _i("price_krw_high")
                if cid and lo > 0:
                    ref[cid] = (lo, hi or lo)
        return ref

    # 정본 참고가(whisky-list) 대비 이 비율 미만/배수 초과면 OCR 가격 오독으로 보고 격리.
    # 보수적(가짜 딜 방지 1순위, CMPA-177): 65%↓ 할인은 실제 마트가로 비현실적이라 차단.
    PRICE_LOW_FRAC = 0.35
    PRICE_HIGH_MULT = 3.0

    def price_plausible(self, cid, price):
        """매칭 정본의 참고가 대비 가격 타당성. 참고가 없으면 통과(보수적).
        반환 (ok, reason). 예: 달모어 2005(ref 670,800) 21,303원 → price_below_ref 격리."""
        ref = self.ref_price.get(cid)
        if not ref or not price:
            return True, ""
        lo, hi = ref
        if price < lo * self.PRICE_LOW_FRAC:
            return False, "price_below_ref"
        if price > hi * self.PRICE_HIGH_MULT:
            return False, "price_above_ref"
        return True, ""

    @staticmethod
    def _load_fixes(fixes_path=None):
        """큐레이션 OCR 오자 사전(assets/whisky-ocr-fixes.csv): 사람이 검증한 글자단위 OCR 혼동
        (예: '글랜피티'→'글렌피딕', '토알살루트'→'로얄 살루트'). 동의어 사전(whisky-aliases)은
        실측상 OCR 깨짐 구제율이 0에 가깝고 느슨히 하면 오매칭('스카치 위스키'→벨즈)이라, 깨진
        글자는 이 정밀 사전으로만 보정(오매칭 0). 없으면 빈 사전(무동작)."""
        path = fixes_path or os.path.join(ASSETS, "whisky-ocr-fixes.csv")
        fixes = []
        if not os.path.exists(path):
            return fixes
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                bad = (r.get("bad") or "").strip()
                good = (r.get("good") or "").strip()
                if bad and good and bad != good:
                    fixes.append((bad, good))
        return fixes

    def _apply_fixes(self, ocr_name):
        s = ocr_name or ""
        for bad, good in self.ocr_fixes:
            if bad in s:
                s = s.replace(bad, good)
        return s

    # ── 동의어 사전(whisky-aliases.csv) 보조 — 정본 매칭이 놓친 OCR 변형 구제 ──────
    ALIAS_FUZZ = 0.85      # 동의어 fuzzy 하한(보수적)
    ALIAS_MARGIN = 0.08    # 1·2위 격차(모호 방지)

    def _load_aliases(self, alias_path=None, list_path=None):
        """whisky-aliases.csv(동의어 사전)를 OCR 보정 보조 인덱스로 적재. master-sku 브랜드앵커
        퍼지가 놓친 OCR 변형을 '큐레이트된 동의어'로 구제(rescue)한다(보드 CMPA-426).
        안전장치: ①저신뢰(confidence=low) 정본 제외(CMPA-177 모호 병합 방지, 예: 탈리스만 9년
        w088) ②한글 별칭만 ③용량 제거 후 squash 키 ④키 충돌(다른 cid)=모호 제거 ⑤fuzzy 는
        숙성년수 일치분만(년수 비대칭=다른 제품)."""
        alias_path = alias_path or os.path.join(ASSETS, "whisky-aliases.csv")
        list_path = list_path or os.path.join(ASSETS, "whisky-list.csv")
        low_conf = set()
        try:
            with open(list_path, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    if (r.get("confidence") or "").strip() == "low":
                        low_conf.add((r.get("id") or "").strip())
        except FileNotFoundError:
            pass
        names = {cid: nm for cid, nm in self.master}
        self.alias_exact = {}            # key -> (cid, name)
        self.alias_entries = []          # (key, cid, name, age) — fuzzy 후보
        amb = set()
        try:
            with open(alias_path, encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
        except FileNotFoundError:
            rows = []
        for r in rows:
            if (r.get("status") or "") != "matched":
                continue
            raw = r.get("raw_name") or ""
            cid = (r.get("canonical_id") or "").strip()
            if not cid or cid in low_conf or not re.search(r"[가-힣]", raw):
                continue
            key = _squash(_strip_vol_loose(raw))
            if len(key) < 4:
                continue
            name = names.get(cid) or (r.get("canonical_name_ko") or "").strip()
            # CMPA-177: 별칭 변형의 숙성년수가 정본과 다르면 다른 제품 → 적재 제외
            # (예: '글렌드로낙 18년'→글렌드로낙 12년 같은 오매핑 별칭 차단).
            if _age(raw) is not None and _age(name) is not None and _age(raw) != _age(name):
                continue
            if key in self.alias_exact and self.alias_exact[key][0] != cid:
                amb.add(key)
            else:
                self.alias_exact[key] = (cid, name)
            # 변형 숙성년수(없으면 None)로 저장 — 위 가드가 raw≠name(둘다 존재) 행을 이미 걸러서
            # 'raw 무년수 → 정본 N년' 같은 큐레이트 별칭(예: 듀어스 캐리비안 스무스)은 보존된다.
            self.alias_entries.append((key, cid, name, _age(raw)))
        for k in amb:
            self.alias_exact.pop(k, None)

    def _alias_rescue(self, ocr_name):
        """정본 매칭 실패분 → 동의어 사전 구제. exact(용량제거 squash) 우선, 실패 시 보수적 fuzzy
        (숙성년수 일치+격차 충족만). 반환 (cid, name, info) 또는 (None, None, None)."""
        key = _squash(_strip_vol_loose(ocr_name))
        if len(key) < 4:
            return None, None, None
        hit = self.alias_exact.get(key)
        if hit:
            return hit[0], hit[1], "alias_exact"
        oage = _age(ocr_name)
        best = None
        second = 0.0
        for akey, cid, name, aage in self.alias_entries:
            if aage != oage:                    # 숙성년수 비대칭 = 다른 제품(CMPA-177)
                continue
            r = difflib.SequenceMatcher(None, key, akey).ratio()
            if best is None or r > best[0]:
                second = best[0] if best else 0.0
                best = (r, cid, name)
            elif r > second:
                second = r
        if best and best[0] >= self.ALIAS_FUZZ and (best[0] - second) >= self.ALIAS_MARGIN:
            return best[1], best[2], f"alias{best[0]:.2f}"
        return None, None, None

    def _detect_brand(self, ocr):
        o = _squash(VOL_RE.sub(" ", AGE_RE.split(ocr)[0]))
        if len(o) < 2:
            return None
        best = None
        for bk in self.brand_keys:
            r = difflib.SequenceMatcher(None, o, bk).ratio()
            if best is None or r > best[1]:
                best = (bk, r, o)
        return best

    def match(self, ocr_name):
        """큐레이션 OCR 오자 보정 → 정본 매칭(master-sku 브랜드앵커 퍼지) → 실패 시 동의어
        사전(whisky-aliases) 구제. 반환 (cid, name_ko, info) 또는 (None, None, reason)."""
        ocr_name = self._apply_fixes(ocr_name)
        cid, name, info = self._match_master(ocr_name)
        if not cid:
            rcid, rname, rinfo = self._alias_rescue(ocr_name)
            if rcid:
                cid, name, info = rcid, rname, rinfo
        # CMPA-177 최종 가드(방어적 중복): OCR 에 명시된 숙성년수가 매칭 정본과 다르면
        # 다른 제품 → 거절. _match_master/_alias_rescue 의 개별 가드를 우회한 경로도 차단.
        if cid and _age(ocr_name) is not None and _age(name) != _age(ocr_name):
            return None, None, "age_mismatch"
        return cid, name, info            # 원래 실패 사유 보존(브랜드저신뢰/년수불일치 등)

    def _match_master(self, ocr_name):
        """master-sku.csv 브랜드앵커 퍼지 매칭. 반환 (cid, name_ko, score) 또는 (None, None, reason)."""
        bd = self._detect_brand(ocr_name)
        if not bd or bd[1] < self.BRAND_MIN:
            return None, None, "brand_lowconf"
        bk, bscore, obrand = bd
        if len(obrand) < self.SHORT_FRAG * len(bk):
            return None, None, "brand_shortfrag"
        oa = _age(ocr_name)
        # 숙성년수 비대칭 = 다른 제품(CMPA-177): 양쪽 년수가 정확히 같은 후보만.
        cands = [(c, n) for c, n in self.brands[bk] if _age(n) == oa]
        if not cands:
            return None, None, "age_mismatch"
        if len(cands) == 1:
            return cands[0][0], cands[0][1], round(bscore, 2)
        # 서브라벨 disambiguation
        orem = _squash(VOL_RE.sub(" ", AGE_RE.sub(" ", ocr_name)))
        orem = orem.replace(obrand, "", 1)
        if not orem:
            # OCR 잔여 없음 → 에디션 토큰 가장 적은 '기본 SKU' 선택(CMPA-177 기본형 우선).
            base = min(cands, key=lambda x: len(_edition_extra(x[1])))
            return base[0], base[1], round(bscore, 2)
        scored = sorted(
            ((difflib.SequenceMatcher(None, orem, _edition_extra(n)).ratio(), c, n)
             for c, n in cands), reverse=True)
        if scored[0][0] >= self.REM_MIN and (
                len(scored) == 1 or scored[0][0] - scored[1][0] >= self.REM_MARGIN):
            return scored[0][1], scored[0][2], round(scored[0][0], 2)
        return None, None, "ambiguous_sku"


# ── 적재 ───────────────────────────────────────────────────────────────────
# CMPA-448 이전(지점 컬럼 신설 전) youtube_ocr CSV 의 레거시 7컬럼 헤더.
# 2026-04/05 등 backfill 미적용 월파일이 이 헤더를 갖는다.
LEGACY_SCHEMA = ["술이름", "가격_KRW", "위치", "가져온날짜", "출처", "신뢰도", "비고"]


def _migrate_file_to_schema(path):
    """레거시 7컬럼(지점 없음) youtube_ocr CSV 를 현행 8컬럼(SCHEMA)으로 **위치기반** 마이그레이션.
    헤더가 SCHEMA 와 다른 채로 8컬럼 행을 append 하면 DictReader 가 행을 오정렬하므로
    (지점 값을 가져온날짜로 읽는 등), raw csv.reader 로 positional 처리해 헤더·폭을 통일한다.
    반환: 마이그레이션 수행 여부."""
    if not os.path.exists(path):
        return False
    with open(path, encoding="utf-8-sig", newline="") as f:
        rd = list(csv.reader(f))
    if not rd or rd[0] == SCHEMA:
        return False
    out = []
    for row in rd[1:]:
        if not row:
            continue
        if len(row) == len(LEGACY_SCHEMA):          # 레거시 7컬럼: 위치 뒤에 지점 삽입
            d = dict(zip(LEGACY_SCHEMA, row)); d["지점"] = ""
        else:                                       # 8컬럼(또는 기타) — 앞에서부터 매핑
            d = {k: (row[i] if i < len(row) else "") for i, k in enumerate(SCHEMA)}
        out.append({k: d.get(k, "") for k in SCHEMA})
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=SCHEMA)
        w.writeheader(); w.writerows(out)
    sys.stderr.write(f"[migrate] {path}: 레거시 헤더 → 8컬럼(SCHEMA) 통일 ({len(out)}행)\n")
    return True


def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _yyyymmdd(s):
    s = (s or "").strip()
    if re.fullmatch(r"\d{8}", s):
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        return s
    return ""


def _vol_label(volume_ml, raw_name):
    """용량 라벨(700ml/1L) 복원 — result.csv volume_ml 우선, 없으면 이름에서."""
    try:
        v = int(float(volume_ml))
    except (TypeError, ValueError):
        v = None
    if not v:
        m = VOL_RE.search(raw_name or "")
        if m:
            num = float(m.group(1))
            v = int(num * 1000) if m.group(2).lower() in ("l", "리터") else int(num)
    if not v:
        return ""
    if v % 1000 == 0:
        return f"{v // 1000}L"
    return f"{v}ml"


def gate_rows(result_rows, matcher, video_id, channel_label, title, upload_date,
              description=None):
    """result.csv 행 → (accepted[SCHEMA], quarantined[QSCHEMA])."""
    location = store_from_title(title)
    branch = branch_from_title(title, description)  # CMPA-446: 지점(매장) 별도 추출(위치 위장 금지)
    store_disp = store_display(location, branch)
    # CMPA-497: 수집 제외 매장(우성식자재마트)이면 영상 전체 드롭(격리 아님). 사유=metric/log.
    if is_excluded_store(location, branch):
        sys.stderr.write(
            f"[gate] {video_id} 수집 제외 매장 '{store_disp}' — 입력 {len(result_rows)}행 "
            f"전체 드롭 (excluded_store; OCR 품질 CMPA-497)\n")
        return [], []
    date = _yyyymmdd(upload_date) or date_from_title(title) or kst_today()
    label = channel_label if channel_label.startswith("@") else f"@{channel_label}"
    accepted, quarantined = [], []
    for r in result_rows:
        raw = (r.get("name") or "").strip()
        price = r.get("price")
        t0 = (r.get("t_start") or "").strip()
        try:
            price_i = int(float(price))
        except (TypeError, ValueError):
            price_i = 0

        def quar(reason):
            quarantined.append({
                "raw_name": raw, "가격_KRW": price_i, "사유": reason,
                "video_id": video_id, "t_start": t0,
                "비고": f"프레임OCR 격리; {label}/{video_id}",
            })

        nr = noise_reason(raw)
        if nr:
            quar(nr)
            continue
        if is_bundle_noise(raw):
            quar("bundle_glass_set")
            continue
        if not is_sane_price(price_i):
            quar("implausible_price")
            continue
        cid, name_ko, info = matcher.match(raw)
        if not cid:
            quar(info)               # brand_lowconf / age_mismatch / ambiguous_sku ...
            continue
        ok, preason = matcher.price_plausible(cid, price_i)
        if not ok:
            quar(preason)            # price_below_ref / price_above_ref (정본 참고가 대비)
            continue
        vol = _vol_label(r.get("volume_ml"), raw)
        disp = (name_ko + (" " + vol if vol else "")).strip()
        src = f"유튜브 {label} / {video_id}"
        if t0:
            try:
                src += f" @ {int(float(t0))}초"
            except ValueError:
                pass
        # CMPA-446: reader-visible 출처에 지점(매장) 노출(예: 트레이더스 구월점 기준).
        src += f" (프레임OCR · {store_disp})" if branch else " (프레임OCR)"
        accepted.append({
            "술이름": disp,
            "가격_KRW": price_i,
            "위치": location,
            "지점": branch,
            "가져온날짜": date,
            "출처": src,
            "신뢰도": "중",     # OCR 출처 명시(CMPA-424): ASR/마트웹과 동급 보조 신호
            "비고": f"프레임OCR 보정 '{raw}'→{name_ko}; id={cid}; brand_score={info}",
        })
    return accepted, quarantined


def _append_csv(path, schema, rows, dedup_keys=None, dry_run=False):
    # 레거시 7컬럼 월파일에 8컬럼 행을 그냥 append 하면 헤더가 안 맞아 다운스트림 DictReader 가
    # 오정렬된다(2026-04/05). 8컬럼 SCHEMA 적재 전엔 기존 파일을 먼저 위치기반 마이그레이션한다.
    if schema == SCHEMA and not dry_run:
        _migrate_file_to_schema(path)
    existing = _read_csv(path)
    seen = set()
    if dedup_keys:
        seen = {tuple(str(r.get(k, "")) for k in dedup_keys) for r in existing}
    out = []
    for r in rows:
        if dedup_keys:
            key = tuple(str(r.get(k, "")) for k in dedup_keys)
            if key in seen:
                continue
            seen.add(key)
        out.append({k: r.get(k, "") for k in schema})
    if not dry_run and out:
        new_file = not os.path.exists(path)
        with open(path, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=schema)
            if new_file:
                w.writeheader()
            w.writerows(out)
    return len(out)


def _load_processed():
    if os.path.exists(PROCESSED_FILE):
        try:
            return json.load(open(PROCESSED_FILE, encoding="utf-8"))
        except Exception:
            return {}
    return {}


def is_processed(video_id):
    return video_id in _load_processed()


def _mark_processed(video_id, meta):
    os.makedirs(STATE_DIR, exist_ok=True)
    data = _load_processed()
    data[video_id] = meta
    json.dump(data, open(PROCESSED_FILE, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)


def ingest(result_path, video_id, channel_label, title, upload_date,
           month=None, dry_run=False, force=False, description=None):
    if not force and is_processed(video_id):
        sys.stderr.write(f"[ingest] {video_id} 이미 처리됨 — skip (멱등). --force 로 재처리\n")
        return {"skipped": True}
    rows = _read_csv(result_path)
    matcher = SkuMatcher()
    accepted, quarantined = gate_rows(rows, matcher, video_id, channel_label,
                                      title, upload_date, description=description)
    date = _yyyymmdd(upload_date) or date_from_title(title) or kst_today()
    ym = month or date[:7]
    acc_path = os.path.join(PRICES_DIR, f"{ym}_youtube_ocr.csv")
    quar_path = os.path.join(PRICES_DIR, f"{ym}_youtube_ocr_quarantine.csv")
    n_acc = _append_csv(acc_path, SCHEMA, accepted,
                        dedup_keys=["술이름", "가격_KRW", "위치", "지점", "가져온날짜"],
                        dry_run=dry_run)
    n_quar = _append_csv(quar_path, QSCHEMA, quarantined,
                         dedup_keys=["raw_name", "가격_KRW", "video_id"],
                         dry_run=dry_run)
    if not dry_run:
        if n_acc:
            snap = snapshot(acc_path, run_date=kst_today())
            if snap:
                sys.stderr.write(f"[ingest] 스냅샷 -> {snap}\n")
        _mark_processed(video_id, {
            "date": date, "channel": channel_label, "title": title,
            "input_rows": len(rows), "accepted": n_acc, "quarantined": n_quar,
            "processed_at": kst_today(),
        })
    # 인접 프레임의 동일 관측(예: 275초·276초 같은 가격표)은 같은 한 건이다 — CSV 적재와
    # 동일 키로 intra-batch dedup 해서 반환한다. 안 그러면 다운스트림(변경분류→블로그/이메일)이
    # 같은 제품을 N건으로 중복 집계한다(발행 정직성, CMPA-459). 가격변동 행은 키가 달라 보존된다.
    accepted_distinct = []
    _seen = set()
    for a in accepted:
        key = tuple(str(a.get(k, "")) for k in ("술이름", "가격_KRW", "위치", "지점", "가져온날짜"))
        if key in _seen:
            continue
        _seen.add(key)
        accepted_distinct.append(a)
    sys.stderr.write(
        f"[ingest] {video_id} ({store_from_title(title)} / {date}) — "
        f"입력 {len(rows)}행 → 적재 {n_acc} / 격리 {n_quar}"
        f"{' [dry-run]' if dry_run else ''}\n  적재: {acc_path}\n")
    # 사람이 읽을 요약(적재분, 중복 관측 collapse)
    for a in accepted_distinct:
        sys.stderr.write(f"    ✓ {a['술이름']}  {a['가격_KRW']:,}원  ({a['비고']})\n")
    return {"accepted": n_acc, "quarantined": n_quar,
            "acc_path": acc_path, "quar_path": quar_path,
            "accepted_rows": accepted_distinct, "quarantined_rows": quarantined}


# ── 지점 백필 (CMPA-446) ─────────────────────────────────────────────────────
# 기존 {YM}_youtube_ocr.csv 는 CMPA-160 시절 적재라 `지점` 컬럼이 없다. 출처에 박힌
# video_id 로 제목을 **유튜브에서 재조회**(보드 핵심 요청)해 지점을 백필하고 8컬럼으로 재기록한다.
_SRC_VID = re.compile(r"/\s+([0-9A-Za-z_\-]{6,})\s+[@(]")


def _video_id_from_src(src):
    m = _SRC_VID.search(src or "")
    return m.group(1) if m else ""


def _title_for_video(video_id, prefer_state=True):
    """video_id → (제목, 설명, via). 처리상태 캐시(ocr_processed.json) 우선, 없으면 yt-dlp
    재조회(라이브). @whiskeykey 처럼 지점이 **설명(촬영 장소)** 에만 있는 영상을 위해 제목과
    설명을 함께 가져온다(CMPA-484: 백필이 설명 미조회라 지점 누락하던 버그 수정).
    캐시 경로는 제목만 보존하므로 설명은 ''(설명 폴백이 필요하면 prefer_state=False)."""
    if prefer_state:
        meta = _load_processed().get(video_id) or {}
        if meta.get("title"):
            return meta["title"], meta.get("description", ""), "state"
    try:
        import subprocess
        sep = "\x1f"                              # title 과 (멀티라인) description 구분자
        r = subprocess.run(
            ["yt-dlp", "--no-warnings", "--print", f"%(title)s{sep}%(description)s",
             f"https://www.youtube.com/watch?v={video_id}"],
            capture_output=True, text=True, timeout=90)
        if r.returncode == 0 and r.stdout.strip():
            title, _, desc = r.stdout.partition(sep)
            return title.strip().splitlines()[0] if title.strip() else "", desc, "yt-dlp"
    except Exception as e:                       # noqa: BLE001
        sys.stderr.write(f"[backfill] {video_id} yt-dlp 실패: {e}\n")
    return "", "", "miss"


def backfill_branch(csv_path, prefer_state=False, dry_run=False):
    """기존 youtube_ocr CSV 에 `지점` 컬럼을 백필(8컬럼 재기록). prefer_state=False 면
    유튜브에서 제목을 재조회(보드 요청). 반환 {video_id: branch} 요약."""
    rows = _read_csv(csv_path)
    if not rows:
        sys.stderr.write(f"[backfill] {csv_path} 비어있음 — skip\n")
        return {}
    vids = []
    for r in rows:
        v = _video_id_from_src(r.get("출처", ""))
        if v and v not in vids:
            vids.append(v)
    title_branch = {}
    for v in vids:
        title, desc, via = _title_for_video(v, prefer_state=prefer_state)
        # CMPA-484: 설명(촬영 장소) 폴백 포함 — @whiskeykey 영어 제목 영상의 동탄점 등 복구.
        b = branch_from_title(title, desc)
        loc = store_from_title(title) if title else ""
        title_branch[v] = {"title": title, "branch": b, "loc": loc, "via": via}
        sys.stderr.write(f"[backfill] {v} via {via}: 지점={b or '(미상)'}  ← {title[:48]}\n")
    out = []
    for r in rows:
        v = _video_id_from_src(r.get("출처", ""))
        info = title_branch.get(v, {})
        branch = info.get("branch", "")
        loc = r.get("위치", "")
        nr = {k: r.get(k, "") for k in SCHEMA}      # 8컬럼(지점 포함), 결측은 빈값
        nr["지점"] = branch
        # 출처에 지점 노출(idempotent): 기존 '(프레임OCR)' 꼬리에 ' · 매장' 주입.
        src = r.get("출처", "")
        if branch and "(프레임OCR" in src and "·" not in src:
            src = src.replace("(프레임OCR)",
                              f"(프레임OCR · {store_display(loc, branch)})")
        nr["출처"] = src
        out.append(nr)
    if not dry_run:
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=SCHEMA)
            w.writeheader()
            w.writerows(out)
        sys.stderr.write(f"[backfill] {csv_path} — {len(out)}행 재기록(지점 컬럼 추가)\n")
    else:
        sys.stderr.write(f"[backfill] {csv_path} — {len(out)}행 [dry-run]\n")
    return {v: i["branch"] for v, i in title_branch.items()}


# 적재 CSV 의 정본 dedup 키(= ingest _append_csv 와 동일). 동일 (제품,가격,위치,지점,날짜)는 한 건.
ACC_DEDUP_KEYS = ["술이름", "가격_KRW", "위치", "지점", "가져온날짜"]


def reconcile_file(csv_path, prefer_state=False, dry_run=False):
    """레거시 월파일 정합화(CMPA-489): ① 7→8컬럼 위치기반 마이그레이션 ② 지점 백필
    (촬영 장소→동탄점 등) ③ 정본 키로 중복행 collapse. 레거시 7컬럼 행과 신규 8컬럼 행이
    같은 제품인데 지점 비대칭으로 중복되던 문제(예: 라가불린 11년 지점없음 + 동탄점)를 해소한다.
    반환: {'before': n, 'after': m, 'dropped': k}."""
    _migrate_file_to_schema(csv_path)               # ① 헤더·폭 통일(raw positional)
    backfill_branch(csv_path, prefer_state=prefer_state, dry_run=False)  # ② 지점 채움
    rows = _read_csv(csv_path)                       # ③ 정본 키 dedup(첫 행 보존)
    seen, out = set(), []
    for r in rows:
        key = tuple(str(r.get(k, "")) for k in ACC_DEDUP_KEYS)
        if key in seen:
            continue
        seen.add(key); out.append({k: r.get(k, "") for k in SCHEMA})
    dropped = len(rows) - len(out)
    if not dry_run:
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=SCHEMA)
            w.writeheader(); w.writerows(out)
    sys.stderr.write(f"[reconcile] {csv_path}: {len(rows)}행 → {len(out)}행 "
                     f"(중복 {dropped}행 제거){' [dry-run]' if dry_run else ''}\n")
    return {"before": len(rows), "after": len(out), "dropped": dropped}


# ── 격리 재심사 (CMPA-491) ───────────────────────────────────────────────────
# 매칭사전(whisky-list.csv 브랜드앵커·OCR 오자사전)을 확장하면 과거에 격리된 '진짜 위스키'가
# 이제 매칭된다. 영상을 다시 다운로드/OCR 하지 않고, 감사로그인 격리 CSV 를 갱신된 매처로
# **재심사**해 복구분을 accepted CSV 로 옮기고 격리에서 제거한다(과소수집 사후 복구).
_SRC_LABEL = re.compile(r"유튜브\s+(@\S+)\s+/")


def _accepted_meta_by_video(acc_rows):
    """기존 적재행에서 video_id → 영상 메타(위치·지점·날짜·채널라벨) 추출. 재심사 복구행이
    같은 영상의 메타를 그대로 쓰도록(메타 위장 금지: 적재행 없는 영상은 복구 대상에서 제외)."""
    meta = {}
    for r in acc_rows:
        v = _video_id_from_src(r.get("출처", ""))
        if not v or v in meta:
            continue
        m = _SRC_LABEL.search(r.get("출처", ""))
        meta[v] = {
            "위치": r.get("위치", ""),
            "지점": r.get("지점", ""),
            "가져온날짜": r.get("가져온날짜", ""),
            "label": m.group(1) if m else "",
        }
    return meta


def reprocess_quarantine(ym, dry_run=False):
    """{YM}_youtube_ocr_quarantine.csv 를 갱신된 매칭사전으로 재심사(CMPA-491 과소수집 복구).
    노이즈/번들/저가 사전게이트는 그대로 적용하고, 이제 정본 매칭 + 가격타당성을 통과하는 격리행을
    accepted CSV 로 복구한 뒤 격리 CSV 에서 제거한다. 영상 메타(위치/지점/날짜/채널)는 같은
    video_id 의 기존 적재행에서 가져온다 — 적재행이 없는 영상은 메타 부재로 복구하지 않고 격리 유지
    (메타 위장 금지, CLAUDE.md). 멱등: 재실행해도 이미 복구된 행은 dedup 으로 중복 적재 안 됨."""
    acc_path = os.path.join(PRICES_DIR, f"{ym}_youtube_ocr.csv")
    quar_path = os.path.join(PRICES_DIR, f"{ym}_youtube_ocr_quarantine.csv")
    acc_rows = _read_csv(acc_path)
    quar_rows = _read_csv(quar_path)
    if not quar_rows:
        sys.stderr.write(f"[reprocess] {quar_path} 비어있음 — skip\n")
        return {"recovered": 0, "remaining": 0}
    meta_by_v = _accepted_meta_by_video(acc_rows)
    matcher = SkuMatcher()
    recovered, remaining, skipped_nometa = [], [], 0
    for q in quar_rows:
        raw = (q.get("raw_name") or "").strip()
        try:
            price_i = int(float(q.get("가격_KRW") or 0))
        except (TypeError, ValueError):
            price_i = 0
        v = q.get("video_id", "")
        t0 = (q.get("t_start") or "").strip()
        # 사전게이트(노이즈/번들/비상식가)는 재심사에서도 그대로 — 통과 못하면 격리 유지
        if noise_reason(raw) or is_bundle_noise(raw) or not is_sane_price(price_i):
            remaining.append(q)
            continue
        cid, name_ko, info = matcher.match(raw)
        if not cid:
            remaining.append(q)
            continue
        ok, _ = matcher.price_plausible(cid, price_i)
        if not ok:
            remaining.append(q)
            continue
        meta = meta_by_v.get(v)
        if not meta:                       # 적재행 없는 영상 → 메타 부재 → 복구 보류(격리 유지)
            skipped_nometa += 1
            remaining.append(q)
            continue
        location, branch = meta["위치"], meta["지점"]
        label = meta["label"] or "@whiskeypick"
        store_disp = store_display(location, branch)
        vol = _vol_label("", raw)
        disp = (name_ko + (" " + vol if vol else "")).strip()
        src = f"유튜브 {label} / {v}"
        if t0:
            try:
                src += f" @ {int(float(t0))}초"
            except ValueError:
                pass
        src += f" (프레임OCR · {store_disp})" if branch else " (프레임OCR)"
        recovered.append({
            "술이름": disp, "가격_KRW": price_i, "위치": location, "지점": branch,
            "가져온날짜": meta["가져온날짜"], "출처": src, "신뢰도": "중",
            "비고": f"프레임OCR 보정 '{raw}'→{name_ko}; id={cid}; "
                    f"brand_score={info}; CMPA-491 격리재심사 복구",
        })
    n_acc = _append_csv(acc_path, SCHEMA, recovered,
                        dedup_keys=["술이름", "가격_KRW", "위치", "지점", "가져온날짜"],
                        dry_run=dry_run)
    if not dry_run:
        # 격리 CSV 를 '복구되지 않은 행'만으로 재기록(복구분 제거)
        with open(quar_path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=QSCHEMA)
            w.writeheader()
            for q in remaining:
                w.writerow({k: q.get(k, "") for k in QSCHEMA})
        if n_acc:
            snap = snapshot(acc_path, run_date=kst_today())
            if snap:
                sys.stderr.write(f"[reprocess] 스냅샷 -> {snap}\n")
    sys.stderr.write(
        f"[reprocess] {ym}: 격리 {len(quar_rows)}행 재심사 → 복구 적재 {n_acc} / "
        f"격리 잔존 {len(remaining)} (메타부재 보류 {skipped_nometa})"
        f"{' [dry-run]' if dry_run else ''}\n")
    for a in recovered[:80]:
        sys.stderr.write(f"    ✓ {a['술이름']}  {a['가격_KRW']:,}원  ({a['출처']})\n")
    return {"recovered": n_acc, "remaining": len(remaining),
            "skipped_nometa": skipped_nometa}


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--reprocess-quarantine", metavar="YYYY-MM",
                    help="해당 월 격리 CSV 를 갱신된 매칭사전으로 재심사·복구(CMPA-491)")
    ap.add_argument("--backfill-branch", metavar="CSV",
                    help="기존 youtube_ocr CSV 에 지점 컬럼 백필(유튜브 제목 재조회)")
    ap.add_argument("--reconcile", metavar="CSV",
                    help="레거시 월파일 정합화(7→8컬럼 마이그레이션+지점 백필+중복 collapse, CMPA-489)")
    ap.add_argument("--prefer-state", action="store_true",
                    help="백필 시 yt-dlp 재조회 대신 처리상태 캐시 제목 우선")
    ap.add_argument("--result", help="frame_ocr result.csv 경로")
    ap.add_argument("--video", help="video_id")
    ap.add_argument("--channel-label", default="@whiskeypick")
    ap.add_argument("--title", default="", help="영상 제목(위치 판별)")
    ap.add_argument("--upload-date", default="", help="업로드일 YYYYMMDD 또는 YYYY-MM-DD")
    ap.add_argument("--description", default=None,
                    help="영상 설명(촬영 장소 폴백 — @whiskeykey 동탄점 등 지점 추출)")
    ap.add_argument("--month", help="적재 월 YYYY-MM(미지정 시 업로드일에서)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true", help="이미 처리한 video 재처리")
    a = ap.parse_args()
    if a.reprocess_quarantine:
        reprocess_quarantine(a.reprocess_quarantine, dry_run=a.dry_run)
        return
    if a.backfill_branch:
        backfill_branch(a.backfill_branch, prefer_state=a.prefer_state,
                        dry_run=a.dry_run)
        return
    if a.reconcile:
        reconcile_file(a.reconcile, prefer_state=a.prefer_state, dry_run=a.dry_run)
        return
    if not (a.result and a.video):
        ap.error("--result 와 --video 가 필요합니다(또는 --backfill-branch).")
    ingest(a.result, a.video, a.channel_label, a.title, a.upload_date,
           month=a.month, dry_run=a.dry_run, force=a.force,
           description=a.description)


if __name__ == "__main__":
    main()
