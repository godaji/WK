#!/usr/bin/env python3
"""신라면세 위스키 가격변동(달러기준) 감지기 — CMPA-168.

정본 디렉터리에서 날짜 패턴 스냅샷을 자동 탐지하여 **최신 + 직전** 두 개를
고른 뒤, `상품코드` 기준으로 조인해 **달러기준** 변동을 분류한다:

  ① 할인가_USD 상승/하락
  ② 할인율_%(%포인트) 변동
  ③ 신규 상품 (직전엔 없고 최신에만 있음)
  ④ 삭제 상품 (직전엔 있었으나 최신에서 사라짐)

조인 키 = `상품코드` (런 간 매칭 표준키, refresh_report_prices.py와 동일).
가격은 이미 USD이므로 FX 환산 불필요.

산출물 md:
  reports/shilla-dutyfree/가격변동_<직전날짜>_to_<최신날짜>.md
  - 상단에 두 스냅샷의 수집 날짜를 반드시 명시 (데이터 3원칙 ③).
  - 요약 카운트 + 변동폭 큰 순 정렬 표.

데이터 3원칙 준수:
  ① 가져오기: 직전 정본 스냅샷을 불러와 비교(백지 시작 아님).
  ② 항목단위: 날짜별 스냅샷은 보존(이 도구는 읽기 전용, 덮어쓰지 않음).
  ③ 수집날짜 메타: 리포트에 양쪽 수집일 노출.

사용법:
  python3 pipelines/shilla_dutyfree/detect_price_changes.py
  python3 pipelines/shilla_dutyfree/detect_price_changes.py --latest 2026-06-07 --prev 2026-06-06
"""
import argparse
import csv
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA_DIR = os.path.join(ROOT, "data", "shilla-dutyfree")
REPORT_DIR = os.path.join(ROOT, "reports", "shilla-dutyfree")

FNAME_RE = re.compile(r"^신라면세_위스키_(\d{4}-\d{2}-\d{2})\.csv$")

# 변동으로 간주할 최소 임계값 (부동소수점 노이즈 / 사소한 반올림 무시).
PRICE_EPS = 0.01   # USD
RATE_EPS = 0.01    # %포인트


def discover_snapshots():
    """정본 디렉터리에서 날짜 패턴 위스키 스냅샷을 날짜 오름차순으로 반환."""
    dates = []
    for fn in os.listdir(DATA_DIR):
        m = FNAME_RE.match(fn)
        if m:
            dates.append(m.group(1))
    return sorted(dates)


def load_snapshot(date):
    """상품코드 -> row dict 로 적재."""
    path = os.path.join(DATA_DIR, f"신라면세_위스키_{date}.csv")
    rows = {}
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            code = (r.get("상품코드") or "").strip()
            if code:
                rows[code] = r
    return rows


def to_float(v):
    try:
        if v is None or str(v).strip() == "":
            return None
        return float(v)
    except (ValueError, TypeError):
        return None


