"""Read-only, synthetic SQLite column profile for explicit demo/test configs."""
import argparse
import json
import re
import sqlite3
import time
from datetime import date
from pathlib import Path

from config_loader import ConfigError, add_config_arguments, load_config


CORE_TABLES = ('incident', 'lot_list', 'wafer_list', 'incident_document',
               'document_chunk', 'image_metadata', 'trend_metadata')
LOW_CARDINALITY_LIMIT = 50
LONG_VALUE_LIMIT = 120
HIDDEN_VALUE_NAME = re.compile(
    r'(^|_)(id|ids|ref|key|number|serial|lot|wafer|url|uri|storage|content|detail|description|cause|action|note|title|code|codes|label|training_label)(_|$)',
    re.I)


def quote_identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r'[^\W\d]\w*', value):
        raise ValueError('PROFILE_INVALID_IDENTIFIER')
    return '"' + value + '"'


def column_descriptions(skills_root):
    found = {}
    for path in Path(skills_root).rglob('*.json'):
        try:
            document = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            continue
        entity = document.get('logical_entity') if isinstance(document, dict) else None
        columns = document.get('columns') if isinstance(document, dict) else None
        if isinstance(entity, str) and isinstance(columns, dict):
            found.setdefault(entity, {}).update({
                key: spec.get('description') for key, spec in columns.items()
                if isinstance(spec, dict) and isinstance(spec.get('description'), str)})
        sources = document.get('logical_sources') if isinstance(document, dict) else None
        if isinstance(sources, dict):
            for name, source in sources.items():
                columns = source.get('columns') if isinstance(source, dict) else None
                if isinstance(columns, dict):
                    found.setdefault(f'platform.{name}', {}).update({
                        key: spec.get('description') for key, spec in columns.items()
                        if isinstance(spec, dict) and isinstance(spec.get('description'), str)})
    return found


def configured_tables(data):
    tables = data.get('tables', {})
    result = {key: tables[key] for key in CORE_TABLES if key in tables}
    platform_tables = data.get('platform', {}).get('tables', {})
    if isinstance(platform_tables, dict):
        result.update({f'platform.{key}': value for key, value in platform_tables.items()
                       if isinstance(value, dict)})
    return result


def profile_column(db, table_name, physical_column, logical_column, description, top_k,
                   query_timeout_seconds, deadline, array_encoding=None):
    table_sql, column_sql = quote_identifier(table_name), quote_identifier(physical_column)
    base = f'FROM {table_sql}'
    def query(sql, parameters=()):
        deadline[0] = time.monotonic() + query_timeout_seconds
        try:
            return db.execute(sql, parameters).fetchall()
        except sqlite3.OperationalError as exc:
            if str(exc).lower() == 'interrupted':
                raise TimeoutError('PROFILE_QUERY_TIMEOUT') from None
            raise
    row = query(f'SELECT COUNT(*), SUM(CASE WHEN {column_sql} IS NULL THEN 1 ELSE 0 END), '
                f'COUNT(DISTINCT {column_sql}) {base}')[0]
    types = {kind: count for kind, count in query(
        f'SELECT typeof({column_sql}), COUNT(*) {base} GROUP BY typeof({column_sql})')}
    result = {'logical_column': logical_column,
              'description': description or '미확인: logical-schema references에 설명 없음',
              'row_count': row[0], 'null_count': row[1] or 0,
              'distinct_count': row[2], 'sqlite_type_counts': types,
              'top_values': []}
    if array_encoding:
        result['array_encoding'] = array_encoding
        if array_encoding == 'json_text':
            safe_json = (f"CASE WHEN json_valid({column_sql}) THEN "
                         f"CASE WHEN json_type({column_sql})='array' THEN {column_sql} ELSE '[]' END "
                         "ELSE '[]' END")
            result['element_distinct_count'] = query(
                f"SELECT COUNT(DISTINCT j.value) FROM {table_sql} t, json_each({safe_json}) j "
                "WHERE j.type='text'")[0][0]
    hidden = logical_column == 'training_label' or bool(HIDDEN_VALUE_NAME.search(logical_column))
    if not hidden and row[2] <= LOW_CARDINALITY_LIMIT and 'blob' not in types:
        values = query(f'SELECT {column_sql}, COUNT(*) AS n {base} '
                       f'WHERE {column_sql} IS NOT NULL GROUP BY {column_sql} '
                       f'ORDER BY n DESC, CAST({column_sql} AS TEXT) LIMIT ?', (top_k,))
        if all(not isinstance(value, str) or (len(value) <= LONG_VALUE_LIMIT and
               not re.search(r'[0-9-]', value)) for value, _ in values):
            result['top_values'] = [{'value': value, 'count': count} for value, count in values]
    return result


