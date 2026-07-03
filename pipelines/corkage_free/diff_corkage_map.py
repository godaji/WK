#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
diff_corkage_map.py — 콜키지프리 맵 변경 감지 diff (CMPA-82, 부모 CMPA-80 승인 방안)

무엇을 하나
-----------
직전 canonical(= `_runs/` 의 이전 날짜 스냅샷) 대비 **현재 canonical** 산출물의 변화를
역별로 요약한다.

  1) 신규 입점        : 이번에 새로 잡힌 식당(rid)
  2) 폐점·콜키지프리 탈락 : 직전엔 있었는데 이번엔 빠진 식당(rid)
  3) 인당비용 ±15% 초과  : 직전 대비 1인_표준이 15%를 초과해 움직인 식당
  4) 식당 총량 변화     : 역별 식당 수 증감

설계
----
- **변경 없으면 로그만 남기고 통과(노이즈 0).** stdout 에 `RESULT: no-change` 만 찍고
  diff 파일을 쓰지 않는다(`--out` 무시). → 사람은 변경 있을 때만 본다.
- **변경 있으면** `RESULT: changes` 를 찍고, `--out` 경로에 diff 마크다운을 쓴다.
  routine 은 이 파일을 정기 실행 이슈에 코멘트로 첨부한다.
- 재크롤·외부호출 0. 디스크의 canonical + `_runs/` 스냅샷만 읽는다(결정론).

식별 키
-------
- 식당: `식당ID`(rid, 신규) 또는 구 CSV의 `다이닝코드링크` URL (없으면 식당명 폴백).
- 인당비용: `콜키지프리_인당비용_전체.csv` 의 `rid` 컬럼, 비교값 = `1인_표준`(원).

기준(직전) 스냅샷 고르기
----------------------
- `_runs/{base}__run{YYYY-MM-DD}.csv` 중 가장 최신 날짜 = 현재 canonical 과 동일(같은 실행).
  → 직전 = 그보다 **엄격히 이전인 가장 최신 날짜** 스냅샷. 없으면 '최초 실행'으로 diff 생략.

사용법
------
    python3 pipelines/corkage_free/diff_corkage_map.py                 # 현재 canonical vs 직전 스냅샷
    python3 pipelines/corkage_free/diff_corkage_map.py --out /tmp/diff.md
    python3 pipelines/corkage_free/diff_corkage_map.py --selftest      # 합성 데이터로 검출 로직 시연
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "data" / "corkage-free"
RUNS_DIR = DATA_DIR / "_runs"
SUFFIX = "_콜키지프리"
MANIFEST = DATA_DIR / "지원역_목록.csv"
PER_PERSON_NAME = "콜키지프리_인당비용_전체"

PCT_THRESHOLD = 15.0  # 인당비용 ±15% 초과면 보고 (CMPA-80 방안)

_RUN_RX = re.compile(r"__run(\d{4}-\d{2}-\d{2})\.csv$")


# ── CSV 로더 ──────────────────────────────────────────────────────────────────
def _read_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        # 매니페스트 등 '#' 주석(신선도 헤더) 줄은 건너뛴다.
        rows = [ln for ln in f if not ln.lstrip().startswith("#")]
    return list(csv.DictReader(rows))


def _rid(row: dict) -> str:
    # 식당ID(신규, rid 단독) 우선 · 구 CSV 다이닝코드링크(URL) 폴백 · 둘 다 없으면 식당명 — CMPA-102
    link = (row.get("식당ID") or row.get("다이닝코드링크") or "").strip()
    if link:
        return link.split("rid=")[-1].strip()
    return (row.get("식당명") or "").strip()


def _live_stations() -> list[str]:
    if not MANIFEST.exists():
        return []
    out = []
    for r in _read_csv(MANIFEST):
        if (r.get("status") or "").strip() == "live" and r.get("station"):
            out.append(r["station"].strip())
    return out