def classify(prev, latest):
    """변동 분류. dict 반환: price_changes, rate_only, new, removed."""
    prev_codes = set(prev)
    latest_codes = set(latest)

    new_codes = latest_codes - prev_codes
    removed_codes = prev_codes - latest_codes
    common = prev_codes & latest_codes

    price_changes = []   # 할인가_USD 변동 (할인율 동반 변동 포함)
    rate_only = []       # 할인가는 동일하나 할인율만 변동

    for code in common:
        p, l = prev[code], latest[code]
        # 표시가_USD = 신라 앱/웹 표시가 (마일리지 할인가). 구버전 CSV 폴백
        p_price = to_float(p.get("표시가_USD") or p.get("할인가_USD"))
        l_price = to_float(l.get("표시가_USD") or l.get("할인가_USD"))
        p_rate = to_float(p.get("마일리지할인율_%") or p.get("할인율_%"))
        l_rate = to_float(l.get("마일리지할인율_%") or l.get("할인율_%"))

        d_price = None
        if p_price is not None and l_price is not None:
            d_price = l_price - p_price
        d_rate = None
        if p_rate is not None and l_rate is not None:
            d_rate = l_rate - p_rate

        price_moved = d_price is not None and abs(d_price) >= PRICE_EPS
        rate_moved = d_rate is not None and abs(d_rate) >= RATE_EPS

        rec = {
            "code": code,
            "name": l.get("위스키명") or p.get("위스키명") or "",
            "url": l.get("상품URL") or p.get("상품URL") or "",
            "p_price": p_price, "l_price": l_price, "d_price": d_price,
            "p_rate": p_rate, "l_rate": l_rate, "d_rate": d_rate,
        }
        if price_moved:
            price_changes.append(rec)
        elif rate_moved:
            rate_only.append(rec)

    # 변동폭 큰 순 (절대 USD 변동 기준; rate_only 는 %p 기준)
    price_changes.sort(key=lambda r: abs(r["d_price"]), reverse=True)
    rate_only.sort(key=lambda r: abs(r["d_rate"] or 0), reverse=True)

    new_items = sorted(
        ({"code": c, "name": latest[c].get("위스키명", ""),
          "price": to_float(latest[c].get("표시가_USD") or latest[c].get("할인가_USD")),
          "rate": to_float(latest[c].get("마일리지할인율_%") or latest[c].get("할인율_%")),
          "url": latest[c].get("상품URL", "")} for c in new_codes),
        key=lambda r: (r["price"] is None, r["price"] or 0), reverse=True)
    removed_items = sorted(
        ({"code": c, "name": prev[c].get("위스키명", ""),
          "price": to_float(prev[c].get("표시가_USD") or prev[c].get("할인가_USD")),
          "rate": to_float(prev[c].get("마일리지할인율_%") or prev[c].get("할인율_%")),
          "url": prev[c].get("상품URL", "")} for c in removed_codes),
        key=lambda r: (r["price"] is None, r["price"] or 0), reverse=True)

    return {
        "price_changes": price_changes,
        "rate_only": rate_only,
        "new": new_items,
        "removed": removed_items,
    }


FX_JSON = os.path.join(ROOT, "data", "whisky-prices", "fx", "fx_latest.json")
FX_DIR = os.path.dirname(FX_JSON)


def _kst_today():
    import datetime
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")


def _read_fx_latest():
    """기존 fx_latest.json 만 읽기(폴백). (rate, asof) | (None, None)."""
    import json
    try:
        fx = json.load(open(FX_JSON, encoding="utf-8"))
        return fx["raw_usd"]["KRW"], fx.get("asof")
    except Exception:
        return None, None


def _import_fx_fetch():
    """공용 FX 모듈(pipelines/common/fx_fetch.py) 임포트. 실패 시 None."""
    common = os.path.join(ROOT, "pipelines", "common")
    if common not in sys.path:
        sys.path.insert(0, common)
    try:
        import fx_fetch
        return fx_fetch
    except Exception:
        return None


