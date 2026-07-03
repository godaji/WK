#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
crop_price_tag.py — CMPA-423 (2/3) 가격표 영역 crop

정지프레임(extract_still_frames.py 산출)에서 **가격표(price tag) 영역만** 잘라낸다.

⚠️ 보드 지시(CMPA-423 2026-06-16): **가격표가 'upper-center(상단-중앙)'에 있다고 너무
   확신하지 말 것.** 진행자/영상마다 태그 위치가 흔들리고, 채널/매대에 따라 중앙·하단·우측
   등으로 달라질 수 있다. 그래서 이 스크립트는 위치를 **하드 ROI 로 잘라내지 않고**,
   `prior`(부드러운 위치 힌트, 약한 가중치) + **프레임 전역에서 '밝은 가격표 사각형'을
   탐색**하는 방식으로 동작한다. prior 는 동점을 가르는 정도(약 ≤35% 보정)만 영향을 주고,
   실제로는 **사각형 면적/형상이 선택을 지배**한다 — 따라서 태그가 상단-중앙이 아니어도
   잡힌다. refine 가 아무 후보도 못 찾으면 (좁은 상단밴드가 아니라) **넉넉한 탐색영역
   밴드**로 폴백해 무엇이라도 남긴다.

채널 템플릿:
  whiskeypick : 진열대 **종이 가격표**(흰 사각형, 상단명+큰가격). prior=상단쪽이지만 약하게.
                흰 사각형 탐색(refine) 사용.
  whiskeykey  : **합성 그래픽 오버레이**(제품명/가격) — CMPA-172 POC 레이아웃. 투명배경이라
                흰사각형 refine 부적합 → off, 넉넉한 우측 밴드 prior 만.

용법:
  python3 crop_price_tag.py FRAMES_DIR --template whiskeypick [--out-dir crops/] [--no-refine]
       [--prior-weight 0.35] [--debug]
  (FRAMES_DIR/manifest.csv 를 읽어 각 프레임을 crop → crops/{name}.jpg + crops/manifest.csv)
