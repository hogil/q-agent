"""SQL connector checks against a real local database; no company DB access."""
import copy
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from config_loader import ConfigError, load_config, validate_values
from enterprise_tools import EnterpriseTools, _time
from incident_tools import ToolError


class EnterpriseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'mes.sqlite'
        conn = sqlite3.connect(self.db)
        conn.execute('CREATE TABLE events (id TEXT, eqp TEXT, step TEXT, start TEXT, end TEXT, state TEXT)')
        conn.executemany('INSERT INTO events VALUES (?,?,?,?,?,?)', [
            ('pm', 'EQ1', 'STEP1', '2026-03-01T20:00:00Z', '2026-03-02T01:00:00Z', 'PM'),
            ('down', 'EQ1', 'STEP1', '2026-03-02T03:00:00Z', '2026-03-02T06:00:00Z', 'DOWN'),
            ('other-eqp', 'EQ2', 'STEP1', '2026-03-02T03:00:00Z', None, 'RUN'),
            ('other-step', 'EQ1', 'STEP2', '2026-03-02T03:00:00Z', None, 'IDLE'),
            ('future', 'EQ1', 'STEP1', '2026-04-02T03:00:00Z', None, 'RUN'),
        ])
        conn.execute('CREATE VIEW approved_events AS SELECT * FROM events')
        conn.commit()
        conn.close()
        self.settings = load_config()
        self.source = dict(id='mes_states', system='Synthetic MES', dialect='sqlite',
                           dsn_env='QAGENT_TEST_DSN', sqlite_file=str(self.db), schema='',
                           view='approved_events', timezone='UTC', synthetic=True,
                           columns=dict(record_id='id', equipment='eqp', step='step', occurred_at='start',
                                        ended_at='end', state='state'))
        self.settings.data['enterprise'].update(enabled=True, sources=[self.source])
        self.context = dict(incident_number='INC1', equipment='EQ1', step='STEP1',
                            **{'from': '2026-03-02T00:00:00Z', 'to': '2026-03-02T23:59:59Z'}, wafers=[])
        self.incidents = {'INC1': {'incident_id': 'i1'}}

    def tool(self):
        validate_values(self.settings.data)
        return EnterpriseTools(self.settings, self.incidents, self.context)

    def query(self):
        return self.tool().query('user', ['i1'], '2026-03-31')

    def test_sql_filters_overlap_and_provenance(self):
        result = self.query()
        system = result['systems'][0]
        self.assertEqual(result['status'], 'OK')
        self.assertEqual([r['state'] for r in system['rows']], ['DOWN', 'PM'])
        self.assertEqual(system['view'], 'approved_events')
        self.assertTrue(system['synthetic'])
        self.assertIn('queried_at', system)
        self.assertNotIn(str(self.db), json.dumps(result))
        self.db.unlink()  # Every connection is closed, including on Windows.

    def test_values_are_bound_not_sql(self):
        self.context['equipment'] = "EQ1' OR 1=1 --"
        tool = self.tool()
        sql, values = tool._statement(self.source, _time(self.context['from']), _time(self.context['to']))
        self.assertNotIn(self.context['equipment'], sql)
        self.assertIn(self.context['equipment'], values)
        self.assertEqual(self.query()['systems'][0]['status'], 'NO_MATCH')

    def test_connection_is_read_only(self):
        conn = self.tool()._connect(self.source)
        try:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute('DELETE FROM events')
        finally:
            conn.close()

    def test_limit_is_reported_not_complete(self):
        self.settings.data['enterprise']['max_rows'] = 1
        result = self.query()
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertTrue(result['systems'][0]['truncated'])
        self.assertEqual(result['systems'][0]['row_count'], 1)

    def test_errors_are_redacted_and_not_demo_fallback(self):
        tool = self.tool()
        with patch.object(tool, '_connect', side_effect=RuntimeError('PWD=secret;host=private')):
            result = tool.query('user', ['i1'], '2026-03-31')
        self.assertEqual(result['status'], 'UNAVAILABLE')
        self.assertEqual(result['systems'][0]['rows'], [])
        self.assertNotIn('secret', json.dumps(result))

    def test_partial_source_failure_preserves_other_source(self):
        self.settings.data['enterprise']['sources'].append({**self.source, 'id': 'broken', 'view': 'missing'})
        result = self.query()
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertEqual([s['status'] for s in result['systems']], ['OK', 'UNAVAILABLE'])

    def test_scope_and_time_limits(self):
        with self.assertRaises(ToolError):
            self.tool().query('user', ['other'], '2026-03-31')
        self.context['to'] = '2026-06-01T00:00:00Z'
        with self.assertRaises(ToolError):
            self.query()
        self.context['to'] = '2026-03-02T23:59:59Z'
        with self.assertRaises(ToolError):
            self.tool().query('user', ['i1'], '2026-02-01')

    def test_bad_identifier_and_missing_mapping_rejected(self):
        self.source['view'] = 'events; DELETE FROM events'
        with self.assertRaises(ConfigError):
            self.tool()
        self.source['view'] = 'approved_events'
        del self.source['columns']['step']
        with self.assertRaises(ConfigError):
            self.tool()

    def test_lot_filter_and_point_time_query(self):
        conn = sqlite3.connect(self.db)
        conn.execute('ALTER TABLE events ADD COLUMN lot TEXT')
        conn.execute("UPDATE events SET lot='LOT1'")
        conn.commit()
        conn.close()
        self.source['columns']['lot_id'] = 'lot'
        del self.source['columns']['ended_at']
        self.context['wafers'] = [{'lot_id': 'LOT1', 'wafer_id': 'W01'}]
        self.assertEqual(self.query()['systems'][0]['row_count'], 1)
        self.context['wafers'][0]['lot_id'] = 'OTHER'
        self.assertEqual(self.query()['systems'][0]['row_count'], 0)

    def test_disabled_does_not_connect(self):
        self.settings.data['enterprise']['enabled'] = False
        tool = self.tool()
        with patch.object(tool, '_connect') as connect:
            self.assertEqual(tool.query('user', ['i1'], '2026-03-31')['status'], 'UNAVAILABLE')
            connect.assert_not_called()

    def test_odbc_parameterization_and_driver_contract(self):
        self.source.update(dialect='sqlserver', schema='dbo', timezone='Asia/Seoul')
        tool = self.tool()
        sql, params = tool._statement(self.source, _time(self.context['from']), _time(self.context['to']))
        self.assertIn('SELECT TOP 41', sql)
        self.assertIn('[dbo].[approved_events]', sql)
        self.assertIsInstance(params[2], datetime)
        self.assertEqual(params[2].hour, 8)
        driver = MagicMock()
        with patch.dict(sys.modules, {'pyodbc': driver}), patch.dict('os.environ', {'QAGENT_TEST_DSN': 'test-dsn'}):
            conn = tool._connect(self.source)
            driver.connect.assert_called_once_with('test-dsn', readonly=True, timeout=30, autocommit=False)
            self.assertEqual(conn.timeout, 30)
            conn.close()

    def test_server_dialects_generate_bounded_select(self):
        for dialect, expected in [('oracle', 'ROWNUM <= 41'), ('postgresql', 'LIMIT 41')]:
            with self.subTest(dialect=dialect):
                source = {**self.source, 'dialect': dialect}
                sql, _ = self.tool()._statement(source, _time(self.context['from']), _time(self.context['to']))
                self.assertTrue(sql.endswith(expected))

    def test_total_result_text_is_bounded(self):
        conn = sqlite3.connect(self.db)
        conn.execute('UPDATE events SET state=?', ('x' * 10000,))
        conn.commit()
        conn.close()
        result = self.query()
        self.assertEqual(result['status'], 'PARTIAL')
        self.assertTrue(result['systems'][0]['text_truncated'])
        self.assertLess(len(json.dumps(result)), 7000)


if __name__ == '__main__':
    unittest.main()
