"""Validated, file-relative deployment configuration. No network, mkdir or secret reads on load."""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import tomllib
import yaml
from pathlib import Path, PureWindowsPath
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from incident_filters import SCALAR_FILTER_FIELDS, ARRAY_FILTER_FIELDS

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / 'config/config.yaml'


class ConfigError(ValueError):
    pass


PATH_KEYS = ('data_root output_root model_root image_root document_root trend_root cache_root '
             'log_root skills_root dictionary_root registry_file skill_lock_file '
             'terminology_file golden_file').split()
TABLE_FIELDS = {
    'incident': ('incident_id incident_number title city line line_code line_alias department occurred_at '
                 'product_generations fab_out_failure_codes expected_lot_count affected_wafer_count '
                 'incident_detail analysis_detail confirmed_cause containment corrective_action '
                 'verification prevention remaining').split(),
    'lot_list': 'incident_ref lot_id product_code status'.split(),
    'wafer_list': 'incident_ref lot_id wafer_id status'.split(),
    'incident_document': 'document_id incident_ref title version storage_ref format source'.split(),
    'document_chunk': 'chunk_id document_ref location content'.split(),
    'image_metadata': 'image_id incident_ref lot_id wafer_id stage storage_ref coordinate_system'.split(),
    'trend_metadata': 'trend_id incident_ref metric unit storage_ref timezone'.split(),
}
MODEL_SPEC = dict(enabled=bool, mode=str, base_url=str, api_key_env=str, served_model=str,
                  local_dir=str, checkpoint_file=str, tokenizer_dir=str, timeout_seconds=int,
                  structured_outputs=bool)
RAG_SPEC = dict(enabled=bool, endpoint=str, api_key_env=str, index_name=str,
                existing_chunks=bool, methods=list, fusion=str, reranker=str,
                top_k=int, timeout_seconds=int)
SERVICE_SPEC = dict(enabled=bool, endpoint=str, api_key_env=str, timeout_seconds=int)
ENTERPRISE_SOURCE_SPEC = dict(
    id=str, system=str, dialect=str, dsn_env=str, sqlite_file=str, schema=str, view=str,
    timezone=str, synthetic=bool, columns={'*': str})
SPEC = {
    'config_version': int, 'environment': str,
    'paths': dict.fromkeys(PATH_KEYS, str),
    'database': dict(dialect=str, host=str, port=int, name=str, schema=str, sqlite_file=str, dsn_env=str,
                     connect_timeout_seconds=int, query_timeout_seconds=int, read_only=bool),
    'tables': {name: {'name': str, 'columns': dict.fromkeys(fields, str)}
               for name, fields in TABLE_FIELDS.items()},
    'relations': dict(incident_parent_key=str, lot_incident_key=str, document_incident_key=str,
                      image_incident_key=str, trend_incident_key=str, chunk_document_key=str,
                      source_completeness=str, wafer_parent_key=str, wafer_incident_key=str, wafer_lot_key=str,
                      wafer_scope=str, wafer_source_completeness=str),
    'arrays': dict(product_generations=str, fab_out_failure_codes=str),
    'value_matching': dict(enabled=bool, fields=list, max_values_per_field=int, max_candidates=int),
    'storage': dict(backend=str, endpoint=str, bucket=str, prefix=str, credential_env=str,
                    signed_url_ttl_seconds=int),
    'models': {'*': MODEL_SPEC},
    'image_tools': {name: dict(SERVICE_SPEC, served_model=str) for name in ('sem', 'overlay')},
    'roles': {role: dict(model=str, temperature=(int, float), max_output_tokens=int)
              for role in ('router', 'answer', 'judge')},
    'retrieval': {name: RAG_SPEC for name in ('internal_documents', 'engineer_notes')},
    'meetings': dict(enabled=bool, backend=str, sqlite_file=str, table=str, fts_table=str,
                     endpoint=str, api_key_env=str, top_k=int, max_top_k=int, timeout_seconds=int),
    'enterprise': dict(SERVICE_SPEC, max_rows=int, max_window_days=int, sources=list),
    'actions': dict(SERVICE_SPEC, require_approval=bool),
    'runtime': dict(timezone=str, default_page_size=int, max_page_size=int,
                    max_scope_incidents=int, scope_ttl_seconds=int, max_tool_calls=int,
                    max_parallel_tools=int, max_retries=int, max_answer_revisions=int,
                    max_agent_steps=int, max_context_characters=int, prompt_examples=bool),
}


