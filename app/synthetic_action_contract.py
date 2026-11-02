"""Validation for the synthetic-only, proposal-only action planner boundary."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import math
from zoneinfo import ZoneInfo

from incident_tools import ToolError

MAX_RESULT_BYTES = 64 * 1024
_REQUIRED = {
    'scope', 'as_of', 'revision', 'evidence', 'remaining_hypotheses',
    'admissible_action_sets', 'decision_sufficient', 'causal_proof',
    'release_allowed', 'release_blocking_risk_hypotheses',
    'requested_action_allowed', 'spent_cost', 'cost_budget',
    'remaining_cost_budget', 'next_test_projected_spent_cost', 'next_test',
}


def _fail():
    raise ToolError('SYNTHETIC_ACTION_PLANNER_FAILED') from None


def _iso(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00')) if isinstance(value, str) else value
    except (ValueError, TypeError):
        _fail()
    if not isinstance(parsed, datetime) or parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        _fail()
    return parsed.astimezone(timezone.utc).isoformat()


def validate_planner_result(result, scoped_input, cutoff_date, timezone_name):
    """Validate planner v1 certificate and permanently strip execution authority."""
    try:
        encoded = json.dumps(result, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8')
    except (TypeError, ValueError, OverflowError):
        _fail()
    if len(encoded) > MAX_RESULT_BYTES or not isinstance(result, dict) or set(result) != _REQUIRED:
        _fail()
    scope = [list(pair) for pair in scoped_input['scope']]
    expected_as_of = scoped_input['as_of'].astimezone(timezone.utc).isoformat()
    if (result['scope'] != scope or _iso(result['as_of']) != expected_as_of
            or result['revision'] != scoped_input['revision']):
        _fail()
    if any(not isinstance(pair, list) or len(pair) != 2
           or any(not isinstance(value, str) or not value for value in pair) for pair in result['scope']):
        _fail()
    if scoped_input['as_of'].astimezone(ZoneInfo(timezone_name)).date().isoformat() != cutoff_date:
        _fail()
    for key in ('decision_sufficient', 'causal_proof', 'release_allowed'):
        if type(result[key]) is not bool:
            _fail()
    if result['causal_proof'] is not False:
        _fail()
    if result['requested_action_allowed'] is not None and type(result['requested_action_allowed']) is not bool:
        _fail()
    if not isinstance(result['evidence'], list) or not isinstance(result['remaining_hypotheses'], list):
        _fail()
    if not isinstance(result['admissible_action_sets'], list) or not isinstance(result['release_blocking_risk_hypotheses'], list):
        _fail()
    if any(not isinstance(row, str) for row in result['remaining_hypotheses'] + result['release_blocking_risk_hypotheses']):
        _fail()
    if any(not isinstance(row, dict) or set(row) != {'id', 'version', 'sha256'}
           or any(not isinstance(row[key], str) or not row[key] for key in ('id', 'version', 'sha256'))
           for row in result['evidence']):
        _fail()
    if any(not isinstance(group, list) or any(not isinstance(action, str) for action in group)
           for group in result['admissible_action_sets']):
        _fail()
    for key in ('spent_cost', 'cost_budget', 'remaining_cost_budget'):
        if isinstance(result[key], bool) or not isinstance(result[key], (int, float)) or not math.isfinite(result[key]):
            _fail()
    projected = result['next_test_projected_spent_cost']
    if projected is not None and (isinstance(projected, bool) or not isinstance(projected, (int, float))
                                  or not math.isfinite(projected)):
        _fail()
    if result['next_test'] is not None and not isinstance(result['next_test'], dict):
        _fail()
    if result['next_test'] is not None:
        expected_test_fields = {'id', 'worst_case_action_sets', 'action_disagreement_reduction',
                                'reduction_per_cost', 'execution_granted'}
        if (set(result['next_test']) != expected_test_fields
                or not isinstance(result['next_test']['id'], str)
                or type(result['next_test']['execution_granted']) is not bool
                or type(result['next_test']['worst_case_action_sets']) is not int
                or type(result['next_test']['action_disagreement_reduction']) is not int
                or isinstance(result['next_test']['reduction_per_cost'], bool)
                or not isinstance(result['next_test']['reduction_per_cost'], (int, float))
                or not math.isfinite(result['next_test']['reduction_per_cost'])):
            _fail()
    safe = json.loads(encoded)

    def suppress_execution(value):
        if isinstance(value, dict):
            for key, item in list(value.items()):
                if key == 'execution_granted':
                    value[key] = False
                else:
                    suppress_execution(item)
        elif isinstance(value, list):
            for item in value:
                suppress_execution(item)

    suppress_execution(safe)
    safe['execution_granted'] = False
    safe['synthetic_only'] = True
    safe['proposal_only'] = True
    safe['provenance'] = {
        'source': 'synthetic_sqlite_action_lease',
        'snapshot_provider_attested': True,
        'scope_revision': scoped_input['revision'],
        'as_of': expected_as_of,
        'assumptions': 'Planner hypotheses, evidence, and candidate tests are synthetic inputs; bridge scope completeness is source-declared.',
    }
    return safe
