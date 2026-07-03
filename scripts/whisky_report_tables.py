#!/usr/bin/env python3
"""CMPA-15 위스키 가격 리포트 표 생성기.
- 입력: data/whisky-prices/2026-{03,04,05}.csv (국내), 2026-05_hk_whisky_poc.csv (홍콩)
- 출력: /tmp/table2.md (국내 최저가·매력도), /tmp/overseas.md (홍콩 면세 비교)
재실행 가능. 월간 자동화 시 months 리스트만 갱신.
"""
import csv, glob, os, re, statistics, sys
from collections import defaultdict, Counter

# CMPA-151: 하드코딩 절대경로(WK 트리) 제거 → 리포 루트 기준 + 환경변수 오버라이드.
# 정규화기(normalize_dataset)와 동일한 입력 디렉터리를 보게 해 _default 단독 실행을 보장한다.
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# CMPA-165: ASR 오수집(비-제품명·말도안되는 가격) 차단 + 매장 라벨 지점명 제거 공통 모듈.
sys.path.insert(0, _ROOT)
from pipelines.common.whisky_quality import (  # noqa: E402
    canonical_store, is_quarantined, is_collectible, is_future_collected)
from pipelines.common.run_dates import run_date  # noqa: E402  (가져온날짜 미래 스탬프 게이트용)
DATA = os.environ.get("WHISKY_PRICES_DIR") or os.path.join(_ROOT, "data", "whisky-prices")
COLS = ["트레이더스", "코스트코"]   # CMPA-160/165: 지점명 제거(전국가 동일)

# ── CMPA-429 (보드 CMPA-424 모델, 2026-06-16): 리포트 신선도 = **품목 단위 최신 수집일** ──
# (CMPA-156 데이터 3원칙 = 가져오기·항목 단위 갱신·수집날짜 메타의 직접 구현. 그 위에 신선도.)
#
# 보드 신선도 모델(CMPA-424 댓글): "트레이더스는 유튜브 영상 촬영일 기준으로 DB 저장 → 그 날짜로
# 표시. 코스트코는 크롤 후 바뀌면 그 날짜·값으로 저장. 핵심: **품목별로 가장 최근 수집일의
# 값·날짜를 쓴다**(가격 동일해도 더 최신 날짜 사용). 최근 수집 없으면 그 품목의 과거(가장 최근)
# 관측 사용." 저장(storage)은 이미 이 모델대로다(OCR=영상일 스탬프·코스트코=크롤일 스탬프, 누적).
#
# 구현: current_obs(md) = 게이트 마트(COLS=트레이더스·코스트코) 관측 중 **그 품목의 가장 최근
# 수집일**의 관측만. 품목 단위라, 8종짜리 부분 OCR(예: 06-08)이 71종 종합 sweep(06-01)을
# 통째로 덮어 표가 붕괴(CMPA-241)할 위험이 없다 → 종전의 '판매처 전체 sweep' 게이트(CMPA-177)와
# 그 부분-sweep 최소크기 가드(CMPA-243)를 **대체**한다(둘 다 폐기). 각 행 '기준일'은 그 품목의
# 최신 수집일이라 품목마다 다를 수 있다(06-08 OCR 품목은 06-08, 06-01 sweep 품목은 06-01).
#
# ⚠️ 롯데마트·이마트는 현재 게이트 대상이 아니다(COLS 제외) — 4월 이후 재수집이 끊겨 stale.
# 현재가 소스로 쓰면 옛 가격을 '현재'로 노출하므로 제외(과거평균엔 사용). 재수집이 살아나면 편입.
#
# ⚠️ stale 허용 정책(작업 #5): 어떤 품목의 최신 COLS 관측이 오래됐어도(예: 2개월+) 보드가 "최근
# 수집 없으면 과거 관측 사용"을 명시했으므로 제외하지 않는다. 대신 '기준일' 컬럼에 그 수집일을
# 그대로 노출해 독자가 신선도를 판단하게 한다(미래 수집일만 load() 에서 거짓 스탬프로 격리).
# CURRENT 는 헤더/보조파일 선택용 '참고 최신월'로만 남는다(게이트 아님).


def _month_files(data_dir):
    """국내 마트 월 CSV(suffix 없는 `YYYY-MM.csv`) 의 월 목록을 오름차순으로 반환.
    `*_dailyshot.csv`·`*_hk_whisky_poc.csv` 등 보조소스(suffix 있음)는 제외한다."""
    out = []
    for p in glob.glob(os.path.join(data_dir, "*.csv")):
        m = re.fullmatch(r"(\d{4}-\d{2})\.csv", os.path.basename(p))
        if m:
            out.append(m.group(1))
    return sorted(out)


def _ocr_files(data_dir):
    """트레이더스 유튜브 프레임-OCR 관측 CSV(`YYYY-MM_youtube_ocr.csv`) 목록을 오름차순 basename
    으로 반환(CMPA-429). 격리본(`*_youtube_ocr_quarantine.csv`)·런 스냅샷(`_runs/`)은 제외 —
    glob `*_youtube_ocr.csv` 는 `_quarantine`/`__run` suffix 와 매칭되지 않고 하위폴더도 안 본다.
    수집일(가져온날짜)=영상 촬영일이라 품목 단위 최신일 산출의 1차 신선 소스다(보드 CMPA-424)."""
    out = []
    for p in glob.glob(os.path.join(data_dir, "*_youtube_ocr.csv")):
        if re.fullmatch(r"\d{4}-\d{2}_youtube_ocr\.csv", os.path.basename(p)):
            out.append(os.path.basename(p))
    return sorted(out)


