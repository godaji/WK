#!/usr/bin/env python3
"""신라면세 발행 리포트 가격 자동갱신 오케스트레이터 (CMPA-141).

build_report_html.py 의 큐레이션 픽(이름·상품코드)에 대해 **라이브 가격**을 모아
`data/shilla-dutyfree/리포트_가격_<date>.json` 으로 출력한다. 리포트 생성기는
이 JSON 에서 가격을 로드해 렌더만 한다(에디토리얼 ↔ 가격 분리).

가격 소스
  - 면세가  = 최신 `신라면세_위스키_<date>.csv` 에서 **상품코드**로 직접 조회(USD→KRW).
              (코드 매칭이라 매칭 모호성 0 = 가장 신뢰도 높은 라이브 신호)
  - 국내최저 = min( enrich_dailyshot 라이브[면세 리스팅 제외] ,
                    normalized_prices DB floor[마트·트레이더스·코스트코·데일리샷] )
              찾으면 라이브 채택, 못 찾으면 build_report 하드코딩(baseline) 폴백.
  - 홍콩    = compare_hk(공식 보틀링 OB 매칭).
  - 이득%   = (면세 − 국내) / 국내 × 100  (음수 = 면세가 더 쌈)

가드(과거 오매칭 사례 다수 → 재사용)
  - enrich_dailyshot: 면세/해외 리스팅 제외(price_usd>0) · 바이알/미니/세트 · 브랜드+숙성+표현 일치.
  - DB floor 매칭: 정규화 부분일치 + EDITION_KW(셰리/포트/CS/퍼페추얼…) 가드 + 길이 가드.
  - 5만원 미만(샘플)·매그넘 용량은 면세 매칭에서 제외(소스 스크립트가 처리).

페르소나(국내파/함정/여행파/취향파/선물파)는 **에디토리얼 고정**(CMPA-141 기본).
이득 기준 자동 재배치는 보드 확인 후 옵션. 단, 편집 배치와 라이브 이득이 **모순**되는
경우(국내파인데 국내가 더 싸짐, 함정인데 면세가 싸짐)는 audit 로그로 큰 소리로 보고한다.

출력: data/shilla-dutyfree/리포트_가격_<date>.json
사용: python3 refresh_report_prices.py [--date YYYY-MM-DD] [--no-crawl]
"""
import argparse
import csv
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import build_report_html as B  # 큐레이션 픽(에디토리얼) 단일 진실
import enrich_dailyshot as DS
import compare_hk as HK
from analyze_attractiveness import (load_fx, load_domestic, norm, vol_of,
                                    EDITION_KW)


def man(krw):
    """KRW(정수) → 'X.X만' 표기(리포트 기존 포맷과 동일)."""
    return f"{krw / 10000:.1f}만"


def parse_man(s):
    """'8.4만' → 84000. 숫자 없는 라벨('국내 없음' 등)은 None."""
    m = re.search(r"([\d.]+)\s*만", s or "")
    return round(float(m.group(1)) * 10000) if m else None


def collect_picks():
    """build_report 의 모든 그룹에서 (name, code, fb_면세, fb_국내, group, win0) 추출."""
    picks = []
    for n, pr, dm, adv, note, code, band in B.DOMESTIC:
        picks.append((n, code, pr, dm, "국내파", True))
    for n, pr, dm, note, code in B.TRAP:
        picks.append((n, code, pr, dm, "함정", False))
    for n, pr, dm, adv, hk, note, code in B.TRAVEL:
        picks.append((n, code, pr, dm, "여행파", True))
    for cat, rows in B.TASTE.items():
        for n, pr, dm, adv, note, code in rows:
            picks.append((n, code, pr, dm, "취향파", True))
    for t in B.GIFT:
        _, n, pr, dm, adv, win, hook, note, code, story = t
        picks.append((n, code, pr, dm, "선물파", win))
    return picks


def build_dom_index():
    """normalized DB floor: [(canon_norm, low_krw, name, channels)] (마트+데일리샷 통합)."""
    dom = load_domestic()
    idx = []
    for cid, d in dom.items():
        idx.append((norm(d["name"]), round(d["low"]), d["name"],
                    "·".join(sorted(d["ch"]))))
    return idx


