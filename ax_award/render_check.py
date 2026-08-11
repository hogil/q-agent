#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""생성된 .docx 를 실제 Word 로 PDF 변환 후 페이지별 PNG 로 렌더한다.

CLAUDE.md §6 검증 절차 2단계. 사용: python render_check.py [버전번호]
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz  # PyMuPDF
import win32com.client as win32

OUT_DIR = Path(__file__).parent / "out"
WD_FORMAT_PDF = 17


def render(version: int) -> None:
    docx_path = (OUT_DIR / f"AX_Award_지원서_Q-Agent_v{version}.docx").resolve()
    if not docx_path.exists():
        raise SystemExit(f"없음: {docx_path}")
    pdf_path = docx_path.with_suffix(".pdf")

    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    try:
        doc = word.Documents.Open(str(docx_path), ReadOnly=True)
        doc.ExportAsFixedFormat(str(pdf_path), WD_FORMAT_PDF)
        pages_word = doc.ComputeStatistics(2)  # wdStatisticPages
        doc.Close(False)
    finally:
        word.Quit()

    img_dir = OUT_DIR / f"render_v{version}"
    img_dir.mkdir(parents=True, exist_ok=True)

    # 같은 버전을 여러 번 빌드하면 이전 시도의 page-6·7.png 가 남아 실제보다 페이지가
    # 많아 보인다(v43 에서 검수 에이전트가 5장을 7장으로 오독). 지우지 않고 옆으로 치운다.
    stale = sorted(img_dir.glob("page-*.png"))
    if stale:
        prev = img_dir / "_prev"
        prev.mkdir(exist_ok=True)
        n = 1
        while (prev / f"try{n}").exists():
            n += 1
        dest = prev / f"try{n}"
        dest.mkdir()
        for f in stale:
            f.rename(dest / f.name)
        print(f"이전 렌더 {len(stale)}장 → {dest}")

    pdf = fitz.open(pdf_path)
    for i, page in enumerate(pdf, start=1):
        page.get_pixmap(dpi=110).save(img_dir / f"page-{i}.png")
    print(f"Word 집계 페이지 수 : {pages_word}")
    print(f"PDF 페이지 수       : {pdf.page_count}   ← 이 값이 정답이다")
    print(f"이미지              : {img_dir}  (page-1..{pdf.page_count}.png)")
    pdf.close()


if __name__ == "__main__":
    render(int(sys.argv[1]) if len(sys.argv) > 1 else 1)
