from __future__ import annotations

import argparse
import json
import math
import re
from pathlib import Path

import win32com.client
from lxml import etree
from playwright.sync_api import sync_playwright


PAGE_WIDTH_PT = 595.2756
PAGE_HEIGHT_PT = 841.8898
EDGE_PATH = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"


def extract_layout(html_path: Path) -> dict:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            executable_path=EDGE_PATH,
            args=["--disable-gpu"],
        )
        page = browser.new_page(viewport={"width": 1100, "height": 1600})
        page.emulate_media(media="print")
        page.goto(html_path.as_uri(), wait_until="load")
        page.evaluate("document.fonts.ready")
        layout = page.evaluate(
            r"""
            () => {
              const visible = (el) => {
                const cs = getComputedStyle(el);
                const r = el.getBoundingClientRect();
                return cs.display !== 'none' && cs.visibility !== 'hidden' &&
                       Number(cs.opacity) > 0 && r.width > 0.05 && r.height > 0.05;
              };
              const cumulativeOpacity = (el, stop) => {
                let value = 1;
                for (let cur = el; cur && cur !== stop.parentElement; cur = cur.parentElement) {
                  value *= Number(getComputedStyle(cur).opacity || 1);
                }
                return value;
              };
              const radiusValue = (value) => {
                const n = parseFloat(value);
                return Number.isFinite(n) ? n : 0;
              };
              const pages = [];
              for (const pageEl of document.querySelectorAll('section.page')) {
                const pr = pageEl.getBoundingClientRect();
                const fit = pageEl.querySelector(':scope > .fit');
                const matrix = new DOMMatrix(getComputedStyle(fit).transform);
                const boxes = [];
                let order = 0;
                for (const el of pageEl.querySelectorAll('*')) {
                  order += 1;
                  if (!visible(el) || el.closest('svg') || ['SCRIPT','STYLE','BR'].includes(el.tagName)) continue;
                  const cs = getComputedStyle(el);
                  const r = el.getBoundingClientRect();
                  const sides = {};
                  for (const side of ['Top','Right','Bottom','Left']) {
                    sides[side.toLowerCase()] = {
                      width: parseFloat(cs[`border${side}Width`]) || 0,
                      color: cs[`border${side}Color`],
                      style: cs[`border${side}Style`],
                    };
                  }
                  const bg = cs.backgroundColor;
                  const hasBg = bg && bg !== 'transparent' && !bg.endsWith(', 0)') && bg !== 'rgba(0, 0, 0, 0)';
                  const hasBorder = Object.values(sides).some(
                    s => s.width > 0 && s.style !== 'none' && s.color !== 'transparent' && !s.color.endsWith(', 0)')
                  );
                  if (!hasBg && !hasBorder) continue;
                  boxes.push({
                    order,
                    tag: el.tagName.toLowerCase(),
                    x: r.left - pr.left,
                    y: r.top - pr.top,
                    w: r.width,
                    h: r.height,
                    background: bg,
                    opacity: cumulativeOpacity(el, pageEl),
                    radius: Math.max(
                      radiusValue(cs.borderTopLeftRadius), radiusValue(cs.borderTopRightRadius),
                      radiusValue(cs.borderBottomLeftRadius), radiusValue(cs.borderBottomRightRadius)
                    ),
                    borders: sides,
                  });
                }

                const textRuns = [];
                const walker = document.createTreeWalker(pageEl, NodeFilter.SHOW_TEXT);
                let node;
                while ((node = walker.nextNode())) {
                  const parent = node.parentElement;
                  if (!parent || parent.closest('script,style,defs,marker,linearGradient') || !visible(parent)) continue;
                  if (!node.data || !node.data.trim()) continue;
                  const cs = getComputedStyle(parent);
                  let current = null;
                  for (let i = 0; i < node.data.length; i++) {
                    const range = document.createRange();
                    range.setStart(node, i);
                    range.setEnd(node, i + 1);
                    const rect = range.getBoundingClientRect();
                    const ch = node.data[i];
                    if (rect.width < 0.01 || rect.height < 0.01) {
                      current = null;
                      continue;
                    }
                    const x = rect.left - pr.left;
                    const y = rect.top - pr.top;
                    const sameLine = current && Math.abs(current.y - y) < 0.55 &&
                                     Math.abs(current.bottom - (rect.bottom - pr.top)) < 0.7 &&
                                     Math.abs(current.right - x) < 2.2;
                    if (!sameLine) {
                      if (current && current.text.trim()) textRuns.push(current);
                      current = {
                        text: ch,
                        x, y,
                        right: rect.right - pr.left,
                        bottom: rect.bottom - pr.top,
                        fontFamily: cs.fontFamily,
                        fontSize: parseFloat(cs.fontSize) || 10,
                        fontWeight: cs.fontWeight,
                        fontStyle: cs.fontStyle,
                        color: cs.color,
                        textDecoration: cs.textDecorationLine,
                        opacity: cumulativeOpacity(parent, pageEl),
                        order: textRuns.length,
                      };
                    } else {
                      current.text += ch;
                      current.right = rect.right - pr.left;
                      current.bottom = Math.max(current.bottom, rect.bottom - pr.top);
                    }
                  }
                  if (current && current.text.trim()) textRuns.push(current);
                }

                const svgs = [];
                let svgOrder = 0;
                for (const svg of pageEl.querySelectorAll('svg')) {
                  if (!visible(svg)) continue;
                  const clone = svg.cloneNode(true);
                  clone.querySelectorAll('text').forEach(el => el.remove());
                  clone.removeAttribute('style');
                  clone.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
                  clone.setAttribute('width', '100%');
                  clone.setAttribute('height', '100%');
                  const r = svg.getBoundingClientRect();
                  svgs.push({
                    order: svgOrder++,
                    x: r.left - pr.left,
                    y: r.top - pr.top,
                    w: r.width,
                    h: r.height,
                    markup: clone.outerHTML,
                  });
                }
                pages.push({
                  width: pr.width,
                  height: pr.height,
                  fitScale: matrix.a || 1,
                  boxes,
                  textRuns,
                  svgs,
                });
              }
              return {pages};
            }
            """
        )
        browser.close()
    return layout


