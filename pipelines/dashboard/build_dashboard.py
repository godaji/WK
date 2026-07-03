#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_dashboard.py — 위스키 가격 대시보드 '초안 HTML' 생성기 (CMPA-507 / 부모 CMPA-505).

사람들이 항상 들어와서 '현재 상태'를 볼 수 있는 위스키 가격 대시보드 1장을 만든다.
**이번 단계는 보드 지시대로 초안 HTML 1장**(라우틴 자동연결·라이브 발행은 2단계, 이번 범위 아님).

설계 원칙
  · 하드코딩 HTML 금지 — 기존 **정본 데이터 아티팩트**를 읽어 자기완결(self-contained) HTML 산출.
  · 새 floor/매칭 로직을 만들지 않는다 — 검증된 정본 헬퍼를 그대로 재사용한다:
      - 소매최저가(floor)   = run_ocr_collection._domestic_floor_lookup
                              (= normalized_prices + common.source_floor.per_source_latest_floor,
                               CMPA-496/500: 소스별 최신가 중 최소값. 기간 단순 min() 금지)
      - floor 출처 라벨      = run_ocr_collection._floor_source_label (데일리샷 vs 물리매장 구분)
      - 면세최저가/매칭      = run_ocr_collection._dutyfree_lookup + _match_dutyfree
                              (CMPA-492 분석기 가드 재사용 — 같은 용량·표준판만, USD→KRW)
      - 소매 변동           = pipelines.dailyshot.detect_dailyshot_changes (🔻 핫딜)
      - 면세 변동           = pipelines.shilla_dutyfree.detect_price_changes
      - 해외 비교           = normalized_prices 의 HK/JP 현지가(같은 canonical_id 조인)
      - 유형/메타           = assets/master-sku.csv

표 컬럼(보드 명세)
  위스키 이름 | 소매최저가 | 면세최저가 | 소매 최근 가격변동 | 면세 최근 가격변동 | 유형

행 라벨/뱃지
  🔥 최근 핫딜  — 소매(데일리샷) 최근 가격하락(detect_dailyshot_changes 🔻, 임계 통과분).
                  '최근' = 최신 스냅샷 vs **직전 영업일** 스냅샷(전일 대비). 인트라데이 잡음 대신
                  하루 단위 핫딜을 본다.
  🇭🇰↓        — 홍콩 현지가가 국내최저보다 쌀 때(해외 비교, 표준용량 ≤750ml만).
  🇯🇵↓        — 일본 현지가가 국내최저보다 쌀 때(해외 비교, 표준용량 ≤750ml만).
  🆕 new       — 해당 품목이 '가장 최근 수집일(최신 런)'에 갱신된 경우(아래 NEW 판정 참고).

하단: 데이터 수집 로그 요약(소스별 마지막 수집일·품목 수·상태).

CLAUDE.md 필수 준수
  · 모바일 우선(CMPA-255): 360~390px 글 안 잘림. 반응형 테이블(data-label) — 데스크톱은 6컬럼,
    좁은 화면은 행이 카드로 접힘(가로 스크롤/숨김 없음).
  · 수집 날짜 메타(CMPA-156): 각 가격에 수집일 표기, 상단 '📅 기준일'. stale 단정 금지.
  · 면세/해외 제외(CMPA-321): 소매 floor 에 면세·해외 섞지 않음(헬퍼가 KR/KR-DS 만 사용).
  · 카피 담백(CMPA-197)·저자 CaskCode(CMPA-198) — 단, 이건 초안이라 발행 전(noindex).

멱등: 같은 입력 → 같은 출력(시각 등 비결정 값은 입력 데이터의 수집일만 사용).

용법:
  python3 pipelines/dashboard/build_dashboard.py            # deploy/dashboard/index.html 생성
  python3 pipelines/dashboard/build_dashboard.py --out /tmp/x.html
