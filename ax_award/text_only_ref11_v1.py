from __future__ import annotations

import hashlib
import re
from pathlib import Path


REFERENCE = Path(r"C:\Users\hgcho\Downloads\사내 AI 프로젝트 디자인 개선 (11)\AX Award 지원서.dc.html")
TARGET = Path(r"D:\project\q-agent\ax_award\html\AX_Award_지원서_ref11_v1.html")
REFERENCE_SHA256 = "48EB829074E29E680EE7F53146895E42E4A4650030F921E961CC07F449452AC9"


REPLACEMENTS = [
    # P1
    ("품질 조사, 판정, 조치 전 과정을 연결하는 AI Agent Orchestration 구축", "이상 접수부터 확정 이력 재사용까지 연결하는 E2E 품질 대응 구축"),
    ("— 감지부터 원인 조사, 판정, 조치안 생성, 이력 등록까지 자동으로 연결하고 단계적으로 자동조치까지 확대하는 품질 관리 시스템", "이상 접수, 조사, 판정, 조치안, 승인, 이력 등록과 재사용을 연결하는 품질 관리 시스템"),
    ("해결하고자 하는 문제 — 감지는 자동, 원인 조사와 판정은 사람 손", "해결할 E2E 문제 — 이상 접수 뒤 조사, 판정, 조치, 확정 이력이 끊긴다"),
    ("현업 사례", "예시 시나리오"),
    ("단일 벡터 검색이라 설비 ID·약어 식별력이 낮다", "범용 문서 검색용이라 사고번호 key 조회와 Trend·Image 연계가 없다"),
    ("데이터 기반은 이미 서 있다.", "지금 시작할 조건은 세 가지다."),
    ("사고 이력 RDB, 설비 이력, Trend, 불량 이미지와 문서 데이터가 쌓여 있고 회귀 평가 환경과 recall 측정 체계까지 갖췄다.", "데이터: 사고 RDB, 설비 이력, Trend, 이미지 / 기술: 조사 코어와 검색 연계 / 검증: 회귀 평가와 recall 측정 체계를 확보했다."),

    # P2
    ("E2E Process 중 반복 수작업 구간을 AI Agent로 대체", "E2E 전체 재설계 — 접수부터 사람 확정, 이력 재사용까지"),
    ("다섯 정거장이 통째로 내려온다 — 자율 tool calling, 합산 수 초", "조사 코어 수 초는 목표, 전체 업무 14h는 현업 산정"),
    ("시작 — 사람이 아니다", "접수 — Chat 또는 감지 이벤트"),
    ("끝 — 자산이 된다", "확정 — 승인 이력을 등록"),
    (". 공정이 3개로 늘어도 추가 자원을 요청하지 않는다.", ". 공정별 연결 범위는 검증 결과에 따라 확정한다."),
    ("— 조사규칙 초안(3Q·공정 담당) · 조치 승인·반려(상시) · 골든셋 확정(분기). 노하우가 등록될수록 시스템이 그 팀에 맞게 자란다. 오탐 남발은 이벤트 그룹핑·수신자 피드백으로 조정(조회는 정보계 경유 전용 — 1Q 통과 조건).", "— 조사규칙 초안(3Q 공정 담당), 조치 승인과 반려(상시), 골든셋 확정(분기). 등록 결과는 다음 검색과 평가에 사용한다. 오탐은 이벤트 그룹핑과 수신자 피드백으로 조정한다."),
    ("5·6Q etch·CMP 확산", "5Q etch 확산"),
    ("3개 공정 — 코어 변경 0", "통과 조건 — 조사 코어 변경 0"),
    ("표준안으로 자원 증설 없이 이관", "검증 완료 표준안으로 이관"),
    ("현행 Workflow와 개선 Workflow — 어디를 대체했는지", "현행과 개선 Workflow — E2E 대체 범위"),
    ("도구 호출 5~15회, 수 초", "도구 호출 5~15회, 조사 코어 수 초 [목표]"),
    ("붉은 구간이 사람 수작업이고, 그 자리를 짙은 구간이 그대로 대체한다.", "현행 수작업 구간을 Agent 자동 조사로 전환한다."),

    # P3
    ("품질 AI Agent Orchestration — 전체 동작 한 장", "품질 AI Agent Orchestration — E2E 전체 흐름"),
    ("감지·질문에서 조치 실행·이력 등록·재학습까지, 한 코어로 닫힌다", "감지와 질문부터 조치, 이력 등록, 재학습까지 한 코어로 연결한다"),
    ("쓸수록 정확해진다 ↗", "확정 이력으로 정기 갱신 ↗"),
    ("전문 모델 구성 — 이미지·Trend 두 갈래 모두 자체 개발로 이미 돌고 있다", "선행 전문 모델 실측 — 이미지 프로토타입 A와 Trend 모델"),
    ("이미지 · unknown-contrastive", "선행 이미지 프로토타입 A"),
    ("— 라벨 없이 배우는 대비학습", "— 라벨 없이 배우는 대조 학습"),
    ("ConvNeXt V2 분류 + contrastive 유사 검색", "ConvNeXt V2 분류 + 대조 학습 유사 검색"),
    ("부품 사다리 실측 — 오적재 6.20→0.52% · 군집 ARI 0.823→0.860 (43 class·900 wafer)", "선행 이미지 A 실측 — noise ratio 6.20→0.52%, 군집 ARI 0.823→0.860 (43 class, 900 wafer)"),
    ("실행 트레이스 — 이미지로 시작하든 사고 문의로 시작하든 같은 코어를 지난다", "실행 예시 — 이미지와 사고 문의가 같은 코어를 통과한다"),

    # P4
    ("Image / Trend", "Image / Trend [실행 예시]"),
    ("스토리지에 쌓인 과거 불량 이미지와 contrastive 학습 모델로 유사도를 비교", "저장된 과거 불량 이미지와 대조 학습 모델로 유사도를 비교"),
    ("Agent를 하나씩 붙일 때마다 답이 자란다 — 프롬프트에 무엇이 들어가 답이 어떻게 달라지나", "Agent 추가에 따라 근거가 보강된다 — 동일 입력의 단계별 비교"),
    ("(ablation · 같은 사례 실측)", "(동일 입력 예시 비교)"),
    ("가설이 설비 이력과 맞물립니다. 원인 확정.", "가설과 설비 이력이 일치합니다. 원인 확정."),
    ("② contrastive 임베딩", "② 대조 학습 임베딩"),
    ("더 부를 도구가 없을 때 Q/A LLM이 답을 닫는다.", "추가 도구가 없을 때 Q/A LLM이 판정서를 작성한다."),
    ("이 파이프는 세 갈래로 배운다", "세 가지 방식으로 갱신한다"),
    ("추후 확장 (2차년 검토) — 지식을 검색에서 관계 탐색까지 넓힌다", "[2차년 확장 설계] 검색을 관계 탐색까지 확장한다"),
    ("읽어서 찾아가는", "문서 연결을 따라 검색하는"),
    ("회귀 기준선 · recall@10", "Q-Agent 실측 · recall@10"),
    ("골든 4건→30건 확장 예정 · 색인 50건 · 회귀 러너 실측", "골든 4건, 색인 50건, 회귀 러너 실측"),
    ("0건으로 관리한다", "운영 목표 0건"),
    ("선행 프로토타입 실측", "선행 검색 B / 이미지 A 실측"),
    ("26질의 hit@1", "선행 검색 프로토타입 B · 26질의 hit@1"),
    ("· 하드셋 38질의", "하드셋 38질의"),
    ("· 군집 품질 AMI", "선행 이미지 프로토타입 A · 군집 품질 AMI"),
    ("/ARI 0.860 — Qwen3 교체 후 재측정", "/ ARI 0.860 [선행 이미지 A 실측]"),

    # P5
    ("IV. 경영효과", "IIII. 경영효과"),
    (';border-radius:5px;padding:4px 9px">', ""),
    ("연간 ROI — 투자 연 347,794,165원 대비", "연 편익/비용 배수 — 연 투자 347,794,165원 기준"),
    ("투자 회수 — 2개년 총투자 기준 12.7일", "연 투자액 기준 6.3일 / 2개년 총투자액 기준 12.7일"),
    ("민감도 — 실측이 낮으면 같은 비율로 하향. 절감이 반이어도 ROI 14배.", "민감도 — 30분 절감 시 편익/비용 배수 14.4배. 실측값으로 갱신."),
    ("구현", "기술 구현"),
    ("평가", "Q-Agent 실측"),
    ("선행 프로토타입", "선행 이미지 A 실측"),
    ("군집 품질 AMI 0.956 · ARI 0.860", "군집 AMI 0.956 / ARI 0.860"),
    ("노이즈 0.52% · 43 class·900 wafer — RAG 전 요소·유사 검색·메타 키 조회 가동", "noise 0.52% / 43 class / 900 wafer"),
    ("신규 과제이지만 백지가 아니다 — 이미 서 있는 선행 실적", "선행 추진 실적과 운영 준비"),
    ("설계", "검증 기준"),
    ("설계 문서 31종", "안전 gate 5칙 정의"),
    ("시스템설계서, 로드맵, Tool 카탈로그, 조사규칙", "근거, 수치, 승인, 스키마, 도구 권한"),
    ("조사 코어 스켈레톤 실행", "생산계 인터페이스 정의"),
    ("검증기 5칙 가동, prod 백엔드 4종 연결", "SPC, MES, 이미지, 사고 원장 연결 명세"),
    ("회귀 러너 + recall 실측", "선행 검색 B 실측"),
    ("recall@10 0.500 · 골든 4건, 색인 50건", "hit@1 1.000 / hard 0.957"),
    ("데이터", "데이터 준비"),
    ("사고 DB · 색인 구축", "사고 원장과 색인 구축"),
    ("자원", "운영 준비"),
    ("GPU 수요 등록 완료", "3Q Shadow 계획 확정"),
    ("1차년 학습·추론 물량 반영", "담당 판정, 처리 시간, 누락 기준선"),
    ("검증 게이트", "측정 gate"),
    ("3Q 그림자 운영", "3Q 기준선 수집"),
    ("조치 미실행, 담당 판정을 정답으로 일치율 기준선과 4h 가정 실측", "처리 시간, 판정 일치율, 반려율 기록"),
    ("4Q 무인 접수", "4Q 무인 접수 검증"),
    ("2주 연속 누락 0건, 처리 시간과 조치 승인율 분기 보고", "누락, 승인율, 오탐율 분기 확인"),
    ("2차년 자동조치", "2차년 L5 개별 심의"),
]

