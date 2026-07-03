#!/usr/bin/env python3
"""데일리샷 일간 가격변동 → 블로그 패치 md (CMPA-390).

신라 패치 정본(`pipelines/shilla_dutyfree/build_blog_md.render_patch_md`)의
**2컬럼 모바일 표 (위스키, 상세)** · front-matter 패턴을 데일리샷판으로 따라 만든다.
정본 동기화를 위해 `front_matter()` 헬퍼를 그대로 재사용한다.

포지셔닝(보드 CMPA-389):
  - 신라 패치 = 면세가 변동. 데일리샷 패치 = **국내 최저가(전국 최저 셀러가) 변동** = 구매 신호.
  - `ds_price` = 데일리샷 제품 페이지 전국 최저 셀러가(CMPA-344).
  - 면세/해외 리스팅 제외(CMPA-321)는 데이터단(crawl)에서 이미 처리됨.

front-matter:
  - categories: [wprice]   ← 렌더 버킷(고아글 금지, CMPA-326). 홈 wprice 아코디언 + Cask 노출.
  - kind: ds-patch
  - robots: noindex,nofollow  ← 미발행 게이트.
  - byline 'by Dram' 은 포스트 레이아웃이 categories(≠tasting)로 자동 부여(CMPA-369).

⚠️ 배포 금지: 이 스크립트는 blog-md/_posts/ 에 **초안만** 쓴다. caskcode-publish push 안 함.
"""
import os
import sys
import argparse

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)                                   # detect_dailyshot_changes
sys.path.insert(0, os.path.join(_HERE, "..", "shilla_dutyfree"))  # build_blog_md.front_matter

from detect_dailyshot_changes import classify, load_csv     # noqa: E402
from build_blog_md import front_matter                       # noqa: E402  (정본 동기화)


def _won(p):
    return f"{p:,}원" if p is not None else "—"


def _delta(d, pct):
    if d is None:
        return "—", "—"
    sign = "+" if d >= 0 else ""
    return f"{sign}{d:,}원", f"{sign}{pct:.1f}%"


def _seller_from_bigo(bigo):
    """floor 런 CSV 의 비고('... 페이지최저 N(셀러:상호)[검색 M]')에서 리테일샵 상호 추출.
    상호 자체에 괄호가 있을 수 있어(예: 'AS(알코올수지)') 바깥 닫는 괄호 하나만 떼낸다."""
    i = bigo.find("(셀러:")
    if i < 0:
        return None
    rest = bigo[i + 4:].split("[검색")[0]
    if rest.endswith(")"):
        rest = rest[:-1]
    rest = rest.strip()
    return rest or None


def load_floor_shops(run_csv, listings_csv=None):
    """최신 floor 런 CSV → {product_id: (셀러명, 지역|None)}.

    데일리샷 floor 가 '데일리샷 리테일샵(페이지 최저 셀러)'인 항목만 잡힌다
    (트레이더스·코스트코 등 마트 floor 는 비고에 셀러: 가 없어 제외 — 그쪽은 국내위치로 이미 표기).
    지역은 동반 listings CSV(셀러명→지역)에서 보강(있으면)."""
    import csv as _csv
    import re as _re
    shops = {}
    with open(run_csv, encoding="utf-8-sig") as f:
        for row in _csv.DictReader(f):
            m = _re.search(r"/product/(\d+)", row.get("URL") or "")
            if not m:
                continue
            s = _seller_from_bigo(row.get("비고") or "")
            if s:
                shops[m.group(1)] = s
    regions = {}
    if listings_csv and os.path.exists(listings_csv):
        with open(listings_csv, encoding="utf-8-sig") as f:
            for row in _csv.DictReader(f):
                nm = (row.get("셀러명") or "").strip()
                reg = (row.get("지역") or "").strip()
                if nm and reg and nm not in regions:
                    regions[nm] = reg
    return {pid: (nm, regions.get(nm)) for pid, nm in shops.items()}