def resolve_config(data_dir, log=True):
    """데이터 폴더를 스캔해 (CURRENT, PAST, MONTHS, decision) 을 반환한다.
    CMPA-166: 월 게이트/이월 폐기. 더는 단일 CURRENT 로 리포트 전체를 묶지 않는다 —
    실제 현재가는 build_domestic 이 **항목 단위 최신 월**로 산출한다(아래).
    여기서 CURRENT(=최신 월)는 헤더 기본 월·보조파일(데일리샷/홍콩) 선택용 '참고값'일 뿐이다."""
    months = _month_files(data_dir)
    if not months:
        raise SystemExit(f"[whisky_report_tables] 국내 마트 월 CSV 없음: {data_dir}")
    current = months[-1]                    # 참고 최신월(헤더·보조파일 선택용) — 월 게이트 없음.
    past = tuple(m for m in months if m != current)
    # CMPA-429: 신선도는 '월'이 아니라 build_domestic 의 **품목 단위 최신 수집일**(current_obs)에서.
    decision = {"mode": "per_item_latest", "latest": current, "months": months,
                "reason": f"품목 단위 최신 수집일(CMPA-429) · 월 {months} · 참고 최신월 {current}"}
    if log:
        print(f"[whisky_report_tables] {decision['reason']}", file=sys.stderr)
    return current, past, [f"{m}.csv" for m in months], decision


def _pick_suffixed(suffix, current, data_dir):
    """`{current}_{suffix}.csv` 우선, 없으면 가장 최신 `{YYYY-MM}_{suffix}.csv`.
    보조소스(데일리샷·홍콩)가 아직 현재월로 안 들어왔을 때 직전월로 안전 폴백."""
    cur = os.path.join(data_dir, f"{current}_{suffix}.csv")
    if os.path.exists(cur):
        return os.path.basename(cur)
    cands = sorted(glob.glob(os.path.join(data_dir, f"*_{suffix}.csv")))
    return os.path.basename(cands[-1]) if cands else f"{current}_{suffix}.csv"


CURRENT, PAST, MONTHS, ROLLOVER = resolve_config(DATA)
MONTH_ORDER = [f[:7] for f in MONTHS]   # 오름차순 월 목록(항목 단위 최신월 산출용, CMPA-166).
DAILYSHOT_FILE = _pick_suffixed("dailyshot", CURRENT, DATA)
HK_FILE = _pick_suffixed("hk_whisky_poc", CURRENT, DATA)

def clean(n):
    n = n.strip(); n = re.sub(r'\s*\d+\s*m+l', '', n)
    # CMPA-169(보드 피드백): 누출 마케팅 문구·일반 카테고리 수식어 제거(표시명/그룹핑 품질).
    # ⚠️ '셰리캐스크' 등 제품 구분 토큰은 건드리지 않음 — 순수 일반 수식어/잡음만.
    n = re.sub(r'제품을\s*평소보다.*$', '', n)                       # '…제품을 평소보다' 마케팅 누출
    n = re.sub(r'싱글\s*몰트\s*위스키|싱글\s*모트\s*위스키|싱글\s*트\s*위스키|스카치\s*위스키', ' ', n)  # 일반 카테고리 수식어
    n = n.replace('글랜', '글렌').replace('그랜트', '그란트').replace('율리엄스', '윌리엄스')
    # CMPA-227: @위스키키 ASR 약어 '벤 10년' = 벤리악 10년(정본 w017, BenRiach The Original Ten).
    # 정확 문자열 치환(=yaml aliases_exact 와 일관) → 그룹핑·표시명 둘 다 벤리악으로 병합.
    # ⚠️ 광의 '벤' 금지(벤로막/벤네빅/벤리네스 오흡수, CMPA-177) — '벤 10년' 정확형만.
    n = n.replace('벤 10년', '벤리악 10년')
    # CMPA-227(보드 후속): ASR 약어/음차 → 정본 대표 표시명. 리포트는 yaml 동의어를 읽지 않고
    # 자체 clean()/key() 로 그룹핑·표시하므로, normalize 경로에선 이미 맞는 표기를 여기서도 맞춘다.
    # ⚠️ 정본 부분문자열 오염 없음: '글렌란트'⊄'글렌그란트', '글렌드로 오드'⊄'글렌드로낙 오드'.
    n = n.replace('글렌란트', '글렌그란트')          # 글렌란트 12/15년 → 글렌그란트(w013/w014)
    # 오드투더(Ode to the) 시리즈 브랜드 음차변형(글렌드로/글렌드러…) → 글렌드로낙(w085/w086).
    # 두 변형 모두 잡아야 그룹이 안 쪼개진다(한쪽만 잡으면 같은 제품이 두 그룹으로 분리·orphan).
    n = n.replace('글렌드로 오드', '글렌드로낙 오드').replace('글렌드러 오드', '글렌드로낙 오드')
    n = n.replace('오드 to투더', '오드 투더')          # 엠버스 OCR 'to투더' → '투더'
    n = n.replace('칼라 1', '칼라일')                  # ASR '칼라 1'(=칼라'일' 오청) → 칼라일(Carlyle, w130)
    n = re.sub(r'^더\s+', '', n); n = re.sub(r'\s+', ' ', n).strip(); return n

