"""Full-population SQL statistics with bounded detail scopes and display groups."""
import copy
import secrets
import time
from datetime import date, timedelta

from incident_filters import ARRAY_FILTER_FIELDS, predicates
from incident_tools import ToolError, ident

GROUP_FIELDS = {'department', 'city', 'line', 'product_generations', 'fab_out_failure_codes'}
QUANTITIES = ('expected_lot_count', 'affected_wafer_count')


def summarize(tool, actor, filters, group_by, comparison_period, top_k, as_of):
    if not isinstance(actor, str) or not actor.strip():
        raise ToolError('INVALID_ACTOR')
    if not isinstance(filters, dict) or not filters or set(filters) & {'incident_number', 'title_terms'}:
        raise ToolError('STATISTICS_REQUIRES_COHORT_FILTERS')
    group_by = ['department'] if group_by is None else group_by
    if (not isinstance(group_by, list) or not 1 <= len(group_by) <= 3
            or any(not isinstance(field, str) or field not in GROUP_FIELDS for field in group_by)
            or len(set(group_by)) != len(group_by)):
        raise ToolError('INVALID_GROUP_BY')
    top_k = tool.m['limits']['default_page_size'] if top_k is None else top_k
    if type(top_k) is not int or not 1 <= top_k <= tool.m['limits']['max_page_size']:
        raise ToolError('INVALID_TOP_K')
    cutoff = None
    if as_of is not None:
        try:
            cutoff = (date.fromisoformat(as_of) + timedelta(days=1)).isoformat()
        except (TypeError, ValueError):
            raise ToolError('INVALID_AS_OF') from None
    mapped = tool.m['entities']['incident']['columns']
    if any(field not in mapped for field in group_by):
        raise ToolError('GROUP_COLUMN_UNAVAILABLE')
    if cutoff and 'occurred_at' not in mapped:
        raise ToolError('STATISTICS_DATE_UNMAPPED')
    if comparison_period is not None and 'occurred_at' not in filters:
        raise ToolError('COMPARISON_REQUIRES_CURRENT_PERIOD')

    def population(selected_filters):
        clauses, values = predicates(tool, selected_filters)
        if cutoff:
            clauses.append('julianday(' + tool.col('incident', 'occurred_at', 'i') + ')<julianday(?)')
            values.append(cutoff)
        where = ' AND '.join('(' + clause + ')' for clause in clauses)
        return ' FROM ' + tool.table('incident') + ' i WHERE ' + where, values, where

    def totals(source, values):
        result = {'total_incidents': tool.db.execute('SELECT COUNT(DISTINCT ' + tool.col('incident', 'incident_id', 'i') + ')' + source, values).fetchone()[0],
                  'recorded_quantities': {}}
        for field in QUANTITIES:
            if field not in mapped:
                result['recorded_quantities'][field] = {'status': 'unmapped', 'sum': None, 'missing_count': None}
                continue
            column = tool.col('incident', field, 'i')
            invalid = tool.db.execute('SELECT 1' + source + ' AND ' + column +
                " IS NOT NULL AND (typeof(" + column + ")!='integer' OR " + column + '<0) LIMIT 1', values).fetchone()
            if invalid:
                raise ToolError('INVALID_SOURCE_QUANTITY: ' + field)
            row = tool.db.execute('SELECT SUM(' + column + '),COUNT(*)-COUNT(' + column + ')' + source, values).fetchone()
            result['recorded_quantities'][field] = {'status': 'partial' if row[1] else 'OK', 'sum': row[0], 'missing_count': row[1]}
        return result

    own_transaction = not tool.db.in_transaction
    if own_transaction:
        tool.db.execute('BEGIN')
    try:
        source, values, where = population(filters)
        result = totals(source, values)
        fields, group_columns, joins = [], [], ''
        for index, field in enumerate(group_by):
            column = tool.col('incident', field, 'i')
            if field in ARRAY_FILTER_FIELDS:
                # Reuse the filter source checks before expanding an array for grouping.
                predicates(tool, {field: {'mode': 'any', 'values': ['__validation_only__']}})
                alias = 'g' + str(index)
                joins += ' LEFT JOIN json_each(' + column + ') ' + alias + ' ON 1=1'
                column = alias + '.value'
            fields.append(column + ' AS ' + ident(field))
            group_columns.append(column)
        grouped = ('SELECT ' + ','.join(fields) + ',COUNT(DISTINCT ' + tool.col('incident', 'incident_id', 'i') + ') AS incident_count'
                   + ' FROM ' + tool.table('incident') + ' i' + joins + ' WHERE ' + where
                   + ' GROUP BY ' + ','.join(group_columns))
        group_count = tool.db.execute('SELECT COUNT(*) FROM (' + grouped + ')', values).fetchone()[0]
        groups = [dict(row) for row in tool.db.execute(grouped + ' ORDER BY incident_count DESC,'
                  + ','.join(ident(field) for field in group_by) + ' LIMIT ?', [*values, top_k])]
        limit = tool.m['limits']['max_scope_incidents']
        ids = tuple(row[0] for row in tool.db.execute('SELECT ' + tool.col('incident', 'incident_id', 'i')
                    + source + ' ORDER BY ' + tool.col('incident', 'incident_id', 'i') + ' LIMIT ?', [*values, limit + 1]))
        comparison = None
        if comparison_period is not None:
            prior_filters = {**copy.deepcopy(filters), 'occurred_at': comparison_period}
            prior_source, prior_values, prior_where = population(prior_filters)
            prior = totals(prior_source, prior_values)
            delta = result['total_incidents'] - prior['total_incidents']
            comparison = {**prior, 'period': copy.deepcopy(comparison_period), 'delta_incidents': delta,
                          'change_percent': 100 * delta / prior['total_incidents'] if prior['total_incidents'] else None}
            comparison['groups'] = []
            for group in groups:
                tests = ' AND '.join(column + ' IS ?' for column in group_columns)
                query = ('SELECT COUNT(DISTINCT ' + tool.col('incident', 'incident_id', 'i') + ') FROM '
                         + tool.table('incident') + ' i' + joins + ' WHERE ' + prior_where
                         + ' AND ' + tests)
                count = tool.db.execute(query, [*prior_values, *(group[field] for field in group_by)]).fetchone()[0]
                comparison['groups'].append({**{field: group[field] for field in group_by}, 'incident_count': count})
    finally:
        if own_transaction:
            tool.db.rollback()
    now = time.monotonic()
    tool.scopes = {key: value for key, value in tool.scopes.items() if value['expires_at'] > now}
    scope_id = secrets.token_hex(12)
    complete = len(ids) <= limit
    tool.scopes[scope_id] = {'actor': actor, 'ids': ids if complete else (), 'expires_at': now + tool.scope_ttl_seconds,
                             'requires_selection': False, 'summary_only': not complete}
    return {**result, 'status': 'OK' if result['total_incidents'] else 'NO_MATCH', 'scope_id': scope_id,
            'scope_mode': 'cohort', 'scope_complete': complete, 'requires_selection': False,
            'filters': copy.deepcopy(filters), 'as_of': as_of, 'group_by': group_by, 'groups': groups,
            'group_count': group_count, 'groups_truncated': group_count > len(groups), 'comparison': comparison,
            'mapping_version': tool.m['mapping_version'], 'population': 'full_filtered_sql_population',
            'source_ref': {'logical_entity': 'incident'}, 'source_completeness': 'unknown',
            'limitations': ['RECORDED_QUANTITIES_NOT_VERIFIED_IMPACT', 'GRADE_AND_LOSS_UNMAPPED']
                + (['OVERLAPPING_ARRAY_GROUPS_NO_QUANTITY_ALLOCATION'] if set(group_by) & ARRAY_FILTER_FIELDS else [])
                + (['DETAIL_SCOPE_LIMIT_EXCEEDED'] if not complete else [])}


