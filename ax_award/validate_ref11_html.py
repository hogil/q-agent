#!/usr/bin/env python
"""Validate the fixed five-page AX Award HTML before DOCX conversion."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from playwright.sync_api import sync_playwright


BANNED_TERMS = (
    "완전한",
    "살아있는",
    "스스로",
    "통째로",
    "정거장",
    "자란다",
    "닫힌다",
    "관문",
    "걷는다",
    "돌파",
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("html", type=Path)
    parser.add_argument("--screenshots", type=Path)
    args = parser.parse_args()

    html = args.html.resolve()
    if not html.exists():
        raise SystemExit(f"missing HTML: {html}")

    raw = html.read_text(encoding="utf-8")
    static = {
        "sections": len(re.findall(r"<section\s+class=[\"'][^\"']*\bpage\b", raw)),
        "middle_dots": raw.count("·"),
        "banned": {term: raw.count(term) for term in BANNED_TERMS if term in raw},
        "has_iiii": "IIII. 경영효과" in raw,
        "css_literal": ';border-radius:5px;padding:4px 9px">' in raw,
    }

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 1200})
        page.goto(html.as_uri())
        page.wait_for_timeout(300)
        geometry = page.evaluate(
            """() => [...document.querySelectorAll('section.page')].map((p, i) => {
              const pr = p.getBoundingClientRect();
              const tables = [...p.querySelectorAll(':scope > table')].map(t => {
                const r = t.getBoundingClientRect();
                return {top:r.top-pr.top, bottom:r.bottom-pr.top, width:r.width};
              });
              const texts = [...p.querySelectorAll('*')].filter(e => {
                const t = [...e.childNodes].some(n => n.nodeType === Node.TEXT_NODE && n.nodeValue.trim());
                return t;
              }).map(e => {
                const s = getComputedStyle(e);
                return {font:s.fontFamily, px:parseFloat(s.fontSize), text:e.textContent.trim().slice(0,60)};
              });
              return {
                page:i+1,
                width:p.clientWidth,
                height:p.clientHeight,
                scrollHeight:p.scrollHeight,
                padding:getComputedStyle(p).padding,
                tables,
                minTextPx:texts.length ? Math.min(...texts.map(t => t.px)) : 0,
                smallTextCount:texts.filter(t => t.px < 10.66).length,
                nonBatangCount:texts.filter(t => !/Batang|바탕/.test(t.font)).length,
                textChars:(p.innerText || '').length
              };
            })"""
        )
        if args.screenshots:
            args.screenshots.mkdir(parents=True, exist_ok=True)
            for index, section in enumerate(page.locator("section.page").all(), start=1):
                section.screenshot(path=args.screenshots / f"page-{index}.png")
        browser.close()

    hard_failures: list[str] = []
    if static["sections"] != 5:
        hard_failures.append(f"page count {static['sections']} != 5")
    if not static["has_iiii"]:
        hard_failures.append("missing IIII. 경영효과")
    if static["css_literal"]:
        hard_failures.append("broken CSS literal is visible in source")
    if static["banned"]:
        hard_failures.append(f"banned terms remain: {static['banned']}")
    if static["middle_dots"]:
        hard_failures.append(f"middle dots remain: {static['middle_dots']}")

    for item in geometry:
        if item["scrollHeight"] > item["height"]:
            hard_failures.append(
                f"page {item['page']} overflow {item['scrollHeight']} > {item['height']}"
            )
        for table in item["tables"]:
            if table["bottom"] > 1027:
                hard_failures.append(
                    f"page {item['page']} table bottom {table['bottom']:.1f} > 1027"
                )

    result = {"html": str(html), "static": static, "pages": geometry, "failures": hard_failures}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if hard_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
