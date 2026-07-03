#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collect_ssand_ocr.py — 싼디(@SSanD3) 조양마트·동부마트 위스키 '실매대(종이 가격표)'
영상에서 OCR 로 (제품명·최종가·용량·촬영일·seller) 를 수집해 월간 CSV 에 적재하는
수집기 (CMPA-190; CMPA-186 스파이크 후속).

@whiskeykey(CMPA-172) 는 합성 그래픽 오버레이(1제품/카드)라 단순했지만, 싼디는
**실제 매대 패닝 촬영**이라 세 가지 신규 처리가 필요(스파이크 §4):
  1) 이름↔가격 공간매칭 : 프레임당 다수 제품 → 가격표 bbox 위의 제품명 bbox 를 y/x 페어링
  2) 안정 프레임 선택    : 패닝 모션블러 배제(샤프니스+장면변화), 제품군당 정지프레임
  3) 정규화 내성        : 태그 OCR 오류 큼 → normalize_whisky_name 정본 id + 신뢰도 임계 + 수기검수

서브커맨드:
  discover  채널 영상목록에서 조양/동부 위스키 영상 필터(실업로드일 포함)
  fetch     video 다운로드(480p) → 안정프레임 선택 → PaddleOCR(korean) → 프레임별 OCR json 캐시
  parse     캐시 OCR → 이름↔가격 공간매칭 → 정규화/번들제외/dedup → 행(네트워크 X, 결정론)
  load      parse → 월간 CSV dedup append (seller·촬영일 보존)

OCR: PaddleOCR(lang='korean', enable_mkldnn=False)  (CMPA-6)
거버넌스: 내부 R&D 만. 공개배포 게이트(c7405e7d)는 본 범위 아님.

용법:
  python3 pipelines/ssand_marts/collect_ssand_ocr.py discover --limit 120
  python3 pipelines/ssand_marts/collect_ssand_ocr.py fetch --video OGpmIb-_acI --seller 조양마트
  python3 pipelines/ssand_marts/collect_ssand_ocr.py parse --video OGpmIb-_acI [--min-score 0.55]
  python3 pipelines/ssand_marts/collect_ssand_ocr.py load  --video OGpmIb-_acI [--month 2026-06] \
        [--out data/whisky-prices/2026-06.csv] [--dry-run]
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "scripts"))

PRICES_DIR = os.path.join(ROOT, "data", "whisky-prices")
CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".cache")

SCHEMA = ["술이름", "가격_KRW", "위치", "가져온날짜", "출처", "신뢰도", "비고"]

# 채널·판매처 키워드(인트로/제목에서 seller 식별). 조양·동부는 '별개 판매처' — 뭉개지 말 것.
SELLER_KEYWORDS = {
    "조양마트": ["조양"],
    "동부마트": ["동부"],
}

# 가격: 99,800 / 99800 / 159,000 (콤마형 또는 평문 4~7자리). '원' 접미 없을 수 있음(종이태그).
PRICE_RE = re.compile(r"(?<!\d)(\d{1,3}(?:,\d{3})+|\d{4,7})(?!\d)")
# 용량: 700ml / 750ml / 1l / 1.75l / 1리터
VOL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|밀리|l|리터)\b", re.I)
# 날짜: 2026.6.1 / 2026.06.01 / 2026-06-01 / 2026/6/1
DATE_RE = re.compile(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})")
HANGUL_RE = re.compile(r"[가-힣]")

# 번들/잔세트/비단품 노이즈 — 단품 가격행에서 제외 (스파이크 요구 4).
# NOTE: 정본은 pipelines/common/whisky_quality.is_bundle_noise 로 통합 예정(CMPA-177).
#       본 미러에는 해당 모듈이 없어 로컬 헬퍼로 구현하고, 모듈이 생기면 위임하도록 시도한다.
_BUNDLE_RX = re.compile(
    r"(잔\s*세트|잔세트|전용\s*잔|전용잔|미니어처|미니어쳐|선물\s*세트|선물세트|기획|증정|"
    r"패키지|번들|2개입|두개입|2병|미니|\bset\b|\bgift\b)", re.I)