def _shop_link(url, shops):
    """URL 의 product_id 에 리테일샵이 잡히면 '🏬 [상호 (지역)](url)' 링크 셀을 반환.
    없으면 None (호출부가 기본 '[데일리샷 🔗]' 로 폴백)."""
    if not shops or not url:
        return None
    import re as _re
    m = _re.search(r"/product/(\d+)", url)
    if not m:
        return None
    info = shops.get(m.group(1))
    if not info:
        return None
    name, region = info
    label = f"{name} · {region}" if region else name
    return f"🏬 [{label}]({url})"


def _dedup_by_url(rows):
    """같은 제품(=같은 데일리샷 URL)인데 수집명 변형만 다른 행을 1행으로 합친다
    (CMPA-177 매칭 원칙 — 동의어 변형은 한 SKU). URL 없으면 이름으로 키.
    최초 출현 행을 대표로 유지(정렬은 호출부에서 이미 변동폭 순)."""
    seen, out = set(), []
    for r in rows:
        url = (r[7] or "").strip()
        key = url or f"name::{r[0]}"
        if key in seen:
            continue
        seen.add(key)
        out.append(r)
    return out


def _tail(loc, url, acc, shops):
    """상세 칸 꼬리: 국내위치 · (리테일샵 링크 | 데일리샷 링크) · 매칭."""
    tail = []
    if loc:
        tail.append(loc)
    shop = _shop_link(url, shops)
    if shop:
        tail.append(shop)
    elif url:
        tail.append(f"[데일리샷 🔗]({url})")
    if acc:
        tail.append(f"매칭 {acc}")
    return tail


def _cell_move(r, shops=None):
    """변동 행(직전·현재 둘 다 있음) → 상세 칸(<br> 묶음)."""
    nm, prev_p, cur_p, d, pct, acc, loc, url, cf = r
    dtxt, ptxt = _delta(d, pct)
    parts = [f"직전 {_won(prev_p)} → 현재 **{_won(cur_p)}**",
             f"**{dtxt}** ({ptxt})"]
    tail = _tail(loc, url, acc, shops)
    if tail:
        parts.append(" · ".join(tail))
    if cf:
        parts.append("⚠️ 보존값(미관측)")
    return "<br>".join(parts)


def _cell_new(r, shops=None):
    nm, prev_p, cur_p, d, pct, acc, loc, url, cf = r
    parts = [f"현재 **{_won(cur_p)}** (신규 입고)"]
    tail = _tail(loc, url, acc, shops)
    if tail:
        parts.append(" · ".join(tail))
    return "<br>".join(parts)


def _cell_lost(r, shops=None):
    nm, prev_p, cur_p, d, pct, acc, loc, url, cf = r
    parts = [f"직전 {_won(prev_p)} → 현재 **품절/내림**"]
    if loc:
        parts.append(loc)
    return "<br>".join(parts)


def _table(rows, cell_fn, shops=None):
    out = ["| 위스키 | 상세 |", "|---|---|"]
    for r in rows:
        out.append(f"| {r[0]} | {cell_fn(r, shops)} |")
    out.append("")
    return out


