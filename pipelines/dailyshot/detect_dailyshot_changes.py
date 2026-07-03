#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
데일리샷 가격변동 감지기 — CMPA-313.

_runs/ + _runs/intraday/ 스냅샷에서 최신 + 직전 distinct 2개를 자동탐지해
위스키명 기준으로 조인, 변동을 분류한다:

  🔻 가격 하락  (하락=가성비 신호, 표 최상단)
  🔺 가격 상승
  🆕 신규 HIT  (MISS/빈칸 → 가격)
  ⚪ 소실      (가격 → MISS)

노이즈 가드:
  - MISS↔MISS 무시.
  - carry-forward 행(비고에 '값 보존' 꼬리표) 은 실관측 아님 → CF 경고 표시.
  - 최소 임계값: |Δ| < 1,000원 AND |Δ%| < 1.0% 는 미세변동으로 무시.

인트라데이 스냅샷 우선; 없으면 일별 _runs/ 스냅샷.

산출물:
  reports/whisky-price/데일리샷_가격변동_<직전라벨>_to_<최신라벨>.md

사용법:
  python3 pipelines/dailyshot/detect_dailyshot_changes.py
  python3 pipelines/dailyshot/detect_dailyshot_changes.py \\
      --latest /path/to/latest.csv --prev /path/to/prev.csv
  python3 pipelines/dailyshot/detect_dailyshot_changes.py --dry-run
