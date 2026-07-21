#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_search_page.py — 위스키 전체 검색 페이지 (CMPA-1044).

whisky-list.csv 278종 전체를 테이블로 표시하고 검색/필터/정렬 기능을 제공한다.
가격 데이터가 있는 SKU는 가격을 표시하고, 없으면 '-' 표시.

데이터 소스:
  · 정본: assets/whisky-list.csv (전체 SKU 마스터)
  · 가격 보강: data/whisky-prices/normalized/normalized_prices.csv
  · 대시보드 스냅샷: data/dashboard/dashboard_latest.json (면세 등)

CLAUDE.md 필수 준수:
  · 모바일 우선(CMPA-255): 360px 카드 접힘
  · 수집 날짜 메타(CMPA-156): 가격에 수집일 표기
  · 카피 담백(CMPA-197)·저자 CaskCode(CMPA-198)

용법:
  python3 pipelines/dashboard/build_search_page.py
  python3 pipelines/dashboard/build_search_page.py --out /tmp/search.html
"""
import argparse
import csv
import html
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)

WHISKY_LIST = os.path.join(ROOT, "assets", "whisky-list.csv")
NORM = os.path.join(ROOT, "data", "whisky-prices", "normalized", "normalized_prices.csv")
OUT_DEFAULT = os.path.join(ROOT, "deploy", "dashboard", "search", "index.html")


def _to_int(v):
    try:
        return int(str(v).replace(",", "").strip())
    except (ValueError, TypeError, AttributeError):
        return None


def load_whisky_list():
    """whisky-list.csv 전체 로드."""
    rows = []
    with open(WHISKY_LIST, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows.append(r)
    return rows


def load_price_data():
    """normalized_prices.csv 에서 canonical_id -> 국내최저가 + 수집일.

    CMPA-496: 소스별 최신가 중 최소값 = floor.
    """
    from pipelines.common.source_floor import per_source_latest_floor

    obs = {}  # cid -> [(source, date, price)]
    try:
        with open(NORM, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                cid = (r.get("canonical_id") or "").strip()
                if not cid or (r.get("exclude_reason") or "").strip():
                    continue
                mkt = (r.get("market") or "").strip()
                if mkt not in ("KR", "KR-DS"):
                    continue
                p = _to_int(r.get("price_krw"))
                if p is None or p < 15000:
                    continue
                d = (r.get("date") or "").strip()
                ch = (r.get("channel") or "").strip()
                fam = (r.get("source_family") or "").strip()
                src = ch or fam
                obs.setdefault(cid, []).append((src, d, p))
    except FileNotFoundError:
        return {}

    result = {}
    for cid, observations in obs.items():
        fl = per_source_latest_floor(observations)
        if fl:
            price, src, prev = fl
            # 최신 수집일 찾기
            latest_date = max(d for _, d, _ in observations)
            result[cid] = {
                "price": price,
                "source": src,
                "date": latest_date,
            }
    return result


def load_dutyfree_data():
    """신라면세 가격 — build_dashboard.py 와 동일 방법론(roc._dutyfree_lookup).

    canonical_id -> KRW 면세가 매칭. 복잡한 substring 매칭은 기존 헬퍼 재사용."""
    from pipelines.youtube_traders.frame_ocr import run_ocr_collection as roc

    df = roc._dutyfree_lookup()  # (canon, shilla_rows, meta) | None
    if not df:
        return {}, None

    df_canon, df_shilla, df_meta = df
    usd_krw = (df_meta or {}).get("usd_krw", 1300)
    shilla_date = (df_meta or {}).get("sdate")

    # whisky-aliases 로드 (build_dashboard 패턴)
    aliases_path = os.path.join(ROOT, "assets", "whisky-aliases.csv")
    aliases, excluded = {}, set()
    try:
        with open(aliases_path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                status = (r.get("status") or "").strip()
                raw = (r.get("raw_name") or "").strip()
                if not raw:
                    continue
                if status == "shilla_exclude":
                    excluded.add(raw)
                elif status == "matched":
                    cid = (r.get("canonical_id") or "").strip()
                    if cid:
                        aliases[raw] = cid
    except FileNotFoundError:
        pass

    from pipelines.shilla_dutyfree import analyze_attractiveness as aa_mod

    # 신라 주류전체 CSV 보완 (버번 등 스피릿 카테고리 누락분)
    import glob as _glob
    existing_skus = {r.get("SKU", "") or r.get("상품코드", "") for r in df_shilla}
    spirit_files = sorted(_glob.glob(os.path.join(ROOT, "data", "shilla-dutyfree",
                                                   "신라면세_주류전체_*.csv")))
    if spirit_files:
        with open(spirit_files[-1], encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                sku = r.get("SKU", "") or r.get("상품코드", "")
                if sku in existing_skus:
                    continue
                r["_norm"] = aa_mod.norm(r.get("위스키명", ""))
                r["_vol"] = aa_mod.vol_of(r.get("위스키명", "")) or 700
                try:
                    usd_val = r.get("표시가_USD") or r.get("할인가_USD")
                    r["_usd"] = float(usd_val)
                except (ValueError, TypeError):
                    r["_usd"] = None
                df_shilla.append(r)

    canon_items = list(df_canon.items())
    result = {}

    for s in df_shilla:
        if s.get("_usd") is None:
            continue
        dvol = s.get("_vol") or 700
        if dvol < aa_mod.MINI_ML or dvol > aa_mod.MAGNUM_ML:
            continue
        sname = s["위스키명"].strip()
        sn = s["_norm"]
        if sname in excluded:
            continue

        cid = aliases.get(sname)
        if not cid:
            best_cid, best_extra = None, 9999
            for c_id, c in canon_items:
                if not (c.get("_norm") and c["_norm"] in sn):
                    continue
                if any(kw in sn and kw not in c["_norm"] for kw in aa_mod.EDITION_KW):
                    continue
                extra = len(sn) - len(c["_norm"]) - 5
                if extra > aa_mod.EXTRA_TOL:
                    continue
                if extra < best_extra:
                    best_extra = extra
                    best_cid = c_id
            cid = best_cid
        if not cid:
            continue

        krw = round(s["_usd"] * usd_krw)
        df_p100 = krw / dvol * 100

        if cid not in result or df_p100 < result[cid]["_p100"]:
            result[cid] = {
                "price_krw": krw,
                "date": shilla_date or "",
                "_p100": df_p100,
            }

    return result, shilla_date


def build_rows():
    """전체 SKU 행 생성."""
    whisky_list = load_whisky_list()
    prices = load_price_data()
    df_prices, df_date = load_dutyfree_data()

    rows = []
    for w in whisky_list:
        cid = (w.get("id") or "").strip()
        name_ko = (w.get("name_ko") or "").strip()
        brand = (w.get("brand") or "").strip()
        category = (w.get("category") or "").strip()
        age = (w.get("age") or "").strip()
        abv = (w.get("abv") or "").strip()
        volume = (w.get("volume_ml") or "").strip()
        channels = (w.get("channels") or "").strip()

        # 국내최저가
        p = prices.get(cid)
        retail_price = p["price"] if p else None
        retail_src = p["source"] if p else ""
        retail_date = p["date"] if p else ""

        # 면세가
        df = df_prices.get(cid)
        df_price = df["price_krw"] if df else None
        df_date_val = df["date"] if df else ""

        rows.append({
            "id": cid,
            "name": name_ko,
            "brand": brand,
            "category": category,
            "age": age,
            "abv": abv,
            "volume": volume,
            "channels": channels,
            "retail_price": retail_price,
            "retail_src": retail_src,
            "retail_date": retail_date,
            "df_price": df_price,
            "df_date": df_date_val,
        })

    return rows, df_date


def render_html(rows, df_date):
    categories = sorted(set(r["category"] for r in rows if r["category"]))

    # 통계
    n_total = len(rows)
    n_priced = sum(1 for r in rows if r["retail_price"] is not None)
    n_df = sum(1 for r in rows if r["df_price"] is not None)

    # 테이블 행 생성
    tr_list = []
    for r in rows:
        name_esc = html.escape(r["name"])
        brand_esc = html.escape(r["brand"])
        cat_esc = html.escape(r["category"])
        age_str = f'{r["age"]}년' if r["age"] else "NAS"
        abv_str = f'{r["abv"]}%' if r["abv"] else "-"
        vol_str = f'{r["volume"]}ml' if r["volume"] else "-"

        # 소매가
        if r["retail_price"] is not None:
            retail_html = (f'<b>{r["retail_price"]:,}원</b>'
                           f'<br><small class="muted">{html.escape(r["retail_src"])} '
                           f'{html.escape(r["retail_date"])}</small>')
            retail_sv = r["retail_price"]
        else:
            retail_html = '<span class="muted">-</span>'
            retail_sv = -1

        # 면세가
        if r["df_price"] is not None:
            df_html = (f'<b>{r["df_price"]:,}원</b>'
                       f'<br><small class="muted">신라면세 '
                       f'{html.escape(r["df_date"])}</small>')
            df_sv = r["df_price"]
        else:
            df_html = '<span class="muted">-</span>'
            df_sv = -1

        channels_esc = html.escape(r["channels"].replace(";", " · ")) if r["channels"] else "-"

        tr_list.append(
            f'<tr data-cat="{cat_esc}">'
            f'<td data-label="위스키" data-sort-val="{name_esc}">'
            f'{name_esc}<br><small class="muted">{brand_esc} · {cat_esc}</small></td>'
            f'<td data-label="숙성" data-sort-val="{int(r["age"]) if r["age"] and r["age"].isdigit() else 0}">'
            f'{age_str}</td>'
            f'<td data-label="도수" data-sort-val="{float(r["abv"]) if r["abv"] else 0}">'
            f'{abv_str}</td>'
            f'<td data-label="용량">{vol_str}</td>'
            f'<td data-label="국내최저가" data-sort-val="{retail_sv}">{retail_html}</td>'
            f'<td data-label="면세가" data-sort-val="{df_sv}">{df_html}</td>'
            f'<td data-label="채널" class="ch-cell">{channels_esc}</td>'
            f'</tr>'
        )

    # 카테고리 필터 버튼
    cat_btns = '<button class="fbtn active" data-cat="all">전체</button>'
    for cat in categories:
        n = sum(1 for r in rows if r["category"] == cat)
        cat_btns += f'<button class="fbtn" data-cat="{html.escape(cat)}">{html.escape(cat)} ({n})</button>'

    css = """