def render(prev_label, latest_label, prev_date, latest_date,
           drops, rises, new_hit, lost, shops=None, shop_date=None):
    drops = _dedup_by_url(drops)
    rises = _dedup_by_url(rises)
    new_hit = _dedup_by_url(new_hit)
    lost = _dedup_by_url(lost)

    title = f"[데일리샷] 국내 최저가 변동 {latest_date}"
    fm = front_matter({
        "layout": "post",
        "title": title,
        "date": f"{latest_date} 09:30:00 +0900",
        "categories": ["wprice"],
        "kind": "ds-patch",
        "prev_date": prev_date,
        "latest_date": latest_date,
        "drops": len(drops),
        "rises": len(rises),
        "description": (f"데일리샷 국내 최저가(전국 최저 셀러가) 변동 {latest_date} — "
                        f"하락 {len(drops)} · 상승 {len(rises)}. CaskCode"),
        "robots": "noindex,nofollow",
    })

    b = [fm, ""]
    b.append(f"*직전 {prev_date} → 최신 {latest_date} 수집 기준*")
    b.append("")
    b.append("> **데일리샷 가격 = 제품 페이지 전국 최저 셀러가**(CMPA-344). "
             "면세점·해외 셀러는 국내 최저가가 아니라 제외했습니다(CMPA-321). "
             "수집 날짜 기준값이며, 현재가는 이 날짜로 유추합니다.")
    b.append("")
    b.append("신라면세 패치가 *면세가* 변동이라면, 이 글은 **국내에서 실제로 살 때의 "
             "최저가** 변동입니다 — 값이 내리면 구매 타이밍 신호입니다.")
    b.append("")
    if shops:
        b.append(f"> 🏬 = **데일리샷 최저가 리테일샵**(상호를 누르면 데일리샷 상품 페이지 → "
                 f"해당 셀러 구매). 최신 수집 {shop_date or latest_date} 기준 최저 셀러이며, "
                 f"트레이더스·코스트코 표기 항목은 그 창고형 매장이 최저가라 별도 리테일샵이 없습니다.")
        b.append("")

    b.append(f"## 🔻 가격 하락 ({len(drops)}) — 구매 신호")
    b.append("")
    if drops:
        b += _table(drops, _cell_move, shops)
    else:
        b.append("이번 구간엔 하락 항목이 없습니다.")
        b.append("")

    if rises:
        b.append(f"## 🔺 가격 상승 ({len(rises)})")
        b.append("")
        b += _table(rises, _cell_move, shops)

    if new_hit:
        b.append(f"## 🆕 신규 입고 ({len(new_hit)})")
        b.append("")
        b += _table(new_hit, _cell_new, shops)

    if lost:
        b.append(f"## ⚪ 품절/내림 ({len(lost)})")
        b.append("")
        b += _table(lost, _cell_lost)

    return "\n".join(b).rstrip() + "\n"


def _date_from_label(label):
    """'2026-06_dailyshot__run2026-06-12' 또는 '..._am' → '2026-06-12' / '2026-06-12 (오전)'."""
    import re
    m = re.search(r"run(\d{4}-\d{2}-\d{2})(?:_(am|pm))?", label)
    if not m:
        return label
    d = m.group(1)
    slot = m.group(2)
    if slot == "am":
        return f"{d} 오전"
    if slot == "pm":
        return f"{d} 오후"
    return d


def main():
    ap = argparse.ArgumentParser(description="데일리샷 가격변동 블로그 패치 md (CMPA-390)")
    ap.add_argument("--prev", required=True, help="직전 스냅샷 CSV")
    ap.add_argument("--latest", required=True, help="최신 스냅샷 CSV")
    ap.add_argument("--out", required=True, help="출력 md 경로 (blog-md/_posts/...)")
    ap.add_argument("--shops", help="리테일샵(셀러) 출처 floor 런 CSV (비고에 '셀러:' 포함). "
                                    "기본=--latest. 예전 스냅샷은 셀러 미수집이라 최신 런을 지정.")
    ap.add_argument("--listings", help="지역 보강용 동반 listings CSV (셀러명→지역)")
    args = ap.parse_args()

    prev_label = os.path.splitext(os.path.basename(args.prev))[0]
    latest_label = os.path.splitext(os.path.basename(args.latest))[0]
    prev_date = _date_from_label(prev_label)
    latest_date = _date_from_label(latest_label)

    prev_rows = load_csv(args.prev)
    latest_rows = load_csv(args.latest)
    drops, rises, new_hit, lost = classify(prev_rows, latest_rows)

    shops_src = args.shops or args.latest
    shops = load_floor_shops(shops_src, args.listings)
    shop_date = _date_from_label(os.path.splitext(os.path.basename(shops_src))[0])

    md = render(prev_label, latest_label, prev_date, latest_date,
                drops, rises, new_hit, lost, shops=shops, shop_date=shop_date)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"[written] {args.out}")
    print(f"  drops={len(_dedup_by_url(drops))} rises={len(_dedup_by_url(rises))} "
          f"new={len(_dedup_by_url(new_hit))} lost={len(_dedup_by_url(lost))} "
          f"(dedup by URL; raw drops={len(drops)})")
    print(f"  shops={len(shops)} (출처 {os.path.basename(shops_src)})")


if __name__ == "__main__":
    main()
