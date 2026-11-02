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
from prompt_contracts import structure, validate_output
from skill_loader import compile_prompt
from conversation_memory import select_turns


class SchemaBoundsTests(unittest.TestCase):
    def test_mes_catalog_candidate_limitation_requires_a_cited_candidate_response(self):
        limitation = agent.MES_CATALOG_CANDIDATE_LIMITATION
        candidate = {'id': 'e-mes', 'source': 'search_mes_reference', 'result': {'items': [
            {'scope_relation': 'catalog_candidate'}]}}
        current = {'id': 'e-current', 'source': 'search_mes_reference', 'result': {'items': [
            {'scope_relation': 'current_scope'}]}}

        candidate_only = {'status': 'answered', 'claims': [{'evidence_ids': ['e-mes']}], 'limitations': []}
        system_limitations = agent.mes_catalog_candidate_system_limitations(candidate_only, [candidate])
        self.assertEqual(system_limitations, [limitation])
        self.assertEqual(candidate_only['limitations'], [])

        mixed_response = {'id': 'e-mixed', 'source': 'search_mes_reference', 'result': {'items': [
            {'scope_relation': 'current_scope'}, {'scope_relation': 'catalog_candidate'}]}}
        mixed = {'status': 'partial', 'claims': [{'evidence_ids': ['e-mixed']}], 'limitations': []}
        self.assertEqual(agent.mes_catalog_candidate_system_limitations(mixed, [mixed_response]), [limitation])

        uncited = {'status': 'answered', 'claims': [{'evidence_ids': ['e-other']}], 'limitations': []}
        self.assertEqual(agent.mes_catalog_candidate_system_limitations(uncited, [candidate]), [])
        current_only = {'status': 'answered', 'claims': [{'evidence_ids': ['e-current']}], 'limitations': []}
        self.assertEqual(agent.mes_catalog_candidate_system_limitations(current_only, [current]), [])

    def test_mes_catalog_candidate_limitation_preserves_and_deduplicates_without_mutation(self):
        limitation = agent.MES_CATALOG_CANDIDATE_LIMITATION
        answer = {'status': 'answered', 'claims': [{'evidence_ids': ['e-mes']}],
                  'limitations': ['existing limitation', limitation]}
        original = copy.deepcopy(answer)
        evidence = [{'id': 'e-mes', 'source': 'search_mes_reference', 'result': {'items': [
            {'scope_relation': 'catalog_candidate'}]}}]

        result = agent.mes_catalog_candidate_system_limitations(answer, evidence)

        self.assertEqual(result, [limitation])
        self.assertEqual(answer, original)
        self.assertEqual(evidence[0]['result']['items'], [{'scope_relation': 'catalog_candidate'}])

    def test_mes_catalog_candidate_limitation_preserves_six_llm_limitations(self):
        original_limitations = [f'synthetic limitation {index}' for index in range(6)]
        answer = {'status': 'answered', 'claims': [{'evidence_ids': ['e-mes']}],
                  'limitations': original_limitations.copy()}
        evidence = [{'id': 'e-mes', 'source': 'search_mes_reference', 'result': {'items': [
            {'scope_relation': 'catalog_candidate'}]}}]

        result = agent.mes_catalog_candidate_system_limitations(answer, evidence)

        self.assertEqual(answer['limitations'], original_limitations)
        self.assertEqual(len(answer['limitations']), 6)
        self.assertEqual(result, [agent.MES_CATALOG_CANDIDATE_LIMITATION])
        self.assertEqual(answer['limitations'], original_limitations)

    def test_document_retrieval_caveats_follow_cited_evidence_without_mutation(self):
        truncated = {'id': 'e-truncated', 'source': 'search_engineer_notes',
                     'result': {'source_reported_truncated': True}}
        unknown = {'id': 'e-unknown', 'source': 'search_internal_documents',
                   'result': {'source_reported_truncated': None}}
        not_truncated = {'id': 'e-complete', 'source': 'search_internal_documents',
                         'result': {'source_reported_truncated': False}}
        truncated_caveat = agent.DOCUMENT_RESULTS_SOURCE_REPORTED_TRUNCATED_LIMITATION
        unknown_caveat = agent.DOCUMENT_RETRIEVAL_COMPLETENESS_UNKNOWN_LIMITATION
        nontruncated_caveat = agent.DOCUMENT_SOURCE_NONTRUNCATION_LIMITATION
        acl_caveat = agent.DOCUMENT_ACCESS_CONTROL_UNVERIFIED_LIMITATION

        cited = {'status': 'answered', 'claims': [{'evidence_ids': ['e-truncated']}],
                 'limitations': ['existing limitation']}
        original = copy.deepcopy(cited)
        self.assertEqual(agent.document_retrieval_system_limitations(cited, [truncated]),
                         [truncated_caveat, acl_caveat])
        self.assertEqual(cited, original)
        self.assertEqual(agent.document_retrieval_system_limitations(
            {'claims': [{'evidence_ids': ['other']}]}, [truncated]), [])

        # A no-match result still receives the caveat when the Answer cites its evidence id.
        no_match = {'status': 'answered', 'claims': [{'evidence_ids': ['e-unknown']}]}
        self.assertEqual(agent.document_retrieval_system_limitations(no_match, [unknown]),
                         [unknown_caveat, acl_caveat])
        self.assertEqual(agent.document_retrieval_system_limitations(
            {'claims': [{'evidence_ids': ['e-complete']}]}, [not_truncated]),
            [nontruncated_caveat, acl_caveat])
        self.assertEqual(agent.document_retrieval_system_limitations(
            {'claims': [{'evidence_ids': ['e-truncated', 'e-unknown', 'e-complete']}]},
            [truncated, unknown, not_truncated]),
            [truncated_caveat, nontruncated_caveat, unknown_caveat, acl_caveat])

    def test_document_retrieval_caveat_defaults_missing_metadata_to_unknown(self):
        legacy = {'id': 'e-legacy', 'source': 'search_engineer_notes', 'result': {}}
        self.assertEqual(agent.document_retrieval_system_limitations(
            {'claims': [{'evidence_ids': ['e-legacy']}]}, [legacy]),
            [agent.DOCUMENT_RETRIEVAL_COMPLETENESS_UNKNOWN_LIMITATION,
             agent.DOCUMENT_ACCESS_CONTROL_UNVERIFIED_LIMITATION])

    def test_document_system_caveats_do_not_consume_six_llm_limitations(self):
        limitations = [f'synthetic limitation {index}' for index in range(6)]
        answer_value = {'status': 'answered', 'claims': [{'evidence_ids': ['e-doc']}],
                        'limitations': limitations.copy()}
        evidence = [{'id': 'e-doc', 'source': 'search_engineer_notes',
                     'result': {'source_reported_truncated': True}}]
        system_limitations = list(dict.fromkeys(
            agent.mes_catalog_candidate_system_limitations(answer_value, evidence)
            + agent.document_retrieval_system_limitations(answer_value, evidence)))
        self.assertEqual(answer_value['limitations'], limitations)
        self.assertEqual(system_limitations, [agent.DOCUMENT_RESULTS_SOURCE_REPORTED_TRUNCATED_LIMITATION,
                                             agent.DOCUMENT_ACCESS_CONTROL_UNVERIFIED_LIMITATION])

    def test_lookup_chain_requires_contiguous_unique_scope_consistent_pages(self):
        def page(offset, lot_id, next_offset, total=2, scope_id='scope-1', status='PARTIAL'):
            return ({'offset': offset}, {
                'status': status, 'scope_id': scope_id, 'offset': offset,
                'total_memberships': total, 'next_offset': next_offset,
                'items': [{'incident_id': 'incident-1', 'lot_id': lot_id}],
            })

        complete = [page(0, 'lot-1', 1), page(1, 'lot-2', None)]
        self.assertTrue(agent.lookup_chain_finished('list_incident_lots', complete, 'scope-1'))
        self.assertFalse(agent.lookup_chain_finished('list_incident_lots', [complete[0], page(2, 'lot-2', None)],
                                                      'scope-1'))
        self.assertFalse(agent.lookup_chain_finished('list_incident_lots', [complete[0], page(1, 'lot-1', None)],
                                                      'scope-1'))
        self.assertFalse(agent.lookup_chain_finished('list_incident_lots', [complete[0], page(1, 'lot-2', None, 3)],
                                                      'scope-1'))
        self.assertFalse(agent.lookup_chain_finished('list_incident_lots', [complete[0], page(1, 'lot-2', None,
                                                                                           scope_id='scope-2')],
                                                      'scope-1'))
        missing_offset = page(1, 'lot-2', None)[1]
        del missing_offset['offset']
        self.assertFalse(agent.lookup_chain_finished('list_incident_lots', [complete[0],
            ({'offset': 1}, missing_offset)], 'scope-1'))
        no_match = ({'offset': 0}, {'status': 'NO_MATCH', 'items': [], 'total_memberships': 0,
                                   'next_offset': None})
        partial_empty = ({'offset': 0}, {'status': 'PARTIAL', 'items': [], 'total_memberships': 0,
                                         'next_offset': None})
        empty_ok = ({'offset': 0}, {'status': 'OK', 'items': [], 'total_memberships': 0,
                                    'next_offset': None})
        self.assertTrue(agent.lookup_chain_finished('list_incident_lots', [no_match], 'scope-1'))
        self.assertTrue(agent.lookup_chain_finished('list_incident_lots', [partial_empty], 'scope-1'))
        self.assertFalse(agent.lookup_chain_finished('list_incident_lots', [empty_ok], 'scope-1'))
        no_match_pages = [page(0, 'lot-1', 1, status='NO_MATCH'),
                          page(1, 'lot-2', None, status='NO_MATCH')]
        self.assertFalse(agent.lookup_chain_finished('list_incident_lots', no_match_pages, 'scope-1'))

    def test_map_prompt_compaction_preserves_identity_and_summary_not_coordinates(self):
        original = {'source': 'get_engineering_snapshot', 'result': {'sections': {'maps': {'assets': [{
            'id': 'map-1', 'sha256': 'digest', 'summary': {'cd': {'mean': 42}},
            'cd': [{'x': 1, 'y': 2, 'value': 42}], 'overlay': [], 'thk': [], 'eds_bin': [],
        }]}}}}
        compact = agent.map_prompt_evidence(original)
        asset = compact['result']['sections']['maps']['assets'][0]
        self.assertEqual(asset, {'id': 'map-1', 'sha256': 'digest', 'summary': {'cd': {'mean': 42}}})
        self.assertEqual(len(original['result']['sections']['maps']['assets'][0]['cd']), 1)

    def test_array_and_string_bounds_preserve_type_validation(self):
        schema = {'type': 'array', 'minItems': 1, 'maxItems': 2,
                  'items': {'type': 'string', 'minLength': 2, 'maxLength': 4}}
        structure(['CD', 'SEM'], schema)
        structure(['가나다라'], schema)
        for value, error in (([], 'MINITEMS'), (['CD'] * 3, 'MAXITEMS'),
                             (['x'], 'MINLENGTH'), (['abcde'], 'MAXLENGTH'), ([4], 'TYPE')):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, error):
                structure(value, schema)
        with self.assertRaisesRegex(ValueError, 'UNSUPPORTED_SCHEMA_KEYWORD'):
            structure('x', {'type': 'string', 'unknownKeyword': True})


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
        data['mes_reference']['synthetic_sqlite']['filter_columns'] = {'__test_disabled': '__test_disabled'}
        data['mes_reference']['synthetic_sqlite']['filter_columns'] = {'__test_disabled': '__test_disabled'}
        self.settings = Settings(data, ())
        generate(self.settings)
        self.use_temporary_skill_lock()

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

    def test_statistics_runs_before_judge_without_candidate_selection(self):
        aggregate = plan(tool='summarize_incidents', arguments={
            'filters': {'department': 'SYNTH-QA'}, 'group_by': ['product_generations'], 'top_k': 1},
            search_mode='sql_aggregate')
        aggregate['intents'] = ['statistics']
        aggregate['filters'] = aggregate['plan'][0]['arguments']['filters']
        result, client = self.run_script([('router', aggregate), *self.finish_steps()])
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual([row['source'] for row in result['evidence']], ['summarize_incidents'])
        self.assertEqual(result['evidence'][0]['result']['total_incidents'], 9)
        self.assertEqual([row[0] for row in client.calls], ['router', 'router', 'judge', 'answer'])

    def test_mes_reference_filters_reach_scoped_callback(self):
        self.settings.data['mes_reference'].update(enabled=True, allowed_kinds=['product'], top_k=3)
        self.settings.data['mes_reference']['synthetic_sqlite']['filter_columns'] = {'department': 'department'}
        captured = {}

        def callback(**kwargs):
            captured.update(kwargs)
            return {'status': 'NO_MATCH', 'items': [], 'truncated': False, 'candidate_count': 0,
                    'incident_ids': kwargs['incident_ids'], 'as_of': kwargs['as_of'],
                    'limitations': []}

        args = {'kind': 'product', 'query': 'widget', 'filters': {'department': 'SYNTH-QA'}}
        steps = [self.lookup(), ('router', plan(stage='tools', tool='list_incident_lots')),
                 ('router', plan(stage='tools', tool='search_mes_reference', arguments=args)), *self.finish_steps()]
        result, _ = self.run_script(steps, mes_reference_query=callback)
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(captured['filters'], {'department': 'SYNTH-QA'})
        self.assertEqual(captured['actor'], 'tester')
        self.assertEqual(captured['incident_ids'], [result['evidence'][0]['result']['data'][0]['incident_id']])
        self.assertEqual(captured['as_of'], '2026-03-31')

    def test_cited_mes_catalog_candidate_adds_answer_limitation(self):
        self.settings.data['mes_reference'].update(enabled=True, allowed_kinds=['product'], top_k=3)
        self.settings.data['mes_reference']['synthetic_sqlite']['filter_columns'] = {'department': 'department'}

        def callback(**kwargs):
            return {'status': 'OK', 'items': [{
                'kind': 'product', 'record_id': 'SYN-REF-1', 'version': 'v1',
                'name': 'Synthetic reference', 'source_ref': 'synthetic://SYN-REF-1',
                'applicability': 'candidate', 'scope_relation': 'catalog_candidate',
                'incident_ids': [], 'available_at': '2026-03-30',
                'effective_from': None, 'effective_to': None,
            }], 'truncated': False, 'candidate_count': 1,
                'incident_ids': kwargs['incident_ids'], 'as_of': kwargs['as_of'], 'limitations': []}

        answer_with_six_limitations = lambda payload: {
            **answer(payload), 'limitations': [f'synthetic limitation {index}' for index in range(6)]}
        steps = [self.lookup(), ('router', plan(stage='tools', tool='list_incident_lots')),
                 ('router', plan(stage='tools', tool='search_mes_reference',
                                 arguments={'kind': 'product', 'query': 'synthetic reference'})),
                 ('router', plan('ready_for_judge', 'tools')), ('judge', judge),
                 ('answer', answer_with_six_limitations)]
        result, _ = self.run_script(steps, mes_reference_query=callback)

        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(result['limitations'], [f'synthetic limitation {index}' for index in range(6)])
        self.assertEqual(result['system_limitations'], [agent.MES_CATALOG_CANDIDATE_LIMITATION])
        self.assertEqual(result['claims'][0]['evidence_ids'], ['e1', 'e2', 'e3'])

    def test_mes_reference_router_catalog_is_trusted_and_only_advertised_when_enabled(self):
        self.use_temporary_skill_lock()
        self.settings.data['mes_reference'].update(enabled=True, allowed_kinds=['product', 'equipment'], top_k=3)
        self.settings.data['mes_reference']['synthetic_sqlite']['filter_columns'] = {
            'department': 'PHYSICAL_SENTINEL_COLUMN', 'line': 'ANOTHER_PHYSICAL_SENTINEL'}
        callback = Mock(return_value={'status': 'NO_MATCH', 'items': [], 'truncated': False,
                                      'candidate_count': 0, 'incident_ids': [],
                                      'as_of': '2026-03-31', 'limitations': []})
        # Repeat routing carries untrusted context, which cannot alter configured metadata.
        steps = [('router', plan('execute', 'incident', tool='find_incidents',
                                 arguments={'incident_number': 'SYN-2026-01'}, search_mode='sql_exact')),
                 ('router', plan('ready_for_judge', 'incident')),
                 ('judge', judge), ('answer', answer)]
        result, client = self.run_script(steps, mes_reference_query=callback,
                                         context_data={'allowed_kinds': ['attacker'],
                                                       'allowed_filter_keys': ['forged']})
        self.assertIn(result['status'], ('answered', 'partial'))
        router_payloads = [payload for role, _, payload in client.calls if role == 'router']
        payload = router_payloads[1]
        self.assertEqual(payload['mes_reference_catalog'], {
            'allowed_kinds': ['product', 'equipment'], 'allowed_filter_keys': ['department', 'line']})
        serialized = json.dumps(payload)
        self.assertNotIn('PHYSICAL_SENTINEL', serialized)
        self.assertNotIn('ANOTHER_PHYSICAL_SENTINEL', serialized)
        self.assertEqual(payload['mes_reference_catalog']['allowed_kinds'], ['product', 'equipment'])
        self.assertEqual(payload['mes_reference_catalog']['allowed_filter_keys'], ['department', 'line'])

        self.settings.data['mes_reference']['enabled'] = False
        result, client = self.run_script([('router', plan('execute', 'incident', tool='find_incidents',
                                                          arguments={'incident_number': 'SYN-2026-01'},
                                                          search_mode='sql_exact')),
                                          ('router', plan('ready_for_judge', 'incident')),
                                          ('judge', judge), ('answer', answer)],
                                         mes_reference_query=callback)
        self.assertNotIn('mes_reference_catalog', client.calls[1][2])
        self.assertFalse(client.calls[1][2]['available_tools']['search_mes_reference']['enabled'])

    def test_mes_reference_router_catalog_missing_callback_and_malformed_filter_config(self):
        self.use_temporary_skill_lock()
        self.settings.data['mes_reference'].update(enabled=True, allowed_kinds=['product'], top_k=3)
        self.settings.data['mes_reference']['synthetic_sqlite']['filter_columns'] = {'valid': 'PHYSICAL_SENTINEL'}
        _, client = self.run_script([('router', plan('execute', 'incident', tool='find_incidents',
                                                     arguments={'incident_number': 'SYN-2026-01'},
                                                     search_mode='sql_exact')),
                                     ('router', plan('ready_for_judge', 'incident')),
                                     ('judge', judge), ('answer', answer)])
        self.assertNotIn('mes_reference_catalog', client.calls[1][2])

    def test_mes_reference_router_catalog_omitted_for_non_mapping_synthetic_config(self):
        self.use_temporary_skill_lock()
        self.settings.data['mes_reference'].update(enabled=True, allowed_kinds=['product'], top_k=3)
        callback = Mock(return_value={})
        for malformed in (None, ['filter_columns']):
            with self.subTest(synthetic_sqlite=malformed):
                self.settings.data['mes_reference']['synthetic_sqlite'] = malformed
                _, client = self.run_script([('router', plan('execute', 'incident', tool='find_incidents',
                                                             arguments={'incident_number': 'SYN-2026-01'},
                                                             search_mode='sql_exact')),
                                             ('router', plan('ready_for_judge', 'incident')),
                                             ('judge', judge), ('answer', answer)],
                                            mes_reference_query=callback)
                self.assertNotIn('mes_reference_catalog', client.calls[1][2])

    def test_mes_reference_filters_reject_invalid_and_unmapped_keys(self):
        self.settings.data['mes_reference'].update(enabled=True, allowed_kinds=['product'], top_k=3)
        self.settings.data['mes_reference']['synthetic_sqlite']['filter_columns'] = {'department': 'department'}
        callback = Mock(return_value={})
        invalid_filters = [
            {}, {'bad-key': 'x'}, {'department': ' padded '}, {'department': ''},
            {'department': 'x' * 129}, {f'k{i}': 'x' for i in range(6)},
        ]
        for filters, expected_error in [(value, 'INVALID_MES_REFERENCE_FILTERS') for value in invalid_filters] + [
                ({'unknown': 'x'}, 'MES_REFERENCE_FILTER_UNAVAILABLE')]:
            with self.subTest(filters=filters):
                args = {'kind': 'product', 'query': 'widget', 'filters': filters}
                bad_request = ('router', plan(stage='tools', tool='search_mes_reference', arguments=args))
                steps = [self.lookup(), ('router', plan(stage='tools', tool='list_incident_lots')),
                         bad_request, bad_request, bad_request,
                         ('router', {**plan('blocked', 'tools'), 'limitations': ['invalid filter']})]
                result, _ = self.run_script(steps, mes_reference_query=callback)
                errors = [event.get('error') for event in result['events']
                          if event['event'] == 'validation_or_tool_error']
                self.assertTrue(errors)
                callback.assert_not_called()

        self.settings.data['mes_reference']['synthetic_sqlite']['filter_columns'] = None
        args = {'kind': 'product', 'query': 'widget', 'filters': {'department': 'SYNTH-QA'}}
        bad_request = ('router', plan(stage='tools', tool='search_mes_reference', arguments=args))
        result, _ = self.run_script([self.lookup(), ('router', plan(stage='tools', tool='list_incident_lots')),
                                     bad_request, bad_request, bad_request,
                                     ('router', {**plan('blocked', 'tools'), 'limitations': ['unmapped filters']})],
                                    mes_reference_query=callback)
        errors = [event.get('error') for event in result['events']
                  if event['event'] == 'validation_or_tool_error']
        self.assertIn('MES_REFERENCE_FILTER_UNAVAILABLE', errors)
        callback.assert_not_called()

    def test_mes_reference_legacy_callback_without_filters_and_fail_closed_with_filters(self):
        self.settings.data['mes_reference'].update(enabled=True, allowed_kinds=['product'], top_k=3)
        self.settings.data['mes_reference']['synthetic_sqlite']['filter_columns'] = {'department': 'department'}
        calls = []

        def legacy(*, kind, actor, incident_ids, as_of, query, top_k):
            calls.append((kind, actor, incident_ids, as_of, query, top_k))
            return {'status': 'NO_MATCH', 'items': [], 'truncated': False, 'candidate_count': 0,
                    'incident_ids': incident_ids, 'as_of': as_of, 'limitations': []}

        no_filters = [self.lookup(), ('router', plan(stage='tools', tool='list_incident_lots')),
                      ('router', plan(stage='tools', tool='search_mes_reference', arguments={'kind': 'product', 'query': 'widget'})),
                      *self.finish_steps()]
        result, _ = self.run_script(no_filters, mes_reference_query=legacy)
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(len(calls), 1)

        calls.clear()
        bad_request = ('router', plan(stage='tools', tool='search_mes_reference', arguments={
            'kind': 'product', 'query': 'widget', 'filters': {'department': 'SYNTH-QA'}}))
        with_filters = [self.lookup(), ('router', plan(stage='tools', tool='list_incident_lots')),
                        bad_request, bad_request, bad_request,
                        ('router', {**plan('blocked', 'tools'), 'limitations': ['legacy callback cannot filter']})]
        result, _ = self.run_script(with_filters, mes_reference_query=legacy)
        self.assertEqual(result['status'], 'unavailable', result)
        self.assertEqual(calls, [])

    def test_mes_reference_request_cannot_override_code_bound_scope(self):
        self.settings.data['mes_reference'].update(enabled=True, allowed_kinds=['product'], top_k=3)
        self.settings.data['mes_reference']['synthetic_sqlite']['filter_columns'] = {'department': 'department'}
        callback = Mock()
        for key, value in (('actor', 'attacker'), ('scope_id', 'forged'),
                           ('incident_ids', ['forged']), ('as_of', '2099-01-01')):
            with self.subTest(argument=key):
                args = {'kind': 'product', 'query': 'widget', key: value}
                bad_request = ('router', plan(stage='tools', tool='search_mes_reference', arguments=args))
                steps = [self.lookup(), ('router', plan(stage='tools', tool='list_incident_lots')),
                         bad_request, bad_request, bad_request,
                         ('router', {**plan('blocked', 'tools'), 'limitations': ['caller identity override']})]
                result, _ = self.run_script(steps, mes_reference_query=callback)
                self.assertEqual(result['status'], 'unavailable', result)
                callback.assert_not_called()

    def test_final_scope_reports_only_current_find_evidence(self):
        self.use_temporary_skill_lock()
        matched, _ = self.run_script([self.lookup(), *self.finish_steps()], incident_number='SYN-2026-01')
        self.assertEqual(matched['final_scope']['incident_lookup_status'], 'OK')
        self.assertEqual(len(matched['final_scope']['confirmed']['incident_ids']), 1)
        self.assertEqual(matched['final_scope']['request']['incident_number'], 'SYN-2026-01')

        missing = plan(tool='find_incidents', arguments={'incident_number': 'SYN-DOES-NOT-EXIST'},
                       search_mode='sql_exact')
        no_match, _ = self.run_script([('router', missing), *self.finish_steps()],
                                      incident_number='SYN-DOES-NOT-EXIST')
        self.assertEqual(no_match['final_scope']['incident_lookup_status'], 'NO_MATCH')
        self.assertEqual(no_match['final_scope']['confirmed']['incident_ids'], [])

    def test_final_scope_ambiguity_failure_and_independent_are_unconfirmed(self):
        self.use_temporary_skill_lock()
        ambiguous = plan(tool='find_incidents', arguments={'city': 'SYNTH-CITY'}, search_mode='sql_filter')
        result, _ = self.run_script([('router', ambiguous)], request_scope='incident')
        self.assertEqual(result['final_scope']['incident_lookup_status'], 'NEEDS_SELECTION')
        self.assertEqual(result['final_scope']['confirmed']['incident_ids'], [])
        self.assertIsNone(result['final_scope']['request']['incident_number'])
        self.assertEqual(result['final_scope']['wafer_page_collection']['status'], 'NOT_QUERIED')

        independent = [('router', plan('route', 'independent')),
                       ('router', plan(stage='independent', tool='search_meeting_minutes',
                                       arguments={'query': '교정'})),
                       *self.finish_steps('independent')]
        result, _ = self.run_script(independent, request_scope='auto')
        self.assertEqual(result['final_scope']['incident_lookup_status'], 'NOT_QUERIED')
        self.assertEqual(result['final_scope']['confirmed']['incident_ids'], [])

    def test_final_scope_keeps_partial_wafer_pages_and_source_metadata_separate(self):
        self.use_temporary_skill_lock()
        steps = [self.lookup(),
                 ('router', plan(stage='tools', tool='list_incident_lots')),
                 ('router', plan(stage='tools', tool='list_incident_wafers',
                                 arguments={'page_size': 1, 'offset': 0})),
                 *self.finish_steps()]
        result, _ = self.run_script(steps)
        self.assertEqual(result['status'], 'answered', result)
        wafer_scope = result['final_scope']['wafer_page_collection']
        self.assertEqual(wafer_scope['status'], 'QUERIED')
        self.assertEqual(wafer_scope['result_status'], 'PARTIAL')
        self.assertEqual(wafer_scope['source_completeness'], 'unknown')
        self.assertTrue(wafer_scope['wafer_scope'])

    def test_final_scope_marks_failed_incident_lookup_without_confirmation(self):
        self.use_temporary_skill_lock()
        with patch.object(agent.IncidentTools, 'find_incidents', side_effect=ToolError('SYNTHETIC_LOOKUP_FAILURE')):
            result, _ = self.run_script([self.lookup()] * 3, request_scope='incident')
        self.assertEqual(result['final_scope']['incident_lookup_status'], 'FAILED')
        self.assertEqual(result['final_scope']['confirmed']['incidents'], [])

    def test_final_scope_expired_during_finish_fails_closed(self):
        original_scope = agent.IncidentTools._scope
        calls = {'count': 0}

        def expire_on_final_check(tool, actor, scope_id):
            calls['count'] += 1
            if calls['count'] > 1:
                raise ToolError('SCOPE_EXPIRED')
            return original_scope(tool, actor, scope_id)

        with patch.object(agent.IncidentTools, '_scope', expire_on_final_check):
            result, _ = self.run_script([self.lookup(), *self.finish_steps()])
        scope = result['final_scope']
        self.assertEqual(scope['scope_status'], 'EXPIRED')
        self.assertFalse(scope['scope_valid'])
        self.assertEqual(scope['confirmed']['incidents'], [])
        self.assertIn('SCOPE_EXPIRED', result['limitations'])

    def test_final_scope_mismatched_membership_fails_closed(self):
        original_find = agent.IncidentTools.find_incidents

        def omit_evidence_row(tool, actor, **arguments):
            result = original_find(tool, actor, **arguments)
            result['data'] = []
            return result

        with patch.object(agent.IncidentTools, 'find_incidents', omit_evidence_row):
            result, _ = self.run_script([self.lookup(), *self.finish_steps()])
        scope = result['final_scope']
        self.assertEqual(scope['scope_status'], 'UNAVAILABLE')
        self.assertFalse(scope['scope_valid'])
        self.assertEqual(scope['confirmed']['incidents'], [])
        self.assertIn('SCOPE_EVIDENCE_MISMATCH', result['limitations'])

    def test_final_scope_missing_evidence_after_cutoff_fails_closed(self):
        self.use_temporary_skill_lock()
        original_review = agent.review_evidence

        def reject_find_evidence(evidence, as_of, timezone):
            if evidence and evidence[0].get('source') == 'find_incidents':
                return {'issues': [{'type': 'after_cutoff'}]}
            return original_review(evidence, as_of, timezone)

        with patch.object(agent, 'review_evidence', side_effect=reject_find_evidence):
            result, _ = self.run_script([self.lookup()] * 3, request_scope='incident')

        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['final_scope']['incident_lookup_status'], 'OK')
        self.assertEqual(result['final_scope']['scope_status'], 'UNAVAILABLE')
        self.assertFalse(result['final_scope']['scope_valid'])
        self.assertEqual(result['final_scope']['confirmed']['incidents'], [])
        self.assertEqual(result['evidence'], [])
        self.assertIn('SCOPE_EVIDENCE_MISSING', result['limitations'])

    def test_explicit_analysis_cohort_allows_followup_tools(self):
        lookup = plan(tool='find_incidents', arguments={
            'filters': {'department': 'SYNTH-QA'}, 'scope_mode': 'cohort'}, search_mode='sql_filter')
        lookup['intents'] = ['analysis']
        lookup['filters'] = lookup['plan'][0]['arguments']['filters']
        result, _ = self.run_script([('router', lookup),
            ('router', plan(stage='tools', tool='list_incident_lots')), *self.finish_steps()])
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(len(result['evidence'][0]['result']['data']), 9)
        self.assertEqual(result['evidence'][1]['source'], 'list_incident_lots')

    def test_statistics_large_population_disables_detail_tools(self):
        self.settings.data['runtime']['max_scope_incidents'] = 2
        aggregate = plan(tool='summarize_incidents', arguments={'filters': {'department': 'SYNTH-QA'}},
                         search_mode='sql_aggregate')
        aggregate['intents'] = ['statistics']
        aggregate['filters'] = aggregate['plan'][0]['arguments']['filters']
        result, client = self.run_script([('router', aggregate), *self.finish_steps()])
        self.assertEqual(result['status'], 'answered', result)
        self.assertFalse(client.calls[1][2]['available_tools']['list_incident_lots']['enabled'])
        self.assertEqual(result['evidence'][0]['result']['total_incidents'], 9)

    def test_statistics_answer_cannot_repeat_invented_model_numbers(self):
        aggregate = plan(tool='summarize_incidents', arguments={'filters': {'department': 'SYNTH-QA'}},
                         search_mode='sql_aggregate')
        aggregate['intents'] = ['statistics']
        aggregate['filters'] = aggregate['plan'][0]['arguments']['filters']
        def wrong_answer(payload):
            response = answer(payload)
            response.update(answer='사고가 999건이다.')
            response['claims'][0]['text'] = '사고가 999건이다.'
            return response
        result, _ = self.run_script([('router', aggregate), ('router', plan('ready_for_judge', 'tools')),
                                    ('judge', judge), ('answer', wrong_answer)])
        self.assertEqual(result['status'], 'answered', result)
        self.assertIn('9건', result['answer'])
        self.assertNotIn('999', result['answer'])
        self.assertNotIn('999', result['claims'][0]['text'])
        self.assertTrue(any(row['event'] == 'statistics_answer_rendered' for row in result['events']))

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

    def test_requested_tool_workflow_advertises_only_retrievable_schema_topics(self):
        query = Mock(return_value={'status': 'OK', 'sections': {}})
        result, client = self.run_script([
            self.lookup(), ('router', plan(stage='tools', tool='get_engineering_snapshot')),
            ('judge', judge), ('answer', answer)],
            engineering_query=query, requested_tools=['find_incidents', 'get_engineering_snapshot'])
        self.assertEqual(result['status'], 'answered', result)
        for _, _, payload in client.calls:
            self.assertIn('incident_search', payload['available_topics'])
            self.assertIn('lots', payload['available_topics'])
            self.assertNotIn('documents', payload['available_topics'])
            self.assertNotIn('trends', payload['available_topics'])

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

    def test_lot_lookup_finishes_after_contiguous_pages(self):
        self.use_temporary_skill_lock()
        steps = [self.lookup()]
        steps.extend(('router', plan(stage='tools', tool='list_incident_lots',
                                     arguments={'page_size': 1, 'offset': offset}))
                     for offset in range(3))
        steps.extend(self.finish_steps())
        result, client = self.run_script(steps)
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual([entry['result']['offset'] for entry in result['evidence'][1:]], [0, 1, 2])
        self.assertTrue(client.calls[4][2]['lot_lookup_complete'])
        self.assertFalse(client.calls[4][2]['available_tools']['list_incident_lots']['enabled'])

    def test_single_page_lookup_retains_completion_and_strict_planner_gate(self):
        self.use_temporary_skill_lock()
        result, client = self.run_script([self.lookup(),
            ('router', plan(stage='tools', tool='list_incident_lots')),
            *self.finish_steps()])
        self.assertEqual(result['status'], 'answered', result)
        self.assertTrue(client.calls[2][2]['lot_lookup_complete'])
        self.assertFalse(client.calls[2][2]['planner_lot_pages_complete'])

    def test_wafer_lookup_finishes_pagination_while_preserving_partial_source_status(self):
        self.use_temporary_skill_lock()
        steps = [self.lookup()]
        steps.extend(('router', plan(stage='tools', tool='list_incident_lots',
                                     arguments={'page_size': 1, 'offset': offset}))
                     for offset in range(3))
        steps.extend(('router', plan(stage='tools', tool='list_incident_wafers',
                                     arguments={'page_size': 1, 'offset': offset}))
                     for offset in range(8))
        steps.extend(self.finish_steps())
        result, client = self.run_script(steps)
        self.assertEqual(result['status'], 'answered', result)
        self.assertTrue(client.calls[12][2]['wafer_lookup_complete'])
        self.assertFalse(client.calls[12][2]['available_tools']['list_incident_wafers']['enabled'])
        self.assertFalse(client.calls[12][2]['planner_lot_pages_complete'])
        self.assertFalse(client.calls[12][2]['planner_wafer_pages_complete'])
        wafer_results = [entry['result'] for entry in result['evidence']
                         if entry['source'] == 'list_incident_wafers']
        self.assertEqual([page['offset'] for page in wafer_results], list(range(8)))
        self.assertTrue(all(page['status'] == 'PARTIAL' for page in wafer_results))
        self.assertTrue(all(page['coverage'] for page in wafer_results))

    def test_unfiltered_wafer_chain_restarts_after_filtered_chain(self):
        self.use_temporary_skill_lock()
        self.settings.data['runtime']['max_tool_calls'] = 20
        steps = [self.lookup()]
        steps.extend(('router', plan(stage='tools', tool='list_incident_lots',
                                     arguments={'page_size': 1, 'offset': offset}))
                     for offset in range(3))
        steps.extend(('router', plan(stage='tools', tool='list_incident_wafers', arguments={
            'lot_ids': ['SYN-LOT-01-01'], 'page_size': 1, 'offset': offset})) for offset in range(2))
        steps.extend(('router', plan(stage='tools', tool='list_incident_wafers',
                                     arguments={'page_size': 1, 'offset': offset}))
                     for offset in range(8))
        steps.extend(self.finish_steps())
        result, client = self.run_script(steps)
        self.assertEqual(result['status'], 'answered', result)
        self.assertFalse(client.calls[6][2]['wafer_lookup_complete'])
        self.assertTrue(client.calls[14][2]['wafer_lookup_complete'])
        self.assertEqual([entry['arguments'].get('lot_ids') for entry in result['evidence']
                          if entry['source'] == 'list_incident_wafers'][:2],
                         [['SYN-LOT-01-01'], ['SYN-LOT-01-01']])

    def test_new_incident_scope_resets_completed_pagination(self):
        self.use_temporary_skill_lock()
        steps = [self.lookup()]
        steps.extend(('router', plan(stage='tools', tool='list_incident_lots',
                                     arguments={'page_size': 1, 'offset': offset}))
                     for offset in range(3))
        steps.extend([self.lookup('SYN-2026-02'), *self.finish_steps()])
        result, client = self.run_script(steps)
        self.assertEqual(result['status'], 'answered', result)
        self.assertTrue(client.calls[4][2]['lot_lookup_complete'])
        self.assertFalse(client.calls[5][2]['lot_lookup_complete'])
        self.assertEqual([entry['source'] for entry in result['evidence']], ['find_incidents'])
        self.assertEqual(result['final_scope']['confirmed']['incidents'][0]['incident_number'], 'SYN-2026-02')

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

    def test_chat_memory_is_role_bounded_unverified_and_not_accumulated_in_router_history(self):
        messages = []
        for index in range(10):
            messages.extend([{'id': f'u{index}', 'role': 'user', 'content': 'SEM synthetic question ' * 200},
                             {'id': f'a{index}', 'role': 'assistant', 'content': 'OLD_UNVERIFIED_CLAIM ' * 300}])
        turns = select_turns(messages, 'SEM', self.settings.data['runtime']['conversation_memory'])
        result, client = self.run_script([self.lookup(), *self.finish_steps()], conversation_turns=turns,
                                         context_data={'selected_incident': 'SYN-2026-01'})
        self.assertEqual(result['status'], 'answered', result)
        sizes = {}
        for role, _, payload in client.calls:
            memory = payload['context_data_unverified']['previous_messages_unverified']
            size = len(json.dumps(memory, ensure_ascii=False, separators=(',', ':')))
            self.assertLessEqual(size, 2400 if role == 'router' else 4800)
            sizes[role] = size
            self.assertEqual(payload['requirements'], ['synthetic contract question'])
        self.assertLess(sizes['router'], sizes['answer'])
        self.assertNotIn('OLD_UNVERIFIED_CLAIM', json.dumps(result['evidence']))
        self.assertNotIn('OLD_UNVERIFIED_CLAIM', json.dumps(client.histories))
        starts = [event for event in result['events'] if event['event'] == 'llm_start']
        self.assertTrue(all(event['conversation_memory']['messages'] for event in starts))
        self.assertEqual(result['llm_calls'], 4)

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

    def test_final_zero_match_uses_code_response_without_judge_or_answer(self):
        result, client = self.run_script([self.lookup('SYN-2026-99'),
                                         ('router', plan('ready_for_judge', 'tools'))])
        self.assertEqual(result['status'], 'answered', result)
        self.assertIn('0건', result['answer'])
        self.assertEqual([row[0] for row in client.calls], ['router', 'router'])
        self.assertEqual(result['lookup_conditions'], {'incident_number': 'SYN-2026-99'})

    def test_scope_mismatch_from_engineering_callback_is_not_evidence(self):
        self.settings.data['runtime']['max_retries'] = 0
        callback = Mock(return_value={'status': 'OK', 'scope': {'incident_ids': ['wrong']}, 'sections': {}})
        result, _ = self.run_script([self.lookup(), ('router', plan(stage='tools', tool='get_engineering_snapshot'))],
                                    engineering_query=callback)
        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('ENGINEERING_EVIDENCE_SCOPE_MISMATCH', result['limitations'])
        self.assertNotIn('get_engineering_snapshot', [row['source'] for row in result['evidence']])

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

    def test_payload_keeps_tool_availability_and_router_prompt_only_has_enabled_schemas(self):
        self.settings.data['value_matching']['enabled'] = False
        self.settings.data['meetings']['enabled'] = False
        self.settings.data['synthetic_action_planner']['enabled'] = False
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
        expected['search_engineer_notes']['enabled'] = False
        expected['search_internal_documents']['enabled'] = False
        expected['search_mes_reference']['enabled'] = False
        expected['get_platform_evidence']['enabled'] = False
        expected['search_platform_history']['enabled'] = False
        expected['plan_synthetic_action_evidence'].update(
            enabled=False, configured=False, runtime_injected=False,
            phase_gate='incident_scope_and_complete_lot_wafer_lookup_required')
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
                lines = prompt.splitlines()
                header = next(index for index, line in enumerate(lines)
                              if line.startswith('[skills/') and line.endswith('/references/tools.json]'))
                body = []
                for line in lines[header + 1:]:
                    if line.startswith('['):
                        break
                    body.append(line)
                prompt_catalog = json.loads('\n'.join(body))
                enabled = {name for name, spec in ready.items() if spec['enabled']}
                self.assertEqual(set(prompt_catalog), enabled)

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
        self.use_temporary_skill_lock()
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

    def test_invalid_timestamp_tool_result_is_dropped_and_requires_successful_requery(self):
        invalid = {'status': 'OK', 'items': [{'chunk_id': 'invalid-chunk', 'meeting_id': 'm1',
                   'version': 'v1', 'meeting_date': '', 'text': 'synthetic private text'}],
                   'retrieval_method': 'synthetic', 'as_of': '2026-03-31', 'incident_ids': None}
        valid = {'status': 'OK', 'items': [{'chunk_id': 'valid-chunk', 'meeting_id': 'm1',
                 'version': 'v1', 'meeting_date': None, 'text': 'synthetic accepted text'}],
                 'retrieval_method': 'synthetic', 'as_of': '2026-03-31', 'incident_ids': None}
        steps = [self.lookup(),
                 ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'bad'})),
                 ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'bad'})),
                 ('router', plan('ready_for_judge', 'tools')), ('judge', judge), ('answer', answer)]
        with patch.object(agent.MeetingTools, 'search', side_effect=[invalid, valid]) as search:
            result, client = self.run_script(steps)

        roles = [role for role, *_ in client.calls]
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(search.call_count, 2)
        self.assertEqual(roles, ['router', 'router', 'router', 'router', 'judge', 'answer'])
        self.assertEqual([entry['result']['items'][0]['chunk_id'] for entry in result['evidence']
                          if entry['source'] == 'search_meeting_minutes'], ['valid-chunk'])
        errors = [event.get('error') for event in result['events']
                  if event['event'] == 'validation_or_tool_error']
        self.assertIn('EVIDENCE_TIMESTAMP_INVALID', errors)
        self.assertNotIn('synthetic private text', json.dumps(client.histories))
        self.assertNotIn('invalid-chunk', json.dumps(result['evidence']))

    def test_invalid_timestamp_failure_survives_different_or_failed_requery(self):
        invalid = {'status': 'OK', 'items': [{'chunk_id': 'invalid-chunk', 'meeting_id': 'm1',
                   'version': 'v1', 'meeting_date': '', 'text': 'synthetic private text'}],
                   'retrieval_method': 'synthetic', 'as_of': '2026-03-31', 'incident_ids': None}
        for retry_query, retry_result in (('different', {'status': 'NO_MATCH', 'items': [],
                                                'retrieval_method': 'synthetic', 'as_of': '2026-03-31',
                                                'incident_ids': None}),
                                          ('same', invalid)):
            with self.subTest(retry_query=retry_query):
                steps = [self.lookup(),
                         ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'same'})),
                         ('router', plan(stage='tools', tool='search_meeting_minutes',
                                         arguments={'query': retry_query})),
                         ('router', plan('ready_for_judge', 'tools')),
                         ('router', {**plan('blocked', 'tools'), 'limitations': ['must requery safely']}),]
                with patch.object(agent.MeetingTools, 'search', side_effect=[invalid, retry_result]):
                    result, client = self.run_script(steps)

                self.assertEqual(result['status'], 'unavailable', result)
                self.assertNotIn('judge', [role for role, *_ in client.calls])
                errors = [event.get('error') for event in result['events']
                          if event['event'] == 'validation_or_tool_error']
                self.assertIn('EVIDENCE_TIMESTAMP_INVALID', errors)

    def test_missing_timestamp_remains_unknown_and_is_accepted(self):
        for timestamp in ('missing', None):
            with self.subTest(timestamp=timestamp):
                item = {'chunk_id': 'missing-time', 'meeting_id': 'm1', 'version': 'v1',
                        'text': 'synthetic text'}
                if timestamp is None:
                    item['meeting_date'] = None
                result_payload = {'status': 'OK', 'items': [item], 'retrieval_method': 'synthetic',
                                  'as_of': '2026-03-31', 'incident_ids': None}
                steps = [self.lookup(),
                         ('router', plan(stage='tools', tool='search_meeting_minutes', arguments={'query': 'missing'})),
                         ('router', plan('ready_for_judge', 'tools')), ('judge', judge), ('answer', answer)]
                with patch.object(agent.MeetingTools, 'search', return_value=result_payload):
                    result, client = self.run_script(steps)

                self.assertEqual(result['status'], 'answered', result)
                self.assertEqual([role for role, *_ in client.calls],
                                 ['router', 'router', 'router', 'judge', 'answer'])
                self.assertEqual(result['evidence'][-1]['result']['items'][0]['chunk_id'], 'missing-time')

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

    def use_temporary_skill_lock(self):
        lock_dir = tempfile.TemporaryDirectory()
        self.addCleanup(lock_dir.cleanup)
        self.settings.data['paths']['skill_lock_file'] = str(Path(lock_dir.name) / 'release.lock.json')
        import skill_loader
        skill_loader.freeze(settings=self.settings)

    def test_non_platform_review_skips_platform_builders(self):
        self.use_temporary_skill_lock()
        import platform_facts
        import investigation_plans
        with patch.object(platform_facts, 'build_platform_facts', wraps=platform_facts.build_platform_facts) as facts, \
             patch.object(investigation_plans, 'build_investigations', wraps=investigation_plans.build_investigations) as investigations:
            result, client = self.run_script([self.lookup(), *self.finish_steps()])

        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual([role for role, *_ in client.calls], ['router', 'router', 'judge', 'answer'])
        self.assertEqual([entry['id'] for entry in result['evidence']], ['e1'])
        self.assertEqual(facts.call_count, 0)
        self.assertEqual(investigations.call_count, 0)

    def test_platform_tool_preserves_role_payload_facts_and_evidence_with_bounded_builds(self):
        self.use_temporary_skill_lock()
        self.settings.data['platform'] = {'enabled': True}
        synthetic_result = {
            'status': 'OK', 'synthetic': True,
            'sections': {'measure': {'status': 'OK', 'count': 1, 'rows': []}},
            'summaries': {'measure': [{'item': 'SYN-MEASURE', 'samples': 10,
                                       'outside_limits': 2, 'unit': 'um', 'mean': 1.5}]},
            'tabular_analysis': {'status': 'OK', 'chip_count': 10, 'feature_count': 2,
                                 'source_feature_count': 2, 'dummy_feature_count': 0,
                                 'flagged_chip_count': 1},
            'cross_modal_alignment': {'chip_counts': {'legacy_measure_out_of_spec': 0}},
            'model_observations': [], 'map_analysis': {},
        }
        def platform_answer(payload):
            return {'status': 'answered', 'answer': 'fixed synthetic response', 'claims': [], 'limitations': [],
                    'selected_fact_ids': [fact['fact_id'] for fact in payload['platform_facts']],
                    'ranked_investigation_ids': [item['id'] for item in payload['platform_investigations']]}

        steps = [self.lookup(),
                 ('router', plan(stage='tools', tool='list_incident_lots')),
                 ('router', plan(stage='tools', tool='get_platform_evidence')),
                 ('router', plan('ready_for_judge', 'tools')),
                 ('judge', judge), ('answer', platform_answer)]
        import platform_facts
        import investigation_plans
        with patch.object(agent.IncidentTools, 'get_platform_evidence', return_value=synthetic_result), \
             patch.object(agent, 'RoleClient', return_value=ScriptedClient(steps)) as client_factory, \
             patch.object(platform_facts, 'build_platform_facts', wraps=platform_facts.build_platform_facts) as facts, \
             patch.object(investigation_plans, 'build_investigations', wraps=investigation_plans.build_investigations) as investigations:
            client = client_factory.return_value
            result = agent.run(self.settings, 'synthetic contract question', 'tester', as_of='2026-03-31')

        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual([role for role, *_ in client.calls], ['router', 'router', 'router', 'router', 'judge', 'answer'])
        self.assertEqual([(entry['id'], entry['source']) for entry in result['evidence']], [
            ('e1', 'find_incidents'), ('e2', 'list_incident_lots'), ('e3', 'get_platform_evidence')])
        fact_ids = [fact['fact_id'] for fact in result['platform_facts']]
        self.assertTrue(fact_ids)
        self.assertTrue(all(fact['evidence_ids'] in (['e2'], ['e3']) for fact in result['platform_facts']))
        self.assertTrue(any(fact['evidence_ids'] == ['e3'] for fact in result['platform_facts']))
        judge_payload = client.calls[4][2]
        answer_payload = client.calls[5][2]
        self.assertEqual(judge_payload['evidence_ids'], ['e1', 'e2', 'e3'])
        self.assertEqual(answer_payload['evidence_ids'], ['e1', 'e2', 'e3'])
        self.assertNotIn('platform_facts', client.calls[0][2])
        self.assertNotIn('platform_investigations', client.calls[0][2])
        self.assertEqual([fact['fact_id'] for fact in judge_payload['platform_facts']], fact_ids)
        self.assertEqual([fact['fact_id'] for fact in answer_payload['platform_facts']], fact_ids)
        self.assertEqual([item['id'] for item in judge_payload['platform_investigations']],
                         [item['id'] for item in answer_payload['platform_investigations']])
        first_fact = next(fact for fact in result['platform_facts']
                          if fact['fact_id'] == result['claims'][0]['claim_id'])
        self.assertEqual(result['claims'][0]['evidence_ids'], first_fact['evidence_ids'])
        self.assertEqual(facts.call_count, 4)
        self.assertEqual(investigations.call_count, 4)

    def test_platform_tools_are_hidden_when_platform_is_disabled(self):
        self.use_temporary_skill_lock()
        self.settings.data['platform'] = {'enabled': False}
        result, client = self.run_script([
            self.lookup(), ('router', {**plan('blocked', 'tools'), 'limitations': ['stop after scope check']})])

        self.assertEqual(result['status'], 'unavailable', result)
        available = client.calls[1][2]['available_tools']
        self.assertFalse(available['get_platform_evidence']['enabled'])
        self.assertFalse(available['search_platform_history']['enabled'])

    def test_enabled_platform_tools_require_incident_then_lot_scope(self):
        self.use_temporary_skill_lock()
        self.settings.data['platform'] = {'enabled': True}
        steps = [self.lookup(), ('router', plan(stage='tools', tool='list_incident_lots')),
                 ('router', {**plan('blocked', 'tools'), 'limitations': ['inspect enabled catalog']})]
        result, client = self.run_script(steps)

        self.assertEqual(result['status'], 'unavailable', result)
        before_incident = client.calls[0][2]['available_tools']
        after_incident_before_lot = client.calls[1][2]['available_tools']
        after_lot = client.calls[2][2]['available_tools']
        self.assertFalse(before_incident['get_platform_evidence']['enabled'])
        self.assertFalse(before_incident['search_platform_history']['enabled'])
        self.assertFalse(after_incident_before_lot['get_platform_evidence']['enabled'])
        self.assertFalse(after_incident_before_lot['search_platform_history']['enabled'])
        self.assertTrue(after_lot['get_platform_evidence']['enabled'])
        self.assertTrue(after_lot['search_platform_history']['enabled'])

    def test_platform_history_receives_only_selected_incident_scope(self):
        self.use_temporary_skill_lock()
        self.settings.data['platform'] = {'enabled': True}
        observed = {}
        def history(db, actor, scope_id, as_of, top_k=5):
            observed.update(actor=actor, ids=list(db._scope(actor, scope_id)['ids']), as_of=as_of, top_k=top_k)
            return {'status': 'NO_MATCH', 'items': [], 'scope': {'incident_ids': observed['ids'], 'as_of': as_of},
                    'candidate_count': 0, 'truncated': False, 'limitations': []}
        steps = [self.lookup(), ('router', plan(stage='tools', tool='list_incident_lots')),
                 ('router', plan(stage='tools', tool='search_platform_history', arguments={'top_k': 3})),
                 ('router', plan('ready_for_judge', 'tools')), ('judge', judge), ('answer', answer)]
        with patch.object(agent.IncidentTools, 'search_platform_history', autospec=True, side_effect=history):
            result, client = self.run_script(steps)

        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(observed, {'actor': 'tester', 'ids': [result['evidence'][0]['result']['data'][0]['incident_id']],
                                    'as_of': '2026-03-31', 'top_k': 3})
        history_entry = next(entry for entry in result['evidence'] if entry['source'] == 'search_platform_history')
        self.assertEqual(history_entry['id'], 'e3')
        self.assertEqual(history_entry['result']['scope']['incident_ids'], observed['ids'])

    def test_platform_history_rejects_multi_incident_scope(self):
        self.use_temporary_skill_lock()
        self.settings.data['platform'] = {'enabled': True}
        cohort = plan(tool='find_incidents', arguments={
            'filters': {'department': 'SYNTH-QA'}, 'scope_mode': 'cohort'}, search_mode='sql_filter')
        cohort['intents'] = ['analysis']
        cohort['filters'] = cohort['plan'][0]['arguments']['filters']
        steps = [
            ('router', cohort),
            ('router', plan(stage='tools', tool='list_incident_lots')),
            ('router', plan(stage='tools', tool='search_platform_history')),
            ('router', {**plan('blocked', 'tools'), 'limitations': ['single incident scope required']}),
        ]
        with patch('platform_tools.PlatformTools.__init__',
                   autospec=True, side_effect=lambda self, settings, tool: setattr(self, 'tool', tool)):
            result, _ = self.run_script(steps)

        self.assertEqual(result['status'], 'unavailable', result)
        errors = [event.get('error') for event in result['events']
                  if event['event'] == 'validation_or_tool_error']
        self.assertIn('PLATFORM_HISTORY_REQUIRES_SINGLE_INCIDENT', errors)


if __name__ == '__main__':
    unittest.main()