def load_fx_krw(max_age_days=1, allow_live=True):
    """현재 USD→KRW 환율 + 기준일 — **라이브 신선도 보장**(CMPA-249/250/251).

    보드 지시: 리포트의 환율은 최신이어야 한다. 신라 면세가는 USD×fx 로 KRW 환산하므로
    동일 적용. 우선순위:
      1) 공용 헬퍼 `fx_fetch.ensure_fresh()`(CMPA-251) 가 있으면 그것을 사용
         — 인터페이스: ensure_fresh(currencies, max_age_days, write) -> snapshot dict
           (raw_usd[KRW], asof, fresh, warning 키 포함).  CEO 정본통합 때 합류.
      2) 헬퍼 미존재(아직 미통합) → 인터페이스 호환 폴백: 라이브 fetch 시도 후
         asof 신선도 검증. 라이브 실패 시 **하드코딩/stale 을 조용히 쓰지 않고**
         기존 fx_latest.json 을 폴백으로 쓰되 명시 경고.
    반환: (rate, asof, fresh, warning).  데이터 3원칙(CMPA-156): asof 항상 노출."""
    fx = _import_fx_fetch()
    today = _kst_today()

    # 1) 공용 헬퍼 우선(CMPA-251).
    if fx is not None and hasattr(fx, "ensure_fresh"):
        try:
            snap = fx.ensure_fresh(currencies=["KRW"], max_age_days=max_age_days,
                                   write=allow_live)
            rate = (snap.get("raw_usd") or {}).get("KRW")
            return rate, snap.get("asof"), bool(snap.get("fresh")), snap.get("warning")
        except Exception as e:
            # 헬퍼가 있으나 실패 → 폴백으로 진행(경고).
            rate, asof = _read_fx_latest()
            return rate, asof, False, f"ensure_fresh 실패({e}) → fx_latest 폴백(asof {asof})"

    # 2) 헬퍼 미존재 → 인터페이스 호환 폴백(라이브 fetch 시도 + asof 검증).
    if allow_live and fx is not None:
        try:
            snap = fx.fx_snapshot(["KRW"])          # 라이브 fetch(open.er-api.com)
            fx.write_snapshot(snap, FX_DIR)         # fx_latest.json 갱신
            rate = (snap.get("raw_usd") or {}).get("KRW")
            asof = snap.get("asof")
            fresh = bool(asof) and asof >= today    # 오늘(또는 그 이후)이면 신선
            warn = None if fresh else (
                f"FX asof {asof} 가 오늘({today})보다 과거 — 소스 미갱신(라이브 fetch 성공)")
            return rate, asof, fresh, warn
        except Exception as e:
            rate, asof = _read_fx_latest()
            warn = (f"라이브 FX fetch 실패({e}) → fx_latest.json 폴백 사용(asof {asof}). "
                    f"환율이 stale 일 수 있음 — 리포트 메타의 수집일 확인.")
            return rate, asof, False, warn

    # 3) 라이브 비활성/모듈 없음 → 기존 스냅샷 + stale 여부 경고.
    rate, asof = _read_fx_latest()
    fresh = bool(asof) and asof >= today
    warn = None if fresh else f"FX 라이브 갱신 생략 — fx_latest.json(asof {asof}) 사용(stale 가능)."
    return rate, asof, fresh, warn


# 인디펜던트 보틀러 / 싱글캐스크 = 국내 동일제품이 없음 → 데일리샷 근사매칭 시
# 엉뚱한 다른 제품가가 붙어 오해를 부른다. 이런 이름은 조회 자체를 건너뛰고 비운다.
INDIE_MARKERS = ("시그나토리", "고든앤맥페일", "더글라스랭", "하트브라더스",
                 "베리브라더스", "아델피", "엘릭서", "캐덴헤드", "더치프타인")


def _exact_matchable(name):
    """브랜드+숙성 근사매칭이 신뢰 가능한 이름인지(인디/싱글캐스크 배제)."""
    nn = (name or "").replace(" ", "")
    if re.search(r"#\s*\d", name or ""):   # 캐스크 넘버 = 싱글캐스크
        return False
    return not any(m in nn for m in INDIE_MARKERS)


# 숙성년수 토큰(예 '12년') — 픽과 DB 표준명의 연식이 다르면 다른 SKU(CLAUDE.md/CMPA-177).
_AGE_RE = re.compile(r"(\d+)\s*년")


def _ages(s):
    return set(_AGE_RE.findall(s or ""))


def _build_dom_index():
    """normalized DB floor 인덱스 [(canon_norm, low_krw, name, channels)].

    소스 = data/whisky-prices/normalized/normalized_prices.csv (오프라인 로컬 파일).
    마트(트레이더스·코스트코·이마트·롯데) + 데일리샷(KR-DS) 통합 국내 최저가.
    refresh_report_prices.build_dom_index 와 동일 로직(에 동봉, 신라 본편 리포트와 일관).
    """
    from analyze_attractiveness import load_domestic, norm as _anorm  # noqa
    idx = []
    for _cid, d in load_domestic().items():
        idx.append((_anorm(d["name"]), round(d["low"]), d["name"],
                    "·".join(sorted(d["ch"]))))
    return idx


