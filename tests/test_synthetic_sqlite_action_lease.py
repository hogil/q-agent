import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'app'))

from incident_tools import IncidentTools
from app.synthetic_sqlite_action_lease import (
    SyntheticSQLiteActionLease, SyntheticSQLiteLeaseError,
    sqlite_action_snapshot_lease_provider,
)


MAPPING = {
    'dialect': 'sqlite', 'mapping_version': 'synthetic-fixture-v1',
    'entities': {
        'incident': {'table': 'incidents', 'columns': {
            'incident_id': 'id', 'incident_number': 'number', 'title': 'title',
            'city': 'city', 'line': 'line', 'expected_lot_count': 'expected_lots',
            'affected_wafer_count': 'expected_wafers'}},
        'lot_list': {'table': 'lots', 'columns': {
            'incident_ref': 'incident_ref', 'lot_id': 'lot_id',
            'product_code': 'product', 'status': 'status'}},
        'wafer_list': {'table': 'wafers', 'columns': {
            'incident_ref': 'incident_ref', 'lot_id': 'wafer_lot_id',
            'wafer_id': 'wafer_id', 'status': 'status'}},
    },
    'relationships': {
        'incident_lots': {'parent_entity': 'incident', 'child_entity': 'lot_list',
                          'parent_key': 'incident_id', 'child_key': 'incident_ref',
                          'duplicate_policy': 'exact_rows_deduplicate_conflicts_error',
                          'source_completeness': 'declared_complete'},
        'incident_wafers': {'scope': 'incident_affected', 'parent_key': 'incident_id',
                            'child_key': 'incident_ref', 'lot_key': 'lot_id',
                            'source_completeness': 'declared_complete'},
    },
    'limits': {'default_page_size': 1, 'max_page_size': 20},
}


class SyntheticSQLiteActionLeaseTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'synthetic.sqlite'
        db = sqlite3.connect(self.path)
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript('CREATE TABLE incidents(id TEXT, number TEXT, title TEXT, city TEXT, line TEXT, '
                         'expected_lots INT, expected_wafers INT); '
                         'CREATE TABLE lots(incident_ref TEXT, lot_id TEXT, product TEXT, status TEXT); '
                         'CREATE TABLE wafers(incident_ref TEXT, wafer_lot_id TEXT, wafer_id TEXT, status TEXT); '
                         'CREATE TABLE manifest(revision TEXT, as_of TEXT); '
                         "INSERT INTO incidents VALUES ('inc-1','SYN-1','title','x','L1',2,2); "
                         "INSERT INTO lots VALUES ('inc-1','lot-a','p','OK'),('inc-1','lot-b','p','OK'); "
                         "INSERT INTO wafers VALUES ('inc-1','lot-a','w1','OK'),('inc-1','lot-b','w2','OK'); "
                         "INSERT INTO manifest VALUES ('fixture-rev-1','2026-10-29T00:00:00Z');")
        db.commit(); db.close()
        self.source = sqlite3.connect(self.path.as_uri() + '?mode=ro', uri=True, isolation_level=None)
        self.source.execute('PRAGMA query_only=ON')
        self.tools = IncidentTools(self.source, MAPPING)
        self.tools.scopes['scope'] = {'actor': 'actor', 'ids': ('inc-1',),
                                      'expires_at': time.monotonic() + 300,
                                      'requires_selection': False}
        self.reader = lambda con: dict(zip(('revision', 'as_of'), con.execute(
            'SELECT revision, as_of FROM manifest').fetchone()))

    def tearDown(self):
        self.source.close()
        self.temp.cleanup()

    def provider(self, reader=None):
        return sqlite_action_snapshot_lease_provider(reader or self.reader)

    def test_paged_reads_keep_private_snapshot_during_wal_writer_and_original_rollback(self):
        with self.provider()(self.tools, 'actor', 'scope') as lease:
            self.assertIsNot(lease._connection, self.source)
            page1 = lease.list_incident_lots('actor', 'scope', page_size=1, offset=0)
            writer = sqlite3.connect(self.path)
            writer.execute("INSERT INTO lots VALUES ('inc-1','lot-c','p','OK')")
            writer.commit(); writer.close()
            self.source.execute('BEGIN'); self.source.rollback()
            self.tools.db = sqlite3.connect(':memory:')  # Original handle replacement is isolated.
            page2 = lease.list_incident_lots('actor', 'scope', page_size=1, offset=1)
            self.assertEqual(page1['total_memberships'], 2)
            self.assertEqual(page2['total_memberships'], 2)
            self.assertEqual(page1['_snapshot_token'], page2['_snapshot_token'])
            self.assertEqual(lease.revision, 'fixture-rev-1')
            self.assertTrue(lease.validate())
            self.tools.db.close()
            self.tools.db = self.source

    def test_scope_actor_expiry_and_selection_are_checked_before_private_copy(self):
        with self.assertRaisesRegex(Exception, 'SCOPE_ACTOR_MISMATCH'):
            with self.provider()(self.tools, 'other', 'scope'):
                pass
        self.tools.scopes['expired'] = {'actor': 'actor', 'ids': ('inc-1',),
                                        'expires_at': 0, 'requires_selection': False}
        with self.assertRaisesRegex(Exception, 'SCOPE_EXPIRED'):
            with self.provider()(self.tools, 'actor', 'expired'):
                pass
        self.tools.scopes['select'] = {'actor': 'actor', 'ids': ('inc-1',),
                                       'expires_at': time.monotonic() + 300,
                                       'requires_selection': True}
        with self.assertRaisesRegex(Exception, 'SELECTION_REQUIRED'):
            with self.provider()(self.tools, 'actor', 'select'):
                pass

    def test_rejects_open_original_transaction_memory_file_and_bad_manifest(self):
        self.source.execute('BEGIN')
        with self.assertRaisesRegex(SyntheticSQLiteLeaseError, 'TRANSACTION_ALREADY_OPEN'):
            with self.provider()(self.tools, 'actor', 'scope'):
                pass
        self.source.rollback()
        mem = sqlite3.connect(':memory:')
        mem.executescript('CREATE TABLE incidents(id TEXT, number TEXT, title TEXT, city TEXT, line TEXT, expected_lots INT, expected_wafers INT); '
                          'CREATE TABLE lots(incident_ref TEXT, lot_id TEXT, product TEXT, status TEXT); '
                          'CREATE TABLE wafers(incident_ref TEXT, wafer_lot_id TEXT, wafer_id TEXT, status TEXT);')
        mem_tools = IncidentTools(mem, MAPPING)
        mem_tools.scopes['scope'] = self.tools.scopes['scope']
        with self.assertRaisesRegex(SyntheticSQLiteLeaseError, 'FILE_BACKED'):
            with self.provider()(mem_tools, 'actor', 'scope'):
                pass
        with self.assertRaisesRegex(SyntheticSQLiteLeaseError, 'MANIFEST_REVISION_REQUIRED'):
            with self.provider(lambda con: {'revision': '', 'as_of': self.reader(con)['as_of']})(
                    self.tools, 'actor', 'scope'):
                pass
        mem.close()

    def test_private_connection_is_query_only_and_exception_closes_it(self):
        lease = SyntheticSQLiteActionLease(self.tools, 'actor', 'scope', self.reader)
        with self.assertRaisesRegex(RuntimeError, 'body error'):
            with lease:
                db = lease._connection
                self.assertEqual(db.execute('PRAGMA query_only').fetchone()[0], 1)
                with self.assertRaises(sqlite3.OperationalError):
                    db.execute("INSERT INTO lots VALUES ('inc-1','bad','p','OK')")
                raise RuntimeError('body error')
        self.assertFalse(lease.validate())
        with self.assertRaises(sqlite3.ProgrammingError):
            db.execute('SELECT 1')

    def test_manifest_reader_receives_private_connection_after_snapshot_pin(self):
        observed = {}
        def reader(connection):
            observed['transaction_open'] = connection.in_transaction
            observed['revision'] = connection.execute(
                'SELECT revision FROM manifest').fetchone()['revision']
            observed['connection'] = connection
            return self.reader(connection)
        with SyntheticSQLiteActionLease(self.tools, 'actor', 'scope', reader) as lease:
            self.assertIs(observed['connection'], lease._connection)
            self.assertTrue(observed['transaction_open'])
            self.assertEqual(observed['revision'], 'fixture-rev-1')

    def test_concurrent_writer_and_manifest_revision_are_from_pinned_snapshot(self):
        def reader(con):
            row = con.execute('SELECT revision, as_of FROM manifest').fetchone()
            return {'revision': row['revision'], 'as_of': row['as_of']}
        with self.provider(reader)(self.tools, 'actor', 'scope') as lease:
            writer = sqlite3.connect(self.path)
            writer.execute("UPDATE manifest SET revision='fixture-rev-2'")
            writer.commit(); writer.close()
            page = lease.list_incident_wafers('actor', 'scope', page_size=1, offset=0)
            self.assertEqual(page['_snapshot_revision'], 'fixture-rev-1')
            self.assertEqual(page['items'][0]['wafer_id'], 'w1')


if __name__ == '__main__':
    unittest.main()
