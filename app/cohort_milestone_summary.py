"""Bounded read-only projection of a pinned synthetic research milestone."""
from copy import deepcopy
import math
from pathlib import Path
import re


def _bounded(value, depth=0):
    if depth > 9:
        raise ValueError('milestone nesting exceeds bound')
    if isinstance(value, dict):
        if len(value) > 128 or any(not isinstance(k, str) or len(k) > 120 for k in value):
            raise ValueError('milestone object exceeds bound')
        for item in value.values():
            _bounded(item, depth + 1)
    elif isinstance(value, list):
        if len(value) > 64:
            raise ValueError('milestone list exceeds bound')
        for item in value:
            _bounded(item, depth + 1)
    elif isinstance(value, str):
        if len(value) > 2500:
            raise ValueError('milestone text exceeds bound')
    elif isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError('milestone number must be finite')
    elif value is not None and not isinstance(value, (int, bool)):
        raise ValueError('milestone JSON type is unsupported')


def _count(value):
    if type(value) is not int or not 0 <= value <= 10**9:
        raise ValueError('milestone count must be a bounded nonnegative integer')


def _strings(value):
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError('milestone text collection must be a string list')


def _display_contract(source):
    for name in ('actual_llm', 'multimodal_tools', 'image_benchmark', 'public_numeric_patch', 'forecast_pool', 'integrated_pilot'):
        _strings(source[name].get('limits'))
    _strings(source.get('pending'))
    facts = source['actual_llm'].get('facts')
    if not isinstance(facts, dict):
        raise ValueError('milestone actual facts must be an object')
    for name in ('current_wafers', 'past_reference_wafers', 'independent_event_wafers', 'current_down_exposed_wafers', 'current_event_intersection', 'current_outcome_queries'):
        _count(facts.get(name))
    _strings(facts.get('current_unobserved_steps'))
    images = source['multimodal_tools'].get('image_expert_results')
    if not isinstance(images, list) or len(images) > 2:
        raise ValueError('at most two image expert views can be displayed')
    for row in images:
        if not isinstance(row, dict) or row.get('view') not in ('wafer_context', 'chip_crop') or not isinstance(row.get('scores'), list) or len(row['scores']) > 2:
            raise ValueError('invalid image expert result shape')
        for score in row['scores']:
            if not isinstance(score, dict) or any(not isinstance(score.get(k), str) for k in ('target', 'scope')):
                raise ValueError('invalid image target scope')
            for key in ('score', 'validation_threshold'):
                value = score.get(key)
                if type(value) not in (int, float) or not 0 <= value <= 1:
                    raise ValueError('image score/threshold must be in [0,1]')
    for section, key in (('public_numeric_patch', 'macro_normalized_mae'), ('forecast_pool', 'macro_normalized_validation_mae')):
        metrics = source[section].get(key)
        if not isinstance(metrics, dict) or any(type(v) not in (int, float) or v < 0 for v in metrics.values()):
            raise ValueError('milestone metrics must be nonnegative numbers')
    for key in ('full_96week_world_created', 'images_generated', 'models_trained'):
        if type(source['integrated_pilot'].get(key)) is not bool:
            raise ValueError('pilot status flags must be boolean')
    overlap = source['integrated_pilot'].get('nominal_complete_rule_overlap_0_to_6')
    if not isinstance(overlap, dict) or set(overlap) != set('0123456'):
        raise ValueError('nominal overlap bins must span zero through six')
    for value in overlap.values():
        _count(value)


def milestone_summary(source, root: Path):
    if source is None:
        return None
    if not isinstance(source, dict) or source.get('schema_id') != 'qagent.skip_research_milestone.v5':
        raise ValueError('unexpected research milestone schema')
    _bounded(source)
    if source.get('fab_sample_origin') != 'procedural_synthetic' or source.get('production_validation') is not False:
        raise ValueError('synthetic research milestone without production validation required')
    names = ('analysis_tracks', 'actual_llm', 'multimodal_tools', 'image_benchmark',
             'public_numeric_patch', 'forecast_pool', 'integrated_pilot', 'proofs')
    if any(not isinstance(source.get(name), dict) for name in names):
        raise ValueError('milestone sections must be objects')
    _display_contract(source)
    llm, multi = source['actual_llm'], source['multimodal_tools']
    for row, fields in ((llm, ('model_calls', 'tool_calls')), (multi, ('tool_calls', 'base_tool_calls', 'llm_calls', 'current_outcome_queries'))):
        for field in fields:
            _count(row.get(field))
    mes = llm.get('dummy_mes')
    if not isinstance(mes, dict):
        raise ValueError('milestone dummy MES summary is required')
    for field in ('receipt_replays', 'new_actions'):
        _count(mes.get(field))
    for row in (mes.get('ledger_counts'), multi.get('scope_counts'), source['integrated_pilot'].get('counts')):
        if not isinstance(row, dict):
            raise ValueError('milestone count group is required')
        for value in row.values():
            _count(value)
    if llm.get('production_execution') is not False or multi.get('production_actions_executed') is not False:
        raise ValueError('milestone production actions are not permitted')
    if llm.get('general_quality_established') is not False or multi.get('connected_to_llm_roles') is not False:
        raise ValueError('v5 milestone must retain separate limited LLM and Tool results')
    proofs = source['proofs']
    if not 1 <= len(proofs) <= 32:
        raise ValueError('milestone proof count exceeds bound')
    for name, entry in proofs.items():
        if not isinstance(entry, dict) or set(entry) != {'path', 'sha256'}:
            raise ValueError('invalid milestone proof metadata')
        path = Path(entry['path']) if isinstance(entry.get('path'), str) else None
        local_release = name == 'application_release' and path is not None and path.resolve() == Path(__file__).with_name('release.lock.json').resolve()
        if path is None or not path.is_absolute() or not (path.resolve().is_relative_to(root.resolve()) or local_release):
            raise ValueError('milestone proof path escapes artifact root')
        if not isinstance(entry.get('sha256'), str) or not re.fullmatch(r'[0-9a-fA-F]{64}', entry['sha256']):
            raise ValueError('invalid milestone proof SHA256')
    result = {name: deepcopy(source[name]) for name in names if name not in ('actual_llm', 'proofs')}
    result['actual_llm'] = {key: deepcopy(value) for key, value in llm.items() if key != 'dummy_mes'}
    result['actual_llm']['dummy_mes'] = {key: deepcopy(mes[key]) for key in ('receipt_replays', 'new_actions', 'ledger_counts')}
    result.update({key: deepcopy(source.get(key)) for key in ('schema_id', 'created_at_utc', 'goal_status', 'fab_sample_origin', 'production_validation', 'pending')})
    result['proof_count'] = len(proofs)
    return result
