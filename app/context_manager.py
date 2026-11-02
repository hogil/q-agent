"""Pure, conservative Router continuation selection; no transport or Tool calls.

The caller retains the complete trace and supplies authoritative current payload
state. This helper never summarizes evidence or changes runtime permissions.
"""
import copy
from datetime import date
import json


def _strings(value):
    return isinstance(value, list) and all(isinstance(item, str) and item for item in value)


def _json_object(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value)
    except (ValueError, TypeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _history_complete(history):
    """Accept only the two Router protocols emitted by RoleClient/observe."""
    if not isinstance(history, list) or len(history) % 2:
        return False
    used = set()
    for index in range(0, len(history), 2):
        assistant, receipt = history[index:index + 2]
        if not isinstance(assistant, dict) or not isinstance(receipt, dict):
            return False
        if assistant.get('role') != 'assistant' or 'function_call' in assistant:
            return False
        if 'tool_calls' in assistant:
            if set(assistant) - {'role', 'content', 'tool_calls'}:
                return False
            calls = assistant['tool_calls']
            if not isinstance(calls, list) or len(calls) != 1:
                return False
            call = calls[0]
            if not isinstance(call, dict) or set(call) != {'id', 'type', 'function'}:
                return False
            call_id, function = call['id'], call['function']
            if (not isinstance(call_id, str) or not call_id or call_id in used
                    or call['type'] != 'function' or not isinstance(function, dict)
                    or set(function) != {'name', 'arguments'} or function['name'] != 'submit_plan'
                    or _json_object(function['arguments']) is None
                    or assistant.get('content') is not None and not isinstance(assistant['content'], str)):
                return False
            used.add(call_id)
            if (set(receipt) != {'role', 'tool_call_id', 'content'} or receipt['role'] != 'tool'
                    or receipt['tool_call_id'] != call_id or _json_object(receipt['content']) is None):
                return False
        else:
            if set(assistant) != {'role', 'content'} or _json_object(assistant['content']) is None:
                return False
            if set(receipt) != {'role', 'content'} or receipt['role'] != 'user':
                return False
            parsed = _json_object(receipt['content'])
            if parsed is None or set(parsed) != {'plan_result'} or not isinstance(parsed['plan_result'], dict):
                return False
    return True


def _sampled(value):
    if isinstance(value, dict):
        return (value.get('routing_only') is True or value.get('prompt_sampled') is True
                or any(_sampled(item) for item in value.values()))
    if isinstance(value, list):
        return any(_sampled(item) for item in value)
    return False


def _manifest_valid(payload, evidence):
    """Validate server attestation shape, not evidence truth or its digest.

    Only the Orchestrator may supply this manifest, computed from original full
    results retained in the trace. A model/user-supplied manifest is untrusted.
    The caller must retain original status, limitations, pagination and partial
    result flags in summaries; a digest alone cannot prove that preservation.
    """
    manifest = payload.get('evidence_manifest')
    if not isinstance(manifest, list) or len(manifest) != len(evidence):
        return False
    for record, entry in zip(evidence, manifest):
        if not isinstance(entry, dict) or set(entry) != {'id', 'source', 'result_sha256'}:
            return False
        digest = entry['result_sha256']
        if (entry['id'] != record['id'] or entry['source'] != record['source']
                or not isinstance(digest, str) or len(digest) != 64
                or any(character not in '0123456789abcdefABCDEF' for character in digest)):
            return False
        if _sampled(record) and (not isinstance(record['result'], dict)
                                or not isinstance(record['result'].get('status'), str)):
            return False
    return True


def _snapshot_complete(payload):
    if not isinstance(payload, dict):
        return False
    try:
        json.dumps(payload, allow_nan=False)
    except (TypeError, ValueError, OverflowError):
        return False
    booleans = ('incident_checked', 'scope_valid', 'incident_evidence_complete',
                'lot_lookup_complete', 'wafer_lookup_complete', 'detail_scope_valid')
    lists = ('requirements', 'lookup_intents', 'evidence_ids', 'loaded_topics',
             'available_topics', 'pending_requested_tools', 'incomparable_evidence_ids', 'mapped_fields')
    if any(key not in payload or type(payload[key]) is not bool for key in booleans):
        return False
    if any(key not in payload or not _strings(payload[key]) for key in lists):
        return False
    if not payload['requirements'] or len(set(payload['evidence_ids'])) != len(payload['evidence_ids']):
        return False
    if any(type(payload.get(key)) is not int or payload[key] < 0
           for key in ('budget_remaining', 'review_rounds_remaining')):
        return False
    if payload.get('request_scope') not in ('auto', 'incident', 'independent'):
        return False
    if payload.get('code_gate') not in ('PASS', 'FAIL'):
        return False
    if not isinstance(payload.get('question'), str) or not payload['question'].strip():
        return False
    try:
        if not isinstance(payload.get('as_of'), str) or date.fromisoformat(payload['as_of']).isoformat() != payload['as_of']:
            return False
    except ValueError:
        return False
    for key in ('scope_id', 'last_error', 'completed_tool'):
        if key not in payload or payload[key] is not None and (not isinstance(payload[key], str) or not payload[key]):
            return False
    if ('completed_tool_arguments' not in payload or payload['completed_tool_arguments'] is not None
            and not isinstance(payload['completed_tool_arguments'], dict)):
        return False
    if (payload['completed_tool'] is None) != (payload['completed_tool_arguments'] is None):
        return False
    if payload['scope_valid'] and (not payload['incident_checked'] or not payload['scope_id']):
        return False
    if payload['incident_evidence_complete'] and not payload['scope_valid']:
        return False
    tools = payload.get('available_tools')
    if not isinstance(tools, dict) or any(not isinstance(name, str) or not name
            or not isinstance(spec, dict) or type(spec.get('enabled')) is not bool
            for name, spec in tools.items()):
        return False
    if any(name not in tools for name in payload['pending_requested_tools']):
        return False
    if 'selected_incident_number' in payload and (not isinstance(payload['selected_incident_number'], str)
                                                or not payload['selected_incident_number'].strip()):
        return False
    evidence = payload.get('evidence')
    if not isinstance(evidence, list):
        return False
    if any(not isinstance(row, dict) or not isinstance(row.get('id'), str)
           or not isinstance(row.get('source'), str) or not row['source'] or 'result' not in row
           or not isinstance(row['result'], (dict, str))
           or 'arguments' in row and not isinstance(row['arguments'], dict) for row in evidence):
        return False
    if [row['id'] for row in evidence] != payload['evidence_ids']:
        return False
    if (_sampled(evidence) or 'evidence_manifest' in payload) and not _manifest_valid(payload, evidence):
        return False
    ids = set(payload['evidence_ids'])
    if not set(payload['incomparable_evidence_ids']) <= ids:
        return False
    actual_incomparable = [row['id'] for row in evidence if isinstance(row['result'], dict)
                           and row['result'].get('status') == 'INCOMPARABLE']
    if actual_incomparable != payload['incomparable_evidence_ids']:
        return False
    if 'judge' not in payload:
        return False
    judge = payload['judge']
    if judge is not None:
        if (not isinstance(judge, dict) or judge.get('verdict') not in ('pass', 'revise', 'need_evidence', 'abstain')
                or judge.get('return_to') not in ('router', 'answer')):
            return False
        for key, texts in (('coverage', ('requirement', 'status')), ('issues', ('type', 'reason', 'next_action'))):
            if not isinstance(judge.get(key), list):
                return False
            for row in judge[key]:
                if (not isinstance(row, dict) or not _strings(row.get('evidence_ids'))
                        or not set(row['evidence_ids']) <= ids
                        or any(not isinstance(row.get(field), str) for field in texts)):
                    return False
                if key == 'coverage' and (row['requirement'] not in payload['requirements']
                        or row['status'] not in ('satisfied', 'missing', 'conflict', 'unavailable')):
                    return False
    return True


def select_context(role, role_round, payload, history, policy, transport_contract=False, force_full=False):
    """Return history selection and compiler hints without modifying any input.

    ``transport_contract`` is an exact bool attestation by the actual client, not
    a deployment setting. Character metrics measure JSON history, never tokens.
    """
    selected = copy.deepcopy(history)
    phase, reason = 'fallback', 'invalid_policy'
    valid_policy = isinstance(policy, dict) and all(type(policy.get(key, default)) is bool
        for key, default in (('enabled', False), ('omit_examples', True), ('omit_embedded_output_schema', True)))
    minimum = policy.get('router_history_min_messages', 0) if isinstance(policy, dict) else None
    valid_policy = valid_policy and type(minimum) is int and 0 <= minimum <= 128
    if valid_policy:
        if not policy.get('enabled', False):
            phase, reason = 'disabled', 'policy_disabled'
        elif role != 'router':
            phase, reason = 'initial', 'non_router'
        elif type(role_round) is not int or role_round < 1:
            reason = 'invalid_role_round'
        elif role_round == 1:
            phase, reason = 'initial', 'first_role_call'
        elif force_full is not False:
            reason = 'force_full'
        elif not _snapshot_complete(payload):
            reason = 'incomplete_snapshot'
        elif not _history_complete(history):
            reason = 'unresolved_or_unknown_history'
        elif len(history) < minimum:
            reason = 'history_below_threshold'
        else:
            selected, phase, reason = [], 'continuation', 'complete_snapshot'
    def characters(value):
        try:
            return len(json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False))
        except (ValueError, TypeError):
            return None
    before = len(history) if isinstance(history, list) else None
    after = len(selected) if isinstance(selected, list) else None
    return {'history': selected, 'phase': phase,
            'omit_examples': phase == 'continuation' and policy.get('omit_examples', True),
            'omit_embedded_output_schema': (phase == 'continuation' and transport_contract is True
                                           and policy.get('omit_embedded_output_schema', True)),
            'metrics': {'phase': phase, 'reason': reason, 'history_messages_before': before,
                        'history_messages_after': after,
                        'history_messages_dropped': before - after if before is not None and after is not None else None,
                        'history_characters_before': characters(history),
                        'history_characters_after': characters(selected)}}
