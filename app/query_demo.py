"""Query the configured DB. This command performs no model or RAG calls."""
import argparse
import json
from config_loader import ConfigError, add_config_arguments, load_config
from incident_tools import ToolError
from runtime_factory import open_incident_tools

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    add_config_arguments(parser)
    parser.add_argument('--incident-number')
    parser.add_argument('--title', help='Incident title; exact by default')
    parser.add_argument('--title-match',choices=['exact','contains'],default='exact')
    parser.add_argument('--city')
    parser.add_argument('--line')
    parser.add_argument('--department')
    parser.add_argument('--from', dest='period_from', help='Inclusive timestamp with timezone')
    parser.add_argument('--to', dest='period_to', help='Exclusive timestamp with timezone')
    parser.add_argument('--cohort', action='store_true', help='Explicitly analyze a structured-filter population')
    parser.add_argument('--statistics', action='store_true', help='SQL statistics over the full filtered population')
    parser.add_argument('--group-by', action='append', choices=['department','city','line','product_generations','fab_out_failure_codes'])
    parser.add_argument('--comparison-from')
    parser.add_argument('--comparison-to')
    parser.add_argument('--select-incident',action='append',help='Choose internal ID from returned candidates; repeatable')
    parser.add_argument('--all-matches',action='store_true',help='Explicitly include every matched incident')
    parser.add_argument('--include-wafers',action='store_true')
    parser.add_argument('--lot',action='append',help='Restrict wafer results to these Lots within selected incidents')
    parser.add_argument('--all-pages', action='store_true')
    args = parser.parse_args()
    if all(value is None for value in (args.incident_number, args.title, args.city, args.line, args.department, args.period_from)):
        parser.error('Specify an incident or a structured population filter')
    if bool(args.period_from) != bool(args.period_to) or bool(args.comparison_from) != bool(args.comparison_to):
        parser.error('Period boundaries must be supplied together')
    if (args.group_by or args.comparison_from) and not args.statistics:
        parser.error('Grouping and comparison require --statistics')
    if args.statistics and any((args.incident_number, args.title, args.select_incident, args.all_matches,
                                args.include_wafers, args.lot, args.cohort)):
        parser.error('Statistics uses population filters without incident selection or detail listing')
    try:
        settings = load_config(args.config, args.overlay)
        with open_incident_tools(settings) as tool:
            filters = {key: value for key, value in (('city', args.city), ('line', args.line),
                       ('department', args.department)) if value is not None}
            if args.period_from:
                filters['occurred_at'] = {'gte': args.period_from, 'lt': args.period_to}
            if args.statistics:
                comparison = {'gte': args.comparison_from, 'lt': args.comparison_to} if args.comparison_from else None
                result = tool.summarize_incidents('demo-user', filters, group_by=args.group_by, comparison_period=comparison)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                raise SystemExit(0)
            number=args.incident_number
            found = tool.find_incidents('demo-user', incident_number=number,title=args.title,
                                       title_match=args.title_match,city=args.city,line=args.line,
                                       filters=filters if args.department or args.period_from else None,
                                       scope_mode='cohort' if args.cohort else 'candidates')
            scope=found['scope_id']
            if args.select_incident and args.all_matches:raise ToolError('CHOOSE_SELECTION_OR_ALL_MATCHES')
            if args.select_incident or args.all_matches:
                scope=tool.select_incidents('demo-user',scope,args.select_incident or [r['incident_id'] for r in found['data']])['scope_id']
            if found['requires_selection'] and not (args.select_incident or args.all_matches):
                print(json.dumps({'status':'NEEDS_SELECTION','incident_candidates':found,
                                  'next':'Choose --select-incident ID or explicitly --all-matches'},ensure_ascii=False,indent=2))
            else:
                def collect(method,**kwargs):
                    pages=[];offset=0
                    while True:
                        page=method('demo-user',scope,offset=offset,**kwargs);pages.append(page)
                        if not args.all_pages or page.get('next_offset') is None:break
                        offset=page['next_offset']
                    return pages
                result={'config_hash':settings.config_hash,'incident_search':found,'selected_scope_id':scope,
                        'lot_pages':collect(tool.list_incident_lots)}
                if args.include_wafers:result['wafer_pages']=collect(tool.list_incident_wafers,lot_ids=args.lot)
                elif args.lot:raise ToolError('LOT_FILTER_REQUIRES_INCLUDE_WAFERS')
                print(json.dumps(result,ensure_ascii=False,indent=2))
    except (ConfigError, ToolError) as exc:
        parser.exit(2, f'DEMO_ERROR: {exc}\n')
