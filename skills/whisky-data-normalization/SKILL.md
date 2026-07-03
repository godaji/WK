---
name: whisky-data-normalization
description: >-
  위스키 원시 상품명(크롤·OCR·ASR)을 회사 정본 위스키 마스터(whisky-list.csv)의 id 로
  정규화·dedup 한다. 한글 위스키명을 수집·매칭·집계할 때(가격 트래커 CMPA-1 파이프라인,
  해외 소싱 CMPA-9/11/14, 데일리샷/코스트코/트레이더스 수집) 사용. "러셀 리저브 싱글 베럴"과
  "싱글 배럴"처럼 철자/음차 변형이 다른 상품으로 잡히는 문제를 해결한다.
---

# whisky-data-normalization

회사의 **위스키 마스터 리스트(whisky-list.csv, 88종)** 와 **동의어/표기변형 규칙** 을 묶은 공유 자산.
수집·크롤 파이프라인이 서로 다른 표기를 같은 정본 id 로 모을 수 있게 한다.

## 언제 쓰나
- 한글 위스키 상품명을 수집/파싱했고, 가격 집계·중복제거를 위해 정본 식별자가 필요할 때
- 데일리샷/코스트코/트레이더스/유튜브(싼디) 등 출처별 표기가 제각각인 이름을 통합할 때
- 새 출처를 붙이기 전에 "이 이름이 우리 마스터의 어느 상품인가"를 판정할 때

## 번들 파일
| 파일 | 역할 |
|---|---|
| `whisky-synonyms.yaml` | 동의어 정의 **정본**(토큰 동의어 + 잡음패턴 + 상품 매칭규칙 + 비위스키 제외목록). 사람이 편집. |
| `normalize_whisky_name.py` | 위 yaml 해석 실행기. `canonicalize(raw) → id`. |
| `whisky-list.csv` | 위스키 마스터 88종 스냅샷(id ↔ name_ko ↔ 메타). |
| `whisky-aliases.csv` | 원시표기→정본 id 전수 매핑 스냅샷(룩업 테이블). |

## ⚙️ 실행 파일·데이터 가져오기 (필수)
이 **company skill 은 SKILL.md(문서)만** 등록한다(Paperclip 스킬 라이브러리는 markdown-only).
위 4개 실행 파일은 [CMPA-22] 첨부가 **정본**이다. 처음 한 번 작업 CWD 로 부트스트랩하라:

```python
import os, re, json, urllib.request
API=os.environ["PAPERCLIP_API_URL"]; KEY=os.environ["PAPERCLIP_API_KEY"]
ISSUE="ad457726-a854-4b30-a124-0b834aad918b"  # CMPA-22 (정본)
WANT={"normalize_whisky_name.py","whisky-synonyms.yaml","whisky-list.csv","whisky-aliases.csv"}
def _get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers={"Authorization":f"Bearer {KEY}"})).read()
atts=json.loads(_get(f"{API}/api/issues/{ISSUE}/attachments"))
atts=atts if isinstance(atts,list) else atts.get("attachments",atts.get("items",[]))
for a in atts:
    fn=re.sub(r"^.*?[0-9a-f-]{36}-","",a["objectKey"].split("/")[-1])
    if fn in WANT:
        open(fn,"wb").write(_get(f'{API}/api/attachments/{a["id"]}/content')); print("fetched", fn)
```
그 뒤 `from normalize_whisky_name import Normalizer, load_rules` 로 바로 사용한다.

## 빠른 사용 (Python)
```python
from normalize_whisky_name import Normalizer, load_rules
norm = Normalizer(load_rules())

r = norm.canonicalize(scraped_name)   # {'status','id','name_ko','norm',...}
if r["status"] == "matched":
    row["whisky_id"] = r["id"]            # 정본 id 로 dedup/집계
elif r["status"] == "excluded":
    drop(scraped_name)                    # 보드카/진/꼬냑 등 비위스키
else:  # unmatched
    queue_for_review(scraped_name)        # 마스터 미등록 후보 → 보드 검토
```

CLI 단건 확인:
```bash
python3 normalize_whisky_name.py "러셀 리저브 싱글 베럴 750ml"
#  -> [matched] w077 러셀스 리저브 싱글배럴
```

## 동작
1. token_synonyms 치환(배럴↔베럴, 캐스크↔케스크, 셰리↔쉐리, 가쿠빈↔각쿠빈, 법원→버번 등)
2. noise 제거(용량/포장/가격/대괄호)
3. 공백 정리
4. products 의 match/not 토큰 부분일치 → 먼저 맞는 정본 id 채택

전수 기준(2026-05): raw 640종 → matched 500 / excluded 14 / unmatched 126.

## ⚠️ 데이터 신선도 — 정본 위치
이 번들의 `whisky-list.csv`·`whisky-aliases.csv` 는 **스냅샷**이다. 마스터/별칭은 월간 데이터와 함께
갱신되므로, **가격 집계 등 실사용에는 [CMPA-22] 첨부의 최신본을 받아 사용**한다(이 스킬은 도구·규칙의
안정 사본). 규칙(`whisky-synonyms.yaml`)에 새 표기/오타를 추가하면 CMPA-22 에도 반영하고 재배포한다.

## 유지보수
- 공통 철자/음차 변형 → `whisky-synonyms.yaml` 의 `token_synonyms`
- 특정 상품 한정 OCR 변형 → 해당 product 의 `aliases_exact`
- 새 정본 상품을 마스터에 추가하면 같은 id 의 매칭규칙을 `products` 에 추가(구체적 규칙일수록 위에)
- 추가 후 `python3 normalize_whisky_name.py --audit` 로 검증
