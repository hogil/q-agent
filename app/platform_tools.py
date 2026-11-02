"""Read-only multimodal evidence over configured synthetic platform tables."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, time, timedelta
import hashlib
import json
import math
from pathlib import Path
from zoneinfo import ZoneInfo

from incident_tools import ToolError, ident
from runtime_factory import open_incident_tools


SOURCES = ('mes', 'test', 'measure', 'failbit', 'sem', 'trend', 'inform')
MATCH_FIELDS = {'mes': ('equipment', 'step', 'recipe', 'status'), 'test': ('stage', 'bin_code'),
                'measure': ('item', 'unit'), 'trend': ('item', 'unit')}


def schema(settings):
    paths = settings.data['paths']
    registry = json.loads(Path(paths['registry_file']).read_text(encoding='utf-8'))
    for folder in registry['topics'].get('platform', []):
        path = Path(paths['skills_root']) / folder / 'references/logical-schema.json'
        if path.is_file():
            document = json.loads(path.read_text(encoding='utf-8'))
            if 'logical_sources' in document:
                return document['logical_sources']
    raise ToolError('PLATFORM_SCHEMA_NOT_REGISTERED')


def cutoff_time(as_of, timezone_name):
    try:
        if not isinstance(as_of, str) or date.fromisoformat(as_of).isoformat() != as_of:
            raise ValueError('canonical ISO date required')
        # Exclusive next local midnight avoids both UTC-day drift and SQLite rounding at time.max.
        return datetime.combine(date.fromisoformat(as_of) + timedelta(days=1), time.min,
                                ZoneInfo(timezone_name)).isoformat()
    except (TypeError, ValueError):
        raise ToolError('INVALID_AS_OF') from None


class PlatformTools:
    def __init__(self, settings, incident_tools):
        self.settings, self.tool = settings, incident_tools
        self.cfg = settings.data.get('platform', {})
        if not self.cfg.get('enabled') or settings.data['environment'] not in ('demo', 'test'):
            raise ToolError('PLATFORM_NOT_CONFIGURED')
        self.definitions = schema(settings)
        if set(self.cfg['tables']) != set(SOURCES):
            raise ToolError('PLATFORM_SOURCE_MAPPING_MISMATCH')
        for source in SOURCES:
            if set(self.cfg['tables'][source]['columns']) != set(self.definitions[source]['columns']):
                raise ToolError('PLATFORM_COLUMN_MAPPING_MISMATCH: ' + source)

    def cutoff(self, as_of):
        return cutoff_time(as_of, self.settings.data['runtime']['timezone'])

    def table(self, source):
        return ident(self.cfg['tables'][source]['name'])

    def col(self, source, field):
        return 'p.' + ident(self.cfg['tables'][source]['columns'][field])

    def base(self, source, ids, as_of):
        if source not in SOURCES or not ids:
            raise ToolError('PLATFORM_INCIDENT_SCOPE_REQUIRED')
        columns = self.cfg['tables'][source]['columns']
        tool = self.tool
        joins = ' FROM ' + self.table(source) + ' p JOIN ' + tool.table('incident') + ' i ON '
        joins += self.col(source, 'incident_id') + '=' + tool.col('incident', 'incident_id', 'i')
        membership = []
        if 'lot_id' in columns:
            relation = tool.m['relationships']['incident_lots']
            membership.append('EXISTS (SELECT 1 FROM ' + tool.table('lot_list') + ' l WHERE '
                + tool.col('lot_list', 'incident_ref', 'l') + '=' + tool.col('incident', relation['parent_key'], 'i')
                + ' AND ' + tool.col('lot_list', 'lot_id', 'l') + '=' + self.col(source, 'lot_id') + ')')
        if 'wafer_id' in columns:
            relation = tool.m['relationships']['incident_wafers']
            if relation['scope'] != 'incident_affected':
                raise ToolError('PLATFORM_REQUIRES_INCIDENT_AFFECTED_WAFERS')
            membership.append('EXISTS (SELECT 1 FROM ' + tool.table('wafer_list') + ' w WHERE '
                + tool.col('wafer_list', 'incident_ref', 'w') + '=' + tool.col('incident', relation['parent_key'], 'i')
                + ' AND ' + tool.col('wafer_list', 'lot_id', 'w') + '=' + self.col(source, 'lot_id')
                + ' AND ' + tool.col('wafer_list', 'wafer_id', 'w') + '=' + self.col(source, 'wafer_id') + ')')
        timestamp = 'timestamp' if source == 'trend' else 'occurred_at'
        joins += ' WHERE ' + self.col(source, 'incident_id') + ' IN (' + ','.join('?' for _ in ids) + ')'
        if membership:
            joins += ' AND ' + ' AND '.join(membership)
        joins += ' AND julianday(' + self.col(source, timestamp) + ')<julianday(?)'
        joins += ' AND julianday(' + self.col(source, 'available_at') + ')<julianday(?)'
        return joins, (*ids, self.cutoff(as_of), self.cutoff(as_of))

    def evidence(self, actor, scope_id, as_of, sources=None, limit=12, measure_features=None):
        ids = self.tool._scope(actor, scope_id)['ids']
        if not ids:
            raise ToolError('PLATFORM_INCIDENT_SCOPE_REQUIRED')
        timestamp = self.tool.col('incident', 'occurred_at', 'i')
        after_cutoff = self.tool.db.execute('SELECT 1 FROM ' + self.tool.table('incident') + ' i WHERE '
            + self.tool.col('incident', 'incident_id', 'i') + ' IN (' + ','.join('?' for _ in ids)
            + ') AND julianday(' + timestamp + ')>=julianday(?) LIMIT 1', (*ids, self.cutoff(as_of))).fetchone()
        if after_cutoff:
            raise ToolError('PLATFORM_INCIDENT_AFTER_CUTOFF')
        if sources is None:
            sources = list(SOURCES)
        if measure_features is not None and ('measure' not in sources or not self.cfg.get('tabular', {}).get('enabled')):
            raise ToolError('MEASURE_FEATURE_QUERY_REQUIRES_TABULAR_SOURCE')
        if (not isinstance(sources, list) or not sources or len(set(sources)) != len(sources)
                or any(source not in SOURCES for source in sources) or type(limit) is not int or not 1 <= limit <= 20):
            raise ToolError('INVALID_PLATFORM_QUERY')
        sections = {}
        for source in sources:
            base, params = self.base(source, ids, as_of)
            fields = [field for field in self.cfg['tables'][source]['columns'] if field != 'training_label']
            select = 'SELECT DISTINCT ' + ','.join(self.col(source, field) + ' AS ' + ident(field) for field in fields)
            count = self.tool.db.execute('SELECT COUNT(*) FROM (' + select + base + ')', params).fetchone()[0]
            rows = [dict(row) for row in self.tool.db.execute(
                select + base + ' ORDER BY ' + self.col(source, 'record_id') + ' LIMIT ?', (*params, limit))]
            sections[source] = {'status': 'OK' if count else 'NO_MATCH', 'count': count,
                                'rows': rows, 'truncated': count > len(rows)}
        if 'failbit' in sections:
            base, params = self.base('failbit', ids, as_of)
            keys = ('incident_id', 'lot_id', 'wafer_id', 'chip_id')
            members = {tuple(row) for row in self.tool.db.execute('SELECT DISTINCT '
                + ','.join(self.col('failbit', key) for key in keys) + base, params)}
            manifest_path = Path(self.settings.data['paths']['data_root']) / 'platform-manifest.json'
            manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
            sections['failbit']['assets'] = [asset for asset in manifest.get('assets', [])
                if asset.get('stage') == 'EDS_FAILBIT' and tuple(asset.get(key) for key in keys) in members][:4]
        analyses = {}
        if 'measure' in sources and self.cfg.get('tabular', {}).get('enabled'):
            from tabular_analysis import analyze_platform_case
            analyses['tabular_analysis'] = analyze_platform_case(self.settings, list(ids), as_of, feature_names=measure_features)
        if 'failbit' in sources and self.cfg.get('map_analysis', {}).get('enabled'):
            from map_analysis import analyze_demo_case
            analyses['map_analysis'] = {'cases': [analyze_demo_case(self.settings, item, as_of) for item in list(ids)[:5]],
                                        'incident_count': len(ids), 'truncated': len(ids) > 5}
        return {'status': 'PARTIAL' if any(row['truncated'] or not row['count'] for row in sections.values()) else 'OK',
                'synthetic': self.settings.data['environment'] in ('demo', 'test'),
                'scope': {'incident_ids': list(ids), 'as_of': as_of}, 'sections': sections,
                'summaries': self.summaries(ids, as_of, sources),
                'model_observations': self.model_observations(ids, as_of, sources),
                'cross_modal_alignment': self.chip_alignment(ids, as_of, sources), **analyses,
                'source_ref': {'logical_entity': 'platform', 'config_hash': self.settings.config_hash},
                'limitations': ['BOUNDED_SOURCE_ROWS', 'OBSERVATIONS_NOT_CONFIRMED_CAUSE',
                                'EVENT_AND_AVAILABILITY_CUTOFF_NOT_DATABASE_SNAPSHOT']}

    def chip_alignment(self, ids, as_of, sources):
        sets = {}
        keys = ('incident_id', 'lot_id', 'wafer_id', 'chip_id')
        for source in ('measure', 'failbit', 'sem'):
            if source not in sources:
                continue
            base, params = self.base(source, ids, as_of)
            select = ','.join(self.col(source, key) for key in keys)
            sets[source] = {tuple(row) for row in self.tool.db.execute('SELECT DISTINCT ' + select + base, params)}
            if source == 'measure':
                condition = (' AND (' + self.col(source, 'value') + '<' + self.col(source, 'lower_limit')
                             + ' OR ' + self.col(source, 'value') + '>' + self.col(source, 'upper_limit') + ')')
                sets['legacy_measure_out_of_spec'] = {tuple(row) for row in self.tool.db.execute(
                    'SELECT DISTINCT ' + select + base + condition, params)}
        overlaps = {a + '_and_' + b: len(sets[a] & sets[b]) for a, b in (
            ('legacy_measure_out_of_spec', 'failbit'), ('legacy_measure_out_of_spec', 'sem'), ('failbit', 'sem'))
            if a in sets and b in sets}
        return {'grain': 'distinct incident/lot/wafer/chip', 'chip_counts': {key: len(value) for key, value in sets.items()},
                'overlap_chip_counts': overlaps, 'keys': list(keys),
                'limitations': ['CO_OBSERVATION_NOT_CAUSE', 'LEGACY_MEASURE_LIMITS_ARE_SEPARATE_FROM_MULTIVARIATE_SCORE']}

    def trend_series(self, ids, as_of):
        base, params = self.base('trend', ids, as_of)
        fields = ('incident_id', 'item', 'unit', 'timestamp', 'value')
        select = ','.join(self.col('trend', field) + ' AS ' + ident(field) for field in fields)
        grouped = {}
        for row in self.tool.db.execute('SELECT ' + select + base + ' ORDER BY '
                + self.col('trend', 'timestamp') + ',' + self.col('trend', 'record_id') + ' LIMIT 4096', params):
            key = (row['incident_id'], row['item'], row['unit'])
            grouped.setdefault(key, []).append({'timestamp': row['timestamp'], 'value': row['value']})
        return [{'incident_id': key[0], 'item': key[1], 'unit': key[2], 'points': values}
                for key, values in grouped.items()]

    def model_observations(self, ids, as_of, sources):
        if self.settings.data['environment'] not in ('demo', 'test'):
            return []
        from platform_models import model_status, predict, sem_features, trend_features
        status = model_status(self.settings)
        trained = {model['modality']: model for model in status['models'] if model['status'] == 'READY'}
        results = []
        allowed = set()
        for modality in ('sem', 'trend'):
            if modality not in sources or modality not in trained:
                continue
            trained_as_of = trained[modality].get('training_data_as_of', 'unknown')
            if trained_as_of == 'unknown' or as_of < trained_as_of:
                results.append({'modality': modality, 'status': 'UNAVAILABLE_AS_OF',
                                'limitation': 'Checkpoint training data cutoff is later than or unknown for this query.'})
            else:
                allowed.add(modality)
        if 'sem' in allowed:
            from io import BytesIO
            from PIL import Image
            base, params = self.base('sem', ids, as_of)
            fields = ('asset_id', 'storage_ref', 'sha256')
            select = ','.join(self.col('sem', field) + ' AS ' + ident(field) for field in fields)
            for row in self.tool.db.execute('SELECT ' + select + base + ' ORDER BY '
                    + self.col('sem', 'record_id') + ' LIMIT 4', params):
                root = Path(self.settings.data['paths']['image_root']).resolve()
                path = (root / row['storage_ref']).resolve()
                if not path.is_relative_to(root):
                    raise ToolError('INVALID_ASSET_PATH')
                content = path.read_bytes()
                if hashlib.sha256(content).hexdigest() != row['sha256']:
                    raise ToolError('ASSET_HASH_MISMATCH')
                with Image.open(BytesIO(content)) as image:
                    features = sem_features(image)
                results.append({**predict(self.settings, 'sem', features), 'asset_id': row['asset_id'],
                                'case_may_be_in_training': True})
        if 'trend' in allowed:
            for series in self.trend_series(ids, as_of):
                points = series['points']
                if len(points) < 8:
                    continue
                values = [point['value'] for point in points]
                timestamps = [datetime.fromisoformat(point['timestamp']).timestamp() for point in points]
                results.append({**predict(self.settings, 'trend', trend_features(values, timestamps)),
                                'item': series['item'], 'unit': series['unit'],
                                'case_may_be_in_training': True})
        return results

    def summaries(self, ids, as_of, sources):
        result = {}
        for source in sources:
            base, params = self.base(source, ids, as_of)
            c = lambda field: self.col(source, field)
            if source == 'test':
                select = (f'{c("stage")} AS stage,SUM({c("fail_count")}) AS failed,'
                          f'SUM({c("tested_count")}) AS tested,COUNT(*) AS wafer_tests')
                group = [c('stage')]
            elif source == 'measure':
                select = (f'{c("item")} AS item,{c("unit")} AS unit,COUNT(*) AS samples,'
                          f'AVG({c("value")}) AS mean,MIN({c("value")}) AS min,MAX({c("value")}) AS max,'
                          f'SUM(CASE WHEN {c("value")}<{c("lower_limit")} OR {c("value")}>{c("upper_limit")} THEN 1 ELSE 0 END) AS outside_limits')
                group = [c('item'), c('unit')]
            elif source == 'trend':
                select = (f'{c("item")} AS item,{c("unit")} AS unit,COUNT(*) AS samples,'
                          f'AVG({c("value")}) AS mean,MIN({c("value")}) AS min,MAX({c("value")}) AS max')
                group = [c('item'), c('unit')]
            elif source == 'mes':
                select = f'{c("status")} AS status,COUNT(*) AS events,AVG({c("queue_hours")}) AS mean_queue_hours'
                group = [c('status')]
            elif source == 'failbit':
                select = (f'{c("test_item")} AS test_item,COUNT(*) AS observed_bit_sites,'
                          f'SUM({c("fail_count")}) AS failed_operations')
                group = [c('test_item')]
            elif source == 'sem':
                select = (f'{c("recipe")} AS recipe,{c("orientation")} AS orientation,'
                          f'{c("pixel_size_nm")} AS synthetic_pixel_size_nm,COUNT(*) AS images,'
                          f'AVG({c("edge_density")}) AS mean_edge_density,AVG({c("contrast")}) AS mean_contrast')
                group = [c('recipe'), c('orientation'), c('pixel_size_nm')]
            else:
                select = f'{c("version")} AS version,COUNT(*) AS notes'
                group = [c('version')]
            rows = [dict(row) for row in self.tool.db.execute('SELECT ' + select + base + ' GROUP BY ' + ','.join(group), params)]
            if source == 'test':
                for row in rows:
                    row['yield_pct_from_counts'] = (100 * (1 - row['failed'] / row['tested'])) if row['tested'] else None
            if source == 'failbit':
                for row in rows:
                    row['chips'] = self.tool.db.execute('SELECT COUNT(*) FROM (SELECT DISTINCT '
                        + ','.join(c(key) for key in ('incident_id', 'lot_id', 'wafer_id', 'chip_id'))
                        + base + ' AND ' + c('test_item') + '=?)', (*params, row['test_item'])).fetchone()[0]
            result[source] = rows
        return result

    def descriptors(self, ids, as_of):
        """Aggregate observed measurements only; synthetic training labels are excluded."""
        result = defaultdict(dict)
        specs = {'sem': [('edge_density', 1), ('contrast', 1)],
                 'measure': [('value', 10)], 'failbit': [('bit_x', 32), ('bit_y', 32), ('fail_count', 64)],
                 'test': [('yield_pct', 100), ('fail_count', 64)],
                 'mes': [('queue_hours', 24)], 'trend': [('value', 100)]}
        for source, features in specs.items():
            base, params = self.base(source, ids, as_of)
            grouping = {'measure': 'item', 'test': 'stage', 'trend': 'item'}.get(source)
            select = self.col(source, 'incident_id') + ' AS incident_id'
            if grouping:
                select += ',' + self.col(source, grouping) + ' AS feature_group'
            for index, (field, _) in enumerate(features):
                column = self.col(source, field)
                select += f',AVG({column}) AS avg_{index}, AVG({column}*{column}) AS square_{index}'
            sql = 'SELECT ' + select + base + ' GROUP BY ' + self.col(source, 'incident_id')
            if grouping:
                sql += ',' + self.col(source, grouping)
            for row in self.tool.db.execute(sql, params):
                vector = [1.0]
                for index, (_, scale) in enumerate(features):
                    value = row['avg_' + str(index)]
                    if value is None or not math.isfinite(value):
                        continue
                    deviation = math.sqrt(max(0, row['square_' + str(index)] - value * value))
                    vector.extend((value / scale, deviation / scale))
                key = source + (':' + str(row['feature_group']) if grouping else '')
                result[row['incident_id']][key] = vector
        return dict(result)

    def history(self, actor, scope_id, as_of, top_k=5):
        ids = self.tool._scope(actor, scope_id)['ids']
        if len(ids) != 1 or type(top_k) is not int or not 1 <= top_k <= 10:
            raise ToolError('PLATFORM_HISTORY_REQUIRES_SINGLE_INCIDENT')
        tool = self.tool
        timestamp = tool.col('incident', 'occurred_at', 'i')
        current = tool.db.execute('SELECT ' + timestamp + ' FROM ' + tool.table('incident')
                                  + ' i WHERE ' + tool.col('incident', 'incident_id', 'i') + '=?', ids).fetchone()[0]
        if datetime.fromisoformat(current) >= datetime.fromisoformat(self.cutoff(as_of)):
            raise ToolError('PLATFORM_INCIDENT_AFTER_CUTOFF')
        fields = ('incident_id', 'incident_number', 'title', 'occurred_at')
        select = ','.join(tool.col('incident', key, 'i') + ' AS ' + ident(key) for key in fields)
        rows = [dict(row) for row in tool.db.execute('SELECT ' + select + ' FROM ' + tool.table('incident')
                + ' i WHERE julianday(' + timestamp + ')<julianday(?) AND julianday(' + timestamp
                + ')<julianday(?) ORDER BY ' + timestamp + ' DESC LIMIT 500', (current, self.cutoff(as_of)))]
        if not rows:
            return {'status': 'NO_MATCH', 'items': [], 'scope': {'incident_ids': list(ids), 'as_of': as_of}}
        vectors = self.descriptors([*ids, *(row['incident_id'] for row in rows)], as_of)
        target = vectors.get(ids[0], {})
        matches = []
        for row in rows:
            observed = vectors.get(row['incident_id'], {})
            common = sorted(target.keys() & observed.keys())
            similarities = []
            for key in common:
                left, right = target[key], observed[key]
                norm = math.sqrt(sum(x*x for x in left) * sum(x*x for x in right))
                if len(left) == len(right) and norm:
                    similarities.append(sum(x*y for x, y in zip(left, right)) / norm)
            if similarities:
                matches.append({**row, 'similarity': round(sum(similarities) / len(similarities), 6),
                                'modalities': common, 'synthetic': True})
        matches.sort(key=lambda row: (-row['similarity'], row['incident_id']))
        return {'status': 'OK' if matches else 'NO_MATCH', 'items': matches[:top_k],
                'scope': {'incident_ids': list(ids), 'as_of': as_of},
                'candidate_count': len(rows), 'candidate_limit': 500,
                'method': 'mean_cosine_of_unit_scaled_observed_descriptors',
                'limitations': ['SIMILARITY_NOT_CAUSE_OR_PROBABILITY', 'PAST_REFERENCES_NOT_AFFECTED_SCOPE',
                                'SYNTHETIC_FEATURE_SCALES_NOT_SITE_CALIBRATION']}


class PlatformService:
    """Workbench facade. Every case query starts with the incident Adapter."""
    def __init__(self, settings):
        self.settings = settings

    def ready(self):
        return bool(self.settings.data.get('platform', {}).get('enabled')
                    and Path(self.settings.data['database']['sqlite_file']).is_file())

    def analyze(self, body):
        """Run the actual Router/Tool/Judge/Answer workflow over synthetic sources."""
        from agent import run
        from uuid import uuid4
        if not isinstance(body, dict) or set(body) - {'incident_number', 'as_of', 'question'}:
            raise ToolError('INVALID_PLATFORM_ANALYSIS_REQUEST')
        number, as_of = body.get('incident_number'), body.get('as_of')
        if not isinstance(number, str) or not number.strip() or len(number) > 256:
            raise ToolError('EXPLICIT_INCIDENT_NUMBER_REQUIRED')
        cutoff_time(as_of, self.settings.data['runtime']['timezone'])
        question = body.get('question') or (
            'EDS/FAB_OUT 수율과 chip별 다변량 Measure, FBM/Failbit, SEM, raw Trend, MES, Inform 및 과거 사례를 '
            '복합 분석하라. 전기 tabular 이상, wafer local 영역, chip 내부 형상, chip 간 반복성은 구분하라. '
            'feature 수와 chip/bit 수, 관측·가설·반대 근거·미확인 사항을 근거 ID로 연결하라.')
        if not isinstance(question, str) or not question.strip() or len(question) > 12000:
            raise ToolError('INVALID_PLATFORM_QUESTION')
        trace_root = Path(self.settings.data['paths']['output_root']) / 'llm-traces'
        trace_root.mkdir(parents=True, exist_ok=True)
        trace_id = uuid4().hex
        with (trace_root / (trace_id + '.jsonl')).open('x', encoding='utf-8') as trace:
            def emit(event):
                trace.write(json.dumps(event, ensure_ascii=False) + '\n')
                trace.flush()
            result = run(self.settings, question, 'platform-workbench', request_scope='incident',
                         incident_number=number, as_of=as_of, topics=['incident_search', 'platform'],
                         requested_tools=('get_platform_evidence', 'search_platform_history'),
                         related_search=False, emit=emit)
        events = result.get('events', [])
        response = {key: result[key] for key in ('status', 'answer', 'claims', 'limitations', 'as_of', 'platform_facts', 'llm_interpretation', 'investigation_order', 'answer_generation_mode') if key in result}
        response.update(synthetic=True, incident_number=number, trace_id=trace_id,
                        llm_called=any(event['event'] == 'llm_output' for event in events),
                        llm_metrics={'calls': result['llm_calls'], 'tools': result['tool_calls'],
                                     'by_role': [{'role': event['role'], **event['metrics']} for event in events
                                                 if event['event'] in ('llm_output', 'llm_metrics') and event.get('metrics')]},
                        tool_calls=[{'tool': entry['source'], 'evidence_id': entry['id'],
                                     'status': entry['result'].get('status')} for entry in result['evidence']],
                        evidence=[{'id': entry['id'], 'source': entry['source'],
                                   'status': entry['result'].get('status')} for entry in result['evidence']])
        for entry in result['evidence']:
            if entry['source'] == 'get_platform_evidence':
                for key in ('tabular_analysis', 'map_analysis'):
                    if key in entry['result']:
                        response[key] = entry['result'][key]
        (trace_root / (trace_id + '.json')).write_text(json.dumps(response, ensure_ascii=False, indent=2), encoding='utf-8')
        return response

    def catalog(self, q='', offset=0, limit=40, field=None, value=None):
        if not self.ready():
            return {'status': 'UNAVAILABLE', 'synthetic': True, 'counts': {}, 'incidents': [],
                    'next_offset': None, 'notice': '합성 통합 DB를 먼저 준비하세요.'}
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 100:
            raise ToolError('INVALID_PAGINATION')
        if not isinstance(q, str) or len(q) > 256:
            raise ToolError('INVALID_PLATFORM_SEARCH')
        if bool(field) != bool(value) or (field and (not isinstance(value, str) or len(value) > 256)):
            raise ToolError('INVALID_CONFIRMED_VALUE_FILTER')
        with open_incident_tools(self.settings) as tool:
            fields = list(tool.m['entities']['incident']['columns'])
            select = ','.join(tool.col('incident', key, 'i') + ' AS ' + ident(key) for key in fields)
            where, params = '', []
            if field:
                source, name = field.split('.', 1) if '.' in field else ('incident', field)
                if source == 'incident' and name in self.settings.data['value_matching']['fields']:
                    column = tool.col('incident', name, 'i')
                    if name in ('product_generations', 'fab_out_failure_codes'):
                        where = ' WHERE EXISTS (SELECT 1 FROM json_each(' + column + ') candidate WHERE candidate.value=?)'
                    else:
                        where = ' WHERE ' + column + '=?'
                elif source in MATCH_FIELDS and name in MATCH_FIELDS[source]:
                    mapping = self.settings.data['platform']['tables'][source]
                    where = (' WHERE EXISTS (SELECT 1 FROM ' + ident(mapping['name']) + ' candidate WHERE candidate.'
                             + ident(mapping['columns']['incident_id']) + '=' + tool.col('incident', 'incident_id', 'i')
                             + ' AND candidate.' + ident(mapping['columns'][name]) + '=?)')
                else:
                    raise ToolError('UNSUPPORTED_CONFIRMED_VALUE_FIELD')
                params = [value]
            elif q.strip():
                where = ' WHERE ' + ' OR '.join('instr(lower(' + tool.col('incident', key, 'i') + '),lower(?))>0'
                          for key in ('incident_number', 'title', 'city', 'line', 'department'))
                params = [q.strip()] * 5
            rows = [dict(row) for row in tool.db.execute('SELECT ' + select + ' FROM '
                    + tool.table('incident') + ' i' + where + ' ORDER BY '
                    + tool.col('incident', 'occurred_at', 'i') + ' DESC,' + tool.col('incident', 'incident_id', 'i')
                    + ' LIMIT ? OFFSET ?', (*params, limit + 1, offset))]
            counts = {entity: tool.db.execute('SELECT COUNT(*) FROM ' + tool.table(entity)).fetchone()[0]
                      for entity in ('incident', 'lot_list', 'wafer_list')}
            for name, table in self.settings.data['platform']['tables'].items():
                counts[name] = tool.db.execute('SELECT COUNT(*) FROM ' + ident(table['name'])).fetchone()[0]
        return {'status': 'OK', 'synthetic': True, 'counts': counts, 'incidents': rows[:limit],
                'default_as_of': datetime.now(ZoneInfo(self.settings.data['runtime']['timezone'])).date().isoformat(),
                'next_offset': offset + limit if len(rows) > limit else None,
                'filter': {'field': field, 'value': value} if field else None}

    def case(self, number, as_of=None):
        zone = self.settings.data['runtime']['timezone']
        as_of = as_of or datetime.now(ZoneInfo(zone)).date().isoformat()
        boundary = cutoff_time(as_of, zone)
        with open_incident_tools(self.settings) as tool:
            found = tool.find_incidents('platform-workbench', incident_number=number,
                                       fields=['incident_detail', 'analysis_detail', 'confirmed_cause'])
            if len(found['data']) != 1:
                raise ToolError('PLATFORM_EXPLICIT_SINGLE_INCIDENT_REQUIRED')
            incident = found['data'][0]
            if datetime.fromisoformat(incident['occurred_at']) >= datetime.fromisoformat(boundary):
                raise ToolError('PLATFORM_INCIDENT_AFTER_CUTOFF')
            scope = found['scope_id']
            tool.list_incident_lots('platform-workbench', scope, page_size=1)
            platform = PlatformTools(self.settings, tool)
            evidence = platform.evidence('platform-workbench', scope, as_of)
            history = platform.history('platform-workbench', scope, as_of)
            descriptors = platform.descriptors([incident['incident_id']], as_of).get(incident['incident_id'], {})
            findings = []
            for source, section in evidence['sections'].items():
                findings.append({'source': source, 'observation': f"조회 가능 {section['count']}행; 화면에는 {len(section['rows'])}행 표시",
                                 'limitation': '합성 관측이며 원인 확정 근거가 아닙니다.'})
            for row in evidence['summaries'].get('test', []):
                value = row['yield_pct_from_counts']
                if value is not None:
                    findings.append({'source': 'test', 'observation': f"{row['stage']} 수율 {value:.2f}% ({row['tested']} tested, {row['failed']} failed)",
                                     'limitation': '검사 단계별 분모를 사용하며 다른 단계 수량을 합치지 않습니다.'})
            for row in evidence['summaries'].get('measure', []):
                findings.append({'source': 'measure', 'observation': f"{row['item']} 평균 {row['mean']:.4g} {row['unit']}; 규격 밖 {row['outside_limits']}/{row['samples']}",
                                 'limitation': '같은 Chip의 검사 결과와 원인 관계는 추가 검토가 필요합니다.'})
            result = {**evidence, 'incident': incident, 'history': history['items'], 'findings': findings,
                      'coverage': [{'source': source, 'count': section['count'],
                                    'returned_count': len(section['rows']), 'status': section['status']}
                                   for source, section in evidence['sections'].items()],
                      'descriptors': descriptors, 'history_method': history.get('method'),
                      'trend_series': platform.trend_series([incident['incident_id']], as_of),
                      'llm_called': False}
        try:
            from platform_models import model_status
            result['model_status'] = model_status(self.settings)
        except ImportError:
            result['model_status'] = {'status': 'NOT_TRAINED', 'synthetic': True, 'models': []}
        return result

    def match(self, question):
        from terminology import match_values
        if not isinstance(question, str) or not question.strip() or len(question) > 12000:
            raise ToolError('INVALID_QUESTION')
        with open_incident_tools(self.settings) as tool:
            result = tool.match_incident_values('platform-workbench', question)
            values, coverage = {}, []
            for source, fields in MATCH_FIELDS.items():
                for field in fields:
                    column = 'p.' + ident(self.settings.data['platform']['tables'][source]['columns'][field])
                    table = ident(self.settings.data['platform']['tables'][source]['name'])
                    rows = tool.db.execute('SELECT DISTINCT ' + column + ' FROM ' + table + ' p LIMIT 501').fetchall()
                    key = source + '.' + field
                    coverage.append({'field': key, 'status': 'checked' if len(rows) <= 500 else 'distinct_limit_exceeded'})
                    if len(rows) <= 500:
                        values[key] = [row[0] for row in rows if isinstance(row[0], str)]
            matching = self.settings.data['value_matching']
            matched = match_values(question, values, 20, fuzzy_enabled=matching.get('fuzzy_enabled', False),
                                   fuzzy_threshold=matching.get('fuzzy_threshold', .85))
        candidates = result['candidates'] + matched['candidates']
        from column_profile import column_descriptions
        descriptions = column_descriptions(self.settings.data['paths']['skills_root'])
        for candidate in candidates:
            source, field = candidate['field'].split('.', 1) if '.' in candidate['field'] else ('incident', candidate['field'])
            entity = source if source == 'incident' else 'platform.' + source
            candidate['description'] = descriptions.get(entity, {}).get(field, '미확인 컬럼')
        return {'candidates': candidates[:20], 'truncated': len(candidates) > 20 or result['truncated'] or matched['truncated'],
                'coverage': result['coverage'] + coverage,
                'notice': '후보는 필터가 아닙니다. 오타와 다중 컬럼 후보는 명시적 확인이 필요합니다.'}

    def measure_catalog(self, question=''):
        from tabular_analysis import profile_platform_tabular
        from terminology import match_values
        if not isinstance(question, str) or len(question) > 256:
            raise ToolError('INVALID_MEASURE_CATALOG_QUERY')
        profile = profile_platform_tabular(self.settings)
        features = profile.get('features', [])
        matching = self.settings.data['value_matching']
        matched = match_values(question, {'measure_features': [feature['name'] for feature in features]}, 10,
                               fuzzy_enabled=matching.get('fuzzy_enabled', False),
                               fuzzy_threshold=matching.get('fuzzy_threshold', .85)) if question.strip() else {'candidates': []}
        chosen = {candidate['value'] for candidate in matched['candidates']}
        result = [feature for feature in features if not question.strip() or feature['name'] in chosen
                  or question.casefold() in feature['name'].casefold()]
        return {key: profile[key] for key in ('status', 'synthetic', 'feature_count', 'source_feature_count', 'dummy_feature_count')
                if key in profile} | {'features': result[:128], 'candidates': matched['candidates'],
                                      'notice': 'Feature 정의 조회이며 사고 필터가 아닙니다. 오타 후보는 확인 후 exact name을 사용합니다.'}

    def asset(self, asset_id):
        if not isinstance(asset_id, str) or not asset_id or len(asset_id) > 128:
            raise ToolError('INVALID_ASSET_ID')
        with open_incident_tools(self.settings) as tool:
            source = self.settings.data['platform']['tables']['sem']
            rows = tool.db.execute('SELECT ' + ident(source['columns']['storage_ref']) + ','
                   + ident(source['columns']['sha256']) + ' FROM ' + ident(source['name'])
                   + ' WHERE ' + ident(source['columns']['asset_id']) + '=? LIMIT 2', (asset_id,)).fetchall()
        if len(rows) != 1:
            manifest = json.loads((Path(self.settings.data['paths']['data_root'])
                                   / 'platform-manifest.json').read_text(encoding='utf-8'))
            assets = [asset for asset in manifest.get('assets', []) if asset.get('asset_id') == asset_id]
            if len(assets) != 1 or assets[0].get('stage') != 'EDS_FAILBIT':
                raise ToolError('ASSET_NOT_FOUND_OR_AMBIGUOUS')
            rows = [(assets[0]['storage_ref'], assets[0]['sha256'])]
        root = Path(self.settings.data['paths']['image_root']).resolve()
        path = (root / rows[0][0]).resolve()
        if not path.is_relative_to(root) or path.suffix.lower() != '.png':
            raise ToolError('INVALID_ASSET_PATH')
        content = path.read_bytes()
        if hashlib.sha256(content).hexdigest() != rows[0][1]:
            raise ToolError('ASSET_HASH_MISMATCH')
        return content

    def profile(self):
        from column_profile import build_profile
        path = Path(self.settings.data['database']['sqlite_file'])
        key = (path.stat().st_mtime_ns, path.stat().st_size, self.settings.config_hash)
        tabular = self.settings.data.get('platform', {}).get('tabular', {})
        if tabular.get('enabled'):
            derived = Path(self.settings.data['paths']['data_root']) / tabular['subdirectory'] / 'chip_tabular.sqlite'
            key += (derived.stat().st_mtime_ns if derived.is_file() else None,)
        if getattr(self, '_profile_key', None) != key:
            profile = build_profile(self.settings, 5)
            self._profile = {'synthetic': True, 'tables': [
                {'entity': table['entity'], 'rows': next((column.get('row_count', 0) for column in table['columns']), 0),
                 'columns': [{**column, 'field': column['logical_column']} for column in table['columns']]}
                for table in profile['tables']]}
            self._profile_key = key
        return self._profile

    def models(self):
        from platform_models import model_status
        return model_status(self.settings)


if __name__ == '__main__':
    import argparse
    from config_loader import add_config_arguments, load_config
    parser = argparse.ArgumentParser(description=__doc__)
    add_config_arguments(parser)
    parser.add_argument('--incident-number')
    parser.add_argument('--as-of')
    parser.add_argument('--question', help='Only return DB-value candidates; no LLM call')
    args = parser.parse_args()
    try:
        service = PlatformService(load_config(args.config, args.overlay))
        result = service.match(args.question) if args.question else (
            service.case(args.incident_number, args.as_of) if args.incident_number else service.catalog())
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ToolError, ValueError, OSError) as exc:
        parser.exit(2, 'PLATFORM_ERROR: ' + str(exc) + '\n')