def check_shape(data, spec, location='config'):
    if isinstance(spec, dict):
        if not isinstance(data, dict):
            raise ConfigError(f'{location}: table required')
        if '*' in spec:
            if not data:
                raise ConfigError(f'{location}: empty table')
            for key, value in data.items():
                if not re.fullmatch(r'[a-z][a-z0-9_]*', key):
                    raise ConfigError(f'{location}: invalid logical name')
                check_shape(value, spec['*'], f'{location}.{key}')
        else:
            unknown, missing = set(data) - set(spec), set(spec) - set(data)
            if unknown or missing:
                raise ConfigError(f'{location}: unknown={sorted(unknown)}, missing={sorted(missing)}')
            for key in spec:
                check_shape(data[key], spec[key], f'{location}.{key}')
    elif type(data) not in (spec if isinstance(spec, tuple) else (spec,)):
        raise ConfigError(f'{location}: wrong value type')


def merge(base, override):
    result = copy.deepcopy(base)
    for key, value in override.items():
        result[key] = merge(result[key], value) if isinstance(result.get(key), dict) and isinstance(value, dict) else copy.deepcopy(value)
    return result


class ConfigYamlLoader(yaml.SafeLoader):
    pass


def unique_yaml_mapping(loader, node):
    loader.flatten_mapping(node)
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node)
        if not isinstance(key, str) or key in result:
            raise ConfigError('YAML mapping keys must be unique strings')
        result[key] = loader.construct_object(value_node)
    return result


ConfigYamlLoader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, unique_yaml_mapping)


def read_config(path):
    try:
        with path.open('rb') as stream:
            if path.suffix.lower() == '.toml':
                data = tomllib.load(stream)
            elif path.suffix.lower() in ('.yaml', '.yml'):
                data = yaml.load(stream, Loader=ConfigYamlLoader)
            else:
                raise ConfigError('Config file must use .yaml, .yml or legacy .toml')
        if not isinstance(data, dict):
            raise ConfigError('Config root must be a mapping')
        return data
    except (OSError, tomllib.TOMLDecodeError, yaml.YAMLError) as exc:
        # Parser errors may contain credentials; report only the exception type.
        raise ConfigError(f'Cannot read config: {path.name} ({type(exc).__name__})') from None


