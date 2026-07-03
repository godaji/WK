#!/usr/bin/env python3
"""CMPA-32 위스키 가격 리포트(md) 생성기 — 루틴화용 버튼.

정규화된 가격 CSV(data/whisky-prices/)만 들어오면 전체 리포트를 한 번에 생성한다.
  - [1] 핵심표: 최저가·매력도·과거평균比·데일리샷대비  (whisky_report_tables.build_domestic)
  - [2] 해외(홍콩) 면세 비교                           (whisky_report_tables.build_overseas)
  - 부록: 매력도 공식·데이터 처리 방법(정적 설명)

출력(CMPA-45 — 최종 산출물은 정본 자체가 날짜 포함):
  reports/whisky-price/{YYYY-MM}_위스키가격리포트_{run-date}.md   ← 기본 단일 산출물(정본, 덮어쓰기 금지·주간 누적)
  reports/whisky-price/{YYYY-MM}_위스키가격리포트_latest.md         ← `--latest` 줄 때만(편의 포인터, 기본 끔)
  - 제목 = 데이터 기준일, 부제 = 리포트 생성일(KST).
  - 보드 지적(파일 수 최소화): 기본 실행은 MD 1개만. HTML은 별도(md_to_html, on-demand),
    공개 배포본도 별도(make_distribution, 배포 시점 게이트). 정기 실행이 7개씩 쏟아내지 않는다.
  - 같은 날 재실행은 그 날짜 파일을 덮어써(날짜 단위 멱등), 다른 날 실행은 새 파일로 누적.
  - 중간 데이터 CSV는 정본(월)=latest + _runs/ 스냅샷(CMPA-38)이지만, 사람이 보는 최종
    리포트/배포물은 다운스트림 하드코딩이 없으므로 '정본 파일명 자체에 실행일'을 박는다.

데이터 기준일 = 현재월 CSV에서 '실질 스크랩'이 있었던 가장 최근 날짜
  (관측 ≥ MIN_OBS 인 날짜 중 최신; 없으면 전체 최신). 소수의 보강행(예: WebSearch 3건)은
  기준일을 흔들지 않게 한다. --data-date 로 수동 고정 가능.

사용:
  python3 scripts/generate_report.py                       # 오늘 생성일, 자동 기준일 → 날짜박힌 정본 1개
  python3 scripts/generate_report.py --data-date 2026-05-27 --gen-date 2026-05-30
  python3 scripts/generate_report.py --latest              # _latest.md 편의 포인터도 추가
"""
import argparse, csv, json, os, re, shutil, sys
from collections import Counter
from datetime import datetime

import whisky_report_tables as W
import kr_jp_compare as JP  # CMPA-53: 한↔일 비교(홍콩표 옆 상설 섹션)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

REPORTS = os.path.join(ROOT, "reports", "whisky-price")  # CMPA-88: reports/whisky-price 로 정리
MIN_OBS = 10  # '실질 스크랩일' 판정 임계(이보다 적은 날은 보강행으로 보고 기준일에서 제외)

# ── CMPA-265: 데이터 변동 지문 게이트(생성 단계) ────────────────────────────────
# 보드 지시(CMPA-263): "데이터 변동이 없어도 리포트를 새로 만든다 → 변동이 있을 때만 만든다."
# '데이터 변동'의 결정론 정의는 **단일 진실원천** scripts/whisky_blog_gate.py 의
# report_signature()/fingerprint()(CMPA-251)를 그대로 재사용한다(두 번째 정의 신설 금지).
# 생성 게이트 상태파일은 발행 게이트(_blog_publish_state.json)와 **독립**이되 최초 도입 시
# 같은 지문이면 발행상태를 베이스라인으로 **조율(coordination)** 채택해 가짜-신선 재생성을 막는다.
GEN_STATE_PATH = os.path.join(W.DATA, "_report_gen_state.json")
BLOG_STATE_PATH = os.path.join(W.DATA, "_blog_publish_state.json")  # 읽기 전용(조율용)


