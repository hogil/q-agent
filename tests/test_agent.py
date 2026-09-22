"""Runtime contracts with scripted model outputs and real synthetic databases."""
import copy
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

import agent
from config_loader import DEFAULT_CONFIG, Settings, load_config
from demo_data import generate
from incident_tools import ToolError
from prompt_contracts import validate_output
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


def partial_answer(payload):
    return {'status': 'partial', 'answer': 'Synthetic comparison findings are available, but physical alignment was not verified.',
            'claims': [{'claim_id': 'c1', 'text': 'The model returned an incomparable result with recorded findings.',
                        'evidence_ids': payload['evidence_ids']}],
            'limitations': ['alignment_verified=false; similarity is unavailable; findings are not semantic certainty.']}


def abstain(payload):
    return {'verdict': 'abstain', 'return_to': 'answer',
            'coverage': [{'requirement': payload['question'], 'status': 'unavailable',
                          'evidence_ids': payload['evidence_ids']}],
            'issues': [{'type': 'alignment_unavailable',
                        'reason': 'Synthetic comparison did not verify physical alignment.',
                        'next_action': 'Report findings with the alignment limitation; do not repeat the same comparison.',
                        'evidence_ids': payload['evidence_ids']}]}


class ScriptedClient:
    def __init__(self, steps):
        self.steps = iter(steps)
        self.calls = []
        self.histories = []

    def call(self, role, system_prompt, payload, history):
        expected_role, output = next(self.steps)
        if role != expected_role:
            raise AssertionError((role, expected_role))
        self.calls.append((role, system_prompt, copy.deepcopy(payload)))
        self.histories.append(copy.deepcopy(history))
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

    def test_engineering_snapshot_requires_scope_and_is_tool_evidence(self):
        query = Mock(return_value={'status': 'OK', 'synthetic': True,
                                   'sections': {'trend': {'count': 4}}})
        result, client = self.run_script([
            self.lookup(), ('router', plan(stage='tools', tool='get_engineering_snapshot')),
            *self.finish_steps()], engineering_query=query)
        self.assertEqual(result['status'], 'answered', result)
        query.assert_called_once()
        self.assertEqual(query.call_args.kwargs['actor'], 'tester')
        self.assertEqual(query.call_args.kwargs['as_of'], '2026-03-31')
        self.assertTrue(query.call_args.kwargs['incident_ids'])
        self.assertEqual(result['evidence'][-1]['source'], 'get_engineering_snapshot')
        self.assertEqual(client.calls[-1][2]['evidence'][-1]['result']['sections']['trend']['count'], 4)

    def test_related_search_keeps_scope_and_cannot_bypass_incident_gate(self):
        related = ('router', plan(stage='tools', tool='search_related_incidents', arguments={'terms': ['SYN']}))
        result, client = self.run_script([self.lookup(), related, *self.finish_steps()])
        self.assertEqual(result['status'], 'answered', result)
        initial, candidates = result['evidence'][:2]
        self.assertEqual(result['scope_id'], initial['result']['scope_id'])
        self.assertFalse(candidates['result']['scope_changed'])
        current_ids = {row['incident_id'] for row in initial['result']['data']}
        self.assertTrue(all(row['incident_id'] not in current_ids for row in candidates['result']['items']))
        self.assertIn('CANDIDATES_NOT_CONFIRMED_RELATION', candidates['result']['limitations'])
        result, _ = self.run_script([related, related, related])
        self.assertEqual(result['tool_calls'], 0)

    def test_related_search_uses_date_cutoff_and_bound_terms(self):
        related = ('router', plan(stage='tools', tool='search_related_incidents',
                                  arguments={'terms': ["xx' OR 1=1 --"]}))
        result, _ = self.run_script([self.lookup(), related, *self.finish_steps()])
        self.assertEqual(result['evidence'][1]['result']['status'], 'NO_MATCH')

    def test_unselected_related_source_is_disabled(self):
        result, client = self.run_script([self.lookup(), *self.finish_steps()], related_search=False)
        self.assertFalse(client.calls[1][2]['available_tools']['search_related_incidents']['enabled'])

    def test_independent_followups_share_one_router_plan(self):
        batch = plan(stage='tools', tool='list_incident_lots')
        batch['plan'] += plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'SYN'})['plan']
        result, client = self.run_script([self.lookup(), ('router', batch), *self.finish_steps()])
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(result['tool_calls'], 3)
        self.assertEqual(result['llm_calls'], 5)
        receipt = json.loads(client.histories[2][-1]['content'])
        self.assertEqual([row['tool'] for row in receipt['observations']],
                         ['list_incident_lots', 'search_meeting_minutes'])

    def test_batch_preflight_rejects_invalid_tail_without_running_prefix(self):
        self.settings.data['runtime']['max_retries'] = 0
        batch = plan(stage='tools', tool='list_incident_lots')
        batch['plan'] += plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 123})['plan']
        result, _ = self.run_script([self.lookup(), ('router', batch)])
        self.assertEqual(result['tool_calls'], 1)
        self.assertEqual(len(result['evidence']), 1)
        self.assertIn('TYPE:', result['limitations'][0])

    def test_batch_cannot_cross_unresolved_lot_prerequisite(self):
        self.settings.data['runtime']['max_retries'] = 0
        batch = plan(stage='tools', tool='list_incident_lots')
        batch['plan'] += plan(stage='tools', tool='list_incident_wafers')['plan']
        result, _ = self.run_script([self.lookup(), ('router', batch)])
        self.assertEqual(result['tool_calls'], 1)
        self.assertIn('BATCH_TOOL_NOT_READY', result['limitations'][0])

    def test_batch_budget_is_checked_before_running_any_followup(self):
        self.settings.data['runtime'].update(max_retries=0, max_tool_calls=2)
        batch = plan(stage='tools', tool='list_incident_lots')
        batch['plan'] += plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'SYN'})['plan']
        result, _ = self.run_script([self.lookup(), ('router', batch)])
        self.assertEqual(result['tool_calls'], 1)
        self.assertEqual(len(result['evidence']), 1)
        self.assertIn('TOOL_BUDGET', result['limitations'][0])

    def test_batch_cannot_guess_pagination_before_receiving_first_page(self):
        self.settings.data['runtime']['max_retries'] = 0
        batch = plan(stage='tools', tool='list_incident_lots', arguments={'offset': 0})
        batch['plan'] += plan(stage='tools', tool='list_incident_lots', arguments={'offset': 10})['plan']
        result, _ = self.run_script([self.lookup(), ('router', batch)])
        self.assertEqual(result['tool_calls'], 1)
        self.assertIn('BATCH_PAGINATION', result['limitations'][0])

    def test_batch_runtime_failure_keeps_evidence_and_stops_remaining_tools(self):
        self.settings.data['runtime']['max_retries'] = 0
        batch = plan(stage='tools', tool='list_incident_lots')
        batch['plan'] += plan(stage='tools', tool='get_engineering_snapshot')['plan']
        batch['plan'] += plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'SYN'})['plan']
        result, _ = self.run_script([self.lookup(), ('router', batch)],
                                   engineering_query=Mock(side_effect=ToolError('SNAPSHOT_DOWN')))
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['tool_calls'], 3)
        self.assertEqual([row['source'] for row in result['evidence']], ['find_incidents', 'list_incident_lots'])

    def test_requested_workflow_projects_router_only_and_finishes_without_ready_roundtrip(self):
        full = {'status': 'OK', 'sections': {'trend': {'raw_text': 'complete source text'}},
                'observations': {'value': 3.5}}
        result, client = self.run_script([
            self.lookup(), ('router', plan(stage='tools', tool='get_engineering_snapshot')),
            ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'SYN'})),
            ('judge', judge), ('answer', answer)], engineering_query=Mock(return_value=full),
            requested_tools=['find_incidents', 'get_engineering_snapshot', 'search_meeting_minutes'])
        self.assertEqual(result['status'], 'answered', result)
        self.assertTrue(client.calls[2][2]['evidence'][1]['routing_only'])
        self.assertNotIn('sections', client.calls[2][2]['evidence'][1]['result'])
        self.assertEqual(result['evidence'][1]['result'], full)
        self.assertNotIn('evidence_focus', client.calls[2][2])
        for role, _, payload in client.calls:
            if role in ('judge', 'answer'):
                self.assertEqual(payload['evidence_focus'][0]['observations'], {'value': 3.5})
                self.assertEqual(payload['evidence_focus'][0]['evidence_id'], 'e2')
        for _, _, payload in client.calls[-2:]:
            projected = payload['evidence'][1]['result']
            self.assertNotIn('observations', projected)
            self.assertEqual({**projected, 'observations': payload['evidence_focus'][0]['observations']}, full)
        self.assertEqual(result['evidence'][1]['result'], full)

    def test_inspection_plan_is_validated_and_returned_without_execution(self):
        def planned(payload):
            row = {'target': 'synthetic wafer', 'basis': 'synthetic observation',
                   'comparison': 'proposed comparison, not executed', 'evidence_ids': payload['evidence_ids']}
            return {**answer(payload), 'inspection_plan': {
                'historical_matches': [], 'checks': [row], 'eds_followup': row}}
        result, client = self.run_script([self.lookup(), *self.finish_steps()[:-1], ('answer', planned)],
                                         inspection_requested=True)
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(len(result['inspection_plan']), 2)
        self.assertEqual(result['tool_calls'], 1)
        self.assertTrue(client.calls[-1][2]['inspection_requested'])
        self.assertTrue(all('inspection_requested' not in payload for _, _, payload in client.calls[:-1]))

    def test_inspection_reference_ids_come_from_snapshot_evidence(self):
        def planned(payload):
            self.assertEqual(payload['historical_reference_evidence'], {'REF-1': ['e2']})
            self.assertEqual(payload['verified_historical_reference_ids'], ['REF-1'])
            row = {'target': 'synthetic wafer', 'basis': 'synthetic observation',
                   'comparison': 'proposed comparison', 'evidence_ids': ['e2']}
            return {**answer(payload), 'inspection_plan': {
                'historical_matches': [{**row, 'target': 'REF-1'}],
                'checks': [row], 'eds_followup': row}}
        result, _ = self.run_script([
            self.lookup(), ('router', plan(stage='tools', tool='get_engineering_snapshot')),
            ('judge', judge), ('answer', planned)], inspection_requested=True,
            engineering_query=Mock(return_value={'status': 'OK', 'sections': {'maps': {'records': [{'id': 'REF-1'}]}}}),
            requested_tools=['find_incidents', 'get_engineering_snapshot'])
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(result['inspection_plan'][0]['target'], 'REF-1')

    def test_inspection_contract_rejects_missing_empty_and_unknown_evidence(self):
        context = {'evidence_ids': ['e1'], 'judge_verdict': 'pass', 'inspection_requested': True}
        row = {'target': 'synthetic wafer', 'basis': 'observed change',
               'comparison': 'compare before/after', 'evidence_ids': ['e1']}
        valid = {**answer(context), 'inspection_plan': {
            'historical_matches': [], 'checks': [row], 'eds_followup': row}}
        self.assertTrue(validate_output('answer', valid, context))
        with self.assertRaisesRegex(ValueError, 'HISTORICAL_COMPARISON_REQUIRED'):
            validate_output('answer', valid, {**context, 'verified_historical_reference_ids': ['REF-1']})
        historical = {'target': 'REF-1', 'basis': 'same step, not proven cause',
                      'comparison': 'compare measurements', 'evidence_ids': ['e1']}
        with_historical = {**valid, 'inspection_plan': {
            **valid['inspection_plan'], 'historical_matches': [historical]}}
        with self.assertRaisesRegex(ValueError, 'UNKNOWN_HISTORICAL_REFERENCE'):
            validate_output('answer', with_historical, context)
        self.assertTrue(validate_output('answer', with_historical,
                                       {**context, 'historical_reference_evidence': {'REF-1': ['e1']}}))
        self.assertTrue(validate_output('answer', {**valid, 'status': 'partial', 'limitations': ['EDS unavailable']},
                                       {**context, 'judge_verdict': 'abstain'}))
        self.assertTrue(validate_output('answer', {**answer(context), 'inspection_plan': None},
                                        {**context, 'inspection_requested': False}))
        self.assertTrue(validate_output('answer', {**answer(context)},
                                        {**context, 'inspection_requested': False}))
        self.assertTrue(validate_output('answer', {**answer(context), 'status': 'unavailable',
                                                   'claims': [], 'limitations': ['No evidence']},
                                        context))
        cases = []
        missing = copy.deepcopy(valid)
        missing.pop('inspection_plan')
        cases.append((missing, 'INSPECTION_PLAN_REQUIRED'))
        missing_eds = copy.deepcopy(valid)
        missing_eds['inspection_plan'].pop('eds_followup')
        cases.append((missing_eds, 'REQUIRED'))
        blank = copy.deepcopy(valid)
        blank['inspection_plan']['checks'][0]['comparison'] = ' '
        cases.append((blank, 'EMPTY_INSPECTION_FIELD'))
        invented = copy.deepcopy(valid)
        invented['inspection_plan']['checks'][0]['evidence_ids'] = ['fabricated']
        cases.append((invented, 'UNKNOWN_EVIDENCE'))
        too_many_checks = copy.deepcopy(valid)
        too_many_checks['inspection_plan']['checks'] = [row] * 4
        cases.append((too_many_checks, 'INSPECTION_KIND_LIMIT'))
        too_many_historical = copy.deepcopy(with_historical)
        too_many_historical['inspection_plan']['historical_matches'] = [historical] * 3
        cases.append((too_many_historical, 'INSPECTION_KIND_LIMIT'))
        unavailable = {**valid, 'status': 'unavailable', 'claims': [], 'limitations': ['No evidence']}
        cases.append((unavailable, 'INSPECTION_PLAN_WITHOUT_REVIEWED_EVIDENCE'))
        for output, error in cases:
            with self.subTest(error=error), self.assertRaisesRegex(ValueError, error):
                validate_output('answer', output, context)

    def test_missing_requested_inspection_is_not_reported_as_answered(self):
        result, _ = self.run_script([self.lookup(), *self.finish_steps()], inspection_requested=True)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['limitations'], ['INSPECTION_PLAN_REQUIRED'])

    def test_execute_skill_preflight_keeps_tool_validation(self):
        lookup = self.lookup()[1]
        lookup['needs_skills'] = ['incident_search']
        result, _ = self.run_script([('router', lookup), *self.finish_steps()])
        self.assertEqual(result['status'], 'answered', result)
        self.assertTrue(any(event['event'] == 'skills_loaded' for event in result['events']))
        lookup['plan'][0]['arguments']['city'] = None
        self.settings.data['runtime']['max_retries'] = 0
        result, _ = self.run_script([('router', lookup)])
        self.assertEqual(result['tool_calls'], 0)
        self.assertIn('TYPE:', result['limitations'][0])

    def test_execute_skill_preflight_cannot_load_incident_topic_for_independent_request(self):
        output = plan(stage='independent', tool='search_meeting_minutes', arguments={'query': 'SYN'})
        output['needs_skills'] = ['lots']
        self.settings.data['runtime']['max_retries'] = 0
        result, _ = self.run_script([('router', output)], request_scope='independent')
        self.assertEqual(result['tool_calls'], 0)
        self.assertIn('INDEPENDENT_TOOL_TOPICS_NOT_SUPPORTED', result['limitations'])

    def test_engineering_snapshot_cannot_run_before_incident_or_without_provider(self):
        self.settings.data['runtime']['max_retries'] = 0
        query = Mock()
        result, _ = self.run_script([
            ('router', plan(stage='tools', tool='get_engineering_snapshot'))], engineering_query=query)
        self.assertEqual(result['status'], 'unavailable')
        query.assert_not_called()
        result, _ = self.run_script([
            self.lookup(), ('router', plan(stage='tools', tool='get_engineering_snapshot'))])
        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('TOOL_UNAVAILABLE', result['limitations'])

    def test_ui_context_stays_separate_from_requirements_and_evidence(self):
        context = {'previous_messages_unverified': [{'role': 'assistant', 'content': 'unverified'}],
                   'selected_incident': 'SYN-2026-01', 'unavailable_sources': ['sem']}
        result, client = self.run_script([self.lookup(), *self.finish_steps()], context_data=context)
        self.assertEqual(result['status'], 'answered', result)
        for _, _, payload in client.calls:
            self.assertEqual(payload['context_data_unverified'], context)
            self.assertEqual(payload['requirements'], ['synthetic contract question'])
        self.assertNotIn('unverified', json.dumps(result['evidence']))

    def test_missing_router_call_retries_without_discarding_checked_evidence(self):
        def malformed(_):
            raise agent.LLMError('ROUTER_FUNCTION_CALL_REQUIRED')
        result, client = self.run_script([self.lookup(), ('router', malformed), *self.finish_steps()])
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(result['tool_calls'], 1)
        self.assertEqual(result['llm_calls'], 5)
        self.assertEqual(client.calls[2][2]['last_error'], 'ROUTER_FUNCTION_CALL_REQUIRED')
        self.assertEqual(client.calls[2][2]['evidence_ids'], ['e1'])

    def test_duplicate_completed_incident_search_goes_to_judge_and_answer(self):
        result, client = self.run_script([self.lookup(), self.lookup(), ('judge', judge), ('answer', answer)])
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(result['tool_calls'], 1)
        self.assertEqual([role for role, _, _ in client.calls], ['router', 'router', 'judge', 'answer'])
        self.assertTrue(any(event['event'] == 'duplicate_tool_guard' for event in result['events']))
        self.assertTrue(client.calls[1][2]['incident_evidence_complete'])
        self.assertIn('find_incidents', client.calls[1][2]['available_tools'])

    def test_judge_can_request_a_different_incident_query_after_completed_search(self):
        first = self.lookup()
        second = self.lookup()
        second[1]['plan'][0]['arguments']['fields'] = ['confirmed_cause']
        steps = [first, ('router', plan('ready_for_judge', 'incident')),
                 ('judge', lambda payload: judge(payload, 'need_evidence')),
                 second, ('router', plan('ready_for_judge', 'incident')),
                 ('judge', judge), ('answer', answer)]
        result, client = self.run_script(steps)
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(result['tool_calls'], 2)
        self.assertEqual(client.calls[4][2]['evidence_ids'], ['e2'])

    def test_analysis_lookup_requests_recorded_cause_and_action_fields(self):
        lookup = plan(tool='find_incidents', arguments={'incident_number': 'SYN-2026-01'},
                      search_mode='sql_exact')
        lookup['intents'] = ['analysis', 'action']
        steps = [
            ('router', lookup),
            ('router', plan('ready_for_judge', 'incident')),
            ('judge', judge),
            ('answer', answer),
        ]
        result, _ = self.run_script(steps)
        self.assertEqual(result['status'], 'answered', result)
        row = result['evidence'][0]['result']['data'][0]
        self.assertIsNone(row['confirmed_cause'])
        self.assertEqual(row['corrective_action'], 'SYNTHETIC_ACTION_ONLY')
        self.assertIn('confirmed_cause', result['evidence'][0]['arguments']['fields'])
        self.assertIn('corrective_action', result['evidence'][0]['arguments']['fields'])

    def test_structured_plan_rejects_null_argument_then_recovers_without_tool_messages(self):
        invalid = ('router', plan(tool='find_incidents',
            arguments={'incident_number': 'SYN-2026-01', 'city': None}, search_mode='sql_exact'))

        class StructuredClient(ScriptedClient):
            def call(self, role, system_prompt, payload, history):
                output, _ = super().call(role, system_prompt, payload, history)
                if role == 'router':
                    history[-1] = {'role': 'assistant', 'content': json.dumps(output)}
                return output, None

        client = StructuredClient([invalid, self.lookup(), *self.finish_steps()])
        with patch.object(agent, 'RoleClient', return_value=client):
            result = agent.run(self.settings, 'synthetic contract question', 'tester', as_of='2026-03-31')
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(result['tool_calls'], 1)
        self.assertIn('$.plan[0].arguments.city; expected string; got null', client.calls[1][2]['last_error'])
        self.assertEqual(client.calls[2][2]['evidence_ids'], ['e1'])
        self.assertEqual([m['role'] for m in client.histories[1]], ['assistant', 'user'])
        self.assertTrue(all(m['role'] != 'tool' and 'tool_calls' not in m
                            for history in client.histories for m in history))

    def test_invalid_city_never_queries_database(self):
        invalid = ('router', plan(tool='find_incidents',
            arguments={'city': ['SYNTH-CITY']}, search_mode='sql_filter'))
        with patch.object(agent, 'open_incident_tools', side_effect=AssertionError('DB must not open')):
            result, _ = self.run_script([invalid] * 3)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['tool_calls'], 0)
        self.assertIn('expected string; got array', result['limitations'][0])

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
        self.assertEqual(router_after_judge['evidence'], client.calls[2][2]['evidence'])
        self.assertEqual([item['role'] for item in client.histories[3]], ['assistant', 'tool', 'assistant', 'tool'])

    def test_tool_history_contains_receipts_and_keeps_full_evidence_once(self):
        steps = [self.lookup(),
                 ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'SYN'})),
                 *self.finish_steps()]
        result, client = self.run_script(steps)
        self.assertEqual(result['status'], 'answered', result)
        receipts = [json.loads(item['content'])['observations'][0]
                    for item in client.histories[2] if item['role'] == 'tool']
        self.assertEqual(receipts, [
            {'tool': 'find_incidents', 'evidence_id': 'e1', 'status': 'OK'},
            {'tool': 'search_meeting_minutes', 'evidence_id': 'e2', 'status': 'OK'}])
        for index in (2, 3, 4):
            self.assertEqual(client.calls[index][2]['evidence'], result['evidence'])
        self.assertEqual(client.histories[3:], [[], []])
        history_text = json.dumps(client.histories[2], ensure_ascii=False)
        for item in result['evidence'][-1]['result']['items']:
            self.assertNotIn(item['text'], history_text)

    def test_payload_keeps_tool_availability_but_not_duplicate_schemas(self):
        self.settings.data['value_matching']['enabled'] = False
        self.settings.data['meetings']['enabled'] = False
        result, client = self.run_script([self.lookup(), *self.finish_steps()])
        self.assertEqual(result['status'], 'answered', result)
        catalog = agent.read_role_reference('router', 'tools.json',
            self.settings.data['paths']['skills_root'], self.settings.data['paths']['registry_file'])
        expected = {name: {key: value for key, value in spec.items() if key != 'parameters'}
                    for name, spec in catalog.items()}
        expected['match_incident_values']['enabled'] = False
        expected['search_meeting_minutes']['enabled'] = False
        expected['get_engineering_snapshot']['enabled'] = False
        expected['list_comparison_assets']['enabled'] = False
        expected['compare_sem_images']['enabled'] = False
        expected['compare_overlay_maps']['enabled'] = False
        expected['compare_sem_images']['asset_ids_by_item'] = {}
        expected['compare_overlay_maps']['asset_ids_by_item'] = {}
        for role, prompt, payload in client.calls:
            ready = copy.deepcopy(expected)
            if not payload['scope_valid']:
                for spec in ready.values():
                    if spec['stage'] == 'tools':
                        spec['enabled'] = False
            ready['list_incident_wafers']['enabled'] = False
            self.assertEqual(payload['available_tools'], ready)
            if role == 'router':
                self.assertIn(json.dumps(catalog, ensure_ascii=False, separators=(',', ':')), prompt)

    def test_requested_sources_are_collected_before_judge_without_repeating_completed_tools(self):
        steps = [self.lookup(), ('router', plan('ready_for_judge', 'tools')),
                 ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'SYN'})),
                 ('judge', judge), ('answer', answer)]
        result, client = self.run_script(steps, requested_tools=['find_incidents', 'search_meeting_minutes'])
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(client.calls[1][2]['pending_requested_tools'], ['search_meeting_minutes'])
        self.assertFalse(client.calls[1][2]['available_tools']['find_incidents']['enabled'])
        self.assertFalse(client.calls[1][2]['available_tools']['match_incident_values']['enabled'])
        self.assertEqual(client.calls[3][2]['pending_requested_tools'], [])
        self.assertFalse(client.calls[3][2]['available_tools']['search_meeting_minutes']['enabled'])
        self.assertTrue(any(event['event'] == 'requested_sources_pending' for event in result['events']))

    def test_exhausted_selection_goes_to_judge_without_an_impossible_router_plan(self):
        self.settings.data['meetings']['enabled'] = False
        names = ['find_incidents', 'list_incident_lots', 'list_incident_wafers']
        steps = [self.lookup(), ('router', plan(stage='tools', tool=names[1])),
                 ('router', plan(stage='tools', tool=names[2])), ('judge', judge), ('answer', answer)]
        result, client = self.run_script(steps, requested_tools=names)
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual([role for role, _, _ in client.calls], ['router', 'router', 'router', 'judge', 'answer'])

    def test_explicit_complete_lot_filter_finishes_wafer_lookup_not_impact_validation(self):
        for lots, complete in ((['SYN-LOT-01-01', 'SYN-LOT-01-02', 'SYN-LOT-01-03'], True),
                               (['SYN-LOT-01-01'], False)):
            with self.subTest(lots=lots):
                steps = [self.lookup(), ('router', plan(stage='tools', tool='list_incident_lots')),
                         ('router', plan(stage='tools', tool='list_incident_wafers',
                                         arguments={'lot_ids': lots, 'page_size': 100})),
                         *self.finish_steps()]
                result, client = self.run_script(steps)
                self.assertEqual(result['status'], 'answered')
                self.assertEqual(client.calls[3][2]['wafer_lookup_complete'], complete)
                self.assertEqual(client.calls[3][2]['available_tools']['list_incident_wafers']['enabled'],
                                 not complete)
                self.assertEqual(result['evidence'][-1]['result']['status'], 'PARTIAL')

    def test_independent_payload_preserves_runtime_stage(self):
        step = ('router', {**plan('blocked', 'independent'), 'limitations': ['not available']})
        self.settings.data['meetings']['enabled'] = False
        _, client = self.run_script([step], request_scope='independent')
        available = client.calls[0][2]['available_tools']
        self.assertEqual(set(available), {'search_meeting_minutes'})
        self.assertEqual(available['search_meeting_minutes']['stage'], 'independent')
        self.assertFalse(available['search_meeting_minutes']['enabled'])
        self.assertNotIn('parameters', available['search_meeting_minutes'])

    def test_new_lookup_drops_previous_scope_from_model_history(self):
        steps = [self.lookup(),
                 ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'SYN'})),
                 self.lookup('SYN-2026-06'), *self.finish_steps()]
        result, client = self.run_script(steps)
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual([item['role'] for item in client.histories[3]], ['assistant', 'tool'])
        self.assertNotIn('SYN-2026-01', json.dumps(client.histories[3]))
        self.assertEqual(client.calls[3][2]['evidence_ids'], ['e3'])
        self.assertIsNone(client.calls[3][2]['judge'])

    def test_judge_revise_clears_history_and_invalid_evidence_references(self):
        steps = [self.lookup(), ('router', plan('ready_for_judge', 'tools')),
                 ('judge', lambda payload: judge(payload, 'revise')),
                 self.lookup('SYN-2026-06'), *self.finish_steps()]
        result, client = self.run_script(steps)
        self.assertEqual(result['status'], 'answered', result)
        retry = client.calls[3][2]
        self.assertFalse(retry['scope_valid'])
        self.assertIsNone(retry['scope_id'])
        self.assertEqual(retry['evidence'], [])
        self.assertEqual(client.histories[3], [])
        self.assertEqual(retry['judge']['verdict'], 'revise')
        self.assertEqual(retry['judge']['coverage'], [])
        self.assertEqual(retry['judge']['issues'][0]['evidence_ids'], [])
        self.assertEqual(retry['judge']['issues'][0]['next_action'], 'retrieve another passage')
        self.assertIsNone(client.calls[4][2]['judge'])
        self.assertEqual(client.calls[4][2]['evidence_ids'], ['e2'])

    def test_expired_scope_keeps_only_pending_call_and_error_receipt(self):
        steps = [self.lookup(), ('router', plan(stage='tools', tool='list_incident_lots')),
                 self.lookup('SYN-2026-06'), *self.finish_steps()]
        with patch.object(agent.IncidentTools, 'list_incident_lots', side_effect=ToolError('SCOPE_EXPIRED')):
            result, client = self.run_script(steps)
        self.assertEqual(result['status'], 'answered', result)
        retry = client.calls[2][2]
        self.assertEqual(retry['evidence'], [])
        self.assertEqual(retry['last_error'], 'SCOPE_EXPIRED')
        self.assertEqual(retry['code_gate'], 'FAIL')
        history = client.histories[2]
        self.assertEqual([item['role'] for item in history], ['assistant', 'tool'])
        self.assertEqual(history[0]['tool_calls'][0]['id'], history[1]['tool_call_id'])
        self.assertEqual(json.loads(history[1]['content']), {'error': 'SCOPE_EXPIRED'})
        self.assertNotIn('SYN-2026-01', json.dumps(history))
        self.assertEqual(result['tool_calls'], 3)

    def test_failed_new_lookup_cannot_restore_old_evidence(self):
        original = agent.IncidentTools.find_incidents
        def find(db, actor, **arguments):
            if arguments.get('incident_number') == 'SYN-2026-06':
                raise ToolError('SYNTHETIC_QUERY_FAILURE')
            return original(db, actor, **arguments)
        steps = [self.lookup(), self.lookup('SYN-2026-06'),
                 ('router', {**plan('blocked'), 'limitations': ['query failed']})]
        with patch.object(agent.IncidentTools, 'find_incidents', find):
            result, client = self.run_script(steps)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['evidence'], [])
        self.assertEqual(client.calls[2][2]['code_gate'], 'FAIL')
        self.assertEqual(len(client.histories[2]), 2)
        self.assertNotIn('SYN-2026-01', json.dumps(client.histories[2]))

    def test_partial_query_match_reaches_judge_and_can_trigger_requery(self):
        for query, strategy in (('SYN absentword', 'scoped_any_terms'), ('SYN 히터', 'scoped_mixed_terms')):
            with self.subTest(strategy=strategy):
                steps = [self.lookup(),
                         ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': query})),
                         ('router', plan('ready_for_judge', 'tools')),
                         ('judge', lambda payload: judge(payload, 'need_evidence')),
                         ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': '히터'})),
                         *self.finish_steps()]
                result, client = self.run_script(steps)
                self.assertEqual(result['status'], 'answered', result)
                first_review = next(payload for role, _, payload in client.calls if role == 'judge')
                self.assertEqual(first_review['evidence'][-1]['result']['query_match']['strategy'], strategy)
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

    def test_hard_profile_is_explicit_and_only_used_for_generation(self):
        from run_agent import main
        output = io.StringIO()
        with patch.object(sys, 'argv', ['run_agent.py', '--demo', '--mode', 'prepare-demo', '--demo-profile', 'hard']), \
                patch('demo_data.generate', return_value={'synthetic': True}) as generate_mock, redirect_stdout(output):
            self.assertEqual(main(), 0)
        self.assertEqual(generate_mock.call_args.kwargs, {'profile': 'hard'})
        with patch.object(sys, 'argv', ['run_agent.py', '--demo', '--mode', 'check', '--demo-profile', 'hard']), \
                redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            main()
        self.assertEqual(error.exception.code, 2)

    def enable_image_tools(self, sem=True, overlay=True):
        for name, enabled in (('sem', sem), ('overlay', overlay)):
            config = self.settings.data['image_tools'][name]
            config.update(enabled=enabled, endpoint=f'http://127.0.0.1:9100/{name}',
                          served_model=f'test-{name}-model')

    def test_image_comparison_runs_after_incident_and_lot_for_both_modalities(self):
        for modality, compare_name in (('sem', 'compare_sem_images'),
                                       ('overlay', 'compare_overlay_maps')):
            with self.subTest(modality=modality):
                self.enable_image_tools()
                asset_ids = [f'{modality}-asset-1', f'{modality}-asset-2']
                asset_version = f'{modality}-assets-v1'
                compare_version = f'{modality}-compare-v1'

                def list_assets(*args, **kwargs):
                    return {
                        'status': 'OK',
                        'provenance': {'source': 'synthetic-image-adapter', 'version': asset_version},
                        'assets': [{'asset_id': asset_id, 'modality': modality} for asset_id in asset_ids],
                    }

                def compare(*args, **kwargs):
                    return {
                        'request_id': f'{modality}-request-1',
                        'model': f'test-{modality}-model',
                        'model_version': compare_version,
                        'item': 'SYNTH-ITEM',
                        'modality': modality,
                        'asset_ids': kwargs['asset_ids'],
                        'asset_revisions': ['r1', 'r2'],
                        'status': 'OK',
                        'alignment_verified': True,
                        'similarity': 0.98,
                        'findings': ['synthetic comparison'],
                        'limitations': [],
                        'artifact_ids': ['artifact-1'],
                        'provenance': {
                            'status': 'OK',
                            'score_type': 'model_similarity',
                            'model_score': 0.98,
                            'validated_asset_metadata': [],
                        },
                    }

                def review(payload):
                    comparison = payload['evidence'][-1]
                    self.assertEqual(comparison['source'], compare_name)
                    self.assertEqual(comparison['result']['model_version'], compare_version)
                    self.assertEqual(comparison['result']['provenance']['model_score'], 0.98)
                    return judge(payload)

                steps = [
                    self.lookup(),
                    ('router', plan(stage='tools', tool='list_incident_lots')),
                    ('router', plan(stage='tools', tool='list_comparison_assets',
                                    arguments={'item': 'SYNTH-ITEM', 'modality': modality})),
                    ('router', plan(stage='tools', tool=compare_name,
                                    arguments={'item': 'SYNTH-ITEM', 'asset_ids': asset_ids})),
                    ('router', plan('ready_for_judge', 'tools')),
                    ('judge', review),
                    ('answer', answer),
                ]
                with patch.object(agent.ImageTools, 'list_comparison_assets', autospec=True,
                                  side_effect=list_assets) as list_mock, \
                     patch.object(agent.ImageTools, compare_name, autospec=True,
                                  side_effect=compare) as compare_mock:
                    result, client = self.run_script(steps)

                self.assertEqual(result['status'], 'answered', result)
                self.assertEqual([role for role, _, _ in client.calls],
                                 ['router', 'router', 'router', 'router', 'router', 'judge', 'answer'])
                self.assertEqual([item['source'] for item in result['evidence']],
                                 ['find_incidents', 'list_incident_lots', 'list_comparison_assets', compare_name])
                for name in ('list_comparison_assets', 'compare_sem_images', 'compare_overlay_maps'):
                    self.assertFalse(client.calls[0][2]['available_tools'][name]['enabled'])
                    self.assertEqual(client.calls[2][2]['available_tools'][name]['enabled'],
                                     name == 'list_comparison_assets')
                    self.assertEqual(client.calls[3][2]['available_tools'][name]['enabled'],
                                     name in ('list_comparison_assets', compare_name))
                self.assertEqual(client.calls[3][2]['available_tools'][compare_name]['asset_ids_by_item'],
                                 {'SYNTH-ITEM': asset_ids})
                self.assertFalse(client.calls[2][2]['available_tools']['list_incident_lots']['enabled'])
                self.assertTrue(any('images' in payload['loaded_topics']
                                    for role, _, payload in client.calls if role == 'router'))
                list_mock.assert_called_once()
                compare_mock.assert_called_once()
                self.assertEqual(list_mock.call_args.kwargs['as_of'], '2026-03-31')
                self.assertEqual(compare_mock.call_args.kwargs['as_of'], '2026-03-31')
                self.assertIn('tester', compare_mock.call_args.args)
                self.assertIn(result['scope_id'], compare_mock.call_args.args)

    def test_incomparable_image_result_reaches_partial_answer_without_repeat(self):
        self.enable_image_tools()
        asset_ids = ['sem-asset-1', 'sem-asset-2']

        def list_assets(*args, **kwargs):
            return {'status': 'OK', 'provenance': {'version': 'sem-assets-v1'},
                    'assets': [{'asset_id': asset_id, 'modality': 'sem'} for asset_id in asset_ids]}

        def incomparable(*args, **kwargs):
            return {'request_id': 'sem-request-1', 'model': 'test-sem-model', 'model_version': 'sem-v1',
                    'item': 'SYNTH-ITEM', 'modality': 'sem', 'asset_ids': asset_ids,
                    'asset_revisions': ['r1', 'r2'], 'status': 'INCOMPARABLE',
                    'alignment_verified': False, 'similarity': None,
                    'findings': ['Synthetic class findings were produced.'],
                    'limitations': ['Physical alignment was not verified.'], 'artifact_ids': [],
                    'provenance': {'status': 'INCOMPARABLE', 'score_type': 'model_similarity',
                                   'model_score': None, 'validated_asset_metadata': []}}

        steps = [self.lookup(),
                 ('router', plan(stage='tools', tool='list_incident_lots')),
                 ('router', plan(stage='tools', tool='list_comparison_assets',
                                 arguments={'item': 'SYNTH-ITEM', 'modality': 'sem'})),
                 ('router', plan(stage='tools', tool='compare_sem_images',
                                 arguments={'item': 'SYNTH-ITEM', 'asset_ids': asset_ids})),
                 ('router', plan(stage='tools', tool='compare_sem_images',
                                 arguments={'item': 'SYNTH-ITEM', 'asset_ids': asset_ids})),
                 ('judge', abstain), ('answer', partial_answer)]
        with patch.object(agent.ImageTools, 'list_comparison_assets', autospec=True,
                          side_effect=list_assets) as list_mock, \
             patch.object(agent.ImageTools, 'compare_sem_images', autospec=True,
                          side_effect=incomparable) as compare_mock:
            result, client = self.run_script(steps)

        self.assertEqual(result['status'], 'partial', result)
        self.assertEqual(result['judge']['verdict'], 'abstain')
        self.assertEqual(compare_mock.call_count, 1)
        self.assertIn('compare_sem_images', client.calls[4][2]['available_tools'])
        self.assertTrue(any(event['event'] == 'duplicate_tool_guard' for event in result['events']))
        list_mock.assert_called_once()

    def test_judge_can_request_different_image_pair_after_completed_comparison(self):
        self.enable_image_tools()
        first_pair = ['sem-asset-1', 'sem-asset-2']
        second_pair = ['sem-asset-2', 'sem-asset-3']

        def list_assets(*args, **kwargs):
            return {'status': 'OK', 'provenance': {'version': 'sem-assets-v1'},
                    'assets': [{'asset_id': asset_id, 'modality': 'sem'}
                               for asset_id in ('sem-asset-1', 'sem-asset-2', 'sem-asset-3')]}

        def compare(*args, **kwargs):
            return {'request_id': 'sem-request', 'model': 'test-sem-model', 'model_version': 'sem-v1',
                    'item': 'SYNTH-ITEM', 'modality': 'sem', 'asset_ids': kwargs['asset_ids'],
                    'asset_revisions': ['r1', 'r2'], 'status': 'INCOMPARABLE',
                    'alignment_verified': False, 'similarity': None, 'findings': ['synthetic finding'],
                    'limitations': ['alignment unavailable'], 'artifact_ids': [],
                    'provenance': {'status': 'INCOMPARABLE', 'score_type': 'model_similarity',
                                   'model_score': None, 'validated_asset_metadata': []}}

        steps = [self.lookup(),
                 ('router', plan(stage='tools', tool='list_incident_lots')),
                 ('router', plan(stage='tools', tool='list_comparison_assets',
                                 arguments={'item': 'SYNTH-ITEM', 'modality': 'sem'})),
                 ('router', plan(stage='tools', tool='compare_sem_images',
                                 arguments={'item': 'SYNTH-ITEM', 'asset_ids': first_pair})),
                 ('router', plan('ready_for_judge', 'tools')),
                 ('judge', lambda payload: judge(payload, 'need_evidence')),
                 ('router', plan(stage='tools', tool='compare_sem_images',
                                 arguments={'item': 'SYNTH-ITEM', 'asset_ids': second_pair})),
                 ('router', plan('ready_for_judge', 'tools')), ('judge', judge), ('answer', answer)]
        with patch.object(agent.ImageTools, 'list_comparison_assets', autospec=True,
                          side_effect=list_assets), \
             patch.object(agent.ImageTools, 'compare_sem_images', autospec=True,
                          side_effect=compare) as compare_mock:
            result, _ = self.run_script(steps)

        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(compare_mock.call_count, 2)
        self.assertEqual([item['result']['asset_ids'] for item in result['evidence']
                          if item['source'] == 'compare_sem_images'], [first_pair, second_pair])

    def test_disabled_image_comparison_is_never_invoked(self):
        self.enable_image_tools(sem=False, overlay=True)
        asset_result = {'status': 'OK', 'provenance': {'version': 'overlay-assets-v1'}, 'assets': []}
        steps = [
            self.lookup(),
            ('router', plan(stage='tools', tool='list_incident_lots')),
            ('router', plan(stage='tools', tool='list_comparison_assets',
                            arguments={'item': 'SYNTH-ITEM', 'modality': 'sem'})),
            ('router', plan(stage='tools', tool='compare_sem_images',
                            arguments={'item': 'SYNTH-ITEM',
                                       'asset_ids': ['sem-asset-1', 'sem-asset-2']})),
            ('router', {**plan('blocked', 'tools'), 'limitations': ['disabled image tool']}),
        ]
        with patch.object(agent.ImageTools, 'list_comparison_assets', autospec=True,
                          return_value=asset_result) as list_mock, \
             patch.object(agent.ImageTools, 'compare_sem_images', autospec=True) as compare_mock:
            result, client = self.run_script(steps)

        self.assertEqual(result['status'], 'unavailable', result)
        self.assertFalse(client.calls[0][2]['available_tools']['compare_sem_images']['enabled'])
        list_mock.assert_called_once()
        compare_mock.assert_not_called()

    def test_image_tools_are_blocked_without_incident_or_lot_scope(self):
        self.enable_image_tools()
        image_step = ('router', plan(stage='tools', tool='list_comparison_assets',
                                     arguments={'item': 'SYNTH-ITEM', 'modality': 'sem'}))
        blocked = ('router', {**plan('blocked', 'tools'), 'limitations': ['prerequisite required']})
        for label, steps in (
                ('no incident', [self.lookup('SYN-2026-99'), image_step, blocked]),
                ('no lot', [self.lookup(), image_step, blocked])):
            with self.subTest(scope=label), \
                 patch.object(agent.ImageTools, 'list_comparison_assets', autospec=True) as list_mock:
                result, _ = self.run_script(steps)
            self.assertEqual(result['status'], 'unavailable', result)
            self.assertEqual(result['tool_calls'], 1)
            list_mock.assert_not_called()

    def test_image_tool_cannot_override_actor_scope_or_as_of(self):
        self.enable_image_tools()
        for key, value in (('actor', 'attacker'), ('scope_id', 'forged-scope'), ('as_of', '2099-01-01')):
            with self.subTest(argument=key), patch.object(agent.ImageTools, 'compare_sem_images', autospec=True) as compare_mock:
                bad_step = ('router', plan(stage='tools', tool='compare_sem_images', arguments={
                    'item': 'SYNTH-ITEM', 'asset_ids': ['sem-asset-1'], key: value}))
                steps = [self.lookup(),
                         ('router', plan(stage='tools', tool='list_incident_lots')),
                         bad_step, bad_step, bad_step,
                         ('router', {**plan('blocked', 'tools'), 'limitations': ['caller identity override']})]
                result, _ = self.run_script(steps)
            self.assertEqual(result['status'], 'unavailable', result)
            self.assertEqual(result['tool_calls'], 2)
            compare_mock.assert_not_called()


if __name__ == '__main__':
    unittest.main()
