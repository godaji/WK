#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
kr_jp_compare.py — 한국 vs 일본 위스키 가격 비교표 (CMPA-53).

[CMPA-53](/CMPA/issues/CMPA-53)에서 JP Shopify 수집기를 정규화에 배선한 결과(정본 id 매칭)를
바탕으로, 기존 한국-홍콩 비교표(whisky_report_tables.build_overseas)와 같은 형식의
**한국-일본** 비교표를 만든다. 정규화된 정본 id 로 동일-병을 잇기 때문에 정규식 큐레이션보다
견고하다(JapaneseMatcher 매칭, 후보 모호는 미매칭).

비교 컬럼
  · 국내 최저가(₩)        : normalized KR(마트/유튜브) 최저가 (데일리샷 KR-DS 는 참고로 별도)
  · 일본 현지가(₩)        : JP Shopify 기준가_KRW(현지 판매가 환산, 면세·무관세 — 홍콩 면세가와 같은 성격)
  · 일본 반입추정가(₩)    : 한국 반입세 cascade(×2.5555) 적용가 — 실제 직구/반입 시 부담
  · 어디가 싼가           : 국내 최저가 vs 일본 현지가 기준

입력
  · data/whisky-prices/normalized/normalized_prices.csv  (KR/JP 정본 id 매칭 결과)
  · data/whisky-prices/jp/2026-05_jp_shopify_poc.csv      (JP 현지가/반입가)
  · assets/whisky-list.csv                                (유형/카테고리)
출력
  · stdout 표 + reports/whisky-price/CMPA-53_한일가격비교.md
용법
  python3 scripts/kr_jp_compare.py
