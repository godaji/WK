#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
normalize_whisky_name.py — 위스키 원시 표기명을 whisky-list.csv 정본 id 로 정규화.

동의어 정의 정본은 같은 폴더의 whisky-synonyms.yaml. 크롤/수집/매칭 파이프라인에서
raw 상품명을 정본 id 로 dedup 할 때 사용한다.

빠른 사용:
    from normalize_whisky_name import Normalizer, load_rules
    norm = Normalizer(load_rules())
    r = norm.canonicalize("러셀 리저브 싱글 베럴 750ml")
    # r == {'status':'matched','id':'w077','name_ko':'러셀스 리저브 싱글배럴', ...}

CLI:
    python3 normalize_whisky_name.py "러셀 리저브 싱글 베럴 750ml"   # 단건
    python3 normalize_whisky_name.py --audit                         # 전수(데이터 워크스페이스에서)

정본 데이터(whisky-list.csv / whisky-aliases.csv)의 최신본은 CMPA-22 첨부가 source of truth.
이 스킬 번들의 사본은 스냅샷이며, 가격집계용으로는 CMPA-22 최신본을 받아 쓴다.
"""
import csv, os, re, sys
import yaml

HERE = os.path.dirname(os.path.abspath(__file__))


def _find(fname):
    """스킬 번들(같은 폴더) 우선, 없으면 데이터 워크스페이스(assets/) 순으로 탐색."""
    for cand in (os.path.join(HERE, fname),
                 os.path.join(HERE, "..", "..", "assets", fname),
                 os.path.join(HERE, "assets", fname)):
        if os.path.exists(cand):
            return cand
    return os.path.join(HERE, fname)


SYN_PATH = _find("whisky-synonyms.yaml")

# 전수(--audit) 모드 대상 — 데이터 워크스페이스 기준(스킬 단독 사용 시엔 불필요)
SOURCES = [
    ("data/whisky-prices/2026-03.csv", "술이름"),
    ("data/whisky-prices/2026-04.csv", "술이름"),
    ("data/whisky-prices/2026-05.csv", "술이름"),
    ("data/whisky-prices/2026-05_dailyshot.csv", "위스키명"),
    ("data/whisky-prices/2026-05_dailyshot.csv", "데일리샷상품명"),
    ("data/whisky-prices/2026-05_whiskeypick_traders_guwol.csv", "술이름"),
    ("whisky-list.csv", "name_ko"),
]


def load_rules(path=SYN_PATH):
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _build_syn_pairs(token_synonyms):
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
        for v, c in self.syn_pairs:
            if v in s:
                s = s.replace(v, c)
        for rx in self.noise:
            s = rx.sub(" ", s)
        return re.sub(r"\s+", " ", s).strip()

    def canonicalize(self, raw):
        """{status, id, name_ko, reason, norm}; status ∈ matched|excluded|unmatched"""
        norm = self.normalize_text(raw)
        for ex in self.exclude:
            if str(ex["token"]).lower() in norm:
                return {"status": "excluded", "id": "", "name_ko": "",
                        "reason": ex.get("reason", ""), "norm": norm}
        for p in self.products:
            allt = [str(t).lower() for t in p.get("match", [])]
            if allt and not all(t in norm for t in allt):
                ax = [str(a).lower() for a in p.get("aliases_exact", [])]
                if not any(a in norm for a in ax):
                    continue
            if any(str(t).lower() in norm for t in p.get("not", [])):
                continue
            return {"status": "matched", "id": p["id"], "name_ko": p["name_ko"],
                    "reason": "rule", "norm": norm}
        return {"status": "unmatched", "id": "", "name_ko": "", "reason": "", "norm": norm}


def _audit():
    norm = Normalizer(load_rules())
    names = {}
    for path, col in SOURCES:
        fp = path if os.path.exists(path) else _find(os.path.basename(path))
        if not os.path.exists(fp):
            continue
        with open(fp, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                v = (row.get(col) or "").strip()
                if v:
                    names.setdefault(v, set()).add(os.path.basename(path))
    by_id, exc, unm = {}, 0, 0
    for raw in sorted(names):
        r = norm.canonicalize(raw)
        if r["status"] == "matched":
            by_id.setdefault((r["id"], r["name_ko"]), []).append(raw)
        elif r["status"] == "excluded":
            exc += 1
        else:
            unm += 1
    print(f"raw={len(names)} matched={sum(len(v) for v in by_id.values())} "
          f"products={len(by_id)} excluded={exc} unmatched={unm}")


def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "--audit":
        _audit(); return
    if len(sys.argv) >= 2:
        norm = Normalizer(load_rules())
        for raw in sys.argv[1:]:
            r = norm.canonicalize(raw)
            print(f"{raw!r} -> [{r['status']}] {r['id']} {r['name_ko']}")
        return
    print(__doc__)


if __name__ == "__main__":
    main()