"""
import argparse
import csv
import glob
import html
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

# 정본 헬퍼 재사용 (새 로직 만들지 않음)
from pipelines.youtube_traders.frame_ocr import run_ocr_collection as roc  # noqa: E402

DATA = os.path.join(ROOT, "data", "whisky-prices")
NORM = os.path.join(DATA, "normalized", "normalized_prices.csv")
DS_LISTINGS = os.path.join(DATA, "*_dailyshot_listings.csv")  # 데일리샷 셀러별 동반 데이터(위치 포함)
MASTER_SKU = os.path.join(ROOT, "assets", "master-sku.csv")
OUT_DEFAULT = os.path.join(ROOT, "deploy", "dashboard", "index.html")
DATA_DASH = os.path.join(ROOT, "data", "dashboard")   # 데이터 스냅샷(누적) 저장소

STD_VOLS = {"", "700", "750", "700.0", "750.0", None}  # 표준판 용량(해외 비교용)


# ---------------------------------------------------------------------------
# 입력 로더
# ---------------------------------------------------------------------------
def load_master_sku():
    """canonical_id -> {name, category, brand}."""
    out = {}
    try:
        with open(MASTER_SKU, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                cid = (r.get("canonical_id") or "").strip()
                if cid:
                    out[cid] = {
                        "name": (r.get("name_ko") or "").strip(),
                        "category": (r.get("category") or "").strip(),
                        "brand": (r.get("brand") or "").strip(),
                    }
    except FileNotFoundError:
        pass
    return out


def load_normalized():
    """normalized_prices 전체 행(list of dict)."""
    try:
        with open(NORM, encoding="utf-8-sig") as f:
            return list(csv.DictReader(f))
    except FileNotFoundError:
        return []


def load_shilla_aliases():
    """whisky-aliases.csv 에서 Shilla raw_name → canonical_id (matched 행만).
    substring 매칭 전 alias override 용 — 이름이 달라 substring 으로 못 찾는 경우
    (예: '조니워커 아일랜드 그린 1000ml' → w042 '조니워커 그린라벨 15년') 를 처리.
    status='shilla_exclude' 행은 신라 제품명 → 매칭 차단 (다른 용량 선호 등).
    Returns (aliases_dict, excluded_set)."""
    p = os.path.join(ROOT, "assets", "whisky-aliases.csv")
    out = {}
    excluded = set()
    try:
        with open(p, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                status = (r.get("status") or "").strip()
                raw = (r.get("raw_name") or "").strip()
                if not raw:
                    continue
                if status == "shilla_exclude":
                    excluded.add(raw)
                elif status == "matched":
                    cid = (r.get("canonical_id") or "").strip()
                    if cid:
                        out[raw] = cid
    except FileNotFoundError:
        pass
    return out, excluded


def _augment_shilla_with_spirits(whisky_rows, aa):
    """신라면세_위스키_*.csv(카테고리 1200) 누락분을 주류전체 CSV로 보완.

    신라는 버번 등을 스피릿(1226)으로 분류해 위스키 CSV에 빠짐(예: 1792 스몰배치).
    주류전체 CSV 의 SKU 중 위스키 CSV 에 없는 것만 추가 — canonical 매칭이 안 되면
    어차피 표에 안 나타나므로 비위스키 항목이 섞여도 안전하다.
    """
    existing_skus = {r.get("SKU", "") or r.get("상품코드", "") for r in whisky_rows}
    files = sorted(glob.glob(os.path.join(ROOT, "data", "shilla-dutyfree",
                                          "신라면세_주류전체_*.csv")))
    if not files:
        return whisky_rows
    extra = []
    with open(files[-1], encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            sku = r.get("SKU", "") or r.get("상품코드", "")
            if sku in existing_skus:
                continue
            r["_norm"] = aa.norm(r.get("위스키명", ""))
            r["_vol"] = aa.vol_of(r.get("위스키명", "")) or 700
            try:
                # 표시가_USD = 신라 앱/웹 표시가 (마일리지 할인가). 구버전 폴백
                usd_val = r.get("표시가_USD") or r.get("할인가_USD")
                r["_usd"] = float(usd_val)
            except (ValueError, TypeError):
                r["_usd"] = None
            extra.append(r)
    return whisky_rows + extra


def _to_int(v):
    try:
        return int(str(v).replace(",", "").strip())
    except (ValueError, TypeError, AttributeError):
        return None


def partitioned_floor_lookup(max_age_days=40):
    """소매 floor 를 **물리매장(phys) vs 데일리샷(ds)** 으로 분리 — 대시보드 로컬(CMPA-557).

    보드 요청: 소매최저가 1차값은 실제로 갈 수 있는 물리매장(트레이더스·코스트코)만,
    데일리샷(온라인 마켓 셀러)이 더 싸면 그건 위치와 함께 **보조 속성**으로. 데일리샷 최저
    셀러가 멀어서 못 가는 경우가 많기 때문.

    ⚠️ 공유 헬퍼 ``run_ocr_collection._domestic_floor_lookup`` 의 **기본 동작은 바꾸지 않는다**
    (블로그·신라가 같이 씀). 여기선 같은 입력(normalized_prices)·같은 소스키 규칙(CMPA-496/500)·
    같은 정본 헬퍼(``per_source_latest_floor``)를 재사용하되, 관측을 두 군으로 나눠 각각 floor 를
    낸다. 새 floor/매칭 로직을 신설하지 않는다.

    반환: ``(phys, ds_norm, ds_names)``
      · phys     = cid -> (price, src_key, prev)   물리매장만(source_family != dailyshot)
      · ds_norm  = cid -> (price, src_key, prev)   데일리샷만(``dailyshot/<채널>`` 복합키)
      · ds_names = cid -> set(raw_name)            데일리샷 raw_name(listings 위치 조인용)
    """
    from datetime import datetime, timedelta
    from pipelines.common.source_floor import per_source_latest_floor
    from pipelines.common.dated import kst_today
    try:
        cutoff = (datetime.strptime(kst_today(), "%Y-%m-%d")
                  - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
    except ValueError:
        cutoff = ""
    phys_obs, ds_obs, ds_names = {}, {}, {}
    try:
        with open(NORM, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                cid = (r.get("canonical_id") or "").strip()
                if not cid or (r.get("exclude_reason") or "").strip():
                    continue
                if (r.get("market") or "").strip() not in ("KR", "KR-DS"):
                    continue                              # 국내만(해외 제외·CMPA-321)
                d = (r.get("date") or "").strip()
                if cutoff and d < cutoff:
                    continue                              # 최근만(stale 과거 저가 방지)
                p = _to_int(r.get("price_krw"))
                if p is None or p < 15000:
                    continue                              # 샘플/미니 노이즈
                fam = (r.get("source_family") or "").strip()
                ch = (r.get("channel") or "").strip()
                if fam == "dailyshot":
                    ds_obs.setdefault(cid, []).append((f"dailyshot/{ch or '?'}", d, p))
                    ds_names.setdefault(cid, set()).add((r.get("raw_name") or "").strip())
                else:
                    phys_obs.setdefault(cid, []).append((ch or fam, d, p))
    except FileNotFoundError:
        pass
    phys = {cid: fl for cid, obs in phys_obs.items()
            if (fl := per_source_latest_floor(obs))}
    ds_norm = {cid: fl for cid, obs in ds_obs.items()
               if (fl := per_source_latest_floor(obs))}
    return phys, ds_norm, ds_names


def listings_min_by_name():
    """데일리샷 동반 listings(최신 수집일)에서 **상품명 -> 최저 셀러(가격·셀러명·지역)**.

    normalized 의 데일리샷 floor 는 제품 페이지 '전국 최저 셀러가'(주소 없음)라 **위치를 못
    붙인다**. listings CSV 는 셀러별 행이라 (가격·셀러명·지역)이 일관된 '구매 가능·위치 확인된'
    오퍼다 → 데일리샷 보조표시는 이 listings 최저 셀러로 한다(보드: '어디까지 가야 하는지'를
    봐야 함). 면세점 업종 제외(CMPA-321), 15,000원 미만(미니/샘플) 제외."""
    files = sorted(glob.glob(DS_LISTINGS))
    if not files:
        return {}
    rows = list(csv.DictReader(open(files[-1], encoding="utf-8-sig")))
    maxdate = max(((r.get("수집일") or "").strip() for r in rows), default="")
    out = {}
    for r in rows:
        if (r.get("수집일") or "").strip() != maxdate:
            continue
        if (r.get("업종") or "").strip() == "면세점":
            continue                                      # 면세 제외(CMPA-321)
        nm = (r.get("위스키명") or "").strip()
        p = _to_int(r.get("가격_KRW"))
        if not nm or p is None or p < 15000:
            continue
        cur = out.get(nm)
        if cur is None or p < cur["price"]:
            out[nm] = {"price": p, "seller": (r.get("셀러명") or "").strip(),
                       "region": (r.get("지역") or "").strip()}
    return out


def domestic_latest_dates(rows):
    """canonical_id -> 그 품목의 국내(KR/KR-DS) 최신 수집일. 'NEW' 판정용.
    global_latest = 데이터셋 전체의 최신 국내 수집일. cid 의 최신일 == global_latest 이면 🆕."""
    by_cid = {}
    for r in rows:
        if (r.get("market") or "").strip() not in ("KR", "KR-DS"):
            continue
        if (r.get("exclude_reason") or "").strip():
            continue
        cid = (r.get("canonical_id") or "").strip()
        d = (r.get("date") or "").strip()
        if cid and d:
            if cid not in by_cid or d > by_cid[cid]:
                by_cid[cid] = d
    global_latest = max(by_cid.values()) if by_cid else ""
    return by_cid, global_latest


def _local_price_index(pattern, col):
    """해외 소스 CSV(최신) 술이름 -> 현지가_KRW 최저. col=현지가 컬럼(기준가_KRW)."""
    files = sorted(glob.glob(os.path.join(DATA, pattern)))
    idx = {}
    if not files:
        return idx
    try:
        with open(files[-1], encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                nm = (r.get("술이름") or "").strip()
                p = _to_int(r.get(col))
                if nm and p is not None and (nm not in idx or p < idx[nm]):
                    idx[nm] = p
    except FileNotFoundError:
        pass
    return idx


def overseas_floor(rows):
    """canonical_id -> {'HK': 현지가_krw_min, 'JP': ...}. 표준용량(≤750ml)만(용량 왜곡 방지).

    ⚠️ normalized 의 overseas price_krw 는 **반입추정가**(한국 반입세 cascade 적용)라 거의 항상
    국내가보다 비싸다. 🇭🇰↓/🇯🇵↓ 뱃지는 '현지가가 더 쌀 때'이므로 **현지가(기준가_KRW)** 를
    소스 CSV 에서 직접 가져와 비교한다(canonical_id 매핑은 normalized 의 raw_name 으로 조인)."""
    hk_local = _local_price_index("2026-*_hk_whisky_poc.csv", "기준가_KRW")
    jp_local = _local_price_index(os.path.join("jp", "2026-*_jp_shopify_poc.csv"), "기준가_KRW")
    out = {}
    for r in rows:
        if (r.get("source_family") or "").strip() != "overseas":
            continue
        mk = (r.get("market") or "").strip()
        if mk not in ("HK", "JP"):
            continue
        vol = (r.get("volume_ml") or "").strip()
        if vol not in STD_VOLS:
            continue
        cid = (r.get("canonical_id") or "").strip()
        nm = (r.get("raw_name") or "").strip()
        local = (hk_local if mk == "HK" else jp_local).get(nm)
        if not cid or local is None:
            continue
        slot = out.setdefault(cid, {})
        if mk not in slot or local < slot[mk]:
            slot[mk] = local
    return out


def name_to_cid(rows):
    """국내 raw_name / canonical_name_ko -> canonical_id (소매 변동명 → cid 매핑용).
    공백 제거 키도 함께 넣어 느슨하게 매칭."""
    idx = {}

    def put(name, cid):
        n = (name or "").strip()
        if n and cid:
            idx.setdefault(n, cid)
            idx.setdefault(n.replace(" ", ""), cid)

    for r in rows:
        if (r.get("market") or "").strip() not in ("KR", "KR-DS"):
            continue
        cid = (r.get("canonical_id") or "").strip()
        put(r.get("raw_name"), cid)
        put(r.get("canonical_name_ko"), cid)
    return idx


def lookup_cid(name, idx):
    n = (name or "").strip()
    return idx.get(n) or idx.get(n.replace(" ", ""))


# ---------------------------------------------------------------------------
# 변동 감지 (정본 detect_* 재사용)
# ---------------------------------------------------------------------------
def dailyshot_changes_by_cid(idx):
    """cid -> {'dir','delta','pct'} (전일 대비). 🔻 핫딜(drops)·🔺(rises) 모두. 없으면 {}."""
    out = {}
    try:
        from pipelines.dailyshot import detect_dailyshot_changes as dd
        snaps = dd.discover_snapshots()
        if len(snaps) < 2:
            return out
        latest = snaps[-1]
        latday = latest[0][0]
        prior = [s for s in snaps if s[0][0] < latday]   # 직전 '영업일' 스냅샷(전일 대비)
        prev = prior[-1] if prior else snaps[-2]
        pr = dd.load_csv(prev[2])
        la = dd.load_csv(latest[2])
        drops, rises, _new, _lost = dd.classify(pr, la)
        meta = {"latest": latest[1], "prev": prev[1]}
        for nm, _pp, _cp, delta, pct, *_ in drops:
            cid = lookup_cid(nm, idx)
            if cid and cid not in out:
                out[cid] = {"dir": "down", "delta": delta, "pct": pct, "name": nm}
        for nm, _pp, _cp, delta, pct, *_ in rises:
            cid = lookup_cid(nm, idx)
            if cid and cid not in out:
                out[cid] = {"dir": "up", "delta": delta, "pct": pct, "name": nm}
        out["__meta__"] = meta
    except Exception as e:  # noqa: BLE001 — 초안: 변동 소스 없으면 '해당 없음'
        sys.stderr.write(f"[dailyshot changes] skipped: {e}\n")
    return out


def shilla_changes_by_name():
    """shilla 위스키명 -> {'dir','d_usd','d_rate'} (최신 vs 직전 스냅샷). 없으면 {}.

    ⚠️ 이전 스냅샷에 '표시가_USD' 컬럼이 없으면 (구버전 = 5% 게스트가 포맷) 방법론
    전환에 따른 일괄 허위 변동이 생기므로 비교를 건너뛴다.
    두 스냅샷 모두 '표시가_USD' 컬럼을 보유할 때만 변동을 집계한다."""
    out = {}
    try:
        from pipelines.shilla_dutyfree import detect_price_changes as dp
        snaps = dp.discover_snapshots()
        if len(snaps) < 2:
            return out
        prev_d, latest_d = snaps[-2], snaps[-1]
        prev = dp.load_snapshot(prev_d)
        latest = dp.load_snapshot(latest_d)
        # 구포맷 가드: prev 중 하나라도 표시가_USD 없으면 전환 아티팩트 → 건너뜀
        prev_vals = list(prev.values())
        if prev_vals and not prev_vals[0].get("표시가_USD"):
            sys.stderr.write(
                f"[shilla changes] prev({prev_d}) 구포맷(표시가_USD 없음) — 변동 비교 건너뜀\n"
            )
            out["__meta__"] = {"prev": prev_d, "latest": latest_d, "skipped": True}
            return out
        res = dp.classify(prev, latest)
        for rec in res.get("price_changes", []):
            nm = (rec.get("name") or "").strip()
            d = rec.get("d_price")
            if nm and d is not None and nm not in out:
                out[nm] = {"dir": "down" if d < 0 else "up", "d_usd": d,
                           "d_rate": rec.get("d_rate")}
        # 할인율만 변동(가격 동일)도 포함 — 마일리지 할인율 변화 표시
        for rec in res.get("rate_only", []):
            nm = (rec.get("name") or "").strip()
            if nm and nm not in out:
                out[nm] = {"dir": "rate_change", "d_usd": 0,
                           "d_rate": rec.get("d_rate")}
        out["__meta__"] = {"prev": prev_d, "latest": latest_d}
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[shilla changes] skipped: {e}\n")
    return out


# ---------------------------------------------------------------------------
# 수집 로그 요약
# ---------------------------------------------------------------------------
def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def collection_log(rows):
    """소스별 (라벨, 마지막 수집일, 품목 수, 상태) 리스트."""
    log = []

    # 데일리샷
    m = _read_json(os.path.join(DATA, "_dailyshot_metrics.json"))
    if m:
        log.append(("데일리샷 (소매 온라인)", m.get("collected_date", "—"),
                    m.get("canonical_priced") or m.get("hits") or "—",
                    "성공" if m.get("dutyfree_leak", 0) == 0 else "점검필요"))

    # 유튜브 OCR (트레이더스/코스트코 현장가) — state 파일엔 ts만 → CSV 에서 최신일/건수
    yt_files = sorted(glob.glob(os.path.join(DATA, "*_youtube_ocr.csv")))
    if yt_files:
        latest_d, cnt = "", 0
        for p in yt_files:
            try:
                with open(p, encoding="utf-8-sig") as f:
                    for r in csv.DictReader(f):
                        d = (r.get("가져온날짜") or "").strip()
                        if d and d > latest_d:
                            latest_d = d
            except FileNotFoundError:
                continue
        # 최신일 품목 수
        for p in yt_files:
            try:
                with open(p, encoding="utf-8-sig") as f:
                    cnt += sum(1 for r in csv.DictReader(f)
                               if (r.get("가져온날짜") or "").strip() == latest_d)
            except FileNotFoundError:
                continue
        log.append(("유튜브 OCR (트레이더스 현장가)", latest_d or "—", cnt or "—", "성공"))

    # 신라면세 — "면세 데이터 (신라면세)"로 표시해 수집 로그에서 면세 갱신 여부를 명확히
    sf = sorted(glob.glob(os.path.join(ROOT, "data", "shilla-dutyfree",
                                       "신라면세_위스키_*.csv")))
    if sf:
        mdate = re.search(r"(\d{4})-(\d{2})-(\d{2})", os.path.basename(sf[-1]))
        scnt = 0
        try:
            with open(sf[-1], encoding="utf-8-sig") as f:
                scnt = sum(1 for _ in csv.DictReader(f))
        except FileNotFoundError:
            pass
        if mdate:
            sdate_iso = f"{mdate.group(1)}-{mdate.group(2)}-{mdate.group(3)}"
            sdate_disp = f"{int(mdate.group(2))}/{int(mdate.group(3))}"  # 6/20 형식
        else:
            sdate_iso = sdate_disp = "—"
        log.append(("면세 데이터 (신라면세)", sdate_iso,
                    scnt or "—", f"갱신됨 ({sdate_disp})"))

    # 코스트코 웹
    c = _read_json(os.path.join(DATA, "_costco_web_metrics.json"))
    if c:
        rc = c.get("rows_collected", 0)
        log.append(("코스트코 웹", c.get("collected_date", "—"), rc,
                    "성공" if rc else "stale(0건)"))

    # 이마트 SSG (참고)
    e = _read_json(os.path.join(DATA, "_emart_ssg_metrics.json"))
    if e:
        b = (e.get("stats") or {}).get("bottles", 0)
        log.append(("이마트 SSG (참고)", e.get("collected_date", "—"), b,
                    "성공" if b else "stale"))

    # 해외 HK/JP
    o = _read_json(os.path.join(DATA, "_overseas_last_run.json"))
    if o:
        asof = o.get("asof", "—")
        steps = o.get("steps", {})
        hk = steps.get("hk", {})
        jp = steps.get("jp", {})
        log.append(("해외 홍콩(HK)", asof, hk.get("rows", "—"),
                    "성공" if hk.get("ok") else "실패"))
        log.append(("해외 일본(JP)", asof, jp.get("rows", "—"),
                    "성공" if jp.get("ok") else "실패"))

    return log


# ---------------------------------------------------------------------------
# 행 조립 — 합산 우주 (소매 수집 + 신라면세 역매칭)
# ---------------------------------------------------------------------------
def build_rows():
    """소매 수집 있는 상품 전체 + 신라에만 있는 상품 — 합산 우주(보드 2026-06-19).

    보드 코멘트: "트레이더스나 코스트코에서 수집했는데, 안보여주는 상품이 있게 되는거야?"
    → 소매 floor 있는 모든 상품(트레이더스·코스트코·데일리샷 등)을 먼저 전부 표시하고,
    그 위에 신라면세 역매칭(Shilla→canonical)으로 면세가를 조인한다. 신라에만 있고
    소매 수집이 없는 상품은 별도로 추가(면세가만 있는 행). 소매가·면세가 모두
    100ml당 단가를 함께 표시해 용량이 달라도 공정 비교 가능.
    """
    from pipelines.shilla_dutyfree import analyze_attractiveness as aa

    rows_norm = load_normalized()
    master = load_master_sku()
    # CMPA-557: 소매 floor 를 물리매장(phys) vs 데일리샷(ds) 으로 분리. phys 가 1차값,
    # 데일리샷 최저는 위치(셀러+지역)와 함께 보조. 공유 헬퍼 기본동작 불변(블로그·신라).
    phys, ds_norm, ds_names = partitioned_floor_lookup()
    ds_loc = listings_min_by_name()               # 상품명 -> {price, seller, region}

    def ds_display(cid):
        """데일리샷 표시값: 위치 확인된 listings 최저 셀러 우선, 없으면 normalized floor(위치無).
        ⚠️ listings = search API 가라 페이지 최저가(ds_norm)보다 높을 수 있음 → 더 싼 쪽 가격 사용."""
        best = None
        for nm in ds_names.get(cid, ()):
            v = ds_loc.get(nm)
            if v and (best is None or v["price"] < best["price"]):
                best = v
        dn = ds_norm.get(cid)
        if best is not None:
            # page price(ds_norm)가 search price(listings)보다 싸면 page price 우선
            page_price = dn[0] if dn else None
            actual_price = min(best["price"], page_price) if page_price else best["price"]
            return {"price": actual_price, "seller": best["seller"],
                    "region": best["region"], "located": True}
        if dn:
            return {"price": dn[0], "seller": None, "region": None, "located": False}
        return None

    def primary_of(cid):
        """소매최저가 1차값: 물리매장 우선, 없으면 데일리샷(엣지). (price, src_key, prev, is_ds)|None."""
        if cid in phys:
            p, s, pv = phys[cid]
            return (p, s, pv, False)
        d = ds_display(cid)
        if d:
            return (d["price"], "dailyshot", None, True)
        return None

    cid_latest, global_latest = domestic_latest_dates(rows_norm)
    over = overseas_floor(rows_norm)
    nidx = name_to_cid(rows_norm)
    ds_chg = dailyshot_changes_by_cid(nidx)
    sh_chg = shilla_changes_by_name()
    df = roc._dutyfree_lookup()                   # (canon, shilla, meta) | None

    ds_meta = ds_chg.pop("__meta__", {})
    sh_meta = sh_chg.pop("__meta__", {})

    df_canon, df_shilla, df_meta_d = (df[0], df[1], df[2]) if df else ({}, [], {})
    usd_krw = (df_meta_d or {}).get("usd_krw", 1300)
    dutyfree_meta = df_meta_d or None

    # 위스키 CSV 누락분(스피릿 카테고리 버번 등) 보완 (예: 1792 스몰배치 — CMPA-505 보드)
    if df_shilla:
        df_shilla = _augment_shilla_with_spirits(df_shilla, aa)

    shilla_aliases, shilla_excluded = load_shilla_aliases()  # Shilla raw_name → cid / excluded set
    canon_items = list(df_canon.items())          # [(cid, canon_row), ...] (substring fallback)

    # Step 1: 신라 상품마다 canonical 역매칭 → 면세 dict
    shilla_matched = {}  # cid -> {"df_krw","df_vol","df_sname","df_usd","df_p100"}
    for s in df_shilla:
        if s.get("_usd") is None:
            continue
        dvol = s.get("_vol") or 700
        if dvol < aa.MINI_ML or dvol > aa.MAGNUM_ML:
            continue

        sname = s["위스키명"].strip()
        sn = s["_norm"]

        # shilla_exclude 차단 먼저
        if sname in shilla_excluded:
            continue

        # alias override 먼저
        cid = shilla_aliases.get(sname)
        if not cid:
            best_cid = None
            best_extra = 9999
            for c_id, c in canon_items:
                if not (c.get("_norm") and c["_norm"] in sn):
                    continue
                if any(kw in sn and kw not in c["_norm"] for kw in aa.EDITION_KW):
                    continue
                extra = len(sn) - len(c["_norm"]) - 5
                if extra > aa.EXTRA_TOL:
                    continue
                if extra < best_extra:
                    best_extra = extra
                    best_cid = c_id
            cid = best_cid
        if not cid:
            continue

        krw = round(s["_usd"] * usd_krw)
        df_p100 = krw / dvol * 100

        # 오매칭 백스톱: 소매 floor(1차값) 대비 용량당 단가 2.5배↑면 에디션 비대칭 의심 → 제외
        retail_data = primary_of(cid)
        if retail_data:
            rvol = df_canon.get(cid, {}).get("_vol") or 700
            retail_p100 = retail_data[0] / rvol * 100
            if df_p100 > retail_p100 * 2.5:
                continue

        if cid not in shilla_matched or df_p100 < shilla_matched[cid]["df_p100"]:
            shilla_matched[cid] = {
                "df_krw": krw, "df_vol": dvol, "df_sname": sname,
                "df_usd": s["_usd"], "df_p100": round(df_p100),
                "df_url": s.get("상품URL", ""),
                "df_mrate": s.get("마일리지할인율_%"),  # 신라 표시가 마일리지 할인율
            }

    # Step 2: 행 조립 헬퍼
    def _make_row(cid, dm):
        info = master.get(cid, {})
        canon_meta = df_canon.get(cid, {})
        name = info.get("name") or canon_meta.get("name_ko") or cid
        # 면세 전용 canonical(CMPA-522)은 master-sku.csv 에 없고 whisky-list.csv 에만 있다 →
        # 유형/브랜드를 whisky-list(canon_meta)에서 폴백해 '—' 대신 정상 유형을 표시한다.
        category = info.get("category") or canon_meta.get("category") or "—"
        brand = info.get("brand") or canon_meta.get("brand") or ""
        retail_vol = canon_meta.get("_vol") or 700  # 소매 표준 용량(100ml 단가 산출용)

        # CMPA-557: 1차값 = 물리매장 floor(없으면 데일리샷 엣지). 데일리샷 위치 보조는 아래.
        prim = primary_of(cid)
        dsd = ds_display(cid)
        if prim is not None:
            price, src_key, prev, prim_is_ds = prim
            if prim_is_ds:
                src_label, retail_dir = "데일리샷(온라인)", ""   # 엣지: 물리매장 없음
            else:
                src_label = roc._floor_source_label(src_key)
                retail_dir = ""
                if prev is not None and prev != price:
                    retail_dir = "down" if price < prev else "up"
        else:
            price = src_key = prev = None
            src_label, retail_dir, prim_is_ds = "", "", False

        # 데일리샷 보조줄: 물리매장이 1차일 때 + 데일리샷이 더 싸면 위치와 함께 보조 노출.
        ds2_show = bool(prim is not None and not prim_is_ds
                        and dsd is not None and dsd["price"] < price)

        rc = ds_chg.get(cid)
        sc = sh_chg.get(dm["df_sname"]) if dm else None

        ov = over.get(cid, {})
        hk_cheaper = price is not None and ov.get("HK") is not None and ov["HK"] < price
        jp_cheaper = price is not None and ov.get("JP") is not None and ov["JP"] < price

        # 🆕 판정: retail 최신 수집일 일치 OR Shilla 수집이 retail보다 최신
        _shilla_latest = sh_meta.get("latest", "")
        is_new = bool(global_latest) and (
            cid_latest.get(cid) == global_latest  # 소매가 오늘 갱신됨
            or (dm is not None and bool(_shilla_latest)
                and _shilla_latest >= global_latest)  # 면세가 오늘 갱신됨
        )

        # 면세가 더 싼지 판단 (100ml당 단가 기준) — 하이라이트·win 배지용
        df_p100_val = dm["df_p100"] if dm else None
        retail_p100_val = round(price / retail_vol * 100) if price else None
        df_win = bool(retail_p100_val and df_p100_val and df_p100_val < retail_p100_val)
        # 소매대비면세가 절감율 (%) — 양수=면세 유리, 음수=소매 유리, None=비교불가
        df_savings_pct = None
        if retail_p100_val and df_p100_val:
            df_savings_pct = round((retail_p100_val - df_p100_val) / retail_p100_val * 100, 1)

        return {
            "cid": cid, "name": name, "category": category,
            "brand": brand,
            "retail_price": price, "retail_vol": retail_vol,
            "retail_src": src_label, "retail_src_key": src_key, "retail_prev": prev,
            "retail_date": cid_latest.get(cid, ""), "retail_dir": retail_dir,
            # CMPA-557 데일리샷 보조(위치 포함)
            "primary_is_ds": prim_is_ds,
            "ds2_show": ds2_show,
            "ds2_price": dsd["price"] if dsd else None,
            "ds2_seller": dsd["seller"] if dsd else None,
            "ds2_region": dsd["region"] if dsd else None,
            "ds2_located": dsd["located"] if dsd else False,
            "df_krw": dm["df_krw"] if dm else None,
            "df_sname": dm["df_sname"] if dm else None,
            "df_url": dm["df_url"] if dm else None,
            "df_vol": dm["df_vol"] if dm else None,
            "df_usd": dm["df_usd"] if dm else None,
            "df_per100": dm["df_p100"] if dm else None,
            "df_mrate": dm.get("df_mrate") if dm else None,
            "df_win": df_win,
            "df_savings_pct": df_savings_pct,
            "retail_change": rc, "df_change": sc,
            "hk_cheaper": hk_cheaper, "hk_krw": ov.get("HK"),
            "jp_cheaper": jp_cheaper, "jp_krw": ov.get("JP"),
            "is_new": is_new,
            "hot": bool(rc and rc["dir"] == "down"),
            "_usd_krw": usd_krw,  # 면세 변동 원화 환산용
        }

    rows = []
    seen = set()

    # A. 소매 수집 있는 상품 전부 (물리매장 phys ∪ 데일리샷 ds — 행 우주 동일, 행 손실 없음)
    #     sorted() 로 결정론적 순서 보장(멱등; set 반복순서는 해시시드에 따라 달라짐).
    for cid in sorted(set(phys) | set(ds_norm)):
        seen.add(cid)
        rows.append(_make_row(cid, shilla_matched.get(cid)))

    # B. 신라에만 있고 소매 수집 없는 상품 (면세-only)
    for cid, dm in shilla_matched.items():
        if cid in seen:
            continue
        rows.append(_make_row(cid, dm))

    # 기본 정렬: 소매대비면세가 절감율 내림차순 (면세 이득 큰 것 먼저), 면세매칭 없으면 뒤로
    rows.sort(key=lambda r: (0 if r["df_savings_pct"] is not None else 1,
                             -(r["df_savings_pct"] or 0)))
    meta = {
        "global_latest": global_latest,
        "ds_meta": ds_meta, "sh_meta": sh_meta,
        "dutyfree_meta": dutyfree_meta,
    }
    return rows, meta, collection_log(rows_norm)


# ---------------------------------------------------------------------------
# 데이터 스냅샷 (보드 2026-06-19: '보고서 업데이트마다 메타데이터 풍부한 data snapshot')
# ---------------------------------------------------------------------------
SCHEMA_VERSION = 1


def assemble_snapshot(rows, meta, log):
    """대시보드의 **정본 데이터 레이어**(메타데이터 풍부). HTML 은 이 구조에서 렌더된다.

    설계(보드 2026-06-19): "보고서를 업데이트할 때마다 data snapshot 을 찍자. 그러면 다음번
    수집 데이터를 그 위에 적용해 대시보드를 갱신할 수 있다. 그래서 snapshot 은 메타데이터를
    많이 가져야 한다." → 각 행에 가격뿐 아니라 **출처·수집일·직전가·환율·용량·용량당단가·
    변동 상세·해외 현지가·뱃지 근거**를 모두 담는다. 누적 기록(CMPA-156): basis_date 별로 파일을
    쌓고(같은 날 재실행은 멱등 덮어쓰기), latest 포인터를 둔다.
    """
    basis = meta["global_latest"] or ""
    dfm = meta["dutyfree_meta"] or {}
    fx_over = _read_json(os.path.join(DATA, "fx", "fx_latest.json")) or {}

    out_rows = []
    for r in rows:
        rc, sc = r["retail_change"], r["df_change"]
        out_rows.append({
            "canonical_id": r["cid"],
            "name": r["name"],
            "brand": r.get("brand", ""),
            "category": r["category"],
            "retail": {
                "price_krw": r["retail_price"],
                "source": r["retail_src"],
                "source_key": r["retail_src_key"],
                "collected_date": r["retail_date"],
                "prev_price_krw": r["retail_prev"],
                "direction": r["retail_dir"] or None,
                "primary_is_dailyshot": r.get("primary_is_ds", False),
            },
            # CMPA-557: 데일리샷 보조 속성(위치 포함). 물리매장보다 쌀 때만 secondary=True.
            "dailyshot": None if r.get("ds2_price") is None else {
                "price_krw": r["ds2_price"],
                "seller": r.get("ds2_seller"),
                "region": r.get("ds2_region"),
                "located": r.get("ds2_located", False),
                "cheaper_than_physical": r.get("ds2_show", False),
            },
            "dutyfree": None if r["df_krw"] is None else {
                "price_krw": r["df_krw"],
                "volume_ml": r["df_vol"],
                "per_100ml_krw": r["df_per100"],
                "price_usd": r["df_usd"],
                "mileage_rate_pct": r.get("df_mrate"),  # 신라 마일리지 할인율 (%)
                "shilla_name": r["df_sname"],
                "shilla_url": r.get("df_url") or "",
            },
            "retail_change": None if not rc else {
                "direction": rc["dir"], "delta_krw": rc["delta"],
                "pct": round(rc["pct"], 2), "matched_name": rc.get("name"),
            },
            "dutyfree_change": None if not sc else {
                "direction": sc["dir"], "delta_usd": round(sc["d_usd"], 2),
            },
            "overseas": {
                "hk_local_krw": r["hk_krw"], "jp_local_krw": r["jp_krw"],
                "hk_cheaper": r["hk_cheaper"], "jp_cheaper": r["jp_cheaper"],
            },
            "badges": {
                "hotdeal": r["hot"], "dutyfree_win": r.get("df_win", False),
                "hk_cheaper": r["hk_cheaper"],
                "jp_cheaper": r["jp_cheaper"], "new": r["is_new"],
            },
        })

    sources = [{"key_label": s[0], "last_collected": s[1],
                "items": s[2], "status": s[3]} for s in log]

    return {
        "schema_version": SCHEMA_VERSION,
        "snapshot": {
            "snapshot_id": basis,                    # = basis_date (멱등 키)
            "basis_date": basis,                     # 데이터셋 전체 최신 국내 수집일
            "generator": "pipelines/dashboard/build_dashboard.py",
            "issue": "CMPA-507",
            "note": ("위스키 가격 대시보드 데이터 스냅샷. 가격은 '수집일 기준값'(CMPA-156). "
                     "소매 floor 는 면세·해외 제외(CMPA-321). 신라→canonical 역방향(보드 2026-06-19). "
                     "다음 수집분을 이 위에 적용해 갱신."),
            "fx_dutyfree": {"usd_krw": dfm.get("usd_krw"), "asof": dfm.get("fx_asof"),
                            "shilla_date": dfm.get("sdate")},
            "fx_overseas": {"asof": fx_over.get("asof"),
                            "krw_per": fx_over.get("krw_per")},
            "thresholds": {
                "dailyshot_change_min_krw": 1000,
                "dailyshot_change_min_pct": 1.0,
                "dutyfree_overmatch_per100ml_ratio": 2.5,
                "overseas_std_volumes_ml": ["700", "750"],  # 표준판만(용량 왜곡 방지)
                "retail_floor_min_krw": 15000,
            },
            "methodology": {
                "retail_floor": "run_ocr_collection._domestic_floor_lookup "
                                "(source_floor.per_source_latest_floor: 소스별 최신가 중 최소값)",
                "dutyfree": "신라→canonical 역매칭 (보드 2026-06-19 승인): "
                            "신라면세 위스키 상품마다 canonical _norm substring 역매칭 + "
                            "whisky-aliases.csv override. 신라에 있는 위스키가 행의 우주.",
                "retail_change": "detect_dailyshot_changes (최신 vs 직전 영업일 스냅샷)",
                "dutyfree_change": "detect_price_changes (신라 직전 스냅샷 대비)",
                "overseas": "HK/JP 소스 CSV 현지가(기준가_KRW) ↔ canonical 조인",
                "new_badge": "품목 국내 최신 수집일 == 데이터셋 전체 최신 수집일",
            },
            "counts": {
                "rows": len(rows),
                "retail_matched": sum(1 for r in rows if r["retail_price"] is not None),
                "dutyfree_matched": sum(1 for r in rows if r["df_krw"] is not None),
                "hotdeal": sum(1 for r in rows if r["hot"]),
                "dutyfree_win": sum(1 for r in rows if r.get("df_win")),
                "hk_cheaper": sum(1 for r in rows if r["hk_cheaper"]),
                "jp_cheaper": sum(1 for r in rows if r["jp_cheaper"]),
                "new": sum(1 for r in rows if r["is_new"]),
            },
            "change_windows": {
                "dailyshot": meta.get("ds_meta") or {},
                "shilla": meta.get("sh_meta") or {},
            },
        },
        "sources": sources,
        "rows": out_rows,
    }


def write_snapshot(snap, snap_dir=None):
    """스냅샷을 basis_date 별 파일 + latest 포인터로 기록(누적·멱등). 경로 dict 반환."""
    snap_dir = snap_dir or os.path.join(DATA_DASH, "snapshots")
    os.makedirs(snap_dir, exist_ok=True)
    basis = snap["snapshot"]["basis_date"] or "unknown"
    dated = os.path.join(snap_dir, f"dashboard_snapshot_{basis}.json")
    latest = os.path.join(DATA_DASH, "dashboard_latest.json")
    blob = json.dumps(snap, ensure_ascii=False, indent=2, sort_keys=False)
    for p in (dated, latest):
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(blob)
    return {"dated": dated, "latest": latest}


# ---------------------------------------------------------------------------
# 렌더
# ---------------------------------------------------------------------------
def _won(v):
    return f"{v:,}원" if v is not None else "—"


_PEAT_KW = ["피트", "피티드", "이슬레이", "아드벡", "라프로익", "라가불린", "옥토모어", "킬호만", "포트샬롯", "아일라"]
_SHERRY_KW = ["셰리", "쉐리", "아부나흐"]


def _type_label(category, name):
    """유형 라벨 — 싱글몰트는 피트/쉐리 세분화."""
    if category == "싱글몰트":
        nm = name
        if any(k in nm for k in _PEAT_KW):
            return "싱글몰트(피트)"
        if any(k in nm for k in _SHERRY_KW):
            return "싱글몰트(쉐리)"
        return "싱글몰트"
    return category or "기타"


def _badges(r):
    out = []
    if r.get("df_win"):
        rp = round(r["retail_price"] / r["retail_vol"] * 100)
        dp = r["df_per100"]
        save_pct = round((rp - dp) / rp * 100)
        out.append(f'<span class="bdg win" title="면세 100ml {_won(dp)} &lt; 소매 100ml {_won(rp)} ({save_pct:+d}%)">🏆 면세↓</span>')
    if r["hk_cheaper"]:
        out.append(f'<span class="bdg ov" title="홍콩 현지가 {_won(r["hk_krw"])} &lt; 국내최저">🇭🇰↓</span>')
    if r["jp_cheaper"]:
        out.append(f'<span class="bdg ov" title="일본 현지가 {_won(r["jp_krw"])} &lt; 국내최저">🇯🇵↓</span>')
    if r["is_new"]:
        out.append('<span class="bdg new" title="최신 수집일에 갱신됨">🆕 new</span>')
    return " ".join(out)


def _change_cell(chg, unit):
    """변동 셀. unit='krw'|'usd'."""
    if not chg:
        return '<span class="muted">—</span>'
    if unit == "krw":
        d = chg["delta"]
        arrow = "🔻" if chg["dir"] == "down" else "🔺"
        cls = "dn" if chg["dir"] == "down" else "up"
        return (f'<span class="chg {cls}">{arrow} {abs(d):,}원'
                f' <small>({chg["pct"]:+.1f}%)</small></span>')
    else:  # usd
        d = chg["d_usd"]
        arrow = "🔻" if chg["dir"] == "down" else "🔺"
        cls = "dn" if chg["dir"] == "down" else "up"
        return f'<span class="chg {cls}">{arrow} ${abs(d):,.1f}</span>'


def _retail_cell(r):
    if r["retail_price"] is None:
        return '<span class="muted">소매가 수집 없음</span>'
    price = r["retail_price"]
    vol = r.get("retail_vol") or 700
    p100 = round(price / vol * 100)
    vtag = "1L" if vol == 1000 else f"{vol}ml"
    arrow = ""
    if r["retail_dir"] == "down":
        arrow = ' <span class="chg dn">▼</span>'
    elif r["retail_dir"] == "up":
        arrow = ' <span class="chg up">▲</span>'
    src = html.escape(r["retail_src"] or "")
    date = r["retail_date"]
    sub = f'{src} · {date}' if date else src
    # 데일리샷-only(엣지: 물리매장 floor 없음)면 1차값 옆에 위치(지역) 명시 — 진짜 최저가 숨기지 않음
    if r.get("primary_is_ds") and r.get("ds2_region"):
        sub += f' · {html.escape(r["ds2_region"])}'
    # 비교 가능할 때: 더 싼 쪽은 흰색(muted 제거), 비싼 쪽은 회색 유지
    retail_wins = r["df_per100"] is not None and not r.get("df_win")
    p100_cls = "" if retail_wins else ' class="muted"'
    cell = (f'<b>{_won(price)}</b> <small class="muted">/{vtag}</small>{arrow}'
            f'<br><small{p100_cls}>{p100:,}원/100ml · {sub}</small>')
    # CMPA-557: 물리매장이 1차일 때, 데일리샷이 더 싸면 위치(셀러+지역)와 함께 보조 노출.
    # 온라인이라 매장이 멀 수 있음을 💻 라벨로 암시.
    if r.get("ds2_show"):
        seller = r.get("ds2_seller")
        region = r.get("ds2_region")
        if seller:
            loc = html.escape(seller)
            if region:
                loc += f' <span class="muted">({html.escape(region)})</span>'
        else:
            loc = '<span class="muted">온라인 셀러</span>'
        cell += (f'<br><small class="ds-line">💻 데일리샷 '
                 f'<b>{_won(r["ds2_price"])}</b> · {loc}</small>')
    return cell


def _df_cell(r):
    if r["df_krw"] is None:
        return '<span class="muted">—</span>'
    # 용량 병기 — 면세는 1L 판이 많아 700ml 소매가와 병당 직접 비교는 오해 소지(용량 표기 필수)
    vol = r.get("df_vol") or 700
    vtag = "1L" if vol == 1000 else f"{vol}ml"
    p100 = round(r["df_krw"] / vol * 100)
    sname = html.escape(r["df_sname"] or "")
    surl = r.get("df_url") or ""
    # 신라 상품명 → 클릭하면 신라면세 상품 페이지로 이동(검증용)
    if surl:
        sub = f'<a href="{html.escape(surl)}" target="_blank" rel="noopener" class="muted src-link">{sname}</a>'
    else:
        sub = f'<span class="muted">{sname}</span>'
    # 면세가 더 싸면 흰색, 아니면 회색
    p100_cls = "" if r.get("df_win") else ' class="muted"'
    # 면세가 변동 표시 (신라 직전 스냅샷 대비)
    sc = r.get("df_change") or {}
    arrow = ""
    if sc.get("dir") == "down":
        d_krw = round(abs(sc.get("d_usd", 0)) * (r.get("_usd_krw") or 1519))
        arrow = f' <span class="chg dn">▼{d_krw:,}원</span>'
    elif sc.get("dir") == "up":
        d_krw = round(abs(sc.get("d_usd", 0)) * (r.get("_usd_krw") or 1519))
        arrow = f' <span class="chg up">▲{d_krw:,}원</span>'
    elif sc.get("dir") == "rate_change":
        dr = sc.get("d_rate")
        if dr is not None:
            sign = "▲" if dr > 0 else "▼"
            arrow = f' <span class="chg {"up" if dr > 0 else "dn"}">{sign}{abs(dr):.0f}%p</span>'
    return (f'<b>{_won(r["df_krw"])}</b> <small class="muted">/ {vtag}</small>{arrow}'
            f'<br><small{p100_cls}>{p100:,}원/100ml · {sub}</small>')


def render_html(rows, meta, log, snapshot_rel=None):
    gl = meta["global_latest"] or "—"
    ds_meta = meta["ds_meta"] or {}
    sh_meta = meta["sh_meta"] or {}
    df_meta = meta["dutyfree_meta"]  # {"sdate","fx_asof","usd_krw"} | None
    df_asof = df_meta.get("fx_asof") if df_meta else None
    df_usd_krw = df_meta.get("usd_krw") if df_meta else None

    # 라벨 동작 카운트
    n_win = sum(1 for r in rows if r.get("df_win"))
    n_hk = sum(1 for r in rows if r["hk_cheaper"])
    n_jp = sum(1 for r in rows if r["jp_cheaper"])
    n_new = sum(1 for r in rows if r["is_new"])

    def _savings_cell(r):
        """소매가-면세가: 100ml당 단가 차이 (원). 양수=면세 유리, 음수=소매 유리."""
        retail_p100 = round(r["retail_price"] / (r.get("retail_vol") or 700) * 100) if r.get("retail_price") else None
        df_p100 = r.get("df_per100")
        if retail_p100 is None or df_p100 is None:
            return '<span class="muted">—</span>', -999999
        diff = round(retail_p100 - int(df_p100))
        sub = (f'<br><small class="muted">면세 {int(df_p100):,}원 · 소매 {retail_p100:,}원 /100ml</small>')
        if diff > 0:
            return f'<span class="chg dn">+{diff:,}원/100ml</span>{sub}', diff
        elif diff < 0:
            return f'<span class="muted">{diff:,}원/100ml</span>{sub}', diff
        else:
            return f'<span class="muted">0원/100ml</span>{sub}', 0

    tr = []
    for r in rows:
        badges = _badges(r)
        type_label = _type_label(r["category"], r["name"])
        retail_price_sv = r["retail_price"] if r["retail_price"] is not None else -1
        df_krw_sv = r["df_krw"] if r["df_krw"] is not None else -1
        savings_html, savings_sv = _savings_cell(r)
        # 마일리지 할인율 컬럼
        mrate = r.get("df_mrate")
        try:
            mrate_f = float(mrate) if mrate is not None else None
        except (TypeError, ValueError):
            mrate_f = None
        mrate_sv = mrate_f if mrate_f is not None else -1
        if mrate_f is not None:
            mrate_html = f'<b>{mrate_f:.0f}%</b>'
        else:
            mrate_html = '<span class="muted">—</span>'
        name_cell = (f'{html.escape(r["name"])}'
                     f'<br><small class="muted">{html.escape(type_label)}</small>')
        if badges:
            name_cell += f'<div class="badges">{badges}</div>'
        dfview = "df" if savings_sv > 0 else "retail"
        tr.append(
            f'<tr data-dfview="{dfview}">'
            f'<td data-label="위스키" data-sort-val="{html.escape(r["name"])}">{name_cell}</td>'
            f'<td data-label="소매최저가" data-sort-val="{retail_price_sv}">{_retail_cell(r)}</td>'
            f'<td data-label="면세최저가" data-sort-val="{df_krw_sv}">{_df_cell(r)}</td>'
            f'<td data-label="면세할인율" data-sort-val="{mrate_sv}">{mrate_html}</td>'
            f'<td data-label="소매가-면세가" data-sort-val="{savings_sv}">{savings_html}</td>'
            "</tr>"
        )

    log_tr = "".join(
        f'<tr><td data-label="소스">{html.escape(str(s[0]))}</td>'
        f'<td data-label="마지막 수집일">{html.escape(str(s[1]))}</td>'
        f'<td data-label="품목 수">{html.escape(str(s[2]))}</td>'
        f'<td data-label="상태">{html.escape(str(s[3]))}</td></tr>'
        for s in log
    )

    legend_items = [
        ("🏆 면세↓", f"면세 100ml 단가 < 소매 100ml 단가 (용량 정규화 비교) — 동작 {n_win}건"),
        ("🇭🇰↓", f"홍콩 현지가 < 국내최저(표준용량) — 동작 {n_hk}건"),
        ("🇯🇵↓", f"일본 현지가 < 국내최저(표준용량) — 동작 {n_jp}건"),
        ("🆕 new", f"가장 최근 수집일({gl})에 갱신된 품목 — 동작 {n_new}건"),
    ]
    legend = "".join(
        f'<li><span class="lg">{html.escape(k)}</span> {html.escape(v)}</li>'
        for k, v in legend_items
    )

    fx_note = ""
    if df_usd_krw:
        fx_note = (f" · 면세 USD→KRW 환율 {df_usd_krw:,.2f}"
                   f" (기준일 {df_asof or '—'})")

    css = """
