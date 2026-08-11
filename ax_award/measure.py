#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""렌더된 PDF 에서 페이지별 실제 사용 높이를 재서 페이지 예산 초과분을 알려준다.

CLAUDE.md §4-B 예산을 눈이 아니라 수치로 맞추기 위한 도구.
사용: python measure.py [버전번호]
"""
from __future__ import annotations

import sys
from pathlib import Path

import fitz

OUT_DIR = Path(__file__).parent / "out"
PT_PER_CM = 72 / 2.54
TOP_MARGIN, BOTTOM_MARGIN, PAGE_H = 3.0, 2.54, 29.7
USABLE = PAGE_H - TOP_MARGIN - BOTTOM_MARGIN          # 24.16 cm


def measure(version: int) -> int:
    pdf_path = OUT_DIR / f"AX_Award_지원서_Q-Agent_v{version}.pdf"
    if not pdf_path.exists():
        raise SystemExit(f"없음: {pdf_path} — render_check.py 를 먼저 돌려라")

    doc = fitz.open(pdf_path)
    print(f"페이지 수 : {doc.page_count}   (목표 5)")
    print(f"본문 영역 : 상단 {TOP_MARGIN}cm ~ {TOP_MARGIN + USABLE:.2f}cm  (가용 {USABLE:.2f}cm)")
    print("-" * 64)
    total_text = 0.0
    for i, page in enumerate(doc, start=1):
        t_top = t_bot = None
        for blk in page.get_text("blocks"):        # 글자만 — 표 테두리 제외
            y0, y1 = blk[1] / PT_PER_CM, blk[3] / PT_PER_CM
            t_top = y0 if t_top is None else min(t_top, y0)
            t_bot = y1 if t_bot is None else max(t_bot, y1)
        d_bot = None
        for d in page.get_drawings():              # 표 테두리 포함
            y1 = d["rect"].y1 / PT_PER_CM
            d_bot = y1 if d_bot is None else max(d_bot, y1)
        if t_top is None:
            print(f"p{i}: 빈 페이지  ← 페이지나눔 낭비")
            continue
        text_h = t_bot - t_top
        total_text += text_h
        slack = (TOP_MARGIN + USABLE) - t_bot
        flag = "넘침" if slack < 0 else ("여백 큼" if slack > 3 else "OK")
        box = f"  테두리끝 {d_bot:5.2f}" if d_bot else ""
        print(f"p{i}: 글자 {t_top:5.2f}~{t_bot:5.2f}cm  높이 {text_h:5.2f}cm  "
              f"하단여유 {slack:+5.2f}cm{box}  [{flag}]")
    print("-" * 64)
    print(f"글자 총 높이 {total_text:.2f}cm  /  5장 예산 합계 약 111cm")
    doc.close()
    return 0


if __name__ == "__main__":
    sys.exit(measure(int(sys.argv[1]) if len(sys.argv) > 1 else 9))
