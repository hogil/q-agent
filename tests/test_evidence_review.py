import json
import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'app'))
from evidence_review import review_evidence, validate_snapshot_scope
from incident_tools import ToolError
from mes_reference_contract import validate_mes_reference_response


class EvidenceReviewTests(unittest.TestCase):
    def _document_entry(self, truncated='missing', candidate_count='missing', status='OK'):
        item = {'document_id': 'd1', 'chunk_id': 'c1', 'version': 'v1', 'source_ref': 'synthetic',
                'locator': 'section 1', 'relation': 'direct', 'applicability_status': 'unverified'}
        result = {'source_kind': 'internal_documents', 'status': status,
                  'items': [item] if status == 'OK' else []}
        if truncated != 'missing':
            result['source_reported_truncated'] = truncated
        if candidate_count != 'missing':
            result['source_reported_candidate_count'] = candidate_count
        if truncated != 'missing' and candidate_count != 'missing':
            result['retrieval_completeness'] = (
                'source_reported_truncated' if truncated is True
                else 'source_reported_not_truncated' if truncated is False else 'unknown')
            result['candidate_count_basis'] = 'source_reported_unverified'
        return {'id': 'doc1', 'source': 'search_internal_documents', 'result': result}

    def test_document_source_truncation_is_preserved_without_claiming_exhaustiveness(self):
        for truncated, expected in ((True, 'DOCUMENT_RESULTS_SOURCE_REPORTED_TRUNCATED'),
                                    (False, None), (None, 'DOCUMENT_RETRIEVAL_COMPLETENESS_UNKNOWN')):
            with self.subTest(truncated=truncated):
                entry = self._document_entry(truncated, 3)
                report = review_evidence([entry], '2026-03-31', 'Asia/Seoul')
                self.assertEqual(entry['review_metadata']['document_retrieval']['source_reported_truncated'],
                                 truncated)
                self.assertIsNone(entry['result']['items'][0].get('observed_at'))
                self.assertIsNone(entry['result']['items'][0].get('available_at'))
                self.assertEqual(expected in report['limitations'], expected is not None)
                self.assertNotIn('DOCUMENT_CORPUS_EXHAUSTIVE', report['limitations'])

    def test_document_legacy_missing_metadata_is_unknown_and_no_match_is_valid(self):
        entry = self._document_entry()
        original = json.loads(json.dumps(entry['result']))
        report = review_evidence([entry], '2026-03-31', 'Asia/Seoul')
        self.assertEqual(entry['review_metadata']['document_retrieval']['retrieval_completeness'], 'unknown')
        self.assertIn('DOCUMENT_RETRIEVAL_COMPLETENESS_UNKNOWN', report['limitations'])
        self.assertEqual(entry['result'], original)
        no_match = self._document_entry(None, 0, 'NO_MATCH')
        reviewed = review_evidence([no_match], '2026-03-31', 'Asia/Seoul')
        self.assertEqual(reviewed['records'], [])
        self.assertIn('DOCUMENT_RETRIEVAL_COMPLETENESS_UNKNOWN', reviewed['limitations'])

    def test_document_retrieval_metadata_malformed_or_inconsistent_fails_closed(self):
        cases = [(1, 2), (False, True), (True, -1)]
        for truncated, count in cases:
            with self.subTest(truncated=truncated, count=count):
                entry = self._document_entry(truncated, count)
                with self.assertRaises(ValueError):
                    review_evidence([entry], '2026-03-31', 'Asia/Seoul')
        entry = self._document_entry(True, 2)
        entry['result']['retrieval_completeness'] = 'source_reported_not_truncated'
        with self.assertRaisesRegex(ValueError, 'inconsistent'):
            review_evidence([entry], '2026-03-31', 'Asia/Seoul')

    def _mes_entry(self, items, as_of='2026-03-31'):
        return {'id': 'mes1', 'source': 'search_mes_reference', 'result': {
            'status': 'OK', 'as_of': as_of, 'incident_ids': ['I1'],
            'items': items, 'truncated': False, 'candidate_count': len(items)}}

    def _mes_item(self, record_id, scope_relation, incident_ids, available_at='2026-03-30'):
        return {'kind': 'recipe', 'record_id': record_id, 'version': 'v1', 'source_ref': 'synthetic',
                'time_status': 'unknown', 'applicability': 'unknown', 'scope_relation': scope_relation,
                'incident_ids': incident_ids, 'available_at': available_at,
                'effective_from': None, 'effective_to': None}

    def test_mes_current_and_catalog_candidate_relations_are_preserved(self):
        items = [self._mes_item('current', 'current_scope', ['I1']),
                 self._mes_item('catalog', 'catalog_candidate', [])]
        report = review_evidence([self._mes_entry(items)], '2026-03-31', 'Asia/Seoul')
        reviewed = {row['record_id']: row for row in report['records']}
        self.assertEqual(reviewed['current']['incident_ids'], ['I1'])
        self.assertEqual(reviewed['catalog']['incident_ids'], [])
        self.assertEqual(reviewed['catalog']['applicability'], 'unknown')

    def test_mes_scope_relation_rejects_contradictory_incident_ids(self):
        for relation, ids in (('catalog_candidate', ['I1']), ('current_scope', [])):
            with self.subTest(relation=relation, ids=ids):
                item = self._mes_item('bad', relation, ids)
                with self.assertRaisesRegex(ValueError, 'incident_ids do not match'):
                    review_evidence([self._mes_entry([item])], '2026-03-31', 'Asia/Seoul')

    def test_mes_available_at_is_required_timezone_aware_and_before_cutoff(self):
        for value in (None, '2026-03-30T12:00:00', 'not-a-date', '2026-04-01'):
            with self.subTest(available_at=value):
                item = self._mes_item('bad-date', 'current_scope', ['I1'], value)
                expected = 'required' if value is None else (
                    'timezone' if value == '2026-03-30T12:00:00' else
                    'AFTER_CUTOFF' if value == '2026-04-01' else 'malformed')
                with self.assertRaisesRegex(ValueError, expected):
                    review_evidence([self._mes_entry([item])], '2026-03-31', 'Asia/Seoul')
        item = self._mes_item('missing-date', 'current_scope', ['I1'])
        del item['available_at']
        with self.assertRaisesRegex(ValueError, 'available_at is required'):
            review_evidence([self._mes_entry([item])], '2026-03-31', 'Asia/Seoul')

    def test_mes_available_at_uses_adapter_date_formats_and_exclusive_cutoff(self):
        for value in ('20260330', '2026-03-30', '2026-03-31T14:59:59Z'):
            with self.subTest(available_at=value):
                item = self._mes_item('valid-date', 'current_scope', ['I1'], value)
                report = review_evidence([self._mes_entry([item])], '2026-03-31', 'Asia/Seoul')
                self.assertEqual(len(report['records']), 1)
        for value in ('20260401', '2026-03-31T15:00:00Z'):
            with self.subTest(available_at=value):
                item = self._mes_item('future-date', 'current_scope', ['I1'], value)
                with self.assertRaisesRegex(ValueError, 'MES_REFERENCE_AFTER_CUTOFF'):
                    review_evidence([self._mes_entry([item])], '2026-03-31', 'Asia/Seoul')

    def test_mes_no_match_rejects_nonzero_candidate_count(self):
        entry = self._mes_entry([])
        entry['result'].update(status='NO_MATCH', candidate_count=1, truncated=True)
        with self.assertRaisesRegex(ValueError, 'candidate_count does not match'):
            review_evidence([entry], '2026-03-31', 'Asia/Seoul')

    def test_mes_effective_dates_share_adapter_parser_and_keep_open_bounds(self):
        item = self._mes_item('effective', 'current_scope', ['I1'])
        item.update(effective_from='20260301', effective_to='2026-04-01', time_status='active')
        report = review_evidence([self._mes_entry([item])], '2026-03-31', 'Asia/Seoul')
        self.assertEqual(report['records'][0]['effective_from'], '20260301')
        self.assertEqual(report['records'][0]['effective_to'], '2026-04-01')
        item.update(effective_from=None, effective_to='20260401', time_status='active')
        report = review_evidence([self._mes_entry([item])], '2026-03-31', 'Asia/Seoul')
        self.assertIsNone(report['records'][0]['effective_from'])
        self.assertEqual(report['records'][0]['effective_to'], '20260401')

    def test_mes_effective_dates_reject_malformed_naive_and_reversed_ranges(self):
        for start, end in (('not-a-date', None), ('2026-03-01T00:00:00', None),
                           ('2026-04-01', '2026-03-01')):
            with self.subTest(start=start, end=end):
                item = self._mes_item('bad-effective', 'current_scope', ['I1'])
                item.update(effective_from=start, effective_to=end)
                with self.assertRaisesRegex(ValueError, 'effective|timezone|interval'):
                    review_evidence([self._mes_entry([item])], '2026-03-31', 'Asia/Seoul')

    def test_mes_effective_interval_uses_instants_across_dst_fold(self):
        item = self._mes_item('dst-effective', 'current_scope', ['I1'])
        item.update(effective_from='2026-10-25T02:45:00+02:00',
                    effective_to='2026-10-25T02:15:00+01:00', time_status='expired')
        report = review_evidence([self._mes_entry([item], '2026-10-25')], '2026-10-25', 'Europe/Berlin')
        self.assertEqual(len(report['records']), 1)
        item.update(effective_from='2026-10-25T02:15:00+01:00',
                    effective_to='2026-10-25T02:45:00+02:00')
        with self.assertRaisesRegex(ValueError, 'effective interval'):
            review_evidence([self._mes_entry([item], '2026-10-25')], '2026-10-25', 'Europe/Berlin')

    def test_mes_time_status_must_match_effective_bounds(self):
        cases = ((None, None, 'active'), ('2026-04-01', None, 'active'),
                 (None, '2026-04-01', 'expired'), (None, '2026-03-31', 'active'))
        for start, end, wrong_status in cases:
            with self.subTest(start=start, end=end, wrong_status=wrong_status):
                item = self._mes_item('wrong-time-status', 'current_scope', ['I1'])
                item.update(effective_from=start, effective_to=end, time_status=wrong_status)
                with self.assertRaisesRegex(ValueError, 'time_status does not match'):
                    review_evidence([self._mes_entry([item])], '2026-03-31', 'Asia/Seoul')

    def test_mes_reviewer_accepts_adapter_projected_time_status(self):
        raw = {'status': 'OK', 'as_of': '2026-03-31', 'incident_ids': ['I1'],
               'truncated': False, 'candidate_count': 1,
               'items': [{'kind': 'recipe', 'record_id': 'valid', 'version': 'v1',
                          'name': 'Synthetic recipe', 'source_ref': 'synthetic',
                          'available_at': '20260330', 'effective_from': '20260331',
                          'effective_to': '20260401', 'applicability': 'unknown',
                          'scope_relation': 'current_scope', 'incident_ids': ['I1']}]}
        projected = validate_mes_reference_response(
            raw, incident_ids=['I1'], as_of='2026-03-31', timezone_name='Asia/Seoul',
            allowed_kinds={'recipe'}, top_k=5)
        entry = {'id': 'mes1', 'source': 'search_mes_reference', 'result': projected}
        report = review_evidence([entry], '2026-03-31', 'Asia/Seoul')
        self.assertEqual(report['records'][0]['time_status'], 'active')

    def test_same_document_chunks_are_one_source_group(self):
        rows = [{'meeting_id': 'm1', 'version': 'v1', 'chunk_id': chunk, 'meeting_date': '2026-03-01'}
                for chunk in ('c1', 'c2')]
        report = review_evidence([{'id': 'e1', 'source': 'search_meeting_minutes', 'result': {'items': rows}},
                                 {'id': 'e2', 'source': 'search_meeting_minutes', 'result': {'items': rows}}],
                                '2026-03-31', 'Asia/Seoul')
        self.assertEqual(len(report['source_groups']), 1)
        self.assertEqual(report['source_groups'][0]['evidence_ids'], ['e1', 'e2'])
        self.assertEqual(report['duplicate_records'], 2)
        self.assertTrue(all(row['availability'] == 'unknown' for row in report['records']))

    def test_publication_time_and_local_cutoff_are_checked(self):
        rows = [{'meeting_id': 'm1', 'version': 'v1', 'chunk_id': 'c1', 'meeting_date': '2026-03-01',
                 'available_at': '2026-04-01T00:00:00+09:00'},
                {'meeting_id': 'm2', 'version': 'v1', 'chunk_id': 'c2', 'meeting_date': '2026-04-02'}]
        report = review_evidence([{'id': 'e1', 'source': 'search_meeting_minutes', 'result': {'items': rows}}],
                                 '2026-03-31', 'Asia/Seoul')
        self.assertEqual({row['field'] for row in report['issues']}, {'observed_at', 'available_at'})

    def test_generic_timestamp_invalid_missing_and_future_semantics(self):
        invalid_values = ('', 'not-a-date', 123)
        rows = []
        for index, value in enumerate(invalid_values):
            rows.append({'meeting_id': f'm{index}', 'version': 'v1', 'chunk_id': f'c{index}',
                         'meeting_date': value, 'available_at': value})
        rows.extend([
            {'meeting_id': 'missing', 'version': 'v1', 'chunk_id': 'missing'},
            {'meeting_id': 'future', 'version': 'v1', 'chunk_id': 'future',
             'meeting_date': '2026-04-01', 'available_at': '2026-04-01T00:00:00+09:00'},
            {'meeting_id': 'offset-valid', 'version': 'v1', 'chunk_id': 'offset-valid',
             'meeting_date': '2026-03-31T23:59:59-07:00',
             'available_at': '2026-03-31T14:59:59Z'},
        ])
        original = json.loads(json.dumps(rows))
        entry = {'id': 'meetings', 'source': 'search_meeting_minutes', 'result': {'items': rows}}
        report = review_evidence([entry], '2026-03-31', 'Asia/Seoul')

        invalid = [issue for issue in report['issues'] if issue['type'] == 'invalid_timestamp']
        self.assertEqual({(issue['record_id'], issue['field']) for issue in invalid},
                         {(f'c{i}', field) for i in range(3) for field in ('observed_at', 'available_at')})
        future = [issue for issue in report['issues'] if issue['type'] == 'after_cutoff']
        self.assertEqual({(issue['record_id'], issue['field']) for issue in future},
                         {('future', 'observed_at'), ('future', 'available_at'),
                          ('offset-valid', 'observed_at')})
        records = {record['record_id']: record for record in report['records']}
        self.assertEqual(records['missing']['availability'], 'unknown')
        self.assertEqual([records[f'c{i}']['availability'] for i in range(3)], ['invalid'] * 3)
        self.assertNotIn('availability', records['offset-valid'])
        self.assertEqual(rows, original)

    def test_generic_timestamp_invalid_reporting_across_sources_and_both_fields(self):
        entries = [
            {'id': 'platform', 'source': 'get_platform_evidence', 'result': {'sections': {
                'fab': {'rows': [{'record_id': 'p1', 'timestamp': 'broken', 'available_at': []}]}}}},
            {'id': 'history', 'source': 'search_platform_history', 'result': {'items': [
                {'incident_id': 'h1', 'occurred_at': '2026-02-30', 'available_at': ''}] }},
            {'id': 'assets', 'source': 'list_comparison_assets', 'result': {'assets': [
                {'asset_id': 'a1', 'acquired_at': '2026-03-01T00:00:00Z', 'available_at': object()}]}},
        ]
        report = review_evidence(entries, '2026-03-31', 'Asia/Seoul')
        self.assertEqual({(issue['evidence_id'], issue['record_id'], issue['field'])
                          for issue in report['issues'] if issue['type'] == 'invalid_timestamp'},
                         {('platform', 'p1', 'observed_at'), ('platform', 'p1', 'available_at'),
                          ('history', 'h1', 'observed_at'), ('history', 'h1', 'available_at'),
                          ('assets', 'a1', 'available_at')})
        records = {record['record_id']: record for record in report['records']}
        self.assertEqual(records['p1']['availability'], 'invalid')
        self.assertEqual(records['h1']['availability'], 'invalid')
        self.assertEqual(records['a1']['availability'], 'invalid')

    def test_same_wafer_is_not_verified_image_map_alignment(self):
        image = {'asset_id': 'sem1', 'revision': 'v1', 'lot_id': 'L1', 'wafer_id': 'W1',
                 'step': 'S1', 'item': 'CD', 'modality': 'sem', 'acquired_at': '2026-03-01T00:00:00Z'}
        metrology = {'id': 'map1', 'sha256': 'digest', 'lot_id': 'L1', 'wafer_id': 'W1',
                     'step': 'S1', 'item': 'CD', 'timestamp': '2026-03-01T01:00:00Z'}
        entries = [{'id': 'e1', 'source': 'list_comparison_assets', 'result': {'assets': [image]}},
                   {'id': 'e2', 'source': 'get_engineering_snapshot', 'result': {'sections': {'maps': {'assets': [metrology]}}}}]
        report = review_evidence(entries, '2026-03-31', 'Asia/Seoul')
        pair = report['correspondence'][0]
        self.assertTrue(pair['same_wafer'])
        self.assertFalse(pair['physical_alignment_verified'])
        self.assertEqual(pair['status'], 'unverified')
        self.assertEqual(set(pair['missing']), {'coordinate_system', 'site'})
        self.assertEqual(pair['time_relation'], 'not_same_timestamp')
        metrology['step'] = 'S2'
        report = review_evidence(entries, '2026-03-31', 'Asia/Seoul')
        self.assertEqual(report['correspondence'][0]['conflicts'], ['step'])
        metrology['wafer_id'] = 'W2'
        self.assertEqual(review_evidence(entries, '2026-03-31', 'Asia/Seoul')['correspondence'], [])

    def test_wrong_scope_wafer_and_future_map_are_rejected(self):
        result = {'scope': {'incident_ids': ['I1'], 'step': 'S1', 'wafers': [{'lot_id': 'L1', 'wafer_id': 'W1'}]},
                  'sections': {'maps': {'assets': [{'id': 'map1', 'lot_id': 'L1', 'wafer_id': 'W2',
                                                   'step': 'S1', 'timestamp': '2026-03-01T00:00:00Z'}]}}}
        with self.assertRaisesRegex(ToolError, 'SCOPE_MISMATCH'):
            validate_snapshot_scope(result, ['I2'], '2026-03-31', 'Asia/Seoul')
        with self.assertRaisesRegex(ToolError, 'WAFER_MISMATCH'):
            validate_snapshot_scope(result, ['I1'], '2026-03-31', 'Asia/Seoul')
        result['sections']['maps']['assets'][0].update(wafer_id='W1', timestamp='2026-04-01T00:00:00Z')
        with self.assertRaisesRegex(ToolError, 'AFTER_CUTOFF'):
            validate_snapshot_scope(result, ['I1'], '2026-03-31', 'Asia/Seoul')
        result['scope']['as_of'] = '2026-04-01'
        with self.assertRaisesRegex(ToolError, 'CUTOFF_MISMATCH'):
            validate_snapshot_scope(result, ['I1'], '2026-03-31', 'Asia/Seoul')

    def test_unscoped_maps_and_empty_wafer_scope_are_rejected(self):
        result = {'sections': {'maps': {'assets': [{'lot_id': 'L1', 'wafer_id': 'W1'}]}}}
        with self.assertRaisesRegex(ToolError, 'SCOPE_MISMATCH'):
            validate_snapshot_scope(result, ['I1'], '2026-03-31', 'Asia/Seoul')
        result['scope'] = {'incident_ids': ['I1'], 'wafers': []}
        with self.assertRaisesRegex(ToolError, 'WAFER_MISMATCH'):
            validate_snapshot_scope(result, ['I1'], '2026-03-31', 'Asia/Seoul')

    def test_local_timestamp_and_distinct_image_modalities(self):
        rows = [{'asset_id': 'a1', 'revision': 'v1', 'modality': modality,
                 'acquired_at': '2026-04-01T00:00:00'} for modality in ('sem', 'overlay')]
        report = review_evidence([{'id': 'e1', 'source': 'list_comparison_assets',
                                  'result': {'assets': rows}}], '2026-03-31', 'Asia/Seoul')
        self.assertEqual(len(report['source_groups']), 2)
        self.assertEqual(len(report['issues']), 2)
