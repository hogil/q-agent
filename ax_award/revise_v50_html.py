#!/usr/bin/env python
"""Create the next versioned HTML source without overwriting the approved visual source."""

from __future__ import annotations

import re
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString, Tag


HERE = Path(__file__).parent
SOURCE = HERE / "html" / "ax_dc_v3.html"
OUTPUT = HERE / "html" / "AX_Award_지원서_v53.html"


def direct_tags(parent: Tag) -> list[Tag]:
    return [node for node in parent.children if isinstance(node, Tag)]


def direct_tables(page: Tag) -> list[Tag]:
    container = page.select_one(":scope > .fit") or page
    return [
        node for node in container.children
        if isinstance(node, Tag) and node.name == "table"
    ]


def content_cell(table: Tag, row_index: int = 0) -> Tag:
    row = table.select(":scope > tbody > tr")[row_index]
    return row.find_all("td", recursive=False)[-1]


def set_heading(soup: BeautifulSoup, node: Tag, number: int | str, title: str) -> None:
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
        soup, 1, "유형효과", 0
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
    roadmap = parts[4]
    achievements.decompose()
    roadmap.insert_before(make_heading(soup, 3, "향후 확산 효과", 8))
    roadmap.insert_after(make_expansion_flow(soup))

    for node in direct_tags(biz_cell):
        style = node.get("style", "")
        if "margin-bottom" in style:
            style = re.sub(r"margin-bottom:\s*\d+(?:\.\d+)?px", "margin-bottom:10px", style)
        node["style"] = style


def make_statement(soup: BeautifulSoup, text: str) -> Tag:
    node = soup.new_tag("div")
    node["style"] = (
        "background:#E6F7F6;border-left:3px solid #12B5B0;border-radius:4px;"
        "padding:5px 9px;font-size:8.5px;color:#0F1E3D;line-height:1.55"
    )
    node.string = text
    return node


def make_comparison(soup: BeautifulSoup) -> Tag:
    node = soup.new_tag("div")
    node["style"] = "display:flex;gap:6px;margin-bottom:6px"
    data = [
        ("개선 전", "조사, 판정, 보고 등 5개 단계를 사람이 수행하며 약 14시간이 걸린다.", "#F2F5FA"),
        ("개선 후", "사건 카드 생성부터 판정서와 조치안 작성까지 Q-Agent가 처리한다.", "#E6F7F6"),
        ("확정", "담당자가 승인, 수정 또는 반려하고 확정 이력을 등록한다.", "#F2F5FA"),
    ]
    for title_text, body_text, color in data:
        card = soup.new_tag("div")
        card["style"] = f"flex:1;background:{color};border-radius:4px;padding:4px 7px"
        title = soup.new_tag("div")
        title["style"] = "font-size:8px;font-weight:900;color:#0F1E3D"
        title.string = title_text
        body = soup.new_tag("div")
        body["style"] = "font-size:7.3px;color:#3E4C64;line-height:1.45;margin-top:1px"
        body.string = body_text
        card.extend([title, body])
        node.append(card)
    return node


def make_algorithm_grid(soup: BeautifulSoup) -> Tag:
    grid = soup.new_tag("div")
    grid["style"] = "display:grid;grid-template-columns:1fr 1fr;gap:5px;margin-bottom:6px"
    data = [
        ("시계열", "2단 이상감지와 변화점 검정", "고정 임계값이 놓치는 완만한 drift를 찾고 유형을 분리한다."),
        ("이미지", "ConvNeXt V2, 대비학습, PatchCore", "라벨이 부족한 불량과 학습되지 않은 패턴을 함께 처리한다."),
        ("문서 검색", "메타 필터, BM25/임베딩, 리랭커", "설비와 recipe 조건을 먼저 좁힌 뒤 원문 근거를 찾는다."),
        ("통합 판정", "Router tool calling과 Q/A LLM", "직전 반환값에 따라 다음 조회를 정하고 여러 근거를 판정서로 종합한다."),
    ]
    for domain, method, reason in data:
        card = soup.new_tag("div")
        card["style"] = "border:1px solid #D7DEEA;border-radius:5px;padding:4px 7px"
        head = soup.new_tag("div")
        head["style"] = "font-size:7.4px;font-weight:700;color:#0E9C97"
        head.string = domain
        name = soup.new_tag("div")
        name["style"] = "font-size:8.4px;font-weight:900;color:#0F1E3D;margin-top:1px"
        name.string = method
        body = soup.new_tag("div")
        body["style"] = "font-size:7.2px;color:#5A6B84;line-height:1.45;margin-top:1px"
        body.string = reason
        card.extend([head, name, body])
        grid.append(card)
    return grid