def render_statistics(entry):
    """Render numeric statements from verified Tool values, not generated prose."""
    result, evidence_id = entry['result'], entry['id']
    lines = [f"조건에 맞는 전체 사고는 {result['total_incidents']}건입니다.",
             '조회 조건: ' + ', '.join(f'{key}={value}' for key, value in result['filters'].items())]
    if result['as_of'] is not None:
        lines.append('조회 기준일: ' + result['as_of'])
    comparison = result['comparison']
    if comparison is not None:
        lines.append('비교 기간: ' + str(comparison['period']))
        percent = comparison['change_percent']
        change = f'{percent:.2f}%' if percent is not None else '계산 불가(비교 기준 0건)'
        lines.append(f"비교 기간 사고 {comparison['total_incidents']}건, 건수 차이 {comparison['delta_incidents']:+d}건, 증감률 {change}.")
    labels = {'department': '부서', 'city': '도시', 'line': '라인',
              'product_generations': '제품세대', 'fab_out_failure_codes': 'FAB Out 코드'}
    header = [labels[field] for field in result['group_by']] + ['현재 사고 건수']
    if comparison is not None:
        header += ['비교 기간 건수', '건수 차이']
    lines += ['', '| ' + ' | '.join(header) + ' |', '| ' + ' | '.join('---' for _ in header) + ' |']
    prior = {tuple(group[field] for field in result['group_by']): group['incident_count']
             for group in comparison['groups']} if comparison is not None else {}
    for group in result['groups']:
        key = tuple(group[field] for field in result['group_by'])
        cells = ['미등록' if value is None else str(value).replace('|', '\\|').replace('\n', ' ') for value in key]
        cells += [str(group['incident_count'])]
        if comparison is not None:
            cells += [str(prior[key]), f"{group['incident_count'] - prior[key]:+d}"]
        lines.append('| ' + ' | '.join(cells) + ' |')
    if result['groups_truncated']:
        lines.append(f"전체 {result['group_count']}개 그룹 중 상위 {len(result['groups'])}개 표시.")
    for field, quantity in result['recorded_quantities'].items():
        if quantity['status'] == 'unmapped':
            lines.append(f'기록 수량 {field}: 미매핑.')
            continue
        total = quantity['sum'] if quantity['sum'] is not None else '미확인'
        lines.append(f"기록 수량 {field}: 합계 {total}, 누락 {quantity['missing_count']}건. 실제 영향 수량 검증과 구분합니다.")
    if set(result['group_by']) & ARRAY_FILTER_FIELDS:
        lines.append('같은 사고가 여러 세대/코드 그룹에 포함되므로 그룹 합계를 전체 사고 건수로 사용하지 않습니다.')
    if not result['scope_complete']:
        lines.append('전체 집계는 계산했으나 상세 조회 scope 한도를 초과했습니다.')
    lines.append('등급·손실량은 현재 매핑에서 지원하지 않습니다. 원본 데이터 완전성은 미확인입니다.')
    text = '\n'.join(lines)
    return {'answer': text, 'claims': [{'claim_id': 'statistics-1', 'text': text, 'evidence_ids': [evidence_id]}]}
