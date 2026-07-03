#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
run_ocr_collection.py — CMPA-424 (2/2) 신규 가격영상 자동수집 오케스트레이터.

@whiskeypick·@whiskeykey 의 **신규 영상**을 discover → frame_ocr(다운로드→프레임→crop→OCR)
→ 품질게이트 적재(ingest_ocr) 까지 한 번에 돈다. 이미 처리한 video_id 는 skip(멱등).

설계(영상 다운로드가 무거워 보수적으로):
  · **동시성 1**(영상 순차 처리), 1회 실행당 **--max 영상 수 상한**(기본 1).
  · **pace 가드**: 마지막 전체 실행 후 --min-hours(기본 12h) 이내 재실행 거부(--force 무시).
    (ASR timedtext 429 와 달리 muxed 영상 다운로드라 자막 429 무관 — 과도 다운로드만 자제.)
  · discover 는 가벼운 flat-playlist(메타만). 처리는 가장 **오래된 미처리 영상부터**(시간순 누적).
  · 각 영상: run_demo.sh(다운로드→프레임→crop→OCR) → ingest_ocr.ingest(품질게이트→월별 CSV).
    실패한 영상은 건너뛰되 processed 로 마킹하지 않음(다음 실행 재시도).

용법:
  python3 run_ocr_collection.py                 # 신규 1영상 처리(pace 가드)
  python3 run_ocr_collection.py --max 2 --force # pace 무시, 최대 2영상
  python3 run_ocr_collection.py --discover-only # 신규 후보만 출력(다운로드 X)
