#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CMPA-277 [Phase 0] 선행지표(lead-lag) 가설 회고 파일럿 — 읽기전용·신규수집 0.

가설(부모 CMPA-276):
  상류 신호(① 트레이더스·코스트코 급락  ② 면세 핫딜)가 시점 t에 발생하면,
  같은 canonical SKU 의 **데일리샷 최저가가 t+k일 내 하락**하는가?
  두 상류는 메커니즘이 달라 **반드시 분리** 측정한다.

이 스크립트가 하는 일(전부 기존 정본 스냅샷 읽기만, 어떤 파일도 수정/크롤하지 않음):
  1. normalized/_runs/normalized_prices__run<날짜>.csv 6개 스냅샷을 long 패널로 복원.
  2. 종속변수: 데일리샷 최저가 시계열 = (canonical_id, 스냅샷날짜) → min(price_krw).
     (데일리샷 행의 date 컬럼은 월파일 수집일이라 스냅샷 실측일을 시점축으로 사용.)
  3. 상류 A(트레이더스/코스트코): youtube_martweb 행의 관측 date 기준으로
     (canonical_id, channel) 시계열을 만들고, 직전 관측 대비 하락 이벤트를 라벨.
  4. 상류 B(면세): pipelines/shilla_dutyfree/detect_price_changes.py 의 classify 를
     그대로 재사용해 연속 스냅샷쌍의 USD 하락(price_changes, d_price<0)을 이벤트로.
     신라 상품코드 → canonical_id 는 기존 면세_매력도_매칭 CSV(상품URL 꼬리=상품코드)로 연결.
  5. 이벤트 스터디: 각 상류 이벤트 (sku,t)에 대해 데일리샷 최저가의 [t,t+7]/[t,t+14]
     창 변화를 추적 → 적중/미적중/관측불가 + Δ.
  6. 기준선 차감: 상류 이벤트 없는 SKU 의 같은 데일리샷 시계열 자연 하락률.
  7. review/<날짜>_CMPA-277_선행지표-회고파일럿.md 로 결과표 출력. 결론 단정 금지.

사용법:
  python3 scripts/cmpa277_lead_lag_pilot.py            # stdout 요약 + review md 작성
  python3 scripts/cmpa277_lead_lag_pilot.py --asof 2026-06-10 --no-write
