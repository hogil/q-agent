import unittest
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
import sys
import tempfile
from contextlib import closing, contextmanager

from app.action_scope_bridge import ActionScopeBridgeError, build_scoped_action_input

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))
from config_loader import DEFAULT_CONFIG, Settings, load_config
from demo_data import generate
from runtime_factory import open_incident_tools


COMPLETE = [{'incident_id': 'inc-1', 'expected_lots': 2, 'returned_total_lots': 2,
             'state': 'complete_by_declared_source_and_count'}]
WAFER_COMPLETE = [{'incident_id': 'inc-1', 'expected_wafers': 2, 'returned_total_wafers': 2,
                   'state': 'complete_by_declared_source_and_count'}]


class SyntheticIncidentTools:
    def __init__(self, *, incident_ids=('inc-1',), wafer_scope='incident_affected', lot_status='OK',
                 wafer_status='OK', lot_items=None, wafer_items=None, omit_page=False):
        self.scope_id = 'selected-scope'
        self.scope = {'ids': incident_ids, 'requires_selection': False, 'summary_only': False}
        self.lot_coverage = [{'incident_id': incident_id, 'expected_lots': 1,
                              'returned_total_lots': 1,
                              'state': 'complete_by_declared_source_and_count'}
                             for incident_id in incident_ids]
        self.wafer_coverage = [{'incident_id': incident_id, 'expected_wafers': 1,
                                'returned_total_wafers': 1,
                                'state': 'complete_by_declared_source_and_count'}
                               for incident_id in incident_ids]
        self.lot_status, self.wafer_status = lot_status, wafer_status
        self.lot_items = lot_items or [
            {'incident_id': 'inc-1', 'lot_id': 'lot-a'},
            {'incident_id': 'inc-1', 'lot_id': 'lot-b'},
        ]
        self.wafer_items = wafer_items or [
            {'incident_id': 'inc-1', 'lot_id': 'lot-a', 'wafer_id': 'wafer-1'},
            {'incident_id': 'inc-1', 'lot_id': 'lot-b', 'wafer_id': 'wafer-2'},
        ]
        self.wafer_scope, self.omit_wafer_page = wafer_scope, omit_page

    def _scope(self, actor, scope_id):
        if scope_id != self.scope_id:
            raise ValueError('unknown scope')
        return self.scope

    def _page(self, items, kind, page_size, offset):
        sliced = items[offset:offset + page_size]
        nxt = offset + len(sliced)
        result = {'status': self.lot_status if kind == 'lot' else self.wafer_status,
                  'scope_id': self.scope_id, 'items': sliced,
                  'total_memberships': len(items), 'offset': offset,
                  'next_offset': nxt if nxt < len(items) else None,
                  'source_completeness': 'declared_complete',
                  'mapping_version': 'synthetic-fixture-v1'}
        if kind == 'lot':
            result['coverage'] = self.lot_coverage
        else:
            result.update({'wafer_scope': self.wafer_scope, 'coverage': self.wafer_coverage,
                           'lot_coverage': self.lot_coverage})
        if kind == 'wafer' and self.omit_wafer_page and offset:
            result['items'] = []
        return result

    def list_incident_lots(self, actor, scope_id, *, page_size, offset):
        return self._page(self.lot_items, 'lot', page_size, offset)

    def list_incident_wafers(self, actor, scope_id, *, page_size, offset):
        return self._page(self.wafer_items, 'wafer', page_size, offset)


