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
        raise ConfigError('DATABASE_FILE_MISSING: configure an existing database')
    connection = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True,
                                 timeout=data['database']['connect_timeout_seconds'])
    try:
        connection.execute('PRAGMA query_only=ON')
        deadline = [time.monotonic() + data['database']['query_timeout_seconds']]
        connection.set_progress_handler(lambda: int(time.monotonic() > deadline[0]), 1000)

        class ConfiguredIncidentTools(IncidentTools):
            def get_platform_evidence(self, *args, **kwargs):
                deadline[0] = time.monotonic() + data['database']['query_timeout_seconds']
                return super().get_platform_evidence(*args, **kwargs)

            def search_platform_history(self, *args, **kwargs):
                deadline[0] = time.monotonic() + data['database']['query_timeout_seconds']
                return super().search_platform_history(*args, **kwargs)

            def match_incident_values(self, *args, **kwargs):
                deadline[0] = time.monotonic() + data['database']['query_timeout_seconds']
                return super().match_incident_values(*args, **kwargs)

            def find_incidents(self, *args, **kwargs):
                deadline[0] = time.monotonic() + data['database']['query_timeout_seconds']
                return super().find_incidents(*args, **kwargs)

            def summarize_incidents(self, *args, **kwargs):
                deadline[0] = time.monotonic() + data['database']['query_timeout_seconds']
                return super().summarize_incidents(*args, **kwargs)

            def list_incident_lots(self, *args, **kwargs):
                deadline[0] = time.monotonic() + data['database']['query_timeout_seconds']
                return super().list_incident_lots(*args, **kwargs)

            def search_related_incidents(self, *args, **kwargs):
                deadline[0] = time.monotonic() + data['database']['query_timeout_seconds']
                return super().search_related_incidents(*args, **kwargs)

            def list_incident_wafers(self, *args, **kwargs):
                deadline[0] = time.monotonic() + data['database']['query_timeout_seconds']
                return super().list_incident_wafers(*args, **kwargs)

        tool = ConfiguredIncidentTools(connection, settings.mapping(),
                                       scope_ttl_seconds=data['runtime']['scope_ttl_seconds'],
                                       value_matching=data['value_matching'])
        tool.platform_settings = settings
        yield tool
    finally:
        connection.close()


def open_synthetic_mes_reference(settings):
    """Create the configured read-only demo MES reader, or return None when off."""
    data = settings.data
    options = data.get('mes_reference', {}).get('synthetic_sqlite', {})
    if options.get('enabled') is not True:
        return None
    if data.get('environment') != 'demo' or data.get('mes_reference', {}).get('enabled') is not True:
        raise ConfigError('mes_reference.synthetic_sqlite: enabled demo MES reference only')
    root = Path(data['paths']['data_root']).resolve()
    path = Path(options['database_file'])
    if not path.is_absolute():
        raise ConfigError('mes_reference.synthetic_sqlite.database_file: resolved path required')
    path = path.resolve()
    if not path.is_relative_to(root):
        raise ConfigError('mes_reference.synthetic_sqlite.database_file: path escapes paths.data_root')
    if not path.is_file():
        raise ConfigError('mes_reference.synthetic_sqlite.database_file: existing synthetic SQLite file required')
    from mes_reference_sqlite import SyntheticMESReferenceReader
    return SyntheticMESReferenceReader(
        path, {'table': options['table'], 'columns': options['columns']},
        timezone_name=options['timezone'],
        allowed_kinds=data['mes_reference']['allowed_kinds'],
        filter_columns=options.get('filter_columns'))
