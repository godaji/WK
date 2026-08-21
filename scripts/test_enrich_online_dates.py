#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CMPA-1345 회귀 테스트 — 데일리샷 온라인 보강 스냅샷의 날짜별 파일 + seed-forward.

배경: 보강 스크립트(enrich_online_dailyshot.py)가 캐시 파일명을 2026-06-28 로 하드코딩해
매 실행이 같은 파일만 덮어써서, build_compare 의 최신 스냅샷 탐색이 영원히 06-28 로 STALE
판정났다(CMPA-1345). 고친 뒤 이 테스트가 다음을 고정한다:
  1) cache_path(date) 가 날짜별 파일 경로를 만든다(파일명 날짜가 매일 전진).
  2) latest_prior_cache 가 대상일 이전 스냅샷 중 최신본을 seed 로 고른다(없으면 None).
  3) _is_stale 이 looked_up_at 기준 경계에서 정확(불량/누락 날짜는 갱신 대상).
  4) load_cache/_write_cache 왕복이 looked_up_at(항목별 수집일)을 보존한다(CMPA-156).

실행: python3 scripts/test_enrich_online_dates.py   (네트워크 불필요)
"""
import datetime
import os
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "pipelines", "dutyfree_compare"))
sys.path.insert(0, os.path.join(ROOT, "pipelines", "shilla_dutyfree"))
import enrich_online_dailyshot as eo  # noqa: E402


def test_cache_path_is_dated():
    p = eo.cache_path("2026-08-21")
    assert p.endswith("_dailyshot_compare_2026-08-21.csv"), p
    assert eo.cache_path("2026-06-28") != eo.cache_path("2026-08-21")
    print("  ✓ cache_path 날짜별 파일(파일명 날짜 전진)")


def test_latest_prior_cache(monkeypatch_dir=None):
    with tempfile.TemporaryDirectory() as d:
        for name in ("_dailyshot_compare_2026-06-28.csv",
                     "_dailyshot_compare_2026-07-15.csv",
                     "_dailyshot_compare_2026-08-01.csv",
                     "README.txt"):
            open(os.path.join(d, name), "w").close()
        old_dir, old_glob = eo.CACHE_DIR, eo.CACHE_GLOB
        eo.CACHE_DIR = d
        eo.CACHE_GLOB = os.path.join(d, "_dailyshot_compare_????-??-??.csv")
        try:
            # 대상일 2026-08-21 이전 최신 = 08-01
            prior = eo.latest_prior_cache("2026-08-21")
            assert prior and prior.endswith("2026-08-01.csv"), prior
            # 대상일과 같은/이후 파일은 seed 대상 아님(07-15 대상이면 06-28 이 최신 이전본)
            prior2 = eo.latest_prior_cache("2026-07-15")
            assert prior2 and prior2.endswith("2026-06-28.csv"), prior2
            # 이전본이 하나도 없으면 None
            assert eo.latest_prior_cache("2026-06-01") is None
        finally:
            eo.CACHE_DIR, eo.CACHE_GLOB = old_dir, old_glob
    print("  ✓ latest_prior_cache 이전 최신본 선택(없으면 None)")


def test_is_stale_boundary():
    today = "2026-08-21"
    assert eo._is_stale({"looked_up_at": "2026-08-21"}, today, 30) is False   # 0일
    assert eo._is_stale({"looked_up_at": "2026-07-23"}, today, 30) is False   # 29일
    assert eo._is_stale({"looked_up_at": "2026-07-22"}, today, 30) is True    # 30일=경계
    assert eo._is_stale({"looked_up_at": "2026-06-28"}, today, 30) is True    # 54일
    assert eo._is_stale({"looked_up_at": "2026-06-28"}, today, 0) is False    # days=0 → 끔
    assert eo._is_stale({"looked_up_at": ""}, today, 30) is True              # 누락 → 갱신
    assert eo._is_stale({"looked_up_at": "bad"}, today, 30) is True           # 불량 → 갱신
    print("  ✓ _is_stale 경계(>=N일 갱신) + 누락/불량 안전")


def test_write_load_roundtrip_preserves_looked_up_at():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "_dailyshot_compare_2026-08-21.csv")
        cache = {
            "발베니12년700ml": {"제품명": "발베니 12년 700ml", "_k1": "발베니12년700ml",
                                "ds_price_krw": 108000, "ds_seller": "리쿼하우스",
                                "ds_vol_ml": "", "ds_item_id": "123", "ds_name": "발베니 12년",
                                "looked_up_at": "2026-06-28"},  # 항목별 수집일 보존돼야 함
        }
        eo._write_cache(path, cache)
        back = eo.load_cache(path)
        assert back["발베니12년700ml"]["looked_up_at"] == "2026-06-28"
        assert back["발베니12년700ml"]["ds_seller"] == "리쿼하우스"
        # 여분 키가 섞여도 FIELDS 만 기록(extrasaction=ignore)
        cache["발베니12년700ml"]["_extra"] = "x"
        eo._write_cache(path, cache)
        with open(path, encoding="utf-8-sig") as f:
            header = f.readline().strip().split(",")
        assert "_extra" not in header, header
    print("  ✓ _write_cache/load_cache 왕복이 looked_up_at 보존(CMPA-156)")


if __name__ == "__main__":
    test_cache_path_is_dated()
    test_latest_prior_cache()
    test_is_stale_boundary()
    test_write_load_roundtrip_preserves_looked_up_at()
    print("ALL PASS ✓  (CMPA-1345 데일리샷 온라인 보강 날짜별 스냅샷 + seed-forward)")