def _db_floor(name, idx):
    """픽 이름 → DB 최저가 (price, channels). canonical 정규화 부분일치 + 가드.

    가드: ① EDITION_KW(셰리/포트/CS/에디션…) 비대칭 제외 ② 숙성년수 비대칭 제외
    (제임슨↔제임슨18년 류 가짜딜 차단, CMPA-177) ③ 최단 매치 채택.
    """
    from analyze_attractiveness import norm as _anorm, EDITION_KW  # noqa
    pn = _anorm(name)
    pa = _ages(name)
    best = None
    for cn, low, cname, ch in idx:
        if not cn or cn not in pn:
            continue
        if any(kw in pn and kw not in cn for kw in EDITION_KW):
            continue
        if _ages(cname) != pa:  # 연식 토큰 비대칭 = 다른 제품
            continue
        extra = len(pn) - len(cn)
        if best is None or extra < best[0]:
            best = (extra, low, ch)
    return (best[1], best[2]) if best else None


def build_dailyshot_lookup(names, enabled=True):
    """변동 상품들의 **국내최저가**(KRW) + 데일리샷 링크를 조회.
    {name: {"floor": price|None, "url": ds_url|None}}.

    국내최저 = min( 데일리샷 라이브[면세·해외 제외] , normalized DB floor[트레이더스·
    코스트코·이마트·데일리샷] ) — 신라 본편 리포트(refresh_report_prices)와 동일 정의.
    보드 CMPA-334: 가격변동 패치도 데일리샷 단독이 아니라 3소스 통합 국내최저와 비교.
    보드 CMPA-334(추가): 독자가 데일리샷 최저가를 직접 확인하도록 데일리샷 제품
    페이지(전국 가격비교) 링크를 함께 단다. 링크는 데일리샷 매칭이 있을 때만(마트가
    floor 라도 데일리샷 가격비교 페이지는 유효한 검증 링크).

    네트워크/매칭 실패는 전부 흡수(없으면 비움) — 리포트 생성은 절대 막지 않는다.
    인디펜던트/싱글캐스크 이름은 오매칭 방지를 위해 조회 생략(빈 칸).
    """
    if not enabled or not names:
        return {}
    matchable = [n for n in dict.fromkeys(names) if _exact_matchable(n)]
    if not matchable:
        return {}
    # 1) 데일리샷 라이브 (가격 + 제품 페이지 URL)
    ds = {}
    try:
        import enrich_dailyshot  # 같은 디렉터리(스크립트 실행 시 sys.path 포함)
        res = enrich_dailyshot.build_lookup(matchable)
        ds = {nm: m for nm, m in res.items() if m}
    except Exception as e:
        print(f"[데일리샷 조회 생략: {e}]")
    # 2) DB floor (마트·코스트코·트레이더스 + 데일리샷) — 오프라인 정규화 DB
    dom_idx = []
    try:
        dom_idx = _build_dom_index()
    except Exception as e:
        print(f"[DB floor 로드 생략: {e}]")
    # 3) 통합: min(데일리샷, DB floor) + 데일리샷 링크
    out = {}
    for nm in matchable:
        cands = []
        m = ds.get(nm)
        if m and m.get("ds_price"):
            cands.append(m["ds_price"])
        f = _db_floor(nm, dom_idx) if dom_idx else None
        if f:
            cands.append(f[0])
        out[nm] = {"floor": (min(cands) if cands else None),
                   "url": (m.get("ds_url") if m else None)}
    return out


def fmt_usd(v):
    return f"${v:,.2f}" if v is not None else "—"


def fmt_ds(name, ds_lookup):
    """국내최저가(KRW, 데일리샷·트레이더스·코스트코 통합) + 데일리샷 가격비교 링크.
    없으면 빈 칸. 링크는 데일리샷 매칭이 있을 때만 ' [🔗데일리샷](url)' 부착."""
    e = (ds_lookup or {}).get(name) or {}
    v, url = e.get("floor"), e.get("url")
    if not v:
        return ""
    base = f"₩{v:,.0f}"
    return f"{base} [🔗데일리샷]({url})" if url else base


def fmt_krw(usd, rate):
    """현재 USD × 현재 환율 = 현재 KRW (원 단위 반올림)."""
    if usd is None or rate is None:
        return "—"
    return f"₩{usd * rate:,.0f}"


def fmt_rate(v):
    return f"{v:.1f}%" if v is not None else "—"


def fmt_signed_usd(v):
    if v is None:
        return "—"
    sign = "+" if v > 0 else ("−" if v < 0 else "")
    return f"{sign}${abs(v):,.2f}"