def make_metrics_block(soup: BeautifulSoup) -> Tag:
    row = soup.new_tag("div")
    row["style"] = "display:flex;gap:5px;margin-bottom:4px"
    data = [
        ("이미지 군집", "오적재 6.20% → 0.52%", "ARI 0.823 → 0.860"),
        ("검색 회귀", "Recall@10 0.500", "골든 4건, 색인 50건"),
        ("선행 검색 평가", "26질의 hit@1 1.000", "Hard set 38질의 0.957, AMI 0.956"),
    ]
    for title_text, metric, note in data:
        card = soup.new_tag("div")
        card["style"] = "flex:1;background:#F2F5FA;border-radius:5px;padding:4px 7px"
        title = soup.new_tag("div")
        title["style"] = "font-size:7.2px;font-weight:700;color:#0E9C97"
        title.string = title_text
        value = soup.new_tag("div")
        value["style"] = "font-size:10px;font-weight:900;color:#0F1E3D;line-height:1.25;margin-top:1px"
        value.string = metric
        detail = soup.new_tag("div")
        detail["style"] = "font-size:7px;color:#5A6B84;line-height:1.4;margin-top:1px"
        detail.string = note
        card.extend([title, value, detail])
        row.append(card)
    return row


def make_improvement_block(soup: BeautifulSoup) -> Tag:
    block = soup.new_tag("div")
    block["style"] = "border:1px solid #D7DEEA;border-radius:6px;overflow:hidden;margin-bottom:6px"

    image_track = soup.new_tag("div")
    image_track["style"] = "background:#0F1E3D;padding:5px 7px;display:flex;align-items:center;gap:5px"
    track_title = soup.new_tag("div")
    track_title["style"] = "flex:none;width:70px;font-size:7.4px;font-weight:900;color:#FFFFFF"
    track_title.string = "이미지 개선 단계"
    image_track.append(track_title)
    stages = [
        ("01", "Global", "전체 표현"),
        ("02", "Local", "부분 패턴"),
        ("03", "Queue", "오분류 샘플"),
        ("04", "위음성 필터", "오적재 제거"),
    ]
    for index, (number, name, note) in enumerate(stages):
        if index:
            arrow = soup.new_tag("span")
            arrow["style"] = "flex:none;color:#7FD1CE;font-size:10px;font-weight:900"
            arrow.string = "→"
            image_track.append(arrow)
        step = soup.new_tag("div")
        step["style"] = "flex:1;min-width:0;display:flex;align-items:center;gap:4px"
        badge = soup.new_tag("span")
        badge["style"] = (
            "flex:none;width:17px;height:17px;border-radius:50%;background:#12B5B0;color:#FFFFFF;"
            "font-size:6.5px;font-weight:900;display:flex;align-items:center;justify-content:center"
        )
        badge.string = number
        copy = soup.new_tag("span")
        copy["style"] = "font-size:7px;color:#C6D2E6;line-height:1.25"
        strong = soup.new_tag("b")
        strong["style"] = "color:#FFFFFF"
        strong.string = name
        copy.append(strong)
        copy.append(soup.new_tag("br"))
        copy.append(NavigableString(note))
        step.extend([badge, copy])
        image_track.append(step)
    block.append(image_track)

    lanes = soup.new_tag("div")
    lanes["style"] = "display:grid;grid-template-columns:1fr 1fr 1fr;gap:5px;padding:5px 7px"
    data = [
        ("Trend", "합성 이상 추가", "복귀형 파형은 정상 데이터로 보완"),
        ("검색", "메타 필터, 하이브리드, 리랭커", "확정 판정-문서 쌍으로 검색기 조정"),
        ("Agent", "승인, 수정, 반려 이력 반영", "도구 추가 전후 비교 평가"),
    ]
    for label_text, title_text, body_text in data:
        lane = soup.new_tag("div")
        lane["style"] = "border-left:3px solid #12B5B0;background:#F2F5FA;border-radius:3px;padding:4px 6px"
        label = soup.new_tag("div")
        label["style"] = "font-size:6.8px;font-weight:700;color:#0E9C97"
        label.string = label_text
        title = soup.new_tag("div")
        title["style"] = "font-size:7.5px;font-weight:900;color:#0F1E3D;margin-top:1px"
        title.string = title_text
        body = soup.new_tag("div")
        body["style"] = "font-size:6.8px;color:#5A6B84;line-height:1.35;margin-top:1px"
        body.string = body_text
        lane.extend([label, title, body])
        lanes.append(lane)
    block.append(lanes)
    return block


