# -*- coding: utf-8 -*-
"""CMPA-243 위스키 리포트 경화 회귀테스트(픽스처, 라이브 무관).

    python3 scripts/test_whisky_report_hardening.py

커버리지:
  1) 빈티지/컬렉터블 격리(is_collectible) — 1980s·vintage·grand vintage·2L·limited·single cask 는
     격리하되, 'release/bottling 연도'(2018/2025 release)·100 Proof·1.75L·표준 N년 은 표준으로 통과.
  2) build_overseas([2] 홍콩표): 매칭 후보가 컬렉터블뿐이면 행 생성 안 함(가짜딜 방지) — 표·배지 제외.
  3) build_overseas 2.5x 발산 가드: 동일 SKU 가 2.5배↑ 벌어진 오매칭은 [2] 표·🇭🇰 배지에서 제외.
  4) 거짓 수집일: 미래 가져온날짜 행은 리포트 적재에서 격리(future_collected_date).
  5) resolve_collected_date: stale 소스 격리 / 최근 소스는 소스기준일로 스탬프 / 결측은 오늘.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
import whisky_report_tables as W
from pipelines.common.whisky_quality import (
    is_collectible, resolve_collected_date, is_future_collected)

HEADER = "술이름,가격_KRW,위치,가져온날짜,출처,신뢰도,비고\n"
HK_HEADER = "술이름,기준가_KRW\n"


def case(title, fn):
    try:
        fn()
        print(f"  [OK ] {title}")
        return True
    except AssertionError as e:
        print(f"  [FAIL] {title}: {e}")
        return False


def _write_domestic(d, rows):
    with open(os.path.join(d, "2026-06.csv"), "w", encoding="utf-8-sig") as f:
        f.write(HEADER)
        for name, price, loc, date in rows:
            f.write(f"{name},{price},{loc},{date},fixture,중,\n")


def _write_hk(d, rows):
    with open(os.path.join(d, "2026-06_hk_whisky_poc.csv"), "w", encoding="utf-8-sig") as f:
        f.write(HK_HEADER)
        for name, price in rows:
            f.write(f"\"{name}\",{price}\n")


def _reset(d):
    """모듈 전역을 픽스처 폴더로 재설정(HK 보조파일 포함)."""
    cur, past, months, _ = W.resolve_config(d, log=False)
    W.DATA, W.CURRENT, W.PAST, W.MONTHS = d, cur, past, months
    W.MONTH_ORDER = [f[:7] for f in months]
    W.HK_FILE = "2026-06_hk_whisky_poc.csv"


# ── 1) is_collectible 정밀도 ────────────────────────────────────────────────
def test_is_collectible_precision():
    collectible = [
        "Glenmorangie 10 Years Old 1980s 2L Single Malt Scotch Whisky",
        "Glenmorangie Original 1974 Vintage 1999 Limited Release Single Malt",
        "Glenmorangie 23 Year Old 1997 Grand Vintage Malt Bond House No.1",
        "Macallan 18y Single Cask #1234",
        "Yamazaki Limited Edition",
        "발베니 2L 대용량",
    ]
    standard = [
        "Macallan - Double Cask, 12y, 2018 release, 40%",   # 보틀링 연도(컬렉터블 아님)
        "Macallan - Double Cask, 12y, 2025 release, 40%",
        "Glenmorangie Traditional 100 Proof Scotch Single Malt",  # 도수
        "Kirkland Signature Blended Scotch 1.75L",          # 표준 대용량 소매
        "조니워커 블랙라벨 12년 1L",                          # 1L 표준 소매
        "발베니 12년 더블우드 700ml",
        "글렌피딕 15년 솔레라",
    ]
    for nm in collectible:
        assert is_collectible(nm), f"컬렉터블로 격리돼야: {nm}"
    for nm in standard:
        assert not is_collectible(nm), f"표준 소매로 통과돼야(오탈락 금지): {nm}"


# ── 2) build_overseas: 컬렉터블뿐이면 행 없음 ────────────────────────────────
def test_overseas_collectible_only_excluded():
    """홍콩 후보가 빈티지 컬렉터블 1종뿐이면 글렌모렌지 행을 만들지 않는다(가짜 '국내 94%↓' 방지).
    표준 소매가가 함께 있으면 그 표준가로 정상 행을 만든다(컬렉터블은 무시)."""
    with tempfile.TemporaryDirectory() as d:
        _write_domestic(d, [("글렌모렌지 오리지널 10년 700ml", 88800, "트레이더스", "2026-06-01")])
        # (a) 컬렉터블뿐
        _write_hk(d, [("Glenmorangie 10 Years Old 1980s 2L Single Malt", 1378860)])
        _reset(d)
        agg, disp = W.load()
        _ov, ovrows = W.build_overseas(agg, disp)
        assert not any("글렌모렌지" in r[0] for r in ovrows), \
            f"컬렉터블뿐이면 행을 만들면 안 됨(가짜딜): {[r[0] for r in ovrows]}"
        assert not W.hk_cheaper_keys(ovrows), "가짜 🇭🇰↓ 배지도 없어야"
        # (b) 표준 소매가 함께 → 표준가로 정상 행(컬렉터블 무시)
        _write_hk(d, [("Glenmorangie 10 Years Old 1980s 2L Single Malt", 1378860),
                      ("Glenmorangie Original 10 Years Old", 120000)])
        _reset(d)
        agg, disp = W.load()
        _ov, ovrows = W.build_overseas(agg, disp)
        gm = [r for r in ovrows if "글렌모렌지" in r[0]]
        assert len(gm) == 1, f"표준가 있으면 정상 1행: {[r[0] for r in ovrows]}"
        assert gm[0][3] == 120000, f"홍콩가는 컬렉터블(1.37M)이 아니라 표준 120k 여야: {gm[0]}"


# ── 3) 2.5x 발산 가드 ───────────────────────────────────────────────────────
def test_overseas_divergence_guard():
    """컬렉터블 키워드가 없어도 동일 SKU 국내↔홍콩가가 2.5배↑ 벌어지면 오매칭으로 보고 제외.
    글렌피딕 12년 국내 84,800 ↔ 홍콩 '12y'(키워드無) 990,000(11.7배) → [2] 표·🇭🇰 배지 모두 제외."""
    with tempfile.TemporaryDirectory() as d:
        _write_domestic(d, [("글렌피딕 12년 700ml", 84800, "트레이더스", "2026-06-01")])
        _write_hk(d, [("Glenfiddich 12y Special Reserve", 990000)])   # 발산(오매칭 가정)
        _reset(d)
        agg, disp = W.load()
        _ov, ovrows = W.build_overseas(agg, disp)
        assert not any("글렌피딕" in r[0] for r in ovrows), \
            f"2.5배↑ 발산 매칭은 제외돼야: {[r[0] for r in ovrows]}"
        assert not W.hk_cheaper_keys(ovrows), "발산 매칭의 🇭🇰 배지도 없어야"


# ── 4) 미래 수집일 격리 ─────────────────────────────────────────────────────
def test_future_collected_date_quarantined():
    """가져온날짜가 오늘(RUN_DATE)보다 미래인 행은 리포트 적재에서 버린다(거짓 스탬프)."""
    old = os.environ.get("RUN_DATE")
    os.environ["RUN_DATE"] = "2026-06-08"
    try:
        with tempfile.TemporaryDirectory() as d:
            _write_domestic(d, [("위스키정상", 70000, "코스트코", "2026-06-08"),
                                ("위스키미래", 60000, "코스트코", "2026-06-09")])  # 미래
            _reset(d)
            agg, disp = W.load()
            assert W.DROPPED_QUALITY.get("future_collected_date") == 1, \
                f"미래 수집일 1행이 격리돼야: {dict(W.DROPPED_QUALITY)}"
            names = {k for k in agg}
            assert any("위스키정상" in k for k in names), "정상 행은 적재돼야"
            assert not any("위스키미래" in k for k in names), "미래 수집일 행은 적재되면 안 됨"
    finally:
        if old is None:
            os.environ.pop("RUN_DATE", None)
        else:
            os.environ["RUN_DATE"] = old


# ── 5) resolve_collected_date 정책 ──────────────────────────────────────────
def test_resolve_collected_date():
    today = "2026-06-08"
    # 결측/형식오류 → 오늘
    assert resolve_collected_date("", today) == (today, "")
    assert resolve_collected_date("2024", today) == (today, "")
    # 2개월↑ 과거 소스 → 격리
    assert resolve_collected_date("2024-01-15", today) == ("", "stale_source")
    assert resolve_collected_date("2026-04-08", today) == ("", "stale_source")  # 정확히 2개월
    # 최근(2개월 미만) 소스 → 오늘이 아니라 소스기준일로 스탬프
    assert resolve_collected_date("2026-05-20", today) == ("2026-05-20", "")
    assert resolve_collected_date("2026-06-01", today) == ("2026-06-01", "")
    # is_future_collected
    assert is_future_collected("2026-06-09", today) is True
    assert is_future_collected("2026-06-08", today) is False
    assert is_future_collected("bad", today) is False


def main():
    results = [
        case("빈티지/컬렉터블 격리 정밀도(is_collectible)", test_is_collectible_precision),
        case("[2]홍콩표: 컬렉터블뿐이면 행 없음(가짜딜 방지)", test_overseas_collectible_only_excluded),
        case("[2]홍콩표: 2.5x 발산 가드(오매칭 제외 + 배지 제외)", test_overseas_divergence_guard),
        case("거짓 수집일: 미래 가져온날짜 격리", test_future_collected_date_quarantined),
        case("resolve_collected_date 정책(stale 격리·소스기준일 스탬프)", test_resolve_collected_date),
    ]
    n = sum(results)
    print(f"\n결과: {n}/{len(results)} 통과")
    if n != len(results):
        raise SystemExit(1)
    print("CMPA-243 위스키 리포트 경화 회귀테스트 모두 통과 ✅")


if __name__ == "__main__":
    main()
