"""Bounded Router -> Tools -> Judge -> Answer loop, with read-only DB adapters."""
from contextlib import ExitStack
from datetime import date, datetime
import inspect
import json
import hashlib
import math
import re
import sqlite3
import copy
import uuid
from zoneinfo import ZoneInfo

from config_loader import ConfigError
from incident_tools import IncidentTools, ToolError
from llm_client import LLMError, RoleClient
from meeting_tools import MeetingTools
from image_tools import ImageTools
from prompt_contracts import inspection_rows, structure, validate_output
from runtime_factory import open_incident_tools
from skill_loader import compile_prompt, read_role_reference
from conversation_memory import pack_turns
from evidence_review import no_match_response, review_evidence, validate_snapshot_scope
from context_manager import select_context
from recovery_policy import classify_recovery

TOOL_TOPICS = {
    'match_incident_values': 'terminology', 'find_incidents': 'incident_search', 'summarize_incidents': 'statistics',
    'list_incident_lots': 'lots', 'list_incident_wafers': 'wafers',
    'search_meeting_minutes': 'meetings', 'list_comparison_assets': 'images',
    'compare_sem_images': 'images', 'compare_overlay_maps': 'images',
    'get_platform_evidence': 'platform', 'search_platform_history': 'platform',
    'search_engineer_notes': 'documents', 'search_internal_documents': 'documents',
    'search_mes_reference': 'mes_reference',
    'search_similar_fbm': 'images',
}

MES_CATALOG_CANDIDATE_LIMITATION = '인용된 MES 결과에 사고 연관성이 확인되지 않은 기준정보 후보가 포함되어 있습니다.'
DOCUMENT_RESULTS_SOURCE_REPORTED_TRUNCATED_LIMITATION = '인용된 문서 검색 결과가 출처에서 잘린 것으로 보고되었습니다.'
DOCUMENT_RETRIEVAL_COMPLETENESS_UNKNOWN_LIMITATION = '인용된 문서 검색 결과의 전체성은 확인되지 않았습니다.'
DOCUMENT_SOURCE_NONTRUNCATION_LIMITATION = '인용된 문서 검색의 미잘림은 출처 보고이며 전체 저장소의 검색 완전성을 보증하지 않습니다.'
DOCUMENT_ACCESS_CONTROL_UNVERIFIED_LIMITATION = '인용된 문서의 사용자별 접근 권한은 Q-Agent에서 별도로 검증하지 않았습니다.'


def provider_usage_field(reported, field, attempted_calls):
    """Summarize valid per-call observations without treating partial sums as totals."""
    known = [row[field] for row in reported
             if type(row.get(field)) is int and row[field] >= 0]
    reported_calls = len(known)
    if attempted_calls == 0:
        observed_subtotal = 0
        coverage = 'no_calls'
    else:
        observed_subtotal = sum(known) if known else None
        if reported_calls == attempted_calls:
            coverage = 'complete'
        elif reported_calls:
            coverage = 'partial'
        else:
            coverage = 'unavailable'
    total = sum(known) if len(known) == attempted_calls else None
    return {'total': total, 'reported_calls': reported_calls,
            'attempted_calls': attempted_calls, 'observed_subtotal': observed_subtotal,
            'coverage': coverage}


def mes_catalog_candidate_system_limitations(answer, evidence):
    """Return response-level caveats for candidate-bearing MES responses cited by the Answer."""
    cited_ids = {evidence_id for claim in answer.get('claims', [])
                 for evidence_id in claim.get('evidence_ids', [])}
    has_cited_candidate = any(
        entry.get('source') == 'search_mes_reference'
        and entry.get('id') in cited_ids
        and isinstance(entry.get('result'), dict)
        and isinstance(entry['result'].get('items'), list)
        and any(isinstance(item, dict) and item.get('scope_relation') == 'catalog_candidate'
                for item in entry['result']['items'])
        for entry in evidence)
    return [MES_CATALOG_CANDIDATE_LIMITATION] if has_cited_candidate else []


def document_retrieval_system_limitations(answer, evidence):
    """Return response-level caveats for cited document results with uncertain completeness."""
    cited_ids = {evidence_id for claim in answer.get('claims', [])
                 for evidence_id in claim.get('evidence_ids', [])}
    states = set()
    has_cited_document = False
    for entry in evidence:
        if (entry.get('source') not in ('search_engineer_notes', 'search_internal_documents')
                or entry.get('id') not in cited_ids):
            continue
        has_cited_document = True
        result = entry.get('result', {})
        metadata = entry.get('review_metadata', {}).get('document_retrieval', {})
        truncated = result.get('source_reported_truncated', metadata.get('source_reported_truncated'))
        if truncated is True:
            states.add(True)
        elif truncated is False:
            states.add(False)
        elif truncated is None:
            states.add(None)
    limitations = []
    if True in states:
        limitations.append(DOCUMENT_RESULTS_SOURCE_REPORTED_TRUNCATED_LIMITATION)
    if False in states:
        limitations.append(DOCUMENT_SOURCE_NONTRUNCATION_LIMITATION)
    if None in states:
        limitations.append(DOCUMENT_RETRIEVAL_COMPLETENESS_UNKNOWN_LIMITATION)
    if has_cited_document:
        limitations.append(DOCUMENT_ACCESS_CONTROL_UNVERIFIED_LIMITATION)
    return limitations


def failures_after_confirmed_membership_change(failures, previous_ids, new_ids):
    """Retire failures for an old membership only after a resolved membership change."""
    if not previous_ids or not new_ids or set(previous_ids) == set(new_ids):
        return failures
    previous = sorted(previous_ids)
    return [failed for failed in failures if failed.get('incident_ids') != previous]


def detail_pages_complete(pages, kind):
    """Return true only for ordered, gap-free, internally consistent complete pages."""
    if kind not in ('lots', 'wafers'):
        return False
    try:
        pages = sorted(pages, key=lambda page: page['offset'])
        if not pages or pages[0]['offset'] != 0:
            return False
        first = pages[0]
        total = first['total_memberships']
        if (type(total) is not int or total <= 0
                or first.get('source_completeness') != 'declared_complete'):
            return False
        coverage_state = 'complete_by_declared_source_and_count'
        coverage = first.get('coverage')
        if (not isinstance(coverage, list) or not coverage
                or any(not isinstance(row, dict) or row.get('state') != coverage_state for row in coverage)):
            return False
        if kind == 'wafers' and (first.get('wafer_scope') != 'incident_affected'
                or not isinstance(first.get('lot_coverage'), list) or not first['lot_coverage']
                or any(not isinstance(row, dict) or row.get('state') != coverage_state
                       for row in first['lot_coverage'])
                or first.get('lots_without_wafer_rows') != []):
            return False
        signature = (first.get('scope_id'), total, first.get('source_completeness'),
                     first.get('mapping_version'), first.get('wafer_scope'),
                     first.get('coverage'), first.get('lot_coverage'))
        expected_offset = 0
        row_count = 0
        identities = set()
        identity_fields = (('incident_id', 'lot_id') if kind == 'lots' else
                           ('incident_id', 'lot_id', 'wafer_id'))
        for index, page in enumerate(pages):
            items = page.get('items')
            if (page.get('status') != 'OK' or type(page.get('offset')) is not int
                    or page['offset'] != expected_offset or page.get('total_memberships') != total
                    or (page.get('scope_id'), page.get('total_memberships'),
                        page.get('source_completeness'), page.get('mapping_version'),
                        page.get('wafer_scope'), page.get('coverage'), page.get('lot_coverage')) != signature
                    or not isinstance(items, list) or not items):
                return False
            row_count += len(items)
            if row_count > total:
                return False
            for item in items:
                if not isinstance(item, dict):
                    return False
                identity = tuple(item.get(field) for field in identity_fields)
                if any(not isinstance(value, str) or not value for value in identity) or identity in identities:
                    return False
                identities.add(identity)
            end = expected_offset + len(items)
            next_offset = page.get('next_offset')
            if next_offset is None:
                if index != len(pages) - 1 or row_count != total:
                    return False
            elif type(next_offset) is not int or next_offset != end:
                return False
            expected_offset = end
        return pages[-1].get('next_offset') is None and row_count == total and len(identities) == total
    except (KeyError, TypeError, ValueError):
        return False


def lookup_chain_finished(name, pages, scope_id):
    """Check pagination termination without treating source status as completeness."""
    if name not in ('list_incident_lots', 'list_incident_wafers'):
        return False
    try:
        pages = sorted(pages, key=lambda pair: pair[0].get('offset', 0))
        expected_offset = 0
        total = None
        identities = set()
        identity_fields = (('incident_id', 'lot_id') if name == 'list_incident_lots' else
                           ('incident_id', 'lot_id', 'wafer_id'))
        for index, (arguments, page) in enumerate(pages):
            offset = arguments.get('offset', 0)
            page_total = page.get('total_memberships')
            items = page.get('items')
            if (type(offset) is not int or offset != expected_offset or type(page_total) is not int
                    or page_total < 0 or (total is not None and page_total != total)
                    or (page_total > 0 and page.get('offset') != offset)
                    or (page.get('offset') is not None and page.get('offset') != offset)
                    or (page_total > 0 and page.get('scope_id') != scope_id)
                    or (page.get('scope_id') is not None and page.get('scope_id') != scope_id)
                    or page.get('status') not in ('OK', 'PARTIAL', 'NO_MATCH')
                    or (page_total == 0 and page.get('status') == 'OK')
                    or (page_total > 0 and page.get('status') == 'NO_MATCH')
                    or not isinstance(items, list) or (page_total > 0 and not items)):
                return False
            total = page_total
            for item in items:
                if not isinstance(item, dict):
                    return False
                identity = tuple(item.get(field) for field in identity_fields)
                if any(not isinstance(value, str) or not value for value in identity) or identity in identities:
                    return False
                identities.add(identity)
            expected_offset += len(items)
            next_offset = page.get('next_offset')
            if next_offset is None:
                if index != len(pages) - 1 or expected_offset != total:
                    return False
            elif type(next_offset) is not int or next_offset != expected_offset:
                return False
        return bool(pages) and pages[-1][1].get('next_offset') is None and expected_offset == total
    except (AttributeError, TypeError, ValueError):
        return False


def map_prompt_evidence(entry):
    # Preserve full Tool arrays for the UI; LLMs receive bounded numerical summaries.
    if entry['source'] == 'get_platform_evidence':
        compact = copy.deepcopy(entry)
        for source, section in compact['result'].get('sections', {}).items():
            rows = section.get('rows', [])
            section['returned_rows_in_original'] = len(rows)
            section['rows'] = rows[:2 if source == 'inform' else 1]
            section['prompt_sampled'] = len(rows) > len(section['rows'])
        tabular = compact['result'].get('tabular_analysis', {})
        if 'chips' in tabular:
            tabular['chips'] = tabular['chips'][:3]
        for case in compact['result'].get('map_analysis', {}).get('cases', []):
            analysis = case.get('analysis', {})
            provenance = analysis.get('provenance', {})
            provenance.pop('chip_asset_sha256', None)
            morphology = analysis.get('grains', {}).get('chip_internal_motif', {})
            if 'chips' in morphology:
                morphology['chips'] = morphology['chips'][:2]
        return compact
    if entry['source'] != 'get_engineering_snapshot':
        return entry
    compact = copy.deepcopy(entry)
    maps = compact['result'].get('sections', {}).get('maps', {})
    if 'assets' in maps:
        maps['assets'] = [{key: value for key, value in asset.items()
                           if key not in ('overlay', 'cd', 'thk', 'eds_bin')}
                          for asset in maps['assets']]
    return compact