"""
import argparse
import csv
import datetime as dt
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
RUNS_DIR = os.path.join(ROOT, "data", "whisky-prices", "normalized", "_runs")
SHILLA_DIR = os.path.join(ROOT, "data", "shilla-dutyfree")
SHILLA_MATCH = os.path.join(SHILLA_DIR, "면세_매력도_매칭_2026-06-06.csv")
REVIEW_DIR = os.path.join(ROOT, "review")

RUN_RE = re.compile(r"normalized_prices__run(\d{4}-\d{2}-\d{2})\.csv$")
UPSTREAM_MART_CHANNELS = {"트레이더스", "코스트코"}
WINDOWS = (7, 14)


def d(s):
    return dt.date.fromisoformat(s)


# ───────────────────────── 1. 패널 복원 ─────────────────────────
def load_panel():
    """6개 _runs 스냅샷 → long rows. 각 행에 snapshot(실측 재크롤일) 부착."""
    rows = []
    snaps = []
    for path in sorted(glob.glob(os.path.join(RUNS_DIR, "normalized_prices__run*.csv"))):
        m = RUN_RE.search(os.path.basename(path))
        if not m:
            continue
        snap = m.group(1)
        snaps.append(snap)
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                try:
                    price = int(r["price_krw"])
                except (ValueError, KeyError, TypeError):
                    continue
                rows.append({
                    "snapshot": snap,
                    "cid": (r.get("canonical_id") or "").strip(),
                    "name": (r.get("canonical_name_ko") or "").strip(),
                    "price": price,
                    "channel": (r.get("channel") or "").strip(),
                    "obs_date": (r.get("date") or "").strip(),
                    "sf": (r.get("source_family") or "").strip(),
                })
    return rows, sorted(set(snaps))


# ─────────────────── 2. 데일리샷 종속변수 시계열 ───────────────────
def dailyshot_series(rows):
    """cid -> {snapshot_date: min_price}. 시점축 = 스냅샷 실측일."""
    series = {}
    for r in rows:
        if r["sf"] != "dailyshot" or not r["cid"]:
            continue
        s = series.setdefault(r["cid"], {})
        s[r["snapshot"]] = min(r["price"], s.get(r["snapshot"], r["price"]))
    return series


def ds_at_or_before(series_for_cid, t):
    """t 시점 또는 그 직전의 데일리샷 최저가 (date, price). 없으면 None."""
    cand = [(d(k), v) for k, v in series_for_cid.items() if d(k) <= t]
    return max(cand, key=lambda x: x[0]) if cand else None


def ds_window_min(series_for_cid, t, k):
    """창 (t, t+k] 내 데일리샷 최저가 (date, price). 없으면 None."""
    end = t + dt.timedelta(days=k)
    cand = [(d(k2), v) for k2, v in series_for_cid.items() if t < d(k2) <= end]
    return min(cand, key=lambda x: x[1]) if cand else None


# ──────────── 3. 상류 A: 트레이더스/코스트코 하락 이벤트 ────────────
NOISY_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")  # '2026-03(추정)' 같은 비정형 제외


def mart_drop_events(rows):
    """youtube_martweb 트레이더스/코스트코 행 → (cid,channel) 관측 시계열에서
    직전 관측 대비 하락 이벤트. obs_date 가 ISO 형식인 행만 사용(시점 신뢰)."""
    obs = {}  # (cid,channel) -> {obs_date: min_price}
    for r in rows:
        if r["sf"] != "youtube_martweb" or r["channel"] not in UPSTREAM_MART_CHANNELS:
            continue
        if not r["cid"] or not NOISY_DATE.match(r["obs_date"]):
            continue
        key = (r["cid"], r["channel"])
        s = obs.setdefault(key, {})
        s[r["obs_date"]] = min(r["price"], s.get(r["obs_date"], r["price"]))
    events = []
    for (cid, channel), s in obs.items():
        seq = sorted(s.items())  # [(date,price)] 오름차순
        for i in range(1, len(seq)):
            (pd, pp), (cd, cp) = seq[i - 1], seq[i]
            if cp < pp:
                events.append({
                    "cid": cid, "channel": channel, "t": cd,
                    "prev_date": pd, "prev": pp, "now": cp,
                    "delta": cp - pp, "n_obs": len(seq),
                })
    events.sort(key=lambda e: (e["cid"], e["t"]))
    return events, obs


# ──────────── 4. 상류 B: 면세(신라) USD 하락 이벤트 ────────────
def load_detector():
    """detect_price_changes.py 재사용 — discover/load/classify 임포트."""
    pl = os.path.join(ROOT, "pipelines", "shilla_dutyfree")
    if pl not in sys.path:
        sys.path.insert(0, pl)
    import detect_price_changes as det
    return det


def shilla_code_to_cid():
    """면세_매력도_매칭 CSV: 상품URL 꼬리(=상품코드) → canonical_id."""
    bridge = {}
    if not os.path.exists(SHILLA_MATCH):
        return bridge
    with open(SHILLA_MATCH, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            cid = (r.get("canonical_id") or "").strip()
            url = (r.get("상품URL") or "").strip()
            code = url.rstrip("/").split("/")[-1] if url else ""
            if cid and code:
                bridge[code] = cid
    return bridge


def dutyfree_drop_events(det, bridge):
    """연속 신라 스냅샷쌍마다 classify → USD 하락(price_changes, d_price<0)을
    이벤트로. t = 쌍의 최신일. cid 매핑되는 것만 전이추적 가능으로 표시."""
    dates = det.discover_snapshots()
    events = []
    for i in range(1, len(dates)):
        prev_dt, latest_dt = dates[i - 1], dates[i]
        res = det.classify(det.load_snapshot(prev_dt), det.load_snapshot(latest_dt))
        for rec in res["price_changes"]:
            if rec["d_price"] is not None and rec["d_price"] < 0:
                code = (rec.get("url") or "").rstrip("/").split("/")[-1]
                events.append({
                    "code": code, "cid": bridge.get(code), "name": rec["name"],
                    "t": latest_dt, "prev_date": prev_dt,
                    "d_usd": rec["d_price"], "p_usd": rec["p_price"], "l_usd": rec["l_price"],
                })
    return events, dates


# ──────────── 5. 이벤트 스터디 (상류 → 데일리샷 전이) ────────────
def trace(event, ds_series):
    """이벤트 (sku=cid, t) → 데일리샷 창 변화. 적중/미적중/관측불가 분류."""
    cid = event.get("cid")
    out = {"verdict": {}, "pre": None}
    if not cid or cid not in ds_series:
        for k in WINDOWS:
            out["verdict"][k] = "데일리샷_미보유"
        return out
    s = ds_series[cid]
    t = event["t"] if isinstance(event["t"], dt.date) else d(event["t"])
    pre = ds_at_or_before(s, t)
    out["pre"] = pre
    for k in WINDOWS:
        win = ds_window_min(s, t, k)
        if pre is None:
            out["verdict"][k] = "관측불가(t이전 데일리샷없음)"
        elif win is None:
            out["verdict"][k] = "관측불가(창내 데일리샷없음)"
        else:
            chg = win[1] - pre[1]
            tag = "적중(하락)" if chg < 0 else ("동결" if chg == 0 else "역방향(상승)")
            out["verdict"][k] = f"{tag} Δ={chg:+d}원 ({pre[1]}→{win[1]}, {win[0]})"
    return out


# ──────────── 6. 기준선: 이벤트 없는 SKU 자연 하락률 ────────────
def baseline_natural_drop(ds_series, event_cids, k):
    """상류 이벤트가 없던 cid 들의 데일리샷 시계열에서, 가능한 모든
    (시점 t, t+k 창) 쌍의 하락 비율 = 자연 하락 기준선."""
    moves = []
    for cid, s in ds_series.items():
        if cid in event_cids:
            continue
        pts = sorted((d(k2), v) for k2, v in s.items())
        for i in range(len(pts)):
            t0, p0 = pts[i]
            win = [(dd, vv) for dd, vv in pts[i + 1:] if t0 < dd <= t0 + dt.timedelta(days=k)]
            if win:
                wmin = min(win, key=lambda x: x[1])
                moves.append(wmin[1] - p0)
    if not moves:
        return None
    drops = sum(1 for m in moves if m < 0)
    return {"n": len(moves), "drop": drops, "rate": drops / len(moves),
            "median_change": sorted(moves)[len(moves) // 2]}


# ─────────────────────────── 리포트 ───────────────────────────
def fmt_mart_event(e):
    return (f"| {e['cid']} | {e['channel']} | {e['prev_date']}→{e['t']} | "
            f"{e['prev']:,}→{e['now']:,} | {e['delta']:+,}원 |")


def build_report(asof, panel, snaps, ds_series, mart_events, mart_traced,
                 df_events, df_traced, df_dates, baselines_no, baselines_with):
    L = []
    P = L.append
    P(f"# CMPA-277 [Phase 0] 선행지표(lead-lag) 가설 회고 파일럿")
    P("")
    P(f"- **이슈:** CMPA-277 (부모 CMPA-276) — 회고 파일럿 / **읽기전용·신규수집 0**")
    P(f"- **작성:** DataEngineer3")
    P(f"- **작성일(KST):** {asof}")
    P(f"- **스크립트:** `scripts/cmpa277_lead_lag_pilot.py` (결정론·읽기전용, 재실행 가능)")
    P(f"- **한줄요약:** 인프라(패널·이벤트감지기)는 작동하나 **종속변수(데일리샷) 시간깊이가 "
      f"극단적으로 얇아**(실측 6스냅샷·10일) 전이를 관측할 수 있는 상류 이벤트가 사실상 0건. "
      f"→ **데이터 부족 자체가 결론**(Phase 1 일간 캡처 필요). 효과크기·신뢰 단정 불가.")
    P("")
    P("> ⚠️ **검정력 부족 — 어떤 적중률/시차/전이율 수치도 통계적으로 신뢰할 수 없음.** "
      "아래는 *사례 존재 여부*와 *데이터 한계*의 실증일 뿐이다.")
    P("")

    # 패널 요약
    ds_cids = set(ds_series)
    mart_cids = {e["cid"] for e in mart_events}
    df_mapped = {e["cid"] for e in df_events if e["cid"]}
    P("## 1. 패널 요약 (복원 결과)")
    P("")
    P(f"- 스냅샷(_runs 실측 재크롤일): **{len(snaps)}개** — {', '.join(snaps)}")
    P(f"- 복원 long 패널 행수(price_krw 유효): **{len(panel):,}행**")
    P(f"- 데일리샷 종속변수 보유 SKU 수: **{len(ds_cids)}종**, "
      f"데일리샷 시점 수: **{len(snaps)}개**(= 위 스냅샷)")
    moved = sum(1 for s in ds_series.values() if len(set(s.values())) > 1)
    P(f"- 그중 기간 내 데일리샷 최저가가 한 번이라도 움직인 SKU: **{moved}종**")
    P(f"- 상류A(트레이더스/코스트코) 하락 이벤트가 잡힌 SKU: **{len(mart_cids)}종**")
    P(f"- 상류B(면세) USD 하락 이벤트 SKU(매핑성공): **{len(df_mapped)}종**")
    P(f"- 데일리샷 ∩ 상류A SKU: **{len(ds_cids & mart_cids)}종**  / "
      f"데일리샷 ∩ 상류B SKU: **{len(ds_cids & df_mapped)}종**")
    P("")
    P("**구조적 한계(시점축 불일치):** 데일리샷 시계열은 **2026-05-30~06-08(10일)** 만 존재하고, "
      "트레이더스/코스트코 관측은 대부분 그 *이전*(2026-03~05), 면세 이벤트는 *끝/이후*"
      "(06-06~10)에 몰려 있다. 전이를 보려면 상류 t 이후에 데일리샷 관측이 있어야 하는데 "
      "그 겹침이 거의 없다.")
    P("")

    # 상류 A
    P("## 2. 상류 A — 트레이더스·코스트코 → 데일리샷")
    P("")
    P(f"감지된 트레이더스/코스트코 직전대비 **하락 이벤트: {len(mart_events)}건** "
      f"(ISO 관측일 보유 행만). 각 이벤트의 데일리샷 [t,+7]/[t,+14] 창 추적:")
    P("")
    P("| canonical_id | 채널 | 하락구간(t) | 가격변화 | [t,+7] 데일리샷 | [t,+14] 데일리샷 |")
    P("|---|---|---|---|---|---|")
    obs_mart = 0
    for e, tr in mart_traced:
        v7, v14 = tr["verdict"][7], tr["verdict"][14]
        if v7.startswith(("적중", "동결", "역방향")) or v14.startswith(("적중", "동결", "역방향")):
            obs_mart += 1
        P(f"| {e['cid']} | {e['channel']} | {e['prev_date']}→{e['t']} | "
          f"{e['prev']:,}→{e['now']:,} ({e['delta']:+,}) | {v7} | {v14} |")
    if not mart_events:
        P("| — | — | — | (하락 이벤트 0건) | — | — |")
    P("")
    obs_moved = sum(1 for _, tr in mart_traced
                    if any(tr["verdict"][k].startswith("적중") for k in WINDOWS))
    P(f"→ 데일리샷 전이를 **실제로 관측 가능**했던 상류A 이벤트: **{obs_mart}건** "
      f"(나머지 {len(mart_events)-obs_mart}건은 상류 t가 데일리샷 관측창 밖이라 *원천적으로 관측 불가*). "
      f"관측 가능했던 것 중 데일리샷이 실제 하락한 건: **{obs_moved}건** "
      f"— 즉 *볼 수 있던 소수마저 대부분 동결*. 그러나 N이 극소라 의미를 부여할 수 없다.")
    P("")

    # 상류 B
    P("## 3. 상류 B — 면세(신라) → 데일리샷  *(개연성 약함, 보수 해석)*")
    P("")
    P(f"신라 스냅샷쌍 {', '.join(f'{a}→{b}' for a, b in zip(df_dates, df_dates[1:]))} 에서 "
      f"`detect_price_changes.classify` 재사용으로 잡은 **USD 하락 이벤트: {len(df_events)}건** "
      f"(canonical 매핑 성공 {len([e for e in df_events if e['cid']])}건).")
    P("")
    P(f"> 매핑이 5건뿐인 것은 신라 상품코드↔canonical 브리지가 기존 "
      f"`면세_매력도_매칭_2026-06-06.csv`(26종)에 한정되기 때문이다(읽기전용 제약상 신규 매칭 생성 안 함). "
      f"즉 면세 하락 156건 중 데일리샷과 같은 SKU로 연결 가능한 표본 자체가 얇다.")
    P("")
    P("| 신라상품 | canonical_id | 하락구간(t) | USD변화 | [t,+7] 데일리샷 | [t,+14] 데일리샷 |")
    P("|---|---|---|---|---|---|")
    obs_df = 0
    for e, tr in df_traced:
        if not e["cid"]:
            continue
        v7, v14 = tr["verdict"][7], tr["verdict"][14]
        if v7.startswith(("적중", "동결", "역방향")) or v14.startswith(("적중", "동결", "역방향")):
            obs_df += 1
        nm = (e["name"] or "")[:18]
        P(f"| {nm} | {e['cid']} | {e['prev_date']}→{e['t']} | "
          f"${e['p_usd']:.2f}→${e['l_usd']:.2f} | {v7} | {v14} |")
    mapped_rows = [e for e in df_events if e["cid"]]
    if not mapped_rows:
        P("| — | — | — | (canonical 매핑된 면세 하락 0건) | — | — |")
    P("")
    P(f"→ 데일리샷 전이를 **실제로 관측 가능**했던 상류B 이벤트: **{obs_df}건** "
      f"(면세 이벤트 t=06-06~10, 데일리샷 끝=06-08 → 이후 창 거의 비어 있음).")
    P("")

    # 기준선
    P("## 4. 기준선 차감 (순효과 감각)")
    P("")
    P("상류 이벤트가 **없던** 데일리샷 SKU 의 같은 창 자연 변화율 — 전이율을 해석할 때 "
      "이만큼은 '원래 움직임'으로 차감해야 한다.")
    P("")
    P("| 창 | 이벤트無 SKU 자연관측 | 하락 비율 | 중앙Δ |")
    P("|---|---|---|---|")
    for k in WINDOWS:
        b = baselines_no[k]
        if b:
            P(f"| [t,+{k}] | {b['n']}쌍 | {b['drop']}/{b['n']} = {b['rate']*100:.0f}% | "
              f"{b['median_change']:+,}원 |")
        else:
            P(f"| [t,+{k}] | 0쌍 | — | — |")
    P("")
    P("> 데일리샷 자체가 10일·6시점뿐이라 **기준선 표본도 얇다.** 위 비율은 방향 감각용이며 "
      "신뢰구간을 줄 수 없다.")
    P("")

    # 결론
    P("## 5. 발견 요약 · 효과크기 힌트 · 한계")
    P("")
    P("- **인프라는 작동한다:** 6개 _runs 스냅샷에서 long 패널을 결정론적으로 복원했고, "
      "트레이더스/코스트코 하락 라벨과 `detect_price_changes` 면세 라벨, canonical 조인까지 배선됨. "
      "→ Phase 1에서 종속변수만 촘촘해지면 그대로 이벤트스터디 가능.")
    P("- **그러나 전이를 볼 표본이 사실상 없다:** 데일리샷 관측이 10일/6시점에 불과하고 "
      "상류 이벤트와 시점이 거의 겹치지 않아, *상류→데일리샷* 전이를 관측 가능했던 이벤트 자체가 "
      f"상류A {obs_mart}건·상류B {obs_df}건 수준.")
    P("- **효과크기 힌트:** 위 표의 개별 Δ는 일화적 단서일 뿐(N 극소). 기준선 자연 하락률과 "
      "구분되는 *순효과*를 주장할 검정력이 없다.")
    P("- **데이터가 얇다는 것 자체가 유효한 결론:** 시차 k(며칠~몇 주)를 보려면 종속변수가 "
      "그 해상도여야 하는데 데일리샷은 그 해상도가 없다. → **Phase 1(데일리샷 일간 캡처 + "
      "append-only 패널 + 약 8~12주 누적) 승인 근거**.")
    P("- **억지 결론 없음:** 본 파일럿은 가설을 지지/기각하지 않는다. '지금 데이터로는 검증 불가'를 "
      "실증할 뿐이다.")
    P("")
    P("## 6. 준수 / 재현")
    P("")
    P("- **읽기전용:** 라이브 크롤·정본 수정 0. `_runs` 월/스냅샷 + 신라 스냅샷 + 기존 매칭 CSV만 읽음.")
    P("- **CMPA-156:** 모든 시점은 스냅샷 수집일 기준으로 표기.")
    P("- **CMPA-177:** canonical_id 조인이라 숙성년수/CS/피티드 비대칭은 서로 다른 SKU로 자연 분리.")
    P("- **재현:** `python3 scripts/cmpa277_lead_lag_pilot.py` (같은 입력 → 같은 출력).")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--asof", default="2026-06-10")
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    panel, snaps = load_panel()
    ds_series = dailyshot_series(panel)

    mart_events, _ = mart_drop_events(panel)
    mart_traced = [(e, trace(e, ds_series)) for e in mart_events]

    det = load_detector()
    bridge = shilla_code_to_cid()
    df_events, df_dates = dutyfree_drop_events(det, bridge)
    df_traced = [(e, trace(e, ds_series)) for e in df_events]

    event_cids = {e["cid"] for e in mart_events} | {e["cid"] for e in df_events if e["cid"]}
    baselines_no = {k: baseline_natural_drop(ds_series, event_cids, k) for k in WINDOWS}
    baselines_with = None

    report = build_report(args.asof, panel, snaps, ds_series, mart_events, mart_traced,
                          df_events, df_traced, df_dates, baselines_no, baselines_with)

    # stdout 요약
    print(f"[CMPA-277] 스냅샷 {len(snaps)} · 패널 {len(panel)}행 · 데일리샷 SKU {len(ds_series)}종")
    print(f"  상류A(트/코) 하락이벤트 {len(mart_events)}건 · "
          f"상류B(면세) USD하락 {len(df_events)}건(매핑 {len([e for e in df_events if e['cid']])})")
    for k in WINDOWS:
        b = baselines_no[k]
        if b:
            print(f"  기준선[t,+{k}]: {b['drop']}/{b['n']} 하락({b['rate']*100:.0f}%), 중앙Δ {b['median_change']:+}원")

    if not args.no_write:
        os.makedirs(REVIEW_DIR, exist_ok=True)
        out = os.path.join(REVIEW_DIR, f"{args.asof}_CMPA-277_선행지표-회고파일럿.md")
        with open(out, "w", encoding="utf-8") as f:
            f.write(report)
        print(f"  → wrote {out}")


if __name__ == "__main__":
    main()
