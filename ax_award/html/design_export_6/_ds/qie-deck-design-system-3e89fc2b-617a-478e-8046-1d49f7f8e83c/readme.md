# QIE Deck Design System

A design system for **executive / technical presentation decks** in the visual
language of the *QIE Data Science* AI-certification deck — a clean, white-background,
**navy + teal** corporate system built for dense, data-heavy Korean technical slides
where *every slide carries a visual* and white space is filled with intent, not padding.

The "product" here is the **deck itself**: a data-driven slide builder. This system
ports its design language to the web as tokens, reusable React primitives, foundation
specimen cards, and a full navigable sample deck.

---

## Sources

- **`presentation/` (attached local codebase)** — a Python `python-pptx` deck builder.
  - `build.py` — the canonical design system: palette constants (NAVY/NAVY2/ACCENT/GOLD…),
    slide-type renderers (`s_title`, `s_section`, `s_flow`, `s_table`, `s_two_col`,
    `s_image_grid`, `s_timeline`, `s_closing`, `s_bullets`, `s_stats`). **This file is the
    source of truth** for colours, spacing, and layout motifs.
  - `spec.json` — the deck content (24 slides) used as copy reference.
  - `PLAN.md` — the deck plan / authoring principles.
  - `_render/*.png` — rendered slides, used as visual reference.
- **User-supplied content prompt** — a detailed self-contained brief (P1/P2/P3 exact
  numbers, narrative, operational-vs-validation rules) used as the authoritative copy
  for the sample deck.
- Subject: 최호길, 메모리제조기술센터 QIE그룹 Data Science 파트 — AI Specialist 인증 발표.

> Note: the original deck is internal/corporate. Treat company names as context, not
> branding to reproduce. The reusable value here is the *visual system*, not the content.

---

## CONTENT FUNDAMENTALS — how copy is written

The deck is a **Korean technical/executive register**: precise, evidence-first, never
boastful. The guiding principle (from `PLAN.md`) is *"일·결과 중심(자기과시 X)"* — lead
with the work and the result, not the self.

- **Language**: Korean body copy with **inline English technical terms** kept in Latin
  (Failbit Map, ROI-YOLO, ConvNeXtV2, HDBSCAN, F1, FCM-PM, wafer, chip). Don't translate
  established ML/process terms — mix scripts freely within a sentence.
- **Voice**: third-person / impersonal. No "I/you". Work is described by what it *does*
  ("매일 사용 중", "검증 F1 0.95"), and ownership is flagged with neutral tags
  (`본인 설계`, `표준 채택`) rather than first-person claims.
- **Casing**: Latin terms keep their canonical casing (ConvNeXtV2, ROI-YOLO). No ALL-CAPS
  shouting except short eyebrow kickers and table headers.
- **Numbers are the argument**: copy is built around metrics — `F1 0.95`, `0.9927`,
  `연 26억`, `일 2만`, `13→7`, `0.00%`. Use the arrow `→` heavily for transitions and
  before/after (`0.78 → 0.95`, `조회 48매 → 일 2만`).