def document_answer_context(evidence, review):
    entries = [entry for entry in evidence if entry['source'] in
               ('search_engineer_notes', 'search_internal_documents')]
    if not entries:
        return None
    evidence_ids = {entry['id'] for entry in entries}
    return {
        'document_evidence': [
            {'evidence_id': entry['id'], 'source': entry['source'],
             'query': entry.get('arguments', {}).get('query'), 'result': entry['result']}
            for entry in entries],
        'document_evidence_review': {
            'records': [record for record in review['records']
                        if record['evidence_id'] in evidence_ids],
            'source_groups': [group for group in review['source_groups']
                              if evidence_ids.intersection(group['evidence_ids'])],
            'issues': [issue for issue in review['issues']
                       if issue.get('evidence_id') in evidence_ids],
            'limitations': review['limitations'],
        },
    }


def mes_reference_answer_context(evidence, review):
    entries = [entry for entry in evidence if entry['source'] == 'search_mes_reference']
    if not entries:
        return None
    evidence_ids = {entry['id'] for entry in entries}
    return {
        'mes_reference_evidence': [
            {'evidence_id': entry['id'], 'kind': entry.get('arguments', {}).get('kind'),
             'query': entry.get('arguments', {}).get('query'), 'result': entry['result']}
            for entry in entries],
        'mes_reference_evidence_review': {
            'records': [record for record in review['records']
                        if record['evidence_id'] in evidence_ids],
            'source_groups': [group for group in review['source_groups']
                              if evidence_ids.intersection(group['evidence_ids'])],
            'issues': [issue for issue in review['issues']
                       if issue.get('evidence_id') in evidence_ids],
            'limitations': review['limitations'],
        },
    }