def fmt_signed_rate(v):
    if v is None:
        return "—"
    sign = "+" if v > 0 else ("−" if v < 0 else "")
    return f"{sign}{abs(v):.1f}%p"


def build_md(prev_date, latest_date, prev, latest, result,
             krw_rate=None, fx_asof=None, ds_lookup=None,
             fx_fresh=True, fx_warning=None):
    pc, ro = result["price_changes"], result["rate_only"]
    new, removed = result["new"], result["removed"]
    up = sum(1 for r in pc if r["d_price"] > 0)
    down = sum(1 for r in pc if r["d_price"] < 0)

    L = []
    L.append("# 신라면세 위스키 가격변동 리포트 (달러기준)")
    L.append("")
    L.append(f"- **직전 스냅샷 수집일:** {prev_date} (위스키 {len(prev)}종)")
    L.append(f"- **최신 스냅샷 수집일:** {latest_date} (위스키 {len(latest)}종)")
    if krw_rate is not None:
        # CMPA-249/251: 환율은 라이브 신선도 보장. asof(수집일) 노출 + stale 경고.
        stale = "" if fx_fresh else " ⚠️ (환율 미갱신·stale 가능)"
        L.append(f"- **현재 환율(USD→KRW):** ₩{krw_rate:,.2f}"
                 + (f" (기준일 {fx_asof})" if fx_asof else "") + stale)
    L.append(f"- **조인 키:** 상품코드 · **가격 기준:** USD · 현재 KRW = 현재 USD × 현재 환율")
    L.append("")
    L.append("> 수집 날짜는 데이터 신뢰성의 1차 신호입니다. 아래 가격은 "
             f"각 스냅샷 **수집일 기준값**이며, 변동은 두 수집일 사이의 차이입니다.")
    L.append("")
    L.append("## 요약")
    L.append("")
    L.append(f"- 가격(할인가_USD) 변동: **{len(pc)}건** (상승 {up} · 하락 {down})")
    L.append(f"- 할인율만 변동(가격 동일): **{len(ro)}건**")
    L.append(f"- 신규 상품: **{len(new)}건**")
    L.append(f"- 삭제(사라진) 상품: **{len(removed)}건**")
    L.append("")

    L.append("## 가격(할인가_USD) 변동 — 변동폭 큰 순")
    L.append("")
    if pc:
        L.append("| 위스키명 | 현재 USD | 현재 할인율 | 직전 할인율 | 현재 KRW | 국내최저가 |")
        L.append("|---|---:|---:|---:|---:|---:|")
        for r in pc:
            L.append(f"| {r['name']} | {fmt_usd(r['l_price'])} | "
                     f"{fmt_rate(r['l_rate'])} | {fmt_rate(r['p_rate'])} | "
                     f"{fmt_krw(r['l_price'], krw_rate)} | "
                     f"{fmt_ds(r['name'], ds_lookup)} |")
    else:
        L.append("_변동 없음._")
    L.append("")

    L.append("## 할인율만 변동 (할인가_USD 동일) — 변동폭 큰 순")
    L.append("")
    if ro:
        L.append("| 위스키명 | 현재 USD | 현재 할인율 | 직전 할인율 | 현재 KRW | 국내최저가 |")
        L.append("|---|---:|---:|---:|---:|---:|")
        for r in ro:
            L.append(f"| {r['name']} | {fmt_usd(r['l_price'])} | "
                     f"{fmt_rate(r['l_rate'])} | {fmt_rate(r['p_rate'])} | "
                     f"{fmt_krw(r['l_price'], krw_rate)} | "
                     f"{fmt_ds(r['name'], ds_lookup)} |")
    else:
        L.append("_변동 없음._")
    L.append("")

    L.append(f"## 신규 상품 ({len(new)}건) — 가격 높은 순")
    L.append("")
    if new:
        L.append("| 위스키명 | 현재 USD | 현재 할인율 | 현재 KRW |")
        L.append("|---|---:|---:|---:|")
        for r in new:
            L.append(f"| {r['name']} | {fmt_usd(r['price'])} | "
                     f"{fmt_rate(r['rate'])} | {fmt_krw(r['price'], krw_rate)} |")
    else:
        L.append("_없음._")
    L.append("")

    L.append(f"## 삭제(사라진) 상품 ({len(removed)}건) — 가격 높은 순")
    L.append("")
    if removed:
        L.append("| 위스키명 | 직전 USD | 직전 할인율 | 직전 KRW |")
        L.append("|---|---:|---:|---:|")
        for r in removed:
            L.append(f"| {r['name']} | {fmt_usd(r['price'])} | "
                     f"{fmt_rate(r['rate'])} | {fmt_krw(r['price'], krw_rate)} |")
    else:
        L.append("_없음._")
    L.append("")

    # 추가 정보 — 변동/신규/삭제된 술의 스토리·도수·맛 (CMPA-179 보드 지시).
    # 표 아래에 리포트처럼 덧붙인다. 보강 데이터(whisky-story.csv)에서 조회.
    story_names = ([r["name"] for r in pc] + [r["name"] for r in ro]
                   + [r["name"] for r in new] + [r["name"] for r in removed])
    if story_names:
        try:
            import whisky_story
            L.append(whisky_story.render_story_section(story_names))
        except Exception as e:
            L.append(f"_스토리 보강 섹션 생략: {e}_")
            L.append("")

    L.append(f"---")
    L.append("_국내최저가 = 데일리샷·트레이더스·코스트코 국내 소매가 중 최저(면세·해외 제외) "
             "브랜드+숙성 근사매칭 · 매칭 실패/인디·싱글캐스크는 비움._")
    L.append(f"_생성: detect_price_changes.py (CMPA-168) · "
             f"{prev_date} → {latest_date}_")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--latest", help="최신 스냅샷 날짜 (기본: 자동 탐지)")
    ap.add_argument("--prev", help="직전 스냅샷 날짜 (기본: 자동 탐지)")
    ap.add_argument("--out", help="md 출력 경로 (기본: 자동)")
    ap.add_argument("--no-dailyshot", action="store_true",
                    help="데일리샷 국내 최저가 실시간 조회 생략(오프라인)")
    ap.add_argument("--no-live-fx", action="store_true",
                    help="환율 라이브 fetch 생략 — 기존 fx_latest.json 사용(오프라인). "
                         "stale 면 경고+메타 노출(CMPA-251).")
    args = ap.parse_args()

    if args.latest and args.prev:
        latest_date, prev_date = args.latest, args.prev
    else:
        snaps = discover_snapshots()
        if len(snaps) < 2:
            raise SystemExit(
                f"비교할 스냅샷이 부족합니다 (발견 {len(snaps)}개). "
                "최소 2개의 신라면세_위스키_<날짜>.csv 가 필요합니다.")
        latest_date, prev_date = snaps[-1], snaps[-2]

    print(f"직전 {prev_date}  →  최신 {latest_date}")
    prev = load_snapshot(prev_date)
    latest = load_snapshot(latest_date)
    result = classify(prev, latest)

    krw_rate, fx_asof, fx_fresh, fx_warning = load_fx_krw(allow_live=not args.no_live_fx)
    if fx_warning:
        print(f"[FX 경고] {fx_warning}", file=sys.stderr)
    print(f"환율 USD→KRW ₩{krw_rate} (기준일 {fx_asof}, "
          f"{'신선' if fx_fresh else 'stale 가능'})")
    change_names = ([r["name"] for r in result["price_changes"]]
                    + [r["name"] for r in result["rate_only"]])
    ds_lookup = build_dailyshot_lookup(change_names, enabled=not args.no_dailyshot)
    md = build_md(prev_date, latest_date, prev, latest, result,
                  krw_rate=krw_rate, fx_asof=fx_asof, ds_lookup=ds_lookup,
                  fx_fresh=fx_fresh, fx_warning=fx_warning)
    os.makedirs(REPORT_DIR, exist_ok=True)
    out = args.out or os.path.join(
        REPORT_DIR, f"가격변동_{prev_date}_to_{latest_date}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)

    r = result
    print(f"가격변동 {len(r['price_changes'])}건 · 할인율만 {len(r['rate_only'])}건 · "
          f"신규 {len(r['new'])}건 · 삭제 {len(r['removed'])}건")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
