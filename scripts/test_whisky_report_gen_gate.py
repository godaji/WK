# -*- coding: utf-8 -*-
"""CMPA-265 위스키 리포트 '생성 단계' 데이터 변동 게이트 단위테스트(픽스처, 라이브 무관).

    python3 scripts/test_whisky_report_gen_gate.py

배경(CMPA-263 포렌식): 데이터가 안 바뀌어도(데이터 기준일 06-01 고정) generate_report 가 매
실행마다 오늘 날짜로 새 dated md 를 찍어 '리포트 생성일'이 가짜로 올라갔다. CMPA-265 는 생성
단계를 whisky_blog_gate 의 지문(report_signature/fingerprint, 단일 진실원천)으로 게이트한다.

검증:
  1) 무변동(지문 동일 + dated md 존재) → no-op (generate=False).
  2) 변경(지문 다름) → 재생성 (generate=True, reason=changed).
  3) 지문 동일이나 dated md 결측 → 복구 재생성 (generate=True, reason=unchanged_but_missing_file).
  4) --force → 무변동에도 강제 재생성 (generate=True, reason=force).
  5) 발행상태 조율(coordination): 생성 상태파일이 없어도 _blog_publish_state.json 의 동일 지문 +
     해당 dated md 존재 시 베이스라인 채택 → no-op (최초 도입 마이그레이션, 가짜-신선 방지).
  6) 상태 라운드트립: _write_gen_state → _resolve_prev_baseline 가 같은 (fp, gen_date) 복원.
  7) make_distribution: 배포본 실행일이 '오늘'이 아니라 소스 리포트 파일명의 생성일을 따른다.
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import generate_report as G  # noqa: E402


def case(title, fn):
    try:
        fn()
        print(f"  [OK ] {title}")
        return True
    except AssertionError as e:
        print(f"  [FAIL] {title}: {e}")
        return False


def _touch_report(month, gen_date):
    """G.REPORTS 아래 dated 정본 md 를 만든다(내용은 게이트 판단에 무관)."""
    os.makedirs(G.REPORTS, exist_ok=True)
    p = G._expected_report_path(month, gen_date)
    with open(p, "w", encoding="utf-8") as f:
        f.write(f"# dummy\n리포트 생성일 {gen_date}\n")
    return p


def _env(tmp):
    """G 모듈 전역(REPORTS·BLOG_STATE_PATH)을 임시 폴더로 재설정. (state_path 는 인자로 전달)"""
    G.REPORTS = os.path.join(tmp, "reports", "whisky-price")
    G.BLOG_STATE_PATH = os.path.join(tmp, "_blog_publish_state.json")
    return os.path.join(tmp, "_report_gen_state.json")


FP = "a" * 64
FP2 = "b" * 64
MONTH = "2026-06"


def test_unchanged_noop():
    with tempfile.TemporaryDirectory() as tmp:
        sp = _env(tmp)
        _touch_report(MONTH, "2026-06-01")
        G._write_gen_state(sp, FP, "2026-06-01", "2026-06-01", "x.md")
        dec = G.gate_decision(FP, MONTH, sp, force=False)
        assert dec["generate"] is False and dec["reason"] == "unchanged", dec
        assert dec["prev_gen"] == "2026-06-01", dec


def test_changed_regenerate():
    with tempfile.TemporaryDirectory() as tmp:
        sp = _env(tmp)
        _touch_report(MONTH, "2026-06-01")
        G._write_gen_state(sp, FP, "2026-06-01", "2026-06-01", "x.md")
        dec = G.gate_decision(FP2, MONTH, sp, force=False)   # 지문 변경
        assert dec["generate"] is True and dec["reason"] == "changed", dec


def test_unchanged_but_missing_file():
    with tempfile.TemporaryDirectory() as tmp:
        sp = _env(tmp)
        # dated md 를 만들지 않음(삭제 가정). 지문은 동일.
        G._write_gen_state(sp, FP, "2026-06-01", "2026-06-01", "x.md")
        dec = G.gate_decision(FP, MONTH, sp, force=False)
        assert dec["generate"] is True and dec["reason"] == "unchanged_but_missing_file", dec


def test_force_regenerate():
    with tempfile.TemporaryDirectory() as tmp:
        sp = _env(tmp)
        _touch_report(MONTH, "2026-06-01")
        G._write_gen_state(sp, FP, "2026-06-01", "2026-06-01", "x.md")
        dec = G.gate_decision(FP, MONTH, sp, force=True)   # 무변동이지만 force
        assert dec["generate"] is True and dec["reason"] == "force", dec


def test_coordination_from_publish_state():
    """생성 상태파일이 없을 때 발행상태(_blog_publish_state.json)와 조율 채택."""
    with tempfile.TemporaryDirectory() as tmp:
        sp = _env(tmp)
        _touch_report(MONTH, "2026-06-09")
        with open(G.BLOG_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump({"fingerprint": FP, "gen_date": "2026-06-09",
                       "data_date": "2026-06-01"}, f)
        # 생성 상태파일 없음 → 발행상태의 동일 지문 + dated md 존재 → no-op.
        dec = G.gate_decision(FP, MONTH, sp, force=False)
        assert dec["generate"] is False and dec["reason"] == "unchanged", dec
        assert dec["prev_gen"] == "2026-06-09", dec
        # 발행상태 지문이 다르면 채택 안 함 → 생성.
        dec2 = G.gate_decision(FP2, MONTH, sp, force=False)
        assert dec2["generate"] is True, dec2


def test_state_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        sp = _env(tmp)
        _touch_report(MONTH, "2026-06-05")
        G._write_gen_state(sp, FP, "2026-06-05", "2026-06-01", "reports/x.md")
        prev_fp, prev_gen = G._resolve_prev_baseline(FP, MONTH, sp)
        assert prev_fp == FP and prev_gen == "2026-06-05", (prev_fp, prev_gen)
        st = G._read_json(sp)
        assert st["fingerprint"] == FP and st["gen_date"] == "2026-06-05", st
        assert st["history"] and st["history"][-1]["gen_date"] == "2026-06-05", st


def test_make_distribution_date_from_source():
    """배포본 실행일은 소스 리포트 파일명의 생성일을 따른다(오늘 아님)."""
    _ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, os.path.join(_ROOT, "reports"))
    import make_distribution as M
    assert M.date_from_report_name("2026-06_위스키가격리포트_2026-06-01.md") == "2026-06-01"
    assert M.date_from_report_name("/a/b/2026-05_위스키가격리포트_2026-05-30.md") == "2026-05-30"
    assert M.date_from_report_name("_위스키가격리포트_latest.md") is None
    assert M.date_from_report_name("") is None


def main():
    results = [
        case("무변동(지문 동일 + dated md 존재) → no-op", test_unchanged_noop),
        case("변경(지문 다름) → 재생성", test_changed_regenerate),
        case("지문 동일·dated md 결측 → 복구 재생성", test_unchanged_but_missing_file),
        case("--force → 강제 재생성", test_force_regenerate),
        case("발행상태 조율 채택(생성상태 부재 시) → no-op", test_coordination_from_publish_state),
        case("게이트 상태 라운드트립", test_state_roundtrip),
        case("make_distribution: 배포본 날짜=소스 리포트 생성일", test_make_distribution_date_from_source),
    ]
    n = sum(results)
    print(f"\n결과: {n}/{len(results)} 통과")
    if n != len(results):
        raise SystemExit(1)
    print("CMPA-265 리포트 생성 단계 변동 게이트 단위테스트 모두 통과 ✅")


if __name__ == "__main__":
    main()
