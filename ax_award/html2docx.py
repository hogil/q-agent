# -*- coding: utf-8 -*-
"""HTML 시안의 내용 칸을 Word 객체로 옮긴다 — 캡처가 아니라 진짜 표·진짜 글자로.

시안은 전부 인라인 스타일이라(외부 CSS·토큰 0) style 속성만 읽으면 레이아웃이 나온다.
  display:flex / display:grid  ->  1행 N열 중첩 표 (열 너비는 flex 비율·grid 트랙에서)
  background / border          ->  셀 음영 · 셀 테두리
  <b>, font-weight>=600        ->  굵게
  color:#...                   ->  글자색
  font-family ...monospace     ->  등폭(바탕체는 고정폭이라 자리가 맞는다)
  <br>                         ->  줄바꿈 run

글자 크기는 px * FS 로 환산한다. 96dpi 기준 1px = 0.75pt 지만, 사내 양식 여백이
HTML 보다 페이지당 1.84cm 좁아 그대로 옮기면 넘친다 — FS 로 전체를 함께 줄인다.
"""
from __future__ import annotations

import re

from bs4 import NavigableString, Tag
from docx.enum.table import WD_ALIGN_VERTICAL
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Cm

import build_docx as B

FS = 0.70                      # px -> pt 환산 계수 (build_docx_v47.py 에서 덮어쓴다)
MIN_PT, MAX_PT = 5.5, 14.0
MONO = "바탕체"                 # 바탕체는 고정폭이라 도해 자리가 맞는다


# ----------------------------------------------------------------- 스타일 파싱
def sty(el) -> dict:
    if not isinstance(el, Tag):
        return {}
    out = {}
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def px(v, default=None):
    m = re.match(r"^(-?\d+(?:\.\d+)?)px$", (v or "").strip())
    return float(m.group(1)) if m else default


def hex6(v):
    m = re.search(r"#([0-9A-Fa-f]{6})\b", v or "")
    return m.group(1).upper() if m else None


def pt(px_val) -> float:
    return max(MIN_PT, min(MAX_PT, round(px_val * FS, 1)))


def is_box(el) -> bool:
    """div/table 처럼 줄을 차지하는 요소인가."""
    return isinstance(el, Tag) and el.name in ("div", "table")


def boxes(el):
    return [c for c in el.children if is_box(c)]


def track_count(s: dict) -> list[float] | None:
    """grid-template-columns -> 열 비율. repeat(N,1fr) / '1fr auto 1fr' 둘 다."""
    g = s.get("grid-template-columns")
    if not g:
        return None
    m = re.match(r"repeat\((\d+)\s*,\s*([\d.]*)fr\)", g)
    if m:
        return [1.0] * int(m.group(1))
    out = []
    for tok in g.split():
        mm = re.match(r"([\d.]+)fr", tok)
        out.append(float(mm.group(1)) if mm else 0.45)   # auto 는 좁은 칸(화살표)
    return out or None


def flex_ratio(el) -> float:
    s = sty(el)
    f = s.get("flex", "")
    m = re.match(r"^([\d.]+)", f)
    if m:
        return max(float(m.group(1)), 0.15)
    if "none" in f:
        return 0.35
    return 1.0


# ----------------------------------------------------------------- 인라인 런
def inline_runs(el, inh):
    """(text, pt, bold, color, mono) 목록. <br> 은 ('\\n',) 로 표시."""
    out = []
    for node in el.children:
        if isinstance(node, NavigableString):
            t = re.sub(r"\s+", " ", str(node))
            if t.strip():
                out.append((t, inh["pt"], inh["bold"], inh["color"], inh["mono"]))
            continue
        if not isinstance(node, Tag):
            continue
        if node.name == "br":
            out.append(("\n", inh["pt"], inh["bold"], inh["color"], inh["mono"]))
            continue
        if is_box(node):                     # 블록이 섞여 있으면 상위에서 처리한다
            continue
        s = sty(node)
        nxt = dict(inh)
        if node.name in ("b", "strong"):
            nxt["bold"] = True
        fw = s.get("font-weight", "")
        if fw.isdigit():
            nxt["bold"] = int(fw) >= 600
        elif fw == "bold":
            nxt["bold"] = True
        if (p := px(s.get("font-size"))) is not None:
            nxt["pt"] = pt(p)
        if (c := hex6(s.get("color"))):
            nxt["color"] = c
        if "monospace" in s.get("font-family", ""):
            nxt["mono"] = True
        out += inline_runs(node, nxt)
    return out


def emit_runs(par, runs):
    for text, size, bold, color, mono in runs:
        if text == "\n":
            r = par.add_run()
            B.style_run(r, size, bold, color=color)
            r.add_break()
            continue
        r = par.add_run(text)
        B.style_run(r, size, bold, color=color)
        if mono:
            r.font.name = MONO


