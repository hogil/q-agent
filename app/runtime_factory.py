"""Configuration consumers implemented today: read-only SQLite retrieval and role profiles."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import time

from config_loader import ConfigError
from incident_tools import IncidentTools


@contextmanager
def open_incident_tools(settings):
    data = settings.data
    if data['database']['dialect'] != 'sqlite':
        raise ConfigError('DATABASE_ADAPTER_NOT_IMPLEMENTED: configuration valid, production driver required')
    path = Path(data['database']['sqlite_file'])
    if not path.is_file():
        raise ConfigError('DATABASE_FILE_MISSING: generate demo or configure an existing database')
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True,
                                 timeout=data['database']['connect_timeout_seconds'])
    try:
        connection.execute('PRAGMA query_only=ON')
        deadline = [time.monotonic() + data['database']['query_timeout_seconds']]
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline[0]), 1000)

        class ConfiguredIncidentTools(IncidentTools):
            def find_incidents(self, *args, **kwargs):
                deadline[0] = time.monotonic() + data['database']['query_timeout_seconds']
                return super().find_incidents(*args, **kwargs)

            def list_incident_lots(self, *args, **kwargs):
                deadline[0] = time.monotonic() + data['database']['query_timeout_seconds']
                return super().list_incident_lots(*args, **kwargs)

        yield ConfiguredIncidentTools(connection, settings.mapping(),
                                      scope_ttl_seconds=data['runtime']['scope_ttl_seconds'])
    finally:
        connection.close()