def is_bundle_noise(name):
    """단품이 아닌 번들/세트/증정/미니어처 등이면 True (집계 제외)."""
    try:
        from pipelines.common.whisky_quality import is_bundle_noise as _canon  # type: ignore
        return bool(_canon(name))
    except Exception:
        return bool(_BUNDLE_RX.search(name or ""))


# ──────────────────────────────────────────────────────────────────────────
# discover: 채널 영상에서 조양/동부 위스키 영상 필터 (실업로드일 포함)
# ──────────────────────────────────────────────────────────────────────────
def discover(limit=120, out=None):
    url = "https://www.youtube.com/@SSanD3/videos"
    cmd = ["yt-dlp", "--flat-playlist", "--playlist-end", str(limit),
           "--print", "%(id)s\t%(title)s", url]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-1500:] + "\n")
        raise SystemExit("[discover] yt-dlp 실패")
    rows = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        vid, title = parts[0], parts[1]
        if "위스키" not in title:
            continue
        seller = _seller_from_text(title)
        if seller not in ("조양마트", "동부마트"):
            continue
        rows.append({"video_id": vid, "title": title, "seller": seller})
    # 실업로드일은 flat-playlist 가 신뢰 못해 영상별 메타로 보강(정렬·신선도 판단용)
    for x in rows:
        meta = subprocess.run(
            ["yt-dlp", "--skip-download", "--print", "%(upload_date)s\t%(duration)s",
             f"https://www.youtube.com/watch?v={x['video_id']}"],
            capture_output=True, text=True)
        p = (meta.stdout.strip().split("\t") + ["", ""])[:2]
        x["upload_date"], x["duration"] = p[0], p[1]
    rows.sort(key=lambda r: r.get("upload_date") or "", reverse=True)
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["video_id", "upload_date", "seller", "duration", "title"])
            w.writeheader()
            w.writerows([{k: x.get(k, "") for k in ["video_id", "upload_date", "seller", "duration", "title"]} for x in rows])
    for x in rows:
        print(f"{x['video_id']}\t{x.get('upload_date','')}\t{x['seller']}\t{x['title']}")
    sys.stderr.write(f"[discover] 조양/동부 위스키 영상 {len(rows)}건\n")
    return rows


def _seller_from_text(text):
    t = text or ""
    for seller, kws in SELLER_KEYWORDS.items():
        if any(k in t for k in kws):
            return seller
    return ""


# ──────────────────────────────────────────────────────────────────────────
# fetch: 다운로드 → 안정프레임 선택 → PaddleOCR → 캐시
# ──────────────────────────────────────────────────────────────────────────
def _video_meta(video_id):
    r = subprocess.run(
        ["yt-dlp", "--skip-download", "--print", "%(upload_date)s\n%(title)s\n%(description)s",
         f"https://www.youtube.com/watch?v={video_id}"],
        capture_output=True, text=True)
    parts = r.stdout.split("\n", 2)
    upload = parts[0].strip() if parts else ""
    title = parts[1].strip() if len(parts) > 1 else ""
    desc = parts[2] if len(parts) > 2 else ""
    return upload, title, desc


