#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CMPA-170 후보 큐레이션(사람 검수 결과) — extract_whisky_candidates.py 자동제안을
사람이 검수한 최종 분류. over-merge 양방향 가드 적용.

final_class:
  new_A    : 정본 신규 SKU(우선 반영 후보, freq/신뢰 충분) → w089~
  new_B    : 실제 제품이나 freq=1·저신뢰 → 이번 패스 보류(Whiskybase 후속)
  synonym  : 기존 정본의 OCR/ASR 표기변형 → whisky-synonyms.yaml 흡수(신규 id 금지)
  noise    : 비위스키/가비지/미니어처세트 등 → 영구 미매칭(정상)

출력: assets/_runs/whisky-list-candidates-curated_<date>.csv  + 매칭률 투영.
"""
import csv, os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
date = sys.argv[1] if len(sys.argv) >= 2 else "2026-06-07"

# norm_key -> (final_class, payload)
#   new_A/new_B payload = (name_ko, name_en, brand, category, origin, age)
#   synonym payload    = canon_id
#   noise payload      = reason
N = "new_A"; B = "new_B"; S = "synonym"; X = "noise"
CUR = {
 # ---- new_A : 우선 반영(30) ----
 "발렌타인 17년": (N, ("발렌타인 17년","Ballantine's 17 Year Old","Ballantine's","블렌디드","스코틀랜드",17)),
 "발렌타인 싱글몰트 글렌버기 16년 스몰 배치": (N, ("발렌타인 싱글몰트 글렌버기 16년","Ballantine's Single Malt Glenburgie 16","Ballantine's","싱글몰트","스코틀랜드-스페이사이드",16)),
 "러셀 리저브 10년": (N, ("러셀스 리저브 10년","Russell's Reserve 10 Year Old","Russell's Reserve","버번","미국",10)),
 "파클라스 15년": (N, ("글렌파클라스 15년","Glenfarclas 15 Year Old","Glenfarclas","싱글몰트","스코틀랜드-스페이사이드",15)),
 "글랜파 클라스 12년": (N, ("글렌파클라스 12년","Glenfarclas 12 Year Old","Glenfarclas","싱글몰트","스코틀랜드-스페이사이드",12)),
 "잭다니엘 허니": (N, ("잭다니엘 허니","Jack Daniel's Tennessee Honey","Jack Daniel's","리큐르(위스키베이스)","미국","NAS")),
 "글렌알라키 10년 루비포트": (N, ("글렌알라키 10년 루비 포트","GlenAllachie 10 Year Old Ruby Port Wood Finish","GlenAllachie","싱글몰트","스코틀랜드-스페이사이드",10)),
 "주라 18년": (N, ("주라 18년","Jura 18 Year Old","Jura","싱글몰트","스코틀랜드-아일랜드(섬)",18)),
 "발베니 16년 프렌치오크": (N, ("발베니 16년 프렌치 오크","Balvenie 16 Year Old French Oak","Balvenie","싱글몰트","스코틀랜드-스페이사이드",16)),
 "부쉬밀 12년 싱글몰트": (N, ("부쉬밀 12년 싱글몰트","Bushmills 12 Year Old Single Malt","Bushmills","싱글몰트","아일랜드",12)),
 "부쉬밀 10년 싱글몰트": (N, ("부쉬밀 10년 싱글몰트","Bushmills 10 Year Old Single Malt","Bushmills","싱글몰트","아일랜드",10)),
 "라프로익 오크셀렉트": (N, ("라프로익 오크 셀렉트","Laphroaig Select / Oak Select","Laphroaig","싱글몰트","스코틀랜드-아일라","NAS")),
 "에반 윌리엄스 싱글 배럴": (N, ("에반 윌리엄스 싱글배럴","Evan Williams Single Barrel","Evan Williams","버번","미국","NAS")),
 "에반윌리엄스 bib": (N, ("에반 윌리엄스 BIB","Evan Williams Bottled-in-Bond","Evan Williams","버번","미국","NAS")),
 "맥캘란 셰리오크 12년": (N, ("맥캘란 셰리 오크 12년","Macallan Sherry Oak 12 Year Old","The Macallan","싱글몰트","스코틀랜드-스페이사이드",12)),
 "린도어스 1494 코어 위스키": (N, ("린도어스 1494 코어","Lindores Abbey MCDXCIV Core","Lindores Abbey","싱글몰트","스코틀랜드-로우랜드","NAS")),
 "코발 밀레 위스키": (N, ("코발 밀레","Koval Millet","Koval","싱글그레인","미국","NAS")),
 "코발라이 위스키": (N, ("코발 라이","Koval Rye","Koval","라이","미국","NAS")),
 "벨즈": (N, ("벨즈","Bell's Original","Bell's","블렌디드","스코틀랜드","NAS")),
 "글렌피딕 12년 셰리캐스크": (N, ("글렌피딕 12년 셰리 캐스크","Glenfiddich 12 Year Old Sherry Cask","Glenfiddich","싱글몰트","스코틀랜드-스페이사이드",12)),
 "글렌피딕 18년": (N, ("글렌피딕 18년","Glenfiddich 18 Year Old","Glenfiddich","싱글몰트","스코틀랜드-스페이사이드",18)),
 "탈리스커 와일드 블루": (N, ("탈리스커 와일드 블루","Talisker Wild (name_en 미확정)","Talisker","싱글몰트","스코틀랜드-스카이","NAS")),
 "탈리스커 디스틸러스 에디션": (N, ("탈리스커 디스틸러스 에디션","Talisker Distillers Edition","Talisker","싱글몰트","스코틀랜드-스카이","NAS")),
 "커클랜드 15년 하일랜드": (N, ("커클랜드 15년 하일랜드 싱글몰트","Kirkland Signature Highland Single Malt 15","Kirkland","싱글몰트","스코틀랜드-하일랜드",15)),
 "커클랜드 시그니처": (N, ("커클랜드 시그니처 스카치","Kirkland Signature Blended Scotch","Kirkland","블렌디드","스코틀랜드","NAS")),
 "커클랜드 시그니처 캐나디안 위스키": (N, ("커클랜드 시그니처 캐나디안","Kirkland Signature Canadian Whisky","Kirkland","캐나디안","캐나다","NAS")),
 "커클랜드 시그니처 바틀 인본드 버번위스키": (N, ("커클랜드 바틀드 인 본드 버번","Kirkland Bottled-in-Bond Bourbon","Kirkland","버번","미국","NAS")),
 "블랙보트": (N, ("블랙보트","Black Bottle","Black Bottle","블렌디드","스코틀랜드","NAS")),
 "주라 10년": (N, ("주라 10년","Jura 10 Year Old","Jura","싱글몰트","스코틀랜드-아일랜드(섬)",10)),
 "주라 12년 셰리캐스크": (N, ("주라 12년 셰리 캐스크","Jura 12 Year Old Sherry Cask","Jura","싱글몰트","스코틀랜드-아일랜드(섬)",12)),

 # ---- new_B : 실제 제품이나 저신뢰/저빈도 → 보류 ----
 "탈리스커 스톰": (B, ("탈리스커 스톰","Talisker Storm","Talisker","싱글몰트","스코틀랜드-스카이","NAS")),
 "탈리스커 포트리": (B, ("탈리스커 포트 리","Talisker Port Ruighe","Talisker","싱글몰트","스코틀랜드-스카이","NAS")),
 "일라이저 크레이그 스몰 배치": (B, ("일라이저 크레이그 스몰배치","Elijah Craig Small Batch","Elijah Craig","버번","미국","NAS")),
 "발렌타인 마스터즈": (B, ("발렌타인 마스터즈","Ballantine's Master's","Ballantine's","블렌디드","스코틀랜드","NAS")),
 "제임슨 블랙배럴": (B, ("제임슨 블랙 배럴","Jameson Black Barrel","Jameson","블렌디드","아일랜드","NAS")),
 "그란츠 트리플 우드": (B, ("그란츠 트리플 우드","Grant's Triple Wood","Grant's","블렌디드","스코틀랜드","NAS")),
 "윈저 12년": (B, ("윈저 12년","Windsor 12","Windsor","블렌디드","스코틀랜드(한국시장)",12)),
 "윈저 17년": (B, ("윈저 17년","Windsor 17","Windsor","블렌디드","스코틀랜드(한국시장)",17)),
 "윈저 21년": (B, ("윈저 21년","Windsor 21","Windsor","블렌디드","스코틀랜드(한국시장)",21)),
 "스카치 블루 클래식": (B, ("스카치블루 클래식","Scotch Blue Classic","Scotch Blue","블렌디드","스코틀랜드(한국시장)","NAS")),
 "스카치 블로 17년": (B, ("스카치블루 17년","Scotch Blue 17","Scotch Blue","블렌디드","스코틀랜드(한국시장)",17)),
 "듀어스 캐리비안 스무스 8연": (B, ("듀어스 캐리비안 스무스 8년","Dewar's Caribbean Smooth 8","Dewar's","블렌디드","스코틀랜드",8)),
 "듀어스 화이트랍에": (B, ("듀어스 화이트 라벨","Dewar's White Label","Dewar's","블렌디드","스코틀랜드","NAS")),
 "스모크헤드 오리지널": (B, ("스모크헤드 오리지널","Smokehead","Smokehead","싱글몰트","스코틀랜드-아일라","NAS")),
 "네이키드 몰트": (B, ("네이키드 몰트","The Naked Malt","The Naked Malt","블렌디드몰트","스코틀랜드","NAS")),
 "시바스리갈 15년 리미티드 에디션": (B, ("시바스 리갈 15년","Chivas Regal 15","Chivas Regal","블렌디드","스코틀랜드",15)),
 "글렌모렌지 오리지널 10년": (B, ("글렌모렌지 오리지널 10년","Glenmorangie Original 10","Glenmorangie","싱글몰트","스코틀랜드-하일랜드",10)),
 "글렌리벳 파운더스 리저브": (B, ("글렌리벳 파운더스 리저브","Glenlivet Founder's Reserve","The Glenlivet","싱글몰트","스코틀랜드-스페이사이드","NAS")),
 "조니워커 골드 리저브 리미티드 에디션": (B, ("조니워커 골드라벨 리저브","Johnnie Walker Gold Label Reserve","Johnnie Walker","블렌디드","스코틀랜드","NAS")),
 "글렌고인 18년": (B, ("글렌고인 18년","Glengoyne 18","Glengoyne","싱글몰트","스코틀랜드-하일랜드",18)),
 "잭다니엘 파이어": (B, ("잭다니엘 파이어","Jack Daniel's Tennessee Fire","Jack Daniel's","리큐르(위스키베이스)","미국","NAS")),
 "짐빔 허니": (B, ("짐빔 허니","Jim Beam Honey","Jim Beam","리큐르(버번베이스)","미국","NAS")),
 "와일드 터키 81": (B, ("와일드터키 81","Wild Turkey 81","Wild Turkey","버번","미국","NAS")),
 "글랜그란트 아보랄리스": (B, ("글렌그란트 아보랄리스","Glen Grant Arboralis","Glen Grant","싱글몰트","스코틀랜드-스페이사이드","NAS")),
 "발렌타인 18년 싱글몰트 글렌버기": (B, ("발렌타인 싱글몰트 글렌버기 18년","Ballantine's Single Malt Glenburgie 18","Ballantine's","싱글몰트","스코틀랜드-스페이사이드",18)),
 "칼라일": (B, ("칼라일","Carlyle","Carlyle","블렌디드","스코틀랜드","NAS")),
 "라벨 5오": (B, ("라벨 5","Label 5","Label 5","블렌디드","스코틀랜드","NAS")),

 # ---- synonym : 기존 정본 흡수(신규 id 금지) ----
 "발렌타인 17년산": (S, "__new:발렌타인 17년"),
 "발렌타인 17년 말본 리미티드 에디션": (S, "__new:발렌타인 17년"),
 "발렌타인 싱글렌버기 16년": (S, "__new:발렌타인 싱글몰트 글렌버기 16년 스몰 배치"),
 "글렌피딕 12년 셰리": (S, "__new:글렌피딕 12년 셰리캐스크"),
 "글렌라키 10년 루비 포트": (S, "__new:글렌알라키 10년 루비포트"),
 "에반 윌리엄스 12주년 에디션 50도": (S, "__new:에반윌리엄스 bib"),
 "에반윌리엄스 12주년 에디션 50도": (S, "__new:에반윌리엄스 bib"),
 "에반 윌리엄스 bib 12주년 에디션": (S, "__new:에반윌리엄스 bib"),
 "에반 윌리엄스 bib 12주년 에디션 50도": (S, "__new:에반윌리엄스 bib"),
 "에반윌리엄스 bib 12주년 에디션 50도": (S, "__new:에반윌리엄스 bib"),
 "에반윌리엄스 보트림본드 12주년 에디션 50도": (S, "__new:에반윌리엄스 bib"),
 # 기존 정본 OCR/ASR 변형
 "글랜피딕 12년": (S, "w005"),
 "글랜피딕 14년": (S, "w006"),
 "글램피닉 15년": (S, "w007"),
 "글랜킨치 12년": (S, "w038"),
 "글랜란트 12년": (S, "w013"),
 "글랜란트 15년": (S, "w014"),
 "글랜립의 15년": (S, "w002"),
 "글랜립의 17년 스몰 배치 2": (S, "w003"),
 "글랜립의 19년 스몰 배치": (S, "w004"),
 "글랜드로 12년": (S, "w018"),
 "글랜 글라사 샌드엔드": (S, "w029"),
 "클라인엘리시 14년": (S, "w025"),
 "벤 10년": (S, "w017"),
 "라가블린 11년": (S, "w036"),
 "맥켈란 12년 더블 캐스크": (S, "w012"),
 "커티 프로히비션": (S, "w058"),
 "부심일 15년": (S, "w062"),
 "탈리스커": (S, "w032"),
 "글랜드러 오드더 엠버스": (S, "w086"),
 "글랜드로 오드트 더더밸리": (S, "w085"),
 "아벨라오 아부나흐흐 셰리케스 퀘디션": (S, "w011"),
 "아벨라워 셰리 캐스크 에디션": (S, "w011"),
 "조니어 그린": (S, "w042"),
 "조니어 레드": (S, "w049"),
 "조니어 블랙 루비": (S, "w052"),
 "조니어커 블랙": (S, "w050"),
 "조니어커 블루": (S, "w053"),
 "조니워커 블ml": (S, "w050"),

 # ---- noise : 비위스키/가비지/세트 ----
 "업타운 마가리타": (X, "칵테일(비위스키)"),
 "진 버번위스키": (X, "OCR 가비지('진 법원위스키')"),
 "칼라 1 블렌디드": (X, "OCR 가비지(칼라일 추정 저빈도)"),
 "글렌고인 미니어처 세트": (X, "미니어처 기프트세트(단일 SKU 아님)"),
 "커클랜드 시그니처꽃 약 xo": (X, "꼬냑 XO OCR('꽃 약'=꼬냑) 비위스키"),
 "스모키 스컷 아일라": (X, "OCR 가비지('스컷') 재확인 필요"),
 "윈저": (X, "용량/표기 truncated, 윈저 라인으로 흡수 예정"),
 "윈저 w그니처ml": (X, "OCR 가비지(truncated)"),
 "조니워커 블랙 오징어 게임 에디션": (X, "노벨티 한정판(블랙 변형) — 별도 SKU 보류"),
 "미스터 보스턴": (X, "초저가 한계 SKU — 보류"),
}

# load candidate csv
cand = list(csv.DictReader(open(os.path.join(ROOT,"assets","_runs",f"whisky-list-candidates_{date}.csv"),encoding="utf-8-sig")))
missing = [c["norm_key"] for c in cand if c["norm_key"] not in CUR]
assert not missing, f"미분류 키 존재: {missing}"

# assign w089+ to new_A in deterministic order (freq desc then key)
newA = [c for c in cand if CUR[c["norm_key"]][0]=="new_A"]
newA.sort(key=lambda c:(-int(c["freq"]), c["norm_key"]))
ids = {c["norm_key"]: f"w{89+i:03d}" for i,c in enumerate(newA)}

# build curated output
out=[]
freq_by_class={N:0,B:0,S:0,X:0}
for c in cand:
    cls,pl = CUR[c["norm_key"]]
    freq_by_class[cls]+=int(c["freq"])
    row={"final_class":cls,"freq":c["freq"],"n_variants":c["n_variants"],
         "norm_key":c["norm_key"],"rep_name":c["rep_name"],
         "price_min":c["price_min"],"price_max":c["price_max"],
         "sources":c["sources"],"raw_variants":c["raw_variants"],
         "proposed_id":"","name_ko":"","name_en":"","brand":"","category":"",
         "origin":"","age":"","synonym_target":"","note":""}
    if cls in (N,B):
        nm,en,br,cat,org,age=pl
        row.update(name_ko=nm,name_en=en,brand=br,category=cat,origin=org,age=age)
        if cls==N: row["proposed_id"]=ids[c["norm_key"]]
    elif cls==S:
        tgt=pl
        row["synonym_target"]=tgt
        row["note"]="신규 SKU로 흡수" if tgt.startswith("__new:") else "기존 정본 흡수"
    else:
        row["note"]=pl
    out.append(row)

order={N:0,B:1,S:2,X:3}
out.sort(key=lambda r:(order[r["final_class"]], -int(r["freq"]), r["norm_key"]))
cols=["final_class","proposed_id","name_ko","name_en","brand","category","origin","age",
      "freq","n_variants","price_min","price_max","synonym_target","norm_key","rep_name",
      "sources","note","raw_variants"]
outp=os.path.join(ROOT,"assets","_runs",f"whisky-list-candidates-curated_{date}.csv")
with open(outp,"w",encoding="utf-8-sig",newline="") as f:
    w=csv.DictWriter(f,fieldnames=cols); w.writeheader(); w.writerows(out)

from collections import Counter
cc=Counter(r["final_class"] for r in out)
print("=== 큐레이션 결과 (그룹 수 / raw행 수) ===")
for k,lab in [(N,"new_A(우선반영)"),(B,"new_B(보류)"),(S,"synonym(흡수)"),(X,"noise(미매칭정상)")]:
    print(f"  {lab:22s}: {cc.get(k,0):3d} 그룹 / {freq_by_class[k]:3d} 행")
print(f"\n출력: assets/_runs/whisky-list-candidates-curated_{date}.csv")

# === 매칭률 투영 ===
# 현재: distinct raw 615, matched 480(78%), excluded 14, unmatched 121
# 분모는 '위스키' 대상(=전체 - 비위스키). 비위스키 = 기존 excluded 14 + noise중 비위스키.
TOTAL=615; CUR_MATCH=480; CUR_EXCL=14
# distinct group 기준 신규 매칭 = new_A 그룹 + synonym 그룹
newA_groups=cc.get(N,0); syn_groups=cc.get(S,0)
# raw distinct 기준: 각 그룹의 raw_variants 수 합으로 신규매칭 distinct 추정
def nvar(r): return len(r["raw_variants"].split(" | "))
newA_raw=sum(nvar(r) for r in out if r["final_class"]==N)
syn_raw =sum(nvar(r) for r in out if r["final_class"]==S)
newB_raw=sum(nvar(r) for r in out if r["final_class"]==B)
noise_raw=sum(nvar(r) for r in out if r["final_class"]==X)
print("\n=== 매칭률 투영 (distinct raw 기준) ===")
print(f"  현재 matched distinct          : {CUR_MATCH} / {TOTAL}  = {CUR_MATCH/TOTAL*100:.1f}%")
after_A = CUR_MATCH + newA_raw + syn_raw
print(f"  +new_A({newA_raw}) +synonym({syn_raw}) → matched: {after_A} / {TOTAL}  = {after_A/TOTAL*100:.1f}%")
after_AB = after_A + newB_raw
print(f"  +new_B({newB_raw}) 추가 반영 시      : {after_AB} / {TOTAL}  = {after_AB/TOTAL*100:.1f}%")
print(f"  잔여 미매칭(noise, 정상)       : {noise_raw} distinct")
print(f"\n  정본 규모: 88 → {88+newA_groups}(new_A) → (+new_B={cc.get(B,0)} 시 {88+newA_groups+cc.get(B,0)})")