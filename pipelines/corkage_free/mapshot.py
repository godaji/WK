#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mapshot.py — 역 중심 정적 지도 이미지 생성기 (CMPA-55)

CEO 요청: "강남역 중심으로 해당 식당이 어디에 있는지 지도 스샷"을 보여달라.
외부 정적지도 API(네이버/카카오/OSM staticmap.de)는 키 필요 또는 네트워크 차단이라,
**OSM/CARTO 타일을 직접 받아 Pillow 로 합성**해 PNG 를 만든다(추가 의존성 없음).

마커
  - 파란 원 = 지하철역(중심) + 도보반경 링
  - 빨간 번호 원 = 위스키 신호 콜키지프리 식당(목록 순번과 일치)
  - 회색 점 = 일반 콜키지프리 식당
지도 위 라벨은 폰트 한계로 숫자/영문만(한글 상호는 HTML 목록·범례에서 매칭).
"""
import base64
import io
import math
import os

import requests
from PIL import Image, ImageDraw, ImageFont

# 같은 역 주변 식당들은 타일이 크게 겹친다 → 프로세스 단위 캐시로 재요청 최소화.
_TILE_CACHE = {}

TILE = 256
UA = "corkage-free-map/1.0 (Paperclip CMPA-55; internal R&D)"
# CARTO Positron(밝고 깔끔) 우선, 실패 시 OSM 표준
TILE_URLS = [
    "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}.png",
    "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
]
_FONT_DIR = "/usr/share/fonts/truetype/dejavu"


def _font(size, bold=True):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(os.path.join(_FONT_DIR, name), size)
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def _deg2px(lat, lon, z):
    """경위도 → 줌 z 전역 픽셀좌표."""
    n = TILE * (2 ** z)
    x = (lon + 180.0) / 360.0 * n
    lat_r = math.radians(lat)
    y = (1.0 - math.asinh(math.tan(lat_r)) / math.pi) / 2.0 * n
    return x, y


def _mpp(lat, z):
    """미터/픽셀."""
    return 156543.03392 * math.cos(math.radians(lat)) / (2 ** z)


def _pick_zoom(lat, radius_m, half_px):
    """도보반경이 half_px 안에 들어오는 최대 디테일 줌."""
    target_mpp = radius_m / max(half_px, 1)
    z = math.floor(math.log2(156543.03392 * math.cos(math.radians(lat)) / target_mpp))
    return max(11, min(16, z))


def _fetch_tile(z, x, y):
    key = (z, x, y)
    if key in _TILE_CACHE:
        return _TILE_CACHE[key]
    img = None
    for tmpl in TILE_URLS:
        try:
            r = requests.get(tmpl.format(z=z, x=x, y=y),
                             headers={"User-Agent": UA}, timeout=20)
            if r.status_code == 200 and r.content:
                img = Image.open(io.BytesIO(r.content)).convert("RGBA")
                break
        except Exception:  # noqa: BLE001
            continue
    if img is None:
        img = Image.new("RGBA", (TILE, TILE), (235, 235, 235, 255))
    _TILE_CACHE[key] = img
    return img


def _compose(center_px, w, h, z):
    """center 전역픽셀 기준 w×h 캔버스에 타일 합성 후 (base, left, top) 반환."""
    cx, cy = center_px
    left, top = cx - w / 2, cy - h / 2
    base = Image.new("RGBA", (w, h), (240, 240, 240, 255))
    for tx in range(int(left // TILE), int((left + w) // TILE) + 1):
        for ty in range(int(top // TILE), int((top + h) // TILE) + 1):
            base.alpha_composite(_fetch_tile(z, tx, ty),
                                 (int(tx * TILE - left), int(ty * TILE - top)))
    return base, left, top


def _zoom_to_fit(lat, span_m, fit_px):
    """두 점 간 거리 span_m 가 fit_px 안에 들어오는 최대 정수 줌."""
    span_m = max(span_m, 60)  # 너무 가까우면 과확대 방지
    target_mpp = span_m / max(fit_px, 1)
    z = math.floor(math.log2(156543.03392 * math.cos(math.radians(lat)) / target_mpp))
    return max(13, min(17, z))


def render_pair(slat, slng, rlat, rlng, w=200, h=150, margin=22):
    """역(S, 파랑) ↔ 식당(빨강) 한 쌍을 보여주는 작은 미니 지도(사진 위 오버레이용).
    PIL 이미지 반환."""
    span = math.hypot(*[(a - b) for a, b in
                        zip(_deg2px(slat, slng, 17), _deg2px(rlat, rlng, 17))])
    span_m = _mpp(slat, 17) * span  # span(px@17) → 거리(m)
    z = _zoom_to_fit(slat, span_m, min(w, h) - 2 * margin)
    spx, spy = _deg2px(slat, slng, z)
    rpx, rpy = _deg2px(rlat, rlng, z)
    base, left, top = _compose(((spx + rpx) / 2, (spy + rpy) / 2), w, h, z)
    draw = ImageDraw.Draw(base, "RGBA")
    sx, sy, rx, ry = spx - left, spy - top, rpx - left, rpy - top
    draw.line([(sx, sy), (rx, ry)], fill=(50, 50, 50, 170), width=2)
    # 식당(빨강 핀)
    draw.ellipse([rx - 7, ry - 7, rx + 7, ry + 7],
                 fill=(214, 40, 40, 255), outline=(255, 255, 255, 255), width=2)
    # 역(파랑 S)
    draw.ellipse([sx - 8, sy - 8, sx + 8, sy + 8],
                 fill=(30, 90, 200, 255), outline=(255, 255, 255, 255), width=2)
    draw.text((sx - 3, sy - 6), "S", font=_font(10, True), fill=(255, 255, 255, 255))
    return base


def to_data_uri(img, fmt="JPEG", quality=78):
    """PIL 이미지를 HTML 인라인용 data URI(base64)로. 지도엔 JPEG가 작아 적합."""
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
        mime = "image/jpeg"
    else:
        img.convert("RGB").save(buf, "PNG", optimize=True)
        mime = "image/png"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def render_station_map(station, lat, lng, rows, radius_m, out_path,
                       w=760, h=560, max_numbered=12):
    """역 중심 정적 지도 PNG 저장. rows 는 find()의 출력(위스키신호순 정렬)."""
    half = min(w, h) / 2 - 48
    z = _pick_zoom(lat, radius_m, half)
    cx, cy = _deg2px(lat, lng, z)
    left, top = cx - w / 2, cy - h / 2

    base = Image.new("RGBA", (w, h), (240, 240, 240, 255))
    tx0, tx1 = int(left // TILE), int((left + w) // TILE)
    ty0, ty1 = int(top // TILE), int((top + h) // TILE)
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            tile = _fetch_tile(z, tx, ty)
            base.alpha_composite(tile, (int(tx * TILE - left), int(ty * TILE - top)))

    draw = ImageDraw.Draw(base, "RGBA")

    def to_xy(plat, plng):
        gx, gy = _deg2px(plat, plng, z)
        return gx - left, gy - top

    # 도보반경 링(반투명 채움은 별도 오버레이에서 alpha_composite 해야 제대로 블렌딩됨)
    rpx = radius_m / _mpp(lat, z)
    sx, sy = to_xy(lat, lng)
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    odraw = ImageDraw.Draw(overlay, "RGBA")
    odraw.ellipse([sx - rpx, sy - rpx, sx + rpx, sy + rpx], fill=(30, 90, 200, 28))
    base.alpha_composite(overlay)
    draw.ellipse([sx - rpx, sy - rpx, sx + rpx, sy + rpx],
                 outline=(30, 90, 200, 220), width=3)

    # 일반 콜키지(회색 점) — 번호 매기는 위스키 신호는 따로
    whisky_rows = [r for r in rows if r.get("위스키신호")][:max_numbered]
    whisky_ids = {id(r) for r in whisky_rows}
    for r in rows:
        if id(r) in whisky_ids:
            continue
        try:
            px, py = to_xy(float(r["lat"]), float(r["lng"]))
        except (TypeError, ValueError):
            continue
        draw.ellipse([px - 3, py - 3, px + 3, py + 3],
                     fill=(120, 120, 120, 200), outline=(255, 255, 255, 200))

    # 위스키 신호(빨간 번호 원)
    fnum = _font(13, bold=True)
    for i, r in enumerate(whisky_rows, 1):
        try:
            px, py = to_xy(float(r["lat"]), float(r["lng"]))
        except (TypeError, ValueError):
            continue
        rad = 11
        draw.ellipse([px - rad, py - rad, px + rad, py + rad],
                     fill=(214, 40, 40, 255), outline=(255, 255, 255, 255), width=2)
        t = str(i)
        tb = draw.textbbox((0, 0), t, font=fnum)
        draw.text((px - (tb[2] - tb[0]) / 2, py - (tb[3] - tb[1]) / 2 - tb[1]),
                  t, font=fnum, fill=(255, 255, 255, 255))

    # 역 마커(파란 원 + S)
    rad = 13
    draw.ellipse([sx - rad, sy - rad, sx + rad, sy + rad],
                 fill=(30, 90, 200, 255), outline=(255, 255, 255, 255), width=3)
    fs = _font(14, bold=True)
    draw.text((sx - 5, sy - 9), "S", font=fs, fill=(255, 255, 255, 255))

    # 제목/범례/출처(영문·ASCII)
    ftitle = _font(16, bold=True)
    fleg = _font(12, bold=False)
    draw.rectangle([0, 0, w, 26], fill=(27, 27, 43, 230))
    draw.text((8, 5), f"Corkage-free near station  (walk {radius_m}m)",
              font=ftitle, fill=(255, 255, 255, 255))
    lx, ly = 8, h - 64
    draw.rectangle([lx - 4, ly - 4, lx + 250, h - 6], fill=(255, 255, 255, 220))
    draw.ellipse([lx, ly + 1, lx + 12, ly + 13], fill=(30, 90, 200, 255))
    draw.text((lx + 18, ly), "Subway station (S) + walk radius", font=fleg, fill=(20, 20, 20))
    draw.ellipse([lx, ly + 19, lx + 12, ly + 31], fill=(214, 40, 40, 255))
    draw.text((lx + 18, ly + 18), f"Whisky corkage-free (1-{len(whisky_rows)}, see list)",
              font=fleg, fill=(20, 20, 20))
    draw.ellipse([lx + 3, ly + 39, lx + 9, ly + 45], fill=(120, 120, 120, 255))
    draw.text((lx + 18, ly + 36), f"Corkage-free ({len(rows) - len(whisky_rows)} more)",
              font=fleg, fill=(20, 20, 20))
    attr = "(c) OpenStreetMap / CARTO"
    ab = draw.textbbox((0, 0), attr, font=fleg)
    draw.text((w - (ab[2] - ab[0]) - 6, h - 16), attr, font=fleg, fill=(90, 90, 90))

    base.convert("RGB").save(out_path, "PNG")
    return out_path, whisky_rows