def validate_values(data):
    if data['config_version'] != 1:
        raise ConfigError('Unsupported config_version')
    if data['environment'] not in ('demo', 'onprem', 'test'):
        raise ConfigError('environment: demo/onprem/test required')

    def visit(value, path='config'):
        if isinstance(value, dict):
            for key, item in value.items():
                place = f'{path}.{key}'
                if key.endswith('_env') and not re.fullmatch(r'[A-Z_][A-Z0-9_]*', item):
                    raise ConfigError(f'{place}: environment variable NAME required')
                if (key.endswith('_seconds') or key in ('top_k', 'max_output_tokens')) and item <= 0:
                    raise ConfigError(f'{place}: positive value required')
                if isinstance(item, str) and any(ord(c) < 32 for c in item):
                    raise ConfigError(f'{place}: control character forbidden')
                visit(item, place)
    visit(data)
    matching = data['value_matching']
    fields = matching['fields']
    if any(not isinstance(field, str) or field not in SCALAR_FILTER_FIELDS | ARRAY_FILTER_FIELDS for field in fields):
        raise ConfigError('value_matching.fields: supported logical filter fields required')
    if len(fields) != len(set(fields)) or (matching['enabled'] and not fields):
        raise ConfigError('value_matching.fields: nonempty unique fields required when enabled')
    for key in ('max_values_per_field', 'max_candidates'):
        if not 1 <= matching[key] <= 10000:
            raise ConfigError('value_matching.' + key + ': value in 1..10000 required')
    required_columns = {'incident': {'incident_id', 'incident_number', 'title', 'city', 'line'},
                        'lot_list': set(TABLE_FIELDS['lot_list']), 'wafer_list': {'lot_id','wafer_id','status'}}
    if data['relations']['wafer_scope'] == 'incident_affected':
        required_columns['wafer_list'].add('incident_ref')
    for name, table in data['tables'].items():
        for key in required_columns.get(name, set()):
            if not table['columns'][key]:
                raise ConfigError(f'tables.{name}.columns.{key}: required by current adapter')
        for value in [table['name'], *[v for v in table['columns'].values() if v]]:
            if not re.fullmatch(r'[^\W\d]\w*', value):
                raise ConfigError(f'tables.{name}: use a simple SQL identifier; schema is separate')
        mapped = [v for v in table['columns'].values() if v]
        if len({v.casefold() for v in mapped}) != len(mapped):
            raise ConfigError(f'tables.{name}: duplicate physical column mapping')
    if len({t['name'].casefold() for t in data['tables'].values()}) != len(data['tables']):
        raise ConfigError('tables: duplicate physical table names')
    db = data['database']
    if db['dialect'] not in ('sqlite', 'postgresql', 'oracle', 'sqlserver'):
        raise ConfigError('database.dialect: unsupported configuration value')
    if db['dialect'] == 'sqlite':
        if db['host'] or db['port'] != 0 or db['name']:
            raise ConfigError('SQLite uses sqlite_file; host/name must be empty and port must be 0')
    elif not db['host'].strip() or not db['name'].strip() or not 1 <= db['port'] <= 65535:
        raise ConfigError('Server database requires host, name and port in 1..65535')
    if db['schema'] and not re.fullmatch(r'[^\W\d]\w*', db['schema']):
        raise ConfigError('database.schema: invalid identifier')
    if not db['read_only']:
        raise ConfigError('database.read_only must remain true for retrieval')
    if data['relations']['incident_parent_key'] not in ('incident_id', 'incident_number', 'title'):
        raise ConfigError('relations.incident_parent_key: unsupported join')
    if data['relations']['wafer_parent_key'] not in ('incident_id', 'incident_number', 'title'):
        raise ConfigError('relations.wafer_parent_key: unsupported join')
    for key in ('lot_incident_key', 'wafer_incident_key', 'document_incident_key', 'image_incident_key', 'trend_incident_key'):
        if data['relations'][key] != 'incident_ref':
            raise ConfigError(f'relations.{key}: change physical mapping, not logical FK')
    if data['relations']['chunk_document_key'] != 'document_ref':
        raise ConfigError('relations.chunk_document_key: invalid logical FK')
    if data['relations']['source_completeness'] not in ('unknown', 'partial', 'declared_complete'):
        raise ConfigError('relations.source_completeness: invalid value')
    if data['relations']['wafer_source_completeness'] not in ('unknown', 'partial', 'declared_complete'):
        raise ConfigError('relations.wafer_source_completeness: invalid value')
    if data['relations']['wafer_scope'] not in ('incident_affected','lot_inventory') or data['relations']['wafer_lot_key'] != 'lot_id':
        raise ConfigError('relations: invalid wafer scope or logical Lot key')
    for value in data['arrays'].values():
        if value not in ('native_array', 'json_array', 'json_text'):
            raise ConfigError('arrays: invalid source representation')
    if db['dialect'] == 'sqlite' and (db['schema'] or any(v != 'json_text' for v in data['arrays'].values())):
        raise ConfigError('SQLite adapter requires empty schema and json_text arrays')

    def url(value, location, required=False):
        if not value:
            if required:
                raise ConfigError(f'{location}: endpoint required when enabled')
            return
        try:
            parsed = urlsplit(value)
            port = parsed.port
            valid = parsed.scheme in ('http', 'https') and parsed.hostname and not (
                parsed.username or parsed.password or parsed.query or parsed.fragment)
        except ValueError:
            valid = False
        if not valid:
            raise ConfigError(f'{location}: HTTP(S) URL without credentials/query/fragment required')

    if data['storage']['backend'] not in ('local', 'object'):
        raise ConfigError('storage.backend: local/object required')
    url(data['storage']['endpoint'], 'storage.endpoint', data['storage']['backend'] == 'object')
    if data['storage']['backend'] == 'object' and not data['storage']['bucket']:
        raise ConfigError('storage.bucket: required')
    meetings = data['meetings']
    if meetings['backend'] not in ('sqlite', 'http'):
        raise ConfigError('meetings.backend: sqlite/http required')
    if not 1 <= meetings['top_k'] <= meetings['max_top_k'] <= 50:
        raise ConfigError('meetings: 1 <= top_k <= max_top_k <= 50 required')
    for key in ('table', 'fts_table'):
        if not re.fullmatch(r'[^\W\d]\w*', meetings[key]):
            raise ConfigError('meetings.' + key + ': simple SQL identifier required')
    if meetings['table'].casefold() == meetings['fts_table'].casefold():
        raise ConfigError('meetings: distinct table names required')
    url(meetings['endpoint'], 'meetings.endpoint', meetings['enabled'] and meetings['backend'] == 'http')
    if meetings['enabled'] and meetings['backend'] == 'http':
        parsed = urlsplit(meetings['endpoint'])
        if parsed.scheme != 'https' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
            raise ConfigError('meetings.endpoint: HTTPS required outside loopback')
    for name, model in data['models'].items():
        if model['mode'] not in ('api', 'local'):
            raise ConfigError(f'models.{name}.mode: api/local required')
        url(model['base_url'], f'models.{name}.base_url', model['enabled'] and model['mode'] == 'api')
        if model['enabled'] and model['mode'] == 'api' and (not model['served_model'] or model['served_model'].startswith(('SET_', 'YOUR_'))):
            raise ConfigError(f'models.{name}.served_model: real served model name required')
        if not model['local_dir']:
            raise ConfigError(f'models.{name}.local_dir: required')
        filename = model['checkpoint_file']
        if filename and (filename in ('.', '..') or '/' in filename or '\\' in filename or ':' in filename):
            raise ConfigError(f'models.{name}.checkpoint_file: filename only; set folder with local_dir')
    for role, profile in data['roles'].items():
        if profile['model'] not in data['models']:
            raise ConfigError(f'roles.{role}.model: unknown model reference')
        if not 0 <= profile['temperature'] <= 2:
            raise ConfigError(f'roles.{role}.temperature: out of range')
    for name, service in data['image_tools'].items():
        url(service['endpoint'], f'image_tools.{name}.endpoint', service['enabled'])
        if service['enabled']:
            parsed = urlsplit(service['endpoint'])
            if parsed.scheme != 'https' and parsed.hostname not in ('127.0.0.1', 'localhost', '::1'):
                raise ConfigError(f'image_tools.{name}.endpoint: HTTPS required outside loopback')
            if not service['served_model'] or service['served_model'].startswith(('SET_', 'YOUR_')):
                raise ConfigError(f'image_tools.{name}.served_model: actual model required')
    for name, source in data['retrieval'].items():
        url(source['endpoint'], f'retrieval.{name}.endpoint', source['enabled'])
        if source['existing_chunks'] is not True or source['methods'] != ['bm25', 'vector_similarity']:
            raise ConfigError(f'retrieval.{name}: existing BM25 + vector chunks must be retained')
        if not source['fusion'] or not source['reranker']:
            raise ConfigError(f'retrieval.{name}: existing retrieval policy required')
        if source['enabled'] and (not source['index_name'] or source['index_name'].startswith(('SET_', 'YOUR_'))):
            raise ConfigError(f'retrieval.{name}.index_name: actual index required')
    enterprise = data['enterprise']
    if not 1 <= enterprise['max_rows'] <= 100 or not 1 <= enterprise['max_window_days'] <= 366:
        raise ConfigError('enterprise: bounded max_rows/max_window_days required')
    if len(enterprise['sources']) > 8 or (enterprise['enabled'] and not enterprise['sources']):
        raise ConfigError('enterprise.sources: 1..8 SQL sources required when enabled')
    source_ids = set()
    for source in enterprise['sources']:
        check_shape(source, ENTERPRISE_SOURCE_SPEC, 'enterprise.sources')
        if not re.fullmatch(r'[a-z][a-z0-9_]*', source['id']) or source['id'] in source_ids:
            raise ConfigError('enterprise.sources: unique logical id required')
        source_ids.add(source['id'])
        if not source['system'].strip() or source['dialect'] not in ('sqlite', 'sqlserver', 'oracle', 'postgresql'):
            raise ConfigError('enterprise.sources: system and supported SQL dialect required')
        if not re.fullmatch(r'[A-Z_][A-Z0-9_]*', source['dsn_env']):
            raise ConfigError('enterprise.sources: DSN environment variable NAME required')
        if source['dialect'] == 'sqlite' and (not source['sqlite_file'] or source['schema']):
            raise ConfigError('enterprise.sources: SQLite file and empty schema required')
        columns = source['columns']
        if not {'record_id', 'equipment', 'step', 'occurred_at'} <= columns.keys() or len(columns) > 16:
            raise ConfigError('enterprise.sources: record_id/equipment/step/occurred_at mappings required; max 16')
        for value in [source['view'], *columns.values(), *([source['schema']] if source['schema'] else [])]:
            if not re.fullmatch(r'[^\W\d]\w*', value):
                raise ConfigError('enterprise.sources: simple SQL identifiers required')
        try:
            ZoneInfo(source['timezone'])
        except (ZoneInfoNotFoundError, ValueError):
            raise ConfigError('enterprise.sources: valid source timezone required') from None
    for name in ('actions',):
        url(data[name]['endpoint'], f'{name}.endpoint', data[name]['enabled'])
    if data['actions']['require_approval'] is not True:
        raise ConfigError('actions.require_approval must remain true')
    rt = data['runtime']
    for key in ('default_page_size', 'max_page_size', 'max_scope_incidents', 'max_tool_calls', 'max_parallel_tools', 'max_agent_steps', 'max_context_characters'):
        if rt[key] < 1:
            raise ConfigError(f'runtime.{key}: positive value required')
    for key in ('max_retries', 'max_answer_revisions'):
        if rt[key] < 0:
            raise ConfigError(f'runtime.{key}: nonnegative value required')
    if rt['default_page_size'] > rt['max_page_size']:
        raise ConfigError('runtime.default_page_size exceeds max_page_size')
    try:
        ZoneInfo(rt['timezone'])
    except (ZoneInfoNotFoundError, ValueError):
        raise ConfigError('runtime.timezone: timezone unavailable; install system tzdata if needed') from None