# ----------------------------------------------------------------- 블록 렌더
def own_text(el) -> bool:
    """자기 줄에 직접 쓸 글자가 있나(자식 블록 제외)."""
    return any(
        (isinstance(n, NavigableString) and n.strip())
        or (isinstance(n, Tag) and n.name not in ("div", "table") and n.get_text(strip=True))
        for n in el.children
    )


def decorate(cell, s):
    if (bg := hex6(s.get("background") or s.get("background-color"))):
        if bg not in ("FFFFFF",):
            B.shade(cell, bg)
    bd = hex6(s.get("border") or s.get("border-top") or "")
    if bd:
        B.cell_border(cell, bd, 6)


class Painter:
    """Word 셀 하나에 HTML 블록들을 순서대로 그린다."""

    def __init__(self, cell, width_cm):
        self.cell = cell
        self.w = width_cm
        cell.vertical_alignment = WD_ALIGN_VERTICAL.TOP
        self._first = cell.paragraphs[0]

    def par(self):
        if self._first is not None:
            p, self._first = self._first, None
            return p
        return self.cell.add_paragraph()

    def text(self, el, inh):
        runs = inline_runs(el, inh)
        if not runs:
            return
        p = self.par()
        s = sty(el)
        B.tighten(p, before=0, after=1, line=1.0)
        if s.get("text-align") == "center":
            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        if (bg := hex6(s.get("background"))) and bg != "FFFFFF":
            B.shade_par(p, bg)
        emit_runs(p, runs)

    def grid(self, el, ratios, inh):
        kids = boxes(el)
        if len(ratios) != len(kids):
            ratios = [flex_ratio(k) for k in kids]
        tot = sum(ratios) or 1
        cols = [max(self.w * r / tot, 0.6) for r in ratios]
        cols[-1] = self.w - sum(cols[:-1])
        tbl = self.cell.add_table(rows=1, cols=len(cols))
        B.fix_table(tbl, self.w, cols)
        B.cell_margins(tbl, 0.05)
        for i, (kid, cw) in enumerate(zip(kids, cols)):
            c = tbl.cell(0, i)
            decorate(c, sty(kid))
            Painter(c, cw - 0.12).block(kid, inh)
        self._first = None
        return tbl

    def html_table(self, el, inh):
        trs = el.find_all("tr")
        ncol = max(len(tr.find_all(["td", "th"])) for tr in trs)
        cols = [self.w / ncol] * ncol
        tbl = self.cell.add_table(rows=len(trs), cols=ncol)
        tbl.style = "Table Grid"
        B.fix_table(tbl, self.w, cols)
        B.cell_margins(tbl, 0.06)
        for ri, tr in enumerate(trs):
            tds = tr.find_all(["td", "th"])
            for ci, td in enumerate(tds):
                if ci >= ncol:
                    break
                c = tbl.cell(ri, ci)
                decorate(c, sty(td))
                Painter(c, cols[ci] - 0.14).block(td, inh)
        self._first = None
        return tbl

    def block(self, el, inh=None):
        inh = inh or {"pt": pt(10), "bold": False, "color": None, "mono": False}
        s = sty(el)
        nxt = dict(inh)
        if (p := px(s.get("font-size"))) is not None:
            nxt["pt"] = pt(p)
        if (c := hex6(s.get("color"))):
            nxt["color"] = c
        fw = s.get("font-weight", "")
        if fw.isdigit():
            nxt["bold"] = int(fw) >= 600
        if "monospace" in s.get("font-family", ""):
            nxt["mono"] = True

        kids = boxes(el)
        if not kids:
            self.text(el, nxt)
            return

        if own_text(el):                       # 블록과 글자가 섞였으면 글자 먼저
            self.text(el, nxt)

        disp = s.get("display", "")
        if disp == "grid" and (r := track_count(s)) and len(kids) >= 2:
            self.grid(el, r, nxt)
            return
        if disp == "flex" and len(kids) >= 2:
            self.grid(el, [flex_ratio(k) for k in kids], nxt)
            return

        for kid in kids:                        # 세로로 쌓인다
            if kid.name == "table":
                self.html_table(kid, nxt)
                continue
            ks = sty(kid)
            if hex6(ks.get("background")) or hex6(ks.get("border")):
                tbl = self.cell.add_table(rows=1, cols=1)   # 배경·테두리는 1x1 표로 감싼다
                B.fix_table(tbl, self.w, [self.w])
                B.cell_margins(tbl, 0.08)
                decorate(tbl.cell(0, 0), ks)
                Painter(tbl.cell(0, 0), self.w - 0.2).block(kid, nxt)
                self._first = None
            else:
                self.block(kid, nxt)


def paint(cell, html_td, width_cm):
    Painter(cell, width_cm).block(html_td)
