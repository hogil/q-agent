"""End-to-end local-provider transport against disposable synthetic SQLite sources."""
import json
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

import agent
from config_loader import DEFAULT_CONFIG, Settings, load_config
from demo_data import generate
from skill_loader import freeze
from runtime_factory import open_synthetic_mes_reference


class LocalProviderSyntheticMESE2E(unittest.TestCase):
    def test_role_client_runs_incident_mes_judge_answer_with_json_schema_transport(self):
        received = []
        request_count = {'router': 0}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append(request)
                self.server.observed_path = self.path
                payload = json.loads(request['messages'][-1]['content'])
                system_prompt = request['messages'][0]['content']
                role = ('router' if request.get('response_format', {}).get('json_schema', {}).get('name') == 'router_output'
                        else 'judge' if '[skills/roles/judge/' in system_prompt else 'answer')
                if role == 'router':
                    request_count['router'] += 1
                    if request_count['router'] == 1:
                        name, args = 'find_incidents', {'incident_number': 'SYN-2026-01'}
                    elif request_count['router'] == 2:
                        name, args = 'search_mes_reference', {'kind': 'product', 'query': 'Alpha', 'top_k': 5}
                    elif request_count['router'] == 4:
                        name, args = 'search_mes_reference', {'kind': 'product', 'query': 'Beta', 'top_k': 5}
                    else:
                        name = None
                    output = ({'intents': ['search'], 'filters': {}, 'plan': [{'tool': name, 'arguments': args,
                               'depends_on': [], 'reason': 'synthetic end-to-end lookup'}], 'needs_skills': [],
                               'clarification': None, 'decision': 'execute',
                               'stage': 'incident' if name == 'find_incidents' else 'tools',
                               'search_mode': 'sql_exact' if name == 'find_incidents' else 'none', 'limitations': []}
                              if name else {'intents': ['analysis'], 'filters': {}, 'plan': [], 'needs_skills': [],
                               'clarification': None, 'decision': 'ready_for_judge', 'stage': 'tools',
                               'search_mode': 'none', 'limitations': []})
                    message = {'role': 'assistant', 'content': json.dumps(output)}
                    finish = 'stop'
                elif role == 'judge':
                    ids = payload['evidence_ids']
                    if sum(1 for row in received if row.get('response_format', {}).get('json_schema', {}).get('name') == 'judge_output') == 1:
                        judgment = {'verdict': 'need_evidence', 'return_to': 'router',
                                    'coverage': [{'requirement': payload['question'], 'status': 'missing', 'evidence_ids': []}],
                                    'issues': [{'type': 'insufficient_evidence', 'reason': 'synthetic requery exercise',
                                                'evidence_ids': [], 'next_action': 'recheck available evidence'}]}
                    else:
                        judgment = {'verdict': 'pass', 'return_to': 'answer',
                                    'coverage': [{'requirement': payload['question'], 'status': 'satisfied', 'evidence_ids': ids}],
                                    'issues': []}
                    message = {'role': 'assistant', 'content': json.dumps(judgment)}
                    finish = 'stop'
                else:
                    ids = payload['evidence_ids']
                    message = {'role': 'assistant', 'content': json.dumps({'status': 'answered',
                               'answer': 'Synthetic MES reference retrieved.', 'claims': [{'claim_id': 'c1',
                               'text': 'Synthetic MES evidence supports this response.', 'evidence_ids': ids}],
                               'limitations': [], 'inspection_plan': None})}
                    finish = 'stop'
                result = {'id': 'local-stub', 'object': 'chat.completion', 'created': 0, 'model': 'local-stub',
                          'choices': [{'index': 0, 'finish_reason': finish, 'message': message}],
                          'usage': {'prompt_tokens': 11, 'completion_tokens': 7, 'total_tokens': 18}}
                encoded = json.dumps(result).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *_args):
                pass

        class LoopbackServer(ThreadingHTTPServer):
            daemon_threads = True
            block_on_close = False

        server = LoopbackServer(('127.0.0.1', 0), Handler)
        server_thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        server_thread.start()
        self.addCleanup(self._stop_server, server, server_thread)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings_data = load_config(DEFAULT_CONFIG, DEFAULT_CONFIG.parent / 'demo.yaml').data
            settings_data['paths'].update(data_root=str(root), golden_file=str(root / 'golden.jsonl'),
                                          skill_lock_file=str(root / 'test-skill-lock.json'))
            settings_data['database']['sqlite_file'] = str(root / 'incidents.sqlite')
            settings_data['meetings']['sqlite_file'] = str(root / 'meetings.sqlite')
            settings_data['models']['text'].update(enabled=True, mode='api', structured_outputs=True,
                base_url=f'http://127.0.0.1:{server.server_port}/v1', api_key_env='QAGENT_TEST_LOOPBACK_KEY',
                served_model='local-stub', timeout_seconds=3)
            settings_data['runtime']['max_retries'] = 0
            settings = Settings(settings_data, ())
            freeze(settings=settings)
            generate(settings, profile='basic', include_goldens=False)
            mes_path = root / 'mes.sqlite'
            with closing(sqlite3.connect(mes_path)) as db:
                db.execute('CREATE TABLE refs (kind, record_id, version, name, source_ref, available_at, effective_from, effective_to, applicability, incident_ids)')
                db.execute('INSERT INTO refs VALUES (?,?,?,?,?,?,?,?,?,?)', ('product', 'SYN-PROD-1', 'v1', 'Alpha',
                    'synthetic://mes/1', '2026-03-01T00:00:00Z', '2026-01-01T00:00:00Z', None,
                    'candidate', json.dumps(['synthetic-pk-2026-01'])))
                db.commit()
            settings_data['mes_reference'] = {'enabled': True, 'top_k': 5, 'allowed_kinds': ['product'],
                'synthetic_sqlite': {'enabled': True, 'database_file': str(mes_path), 'table': 'refs',
                    'timezone': 'UTC', 'columns': {key: key for key in ('kind', 'record_id', 'version', 'name',
                        'source_ref', 'available_at', 'effective_from', 'effective_to', 'applicability', 'incident_ids')}}}
            settings = Settings(settings_data, ())
            with patch.dict(os.environ, {'QAGENT_TEST_LOOPBACK_KEY': 'synthetic-test-key'}):
                result = agent.run(settings, 'SYN-2026-01 사고 Product Alpha 기준정보 조회', 'synthetic-test', as_of='2026-03-31',
                                   mes_reference_query=open_synthetic_mes_reference(settings))

        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(server.observed_path, '/v1/chat/completions')
        self.assertEqual(len(received), 8)
        self.assertEqual([r['model'] for r in received], ['local-stub'] * 8)
        for request in received:
            self.assertEqual(request['response_format']['type'], 'json_schema')
            self.assertTrue(request['response_format']['json_schema']['strict'])
            self.assertNotIn('tools', request)
            self.assertNotIn('tool_choice', request)
            self.assertNotIn('functions', request)
            self.assertNotIn('function_call', request)
        # Router history carries the assistant plan and the code-generated receipt into the next Router turn.
        second_router = received[2]['messages']
        self.assertTrue(any(m['role'] == 'assistant' and m.get('content') for m in second_router))
        self.assertTrue(any(m['role'] == 'user' and 'plan_result' in m.get('content', '') for m in second_router))
        # Judge requests a recheck; the next Router sees that review state and retained Tool receipt.
        requery_router = received[4]
        self.assertEqual(requery_router['response_format']['json_schema']['name'], 'router_output')
        self.assertEqual(json.loads(requery_router['messages'][-1]['content'])['judge']['verdict'], 'need_evidence')
        self.assertTrue(any(m['role'] == 'user' and 'plan_result' in m.get('content', '')
                            for m in requery_router['messages']))
        requery_plans = [json.loads(message['content']) for message in received[5]['messages']
                         if message['role'] == 'assistant' and message.get('content')]
        self.assertTrue(any(plan.get('plan') and plan['plan'][0]['arguments'].get('query') == 'Beta'
                            for plan in requery_plans))
        self.assertEqual(received[6]['response_format']['json_schema']['name'], 'judge_output')
        usage = result['execution_metrics']['provider_usage']
        self.assertEqual(usage['input_tokens']['total'], 88)
        self.assertEqual(usage['output_tokens']['total'], 56)
        self.assertEqual(usage['total_tokens']['total'], 144)
        mes_evidence = [row for row in result['evidence'] if row['source'] == 'search_mes_reference']
        self.assertEqual(len(mes_evidence), 2)
        incident_id = result['evidence'][0]['result']['data'][0]['incident_id']
        self.assertEqual(mes_evidence[0]['result']['incident_ids'], [incident_id])
        self.assertEqual(mes_evidence[0]['result']['as_of'], '2026-03-31')
        self.assertEqual(mes_evidence[0]['result']['items'][0]['record_id'], 'SYN-PROD-1')
        self.assertEqual(mes_evidence[1]['result']['status'], 'NO_MATCH')
        self.assertEqual(mes_evidence[1]['result']['incident_ids'], [incident_id])
        self.assertEqual(mes_evidence[1]['result']['as_of'], '2026-03-31')
        expected_evidence_ids = {row['id'] for row in result['evidence']}
        self.assertEqual(set(json.loads(received[6]['messages'][-1]['content'])['evidence_ids']), expected_evidence_ids)
        self.assertEqual(set(json.loads(received[7]['messages'][-1]['content'])['evidence_ids']), expected_evidence_ids)

    def test_role_client_runs_incident_mes_judge_answer_over_loopback(self):
        received = []
        request_count = {'router': 0}

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.server.observed_path = self.path
                request = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append(request)
                payload = json.loads(request['messages'][-1]['content'])
                system_prompt = request['messages'][0]['content']
                role = ('router' if 'tools' in request else
                        'judge' if '[skills/roles/judge/' in system_prompt else 'answer')
                if role == 'router':
                    request_count['router'] += 1
                    if request_count['router'] == 1:
                        name, args = 'find_incidents', {'incident_number': 'SYN-2026-01'}
                    elif request_count['router'] == 2:
                        name, args = 'search_mes_reference', {'kind': 'product', 'query': 'Alpha', 'top_k': 5}
                    else:
                        name = None
                    if name:
                        output = {'intents': ['search'], 'filters': {}, 'plan': [{'tool': name, 'arguments': args,
                                  'depends_on': [], 'reason': 'synthetic end-to-end lookup'}], 'needs_skills': [],
                                  'clarification': None, 'decision': 'execute',
                                  'stage': 'incident' if name == 'find_incidents' else 'tools',
                                  'search_mode': 'sql_exact' if name == 'find_incidents' else 'none', 'limitations': []}
                        message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': f'call-{len(received)}',
                                   'type': 'function', 'function': {'name': 'submit_plan', 'arguments': json.dumps(output)}}]}
                        finish = 'tool_calls'
                    else:
                        output = {'intents': ['analysis'], 'filters': {}, 'plan': [], 'needs_skills': [],
                                  'clarification': None, 'decision': 'ready_for_judge', 'stage': 'tools',
                                  'search_mode': 'none', 'limitations': []}
                        message = {'role': 'assistant', 'content': None, 'tool_calls': [{'id': f'call-{len(received)}',
                                   'type': 'function', 'function': {'name': 'submit_plan', 'arguments': json.dumps(output)}}]}
                        finish = 'tool_calls'
                elif role == 'judge':
                    ids = payload['evidence_ids']
                    message = {'role': 'assistant', 'content': json.dumps({'verdict': 'pass', 'return_to': 'answer',
                               'coverage': [{'requirement': payload['question'], 'status': 'satisfied', 'evidence_ids': ids}], 'issues': []})}
                    finish = 'stop'
                else:
                    ids = payload['evidence_ids']
                    message = {'role': 'assistant', 'content': json.dumps({'status': 'answered',
                               'answer': 'Synthetic MES reference retrieved.', 'claims': [{'claim_id': 'c1',
                               'text': 'Synthetic MES evidence supports this response.', 'evidence_ids': ids}],
                               'limitations': [], 'inspection_plan': None})}
                    finish = 'stop'
                result = {'id': 'local-stub', 'object': 'chat.completion', 'created': 0, 'model': 'local-stub',
                          'choices': [{'index': 0, 'finish_reason': finish, 'message': message}],
                          'usage': {'prompt_tokens': 11, 'completion_tokens': 7, 'total_tokens': 18}}
                encoded = json.dumps(result).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(encoded)))
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(self, *_args):
                pass

        class LoopbackServer(ThreadingHTTPServer):
            daemon_threads = True
            block_on_close = False

        server = LoopbackServer(('127.0.0.1', 0), Handler)
        server_thread = Thread(target=server.serve_forever, kwargs={'poll_interval': 0.05}, daemon=True)
        server_thread.start()
        self.addCleanup(self._stop_server, server, server_thread)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            settings_data = load_config(DEFAULT_CONFIG, DEFAULT_CONFIG.parent / 'demo.yaml').data
            settings_data['paths'].update(data_root=str(root), golden_file=str(root / 'golden.jsonl'),
                                          skill_lock_file=str(root / 'test-skill-lock.json'))
            settings_data['database']['sqlite_file'] = str(root / 'incidents.sqlite')
            settings_data['meetings']['sqlite_file'] = str(root / 'meetings.sqlite')
            settings_data['models']['text'].update(enabled=True, mode='api',
                base_url=f'http://127.0.0.1:{server.server_port}/v1', api_key_env='QAGENT_TEST_LOOPBACK_KEY',
                served_model='local-stub', timeout_seconds=3)
            settings_data['runtime']['max_retries'] = 0
            settings = Settings(settings_data, ())
            freeze(settings=settings)
            generate(settings, profile='basic', include_goldens=False)
            mes_path = root / 'mes.sqlite'
            with closing(sqlite3.connect(mes_path)) as db:
                db.execute('CREATE TABLE refs (kind, record_id, version, name, source_ref, available_at, effective_from, effective_to, applicability, incident_ids)')
                db.execute('INSERT INTO refs VALUES (?,?,?,?,?,?,?,?,?,?)', ('product', 'SYN-PROD-1', 'v1', 'Alpha',
                    'synthetic://mes/1', '2026-03-01T00:00:00Z', '2026-01-01T00:00:00Z', None,
                    'candidate', json.dumps(['synthetic-pk-2026-01'])))
                db.commit()
            settings_data['mes_reference'] = {'enabled': True, 'top_k': 5, 'allowed_kinds': ['product'],
                'synthetic_sqlite': {'enabled': True, 'database_file': str(mes_path), 'table': 'refs',
                    'timezone': 'UTC', 'columns': {key: key for key in ('kind', 'record_id', 'version', 'name',
                        'source_ref', 'available_at', 'effective_from', 'effective_to', 'applicability', 'incident_ids')}}}
            settings = Settings(settings_data, ())
            with patch.dict(os.environ, {'QAGENT_TEST_LOOPBACK_KEY': 'synthetic-test-key'}):
                result = agent.run(settings, 'SYN-2026-01 사고 Product Alpha 기준정보 조회', 'synthetic-test', as_of='2026-03-31',
                                   mes_reference_query=open_synthetic_mes_reference(settings))

        self.assertEqual(result['status'], 'answered', result)
        self.assertEqual(server.observed_path, '/v1/chat/completions')
        self.assertEqual(len(received), 5)
        self.assertEqual([r['model'] for r in received], ['local-stub'] * 5)
        self.assertEqual([r.get('tools') is not None for r in received], [True, True, True, False, False])
        usage = result['execution_metrics']['provider_usage']
        self.assertEqual(usage['input_tokens']['total'], 55)
        self.assertEqual(usage['output_tokens']['total'], 35)
        self.assertEqual(usage['total_tokens']['total'], 90)
        mes_evidence = [row for row in result['evidence'] if row['source'] == 'search_mes_reference']
        self.assertEqual(len(mes_evidence), 1)
        incident_id = result['evidence'][0]['result']['data'][0]['incident_id']
        self.assertEqual(mes_evidence[0]['result']['incident_ids'], [incident_id])
        self.assertEqual(mes_evidence[0]['result']['as_of'], '2026-03-31')
        self.assertEqual(mes_evidence[0]['result']['items'][0]['record_id'], 'SYN-PROD-1')

    @staticmethod
    def _stop_server(server, thread):
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
