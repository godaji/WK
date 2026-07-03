#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collect_traders_prices.py — 유튜브 위스키 채널(**@whiskeypick·@whiskeykey**) 영상에서
이마트 트레이더스 현장 위스키 가격을 ko ASR 자막으로 수집해 월간 CSV에 적재하는
**수집 루틴 엔진** (CMPA-27).

  ⚠️ 라이브 1차 소스 = **@whiskeypick + @whiskeykey 2개** (싼디/@SSanD3 아님).
     - @whiskeypick(위스키픽): 2026-03~05 1차 소스.
     - @whiskeykey(위스키키): CMPA-160 신규 검증·보드 승인(2026-06-07). 거의 주간 업로드로
       @whiskeypick 6월 0행 공백을 메움. ⚠️ 핸들이 비슷하나 위스키픽과 다른 채널.
     @SSanD3(싼디) 는 ASR 부적합(BGM 가사·가격 0행)으로 CHANNELS 에서 제거됨(CMPA-423 보드 지시).
     "싼디에서 수집한다"는 틀린 표현. (CMPA-154 → CMPA-160 → CMPA-423 보드 확인)
  ⚠️ 위치(마트명)는 '트레이더스'로 유지하되, **지점은 함께 기록**한다 (CMPA-446 보드 2026-06-17,
     CMPA-160 반전 — 지점별 재고 상이). 지점 추출·`지점` 컬럼은 frame_ocr/ingest_ocr.branch_from_title.

파이프라인 4단계 (서브커맨드):
  discover  채널 영상 목록(RSS/yt-dlp flat-playlist)에서 '트레이더스' 영상 필터 → 인덱스 CSV
  fetch     특정 video_id 의 ko ASR 자막(json3) 다운로드. **per-IP 429 회피 ≥60분 페이싱**.
  parse     자막(json3) → (술이름·용량·가격·타임스탬프·신뢰도) 행 추출 (네트워크 X, 재현 가능)
  load      parse → 정규화(마스터 SKU id 주석) → 월간 YYYY-MM.csv 에 dedup append

설계 메모:
  * ko ASR 자막은 per-IP 429 가 심하다(메모리 ytdlp-timedtext-429-pacing). fetch 는
    상태파일(.state/last_fetch.json)로 마지막 호출 시각을 기록하고 60분 이내 재호출을 거부한다
    (--force 로 무시 가능). 주간 루틴은 1회 1영상이라 페이싱과 충돌하지 않는다.
  * OCR 가 아니라 ASR 자막을 1차 소스로 쓴다(CMPA-5 OCR NO-GO). 가격은 자막에 또렷이
    찍히고(99,800원), 이름은 음차/오인이 잦아 → 정규화 루틴(CMPA-22)의 Normalizer 로
    canonical id 를 비고에 주석한다. 매칭 실패해도 raw 이름은 보존(후속 정규화 입력).
  * 거버넌스: 월간 CSV 적재는 **내부 R&D OK**. 공개 재배포는 CMPA-7 게이트 — 배포 루틴에서 체크.

용법:
  python3 pipelines/youtube_traders/collect_traders_prices.py parse \
      --sub /tmp/subs/nYUtBO0v7vI.ko.json3 --video nYUtBO0v7vI
  python3 pipelines/youtube_traders/collect_traders_prices.py fetch --video <ID>
  python3 pipelines/youtube_traders/collect_traders_prices.py load \
      --sub /tmp/subs/<ID>.ko.json3 --video <ID> [--month 2026-05] [--dry-run]
  python3 pipelines/youtube_traders/collect_traders_prices.py discover --channel whiskeypick
