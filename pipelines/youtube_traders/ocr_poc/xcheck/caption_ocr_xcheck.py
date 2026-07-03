#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
caption_ocr_xcheck.py — CMPA-229 자막↔OCR 교차검증 (ASR 미사용 원칙)

흐름:
  1) 자막(caption json3)에서 가격 언급 이벤트의 '타임코드'를 뽑는다.   (소스=시점)
  2) 그 타임코드의 영상 프레임을 OCR 해 화면에 박힌 가격을 읽는다.    (소스=값)
  3) 자막값 ↔ OCR값 비교 → 채택 규칙으로 최종가 확정.

채택 규칙(보드 지시 반영):
  - 일치 → 확정(confirmed).
  - 불일치 → **화면 OCR 우선**(오버레이는 합성 그래픽이라 가장 신뢰도 높음),
    단 needs_human=True 플래그를 남겨 사람확인 큐로 보낸다.
"""
import sys, re, json, glob, cv2
from paddleocr import PaddleOCR

# 한국어 자막은 가격을 콤마 그룹 + '원'으로 쓴다(예: 39,980원).
# 브랜드 숫자('1792')는 콤마가 없어 자연히 배제된다.
PRICE_RE = re.compile(r'(\d{1,3}(?:,\d{3})+)\s*원?')

def caption_events(path):
    d = json.load(open(path)); out = []
    for e in d.get('events', []):
        segs = e.get('segs') or []
        txt = ''.join(s.get('utf8', '') for s in segs).strip()
        if txt:
            out.append((e.get('tStartMs', 0) / 1000.0, txt))
    return out

def caption_price(txt):
    m = PRICE_RE.findall(txt)
    vals = [int(x.replace(',', '')) for x in m]
    vals = [v for v in vals if v >= 1000]  # 가격대만
    return vals

def ocr_boxes(ocr, img):
    out = []
    for r in ocr.predict(img):
        polys = r.get('rec_polys') or r.get('dt_polys') or []
        for i, (tx, sc) in enumerate(zip(r['rec_texts'], r['rec_scores'])):
            box = polys[i] if i < len(polys) else None
            if box is not None:
                ys = [float(p[1]) for p in box]; xs = [float(p[0]) for p in box]
                h, y, x = max(ys) - min(ys), min(ys), min(xs)
            else:
                h = y = x = 0.0
            out.append({'t': tx, 's': float(sc), 'h': h, 'y': y, 'x': x})
    return out

def ocr_frame(ocr, fp):
    im = cv2.imread(fp); H, W = im.shape[:2]
    name_c  = im[0:int(H * 0.14), int(W * 0.40):W]
    price_c = im[int(H * 0.15):int(H * 0.74), int(W * 0.72):W]
    name = ocr_boxes(ocr, name_c)
    price = ocr_boxes(ocr, price_c)
    name_txt = ' '.join(b['t'] for b in name if b['s'] > 0.5).strip()
    # 최종가 = 가격밴드에서 폰트 높이가 가장 큰 숫자 토큰 (정상가 취소선/할인액/100ml단가 배제)
    pcands = []
    for b in price:
        digits = re.sub(r'[^0-9]', '', b['t'])
        if len(digits) >= 4:
            pcands.append((b['h'], int(digits), b['t'], b['s']))
    pcands.sort(reverse=True)
    final = pcands[0][1] if pcands else None
    return name_txt, final, pcands

def main():
    cap, frames_dir, target = sys.argv[1], sys.argv[2], float(sys.argv[3])
    evs = caption_events(cap)
    # target 시점에 가장 가까운(직전 시작) 자막 이벤트
    near = min(evs, key=lambda e: abs(e[0] - target))
    cap_vals = caption_price(near[1])
    print(f"[CAPTION] t={near[0]:.2f}s  text={near[1]!r}")
    print(f"[CAPTION] price tokens -> {cap_vals}")
    ocr = PaddleOCR(lang='korean', use_textline_orientation=False, enable_mkldnn=False)
    print()
    chosen = []
    for fp in sorted(glob.glob(f"{frames_dir}/*.jpg")):
        name_txt, final, pcands = ocr_frame(ocr, fp)
        allp = [f"{v}(h{h:.0f})" for h, v, _, _ in pcands]
        print(f"[OCR] {fp.split('/')[-1]:14s} name={name_txt!r}")
        print(f"      price band tokens (by font) = {allp}  -> FINAL={final}")
        if final:
            chosen.append(final)
    # 안정 프레임 다수결
    if chosen:
        from collections import Counter
        ocr_final = Counter(chosen).most_common(1)[0][0]
        cap_final = min(cap_vals) if cap_vals else None
        match = (ocr_final == cap_final)
        print("\n================= DECISION =================")
        print(f"caption final price = {cap_final}")
        print(f"OCR final price     = {ocr_final}  (vote over frames: {chosen})")
        print(f"MATCH = {match}")
        if match:
            print("=> CONFIRMED (caption==OCR). adopt:", ocr_final)
        else:
            print("=> MISMATCH. rule: adopt screen OCR, set needs_human=True. adopt:", ocr_final)

if __name__ == '__main__':
    main()