def _download(video_id, dst):
    # 480p 단일스트림 우선(스파이크 §1). imageio_ffmpeg 번들 바이너리로 merge 회피 위해 단일포맷.
    fmt = "best[height<=480][ext=mp4]/best[height<=480]/best"
    cmd = ["yt-dlp", "-f", fmt, "-o", dst, "--no-part",
           f"https://www.youtube.com/watch?v={video_id}"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(dst):
        sys.stderr.write(r.stderr[-1500:] + "\n")
        raise SystemExit(f"[fetch] 다운로드 실패 {video_id}")
    return dst


def _select_stable_frames(video_path, step_sec=1.0, win_sec=2.5,
                          max_frames=80, intro_sec=22, intro_keep=6):
    """2패스 저메모리 안정프레임 선택.
    pass1: step_sec 간격 (t, 샤프니스, 모션) 측정(프레임 폐기).
    선택  : 모션 낮은 후보 중 win_sec 시간 NMS 로 샤프니스 최대만 → 패닝 블러 배제.
            인트로(t<intro_sec)는 seller/날짜용으로 샤프니스 상위 intro_keep 별도 확보.
    """
    import cv2
    import numpy as np
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    dur = (total / fps) if total else 0
    cands = []  # (t, sharp, motion)
    prev = None
    t = 0.0
    while dur == 0 or t < dur:
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok:
            break
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        sharp = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        small = cv2.resize(gray, (160, 90))
        motion = 0.0 if prev is None else float(np.mean(cv2.absdiff(small, prev)))
        prev = small
        cands.append((round(t, 2), sharp, motion))
        t += step_sec
    cap.release()
    if not cands:
        return []
    body = [c for c in cands if c[0] >= intro_sec]
    intro = [c for c in cands if c[0] < intro_sec]
    # 모션 임계: 본문 후보 모션의 35퍼센타일(정지에 가까운 프레임만)
    if body:
        mot = sorted(c[2] for c in body)
        thr = mot[max(0, int(len(mot) * 0.35) - 1)]
        stable = [c for c in body if c[2] <= max(thr, 1.0)]
    else:
        stable = []
    # 시간 NMS: 샤프니스 desc 그리디, 이미 뽑힌 시간과 win_sec 이내면 skip
    stable.sort(key=lambda c: c[1], reverse=True)
    picked, picked_t = [], []
    for c in stable:
        if all(abs(c[0] - pt) >= win_sec for pt in picked_t):
            picked.append(c)
            picked_t.append(c[0])
        if len(picked) >= max_frames:
            break
    intro.sort(key=lambda c: c[1], reverse=True)
    sel = picked + intro[:intro_keep]
    sel.sort(key=lambda c: c[0])
    return sel  # list of (t, sharp, motion)


def _get_ocr():
    if not hasattr(_get_ocr, "_o"):
        from paddleocr import PaddleOCR
        # PaddleOCR 3.6: 유효 인자만(show_log/use_angle_cls 미지원). enable_mkldnn=False=CMPA-6.
        _get_ocr._o = PaddleOCR(lang="korean", enable_mkldnn=False)
    return _get_ocr._o


def _poly_to_box(poly):
    xs = [float(p[0]) for p in poly]
    ys = [float(p[1]) for p in poly]
    return [min(xs), min(ys), max(xs), max(ys)]


def _normalize_ocr_result(res):
    """PaddleOCR .ocr() 신/구 반환형을 [{box,cx,cy,h,text,score}] 로 통일."""
    items = []

    def add(poly, text, score):
        if not text or not str(text).strip():
            return
        box = _poly_to_box(poly)
        items.append({"box": box, "cx": (box[0] + box[2]) / 2,
                      "cy": (box[1] + box[3]) / 2, "h": box[3] - box[1],
                      "text": str(text).strip(), "score": float(score or 0.0)})

    if res is None:
        return items
    # 신형 predict: [{'rec_texts':[...], 'rec_scores':[...], 'rec_polys'/'dt_polys':[...]}]
    if isinstance(res, list) and res and isinstance(res[0], dict):
        d = res[0]
        texts = d.get("rec_texts") or d.get("texts") or []
        scores = d.get("rec_scores") or d.get("scores") or []
        polys = d.get("rec_polys") or d.get("dt_polys") or d.get("polys") or []
        for i, poly in enumerate(polys):
            t = texts[i] if i < len(texts) else ""
            s = scores[i] if i < len(scores) else 0.0
            add(poly, t, s)
        return items
    # 구형: [[ [poly,(text,score)], ... ]] 또는 [ [poly,(text,score)], ... ]
    page = res[0] if (isinstance(res, list) and res and isinstance(res[0], list)
                      and res[0] and isinstance(res[0][0], (list, tuple))
                      and len(res[0][0]) == 2 and isinstance(res[0][0][0], (list, tuple))
                      and not isinstance(res[0][0][1], (int, float))) else res
    try:
        for line in page:
            poly, rec = line[0], line[1]
            text, score = (rec[0], rec[1]) if isinstance(rec, (list, tuple)) else (rec, 0.0)
            add(poly, text, score)
    except Exception:
        pass
    return items


def fetch(video_id, seller="", keep_video=False, **kw):
    import cv2
    os.makedirs(CACHE_DIR, exist_ok=True)
    vdir = os.path.join(CACHE_DIR, video_id)
    os.makedirs(vdir, exist_ok=True)
    upload, title, desc = _video_meta(video_id)
    seller = seller or _seller_from_text(title)
    mp4 = os.path.join(vdir, "video.mp4")
    if not os.path.exists(mp4):
        _download(video_id, mp4)
    sys.stderr.write(f"[fetch] {video_id} seller={seller} upload={upload} — 프레임 선택…\n")
    sel = _select_stable_frames(mp4, **kw)
    sys.stderr.write(f"[fetch] 안정프레임 {len(sel)}개 → OCR…\n")
    ocr = _get_ocr()
    cap = cv2.VideoCapture(mp4)
    frames_out = []
    for i, (t, sharp, motion) in enumerate(sel):
        cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
        ok, frame = cap.read()
        if not ok:
            continue
        try:
            res = ocr.ocr(frame)
        except Exception as e:
            sys.stderr.write(f"  [ocr-warn] t={t}: {e}\n")
            res = None
        items = _normalize_ocr_result(res)
        frames_out.append({"t": t, "sharp": sharp, "motion": motion,
                           "intro": t < 22, "items": items})
        if (i + 1) % 10 == 0:
            sys.stderr.write(f"  …{i + 1}/{len(sel)}\n")
    cap.release()
    if not keep_video:
        try:
            os.remove(mp4)  # R&D 후 원본 미보관(스파이크 규율)
        except OSError:
            pass
    cache = {"video_id": video_id, "seller": seller, "title": title,
             "upload_date": upload, "description": desc, "frames": frames_out}
    cpath = os.path.join(vdir, "ocr.json")
    with open(cpath, "w", encoding="utf-8") as f:
        json.dump(cache, f, ensure_ascii=False)
    sys.stderr.write(f"[fetch] 캐시 저장 {cpath} (프레임 {len(frames_out)})\n")
    print(cpath)
    return cpath


# ──────────────────────────────────────────────────────────────────────────
# parse: 캐시 OCR → 이름↔가격 공간매칭 → 정규화/dedup → 행 (네트워크 X, 결정론)
# ──────────────────────────────────────────────────────────────────────────
def _extract_date(cache):
    """촬영일: 인트로 프레임 OCR + 설명문에서 YYYY.M.D 추출, 없으면 upload_date."""
    texts = [cache.get("description", "")]
    for fr in cache.get("frames", []):
        if fr.get("intro"):
            texts += [it["text"] for it in fr["items"]]
    for blob in texts:
        m = DATE_RE.search(blob or "")
        if m:
            y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
            if 2000 <= y <= 2099 and 1 <= mo <= 12 and 1 <= d <= 31:
                return f"{y:04d}-{mo:02d}-{d:02d}"
    up = cache.get("upload_date") or ""
    if len(up) == 8 and up.isdigit():
        return f"{up[:4]}-{up[4:6]}-{up[6:]}"
    return ""


def _parse_price(text):
    m = PRICE_RE.search(text or "")
    if not m:
        return None
    v = int(m.group(1).replace(",", ""))
    return v if 15000 <= v <= 8000000 else None  # 위스키 단품 현실범위


_AGE_RE = re.compile(r"(\d{1,2})\s*년")


def _detect_age(name):
    """이름에서 숙성년수 토큰(예: 18년) 추출. 없으면 '' (NAS)."""
    m = _AGE_RE.search(name or "")
    if m and 1 <= int(m.group(1)) <= 50:
        return m.group(1)
    return ""


def _clean_name(raw, name_ko):
    """matched 행 표시용: 선두 OCR 잡음토큰(인접 그래픽 오인식)을 버리고 브랜드부터 유지.
    name_ko 의 토큰과 2글자 이상 겹치는 첫 raw 토큰부터 채택. 못 찾으면 raw 그대로."""
    toks = raw.split()
    kts = [t for t in re.split(r"\s+", name_ko or "") if len(t) >= 2]
    for i, tk in enumerate(toks):
        for kt in kts:
            # 토큰이 브랜드토큰을 포함하거나 앞 2글자 공유
            if kt[:3] in tk or kt[:2] in tk or tk[:2] in kt:
                return " ".join(toks[i:]).strip()
    return raw.strip()


def _extract_volume(name):
    m = VOL_RE.search(name or "")
    if not m:
        return None
    val = float(m.group(1)); unit = m.group(2).lower()
    if unit in ("l", "리터"):
        val *= 1000
    return int(round(val))


def _pair_names_prices(frame, min_score):
    """프레임 내 가격표(bbox)와 그 위 제품명(bbox)을 y/x 좌표로 페어링.
    반환: [(raw_name, price, name_score)] — 같은 프레임에서 매대 다수 제품."""
    items = frame["items"]
    prices, names = [], []
    for it in items:
        pv = _parse_price(it["text"])
        # 가격: 숫자만(한글 거의 없음) + 큰 글씨(태그 빨강숫자)
        if pv is not None and len(HANGUL_RE.findall(it["text"])) == 0:
            prices.append((it, pv))
        elif it["score"] >= min_score and HANGUL_RE.search(it["text"]):
            names.append(it)
    if not prices or not names:
        return []
    out = []
    for pit, pv in prices:
        max_gap = max(pit["h"] * 4.0, 60.0)   # 이름은 가격표 위 가까이
        x_tol = max(pit["box"][2] - pit["box"][0], 80.0) * 1.2
        cands = []
        for nit in names:
            dy = pit["cy"] - nit["cy"]          # 이름이 위(>0)
            if dy <= 0 or dy > max_gap:
                continue
            if abs(nit["cx"] - pit["cx"]) > x_tol:
                continue
            cands.append((dy, nit))
        if not cands:
            continue
        cands.sort(key=lambda c: c[0])          # 가장 가까운 위 = 주 이름
        primary = cands[0][1]
        name = primary["text"]
        score = primary["score"]
        # 멀티라인: 주 이름 바로 위 한 줄 더(브랜드+표현 분리 케이스)
        for dy, nit in cands[1:]:
            if dy <= max_gap and abs(nit["cy"] - primary["cy"]) <= primary["h"] * 2.2:
                name = (nit["text"] + " " + name).strip()
                score = min(score, nit["score"])
                break
        out.append((name.strip(), pv, score))
    return out


def parse(video_id, min_score=0.55):
    cpath = os.path.join(CACHE_DIR, video_id, "ocr.json")
    if not os.path.exists(cpath):
        raise SystemExit(f"[parse] 캐시 없음: {cpath} — 먼저 fetch 하세요")
    with open(cpath, encoding="utf-8") as f:
        cache = json.load(f)
    seller = cache.get("seller") or ""
    date = _extract_date(cache)
    # 1) 프레임별 페어링 → 후보 누적
    cands = []  # (raw_name, price, score, t)
    for fr in cache["frames"]:
        if fr.get("intro"):
            continue
        for name, price, score in _pair_names_prices(fr, min_score):
            cands.append((name, price, score, fr["t"]))
    # 2) 정규화 + 그룹핑.
    #    마스터가 '브랜드 단위'로 coarse 라(w018 글렌드로낙 = 12/15/18 동일 id, SKU 구분=CMPA-177)
    #    matched 라도 name_ko 로 술이름을 덮어쓰면 18년→12년 오표기가 난다. 그래서:
    #      · 술이름은 raw OCR 이름을 유지(실제 숙성년수 보존, collect_traders 관례)하고 id 는 비고에만 주석.
    #      · 그룹 key 는 matched=(id, 숙성년수), unmatched=정규화텍스트 — coarse id 가 12/18 을 뭉개지 않게.
    norm = _load_normalizer()
    groups = {}  # key -> {raw_best, score_best, id, name_ko, prices:{price:count}, n, age}
    for raw, price, score, t in cands:
        if is_bundle_noise(raw):
            continue
        res = norm.canonicalize(raw) if norm else {"status": "unmatched", "id": "", "name_ko": "", "norm": raw.lower()}
        if res["status"] == "excluded":
            continue
        age = _detect_age(raw)
        if res["status"] == "matched":
            key = f"id:{res['id']}|age:{age}"
        else:
            key = "nm:" + (res.get("norm") or raw.lower())
        g = groups.setdefault(key, {"raw_best": raw, "score_best": score, "status": res["status"],
                                    "id": res["id"], "name_ko": res["name_ko"], "prices": {}, "n": 0,
                                    "age": age})
        g["n"] += 1
        g["prices"][price] = g["prices"].get(price, 0) + 1
        if score > g["score_best"]:
            g["score_best"], g["raw_best"] = score, raw
    # 3) 행 생성: 그룹별 최빈 가격 채택
    rows = []
    for key, g in groups.items():
        price = max(g["prices"].items(), key=lambda kv: (kv[1], kv[0]))[0]
        raw = g["raw_best"]
        vol = _extract_volume(raw) or (_extract_volume(g["name_ko"]) if g["name_ko"] else None)
        if g["status"] == "matched":
            # 선두 OCR 잡음토큰 제거(브랜드 토큰 이전 버림) 후 raw 유지 — 숙성년수/표현 보존
            disp = _clean_name(raw, g["name_ko"])
            if vol and f"{vol}ml" not in disp.replace(" ", ""):
                disp = f"{disp} {vol}ml"
            conf = "중" if g["score_best"] >= 0.80 else "하"
            tag = f"id={g['id']}(={g['name_ko']})"
        else:
            disp = raw if (not vol or VOL_RE.search(raw)) else f"{raw} {vol}ml"
            conf = "하"
            tag = "needs_review"
        note = f"{tag}; raw=\"{raw}\"; ocr={g['score_best']:.2f}; n={g['n']}; src=싼디매대OCR/{video_id}"
        rows.append({
            "술이름": disp,
            "가격_KRW": price,
            "위치": seller,
            "가져온날짜": date,
            "출처": f"싼디(@SSanD3) 매대OCR {video_id}",
            "신뢰도": conf,
            "비고": note,
            "_status": g["status"], "_score": g["score_best"], "_vol": vol,
        })
    # 정렬: 매칭 우선, score desc
    rows.sort(key=lambda r: (r["_status"] != "matched", -r["_score"]))
    stats = {"video_id": video_id, "seller": seller, "date": date,
             "candidates": len(cands), "rows": len(rows),
             "matched": sum(1 for r in rows if r["_status"] == "matched")}
    return rows, stats


def _load_normalizer():
    try:
        from normalize_whisky_name import Normalizer, load_rules
        return Normalizer(load_rules())
    except Exception as e:
        sys.stderr.write(f"[warn] 정규화 모듈 로드 실패({e}); raw 이름만 유지\n")
        return None


# ──────────────────────────────────────────────────────────────────────────
# load: 월간 CSV dedup append
# ──────────────────────────────────────────────────────────────────────────
def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load(video_id, month=None, out=None, dry_run=False, min_score=0.55,
         matched_only=False):
    rows, stats = parse(video_id, min_score=min_score)
    if matched_only:
        rows = [r for r in rows if r["_status"] == "matched"]
    clean = [{k: r[k] for k in SCHEMA} for r in rows]
    if not clean:
        return {"appended": 0, "skipped": 0, "path": None, "stats": stats, "rows": []}
    if out:
        path = out if os.path.isabs(out) else os.path.join(ROOT, out)
    else:
        m = month or (clean[0]["가져온날짜"][:7] if clean[0]["가져온날짜"] else None)
        if not m:
            raise SystemExit("월 추정 실패 — --month YYYY-MM 또는 --out 지정")
        path = os.path.join(PRICES_DIR, f"{m}.csv")
    existing = _read_csv(path)
    seen = {(r.get("술이름"), str(r.get("가격_KRW")), r.get("위치"), r.get("가져온날짜")) for r in existing}
    appended, skipped = [], 0
    for r in clean:
        key = (r["술이름"], str(r["가격_KRW"]), r["위치"], r["가져온날짜"])
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        appended.append(r)
    if not dry_run and appended:
        new_file = not os.path.exists(path)
        with open(path, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=SCHEMA)
            if new_file:
                w.writeheader()
            w.writerows(appended)
    return {"appended": len(appended), "skipped": skipped, "path": path,
            "stats": stats, "rows": rows, "appended_rows": appended}


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("discover")
    p.add_argument("--limit", type=int, default=120)
    p.add_argument("--out")

    p = sub.add_parser("fetch")
    p.add_argument("--video", required=True)
    p.add_argument("--seller", default="")
    p.add_argument("--keep-video", action="store_true")
    p.add_argument("--max-frames", type=int, default=80)
    p.add_argument("--step-sec", type=float, default=1.0)

    for name in ("parse", "load"):
        p = sub.add_parser(name)
        p.add_argument("--video", required=True)
        p.add_argument("--min-score", type=float, default=0.55)
        if name == "load":
            p.add_argument("--month")
            p.add_argument("--out")
            p.add_argument("--dry-run", action="store_true")
            p.add_argument("--matched-only", action="store_true")

    a = ap.parse_args()
    if a.cmd == "discover":
        discover(limit=a.limit, out=a.out)
    elif a.cmd == "fetch":
        fetch(a.video, seller=a.seller, keep_video=a.keep_video,
              max_frames=a.max_frames, step_sec=a.step_sec)
    elif a.cmd == "parse":
        rows, stats = parse(a.video, min_score=a.min_score)
        sys.stderr.write(json.dumps(stats, ensure_ascii=False) + "\n")
        w = csv.DictWriter(sys.stdout, fieldnames=SCHEMA)
        w.writeheader()
        for r in rows:
            w.writerow({k: r[k] for k in SCHEMA})
    elif a.cmd == "load":
        res = load(a.video, month=a.month, out=a.out, dry_run=a.dry_run,
                   min_score=a.min_score, matched_only=a.matched_only)
        tag = "[DRY] " if a.dry_run else ""
        sys.stderr.write(json.dumps(res["stats"], ensure_ascii=False) + "\n")
        sys.stderr.write(f"{tag}[load] {res['path']} — append {res['appended']}행, "
                         f"skip {res['skipped']}행\n")
        w = csv.DictWriter(sys.stdout, fieldnames=SCHEMA)
        w.writeheader()
        for r in res.get("appended_rows", []):
            w.writerow({k: r[k] for k in SCHEMA})


if __name__ == "__main__":
    main()
