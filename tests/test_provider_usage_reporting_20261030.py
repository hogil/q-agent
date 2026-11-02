"""Synthetic contracts for provider usage reporting coverage."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from agent import provider_usage_field


class ProviderUsageReportingTests(unittest.TestCase):
    def test_complete_and_existing_total_semantics(self):
        reported = [{'input_tokens': 4}, {'input_tokens': 6}]
        result = provider_usage_field(reported, 'input_tokens', 2)
        self.assertEqual(result, {'total': 10, 'reported_calls': 2, 'attempted_calls': 2,
                                  'observed_subtotal': 10, 'coverage': 'complete'})

    def test_partial_reports_known_observations_without_changing_null_total(self):
        result = provider_usage_field([{'input_tokens': 4}, {}], 'input_tokens', 2)
        self.assertEqual(result, {'total': None, 'reported_calls': 1, 'attempted_calls': 2,
                                  'observed_subtotal': 4, 'coverage': 'partial'})

    def test_unavailable_usage_has_no_subtotal(self):
        result = provider_usage_field([{}], 'input_tokens', 1)
        self.assertEqual(result, {'total': None, 'reported_calls': 0, 'attempted_calls': 1,
                                  'observed_subtotal': None, 'coverage': 'unavailable'})

    def test_zero_calls_reports_zero_without_inventing_total_for_other_fields(self):
        result = provider_usage_field([], 'input_tokens', 0)
        self.assertEqual(result, {'total': 0, 'reported_calls': 0, 'attempted_calls': 0,
                                  'observed_subtotal': 0, 'coverage': 'no_calls'})

    def test_zero_token_usage_is_valid(self):
        result = provider_usage_field([{'input_tokens': 0}], 'input_tokens', 1)
        self.assertEqual(result['total'], 0)
        self.assertEqual(result['observed_subtotal'], 0)
        self.assertEqual(result['coverage'], 'complete')

    def test_bool_negative_and_float_are_not_valid_reports(self):
        reported = [{'input_tokens': True}, {'input_tokens': -2}, {'input_tokens': 3.0}]
        result = provider_usage_field(reported, 'input_tokens', 3)
        self.assertEqual(result, {'total': None, 'reported_calls': 0, 'attempted_calls': 3,
                                  'observed_subtotal': None, 'coverage': 'unavailable'})


if __name__ == '__main__':
    unittest.main()
