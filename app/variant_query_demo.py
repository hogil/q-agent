"""Labelled question -> terminology -> incident DB -> separate Lot/Wafer tables.

No Router/Judge/Answer LLM calls or RAG calls are performed. The tool trace records
executed business retrieval only, not simulated LLM decisions.
"""
import argparse
import json
import sqlite3
from pathlib import Path

from config_loader import ConfigError, add_config_arguments, load_config
from incident_tools import ToolError
from runtime_factory import open_incident_tools
from terminology import load_dictionary, normalize_request


def run_query(settings, question, selected=None, dictionary=None, effective_at=None):
    dictionary = dictionary or load_dictionary(settings)
    normalized = normalize_request(question, dictionary, settings.data['runtime']['timezone'], effective_at)
    result = {'notice': 'Synthetic labelled-query demo. No LLM/RAG/production calls.',
              'normalization': normalized, 'tool_trace': [], 'incident_ids': []}
    if normalized['status'] != 'READY':
        return {**result, 'status': normalized['status']}
    try:
        with open_incident_tools(settings) as tool:
            found = tool.find_incidents('variant-demo-user', filters=normalized['filters'])
            result['tool_trace'].append({'tool': 'find_incidents', 'status': found['status'], 'count': len(found['data'])})
            result['incidents'] = found['data']; result['incident_ids'] = [r['incident_id'] for r in found['data']]
            scope = found['scope_id']
            if selected:
                scope = tool.select_incidents('variant-demo-user', scope, selected)['scope_id']
                result['tool_trace'].append({'tool': 'select_incidents', 'count': len(selected)})
                result['incident_ids'] = list(selected)
                result['incidents'] = [r for r in result['incidents'] if r['incident_id'] in selected]
            elif found['requires_selection'] and normalized['request'] in ('lots', 'wafers'):
                return {**result, 'status': 'NEEDS_SELECTION'}
            if not result['incident_ids']:
                return {**result, 'status': 'NO_MATCH'}
            def collect(method, **kwargs):
                pages, offset = [], 0
                while True:
                    page = method('variant-demo-user', scope, offset=offset, **kwargs)
                    pages.append(page)
                    result['tool_trace'].append({'tool': method.__name__, 'status': page['status'],
                                                 'returned': len(page['items']), 'offset': offset})
                    if page['next_offset'] is None:
                        return pages
                    if page['next_offset'] <= offset:
                        raise ToolError('PAGINATION_DID_NOT_ADVANCE')
                    offset = page['next_offset']
            if normalized['request'] in ('lots', 'wafers'):
                result['lot_pages'] = collect(tool.list_incident_lots)
                result['lot_ids'] = sorted({row['lot_id'] for p in result['lot_pages'] for row in p['items']})
            if normalized['request'] == 'wafers':
                result['wafer_pages'] = collect(tool.list_incident_wafers, lot_ids=normalized.get('lot_ids'))
                result['wafer_keys'] = sorted({(r['lot_id'], r['wafer_id']) for p in result['wafer_pages'] for r in p['items']})
            result['status'] = 'MATCHED'
            result['coverage_notice'] = 'MATCHED means query matched, not source completeness. Read page coverage.'
            return result
    except (ConfigError, ToolError) as exc:
        return {**result, 'status': 'TOOL_ERROR', 'error': str(exc)}
    except sqlite3.Error:
        return {**result, 'status': 'TOOL_ERROR', 'error': 'DATABASE_QUERY_FAILED'}


def run_cases(settings):
    corpus = json.loads(Path(settings.data['paths']['variant_cases_file']).read_text())
    dictionary = load_dictionary(settings)
    outcomes = []
    for case in corpus['cases']:
        # Expected labels are used only AFTER execution, never by the resolver/search.
        actual = run_query(settings, case['question'], case.get('selected'), dictionary, case.get('effective_at'))
        expected = case['expected']; errors = []
        for key in ('status', 'incident_ids'):
            if key in expected and actual.get(key) != expected[key]:
                errors.append({'key': key, 'expected': expected[key], 'actual': actual.get(key)})
        for key, field in [('lot_count', 'lot_ids'), ('wafer_count', 'wafer_keys')]:
            if key in expected and len(actual.get(field, [])) != expected[key]:
                errors.append({'key': key, 'expected': expected[key], 'actual': len(actual.get(field, []))})
        if 'filters' in expected and actual['normalization']['filters'] != expected['filters']:
            errors.append({'key': 'filters', 'expected': expected['filters'], 'actual': actual['normalization']['filters']})
        if expected.get('no_business_tools') and actual['tool_trace']:
            errors.append({'key': 'unresolved_request_executed_business_tool'})
        if 'reason' in expected and expected['reason'] not in [i['reason'] for i in actual['normalization']['issues']]:
            errors.append({'key': 'reason', 'expected': expected['reason'], 'actual': actual['normalization']['issues']})
        outcomes.append({'id': case['id'], 'category': case['category'], 'question': case['question'],
                         'passed': not errors, 'errors': errors, 'status': actual['status'],
                         'filters': actual['normalization']['filters'], 'incident_ids': actual['incident_ids'],
                         'lot_count': len(actual.get('lot_ids', [])), 'wafer_count': len(actual.get('wafer_keys', [])),
                         'issues': actual['normalization']['issues'], 'tool_trace': actual['tool_trace']})
    report = {'notice': 'Synthetic finite-grammar regression; not an LLM accuracy benchmark.',
              'dictionary_version': dictionary['version'], 'config_hash': settings.config_hash,
              'total': len(outcomes), 'passed': sum(r['passed'] for r in outcomes),
              'failed': sum(not r['passed'] for r in outcomes), 'results': outcomes}
    target = Path(settings.data['paths']['variant_report_file'])
    if not target.is_relative_to(Path(settings.data['paths']['output_root'])):
        raise ValueError('VARIANT_REPORT_MUST_BE_IN_OUTPUT_ROOT')
    protected = [settings.data['database']['sqlite_file'], settings.data['paths']['variant_cases_file'],
                 settings.data['paths']['terminology_file'], settings.data['paths']['incident_fixture_file'],
                 *settings.source_files]
    if target in [Path(p) for p in protected]:
        raise ValueError('VARIANT_REPORT_OVERLAPS_INPUT')
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    add_config_arguments(parser)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--question'); mode.add_argument('--run-cases', action='store_true')
    parser.add_argument('--select-incident', action='append')
    parser.add_argument('--effective-at')
    args = parser.parse_args()
    try:
        settings = load_config(args.config, args.overlay)
        if args.run_cases:
            report = run_cases(settings)
            print(json.dumps({k: v for k, v in report.items() if k != 'results'}, ensure_ascii=False, indent=2))
            raise SystemExit(1 if report['failed'] else 0)
        print(json.dumps(run_query(settings, args.question, args.select_incident, effective_at=args.effective_at), ensure_ascii=False, indent=2))
    except (ValueError, OSError) as exc:
        parser.exit(2, f'VARIANT_DEMO_ERROR: {exc}\n')