def latest_obs_date():
    """CMPA-166: 단일월 게이트 폐기 → '데이터 기준일'을 단일 CURRENT 월에서 뽑지 않고,
    **전체 월 CSV 를 통틀어** 가장 최근 수집일(가져온날짜)을 헤더 '최신 수집일'로 쓴다.
    (항목별 신선도는 각 행 '기준일' 컬럼이 그대로 노출 — 이건 전체 중 가장 신선한 날짜일 뿐.)
    소수의 보강행이 날짜를 흔들지 않게, 관측 ≥ MIN_OBS 인 날짜 중 최신을 우선하되 없으면 절대 최신."""
    cnt = Counter()
    for f in W.MONTHS:
        path = os.path.join(W.DATA, f)
        try:
            rows = csv.DictReader(open(path, encoding="utf-8-sig"))
        except FileNotFoundError:
            continue
        for row in rows:
            d = row.get("가져온날짜", "").strip()
            if re.match(r"\d{4}-\d{2}-\d{2}", d):
                cnt[d] += 1
    if not cnt:
        return W.CURRENT
    substantial = [d for d, n in cnt.items() if n >= MIN_OBS]
    return max(substantial) if substantial else max(cnt)


# ── CMPA-265 게이트 헬퍼 ────────────────────────────────────────────────────
def _compute_data_fingerprint():
    """단일 진실원천 재사용: whisky_blog_gate 의 report_signature/fingerprint 로 현재 데이터 지문 산출.
    divergent 정의 신설 금지(CMPA-265 AC3). 순환 import(whisky_blog_gate→generate_report) 회피를
    위해 함수 내 지연 import. 반환 (fingerprint, data_date)."""
    import whisky_blog_gate as gate  # lazy: 모듈 최상단 import 시 순환
    data = gate.load_report_data()
    sig = gate.report_signature(data)
    return gate.fingerprint(sig), data["data_date"]


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def _expected_report_path(month, gen_date):
    return os.path.join(REPORTS, f"{month}_위스키가격리포트_{gen_date}.md")


def _resolve_prev_baseline(fp, month, state_path):
    """직전 생성 베이스라인 (prev_fp, prev_gen_date) 결정.
    1) _report_gen_state.json 우선(생성 게이트의 독립 상태).
    2) 생성 상태가 없으면 발행 게이트(_blog_publish_state.json)와 **조율**: 같은 지문이고 그
       gen_date 의 dated md 가 이미 있으면 그것을 베이스라인으로 채택(최초 도입 마이그레이션 —
       이미 존재하는 리포트를 무변동인데도 새 날짜로 다시 찍는 가짜-신선을 막는다).
    매칭 없으면 (None, None) → 변경(=생성)으로 간주."""
    st = _read_json(state_path)
    if st and st.get("fingerprint"):
        return st["fingerprint"], st.get("gen_date")
    pub = _read_json(BLOG_STATE_PATH)
    if pub and pub.get("fingerprint") == fp and pub.get("gen_date"):
        gd = pub["gen_date"]
        if os.path.exists(_expected_report_path(month, gd)):
            return fp, gd
    return None, None


def _write_gen_state(path, fp, gen_date, data_date, report_rel):
    prev = _read_json(path) or {}
    history = list(prev.get("history", []))
    history.append({"fingerprint": fp, "gen_date": gen_date, "data_date": data_date,
                    "report": report_rel})
    state = {"fingerprint": fp, "gen_date": gen_date, "data_date": data_date,
             "report": report_rel, "updated_at": gen_date, "history": history[-50:]}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    return state


