#!/usr/bin/env python3
"""롯데면세점 위스키 크롤러 회귀 게이트 — CMPA-647.

네트워크 없이 순수 파서/가드를 검증한다(오프라인 fixture 기반).
실행: python scripts/test_lotte_crawl_gate.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.lotte_dutyfree.crawl_lotte import (  # noqa: E402
    is_dutyfree_listing,
    parse_listing_cards,
    parse_total_count,
    parse_volume_ml,
)
from pipelines.common.whisky_quality import is_undersized_volume  # noqa: E402  CMPA-733

# 실제 searchShopAjax 응답에서 따온 카드 fixture (2026-06 캡처) -------------------
# 카드1: 할인 있음(정상가 price01 + 할인가 price02 + sale% + 원화)
# 카드2: 할인 없음(price01 생략 → 정상가=판매가, 할인 0)
LISTING_HTML = """
<ol id="unitStyleList">
<li>
  <!-- 1. 상품정보 -->
  <a href="javascript:void(0);" class="unit_link" data-prdNo="20000959658"
     onclick=" ga_adltCheckPrdDtlMove(&#39;20000959658&#39;,&#39;20001278582&#39;,&#39;B003&#39;,&#39;Y&#39;);">
    <div class="unit_info">
      <span class="brand"><i class="kor">발베니</i></span>
      <span class="name">발베니 12년 골든럼 캐스크 700ml</span>
    </div>
    <div class="unit_price">
      <span class="price01">&#x0024;80</span>
      <strong class="price02"><th:bock>&#x0024;42.24</th:bock> <i class="sale">47&#x0025;</i></strong>
      <span class="price03">65,273&#xC6D0;</span>
    </div>
  </a>
</li>
<li>
  <!-- 1. 상품정보 -->
  <a href="javascript:void(0);" class="unit_link" data-prdNo="20001000001"
     onclick=" ga_adltCheckPrdDtlMove(&#39;20001000001&#39;,&#39;20009000001&#39;,&#39;B003&#39;,&#39;Y&#39;);">
    <div class="unit_info">
      <span class="brand"><i class="kor">맥캘란</i></span>
      <span class="name">맥캘란 18년 셰리 오크 1L</span>
    </div>
    <div class="unit_price">
      <strong class="price02"><th:bock>&#x0024;500&#x0025;</th:bock></strong>
      <span class="price03">772,000&#xC6D0;</span>
    </div>
  </a>
</li>
</ol>
<script>var x = {"totalCnt":"239","etc":0};</script>
"""


def check(name, cond):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}")
    return cond


def main():
    ok = True

    # §1 용량 파싱
    print("§1 parse_volume_ml")
    ok &= check("700ml", parse_volume_ml("발베니 12년 골든럼 캐스크 700ml") == 700)
    ok &= check("750ML 대문자", parse_volume_ml("JOHNNIE WALKER 750ML") == 750)
    ok &= check("1L", parse_volume_ml("맥캘란 18년 1L") == 1000)
    ok &= check("1.75L", parse_volume_ml("JACK DANIELS 1.75L") == 1750)
    ok &= check("1000ml", parse_volume_ml("글렌피딕 1000ml") == 1000)
    ok &= check("용량없음=None", parse_volume_ml("맥캘란 레어 캐스크") is None)
    ok &= check("빈문자=None", parse_volume_ml("") is None)

    # §2 카드 파싱
    print("§2 parse_listing_cards")
    rows = parse_listing_cards(LISTING_HTML, category="주류/위스키/싱글 몰트")
    ok &= check("2장 파싱", len(rows) == 2)
    r0 = rows[0]
    ok &= check("prdNo", r0["prd_no"] == "20000959658")
    ok &= check("prdOptNo", r0["prd_opt_no"] == "20001278582")
    ok &= check("한글명", r0["name"] == "발베니 12년 골든럼 캐스크 700ml")
    ok &= check("브랜드", r0["brand"] == "발베니")
    ok &= check("정상가 80", r0["regular_price"] == 80.0)
    ok &= check("판매가 42.24", r0["sale_price"] == 42.24)
    ok &= check("할인율 47", r0["discount_pct"] == 47.0)
    ok &= check("통화 USD", r0["currency"] == "USD")
    ok &= check("원화 65273", r0["krw_price"] == "65273")
    ok &= check("카테고리", r0["category"] == "주류/위스키/싱글 몰트")

    # §3 할인 없는 카드 → 정상가=판매가, 할인 0
    print("§3 할인 없는 카드")
    r1 = rows[1]
    ok &= check("정상가=판매가 500", r1["regular_price"] == 500.0 and r1["sale_price"] == 500.0)
    ok &= check("할인율 0", r1["discount_pct"] == 0.0)

    # §4 빈 HTML → 0장
    print("§4 빈 응답")
    ok &= check("0장", parse_listing_cards("<div>nothing</div>") == [])

    # §5 totalCnt
    print("§5 parse_total_count")
    ok &= check("totalCnt 239", parse_total_count(LISTING_HTML) == 239)
    ok &= check("없으면 None", parse_total_count("<div/>") is None)

    # §6 면세 가드 (CMPA-321)
    print("§6 is_dutyfree_listing — 항상 True (면세 소스)")
    ok &= check("항상 면세", is_dutyfree_listing({"prd_no": "x", "sale_price": 42.24}))

    # §7 소용량 수집 금지 (CMPA-733)
    print("§7 is_undersized_volume — 500ml 미만 차단")
    ok &= check("200ml 차단", is_undersized_volume(200) is True)
    ok &= check("375ml 차단", is_undersized_volume(375) is True)
    ok &= check("499ml 차단", is_undersized_volume(499) is True)
    ok &= check("500ml 허용", is_undersized_volume(500) is False)
    ok &= check("700ml 허용", is_undersized_volume(700) is False)
    ok &= check("1000ml 허용", is_undersized_volume(1000) is False)
    ok &= check("None 판정불가=허용", is_undersized_volume(None) is False)

    print("\n" + ("ALL PASS ✅" if ok else "FAILURES ❌"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
