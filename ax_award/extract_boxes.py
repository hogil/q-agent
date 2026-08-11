#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""HTML 시안을 '도형 + 텍스트' 목록으로 뽑는다 — Word 에 그대로 앉히기 위한 중간 표현.

캡처가 아니라 객체로 옮기는 게 목적이다. 브라우저의 getComputedStyle 로 실제 렌더
값(상속·단축 속성까지 해석된 값)을 읽으므로 인라인 스타일을 손으로 파싱할 필요가 없다.

  box   배경색·테두리가 있는 요소     -> 둥근 사각형 도형 (글자 없음)
  text  자기 줄에 글자가 있는 요소     -> 투명 텍스트 상자 (글자만)
  svg   스파크라인·웨이퍼 맵          -> 도형으로 옮길 수 없어 그림 (몇 개 안 된다)

둘을 분리하는 이유: 칸 배경과 글자를 한 도형에 넣으면 Word 의 줄바꿈이 브라우저와
달라질 때 배경까지 같이 틀어진다. 배경은 좌표로 고정하고 글자만 흐르게 둔다.
좌표는 페이지 좌상단 기준 px (96dpi) 다.

사용: python extract_boxes.py [출력.json]
"""
from __future__ import annotations

import asyncio
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).parent
HTML = HERE / "html" / "AX_Award_지원서.html"
OUT = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "out" / "boxes.json"
SVGDIR = HERE / "out" / "fig_v48"

JS = r"""() => {
  const TRANSPARENT = new Set(['rgba(0, 0, 0, 0)', 'transparent']);
  const rgb = (s) => {
    const m = /rgba?\((\d+),\s*(\d+),\s*(\d+)(?:,\s*([\d.]+))?\)/.exec(s || '');
    if (!m) return null;
    if (m[4] !== undefined && parseFloat(m[4]) === 0) return null;
    return [ +m[1], +m[2], +m[3] ];
  };
  const isBlockish = (el) => {
    const d = getComputedStyle(el).display;
    return d !== 'inline' && el.tagName !== 'BR';
  };

  // 이 요소의 '자기 줄' 글자 조각들. 자식 블록 안의 글자는 그 블록이 따로 맡는다.
  const ownRuns = (el) => {
    const out = [];
    const walk = (node) => {
      for (const n of node.childNodes) {
        if (n.nodeType === 3) {
          const t = n.nodeValue.replace(/\s+/g, ' ');
          if (!t.trim()) {
            // 조각 사이의 공백 한 칸은 살린다 — 버리면 'Agent'+'get_x' 가 붙어버린다
            if (t === ' ' && out.length) out.push({ t: ' ', size: 10, bold: false,
                                                    color: [17,24,39], mono: false });
            continue;
          }
          {
            const cs = getComputedStyle(n.parentElement);
            out.push({ t, size: parseFloat(cs.fontSize),
                       bold: parseInt(cs.fontWeight, 10) >= 600,
                       color: rgb(cs.color) || [17, 24, 39],
                       mono: /mono|Consolas|AXNoto/i.test(cs.fontFamily) &&
                             /mono|Consolas/i.test(cs.fontFamily) });
          }
        } else if (n.nodeType === 1) {
          if (n.tagName === 'BR') { out.push({ t: '\n' }); continue; }
          if (n.tagName === 'SVG' || n.tagName === 'svg') continue;
          if (isBlockish(n)) continue;          // 자식 블록은 건너뛴다
          walk(n);
        }
      }
    };
    walk(el);
    return out;
  };

  const pages = [];
  document.querySelectorAll('section.page').forEach((sec, pi) => {
    const P = sec.getBoundingClientRect();
    const items = [];
    let svgN = 0;

    const visit = (el) => {
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') return;
      const r = el.getBoundingClientRect();
      if (r.width < 0.6 || r.height < 0.6) return;
      const box = { x: r.left - P.left, y: r.top - P.top, w: r.width, h: r.height };

      if (el.tagName.toLowerCase() === 'svg') {
        const id = `p${pi + 1}_svg${svgN++}`;
        el.setAttribute('data-svg', id);
        items.push({ kind: 'svg', id, ...box });
        return;
      }

      const bg = TRANSPARENT.has(cs.backgroundColor) ? null : rgb(cs.backgroundColor);
      const radius = parseFloat(cs.borderTopLeftRadius) || 0;
      const shadow = !!(cs.boxShadow && cs.boxShadow !== 'none');
      // 네 변을 따로 본다 — 한쪽만 있는 테두리(왼쪽 세로 막대 등)를 놓치지 않기 위해
      const side = (S) => {
        const w = parseFloat(cs['border' + S + 'Width']) || 0;
        const st = cs['border' + S + 'Style'];
        return (w > 0 && st !== 'none') ? { w, c: rgb(cs['border' + S + 'Color']) } : null;
      };
      const B = { Top: side('Top'), Right: side('Right'),
                  Bottom: side('Bottom'), Left: side('Left') };
      const present = Object.values(B).filter(Boolean);
      const allFour = present.length === 4;

      if (bg || allFour) {
        items.push({ kind: 'box', ...box, bg, shadow, radius,
                     bc: allFour ? B.Top.c : null, bw: allFour ? B.Top.w : 0 });
      }
      if (!allFour) {
        // 한쪽 테두리는 그 변 자리에 얇은 채움 사각형으로 옮긴다 — 보이는 대로다
        if (B.Top)    items.push({ kind: 'box', x: box.x, y: box.y, w: box.w, h: B.Top.w, bg: B.Top.c, bc: null, bw: 0, radius: 0 });
        if (B.Bottom) items.push({ kind: 'box', x: box.x, y: box.y + box.h - B.Bottom.w, w: box.w, h: B.Bottom.w, bg: B.Bottom.c, bc: null, bw: 0, radius: 0 });
        if (B.Left)   items.push({ kind: 'box', x: box.x, y: box.y, w: B.Left.w, h: box.h, bg: B.Left.c, bc: null, bw: 0, radius: 0 });
        if (B.Right)  items.push({ kind: 'box', x: box.x + box.w - B.Right.w, y: box.y, w: B.Right.w, h: box.h, bg: B.Right.c, bc: null, bw: 0, radius: 0 });
      }

      const runs = ownRuns(el);
      if (runs.length) {
        // 글자는 안쪽 여백을 뺀 자리에 앉힌다
        const pl = parseFloat(cs.paddingLeft) || 0, pr = parseFloat(cs.paddingRight) || 0;
        const pt = parseFloat(cs.paddingTop) || 0, pb = parseFloat(cs.paddingBottom) || 0;
        items.push({ kind: 'text',
                     x: box.x + pl, y: box.y + pt,
                     w: Math.max(box.w - pl - pr, 4), h: Math.max(box.h - pt - pb, 4),
                     align: cs.textAlign, lh: parseFloat(cs.lineHeight) || 0, runs });
      }

      for (const c of el.children) if (isBlockish(c)) visit(c);
    };

    for (const c of sec.children) if (isBlockish(c)) visit(c);
    pages.push({ page: pi + 1, w: P.width, h: P.height, items });
  });
  return pages;
}"""


async def main():
    from playwright.async_api import async_playwright
    SVGDIR.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as pw:
        b = await pw.chromium.launch()
        pg = await b.new_page(viewport={"width": 900, "height": 1200}, device_scale_factor=4)
        await pg.goto(HTML.resolve().as_uri())
        await pg.wait_for_timeout(900)
        pages = await pg.evaluate(JS)
        for p in pages:
            for it in p["items"]:
                if it["kind"] == "svg":
                    el = await pg.query_selector(f'[data-svg="{it["id"]}"]')
                    if el:
                        await el.screenshot(path=str(SVGDIR / f'{it["id"]}.png'))
        await b.close()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")
    for p in pages:
        k = {}
        for it in p["items"]:
            k[it["kind"]] = k.get(it["kind"], 0) + 1
        print(f'  p{p["page"]}  {p["w"]:.0f}x{p["h"]:.0f}px   도형 {k.get("box",0)} · 글상자 {k.get("text",0)} · 그림 {k.get("svg",0)}')
    tot = sum(len(p["items"]) for p in pages)
    print(f"총 {tot}개 -> {OUT}")


asyncio.run(main())