def resolve_paths(data, base_dir):
    cache, active = {}, set()

    def absolute(raw, label):
        if not raw:
            raise ConfigError(f'{label}: path cannot be empty')
        if os.name != 'nt' and PureWindowsPath(raw).drive:
            raise ConfigError(f'{label}: Windows path cannot be used on this Linux runtime')
        path = Path(raw).expanduser()
        return str((path if path.is_absolute() else base_dir / path).resolve())

    def expand(raw):
        result = re.sub(r'\$\{paths\.([a-z_]+)\}', lambda m: path_value(m.group(1)), raw)
        if '${' in result:
            raise ConfigError('Unresolved path reference; only ${paths.name} is supported')
        return result

    def path_value(key):
        if key not in data['paths']:
            raise ConfigError(f'Unknown path reference: paths.{key}')
        if key in active:
            raise ConfigError(f'Cyclic path reference: paths.{key}')
        if key not in cache:
            active.add(key)
            cache[key] = absolute(expand(data['paths'][key]), f'paths.{key}')
            active.remove(key)
        return cache[key]
    for key in data['paths']:
        path_value(key)
    data['paths'] = cache
    data['database']['sqlite_file'] = absolute(expand(data['database']['sqlite_file']), 'database.sqlite_file')
    data['meetings']['sqlite_file'] = absolute(expand(data['meetings']['sqlite_file']), 'meetings.sqlite_file')
    for source in data['enterprise']['sources']:
        if source['sqlite_file']:
            source['sqlite_file'] = absolute(expand(source['sqlite_file']), 'enterprise.sources.sqlite_file')
    for name, model in data['models'].items():
        for key in ('local_dir', 'tokenizer_dir'):
            if model[key]:
                model[key] = absolute(expand(model[key]), f'models.{name}.{key}')


