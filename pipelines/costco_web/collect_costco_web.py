#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collect_costco_web.py — 국내 마트(코스트코 우선) 웹 가격 주간 수집기 (CMPA-28)

배경 / 왜 이 소스인가
---------------------
한국은 **주류 통신판매(온라인 판매) 금지**라 코스트코·이마트·롯데마트의 공식 e-commerce
( costco.co.kr / emart.ssg.com / lottemart )에는 **위스키 상품 자체가 노출되지 않는다.**
  - 실측: costco.co.kr Hybris REST(`/rest/v2/korea/products/search?query=위스키`)는 하이볼잔·
    토닉워터·김치냉장고만 반환(위스키 0건).
따라서 "마트 웹 가격"은 공식몰이 아니라 **매장 가격표를 추적·게시하는 2차 웹 소스**에서 얻는다.
본 수집기의 1차 소스는 **costcome.com(코스트컴)** — 코스트코 매장 위스키 가격/할인 이력을
상품별로 정리해 자동 갱신하는 가격추적 블로그. 단건 수동 WebSearch(기존 05월 코스트코 행 생성
방식)를 반복 가능한 스크립트로 자동화한 것이다.

출력
----
`data/whisky-prices/YYYY-MM.csv` 에 코스트코 행 append (정본 7컬럼 스키마):
  술이름, 가격_KRW, 위치, 가져온날짜, 출처, 신뢰도, 비고
메트릭: `data/whisky-prices/_costco_web_metrics.json`

용법
----
  python3 pipelines/costco_web/collect_costco_web.py            # 수집 + 해당월 CSV append
  python3 pipelines/costco_web/collect_costco_web.py --dry-run  # 수집만, 파일 미수정(콘솔 출력)
  python3 pipelines/costco_web/collect_costco_web.py --limit 8  # 기사 N건만(스모크)
  python3 pipelines/costco_web/collect_costco_web.py --month 2026-05

