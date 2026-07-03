#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ocr_dump_frames.py — CMPA-172 OCR 타당성 스파이크 (1/2단계)

@whiskeykey 트레이더스 영상의 **화면 오버레이(이름/가격 그래픽)** 를 프레임 단위로
OCR 해서 raw 박스(텍스트·신뢰도·박스높이·좌표)를 JSON 으로 덤프한다.
2단계(extract_overlay_fields.py)는 이 JSON 만 읽어 이름/최종가 추출 휴리스틱을
네트워크·재OCR 없이 빠르게 튜닝한다.

전처리(이 스크립트 밖에서):
  yt-dlp -f 136 -o vid.mp4 "https://www.youtube.com/watch?v=<ID>"   # 720p video-only
  ffmpeg -i vid.mp4 -vf fps=1/3 frames/f%03d.png                    # 3초당 1프레임
  (ffmpeg 없으면 imageio_ffmpeg.get_ffmpeg_exe() 의 번들 바이너리 사용)

용법:
  python3 ocr_dump_frames.py <frames_dir> <out.json>

설계 메모:
  * PaddleOCR(lang='korean') — onednn 충돌 회피 위해 enable_mkldnn=False (CMPA-6 교훈).
  * 오버레이는 우측에 집중 → name 크롭(상단 우측), price 크롭(우측 중단)만 OCR해
    설명문단·배너·병사진 노이즈를 줄이고 속도를 높인다(720p 기준 ~6s/프레임).
"""
import sys, glob, time, json, cv2
from paddleocr import PaddleOCR


def ocr_crop(ocr, img):
    out = []
    for r in ocr.predict(img):
        polys = r.get('rec_polys') or r.get('dt_polys') or []
        for i, (tx, sc) in enumerate(zip(r['rec_texts'], r['rec_scores'])):
            box = polys[i] if i < len(polys) else None
            if box is not None:
                ys = [float(p[1]) for p in box]
                xs = [float(p[0]) for p in box]
                h, y, x = max(ys) - min(ys), min(ys), min(xs)
            else:
                h = y = x = 0.0
            out.append({'t': tx, 's': float(sc), 'h': h, 'y': y, 'x': x})
    return out


def main():
    if len(sys.argv) < 3:
        raise SystemExit("용법: ocr_dump_frames.py <frames_dir> <out.json>")
    frames_dir, out_json = sys.argv[1], sys.argv[2]
    ocr = PaddleOCR(lang='korean', use_textline_orientation=False, enable_mkldnn=False)
    frames = sorted(glob.glob(f"{frames_dir}/*.png"))
    t0 = time.time(); data = []
    for fp in frames:
        im = cv2.imread(fp); H, W = im.shape[:2]
        name_c = im[0:int(H * 0.14), int(W * 0.40):W]              # 상단 우측 = 제품명
        price_c = im[int(H * 0.15):int(H * 0.74), int(W * 0.72):W]  # 우측 중단 = 가격 블록
        data.append({'f': fp.split('/')[-1],
                     'name': ocr_crop(ocr, name_c),
                     'price': ocr_crop(ocr, price_c)})
    json.dump(data, open(out_json, 'w'), ensure_ascii=False)
    sys.stderr.write(f"[dump] {len(frames)} frames {time.time()-t0:.0f}s -> {out_json}\n")


if __name__ == "__main__":
    main()
