#!/usr/bin/env python
"""Create the v50 HTML source without overwriting the approved visual source."""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag


HERE = Path(__file__).parent
SOURCE = HERE / "html" / "AX_Award_지원서.html"
OUTPUT = HERE / "html" / "AX_Award_지원서_v50.html"


def direct_tags(parent: Tag) -> list[Tag]:
    return [node for node in parent.children if isinstance(node, Tag)]


def direct_tables(page: Tag) -> list[Tag]:
    fit = page.select_one(":scope > .fit")
    return [node for node in fit.children if isinstance(node, Tag) and node.name == "table"]


def content_cell(table: Tag, row_index: int = 0) -> Tag:
    row = table.select(":scope > tbody > tr")[row_index]
    return row.find_all("td", recursive=False)[-1]


def set_heading(soup: BeautifulSoup, node: Tag, number: int, title: str) -> None:
    node.clear()
    span = soup.new_tag("span")
    span["style"] = "color:#12B5B0"
    span.string = f"{number}."
    node.append(span)
    node.append(NavigableString(f" {title}"))


def make_heading(soup: BeautifulSoup, number: int, title: str, margin_top: int = 7) -> Tag:
    node = soup.new_tag("div")
    node["style"] = (
        "font-size:12.5px;font-weight:700;color:#0F1E3D;"
        f"margin-top:{margin_top}px"
    )
    set_heading(soup, node, number, title)
    return node


def replace_text(soup: BeautifulSoup, replacements: dict[str, str]) -> None:
    for text_node in list(soup.find_all(string=True)):
        if text_node.parent and text_node.parent.name in {"style", "script"}:
            continue
        value = str(text_node)
        updated = value
        for old, new in replacements.items():
            updated = updated.replace(old, new)
        if updated != value:
            text_node.replace_with(updated)


def add_biz_labels(soup: BeautifulSoup, biz_cell: Tag) -> None:
    parts = direct_tags(biz_cell)
    biz_cell.insert(0, make_heading(
        soup, 1, "유형 효과 — 확산 완료 후 절감 시간을 금액으로 환산한다", 0
    ))

    split = parts[2]
    columns = direct_tags(split)
    if len(columns) >= 2:
        label = soup.new_tag("div")
        label["style"] = "font-size:10px;font-weight:700;color:#0F1E3D;margin-bottom:4px"
        label.string = "민감도"
        columns[0].insert(0, label)

        label = soup.new_tag("div")
        label["style"] = "font-size:10px;font-weight:700;color:#0F1E3D;margin-bottom:4px"
        label.string = "2. 무형 효과"
        columns[1].insert(0, label)

    achievements = parts[3]
    achievements.insert_before(make_heading(
        soup, 3, "선행 실적과 검증 계획 — 이미 구현한 범위부터 현업에서 확인한다", 8
    ))

    for node in direct_tags(biz_cell):
        style = node.get("style", "")
        if "margin-bottom" in style:
            style = re.sub(r"margin-bottom:\s*\d+(?:\.\d+)?px", "margin-bottom:10px", style)
        node["style"] = style


def rewrite_learning_block(soup: BeautifulSoup, rag_block: Tag) -> None:
    children = direct_tags(rag_block)
    if len(children) < 5:
        raise RuntimeError("Agentic RAG block structure changed")
    children[4].decompose()  # unscored future concepts: LLM Wiki / Graph RAG

    learning = children[3]
    learning.clear()

    title = soup.new_tag("div")
    title["style"] = (
        "font-size:8px;font-weight:700;color:#0F1E3D;"
        "border-bottom:1px solid #D7DEEA;padding-bottom:2px;margin-bottom:2px"
    )
    title.string = (
        "개선 과정 — 확정된 승인·수정·반려 이력을 월 4회 반영하고, "
        "골든셋 회귀를 통과한 변경만 배포한다"
    )
    learning.append(title)

    rows = soup.new_tag("div")
    rows["style"] = "display:flex;flex-direction:column;gap:2px"
    data = [
        (
            "검색 전처리",
            "설비·STEP·recipe ID를 보호한 뒤 Kiwi 형태소 분석과 품사 필터를 거쳐 tsvector를 만든다.",
        ),
        (
            "검색기 파인튜닝",
            "확정된 판정-문서 쌍으로 임베딩과 리랭커를 조정한다. 현장 용어가 포함된 문서를 먼저 찾게 한다.",
        ),
        (
            "선호학습",
            "채택 이력은 선호, 반려·수정 이력은 비선호로 사용한다. 근거가 부족하면 판단 불가를 선택하게 한다.",
        ),
    ]
    for label_text, body_text in data:
        row = soup.new_tag("div")
        row["style"] = "display:flex;gap:6px;align-items:baseline"
        label = soup.new_tag("span")
        label["style"] = (
            "flex:none;width:80px;background:#F2F5FA;border-radius:3px;"
            "padding:1px 4px;font-size:7.3px;font-weight:900;"
            "color:#0F1E3D;text-align:center"
        )
        label.string = label_text
        body = soup.new_tag("span")
        body["style"] = "font-size:7.3px;color:#3E4C64;line-height:1.5"
        body.string = body_text
        row.extend([label, body])
        rows.append(row)
    learning.append(rows)


