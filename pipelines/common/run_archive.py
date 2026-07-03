#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_archive.py — 통합 실행의 '런 단위(run-centric)' 산출물 아카이브 — CMPA-151.

배경 (두 가지 누적 뷰)
----------------------
이 리포의 데이터는 "한 시점 스냅샷"이 아니라 "수집 날짜가 찍힌 누적 기록"이다(CMPA-156).
그래서 두 가지 보존 뷰를 함께 유지한다:

  1) **정본(latest) + 자산-로컬 스냅샷** — `pipelines/common/dated.py`.
     각 자산은 정본 파일명을 그대로 유지(=항상 최신=latest 포인터)하고,
     쓴 직후 같은 폴더의 `_runs/<stem>__run<date>.<ext>` 에 날짜 사본을 남긴다.
     (자산별로 흩어진 '세로' 뷰 — "이 파일의 시간축")

  2) **런 단위 폴더** — 이 모듈. `runs/<run_date>/<asset>/` 아래에
     **한 번의 통합 실행이 만든 모든 자산 산출물을 한곳에 모은다.**
     (한 실행의 '가로' 뷰 — "이 런이 뭘 만들었나"). deploy 는 cross-asset 이라
     `runs/<run_date>/deploy/`. 날짜는 `run_dates.run_date()` 단일 출처.

정본은 그대로 두고 **추가로** 사본을 모으는 것이라(복사, 이동 아님) 다운스트림 latest
포인터는 영향받지 않는다. 같은 run_date 재실행은 그 날 폴더를 갱신(날짜 단위 멱등).
symlink 미사용(/mnt/c drvfs 비호환) — 단순 복사.

용법
  python3 pipelines/common/run_archive.py            # 오늘(run_date) 폴더로 현재 정본 수집
  python3 pipelines/common/run_archive.py 2026-06-07 # 특정 run_date 로
  from pipelines.common.run_archive import collect_run_outputs
  collect_run_outputs(run_date)                       # 통합 실행 끝에서 호출
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[2]  # .../WK

# 자산 → 정본 산출물 스펙(ROOT 기준 상대경로). 스펙 규칙:
#   - '{run_date}' 는 이번 런 날짜로 치환된다.
#   - '*' 가 있으면 glob 후 임베드 날짜가 가장 최신인 1개만 고른다(월 무관).
#   - 그 외는 정확한 경로.
# costco/marts 는 같은 월간 정본 `{month}.csv` 를 공유(코스트코가 append) → 'marts' 하나로.
ASSET_OUTPUTS: dict[str, list[str]] = {
    "marts": [
        "data/whisky-prices/*.csv",  # 최신 월 마트 정본(국내 마트 + 코스트코 append)
    ],
    "dailyshot": [
        "data/whisky-prices/*_dailyshot.csv",
    ],
    "overseas": [
        "data/whisky-prices/*_hk_whisky_poc.csv",
        "data/whisky-prices/*_jp_shopify_poc.csv",
        "data/whisky-prices/fx/fx_snapshot.csv",
        "data/whisky-prices/fx/fx_latest.json",
    ],
    "normalized": [
        "data/whisky-prices/normalized/normalized_prices.csv",
        "data/whisky-prices/normalized/normalized_all_rows.csv",
        "assets/master-sku.csv",
        "assets/whisky-aliases.csv",
    ],
    "reports": [
        "reports/whisky-price/*_위스키가격리포트_{run_date}.md",  # 이번 런이 만든 리포트(날짜로 특정)
        "reports/whisky-price/CMPA-31_정규화검증리포트.md",
    ],
}

# 신라면세 자산(별도 통합 실행 `scripts/run_shilla_pipeline.py` 용) — CMPA-293.
# 신라 산출물은 파일명에 요청 <run_date> 를 박는다(수집·필터·분석·리포트 전부 SHILLA_DATE 공유).
# 그래서 "이번 런이 만든 모든 dated 파일" 을 그대로 모으면 된다 → glob_all=True 로 매칭 전부 복사
# (위스키가격의 '여러 월 중 최신 1개' 의미와 다름). deploy 는 cross-asset 이라 build_deploy 가
# 별도로 `runs/<run_date>/deploy/` 에 채운다(여기선 data/·reports/ 자산만).
SHILLA_ASSET_OUTPUTS: dict[str, list[str]] = {
    "shilla_data":   ["data/shilla-dutyfree/*{run_date}*"],     # 수집 raw + 분석 CSV/JSON 전부
    "shilla_report": ["reports/shilla-dutyfree/*{run_date}*"],  # 피트/가성비/예산 md + 발행 html
}

