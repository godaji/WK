# -*- coding: utf-8 -*-
"""source_floor — '소스(매장)별 최신가' 국내최저(floor) 계산 공용 헬퍼 (CMPA-496 보드).

문제(검증됨): 트레이더스/코스트코처럼 **가격을 전 지점 동일하게 오르내리는** 소스는, 새
관측이 들어오면 같은 소스의 옛 관측은 무효(superseded)가 된다. 그런데 floor 를 '기간 내
단순 min()' 으로 잡으면 이미 사라진 옛 저가를 국내최저로 집어 **가격 인상을 인하처럼**
보이게 한다(예: 글렌글라사 포트소이 w030 — 트레이더스 89,800(05-27) → 109,800(06-09)
인데 floor=89,800 으로 표기, 현재가 109,800 과 모순).

규칙(보드 CMPA-495/496):
  1. floor = **소스(매장)별 '최신 관측가' 중 최소값**. 같은 소스의 과거 관측은 더 싸도 무시.
  2. floor 소스의 **직전가**(직전 distinct 수집일의 가격)를 함께 돌려준다 → 방향(▲/▼) 표기용.
  3. 타 매장(데일리샷·코스트코)도 각자 최신가 기준(현행 의미 유지·기준 통일).

⚠️ 데이터 관리 원칙(CMPA-156): 과거 관측 행을 **삭제하지 않는다**. floor 선택 로직에서만
소스별 최신가를 고른다. 누적 기록은 그대로 보존된다.
"""


def per_source_latest_floor(observations):
    """소스별 최신가 floor.

    observations: iterable of ``(source, date, price)``
      · source = 매장/소스 키(예: '트레이더스', '코스트코', '데일리샷'). 같은 소스의
        지점(branch)은 가격이 동일하게 움직이므로 **하나의 source 키로 합쳐서** 넘겨라.
      · date   = 'YYYY-MM-DD' 수집일 문자열(사전식 정렬 가능). 빈값은 가장 오래된 것으로 취급.
      · price  = int/float 가격(None 은 무시).

    반환: ``(floor_price, floor_source, prev_price)`` 또는 관측이 없으면 ``None``.
      · floor_price  = 소스별 최신가 중 최소값.
      · floor_source = 그 최소값을 낸 소스.
      · prev_price   = floor_source 의 **직전 distinct 수집일** 가격(없으면 None). 방향 표기용.
    """
    by_src = {}                                  # source -> {date: 그 날의 최저가}
    for src, date, price in observations:
        if price is None:
            continue
        d = "" if date is None else str(date)
        slot = by_src.setdefault(src, {})
        if d not in slot or price < slot[d]:
            slot[d] = price                      # 같은 소스·같은 날 여러 가격이면 최저(보수)
    best = None                                  # (price, source, prev)
    for src, slot in by_src.items():
        dates = sorted(slot)                     # 오름차순(빈 날짜가 가장 오래된 것)
        latest = dates[-1]
        latest_price = slot[latest]
        prev_price = slot[dates[-2]] if len(dates) >= 2 else None
        if best is None or latest_price < best[0]:
            best = (latest_price, src, prev_price)
    return best