class Settings:
    def __init__(self, data, source_files):
        self.data = copy.deepcopy(data)
        self.source_files = tuple(source_files)
        self.config_hash = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def model_profile(self, role):
        profile = copy.deepcopy(self.data['roles'][role])
        model = copy.deepcopy(self.data['models'][profile['model']])
        model['checkpoint_path'] = str(Path(model['local_dir']) / model['checkpoint_file']) if model['checkpoint_file'] else ''
        return dict(profile, deployment=model)

    def mapping(self):
        d = self.data
        return {
            'mapping_version': self.config_hash,
            'dialect': d['database']['dialect'],
            'entities': {key: {'table': d['tables'][key]['name'], 'columns': {k:v for k,v in d['tables'][key]['columns'].items() if v}}
                         for key in ('incident', 'lot_list','wafer_list')},
            'relationships': {'incident_lots': {
                'parent_entity': 'incident', 'parent_key': d['relations']['incident_parent_key'],
                'child_entity': 'lot_list', 'child_key': d['relations']['lot_incident_key'],
                'grain': ['incident_id', 'lot_id'], 'relation_scope': 'registered affected lots',
                'source_completeness': d['relations']['source_completeness'],
                'duplicate_policy': 'exact_rows_deduplicate_conflicts_error'},
                'incident_wafers': {'parent_key':d['relations']['wafer_parent_key'],
                    'child_key':d['relations']['wafer_incident_key'], 'lot_key':d['relations']['wafer_lot_key'],
                    'scope':d['relations']['wafer_scope'], 'source_completeness':d['relations']['wafer_source_completeness']}},
            'limits': {key: d['runtime'][key] for key in ('default_page_size', 'max_page_size', 'max_scope_incidents')},
        }

    def check_paths(self):
        """Read-only checks. No endpoint probes and no directory creation."""
        errors = []
        for key in ('registry_file', 'skill_lock_file'):
            if not Path(self.data['paths'][key]).is_file():
                errors.append(f'paths.{key}: file missing')
        for key in ('skills_root', 'dictionary_root'):
            if not Path(self.data['paths'][key]).is_dir():
                errors.append(f'paths.{key}: directory missing')
        for name, model in self.data['models'].items():
            if model['enabled'] and model['mode'] == 'local':
                target = Path(model['local_dir'])
                if not target.is_dir():
                    errors.append(f'models.{name}.local_dir: directory missing')
                if model['checkpoint_file'] and not (target / model['checkpoint_file']).is_file():
                    errors.append(f'models.{name}.checkpoint_file: file missing')
                if model['tokenizer_dir'] and not Path(model['tokenizer_dir']).is_dir():
                    errors.append(f'models.{name}.tokenizer_dir: directory missing')
        if errors:
            raise ConfigError('; '.join(errors))


