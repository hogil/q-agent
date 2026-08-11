#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""v46 — 현재 디자인(html/AX_Award_지원서.html) 내용을 v45 방식의 진짜 docx 로 낸다.

왜 이렇게 하나
  v45 는 python-docx 로 Word 표를 직접 짜서 만들었다(§3 규격 그대로). 그 뒤 디자인이
  HTML 로 다시 쓰이면서 docx 쪽이 v45 에 멈춰 있었다. 파이프라인이 고장난 게 아니라
  새 내용을 되돌려 넣지 않았을 뿐이다. 이 스크립트가 그 자리를 잇는다.

  · 표 골격 · 여백 · 글꼴 · 열 너비는 v45 와 동일하게 §3 규격을 지킨다(build_docx 헬퍼 재사용).
  · `I. 개요` 는 **진짜 텍스트 표** 로 다시 짠다 — 실제로 고쳐 넣는 칸이 여기라서.
  · 절 내용은 flex·grid 로 짜여 Word 표로 재현이 안 되므로, HTML 의 해당 셀만 잘라
    고해상도 그림으로 넣는다(v45 도 그림을 셀에 넣었다).

폭이 12.5cm 인 이유
  HTML 은 페이지당 26.0cm 를 쓰는데 사내 양식 여백(위 3 / 아래 2.54)은 24.16cm 뿐이다.
  1:1 로 옮기면 4페이지가 넘친다. 5장 안에 앉히려면 이 폭이 상한이다 — 계산은 fit_width().

사용: python build_docx_v46.py [버전번호]
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm

import build_docx as B          # 헬퍼·규격 재사용 (import 시 부작용 없음)

HERE = Path(__file__).parent
HTML = HERE / "html" / "AX_Award_지원서.html"
FIG = HERE / "out" / "fig_v46"
USABLE = B.PAGE_H - B.M_TOP - B.M_BOTTOM          # 24.16 cm
SHOT_W = 516                                      # HTML 내용 셀 폭(px)


# ----------------------------------------------------------------- 1) 잘라내기
async def _shoot():
    from playwright.async_api import async_playwright
    FIG.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 900, "height": 1200}, device_scale_factor=4)
        await pg.goto(HTML.resolve().as_uri())
        await pg.wait_for_timeout(900)            # 내장 폰트 로드

        # 각 페이지의 [라벨 | 내용] 행에서 내용 td 만 집는다. 개요 표(5행)는 텍스트로 다시 짜므로 제외.
        cells = await pg.evaluate("""() => {
          const out = [];
          document.querySelectorAll('section.page').forEach((s, pi) => {
            s.querySelectorAll('table').forEach((t) => {
              [...t.querySelectorAll(':scope > tbody > tr')].forEach((tr) => {
                const td = [...tr.children];
                if (td.length !== 2) return;
                const w = td[1].getBoundingClientRect().width;
                if (w < 400) return;                       // 개요 표의 좁은 칸 배제
                const h = td[1].getBoundingClientRect().height;
                if (h < 120) return;                       // 개요 행(22~38px) 배제
                td[1].setAttribute('data-shot', `p${pi + 1}_${out.length}`);
                out.push({ id: `p${pi + 1}_${out.length}`, page: pi + 1,
                           label: td[0].innerText.replace(/\\s+/g, ' ').trim(),
                           w: Math.round(w), h: Math.round(h) });
              });
            });
          });
          return out;
        }""")

        # 개요 표 값도 같이 뽑는다 — 텍스트 표로 다시 짜기 위해
        overview = await pg.evaluate("""() => {
          const t = document.querySelector('section.page table');
          return [...t.querySelectorAll(':scope > tbody > tr')].slice(1)
                 .map(tr => [...tr.children].map(td => td.innerText.replace(/\\s+/g,' ').trim()));
        }""")

        for c in cells:
            el = await pg.query_selector(f'[data-shot="{c["id"]}"]')
            await el.screenshot(path=str(FIG / f'{c["id"]}.png'))
        await b.close()
        return cells, overview


# ----------------------------------------------------------------- 2) 폭 계산
def fit_width(cells) -> float:
    """5장 안에 앉는 그림 폭(cm). 페이지마다 그림 외 고정 높이를 빼고 남는 만큼으로 역산."""
    overhead = {1: 4.60, 2: 0.30, 3: 0.80, 4: 0.30, 5: 1.00}   # 제목·개요표·절 머리행·1pt 문단
    limit = B.COL_R - 0.25
    for page in sorted({c["page"] for c in cells}):
        px = sum(c["h"] for c in cells if c["page"] == page)
        limit = min(limit, (USABLE - overhead[page]) * SHOT_W / px)
    return round(limit - 0.05, 2)        # 반올림 여유


