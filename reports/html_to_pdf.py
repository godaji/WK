#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
⚠️ DEPRECATED (CMPA-88, 2026-05-31): reports/md_to_pdf.py 를 대신 사용할 것.
이 변환기는 두 가지 문제로 폐기되었다:
  1) WeasyPrint 의 @font-face 폰트를 등록하려면 FontConfiguration 을 CSS·write_pdf 양쪽에
     전달해야 하는데 그걸 빠뜨려 Malgun 이 로드되지 않고 DejaVu 로 폴백 → 한글 깨짐.
  2) 변환 대상 HTML 이 화면용 인터랙티브(정렬) 표라 인쇄 시 표 레이아웃이 망가짐.
보드 지시로 MD 를 직접 PDF 로 변환하는 md_to_pdf.py 로 전환(한글·표·링크 모두 검증 통과).
이 파일은 이력 보존용으로만 남긴다.

html_to_pdf.py — HTML → PDF 변환 (하이퍼링크 보존) — CMPA-88

Google Drive(WK 폴더) 지인 공유용 PDF를 만든다.
- 엔진: WeasyPrint (무료 OSS, CSS/링크 충실, headless Chrome 불필요)
- 한글 렌더: Windows Malgun Gothic(/mnt/c/Windows/Fonts)을 @font-face 로 주입
  (이 환경엔 fontconfig 폰트 캐시가 없어 폰트를 명시 주입하지 않으면 한글이 깨짐)
- 링크 보존: <a href> 가 PDF Link annotation(/URI) 으로 들어갔는지 변환 후 검증

사용:
  python3 html_to_pdf.py <input.html> [output.pdf]
  python3 html_to_pdf.py --selftest        # 링크 보존 파이프라인 자체 검증

