#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_poll.py — 식당 Poll Phase 1 admin 도구 (CMPA-127)

흐름(보드 plan rev5, 방안 C-refined):
  Admin 이 정본 콜키지프리 데이터에서 한 역의 식당 4~5곳을 rid 로 고르면 →
  ① 그 식당들의 **정본 카드**(find_corkage_free._render_html 재사용) +
  ② StrawPoll **익명 API**(키 없이) 로 자동 생성한 poll 을 iframe 임베드한
  **단일 페이지**를 생성한다. Admin 은 page URL 하나만 공유 → 투표자는 같은
  페이지에서 상세 카드 보고 1클릭 투표 + 실시간 결과(집계·중복방지는 StrawPoll 위임).

정본 재사용 (CMPA-127 가드 — 독립 재구현 금지):
  - 카드 렌더: `pipelines/corkage_free/find_corkage_free.py` 의 `_render_html` 를 그대로 호출.
    (카드 마크업/CSS/모달/필터/인당비용 배지 전부 정본 엔진 산출 — 본 도구는 카드 HTML 을
     재작성하지 않는다. poll 섹션·카드별 투표 앵커만 정본 출력에 *덧붙인다*.)
  - 데이터: `data/corkage-free/{역}_콜키지프리.csv` (정본, utf-8-sig) + 인당비용 CSV.
  - rid 조인키·인당비용 맵·분류 전부 정본 엔진 함수(`row_rid`,`_load_cost_map`) 재사용.

가드레일:
  - DB/서버 신설 0 (투표 저장은 StrawPoll 위임).
  - 공개 배포 X — 내부 스테이징(deploy/poll/)만. 외부 공개는 CMPA-119 게이트(이 도구 범위 밖).

용법:
  python3 scripts/build_poll.py --station 강남역 --rids m5wGN8SvjWvK,3Et3gAnhaBGi,...   # 4~5개
  python3 scripts/build_poll.py --station 강남역 --rids ... --dry-run                  # poll 생성 안 함(렌더만)
