#!/usr/bin/env python3
"""
CMPA-12 / CMPA-11 — Japan whisky price collection POC (Rakuten Ichiba Item Search API).

INTERNAL R&D ONLY (CMPA-7 frame): measurement, not published / commercial surface.

Pipeline (drop-in-key-and-go):
  collect  -> Rakuten Ichiba Item Search API (LIVE if RAKUTEN_APP_ID set, else recorded-shape fixture)
  parse    -> regex extract (brand, age, volume_ml, price_JPY, seller, url) + non-bottle noise filter
  normalize-> canonical bottle name (KR) via alias dict
  convert  -> JPY -> KRW at live/declared FX
  tax      -> Korea cumulative import-tax estimate (관세20 / 주세72 / 교육세30 / 부가10)
  load     -> CSV with country/currency/fx/tax columns (extends CMPA-1 schema)

Reused back-end (per CMPA-6 reuse note): the parser / name-normalization / FX-tax
normalization / CMPA-1 load schema. The OCR front-end is NOT reused (prices are JSON text).
The FX+tax block is split into a country-agnostic component (import_landed_cost) reusable
by CMPA-13 (Taiwan) / CMPA-14 (Hong Kong).

Usage:
  python3 rakuten_poc.py                 # fixture mode (default), writes CSV + metrics
  RAKUTEN_APP_ID=xxxx python3 rakuten_poc.py   # LIVE mode, real API calls
  FX_JPY_KRW=9.46 python3 rakuten_poc.py       # override FX rate
"""
import csv
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

# 공통 환율·세금 정규화 컴포넌트(국가 무관) — CMPA-13/14가 동일 모듈 재사용.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from pipelines.common.fx_tax import KR_TAX, import_landed_cost  # noqa: E402
from pipelines.common.dated import snapshot  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
FIXTURE = os.path.join(HERE, "fixtures", "rakuten_sample.json")
DEFAULT_OUT = os.path.join(HERE, "..", "..", "data", "whisky-prices", "jp",
                           "2026-05_jp_rakuten_poc.csv")

RAKUTEN_ENDPOINT = "https://app.rakuten.co.jp/services/api/IchibaItem/Search/20220601"
COLLECT_DATE = os.environ.get("COLLECT_DATE", "2026-05-30")
FX_JPY_KRW = float(os.environ.get("FX_JPY_KRW", "9.458761"))  # live 2026-05-30 (open.er-api.com)

# Keywords to query (the fixture mirrors these). Japanese names per Rakuten catalog.
KEYWORDS = [
    "サントリー 山崎", "サントリー 白州", "サントリー 響", "ニッカ 竹鶴", "ニッカ 余市",
    "ニッカ 宮城峡", "ニッカ フロムザバレル", "ニッカ セッション", "ニッカ カフェグレーン",
    "サントリー 知多", "キリン 富士", "イチローズモルト", "マルス 駒ヶ岳",
    "厚岸 ウイスキー", "サントリー 角瓶",
    "サントリー 季 TOKI", "ニッカ デイズ", "マツイ 倉吉", "明石 ホワイトオーク", "マルス 津貫",
]

# ----------------------------------------------------------------------------
# Brand dictionary: canonical_key -> (Korean display name, [alias substrings])
# Order matters: more specific aliases first so partial overlaps resolve correctly.
# ----------------------------------------------------------------------------
BRANDS = [
    ("yamazaki",            "야마자키",            ["山崎", "yamazaki"]),
    ("hakushu",             "하쿠슈",              ["白州", "hakushu"]),
    ("hibiki",              "히비키",              ["響", "hibiki"]),
    ("taketsuru",           "타케츠루",            ["竹鶴", "taketsuru"]),
    ("yoichi",              "요이치",              ["余市", "yoichi"]),
    ("miyagikyo",           "미야기쿄",            ["宮城峡", "miyagikyo"]),
    ("nikka_from_the_barrel","니카 프롬더배럴",     ["フロム・ザ・バレル", "フロムザバレル", "from the barrel", "from-the-barrel"]),
    ("nikka_session",       "니카 세션",           ["セッション", "session"]),
    ("nikka_coffey_grain",  "니카 카페그레인",      ["カフェグレーン", "coffey grain", "coffey"]),
    ("chita",               "치타",                ["知多", "chita"]),
    ("fuji",                "후지",                ["富士", "fuji"]),
    ("ichiros_malt",        "이치로스 몰트",        ["イチローズモルト", "ichiro"]),
    ("mars_komagatake",     "마르스 코마가타케",     ["駒ヶ岳", "komagatake"]),
    ("akkeshi",             "앗케시",              ["厚岸", "akkeshi"]),
    ("kakubin",             "산토리 가쿠빈",        ["角瓶", "kakubin"]),
    ("toki",                "산토리 토키",          ["季 toki", "サントリー 季", "toki"]),
    ("nikka_days",          "니카 데이즈",          ["デイズ", "nikka days"]),
    ("kurayoshi",           "마쓰이 쿠라요시",       ["倉吉", "kurayoshi", "松井"]),
    ("akashi",              "아카시(에이가시마)",    ["明石", "ホワイトオーク", "akashi", "江井ヶ嶋"]),
    ("tsunuki",             "마르스 쓰누키",         ["津貫", "tsunuki"]),
]

