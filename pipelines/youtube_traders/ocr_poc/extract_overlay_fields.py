#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_overlay_fields.py — CMPA-172 OCR 타당성 스파이크 (2/2단계)

ocr_dump_frames.py 가 만든 raw.json 만 읽어, 프레임별 OCR 박스에서
**제품명 + 최종가** 를 휴리스틱으로 뽑고 연속 프레임을 위스키 단위로 dedup 한다.
(네트워크·재OCR 없음 → 휴리스틱을 즉시 반복 튜닝 가능)

용법:  python3 extract_overlay_fields.py [raw.json]

스파이크 한계(= 후속 구현 과제, OCR 능력 한계 아님):
  * pick_price 의 '최대 폰트' 휴리스틱은 표준 레이아웃(단일가/취소선-할인가)에선
    ASR 와 정확히 일치하나, 1L 병·OCR 라인분할로 '100ml당 단가'가 새는 경우 오선택.
    → 최종가 전용 y-밴드 절대좌표 타게팅 + 단가/취소선 레이아웃 처리 필요.
"""
import json, re, sys
data = json.load(open(sys.argv[1] if len(sys.argv) > 1 else '/tmp/cmpa172/raw.json'))
NUM = re.compile(r'\d{1,3}(?:,\d{3})+|\d{4,7}')
NOISE = ('신세계','포인트','적립','할인','배너','관심','부탁','광고','공간','드립니다')
def is_hangul(s): return any('가'<=c<='힣' for c in s)

def pick_name(lines):
    cand=[l for l in lines if is_hangul(l['t']) and l['s']>0.85 and len(l['t'])>=3
          and not any(n in l['t'] for n in NOISE)]
    if not cand: return ''
    # title = topmost substantial hangul line
    cand.sort(key=lambda l:(l['y'], -len(l['t'])))
    return re.sub(r'\s+',' ',cand[0]['t']).strip()

def pick_price(lines):
    # final price = number token rendered with the LARGEST font (box height),
    # excluding unit-price (100ml당) and discount lines.
    best=None
    for l in lines:
        t=l['t']
        if 'ml' in t or '당' in t: continue           # 100ml당 단가 제외
        if any(n in t for n in ('적립','할인')): continue
        for m in NUM.finditer(t):
            v=int(m.group().replace(',',''))
            if v<10000: continue
            if best is None or l['h']>best[0]:
                best=(l['h'], v)
    return best[1] if best else None

# per-frame (name, final)
per=[]
for d in data:
    per.append((d['f'], pick_name(d['name']), pick_price(d['price'])))

# segment by consecutive same/similar name
def norm(s): return re.sub(r'\s+','',s)
segs=[]; cur=None
for f,name,price in per:
    if not name or not price:
        continue
    k=norm(name)
    if cur and (k==cur['k'] or (len(k)>=4 and (k in cur['k'] or cur['k'] in k))):
        cur['names'][name]=cur['names'].get(name,0)+1
        cur['prices'][price]=cur['prices'].get(price,0)+1
        cur['n']+=1
    else:
        cur={'k':k,'names':{name:1},'prices':{price:1},'n':1}
        segs.append(cur)
# resolve each segment: modal name + modal price
out=[]
for s in segs:
    name=max(s['names'].items(), key=lambda x:(x[1],len(x[0])))[0]
    price=max(s['prices'].items(), key=lambda x:x[1])[0]
    out.append((name,price,s['n']))

print(f"=== distinct whisky segments: {len(out)} ===")
for name,price,n in out:
    print(f"  {price:>8,}원 | {name}  (x{n}frames)")