"""
from __future__ import annotations
import argparse
import csv
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CORKAGE_DIR = ROOT / "data" / "corkage-free"
ENGINE_DIR = ROOT / "pipelines" / "corkage_free"
DEFAULT_OUT = ROOT / "deploy" / "poll" / "index.html"
STRAWPOLL_API = "https://api.strawpoll.com/v3/polls"

# 정본 카드 엔진 import (재구현 금지 — 그대로 재사용).
sys.path.insert(0, str(ENGINE_DIR))
import find_corkage_free as fcf  # noqa: E402


def load_station_rows(station: str) -> list[dict]:
    """정본 {역}_콜키지프리.csv 를 utf-8-sig 로 로드(엔진과 동일 규약)."""
    path = CORKAGE_DIR / f"{station}_콜키지프리.csv"
    if not path.exists():
        sys.exit(f"[build_poll] 정본 CSV 없음: {path}\n  → find_corkage_free.py --station {station} 로 먼저 생성하거나 정본 경로 확인.")
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def select_rows(rows: list[dict], rids: list[str]) -> list[dict]:
    """admin 이 고른 rid 순서대로 행 선택(정본 row_rid 조인키 사용)."""
    by_rid = {fcf.row_rid(r): r for r in rows}
    sel = []
    missing = []
    for rid in rids:
        r = by_rid.get(rid)
        if r is None:
            missing.append(rid)
        else:
            sel.append(r)
    if missing:
        sys.exit(f"[build_poll] CSV 에 없는 rid: {missing}\n  사용 가능 rid 예: {list(by_rid)[:8]} …")
    return sel


def option_description(row: dict) -> str:
    """poll 옵션 한 줄 설명 = 업종(대분류) · 1인 비용 · 페어링 위스키 (정본 필드)."""
    major = (row.get("대분류") or "").strip()
    parts = [major] if major else []
    rid = fcf.row_rid(row)
    cost = fcf._load_cost_map().get(rid, {})  # 정본 인당비용 맵 재사용
    std = (cost.get("1인_표준") or "").strip()
    if std:
        try:
            parts.append(f"1인 약 {int(round(float(std)/10000))}만원")
        except ValueError:
            parts.append(f"1인 {std}원")
    pair = (row.get("추천_위스키종류") or "").strip()
    if pair:
        parts.append(f"🥃 {pair}")
    return " · ".join(parts)


def create_poll(station: str, sel: list[dict], title: str | None) -> dict:
    """StrawPoll 익명 API(키 없이)로 poll 생성. 옵션 N = 선택 식당 N (1:1).
    반환: {id, url, embed_url, options:[{rid,name,description}]}."""
    options_meta = [
        {"rid": fcf.row_rid(r), "name": r["식당명"], "description": option_description(r)}
        for r in sel
    ]
    payload = {
        "title": title or f"[{station}] 위스키 한잔하기 좋은 콜키지프리 식당, 어디로 갈까요?",
        "poll_options": [
            {"type": "text", "value": o["name"], "description": o["description"]}
            for o in options_meta
        ],
        "poll_config": {
            "require_voter_account": False,   # 로그인 없이 투표
            "results_visibility": "always",   # 실시간 공개 결과
            "duplication_checking": "ip",     # IP 기반 중복방지(위젯 내장)
            "allow_comments": False,
            "is_private": False,
        },
    }
    req = urllib.request.Request(
        STRAWPOLL_API, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Accept": "application/json",
                 "User-Agent": "WK-build-poll/1.0 (CMPA-127)"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            d = json.load(resp)
    except urllib.error.HTTPError as e:
        sys.exit(f"[build_poll] StrawPoll 생성 실패 HTTP {e.code}: {e.read().decode()[:400]}")
    return {
        "id": d["id"],
        "url": d.get("url", f"https://strawpoll.com/{d['id']}"),
        "embed_url": d.get("embed_url", f"https://strawpoll.com/embed/{d['id']}"),
        "options": options_meta,
    }


# ── 페이지 조립: 정본 카드 HTML 에 poll 섹션 + 카드별 투표 앵커만 덧붙인다 ──
_POLL_CSS = (
    "<style>"
    ".pollvote{display:block;margin:8px 0 0;text-align:center;background:#c8941f;color:#fff;"
    "font-size:13px;font-weight:700;text-decoration:none;padding:9px 0;border-radius:8px}"
    ".pollvote:hover{background:#a87c12}"
    ".pollsec{max-width:760px;margin:8px auto 40px;padding:0 16px}"
    ".pollsec h2{font-size:19px;margin:18px 0 6px}"
    ".pollsec .lead{font-size:13px;color:#555;margin:0 0 14px}"
    ".polllegend{list-style:none;padding:0;margin:0 0 16px;display:grid;gap:8px}"
    ".polllegend li{background:#fff;border:1px solid #ececf2;border-left:4px solid #c8941f;"
    "border-radius:8px;padding:10px 12px;scroll-margin-top:14px}"
    ".polllegend .on{display:inline-block;min-width:22px;height:22px;line-height:22px;text-align:center;"
    "background:#c8941f;color:#fff;border-radius:50%;font-size:12px;font-weight:800;margin-right:8px}"
    ".polllegend b{font-size:14px}.polllegend .od{font-size:12px;color:#666;margin-top:3px}"
    ".pollframe{width:100%;height:480px;border:0;border-radius:14px;background:#fff;"
    "box-shadow:0 1px 6px rgba(0,0,0,.1)}"
    ".pollnote{font-size:12px;color:#888;margin-top:10px;line-height:1.6}"
    ".pollnote a{color:#1366c2}"
    "</style>"
)


def inject_vote_anchors(cards_html: str, sel: list[dict]) -> str:
    """각 정본 카드의 .links 직전에 '이 식당 투표 ↓' 앵커를 끼워 카드↔옵션 시각 연결.
    정본 카드 마크업은 손대지 않고 앵커 한 줄만 추가한다(카드 순서 = sel 순서)."""
    marker = "<div class=links>"
    parts = cards_html.split(marker)
    if len(parts) != len(sel) + 1:
        # 안전장치: 카드 수와 마커 수가 안 맞으면 카드별 주입을 건너뛴다(페이지는 정상).
        return cards_html
    out = parts[0]
    for i, r in enumerate(sel):
        rid = fcf.row_rid(r)
        anchor = f'<a class=pollvote href="#poll-{rid}">🗳️ 이 식당 투표 ↓</a>'
        out += anchor + marker + parts[i + 1]
    return out


def poll_section(station: str, sel: list[dict], poll: dict) -> str:
    legend = "".join(
        f'<li id="poll-{o["rid"]}"><span class=on>{i}</span><b>{fcf._esc(o["name"])}</b>'
        f'<div class=od>{fcf._esc(o["description"])}</div></li>'
        for i, o in enumerate(poll["options"], 1)
    )
    return (
        _POLL_CSS
        + '<section id="poll" class="pollsec">'
        + "<h2>🗳️ 어디로 갈까요? — 바로 투표</h2>"
        + '<p class="lead">아래에서 1클릭 투표하면 실시간 결과가 바로 보입니다. '
          "각 식당 상세는 위 카드를 참고하세요. (투표·집계·중복방지는 StrawPoll 위젯에 위임)</p>"
        + f'<ol class="polllegend" start=1>{legend}</ol>'
        + f'<iframe class="pollframe" src="{poll["embed_url"]}" '
          'title="식당 투표" loading="lazy" allowtransparency></iframe>'
        + f'<p class="pollnote">poll: <a href="{poll["url"]}" target=_blank>{poll["url"]}</a>'
          " · 투표는 외부 위젯(StrawPoll)에서 처리되며 우리 서버에 저장하지 않습니다.</p>"
        + "</section>"
    )


def render_page(station: str, sel: list[dict], poll: dict, radius_m: int) -> str:
    # 정본 카드 페이지(전체 HTML 문서) — 엔진 그대로.
    cards_html = fcf._render_html(station, sel, radius_m)
    cards_html = inject_vote_anchors(cards_html, sel)
    section = poll_section(station, sel, poll)
    # poll 섹션을 본문 끝(</body>) 직전에 삽입.
    return cards_html.replace("</body></html>", section + "</body></html>", 1)


def main(argv=None):
    ap = argparse.ArgumentParser(description="식당 Poll Phase 1 admin 도구 (CMPA-127)")
    ap.add_argument("--station", required=True, help="역명 (예: 강남역) — 정본 CSV 키")
    ap.add_argument("--rids", required=True, help="식당 rid 4~5개 콤마구분 (정본 CSV 식당ID)")
    ap.add_argument("--radius", type=int, default=800, help="도보 반경 m (카드 헤더 표기용)")
    ap.add_argument("--title", default=None, help="poll 제목 override")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help=f"출력 HTML 경로 (기본 {DEFAULT_OUT})")
    ap.add_argument("--dry-run", action="store_true", help="StrawPoll 생성 없이 렌더만(플레이스홀더 embed)")
    args = ap.parse_args(argv)

    rids = [x.strip() for x in args.rids.split(",") if x.strip()]
    if not (2 <= len(rids) <= 6):
        print(f"[build_poll] ⚠️ rid {len(rids)}개 — 권장 4~5개(plan). 계속 진행합니다.", file=sys.stderr)

    rows = load_station_rows(args.station)
    sel = select_rows(rows, rids)

    if args.dry_run:
        poll = {"id": "DRYRUN", "url": "https://strawpoll.com/DRYRUN",
                "embed_url": "about:blank",
                "options": [{"rid": fcf.row_rid(r), "name": r["식당명"],
                             "description": option_description(r)} for r in sel]}
        print("[build_poll] --dry-run: StrawPoll 생성 생략")
    else:
        poll = create_poll(args.station, sel, args.title)
        print(f"[build_poll] StrawPoll 생성: id={poll['id']} url={poll['url']} embed={poll['embed_url']}")

    page = render_page(args.station, sel, poll, args.radius)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"[build_poll] page 작성: {out}  ({len(sel)} 식당, {len(page)} bytes)")
    print(f"[build_poll] 공유 URL(내부 스테이징): {out}")
    return poll


if __name__ == "__main__":
    main()