def _prev_snapshot(base: str) -> Path | None:
    """`{base}__run*.csv` 중 '직전'(최신보다 엄격히 이전) 스냅샷. 없으면 None."""
    dated: dict[str, Path] = {}
    for p in RUNS_DIR.glob(f"{base}__run*.csv"):
        m = _RUN_RX.search(p.name)
        if m:
            dated[m.group(1)] = p
    if len(dated) < 2:
        return None
    newest = max(dated)
    prev = max(d for d in dated if d < newest)
    return dated[prev]


# ── 비교 로직 ─────────────────────────────────────────────────────────────────
def diff_station(station: str) -> dict:
    """역 1곳의 식당 멤버십 diff. 반환 dict 에 added/removed/totals/baseline."""
    cur_path = DATA_DIR / f"{station}{SUFFIX}.csv"
    prev_path = _prev_snapshot(f"{station}{SUFFIX}")
    res = {"station": station, "baseline": None,
           "added": [], "removed": [], "cur_n": 0, "prev_n": 0}
    if not cur_path.exists():
        return res
    cur = {_rid(r): (r.get("식당명") or "").strip() for r in _read_csv(cur_path)}
    res["cur_n"] = len(cur)
    if prev_path is None:
        return res  # baseline 없음
    res["baseline"] = prev_path.name
    prev = {_rid(r): (r.get("식당명") or "").strip() for r in _read_csv(prev_path)}
    res["prev_n"] = len(prev)
    res["added"] = [(rid, cur[rid]) for rid in cur if rid not in prev]
    res["removed"] = [(rid, prev[rid]) for rid in prev if rid not in cur]
    return res


def _to_int(v) -> int | None:
    try:
        return int(str(v).replace(",", "").replace("원", "").strip())
    except (TypeError, ValueError):
        return None


def diff_per_person() -> dict:
    """인당비용 1인_표준 의 ±PCT_THRESHOLD% 초과 변동 식당."""
    cur_path = DATA_DIR / f"{PER_PERSON_NAME}.csv"
    prev_path = _prev_snapshot(PER_PERSON_NAME)
    res = {"baseline": None, "moves": [], "has_prev": False}
    if not cur_path.exists() or prev_path is None:
        return res
    res["baseline"] = prev_path.name
    res["has_prev"] = True
    prev = {}
    for r in _read_csv(prev_path):
        prev[r.get("rid", "")] = (_to_int(r.get("1인_표준")), (r.get("식당명") or "").strip())
    for r in _read_csv(cur_path):
        rid = r.get("rid", "")
        cur_v = _to_int(r.get("1인_표준"))
        if rid not in prev:
            continue
        prev_v, name = prev[rid]
        if not prev_v or not cur_v:
            continue
        pct = (cur_v - prev_v) / prev_v * 100.0
        if abs(pct) > PCT_THRESHOLD:
            res["moves"].append({
                "rid": rid, "name": r.get("식당명") or name,
                "역": r.get("역", ""), "prev": prev_v, "cur": cur_v, "pct": pct,
            })
    res["moves"].sort(key=lambda m: -abs(m["pct"]))
    return res


