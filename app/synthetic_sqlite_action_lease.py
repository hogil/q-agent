"""Owned read-only SQLite snapshot for the synthetic action-scope bridge.

The lease opens a private mode=ro connection whose resolved main-database path
matches IncidentTools' path, pins a read transaction with its own SQLite SELECT,
then requires the injected trusted synthetic manifest reader to SELECT through
that same connection. This checks path strings, not open-file identity; database
replacement/rotation after either connection opens is not detected. The request
UUID is only a correlation token. Manifest truth depends on the injected
provider; this does not provide production ACL, historical as_of guarantees, or
action execution rights.

The trust boundary is API ownership: callers must not mutate this lease's private
objects through reflection or share them with untrusted code. This is not a
process sandbox or a production authorization mechanism.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from uuid import uuid4

from incident_tools import IncidentTools


class SyntheticSQLiteLeaseError(RuntimeError):
    pass


def _database_path(connection):
    rows = connection.execute('PRAGMA database_list').fetchall()
    main = next((row[2] for row in rows if row[1] == 'main'), '')
    if not main:
        raise SyntheticSQLiteLeaseError('SQLITE_FILE_BACKED_DATABASE_REQUIRED')
    return Path(main).resolve()


class SyntheticSQLiteActionLease:
    atomic_snapshot = True

    def __init__(self, tools, actor, scope_id, manifest_reader):
        self.tools = tools
        self.actor = actor
        self.scope_id = scope_id
        self.manifest_reader = manifest_reader
        self.snapshot_token = str(uuid4())
        self.revision = None
        self.as_of = None
        self._connection = None
        self._snapshot_tools = None
        self._active = False

    def __enter__(self):
        source = getattr(self.tools, 'db', None)
        if not isinstance(source, sqlite3.Connection):
            raise SyntheticSQLiteLeaseError('SQLITE_TOOLS_CONNECTION_REQUIRED')
        if source.in_transaction:
            raise SyntheticSQLiteLeaseError('SQLITE_TRANSACTION_ALREADY_OPEN')
        scope = self.tools._scope(self.actor, self.scope_id)
        path = _database_path(source)
        connection = None
        try:
            connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True,
                                         isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute('PRAGMA query_only=ON')
            if connection.execute('PRAGMA query_only').fetchone()[0] != 1:
                raise SyntheticSQLiteLeaseError('SQLITE_QUERY_ONLY_REQUIRED')
            if _database_path(connection) != path:
                raise SyntheticSQLiteLeaseError('SQLITE_DATABASE_PATH_MISMATCH')
            connection.execute('BEGIN')
            # Pin the transaction snapshot before invoking the trusted reader.
            connection.execute('SELECT name FROM sqlite_master LIMIT 1').fetchone()
            manifest = self.manifest_reader(connection)
            if not connection.in_transaction:
                raise SyntheticSQLiteLeaseError('SQLITE_MANIFEST_READER_ENDED_TRANSACTION')
            if not isinstance(manifest, dict):
                raise SyntheticSQLiteLeaseError('SYNTHETIC_MANIFEST_REQUIRED')
            revision, as_of = manifest.get('revision'), manifest.get('as_of')
            if not isinstance(revision, str) or not revision.strip():
                raise SyntheticSQLiteLeaseError('SYNTHETIC_MANIFEST_REVISION_REQUIRED')
            if isinstance(as_of, str):
                try:
                    as_of = datetime.fromisoformat(as_of.replace('Z', '+00:00'))
                except ValueError as exc:
                    raise SyntheticSQLiteLeaseError('SYNTHETIC_MANIFEST_AS_OF_INVALID') from exc
            if (not isinstance(as_of, datetime) or as_of.tzinfo is None or
                    as_of.utcoffset() != timezone.utc.utcoffset(as_of)):
                raise SyntheticSQLiteLeaseError('SYNTHETIC_MANIFEST_AS_OF_INVALID')

            snapshot_tools = IncidentTools(connection, self.tools.m,
                                           scope_ttl_seconds=self.tools.scope_ttl_seconds,
                                           value_matching=self.tools.value_matching)
            # _scope above owns actor, expiry and selection validation. Copy only
            # that validated record under the same ID so the bridge scope remains.
            snapshot_tools.scopes[self.scope_id] = dict(scope)
            self._connection = connection
            self._snapshot_tools = snapshot_tools
            self.revision = revision
            self.as_of = as_of.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')
            self._active = True
            return self
        except Exception:
            if connection is not None:
                if connection.in_transaction:
                    connection.rollback()
                connection.close()
            raise

    def __exit__(self, exc_type, exc, traceback):
        self._active = False
        if self._connection is not None:
            try:
                if self._connection.in_transaction:
                    self._connection.rollback()
            finally:
                self._connection.close()
                self._connection = None
        self._snapshot_tools = None
        return False

    def _page(self, method_name, actor, scope_id, **kwargs):
        connection = self._connection
        if (not self._active or connection is None or
                not connection.in_transaction or self._snapshot_tools is None):
            raise SyntheticSQLiteLeaseError('SQLITE_SNAPSHOT_LEASE_CLOSED')
        if actor != self.actor or scope_id != self.scope_id:
            raise SyntheticSQLiteLeaseError('SQLITE_SNAPSHOT_SCOPE_MISMATCH')
        page = getattr(self._snapshot_tools, method_name)(actor, scope_id, **kwargs)
        if not connection.in_transaction:
            self._active = False
            raise SyntheticSQLiteLeaseError('SQLITE_SNAPSHOT_TRANSACTION_ENDED')
        page['_snapshot_token'] = self.snapshot_token
        page['_snapshot_revision'] = self.revision
        page['_snapshot_as_of'] = self.as_of
        return page

    def list_incident_lots(self, actor, scope_id, **kwargs):
        return self._page('list_incident_lots', actor, scope_id, **kwargs)

    def list_incident_wafers(self, actor, scope_id, **kwargs):
        return self._page('list_incident_wafers', actor, scope_id, **kwargs)

    def validate(self):
        return (self._active and self._connection is not None and
                self._connection.in_transaction)


def sqlite_action_snapshot_lease_provider(manifest_reader):
    """Create an action_scope_bridge provider using a trusted synthetic manifest reader."""
    if not callable(manifest_reader):
        raise TypeError('manifest_reader must be callable')

    @contextmanager
    def provide(tools, actor, scope_id):
        with SyntheticSQLiteActionLease(tools, actor, scope_id, manifest_reader) as lease:
            yield lease

    return provide