def db_floor(name, idx):
    """픽 이름 → DB 최저가. canonical 정규화 부분일치 + EDITION 가드 + 최단 추가."""
    pn = norm(name)
    best = None
    for cn, low, cname, ch in idx:
        if not cn or cn not in pn:
            continue
        # 비표준 피니시·강도·에디션이 픽에만 있으면 표준 DB가와 비교 부적합
        if any(kw in pn and kw not in cn for kw in EDITION_KW):
            continue
        extra = len(pn) - len(cn)
        if best is None or extra < best[0]:
            best = (extra, low, cname, ch)
    return best  # (extra, low, cname, ch) | None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=os.environ.get("SHILLA_DATE")
                    or time.strftime("%Y-%m-%d"))
    ap.add_argument("--no-crawl", action="store_true",
                    help="신라 CSV 없으면 크롤 대신 실패")
    args = ap.parse_args()
    date = args.date

    # 1) 신라면세 CSV (없으면 크롤)
    csv_path = os.path.join(ROOT, "data", "shilla-dutyfree",
                            f"신라면세_위스키_{date}.csv")
    if not os.path.exists(csv_path):
        if args.no_crawl:
            sys.exit(f"신라 CSV 없음: {csv_path} (--no-crawl)")
        print(f"신라 CSV 없음 → crawl_shilla_whisky.py {date} 실행")
        import subprocess
        subprocess.run([sys.executable,
                        os.path.join(HERE, "crawl_shilla_whisky.py"), date],
                       check=True)
    shilla = {r["상품코드"]: r for r in
              csv.DictReader(open(csv_path, encoding="utf-8-sig"))}

    usd_krw, fx_asof = load_fx()
    dom_idx = build_dom_index()
    hk_map = HK.build_hk_map(date)
    picks = collect_picks()

    # 2) 데일리샷 라이브 (코드 있는 픽 이름만, 유니크 키 페이싱)
    names = [n for n, code, *_ in picks if code]
    print(f"데일리샷 라이브 조회 {len(names)}종 …")
    ds_live = DS.build_lookup(names)

    out = {}
    audit = {"flip_trap": [], "flip_win": [], "no_domestic": [],
             "diverge": [], "editorial_none_live": [], "no_code": []}
    for name, code, fb_pr, fb_dm, group, win0 in picks:
        if not code:
            audit["no_code"].append(f"{group}/{name}")
            continue
        row = shilla.get(code)
        if not row:
            audit["no_code"].append(f"{group}/{name} (코드 {code} CSV없음)")
            continue
        try:
            # 표시가_USD = 신라 앱/웹 표시가 (마일리지 할인가). 구버전 폴백
            usd_val = row.get("표시가_USD") or row.get("할인가_USD")
            usd = float(usd_val)
        except (ValueError, TypeError):
            usd = None
        duty_krw = round(usd * usd_krw) if usd else parse_man(fb_pr)
        vol = vol_of(row["위스키명"]) or 700

        # 국내 최저 = min(데일리샷 라이브, DB floor)
        cands = []
        m = ds_live.get(name)
        if m and m.get("ds_price"):
            cands.append((m["ds_price"], "데일리샷"))
        f = db_floor(name, dom_idx)
        if f:
            cands.append((f[1], f[3] or "DB"))
        baseline = parse_man(fb_dm)
        live_low = min(cands, key=lambda x: x[0]) if cands else None

        # 채택 로직(데이터 정직성 우선):
        #  - baseline(사람 검증)이 있고 라이브가 ±DIVERGE% 넘게 벌어지면 = 오매칭 의심
        #    → 라이브 거부, baseline 유지(과거 부쉬밀 마르살라 wrong-product 사례).
        #  - baseline 라벨이 '없음'류(편집 고정)면 라이브가 잡혀도 편집 유지(스토리 모순 방지).
        DIVERGE = 35
        rejected = None
        if live_low and baseline:
            div = abs(live_low[0] - baseline) / baseline * 100
            if div >= DIVERGE:
                rejected = (live_low, div)
                live_low = None
        elif live_low and baseline is None:
            # 편집 라벨이 비수치('국내 없음'·'면세 전용급' 등 = 편집 판단)면 라이브가
            # 잡혀도 편집 유지(스토리 모순 방지). 단 라이브가 잡혔다는 사실은 audit 보고.
            audit["editorial_none_live"].append(
                f"{name}: 편집='{fb_dm}'인데 라이브 국내 {man(live_low[0])}({live_low[1]}) 발견 → 편집 검토")
            live_low = None

        if live_low:
            dom_krw, dom_src = live_low
            dom_label = man(dom_krw)
            src = "live"
        elif baseline:
            dom_krw, dom_src = baseline, "baseline"
            dom_label = man(dom_krw)
            src = "baseline"
        else:
            dom_krw, dom_src = None, None
            dom_label = fb_dm  # '국내 없음'·'면세 전용급' 등 편집 라벨 유지
            src = "none"

        # 이득 계산 + 배지 (면세 1L 용량당 보정: win은 100ml당으로 판정)
        if duty_krw and dom_krw:
            gain_pb = (duty_krw - dom_krw) / dom_krw * 100          # 병당(표시용)
            duty_p100 = duty_krw / vol * 100
            dom_p100 = dom_krw / 700 * 100                          # 국내 표준 700ml
            gain_v = (duty_p100 - dom_p100) / dom_p100 * 100        # 용량당(판정용)
            win = gain_v < 0
            gain = gain_pb
            # 라벨 '% 더 쌈'은 더 비싼 쪽 대비(편집 관례: 조니워커 −44%=면세가 국내보다 44%↓,
            # 탈리스커 국내 −44%=국내가 면세보다 44%↓).
            if abs(gain_pb) < 3:
                gain_label = "≈ 동가" + ("(용량당 이득)" if win and vol > 700 else "")
            elif gain_pb < 0:                      # 면세가 병당 더 쌈
                gain_label = f"−{(dom_krw - duty_krw) / dom_krw * 100:.0f}%"
            elif win and vol > 700:               # 병당은 국내↓지만 용량당은 면세↓
                gain_label = "용량당 이득"
            else:                                  # 국내가 병당 더 쌈
                gain_label = f"국내 −{(duty_krw - dom_krw) / duty_krw * 100:.0f}%"
        else:
            gain, win, gain_label = None, win0, ""

        entry = {
            "name": name, "group": group,
            "면세": man(duty_krw) if duty_krw else fb_pr,
            "면세_krw": duty_krw, "면세_usd": usd, "면세_vol": vol,
            "국내": dom_label, "국내_krw": dom_krw, "국내_src": dom_src,
            "src": src,
            "홍콩": man(hk_map[code]["hk_krw"]) if code in hk_map else "",
            "홍콩_krw": hk_map[code]["hk_krw"] if code in hk_map else None,
            "이득": gain_label, "이득_pct": round(gain, 1) if gain is not None else None,
            "win": win,
            "baseline_면세": fb_pr, "baseline_국내": fb_dm,
        }
        out[code] = entry

        # audit: 편집 배치 vs 라이브 이득 모순
        if gain is not None:
            if group == "함정" and win:
                audit["flip_win"].append(
                    f"{name}: 함정인데 면세가 {gain:.0f}% 더 쌈 (재분류 검토)")
            elif group in ("국내파", "취향파", "선물파") and not win and win0:
                audit["flip_trap"].append(
                    f"{name}: {group}인데 국내가 더 쌈(+{gain:.0f}%) (함정 검토)")
        if src == "none" and group != "함정":
            audit["no_domestic"].append(f"{name} ({fb_dm})")
        if rejected:
            (rlow, rsrc), rdiv = rejected
            audit["diverge"].append(
                f"{name}: 라이브 {man(rlow)}({rsrc})가 baseline {man(baseline)}와 "
                f"{rdiv:.0f}% 차 → 오매칭 의심, baseline 유지")

    meta = {
        "date": date, "generated": time.strftime("%Y-%m-%d %H:%M:%S KST"),
        "fx_usd_krw": round(usd_krw, 2), "fx_asof": fx_asof,
        "picks": len(out), "shilla_csv": os.path.basename(csv_path),
    }
    payload = {"_meta": meta, "prices": out}
    out_path = os.path.join(ROOT, "data", "shilla-dutyfree",
                            f"리포트_가격_{date}.json")
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)

    # 요약 + audit
    print(f"\nJSON -> {out_path} ({len(out)}종, 환율 {usd_krw:,.2f})")
    print(f"  데일리샷/DB 라이브 국내 {sum(1 for e in out.values() if e['src']=='live')}종 / "
          f"baseline {sum(1 for e in out.values() if e['src']=='baseline')} / "
          f"국내없음 {sum(1 for e in out.values() if e['src']=='none')}")
    print(f"  홍콩 매칭 {sum(1 for e in out.values() if e['홍콩_krw'])}종")
    for key, label in [("flip_trap", "⚠️ 편집=이득이지만 국내가 더 쌈"),
                       ("flip_win", "⚠️ 함정인데 면세가 더 쌈"),
                       ("diverge", "⚠️ 라이브 국내가 baseline과 ≥35% 차 → 거부(오매칭 의심)"),
                       ("editorial_none_live", "ℹ️ 편집='국내 없음'인데 라이브 발견(편집 검토)"),
                       ("no_domestic", "ℹ️ 국내 최저 미확인(편집 라벨 유지)"),
                       ("no_code", "ℹ️ 코드 없음/미존재(하드코딩 폴백)")]:
        if audit[key]:
            print(f"\n  {label} ({len(audit[key])}):")
            for x in audit[key]:
                print(f"    - {x}")


if __name__ == "__main__":
    main()
