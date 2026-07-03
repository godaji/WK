#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
normalize_whisky_name.py — 위스키 원시 표기명을 whisky-list.csv 정본 id 로 정규화.

동의어 정의의 정본은 assets/whisky-synonyms.yaml. 이 스크립트는 그 규칙을 해석하는
실행기이며, 크롤/수집 파이프라인에서 raw 상품명을 정본 id 로 dedup 할 때 사용한다.

용법:
  # 단건 정규화
  python3 scripts/normalize_whisky_name.py "러셀 리저브 싱글 베럴 750ml"

  # 전수 조사(audit): data/whisky-prices 의 한글 표기 전부를 정규화하고
  #   - assets/whisky-aliases.csv (raw → 정본 id 매핑, 전수)
  #   - 콘솔 요약(매칭/제외/미매칭, 변형 병합 검증)
  python3 scripts/normalize_whisky_name.py --audit
"""
import csv, os, re, sys
import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYN_PATH = os.path.join(ROOT, "assets", "whisky-synonyms.yaml")

# CMPA-444/CMPA-177: 숙성년수(N년) 비대칭 가드용. 많은 동의어 규칙이 브랜드 토큰만으로
# 매칭(예: {match:[글렌드로낙]} → 글렌드로낙 12년)이라, 'N년' 값이 다른 변형(글렌드로낙
# 18년·라가불린 8년)이 정본 다른 SKU 로 오병합된다. 변형과 정본의 N년이 둘 다 있고 값이
# 다르면 다른 제품 → 거절(ingest_ocr.match 의 최종 age 가드와 동일 규칙).
AGE_RE = re.compile(r"(\d{1,2})\s*년")


def _age(s):
    """문자열에서 숙성년수(N년) 토큰값(문자열) 추출, 없으면 None."""
    m = AGE_RE.search(str(s or ""))
    return m.group(1) if m else None

# 한글 표기명이 들어있는 (파일, 컬럼) 목록 — 전수 조사 대상
SOURCES = [
    ("data/whisky-prices/2026-03.csv", "술이름"),
    ("data/whisky-prices/2026-04.csv", "술이름"),
    ("data/whisky-prices/2026-05.csv", "술이름"),
    ("data/whisky-prices/2026-05_dailyshot.csv", "위스키명"),
    ("data/whisky-prices/2026-05_dailyshot.csv", "데일리샷상품명"),
    ("data/whisky-prices/2026-05_whiskeypick_traders_guwol.csv", "술이름"),
    ("assets/whisky-list.csv", "name_ko"),
]


def load_rules(path=SYN_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_syn_pairs(token_synonyms):
    """(variant, canonical) 쌍을 긴 변형 우선으로 정렬해 반환."""
    pairs = []
    for canon, variants in (token_synonyms or {}).items():
        for v in variants:
            pairs.append((str(v).lower(), str(canon).lower()))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


class Normalizer:
    def __init__(self, rules):
        self.rules = rules
        self.syn_pairs = _build_syn_pairs(rules.get("token_synonyms"))
        self.noise = [re.compile(p, re.IGNORECASE) for p in rules.get("noise_patterns", [])]
        self.products = rules.get("products", [])
        self.exclude = rules.get("exclude_non_whisky", [])

    def normalize_text(self, raw):
        s = str(raw).lower().strip()
        for v, c in self.syn_pairs:          # 1) 토큰 동의어 치환
            if v in s:
                s = s.replace(v, c)
        for rx in self.noise:                # 2) 잡음 제거
            s = rx.sub(" ", s)
        s = re.sub(r"\s+", " ", s).strip()   # 3) 공백 정리
        return s

    def canonicalize(self, raw):
        """반환 dict: {status, id, name_ko, reason, norm}
        status ∈ {matched, excluded, unmatched}"""
        norm = self.normalize_text(raw)
        # 제외(비위스키) 우선
        for ex in self.exclude:
            if str(ex["token"]).lower() in norm:
                return {"status": "excluded", "id": "", "name_ko": "",
                        "reason": ex.get("reason", ""), "norm": norm}
        # 제품 매칭 (위→아래, 먼저 맞는 것)
        for p in self.products:
            allt = [str(t).lower() for t in p.get("match", [])]
            if allt and not all(t in norm for t in allt):
                # aliases_exact 보조 매칭
                ax = [str(a).lower() for a in p.get("aliases_exact", [])]
                if not any(a in norm for a in ax):
                    continue
            nott = [str(t).lower() for t in p.get("not", [])]
            if any(t in norm for t in nott):
                continue
            # CMPA-444/CMPA-177: 변형 년수 ≠ 정본 년수면 다른 제품 → 이 규칙 거절(다음 규칙
            # 시도, 없으면 unmatched). 둘 중 하나라도 년수가 없으면(무연수 정본·큐레이트 별칭)
            # 보수적으로 통과시킨다(가드는 양쪽 명시 N년이 어긋날 때만 작동).
            va, ca = _age(raw), _age(p["name_ko"])
            if va is not None and ca is not None and va != ca:
                continue
            return {"status": "matched", "id": p["id"], "name_ko": p["name_ko"],
                    "reason": "rule", "norm": norm}
        return {"status": "unmatched", "id": "", "name_ko": "", "reason": "", "norm": norm}


def collect_raw_names():
    """(raw_name -> set(source_files)) 전수 수집."""
    names = {}
    for path, col in SOURCES:
        fp = os.path.join(ROOT, path)
        if not os.path.exists(fp):
            continue
        with open(fp, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                v = (row.get(col) or "").strip()
                if v:
                    names.setdefault(v, set()).add(os.path.basename(path))
    return names


def audit():
    rules = load_rules()
    norm = Normalizer(rules)
    names = collect_raw_names()

    rows = []
    by_id, excluded, unmatched = {}, [], []
    for raw in sorted(names):
        r = norm.canonicalize(raw)
        rows.append((raw, r["status"], r["id"], r["name_ko"], r["reason"],
                     ";".join(sorted(names[raw]))))
        if r["status"] == "matched":
            by_id.setdefault((r["id"], r["name_ko"]), []).append(raw)
        elif r["status"] == "excluded":
            excluded.append((raw, r["reason"]))
        else:
            unmatched.append(raw)

    out = os.path.join(ROOT, "assets", "whisky-aliases.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["raw_name", "status", "canonical_id", "canonical_name_ko",
                    "match_reason", "source_files"])
        w.writerows(rows)

    total = len(names)
    matched = sum(len(v) for v in by_id.values())
    print(f"=== 전수 조사 요약 (raw distinct = {total}) ===")
    print(f"matched  : {matched}  → {len(by_id)} 정본 상품")
    print(f"excluded : {len(excluded)} (비위스키)")
    print(f"unmatched: {len(unmatched)}")
    print(f"\n출력: assets/whisky-aliases.csv\n")

    # 변형 병합 검증: 한 정본 id 에 여러 raw 표기가 모인 사례(=동의어 통합 성공)
    print("=== 동의어 병합 예시 (raw 표기 ≥ 3개) ===")
    for (cid, nm), variants in sorted(by_id.items()):
        if len(variants) >= 3:
            print(f"[{cid}] {nm}  ← {len(variants)}종")
            for v in variants:
                print(f"      · {v}")

    if unmatched:
        print("\n=== 미매칭 (정본 미등록 위스키 후보 / 추가검토) ===")
        for u in unmatched:
            print(f"  ? {u}")
    if excluded:
        print("\n=== 제외(비위스키) ===")
        for raw, why in excluded:
            print(f"  x {raw}  ({why})")


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--audit":
        audit()
        return
    if len(sys.argv) >= 2:
        norm = Normalizer(load_rules())
        for raw in sys.argv[1:]:
            r = norm.canonicalize(raw)
            print(f"{raw!r}\n  -> [{r['status']}] {r['id']} {r['name_ko']}  (norm={r['norm']!r})")
        return
    print(__doc__)


if __name__ == "__main__":
    main()
