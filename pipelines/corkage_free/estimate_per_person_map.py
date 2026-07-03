#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CMPA-66 (board 확장) — 콜키지프리 맵 전 식당 인당 예상 식사비용 추정.

기존 `estimate_per_person.py` 는 3곳(빠넬로·짚불돈·마담풍천)을 손수 구성한
주문 바구니로 정밀 추정한다. 이 스크립트는 그 방법론을 **콜키지프리 맵 전체**
(강남역 91곳 + 합정역 32곳)로 일반화한다.

board 지시: "콜키지프리맵의 강남역·합정역 식당들, 그 식당의 예상 인당 비용을
방금과 같이 근거와 함께 생성." → 전 식당 자동 추정 + 식당별 근거 컬럼.

방법(투명·결정론):
  1) 콜키지프리 finder CSV 에서 식당·rid·대분류·lat/lng 를 읽는다.
  2) DiningCode 프로필 JSON-LD 메뉴(라이브 정가)를 식당별로 긁는다.
  3) 메뉴에서 '음료'를 제외하고 가격대 하한 이상을 '대표메뉴(main)'로 본다.
  4) **대분류별 주문 패턴 상수**(1인 몇 인분 + 사이드 가산)를 적용:
       1인 비용 = 대표메뉴가격 × 인분/인 + 사이드/인
     아낌/표준/넉넉 = 대표메뉴 25%/중앙값/75% 분위로 밴드.
  5) 손수 구성한 3곳(CURATED)은 그 값을 그대로 override(연속성 유지).

음식값 기준(콜키지프리=위스키 지참, 술값 별도). 각 식당 '근거' 컬럼에 모델·메뉴
표본 수·중앙값을 명시한다. 메뉴 데이터가 없으면 confidence=메뉴없음 으로 표시.

산출: data/corkage-free/콜키지프리_인당비용_전체.{csv,md}  (지도 조인키 rid/lat/lng 포함)
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import sys
import time

import requests

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)
from pipelines.common.dated import snapshot  # noqa: E402

PROFILE = "https://www.diningcode.com/profile.php?rid="
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
OUT_DIR = os.path.join("data", "corkage-free")
CACHE_PATH = os.path.join(OUT_DIR, "_cache", "menus.json")
STATIONS = ["강남역", "합정역", "마포역"]  # 마포역 추가 (CMPA-79)

# DiningCode 는 AWS WAF 로 빠른 연속 요청(≈70+건)에서 'Human Verification' 차단을
# 건다(~150초 후 자동 해제, 실측). → 차단 감지 시 쿨다운 후 재시도 + 메뉴 캐시로
# 재실행 시 재크롤 회피(자원 절약·재차단 방지).
FETCH_SLEEP = 1.2       # 정상 요청 간격(차단 회피)
WAF_COOLDOWN = 160      # 차단 감지 시 대기(초)
WAF_MAX_COOLDOWNS = 4   # rid 1건당 최대 쿨다운 횟수

_CACHE = None


def _load_cache() -> dict:
    global _CACHE
    if _CACHE is None:
        try:
            _CACHE = json.load(open(CACHE_PATH, encoding="utf-8"))
        except (OSError, ValueError):
            _CACHE = {}
    return _CACHE


def _save_cache() -> None:
    os.makedirs(os.path.dirname(CACHE_PATH), exist_ok=True)
    json.dump(_CACHE, open(CACHE_PATH, "w", encoding="utf-8"), ensure_ascii=False)

