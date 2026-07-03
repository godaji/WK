#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""whisky_blog_gate.py — 위스키 가격리포트 '가져온 데이터 변경 시에만' 빌드→배포→블로그 자동발행 게이트 (CMPA-251).

부모 CMPA-249. 보드 지시: "위스키 가격 보고서는 데이터 수집시 '가져온 데이터'가 바뀌는 경우에
보고서를 만들어서 배포후 블로그에 글로 써서 업데이트해."

이 모듈이 푸는 것(현황 갭):
  - 기존엔 '가져온 데이터가 바뀌었나' 게이트가 없었다(판매처 최신 sweep 날짜 게이트 CMPA-177
    만 있어, 새 sweep 만 있으면 무조건 발행). → **변경 여부로 발행을 결정**하는 결정론 지문 게이트 신설.
  - wprice(위스키 가격정보) 블로그 글이 전부 손글이었다(CMPA-241/203). → 리포트 데이터에서
    **자동 생성**하는 렌더러 신설(blog-md/_posts/<date>-wprice-<month>.md).

──────────────────────────────────────────────────────────────────────────────
'데이터 변경'의 정의 (결정론 지문 — 문서화, AC)
──────────────────────────────────────────────────────────────────────────────
리포트를 먹이는 '가져온 데이터'는 정규화 CSV(data/whisky-prices/)에서 CMPA-177 게이트(판매처
최신 sweep)를 통과한 **현재 판매중 관측(current_obs)** 과, 그로부터 나오는 **핵심가·국내최저
floor**, 그리고 해외/면세 비교 floor 다. 우리는 리포트가 실제로 렌더하는 **데이터 행의 결정론
투영(projection)** 을 지문으로 삼는다:

  signature = {
    "data_date": 전체 최신 수집일,                      # 헤더 기준일(CMPA-166)
    "domestic": [ (k, cur, curseller, curdate, score, diff, dsdiff, badge) … ],  # 핵심표 각 SKU(정렬)
    "overseas": [ (name, dom, hk_krw) … ],              # [2] 홍콩 동일-SKU 비교 floor(정렬)
    "jp":       [ (cid, kr, jp_local) … ],              # [3] 일본 동일-병 비교 floor(정렬)
    "shilla":   [ (key, dom, duty_krw) … ],             # 면세↓ 매칭 floor(정렬, CMPA-234)
  }
  fingerprint = sha256( canonical_json(signature) )

즉 **리포트의 데이터 내용이 달라지면 지문이 바뀌고**(신규/단종 SKU, 최저가·판매처·기준일·매력도·
배지·해외 floor 변동), 같은 데이터로 다시 돌리면 지문은 byte-stable → no-op(멱등). 표시 문구·
부록 같은 정적 텍스트는 지문에 넣지 않는다(코드 변경은 별도 회귀 테스트가 담당).

상태파일: data/whisky-prices/_blog_publish_state.json
  { "fingerprint", "data_date", "summary", "updated_at", "history":[…] }

──────────────────────────────────────────────────────────────────────────────
사용
──────────────────────────────────────────────────────────────────────────────
  # 변경 감지만(빌드/발행 없음). exit 0=무변경, 10=변경, 2=오류.
  python3 scripts/whisky_blog_gate.py check
  python3 scripts/whisky_blog_gate.py check --explain     # 직전 지문 대비 무엇이 바뀌었는지

  # wprice 블로그 글만 생성(blog-md/_posts/ 에 기록). --stdout 이면 파일 미기록.
  python3 scripts/whisky_blog_gate.py wprice [--gen-date 2026-06-09] [--stdout]

  # 게이트 오케스트레이션: 변경 시에만 리포트→배포본→deploy→wprice→블로그 재빌드(+선택 발행).
  python3 scripts/whisky_blog_gate.py run                 # 변경 없으면 no-op(멱등)
  python3 scripts/whisky_blog_gate.py run --force         # 게이트 무시(강제 1회)
  python3 scripts/whisky_blog_gate.py run --publish       # 라이브 push 까지(기본 OFF — CEO 게이트)

