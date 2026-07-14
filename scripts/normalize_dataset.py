#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
normalize_dataset.py — CMPA-31 데이터 정규화·검증(클렌징) + 마스터 SKU 사전.

수집 루틴 4종(유튜브/마트웹·데일리샷·해외)의 raw CSV 를 한 스키마로 모으고,
CMPA-22 동의어 자산(assets/whisky-synonyms.yaml + normalize_whisky_name.py)을 재사용해
정본 위스키 id 로 정규화한 뒤, 오염행·비위스키·용량/에디션을 정리해 통합 데이터셋을 만든다.
그동안 CEO 가 리뷰마다 수동으로 메우던 클렌징 단계를 스크립트화한 것.

정규화 단계
  1) 소스 어댑터: 4종 raw → 통합 스키마(raw_name, price_krw, market, channel, date, volume_ml ...)
  2) 용량/에디션 정규화: 이름에서 용량(ml) 추출, 미니어처/세트/전용잔 등 비-단품 플래그
  3) 이름 → 정본 id 정규화
       · 국내(한글): Normalizer(whisky-synonyms.yaml)  — 오탈자/표기변형 병합
       · 해외(영문): whisky-list.csv name_en 기반 한↔영 매처(브랜드+숙성년수 토큰 전부 일치)
     서로 다른 제품은 글자 1개 차이여도 병합 금지 — 명시적 사전(match/not 토큰) 방식 유지.
  4) 제외: 비위스키(exclude_non_whisky), 비-단품(미니어처/세트), 가격 결측/0
  5) 오염행 제거: 같은 정본 id 의 과거평균(03·04월) 대비 ⅓~3배 밖 현재가 → 드롭

산출물
  · data/whisky-prices/normalized/normalized_prices.csv  — 정규화된 통합 데이터셋
  · assets/master-sku.csv                                — 마스터 SKU 사전(정본 id 별 집계)
  · assets/whisky-aliases.csv                            — 별칭 사전(raw → 정본 id, 전 소스)
  · reports/whisky-price/CMPA-31_정규화검증리포트.md       — 검증 리포트(병합/제외/오염 건수)

용법
  python3 scripts/normalize_dataset.py            # 전체 파이프라인 실행 + 리포트
  python3 scripts/normalize_dataset.py --quiet    # 콘솔 요약만(파일은 그대로 생성)
