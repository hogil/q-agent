#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""v48 — HTML 시안을 Word 도형·텍스트 상자로 그대로 옮긴다. 캡처 없음, 전부 편집 가능.

pptx 가 도형 266개를 전부 진짜 AutoShape 로 갖고 있듯이, Word 도 같은 DrawingML 도형을
쓴다. python-docx 에는 도형 API 가 없어서 Word COM 으로 직접 앉힌다.

  box  -> AddShape(둥근 사각형)   채우기·선만, 글자 없음
  text -> AddTextbox(투명)        글자만, 칸마다 run 단위로 크기·굵기·색·등폭 유지
  svg  -> AddPicture              스파크라인·웨이퍼 맵 6개를 SVG 벡터로 유지

배경과 글자를 다른 개체로 나눈 이유: 한 도형에 같이 넣으면 Word 의 줄바꿈이 브라우저와
어긋날 때 배경까지 따라 틀어진다. 배경은 좌표로 못 박고 글자만 흐르게 둔다.

좌표 변환
  HTML 내용 상자 (96,88)-(698,1071)px 를 사내 양식 여백 상자
  (좌 2.54 / 위 3.0 / 우 2.54 / 아래 2.54 cm) 안에 균등 배율로 앉힌다.
  1px = 0.75pt 지만 HTML 이 세로로 26.0cm 를 쓰고 양식은 24.16cm 뿐이라 s = 0.697pt/px.
  도형은 텍스트 단이 아니라 '페이지' 기준으로 놓으므로 여백 규격은 그대로 지켜진다.

사용: python build_docx_v48.py [버전번호] [boxes.json] [SVG폴더]