"""
import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from pipelines.common.dated import snapshot, kst_today  # noqa: E402
# CMPA-165: 수집 단계에서부터 ASR 비-제품명(문장/추임새)·비상식 가격을 거른다(보드: 수집측 정제).
from pipelines.common.whisky_quality import (  # noqa: E402
    canonical_store, is_garbage_name, is_sane_price)

PRICES_DIR = os.path.join(ROOT, "data", "whisky-prices")
STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".state")
SUB_CACHE = os.path.join(STATE_DIR, "subs")
PACE_FILE = os.path.join(STATE_DIR, "last_fetch.json")
PACE_SECONDS = 60 * 60  # ≥60분 (메모리 ytdlp-timedtext-429-pacing)

SCHEMA = ["술이름", "가격_KRW", "위치", "가져온날짜", "출처", "신뢰도", "비고"]

# 채널 핸들 → 표기. channel_id 는 discover 가 동적 해석(yt-dlp).
# ⚠️ 라이브 적재 대상 = active=True 채널(whiskeypick·whiskeykey 2개).
#    2채널은 ≥60분 페이싱 가드 때문에 요일/실행 분리로 운용한다(429 회피·README 참조).
#    싼디(@SSanD3) 는 ASR 부적합(BGM 가사·가격 0행)으로 보드 지시(CMPA-423) 제거 — 다시 넣지 말 것.
CHANNELS = {
    "whiskeypick": {"handle": "@whiskeypick", "label": "@whiskeypick", "active": True},
    # @whiskeykey(위스키키) — 트레이더스 전 위스키 현장가를 또렷이 읽어 주며 거의 주간으로
    # 날짜 명기 영상 업로드. CMPA-160 POC 검증: 2026-06-01 영상(dMF5i15ucJQ) ASR → 79행,
    # 날짜 자동검출 2026-06-01, 정규화 31/79. @whiskeypick(위스키픽)이 6월 0행이던 공백을 메움.
    # ⚠️ @whiskeypick(위스키픽) 과 핸들이 비슷하나 다른 채널이다(혼동 주의).
    "whiskeykey": {"handle": "@whiskeykey", "label": "@위스키키", "active": True},
}

# 가격: 99,800원 / 99800원 / 9만9천 형태(콤마형·평문 4~7자리)
PRICE_RE = re.compile(r"(\d{1,3}(?:,\d{3})+|\d{4,7})\s*원")
# 용량: 700ml / 750ml / 1l / 1.75l / 1리터
VOL_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(ml|l|리터)\b", re.IGNORECASE)
DATE_RE = re.compile(r"(\d{4})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
NOISE_RE = re.compile(r"\[[^\]]*\]")            # [음악] [박수] 등
# ⚠️ 위치(마트명)는 '트레이더스' 로 유지한다. CMPA-446 반전(보드 2026-06-17): 지점별 재고가
#    달라 '지점'을 함께 기록한다 — 단 위치=마트명, 지점은 별도(frame_ocr 의 `지점` 컬럼)로 분리.
#    이 ASR 경로(collect_traders_prices)는 제목 지점 추출 미구현 — 정본 지점 파이프라인은
#    frame_ocr/ingest_ocr.branch_from_title(영상 제목 기반). (구 CMPA-160 → CMPA-446 반전.)

# 가격 하한: 위스키 1병이 이보다 싸면 ASR 자릿수 누락 의심 → 낮음 플래그
LOW_PRICE_FLOOR = 19000
LOW_NOTE = "ASR 자릿수 누락/오인 추정-재확인"


# ──────────────────────────────────────────────────────────────────────────
# 공통 유틸
# ──────────────────────────────────────────────────────────────────────────
def _ts(ms):
    s = int(ms) // 1000
    return f"{s // 60}:{s % 60:02d}"


def _load_subtitle_events(path):
    """json3 자막 → [(start_ms, text)] (텍스트 있는 이벤트만)."""
    with open(path, encoding="utf-8") as f:
        d = json.load(f)
    out = []
    for e in d.get("events", []):
        segs = e.get("segs") or []
        txt = "".join(s.get("utf8", "") for s in segs)
        txt = txt.replace("\n", " ").strip()
        if txt:
            out.append((e.get("tStartMs", 0), txt))
    return out


def detect_context(events):
    """자막 인트로에서 촬영일자(YYYY-MM-DD) 추정. 위치는 항상 '트레이더스'(지점명 미표기)."""
    head = " ".join(t for _, t in events[:20])
    date = None
    m = DATE_RE.search(head)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        date = f"{y:04d}-{mo:02d}-{d:02d}"
    # 트레이더스는 전국 매장가 동일 → 지점명 없이 '트레이더스' 로 통일 (CMPA-160 보드).
    return date, "트레이더스"


# ──────────────────────────────────────────────────────────────────────────
# parse: 자막 → 행
# ──────────────────────────────────────────────────────────────────────────
def parse_subtitle(path, video_id=None, location=None, date=None, channel_label="@whiskeypick"):
    events = _load_subtitle_events(path)
    if not events:
        return [], {"date": None, "location": None, "n_events": 0}
    det_date, det_loc = detect_context(events)
    date = date or det_date
    location = location or det_loc

    # 가격이 등장하는 '시각'을 알기 위해 (글로벌 오프셋 → 이벤트 start_ms) 인덱스를 만든다.
    joined = ""
    offsets = []  # (char_start, char_end, start_ms)
    for ms, t in events:
        t = NOISE_RE.sub(" ", t)
        start = len(joined)
        joined += t + " "
        offsets.append((start, len(joined), ms))

    def ms_at(char_pos):
        for s, e, ms in offsets:
            if s <= char_pos < e:
                return ms
        return offsets[-1][2] if offsets else 0

    rows = []
    prev_end = 0
    for m in PRICE_RE.finditer(joined):
        price = int(m.group(1).replace(",", ""))
        chunk = joined[prev_end:m.start()]
        prev_end = m.end()

        # chunk = 이름 + (선택)용량. 용량 분리.
        vol = ""
        vm = None
        for vm in VOL_RE.finditer(chunk):
            pass  # 마지막 용량 토큰 사용
        if vm:
            unit = vm.group(2).lower()
            num = vm.group(1)
            vol = (num + "L") if unit in ("l", "리터") else (num + "ML")
            name = chunk[:vm.start()]
        else:
            name = chunk

        # 이름은 가격 직전 '문장'만 취한다 — 마지막 문장부호(.!?) 뒤만 남긴다.
        # CMPA-229: 인트로 인사말·앞선 멘트·할인안내('5,000원 할인하여 …')가 앞 청크에
        #   딸려 오면 is_garbage_name 에 걸려 '진짜 첫 위스키'(예: 1792 스몰배치 39,980원)까지
        #   통째로 버려진다. 첫 레코드만 자르던 과거 로직은 인트로의 할인가('5,000원')가
        #   먼저 매칭돼 그 한 번을 소진해 버려 무력화됐다 → 모든 청크에 문장 절단 적용.
        name = re.split(r"[.!?]", name)[-1]
        name = re.sub(r"\s+", " ", name).strip(" .,·-")

        if not name or len(name) < 2:
            continue

        # CMPA-165: ASR 비-제품명(진행자 멘트·문장·'할인해서' 등 토막)은 수집에서 제외.
        if is_garbage_name(name):
            continue
        # 단품인데 가격이 비상식(예: 'N천원 할인'의 5,000)이면 제외(미니어처/세트는 비고로 구분).
        if not is_sane_price(price):
            continue

        conf = "중"
        note = ""
        if price < LOW_PRICE_FLOOR:
            conf, note = "낮음", LOW_NOTE

        src = f"유튜브 {channel_label}"
        if video_id:
            src += f" / {video_id} @ {_ts(ms_at(m.start()))}"

        rows.append({
            "술이름": (name + (" " + vol.lower() if vol else "")).strip(),
            "_name_only": name,
            "_vol": vol,
            "가격_KRW": price,
            "위치": canonical_store(location) or "트레이더스",
            "가져온날짜": date or "",
            "출처": src,
            "신뢰도": conf,
            "비고": note,
        })
    meta = {"date": date, "location": location, "n_events": len(events)}
    return rows, meta


# ──────────────────────────────────────────────────────────────────────────
# normalize: 마스터 SKU id 주석
# ──────────────────────────────────────────────────────────────────────────
def annotate_canonical(rows):
    """정규화 루틴(CMPA-22)의 Normalizer 로 canonical id 를 비고에 주석. 실패해도 raw 보존."""
    try:
        sys.path.insert(0, os.path.join(ROOT, "scripts"))
        from normalize_whisky_name import Normalizer, load_rules
        norm = Normalizer(load_rules())
    except Exception as e:
        sys.stderr.write(f"[warn] 정규화 모듈 로드 실패({e}); raw 이름만 유지\n")
        return rows, {"matched": 0, "total": len(rows)}
    matched = 0
    for r in rows:
        res = norm.canonicalize(r["_name_only"])
        if res["status"] == "matched":
            matched += 1
            tag = f"id={res['id']}"
            r["비고"] = (r["비고"] + "; " + tag).strip("; ") if r["비고"] else tag
    return rows, {"matched": matched, "total": len(rows)}


# ──────────────────────────────────────────────────────────────────────────
# load: 월간 CSV 에 dedup append
# ──────────────────────────────────────────────────────────────────────────
def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def load_rows(rows, month=None, dry_run=False):
    if not rows:
        return {"appended": 0, "skipped": 0, "path": None}
    month = month or (rows[0]["가져온날짜"][:7] if rows[0]["가져온날짜"] else None)
    if not month:
        raise SystemExit("월(month) 추정 실패 — --month YYYY-MM 지정 필요")
    path = os.path.join(PRICES_DIR, f"{month}.csv")
    existing = _read_csv(path)
    # dedup key: (술이름, 가격, 위치, 가져온날짜) — 같은 영상 재실행 시 중복 방지
    seen = {(r["술이름"], str(r["가격_KRW"]), r["위치"], r["가져온날짜"]) for r in existing}
    appended, skipped = [], 0
    for r in rows:
        key = (r["술이름"], str(r["가격_KRW"]), r["위치"], r["가져온날짜"])
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        appended.append({k: r[k] for k in SCHEMA})
    if not dry_run and appended:
        new_file = not os.path.exists(path)
        with open(path, "a", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=SCHEMA)
            if new_file:
                w.writeheader()
            w.writerows(appended)
    return {"appended": len(appended), "skipped": skipped, "path": path,
            "appended_rows": appended}


# ──────────────────────────────────────────────────────────────────────────
# fetch: ko ASR 자막 다운로드 (페이싱 가드)
# ──────────────────────────────────────────────────────────────────────────
def _pace_check(force=False):
    os.makedirs(STATE_DIR, exist_ok=True)
    last = 0
    if os.path.exists(PACE_FILE):
        try:
            last = json.load(open(PACE_FILE)).get("ts", 0)
        except Exception:
            last = 0
    elapsed = time.time() - last
    if not force and elapsed < PACE_SECONDS:
        wait = int((PACE_SECONDS - elapsed) / 60)
        raise SystemExit(
            f"[pace] 마지막 fetch 후 {int(elapsed/60)}분 — per-IP 429 회피 위해 "
            f"{wait}분 더 대기. 강제 실행: --force")


def _pace_mark():
    os.makedirs(STATE_DIR, exist_ok=True)
    json.dump({"ts": time.time()}, open(PACE_FILE, "w"))


def fetch_subtitle(video_id, force=False):
    _pace_check(force=force)
    os.makedirs(SUB_CACHE, exist_ok=True)
    out_tmpl = os.path.join(SUB_CACHE, "%(id)s.%(ext)s")
    cmd = ["yt-dlp", "--skip-download", "--write-auto-subs", "--sub-langs", "ko",
           "--sub-format", "json3", "-o", out_tmpl,
           f"https://www.youtube.com/watch?v={video_id}"]
    sys.stderr.write("[fetch] " + " ".join(cmd) + "\n")
    r = subprocess.run(cmd, capture_output=True, text=True)
    _pace_mark()
    if r.returncode != 0:
        sys.stderr.write(r.stderr[-1500:] + "\n")
        raise SystemExit(f"[fetch] yt-dlp 실패 (rc={r.returncode})")
    path = os.path.join(SUB_CACHE, f"{video_id}.ko.json3")
    if not os.path.exists(path):
        raise SystemExit(f"[fetch] ko 자막 없음: {path}")
    print(path)
    return path


# ──────────────────────────────────────────────────────────────────────────
# discover: 채널 영상에서 트레이더스 영상 필터
# ──────────────────────────────────────────────────────────────────────────
def discover(channel, limit=30, out=None):
    ch = CHANNELS.get(channel)
    if not ch:
        raise SystemExit(f"알 수 없는 채널: {channel} ({'|'.join(CHANNELS)})")
    url = f"https://www.youtube.com/{ch['handle']}/videos"
    cmd = ["yt-dlp", "--flat-playlist", "--playlist-end", str(limit),
           "--print", "%(id)s\t%(title)s\t%(upload_date)s", url]
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
        upload = parts[2] if len(parts) > 2 else ""
        if "트레이더스" in title or "trader" in title.lower():
            rows.append({"video_id": vid, "title": title, "upload_date": upload,
                         "channel": ch["label"]})
    if out:
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["video_id", "title", "upload_date", "channel"])
            w.writeheader()
            w.writerows(rows)
    for x in rows:
        print(f"{x['video_id']}\t{x['upload_date']}\t{x['title']}")
    sys.stderr.write(f"[discover] 트레이더스 영상 {len(rows)}건\n")
    return rows


# ──────────────────────────────────────────────────────────────────────────
# CLI
# ──────────────────────────────────────────────────────────────────────────
def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("discover")
    p.add_argument("--channel", default="whiskeypick")
    p.add_argument("--limit", type=int, default=30)
    p.add_argument("--out")

    p = sub.add_parser("fetch")
    p.add_argument("--video", required=True)
    p.add_argument("--force", action="store_true")

    p = sub.add_parser("parse")
    p.add_argument("--sub", required=True)
    p.add_argument("--video")
    p.add_argument("--location")
    p.add_argument("--date")
    p.add_argument("--channel-label", default="@whiskeypick")
    p.add_argument("--no-normalize", action="store_true")

    p = sub.add_parser("load")
    p.add_argument("--sub", required=True)
    p.add_argument("--video")
    p.add_argument("--location")
    p.add_argument("--date")
    p.add_argument("--month")
    p.add_argument("--channel-label", default="@whiskeypick")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-normalize", action="store_true")

    a = ap.parse_args()

    if a.cmd == "discover":
        discover(a.channel, limit=a.limit, out=a.out)
        return

    if a.cmd == "fetch":
        fetch_subtitle(a.video, force=a.force)
        return

    if a.cmd in ("parse", "load"):
        rows, meta = parse_subtitle(a.sub, video_id=a.video, location=a.location,
                                    date=a.date, channel_label=a.channel_label)
        if not a.no_normalize:
            rows, nmeta = annotate_canonical(rows)
        else:
            nmeta = {"matched": 0, "total": len(rows)}
        sys.stderr.write(
            f"[parse] {meta['location']} / {meta['date']} — {len(rows)}행 추출, "
            f"정규화 매칭 {nmeta['matched']}/{nmeta['total']}, "
            f"낮음(자릿수의심) {sum(1 for r in rows if r['신뢰도']=='낮음')}건\n")
        if a.cmd == "parse":
            w = csv.DictWriter(sys.stdout, fieldnames=SCHEMA)
            w.writeheader()
            for r in rows:
                w.writerow({k: r[k] for k in SCHEMA})
            return
        res = load_rows(rows, month=a.month, dry_run=a.dry_run)
        tag = "[dry-run] " if a.dry_run else ""
        sys.stderr.write(
            f"{tag}[load] {res['path']} — append {res['appended']}행, "
            f"중복 skip {res['skipped']}행\n")
        # 실행일 스냅샷: 누적 월간 정본의 이번 실행 시점 상태를 _runs/ 에 보존
        if not a.dry_run and res.get("path") and res.get("appended"):
            snap = snapshot(res["path"], run_date=kst_today())
            if snap:
                sys.stderr.write(f"[load] 실행 스냅샷 -> {snap}\n")
        return


if __name__ == "__main__":
    main()
