#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_dates.py — 루틴 실행일(run date) 공통 유틸 — CMPA-38 / CMPA-151.

문제: 루틴은 주간/격주로 도는데 산출물 파일명이 '월'(YYYY-MM)만 담고 있어,
같은 달 안에서 다시 돌면 이전 산출물을 덮어써 추적이 불가능했다.

원칙(중요): **수집 대상 데이터의 '월'(data month)** 과 **'실행일'(run date)** 은
서로 다른 개념이다. 예) 5월 가격을 6월 1주차에 수집 — data month=2026-05, run date=2026-06-03.
파일명 추적에 쓰는 건 항상 '실행일'이며, 이 모듈이 그 단일 출처(single source of truth)다.

CMPA-151: 통합 실행은 이 모듈의 `run_date()` 하나만을 날짜 출처로 삼아
`runs/<run_date>/<asset>/` 날짜 폴더를 만든다(여러 스테이지가 같은 run_date 를 공유).

제공 함수
  run_date()                 실행일(YYYY-MM-DD). COLLECT_DATE>RUN_DATE>FX_ASOF>오늘(로컬).
  dated_name(stem, date)     '2026-06-03_hk_whisky_poc.csv' (날짜 프리픽스 = 정렬가능)
  latest_file(dir, stem)     dir 안의 '*_{stem}.csv' 중 파일명 임베드 날짜가 가장 최신인 경로
                             (신규 YYYY-MM-DD_ 와 레거시 YYYY-MM_ 모두 매칭. 없으면 None)

다운스트림(normalize→report→distribute)은 고정 월 파일명을 하드코딩하는 대신
latest_file() 로 '최신 입력'을 자동 선택해 주간/격주 누적과 호환된다.
"""
from __future__ import annotations

import datetime
import glob
import os
import re

_FULL_RX = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_PREFIX_RX = re.compile(r"^(\d{4}-\d{2}(?:-\d{2})?)_")


def run_date(default_today: bool = True) -> str:
    """루틴 '실행일'(YYYY-MM-DD). 데이터의 '월'과 혼동 금지.

    우선순위: 명시 환경변수(COLLECT_DATE > RUN_DATE > FX_ASOF) > 오늘(로컬).
    default_today=False 면 환경변수가 없을 때 빈 문자열을 돌려준다.
    """
    for key in ("COLLECT_DATE", "RUN_DATE", "FX_ASOF"):
        val = (os.environ.get(key) or "").strip()
        if _FULL_RX.match(val):
            return val
    if default_today:
        return datetime.date.today().isoformat()
    return ""


def dated_name(stem: str, date: str, ext: str) -> str:
    """'{YYYY-MM-DD}_{stem}.{ext}' — 날짜 프리픽스는 사전식 정렬=시간순 정렬."""
    return f"{date}_{stem}.{ext}"


def _embedded_date(path: str) -> str:
    """파일명 앞 날짜 프리픽스 추출. 없으면 ''(빈문자열은 mtime 으로 밀린다)."""
    m = _PREFIX_RX.match(os.path.basename(path))
    if m:
        return m.group(1)
    return ""


def latest_file(dirpath: str, stem: str, ext: str) -> str | None:
    """dir 안 '*_{stem}.{ext}' 중 가장 최신 파일 경로.

    1차 키: 파일명 임베드 날짜(YYYY-MM-DD 가 YYYY-MM 보다 사전식으로 큼 → 신규 우선),
    2차 키: mtime. 후보가 없으면 None.
    """
    cands = glob.glob(os.path.join(dirpath, f"*_{stem}.{ext}"))
    if not cands:
        return None
    return max(cands, key=lambda p: (_embedded_date(p), os.path.getmtime(p)))


if __name__ == "__main__":  # 간단 자가검증
    print("run_date():", run_date())
    print("dated_name:", dated_name("hk_whisky_poc", run_date(), "csv"))