def build_profile(settings, top_k):
    data = settings.data
    if not isinstance(top_k, int) or isinstance(top_k, bool) or not 1 <= top_k <= 5:
        raise ValueError('PROFILE_TOP_K_MUST_BE_1_TO_5')
    if data['environment'] not in ('demo', 'test') or data['database']['dialect'] != 'sqlite':
        raise ConfigError('SYNTHETIC_SQLITE_DEMO_TEST_ONLY')
    db_path = Path(data['database']['sqlite_file'])
    if not db_path.is_file():
        raise ConfigError('DATABASE_FILE_MISSING')
    db = sqlite3.connect(db_path.as_uri() + '?mode=ro', uri=True,
                         timeout=data['database']['connect_timeout_seconds'])
    db.execute('PRAGMA query_only=ON')
    deadline = [time.monotonic() + data['database']['query_timeout_seconds']]
    db.set_progress_handler(lambda: int(time.monotonic() > deadline[0]), 1000)
    descriptions = column_descriptions(data['paths']['skills_root'])
    profiles = []
    try:
        for entity, spec in configured_tables(data).items():
            columns = spec.get('columns', {})
            table_name = spec.get('name', '')
            table = {'entity': entity, 'status': 'ok', 'columns': []}
            try:
                table_sql = quote_identifier(table_name)
                db.execute(f'SELECT 1 FROM {table_sql} LIMIT 0')
            except (ValueError, sqlite3.Error):
                table['status'] = 'unavailable_table'
                profiles.append(table)
                continue
            for logical, physical in columns.items():
                if not physical:
                    table['columns'].append({'logical_column': logical, 'status': 'unmapped',
                                             'description': descriptions.get(entity, {}).get(logical)
                                             or '미확인: logical-schema references에 설명 없음'})
                    continue
                try:
                    info = profile_column(db, table_name, physical, logical,
                                          descriptions.get(entity, {}).get(logical), top_k,
                                          data['database']['query_timeout_seconds'], deadline,
                                          data.get('arrays', {}).get(logical))
                    info['status'] = 'ok'
                except TimeoutError:
                    info = {'logical_column': logical, 'status': 'query_timeout',
                            'description': descriptions.get(entity, {}).get(logical)
                            or '미확인: logical-schema references에 설명 없음'}
                except (ValueError, sqlite3.Error):
                    info = {'logical_column': logical, 'status': 'unavailable_column',
                            'description': descriptions.get(entity, {}).get(logical)
                            or '미확인: logical-schema references에 설명 없음'}
                table['columns'].append(info)
            profiles.append(table)
    finally:
        db.close()
    manifest_root = Path(data['paths']['data_root'])
    manifest_path = manifest_root / 'platform-manifest.json'
    if not manifest_path.is_file():
        manifest_path = manifest_root / 'manifest.json'
    source_cutoff = 'unknown; no database sidecar cutoff found'
    try:
        manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
        for key in ('as_of', 'source_cutoff'):
            value = manifest.get(key) if isinstance(manifest, dict) else None
            if isinstance(value, str):
                try:
                    source_cutoff = date.fromisoformat(value).isoformat()
                    break
                except ValueError:
                    pass
    except (OSError, ValueError):
        pass
    if data.get('platform', {}).get('tabular', {}).get('enabled'):
        from tabular_analysis import profile_platform_tabular
        tabular = profile_platform_tabular(settings)
        if tabular['status'] == 'OK':
            rows = tabular['chip_count']
            profiles.append({'entity': 'platform.tabular_measure', 'status': 'ok', 'columns': [
                {'logical_column': feature['name'], 'physical_column': f"feature_{feature['feature_index']:03d}",
                 'description': feature['semantic_description'], 'status': 'ok', 'row_count': rows,
                 'null_count': feature['missing_count'], 'distinct_count': feature['distinct_count'],
                 'sqlite_type_counts': {'real': rows - feature['missing_count'], 'null': feature['missing_count']},
                 'top_values': [], 'unit': feature['unit'], 'lower_limit': feature['lower_limit'],
                 'upper_limit': feature['upper_limit'], 'source_kind': feature['source_kind']}
                for feature in tabular['features']]})
    return {'status': 'PROFILE_COMPLETE', 'source_cutoff': source_cutoff,
            'profiled_on': date.today().isoformat(), 'synthetic': True,
            'environment': data['environment'], 'config_hash': settings.config_hash,
            'top_k': top_k, 'tables': profiles}


