"""Standalone synthetic, read-only code-worker experiment; no LLM team calls."""
import argparse
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.team_executor import run_team
from app.team_graph import EvidencePin, Task, trusted_scope_context
from app.team_ledger import EvidenceLedger
from config_loader import ConfigError, add_config_arguments, load_config
from incident_tools import ToolError
from runtime_factory import open_incident_tools
from skill_loader import compile_prompt


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def run_synthetic(settings, incident_number):
    policy = settings.data['runtime'].get('team_execution', {})
    if settings.data['environment'] != 'demo' or policy.get('enabled') is not True:
        raise ValueError('SYNTHETIC_TEAM_OVERLAY_REQUIRED')
    if settings.data['database']['dialect'] != 'sqlite' or not settings.data['database']['read_only']:
        raise ValueError('SYNTHETIC_READONLY_SQLITE_REQUIRED')
    release = compile_prompt('router', ['incident_search'], settings=settings)['release']
    actor, queries, trace = 'synthetic-team-cli', 0, []
    budget = settings.data['runtime']['max_tool_calls']
    with open_incident_tools(settings) as tool:
        def query(name, **arguments):
            nonlocal queries
            if queries >= budget:
                raise ValueError('PARENT_TOOL_BUDGET_EXCEEDED')
            queries += 1
            result = getattr(tool, name)(actor, **arguments)
            trace.append({'tool': name, 'status': result.get('status')})
            return result

        found = query('find_incidents', incident_number=incident_number)
        if found.get('requires_selection') or len(found['data']) != 1:
            raise ValueError('EXPLICIT_UNIQUE_INCIDENT_REQUIRED')
        scope_id = found['scope_id']

        def pages(name):
            result, offset, seen = [], 0, set()
            while True:
                if offset in seen:
                    raise ValueError('PAGINATION_LOOP')
                seen.add(offset)
                page = query(name, scope_id=scope_id, offset=offset)
                result.append(page)
                if page.get('next_offset') is None:
                    return result
                offset = page['next_offset']

        lot_pages = pages('list_incident_lots')
        wafer_pages = pages('list_incident_wafers')

    # These are current read snapshots; historical source availability is unknown.
    captured = datetime.now(timezone.utc).isoformat()
    evidence = {
        'e_lots': {'pages': lot_pages, 'availability_basis': 'current_read_snapshot',
                   'synthetic': True},
        'e_wafers': {'pages': wafer_pages, 'availability_basis': 'current_read_snapshot',
                     'synthetic': True},
    }
    versions = {key: digest(value) for key, value in evidence.items()}
    context = trusted_scope_context([scope_id], captured, versions,
                                    {key: captured for key in evidence})
    ledger = EvidenceLedger(scope={'refs': sorted(context.refs), 'as_of': context.as_of,
                                    'release': release}, allowed_scope_refs=(scope_id,))
    for key, payload in evidence.items():
        ledger.add_evidence(key, payload, source_version=versions[key],
                            expected_revision=ledger.snapshot().revision)
    scope = frozenset({scope_id})
    tasks = [
        Task('lot_inventory', frozenset({'lot_inventory'}), scope,
             (EvidencePin('e_lots', versions['e_lots'], captured, captured),)),
        Task('wafer_inventory', frozenset({'wafer_inventory'}), scope,
             (EvidencePin('e_wafers', versions['e_wafers'], captured, captured),)),
        Task('inventory_summary', frozenset({'summary'}), scope,
             data_dependencies=('lot_inventory', 'wafer_inventory')),
        Task('format_metadata', frozenset({'summary'}), scope,
             control_dependencies=('inventory_summary',)),
    ]
    capabilities = {'lot_reader': ['lot_inventory'], 'wafer_reader': ['wafer_inventory'],
                    'summary_worker': ['summary']}

    def rows(packet, key):
        return [item for page in packet.evidence[key]['payload']['pages'] for item in page['items']]

    def lot_reader(packet):
        return {'recorded_lots': len(rows(packet, 'e_lots')), 'impact_confirmed': False}

    def wafer_reader(packet):
        return {'recorded_wafers': len(rows(packet, 'e_wafers')), 'impact_confirmed': False}

    def wafer_reader_v2(packet):
        items = rows(packet, 'e_wafers')
        return {'recorded_wafers': len(items), 'impact_confirmed': False,
                'unique_wafer_ids': len({item['wafer_id'] for item in items})}

    def summary_worker(packet):
        if packet.task_id == 'format_metadata':
            return {'format_version': 1, 'counts_consumed': False, 'LLM_judged': False}
        return {'recorded_lots': packet.data_parents['lot_inventory']['recorded_lots'],
                'recorded_wafers': packet.data_parents['wafer_inventory']['recorded_wafers'],
                'impact_confirmed': False}

    callbacks = {'lot_reader': lot_reader, 'wafer_reader': wafer_reader,
                 'summary_worker': summary_worker}
    source_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    profiles = {key: digest({'source_sha256': source_sha, 'callback': key, 'version': 1})
                for key in callbacks}
    limits = {key: policy[key] for key in ('max_workers', 'max_parallel_tasks',
                                          'max_shared_calls', 'deadline_seconds')}
    # Parent DB calls and worker callbacks share the configured total call ceiling.
    limits['max_shared_calls'] = min(limits['max_shared_calls'], budget - queries)
    results = []
    for phase in ('initial', 'unchanged_cache', 'changed_worker_profile'):
        if phase == 'changed_worker_profile':
            callbacks = {**callbacks, 'wafer_reader': wafer_reader_v2}
            profiles = {**profiles, 'wafer_reader': digest(
                {'source_sha256': source_sha, 'callback': 'wafer_reader_v2', 'version': 2})}
        result = run_team(tasks, capabilities, context, limits, ledger, callbacks,
                          release=release, provider_versions=profiles)
        results.append({'phase': phase, **asdict(result)})
        if result.failed or result.stale or result.blocked:
            raise ValueError('SYNTHETIC_TEAM_PHASE_INCOMPLETE')
    final = ledger.snapshot()
    return {'status': 'SYNTHETIC_CODE_TEAM_RUN_COMPLETE', 'release': release,
            'config_hash': settings.config_hash, 'selected_incident_number': incident_number,
            'scope_id': scope_id, 'scope_as_of': context.as_of,
            'availability_basis': 'current_read_snapshot_not_historical_availability',
            'lookup_trace': trace, 'parent_db_calls': queries, 'phases': results,
            'total_worker_dispatches': final.dispatch_count,
            'summary': final.tasks['inventory_summary']['output'],
            'worker_profile_change': 'predeclared_synthetic_code_comparison',
            'ledger': asdict(final), 'actual_llm_calls': 0,
            'actual_business_agent_team_connected': False, 'production_verified': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_config_arguments(parser)
    parser.add_argument('--incident-number', required=True)
    parser.add_argument('--output', required=True, help='Fresh absolute JSON inside configured output_root')
    args = parser.parse_args()
    try:
        settings = load_config(args.config, args.overlay)
        target = Path(args.output)
        allowed = Path(settings.data['paths']['output_root']).resolve()
        if (not target.is_absolute() or not target.resolve().is_relative_to(allowed)
                or target.exists()):
            raise ValueError('FRESH_CONFIGURED_OUTPUT_REQUIRED')
        result = run_synthetic(settings, args.incident_number)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open('x', encoding='utf-8') as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
        print(json.dumps({'status': result['status'], 'output': str(target.resolve()),
                          'phases': [{key: row[key] for key in ('phase', 'attempted', 'cached', 'failed', 'stale', 'blocked')}
                                     for row in result['phases']], 'summary': result['summary'],
                          'actual_llm_calls': 0}, ensure_ascii=False))
        return 0
    except (ConfigError, ToolError, ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(2, 'TEAM_CLI_ERROR: ' + type(error).__name__ + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