# 대분류별 인당 정규화 파라미터(음식값, 1인 기준). — CMPA-66 정밀화(board 5규칙)
#   floor    : 이 가격 미만 메뉴 = 사이드/공깃밥으로 간주(메인 제외)
#   ppg      : 1인 기준 그램(고기·해산물). 메뉴명 그램(150g/630g)을 1인 기준으로 환산.
#   appetite : 1인이 먹는 인분 수(board (4): 1.5인분). 고기집만 1.5, 그 외 1.0
#              (오마카세·코스·1인 1메인 업종에 1.5 곱하면 과대 → 고기에만 적용).
#   meat_only: True 면 '고기'가 아닌 메인(국물/탕/면/밥/튀김 등)을 제외(board (3)).
# 핵심: '메뉴 한 줄 = 1인분' 가정을 버리고 각 메뉴를 **1인 가격으로 정규화**:
#   'N인 세트'→÷N · 'NNNg'→×(ppg/G) · 'N인 이상/부터'=1인가(÷X) · 그 외 단품 1인가.
CAT_MODEL = {
    "고기":          {"floor": 9000,  "ppg": 180, "appetite": 1.5, "meat_only": True},
    "웨스턴(양식)":  {"floor": 12000, "ppg": 0,   "appetite": 1.0, "meat_only": False},
    "물고기·해산물": {"floor": 12000, "ppg": 200, "appetite": 1.0, "meat_only": False},
    "일식":          {"floor": 10000, "ppg": 0,   "appetite": 1.0, "meat_only": False},
    "중식":          {"floor": 7000,  "ppg": 0,   "appetite": 1.0, "meat_only": False},
    "한식·기타":     {"floor": 8000,  "ppg": 0,   "appetite": 1.0, "meat_only": False},
    "바·주류":       {"floor": 8000,  "ppg": 0,   "appetite": 1.0, "meat_only": False},
}
CAT_DEFAULT = {"floor": 9000, "ppg": 0, "appetite": 1.0, "meat_only": False}

_GRAM_RX = re.compile(r"(\d{2,4})\s*g", re.I)
# board (5): 'N인 이상/부터/이상가능' = 1인분 가격(최소 주문 인원 표기) → 나누지 않음.
_MINPARTY_RX = re.compile(r"\d\s*인\s*이상|\d\s*인\s*부터|인\s*이상|인\s*부터")
# 'N인 세트/코스' = 실제 N인용 세트 → ÷N.
_SET_RX = re.compile(r"(\d)\s*인")
# board (1): 점심특선·런치·평일런치 제외.  board (2): 빙수·냉면·음료수 제외.
LUNCH_RX = re.compile(r"점심|런치|평일")
EXCLUDE_RX = re.compile(r"빙수|냉면|샤베트|사베트|아이스크림")
# board (3) 고기집 '고기' 신호: 그램·세트·아래 키워드 중 하나면 고기 메인으로 인정.
MEAT_KW = re.compile(
    r"삼겹|목살|항정|갈비|등심|차돌|우삼겹|돼지|소고기|한우|곱창|막창|대창|육회|토시|"
    r"안창|부채|살치|갈매기|돈마|스테이크|불고기|불갈비|생갈비|뭉티기|특수부위|모둠|"
    r"세트|한판|숙성|초벌|램|양갈비|닭|오리|미등겹|고기|꽃살|소갈비|한돈|이베리코|고깃|"
    r"우대|티본|척아이|살|구이")

# 메뉴명에 들어가면 '음료/주류'로 보고 대표메뉴 후보에서 제외(콜키지프리=술 지참).
DRINK_RX = re.compile(
    "하이볼|사이다|콜라|펩시|소주|맥주|생맥|막걸리|와인|사케|청하|복분자|"
    "음료|주스|에이드|스무디|콜드브루|커피|라떼|아메리카노|아아|보틀|병맥|"
    "토닉|진저|하리보|티(?:라떼)?$|차\\b|글라스|잔\\)|샴페인|하우스와인"
)

# 손수 구성한 3곳(estimate_per_person.py)의 값 그대로 override.
CURATED = {
    "JSpWFEZBrAsB": (23500, 32000, 63500, "큐레이션 바구니(피자1+파스타1÷2인)"),
    "4tPbVrNHU2AN": (24350, 34500, 43950, "큐레이션 바구니(모둠한판+사이드÷2인)"),
    "YowFb2ExbhbA": (58000, 78000, 110000, "큐레이션(오마카세 1인정찰+음료최소)"),
}


def _parse_menu(html: str) -> list[tuple[str, int]]:
    out = []
    for nm, price in re.findall(
            r'"name":"([^"]{1,40})","offers":\{"@type":"Offer","price":"([0-9,]+)원"',
            html):
        try:
            out.append((nm.strip(), int(price.replace(",", ""))))
        except ValueError:
            continue
    return out


