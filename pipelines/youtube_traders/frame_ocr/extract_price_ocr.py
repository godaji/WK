#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_price_ocr.py — CMPA-423 (3/3) crop 이미지 → (제품명, 가격_KRW, 용량_ml)

가격표 crop(crop_price_tag.py 산출) 한 장을 OCR(한글) 해 **제품명 + 가격(KRW) + 용량(ml)** 을
구조화 dict 로 뽑는다. 가격표 레이아웃(상단=제품명 KR/EN/용량, 하단=큰 폰트 가격)을
이용해 휴리스틱으로 필드를 선택하고, 회사 공통 가드(is_bundle_noise·is_sane_price)로
노이즈를 거른다. 용량(700/750/1000/1750ml 등)은 제품명 라인 우선, 없으면 가격표 내 용량
토큰에서 뽑되 OCR 의 끝-l 누락('750m')은 표준 소매 용량일 때만 보정 인정한다(CMPA-423 보드).

OCR 엔진: **PaddleOCR 3.6.0 `lang=korean`** (CMPA-172 POC 에서 GO 확정).
  ⚠️ `enable_mkldnn=False` 필수(CMPA-6 교훈), orientation/unwarp 분류 off(속도).

함수 API(후속 어댑터가 import):
  ocr_engine()                  → 싱글턴 PaddleOCR
  ocr_lines(img_or_path)        → [{'t','s','x','y','w','h'}, ...] (텍스트/신뢰도/박스)
  extract_fields(lines)         → {'name','price','volume_ml','raw_names','raw_prices'} (없으면 None)
  extract_from_crop(path)       → extract_fields(ocr_lines(path)) + {'crop'}

CLI(폴더 E2E):
  python3 extract_price_ocr.py CROPS_DIR [--min-score 0.80] [--out result.csv]
  (CROPS_DIR/manifest.csv 의 각 crop 을 OCR → 제품 단위 dedup → CSV/표)
