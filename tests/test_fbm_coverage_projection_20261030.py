"""Agent-path projection of incident-grain FBM source coverage."""
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
from fbm_search_contract import project_source_coverage
from skill_loader import freeze
from test_agent import ScriptedClient, answer, judge, plan


class FBMCoverageProjectionTests(unittest.TestCase):
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
        data['relations']['source_completeness'] = 'unknown'
        data['relations']['wafer_source_completeness'] = 'partial'
        data['relations']['wafer_scope'] = 'lot_inventory'
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

    def _run(self, callback):
        steps = [('router', plan(tool='find_incidents', arguments={'incident_number': 'SYN-2026-01'},
                                 search_mode='sql_exact')),
                 ('router', plan(stage='tools', tool='list_incident_lots',
                                 arguments={'page_size': 100, 'offset': 0})),
                 ('router', plan(stage='tools', tool='list_incident_wafers',
                                 arguments={'page_size': 100, 'offset': 0})),
                 ('router', plan(stage='tools', tool='search_similar_fbm', arguments={
                     'source_incident_id': 'synthetic-pk-2026-01', 'lot_id': 'SYN-LOT-01-01',
                     'wafer_id': 'W01', 'representation': 'raw_fbm'})),
                 ('judge', judge), ('answer', answer)]
        client = ScriptedClient(steps)
        with patch.object(agent, 'RoleClient', return_value=client):
            return agent.run(self.settings, '합성 wafer 유사 FBM 조회', 'synthetic-tester',
                             as_of='2026-03-31', requested_tools=['search_similar_fbm'],
                             fbm_search_query=callback)

    @staticmethod
    def _response(query):
        record = dict(query, asset_id='SYN-ASSET-1', revision='r1',
                      available_at='2026-03-30T12:00:00+09:00')
        return {'status': 'OK', 'as_of': '2026-03-31', 'representation': 'raw_fbm',
                'query': record, 'items': [dict(record, asset_id='SYN-ASSET-2', rank=1, similarity=0.9, relation='direct')],
                'model_id': 'synthetic-model', 'model_version': '1', 'preprocess_version': 'p1',
                'checkpoint_sha256': 'a' * 64, 'truncated': None}

    def test_projects_only_selected_incident_and_preserves_unknown_inventory_and_rank_caveats(self):
        def callback(**kwargs):
            return self._response(kwargs['query_wafer'])

        result = self._run(callback)
        self.assertEqual(result['status'], 'answered', result)
        evidence = next(row for row in result['evidence'] if row['source'] == 'search_similar_fbm')
        projected = evidence['result']['source_coverage']
        self.assertEqual(projected['grain'], 'incident')
        self.assertEqual(set(projected), {'grain', 'lot', 'wafer'})
        self.assertEqual(set(projected['lot']), {'state', 'expected_lots', 'returned_total_lots'})
        self.assertEqual(set(projected['wafer']), {'state', 'expected_wafers', 'returned_total_wafers'})
        self.assertEqual(projected['lot']['expected_lots'], 3)
        self.assertIsNone(projected['wafer']['expected_wafers'])
        self.assertEqual(projected['wafer']['returned_total_wafers'], 8)
        self.assertEqual(evidence['result']['source_completeness'], 'partial')
        self.assertEqual(evidence['result']['source_wafer_scope'], 'lot_inventory')
        self.assertIn('inventory_context_only_not_incident_impact', evidence['result']['limitations'])
        self.assertIn('source_completeness_not_declared_complete', evidence['result']['limitations'])
        self.assertIn('lot_wafer_snapshot_as_of_unverified', evidence['result']['limitations'])
        self.assertIn('source_ranking_unverified', evidence['result']['limitations'])

    def test_missing_selected_coverage_is_explicit_and_other_incident_is_not_projected(self):
        original_lots = agent.IncidentTools.list_incident_lots
        original_wafers = agent.IncidentTools.list_incident_wafers

        def lots(self, *args, **kwargs):
            result = original_lots(self, *args, **kwargs)
            result['coverage'] = []
            return result

        def wafers(self, *args, **kwargs):
            result = original_wafers(self, *args, **kwargs)
            result['coverage'] = []
            return result

        with patch.object(agent.IncidentTools, 'list_incident_lots', lots), \
                patch.object(agent.IncidentTools, 'list_incident_wafers', wafers):
            result = self._run(lambda **kwargs: self._response(kwargs['query_wafer']))
        self.assertEqual(result['status'], 'answered', result)
        evidence = next(row for row in result['evidence'] if row['source'] == 'search_similar_fbm')
        self.assertEqual(evidence['result']['source_coverage']['lot'],
                         {'state': 'missing', 'expected_lots': None, 'returned_total_lots': None})
        self.assertEqual(evidence['result']['source_coverage']['wafer'],
                         {'state': 'missing', 'expected_wafers': None, 'returned_total_wafers': None})
        self.assertNotIn('secret', str(evidence['result']['source_coverage']))

    def test_duplicate_selected_coverage_and_invalid_count_fail_closed(self):
        original = agent.IncidentTools.list_incident_lots
        for rows in (
            [{'incident_id': 'synthetic-pk-2026-01', 'state': 'ok', 'expected_lots': 1,
              'returned_total_lots': 1}, {'incident_id': 'synthetic-pk-2026-01', 'state': 'ok',
                                           'expected_lots': 1, 'returned_total_lots': 1}],
            [{'incident_id': 'synthetic-pk-2026-01', 'state': 'ok', 'expected_lots': True,
              'returned_total_lots': 1}],
            [{'incident_id': 'synthetic-pk-2026-01', 'state': 'ok', 'expected_lots': -1,
              'returned_total_lots': 1}],
        ):
            with self.subTest(rows=rows):
                def tampered(self, *args, **kwargs):
                    result = original(self, *args, **kwargs)
                    result['coverage'] = rows
                    return result

                self.settings.data['runtime']['max_retries'] = 0
                with patch.object(agent.IncidentTools, 'list_incident_lots', tampered):
                    result = self._run(lambda **kwargs: self._response(kwargs['query_wafer']))
                self.assertEqual(result['status'], 'unavailable')
                self.assertNotIn('search_similar_fbm', [row['source'] for row in result['evidence']])

    def test_projection_rejects_non_dict_source_rows(self):
        with self.assertRaises(ValueError):
            project_source_coverage('incident-1', [None], [])


if __name__ == '__main__':
    unittest.main()
