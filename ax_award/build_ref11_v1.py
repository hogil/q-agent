from pathlib import Path

from bs4 import BeautifulSoup, NavigableString


SOURCE = Path(r"C:\Users\hgcho\Downloads\사내 AI 프로젝트 디자인 개선 (11)\AX Award 지원서.dc.html")
TARGET = Path(r"D:\project\q-agent\ax_award\html\AX_Award_지원서_ref11_v1.html")


CSS = r"""
@page { size: A4; margin: 0; }
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #dfe4eb; }
body { color: #111827; font-family: BatangChe, Batang, serif; }
x-dc, doc-page { display: block; }
helmet { display: none; }
doc-page { width: 794px; margin: 0 auto; }
.page {
  position: relative; width: 794px; height: 1123px; padding: 113px 96px 96px;
  overflow: hidden; background: #fff; font-family: BatangChe, Batang, serif;
  font-size: 13.33px; line-height: 1.38; letter-spacing: 0; page-break-after: always;
}
.page:last-child { page-break-after: auto; }
.page-title { margin: 0 0 10px; text-align: center; color: #0f1e3d; font-size: 29.33px; line-height: 1.18; font-weight: 700; text-decoration: underline; }
.overview, .main-table { width: 604.3px !important; margin-left: -1.15px; border-collapse: collapse; table-layout: fixed; }
.overview { font-size: 13.33px !important; line-height: 1.25; table-layout: fixed; }
.overview td { padding: 3px 8px !important; }
.overview td:first-child { width: 84.7px !important; }
.main-table { margin-top: 7px; }
.main-table .section-head { height: 31px; padding: 4px 10px !important; border: 1px solid #33415e; background: #f2f5fa; }
.head-wrap { display: flex; align-items: center; gap: 9px; }
.head-mark { width: 5px; height: 15px; flex: none; background: #12b5b0; }
.head-text { color: #0f1e3d; font-size: 16px !important; line-height: 1.15; font-weight: 700; }
.main-table .rail { width: 84.7px !important; padding: 5px 4px !important; border: 1px solid #33415e; background: #f2f5fa; color: #0f1e3d; font-size: 14.67px; line-height: 1.35; font-weight: 700; text-align: center; vertical-align: middle; }
.main-table .content { padding: 8px 10px !important; border: 1px solid #33415e; vertical-align: top; }
.section-title { display: flex; align-items: baseline; gap: 7px; margin: 0 0 5px; color: #0f1e3d; font-size: 13.33px; line-height: 1.3; font-weight: 700; }
.section-title .n { color: #0e9c97; font-size: 16px; font-weight: 700; }
.copy { margin: 0; color: #33415e; font-size: 13.33px; line-height: 1.42; }
.micro { color: #4b5b73; font-size: 10.67px; line-height: 1.35; }
.strong { color: #0f1e3d; font-weight: 700; }
.teal { color: #0e9c97; }
.pill { display: inline-block; padding: 2px 7px; border-radius: 3px; background: #0f1e3d; color: #fff; font-size: 10.67px; line-height: 1.25; font-weight: 700; }
.rule { height: 1px; margin: 8px 0; background: #d7deea; }
.page-no { position: absolute; right: 0; bottom: 40px; left: 0; color: #718096; font-size: 10.67px; text-align: center; }

/* P1 */
.ribbon { display: grid; grid-template-columns: repeat(10, 1fr); margin: 7px 0 5px; overflow: hidden; border-radius: 4px; }
.ribbon span { min-height: 43px; padding: 7px 2px 4px; background: #e9edf3; color: #4b5b73; font-size: 10.67px; line-height: 1.2; text-align: center; border-right: 2px solid #fff; }
.ribbon span:nth-child(n+3):nth-child(-n+8) { background: #0f1e3d; color: #fff; }
.ribbon span:nth-child(8) { background: #12b5b0; }
.ribbon-note { display: flex; justify-content: space-between; margin-bottom: 7px; color: #4b5b73; font-size: 10.67px; }
.case-label { display: flex; align-items: center; gap: 8px; margin: 7px 0 5px; }
.time-axis { position: relative; height: 64px; padding: 25px 7px 0; border: 1px solid #d7deea; border-radius: 6px; background: linear-gradient(90deg,#eef1f6 0 45%,#d8dee9 45% 57%,#8694aa 57% 88%,#0f1e3d 88% 100%); }
.time-axis:before { content: ""; position: absolute; top: 37px; right: 10px; left: 10px; height: 2px; background: rgba(255,255,255,.82); }
.time-axis .times { position: absolute; top: 5px; right: 7px; left: 7px; display: flex; justify-content: space-between; color: #0f1e3d; font-size: 10.67px; font-weight: 700; }
.time-axis .segments { display: grid; grid-template-columns: 45fr 12fr 31fr 12fr; color: #fff; font-size: 10.67px; font-weight: 700; text-align: center; }
.time-axis .segments span:first-child { color: #33415e; }
.pain-grid { display: grid; grid-template-columns: repeat(4,1fr); gap: 6px; margin: 5px 0 8px; }
.pain { padding: 5px 7px 5px 10px; border-left: 4px solid #0f1e3d; background: #f5f7fa; color: #33415e; font-size: 13.33px; line-height: 1.35; }
.dual-cost { display: grid; grid-template-columns: 1fr 54px 1fr; align-items: stretch; margin: 5px 0 8px; }
.cost { padding: 8px 10px; border-top: 4px solid #c55252; background: #fbeded; color: #33415e; font-size: 13.33px; line-height: 1.35; }
.balance { display: flex; align-items: center; justify-content: center; color: #0f1e3d; font-size: 12px; font-weight: 700; }
.conditions { display: grid; grid-template-columns: repeat(3,1fr); gap: 0; margin-top: 5px; border: 1px solid #aebbc8; border-radius: 6px; overflow: hidden; }
.condition { position: relative; min-height: 74px; padding: 9px 11px; color: #33415e; font-size: 13.33px; line-height: 1.35; border-right: 1px solid #d7deea; }
.condition:last-child { border-right: 0; }
.condition b { display: block; margin-bottom: 3px; color: #0f1e3d; font-size: 13.33px; }

/* P2 */
.lane-wrap { padding: 7px 8px 6px; border: 1px solid #cbd4e0; border-radius: 6px; background: #fff; }
.lane-svg { display: block; width: 100%; height: 184px; }
.gate { display: grid; grid-template-columns: repeat(5,1fr); margin: 5px 0 8px; border: 1px solid #aebbc8; border-radius: 6px; overflow: hidden; }
.gate > div { min-height: 86px; padding: 7px 6px; border-right: 1px solid #d7deea; color: #33415e; font-size: 13.33px; line-height: 1.3; }
.gate > div:last-child { border-right: 0; }
.gate .level { display: block; margin-bottom: 3px; color: #0f1e3d; font-size: 13.33px; font-weight: 700; }
.gate .approval { background: #e6f7f6; box-shadow: inset 0 4px #12b5b0; }
.gate .future { background: #f3f5f8; color: #718096; }
.e2e { display: grid; grid-template-columns: 1fr 28px 1.2fr 28px 1fr; align-items: center; margin: 5px 0 8px; }
.e2e .stage { min-height: 71px; padding: 9px 10px; border: 1px solid #cbd4e0; color: #33415e; font-size: 13.33px; line-height: 1.35; }
.e2e .stage:nth-child(3) { background: #0f1e3d; color: #fff; }
.e2e .arrow { color: #12b5b0; font-size: 22px; font-weight: 700; text-align: center; }
.roadmap { position: relative; display: grid; grid-template-columns: repeat(4,1fr); gap: 14px; margin-top: 8px; }
.roadmap:before { content:""; position:absolute; top:15px; right:10%; left:10%; height:3px; background:#b9c3d1; }
.roadmap .phase { position: relative; padding-top: 30px; color: #33415e; font-size: 13.33px; line-height: 1.32; text-align: center; }
.roadmap .phase:before { content:""; position:absolute; top:9px; left:50%; width:15px; height:15px; transform:translateX(-50%); border:3px solid #fff; border-radius:50%; background:#0f1e3d; box-shadow:0 0 0 1px #8a97ab; }
.roadmap .phase.active:before { background:#12b5b0; }

/* P3 */
.arch { position: relative; padding: 12px 12px 28px; border: 1.5px solid #0f1e3d; border-radius: 7px; background: #f8fafc; }
.arch-title { color:#0f1e3d; font-size:16px; font-weight:700; }
.arch-sub { margin:2px 0 9px; color:#4b5b73; font-size:10.67px; }
.arch-flow { display:grid; grid-template-columns:1fr 22px 1.25fr 22px 1fr 22px 1fr 22px 1fr; align-items:stretch; }
.arch-node { min-height:82px; padding:8px 6px; border-top:4px solid #0f1e3d; background:#fff; color:#33415e; font-size:10.67px; line-height:1.3; text-align:center; box-shadow:0 0 0 1px #cbd4e0 inset; }
.arch-node.core { border-top-color:#12b5b0; background:#e6f7f6; }
.arch-arrow { align-self:center; color:#12b5b0; font-size:20px; font-weight:700; text-align:center; }
.arch-return { position:absolute; right:20px; bottom:8px; left:20px; color:#0e9c97; font-size:10.67px; font-weight:700; text-align:center; border-top:2px dashed #12b5b0; }
.why { display:grid; grid-template-columns:repeat(3,1fr); gap:7px; margin:5px 0 8px; }
.why > div { padding:7px 8px; background:#f2f5fa; border-left:4px solid #0f1e3d; color:#33415e; font-size:13.33px; line-height:1.35; }
.decision { border:1px solid #cbd4e0; border-radius:6px; overflow:hidden; }
.decision .drow { display:grid; grid-template-columns:1.05fr 1fr 1.55fr; min-height:54px; border-bottom:1px solid #d7deea; }
.decision .drow:last-child { border-bottom:0; }
.decision .drow > div { padding:6px 8px; color:#33415e; font-size:13.33px; line-height:1.3; border-right:1px solid #e4e8ee; }
.decision .drow > div:last-child { border-right:0; background:#f0f9f8; }
.decision .head > div { min-height:0; padding:4px 8px; background:#0f1e3d; color:#fff; font-weight:700; }
.models { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
.model { min-height:172px; padding:8px 9px; border:1px solid #cbd4e0; border-radius:6px; }
.model h4 { margin:0 0 4px; color:#0e9c97; font-size:13.33px; }
.model p { margin:0; color:#33415e; font-size:13.33px; line-height:1.35; }
.metric-bars { display:flex; height:42px; gap:7px; align-items:flex-end; margin:8px 0 3px; }
.metric-bars i { flex:1; display:block; background:#1b3260; }
.metric-bars i:nth-child(1){height:39px;background:#aebbc8}.metric-bars i:nth-child(2){height:25px;background:#8795a9}.metric-bars i:nth-child(3){height:10px}.metric-bars i:nth-child(4){height:4px;background:#12b5b0}
.trend-chart { width:100%; height:66px; margin-top:5px; }

/* P3 cross-render reserve: preserve type size and content, tighten only vertical rhythm. */
.p3 .content { padding-top: 6px !important; padding-bottom: 6px !important; }
.p3 .arch { padding: 8px 12px 20px; }
.p3 .arch-sub { margin: 2px 0 5px; }
.p3 .content > .section-title { margin-bottom: 3px; }
.p3 .why { margin-top: 3px; margin-bottom: 5px; }
.p3 .metric-bars { height: 38px; margin-top: 5px; margin-bottom: 2px; }

/* P4 */
.evidence-layout { display:grid; grid-template-columns:1fr 1.05fr; gap:10px; }
.ladder { position:relative; min-height:180px; padding:2px 0; }
.layer { position:relative; min-height:38px; margin-bottom:4px; padding:5px 10px 4px 42px; color:#33415e; font-size:13.33px; line-height:1.25; background:#eef2f6; clip-path:polygon(0 0,96% 0,100% 50%,96% 100%,0 100%,4% 50%); }
.layer:nth-child(2){margin-left:14px;background:#dfe8ef}.layer:nth-child(3){margin-left:28px;background:#cbe9e7}.layer:nth-child(4){margin-left:42px;background:#12b5b0;color:#fff}
.layer b { color:#0f1e3d; }.layer:nth-child(4) b { color:#fff; }
.trace { padding:8px 9px; border:1px solid #cbd4e0; border-radius:6px; background:#f8fafc; }
.trace-line { display:grid; grid-template-columns:43px 1fr; gap:7px; margin-bottom:6px; color:#33415e; font-size:13.33px; line-height:1.3; }
.trace-line span:first-child { color:#fff; background:#0f1e3d; text-align:center; font-weight:700; border-radius:3px; }
.trace-line:nth-child(2) span:first-child { background:#12b5b0; }
.trace-result { margin-top:7px; padding-top:7px; border-top:1px solid #d7deea; color:#0f1e3d; font-size:13.33px; font-weight:700; }
.ablation { display:grid; grid-template-columns:repeat(4,1fr); gap:5px; margin:5px 0 8px; align-items:end; }
.ablation > div { padding:7px 7px; color:#33415e; font-size:13.33px; line-height:1.3; background:#f2f5fa; border-top:4px solid #aebbc8; }
.ablation > div:nth-child(2){min-height:68px;border-top-color:#8190a6}.ablation > div:nth-child(3){min-height:79px;border-top-color:#1b3260}.ablation > div:nth-child(4){min-height:90px;border-top-color:#12b5b0;background:#e6f7f6}
.rag { display:grid; grid-template-columns:1fr 1fr; gap:8px; margin:5px 0 8px; }
.rag-track { position:relative; min-height:166px; padding:7px 9px 7px 14px; border:1px solid #cbd4e0; border-radius:6px; overflow:hidden; }
.rag-track:before { content:""; position:absolute; top:43px; bottom:13px; left:20px; width:3px; background:#12b5b0; }
.rag-track h4 { margin:0 0 7px; color:#0f1e3d; font-size:13.33px; }
.rag-step { position:relative; margin:0 0 5px 18px; color:#33415e; font-size:13.33px; line-height:1.25; }
.rag-step:before { content:""; position:absolute; top:4px; left:-19px; width:9px; height:9px; border:2px solid #fff; border-radius:50%; background:#12b5b0; box-shadow:0 0 0 1px #0e9c97; }
.verify { display:grid; grid-template-columns:repeat(4,1fr); gap:7px; }
.verify > div { min-height:78px; padding:7px 8px; border:1px solid #cbd4e0; border-top:4px solid #0f1e3d; color:#33415e; font-size:10.67px; line-height:1.3; }
.verify .qmetric { border-top-color:#12b5b0; background:#e6f7f6; }

/* P5 */
.kpis { display:grid; grid-template-columns:repeat(3,1fr); gap:8px; margin:5px 0 8px; }
.kpi { min-height:101px; padding:10px 10px; border:1px solid #cbd4e0; border-top:6px solid #12b5b0; }
.kpi .value { color:#0f1e3d; font-size:24px; line-height:1.05; font-weight:700; }
.kpi .label { margin-top:5px; color:#33415e; font-size:13.33px; line-height:1.3; }
.formula { padding:8px 10px; border:1px solid #aebbc8; background:#f6f8fb; color:#0f1e3d; font-size:13.33px; line-height:1.35; text-align:center; }
.assumption { margin-top:4px; color:#4b5b73; font-size:10.67px; line-height:1.35; text-align:left; }
.effect-grid { display:grid; grid-template-columns:1.2fr 1fr; gap:12px; margin:7px 0 9px; }
.sensitivity { display:grid; gap:6px; }
.srow { display:grid; grid-template-columns:67px 1fr 100px; gap:6px; align-items:center; color:#33415e; font-size:13.33px; }
.bar { height:10px; background:#edf1f5; }.bar i { display:block; height:100%; background:#1b3260; }.srow:first-child .bar i { background:#12b5b0; }
.soft { display:grid; grid-template-columns:1fr 1fr; gap:5px 9px; }
.soft div { padding:4px 0 4px 10px; color:#33415e; font-size:13.33px; line-height:1.32; border-left:3px solid #12b5b0; }
.proof { display:grid; grid-template-columns:repeat(4,1fr); border:1px solid #cbd4e0; border-radius:6px; overflow:hidden; }
.proof > div { min-height:86px; padding:8px 8px; color:#33415e; font-size:13.33px; line-height:1.3; border-right:1px solid #d7deea; }
.proof > div:last-child { border-right:0; }
.proof b { display:block; margin-bottom:3px; color:#0f1e3d; font-size:13.33px; }
.launch { position:relative; display:grid; grid-template-columns:repeat(3,1fr); gap:20px; margin-top:10px; }
.launch:before { content:""; position:absolute; top:15px; right:12%; left:12%; height:3px; background:#aebbc8; }
.launch div { position:relative; padding-top:31px; color:#33415e; font-size:13.33px; line-height:1.32; text-align:center; }
.launch div:before { content:""; position:absolute; top:8px; left:50%; width:16px; height:16px; transform:translateX(-50%); border:3px solid #fff; border-radius:50%; background:#12b5b0; box-shadow:0 0 0 1px #0e9c97; }
@media print { html,body { background:#fff; } doc-page { margin:0; } }
"""


