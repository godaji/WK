#!/usr/bin/env python3
"""신세계(SSG)면세점 위스키 크롤러 회귀 게이트 — CMPA-652.

네트워크 없이 순수 파서/가드를 검증한다(오프라인 fixture 기반).
fixture 는 실제 ``getSearchGoodsList`` 응답(2026-06-28 캡처)의 카드/페이징 구조를
그대로 축약한 것이다.
실행: python scripts/test_ssg_crawl_gate.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.ssg_dutyfree.crawl_ssg import (  # noqa: E402
    is_blocked,
    is_dutyfree_listing,
    parse_cards,
    parse_exchange_rate,
    parse_max_page,
    parse_volume_ml,
)
from pipelines.common.whisky_quality import is_undersized_volume  # noqa: E402  CMPA-733

# 실제 응답 구조 축약 fixture --------------------------------------------------
# 카드1: 할인 있음(saleNum % + originPrice $ + saleDollar $ + saleWon 원)
# 카드2: 할인 없음(originPrice/saleNum 생략 → 정상가=판매가, 할인 0)
LIST_HTML = """
<ul id="goosList">
<li class="prodCont flagRenewal badgeProd prodAge sizeL">
  <a href="javascript:void(0);" role="button"
     data-ga4_param1="발렌타인 30년 700ml" data-ga4_param2="102488000001"
     data-ga4_param3="liquor" data-ga4_param4="whisky" data-ga4_param5="발렌타인"
     data-ga4_param6="690749">
    <span class="prodInfo"><span class="brandName">발렌타인</span>
    <em class="prodName">발렌타인 30년 700ml</em>
    <span class="priceArea"><span class="saleCont"><span class="priceWrap">
    <strong class="saleNum"><b>30</b>%</strong>
    <span class="originPrice" aria-label="정가">$447</span></span>
    <strong class="saleDollar" aria-label="할인가 미화">$312.9</strong>
    <em class="saleWon" aria-label="할인가 원화">483,524<span>원</span></em>
    </span></span></span>
  </a>
</li>
<li class="prodCont badgeProd prodAge sizeL">
  <a href="javascript:void(0);" role="button"
     data-ga4_param1="브룩라디 옥토모어 15.3 700ml" data-ga4_param2="106858000011"
     data-ga4_param3="liquor" data-ga4_param4="whisky" data-ga4_param5="브룩라디"
     data-ga4_param6="350783">
    <span class="prodInfo"><span class="brandName">브룩라디</span>
    <em class="prodName">브룩라디 옥토모어 15.3 700ml</em>
    <span class="priceArea"><span class="saleCont"><span class="priceWrap">
    </span><strong class="saleDollar" aria-label="할인가 미화">$230</strong>
    <em class="saleWon" aria-label="할인가 원화">355,419<span>원</span></em>
    </span></span></span>
  </a>
</li>
</ul>
<div class="listPaging" id="goosPaging">
  <a class="num on" data-current="true" data-value="1">1</a>
  <a class="num" data-value="2">2</a>
  <a class="num" data-value="10"><button class="next">다음 리스트</button></a>
  <a class="num" data-value="19">19</a>
</div>
"""

BLOCK_HTML = '<html><body>잠시 연결에 문제가 발생했습니다. _fec_sbu</body></html>'
LANDING_HTML = '<script>var g={"exchange_rate":"1545.3","cookie_domain":"x"};</script>'


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    return cond


def main():
    ok = True

    # §1 용량 파싱
    print("§1 parse_volume_ml")
    ok &= check("700ml", parse_volume_ml("발렌타인 30년 700ml") == 700)
    ok &= check("750ML 대문자", parse_volume_ml("JW BLUE 750ML") == 750)
    ok &= check("1L", parse_volume_ml("카발란 솔리스트 1L") == 1000)
    ok &= check("1.75L", parse_volume_ml("JACK DANIELS 1.75L") == 1750)
    ok &= check("1000ml", parse_volume_ml("카발란 비노바리끄 솔리스트 1000ml") == 1000)
    ok &= check("용량없음=None", parse_volume_ml("맥캘란 레어 캐스크") is None)
    ok &= check("빈문자=None", parse_volume_ml("") is None)

    # §2 카드 파싱 (할인 있음)
    print("§2 parse_cards — 할인 카드")
    rows = parse_cards(LIST_HTML, category="주류/위스키")
    ok &= check("2장 파싱", len(rows) == 2)
    r0 = rows[0]
    ok &= check("goos_cd", r0["goos_cd"] == "102488000001")
    ok &= check("한글명", r0["name"] == "발렌타인 30년 700ml")
    ok &= check("브랜드", r0["brand"] == "발렌타인")
    ok &= check("정가 447", r0["regular_price"] == 447.0)
    ok &= check("할인가 312.9", r0["sale_price"] == 312.9)
    ok &= check("할인율 30", r0["discount_pct"] == 30.0)
    ok &= check("통화 USD", r0["currency"] == "USD")
    ok &= check("원화 483524", r0["krw_price"] == "483524")
    ok &= check("대분류 liquor", r0["l_cate"] == "liquor")
    ok &= check("카테고리 고정", r0["category"] == "주류/위스키")

    # §3 할인 없는 카드 → 정상가=판매가, 할인 0
    print("§3 할인 없는 카드")
    r1 = rows[1]
    ok &= check("정상가=판매가 230", r1["regular_price"] == 230.0 and r1["sale_price"] == 230.0)
    ok &= check("할인율 0", r1["discount_pct"] == 0.0)

    # §4 빈 HTML → 0장
    print("§4 빈 응답")
    ok &= check("0장", parse_cards("<div>nothing</div>") == [])

    # §5 페이지 최댓값
    print("§5 parse_max_page")
    ok &= check("max page 19", parse_max_page(LIST_HTML) == 19)
    ok &= check("없으면 None", parse_max_page("<div/>") is None)

    # §6 환율 파싱
    print("§6 parse_exchange_rate")
    ok &= check("환율 1545.3", parse_exchange_rate(LANDING_HTML) == "1545.3")
    ok &= check("없으면 None", parse_exchange_rate("<div/>") is None)

    # §7 WAF 차단 감지
    print("§7 is_blocked — WAF 깨짐 가드")
    ok &= check("차단 페이지 True", is_blocked(BLOCK_HTML) is True)
    ok &= check("정상 응답 False", is_blocked(LIST_HTML) is False)

    # §8 면세 가드 (CMPA-321)
    print("§8 is_dutyfree_listing — 항상 True (면세 소스)")
    ok &= check("항상 면세", is_dutyfree_listing({"goos_cd": "x", "sale_price": 312.9}))

    # §9 소용량 수집 금지 (CMPA-733)
    print("§9 is_undersized_volume — 500ml 미만 차단")
    ok &= check("200ml 차단", is_undersized_volume(200) is True)
    ok &= check("375ml 차단", is_undersized_volume(375) is True)
    ok &= check("499ml 차단", is_undersized_volume(499) is True)
    ok &= check("500ml 허용", is_undersized_volume(500) is False)
    ok &= check("700ml 허용", is_undersized_volume(700) is False)
    ok &= check("None 판정불가=허용", is_undersized_volume(None) is False)

    print("\n" + ("ALL PASS ✅" if ok else "FAILURES ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