# 오탈자/표기변형 → 표준형. 같은 제품을 같은 key로 묶기 위함(서로 다른 제품은 건드리지 않음).
# 적용은 key()의 공백제거 문자열에. 순서 중요(구체적 → 일반).
TYPO = [
    ('싱글모트', '싱글몰트'), ('싱글트', '싱글몰트'),        # malt 오탈자
    ('케스크', '캐스크'), ('쉐리', '셰리'),                  # cask/sherry 표기 통일
    ('배럴', '베럴'),                                        # barrel
    ('파인노크', '파이노크'), ('켄터키', '캔터키'),
    ('글램모렌지', '글렌모렌지'), ('글렌라키', '글렌알라키'),
    ('라프로잇', '라프로익'), ('뱅콜', '뱅크홀'),
    ('스탠다드', '스탠더드'), ('진빔', '짐빔'), ('하이트', '화이트'),   # 진빔=ASR오청 → 짐빔(정본 name_ko·yaml)
    ('셀레트', '셀렉트'), ('러셀스', '러셀'), ('포로지지스', '포로지스'),
    ('더블로드', '더블우드'), ('글램버이', '글램버기'), ('글렌드로나', '글렌드로낙'),
    ('아브나르', '아브나흐'), ('아브나오', '아브나흐'), ('아브나우', '아브나흐'), ('아브나후', '아브나흐'),
    ('잭다니엘시', '잭다니엘스'), ('잭다니에스', '잭다니엘스'), ('잭다니스', '잭다니엘스'), ('잭다니의', '잭다니엘스'),
    # CMPA-165 (보드결정 B): 유튜브 ASR 오타로 갈라진 '같은 제품'을 정본 표기로 병합(1차 배치).
    # ⚠️ 서로 다른 에디션(오징어게임/더블블랙 등)은 건드리지 않음. 순서: 구체적 → 일반.
    ('조니어커', '조니워커'), ('조니어', '조니워커'),       # 조니워커 prefix 오타
    ('블랙라베', '블랙라벨'), ('블루라베', '블루라벨'),     # 라벨 끝음절 누락
    ('제임스나이시', '제임슨아이리시'),                     # 제임슨 아이리시
    ('진빈', '짐빔'), ('버유스키', '버번위스키'),           # 진빈/진빔 ASR오청 → 짐빔(Jim Beam) 버번
    ('법원', '버번'), ('유스키', '위스키'), ('이스키', '위스키'),
    ('쿠티삭', '커티삭'), ('커티프로이비션', '커티삭프로히비션'), ('프로이비션', '프로히비션'),
    ('탈리스마', '탈리스만'),                               # 탈리스만(블렌드) — 탈리스커 아님
    ('맥켈란', '맥캘란'), ('글램피닉', '글렌피딕'),
    # CMPA-169 item3: 추가 ASR 깨진 실제 제품명 → 정본 표기(yaml token_synonyms 와 일관).
    ('글렌립의', '글렌리벳'), ('아벨라오', '아벨라워'), ('퀘디션', '에디션'),
    ('클라인엘리시', '클라이넬리시'), ('부심일', '부쉬밀'), ('부시밀', '부쉬밀'),
    # CMPA-170 board 리포트 머지요청(2026-06-07): 동의어사전(yaml)과 리포트 그룹핑 일관화.
    ('스몰배치2', '스몰배치'),                                   # 글렌리벳 19년 스몰배치 '2'(배치번호) 통일
    ('싱글램버기', '싱글몰트글렌버기'),                           # '싱글(몰트 글렌)버기' 음절누락 복원(글램버기 규칙보다 먼저)
    ('글램버기', '글렌버기'),                                     # Ballantine's Glenburgie 표기통일(정본 name_ko)
    ('글렌버기16년스몰배치', '글렌버기16년'),                     # 글렌버기16 = 스몰배치 동일제품(w092)
    ('오드트더더', '오드투더'), ('오드to투더', '오드투더'),       # GlenDronach Ode-to-the OCR(yaml 일관)
    ('로드투더', '오드투더'), ('오드더', '오드투더'),
    ('투더닥', '투더다크'),
    ('글렌드러', '글렌드로'), ('글렌드오드투더', '글렌드로오드투더'),
    ('아벨라워셰리캐스크에디션', '아벨라워아브나흐셰리캐스크에디션'),  # A'bunadh = 셰리캐스크 에디션
    ('셰리케스에디션', '셰리캐스크에디션'),                       # 아벨라워 OCR '케스'(크 누락)
]
# ── CMPA-169: 조니워커 라벨 suffix·용량 전수 동의어 정규화 ──────────────────────
# ASR 자막이 같은 조니워커 제품을 라벨 끝음절 누락/오청(블랙라베·블랙누비·블로라·그인라 등)
# 으로 수십 갈래로 쪼갠다. 공백 제거된 key 문자열을 받아 표준 라벨 key 로 모은다.
# ⚠️ 가드(절대 라벨 병합 금지·정본 SKU 보존):
#   · 더블블랙(w051)·오징어게임 에디션·골드 리저브 = 블랙라벨과 별개 → 보존
#   · 블랙 '루비'(w052, 면세 전용 별개 제품)와 그 ASR 변형(누비·누루비)은 블랙'라벨'(w050)
#     로 병합 금지 — 둘을 각각 따로 모은다(정본 whisky-list.csv 가 distinct SKU 로 등록).
#   · 용량(1L/1.75L)은 진짜 다른 SKU → key 에 보존(대소문자만 통일). 700/750/ml=표준은 병합.
def _jw_vol(rest):
    """조니워커 변형의 '진짜 다른' 용량 suffix만 추출(대소문자 통일). 표준(700/750/ml)→''."""
    if '1.75' in rest: return '1.75L'
    if re.search(r'1\s*l', rest, re.I): return '1L'
    return ''
def _jw_canon(s):
    """공백 제거 key 문자열 → 조니워커 표준 라벨 key. 비-조니워커는 그대로 반환."""
    if not s.startswith('조니워커'): return s
    rest = s[len('조니워커'):]
    vol = _jw_vol(rest)
    # ── 별개 제품 가드(라벨 병합 금지) — 색상 판별보다 먼저 ──
    if '오징어' in rest or '게임' in rest: return '조니워커블랙오징어게임에디션'
    if '골드' in rest: return s                              # 골드 리저브 등 — 그대로 보존
    if '더블블랙' in rest or '더블랙' in rest: return '조니워커더블블랙' + vol
    if any(t in rest for t in ('루비', '누비', '누루비')):   # 블랙 루비(w052) = 블랙라벨과 별개
        return '조니워커블랙루비' + vol
    # ── 표준 라벨(블랙/블루/그린/레드) suffix 통일 ──
    if '블랙' in rest: return '조니워커블랙라벨' + vol
    if '블루' in rest or '블로' in rest: return '조니워커블루라벨' + vol
    if '그린' in rest or '그인' in rest: return '조니워커그린라벨' + vol
    if '레드' in rest: return '조니워커레드라벨' + vol
    return s