# Non-bottle noise markers (glassware, empties, toys, multi-unit sets, cases, cans).
NOISE_MARKERS = [
    "グラス", "タンブラー", "コースター", "空瓶", "空きボトル", "空き瓶",
    "ぬいぐるみ", "マスコット", "ノベルティ", "tシャツ", "tシャツ", "ｔシャツ",
    "セット", "まとめ買い", "本セット", "ケース",
]


def fetch_query(keyword, app_id):
    """LIVE Rakuten Ichiba Item Search. Returns the parsed JSON response dict."""
    params = {
        "applicationId": app_id,
        "format": "json",
        "keyword": keyword,
        "hits": 30,
        "page": 1,
        "sort": "+itemPrice",
        "availability": 1,
    }
    url = RAKUTEN_ENDPOINT + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "WK-rnd-poc/0.1"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8"))


def collect():
    """Yield (keyword, response_dict). LIVE if RAKUTEN_APP_ID set, else fixture."""
    app_id = os.environ.get("RAKUTEN_APP_ID")
    if app_id:
        print(f"[collect] LIVE mode — RAKUTEN_APP_ID present, querying {len(KEYWORDS)} keywords")
        for kw in KEYWORDS:
            t0 = time.time()
            try:
                resp = fetch_query(kw, app_id)
            except Exception as e:  # noqa: BLE001
                print(f"  ! {kw}: API error {e}")
                continue
            dt = time.time() - t0
            n = resp.get("hits", len(resp.get("Items", [])))
            print(f"  + {kw}: {n} hits in {dt:.2f}s")
            yield kw, resp
            time.sleep(1.0)  # be polite to the quota (1 req/s)
    else:
        print(f"[collect] FIXTURE mode — no RAKUTEN_APP_ID. Loading {FIXTURE}")
        with open(FIXTURE, encoding="utf-8") as f:
            data = json.load(f)
        for q in data["queries"]:
            yield q["keyword"], q["response"]


# ----------------------------------------------------------------------------
# Parser / normalizer
# ----------------------------------------------------------------------------
def is_noise(name):
    low = name.lower()
    return any(m.lower() in low for m in NOISE_MARKERS)


def detect_brand(name):
    low = name.lower()
    for key, kr, aliases in BRANDS:
        for a in aliases:
            if a.lower() in low:
                return key, kr
    return None, None


def extract_volume_ml(name):
    # match 700ml / 1920ml / 1.75L / 0.7L etc.
    m = re.search(r"(\d+(?:\.\d+)?)\s*(ml|ML|ｍｌ)", name)
    if m:
        return int(round(float(m.group(1))))
    m = re.search(r"(\d+(?:\.\d+)?)\s*[lL]", name)
    if m:
        return int(round(float(m.group(1)) * 1000))
    return None


def extract_age(name):
    m = re.search(r"(\d{1,2})\s*年", name)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d{1,2})\s*(?:year|yo|y\.o)", name, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def canonical_name(kr, age, volume_ml):
    parts = [kr]
    if age:
        parts.append(f"{age}년")
    else:
        parts.append("NAS")
    if volume_ml:
        parts.append(f"{volume_ml}ml")
    return " ".join(parts)


