# -*- coding: utf-8 -*-
"""지원서에 넣을 인포그래픽 PNG 를 그린다.

표만으로는 심사위원 눈을 못 끈다. 여기서 만든 PNG 를 build_docx.py 가 셀에 삽입한다.
규칙(ax_award/CLAUDE.md §0): 리소스 수치 금지 · 없는 수치 금지 · 5장 예산 안.

사용: python figures.py   → out/fig/*.png 생성
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FIG_DIR = Path(__file__).parent / "out" / "fig"
DPI = 300
PX_PER_CM = DPI / 2.54          # 118.1

# 색 — 문서의 붉은 강조와 맞춘다
RED = (192, 0, 0)
RED_FILL = (251, 228, 228)
GRAY = (110, 110, 110)
GRAY_FILL = (242, 242, 242)
BLUE = (46, 90, 150)
BLUE_FILL = (232, 238, 247)
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)

# 도해 안 글자는 산세리프로 간다. 본문(바탕체)과 층이 갈려 그림이 그림으로 읽힌다.
FONT_PATH = r"C:\Windows\Fonts\malgun.ttf"
FONT_BOLD = r"C:\Windows\Fonts\malgunbd.ttf"

# 확장 팔레트 — 층마다 색을 달리해 스윔레인이 구분된다
INK = (28, 32, 38)
SLATE = (96, 106, 120)
LINE = (176, 186, 198)
BAND_IN = (238, 243, 250)
BAND_MODEL = (243, 240, 250)
BAND_ORCH = (253, 236, 236)
BAND_OUT = (240, 246, 240)
VIOLET = (108, 76, 168)
GREEN = (42, 122, 78)
NAVY = (31, 78, 121)            # #1F4E79 — 수치·도착점 강조는 전부 이 색으로 통일한다
NAVY_FILL = (233, 240, 248)
DIV = (200, 205, 214)


def cm(v: float) -> int:
    return int(round(v * PX_PER_CM))


def save(img: Image.Image, name: str, pad_cm: float = 0.05) -> Path:
    """캔버스 하단의 그리지 않은 흰 여백을 잘라 저장한다.

    build_docx 는 폭만 지정해 넣으므로 높이는 비율로 따라온다 — 잘라낸 만큼
    문서에서 그림 아래 죽은 공백이 사라진다. 폭은 건드리지 않는다.
    """
    bbox = img.convert("L").point(lambda v: 0 if v > 250 else 255).getbbox()
    if bbox:
        bottom = min(img.height, bbox[3] + cm(pad_cm))
        if bottom < img.height:
            img = img.crop((0, 0, img.width, bottom))
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    p = FIG_DIR / f"{name}.png"
    img.save(p, dpi=(DPI, DPI))
    return p


def font(size_pt: float, bold: bool = False):
    px = int(round(size_pt * DPI / 72))
    try:
        return ImageFont.truetype(FONT_BOLD if bold else FONT_PATH, px)
    except OSError:
        return ImageFont.truetype(FONT_PATH, px)


def text_w(d: ImageDraw.ImageDraw, s: str, f) -> int:
    return int(d.textlength(s, font=f))


def centered(d, box, s, f, fill=BLACK):
    x0, y0, x1, y1 = box
    w = text_w(d, s, f)
    asc, desc = f.getmetrics()
    h = asc + desc
    d.text((x0 + (x1 - x0 - w) / 2, y0 + (y1 - y0 - h) / 2), s, font=f, fill=fill)


def wrap_lines(d, s, f, max_w):
    """max_w 안에 들어가게 어절 단위로 접는다. 한 어절이 넘치면 글자 단위로 쪼갠다."""
    out, cur = [], ""
    for tok in s.split(" "):
        t = tok if not cur else cur + " " + tok
        if not cur or text_w(d, t, f) <= max_w:
            cur = t
        else:
            out.append(cur)
            cur = tok
    if cur:
        out.append(cur)
    res = []
    for ln in out:
        while text_w(d, ln, f) > max_w and len(ln) > 1:
            k = len(ln)
            while k > 1 and text_w(d, ln[:k], f) > max_w:
                k -= 1
            res.append(ln[:k])
            ln = ln[k:]
        res.append(ln)
    return res


def fit_wrap(d, s, max_w, max_lines, sizes, bold=False):
    """폰트를 한 단계씩 내려가며 max_lines 안에 접히는 크기를 고른다."""
    for sz in sizes:
        f = font(sz, bold)
        lines = wrap_lines(d, s, f, max_w)
        if len(lines) <= max_lines:
            return f, lines
    f = font(sizes[-1], bold)
    return f, wrap_lines(d, s, f, max_w)[:max_lines]


def block(d, box, s, sizes, fill=BLACK, bold=False, max_lines=2, pad=None, line_gap=1.18):
    """상자 안에 접어 넣고 세로 가운데 정렬. 넘치면 폰트를 내린다 (글자 잘림 방지 가드)."""
    x0, y0, x1, y1 = box
    p = cm(0.10) if pad is None else pad
    f, lines = fit_wrap(d, s, (x1 - x0) - 2 * p, max_lines, sizes, bold)
    asc, desc = f.getmetrics()
    lh = int((asc + desc) * line_gap)
    total = lh * len(lines)
    ty = y0 + max(0, (y1 - y0 - total) / 2)
    for i, ln in enumerate(lines):
        w = text_w(d, ln, f)
        d.text((x0 + (x1 - x0 - w) / 2, ty + i * lh), ln, font=f, fill=fill)
    return ty + total


def rounded(d, box, fill, outline, width=3, r=14):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def card(d, box, fill, outline, width=3, r=12, shadow=True):
    """살짝 그림자를 깐 상자. 층이 생겨 상자 나열처럼 안 보인다."""
    if shadow:
        off = max(2, int(cm(0.035)))
        d.rounded_rectangle((box[0] + off, box[1] + off, box[2] + off, box[3] + off),
                            radius=r, fill=(226, 230, 236))
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def band(d, box, fill, label, f, color=SLATE):
    """스윔레인 — 왼쪽에 세로 라벨을 세운다."""
    d.rounded_rectangle(box, radius=10, fill=fill)
    d.text((box[0] + cm(0.14), box[1] + cm(0.10)), label, font=f, fill=color)


def chip(d, x, y, text, f, fg=VIOLET, bg=(238, 234, 248)):
    """모델명 칩. 상자 안에 모델을 박아 파이프라인이 실물로 보인다."""
    w = text_w(d, text, f)
    pad_x, pad_y = cm(0.10), cm(0.045)
    box = (x, y, x + w + pad_x * 2, y + f.getmetrics()[0] + f.getmetrics()[1] + pad_y * 2)
    d.rounded_rectangle(box, radius=6, fill=bg, outline=fg, width=2)
    d.text((x + pad_x, y + pad_y), text, font=f, fill=fg)
    return box[2] - box[0]


def elbow(d, x0, y0, x1, y1, color=LINE, w=3, head=True):
    """꺾인 연결선. 직선만 쓰면 층 사이 관계가 안 보인다."""
    ym = (y0 + y1) / 2
    d.line([(x0, y0), (x0, ym), (x1, ym), (x1, y1 - (12 if head else 0))], fill=color, width=w)
    if head:
        d.polygon([(x1, y1), (x1 - 8, y1 - 13), (x1 + 8, y1 - 13)], fill=color)


def arrow(d, x0, y, x1, color=GRAY, w=4):
    d.line([(x0, y), (x1 - 14, y)], fill=color, width=w)
    d.polygon([(x1, y), (x1 - 16, y - 9), (x1 - 16, y + 9)], fill=color)


def down_arrow(d, x, y0, y1, color=GRAY, w=4):
    d.line([(x, y0), (x, y1 - 14)], fill=color, width=w)
    d.polygon([(x, y1), (x - 9, y1 - 16), (x + 9, y1 - 16)], fill=color)


# ---------------------------------------------------------------------------
# 1. 오케스트레이션 구조도 — 입구 둘 → 마스터 Agent → 하위 Agent·도구 → 출구
# ---------------------------------------------------------------------------
def fig_orchestration(width_cm=13.3, height_cm=7.55) -> Path:
    """모델 파이프라인 아키텍처 — 층(스윔레인)마다 어떤 모델이 무엇을 하는지."""
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f7, f8, f8b, f9b, f10b = font(7), font(8), font(8, True), font(9, True), font(10, True)

    pad = cm(0.12)
    lane_x = pad + cm(1.52)          # 왼쪽 층 라벨 폭
    inner_w = W - lane_x - pad

    def lane(y, h, fill, title, sub):
        d.rounded_rectangle((pad, y, W - pad, y + h), radius=10, fill=fill)
        centered(d, (pad, y + cm(0.08), lane_x - cm(0.10), y + cm(0.46)), title, f8b, INK)
        centered(d, (pad, y + cm(0.44), lane_x - cm(0.10), y + cm(0.80)), sub, f7, SLATE)

    # ── ① 입력층
    y0 = pad
    h0 = cm(1.05)
    lane(y0, h0, BAND_IN, "입력", "두 갈래")
    ins = [("Chat 질문", "엔지니어가 묻는다"), ("이상감지 이벤트", "시스템이 스스로 기동")]
    gap = cm(0.24)
    bw = (inner_w - gap) / 2
    for i, (t, s) in enumerate(ins):
        x = lane_x + i * (bw + gap)
        box = (x, y0 + cm(0.14), x + bw, y0 + h0 - cm(0.14))
        card(d, box, WHITE, BLUE, 3, 10)
        centered(d, (x, y0 + cm(0.20), x + bw, y0 + cm(0.58)), t, f9b, BLUE)
        centered(d, (x, y0 + cm(0.56), x + bw, y0 + cm(0.92)), s, f7, SLATE)

    # ── ② 오케스트레이션층
    y1 = y0 + h0 + cm(0.30)
    h1 = cm(1.12)
    lane(y1, h1, BAND_ORCH, "조율", "supervisor")
    for i in range(2):
        x = lane_x + i * (bw + gap) + bw / 2
        elbow(d, x, y0 + h0 - cm(0.10), lane_x + inner_w / 2, y1 + cm(0.12), BLUE, 3)
    obox = (lane_x, y1 + cm(0.14), lane_x + inner_w, y1 + h1 - cm(0.14))
    card(d, obox, WHITE, RED, 4, 10)
    centered(d, (lane_x, y1 + cm(0.20), lane_x + inner_w, y1 + cm(0.60)),
             "마스터 Agent — 증상 분류 → 조사 설계 → 도구 자율 호출 → 증거 종합", f9b, RED)
    cw = text_w(d, "GLM-5.2 743B-A39B MoE", f7) + cm(0.20)
    chip(d, lane_x + (inner_w - cw) / 2, y1 + cm(0.62), "GLM-5.2 743B-A39B MoE", f7, RED,
         (252, 235, 235))

    # ── ③ 전문 모델층
    y2 = y1 + h1 + cm(0.34)
    h2 = cm(2.06)
    lane(y2, h2, BAND_MODEL, "전문 모델", "층별 학습")
    cols = [
        ("Trend Agent", "변화 시점·변화량", ["PatchTST", "CUSUM · BOCPD"]),
        ("Image Agent", "패턴 분류 · 유사 검색", ["ConvNeXt V2", "PatchCore"]),
        ("Agentic RAG", "재작성 · 리랭크 · 재검색", ["Qwen3-Emb + BM25", "Qwen3-Reranker"]),
        ("사내 시스템 Tool", "SPC·MES·YMS·EES·QMS", ["조회 전용 뷰", "가드·타임아웃"]),
    ]
    g2 = cm(0.20)
    cw2 = (inner_w - g2 * 3) / 4
    for i, (t, s, chips) in enumerate(cols):
        x = lane_x + i * (cw2 + g2)
        box = (x, y2 + cm(0.14), x + cw2, y2 + h2 - cm(0.14))
        card(d, box, WHITE, VIOLET, 3, 10)
        elbow(d, lane_x + inner_w / 2, y1 + h1 - cm(0.10), x + cw2 / 2, y2 + cm(0.12), RED, 3)
        centered(d, (x, y2 + cm(0.20), x + cw2, y2 + cm(0.58)), t, f8b, VIOLET)
        centered(d, (x, y2 + cm(0.56), x + cw2, y2 + cm(0.90)), s, f7, SLATE)
        # 칩 라벨이 알고리즘 선택 근거다 — 7pt 로 그리면 축소 삽입 뒤 읽히지 않는다
        cy = y2 + cm(0.98)
        for ch in chips:
            fc = f8 if text_w(d, ch, f8) + cm(0.20) <= cw2 else f7
            w = text_w(d, ch, fc) + cm(0.20)
            chip(d, x + (cw2 - w) / 2, cy, ch, fc)
            cy += cm(0.46)

    # ── ④ 검증·조치층
    y3 = y2 + h2 + cm(0.32)
    h3 = cm(1.05)
    lane(y3, h3, BAND_OUT, "검증·조치", "코드가 통제")
    outs = [("검증기 5칙", "통과분만 채택"), ("조치 등급표", "L0~L3 규칙 결정"),
            ("사람 승인 (HITL)", "현장 조치는 승인 후")]
    g3 = cm(0.20)
    cw3 = (inner_w - g3 * 2) / 3
    for i, (t, s) in enumerate(outs):
        x = lane_x + i * (cw3 + g3)
        box = (x, y3 + cm(0.14), x + cw3, y3 + h3 - cm(0.14))
        card(d, box, WHITE, GREEN, 3, 10)
        centered(d, (x, y3 + cm(0.20), x + cw3, y3 + cm(0.58)), t, f8b, GREEN)
        centered(d, (x, y3 + cm(0.56), x + cw3, y3 + cm(0.92)), s, f7, SLATE)
        if i:
            arrow(d, x - g3 + cm(0.02), y3 + h3 / 2, x - cm(0.02), GREEN, 3)
    for i in range(4):
        x = lane_x + i * (cw2 + g2) + cw2 / 2
        elbow(d, x, y2 + h2 - cm(0.10), lane_x + cw3 / 2, y3 + cm(0.12), VIOLET, 2)

    # ── ⑤ 순환
    y4 = y3 + h3 + cm(0.22)
    rbox = (lane_x, y4, lane_x + inner_w, y4 + cm(0.62))
    d.rounded_rectangle(rbox, radius=8, fill=GRAY_FILL, outline=LINE, width=2)
    centered(d, rbox, "판정 이력 · 확정 Inform Note → 다음 사건의 검색 근거 → 월 4회 재학습  (선순환)",
             f8b, INK)
    d.line([(lane_x + inner_w - cm(0.5), y4), (lane_x + inner_w - cm(0.5), y4 - cm(0.16)),
            (lane_x + cm(0.5), y4 - cm(0.16))], fill=SLATE, width=2)

    return save(img, "orchestration")


# ---------------------------------------------------------------------------
# 2. 시간 대비 막대 — AS-IS 5단계 누적 vs TO-BE
# ---------------------------------------------------------------------------
def fig_time(width_cm=13.3, height_cm=4.3) -> Path:
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f9b, f8, f8b = font(9, True), font(8), font(8, True)

    pad = cm(0.15)
    lab_w = cm(1.9)
    bar_x0 = pad + lab_w
    bar_x1 = W - pad - cm(1.6)

    steps = [
        ("① 트렌드", 1, "수 분"),
        ("② Map", 4, "수십 분"),
        ("③ 사례", 24, "반나절"),
        ("④ 이력", 4, "수십 분"),
        ("⑤ 보고·결재", 12, "수 시간"),
    ]
    total = sum(s[1] for s in steps)

    centered(d, (pad, pad, W - pad, pad + cm(0.40)),
             "같은 1건 — 엔지니어 수작업 vs Agent", f9b, BLACK)

    y = pad + cm(0.48)
    bh = cm(0.42)
    d.text((pad, y + cm(0.06)), "AS-IS", font=f8b, fill=BLACK)
    x = bar_x0
    for i, (name, wgt, tlabel) in enumerate(steps):
        seg = (bar_x1 - bar_x0) * wgt / total
        shade = RED_FILL if i % 2 == 0 else (245, 210, 210)
        d.rectangle((x, y, x + seg, y + bh), fill=shade, outline=RED, width=2)
        if seg > cm(1.0):
            centered(d, (x, y, x + seg, y + bh), name, f8, RED)
        x += seg
    d.text((bar_x1 + cm(0.12), y + cm(0.06)), "반나절 이상", font=f8b, fill=RED)

    # 단계 라벨 줄
    y2 = y + bh + cm(0.08)
    x = bar_x0
    for name, wgt, tlabel in steps:
        seg = (bar_x1 - bar_x0) * wgt / total
        if seg > cm(1.0):
            centered(d, (x, y2, x + seg, y2 + cm(0.32)), tlabel, f8, GRAY)
        x += seg

    # TO-BE
    y3 = y2 + cm(0.52)
    d.text((pad, y3 + cm(0.06)), "TO-BE", font=f8b, fill=BLACK)
    seg = (bar_x1 - bar_x0) * 0.018
    d.rectangle((bar_x0, y3, bar_x0 + max(seg, cm(0.12)), y3 + bh),
                fill=BLUE_FILL, outline=BLUE, width=2)
    d.text((bar_x0 + max(seg, cm(0.12)) + cm(0.12), y3 + cm(0.06)),
           "Agent 가 도구를 자율 호출 — 수 초", font=f8b, fill=BLUE)

    y4 = y3 + bh + cm(0.30)
    d.line([(pad, y4), (W - pad, y4)], fill=GRAY, width=2)
    d.text((pad, y4 + cm(0.10)),
           "확인 ①~④ 는 Agent 가 대체한다. ⑤ 의 승인과 실행은 사람이 그대로 한다.",
           font=f8, fill=BLACK)

    return save(img, "time_compare")


# ---------------------------------------------------------------------------
# 3. 조치 사다리 — 5단계 게이지
# ---------------------------------------------------------------------------
def fig_ladder(width_cm=13.3, height_cm=3.10) -> Path:
    """제목은 문서 소제목이 이미 달고 있다 — 그림 안에 또 넣지 않는다."""
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f9b, f8, f8b = font(9, True), font(8), font(8, True)

    pad = cm(0.15)

    rungs = [
        ("① 알림", "이상 통보", 1, "즉시"),
        ("② 공유", "유형 소견", 2, "즉시"),
        ("③ 권고", "점검 권고", 3, "즉시"),
        ("④ Hold", "lot Hold", 4, "승인 후"),
        ("⑤ 자동조치", "되돌릴 수 있는 것", 5, "2차년 승격 후"),
    ]
    gap = cm(0.18)
    bw = (W - 2 * pad - gap * 4) / 5
    y0 = pad
    bh = cm(1.72)
    for i, (name, what, filled, when) in enumerate(rungs):
        x0 = pad + i * (bw + gap)
        box = (x0, y0, x0 + bw, y0 + bh)
        is_auto = i == 4
        # 붉은색은 '대체 구간' 전용이다 — ⑤ 는 회색 테두리에 라벨 글자만 붉게 둔다
        rounded(d, box, WHITE, SLATE if is_auto else GRAY, 4 if is_auto else 2)
        block(d, (x0, y0 + cm(0.04), x0 + bw, y0 + cm(0.44)), name, [8, 7.5, 7],
              RED if is_auto else BLACK, bold=True, max_lines=1)
        # ⑤ 자동조치 칸만 문구가 길다 — 상자 내폭에 맞춰 폰트를 내려 한 줄로 앉힌다
        block(d, (x0, y0 + cm(0.46), x0 + bw, y0 + cm(0.94)), what, [8, 7.5, 7, 6.5],
              GRAY, max_lines=1)
        dots = "●" * filled + "○" * (5 - filled)
        block(d, (x0, y0 + cm(0.96), x0 + bw, y0 + cm(1.32)), dots, [8, 7.5, 7],
              SLATE if is_auto else GRAY, max_lines=1)
        block(d, (x0, y0 + cm(1.34), x0 + bw, y0 + cm(1.70)), when, [8, 7.5, 7],
              BLACK, bold=True, max_lines=1)
        if i < 4:
            arrow(d, x0 + bw + cm(0.02), y0 + bh / 2, x0 + bw + gap - cm(0.02))

    y1 = y0 + bh + cm(0.14)
    cap = ("승인 이력이 쌓인 시나리오만 개별 심의로 자동조치에 올린다. 승격 뒤에도 전건 사후 "
           "리뷰한다. 설비 제어성 조치는 2차년에도 사람 승인 대상이다.")
    for k, ln in enumerate(wrap_lines(d, cap, f8, W - 2 * pad)):
        d.text((pad, y1 + k * cm(0.36)), ln, font=f8, fill=BLACK)

    return save(img, "action_ladder")


# ---------------------------------------------------------------------------
# 4. 문제 4종 — 큰 글자 콜아웃 4칸
# ---------------------------------------------------------------------------
def fig_problem(width_cm=13.3, height_cm=3.30) -> Path:
    """content.FOUR_PROBLEMS (라벨, 본문, 계측 지점)를 읽는다 — 9회차 배선.

    계측 지점은 카드 하단 회색 줄 — 새 수치가 아니라 '어디서 확인되는가'만 적는다.
    11회차 : 렌더 실측상 ②③ 카드가 말줄임 없이 문장 중간에서 잘렸다 — 높이 2.95→3.30,
    본문 max_lines 3→4 로 안전판을 건다. 하단 회색줄 폰트 하한도 6.5→7pt(6pt 대는
    흑백 인쇄 판독 한계 아래).
    """
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    fbig = font(15, True)

    import content as C

    pad = cm(0.12)
    gap = cm(0.2)
    bw = (W - 2 * pad - gap * 3) / 4
    bh = H - 2 * pad
    for i, (big, body, meter) in enumerate(C.FOUR_PROBLEMS):
        x0 = pad + i * (bw + gap)
        box = (x0, pad, x0 + bw, pad + bh)
        rounded(d, box, RED_FILL, RED, 3)
        centered(d, (x0, pad + cm(0.04), x0 + bw, pad + cm(0.54)), big, fbig, RED)
        d.line([(x0 + bw * 0.28, pad + cm(0.60)), (x0 + bw * 0.72, pad + cm(0.60))],
               fill=RED, width=2)
        block(d, (x0, pad + cm(0.66), x0 + bw, pad + cm(2.17)), body, [9, 8.5, 8, 7.5],
              BLACK, max_lines=4, pad=cm(0.12), line_gap=1.06)
        d.line([(x0 + cm(0.16), pad + cm(2.27)), (x0 + bw - cm(0.16), pad + cm(2.27))],
               fill=(226, 180, 180), width=1)
        block(d, (x0, pad + cm(2.33), x0 + bw, pad + cm(3.01)), "계측 : " + meter,
              [7.5, 7], SLATE, max_lines=2, pad=cm(0.10), line_gap=1.0)

    return save(img, "problem_four")


# ---------------------------------------------------------------------------
# 5. 검증기 5칙 — 게이트 파이프라인
# ---------------------------------------------------------------------------
def fig_verifier(width_cm=13.3, height_cm=2.3) -> Path:
    """9회차 : 그림 안 7pt 캡션(탈락→재생성)은 뺐다 — 본문 VERIFIER_NOTE 와 중복이었다.

    10회차 : 그림 안 제목도 뺐다. 소제목·그림 제목·VERIFIER_NOTE 가 같은 말을 세 번 했다.
    제목은 build_docx 의 소제목 '5. 그럴듯한 오답은 코드가 걸러낸다 — 다섯 관문'이 승계한다.
    """
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    pad = cm(0.12)

    gates = [
        ("스키마", "형식 위반"),
        ("근거 실재", "없는 증거"),
        ("사실 대조", "원문에 없는 수치"),
        ("신뢰도", "근거 3개 미만"),
        ("공백 금지", "부족분 미명시"),
    ]
    y0 = pad + cm(0.06)
    gh = cm(1.30)
    lead = cm(1.15)
    tail = cm(1.32)                 # '채택' 이 들어갈 자리를 미리 떼어 둔다 — 좁으면 글자가 잘린다
    gap = cm(0.15)
    # 관문 폭은 5등분 고정이 아니라 이름·부제 실측 폭 비례로 나눈다
    avail = W - 2 * pad - lead - tail - gap * 6
    fn, fr = font(8, True), font(7.5)
    need = [max(text_w(d, n, fn), text_w(d, "× " + r, fr) / 2) + cm(0.26) for n, r in gates]
    scale = avail / sum(need)
    widths = [n * scale for n in need]

    # 입력
    ibox = (pad, y0, pad + lead, y0 + gh)
    rounded(d, ibox, GRAY_FILL, GRAY, 2)
    block(d, (pad, y0 + cm(0.26), pad + lead, y0 + cm(0.66)), "판단서", [8, 7.5],
          BLACK, bold=True, max_lines=1)
    block(d, (pad, y0 + cm(0.66), pad + lead, y0 + cm(1.02)), "초안", [8, 7.5], GRAY, max_lines=1)

    x = pad + lead
    for (name, reject), gw in zip(gates, widths):
        arrow(d, x + cm(0.03), y0 + gh / 2, x + gap - cm(0.03), SLATE, 3)
        x += gap
        box = (x, y0, x + gw, y0 + gh)
        rounded(d, box, WHITE, RED, 3)
        block(d, (x, y0 + cm(0.06), x + gw, y0 + cm(0.44)), name, [8, 7.5, 7],
              RED, bold=True, max_lines=1)
        # '✕'(U+2715)는 맑은 고딕에 글리프가 없어 □ 로 깨진다 — '×'(U+00D7)를 쓴다
        block(d, (x, y0 + cm(0.44), x + gw, y0 + cm(1.26)), "× " + reject, [7.5, 7, 6.5],
              GRAY, max_lines=2, line_gap=1.02)
        d.line([(x + gw / 2, y0 + gh), (x + gw / 2, y0 + gh + cm(0.18))], fill=LINE, width=2)
        x += gw

    arrow(d, x + cm(0.03), y0 + gh / 2, x + cm(0.58), SLATE, 3)
    block(d, (x + cm(0.62), y0 + cm(0.46), W - pad, y0 + cm(0.86)), "채택", [8, 7.5],
          NAVY, bold=True, max_lines=1, pad=cm(0.02))

    return save(img, "verifier_gate")


# ---------------------------------------------------------------------------
# 6. 경영효과 — 큰 숫자 3칸 + 산출식
# ---------------------------------------------------------------------------
def fig_effect(width_cm=13.3, height_cm=3.50) -> Path:
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    fnum, f8, f8b, f9 = font(19, True), font(8), font(8, True), font(9)

    pad = cm(0.12)
    gap = cm(0.22)
    bw = (W - 2 * pad - gap * 2) / 3
    bh = cm(1.86)
    cards = [
        ("200억", "원 / 년", "확산 완료 후 1,000명 전면 적용", RED),
        ("57.5배", "연간 ROI", "투자 347,794,165원 대비", BLUE),
        ("6.3일", "투자 회수", "2개년 총투자 기준 12.7일", BLUE),
    ]
    for i, (num, unit, sub, color) in enumerate(cards):
        x0 = pad + i * (bw + gap)
        box = (x0, pad, x0 + bw, pad + bh)
        rounded(d, box, RED_FILL if i == 0 else BLUE_FILL, color, 4 if i == 0 else 3)
        centered(d, (x0, pad + cm(0.14), x0 + bw, pad + cm(0.90)), num, fnum, color)
        centered(d, (x0, pad + cm(0.92), x0 + bw, pad + cm(1.26)), unit, f8b, BLACK)
        centered(d, (x0, pad + cm(1.30), x0 + bw, pad + cm(1.68)), sub, f8, GRAY)

    y = pad + bh + cm(0.22)
    fbox = (pad, y, W - pad, y + cm(1.18))
    rounded(d, fbox, GRAY_FILL, GRAY, 2, r=8)
    # U+2212(−)는 맑은 고딕에 글리프가 없어 □ 로 깨진다. 일반 하이픈을 쓴다.
    centered(d, (pad, y + cm(0.04), W - pad, y + cm(0.54)),
             "[ (개선 전 4h ÷ 8h) - (개선 후 2h ÷ 8h) ] × 연봉 80,000,000원 × 1,000명 = 연 200억 원",
             f9, BLACK)
    # 산출식의 입력값 출처 — docs/03 §4.1 가정표 원문
    block(d, (pad, y + cm(0.52), W - pad, y + cm(0.86)),
          "연봉 80,000,000원 = 사내 산정 기준값 · 1,000명 = 제조기술센터 품질·공정 엔지니어",
          [7, 6.5, 6], GRAY, max_lines=2)
    # 10회차 : 큰 숫자 카드가 200억을 확정치처럼 그리는데 산출식의 두 항은 아직 실측 전이다.
    # 캡션과 그림의 확신 수준을 맞춘다.
    block(d, (pad, y + cm(0.84), W - pad, y + cm(1.14)),
          "4h → 2h 는 실측 전 가정 — 그림자 운영 로그로 대체한다",
          [8, 7.5, 7], SLATE, bold=True, max_lines=1)

    return save(img, "effect_big")


# ---------------------------------------------------------------------------
# 7. 민감도 — 가로 막대
# ---------------------------------------------------------------------------
def fig_sensitivity(width_cm=13.3, height_cm=3.45) -> Path:
    """9회차 : 캡션을 content.SENSITIVITY_NOTE 로 배선 — 표가 흔들지 않는 기준 4시간을
    문서가 먼저 인정한다. '30분만 줄여도 14배'는 4시간을 전제로 깔아 버렸다.

    11회차 : 캡션 렌더를 가운데 정렬·굵게 2줄 → 좌정렬·보통 굵기·※ 접두로 내린다 —
    바로 아래 절 제목 '무형 효과 (정성)'(11pt)보다 시각적으로 세서 제목을 눌렀다.
    이 구간 강조는 위 fig_effect 의 200억·57.5배가 이미 맡는다.
    """
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f8, f8b = font(8), font(8, True)

    import content as C

    pad = cm(0.12)
    note_f, note_lines = fit_wrap(d, "※ " + C.SENSITIVITY_NOTE, W - 2 * pad, 2, [8.5, 8, 7.5])
    asc, desc_ = note_f.getmetrics()
    lh = int((asc + desc_) * 1.15)
    for k, ln in enumerate(note_lines):
        d.text((pad, pad + k * lh), ln, font=note_f, fill=SLATE)

    rows = [
        ("2.0시간 (기준)", 57.5, "200억", True),
        ("2.5시간", 43.1, "150억", False),
        ("3.0시간", 28.8, "100억", False),
        ("3.5시간", 14.4, "50억", False),
    ]
    lab_w = cm(2.5)
    x0 = pad + lab_w
    x1 = W - pad - cm(2.6)
    y = pad + cm(0.92)
    bh = cm(0.42)
    step = cm(0.56)
    for name, roi, money, hi in rows:
        d.text((pad, y + cm(0.06)), name, font=f8b if hi else f8, fill=RED if hi else BLACK)
        w = (x1 - x0) * roi / 57.5
        d.rectangle((x0, y, x0 + w, y + bh),
                    fill=RED_FILL if hi else BLUE_FILL, outline=RED if hi else BLUE, width=2)
        d.text((x0 + w + cm(0.10), y + cm(0.06)), f"{roi}배 · {money}",
               font=f8b if hi else f8, fill=RED if hi else BLACK)
        y += step

    return save(img, "sensitivity")


# ---------------------------------------------------------------------------
# 8. E2E 업무 워크플로우 — 위 AS-IS(사람) / 아래 TO-BE(Agent), 대체 구간을 세로로 잇는다
# ---------------------------------------------------------------------------
def fig_workflow(width_cm=13.3, height_cm=6.65) -> Path:
    """10회차 : 상단 '업무 단계 ①~⑤' 밴드를 지웠다 — 위 코어 6칸 표가 같은 흐름을 이미 그린다.
    단계 번호는 AS-IS 카드 왼쪽 위에 붙여 자리를 안 먹게 옮겼다.
    AS-IS 소요 시간이 실측처럼 읽히던 것도 레인 안 단서 한 줄로 못 박는다.
    """
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f7, f7b, f8, f8b, f9b = font(7), font(7, True), font(8), font(8, True), font(9, True)

    pad = cm(0.12)
    lane_x = pad + cm(1.30)
    inner = W - lane_x - pad

    # 칸 폭이 약 2.2cm 다. 7pt 기준 한 줄 9자 안쪽으로 끊는다 — 넘치면 상자를 뚫는다.
    steps = [
        ("① 트렌드 확인", "SPC 화면 열어\nlot·chamber\n직접 조회", "수 분",
         "Trend Agent\n02:14 CD\n+0.8nm 검출", "수 초"),
        ("② 불량 Map", "Failbit Map\n분포를 눈으로\n확인", "수십 분",
         "Image Agent\nedge 집중\nFocus 편차형", "수 초"),
        ("③ 과거 사례", "과거 이미지·\nNote 뒤져\n하나씩 대조", "반나절",
         "유사도로 좁혀\n메타 키로\n원인 인용", "수 초"),
        ("④ 설비 이력", "MES·SPC 접속\nPM·변경점\n이력 조회", "수십 분",
         "조회 도구가\nPM 직후 재보정\n누락 확인", "수 초"),
        # 11회차 : TO-BE 3줄에 '승인·반려로 치환'을 넣는다 — 도해만 보면 AS-IS⑤
        # (회의·품의·결재) 구간이 대체 안 된 것으로 읽혔다. 같은 문장은 SPREAD_BOX 에서 뺐다.
        # 렌더 실측 : '승인·반려가 결재 치환'(12자)은 카드 폭(줄당 9~10자)을 넘어 우측이
        # 잘렸다 — '승인·반려로 치환'(9자)으로 축약.
        ("⑤ 결론·조치", "보고서 작성\n회의 소집\n품의·결재", "수 시간",
         "근거 3종 인용\n보고서·조치안 생성\n승인·반려로 치환", "수 초"),
    ]

    gap = cm(0.16)
    bw = (inner - gap * (len(steps) - 1)) / len(steps)

    # AS-IS 레인 — 헤더 밴드는 뺐다(10회차). 단계 번호는 카드 좌상단에 얹는다.
    ay = pad
    ah = cm(2.35)
    d.rounded_rectangle((pad, ay, W - pad, ay + ah), radius=10, fill=(244, 245, 247))
    centered(d, (pad, ay + cm(0.30), lane_x - cm(0.10), ay + cm(0.74)), "AS-IS", f9b, SLATE)
    centered(d, (pad, ay + cm(0.72), lane_x - cm(0.10), ay + cm(1.10)), "엔지니어", f7, SLATE)
    centered(d, (pad, ay + cm(1.06), lane_x - cm(0.10), ay + cm(1.44)), "수작업", f7, SLATE)
    core = cm(2.05)                       # 카드+소요 배지가 쓰는 높이 (레인은 단서 한 줄만큼 더 크다)
    for i, s in enumerate(steps):
        x = lane_x + i * (bw + gap)
        box = (x, ay + cm(0.14), x + bw, ay + core - cm(0.52))
        card(d, box, WHITE, LINE, 2, 9, shadow=False)
        d.text((x + cm(0.08), ay + cm(0.16)), s[0].split(" ")[0], font=f7b, fill=SLATE)
        for k, ln in enumerate(s[1].split("\n")):
            centered(d, (x, ay + cm(0.20) + k * cm(0.36), x + bw,
                         ay + cm(0.56) + k * cm(0.36)), ln, f7, INK)
        tb = (x + bw * 0.18, ay + core - cm(0.48), x + bw * 0.82, ay + core - cm(0.08))
        d.rounded_rectangle(tb, radius=7, fill=(226, 229, 234), outline=SLATE, width=2)
        centered(d, tb, s[2], f7b, SLATE)
    # AS-IS 소요가 실측처럼 읽히지 않게 레인 안에서 성격을 밝힌다(10회차)
    block(d, (pad, ay + core, W - pad, ay + ah - cm(0.04)),
          "단계 시간은 산정치 — 가동 후 처리 시간 로그로 실측해 보정한다",
          [7.5, 7, 6.5], SLATE, max_lines=1)

    # 대체 화살표
    my = ay + ah
    for i in range(len(steps)):
        x = lane_x + i * (bw + gap) + bw / 2
        d.line([(x, my + cm(0.04)), (x, my + cm(0.34))], fill=RED, width=4)
        d.polygon([(x, my + cm(0.46)), (x - 9, my + cm(0.32)), (x + 9, my + cm(0.32))], fill=RED)
    centered(d, (pad, my + cm(0.04), lane_x - cm(0.10), my + cm(0.46)), "대체", f7b, RED)

    # TO-BE 레인 — 붉은색은 '대체' 화살표에만 남긴다. 밴드·카드는 파랑으로 내린다
    ty = my + cm(0.52)
    th = cm(2.05)
    d.rounded_rectangle((pad, ty, W - pad, ty + th), radius=10, fill=BAND_IN)
    centered(d, (pad, ty + cm(0.30), lane_x - cm(0.10), ty + cm(0.74)), "TO-BE", f9b, NAVY)
    centered(d, (pad, ty + cm(0.72), lane_x - cm(0.10), ty + cm(1.10)), "Agent", f7, NAVY)
    centered(d, (pad, ty + cm(1.06), lane_x - cm(0.10), ty + cm(1.44)), "자율 호출", f7, NAVY)
    for i, s in enumerate(steps):
        x = lane_x + i * (bw + gap)
        box = (x, ty + cm(0.14), x + bw, ty + th - cm(0.52))
        card(d, box, WHITE, NAVY, 3, 9)
        for k, ln in enumerate(s[3].split("\n")):
            centered(d, (x, ty + cm(0.20) + k * cm(0.36), x + bw,
                         ty + cm(0.56) + k * cm(0.36)), ln, f7, INK)
        tb = (x + bw * 0.18, ty + th - cm(0.48), x + bw * 0.82, ty + th - cm(0.08))
        d.rounded_rectangle(tb, radius=7, fill=NAVY_FILL, outline=NAVY, width=2)
        centered(d, tb, s[4], f7b, NAVY)

    # 총계 띠 — 단계명을 코어 6칸 표 어휘로 맞춘다(10회차). 같은 흐름을 두 어휘로 부르지 않는다.
    # 11회차 : '결과 활용까지'의 끝단(확정 이력 → 검색 자산)을 이 띠 문구로 닫는다 —
    # ⑥등록 칸을 새로 만드는 대신(고정 높이 6.65cm 에서 6행 재배분은 카드가 다시 잘린다),
    # 이미 있는 총계 띠 한 줄로 같은 주장을 0cm 순증으로 넣는다.
    sy = ty + th + cm(0.18)
    sbox = (pad, sy, W - pad, sy + cm(0.52))
    d.rounded_rectangle(sbox, radius=8, fill=GRAY_FILL, outline=LINE, width=2)
    block(d, (pad + cm(0.10), sy, W - pad - cm(0.10), sy + cm(0.52)),
          "확인 5단계 : 반나절 이상 → 수 초. 확정 이력은 다음 사건의 검색 근거로 돌아간다.",
          [8, 7.5, 7], INK, bold=True, max_lines=1)

    return save(img, "workflow_e2e")


# ---------------------------------------------------------------------------
# 9. 확산 로드맵 — 8분기 시간축. 4행 표는 읽어야 순서가 잡히지만 축은 한 번에 잡힌다
# ---------------------------------------------------------------------------
def fig_spread(width_cm=13.3, height_cm=2.7) -> Path:
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f8 = font(8)

    pad = cm(0.12)
    cardw = cm(2.9)
    inner = W - 2 * pad
    step = (inner - cardw * 4) / 3 + cardw
    xs = [pad + i * step for i in range(4)]        # 카드 좌측
    cx = [x + cardw / 2 for x in xs]

    # ── 연차 밴드 : 2개년 단계 과제라는 정체성을 글자 없이 나른다
    mid = (xs[1] + cardw + xs[2]) / 2
    by0, by1 = pad, pad + cm(0.34)
    d.rounded_rectangle((pad, by0, mid - cm(0.04), by1), radius=6, fill=(243, 244, 246))
    d.rounded_rectangle((mid + cm(0.04), by0, W - pad, by1), radius=6, fill=BAND_IN)
    block(d, (pad, by0, mid, by1), "1차년 구축·검증", [8, 7.5], SLATE, max_lines=1)
    block(d, (mid, by0, W - pad, by1), "2차년 확산·자동화", [8, 7.5], NAVY, max_lines=1)

    # ── 카드 (SPREAD_TABLE '무엇을 여는가' 원문)
    cy0, cy1 = pad + cm(0.40), pad + cm(1.50)
    opens = [
        "그림자 운영 → Chat 파일럿",
        "무인 접수 — 누락 0건 · 채택·반려 집계 개시",
        "etch·CMP 확산 — 코어 변경 0 · 반려율 상승 없음",
        "확산 표준안 — 자원 증설 없이 이관",
    ]
    edges = [(200, 206, 214), (150, 165, 190), (91, 127, 168), NAVY]
    for i, (x, txt) in enumerate(zip(xs, opens)):
        d.rounded_rectangle((x, cy0, x + cardw, cy1), radius=8, fill=WHITE,
                            outline=edges[i], width=3 if i == 3 else 2)
        block(d, (x, cy0, x + cardw, cy1), txt, [7.5, 7, 6.5], INK, max_lines=3,
              pad=cm(0.09), line_gap=1.02)

    # ── 시간축
    ay = pad + cm(1.62)
    arrow(d, pad, ay, W - pad, LINE, 3)
    for i, x in enumerate(cx):
        if i == 2:                                  # 5Q·6Q 두 분기는 브래킷으로 묶는다
            d.line([(x - cm(0.45), ay - cm(0.10)), (x - cm(0.45), ay),
                    (x + cm(0.45), ay), (x + cm(0.45), ay - cm(0.10))], fill=NAVY, width=3)
        else:
            r = cm(0.11)
            d.polygon([(x, ay - r), (x + r, ay), (x, ay + r), (x - r, ay)],
                      fill=NAVY if i == 3 else SLATE)

    # ── 시점 · 대상
    whens = ["1차년 3Q", "1차년 4Q", "2차년 5Q·6Q", "2차년 8Q"]
    whos = ["포토 엔지니어", "야간·주말", "3개 공정", "약 1,000명"]
    sizes = [8, 8.5, 9.5, 11]
    for i, x in enumerate(xs):
        block(d, (x, ay + cm(0.16), x + cardw, ay + cm(0.50)), whens[i], [8, 7.5],
              SLATE, bold=True, max_lines=1)
        block(d, (x, ay + cm(0.52), x + cardw, ay + cm(1.02)), whos[i],
              [sizes[i], sizes[i] - 1, 7], NAVY if i == 3 else INK,
              bold=(i == 3), max_lines=1)

    return save(img, "spread")


# ---------------------------------------------------------------------------
# 10. 도구 누적 캐스케이드 — 왼쪽 끝이 한 단씩 밀려 '답이 깊어진다'가 배치로 보인다
# ---------------------------------------------------------------------------
def fig_ablation_cascade(width_cm=13.3, height_cm=3.4) -> Path:
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    import content as C                              # 표 원문을 그대로 그림 데이터로 쓴다

    rows = list(C.ABLATION)
    rh, rgap = cm(0.46), cm(0.04)
    x1 = W - cm(0.25)
    namew = cm(3.2)
    y = cm(0.06)
    for i, (tool, ans) in enumerate(rows):
        x0 = cm(0.25) + i * cm(0.50)
        last = i == len(rows) - 1
        d.rounded_rectangle((x0, y, x1, y + rh), radius=6, fill=WHITE,
                            outline=NAVY if last else LINE, width=3 if last else 2)
        block(d, (x0 + cm(0.10), y, x0 + namew, y + rh), tool, [9, 8.5, 8],
              NAVY if last else INK, bold=True, max_lines=1)
        d.line([(x0 + namew + cm(0.06), y + cm(0.08)),
                (x0 + namew + cm(0.06), y + rh - cm(0.08))], fill=LINE, width=2)
        block(d, (x0 + namew + cm(0.16), y, x1, y + rh), ans, [8.5, 8, 7.5],
              INK, max_lines=1, pad=cm(0.06))
        y += rh + rgap

    y += cm(0.06)
    d.text((cm(0.25), y), C.ABLATION_NOTE, font=font(7.5), fill=GRAY)

    return save(img, "ablation_cascade")


# ---------------------------------------------------------------------------
# 11. 무형효과 5칸 — 박스 없는 낮은 띠. p1·p5 의 라운드 카드와 형태를 구분한다
# ---------------------------------------------------------------------------
def fig_intangible(width_cm=13.3, height_cm=2.2) -> Path:
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    import content as C

    items = list(C.INTANGIBLE)
    pad = cm(0.10)
    cw = (W - 2 * pad) / len(items)
    for i, (label, desc) in enumerate(items):
        x0 = pad + i * cw
        if i:
            d.line([(x0, cm(0.10)), (x0, H - cm(0.20))], fill=DIV, width=2)
        # 라벨은 한 줄로 고정한다 — 한 칸만 두 줄이 되면 다섯 칸의 밑줄이 어긋난다
        block(d, (x0, cm(0.06), x0 + cw, cm(0.46)), label, [10, 9.5, 9, 8.5, 8],
              NAVY, bold=True, max_lines=1, pad=cm(0.08))
        uy = cm(0.60)
        d.line([(x0 + cw * 0.20, uy), (x0 + cw * 0.80, uy)], fill=NAVY, width=2)
        block(d, (x0, cm(0.66), x0 + cw, cm(2.10)), desc, [8, 7.5, 7],
              GRAY, max_lines=4, pad=cm(0.08), line_gap=1.02)

    return save(img, "intangible")


# ---------------------------------------------------------------------------
# 12. 기존 대안 4종 — 2×2 카드. 앞 3장 붉은 ✕ 배지(대체 불가), SPC 만 남색 화살표(트리거 흡수)
# ---------------------------------------------------------------------------
def fig_alternatives(width_cm=13.3, height_cm=3.60) -> Path:
    """content.ALTERNATIVES 를 읽는다(9회차) — 문구가 두 곳으로 갈라지지 않게.

    ✕(U+2715)·↳(U+21B3) 글리프는 폰트에 없을 수 있어 선분으로 직접 그린다.
    11회차 : ALTERNATIVES[0][1] 본문이 길어져 높이 3.35→3.60, max_lines 2→3.
    ✕ 배지 3개를 RED→GRAY 로 내린다 — p1 한 지면에서 빨강이 문제 카드·게이지·이 배지까지
    네 자리로 쓰이던 것을 두 자리(문제·부하)로 줄인다. 마지막 SPC 카드의 → 배지만 NAVY 로
    남겨 '셋은 버리고 하나는 쓴다'를 색으로 보여준다.
    """
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f9b = font(9, True)

    import content as C

    pad = cm(0.12)
    gap = cm(0.16)
    cw = (W - 2 * pad - gap) / 2
    ch = (H - 2 * pad - gap) / 2
    for i, (name, why) in enumerate(C.ALTERNATIVES):
        r, col = divmod(i, 2)
        x0 = pad + col * (cw + gap)
        y0 = pad + r * (ch + gap)
        last = i == 3                            # SPC 알람 — 대체 대상이 아니라 트리거 입력
        card(d, (x0, y0, x0 + cw, y0 + ch), WHITE, NAVY if last else LINE,
             3 if last else 2, 10)
        d.text((x0 + cm(0.16), y0 + cm(0.10)), name, font=f9b,
               fill=NAVY if last else INK)
        bcx, bcy, br = x0 + cw - cm(0.34), y0 + cm(0.28), cm(0.18)
        if last:
            d.ellipse((bcx - br, bcy - br, bcx + br, bcy + br),
                      fill=NAVY_FILL, outline=NAVY, width=2)
            arrow(d, bcx - br + cm(0.05), bcy, bcx + br - cm(0.03), NAVY, 3)
        else:
            d.ellipse((bcx - br, bcy - br, bcx + br, bcy + br),
                      fill=GRAY_FILL, outline=GRAY, width=2)
            k = cm(0.085)
            d.line([(bcx - k, bcy - k), (bcx + k, bcy + k)], fill=GRAY, width=4)
            d.line([(bcx - k, bcy + k), (bcx + k, bcy - k)], fill=GRAY, width=4)
        block(d, (x0 + cm(0.06), y0 + cm(0.46), x0 + cw - cm(0.06), y0 + ch - cm(0.06)),
              why, [8, 7.5, 7], GRAY, max_lines=3, line_gap=1.05)

    return save(img, "alternatives")


# ---------------------------------------------------------------------------
# 13. 부하 게이지 — 근무 8시간 중 판정 4시간. '절반'을 문장이 아니라 면적으로
# ---------------------------------------------------------------------------
def fig_burden(width_cm=13.3, height_cm=3.35) -> Path:
    """content.IMPORTANCE 를 읽는다(9회차). '50%' 같은 새 퍼센트는 적지 않는다(§0-3).

    10회차 : 캡션은 '실측해 대체한다'로 정직한데 게이지가 8칸 중 4칸을 확정치처럼 칠해
    캡션을 뒤집었다. 막대 제목 옆에 '가정' 배지를 얹는다(빗금은 8칸 눈금 판독을 흐린다).
    오판 비용 줄(IMPORTANCE[2])은 8pt 한 줄 각주에서 9.5pt 굵은 두 줄로 올린다 —
    중요도 논거의 절반이 잘려 있었다. 그만큼 높이를 2.62 → 3.05 로 넓혔다(p1 슬랙 안).
    11회차 : IMPORTANCE[2] 에 정본 §8 R4(오탐 알림 남발 → 이탈) 대응 문장이 붙어 3줄로
    늘었다 — 높이 3.05→3.35, max_lines 2→3. 각주(IMPORTANCE[1]) 폰트 하한도 6.5→7pt.
    """
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f8, f11b, f14b = font(8), font(11, True), font(14, True)

    import content as C

    pad = cm(0.12)
    dark = (192, 57, 43)
    bar_x0, bar_x1 = pad, cm(8.5)
    bar_y0, bar_y1 = cm(0.66), cm(1.30)
    d.text((bar_x0, cm(0.08)), "판정에 쓰는 4시간", font=f11b, fill=dark)
    # '가정' 배지 — 이 4시간이 실측치가 아님을 그림 스스로 말하게 한다(§0-3 은 수치를 못 만들 뿐,
    # 가진 수치의 성격 표기는 오히려 요구한다)
    f8b_ = font(8, True)
    bx = bar_x0 + text_w(d, "판정에 쓰는 4시간", f11b) + cm(0.16)
    bw_ = text_w(d, "가정", f8b_) + cm(0.22)
    d.rounded_rectangle((bx, cm(0.13), bx + bw_, cm(0.51)), radius=6,
                        fill=WHITE, outline=SLATE, width=2)
    centered(d, (bx, cm(0.13), bx + bw_, cm(0.51)), "가정", f8b_, SLATE)
    w_r = text_w(d, "나머지 4시간", f8)
    d.text((bar_x1 - w_r, cm(0.26)), "나머지 4시간", font=f8, fill=GRAY)
    seg = (bar_x1 - bar_x0 - cm(0.03) * 7) / 8
    x = bar_x0
    for i in range(8):
        d.rectangle((x, bar_y0, x + seg, bar_y1),
                    fill=dark if i < 4 else (233, 235, 238))
        centered(d, (x, bar_y1 + cm(0.04), x + seg, bar_y1 + cm(0.32)), str(i + 1),
                 f8, SLATE)
        x += seg + cm(0.03)
    d.rounded_rectangle((bar_x0, bar_y0, bar_x1, bar_y1), radius=6, outline=LINE, width=3)
    centered(d, (bar_x0, bar_y1 + cm(0.34), bar_x1, bar_y1 + cm(0.62)), "근무 8시간",
             f8, SLATE)

    dx = cm(8.75)
    d.line([(dx, cm(0.16)), (dx, cm(1.96))], fill=LINE, width=2)
    d.text((cm(8.95), cm(0.22)), "× 약 1,000명", font=f14b, fill=INK)
    d.text((cm(8.95), cm(0.94)), "품질·공정 엔지니어", font=f8, fill=GRAY)
    block(d, (cm(8.90), cm(1.28), W - pad, cm(1.96)), C.IMPORTANCE[1].split(". ")[0],
          [7.5, 7], GRAY, max_lines=2, pad=cm(0.05), line_gap=1.02)

    # 오판 비용 — 8pt 한 줄이면 뒤가 잘렸다. 9.5pt 굵게 두 줄로 올린다(10회차)
    # 11회차 : R4 대응 문장이 붙어 3줄이 됐다 — 영역을 2.96→3.26 으로 넓힌다
    block(d, (pad, cm(2.06), W - pad, cm(3.26)), C.IMPORTANCE[2],
          [9.5, 9, 8.5], SLATE, bold=True, max_lines=3, pad=cm(0.02), line_gap=1.10)

    return save(img, "burden")


# ---------------------------------------------------------------------------
# 14. 지금 시작 — WHY_NOW 세 조건 배지 → 화살표 → 지금 시작
# ---------------------------------------------------------------------------
def fig_readiness(width_cm=13.3, height_cm=2.60) -> Path:
    """content.WHY_NOW 원문 어절만 쓴다(9회차). ☑ 글리프 금지 — 체크는 꺾은선 2획.

    '축적 완료' 류의 신규 자기평가 어휘는 쓰지 않는다.
    11회차 : 채점 문구에 직접 안 걸리는 절이 p1 최대 면적(3.45cm)을 쓰고 있었다 — 높이를
    2.60 으로 줄여 p1 그림 3종(fig_problem·fig_alternatives·fig_burden) 확대의 재원으로
    쓴다. 문구는 한 글자도 안 바꾼다. 배지 높이(bh)가 줄어드는 만큼 라벨·부연의 y 오프셋도
    비례로 낮춘다 — 이 함수는 d.text 로 고정 좌표에 찍기 때문에 block() 처럼 자동으로 안
    접힌다. 안 낮추면 8pt 부연이 좁아진 카드 하단을 넘는다.
    """
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f8, f9b, f10b = font(8), font(9, True), font(10, True)

    conds = [
        ("판정 이력·Inform Note", "학습 자산으로 쓸 만한 양에 도달했다"),
        ("공개 모델", "사내에 들일 수 있는 모델이 성숙했다"),
        # 11회차 : WHY_NOW 셋째 절과 동기화 — 이 함수는 content.WHY_NOW 문자열이 아니라
        # 이 conds 를 하드코딩해서 읽는다. 상수만 고치고 여기를 안 고치면 렌더가 안 바뀐다.
        ("설계·검증 체계", "회귀 러너·recall 실측까지 서 있다"),
    ]
    pad = cm(0.12)
    bx1 = cm(9.3)
    bh = cm(0.70)
    gap = cm(0.12)
    y = pad + (H - 2 * pad - bh * 3 - gap * 2) / 2
    for label, desc in conds:
        card(d, (pad, y, bx1, y + bh), WHITE, NAVY, 2, 10, shadow=False)
        cx, cy = pad + cm(0.34), y + bh / 2
        d.line([(cx - cm(0.10), cy), (cx - cm(0.02), cy + cm(0.10))], fill=NAVY, width=4)
        d.line([(cx - cm(0.02), cy + cm(0.10)), (cx + cm(0.14), cy - cm(0.12))],
               fill=NAVY, width=4)
        tx = pad + cm(0.62)
        d.text((tx, y + cm(0.06)), label, font=f9b, fill=NAVY)
        d.text((tx, y + cm(0.36)), desc, font=f8, fill=GRAY)
        y += bh + gap

    my = H / 2
    ax0, ax1 = cm(9.55), cm(10.55)
    d.line([(ax0, my), (ax1 - cm(0.14), my)], fill=SLATE, width=6)
    d.polygon([(ax1, my), (ax1 - cm(0.18), my - cm(0.12)), (ax1 - cm(0.18), my + cm(0.12))],
              fill=SLATE)
    # 10회차 : 빨강은 '문제'(p1 카드·부하 게이지)와 '대체 구간'(p2 붉은 칸) 전용으로 고정한다.
    # 결론 배지까지 붉으면 CTA 가 문제 강조들 사이에 묻힌다 → 남색으로 내린다.
    rbox = (cm(10.75), my - cm(0.45), W - pad, my + cm(0.45))
    card(d, rbox, NAVY_FILL, NAVY, 4, 12)
    centered(d, rbox, "지금 시작", f10b, NAVY)

    return save(img, "readiness")


# ---------------------------------------------------------------------------
# 15. 검증 트랙 — 3구간 게이트. 조건을 못 넘으면 다음 칸으로 안 간다
# ---------------------------------------------------------------------------
def fig_verify_track(width_cm=13.3, height_cm=2.6) -> Path:
    """content.VERIFY_PLAN 을 칸 본문으로 읽는다(9회차). 목표 퍼센트는 적지 않는다(§0-3).

    11회차 : PRIOR_WORK → fig_prior 교체로 확보된 p5 여유에 배선한다(build_docx.py:549
    주석의 투입 조건 충족). 높이 3.0→2.6 으로 p5 순증을 최소화한다.
    """
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f8b, f9b = font(8, True), font(9, True)

    import content as C

    gates = []
    for item in C.VERIFY_PLAN:
        head, _, body = item.partition(" — ")
        when, _, title = head.partition(" ")
        gates.append((when, title, body.rstrip(".")))
    passes = ["조치 미실행", "2주 연속 누락 0건", "전건 감사"]

    pad = cm(0.12)
    agap = cm(0.45)
    gw = (W - 2 * pad - agap * 2) / 3
    y0, y1 = cm(0.10), cm(2.30)
    for i, ((when, title, body), cond) in enumerate(zip(gates, passes)):
        x0 = pad + i * (gw + agap)
        card(d, (x0, y0, x0 + gw, y1), WHITE, LINE, 2, 10)
        bw_ = text_w(d, when, f8b) + cm(0.20)
        d.rounded_rectangle((x0 + cm(0.10), y0 + cm(0.10), x0 + cm(0.10) + bw_,
                             y0 + cm(0.46)), radius=6, fill=SLATE)
        centered(d, (x0 + cm(0.10), y0 + cm(0.10), x0 + cm(0.10) + bw_, y0 + cm(0.46)),
                 when, f8b, WHITE)
        d.text((x0 + cm(0.22) + bw_, y0 + cm(0.14)), title, font=f9b, fill=NAVY)
        block(d, (x0 + cm(0.08), y0 + cm(0.54), x0 + gw - cm(0.08), y1 - cm(0.56)),
              body, [8, 7.5, 7], INK, max_lines=3, line_gap=1.05)
        tb = (x0 + cm(0.08), y1 - cm(0.46), x0 + gw - cm(0.08), y1 - cm(0.08))
        d.rounded_rectangle(tb, radius=7, fill=NAVY_FILL, outline=NAVY, width=2)
        centered(d, tb, cond, f8b, NAVY)
        if i:
            arrow(d, x0 - agap + cm(0.04), (y0 + y1) / 2, x0 - cm(0.04), GRAY, 4)

    ay = cm(2.52)
    d.line([(pad, ay), (W - pad, ay)], fill=LINE, width=3)
    for i in range(3):
        cx = pad + i * (gw + agap) + gw / 2
        r = cm(0.06)
        d.ellipse((cx - r, ay - r, cx + r, ay + r), fill=SLATE)

    return save(img, "verify_track")


# ---------------------------------------------------------------------------
# 16. 닫힌 고리 — 시작(입구 둘) → 코어 → 승인·이력 등록 → 그 이력이 다시 검색 근거로
# ---------------------------------------------------------------------------
def fig_loop(width_cm=13.3, height_cm=1.30) -> Path:
    """Process 20점 #2(시작부터 결과 활용까지)의 근거가 불릿 두 줄뿐이었다 —
    같은 주장을 닫힌 고리 구조로 올린다(10회차, NOT_SINGLE 불릿을 대체).

    ASCII 로 그리지 않는다 : 바탕체는 박스문자·한글이 전각, 영문·숫자가 반각이라 칸 맞춤이
    전각공백 개수에 매달린다. p2 는 한 줄만 접혀도 6페이지가 된다.
    '월 4회 재학습'은 넣지 않는다 — p3 오케스트레이션 하단 띠가 이미 그 문장을 쓴다.
    """
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f8, f8b = font(8), font(8, True)

    pad = cm(0.06)
    y0, y1 = pad, cm(0.84)
    lw, mw, rw = cm(3.6), cm(4.2), cm(4.2)
    lx0 = pad
    gapw = (W - 2 * pad - lw - mw - rw) / 2
    mx0 = lx0 + lw + gapw
    rx0 = mx0 + mw + gapw

    def duo(x0, w, fill, edge, head, sub, head_color):
        card(d, (x0, y0, x0 + w, y1), fill, edge, 2, 9, shadow=False)
        block(d, (x0 + cm(0.05), y0 + cm(0.04), x0 + w - cm(0.05), y0 + cm(0.44)),
              head, [10, 9.5, 9, 8.5], head_color, bold=True, max_lines=1)
        block(d, (x0 + cm(0.05), y0 + cm(0.44), x0 + w - cm(0.05), y1 - cm(0.02)),
              sub, [8.5, 8, 7.5, 7], SLATE, max_lines=1)

    # 시작 — 사람이 아니다 / 코어 하나 / 끝 — 검색 자산
    duo(lx0, lw, GRAY_FILL, SLATE, "시작 · 사람이 아니다", "① Chat · ② 무인 감지", SLATE)
    arrow(d, lx0 + lw + cm(0.08), (y0 + y1) / 2, mx0 - cm(0.06), SLATE, 4)
    duo(mx0, mw, RED_FILL, RED, "조사 → 판정 → 조치안", "코어 하나", RED)
    arrow(d, mx0 + mw + cm(0.08), (y0 + y1) / 2, rx0 - cm(0.06), SLATE, 4)
    duo(rx0, rw, NAVY_FILL, NAVY, "승인 · 이력 등록", "끝 · 검색 자산이 된다", NAVY)

    # 복귀선 — 확정 이력이 다음 사건의 근거로 돌아온다
    ry = cm(1.08)
    bx, ex = rx0 + rw / 2, lx0 + cm(0.45)
    d.line([(bx, y1), (bx, ry), (ex, ry)], fill=NAVY, width=3)
    d.line([(ex, ry), (ex, y1 + cm(0.12))], fill=NAVY, width=3)
    d.polygon([(ex, y1), (ex - 9, y1 + cm(0.16)), (ex + 9, y1 + cm(0.16))], fill=NAVY)
    lab = "확정 이력이 다음 사건의 검색 근거로 돌아온다"
    lw_ = text_w(d, lab, f8b)
    cx = (bx + ex) / 2
    d.rectangle((cx - lw_ / 2 - cm(0.12), ry - cm(0.20), cx + lw_ / 2 + cm(0.12),
                 ry + cm(0.20)), fill=WHITE)
    centered(d, (cx - lw_ / 2, ry - cm(0.18), cx + lw_ / 2, ry + cm(0.18)), lab, f8b, NAVY)

    return save(img, "loop")


# ---------------------------------------------------------------------------
# 17. 알고리즘 선택 근거 — 밴드 3개(코어/감지/판독·검색), 카드마다 '채택 + 기각 대안'
# ---------------------------------------------------------------------------
def fig_algo_choice(width_cm=13.3, height_cm=7.8) -> Path:
    """content.ALGO_CHOICE (밴드, 채택 모델, 채택 근거, 기각 대안) 4튜플을 읽는다(11회차).

    ALGO_ROWS 표를 대체 — 근거는 기각 대안이 옆에 보일 때만 근거로 읽힌다.
    문구는 ALGO_ROWS 원문 근거를 채택/기각 두 줄로 자른 것뿐, 새 비교평가는 없다(규칙 6).
    카드 내부 3단(모델명/근거/기각)은 고정 비율이 아니라 실측 줄 수로 높이를 나눈다 —
    고정 비율로는 긴 문구가 옆 구역을 덮어 잘리거나 겹쳐 보이는 사고가 났다(11회차 1차 시도).
    """
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    f9 = font(9, True)
    fcap = font(9)

    import content as C

    pad = cm(0.12)
    lane_x = pad + cm(1.5)
    inner_w = W - lane_x - pad
    band_fill = {"코어": BAND_ORCH, "감지": BAND_IN, "판독·검색": BAND_MODEL}
    # 코어 밴드는 모델명 1줄이라 여유가 적어도 되고, 감지·판독 밴드는 모델명이 2줄까지
    # 늘어나는 카드가 있어 더 크게 준다(렌더 실측으로 재배분 — 11회차 2차 시도).
    band_h = {"코어": cm(1.60), "감지": cm(2.70), "판독·검색": cm(2.50)}
    card_gap = cm(0.15)
    band_gap = cm(0.12)
    inset = cm(0.08)

    def measure(s, max_w, max_lines, sizes):
        f, lines = fit_wrap(d, s, max_w, max_lines, sizes)
        asc, desc = f.getmetrics()
        return int((asc + desc) * 1.04) * len(lines)

    groups = []
    for row in C.ALGO_CHOICE:
        label = row[0]
        if groups and groups[-1][0] == label:
            groups[-1][1].append(row)
        else:
            groups.append((label, [row]))

    y = cm(0.20)
    for gi, (label, rows) in enumerate(groups):
        bh = band_h.get(label, cm(2.2))
        d.rounded_rectangle((pad, y, W - pad, y + bh), radius=10, fill=band_fill.get(label, GRAY_FILL))
        centered(d, (pad, y, lane_x - cm(0.06), y + bh), label, f9, INK)

        n = len(rows)
        cw = (inner_w - card_gap * (n - 1)) / n
        cy0, cy1 = y + cm(0.10), y + bh - cm(0.10)
        ch = cy1 - cy0
        avail_w = cw - 2 * inset
        for i, (_, model, reason, reject) in enumerate(rows):
            x0 = lane_x + i * (cw + card_gap)
            box = (x0, cy0, x0 + cw, cy1)
            card(d, box, WHITE, LINE, 2, 9, shadow=False)

            # 세 영역을 각각 실측하고, 합이 카드 높이를 넘으면 근거→기각 순으로 폰트를
            # 낮춰 다시 잰다. 자리를 셋 다 실측해 순서대로 배치하므로 서로 겹치지 않는다
            # (11회차 1차 시도의 결함 — '남는 자리'를 모델명에 몰아줘 근거가 모델명을 덮었다).
            name_h = measure(model, avail_w, 2, [9.5, 8.5, 8]) + cm(0.06)
            reason_sizes = [8.5, 8, 7.5]
            reason_h = measure(reason, avail_w, 2, reason_sizes) + cm(0.08)
            reject_sizes = [8, 7.5, 7]
            reject_h = measure(reject, avail_w, 2, reject_sizes) + cm(0.08)
            if name_h + reason_h + reject_h > ch:
                reason_sizes = [7.5, 7]
                reason_h = measure(reason, avail_w, 2, reason_sizes) + cm(0.05)
            if name_h + reason_h + reject_h > ch:
                reject_sizes = [7, 6.5]
                reject_h = measure(reject, avail_w, 2, reject_sizes) + cm(0.05)
            if name_h + reason_h + reject_h > ch:
                # 마지막 안전판 — 세 영역 비례 축소(겹침 대신 카드 하단에서 살짝 눌리는 쪽을 택한다)
                scale = ch / (name_h + reason_h + reject_h)
                name_h, reason_h, reject_h = name_h * scale, reason_h * scale, reject_h * scale

            block(d, (x0 + inset, cy0, x0 + cw - inset, cy0 + name_h),
                  model, [9.5, 8.5, 8], NAVY, bold=True, max_lines=2, pad=0, line_gap=1.0)
            ry0 = cy0 + name_h
            block(d, (x0 + inset, ry0, x0 + cw - inset, ry0 + reason_h),
                  reason, reason_sizes, INK, max_lines=2, pad=0, line_gap=1.0)
            rj0 = ry0 + reason_h
            d.rectangle((x0 + cm(0.02), rj0, x0 + cw - cm(0.02), cy1 - cm(0.02)), fill=GRAY_FILL)
            block(d, (x0 + inset, rj0, x0 + cw - inset, cy1 - cm(0.02)),
                  reject, reject_sizes, SLATE, max_lines=2, pad=0, line_gap=1.0)
        y += bh
        if gi < len(groups) - 1:
            y += band_gap

    centered(d, (pad, y + cm(0.06), W - pad, H - cm(0.04)),
             "모델마다 버린 대안이 있다 — 성능이 아니라 자리에 맞춰 골랐다", fcap, SLATE)

    return save(img, "algo_choice")


# ---------------------------------------------------------------------------
# 18. 성능 지표 — 좌 recall@10 큰 숫자, 우 '0건으로 관리한다' 상자
# ---------------------------------------------------------------------------
def fig_metrics(width_cm=13.3, height_cm=2.0) -> Path:
    """content.METRICS_KEY/METRICS_TAIL/METRICS[0] 원문만 옮긴다(11회차) — 새 수치 없음.

    좌 40% recall@10=0.500(문서 유일 실측치), 우 60% '0건으로 관리한다' 3항.
    테두리는 NAVY — 같은 지면 fig_verifier_gate 의 관문이 이미 붉어 두 번째 빨강
    로커스를 만들지 않는다. ✕ 기호도 안 쓴다(fig_algo_choice 의 ✕ '기각 대안'과 뜻이 겹친다).
    """
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)
    fnum = font(22, True)
    f8, f8b, f10b = font(8), font(8, True), font(10, True)

    pad = cm(0.10)
    left_w = cm(5.3)
    gap = cm(0.20)
    rx0 = pad + left_w + gap

    lbox = (pad, pad, pad + left_w, H - pad)
    d.rounded_rectangle(lbox, radius=10, fill=GRAY_FILL)
    centered(d, (pad, pad + cm(0.06), pad + left_w, pad + cm(0.32)), "recall@10", f8, NAVY)
    centered(d, (pad, pad + cm(0.24), pad + left_w, pad + cm(0.98)), "0.500", fnum, NAVY)
    block(d, (pad + cm(0.15), pad + cm(1.00), pad + left_w - cm(0.15), H - pad - cm(0.04)),
          "골든 4건 → 30건 확장 예정 · 색인 50건 · 회귀 러너 실측 — 회귀 검출용 기준선이다",
          [7.5, 7, 6.5], GRAY, max_lines=2, line_gap=1.05)

    rbox = (rx0, pad, W - pad, H - pad)
    rounded(d, rbox, WHITE, NAVY, width=4, r=10)
    d.text((rx0 + cm(0.16), pad + cm(0.08)), "0 건으로 관리한다", font=f10b, fill=NAVY)
    items = ["근거 없는 판단 채택", "미승인 L2 조치 실행", "무인 접수 누락"]
    iy = pad + cm(0.48)
    for it in items:
        sq = cm(0.08)
        cy = iy + cm(0.10)
        d.rectangle((rx0 + cm(0.18) - sq, cy - sq, rx0 + cm(0.18) + sq, cy + sq), fill=NAVY)
        d.text((rx0 + cm(0.36), iy), it, font=f8b, fill=INK)
        iy += cm(0.30)
    block(d, (rx0 + cm(0.16), H - pad - cm(0.34), W - pad - cm(0.10), H - pad - cm(0.02)),
          "검증기 차단 로그와 감사 로그로 센다", [7.5, 7], GRAY, max_lines=1)

    return save(img, "metrics")


# ---------------------------------------------------------------------------
# 19. 선행 추진 실적 4칸 배지 — 구현 / 평가 / 선행 프로토타입 / 설계
# ---------------------------------------------------------------------------
def fig_prior(width_cm=13.3, height_cm=2.6) -> Path:
    """PRIOR_WORK 4행 표(11회차) 를 배지 띠로 옮긴다 — 값은 CLAUDE.md §9-5 사실 카드 원문.

    ③칸('선행 프로토타입')은 반드시 '군집 지표'를 먼저 명시한다 — AMI·ARI 를 판정
    정확도로 부르는 것은 §0-3 금지다.
    """
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    pad = cm(0.10)
    widths = [cm(3.0), cm(3.0), cm(4.6), cm(2.7)]
    items = [
        ("구현", "검증기 5칙", "조사 코어 스켈레톤 실행 확인 · prod 백엔드 4종"),
        ("평가", "recall@10 0.500", "골든 4건 / 색인 50건 · 회귀 러너 실측"),
        ("선행 프로토타입", "AMI 0.956 · ARI 0.860",
         "불량 이미지 임베딩 군집 지표. 노이즈 0.52% (43 class · 900 wafer). agentic RAG "
         "전 요소와 이미지 유사 검색·메타 키 조회가 돈다"),
        ("설계", "31종", "시스템설계서 · 로드맵 · Tool 카탈로그 · 그라운딩 · 조사규칙"),
    ]
    x = pad
    for i, ((label, badge, desc), w) in enumerate(zip(items, widths)):
        if i:
            d.line([(x, cm(0.10)), (x, H - cm(0.10))], fill=DIV, width=2)
        cx0, cx1 = x + cm(0.10), x + w - cm(0.10)
        block(d, (cx0, cm(0.04), cx1, cm(0.36)), label, [9.5, 9, 8.5, 8], NAVY, bold=True,
              max_lines=1)
        d.line([(cx0, cm(0.42)), (cx1, cm(0.42))], fill=NAVY, width=2)
        bf, blines = fit_wrap(d, badge, cx1 - cx0, 1, [10, 9, 8, 7.5])
        bline = blines[0] if blines else badge
        bw_ = text_w(d, bline, bf) + cm(0.18)
        asc, desc_m = bf.getmetrics()
        bh_ = int((asc + desc_m) * 1.15) + cm(0.10)
        by0 = cm(0.52)
        rounded(d, (cx0, by0, cx0 + bw_, by0 + bh_), NAVY_FILL, NAVY, 2, r=8)
        centered(d, (cx0, by0, cx0 + bw_, by0 + bh_), bline, bf, NAVY)
        # 11회차 렌더 실측 : ③칸(선행 프로토타입) 부연이 max_lines=3 에서 마지막 절이
        # 말없이 잘렸다(block() 은 넘치면 ...없이 버린다) — 4로 올린다. 박스 안 실측 여유로
        # 4줄도 들어간다(by0+bh_+0.08 ~ H-0.06 사이).
        block(d, (cx0, by0 + bh_ + cm(0.08), cx1, H - cm(0.06)), desc, [8, 7.5, 7], GRAY,
              max_lines=4, line_gap=1.0)
        x += w

    return save(img, "prior")


# ---------------------------------------------------------------------------
# 20. 도구 8종 칩 띠 — SQL 5 / Vision 2 / RAG 1
# ---------------------------------------------------------------------------
def fig_tools(width_cm=13.3, height_cm=1.55) -> Path:
    """CLAUDE.md §9-3 도구 8종 목록 그대로 노출한다(11회차) — 신조어 금지.

    p3 하단 공백을 닫는다. 전문 Agent 4종까지만 보이던 오케스트레이션 그림 옆에
    실제 함수 이름이 붙으면 개념도가 구현물로 내려온다. 1.75→1.55 — p3(Tech①) 물리
    페이지 슬랙이 1.58cm 뿐이라 렌더 실측으로 낮췄다(넘치면 그림 전체가 다음 장으로 밀린다).
    """
    W, H = cm(width_cm), cm(height_cm)
    img = Image.new("RGB", (W, H), WHITE)
    d = ImageDraw.Draw(img)

    groups = [
        ("SQL 5", cm(7.0), BAND_IN,
         ["get_spc_trend", "commonality_analysis", "get_master_info",
          "get_interlock_history", "search_fab_data"]),
        ("Vision 2", cm(3.0), BAND_MODEL,
         ["classify_wafer_map", "analyze_defect_images"]),
        ("RAG 1", cm(2.8), BAND_OUT,
         ["search_inform_notes"]),
    ]
    f8b = font(8.5, True)
    pad = cm(0.10)
    gap = cm(0.15)
    top_h = H - cm(0.42)
    x = pad
    for label, w, fill, names in groups:
        box = (x, cm(0.04), x + w, top_h)
        rounded(d, box, fill, LINE, 2, r=8)
        d.text((x + cm(0.12), cm(0.10)), label, font=f8b, fill=INK)
        block(d, (x + cm(0.10), cm(0.42), x + w - cm(0.08), top_h - cm(0.04)),
              " · ".join(names), [7.5, 7], SLATE, max_lines=3, line_gap=1.08)
        x += w + gap

    block(d, (pad, top_h + cm(0.04), W - pad, H - cm(0.02)),
          "조회 전용 — 통계·공통성 분석은 코드가 계산한다. 마스터 Agent 가 사안마다 골라 "
          "5~15회 부른다", [8.5, 8, 7.5], GRAY, max_lines=1)

    return save(img, "tools")


ALL = {
    "loop": fig_loop,
    "algo_choice": fig_algo_choice,
    "metrics": fig_metrics,
    "prior": fig_prior,
    "tools": fig_tools,
    "workflow_e2e": fig_workflow,
    "spread": fig_spread,
    "ablation_cascade": fig_ablation_cascade,
    "intangible": fig_intangible,
    "orchestration": fig_orchestration,
    "time_compare": fig_time,
    "action_ladder": fig_ladder,
    "problem_four": fig_problem,
    "verifier_gate": fig_verifier,
    "effect_big": fig_effect,
    "sensitivity": fig_sensitivity,
    "alternatives": fig_alternatives,
    "burden": fig_burden,
    "readiness": fig_readiness,
    "verify_track": fig_verify_track,
}


def build_all():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    out = []
    for name, fn in ALL.items():
        out.append(fn())
    return out


if __name__ == "__main__":
    for p in build_all():
        print(f"OK {p}")