def gate_decision(fp, month, state_path, force):
    """생성 여부 결정(순수 로직, 테스트 가능).
    반환 dict: {generate: bool, reason: str, prev_fp, prev_gen}.
    무변동 = 지문 동일 + 해당 생성일 dated md 이미 존재(AC1). 파일이 없으면(삭제 등) 복구 생성."""
    prev_fp, prev_gen = _resolve_prev_baseline(fp, month, state_path)
    if force:
        return {"generate": True, "reason": "force", "prev_fp": prev_fp, "prev_gen": prev_gen}
    if fp == prev_fp and prev_gen and os.path.exists(_expected_report_path(month, prev_gen)):
        return {"generate": False, "reason": "unchanged", "prev_fp": prev_fp, "prev_gen": prev_gen}
    if fp == prev_fp and prev_gen:
        return {"generate": True, "reason": "unchanged_but_missing_file",
                "prev_fp": prev_fp, "prev_gen": prev_gen}
    return {"generate": True, "reason": "changed", "prev_fp": prev_fp, "prev_gen": prev_gen}


INTRO = """> 국내 대형마트(이마트 트레이더스·코스트코) 위스키 가격을 모아, **지금 가장 싸게 사는 곳**과 **과거·해외 대비 얼마나 좋은 값인지**를 정리한 리포트입니다.
> 핵심은 **[1] 최저가·매력도 표**(과거평균·데일리샷·매력도 모두 이 표의 컬럼). 해외 비교는 [2] 홍콩·[3] 일본, 계산 방법은 부록.
> **🆕 신선도 기준(CMPA-429, 보드 CMPA-424 모델):** **품목별로 가장 최근 수집일의 값·날짜**를 씁니다(트레이더스=유튜브 영상 촬영일, 코스트코=크롤일 스탬프). 최근 수집이 없으면 그 품목의 **가장 최근 과거 관측**을 그대로 씁니다 — 각 행 `기준일` 컬럼이 그 품목의 실제 수집일이라 품목마다 다를 수 있습니다(오래된 기준일 = 그만큼 오래 전 가격)."""

SEC1_HEAD = """## [1] 🎯 위스키 최저가 · 판매처 · 매력도 (핵심)

> 컬럼: `위스키 → 최저가 → 매력도 → 과거평균比(₩) → 데일리샷대비(₩) → 유형 → 최저 판매처 → 기준일 → 관측MIN/MAX → 과거평균`.
> **매력도 (0~100, 높을수록 매력적)** = 현재 최저가가 **전체 관측 가격대(과거 관측 + 현재가, `관측MIN`~`관측MAX`)** 안에서 어디에 있는지.
> · **100** = 관측 최저가(역대 최저) = **역대급 딜**  ·  **0** = 관측 최고가(지금이 가장 비쌈).
> **현재가도 MIN/MAX에 포함**합니다(보드 지시). 그래서 과거 관측이 1건뿐이어도 현재가가 더 싸면 제대로 100점을 받습니다.
> **⚪** = 과거와 현재가가 **완전히 동일**해 변동 정보가 없는 경우만(비교 불가) → 매력도 0, 맨 뒤.
> 정렬: **매력도 내림차순** — 위로 갈수록 좋은 딜. **기준일** = 그 최저가를 관측한 날짜 = **그 품목의 가장 최근 수집일**(CMPA-429: 품목 단위라 트레이더스 영상 OCR 신상품은 06-08처럼 더 최신 날짜로, 최근 재수집이 끊긴 품목은 그 품목의 마지막 관측일로 표시됩니다).
> **🏷️ 해외대비 배지(CMPA-54):** 위스키 이름 옆 **🟡🇭🇰↓** = 국내 마트가 **홍콩 면세가보다 쌈**, **🟡🇯🇵↓** = 국내 마트가 **일본 현지가보다 쌈**(🟡 노란 표시 = 눈에 띄게, HTML 리포트에선 노란 pill 로 렌더).
> **🟡면세↓** = 국내 마트가 **신라면세점 면세가보다도 쌈**(CMPA-234 — 출국 면세가보다도 싼 자랑 배지. 신라 USD×환율, 정규 700ml급 동일 SKU 정밀매칭).
> 동일 SKU 가 아래 [2]홍콩·[3]일본 비교에서 '국내 우세'로 판정된 병(면세↓는 신라면세 동일 SKU 대비 우세)에만 답니다(세전 면세·현지가 기준 — 반입세 미포함). 배지 없는 병은 해외 동일-SKU 비교 데이터가 없거나 해외가 더 싼 경우입니다."""