def load_config(config=None, overlay=None):
    base = Path(config or os.environ.get('QAGENT_CONFIG') or DEFAULT_CONFIG).expanduser().resolve()
    selected = overlay if overlay is not None else os.environ.get('QAGENT_OVERLAY')
    data, sources = read_config(base), [str(base)]
    if selected:
        site = Path(selected).expanduser().resolve()
        data = merge(data, read_config(site))
        sources.append(str(site))
    check_shape(data, SPEC)
    validate_values(data)
    resolve_paths(data, base.parent)
    return Settings(data, sources)


def add_config_arguments(parser):
    parser.add_argument('--config', help='Base YAML; defaults to QAGENT_CONFIG or bundled config/config.yaml')
    parser.add_argument('--overlay', help='Site YAML; defaults to QAGENT_OVERLAY; paths are relative to the base config. Legacy TOML is accepted.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    add_config_arguments(parser)
    parser.add_argument('--check-paths', action='store_true')
    parser.add_argument('--show', action='store_true', help='Print effective non-secret settings; may contain internal paths')
    args = parser.parse_args()
    try:
        settings = load_config(args.config, args.overlay)
        if args.check_paths:
            settings.check_paths()
        result = {'status': 'CONFIG_VALID', 'config_hash': settings.config_hash,
                  'environment': settings.data['environment'], 'network_checked': False}
        if args.show:
            result['effective_config'] = settings.data
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except ConfigError as exc:
        parser.exit(2, f'CONFIG_ERROR: {exc}\n')
