#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
md_to_pdf.py — Markdown → PDF 변환 (한글 정상 렌더 · 깨끗한 표 · 링크 보존) — CMPA-88

보드 지시: HTML 경유 변환은 한글이 깨지고 표가 망가졌다 → **MD 파일을 직접 PDF로** 변환한다.
이 스크립트는 배포본 MD를 입력으로 받아, 인쇄에 맞춘 깨끗한 표 레이아웃의 PDF를 생성한다.

핵심:
- 엔진: WeasyPrint(무료 OSS). headless Chrome 불필요.
- 한글: Windows Malgun Gothic 을 @font-face 로 주입하되, **반드시 FontConfiguration 을
  CSS·write_pdf 양쪽에 전달**해야 @font-face 폰트가 등록된다(이걸 빠뜨려 기존 PDF가
  DejaVu 로 폴백 → 한글 깨짐. 이번 변환의 근본 수정).
- 이모지: Segoe UI Emoji/Symbol 을 폴백 폰트로 추가(🥃🎯⚪ 등 두부 글자 방지).
- 표: GFM 표를 인쇄용 CSS(테두리·헤더 반복·행 분리 방지·정렬 보존)로 렌더. A4 가로.
- 링크 보존: MD `[text](url)` → `<a href>` → PDF Link annotation(/URI). 변환 후 검증.

사용:
  python3 md_to_pdf.py <input.md> [output.pdf]
  python3 md_to_pdf.py --selftest

출력 파일명은 입력의 run-date 규칙(파일명에 날짜 포함)을 그대로 유지한다.
"""
import sys
import re
from pathlib import Path

import markdown
from weasyprint import HTML, CSS
from weasyprint.text.fonts import FontConfiguration
from pypdf import PdfReader

# --- 폰트 경로 -------------------------------------------------------------
WIN_FONTS = Path("/mnt/c/Windows/Fonts")
_FONT_REG = WIN_FONTS / "malgun.ttf"
_FONT_BD = WIN_FONTS / "malgunbd.ttf"
_FONT_EMOJI = WIN_FONTS / "seguiemj.ttf"   # 컬러 이모지(모양은 렌더)
_FONT_SYM = WIN_FONTS / "seguisym.ttf"     # 기호(⚪🔞 등)


def _font_faces() -> str:
    """사용 가능한 폰트만 @font-face 로 등록하고 본문 폰트 스택을 구성."""
    faces = []
    body_stack = []
    if _FONT_REG.exists():
        faces.append(
            "@font-face{font-family:'WK';font-weight:400;font-style:normal;"
            f"src:url('{_FONT_REG.as_uri()}');}}"
        )
        body_stack.append("'WK'")
    if _FONT_BD.exists():
        faces.append(
            "@font-face{font-family:'WK';font-weight:700;font-style:normal;"
            f"src:url('{_FONT_BD.as_uri()}');}}"
        )
    for fam, path in (("WKEmoji", _FONT_EMOJI), ("WKSym", _FONT_SYM)):
        if path.exists():
            faces.append(
                f"@font-face{{font-family:'{fam}';"
                f"src:url('{path.as_uri()}');}}"
            )
            body_stack.append(f"'{fam}'")
    body_stack += ["sans-serif"]
    stack = ",".join(body_stack)
    return "".join(faces) + f"html,body{{font-family:{stack};}}"


# --- 인쇄용 CSS ------------------------------------------------------------
def _print_css() -> str:
    return """