_DATE_RX = __import__("re").compile(r"(\d{4}-\d{2}(?:-\d{2})?)")


def _embedded_date(path: str) -> str:
    """파일명 안의 가장 마지막 YYYY-MM[-DD] 토큰(정렬 키). 없으면 ''."""
    found = _DATE_RX.findall(os.path.basename(path))
    return found[-1] if found else ""


def _resolve(spec: str, run_date: str, root: Path, glob_all: bool = False) -> list[str]:
    """스펙 1개 → 실제 존재하는 절대경로 목록.

    glob 일 때: 기본은 최신 1개(여러 월 정본 중 최신만), glob_all=True 면 매칭 파일 전부
    (신라처럼 한 런이 같은 날짜로 다수 산출물을 만드는 경우). 디렉터리는 제외.
    """
    rel = spec.format(run_date=run_date)
    if "*" in rel:
        cands = [p for p in glob.glob(str(root / rel)) if os.path.isfile(p)]
        if not cands:
            return []
        if glob_all:
            return sorted(cands)
        # 임베드 날짜 → mtime 순 최신 1개(같은 자산의 여러 월 중 최신만 아카이브)
        best = max(cands, key=lambda p: (_embedded_date(p), os.path.getmtime(p)))
        return [best]
    p = root / rel
    return [str(p)] if p.exists() else []


def collect_run_outputs(run_date: str, root: Path | str = ROOT,
                        assets: dict[str, list[str]] | None = None,
                        glob_all: bool = False,
                        manifest_name: str = "_manifest.json") -> dict:
    """현재 정본 산출물을 `runs/<run_date>/<asset>/` 로 복사(추가, 정본 불변).

    glob_all=True 면 glob 스펙이 매칭한 파일을 전부 복사(신라면세 통합 실행 — CMPA-293).
    manifest_name: 같은 run_date 폴더를 위스키가격·신라 두 통합 실행이 공유할 수 있으므로
      각자 다른 매니페스트 파일명을 써서 서로 덮어쓰지 않게 한다(신라=_manifest_shilla.json).
    반환: {"run_date","run_dir","assets":{asset:[복사된 상대경로...]},"copied":N,"missing":[...]}.
    """
    root = Path(root)
    assets = assets or ASSET_OUTPUTS
    run_dir = root / "runs" / run_date
    out = {"run_date": run_date, "run_dir": str(run_dir.relative_to(root)),
           "assets": {}, "copied": 0, "missing": []}
    for asset, specs in assets.items():
        copied: list[str] = []
        for spec in specs:
            srcs = _resolve(spec, run_date, root, glob_all=glob_all)
            if not srcs:
                out["missing"].append(spec.format(run_date=run_date))
                continue
            for src in srcs:
                dst_dir = run_dir / asset
                dst_dir.mkdir(parents=True, exist_ok=True)
                dst = dst_dir / os.path.basename(src)
                shutil.copy2(src, dst)
                copied.append(str(dst.relative_to(root)))
                out["copied"] += 1
        out["assets"][asset] = copied
    # 런 매니페스트(이 런이 무엇을 모았는지 한눈에)
    run_dir.mkdir(parents=True, exist_ok=True)
    with open(run_dir / manifest_name, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    return out


def main(argv: list[str]) -> int:
    run_date = argv[1] if len(argv) > 1 else None
    if not run_date:
        from pipelines.common import run_dates  # 단일 날짜 출처
        run_date = run_dates.run_date()
    res = collect_run_outputs(run_date)
    print(f"[run-archive] {res['run_dir']}/  — {res['copied']} files, "
          f"{len(res['assets'])} assets")
    for asset, files in res["assets"].items():
        print(f"  {asset:12s} {len(files)} file(s)")
        for rel in files:
            print(f"      + {rel}")
    if res["missing"]:
        print(f"  [skip] 없음(이번 런 미생성/해당없음): {', '.join(res['missing'])}")
    return 0


if __name__ == "__main__":
    # 직접 실행 시 ROOT 를 sys.path 에 넣어 'pipelines.common' 임포트 가능하게.
    sys.path.insert(0, str(ROOT))
    raise SystemExit(main(sys.argv))
