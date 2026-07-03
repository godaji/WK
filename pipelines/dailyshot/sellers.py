#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""데일리샷 셀러 메타 해소·캐시 — CMPA-322.

데일리샷 마켓플레이스의 익명 `seller_id` 를 **상호·업종(service_type)·지역**까지
해소한다. seller_id→메타는 거의 불변이므로 `data/whisky-prices/_dailyshot_sellers.json`
에 캐시하고 **신규 seller 만 API 조회**(추가 부하 최소; CMPA-321 보고서 권고 ②).

소스(런타임 디스커버리, CMPA-321):
  GET https://api.dailyshot.co/sellers/{id}/
    -> {"id", "name", "service_type", "address", "is_active", ...}

업종(service_type) 라벨 — CMPA-321 보고서 §2 분류:
  0=픽업제휴 · 1=주류전문샵 · 2/7=CU편의점 · 5=면세점 · 9/10=이마트24

⚠️ 면세점(service_type=5, 예: 신라면세점 15919)은 마켓플레이스 검색에 KRW 로 섞여
들어와 '국내 최저가' floor 를 오염시켰다(CMPA-322). 크롤러는 floor 계산에서 면세/해외
리스팅을 제외한다(crawl_dailyshot.match_lowest). 본 모듈은 그 floor 와 무관하게
listings 동반 데이터셋의 '셀러 상호·업종·지역' 라벨링을 담당한다.
"""
import json
import os
import time
import urllib.request

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CACHE_PATH = os.path.join(ROOT, "data", "whisky-prices", "_dailyshot_sellers.json")
SELLER_URL = "https://api.dailyshot.co/sellers/{id}/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# CMPA-321 §2 업종 분류. 미지 코드는 f"기타(svc{n})" 로 폴백.
SERVICE_TYPE_LABEL = {
    0: "픽업제휴",
    1: "주류전문샵",
    2: "CU편의점",
    5: "면세점",
    7: "CU편의점",
    9: "이마트24",
    10: "이마트24",
}
DUTYFREE_SVC = 5   # 면세점 — 국내 floor 에서 제외 대상


def service_label(st):
    if st is None:
        return ""
    return SERVICE_TYPE_LABEL.get(st, f"기타(svc{st})")


def region_of(address):
    """주소 앞 2토큰을 지역으로(예: '서울 강남구', '서울시 중구'). 없으면 ''."""
    if not address:
        return ""
    return " ".join(str(address).split()[:2])


def load_cache(path=CACHE_PATH):
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (ValueError, OSError):
        return {}


def save_cache(cache, path=CACHE_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False, indent=2, sort_keys=True)


def _http_json(url, timeout=15):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9", "Referer": "https://dailyshot.co/"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


class SellerResolver:
    """seller_id → {셀러명, service_type, 업종, 지역} 해소(캐시 우선, 신규만 조회)."""

    def __init__(self, cache=None, pace=0.3, fetched_date=None):
        self.cache = cache if cache is not None else load_cache()
        self.pace = pace
        self.fetched_date = fetched_date
        self.fetched = 0      # 이번 실행에서 신규 API 조회한 셀러 수
        self.failed = 0       # 조회 실패(미해소) 수

    def resolve(self, seller_id):
        """메타 dict 반환. 미지/실패면 None. 캐시에 있으면 API 미조회."""
        if seller_id is None or seller_id == "":
            return None
        key = str(seller_id)
        if key in self.cache:
            return self.cache[key]
        # 신규 셀러만 조회(거의 불변이므로 1회면 충분).
        if self.pace:
            time.sleep(self.pace)
        try:
            d = _http_json(SELLER_URL.format(id=key))
        except Exception:
            self.failed += 1
            return None
        st = d.get("service_type")
        meta = {
            "seller_id": d.get("id", seller_id),
            "셀러명": (d.get("name") or "").strip(),
            "service_type": st,
            "업종": service_label(st),
            "지역": region_of(d.get("address")),
            "address": (d.get("address") or "").strip(),
            "해소일": self.fetched_date or "",
        }
        self.cache[key] = meta
        self.fetched += 1
        return meta

    def is_dutyfree(self, seller_id):
        """해소된 셀러의 업종이 면세점(svc5)이면 True (백스톱; 1차 신호는 price_usd)."""
        meta = self.resolve(seller_id)
        return bool(meta) and meta.get("service_type") == DUTYFREE_SVC


if __name__ == "__main__":
    # 스모크: 알려진 셀러 4곳 해소(CMPA-321 보고서 대조).
    r = SellerResolver(cache={}, pace=0.2, fetched_date="self-check")
    for sid in (15919, 16362, 36986, 14600):
        m = r.resolve(sid)
        print(sid, "->", m and (m["셀러명"], m["업종"], m["지역"]))
    assert r.cache["15919"]["service_type"] == 5, "신라면세점=svc5 기대"
    assert service_label(5) == "면세점"
    assert service_label(1) == "주류전문샵"
    assert region_of("서울 강남구 테헤란로 101") == "서울 강남구"
    print("self-check PASS ✓  fetched=%d failed=%d" % (r.fetched, r.failed))