def fragment(soup: BeautifulSoup, html: str):
    holder = BeautifulSoup(html, "html.parser")
    return [node.extract() for node in holder.contents if not (isinstance(node, NavigableString) and not node.strip())]


def content_cell(page):
    table = page.find_all("table", recursive=False)[-1]
    tbody = table.find("tbody", recursive=False)
    rows = tbody.find_all("tr", recursive=False)
    return rows[-1].find_all("td", recursive=False)[-1]


def set_main_shell(page, page_number, heading, rail):
    tables = page.find_all("table", recursive=False)
    main = tables[-1]
    main["class"] = ["main-table"]
    rail_html = "<br>".join(rail.split("\n"))
    main.clear()
    shell = BeautifulSoup(
        f'''<colgroup><col style="width:84.7px"><col></colgroup><tbody>
        <tr><td class="section-head" colspan="2"><div class="head-wrap"><span class="head-mark"></span><span class="head-text">{heading}</span></div></td></tr>
        <tr><td class="rail">{rail_html}</td><td class="content"></td></tr>
        </tbody>''',
        "html.parser",
    )
    for node in list(shell.contents):
        main.append(node.extract())
    footer = page.find("div", string=lambda s: isinstance(s, str) and s.strip() == f"- {page_number} -")
    if footer:
        footer["class"] = ["page-no"]
        footer.attrs.pop("style", None)