SEC1_FOOT = f"""**과거평균比(₩)** = **현재 최저가 − 과거평균**. **음수(−) = 과거 평균보다 그만큼 싸게 사는 것(좋은 딜)**, 양수(+) = 더 비쌈.
**데일리샷대비(₩)** = **마트 최저가 − 데일리샷 최저가**(`{W.DAILYSHOT_FILE}`). **음수(−) = 마트가 데일리샷보다 그만큼 쌈**, 양수(+) = 데일리샷이 더 쌈. `—` = 데일리샷 매칭 없음. **`≈` = 근접 매칭**(용량·에디션이 다를 수 있어 참고용).
**유형 범례:** 버번 / 스카치(몰트) / 스카치(블렌디드) / 피트 / 아이리시 / 재패니즈 / 월드몰트 (제품명 휴리스틱).  **⚪** = 과거·현재가 완전 동일 → 매력도 0·맨 뒤.  **관측MIN/MAX** = 그 항목의 과거 관측 + 현재가 모두 포함.  *판매처별 가격 컬럼은 가독성 위해 제거(최저 판매처만 표기).*"""

SEC2_HEAD = f"""## [2] 🌏 해외(홍콩) 가격 대비 메리트 — 동일 SKU, **면세 반입 기준**

> 보드 기준: **개인이 면세(免稅)로 직접 들고 들어오는 가격**과 비교(한국 관세·주세 미적용).
> **🇭🇰홍콩 면세가** = 홍콩 소매가(HKD)를 환율 환산(`기준가_KRW`). 출처 `{W.HK_FILE}`(Caskells Shopify 공개, **총 1,829종**), 정규 700ml.
> 국내 마트 SKU와 신뢰도 높게 1:1로 맞아떨어지는 **사람이 검증한 동일 제품**만 실었습니다(브랜드만으로 자동 매칭하면 오매칭이 섞이므로 제외)."""

SEC3_HEAD = """## [3] 🇯🇵 일본(현지) 가격 대비 메리트 — 동일 SKU

> [2] 홍콩과 같은 방식의 **한↔일 비교**(CMPA-53). **🇯🇵일본 현지가** = 일본 주류 Shopify 소매가(JPY) 환율 환산(`기준가_KRW`, 면세·무관세 — 홍콩 면세가와 같은 성격). 출처 `jp/2026-05_jp_shopify_poc.csv`(酒類ドットコム·SAKE People·酒庫住田屋 공개, **총 1,435종**), 정규 700/750ml.
> **🇯🇵반입추정가** = 한국 반입세 cascade(×2.5555) 적용가(실제 직구·반입 부담). 정본 위스키 id 로 자동 매칭하되 **숙성년수(N年)까지 일치하는 동일 제품만**(브랜드만 매칭은 오매칭이라 제외)."""

APPENDIX = """## 📎 부록 (Appendix) — 매력도 계산 근거 · 데이터 처리 방법

> **공식:** 매력도 = (관측MAX − 현재최저가) ÷ (관측MAX − 관측MIN) × 100. **관측MIN/MAX는 그 항목의 과거 관측 + 현재가를 모두 포함**하므로 현재가가 항상 범위 안에 들어가 0~100이 자연스럽게 나옵니다. 과거·현재가 모두 같으면 0(⚪).
>
> **🆕 수록 데이터 기준(CMPA-429, 보드 CMPA-424 모델):** '현재가'는 각 품목의 **가장 최근 수집일**(트레이더스·코스트코 관측 중)의 값입니다. 가격이 같아도 더 최신 수집일을 우선하고, 최근 수집이 없으면 그 품목의 **가장 최근 과거 관측**을 그대로 씁니다(제외하지 않음). 그 품목의 최신일 이전 관측은 과거평균(과거평균比 계산)에만 쓰입니다. ※ 롯데마트·이마트는 4월 이후 재수집이 끊겨 현재가 소스에서 제외(과거평균엔 사용) — 재수집이 살아나면 편입합니다. ※ 트레이더스 현장가는 유튜브 프레임-OCR(@whiskeypick·@whiskeykey 영상 촬영일)로도 수집합니다.

**SKU 정규화:** 같은 제품이 표기 차이(`글렌/글랜`·앞의 `더 `·띄어쓰기)나 오탈자(`배럴↔베럴`·`파이노크↔파인노크`·`잭다니엘↔잭다니엘스` 등, 스크립트 `TYPO` 표)로 여러 행으로 쪼개지던 문제를 병합했습니다. **서로 다른 제품(예: 조니워커 블랙 vs 블루)은 병합하지 않습니다** — 오탈자만 교정.

**한계:** 과거 이력이 짧아(현재 3~6월) 다수 SKU가 단일가(⚪). 오염행(현재가가 과거평균 ⅓~3배 밖)·비위스키는 제외."""