- **Honesty guardrails (critical to the brand's tone)**: rigorously separate
  **운영(양산) vs 검증/PoC(미배포)**. A validation score is never written as an operating
  result. This careful hedging *is* the credibility signal — preserve qualifier phrases
  like "(검증·미배포)", "(연 반복액 아님)", "(PoC)".
- **Emphasis**: bold (`**…**`) marks the load-bearing phrase in a bullet; bold renders in
  **navy**, not a colour. One or two bolds per bullet, never a whole sentence.
- **Punctuation**: middot `·` separates peers ("최호길 · QIE Data Science · 인증");
  em-dash `—` introduces a definition or consequence; parentheses carry the caveat.
- **Emoji**: none. Ever. This is a corporate engineering register.
- **Kickers**: every content slide opens with a teal eyebrow like `P1 · 데이터 파이프라인`
  — task tag + middot + topic.

Examples (verbatim register):
- *"현장에서 아는 사실을 **AI의 데이터·손실·평가 설계로 옮긴다**"*
- *"백본 교체+튜닝+2단계 보정: 0.78 → 0.95"*
- *"운영(양산 중) vs 모델(검증·배포 대기) 분리"*

---

## VISUAL FOUNDATIONS

**Overall vibe**: clinical, confident, *flat*. A white clinical canvas with navy
authority and a single electric-teal accent. Reads like a precise lab report, not a
marketing deck.

- **Colour**: white background **always**. Navy (`#0F1E3D`) for titles, dark flow boxes
  and the table header band. Teal (`#12B5B0`) is the one signature accent — bars, kickers,
  arrows, progress, "owned" flow boxes, KPI strips. Navy-2 (`#1B3260`) for nested sub-stages.
  **Gold (`#F2B705`) is rationed** to a single final business-value KPI — never decorative.
  Max **two accent colours on screen**. See `tokens/colors.css`.
- **Type**: one family — **Malgun Gothic (맑은 고딕)**, substituted on the web by
  **Noto Sans KR** (see Iconography/Fonts note). Weights 400 / 700 / 900. Big black
  numerals (P-numbers 80px, stats 22–52px) anchor each slide; 27–32px bold navy titles;
  16–17px body. See `tokens/typography.css`.
- **Depth = FLAT**. There are **no drop shadows** anywhere (`build.py` sets
  `shadow.inherit = False` globally). "Cards" are a panel fill (`#F2F5FA`) plus ONE of:
  a 1px hairline (`#D7DEEA`), a 10px **teal top strip**, or a 9px **teal left bar**. The
  only allowed lift is a subtle hover shadow on interactive buttons.
- **The accent-bar motif** is the system's signature: a teal vertical bar to the LEFT of
  every title (titles are **never underlined** — explicit rule), a teal top strip on stat
  cards, a teal left edge on "after"/highlight panels.
- **Cards / corners**: radius `6px` (chips, image frames), `10px` (cards, flow boxes,
  panels), pill for dots. Restrained, not pill-soft.
- **Backgrounds**: solid white. No gradients, no textures, no full-bleed photos, no
  patterns. Section dividers add a single flat light-panel side column — that is the only
  "background" treatment.
- **Imagery**: domain figures only, in **two distinct visual domains** — do not conflate
  them. (1) **Failbit Map** — the *spatial* wafer/chip data behind **P1 (wafer-level maps)
  and P2 (chip-level detections)**: pale-blue wafer field, grey grid, sparse green/red
  defect clusters. (2) **Trend** — the *time-series* line charts behind **P3 only** (points
  scattered around a horizontal baseline); P3 is NOT a Failbit Map. Both are framed in a
  1px hairline + 6px radius with a bold-navy caption beneath. Never decorative stock photography.
- **Layout**: a fixed grid — 64px content inset, 29px card gutters. Title block top-left,
  footer (`최호길 · QIE Data Science · 인증` + page number) pinned bottom. Content fills the
  band between; empty zones get absorbed by stat-card strips, before→after badges, or
  progress rails rather than left blank.
- **Flow diagrams**: left→right stages of rounded boxes (navy / navy-2 / teal) joined by
  teal `→` arrows; stage labels in teal above each column. Branches stack two boxes per
  column.
- **Tables**: navy header band, zebra body (white / `#F2F5FA`), one teal-tint
  (`#E6F7F6`) highlight row for the winning result. Flat, no vertical rules.
- **Motion**: essentially none in the source (it's a PPTX). For web, keep it minimal —
  short opacity/translate entrances gated on `[data-deck-active]` and reduced-motion;
  no bounces, no infinite loops. Easing `cubic-bezier(0.4,0,0.2,1)`, ~200ms.
- **Hover / press** (web additions): buttons darken (teal → `#0E9C97`) and lift with a
  faint shadow; ghost/outline fill with panel/teal-tint. Nothing scales or bounces.
- **Transparency / blur**: not used. Surfaces are opaque. Teal-tint is a solid tint, not
  an alpha overlay.

---

## ICONOGRAPHY

The source deck is **almost entirely icon-free** — this is a deliberate, austere system.

- **No icon font, no SVG icon set, no emoji.** `build.py` draws only primitive shapes
  (rectangles, rounded rectangles, ovals, and PowerPoint's `RIGHT_ARROW` autoshape).
- **The arrow is the only recurring glyph**: a teal `→` (flow transitions, before→after)
  and a teal right-arrow shape between flow stages. In the web port this is the Unicode
  `→` (U+2192), styled teal/bold.
- **Bullets** are a small teal filled circle `●` (U+25CF); sub-bullets a muted en-dash
  `–` (U+2013). **Progress / timeline nodes** are filled (done) or hollow-outline
  (upcoming) teal circles.
- **Middot `·` (U+00B7)** is the workhorse separator throughout.
- **If a consuming project needs UI icons** (for an app surface built on this system),
  there is no brand set to match — use **Lucide** (`https://unpkg.com/lucide-static`) at
  1.75px stroke to stay consistent with the thin hairline language, and flag the addition.
  Do **not** introduce filled/duotone icon styles — they fight the flat hairline system.
- **Imagery, not icons, carries meaning** — prefer a real domain figure (wafer map, chip,
  trend) over an icon whenever illustrating a concept.

---

## INDEX — what's in this system

**Root**
- `styles.css` — global entry point (import this one file). `@import` manifest only.
- `readme.md` — this guide.
- `SKILL.md` — Agent-Skills-compatible front matter for use in Claude Code.

**`tokens/`** — `fonts.css` (Noto Sans KR + Malgun Gothic stack), `colors.css`,
`typography.css`, `spacing.css` (spacing, radii, accent bars, flat-elevation), `base.css`
(reset + shared `.qie-*` helpers).

**`components/core/`** — reusable React primitives (`window.QIEDeckDesignSystem_3e89fc`):
| Component | Role |
|---|---|
| `TitleBlock` | signature header — teal bar + kicker + navy title |
| `StatCard` | hero KPI metric card (teal strip; gold for final value) |
| `Chip` | rounded label / tag (teal / navy / panel / tealSoft / outline) |
| `FlowBox` | pipeline / architecture node (navy / navy2 / teal / panel) |
| `BeforeAfter` | 적용 전 → 후 comparison row |
| `ProgressRail` | P1·P2·P3 section progress indicator |
| `DataTable` | navy-header zebra table with highlight row |
| `Panel` | generic flat surface with top/left accent strip |
| `Button` | interactive primitive (teal/navy/outline/ghost) |
| `Timeline` | horizontal roadmap axis (done vs upcoming nodes) |

Each has a `.d.ts` (props + starting-point tag), `.prompt.md` (usage), and the directory
carries `card-*.html` `@dsCard` thumbnails.

**`guidelines/`** — foundation specimen cards (`@dsCard`): colours (brand / ink / surface),
type (display / titles / body), spacing (scale / radii+bars), brand (lockup / imagery).

**`ui_kits/deck/`** — the **sample deck**: `index.html` (navigable 12-slide recreation of
the real presentation, all slide types), `deck.css` (slide layouts), `deck-stage.js`
(deck shell). This is the primary reference for composing slides.

**`assets/imagery/`** — domain figures (wafer Failbit maps, chip detection, trend chart).

---

## Using this system

- **Web/HTML**: link `styles.css`, then either compose with the React components
  (`const { TitleBlock, StatCard } = window.QIEDeckDesignSystem_3e89fc`) or copy the
  `ui_kits/deck/deck.css` slide classes for a pure-HTML deck.
- **New slide**: start from the matching `<section class="slide">` in `ui_kits/deck/index.html`.
- **Keep it flat, keep it honest**: no shadows, two accent colours max, and never write a
  validation number as an operating result.
