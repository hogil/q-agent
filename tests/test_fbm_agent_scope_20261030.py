"""Synthetic scoped Agent integration for callback-backed FBM search."""
import copy
import gc
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

import agent
from config_loader import DEFAULT_CONFIG, Settings, load_config
from demo_data import generate
from skill_loader import freeze
from test_agent import ScriptedClient, answer, judge, plan


class FBMAgentScopeTests(unittest.TestCase):
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
        data['fbm_search'] = {'enabled': True, 'top_k': 5}
        self.settings = Settings(data, ())
        freeze(settings=self.settings)
        generate(self.settings, include_goldens=False)
        conn = sqlite3.connect(data['database']['sqlite_file'])
        try:
            conn.execute('UPDATE demo_incident SET affected_wafer_count = '
                         '(SELECT COUNT(*) FROM demo_wafer_list w '
                         'WHERE w.accident_ref = demo_incident.accident_pk)')
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _steps(*, with_lots=True, with_wafers=True, wafer_page_size=100,
               wafer_offsets=None, fbm_args=None):
        steps = [('router', plan(tool='find_incidents', arguments={'incident_number': 'SYN-2026-01'},
                                 search_mode='sql_exact'))]
        if with_lots:
            steps.append(('router', plan(stage='tools', tool='list_incident_lots',
                                         arguments={'page_size': 100, 'offset': 0})))
        if with_wafers:
            for offset in (wafer_offsets if wafer_offsets is not None else [0]):
                steps.append(('router', plan(stage='tools', tool='list_incident_wafers',
                                             arguments={'page_size': wafer_page_size, 'offset': offset})))
        steps.append(('router', plan(stage='tools', tool='search_similar_fbm', arguments=fbm_args or {
            'source_incident_id': 'synthetic-pk-2026-01', 'lot_id': 'SYN-LOT-01-01',
            'wafer_id': 'W01', 'representation': 'raw_fbm'})))
        steps.extend([('judge', judge), ('answer', answer)])
        return steps

    def run_agent(self, steps, callback=None):
        client = ScriptedClient(steps)
        self.client = client
        with patch.object(agent, 'RoleClient', return_value=client):
            return agent.run(self.settings, '합성 wafer 유사 FBM 조회', 'synthetic-tester',
                             as_of='2026-03-31', requested_tools=['search_similar_fbm'],
                             fbm_search_query=callback)

    @staticmethod
    def _response(query, *, future=False):
        record = dict(query, asset_id='SYN-ASSET-1', revision='r1',
                      available_at='2026-04-01T00:00:00+09:00' if future else '2026-03-30T12:00:00+09:00')
        return {'status': 'OK', 'as_of': '2026-03-31', 'representation': 'raw_fbm',
                'query': record, 'items': [dict(record, asset_id='SYN-ASSET-2', rank=1, similarity=0.9, relation='direct')],
                'model_id': 'synthetic-model', 'model_version': '1', 'preprocess_version': 'p1',
                'checkpoint_sha256': 'a' * 64, 'truncated': None}

    def test_disabled_config_or_missing_callback_does_not_run_agent(self):
        self.settings.data['fbm_search']['enabled'] = False
        called = []
        result = self.run_agent(self._steps(), lambda **kwargs: called.append(kwargs))
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(called, [])

    def test_incomplete_pages_and_invalid_wafer_block_callback(self):
        called = []
        self.settings.data['runtime']['max_retries'] = 0
        result = self.run_agent(self._steps(wafer_page_size=1), lambda **kwargs: called.append(kwargs))
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(called, [])

        steps = self._steps(fbm_args={'source_incident_id': 'synthetic-pk-2026-01', 'lot_id': 'SYN-LOT-01-01',
                                      'wafer_id': 'W99', 'representation': 'raw_fbm'})
        result = self.run_agent(steps, lambda **kwargs: called.append(kwargs))
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(called, [])

    def test_callback_receives_only_bound_scope_and_valid_result_is_recorded(self):
        calls = []

        def callback(**kwargs):
            calls.append(kwargs)
            return self._response(kwargs['query_wafer'])

        result = self.run_agent(self._steps(), callback)
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]['actor'], 'synthetic-tester')
        self.assertEqual(calls[0]['incident_ids'], ['synthetic-pk-2026-01'])
        self.assertEqual(calls[0]['historical_incident_ids'], [])
        self.assertEqual(calls[0]['query_wafer'], {'incident_id': 'synthetic-pk-2026-01',
                                                   'lot_id': 'SYN-LOT-01-01', 'wafer_id': 'W01'})
        self.assertEqual(calls[0]['representation'], 'raw_fbm')
        self.assertEqual(calls[0]['as_of'], '2026-03-31')
        self.assertEqual(calls[0]['top_k'], 5)
        evidence = next(item for item in result['evidence'] if item['source'] == 'search_similar_fbm')
        self.assertEqual(evidence['result']['items'][0]['similarity'], 0.9)
        self.assertEqual(evidence['result']['source_wafer_scope'], 'incident_affected')
        self.assertEqual(evidence['result']['source_completeness'], 'declared_complete')
        self.assertIn('lot_wafer_snapshot_as_of_unverified', evidence['result']['limitations'])

    def test_complete_lot_inventory_chain_is_context_only_and_incomplete_or_forged_scope_is_blocked(self):
        self.settings.data['relations']['wafer_scope'] = 'lot_inventory'
        calls = []

        def callback(**kwargs):
            calls.append(kwargs)
            return self._response(kwargs['query_wafer'])

        result = self.run_agent(self._steps(), callback)
        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(len(calls), 1)
        evidence = next(item for item in result['evidence'] if item['source'] == 'search_similar_fbm')
        self.assertEqual(evidence['result']['source_wafer_scope'], 'lot_inventory')
        self.assertEqual(evidence['result']['source_completeness'], 'declared_complete')
        self.assertIn('inventory_context_only_not_incident_impact', evidence['result']['limitations'])
        self.assertIn('lot_wafer_snapshot_as_of_unverified', evidence['result']['limitations'])

        self.settings.data['runtime']['max_retries'] = 0
        calls.clear()
        result = self.run_agent(self._steps(wafer_page_size=1), callback)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(calls, [])

    def test_page_chain_coverage_and_status_mismatch_blocks_fbm(self):
        self.settings.data['relations']['wafer_scope'] = 'lot_inventory'
        self.settings.data['runtime']['max_retries'] = 0
        original = agent.IncidentTools.list_incident_wafers
        for field in ('coverage', 'status'):
            with self.subTest(field=field):
                calls = []

                def callback(**kwargs):
                    calls.append(kwargs)
                    return self._response(kwargs['query_wafer'])

                def tampered(self, actor, scope_id, lot_ids=None, page_size=None, offset=0):
                    result = original(self, actor, scope_id, lot_ids=lot_ids,
                                      page_size=page_size, offset=offset)
                    if offset == 3:
                        if field == 'coverage':
                            result['coverage'][0]['state'] = 'forged_coverage'
                        else:
                            result['status'] = 'OK'
                    return result

                with patch.object(agent.IncidentTools, 'list_incident_wafers', tampered):
                    result = self.run_agent(self._steps(wafer_page_size=3,
                                                        wafer_offsets=[0, 3, 6]), callback)
                self.assertEqual(result['status'], 'unavailable')
                self.assertEqual(calls, [])

        for completeness in ('unknown', 'partial'):
            with self.subTest(source_completeness=completeness):
                self.settings.data['relations']['wafer_source_completeness'] = completeness
                result = self.run_agent(self._steps(), callback)
                self.assertEqual(result['status'], 'answered', result)
                item = next(row for row in result['evidence'] if row['source'] == 'search_similar_fbm')
                self.assertEqual(item['result']['source_completeness'], completeness)
                self.assertIn('source_completeness_not_declared_complete', item['result']['limitations'])

        calls.clear()
        forged = self._steps(fbm_args={'source_incident_id': 'synthetic-pk-2026-01',
                                       'lot_id': 'SYN-LOT-01-01', 'wafer_id': 'W99',
                                       'representation': 'raw_fbm'})
        result = self.run_agent(forged, callback)
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(calls, [])

    def test_scope_mismatch_or_future_response_fails_closed(self):
        self.settings.data['runtime']['max_retries'] = 0
        for future in (False, True):
            with self.subTest(future=future):
                def callback(**kwargs):
                    response = self._response(kwargs['query_wafer'], future=future)
                    if not future:
                        response['query']['wafer_id'] = 'W99'
                    return response

                result = self.run_agent(self._steps(), callback)
                self.assertEqual(result['status'], 'unavailable')
                self.assertNotIn('search_similar_fbm', [item['source'] for item in result['evidence']])
                self.assertTrue(any(item.get('tool') == 'search_similar_fbm'
                                    for item in result['state']['retrieval_failures'])
                                if isinstance(result.get('state'), dict) else
                                'FBM_RETRIEVAL_FAILED' in result.get('limitations', []))