def revise() -> BeautifulSoup:
    soup = BeautifulSoup(SOURCE.read_text(encoding="utf-8"), "html.parser")
    pages = soup.select("section.page")
    if len(pages) != 5:
        raise RuntimeError(f"expected 5 pages, found {len(pages)}")

    # Page 1: finish the problem definition on this page.
    p1_problem = content_cell(direct_tables(pages[0])[1], 1)
    p1_parts = direct_tags(p1_problem)
    p2_problem_table, p2_process_table = direct_tables(pages[1])
    p2_problem = content_cell(p2_problem_table)
    p2_parts = direct_tags(p2_problem)

    set_heading(
        soup,
        p1_parts[0],
        1,
        "해결하려는 문제 — 이상은 바로 잡히지만 원인 확인과 조치 결정은 다음 근무까지 밀린다",
    )
    set_heading(
        soup,
        p1_parts[3],
        2,
        "현업에서 반복되는 네 가지 문제 — 시간·편차·공백·기록",
    )
    set_heading(
        soup,
        p2_parts[0],
        3,
        "현업 중요도와 개선 필요성 — 매일 반복되는 업무이고 오판 비용이 크다",
    )
    set_heading(soup, p1_parts[5], 4, "기존 방식으로 해결되지 않는 이유")
    set_heading(soup, p2_parts[3], 5, "지금 시작할 수 있는 이유")

    # Put importance before the alternatives, then place readiness at the end.
    alternatives_heading = p1_parts[5]
    for node in p2_parts[0:3]:
        alternatives_heading.insert_before(node.extract())
    for node in p2_parts[3:5]:
        p1_problem.append(node.extract())
    p2_problem_table.decompose()

    pages[0]["aria-label"] = "1p — 개요·문제정의"
    pages[1]["aria-label"] = "2p — Process 재설계"
    p2_process_table["style"] = "width:100%;border-collapse:collapse"
    p2_process = content_cell(p2_process_table)
    p2_process_parts = direct_tags(p2_process)
    set_heading(
        soup,
        p2_process_parts[0],
        1,
        "대체 범위 — 접수부터 이력 등록까지 여섯 단계를 한 흐름으로 바꾼다",
    )
    set_heading(
        soup,
        p2_process_parts[2],
        2,
        "조치 권한 — 위험도에 따라 알림, 권고, 승인 실행, 자동조치로 나눈다",
    )
    set_heading(
        soup,
        p2_process_parts[4],
        3,
        "업무 흐름 — Chat 질문과 무인 감지가 같은 조사 절차를 사용한다",
    )
    set_heading(
        soup,
        p2_process_parts[6],
        4,
        "확산 방식 — 코어는 유지하고 공정별 조사규칙과 색인만 추가한다",
    )

    # Pages 3-4: contain all four required Tech elements. Page 5 becomes BIZ only.
    p3_tech = content_cell(direct_tables(pages[2])[0], 1)
    p4_tech = content_cell(direct_tables(pages[3])[0])
    p4_parts = direct_tags(p4_tech)
    p5_tech_table, p5_biz_table = direct_tables(pages[4])
    p5_tech = content_cell(p5_tech_table)
    p5_parts = direct_tags(p5_tech)

    verifier = [node.extract() for node in p5_parts[0:3]]
    rag_heading = p5_parts[3].extract()
    rag_block = p5_parts[4].extract()
    metrics = [node.extract() for node in p5_parts[5:8]]
    rewrite_learning_block(soup, rag_block)

    set_heading(
        soup,
        verifier[0],
        5,
        "성능 관리 — 판단서는 다섯 가지 검증을 모두 통과해야 한다",
    )
    set_heading(
        soup,
        metrics[0],
        6,
        "성능 지표 — 실측값과 회귀 기준만 적는다",
    )
    for node in verifier + metrics:
        p3_tech.append(node)

    # Keep the evidence output and ablation; replace the long trace with the improvement process.
    action = [node.extract() for node in p4_parts[3:5]]
    ablation = [node.extract() for node in p4_parts[5:8]]
    p4_tech.clear()
    set_heading(
        soup,
        rag_heading,
        7,
        "개선 과정 — 검색 범위를 좁히고, 확정 이력으로 검색과 판단을 보정한다",
    )
    p4_tech.extend([rag_heading, rag_block])
    set_heading(
        soup,
        action[0],
        8,
        "조치안에는 변경량, 한도, 예상 부작용을 함께 적는다",
    )
    p4_tech.extend(action)
    set_heading(
        soup,
        ablation[0],
        9,
        "도구를 추가할 때 판단 근거가 어떻게 보강되는지 확인했다",
    )
    p4_tech.extend(ablation)

    p5_tech_table.decompose()
    pages[2]["aria-label"] = "3p — Tech 당위성·알고리즘·성능"
    pages[3]["aria-label"] = "4p — Tech 개선 과정·검증"
    pages[4]["aria-label"] = "5p — 경영효과"
    p5_biz_table["style"] = "width:100%;border-collapse:collapse"
    add_biz_labels(soup, content_cell(p5_biz_table, 1))

    replacements = {
        "새벽 이상 1건의 실제 동선 — 검출은 2초, 그러나 원인을 아는 사람이 없었다":
            "야간 이상 1건의 처리 과정 — 검출 뒤 원인 확인과 조치 결정에 시간이 걸렸다",
        "숫자는 정상처럼 보이지만 원인은 그대로 남는다 — ":
            "수치는 정상 범위로 돌아오지만 원인은 남는다. ",
        "같은 불량이 재발·확산된 뒤에야 주간에 드러난다. 이것이 매번 반복되는 사고의 전형이다.":
            "같은 불량이 다시 발생한 뒤에야 주간 근무에서 원인을 확인한다.",
        "특별한 사고가 아니라 매일의 기본 동선": "일반적인 이상 판정에서도 반복되는 과정",
        "조사 공수가 크다": "조사에 시간이 많이 든다",
        "판단이 상향 평준화되지 않는다": "판단 기준이 사람마다 다르다",
        "취약시간에 사고가 난다": "야간·주말 대응이 늦어진다",
        "기록 없이 각자 알아서 변경한다": "판단 근거가 기록으로 남지 않는다",
        "만 명 규모 제조 조직의 품질·공정 엔지니어 전원의 매일 업무":
            "품질·공정 엔지니어 약 1,000명이 반복해서 수행하는 업무",
        "사람이 시간을 더 쓰는 이유가 게으름이 아니라 비용 구조":
            "판정을 서두르면 불량 유출과 불필요한 Hold 중 한쪽의 비용이 커진다. 그래서 확인에 시간이 걸린다",
        "지금 시작": "착수 가능",
        "다섯 정거장이 통째로 내려온다 — 자율 tool calling, 합산 수 초":
            "다섯 분석 단계를 같은 코어에서 처리한다 — 자율 tool calling, 합산 수 초",
        "다섯 단계가 통째로 내려온다 — 자율 tool calling, 합산 수 초":
            "다섯 분석 단계를 같은 코어에서 처리한다 — 자율 tool calling, 합산 수 초",
        "시작 — 사람이 아니다": "입력 — Chat 질문 또는 무인 감지",
        "중간 — 코어 하나": "처리 — 공통 조사 코어",
        "끝 — 자산이 된다": "결과 — 확정 이력 등록",
        "끝이 다음 시작을 키운다": "확정 이력을 다음 조사에 다시 사용한다",
        "노하우가 등록될수록 시스템이 그 팀에 맞게 자란다.":
            "확정된 사례는 다음 조사에서 검색 근거로 사용한다.",
        "표준안으로 자원 증설 없이 이관": "확산 표준안으로 타 조직에 이관",
        "품질 AI Agent Orchestration — 전체 동작 한 장":
            "품질 AI Agent Orchestration — 전체 동작 구조",
        "감지·질문에서 조치 실행·이력 등록·재학습까지, 한 코어로 닫힌다":
            "감지와 질문부터 조치 실행, 이력 등록, 재학습까지 하나의 흐름으로 연결한다",
        "왜 Agent Orchestration 인가 — 규칙·분류기·단일 LLM이 각각 실패하는 지점":
            "AI Agent가 필요한 이유 — 고정 규칙과 단일 모델만으로 처리하기 어려운 업무",
        "조사 순서를 미리 못 정한다": "조사 순서를 사전에 고정하기 어렵다",
        "고정 파이프라인은 분기가 폭발한다.": "고정 절차로 만들면 예외 분기가 지나치게 많아진다.",
        "이종 모달이 한 사안에 섞인다": "한 건의 판단에 여러 형태의 데이터가 필요하다",
        "정답이 라벨이 아니라 근거 있는 설명이다": "판정에는 결과뿐 아니라 근거가 필요하다",
        "임계 기반으로는 안 걸린다": "고정 임계값만으로는 잡기 어렵다",
        "무엇이 새로운가 — 이 설계의 기술적 신규성 셋": "설계의 차별점 — 실제 운영을 위한 세 가지 기준",
        "채택 조건이 \"그럴듯함\"이 아니라": "채택 조건은 문장의 자연스러움이 아니라",
        "침묵 실패가 구조적으로 없다": "반복 실패를 숨기지 않고 사람 검토로 넘긴다",
        "업무가 곧 라벨링인 폐루프": "승인 이력을 학습 데이터로 활용",
        "승인·수정·반려가 그대로 학습 라벨 — 별도 라벨링 조직 없이 SFT·선호학습(DPO/KTO)으로":
            "승인·수정·반려 이력을 검색기 파인튜닝과 선호학습에 사용한다",
        "승인·수정·반려가 그대로 학습 라벨 — 별도 라벨링 조직 없이 SFT·선호학습(DPO·KTO)·검색기 파인튜닝이 월 4회 돈다.":
            "승인·수정·반려 이력을 검색기 파인튜닝과 선호학습에 월 4회 반영한다.",
        "검색기 파인튜닝 · SFT · DPO/KTO 월 4회, 골든셋 회귀 통과분만 배포":
            "검색기 파인튜닝 · 선호학습 월 4회, 골든셋 회귀 통과분만 배포",
        "쓸수록 정확해진다": "확정 이력으로 검색과 판단 기준을 갱신한다",
        "전문 모델의 밑단 — 이미지·Trend 두 갈래 모두 자체 개발로 이미 돌고 있다":
            "전문 모델 선택 근거 — 이미지와 Trend 모델은 선행 프로토타입에서 검증했다",
        "라벨 없이 배우는 대비학습": "라벨이 부족한 불량 이미지를 위한 대비학습",
        "라벨 없이 배우는 대조 학습": "라벨이 부족한 불량 이미지를 위한 대비학습",
        "무라벨 SEM·Failbit 이미지 쌍": "라벨이 없는 SEM·Failbit 이미지 쌍",
        "근거 사슬이 실물에 닿는다": "근거가 원본 데이터와 문서까지 이어진다",
        "Agent를 하나씩 열어줄 때마다 답이 자란다 — 프롬프트에 무엇이 들어가 답이 어떻게 달라지나":
            "도구를 하나씩 추가하며 판단 근거가 어떻게 보강되는지 비교했다",
        "그럴듯한 오답은 코드가 거른다 — 다섯 관문": "근거가 부족한 판단은 다섯 단계에서 차단한다",
        "관문을 지날수록 통로가 좁아진다 — ": "다섯 항목을 모두 통과한 판단서만 채택한다. ",
        "침묵 실패가 없다.": "반복 실패는 사람 검토로 넘긴다.",
        "사고 원장 RDB — 무조건 1번": "사고 원장 RDB — 우선 조회",
        "담당 엔지니어가 손으로 쓴 원장 — 규모·피해·원인·대책·잘못된 점까지. 신뢰 최상":
            "담당 엔지니어가 직접 작성한 원장이다. 규모·피해·원인·대책과 판단 오류까지 남아 있다.",
        "질의 재작성 후 ③으로 루프": "질의를 고쳐 ③부터 다시 검색",
        "이후 모든 검색의 필터 키": "이후 검색 범위를 정하는 키",
        "유사도는 후보만 — 확정은 언제나 키 조회.":
            "유사도는 후보를 좁힐 때만 사용하고, 최종 사고는 키 조회로 확정한다.",
        "Router에 tool 반환이 계속 쌓이고": "Router에는 도구 반환값이 순서대로 쌓인다",
        "더 부를 도구가 없을 때 Q/A LLM이 답을 닫는다.": "추가 조회가 필요 없을 때 판단서를 작성한다.",
        "지표는 실측으로만 — 임의의 %를 지금 적지 않는다":
            "성능 지표는 실측값만 사용한다 — 아직 측정하지 않은 비율은 적지 않는다",
        "0건으로 관리한다": "운영 중 반드시 0건으로 관리할 항목",
        "연봉 8,000만 = 사내 산정 기준값": "연봉 8,000만 원은 사내 산정 기준값이다",
        "민감도 — 실측이 낮으면 같은 비율로 하향. 절감이 반이어도 ROI 14배.":
            "실제 절감 시간이 목표보다 작으면 기대효과도 같은 비율로 낮춰 계산한다. 하루 30분만 줄어도 연간 ROI는 14.4배다.",
        "백지 출발이 아니다": "설계와 평가 체계를 이미 갖췄다",
        "보는 화면만 늘어난다": "화면을 추가해도 시스템 간 대조와 판단, 조치는 사람의 업무로 남는다",
    }
    replace_text(soup, replacements)

    # Exact correction for the shared RAG alternative; this is a fact-sensitive sentence.
    for td in soup.find_all("td"):
        if "문서를 통짜 벡터로 넣는 구조" in td.get_text(" ", strip=True):
            td.clear()
            td.string = (
                "문서 적재는 가능하지만 검색 설정은 기본값에 가깝다. 반도체 사전 등록, "
                "용어 병기, 메타 필터를 적용할 수 없어 설비·recipe·공정 조건을 정확히 좁히기 어렵다"
            )

    # Replace the prototype card beside recall with a deployment-gate statement.
    metrics_row = metrics[1]
    cards = direct_tags(metrics_row)
    if len(cards) >= 3:
        cards[2].clear()
        title = soup.new_tag("div")
        title["style"] = "font-size:7.5px;font-weight:700;color:#0E9C97"
        title.string = "배포 기준"
        body = soup.new_tag("div")
        body["style"] = "font-size:8px;color:#3E4C64;line-height:1.5;margin-top:1px"
        body.string = (
            "판정 일치율·처리 시간·반려율은 그림자 운영에서 기준선을 잡는다. "
            "변경 뒤 기준선보다 낮아지면 배포하지 않는다."
        )
        cards[2].extend([title, body])

    return soup


def visible_text(soup: BeautifulSoup) -> str:
    clone = BeautifulSoup(str(soup), "html.parser")
    for node in clone(["style", "script"]):
        node.decompose()
    return " ".join(clone.get_text(" ", strip=True).split())


def lint(text: str) -> list[str]:
    forbidden = [
        "답이 자란다", "한 코어로 닫힌다", "실물에 닿는다", "통째로 내려온다",
        "끝이 다음 시작을 키운다", "침묵 실패", "쓸수록 정확해진다", "SFT", "DPO", "KTO",
        "GPU", " VM ", "스토리지", "인프라",
    ]
    return [token for token in forbidden if token in text]


def main() -> None:
    soup = revise()
    text = visible_text(soup)
    problems = lint(text)
    if problems:
        raise SystemExit(f"문체/금지어 검사 실패: {problems}")
    OUTPUT.write_text(str(soup), encoding="utf-8")
    print(f"OK {OUTPUT.resolve()}")
    print(f"visible chars={len(text)} pages={len(soup.select('section.page'))}")


if __name__ == "__main__":
    main()
