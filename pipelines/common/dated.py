#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
dated.py — 실행 날짜(run date) 스탬프 공통 유틸 (CMPA-38).

배경
----
파이프라인/루틴들이 본래 **월간(monthly)** 작업을 전제로 `YYYY-MM[...].csv` 처럼
파일명을 지었다. 그러나 실제 수집·정규화·리포트는 **주간(1주)~격주(2주)** 로 돈다.
같은 달 안에서 여러 번 돌리면 덮어쓰여(overwrite) 어느 시점 데이터인지 추적이 끊긴다.

설계 (latest 포인터 + 날짜 스냅샷)
----------------------------------
각 저장 지점은 **정본(canonical) 파일명을 그대로 유지**한다(= 항상 최신 = latest 포인터).
그래서 normalize→report→distribute 다운스트림은 **수정 없이** 늘 최신 입력을 집어간다.
정본 파일을 쓴 직후 `snapshot()` 으로 같은 디렉터리의 `_runs/` 아래에 **실행일(KST)** 이
박힌 사본을 남긴다 → 주간/격주 재실행이 충돌 없이 누적되고 감사 추적이 가능하다.

파일명 규칙 (이상적: 데이터 '월' 과 '실행일' 둘 다 노출)
  정본:   data/whisky-prices/2026-05_dailyshot.csv          (월, 항상 최신)
  스냅샷: data/whisky-prices/_runs/2026-05_dailyshot__run2026-06-03.csv
          └ 5월 가격을 6월 1주차에 수집 → 파일명에 둘 다 드러남.

심볼릭링크는 쓰지 않는다(이 저장소는 /mnt/c drvfs — symlink 비호환). 단순 복사본.

API
  kst_today()                      -> "YYYY-MM-DD" (KST, UTC+9)
  snapshot(path, run_date=None)    -> 날짜 사본 경로(또는 None). 정본을 쓴 직후 호출.
  latest_snapshot(path)            -> path 의 가장 최근 날짜 사본(검증/툴링용) 또는 None.
  list_snapshots(path)             -> [(run_date, 사본경로)] 오름차순.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
from datetime import datetime, timezone, timedelta

KST = timezone(timedelta(hours=9))
RUN_TAG = "__run"
_RUN_RX = re.compile(r"__run(\d{4}-\d{2}-\d{2})(?=\.[^.]+$)")


def kst_today() -> str:
    """오늘 날짜(한국시간, UTC+9) YYYY-MM-DD."""
    return datetime.now(KST).strftime("%Y-%m-%d")


def runs_dir_for(path: str) -> str:
    """정본 파일 경로 → 그 옆 `_runs/` 디렉터리 경로."""
    return os.path.join(os.path.dirname(os.path.abspath(path)), "_runs")


def snapshot_path(path: str, run_date: str | None = None) -> str:
    """정본 경로 + 실행일 → 스냅샷 경로(`_runs/<stem>__run<date><ext>`)."""
    run_date = run_date or kst_today()
    stem, ext = os.path.splitext(os.path.basename(path))
    return os.path.join(runs_dir_for(path), f"{stem}{RUN_TAG}{run_date}{ext}")


def snapshot(path: str, run_date: str | None = None) -> str | None:
    """정본 파일을 막 쓴 직후 호출 → 실행일이 박힌 사본을 `_runs/` 에 남긴다.

    같은 날 재실행이면 그 날 사본을 덮어쓴다(날짜 단위 멱등). 정본이 없으면 None.
    run_date 미지정 시 KST 오늘. (수집 스크립트는 데이터 수집일 인자를 그대로 넘겨도 됨.)
    """
    if not path or not os.path.exists(path):
        return None
    dst = snapshot_path(path, run_date)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copy2(path, dst)
    return dst


def list_snapshots(path: str):
    """path 정본의 모든 날짜 사본을 [(run_date, 사본경로)] 오름차순으로."""
    stem, ext = os.path.splitext(os.path.basename(path))
    pat = os.path.join(runs_dir_for(path), f"{stem}{RUN_TAG}*{ext}")
    out = []
    for p in glob.glob(pat):
        m = _RUN_RX.search(os.path.basename(p))
        if m:
            out.append((m.group(1), p))
    return sorted(out)


def latest_snapshot(path: str) -> str | None:
    """가장 최근 실행일 사본 경로(없으면 None). 정본이 곧 latest 이므로 보통은
    정본을 그대로 쓰면 되고, 이 함수는 검증/감사 도구용."""
    snaps = list_snapshots(path)
    return snaps[-1][1] if snaps else None


if __name__ == "__main__":  # 간단 자가검증
    import tempfile
    d = tempfile.mkdtemp()
    f = os.path.join(d, "2026-05_demo.csv")
    open(f, "w").write("a,b\n1,2\n")
    s1 = snapshot(f, "2026-06-03")
    s2 = snapshot(f, "2026-06-10")
    assert os.path.basename(s1) == "2026-05_demo__run2026-06-03.csv", s1
    assert os.path.basename(s2) == "2026-05_demo__run2026-06-10.csv", s2
    assert latest_snapshot(f) == s2
    assert [d for d, _ in list_snapshots(f)] == ["2026-06-03", "2026-06-10"]
    print("dated.py self-check OK ·", kst_today())
    print(" snapshots:", [os.path.basename(p) for _, p in list_snapshots(f)])
