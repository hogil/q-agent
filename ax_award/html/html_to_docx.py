#!/usr/bin/env python3
"""AX_Award_지원서.html -> 텍스트가 살아있는 .docx (Word 로 열어 변환).

이미지 docx(build_docx.py)는 화면과 1:1 이지만 글자를 복사할 수 없다.
제출·편집용으로는 Word 가 HTML 을 직접 읽어 만든 문서가 필요하다 —
표·글자·색은 넘어오고, flex 로 짠 칸은 Word 가 자기 방식으로 다시 흘린다.

쓰기
  python html_to_docx.py
출력
  AX_Award_지원서_편집용.docx   (텍스트 복사·수정 가능)
  AX_Award_지원서_편집용.pdf    (변환 결과 확인용)
"""
import pathlib, win32com.client as win32

HERE = pathlib.Path(__file__).parent
SRC = HERE / "AX_Award_지원서.html"
OUT = HERE / "AX_Award_지원서_편집용.docx"
PDF = HERE / "AX_Award_지원서_편집용.pdf"

WD_FORMAT_DOCX, WD_FORMAT_PDF = 16, 17

word = win32.gencache.EnsureDispatch("Word.Application")
word.Visible = False
word.DisplayAlerts = 0
try:
    doc = word.Documents.Open(str(SRC), ConfirmConversions=False, ReadOnly=False)

    # 사내 양식 여백 (위 3 / 아래·좌·우 2.54 cm) 을 다시 잡는다 — HTML 은 여백 0 이다.
    # CentimetersToPoints 는 웹 레이아웃 문서에서 COM 오류를 내므로 직접 환산한다(1cm = 28.3465pt).
    CM = 28.3464567
    doc.ActiveWindow.View.Type = 3            # wdPrintView — 인쇄 레이아웃으로 먼저 전환
    for s in doc.Sections:
        ps = s.PageSetup
        ps.PageWidth, ps.PageHeight = 21.0 * CM, 29.7 * CM
        ps.TopMargin = 3.0 * CM
        ps.BottomMargin = ps.LeftMargin = ps.RightMargin = 2.54 * CM

    doc.SaveAs2(str(OUT), FileFormat=WD_FORMAT_DOCX)
    doc.ExportAsFixedFormat(str(PDF), ExportFormat=WD_FORMAT_PDF)
    pages = doc.ComputeStatistics(2)          # wdStatisticPages
    words = doc.ComputeStatistics(0)          # wdStatisticWords
    doc.Close(SaveChanges=0)
finally:
    word.Quit()

print(f"{OUT.name}  {OUT.stat().st_size/1e6:.1f} MB · {pages}장 · 단어 {words:,}개 (복사 가능)")
print(f"{PDF.name}   확인용")