v49 에서 더한 것 — 세로 정렬(flex align-items) 반영, 넘치는 글상자는 글자를 자동
축소해 옆 칸을 침범하지 않게 했다(최대 3단, 0.78배까지).
"""
from __future__ import annotations

import json
import pathlib
import sys
import time

import win32com.client as win32

HERE = pathlib.Path(__file__).parent
BOXES = pathlib.Path(sys.argv[2]) if len(sys.argv) > 2 else HERE / "out" / "boxes.json"
SVGDIR = pathlib.Path(sys.argv[3]) if len(sys.argv) > 3 else HERE / "out" / "fig_v48"
OUTDIR = HERE / "out"

CM = 28.3464567                       # 1cm in points
M_L, M_T, M_R, M_B = 2.54, 3.0, 2.54, 2.54
PAGE_W_CM, PAGE_H_CM = 21.0, 29.7
SRC = dict(x0=96, y0=88, x1=698, y1=1071)          # HTML 내용 상자(px)

# Word 상수
WD_REL_PAGE = 1                       # wdRelativeHorizontal/VerticalPositionPage
WD_WRAP_NONE = 3
MSO_ROUNDED, MSO_RECT = 5, 1
MSO_TRUE, MSO_FALSE = -1, 0
WD_LINE_EXACT = 4
VANCHOR = {"top": 1, "middle": 3, "bottom": 4}   # msoAnchorTop/Middle/Bottom
ALIGN = {"left": 0, "center": 1, "right": 2, "start": 0, "end": 2}
PAD_X, PAD_Y = 0.0, 1.5          # 글상자 여유(pt). 좌우는 0 — 늘리면 옆 칸 글자와 겹친다
FONT_K = 0.955                   # Word 한글 폭이 브라우저보다 넓다. 줄바꿈이 어긋나 겹치는
                                 # 것을 막으려고 글자만 살짝 줄인다(상자 크기는 그대로).


def retry(fn, tries=8):
    """Word 는 개체를 몰아 만들면 RPC_E_CALL_REJECTED 로 튕긴다 — 잠깐 쉬고 다시 부른다."""
    for i in range(tries):
        try:
            return fn()
        except Exception as e:
            if "거부" not in str(e) and "0x80010001" not in str(e) and i == tries - 1:
                raise
            time.sleep(0.12 * (i + 1))
    raise RuntimeError("Word 가 계속 호출을 거부한다")


def bgr(rgb):
    r, g, b = rgb
    return (b << 16) | (g << 8) | r


def main(version: int):
    pages = json.loads(BOXES.read_text(encoding="utf-8"))

    # --- 좌표 변환 계수 ---
    dst_w = (PAGE_W_CM - M_L - M_R) * CM
    dst_h = (PAGE_H_CM - M_T - M_B) * CM
    src_w, src_h = SRC["x1"] - SRC["x0"], SRC["y1"] - SRC["y0"]
    s = min(dst_w / src_w, dst_h / src_h)
    off_x = M_L * CM + (dst_w - src_w * s) / 2
    off_y = M_T * CM
    X = lambda px: off_x + (px - SRC["x0"]) * s
    Y = lambda px: off_y + (px - SRC["y0"]) * s
    print(f"  배율 {s:.4f} pt/px  (1:1 이면 0.75)")

    word = win32.gencache.EnsureDispatch("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    word.ScreenUpdating = False
    doc = word.Documents.Add()
    try:
        ps = doc.Sections(1).PageSetup
        ps.PageWidth, ps.PageHeight = PAGE_W_CM * CM, PAGE_H_CM * CM
        ps.TopMargin, ps.BottomMargin = M_T * CM, M_B * CM
        ps.LeftMargin, ps.RightMargin = M_L * CM, M_R * CM

        # 페이지마다 1pt 문단 하나 — 도형을 걸 닻이다
        anchors = []
        rng = doc.Content
        rng.Text = "\r" * (len(pages) - 1)
        for i in range(len(pages)):
            p = doc.Paragraphs(i + 1)
            p.Range.Font.Size = 1
            p.SpaceBefore = p.SpaceAfter = 0
            p.LineSpacingRule = WD_LINE_EXACT
            p.LineSpacing = 1
            if i:
                p.PageBreakBefore = True
            anchors.append(p.Range)

        made = failed = 0
        stat = {"shrunk": 0, "nobound": 0}
        for pinfo, anc in zip(pages, anchors):
            for it in pinfo["items"]:
                try:
                  def make(it=it, anc=anc):
                    l, t = X(it["x"]), Y(it["y"])
                    w, h = max(it["w"] * s, 1.0), max(it["h"] * s, 1.0)

                    if it["kind"] == "svg":
                        vector = SVGDIR / it.get("asset", f'{it["id"]}.svg')
                        if not vector.exists():
                            return
                        sh = doc.Shapes.AddPicture(str(vector), False, True, l, t, w, h, anc)
                    elif it["kind"] == "box":
                        kind = MSO_ROUNDED if it.get("radius", 0) >= 2 else MSO_RECT
                        sh = doc.Shapes.AddShape(kind, l, t, w, h, anc)
                        if kind == MSO_ROUNDED:
                            try:      # 모서리 반경 — 짧은 변 대비 비율
                                sh.Adjustments[1] = min(
                                    it["radius"] / max(min(it["w"], it["h"]), 1), 0.5)
                            except Exception:
                                pass
                        if it.get("bg"):
                            sh.Fill.Visible = MSO_TRUE
                            sh.Fill.Solid()
                            sh.Fill.ForeColor.RGB = bgr(it["bg"])
                        else:
                            sh.Fill.Visible = MSO_FALSE
                        if it.get("bc"):
                            sh.Line.Visible = MSO_TRUE
                            sh.Line.ForeColor.RGB = bgr(it["bc"])
                            sh.Line.Weight = max(it.get("bw", 1) * s, 0.25)
                        else:
                            sh.Line.Visible = MSO_FALSE
                        if it.get("shadow"):
                            try:
                                sh.Shadow.Visible = MSO_TRUE
                                sh.Shadow.Transparency = 0.72
                            except Exception:
                                pass
                        sh.TextFrame.TextRange.Text = ""
                    else:                                   # text
                        # Word 글꼴 폭이 브라우저와 미세하게 달라 딱 맞는 상자는 글자를 자른다
                        # (I. 개'요' 가 잘렸다). 좌우 위아래로 여유를 준다 — 상자는 투명이라
                        # 겹쳐도 보이지 않는다.
                        l, t = l - PAD_X, t - PAD_Y
                        w, h = w + 2 * PAD_X, h + 2 * PAD_Y + 3
                        sh = doc.Shapes.AddTextbox(1, l, t, w, h, anc)
                        sh.Fill.Visible = MSO_FALSE
                        sh.Line.Visible = MSO_FALSE
                        tf = sh.TextFrame
                        tf.MarginLeft = tf.MarginRight = tf.MarginTop = tf.MarginBottom = 0
                        # 단어 하나짜리 상자는 줄바꿈을 끈다. 켜두면 좁은 칸에서 Word 가
                        # 'adapter' 를 'adapte/r' 로 쪼갠다 — 넘쳐도 투명 상자라 겹쳐 보이지 않는다.
                        raw_text = "".join(r.get("t", "") for r in it["runs"])
                        one_word = " " not in raw_text.strip() and "\n" not in raw_text
                        tf.WordWrap = not one_word
                        tf.AutoSize = False
                        runs = it["runs"]
                        text = "".join(r.get("t", "") for r in runs).replace("\n", "\v")
                        tr = tf.TextRange
                        tr.Text = text
                        pf = tr.ParagraphFormat
                        pf.SpaceBefore = pf.SpaceAfter = 0
                        pf.Alignment = ALIGN.get(it.get("align", "left"), 0)
                        if it.get("lh"):
                            pf.LineSpacingRule = WD_LINE_EXACT
                            pf.LineSpacing = it["lh"] * s
                        base = tr.Start
                        off = 0
                        for r in runs:
                            txt = r.get("t", "")
                            n = len(txt)
                            if not n:
                                continue
                            if txt != "\n":
                                sub = tr.Duplicate
                                sub.SetRange(base + off, base + off + n)
                                f = sub.Font
                                f.Size = max(r["size"] * s * FONT_K, 4)
                                f.Bold = MSO_TRUE if r.get("bold") else MSO_FALSE
                                f.Color = bgr(r["color"])
                                f.Name = "Consolas" if r.get("mono") else "Noto Sans KR"
                            off += n
                        # 세로 정렬
                        try:
                            sh.TextFrame2.VerticalAnchor = VANCHOR.get(
                                it.get("valign", "top"), 1)
                        except Exception:
                            pass
                        # 넘치면 글자를 줄인다. BoundHeight 는 고정 크기 상자에서 못 쓰므로
                        # AutoSize 를 잠깐 켜 Word 가 필요로 하는 높이를 재고 되돌린다.
                        try:
                            for _ in range(4):
                                tf.AutoSize = True
                                need = sh.Height
                                tf.AutoSize = False
                                sh.Width = w
                                sh.Height = h
                                if need <= h + 0.6:
                                    break
                                k = max(h / need, 0.86)
                                tr.Font.Size = max(tr.Font.Size * k, 4.0)
                                if it.get("lh"):
                                    pf.LineSpacing = max(pf.LineSpacing * k, 4.0)
                                stat["shrunk"] += 1
                            sh.Width = w
                            sh.Height = h
                        except Exception as ex:
                            stat["nobound"] += 1
                            if stat["nobound"] <= 2:
                                print(f"    높이 측정 불가: {ex}")
                    sh.RelativeHorizontalPosition = WD_REL_PAGE
                    sh.RelativeVerticalPosition = WD_REL_PAGE
                    sh.Left, sh.Top = l, t
                    sh.WrapFormat.Type = WD_WRAP_NONE
                    sh.WrapFormat.AllowOverlap = True
                    sh.LockAnchor = True
                  retry(make)
                  made += 1
                except Exception as e:
                    failed += 1
                    if failed <= 5:
                        print(f"    건너뜀 {it['kind']}: {e}")

        OUTDIR.mkdir(parents=True, exist_ok=True)
        out = OUTDIR / f"AX_Award_지원서_Q-Agent_v{version}.docx"
        doc.SaveAs2(str(out), FileFormat=16)
        doc.ExportAsFixedFormat(str(out.with_suffix(".pdf")), ExportFormat=17)
        pgs = doc.ComputeStatistics(2)
        print(f"  개체 {made}개 생성 (실패 {failed}) · {pgs}장"
              f" · 축소 {stat['shrunk']}회 · 측정불가 {stat['nobound']}")
        print(f"OK {out}")
    finally:
        try:
            doc.Close(SaveChanges=0)
        except Exception:
            pass
        word.ScreenUpdating = True
        word.Quit()


main(int(sys.argv[1]) if len(sys.argv) > 1 else 48)