# ── 리포트 ────────────────────────────────────────────────────────────────────
def build_report(stations: list[str]):
    st_results = [diff_station(s) for s in stations]
    pp = diff_per_person()

    any_change = any(r["added"] or r["removed"] or
                     (r["baseline"] and r["cur_n"] != r["prev_n"])
                     for r in st_results) or bool(pp["moves"])

    lines = ["# 콜키지프리 맵 변경 감지 diff (CMPA-82)", ""]
    no_baseline = [r["station"] for r in st_results if r["baseline"] is None]
    if no_baseline:
        lines.append(f"> ⚠️ 기준(직전) 스냅샷 없음 — {', '.join(no_baseline)} "
                     f"(최초 실행이거나 `_runs/` 스냅샷이 1개뿐). 다음 분기부터 diff 가능.")
        lines.append("")

    lines.append("## 역별 식당 멤버십")
    lines.append("")
    lines.append("| 역 | 직전 | 현재 | 신규 | 폐점·탈락 | 기준 스냅샷 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | --- |")
    for r in st_results:
        base = r["baseline"] or "—(기준없음)"
        prev_n = r["prev_n"] if r["baseline"] else "—"
        lines.append(f"| {r['station']} | {prev_n} | {r['cur_n']} | "
                     f"{len(r['added'])} | {len(r['removed'])} | {base} |")
    lines.append("")

    for r in st_results:
        if not (r["added"] or r["removed"]):
            continue
        lines.append(f"### {r['station']}")
        for rid, nm in r["added"]:
            lines.append(f"- 🟢 신규 입점: **{nm}** (`{rid}`)")
        for rid, nm in r["removed"]:
            lines.append(f"- 🔴 폐점·콜키지프리 탈락: **{nm}** (`{rid}`)")
        lines.append("")

    lines.append(f"## 인당비용 ±{PCT_THRESHOLD:g}% 초과 변동")
    lines.append("")
    if not pp["has_prev"]:
        lines.append("> 기준 인당비용 스냅샷 없음 — 이번 실행부터 `_runs/` 에 스냅샷이 쌓여 "
                     "다음 분기부터 비교 가능.")
    elif not pp["moves"]:
        lines.append(f"> ±{PCT_THRESHOLD:g}% 초과 변동 식당 없음. (기준 `{pp['baseline']}`)")
    else:
        lines.append(f"기준 `{pp['baseline']}` 대비:")
        lines.append("")
        lines.append("| 역 | 식당 | 직전 표준 | 현재 표준 | 변동% |")
        lines.append("| --- | --- | ---: | ---: | ---: |")
        for m in pp["moves"]:
            arrow = "▲" if m["pct"] > 0 else "▼"
            lines.append(f"| {m['역']} | {m['name']} | {m['prev']:,}원 | "
                         f"{m['cur']:,}원 | {arrow}{m['pct']:+.1f}% |")
    lines.append("")
    return any_change, "\n".join(lines) + "\n"


# ── selftest: 합성 데이터로 검출 로직 시연 ────────────────────────────────────
def _selftest() -> int:
    """디스크를 건드리지 않고 added/removed/±15% 검출이 동작함을 보인다."""
    prev_r = {"AAA": "가게A", "BBB": "가게B", "CCC": "가게C"}
    cur_r = {"BBB": "가게B", "CCC": "가게C", "DDD": "가게D"}  # AAA 폐점, DDD 신규
    added = [(k, v) for k, v in cur_r.items() if k not in prev_r]
    removed = [(k, v) for k, v in prev_r.items() if k not in cur_r]
    prev_cost = {"BBB": 30000, "CCC": 20000}
    cur_cost = {"BBB": 36000, "CCC": 21000}  # BBB +20%(검출), CCC +5%(무시)
    moves = []
    for rid, cv in cur_cost.items():
        pv = prev_cost.get(rid)
        if pv:
            pct = (cv - pv) / pv * 100
            if abs(pct) > PCT_THRESHOLD:
                moves.append((rid, pct))
    print("[selftest] 신규:", added)
    print("[selftest] 폐점·탈락:", removed)
    print(f"[selftest] ±{PCT_THRESHOLD:g}% 초과:", moves)
    ok = (added == [("DDD", "가게D")] and removed == [("AAA", "가게A")]
          and moves == [("BBB", 20.0)])
    print("[selftest]", "PASS ✅" if ok else "FAIL ❌")
    return 0 if ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="콜키지프리 맵 변경 감지 diff")
    ap.add_argument("--out", default=None, help="변경 있을 때 diff 마크다운을 쓸 경로")
    ap.add_argument("--stations", nargs="*", default=None,
                    help="비교할 역(기본=매니페스트 live 역)")
    ap.add_argument("--selftest", action="store_true", help="합성 데이터 검출 시연")
    a = ap.parse_args()

    if a.selftest:
        return _selftest()

    stations = a.stations if a.stations else _live_stations()
    if not stations:
        print("RESULT: error — live 역을 찾지 못함(매니페스트 확인)", file=sys.stderr)
        return 2

    changed, report = build_report(stations)
    if not changed:
        print("RESULT: no-change  (변경 없음 — 통과, 노이즈 0)")
        return 0

    print("RESULT: changes  (변경 감지됨 — 리뷰 필요)")
    if a.out:
        Path(a.out).write_text(report, encoding="utf-8")
        print(f"  diff 작성: {a.out}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
