#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_youtube_ocr_gate.py — CMPA-424 프레임OCR 품질게이트 회귀 테스트.

데모 result.csv(트레이더스 k3GQq, 23행, OCR 노이즈 다수)를 입력으로 ingest_ocr.gate_rows
를 돌려, **비제품 노이즈/오자/비위스키가 floor 에 새지 않는지**를 고정한다.

핵심 불변식(어기면 데이터 오염):
  · 매대 안내문("19세…판매", "해산물", "과일·채소")·숫자뭉치는 노이즈로 격리.
  · OCR 오자는 정본 id 로 보정되거나(예: 글렌피릭→w007 글렌피딕 15년) 격리 — **오매칭 0**.
  · 적재된 모든 행은 canonical id 가 비고에 박혀 있고 가격이 상식적(≥15,000).
  · 보수성: 모호/저신뢰 매칭은 격리(가짜 딜 방지 CMPA-177).
실행: python3 scripts/test_youtube_ocr_gate.py   (exit 0=통과)
"""
import csv
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pipelines.youtube_traders.frame_ocr.ingest_ocr import (  # noqa: E402
    SkuMatcher, gate_rows, noise_reason, store_from_title,
    branch_from_title, store_display)

DEMO = os.path.join(ROOT, "pipelines", "youtube_traders", "frame_ocr",
                    "_demo", "k3GQq_-rD1k", "result.csv")

# 적재(통과)되어야 하는 OCR 오자 → 정본 id (오매칭 시 즉시 실패)
EXPECT_MATCH = {
    "글렌피릭15년700ml": "w007",          # 글렌피딕 15년 (오자 보정)
    "포로지스 싱글배털 750m": "w078",       # 포 로지스 싱글배럴
    "이글레어10년750ml": "w076",          # 이글 레어 10년
    "메이커스마크1L": "w071",              # 메이커스 마크
    "조니워커블랙루비700ml": "w052",        # 조니워커 블랙 루비
    "커티삭프로히비션 1L": "w058",          # 커티삭 프로히비션
    "날모어 12년 700ml": "w023",          # 달모어 12년 (브랜드 오자)
    "달오어2005빈터지700m": "w024",        # 달모어 2005 빈티지
    "글랜피티 14년 버번 캐스크 700m": "w006",  # 글렌피딕 14년 버번배럴 (큐레이션 OCR 오자사전 CMPA-426)
}
# 반드시 격리되어야 하는 비제품 노이즈(floor 에 새면 안 됨)
EXPECT_NOISE = [
    "만 19세미만청소년에게는절대 판매하지요",
    "해산물", "과일·체소", "과일·채소", "더그127000", "남두15700m",
]
# 다른 제품으로 절대 매칭되면 안 되는 위험 오자(비위스키/cheap blend/꼬냑) — 격리 기대
EXPECT_QUAR = [
    "레이아린V.S.0.P700ml",     # 레미마틴 VSOP(꼬냑) — 위스키 아님
    "다카라 미야자키망고 700ml",   # 비위스키
    "탈리스만위스키1L",          # cheap blend ≠ 탈리스커/탈리스만 9년 싱글몰트
    "라이드199031년700m",        # 브랜드 단편 — 오매칭 금지
]


def fail(msg):
    print(f"  ✗ FAIL: {msg}")
    return 1


def _expected_source_latest_floor(cid, max_age_days=40):
    """CMPA-697: 정규화 CSV(normalized_prices)에서 ``cid`` 의 기대 floor 를 **독립 재계산**한다.
    하드코딩(옛 109,800) 대신 '소스(매장)별 최신 관측가 중 최소값'(CMPA-496) 규칙을 게이트가
    데이터로부터 직접 산출 → 트레이더스가 가격을 올리든 내리든(예: 06-16 109,800 → 06-22
    89,800 −20,000 할인) floor 가 따라가는 게 정상임을 검증한다. 반환 (price, source, prev)|None.

    소스 키 규칙은 _domestic_floor_lookup 과 동일: 데일리샷(온라인 셀러)은 ``dailyshot/<channel>``
    복합키로 분리, 물리 매장은 channel 병합(youtube_ocr·youtube_martweb 트레이더스 = 같은 매장).
    이 재계산값과 생산 경로(_domestic_floor_lookup)의 출력이 어긋나면 stale-min 회귀/배선 깨짐이다."""
    from datetime import datetime, timedelta
    from pipelines.common.source_floor import per_source_latest_floor
    from pipelines.youtube_traders.frame_ocr import run_ocr_collection
    from pipelines.youtube_traders.frame_ocr import ingest_ocr
    try:
        cutoff = (datetime.strptime(ingest_ocr.kst_today(), "%Y-%m-%d")
                  - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
    except ValueError:
        cutoff = ""
    obs = []
    try:
        with open(run_ocr_collection.NORM_PRICES, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if (r.get("canonical_id") or "").strip() != cid:
                    continue
                if (r.get("exclude_reason") or "").strip():
                    continue
                if (r.get("market") or "").strip() not in ("KR", "KR-DS"):
                    continue
                d = (r.get("date") or "").strip()
                if cutoff and d < cutoff:
                    continue
                try:
                    p = int(str(r.get("price_krw", "")).replace(",", ""))
                except (ValueError, TypeError):
                    continue
                if p < 15000:
                    continue
                fam = (r.get("source_family") or "").strip()
                ch = (r.get("channel") or "").strip()
                src = f"dailyshot/{ch or '?'}" if fam == "dailyshot" else (ch or fam)
                obs.append((src, d, p))
    except FileNotFoundError:
        return None
    return per_source_latest_floor(obs) if obs else None


def _is_source_latest_price(cid, source_label, price, max_age_days=40):
    """CMPA-697 직접 불변식: floor 가 그 소스의 **최신 날짜 관측가**인지 검증한다.
    stale-min 회귀(같은 소스의 옛 저가를 집음)를 per_source_latest_floor 재계산과 별개로
    독립 확인한다 — ``source_label`` 의 최신 날짜 관측가들 중 ``price`` 가 있으면 True.
    (소스 키 규칙은 _expected_source_latest_floor 와 동일.)"""
    from datetime import datetime, timedelta
    from pipelines.youtube_traders.frame_ocr import run_ocr_collection
    from pipelines.youtube_traders.frame_ocr import ingest_ocr
    try:
        cutoff = (datetime.strptime(ingest_ocr.kst_today(), "%Y-%m-%d")
                  - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
    except ValueError:
        cutoff = ""
    latest_date, latest_prices = "", set()
    try:
        with open(run_ocr_collection.NORM_PRICES, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if (r.get("canonical_id") or "").strip() != cid:
                    continue
                if (r.get("exclude_reason") or "").strip():
                    continue
                if (r.get("market") or "").strip() not in ("KR", "KR-DS"):
                    continue
                d = (r.get("date") or "").strip()
                if cutoff and d < cutoff:
                    continue
                try:
                    p = int(str(r.get("price_krw", "")).replace(",", ""))
                except (ValueError, TypeError):
                    continue
                if p < 15000:
                    continue
                fam = (r.get("source_family") or "").strip()
                ch = (r.get("channel") or "").strip()
                src = f"dailyshot/{ch or '?'}" if fam == "dailyshot" else (ch or fam)
                if src != source_label:
                    continue
                if d > latest_date:
                    latest_date, latest_prices = d, {p}
                elif d == latest_date:
                    latest_prices.add(p)
    except FileNotFoundError:
        return True                                      # 데이터 없으면 강제 안 함
    return (not latest_prices) or price in latest_prices


def main():
    rows = list(csv.DictReader(open(DEMO, encoding="utf-8-sig")))
    assert rows, "데모 result.csv 비어있음"
    matcher = SkuMatcher()
    accepted, quarantined = gate_rows(
        rows, matcher, "k3GQq_-rD1k", "@whiskeypick",
        "트레이더스 위스키 가격 정보 (2026.06.08 구월점)", "20260608")

    # 적재행: raw→id 매핑 추출(비고에 id= 박힘)
    acc_by_raw = {}
    for a in accepted:
        m = re.search(r"보정 '([^']+)'→.*id=(w\d+)", a["비고"])
        if m:
            acc_by_raw[m.group(1)] = m.group(2)
    quar_raws = {q["raw_name"] for q in quarantined}

    errs = 0
    # 1) 위치 판별
    if store_from_title("트레이더스 위스키 가격") != "트레이더스":
        errs += fail("store_from_title 트레이더스 판별 실패")

    # 2) 기대 매칭 — 정확한 정본 id 로 적재
    for raw, cid in EXPECT_MATCH.items():
        got = acc_by_raw.get(raw)
        if got != cid:
            errs += fail(f"매칭 기대 {raw!r}→{cid}, 실제 {got!r}")

    # 3) 노이즈 — 반드시 격리(적재 금지)
    for raw in EXPECT_NOISE:
        if raw in acc_by_raw:
            errs += fail(f"노이즈가 적재됨: {raw!r} (격리됐어야)")
        if raw not in quar_raws:
            errs += fail(f"노이즈가 격리목록에 없음: {raw!r}")

    # 4) 위험 오자 — 반드시 격리(오매칭 금지)
    for raw in EXPECT_QUAR:
        if raw in acc_by_raw:
            errs += fail(f"위험 오자가 적재됨(오매칭): {raw!r}")

    # 5) 모든 적재행: 가격 상식 + canonical id 존재
    valid_ids = {c for c, _ in matcher.master}
    for a in accepted:
        if int(a["가격_KRW"]) < 15000:
            errs += fail(f"적재행 비상식 가격: {a['술이름']} {a['가격_KRW']}")
        m = re.search(r"id=(w\d+)", a["비고"])
        if not m or m.group(1) not in valid_ids:
            errs += fail(f"적재행 canonical id 누락/오류: {a['술이름']}")

    # 6) noise_reason 단위
    if not noise_reason("만 19세미만 판매금지"):
        errs += fail("noise_reason 19세 경고 미탐")
    if noise_reason("글렌피딕 15년"):
        errs += fail("noise_reason 정상 제품명 오탐")
    # 6b) 일반 카테고리 단독 라벨(코스트코 슬라이드/Kirkland 노이즈, CMPA-547):
    #     브랜드 없는 카테고리는 차단(오매칭 '스카치위스키'→스카파 방지), 브랜드 붙은 제품은 통과.
    for cat in ("스카치위스키", "스카치 위스키", "버번위스키", "블렌디드 스카치 위스키",
                "캐리비안럼", "런던드라이진"):
        if noise_reason(cat) != "generic_category":
            errs += fail(f"noise_reason 일반카테고리 미탐: {cat!r}")
    for prod in ("글렌피딕 12년", "발베니 12년 아메리칸 오크", "조니워커 블랙라벨",
                 "메이커스 마크", "12년스카치위스키"):
        if noise_reason(prod) == "generic_category":
            errs += fail(f"noise_reason 브랜드 제품 오탐(generic): {prod!r}")

    # 7) 동의어 사전(whisky-aliases) 구제 — 정본 브랜드앵커가 놓친 OCR 변형 보정(CMPA-426 보드).
    #    숙성년수 미표기 실제품(블랙/그린 라벨)을 동의어 사전이 정본으로 구제한다.
    ALIAS_RESCUE = {"조니워커블랙라벨1L": "w050", "조니워커 그린라벨700m": "w042"}
    for raw, cid in ALIAS_RESCUE.items():
        got, _, _info = matcher.match(raw)
        if got != cid:
            errs += fail(f"동의어 구제 기대 {raw!r}→{cid}, 실제 {got!r}")
    # 안전장치: 저신뢰 정본(예: 탈리스만 9년 w088)·비위스키는 동의어로도 구제 금지(CMPA-177).
    ALIAS_MUST_QUAR = ["탈리스만위스키1L", "레이아린V.S.0.P700ml", "다카라 미야자키망고 700ml"]
    for raw in ALIAS_MUST_QUAR:
        got, _, _ = matcher.match(raw)
        if got is not None:
            errs += fail(f"동의어 구제가 저신뢰/비위스키 오매칭: {raw!r}→{got!r} (격리됐어야)")

    # 8) CMPA-443: 숙성년수 비대칭 '병합' 차단 — OCR 의 N년이 사전의 **다른** 년수 정본으로
    #    새면 안 된다(가짜 딜). 단 CMPA-491: 사전에 그 년수 SKU 가 실재하면 그 정본으로의 복구는
    #    정상이다('사전에 없어서 떨군 것'과 '실제 년수가 다른 것'을 구분 — CMPA-177 유지).
    AGE_MUST_QUAR = {
        # 글렌드로낙 15년 SKU 는 사전에 없음 → 12년(w018)으로 병합 금지, 격리 유지.
        "글랜드로낙15년(신청)": "글렌드로낙 12년→15년 age-merge",
        # 라가불린 8년 SKU 도 없음 → 11년으로 병합 금지.
        "라가불린 8년 700ml": "라가불린 11년→8년 age-merge",
    }
    for raw, why in AGE_MUST_QUAR.items():
        got, _, info = matcher.match(raw)
        if got is not None:
            errs += fail(f"숙성년수 비대칭 오매칭({why}): {raw!r}→{got!r} (격리됐어야)")
    # 동일 브랜드 정상 년수는 보존(거짓 거절 금지). CMPA-491: 18년 SKU(w169)가 실재하므로
    # '그렌드로낙 18년'은 18년 정본으로 복구되어야 하고, 12년(w018)으로 새면 안 된다.
    for raw, cid in {"글렌드로낙 12년": "w018", "그렌드로낙 18년": "w169",
                     "글렌피릭15년700ml": "w007"}.items():
        got, _, _ = matcher.match(raw)
        if got != cid:
            errs += fail(f"정상 년수 매칭 회귀: {raw!r}→{cid} 기대, 실제 {got!r}")

    # 9) CMPA-443: 정본 참고가 대비 비현실가(OCR 가격 오독) 격리 — 가짜 딜 방지.
    #    예: 달모어 2005(ref 670,800) 21,303원 / 글렌피딕 18년(ref 256,600) 24,900원.
    PRICE_BAD = [("w024", 21303), ("w115", 24900), ("w115", 79000)]
    for cid, price in PRICE_BAD:
        ok, _ = matcher.price_plausible(cid, price)
        if ok:
            errs += fail(f"비현실가 미격리: id={cid} {price}원 (격리됐어야)")
    PRICE_OK = [("w007", 99800), ("w018", 158000)]   # 참고가 범위 내 — 보존
    for cid, price in PRICE_OK:
        ok, _ = matcher.price_plausible(cid, price)
        if not ok:
            errs += fail(f"정상가 거짓 격리: id={cid} {price}원 (통과됐어야)")

    # 10) CMPA-446: 지점(매장) 파서 — 트레이더스/코스트코/우성 추출, 영어=무지점.
    BRANCH_CASES = {
        "트레이더스 위스키 가격 정보 (2026. 06. 08. 트레이더스 구월점)": "구월점",
        "코스트코 위스키 가격 정보 (2026. 06. 16. 코스트코 송도점)": "송도점",
        "트레이더스 위스키 가격 정보 (2026. 06. 17. 트레이더스 안산점)": "안산점",
        "[위스키 성지] 우성 그린 마트 위스키 가격 정보 (2026. 06. 13)": "우성 그린 마트",
        "[위스키성지] 우성 식자재 마트 위스키 가격 정보 (2026. 06. 06.)": "우성 식자재 마트",
        # 영어 제목 — 지점 정보 없음 → 빈값(위치 위장 금지)
        "All Whiskey Prices Available at Traders (June 9, '26)": "",
        "I'll tell you all the Costco whiskey price information (April 2, 2026)": "",
        # 비-지점 일반어('지점'/'장점' 등)는 지점으로 오인하지 않음
        "트레이더스 위스키 장점 정리": "",
    }
    for title, exp in BRANCH_CASES.items():
        got = branch_from_title(title)
        if got != exp:
            errs += fail(f"지점 파서 기대 {exp!r}, 실제 {got!r} ← {title[:40]!r}")
    # store_display: 위치+지점 결합(지점 없으면 마트명, 점은 'OO OO점', 마트명포함 지점은 그대로)
    DISP_CASES = [
        ("트레이더스", "구월점", "트레이더스 구월점"),
        ("코스트코", "송도점", "코스트코 송도점"),
        ("우성마트", "우성 식자재 마트", "우성 식자재 마트"),
        ("트레이더스", "", "트레이더스"),
    ]
    for loc, br, exp in DISP_CASES:
        got = store_display(loc, br)
        if got != exp:
            errs += fail(f"store_display({loc!r},{br!r}) 기대 {exp!r}, 실제 {got!r}")
    # gate_rows 가 지점 컬럼을 채우는지(구월점 영상) — 적재행 모두 지점=구월점
    if accepted and any(a.get("지점") != "구월점" for a in accepted):
        errs += fail("gate_rows 지점 컬럼 미충전(구월점 기대)")

    # 11) CMPA-496: floor = 소스(매장)별 '최신 관측가' 중 최소값. 같은 소스의 과거 저가는
    #     무효(superseded) — 단순 min() 으로 잡으면 가격 인상을 인하처럼 보이게 한다.
    from pipelines.common.source_floor import per_source_latest_floor
    #  ⓐ 헬퍼 단위: 트레이더스 89,800(옛) → 109,800(최신) ⇒ floor=109,800(옛값 superseded)
    fl = per_source_latest_floor([("트레이더스", "2026-05-27", 89800),
                                  ("트레이더스", "2026-06-09", 109800)])
    if fl != (109800, "트레이더스", 89800):
        errs += fail(f"source_floor 트레이더스 인상 케이스 기대 (109800,트레이더스,89800), 실제 {fl}")
    #  ⓑ 타 매장이 더 싸면 그 최신가가 floor (per-source 최신 후 min)
    fl2 = per_source_latest_floor([("트레이더스", "2026-06-09", 109800),
                                   ("코스트코", "2026-06-10", 95000)])
    if not (fl2 and fl2[0] == 95000 and fl2[1] == "코스트코"):
        errs += fail(f"source_floor 타매장 최저 기대 95000(코스트코), 실제 {fl2}")
    #  ⓒ 실데이터 회귀(CMPA-697): w030(글렌글라사 포트소이) floor 가 '소스별 최신 관측가 중
    #     최소값'(CMPA-496)과 일치하는지 — 기대값을 **하드코딩하지 않고** 정규화 CSV 에서
    #     동일 규칙으로 재계산해 비교한다. 트레이더스가 가격을 올리거나(06-16 109,800) 내려도
    #     (06-22 89,800 −20,000 할인, 7g3YR_98FLY 36초 프레임 실측 확인) floor 가 현재가를
    #     따라가는 게 정상 — 옛 저가를 stale-min 으로 집으면 안 된다. 하드코딩 109,800 은
    #     06-22 실인하로 stale 가 됐다(과거 회귀 사건의 잔재).
    from pipelines.youtube_traders.frame_ocr import run_ocr_collection
    floor = run_ocr_collection._domestic_floor_lookup()
    w030 = floor.get("w030")
    exp_w030 = _expected_source_latest_floor("w030")     # 정규화 CSV 독립 재계산(소스별 최신가)
    if exp_w030 is not None:                    # 데이터에 w030 관측이 있을 때만 강제(데이터 변동 대비)
        if w030 != exp_w030:
            errs += fail(f"w030 floor 기대 {exp_w030}(소스별 최신가 재계산·CMPA-496), 실제 {w030} "
                         f"— stale-min 회귀 또는 floor 배선 깨짐(CMPA-697)")
        # 추가 불변식: floor 는 그 소스의 '최신 날짜' 관측가여야 한다(옛 저가 superseded 금지).
        elif w030 and not _is_source_latest_price("w030", w030[1], w030[0]):
            errs += fail(f"w030 floor {w030[0]}({w030[1]}) 가 해당 소스 최신가가 아님 — stale-min 회귀")

    # 12) CMPA-497: 수집 제외 매장(우성식자재마트) 제목 영상 → 0행 채택 + 0행 격리(영상 전체 드롭).
    #     OCR 품질 문제로 보드가 우성식자재마트 수집을 제외. 격리(감사보존)가 아니라 명시 드롭이라
    #     동일 데모 result.csv 라도 우성식자재마트 제목이면 accepted/quarantined 모두 0이어야 한다.
    from pipelines.youtube_traders.frame_ocr.ingest_ocr import is_excluded_store
    exc_acc, exc_quar = gate_rows(
        rows, matcher, "3Cxa6iOEbxY", "@whiskeypick",
        "[위스키성지] 우성 식자재 마트 위스키 가격 정보 (2026. 06. 06.)", "20260606")
    if exc_acc or exc_quar:
        errs += fail(f"우성식자재마트 영상 미제외: 적재 {len(exc_acc)} / 격리 {len(exc_quar)} (0/0 기대)")
    # 띄어쓰기 변형 흡수 + 범위 가드(우성그린마트는 제외 대상 아님)
    if not is_excluded_store("우성마트", "우성 식자재 마트"):
        errs += fail("is_excluded_store 우성식자재마트(띄어쓰기 변형) 미탐")
    if is_excluded_store("우성마트", "우성 그린 마트"):
        errs += fail("is_excluded_store 우성그린마트 오탐(범위 밖인데 제외됨)")
    if is_excluded_store("트레이더스", "구월점"):
        errs += fail("is_excluded_store 트레이더스 오탐")

    # 13) CMPA-500: 데일리샷 셀러 '트레이더스'(온라인 마켓)는 물리 트레이더스(youtube)와 다른
    #     소스 → 합치면 데일리샷 최신가가 '트레이더스 최신가'로 둔갑하고 youtube 직전가가 붙어
    #     '179,800→185,000 ▲인상' 가짜 라인이 뜬다(현재가 209,800 과 모순). 소스키 분리 검증.
    #  ⓐ 소스키가 다르면(분리) 데일리샷은 직전가 None → ▲인상 혼동 라인 안 생김.
    fl_ds = per_source_latest_floor([("트레이더스", "2026-06-16", 209800),          # 물리(youtube)
                                     ("dailyshot/트레이더스", "2026-06-19", 185000)])  # 데일리샷 셀러
    if fl_ds != (185000, "dailyshot/트레이더스", None):
        errs += fail(f"CMPA-500 데일리샷 분리 기대 (185000,dailyshot/트레이더스,None), 실제 {fl_ds}")
    #  ⓑ 라벨: dailyshot 복합키 → '데일리샷', 물리 채널은 그대로.
    if run_ocr_collection._floor_source_label("dailyshot/트레이더스") != "데일리샷":
        errs += fail("CMPA-500 _floor_source_label(dailyshot/트레이더스) 기대 '데일리샷'")
    if run_ocr_collection._floor_source_label("트레이더스") != "트레이더스":
        errs += fail("CMPA-500 _floor_source_label(트레이더스) 기대 '트레이더스'(물리 매장 그대로)")
    #  ⓒ w030 무회귀(이미 §11ⓒ 강제): 물리 매장은 channel 병합 유지라야 martweb 89,800 stale-min
    #     이 다시 floor 로 안 잡힘 → floor source 가 'dailyshot/...' 로 둔갑하지 않아야 한다.
    w030b = floor.get("w030")
    if w030b is not None and str(w030b[1]).startswith("dailyshot"):
        errs += fail(f"w030 floor source 가 데일리샷으로 둔갑({w030b[1]}) — 물리 매장 병합 깨짐")

    print(f"\n입력 {len(rows)}행 → 적재 {len(accepted)} / 격리 {len(quarantined)}")
    print(f"기대 매칭 {len(EXPECT_MATCH)}건 검증 · 노이즈 {len(EXPECT_NOISE)}건 격리 검증 · "
          f"위험오자 {len(EXPECT_QUAR)}건 오매칭방지 검증")
    if errs:
        print(f"\n❌ {errs}건 실패")
        sys.exit(1)
    print("\n✅ ALL PASS — 프레임OCR 품질게이트 회귀 통과")


if __name__ == "__main__":
    main()
