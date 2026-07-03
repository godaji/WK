#!/usr/bin/env python3
"""신라면세 — 주간 리포트(일요일) 빌더 (CMPA-334).

보드 지시(2026-06-14): 매주 일요일 발행하는 '주간 리포트'는 **지난주 분석 + 기회 회고**.
  ① 지난주 환율 변동 분석 (USD→KRW 추이가 면세가에 미친 영향)
  ② 지난주 할인 종목 분석 (주간 누적: 할인 심화/할증·신규 입고·국내최저 돌파)
  ③ 기회 회고(3-렌즈, CMPA-338): 지난주 스냅샷 floor vs 발행일 데일리샷 라이브 floor 를
     대조해 🔻사라진 기회 / 🆕새 기회 / ✅유지되는 기회 로 분류. ✅버킷이 기존 '현재 추천'을
     대체한다. 갭(스냅샷↔라이브)을 버그로 덮지 않고 콘텐츠로 노출(보드 weekly-retro-redesign:v1).

기존 산출물을 **재사용·집계**만 한다(새 크롤 0 + 라이브 floor 주1회 조회, 결정론):
  - 환율: data/whisky-prices/fx/fx_snapshot.csv (+ fx_latest.json 오늘값)
  - 주간 할인: reports/shilla-dutyfree/가격변동_<D-1>_to_<D>.md (일일 패치) 누적
              → build_blog.parse_patch_md + classify_patch (국내최저가 통합 floor, CMPA-334)
  - 회고: 지난주/이번주 면세_국내최저대비_저렴_<date>.md (CMPA-138 표, 디스크 보존본) 매칭
          + enrich_dailyshot 라이브 floor 대조(제품-구분 토큰 가드, CMPA-177)

출력: reports/shilla-dutyfree/주간리포트_<일요일date>.md
사용: python3 build_weekly_digest.py [--date YYYY-MM-DD] [--days 7]
"""
from __future__ import annotations

import argparse
import csv
import glob
import json
import os
import re
import sys
import datetime

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)

import build_blog as bb  # parse_patch_md / classify_patch 재사용
from build_blog import _fmt_krw

REPORT_DIR = os.path.join(ROOT, "reports", "shilla-dutyfree")
FX_CSV = os.path.join(ROOT, "data", "whisky-prices", "fx", "fx_snapshot.csv")
FX_JSON = os.path.join(ROOT, "data", "whisky-prices", "fx", "fx_latest.json")

# ── 용량 가드 (CMPA-374) ──────────────────────────────────────────────
# 보드 지적(CMPA-373): 주간 다이제스트가 용량이 다른 가격을 병당(per-bottle)으로 비교해
#   가짜 절약이 떴다(시바스리갈 18년 200ml 면세 ₩20,908 ↔ 국내 700ml ₩104,900 → +83,992).
# 규칙: ①위스키명에서 용량(ml)을 파싱 ②<500ml(미니어처) 항목은 글의 모든 섹션에서 제외.
#   파싱 불가는 '풀보틀'로 간주하고 유지한다(BUSHMILLS 처럼 용량 미표기 본편).
MIN_VOLUME_ML = 500


def parse_volume_ml(name):
    """위스키명에서 용량(ml) 추출. 파싱 불가→None(='풀보틀'로 간주, 유지).

    예: 200ml→200, 700ml/700mL→700, 750ml→750, 1000ml→1000, 1L→1000, 1.75L→1750.
    'ml/mL' 을 먼저 보고, 그다음 'L'(리터)를 ×1000 한다('700ml' 의 l 오인 방지)."""
    if not name:
        return None
    m_ml = re.search(r"(\d+(?:\.\d+)?)\s*[mM][lL]\b", name)
    if m_ml:
        return float(m_ml.group(1))
    m_l = re.search(r"(\d+(?:\.\d+)?)\s*[lL]\b", name)
    if m_l:
        return float(m_l.group(1)) * 1000
    return None


def vol_ok(name):
    """용량 가드: <500ml 미니어처면 False(글에서 제외). 미표기(풀보틀)는 True."""
    v = parse_volume_ml(name)
    return v is None or v >= MIN_VOLUME_ML


# ── '이번 주 추천' 신선도 가드용 상태 (CMPA-377) ───────────────────────
# 보드 확정(D안, CMPA-376): 월간 [신라면세] 리포트를 정기발행에서 폐지하고, 주간
#   다이제스트에 '이번 주 추천'을 정식 섹션으로 승격한다. 핵심 리스크 = "매주 같은 TOP
#   반복". 가격은 느리게 움직여 절약 톱이 주마다 거의 안 바뀌므로, 지난주 추천과
#   겹치면 강등·제외하고 **이번 주 변동(신규 하락·floor 갭 확대)** 을 우선 노출한다.
# 데이터 관리 3원칙(CMPA-156): 상태는 스냅샷이 아니라 '날짜 찍힌 누적 기록' → 발행일별
#   추천 종목을 JSON 에 누적 저장하고, 다음 주는 '현재일 이전 최신' 항목을 지난주 추천으로
#   읽는다. 같은 날 재실행은 자기 기록을 읽지 않으므로(< current) 멱등.
RECO_STATE = os.path.join(
    ROOT, "data", "shilla-dutyfree", "_weekly_reco_state.json")
RECO_MAX = 5            # 한 주 추천 최대 종수
GAP_DROP_FRAC = 0.05   # 국내최저 floor 가 지난주 대비 5%+ 빠지면 '갭 확대'(이번 주 변동)


def _load_reco_state():
    try:
        return json.load(open(RECO_STATE, encoding="utf-8"))
    except Exception:
        return {}


def _prev_reco_names(date):
    """현재 발행일 '이전' 최신 회차의 추천 종목 집합(지난주 추천). 없으면 빈 set."""
    st = _load_reco_state()
    prior = [d for d in st if d < date]
    if not prior:
        return set()
    return set(st[max(prior)] or [])


