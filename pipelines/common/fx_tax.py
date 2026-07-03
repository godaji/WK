"""
국가 공통 환율 · 한국 반입세 정규화 컴포넌트 (country-agnostic).

CMPA-11(일본 Rakuten) POC에서 추출. 도착국(한국) 세금 cascade는 원산지와 무관하게
동일하므로, 국가별로 바뀌는 것은 '현지통화 → KRW 환산'(FX)뿐이다.
CMPA-13(대만)·CMPA-14(홍콩) 파이프라인이 그대로 import 해 재사용한다.

API:
  to_krw(amount, fx)            -> KRW (float)
  import_landed_cost(cif_krw)   -> dict(cif/customs/liquor/education/vat/landed_total/multiplier)
  KR_TAX                        -> 세율 상수 (한 곳에서만 정의)

한국 위스키(증류주) 개인 반입 추정 — 누적식(cascading):
  관세    = CIF * 20%
  주세    = (CIF + 관세) * 72%
  교육세  = 주세 * 30%
  부가세  = (CIF + 관세 + 주세 + 교육세) * 10%
  반입가  = 위 전부 합   (관세20 기준 유효배수 ≈ 2.5555x)

주의(POC 단순화): CIF(과세표준)를 '현지가 KRW 환산'으로 둔다. 실제 CIF는 운임·보험이
더해지고, 개인 면세한도(2병·2L·USD400)는 미적용 — 산식 sanity check / 가격비교 용도.
"""
from __future__ import annotations

# 세율은 단일 출처. FTA 0% 시나리오 등은 customs 율만 교체해 재사용.
KR_TAX = {"customs": 0.20, "liquor": 0.72, "education": 0.30, "vat": 0.10}


def to_krw(amount: float, fx: float) -> float:
    """현지통화 금액 -> KRW (1단위당 환율 fx)."""
    return amount * fx


def import_landed_cost(cif_krw: float, tax=KR_TAX) -> dict:
    customs = cif_krw * tax["customs"]
    liquor = (cif_krw + customs) * tax["liquor"]
    education = liquor * tax["education"]
    vat = (cif_krw + customs + liquor + education) * tax["vat"]
    total = cif_krw + customs + liquor + education + vat
    return {
        "cif": round(cif_krw),
        "customs": round(customs),
        "liquor": round(liquor),
        "education": round(education),
        "vat": round(vat),
        "landed_total": round(total),
        "multiplier": round(total / cif_krw, 4) if cif_krw else None,
    }