"""
import argparse
import csv
import os
import re
import sys
import warnings

warnings.filterwarnings("ignore")

# 회사 공통 게이트 재사용(번들 노이즈·가격 하한)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from pipelines.common.whisky_quality import is_bundle_noise, is_sane_price  # noqa: E402

NUM = re.compile(r"\d{1,3}(?:,\d{3})+|\d{4,7}")
# 코스트코 가격 태그: "279,000원" 같이 "원" 접미사가 붙은 가격 — OCR이 '0'→'c'/'o'/'O' 로
# 오인하는 경우도 보정해 파싱한다(실측: "279,c00원").
_PRICE_WON_RE = re.compile(r"([0-9,cCoO]{4,})원")
# 용량 토큰(700ml/750ml/1L/1.75L). 'ml/mL' 을 먼저 보고 그다음 'L'(리터)를 ×1000 —
# '700ml' 의 l 을 리터로 오인하지 않기 위함(build_weekly_digest.parse_volume_ml 과 동일 규약).
VOL_ML = re.compile(r"(\d+(?:[.,]\d+)?)\s*[mM][lL]\b")
VOL_L = re.compile(r"(?<![mM])(\d+(?:[.,]\d+)?)\s*[lL]\b")
# OCR 이 끝의 'l' 을 자주 떨어뜨린다('750ml'→'750m', '700ml'→'700m', 실측 k3GQq).
# 끝-l 누락 보정: '<숫자>m'(l 없음)은 그 값이 **표준 소매 용량**일 때만 ml 로 인정(오인 방어).
VOL_ML_NOL = re.compile(r"(\d{3,4})\s*[mM](?![lL])\b")
KNOWN_VOLS = {200, 350, 375, 500, 700, 750, 1000, 1500, 1750}
# 가격표/매대에 흔한 비-제품명 노이즈 토큰
NOISE = ("신세계", "포인트", "적립", "할인", "행사", "원산지", "용량", "바코드",
         "traders", "wholesale", "club", "이마트", "emart")

_OCR = None


def ocr_engine():
    """PaddleOCR 싱글턴(모델 로드 1회)."""
    global _OCR
    if _OCR is None:
        from paddleocr import PaddleOCR
        _OCR = PaddleOCR(
            lang="korean",
            # CPU-only(ffmpeg 없음·저사양) → det 도 **mobile** 로 고정. server det 은
            # 103장 crop 에 분 단위로 느려 SIGTERM(타임아웃)으로 죽는다. mobile 은 수배 빠르고
            # 가격표(또렷한 큰 글자) 인식엔 충분(가성비 우선).
            text_detection_model_name="PP-OCRv5_mobile_det",
            text_recognition_model_name="korean_PP-OCRv5_mobile_rec",
            use_doc_orientation_classify=False,
            use_doc_unwarping=False,
            use_textline_orientation=False,
            enable_mkldnn=False,
        )
    return _OCR


def ocr_lines(img):
    """이미지(경로 또는 ndarray) → 박스 리스트. 박스 y/h 로 폰트크기·위치 추정."""
    res = ocr_engine().predict(img)
    out = []
    for r in res:
        texts = r.get("rec_texts", [])
        scores = r.get("rec_scores", [])
        polys = r.get("rec_polys", r.get("dt_polys", []))
        for i, t in enumerate(texts):
            s = scores[i] if i < len(scores) else 0.0
            if i < len(polys) and polys[i] is not None:
                p = polys[i]
                xs = [pt[0] for pt in p]
                ys = [pt[1] for pt in p]
                x, y = min(xs), min(ys)
                w, h = max(xs) - x, max(ys) - y
            else:
                x = y = w = h = 0
            out.append({"t": t, "s": float(s), "x": float(x), "y": float(y),
                        "w": float(w), "h": float(h)})
    return out


def _is_hangul(s):
    return any("가" <= c <= "힣" for c in s)


def pick_name(lines, min_score=0.80):
    """제품명 = 신뢰도 충분한 '한글 포함' 라인 중 최상단.
    코스트코 가격 태그처럼 브랜드/제품명이 두 줄로 나뉜 경우(발베니 / 12년아메리칸오크)
    인접한 두 번째 한글 줄도 합쳐서 반환한다."""
    cand = [l for l in lines
            if _is_hangul(l["t"]) and l["s"] >= min_score and len(l["t"].strip()) >= 3
            and not any(n in l["t"].lower() for n in NOISE)
            and not NUM.fullmatch(l["t"].replace(" ", ""))
            and not _PRICE_WON_RE.search(l["t"])       # 가격 라인(279,000원 등)은 이름 아님
            and "/" not in l["t"]]                    # 단가/100ml 같은 단가 라인 제외
    if not cand:
        return ""
    cand.sort(key=lambda l: (l["y"], -len(l["t"])))      # 최상단 우선, 동률이면 긴 것
    first = cand[0]
    name_parts = [re.sub(r"\s+", " ", first["t"]).strip()]
    # 두 번째 한글 줄이 첫 줄과 y 거리 ≤ 첫 줄 높이×2이면 이름의 일부로 병합
    # (트레이더스 영상은 이름이 1줄이라 해당 없음; 코스트코 2줄 이름 대응)
    if len(cand) > 1:
        second = cand[1]
        gap = second["y"] - (first["y"] + first["h"])
        if gap <= first["h"] * 2:
            name_parts.append(re.sub(r"\s+", " ", second["t"]).strip())
    return " ".join(name_parts)


def parse_volume_ml(text):
    """텍스트 1줄에서 용량(ml) 추출. 파싱 불가→None.
    700ml→700, 750ml→750, 1L→1000, 1.75L→1750. (OCR 콤마/공백 허용)
    끝-l 누락('750m')은 표준 소매 용량일 때만 보정 인정."""
    if not text:
        return None
    m = VOL_ML.search(text)
    if m:
        return int(round(float(m.group(1).replace(",", ".")) ))
    m = VOL_L.search(text)
    if m:
        return int(round(float(m.group(1).replace(",", ".")) * 1000))
    m = VOL_ML_NOL.search(text)              # '750m' 등 끝-l 누락 보정(표준 용량만)
    if m:
        v = int(m.group(1))
        if v in KNOWN_VOLS:
            return v
    return None


def pick_volume(lines, name="", min_score=0.60):
    """용량 = 제품명 라인에 붙은 용량(우선) 또는 가격표 내 별도 용량 토큰.
    표준 소매 용량(700/750/1000/1750ml 등)을 우선 신뢰, 그 외는 OCR 오인 가능성."""
    v = parse_volume_ml(name)
    if v:
        return v
    cands = []
    for l in lines:
        if l["s"] < min_score:
            continue
        vv = parse_volume_ml(l["t"])
        if vv:
            cands.append(vv)
    for vv in cands:                         # 표준 소매 용량에 맞는 값 우선 채택
        if vv in KNOWN_VOLS:
            return vv
    return cands[0] if cands else None


def _parse_price_won(text):
    """'원' 접미사 가격 텍스트에서 KRW 파싱. OCR 이 '0'→'c'/'o'/'O' 오인 보정(코스트코 실측)."""
    m = _PRICE_WON_RE.search(text)
    if not m:
        return None
    raw = m.group(1).replace(",", "").replace("c", "0").replace("C", "0").replace("o", "0").replace("O", "0")
    try:
        v = int(raw)
        return v if is_sane_price(v) else None
    except ValueError:
        return None


def pick_price(lines, min_score=0.70):
    """가격 = (단가/할인 제외) 숫자 토큰 중 가장 큰 폰트(박스 높이)로 렌더된 값.
    종이 가격표는 최종가가 가장 크게 박혀 있다.
    '원' 접미사 가격 라인(코스트코 방식)을 1순위로 파싱해 OCR 오인 문자도 보정한다."""
    # 1순위: '원' 접미사가 붙은 라인(가장 큰 h) — 코스트코 가격 태그 방식
    won_cands = []
    for l in lines:
        if l["s"] < min_score:
            continue
        if "ml당" in l["t"] or "당" in l["t"] or "/" in l["t"]:
            continue
        if any(n in l["t"] for n in ("적립", "할인")):
            continue
        v = _parse_price_won(l["t"])
        if v is not None:
            won_cands.append((l["h"], v))
    if won_cands:
        won_cands.sort(key=lambda x: -x[0])              # 가장 큰 폰트(h) 우선 = 최종가
        return won_cands[0][1]

    # 2순위: 기존 — 숫자 토큰 중 가장 큰 폰트
    best = None  # (h, value)
    for l in lines:
        t = l["t"]
        if l["s"] < min_score:
            continue
        if "ml당" in t or "당" in t or "/" in t:        # 100ml당 단가 제외
            continue
        if any(n in t for n in ("적립", "할인")):
            continue
        for m in NUM.finditer(t):
            v = int(m.group().replace(",", ""))
            if not is_sane_price(v):                      # 15,000원 하한(공통 게이트)
                continue
            if best is None or l["h"] > best[0]:
                best = (l["h"], v)
    return best[1] if best else None


def extract_fields(lines, min_score=0.80):
    name = pick_name(lines, min_score)
    price = pick_price(lines)
    volume_ml = pick_volume(lines, name or "")            # 700/750/1000/1750ml 등(CMPA-423 보드)
    if name and is_bundle_noise(name):                    # 잔세트/번들 노이즈 차단
        name = ""
    return {
        "name": name or None,
        "price": price,
        "volume_ml": volume_ml,
        "raw_names": [l["t"] for l in lines if _is_hangul(l["t"])],
        "raw_prices": sorted({int(m.group().replace(",", ""))
                              for l in lines for m in NUM.finditer(l["t"])
                              if is_sane_price(int(m.group().replace(",", "")))}),
    }


def extract_from_crop(path, min_score=0.80):
    d = extract_fields(ocr_lines(path), min_score)
    d["crop"] = os.path.basename(path)
    return d


def _norm(s):
    return re.sub(r"\s+", "", s)


def dedup_segments(per):
    """연속 프레임을 같은 제품 단위로 묶어 modal name/price/volume 로 정리.
    per = [(crop, t_sec, name, price, volume_ml), ...] (시간순)."""
    segs = []
    cur = None
    for crop, t, name, price, volume_ml in per:
        if not name or not price:
            continue
        k = _norm(name)
        if cur and (k == cur["k"] or (len(k) >= 4 and (k in cur["k"] or cur["k"] in k))):
            cur["names"][name] = cur["names"].get(name, 0) + 1
            cur["prices"][price] = cur["prices"].get(price, 0) + 1
            if volume_ml:
                cur["vols"][volume_ml] = cur["vols"].get(volume_ml, 0) + 1
            cur["n"] += 1
            cur["t_end"] = t
        else:
            cur = {"k": k, "names": {name: 1}, "prices": {price: 1},
                   "vols": ({volume_ml: 1} if volume_ml else {}), "n": 1,
                   "t_start": t, "t_end": t}
            segs.append(cur)
    out = []
    for s in segs:
        name = max(s["names"].items(), key=lambda x: (x[1], len(x[0])))[0]
        price = max(s["prices"].items(), key=lambda x: x[1])[0]
        vol = max(s["vols"].items(), key=lambda x: x[1])[0] if s["vols"] else None
        out.append({"name": name, "price": price, "volume_ml": vol, "n_frames": s["n"],
                    "t_start": s["t_start"], "t_end": s["t_end"]})
    return out


def run_dir(crops_dir, min_score=0.80, out_csv=None):
    man = os.path.join(crops_dir, "manifest.csv")
    if os.path.exists(man):
        with open(man, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    else:
        rows = [{"crop": p, "t_sec": ""}
                for p in sorted(os.listdir(crops_dir)) if p.endswith(".jpg")]

    # 재개 캐시(CMPA-489): PaddleOCR CPU 가 영상당 ~10분이라 백그라운드 OCR 이 종료 신호로
    # 중간에 죽으면 매번 처음부터다. crop 단위 결과를 즉시 JSONL 로 flush 해, 재실행 시
    # 이미 OCR 한 crop 은 건너뛰고 남은 것만 처리한다(전진 보장·멱등).
    import json as _json
    cache_path = os.path.join(crops_dir, ".ocr_cache.jsonl")
    cache = {}
    if os.path.exists(cache_path):
        with open(cache_path, encoding="utf-8") as f:
            for line in f:
                try:
                    c = _json.loads(line)
                    cache[c["crop"]] = c
                except Exception:                         # noqa: BLE001 — 깨진 줄 무시
                    continue
    if cache:
        print(f"[ocr] 재개 캐시 {len(cache)} crop 사용 — 남은 것만 OCR", file=sys.stderr)

    per = []
    for r in rows:
        crop = r["crop"]
        path = os.path.join(crops_dir, crop)
        if not os.path.exists(path):
            continue
        if crop in cache:
            d = cache[crop]
        else:
            d = extract_from_crop(path, min_score)
            with open(cache_path, "a", encoding="utf-8") as cf:
                cf.write(_json.dumps({"crop": crop, "name": d["name"],
                                      "price": d["price"],
                                      "volume_ml": d.get("volume_ml")},
                                     ensure_ascii=False) + "\n")
        try:
            t = float(r.get("t_sec") or 0)
        except ValueError:
            t = 0.0
        per.append((crop, t, d["name"], d["price"], d.get("volume_ml")))
    per.sort(key=lambda x: x[1])
    segs = dedup_segments(per)

    print(f"\n=== OCR 추출: 프레임 {len(per)}장 → 제품 {len(segs)}종 ===")
    for s in segs:
        vol = f"{s['volume_ml']}ml" if s.get("volume_ml") else "용량?"
        print(f"  {s['price']:>8,}원 | {vol:>7} | {s['name']}  "
              f"(x{s['n_frames']}f, {s['t_start']:.0f}~{s['t_end']:.0f}s)")

    if out_csv:
        with open(out_csv, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=["name", "price", "volume_ml", "n_frames",
                                              "t_start", "t_end"])
            w.writeheader()
            w.writerows(segs)
        print(f"\n[ocr] 결과 CSV → {out_csv}", file=sys.stderr)
    return segs


def main():
    ap = argparse.ArgumentParser(description="가격표 crop → (제품명, 가격) OCR 추출")
    ap.add_argument("crops_dir", help="crop_price_tag.py 산출 폴더")
    ap.add_argument("--min-score", type=float, default=0.80, help="제품명 OCR 신뢰도 하한")
    ap.add_argument("--out", default=None, help="결과 CSV 경로")
    a = ap.parse_args()
    run_dir(a.crops_dir, a.min_score, a.out)


if __name__ == "__main__":
    main()