정직성 노트
-----------
- costcome 가격은 "포스팅 작성/갱신 시점" 기준 코스트코 매장가 → 실시간 아닐 수 있어 신뢰도=중.
- 코스트코는 점포·주차별 가격이 갈리므로 단일 대표가로 본다(점포 미상). 비고에 소스 명시.
- 정규화·검증은 후속(CMPA-29/30)에서. 여기서는 raw 표기 + 정본 매칭 힌트(비고)만 남긴다.
"""
import argparse
import datetime
import html
import json
import os
import re
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from pipelines.common.dated import snapshot  # noqa: E402
from pipelines.common.whisky_quality import is_quarantined  # noqa: E402

CATEGORY_URL = "https://costcome.com/category/item/whiskey/"
BASE = "https://costcome.com/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
OUT_DIR = os.path.join(ROOT, "data", "whisky-prices")
METRICS = os.path.join(OUT_DIR, "_costco_web_metrics.json")
SCHEMA = ["술이름", "가격_KRW", "위치", "가져온날짜", "출처", "신뢰도", "비고"]
SOURCE_LABEL = "costcome.com(코스트컴)"

# 코스트코 위스키 상품 기사가 아닌(목록/카테고리/와인 등) 슬러그 제외
SLUG_DENY = re.compile(
    r"(list|category|recommended|winelist|wine-list|/category/|/tag/|/page/|feed|wp-json)", re.I)
PRICE_MIN, PRICE_MAX = 20_000, 2_000_000  # 위스키 1병 합리적 KRW 범위

WON = r"([0-9]{1,3}(?:,[0-9]{3})+)"  # 12,345 형태

# 위스키 문맥 토큰(제목/상품명에 하나라도 있으면 위스키 기사로 인정)
WHISKY_TOKENS = ("위스키", "위스키", "스카치", "싱글몰트", "싱글 몰트", "몰트", "버번",
                 "버본", "블렌디드", "년산", "년 ", "whisky", "whiskey")
# 토큰이 없어도 위스키로 인정하는 브랜드 allowlist(데이터에 등장한 주요 브랜드)
WHISKY_BRANDS = ("잭다니엘", "잭 다니엘", "짐빔", "와일드터키", "와일드 터키", "버팔로",
                 "메이커스", "발렌타인", "시바스", "조니워커", "조니 워커", "글렌", "맥캘란",
                 "발베니", "달모어", "몽키숄더", "몽키 숄더", "제임슨", "듀어스", "라프로익",
                 "라프로잇", "탈리스커", "커클랜드", "우드포드", "에반", "아벨라워", "아란",
                 "오반", "주라", "부시밀", "로얄살루트", "발렌", "산토리", "가쿠빈", "각쿠빈")
# 명백한 비위스키(코스트코 추천/관련 글 누수 차단)
NON_WHISKY_DENY = ("커피머신", "머신", "냉장고", "청소기", "세탁기", "에어컨", "노트북",
                   "매트리스", "타이어", "그릴", "프라이팬", "와인", "맥주", "보드카",
                   "데킬라", "럼", "진토닉")


def is_whisky(name, title):
    blob = (name + " " + title)
    if any(d in blob for d in NON_WHISKY_DENY):
        return False
    if any(t in blob for t in WHISKY_TOKENS):
        return True
    if any(b in name for b in WHISKY_BRANDS):
        return True
    return False


def fetch(url, retries=3, delay=1.0):
    last = None
    for i in range(retries):
        try:
            r = requests.get(url, headers={"User-Agent": UA,
                                           "Accept-Language": "ko-KR,ko;q=0.9"},
                             timeout=20)
            if r.status_code == 200 and r.text:
                r.encoding = r.apparent_encoding or "utf-8"
                return r.text
            last = f"http={r.status_code}"
        except requests.RequestException as e:
            last = str(e)
        time.sleep(delay * (i + 1))
    sys.stderr.write(f"[warn] fetch 실패 {url}: {last}\n")
    return None


def discover_articles(cat_html):
    """카테고리 페이지에서 상품 기사 URL 추출(중복/비상품 제외)."""
    urls = re.findall(r'href="(https://costcome\.com/[a-z0-9][a-z0-9\-]+/)"', cat_html)
    seen, out = set(), []
    for u in urls:
        if u in seen or u.rstrip("/") == BASE.rstrip("/"):
            continue
        if SLUG_DENY.search(u):
            continue
        seen.add(u)
        out.append(u)
    return out


def next_page_url(cat_html):
    """WordPress 카테고리 '다음 페이지' URL. 없으면 None."""
    m = re.search(r'href="(https://costcome\.com/[^"]+/page/\d+/)"', cat_html)
    return m.group(1) if m else None


def _text(htmlstr):
    t = html.unescape(re.sub(r"<[^>]+>", " ", htmlstr))
    return re.sub(r"\s+", " ", t)


def parse_article(htmlstr):
    """기사 HTML → (product_name, costco_price) 또는 None."""
    m = re.search(r"<title>([^<]*)</title>", htmlstr)
    if not m:
        return None
    title = html.unescape(m.group(1)).strip()
    # 위스키 가격 기사만(와인/목록/추천 글 배제)
    # "코스트컴"은 costcome.com 사이트명 — 제목에 사이트명만 있어도 허용
    if "코스트코" not in title and "코스트컴" not in title:
        return None
    if "와인" in title:
        return None
    # 상품명 추출
    if "코스트코" in title:
        # e.g. "발렌타인 17년산 코스트코 할인 가격..." → "발렌타인 17년산"
        name = title.split("코스트코")[0].strip()
        name = re.sub(r"\s+", " ", name).strip(" -·,")
        if len(name) < 2:
            # e.g. "코스트코 벨즈 블렌디드 위스키 할인..." → 코스트코 뒤에서 추출
            remainder = title.split("코스트코", 1)[1].strip()
            for stop in (" 할인", " 가격", " 특징", " 정리", " -", " 추천"):
                if stop in remainder:
                    remainder = remainder[:remainder.index(stop)]
            name = re.sub(r"\s+", " ", remainder).strip(" -·,")
    else:
        # e.g. "커클랜드 아일레이 싱글몰트 위스키 가격과 특징 정리 - 코스트컴"
        name = re.sub(r"\s*-\s*코스트컴\s*$", "", title).strip()
        for stop in (" 가격", " 특징", " 정리", " 할인", " 추천"):
            if stop in name:
                name = name[:name.index(stop)].strip()
        name = re.sub(r"\s+", " ", name).strip(" -·,")
    if len(name) < 2:
        return None
    if not is_whisky(name, title):  # 코스트코 추천/관련 글(커피머신 등) 누수 차단
        return None

    txt = _text(htmlstr)
    price = None
    # 1순위: "코스트코 ... 정상 판매 가격은 X원에서 Y원으로 (인하)" → '으로' 직전값(현재가)
    p = re.search(r"코스트코[^.]{0,80}?정상\s*판매\s*가격은[^.]*?" + WON + r"\s*원으로", txt)
    if not p:
        # 2순위: 인하 표현 없이 "정상 판매 가격은 X원"
        p = re.search(r"정상\s*판매\s*가격은[^.0-9]{0,20}" + WON + r"\s*원", txt)
    if not p:
        # 3순위: "코스트코" 가 들어간 문장의 첫 가격
        s = re.search(r"코스트코[^.]{0,120}?" + WON + r"\s*원", txt)
        p = s
    if p:
        val = int(p.group(1).replace(",", ""))
        if PRICE_MIN <= val <= PRICE_MAX:
            price = val
    if price is None:
        return None
    return name, price


def load_normalizer():
    """정본 매칭 힌트용(best-effort). 실패해도 수집은 진행."""
    try:
        from scripts.normalize_whisky_name import Normalizer, load_rules
        return Normalizer(load_rules())
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[info] normalizer 비활성({e}); raw 표기만 기록\n")
        return None


def collect(limit=None, sleep=1.0):
    # 페이지네이션: 카테고리 1·2·…페이지를 모두 읽어 기사 URL 수집
    articles, page_url = [], CATEGORY_URL
    while page_url:
        cat = fetch(page_url)
        if not cat:
            if not articles:
                return [], {"error": "category fetch 실패", "articles_seen": 0}
            break
        articles.extend(discover_articles(cat))
        nxt = next_page_url(cat)
        # 무한루프 방지: 다음 URL이 현재와 같거나 최대 10페이지
        if not nxt or nxt == page_url or len(articles) > 200:
            break
        page_url = nxt
        time.sleep(sleep)
    # 중복 제거(여러 페이지에서 같은 슬러그 링크가 반복될 수 있음)
    articles = list(dict.fromkeys(articles))
    if limit:
        articles = articles[:limit]
    norm = load_normalizer()

    rows, ok, miss, quarantined = [], 0, 0, 0
    seen_key = set()
    for u in articles:
        h = fetch(u)
        time.sleep(sleep)
        if not h:
            miss += 1
            continue
        parsed = parse_article(h)
        if not parsed:
            miss += 1
            continue
        name, price = parsed
        # CMPA-177 공통 게이트: 잔패키지/잔세트·번들 노이즈, 비-제품명, 비상식 가격은
        # 수집 단계에서 제외(정규화·리포트와 같은 단일 규칙). 잔값으로 부풀려진 행이
        # 월간 정본 CSV 에 새어들면 동일제품 비교가 망가진다.
        reason = is_quarantined(name, price)
        if reason:
            quarantined += 1
            sys.stderr.write(f"[skip:{reason}] {name} ({price:,}원) {u}\n")
            continue
        key = (name, price)
        if key in seen_key:
            continue
        seen_key.add(key)
        note = f"코스트코 매장가(점포미상), {SOURCE_LABEL} 추적; {u}"
        if norm:
            c = norm.canonicalize(name)
            if c["status"] == "matched":
                note = f"정본={c['id']}({c['name_ko']}); " + note
        rows.append({
            "술이름": name, "가격_KRW": price, "위치": "코스트코",
            "출처": f"WebScrape({SOURCE_LABEL})", "신뢰도": "중", "비고": note,
        })
        ok += 1
    metrics = {
        "source": SOURCE_LABEL,
        "category_url": CATEGORY_URL,
        "articles_seen": len(articles),
        "rows_collected": ok,
        "articles_unparsed": miss,
        "rows_quarantined": quarantined,  # CMPA-177 번들/노이즈 게이트 차단 수
    }
    return rows, metrics


def month_path(month):
    return os.path.join(OUT_DIR, f"{month}.csv")


def append_rows(rows, month, today):
    path = month_path(month)
    import csv
    exists = os.path.exists(path)
    # 중복 방지 키 = (술이름, 가격, 가져온날짜) — CMPA-156:
    # 같은 날 재실행은 멱등(idempotent), 날짜가 다르면 가격 불변이어도 반드시 기록한다.
    have = set()
    if exists:
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if (r.get("위치") or "").strip() == "코스트코":
                    have.add(((r.get("술이름") or "").strip(),
                              (r.get("가격_KRW") or "").strip(),
                              (r.get("가져온날짜") or "").strip()))
    written = 0
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if not exists:
            # utf-8-sig 인코더가 새 파일 첫 write 때 BOM을 자동 기록한다.
            # 여기서 BOM을 또 쓰면 이중 BOM → 첫 컬럼명이 '﻿술이름'이 되어
            # 재실행 시 DictReader 가 술이름을 못 읽어 dedup 실패(중복 append) → 쓰지 않는다.
            w.writerow(SCHEMA)
        for r in rows:
            key = (r["술이름"], str(r["가격_KRW"]), today)
            if key in have:
                continue
            have.add(key)
            w.writerow([r["술이름"], r["가격_KRW"], r["위치"], today,
                        r["출처"], r["신뢰도"], r["비고"]])
            written += 1
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--month", default=None, help="YYYY-MM (기본: 오늘 기준)")
    ap.add_argument("--sleep", type=float, default=1.0)
    args = ap.parse_args()

    today = datetime.date.today().isoformat()
    month = args.month or today[:7]

    rows, metrics = collect(limit=args.limit, sleep=args.sleep)
    print(f"=== costcome 수집: {metrics.get('rows_collected', 0)}행 "
          f"(기사 {metrics.get('articles_seen', 0)}건, 미파싱 {metrics.get('articles_unparsed', 0)}) ===")
    for r in rows:
        print(f"  {r['가격_KRW']:>9,}  {r['술이름']}")

    if args.dry_run:
        print("\n[dry-run] CSV 미수정.")
    else:
        written = append_rows(rows, month, today)
        # 누적되는 월간 정본 파일의 '이번 실행 시점' 상태를 _runs/ 에 날짜 스냅샷
        snap = snapshot(month_path(month), run_date=today)
        metrics["rows_written"] = written
        metrics["month_file"] = f"{month}.csv"
        metrics["collected_date"] = today
        metrics["snapshot"] = os.path.relpath(snap, ROOT) if snap else None
        with open(METRICS, "w", encoding="utf-8") as f:
            json.dump(metrics, f, ensure_ascii=False, indent=2)
        print(f"\n→ {month}.csv 에 신규 {written}행 append (중복 제외). 메트릭: {METRICS}")
        if snap:
            print(f"→ 실행 스냅샷: {os.path.relpath(snap, ROOT)}")


if __name__ == "__main__":
    main()