def key(n):
    s = re.sub(r'\s+', '', clean(n))
    for a, b in TYPO: s = s.replace(a, b)
    s = re.sub(r'잭다니엘(?!스)', '잭다니엘스', s)          # 잭다니엘 → 잭다니엘스 (스 없는 것만)
    s = _jw_canon(s)                                        # CMPA-169 조니워커 라벨/용량 통일
    return s

# CMPA-169: 병합된 조니워커 key 의 표시명을 표준 라벨로 정돈(용량 suffix 유지).
_JW_DISP = {'조니워커블랙라벨': '조니워커 블랙라벨', '조니워커블루라벨': '조니워커 블루라벨',
            '조니워커그린라벨': '조니워커 그린라벨', '조니워커레드라벨': '조니워커 레드라벨',
            '조니워커블랙루비': '조니워커 블랙 루비', '조니워커더블블랙': '조니워커 더블블랙'}
def jw_display(k, fallback):
    for base, disp in _JW_DISP.items():
        if k.startswith(base):
            vol = k[len(base):]
            return f"{disp} {vol}".strip() if vol else disp
    return fallback
def fix_display(name):                                      # 표시명도 오탈자 교정(공백 유지)
    for a, b in TYPO: name = name.replace(a, b)
    return re.sub(r'잭다니엘(?!스)', '잭다니엘스', name)
def seller_col(s):
    # CMPA-160/165: 매장 지점명 제거(전국가 동일) — 공통 모듈로 통일.
    return canonical_store(s)
def fmt(n): return f"{n:,}"

# CMPA-165: 비위스키(보드 데이터 품질 지적) — 마트엔 위스키 외 주류도 섞여 들어온다.
# 토큰은 key()(공백 제거·TYPO 적용) 문자열에 substring 매칭. '진'은 '진빔'(Jim Beam)과
# 충돌하므로 절대 단독 추가 금지 — 진 종류는 '드라이진'·브랜드명으로만 잡는다.
NONWHISKY = ['꼬약','꼬냑','브랜디','코냑','데낄라','데킬라','보드카','리큐르',
             # 보드카/진(드라이진·브랜드)
             '앱솔루트','스미노프','드라이진','봄베이','사파이어','탱커레이','헨드릭스','비피터',
             # 럼/칵테일/리큐르
             '바카디','마가리타','마르가리타','모이또','모히토','리몬첼','피치트리','깔루아',
             '베일리스','말리부','슈냅스','슈납스']
CATS = [
 (['탈리스커','라가불린','아드벡','라프로익','보모어','쿨일라','옥토모어','킬호만','아일라','피트','스모키'], '피트'),
 (['짐빔','진빔','메이커스','와일드터키','버팔로','잭다니엘','에반윌리엄스','1792','포로지스','러셀','불렛','우드포드','벤치마크','이글레어','놉크릭'], '버번'),
 (['제임슨','부쉬밀','털라모어','레드브레스트'], '아이리시'),
 (['야마자키','히비키','하쿠슈','산토리','가쿠빈','각쿠빈','니카','요이치','치타','토리스'], '재패니즈'),
 (['카발란','암룻','맥미라','폴존'], '월드몰트'),
 (['글렌피딕','글렌리벳','발베니','맥캘란','맥켈란','글렌그란트','글렌드로낙','글렌드로','아벨라워','글렌모렌지','달모어','오반','로얄브라클라','뱅크홀','탐듀','아란','벤리악','글렌알라키','클라이넬리시','에버펠','애버펠','글렌파클','파클라스'], '스카치(몰트)'),
 (['발렌타인','조니워커','시바스','듀어스','몽키숄더','골든블루','윈저','임페리얼','딤플','커티삭','벨즈','페이머스그라우스','칼라일'], '스카치(블렌디드)'),
]
def category(nk):
    for ks, c in CATS:
        if any(k in nk for k in ks): return c
    return '몰트(기타)' if '싱글몰트' in nk else '기타'

# CMPA-169(보드 피드백): 대표 표시명 출처 우선순위. 코스트코·데일리샷=정형 소매(정확),
# 트레이더스=유튜브 ASR(오청 많음). 표시명은 더 정확한 소스에서 관측된 표기를 우선 채택.
SRC_RANK = {'코스트코': 0}                  # 마트 루프엔 트레이더스/코스트코만 등장(데일리샷은 별도파일)
DISP_SRC = {}                               # k -> {cleaned_name: best_rank}  (load 가 채움)

def current_obs(md):
    """CMPA-429 (보드 CMPA-424 모델): '현재 판매중' 관측 = 게이트 마트(COLS) 관측 중 **그 품목의
    가장 최근 수집일**의 관측만. 품목 단위라 부분 OCR(8종 06-08)이 71종 종합 sweep(06-01)을
    덮는 붕괴(CMPA-241) 위험이 없어, 종전 '판매처 전체 sweep' 게이트(CMPA-177)와 부분-sweep
    최소크기 가드(CMPA-243)를 대체한다. 어느 게이트 마트에도 관측이 없으면 [](호출부가 제외).
    수집일은 'YYYY-MM-DD' 형식만 신선도 후보로 본다(비정형 제외). 가격이 같아도 더 최신 날짜를
    채택하므로 '기준일' 이 품목마다 다를 수 있다. md = {month: [(가격, 판매처, 수집일), …]}."""
    cobs = [(p, s, d) for obs in md.values() for (p, s, d) in obs
            if s in COLS and d and re.match(r"\d{4}-\d{2}-\d{2}$", d)]
    if not cobs:
        return []
    latest = max(d for _p, _s, d in cobs)
    return [(p, s, d) for (p, s, d) in cobs if d == latest]