def replace_content(page, html):
    cell = content_cell(page)
    cell.clear()
    for node in fragment(page, html):
        cell.append(node)


soup = BeautifulSoup(SOURCE.read_text(encoding="utf-8"), "html.parser")
for tag in list(soup.find_all(["script", "link"])):
    tag.decompose()
for tag in list(soup.find_all("sc-if")):
    tag.decompose()

helmet = soup.find("helmet")
helmet.clear()
style = soup.new_tag("style")
style.string = CSS
helmet.append(style)

pages = soup.select("section.page")
for idx, page in enumerate(pages, 1):
    page.attrs = {
        "class": ["page", f"p{idx}"],
        "data-screen-label": page.get("data-screen-label", "").replace("·", ", "),
    }
    set_main_shell(page, idx, "II. Process" if idx in (1, 2) else ("III. Tech" if idx in (3, 4) else "IIII. 경영효과"),
                   "문제\n정의" if idx == 1 else ("Process\n재설계" if idx == 2 else ("기술적\n해결방안" if idx in (3, 4) else "예상\n성과")))

# P1 overview
p1 = pages[0]
title = p1.find("div", string=lambda s: isinstance(s, str) and s.strip() == "AX Award 지원서")
title["class"] = ["page-title"]
title.attrs.pop("style", None)
overview = p1.find_all("table", recursive=False)[0]
overview["class"] = ["overview"]
overview.clear()
overview_markup = BeautifulSoup(r"""
<colgroup><col style="width:84.7px"><col style="width:359.6px"><col style="width:60px"><col style="width:100px"></colgroup>
<tbody>
 <tr><td colspan="4" style="border:1px solid #33415e;background:#f2f5fa"><div class="head-wrap"><span class="head-mark"></span><span class="head-text">I. 개요</span></div></td></tr>
 <tr><td style="border:1px solid #33415e;background:#f2f5fa;text-align:center;font-weight:700">지원부문</td><td colspan="3" style="border:1px solid #33415e">제조 AX 부문</td></tr>
 <tr><td style="border:1px solid #33415e;background:#f2f5fa;text-align:center;font-weight:700">팀 / 그룹</td><td style="border:1px solid #33415e">제조기술센터 품질기술그룹</td><td style="border:1px solid #33415e;background:#f2f5fa;text-align:center;font-weight:700">대표자</td><td style="border:1px solid #33415e">홍길동</td></tr>
 <tr><td style="border:1px solid #33415e;background:#f2f5fa;text-align:center;font-weight:700">제목</td><td colspan="3" style="border:1px solid #33415e"><b>감지 이후 조사, 판정, 조치까지 E2E로 연결하는 Q-Agent</b><br>이상 접수부터 확정 이력 재사용까지 전 과정을 재설계한다.</td></tr>
 <tr><td style="border:1px solid #33415e;background:#f2f5fa;text-align:center;font-weight:700">적용시점</td><td colspan="3" style="border:1px solid #33415e">2026-09-01 ~ 2028-08-31, 24개월</td></tr>
 <tr><td style="border:1px solid #33415e;background:#f2f5fa;text-align:center;font-weight:700">횡전개 범위</td><td colspan="3" style="border:1px solid #33415e">포토 1개 공정 → etch, CMP 3개 공정 → 품질과 공정 엔지니어 약 1,000명</td></tr>
</tbody>
""", "html.parser")
for node in list(overview_markup.contents):
    overview.append(node.extract())