class SyntheticLease:
    atomic_snapshot = True
    snapshot_token = 'test-lease-token-1'
    revision = 'demo-db-snapshot-17'
    as_of = '2026-10-29T00:00:00Z'

    def __init__(self, tools, *, transaction=False, mismatch_after_first_wafer_page=False,
                 mutate_membership_after_first_wafer_page=False, as_of=None, revision=None,
                 atomic_snapshot=True):
        self.tools = tools
        self.transaction = transaction
        self.atomic_snapshot = atomic_snapshot
        self.mismatch_after_first_wafer_page = mismatch_after_first_wafer_page
        self.mutate_membership_after_first_wafer_page = mutate_membership_after_first_wafer_page
        if as_of is not None:
            self.as_of = as_of
        if revision is not None:
            self.revision = revision
        self.wafer_calls = 0

    def __enter__(self):
        if self.transaction:
            self.tools.db.execute('BEGIN')
        return self

    def __exit__(self, *_):
        if self.transaction and self.tools.db.in_transaction:
            self.tools.db.rollback()

    def _bind(self, page, *, wafer=False):
        if wafer:
            self.wafer_calls += 1
            if self.mismatch_after_first_wafer_page and self.wafer_calls > 1:
                page['_snapshot_revision'] = 'different-revision'
            if self.mutate_membership_after_first_wafer_page and self.wafer_calls > 1:
                page['items'][0]['wafer_id'] = 'changed-between-pages'
        page['_snapshot_token'] = self.snapshot_token
        page['_snapshot_revision'] = page.get('_snapshot_revision', self.revision)
        page['_snapshot_as_of'] = self.as_of
        return page

    def list_incident_lots(self, actor, scope_id, **kwargs):
        return self._bind(self.tools.list_incident_lots(actor, scope_id, **kwargs))

    def list_incident_wafers(self, actor, scope_id, **kwargs):
        return self._bind(self.tools.list_incident_wafers(actor, scope_id, **kwargs), wafer=True)

    def validate(self):
        return ((not self.transaction or self.tools.db.in_transaction) and
                not (self.mutate_membership_after_first_wafer_page and self.wafer_calls > 1))


def lease_provider(*, transaction=False, **kwargs):
    @contextmanager
    def provide(tools, actor, scope_id):
        with SyntheticLease(tools, transaction=transaction, **kwargs) as lease:
            yield lease
    return provide