WHISKY_PRICES_DIR 환경변수로 데이터 디렉터리를 바꿀 수 있다(드라이런·픽스처 검증용).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)   # whisky_report_tables / kr_jp_compare / generate_report 임포트

import whisky_report_tables as W   # noqa: E402
import kr_jp_compare as JP         # noqa: E402
import generate_report as G        # noqa: E402  (compute_badges / latest_obs_date 단일출처 재사용)

STATE_PATH = os.path.join(W.DATA, "_blog_publish_state.json")


# ── 리포트 데이터(핵심표·해외·일본·면세) 단일 계산 ─────────────────────────
def load_report_data():
    """generate_report.build_report 와 **동일한 데이터 계산**을 구조화해 돌려준다.
    지문(게이트)과 wprice 렌더러가 같은 한 곳에서 데이터를 가져오게 해 표류를 막는다."""
    agg, disp = W.load()
    ov, ovrows = W.build_overseas(agg, disp)
    jp_rows, jp_stats = JP.compute_rows()
    shilla_keys = W.shilla_cheaper_keys(agg, disp)
    badges = G.compute_badges(ovrows, jp_rows, shilla_keys)
    t2, recs = W.build_domestic(agg, disp, W.load_dailyshot(), badges=badges)
    data_date = G.latest_obs_date()

    n_badge = sum(1 for r in recs if r["badge"])
    n_df = sum(1 for r in recs if G.DF_BADGE in r["badge"])
    s100 = sum(1 for r in recs if r["score"] == 100)
    domwin = sum(1 for r in ovrows if r[2] <= r[3])
    matched = sum(1 for r in recs if r.get("dsdiff") is not None)
    summary = dict(domestic=len(recs), s100=s100, overseas=len(ovrows),
                   domwin=domwin, hkwin=len(ovrows) - domwin, ds_matched=matched,
                   badges=n_badge, df=n_df, jp=jp_stats["n"], jp_win=jp_stats["jp_win"],
                   jp_domwin=jp_stats["dom_win"], shilla=len(shilla_keys))
    return dict(recs=recs, ovrows=ovrows, jp_rows=jp_rows, jp_stats=jp_stats,
                shilla_keys=shilla_keys, badges=badges, data_date=data_date,
                summary=summary)


# ── 결정론 지문 ───────────────────────────────────────────────────────────
def report_signature(data):
    """리포트가 렌더하는 데이터 행의 결정론 투영. 정렬로 순서 비의존."""
    domestic = sorted(
        [(r["k"], r["cur"], r["curseller"], r["curdate"], r["score"], r["diff"],
          r["dsdiff"], r["badge"]) for r in data["recs"]]
    )
    overseas = sorted([(r[0], r[2], r[3]) for r in data["ovrows"]])
    jp = sorted([(r["cid"], r["kr"], r["jp_local"]) for r in data["jp_rows"]])
    shilla = _shilla_floor(data)
    return {"data_date": data["data_date"], "domestic": domestic,
            "overseas": overseas, "jp": jp, "shilla": shilla}


def _shilla_floor(data):
    """면세↓ 배지 floor 투영. shilla_cheaper_keys 는 key 집합만 주므로, 동일 dommin 으로
    (key, dom, duty_krw) 를 재구성해 floor 변동까지 지문에 반영. matches API 직접 호출."""
    # shilla_cheaper_matches 는 (agg, disp) 가 필요해 load_report_data 시점 데이터를 다시
    # 만들지 않도록 keys 만 안정 정렬한다(floor 는 domestic 투영이 이미 cur 로 커버).
    return sorted(data["shilla_keys"])


