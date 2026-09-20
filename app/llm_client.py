"""OpenAI-compatible Chat Completions transport for configured role models."""
import json
import os

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
        profile = self.settings.model_profile(role)
        model = profile['deployment']
        messages = [{'role': 'system', 'content': system_prompt}, *history,
                    {'role': 'user', 'content': json.dumps(payload, ensure_ascii=False, separators=(',', ':'))}]
        options = dict(model=model['served_model'], messages=messages, temperature=profile['temperature'],
                       max_tokens=profile['max_output_tokens'])
        if role == 'router':
            paths = self.settings.data['paths']
            schema = read_role_reference('router', 'output.schema.json', paths['skills_root'], paths['registry_file'])
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
                if role == 'judge' and payload.get('requirements'):
                    rows['requirement']['enum'] = list(payload['requirements'])
                options['response_format'] = {'type': 'json_schema', 'json_schema': {
                    'name': role + '_output', 'strict': True, 'schema': schema}}
        # Count the complete request, including function schemas; this is not a token budget.
        if len(json.dumps(options, ensure_ascii=False)) > self.settings.data['runtime']['max_context_characters']:
            raise LLMError('MODEL_CONTEXT_LIMIT')
        try:
            with OpenAI(base_url=model['base_url'], api_key=os.environ[model['api_key_env']],
                        timeout=model['timeout_seconds'], max_retries=self.settings.data['runtime']['max_retries']) as client:
                completion = client.chat.completions.create(**options)
            choice = completion.choices[0]
            message = choice.message
            if choice.finish_reason in ('length', 'content_filter') or message.refusal:
                raise LLMError('MODEL_OUTPUT_INCOMPLETE_OR_REFUSED')
            if role == 'router':
                calls = message.tool_calls or []
                if len(calls) != 1 or calls[0].type != 'function' or calls[0].function.name != 'submit_plan':
                    raise LLMError('ROUTER_FUNCTION_CALL_REQUIRED')
                value = json.loads(calls[0].function.arguments)
                history.append({'role': 'assistant', 'content': message.content,
                    'tool_calls': [{'id': calls[0].id, 'type': 'function', 'function': {
                        'name': 'submit_plan', 'arguments': json.dumps(value, ensure_ascii=False, separators=(',', ':'))}}]})
                return value, calls[0].id
            return json.loads(message.content or ''), None
        except OpenAIError as exc:
            raise LLMError('MODEL_REQUEST_FAILED: ' + type(exc).__name__) from None
        except (ValueError, IndexError, AttributeError, KeyError):
            raise LLMError('MODEL_RESPONSE_INVALID') from None