# CMPA-54: 배지 앞에 🟡(노란 점)을 붙인다. MD 문서는 CSS 색을 못 담으므로,
# 보드가 MD로 봐도 '노란색'이 보이도록 이모지로 색을 싣는다(보드 요청). HTML 렌더는
# 이미 노란 pill 이라 md_to_html 가 이 🟡 을 떼고 flag 만 pill 에 넣는다.
HK_BADGE = "🟡🇭🇰↓"   # 국내가가 홍콩 면세가보다 쌈
JP_BADGE = "🟡🇯🇵↓"   # 국내가가 일본 현지가보다 쌈
DF_BADGE = "🟡면세↓"   # CMPA-234: 국내가가 신라면세점 면세가보다도 쌈(🟡=MD 색 캐리어)


def compute_badges(ovrows, jp_rows, shilla_keys=None):
    """핵심표 정본key → 배지 문자열. CMPA-54/234.
    동일 SKU 가 [2]홍콩/[3]일본/신라면세 비교에서 '국내가 더 쌈'으로 판정된 경우에만 배지를 단다
    (오매칭 방지: 홍콩=dmin이 잡은 정본key, 일본=canonical_id→KR raw_name key 역매핑,
    면세=CMPA-138 정밀 가드 매칭 후 국내≤면세). HK/JP/면세 모두 동일 dommin 기준."""
    badges = {}
    for k in W.hk_cheaper_keys(ovrows):
        badges.setdefault(k, []).append(HK_BADGE)
    for k in JP.jp_cheaper_keys(jp_rows):
        badges.setdefault(k, []).append(JP_BADGE)
    for k in (shilla_keys or set()):
        badges.setdefault(k, []).append(DF_BADGE)
    return {k: " ".join(v) for k, v in badges.items()}