def _save_reco_state(date, names):
    """이번 회차 추천 종목을 발행일 키로 누적 저장(덮어쓰기=같은 날 재실행 멱등)."""
    st = _load_reco_state()
    st[date] = list(names)
    try:
        os.makedirs(os.path.dirname(RECO_STATE), exist_ok=True)
        with open(RECO_STATE, "w", encoding="utf-8") as f:
            json.dump(st, f, ensure_ascii=False, indent=0, sort_keys=True)
    except Exception as e:
        print(f"[추천 상태 저장 생략: {e}]")


# ── 해외비교 심층 블록 4주 1회 로테이션 (CMPA-377) ─────────────────────
# 보드(D안): 월간에만 있던 홍콩/일본/대만 해외비교 깊이를 별도 글 없이 주간으로 흡수한다.
#   매주 넣으면 변동이 거의 없어 식상 → ISO 주차 % 4 로 4주에 1회 회차에만 '심층' 블록을
#   끼운다(결정론적 회차 판정). 나머지 3주는 생략.
INTL_WEEK_RESIDUE = 0   # ISO week % 4 == 0 인 주차에만 해외비교 심층 블록 노출


def intl_week_due(date):
    """해당 발행일(ISO 주차)이 해외비교 심층 회차인지(결정론). week%4==residue."""
    try:
        iso_week = datetime.date.fromisoformat(date).isocalendar()[1]
    except ValueError:
        return False
    return iso_week % 4 == INTL_WEEK_RESIDUE


# ── ① 환율 ────────────────────────────────────────────────────────────
def load_krw_series():
    """{date: krw} — fx_snapshot.csv 의 KRW 행 + fx_latest.json 오늘값."""
    series = {}
    if os.path.exists(FX_CSV):
        for r in csv.DictReader(open(FX_CSV, encoding="utf-8-sig")):
            cur = (r.get("통화") or r.get("currency") or r.get("code") or "").upper()
            if cur != "KRW":
                continue
            d = r.get("날짜") or r.get("date") or r.get("asof")
            # KRW per USD 컬럼명이 버전마다 다름 — 큰 값(>100)을 환율로 채택.
            val = None
            for v in r.values():
                try:
                    f = float(v)
                except (ValueError, TypeError):
                    continue
                if f > 100:
                    val = f
                    break
            if d and val:
                series[d] = val
    try:
        fx = json.load(open(FX_JSON, encoding="utf-8"))
        d = fx.get("asof")
        v = (fx.get("raw_usd") or {}).get("KRW")
        if d and v:
            series[d] = float(v)
    except Exception:
        pass
    return series


def fx_section(start, end):
    s = load_krw_series()
    if not s:
        return ["## 📈 지난주 환율 변동 (USD→KRW)", "",
                "_환율 스냅샷이 없어 이번 주 분석을 건너뜁니다._", ""]
    dates = sorted(s)
    win = [d for d in dates if start <= d <= end] or dates[-2:]
    d0, d1 = win[0], win[-1]
    r0, r1 = s[d0], s[d1]
    delta = r1 - r0
    pct = (delta / r0 * 100) if r0 else 0.0
    if delta < 0:
        impact = ("원화 강세 → **면세가(USD 표기)의 원화 환산액이 그만큼 낮아졌습니다.** "
                  "같은 면세 위스키라도 이번 주 원화 부담이 줄었습니다.")
        arrow = "▼"
    elif delta > 0:
        impact = ("원화 약세 → **면세가의 원화 환산액이 그만큼 올랐습니다.** "
                  "면세 위스키의 원화 체감가가 이번 주 다소 높아졌습니다.")
        arrow = "▲"
    else:
        impact = "환율 변동이 거의 없어 면세가의 원화 환산액도 비슷했습니다."
        arrow = "—"
    out = ["## 📈 지난주 환율 변동 (USD→KRW)", ""]
    out.append(f"- **{d0}** ₩{r0:,.2f} → **{d1}** ₩{r1:,.2f} "
               f"({arrow} {abs(delta):,.2f}원 · {pct:+.2f}%)")
    out.append(f"- {impact}")
    # 주간 추이(있으면 한 줄로)
    if len(win) > 2:
        trail = " → ".join(f"{d[5:]} ₩{s[d]:,.0f}" for d in win)
        out.append(f"- 주간 추이: {trail}")
    out.append("")
    return out


# ── 분석 범위 funnel (CMPA-374 보드 후속) ─────────────────────────────
# 보드: "신라면세점에서 수집하는 위스키 수가 총 몇 개야?" — 글이 면세<국내 '기회'만 보여줘
#   '고려 수량'이 작아 보였다. 신라 수집 전체(수백 종) → ≤50만원 후보 → 국내가 비교가능 →
#   면세가 더 싼 기회 로 좁혀지는 깔때기를 글에 투명히 노출한다. 전부 기존 파일 재집계(네트워크 0).
SHILLA_DAILY_GLOB = os.path.join(
    ROOT, "data", "shilla-dutyfree", "신라면세_위스키_*.csv")


def _shilla_total(date):
    """date 이전(포함) 최신 '신라면세_위스키_<date>.csv' 의 (수집종수, 수집일).

    신라가 실제로 수집한 위스키 전체 종수 — '총 몇 종'의 정답(면세<국내 기회의 모집단)."""
    cands = []
    for p in glob.glob(SHILLA_DAILY_GLOB):
        m = re.search(r"(\d{4}-\d{2}-\d{2})\.csv$", p)
        if m and m.group(1) <= date:
            cands.append((m.group(1), p))
    if not cands:
        return None, None
    d, path = max(cands)
    try:
        n = sum(1 for _ in csv.reader(open(path, encoding="utf-8-sig"))) - 1  # 헤더 제외
    except Exception:
        return None, d
    return (n if n >= 0 else None), d


