#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
환율 스냅샷 수집기 (HKD/JPY → KRW). CMPA-30 해외 수집 루틴 공통 컴포넌트.

소스: open.er-api.com (무료, 키 불필요, 일 1회 갱신). USD 기준 rate 테이블을 받아
KRW per 1 통화 = rates["KRW"] / rates[통화] 로 cross-rate 를 산출한다.
  HKD→KRW = KRW/USD ÷ HKD/USD
  JPY→KRW = KRW/USD ÷ JPY/USD
이 값이 HK(crawl_hk_whisky.py) · JP(rakuten_poc.py) 가격 파이프라인의 환산 입력이 된다.

API:
  fetch_usd_rates()                 -> dict (open.er-api.com /v6/latest/USD 응답)
  cross_to_krw(rates, ccy)          -> float (1 ccy 당 KRW)
  fx_snapshot(currencies=[...])     -> dict {asof, source, krw_per: {ccy: rate}, raw_usd: {...}}

CLI:
  python3 fx_fetch.py                # 스냅샷 출력 + data/whisky-prices/fx/ 에 append/write
  python3 fx_fetch.py HKD JPY TWD    # 통화 지정
환경:
  FX_SOURCE_URL  기본 https://open.er-api.com/v6/latest/USD
  FX_ASOF        기본 응답의 time_last_update(UTC) date, 없으면 호출일