replace_content(p1, r"""
<div class="section-title"><span class="n">1.</span><span>감지는 수 초, 처리 결정은 수 시간인 E2E 공백</span></div>
<p class="copy">이상 검출 뒤 여러 시스템과 과거 사고를 직접 대조한다. 조사 순서와 근거가 개인 경험에 남아 야간 대응, 판정 일관성, 이력 재사용이 함께 끊긴다.</p>
<div class="ribbon"><span>이상<br>발생</span><span>알람<br>확인</span><span>Trend<br>확인</span><span>MES<br>조회</span><span>변경점<br>대조</span><span>과거 사고<br>검색</span><span>원인<br>판정</span><span>조치<br>결정</span><span>보고</span><span>이력<br>등록</span></div>
<div class="ribbon-note"><b>진한 6단계가 반복 수작업 구간</b><span>SPC, MES, 설비 이력, 이미지, 사고 원장을 교차 확인</span></div>
<div class="case-label"><span class="pill">사례형 시나리오</span><b class="micro">PHOD03 CD 급등 1건</b></div>
<div class="time-axis"><div class="times"><span>02:14 검출</span><span>08:30 조사 착수</span><span>16:00 처리 결정</span></div><div class="segments"><span>무대응 6h</span><span>인수</span><span>교차 조사 4h+</span><span>결재</span></div></div>
<div class="section-title" style="margin-top:8px"><span class="n">2.</span><span>현장에서 반복되는 네 가지 손실</span></div>
<div class="pain-grid"><div class="pain"><b class="strong">조사 지연</b><br>반복 조회</div><div class="pain"><b class="strong">판정 편차</b><br>담당자별 결론 차이</div><div class="pain"><b class="strong">취약시간</b><br>야간 착수 지연</div><div class="pain"><b class="strong">이력 단절</b><br>승인 근거 미재사용</div></div>
<div class="section-title"><span class="n">3.</span><span>오판 비용은 양쪽에서 발생한다</span></div>
<div class="dual-cost"><div class="cost"><b class="strong">진성 놓침</b><br>불량이 후공정과 고객까지 확대</div><div class="balance">판정<br>균형</div><div class="cost"><b class="strong">가성 Hold</b><br>정상 Lot 정지로 수율과 TAT 손실</div></div>
<div class="section-title"><span class="n">4.</span><span>지금 시작할 조건</span></div>
<div class="conditions"><div class="condition"><b>데이터</b>Trend, 설비 이력, 사고 원장, 이미지가 이미 축적</div><div class="condition"><b>실행 기반</b>조사 코어와 생산 백엔드 연결 구조를 선행 구현</div><div class="condition"><b>검증 체계</b>3Q 그림자 운영으로 처리 시간과 일치율을 실측</div></div>
""")

