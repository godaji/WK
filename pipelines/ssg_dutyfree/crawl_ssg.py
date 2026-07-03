#!/usr/bin/env python3
"""신세계(SSG)면세점(ssgdfs.com) 위스키 카탈로그 크롤러 — CMPA-652.

**수집 방법(부모 CMPA-651 수집가능성 검토, CMO):**
ssgdfs.com 은 ``_fec_sbu`` 안티봇 WAF 뒤에 있어 curl·기본 헤들리스(`--headless`)는
**406/차단 페이지**로 막힌다. 단, 헤들리스 크롬을
``--headless=new --disable-blink-features=AutomationControlled`` 로 띄우면 WAF를 통과한다.

WAF만 통과하면 카테고리 상품 리스트 AJAX
``GET /kr/search/getSearchGoodsList`` 가 상품 카드 HTML 을 **서버 렌더로** 돌려준다.
카드 안에 한글 상품명·브랜드·정가($)·할인가($)·할인율(%)·원화환산가가 모두 인라인으로
박혀 있어(롯데 ``searchShopAjax`` 와 동일 구조) 상품별 추가 호출이 불필요하다.

위스키 = 주류(`/kr/dispctg/ctg/liquor`) > **위스키 카테고리 ``disp_ctg_no=2306012486``**.
페이지는 ``listCount=40`` 단위로 나뉘고 ``startCount=(page-1)*40`` 로 페이지네이션한다
(2026-06 기준 19 페이지 ≈ 731종 — 1차 페인트 40 ≠ 전체, 롯데 24→411 선례와 동일).

⚠️ **하네스 제약(headless-browser-verify-recipe / CMPA-557):** 백그라운드 chrome 이나
   ``--remote-debugging-port`` (CDP)은 하네스가 exit 144 로 죽인다. 그래서 CDP/네트워크
   인터셉트 대신 **포그라운드 단발 ``--dump-dom`` 호출**로 HTML 을 받아 정규식 파싱한다.

⚠️ **면세가 가드(CMPA-321):** 가격은 전부 **면세가**(세금 0·출국 조건, USD 1차 신호)다.
   국내 최저가로 쓰면 안 된다. ``is_dutyfree_listing()`` 가 모든 행을 면세로 표시하고
   CSV ``is_dutyfree=True``. 향후 대시보드/리포트는 신라·롯데 면세와 동일 취급.

⚠️ **WAF 깨짐 리스크(신뢰도 중):** ``_fec_sbu`` 가 탐지 룰을 강화하면 우회 플래그가 막힐 수
   있다. 0건 수집 시 **exit 1 + stderr 경보**(루틴 실패 알림 트리거). 회귀 가드 =
   ``scripts/test_ssg_crawl_gate.py`` (네트워크 없는 순수 파서 검증).

출력 CSV: ``assets/ssg_dutyfree/YYYY-MM_ssg_whisky.csv`` (+ ``snapshots/YYYY-MM-DD_…``)
  컬럼(롯데 스키마 호환 — canonical_id 조인/매처 재사용용):
    goos_cd, name, brand, volume_ml, regular_price, sale_price, discount_pct,
    currency, krw_price, l_cate, category, is_dutyfree, exch_rate, source, collected_at

헤들리스 크롬 셋업(레시피 = headless-browser-verify-recipe):
  바이너리는 환경변수 ``SSG_CHROME_BIN`` 로 지정(기본=playwright 캐시 chrome-headless-shell).
  누락 시스템 libs(libnspr4/libnss3/libasound2t64)는 ``SSG_CHROME_LD_PATH`` 로 추가
  (기본=/tmp/pwlibs/extracted/...). sudo 없이 ``apt-get download`` → Node24 zstd 추출.

사용:
  python -m pipelines.ssg_dutyfree.crawl_ssg            # 전체 위스키 → CSV
  python -m pipelines.ssg_dutyfree.crawl_ssg --dry-run  # CSV 안 쓰고 요약만
  python -m pipelines.ssg_dutyfree.crawl_ssg --limit 80 # 앞 N종(점검)
"""
from __future__ import annotations

