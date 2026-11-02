"""Deterministic Korean quantitative facts derived from platform evidence."""
from __future__ import annotations

import hashlib
import math
import re
from typing import Any


MAX_FACTS = 12
PLATFORM_LIMITATIONS = [
    '합성 자료이며 실제 공정의 성능과 인과는 검증하지 않았습니다.',
    '등록 목록의 원본 완전성은 미확인입니다.',
    'Map 반복성은 선택한 crop의 정합과 방향 가정 안에서만 해석합니다.',
    '합성 모델 score는 원인 확률이나 확정 불량 판정이 아닙니다.',
    'Die·bit·pixel 좌표의 물리 정합은 별도로 확인해야 합니다.',
]
_ALLOWED_PROSE_REFERENCE = re.compile(r"\[e[0-9]+\]", re.IGNORECASE)
_KOREAN_NUMBER_QUANTITY = re.compile(
    r"(?<![가-힣A-Za-z])(?:[영공일이삼사오육칠팔구십백천만억]+|열한|열두|열세|열네|스무|스물한|스물두|스물세|스물네|"
    r"한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|스물|서른|마흔|쉰|예순|일흔|여든|아흔)"
    r"\s*(?:건수|건|개|회|번|명|장|쌍|곳|항목|칩|chip|wafer|lot|row|퍼센트|%)",
    re.IGNORECASE)
_ENGLISH_NUMBER_QUANTITY = re.compile(
    r"\b(?:zero|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|"
    r"dozen|hundred|thousand|million)\s+(?:chips?|wafers?|lots?|dies|features?|samples?|rows?|"
    r"tests?|failures?|counts?|percent(?:age)?|notes?|pairs?|regions?|items?|days?|hours?)\b",
    re.IGNORECASE)


def _count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _number(value: Any) -> float | None:
    if type(value) not in (int, float):
        return None
    result = float(value)
    return result if math.isfinite(result) else None


def _label(value: Any, limit: int = 80) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    clean = " ".join("".join(char for char in value if char >= " " and char != "\x7f").split())
    return clean[:limit] or None


def _source_ok(evidence: dict[str, Any], source: str) -> bool:
    section = evidence.get("sections", {}).get(source, {})
    return isinstance(section, dict) and section.get("status") == "OK" and _count(section.get("count")) is not None and section["count"] > 0


def _fact(kind: str, text: str, evidence_ids: list[str]) -> dict[str, Any]:
    digest = hashlib.sha256((kind + "\n" + text).encode("utf-8")).hexdigest()[:10]
    return {"fact_id": f"f_{kind}_{digest}", "text": text,
            "evidence_ids": evidence_ids, "kind": kind}


