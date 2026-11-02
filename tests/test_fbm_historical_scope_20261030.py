"""Synthetic end-to-end historical scope checks for callback-backed FBM search."""
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


class FBMHistoricalScopeTests(unittest.TestCase):
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
    def _steps(*, include_related, fbm_args=None):
        steps = [('router', plan(tool='find_incidents', arguments={'incident_number': 'SYN-2026-01'},
                                 search_mode='sql_exact')),
                 ('router', plan(stage='tools', tool='list_incident_lots',
                                 arguments={'page_size': 100, 'offset': 0})),
                 ('router', plan(stage='tools', tool='list_incident_wafers',
                                 arguments={'page_size': 100, 'offset': 0}))]
        if include_related:
            steps.append(('router', plan(stage='tools', tool='search_related_incidents',
                                         arguments={'terms': ['합성']})))
        steps.extend([
            ('router', plan(stage='tools', tool='search_similar_fbm', arguments=fbm_args or {
                'source_incident_id': 'synthetic-pk-2026-01', 'lot_id': 'SYN-LOT-01-01',
                'wafer_id': 'W01', 'representation': 'raw_fbm'})),
            ('judge', judge), ('answer', answer),
        ])
        return steps

    def run_agent(self, steps, callback):
        self.settings.data['runtime']['max_retries'] = 0
        client = ScriptedClient(steps)
        with patch.object(agent, 'RoleClient', return_value=client):
            result = agent.run(self.settings, '합성 wafer 유사 FBM 조회', 'synthetic-tester',
                               as_of='2026-03-31', requested_tools=['search_similar_fbm'],
                               fbm_search_query=callback)
        return result, client

    @staticmethod
    def _item(incident_id, relation, rank, *, lot_id='SYN-LOT-01-01', wafer_id='W01'):
        return {'incident_id': incident_id, 'lot_id': lot_id, 'wafer_id': wafer_id,
                'asset_id': f'SYN-ASSET-{rank}', 'revision': 'r1',
                'available_at': '2026-03-30T12:00:00+09:00', 'rank': rank,
                'similarity': 0.9 - rank / 100, 'relation': relation}

    @classmethod
    def _response(cls, kwargs, items):
        query = dict(kwargs['query_wafer'], asset_id='SYN-QUERY-ASSET', revision='r1',
                     available_at='2026-03-30T12:00:00+09:00')
        return {'status': 'OK', 'as_of': kwargs['as_of'],
                'representation': kwargs['representation'], 'query': query,
                'items': items, 'model_id': 'synthetic-model', 'model_version': '1',
                'preprocess_version': 'p1', 'checkpoint_sha256': 'a' * 64,
                'truncated': None}

    def test_successful_related_evidence_binds_historical_candidates_and_keeps_direct_scope(self):
        calls = []

        def callback(**kwargs):
            calls.append(kwargs)
            return self._response(kwargs, [
                self._item(kwargs['incident_ids'][0], 'direct', 1),
                self._item(kwargs['historical_incident_ids'][0], 'historical_candidate', 2,
                           lot_id='SYN-HIST-LOT', wafer_id='H01'),
            ])

        result, _ = self.run_agent(self._steps(include_related=True), callback)

        self.assertEqual(result['status'], 'answered', result)
        related = next(entry for entry in result['evidence'] if entry['source'] == 'search_related_incidents')
        related_ids = list(dict.fromkeys(item['incident_id'] for item in related['result']['items']))
        self.assertTrue(related_ids)
        self.assertEqual(calls[0]['historical_incident_ids'], related_ids)
        self.assertNotIn(calls[0]['incident_ids'][0], related_ids)
        fbm = next(entry for entry in result['evidence'] if entry['source'] == 'search_similar_fbm')
        self.assertEqual(fbm['result']['items'][0]['incident_id'], calls[0]['incident_ids'][0])
        self.assertEqual(fbm['result']['items'][0]['relation'], 'direct')
        self.assertEqual(fbm['result']['items'][1]['incident_id'], related_ids[0])
        self.assertEqual(fbm['result']['items'][1]['relation'], 'historical_candidate')

    def test_unregistered_historical_callback_result_is_rejected(self):
        calls = []

        def callback(**kwargs):
            calls.append(kwargs)
            return self._response(kwargs, [
                self._item(kwargs['incident_ids'][0], 'direct', 1),
                self._item('synthetic-pk-not-in-related-evidence', 'historical_candidate', 2,
                           lot_id='SYN-HIST-LOT', wafer_id='H01'),
            ])

        result, _ = self.run_agent(self._steps(include_related=True), callback)

        self.assertTrue(calls[0]['historical_incident_ids'])
        self.assertEqual(result['status'], 'unavailable', result)
        self.assertNotIn('search_similar_fbm', [entry['source'] for entry in result['evidence']])
        self.assertIn('FBM_RETRIEVAL_FAILED', result.get('limitations', []))

    def test_without_related_evidence_callback_has_empty_historical_scope(self):
        calls = []

        def callback(**kwargs):
            calls.append(kwargs)
            return self._response(kwargs, [
                self._item(kwargs['incident_ids'][0], 'direct', 1),
                self._item('synthetic-pk-2026-02', 'historical_candidate', 2,
                           lot_id='SYN-HIST-LOT', wafer_id='H01'),
            ])

        result, _ = self.run_agent(self._steps(include_related=False), callback)

        self.assertEqual(calls[0]['historical_incident_ids'], [])
        self.assertEqual(result['status'], 'unavailable', result)
        self.assertFalse(any(entry['source'] == 'search_related_incidents' for entry in result['evidence']))
        self.assertNotIn('search_similar_fbm', [entry['source'] for entry in result['evidence']])
        self.assertIn('FBM_RETRIEVAL_FAILED', result.get('limitations', []))


if __name__ == '__main__':
    unittest.main()
