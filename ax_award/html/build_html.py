"""디자인 프로젝트의 dc.html -> 사내에서 바로 열리는 단독 HTML 1장.

입력  : ax_dc.html (Claude Design 프로젝트 `AX Award 지원서.dc.html` 원문)
출력  : AX_Award_지원서.html  — 외부 의존 0. 브라우저로 열고 Ctrl+P -> A4 -> PDF 저장하면 5장.

하는 일
  1) 디자인 앱 스캐폴딩 제거: <x-dc> <helmet> <doc-page> <sc-if>(루브릭 배지) + 외부 css/js 링크
  2) 페이지 5개를 210x297mm 고정 박스로 고정, @page A4 margin 0
  3) 본문이 10px(=7.5pt)로 짜여 페이지 하단 40%가 비는 문제 -> transform:scale(K) 로 확대.
     내부 레이아웃 폭을 794/K 로 줄이고 K배 확대하므로 글자만 커지는 게 아니라
     줄바꿈까지 다시 흘러 페이지가 채워진다. K 는 measure.py 로 실측해 정한다.
"""
import re, pathlib, sys

HERE = pathlib.Path(__file__).parent
SRC = HERE / "ax_dc.html"
OUT = HERE / "AX_Award_지원서.html"

PAGE_W, PAGE_H = 794, 1123          # A4 @96dpi = 210x297mm
K = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0

raw = SRC.read_text(encoding="utf-8")
raw = re.sub(r"<sc-if\b.*?</sc-if>", "", raw, flags=re.S)     # 심사 루브릭 배지(원래 숨김)

import patches                                                # 조사 흐름 교정(patches.py)
raw = patches.apply(raw)
# 등폭 블록 안의 한글도 심어둔 폰트로 떨어지게 한다(사내 PC 기본 등폭엔 한글이 없다).
raw = raw.replace("ui-monospace,monospace", "ui-monospace,Consolas,'AXNoto',monospace")
sections = re.findall(r'<section class="page"[^>]*>(.*?)</section>', raw, flags=re.S)
assert len(sections) == 5, f"페이지 5장이 아니다: {len(sections)}"

TAG = re.findall(r'<section class="page"([^>]*)>', raw)
LABELS = [re.search(r'data-screen-label="([^"]*)"', t).group(1) for t in TAG]

# --- 재배치 -------------------------------------------------------------
# 원본은 2페이지에 '문제정의 뒷부분 + Process 재설계' 가 다 얹혀 있어 혼자 꽉 차고,
# 나머지 네 장이 25% 씩 빈다. 확대율은 제일 빡빡한 장에 묶이므로 2페이지가 전체를 눌렀다.
# '3. 왜 중요한가' 한 덩이를 1페이지 끝(같은 '문제 정의' 칸)으로 옮겨 균형을 맞춘다.
from bs4 import BeautifulSoup


def deepest_td(soup, kw):
    """kw 를 품은 가장 안쪽 td (중첩 표에서 바깥 td 를 잡지 않도록)."""
    hits = [td for td in soup.find_all("td") if kw in td.get_text()]
    return min(hits, key=lambda td: len(td.find_all(True)))


def move_block(src_html, dst_html, start_kw, end_kw):
    src, dst = BeautifulSoup(src_html, "html.parser"), BeautifulSoup(dst_html, "html.parser")
    s_td, d_td = deepest_td(src, start_kw), deepest_td(dst, end_kw)
    kids = [c for c in s_td.children if getattr(c, "name", None)]
    i = next(n for n, c in enumerate(kids) if start_kw in c.get_text())
    j = next(n for n, c in enumerate(kids) if "기존 대안 검토" in c.get_text())
    for c in kids[i:j]:
        d_td.append(c.extract())
    return str(src), str(dst)


def merge_td(src_html, dst_html, src_kw, dst_kw):
    """src 페이지의 칸 내용을 dst 페이지의 같은 절 칸 끝으로 옮기고, 빈 표는 없앤다."""
    src, dst = BeautifulSoup(src_html, "html.parser"), BeautifulSoup(dst_html, "html.parser")
    s_td, d_td = deepest_td(src, src_kw), deepest_td(dst, dst_kw)
    for c in [c for c in s_td.children if getattr(c, "name", None)]:
        d_td.append(c.extract())
    s_td.find_parent("table").decompose()
    return str(src), str(dst)


# 3페이지 위에 얹혀 있던 `Process 재설계(계속)` 를 2페이지로 내린다.
# 3페이지가 97% 로 꽉 차 확대율을 혼자 묶고 있었고, 2페이지는 71% 로 비어 있었다.
# 옮기면 재설계가 2페이지에서 끝나고 3페이지는 III. Tech 로만 시작한다.
# 소스 (6) 세대는 원저자가 이미 2페이지로 내렸다 — 두 마커가 같은 페이지라 이 이동은 불필요.
MERGE_REDESIGN = False
if MERGE_REDESIGN:
    sections[2], sections[1] = merge_td(sections[2], sections[1], "현업 활용·확산", "E2E 전체 대체")