def build_report(data_date, gen_date):
    agg, disp = W.load()
    # 핵심표 배지를 위해 해외 비교를 먼저 계산 → 배지맵 → 핵심표(build_domestic) 순서.
    ov, ovrows = W.build_overseas(agg, disp)
    jp_rows, jp_stats = JP.compute_rows()
    shilla_keys = W.shilla_cheaper_keys(agg, disp)   # CMPA-234: 국내≤신라면세가 핵심표 key
    badges = compute_badges(ovrows, jp_rows, shilla_keys)
    t2, recs = W.build_domestic(agg, disp, W.load_dailyshot(), badges=badges)

    n_badge = sum(1 for r in recs if r["badge"])
    n_df = sum(1 for r in recs if DF_BADGE in r["badge"])   # CMPA-234: 면세↓ 단 SKU 수
    s100 = sum(1 for r in recs if r["score"] == 100)
    domwin = sum(1 for r in ovrows if r[2] <= r[3])
    hkwin = len(ovrows) - domwin
    matched = sum(1 for r in recs if r.get("dsdiff") is not None)

    sec2_foot = (
        f"> **시사점(면세 반입 기준, {len(ovrows)}종):** 관세를 빼고 비교해도 "
        f"**{domwin}종은 국내 마트가 저렴**, **{hkwin}종은 홍콩 면세가 더 쌈.** "
        "국내 우세 폭이 큰 제품일수록 면세 반입보다 국내 구매가 유리합니다."
    )
    sec1_foot = SEC1_FOOT + f"\n*({len(recs)}종 중 데일리샷 매칭 {matched}종.)*"

    # [3] 일본(현지) 비교 — CMPA-53. 홍콩과 동일 형식의 상설 섹션. (jp_rows/jp_stats 는 위에서 계산)
    jp_table = JP.table_md(jp_rows)
    sec3_foot = (
        f"> **시사점(일본 현지가 기준, {jp_stats['n']}종):** **현지가는 일본이 더 싼 제품 {jp_stats['jp_win']}종 / "
        f"국내가 우세 {jp_stats['dom_win']}종.** 단 **반입세(×2.56)를 더하면 전 품목 국내가 우위** — "
        "여행·면세 현지 구매는 일본이 유리하나, 직구·반입은 국내가 유리합니다."
    )

    parts = [
        f"# 🥃 위스키 가격 리포트 — {gen_date} 작성",
        f"<sub>리포트 생성일 {gen_date} (KST) · 데이터 기준일 {data_date}(전체 최신 수집일) · **품목별 최신 수집일 기준(CMPA-429)** — 각 품목의 실제 수집일은 표의 `기준일` 컬럼 참조(품목마다 다를 수 있음)</sub>",
        "",
        INTRO,
        "",
        "---",
        "",
        SEC1_HEAD,
        f"\n총 **{len(recs)}종** · 매력도 100(역대급 딜) **{s100}종** · 🏷️해외대비 저렴 배지 **{n_badge}종**(🇭🇰/🇯🇵/면세↓ {n_df}종).\n",
        "\n".join(t2),
        "",
        sec1_foot,
        "",
        "---",
        "",
        SEC2_HEAD,
        "",
        "\n".join(ov),
        "",
        sec2_foot,
        "",
        "---",
        "",
        SEC3_HEAD,
        "",
        "\n".join(jp_table),
        "",
        sec3_foot,
        "",
        APPENDIX,
        "",
    ]
    summary = dict(domestic=len(recs), s100=s100, overseas=len(ovrows),
                   domwin=domwin, ds_matched=matched, badges=n_badge, df=n_df,
                   jp=jp_stats["n"], jp_win=jp_stats["jp_win"])
    return "\n".join(parts), summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-date", help="헤더 '최신 수집일'(YYYY-MM-DD). 미지정 시 전체 월 통틀어 자동 추정.")
    ap.add_argument("--gen-date", help="리포트 생성일(YYYY-MM-DD). 미지정 시 오늘(KST).")
    ap.add_argument("--month", default=W.CURRENT, help=f"리포트 월(YYYY-MM). 기본 {W.CURRENT}.")
    ap.add_argument("--out", help="출력 경로. 미지정 시 reports/whisky-price/{month}_위스키가격리포트_{gen-date}.md (CMPA-45).")
    ap.add_argument("--latest", action="store_true",
                    help="추가로 _latest.md 편의 포인터 사본을 만든다(기본 끔 — 파일 수 최소화, CMPA-45 보드).")
    # CMPA-265: 데이터 변동 지문 게이트(기본 ON). 무변동이면 새 리포트·생성일을 만들지 않는다.
    ap.add_argument("--force", action="store_true",
                    help="지문 게이트 무시 — 무변동에도 강제 재생성(CMPA-265 탈출구).")
    ap.add_argument("--no-gate", action="store_true",
                    help="게이트 자체를 끔(종전 무조건 생성 동작; 디버그/특수 용도).")
    ap.add_argument("--gate-state", default=GEN_STATE_PATH,
                    help=f"생성 게이트 상태파일(기본 {GEN_STATE_PATH}).")
    args = ap.parse_args()

    gen_date = args.gen_date or datetime.now().strftime("%Y-%m-%d")

    # ── CMPA-265: 생성 단계 변동 게이트 ──────────────────────────────────────
    # --out(커스텀 경로)·--no-gate 는 명시적 의도로 보고 게이트를 적용하지 않는다.
    gated = not args.no_gate and not args.out
    fp = fp_data_date = None
    if gated:
        fp, fp_data_date = _compute_data_fingerprint()
        dec = gate_decision(fp, args.month, args.gate_state, args.force)
        if not dec["generate"]:
            prev_gen = dec["prev_gen"]
            print(f"[gate] 가져온 데이터 변경 없음(지문 {fp[:12]} 동일) → no-op. "
                  f"기존 리포트 {args.month}_위스키가격리포트_{prev_gen}.md 유지(새 리포트·생성일 갱신 없음).")
            # 발행상태와 조율해 채택한 베이스라인을 생성 상태파일에 1회 기록(다음 실행 가속·독립화).
            if _read_json(args.gate_state) is None:
                _write_gen_state(args.gate_state, fp, prev_gen, fp_data_date,
                                 os.path.relpath(_expected_report_path(args.month, prev_gen), ROOT))
                print(f"[gate] _report_gen_state.json 베이스라인 채택(발행상태와 조율, gen_date={prev_gen}).")
            return
        pfp = dec["prev_fp"]
        msg = {"force": "--force → 게이트 무시, 강제 재생성",
               "changed": f"변경 감지(지문 {str(pfp)[:12] if pfp else '없음'} → {fp[:12]})",
               "unchanged_but_missing_file":
                   f"지문 동일이나 dated md 결측 → 복구 재생성({fp[:12]})"}[dec["reason"]]
        print(f"[gate] {msg} → 리포트 생성(생성일 {gen_date}).")

    data_date = args.data_date or latest_obs_date()   # CMPA-166: 전체 월 통틀어 최신 수집일
    # CMPA-45: 최종 리포트는 정본 파일명 자체에 실행일을 박아 덮어쓰지 않고 누적한다.
    out = args.out or os.path.join(REPORTS, f"{args.month}_위스키가격리포트_{gen_date}.md")

    md, s = build_report(data_date, gen_date)
    os.makedirs(REPORTS, exist_ok=True)
    # 1) 정본 = 날짜 박힌 파일. 같은 날 재실행이면 그 날짜 파일만 덮어써(멱등), 다른 날은 새 파일.
    with open(out, "w", encoding="utf-8") as f:
        f.write(md)
    # 2) (선택, 기본 끔) 최신 편의 포인터 — `--latest` 줄 때만. 파일 수 최소화(CMPA-45 보드 지적).
    latest = None
    if args.latest and not args.out:
        latest = os.path.join(REPORTS, f"{args.month}_위스키가격리포트_latest.md")
        shutil.copy2(out, latest)

    # CMPA-265: 생성한 경우에만 게이트 상태 갱신(지문/생성일/기준일). 다음 무변동 실행의 no-op 기준.
    if gated:
        if fp is None:
            fp, fp_data_date = _compute_data_fingerprint()
        _write_gen_state(args.gate_state, fp, gen_date, fp_data_date, os.path.relpath(out, ROOT))
        print(f"[gate] _report_gen_state.json 갱신(지문 {fp[:12]}, gen_date={gen_date}).")

    print(f"wrote {os.path.relpath(out, ROOT)}"
          + (f"  (latest pointer: {os.path.relpath(latest, ROOT)})" if latest else ""))
    print(f"  최신 수집일={data_date} · 작성일={gen_date} (품목 단위 최신 수집일, CMPA-429)")
    print(f"  국내 {s['domestic']}종(매력도100={s['s100']}, 데일리샷매칭={s['ds_matched']}, 해외대비배지={s['badges']}/면세↓{s['df']}) | "
          f"홍콩 {s['overseas']}종(국내우세={s['domwin']}) | 일본 {s['jp']}종(일본현지우세={s['jp_win']})")


if __name__ == "__main__":
    main()