def load():
    agg = defaultdict(lambda: defaultdict(list)); disp = defaultdict(Counter)
    global DROPPED_QUALITY, DISP_SRC
    DROPPED_QUALITY = Counter(); DISP_SRC = defaultdict(dict)
    today = run_date()                                  # 실행일(KST) — 미래 수집일 게이트 기준
    # CMPA-429: 국내 마트 월 CSV + 트레이더스 유튜브 프레임-OCR CSV(영상일 스탬프) 둘 다 관측 소스.
    # 둘 다 'YYYY-MM…' 파일명이라 m=f[:7] 이 월키를 준다(OCR=YYYY-MM_youtube_ocr.csv → YYYY-MM).
    for f in MONTHS + _ocr_files(DATA):
        m = f[:7]
        for row in csv.DictReader(open(f"{DATA}/{f}", encoding='utf-8-sig')):
            name = row['술이름']
            try: p = int(re.sub(r'[^\d]', '', row['가격_KRW']))
            except: continue
            if p <= 0: continue
            # CMPA-165: ASR 오수집(비-제품명·말도안되는 가격) 차단.
            q = is_quarantined(name, p)
            if q:
                DROPPED_QUALITY[q] += 1; continue
            collected = row['가져온날짜'].strip()
            # CMPA-243: 미래 수집일(오늘보다 뒤)은 거짓 스탬프(아직 수집 안 함) → 버린다.
            # stale 소스가 미래 날짜로 위장해 '최신 sweep' 을 가로채는 것을 방어한다.
            if is_future_collected(collected, today):
                DROPPED_QUALITY["future_collected_date"] += 1; continue
            k = key(name); seller = seller_col(row['위치']); nm = clean(name)
            agg[k][m].append((p, seller, collected)); disp[k][nm] += 1
            r = SRC_RANK.get(seller, 2)
            d = DISP_SRC[k]; d[nm] = min(d.get(nm, 9), r)   # 표기별 최우선(최저랭크) 소스 기록
    return agg, disp


def best_display(k, disp):
    """그룹 대표 표시명: 더 정확한 소스(코스트코>데일리샷>트레이더스ASR) 관측 표기 우선,
    동률은 빈도순. CMPA-169 보드 피드백 — 코스트코 등 정형 소매 이름을 대표명으로 사용."""
    cand = disp[k]
    if not cand: return ""
    src = DISP_SRC.get(k, {})
    return min(cand, key=lambda nm: (src.get(nm, 9), -cand[nm]))


DROPPED_QUALITY = Counter()


def item_current_month(md):
    """[호환용] 항목의 '현재월' = current_obs(품목 최신 수집일 관측)이 잡힌 월(CMPA-429).
    품목의 가장 최근 게이트-마트 관측의 월을 돌려준다. 관측이 없으면 None(=리포트 제외)."""
    co = current_obs(md)
    return max(d for _p, _s, d in co)[:7] if co else None

def load_dailyshot():
    """데일리샷 최저가 맵: key → (가격, 정확도). MISS/빈가격 제외, 같은 key는 최저가."""
    m = {}
    try:
        rows = csv.DictReader(open(f"{DATA}/{DAILYSHOT_FILE}", encoding='utf-8-sig'))
    except FileNotFoundError:
        return m
    for row in rows:
        acc = row.get('정확도', '').strip()
        if acc in ('', 'MISS'): continue
        try: p = int(re.sub(r'[^\d]', '', row.get('가격_KRW', '')))
        except: continue
        if p <= 0: continue
        k = key(row['위스키명'])
        if k not in m or p < m[k][0]: m[k] = (p, acc)
    return m

def build_domestic(agg, disp, dsmap=None, badges=None):
    """badges: {key: 'badge markup'} → 위스키 이름 옆에 붙는 배지(예: 🇭🇰↓ 🇯🇵↓). CMPA-54.
    배지는 해외 비교 섹션([2]홍콩/[3]일본)에서 '국내가 더 쌈'으로 판정된 동일 SKU에만 단다."""
    dsmap = dsmap or {}
    badges = badges or {}
    recs = []
    for k, md in agg.items():
        if any(w in k for w in NONWHISKY): continue
        # CMPA-429: 현재가 후보 = 게이트 마트(COLS)의 **그 품목 최신 수집일** 관측만.
        cobs = current_obs(md)
        if not cobs: continue                        # 어느 게이트 마트에도 관측 없음 = 단종/미판매 → 제외
        latest = cobs[0][2]                           # current_obs 의 관측은 모두 같은(품목 최신) 수집일
        allobs = [(p, s, d) for obs in md.values() for (p, s, d) in obs]
        # 과거평균(hist) = 현재 관측에 들지 않은 모든 과거 관측(현재 관측 제외 → 이중계상 방지).
        # 옛 트레이더스/코스트코 관측, 그리고 비-게이트 마트(롯데마트·이마트) 관측도 과거평균엔 반영.
        hist = [p for (p, s, d) in allobs if not (s in COLS and d == latest)]
        if not hist: hist = [p for p, _, _ in cobs]  # 이전 관측 없으면 현재 sweep 단일점(⚪ score 0)
        cur = min(p for p, _, _ in cobs)
        at_min = [(s, d) for p, s, d in cobs if p == cur]
        curseller, curdate = sorted(at_min, key=lambda x: x[1])[-1]  # 최저가 관측 중 가장 최근 날짜
        ph_min, ph_max = min(hist), max(hist); havg = round(statistics.mean(hist))
        if not (havg/3 <= cur <= havg*3): continue            # garbage filter
        if ph_min > 0 and ph_max/ph_min > 3: continue
        omin, omax = min(ph_min, cur), max(ph_max, cur)        # include current in range
        score, flat = (0, True) if omax == omin else (round((omax-cur)/(omax-omin)*100), False)
        ds = dsmap.get(k)
        dsdiff = (cur - ds[0]) if ds else None     # 마트최저가 − 데일리샷가 (음수 = 마트가 쌈)
        dsacc = ds[1] if ds else None
        # CMPA-177(보드 지적): 데일리샷 오매칭 가드. 데일리샷 검색이 'N년' 프리미엄 표현 등 **다른
        # 제품**을 근접 매칭하면 가격이 비상식적으로 벌어진다(예: 표준 '제임슨' 27,980 vs 데일리샷
        # '제임슨 18년' 370,000 → 가짜 −342,020 딜). 마트(트레이더스/코스트코)는 통상 최저가권이라
        # 데일리샷가가 마트가의 2.5배를 넘게 벌어지면 동일 제품으로 보기 어렵다 → 비교를 숨긴다(—).
        # (신라면세 CMPA-141 divergence reject 와 동일 취지. 정상 딜은 보통 2.5배 안쪽이라 무영향.)
        if ds and max(ds[0], cur) / max(min(ds[0], cur), 1) >= 2.5:
            dsdiff = dsacc = None
        recs.append(dict(k=k, name=jw_display(k, fix_display(best_display(k, disp))), cat=category(k),
                         cur=cur, curseller=curseller, curdate=curdate, omin=omin, omax=omax, havg=havg,
                         score=score, flat=flat, diff=cur-havg,     # 현재가 − 과거평균 (음수 = 쌈)
                         dsdiff=dsdiff, dsacc=dsacc, badge=badges.get(k, ""),
                         curmonth=curdate[:7]))    # 현재 관측의 월(=품목 최신 수집일, CMPA-429)
    # 정렬: 1차 매력도(score) 내림차순, 2차(같은 매력도) 가격 내림차순(보드 CMPA-434).
    # ⚪(flat=단일관측) 은 정렬 영향 없이 표시만 유지 — 같은 매력도면 비싼 순으로 통일.
    recs.sort(key=lambda r: (-r['score'], -r['cur']))
    sv = lambda v: f"−{fmt(-v)}" if v < 0 else (f"+{fmt(v)}" if v > 0 else "0")
    def dscell(r):
        if r['dsdiff'] is None: return "—"
        s = sv(r['dsdiff'])
        return f"≈{s}" if r['dsacc'] == '근접' else s
    out = ["| 위스키 | **최저가(₩)** | 매력도 | 과거평균比(₩) | 데일리샷대비(₩) | 유형 | 최저 판매처 | 기준일 | 관측MIN | 관측MAX | 과거평균 |",
           "|---|---:|:--:|---:|---:|:--:|---|:--:|---:|---:|---:|"]
    for r in recs:
        sc = f"**{r['score']}**" + (" ⚪" if r['flat'] else "")
        marks = r['badge']
        nm = f"{r['name']} {marks}".rstrip() if marks else r['name']
        out.append(f"| {nm} | **{fmt(r['cur'])}** | {sc} | {sv(r['diff'])} | {dscell(r)} | {r['cat']} | {r['curseller']} | {r['curdate']} | {fmt(r['omin'])} | {fmt(r['omax'])} | {fmt(r['havg'])} |")
    return out, recs

