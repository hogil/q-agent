#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""AX Award 지원서 .docx 생성기.

규격은 ax_award/CLAUDE.md §3·§4, 페이지 예산은 §4-B, 본문은 content.py.
페이지마다 표를 따로 만든다 — 중첩 표가 든 행은 Word 가 페이지 분할을 못 하기 때문이다.

사용: python build_docx.py [버전번호]
"""
from __future__ import annotations

import sys
from pathlib import Path

from docx import Document
from docx.enum.table import WD_ROW_HEIGHT_RULE, WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor

import content as C

# ----------------------------------------------------------------- 규격 (§3)
FONT = "바탕체"
SZ_TITLE, SZ_BIG, SZ_MID, SZ_BODY = 22, 12, 11, 10

PAGE_W, PAGE_H = 21.0, 29.7
M_TOP, M_BOTTOM, M_LEFT, M_RIGHT = 3.0, 2.54, 2.54, 2.54

TBL_W, COL_L, COL_R = 15.99, 2.24, 13.75
GRID_P1 = [2.24, 2.24, 3.515, 2.24, 5.755]
INNER_W = 13.3

# 페이지 예산 (§4-B) — 이 값을 넘기면 반드시 빈 페이지가 생긴다
# H_TECH2 는 23.9 였다. 최소 높이가 내용보다 커서 아무리 줄여도 행이 안 줄고, 표 뒤 문단이
# 다음 장으로 밀려 빈 페이지가 생겼다(v34~v37). 내용 높이로 앉게 낮춘다.
H_PROBLEM, H_REDESIGN, H_TECH1, H_TECH2, H_EFFECT = 16.9, 23.8, 23.2, 23.0, 23.1

RED, RED_FILL, GRAY_FILL, BLUE_FILL = "C00000", "FBE4E4", "F2F2F2", "E8EEF7"
NAVY = "1F4E79"      # 수치 강조는 파랑으로 — 붉은색은 '대체 구간' 전용 신호로 남긴다
OUT_DIR = Path(__file__).parent / "out"
FIG_DIR = OUT_DIR / "fig"


# ----------------------------------------------------------------- 헬퍼
def style_run(run, size=SZ_BODY, bold=False, underline=False, color=None):
    """한글은 w:eastAsia 를 직접 넣어야 글꼴이 적용된다 (CLAUDE.md §5-2)."""
    run.font.name = FONT
    run.font.size = Pt(size)
    run.bold = bold
    run.underline = underline
    if color:
        run.font.color.rgb = RGBColor.from_string(color)
    rPr = run._element.get_or_add_rPr()
    rFonts = rPr.find(qn("w:rFonts"))
    if rFonts is None:
        rFonts = OxmlElement("w:rFonts")
        rPr.insert(0, rFonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rFonts.set(qn(attr), FONT)


def tighten(par, before=0, after=0, line=1.0, left=0.0, hanging=0.0):
    pf = par.paragraph_format
    pf.space_before, pf.space_after = Pt(before), Pt(after)
    pf.line_spacing = line
    pf.line_spacing_rule = WD_LINE_SPACING.MULTIPLE
    if left:
        pf.left_indent = Cm(left)
    if hanging:
        pf.first_line_indent = Cm(-hanging)


def write(par, *chunks, align=None, before=0, after=0, line=1.0, left=0.0, hanging=0.0):
    tighten(par, before, after, line, left, hanging)
    if align is not None:
        par.alignment = align
    for ch in chunks:
        if isinstance(ch, str):
            ch = (ch,)
        style_run(par.add_run(ch[0]),
                  ch[1] if len(ch) > 1 else SZ_BODY,
                  ch[2] if len(ch) > 2 else False,
                  color=ch[3] if len(ch) > 3 else None)
    return par


def shade(cell, fill):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    cell._tc.get_or_add_tcPr().append(shd)


def shade_par(par, fill=GRAY_FILL):
    """문단 한 줄에 옅은 음영. w:shd 는 pPr 안에서 spacing/ind/jc 앞에 와야 한다."""
    pPr = par._p.get_or_add_pPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear")
    shd.set(qn("w:color"), "auto")
    shd.set(qn("w:fill"), fill)
    for tag in ("w:tabs", "w:spacing", "w:ind", "w:jc", "w:rPr"):
        anchor = pPr.find(qn(tag))
        if anchor is not None:
            anchor.addprevious(shd)
            return
    pPr.append(shd)


def par_left_bar(par, color=NAVY, sz=18, space=6):
    """문단 왼쪽 세로 괘선. 연속 문단에 같은 값을 주면 한 줄로 이어진다.

    w:pBdr 는 CT_PPr 순서상 w:shd 앞에 와야 한다 — 뒤에 넣으면 Word 가 문단을 통째로 버린다.
    """
    pPr = par._p.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr")
    el = OxmlElement("w:left")
    el.set(qn("w:val"), "single")
    el.set(qn("w:sz"), str(sz))
    el.set(qn("w:space"), str(space))
    el.set(qn("w:color"), color)
    bdr.append(el)
    for tag in ("w:shd", "w:tabs", "w:spacing", "w:ind", "w:jc", "w:rPr"):
        anchor = pPr.find(qn(tag))
        if anchor is not None:
            anchor.addprevious(bdr)
            return
    pPr.append(bdr)


def cell_border(cell, color=RED, sz=12, sides=("top", "left", "bottom", "right")):
    tcPr = cell._tc.get_or_add_tcPr()
    borders = tcPr.find(qn("w:tcBorders"))
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tcPr.append(borders)
    for side in sides:
        el = OxmlElement(f"w:{side}")
        el.set(qn("w:val"), "single")
        el.set(qn("w:sz"), str(sz))
        el.set(qn("w:space"), "0")
        el.set(qn("w:color"), color)
        borders.append(el)


def cell_margins(table, side_cm):
    """표 전체의 셀 좌우 여백. 코어 스트립처럼 칸이 좁은 도해에서만 줄인다."""
    tblPr = table._tbl.tblPr
    mar = tblPr.find(qn("w:tblCellMar"))
    if mar is None:
        mar = OxmlElement("w:tblCellMar")
        tblPr.append(mar)
    for side in ("left", "right"):
        el = mar.find(qn(f"w:{side}"))
        if el is None:
            el = OxmlElement(f"w:{side}")
            mar.append(el)
        el.set(qn("w:w"), str(int(side_cm * 566.9291)))
        el.set(qn("w:type"), "dxa")


def fix_table(table, total_cm, col_cms):
    table.autofit = False
    tblPr = table._tbl.tblPr
    for tag, attrs in (("w:tblW", {"w:type": "dxa", "w:w": str(int(total_cm * 566.9291))}),
                       ("w:tblLayout", {"w:type": "fixed"})):
        el = tblPr.find(qn(tag))
        if el is None:
            el = OxmlElement(tag)
            tblPr.append(el)
        for k, v in attrs.items():
            el.set(qn(k), v)
    grid = table._tbl.find(qn("w:tblGrid"))
    if grid is not None:
        for gc, w in zip(grid.findall(qn("w:gridCol")), col_cms):
            gc.set(qn("w:w"), str(int(w * 566.9291)))
    for row in table.rows:
        for idx, cell in enumerate(row.cells):
            if idx < len(col_cms):
                cell.width = Cm(col_cms[idx])


def set_h(row, cm):
    row.height_rule = WD_ROW_HEIGHT_RULE.AT_LEAST
    row.height = Cm(cm)


def page_break(doc):
    """표와 표 사이에는 문단이 있어야 두 표가 하나로 합쳐지지 않는다.

    페이지 나눔은 run 의 break 가 아니라 문단의 pageBreakBefore 로 건다.
    break run 은 문단이 현재 페이지에 앉을 자리가 없으면 다음 장으로 밀린 뒤 거기서
    또 끊어 **백지 한 장**을 만든다 (v10 의 p7). pageBreakBefore 는 그 사고가 없다.

    문단 부호까지 1pt 로 눌러야 한다. 안 그러면 Normal 10pt 가 줄 높이를 잡아
    새 장 상단을 0.35cm 먹고, 그만큼 뒤 표(23.9cm)가 또 밀린다 (v11 의 p5·p8).
    """
    tiny_par(doc, brk=True)


def tiny_par(doc, brk=False):
    """높이 1pt 짜리 문단. 표 뒤에 문단이 반드시 하나 붙으므로 그것도 1pt 여야 한다."""
    p = doc.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = pf.space_after = Pt(0)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(1)
    pf.page_break_before = brk
    style_run(p.add_run(), 1)
    pPr = p._p.get_or_add_pPr()
    rPr = pPr.find(qn("w:rPr"))
    if rPr is None:
        rPr = OxmlElement("w:rPr")
        pPr.append(rPr)
    for tag in ("w:sz", "w:szCs"):
        el = OxmlElement(tag)
        el.set(qn("w:val"), "2")
        rPr.append(el)


def label_cell(cell, text, size=SZ_MID, align=WD_ALIGN_PARAGRAPH.CENTER):
    """'\\n' 은 쓰지 않는다 — run.text 대입이 run 내용을 갈아치우므로 별도 run 으로 줄바꿈."""
    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    par = cell.paragraphs[0]
    tighten(par)
    par.alignment = align
    for i, line in enumerate(text.split("\n")):
        if i:
            br = par.add_run()
            style_run(br, size, bold=True)
            br.add_break()
        style_run(par.add_run(line), size, bold=True)


def section_row(table, r, text, cols):
    table.cell(r, 0).merge(table.cell(r, cols - 1))
    c = table.cell(r, 0)
    c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    shade(c, GRAY_FILL)
    write(c.paragraphs[0], (text, SZ_BIG, True))


class Cell:
    """내용 셀에 문단·표를 순서대로 쌓는 얇은 래퍼."""

    def __init__(self, cell):
        self.cell = cell
        cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
        self._first = cell.paragraphs[0]

    def _par(self):
        if self._first is not None:
            p, self._first = self._first, None
            return p
        return self.cell.add_paragraph()

    def head(self, text, before=6):
        write(self._par(), (text, SZ_BODY, True), before=before, after=2)

    def para(self, text, before=0, after=3, left=0.4, **kw):
        write(self._par(), text, before=before, after=after, left=left, **kw)

    def bullets(self, items, after=3):
        for t in items:
            write(self._par(), "- " + t, after=after, left=0.75, hanging=0.35)

    def bullet_rich(self, *chunks, after=3):
        """한 불릿 안에서 일부만 굵게 쓸 때. chunks 는 write() 와 같은 형식."""
        return write(self._par(), *chunks, after=after, left=0.75, hanging=0.35)

    def note(self, text, color=RED, align=WD_ALIGN_PARAGRAPH.CENTER, before=3, after=5):
        write(self._par(), (text, SZ_BODY, False, color), align=align, before=before, after=after)

    def image(self, name, width_cm=INNER_W, before=2, after=3):
        """figures.py 가 만든 인포그래픽 PNG 를 셀에 넣는다.

        표만으로 지면을 채우면 심사위원 눈이 안 간다. 도해·비교 막대·게이지는
        그림으로 넣는다. 파일이 없으면 조용히 건너뛴다(빌드를 멈추지 않는다).
        """
        path = FIG_DIR / f"{name}.png"
        if not path.exists():
            return None
        par = self._par()
        tighten(par, before, after)
        par.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = par.add_run()
        run.add_picture(str(path), width=Cm(width_cm))
        return par

    def mono(self, lines, before=2, after=3, left=0.4, size=9, fill=None, bar=None):
        """ASCII 도해. 바탕체는 고정폭이라 자리가 맞는다.

        fill·bar 를 주면 블록이 문단 음영 + 왼쪽 세로 괘선으로 감싸인다(10회차) —
        컬러 도해 밑에 붙어 '그림에 딸린 잔글씨'로 눌리던 것을 막는다.
        """
        for i, ln in enumerate(lines):
            p = self._par()
            tighten(p, before if i == 0 else 0,
                    after if i == len(lines) - 1 else 0, left=left)
            if bar:
                par_left_bar(p, bar)
            if fill:
                shade_par(p, fill)
            style_run(p.add_run(ln.replace(" ", " ")), size)

    def table(self, cols_cm, header, rows, head_fill=GRAY_FILL, label_first=True, row_h=None):
        n = len(rows) + (1 if header else 0)
        tbl = self.cell.add_table(rows=n, cols=len(cols_cm))
        tbl.style = "Table Grid"
        fix_table(tbl, sum(cols_cm), cols_cm)
        r0 = 0
        if header:
            for i, h in enumerate(header):
                c = tbl.cell(0, i)
                c.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                shade(c, head_fill)
                write(c.paragraphs[0], (h, SZ_BODY, True), align=WD_ALIGN_PARAGRAPH.CENTER)
            set_h(tbl.rows[0], 0.48)
            r0 = 1
        for ri, row in enumerate(rows):
            for ci, txt in enumerate(row):
                c = tbl.cell(r0 + ri, ci)
                if ci == 0 and label_first:
                    label_cell(c, txt, SZ_BODY)
                elif isinstance(txt, list):   # ["굵게", "보통"] — 앞 조각만 굵게
                    write(c.paragraphs[0], (txt[0], SZ_BODY, True), *txt[1:])
                else:
                    write(c.paragraphs[0], txt)
            if row_h:
                set_h(tbl.rows[r0 + ri], row_h)
        self._first = None
        return tbl

    def callout(self, lines):
        """강조 상자 — 남색 테두리 1행 1열 중첩표 (9회차, SPREAD_BOX 용).

        테두리는 남색이다 — p2 상단에 붉은색이 이미 세 갈래(CORE_FLOW 헤더·※ 문구·
        대체 화살표)라 네 번째 붉은 요소는 강조 위계를 무너뜨린다.
        1행 10pt 굵게, 2행부터 9pt.
        """
        tbl = self.cell.add_table(rows=1, cols=1)
        tbl.style = "Table Grid"
        fix_table(tbl, INNER_W, [INNER_W])
        cc = tbl.cell(0, 0)
        cell_border(cc, "1F3864", 12)
        shade(cc, "F2F4F8")
        for i, ln in enumerate(lines):
            p = cc.paragraphs[0] if i == 0 else cc.add_paragraph()
            if i == 0:
                write(p, (ln, SZ_BODY, True), before=2, after=1)
            else:
                write(p, (ln, 9, False, "44506A"), before=0,
                      after=2 if i == len(lines) - 1 else 1)
        self._first = None
        return tbl


# ----------------------------------------------------------------- 페이지별 본문
def page1_problem(cell):
    """9회차 : p1 은 AT_LEAST 최소 높이라 셀 안 백지 5.29cm 가 남던 '채우는 페이지'다.
    표·불릿·문단을 그림 3종(alternatives·burden·readiness)으로 바꿔 백지를 채운다.
    그림이 없으면(figures.py 미실행) 각 자리는 표·불릿·문단 폴백으로 돌아간다."""
    c = Cell(cell)
    c.head("1. 현행 업무 — 불량 하나를 판단하는 데 네 가지가 반복된다", before=0)
    c.image("problem_four", before=1, after=3)   # 카드 4칸 + 계측 지점 (FOUR_PROBLEMS 배선)

    c.head("2. 기존 대안으로는 해결되지 않는다")
    if c.image("alternatives", before=1, after=3) is None:
        at = c.table([3.3, INNER_W - 3.3], ["대안", "왜 부족한가"], C.ALTERNATIVES)
        for r in range(1, len(C.ALTERNATIVES) + 1):
            shade(at.cell(r, 0), GRAY_FILL)

    c.head("3. 현업 관점의 중요도 — 상시·대량 업무이고, 오판 비용이 크다")
    if c.image("burden", before=1, after=3) is None:
        for item in C.IMPORTANCE:       # 리스트면 조각별 서식(굵게), 문자열이면 그대로
            if isinstance(item, list):
                c.bullet_rich("- " + item[0], *item[1:])
            else:
                c.bullets([item])

    c.head("4. 지금 시작해야 하는 이유")
    if c.image("readiness", before=1, after=0) is None:
        c.para(C.WHY_NOW, after=0)


def hairline(cell):
    """표와 표 사이를 잇는 2pt 문단. 없으면 Word 가 두 표를 하나로 합친다."""
    p = cell.add_paragraph()
    pf = p.paragraph_format
    pf.space_before = pf.space_after = Pt(0)
    pf.line_spacing_rule = WD_LINE_SPACING.EXACTLY
    pf.line_spacing = Pt(2)
    style_run(p.add_run(), 2)


def page2_redesign(cell):
    c = Cell(cell)
    # 설비명에 하이픈은 없다 (CLAUDE.md §9-2B) — 3·4페이지와 표기를 맞춘다
    c.head("1. 대상 E2E Process — 코어는 하나, 입구는 둘 (예시 : PHOD03 CD 급등)", before=0)

    ent = cell.add_table(rows=1, cols=2)
    ent.style = "Table Grid"
    fix_table(ent, INNER_W, [INNER_W / 2] * 2)
    for i, t in enumerate(C.ENTRIES):     # 칠은 빨강(대체 구간)·회색(구조) 둘로만 쓴다
        label_cell(ent.cell(0, i), t, SZ_BODY)
    set_h(ent.rows[0], 0.48)

    hairline(cell)

    # 위 행은 코어 단계, 아래 행은 그 단계가 대신하는 업무 — 붉은 띠가 세로로 이어진다
    strip = cell.add_table(rows=2, cols=6)
    strip.style = "Table Grid"
    # 칸마다 '→' 가 붙어 폭이 늘었다 — 셀 좌우 여백을 0.19→0.10 으로 줄여 13.3 안에 넣는다.
    cell_margins(strip, 0.10)
    fix_table(strip, INNER_W, [2.10, 3.00, 2.25, 2.05, 1.85, 2.05])
    for i, name in enumerate(C.CORE_FLOW):
        cc = strip.cell(0, i)
        label_cell(cc, name, SZ_BODY)
        if C.CORE_RED[i]:
            shade(cc, RED_FILL)
            cell_border(cc, RED, 12)
    for i, stage in enumerate(C.CORE_STAGES):
        cc = strip.cell(1, i)
        cc.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        write(cc.paragraphs[0], stage, align=WD_ALIGN_PARAGRAPH.CENTER)
        if C.CORE_RED[i]:
            shade(cc, RED_FILL)
            cell_border(cc, RED, 12)
    set_h(strip.rows[0], 0.72)
    set_h(strip.rows[1], 0.40)

    c2 = Cell.__new__(Cell)
    c2.cell, c2._first = cell, None
    # '붉은 칸'은 굵게로만(9회차) — 붉은색은 '사람 일을 대신하는 자리'(스트립·화살표) 전용이다
    write(c2._par(), C.CORE_NOTE[0], (C.CORE_NOTE[1], SZ_BODY, True), C.CORE_NOTE[2],
          align=WD_ALIGN_PARAGRAPH.LEFT, before=3, after=5)

    # AS-IS/TO-BE 6행 표 → 업무 워크플로우 도해. 단계·소요·대체를 한 그림에서 읽는다.
    # 폭을 줄이면 높이도 비례로 준다 — 12.6cm 폭에서 6.8cm (원본 13.3 × 7.15)
    c2.image("workflow_e2e", width_cm=12.6, before=1, after=2)
    # WORKFLOW_NOTE 는 뺐다(9회차 예비 컷 ① — p2 행이 최소 높이를 넘겨 성장했다)

    c2.head("2. 조치는 다섯 단계로 올라간다 — 마지막 단계가 자동조치다", before=3)
    c2.image("action_ladder", before=1, after=3)   # 표 6행 → ●○ 게이지 5칸. 주석은 그림 캡션에

    c2.head("3. 단일 기능 개선이 아니다 — 시작·중간·끝을 모두 바꿨다", before=3)
    # 불릿 두 줄(NOT_SINGLE)을 닫힌 고리 도해로 올린다(10회차). 배점 20점이 통째로 걸린 칸의
    # 근거가 산문 두 줄이면 '조사만 자동화한 단일 기능'이라는 읽기가 그대로 성립한다.
    # 그림이 없으면 옛 불릿으로 돌아간다 — 이 칸이 비면 안 된다.
    if c2.image("loop", before=1, after=2) is None:
        c2.bullets(C.NOT_SINGLE)
    c2.head("4. 현업 활용과 확산 — 현업 노하우가 등록되어야 자라는 구조다", before=3)
    c2.image("spread", before=1, after=2)          # 4행 3열 표 → 8분기 시간축
    # 확산 20점의 정답(표준안·통과 조건·현업 몫)을 산문에서 꺼내 상자에 올린다(9회차)
    c2.callout(C.SPREAD_BOX)
    c2.para(C.SPREAD_TOUCH, before=3, after=2)


def page3_tech1(cell):
    c = Cell(cell)
    c.head("1. 왜 AI Agent Orchestration 이어야 하는가", before=0)
    c.bullets(C.WHY_AGENT)

    c.head("2. 오케스트레이션 구성 — 마스터 Agent 가 전문 Agent 와 사내 시스템을 부린다")
    # 표 5행 → 층별 모델 파이프라인 도해. 칩 라벨(모델 선택 근거)이 읽히게 전폭으로 넣는다.
    c.image("orchestration", before=1, after=2)
    # 근거 사슬 — 접두 트리(9회차). EVIDENCE_NOTE 는 트리 설명 열에 흡수돼 삭제됐다.
    # 10회차 : 문서에서 가장 강한 논거(유사도는 후보만 좁히고 확정은 키 조회가 한다)가
    # 컬러 도해 밑 잔글씨로 눌려 있었다 — 라벨 한 줄 + 음영 + 남색 세로 괘선으로 층을 올린다.
    # 11회차 : 8.5→10pt — 문서에서 가장 강한 논거가 컬러 도해 밑 잔글씨로 눌려 있었다.
    # 줄 수 증가 0 의 서식 변경이라 비용 없음.
    lab = write(c._par(), ("근거 사슬 — LLM 이 지어낸 자리가 없다", 10, True, NAVY),
                before=2, after=0, left=0.4)
    par_left_bar(lab, NAVY)
    shade_par(lab, GRAY_FILL)
    c.mono(C.EVIDENCE_CHAIN, size=9, left=0.4, before=0, after=4,
           fill=GRAY_FILL, bar=NAVY)
    # 세 덩어리가 9줄 통짜 회색으로 붙는다 — 들여쓰기와 굵은 라벨로 층을 나눈다
    c.para(C.PROTO_NOTE, before=2, after=3, left=0.8)
    lab, sep, rest = C.DESIGN_DECISIONS.partition(" : ")
    write(c._par(), (lab + sep, SZ_BODY, True), rest, after=3, left=0.4)

    c.head("3. 도구 구성의 근거 — 하나씩 붙여 답이 어떻게 달라지는지 비교했다")
    c.para(C.ABLATION_LEAD, after=2)
    # 6행 2열 표 → 가로 전폭 캐스케이드. 왼쪽 끝이 한 단씩 밀려 도구 누적이 배치로 보인다.
    c.image("ablation_cascade", before=1, after=0)
    # 11회차 : p3 하단 공백을 도구 8종 칩 띠로 닫는다 — 오케스트레이션 그림엔 전문 Agent
    # 4종만 보이고 실제 함수 이름이 없어 개념도로 읽혔다. p3 슬랙이 좁아 before=0 으로 최소화.
    c.image("tools", before=0, after=0)


def page4_tech2(cell):
    c = Cell(cell)
    c.head("4. 알고리즘 선택 근거", before=0)
    # 11회차 — ALGO_ROWS 표(지면 39%, 근거가 잔글씨에 묻힘)를 fig_algo_choice(밴드별
    # 채택+기각대안 카드)로 교체한다. 표 코드는 그림 미생성 시 폴백으로만 남긴다.
    if c.image("algo_choice", before=1, after=2) is None:
        # 열 재배분(9회차) — 좌열 2.4 에서 '문서·사례 검색'·'이미지 유사검색'이 두 줄로 접혔다.
        # 렌더 실측으로 3.05 확정(2.8 은 부족). 열 합은 INNER_W 그대로라 표 폭 규격은 불변.
        # 10회차 — 선택 열 3.55 에서 모델명이 하이픈 뒤로 쪼개졌다(PatchCore + WRN-/50-2,
        # PatchTST +/CUSUM/BOCPD, Qwen3-VL-/Embedding). 깨짐 수리 목적으로 3.55→4.30 만 넓히고
        # 0.75 를 근거 열에서 가져온다. 좌열 3.05 는 건드리지 않는다(9회차 버그 재발).
        # 셀 좌우 여백도 0.19→0.05 로 줄여 좁아진 근거 열의 줄 수 증가를 상쇄한다.
        # 4.10 은 가장 긴 선택 값('ReAct 루프 (LangGraph)' · 'PatchTST + CUSUM/BOCPD' 각 3.88cm)의
        # 최소 필요 폭이다 — 더 줄이면 다시 쪼개지고, 더 늘리면 근거 칸에서 줄이 는다(렌더 실측).
        # ※ 외곽 표(15.99 / 2.24 / 13.75)는 무접촉이다. 이 표는 내용 셀 안 중첩 표다.
        at4 = c.table([3.05, 4.10, INNER_W - 7.15], ["과제", "선택", "선택 근거"], C.ALGO_ROWS)
        cell_margins(at4, 0.05)
        for row in at4.rows:
            row.cells[0].vertical_alignment = WD_ALIGN_VERTICAL.TOP
            row.cells[1].vertical_alignment = WD_ALIGN_VERTICAL.TOP
            row.cells[2].vertical_alignment = WD_ALIGN_VERTICAL.TOP

    # 10회차 : 소제목·그림 안 제목·VERIFIER_NOTE 가 같은 말을 세 번 했다 — 한 줄로 합쳤다
    c.head("5. 그럴듯한 오답은 코드가 걸러낸다 — 다섯 관문", before=3)
    # 표 5행 → 게이트 파이프라인. 11.4cm 로 눌러 놓으면 관문 부제가 옆 칸을 침범한다 → 13.3cm.
    c.image("verifier_gate", before=1, after=2)
    c.para(C.VERIFIER_NOTE, before=0, after=2)   # 근거는 그림에 붙어야 증거가 된다

    c.head("6. 성능 지표와 배포 게이트", before=3)
    # 11회차 — 문서 유일의 실측치가 본문과 같은 크기 회색 줄에 묻혀 있었다. fig_metrics 로
    # 승격하고, 그림 미생성 시에만 기존 강조줄+불릿 폴백으로 돌아간다.
    if c.image("metrics", before=1, after=2) is None:
        rc = write(c._par(), C.METRICS_HEAD, (C.METRICS_KEY, SZ_BODY, True, NAVY), C.METRICS_TAIL,
                   after=3, left=0.4)
        shade_par(rc)
        c.bullets(C.METRICS)
    else:
        c.bullets(C.METRICS[1:], after=2)   # [0](0건 관리)은 그림이 이미 보여준다

    c.head("7. 알고리즘 개선을 위해 수행한 과정", before=3)
    # 11회차 — 검색 3층 분기(§9-4 원문)를 mono 트리로 세운다. 아래 불릿은 트리 트레일러
    # (색인 규모) + 남은 IMPROVE 2항(환각 발생원 제거·재학습).
    c.mono(C.SEARCH_LAYERS, size=9, left=0.4, before=0, after=2, fill=GRAY_FILL, bar=NAVY)
    c.bullets([C.SEARCH_LAYERS_NOTE] + C.IMPROVE, after=2)
    # §0-3 이 허용하는 선행 프로토타입 실측(10회차). §6 의 recall@10 강조 줄과는 소제목 하나·
    # 불릿 넷을 사이에 두고 떨어진다 — 같은 문장·같은 줄에 절대 놓지 않는다.
    # 11회차 : 내어쓰기 정렬 + '선행 프로토타입 실측' 어절만 굵게 세워 위 불릿의 연속처럼
    # 안 읽히게 한다. 수치는 큰 글자로 승격하지 않는다(§0-3 병치 금지).
    lead, _, rest = C.PROTO_EVAL.partition(" — ")
    write(c._par(), (lead, SZ_BODY, True), " — " + rest, before=2, after=0, left=0.4, hanging=0.4)


def page5_effect(cell):
    c = Cell(cell)
    write(c._par(), (C.EFFECT_NOTE, SZ_BODY, True), after=4)

    c.head("유형 효과 (정량)", before=0)
    c.image("effect_big", before=1, after=2)      # 표 4행 + 산출식 → 큰 숫자 3칸
    c.bullets(C.EFFECT_LINES, after=2)
    c.image("sensitivity", before=2, after=2)     # 민감도 표 5행 → 가로 막대

    c.head("무형 효과 (정성)", before=3)
    c.image("intangible", before=1, after=2)      # 5행 2열 표 → 낮은 띠 5칸

    c.head("선행 추진 실적 — 백지에서 시작하지 않는다", before=3)
    # 11회차 — 신규과제 BIZ 방어의 유일한 실측 수치가 표 셋째 행 3줄 줄글에 묻혀 있었다.
    # fig_prior 배지 띠로 교체. 그림 미생성 시에만 기존 표로 돌아간다.
    if c.image("prior", before=1, after=2) is None:
        # 좌열 2.2 에서 '선행 프로토타입'이 두 줄로 깨져 그 행만 높이가 튀었다 → 3.0 (10회차).
        # 2.6·2.9 로도 부족했다 — 바탕체는 어절 사이 공백까지 전각이라 8칸(2.82cm)이 필요하다.
        # 셀 여백을 0.05 로 줄여 안쪽 2.90cm 를 확보한다. 오른쪽 칸은 오히려 넓어진다.
        pw = c.table([3.0, INNER_W - 3.0], None, C.PRIOR_WORK)
        cell_margins(pw, 0.05)
    c.para(C.PRIOR_NOTE, before=2, after=0)

    c.head("검증 방법", before=3)
    # 11회차 — PRIOR_WORK → fig_prior 교체로 확보된 여유에 fig_verify_track 을 배선한다
    # (10회차 갱신 메모의 투입 조건 충족). 채점 주체(공정 담당 엔지니어)가 그림·불릿 양쪽에
    # 이제 들어 있다. 그림 미생성 시에만 불릿 폴백.
    if c.image("verify_track", before=1, after=2) is None:
        c.bullets(C.VERIFY_PLAN, after=2)


# ----------------------------------------------------------------- 조립
def new_table(doc, rows, cols, col_cms):
    t = doc.add_table(rows=rows, cols=cols)
    t.style = "Table Grid"
    fix_table(t, TBL_W, col_cms)
    return t


def build(version: int) -> Path:
    """10회차 지면 수지 — 기준은 measure.py 실측이지 추정이 아니다.

    v43 실측 : 5페이지 / 하단여유 p1 +2.48 · p2 +0.47 · p3 +2.04 · p4 +1.36 · p5 +0.23 (전부 OK).
    ※ p5 의 +0.23 은 표 뒤 1pt 문단 위치다 — 내용 셀 안에는 약 2.5cm 가 더 남아 있다.
      실제로 조이는 페이지는 p2(+0.47)와 p4(+1.36)다.
    ※ '5.49cm 초과' 진단은 AT_LEAST 행 높이를 상한으로 오독한 값이라 따르지 않는다.
      그에 딸린 컷(IMPORTANCE·WHY_NOW 축약)은 fig_burden·fig_readiness 가 그 상수를 읽지도
      않으므로 렌더가 1픽셀도 안 변하는 죽은 편집이다.
    집행 후 measure.py → render_check.py 로 (a) 페이지 5 (b) 하단여유 양수
    (c) ALGO 표 모델명 미분절 (d) PNG 재생성 반영을 눈으로 확인하기 전에는 완성 보고 금지(§0-6).
    초과 시 폴백 순서 : ① PROTO_EVAL 하드셋 열거 압축 ② ALGO 근거 칸 어절 축약
    ③ fig_loop 높이 축소 ④ fig_loop 철회 + NOT_SINGLE 불릿 원복.
    """
    doc = Document()

    normal = doc.styles["Normal"]
    normal.font.name = FONT
    normal.font.size = Pt(SZ_BODY)
    rpr = normal.element.get_or_add_rPr()
    rf = rpr.find(qn("w:rFonts"))
    if rf is None:
        rf = OxmlElement("w:rFonts")
        rpr.insert(0, rf)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        rf.set(qn(attr), FONT)

    sec = doc.sections[0]
    sec.page_width, sec.page_height = Cm(PAGE_W), Cm(PAGE_H)
    sec.top_margin, sec.bottom_margin = Cm(M_TOP), Cm(M_BOTTOM)
    sec.left_margin, sec.right_margin = Cm(M_LEFT), Cm(M_RIGHT)

    # ---- 1 페이지 : 개요 + 문제 정의
    title = doc.add_paragraph()
    write(title, ("AX Award 지원서", SZ_TITLE, True), align=WD_ALIGN_PARAGRAPH.CENTER, after=6)
    title.runs[0].underline = True

    t1 = new_table(doc, 8, 5, GRID_P1)
    section_row(t1, 0, "I. 개요", 5)
    set_h(t1.rows[0], 0.23)

    t1.cell(1, 1).merge(t1.cell(1, 4))
    label_cell(t1.cell(1, 0), "지원부문")
    t1.cell(1, 1).vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    write(t1.cell(1, 1).paragraphs[0], C.V_BUMUN)
    set_h(t1.rows[1], 0.23)

    t1.cell(2, 1).merge(t1.cell(2, 2))
    label_cell(t1.cell(2, 0), "팀/그룹")
    label_cell(t1.cell(2, 3), "대표자")
    for col, val in ((1, C.V_TEAM), (4, C.V_LEAD)):
        t1.cell(2, col).vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        write(t1.cell(2, col).paragraphs[0], val)
    set_h(t1.rows[2], 0.67)

    t1.cell(3, 1).merge(t1.cell(3, 4))
    label_cell(t1.cell(3, 0), "제목")
    t1.cell(3, 1).vertical_alignment = WD_ALIGN_VERTICAL.CENTER
    write(t1.cell(3, 1).paragraphs[0], (C.V_TITLE, SZ_BODY, True))
    set_h(t1.rows[3], 0.58)

    t1.cell(4, 2).merge(t1.cell(4, 4))
    t1.cell(5, 2).merge(t1.cell(5, 4))
    t1.cell(4, 0).merge(t1.cell(5, 0))
    label_cell(t1.cell(4, 0), "분류")
    label_cell(t1.cell(4, 1), "적용시점")
    label_cell(t1.cell(5, 1), "횡전개 범위")
    for r, val in ((4, C.V_WHEN), (5, C.V_SPREAD)):
        t1.cell(r, 2).vertical_alignment = WD_ALIGN_VERTICAL.CENTER
        write(t1.cell(r, 2).paragraphs[0], val)
    set_h(t1.rows[4], 0.58)
    set_h(t1.rows[5], 0.74)

    section_row(t1, 6, "II. Process", 5)
    set_h(t1.rows[6], 0.18)

    t1.cell(7, 1).merge(t1.cell(7, 4))
    label_cell(t1.cell(7, 0), "문제 정의")
    t1.cell(7, 0).vertical_alignment = WD_ALIGN_VERTICAL.TOP
    page1_problem(t1.cell(7, 1))
    set_h(t1.rows[7], H_PROBLEM)

    # ---- 2 페이지 : Process 재설계
    page_break(doc)
    t2 = new_table(doc, 1, 2, [COL_L, COL_R])
    label_cell(t2.cell(0, 0), "Process\n재설계")
    t2.cell(0, 0).vertical_alignment = WD_ALIGN_VERTICAL.TOP
    page2_redesign(t2.cell(0, 1))
    set_h(t2.rows[0], H_REDESIGN)

    # ---- 3 페이지 : Tech ①
    page_break(doc)
    t3 = new_table(doc, 2, 2, [COL_L, COL_R])
    section_row(t3, 0, "III. Tech", 2)
    set_h(t3.rows[0], 0.6)
    label_cell(t3.cell(1, 0), "기술적\n해결 방안")
    t3.cell(1, 0).vertical_alignment = WD_ALIGN_VERTICAL.TOP
    page3_tech1(t3.cell(1, 1))
    set_h(t3.rows[1], H_TECH1)

    # ---- 4 페이지 : Tech ②
    page_break(doc)
    t4 = new_table(doc, 1, 2, [COL_L, COL_R])
    label_cell(t4.cell(0, 0), "기술적\n해결 방안")
    t4.cell(0, 0).vertical_alignment = WD_ALIGN_VERTICAL.TOP
    page4_tech2(t4.cell(0, 1))
    set_h(t4.rows[0], H_TECH2)

    # ---- 5 페이지 : 경영효과
    page_break(doc)
    t5 = new_table(doc, 2, 2, [COL_L, COL_R])
    section_row(t5, 0, "IIII. 경영효과", 2)
    set_h(t5.rows[0], 0.7)
    label_cell(t5.cell(1, 0), "예상 성과")
    t5.cell(1, 0).vertical_alignment = WD_ALIGN_VERTICAL.TOP
    page5_effect(t5.cell(1, 1))
    set_h(t5.rows[1], H_EFFECT)
    tiny_par(doc)   # 문서 끝 표 뒤 문단 — 기본 10pt 로 두면 백지 한 장이 더 생긴다

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"AX_Award_지원서_Q-Agent_v{version}.docx"
    doc.save(path)
    return path


if __name__ == "__main__":
    print(f"OK {build(int(sys.argv[1]) if len(sys.argv) > 1 else 17)}")
