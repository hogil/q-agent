import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from config_loader import DEFAULT_CONFIG, Settings, load_config
import llm_client
from llm_client import LLMError, RoleClient
from skill_loader import read_role_reference


def completion(*, arguments='{}', content=None, finish_reason='tool_calls',
               refusal=None, tool_call=True):
    message = SimpleNamespace(content=content, refusal=refusal,
                              tool_calls=[])
    if tool_call:
        message.tool_calls = [SimpleNamespace(
            id='call-1', type='function',
            function=SimpleNamespace(name='submit_plan', arguments=arguments))]
    return SimpleNamespace(choices=[SimpleNamespace(
        finish_reason=finish_reason, message=message)])


class RoleClientTests(unittest.TestCase):
    def setUp(self):
        data = load_config(DEFAULT_CONFIG).data
        data['models']['text'].update(
            enabled=True, mode='api', base_url='https://llm.invalid/v1',
            api_key_env='QAGENT_TEST_LLM_KEY', served_model='test-model')
        self.settings = Settings(data, ())
        self.client_factory = MagicMock()
        self.api = self.client_factory.return_value.__enter__.return_value
        self.create = self.api.chat.completions.create
        self.openai = patch.object(llm_client, 'OpenAI', self.client_factory)
        self.openai.start()
        self.addCleanup(self.openai.stop)
        self.env = patch.dict('os.environ', {'QAGENT_TEST_LLM_KEY': 'test-key'}, clear=False)
        self.env.start()
        self.addCleanup(self.env.stop)

    def make_client(self):
        return RoleClient(self.settings)

    def test_requests_have_one_system_and_one_current_user(self):
        router_history = []
        router_response = completion(arguments='{}')
        self.create.side_effect = [router_response, router_response,
                                   completion(content='{"verdict":"pass"}',
                                              tool_call=False),
                                   completion(content='{"status":"answered"}',
                                              tool_call=False)]
        client = self.make_client()

        client.call('router', 'router system', {'step': 1}, router_history)
        router_history.append({'role': 'tool', 'tool_call_id': 'call-1', 'content': '{}'})
        client.call('router', 'router system', {'step': 2}, router_history)
        client.call('judge', 'judge system', {'step': 3}, [])
        client.call('answer', 'answer system', {'step': 4}, [])

        self.assertEqual(len(router_history), 3)
        for call in self.create.call_args_list:
            messages = call.kwargs['messages']
            self.assertEqual(sum(message['role'] == 'system' for message in messages), 1)
            self.assertEqual(sum(message['role'] == 'user' for message in messages), 1)
            self.assertEqual(messages[-1]['role'], 'user')
        self.assertEqual(json.loads(self.create.call_args_list[1].kwargs['messages'][-1]['content']),
                         {'step': 2, 'response_contract': {'transport': 'function_call', 'name': 'submit_plan'}})
        self.assertEqual(json.loads(self.create.call_args_list[2].kwargs['messages'][-1]['content']),
                         {'step': 3})
        self.assertEqual([message['role'] for message in self.create.call_args_list[1].kwargs['messages']],
                         ['system', 'assistant', 'tool', 'user'])
        for call in self.create.call_args_list[2:]:
            self.assertEqual([message['role'] for message in call.kwargs['messages']], ['system', 'user'])

    def test_router_success_appends_only_returned_assistant_tool_call(self):
        prior = [{'role': 'assistant', 'content': None, 'tool_calls': [{
            'id': 'prior', 'type': 'function',
            'function': {'name': 'submit_plan', 'arguments': '{}'}}]},
            {'role': 'tool', 'tool_call_id': 'prior', 'content': '{}'}]
        history = copy.deepcopy(prior)
        response = completion(arguments='{"decision":"route"}', content='assistant note')
        self.create.return_value = response

        value, call_id = self.make_client().call(
            'router', 'system', {'question': 'next'}, history)

        self.assertEqual(value, {'decision': 'route'})
        self.assertEqual(call_id, 'call-1')
        self.assertEqual(history, prior + [{
            'role': 'assistant', 'content': 'assistant note', 'tool_calls': [{
                'id': 'call-1', 'type': 'function',
                'function': {'name': 'submit_plan', 'arguments': '{"decision":"route"}'}}]}])
        self.assertNotIn('user', [message['role'] for message in history])

    def test_judge_and_answer_use_json_mode_without_router_tools(self):
        self.create.side_effect = [
            completion(content='{"verdict":"pass"}', tool_call=False),
            completion(content='{"status":"answered"}', tool_call=False),
        ]
        client = self.make_client()

        self.assertEqual(client.call('judge', 'judge', {}, [])[0], {'verdict': 'pass'})
        self.assertEqual(client.call('answer', 'answer', {}, [])[0], {'status': 'answered'})

        for call in self.create.call_args_list:
            self.assertEqual(call.kwargs['response_format'], {'type': 'json_object'})
            self.assertNotIn('tools', call.kwargs)
            self.assertNotIn('tool_choice', call.kwargs)

    def test_router_uses_submit_plan_tool_and_no_json_mode(self):
        self.create.return_value = completion(arguments='{}')

        self.make_client().call('router', 'router', {}, [])

        options = self.create.call_args.kwargs
        self.assertEqual(options['tools'][0]['function']['name'], 'submit_plan')
        self.assertEqual(options['tools'][0]['function']['description'],
                         options['tools'][0]['function']['parameters']['description'])
        self.assertEqual(options['tool_choice']['function']['name'], 'submit_plan')
        self.assertFalse(options['parallel_tool_calls'])
        self.assertNotIn('response_format', options)

    def test_structured_router_uses_typed_plans_without_fake_function_calls(self):
        self.settings.data['models']['text']['structured_outputs'] = True
        output = {'decision': 'ready_for_judge', 'plan': []}
        self.create.return_value = completion(content=json.dumps(output), tool_call=False)
        history = [{'role': 'assistant', 'content': 'stale'}]
        payload = {'evidence_ids': ['e1'], 'last_error': 'TYPE: $.plan[0].arguments.city'}
        result, call_id = self.make_client().call('router', 'router', payload, history)
        options = self.create.call_args.kwargs
        self.assertEqual(result, output)
        self.assertIsNone(call_id)
        self.assertEqual(json.loads(history[-1]['content']), output)
        self.assertNotIn('tool_calls', history[-1])
        self.assertNotIn('tools', options)
        self.assertNotIn('tool_choice', options)
        self.assertEqual([m['role'] for m in options['messages']], ['system', 'assistant', 'user'])
        current = json.loads(options['messages'][-1]['content'])
        self.assertEqual(current['response_contract']['transport'], 'json_schema')
        self.assertEqual(current['evidence_ids'], ['e1'])
        self.assertEqual(current['last_error'], payload['last_error'])
        self.assertNotIn('response_contract', payload)
        schema = options['response_format']['json_schema']['schema']
        self.assertEqual(list(schema['properties'])[:4], ['decision', 'stage', 'search_mode', 'plan'])
        variants = schema['properties']['plan']['items']['anyOf']
        find = next(v for v in variants if v['properties']['tool']['enum'] == ['find_incidents'])
        self.assertEqual(find['properties']['arguments']['properties']['city']['type'], 'string')
        self.assertFalse(find['properties']['arguments']['additionalProperties'])

    def test_structured_router_omits_completed_tools_from_plan_schema(self):
        self.settings.data['models']['text']['structured_outputs'] = True
        output = {'decision': 'ready_for_judge', 'plan': []}
        self.create.return_value = completion(content=json.dumps(output), tool_call=False)
        catalog = read_role_reference('router', 'tools.json',
                                      self.settings.data['paths']['skills_root'],
                                      self.settings.data['paths']['registry_file'])
        available = {name: {key: value for key, value in spec.items() if key != 'parameters'}
                     for name, spec in catalog.items() if name != 'find_incidents'}

        self.make_client().call('router', 'router', {'available_tools': available}, [])
        variants = self.create.call_args.kwargs['response_format']['json_schema']['schema']
        names = {variant['properties']['tool']['enum'][0]
                 for variant in variants['properties']['plan']['items']['anyOf']}
        self.assertNotIn('find_incidents', names)

    def test_structured_router_with_no_available_tools_has_zero_plan_schema(self):
        self.settings.data['models']['text']['structured_outputs'] = True
        self.create.return_value = completion(
            content=json.dumps({'decision': 'load_skills', 'plan': [], 'needs_skills': ['meetings']}),
            tool_call=False)

        self.make_client().call('router', 'router', {'available_tools': {}}, [])
        plan_schema = self.create.call_args.kwargs['response_format']['json_schema']['schema']
        items = plan_schema['properties']['plan']['items']
        self.assertEqual(items['properties']['tool']['enum'], [])

    def test_pending_requested_source_cannot_be_skipped_by_structured_router(self):
        self.settings.data['models']['text']['structured_outputs'] = True
        self.create.return_value = completion(content='{}', tool_call=False)
        self.make_client().call('router', 'router', {
            'pending_requested_tools': ['compare_sem_images'],
            'available_tools': {'list_comparison_assets': {'enabled': True, 'modalities': ['sem']}},
        }, [])
        schema = self.create.call_args.kwargs['response_format']['json_schema']['schema']
        self.assertNotIn('ready_for_judge', schema['properties']['decision']['enum'])
        self.assertEqual(schema['properties']['plan']['items']['anyOf'][0]['properties']['arguments']
                         ['properties']['modality']['enum'], ['sem'])

    def test_structured_image_plan_only_accepts_discovered_ids_for_each_item(self):
        self.settings.data['models']['text']['structured_outputs'] = True
        self.create.return_value = completion(content='{}', tool_call=False)
        available = {'compare_sem_images': {'enabled': True, 'asset_ids_by_item': {
            'item-a': ['a1', 'a2'], 'item-b': ['b1', 'b2']}}}
        self.make_client().call('router', 'router', {'available_tools': available}, [])
        variants = self.create.call_args.kwargs['response_format']['json_schema']['schema']
        arguments = [v['properties']['arguments']['properties']
                     for v in variants['properties']['plan']['items']['anyOf']]
        self.assertEqual([(a['item']['enum'], a['asset_ids']['items']['enum']) for a in arguments],
                         [(['item-a'], ['a1', 'a2']), (['item-b'], ['b1', 'b2'])])

    def test_structured_router_rejects_prose_or_unexpected_tool_calls(self):
        self.settings.data['models']['text']['structured_outputs'] = True
        for response in (completion(content='not a plan', tool_call=False), completion(content='{}')):
            self.create.return_value = response
            with self.assertRaisesRegex(LLMError, 'MODEL_RESPONSE_INVALID'):
                self.make_client().call('router', 'router', {}, [])

    def test_structured_router_context_budget_includes_expanded_tool_schemas(self):
        self.settings.data['models']['text']['structured_outputs'] = True
        self.create.return_value = completion(content='{}', tool_call=False)
        client = self.make_client()
        client.call('router', 'router', {}, [])
        size = len(json.dumps(self.create.call_args.kwargs, ensure_ascii=False))
        self.settings.data['runtime']['max_context_characters'] = size
        client.call('router', 'router', {}, [])
        self.settings.data['runtime']['max_context_characters'] = size - 1
        self.create.reset_mock()
        with self.assertRaisesRegex(LLMError, 'MODEL_CONTEXT_LIMIT'):
            client.call('router', 'router', {}, [])
        self.create.assert_not_called()

    def test_configured_structured_outputs_preserve_schema_and_current_evidence_ids(self):
        self.settings.data['models']['text']['structured_outputs'] = True
        self.create.return_value = completion(content='{}', tool_call=False)
        client = self.make_client()
        client.call('answer', 'answer', {'evidence_ids': ['e7']}, [])
        output = self.create.call_args.kwargs['response_format']
        self.assertEqual(output['type'], 'json_schema')
        self.assertEqual(output['json_schema']['schema']['properties']['claims']['items']
                         ['properties']['evidence_ids']['items']['enum'], ['e7'])
        client.call('judge', 'judge', {'evidence_ids': ['e2'], 'requirements': ['current question']}, [])
        rows = self.create.call_args.kwargs['response_format']['json_schema']['schema']['properties']['coverage']['items']['properties']
        self.assertEqual(rows['requirement']['enum'], ['current question'])
        self.assertEqual(rows['evidence_ids']['items']['enum'], ['e2'])
        properties = self.create.call_args.kwargs['response_format']['json_schema']['schema']['properties']
        self.assertEqual(properties['coverage']['minItems'], 1)
        self.assertEqual(properties['coverage']['maxItems'], 1)
        self.assertEqual(properties['issues']['items']['properties']['evidence_ids']['items']['enum'], ['e2'])

    def test_disabled_or_non_api_model_fails_at_initialization(self):
        for enabled, mode in ((False, 'api'), (True, 'local')):
            with self.subTest(enabled=enabled, mode=mode):
                data = copy.deepcopy(self.settings.data)
                data['models']['text'].update(enabled=enabled, mode=mode)
                with self.assertRaisesRegex(LLMError, 'ROLE_REQUIRES_ENABLED_API_MODEL: router'):
                    RoleClient(Settings(data, ()))

    def test_judge_cannot_pass_incomparable_evidence_or_exceed_review_budget(self):
        self.settings.data['models']['text']['structured_outputs'] = True
        self.create.return_value = completion(content='{}', tool_call=False)
        self.make_client().call('judge', 'judge', {
            'incomparable_evidence_ids': ['e6'], 'review_rounds_remaining': 0,
            'evidence_ids': ['e6'], 'requirements': ['compare selected images'],
        }, [])
        schema = self.create.call_args.kwargs['response_format']['json_schema']['schema']
        self.assertEqual(schema['properties']['verdict']['enum'], ['abstain'])
        self.assertEqual(schema['properties']['return_to']['enum'], ['answer'])
        self.make_client().call('answer', 'answer', {'judge': {'verdict': 'abstain'}}, [])
        schema = self.create.call_args.kwargs['response_format']['json_schema']['schema']
        self.assertEqual(schema['properties']['status']['enum'], ['partial', 'unavailable'])
        self.make_client().call('judge', 'judge', {
            'incomparable_evidence_ids': ['e6'], 'review_rounds_remaining': 2,
            'available_tools': {'compare_sem_images': {'enabled': False}},
        }, [])
        schema = self.create.call_args.kwargs['response_format']['json_schema']['schema']
        self.assertEqual(schema['properties']['verdict']['enum'], ['abstain'])
        self.assertEqual(schema['properties']['return_to']['enum'], ['answer'])

    def test_missing_api_key_fails_at_initialization(self):
        with patch.dict('os.environ', {}, clear=True):
            with self.assertRaisesRegex(LLMError, 'MODEL_API_KEY_ENV_MISSING: router'):
                self.make_client()

    def test_incomplete_or_refused_completion_fails(self):
        cases = (
            completion(finish_reason='length'),
            completion(finish_reason='content_filter'),
            completion(refusal='safety refusal'),
        )
        for response in cases:
            with self.subTest(response=response.choices[0].finish_reason):
                self.create.reset_mock()
                self.create.return_value = response
                with self.assertRaisesRegex(LLMError, 'MODEL_OUTPUT_INCOMPLETE_OR_REFUSED'):
                    self.make_client().call('router', 'system', {}, [])

    def test_malformed_completion_fails(self):
        cases = (
            completion(content='{not-json}', tool_call=False),
            completion(arguments='{not-json}'),
            completion(tool_call=False),
        )
        for response in cases:
            with self.subTest(response=response):
                self.create.reset_mock()
                self.create.return_value = response
                role = 'judge' if response.choices[0].message.tool_calls == [] and response.choices[0].message.content else 'router'
                with self.assertRaisesRegex(LLMError, 'MODEL_RESPONSE_INVALID|ROUTER_FUNCTION_CALL_REQUIRED'):
                    self.make_client().call(role, 'system', {}, [])

    def test_context_bound_rejection_prevents_api_invocation(self):
        self.settings.data['runtime']['max_context_characters'] = 1
        client = self.make_client()

        with self.assertRaisesRegex(LLMError, 'MODEL_CONTEXT_LIMIT'):
            client.call('router', 'system', {'large': 'payload'}, [])
        self.create.assert_not_called()
        self.client_factory.assert_not_called()

    def test_payload_and_arguments_are_compact_without_losing_values(self):
        value = {'text': '\uad50\uc815 with spaces', 'values': [None, True, 1.25]}
        raw = json.dumps(value, ensure_ascii=True, indent=4)
        self.create.return_value = completion(arguments=raw)
        history = []
        returned, _ = self.make_client().call('router', 'system', value, history)
        compact = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        self.assertEqual(returned, value)
        self.assertEqual(json.loads(self.create.call_args.kwargs['messages'][-1]['content']),
                         {**value, 'response_contract': {'transport': 'function_call', 'name': 'submit_plan'}})
        self.assertEqual(history[-1]['tool_calls'][0]['function']['arguments'], compact)

    def test_context_bound_includes_tool_schema(self):
        self.create.return_value = completion()
        client = self.make_client()
        client.call('router', 'system', {}, [])
        options = self.create.call_args.kwargs
        self.settings.data['runtime']['max_context_characters'] = len(json.dumps(options['messages'], ensure_ascii=False)) + 1
        self.client_factory.reset_mock()
        with self.assertRaisesRegex(LLMError, 'MODEL_CONTEXT_LIMIT'):
            client.call('router', 'system', {}, [])
        self.client_factory.assert_not_called()

    def test_complete_request_bound_accepts_exact_limit(self):
        for role in ('router', 'judge', 'answer'):
            with self.subTest(role=role):
                self.settings.data['runtime']['max_context_characters'] = 120000
                self.create.return_value = completion(content='{}')
                client = self.make_client()
                client.call(role, 'system', {}, [])
                size = len(json.dumps(self.create.call_args.kwargs, ensure_ascii=False))
                self.settings.data['runtime']['max_context_characters'] = size
                client.call(role, 'system', {}, [])
                self.settings.data['runtime']['max_context_characters'] = size - 1
                self.client_factory.reset_mock()
                with self.assertRaisesRegex(LLMError, 'MODEL_CONTEXT_LIMIT'):
                    client.call(role, 'system', {}, [])
                self.client_factory.assert_not_called()


if __name__ == '__main__':
    unittest.main()