:root{--bg:#0f1115;--panel:#161922;--line:#2a2e38;--txt:#f2efe6;--sub:#9aa0aa;
--amber:#e0a84e;--gold:#ffd34e;--green:#34c759;--red:#ff6b6b}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--txt);
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans KR",sans-serif;
line-height:1.5;font-size:15px}
.wrap{max-width:1100px;margin:0 auto;padding:18px 14px 60px}
h1{font-size:21px;margin:6px 0 4px;color:var(--gold)}
.sub{color:var(--sub);font-size:13px;margin:0 0 14px}
.nav{margin-bottom:14px}
.nav a{color:var(--amber);text-decoration:none;font-size:13px}
.nav a:hover{text-decoration:underline}
h2{font-size:16px;color:var(--amber);margin:20px 0 10px;border-bottom:1px solid var(--line);
padding-bottom:6px}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{border:1px solid var(--line);padding:8px 9px;text-align:left;vertical-align:top;
word-break:keep-all}
th{background:var(--panel);color:var(--amber);font-weight:700;white-space:nowrap;
cursor:pointer;user-select:none}
th:hover{background:rgba(224,168,78,.12)}
tbody tr:nth-child(even){background:rgba(255,255,255,.015)}
b{color:var(--gold)}
small{font-size:11.5px}
.muted{color:var(--sub)}
.search-bar{margin-bottom:10px}
.search-input{width:100%;background:var(--panel);border:1px solid var(--line);
color:var(--txt);border-radius:6px;padding:10px 14px;font-size:15px;outline:none}
.search-input::placeholder{color:var(--sub)}
.search-input:focus{border-color:var(--amber)}
.filter-bar{display:flex;gap:6px;margin-bottom:10px;flex-wrap:wrap}
.fbtn{background:var(--panel);border:1px solid var(--line);color:var(--sub);
border-radius:6px;padding:6px 12px;font-size:13px;cursor:pointer;white-space:nowrap}
.fbtn.active{background:rgba(224,168,78,.18);color:var(--amber);border-color:var(--amber);font-weight:700}
.count-bar{color:var(--sub);font-size:12px;margin-bottom:8px}
.foot{margin-top:30px;padding-top:14px;border-top:1px solid var(--line);
color:var(--sub);font-size:12px}
/* 모바일 카드 레이아웃 (CMPA-255) */
@media(max-width:640px){
  body{font-size:13px}
  table,thead,tbody{display:block}
  thead{position:absolute;left:-9999px}
  th{display:none}
  tr{display:flex;flex-wrap:wrap;align-items:baseline;
     margin:0 0 5px;border:1px solid var(--line);border-radius:8px;
     padding:6px 10px;gap:2px 0}
  td{display:none;border:0;padding:0}
  /* 위스키명: 전체폭 */
  td[data-label="위스키"]{
    display:flex;flex:0 0 100%;flex-wrap:wrap;align-items:center;gap:4px;
    font-weight:700;color:var(--gold);font-size:13px;padding-bottom:2px}
  td[data-label="위스키"] br{display:none}
  /* 가격: 같은 줄 */
  td[data-label="국내최저가"],
  td[data-label="면세가"]{display:inline-flex;align-items:center;font-size:12px;color:var(--txt)}
  td[data-label="국내최저가"]::before{content:"소매 ";color:var(--sub);font-size:10px;margin-right:2px}
  td[data-label="면세가"]::before{content:" · 면세 ";color:var(--sub);font-size:10px;margin-right:2px}
  td[data-label="국내최저가"] small,
  td[data-label="면세가"] small{display:none}
  td[data-label="국내최저가"] br,
  td[data-label="면세가"] br{display:none}
  /* 숙성·도수·용량·채널: 숨김 (카드에서 브랜드·카테고리 small로 충분) */
  td[data-label="숙성"],td[data-label="도수"],
  td[data-label="용량"],td[data-label="채널"]{display:none}
  .ch-cell{display:none!important}
}
"""

    html_doc = f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>위스키 전체 검색 — CaskCode</title>
<style>{css}</style>
</head>
<body>
<div class="wrap">
  <div class="nav"><a href="../">← 대시보드로 돌아가기</a></div>
  <h1>🔍 위스키 전체 검색</h1>
  <p class="sub">전체 {n_total}종 · 국내최저가 수집 {n_priced}종 · 면세가 매칭 {n_df}종
  · 가격은 수집일 기준값(CMPA-156)</p>

  <div class="search-bar">
    <input id="q" class="search-input" type="search"
           placeholder="위스키명, 브랜드, 카테고리 검색..." autocomplete="off">
  </div>
  <div class="filter-bar" id="cat-bar">
    {cat_btns}
  </div>
  <div class="count-bar" id="count-bar">표시: {n_total}종</div>

  <table id="tbl">
    <thead><tr>
      <th data-col="0">위스키 ▲</th>
      <th data-col="1">숙성</th>
      <th data-col="2">도수</th>
      <th data-col="3">용량</th>
      <th data-col="4">국내최저가</th>
      <th data-col="5">면세가</th>
      <th data-col="6">채널</th>
    </tr></thead>
    <tbody>
      {''.join(tr_list)}
    </tbody>
  </table>

  <p class="foot">정본: <code>assets/whisky-list.csv</code> ·
  가격: <code>data/whisky-prices/normalized/normalized_prices.csv</code> ·
  생성기: <code>pipelines/dashboard/build_search_page.py</code> · by CaskCode</p>
</div>
<script>
(function(){{
  var tbl = document.getElementById('tbl');
  var ths = tbl.querySelectorAll('thead th');
  var tbody = tbl.querySelector('tbody');
  var allRows = Array.from(tbody.querySelectorAll('tr'));
  var sortCol = 0, sortAsc = true;
  var searchQ = '';
  var activeCat = 'all';
  var countBar = document.getElementById('count-bar');

  function sortRows(){{
    var isText = (sortCol === 0 || sortCol === 6);
    allRows.sort(function(a,b){{
      var av = a.children[sortCol] ? a.children[sortCol].getAttribute('data-sort-val') || a.children[sortCol].textContent : '';
      var bv = b.children[sortCol] ? b.children[sortCol].getAttribute('data-sort-val') || b.children[sortCol].textContent : '';
      if(isText){{
        return sortAsc ? av.localeCompare(bv,'ko') : bv.localeCompare(av,'ko');
      }}
      var an = parseFloat(av), bn = parseFloat(bv);
      if(isNaN(an)) an = -1;
      if(isNaN(bn)) bn = -1;
      if(an < 0 && bn >= 0) return 1;
      if(bn < 0 && an >= 0) return -1;
      return sortAsc ? an - bn : bn - an;
    }});
  }}

  function applyView(){{
    var q = searchQ.trim().toLowerCase();
    var visible = 0;
    allRows.forEach(function(r){{
      var show = true;
      if(activeCat !== 'all' && r.dataset.cat !== activeCat) show = false;
      if(show && q){{
        var txt = (r.children[0] ? r.children[0].textContent : '').toLowerCase();
        if(txt.indexOf(q) < 0) show = false;
      }}
      r.style.display = show ? '' : 'none';
      if(show) visible++;
      tbody.appendChild(r);
    }});
    countBar.textContent = '표시: ' + visible + '종';
  }}

  function updateIndicators(){{
    ths.forEach(function(th,i){{
      var base = th.textContent.replace(/ [▲▼]$/,'');
      if(i === sortCol) th.textContent = base + (sortAsc ? ' ▲' : ' ▼');
      else th.textContent = base;
    }});
  }}

  ths.forEach(function(th,i){{
    th.addEventListener('click', function(){{
      if(sortCol === i) sortAsc = !sortAsc;
      else {{ sortCol = i; sortAsc = (i === 0 || i === 6); }}
      sortRows();
      applyView();
      updateIndicators();
    }});
  }});

  document.getElementById('q').addEventListener('input', function(){{
    searchQ = this.value;
    applyView();
  }});

  document.getElementById('cat-bar').addEventListener('click', function(e){{
    var btn = e.target.closest('.fbtn');
    if(!btn) return;
    activeCat = btn.dataset.cat;
    document.querySelectorAll('#cat-bar .fbtn').forEach(function(b){{
      b.classList.toggle('active', b.dataset.cat === activeCat);
    }});
    applyView();
  }});

  sortRows();
  applyView();
  updateIndicators();
}})();
</script>
</body>
</html>
"""
    return html_doc


def main():
    ap = argparse.ArgumentParser(description="위스키 전체 검색 페이지 (CMPA-1044)")
    ap.add_argument("--out", default=OUT_DEFAULT, help="출력 HTML 경로")
    args = ap.parse_args()

    rows, df_date = build_rows()
    doc = render_html(rows, df_date)

    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(doc)

    n_priced = sum(1 for r in rows if r["retail_price"] is not None)
    n_df = sum(1 for r in rows if r["df_price"] is not None)
    print(f"WROTE {args.out}")
    print(f"  전체={len(rows)}종  국내최저가={n_priced}종  면세가={n_df}종")


if __name__ == "__main__":
    main()