import argparse
import csv
import html
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

BASE = "https://www.ssgdfs.com"
LANDING_URL = f"{BASE}/kr/dispctg/ctg/liquor"
LIST_URL = f"{BASE}/kr/search/getSearchGoodsList"
WHISKY_DISP_CTG_NO = "2306012486"     # 주류 > 위스키
PAGE_SIZE = 40                        # data-list-count (PC chnl_cd=10)
SAFETY_MAX_PAGES = 80                 # 폭주 방지(=3200종 상한)

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
# WAF 통과 핵심 플래그. headless=new + 자동화 탐지 끄기(CMPA-651 검증).
CHROME_FLAGS = [
    "--headless=new", "--no-sandbox", "--disable-gpu",
    "--disable-blink-features=AutomationControlled", "--lang=ko-KR",
    f"--user-agent={CHROME_UA}",
]
DEFAULT_CHROME_BIN = str(
    Path.home() / ".cache/ms-playwright/chromium_headless_shell-1223"
    "/chrome-headless-shell-linux64/chrome-headless-shell"
)
DEFAULT_LD_PATH = "/tmp/pwlibs/extracted/usr/lib/x86_64-linux-gnu"

ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "ssg_dutyfree"

CSV_COLUMNS = [
    "goos_cd", "name", "brand", "volume_ml",
    "regular_price", "sale_price", "discount_pct", "currency", "krw_price",
    "l_cate", "category", "is_dutyfree", "exch_rate", "source", "collected_at",
]
SOURCE = "신세계(SSG)면세"


# --------------------------------------------------------------------------- #
# 순수 파서 (네트워크 무관 — 단위 테스트 대상)
# --------------------------------------------------------------------------- #
def parse_volume_ml(name: str) -> int | None:
    """상품명에서 용량(ml)을 파싱. 700ml / 750ML / 1L / 1.75L / 1000ml 등 지원."""
    if not name:
        return None
    s = name.upper().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*ML", s)
    if m:
        try:
            return int(round(float(m.group(1))))
        except ValueError:
            return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*L(?![A-Z])", s)
    if m:
        try:
            return int(round(float(m.group(1)) * 1000))
        except ValueError:
            return None
    return None


def is_dutyfree_listing(row: dict) -> bool:
    """CMPA-321 가드. SSG면세 수집물은 정의상 전부 면세 리스팅이라 항상 True.

    국내 최저가 파이프라인이 실수로 면세가를 섞지 않도록 모든 행을 면세로 표시한다
    (신라면세 ``service_type==5`` · 롯데면세와 동등한 자가완결 신호).
    """
    return True