def skill_draft(profile):
    lines = ['---', 'name: synthetic-column-profile',
             'description: 합성 DB 전체 논리 컬럼의 설명·unique·NULL·type 통계를 검토하는 오프라인 Skill 초안.',
             '---', '', '# 합성 데이터 컬럼 프로파일 초안', '',
             f"- 기준일: {profile['profiled_on']}",
             f"- 데이터 기준시점: {profile['source_cutoff']}",
             f"- 설정 해시: `{profile['config_hash']}`",
             '- synthetic: true; 사내 데이터/의미 검증 미완료',
             '- 통계는 값 분포의 관측치이며 컬럼 의미를 확정하지 않는다.',
             '- 배열 원소 distinct count는 배열 원소 종류 수이며 사고/수량 배분이나 원본 완전성을 뜻하지 않는다.', '']
    for table in profile['tables']:
        lines.extend([f"## {table['entity']}", '', f"상태: {table['status']}", ''])
        for column in table['columns']:
            lines.append(f"### {column['logical_column']}")
            lines.append(f"- 설명: {column.get('description') or '미확인'}")
            if column.get('status') == 'ok':
                lines.append(f"- 행수: {column['row_count']}; NULL: {column['null_count']}; "
                             f"고유값 수: {column['distinct_count']}; 타입: `{column['sqlite_type_counts']}`")
                if column['top_values']:
                    lines.append(f"- 저 cardinality 합성 값 예시: `{column['top_values']}`")
                elif column['distinct_count'] > LOW_CARDINALITY_LIMIT:
                    lines.append('- 고유값 수가 많아 값 예시는 생략함.')
            else:
                lines.append(f"- 상태: {column.get('status')}")
            lines.append('')
    return '\n'.join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    add_config_arguments(parser)
    parser.add_argument('--top-k', type=int, default=5)
    parser.add_argument('--full', action='store_true', help='Print per-table and per-column profile JSON')
    parser.add_argument('--output-skill', help='Write a draft Skill artifact; never writes under app/skills')
    args = parser.parse_args()
    if not 1 <= args.top_k <= 5:
        parser.error('--top-k must be in 1..5')
    try:
        settings = load_config(args.config, args.overlay)
        profile = build_profile(settings, args.top_k)
        if args.output_skill:
            destination = Path(args.output_skill).expanduser().resolve()
            skills_root = Path(settings.data['paths']['skills_root']).resolve()
            if destination == skills_root or destination.is_relative_to(skills_root):
                raise ConfigError('OUTPUT_SKILL_MUST_NOT_MODIFY_APP_SKILLS')
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(skill_draft(profile), encoding='utf-8')
        if args.full:
            print(json.dumps(profile, ensure_ascii=False, indent=2))
        else:
            summary = {'status': profile['status'], 'synthetic': True,
                       'environment': profile['environment'], 'config_hash': profile['config_hash'],
                       'tables': len(profile['tables']),
                       'columns': sum(len(t['columns']) for t in profile['tables']),
                       'unavailable_tables': sum(t['status'] != 'ok' for t in profile['tables']),
                       'output_skill_written': bool(args.output_skill)}
            print(json.dumps(summary, ensure_ascii=False))
    except (ConfigError, OSError, sqlite3.Error, ValueError) as exc:
        parser.exit(2, str(exc) + '\n')


if __name__ == '__main__':
    main()
