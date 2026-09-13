"""Behavioral checks independent of generated alias combinations."""
import copy
import json
import sqlite3
import unittest
from pathlib import Path

from check_config import ConfigTests
from config_loader import ConfigError
from generate_dummy import generate
from incident_tools import ToolError, ident
from runtime_factory import open_incident_tools
from terminology import load_dictionary, normalize_request
from variant_query_demo import run_query


class VariantTests(unittest.TestCase):
    setUp = ConfigTests.setUp
    settings = ConfigTests.settings

    def fixture(self, override=None):
        settings = self.settings(override)
        generate(settings)
        return settings

    def dictionary(self):
        return load_dictionary(self.settings())

    def test_reordered_scope_resolves_same_department(self):
        d = self.dictionary()
        for query in ['부서=p기술팀; 도시=평택', '도시=평택; 부서=p기술팀']:
            r = normalize_request(query, d)
            self.assertEqual(r['status'], 'READY')
            self.assertEqual(r['filters'], {'city': '평택', 'department': 'ETCH'})

    def test_canonical_department_does_not_require_alias_context(self):
        self.assertEqual(normalize_request('부서=PHOTO', self.dictionary())['status'], 'READY')

    def test_expired_alias_is_valid_at_historical_time(self):
        d = self.dictionary()
        self.assertEqual(normalize_request('부서=구포토팀', d, effective_at='2024-12-31')['status'], 'READY')
        self.assertEqual(normalize_request('부서=구포토팀', d, effective_at='2025-01-01')['status'], 'NEEDS_CLARIFICATION')

    def test_fuzzy_candidate_does_not_become_a_filter(self):
        r = normalize_request('부서=photox', self.dictionary())
        self.assertEqual(r['status'], 'NEEDS_CLARIFICATION')
        self.assertNotIn('department', r['filters'])
        self.assertIn('PHOTO', [c['canonical'] for c in r['issues'][0]['candidates']])

    def test_unknown_field_and_duplicate_field_do_not_disappear(self):
        d = self.dictionary()
        for q in ['도시=화성; 없는필터=ABC', '도시=화성; 위치=화성']:
            self.assertEqual(normalize_request(q, d)['status'], 'INVALID_REQUEST')

    def test_partial_array_resolution_blocks_entire_request(self):
        r = normalize_request('도시=화성; 세대=D1a,D1x', self.dictionary())
        self.assertEqual(r['status'], 'NEEDS_CLARIFICATION')
        self.assertNotIn('product_generations', r['filters'])

    def test_alias_is_field_specific(self):
        self.assertEqual(normalize_request('부서=노광', self.dictionary())['status'], 'NEEDS_CLARIFICATION')
        self.assertEqual(normalize_request('도시=PHOTO', self.dictionary())['status'], 'NEEDS_CLARIFICATION')

    def test_unknown_request_never_executes_business_tools(self):
        settings = self.settings()  # DB deliberately absent: normalization must stop first.
        r = run_query(settings, '사고번호=SYN-2026-0001; 요청=즉시실행')
        self.assertEqual(r['status'], 'NEEDS_CLARIFICATION')
        self.assertEqual(r['tool_trace'], [])

    def test_synthetic_dictionary_blocked_onprem(self):
        settings = self.settings({'environment': 'onprem'})
        with self.assertRaisesRegex(ValueError, 'SYNTHETIC_DICTIONARY'):
            load_dictionary(settings)

    def test_all_columns_renamed_and_arrays_query_correctly(self):
        settings = self.fixture({'tables': {'incident': {'name': '사고원장', 'columns': {
            'department': '담당조직', 'product_generations': '세대배열', 'title': '발생내용',
            'fab_out_failure_codes': '출하검사불량', 'line_code': '라인코드'}}}})
        r = run_query(settings, '사고번호=SYN-2026-0001; 부서=포토; 세대=디원에이,디원지; 세대조건=모두; 팹아웃=외곽불량; 요청=웨이퍼목록')
        self.assertEqual(r['status'], 'MATCHED')
        self.assertEqual(r['incident_ids'], ['synthetic-pk-0001'])
        self.assertEqual(len(r['wafer_keys']), 80)
        self.assertEqual(r['tool_trace'][0]['tool'], 'find_incidents')

    def test_conflicting_filter_does_not_fall_back_to_identifier_only(self):
        settings = self.fixture()
        for q in ['사고번호=SYN-2026-0001; 부서=에치', '사고번호=SYN-2026-0001; 세대=V8',
                  '사고번호=SYN-2026-0001; 도시=평택', '사고번호=SYN-2026-0001; 라인=66엘']:
            self.assertEqual(run_query(settings, q)['status'], 'NO_MATCH')

    def test_array_modes_have_independent_expected_sets(self):
        settings = self.fixture()
        with open_incident_tools(settings) as t:
            for mode, values, expected in [('any', ['D1a', 'D1z'], ['synthetic-pk-0001', 'synthetic-pk-0002']),
                                          ('all', ['D1a', 'D1z'], ['synthetic-pk-0001']),
                                          ('exact', ['D1a'], ['synthetic-pk-0002']),
                                          ('exact', ['D1a', 'D1a', 'D1z'], ['synthetic-pk-0001'])]:
                r = t.find_incidents('u', filters={'product_generations': {'mode': mode, 'values': values}})
                self.assertEqual([r['incident_id'] for r in r['data']], expected)

    def test_unknown_column_or_bad_operator_rejected(self):
        settings = self.fixture()
        with open_incident_tools(settings) as t:
            for filters in [{'not_a_column': 'x'}, {'department': ['PHOTO']},
                            {'product_generations': {'mode': 'not_any', 'values': ['D1a']}},
                            {'product_generations': {'mode': 'any', 'values': []}}, {}]:
                with self.assertRaises(ToolError):
                    t.find_incidents('u', filters=filters)

    def test_unmapped_filter_is_rejected(self):
        settings = self.fixture({'tables': {'incident': {'columns': {'department': ''}}}})
        r = run_query(settings, '부서=포토')
        self.assertEqual(r['status'], 'TOOL_ERROR')
        self.assertIn('FILTER_COLUMN_UNAVAILABLE', r['error'])

    def test_literal_query_does_not_inject_sql_or_wildcards(self):
        settings = self.fixture()
        with open_incident_tools(settings) as t:
            for raw in ["' OR 1=1 --", '%_', 'PHOTO; DROP TABLE x']:
                self.assertEqual(t.find_incidents('u', filters={'title_terms': [raw]})['status'], 'NO_MATCH')

    def test_month_boundary_compares_instants(self):
        settings = self.fixture()
        with sqlite3.connect(settings.data['database']['sqlite_file']) as db:
            db.execute('UPDATE demo_incident SET occurred_at=? WHERE accident_no=?', ('2026-01-31T15:00:00+00:00', 'SYN-2026-0001'))
        self.assertEqual(run_query(settings, '사고번호=SYN-2026-0001; 기간=2026-01')['status'], 'NO_MATCH')
        self.assertEqual(run_query(settings, '사고번호=SYN-2026-0001; 기간=2026-02')['status'], 'MATCHED')

    def test_malformed_arrays_are_errors_not_empty_matches(self):
        settings = self.fixture()
        for value in ['{bad', '{}', '"D1a"', '[1]', '["D1a",null]']:
            with sqlite3.connect(settings.data['database']['sqlite_file']) as db:
                db.execute('UPDATE demo_incident SET product_generations=? WHERE accident_no=?', (value, 'SYN-2026-0001'))
            r = run_query(settings, '세대=D1a')
            self.assertEqual(r['status'], 'TOOL_ERROR', value)
            self.assertIn('INVALID_SOURCE_ARRAY', r['error'])

    def test_multiple_matches_require_selection_before_lots(self):
        settings = self.fixture()
        r = run_query(settings, '부서=포토; 요청=랏목록')
        self.assertEqual(r['status'], 'NEEDS_SELECTION')
        self.assertEqual([r['tool'] for r in r['tool_trace']], ['find_incidents'])
        chosen = run_query(settings, '부서=포토; 요청=랏목록', selected=['synthetic-pk-0002'])
        self.assertEqual(chosen['status'], 'MATCHED')
        self.assertEqual({row['incident_id'] for p in chosen['lot_pages'] for row in p['items']}, {'synthetic-pk-0002'})

    def test_incident_scope_still_enforced_after_new_search(self):
        settings = self.fixture()
        with open_incident_tools(settings) as t:
            found = t.find_incidents('u', filters={'department': 'PHOTO'})
            with self.assertRaisesRegex(ToolError, 'SELECTION_REQUIRED'):
                t.list_incident_wafers('u', found['scope_id'])
            scope = t.select_incidents('u', found['scope_id'], ['synthetic-pk-0001'])['scope_id']
            with self.assertRaisesRegex(ToolError, 'ACTOR_MISMATCH'):
                t.list_incident_lots('other', scope)

    def test_raw_variants_do_not_modify_canonical_db(self):
        settings = self.fixture()
        before = Path(settings.data['database']['sqlite_file']).read_bytes()
        run_query(settings, '사고번호=SYN-2026-0001; 부셔=phpto; 세대=디원에이; 요청=웨이펴목록')
        self.assertEqual(before, Path(settings.data['database']['sqlite_file']).read_bytes())

    def test_native_array_configuration_is_not_silently_json(self):
        with self.assertRaisesRegex(ConfigError, 'json_text'):
            self.settings({'arrays': {'product_generations': 'native_array'}})


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(VariantTests)
    result = unittest.TextTestRunner(verbosity=1).run(suite)
    print(json.dumps({'variant_behavior_checks': result.testsRun, 'passed': result.wasSuccessful()}))
    raise SystemExit(0 if result.wasSuccessful() else 1)