재실행 가능. 월 변경 시 DOMESTIC_MONTHS / CURRENT_MONTH 만 갱신.
"""
import csv, os, re, sys, statistics
from collections import defaultdict, Counter

# CMPA-22 정규화기 재사용 (정본: assets/whisky-synonyms.yaml)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from normalize_whisky_name import Normalizer, load_rules  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "whisky-prices")
OUT_DIR = os.path.join(DATA, "normalized")

# CMPA-38: 수집 루틴은 주간/격주로 돈다. 입력(정본) 파일명은 데이터 '월' 을 유지하고
# (= 항상 최신 = 안정적 latest 포인터), 매 실행 시점 스냅샷은 _runs/ 에 누적된다.
# normalize 는 정본(월) 파일을 그대로 읽으면 늘 '가장 최신' 입력을 보게 된다.
sys.path.insert(0, ROOT)
from pipelines.common.dated import snapshot, kst_today  # noqa: E402
# CMPA-165: 매장 라벨 지점명 제거 + ASR 오수집(비-제품명·말도안되는 가격) 격리 공통 모듈.
from pipelines.common.whisky_quality import canonical_store, is_quarantined  # noqa: E402

# 월 변경 시 아래 두 줄만 갱신하면 도메스틱 누적월·현재월 단발소스(SOURCES)·오염
# 베이스라인(PAST_MONTHS)이 모두 이 둘로부터 파생되어 따라온다. 미존재 입력은 로더가 skip.
DOMESTIC_MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07"]
CURRENT_MONTH = "2026-07"
PAST_MONTHS = tuple(m for m in DOMESTIC_MONTHS if m != CURRENT_MONTH)  # 오염 베이스라인 = 현재월 제외 과거 도메스틱
OUTLIER_LO, OUTLIER_HI = 1 / 3, 3      # 현재가가 과거평균의 ⅓~3배 밖이면 오염행

# 통합 스키마
FIELDS = ["canonical_id", "canonical_name_ko", "raw_name", "volume_ml", "non_unit",
          "price_krw", "market", "channel", "branch", "date", "source_family",
          "source_file", "status", "exclude_reason"]

# 비-단품(미니어처/세트/전용잔 등) — 단품 최저가 집계에서 제외
NON_UNIT_RX = re.compile(
    r"(미니어처|미니어쳐|miniature|gift\s*set|선물세트|세트구성|전용잔|전용 ?잔|잔세트|"
    r"\b(5|20|35|50|100|200|375)\s*ml\b|two\s*pack|두\s*개입)", re.I)
VOL_RX = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|밀리|l|리터)\b", re.I)


def extract_volume_ml(name):
    """이름에서 용량(ml) 추출. 없으면 None. 1.75L→1750, 700ml→700."""
    m = VOL_RX.search(name or "")
    if not m:
        return None
    val = float(m.group(1)); unit = m.group(2).lower()
    if unit in ("l", "리터"):
        val *= 1000
    return int(round(val))


# ── 소스 어댑터 ──────────────────────────────────────────────────────────
# 각 어댑터는 raw CSV 한 줄 → 통합 dict(부분) 또는 None(스킵) 반환.
# market: KR(국내 소매)·KR-DS(데일리샷)·HK·TW·JP

def _int(s):
    try:
        v = int(re.sub(r"[^\d]", "", str(s)))
        return v if v > 0 else None
    except Exception:
        return None


_norm_store = canonical_store   # CMPA-165: 공통 모듈로 통일(트레이더스·코스트코·롯데마트 …)


def adapt_domestic(row, month):
    """유튜브/마트웹 국내 월간(2026-03/04/05.csv). 술이름·가격_KRW·위치.
    CMPA-446: 유튜브 OCR CSV 의 `지점`(트레이더스 구월점 등)을 nullable branch 로 전파
    (provenance 보존). floor/리포트는 제품키 유지 — 지점별 분리하지 않음. 구파일은 빈값."""
    name = (row.get("술이름") or "").strip()
    price = _int(row.get("가격_KRW"))
    if not name:
        return None
    return dict(raw_name=name, price_krw=price, market="KR",
                channel=_norm_store(row.get("위치")),
                branch=(row.get("지점") or "").strip(),
                date=(row.get("가져온날짜") or "").strip() or month,
                volume_ml=extract_volume_ml(name))


def adapt_guwol(row, month):
    """위스키픽 ASR 구월점(2026-05_whiskeypick_traders_guwol.csv). 용량 컬럼 별도."""
    name = (row.get("술이름") or "").strip()
    price = _int(row.get("가격_KRW"))
    if not name:
        return None
    vol = extract_volume_ml((row.get("용량") or "")) or extract_volume_ml(name)
    return dict(raw_name=name, price_krw=price, market="KR",
                channel=_norm_store(row.get("위치")),
                date=(row.get("가져온날짜") or "").strip() or month,
                volume_ml=vol)


def adapt_dailyshot(row, month):
    """데일리샷(2026-05_dailyshot.csv). MISS/빈 정확도 행은 스킵."""
    name = (row.get("위스키명") or "").strip()
    acc = (row.get("정확도") or "").strip()
    if not name or acc in ("", "MISS"):
        return None
    price = _int(row.get("가격_KRW"))
    return dict(raw_name=name, price_krw=price, market="KR-DS",
                channel=_norm_store(row.get("국내위치") or "데일리샷"),
                date=(row.get("수집일") or "").strip() or month,
                volume_ml=extract_volume_ml(row.get("데일리샷상품명") or name))


def adapt_overseas(market, price_col):
    def _adapt(row, month):
        name = (row.get("술이름") or "").strip()
        if not name:
            return None
        price = _int(row.get(price_col)) or _int(row.get("기준가_KRW"))
        return dict(raw_name=name, price_krw=price, market=market,
                    channel=(row.get("셀러") or row.get("출처") or "").strip(),
                    date=(row.get("가져온날짜") or "").strip() or month,
                    volume_ml=extract_volume_ml(name) or _int(row.get("용량_ml")))
    return _adapt


# (source_family, 파일경로(상대), 어댑터, month) — 입력 4종.
# 도메스틱(유튜브/마트웹) 월간은 DOMESTIC_MONTHS 만큼 누적, 데일리샷·해외(HK/JP)는
# CURRENT_MONTH 단발 스냅샷으로 파생한다. 미존재 파일은 run() 로더에서 skip 되므로
# 월 롤포워드 시 위의 두 상수만 갱신하면 SOURCES 가 그대로 따라온다.
SOURCES = [("youtube_martweb", f"{m}.csv", adapt_domestic, m) for m in DOMESTIC_MONTHS]
# CMPA-424: 유튜브 가격영상 프레임OCR 적재분(품질게이트·정본 매핑 통과분만). 정본 스키마라
# adapt_domestic 그대로 재사용. 격리분(_youtube_ocr_quarantine.csv)은 미등록 → floor 미반영.
# 미존재 월 파일은 run() 로더에서 skip 되므로 월 롤포워드 시 DOMESTIC_MONTHS 만 따라온다.
SOURCES += [("youtube_ocr", f"{m}_youtube_ocr.csv", adapt_domestic, m) for m in DOMESTIC_MONTHS]
SOURCES += [
    ("dailyshot", f"{CURRENT_MONTH}_dailyshot.csv", adapt_dailyshot, CURRENT_MONTH),
    ("overseas", f"{CURRENT_MONTH}_hk_whisky_poc.csv",
     adapt_overseas("HK", "반입추정가_KRW_FTA0"), CURRENT_MONTH),
    # JP: CMPA-52/CMPA-53 — Rakuten(키 대기) → 키리스 Shopify products.json 로 교체.
    # 동일 컬럼(술이름·한국반입추정가_KRW·출처·가져온날짜)이라 어댑터 그대로 재사용.
    ("overseas", f"jp/{CURRENT_MONTH}_jp_shopify_poc.csv",
     adapt_overseas("JP", "한국반입추정가_KRW"), CURRENT_MONTH),
]
# POC/단발 소스 — 월간 재수집 루틴이 없어 마지막 수집월(2026-05)에 고정. 새 월 데이터가
# 생기기 전까지 가장 최신 스냅샷으로 유지(미존재 시 skip). 향후 루틴화되면 위로 승격.
SOURCES += [
    ("youtube_martweb", "2026-05_whiskeypick_traders_guwol.csv", adapt_guwol, "2026-05"),
    ("overseas", "2026-05_tw_whisky_poc.csv",
     adapt_overseas("TW", "반입추정가_KRW_FTA0"), "2026-05"),
]


# ── 해외 영문 → 정본 id 매처 (한↔영 사전) ────────────────────────────────
# whisky-list.csv 의 name_en/brand/age 로 "브랜드 토큰 + 숙성년수" 규칙을 만든다.
# 같은 브랜드+년수에 후보가 2개 이상이면(예: 맥캘란 12 더블캐스크 vs 셰리오크)
# 잘못 병합하지 않도록 모두 모호(ambiguous) 처리 → unmatched 로 둔다.
STOP_EN = {"the", "old", "year", "years", "yo", "single", "malt", "scotch",
           "whisky", "whiskey", "release", "vol", "no", "cask"}


def _en_norm(s):
    s = str(s).lower()
    s = re.sub(r"(\d+)\s*(年|y\.?o\.?|years?\s*old|years?)\b", r"\1y", s)
    s = re.sub(r"[^a-z0-9가-힣]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def load_whisky_list():
    rows = []
    fp = os.path.join(ROOT, "assets", "whisky-list.csv")
    with open(fp, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def build_en_rules(wl_rows):
    """name_en 이 있는 정본만 대상. 반환: [(id, name_ko, [required_tokens], age)]"""
    rules = []
    for r in wl_rows:
        en = _en_norm(r.get("name_en") or "")
        if not en:
            continue
        brand = _en_norm(r.get("brand") or "")
        age = (r.get("age") or "").strip()
        toks = []
        # 브랜드 첫 단어(고유)
        if brand:
            toks.append(brand.split()[0])
        elif en:
            toks.append(en.split()[0])
        if age:
            toks.append(f"{age}y")
        # 브랜드/년수만으로 부족하면 name_en 의 변별 단어 1개 추가
        extra = [w for w in en.split() if w not in STOP_EN and w not in toks
                 and not w.isdigit() and not re.fullmatch(r"\d+y", w)]
        if extra:
            toks.append(extra[-1])           # 익스프레션 명(예: doublewood, caribbean)
        rules.append((r["id"], r.get("name_ko", ""), toks, age))
    return rules


class EnglishMatcher:
    def __init__(self, rules):
        self.rules = rules

    def match(self, raw):
        norm = _en_norm(raw)
        if not norm:
            return None
        hits = []
        for cid, name_ko, toks, age in self.rules:
            if toks and all(t in norm for t in toks):
                hits.append((cid, name_ko))
        if len(hits) == 1:
            return hits[0]
        return None        # 0건=미매칭, 2건↑=모호 → 병합 금지


# ── 일본어(가타카나) → 정본 id 매처 (CMPA-53) ──────────────────────────────
# JP Shopify(CMPA-52) 상품명은 일본어 표기라 한글 Normalizer/영문 매처가 못 잡는다.
# whisky-list 의 brand 를 가타카나로 잇는 브리지로, "브랜드 + 숙성년수(N年)" 가
# 마스터에서 **유일하게** 가리키는 1종일 때만 매칭한다(후보 0/2↑=미매칭, 오병합 금지).
# 가타카나 키는 마스터(whisky-list)에 실재하는 브랜드만 — 일본 국내 위스키 등 마스터
# 미등록 제품은 의도적으로 unmatched(= 마스터 확장 후보, CMPA-22 원칙) 로 남긴다.
KATAKANA_BRAND = {
    "グレンモーレンジィ": "Glenmorangie", "グレンモーレンジ": "Glenmorangie",
    "マッカラン": "Macallan", "ザ・マッカラン": "Macallan",
    "グレンリベット": "Glenlivet", "ザ・グレンリベット": "Glenlivet",
    "グレンフィディック": "Glenfiddich", "グレンフィデック": "Glenfiddich",
    "ボウモア": "Bowmore", "ラフロイグ": "Laphroaig",
    "ラガヴーリン": "Lagavulin", "ラガブーリン": "Lagavulin",
    "タリスカー": "Talisker", "アベラワー": "Aberlour",
    "バルヴェニー": "Balvenie", "ザ・バルヴェニー": "Balvenie",
    "デュワーズ": "Dewar's", "バランタイン": "Ballantine's",
    "シーバスリーガル": "Chivas Regal", "ジョニーウォーカー": "Johnnie Walker",
    "アラン": "Arran", "カバラン": "Kavalan", "カヴァラン": "Kavalan",
    "オーバン": "Oban", "ダルモア": "Dalmore", "ザ・ダルモア": "Dalmore",
    "グレンドロナック": "GlenDronach", "ベンリアック": "BenRiach",
    "タムドゥ": "Tamdhu", "アバフェルディ": "Aberfeldy",
    "オーヘントッシャン": "Auchentoshan", "オーヘントシャン": "Auchentoshan",
    "ロイヤルサルート": "Royal Salute", "ロイヤルブラックラ": "Royal Brackla",
    "フェイマスグラウス": "The Famous Grouse", "モンキーショルダー": "Monkey Shoulder",
    "ジェムソン": "Jameson", "ジェイムソン": "Jameson", "ブッシュミルズ": "Bushmills",
    "カティサーク": "Cutty Sark", "グレングラント": "Glen Grant",
    "グレンゴイン": "Glengoyne", "グレンキンチー": "Glenkinchie",
    "クライヌリッシュ": "Clynelish", "グレングラッサ": "Glenglassaugh",
    "ジャックダニエル": "Jack Daniel's", "メーカーズマーク": "Maker's Mark",
    "ワイルドターキー": "Wild Turkey", "ジムビーム": "Jim Beam",
    "フォアローゼズ": "Four Roses", "フォアローゼス": "Four Roses",
    "ウッドフォードリザーブ": "Woodford Reserve", "イーグルレア": "Eagle Rare",
    "バッファロートレース": "Buffalo Trace", "エヴァンウィリアムス": "Evan Williams",
    "ラッセルズリザーブ": "Russell's Reserve", "ノマド": "Nomad",
}


class JapaneseMatcher:
    """가타카나 브랜드 + 숙성년수(N年) → 마스터에서 유일하게 가리키는 1 SKU 만 매칭."""

    def __init__(self, wl_rows):
        self.idx = defaultdict(list)         # _en_norm(brand) -> [(id, name_ko, age)]
        for r in wl_rows:
            bn = _en_norm(r.get("brand") or "")
            if bn:
                self.idx[bn].append((r["id"], r.get("name_ko", ""), (r.get("age") or "").strip()))
        # 긴 키 우선(짧은 키가 긴 키의 부분문자열일 때 오매칭 방지)
        self.keys = sorted(KATAKANA_BRAND, key=len, reverse=True)

    # 본질적으로 무연수(NAS)/특수 라인 — 출처에 잘못 "12年" 등이 붙어도(예: ジョニーウォーカー
    # レッドラベル 12年) 숙성 SKU 로 오매칭되면 안 됨. 발견 시 매칭 포기.
    NAS_HINTS = ("レッドラベル", "ブルーラベル", "ゴールドラベル", "プラチナラベル",
                 "ダブルブラック", "ホワイトウォーカー")

    def match(self, raw):
        if any(h in raw for h in self.NAS_HINTS):
            return None
        brand_disp = next((KATAKANA_BRAND[k] for k in self.keys if k in raw), None)
        if not brand_disp:
            return None
        cands = self.idx.get(_en_norm(brand_disp))
        if not cands:
            return None
        # 숙성년수(N年)가 명시된 행만 매칭한다. 무연수(NAS) 행을 브랜드만으로 잇는 것은
        # 위험 — 같은 브랜드의 서로 다른 무연수 익스프레션(예: 달모어 Cigar Malt / King
        # Alexander)이 마스터의 유일 무연수 SKU(달모어 2005 빈티지)로 오병합된다(실측 확인).
        # 또 N年 이 2종↑(사은품 미니보틀 등)이면 본품 숙성 모호 → 포기.
        ages = set(re.findall(r"(\d+)\s*年", raw))
        if len(ages) != 1:
            return None
        age = next(iter(ages))
        cands = [c for c in cands if c[2] == age]
        if len(cands) == 1:                  # 유일해야만 매칭(0/2↑=미매칭, 오병합 금지)
            return (cands[0][0], cands[0][1])
        return None


# ── 파이프라인 ───────────────────────────────────────────────────────────
def run(quiet=False):
    rules = load_rules()
    norm = Normalizer(rules)
    wl_rows = load_whisky_list()
    enm = EnglishMatcher(build_en_rules(wl_rows))
    jam = JapaneseMatcher(wl_rows)        # CMPA-53: JP 가타카나 브리지

    # CEO alias: aliases.csv ceo_alias 행을 미리 읽어 rule 매칭보다 우선 적용.
    # CEO가 직접 지정한 매핑은 자동 rule 매칭 결과를 override 해야 한다.
    _aliases_path = os.path.join(ROOT, "assets", "whisky-aliases.csv")
    ceo_alias_map = {}
    if os.path.exists(_aliases_path):
        with open(_aliases_path, encoding="utf-8-sig") as _f:
            for _row in csv.DictReader(_f):
                if (_row.get("match_reason") or "").startswith("ceo_alias"):
                    _raw = _row.get("raw_name", "")
                    if _raw:
                        ceo_alias_map[_raw] = (_row.get("status", "matched"),
                                               _row.get("canonical_id", ""),
                                               _row.get("canonical_name_ko", ""),
                                               _row.get("match_reason", "ceo_alias"))

    records = []                       # 통합 행(정규화 결과 포함, 모든 status)
    stats = defaultdict(Counter)       # source_family → Counter(status/exclude)
    raw_to_canon = {}                  # raw_name → (status, id, name_ko, reason)

    for fam, rel, adapt, month in SOURCES:
        fp = os.path.join(DATA, rel)         # 정본(월) 파일 = 항상 최신 (CMPA-38 latest 포인터)
        if not os.path.exists(fp):
            continue
        with open(fp, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                rec = adapt(row, month)
                if rec is None:
                    stats[fam]["skipped_input"] += 1
                    continue
                rec.update(source_family=fam, source_file=os.path.basename(fp))
                raw = rec["raw_name"]
                rec["non_unit"] = bool(NON_UNIT_RX.search(raw))

                # CEO alias 우선 — rule 자동 매칭보다 먼저 확인
                if raw in ceo_alias_map:
                    status, cid, name_ko, reason = ceo_alias_map[raw]
                # 정규화: 국내=한글 Normalizer, 해외=영문 매처(보조로 한글도 시도)
                elif rec["market"] in ("KR", "KR-DS"):
                    c = norm.canonicalize(raw)
                    status, cid, name_ko, reason = (
                        c["status"], c["id"], c["name_ko"], c["reason"])
                else:
                    c = norm.canonicalize(raw)             # 비위스키 토큰은 한글 규칙으로도 잡음
                    if c["status"] == "excluded":
                        status, cid, name_ko, reason = "excluded", "", "", c["reason"]
                    else:
                        m = enm.match(raw)
                        jm = jam.match(raw) if rec["market"] == "JP" else None
                        if m:
                            status, cid, name_ko, reason = "matched", m[0], m[1], "en"
                        elif jm:
                            status, cid, name_ko, reason = "matched", jm[0], jm[1], "ja"
                        elif c["status"] == "matched":
                            status, cid, name_ko, reason = "matched", c["id"], c["name_ko"], "rule"
                        else:
                            status, cid, name_ko, reason = "unmatched", "", "", ""

                rec.update(canonical_id=cid, canonical_name_ko=name_ko,
                           status=status, exclude_reason="")
                raw_to_canon[raw] = (status, cid, name_ko, reason)

                # CMPA-165: 유튜브 트레이더스 ASR 오수집(비-제품명·말도안되는 가격) 격리.
                # 마트 현장가(market=KR)에만 적용 — 데일리샷/해외는 정형 소스라 제외.
                qx = is_quarantined(raw, rec["price_krw"]) if rec["market"] == "KR" else ""
                if qx:
                    rec["status"] = "excluded"; rec["exclude_reason"] = qx
                    stats[fam][f"excluded_{qx}"] += 1
                    records.append(rec)
                    continue

                if status == "excluded":
                    rec["exclude_reason"] = reason
                    stats[fam]["excluded_nonwhisky"] += 1
                elif rec["non_unit"]:
                    rec["status"] = "excluded"; rec["exclude_reason"] = "non_unit"
                    stats[fam]["excluded_nonunit"] += 1
                elif rec.get("volume_ml") is not None and int(rec["volume_ml"]) < 500:
                    # CMPA-733: 500ml 미만 소용량 수집 금지
                    rec["status"] = "excluded"; rec["exclude_reason"] = "sub_500ml"
                    stats[fam]["excluded_sub500ml"] += 1
                elif rec["price_krw"] is None:
                    rec["status"] = "excluded"; rec["exclude_reason"] = "no_price"
                    stats[fam]["excluded_noprice"] += 1
                elif status == "matched":
                    stats[fam]["matched"] += 1
                else:
                    stats[fam]["unmatched"] += 1
                records.append(rec)

    # ── 오염행 제거: 정본 id 별 과거평균(03·04월) 대비 ⅓~3배 밖 ──────────
    hist = defaultdict(list)
    for r in records:
        if (r["status"] == "matched" and r["canonical_id"]
                and r["market"] == "KR" and r["price_krw"]):
            mon = (r["date"] or "")[:7]
            if mon in PAST_MONTHS:
                hist[r["canonical_id"]].append(r["price_krw"])
    havg = {cid: statistics.mean(v) for cid, v in hist.items() if v}

    outliers = 0
    for r in records:
        if r["status"] != "matched" or not r["price_krw"]:
            continue
        a = havg.get(r["canonical_id"])
        if a and not (a * OUTLIER_LO <= r["price_krw"] <= a * OUTLIER_HI):
            r["status"] = "outlier"; r["exclude_reason"] = f"price_vs_havg({int(a)})"
            stats[r["source_family"]]["outlier_dropped"] += 1
            outliers += 1

    clean = [r for r in records if r["status"] == "matched"]
    write_outputs(records, clean, stats, raw_to_canon, havg)
    report = build_report(records, clean, stats, raw_to_canon, outliers)
    rp = os.path.join(ROOT, "reports", "whisky-price", "CMPA-31_정규화검증리포트.md")
    os.makedirs(os.path.dirname(rp), exist_ok=True)
    with open(rp, "w", encoding="utf-8") as f:
        f.write(report)

    # CMPA-38: 정본(고정명) 출력은 그대로 두고, 매 실행 시점 사본을 _runs/ 에 날짜 스냅샷.
    rd = kst_today()
    for p in [os.path.join(OUT_DIR, "normalized_prices.csv"),
              os.path.join(OUT_DIR, "normalized_all_rows.csv"),
              os.path.join(ROOT, "assets", "master-sku.csv"),
              os.path.join(ROOT, "assets", "whisky-aliases.csv"), rp]:
        snapshot(p, run_date=rd)

    if not quiet:
        print(report)
    print(f"\n[outputs]")
    print(f"  normalized : {os.path.join(OUT_DIR, 'normalized_prices.csv')}  (clean rows={len(clean)})")
    print(f"  master sku : {os.path.join(ROOT, 'assets', 'master-sku.csv')}")
    print(f"  aliases    : {os.path.join(ROOT, 'assets', 'whisky-aliases.csv')}")
    print(f"  report     : {rp}")
    return records, clean, stats


def write_outputs(records, clean, stats, raw_to_canon, havg):
    os.makedirs(OUT_DIR, exist_ok=True)

    # 1) 정규화된 통합 데이터셋 (matched 단품만)
    with open(os.path.join(OUT_DIR, "normalized_prices.csv"), "w",
              encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in sorted(clean, key=lambda x: (x["canonical_id"], x["price_krw"] or 0)):
            w.writerow({k: r.get(k, "") for k in FIELDS})

    # 1b) 전수 행(제외/오염 사유 포함) — 감사 추적용
    with open(os.path.join(OUT_DIR, "normalized_all_rows.csv"), "w",
              encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in records:
            w.writerow({k: r.get(k, "") for k in FIELDS})

    # 2) 마스터 SKU 사전: 정본 id 별 집계
    wl = {r["id"]: r for r in load_whisky_list()}
    by_id = defaultdict(lambda: dict(aliases=set(), rows=0, markets=set(), prices=[]))
    for r in clean:
        g = by_id[r["canonical_id"]]
        g["aliases"].add(r["raw_name"]); g["rows"] += 1
        g["markets"].add(r["market"])
        if r["price_krw"]:
            g["prices"].append(r["price_krw"])
    with open(os.path.join(ROOT, "assets", "master-sku.csv"), "w",
              encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["canonical_id", "name_ko", "name_en", "brand", "category",
                    "n_aliases", "n_rows", "markets", "min_krw", "max_krw", "alias_examples"])
        for cid in sorted(by_id):
            g = by_id[cid]; meta = wl.get(cid, {})
            ex = "; ".join(sorted(g["aliases"])[:4])
            w.writerow([cid, meta.get("name_ko", ""), meta.get("name_en", ""),
                        meta.get("brand", ""), meta.get("category", ""),
                        len(g["aliases"]), g["rows"], ";".join(sorted(g["markets"])),
                        min(g["prices"]) if g["prices"] else "",
                        max(g["prices"]) if g["prices"] else "", ex])

    # 3) 별칭 사전: raw → 정본 id (전 소스, 전수)
    # ceo_alias 수작업 행은 재생성 시 삭제되지 않도록 먼저 읽어 보존한다.
    aliases_path = os.path.join(ROOT, "assets", "whisky-aliases.csv")
    ceo_aliases = {}  # raw_name → (st, cid, nm, reason)
    if os.path.exists(aliases_path):
        with open(aliases_path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if (row.get("match_reason") or "").startswith("ceo_alias"):
                    raw = row.get("raw_name", "")
                    if raw:
                        # ceo_alias 는 rule 자동 매칭보다 우선(CEO가 직접 지정한 매핑).
                        # raw_to_canon 에 이미 있어도 override 한다.
                        ceo_aliases[raw] = (row.get("status", "matched"),
                                            row.get("canonical_id", ""),
                                            row.get("canonical_name_ko", ""),
                                            row.get("match_reason", "ceo_alias"))
    with open(aliases_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["raw_name", "status", "canonical_id", "canonical_name_ko", "match_reason"])
        for raw in sorted(raw_to_canon):
            st, cid, nm, reason = raw_to_canon[raw]
            w.writerow([raw, st, cid, nm, reason])
        for raw in sorted(ceo_aliases):
            st, cid, nm, reason = ceo_aliases[raw]
            w.writerow([raw, st, cid, nm, reason])


def build_report(records, clean, stats, raw_to_canon, outliers):
    fams = ["youtube_martweb", "dailyshot", "overseas"]
    distinct_raw = len(raw_to_canon)
    matched_ids = {r["canonical_id"] for r in clean}
    total_rows = len(records)
    L = []
    L.append("# CMPA-31 데이터 정규화·검증 리포트")
    L.append("")
    L.append("> `scripts/normalize_dataset.py` 1회 실행 결과. 재실행 가능. "
             "수집 4종(유튜브/마트웹·데일리샷·해외) raw → 정본 위스키 id 정규화·클렌징.")
    L.append("")
    L.append(f"- 입력 raw 행: **{total_rows:,}**  ·  distinct raw 표기: **{distinct_raw:,}**")
    L.append(f"- 정규화(병합) 후 정본 SKU 수: **{len(matched_ids)}** "
             f"(whisky-list.csv 89종 중)")
    L.append(f"- 통합 데이터셋(clean 단품) 행: **{len(clean):,}**")
    L.append(f"- 오염행 제거(과거평균 ⅓~3배 밖): **{outliers}**")
    L.append("")
    en_rows = sum(1 for r in clean if r["market"] not in ("KR", "KR-DS"))
    L.append(f"> ⚠️ 신뢰도: 국내(한글) 매칭은 명시적 사전(match/not) 기반 고신뢰. "
             f"해외 매칭({en_rows}행, reason=`en`)은 name_en 브랜드+년수 토큰 휴리스틱이라 "
             f"보조(advisory) 신뢰도 — 리포트 본표 반영 전 스팟체크 권장. 모호(후보 2개↑)는 미매칭 처리.")
    L.append("")
    L.append("## 소스별 정규화/제외 집계")
    L.append("")
    L.append("| 소스 | 입력스킵 | matched | unmatched | 비위스키제외 | 비단품제외 | 가격결측 | 오염제거 |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    tot = Counter()
    for fam in fams:
        s = stats.get(fam, Counter())
        row = [s["skipped_input"], s["matched"], s["unmatched"],
               s["excluded_nonwhisky"], s["excluded_nonunit"],
               s["excluded_noprice"], s["outlier_dropped"]]
        for k, v in s.items():
            tot[k] += v
        L.append(f"| {fam} | " + " | ".join(f"{x:,}" for x in row) + " |")
    L.append(f"| **합계** | {tot['skipped_input']:,} | {tot['matched']:,} | "
             f"{tot['unmatched']:,} | {tot['excluded_nonwhisky']:,} | "
             f"{tot['excluded_nonunit']:,} | {tot['excluded_noprice']:,} | "
             f"{tot['outlier_dropped']:,} |")
    L.append("")

    # 병합 예시(같은 정본에 raw 표기 ≥3종)
    by_id = defaultdict(set)
    for raw, (st, cid, nm, reason) in raw_to_canon.items():
        if st == "matched":
            by_id[(cid, nm)].add(raw)
    merges = sorted(((len(v), cid, nm, v) for (cid, nm), v in by_id.items()),
                    reverse=True)
    L.append("## 표기변형 병합 예시 (raw 표기 ≥ 3종 → 1 SKU)")
    L.append("")
    shown = 0
    for n, cid, nm, variants in merges:
        if n < 3:
            continue
        L.append(f"- **[{cid}] {nm}** ← {n}종: " +
                 ", ".join(f"`{v}`" for v in sorted(variants)[:6]) +
                 (" …" if n > 6 else ""))
        shown += 1
        if shown >= 12:
            break
    if shown == 0:
        L.append("- (3종 이상 병합 사례 없음)")
    L.append("")

    # 미매칭 후보(정본 미등록 위스키 → 마스터 확장 후보)
    unmatched = sorted({raw for raw, (st, *_2) in raw_to_canon.items() if st == "unmatched"})
    L.append(f"## 미매칭 raw 표기 ({len(unmatched)}종) — 마스터 SKU 확장 후보")
    L.append("")
    L.append("> 정본 미등록이거나 해외(영문/중문) 매칭 규칙 밖. 무리한 병합 대신 미매칭으로 남김"
             "(서로 다른 제품 오병합 방지 원칙).")
    L.append("")
    for u in unmatched[:40]:
        L.append(f"- `{u}`")
    if len(unmatched) > 40:
        L.append(f"- … 외 {len(unmatched) - 40}종 (전체는 `assets/whisky-aliases.csv` status=unmatched)")
    L.append("")
    L.append("## 산출물")
    L.append("")
    L.append("- `data/whisky-prices/normalized/normalized_prices.csv` — 정규화된 통합 데이터셋(clean 단품)")
    L.append("- `data/whisky-prices/normalized/normalized_all_rows.csv` — 전수 행(제외/오염 사유 포함, 감사용)")
    L.append("- `assets/master-sku.csv` — 마스터 SKU 사전(정본 id별 별칭수·행수·마켓·가격대)")
    L.append("- `assets/whisky-aliases.csv` — 별칭 사전(raw→정본 id, 전 소스 전수)")
    L.append("")
    return "\n".join(L) + "\n"


if __name__ == "__main__":
    run(quiet="--quiet" in sys.argv)