def parse_css_color(value: str) -> tuple[int, int, int, float] | None:
    if not value or value in {"transparent", "none"}:
        return None
    if value.startswith("#"):
        raw = value[1:]
        if len(raw) == 3:
            raw = "".join(ch * 2 for ch in raw)
        if len(raw) >= 6:
            return int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16), 1.0
    nums = re.findall(r"[\d.]+", value)
    if len(nums) >= 3:
        alpha = float(nums[3]) if len(nums) >= 4 else 1.0
        return int(float(nums[0])), int(float(nums[1])), int(float(nums[2])), alpha
    return None


def office_rgb(color: tuple[int, int, int, float]) -> int:
    r, g, b, _ = color
    return r + (g << 8) + (b << 16)


def clean_svg(markup: str, output_path: Path) -> None:
    parser = etree.XMLParser(remove_blank_text=True, recover=True)
    root = etree.fromstring(markup.encode("utf-8"), parser=parser)
    for text in root.xpath("//*[local-name()='text']"):
        text.getparent().remove(text)
    output_path.write_bytes(etree.tostring(root, xml_declaration=True, encoding="utf-8"))


def set_shape_position(shape, x: float, y: float, w: float, h: float, in_front: bool = True) -> None:
    shape.RelativeHorizontalPosition = 1  # wdRelativeHorizontalPositionPage
    shape.RelativeVerticalPosition = 1  # wdRelativeVerticalPositionPage
    shape.Left = x
    shape.Top = y
    shape.Width = max(0.2, w)
    shape.Height = max(0.2, h)
    shape.WrapFormat.Type = 6 if in_front else 5  # wdWrapFront / wdWrapBehind
    shape.LockAnchor = -1
    try:
        shape.LayoutInCell = 0
    except Exception:
        pass


def set_line_format(line, color_value: str, width_pt: float, style: str, opacity: float) -> None:
    color = parse_css_color(color_value)
    if not color or width_pt <= 0 or style == "none":
        line.Visible = 0
        return
    line.Visible = -1
    line.ForeColor.RGB = office_rgb(color)
    line.Transparency = max(0.0, min(1.0, 1.0 - color[3] * opacity))
    line.Weight = max(0.25, width_pt)
    if style == "dashed":
        line.DashStyle = 4
    elif style == "dotted":
        line.DashStyle = 3
    else:
        line.DashStyle = 1


