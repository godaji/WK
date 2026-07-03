#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_brand_value.py — 브랜드별 '가치(value) 추천' deep-dive 대시보드 (CMPA-521 / 부모 CMPA-520).

평면 가격표(build_dashboard.py)의 확장이 아니라, 보드가 원한 **"한 급 위를 아래 급 값에
살 수 있을 때 사라"** 를 잡는 추천 뷰. 8개 브랜드(발베니·조니워커·글렌피딕·글렌리벳·
탈리스커·듀어스·발렌타인·로얄살루트)를 패널로 보여준다.

설계 원칙 (CMPA-520 §6 방법론)
  · ⚠️ 정확 1:1 canonical 매칭 불필요 — **브랜드 × 년수 × CS 속성 레벨**에서 동작한다.
    (이게 '대시보드 109종 병목'을 우회하는 핵심. 자식 B[canonical 등록]와 독립 병렬.)
  · 새 floor/환율 로직을 만들지 않는다 — 검증된 정본을 재사용:
      - 소매 floor   = analyze_attractiveness.load_domestic (source_floor 소스별 최신가 min)
      - 환율(면세)   = fx_latest.json raw_usd.KRW (USD→KRW). 면세=표시가_USD(마일리지 할인가).
      - 속성 파싱    = analyze_attractiveness.norm/vol_of + 본 모듈의 년수/CS/캐스크 파서
      - 노이즈 제외  = whisky_quality.is_bundle_noise / is_collectible

가치(value) 3렌즈 ('지금 사라' 랭킹)
  1) 교차-급(킬러)  : 면세 SKU(년수 A)의 700ml 환산가 ≤ 소매 더 낮은 급(년수 B<A) 가격이면
                      "면세 A년을 소매 B년 값에" 뱃지. (예: 발베니 면세18 212,769 ≤ 소매16 245,000)
  2) 교차-채널      : 같은 급(년수 A) 소매 vs 면세 격차 %. (예: 글렌피딕 18년 면세 절반)
  3) 시계열(지금싼지): 면세 현재가 vs 자기 최근 N일 최저/평균(신라 일별 스냅샷 누적).

패널 = 가격×년수 산점도(소매·면세 2계열, 인라인 SVG·경량) + '지금 사라' 랭킹.

용량: 700ml 환산가(= 100ml단가×7)로 공정 비교(1L 면세를 700ml 소매와 직접 비교 금지).
      실제 병가·용량·100ml단가를 함께 병기(CMPA-507 교훈: 700ml-only 가드가 1L 누락).

CLAUDE.md 필수 준수
  · 모바일 우선(CMPA-255): 360/390/1080 글 안 잘림. 랭킹=카드, 넓은표 overflow-x:auto.
    차트는 경량 인라인 SVG(viewBox+width:100% 로 반응형, 무거운 의존성 없음).
  · 수집 날짜 메타(CMPA-156): 면세 수집일·소매 수집일·환율 기준일 노출. stale 단정 금지.
  · 면세/해외 제외(CMPA-321): 소매 floor 는 면세 안 섞음(load_domestic 가 KR/KR-DS 만).
  · 카피 담백(CMPA-197)·저자 CaskCode(CMPA-198) — 초안이라 발행 전(noindex).

멱등: 같은 입력 → 같은 출력(비결정 값은 입력 데이터의 수집일만 사용).

용법:
  python3 pipelines/dashboard/build_brand_value.py          # deploy/dashboard/brands/index.html
  python3 pipelines/dashboard/build_brand_value.py --out /tmp/x.html