# P2
p2 = pages[1]
replace_content(p2, r"""
<div class="section-title"><span class="n">1.</span><span>접수부터 확정 이력 재사용까지 E2E 전체 재설계</span></div>
<div class="lane-wrap">
<svg class="lane-svg" viewBox="0 0 608 184" aria-label="Human과 Q-Agent 두 개 작업 흐름">
 <defs><marker id="p2arrow" markerWidth="8" markerHeight="8" refX="6" refY="4" orient="auto"><path d="M0,0 L8,4 L0,8Z" fill="#12B5B0"/></marker></defs>
 <text x="72" y="17" text-anchor="middle" font-size="11" fill="#4b5b73">인지</text><text x="166" y="17" text-anchor="middle" font-size="11" fill="#4b5b73">조사</text><text x="260" y="17" text-anchor="middle" font-size="11" fill="#4b5b73">판정</text><text x="354" y="17" text-anchor="middle" font-size="11" fill="#4b5b73">조치 결정</text><text x="448" y="17" text-anchor="middle" font-size="11" fill="#4b5b73">보고</text><text x="542" y="17" text-anchor="middle" font-size="11" fill="#4b5b73">등록</text>
 <rect x="48" y="28" width="520" height="47" rx="5" fill="#f2f5fa" stroke="#cbd4e0"/><text x="7" y="53" font-size="11" font-weight="700" fill="#0f1e3d">Human</text><text x="307" y="43" text-anchor="middle" font-size="10.7" font-weight="700" fill="#4b5b73">전체 업무 약 14h [현업 산정]</text>
 <path d="M72 51H542" stroke="#8a97ab" stroke-width="2"/><g fill="#8a97ab"><circle cx="72" cy="51" r="5"/><circle cx="166" cy="51" r="5"/><circle cx="260" cy="51" r="5"/><circle cx="354" cy="51" r="5"/><circle cx="448" cy="51" r="5"/><circle cx="542" cy="51" r="5"/></g><text x="307" y="69" text-anchor="middle" font-size="10.7" fill="#4b5b73">수동 조회와 판단, 개인 기록</text>
 <rect x="48" y="101" width="520" height="48" rx="5" fill="#0f1e3d"/><text x="4" y="128" font-size="11" font-weight="700" fill="#0f1e3d">Q-Agent</text><text x="307" y="114" text-anchor="middle" font-size="10.7" font-weight="700" fill="#a7e2df">조사 코어 수 초 [목표]</text>
 <path d="M72 125H542" stroke="#12B5B0" stroke-width="2.5"/><g fill="#12B5B0" stroke="#fff"><circle cx="72" cy="125" r="5"/><circle cx="166" cy="125" r="5"/><circle cx="260" cy="125" r="5"/><circle cx="354" cy="125" r="5"/><circle cx="448" cy="125" r="5"/><circle cx="542" cy="125" r="5"/></g>
 <g fill="#a7e2df" font-size="10.7" text-anchor="middle"><text x="72" y="143">adapter</text><text x="166" y="143">investigator</text><text x="260" y="143">judgment</text><text x="354" y="143">action</text><text x="448" y="143">answer</text><text x="542" y="143">register</text></g>
 <path d="M542 153 C500 179 196 179 166 153" fill="none" stroke="#12B5B0" stroke-width="2" stroke-dasharray="5 4" marker-end="url(#p2arrow)"/><text x="354" y="176" text-anchor="middle" font-size="10.7" font-weight="700" fill="#0e9c97">사람의 승인, 수정, 반려 이력을 다음 조사 근거로 환류</text>
</svg>
</div>
<div class="section-title" style="margin-top:8px"><span class="n">2.</span><span>L1~L5 권한과 L4 승인 gate</span></div>
<div class="gate"><div><span class="level">L1 알림</span>이상 사실을 즉시 전달</div><div><span class="level">L2 소견</span>유형과 유사 사고를 제시</div><div><span class="level">L3 제안</span>현장 점검안을 제시</div><div class="approval"><span class="level">L4 승인</span>Lot Hold는 담당자 승인 후 실행</div><div class="future"><span class="level">L5 자동조치</span>2차년 지표 통과 항목만 개별 심의</div></div>
<div class="section-title"><span class="n">3.</span><span>업무의 시작과 끝을 함께 바꾼다</span></div>
<div class="e2e"><div class="stage"><b class="strong">접수</b><br>SPC 이벤트 또는 Chat 질문을 표준 사건으로 변환</div><div class="arrow">→</div><div class="stage"><b>조사와 판정</b><br>도구 호출, 근거 조합, 안전 검증을 한 코어에서 수행</div><div class="arrow">→</div><div class="stage"><b class="strong">확정과 재사용</b><br>승인, 수정, 반려 결과를 다음 사건의 검색 근거로 등록</div></div>
<div class="section-title"><span class="n">4.</span><span>확산 조건을 분기별로 검증한다</span></div>
<div class="roadmap"><div class="phase active"><b class="strong">3Q Shadow</b><br>담당 판정과 병행해 기준선 실측</div><div class="phase"><b class="strong">4Q 무인 접수</b><br>야간 접수 누락과 채택률 확인</div><div class="phase"><b class="strong">5Q etch 확산</b><br>조사 코어 변경 0을 통과 조건으로 확인</div><div class="phase"><b class="strong">8Q 표준화</b><br>3개 공정 검증 후 약 1,000명 적용</div></div>
""")

