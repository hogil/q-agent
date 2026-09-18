"""Runtime contracts with scripted model outputs and real synthetic databases."""
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

import agent
from config_loader import DEFAULT_CONFIG, Settings, load_config
from demo_data import generate
from incident_tools import ToolError
from skill_loader import compile_prompt


def plan(decision='execute', stage='incident', tool=None, arguments=None, search_mode='none'):
    return {'intents': ['search'], 'filters': {}, 'plan': [] if tool is None else [
        {'tool': tool, 'arguments': arguments or {}, 'depends_on': [], 'reason': 'contract check'}],
        'needs_skills': [], 'clarification': None, 'decision': decision,
        'stage': stage, 'search_mode': search_mode, 'limitations': []}


def judge(payload, verdict='pass'):
    ids = payload['evidence_ids']
    return {'verdict': verdict, 'return_to': 'answer' if verdict == 'pass' else 'router',
            'coverage': [{'requirement': payload['question'], 'status': 'satisfied' if verdict == 'pass' else 'missing', 'evidence_ids': ids}],
            'issues': [] if verdict == 'pass' else [{'type': 'missing', 'reason': 'another passage required',
                'next_action': 'retrieve another passage', 'evidence_ids': ids}]}


def answer(payload):
    return {'status': 'answered', 'answer': 'Synthetic contract response, not model quality evidence.',
            'claims': [{'claim_id': 'c1', 'text': 'Synthetic response.', 'evidence_ids': payload['evidence_ids']}],
            'limitations': []}


class ScriptedClient:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.calls = []

    def call(self, role, system_prompt, payload, history):
        expected_role, output = next(self.steps)
        if role != expected_role:
            raise AssertionError((role, expected_role))
        self.calls.append((role, system_prompt, copy.deepcopy(payload)))
        output = output(payload) if callable(output) else output
        call_id = 'call-' + str(len(self.calls)) if role == 'router' else None
        if role == 'router':
            history.append({'role': 'assistant', 'tool_calls': [{'id': call_id, 'type': 'function',
                'function': {'name': 'submit_plan', 'arguments': json.dumps(output)}}]})
        return output, call_id