:root{--bg:#0f1115;--panel:#161922;--line:#2a2e38;--txt:#f2efe6;--sub:#9aa0aa;
--amber:#e0a84e;--gold:#ffd34e;--green:#34c759;--red:#ff6b6b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans KR",sans-serif;
line-height:1.5;font-size:15px}
.wrap{max-width:1080px;margin:0 auto;padding:18px 14px 60px}
h1{font-size:21px;margin:6px 0 4px;color:var(--gold)}
.sub{color:var(--sub);font-size:13px;margin:0 0 14px}
.draft{display:inline-block;background:rgba(255,107,107,.16);color:var(--red);
border:1px solid var(--red);border-radius:6px;padding:2px 8px;font-size:12px;font-weight:700}
h2{font-size:16px;color:var(--amber);margin:26px 0 10px;border-bottom:1px solid var(--line);
padding-bottom:6px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{border:1px solid var(--line);padding:8px 9px;text-align:left;vertical-align:top;
word-break:keep-all}
th{background:var(--panel);color:var(--amber);font-weight:700;white-space:nowrap}
tbody tr:nth-child(even){background:rgba(255,255,255,.015)}
b{color:var(--gold)}
small{font-size:11.5px}
.muted{color:var(--sub)}
a.src-link{color:var(--sub);text-decoration:underline dotted;text-underline-offset:2px}
.badges{margin-top:5px;display:flex;flex-wrap:wrap;gap:4px}
.bdg{font-size:11px;border-radius:5px;padding:1px 6px;white-space:nowrap;
border:1px solid var(--line)}
.bdg.win{background:rgba(52,199,89,.18);color:var(--green);border-color:var(--green)}
th[data-col]{cursor:pointer}
th[data-col]:hover{background:rgba(224,168,78,.12)}
.filter-bar{display:flex;gap:8px;margin-bottom:10px;flex-wrap:wrap}
.fbtn{background:var(--panel);border:1px solid var(--line);color:var(--sub);
border-radius:6px;padding:6px 14px;font-size:13px;cursor:pointer;white-space:nowrap}
.fbtn.active{background:rgba(224,168,78,.18);color:var(--amber);border-color:var(--amber);font-weight:700}
.bdg.ov{background:rgba(224,168,78,.14);color:var(--amber)}
.bdg.new{background:rgba(52,199,89,.16);color:var(--green);border-color:var(--green)}
.chg.dn{color:var(--green)}
.chg.up{color:var(--red)}
.ds-line{color:var(--amber)}
.ds-line b{color:var(--amber)}
.legend{list-style:none;padding:0;margin:0;display:grid;gap:6px}
.legend li{background:var(--panel);border:1px solid var(--line);border-radius:8px;
padding:8px 10px;font-size:13px;color:var(--sub)}
.legend .lg{color:var(--txt);font-weight:700;margin-right:6px}
.foot{margin-top:30px;padding-top:14px;border-top:1px solid var(--line);
color:var(--sub);font-size:12px}
code{word-break:break-all;overflow-wrap:anywhere}
/* 모바일 우선(CMPA-255): 좁은 화면은 행을 카드로 접는다(가로스크롤/숨김 없음) */
@media(max-width:640px){
  table,thead,tbody,th,td,tr{display:block}
  thead{position:absolute;left:-9999px}
  tr{margin:0 0 12px;border:1px solid var(--line);border-radius:10px;overflow:hidden}
  td{border:0;border-bottom:1px solid var(--line);padding:8px 12px;
     display:flex;justify-content:space-between;gap:12px}
  td:last-child{border-bottom:0}
  td::before{content:attr(data-label);color:var(--amber);font-weight:700;
     flex:0 0 38%;font-size:12px}
  /* 멀티라인 가격 셀(소매최저가·면세최저가·소매가-면세가)은 라벨을 위에 두고 값을 카드
     전체폭으로 — 좁은 폭(360px)에서 데일리샷 보조줄·출처·수집일이 잘리지 않게(CMPA-557·CLAUDE.md). */
  td[data-label="소매최저가"],td[data-label="면세최저가"],td[data-label="소매가-면세가"]{
     flex-direction:column;align-items:stretch;gap:3px}
  td[data-label="소매최저가"]::before,td[data-label="면세최저가"]::before,
  td[data-label="소매가-면세가"]::before{flex:none;font-size:12px}
  td[data-label="위스키"]{flex-direction:column;background:rgba(224,168,78,.06)}
  td[data-label="위스키"]::before{display:none}
  td[data-label="위스키"]{font-weight:700;color:var(--gold);font-size:15px}
  .badges{margin-top:6px}
}
"""

    html_doc = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>위스키 가격 대시보드 — CaskCode</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <h1>🥃 위스키 가격 대시보드</h1>
  <p class="sub">📅 소매 최신 수집: <b>{gl}</b>
  · 신라면세 수집: <b>{df_meta.get("sdate") if df_meta else "—"}</b>
  · 표시 {len(rows)}종 (소매 수집 {sum(1 for r in rows if r["retail_price"] is not None)}종 /
  신라면세 매칭 {sum(1 for r in rows if r["df_krw"] is not None)}종){fx_note}
  <br>가격은 '수집일 기준값'입니다(현재 이 순간의 값이 아닙니다 · CMPA-156). 소매최저가는
  면세·해외를 제외한 국내 소매가입니다(CMPA-321). 소매·면세 모두 100ml당 단가로 공정 비교
  가능합니다(용량 다른 경우에도).</p>

  <h2>현재 가격 상태</h2>
  <div class="filter-bar">
    <button class="fbtn active" data-fview="cheap" onclick="filterView('cheap')">💰 소매최저가↓</button>
    <button class="fbtn" data-fview="df" onclick="filterView('df')">🏆 면세유리 보기</button>
    <button class="fbtn" data-fview="retail" onclick="filterView('retail')">🛒 소매유리 보기</button>
    <button class="fbtn" data-fview="mrate" onclick="filterView('mrate')">면세할인율↓</button>
    <button class="fbtn" data-fview="name" onclick="filterView('name')">이름순</button>
  </div>
  <table id="main-table">
    <thead><tr>
      <th data-col="0">위스키 이름</th>
      <th data-col="1">소매최저가</th>
      <th data-col="2">면세최저가</th>
      <th data-col="3">면세할인율</th>
      <th data-col="4" data-sort-dir="desc">소매가-면세가 ▼</th>
    </tr></thead>
    <tbody>
      {''.join(tr)}
    </tbody>
  </table>

  <h2>범례 (라벨/뱃지)</h2>
  <ul class="legend">{legend}</ul>
  <p class="sub" style="margin-top:8px">
    · <b>소매최저가</b> = 실제로 갈 수 있는 <b>물리매장(트레이더스·코스트코 등)</b> 우선.
      데일리샷(온라인 마켓)이 더 싸면 <b>💻 데일리샷 가격 · 셀러(지역)</b> 으로 보조 표기 —
      온라인이라 매장이 멀 수 있어 위치를 함께 봅니다. 물리매장 수집이 없으면 데일리샷을
      1차값으로 표시(위치 포함).<br>
    · 소매최저가 옆 ▼/▲ = 같은 소스(매장)의 직전 수집가 대비 방향(CMPA-496 소스별 최신가 floor).<br>
    · 소매가-면세가 = 소매 100ml 단가 − 면세 100ml 단가 (원). 양수=면세 유리, 음수=소매 유리.<br>
    · 🆕 판정 = 품목의 국내 최신 수집일이 데이터셋 전체 최신 수집일({gl})과 같을 때.<br>
    · <b>소매·면세 모두 100ml당 단가로 공정 비교</b>(소매 700ml vs 면세 1L 등 용량 차이 보정).
      면세가가 소매 100ml 단가의 2.5배↑(에디션 비대칭 의심)인 경우는 제외.
      소매 수집이 없는 상품은 소매가 '수집 없음'으로 표시됩니다.
    · 컬럼 제목 클릭 시 해당 컬럼 기준으로 재정렬합니다.
  </p>

  <h2>데이터 수집 로그 요약</h2>
  <table>
    <thead><tr><th>소스</th><th>마지막 수집일</th><th>품목 수</th><th>상태</th></tr></thead>
    <tbody>{log_tr}</tbody>
  </table>

  <p class="foot">생성기 <code>pipelines/dashboard/build_dashboard.py</code> ·
  정본 데이터 재사용(normalized_prices · source_floor · detect_* · master-sku) ·
  데이터 스냅샷 <code>{html.escape(snapshot_rel or 'data/dashboard/dashboard_latest.json')}</code>
  (basis_date {gl}, 메타데이터 동봉 — 다음 수집분을 이 위에 적용해 갱신) ·
  발행/라우틴 배선 없음(2단계 예정). by CaskCode.</p>
</div>
<script>
(function(){{
  var tbl = document.getElementById('main-table');
  if(!tbl) return;
  var ths = tbl.querySelectorAll('thead th');
  var sortCol = 4, sortAsc = false;
  function indicator(col, asc) {{
    ths.forEach(function(th,i) {{
      var base = th.textContent.replace(/ [▲▼]$/, '');
      if(i === col) th.textContent = base + (asc ? ' ▲' : ' ▼');
      else th.textContent = base;
    }});
  }}
  function sortBy(col, forcedAsc) {{
    if(forcedAsc !== undefined) {{
      sortCol = col; sortAsc = forcedAsc;
    }} else if(sortCol === col) {{
      sortAsc = !sortAsc;
    }} else {{
      sortCol = col; sortAsc = (col === 0 || col === 1 || col === 2);
    }}
    var tbody = tbl.querySelector('tbody');
    var rows = Array.from(tbody.querySelectorAll('tr'));
    rows.forEach(function(r) {{ r.style.display = ''; }});  // 필터 숨김 해제
    var isText = (col === 0);
    rows.sort(function(a, b) {{
      var av = a.children[col] ? a.children[col].getAttribute('data-sort-val') : '';
      var bv = b.children[col] ? b.children[col].getAttribute('data-sort-val') : '';
      var cmp;
      if(isText) {{
        cmp = (av || '').localeCompare(bv || '', 'ko');
      }} else {{
        var an = parseFloat(av), bn = parseFloat(bv);
        if(isNaN(an)) an = -999999;
        if(isNaN(bn)) bn = -999999;
        // 데이터 없는 행(sentinel)은 정렬방향과 관계없이 항상 하단
        var aBot = (col === 4 ? an <= -99999 : an < 0);
        var bBot = (col === 4 ? bn <= -99999 : bn < 0);
        if(aBot && !bBot) return 1;
        if(!aBot && bBot) return -1;
        cmp = an - bn;
      }}
      return sortAsc ? cmp : -cmp;
    }});
    rows.forEach(function(r) {{ tbody.appendChild(r); }});
    indicator(col, sortAsc);
  }}
  window.filterView = function(view) {{
    document.querySelectorAll('.fbtn').forEach(function(b) {{
      b.classList.toggle('active', b.dataset.fview === view);
    }});
    // 버튼은 정렬 숏컷
    if(view === 'cheap') sortBy(1, true);  // 소매최저가 오름차순(싼값 먼저)
    else if(view === 'df') sortBy(4, false);
    else if(view === 'retail') sortBy(4, true);
    else if(view === 'mrate') sortBy(3, false);  // 면세할인율↓ 높은순
    else if(view === 'name') sortBy(0, true);
    else sortBy(1, true);
  }};
  ths.forEach(function(th, i) {{
    th.style.cursor = 'pointer';
    th.style.userSelect = 'none';
    th.addEventListener('click', function() {{ sortBy(i); }});
  }});
  filterView('cheap');  // 기본값: 소매최저가 오름차순(싼값 먼저) (CMPA-671)
}})();
</script>
</body>
</html>
"""
    return html_doc


def main():
    ap = argparse.ArgumentParser(description="위스키 가격 대시보드 초안 HTML 생성기 (CMPA-507)")
    ap.add_argument("--out", default=OUT_DEFAULT, help="출력 HTML 경로")
    ap.add_argument("--no-snapshot", action="store_true",
                    help="데이터 스냅샷 JSON 기록 생략(HTML 만)")
    args = ap.parse_args()

    rows, meta, log = build_rows()

    # 데이터 스냅샷(정본 데이터 레이어) — 보드 2026-06-19. HTML 은 이 스냅샷에서 렌더.
    snap = assemble_snapshot(rows, meta, log)
    snap_rel = None
    if not args.no_snapshot:
        paths = write_snapshot(snap)
        snap_rel = os.path.relpath(paths["dated"], ROOT)
        print(f"WROTE {paths['dated']}")
        print(f"WROTE {paths['latest']}")

    doc = render_html(rows, meta, log, snapshot_rel=snap_rel)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(doc)

    c = snap["snapshot"]["counts"]
    print(f"WROTE {args.out}")
    print(f"  rows={c['rows']}  면세매칭={c['dutyfree_matched']}")
    print(f"  badges: 🔥핫딜={c['hotdeal']} 🏆면세↓={c.get('dutyfree_win',0)} "
          f"🇭🇰↓={c['hk_cheaper']} 🇯🇵↓={c['jp_cheaper']} 🆕new={c['new']}")
    print(f"  기준일/basis_date={snap['snapshot']['basis_date']}")


if __name__ == "__main__":
    main()