# P3
p3 = pages[2]
replace_content(p3, r"""
<div class="arch"><div class="arch-title">품질 AI Agent Architecture</div><div class="arch-sub">입구에서 등록까지 다섯 단계가 하나의 조사 코어와 승인 흐름을 공유한다.</div><div class="arch-flow"><div class="arch-node"><b class="strong">① 입구</b><br>SPC 이벤트<br>Chat 질문</div><div class="arch-arrow">→</div><div class="arch-node core"><b class="strong">② Router 조사</b><br>도구 선택<br>가설 갱신</div><div class="arch-arrow">→</div><div class="arch-node"><b class="strong">③ 판정</b><br>근거 조합<br>검증 5칙</div><div class="arch-arrow">→</div><div class="arch-node"><b class="strong">④ 조치</b><br>L1~L5<br>L4 승인</div><div class="arch-arrow">→</div><div class="arch-node"><b class="strong">⑤ 등록</b><br>승인 이력<br>재사용</div></div><div class="arch-return">확정 이력과 현업 피드백을 조사 규칙, 검색 코퍼스, 평가셋에 반영</div></div>
<div class="section-title" style="margin-top:8px"><span class="n">1.</span><span>Agent 당위성</span></div>
<div class="why"><div><b class="strong">조사 순서가 가변</b><br>직전 결과에 따라 다음 데이터와 도구가 달라진다.</div><div><b class="strong">데이터 형식이 혼합</b><br>Trend, 이미지, 문서, 정형 DB를 함께 판단한다.</div><div><b class="strong">근거가 감사 대상</b><br>결론뿐 아니라 원문, 수치, 승인 이력을 남겨야 한다.</div></div>
<div class="section-title"><span class="n">2.</span><span>알고리즘 선택</span></div>
<div class="decision"><div class="drow head"><div>문제</div><div>기각</div><div>채택과 이유</div></div><div class="drow"><div><b>Trend 이상</b><br>완만한 drift 포함</div><div>고정 임계 규칙</div><div><b>합성 데이터 감지 + LLM</b><br>감지는 모델, 변경점 연결은 LLM</div></div><div class="drow"><div><b>불량 이미지</b><br>미등록 패턴 포함</div><div>분류기 단독</div><div><b>ConvNeXt V2 + contrastive</b><br>분류와 유사 사례 검색을 함께 사용</div></div><div class="drow"><div><b>사고 검색</b><br>번호와 전문 용어</div><div>벡터 검색 단독</div><div><b>meta + BM25 + embedding + rerank</b><br>키 조회 뒤 제한 범위에서 결합 검색</div></div></div>
<div class="section-title" style="margin-top:8px"><span class="n">3.</span><span>성능: 선행 전문 모델 실측</span></div>
<div class="models"><div class="model"><h4>선행 이미지 프로토타입 A</h4><p>무라벨 이미지 대조 학습으로 유사 패턴을 찾고, 운영 확정은 composite map과 원본 이미지로 수행한다.</p><div class="metric-bars"><i></i><i></i><i></i><i></i></div><p><b class="strong">noise ratio 6.20% → 0.52%</b><br>군집 ARI 0.823 → 0.860<br>43 class, 900 wafer 선행 실측</p></div><div class="model"><h4>Trend 전문 모델</h4><p>라벨이 부족한 drift, spike, level step을 합성 주입하고 복귀형 파형은 정상 학습에 포함한다.</p><svg class="trend-chart" viewBox="0 0 250 66"><path d="M3 54H247M3 33H247M3 12H247" stroke="#d7deea"/><polyline points="4,46 30,44 55,43 80,41 104,40 128,31 153,27 178,22 204,16 244,13" fill="none" stroke="#12B5B0" stroke-width="3"/><path d="M128 8V58" stroke="#0f1e3d" stroke-dasharray="4 3"/><text x="133" y="18" font-size="10.7" fill="#0f1e3d">변화 시점</text></svg><p><b class="strong">1단 감지 + 2단 LLM 판독</b><br>Grad-CAM과 임계 sweep으로 근거와 운영 기준을 남긴다.</p></div></div>
""")