def _cheaper_funnel(path):
    """면세_국내최저대비_저렴_<date>.md 머리말의 깔때기 숫자 파싱.

    머리말 예: '면세 ≤50만원 후보 542종 중 국내가 확인된 189종 비교',
    '병당 절대가도 국내최저보다 싼 위스키: 75종 (구매가능 59종)'.
    → {cand, compared, cheaper, buyable} (없으면 키 누락). 생성기 텍스트라 안정적."""
    out = {}
    try:
        head = open(path, encoding="utf-8").read(2000)
    except Exception:
        return out
    m = re.search(r"후보\s*([\d,]+)\s*종\s*중\s*국내가\s*확인된\s*([\d,]+)\s*종", head)
    if m:
        out["cand"] = int(m.group(1).replace(",", ""))
        out["compared"] = int(m.group(2).replace(",", ""))
    m = re.search(r"국내최저보다\s*싼\s*위스키[:：]\s*([\d,]+)\s*종"
                  r"(?:[\s*`]*\(구매가능\s*([\d,]+)\s*종\))?", head)
    if m:
        out["cheaper"] = int(m.group(1).replace(",", ""))
        if m.group(2):
            out["buyable"] = int(m.group(2).replace(",", ""))
    return out


def funnel_lines(date, n_retro):
    """글 맨 아래 '이번 분석 범위' 깔때기. 신라 수집 전체→후보→비교가능→기회→회고 대조."""
    total, tdate = _shilla_total(date)
    _cur_date, cur_path = _cheaper_report_on_or_before(date)
    f = _cheaper_funnel(cur_path) if cur_path else {}
    out = ["### 📊 이번 분석 범위 (얼마나 보고 추렸나)", ""]
    if total:
        out.append(f"- 신라면세 **수집 위스키 전체 {total:,}종**"
                   + (f" ({tdate} 수집)" if tdate else ""))
    if f.get("cand"):
        out.append(f"- 그중 면세 ≤50만원 **후보 {f['cand']:,}종**")
    if f.get("compared"):
        out.append(f"- 국내 최저가가 확인돼 **비교 가능 {f['compared']:,}종**")
    if f.get("cheaper"):
        buy = f" (구매가능 {f['buyable']:,}종)" if f.get("buyable") else ""
        out.append(f"- **면세가 국내최저보다 싼 기회 {f['cheaper']:,}종**{buy} "
                   f"— 용량 500ml 미만(미니어처)·면세 한정 제외")
    out.append(f"- 위 3-렌즈 회고는 이 기회군에서 지난주·이번주 **절약 상위 {n_retro}종**을 "
               f"라이브로 다시 대조한 것입니다")
    if not total and not f:
        out.append("_분석 범위 집계 소스가 없어 생략합니다._")
    out.append("")
    return out


# ── ② 주간 할인 종목 ──────────────────────────────────────────────────
def _consecutive_patch_paths(start, end):
    """[start,end] 구간의 **연속 1일** 패치 소스만(중복 구간 제외)."""
    paths = []
    for p in glob.glob(os.path.join(REPORT_DIR, "가격변동_*_to_*.md")):
        m = re.search(r"가격변동_(\d{4}-\d{2}-\d{2})_to_(\d{4}-\d{2}-\d{2})\.md$", p)
        if not m:
            continue
        a, b = m.group(1), m.group(2)
        try:
            da = datetime.date.fromisoformat(a)
            db = datetime.date.fromisoformat(b)
        except ValueError:
            continue
        if (db - da).days != 1:      # 연속 1일 패치만(10_to_12 같은 갭필 제외 → 이중계상 방지)
            continue
        if b < start or b > end:
            continue
        paths.append((b, p))
    return [p for _b, p in sorted(paths)]


def discount_section(start, end):
    paths = _consecutive_patch_paths(start, end)
    if not paths:
        return ["## 🏷️ 지난주 할인 종목 분석", "",
                "_이번 주 일일 가격변동 패치가 없어 분석을 건너뜁니다._", ""], 0
    agg = {}      # name -> {net_pp, krw, floor, save}
    new_items, breaks = {}, []
    for path in paths:
        parsed = bb.parse_patch_md(path)
        bb.classify_patch(parsed)
        recs = (parsed.get("breakthroughs", []) + parsed.get("drops", [])
                + parsed.get("others", []))
        for r in recs:
            nm = r["name"]
            if not vol_ok(nm):      # CMPA-374: <500ml 미니어처 제외
                continue
            a = agg.setdefault(nm, {"net": 0.0, "krw": None, "floor": None, "url": None})
            if r.get("d_rate") is not None:
                a["net"] += r["d_rate"]
            if r.get("krw") is not None:
                a["krw"] = r["krw"]
            if r.get("floor") is not None:
                a["floor"] = r["floor"]
                a["url"] = r.get("floor_url")
        for r in parsed.get("breakthroughs", []):
            if vol_ok(r["name"]):      # CMPA-374: <500ml 제외
                breaks.append(r["name"])
        for r in parsed["sections"].get("new", []):
            nm = bb._name_key(r)
            if nm and vol_ok(nm):      # CMPA-374: <500ml 제외
                new_items[nm] = r.get("현재 KRW", "")

    deepen = sorted(((nm, a) for nm, a in agg.items() if a["net"] >= 1.0),
                    key=lambda x: -x[1]["net"])
    raise_ = sorted(((nm, a) for nm, a in agg.items() if a["net"] <= -1.0),
                    key=lambda x: x[1]["net"])
    out = ["## 🏷️ 지난주 할인 종목 분석", "",
           f"_지난주({start}~{end}) 일일 패치 {len(paths)}건 누적 — 할인율 변동(%p) 합산._", ""]
    bset = sorted(set(breaks))
    if bset:
        out.append(f"- 🏆 **국내최저가 돌파**(면세가 < 국내최저): 주간 {len(bset)}종 — "
                   + ", ".join(bset[:8]) + ("…" if len(bset) > 8 else ""))
    if deepen:
        out.append("")
        out.append("**🔥 할인 심화 (면세가가 더 싸짐) — 주간 할인율↑ 톱**")
        out.append("")
        out.append("| 위스키 | 상세 |")
        out.append("|---|---|")
        for nm, a in deepen[:8]:
            if a["floor"]:
                _t = _fmt_krw(a["floor"])
                # 정직한 라벨(CMPA-339): 숫자=수집일 스냅샷, 링크=라이브 현재가 확인(분리).
                fl = (f' · 국내최저 {_t} · [데일리샷 현재가 ↗]({a["url"]})' if a.get("url")
                      else f' · 국내최저 {_t}')
            else:
                fl = ""
            kw = f'면세 **{_fmt_krw(a["krw"])}**' if a["krw"] else "면세 —"
            out.append(f"| {nm} | {kw}{fl}<br>주간 할인율 **+{a['net']:.0f}%p** |")
    if raise_:
        out.append("")
        out.append("**🔺 할증 (할인 축소·가격 상승) — 주간 할인율↓**")
        out.append("")
        out.append("| 위스키 | 상세 |")
        out.append("|---|---|")
        for nm, a in raise_[:5]:
            kw = f'면세 {_fmt_krw(a["krw"])}' if a["krw"] else "면세 —"
            out.append(f"| {nm} | {kw}<br>주간 할인율 **{a['net']:.0f}%p** |")
    if new_items:
        out.append("")
        names = list(new_items)
        out.append(f"- 🆕 **신규 입고** 주간 {len(names)}종: "
                   + ", ".join(names[:8]) + ("…" if len(names) > 8 else ""))
    out.append("")
    return out, len(bset)


