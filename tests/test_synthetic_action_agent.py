"""Synthetic-only main Agent integration for proposal-only action evidence."""
import copy
import gc
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

import agent
from config_loader import DEFAULT_CONFIG, SPEC, Settings, check_shape, load_config
from demo_data import generate
from skill_loader import freeze
from synthetic_sqlite_action_lease import sqlite_action_snapshot_lease_provider
from test_agent import ScriptedClient, answer, judge, plan


def certificate(scoped, *, execution=True):
    return {
        'scope': [list(pair) for pair in scoped['scope']], 'as_of': scoped['as_of'].isoformat(),
        'revision': scoped['revision'], 'evidence': [], 'remaining_hypotheses': ['synthetic-h1'],
        'admissible_action_sets': [['HOLD']], 'decision_sufficient': True, 'causal_proof': False,
        'release_allowed': False, 'release_blocking_risk_hypotheses': ['synthetic-h1'],
        'requested_action_allowed': False, 'spent_cost': 0.0, 'cost_budget': 1.0,
        'remaining_cost_budget': 1.0, 'next_test_projected_spent_cost': 1.0,
        'next_test': {'id': 'synthetic-test', 'worst_case_action_sets': 1,
                      'action_disagreement_reduction': 1, 'reduction_per_cost': 1.0,
                      'execution_granted': execution},
    }


class DetailPageCompletenessTests(unittest.TestCase):
    def test_page_completeness_requires_first_intermediate_and_final_pages(self):
        def page(offset, count, next_offset, status='OK'):
            return {'status': status, 'scope_id': 'scope-1', 'offset': offset,
                    'total_memberships': 3, 'items': [{'incident_id': 'inc-1', 'lot_id': f'lot-{i}'}
                                                      for i in range(offset, offset + count)],
                    'next_offset': next_offset, 'source_completeness': 'declared_complete',
                    'mapping_version': 'map-v1', 'coverage': [{'incident_id': 'inc-1',
                                                               'state': 'complete_by_declared_source_and_count'}],
                    'lot_coverage': None, 'wafer_scope': None}

        self.assertFalse(agent.detail_pages_complete([page(0, 1, 1)], 'lots'), 'first page alone')
        self.assertFalse(agent.detail_pages_complete([page(2, 1, None)], 'lots'), 'last page alone')
        self.assertFalse(agent.detail_pages_complete([page(0, 1, 1), page(2, 1, None)], 'lots'),
                         'middle page missing')
        self.assertFalse(agent.detail_pages_complete([page(0, 1, 1, status='PARTIAL'),
                                                      page(1, 1, 2), page(2, 1, None)], 'lots'),
                         'PARTIAL status')
        self.assertTrue(agent.detail_pages_complete([page(0, 1, 1), page(1, 1, 2), page(2, 1, None)], 'lots'))

        duplicate_lots = page(0, 2, None)
        duplicate_lots['total_memberships'] = 2
        duplicate_lots['items'] = [{'incident_id': 'inc-1', 'lot_id': 'same-lot'}] * 2
        self.assertFalse(agent.detail_pages_complete([duplicate_lots], 'lots'), 'duplicate lot membership')
        duplicate_wafers = page(0, 2, None)
        duplicate_wafers['total_memberships'] = 2
        duplicate_wafers['items'] = [{'incident_id': 'inc-1', 'lot_id': 'same-lot', 'wafer_id': 'W01'}] * 2
        duplicate_wafers['wafer_scope'] = 'incident_affected'
        duplicate_wafers['lot_coverage'] = [{'incident_id': 'inc-1',
            'state': 'complete_by_declared_source_and_count'}]
        duplicate_wafers['lots_without_wafer_rows'] = []
        self.assertFalse(agent.detail_pages_complete([duplicate_wafers], 'wafers'), 'duplicate wafer membership')

    def test_retrieval_failures_retire_only_after_confirmed_membership_change(self):
        failures = [
            {'key': 'old-a', 'scope_id': 'scope-a', 'incident_ids': ['inc-a'], 'tool': 'docs'},
            {'key': 'old-a2', 'scope_id': 'scope-a', 'incident_ids': ['inc-a'], 'tool': 'planner'},
            {'key': 'other', 'scope_id': 'scope-b', 'incident_ids': ['inc-b'], 'tool': 'docs'},
        ]
        self.assertEqual(agent.failures_after_confirmed_membership_change(failures, ['inc-a'], ['inc-a']),
                         failures, 'new scope ID with same incident membership cannot clear failures')
        self.assertEqual(agent.failures_after_confirmed_membership_change(failures, ['inc-a'], None),
                         failures, 'unconfirmed or multi-candidate scope fails closed')
        self.assertEqual(agent.failures_after_confirmed_membership_change(failures, None, ['inc-b']),
                         failures, 'missing prior confirmed membership cannot retire failures')
        self.assertEqual(agent.failures_after_confirmed_membership_change(failures, ['inc-a'], ['inc-b']),
                         [failures[-1]], 'only failures attached to the prior membership are retired')


class SyntheticActionAgentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(gc.collect)
        data = copy.deepcopy(load_config(DEFAULT_CONFIG, DEFAULT_CONFIG.parent / 'demo.yaml').data)
        root = Path(self.temp.name)
        data['paths'].update(data_root=str(root), golden_file=str(root / 'golden.jsonl'))
        data['database']['sqlite_file'] = str(root / 'incidents.sqlite')
        data['meetings']['sqlite_file'] = str(root / 'meetings.sqlite')
        data['paths']['skill_lock_file'] = str(root / 'release.lock.json')
        data['relations']['source_completeness'] = 'declared_complete'
        data['relations']['wafer_source_completeness'] = 'declared_complete'
        data['relations']['wafer_scope'] = 'incident_affected'
        data['synthetic_action_planner'] = {'enabled': True}
        self.settings = Settings(data, ())
        freeze(settings=self.settings)
        generate(self.settings)
        conn = sqlite3.connect(data['database']['sqlite_file'])
        try:
            conn.execute('UPDATE demo_incident SET affected_wafer_count = '
                         '(SELECT COUNT(*) FROM demo_wafer_list w '
                         'WHERE w.accident_ref = demo_incident.accident_pk)')
            conn.execute('CREATE TABLE synthetic_action_manifest (revision TEXT, as_of TEXT)')
            conn.execute('INSERT INTO synthetic_action_manifest VALUES (?, ?)',
                         ('synthetic-revision-1', '2026-03-31T00:00:00Z'))
            conn.commit()
        finally:
            conn.close()
        self.lease_provider = sqlite_action_snapshot_lease_provider(lambda conn: {
            'revision': conn.execute('SELECT revision FROM synthetic_action_manifest').fetchone()[0],
            'as_of': conn.execute('SELECT as_of FROM synthetic_action_manifest').fetchone()[0],
        })

    def run_script(self, steps, **kwargs):
        client = ScriptedClient(steps)
        with patch.object(agent, 'RoleClient', return_value=client):
            result = agent.run(self.settings, '합성 조치 evidence 검토', 'synthetic-tester',
                               as_of='2026-03-31', **kwargs)
        return result, client

    def e2e_steps(self, planner_arguments=None):
        def wafer_args(payload):
            return plan(stage='tools', tool='list_incident_wafers',
                        arguments={'page_size': 100, 'offset': 0})

        def planner_result(scoped):
            return certificate(scoped)

        return [
            ('router', plan(tool='find_incidents', arguments={'incident_number': 'SYN-2026-01'},
                            search_mode='sql_exact')),
            ('router', plan(stage='tools', tool='list_incident_lots', arguments={'page_size': 100, 'offset': 0})),
            ('router', wafer_args),
            ('router', plan(stage='tools', tool='plan_synthetic_action_evidence',
                            arguments=planner_arguments or {})),
            ('judge', judge), ('answer', answer),
        ], planner_result

    def test_incident_first_complete_bridge_planner_judge_answer_and_execution_false(self):
        steps, planner = self.e2e_steps()
        received = []
        def callback(scoped):
            received.append(scoped)
            return planner(scoped)
        result, client = self.run_script(steps, requested_tools=[
            'find_incidents', 'plan_synthetic_action_evidence'],
            synthetic_action_planner=callback, snapshot_lease_provider=self.lease_provider)
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual([row['source'] for row in result['evidence']], [
            'find_incidents', 'list_incident_lots', 'list_incident_wafers', 'plan_synthetic_action_evidence'])
        self.assertEqual(len(received), 1)
        self.assertEqual(result['evidence'][-1]['result']['revision'], 'synthetic-revision-1')
        self.assertFalse(result['evidence'][-1]['result']['execution_granted'])
        self.assertFalse(result['evidence'][-1]['result']['next_test']['execution_granted'])
        self.assertTrue(client.calls[-2][2]['synthetic_action_provenance_and_assumptions'])
        self.assertTrue(client.calls[-1][2]['synthetic_action_provenance_and_assumptions'])
        self.assertEqual([role for role, _, _ in client.calls][-2:], ['judge', 'answer'])

    def test_no_scope_or_time_callback_on_external_arguments_or_cutoff_mismatch(self):
        calls = []
        self.settings.data['runtime']['max_retries'] = 0
        steps, planner = self.e2e_steps({'scope_id': 'outside'})
        result, _ = self.run_script(steps, requested_tools=['find_incidents', 'plan_synthetic_action_evidence'],
                                    synthetic_action_planner=lambda scoped: calls.append(scoped),
                                    snapshot_lease_provider=self.lease_provider)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(calls, [])

        steps, _ = self.e2e_steps()
        original_provider = self.lease_provider
        future_provider = sqlite_action_snapshot_lease_provider(lambda conn: {
            'revision': conn.execute('SELECT revision FROM synthetic_action_manifest').fetchone()[0],
            'as_of': '2026-04-01T00:00:00Z',
        })
        callback = patch.object(agent, 'RoleClient', return_value=ScriptedClient(steps))
        with callback:
            result = agent.run(self.settings, '합성 조치 evidence 검토', 'synthetic-tester',
                               as_of='2026-03-31', requested_tools=['find_incidents', 'plan_synthetic_action_evidence'],
                               synthetic_action_planner=lambda scoped: calls.append(scoped),
                               snapshot_lease_provider=future_provider)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(calls, [])

    def test_sensitive_callback_errors_are_sanitized_and_block_judge(self):
        self.settings.data['runtime']['max_retries'] = 0
        steps, _ = self.e2e_steps()
        result, client = self.run_script(steps, requested_tools=['find_incidents', 'plan_synthetic_action_evidence'],
            synthetic_action_planner=Mock(side_effect=RuntimeError('SECRET_ACTOR_DB_PASSWORD')),
            snapshot_lease_provider=self.lease_provider)
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('SECRET_ACTOR_DB_PASSWORD', str(result))
        self.assertNotIn('judge', [role for role, _, _ in client.calls])

    def test_disabled_or_missing_injection_and_disabled_config_remain_unavailable(self):
        steps, _ = self.e2e_steps()
        result, client = self.run_script(steps, requested_tools=['plan_synthetic_action_evidence'])
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(client.calls, [])

        self.settings.data['synthetic_action_planner']['enabled'] = False
        result, _ = self.run_script(steps, requested_tools=['plan_synthetic_action_evidence'],
            synthetic_action_planner=lambda scoped: certificate(scoped),
            snapshot_lease_provider=self.lease_provider)
        self.assertEqual(result['status'], 'unavailable')

    def test_planner_configuration_uses_strict_boolean(self):
        invalid = copy.deepcopy(self.settings.data)
        invalid['synthetic_action_planner']['enabled'] = 1
        with self.assertRaises(ValueError):
            check_shape(invalid, SPEC)

    def test_callback_failure_retry_does_not_reuse_stale_evidence(self):
        steps, _ = self.e2e_steps()
        steps[-2:] = [('router', plan(stage='tools', tool='plan_synthetic_action_evidence')),
                      ('router', plan(stage='tools', tool='plan_synthetic_action_evidence')),
                      ('router', plan(stage='tools', tool='plan_synthetic_action_evidence'))]
        callback = Mock(side_effect=RuntimeError('PRIVATE_FAILURE'))
        result, client = self.run_script(steps, requested_tools=['find_incidents', 'plan_synthetic_action_evidence'],
            synthetic_action_planner=callback, snapshot_lease_provider=self.lease_provider)
        self.assertEqual(result['status'], 'unavailable')
        self.assertNotIn('judge', [role for role, _, _ in client.calls])
        self.assertNotIn('PRIVATE_FAILURE', str(result))
        self.assertGreaterEqual(callback.call_count, 1)

if __name__ == '__main__':
    unittest.main()