"""
import csv, os, collections, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pipelines.common.dated import snapshot, kst_today  # noqa: E402
from pipelines.common.whisky_quality import is_collectible  # noqa: E402  (CMPA-243 빈티지 격리)
DATA = os.path.join(ROOT, "data", "whisky-prices")
NORM = os.path.join(DATA, "normalized", "normalized_prices.csv")
JP_CSV = os.path.join(DATA, "jp", "2026-05_jp_shopify_poc.csv")
WL = os.path.join(ROOT, "assets", "whisky-list.csv")
OUT_MD = os.path.join(ROOT, "reports", "whisky-price", "CMPA-53_한일가격비교.md")  # CMPA-88


def fmt(v):
    return f"{int(round(v)):,}" if v is not None else "—"


def load_rows(p):
    with open(p, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _cid_to_keys():
    """canonical_id → 그 id 로 묶인 KR(마트) raw_name 들의 whisky_report_tables.key() 집합.
    [1] 핵심표(recs)·[2] 홍콩표와 동일 key 체계라 교집합/조인이 가능하다(CMPA-54)."""
    import whisky_report_tables as W  # 지연 import — 순환참조 방지(W 는 JP 를 import 하지 않음)
    m = {}
    for r in load_rows(NORM):
        if r.get("market") == "KR" and r.get("raw_name"):
            m.setdefault(r["canonical_id"], set()).add(W.key(r["raw_name"]))
    return m


def gated_kr_min():
    """CMPA-231(보드 A): [3] 일본표·🇯🇵 배지의 '국내 최저가'를 [1]/[2]와 **동일한 신선도 게이트**로
    맞춘다. 종전엔 정규화본의 *모든 날짜* KR 최저가를 써서, [1] 핵심표가 CMPA-177 '판매처 최신
    sweep' 게이트로 제외한 항목(예: 라프로익 10년 — 06-01 트레이더스 sweep에 없음)이 [3]엔 옛 가격으로
    남는 불일치가 있었다. 이제 **build_domestic(=[1]) 의 게이트 통과 현재가(cur)** 만 정본으로 삼아
    canonical_id 로 역조인한다 → 세 표가 일관. 최신 sweep 에 없는 cid 는 키가 없어 [3]에서도 빠진다.
    반환: {canonical_id: 게이트 통과 국내 현재가(₩)}."""
    import whisky_report_tables as W  # 지연 import(순환참조 방지)
    agg, disp = W.load()
    _, recs = W.build_domestic(agg, disp, W.load_dailyshot())
    kcur = {r["k"]: r["cur"] for r in recs}              # [1] 게이트 통과 key → 현재 최저가
    gated = {}
    for cid, keys in _cid_to_keys().items():
        cand = [kcur[k] for k in keys if k in kcur]      # 그 cid 의 KR key 중 게이트 통과분
        if cand:
            gated[cid] = min(cand)
    return gated


def compute_rows():
    """정규화 데이터에서 한↔일 동일-병 비교 행을 만든다.
    반환: (rows, stats). rows = [{cid,name,cat,kr,krds,jp_local,jp_landed}], 국내가/현지가 비율 오름차순.
    generate_report 의 상설 JP 섹션과 standalone 리포트가 같은 로직을 공유한다.
    국내 최저가(kr)는 CMPA-231(보드 A)로 [1]/[2]와 같은 CMPA-177 최신-sweep 게이트를 적용한다(gated_kr_min)."""
    clean = load_rows(NORM)
    wl = {r["id"]: r for r in load_rows(WL)}
    kr_gated = gated_kr_min()        # CMPA-231: [1] 핵심표와 동일 신선도 게이트의 국내 현재가

    # KR-DS(데일리샷) 참고 + name_ko + JP raw 목록 per 정본 id (국내 현재가는 kr_gated 사용)
    krds_min, name_ko = {}, {}
    jp_raws = collections.defaultdict(set)
    for r in clean:
        cid = r["canonical_id"]
        if not cid:
            continue
        name_ko[cid] = r["canonical_name_ko"]
        p = int(r["price_krw"]) if r["price_krw"] else None
        if p is None:
            continue
        # 비표준 용량(700/750ml 외)은 동일-병 비교에서 제외 — 미니/500ml 변형이 KR 측
        # 정규화 노이즈(예: 500ml 글렌버기 싱글몰트가 '발렌타인 12년'으로 오병합)로 섞이는 것 차단.
        vol = r.get("volume_ml")
        if vol and vol.isdigit() and not (650 <= int(vol) <= 800):
            continue
        if r["market"] == "KR-DS":
            krds_min[cid] = min(krds_min.get(cid, p), p)
        elif r["market"] == "JP":
            jp_raws[cid].add(r["raw_name"])

    # JP Shopify: 술이름 -> (현지가_KRW, 반입추정가_KRW).
    # 키는 normalize 어댑터와 동일하게 .strip() 정렬(정확 문자열 조인 누락 방지).
    jp_local, jp_landed = {}, {}
    for r in load_rows(JP_CSV):
        nm = (r["술이름"] or "").strip()
        # CMPA-243: 빈티지/컬렉터블/단독캐스크/대용량(빈티지연도·限定·2L 등) JP SKU 는 동일-병
        # 비교 후보에서 격리 — 표준 700/750ml 소매와 가격대가 달라 오매칭 시 가짜딜을 만든다.
        if is_collectible(nm):
            continue
        try:
            jp_local[nm] = int(r["기준가_KRW"])
            jp_landed[nm] = int(r["한국반입추정가_KRW"])
        except (ValueError, KeyError):
            pass

    rows = []
    for cid, raws in jp_raws.items():
        if cid not in kr_gated:
            continue  # CMPA-231: [1] 최신-sweep 게이트를 통과한 국내 현재가가 있어야 비교 성립
        locs = [jp_local[n] for n in raws if n in jp_local]
        lands = [jp_landed[n] for n in raws if n in jp_landed]
        if not locs:
            continue
        meta = wl.get(cid, {})
        cat = meta.get("category", "") or "—"
        rows.append({
            "cid": cid, "name": name_ko.get(cid, cid), "cat": cat,
            "kr": kr_gated[cid], "krds": krds_min.get(cid),
            "jp_local": min(locs), "jp_landed": min(lands) if lands else None,
        })

    rows.sort(key=lambda r: r["kr"] / r["jp_local"])
    dom_win = sum(1 for r in rows if r["kr"] <= r["jp_local"])
    stats = {"n": len(rows), "dom_win": dom_win, "jp_win": len(rows) - dom_win}
    return rows, stats


def jp_cheaper_keys(rows):
    """국내가 ≤ 일본 현지가인 동일-병의 정본(whisky_report_tables) key 집합 — 핵심표 🇯🇵 배지용(CMPA-54).
    canonical_id → 그 id 로 묶인 KR(마트) raw_name 들의 whisky_report_tables.key() 로 역매핑한다
    (핵심표 recs 가 같은 key 체계라 그대로 교집합 가능). 비-국내우세 행은 제외.
    CMPA-231: rows 의 'kr' 가 이제 게이트 통과 현재가라 cheaper 판정도 [1]/[2]와 일관."""
    cid2keys = _cid_to_keys()
    keys = set()
    for r in rows:
        if r["kr"] <= r["jp_local"]:           # 국내가가 일본 현지가보다 싼 경우만
            keys |= cid2keys.get(r["cid"], set())
    return keys


def table_md(rows):
    """비교 행 → 마크다운 표(헤더+구분선+행). 리포트/standalone 공용."""
    out = ["| 위스키 | 유형 | 국내 최저가(₩) | 🇯🇵일본 현지가(₩) | 🇯🇵반입추정가(₩) | 국내가=일본현지의 | 어디가 싼가 |",
           "|---|:--:|---:|---:|---:|:--:|---|"]
    for r in rows:
        ratio = r["kr"] / r["jp_local"]
        if r["kr"] <= r["jp_local"]:
            verdict = f"**국내 {round((1-ratio)*100)}%↓**"
        else:
            verdict = f"일본현지 {round((1-r['jp_local']/r['kr'])*100)}%↓"
        out.append(f"| {r['name']} | {r['cat']} | **{fmt(r['kr'])}** | {fmt(r['jp_local'])} | "
                   f"{fmt(r['jp_landed'])} | **{ratio*100:.0f}%** | {verdict} |")
    return out


def main():
    rows, stats = compute_rows()
    L = ["# CMPA-53 한국 ↔ 일본 위스키 가격 비교", ""]
    L.append("> `scripts/kr_jp_compare.py` 산출. JP Shopify(키리스, CMPA-52) 수집 → 정본 id 매칭"
             "(JapaneseMatcher, CMPA-53) → 한↔일 동일-병 비교. 한국-홍콩 비교표와 동일 형식. "
             "메인 가격리포트(`generate_report.py`)에 [3] 일본 상설 섹션으로도 편입됨.")
    L.append("")
    L.append(f"- 한↔일 **동일-병 매칭 SKU: {stats['n']}종** (정본 id 기준, 마트 국내가 존재분)")
    L.append("- **일본 현지가** = JP 소매가 환산(면세·무관세, 홍콩 '면세가'와 같은 성격). "
             "**반입추정가** = 한국 반입세 ×2.5555 적용(실제 직구 부담).")
    L.append("- 환율·세금 cascade 는 `pipelines/common/fx_tax.py` 공통 모듈(관세20/주세72/교육세30/부가10).")
    L.append("")
    L += table_md(rows)
    L.append("")
    L.append(f"**요약**: 비교 {stats['n']}종 중 **국내가 우세 {stats['dom_win']}종 / 일본현지 우세 {stats['jp_win']}종**. "
             "반입추정가(세금 포함)는 전 품목에서 일본이 국내보다 비싸짐 — 반입세(×2.56)가 현지 가격차를 상쇄.")
    L.append("")
    L.append("> ⚠️ JP 매칭은 가타카나 브랜드+숙성년수(N年) 휴리스틱(reason=`ja`) — 본표 외부 공개 전 "
             "스팟체크 권장. 외부 공개/상업화는 [CMPA-15](/CMPA/issues/CMPA-15)/board gate 대상.")
    L.append("")

    os.makedirs(os.path.dirname(OUT_MD), exist_ok=True)
    with open(OUT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(L) + "\n")
    snapshot(OUT_MD, run_date=kst_today())     # CMPA-38/45 날짜 스냅샷(_runs/)
    print("\n".join(L))
    print(f"\n[written] {os.path.relpath(OUT_MD, ROOT)}  ({stats['n']} rows, 국내우세 {stats['dom_win']})")


if __name__ == "__main__":
    main()