def domestic_min_map(agg, disp):
    """정본key → (국내 최저가, 표시명). CMPA-177: 국내 최저가는 판매처 최신 sweep(current_obs)
    에서만 산출. 홍콩/일본/면세(CMPA-234) 배지가 모두 **같은 dommin 기준**을 쓰도록 한 곳에서
    만든다(회귀·일관성). 어느 게이트 마트 최신 sweep 에도 없는 항목은 제외(단종 추정)."""
    dommin = {}
    for k, md in agg.items():
        cobs = current_obs(md)
        if cobs:
            dommin[k] = (min(p for p, *_ in cobs), disp[k].most_common(1)[0][0])
    return dommin


def build_overseas(agg, disp):
    dommin = domestic_min_map(agg, disp)   # CMPA-177 판매처 최신 sweep 기준(HK/JP/면세 공용).
    def dmin(substr, exclude=None):
        # (가격, 표시명, 정본key) — key 는 핵심표 배지 매칭용(CMPA-54).
        cand = [(v[0], v[1], kk) for kk, v in dommin.items()
                if substr in clean(v[1]) and '1L' not in v[1] and '전용잔' not in v[1] and 'BIB' not in v[1]
                and (exclude is None or exclude not in v[1])]
        return min(cand) if cand else None
    hk = list(csv.DictReader(open(f"{DATA}/{HK_FILE}", encoding='utf-8-sig')))
    def hk_best(pat):
        out = []
        for r in hk:
            nm = r['술이름']
            if re.search(r'\b(5|20|35|50|200|375)\s*ml|miniature|gift set|\(\s*50ml', nm, re.I): continue
            # CMPA-243: 빈티지/컬렉터블/단독캐스크/대용량(1980s·1974·grand vintage·limited·2L 등)은
            # 동일-SKU 비교 후보에서 격리. CEO 의 2.5x 발산 가드(아래 build_overseas 루프)는 증상
            # 차단용 — 근본은 매칭 후보에서 컬렉터블을 거르는 것(글렌모렌지 오리지널↔1980s 2L 오매칭).
            if is_collectible(nm): continue
            if re.search(pat, nm, re.I):
                try: out.append((int(r['기준가_KRW']), nm))
                except: pass
        out.sort(); return out[0] if out else None
    C = [('글렌피딕 12년','글렌피딕 12년',None,r'glenfiddich.*\b12\s*y','스카치(몰트)'),
         ('글렌피딕 15년','글렌피딕 15년',None,r'glenfiddich.*\b15\s*y','스카치(몰트)'),
         ('발베니 12년 더블우드','발베니 12년',None,r'balvenie.*double ?wood.*12','스카치(몰트)'),
         ('발베니 14년 캐리비안캐스크','발베니 14년',None,r'balvenie.*caribbean.*14','스카치(몰트)'),
         ('맥캘란 12년 더블캐스크','맥캘란 12년 더블',None,r'macallan.*double cask.*12','스카치(몰트)'),
         ('맥캘란 12년 쉐리오크','맥캘란 쉐리',None,r'macallan.*sherry oak.*12','스카치(몰트)'),
         ('글렌리벳 15년','글렌리벳 15',None,r'glenlivet.*15','스카치(몰트)'),
         ('라프로익 10년','라프로익 10',None,r'laphroaig.*10','피트'),
         ('탈리스커 10년','탈리스커 10',None,r'talisker.*10','피트'),
         ('글렌모렌지 오리지널(≈10년)','글렌모렌지',None,r'glenmorangie.*(original|10)\b','스카치(몰트)'),
         ('달모어 12년','달모어 12',None,r'dalmore.*\b12','스카치(몰트)'),
         ('로얄 브라클라 12년','로얄 브라클라',None,r'royal.?brackla.*12','스카치(몰트)'),
         ('글렌그란트 12년','그란트 12',None,r'glen ?grant.*12','스카치(몰트)'),
         ('카발란 디스틸러리 셀렉트','카발란 디스틸러리 셀렉트',None,r'kavalan distiller','월드몰트'),
         ('와일드터키 레어브리드','와일드 터키 레어브리드',None,r'wild ?turkey.*rare ?breed','버번'),
         ('조니워커 블랙 12년','조니워커 블랙','루비',r'johnnie ?walker.*12.*black','스카치(블렌디드)')]
    rows = []
    for disp_, dsub, dexc, hpat, cat in C:
        dd = dmin(dsub, dexc); hb = hk_best(hpat)
        if not (dd and hb): continue
        # wrong-product/컬렉터블 가드(CMPA-241): 동일 SKU 의 국내↔홍콩 면세가가 2.5배 넘게 벌어지면
        # 오매칭(빈티지·2L·리미티드 등 다른 제품)으로 본다 → 가짜딜 방지로 행 제외.
        # (CMPA-177 데일리샷·CMPA-141 신라 sanity 와 동일 취지. 정상 동일제품은 1.5배 안쪽이라 무영향.)
        if max(dd[0], hb[0]) / max(min(dd[0], hb[0]), 1) >= 2.5: continue
        rows.append((disp_, cat, dd[0], hb[0], dd[2]))  # dd[2]=정본key(배지 매칭, CMPA-54)
    rows.sort(key=lambda r: r[2]/r[3])
    out = ["| 위스키 | 유형 | 국내 최저가(₩) | 🇭🇰홍콩 면세가(₩) | 국내가=홍콩의 | 어디가 싼가 |",
           "|---|:--:|---:|---:|:--:|---|"]
    for disp_, cat, dm, hk_krw, _dkey in rows:
        ratio = dm/hk_krw
        v = f"**국내 {round((1-ratio)*100)}%↓**" if dm <= hk_krw else f"홍콩면세 {round((1-hk_krw/dm)*100)}%↓"
        out.append(f"| {disp_} | {cat} | **{fmt(dm)}** | {fmt(hk_krw)} | **{ratio*100:.0f}%** | {v} |")
    return out, rows