SEQUENTIAL_REPLACEMENTS = {
    (5, "구현"): ["기술 구현", "연계 준비"],
    (5, "평가"): ["Q-Agent 실측", "선행 검색 B"],
    (5, "설계"): ["설계 자산", "검증 기준"],
    (5, "3Q 그림자 운영"): ["3Q 그림자 운영", "3Q 기준선 수집"],
    (5, "4Q 무인 접수"): ["4Q 무인 접수", "4Q 무인 접수 검증"],
}
SUBSTRING_REPLACEMENTS = {
    "가설이 설비 이력과 맞물립니다. 원인 확정.",
    "더 부를 도구가 없을 때 Q/A LLM이 답을 닫는다.",
    "이 파이프는 세 갈래로 배운다",
}


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest().upper()


def scan_parts(raw: str):
    """Yield (is_tag, bytes-as-text) without normalizing any markup."""
    pos = 0
    data_start = 0
    n = len(raw)
    while pos < n:
        if raw[pos] != "<":
            pos += 1
            continue
        if data_start < pos:
            yield False, raw[data_start:pos]
        tag_start = pos
        quote = None
        pos += 1
        while pos < n:
            ch = raw[pos]
            if quote:
                if ch == quote:
                    quote = None
            elif ch in ("'", '"'):
                quote = ch
            elif ch == ">":
                pos += 1
                break
            pos += 1
        yield True, raw[tag_start:pos]
        data_start = pos
    if data_start < n:
        yield False, raw[data_start:]