# ── ③ 기회 회고 (3-렌즈) — 지난주 스냅샷 vs 발행일 라이브 (CMPA-338) ──────
# (구 '현재 추천' 단일 표 reco_section 은 CMPA-338 에서 ✅'유지되는 기회' 버킷으로 흡수·대체됨)
def _to_int(s):
    try:
        return int(re.sub(r"[^\d]", "", str(s)))
    except (ValueError, TypeError):
        return None


def _parse_cheaper_table(path):
    """면세_국내최저대비_저렴_<date>.md 의 ① 표 → {name: {duty,floor,save,buy,src,
       duty100,floor100,save100}}.

    컬럼: # | 위스키 | 면세(₩) | 국내최저(₩) | 면세₩/100ml | 국내₩/100ml |
          절감(병당) | 절감(100ml) | 국내출처 | 구매.
    CMPA-374: <500ml(미니어처) 행은 제외하고, 용량당(100ml) 절약(국내100−면세100)도 파싱한다
    (병당 비교가 용량 불일치일 수 있어 용량당 절약을 함께 노출하기 위함)."""
    out = {}
    in_tbl = False
    for ln in open(path, encoding="utf-8"):
        if ln.startswith("| # | 위스키"):
            in_tbl = True
            continue
        if in_tbl:
            if not ln.lstrip().startswith("|"):
                if out:
                    break
                continue
            cells = [c.strip() for c in ln.strip().strip("|").split("|")]
            if len(cells) < 10 or not cells[0].lstrip("-").isdigit():
                continue
            name = cells[1]
            if not vol_ok(name):      # CMPA-374: <500ml 미니어처 제외
                continue
            duty, floor, save = _to_int(cells[2]), _to_int(cells[3]), _to_int(cells[6])
            duty100, floor100 = _to_int(cells[4]), _to_int(cells[5])
            if not (duty and floor):
                continue
            save100 = (floor100 - duty100) if (duty100 and floor100) else None
            out[name] = {"duty": duty, "floor": floor, "save": save or 0,
                         "buy": cells[9], "src": cells[8],
                         "duty100": duty100, "floor100": floor100, "save100": save100}
    return out


def _cheaper_report_on_or_before(date):
    cands = []
    for p in glob.glob(os.path.join(REPORT_DIR, "면세_국내최저대비_저렴_*.md")):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(p))
        if m and m.group(1) <= date:
            cands.append((m.group(1), p))
    return max(cands) if cands else (None, None)


def _cheaper_report_before(date):
    cands = []
    for p in glob.glob(os.path.join(REPORT_DIR, "면세_국내최저대비_저렴_*.md")):
        m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(p))
        if m and m.group(1) < date:
            cands.append((m.group(1), p))
    return max(cands) if cands else (None, None)


def _live_floor(names, enabled=True):
    """이름 → 데일리샷 라이브 {name: {price, url, ds_name}} (enrich_dailyshot 재사용).
    주1회라 부하 미미. 실패는 전부 흡수(빈 dict). CMPA-338: '덮어쓰기'가 아니라 '대조'용.

    CMPA-343 보드(CMPA-338 근본해결): '지금 floor' 는 검색 API 의 '대표 셀러가'(ds_price)가
    아니라 사용자가 링크로 들어가는 제품 페이지(/m/item/{tpid})의 **전국 최저 셀러가**
    (page_price)여야 한다. 둘은 크게 어긋난다(예: 글렌드로낙16 검색 372,000 vs 페이지
    329,000/피보, 발베니19 위크오브피트 620,000 vs 395,000/더블랙). with_page=True 로 페이지가를
    받아 우선 사용하고, 페이지 파싱 실패 시 검색가로 폴백한다."""
    if not enabled or not names:
        return {}
    try:
        import enrich_dailyshot
        res = enrich_dailyshot.build_lookup(list(names), with_page=True)
        out = {}
        for nm, m in res.items():
            if not m:
                continue
            price = m.get("page_price") or m.get("ds_price")
            if price:
                out[nm] = {"price": price, "url": m.get("ds_url"),
                           "ds_name": m.get("ds_name")}
        return out
    except Exception as e:
        print(f"[회고 라이브 floor 생략: {e}]")
        return {}


# CMPA-177: 숙성년수(enrich가 처리)·CS·피티드·캐스크종류는 '제품을 가르는 토큰' — 한쪽에만
# 있으면 다른 SKU. enrich_dailyshot 의 매칭은 브랜드+숙성만 봐서 '로얄살루트 21년 Peated
# Blend' 를 '로얄살루트 21년 블렌디드 그레인'(195k)에 오매칭한다. 회고가 이 더 싼 오매칭으로
# '딜 소멸'을 단정하지 않도록, 핵심 토큰 비대칭이면 라이브 매칭을 신뢰하지 않는다(스냅샷 폴백).
_MATCH_GUARD_TOKENS = [
    ("피티드", "peated"),
    ("캐스크스트랭스", "caskstrength", "cask strength"),
    ("블렌디드그레인", "blended grain"),
]


