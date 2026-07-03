#!/usr/bin/env python3
"""위스키 '스토리·도수·맛' 보강 데이터 스토어 — CMPA-179 보드 지시.

가격변동 리포트 표 아래에 각 술의 **도수(ABV)·맛(테이스팅 노트)·스토리**를
리포트처럼 덧붙이기 위한 정본 보강 데이터.

데이터 3원칙 준수:
  ① 가져오기: 정본 `data/shilla-dutyfree/whisky-story.csv` 를 먼저 불러온다.
  ② 항목단위 갱신: 이미 있으면 그 값을 쓰고, 없으면 리서치해 행을 추가(누적).
  ③ 수집날짜 메타: 각 행에 `출처`·`수집일`을 둬 신뢰성 근거를 남긴다.

이 모듈은 읽기 전용 조회 + 마크다운 섹션 렌더만 담당한다. 새 술의 보강은
CSV 에 행을 추가(리서치 후)하면 다음 리포트부터 자동 노출된다.

매칭: 위스키명을 공백 제거·소문자화한 정규형으로 조회(스냅샷 간 사소한
표기차 흡수). 정확 일치가 없으면 보강 대기로 표시한다.
"""
import csv
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
STORY_CSV = os.path.join(ROOT, "data", "shilla-dutyfree", "whisky-story.csv")


def _norm(name):
    return "".join((name or "").split()).lower()


def load_stories(path=STORY_CSV):
    """정규형 키 -> 행 dict. 파일이 없으면 빈 dict(리포트 생성을 막지 않음)."""
    out = {}
    if not os.path.exists(path):
        return out
    with open(path, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            key = _norm(r.get("위스키명"))
            if key:
                out[key] = r
    return out


def lookup(name, stories=None):
    """위스키명으로 보강 행을 조회. 없으면 None."""
    stories = load_stories() if stories is None else stories
    return stories.get(_norm(name))


def render_story_section(names, stories=None):
    """주어진 위스키명들의 스토리 카드를 마크다운으로 렌더.

    중복 이름은 1회만. 보강 데이터가 있으면 도수·맛·캐스크·스토리·출처를,
    없으면 '보강 예정' 한 줄을 남긴다(누락을 숨기지 않음 — 데이터 정직성).
    리포트의 표 아래에 붙일 본문 문자열을 반환.
    """
    stories = load_stories() if stories is None else stories
    seen = set()
    L = []
    L.append("## 추가 정보 — 각 술의 스토리·도수·맛")
    L.append("")
    L.append("> 표의 가격 변동에 더해, 변동된 술이 어떤 술인지 도수·풍미·배경을 "
             "우리 보강 데이터(`whisky-story.csv`)에서 붙였습니다. 보강 데이터가 "
             "아직 없는 술은 '보강 예정'으로 표시하고 다음 갱신에 리서치해 채웁니다.")
    L.append("")
    pending = []
    for name in names:
        key = _norm(name)
        if not key or key in seen:
            continue
        seen.add(key)
        row = stories.get(key)
        if not row:
            pending.append(name)
            continue
        L.append(f"### {name}")
        meta = []
        if row.get("증류소"):
            meta.append(f"증류소 {row['증류소']}")
        if row.get("지역"):
            meta.append(f"지역 {row['지역']}")
        if meta:
            L.append("- **" + " · ".join(meta) + "**")
        if row.get("도수"):
            L.append(f"- **도수(ABV):** {row['도수']}")
        if row.get("캐스크"):
            L.append(f"- **캐스크/숙성:** {row['캐스크']}")
        if row.get("맛_노트"):
            L.append(f"- **맛(테이스팅 노트):** {row['맛_노트']}")
        if row.get("스토리"):
            L.append(f"- **스토리:** {row['스토리']}")
        src = row.get("출처", "")
        asof = row.get("수집일", "")
        tail = " · ".join(x for x in [src, (f"수집일 {asof}" if asof else "")] if x)
        if tail:
            L.append(f"- _출처: {tail}_")
        L.append("")
    if pending:
        L.append("### 보강 예정 (아직 우리 데이터에 없음)")
        for name in pending:
            L.append(f"- {name} — 도수·맛·스토리 리서치 후 다음 갱신에 반영")
        L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    s = load_stories()
    print(f"보강 데이터 {len(s)}종 로드: {STORY_CSV}")
    for k, r in s.items():
        print(f" - {r['위스키명']} | 도수 {r.get('도수','')}")
