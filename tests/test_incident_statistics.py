import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from config_loader import Settings, load_config
from demo_data import generate
from incident_tools import ToolError
from incident_statistics import render_statistics
from runtime_factory import open_incident_tools


class IncidentStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        data = load_config(ROOT / 'config/config.yaml', ROOT / 'config/demo.yaml').data
        data['paths'].update(data_root=str(root), golden_file=str(root / 'golden.jsonl'))
        data['database']['sqlite_file'] = str(root / 'incidents.sqlite')
        data['meetings']['sqlite_file'] = str(root / 'meetings.sqlite')
        self.settings = Settings(data, ())
        generate(self.settings)

    def test_full_population_and_overlapping_generations(self):
        with open_incident_tools(self.settings) as tool:
            result = tool.summarize_incidents('tester', {'department': 'SYNTH-QA'}, ['product_generations'], top_k=1)
            self.assertEqual(result['total_incidents'], 9)
            self.assertEqual(result['groups'], [{'product_generations': 'SYN-GEN-A', 'incident_count': 9}])
            self.assertEqual(result['group_count'], 3)
            self.assertTrue(result['groups_truncated'])
            self.assertEqual(result['recorded_quantities']['expected_lot_count']['sum'], 24)
            self.assertEqual(result['recorded_quantities']['affected_wafer_count']['sum'], 168)
            self.assertEqual(tool._scope('tester', result['scope_id'])['ids'].__len__(), 9)

    def test_period_comparison_and_zero_baseline(self):
        current = {'gte': '2026-03-01T00:00:00+09:00', 'lt': '2026-04-01T00:00:00+09:00'}
        prior = {'gte': '2026-02-01T00:00:00+09:00', 'lt': '2026-03-01T00:00:00+09:00'}
        with open_incident_tools(self.settings) as tool:
            result = tool.summarize_incidents('tester', {'department': 'SYNTH-QA', 'occurred_at': current},
                                             comparison_period=prior, as_of='2026-03-31')
            self.assertEqual(result['total_incidents'], 4)
            self.assertEqual(result['comparison']['total_incidents'], 3)
            self.assertEqual(result['comparison']['delta_incidents'], 1)
            self.assertAlmostEqual(result['comparison']['change_percent'], 100 / 3)
            text = render_statistics({'id': 'e1', 'result': result})['answer']
            self.assertIn('조회 기준일: 2026-03-31', text)
            self.assertIn('비교 기간:', text)
            generations = tool.summarize_incidents('tester', {'occurred_at': current}, ['product_generations'], comparison_period=prior)
            self.assertEqual({row['product_generations']: row['incident_count'] for row in generations['comparison']['groups']},
                             {'SYN-GEN-A': 3, 'SYN-GEN-B': 2, 'SYN-GEN-C': 1})
            empty = {'gte': '2025-02-01T00:00:00Z', 'lt': '2025-03-01T00:00:00Z'}
            result = tool.summarize_incidents('tester', {'occurred_at': current}, comparison_period=empty)
            self.assertIsNone(result['comparison']['change_percent'])

    def test_summary_scope_limit_does_not_truncate_counts(self):
        self.settings.data['runtime']['max_scope_incidents'] = 2
        with open_incident_tools(self.settings) as tool:
            result = tool.summarize_incidents('tester', {'department': 'SYNTH-QA'})
            self.assertEqual(result['total_incidents'], 9)
            self.assertFalse(result['scope_complete'])
            with self.assertRaisesRegex(ToolError, 'SUMMARY_ONLY_SCOPE'):
                tool.list_incident_lots('tester', result['scope_id'])
            with self.assertRaisesRegex(ToolError, 'SCOPE_ACTOR_MISMATCH'):
                tool._scope('other', result['scope_id'])

    def test_cohort_scope_and_identity_ambiguity(self):
        with open_incident_tools(self.settings) as tool:
            candidates = tool.find_incidents('tester', filters={'department': 'SYNTH-QA'})
            self.assertTrue(candidates['requires_selection'])
            cohort = tool.find_incidents('tester', filters={'department': 'SYNTH-QA'}, scope_mode='cohort')
            self.assertFalse(cohort['requires_selection'])
            self.assertEqual(len(tool._scope('tester', cohort['scope_id'])['ids']), 9)
            for arguments in ({'title': '점검', 'title_match': 'contains'},
                              {'filters': {'title_terms': ['점검']}}, {'incident_number': 'SYN-2026-01'}):
                with self.assertRaisesRegex(ToolError, 'COHORT_CANNOT'):
                    tool.find_incidents('tester', scope_mode='cohort', **arguments)

    def test_reject_unsupported_metrics_invalid_period_and_empty_filters(self):
        with open_incident_tools(self.settings) as tool:
            for arguments in ({'filters': {}}, {'filters': {'department': 'SYNTH-QA'}, 'group_by': ['loss']},
                              {'filters': {'department': 'SYNTH-QA'}, 'comparison_period': {'gte': 'bad', 'lt': 'bad'}},
                              {'filters': {'occurred_at': {'gte': 'bad', 'lt': 'bad'}}}):
                with self.subTest(arguments=arguments), self.assertRaises(ToolError):
                    tool.summarize_incidents('tester', **arguments)
            self.assertFalse(tool.db.in_transaction)