"""
from __future__ import annotations

import csv
import json
import os
import sys
import urllib.request

DEFAULT_URL = os.environ.get("FX_SOURCE_URL", "https://open.er-api.com/v6/latest/USD")
DEFAULT_CCYS = ["HKD", "JPY"]
UA = "WK-fx-snapshot/1.0 (internal price-tracker)"


def fetch_usd_rates(url: str = DEFAULT_URL) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8"))
    if data.get("result") != "success":
        raise RuntimeError(f"FX API non-success: {data.get('result')} / {data.get('error-type')}")
    if "rates" not in data or "KRW" not in data["rates"]:
        raise RuntimeError("FX API missing rates/KRW")
    return data


def cross_to_krw(rates: dict, ccy: str) -> float:
    """KRW per 1 unit of `ccy`, derived from a USD-based rate table."""
    if ccy == "KRW":
        return 1.0
    if ccy not in rates:
        raise KeyError(f"currency {ccy} not in FX table")
    return rates["KRW"] / rates[ccy]


def _asof_from(data: dict) -> str:
    # "Fri, 30 May 2026 00:02:31 +0000" -> "2026-05-30"; fallback env or empty.
    utc = data.get("time_last_update_utc", "")
    try:
        parts = utc.split()  # [DOW, DD, Mon, YYYY, HH:MM:SS, +0000]
        months = {"Jan": "01", "Feb": "02", "Mar": "03", "Apr": "04", "May": "05",
                  "Jun": "06", "Jul": "07", "Aug": "08", "Sep": "09", "Oct": "10",
                  "Nov": "11", "Dec": "12"}
        return f"{parts[3]}-{months[parts[2]]}-{int(parts[1]):02d}"
    except Exception:
        return os.environ.get("FX_ASOF", "")


def fx_snapshot(currencies=None, url: str = DEFAULT_URL) -> dict:
    currencies = currencies or DEFAULT_CCYS
    data = fetch_usd_rates(url)
    rates = data["rates"]
    asof = os.environ.get("FX_ASOF") or _asof_from(data)
    return {
        "asof": asof,
        "source": "open.er-api.com (USD base cross-rate)",
        "krw_per": {c: round(cross_to_krw(rates, c), 6) for c in currencies},
        "raw_usd": {c: rates.get(c) for c in currencies + ["KRW"]},
        "fetched_url": url,
    }


HEADER = ["날짜", "통화", "KRW_per_1단위", "USD_per_1단위_역수참고", "소스", "수집URL"]


def write_snapshot(snap: dict, outdir: str) -> tuple[str, str]:
    """Upsert one row per currency into fx_snapshot.csv (history, keyed by 날짜+통화)
    and overwrite fx_latest.json. Re-running the same day replaces that day's rows
    rather than appending duplicates."""
    os.makedirs(outdir, exist_ok=True)
    csv_path = os.path.join(outdir, "fx_snapshot.csv")
    json_path = os.path.join(outdir, "fx_latest.json")

    # load existing history into a (날짜,통화)->row map, preserving insertion order
    rows: "dict[tuple[str, str], list]" = {}
    if os.path.exists(csv_path):
        with open(csv_path, encoding="utf-8-sig", newline="") as f:
            r = csv.reader(f)
            header = next(r, None)
            for row in r:
                if len(row) >= 2:
                    rows[(row[0], row[1])] = row

    for ccy, rate in snap["krw_per"].items():
        usd_rate = snap["raw_usd"].get(ccy)
        rows[(snap["asof"], ccy)] = [snap["asof"], ccy, rate, usd_rate,
                                     snap["source"], snap["fetched_url"]]

    ordered = sorted(rows.values(), key=lambda x: (x[0], x[1]))
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(ordered)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=2)
    return csv_path, json_path


def _latest_json_path() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(here, "..", "..", "data",
                                        "whisky-prices", "fx", "fx_latest.json"))


def _read_latest():
    try:
        with open(_latest_json_path(), encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _today_str(today=None) -> str:
    if today:
        return today
    env = os.environ.get("FX_TODAY")
    if env:
        return env
    import datetime as _dt
    return _dt.date.today().isoformat()


def _age_days(asof: str, today: str):
    import datetime as _dt
    try:
        return (_dt.date.fromisoformat(today) - _dt.date.fromisoformat(asof)).days
    except Exception:
        return None


def ensure_fresh(currencies=None, max_age_days: int = 1, write: bool = True,
                 today=None) -> dict:
    """리포트 빌드 직전 환율을 '최신'으로 보장한다 (CMPA-249/251 보드 요구).

    동작:
      1) 캐시(fx_latest.json) `asof` 가 today-max_age_days 이내면 → 네트워크 없이 캐시 반환(fresh=True).
      2) 아니면(또는 캐시 없음) 라이브 fetch 시도 → 성공 시 fx_latest.json 갱신(write=True).
      3) 라이브 실패 시 → 캐시 폴백 + fresh=False + warning(**silent stale 금지**).
    반환: fx_snapshot 키 + {fresh: bool, warning: str|None}. raw_usd["KRW"] 가능 시 항상 포함.

    호출자가 ["KRW"] 만 줘도 fx_latest.json 이 HKD/JPY 를 잃지 않도록 DEFAULT_CCYS(HKD/JPY)
    를 항상 합쳐 받아 전체를 다시 쓴다(다운스트림 보존)."""
    requested = list(currencies or ["KRW"])
    want = [c for c in dict.fromkeys(DEFAULT_CCYS + requested) if c != "KRW"] or DEFAULT_CCYS
    td = _today_str(today)
    cached = _read_latest()
    cached_asof = (cached or {}).get("asof")

    # 1) 이미 신선 → 네트워크 생략
    if cached and cached_asof:
        age = _age_days(cached_asof, td)
        if age is not None and 0 <= age <= max_age_days:
            out = dict(cached)
            out["fresh"], out["warning"] = True, None
            return out

    # 2) 라이브 fetch 시도
    try:
        snap = fx_snapshot(want)
        if write:
            here = os.path.dirname(os.path.abspath(__file__))
            outdir = os.path.abspath(os.path.join(here, "..", "..", "data",
                                                  "whisky-prices", "fx"))
            write_snapshot(snap, outdir)
        age = _age_days(snap.get("asof", ""), td)
        snap["fresh"] = (age is None) or (age <= max_age_days)
        snap["warning"] = None if snap["fresh"] else (
            f"환율 소스 asof={snap.get('asof')} 가 기준일 {td} 보다 오래됨(API 지연 가능)")
        return snap
    except Exception as e:
        # 3) 폴백: 캐시 + 명시 경고(silent stale 금지)
        if cached:
            out = dict(cached)
            out["fresh"] = False
            out["warning"] = (f"라이브 환율 fetch 실패({type(e).__name__}) → "
                              f"캐시 fx_latest.json(asof {cached_asof}) 사용(stale 가능)")
            return out
        return {"asof": "", "source": "unavailable", "krw_per": {},
                "raw_usd": {"KRW": None}, "fresh": False,
                "warning": f"환율 라이브 실패 + 캐시 없음({type(e).__name__})"}


def main():
    ccys = [a.upper() for a in sys.argv[1:]] or DEFAULT_CCYS
    here = os.path.dirname(os.path.abspath(__file__))
    outdir = os.path.abspath(os.path.join(here, "..", "..", "data", "whisky-prices", "fx"))
    snap = fx_snapshot(ccys)
    csv_path, json_path = write_snapshot(snap, outdir)
    print(json.dumps(snap, ensure_ascii=False, indent=2))
    print(f"\nAPPENDED -> {csv_path}", file=sys.stderr)
    print(f"WROTE    -> {json_path}", file=sys.stderr)


if __name__ == "__main__":
    main()