def _live_match_trusted(snap_name, ds_name):
    """라이브 매칭이 제품-구분 토큰까지 일치하는지(신뢰 가능) 여부."""
    if not ds_name:
        return False
    a = snap_name.lower().replace(" ", "")
    b = ds_name.lower().replace(" ", "")
    for keys in _MATCH_GUARD_TOKENS:
        ka = [k.replace(" ", "") for k in keys]
        if any(k in a for k in ka) != any(k in b for k in ka):
            return False
    return True


def retro_section(date, days=7, enrich=True):
    """3-렌즈 기회 회고: 지난주 스냅샷 floor vs 발행일 라이브 floor 대조 (CMPA-338).

    🔻 사라진 기회 / 🆕 새 기회 / ✅ 유지되는 기회 로 분류. 숫자=수집일 스냅샷,
    [데일리샷 현재가 ↗]=실시간(정직 라벨, CMPA-339). 데일리샷 API 실패는 비치명."""
    cur_date, cur_path = _cheaper_report_on_or_before(date)
    if not cur_path:
        return ["## 🔁 지난주 기회, 지금은? (3-렌즈 회고)", "",
                "_floor 리포트가 없어 회고를 건너뜁니다._", ""], 0, {}
    prev_date, prev_path = _cheaper_report_before(cur_date)
    if not prev_path:
        return ["## 🔁 지난주 기회, 지금은? (3-렌즈 회고)", "",
                "_비교할 지난주 스냅샷이 없어 회고를 건너뜁니다._", ""], 0, {}
    cur, prev = _parse_cheaper_table(cur_path), _parse_cheaper_table(prev_path)

    # 3-렌즈 라이브 대조 universe = 절약 톱(prev14+cur16). 라이브 floor 조회(데일리샷 제품
    # 페이지)는 종당 1요청이라 전수(수백 종) 조회는 메모리·시간 폭증(OOM) → 톱으로 캡한다.
    # '고려한 위스키 수량'(전체 분석 범위)은 라이브 조회와 분리해 funnel_lines() 가 파일에서
    # 싸게 집계한다(신라 수집 전체 → 후보 → 비교가능 → 기회). 보드 후속(CMPA-374): 표시 종수
    # 자체보다 '신라 수집 총 몇 종'을 투명히 보여 달라는 요구를 funnel 로 충족.
    def top(d, n):
        return [nm for nm, _ in sorted(d.items(), key=lambda kv: -kv[1]["save"])[:n]]
    universe = list(dict.fromkeys(top(prev, 14) + top(cur, 16)))
    live = _live_floor(universe, enabled=enrich)

    pm, cm = prev_date[5:], cur_date[5:]   # MM-DD
    expired, fresh, still = [], [], []
    for nm in universe:
        p, c = prev.get(nm), cur.get(nm)
        base = c or p
        duty = base["duty"]
        buy = base["buy"]
        lm = live.get(nm) or {}
        floor_live = lm.get("price")
        url = lm.get("url")
        # 라이브 floor 는 제품-구분 토큰까지 일치할 때만 신뢰(오매칭으로 허위 '딜 소멸' 방지).
        trusted = floor_live is not None and _live_match_trusted(nm, lm.get("ds_name"))
        snap_floor = c["floor"] if c else None
        floor_now = floor_live if trusted else snap_floor
        floor_prev = p["floor"] if p else None
        in_last = p is not None
        # 'now_deal' 판정: 신뢰 라이브가 있으면 그것으로 권위 판정(소멸 단정 가능),
        # 없으면 이번주 스냅샷 등재 여부로만 판단(소멸은 단정하지 않음).
        if trusted:
            now_deal = duty < floor_live
        elif c is not None:
            now_deal = True
        else:
            continue   # 신뢰 라이브도 없고 이번주 스냅샷에도 없음 → 분류 보류(추정 금지)
        save_now = (floor_now - duty) if (floor_now and now_deal) else None
        # CMPA-374: 용량당(100ml) 절약 — 소스 표의 면세/100ml·국내/100ml(이번주 스냅샷)에서.
        save100 = (c or p).get("save100") if (c or p) else None
        row = {"name": nm, "duty": duty, "buy": buy, "url": url if trusted else None,
               "live_real": trusted, "floor_now": floor_now,
               "floor_prev": floor_prev, "save_now": save_now,
               "save_prev": p["save"] if p else 0, "save100": save100}
        if in_last and now_deal:
            still.append(row)
        elif in_last and not now_deal:
            expired.append(row)   # 도달 조건: trusted 라이브가 flip 을 보여줄 때만
        elif (not in_last) and now_deal:
            fresh.append(row)

    expired.sort(key=lambda r: -r["save_prev"])
    fresh.sort(key=lambda r: -(r["save_now"] or 0))
    still.sort(key=lambda r: -(r["save_now"] or 0))

    def nowtag(r):
        if r["live_real"]:
            return f' · [데일리샷 현재가 ↗]({r["url"]})' if r["url"] else " (라이브)"
        return f" ({cm} 기준 스냅샷)"

    def badge(r):
        return " ⭐구매가능" if (r["buy"] or "").upper() == "Y" else ""

    def per100(r):
        # CMPA-374: 용량당(100ml) 절약을 병당값 옆에 함께 노출(용량 불일치 보정 신호).
        return f' · 100ml당 ₩{r["save100"]:,} 절약' if r.get("save100") else ""

    out = ["## 🔁 지난주 기회, 지금은? (3-렌즈 회고)", "",
           f"_지난주({prev_date}) 스냅샷과 발행일({cur_date}) **데일리샷 라이브**를 대조했습니다. "
           "지난주 '면세가 더 쌌던' 기회가 지금도 살아있는지(✅)·사라졌는지(🔻)·새로 생겼는지(🆕)를 "
           "보여줍니다. **국내최저 숫자는 수집일 스냅샷**, **[데일리샷 현재가 ↗]는 실시간 페이지**라 "
           "시세가 움직이면 다를 수 있습니다. **비교는 용량당(100ml) 기준**으로 보정한 값을 함께 "
           "표기하며, **용량 200ml·미니어처(500ml 미만) 항목은 제외**했습니다._", ""]

    out += ["### 🔻 지금은 사라진 기회", ""]
    if expired:
        out += ["| 위스키 | 상세 |", "|---|---|"]
        for r in expired[:6]:
            fp = f'₩{r["floor_prev"]:,}' if r["floor_prev"] else "—"
            fn = f'₩{r["floor_now"]:,}' if r["floor_now"] else "데일리샷 매물 미확인"
            out.append(
                f'| {r["name"]} | 면세 ₩{r["duty"]:,}<br>'
                f'지난주({pm}) 국내최저 {fp} → 면세가 더 쌌던 딜<br>'
                f'지금 국내최저 {fn}{nowtag(r)} → 면세 메리트 소멸 |')
    else:
        out.append("_지난주 딜 중 사라진 종목은 없습니다._")
    out.append("")

    out += ["### 🆕 지금 새로 생긴 기회", ""]
    if fresh:
        out += ["| 위스키 | 상세 |", "|---|---|"]
        for r in fresh[:6]:
            sv = f'₩{r["save_now"]:,} 이득' if r["save_now"] else "면세가 우위"
            out.append(
                f'| {r["name"]}{badge(r)} | 면세 **₩{r["duty"]:,}**<br>'
                f'지난주: 딜 아님(또는 미등재)<br>'
                f'지금 국내최저 ₩{r["floor_now"]:,}{nowtag(r)} → **{sv}**{per100(r)} 🆕 |')
    else:
        out.append("_이번 주 새로 생긴 면세 우위 종목은 없습니다._")
    out.append("")

    out += ["### ✅ 유지되는 기회 (지금 사도 이득)", ""]
    if still:
        out += ["| 위스키 | 상세 |", "|---|---|"]
        for r in still[:8]:
            fp = f'₩{r["floor_prev"]:,}' if r["floor_prev"] else "—"
            sv = f'₩{r["save_now"]:,} 절약' if r["save_now"] else "면세가 우위"
            out.append(
                f'| {r["name"]}{badge(r)} | 면세 **₩{r["duty"]:,}**<br>'
                f'지난주({pm}) 국내최저 {fp} → 지금 ₩{r["floor_now"]:,}{nowtag(r)}<br>'
                f'**{sv}**{per100(r)} — 지금 사도 이득 ✅ |')
    else:
        out.append("_지금 추천할 유지 기회가 없습니다._")
    out.append("")
    # CMPA-374 R4: '고려한 위스키 수량' N = 3-렌즈 회고가 대조한 floor 유니버스 종수 = universe
    #   (지난주·이번주 면세<국내 floor 리포트의 **전체 합집합**, <500ml 제외 후). 글 맨 아래에 노출.
    # CMPA-377: '이번 주 추천'(신선도 가드)이 fresh/still 버킷을 재사용하도록 함께 반환
    #   (라이브 floor 재조회 없이 동일 데이터로 추천을 뽑기 위함).
    buckets = {"fresh": fresh, "still": still, "expired": expired,
               "cur_date": cur_date, "prev_date": prev_date}
    return out, len(universe), buckets