def hk_cheaper_keys(ovrows):
    """국내가 ≤ 홍콩 면세가인 동일 SKU 의 정본key 집합(핵심표 🇭🇰 배지용, CMPA-54)."""
    return {r[4] for r in ovrows if len(r) > 4 and r[4] and r[2] <= r[3]}


# ── CMPA-234 (부모 CMPA-232): 신라면세 대비 '면세↓' 배지 ───────────────────────
# 의미: 국내 마트 최저가 ≤ 신라면세점 면세가(KRW) 인 핵심표 SKU 에만 단다(HK/JP 와 동일 방향
#   = '국내가가 면세점보다도 쌈'). 국내 최저가는 HK/JP 와 같은 dommin(domestic_min_map,
#   CMPA-177 판매처 최신 sweep) 을 쓴다 — 기준이 같아야 회귀·일관성 유지.
# 매칭(가장 위험): 핵심표 표시명 ↔ 신라 위스키명 을 CMPA-138 find_cheaper_than_domestic 의
#   정밀 가드(희귀/인디/숙성대칭/디스크립터대칭/sig토큰/길이) 로 검증해 FP(가짜딜)를 막는다.
#   CLAUDE.md 위스키 매칭 원칙(CMPA-177): 숙성년수·CS·피티드·캐스크종류·에디션 토큰 비대칭이면
#   다른 SKU → 매칭 금지. 1L/잔/번들 노이즈는 700·750ml 만 비교해 배제.

_SHILLA_VOLS = (700, 750)   # HK/JP 와 동일하게 정규 700ml급 병끼리 비교(1L·미니어처 제외)
_SHILLA_SANITY = 2.5        # 면세가가 국내가의 2.5배↑ 면 오매칭 의심 → 배지 보류(sanity 가드)


def _shilla_guards():
    """CMPA-138 정밀 가드 함수들을 지연 임포트(파이프라인 폴더가 없으면 면세배지만 비활성)."""
    gdir = os.path.join(_ROOT, "pipelines", "shilla_dutyfree")
    if gdir not in sys.path:
        sys.path.insert(0, gdir)
    import find_cheaper_than_domestic as F  # noqa: E402  (enrich_dailyshot 임포트는 망 없음)
    return F


def _latest_shilla_csv():
    """가장 최근 신라면세_위스키_<date>.csv 자동선택(없으면 None)."""
    cands = sorted(glob.glob(os.path.join(_ROOT, "data", "shilla-dutyfree",
                                          "신라면세_위스키_*.csv")))
    return cands[-1] if cands else None


def _identity_tokens(name, F):
    """제품 식별 토큰(브랜드·표현명) 집합 — 숙성·용량·일반어(SIG_STRIP/SIG_STOP) 제거 후.
    한글 ≥2자·영문 ≥3자. CMPA-138 sig_token/hangul_anchor 와 같은 토큰화이되, 브랜드 인자
    없이(=핵심표 표시명엔 브랜드 컬럼이 없음) 안전하게 — F.hangul_anchor 에 brand='' 를 주면
    str.replace('', …) 가 문자열을 망가뜨려 앵커가 None 이 되는 함정을 피한다."""
    t = name.lower()
    t = re.sub(r"\d+\s*(?:ml|년|y|yo|years?|l|%)\b", " ", t)
    for g in F.SIG_STRIP:
        t = t.replace(g, " ")
    return [x for x in re.findall(r"[a-z]{3,}|[가-힣]{2,}", t) if x not in F.SIG_STOP]