def parse_item(item):
    """Return a structured bottle dict, or None if non-bottle noise / unmatched."""
    name = item.get("itemName", "")
    price = item.get("itemPrice")
    if not name or not isinstance(price, (int, float)) or price <= 0:
        return None
    if is_noise(name):
        return {"_noise": True}
    brand, kr = detect_brand(name)
    if not brand:
        return None  # could not match to a known bottle
    age = extract_age(name)
    volume = extract_volume_ml(name)
    return {
        "brand": brand,
        "name_kr": canonical_name(kr, age, volume),
        "age": age,
        "volume_ml": volume,
        "price_jpy": int(price),
        "seller": item.get("shopName", ""),
        "url": item.get("itemUrl", ""),
        "item_code": item.get("itemCode", ""),
        "raw_name": name,
    }


# ----------------------------------------------------------------------------
# FX + Korea import-tax — 이제 공통 모듈 pipelines.common.fx_tax 에서 import.
# (KR_TAX / import_landed_cost 는 한 곳에서만 정의 → CMPA-13/14 동일 재사용)
# ----------------------------------------------------------------------------
def to_krw(jpy, fx=FX_JPY_KRW):
    return jpy * fx


# ----------------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------------
def main():
    out_path = os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else DEFAULT_OUT)
    bottles = []
    metrics = {
        "queries": 0, "items_total": 0,
        "parsed_noise": 0, "parsed_bottle": 0, "parsed_none": 0,
        # self-grading vs fixture ground truth (LIVE mode has no _gt -> skipped)
        "gt_available": 0, "gt_bottle": 0, "gt_noise": 0,
        "brand_correct": 0, "volume_correct": 0,
        "noise_tp": 0, "noise_fp": 0, "noise_fn": 0,
    }

    for kw, resp in collect():
        metrics["queries"] += 1
        items = resp.get("Items", [])
        for wrap in items:
            item = wrap.get("Item", wrap)
            metrics["items_total"] += 1
            gt = item.get("_gt", "__missing__")  # ground truth (fixture only)
            parsed = parse_item(item)

            # classify parser output
            if parsed is None:
                metrics["parsed_none"] += 1
                parsed_is_bottle = False
                parsed_is_noise = False
            elif parsed.get("_noise"):
                metrics["parsed_noise"] += 1
                parsed_is_bottle = False
                parsed_is_noise = True
            else:
                metrics["parsed_bottle"] += 1
                parsed_is_bottle = True
                parsed_is_noise = False
                bottles.append((kw, parsed))

            # self-grade against ground truth when present
            if gt != "__missing__":
                metrics["gt_available"] += 1
                gt_is_bottle = gt is not None
                if gt_is_bottle:
                    metrics["gt_bottle"] += 1
                else:
                    metrics["gt_noise"] += 1
                # noise-filter confusion (positive class = "noise/non-bottle")
                if not gt_is_bottle and parsed_is_noise:
                    metrics["noise_tp"] += 1
                if gt_is_bottle and parsed_is_noise:
                    metrics["noise_fp"] += 1
                if not gt_is_bottle and not parsed_is_noise:
                    metrics["noise_fn"] += 1
                # brand / volume accuracy on true bottles that we parsed as bottles
                if gt_is_bottle and parsed_is_bottle:
                    if parsed["brand"] == gt.get("brand"):
                        metrics["brand_correct"] += 1
                    if parsed["volume_ml"] == gt.get("volume_ml"):
                        metrics["volume_correct"] += 1

    # ---- write CSV ----
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    cols = ["술이름", "브랜드", "숙성년수", "용량_ml", "원가격_JPY", "통화",
            "환율_1JPY_KRW", "가격_KRW", "관세_KRW", "주세_KRW", "교육세_KRW", "부가세_KRW",
            "한국반입추정가_KRW", "반입배수", "국가", "셀러", "URL", "itemCode",
            "가져온날짜", "출처", "신뢰도", "비고"]
    rows = 0
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for kw, b in bottles:
            krw = to_krw(b["price_jpy"])
            tax = import_landed_cost(krw)
            note = ""
            if b["volume_ml"] and b["volume_ml"] < 500:
                note = f"소용량({b['volume_ml']}ml) — 700ml 환산 아님, 직접비교 주의"
            elif b["volume_ml"] and b["volume_ml"] > 1000:
                note = f"대용량({b['volume_ml']}ml)"
            w.writerow([
                b["name_kr"], b["brand"], b["age"] or "", b["volume_ml"] or "",
                b["price_jpy"], "JPY", FX_JPY_KRW, round(krw),
                tax["customs"], tax["liquor"], tax["education"], tax["vat"],
                tax["landed_total"], tax["multiplier"], "일본(JP)",
                b["seller"], b["url"], b["item_code"], COLLECT_DATE,
                f"Rakuten Ichiba API ({kw})", "중", note,
            ])
            rows += 1
    snap = snapshot(out_path, run_date=COLLECT_DATE if len(COLLECT_DATE) == 10 else None)

    # ---- metrics report ----
    m = metrics
    raw_hit = m["parsed_bottle"] / m["items_total"] if m["items_total"] else 0
    bottle_recall = m["parsed_bottle"] / m["gt_bottle"] if m["gt_bottle"] else None
    brand_acc = m["brand_correct"] / m["parsed_bottle"] if m["parsed_bottle"] else None
    vol_acc = m["volume_correct"] / m["parsed_bottle"] if m["parsed_bottle"] else None
    noise_prec = m["noise_tp"] / (m["noise_tp"] + m["noise_fp"]) if (m["noise_tp"] + m["noise_fp"]) else None
    noise_rec = m["noise_tp"] / (m["noise_tp"] + m["noise_fn"]) if (m["noise_tp"] + m["noise_fn"]) else None

    print("\n" + "=" * 64)
    print("CMPA-12 Rakuten POC — METRICS")
    print("=" * 64)
    print(f"FX: 1 JPY = {FX_JPY_KRW} KRW   collect_date={COLLECT_DATE}")
    print(f"keyword queries        : {m['queries']}")
    print(f"items returned (total) : {m['items_total']}")
    print(f"  -> parsed as bottle  : {m['parsed_bottle']}")
    print(f"  -> filtered as noise : {m['parsed_noise']}")
    print(f"  -> unmatched/dropped : {m['parsed_none']}")
    print(f"CSV rows written       : {rows}  -> {out_path}")
    print("-" * 64)
    print(f"raw parse hit-rate (bottle/all items)   : {raw_hit:.1%}")
    if bottle_recall is not None:
        print(f"bottle recall (parsed/true bottles)     : {bottle_recall:.1%}  ({m['parsed_bottle']}/{m['gt_bottle']})")
    if brand_acc is not None:
        print(f"brand matching accuracy                 : {brand_acc:.1%}  ({m['brand_correct']}/{m['parsed_bottle']})")
    if vol_acc is not None:
        print(f"volume extraction accuracy              : {vol_acc:.1%}  ({m['volume_correct']}/{m['parsed_bottle']})")
    if noise_prec is not None:
        print(f"noise-filter precision / recall         : {noise_prec:.1%} / {noise_rec:.1%}")
    print("-" * 64)
    sample = import_landed_cost(to_krw(13800))  # 山崎NV ¥13,800 worked example
    print("tax worked example — Yamazaki NV ¥13,800:")
    print(f"  CIF(KRW)={sample['cif']:,}  관세={sample['customs']:,}  주세={sample['liquor']:,}"
          f"  교육세={sample['education']:,}  부가세={sample['vat']:,}")
    print(f"  => 한국반입추정가 {sample['landed_total']:,} KRW  (배수 {sample['multiplier']}x)")
    print("=" * 64)

    # machine-readable metrics for the issue comment
    metrics_path = os.path.join(os.path.dirname(out_path), "_poc_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump({
            "fx_jpy_krw": FX_JPY_KRW, "collect_date": COLLECT_DATE,
            "queries": m["queries"], "items_total": m["items_total"],
            "parsed_bottle": m["parsed_bottle"], "parsed_noise": m["parsed_noise"],
            "parsed_none": m["parsed_none"], "csv_rows": rows,
            "snapshot": snap,
            "raw_hit_rate": round(raw_hit, 4),
            "bottle_recall": round(bottle_recall, 4) if bottle_recall is not None else None,
            "brand_accuracy": round(brand_acc, 4) if brand_acc is not None else None,
            "volume_accuracy": round(vol_acc, 4) if vol_acc is not None else None,
            "noise_precision": round(noise_prec, 4) if noise_prec is not None else None,
            "noise_recall": round(noise_rec, 4) if noise_rec is not None else None,
            "tax_multiplier": sample["multiplier"],
        }, f, ensure_ascii=False, indent=2)
    print(f"metrics json -> {metrics_path}")


if __name__ == "__main__":
    main()