def add_box(doc, anchor, box: dict, scale: float, page_no: int, index: int) -> int:
    x, y = box["x"] * scale, box["y"] * scale
    w, h = box["w"] * scale, box["h"] * scale
    if w < 0.15 or h < 0.15:
        return 0
    bg = parse_css_color(box["background"])
    opacity = float(box.get("opacity", 1.0))
    borders = box["borders"]
    visible_sides = [s for s in ("top", "right", "bottom", "left")
                     if borders[s]["width"] > 0 and borders[s]["style"] != "none"
                     and parse_css_color(borders[s]["color"])]
    uniform = len(visible_sides) == 4 and all(
        abs(borders[s]["width"] - borders["top"]["width"]) < 0.05 and
        borders[s]["style"] == borders["top"]["style"] and
        borders[s]["color"] == borders["top"]["color"]
        for s in visible_sides
    )
    shape_type = 5 if box.get("radius", 0) * scale >= 1.0 and min(w, h) >= 3 else 1
    shape = None
    count = 0
    if bg or uniform:
        shape = doc.Shapes.AddShape(shape_type, x, y, w, h, anchor)
        shape.Name = f"P{page_no}_Box_{index:03d}"
        set_shape_position(shape, x, y, w, h)
        if bg:
            shape.Fill.Visible = -1
            shape.Fill.Solid()
            shape.Fill.ForeColor.RGB = office_rgb(bg)
            shape.Fill.Transparency = max(0.0, min(1.0, 1.0 - bg[3] * opacity))
        else:
            shape.Fill.Visible = 0
        if uniform:
            set_line_format(
                shape.Line,
                borders["top"]["color"],
                borders["top"]["width"] * scale,
                borders["top"]["style"],
                opacity,
            )
        else:
            shape.Line.Visible = 0
        if shape_type == 5:
            try:
                shape.Adjustments[1] = min(0.35, (box["radius"] * scale) / max(1.0, min(w, h)))
            except Exception:
                pass
        count += 1
    if not uniform:
        coords = {
            "top": (x, y, x + w, y),
            "right": (x + w, y, x + w, y + h),
            "bottom": (x, y + h, x + w, y + h),
            "left": (x, y, x, y + h),
        }
        for side in visible_sides:
            x1, y1, x2, y2 = coords[side]
            line = doc.Shapes.AddLine(x1, y1, x2, y2, anchor)
            line.Name = f"P{page_no}_Box_{index:03d}_{side}"
            set_shape_position(line, min(x1, x2), min(y1, y2), max(0.2, abs(x2-x1)), max(0.2, abs(y2-y1)))
            set_line_format(
                line.Line,
                borders[side]["color"],
                borders[side]["width"] * scale,
                borders[side]["style"],
                opacity,
            )
            count += 1
    return count


def map_font(font_family: str) -> str:
    lower = font_family.lower()
    if "consolas" in lower or "monospace" in lower:
        return "Consolas"
    if "segoe ui symbol" in lower:
        return "Segoe UI Symbol"
    if "굴림" in lower or "gulim" in lower:
        return "굴림"
    return "Noto Sans KR"


def add_text_run(doc, anchor, run: dict, scale: float, fit_scale: float, page_no: int, index: int) -> None:
    text = run["text"].replace("\n", " ").replace("\r", " ")
    if not text.strip():
        return
    x = run["x"] * scale
    y = run["y"] * scale - 0.35
    w = max(2.0, (run["right"] - run["x"]) * scale + 2.2)
    h = max(2.0, (run["bottom"] - run["y"]) * scale + 2.4)
    shape = doc.Shapes.AddTextbox(1, x, y, w, h, anchor)
    shape.Name = f"P{page_no}_Text_{index:04d}"
    shape.AlternativeText = text[:250]
    set_shape_position(shape, x, y, w, h)
    shape.Fill.Visible = 0
    shape.Line.Visible = 0
    frame = shape.TextFrame
    frame.MarginLeft = 0
    frame.MarginRight = 0
    frame.MarginTop = 0
    frame.MarginBottom = 0
    frame.AutoSize = 0
    try:
        frame.WordWrap = 0
        frame.VerticalAnchor = 1
    except Exception:
        pass
    text_range = frame.TextRange
    text_range.Text = text
    font = text_range.Font
    font_name = map_font(run["fontFamily"])
    font.Name = font_name
    try:
        font.NameFarEast = font_name
    except Exception:
        pass
    font.Size = max(1.0, float(run["fontSize"]) * 0.75 * fit_scale)
    weight = str(run.get("fontWeight", "400")).lower()
    numeric_weight = int(weight) if weight.isdigit() else (700 if weight in {"bold", "bolder"} else 400)
    font.Bold = -1 if numeric_weight >= 600 else 0
    font.Italic = -1 if run.get("fontStyle") == "italic" else 0
    font.Underline = 1 if "underline" in run.get("textDecoration", "") else 0
    color = parse_css_color(run.get("color", "rgb(0,0,0)"))
    if color:
        font.Color = office_rgb(color)
    paragraph = text_range.ParagraphFormat
    paragraph.Alignment = 0
    paragraph.SpaceBefore = 0
    paragraph.SpaceAfter = 0
    paragraph.LineSpacingRule = 0
    try:
        paragraph.DisableLineHeightGrid = -1
    except Exception:
        pass