출력 파일명은 입력의 run-date 규칙(파일명에 날짜 포함)을 그대로 유지한다.
"""
import sys
import re
import shutil
import subprocess
from pathlib import Path

from weasyprint import HTML, CSS
from pypdf import PdfReader

# --- 한글 폰트 보장 (Malgun Gothic via fontconfig) -------------------------
# CMPA-88 회귀 교훈: @font-face url() 주입은 WeasyPrint 68 에서 조용히 실패하여
# DejaVu Sans 로 폴백 → 한글이 전부 두부(□)로 깨졌다(보드 지적). 신뢰할 수 있는
# 경로는 폰트를 fontconfig 에 설치한 뒤 패밀리명으로 참조하는 것.
WIN_FONTS = Path("/mnt/c/Windows/Fonts")
_FONT_REG = WIN_FONTS / "malgun.ttf"
_FONT_BD = WIN_FONTS / "malgunbd.ttf"
_USER_FONTS = Path.home() / ".fonts"
KOREAN_FAMILY = "Malgun Gothic"


def _has_korean_font() -> bool:
    """fontconfig 에 한글(ko) 커버리지 폰트가 있는지."""
    try:
        out = subprocess.run(
            ["fc-list", ":lang=ko"], capture_output=True, text=True, timeout=15
        ).stdout
        return bool(out.strip())
    except Exception:
        return False


def ensure_korean_font() -> bool:
    """한글 폰트가 fontconfig 에 없으면 Windows Malgun 을 ~/.fonts 로 설치.

    반환: 한글 폰트 사용 가능 여부.
    """
    if _has_korean_font():
        return True
    if not _FONT_REG.exists():
        return False  # 소스 폰트 없음 → 호출측에서 경고
    _USER_FONTS.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(_FONT_REG, _USER_FONTS / "malgun.ttf")
    if _FONT_BD.exists():
        shutil.copyfile(_FONT_BD, _USER_FONTS / "malgunbd.ttf")
    try:
        subprocess.run(["fc-cache", "-f", str(_USER_FONTS)], timeout=60,
                       capture_output=True)
    except Exception:
        pass
    return _has_korean_font()


def _korean_font_css() -> str:
    """본문 전체를 한글 커버 폰트로 강제(숫자/영문도 동일 폰트로 일관 렌더)."""
    stack = f"'{KOREAN_FAMILY}','Noto Sans CJK KR','NanumGothic',sans-serif"
    return "html,body,*{font-family:" + stack + " !important;}"


# --- 링크 검증 -------------------------------------------------------------
def count_html_links(html_path: Path) -> int:
    text = html_path.read_text(encoding="utf-8", errors="ignore")
    return len(re.findall(r"<a\b[^>]*\bhref\s*=", text, flags=re.IGNORECASE))


def extract_pdf_fonts(pdf_path: Path):
    """PDF 페이지 리소스에 임베드된 BaseFont 이름 집합."""
    reader = PdfReader(str(pdf_path))
    fonts = set()
    for page in reader.pages:
        res = page.get("/Resources")
        if not res:
            continue
        fobj = res.get_object().get("/Font")
        if not fobj:
            continue
        for _k, v in fobj.get_object().items():
            base = v.get_object().get("/BaseFont")
            if base:
                fonts.add(str(base))
    return fonts


def extract_pdf_link_uris(pdf_path: Path):
    """PDF 의 Link annotation 에서 외부 URI 목록을 추출."""
    reader = PdfReader(str(pdf_path))
    uris = []
    for page in reader.pages:
        annots = page.get("/Annots")
        if not annots:
            continue
        for ref in annots:
            obj = ref.get_object()
            if obj.get("/Subtype") != "/Link":
                continue
            action = obj.get("/A")
            if action:
                action = action.get_object()
                uri = action.get("/URI")
                if uri:
                    uris.append(str(uri))
    return uris


# --- 변환 ------------------------------------------------------------------
def convert(input_html: Path, output_pdf: Path) -> dict:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    korean_ok = ensure_korean_font()
    extra_css = _korean_font_css()
    stylesheets = [CSS(string=extra_css)]
    # base_url = HTML 디렉터리 → 상대 리소스/링크 정상 해석
    HTML(filename=str(input_html), base_url=str(input_html.parent)).write_pdf(
        str(output_pdf), stylesheets=stylesheets
    )
    n_html = count_html_links(input_html)
    pdf_uris = extract_pdf_link_uris(output_pdf)
    fonts = extract_pdf_fonts(output_pdf)
    # 한글 렌더 검증: Malgun(한글 커버) 폰트가 실제로 임베드됐는지.
    # DejaVu 만 임베드 = 한글 두부(□) 깨짐 = FAIL.
    korean_font_embedded = any(
        ("Malgun" in f) or ("Noto" in f) or ("Nanum" in f) or ("Gothic" in f)
        for f in fonts
    )
    return {
        "input": str(input_html),
        "output": str(output_pdf),
        "size_kb": round(output_pdf.stat().st_size / 1024, 1),
        "html_links": n_html,
        "pdf_link_annots": len(pdf_uris),
        "sample_uris": pdf_uris[:5],
        "korean_font_available": korean_ok,
        "embedded_fonts": sorted(fonts),
        "korean_font_embedded": korean_font_embedded,
    }


def _report(r: dict):
    print("[변환 완료]")
    print(f"  입력 : {r['input']}")
    print(f"  출력 : {r['output']}  ({r['size_kb']} KB)")
    print(f"  한글폰트 사용가능(fontconfig): {r['korean_font_available']}")
    print(f"  임베드 폰트: {r['embedded_fonts']}")
    ko_ok = r["korean_font_embedded"]
    print(f"  한글 렌더 검증: {'PASS' if ko_ok else 'FAIL — 한글 두부(□) 위험!'} "
          f"(한글커버 폰트 임베드={ko_ok})")
    print(f"  HTML <a href> 개수      : {r['html_links']}")
    print(f"  PDF Link annotation 개수: {r['pdf_link_annots']}")
    if r["sample_uris"]:
        print("  샘플 링크(PDF에서 추출):")
        for u in r["sample_uris"]:
            print(f"    - {u}")
    if r["html_links"] > 0:
        ok = r["pdf_link_annots"] >= r["html_links"]
        print(f"  링크 보존 검증: {'PASS' if ok else 'FAIL'} "
              f"({r['pdf_link_annots']}/{r['html_links']})")
    else:
        print("  (이 HTML에는 <a href> 링크가 없어 보존 검증 대상 없음)")


def selftest():
    """알려진 링크가 든 합성 HTML 로 링크 보존 파이프라인을 증명."""
    import tempfile
    html = """<!DOCTYPE html><html lang="ko"><head><meta charset="utf-8">
    <title>링크 보존 셀프테스트</title></head><body>
    <h1>위스키 콜키지프리 맵 (셀프테스트)</h1>
    <p>한글 렌더링 확인: 발렌타인 30년, 맥캘란 18년, 산토리 가쿠빈</p>
    <ul>
    <li><a href="https://map.naver.com/p/entry/place/12345678">네이버지도 딥링크 1</a></li>
    <li><a href="https://map.naver.com/p/entry/place/87654321">네이버지도 딥링크 2</a></li>
    <li><a href="https://www.dailyshot.co/">데일리샷</a></li>
    </ul></body></html>"""
    with tempfile.TemporaryDirectory() as d:
        hp = Path(d) / "selftest.html"
        pp = Path(d) / "selftest.pdf"
        hp.write_text(html, encoding="utf-8")
        r = convert(hp, pp)
        _report(r)
        assert r["html_links"] == 3, r
        assert r["pdf_link_annots"] >= 3, r
        assert any("naver" in u for u in r["sample_uris"]), r
        assert r["korean_font_embedded"], (
            "한글 커버 폰트가 임베드되지 않음 — 한글 두부 깨짐! " + str(r["embedded_fonts"])
        )
        print("\n[SELFTEST PASS] 링크 보존 + 한글 폰트 임베드 OK (클릭 가능 + 한글 정상).")


def main(argv):
    if len(argv) >= 2 and argv[1] == "--selftest":
        selftest()
        return
    if len(argv) < 2:
        print(__doc__)
        sys.exit(2)
    inp = Path(argv[1])
    if len(argv) >= 3:
        outp = Path(argv[2])
    else:
        outp = inp.parent / "pdf" / (inp.stem + ".pdf")
    r = convert(inp, outp)
    _report(r)


if __name__ == "__main__":
    main(sys.argv)