# ── '이번 주 추천' 정식 섹션 (CMPA-377, 신선도 가드) ────────────────────
def weekly_reco_section(date, buckets):
    """주간 다이제스트의 헤드라인 = '이번 주 추천' (델타·로테이션 + 신선도 가드).

    재료: retro_section 의 fresh(이번 주 새 면세 우위)·still(유지 기회) 버킷(라이브 floor
      이미 반영). 추천은 **이번 주 변동**을 우선한다 — ① 🆕 신규 하락(딜 신규 진입),
      ② floor 갭 확대(국내최저가 지난주 대비 5%+ 하락 → 면세 메리트 강화).
    신선도 가드(CMPA-376 D안 핵심): 지난주(`_prev_reco_names`)와 겹치고 이번 주 변동이
      없는 종목은 강등·제외한다. '변동 있는' 후보가 부족하면 추천 수를 줄이고, 아예 없으면
      '이번 주는 큰 변동 없음'을 담백하게 표기(과장 금지·CMPA-197). 그래도 한두 종은
      '꾸준한 기회'로 — 단 지난주 추천과 다른 종목으로 로테이션해 반복을 피한다.
    반환: (lines, reco_names) — reco_names 는 상태파일에 누적 저장해 다음 주 가드 기준.
    """
    fresh = buckets.get("fresh", []) or []
    still = buckets.get("still", []) or []
    if not fresh and not still:
        return (["## 🌟 이번 주 추천", "",
                 "_이번 주는 비교할 floor 데이터가 부족해 추천을 건너뜁니다._", ""], [])
    prev_reco = _prev_reco_names(date)

    def gap_expanded(r):
        fp, fn = r.get("floor_prev"), r.get("floor_now")
        return bool(fp and fn and fn < fp * (1 - GAP_DROP_FRAC))

    def buyable(r):
        # CMPA-377 보드 후속: '추천'은 독자가 **지금 실제로 살 수 있어야** 의미가 있다.
        #   구매가능=Y = 신라면세 라이브 allowProductPurchase & 재고>0(품절·미판매 제외).
        #   회고/분석 섹션은 전체를 ⭐배지로 구분해 보여주지만, 추천은 구매가능만 싣는다.
        return (r.get("buy") or "").upper() == "Y"

    # 후보에 '이번 주 변동' 태그를 단다(🆕 신규 / 📉 갭확대). still 중 갭 확대만 변동.
    # 추천은 **구매가능(Y)만** — 못 사는 종목을 추천하면 독자 행동으로 이어지지 않음.
    changed = []
    for r in fresh:
        if buyable(r) and (r.get("save_now") or 0) > 0:
            changed.append({**r, "why": "🆕 이번 주 신규", "_chg": True})
    for r in still:
        if buyable(r) and gap_expanded(r) and (r.get("save_now") or 0) > 0:
            drop = r["floor_prev"] - r["floor_now"]
            changed.append({**r, "why": f"📉 국내최저 ₩{drop:,}↓ (갭 확대)", "_chg": True})
    # 변동 후보 정렬: 절약액 큰 순. 지난주 추천과 겹쳐도 '변동'이면 유지(새 사유로 노출).
    changed.sort(key=lambda r: -(r.get("save_now") or 0))

    picks, seen = [], set()
    for r in changed:
        if r["name"] in seen:
            continue
        seen.add(r["name"])
        picks.append(r)
        if len(picks) >= RECO_MAX:
            break

    no_change_note = False
    # 변동 후보가 적으면 '꾸준한 기회'로 보충 — 단 지난주 추천과 겹치지 않게 로테이션.
    if len(picks) < RECO_MAX:
        ever = sorted((r for r in still if buyable(r) and (r.get("save_now") or 0) > 0),
                      key=lambda r: -(r.get("save_now") or 0))
        for r in ever:
            if r["name"] in seen or r["name"] in prev_reco:
                continue   # 지난주 추천 반복 금지(신선도 가드)
            seen.add(r["name"])
            picks.append({**r, "why": "꾸준한 기회", "_chg": False})
            if len(picks) >= RECO_MAX:
                break
    if not any(p.get("_chg") for p in picks):
        no_change_note = True   # 이번 주 변동 추천 0 → 담백하게 표기

    out = ["## 🌟 이번 주 추천", ""]
    cur_date = buckets.get("cur_date") or date
    if no_change_note:
        out.append(f"_이번 주는 지난주 대비 **큰 변동이 없습니다.** 아래는 지금도 면세가가 "
                   f"국내최저보다 유리한 '꾸준한 기회'이며, 지난주 추천과 겹치지 않게 "
                   f"골랐습니다. **신라면세 온라인에서 지금 구매 가능한(재고 있는) 종목만** "
                   f"실었습니다. 가격은 {cur_date} 수집 기준입니다._")
    else:
        out.append(f"_이번 주 **새로 떴거나 더 싸진** 면세 기회를 우선 골랐습니다 "
                   f"(🆕 신규 하락·📉 국내최저 갭 확대). 매주 같은 종목이 반복되지 않도록 "
                   f"지난주 추천과 변동을 함께 봅니다. **신라면세 온라인에서 지금 구매 "
                   f"가능한(재고 있는) 종목만** 실었습니다. 가격은 {cur_date} 수집 기준이며, "
                   f"면세가는 출국 시에만 구매 가능합니다._")
    out.append("")
    if not picks:
        out += ["_이번 주는 새로 추천할(지금 구매 가능한) 면세 우위 종목이 없습니다._", ""]
        return out, []
    out += ["| 위스키 | 상세 |", "|---|---|"]
    for r in picks:
        # 추천은 구매가능(Y)만 싣으므로 행마다 ⭐배지를 반복하지 않고 리드에서 한 번 명시.
        fn = f'₩{r["floor_now"]:,}' if r.get("floor_now") else "—"
        sv = f'₩{r["save_now"]:,} 절약' if r.get("save_now") else "면세가 우위"
        per100 = (f' · 100ml당 ₩{r["save100"]:,} 절약'
                  if r.get("save100") else "")
        nowtag = (f' · [데일리샷 현재가 ↗]({r["url"]})'
                  if r.get("live_real") and r.get("url") else "")
        out.append(
            f'| {r["name"]} | {r["why"]}<br>'
            f'면세 **₩{r["duty"]:,}** · 국내최저 {fn}{nowtag}<br>'
            f'**{sv}**{per100} |')
    out.append("")
    return out, [p["name"] for p in picks]