def _best_shilla_match(dname, srows, F):
    """핵심표 표시명(dname) ↔ 신라 상품 정밀매칭. 동일 SKU로 신뢰 가능한 신라 최저 면세가(dict).
    가드: 700/750ml 정규병 · RARE/INDIE 제외 · 숙성 대칭 · 디스크립터(CS·피티드·피니시·에디션·
    프루프) 대칭(CMPA-177) · **양방향 식별토큰**(국내 토큰⊂신라 & 신라 토큰⊂국내 → 브랜드/표현
    오매칭 차단) · 길이 비대칭. 매칭 다수면 면세가 최저(보수적)."""
    dn = F.norm(dname)
    dage = F.age_of(dname)
    ddesc = F.descriptor_set(dname)
    dtoks = {F.norm(t) for t in _identity_tokens(dname, F)}
    if not dtoks:
        return None                                   # 식별 불가 표시명(잡음) → 매칭 안 함
    best = None
    for r, usd, krw in srows:
        sname = r["위스키명"]
        brand = (r.get("브랜드") or "").strip()
        if F.vol_of(sname) not in _SHILLA_VOLS:
            continue                                  # 1L/미니 → 병당 공정비교 불가
        if F.RARE_SHILLA.search(sname):
            continue                                  # 싱글캐스크·#번호 등 희귀/단독 → 비교 부적합
        if any(x in sname for x in F.INDIE_MARK):
            continue                                  # 인디/독립 보틀러 → OB 표준과 비교 부적합
        if F.age_of(sname) != dage:
            continue                                  # 숙성년수 대칭(CMPA-177)
        if F.descriptor_set(sname) != ddesc:
            continue                                  # 피니시·CS·프루프·에디션 대칭(CMPA-177)
        sn = F.norm(sname)
        stoks = {F.norm(t) for t in _identity_tokens(sname, F)}
        if not stoks:
            continue
        # 양방향 토큰 포함: 모든 국내토큰⊂신라명 & 모든 신라토큰⊂국내명. 한쪽에만 있는 표현
        # 토큰(싱글배럴↔보틀인본드, 더블캐스크↔GTR, 블랙↔골드)이 있으면 다른 SKU → 차단.
        if any(t not in sn for t in dtoks):
            continue
        if any(t not in dn for t in stoks):
            continue
        if best is None or krw < best["duty_krw"]:
            best = {"duty_krw": krw, "duty_usd": usd, "sname": sname,
                    "brand": brand, "vol": F.vol_of(sname),
                    "code": (r.get("상품코드") or "").strip()}
    return best


def shilla_cheaper_matches(agg, disp, csv_path=None):
    """핵심표 각 SKU 를 신라면세와 정밀매칭해 '국내 최저가 ≤ 면세가 ≤ 국내×2.5' 인 매칭 dict 리스트.
    각 dict: key/domname/dom/duty_krw/duty_usd/sname/brand/vol/code — 사람 검수표·배지에 공용."""
    path = csv_path or _latest_shilla_csv()
    if not path:
        return []
    try:
        F = _shilla_guards()
    except Exception as e:                            # 파이프라인 폴더 부재 등 → 면세배지 비활성
        print(f"[shilla_cheaper] guard import 실패 → 면세배지 skip: {e}", file=sys.stderr)
        return []
    usd_krw, _asof = F.load_fx()
    srows = []
    for r in csv.DictReader(open(path, encoding="utf-8-sig")):
        try:
            usd = float(r.get("할인가_USD") or 0)
        except (ValueError, TypeError):
            continue
        if usd <= 0:
            continue
        srows.append((r, usd, round(usd * usd_krw)))
    dommin = domestic_min_map(agg, disp)
    matches = []
    for k, (dom, dname) in dommin.items():
        if any(w in k for w in NONWHISKY):
            continue
        m = _best_shilla_match(dname, srows, F)
        if m is None:
            continue
        # 배지 조건: 국내 ≤ 면세(자랑 방향) + sanity(면세가 국내×2.5 초과면 오매칭 의심 → 보류).
        if dom <= m["duty_krw"] <= dom * _SHILLA_SANITY:
            m.update(key=k, domname=dname, dom=dom)
            matches.append(m)
    matches.sort(key=lambda m: m["duty_krw"] - m["dom"])   # 차이 작은 순(딜 강도)
    return matches


def shilla_cheaper_keys(agg, disp, csv_path=None):
    """국내 최저가 ≤ 신라면세점 면세가 인 핵심표 정본key 집합(면세↓ 배지용, CMPA-234).
    HK/JP 와 동일한 dommin(CMPA-177 판매처 최신 sweep) 기준."""
    return {m["key"] for m in shilla_cheaper_matches(agg, disp, csv_path)}

if __name__ == "__main__":
    agg, disp = load()
    t2, recs = build_domestic(agg, disp, load_dailyshot())
    ov, ovrows = build_overseas(agg, disp)
    open("/tmp/table2.md", "w", encoding='utf-8').write("\n".join(t2))
    open("/tmp/overseas.md", "w", encoding='utf-8').write("\n".join(ov))
    flat = sum(1 for r in recs if r['flat']); s100 = sum(1 for r in recs if r['score'] == 100)
    domwin = sum(1 for r in ovrows if r[2] <= r[3])
    from collections import Counter as _C
    bymonth = _C(r['curmonth'] for r in recs)      # 품목 최신 수집월 분포(품목마다 다를 수 있음, CMPA-429)
    bydate = _C(r['curdate'] for r in recs)
    print(f"CURRENT(참고최신월)={CURRENT} MONTHS={MONTH_ORDER} OCR={_ocr_files(DATA)} "
          f"dailyshot={DAILYSHOT_FILE} hk={HK_FILE}")
    print(f"mode: {ROLLOVER['reason']}")
    print(f"기준일 분포(품목 단위 최신 수집일, CMPA-429): {dict(sorted(bydate.items()))}")
    print(f"domestic rows={len(recs)} (매력도100={s100}, flat⚪={flat}) "
          f"| overseas={len(ovrows)} (국내우세={domwin})")