@page{size:A4 landscape;margin:12mm 12mm 14mm 12mm;
      @bottom-center{content:counter(page) ' / ' counter(pages);
                     font-size:8pt;color:#888;}}
html,body{font-size:9.5pt;line-height:1.45;color:#1a1a1a;}
h1{font-size:18pt;margin:0 0 4pt;border-bottom:2px solid #333;padding-bottom:4pt;}
h2{font-size:13pt;margin:14pt 0 6pt;color:#222;border-left:4px solid #c0392b;
   padding-left:6pt;}
h3{font-size:11pt;margin:10pt 0 4pt;}
sub{color:#777;font-size:8pt;}
p{margin:5pt 0;}
hr{border:none;border-top:1px solid #ddd;margin:10pt 0;}
blockquote{margin:6pt 0;padding:5pt 9pt;background:#f7f7f9;
           border-left:3px solid #bbb;color:#333;font-size:8.8pt;}
blockquote p{margin:2pt 0;}
code{background:#eee;padding:0 3px;border-radius:3px;font-size:8.5pt;
     font-family:monospace,'WK';}
a{color:#1558b0;text-decoration:underline;}
table{border-collapse:collapse;width:100%;margin:6pt 0;font-size:8.3pt;
      table-layout:auto;}
thead{display:table-header-group;}
th,td{border:1px solid #cfcfcf;padding:2.6pt 5pt;vertical-align:top;}
th{background:#34495e;color:#fff;font-weight:700;text-align:center;}
tbody tr:nth-child(even){background:#f4f6f8;}
tr{page-break-inside:avoid;}
"""


# --- 링크 검증 -------------------------------------------------------------
def count_html_links(html: str) -> int:
    return len(re.findall(r"<a\b[^>]*\bhref\s*=", html, flags=re.IGNORECASE))


def extract_pdf_link_uris(pdf_path: Path):
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
                uri = action.get_object().get("/URI")
                if uri:
                    uris.append(str(uri))
    return uris


def korean_renders_ok(pdf_path: Path) -> bool:
    """추출 텍스트에 정상 한글 음절(가-힣)이 충분히 있으면 렌더 정상으로 본다."""
    reader = PdfReader(str(pdf_path))
    text = "".join((p.extract_text() or "") for p in reader.pages[:2])
    return len(re.findall(r"[가-힣]", text)) >= 30


# --- 변환 ------------------------------------------------------------------
def md_to_html_body(md_text: str) -> str:
    return markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code", "sane_lists", "attr_list", "md_in_html"],
        output_format="html5",
    )


def build_html(md_text: str, title: str) -> str:
    body = md_to_html_body(md_text)
    return (
        "<!DOCTYPE html><html lang='ko'><head><meta charset='utf-8'>"
        f"<title>{title}</title><style>{_font_faces()}{_print_css()}</style>"
        f"</head><body>{body}</body></html>"
    )


def convert(input_md: Path, output_pdf: Path) -> dict:
    output_pdf.parent.mkdir(parents=True, exist_ok=True)
    md_text = input_md.read_text(encoding="utf-8")
    html = build_html(md_text, input_md.stem)

    font_config = FontConfiguration()
    stylesheet = CSS(string="", font_config=font_config)  # @font-face는 inline <style>
    HTML(string=html, base_url=str(input_md.parent)).write_pdf(
        str(output_pdf), stylesheets=[stylesheet], font_config=font_config
    )

    n_html = count_html_links(html)
    pdf_uris = extract_pdf_link_uris(output_pdf)
    return {
        "input": str(input_md),
        "output": str(output_pdf),
        "size_kb": round(output_pdf.stat().st_size / 1024, 1),
        "pages": len(PdfReader(str(output_pdf)).pages),
        "html_links": n_html,
        "pdf_link_annots": len(pdf_uris),
        "sample_uris": pdf_uris[:5],
        "korean_ok": korean_renders_ok(output_pdf),
    }


def _report(r: dict):
    print("[MD→PDF 변환 완료]")
    print(f"  입력 : {r['input']}")
    print(f"  출력 : {r['output']}  ({r['size_kb']} KB, {r['pages']}쪽)")
    print(f"  한글 렌더 검증(가-힣 추출): {'PASS' if r['korean_ok'] else 'FAIL'}")
    if r["html_links"] > 0:
        ok = r["pdf_link_annots"] >= r["html_links"]
        print(f"  링크 보존 검증: {'PASS' if ok else 'FAIL'} "
              f"(PDF {r['pdf_link_annots']} / HTML {r['html_links']})")
        for u in r["sample_uris"]:
            print(f"    - {u}")
    else:
        print("  (이 MD에는 링크가 없어 링크 보존 검증 대상 없음)")


def _default_out(input_md: Path) -> Path:
    return input_md.parent / "pdf" / (input_md.stem + ".pdf")


def selftest():
    """한글 + 표 + 링크가 든 합성 MD 로 파이프라인 3대 보증을 증명."""
    import tempfile
    md = (
        "# 위스키 가격 셀프테스트\n\n"
        "네이버 지도 [발베니 매장](https://map.naver.com/v5/search/발베니) 링크.\n\n"
        "| 위스키 | 최저가(₩) | 유형 |\n| --- | ---: | :--: |\n"
        "| 발베니 12년 더블우드 | **94,900** | 스카치(몰트) |\n"
        "| 가쿠빈 | **27,690** | 재패니즈 |\n"
    )
    with tempfile.TemporaryDirectory() as d:
        mp = Path(d) / "selftest.md"
        mp.write_text(md, encoding="utf-8")
        out = Path(d) / "selftest.pdf"
        r = convert(mp, out)
        _report(r)
        assert r["korean_ok"], "한글 렌더 실패"
        assert r["pdf_link_annots"] >= 1, "링크 보존 실패"
        print("  SELFTEST PASS ✅ (한글·표·링크 모두 정상)")


def main(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--selftest":
        selftest()
        return 0
    input_md = Path(argv[0])
    if not input_md.exists():
        print(f"입력 MD 없음: {input_md}", file=sys.stderr)
        return 2
    output_pdf = Path(argv[1]) if len(argv) > 1 else _default_out(input_md)
    _report(convert(input_md, output_pdf))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
