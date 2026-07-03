# -*- coding: utf-8 -*-
"""CMPA-429 (보드 CMPA-424 모델, 2026-06-16): '품목 단위 최신 수집일' 신선도 단위테스트(픽스처, 라이브 무관).

    python3 scripts/test_whisky_report_rollover.py

배경/모델 변천:
  · CMPA-166: '항목 단위 최신 *월*' — 옛 월가로 계속 노출(3~5월 기준일 행 다수).
  · CMPA-177: '판매처 전체 sweep' 게이트 — 한 판매처의 가장 최근 sweep 에 없는 항목은 단종으로
    보고 제외. + CMPA-243 부분-sweep 최소크기 가드(작은 부분수집이 sweep 을 가로채 표를 붕괴시키는
    CMPA-241 회귀 방지).
  · CMPA-429(현행, 보드 CMPA-424): **품목 단위 최신 수집일**. 보드: "트레이더스=영상 촬영일 스탬프,
    코스트코=크롤일 스탬프. 품목별로 가장 최근 수집일의 값·날짜를 쓴다(가격 같아도 더 최신 날짜).
    최근 수집 없으면 그 품목의 과거(가장 최근) 관측 사용." → current_obs(md) = COLS 관측 중 그 품목
    최신 수집일의 관측만. 품목 단위라 부분 OCR(8종)이 종합 sweep(71종)을 덮는 붕괴(CMPA-241)가
    구조적으로 불가능 → CMPA-177 sweep 게이트와 CMPA-243 부분-sweep 가드를 **둘 다 대체**한다.

검증:
  1) 게이트(월) 폐기   — resolve_config 는 mode='per_item_latest', CURRENT=최신월(참고값)만.
  2) 품목 최신 수집일   — 한 품목의 옛 관측(05-01)과 새 관측(06-01)이 있으면 더 최신(06-01)을 채택.
  3) 과거 fallback     — 최근 수집이 끊긴 품목도 제외하지 않고 **그 품목의 가장 최근 관측**으로 노출.
  4) hist 경계         — 현재(최신일) 관측을 뺀 과거 관측만 과거평균에(이중계상 없음).
  5) 단일점 폴백        — 과거 관측이 없는 품목은 단일점(flat ⚪, score 0)으로 노출.
  6) 비게이트 마트      — 롯데마트·이마트는 현재가 소스 아님(과거평균엔 사용); 둘만 있는 항목은 제외.
  7) OCR 소스 적재      — `*_youtube_ocr.csv`(트레이더스 영상 OCR)도 관측 소스로 읽고, 그 영상일이
                          월 CSV sweep 보다 최신이면 OCR 날짜·값을 채택(보드 CMPA-424 핵심).
  8) 붕괴 불가(CMPA-241) — 8종 부분 OCR(06-08)이 와도 71종 종합 sweep(06-01)을 덮지 않는다 —
                          둘 다 각자의 최신 수집일로 노출(종수 미붕괴).
  9) 보조파일 폴백      — 현재월 dailyshot/hk 가 없으면 최신 보조파일 폴백(불변).
 10) 해외표 dommin      — current_obs(품목 최신일)에서 국내 최저가 산출; COLS 관측 없는 항목만 제외.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import whisky_report_tables as W

HEADER = "술이름,가격_KRW,위치,가져온날짜,출처,신뢰도,비고\n"


def _write(d, month, rows, suffix=""):
    """rows = [(술이름, 가격, 위치, 가져온날짜)] → {month}{suffix}.csv 작성(수집일을 행별로 명시).
    suffix='_youtube_ocr' 면 트레이더스 프레임-OCR 관측 파일을 만든다(CMPA-429)."""
    path = os.path.join(d, f"{month}{suffix}.csv")
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write(HEADER)
        for name, price, loc, date in rows:
            f.write(f"{name},{price},{loc},{date},fixture,중,\n")


def _write_month(d, month, n_rows, price=50000, loc="트레이더스 구월점", start=0):
    _write(d, month, [(f"위스키{i}", price + i, loc, f"{month}-01") for i in range(start, start + n_rows)])


def _write_suffixed(d, name):
    with open(os.path.join(d, name), "w", encoding="utf-8-sig") as f:
        f.write("위스키명,가격_KRW,정확도\n샘플,50000,정확\n")


def case(title, fn):
    try:
        fn()
        print(f"  [OK ] {title}")
        return True
    except AssertionError as e:
        print(f"  [FAIL] {title}: {e}")
        return False


def _reset(d):
    """픽스처 폴더 d 로 모듈 전역을 재설정(모듈은 import 시 라이브 DATA 로 전역을 잡으므로).
    OCR 파일은 load() 가 W.DATA 를 직접 glob 하므로(전역 캐시 없음) tmp 폴더만 보면 된다."""
    cur, past, months, dec = W.resolve_config(d, log=False)
    W.DATA, W.CURRENT, W.PAST, W.MONTHS = d, cur, past, months
    W.MONTH_ORDER = [f[:7] for f in months]
    return cur, past, months, dec


def test_gate_abolished():
    """월 게이트 폐기 — 최신월이 직전월 대비 급감해도 보류/이월 없이 CURRENT=최신월,
    mode='per_item_latest', 게이트/이월 키 없음."""
    with tempfile.TemporaryDirectory() as d:
        _write_month(d, "2026-04", 200)
        _write_month(d, "2026-05", 200)
        _write_month(d, "2026-06", 5)            # 종전이라면 월 게이트 미달 → 이월. 이제는 무관.
        cur, past, months, dec = W.resolve_config(d, log=False)
        assert cur == "2026-06", f"CURRENT 는 최신월(참고값)이어야 함: {cur}"
        assert dec.get("mode") == "per_item_latest", dec
        assert "carry_forward" not in dec and "gate" not in dec and "donor" not in dec, \
            f"게이트/이월 키가 남아있으면 안 됨: {dec}"
        assert past == ("2026-04", "2026-05"), f"PAST mismatch: {past}"
        assert not hasattr(W, "_carry_forward"), "_carry_forward 는 폐기되어야 함"


def test_per_item_latest_date():
    """품목 단위 최신 수집일: 위스키A 가 05-01(90k)·06-01(88k) 두 관측이면 더 최신 06-01·88k 채택."""
    with tempfile.TemporaryDirectory() as d:
        _write(d, "2026-05", [("위스키A", 90000, "코스트코", "2026-05-01")])
        _write(d, "2026-06", [("위스키A", 88000, "코스트코", "2026-06-01")])
        _reset(d)
        agg, disp = W.load()
        _t2, recs = W.build_domestic(agg, disp)
        a = next(r for r in recs if r["name"] == "위스키A")
        assert a["cur"] == 88000 and a["curdate"] == "2026-06-01" and a["curseller"] == "코스트코", a
        assert a["curmonth"] == "2026-06", a


def test_stale_item_kept_with_own_date():
    """과거 fallback(CMPA-429 핵심): 최근 수집이 끊긴 품목도 제외하지 않고 그 품목의 가장 최근
    관측(05-01)으로 노출한다. 다른 품목(06-01)이 있어도 stale 품목을 단종 처리하지 않는다."""
    with tempfile.TemporaryDirectory() as d:
        _write(d, "2026-05", [("위스키B", 78000, "코스트코", "2026-05-01")])   # 6월엔 재수집 안 됨
        _write(d, "2026-06", [("위스키A", 88000, "코스트코", "2026-06-01")])
        _reset(d)
        agg, disp = W.load()
        _t2, recs = W.build_domestic(agg, disp)
        by = {r["name"]: r for r in recs}
        assert "위스키A" in by and "위스키B" in by, f"두 품목 모두 노출돼야: {list(by)}"
        assert by["위스키B"]["curdate"] == "2026-05-01", \
            f"stale 품목은 그 품목의 최신일(05-01)로 노출돼야: {by['위스키B']}"
        assert by["위스키A"]["curdate"] == "2026-06-01", by["위스키A"]


def test_hist_excludes_current():
    """과거평균(hist)은 현재(품목 최신일) 관측을 뺀 과거 관측만 — 이중계상 없음.
    A: 5월 100k(과거), 6월 90k(최신) → 현재가 90k, hist=5월 100k → havg=100k, diff=−10k."""
    with tempfile.TemporaryDirectory() as d:
        _write(d, "2026-05", [("위스키A", 100000, "코스트코", "2026-05-01")])
        _write(d, "2026-06", [("위스키A", 90000, "코스트코", "2026-06-01")])
        _reset(d)
        agg, disp = W.load()
        _t2, recs = W.build_domestic(agg, disp)
        a = next(r for r in recs if r["name"] == "위스키A")
        assert a["cur"] == 90000 and a["curdate"] == "2026-06-01", a
        assert a["havg"] == 100000, f"hist 는 옛 관측(5월 100k)만이어야: havg={a['havg']}"
        assert a["diff"] == -10000, f"diff=cur-havg=−10000 이어야: {a['diff']}"


def test_single_point_fallback():
    """과거 관측이 없는 품목(단일 관측)은 제외하지 않고 단일점(flat ⚪)으로 노출."""
    with tempfile.TemporaryDirectory() as d:
        _write(d, "2026-06", [("위스키X", 70000, "코스트코", "2026-06-01"),
                              ("위스키Y", 60000, "코스트코", "2026-06-01")])
        _reset(d)
        agg, disp = W.load()
        _t2, recs = W.build_domestic(agg, disp)
        x = next(r for r in recs if r["name"] == "위스키X")
        assert x["curmonth"] == "2026-06" and x["flat"] and x["score"] == 0, x
        assert x["havg"] == x["cur"] == 70000, x


def test_non_gated_marts_excluded_as_current():
    """롯데마트·이마트는 현재가 소스(COLS)가 아니다: (a) 트레이더스 관측이 있는 품목의 롯데마트
    옛 관측은 hist 로만, (b) 롯데마트에만 있는 품목은 제외(현재가 후보 없음)."""
    with tempfile.TemporaryDirectory() as d:
        _write(d, "2026-04", [("위스키A", 120000, "롯데마트", "2026-04-23"),
                              ("위스키L", 50000, "롯데마트", "2026-04-23")])   # L = 롯데마트 전용
        _write(d, "2026-06", [("위스키A", 100000, "트레이더스", "2026-06-01")])
        _reset(d)
        agg, disp = W.load()
        _t2, recs = W.build_domestic(agg, disp)
        by = {r["name"]: r for r in recs}
        assert "위스키L" not in by, "롯데마트 전용 항목은 현재가 후보 없음 → 제외돼야"
        a = by["위스키A"]
        assert a["cur"] == 100000 and a["curseller"] == "트레이더스", a
        assert a["havg"] == 120000, f"롯데마트 옛 관측은 hist 로만(120k): {a['havg']}"


def test_ocr_source_ingested_and_wins():
    """`*_youtube_ocr.csv`(트레이더스 영상 OCR) 를 관측 소스로 읽고, 영상일(06-08)이 월 CSV
    sweep(06-01)보다 최신이면 OCR 날짜·값을 채택한다(보드 CMPA-424 핵심)."""
    with tempfile.TemporaryDirectory() as d:
        _write(d, "2026-06", [("글렌피딕 15년 700ml", 105000, "트레이더스", "2026-06-01")])
        _write(d, "2026-06", [("글렌피딕 15년 700ml", 99800, "트레이더스", "2026-06-08")],
               suffix="_youtube_ocr")
        _reset(d)
        agg, disp = W.load()
        _t2, recs = W.build_domestic(agg, disp)
        g = next(r for r in recs if "글렌피딕 15년" in r["name"])
        assert g["curdate"] == "2026-06-08" and g["cur"] == 99800, \
            f"OCR 영상일(06-08)·값(99800)이 채택돼야: {g}"
        assert g["havg"] == 105000, f"옛 06-01 sweep 은 hist 로만(105k): {g['havg']}"


def test_partial_ocr_does_not_collapse():
    """CMPA-241 회귀 불가: 8종 부분 OCR(06-08)이 와도 50종 종합 sweep(06-01)을 덮지 않는다 —
    품목 단위라 둘 다 각자의 최신 수집일로 노출(종수 붕괴 없음)."""
    with tempfile.TemporaryDirectory() as d:
        big = [(f"위스키{i}", 50000 + i, "트레이더스", "2026-06-01") for i in range(50)]
        _write(d, "2026-06", big)
        partial = [(f"OCR품목{j}", 80000 + j, "트레이더스", "2026-06-08") for j in range(8)]
        _write(d, "2026-06", partial, suffix="_youtube_ocr")
        _reset(d)
        agg, disp = W.load()
        _t2, recs = W.build_domestic(agg, disp)
        names = {r["name"] for r in recs}
        assert len(recs) >= 58, f"부분 OCR 이 표를 붕괴시키면 안 됨(50+8 유지): rows={len(recs)}"
        assert "위스키0" in names and "위스키49" in names, "06-01 종합 sweep 항목은 유지돼야"
        assert "OCR품목0" in names and "OCR품목7" in names, "06-08 OCR 항목도 노출돼야"
        by = {r["name"]: r for r in recs}
        assert by["위스키0"]["curdate"] == "2026-06-01", by["위스키0"]
        assert by["OCR품목0"]["curdate"] == "2026-06-08", by["OCR품목0"]


def test_suffixed_fallback():
    """현재월 보조파일이 없으면 가장 최신 보조파일로 폴백, 있으면 현재월 사용(불변)."""
    with tempfile.TemporaryDirectory() as d:
        _write_suffixed(d, "2026-05_dailyshot.csv")
        _write_suffixed(d, "2026-06_dailyshot.csv")
        _write_suffixed(d, "2026-05_hk_whisky_poc.csv")  # 06 hk 없음 → 05 폴백
        assert W._pick_suffixed("dailyshot", "2026-06", d) == "2026-06_dailyshot.csv"
        assert W._pick_suffixed("hk_whisky_poc", "2026-06", d) == "2026-05_hk_whisky_poc.csv"


def test_overseas_dommin_uses_current_obs():
    """해외표 국내 최저가도 current_obs(품목 최신일)에서 산출: COLS 관측이 있는 항목(A·B)은
    각자 최신일 가격이 dommin 에, COLS 관측이 전혀 없는 항목(롯데마트 전용 L)만 제외."""
    with tempfile.TemporaryDirectory() as d:
        _write(d, "2026-04", [("위스키L", 40000, "롯데마트", "2026-04-23")])  # COLS 관측 없음
        _write(d, "2026-05", [("위스키B", 78000, "코스트코", "2026-05-01")])
        _write(d, "2026-06", [("위스키A", 90000, "코스트코", "2026-06-01")])
        _reset(d)
        agg, disp = W.load()
        kl = next(k for k in agg if "위스키L" in k)
        assert W.current_obs(agg[kl]) == [], "L 은 COLS 관측이 없으니 국내 최저가 후보 없음"
        kb = next(k for k in agg if "위스키B" in k)
        assert min(p for p, *_ in W.current_obs(agg[kb])) == 78000, "B 는 05-01 관측으로 노출"
        ka = next(k for k in agg if "위스키A" in k)
        assert min(p for p, *_ in W.current_obs(agg[ka])) == 90000, W.current_obs(agg[ka])


def main():
    results = [
        case("월 게이트/이월 폐기 (resolve_config = per_item_latest)", test_gate_abolished),
        case("품목 단위 최신 수집일 채택 (더 최신 날짜)", test_per_item_latest_date),
        case("과거 fallback (최근 수집 없는 품목도 자기 최신일로 노출)", test_stale_item_kept_with_own_date),
        case("hist 경계 (현재 관측 제외 → 이중계상 없음)", test_hist_excludes_current),
        case("단일점 폴백 (과거 없는 항목도 노출, flat ⚪)", test_single_point_fallback),
        case("비게이트 마트(롯데마트·이마트) = 현재가 소스 아님(hist 만)", test_non_gated_marts_excluded_as_current),
        case("OCR 소스 적재 + 영상일이 sweep 보다 최신이면 채택 (CMPA-424)", test_ocr_source_ingested_and_wins),
        case("부분 OCR 이 종합 sweep 을 붕괴시키지 않음 (CMPA-241 회귀 불가)", test_partial_ocr_does_not_collapse),
        case("보조파일(dailyshot/hk) 폴백", test_suffixed_fallback),
        case("해외표 dommin = current_obs(품목 최신일) 산출", test_overseas_dommin_uses_current_obs),
    ]
    n = sum(results)
    print(f"\n결과: {n}/{len(results)} 통과")
    if n != len(results):
        raise SystemExit(1)
    print("CMPA-429 품목 단위 최신 수집일 신선도 단위테스트 모두 통과 ✅")


if __name__ == "__main__":
    main()
