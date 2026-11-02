"""Run-level synthetic regressions for retrieval failures across incident scopes."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
sys.path.insert(0, str(ROOT / 'tests'))

import agent
from config_loader import DEFAULT_CONFIG, Settings, load_config
from demo_data import generate
from skill_loader import freeze
from test_agent import ScriptedClient, plan, judge, answer


class ScopeTransitionRetrievalE2E(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        data = load_config(DEFAULT_CONFIG, DEFAULT_CONFIG.parent / 'demo.yaml').data
        data['paths'].update(data_root=str(root), golden_file=str(root / 'golden.jsonl'),
                             skill_lock_file=str(root / 'release.lock.json'))
        data['database']['sqlite_file'] = str(root / 'incidents.sqlite')
        data['meetings']['sqlite_file'] = str(root / 'meetings.sqlite')
        data['retrieval']['internal_documents']['enabled'] = True
        self.settings = Settings(data, ())
        generate(self.settings)
        freeze(settings=self.settings)
        self.tool = 'search_internal_documents'
        self.requested = [self.tool]

    @staticmethod
    def lookup(number):
        return ('router', plan(tool='find_incidents', arguments={'incident_number': number},
                               search_mode='sql_exact'))

    @staticmethod
    def doc(query):
        return ('router', plan(stage='tools', tool='search_internal_documents',
                               arguments={'query': query, 'top_k': 1}))

    def run_steps(self, steps, callback):
        client = ScriptedClient(steps)
        with patch.object(agent, 'RoleClient', return_value=client):
            result = agent.run(self.settings, 'synthetic incident document lookup', 'tester',
                               as_of='2026-03-31', requested_tools=self.requested,
                               document_query=callback, document_allowed_statuses={'internal_documents': ['released']})
        return result, client

    def test_failed_a_document_retrieval_is_retired_on_explicit_b_selection(self):
        calls = []
        def retrieve(**kwargs):
            calls.append(kwargs)
            if kwargs['incident_ids'] == ['synthetic-pk-2026-01']:
                raise RuntimeError('secret synthetic backend detail')
            return {'status': 'NO_MATCH', 'retrieval_method': 'bm25_vector_hybrid',
                    'as_of': kwargs['as_of'], 'items': [], 'truncated': False,
                    'candidate_count': 0}

        # The synthetic database's incident numbers are selected explicitly by the scripted Router.
        result, client = self.run_steps([self.lookup('SYN-2026-01'), self.doc('A query'),
                                         self.lookup('SYN-2026-02'), self.doc('B query'),
                                         ('judge', judge), ('answer', answer)], retrieve)
        self.assertEqual(result['status'], 'answered', result)
        self.assertNotIn('secret synthetic backend detail', json.dumps(result, ensure_ascii=False))
        self.assertEqual([role for role, _, _ in client.calls][-2:], ['judge', 'answer'])
        self.assertFalse(any(entry['source'] == 'find_incidents' and
                             entry['result'].get('data', [{}])[0].get('incident_number') == 'SYN-2026-01'
                             for entry in result['evidence']))

    def test_same_scope_refresh_does_not_clear_failure_and_blocks_judge(self):
        self.settings.data['runtime']['max_agent_steps'] = 4
        self.settings.data['runtime']['max_tool_calls'] = 3
        calls = []
        def retrieve(**kwargs):
            calls.append(kwargs)
            raise RuntimeError('secret synthetic backend detail')

        result, client = self.run_steps([self.lookup('SYN-2026-01'), self.doc('same query'),
                                         self.doc('same query'),
                                         ('router', plan('ready_for_judge', 'tools'))], retrieve)
        self.assertNotIn('judge', [role for role, _, _ in client.calls])
        self.assertTrue(any(event.get('event') == 'judge_blocked' and
                            event.get('reason') == 'RETRIEVAL_REQUERY_REQUIRED'
                            for event in result['events']), result)
        self.assertNotIn('secret synthetic backend detail', json.dumps(result, ensure_ascii=False))

    def test_different_query_success_does_not_retire_failed_request(self):
        def retrieve(**kwargs):
            if kwargs['query'] == 'failed query':
                raise RuntimeError('secret synthetic backend detail')
            return {'status': 'NO_MATCH', 'retrieval_method': 'bm25_vector_hybrid',
                    'as_of': kwargs['as_of'], 'items': [], 'truncated': False,
                    'candidate_count': 0}

        result, client = self.run_steps([self.lookup('SYN-2026-01'), self.doc('failed query'),
                                         self.doc('different query'),
                                         ('router', plan('ready_for_judge', 'tools'))], retrieve)
        self.assertNotIn('judge', [role for role, _, _ in client.calls])
        self.assertTrue(any(event.get('event') == 'judge_blocked' and
                            event.get('reason') == 'RETRIEVAL_REQUERY_REQUIRED'
                            for event in result['events']))
        self.assertNotIn('secret synthetic backend detail', json.dumps(result, ensure_ascii=False))