# v2 소스(2026-08-09)는 원저자가 페이지 배분을 다시 했다 — 아래 재배치는 v1 전용이라 끈다.
# (v1 에서는 2페이지에만 내용이 몰려 확대율이 거기 묶였다. ax_dc_v1.html 참고)
REPAGINATE_V1 = False
if REPAGINATE_V1:
    sections[1], sections[0] = move_block(sections[1], sections[0], "왜 중요한가", "동선 안에 반복")

# --- Tech 두 장 교체 ----------------------------------------------------
# overrides/*.html 이 3·4페이지의 '기술적 해결 방안' 칸 내용을 통째로 갈아끼운다.
# (Router 6결정 / Agentic RAG 2트랙 / 이미지 대조학습 / 프롬프트 성장 / 학습 3단)
OVR = HERE / "overrides"


def replace_td(section_html, kw, frag):
    soup = BeautifulSoup(section_html, "html.parser")
    td = deepest_td(soup, kw)
    td.clear()
    td.append(BeautifulSoup(frag.read_text(encoding="utf-8"), "html.parser"))
    return str(soup)


for marker, frag in [("왜 Agent Orchestration", "p3_tech.html"),
                     ("실행 트레이스", "p4_tech.html")]:
    path = OVR / frag
    if path.exists():
        idx = next(n for n, s in enumerate(sections) if marker in s)
        sections[idx] = replace_td(sections[idx], marker, path)
        print(f"  override: p{idx + 1} ← {frag}")

# 원본 section 인라인 스타일에서 padding 만 떼어 .fit 으로 옮긴다(나머지는 그대로).
PAD = "88px 96px 52px"
INNER = ("font-family:'AXNoto','Malgun Gothic','맑은 고딕',sans-serif;"
         "font-size:10px;line-height:1.5;color:#111827")

# 폰트를 파일 안에 심는다 — 사내 PC 에 Noto Sans KR 이 없어도 자간이 안 바뀐다(make_font.py 참고).
B64 = (HERE / "noto-subset.b64").read_text(encoding="utf-8").strip()
FONT_FACE = (
    "@font-face{font-family:'AXNoto';"
    f"src:url(data:font/woff2;base64,{B64}) format('woff2');"
    "font-weight:100 900;font-style:normal;font-display:block}"
)

pages = "\n".join(
    f'<section class="page" aria-label="{lab}">\n'
    f'  <div class="fit">{body}</div>\n'
    f"</section>"
    for lab, body in zip(LABELS, sections)
)

HTML = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<title>AX Award 지원서 — Q-Agent</title>
<style>
  {FONT_FACE}
  :root {{ --k: {K}; --pw: {PAGE_W}px; --ph: {PAGE_H}px; }}
  * {{ box-sizing: border-box; }}
  html, body {{ margin: 0; padding: 0; background: #E9ECF1; }}

  section.page {{
    width: var(--pw); height: var(--ph);
    margin: 0 auto 18px; position: relative; overflow: hidden;
    background: #fff; box-shadow: 0 2px 12px rgba(0,0,0,.18);
    print-color-adjust: exact; -webkit-print-color-adjust: exact;
  }}
  /* 레이아웃은 794/K 폭에서 흐르고, 그 결과를 K배로 확대해 A4 를 채운다. */
  section.page > .fit {{
    width: calc(var(--pw) / var(--k)); height: calc(var(--ph) / var(--k));
    padding: {PAD}; position: relative; overflow: hidden;
    transform: scale(var(--k)); transform-origin: top left;
    {INNER};
    display: flex; flex-direction: column;
  }}
  /* 페이지 하단이 허옇게 비지 않게 마지막 표를 바닥까지 늘린다(원본 docx 도 행 높이로 채웠다).
     늘어난 높이는 안쪽 행에 배분되므로 글자 크기는 페이지마다 그대로다. */
  section.page > .fit > table:last-of-type {{ flex: 1 1 auto; }}

  @page {{ size: A4; margin: 0; }}
  @media print {{
    html, body {{ background: #fff; }}
    section.page {{
      width: 210mm; height: 297mm; margin: 0; box-shadow: none;
      break-after: page; break-inside: avoid;
    }}
    section.page:last-child {{ break-after: auto; }}
  }}
</style>
</head>
<body>
{pages}
</body>
</html>
"""

OUT.write_text(HTML, encoding="utf-8")
print(f"K={K}  ->  {OUT}  ({len(HTML):,} bytes, {len(sections)} pages)")
