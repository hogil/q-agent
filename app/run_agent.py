"""Agent entry point: site checks, prompt compilation and a bounded ReAct run."""
import argparse
import json
from pathlib import Path

from config_loader import ConfigError, DEFAULT_CONFIG, load_config, read_config
from skill_loader import compile_prompt


SITE_PATHS = ('skills_root', 'dictionary_root', 'registry_file', 'skill_lock_file',
              'terminology_file')


def load_site(site_file):
    site = Path(site_file).expanduser().resolve()
    raw = read_config(site)
    if raw.get('environment') != 'onprem':
        raise ConfigError('Site config must explicitly set environment: onprem')
    paths = raw.get('paths')
    if not isinstance(paths, dict) or any(not paths.get(key) for key in SITE_PATHS):
        raise ConfigError('Site config must explicitly set paths: ' + ', '.join(SITE_PATHS))
    # Explicit arguments prevent QAGENT_CONFIG/QAGENT_OVERLAY from selecting another site.
    settings = load_config(DEFAULT_CONFIG, site)
    bundled = load_config(DEFAULT_CONFIG, overlay='')
    database = raw.get('database', {})
    connection_keys = ('dialect', 'sqlite_file') if settings.data['database']['dialect'] == 'sqlite' else ('dialect', 'host', 'port', 'name', 'schema')
    if any(key not in database for key in connection_keys):
        raise ConfigError('Site config must explicitly set database: ' + ', '.join(connection_keys))
    for entity, table in settings.data['tables'].items():
        configured = raw.get('tables', {}).get(entity, {})
        if 'name' not in configured or set(configured.get('columns', {})) != set(table['columns']):
            raise ConfigError('Site config must explicitly map table name and all logical columns: ' + entity)
    if settings.data['database']['dialect'] == 'sqlite' and settings.data['database']['sqlite_file'] == bundled.data['database']['sqlite_file']:
        raise ConfigError('Bundled demo SQLite path is not allowed')
    for key in SITE_PATHS:
        target = Path(settings.data['paths'][key])
        if target == Path(bundled.data['paths'][key]):
            raise ConfigError('Bundled demo resource is not allowed: paths.' + key)
        exists = target.is_dir() if key.endswith('_root') else target.is_file()
        if not exists:
            raise ConfigError('Site resource missing: paths.' + key)
    dictionary_path = Path(settings.data['paths']['terminology_file'])
    dictionary_root = Path(settings.data['paths']['dictionary_root'])
    if not dictionary_path.is_relative_to(dictionary_root):
        raise ConfigError('Site terminology_file must be inside dictionary_root for release verification')
    dictionary = json.loads(dictionary_path.read_text(encoding='utf-8'))
    if not isinstance(dictionary, dict) or dictionary.get('synthetic') is not False:
        raise ConfigError('Site dictionary must explicitly declare synthetic: false')
    if not dictionary.get('version') or not isinstance(dictionary.get('fields'), dict):
        raise ConfigError('Invalid site dictionary')
    return settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-config', required=True, help='Explicit site YAML; no default or environment fallback')
    parser.add_argument('--mode', choices=('check', 'prompt', 'run'), default='check')
    parser.add_argument('--role', choices=('router', 'judge', 'answer'), default='router')
    parser.add_argument('--topics', default='incident_search', help='Comma-separated registered topics')
    parser.add_argument('--question', help='Question for --mode run')
    parser.add_argument('--actor', help='Local caller identifier; not authentication or ACL')
    parser.add_argument('--request-scope', choices=('incident', 'independent'), default='incident')
    parser.add_argument('--select-incident', action='append', help='Explicitly select a returned candidate ID; repeatable')
    parser.add_argument('--trace', action='store_true', help='Write live events to stderr; may contain private query data')
    args = parser.parse_args()
    try:
        settings = load_site(args.site_config)
        topics = [topic.strip() for topic in args.topics.split(',') if topic.strip()]
        if args.mode == 'run':
            if not args.question or not args.actor:
                parser.error('--mode run requires --question and --actor')
            import sys
            from agent import run
            emit = (lambda event: print(json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True)) if args.trace else None
            result = run(settings, args.question, args.actor, args.request_scope, topics, args.select_incident, emit)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2 if result['status'] == 'unavailable' else 0
        roles = ('router', 'judge', 'answer') if args.mode == 'check' else (args.role,)
        prompts = [compile_prompt(role, topics, settings=settings) for role in roles]
        if args.mode == 'prompt':
            print(prompts[0]['system_prompt'])
        else:
            print(json.dumps({'status': 'SITE_CONFIG_AND_SKILLS_VALID',
                              'config_hash': settings.config_hash,
                              'release': prompts[0]['release'], 'roles': list(roles),
                              'network_checked': False, 'agent_started': False,
                              'notice': 'No DB/model connection or real-data correctness validation.'}, indent=2))
    except (ConfigError, OSError, ValueError, KeyError, TypeError) as exc:
        # File/parser errors can embed private paths or source contents.
        detail = str(exc) if isinstance(exc, ConfigError) else type(exc).__name__
        parser.exit(2, 'ONPREM_ERROR: ' + detail + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