def _amt(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def _grab(card: str, pat: str) -> str | None:
    m = re.search(pat, card, re.S)
    return html.unescape(m.group(1).strip()) if m else None


def parse_cards(html_text: str, category: str = "") -> list[dict]:
    """``getSearchGoodsList`` 응답 HTML 의 상품 카드(``<li class="prodCont">``)를 파싱.

    각 카드에서:
      - goos_cd(상품코드)·한글 상품명·브랜드·대분류(liquor)·중분류(whisky)
        → ``data-ga4_param2/1/5/3/4`` (서버가 카드 ``<a>`` 에 인라인으로 박아둠)
      - 할인율(``strong.saleNum b`` %)·정가(``span.originPrice`` $, 할인 없으면 생략)
      - 할인가(``strong.saleDollar`` $, 항상 존재)·원화환산가(``em.saleWon`` 원)
    """
    rows: list[dict] = []
    cards = re.split(r'<li class="prodCont', html_text)[1:]
    for c in cards:
        goos = _grab(c, r'data-ga4_param2="([^"]*)"')
        if not goos:
            continue
        name = _grab(c, r'data-ga4_param1="([^"]*)"') \
            or _grab(c, r'class="prodName">(.*?)</em>')
        brand = _grab(c, r'data-ga4_param5="([^"]*)"') \
            or _grab(c, r'class="brandName">(.*?)</span>')
        l_cate = _grab(c, r'data-ga4_param3="([^"]*)"') or ""
        m_cate = _grab(c, r'data-ga4_param4="([^"]*)"') or ""

        sale = _amt(_grab(c, r'class="saleDollar"[^>]*>\$?([\d,.]+)'))
        regular = _amt(_grab(c, r'class="originPrice"[^>]*>\$?([\d,.]+)'))
        krw = _grab(c, r'class="saleWon"[^>]*>([\d,]+)')
        m_dc = _grab(c, r'class="saleNum"><b>(\d+)</b>')

        if regular is None:           # 할인 없는 상품 → 정상가=판매가
            regular = sale
        if m_dc is not None:
            discount = float(m_dc)
        elif regular and sale and sale < regular:
            discount = round((regular - sale) / regular * 100, 1)
        else:
            discount = 0.0

        rows.append({
            "goos_cd": goos,
            "name": name or "",
            "brand": brand or "",
            "regular_price": regular,
            "sale_price": sale,
            "discount_pct": discount,
            "currency": "USD",
            "krw_price": krw.replace(",", "") if krw else "",
            "l_cate": l_cate,
            "category": category or m_cate,
        })
    return rows


def parse_max_page(html_text: str) -> int | None:
    """``#goosPaging`` 의 페이지 번호(``data-value``) 최댓값. 없으면 None."""
    pg = re.search(r'id="goosPaging".*?</div>', html_text, re.S)
    scope = pg.group(0) if pg else html_text
    vals = [int(x) for x in re.findall(r'data-value="(\d+)"', scope)]
    return max(vals) if vals else None


def parse_exchange_rate(html_text: str) -> str | None:
    """랜딩 페이지 config 의 환율(``exchange_rate":"1545.3"``). 없으면 None."""
    m = re.search(r'exchange_rate"\s*:\s*"([\d.]+)"', html_text)
    return m.group(1) if m else None


def is_blocked(html_text: str) -> bool:
    """WAF 차단/연결오류 페이지인지(상품 마커 부재 + 차단 문구)."""
    if "prodCont" in html_text or "goosList" in html_text:
        return False
    return bool(re.search(r"연결에 문제|_fec_sbu|잠시", html_text))


# --------------------------------------------------------------------------- #
# 네트워크 (포그라운드 단발 헤들리스 크롬 — CDP/백그라운드 금지)
# --------------------------------------------------------------------------- #
_REQUIRED_DEBS = ["libnspr4", "libnss3", "libasound2t64"]
_DEB_STAGING = Path("/tmp/pwlibs/debs")
_LIB_ROOT    = Path("/tmp/pwlibs/extracted")


def _ensure_chrome_libs(ld_path: str) -> None:
    """libnspr4.so 가 없으면 apt-get download + Node24 zstd 추출로 자동 복구.

    /tmp 재시작(컨테이너 리부트) 시 /tmp/pwlibs 가 날아가도 다음 번 실행에
    자동 복구된다. sudo 불필요(apt-get download + ar x + Node zstd).
    """
    sentinel = Path(ld_path) / "libnspr4.so"
    if sentinel.exists():
        return

    print("  [chrome-libs] /tmp/pwlibs 소실 감지 → 자동 복구 시작", file=sys.stderr)
    _DEB_STAGING.mkdir(parents=True, exist_ok=True)
    _LIB_ROOT.mkdir(parents=True, exist_ok=True)

    # 1) apt-get download (네트워크 필요, ~2MB)
    subprocess.run(
        ["apt-get", "download", *_REQUIRED_DEBS],
        cwd=str(_DEB_STAGING), capture_output=True, check=False,
    )

    # 2) ar x + Node24 zstd 로 data.tar.zst 추출
    node = "node"
    for deb in _DEB_STAGING.glob("*.deb"):
        tmp = Path("/tmp") / f"pwdeb_{deb.stem}"
        tmp.mkdir(exist_ok=True)
        subprocess.run(["ar", "x", str(deb), "--output", str(tmp)],
                       capture_output=True, check=False)
        data_zst = tmp / "data.tar.zst"
        if not data_zst.exists():
            continue
        # Node 24 has native zstd via zlib.zstdDecompressSync
        js = (
            "const fs=require('fs'),zlib=require('zlib');"
            f"const buf=fs.readFileSync('{data_zst}');"
            f"fs.writeFileSync('{tmp}/data.tar',zlib.zstdDecompressSync(buf));"
        )
        r = subprocess.run([node, "-e", js], capture_output=True, check=False)
        if r.returncode == 0 and (tmp / "data.tar").exists():
            subprocess.run(["tar", "xf", str(tmp / "data.tar"),
                            "-C", str(_LIB_ROOT)],
                           capture_output=True, check=False)

    if sentinel.exists():
        print("  [chrome-libs] 복구 완료", file=sys.stderr)
    else:
        print("  [chrome-libs] 복구 실패 — SSG_CHROME_LD_PATH 를 수동으로 설정하세요",
              file=sys.stderr)


def _chrome_env() -> dict:
    env = dict(os.environ)
    # ⚠️ npm/postgres 의 불량 liblzma 가 섞이지 않도록 LD_LIBRARY_PATH 를 완전 교체.
    extra = os.environ.get("SSG_CHROME_LD_PATH", DEFAULT_LD_PATH)
    _ensure_chrome_libs(extra)
    env["LD_LIBRARY_PATH"] = extra
    return env


def fetch_via_chrome(url: str, budget_ms: int = 6000,
                     timeout_s: int = 60) -> str:
    """포그라운드 단발 ``--dump-dom`` 으로 URL 의 렌더 HTML 을 받아 반환."""
    chrome = os.environ.get("SSG_CHROME_BIN", DEFAULT_CHROME_BIN)
    cmd = [chrome, *CHROME_FLAGS,
           f"--virtual-time-budget={budget_ms}", "--dump-dom", url]
    p = subprocess.run(cmd, capture_output=True, text=True,
                       timeout=timeout_s, env=_chrome_env())
    return p.stdout or ""


def fetch_list_page(start: int, budget_ms: int = 6000,
                    retries: int = 1) -> str:
    url = (f"{LIST_URL}?searchType=CATEGORY&disp_ctg_no={WHISKY_DISP_CTG_NO}"
           f"&startCount={start}&listCount={PAGE_SIZE}")
    for attempt in range(retries + 1):
        html_text = fetch_via_chrome(url, budget_ms=budget_ms)
        if "prodCont" in html_text or not is_blocked(html_text):
            return html_text
        if attempt < retries:
            print(f"  [retry] startCount={start} WAF/빈응답 재시도", file=sys.stderr)
            time.sleep(2.0)
    return html_text


def _pace(sec: float = 0.8) -> None:
    time.sleep(sec)


# --------------------------------------------------------------------------- #
# 오케스트레이션
# --------------------------------------------------------------------------- #
def crawl(limit: int | None = None, pace: bool = True,
          budget_ms: int = 6000) -> list[dict]:
    """위스키 카테고리 전체를 페이지네이션하며 수집 → goos_cd 중복 제거 후 반환."""
    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # 워밍업(쿠키/WAF) 겸 환율 파싱
    exch_rate = ""
    try:
        landing = fetch_via_chrome(LANDING_URL, budget_ms=budget_ms)
        exch_rate = parse_exchange_rate(landing) or ""
    except Exception as e:  # noqa: BLE001
        print(f"  [경고] 랜딩/환율 조회 실패: {e}", file=sys.stderr)

    seen: set[str] = set()
    out: list[dict] = []
    page = 0
    max_page_seen = None
    while page < SAFETY_MAX_PAGES:
        start = page * PAGE_SIZE
        html_text = fetch_list_page(start, budget_ms=budget_ms)
        cards = parse_cards(html_text, category="주류/위스키")
        mp = parse_max_page(html_text)
        if mp:
            max_page_seen = mp
        got = len(cards)
        print(f"  [위스키] page {page+1}"
              f"{'/' + str(max_page_seen) if max_page_seen else ''}"
              f"  {start+got}종 (이번 {got})")
        for r in cards:
            if not r["goos_cd"] or r["goos_cd"] in seen:
                continue
            if not r["sale_price"]:
                print(f"  - 가격없음 스킵: {r['goos_cd']} {r['name']}",
                      file=sys.stderr)
                continue
            seen.add(r["goos_cd"])
            vol = parse_volume_ml(r["name"])
            if vol is not None and vol < 500:  # CMPA-733: 500ml 미만 소용량 수집 금지
                print(f"  - 소용량 스킵({vol}ml): {r['name']}", file=sys.stderr)
                continue
            r["volume_ml"] = vol
            r["is_dutyfree"] = True
            r["exch_rate"] = exch_rate
            r["source"] = SOURCE
            r["collected_at"] = collected_at
            assert is_dutyfree_listing(r)  # CMPA-321 가드
            out.append(r)
        if got < PAGE_SIZE or (limit and len(out) >= limit):
            break
        page += 1
        if pace:
            _pace()
    if limit:
        out = out[:limit]
    print(f"[완료] 위스키 {len(out)}종(중복 제거)")
    return out


def _write_one(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_COLUMNS})
    return path