def fetch_menu(rid: str) -> list[tuple[str, int]]:
    """캐시 우선. 미스 시 WAF-aware GET(차단이면 쿨다운 후 재시도)."""
    cache = _load_cache()
    if rid in cache:
        return [(n, p) for n, p in cache[rid]]   # json list → tuple
    cooldowns = 0
    while True:
        try:
            html = requests.get(PROFILE + rid, headers={"User-Agent": UA},
                                timeout=25).text
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] {rid} fetch 실패: {e}", file=sys.stderr)
            return []
        blocked = "Human Verification" in html or len(html) < 5000
        if blocked and cooldowns < WAF_MAX_COOLDOWNS:
            cooldowns += 1
            print(f"  [WAF] {rid} 차단 감지 → {WAF_COOLDOWN}s 쿨다운"
                  f"({cooldowns}/{WAF_MAX_COOLDOWNS})", file=sys.stderr)
            time.sleep(WAF_COOLDOWN)
            continue
        if blocked:
            print(f"  [WAF] {rid} 쿨다운 후에도 차단 — 스킵", file=sys.stderr)
            return []
        menu = _parse_menu(html)
        cache[rid] = [[n, p] for n, p in menu]   # 빈 메뉴도 캐시(진짜 메뉴없음)
        if len(cache) % 8 == 0:
            _save_cache()
        time.sleep(FETCH_SLEEP)
        return menu


