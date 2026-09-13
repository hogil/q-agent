"""Query the configured DB. This command performs no model or RAG calls."""
import argparse
import json
from config_loader import ConfigError, add_config_arguments, load_config
from incident_tools import ToolError
from runtime_factory import open_incident_tools

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    add_config_arguments(parser)
    parser.add_argument('--incident-number', default='SYN-2026-0001')
    parser.add_argument('--all-pages', action='store_true')
    args = parser.parse_args()
    try:
        settings = load_config(args.config, args.overlay)
        with open_incident_tools(settings) as tool:
            found = tool.find_incidents('demo-user', incident_number=args.incident_number)
            pages, offset = [], 0
            while True:
                page = tool.list_incident_lots('demo-user', found['scope_id'], offset=offset)
                pages.append(page)
                if not args.all_pages or page.get('next_offset') is None:
                    break
                offset = page['next_offset']
            print(json.dumps({'config_hash': settings.config_hash, 'incident': found, 'lot_pages': pages}, ensure_ascii=False, indent=2))
    except (ConfigError, ToolError) as exc:
        parser.exit(2, f'DEMO_ERROR: {exc}\n')