# P4
p4 = pages[3]
replace_content(p4, r"""
<div class="section-title"><span class="n">4.</span><span>개선 과정: Agent 추가에 따른 근거 보강</span></div>
<div class="ablation"><div><b class="strong">LLM 단독</b><br>알람 원문만 요약</div><div><b class="strong">+ Trend</b><br>변화 시점과 drift 확인</div><div><b class="strong">+ Image</b><br>유사 패턴과 사고 후보 연결</div><div><b class="strong">+ RAG와 DB</b><br>변경점, 사고번호, 조치 범위를 인용</div></div>
<div class="section-title"><span class="n">5.</span><span>Evidence ladder와 A/B 실행 trace</span></div>
<div class="evidence-layout"><div class="ladder"><div class="layer"><b>1층 입력</b><br>알람 JSON 또는 이미지</div><div class="layer"><b>2층 관측</b><br>Trend와 이미지 결과</div><div class="layer"><b>3층 이력</b><br>설비 변경점과 사고 원장</div><div class="layer"><b>4층 확정</b><br>근거 인용, 조치안, 승인 기록</div></div><div class="trace"><div class="trace-line"><span>A</span><div><b class="strong">이미지 진입</b><br>유사 이미지 → 사고번호 → 변경점</div></div><div class="trace-line"><span>B</span><div><b class="strong">알람 진입</b><br>Trend 변화 → 공통 설비 → 사고번호</div></div><div class="trace-result">입구만 다르고 Router 조사, 판정, L4 승인, 등록 흐름은 같다.<br><span class="teal">Router T=0 / Answer T=0.3</span></div></div></div>
<div class="section-title" style="margin-top:6px"><span class="n">6.</span><span>LLM Wiki와 Graph RAG <span class="micro">[2차년 확장 설계]</span></span></div>
<div class="rag"><div class="rag-track"><h4>LLM Wiki: 원문 우선 검색</h4><div class="rag-step"><b class="strong">사고 원장 RDB</b><br>담당자가 확정한 원문을 먼저 조회</div><div class="rag-step"><b class="strong">meta 범위 제한</b><br>사고번호, 공정, 설비, 기간으로 후보 축소</div><div class="rag-step"><b class="strong">결합 검색</b><br>BM25와 embedding 결과를 융합하고 rerank</div><div class="rag-step"><b class="strong">인용 반환</b><br>근거 문장과 문서 위치를 판정서에 기록</div></div><div class="rag-track"><h4>Graph RAG: 관계 우선 탐색</h4><div class="rag-step"><b class="strong">사건 node</b><br>Lot, 설비, recipe, PM, 자재를 연결</div><div class="rag-step"><b class="strong">공통성 계산</b><br>같은 조합과 반복 경로를 우선 확인</div><div class="rag-step"><b class="strong">후보 확장</b><br>연결된 사고와 조치 결과를 조회</div><div class="rag-step"><b class="strong">Wiki 교차 확인</b><br>관계 후보를 원문 인용으로 확정</div></div></div>
<div class="section-title"><span class="n">7.</span><span>성능과 안전 검증</span></div>
<div class="verify"><div class="qmetric"><b class="strong">Q-Agent 실측</b><br><span style="font-size:18px;font-weight:700;color:#0f1e3d">recall@10 0.500</span><br>골든 4건, 색인 50건</div><div><b class="strong">선행 검색 프로토타입 B</b><br>26질의 hit@1 1.000<br>하드셋 38질의 0.957</div><div><b class="strong">선행 이미지 프로토타입 A</b><br>noise 0.52%<br>AMI 0.956, ARI 0.860<br>43 class, 900 wafer</div><div><b class="strong">안전 gate 운영 목표</b><br>근거 없는 판단 0건<br>미승인 L4 실행 0건<br>무인 접수 누락 0건</div></div>
""")