"""
import argparse
import csv
import glob
import html
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

from pipelines.shilla_dutyfree import analyze_attractiveness as aa  # noqa: E402
from pipelines.common import whisky_quality as wq                   # noqa: E402

DATA = os.path.join(ROOT, "data", "whisky-prices")
SHILLA_DIR = os.path.join(ROOT, "data", "shilla-dutyfree")
OUT_DEFAULT = os.path.join(ROOT, "deploy", "dashboard", "brands", "index.html")
DATA_DASH = os.path.join(ROOT, "data", "dashboard")

# ── X축 '등급 사다리'(tier ladder) — NAS 블렌드용 (CMPA-521 보드 2026-06-20) ──
# 보드 지적: "조니워커는 NAS(무연산)라 X축을 년산으로 하면 안 된다. 블랙→더블블랙→그린→골드→
#   블루 순서다." → 무연산 블렌드는 숙성년수 대신 **품질 등급 사다리**를 X축 순서로 쓴다.
#   품질 오름차순으로 나열(낮은 등급=왼쪽). 매칭은 '가장 긴 토큰 우선'(더블블랙이 블랙보다 먼저).
#   '한 급 위를 아래 급 값에' = 높은 등급을 낮은 등급 값에. 가치 모델은 그대로(rank만 교체).
JW_LADDER = [
    ("레드",     ["레드"]),
    ("블랙",     ["블랙"]),                 # 블랙/블랙루비/블랙트리플 (더블블랙은 아래서 더 길게 매칭)
    ("더블블랙", ["더블블랙"]),
    ("그린",     ["그린", "아일랜드그린"]),
    ("골드",     ["골드"]),
    ("18년",     ["18년"]),
    ("XR21년",   ["xr", "21년"]),
    ("블루",     ["블루"]),
    ("프리미엄",  ["킹조지", "엑스오디네어", "엑스오", "킹"]),   # 킹조지5세·엑스오디네어 최상위
]

# 브랜드 카탈로그(후보 superset) — (표시명, 이름 매칭 토큰, 서브라인, 등급사다리)
# 매칭: 위스키명(면세) / canonical_name_ko(소매) 의 정규화 문자열에 토큰이 들어있으면 그 브랜드.
# 서브라인(sublines): 한 브랜드 안에서 '다른 제품군'을 분리하는 키. CMPA-177(다른 제품 토큰=다른
#   SKU): 블렌드 브랜드(발렌타인)는 같은 이름으로 블렌디드(발렌타인 21년)와 싱글몰트(글렌버기 18년)를
#   함께 팔아, 둘을 같은 년수 곡선에 섞으면 '블렌드 21년 ≤ 싱글몰트 18년 값' 같은 교차-제품군 가짜
#   추천이 생긴다. 서브라인 토큰이 있으면 가치 비교(교차-급/교차-채널)를 같은 서브라인끼리만 한다.
# ladder: NAS 블렌드는 등급 사다리(X축=등급). None 이면 X축=숙성년수(age 모드, 싱글몰트 기본).
#
# ⚠️ 표시 브랜드는 build()에서 **면세 SKU ≥ MIN_BRAND_SKU(10)** 인 것만 자동 선별한다
#   (CMPA-521 보드 2026-06-20: "10종 이상 발굴해 추가, 10종 이하(탈리스커 등)는 제거").
#   데이터가 늘면 자동 편입/탈락(self-maintaining). 탈리스커(3)는 카탈로그에 두되 임계로 자동 제외.
# ⚠️ 독립병입(IB) 하우스(고든앤맥패일·시그나토리·더글라스랭)는 카탈로그에서 제외 — 여러 증류소를
#   한 브랜드로 묶어 '가격×년수' 사다리가 성립하지 않는다(교차-증류소 가짜 추천 위험). 보드 재량으로
#   추가 가능.
MIN_BRAND_SKU = 10
BRAND_CATALOG = [
    ("발베니",   ["발베니", "balvenie"], [], None),
    ("조니워커", ["조니워커", "johnnie"], [], JW_LADDER),
    ("글렌피딕", ["글렌피딕", "glenfiddich"], [], None),
    ("글렌리벳", ["글렌리벳", "glenlivet"], [], None),
    ("듀어스",   ["듀어스", "dewar"], [], None),
    ("발렌타인", ["발렌타인", "ballantine"],
     # 순서 중요: 증류소명(글렌버기) 먼저 → 면세 'GLENBURGIE'·소매 '싱글몰트 글렌버기'가 같은
     # 서브라인으로 묶인다. 그 뒤 일반 '싱글몰트'(증류소명 없는 발렌타인 싱글몰트)를 블렌드와 분리.
     [("글렌버기", ["글렌버기", "glenburgie"]),
      ("글렌토커스", ["글렌토커스", "glentauchers"]),
      ("싱글몰트", ["싱글몰트", "singlemalt"])], None),
    ("로얄살루트", ["로얄살루트", "royalsalute"], [], None),
    # 탈리스커(면세 3)·로얄살루트(<10 비프리미엄) 등은 임계로 자동 제외.
    ("탈리스커", ["탈리스커", "talisker"], [], None),
    # ⚠️ CMPA-521 보드 2026-06-20: 달모어·잭다니엘·카발란·시바스리갈은 임계(≥10)를 통과하지만
    #   보드가 명시적으로 제외 요청("빼자") → 카탈로그에서 제외(임계와 무관하게 미표시).
    #   (잭다니엘·카발란은 NAS 위주라 산점도 희소했음.) 보드 재요청 시 복원.
]

# 700ml 환산가 상한·년수 상한 — 초고가 컬렉터블은 '가치 추천' 관심 밖(별도 집계만)
PREMIUM_EQ_CAP = 1_000_000   # 700ml 환산가 100만원 초과 = 컬렉터블 취급
AGE_CAP = 35                 # 35년 초과 = 컬렉터블 취급
TS_WINDOW = 14               # 시계열 '최근 N일' 창 (신라 일별 스냅샷)

# 캐스크/피니시 디스크립터(툴팁 표기용) — 값 계산엔 안 쓰고 설명만
_CASK_KW = [
    ("셰리", "셰리"), ("쉐리", "셰리"), ("sherry", "셰리"),
    ("px", "PX셰리"), ("페드로", "PX셰리"), ("몬틸라", "몬틸라"),
    ("포트", "포트"), ("port", "포트"),
    ("마데이라", "마데이라"), ("madeira", "마데이라"),
    ("버번", "버번"), ("bourbon", "버번"), ("프렌치", "프렌치오크"),
    ("캐리비안", "캐리비안"), ("헝가리안", "헝가리안"), ("미즈나라", "미즈나라"),
    ("피트", "피티드"), ("피티드", "피티드"), ("peat", "피티드"),
]


# ---------------------------------------------------------------------------
# 속성 파서 (브랜드×년수×CS — canonical 매칭 불필요)
# ---------------------------------------------------------------------------
_AGE_KO = re.compile(r"(\d{1,2})\s*년")
_AGE_EN = re.compile(r"(\d{1,2})\s*(?:years?|yo|y\.?o\.?)\b", re.I)
_CS = re.compile(r"캐스크\s*스트[랭렝]|케스크\s*스트[랭렝]|cask\s*strength|\bcs\b|"
                 r"캐스크피니시|아부나흐|배치\s*스트렝스", re.I)


def parse_age(name):
    m = _AGE_KO.search(name)
    if m:
        return int(m.group(1))
    m = _AGE_EN.search(name)
    if m:
        return int(m.group(1))
    return None


def parse_cs(name):
    return bool(_CS.search(name or ""))


def parse_cask(name):
    n = (name or "").lower()
    out = []
    for kw, label in _CASK_KW:
        if kw in n and label not in out:
            out.append(label)
    return out


def fmt_attr(age, cs, casks):
    bits = []
    if age:
        bits.append(f"{age}년")
    else:
        bits.append("무연산")
    if cs:
        bits.append("CS")
    bits.extend(casks[:2])
    return " · ".join(bits)


def match_brand(name, tokens):
    """정규화(공백·기호 제거 소문자) 문자열에 토큰 포함 시 True."""
    n = aa.norm(name)
    return any(t in n for t in tokens)


def tier_rank(name, ladder):
    """이름을 등급 사다리에서 (rank, label) 로. 가장 긴 매칭 토큰 우선(더블블랙>블랙).
    rank = 사다리 위치(1=최저등급). 미매칭이면 (None, None)."""
    n = aa.norm(name)
    best = None  # (token_len, rank, label)
    for i, (label, toks) in enumerate(ladder):
        for t in toks:
            if t in n and (best is None or len(t) > best[0]):
                best = (len(t), i + 1, label)
    return (best[1], best[2]) if best else (None, None)


def assign_ranks(items, ladder):
    """각 항목에 rank(숫자)·rank_label(표시) 부착. ladder 있으면 등급(tier) 모드,
    없으면 숙성년수(age) 모드. rank 없는 항목(NAS·미매칭)은 rank=None → 산점도/가치비교 제외."""
    for it in items:
        if ladder:
            it["rank"], it["rank_label"] = tier_rank(it["name"], ladder)
        else:
            a = it.get("age")
            it["rank"], it["rank_label"] = (a, f"{a}년") if a is not None else (None, None)


# ---------------------------------------------------------------------------
# 입력 로더
# ---------------------------------------------------------------------------
def load_fx():
    p = os.path.join(DATA, "fx", "fx_latest.json")
    fx = json.load(open(p, encoding="utf-8"))
    return float(fx["raw_usd"]["KRW"]), fx.get("asof")


def _shilla_files():
    return sorted(glob.glob(os.path.join(SHILLA_DIR, "신라면세_위스키_*.csv")))


def _shilla_date(path):
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path))
    return m.group(1) if m else ""


def load_dutyfree_latest(usd_krw):
    """최신 신라 위스키 CSV → SKU 리스트(노이즈/미니/매그넘/결측가 제외).

    각 항목: name, code, usd, eq(700ml 환산 KRW), vol, per100, url, sales,
             age, cs, casks, premium(초고가 여부).
    """
    files = _shilla_files()
    if not files:
        return [], ""
    latest = files[-1]
    sdate = _shilla_date(latest)
    out = []
    for r in csv.DictReader(open(latest, encoding="utf-8-sig")):
        name = (r.get("위스키명") or "").strip()
        if not name or wq.is_bundle_noise(name) or wq.is_collectible(name):
            continue
        try:
            usd = float(r.get("표시가_USD") or r.get("할인가_USD"))
        except (TypeError, ValueError):
            continue
        if usd <= 0:
            continue
        vol = aa.vol_of(name) or 700
        if vol < aa.MINI_ML or vol > aa.MAGNUM_ML:
            continue
        krw = round(usd * usd_krw)
        per100 = krw / vol * 100
        eq = round(per100 * 7)            # 700ml 환산가
        age = parse_age(name)
        out.append({
            "name": name, "code": (r.get("상품코드") or "").strip(),
            "usd": usd, "krw": krw, "vol": vol, "per100": round(per100), "eq": eq,
            "url": (r.get("상품URL") or "").strip(),
            "sales": aa._to_int(r.get("누적판매")) if hasattr(aa, "_to_int") else None,
            "age": age, "cs": parse_cs(name), "casks": parse_cask(name),
            "premium": eq > PREMIUM_EQ_CAP or (age is not None and age > AGE_CAP),
        })
    return out, sdate


def dutyfree_timeseries():
    """상품코드 -> [(date, usd), ...] (최근 TS_WINDOW 일 신라 스냅샷). 시계열 렌즈용."""
    files = _shilla_files()[-TS_WINDOW:]
    series = {}
    for p in files:
        d = _shilla_date(p)
        for r in csv.DictReader(open(p, encoding="utf-8-sig")):
            code = (r.get("상품코드") or "").strip()
            try:
                usd = float(r.get("표시가_USD") or r.get("할인가_USD"))
            except (TypeError, ValueError):
                continue
            if code and usd > 0:
                series.setdefault(code, []).append((d, usd))
    for code in series:
        series[code].sort()
    return series


def load_retail():
    """canonical_name_ko -> {eq, low, cur, vol, ch, date}. 소매 floor(면세 제외).

    eq = 700ml 환산가(= low/vol*700). 용량은 normalized 에 직접 없어 이름에서 추정(없으면 700).
    """
    dom = aa.load_domestic()                  # cid -> {name, low, cur, ch, curdate}
    out = []
    for cid, d in dom.items():
        name = d["name"]
        low = d["low"]
        vol = aa.vol_of(name) or 700
        if vol < aa.MINI_ML or vol > aa.MAGNUM_ML:
            continue
        eq = round(low / vol * 700)
        out.append({
            "name": name, "low": round(low), "cur": round(d.get("cur") or low),
            "vol": vol, "eq": eq, "per100": round(low / vol * 100),
            "ch": "/".join(sorted(d.get("ch") or [])), "date": d.get("curdate", ""),
            "age": parse_age(name), "cs": parse_cs(name), "casks": parse_cask(name),
        })
    return out


# ---------------------------------------------------------------------------
# 가치 렌즈 계산 (브랜드 단위)
# ---------------------------------------------------------------------------
def _seg_of(name, sublines):
    """이름이 어느 서브라인(제품군)인지 — 토큰 매칭. 없으면 'main'."""
    n = aa.norm(name)
    for label, toks in sublines:
        if any(t in n for t in toks):
            return label
    return "main"


def compute_brand(df_items, rt_items, ts, sdate, sublines=(), mode="age"):
    """브랜드의 면세/소매 항목에 가치 시그널을 부착하고 '지금 사라' 랭킹을 만든다.

    rank = 비교 축(age 모드=숙성년수, tier 모드=등급 사다리 위치). '한 급 위를 아래 급 값에'
    는 rank 가 더 높은 SKU 를 더 낮은 rank 의 값에 사는 것 — age/tier 공통.
    sublines 가 있으면 교차-급/교차-채널 비교를 같은 서브라인(제품군)끼리만 한다
    (블렌드 vs 싱글몰트 교차-제품군 가짜 추천 방지, CMPA-177).
    """
    unit = "단계" if mode == "tier" else "년"   # gap 단위 표시

    # 컬렉터블(초고가) 분리 — 가치 추천 관심 밖
    df_main = [d for d in df_items if not d["premium"]]
    df_premium = [d for d in df_items if d["premium"]]

    # 소매: (서브라인, rank) -> 최저 eq 행 (가장 보수적인 '소매 한 급 아래 값')
    rt_by_rank = {}   # seg -> {rank: row}
    for r in rt_items:
        a = r.get("rank")
        if a is None:
            continue
        seg = _seg_of(r["name"], sublines)
        bucket = rt_by_rank.setdefault(seg, {})
        if a not in bucket or r["eq"] < bucket[a]["eq"]:
            bucket[a] = r

    ranked = []
    for d in df_main:
        a = d.get("rank")
        d["lens1"] = None   # 교차-급
        d["lens2"] = None   # 교차-채널
        d["lens3"] = None   # 시계열
        d["score"] = 0
        seg = _seg_of(d["name"], sublines)
        seg_ranks = rt_by_rank.get(seg, {})

        # 렌즈 1: 교차-급 (면세 rank A ≤ 소매 rank B 값, B<A) — 가장 높은 B 채택(보수적·신뢰)
        if a is not None:
            best = None
            for B, r in seg_ranks.items():
                if B < a and d["eq"] <= r["eq"]:
                    if best is None or B > best[0]:
                        best = (B, r)
            if best:
                B, r = best
                d["lens1"] = {"b_age": B, "b_label": r.get("rank_label") or f"{B}",
                              "rt_eq": r["eq"], "rt_name": r["name"],
                              "rt_low": r["low"], "gap_years": a - B,
                              "gap_unit": unit, "won": r["eq"] - d["eq"]}
                d["score"] += 100 + (a - B) * 15

        # 렌즈 2: 교차-채널 (같은 rank 소매 vs 면세 격차%) — 면세가 쌀 때만
        if a is not None and a in seg_ranks:
            r = seg_ranks[a]
            if d["eq"] < r["eq"]:
                gap = round((r["eq"] - d["eq"]) / r["eq"] * 100)
                d["lens2"] = {"rt_eq": r["eq"], "rt_name": r["name"], "gap_pct": gap}
                d["score"] += gap

        # 렌즈 3: 시계열 (현재가 vs 최근 N일 최저/평균)
        hist = ts.get(d["code"]) or []
        usds = [u for _, u in hist]
        if len(usds) >= 3:
            lo, avg = min(usds), sum(usds) / len(usds)
            cur = usds[-1]
            if cur <= lo * 1.001:
                d["lens3"] = {"kind": "low", "days": len(usds), "min_usd": lo}
                d["score"] += 25
            elif cur < avg:
                d["lens3"] = {"kind": "below_avg", "days": len(usds),
                              "avg_krw": round(avg / cur * d["krw"])}
                d["score"] += 8

        if d["lens1"] or d["lens2"] or d["lens3"]:
            ranked.append(d)

    ranked.sort(key=lambda x: -x["score"])
    return {
        "df_main": df_main, "df_premium": df_premium, "rt_items": rt_items,
        "rt_by_rank": rt_by_rank, "ranked": ranked, "sdate": sdate, "mode": mode,
    }


# ---------------------------------------------------------------------------
# 인라인 SVG 산점도 (경량·반응형)
# ---------------------------------------------------------------------------
def _is_reco(d):
    """추천(다른 색으로 강조) = 강한 가치 시그널(교차-급 또는 교차-채널). 보드 2026-06-20."""
    return bool(d.get("lens1") or d.get("lens2"))


def svg_scatter(rt_items, df_items, brand, mode="age"):
    """가격(700ml 환산 KRW, log Y) × rank(X) 산점도. 소매·면세 2계열.

    X축 = rank: age 모드=숙성년수, tier 모드=등급 사다리(NAS 블렌드, 보드 2026-06-20).
    rank 없는 SKU(NAS·미매칭)는 산점도에서 제외. ⭐추천(교차급/교차채널) 점은 빨강으로 강조.
    SVG 는 viewBox 로 반응형(width:100%) — 모바일 가로 스크롤 없이 폭에 맞춰 축소.
    """
    pts_rt = [r for r in rt_items if r.get("rank") is not None]
    pts_df = [d for d in df_items if d.get("rank") is not None]
    pts = [(r["rank"], r["eq"]) for r in pts_rt] + [(d["rank"], d["eq"]) for d in pts_df]
    if not pts:
        msg = ("등급 매칭 제품이 없어" if mode == "tier"
               else "년수 표기 제품이 없어(무연산 블렌드 위주)")
        return f'<p class="muted">{msg} 산점도 생략.</p>'

    W, H = 640, 320
    ml, mr, mt, mb = 56, 14, 14, 34
    pw, ph = W - ml - mr, H - mt - mb
    ages = [a for a, _ in pts]
    eqs = [e for _, e in pts if e > 0]
    amin, amax = min(ages), max(ages)
    if amin == amax:
        amin -= 1
        amax += 1
    emin, emax = min(eqs), max(eqs)
    lo, hi = math.log10(max(emin, 1000)), math.log10(emax)
    if hi - lo < 0.1:
        lo -= 0.5
        hi += 0.5

    # rank -> 표시 라벨 (tier 모드는 등급명, age 모드는 'N년')
    rank_label = {}
    for it in pts_rt + pts_df:
        rank_label.setdefault(it["rank"], it.get("rank_label") or f'{it["rank"]}')

    def px(a):
        return ml + pw * (a - amin) / (amax - amin)

    def py(e):
        return mt + ph * (1 - (math.log10(max(e, 1000)) - lo) / (hi - lo))

    xaxis = "등급" if mode == "tier" else "숙성년수"
    parts = [f'<svg viewBox="0 0 {W} {H}" class="scatter" '
             f'role="img" aria-label="{html.escape(brand)} 가격×{xaxis} 산점도" '
             f'preserveAspectRatio="xMidYMid meet">']
    # Y 그리드(가격)
    nice = [30000, 50000, 100000, 200000, 300000, 500000, 1000000]
    for v in nice:
        if v < emin * 0.7 or v > emax * 1.3:
            continue
        y = py(v)
        parts.append(f'<line x1="{ml}" y1="{y:.1f}" x2="{W-mr}" y2="{y:.1f}" class="grid"/>')
        parts.append(f'<text x="{ml-6}" y="{y+3:.1f}" class="axl" '
                     f'text-anchor="end">{v//10000}만</text>')
    # X 눈금
    if mode == "tier":
        ticks = sorted(rank_label)                       # 등급은 전부 표시
    else:
        span = amax - amin
        step = 1 if span <= 8 else (2 if span <= 16 else 5)
        ticks = list(range(amin, amax + 1, step))
    for a in ticks:
        x = px(a)
        lab = rank_label.get(a, f"{a}년" if mode != "tier" else str(a))
        parts.append(f'<text x="{x:.1f}" y="{H-12}" class="axl xtick" '
                     f'text-anchor="middle">{html.escape(lab)}</text>')
    # 점 — 소매(amber 원)
    for r in pts_rt:
        x, y = px(r["rank"]), py(r["eq"])
        tip = f'{r["name"]} · 소매 {r["low"]:,}원 ({r["vol"]}ml)'
        if r["vol"] != 700:
            tip += f' · 700ml환산 {r["eq"]:,}원'
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" class="p-rt">'
                     f'<title>{html.escape(tip)}</title></circle>')
    # 점 — 면세(다이아몬드). ⭐추천=빨강 강조(보드), 일반=gold. 1L 등 비700은 속 빈 마름모.
    for d in pts_df:
        x, y = px(d["rank"]), py(d["eq"])
        reco = _is_reco(d)
        base = "p-reco" if reco else "p-df"
        cls = base if d["vol"] == 700 else f"{base} hollow"
        s = 7 if reco else 6
        tip = f'{d["name"]} · 면세 {d["krw"]:,}원 ({d["vol"]}ml)'
        if reco:
            tip += " · ⭐추천"
        if d["vol"] != 700:
            tip += f' · 700ml환산 {d["eq"]:,}원'
        parts.append(
            f'<rect x="{x-s:.1f}" y="{y-s:.1f}" width="{2*s}" height="{2*s}" '
            f'transform="rotate(45 {x:.1f} {y:.1f})" class="{cls}">'
            f'<title>{html.escape(tip)}</title></rect>')
    parts.append('</svg>')
    return "".join(parts)


# ---------------------------------------------------------------------------
# 렌더 — 브랜드 패널
# ---------------------------------------------------------------------------
def _won(v):
    return f"{v:,}원" if v is not None else "—"


def _shilla_link(name, url):
    if url:
        return (f'<a href="{html.escape(url)}" target="_blank" rel="noopener" '
                f'class="src-link">{html.escape(name)}</a>')
    return html.escape(name)


def _badges(d):
    out = []
    l1, l2, l3 = d["lens1"], d["lens2"], d["lens3"]
    rl = d.get("rank_label") or "—"
    if l1:
        out.append(f'<span class="bdg killer" title="면세 {rl} 700ml환산 '
                   f'{d["eq"]:,}원 ≤ 소매 {l1["b_label"]} {l1["rt_eq"]:,}원">'
                   f'🔥 면세 {rl} → 소매 {l1["b_label"]} 값에</span>')
    if l2:
        out.append(f'<span class="bdg ch" title="동급 {rl} 소매 {l2["rt_eq"]:,}원 '
                   f'(700ml환산)">💳 동급 소매보다 {l2["gap_pct"]}%↓</span>')
    if l3:
        if l3["kind"] == "low":
            out.append(f'<span class="bdg ts" title="최근 {l3["days"]}일 신라 스냅샷 기준">'
                       f'📉 최근 {l3["days"]}일 최저가</span>')
        else:
            out.append(f'<span class="bdg ts" title="최근 {l3["days"]}일 평균 이하">'
                       f'📉 최근평균 이하</span>')
    return " ".join(out)


def render_panel(brand, B):
    df_main = B["df_main"]
    ranked = B["ranked"]
    rt_items = B["rt_items"]
    df_premium = B["df_premium"]

    mode = B.get("mode", "age")
    n_df, n_rt = len(df_main), len(rt_items)
    scatter = svg_scatter(rt_items, df_main, brand, mode=mode)

    # '지금 사라' 랭킹 카드 (추천=교차급/교차채널은 카드도 강조)
    cards = []
    for d in ranked[:8]:
        badges = _badges(d)
        attr = fmt_attr(d.get("age"), d["cs"], d["casks"])
        if mode == "tier" and d.get("rank_label"):
            attr = d["rank_label"] + (" · " + attr if attr and attr != "무연산" else "")
        vtag = "1L" if d["vol"] == 1000 else f'{d["vol"]}ml'
        eqnote = "" if d["vol"] == 700 else f' · 700ml환산 {d["eq"]:,}원'
        detail = (f'<div class="rk-price"><b>{_won(d["krw"])}</b> '
                  f'<small class="muted">/ {vtag} · {d["per100"]:,}원/100ml{eqnote}</small></div>')
        # 렌즈1 근거 한 줄(담백)
        why = ""
        if d["lens1"]:
            l1 = d["lens1"]
            why = (f'<div class="rk-why">소매 {l1["rt_name"]} {l1["rt_low"]:,}원 '
                   f'(700ml환산 {l1["rt_eq"]:,}원)보다 같거나 저렴 — '
                   f'한 급 위(+{l1["gap_years"]}{l1["gap_unit"]})를 그 값에.</div>')
        elif d["lens2"]:
            l2 = d["lens2"]
            why = (f'<div class="rk-why">동급 소매 {l2["rt_name"]} 대비 '
                   f'700ml환산 {l2["gap_pct"]}% 저렴.</div>')
        rkcls = "rkcard reco" if _is_reco(d) else "rkcard"
        cards.append(
            f'<div class="{rkcls}">'
            f'<div class="rk-name">{_shilla_link(d["name"], d["url"])}'
            f'<span class="rk-attr">{html.escape(attr)}</span></div>'
            f'{detail}'
            f'<div class="badges">{badges}</div>'
            f'{why}</div>')
    if not cards:
        cards.append('<p class="muted">현재 가치 시그널(교차급/교차채널/시계열) 해당 없음 — '
                     '면세·소매 비교군이 부족하거나 가격 우위 없음.</p>')

    prem_note = ""
    if df_premium:
        names = ", ".join(html.escape(p["name"][:20]) for p in df_premium[:4])
        prem_note = (f'<p class="muted prem">초고가 컬렉터블 {len(df_premium)}종 제외'
                     f'(700ml환산 100만원↑ 또는 35년↑): {names}…</p>')

    # 탭 진입 시 차트 전에 '추천하는 위스키' 한 줄(보드 2026-06-20) — 1위 가치 SKU
    reco_line = ""
    top = ranked[0] if ranked else None
    if top:
        if top["lens1"]:
            why = f'면세 {top["rank_label"]} → 소매 {top["lens1"]["b_label"]} 값에'
        elif top["lens2"]:
            why = f'동급 소매보다 {top["lens2"]["gap_pct"]}% 저렴'
        elif top["lens3"] and top["lens3"]["kind"] == "low":
            why = f'최근 {top["lens3"]["days"]}일 최저가'
        else:
            why = '최근 평균 이하'
        reco_line = (f'<p class="reco-line">⭐ <b>추천</b> — '
                     f'{_shilla_link(top["name"], top["url"])} '
                     f'<span class="muted">· {html.escape(why)} · {_won(top["krw"])}</span></p>')

    slug = re.sub(r"\s+", "", brand)
    return (
        f'<section class="panel" id="b-{slug}">'
        f'<h2>{html.escape(brand)} '
        f'<small class="muted">면세 {n_df}종 · 소매 {n_rt}종</small></h2>'
        f'{reco_line}'
        f'<div class="chart-wrap">{scatter}</div>'
        f'<p class="chart-cap muted">● 소매최저가 &nbsp; ◆ 면세가 &nbsp; '
        f'<b style="color:var(--red)">◆ 빨강=지금 추천</b>(교차급/교차채널) '
        f'(빈 ◇=1L 등 비표준 용량·700ml 환산) · Y=700ml 환산가(로그) · '
        f'X={"등급(블렌드 NAS — 블랙→블루)" if mode == "tier" else "숙성년수"}. '
        f'점 위에 올리면 상세.</p>'
        f'<h3>🛒 지금 사라 — 가치 랭킹</h3>'
        f'<div class="rklist">{"".join(cards)}</div>'
        f'{prem_note}'
        f'</section>')


def render_html(panels, meta):
    sdate = meta["sdate"]
    usd_krw = meta["usd_krw"]
    fx_asof = meta["fx_asof"]
    rt_date = meta["rt_date"]
    n_killer = meta["n_killer"]

    # 브랜드 탭(보드 2026-06-20): 한 번에 한 브랜드 패널만 표시. 첫 브랜드 기본 활성.
    # 표시 브랜드·순서 = build()가 임계로 선별·정렬한 brand_order.
    tabs = "".join(
        f'<button class="tab{" active" if i == 0 else ""}" '
        f'data-brand="{re.sub(r"\s+", "", b)}" '
        f'onclick="showBrand(\'{re.sub(r"\s+", "", b)}\')">{html.escape(b)}</button>'
        for i, b in enumerate(meta["brand_order"]))

    css = """
