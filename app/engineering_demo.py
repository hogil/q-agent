"""Build linked synthetic incident history and recurring review meeting records."""
from __future__ import annotations

import copy
import json
from pathlib import Path


def load_scenarios(path):
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if set(payload) != {"version", "synthetic", "cases"} or payload["version"] != 1 or payload["synthetic"] is not True:
        raise ValueError("invalid synthetic scenarios")
    fields = {"title", "hypothesis", "counterevidence", "checks", "historical_cause", "action", "verification"}
    if not isinstance(payload["cases"], dict) or not payload["cases"]:
        raise ValueError("scenario cases required")
    for case in payload["cases"].values():
        if not isinstance(case, dict) or set(case) != fields:
            raise ValueError("invalid scenario fields")
        if any(not isinstance(case[key], str) or not case[key].strip() for key in fields - {"historical_cause"}):
            raise ValueError("scenario text required")
        if case["historical_cause"] is not None and not isinstance(case["historical_cause"], str):
            raise ValueError("invalid historical cause")
    return payload


def enrich_raw(records, scenarios):
    if scenarios.get("version") != 1 or scenarios.get("synthetic") is not True:
        raise ValueError("synthetic scenarios version 1 required")
    cases = scenarios["cases"]
    for record in records.values():
        informs = {row["id"]: row for row in record["inform_notes"]}
        for ref in record.get("defect_references", []):
            if ref["item"] not in cases:
                raise ValueError(f"scenario missing for {ref['item']}")
            case = cases[ref["item"]]
            ref["finding"] = (
                f"합성 과거 사례: {case['title']}. {case['verification']} "
                "CD는 합성 좌표값이며 SEM 픽셀 실측값이 아니다. 현재 원인 확정 근거가 아니다.")
            note = informs[ref["inform_id"]]
            note["title"] = f"{ref['incident_number']} · {case['title']}"
            note["body"] = (f"합성 Eng'r Inform / {ref['incident_number']} / {ref['step']} / {ref['equipment']}\n"
                            f"가설: {case['hypothesis']}\n반대 근거: {case['counterevidence']}\n"
                            f"과거 기록 원인: {case['historical_cause'] or '미확정'}\n"
                            f"조치 기록: {case['action']}\n검증: {case['verification']}\n"
                            f"현재 점검: {case['checks']}\n출처: synthetic://incident/{ref['incident_number']}")
    return records


def linked_rows(records, base_incidents, scenarios):
    template = base_incidents[0]
    history, lots, wafers, meetings = {}, [], [], []
    for number, record in records.items():
        current_id = next(row["incident_id"] for row in base_incidents if row["incident_number"] == number)
        informs = {row["id"]: row for row in record["inform_notes"]}
        for ref in record.get("defect_references", []):
            case = scenarios["cases"][ref["item"]]
            hist_number = ref["incident_number"]
            hist_id = f"synthetic-history-{hist_number}"
            review_id = f"syn-chunk-review-{number}-{ref['item']}"
            first_history = hist_id not in history
            if first_history:
                note = informs[ref["inform_id"]]
                row = copy.deepcopy(template)
                row.update(incident_id=hist_id, incident_number=hist_number, title=note["title"],
                           occurred_at=ref["date"], expected_lot_count=1, affected_wafer_count=1,
                           incident_detail=f"합성 사고이력 / {ref['step']} / {ref['equipment']} / {ref['item']}",
                           analysis_detail=note["body"], confirmed_cause=case["historical_cause"],
                           containment="합성 사례의 검토 대상 보류; 실제 조치 아님",
                           corrective_action=case["action"],
                           verification=ref["finding"], prevention="정기 사고 분석회의에서 동일 조건 재발 검토",
                           remaining="현재 사례와의 동일 원인 여부는 미확인")
                history[hist_id] = row
                lots.append(dict(incident_ref=hist_id, lot_id=ref["lotId"], product_code="SYN-PRODUCT-HISTORY", status="REGISTERED"))
                wafers.append(dict(incident_ref=hist_id, lot_id=ref["lotId"], wafer_id=ref["waferId"], status="REGISTERED"))
            note = informs[ref["inform_id"]]
            # Past conclusions and current hypotheses belong to different time scopes.
            for stage, meeting_date, text in (
                ("history", ref["date"][:10], f"과거 사례 검토. {note['body']}"),
                ("initial", "2026-03-29", f"현재 {number} / {ref['item']} 초기 분석. {note['body']}\n과거 결론은 현재 원인으로 전이하지 않는다. 현재 EDS 대기. 현재 가설은 미확정."),
                ("review", "2026-03-31", f"현재 {number} / {ref['item']} 정기 사고 분석회의 재검토. {note['body']}\nTrend·SEM·CD·THK·Overlay와 생산 이력을 동일 Step/시간/Lot/Wafer로 대조한다. 반대 근거와 정상 비교군을 확인한다. 현재 EDS 미수신으로 불량 확정은 보류. 점검은 권고이며 실행되지 않았다."),
            ):
                if stage == "history" and not first_history:
                    continue
                meetings.append(dict(chunk_id=f"{review_id}-{stage}", meeting_id=f"syn-periodic-{meeting_date}",
                                     title=f"정기 사고 분석회의 {meeting_date[:7]} / {number} / {ref['item']} / {stage}",
                                     meeting_date=meeting_date, version="v1", status="approved",
                                     incident_ids=[hist_id] if stage == "history" else [current_id, hist_id],
                                     text=text, source_ref=f"synthetic://periodic-review/{review_id}/{stage}"))
    return list(history.values()), lots, wafers, meetings