def transform_visible_text(raw: str):
    output = []
    tag_tokens = []
    raw_text_tag = None
    page_number = 0
    counts = {old: 0 for old, _ in REPLACEMENTS}
    sequential_index = {key: 0 for key in SEQUENTIAL_REPLACEMENTS}

    for is_tag, part in scan_parts(raw):
        if is_tag:
            output.append(part)
            tag_tokens.append(part)
            match = re.match(r"<\s*(/?)\s*([a-zA-Z0-9:-]+)", part)
            if match:
                closing, name = match.group(1), match.group(2).lower()
                if not closing and name == "section" and re.search(r'''class\s*=\s*["'][^"']*\bpage\b''', part):
                    page_number += 1
                if closing and raw_text_tag == name:
                    raw_text_tag = None
                elif not closing and name in {"script", "style"} and not part.rstrip().endswith("/>"):
                    raw_text_tag = name
            continue

        if raw_text_tag:
            output.append(part)
            continue

        changed = part
        stripped = changed.strip()
        seq_key = (page_number, stripped)
        if seq_key in SEQUENTIAL_REPLACEMENTS:
            index = sequential_index[seq_key]
            options = SEQUENTIAL_REPLACEMENTS[seq_key]
            if index >= len(options):
                raise RuntimeError(f"Unexpected extra occurrence: {seq_key}")
            new = options[index]
            sequential_index[seq_key] += 1
            counts[stripped] += 1
            changed = changed.replace(stripped, new, 1)
        else:
            for old, new in REPLACEMENTS:
                if stripped == old:
                    counts[old] += 1
                    changed = changed.replace(old, new, 1)
                    break
                if old in SUBSTRING_REPLACEMENTS and old in changed:
                    counts[old] += changed.count(old)
                    changed = changed.replace(old, new)
        changed = re.sub(r"\s*·\s*", ", ", changed)
        changed = re.sub(r"\s+—\s+", ": ", changed)
        output.append(changed)

    return "".join(output), tag_tokens, counts


reference = REFERENCE.read_text(encoding="utf-8")
current = TARGET.read_text(encoding="utf-8")
if sha256(reference) != REFERENCE_SHA256 or sha256(current) != REFERENCE_SHA256:
    raise RuntimeError("v1 is not the byte-identical reference baseline")

updated, before_tags, counts = transform_visible_text(current)
after_tags = [part for is_tag, part in scan_parts(updated) if is_tag]
if before_tags != after_tags:
    raise RuntimeError("Markup token changed during text-only edit")

missing = [old for old, _ in REPLACEMENTS if counts[old] == 0]
if missing:
    raise RuntimeError("Expected text not found: " + repr(missing))

TARGET.write_text(updated, encoding="utf-8")
print(TARGET)
print("before_sha256", REFERENCE_SHA256)
print("after_sha256", sha256(updated))
print("tag_tokens", len(before_tags), "unchanged", before_tags == after_tags)