def _result_facts(evidence: dict[str, Any]) -> list[dict[str, Any]]:
    """Create bounded facts from a platform result's complete aggregates."""
    if not isinstance(evidence, dict) or evidence.get("synthetic") is not True:
        return []
    facts: list[dict[str, Any]] = []

    def add(kind: str, text: str, refs: list[str]):
        if len(facts) < MAX_FACTS and len(text) <= 240:
            fact = _fact(kind, text, refs)
            if all(existing["fact_id"] != fact["fact_id"] for existing in facts):
                facts.append(fact)

    summaries = evidence.get("summaries", {})
    if not isinstance(summaries, dict):
        summaries = {}

    if _source_ok(evidence, "test"):
        test_facts = []
        for row in summaries.get("test", [])[:4]:
            if not isinstance(row, dict):
                continue
            stage = _label(row.get("stage"), 24)
            tested, failed, wafer_tests = (_count(row.get(key)) for key in ("tested", "failed", "wafer_tests"))
            if not stage or tested is None or failed is None or wafer_tests is None or failed > tested:
                continue
            yield_pct = _number(row.get("yield_pct_from_counts"))
            if yield_pct is None and tested:
                yield_pct = 100.0 * (1.0 - failed / tested)
            yield_text = f", yield {yield_pct:.2f}%" if yield_pct is not None else ""
            test_facts.append(f"{stage}: chip test {tested}건 중 fail {failed}건; wafer-stage test 행 {wafer_tests}건{yield_text}")
        if test_facts:
            add("test_summary", "Test stage별 " + "; ".join(test_facts) + ".", ["get_platform_evidence.summaries.test"])

    if _source_ok(evidence, "measure"):
        measure_facts = []
        for row in summaries.get("measure", [])[:3]:
            if not isinstance(row, dict):
                continue
            item = _label(row.get("item"), 32)
            samples, outside = _count(row.get("samples")), _count(row.get("outside_limits"))
            if not item or samples is None or outside is None or outside > samples:
                continue
            unit = _label(row.get("unit"), 16) or "unit 미확인"
            mean = _number(row.get("mean"))
            mean_text = f", 평균 {mean:.5g} {unit}" if mean is not None else ""
            measure_facts.append(f"{item}: sample {samples}건{mean_text}, 기존 limit 초과 {outside}건")
        if measure_facts:
            add("legacy_measure", "Legacy 단변량 measure item별 " + "; ".join(measure_facts) + ".", ["get_platform_evidence.summaries.measure"])

    tabular = evidence.get("tabular_analysis")
    if _source_ok(evidence, "measure") and isinstance(tabular, dict) and tabular.get("status") == "OK":
        chips = _count(tabular.get("chip_count")); features = _count(tabular.get("feature_count"))
        source_features = _count(tabular.get("source_feature_count")); dummy = _count(tabular.get("dummy_feature_count"))
        flagged = _count(tabular.get("flagged_chip_count"))
        if None not in (chips, features, source_features, dummy, flagged) and source_features + dummy == features:
            add("tabular_summary", f"다변량 chip-stage 분석: source measure item {source_features}개 + 합성 dummy feature {dummy}개 = feature {features}개; chip-stage row {chips}건 중 threshold flag {flagged}건.",
                ["get_platform_evidence.tabular_analysis"])

    if _source_ok(evidence, "failbit"):
        failbit_facts = []
        for row in summaries.get("failbit", [])[:2]:
            if not isinstance(row, dict):
                continue
            test_item = _label(row.get("test_item"), 32)
            sites = _count(row.get("observed_bit_sites")); chips = _count(row.get("chips"))
            operations = _count(row.get("failed_operations"))
            if test_item and sites is not None and chips is not None and operations is not None:
                failbit_facts.append(f"{test_item}: bit-site {sites}건, 실패 operation {operations}건, distinct chip {chips}개")
        if failbit_facts:
            add("failbit_summary", "Failbit item별 " + "; ".join(failbit_facts) + ".", ["get_platform_evidence.summaries.failbit"])

    observations = evidence.get("model_observations", [])
    if isinstance(observations, list):
        by_modality: dict[str, list[dict[str, Any]]] = {}
        for row in observations:
            if isinstance(row, dict) and _label(row.get("modality"), 24):
                by_modality.setdefault(row["modality"], []).append(row)
        model_facts = []
        for modality, rows in sorted(by_modality.items()):
            available = [row for row in rows if row.get("status") == "OK" and _number(row.get("score")) is not None]
            if available:
                labels: dict[str, int] = {}
                scores = []
                for row in available:
                    label = _label(row.get("label"), 40)
                    if label:
                        labels[label] = labels.get(label, 0) + 1
                    scores.append(_number(row["score"]))
                class_text = ", ".join(f"{key} {value}건" for key, value in sorted(labels.items())) or "label 미제공"
                model_facts.append(f"{modality.upper()} synthetic score {len(available)}건, class {class_text}, score {min(scores):.4f}–{max(scores):.4f}")
            else:
                status = _label(rows[0].get("status"), 40) or "unavailable"
                model_facts.append(f"{modality.upper()} synthetic model 상태 {status}; score 미제공")
        if model_facts:
            add("model_observation", "; ".join(model_facts) + ". Synthetic score는 verdict가 아닙니다.",
                ["get_platform_evidence.model_observations"])

    maps = evidence.get("map_analysis", {})
    cases = maps.get("cases", []) if isinstance(maps, dict) else []
    if isinstance(cases, list):
        map_facts = []
        for case in cases[:2]:
            if not isinstance(case, dict) or case.get("status") != "OK":
                continue
            analysis = case.get("analysis", {})
            grains = analysis.get("grains", {}) if isinstance(analysis, dict) else {}
            wafer = grains.get("wafer_local_anomaly", {}) if isinstance(grains, dict) else {}
            chip = grains.get("chip_internal_motif", {}) if isinstance(grains, dict) else {}
            motif = grains.get("cross_chip_repeated_motif", {}) if isinstance(grains, dict) else {}
            crop_count = _count(analysis.get("bounds", {}).get("chip_crops_analyzed")) if isinstance(analysis.get("bounds"), dict) else None
            regions = _count(wafer.get("regions_returned")) if isinstance(wafer, dict) else None
            registered = _count(chip.get("registered_chip_count")) if isinstance(chip, dict) else None
            support = motif.get("supporting_chip_ids", []) if isinstance(motif, dict) else []
            support_count = len(support) if isinstance(support, list) else None
            pairs = _count(motif.get("supporting_pair_count")) if isinstance(motif, dict) else None
            if None not in (crop_count, regions, registered, support_count, pairs):
                status = _label(motif.get("status"), 48) or "status 미확인"
                map_facts.append(f"crop {crop_count}건, wafer color 후보 {regions}개, registered chip {registered}개, motif support chip/pair {support_count}/{pairs} ({status})")
        if map_facts:
            add("map_observation", "등록 map 분석 sample: " + "; ".join(map_facts) + ". 후보 통계이며 결함 판정이 아닙니다.",
                ["get_platform_evidence.map_analysis"])

    if _source_ok(evidence, "inform"):
        inform_facts = []
        for row in summaries.get("inform", [])[:2]:
            if isinstance(row, dict):
                version = _label(row.get("version"), 48)
                notes = _count(row.get("notes"))
                if version and notes is not None:
                    inform_facts.append(f"version {version}: note {notes}건")
        if inform_facts:
            add("inform_summary", "Inform Note " + "; ".join(inform_facts) + ".", ["get_platform_evidence.summaries.inform"])

    return facts[:MAX_FACTS]


