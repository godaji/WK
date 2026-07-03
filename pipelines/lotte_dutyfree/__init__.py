"""롯데면세점(lottedfs.com) 위스키 카탈로그 수집 파이프라인.

부모 이슈 CMPA-645 A안 / 구현 CMPA-647.

⚠️ 롯데면세가 = 면세가(세금 0·출국 조건) → 국내 최저가가 아니다 (CMPA-321 패턴).
   신라면세 파이프라인(pipelines/shilla_dutyfree/)과 동일 취급한다.
"""