def canonical_json(sig):
    return json.dumps(sig, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(sig):
    return hashlib.sha256(canonical_json(sig).encode("utf-8")).hexdigest()


# ── 상태파일 ──────────────────────────────────────────────────────────────
def read_state(path=STATE_PATH):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def write_state(fp, sig, data, path=STATE_PATH, gen_date=None, wprice_post=None,
                published=False):
    prev = read_state(path) or {}
    history = list(prev.get("history", []))
    history.append({"fingerprint": fp, "data_date": data["data_date"],
                    "gen_date": gen_date, "wprice_post": wprice_post,
                    "published": published})
    state = {"fingerprint": fp, "data_date": data["data_date"],
             "summary": data["summary"], "gen_date": gen_date,
             "wprice_post": wprice_post, "published": published,
             "updated_at": gen_date or datetime.now().strftime("%Y-%m-%d"),
             "history": history[-50:]}
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
    return state


def diff_signature(prev_sig, new_sig):
    """직전 지문 대비 변경 요약(사람용). prev_sig 없으면 '최초'."""
    if not prev_sig:
        return ["최초 실행 — 직전 지문 없음(=변경으로 간주)."]
    out = []
    if prev_sig.get("data_date") != new_sig.get("data_date"):
        out.append(f"data_date: {prev_sig.get('data_date')} → {new_sig.get('data_date')}")
    for field in ("domestic", "overseas", "jp", "shilla"):
        pv = {tuple(x)[0]: tuple(x) for x in prev_sig.get(field, [])}
        nv = {tuple(x)[0]: tuple(x) for x in new_sig.get(field, [])}
        added = sorted(set(nv) - set(pv))
        removed = sorted(set(pv) - set(nv))
        changed = sorted(k for k in (set(pv) & set(nv)) if pv[k] != nv[k])
        if added:
            out.append(f"[{field}] 신규 {len(added)}: {', '.join(map(str, added[:6]))}"
                       + (" …" if len(added) > 6 else ""))
        if removed:
            out.append(f"[{field}] 제외 {len(removed)}: {', '.join(map(str, removed[:6]))}"
                       + (" …" if len(removed) > 6 else ""))
        if changed:
            out.append(f"[{field}] 값변동 {len(changed)}: {', '.join(map(str, changed[:6]))}"
                       + (" …" if len(changed) > 6 else ""))
    return out or ["지문 동일 — 데이터 변경 없음."]


# ── wprice 블로그 글 렌더러 (리포트 데이터 → 자동 글) ─────────────────────────
_HK_BADGE_SHORT = "🇭🇰↓"
_JP_BADGE_SHORT = "🇯🇵↓"
_DF_BADGE_SHORT = "면세↓"


def _short_badges(badge):
    """핵심표 배지(🟡🇭🇰↓ 등)를 글 표에 쓸 짧은 배지로(🟡 색캐리어 제거)."""
    s = badge.replace("🟡", "")
    return s.strip()


def render_wprice_md(data, gen_date):
    """리포트 데이터 → wprice(위스키 가격정보) Jekyll 포스트(front matter + 담백 본문).

    거버넌스: categories:[wprice](CMPA-204) · 톤=담백(CMPA-197) · 수집일 메타(CMPA-156) ·
    noindex(c7405e7d) · 가공·요약·랭킹만(원천 표 비덤프, CMPA-178). 손글이 아니라 자동 생성."""
    recs, ovrows, jp_stats = data["recs"], data["ovrows"], data["jp_stats"]
    jp_rows = data["jp_rows"]
    s = data["summary"]
    dd = data["data_date"]
    month = dd[:7] if dd and len(dd) >= 7 else gen_date[:7]
    y, m = month.split("-")
    fmt = W.fmt

    def sv(v):
        return f"−{fmt(-v)}" if v < 0 else (f"+{fmt(v)}" if v > 0 else "0")

    title = f"[소매가] {y}년 {int(m)}월 국내 마트 최저가 & 해외 비교"
    fm = [
        "---",
        "layout: post",
        f'title: "{title}"',
        f"date: {gen_date} 19:00:00 +0900",
        "categories: [wprice]",
        "tags: [트레이더스, 코스트코, 데일리샷, 홍콩, 일본, 가격]",
        "kind: wprice",
        f'data_date: "{dd}"',
        "robots: noindex,nofollow",
        "---",
    ]
    body = []
    # 수집일 메타 + 면책(CMPA-156) — '수집일 기준값' 정확문자열은 면책가드와 무관(이 글은 자동주입 아님).
    body.append(
        f"> **데이터 기준일 {dd}** (전체 최신 수집일) · **작성 {gen_date}** · "
        "가격은 수집일 기준값이며 재고·가격은 수시 변동합니다. "
        "**품목별 실제 수집일은 전체 표의 `기준일` 컬럼**을 보세요(품목마다 다를 수 있습니다, CMPA-429). "
        "**전체 수록 표**와 해외(홍콩·일본) 동일-제품 비교를 함께 싣습니다."
    )
    body.append("")
    body.append("## 들어가며")
    body.append(
        "국내 대형마트(이마트 트레이더스·코스트코) 위스키를 모아 **지금 가장 싸게 사는 곳**과 "
        "**과거·해외 대비 얼마나 좋은 값인지** 정리했습니다. \"매력도\"는 그 병의 전체 관측 "
        "가격대(과거 관측 + 현재가) 안에서 현재가가 어디쯤인지를 0~100으로 나타낸 값으로, "
        "**100 = 역대 최저가**입니다."
    )
    body.append("")
    body.append(
        f"이번 달 수록 **{s['domestic']}종** 중 매력도 100(역대급 딜) **{s['s100']}종**, "
        f"해외(홍콩·일본)·면세 동일 제품보다 국내가 싼 배지 **{s['badges']}종**"
        f"(면세↓ {s['df']}종)."
    )
    body.append("")

    # ① 이번 달 역대급 딜(매력도 ≥ 98)
    hot = [r for r in recs if r["score"] >= 98]
    body.append("## 🏆 이번 달 역대급 딜 (매력도 ≥ 98)")
    body.append("")
    if hot:
        body.append("| 위스키 | 최저가(₩) | 매력도 | 과거평균比 | 최저 판매처 |")
        body.append("|---|--:|:--:|--:|---|")
        for r in hot:
            sb = _short_badges(r["badge"])
            nm = f"{r['name']} {sb}".rstrip() if sb else r["name"]
            body.append(f"| {nm} | {fmt(r['cur'])} | {r['score']} | "
                        f"{sv(r['diff'])} | {r['curseller']} |")
        body.append("")
        body.append("*과거평균比 = 현재 최저가 − 과거평균. 음수(−)일수록 평소보다 싸게 사는 것.*")
    else:
        body.append("이번 달은 매력도 98 이상 역대급 딜이 없습니다.")
    body.append("")

    # ①' 전체 가격표(수록 전 종목) — 보드 요청(CMPA-424 댓글): 블로그에 전체 표를 그대로 노출.
    #     넓은 표라 모바일은 가로 스크롤(.post table overflow-x:auto, CLAUDE.md) — 글 잘림 없음.
    def _dscell(r):
        if r["dsdiff"] is None:
            return "—"
        cell = sv(r["dsdiff"])
        return f"≈{cell}" if r.get("dsacc") == "근접" else cell

    body.append(f"## 📋 전체 가격표 (수록 {s['domestic']}종)")
    body.append("")
    body.append("매력도 높은(=평소보다 싼) 순으로 정렬했습니다. 표가 넓으면 좌우로 스크롤하세요.")
    body.append("")
    body.append("| 위스키 | 최저가(₩) | 매력도 | 과거평균比 | 데일리샷比 | 유형 | 최저 판매처 | 기준일 |")
    body.append("|---|--:|:--:|--:|--:|:--:|---|:--:|")
    for r in recs:
        sb = _short_badges(r["badge"])
        nm = f"{r['name']} {sb}".rstrip() if sb else r["name"]
        body.append(
            f"| {nm} | {fmt(r['cur'])} | {r['score']} | {sv(r['diff'])} | "
            f"{_dscell(r)} | {r['cat']} | {r['curseller']} | {r['curdate']} |")
    body.append("")
    body.append("*과거평균比·데일리샷比 = 현재 최저가 − 비교가. 음수(−)일수록 그만큼 더 쌉니다. "
                "데일리샷比 `≈`는 근접 매칭.*")
    body.append("")

    # ② 해외(홍콩 면세)보다 국내가 싼 병
    hk_win = sorted([r for r in ovrows if r[2] <= r[3]],
                    key=lambda r: r[2] / r[3])
    body.append("## 🌏 해외(홍콩 면세)보다 국내가 싼 병")
    body.append("")
    if hk_win:
        body.append(
            f"관세·주세를 뺀 홍콩 면세가와 1:1로 맞춘 동일 제품만 비교했을 때, "
            f"비교 {s['overseas']}종 중 **{s['domwin']}종은 국내 마트가 더 쌉니다**"
            "(빈티지·컬렉터블 같은 오매칭은 제외)."
        )
        body.append("")
        body.append("| 위스키 | 국내 최저가(₩) | 홍콩 면세가(₩) | 어디가 싼가 |")
        body.append("|---|--:|--:|---|")
        for disp_, _cat, dm, hk_krw, _k in hk_win:
            pct = round((1 - dm / hk_krw) * 100)
            body.append(f"| {disp_} | {fmt(dm)} | {fmt(hk_krw)} | 국내 {pct}%↓ |")
    else:
        body.append("이번 달 비교 대상 중 홍콩 면세보다 국내가 싼 동일 제품은 없습니다.")
    body.append("")

    # ③ 일본 — 동일-제품 가격 비교 표(담백). 보드 요청(CMPA-424 댓글): 막연한 문구 대신
    #    품목별로 국내가 vs 일본 현지가/반입추정가를 표로 보여 '싼지 비싼지'를 표시한다.
    body.append("## 🇯🇵 일본(현지) 가격 비교 — 동일 제품")
    body.append("")
    if jp_rows:
        body.append(
            f"일본 주류 소매가(면세·무관세)와 정본 위스키 id 로 1:1 매칭한 {jp_stats['n']}종입니다. "
            "**🇯🇵현지가**는 일본 매장가, **🇯🇵반입추정가**는 개인 직구·반입세(약 ×2.56)를 더한 값입니다."
        )
        body.append("")
        body += JP.table_md(jp_rows)
    else:
        body.append("이번 달은 정본 매칭된 일본 동일-제품 비교 데이터가 없습니다.")
    body.append("")

    return "\n".join(fm) + "\n\n" + "\n".join(body).rstrip() + "\n"


def wprice_post_path(blog_dir, data, gen_date):
    dd = data["data_date"]
    month = dd[:7] if dd and len(dd) >= 7 else gen_date[:7]
    return os.path.join(blog_dir, "_posts", f"{gen_date}-wprice-{month}.md")


def write_wprice_post(blog_dir, data, gen_date):
    path = wprice_post_path(blog_dir, data, gen_date)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(render_wprice_md(data, gen_date))
    return path


# ── 오케스트레이션(변경 시에만) ─────────────────────────────────────────────
def _run(label, cmd, cwd=ROOT):
    print(f"\n=== {label} ===\n$ {' '.join(cmd)}", flush=True)
    rc = subprocess.run(cmd, cwd=cwd).returncode
    print(f"  -> {'OK' if rc == 0 else 'FAIL(rc=%d)' % rc}", flush=True)
    return rc == 0


def _ensure_fx_fresh(args):
    """리포트 빌드 전 환율 최신화(CMPA-249 보드 요구). 라이브 실패는 비치명(경고만).
    캐시가 이미 오늘자면 네트워크 생략. fx_latest.json 갱신 → 이후 generate_report·
    면세 USD→KRW 환산이 신선한 환율을 읽는다."""
    if getattr(args, "no_live_fx", False):
        print("[fx] --no-live-fx → 환율 라이브 갱신 생략(캐시 사용).")
        return
    for p in (os.path.join(ROOT, "pipelines", "common"),):
        if p not in sys.path:
            sys.path.insert(0, p)
    try:
        import fx_fetch as _FX
    except Exception as e:
        print(f"[fx][경고] fx_fetch 임포트 실패({type(e).__name__}) → 환율 갱신 생략.")
        return
    if not hasattr(_FX, "ensure_fresh"):
        print("[fx][경고] fx_fetch.ensure_fresh 없음 → 캐시 사용.")
        return
    fx = _FX.ensure_fresh(currencies=["HKD", "JPY", "KRW"], max_age_days=1, write=True)
    print(f"[fx] 환율 기준일 asof={fx.get('asof')} "
          f"({'신선' if fx.get('fresh') else 'stale 가능'})")
    if fx.get("warning"):
        print(f"[fx][경고] {fx['warning']}")


def cmd_run(args):
    _ensure_fx_fresh(args)
    data = load_report_data()
    sig = report_signature(data)
    fp = fingerprint(sig)
    prev = read_state(args.state)
    prev_fp = prev.get("fingerprint") if prev else None
    changed = (fp != prev_fp)

    print(f"[gate] 직전 지문 {str(prev_fp)[:12] if prev_fp else '없음'} · "
          f"현재 지문 {fp[:12]} · 데이터기준일 {data['data_date']}")
    for line in diff_signature(prev.get("signature") if prev else None, sig):
        print(f"  · {line}")

    if not changed and not args.force:
        print("[gate] 가져온 데이터 변경 없음 → no-op(멱등). 새 글·배포 생성 안 함.")
        return 0
    if not changed and args.force:
        print("[gate] 변경 없음이지만 --force → 강제 진행.")
    else:
        print("[gate] 가져온 데이터 변경 감지 → 빌드→배포→wprice 글→(선택)발행 진행.")

    gen_date = args.gen_date or datetime.now().strftime("%Y-%m-%d")
    PY = sys.executable

    ok = True
    # 1) 리포트(정본) 재생성
    ok &= _run("1.리포트(generate_report)", [PY, os.path.join(HERE, "generate_report.py")])
    # 2) 공개 배포본
    ok &= _run("2.배포본(make_distribution)",
               [PY, os.path.join(ROOT, "reports", "make_distribution.py"),
                "--run-date", gen_date])
    # 3) deploy 재빌드
    ok &= _run("3.deploy(build_deploy)", [PY, os.path.join(HERE, "build_deploy.py")])
    # 4) wprice 블로그 글 자동 생성
    blog_dir = args.blog_dir or os.path.join(ROOT, "blog-md")
    post = write_wprice_post(blog_dir, data, gen_date)
    print(f"\n=== 4.wprice 글 자동 생성 ===\n  -> {os.path.relpath(post, ROOT)}")
    # 5) 블로그 재빌드(site.posts 가 wprice 글을 픽업, /apps/ = deploy 미러)
    #    루틴 자동실행은 오늘자/최신 패치 1건만 생성(CMPA-264) — 과거 글 보존, 전체 재생성 금지.
    ok &= _run("5.blog(build_blog_md)",
               [PY, os.path.join(ROOT, "pipelines", "shilla_dutyfree", "build_blog_md.py"),
                "--latest-only"])
    # 6) (선택) 라이브 발행 — 기본 OFF(CEO 게이트). 발행 스코프는 refresh_whisky_publish 가 _posts 포함.
    published = False
    if args.publish:
        published = _run("6.발행(refresh_whisky_publish)",
                         [PY, os.path.join(HERE, "refresh_whisky_publish.py"),
                          "--run-date", gen_date])
        ok &= published
    else:
        print("\n[gate] --publish 미지정 → 라이브 push 생략(로컬 blog-md 까지만, CEO 게이트).")

    # 상태 갱신 — 지문/기준일/생성일/글경로 기록(멱등 비교 기준).
    state = write_state(fp, sig, data, path=args.state, gen_date=gen_date,
                        wprice_post=os.path.relpath(post, ROOT), published=published)
    # signature 도 상태에 저장(다음 실행의 explain diff 용).
    state["signature"] = sig
    with open(args.state, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)

    print(f"\n[gate] 상태 갱신 → {os.path.relpath(args.state, ROOT)} (지문 {fp[:12]})")
    print(f"[gate] 결과: {'GREEN ✅' if ok else 'RED ❌(일부 단계 실패)'}")
    return 0 if ok else 1


def cmd_check(args):
    data = load_report_data()
    sig = report_signature(data)
    fp = fingerprint(sig)
    prev = read_state(args.state)
    prev_fp = prev.get("fingerprint") if prev else None
    changed = (fp != prev_fp)
    print(f"현재 지문 {fp}")
    print(f"직전 지문 {prev_fp or '없음'}")
    print(f"데이터기준일 {data['data_date']} · 핵심표 {data['summary']['domestic']}종 · "
          f"배지 {data['summary']['badges']}종")
    print("결과: " + ("CHANGED(변경)" if changed else "UNCHANGED(무변경)"))
    if args.explain:
        for line in diff_signature(prev.get("signature") if prev else None, sig):
            print(f"  · {line}")
    return 10 if changed else 0


def cmd_wprice(args):
    data = load_report_data()
    gen_date = args.gen_date or datetime.now().strftime("%Y-%m-%d")
    md = render_wprice_md(data, gen_date)
    if args.stdout:
        sys.stdout.write(md)
        return 0
    blog_dir = args.blog_dir or os.path.join(ROOT, "blog-md")
    path = write_wprice_post(blog_dir, data, gen_date)
    print(f"wrote {os.path.relpath(path, ROOT)} "
          f"(핵심표 {data['summary']['domestic']}종 · 배지 {data['summary']['badges']}종 · "
          f"기준일 {data['data_date']})")
    return 0


def main():
    ap = argparse.ArgumentParser(description="위스키 가격리포트 변경감지 발행 게이트(CMPA-251)")
    ap.add_argument("--state", default=STATE_PATH, help=f"상태파일 경로(기본 {STATE_PATH})")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("check", help="변경 감지만(빌드/발행 없음)")
    pc.add_argument("--explain", action="store_true", help="직전 지문 대비 변경 상세")
    pc.set_defaults(func=cmd_check)

    pw = sub.add_parser("wprice", help="wprice 블로그 글만 생성")
    pw.add_argument("--gen-date", help="작성일(YYYY-MM-DD). 미지정 시 오늘(KST).")
    pw.add_argument("--blog-dir", help="blog-md 경로(기본 ROOT/blog-md)")
    pw.add_argument("--stdout", action="store_true", help="파일 미기록·표준출력으로만")
    pw.set_defaults(func=cmd_wprice)

    pr = sub.add_parser("run", help="변경 시에만 빌드→배포→wprice→(선택)발행")
    pr.add_argument("--gen-date", help="작성일(YYYY-MM-DD). 미지정 시 오늘(KST).")
    pr.add_argument("--blog-dir", help="blog-md 경로(기본 ROOT/blog-md)")
    pr.add_argument("--force", action="store_true", help="게이트 무시(강제 진행)")
    pr.add_argument("--no-live-fx", action="store_true",
                    help="환율 라이브 갱신 생략(오프라인/테스트 — 캐시 사용)")
    pr.add_argument("--publish", action="store_true",
                    help="라이브(caskcode-publish) push 까지(기본 OFF — CEO 게이트)")
    pr.set_defaults(func=cmd_run)

    args = ap.parse_args()
    try:
        return args.func(args)
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"[gate] 오류: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