class AgentContracts(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        data = load_config(DEFAULT_CONFIG, DEFAULT_CONFIG.parent / 'demo.yaml').data
        root = Path(self.temp.name)
        data['paths'].update(data_root=str(root), golden_file=str(root / 'golden.jsonl'))
        data['database']['sqlite_file'] = str(root / 'incidents.sqlite')
        data['meetings']['sqlite_file'] = str(root / 'meetings.sqlite')
        self.settings = Settings(data, ())
        generate(self.settings)

    def run_script(self, steps, **kwargs):
        client = ScriptedClient(steps)
        with patch.object(agent, 'RoleClient', return_value=client):
            result = agent.run(self.settings, 'synthetic contract question', 'tester',
                               as_of='2026-03-31', **kwargs)
        return result, client

    @staticmethod
    def lookup(number='SYN-2026-01'):
        return ('router', plan(tool='find_incidents', arguments={'incident_number': number}, search_mode='sql_exact'))

    @staticmethod
    def finish_steps(stage='tools'):
        return [('router', plan('ready_for_judge', stage)), ('judge', judge), ('answer', answer)]

    def test_auto_full_sequence_and_role_order(self):
        self.settings.data['runtime']['prompt_examples'] = True
        steps = [('router', plan('route')), self.lookup(),
                 ('router', plan(stage='tools', tool='list_incident_lots')),
                 ('router', plan(stage='tools', tool='list_incident_wafers')),
                 ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'SYN'})),
                 *self.finish_steps()]
        result, client = self.run_script(steps, request_scope='auto')
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(result['tool_calls'], 4)
        self.assertEqual([x[0] for x in client.calls][-2:], ['judge', 'answer'])
        self.assertIn('syn-chunk-002', [x['chunk_id'] for x in result['evidence'][-1]['result']['items']])
        self.assertEqual(result['request_scope'], 'incident')

    def test_independent_never_opens_incident_db(self):
        steps = [('router', plan('route', 'independent')),
                 ('router', plan(stage='independent', tool='search_meeting_minutes', arguments={'query': '교정'})),
                 *self.finish_steps('independent')]
        with patch.object(agent, 'open_incident_tools', side_effect=AssertionError('DB must not open')):
            result, _ = self.run_script(steps, request_scope='auto')
        self.assertEqual(result['status'], 'answered', result)
        self.assertIsNone(result['scope_id'])
        self.assertEqual(result['evidence'][-1]['result']['incident_ids'], None)

    def test_auto_cannot_execute_without_route(self):
        with patch.object(agent, 'open_incident_tools', side_effect=AssertionError('DB must not open')):
            result, _ = self.run_script([self.lookup()] * 3, request_scope='auto')
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['tool_calls'], 0)

    def test_incident_cannot_search_minutes_before_db(self):
        step = ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'SYN'}))
        result, _ = self.run_script([step] * 3)
        self.assertEqual(result['tool_calls'], 0)
        self.assertEqual(result['status'], 'unavailable')

    def test_independent_cannot_call_db_or_reroute(self):
        for step in (self.lookup(), ('router', plan('route'))):
            with self.subTest(step=step):
                result, _ = self.run_script([step] * 3, request_scope='independent')
                self.assertEqual(result['tool_calls'], 0)
                self.assertEqual(result['status'], 'unavailable')

    def test_disabled_catalog_cannot_be_enabled_by_config(self):
        catalog = agent.read_role_reference('router', 'tools.json',
            self.settings.data['paths']['skills_root'], self.settings.data['paths']['registry_file'])
        catalog['search_meeting_minutes']['enabled'] = False
        step = ('router', plan(stage='independent', tool='search_meeting_minutes', arguments={'query': '교정'}))
        with patch.object(agent, 'read_role_reference', return_value=catalog):
            result, _ = self.run_script([step] * 3, request_scope='independent')
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['tool_calls'], 0)

    def test_model_cannot_override_cutoff_or_ids(self):
        for injected in ({'as_of': '2099-01-01'}, {'incident_ids': ['anything']}):
            step = ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'SYN', **injected}))
            result, _ = self.run_script([self.lookup(), step, step, step])
            self.assertEqual(result['tool_calls'], 1)
            self.assertEqual(result['status'], 'unavailable')

    def test_multiple_candidates_need_user_selection(self):
        step = ('router', plan(tool='find_incidents', arguments={'city': 'SYNTH-CITY'}, search_mode='sql_filter'))
        result, _ = self.run_script([step])
        self.assertEqual(result['status'], 'needs_selection')
        self.assertEqual(len(result['candidates']), 9)

    def test_no_incident_match_does_not_search_globally(self):
        steps = [self.lookup('SYN-2026-99'),
                 ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': '교정'})),
                 ('router', {**plan('blocked', 'tools'), 'limitations': ['no evidence']})]
        result, _ = self.run_script(steps)
        observation = result['evidence'][-1]['result']
        self.assertEqual(observation['status'], 'NO_MATCH')
        self.assertEqual(observation['incident_ids'], [])

    def test_meeting_failure_cannot_be_cleared_by_formatting(self):
        steps = [self.lookup(),
                 ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'SYN'})),
                 ('router', plan('ready_for_judge', 'tools')), ('judge', judge),
                 ('router', {**plan('blocked', 'tools'), 'limitations': ['retrieval failed']})]
        with patch.object(agent.MeetingTools, 'search', side_effect=ToolError('SYNTHETIC_FAILURE')):
            result, client = self.run_script(steps)
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('answer', [x[0] for x in client.calls])
        self.assertEqual(client.calls[-1][2]['code_gate'], 'FAIL')

    def test_judge_returns_to_same_router_with_scope(self):
        steps = [self.lookup(), ('router', plan('ready_for_judge', 'tools')),
                 ('judge', lambda payload: judge(payload, 'need_evidence')),
                 ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'SYN'})),
                 *self.finish_steps()]
        result, client = self.run_script(steps)
        self.assertEqual(result['status'], 'answered', result)
        router_after_judge = client.calls[3][2]
        self.assertTrue(router_after_judge['scope_valid'])
        self.assertEqual(router_after_judge['judge']['verdict'], 'need_evidence')

    def test_partial_query_match_reaches_judge_and_can_trigger_requery(self):
        steps = [self.lookup(),
                 ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'SYN absentword'})),
                 ('router', plan('ready_for_judge', 'tools')),
                 ('judge', lambda payload: judge(payload, 'need_evidence')),
                 ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': '히터'})),
                 *self.finish_steps()]
        result, client = self.run_script(steps)
        self.assertEqual(result['status'], 'answered', result)
        first_review = next(payload for role, _, payload in client.calls if role == 'judge')
        self.assertEqual(first_review['evidence'][-1]['result']['query_match']['strategy'], 'scoped_any_terms')
        self.assertEqual(result['evidence'][-1]['result']['query_match']['strategy'], 'all_terms')
        self.assertEqual(result['evidence'][-1]['result']['incident_ids'], ['synthetic-pk-2026-01'])
        self.assertEqual(result['tool_calls'], 3)

    def test_selected_scope_never_admits_other_incident_minutes(self):
        step = ('router', plan(tool='find_incidents', arguments={'city': 'SYNTH-CITY'}, search_mode='sql_filter'))
        steps = [step, ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'SYN'})),
                 *self.finish_steps()]
        result, _ = self.run_script(steps, selected=['synthetic-pk-2026-01'])
        self.assertEqual(result['status'], 'answered', result)
        meeting = result['evidence'][-1]['result']
        self.assertEqual(meeting['incident_ids'], ['synthetic-pk-2026-01'])
        self.assertTrue(all('synthetic-pk-2026-01' in item['incident_ids'] for item in meeting['items']))

    def test_invalid_plan_can_recover_without_repeating_db_query(self):
        steps = [self.lookup(), ('router', {**plan('ready_for_judge', 'tools'), 'unexpected': True}),
                 *self.finish_steps()]
        result, _ = self.run_script(steps)
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(result['tool_calls'], 1)

    def test_missing_models_do_not_fallback_to_scripted_answers(self):
        result = agent.run(self.settings, 'example', 'tester')
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['tool_calls'], 0)
        self.assertIn('ROLE_REQUIRES_ENABLED_API_MODEL', result['limitations'][0])

    def test_optional_examples_change_prompt_not_contract(self):
        for role in ('router', 'judge', 'answer'):
            baseline = compile_prompt(role, ['meetings'], settings=self.settings)
            data = copy.deepcopy(self.settings.data)
            data['runtime']['prompt_examples'] = True
            candidate = compile_prompt(role, ['meetings'], settings=Settings(data, ()))
            self.assertNotEqual(baseline['prompt_sha256'], candidate['prompt_sha256'])
            self.assertEqual(baseline['release'], candidate['release'])
            self.assertEqual(set(candidate['loaded_files']) - set(baseline['loaded_files']),
                             {f'skills/roles/{role}/references/examples.md'})

    def test_generator_refuses_overwrite_and_outside_paths(self):
        with self.assertRaises(FileExistsError):
            generate(self.settings)
        data = copy.deepcopy(self.settings.data)
        data['database']['sqlite_file'] = str(Path(self.temp.name).parent / 'outside.sqlite')
        with self.assertRaisesRegex(ValueError, 'inside paths.data_root'):
            generate(Settings(data, ()))
        for section, key, value in (('environment', None, 'onprem'), ('meetings', 'backend', 'http')):
            data = copy.deepcopy(self.settings.data)
            if key:
                data[section][key] = value
            else:
                data[section] = value
            with self.assertRaises(ValueError):
                generate(Settings(data, ()))

    def test_demo_overlay_resolves_dependent_paths_after_merge(self):
        from run_agent import main
        target = Path(self.temp.name) / 'overlay-data'
        overlay = Path(self.temp.name) / 'demo.local.yaml'
        overlay.write_text('paths:\n  data_root: ' + json.dumps(str(target)) + '\n', encoding='utf-8')
        output = io.StringIO()
        with patch.object(sys, 'argv', ['run_agent.py', '--demo', '--demo-overlay', str(overlay), '--mode', 'prepare-demo']), redirect_stdout(output):
            self.assertEqual(main(), 0)
        result = json.loads(output.getvalue())
        self.assertTrue(all(Path(path).parent == target for path in result['paths'].values()))


if __name__ == '__main__':
    unittest.main()