def build_platform_facts(evidence: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bind numerical facts to canonical runtime evidence IDs, never JSON paths."""
    if not isinstance(evidence, list) or not any(entry.get('source') == 'get_platform_evidence'
                                               and entry.get('result', {}).get('synthetic') is True for entry in evidence):
        return []
    facts = []
    for entry in evidence:
        result, source, evidence_id = entry.get('result', {}), entry.get('source'), entry.get('id')
        if not isinstance(result, dict) or not isinstance(evidence_id, str):
            continue
        if source == 'get_platform_evidence':
            found = _result_facts(result)
            empty = [name for name, section in result.get('sections', {}).items()
                     if section.get('status') == 'NO_MATCH' and section.get('count') == 0]
            if empty:
                found.append(_fact('unobserved_sources', '조회 범위의 source ' + ', '.join(empty)
                    + '는 관측 행이 0건입니다. 미적재·미연결·관측 없음을 구분해야 하며 정상 판정이 아닙니다.', []))
            alignment = result.get('cross_modal_alignment', {})
            counts, overlaps = alignment.get('chip_counts', {}), alignment.get('overlap_chip_counts', {})
            if all(key in counts for key in ('measure', 'failbit', 'sem', 'legacy_measure_out_of_spec')):
                text = (f"동일 복합키의 distinct chip: Measure {counts['measure']}개, 기존 규격 초과 {counts['legacy_measure_out_of_spec']}개, "
                        f"Failbit {counts['failbit']}개, SEM {counts['sem']}개. "
                        f"Failbit∩SEM {overlaps.get('failbit_and_sem', 0)}개; 동시 관측이며 인과 확정이 아닙니다.")
                found = [fact for fact in found if fact['kind'] != 'cross_modal_alignment']
                found.append(_fact('cross_modal_alignment', text, []))
            if _source_ok(result, 'mes'):
                states = ', '.join(f"{row['status']} {row['events']}행" for row in result.get('summaries', {}).get('mes', []))
                if states:
                    found.append(_fact('mes_summary', 'MES 상태 관측: ' + states + '. 상태만으로 조치 완료를 뜻하지 않습니다.', []))
        elif source == 'list_incident_lots' and _count(result.get('unique_lots')) is not None:
            found = [_fact('lot_summary', f"등록 Lot distinct {result['unique_lots']}개. 원본 완전성: {result.get('source_completeness', 'unknown')}; Lot별 Wafer 수를 추론하지 않습니다.", [])]
        elif source == 'search_platform_history' and result.get('status') == 'OK':
            items = result.get('items', [])
            found = [_fact('history_summary', f"표시된 과거 유사 사고 후보 {len(items)}건. 유사도는 원인 확률이 아니며 현재 영향 scope에 합치지 않습니다.", [])]
        else:
            continue
        for fact in found:
            fact = {**fact, 'evidence_ids': [evidence_id]}
            existing = next((row for row in facts if row['fact_id'] == fact['fact_id']), None)
            if existing is None:
                facts.append(fact)
            elif evidence_id not in existing['evidence_ids']:
                existing['evidence_ids'].append(evidence_id)
    return facts[:MAX_FACTS]


def validate_platform_prose(text: str, allowed_identifiers: list[str] | None = None) -> bool:
    """Reject digits in free prose; only [eN] refs and explicit IDs may remain."""
    if not isinstance(text, str) or len(text) > 4000:
        return False
    if allowed_identifiers is not None and not isinstance(allowed_identifiers, list):
        return False
    remaining = _ALLOWED_PROSE_REFERENCE.sub("", text)
    for identifier in allowed_identifiers or []:
        if not isinstance(identifier, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", identifier):
            return False
        remaining = re.sub(r"(?<![A-Za-z0-9_-])" + re.escape(identifier) + r"(?![A-Za-z0-9_-])", "", remaining)
    return (not any(character.isnumeric() for character in remaining)
            and not _KOREAN_NUMBER_QUANTITY.search(remaining)
            and not _ENGLISH_NUMBER_QUANTITY.search(remaining))


def render_platform_answer(facts: list[dict[str, Any]], selected_fact_ids: list[str] | None = None,
                           prose: str = "",
                           allowed_identifiers: list[str] | None = None) -> str:
    """Compose computed fact strings and qualitative LLM prose as separate blocks."""
    if not isinstance(facts, list) or (selected_fact_ids is not None
            and (not isinstance(selected_fact_ids, list) or len(selected_fact_ids) > MAX_FACTS)):
        raise ValueError("invalid platform fact selection")
    selected_fact_ids = selected_fact_ids if selected_fact_ids is not None else [fact.get("fact_id") for fact in facts]
    if any(not isinstance(fact_id, str) for fact_id in selected_fact_ids):
        raise ValueError("fact ids must be strings")
    if len(set(selected_fact_ids)) != len(selected_fact_ids):
        raise ValueError("duplicate selected fact id")
    by_id = {fact.get("fact_id"): fact for fact in facts if isinstance(fact, dict)}
    if any(fact_id not in by_id for fact_id in selected_fact_ids):
        raise ValueError("unknown selected fact id")
    if not validate_platform_prose(prose, allowed_identifiers):
        raise ValueError("PLATFORM_PROSE_CONTAINS_UNSUPPORTED_QUANTITY")
    selected = [by_id[fact_id] for fact_id in selected_fact_ids]
    computed = "\n".join("- " + fact["text"] + " [" + ", ".join(fact["evidence_ids"]) + "]"
                          for fact in selected)
    if computed and prose.strip():
        return computed + "\n\n" + prose.strip()
    return computed or prose.strip()