def make_release_gate(soup: BeautifulSoup) -> Tag:
    node = soup.new_tag("div")
    node["style"] = "display:flex;align-items:stretch;gap:0;margin-top:5px"
    data = [
        ("실측", "Shadow 운영", "#0F1E3D", "#FFFFFF"),
        ("비교", "기존 기준선", "#F2F5FA", "#0F1E3D"),
        ("판정", "4개 지표 확인", "#E6F7F6", "#0F1E3D"),
        ("결과", "충족 시 배포, 미달 시 보류", "#0F1E3D", "#FFFFFF"),
    ]
    for index, (kicker, body_text, bg, fg) in enumerate(data):
        if index:
            arrow = soup.new_tag("div")
            arrow["style"] = "flex:none;width:22px;display:flex;align-items:center;justify-content:center;color:#12B5B0;font-weight:900"
            arrow.string = "→"
            node.append(arrow)
        step = soup.new_tag("div")
        step["style"] = f"flex:1;background:{bg};border:1px solid #D7DEEA;border-radius:4px;padding:4px 7px"
        top = soup.new_tag("div")
        top["style"] = "font-size:6.7px;font-weight:700;color:#0E9C97"
        top.string = kicker
        body = soup.new_tag("div")
        body["style"] = f"font-size:7.5px;font-weight:900;color:{fg};margin-top:1px"
        body.string = body_text
        step.extend([top, body])
        node.append(step)
    return node


def make_expansion_flow(soup: BeautifulSoup) -> Tag:
    node = soup.new_tag("div")
    node["style"] = "display:flex;align-items:stretch;gap:0;margin-top:6px"
    data = [
        ("1차년", "포토 1개 공정", "초기 검증"),
        ("2차년", "etch, CMP 포함 3개 공정", "조사규칙과 색인 추가"),
        ("확산", "약 1,000명", "품질, 공정 엔지니어"),
        ("이관", "타 조직 적용", "확산 표준안 사용"),
    ]
    for index, (kicker, title_text, note) in enumerate(data):
        if index:
            arrow = soup.new_tag("div")
            arrow["style"] = "flex:none;width:20px;display:flex;align-items:center;justify-content:center;color:#12B5B0;font-weight:900"
            arrow.string = "→"
            node.append(arrow)
        stage = soup.new_tag("div")
        stage["style"] = "flex:1;border-top:3px solid #12B5B0;background:#F2F5FA;border-radius:4px;padding:5px 7px"
        top = soup.new_tag("div")
        top["style"] = "font-size:6.8px;font-weight:700;color:#0E9C97"
        top.string = kicker
        title = soup.new_tag("div")
        title["style"] = "font-size:8px;font-weight:900;color:#0F1E3D;margin-top:1px"
        title.string = title_text
        body = soup.new_tag("div")
        body["style"] = "font-size:6.8px;color:#5A6B84;line-height:1.35;margin-top:1px"
        body.string = note
        stage.extend([top, title, body])
        node.append(stage)
    return node


