#!/usr/bin/env python
"""Prove that an AX Award HTML revision changed copy, not design markup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from playwright.sync_api import sync_playwright


SNAPSHOT_JS = r"""() => {
  const elements = [...document.querySelectorAll('*')];
  const attrs = (el) => [...el.attributes]
    .map(a => [a.name, a.value])
    .sort((a, b) => a[0].localeCompare(b[0]));
  const structure = elements.map((el, index) => ({
    index,
    tag: el.tagName,
    attrs: attrs(el),
    childTags: [...el.children].map(c => c.tagName)
  }));
  const styleTexts = [...document.querySelectorAll('style')].map(s => s.textContent);
  const visualRects = elements.map((el, index) => {
    const s = getComputedStyle(el);
    const r = el.getBoundingClientRect();
    const visual = el.matches('section.page, table, td, svg') ||
      s.backgroundColor !== 'rgba(0, 0, 0, 0)' ||
      parseFloat(s.borderTopWidth) || parseFloat(s.borderRightWidth) ||
      parseFloat(s.borderBottomWidth) || parseFloat(s.borderLeftWidth);
    return visual ? {
      index,
      x: +r.x.toFixed(2), y: +r.y.toFixed(2),
      w: +r.width.toFixed(2), h: +r.height.toFixed(2)
    } : null;
  }).filter(Boolean);
  return {structure, styleTexts, visualRects};
}"""


def capture(page, path: Path) -> dict:
    page.goto(path.resolve().as_uri())
    page.wait_for_timeout(300)
    return page.evaluate(SNAPSHOT_JS)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("original", type=Path)
    parser.add_argument("revision", type=Path)
    parser.add_argument("--rect-tolerance", type=float, default=1.0)
    args = parser.parse_args()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1200})
        original = capture(page, args.original)
        revision = capture(page, args.revision)
        browser.close()

    failures: list[str] = []
    if original["structure"] != revision["structure"]:
        failures.append("DOM tags or attributes changed")
    if original["styleTexts"] != revision["styleTexts"]:
        failures.append("stylesheet text changed")

    a_rects = {r["index"]: r for r in original["visualRects"]}
    b_rects = {r["index"]: r for r in revision["visualRects"]}
    rect_diffs = []
    if a_rects.keys() != b_rects.keys():
        failures.append("set of visual elements changed")
    else:
        for index in a_rects:
            a, b = a_rects[index], b_rects[index]
            delta = max(abs(a[k] - b[k]) for k in ("x", "y", "w", "h"))
            if delta > args.rect_tolerance:
                rect_diffs.append({"index": index, "maxDelta": round(delta, 2), "before": a, "after": b})
        if rect_diffs:
            failures.append(f"visual geometry changed for {len(rect_diffs)} elements")

    report = {
        "original": str(args.original.resolve()),
        "revision": str(args.revision.resolve()),
        "elementCount": len(original["structure"]),
        "visualElementCount": len(original["visualRects"]),
        "geometryDiffs": rect_diffs[:30],
        "failures": failures,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