"""
import argparse
import csv
import os
import sys

import cv2
import numpy as np

# 채널 템플릿.
#   search : 사각형을 찾을 **넉넉한** 탐색영역(상대좌표 x0,y0,x1,y1). 좁은 상단밴드가 아니라
#            화면 대부분을 덮어, 태그가 어디 있든 잡히게 한다(upper-center 비확신 원칙).
#   prior  : 부드러운 위치 힌트(중심 cx,cy 상대좌표). 약한 가중치로 동점만 가른다.
#   refine : 밝은 흰 사각형(종이 가격표) 탐색 사용 여부.
#   fallback_band : refine 실패 시 잘라낼 폴백 밴드(= 보통 search 와 동일, 넉넉하게).
TEMPLATES = {
    "whiskeypick": {
        # 종이 가격표. 흔히 상단~중앙대에 오지만(=prior 약한 힌트), 좌우/하단으로도 흔들림 →
        # 탐색은 화면 거의 전체. 좌우 가장자리 이웃 태그만 살짝 배제(0.05~0.95).
        "search": (0.05, 0.00, 0.95, 0.80),
        "prior": (0.50, 0.28),
        "refine": True,
        "fallback_band": (0.10, 0.00, 0.90, 0.55),
    },
    "whiskeykey": {
        # 합성 오버레이(CMPA-172). 흰사각형 refine 부적합 → off. 우측에 흔하나 확신 X →
        # 우측 위주지만 넉넉히, prior 도 우측-중앙으로 약하게.
        "search": (0.40, 0.00, 1.00, 1.00),
        "prior": (0.72, 0.50),
        "refine": False,
        "fallback_band": (0.40, 0.00, 1.00, 1.00),
    },
}


def _abs_box(rel, W, H):
    x0, y0, x1, y1 = rel
    return int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)


def find_tag(img, search_rel, prior_rel, prior_weight=0.35, debug=False):
    """프레임 **전역(search 영역)** 에서 '밝은 가격표 사각형' 후보를 모아 점수로 1장 고른다.

    점수 = 면적(지배적) × (1 + prior_weight × 위치_prior). prior 는 부드러운 가우시안이라
    상단-중앙에서 멀어도 '약하게'만 깎인다(σ 넓음) → **upper-center 비확신**. 면적/형상이
    선택을 지배하므로 태그가 중앙이 아니어도 큰 흰 사각형이면 선택된다.

    반환: (x0,y0,x1,y1) 전체프레임 절대좌표, 또는 None.
    """
    H, W = img.shape[:2]
    SX0, SY0, SX1, SY1 = _abs_box(search_rel, W, H)
    SX0, SY0 = max(0, SX0), max(0, SY0)
    SX1, SY1 = min(W, SX1), min(H, SY1)
    if SX1 - SX0 < 8 or SY1 - SY0 < 8:
        return None
    region = img[SY0:SY1, SX0:SX1]
    rh, rw = region.shape[:2]

    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    _, th = cv2.threshold(gray, 170, 255, cv2.THRESH_BINARY)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 9))
    th = cv2.morphologyEx(th, cv2.MORPH_CLOSE, kernel, iterations=2)
    cnts, _ = cv2.findContours(th, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    pcx, pcy = prior_rel                 # prior 중심(전체프레임 상대좌표)
    sigma = 0.40                          # 넓게 → 위치는 약한 신호일 뿐(upper-center 비확신)
    best = None                           # (score, x,y,cw,ch)
    cands = 0
    for c in cnts:
        x, y, cw, ch = cv2.boundingRect(c)
        area = cw * ch
        if area < 0.015 * rw * rh:        # 너무 작은 잡티 제외(전역 탐색이라 하한 낮춤)
            continue
        if ch == 0:
            continue
        ar = cw / ch
        if not (1.1 <= ar <= 5.0):        # 가격표는 가로로 긴 사각형
            continue
        if cw > 0.98 * rw and ch > 0.98 * rh:   # 탐색영역 전체를 덮는 건 배경
            continue
        cands += 1
        # 후보 중심(전체프레임 상대좌표)
        ccx = (SX0 + x + cw / 2) / W
        ccy = (SY0 + y + ch / 2) / H
        dist2 = ((ccx - pcx) ** 2 + (ccy - pcy) ** 2) / (sigma ** 2)
        prior = float(np.exp(-0.5 * dist2))      # 1(중심)~0(멀리)
        area_norm = area / (rw * rh)
        score = area_norm * (1.0 + prior_weight * prior)
        if best is None or score > best[0]:
            best = (score, x, y, cw, ch)
    if best is None:
        if debug:
            print(f"    [find_tag] 후보 {cands}개 중 채택 0 → 폴백", file=sys.stderr)
        return None
    _, x, y, cw, ch = best
    pad_x, pad_y = int(0.04 * rw), int(0.05 * rh)   # 글자 잘림 방지 여유
    x0 = max(0, SX0 + x - pad_x); y0 = max(0, SY0 + y - pad_y)
    x1 = min(W, SX0 + x + cw + pad_x); y1 = min(H, SY0 + y + ch + pad_y)
    if debug:
        print(f"    [find_tag] 후보 {cands}개 → 채택 score={best[0]:.4f} "
              f"box=({x0},{y0},{x1},{y1})", file=sys.stderr)
    return (x0, y0, x1, y1)


def crop_frame(img, template, refine=True, prior_weight=0.35, debug=False):
    H, W = img.shape[:2]
    if refine and template.get("refine"):
        box = find_tag(img, template["search"], template["prior"], prior_weight, debug)
        if box is not None:
            x0, y0, x1, y1 = box
            return img[y0:y1, x0:x1], "white_rect"
    # 폴백: 좁은 상단밴드가 아니라 **넉넉한 밴드**로 잘라 무엇이라도 남긴다(비확신 원칙).
    fx0, fy0, fx1, fy1 = _abs_box(template["fallback_band"], W, H)
    return img[fy0:fy1, fx0:fx1], "roi_fallback"


def run(frames_dir, template_name, out_dir=None, refine=True, prior_weight=0.35,
        debug=False):
    if template_name not in TEMPLATES:
        raise SystemExit(f"알 수 없는 템플릿: {template_name} ({'|'.join(TEMPLATES)})")
    tpl = TEMPLATES[template_name]
    out_dir = out_dir or os.path.join(frames_dir, "crops")
    os.makedirs(out_dir, exist_ok=True)
    man_in = os.path.join(frames_dir, "manifest.csv")
    rows = []
    if os.path.exists(man_in):
        with open(man_in, encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
    else:  # manifest 없으면 폴더의 jpg 직접 스캔
        rows = [{"path": p, "t_sec": "", "video_id": ""}
                for p in sorted(os.listdir(frames_dir)) if p.endswith(".jpg")]

    out_rows = []
    for r in rows:
        src = os.path.join(frames_dir, r["path"])
        img = cv2.imread(src)
        if img is None:
            continue
        if debug:
            print(f"  {r['path']}", file=sys.stderr)
        crop, method = crop_frame(img, tpl, refine, prior_weight, debug)
        if crop.size == 0:
            continue
        name = os.path.basename(r["path"])
        dst = os.path.join(out_dir, name)
        cv2.imwrite(dst, crop, [cv2.IMWRITE_JPEG_QUALITY, 95])
        out_rows.append({
            "video_id": r.get("video_id", ""), "t_sec": r.get("t_sec", ""),
            "frame": r["path"], "crop": os.path.relpath(dst, out_dir),
            "method": method, "w": crop.shape[1], "h": crop.shape[0],
        })
    mpath = os.path.join(out_dir, "manifest.csv")
    with open(mpath, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["video_id", "t_sec", "frame", "crop",
                                          "method", "w", "h"])
        w.writeheader()
        w.writerows(out_rows)
    n_ref = sum(1 for x in out_rows if x["method"] == "white_rect")
    print(f"[crop] {len(out_rows)}장 crop → {out_dir} "
          f"(white_rect {n_ref}/{len(out_rows)}, 폴백 {len(out_rows) - n_ref}, "
          f"manifest: {mpath})", file=sys.stderr)
    return out_rows


def main():
    ap = argparse.ArgumentParser(description="정지프레임 → 가격표 crop(전역 사각형 탐색, "
                                             "upper-center 비확신)")
    ap.add_argument("frames_dir", help="extract_still_frames.py 산출 폴더(manifest.csv 포함)")
    ap.add_argument("--template", required=True, choices=list(TEMPLATES),
                    help="채널 템플릿(whiskeypick|whiskeykey)")
    ap.add_argument("--out-dir", default=None, help="crop 저장 폴더(기본 FRAMES_DIR/crops)")
    ap.add_argument("--no-refine", action="store_true", help="흰사각형 탐색 끄기(폴백밴드만)")
    ap.add_argument("--prior-weight", type=float, default=0.35,
                    help="위치 prior 가중치(0=위치무시, 클수록 prior 영향↑; 기본 0.35=약함)")
    ap.add_argument("--debug", action="store_true", help="프레임별 후보/채택 로그")
    a = ap.parse_args()
    run(a.frames_dir, a.template, a.out_dir, refine=not a.no_refine,
        prior_weight=a.prior_weight, debug=a.debug)


if __name__ == "__main__":
    main()
