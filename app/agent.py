"""Bounded Router -> Tools -> Judge -> Answer loop, with read-only DB adapters."""
from contextlib import ExitStack
from datetime import date, datetime
import inspect
import json
import sqlite3
from zoneinfo import ZoneInfo

from config_loader import ConfigError
from incident_tools import IncidentTools, ToolError
from llm_client import LLMError, RoleClient
from meeting_tools import MeetingTools
from image_tools import ImageTools
from prompt_contracts import inspection_rows, structure, validate_output
from runtime_factory import open_incident_tools
from skill_loader import compile_prompt, read_role_reference


def run(settings, question, actor, request_scope='incident', topics=None, selected=None, emit=None, as_of=None,
        context_data=None, engineering_query=None, requested_tools=(), related_search=True, inspection_requested=False):
    if not isinstance(question, str) or not question.strip() or len(question) > 12000:
        raise ValueError('QUESTION_REQUIRED_OR_TOO_LONG')
    if not actor or not actor.strip() or request_scope not in ('auto', 'incident', 'independent'):
        raise ValueError('ACTOR_AND_VALID_REQUEST_SCOPE_REQUIRED')
    if type(inspection_requested) is not bool:
        raise ValueError('INVALID_INSPECTION_REQUEST')
    as_of = as_of or datetime.now(ZoneInfo(settings.data['runtime']['timezone'])).date().isoformat()
    if not isinstance(as_of, str) or date.fromisoformat(as_of).isoformat() != as_of:
        raise ValueError('AS_OF_ISO_DATE_REQUIRED')
    topics = set(topics or []) if request_scope == 'incident' else set()
    if request_scope == 'incident':
        topics.add('incident_search')
    events, evidence, history = [], [], []
    limits = settings.data['runtime']
    state = {'scope_id': None, 'incident_checked': False, 'scope_valid': False,
             'budget_remaining': limits['max_tool_calls'], 'code_gate': 'PASS',
             'requirements': [question], 'request_scope': request_scope, 'judge': None,
             'inspection_requested': inspection_requested,
             'last_error': None, 'as_of': as_of, 'incident_evidence_complete': False,
             'completed_tool': None, 'completed_tool_arguments': None,
             'lot_lookup_complete': False, 'wafer_lookup_complete': False}
    if request_scope == 'independent':
        evidence.append({'id': 'input-1', 'source': 'user_supplied_unverified', 'result': question})
    calls = 0
    next_evidence = 0
    lot_checked = False
    errors = 0
    revisions = 0
    completed_find_fingerprints = set()
    repeat_guarded_tools = {'compare_sem_images', 'compare_overlay_maps', 'get_engineering_snapshot',
                            'list_incident_lots', 'list_incident_wafers'}
    completed_tool_fingerprints = {name: set() for name in repeat_guarded_tools}
    requested_tools = set(requested_tools)
    analysis_fields = ('incident_detail', 'analysis_detail', 'confirmed_cause', 'containment',
                       'corrective_action', 'verification', 'prevention', 'remaining')

    def event(kind, **values):
        item = {'event': kind, **values}
        events.append(item)
        if emit:
            emit(item)

    def finish(status, **values):
        return {'status': status, **values, 'scope_id': state['scope_id'],
                'request_scope': request_scope, 'as_of': as_of, 'evidence': evidence, 'events': events,
                'llm_calls': calls, 'tool_calls': limits['max_tool_calls'] - state['budget_remaining']}

    def context():
        references = {}
        verified = []
        for entry in evidence:
            if entry['source'] == 'get_engineering_snapshot':
                rows = entry['result'].get('sections', {}).get('maps', {}).get('records', [])
                key = 'id'
                verified.extend(row[key] for row in rows)
            elif entry['source'] == 'search_related_incidents':
                rows, key = entry['result'].get('items', []), 'incident_number'
            else:
                continue
            for row in rows:
                references.setdefault(row[key], []).append(entry['id'])
        return {**state, 'available_tools': catalog, 'evidence_ids': [item['id'] for item in evidence],
                'historical_reference_evidence': references,
                'verified_historical_reference_ids': list(dict.fromkeys(verified)),
                'mapped_fields': [k for k, v in settings.data['tables']['incident']['columns'].items() if v],
                'skills_root': settings.data['paths']['skills_root'],
                'registry_file': settings.data['paths']['registry_file']}

    def advertised_tools():
        visible = {name: {key: value for key, value in spec.items() if key != 'parameters'}
                   for name, spec in catalog.items()}
        for name, spec in visible.items():
            if requested_tools and state['scope_valid'] and spec['stage'] == 'incident':
                spec['enabled'] = False
            if request_scope == 'incident' and not state['scope_valid'] and spec['stage'] == 'tools':
                spec['enabled'] = False
            if name in {'list_incident_wafers', 'list_comparison_assets', 'compare_sem_images', 'compare_overlay_maps'} and not lot_checked:
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

    def observe(call_id, result):
        if call_id is None:
            history.append({'role': 'user', 'content': json.dumps({'plan_result': result}, ensure_ascii=False, separators=(',', ':'))})
            return
        history.append({'role': 'tool', 'tool_call_id': call_id,
                        'content': json.dumps(result, ensure_ascii=False, separators=(',', ':'))})

    def invalidate_scope(keep_pending=False):
        nonlocal lot_checked
        state.update(scope_id=None, scope_valid=False, incident_checked=False, judge=None)
        state.update(incident_evidence_complete=False, completed_tool=None, completed_tool_arguments=None)
        state.update(lot_lookup_complete=False, wafer_lookup_complete=False)
        evidence.clear()
        topics.discard('terminology')
        lot_checked = False
        # The pending call still needs its matching tool response, even after failure.
        history[:] = history[-1:] if keep_pending and history and history[-1]['role'] == 'assistant' else []

    def ask(role):
        nonlocal calls
        if calls >= limits['max_agent_steps']:
            raise LLMError('AGENT_STEP_LIMIT')
        prompt = compile_prompt(role, sorted(topics), settings=settings, shared_topics=True)
        routed_evidence = evidence
        if role == 'router' and requested_tools:
            # Routing needs identifiers and retrieval state; review retains the source content.
            summarized = {'get_engineering_snapshot', 'search_meeting_minutes',
                          'compare_sem_images', 'compare_overlay_maps'}
            routed_evidence = [{**entry, 'result': {
                key: value for key, value in entry['result'].items()
                if key in ('status', 'limitations', 'count', 'total', 'next_offset')}, 'routing_only': True}
                if entry['source'] in summarized else entry for entry in evidence]
        payload = {'question': question, **state, 'evidence': routed_evidence,
                   'evidence_ids': [item['id'] for item in evidence],
                   'available_tools': advertised_tools(),
                   'mapped_fields': context()['mapped_fields'],
                   'loaded_topics': prompt['topics'], 'available_topics': prompt['available_topics']}
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
        if context_data is not None:
            payload['context_data_unverified'] = context_data
        if role in ('judge', 'answer'):
            # Keep observations once in evidence_focus; canonical Tool evidence stays intact.
            payload['evidence'] = [
                {**entry, 'result': {key: value for key, value in entry['result'].items()
                                     if key != 'observations'}}
                if entry['source'] == 'get_engineering_snapshot' else entry for entry in evidence]
            payload['evidence_focus'] = [
                {'evidence_id': entry['id'], 'source': entry['source'],
                 'observations': entry['result'].get('observations'),
                 **{key: entry['result'][key] for key in
                    ('status', 'findings', 'model', 'model_version', 'asset_ids', 'limitations')
                    if key in entry['result']}}
                for entry in evidence if entry['source'] in
                ('get_engineering_snapshot', 'compare_sem_images', 'compare_overlay_maps')]
        calls += 1
        event('llm_start', role=role, step=calls, release=prompt['release'],
              model=settings.model_profile(role)['deployment']['served_model'],
              prompt_sha256=prompt['prompt_sha256'], loaded_files=prompt['loaded_files'])
        try:
            output, call_id = client.call(role, prompt['system_prompt'], payload, history if role == 'router' else [])
        except LLMError:
            event('llm_metrics', role=role, metrics=getattr(client, 'last_metrics', {}))
            raise
        event('llm_output', role=role, output=output, metrics=getattr(client, 'last_metrics', {}))
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
            implemented = {'match_incident_values', 'find_incidents', 'list_incident_lots', 'list_incident_wafers', 'search_meeting_minutes', 'get_engineering_snapshot', 'search_related_incidents'} | image_methods
            if set(all_tools) - implemented:
                raise ValueError('UNIMPLEMENTED_TOOL_IN_CATALOG')

            def available(scope):
                if scope == 'auto':
                    return {}
                result = {name: dict(spec) for name, spec in all_tools.items()
                          if scope == 'incident' or name == 'search_meeting_minutes'}
                if 'match_incident_values' in result and not settings.data['value_matching']['enabled']:
                    result['match_incident_values']['enabled'] = False
                if 'get_engineering_snapshot' in result:
                    result['get_engineering_snapshot']['enabled'] = callable(engineering_query)
                if 'search_related_incidents' in result:
                    result['search_related_incidents']['enabled'] = bool(related_search)
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
                if request_scope == 'incident' and name not in ('find_incidents', 'match_incident_values') and not state['scope_valid']:
                    raise ToolError('INCIDENT_SCOPE_REQUIRED')
                if (name == 'list_incident_wafers' or name in image_methods) and not lot_checked:
                    raise ToolError('LOT_LOOKUP_REQUIRED')
                state['budget_remaining'] -= 1
                if name != 'search_meeting_minutes' and db is None:
                    db = resources.enter_context(open_incident_tools(settings))
                if name == 'get_engineering_snapshot':
                    ids = list(db._scope(actor, state['scope_id'])['ids'])
                    result = engineering_query(actor=actor, incident_ids=ids, as_of=as_of)
                elif name == 'search_related_incidents':
                    result = db.search_related_incidents(actor, state['scope_id'], as_of=as_of, **arguments)
                elif name == 'search_meeting_minutes':
                    ids = list(db._scope(actor, state['scope_id'])['ids']) if request_scope == 'incident' else None
                    result = MeetingTools(settings).search(actor, incident_ids=ids, as_of=as_of, **arguments)
                elif name in image_methods:
                    if images is None:
                        images = ImageTools(settings, db)
                    result = getattr(images, name)(actor, state['scope_id'], as_of=as_of, **arguments)
                elif name == 'match_incident_values':
                    result = db.match_incident_values(actor, question)
                elif name == 'find_incidents':
                    # A new search invalidates previous evidence, even if it fails.
                    invalidate_scope(keep_pending=True)
                    result = db.find_incidents(actor, **arguments)
                    if len(result['data']) > 1 and not selected:
                        result = {**result, 'requires_selection': True, 'status': 'NEEDS_SELECTION'}
                    if selected:
                        selection = db.select_incidents(actor, result['scope_id'], selected)
                        result = {**result, 'scope_id': selection['scope_id'], 'requires_selection': False,
                                  'status': 'OK', 'data': [r for r in result['data'] if r['incident_id'] in selected]}
                    state.update(scope_id=result['scope_id'], incident_checked=True,
                                 scope_valid=not result['requires_selection'])
                else:
                    result = getattr(db, name)(actor, state['scope_id'], **arguments)
                    if name == 'list_incident_lots':
                        lot_checked = True
                    if arguments.get('offset', 0) == 0 and result.get('next_offset') is None:
                        if name == 'list_incident_lots':
                            state['lot_lookup_complete'] = True
                        elif name == 'list_incident_wafers':
                            known_lots = {row['lot_id'] for entry in evidence
                                          if entry['source'] == 'list_incident_lots'
                                          for row in entry['result']['items']}
                            requested = arguments.get('lot_ids')
                            state['wafer_lookup_complete'] = (not requested or
                                (state['lot_lookup_complete'] and known_lots.issubset(set(requested))))
                next_evidence += 1
                item = {'id': 'e' + str(next_evidence), 'source': name, 'arguments': arguments, 'result': result}
                evidence.append(item)
                if name != 'match_incident_values':
                    state.update(code_gate='PASS', last_error=None)
                event('tool_result', **item)
                return item

            def review(call_id=None, observe_ready=False):
                nonlocal revisions
                if observe_ready:
                    observe(call_id, {'status': 'ready_for_judge', 'reason': 'IDENTICAL_COMPLETED_TOOL'})
                if (requested_tools - {entry['source'] for entry in evidence} and state['budget_remaining'] > 0
                        and any(spec['enabled'] for spec in advertised_tools().values())):
                    return None
                judge, _ = ask('judge')
                validate_output('judge', judge, context())
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
                answer, _ = ask('answer')
                validate_output('answer', answer, {**context(), 'judge_verdict': judge['verdict']})
                return finish(answer['status'], answer=answer['answer'], claims=answer['claims'],
                              limitations=answer['limitations'], judge=judge,
                              inspection_plan=inspection_rows(answer.get('inspection_plan')))

            while calls < limits['max_agent_steps']:
                call_id = None
                observations = []
                try:
                    if requested_tools and state['incident_checked'] and not any(
                            spec['enabled'] for spec in advertised_tools().values()):
                        result = review()
                        if result is not None:
                            return result
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
                                arguments = add_analysis_fields(arguments, output['intents'])
                                structure(arguments, catalog[name]['parameters'], f'$.plan[{index}].arguments')
                                if output['filters'] != arguments.get('filters', {}):
                                    raise ValueError('FILTER_PLAN_MISMATCH: copy arguments.filters to top-level filters; '
                                                     'use {} when arguments.filters is omitted. Keep query conditions in arguments.')
                            duplicate = ((name == 'find_incidents' and fingerprint(arguments) in completed_find_fingerprints)
                                         or (name in repeat_guarded_tools and fingerprint(arguments) in completed_tool_fingerprints[name]))
                            if len(batch) > 1 and (duplicate or not ready[name]['enabled']):
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
                            elif name not in ('find_incidents', 'search_meeting_minutes'):
                                bound['scope_id'] = state['scope_id']
                            if name in image_methods or name == 'search_related_incidents':
                                bound['as_of'] = as_of
                            if name != 'get_engineering_snapshot':
                                method = (MeetingTools.search if name == 'search_meeting_minutes'
                                          else getattr(ImageTools if name in image_methods else IncidentTools, name))
                                inspect.signature(method).bind(None, **bound)
                            needed = 'images' if name in image_methods else {'match_incident_values': 'terminology', 'list_incident_lots': 'lots', 'list_incident_wafers': 'wafers', 'search_meeting_minutes': 'meetings'}.get(name)
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
                            if name == 'find_incidents':
                                state['incident_evidence_complete'] = state['scope_valid'] and status in ('OK', 'NO_MATCH')
                                if state['incident_evidence_complete']:
                                    completed_find_fingerprints.add(fingerprint(arguments))
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
                    # Rejected output does not invalidate previously checked evidence.
                    if isinstance(exc, (ToolError, ConfigError, sqlite3.Error)):
                        state['code_gate'] = 'FAIL'
                    if isinstance(exc, ToolError) and 'SCOPE_EXPIRED' in error:
                        invalidate_scope(keep_pending=True)
                    event('validation_or_tool_error', error=error)
                    # A pending plan receives a receipt in its original transport.
                    if history and history[-1]['role'] == 'assistant':
                        observe(call_id, {'error': error, **({'observations': observations} if observations else {})})
                    if errors > limits['max_retries'] or state['judge'] is not None and state['judge']['return_to'] == 'answer':
                        return finish('unavailable', limitations=[error])
            return finish('unavailable', limitations=['AGENT_STEP_LIMIT'])
        except (LLMError, ConfigError, ValueError, OSError, KeyError, TypeError) as exc:
            error = str(exc) if isinstance(exc, LLMError) else type(exc).__name__
            event('run_error', error=error)
            return finish('unavailable', limitations=[error])