# ----------------------------------------------------------------- 3) 조립
def put_image(cell, png: Path, w_cm: float):
    par = cell.paragraphs[0]
    B.tighten(par)
    par.alignment = WD_ALIGN_PARAGRAPH.CENTER
    par.add_run().add_picture(str(png), width=Cm(w_cm))


def content_row(doc, label, png, w_cm, header=None, h_cm=None):
    rows = 2 if header else 1
    t = B.new_table(doc, rows, 2, [B.COL_L, B.COL_R])
    r = 0
    if header:
        B.section_row(t, 0, header, 2)
        B.set_h(t.rows[0], 0.6)
        r = 1
    B.label_cell(t.cell(r, 0), label)
    t.cell(r, 0).vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    put_image(t.cell(r, 1), png, w_cm)
    if h_cm:                       # 테두리를 아래 여백까지 끌어 v45 처럼 프레임이 닫히게 한다
        B.set_h(t.rows[r], h_cm)
    return t


def build(version: int) -> Path:
    cells, overview = asyncio.run(_shoot())
    W = fit_width(cells)
    print(f"  그림 폭 {W} cm  (셀 {B.COL_R} cm)")

    doc = B.Document()
    s = doc.sections[0]
    s.page_width, s.page_height = Cm(B.PAGE_W), Cm(B.PAGE_H)
    s.top_margin, s.bottom_margin = Cm(B.M_TOP), Cm(B.M_BOTTOM)
    s.left_margin, s.right_margin = Cm(B.M_LEFT), Cm(B.M_RIGHT)

    # 제목
    # write() 의 4번째 자리는 색이다 — 밑줄은 style_run 으로 직접 건다(§3 제목: 진하게+밑줄)
    p = doc.paragraphs[0] if doc.paragraphs else doc.add_paragraph()
    B.tighten(p, after=4)
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    B.style_run(p.add_run("AX Award 지원서"), B.SZ_TITLE, bold=True, underline=True)

    # I. 개요 — 진짜 텍스트 표 (여기가 실제로 고쳐 넣는 칸이다)
    t0 = B.new_table(doc, 1 + len(overview), 5, B.GRID_P1)
    B.section_row(t0, 0, "I. 개요", 5)
    B.set_h(t0.rows[0], 0.23)
    for i, row in enumerate(overview, start=1):
        cs = t0.rows[i].cells
        if len(row) == 4:                                   # 팀/그룹 | 값 | 대표자 | 값
            B.label_cell(cs[0], row[0]); cs[1].merge(cs[2])
            B.write(cs[1].paragraphs[0], (row[1], B.SZ_BODY))
            B.label_cell(cs[3], row[2])
            B.write(cs[4].paragraphs[0], (row[3], B.SZ_BODY))
        else:                                               # 라벨 | 값
            B.label_cell(cs[0], row[0])
            cs[1].merge(cs[4])
            B.write(cs[1].paragraphs[0], (row[1], B.SZ_BODY))
        for c in cs:
            c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER

    by_page: dict[int, list] = {}
    for c in cells:
        by_page.setdefault(c["page"], []).append(c)

    HEAD = {1: "II. Process", 3: "III. Tech"}
    OVERHEAD = {1: 4.60, 2: 0.30, 3: 0.80, 4: 0.30, 5: 1.00}
    SLACK = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    for page in sorted(by_page):
        if page > 1:
            B.page_break(doc)
        # 남는 높이를 그림 높이 비율대로 나눠 행에 준다 — 표가 아래 여백까지 닿는다
        # OVERHEAD 는 추정치라 그대로 쓰면 한 장이 밀린다(v46 1차: 6장). 안전분 SLACK 을 뺀다.
        room = USABLE - OVERHEAD[page] - SLACK
        px_tot = sum(c["h"] for c in by_page[page])
        for i, c in enumerate(by_page[page]):
            if page > 1 and i:
                B.tiny_par(doc)
            head = HEAD.get(page) if i == 0 else None
            # 5 페이지 두 번째 칸은 경영효과 머리행을 앞에 단다
            if page == 5 and i == 1:
                head = "IIII. 경영효과"
            h = round(room * c["h"] / px_tot - (0.6 if head else 0) - 0.05, 2)
            content_row(doc, c["label"], FIG / f'{c["id"]}.png', W, head, h)
    B.tiny_par(doc)

    B.OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = B.OUT_DIR / f"AX_Award_지원서_Q-Agent_v{version}.docx"
    doc.save(path)
    return path


if __name__ == "__main__":
    print(f"OK {build(int(sys.argv[1]) if len(sys.argv) > 1 else 46)}")