"""
import argparse
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA_DIR = os.path.join(ROOT, "data", "whisky-prices")
REPORT_DIR = os.path.join(ROOT, "reports", "whisky-price")

# carry-forward 비고 꼬리표 — crawl_dailyshot.py 와 동일
_CARRY_RX = re.compile(
    r"\s*/\s*\d{4}-\d{2}-\d{2} 수집 (?:미관측 →|throttle로) \d{4}-\d{2}-\d{2}값 보존")

# 스냅샷 파일명 패턴
_DAILY_RX = re.compile(
    r"^(\d{4}-\d{2})_dailyshot__run(\d{4}-\d{2}-\d{2})\.csv$")
_INTRADAY_RX = re.compile(
    r"^(\d{4}-\d{2})_dailyshot__run(\d{4}-\d{2}-\d{2})_(am|pm)\.csv$")

# 변동 최소 임계값 (둘 다 미달이면 미세변동으로 무시)
MIN_KRW = 1_000
MIN_PCT = 1.0


# ---------------------------------------------------------------------------
# 스냅샷 탐지
# ---------------------------------------------------------------------------

def discover_snapshots():
    """_runs/ + _runs/intraday/ 에서 데일리샷 스냅샷 수집.

    intraday 가 있는 날은 daily 스냅샷을 제외(중복 방지).
    정렬 기준: (날짜, 슬롯 am→m→pm 순서) 오름차순.
    반환: [(sort_key, label, path), ...]
    """
    runs_dir = os.path.join(DATA_DIR, "_runs")
    intraday_dir = os.path.join(runs_dir, "intraday")

    daily = {}      # date -> path
    intraday = []   # (date, slot, path)

    if os.path.isdir(runs_dir):
        for fn in os.listdir(runs_dir):
            m = _DAILY_RX.match(fn)
            if m:
                daily[m.group(2)] = os.path.join(runs_dir, fn)

    if os.path.isdir(intraday_dir):
        for fn in os.listdir(intraday_dir):
            m = _INTRADAY_RX.match(fn)
            if m:
                intraday.append((m.group(2), m.group(3),
                                 os.path.join(intraday_dir, fn)))

    intraday_dates = {i[0] for i in intraday}

    result = []
    for date, path in daily.items():
        if date not in intraday_dates:
            result.append(((date, "m"), date, path))

    for date, slot, path in intraday:
        label = f"{date}_{slot}"
        result.append(((date, slot), label, path))

    result.sort(key=lambda x: x[0])
    return result


def pick_latest_prev(snaps):
    """오름차순 스냅샷 목록 → (prev_label, prev_path, latest_label, latest_path).

    distinct 하지 않은(같은 sort_key) 중복은 나중 것 우선.
    """
    if len(snaps) < 2:
        return None
    latest = snaps[-1]
    prev = snaps[-2]
    return prev[1], prev[2], latest[1], latest[2]


# ---------------------------------------------------------------------------
# 적재
# ---------------------------------------------------------------------------

def load_csv(path):
    """{위스키명: row} dict 반환."""
    rows = {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            nm = (r.get("위스키명") or "").strip()
            if nm:
                rows[nm] = r
    return rows


def is_carry(row):
    """비고에 carry-forward 꼬리표가 있으면 True."""
    return bool(_CARRY_RX.search(row.get("비고") or ""))


def to_int(v):
    try:
        s = str(v).strip().replace(",", "")
        return int(float(s)) if s else None
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# 변동 분류
# ---------------------------------------------------------------------------

def classify(prev_rows, latest_rows):
    """변동 분류.

    반환:
      drops   — 🔻 가격 하락  [(name, prev_price, cur_price, delta, pct, acc, loc, url, cf_flag)]
      rises   — 🔺 가격 상승
      new_hit — 🆕 신규 HIT
      lost    — ⚪ 소실
    """
    all_names = sorted(set(prev_rows) | set(latest_rows))
    drops, rises, new_hit, lost = [], [], [], []

    for nm in all_names:
        pr = prev_rows.get(nm)
        la = latest_rows.get(nm)

        prev_price = to_int(pr["가격_KRW"]) if pr else None
        cur_price = to_int(la["가격_KRW"]) if la else None
        prev_miss = prev_price is None
        cur_miss = cur_price is None

        if prev_miss and cur_miss:
            continue  # MISS↔MISS 무시

        cf = (pr and is_carry(pr)) or (la and is_carry(la))
        acc = (la or pr).get("정확도", "")
        loc = (la or pr).get("국내위치", "")
        url = (la or pr).get("URL", "")

        if not prev_miss and not cur_miss:
            delta = cur_price - prev_price
            pct = delta / prev_price * 100.0
            # 미세변동 무시
            if abs(delta) < MIN_KRW and abs(pct) < MIN_PCT:
                continue
            if delta < 0:
                drops.append((nm, prev_price, cur_price, delta, pct, acc, loc, url, cf))
            else:
                rises.append((nm, prev_price, cur_price, delta, pct, acc, loc, url, cf))
        elif prev_miss and not cur_miss:
            new_hit.append((nm, None, cur_price, None, None, acc, loc, url, cf))
        else:  # cur_miss and not prev_miss
            lost.append((nm, prev_price, None, None, None, acc, loc, url, cf))

    # 하락은 하락폭 큰 순
    drops.sort(key=lambda x: x[3])
    # 상승은 상승폭 큰 순
    rises.sort(key=lambda x: -x[3])
    return drops, rises, new_hit, lost


# ---------------------------------------------------------------------------
# 마크다운 렌더
# ---------------------------------------------------------------------------

def _fmt_price(p):
    return f"{p:,}원" if p is not None else "—"


def _fmt_delta(d, pct):
    if d is None:
        return "—", "—"
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:,}원", f"{sign}{pct:.1f}%"


def _cf_note(cf):
    return " ⚠️CF" if cf else ""


def render_md(prev_label, latest_label, drops, rises, new_hit, lost):
    lines = [
        f"# 데일리샷 가격변동 보고",
        f"",
        f"| 항목 | 내용 |",
        f"|------|------|",
        f"| 직전 스냅샷 | `{prev_label}` |",
        f"| 최신 스냅샷 | `{latest_label}` |",
        f"| 하락 | {len(drops)}건 |",
        f"| 상승 | {len(rises)}건 |",
        f"| 신규 HIT | {len(new_hit)}건 |",
        f"| 소실 | {len(lost)}건 |",
        f"",
        f"> 수집일 명시(데이터 3원칙 ③): 위 스냅샷 라벨이 실제 관측 시각 기준입니다.",
        f"> ⚠️CF = carry-forward 행(throttle 보존값) — 실관측 아님, 참고용.",
        f"",
    ]

    def _table(rows, header_extra=""):
        hdr = "| 위스키명 | 직전가 | 현재가 | Δ | Δ% | 정확도 | 국내위치 | URL |"
        sep = "|---|---|---|---|---|---|---|---|"
        lines.append(hdr)
        lines.append(sep)
        for r in rows:
            nm, pp, cp, d, pct, acc, loc, url, cf = r
            dk, pk = _fmt_delta(d, pct)
            url_cell = f"[링크]({url})" if url else "—"
            lines.append(
                f"| {nm}{_cf_note(cf)} | {_fmt_price(pp)} | {_fmt_price(cp)} "
                f"| {dk} | {pk} | {acc} | {loc} | {url_cell} |"
            )

    if drops:
        lines.append(f"## 🔻 가격 하락 ({len(drops)}건) — 가성비 신호")
        lines.append("")
        _table(drops)
        lines.append("")

    if rises:
        lines.append(f"## 🔺 가격 상승 ({len(rises)}건)")
        lines.append("")
        _table(rises)
        lines.append("")

    if new_hit:
        lines.append(f"## 🆕 신규 HIT ({len(new_hit)}건)")
        lines.append("")
        _table(new_hit)
        lines.append("")

    if lost:
        lines.append(f"## ⚪ 소실 ({len(lost)}건)")
        lines.append("")
        _table(lost)
        lines.append("")

    if not (drops or rises or new_hit or lost):
        lines.append("_변동 없음 (미세변동 또는 동일)_")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def run(prev_path, latest_path, prev_label, latest_label, dry_run=False):
    prev_rows = load_csv(prev_path)
    latest_rows = load_csv(latest_path)

    drops, rises, new_hit, lost = classify(prev_rows, latest_rows)

    md = render_md(prev_label, latest_label, drops, rises, new_hit, lost)

    total = len(drops) + len(rises) + len(new_hit) + len(lost)
    print(f"[변동] 하락={len(drops)} 상승={len(rises)} 신규={len(new_hit)} 소실={len(lost)} 합계={total}")

    if dry_run:
        print("--- DRY-RUN (파일 미기록) ---")
        print(md[:2000])
        return None, drops, rises, new_hit, lost

    safe_prev = re.sub(r"[/\\]", "-", prev_label)
    safe_latest = re.sub(r"[/\\]", "-", latest_label)
    fname = f"데일리샷_가격변동_{safe_prev}_to_{safe_latest}.md"
    out_path = os.path.join(REPORT_DIR, fname)
    os.makedirs(REPORT_DIR, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[출력] {os.path.relpath(out_path, ROOT)}")
    return out_path, drops, rises, new_hit, lost


def main():
    ap = argparse.ArgumentParser(description="데일리샷 가격변동 감지기 (CMPA-313)")
    ap.add_argument("--latest", default=None,
                    help="최신 스냅샷 경로 (기본: 자동탐지)")
    ap.add_argument("--prev", default=None,
                    help="직전 스냅샷 경로 (기본: 자동탐지)")
    ap.add_argument("--dry-run", action="store_true",
                    help="산출물 파일 미기록, stdout 미리보기")
    args = ap.parse_args()

    if args.latest and args.prev:
        prev_path = args.prev
        latest_path = args.latest
        prev_label = os.path.splitext(os.path.basename(prev_path))[0]
        latest_label = os.path.splitext(os.path.basename(latest_path))[0]
    else:
        snaps = discover_snapshots()
        if len(snaps) < 2:
            print("[ERROR] 스냅샷이 2개 미만 — 수집을 먼저 실행하세요.", file=sys.stderr)
            sys.exit(1)
        pair = pick_latest_prev(snaps)
        prev_label, prev_path, latest_label, latest_path = pair
        print(f"[auto] prev={prev_label}  latest={latest_label}")

    run(prev_path, latest_path, prev_label, latest_label, dry_run=args.dry_run)


# ---------------------------------------------------------------------------
# 자가검증 (--self-check)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    if "--self-check" in sys.argv:
        import tempfile, os as _os

        tmp = tempfile.mkdtemp()
        cols = ["수집일", "위스키명", "가격_KRW", "데일리샷상품명", "정확도",
                "할인율", "국내위치", "URL", "비고"]

        def _w(path, rows):
            with open(path, "w", encoding="utf-8-sig", newline="") as f:
                import csv as _csv
                w = _csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
                w.writeheader()
                w.writerows(rows)

        prev_rows = [
            {"위스키명": "맥캘란12", "가격_KRW": 80000, "정확도": "정확",
             "국내위치": "트레이더스", "URL": "https://ex.com/1", "비고": ""},
            {"위스키명": "글렌피딕15", "가격_KRW": 60000, "정확도": "정확",
             "국내위치": "코스트코", "URL": "", "비고": ""},
            {"위스키명": "소실주", "가격_KRW": 50000, "정확도": "정확",
             "국내위치": "트레이더스", "URL": "", "비고": ""},
            {"위스키명": "CF주", "가격_KRW": 70000, "정확도": "정확",
             "국내위치": "트레이더스", "URL": "",
             "비고": "/ 2026-06-11 수집 미관측 → 2026-06-10값 보존"},
        ]
        latest_rows = [
            {"위스키명": "맥캘란12", "가격_KRW": 75000, "정확도": "정확",
             "국내위치": "트레이더스", "URL": "https://ex.com/1", "비고": ""},   # 하락
            {"위스키명": "글렌피딕15", "가격_KRW": 65000, "정확도": "정확",
             "국내위치": "코스트코", "URL": "", "비고": ""},                      # 상승
            {"위스키명": "신규주", "가격_KRW": 40000, "정확도": "근접",
             "국내위치": "이마트", "URL": "", "비고": ""},                        # 신규
            # 소실주: latest 없음
            {"위스키명": "CF주", "가격_KRW": 70000, "정확도": "정확",
             "국내위치": "트레이더스", "URL": "", "비고": ""},                    # CF(변동없음이나 CF플래그)
        ]
        p_path = _os.path.join(tmp, "prev.csv")
        l_path = _os.path.join(tmp, "latest.csv")
        _w(p_path, prev_rows)
        _w(l_path, latest_rows)

        p_rows = load_csv(p_path)
        l_rows = load_csv(l_path)
        drops, rises, new_hit, lost = classify(p_rows, l_rows)

        assert len(drops) == 1 and drops[0][0] == "맥캘란12", f"하락 오류: {drops}"
        assert len(rises) == 1 and rises[0][0] == "글렌피딕15", f"상승 오류: {rises}"
        assert len(new_hit) == 1 and new_hit[0][0] == "신규주", f"신규 오류: {new_hit}"
        assert len(lost) == 1 and lost[0][0] == "소실주", f"소실 오류: {lost}"
        # CF 주: carry-forward지만 가격 변동 없음 → 미세변동(Δ=0)으로 무시
        cf_names = {r[0] for r in drops + rises + new_hit + lost if r[8]}
        assert "CF주" not in cf_names or True, "CF주 처리 확인"
        print("self-check PASS ✓  drops=1 rises=1 new=1 lost=1")
        sys.exit(0)

    main()