:root{--bg:#0f1115;--panel:#161922;--line:#2a2e38;--txt:#f2efe6;--sub:#9aa0aa;
--amber:#e0a84e;--gold:#ffd34e;--green:#34c759;--red:#ff6b6b;--blue:#5ac8fa}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans KR",sans-serif;
line-height:1.5;font-size:15px}
.wrap{max-width:1080px;margin:0 auto;padding:18px 14px 60px}
h1{font-size:20px;margin:2px 0 2px;color:var(--gold)}
.sub{color:var(--sub);font-size:13px;margin:0 0 10px}
.meta{color:var(--sub);font-size:12px;margin:0 0 4px}
.reco-line{margin:8px 0 10px;font-size:14px;color:var(--txt)}
.reco-line b{color:var(--gold)}
.draft{display:inline-block;background:rgba(255,107,107,.16);color:var(--red);
border:1px solid var(--red);border-radius:6px;padding:1px 7px;font-size:11px;font-weight:700;
vertical-align:middle}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0 4px;
position:sticky;top:0;background:var(--bg);padding:8px 0;z-index:5;border-bottom:1px solid var(--line)}
.tab{background:var(--panel);border:1px solid var(--line);color:var(--sub);
border-radius:8px;padding:6px 12px;font-size:13px;cursor:pointer;white-space:nowrap;font-weight:600}
.tab:hover{border-color:var(--amber);color:var(--amber)}
.tab.active{background:rgba(255,211,78,.16);color:var(--gold);border-color:var(--gold)}
.panel{padding-top:8px;display:none}
.panel.active{display:block}
h2{font-size:18px;color:var(--gold);margin:14px 0 8px}
h2 small{font-size:12px;font-weight:400}
h3{font-size:14px;color:var(--amber);margin:16px 0 8px}
/* 차트 max-width(보드 2026-06-20): PC에서 차트가 과도하게 커지지 않게 캡·좌측 정렬 */
.chart-wrap{background:var(--panel);border:1px solid var(--line);border-radius:10px;
padding:8px 6px;max-width:580px}
svg.scatter{width:100%;height:auto;display:block}
svg .grid{stroke:var(--line);stroke-width:1}
svg .axl{fill:var(--sub);font-size:11px}
svg .xtick{font-size:10.5px}
svg .p-rt{fill:var(--amber);opacity:.9}
svg .p-df{fill:var(--gold);opacity:.92}
svg .p-df.hollow{fill:none;stroke:var(--gold);stroke-width:2}
svg .p-reco{fill:var(--red);opacity:.95;stroke:#fff;stroke-width:1}
svg .p-reco.hollow{fill:none;stroke:var(--red);stroke-width:2.5}
.chart-cap{font-size:11.5px;margin:6px 2px 0;max-width:580px}
.rklist{display:grid;gap:10px}
.rkcard{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:10px 12px}
.rkcard.reco{border-left:3px solid var(--red)}
.rk-name{font-weight:700;color:var(--gold);font-size:14.5px}
.rk-attr{color:var(--sub);font-weight:400;font-size:12px;margin-left:6px}
.rk-price{margin:4px 0}
.rk-price b{color:var(--txt)}
.rk-why{color:var(--sub);font-size:12px;margin-top:4px}
.muted{color:var(--sub)}
.prem{font-size:11.5px;margin-top:8px}
a.src-link{color:inherit;text-decoration:underline dotted;text-underline-offset:2px}
.badges{margin-top:6px;display:flex;flex-wrap:wrap;gap:5px}
.bdg{font-size:11px;border-radius:5px;padding:1px 7px;white-space:nowrap;
border:1px solid var(--line)}
.bdg.killer{background:rgba(255,107,107,.16);color:var(--red);border-color:var(--red);font-weight:700}
.bdg.ch{background:rgba(90,200,250,.14);color:var(--blue);border-color:var(--blue)}
.bdg.ts{background:rgba(52,199,89,.14);color:var(--green);border-color:var(--green)}
.legend{list-style:none;padding:0;margin:8px 0 0;display:grid;gap:6px}
.legend li{background:var(--panel);border:1px solid var(--line);border-radius:8px;
padding:8px 10px;font-size:12.5px;color:var(--sub)}
.legend .lg{color:var(--txt);font-weight:700;margin-right:6px}
.foot{margin-top:30px;padding-top:14px;border-top:1px solid var(--line);
color:var(--sub);font-size:12px}
code{word-break:break-all;overflow-wrap:anywhere}
@media(max-width:640px){
  .rk-attr{display:block;margin-left:0;margin-top:2px}
}
"""

    legend = "".join(f'<li><span class="lg">{k}</span>{v}</li>' for k, v in [
        ("◆ 빨강 = 지금 추천", "교차-급 또는 교차-채널 시그널이 있는 면세 SKU를 산점도·랭킹에서 빨강으로 강조."),
        ("🔥 교차-급", "면세 한 급(년수·등급) 위를 소매 아래 급 값에 산다(킬러)."),
        ("💳 교차-채널", "같은 급(년수·등급) 소매보다 면세가 % 저렴(700ml 환산 공정 비교)."),
        ("📉 시계열", f"면세 현재가가 최근 {TS_WINDOW}일 신라 스냅샷 최저/평균 이하(지금 싸다)."),
        ("X축", "싱글몰트=숙성년수. <b>무연산 블렌드(조니워커)=품질 등급 사다리</b>(블랙→더블블랙→그린→골드→블루)."),
    ])

    # 첫 패널만 활성(나머지는 탭 클릭 시 표시)
    body_panels = "".join(
        p.replace('class="panel"', 'class="panel active"', 1) if i == 0 else p
        for i, p in enumerate(panels))
    doc = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>브랜드 가치 추천 대시보드 — CaskCode</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <h1>🥃 브랜드 가치 추천</h1>
  <p class="meta">📅 면세 {sdate or "—"} · 소매 {rt_date or "—"} · 환율 {usd_krw:,.0f}원</p>
  <div class="tabs" role="tablist">{tabs}</div>

  {body_panels}

  <h2>읽는 법 · 범례</h2>
  <ul class="legend">{legend}</ul>
  <p class="sub" style="margin-top:8px">
    · '한 급 위를 아래 급 값에' — 같은 브랜드에서 더 높은 급(년수·등급)을 더 낮은 급 값에 살 수
      있을 때 추천합니다. <b>브랜드 × 년수/등급 × 캐스크·CS 속성 레벨</b>로 계산(정확 1:1 매칭 불필요).<br>
    · 면세가 = 신라 표시가(마일리지 할인가). 가격은 '수집일 기준값'(현재 값 아님 · CMPA-156).
      소매최저가는 면세·해외 제외 국내 소매 floor(CMPA-321). 용량 다른 제품은 <b>700ml 환산가</b>로 비교.<br>
    · '소매 N급 값'은 그 급의 <b>최저가</b> 기준(보수적). 초고가 컬렉터블·잔세트/번들은 제외합니다.
  </p>
  <p class="foot">생성기 <code>pipelines/dashboard/build_brand_value.py</code> ·
  정본 데이터 재사용(analyze_attractiveness · source_floor · fx_latest · whisky_quality) ·
  발행/라우틴 배선 없음(라이브 발행은 CEO 검증 후 보드 go). by CaskCode.</p>
</div>
<script>
(function(){{
  window.showBrand = function(slug, skipHistory){{
    document.querySelectorAll('.panel').forEach(function(p){{
      p.classList.toggle('active', p.id === 'b-' + slug);
    }});
    document.querySelectorAll('.tab').forEach(function(t){{
      t.classList.toggle('active', t.dataset.brand === slug);
    }});
    if (!skipHistory) {{
      history.replaceState(null, '', '?brand=' + encodeURIComponent(slug));
    }}
    window.scrollTo(0, 0);
  }};
  // Restore tab from URL on load
  var initial = new URLSearchParams(location.search).get('brand');
  if (initial && document.querySelector('.tab[data-brand="' + initial + '"]')) {{
    window.showBrand(initial, true);
  }}
}})();
</script>
</body>
</html>
"""
    return doc


# ---------------------------------------------------------------------------
def build():
    usd_krw, fx_asof = load_fx()
    df_all, sdate = load_dutyfree_latest(usd_krw)
    rt_all = load_retail()
    ts = dutyfree_timeseries()
    rt_date = max((r["date"] for r in rt_all if r["date"]), default="")

    # 1차: 브랜드별 면세 SKU 수로 임계(≥MIN_BRAND_SKU) 선별 + 면세 수 내림차순 정렬
    #      (CMPA-521 보드: 10종 이상만 표시, 탈리스커 등 소수 브랜드 자동 제외)
    scored = []
    for brand, tokens, sublines, ladder in BRAND_CATALOG:
        df_b = [d for d in df_all if match_brand(d["name"], tokens)
                and not d["premium"]]
        if len(df_b) >= MIN_BRAND_SKU:
            scored.append((len(df_b), brand, tokens, sublines, ladder))
    scored.sort(key=lambda x: -x[0])
    selected = [(b, t, s, l) for _n, b, t, s, l in scored]

    panels, n_killer = [], 0
    summary = []
    brand_order = []
    for brand, tokens, sublines, ladder in selected:
        df_b = [d for d in df_all if match_brand(d["name"], tokens)]
        rt_b = [r for r in rt_all if match_brand(r["name"], tokens)]
        mode = "tier" if ladder else "age"
        assign_ranks(df_b, ladder)        # rank/rank_label 부착 (age 또는 등급)
        assign_ranks(rt_b, ladder)
        B = compute_brand(df_b, rt_b, ts, sdate, sublines=sublines, mode=mode)
        n_killer += sum(1 for d in B["ranked"] if d["lens1"])
        panels.append(render_panel(brand, B))
        brand_order.append(brand)
        summary.append((brand, len(B["df_main"]), len(rt_b), len(B["ranked"]),
                        sum(1 for d in B["ranked"] if d["lens1"])))

    meta = {"sdate": sdate, "usd_krw": usd_krw, "fx_asof": fx_asof,
            "rt_date": rt_date, "n_killer": n_killer, "brand_order": brand_order}
    doc = render_html(panels, meta)
    return doc, meta, summary


def main():
    ap = argparse.ArgumentParser(description="브랜드 가치 추천 deep-dive 대시보드 (CMPA-521)")
    ap.add_argument("--out", default=OUT_DEFAULT, help="출력 HTML 경로")
    args = ap.parse_args()

    doc, meta, summary = build()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(doc)

    print(f"WROTE {args.out}")
    print(f"  환율 {meta['usd_krw']:,.0f} (기준 {meta['fx_asof']}) · 면세수집 {meta['sdate']} · "
          f"소매수집 {meta['rt_date']}")
    print(f"  교차-급(킬러) 시그널 합계 {meta['n_killer']}건")
    print(f"  {'브랜드':<10}{'면세':>5}{'소매':>5}{'랭킹':>5}{'킬러':>5}")
    for b, nd, nr, nk, kl in summary:
        print(f"  {b:<10}{nd:>5}{nr:>5}{nk:>5}{kl:>5}")


if __name__ == "__main__":
    main()