# P5
p5 = pages[4]
replace_content(p5, r"""
<div class="section-title"><span class="n">1.</span><span>유형효과: 판정 업무 시간의 환산 가치</span></div>
<div class="kpis"><div class="kpi"><div class="value">200억<span style="font-size:13.33px"> 원/년</span></div><div class="label">확산 완료 후 약 1,000명 적용 시 시간 환산 가치</div></div><div class="kpi"><div class="value">57.5배</div><div class="label">연 편익/비용 배수<br>연 투자 347,794,165원 기준</div></div><div class="kpi"><div class="value">6.3일</div><div class="label">연 투자액 기준 회수 기간<br><b class="strong">12.7일</b>은 2개년 총투자액 기준</div></div></div>
<div class="formula">[(개선 전 4h ÷ 8h) - (개선 후 2h ÷ 8h)] × 연봉 80,000,000원 × 1,000명 = 연 200억 원<div class="assumption">4h와 2h는 ROI 산정 가정이다. 3Q Shadow에서 실제 처리 시간을 측정해 대체하며, 인원 감축 효과로 계산하지 않는다.</div></div>
<div class="section-title" style="margin-top:9px"><span class="n">2.</span><span>민감도와 무형효과</span></div>
<div class="effect-grid"><div class="sensitivity"><div class="srow"><span>2.0h 목표</span><div class="bar"><i style="width:100%"></i></div><b>200억 / 57.5배</b></div><div class="srow"><span>2.5h</span><div class="bar"><i style="width:75%"></i></div><span>150억 / 43.1배</span></div><div class="srow"><span>3.0h</span><div class="bar"><i style="width:50%"></i></div><span>100억 / 28.8배</span></div><div class="srow"><span>3.5h</span><div class="bar"><i style="width:25%"></i></div><span>50억 / 14.4배</span></div><div class="micro">30분만 줄여도 편익/비용 배수는 14.4배다.</div></div><div class="soft"><div><b class="strong">야간 공백 축소</b><br>발생부터 조사 착수까지 측정</div><div><b class="strong">판정 편차 축소</b><br>동일 현상 일치율 측정</div><div><b class="strong">감사 대응</b><br>원문, 수치, 승인 기록 보존</div><div><b class="strong">이력 재사용</b><br>확정분을 검색과 평가에 반영</div></div></div>
<div class="section-title"><span class="n">3.</span><span>선행 추진 실적</span></div>
<div class="proof"><div><b>설계와 구현</b>설계 문서 31종<br>조사 코어와 생산 백엔드 4종 연결 구조</div><div><b>Q-Agent 실측</b>recall@10 0.500<br>골든 4건, 색인 50건</div><div><b>선행 검색 프로토타입 B</b>26질의 hit@1 1.000<br>하드셋 38질의 0.957</div><div><b>선행 이미지 프로토타입 A</b>noise 0.52%<br>AMI 0.956, ARI 0.860</div></div>
<div class="section-title" style="margin-top:9px"><span class="n">4.</span><span>성과 확정 일정</span></div>
<div class="launch"><div><b class="strong">3Q Shadow</b><br>조치 미실행 상태에서 4h 가정과 판정 일치율 측정</div><div><b class="strong">4Q 무인 접수</b><br>누락, 처리 시간, 조치안 채택률을 분기 보고</div><div><b class="strong">2차년 L5 심의</b><br>승인율과 오탐 기준 통과 항목만 자동조치 검토</div></div>
""")

# Naturalize punctuation and remove the prohibited middle dot throughout visible text.
for text_node in list(soup.find_all(string=True)):
    if text_node.parent and text_node.parent.name not in ("style",):
        value = str(text_node).replace("·", ", ").replace("—", ": ")
        value = value.replace("다섯 정거장이 통째로 내려온다", "다섯 단계를 자동 실행한다")
        value = value.replace("답이 자란다", "근거가 보강된다")
        if value != str(text_node):
            text_node.replace_with(value)

TARGET.parent.mkdir(parents=True, exist_ok=True)
TARGET.write_text(str(soup), encoding="utf-8")
print(TARGET)
