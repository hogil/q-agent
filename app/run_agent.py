"""Agent entry point: site checks, prompt compilation and a bounded ReAct run."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from config_loader import ConfigError, DEFAULT_CONFIG, Settings, load_config, read_config
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
    meetings = settings.data['meetings']
    if meetings['enabled']:
        required = ('backend', 'sqlite_file', 'table', 'fts_table') if meetings['backend'] == 'sqlite' else ('backend', 'endpoint', 'api_key_env')
        if any(key not in raw.get('meetings', {}) for key in required):
            raise ConfigError('Site config must explicitly set meetings: ' + ', '.join(required))
        if meetings['backend'] == 'sqlite' and meetings['sqlite_file'] == bundled.data['meetings']['sqlite_file']:
            raise ConfigError('Bundled meeting database is not allowed')
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
    environment = parser.add_mutually_exclusive_group(required=True)
    environment.add_argument('--site-config', help='Explicit site YAML; no default or environment fallback')
    environment.add_argument('--demo', action='store_true', help='Explicit synthetic environment; never a site fallback')
    parser.add_argument('--demo-overlay', help='Optional demo-only model/path overlay; relative paths use config/ as base')
    parser.add_argument('--demo-profile', choices=('basic', 'hard'), help='Synthetic data profile for --mode prepare-demo only')
    parser.add_argument('--mode', choices=('check', 'prompt', 'run', 'prepare-demo', 'evaluate', 'propose', 'compare'), default='check')
    parser.add_argument('--role', choices=('router', 'judge', 'answer'), default='router')
    parser.add_argument('--topics', default='incident_search', help='Comma-separated registered topics')
    parser.add_argument('--question', help='Question for --mode run')
    parser.add_argument('--actor', help='Local caller identifier; not authentication or ACL')
    parser.add_argument('--request-scope', choices=('auto', 'incident', 'independent'), default='auto')
    parser.add_argument('--as-of', help='Meeting availability cutoff YYYY-MM-DD; default is today in runtime.timezone')
    parser.add_argument('--split', choices=('train', 'dev', 'test'), default='dev')
    parser.add_argument('--evaluation-mode', choices=('retrieval', 'live'), default='retrieval')
    parser.add_argument('--query-source', choices=('annotated', 'question'), default='annotated', help='Meeting retrieval input; question stress-tests full wording, not Router quality')
    parser.add_argument('--limit', type=int, help='Maximum golden cases, explicit positive bound')
    parser.add_argument('--report', help='Existing dev report for propose, or candidate report for compare')
    parser.add_argument('--baseline', help='Baseline retrieval report for --mode compare')
    examples = parser.add_mutually_exclusive_group()
    examples.add_argument('--with-examples', dest='examples', action='store_true')
    examples.add_argument('--without-examples', dest='examples', action='store_false')
    parser.set_defaults(examples=None)
    parser.add_argument('--select-incident', action='append', help='Explicitly select a returned candidate ID; repeatable')
    parser.add_argument('--trace', action='store_true', help='Write live events to stderr; may contain private query data')
    args = parser.parse_args()
    try:
        if args.demo_overlay and not args.demo:
            parser.error('--demo-overlay requires --demo')
        if args.demo_profile and (not args.demo or args.mode != 'prepare-demo'):
            parser.error('--demo-profile requires --demo --mode prepare-demo')
        if args.demo:
            settings = load_config(DEFAULT_CONFIG, DEFAULT_CONFIG.parent / 'demo.yaml')
            if args.demo_overlay:
                from config_loader import check_shape, merge, resolve_paths, SPEC, validate_values
                overlay = Path(args.demo_overlay).expanduser().resolve()
                data = merge(merge(read_config(DEFAULT_CONFIG), read_config(DEFAULT_CONFIG.parent / 'demo.yaml')), read_config(overlay))
                check_shape(data, SPEC)
                validate_values(data)
                resolve_paths(data, DEFAULT_CONFIG.parent)
                settings = Settings(data, (*settings.source_files, str(overlay)))
            if settings.data['environment'] not in ('demo', 'test'):
                raise ConfigError('--demo requires environment demo/test')
        else:
            settings = load_site(args.site_config)
        if args.examples is not None:
            data = settings.data.copy()
            data['runtime'] = {**data['runtime'], 'prompt_examples': args.examples}
            settings = Settings(data, settings.source_files)
        topics = [topic.strip() for topic in args.topics.split(',') if topic.strip()]
        if args.mode == 'prepare-demo':
            if not args.demo:
                parser.error('--mode prepare-demo requires --demo')
            from demo_data import generate
            print(json.dumps(generate(settings, profile=args.demo_profile or 'basic'), ensure_ascii=False, indent=2))
            return 0
        if args.mode in ('evaluate', 'propose', 'compare'):
            from golden import compare, evaluate, propose
            if args.mode == 'evaluate':
                result = evaluate(settings, split=args.split, mode=args.evaluation_mode, limit=args.limit, query_source=args.query_source)
            else:
                if not args.report:
                    parser.error('--mode ' + args.mode + ' requires --report')
                report = json.loads(Path(args.report).read_text(encoding='utf-8'))
                if args.mode == 'compare':
                    if not args.baseline:
                        parser.error('--mode compare requires --baseline')
                    result = compare(json.loads(Path(args.baseline).read_text(encoding='utf-8')), report)
                else:
                    result = propose(report)
            output = Path(settings.data['paths']['output_root'])
            output.mkdir(parents=True, exist_ok=True)
            path = output / (args.mode + '-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
            with path.open('x', encoding='utf-8') as stream:
                json.dump(result, stream, ensure_ascii=False, indent=2)
            print(json.dumps({'report_file': str(path), 'result': result}, ensure_ascii=False, indent=2))
            return 2 if ((args.mode == 'evaluate' and result['aggregate']['failed'])
                         or (args.mode == 'compare' and result['status'] == 'regression')) else 0
        if args.mode == 'run':
            if not args.question or not args.actor:
                parser.error('--mode run requires --question and --actor')
            import sys
            from agent import run
            emit = (lambda event: print(json.dumps(event, ensure_ascii=False), file=sys.stderr, flush=True)) if args.trace else None
            result = run(settings, args.question, args.actor, args.request_scope, topics, args.select_incident, emit, as_of=args.as_of)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 2 if result['status'] == 'unavailable' else 0
        roles = ('router', 'judge', 'answer') if args.mode == 'check' else (args.role,)
        prompts = [compile_prompt(role, topics, settings=settings, shared_topics=args.mode == 'check') for role in roles]
        if args.mode == 'prompt':
            print(prompts[0]['system_prompt'])
        else:
            print(json.dumps({'status': 'CONFIG_AND_SKILLS_VALID',
                              'config_hash': settings.config_hash,
                              'release': prompts[0]['release'], 'roles': list(roles),
                              'network_checked': False, 'agent_started': False,
                              'notice': 'No DB/model connection or real-data correctness validation.'}, indent=2))
    except (ConfigError, OSError, ValueError, KeyError, TypeError) as exc:
        # File/parser errors can embed private paths or source contents.
        detail = str(exc) if isinstance(exc, ConfigError) else type(exc).__name__
        parser.exit(2, 'QAGENT_ERROR: ' + detail + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
