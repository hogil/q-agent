"""Execute independent plans with DB access trapped; retain incident gates."""
import copy
import unittest
from unittest.mock import Mock, patch

from plan_executor import execute_plan


class RequestScopeTests(unittest.TestCase):
    def setUp(self):
        self.context = {'request_scope': 'independent', 'budget_remaining': 2,
                        'available_tools': {'read_reference': {'enabled': True, 'stage': 'independent'}}}
        self.output = {'intents': ['document'], 'filters': {}, 'plan': [],
                       'needs_skills': [], 'clarification': None, 'limitations': [],
                       'decision': 'ready_for_judge', 'stage': 'independent', 'search_mode': 'none'}

    def test_provided_context_needs_no_tool_or_database(self):
        with patch('sqlite3.connect', side_effect=AssertionError('DB must not open')):
            self.assertEqual(execute_plan(self.output, self.context, {}), [])

    def test_independent_reference_only_calls_requested_adapter(self):
        self.output.update(decision='execute', plan=[{'tool': 'read_reference', 'arguments': {'key': 'glossary'}, 'depends_on': [], 'reason': 'Read definition'}])
        adapter = Mock(return_value={'evidence_id': 'reference-1', 'text': 'Synthetic definition'})
        incident = Mock(side_effect=AssertionError('Incident adapter must not run'))
        with patch('sqlite3.connect', side_effect=AssertionError('DB must not open')):
            result = execute_plan(self.output, self.context, {'read_reference': adapter, 'find_incidents': incident})
        adapter.assert_called_once_with(key='glossary')
        incident.assert_not_called()
        self.assertEqual(result[0]['result']['evidence_id'], 'reference-1')

    def test_independent_request_rejects_incident_plan_before_dispatch(self):
        self.output.update(stage='incident', search_mode='sql_exact', decision='execute',
                           plan=[{'tool': 'find_incidents', 'arguments': {}, 'depends_on': [], 'reason': 'Unnecessary lookup'}])
        adapter = Mock()
        with self.assertRaisesRegex(ValueError, 'CANNOT_QUERY_INCIDENTS'):
            execute_plan(self.output, self.context, {'find_incidents': adapter})
        adapter.assert_not_called()

    def test_incident_request_cannot_use_independent_stage(self):
        for scope in ('incident', None):
            context = copy.deepcopy(self.context)
            if scope is None:
                context.pop('request_scope')
            else:
                context['request_scope'] = scope
            with self.assertRaisesRegex(ValueError, 'CANNOT_SKIP_LOOKUP'):
                execute_plan(self.output, context, {})

    def test_incident_followup_still_requires_scope(self):
        self.context.update(request_scope='incident', scope_valid=False,
                            available_tools={'list_incident_lots': {'enabled': True, 'stage': 'tools'}})
        self.output.update(stage='tools', decision='execute', plan=[{'tool': 'list_incident_lots', 'arguments': {}, 'depends_on': [], 'reason': 'List lots'}])
        with self.assertRaisesRegex(ValueError, 'INCIDENT_SCOPE_REQUIRED'):
            execute_plan(self.output, self.context, {})

    def test_independent_cannot_relabel_incident_adapter(self):
        self.context['available_tools'] = {'find_incidents': {'enabled': True, 'stage': 'incident'}}
        self.output.update(decision='execute', plan=[{'tool': 'find_incidents', 'arguments': {}, 'depends_on': [], 'reason': 'Lookup'}])
        with self.assertRaisesRegex(ValueError, 'TOOL_STAGE_MISMATCH'):
            execute_plan(self.output, self.context, {'find_incidents': Mock()})

    def test_missing_adapter_rejects_whole_plan_before_first_call(self):
        self.context['available_tools']['missing'] = {'enabled': True, 'stage': 'independent'}
        self.output.update(decision='execute', plan=[{'tool': name, 'arguments': {}, 'depends_on': [], 'reason': 'Read'} for name in ('read_reference', 'missing')])
        adapter = Mock()
        with self.assertRaisesRegex(ValueError, 'TOOL_ADAPTER_UNAVAILABLE'):
            execute_plan(self.output, self.context, {'read_reference': adapter})
        adapter.assert_not_called()

    def test_independent_cannot_keep_incident_filters(self):
        self.output['filters'] = {'incident_number': 'synthetic-id'}
        with self.assertRaisesRegex(ValueError, 'CANNOT_QUERY_INCIDENTS'):
            execute_plan(self.output, self.context, {})


if __name__ == '__main__':
    unittest.main()