def revise() -> BeautifulSoup:
    soup = BeautifulSoup(SOURCE.read_text(encoding="utf-8"), "html.parser")
    for node in soup.find_all(src=True):
        value = node["src"]
        if value.startswith("./"):
            node["src"] = f"design_export_6/{value[2:]}"
        elif value.startswith("_ds/"):
            node["src"] = f"design_export_6/{value}"
    for node in soup.find_all(href=True):
        value = node["href"]
        if value.startswith("_ds/"):
            node["href"] = f"design_export_6/{value}"
    pages = soup.select("section.page")
    if len(pages) != 5:
        raise RuntimeError(f"expected 5 pages, found {len(pages)}")

    # Page 1: problem definition in the evaluator's requested order.
    p1_problem = content_cell(direct_tables(pages[0])[1], 1)
    p1_parts = [node.extract() for node in direct_tags(p1_problem)]
    p2_problem_table, p2_process_table = direct_tables(pages[1])
    p2_problem = content_cell(p2_problem_table)
    p2_problem_parts = [node.extract() for node in direct_tags(p2_problem)]
    set_heading(soup, p1_parts[0], 1, "해결하고자 하는 현업 문제")
    set_heading(soup, p1_parts[3], 3, "병목 구간과 현업 문제")
    set_heading(soup, p2_problem_parts[0], 4, "현업 중요도와 개선 필요성")
    problem_statement = make_statement(
        soup,
        "현재 이상감지는 발생 사실만 알린다. 원인 판정에는 Trend 이력, 직전 변경점, "
        "과거 유사 사고를 함께 확인해야 한다. 야간에는 이를 대조할 담당자가 없어 조사와 조치 결정이 다음 근무로 넘어간다.",
    )
    p1_problem.extend([
        p1_parts[0],
        problem_statement,
        make_heading(soup, 2, "현재 E2E 업무 Process", 6),
        p1_parts[2],
        p1_parts[3],
        p1_parts[4],
        p2_problem_parts[0],
        p2_problem_parts[1],
        p2_problem_parts[2],
        make_heading(soup, 5, "실제 사례: 6월 28일 PHOD03 CD 이상", 6),
        p1_parts[1],
    ])
    p2_problem_table.decompose()

    pages[0]["aria-label"] = "1p — 개요·문제정의"
    pages[1]["aria-label"] = "2p — Process 재설계"
    p2_process_table["style"] = "width:100%;border-collapse:collapse"
    p2_process = content_cell(p2_process_table)
    p2_process_parts = [node.extract() for node in direct_tags(p2_process)]
    set_heading(soup, p2_process_parts[0], 1, "기존 E2E Process와 수작업 병목")
    set_heading(soup, p2_process_parts[4], 2, "AI Agent가 대체하는 반복 수작업 구간")
    set_heading(soup, p2_process_parts[2], 4, "사람 승인과 자동화 범위")
    set_heading(soup, p2_process_parts[6], 5, "타 공정 확산 방법")
    p2_process.extend([
        p2_process_parts[0],
        p2_process_parts[1],
        p2_process_parts[4],
        p2_process_parts[5],
        make_heading(soup, 3, "개선 전후 Process 비교", 7),
        make_comparison(soup),
        p2_process_parts[2],
        p2_process_parts[3],
        p2_process_parts[6],
        p2_process_parts[7],
        p2_process_parts[8],
    ])

    # Pages 3-4: Tech content ordered exactly as the assessment criteria.
    p3_tech = content_cell(direct_tables(pages[2])[0], 1)
    p3_parts = [node.extract() for node in direct_tags(p3_tech)]
    p4_tech = content_cell(direct_tables(pages[3])[0])
    p4_parts = [node.extract() for node in direct_tags(p4_tech)]
    p5_tech_table, p5_biz_table = direct_tables(pages[4])
    p5_tech = content_cell(p5_tech_table)
    p5_parts = [node.extract() for node in direct_tags(p5_tech)]

    set_heading(soup, p3_parts[1], 1, "왜 기존 자동화가 아니라 AI Agent인가")
    set_heading(soup, p3_parts[7], 2, "문제별 알고리즘 선택 근거")
    set_heading(soup, p5_parts[5], 3, "알고리즘별 성능 검증 결과")
    p3_tech.extend([
        p3_parts[1],
        p3_parts[2],
        make_heading(soup, "1-1", "기존 자동화 방식의 한계", 6),
        p1_parts[6],
        p3_parts[7],
        make_algorithm_grid(soup),
        p5_parts[5],
        make_metrics_block(soup),
        p5_parts[7],
        make_heading(soup, 4, "성능 개선 과정", 7),
        make_improvement_block(soup),
        make_release_gate(soup),
    ])

    architecture = p3_parts[0]
    action = p4_parts[3:5]
    ablation = p4_parts[5:8]
    verifier = p5_parts[0:3]
    p4_tech.clear()
    set_heading(soup, action[0], 6, "대표 실행 사례: 여러 데이터의 근거를 종합한 판정서")
    set_heading(soup, ablation[0], "6-1", "도구별 근거가 판정서에 반영되는 과정")
    set_heading(soup, verifier[0], 7, "검증과 안전 장치")
    p4_tech.extend([
        make_heading(soup, 5, "Agent Architecture", 0),
        architecture,
        action[0],
        action[1],
        ablation[0],
        ablation[1],
        ablation[2],
        verifier[0],
        verifier[1],
        verifier[2],
    ])

    p5_tech_table.decompose()
    pages[2]["aria-label"] = "3p — Tech 필요성·알고리즘·성능·개선"
    pages[3]["aria-label"] = "4p — Tech 구조·실행 사례·검증"
    pages[4]["aria-label"] = "5p — 경영효과"
    p5_biz_table["style"] = "width:100%;border-collapse:collapse"
    add_biz_labels(soup, content_cell(p5_biz_table, 1))

    replacements = {
        "완전한 품질 AI Agent Orchestration 구축":
            "품질 조사, 판정, 조치 전 과정을 연결하는 AI Agent Orchestration 구축",
        "감지부터 판단·조치·자동조치까지 스스로 수행하는 살아있는 품질 관리 시스템":
            "감지부터 원인 조사, 판정, 조치안 생성, 이력 등록까지 자동 연계하고, 단계적으로 자동조치까지 확대하는 품질 관리 시스템",
        "IIII. 경영효과": "IV. 경영효과",
        "미승인 L2 조치 실행": "미승인 L4 조치 실행",
        "2Q 그림자 운영": "3Q Shadow 운영(병행 검증)",
        "3Q 그림자": "3Q Shadow 운영(병행 검증)",
        "새벽 이상 1건의 실제 동선 — 검출은 2초, 그러나 원인을 아는 사람이 없었다":
            "야간 이상 1건의 처리 과정 — 검출 뒤 원인 확인과 조치 결정에 시간이 걸렸다",
        "새벽 이상 1건의 실제 동선": "야간 이상 발생 1건의 실제 처리 흐름",
        "검출은 2초, 그러나 원인을 아는 사람이 없었다":
            "이상은 2초 내 검출되지만 야간에는 원인 조사에 필요한 정보와 경험자가 부족하다",
        "trend만 원위치": "Trend만 정상 범위로 복귀",
        "이 판정 하나에 필요한 지식은 셋이다": "판정에는 다음 3가지 정보가 필요하다",
        "이 item의 trend 이력": "해당 항목의 Trend 이력",
        "숫자는 정상처럼 보이지만 원인은 그대로 남는다 — ":
            "수치는 정상 범위로 돌아오지만 원인은 남는다. ",
        "같은 불량이 재발·확산된 뒤에야 주간에 드러난다. 이것이 매번 반복되는 사고의 전형이다.":
            "같은 불량이 다시 발생한 뒤에야 주간 근무에서 원인을 확인한다.",
        "이것이 매번 반복되는 사고의 전형이다.":
            "이러한 임시 대응이 동일 유형 사고의 재발 원인이 된다.",
        "특별한 사고가 아니라 매일의 기본 동선": "일반적인 이상 판정에서도 반복되는 과정",
        "동선 안에 반복되는 구조 결함 4 — 측정 가능한 문제로 적는다":
            "현행 처리 과정의 구조적 문제 4가지",
        "조사 공수가 크다": "조사에 시간이 많이 든다",
        "판단이 상향 평준화되지 않는다": "판단 기준이 사람마다 다르다",
        "취약시간에 사고가 난다": "야간·주말 대응이 늦어진다",
        "기록 없이 각자 알아서 변경한다": "판단 근거가 기록으로 남지 않는다",
        "기준이 시스템이 아니라 사람 머릿속에 있다": "판정 기준이 시스템화되지 않고 개인 경험에 의존한다",
        "기존 대안 검토 — 셋은 기각, 하나는 트리거로 편입": "기존 자동화 방식의 적용 한계",
        "대조를 할 손이 없다": "대조 기능이 없다",
        "물어보는 사람의 지식만큼만 나온다":
            "질문자가 제공한 정보 범위를 넘어 현장 근거를 자동 확보하지 못한다",
        "문서를 통짜 벡터로 넣는 구조": "문서를 단일 벡터 중심으로 검색하는 구조",
        "임베딩에서 뭉개져": "임베딩만으로는 식별력이 낮아",
        "meta 필터 같은 손잡이가 없다": "메타데이터 필터 등 검색 제어 수단이 없다",
        "메타 필터 같은 손잡이가 없다": "메타데이터 필터 등 검색 제어 수단이 없다",
        "spec·rule 기반": "규격과 규칙 기반",
        "기각": "단독 적용 어려움",
        "편입": "활용",
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
        "SFT·선호학습(DPO·KTO)·검색기 파인튜닝이 월 4회":
            "지시 데이터 기반 조정, 선호학습, 검색기 파인튜닝을 월 4회 수행한다",
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
        "코드 관문 통과": "코드 검증 통과",
        "침묵 실패가 없다.": "반복 실패는 사람 검토로 넘긴다.",
        "침묵 실패가 없다 — 모르는 것은 모른다고 적는 것까지가 관문이다.":
            "근거가 부족하면 판단 불가를 명시하고 사람 검토로 넘긴다.",
        "사고 원장 RDB — 무조건 1번": "사고 원장 RDB — 우선 조회",
        "담당 엔지니어가 손으로 쓴 원장 — 규모·피해·원인·대책·잘못된 점까지. 신뢰 최상":
            "담당 엔지니어가 직접 작성한 원장이다. 규모·피해·원인·대책과 판단 오류까지 남아 있다.",
        "질의 재작성 후 ③으로 루프": "질의를 고쳐 ③부터 다시 검색",
        "이후 모든 검색의 필터 키": "이후 검색 범위를 정하는 키",
        "유사도는 후보만 — 확정은 언제나 키 조회.":
            "유사도는 후보를 좁힐 때만 사용하고, 최종 사고는 키 조회로 확정한다.",
        "Router에 tool 반환이 계속 쌓이고": "Router에는 도구 반환값이 순서대로 쌓인다",
        "더 부를 도구가 없을 때 Q/A LLM이 답을 닫는다.": "추가 조회가 필요 없을 때 판단서를 작성한다.",
        "Q/A LLM 이 최종 판정서를 생성한다": "Q/A LLM이 최종 판정서를 생성한다",
        "이 파이프는 세 갈래로 배운다": "모델 개선 경로는 3가지다",
        "현장 용어를 배운다": "현장 용어에 대한 검색 순위를 개선한다",
        "스스로 '판단 불가'를 고른다": "근거 기준 미달 시 판단 불가를 출력하도록 학습한다",
        "지식을 '검색'에서 '읽고 걷는' 구조로": "키워드 검색에서 연결 관계 탐색까지 확장",
        "살아있는 지식 베이스": "자동 갱신형 지식 베이스",
        "벡터 검색이 못 잇는 관계를 걷는다": "벡터 검색으로 찾기 어려운 다단 관계를 그래프 탐색으로 조회한다",
        "지표는 실측으로만 — 임의의 %를 지금 적지 않는다":
            "성능 지표는 실측값만 사용한다 — 아직 측정하지 않은 비율은 적지 않는다",
        "0건으로 관리한다": "운영 중 반드시 0건으로 관리할 항목",
        "연봉 8,000만 = 사내 산정 기준값": "연봉 8,000만 원은 사내 산정 기준값이다",
        "민감도 — 실측이 낮으면 같은 비율로 하향. 절감이 반이어도 ROI 14배.":
            "실제 절감 시간이 목표보다 작으면 기대효과도 같은 비율로 낮춰 계산한다. 하루 30분만 줄어도 연간 ROI는 14.4배다.",
        "백지 출발이 아니다": "설계와 평가 체계를 이미 갖췄다",
        "보는 화면만 늘어난다": "화면을 추가해도 시스템 간 대조와 판단, 조치는 사람의 업무로 남는다",
        "횡전개 범위": "확산 범위",
        "반나절짜리 공수가 매일 반복된다": "판정 한 건에 최대 반나절이 소요된다",
        "다 띄워놓고 손으로 대조한다": "각 시스템에서 조회한 뒤 수동으로 대조한다",
        "trend만 맞추는 임시 대응이 나온다": "Trend 수치만 정상 범위로 되돌리는 임시 대응이 발생한다",
        "담당이 바뀌면 같은 조사를 처음부터": "담당자 변경 시 동일 조사를 반복한다",
        "어느 쪽으로도 못 기운다": "판정 기준을 한쪽으로 단순화하기 어렵다",
        "사람이 시간을 더 쓰는 이유가 게으름이 아니라 비용 구조":
            "판정을 서두르면 불량 유출 또는 불필요한 Hold 비용이 커질 수 있어 확인 시간이 필요하다",
        "시스템도 여기서 똑같이 무너진다": "오탐이 반복되면 알림 사용률이 낮아질 수 있다",
        "알림을 꺼 사장된다": "알림을 사용하지 않게 된다",
        "양쪽 다 크니 판정은 늦고 보수적이 된다.":
            "불량 유출과 불필요한 Hold 비용을 모두 확인해야 하므로 판정 시간이 길어진다.",
        "오탐이 잦으면 현업이 알림을 꺼 시스템이 사장된다":
            "오탐이 반복되면 알림 사용률이 낮아진다",
        "그래서 판정은 늦고 보수적이 된다 — ": "두 비용을 모두 확인해야 하므로 판정 시간이 길어진다. ",
        "사람이 시간을 더 쓰는 이유가 게으름이 아니라 ": "",
        "비용 구조": "추가 확인이 필요하",
        "낮아질 수 있다:": "낮아질 수 있다.",
        "처리 절차 이다": "처리 절차이다",
        "자율 tool calling": "Router 도구 호출",
        "tool calling": "도구 호출",
        "tool 반환": "도구 반환",
        "Tool 추가": "도구 추가",
        "설비 이력 Tool": "설비 이력 도구",
        "무인 기동": "이벤트 기반 자동 실행",
        "이벤트 기반 자동 실행 트리거 로만 쓴다": "이벤트 발생 신호로만 사용한다",
        "트리거 로만 쓴다": "발생 신호로만 사용한다",
        "1차년 즉시 개방 — 통보성 (되돌릴 것 없음)": "1차년 운영 개시 — 통보 기능 우선 적용",
        "공정이 3개로 늘어도 추가 자원을 요청하지 않는다":
            "기존 공통 자원 범위 내 3개 공정 확산을 목표로 한다",
        "현업 몫": "현업 담당 역할",
        "오탐 남발": "과다 알림",
        "8Q 약 1,000명 전면": "8Q 약 1,000명 전면 적용",
        "확정분이 코퍼스·재학습 라벨": "확정 이력을 검색 데이터와 학습 데이터로 저장",
        "확정분이 코퍼스·라벨": "확정 이력을 검색 데이터와 학습 데이터로 저장",
        "승인·등록 확정 이력을 검색 데이터와 학습 데이터로 저장로":
            "승인 후 확정 이력을 검색 데이터와 학습 데이터로 저장",
        "코어 변경 0": "조사 코어 변경 없음",
        "1차년 · 구축·검증": "1차년 구축 및 검증",
        "2차년 · 확산·자동화": "2차년 확산 및 자동화",
        "5·6Q": "5~6Q",
        "각 모달은 전용 모델이 정확하고, 종합은 LLM이 한다.":
            "데이터 유형별 전용 모델로 분석하고 LLM은 반환 결과를 종합한다.",
        "정답이 라벨이 아니라 근거 있는 설명이다":
            "출력은 단순 분류값이 아니라 근거가 포함된 판정서여야 한다",
        "LLM이 숫자를 만들 자리가 없다": "수치와 라벨은 도구 반환값만 사용하도록 제한한다",
        "무엇이 새로운가 — 이 설계의 기술적 신규성 셋": "기술적 차별점 3가지",
        "채택 조건이 \"그럴듯함\"이 아니라 코드 관문 통과 다.":
            "채택 여부는 LLM 출력의 개연성이 아니라 코드 기반 검증 결과로 결정한다.",
        "침묵 실패가 구조적으로 없다": "검증 실패 시 판단 불가 상태를 반환한다",
        "전문 모델의 밑단": "전문 모델 구성",
        "이미지·Trend 두 갈래 모두 자체 개발로 이미 돌고 있다":
            "이미지와 Trend 전문 모델은 자체 개발해 선행 검증 중이다",
        "라벨 한계를 생성 데이터로 돌파": "라벨 부족 문제를 합성 데이터로 보완",
        "여기서는 양·불만 가른다": "1단에서는 정상/이상만 판별한다",
        "게이트 기준을 잠그며": "게이트 임계값을 고정하고",
        "부품 사다리 실측": "구성요소별 ablation 실측",
        "분류기는 Hold/Release만 찍는다.": "분류 모델은 Hold/Release 값만 반환한다.",
        "임계 아래로 완만히 흐르는 shift는 규칙 알람이 못 잡는다.":
            "임계값 이하에서 진행되는 완만한 shift는 규칙 알람으로 찾기 어렵다.",
        "판정 정답률은 그림자 운영 실측 뒤 확정한다. 일치율(AI 대 엔지니어 판정)·recall@10·처리 시간·반려율이 떨어지면 기준 미달 시 배포를 보류한다.":
            "판정 일치율, recall@10, 처리 시간, 반려율은 그림자 운영에서 기준선을 확정한다. 변경 후 어느 지표라도 기준선보다 낮으면 배포를 보류한다.",
        "판정 정답률은 그림자 운영 실측 뒤 확정한다. 일치율(AI 대 엔지니어 판정)·recall@10·처리 시간·반려율이 떨어지면 배포를 막는다.":
            "판정 일치율, Recall@10, 처리 시간, 반려율은 Shadow 운영(병행 검증)에서 기준선을 확정한다. 변경 후 어느 지표라도 기준선보다 낮으면 배포를 보류한다.",
        "그림자 운영 로그": "Shadow 운영 로그",
        "recall@10": "Recall@10",
        "도구별 ablation을 수행했다": "도구 추가 전후 비교 평가를 수행했다",
        "Router 자율 루프": "Router 반복 조회",
        "반복 실패는 판단 불가로 강등": "반복 실패 시 판단 불가로 반환",
        "확정분이 검색 코퍼스 + 학습 라벨 로": "확정 이력을 검색 데이터와 학습 데이터로 저장",
        "검색 코퍼스 + 학습 라벨": "검색 데이터와 학습 데이터",
        "사이드 이펙트": "예상 영향",
        "모니터 lot 2매 선행 확인 후 본류 적용": "모니터 lot 2매를 먼저 확인한 뒤 본 공정에 적용",
        "조치 등급표가 강제한다": "조치 등급표로 제한한다",
        "파라미터 가드(변경량 상한·횟수 제한·되돌림 가능성)를 조치 등급표가 강제한다.":
            "조치 등급표와 파라미터 가드가 변경량, 횟수, 되돌림 가능성을 제한한다.",
        "파라미터 가드(변경량 상한·횟수 제한·되돌림 가능성)를 조치 등급표로 제한한다.":
            "조치 등급표와 파라미터 가드가 변경량, 횟수, 되돌림 가능성을 제한한다.",
        "근거가 원본 데이터와 문서까지 이어진다":
            "모든 근거를 원문 또는 RDB 레코드까지 추적할 수 있다",
        "확정은 메타·경로 키로 RDB에서":
            "최종 확인은 메타데이터와 경로 키를 이용해 RDB에서 수행한다",
        "원장 → meta → 문서": "원장 → 메타데이터 → 문서",
        "답의 수준 차이는 모델이 아니라 스택에 쌓인 증거의 차이다.":
            "판정 결과의 차이는 모델이 아니라 입력 근거의 차이에서 발생한다.",
        "실행 트레이스 두 갈래 — 데이터가 실제로 이렇게 흐른다":
            "대표 실행 시나리오 2개 및 데이터 흐름",
        "역할별 temperature — 같은 엔진, 다른 온도": "역할별 Temperature 설정",
        "서술만 풀어주는 폭": "표현 다양성만 제한적으로 허용한다",
        "온도가 값을 못 흔든다": "수치, ID, 인용문은 도구 반환값을 직접 사용한다",
        "새는 건 검증기 ③ 사실 대조가 잡는다": "생성 오류는 검증기 ③ 사실 대조 단계에서 차단한다",
        "4층 스택": "4개 입력 계층",
        "조치가 곧 명령이 아니다": "생성된 조치안은 즉시 실행 명령으로 사용하지 않는다",
        "\"많이 바꾸는\" 답은 구조적으로 못 나간다": "가드 한도를 초과한 조치안은 실행 단계에서 차단한다",
        "가설이 설비 이력과 맞물립니다": "가설과 실제 설비 이력이 일치합니다",
        "원인 확정": "원인 가능성 높음",
        "도구를 하나 빼면 답이 어느 단계로 후퇴하는지가 그대로 보인다":
            "Ablation을 통해 각 도구의 판정 기여도를 측정한다",
        "답의 수준 차이는 모델이 아니라 ": "판정 품질은 모델뿐 아니라 ",
        "스택에 쌓인 증거의 차이": "입력 근거 구성에 좌우된",
        "반복 실패 시 판단 불가로 강등": "반복 실패 시 판단 불가로 반환",
        "반복 실패는 판단 불가로 강등해 사람에게 넘긴다.":
            "반복 실패 시 판단 불가를 반환하고 사람 검토로 넘긴다.",
        "원인 가능성 높음.": "원인 가능성이 높습니다.",
        "입력 근거 구성에 좌우된": "입력 근거 구성의 영향을 받는",
        "반복 실패 시 판단 불가로 반환해 사람에게 넘긴다.":
            "반복 실패 시 판단 불가를 반환하고 사람 검토로 넘긴다.",
        "판단 불가로 강등해 사람에게 넘긴다.":
            "판단 불가를 반환하고 사람 검토로 넘긴다.",
        "trend만 스펙 안으로": "Trend 수치만 규격 범위로",
        "야간 알람은 \"이상이다\"에서 멈춘다": "야간 알람은 이상 발생만 통보한다",
        "야간·주말도 그 자리에서 조사": "야간과 주말에도 즉시 조사 착수",
        "조사규칙·EngrNote로 남아 사람에 안 묶인다": "조사규칙과 EngrNote로 기록해 담당자 변경 시 재사용",
        "표준안으로 코어를 그대로 넘긴다": "공통 조사 코어와 확산 표준안을 적용",
        "확산 공통 조사 코어와 확산 표준안을 적용": "공통 조사 코어와 확산 표준안을 적용",
        "2차년 자동조치 개방": "2차년 자동조치 적용",
        "기준 넘은 시나리오만": "기준을 충족한 시나리오만",
        "배포를 막는다": "기준 미달 시 배포를 보류한다",
    }
    replace_text(soup, replacements)

    # The application form reads more naturally when compact noun lists use commas.
    replace_text(soup, {"·": ", "})
    for text_node in list(soup.find_all(string=True)):
        if text_node.parent and text_node.parent.name in {"style", "script"}:
            continue
        value = str(text_node)
        updated = re.sub(r"\s+,", ",", value)
        updated = re.sub(r",(?=[^\s\d])", ", ", updated)
        updated = re.sub(r" {2,}", " ", updated)
        if updated != value:
            text_node.replace_with(updated)

    # Exact correction for the shared RAG alternative; this is a fact-sensitive sentence.
    for td in soup.find_all("td"):
        if "문서를 통짜 벡터로 넣는 구조" in td.get_text(" ", strip=True):
            td.clear()
            td.string = (
                "문서 적재는 가능하지만 검색 설정은 기본값에 가깝다. 반도체 사전 등록, "
                "용어 병기, 메타 필터를 적용할 수 없어 설비·recipe·공정 조건을 정확히 좁히기 어렵다"
            )

    return soup


def visible_text(soup: BeautifulSoup) -> str:
    clone = BeautifulSoup(str(soup), "html.parser")
    for node in clone(["style", "script"]):
        node.decompose()
    return " ".join(clone.get_text(" ", strip=True).split())


def lint(text: str) -> list[str]:
    forbidden = [
        "완전한", "살아있는", "스스로", "통째로", "정거장", "자란다", "닫힌다", "관문", "걷는다", "돌파",
        "답이 자란다", "한 코어로 닫힌다", "실물에 닿는다", "통째로 내려온다",
        "끝이 다음 시작을 키운다", "침묵 실패", "쓸수록 정확해진다", "SFT", "DPO", "KTO", "·",
        "통짜", "뭉개", "손잡이", "할 손이", "사장된다", "상향 평준화", "사람 머릿속",
        "각자 알아서", "답의 수준", "그림자 운영", "현업 몫", "오탐 남발", "원인 확정",
        "강등",
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