# ── 해외비교 심층 블록 (4주 1회 로테이션, CMPA-377) ─────────────────────
INTL_GLOB = os.path.join(
    ROOT, "data", "shilla-dutyfree", "신라면세_피트위스키_해외비교_*_v2.csv")


def _latest_intl_csv(date):
    """발행일 이전(포함) 최신 해외비교 v2 CSV (date, path). 없으면 (None,None)."""
    cands = []
    for p in glob.glob(INTL_GLOB):
        m = re.search(r"(\d{4}-\d{2}-\d{2})_v2\.csv$", p)
        if m and m.group(1) <= date:
            cands.append((m.group(1), p))
    return max(cands) if cands else (None, None)


def international_section(date):
    """해외 현지가(HK/JP/TW) vs 신라면세 비교 — 4주 1회 회차에만 노출 (CMPA-377).

    회차가 아니면 빈 리스트(섹션 생략). compare_international.py 산출 v2 CSV 재사용
    (새 크롤 0). 코어 증류소·동일 숙성 신뢰매칭만(매칭지역수>0). 모바일 2컬럼."""
    if not intl_week_due(date):
        return []
    csv_date, path = _latest_intl_csv(date)
    if not path:
        return []
    rows = []
    try:
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            try:
                nreg = int(r.get("매칭지역수") or 0)
            except ValueError:
                nreg = 0
            if nreg <= 0:
                continue
            if not vol_ok(r.get("위스키명", "")):   # <500ml 제외
                continue
            try:
                attr = float(r.get("가격매력도_vs중앙_%") or "")
            except ValueError:
                attr = None
            rows.append({"name": (r.get("위스키명", "") or "").strip(), "buy": r.get("구매가능", ""),
                         "attr": attr, "hk": r.get("HK_USD", ""), "jp": r.get("JP_USD", ""),
                         "tw": r.get("TW_USD", ""), "shilla": r.get("신라700ml환산_USD", ""),
                         "conf": r.get("신뢰도", "")})
    except Exception as e:
        print(f"[해외비교 심층 생략: {e}]")
        return []
    if not rows:
        return []
    # 신라가 더 싼(매력도 양수) 순 → 해외가 더 싼 순. None 은 맨 뒤.
    rows.sort(key=lambda r: -(r["attr"] if r["attr"] is not None else -999))
    out = ["## 🌏 해외 현지가 비교 (심층 · 4주 1회)", "",
           f"_월 1회 회차에 싣는 심층 블록입니다. 신라면세(USD)를 홍콩·일본·대만 **현지 "
           f"소매가**(세금 포함, 면세 아님)와 700ml 환산·동일 숙성으로 비교했습니다. "
           f"양수(+)면 신라면세가 더 쌉니다. 코어 증류소·동일 숙성 신뢰매칭만 실었습니다 "
           f"({csv_date} 기준)._", "",
           "| 위스키 | 상세 |", "|---|---|"]
    def usd(v):
        return f"${v}" if v not in ("", None) else "—"
    for r in rows[:8]:
        badge = " ⭐구매가능" if (r["buy"] or "").upper() == "Y" else ""
        if r["attr"] is None:
            verdict = "비교가 산출 안 됨"
        elif r["attr"] > 0:
            verdict = f"신라면세가 **{r['attr']:.0f}% 더 쌈**"
        else:
            verdict = f"해외가 {abs(r['attr']):.0f}% 더 쌈"
        regions = " · ".join(
            f"{lbl} {usd(r[k])}" for lbl, k in (("HK", "hk"), ("JP", "jp"), ("TW", "tw"))
            if r[k] not in ("", None))
        out.append(
            f'| {r["name"]}{badge} | 신라 {usd(r["shilla"])}/700ml — {verdict}<br>'
            f'{regions} (현지 소매가)<br>'
            f'신뢰도 {r["conf"] or "—"} |')
    out.append("")
    return out


