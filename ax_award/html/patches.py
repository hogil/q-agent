"""소스(ax_dc.html)에 남은 정합 오류를 조립 시점에 고친다. 원본은 건드리지 않는다.

이력
  · 2026-08-09 교정(사고 원장 1순위 · meta 선별 후 하이브리드 · 이미지는 RAG DB 먼저 ·
    합류는 Router 증거 스택 · 도구 종료 후 Q/A 인계 · Router T=0 / Q/A T≈0.3)은
    **소스 (6) 세대에서 원저자가 전부 반영**했다 — 해당 패치는 전부 뺐다.
  · 남은 것은 도구 이름 정합뿐이다. 트레이스가 부르는 `search_rag`,
    `search_similar_image` 는 문서 어디에도 정의가 없는 이름이고,
    `search_incidents` / `get_incident` 는 쓰이는데 카탈로그에 빠져 있다.
    "사고 원장이 1번" 이라면서 도구 목록에 원장이 없으면 앞뒤가 안 맞는다.
"""
import re

PATCHES = [
    # ── 없는 도구 이름 → 실제 카탈로그 이름 ────────────────────────────────
    ("search_similar_image(img)", "analyze_defect_image(img)"),
    ("search_rag(meta)", "search_engr_notes(meta)"),
    ("도구 스키마 8종", "도구 스키마 10종"),

    # ── p4 §7 도구 카탈로그 — 원장 그룹을 맨 앞에 세운다 ────────────────────
    ('<div style="flex:2.2;background:#F2F5FA;border-radius:4px;padding:3px 8px">'
     '<span style="font-size:8.5px;font-weight:900;color:#0F1E3D">SQL 5</span>',

     '<div style="flex:1.5;background:#E6F7F6;border:1px solid #12B5B0;border-radius:4px;padding:3px 8px">'
     '<span style="font-size:8.5px;font-weight:900;color:#0F1E3D">원장 2</span> '
     '<span style="font-size:7px;font-weight:700;color:#0E9C97">사고 건이면 여기가 1번</span> '
     '<span style="font-size:7.5px;color:#3E4C64;font-family:ui-monospace,monospace">search_incidents · get_incident</span></div>'
     '<div style="flex:2.0;background:#F2F5FA;border-radius:4px;padding:3px 8px">'
     '<span style="font-size:8.5px;font-weight:900;color:#0F1E3D">SQL 5</span>'),

    # ── p3 §2 RAG 갈래 — 원장이 앞에 온다는 걸 아키텍처 그림에도 ────────────
    ("↓ search_engr_notes(증상)", "↓ search_incidents → search_engr_notes"),

    # ── p3 §2 Router — 도구 종료 판정과 역할 분리(p4 에만 있고 p3 엔 없다) ──
    ("매 턴 Router가 하는 일: 도구 선택 → 호출 인자 생성 → 반환 JSON 해석 → 가설 갱신 → 계속/중단 판단.",
     "매 턴 Router가 하는 일: 도구 선택 → 호출 인자 생성 → 반환 JSON 해석 → 가설 갱신 → 계속/중단 판단. "
     '<b style="color:#FFFFFF">더 부를 도구가 없다고 판정되면 멈추고 Q/A 역할로 넘긴다</b> — '
     "도구를 고르는 역할(T=0)과 답을 쓰는 역할(T≈0.3)은 시스템 프롬프트로만 갈린다(엔진은 하나 — 앞부분 캐시 공유)."),
]

# 검증기 앞 ↓ 를 '도구 종료 → Q/A 인계' 로 바꾼다(줄이 이미 있어 높이 중립).
HANDOFF_RE = (
    r'<div style="text-align:center;font-size:9px;font-weight:900;color:#12B5B0;line-height:1\.1">↓</div>'
    r'(\s*<div style="display:grid;grid-template-columns:1fr auto 1fr auto 1fr)'
)
HANDOFF_TO = (
    '<div style="text-align:center;font-size:7px;font-weight:700;color:#0E9C97;line-height:1.3">'
    '↓ 도구 종료 판정 — <b style="color:#0F1E3D">Q/A 역할이 스택 전체를 받아 판정서 작성</b></div>\\1'
)


def apply(html: str) -> str:
    for old, new in PATCHES:
        if old not in html:
            raise SystemExit(f"패치 대상 없음 — 소스가 바뀌었다:\n  {old[:90]}...")
        html = html.replace(old, new)          # 같은 문자열이 여러 번 나와도 전부
    html, n = re.subn(HANDOFF_RE, HANDOFF_TO, html, count=1)
    if n != 1:
        raise SystemExit("패치 대상 없음 — 검증기 앞 ↓ 를 못 찾았다")
    return html
