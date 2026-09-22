"""OpenAI-compatible Chat Completions transport for configured role models."""
import copy
import json
import os
from time import perf_counter

from openai import OpenAI, OpenAIError
from skill_loader import read_role_reference


class LLMError(RuntimeError):
    pass


class RoleClient:
    def __init__(self, settings):
        self.settings = settings
        for role in ('router', 'judge', 'answer'):
            model = settings.model_profile(role)['deployment']
            if not model['enabled'] or model['mode'] != 'api':
                raise LLMError('ROLE_REQUIRES_ENABLED_API_MODEL: ' + role)
            if not os.environ.get(model['api_key_env']):
                raise LLMError('MODEL_API_KEY_ENV_MISSING: ' + role)

    def call(self, role, system_prompt, payload, history):
        started = perf_counter()
        self.last_metrics = {
            'elapsed_seconds': 0.0,
            'input_tokens': None,
            'output_tokens': None,
            'total_tokens': None,
            'finish_reason': None,
            'request_characters': None,
        }
        profile = self.settings.model_profile(role)
        model = profile['deployment']
        structured_router = role == 'router' and model['structured_outputs']
        if role == 'router':
            payload = {**payload, 'response_contract': {
                'transport': 'json_schema' if structured_router else 'function_call',
                'name': 'submit_plan'}}
        messages = [{'role': 'system', 'content': system_prompt}, *history,
                    {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}]
        options = dict(model=model['served_model'], messages=messages, temperature=profile['temperature'],
                       max_tokens=profile['max_output_tokens'])
        if role == 'router':
            paths = self.settings.data['paths']
            schema = read_role_reference('router', 'output.schema.json', paths['skills_root'], paths['registry_file'])
            if 'available_topics' in payload:
                schema['properties']['needs_skills']['items']['enum'] = list(payload['available_topics'])
            if structured_router:
                intents = schema['properties']['intents']
                intents['maxItems'] = len(intents['items']['enum'])
                budget_remaining = payload.get('budget_remaining', 4)
                if not isinstance(budget_remaining, int):
                    budget_remaining = 4
                schema['properties']['plan']['maxItems'] = (
                    min(4, max(0, budget_remaining)) if payload.get('scope_valid') is True else 1)
                catalog = read_role_reference('router', 'tools.json', paths['skills_root'], paths['registry_file'])
                advertised = payload.get('available_tools')
                if payload.get('pending_requested_tools') and isinstance(advertised, dict) and any(
                        spec.get('enabled') for spec in advertised.values()):
                    schema['properties']['decision']['enum'] = [decision for decision in
                        schema['properties']['decision']['enum'] if decision != 'ready_for_judge']
                if isinstance(advertised, dict):
                    enabled = {name for name, spec in advertised.items()
                               if isinstance(spec, dict) and spec.get('enabled') is True}
                    catalog = {name: spec for name, spec in catalog.items() if name in enabled}
                    if payload.get('pending_requested_tools'):
                        slots = sum(len(advertised[name].get('modalities', ['sem', 'overlay']))
                                    if name == 'list_comparison_assets' else 1 for name in catalog)
                        schema['properties']['plan']['maxItems'] = min(
                            schema['properties']['plan']['maxItems'], slots)
                step = schema['properties']['plan']['items']
                if catalog:
                    variants = []
                    for name, spec in catalog.items():
                        assets = (advertised or {}).get(name, {}).get('asset_ids_by_item')
                        for item, ids in (assets.items() if assets is not None else [(None, None)]):
                            variant = copy.deepcopy(step)
                            variant['properties']['tool']['enum'] = [name]
                            variant['properties']['arguments'] = copy.deepcopy(spec['parameters'])
                            if name == 'list_comparison_assets' and advertised and 'modalities' in advertised[name]:
                                variant['properties']['arguments']['properties']['modality']['enum'] = advertised[name]['modalities']
                            if item is not None:
                                args = variant['properties']['arguments']['properties']
                                args['item']['enum'] = [item]
                                args['asset_ids']['items']['enum'] = ids
                                args['asset_ids'].update(minItems=2, maxItems=2)
                            variants.append(variant)
                    schema['properties']['plan']['items'] = {'anyOf': variants}
                else:
                    # Empty plans remain valid for route/clarify/blocked/load_skills;
                    # no Tool item can be emitted until the catalog is repopulated.
                    empty = copy.deepcopy(step)
                    empty['properties']['tool']['enum'] = []
                    schema['properties']['plan']['items'] = empty
                # Generate the plan before its duplicated filter summary.
                props = schema['properties']
                first = ('decision', 'stage', 'search_mode', 'plan')
                schema['properties'] = {**{k: props[k] for k in first},
                                        **{k: v for k, v in props.items() if k not in first}}
                options['response_format'] = {'type': 'json_schema', 'json_schema': {
                    'name': 'router_output', 'strict': True, 'schema': schema}}
            else:
                options.update(tools=[{'type': 'function', 'function': {'name': 'submit_plan',
                               'description': schema['description'], 'parameters': schema}}],
                               tool_choice={'type': 'function', 'function': {'name': 'submit_plan'}}, parallel_tool_calls=False)
        else:
            options['response_format'] = {'type': 'json_object'}
            if model['structured_outputs']:
                paths = self.settings.data['paths']
                schema = read_role_reference(role, 'output.schema.json', paths['skills_root'], paths['registry_file'])
                rows = schema['properties']['coverage' if role == 'judge' else 'claims']['items']['properties']
                if payload.get('evidence_ids'):
                    rows['evidence_ids']['items']['enum'] = list(payload['evidence_ids'])
                    if role == 'judge':
                        schema['properties']['issues']['items']['properties']['evidence_ids']['items']['enum'] = list(payload['evidence_ids'])
                if role == 'judge' and payload.get('requirements'):
                    rows['requirement']['enum'] = list(payload['requirements'])
                    count = len(payload['requirements'])
                    schema['properties']['coverage'].update(minItems=count, maxItems=count)
                if role == 'judge':
                    verdicts = schema['properties']['verdict']['enum']
                    if payload.get('incomparable_evidence_ids') or payload.get('pending_requested_tools'):
                        verdicts = [value for value in verdicts if value != 'pass']
                    no_retrieval = ('available_tools' in payload and not any(
                        spec.get('enabled') for spec in payload['available_tools'].values()))
                    if payload.get('review_rounds_remaining') == 0 or no_retrieval:
                        verdicts = [value for value in verdicts if value in ('pass', 'abstain')]
                        schema['properties']['return_to']['enum'] = ['answer']
                    schema['properties']['verdict']['enum'] = verdicts
                    if 'pass' not in verdicts:
                        schema['properties']['issues']['minItems'] = 1
                if role == 'answer' and (payload.get('judge') or {}).get('verdict') == 'abstain':
                    schema['properties']['status']['enum'] = ['partial', 'unavailable']
                if role == 'answer':
                    # The business plan is optional via null, not a missing strict-schema key.
                    schema['required'].append('inspection_plan')
                    plan = schema['properties']['inspection_plan']['properties']
                    plan['checks'].update(minItems=1, maxItems=3)
                    plan['historical_matches'].update(minItems=0, maxItems=2)
                    if payload.get('evidence_ids'):
                        for row in (plan['historical_matches']['items'], plan['checks']['items'], plan['eds_followup']):
                            row['properties']['evidence_ids']['items']['enum'] = list(payload['evidence_ids'])
                    if 'historical_reference_evidence' in payload:
                        references = payload['historical_reference_evidence']
                        if references:
                            plan['historical_matches']['items']['properties']['target']['enum'] = list(references)
                            if payload.get('verified_historical_reference_ids'):
                                plan['historical_matches']['minItems'] = 1
                        else:
                            plan['historical_matches']['maxItems'] = 0
                options['response_format'] = {'type': 'json_schema', 'json_schema': {
                    'name': role + '_output', 'strict': True, 'schema': schema}}
        # Count the complete request, including function schemas; this is not a token budget.
        request_characters = len(json.dumps(options, ensure_ascii=False))
        self.last_metrics['request_characters'] = request_characters
        if request_characters > self.settings.data['runtime']['max_context_characters']:
            self.last_metrics['elapsed_seconds'] = perf_counter() - started
            raise LLMError('MODEL_CONTEXT_LIMIT')
        try:
            with OpenAI(base_url=model['base_url'], api_key=os.environ[model['api_key_env']],
                        timeout=model['timeout_seconds'], max_retries=self.settings.data['runtime']['max_retries']) as client:
                completion = client.chat.completions.create(**options)
            usage = getattr(completion, 'usage', None)
            if usage is not None:
                def usage_value(*names):
                    if isinstance(usage, dict):
                        return next((usage[name] for name in names
                                     if name in usage and usage[name] is not None), None)
                    return next((value for name in names
                                 if (value := getattr(usage, name, None)) is not None), None)

                self.last_metrics.update(
                    input_tokens=usage_value('prompt_tokens', 'input_tokens'),
                    output_tokens=usage_value('completion_tokens', 'output_tokens'),
                    total_tokens=usage_value('total_tokens'))
            choice = completion.choices[0]
            message = choice.message
            self.last_metrics['finish_reason'] = getattr(choice, 'finish_reason', None)
            if self.last_metrics['finish_reason'] == 'length':
                raise LLMError('MODEL_OUTPUT_LIMIT')
            if getattr(message, 'refusal', None) or self.last_metrics['finish_reason'] == 'content_filter':
                raise LLMError('MODEL_OUTPUT_REFUSED')
            if role == 'router' and not structured_router:
                calls = message.tool_calls or []
                if len(calls) != 1 or calls[0].type != 'function' or calls[0].function.name != 'submit_plan':
                    raise LLMError('ROUTER_FUNCTION_CALL_REQUIRED')
                value = json.loads(calls[0].function.arguments)
                history.append({'role': 'assistant', 'content': message.content,
                    'tool_calls': [{'id': calls[0].id, 'type': 'function', 'function': {
                        'name': 'submit_plan', 'arguments': json.dumps(value, ensure_ascii=False, separators=(',', ':'))}}]})
                return value, calls[0].id
            if structured_router and message.tool_calls:
                raise LLMError('MODEL_RESPONSE_INVALID')
            value = json.loads(message.content or '')
            if structured_router:
                history.append({'role': 'assistant', 'content': json.dumps(value, ensure_ascii=False, separators=(',', ':'))})
            return value, None
        except OpenAIError as exc:
            raise LLMError('MODEL_REQUEST_FAILED: ' + type(exc).__name__) from None
        except (ValueError, IndexError, AttributeError, KeyError):
            raise LLMError('MODEL_RESPONSE_INVALID') from None
        finally:
            self.last_metrics['elapsed_seconds'] = perf_counter() - started