# ── 조립 ──────────────────────────────────────────────────────────────
def build(date, days=7):
    end = date
    start = (datetime.date.fromisoformat(date)
             - datetime.timedelta(days=days)).isoformat()
    disc, nbreak = discount_section(start, end)
    L = [f"# [신라면세] 주간 리포트 ({start} ~ {end})", "",
         "> 매주 일요일 발행하는 **지난주 분석 + 기회 회고** 다이제스트입니다. "
         "지난주 면세 기회가 지금도 살아있는지(✅)·사라졌는지(🔻)·새로 생겼는지(🆕)를 대조합니다. "
         "가격은 각 스냅샷 **수집일 기준값**이며, 면세가는 출국 시에만 구매 가능합니다 "
         "(주류 면세한도 2병·2L·$400). **가격 비교는 용량당(100ml) 기준**으로 보정하고, "
         "**용량 500ml 미만(미니어처) 항목은 제외**합니다.", ""]
    # CMPA-377: 회고를 먼저 계산해 fresh/still 버킷을 얻고(라이브 floor 1회 조회),
    #   그 데이터로 '이번 주 추천'(헤드라인·신선도 가드)을 뽑아 글 맨 위에 싣는다.
    retro, n_universe, buckets = retro_section(date, days)
    reco, reco_names = weekly_reco_section(date, buckets)
    _save_reco_state(date, reco_names)   # 다음 주 신선도 가드 기준(누적 저장)
    L += reco
    L += fx_section(start, end)
    L += disc
    # CMPA-338: '현재 추천' 단일 표 → 3-렌즈 기회 회고(지난주 스냅샷 vs 발행일 라이브).
    # ✅ '유지되는 기회' 버킷이 기존 현재 추천 표의 역할을 한다.
    L += retro
    # CMPA-377: 해외비교 심층 블록 — 4주 1회 회차에만(ISO week%4). 나머지 주는 생략.
    L += international_section(date)
    # CMPA-374 R4 + 보드 후속: 글 맨 아래에 '이번 분석 범위' 깔때기(신라 수집 전체→후보→
    # 비교가능→면세<국내 기회→회고 대조 종수). '고려 수량'이 작아 보인다는 지적을, 면세<국내
    # 기회는 신라 수집 전체(수백 종)의 자연스러운 소수 부분집합임을 투명히 보여 해소.
    L += funnel_lines(date, n_universe)
    L += ["---",
          f"_국내최저가 = 데일리샷·트레이더스·코스트코 국내 소매가 중 최저(면세·해외 제외). "
          f"생성: build_weekly_digest.py (CMPA-334·CMPA-374) · {start} ~ {end}_", ""]
    return "\n".join(L)


def publish_blog(date, md, days=7, out_dir=None):
    """주간 리포트 md → Jekyll 블로그 포스트(front matter + 본문). CMPA-334 보드 승인.

    카테고리=price(면세 가성비 스트림·렌더 버킷), kind=weekly. H1 은 front matter title 로
    올리고 본문에서 제거. blog-md/_posts/<date>-weekly-digest.md 로 발행(타 글 보존)."""
    import build_blog_md as bm
    import brand
    start = (datetime.date.fromisoformat(date)
             - datetime.timedelta(days=days)).isoformat()
    lines = md.splitlines()
    body = ("\n".join(lines[1:]).lstrip("\n")
            if lines and lines[0].startswith("# ") else md)
    title = f"[신라면세] 주간 리포트 ({start} ~ {date})"
    fm = bm.front_matter({
        "layout": "post",
        "title": title,
        "date": f"{date} 08:30:00 +0900",
        "categories": ["price"],
        "kind": "weekly",
        "weekly_start": start,
        "weekly_end": date,
        "description": (f"신라면세 주간 리포트 — 지난주 환율·할인 종목 + 기회 회고"
                        f"(사라진/새/유지되는 면세 기회) ({start}~{date}). {brand.NAME_EN}"),
        "robots": "noindex,nofollow",
    })
    out_dir = out_dir or os.path.join(ROOT, "blog-md", "_posts")
    path = os.path.join(out_dir, f"{date}-weekly-digest.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(fm + "\n\n" + body.rstrip() + "\n")
    return path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=os.environ.get("SHILLA_DATE"),
                    help="주간 종료일(일요일). 기본=오늘(KST)")
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--out")
    ap.add_argument("--publish-blog", action="store_true",
                    help="blog-md/_posts/ 에 주간 리포트 블로그 포스트도 발행")
    args = ap.parse_args()
    date = args.date or (datetime.datetime.utcnow()
                         + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")
    md = build(date, args.days)
    out = args.out or os.path.join(REPORT_DIR, f"주간리포트_{date}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write(md + "\n")
    print(f"-> {out}")
    print(f"   (구간 {args.days}일 · 종료 {date})")
    if args.publish_blog:
        post = publish_blog(date, md, args.days)
        print(f"-> 블로그 포스트 {post}")


if __name__ == "__main__":
    main()
