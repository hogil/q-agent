"""Create connected synthetic incidents, lots, Markdown chunks, SVG maps and CSV trends."""
from __future__ import annotations

import argparse
import csv
import hashlib
import html
import json
import math
import random
import re
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from config_loader import ConfigError, TABLE_FIELDS, add_config_arguments, load_config
from incident_tools import ident

NOTICE = 'ALL SYNTHETIC. No fab data, model inference, BM25/vector retrieval or production action.'


def planned_paths(settings):
    d = settings.data
    count = d['demo']['incident_count']
    paths = [Path(d['database']['sqlite_file']), Path(d['paths']['demo_manifest_file'])]
    for n in range(1, count + 1):
        for source in ('incident', 'internal_documents', 'engineer_notes'):
            paths.append(Path(d['paths']['document_root']) / f'SYN-{n:04}-{source}.md')
        for stage in ('FAB', 'EDS'):
            paths.append(Path(d['paths']['image_root']) / f'SYN-{n:04}-{stage}.svg')
        paths.append(Path(d['paths']['trend_root']) / f'SYN-{n:04}.csv')
    return paths


def generate(settings):
    d = settings.data
    if d['environment'] not in ('demo', 'test') or d['database']['dialect'] != 'sqlite' or d['storage']['backend'] != 'local':
        raise ConfigError('DUMMY_GENERATION_REQUIRES_LOCAL_SQLITE_DEMO_OR_TEST')
    templates = json.loads(Path(d['paths']['incident_fixture_file']).read_text(encoding='utf-8'))
    if not templates:
        raise ConfigError('No synthetic incident templates')
    outputs = planned_paths(settings)
    if len(set(outputs)) != len(outputs):
        raise ConfigError('DUMMY_OUTPUT_COLLISION')
    if any(path.exists() for path in outputs):
        raise ConfigError('DUMMY_OUTPUT_EXISTS: choose a new data/output folder; originals are never overwritten')
    if any(path == Path(d['paths']['incident_fixture_file']) for path in outputs):
        raise ConfigError('DUMMY_OUTPUT_OVERLAPS_INPUT')
    for path in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive DB reservation; never open a configured production file in write mode.
    db_path = Path(d['database']['sqlite_file'])
    with db_path.open('xb'):
        pass
    connection = sqlite3.connect(db_path)
    tables = {name: dict(table, columns={key:value for key,value in table['columns'].items() if value})
              for name, table in d['tables'].items()}
    rows = {name: [] for name in TABLE_FIELDS}
    rng = random.Random(d['demo']['seed'])
    written = []

    def write(path, value):
        with path.open('x', encoding='utf-8', newline='') as stream:
            stream.write(value)
        written.append(path)

    try:
        for name, table in tables.items():
            if not table['columns']:
                raise ConfigError('Dummy fixtures require at least one mapped column per table')
            cols = []
            for key, physical in table['columns'].items():
                dtype = 'INTEGER' if key in ('expected_lot_count', 'affected_wafer_count') else 'TEXT'
                cols.append(f'{ident(physical)} {dtype}')
            connection.execute(f'CREATE TABLE {ident(table["name"])} ({",".join(cols)})')

        for index in range(d['demo']['incident_count']):
            n, template = index + 1, templates[index % len(templates)]
            incident_id, number = f'synthetic-pk-{n:04}', f'SYN-2026-{n:04}'
            parent = incident_id if d['relations']['incident_parent_key'] == 'incident_id' else number
            lot_count = d['demo']['lots_per_incident']
            wafer_count = lot_count * 20
            detail = re.sub(r'\d+개 Lot', f'{lot_count}개 Lot', template['incident_detail'])
            detail = re.sub(r'\d+ Wafer', f'{wafer_count} Wafer', detail)
            start = datetime(2026, 1, 1, tzinfo=ZoneInfo(d['runtime']['timezone'])) + timedelta(days=index)
            generations = template['product_generations']
            if n % 11 == 0:
                generations = None
            elif n % 13 == 0:
                generations = []
            row = dict(incident_id=incident_id, incident_number=number,
                       title=f'[합성 {n:04}] {template["title"]}', city=template['city'],
                       line=f'{template["line_code"]} ({template["line_alias"]})',
                       line_code=template['line_code'], line_alias=template['line_alias'],
                       department=template['department'], occurred_at=start.isoformat(),
                       product_generations=json.dumps(generations) if generations is not None else None,
                       fab_out_failure_codes=json.dumps(template['fab_out_failure_codes']) if template['fab_out_failure_codes'] is not None else None,
                       expected_lot_count=lot_count, affected_wafer_count=wafer_count,
                       incident_detail=detail)
            for key in ('analysis_detail', 'confirmed_cause', 'containment', 'corrective_action', 'verification', 'prevention', 'remaining'):
                row[key] = template[key]
            rows['incident'].append(row)
            for lot_index in range(lot_count):
                # One shared Lot on each even incident tests membership vs unique counts.
                lot_id = f'SYN-LOT-{n:04}-{lot_index + 1:03}'
                if n % 2 == 0 and lot_index == 0:
                    lot_id = f'SYN-LOT-{n - 1:04}-001'
                rows['lot_list'].append(dict(incident_ref=parent, lot_id=lot_id,
                                             product_code='SYNTH_PRODUCT', status='REGISTERED'))
            first_lot = rows['lot_list'][-lot_count]['lot_id']

            for source in ('incident', 'internal_documents', 'engineer_notes'):
                document_id = f'SYN-DOC-{n:04}-{source}'
                path = Path(d['paths']['document_root']) / f'SYN-{n:04}-{source}.md'
                parts = [row['incident_detail'], row['analysis_detail'], row['corrective_action'] + '\n' + row['verification']]
                body = f'# {row["title"]}\n\n{NOTICE}\n\nSource fixture: {source}\n'
                for section, content in enumerate(parts, 1):
                    body += f'\n## Section {section}\n\n{content}\n'
                    rows['document_chunk'].append(dict(chunk_id=f'{document_id}-{section}',
                        document_ref=document_id, location=f'section:{section}', content=content))
                write(path, body)
                rows['incident_document'].append(dict(document_id=document_id, incident_ref=parent,
                    title=row['title'], version='synthetic-v1', storage_ref=str(path), format='markdown', source=source))

            for stage in ('FAB', 'EDS'):
                path = Path(d['paths']['image_root']) / f'SYN-{n:04}-{stage}.svg'
                dots = []
                for x in range(-4, 5):
                    for y in range(-4, 5):
                        if x*x + y*y > 18:
                            continue
                        failure = (x*x + y*y > 12) if index % 2 == 0 else (x % 3 == 0)
                        color = '#dc4c5b' if failure else '#389e86'
                        dots.append(f'<rect x="{128+x*21}" y="{128+y*21}" width="15" height="15" fill="{color}"/>')
                svg = '<svg xmlns="http://www.w3.org/2000/svg" width="280" height="310" viewBox="0 0 280 310">'
                svg += '<rect width="280" height="310" fill="#101827"/><circle cx="136" cy="136" r="108" fill="#202e43"/>'
                svg += ''.join(dots) + f'<text x="12" y="278" fill="white">{html.escape(number)} {stage}</text>'
                svg += '<text x="12" y="298" fill="#ffaabb">SYNTHETIC GRID / NOT MEASURED</text></svg>'
                write(path, svg)
                rows['image_metadata'].append(dict(image_id=f'SYN-IMG-{n:04}-{stage}', incident_ref=parent,
                    lot_id=first_lot, wafer_id=f'{first_lot}-W01', stage=stage,
                    storage_ref=str(path), coordinate_system='SYNTHETIC_GRID_NOT_PHYSICAL'))

            path = Path(d['paths']['trend_root']) / f'SYN-{n:04}.csv'
            pattern = ('normal', 'drift', 'spike', 'variance', 'step', 'missing')[index % 6]
            with path.open('x', encoding='utf-8', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(['timestamp', 'value', 'unit', 'synthetic_scenario'])
                for t in range(d['demo']['trend_points']):
                    value = 10 + rng.gauss(0, 0.2)
                    halfway = d['demo']['trend_points'] // 2
                    if pattern == 'drift': value += max(0, t-halfway) * 0.12
                    if pattern == 'spike' and t == halfway: value += 5
                    if pattern == 'variance' and t >= halfway: value += rng.gauss(0, 1.5)
                    if pattern == 'step' and t >= halfway: value += 2
                    recorded = '' if pattern == 'missing' and halfway <= t < halfway+3 else f'{value:.6f}'
                    writer.writerow([(start + timedelta(hours=t)).isoformat(), recorded, 'synthetic_unit', pattern])
            written.append(path)
            rows['trend_metadata'].append(dict(trend_id=f'SYN-TREND-{n:04}', incident_ref=parent,
                metric='synthetic_measurement', unit='synthetic_unit', storage_ref=str(path), timezone=d['runtime']['timezone']))

        for name, records in rows.items():
            fields = list(tables[name]['columns'])
            sql = f'INSERT INTO {ident(tables[name]["name"])} (' + ','.join(ident(tables[name]['columns'][f]) for f in fields) + ') VALUES (' + ','.join('?' for _ in fields) + ')'
            connection.executemany(sql, [[row.get(field) for field in fields] for row in records])
        connection.commit()
    finally:
        connection.close()

    manifest = {
        'notice': NOTICE, 'config_hash': settings.config_hash, 'seed': d['demo']['seed'],
        'counts': {name: len(records) for name, records in rows.items()},
        'unique_lots': len({r['lot_id'] for r in rows['lot_list']}),
        'source_completeness': d['relations']['source_completeness'],
        'retrieval': 'Source fixtures only; no BM25/vector index or scoring implemented',
        'image_notice': 'Procedural SVG grids. FAB/EDS pairing is synthetic, not a validated coordinate transform.',
        'files': [{'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()} for path in [db_path, *written]],
    }
    write(Path(d['paths']['demo_manifest_file']), json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    add_config_arguments(parser)
    args = parser.parse_args()
    try:
        result = generate(load_config(args.config, args.overlay))
        print(json.dumps({k: v for k, v in result.items() if k != 'files'}, ensure_ascii=False, indent=2))
    except ConfigError as exc:
        parser.exit(2, f'CONFIG_ERROR: {exc}\n')