"""
import argparse
import csv
import glob
import json
import os
import re
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, ROOT)
from pipelines.youtube_traders.frame_ocr import ingest_ocr  # noqa: E402

STATE_DIR = os.path.join(os.path.dirname(HERE), ".state")
PACE_FILE = os.path.join(STATE_DIR, "ocr_collection_last_run.json")
PRICES_DIR = ingest_ocr.PRICES_DIR
# 외부글 배포 폴더(CMPA-355 deploy_external_post.py 가 검증·라이브 발행). 블로그 글 1개=md 1개.
EXTERNAL_POSTS_DIR = os.path.join(ROOT, "content", "external-posts")

# 채널 → crop 템플릿(crop_price_tag.py). whiskeypick=종이 가격표, whiskeykey=그래픽 오버레이.
CHANNELS = {
    "whiskeypick": {"handle": "@whiskeypick", "label": "@whiskeypick", "template": "whiskeypick"},
    "whiskeykey": {"handle": "@whiskeykey", "label": "@whiskeykey", "template": "whiskeykey"},
}
# 가격영상 제목 신호(비-가격 콘텐츠/쇼츠 다운로드 회피). 채널 특성상 대부분 가격영상이지만
# 시음/잡담 영상은 제외해 다운로드를 아낀다.
PRICE_TITLE_HINTS = ("가격", "트레이더스", "코스트코", "trader", "costco", "시세", "마트")


def discover(channel, limit=20):
    ch = CHANNELS[channel]
    url = f"https://www.youtube.com/{ch['handle']}/videos"
    # description 포함 — @whiskeykey 처럼 설명에 '촬영 장소 : 지점' 을 쓰는 채널 대응(CMPA-446)
    cmd = ["yt-dlp", "--flat-playlist", "--playlist-end", str(limit),
           "--print", "%(id)s\t%(title)s\t%(upload_date)s\t%(description)s", url]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(f"[discover] {channel} yt-dlp 실패\n{r.stderr[-600:]}\n")
        return []
    out = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        vid, title = parts[0], parts[1]
        upload = parts[2] if len(parts) > 2 else ""
        desc = parts[3] if len(parts) > 3 else ""
        if any(h.lower() in title.lower() for h in PRICE_TITLE_HINTS):
            out.append({"video_id": vid, "title": title, "upload_date": upload,
                        "description": desc,
                        "channel": channel, "label": ch["label"],
                        "template": ch["template"]})
    return out


def discover_new(channels, limit=20, newest_first=False):
    """모든 채널에서 미처리 가격영상 후보.
    기본은 오래된→최신(누적 처리). newest_first=True 면 최신→오래된(일간 루틴 권장:
    최신 현장가를 먼저 floor·블로그에 반영, 오래된 백필은 뒤로 흘려보냄)."""
    cands = []
    for c in channels:
        cands += discover(c, limit=limit)
    new = [v for v in cands if not ingest_ocr.is_processed(v["video_id"])]
    # 업로드일(없으면 제목 날짜) 기준 정렬. 둘 다 없으면 맨 뒤.
    for v in new:
        v["_date"] = (ingest_ocr._yyyymmdd(v["upload_date"])
                      or ingest_ocr.date_from_title(v["title"]) or "")
    if newest_first:
        new.sort(key=lambda v: v["_date"] or "00000000", reverse=True)
    else:
        new.sort(key=lambda v: v["_date"] or "99999999")
    return new


def _pace_ok(min_hours, force):
    if force:
        return True, 0
    if not os.path.exists(PACE_FILE):
        return True, 0
    try:
        last = json.load(open(PACE_FILE)).get("ts", 0)
    except Exception:
        last = 0
    elapsed = time.time() - last
    need = min_hours * 3600
    return elapsed >= need, max(0, (need - elapsed) / 3600)


def _pace_mark():
    os.makedirs(STATE_DIR, exist_ok=True)
    json.dump({"ts": time.time()}, open(PACE_FILE, "w"))


def process_video(v):
    """1영상: run_demo.sh(다운로드→프레임→crop→OCR) → ingest. 성공 시 ingest 결과 dict."""
    vid = v["video_id"]
    demo_dir = os.path.join(HERE, "_demo", vid)
    result_csv = os.path.join(demo_dir, "result.csv")
    sys.stderr.write(f"\n[process] {vid} ({v['channel']}) — {v['title'][:50]}\n")
    cmd = ["bash", os.path.join(HERE, "run_demo.sh"), vid, v["template"]]
    r = subprocess.run(cmd, cwd=HERE)
    if r.returncode != 0 or not os.path.exists(result_csv):
        sys.stderr.write(f"[process] {vid} frame_ocr 실패(rc={r.returncode}) — skip(다음 실행 재시도)\n")
        return None
    return ingest_ocr.ingest(result_csv, vid, v["label"], v["title"], v["upload_date"],
                             description=v.get("description", ""))


def _prior_prices():
    """이번 실행 전, 이미 적재된 youtube_ocr 정본의 {술이름: 최근가격} 맵.
    변경사항(신규/가격변동) 판정 기준선. 같은 이름 여러 행이면 마지막(최근 적재)값."""
    prior = {}
    for path in sorted(glob.glob(os.path.join(PRICES_DIR, "*_youtube_ocr.csv"))):
        try:
            with open(path, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    name = (r.get("술이름") or "").strip()
                    try:
                        prior[name] = int(str(r.get("가격_KRW", "")).replace(",", ""))
                    except (ValueError, TypeError):
                        continue
        except FileNotFoundError:
            continue
    return prior


def classify_changes(accepted_rows, prior):
    """적재분을 직전 정본과 비교 → 변경사항만 추린다.
    반환: [{'name','price','store','source','kind','old'}] (kind=신규|가격변동)."""
    changes = []
    for a in accepted_rows:
        name = a.get("술이름", "")
        try:
            price = int(str(a.get("가격_KRW", "")).replace(",", ""))
        except (ValueError, TypeError):
            continue
        old = prior.get(name)
        if old is None:
            kind = "신규"
        elif old != price:
            kind = "가격변동"
        else:
            continue                     # 동일가 = 변경 아님(이메일/블로그 제외)
        # CMPA-446: 지점(매장)을 reader-visible store 라벨로 결합(트레이더스 구월점).
        store = ingest_ocr.store_display(a.get("위치", ""), a.get("지점", ""))
        changes.append({"name": name, "price": price, "store": store,
                        "source": a.get("출처", ""), "kind": kind, "old": old,
                        "date": (a.get("가져온날짜") or "").strip()})
    return changes


def fresh_changes(changes, max_age_days=14):
    """블로그/이메일 발행 대상 = '최근 수집분'만. 오래된 백필 영상을 '오늘의 변동'으로
    오인 발행하지 않도록 가른다(수집날짜 메타 정직성, CLAUDE.md 데이터 관리 원칙③).
    가져온날짜(영상 기준일)가 today-max_age_days 이후인 변경만 발행. 날짜 미상은 보수적 제외.
    데이터(CSV/floor) 적재는 freshness 와 무관하게 이미 끝났고, 여기선 '발행' 여부만 가른다."""
    from datetime import datetime, timedelta
    try:
        today = datetime.strptime(ingest_ocr.kst_today(), "%Y-%m-%d")
    except ValueError:
        return changes, []
    cutoff = today - timedelta(days=max_age_days)
    fresh, stale = [], []
    for c in changes:
        try:
            d = datetime.strptime(c.get("date", ""), "%Y-%m-%d")
        except ValueError:
            stale.append(c)
            continue
        (fresh if d >= cutoff else stale).append(c)
    return fresh, stale


def _stores_label(changes):
    """변경분에 실제로 등장한 매장(위치)들을 '·'로 묶어 정직한 라벨 생성. 위장 금지(CLAUDE.md):
    제목/리드가 '트레이더스'로 고정되면 코스트코·마트 변동이 트레이더스로 오인된다."""
    seen = []
    for c in changes:
        s = (c.get("store") or "").strip()
        if s and s not in seen:
            seen.append(s)
    return "·".join(seen) if seen else "트레이더스/코스트코"


def _source_md(source):
    """출처 텍스트를 클릭 가능한 YouTube 링크로 감싼다(CMPA-485). 출처에 video_id 가 박혀
    있으면(`유튜브 {채널} / {video_id} ...`) `[출처 ▶](watch?v=...)` 마크다운 링크로 만든다.
    표시 텍스트에선 긴 `/ {video_id}` 와 `@ N초` 는 떼어 모바일 칸을 짧게 유지(CLAUDE.md).
    video_id 미상이면 원문 텍스트만 반환(위장·깨진 링크 금지). 마크다운 링크는 블로그(md)와
    이메일(email_report._inline_md) 양쪽에서 클릭 가능하다."""
    source = (source or "").strip()
    if not source:
        return source
    vid = ingest_ocr._video_id_from_src(source)
    if not vid:
        return source                    # 미상 — 텍스트 폴백(위장 금지)
    label = source.replace(f" / {vid}", "")
    label = re.sub(r"\s*@\s*\d+초", "", label).strip()
    return f"[{label} ▶](https://www.youtube.com/watch?v={vid})"


_ID_RE = re.compile(r"id=(w\d+)")


def _load_desc_lookup():
    """assets/whisky-list.csv → {canonical id: '싱글몰트 · 스코틀랜드 스페이사이드 · 12년'}.
    리더용 위스키 설명(CMPA-484 보드). notes 컬럼은 'OCR 재확인 필요' 등 **내부 감사 메모**가
    섞여 독자 노출 부적합 → 사실 컬럼(category·origin·age)만 조합한다."""
    path = os.path.join(ROOT, "assets", "whisky-list.csv")
    out = {}
    try:
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                parts = []
                cat = (r.get("category") or "").strip()
                origin = (r.get("origin") or "").strip().replace("-", " ")
                age = (r.get("age") or "").strip()
                if cat:
                    parts.append(cat)
                if origin:
                    parts.append(origin)
                if age.isdigit():
                    parts.append(f"{age}년")
                out[(r.get("id") or "").strip()] = " · ".join(parts)
    except FileNotFoundError:
        pass
    return out


NORM_PRICES = os.path.join(ROOT, "data", "whisky-prices", "normalized", "normalized_prices.csv")


def _domestic_floor_lookup(max_age_days=40):
    """normalized_prices 에서 정본 id별 **국내 최저가** {id: (price, source_label, prev_price)}.
    '다른데(코스트코·데일리샷 등) 더 싼 곳이 있으면 보여줘'(보드 CMPA-484)용. market KR/KR-DS 만
    (해외 HK/JP 제외), 최근 max_age_days 이내(stale 제외), 제외행·샘플(<15,000)·면세 제외
    (면세는 normalized 에 없음 — CMPA-321).

    ⚠️ floor = **소스(매장)별 '최신 관측가' 중 최소값**(CMPA-496 보드). 트레이더스/코스트코는
    가격을 전 지점 동일하게 오르내리므로 같은 소스의 과거 저가는 무효(superseded) — 단순
    min() 으로 잡으면 가격 인상을 인하처럼 보이게 한다(w030: 89,800 옛값 → 109,800 현재값).
    채널(branch 제외 매장명)을 소스 키로 묶어 per_source_latest_floor 가 골라준다.
    prev_price = floor 소스의 직전가(방향 ▲/▼ 표기용, 없으면 None).

    ⚠️ 소스 키(CMPA-500 보드): **데일리샷(온라인 마켓플레이스 셀러)은 물리 매장과 분리**한다.
    데일리샷 셀러 '트레이더스'(185,000·06-19)는 이마트 트레이더스 물리 매장이 아니다 — 같은
    채널명이라고 물리 트레이더스 관측(youtube)과 합치면, 데일리샷 최신가가 '트레이더스 최신가'로
    둔갑하고 youtube 직전가가 '직전가'로 붙어 '179,800→185,000 ▲인상' 같은 가짜 변동 라인이
    뜬다(현재가 209,800 과 모순). 따라서 dailyshot 은 ``dailyshot/<channel>`` 복합키로 분리한다.
    반대로 **물리 매장은 channel 키로 병합 유지** — youtube_ocr 와 youtube_martweb 의 '트레이더스'는
    같은 물리 매장을 다른 방법(프레임OCR vs 웹)으로 읽은 것이라, source_family 까지 키에 넣어
    쪼개면 CMPA-496 의 stale-min 수정이 깨진다(w030: martweb 89,800(05-27) 이 다시 floor 로
    선택됨). 즉 분리 기준은 source_family 전부가 아니라 '온라인 마켓 vs 물리 매장' 이다."""
    from datetime import datetime, timedelta
    from pipelines.common.source_floor import per_source_latest_floor
    try:
        cutoff = (datetime.strptime(ingest_ocr.kst_today(), "%Y-%m-%d")
                  - timedelta(days=max_age_days)).strftime("%Y-%m-%d")
    except ValueError:
        cutoff = ""
    obs = {}                                              # cid -> [(channel, date, price)]
    try:
        with open(NORM_PRICES, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                cid = (r.get("canonical_id") or "").strip()
                if not cid or (r.get("exclude_reason") or "").strip():
                    continue
                if (r.get("market") or "").strip() not in ("KR", "KR-DS"):
                    continue                              # 국내만(해외 벤치마크 제외)
                d = (r.get("date") or "").strip()
                if cutoff and d < cutoff:
                    continue                              # 최근만(과거 저가 stale 방지)
                try:
                    p = int(str(r.get("price_krw", "")).replace(",", ""))
                except (ValueError, TypeError):
                    continue
                if p < 15000:
                    continue                              # 샘플/미니 노이즈
                fam = (r.get("source_family") or "").strip()
                ch = (r.get("channel") or "").strip()
                # dailyshot(온라인 마켓 셀러)은 물리 매장과 분리(복합키), 물리 매장은 channel
                # 병합 유지(youtube_ocr·youtube_martweb 트레이더스 = 같은 매장) — CMPA-500.
                src = f"dailyshot/{ch or '?'}" if fam == "dailyshot" else (ch or fam)
                obs.setdefault(cid, []).append((src, d, p))
    except FileNotFoundError:
        pass
    best = {}
    for cid, rows in obs.items():
        fl = per_source_latest_floor(rows)               # (price, source, prev) | None
        if fl:
            best[cid] = fl
    return best


def _floor_source_label(src):
    """floor 소스키(_domestic_floor_lookup 가 만든) → 독자용 출처 라벨(CMPA-500).
    데일리샷 셀러는 ``dailyshot/<channel>`` 복합키로 들어온다 → '데일리샷'으로 명시해
    이마트 트레이더스 물리 매장과 혼동을 막는다(셀러명이 '트레이더스'여도 '데일리샷' 표기).
    물리 매장(youtube)은 channel 키 그대로(예: '트레이더스'·'코스트코')."""
    fam, sep, ch = (src or "").partition("/")
    if sep and fam == "dailyshot":
        return "데일리샷"
    if sep:
        return ch or fam                                 # 혹시 모를 타 복합키는 채널부 노출
    return fam


def _dutyfree_lookup():
    """신라면세 CSV(USD)에서 정본 id별 **면세 현재가** 매칭 준비물(CMPA-492 보드).
    면세는 normalized DB 에 없어(CMPA-321 면세 제외) canonical_id 매칭이 안 된다 → 신라
    상품명과 퍼지 매칭이 필요하다. analyze_attractiveness 의 검증된 매칭 가드(에디션 EDITION_KW·
    길이 EXTRA_TOL·norm 부분일치)를 재사용하되, 보드 지시대로 **같은 용량(700ml↔700ml)만**
    비교한다 — 용량 다른 병끼리 비교하면 가짜 % 가 나고 CMPA-177 오매칭(발베12 vs 발베18) 위험.
    반환: (canon{id:row}, shilla_rows, meta{sdate,fx_asof,usd_krw}). 신라/환율 파일 없으면 None."""
    try:
        from pipelines.shilla_dutyfree import analyze_attractiveness as aa
        usd_krw, fx_asof = aa.load_fx()
        files = sorted(glob.glob(os.path.join(
            ROOT, "data", "shilla-dutyfree", "신라면세_위스키_*.csv")))
        if not files:
            return None
        m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(files[-1]))
        sdate = m.group(1) if m else ""
        shilla = aa.load_shilla(sdate)
        canon = {r["id"]: r for r in aa.load_canonical()}
    except (FileNotFoundError, KeyError, ImportError):
        return None
    return canon, shilla, {"sdate": sdate, "fx_asof": fx_asof, "usd_krw": usd_krw}


def _match_dutyfree(name, wid, trader_vol, df):
    """트레이더스 1종(name·정본 wid·용량 trader_vol) → 신라면세 매칭가 {krw, sname} 또는 None.
    같은 용량·표준판(에디션·길이 가드)만 매칭한다(위장 금지 — 확신 못하면 None). df=_dutyfree_lookup()."""
    from pipelines.shilla_dutyfree import analyze_attractiveness as aa
    canon, shilla, meta = df
    c = canon.get(wid)
    if not c or not c.get("_norm"):
        return None
    cand = []
    for s in shilla:
        if s["_usd"] is None or s["_vol"] != trader_vol:
            continue                                  # 같은 용량만(보드 700ml↔700ml)
        if c["_norm"] not in s["_norm"]:
            continue                                  # canonical 부분일치
        if any(kw in s["_norm"] and kw not in c["_norm"] for kw in aa.EDITION_KW):
            continue                                  # 셰리/CS/에디션 비대칭 → 다른 SKU
        if len(s["_norm"]) - len(c["_norm"]) - 5 > aa.EXTRA_TOL:
            continue                                  # 추가 수식어 과다 → 특별판 의심
        cand.append((s["_usd"], s))
    if not cand:
        return None
    cand.sort(key=lambda x: x[0])                      # 같은 용량 내 최저 면세가
    s = cand[0][1]
    return {"krw": int(round(s["_usd"] * meta["usd_krw"])), "sname": s["위스키명"]}


def _collection_history():
    """youtube_ocr 정본 전체에서 {(술이름, 매장): {수집일: 가격}}. '직전 수집일 대비 변동'
    계산용(보드 CMPA-484). **매장(store_display)별로 분리** — 지점마다 가격이 달라(CMPA-446)
    교차-매장 비교는 가짜 변동이 된다(예: 우성마트 카발란 85,000 vs 트레이더스 69,800).
    같은 매장·같은 날 여러 가격이면 마지막 값(best-effort)."""
    hist = {}
    for path in sorted(glob.glob(os.path.join(PRICES_DIR, "*_youtube_ocr.csv"))):
        try:
            with open(path, encoding="utf-8-sig") as f:
                for r in csv.DictReader(f):
                    name = (r.get("술이름") or "").strip()
                    d = (r.get("가져온날짜") or "").strip()
                    if not name or not d:
                        continue
                    try:
                        p = int(str(r.get("가격_KRW", "")).replace(",", ""))
                    except (ValueError, TypeError):
                        continue
                    store = ingest_ocr.store_display(r.get("위치", ""), r.get("지점", ""))
                    hist.setdefault((name, store), {})[d] = p
        except FileNotFoundError:
            continue
    return hist


def _current_prices_md(accepted_rows, kst_date):
    """이번 런 적재 위스키 전체의 '현재가' 표(변동 표 아래 부가 섹션, CMPA-484).
    보드 리디자인(2026-06-19): ① **유튜브 링크는 표 밖에 영상당 1개**(48행 동일 링크 반복 제거)
    ② 각 행에 **직전 수집일 대비 가격 변동**(🔺/🔻/🆕) ③ **위스키 설명**(category·origin·age).
    같은 이름은 최신 수집행 1건 dedup, 가격 내림차순. 빈 입력이면 빈 문자열."""
    best = {}
    for a in accepted_rows or []:
        name = (a.get("술이름") or "").strip()
        if not name:
            continue
        try:
            price = int(str(a.get("가격_KRW", "")).replace(",", ""))
        except (ValueError, TypeError):
            continue
        d = (a.get("가져온날짜") or "").strip()
        prev = best.get(name)
        if prev is not None and d < prev["date"]:
            continue                     # 더 오래된 관측 — 최신 1행만 유지
        wid = _ID_RE.search(a.get("비고", "") or "")
        best[name] = {"name": name, "price": price, "date": d,
                      "store": ingest_ocr.store_display(a.get("위치", ""), a.get("지점", "")),
                      "source": (a.get("출처") or "").strip(),
                      "video": ingest_ocr._video_id_from_src(a.get("출처", "")),
                      "wid": wid.group(1) if wid else ""}
    items = sorted(best.values(), key=lambda x: -x["price"])
    if not items:
        return ""
    desc = _load_desc_lookup()
    hist = _collection_history()
    floor = _domestic_floor_lookup()         # 정본 id별 국내 최저가(다른 매장 비교용)
    df = _dutyfree_lookup()                   # 신라면세 매칭 준비물(CMPA-492) — 없으면 None
    df_aa = None
    if df:
        from pipelines.shilla_dutyfree import analyze_attractiveness as df_aa
    stores = {i["store"] for i in items if i["store"]}
    multi_store = len(stores) > 1            # 단일 매장이면 출처 줄에만, 여러 매장이면 행에도 표기

    # 출처 = 영상당 1줄(표 밖). 같은 video_id 는 한 번만. (보드: 동일 링크 48개 반복 금지)
    srcs = {}
    for i in items:
        vid = i["video"]
        if not vid or vid in srcs:
            continue
        m = re.search(r"(@\w+)", i["source"] or "")
        ch = f"유튜브 {m.group(1)}" if m else "유튜브"
        srcs[vid] = {"store": i["store"], "date": i["date"], "ch": ch, "vid": vid}
    src_lines = []
    for s in srcs.values():
        label = " · ".join(x for x in (s["store"], s["ch"], s["date"]) if x)
        src_lines.append(
            f"> 출처: {label} — [영상 보기 ▶](https://www.youtube.com/watch?v={s['vid']})")

    lines = ["", f"### 📋 이번 수집 위스키 현재가 (전체 {len(items)}종) — 수집일 {kst_date}", ""]
    lines += src_lines
    lines += ["", "| 위스키 | 상세 |", "|---|---|"]
    df_used = False
    for i in items:
        h = hist.get((i["name"], i["store"]), {})    # 같은 매장 이력만(교차-매장 비교 금지)
        prevs = sorted((d, p) for d, p in h.items() if d < i["date"])
        if prevs:
            pp = prevs[-1][1]
            if i["price"] > pp:
                badge = f" 🔺{i['price'] - pp:,}"
            elif i["price"] < pp:
                badge = f" 🔻{pp - i['price']:,}"
            else:
                badge = ""               # 직전과 동일가 = 배지 없음
        else:
            badge = " 🆕"                 # 첫 수집(직전 관측 없음)
        sub_parts = [x for x in (desc.get(i["wid"], ""),) if x]
        if multi_store and i["store"]:
            sub_parts.append(i["store"])
        # 다른 매장(코스트코·데일리샷 등) 국내 최저가가 더 싸면 노출(보드 CMPA-484).
        # floor = 소스별 최신가 중 최소값(CMPA-496) → 옛 트레이더스 저가는 superseded 라 안 잡힘.
        # 가드(CMPA-177): 트레이더스가가 최저가의 2.5배↑면 다른 SKU 오매칭 의심 → 숨김(가짜딜 방지).
        fl = floor.get(i["wid"]) if i["wid"] else None
        cheaper = ""
        if fl and fl[0] < i["price"] <= fl[0] * 2.5:
            # floor 소스가 직전가 대비 바뀌었으면 방향(▲인상/▼인하) 병기(보드 CMPA-496 규칙2).
            prev = fl[2] if len(fl) > 2 else None
            arrow = (f" {prev:,}→{fl[0]:,} {'▲인상' if fl[0] > prev else '▼인하'}"
                     if prev is not None and prev != fl[0] else "")
            cheaper = f" · 🏷 국내최저 {fl[0]:,}원({_floor_source_label(fl[1])}{arrow})"
        # 면세(신라면세) 현재가 + 트레이더스 vs 면세 %(보드 CMPA-492). 같은 용량·표준판만
        # 매칭(_match_dutyfree), 확신 못하면 생략(위장 금지). +%=트레이더스가 더 비쌈.
        duty = ""
        if df and i["wid"]:
            tv = df_aa.vol_of(i["name"]) or df[0].get(i["wid"], {}).get("_vol") or 700
            dm = _match_dutyfree(i["name"], i["wid"], tv, df)
            if dm and dm["krw"] > 0:
                pct = round((i["price"] - dm["krw"]) / dm["krw"] * 100)
                duty = f" · ✈️ 면세 {dm['krw']:,}원 · 트레이더스 {'+' if pct >= 0 else ''}{pct}%"
                df_used = True
        extra = f"{cheaper}{duty}"
        sub = f"<br><sub>{' · '.join(sub_parts)}{extra}</sub>" if (sub_parts or extra) else ""
        lines.append(f"| {i['name']} | {i['price']:,}원{badge}{sub} |")
    if df_used:
        meta = df[2]
        lines.append("")
        lines.append(f"> ✈️ 면세가: 신라면세 {meta['sdate']} 수집 · 환율 {meta['fx_asof']} "
                     f"(USD₩{meta['usd_krw']:,.0f}) 기준 · 트레이더스 +%=면세보다 비쌈")
    return "\n".join(lines)


def _changes_md(changes, kst_date, accepted_rows=None):
    """변경사항 → 마크다운 본문(이메일·블로그 공용). 모바일 2컬럼 표(CLAUDE.md).
    accepted_rows 가 주어지면 변동 표 아래에 '이번 수집 위스키 현재가' 표를 부가 섹션으로
    덧붙인다(CMPA-484). 발행 트리거는 여전히 변동분이며 현재가 표는 부가물이다."""
    n_new = sum(1 for c in changes if c["kind"] == "신규")
    n_chg = len(changes) - n_new
    lines = [f"{_stores_label(changes)} 유튜브 가격영상(프레임 OCR)에서 **{len(changes)}건**의 "
             f"변경사항을 수집했습니다 (신규 {n_new} · 가격변동 {n_chg}). 수집일 {kst_date}.",
             "", "| 위스키 | 상세 |", "|---|---|"]
    for c in sorted(changes, key=lambda x: (x["kind"] != "신규", -x["price"])):
        badge = "🆕 신규" if c["kind"] == "신규" else f"🔄 {c['old']:,}→"
        detail = f"{badge}{c['price']:,}원 · {c['store']}<br><sub>{_source_md(c['source'])}</sub>"
        lines.append(f"| {c['name']} | {detail} |")
    current = _current_prices_md(accepted_rows, kst_date)
    if current:
        lines.append(current)
    lines += ["", "> 가격표를 화면에 0.5초+ 정지하는 지점을 프레임 OCR 로 읽어 수집합니다 "
              "(ASR 우회, CMPA-423). 수집 날짜 기준값이며 현재가와 다를 수 있습니다."]
    return "\n".join(lines)


def notify_email(changes, to_addrs, kst_date, accepted_rows=None):
    """변경사항을 이메일로 발송(reuse email_report.send_report). 자격 없으면 경고만.
    accepted_rows 가 있으면 변동 표 아래 '이번 수집 위스키 현재가' 표를 함께 보낸다(CMPA-484)."""
    if not changes or not to_addrs:
        return False
    try:
        from pipelines.common.email_report import send_report
    except Exception as e:
        sys.stderr.write(f"[email] import 실패: {e}\n")
        return False
    subject = f"[유튜브 {_stores_label(changes)}] 위스키 가격 변경 {len(changes)}건 ({kst_date})"
    body = _changes_md(changes, kst_date, accepted_rows)
    try:
        sent = send_report(subject, body, to_addrs=to_addrs)
        sys.stderr.write(f"[email] 발송 완료 → {', '.join(sent)}\n")
        return True
    except Exception as e:
        sys.stderr.write(f"[email] 발송 실패(자격/네트워크): {e}\n")
        return False


def write_blog_md(changes, kst_date, accepted_rows=None):
    """변경사항 → content/external-posts/ 마크다운 1개(wprice 버킷). 실제 라이브 발행은
    deploy_external_post.py 가 담당(검증+surgical push). 작성 경로 반환(없으면 None).
    accepted_rows 가 있으면 변동 표 아래 '이번 수집 위스키 현재가' 표를 함께 쓴다(CMPA-484)."""
    if not changes:
        return None
    os.makedirs(EXTERNAL_POSTS_DIR, exist_ok=True)
    slug = f"{kst_date}-youtube-traders-prices"
    path = os.path.join(EXTERNAL_POSTS_DIR, f"{slug}.md")
    stores = _stores_label(changes)
    front = (f"---\nlayout: post\n"
             f"title: \"[소매가] {stores} 가격 변동 {len(changes)}건 ({kst_date})\"\n"
             f"date: {kst_date} 08:30:00 +0900\n"
             f"categories: [wprice]\nkind: trprice\ndata_date: {kst_date}\n"
             f"tags: [유튜브가격, 위스키가격]\n"
             f"robots: noindex,nofollow\n---\n\n")
    with open(path, "w", encoding="utf-8") as f:
        f.write(front + _changes_md(changes, kst_date, accepted_rows) + "\n")
    sys.stderr.write(f"[blog] 외부글 md 작성 → {path}\n"
                     f"       (라이브 발행: python3 scripts/deploy_external_post.py)\n")
    return path


def main():
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--channels", nargs="+", default=list(CHANNELS),
                    choices=list(CHANNELS))
    ap.add_argument("--limit", type=int, default=20, help="채널당 discover 영상 수")
    ap.add_argument("--max", type=int, default=1, help="1회 실행 처리 영상 상한")
    ap.add_argument("--min-hours", type=float, default=12.0, help="전체 실행 간 최소 간격")
    ap.add_argument("--force", action="store_true", help="pace 가드 무시")
    ap.add_argument("--discover-only", action="store_true",
                    help="신규 후보만 출력(다운로드/적재 X)")
    ap.add_argument("--email", nargs="*", default=None,
                    help="변경사항(신규/가격변동) 발생 시 알림 이메일 수신자(생략 시 미발송)")
    ap.add_argument("--blog", action="store_true",
                    help="변경사항 시 content/external-posts/ 블로그 md 작성"
                         "(라이브 발행은 deploy_external_post.py)")
    ap.add_argument("--newest-first", action="store_true",
                    help="최신 영상부터 처리(기본은 오래된 것부터). 일간 루틴 권장: 최신 현장가 우선")
    ap.add_argument("--max-age-days", type=int, default=14,
                    help="블로그/이메일 발행 대상 최대 수집경과일(기본 14). "
                         "이보다 오래된 백필 영상은 데이터만 적재하고 발행은 생략")
    a = ap.parse_args()

    new = discover_new(a.channels, limit=a.limit, newest_first=a.newest_first)
    sys.stderr.write(f"[discover] 미처리 가격영상 후보 {len(new)}건\n")
    for v in new[:10]:
        sys.stderr.write(f"   - {v['upload_date']} {v['video_id']} [{v['channel']}] {v['title'][:48]}\n")
    if a.discover_only:
        for v in new:
            print(f"{v['video_id']}\t{v['upload_date']}\t{v['channel']}\t{v['title']}")
        return
    if not new:
        sys.stderr.write("[run] 신규 영상 없음 — 종료(멱등)\n")
        return

    ok, wait_h = _pace_ok(a.min_hours, a.force)
    if not ok:
        sys.stderr.write(
            f"[pace] 마지막 실행 후 {a.min_hours - wait_h:.1f}h — {wait_h:.1f}h 더 대기. "
            f"강제: --force\n")
        return

    prior = _prior_prices()         # 처리 전 정본 기준선(신규/가격변동 판정)
    n_done = 0
    totals = {"accepted": 0, "quarantined": 0}
    accepted_rows = []
    for v in new[:a.max]:           # 동시성 1: 순차 처리
        res = process_video(v)
        if res and not res.get("skipped"):
            n_done += 1
            totals["accepted"] += res.get("accepted", 0)
            totals["quarantined"] += res.get("quarantined", 0)
            accepted_rows += res.get("accepted_rows", [])
    _pace_mark()
    sys.stderr.write(
        f"\n[run] 처리 {n_done}영상 — 적재 {totals['accepted']} / 격리 "
        f"{totals['quarantined']} (잔여 미처리 {max(0, len(new) - n_done)}건)\n")

    # 변경사항(신규/가격변동)만 알림 — 동일가는 제외(보드: "변경사항이 있으면").
    changes = classify_changes(accepted_rows, prior)
    if changes:
        kst_date = ingest_ocr.kst_today()
        fresh, stale = fresh_changes(changes, a.max_age_days)
        sys.stderr.write(
            f"[change] 변경사항 {len(changes)}건 — 발행대상 최근 {len(fresh)} / "
            f"백필·미상 {len(stale)}건(데이터만 적재, 발행 제외)\n")
        if fresh:
            # 현재가 표(CMPA-484)는 이번 런 적재분 전체를 보여준다(변동분만이 아님).
            if a.email is not None:
                notify_email(fresh, a.email or None, kst_date, accepted_rows)
            if a.blog:
                write_blog_md(fresh, kst_date, accepted_rows)
        else:
            sys.stderr.write(
                "[change] 최근(발행대상) 변경 없음 — 이메일/블로그 생략(데이터는 적재됨)\n")
    else:
        sys.stderr.write("[change] 변경사항 없음 — 이메일/블로그 생략\n")


if __name__ == "__main__":
    main()