def q(vals, frac):
    """정렬 리스트에서 분위값(선형보간). vals 비어있지 않다고 가정."""
    s = sorted(vals)
    if len(s) == 1:
        return s[0]
    pos = frac * (len(s) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def round100(x) -> int:
    return int(round(x / 100.0) * 100)


def _normalize_item(nm: str, price: int, ppg: int):
    """메뉴 1줄 → (1인_가격, 정규화_라벨).
    board (5): 'N인 이상/부터'는 1인분 가격 → 나누지 않음.
    'N인 세트'는 ÷N. 그램은 1인 ppg 환산. 그 외 단품 1인가."""
    if _MINPARTY_RX.search(nm):          # 'N인 이상' = 최소주문 표기, 1인가
        return float(price), f"{nm} {price:,}원/인(N인이상=최소주문, 1인가)"
    mN = _SET_RX.search(nm)
    if mN and int(mN.group(1)) >= 2 and re.search(r"세트|코스|플래터|상차림", nm):
        n = int(mN.group(1))
        pp = price / n
        return pp, f"{nm} {price:,}원 ÷{n}인세트 = {round100(pp):,}/인"
    mG = _GRAM_RX.search(nm)
    if mG and ppg:
        g = int(mG.group(1))
        if g >= 80:
            pp = price * ppg / g
            return pp, f"{nm} {price:,}원({g}g)→1인{ppg}g = {round100(pp):,}/인"
    return float(price), f"{nm} {price:,}원/인"


def _party_size(nm: str):
    """메뉴명의 '먹는 인원수' 표기 → 나눌 인원수(float). 없으면 None.
    board: '2인','2~3인','4인' = 그 인원이 먹는 양 → ÷인원. 단 'N인 이상/부터'(최소주문)는 제외."""
    if _MINPARTY_RX.search(nm):
        return None
    mr = re.search(r"(\d)\s*[~\-]\s*(\d)\s*인", nm)   # 범위 'N~M인' → 평균
    if mr:
        return (int(mr.group(1)) + int(mr.group(2))) / 2
    ms = re.search(r"(\d)\s*인", nm)                  # 단일 'N인'
    if ms and int(ms.group(1)) >= 2:
        return float(ms.group(1))
    return None


def _is_main(nm: str, p: int, floor: int, meat_only: bool) -> bool:
    """이 메뉴가 '대표 메인'인지. board (1)(2)(3) 제외 규칙 적용."""
    if DRINK_RX.search(nm) or LUNCH_RX.search(nm) or EXCLUDE_RX.search(nm):
        return False                      # (1)런치 (2)빙수·냉면·음료
    if p < floor:                         # 사이드·공깃밥·소품
        return False
    if meat_only and not (_GRAM_RX.search(nm) or re.search(r"세트|한판|모둠", nm)
                          or MEAT_KW.search(nm)):
        return False                      # (3)고기집: 고기 아닌 메인(국물/탕/면/밥) 제외
    return True


def estimate(daebun: str, menu: list[tuple[str, int]]):
    """인당 정규화 모델 → (low, typ, high, confidence, 근거, 정규화내역[list])."""
    m = CAT_MODEL.get(daebun, CAT_DEFAULT)
    floor, ppg, appetite, meat_only = m["floor"], m["ppg"], m["appetite"], m["meat_only"]
    mains = [(nm, p) for nm, p in menu if _is_main(nm, p, floor, meat_only)]

    # board: 인원수('2인','2~3인','4인')가 적힌 가게는 **그 메뉴만** ÷인원 → 평균.
    # 고기집은 기존 정규화(세트÷N + 그램 + 1.5인분)가 검증됨 → 그대로 유지(제외).
    if daebun != "고기":
        party = []
        for nm, p in mains:
            ps = _party_size(nm)
            if ps:
                pp = p / ps
                party.append((pp, f"{nm} {p:,}원 ÷{ps:g}인 = {round100(pp):,}/인"))
        if party:
            pps = [u[0] for u in party]
            avg = sum(pps) / len(pps)
            lo, hi = min(pps), max(pps)   # min/max 밴드(아낌≤표준≤넉넉 보장)
            conf = "보통(인원표기 평균)" if len(party) >= 3 else "낮음(인원표기 적음)"
            basis = (f"인당(인원표기 평균, {daebun}): 인원수 적힌 메뉴 {len(party)}종 "
                     f"÷인원 평균 = {round100(avg):,}원")
            labels = [lab for _, lab in sorted(party, key=lambda u: -u[0])][:16]
            return round100(lo), round100(avg), round100(hi), conf, basis, labels

    units = [_normalize_item(nm, p, ppg) for nm, p in mains]
    if not units:   # 메인 0 → meat_only·floor 완화 폴백(음료/런치/빙수만 제외)
        units = [_normalize_item(nm, p, ppg) for nm, p in menu
                 if not (DRINK_RX.search(nm) or LUNCH_RX.search(nm) or EXCLUDE_RX.search(nm))]
    if not units:
        return None, None, None, "메뉴없음", f"{daebun} 인당 정규화: 메뉴 데이터 없음(추정 보류)", []
    pps = [u[0] for u in units]
    lo, mid, hi = q(pps, 0.25), statistics.median(pps), q(pps, 0.75)
    low, typ, high = round100(lo * appetite), round100(mid * appetite), round100(hi * appetite)
    conf = "보통" if len(units) >= 3 else ("낮음(메뉴적음)" if menu else "메뉴없음")
    appe = f" ×{appetite}인분" if appetite != 1.0 else ""
    basis = (f"인당 정규화({daebun}): 메인 {len(units)}종 1인가 중앙값 "
             f"{round100(mid):,}원{appe} = {typ:,}원")
    labels = [lab for _, lab in sorted(units, key=lambda u: -u[0])][:16]
    return low, typ, high, conf, basis, labels


def won(n) -> str:
    return f"{n:,}원" if isinstance(n, int) else "—"


def load_rows(station: str):
    p = os.path.join(OUT_DIR, f"{station}_콜키지프리.csv")
    return list(csv.DictReader(open(p, encoding="utf-8-sig")))


def main() -> int:
    ap = argparse.ArgumentParser(description="콜키지프리 맵 전 식당 인당비용 추정")
    ap.add_argument("--stations", nargs="*", default=None,
                    help="추정할 역 목록(기본=내장 STATIONS). routine 은 매니페스트 live 역을 전달.")
    a = ap.parse_args()
    stations = a.stations if a.stations else STATIONS

    all_out = []
    for st in stations:
        rows = load_rows(st)
        print(f"\n##### {st}: {len(rows)}곳 추정 시작 #####")
        for i, r in enumerate(rows, 1):
            # 식당ID(신규) 우선, 구 CSV의 다이닝코드링크(URL) 폴백 — CMPA-102
            rid = (r.get("식당ID") or r.get("다이닝코드링크") or "").split("rid=")[-1]
            daebun = r.get("대분류", "")
            menu = fetch_menu(rid)
            low, typ, high, conf, basis, labels = estimate(daebun, menu)
            all_out.append({
                "역": st, "식당명": r["식당명"], "rid": rid,
                "카테고리": r.get("카테고리", ""), "대분류": daebun,
                "1인_아낌": low, "1인_표준": typ, "1인_넉넉": high,
                "confidence": conf, "lat": r.get("lat", ""),
                "lng": r.get("lng", ""), "메뉴수": len(menu), "근거": basis,
                "정규화내역": " | ".join(labels),
            })
            if i % 10 == 0 or i == len(rows):
                print(f"  {st} {i}/{len(rows)} … {r['식당명']}: "
                      f"표준 {won(typ)} ({conf})")
    _save_cache()

    # CSV
    csv_path = os.path.join(OUT_DIR, "콜키지프리_인당비용_전체.csv")
    cols = ["역", "식당명", "rid", "카테고리", "대분류",
            "1인_아낌", "1인_표준", "1인_넉넉", "confidence",
            "lat", "lng", "메뉴수", "근거", "정규화내역"]
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for row in all_out:
            w.writerow(row)
    snapshot(csv_path)  # _runs/ 날짜 스냅샷 → diff_corkage_map 인당비용 ±15% 베이스라인 누적
    print(f"\n[CSV] {csv_path}  ({len(all_out)}곳)")

    # 요약 통계
    have = [r for r in all_out if isinstance(r["1인_표준"], int)]
    nomenu = [r for r in all_out if r["confidence"] == "메뉴없음"]
    print(f"  추정성공 {len(have)}곳 / 메뉴없음 {len(nomenu)}곳")

    # Markdown (역별 표 + 대분류 평균)
    lines = [
        "# 콜키지프리 맵 — 식당별 1인 예상 식사비용 (CMPA-66 확장)",
        "",
        "> DiningCode 라이브 정가 메뉴 + **대분류별 주문 패턴 모델**(대표메뉴 중앙값 "
        "× 인분/인 + 사이드)로 추정. **음식값 기준**(콜키지프리=위스키 지참, 술값 별도).",
        "> 손수 구성한 3곳(빠넬로·짚불돈·마담풍천)은 큐레이션 값 적용. "
        "근거·표본수는 CSV `근거`/`메뉴수` 컬럼 참조.",
        "",
    ]
    # 대분류 평균(표준)
    bycat = {}
    for r in have:
        bycat.setdefault(r["대분류"], []).append(r["1인_표준"])
    lines += ["## 대분류 평균 (1인 표준)", "",
              "| 대분류 | 식당수 | 평균 1인 표준 |", "|---|--:|--:|"]
    for cat, vals in sorted(bycat.items(), key=lambda x: -statistics.mean(x[1])):
        lines.append(f"| {cat} | {len(vals)} | {round100(statistics.mean(vals)):,}원 |")

    for st in stations:
        sub = [r for r in all_out if r["역"] == st]
        sub_sorted = sorted(
            sub, key=lambda r: (r["1인_표준"] if isinstance(r["1인_표준"], int) else -1),
            reverse=True)
        lines += ["", f"## {st} ({len(sub)}곳, 1인 표준 내림차순)", "",
                  "| 식당 | 대분류 | 아낌 | 표준 | 넉넉 | 신뢰도 |",
                  "|---|---|--:|--:|--:|---|"]
        for r in sub_sorted:
            lines.append(
                f"| {r['식당명']} | {r['대분류']} | {won(r['1인_아낌'])} "
                f"| **{won(r['1인_표준'])}** | {won(r['1인_넉넉'])} | {r['confidence']} |")

    lines += [
        "", "## 방법·한계",
        "- 대분류별 주문 패턴(인분/사이드)은 업종 통념 기반 상수 → CSV `근거` 에 식당별 적용내역 공개.",
        "- 정가 메뉴 기반 추정치(실제 객단가는 추가주문·음료로 변동). 메뉴 JSON-LD 없는 곳은 '메뉴없음' 표시.",
        "- 콜키지프리라 위스키는 본인 지참 → 동급 식당 대비 '술값' 절감이 핵심.",
        "- 지도 활용: `rid`/`lat`/`lng` 로 콜키지프리 마커와 조인 → 팝업에 '1인 표준' 노출(→ CMPA-68).",
        "",
        "_출처: DiningCode 프로필 메뉴(라이브). 생성: estimate_per_person_map.py_",
    ]
    md_path = os.path.join(OUT_DIR, "콜키지프리_인당비용_전체.md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[MD]  {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