def run(settings, question, actor, request_scope='incident', topics=None, selected=None, emit=None, as_of=None,
        context_data=None, engineering_query=None, requested_tools=(), related_search=True, inspection_requested=False,
        conversation_turns=None, incident_number=None, document_query=None, document_allowed_statuses=None,
        mes_reference_query=None, synthetic_action_planner=None, snapshot_lease_provider=None,
        fbm_search_query=None):
    if not isinstance(question, str) or not question.strip() or len(question) > 12000:
        raise ValueError('QUESTION_REQUIRED_OR_TOO_LONG')
    if not actor or not actor.strip() or request_scope not in ('auto', 'incident', 'independent'):
        raise ValueError('ACTOR_AND_VALID_REQUEST_SCOPE_REQUIRED')
    if type(inspection_requested) is not bool:
        raise ValueError('INVALID_INSPECTION_REQUEST')
    if incident_number is not None and (request_scope != 'incident' or not isinstance(incident_number, str)
                                        or not incident_number.strip() or len(incident_number) > 256):
        raise ValueError('EXPLICIT_INCIDENT_NUMBER_REQUIRES_INCIDENT_SCOPE')
    as_of = as_of or datetime.now(ZoneInfo(settings.data['runtime']['timezone'])).date().isoformat()
    if not isinstance(as_of, str) or date.fromisoformat(as_of).isoformat() != as_of:
        raise ValueError('AS_OF_ISO_DATE_REQUIRED')
    topics = set(topics or []) if request_scope == 'incident' else set()
    if request_scope == 'incident':
        topics.add('incident_search')
    events, evidence, history = [], [], []
    limits = settings.data['runtime']
    role_contexts = {}
    memory_metrics = {}
    for role in ('router', 'judge', 'answer'):
        role_contexts[role] = context_data
        if conversation_turns is not None:
            budget = limits['conversation_memory']['router_characters' if role == 'router' else 'review_characters']
            memory = pack_turns(conversation_turns, question, budget)
            role_contexts[role] = {**(context_data or {}), 'previous_messages_unverified': memory}
            memory_metrics[role] = {'characters': len(json.dumps(memory, ensure_ascii=False, separators=(',', ':'))),
                                  'budget_characters': budget, 'messages': len(memory),
                                  'turns': len({row['turn_id'] for row in memory}),
                                  'truncated_messages': sum(row['truncated'] for row in memory)}
    state = {'scope_id': None, 'incident_checked': False, 'scope_valid': False,
             'budget_remaining': limits['max_tool_calls'], 'code_gate': 'PASS',
             'requirements': [question], 'request_scope': request_scope, 'judge': None,
             'inspection_requested': inspection_requested,
             'last_error': None, 'as_of': as_of, 'incident_evidence_complete': False,
             'completed_tool': None, 'completed_tool_arguments': None,
             'lot_lookup_complete': False, 'wafer_lookup_complete': False, 'detail_scope_valid': True,
             'planner_lot_pages_complete': False, 'planner_wafer_pages_complete': False,
             'lookup_intents': [], 'retrieval_failures': [], 'scope_status': 'UNVERIFIED',
             'scope_validation_error': None,
             'incident_lookup_status': 'NOT_QUERIED'}
    if request_scope == 'independent':
        evidence.append({'id': 'input-1', 'source': 'user_supplied_unverified', 'result': question})
    calls = 0
    run_id = uuid.uuid4().hex
    role_rounds = {'router': 0, 'judge': 0, 'answer': 0}
    next_evidence = 0
    lot_checked = False
    errors = 0
    revisions = 0
    completed_find_fingerprints = set()
    repeat_guarded_tools = {'compare_sem_images', 'compare_overlay_maps', 'get_engineering_snapshot',
                            'list_incident_lots', 'list_incident_wafers', 'get_platform_evidence', 'search_platform_history',
                            'search_related_incidents', 'search_meeting_minutes', 'search_engineer_notes',
                            'search_internal_documents', 'search_mes_reference'}
    repeat_guarded_tools.add('search_similar_fbm')
    completed_tool_fingerprints = {name: set() for name in repeat_guarded_tools}
    requested_tools = set(requested_tools)
    analysis_fields = ('incident_detail', 'analysis_detail', 'confirmed_cause', 'containment',
                       'corrective_action', 'verification', 'prevention', 'remaining')

    def event(kind, **values):
        item = {'event': kind, **values}
        events.append(item)
        if emit:
            emit(item)

    def retrieval_request_key(name, arguments):
        trusted_ids = None
        if state.get('scope_id') and db is not None:
            trusted_ids = sorted(db._scope(actor, state['scope_id'])['ids'])
        return fingerprint({'tool': name, 'incident_ids': trusted_ids, 'arguments': arguments})

    def mark_retrieval_failure(name, arguments):
        if name not in retrieval_tools:
            return
        key = retrieval_request_key(name, arguments)
        state['retrieval_failures'] = [failed for failed in state['retrieval_failures']
                                       if failed['key'] != key]
        trusted_ids = None
        if state.get('scope_id') and db is not None:
            trusted_ids = sorted(db._scope(actor, state['scope_id'])['ids'])
        state['retrieval_failures'].append({'key': key, 'tool': name,
                                            'scope_id': state.get('scope_id'),
                                            'incident_ids': trusted_ids})
        evidence[:] = [entry for entry in evidence
                       if not (entry['source'] == name and retrieval_request_key(name, entry['arguments']) == key)]

    def mark_timestamp_failure(name, arguments):
        key = retrieval_request_key(name, arguments)
        state['retrieval_failures'] = [failed for failed in state['retrieval_failures']
                                       if failed['key'] != key]
        trusted_ids = None
        if state.get('scope_id') and db is not None:
            trusted_ids = sorted(db._scope(actor, state['scope_id'])['ids'])
        state['retrieval_failures'].append({'key': key, 'tool': name,
                                            'scope_id': state.get('scope_id'),
                                            'incident_ids': trusted_ids, 'reason': 'invalid_timestamp'})
        evidence[:] = [entry for entry in evidence
                       if not (entry['source'] == name and retrieval_request_key(name, entry['arguments']) == key)]

    def validate_retrieval_signature(name, callback, bound_args, arguments):
        try:
            inspect.signature(callback).bind(**bound_args)
        except Exception:
            mark_retrieval_failure(name, arguments)
            code = ('DOCUMENT_RETRIEVAL_FAILED' if name in document_tools else
                    ('FBM_RETRIEVAL_FAILED' if name == 'search_similar_fbm' else 'MES_REFERENCE_RETRIEVAL_FAILED'))
            raise ToolError(code) from None

    def finish(status, **values):
        reported = [item['metrics'] for item in events
                    if item['event'] in ('llm_output', 'llm_metrics') and isinstance(item.get('metrics'), dict)]
        usage = {}
        for name in ('input_tokens', 'output_tokens', 'total_tokens', 'reasoning_tokens', 'cached_input_tokens'):
            usage[name] = provider_usage_field(reported, name, calls)
        latency = [row['elapsed_seconds'] for row in reported
                   if type(row.get('elapsed_seconds')) in (int, float)
                   and math.isfinite(row['elapsed_seconds']) and row['elapsed_seconds'] >= 0]
        phases = {}
        recoveries = {}
        for item in events:
            if item['event'] == 'llm_start':
                phase = item.get('context', {}).get('phase', 'unknown')
                phases[phase] = phases.get(phase, 0) + 1
            if item['event'] == 'validation_or_tool_error' and item.get('recovery'):
                category = item['recovery']['category']
                recoveries[category] = recoveries.get(category, 0) + 1
        active_find = next((entry.get('result') for entry in reversed(evidence)
                            if entry.get('source') == 'find_incidents'
                            and isinstance(entry.get('result'), dict)
                            and entry['result'].get('scope_id') == state.get('scope_id')), None)
        confirmed = []
        if active_find and state.get('scope_valid') and active_find.get('status') == 'OK' \
                and not active_find.get('requires_selection') and db is not None:
            try:
                scope_members = set(db._scope(actor, state['scope_id'])['ids'])
                rows = active_find.get('data', [])
                row_ids = [row.get('incident_id') for row in rows if isinstance(row, dict)]
                rows_valid = (isinstance(rows, list) and len(row_ids) == len(rows)
                              and all(isinstance(value, str) for value in row_ids)
                              and len(set(row_ids)) == len(row_ids) and set(row_ids) == scope_members
                              and all(isinstance(row.get('incident_number'), str) for row in rows))
                if rows_valid:
                    confirmed = [{'incident_id': row['incident_id'], 'incident_number': row['incident_number']}
                                 for row in rows]
                    state['scope_status'] = 'VALID'
                else:
                    state['scope_valid'] = False
                    state['scope_status'] = 'UNAVAILABLE'
                    state['scope_validation_error'] = 'SCOPE_EVIDENCE_MISMATCH'
            except Exception as exc:
                state['scope_valid'] = False
                state['scope_status'] = 'EXPIRED' if 'SCOPE_EXPIRED' in str(exc) else 'UNAVAILABLE'
                state['scope_validation_error'] = 'SCOPE_EXPIRED' if state['scope_status'] == 'EXPIRED' else 'SCOPE_VALIDATION_FAILED'
        elif (request_scope == 'incident' and state.get('scope_valid')
              and state.get('incident_lookup_status') == 'OK' and state.get('scope_id')):
            state['scope_valid'] = False
            state['scope_status'] = 'UNAVAILABLE'
            state['scope_validation_error'] = 'SCOPE_EVIDENCE_MISSING'
        lot_results = [entry['result'] for entry in evidence if entry.get('source') == 'list_incident_lots'
                       and isinstance(entry.get('result'), dict)
                       and entry['result'].get('scope_id') == state.get('scope_id')]
        wafer_results = [entry['result'] for entry in evidence if entry.get('source') == 'list_incident_wafers'
                         and isinstance(entry.get('result'), dict)
                         and entry['result'].get('scope_id') == state.get('scope_id')]
        if state.get('incident_lookup_status') == 'NEEDS_SELECTION':
            selection_status = 'NEEDS_SELECTION'
        elif confirmed and active_find.get('scope_mode') == 'cohort':
            selection_status = 'COHORT'
        elif confirmed:
            selection_status = 'SELECTED'
        elif state.get('incident_lookup_status') == 'NO_MATCH':
            selection_status = 'NO_MATCH'
        else:
            selection_status = 'NONE'
        final_scope = {
            'request': {'incident_number': incident_number},
            'confirmed': {'incident_ids': [row['incident_id'] for row in confirmed], 'incidents': confirmed,
                          'selected': bool(confirmed and state.get('scope_valid')),
                          'selection_status': selection_status},
            'incident_lookup_status': state.get('incident_lookup_status', 'NOT_QUERIED'),
            'scope_id': state.get('scope_id'), 'scope_valid': bool(state.get('scope_valid')),
            'scope_status': state.get('scope_status', 'UNVERIFIED'),
            'lot_page_collection': {'status': 'COMPLETE' if state.get('lot_lookup_complete') else
                                    ('QUERIED' if lot_results else 'NOT_QUERIED'),
                                    'result_status': lot_results[-1].get('status') if lot_results else None},
            'wafer_page_collection': {'status': 'COMPLETE' if state.get('wafer_lookup_complete') else
                                      ('QUERIED' if wafer_results else 'NOT_QUERIED'),
                                      'result_status': wafer_results[-1].get('status') if wafer_results else None,
                                      'source_completeness': wafer_results[-1].get('source_completeness') if wafer_results else None,
                                      'wafer_scope': wafer_results[-1].get('wafer_scope') if wafer_results else None}}
        limitations = list(values.get('limitations') or [])
        if state.get('scope_validation_error') and state['scope_validation_error'] not in limitations:
            limitations.append(state['scope_validation_error'])
        if 'limitations' in values or limitations:
            values['limitations'] = limitations
        return {'status': status, **values, 'scope_id': state['scope_id'], 'final_scope': final_scope,
                'request_scope': request_scope, 'as_of': as_of, 'evidence': evidence, 'events': events,
                'llm_calls': calls, 'tool_calls': limits['max_tool_calls'] - state['budget_remaining'],
                'execution_metrics': {'role_attempts': dict(role_rounds), 'provider_usage': usage,
                                      'reported_model_seconds': sum(latency) if len(latency) == calls else None,
                                      'context_phases': phases, 'recovery_categories': recoveries,
                                      'quality_assessed': False},
                'evidence_review': review_evidence(evidence, as_of, limits['timezone'])}

    def context(include_platform=False):
        references = {}
        verified = []
        for entry in evidence:
            result = entry.get('result')
            if not isinstance(result, dict):
                continue
            if entry['source'] == 'get_engineering_snapshot':
                rows = result.get('sections', {}).get('maps', {}).get('records', [])
                key = 'id'
                verified.extend(row[key] for row in rows)
            elif entry['source'] == 'search_related_incidents':
                rows, key = result.get('items', []), 'incident_number'
            else:
                continue
            for row in rows:
                references.setdefault(row[key], []).append(entry['id'])
        result = {**state, 'available_tools': catalog, 'evidence_ids': [item['id'] for item in evidence],
                'platform_identifiers': [row['incident_number'] for entry in evidence
                                         for result in [entry.get('result')]
                                         if isinstance(result, dict)
                                         for row in result.get('data', result.get('items', []))
                                         if isinstance(row, dict) and isinstance(row.get('incident_number'), str)],
                'historical_reference_evidence': references,
                'synthetic_action_evidence': [
                    {'evidence_id': entry['id'], 'result': entry['result']}
                    for entry in evidence if entry['source'] == 'plan_synthetic_action_evidence'],
                'verified_historical_reference_ids': list(dict.fromkeys(verified)),
                'mapped_fields': [k for k, v in settings.data['tables']['incident']['columns'].items() if v],
                'skills_root': settings.data['paths']['skills_root'],
                'registry_file': settings.data['paths']['registry_file'],
                'platform_facts': [], 'platform_investigations': []}
        if include_platform:
            from platform_facts import build_platform_facts
            from investigation_plans import build_investigations
            result['platform_facts'] = build_platform_facts(evidence)
            result['platform_investigations'] = build_investigations(settings, evidence)
        return result

    def advertised_tools():
        nonlocal db
        visible = {name: {key: value for key, value in spec.items() if key != 'parameters'}
                   for name, spec in catalog.items()}
        workflow_tools = requested_tools | {'find_incidents'}
        if 'plan_synthetic_action_evidence' in requested_tools:
            workflow_tools.update({'list_incident_lots', 'list_incident_wafers'})
        if 'search_similar_fbm' in requested_tools:
            workflow_tools.update({'list_incident_lots', 'list_incident_wafers', 'search_related_incidents'})
        if requested_tools & {'get_platform_evidence', 'search_platform_history', 'list_incident_wafers',
                              'list_comparison_assets', 'compare_sem_images', 'compare_overlay_maps'}:
            workflow_tools.add('list_incident_lots')
        if requested_tools & {'compare_sem_images', 'compare_overlay_maps'}:
            workflow_tools.add('list_comparison_assets')
        for name, spec in visible.items():
            if requested_tools and name not in workflow_tools:
                spec['enabled'] = False
            if incident_number is not None and not state['scope_valid']:
                spec['enabled'] = name == 'find_incidents'
            if requested_tools and state['scope_valid'] and spec['stage'] == 'incident':
                spec['enabled'] = False
            if request_scope == 'incident' and not state['scope_valid'] and spec['stage'] == 'tools':
                spec['enabled'] = False
            if not state['detail_scope_valid'] and spec['stage'] == 'tools':
                spec['enabled'] = False
            if name == 'plan_synthetic_action_evidence':
                ready_for_planner = (state['scope_valid'] and state['incident_checked']
                                     and state['detail_scope_valid'] and state['planner_lot_pages_complete']
                                     and state['planner_wafer_pages_complete'])
                spec['enabled'] = bool(spec['enabled'] and ready_for_planner)
                spec['phase_gate'] = ('ready' if ready_for_planner else
                                      'incident_scope_and_complete_lot_wafer_lookup_required')
            if name == 'search_similar_fbm':
                spec['enabled'] = bool(spec['enabled'] and fbm_source_wafers() is not None and lot_checked)
            if name in retrieval_tools and spec['enabled']:
                if request_scope != 'incident' or not state['scope_valid']:
                    spec['enabled'] = False
                else:
                    if db is None:
                        db = resources.enter_context(open_incident_tools(settings))
                    spec['enabled'] = bool(db._scope(actor, state['scope_id'])['ids'])
            if name in {'list_incident_wafers', 'list_comparison_assets', 'compare_sem_images', 'compare_overlay_maps',
                        'get_platform_evidence', 'search_platform_history'} and not lot_checked:
                spec['enabled'] = False
            if name == 'list_incident_lots' and state['lot_lookup_complete']:
                spec['enabled'] = False
            if name == 'list_incident_wafers' and state['wafer_lookup_complete']:
                spec['enabled'] = False
            if name in {'compare_sem_images', 'compare_overlay_maps'}:
                modality = 'sem' if name == 'compare_sem_images' else 'overlay'
                assets = {entry['arguments']['item']: [asset['asset_id'] for asset in entry['result']['assets']]
                          for entry in evidence if entry['source'] == 'list_comparison_assets'
                          and entry['arguments']['modality'] == modality}
                spec['asset_ids_by_item'] = {item: ids for item, ids in assets.items() if len(ids) >= 2}
                if not spec['asset_ids_by_item']:
                    spec['enabled'] = False
            if requested_tools and name in requested_tools and any(entry['source'] == name for entry in evidence):
                spec['enabled'] = False
            if requested_tools and name == 'list_comparison_assets':
                discovered = {entry['arguments']['modality'] for entry in evidence
                              if entry['source'] == 'list_comparison_assets'}
                spec['modalities'] = [modality for modality, tool in (
                    ('sem', 'compare_sem_images'), ('overlay', 'compare_overlay_maps'))
                    if tool in requested_tools and modality not in discovered]
                if not spec['modalities']:
                    spec['enabled'] = False
        return visible

    def fingerprint(arguments):
        return json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(',', ':'))

    def add_analysis_fields(arguments, intents):
        if not set(intents).intersection({'analysis', 'action'}):
            return arguments
        mapped = set(context()['mapped_fields'])
        fields = list(arguments.get('fields', []))
        for field in analysis_fields:
            if field in mapped and field not in fields:
                fields.append(field)
        return {**arguments, 'fields': fields} if fields != arguments.get('fields', []) else arguments

    def complete_detail_pages(name, arguments, result):
        """Mark detail lookup complete only when every stable page is present in order."""
        if name not in ('list_incident_lots', 'list_incident_wafers'):
            return False
        pages = [(entry['arguments'], entry['result']) for entry in evidence if entry['source'] == name]
        pages.append((arguments, result))
        kind = 'wafers' if name == 'list_incident_wafers' else 'lots'
        if not detail_pages_complete([page for _, page in pages], kind):
            return False
        if name == 'list_incident_wafers':
            if not state['planner_lot_pages_complete']:
                return False
            known_lots = {row['lot_id'] for entry in evidence if entry['source'] == 'list_incident_lots'
                          for row in entry['result'].get('items', [])}
            requested = arguments.get('lot_ids')
            if requested and not known_lots.issubset(set(requested)):
                return False
        return True

    def latest_lookup_chain(name):
        """Return only the latest offset-zero membership chain in the active scope."""
        entries = [(index, entry) for index, entry in enumerate(evidence)
                   if entry.get('source') == name
                   and entry.get('result', {}).get('scope_id') == state.get('scope_id')]
        starts = [(index, entry) for index, entry in entries
                  if entry.get('arguments', {}).get('offset', 0) == 0]
        if not starts:
            return None
        start_index, first = starts[-1]
        membership = {key: value for key, value in first.get('arguments', {}).items()
                      if key not in ('offset', 'page_size')}
        chain = []
        for index, entry in entries:
            if index < start_index:
                continue
            arguments = entry.get('arguments', {})
            current = {key: value for key, value in arguments.items()
                       if key not in ('offset', 'page_size')}
            if current == membership:
                chain.append((arguments, entry.get('result', {})))
        if not lookup_chain_finished(name, chain, state.get('scope_id')):
            return None
        return chain

    def fbm_source_wafers():
        """Validate complete current Lot/Wafer membership chains for FBM source queries."""
        nonlocal db
        if not (state['scope_valid'] and state['incident_checked'] and state['detail_scope_valid']
                and state['lot_lookup_complete'] and state['wafer_lookup_complete']):
            return None
        lot_chain = latest_lookup_chain('list_incident_lots')
        wafer_chain = latest_lookup_chain('list_incident_wafers')
        if not lot_chain or not wafer_chain:
            return None
        lot_pages = [page for _, page in lot_chain]
        wafer_pages = [page for _, page in wafer_chain]
        if db is None:
            db = resources.enter_context(open_incident_tools(settings))
        current_ids = set(db._scope(actor, state['scope_id'])['ids'])
        if not current_ids:
            return None
        def common_metadata(pages, fields):
            first = pages[0]
            signature = tuple(first.get(field) for field in fields)
            return all(tuple(page.get(field) for field in fields) == signature for page in pages)
        if (not common_metadata(lot_pages, ('scope_id', 'source_completeness', 'mapping_version',
                                            'coverage', 'status'))
                or not common_metadata(wafer_pages, ('scope_id', 'wafer_scope', 'source_completeness',
                                                     'mapping_version', 'coverage', 'lot_coverage',
                                                     'lots_without_wafer_rows', 'status'))
                or lot_pages[0].get('scope_id') != state['scope_id']
                or wafer_pages[0].get('scope_id') != state['scope_id']
                or not isinstance(lot_pages[0].get('source_completeness'), str)
                or not lot_pages[0]['source_completeness'].strip()
                or not isinstance(wafer_pages[0].get('source_completeness'), str)
                or not wafer_pages[0]['source_completeness'].strip()
                or wafer_pages[0].get('wafer_scope') not in ('incident_affected', 'lot_inventory')):
            return None
        if (any(page.get('status') not in ('OK', 'PARTIAL') for page in lot_pages)
                or any(not isinstance(page.get('coverage'), list) for page in lot_pages)
                or any(not isinstance(row, dict) or row.get('incident_id') not in current_ids
                       or not isinstance(row.get('state'), str) or not row['state']
                       for page in lot_pages for row in page.get('coverage', []))):
            return None
        wafer_scope = wafer_pages[0].get('wafer_scope')
        if wafer_scope == 'incident_affected':
            if (any(page.get('status') not in ('OK', 'PARTIAL') for page in wafer_pages)
                    or any(not isinstance(page.get('coverage'), list)
                           for page in wafer_pages)
                    or any(not isinstance(row, dict) or row.get('incident_id') not in current_ids
                           or not isinstance(row.get('state'), str) or not row['state']
                           for page in wafer_pages for row in page.get('coverage', []))):
                return None
        else:
            if (any(page.get('status') not in ('OK', 'PARTIAL') for page in wafer_pages)
                    or any(not isinstance(page.get('coverage'), list)
                           for page in wafer_pages)
                    or any(not isinstance(row, dict) or row.get('incident_id') not in current_ids
                           or not isinstance(row.get('state'), str) or not row['state']
                           for page in wafer_pages for row in page.get('coverage', []))):
                return None
        lot_pairs = {(row.get('incident_id'), row.get('lot_id'))
                     for page in lot_pages for row in page.get('items', []) if isinstance(row, dict)}
        if (not current_ids or any(not isinstance(incident_id, str) or incident_id not in current_ids
                                   or not isinstance(lot_id, str) or not lot_id
                                   for incident_id, lot_id in lot_pairs)):
            return None
        wafer_rows = [row for page in wafer_pages for row in page.get('items', []) if isinstance(row, dict)]
        if any((row.get('incident_id'), row.get('lot_id')) not in lot_pairs
               or not isinstance(row.get('wafer_id'), str) or not row.get('wafer_id')
               for row in wafer_rows):
            return None
        registered = {(row['incident_id'], row['lot_id'], row['wafer_id']) for row in wafer_rows}
        if len(registered) != sum(len(page.get('items', [])) for page in wafer_pages):
            return None
        return {'registered_wafers': registered, 'wafer_scope': wafer_scope,
                'source_completeness': wafer_pages[0]['source_completeness'],
                'lot_coverage': lot_pages[0]['coverage'],
                'wafer_coverage': wafer_pages[0]['coverage']}

    def lookup_pages_finished(name, arguments, result):
        """Track whether the current membership query's offset chain reached its end."""
        if name not in ('list_incident_lots', 'list_incident_wafers'):
            return False
        current_membership = {key: value for key, value in arguments.items()
                              if key not in ('offset', 'page_size')}
        pages = []
        for entry in evidence:
            if entry['source'] != name:
                continue
            prior = entry.get('arguments', {})
            prior_membership = {key: value for key, value in prior.items()
                                if key not in ('offset', 'page_size')}
            if prior_membership == current_membership:
                pages.append((prior, entry.get('result', {})))
        # A fresh offset-zero request starts a distinct chain, including after a filter change.
        last_start = max((index for index, (prior, _) in enumerate(pages)
                          if prior.get('offset', 0) == 0), default=0)
        if arguments.get('offset', 0) == 0:
            pages = []
        elif pages:
            pages = pages[last_start:]
        pages.append((arguments, result))
        return lookup_chain_finished(name, pages, state.get('scope_id'))

    def observe(call_id, result):
        if call_id is None:
            history.append({'role': 'user', 'content': json.dumps({'plan_result': result}, ensure_ascii=False, separators=(',', ':'))})
            return
        history.append({'role': 'tool', 'tool_call_id': call_id,
                        'content': json.dumps(result, ensure_ascii=False, separators=(',', ':'))})

    def invalidate_scope(keep_pending=False):
        nonlocal lot_checked
        state.update(scope_id=None, scope_valid=False, incident_checked=False, judge=None, detail_scope_valid=True)
        state.update(scope_status='UNVERIFIED', scope_validation_error=None)
        state.update(incident_evidence_complete=False, completed_tool=None, completed_tool_arguments=None, lookup_intents=[])
        state['incident_lookup_status'] = 'NOT_QUERIED'
        state.update(lot_lookup_complete=False, wafer_lookup_complete=False)
        state.update(planner_lot_pages_complete=False, planner_wafer_pages_complete=False)
        evidence.clear()
        topics.discard('terminology')
        lot_checked = False
        # The pending call still needs its matching tool response, even after failure.
        history[:] = history[-1:] if keep_pending and history and history[-1]['role'] == 'assistant' else []

    def retire_retrieval_failures_after_confirmed_membership_change(previous_ids, new_ids):
        # Only an explicit, resolved incident selection can retire failures. A refreshed scope
        # containing the same incident membership keeps the failure and its requery obligation.
        state['retrieval_failures'] = failures_after_confirmed_membership_change(
            state['retrieval_failures'], previous_ids, new_ids)

    def ask(role):
        nonlocal calls
        if calls >= limits['max_agent_steps']:
            raise LLMError('AGENT_STEP_LIMIT')
        prompt = compile_prompt(role, sorted(topics), settings=settings, shared_topics=True,
                                include_schema_json=role == 'router',
                                platform_review=role != 'router' and any(entry['source'] == 'get_platform_evidence' for entry in evidence),
                                tool_names=set(advertised_tools()) if role != 'router' else {
                                    name for name,spec in advertised_tools().items() if spec['enabled']})
        if role == 'router':
            topics.update(prompt['topics'])
        routed_evidence = [map_prompt_evidence(entry) for entry in evidence]
        if role == 'router' and requested_tools:
            # Routing needs identifiers and retrieval state; review retains the source content.
            summarized = {'get_engineering_snapshot', 'search_meeting_minutes',
                          'compare_sem_images', 'compare_overlay_maps', 'get_platform_evidence', 'search_platform_history'}
            routed_evidence = [{**entry, 'result': {
                key: value for key, value in entry['result'].items()
                if key in ('status', 'limitations', 'count', 'total', 'next_offset',
                           'complete', 'truncated', 'candidate_count', 'partial', 'has_more', 'row_count')}, 'routing_only': True}
                if entry['source'] in summarized else entry for entry in evidence]
        advertised = advertised_tools()
        payload = {'question': question, **state, 'evidence': routed_evidence,
                   'evidence_ids': [item['id'] for item in evidence],
                   'available_tools': advertised,
                   'mapped_fields': context()['mapped_fields'],
                   'loaded_topics': prompt['topics'], 'available_topics': prompt['available_topics']}
        if role == 'router':
            mes_spec = advertised.get('search_mes_reference')
            mes_config = settings.data.get('mes_reference', {})
            if (mes_spec and mes_spec.get('enabled') is True
                    and mes_config.get('enabled') is True and callable(mes_reference_query)):
                kinds = mes_allowed_kinds()
                synthetic_config = mes_config.get('synthetic_sqlite')
                filter_columns = (synthetic_config.get('filter_columns')
                                  if isinstance(synthetic_config, dict) else None)
                valid_synthetic_config = isinstance(synthetic_config, dict)
                valid_filter_keys = (filter_columns is None or isinstance(filter_columns, dict)
                                     and len(filter_columns) <= 32
                                     and all(isinstance(key, str) and len(key) <= 64
                                             and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', key)
                                             for key in filter_columns))
                if kinds is not None and valid_synthetic_config and valid_filter_keys:
                    payload['mes_reference_catalog'] = {
                        'allowed_kinds': list(kinds),
                        'allowed_filter_keys': sorted(filter_columns) if isinstance(filter_columns, dict) else [],
                    }
        if incident_number is not None:
            payload['selected_incident_number'] = incident_number
        if requested_tools:
            # A bounded Tool workflow does not need schemas for unimplemented retrieval paths.
            tool_topics = topics | {TOOL_TOPICS[name] for name, spec in catalog.items()
                                    if spec['enabled'] and name in TOOL_TOPICS}
            payload['available_topics'] = [topic for topic in prompt['available_topics'] if topic in tool_topics]
        if role != 'answer':
            payload.pop('inspection_requested')
        else:
            payload['historical_reference_evidence'] = context()['historical_reference_evidence']
            payload['verified_historical_reference_ids'] = context()['verified_historical_reference_ids']
        payload['pending_requested_tools'] = sorted(requested_tools - {entry['source'] for entry in evidence})
        payload['review_rounds_remaining'] = max(0, limits['max_answer_revisions'] - revisions)
        payload['incomparable_evidence_ids'] = [entry['id'] for entry in evidence
                                               if isinstance(entry['result'], dict)
                                               and entry['result'].get('status') == 'INCOMPARABLE']
        if role_contexts[role] is not None:
            payload['context_data_unverified'] = role_contexts[role]
        if role in ('judge', 'answer'):
            payload['synthetic_action_provenance_and_assumptions'] = context()['synthetic_action_evidence']
        if role in ('judge', 'answer'):
            try:
                review = review_evidence(evidence, as_of, limits['timezone'])
            except Exception:
                retrieval_entries = [entry for entry in evidence if entry.get('source') in retrieval_tools]
                if not retrieval_entries:
                    raise
                for entry in retrieval_entries:
                    mark_retrieval_failure(entry['source'], entry.get('arguments', {}))
                raise ToolError('RETRIEVAL_EVIDENCE_REVIEW_FAILED') from None
            # Review checks all original records; avoid serializing repeated lineage per raw row.
            seen_groups = set()
            records = []
            for record in review['records']:
                group = (record['evidence_id'], record['kind'])
                if group not in seen_groups:
                    records.append(record)
                    seen_groups.add(group)
            payload['evidence_review'] = {**review, 'records': records,
                'source_groups': review['source_groups'][:20],
                'record_count_in_original': len(review['records']),
                'source_group_count_in_original': len(review['source_groups']), 'prompt_sampled': True}
            if any(entry['source'] == 'get_platform_evidence' for entry in evidence):
                from platform_facts import PLATFORM_LIMITATIONS
                has_platform_evidence = any(entry['source'] == 'get_platform_evidence' for entry in evidence)
                platform_context = context(include_platform=has_platform_evidence)
                payload['platform_facts'] = platform_context['platform_facts']
                payload['platform_limitations'] = PLATFORM_LIMITATIONS
                payload['platform_investigations'] = platform_context['platform_investigations']
            # Keep observations once in evidence_focus; canonical Tool evidence stays intact.
            payload['evidence'] = [
                {**entry, 'result': {key: value for key, value in entry['result'].items()
                                     if key != 'observations'}}
                if entry['source'] == 'get_engineering_snapshot' else map_prompt_evidence(entry) for entry in evidence]
            payload['evidence_focus'] = [
                {'evidence_id': entry['id'], 'source': entry['source'],
                 'observations': entry['result'].get('observations'),
                 **{key: entry['result'][key] for key in
                    ('status', 'findings', 'model', 'model_version', 'asset_ids', 'limitations')
                    if key in entry['result']}}
                for entry in evidence if entry['source'] in
                ('get_engineering_snapshot', 'compare_sem_images', 'compare_overlay_maps')]
        payload['evidence'] = [map_prompt_evidence(entry) for entry in payload['evidence']]
        if role == 'answer' and payload.get('platform_facts'):
            # Final synthesis needs reviewed facts, hypotheses and limits, not duplicate SQL rows/contracts.
            notes = [{'evidence_id': entry['id'], 'notes': [{'content': row['content']} for row in
                      entry['result'].get('sections', {}).get('inform', {}).get('rows', [])[:2]]}
                     for entry in evidence if entry['source'] == 'get_platform_evidence']
            keep = ('question', 'as_of', 'selected_incident_number', 'evidence_ids', 'platform_facts',
                    'platform_limitations', 'platform_investigations', 'judge', 'last_error', 'inspection_requested')
            payload = {key: payload[key] for key in keep if key in payload}
            payload['inform_context'] = notes
            document_context = document_answer_context(evidence, review)
            if document_context is not None:
                payload.update(document_context)
            mes_context = mes_reference_answer_context(evidence, review)
            if mes_context is not None:
                payload.update(mes_context)
        role_rounds[role] += 1
        policy = limits.get('context_management', {'enabled': False})
        if role == 'router' and policy.get('enabled') is True:
            # Only code creates this attestation, from full canonical Tool results.
            # It proves retained record identity, not evidence truth/completeness.
            try:
                payload['evidence_manifest'] = [
                    {'id': entry['id'], 'source': entry['source'], 'result_sha256': hashlib.sha256(
                        json.dumps(entry['result'], ensure_ascii=False, sort_keys=True,
                                   separators=(',', ':'), allow_nan=False).encode()).hexdigest()}
                    for entry in evidence]
            except (TypeError, ValueError, OverflowError):
                payload.pop('evidence_manifest', None)
        if state['last_error'] is None and state['code_gate'] == 'PASS':
            state.pop('recovery', None)
            payload.pop('recovery', None)
        # This concrete transport always sends the complete Router output schema
        # through json_schema or submit_plan. Custom clients retain embedded schema.
        transport_contract = type(client) is RoleClient and role == 'router'
        selection = select_context(role, role_rounds[role], payload,
                                   history if role == 'router' else [], policy,
                                   transport_contract=transport_contract,
                                   force_full=bool(state.get('recovery', {}).get('force_full_context')))
        if selection['omit_examples'] or selection['omit_embedded_output_schema']:
            prompt = compile_prompt(role, sorted(topics), settings=settings, shared_topics=True,
                                    include_schema_json=True,
                                    tool_names={name for name,spec in advertised_tools().items() if spec['enabled']},
                                    context_phase='continuation', omit_examples=selection['omit_examples'],
                                    omit_embedded_output_schema=selection['omit_embedded_output_schema'])
        payload['runtime_context'] = {'phase': selection['phase'], 'role_round': role_rounds[role],
                                      'output_schema_in_transport': transport_contract,
                                      'core_and_role_instructions_retained': True}
        request_history = selection['history'] if selection['phase'] == 'continuation' else history
        if role != 'router':
            request_history = []
        request_history_size = len(request_history)
        calls += 1
        llm_call_id = f'{run_id}:{calls}'
        prompt_characters = len(prompt['system_prompt'])
        payload_characters = len(json.dumps(payload, ensure_ascii=False, separators=(',', ':')))
        event('llm_start', call_id=llm_call_id, role=role, step=calls, release=prompt['release'],
              model=settings.model_profile(role)['deployment']['served_model'],
              prompt_sha256=prompt['prompt_sha256'], loaded_files=prompt['loaded_files'],
              skill_dependencies=prompt['dependency_order'], context=selection['metrics'],
              system_prompt_characters=prompt_characters,
              payload_characters=payload_characters,
              output_schema_in_transport=transport_contract,
              **({'conversation_memory': memory_metrics[role]} if role in memory_metrics else {}))
        try:
            try:
                output, call_id = client.call(role, prompt['system_prompt'], payload, request_history)
            finally:
                # RoleClient appends the new assistant message to its history arg.
                # Retain that delta in canonical history before observe adds receipt.
                if role == 'router' and selection['phase'] == 'continuation':
                    history.extend(copy.deepcopy(request_history[request_history_size:]))
        except LLMError:
            event('llm_metrics', call_id=llm_call_id, role=role,
                  system_prompt_characters=prompt_characters, payload_characters=payload_characters,
                  metrics=getattr(client, 'last_metrics', {}))
            raise
        event('llm_output', call_id=llm_call_id, role=role,
              system_prompt_characters=prompt_characters, payload_characters=payload_characters,
              output=output, metrics=getattr(client, 'last_metrics', {}))
        return output, call_id

    with ExitStack() as resources:
        db = None
        images = None
        try:
            # Validate all roles before any external request or DB connection.
            for role in ('router', 'judge', 'answer'):
                compile_prompt(role, sorted(topics), settings=settings, shared_topics=True)
            client = RoleClient(settings)
            paths = settings.data['paths']
            all_tools = read_role_reference('router', 'tools.json', paths['skills_root'], paths['registry_file'])
            image_methods = {'list_comparison_assets', 'compare_sem_images', 'compare_overlay_maps'}
            document_tools = {'search_engineer_notes': 'engineer_notes',
                              'search_internal_documents': 'internal_documents'}
            retrieval_tools = set(document_tools) | {'search_mes_reference', 'plan_synthetic_action_evidence', 'search_similar_fbm'}
            implemented = {'match_incident_values', 'find_incidents', 'summarize_incidents', 'list_incident_lots', 'list_incident_wafers', 'search_meeting_minutes', 'get_engineering_snapshot', 'search_related_incidents'} | image_methods | retrieval_tools
            implemented.update(('get_platform_evidence', 'search_platform_history'))
            if set(all_tools) - implemented:
                raise ValueError('UNIMPLEMENTED_TOOL_IN_CATALOG')

            planner_enabled = (settings.data.get('synthetic_action_planner', {}).get('enabled') is True
                               and callable(synthetic_action_planner)
                               and callable(snapshot_lease_provider))

            def document_top_k(source_kind, arguments):
                source = settings.data.get('retrieval', {}).get(source_kind, {})
                cap = source.get('top_k')
                if isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= 100:
                    raise ToolError('INVALID_DOCUMENT_TOP_K_CONFIG')
                value = arguments.get('top_k', cap)
                if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= cap:
                    raise ToolError('INVALID_DOCUMENT_TOP_K')
                return value

            def document_requires_content_kind(source_kind):
                retrieval = settings.data.get('retrieval', {})
                source = retrieval.get(source_kind, {}) if isinstance(retrieval, dict) else None
                if not isinstance(source, dict):
                    raise ToolError('INVALID_DOCUMENT_CONTENT_KIND_CONFIG')
                required = source.get('require_content_kind', False)
                if type(required) is not bool:
                    raise ToolError('INVALID_DOCUMENT_CONTENT_KIND_CONFIG')
                return required

            def document_statuses(source_kind):
                statuses = (document_allowed_statuses.get(source_kind)
                            if isinstance(document_allowed_statuses, dict) else None)
                if (not isinstance(statuses, (list, tuple)) or not statuses or len(statuses) > 100
                        or any(not isinstance(value, str) or not value.strip() for value in statuses)
                        or any(len(value) > 256 for value in statuses if isinstance(value, str))
                        or len(set(statuses)) != len(statuses)):
                    return None
                return statuses

            def historical_document_ids(current_ids):
                current = set(current_ids)
                found = []
                for entry in evidence:
                    if entry.get('source') != 'search_related_incidents':
                        continue
                    result = entry.get('result')
                    if not isinstance(result, dict) or result.get('status') not in ('OK', 'NO_MATCH'):
                        continue
                    items = result.get('items')
                    if not isinstance(items, list):
                        continue
                    for item in items:
                        if not isinstance(item, dict):
                            continue
                        incident_id = item.get('incident_id')
                        if (isinstance(incident_id, str) and incident_id.strip()
                                and incident_id not in current and incident_id not in found):
                            found.append(incident_id)
                return found

            def mes_allowed_kinds():
                kinds = settings.data.get('mes_reference', {}).get('allowed_kinds')
                if (not isinstance(kinds, (list, tuple)) or not kinds
                        or any(not isinstance(kind, str) or not kind.strip() or len(kind) > 64 for kind in kinds)
                        or len(set(kinds)) != len(kinds)):
                    return None
                return kinds

            def mes_top_k(arguments):
                cap = settings.data.get('mes_reference', {}).get('top_k')
                if isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= 100:
                    raise ToolError('INVALID_MES_REFERENCE_TOP_K_CONFIG')
                value = arguments.get('top_k', cap)
                if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= cap:
                    raise ToolError('INVALID_MES_REFERENCE_TOP_K')
                return value

            def validate_mes_arguments(arguments):
                if set(arguments) - {'kind', 'query', 'top_k', 'filters'}:
                    raise ToolError('MES_REFERENCE_ARGUMENTS_FORBIDDEN')
                kinds = mes_allowed_kinds()
                kind = arguments.get('kind')
                if kinds is None or not isinstance(kind, str) or kind not in kinds:
                    raise ToolError('MES_REFERENCE_KIND_UNAVAILABLE')
                query = arguments.get('query')
                if not isinstance(query, str) or not 1 <= len(query) <= 512 or not query.strip():
                    raise ToolError('INVALID_MES_REFERENCE_QUERY')
                filters = arguments.get('filters')
                if 'filters' not in arguments:
                    filters = {}
                elif not isinstance(filters, dict) or not filters or len(filters) > 5:
                    raise ToolError('INVALID_MES_REFERENCE_FILTERS')
                for key, value in filters.items():
                    if (not isinstance(key, str) or len(key) > 64
                            or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', key)
                            or not isinstance(value, str) or not value.strip()
                            or value != value.strip() or len(value) > 128):
                        raise ToolError('INVALID_MES_REFERENCE_FILTERS')
                filter_columns = settings.data.get('mes_reference', {}).get('synthetic_sqlite', {}).get('filter_columns')
                if filters:
                    if (not isinstance(filter_columns, dict)
                            or set(filters) - set(filter_columns)):
                        raise ToolError('MES_REFERENCE_FILTER_UNAVAILABLE')
                return kind, query, mes_top_k(arguments), filters

            def available(scope):
                if scope == 'auto':
                    return {}
                result = {name: dict(spec) for name, spec in all_tools.items()
                          if scope == 'incident' or name == 'search_meeting_minutes'}
                if 'match_incident_values' in result and not settings.data['value_matching']['enabled']:
                    result['match_incident_values']['enabled'] = False
                if 'get_engineering_snapshot' in result:
                    result['get_engineering_snapshot']['enabled'] = callable(engineering_query)
                for name in ('get_platform_evidence', 'search_platform_history'):
                    if name in result:
                        result[name]['enabled'] = bool(settings.data.get('platform', {}).get('enabled'))
                if 'search_related_incidents' in result:
                    result['search_related_incidents']['enabled'] = bool(related_search)
                for tool_name, source_kind in document_tools.items():
                    if tool_name in result:
                        source = settings.data.get('retrieval', {}).get(source_kind, {})
                        statuses = document_statuses(source_kind)
                        result[tool_name]['enabled'] = bool(
                            callable(document_query) and source.get('enabled') is True
                            and statuses is not None
                        )
                if 'search_mes_reference' in result:
                    mes_config = settings.data.get('mes_reference', {})
                    result['search_mes_reference']['enabled'] = bool(
                        mes_config.get('enabled') is True and callable(mes_reference_query)
                        and mes_allowed_kinds() is not None
                    )
                if 'search_similar_fbm' in result:
                    result['search_similar_fbm']['enabled'] = bool(
                        settings.data.get('fbm_search', {}).get('enabled') is True
                        and callable(fbm_search_query))
                if 'plan_synthetic_action_evidence' in result:
                    planner = result['plan_synthetic_action_evidence']
                    planner['configured'] = settings.data.get('synthetic_action_planner', {}).get('enabled') is True
                    planner['runtime_injected'] = bool(callable(synthetic_action_planner)
                                                       and callable(snapshot_lease_provider))
                    planner['enabled'] = planner_enabled
                    planner['phase_gate'] = ('incident_scope_and_complete_lot_wafer_lookup_required'
                                             if planner_enabled else 'disabled_or_trusted_runtime_not_injected')
                if 'search_meeting_minutes' in result:
                    result['search_meeting_minutes']['enabled'] = bool(result['search_meeting_minutes']['enabled'] and settings.data['meetings']['enabled'])
                    result['search_meeting_minutes']['stage'] = 'tools' if scope == 'incident' else 'independent'
                for name in image_methods & result.keys():
                    config = settings.data['image_tools']
                    enabled = (any(item['enabled'] for item in config.values()) if name == 'list_comparison_assets'
                               else config['sem' if name == 'compare_sem_images' else 'overlay']['enabled'])
                    result[name]['enabled'] = bool(result[name]['enabled'] and enabled)
                return result

            catalog = available(request_scope)
            if requested_tools - {name for name, spec in catalog.items() if spec['enabled']}:
                raise ValueError('REQUESTED_TOOL_UNAVAILABLE')

            def invoke(name, **arguments):
                nonlocal db, images, next_evidence, lot_checked
                if state['budget_remaining'] <= 0:
                    raise ToolError('TOOL_BUDGET_EXCEEDED')
                if any(key in arguments for key in ('actor', 'scope_id', 'incident_ids', 'as_of')):
                    raise ToolError('CALLER_IDENTITY_ARGUMENT_FORBIDDEN')
                if request_scope == 'auto' or name not in catalog or not catalog[name]['enabled']:
                    raise ToolError('TOOL_UNAVAILABLE')
                if name == 'find_incidents' and incident_number is not None:
                    if arguments.get('incident_number') != incident_number or set(arguments) - {'incident_number', 'fields'}:
                        raise ValueError('SELECTED_INCIDENT_LOOKUP_ONLY: use the selected incident number without inferred filters')
                if request_scope == 'incident' and name not in ('find_incidents', 'summarize_incidents', 'match_incident_values') and not state['scope_valid']:
                    raise ToolError('INCIDENT_SCOPE_REQUIRED')
                if (name in ('list_incident_wafers', 'get_platform_evidence', 'search_platform_history') or name in image_methods) and not lot_checked:
                    raise ToolError('LOT_LOOKUP_REQUIRED')
                state['budget_remaining'] -= 1
                if name != 'search_meeting_minutes' and db is None:
                    db = resources.enter_context(open_incident_tools(settings))
                if name == 'plan_synthetic_action_evidence':
                    if arguments:
                        raise ToolError('SYNTHETIC_ACTION_ARGUMENTS_FORBIDDEN')
                    if not (planner_enabled and state['scope_valid'] and state['incident_checked']
                            and state['detail_scope_valid'] and state['planner_lot_pages_complete']
                            and state['planner_wafer_pages_complete']):
                        raise ToolError('SYNTHETIC_ACTION_SCOPE_INCOMPLETE')
                    try:
                        from action_scope_bridge import build_scoped_action_input
                        from synthetic_action_contract import validate_planner_result
                        scoped = build_scoped_action_input(
                            db, actor, state['scope_id'], snapshot_lease_provider=snapshot_lease_provider,
                            page_size=limits['max_page_size'])
                        if scoped['as_of'].astimezone(ZoneInfo(limits['timezone'])).date().isoformat() != as_of:
                            raise ValueError('snapshot cutoff mismatch')
                        proposed = synthetic_action_planner(copy.deepcopy(scoped))
                        result = validate_planner_result(proposed, scoped, as_of, limits['timezone'])
                    except Exception:
                        mark_retrieval_failure(name, arguments)
                        raise ToolError('SYNTHETIC_ACTION_PLANNER_FAILED') from None
                elif name == 'get_engineering_snapshot':
                    ids = list(db._scope(actor, state['scope_id'])['ids'])
                    result = engineering_query(actor=actor, incident_ids=ids, as_of=as_of)
                    validate_snapshot_scope(result, ids, as_of, limits['timezone'])
                elif name in document_tools:
                    if set(arguments) - {'query', 'top_k'}:
                        raise ToolError('DOCUMENT_TOOL_ARGUMENTS_FORBIDDEN')
                    source_kind = document_tools[name]
                    query = arguments.get('query')
                    if not isinstance(query, str) or not query.strip() or len(query) > 12000:
                        raise ToolError('INVALID_DOCUMENT_QUERY')
                    ids = list(db._scope(actor, state['scope_id'])['ids'])
                    if request_scope != 'incident' or not state['scope_valid'] or not ids:
                        raise ToolError('INCIDENT_SCOPE_REQUIRED')
                    top_k = document_top_k(source_kind, arguments)
                    historical_ids = historical_document_ids(ids)
                    try:
                        response = document_query(source_kind=source_kind, actor=actor, incident_ids=list(ids),
                                                  historical_incident_ids=list(historical_ids), as_of=as_of,
                                                  query=arguments['query'], top_k=top_k)
                        from document_evidence_contract import validate_hybrid_response
                        result = validate_hybrid_response(
                            response, source_kind=source_kind, incident_ids=ids, as_of=as_of,
                            timezone_name=limits['timezone'], top_k=top_k,
                            historical_incident_ids=historical_ids, allowed_statuses=document_statuses(source_kind),
                            require_content_kind=document_requires_content_kind(source_kind))
                    except Exception:
                        mark_retrieval_failure(name, arguments)
                        raise ToolError('DOCUMENT_RETRIEVAL_FAILED') from None
                elif name == 'search_mes_reference':
                    kind, query, top_k, filters = validate_mes_arguments(arguments)
                    ids = list(db._scope(actor, state['scope_id'])['ids'])
                    if request_scope != 'incident' or not state['scope_valid'] or not ids:
                        raise ToolError('INCIDENT_SCOPE_REQUIRED')
                    try:
                        callback_args = dict(kind=kind, actor=actor, incident_ids=list(ids),
                                             as_of=as_of, query=query, top_k=top_k)
                        if filters:
                            callback_args['filters'] = filters
                        validate_retrieval_signature(name, mes_reference_query, callback_args, arguments)
                        response = mes_reference_query(**callback_args)
                        from mes_reference_contract import validate_mes_reference_response
                        result = validate_mes_reference_response(
                            response, incident_ids=ids, as_of=as_of, timezone_name=limits['timezone'],
                            allowed_kinds=[kind], top_k=top_k)
                        if not isinstance(response, dict):
                            raise ValueError('MES response must be an object')
                        truncated = response.get('truncated')
                        candidate_count = response.get('candidate_count')
                        item_count = len(result['items'])
                        if type(truncated) is not bool:
                            raise ValueError('MES response truncated flag is invalid')
                        if (isinstance(candidate_count, bool) or not isinstance(candidate_count, int)
                                or candidate_count < item_count or (candidate_count > item_count) != truncated
                                or (result['status'] == 'NO_MATCH') != (candidate_count == 0)):
                            raise ValueError('MES response candidate count does not match truncation state')
                        result['truncated'] = truncated
                        result['candidate_count'] = candidate_count
                    except Exception:
                        mark_retrieval_failure(name, arguments)
                        raise ToolError('MES_REFERENCE_RETRIEVAL_FAILED') from None
                elif name == 'search_similar_fbm':
                    if set(arguments) - {'source_incident_id', 'lot_id', 'wafer_id', 'representation', 'top_k'}:
                        raise ToolError('FBM_ARGUMENTS_FORBIDDEN')
                    source_incident_id = arguments.get('source_incident_id')
                    lot_id, wafer_id = arguments.get('lot_id'), arguments.get('wafer_id')
                    representation = arguments.get('representation')
                    if (not all(isinstance(value, str) and value.strip()
                                for value in (source_incident_id, lot_id, wafer_id))
                            or representation not in ('raw_fbm', 'object_id_yield_fbm')):
                        raise ToolError('INVALID_FBM_QUERY')
                    fbm_config = settings.data.get('fbm_search', {})
                    cap = fbm_config.get('top_k', 5)
                    if isinstance(cap, bool) or not isinstance(cap, int) or not 1 <= cap <= 50:
                        raise ToolError('INVALID_FBM_TOP_K_CONFIG')
                    top_k = arguments.get('top_k', cap)
                    if isinstance(top_k, bool) or not isinstance(top_k, int) or not 1 <= top_k <= min(cap, 50):
                        raise ToolError('INVALID_FBM_TOP_K')
                    verified_source = fbm_source_wafers()
                    if not (fbm_config.get('enabled') is True and callable(fbm_search_query)
                            and verified_source is not None):
                        raise ToolError('FBM_SCOPE_INCOMPLETE')
                    current_ids = list(db._scope(actor, state['scope_id'])['ids'])
                    if not current_ids:
                        raise ToolError('INCIDENT_SCOPE_REQUIRED')
                    registered = verified_source['registered_wafers']
                    query_wafer = {'incident_id': source_incident_id, 'lot_id': lot_id, 'wafer_id': wafer_id}
                    if source_incident_id not in current_ids or tuple(query_wafer.values()) not in registered:
                        raise ToolError('FBM_WAFER_SCOPE_MISMATCH')
                    historical_ids = historical_document_ids(current_ids)
                    callback_args = dict(actor=actor, incident_ids=list(current_ids),
                                         historical_incident_ids=list(historical_ids), query_wafer=query_wafer,
                                         representation=representation, as_of=as_of, top_k=top_k)
                    validate_retrieval_signature(name, fbm_search_query, callback_args, arguments)
                    try:
                        response = fbm_search_query(**callback_args)
                        from fbm_search_contract import project_source_coverage, validate_fbm_response
                        result = validate_fbm_response(
                            response, query_wafer=tuple(query_wafer.values()), representation=representation,
                            current_incident_ids=current_ids, historical_incident_ids=historical_ids,
                            registered_wafers=registered, as_of=as_of,
                            timezone_name=limits['timezone'], top_k=top_k)
                        result['source_wafer_scope'] = verified_source['wafer_scope']
                        result['source_completeness'] = verified_source['source_completeness']
                        result['source_coverage'] = project_source_coverage(
                            source_incident_id, verified_source['lot_coverage'], verified_source['wafer_coverage'])
                        result['limitations'] = list(dict.fromkeys(
                            result['limitations'] + ['lot_wafer_snapshot_as_of_unverified']))
                        if verified_source['wafer_scope'] == 'lot_inventory':
                            result['limitations'] = list(dict.fromkeys(
                                result['limitations'] + ['inventory_context_only_not_incident_impact']))
                        if verified_source['source_completeness'] != 'declared_complete':
                            result['limitations'] = list(dict.fromkeys(
                                result['limitations'] + ['source_completeness_not_declared_complete']))
                    except Exception:
                        mark_retrieval_failure(name, arguments)
                        raise ToolError('FBM_RETRIEVAL_FAILED') from None
                elif name == 'search_related_incidents':
                    result = db.search_related_incidents(actor, state['scope_id'], as_of=as_of, **arguments)
                elif name in ('get_platform_evidence', 'search_platform_history'):
                    result = getattr(db, name)(actor, state['scope_id'], as_of=as_of, **arguments)
                elif name == 'search_meeting_minutes':
                    ids = list(db._scope(actor, state['scope_id'])['ids']) if request_scope == 'incident' else None
                    result = MeetingTools(settings).search(actor, incident_ids=ids, as_of=as_of, **arguments)
                elif name in image_methods:
                    if images is None:
                        images = ImageTools(settings, db)
                    result = getattr(images, name)(actor, state['scope_id'], as_of=as_of, **arguments)
                elif name == 'match_incident_values':
                    result = db.match_incident_values(actor, question)
                elif name == 'summarize_incidents':
                    if selected:
                        raise ToolError('AGGREGATE_CANNOT_USE_SELECTED_INCIDENTS')
                    invalidate_scope(keep_pending=True)
                    result = db.summarize_incidents(actor, as_of=as_of, **arguments)
                    state.update(scope_id=result['scope_id'], incident_checked=True, scope_valid=True,
                                 detail_scope_valid=result['scope_complete'])
                elif name == 'find_incidents':
                    previous_ids = (list(db._scope(actor, state['scope_id'])['ids'])
                                    if state['scope_id'] and state['scope_valid'] else None)
                    # A typo proposal is not user authorization to change a WHERE value.
                    from terminology import match_values
                    proposed = dict(arguments.get('filters') or {})
                    proposed.update({key: arguments[key] for key in ('city', 'line') if key in arguments})
                    candidate_sets = [entry['result'].get('candidates', []) for entry in evidence
                                      if entry['source'] == 'match_incident_values']
                    if not candidate_sets and settings.data['value_matching'].get('fuzzy_enabled'):
                        # Repeat the bounded DB-value validation when Router omitted the helper Tool.
                        checked = db.match_incident_values(actor, question)
                        candidate_sets = [checked['candidates']]
                        event('value_validation', source='db_unique_values', candidate_count=len(checked['candidates']))
                    for candidates in candidate_sets:
                        for candidate in candidates:
                            if not candidate.get('requires_confirmation'):
                                continue
                            value = proposed.get(candidate['field'])
                            values = value.get('values', []) if isinstance(value, dict) else [value]
                            if candidate['value'] in values and not match_values(
                                    question, {candidate['field']: [candidate['value']]}, 1)['candidates']:
                                raise ToolError('TYPO_CANDIDATE_REQUIRES_USER_CONFIRMATION')
                    # A new search invalidates previous evidence, even if it fails.
                    invalidate_scope(keep_pending=True)
                    state['incident_lookup_status'] = 'FAILED'
                    try:
                        result = db.find_incidents(actor, **arguments)
                    except Exception:
                        state['incident_lookup_status'] = 'FAILED'
                        raise
                    if len(result['data']) > 1 and not selected and arguments.get('scope_mode') != 'cohort':
                        result = {**result, 'requires_selection': True, 'status': 'NEEDS_SELECTION'}
                    if selected:
                        selection = db.select_incidents(actor, result['scope_id'], selected)
                        result = {**result, 'scope_id': selection['scope_id'], 'requires_selection': False,
                                  'status': 'OK', 'data': [r for r in result['data'] if r['incident_id'] in selected]}
                    state.update(scope_id=result['scope_id'], incident_checked=True,
                                 scope_valid=not result['requires_selection'])
                    state['incident_lookup_status'] = result.get('status', 'FAILED')
                    state['scope_status'] = ('NEEDS_SELECTION' if result['requires_selection'] else
                                             ('EMPTY' if result.get('status') == 'NO_MATCH' else 'VALID'))
                    if state['scope_valid']:
                        confirmed_ids = list(db._scope(actor, state['scope_id'])['ids'])
                        retire_retrieval_failures_after_confirmed_membership_change(previous_ids, confirmed_ids)
                else:
                    result = getattr(db, name)(actor, state['scope_id'], **arguments)
                    if name == 'list_incident_lots':
                        lot_checked = True
                    if name == 'list_incident_lots':
                        state['lot_lookup_complete'] = lookup_pages_finished(name, arguments, result)
                        state['wafer_lookup_complete'] = False
                        state['planner_lot_pages_complete'] = complete_detail_pages(name, arguments, result)
                        state['planner_wafer_pages_complete'] = False
                    elif name == 'list_incident_wafers':
                        known_lots = {row['lot_id'] for entry in evidence
                                      if entry['source'] == 'list_incident_lots'
                                      for row in entry['result']['items']}
                        requested = arguments.get('lot_ids')
                        state['wafer_lookup_complete'] = (lookup_pages_finished(name, arguments, result)
                            and (not requested or
                            (state['lot_lookup_complete'] and known_lots.issubset(set(requested)))))
                        state['planner_wafer_pages_complete'] = complete_detail_pages(name, arguments, result)
                next_evidence += 1
                item = {'id': 'e' + str(next_evidence), 'source': name, 'arguments': arguments, 'result': result}
                try:
                    item_review = review_evidence([item], as_of, limits['timezone'])
                except Exception:
                    if name in retrieval_tools:
                        mark_retrieval_failure(name, arguments)
                        raise ToolError('RETRIEVAL_EVIDENCE_REVIEW_FAILED') from None
                    raise
                if any(issue['type'] == 'after_cutoff' for issue in item_review['issues']):
                    mark_retrieval_failure(name, arguments)
                    raise ToolError('EVIDENCE_AFTER_CUTOFF')
                if any(issue['type'] == 'invalid_timestamp' for issue in item_review['issues']):
                    mark_timestamp_failure(name, arguments)
                    raise ToolError('EVIDENCE_TIMESTAMP_INVALID')
                evidence.append(item)
                if name in retrieval_tools or any(
                        failed['key'] == retrieval_request_key(name, arguments)
                        and failed.get('reason') == 'invalid_timestamp'
                        for failed in state['retrieval_failures']):
                    key = retrieval_request_key(name, arguments)
                    state['retrieval_failures'] = [failed for failed in state['retrieval_failures']
                                                   if failed['key'] != key]
                if name != 'match_incident_values':
                    state.update(code_gate='PASS', last_error=None)
                event('tool_result', **item)
                return item

            def review(call_id=None, observe_ready=False):
                nonlocal revisions
                if observe_ready:
                    observe(call_id, {'status': 'ready_for_judge', 'reason': 'IDENTICAL_COMPLETED_TOOL'})
                if state['retrieval_failures']:
                    event('judge_blocked', reason='RETRIEVAL_REQUERY_REQUIRED',
                          tools=sorted({failed['tool'] for failed in state['retrieval_failures']}))
                    return None
                if (requested_tools - {entry['source'] for entry in evidence} and state['budget_remaining'] > 0
                        and any(spec['enabled'] for spec in advertised_tools().values())):
                    return None
                if (len(evidence) == 1 and evidence[0]['source'] == 'find_incidents'
                        and evidence[0]['result']['status'] == 'NO_MATCH' and state['code_gate'] == 'PASS'
                        and state['scope_valid'] and not requested_tools - {'find_incidents'}
                        and state['lookup_intents'] and set(state['lookup_intents']) <= {'search', 'lot_list', 'wafer_list'}):
                    response = no_match_response(evidence[0])
                    event('no_match_answer_rendered', evidence_id=evidence[0]['id'])
                    return finish(response.pop('status'), **response)
                judge, _ = ask('judge')
                platform_context = context(include_platform=any(
                    entry['source'] == 'get_platform_evidence' for entry in evidence))
                validate_output('judge', judge, platform_context)
                state['judge'] = judge
                if judge['return_to'] == 'router':
                    revisions += 1
                    if revisions > limits['max_answer_revisions']:
                        return finish('unavailable', limitations=['JUDGE_REVISION_LIMIT'])
                    if judge['verdict'] == 'revise':
                        invalidate_scope()
                        state['judge'] = {**judge, 'coverage': [],
                                          'issues': [{**issue, 'evidence_ids': []} for issue in judge['issues']]}
                    return None
                for answer_attempt in range(2):
                    answer, _ = ask('answer')
                    platform_context = None
                    try:
                        has_platform_evidence = any(entry['source'] == 'get_platform_evidence' for entry in evidence)
                        platform_context = context(include_platform=has_platform_evidence)
                        if platform_context['platform_facts']:
                            answer = copy.deepcopy(answer)
                            facts_by_id = {fact['fact_id']: fact for fact in platform_context['platform_facts']}
                            chosen = answer.pop('selected_fact_ids', None)
                            if (not isinstance(chosen, list) or any(not isinstance(item, str) for item in chosen)
                                    or len(set(chosen)) != len(chosen) or set(chosen) != set(facts_by_id)):
                                raise ValueError('PLATFORM_FACT_COVERAGE_REQUIRED')
                            if answer.get('claims'):
                                raise ValueError('PLATFORM_QUANTITIES_RENDERED_BY_CODE')
                            answer['claims'] = [{'claim_id': item, 'text': facts_by_id[item]['text'],
                                                 'evidence_ids': facts_by_id[item]['evidence_ids']} for item in chosen]
                            from investigation_plans import render_investigations
                            ranked = answer.pop('ranked_investigation_ids', None)
                            interpretation_text = render_investigations(platform_context['platform_investigations'], ranked)
                            event('platform_facts_rendered', selected_fact_ids=chosen, quantitative_author='tool_adapter')
                        validate_output('answer', answer, {**platform_context, 'judge_verdict': judge['verdict']})
                        break
                    except ValueError as exc:
                        if platform_context is None or not platform_context['platform_facts'] or answer_attempt:
                            raise
                        state['last_error'] = str(exc)
                        event('answer_validation_retry', error=str(exc))
                system_limitations = list(dict.fromkeys(
                    mes_catalog_candidate_system_limitations(answer, evidence)
                    + document_retrieval_system_limitations(answer, evidence)))
                facts = platform_context['platform_facts']
                interpretation = None
                if facts and answer['status'] in ('answered', 'partial'):
                    from platform_facts import render_platform_answer
                    interpretation = interpretation_text
                    answer['answer'] = render_platform_answer(facts, [claim['claim_id'] for claim in answer['claims']], '')
                    if interpretation:
                        answer['answer'] += '\n\n' + interpretation
                if len(evidence) == 1 and evidence[0]['source'] == 'summarize_incidents' and answer['status'] in ('answered', 'partial'):
                    from incident_statistics import render_statistics
                    answer = {**answer, **render_statistics(evidence[0])}
                    event('statistics_answer_rendered', evidence_id=evidence[0]['id'])
                return finish(answer['status'], answer=answer['answer'], claims=answer['claims'],
                              limitations=answer['limitations'], judge=judge,
                              **({'system_limitations': system_limitations} if system_limitations else {}),
                              **({'platform_facts': facts, 'llm_interpretation': interpretation,
                                  'investigation_order': ranked,
                                  'answer_generation_mode': 'llm_ranking_with_tool_facts_and_frozen_skill_recipes'} if facts else {}),
                              inspection_plan=inspection_rows(answer.get('inspection_plan')))

            while calls < limits['max_agent_steps']:
                call_id = None
                observations = []
                try:
                    catalog = available(request_scope)
                    if requested_tools and state['incident_checked'] and not any(
                            spec['enabled'] for spec in advertised_tools().values()):
                        prior_calls = calls
                        result = review()
                        if result is not None:
                            return result
                        if calls == prior_calls:
                            return finish('unavailable', limitations=['RETRIEVAL_REQUERY_REQUIRED'
                                          if state['retrieval_failures'] else 'REVIEW_CANNOT_PROGRESS'])
                        continue
                    output, call_id = ask('router')
                    if isinstance(output, dict) and output.get('decision') == 'execute' and output.get('needs_skills'):
                        schema = read_role_reference('router', 'output.schema.json', paths['skills_root'], paths['registry_file'])
                        structure(output, schema)
                        requested = set(output['needs_skills'])
                        if request_scope == 'independent' and requested - {'meetings'}:
                            raise ValueError('INDEPENDENT_TOOL_TOPICS_NOT_SUPPORTED')
                        for role in ('router', 'judge', 'answer'):
                            compile_prompt(role, sorted(topics | requested), settings=settings, shared_topics=True)
                        topics |= requested
                        output = {**output, 'needs_skills': []}
                        event('skills_loaded', topics=sorted(topics))
                    validate_output('router', output, context())
                    if state['code_gate'] == 'PASS':
                        state['last_error'] = None
                    decision = output['decision']
                    if decision == 'route':
                        request_scope = output['stage']
                        state['request_scope'] = request_scope
                        catalog = available(request_scope)
                        if request_scope == 'incident':
                            topics.add('incident_search')
                        else:
                            evidence.append({'id': 'input-1', 'source': 'user_supplied_unverified', 'result': question})
                        event('route_selected', request_scope=request_scope)
                        observe(call_id, {'request_scope': request_scope})
                    elif decision == 'execute':
                        batch = output['plan']
                        if len(batch) > (4 if state['scope_valid'] and output['stage'] == 'tools' else 1):
                            raise ValueError('PLAN_BATCH_LIMIT')
                        if len(batch) > state['budget_remaining']:
                            raise ValueError('TOOL_BUDGET_EXCEEDED')
                        ready = advertised_tools()
                        prepared, seen, needed_topics = [], set(), set()
                        duplicate = False
                        # Preflight the whole batch before any side effects or Tool calls.
                        for index, step in enumerate(batch):
                            name, arguments = step['tool'], step['arguments']
                            structure(arguments, catalog[name]['parameters'], f'$.plan[{index}].arguments')
                            if step['depends_on']:
                                raise ValueError('BATCH_REQUIRES_INDEPENDENT_TOOLS')
                            if name == 'find_incidents':
                                if incident_number is not None and (
                                        arguments.get('incident_number') != incident_number
                                        or set(arguments) - {'incident_number', 'fields'}
                                        or output['search_mode'] != 'sql_exact'):
                                    raise ValueError('SELECTED_INCIDENT_LOOKUP_ONLY: incident_number and optional fields; sql_exact; filters={}')
                                if arguments.get('scope_mode') == 'cohort' and not set(output['intents']) & {'statistics', 'analysis'}:
                                    raise ValueError('COHORT_REQUIRES_ANALYSIS_OR_STATISTICS_INTENT')
                                arguments = add_analysis_fields(arguments, output['intents'])
                                structure(arguments, catalog[name]['parameters'], f'$.plan[{index}].arguments')
                                if output['filters'] != arguments.get('filters', {}):
                                    raise ValueError('FILTER_PLAN_MISMATCH: copy arguments.filters to top-level filters; '
                                                     'use {} when arguments.filters is omitted. Keep query conditions in arguments.')
                            if name == 'summarize_incidents':
                                if 'statistics' not in output['intents']:
                                    raise ValueError('STATISTICS_INTENT_REQUIRED')
                                if output['filters'] != arguments.get('filters'):
                                    raise ValueError('FILTER_PLAN_MISMATCH')
                            duplicate = ((name in ('find_incidents', 'summarize_incidents') and (name, fingerprint(arguments)) in completed_find_fingerprints)
                                         or (name in repeat_guarded_tools and fingerprint(arguments) in completed_tool_fingerprints[name]))
                            retrying_failed_request = any(
                                failed['key'] == retrieval_request_key(name, arguments)
                                and (name in retrieval_tools or failed.get('reason') == 'invalid_timestamp')
                                for failed in state['retrieval_failures'])
                            if name in retrieval_tools and (not ready[name]['enabled'] or (duplicate and not retrying_failed_request)):
                                raise ToolError('TOOL_UNAVAILABLE')
                            if len(batch) > 1 and ((duplicate and not retrying_failed_request) or not ready[name]['enabled']):
                                raise ValueError('BATCH_TOOL_NOT_READY: ' + name)
                            identity = (name, fingerprint(arguments))
                            if name in ('list_incident_lots', 'list_incident_wafers') and any(
                                    prior_name == name for prior_name, _ in prepared):
                                raise ValueError('BATCH_PAGINATION_REQUIRES_PREVIOUS_RESULT')
                            if identity in seen:
                                raise ValueError('DUPLICATE_BATCH_TOOL')
                            seen.add(identity)
                            if any(key in arguments for key in ('actor', 'scope_id', 'incident_ids', 'as_of')):
                                raise ValueError('CALLER_IDENTITY_ARGUMENT_FORBIDDEN')
                            bound = {'actor': actor, **arguments}
                            if name == 'match_incident_values':
                                bound['question'] = question
                            elif name not in ('find_incidents', 'summarize_incidents', 'search_meeting_minutes'):
                                bound['scope_id'] = state['scope_id']
                            if name in image_methods or name in ('search_related_incidents', 'summarize_incidents', 'get_platform_evidence', 'search_platform_history'):
                                bound['as_of'] = as_of
                            if name in document_tools:
                                if set(arguments) - {'query', 'top_k'}:
                                    raise ValueError('DOCUMENT_TOOL_ARGUMENTS_FORBIDDEN')
                                query = arguments.get('query')
                                if not isinstance(query, str) or not query.strip() or len(query) > 12000:
                                    raise ValueError('INVALID_DOCUMENT_QUERY')
                                source_kind = document_tools[name]
                                statuses = document_statuses(source_kind)
                                document_requires_content_kind(source_kind)
                                source = settings.data.get('retrieval', {}).get(source_kind, {})
                                if (request_scope != 'incident' or not state['scope_valid']
                                        or source.get('enabled') is not True or statuses is None
                                        or not callable(document_query)):
                                    raise ValueError('INCIDENT_SCOPE_REQUIRED')
                                top_k = document_top_k(source_kind, arguments)
                                if db is None:
                                    db = resources.enter_context(open_incident_tools(settings))
                                current_ids = list(db._scope(actor, state['scope_id'])['ids'])
                                if not current_ids:
                                    raise ValueError('INCIDENT_SCOPE_REQUIRED')
                                historical_ids = historical_document_ids(current_ids)
                                validate_retrieval_signature(name, document_query, {
                                    'source_kind': source_kind, 'actor': actor,
                                    'incident_ids': list(current_ids), 'historical_incident_ids': list(historical_ids),
                                    'as_of': as_of, 'query': query, 'top_k': top_k},
                                    arguments)
                            elif name == 'search_mes_reference':
                                if (settings.data.get('mes_reference', {}).get('enabled') is not True
                                        or not callable(mes_reference_query)):
                                    raise ToolError('TOOL_UNAVAILABLE')
                                kind, query, top_k, filters = validate_mes_arguments(arguments)
                                if request_scope != 'incident' or not state['scope_valid']:
                                    raise ToolError('INCIDENT_SCOPE_REQUIRED')
                                if db is None:
                                    db = resources.enter_context(open_incident_tools(settings))
                                current_ids = list(db._scope(actor, state['scope_id'])['ids'])
                                if not current_ids:
                                    raise ToolError('INCIDENT_SCOPE_REQUIRED')
                                callback_args = dict(
                                    kind=kind, actor=actor, incident_ids=list(current_ids), as_of=as_of,
                                    query=query, top_k=top_k)
                                if filters:
                                    callback_args['filters'] = filters
                                validate_retrieval_signature(name, mes_reference_query, callback_args, arguments)
                            elif name == 'search_similar_fbm':
                                if (settings.data.get('fbm_search', {}).get('enabled') is not True
                                        or not callable(fbm_search_query)
                                        or fbm_source_wafers() is None):
                                    raise ToolError('FBM_SCOPE_INCOMPLETE')
                                if db is None:
                                    db = resources.enter_context(open_incident_tools(settings))
                                current_ids = list(db._scope(actor, state['scope_id'])['ids'])
                                historical_ids = historical_document_ids(current_ids)
                                cap = settings.data.get('fbm_search', {}).get('top_k', 5)
                                top_k = arguments.get('top_k', cap)
                                query_wafer = {key: arguments.get(key) for key in
                                               ('incident_id', 'lot_id', 'wafer_id')}
                                query_wafer['incident_id'] = arguments.get('source_incident_id')
                                registered = fbm_source_wafers()['registered_wafers']
                                if (query_wafer['incident_id'] not in current_ids
                                        or tuple(query_wafer.values()) not in registered):
                                    raise ToolError('FBM_WAFER_SCOPE_MISMATCH')
                                validate_retrieval_signature(name, fbm_search_query, {
                                    'actor': actor, 'incident_ids': list(current_ids),
                                    'historical_incident_ids': list(historical_ids),
                                    'query_wafer': query_wafer, 'representation': arguments.get('representation'),
                                    'as_of': as_of, 'top_k': top_k}, arguments)
                            elif name not in ('get_engineering_snapshot', 'plan_synthetic_action_evidence',
                                              'search_similar_fbm'):
                                method = (MeetingTools.search if name == 'search_meeting_minutes'
                                          else getattr(ImageTools if name in image_methods else IncidentTools, name))
                                inspect.signature(method).bind(None, **bound)
                            needed = TOOL_TOPICS.get(name)
                            if needed:
                                needed_topics.add(needed)
                            prepared.append((name, arguments))
                        if duplicate:
                            event('duplicate_tool_guard', tool=name, reason='IDENTICAL_COMPLETED_TOOL')
                            result = review(call_id, observe_ready=True)
                            if result is not None:
                                return result
                            if state['judge'] and state['judge']['verdict'] == 'revise':
                                return finish('unavailable', limitations=['IDENTICAL_COMPLETED_TOOL'])
                            errors = 0
                            continue
                        if needed_topics - topics:
                            for role in ('router', 'judge', 'answer'):
                                compile_prompt(role, sorted(topics | needed_topics), settings=settings, shared_topics=True)
                            topics |= needed_topics
                        for name, arguments in prepared:
                            result = invoke(name, **arguments)
                            status = result['result'].get('status')
                            if name in ('find_incidents', 'summarize_incidents'):
                                state['lookup_intents'] = list(output['intents'])
                                state['incident_evidence_complete'] = state['scope_valid'] and status in ('OK', 'NO_MATCH')
                                if state['incident_evidence_complete']:
                                    completed_find_fingerprints.add((name, fingerprint(arguments)))
                                    state['completed_tool'] = name
                                    state['completed_tool_arguments'] = arguments
                            elif name in repeat_guarded_tools and status in ('OK', 'INCOMPARABLE', 'PARTIAL', 'NO_MATCH'):
                                state['completed_tool'] = name
                                state['completed_tool_arguments'] = arguments
                                completed_tool_fingerprints[name].add(fingerprint(arguments))
                            observations.append({'tool': name, 'evidence_id': result['id'], 'status': status})
                        observe(call_id, {'observations': observations})
                        if state['incident_checked'] and not state['scope_valid']:
                            return finish('needs_selection', candidates=evidence[-1]['result']['data'])
                        if requested_tools and not requested_tools - {entry['source'] for entry in evidence}:
                            result = review()
                            if result is not None:
                                return result
                    elif decision == 'load_skills':
                        requested = set(output['needs_skills'])
                        if not requested - topics:
                            raise ValueError('SKILLS_ALREADY_LOADED')
                        if request_scope == 'independent' and requested - {'meetings'}:
                            raise ValueError('INDEPENDENT_TOOL_TOPICS_NOT_SUPPORTED')
                        for role in ('router', 'judge', 'answer'):
                            compile_prompt(role, sorted(topics | requested), settings=settings, shared_topics=True)
                        topics |= requested
                        observe(call_id, {'loaded_topics': sorted(topics)})
                    elif decision in ('clarify', 'blocked'):
                        observe(call_id, {'status': decision})
                        return finish('needs_clarification' if decision == 'clarify' else 'unavailable',
                                      clarification=output['clarification'], limitations=output['limitations'])
                    else:
                        pending = requested_tools - {entry['source'] for entry in evidence}
                        if pending and state['budget_remaining'] > 0 and any(spec['enabled'] for spec in advertised_tools().values()):
                            observe(call_id, {'status': 'pending_sources', 'tools': sorted(pending)})
                            event('requested_sources_pending', tools=sorted(pending))
                            continue
                        observe(call_id, {'status': 'ready_for_judge'})
                        result = review()
                        if result is not None:
                            return result
                    errors = 0
                except (ValueError, TypeError, KeyError, ToolError, ConfigError, sqlite3.Error, LLMError) as exc:
                    if isinstance(exc, LLMError) and str(exc) != 'ROUTER_FUNCTION_CALL_REQUIRED':
                        raise
                    errors += 1
                    error = type(exc).__name__ if isinstance(exc, (sqlite3.Error, TypeError, KeyError)) else str(exc)
                    state['last_error'] = error
                    recovery = classify_recovery(exc, type(exc))
                    state['recovery'] = recovery
                    # Rejected output does not invalidate previously checked evidence.
                    if isinstance(exc, (ToolError, ConfigError, sqlite3.Error)):
                        state['code_gate'] = 'FAIL'
                    if isinstance(exc, ToolError) and 'SCOPE_EXPIRED' in error:
                        invalidate_scope(keep_pending=True)
                    event('validation_or_tool_error', error=error, recovery=recovery)
                    # A pending plan receives a receipt in its original transport.
                    if history and history[-1]['role'] == 'assistant':
                        observe(call_id, {'error': error, **({'observations': observations} if observations else {})})
                    if not recovery['retry_via_router']:
                        return finish('unavailable', limitations=[error])
                    if errors > limits['max_retries'] or state['judge'] is not None and state['judge']['return_to'] == 'answer':
                        return finish('unavailable', limitations=[error])
            return finish('unavailable', limitations=['AGENT_STEP_LIMIT'])
        except (LLMError, ConfigError, ValueError, OSError, KeyError, TypeError) as exc:
            error = str(exc) if isinstance(exc, LLMError) else type(exc).__name__
            event('run_error', error=error)
            return finish('unavailable', limitations=[error])