def build_docx(layout: dict, output_path: Path, work_dir: Path) -> dict:
    word = win32com.client.DispatchEx("Word.Application")
    word.Visible = False
    word.DisplayAlerts = 0
    word.ScreenUpdating = False
    doc = None
    counts = {"boxes": 0, "text": 0, "svg": 0}
    try:
        doc = word.Documents.Add()
        setup = doc.PageSetup
        setup.PageWidth = PAGE_WIDTH_PT
        setup.PageHeight = PAGE_HEIGHT_PT
        setup.TopMargin = 0
        setup.BottomMargin = 0
        setup.LeftMargin = 0
        setup.RightMargin = 0
        setup.HeaderDistance = 0
        setup.FooterDistance = 0
        setup.Gutter = 0

        doc.Content.Text = "\r\f\r\f\r\f\r\f\r"
        base = doc.Content
        base.Font.Name = "Noto Sans KR"
        base.Font.Size = 1
        base.ParagraphFormat.SpaceBefore = 0
        base.ParagraphFormat.SpaceAfter = 0
        base.ParagraphFormat.LineSpacingRule = 4
        base.ParagraphFormat.LineSpacing = 1
        doc.Repaginate()

        anchors = [doc.GoTo(1, 1, i).Duplicate for i in range(1, 6)]  # wdGoToPage / absolute
        for page_no, (page, anchor) in enumerate(zip(layout["pages"], anchors), start=1):
            scale = PAGE_WIDTH_PT / float(page["width"])
            for index, box in enumerate(page["boxes"], start=1):
                counts["boxes"] += add_box(doc, anchor, box, scale, page_no, index)

            for index, svg in enumerate(page["svgs"], start=1):
                svg_path = work_dir / f"page_{page_no}_diagram_{index}.svg"
                clean_svg(svg["markup"], svg_path)
                x, y = svg["x"] * scale, svg["y"] * scale
                w, h = svg["w"] * scale, svg["h"] * scale
                inline = doc.InlineShapes.AddPicture(str(svg_path), False, True, anchor)
                shape = inline.ConvertToShape()
                shape.Name = f"P{page_no}_VectorDiagram_{index:02d}"
                shape.AlternativeText = "HTML source vector diagram; diagram labels are separate editable text boxes."
                set_shape_position(shape, x, y, w, h)
                counts["svg"] += 1

            for index, run in enumerate(page["textRuns"], start=1):
                add_text_run(doc, anchor, run, scale, float(page["fitScale"]), page_no, index)
                counts["text"] += 1

        doc.BuiltInDocumentProperties.Item("Title").Value = "AX Award 지원서 - Q-Agent"
        doc.BuiltInDocumentProperties.Item("Subject").Value = "Editable Word reconstruction of the HTML award application"
        doc.BuiltInDocumentProperties.Item("Comments").Value = "All text and layout boxes are editable Word objects. Diagrams remain editable vector graphics; no raster page captures are used."
        doc.Repaginate()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        doc.SaveAs2(str(output_path), 16)
        pages = doc.ComputeStatistics(2)
        shapes = doc.Shapes.Count
        inline_shapes = doc.InlineShapes.Count
        tables = doc.Tables.Count
        return {**counts, "pages": pages, "shapes": shapes, "inline_shapes": inline_shapes, "tables": tables}
    finally:
        if doc is not None:
            doc.Close(False)
        word.Quit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--html", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--extract-only", action="store_true")
    args = parser.parse_args()
    args.work_dir.mkdir(parents=True, exist_ok=True)
    layout = extract_layout(args.html.resolve())
    layout_path = args.work_dir / "layout.json"
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "pages": len(layout["pages"]),
        "boxes": [len(p["boxes"]) for p in layout["pages"]],
        "text_runs": [len(p["textRuns"]) for p in layout["pages"]],
        "svgs": [len(p["svgs"]) for p in layout["pages"]],
        "layout": str(layout_path.resolve()),
    }, ensure_ascii=False))
    if args.extract_only:
        return
    result = build_docx(layout, args.output.resolve(), args.work_dir.resolve())
    print(json.dumps({"output": str(args.output.resolve()), **result}, ensure_ascii=False))


if __name__ == "__main__":
    main()