class ActionScopeBridgeTests(unittest.TestCase):
    def test_builds_exact_pair_scope_and_keeps_snapshot_revision_separate(self):
        result = build_scoped_action_input(SyntheticIncidentTools(), 'tester', 'selected-scope',
                                           snapshot_lease_provider=lease_provider(), page_size=1)
        self.assertEqual(result['scope'], (('wafer-1', 'lot-a'), ('wafer-2', 'lot-b')))
        self.assertEqual(result['as_of'], datetime(2026, 10, 29, tzinfo=timezone.utc))
        self.assertEqual(result['revision'], 'demo-db-snapshot-17')
        self.assertNotEqual(result['revision'], 'selected-scope')
        self.assertTrue(result['synthetic_only'])
        self.assertTrue(result['snapshot_provider_attested'])
        self.assertTrue(result['synthetic_planner_input_eligible'])
        self.assertFalse(result['execution_granted'])

    def test_rejects_partial_source_and_non_affected_wafer_scope(self):
        with self.assertRaisesRegex(ActionScopeBridgeError, 'LOT_INCOMPLETE'):
            build_scoped_action_input(SyntheticIncidentTools(lot_status='PARTIAL'), 'tester',
                                      'selected-scope', snapshot_lease_provider=lease_provider())
        with self.assertRaisesRegex(ActionScopeBridgeError, 'WAFER_SCOPE_IS_NOT_INCIDENT_AFFECTED'):
            build_scoped_action_input(SyntheticIncidentTools(wafer_scope='lot_inventory'), 'tester',
                                      'selected-scope', snapshot_lease_provider=lease_provider())

    def test_rejects_missing_pages_and_out_of_scope_lots(self):
        with self.assertRaisesRegex(ActionScopeBridgeError, 'WAFER_MISSING_PAGE'):
            build_scoped_action_input(SyntheticIncidentTools(omit_page=True), 'tester',
                                      'selected-scope', snapshot_lease_provider=lease_provider(), page_size=1)
        tools = SyntheticIncidentTools(wafer_items=[
            {'incident_id': 'inc-1', 'lot_id': 'lot-outside', 'wafer_id': 'wafer-1'}])
        with self.assertRaisesRegex(ActionScopeBridgeError, 'WAFER_LOT_OUTSIDE_INCIDENT_SCOPE'):
            build_scoped_action_input(tools, 'tester', 'selected-scope', snapshot_lease_provider=lease_provider())

    def test_rejects_empty_scope_bad_as_of_and_scope_id_as_revision(self):
        tools = SyntheticIncidentTools()
        tools.scope['ids'] = ()
        with self.assertRaisesRegex(ActionScopeBridgeError, 'SELECTED_INCIDENT_SCOPE_REQUIRED'):
            build_scoped_action_input(tools, 'tester', 'selected-scope', snapshot_lease_provider=lease_provider())
        with self.assertRaisesRegex(ActionScopeBridgeError, 'INVALID_SNAPSHOT_AS_OF'):
            build_scoped_action_input(SyntheticIncidentTools(), 'tester', 'selected-scope',
                                      snapshot_lease_provider=lease_provider(
                                          as_of='2026-10-29T09:00:00+09:00'))
        with self.assertRaisesRegex(ActionScopeBridgeError, 'MUST_NOT_BE_SCOPE_ID'):
            build_scoped_action_input(SyntheticIncidentTools(), 'tester', 'selected-scope',
                                      snapshot_lease_provider=lease_provider(revision='selected-scope'))

    def _settings(self, root, *, declare_complete):
        data = load_config(DEFAULT_CONFIG, DEFAULT_CONFIG.parent / 'demo.yaml').data
        data['paths'].update(data_root=str(root), golden_file=str(Path(root) / 'golden.jsonl'))
        data['database']['sqlite_file'] = str(Path(root) / 'incidents.sqlite')
        data['meetings']['sqlite_file'] = str(Path(root) / 'meetings.sqlite')
        if declare_complete:
            data['relations']['source_completeness'] = 'declared_complete'
            data['relations']['wafer_source_completeness'] = 'declared_complete'
        return Settings(data, ())

    def test_actual_incident_tools_complete_synthetic_sqlite_and_unknown_default_fail_closed(self):
        with tempfile.TemporaryDirectory() as root:
            settings = self._settings(root, declare_complete=True)
            generate(settings, profile='basic', include_goldens=False)
            # This fixture has 8 registered wafers for SYN-2026-01; align its
            # synthetic expected count without changing any checked-in source.
            incident = settings.data['tables']['incident']
            with closing(sqlite3.connect(settings.data['database']['sqlite_file'])) as con:
                con.execute(f"UPDATE {incident['name']} SET {incident['columns']['affected_wafer_count']}=8 "
                            f"WHERE {incident['columns']['incident_number']}='SYN-2026-01'")
                con.commit()
            with open_incident_tools(settings) as tools:
                lookup = tools.find_incidents('bridge-fixture', incident_number='SYN-2026-01')
                result = build_scoped_action_input(
                    tools, 'bridge-fixture', lookup['scope_id'],
                    snapshot_lease_provider=lease_provider(transaction=True),
                    page_size=2)
                self.assertEqual(len(result['scope']), 8)
                self.assertEqual({lot for _, lot in result['scope']}, {
                    'SYN-LOT-01-01', 'SYN-LOT-01-02', 'SYN-LOT-01-03'})

        with tempfile.TemporaryDirectory() as root:
            settings = self._settings(root, declare_complete=False)
            generate(settings, profile='basic', include_goldens=False)
            with open_incident_tools(settings) as tools:
                lookup = tools.find_incidents('bridge-default', incident_number='SYN-2026-01')
                with self.assertRaisesRegex(ActionScopeBridgeError, 'LOT_INCOMPLETE'):
                    build_scoped_action_input(
                        tools, 'bridge-default', lookup['scope_id'],
                        snapshot_lease_provider=lease_provider(transaction=True))

    def test_actual_shared_lot_across_selected_incidents_is_retained_once(self):
        with tempfile.TemporaryDirectory() as root:
            settings = self._settings(root, declare_complete=True)
            generate(settings, profile='hard', include_goldens=False)
            incident = settings.data['tables']['incident']
            wafers = settings.data['tables']['wafer_list']
            lot_table = settings.data['tables']['lot_list']
            numbers = ('H-2026-005', 'H-2026-006')
            selected_incident_ids = []
            with closing(sqlite3.connect(settings.data['database']['sqlite_file'])) as con:
                for number in numbers:
                    incident_id = con.execute(
                        f"SELECT {incident['columns']['incident_id']} FROM {incident['name']} "
                        f"WHERE {incident['columns']['incident_number']}=?", (number,)).fetchone()[0]
                    selected_incident_ids.append(incident_id)
                    actual = con.execute(
                        f"SELECT COUNT(*) FROM {wafers['name']} WHERE "
                        f"{wafers['columns']['incident_ref']}=?", (incident_id,)).fetchone()[0]
                    con.execute(f"UPDATE {incident['name']} SET {incident['columns']['affected_wafer_count']}=? "
                                f"WHERE {incident['columns']['incident_id']}=?", (actual, incident_id))
                con.commit()
                shared_memberships = con.execute(
                    f"SELECT COUNT(DISTINCT {lot_table['columns']['incident_ref']}) "
                    f"FROM {lot_table['name']} WHERE {lot_table['columns']['lot_id']}='H-LOT-01-02' "
                    f"AND {lot_table['columns']['incident_ref']} IN (?,?)",
                    selected_incident_ids).fetchone()[0]
                title = con.execute(
                    f"SELECT {incident['columns']['title']} FROM {incident['name']} "
                    f"WHERE {incident['columns']['incident_number']}=?", (numbers[0],)).fetchone()[0]
            with open_incident_tools(settings) as tools:
                candidates = tools.find_incidents('shared-lot-fixture', title=title)
                selected = tools.select_incidents(
                    'shared-lot-fixture', candidates['scope_id'],
                    ['synthetic-hard-pk-2026-005', 'synthetic-hard-pk-2026-006'])
                result = build_scoped_action_input(
                    tools, 'shared-lot-fixture', selected['scope_id'],
                    snapshot_lease_provider=lease_provider(transaction=True), page_size=2)
            shared = [pair for pair in result['scope'] if pair[1] == 'H-LOT-01-02']
            self.assertEqual(shared_memberships, 2)
            self.assertEqual(len(shared), 3)
            self.assertEqual(len(result['scope']), len(set(result['scope'])))

    def test_rejects_revision_change_across_pages(self):
        tools = SyntheticIncidentTools()
        with self.assertRaisesRegex(ActionScopeBridgeError, 'WAFER_SNAPSHOT_BINDING_MISMATCH'):
            build_scoped_action_input(tools, 'tester', 'selected-scope',
                                      snapshot_lease_provider=lease_provider(
                                          mismatch_after_first_wafer_page=True), page_size=1)

    def test_rejects_lot_linked_only_to_another_selected_incident(self):
        tools = SyntheticIncidentTools(
            incident_ids=('inc-1', 'inc-2'),
            lot_items=[{'incident_id': 'inc-1', 'lot_id': 'lot-x'},
                       {'incident_id': 'inc-2', 'lot_id': 'lot-y'}],
            wafer_items=[{'incident_id': 'inc-1', 'lot_id': 'lot-y', 'wafer_id': 'wafer-y'},
                         {'incident_id': 'inc-2', 'lot_id': 'lot-y', 'wafer_id': 'wafer-y'}])
        tools.lot_coverage = [dict(row, expected_lots=1, returned_total_lots=1)
                              for row in tools.lot_coverage]
        tools.wafer_coverage = [dict(row, expected_wafers=1, returned_total_wafers=1)
                                for row in tools.wafer_coverage]
        with self.assertRaisesRegex(ActionScopeBridgeError, 'WAFER_LOT_OUTSIDE_INCIDENT_SCOPE'):
            build_scoped_action_input(tools, 'tester', 'selected-scope',
                                      snapshot_lease_provider=lease_provider())

    def test_accepts_shared_lot_membership_across_selected_incidents_once(self):
        tools = SyntheticIncidentTools(
            incident_ids=('inc-1', 'inc-2'),
            lot_items=[{'incident_id': 'inc-1', 'lot_id': 'lot-shared'},
                       {'incident_id': 'inc-2', 'lot_id': 'lot-shared'}],
            wafer_items=[{'incident_id': 'inc-1', 'lot_id': 'lot-shared', 'wafer_id': 'wafer-1'},
                         {'incident_id': 'inc-2', 'lot_id': 'lot-shared', 'wafer_id': 'wafer-1'}])
        result = build_scoped_action_input(tools, 'tester', 'selected-scope',
                                           snapshot_lease_provider=lease_provider())
        self.assertEqual(result['scope'], (('wafer-1', 'lot-shared'),))

    def test_atomic_snapshot_requires_boolean_true(self):
        with self.assertRaisesRegex(ActionScopeBridgeError, 'TRUSTED_SNAPSHOT_LEASE_REQUIRED'):
            build_scoped_action_input(SyntheticIncidentTools(), 'tester', 'selected-scope',
                                      snapshot_lease_provider=lease_provider(atomic_snapshot='false'))

    def test_rejects_membership_change_reported_by_snapshot_lease(self):
        with self.assertRaisesRegex(ActionScopeBridgeError, 'SNAPSHOT_LEASE_VALIDATION_FAILED'):
            build_scoped_action_input(SyntheticIncidentTools(), 'tester', 'selected-scope',
                                      snapshot_lease_provider=lease_provider(
                                          mutate_membership_after_first_wafer_page=True), page_size=1)


if __name__ == '__main__':
    unittest.main()
