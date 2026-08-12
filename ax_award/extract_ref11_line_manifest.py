#!/usr/bin/env python
"""Extract actual browser soft-line boundaries for the ref11 text objects."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


HERE = Path(__file__).resolve().parent
HTML = HERE / "html" / "AX_Award_지원서_ref11_v3.html"
BOXES = HERE / "out" / "boxes_ref11_v3_alignment_v5.json"
OUTPUT = HERE / "out" / "ref11_v6_line_manifest.json"


JS = r"""(pages) => {
  const isBlockish = (el) => {
    const d = getComputedStyle(el).display;
    return d !== 'inline' && el.tagName !== 'BR';
  };
  const textParts = (el) => {
    const chars = [];
    const addText = (node) => {
      const source = node.nodeValue || '';
      const tokens = [...source.matchAll(/\s+|[^\s]/gu)];
      const normalized = source.replace(/\s+/g, ' ');
      if (!normalized.trim()) {
        if (normalized === ' ' && chars.length) {
          const token = tokens[0];
          const range = document.createRange();
          range.setStart(node, token.index);
          range.setEnd(node, token.index + token[0].length);
          const rect = range.getBoundingClientRect();
          chars.push({ch: ' ', top: rect.top, bottom: rect.bottom});
        }
        return;
      }
      for (const token of tokens) {
        const ch = /^\s+$/.test(token[0]) ? ' ' : token[0];
        const range = document.createRange();
        range.setStart(node, token.index);
        range.setEnd(node, token.index + token[0].length);
        const rect = range.getBoundingClientRect();
        chars.push({ch, top: rect.top, bottom: rect.bottom});
      }
    };
    const walk = (node) => {
      for (const child of node.childNodes) {
        if (child.nodeType === 3) addText(child);
        else if (child.nodeType === 1) {
          if (child.tagName === 'BR') { chars.push({ch: '\n', top: null, bottom: null}); continue; }
          if (child.tagName.toLowerCase() === 'svg') continue;
          if (isBlockish(child)) continue;
          walk(child);
        }
      }
    };
    walk(el);
    return chars;
  };
  const records = [];
  document.querySelectorAll('section.page').forEach((sec, pageIndex) => {
    const pageRect = sec.getBoundingClientRect();
    const candidates = [];
    const visit = (el) => {
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') return;
      const rect = el.getBoundingClientRect();
      if (rect.width < 0.6 || rect.height < 0.6) return;
      if (el.tagName.toLowerCase() === 'svg') {
        for (const tx of el.querySelectorAll('text')) {
          const tr = tx.getBoundingClientRect();
          const raw = (tx.textContent || '').replace(/\s+/g, ' ').trim();
          if (raw) candidates.push({raw, x: tr.left-pageRect.left, y: tr.top-pageRect.top,
                                    w: Math.max(tr.width+2,4), h: Math.max(tr.height+2,4), soft: []});
        }
        return;
      }
      const chars = textParts(el);
      const raw = chars.map(item => item.ch).join('');
      if (raw.length) {
        const pl = parseFloat(cs.paddingLeft) || 0, pr = parseFloat(cs.paddingRight) || 0;
        const pt = parseFloat(cs.paddingTop) || 0, pb = parseFloat(cs.paddingBottom) || 0;
        const soft = [];
        let previousBottom = null;
        const lineHeight = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) || 10;
        const lineThreshold = Math.max(2.5, lineHeight * 0.35);
        for (let index = 0; index < chars.length; index++) {
          const item = chars[index];
          if (item.ch === '\n') { previousBottom = null; continue; }
          if (previousBottom !== null && item.bottom !== null &&
              Math.abs(item.bottom - previousBottom) > lineThreshold &&
              chars[index - 1]?.ch !== '\n') soft.push(index);
          if (item.bottom !== null) previousBottom = item.bottom;
        }
        candidates.push({raw, x: rect.left-pageRect.left+pl, y: rect.top-pageRect.top+pt,
                         w: Math.max(rect.width-pl-pr,4), h: Math.max(rect.height-pt-pb,4), soft});
      }
      for (const child of el.children) if (isBlockish(child)) visit(child);
    };
    for (const child of sec.children) if (isBlockish(child)) visit(child);

    const used = new Set();
    const textItems = pages[pageIndex].items.filter(item => item.kind === 'text');
    const pageRecords = [];
    for (const item of textItems) {
      const raw = item.runs.map(run => run.t || '').join('');
      let best = -1, bestDistance = Infinity;
      for (let index = 0; index < candidates.length; index++) {
        if (used.has(index) || candidates[index].raw !== raw) continue;
        const c = candidates[index];
        const distance = Math.abs(c.x-item.x)+Math.abs(c.y-item.y)+Math.abs(c.w-item.w)+Math.abs(c.h-item.h);
        if (distance < bestDistance) { best=index; bestDistance=distance; }
      }
      if (best < 0) pageRecords.push({raw, soft: null, error: 'unmatched'});
      else {
        used.add(best);
        const c = candidates[best];
        pageRecords.push({raw, soft: c.soft, distance: bestDistance});
      }
    }
    records.push(pageRecords);
  });
  return records;
}"""


async def main() -> None:
    pages = json.loads(BOXES.read_text(encoding="utf-8"))
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch()
        page = await browser.new_page(viewport={"width": 900, "height": 1200})
        await page.goto(HTML.resolve().as_uri())
        await page.wait_for_timeout(500)
        manifest = await page.evaluate(JS, pages)
        await browser.close()
    unmatched = sum(1 for page in manifest for item in page if item.get("soft") is None)
    max_distance = max(item.get("distance", 0) for page in manifest for item in page)
    OUTPUT.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"text={sum(map(len, manifest))} unmatched={unmatched} max_distance={max_distance:.4f}")
    print(OUTPUT)


if __name__ == "__main__":
    asyncio.run(main())
