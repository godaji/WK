#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CMPA-672 회귀 테스트 — build_compare 의 스냅샷 날짜 동적 탐색 + staleness 가드.

배경: build_compare.py 가 면세 스냅샷 경로/날짜를 하드코딩해 일간 루틴에서 매일 stale
되던 결함을 고쳤다. 이 테스트는 다음을 고정한다:
  1) _latest_snapshot 이 glob 결과에서 **파일명 날짜 최신본**을 고른다(접두/접미 무관).
  2) required=False 면 없을 때 ("", "") (비치명 — 데일리샷 보강 캐시).
  3) _date_from_path 가 신라(접미)·마트(접두) 두 명명 규칙 모두에서 날짜를 뽑는다.
  4) _staleness_warn 이 max_age_days 경계에서 정확히 동작(주입 today 로 결정론).
  5) 모듈 전역(LOTTE_CSV/SHILLA_CSV/SSG_CSV)이 실제 존재하는 파일로 해소된다.

실행: python3 scripts/test_build_compare_dates.py   (네트워크 불필요)
"""
import datetime
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "pipelines", "dutyfree_compare"))
import build_compare as bc  # noqa: E402


def test_latest_snapshot_picks_max_date():
    with tempfile.TemporaryDirectory() as d:
        for name in ("2026-06-20_lotte_whisky.csv", "2026-06-28_lotte_whisky.csv",
                     "2026-06-25_lotte_whisky.csv", "README.txt"):
            open(os.path.join(d, name), "w").close()
        path, date = bc._latest_snapshot(os.path.join(d, "????-??-??_lotte_whisky.csv"))
        assert date == "2026-06-28", date
        assert path.endswith("2026-06-28_lotte_whisky.csv"), path
    # 신라 접미 명명도 최신본을 고른다
    with tempfile.TemporaryDirectory() as d:
        for name in ("신라면세_위스키_2026-06-27.csv", "신라면세_위스키_2026-06-28.csv",
                     "신라면세_위스키_2026-06-09.csv"):
            open(os.path.join(d, name), "w").close()
        path, date = bc._latest_snapshot(os.path.join(d, "신라면세_위스키_????-??-??.csv"))
        assert date == "2026-06-28", date
    print("  ✓ _latest_snapshot 최신 날짜 선택(접두/접미 무관)")


def test_latest_snapshot_missing():
    with tempfile.TemporaryDirectory() as d:
        # required=False → 없으면 비치명적으로 ("", "")
        path, date = bc._latest_snapshot(os.path.join(d, "_dailyshot_compare_????-??-??.csv"),
                                         required=False)
        assert (path, date) == ("", ""), (path, date)
        # required=True(기본) → FileNotFoundError
        try:
            bc._latest_snapshot(os.path.join(d, "????-??-??_lotte_whisky.csv"))
            raise AssertionError("필수 스냅샷 없을 때 예외가 나야 함")
        except FileNotFoundError:
            pass
    print("  ✓ _latest_snapshot required 분기(없음 비치명 vs 예외)")


def test_date_from_path():
    assert bc._date_from_path("신라면세_위스키_2026-06-28.csv") == "2026-06-28"
    assert bc._date_from_path("2026-06-28_lotte_whisky.csv") == "2026-06-28"
    assert bc._date_from_path("/a/b/_dailyshot_compare_2026-06-28.csv") == "2026-06-28"
    assert bc._date_from_path("no_date_here.csv") == ""
    print("  ✓ _date_from_path 신라(접미)·마트(접두) 모두 추출")


def test_staleness_warn_boundary():
    today = datetime.date(2026, 6, 28)
    assert bc._staleness_warn("2026-06-28", "x", today=today) is False   # 0일
    assert bc._staleness_warn("2026-06-26", "x", today=today) is False   # 2일
    assert bc._staleness_warn("2026-06-25", "x", today=today) is True    # 3일=경계
    assert bc._staleness_warn("2026-06-10", "x", today=today) is True    # 18일
    assert bc._staleness_warn("", "x", today=today) is False             # 빈값 안전
    assert bc._staleness_warn("bad-date", "x", today=today) is False     # 불량 안전
    print("  ✓ _staleness_warn 경계(>=3일 경고) + 빈/불량 입력 안전")


def test_module_globals_resolve_to_real_files():
    """리포 정본 스냅샷 디렉터리에서 실제 파일로 해소돼야 한다(import 시 깨지지 않음)."""
    for path, date, label in (
        (bc.LOTTE_CSV, bc.LOTTE_DATE, "롯데"),
        (bc.SHILLA_CSV, bc.SHILLA_DATE, "신라"),
        (bc.SSG_CSV, bc.SSG_DATE, "신세계"),
    ):
        assert os.path.exists(path), f"{label} 스냅샷 경로 없음: {path}"
        # 날짜 토큰이 파일명과 일치
        assert date == bc._date_from_path(path), f"{label} 날짜 불일치: {date} vs {path}"
        datetime.date.fromisoformat(date)  # 유효한 ISO 날짜
    print(f"  ✓ 모듈 전역 실파일 해소(신라 {bc.SHILLA_DATE}·롯데 {bc.LOTTE_DATE}·"
          f"신세계 {bc.SSG_DATE}·데일리샷 {bc.ONLINE_DATE or '없음'})")


if __name__ == "__main__":
    test_latest_snapshot_picks_max_date()
    test_latest_snapshot_missing()
    test_date_from_path()
    test_staleness_warn_boundary()
    test_module_globals_resolve_to_real_files()
    print("ALL PASS ✓  (CMPA-672 build_compare 동적 스냅샷 날짜 + staleness 가드)")