def write_csv(rows: list[dict], path: Path | None = None,
              snapshot: bool = True) -> Path:
    """월별 'latest' CSV + 날짜별 스냅샷을 함께 기록(CMPA-156 누적 기록).

    '오늘부터 매일 수집' 시 각 수집일을 보존하기 위해
    ``snapshots/YYYY-MM-DD_ssg_whisky.csv`` 를 남긴다. 월별 파일은 최신값이며 각 행의
    ``collected_at`` 으로 수집 시점을 알 수 있다.
    """
    if path is None:
        ym = date.today().strftime("%Y-%m")
        path = ASSET_DIR / f"{ym}_ssg_whisky.csv"
    _write_one(rows, path)
    if snapshot:
        snap = ASSET_DIR / "snapshots" / f"{date.today():%Y-%m-%d}_ssg_whisky.csv"
        _write_one(rows, snap)
        print(f"스냅샷 기록: {snap}")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="신세계(SSG)면세점 위스키 크롤러 (CMPA-652)")
    ap.add_argument("--limit", type=int, default=None, help="앞 N종만(점검용)")
    ap.add_argument("--no-pace", action="store_true", help="요청 간 딜레이 끄기")
    ap.add_argument("--dry-run", action="store_true", help="CSV 안 쓰고 요약만")
    ap.add_argument("--budget", type=int, default=6000,
                    help="virtual-time-budget(ms), WAF 느릴 때 상향")
    ap.add_argument("--out", type=str, default=None, help="출력 CSV 경로 직접 지정")
    args = ap.parse_args(argv)

    rows = crawl(limit=args.limit, pace=not args.no_pace, budget_ms=args.budget)
    if not rows:
        # WAF 깨짐/사이트 구조 변경 경보 (루틴 실패 알림 트리거)
        print("수집 0건 — _fec_sbu WAF 차단 또는 사이트 구조 변경 가능성. 보고 필요.",
              file=sys.stderr)
        return 1
    n_null = sum(1 for r in rows if not r["sale_price"])
    n_vol = sum(1 for r in rows if r["volume_ml"])
    n_dc = sum(1 for r in rows if r["discount_pct"])
    n_krw = sum(1 for r in rows if r["krw_price"])
    print(f"\n검증: 행 {len(rows)} / 가격(USD)null {n_null}"
          f" / 원화있음 {n_krw} / 용량파싱 {n_vol} ({n_vol/len(rows)*100:.0f}%)"
          f" / 할인표기 {n_dc}")
    if args.dry_run:
        print("[dry-run] CSV 미기록")
        return 0
    out = write_csv(rows, Path(args.out) if args.out else None)
    print(f"CSV 기록: {out} ({len(rows)}행)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
