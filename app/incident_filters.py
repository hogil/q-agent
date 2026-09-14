"""Bound, allowlisted multi-column predicates for the SQLite incident demo."""
import unicodedata
from datetime import datetime

SCALAR_FILTER_FIELDS = {'incident_number', 'city', 'line', 'line_code', 'line_alias', 'department'}
ARRAY_FILTER_FIELDS = {'product_generations', 'fab_out_failure_codes'}


def fold(value):
    return ''.join(unicodedata.normalize('NFKC', value or '').casefold().split())


def predicates(tool, filters):
    from incident_tools import ToolError
    if not isinstance(filters, dict) or not filters:
        raise ToolError('NONEMPTY_FILTER_OBJECT_REQUIRED')
    scalar = SCALAR_FILTER_FIELDS
    arrays = ARRAY_FILTER_FIELDS
    allowed = scalar | arrays | {'title_terms', 'occurred_at'}
    if set(filters) - allowed:
        raise ToolError('UNSUPPORTED_LOGICAL_FILTER')
    clauses, params = [], []
    for key, value in filters.items():
        mapped = 'title' if key == 'title_terms' else key
        if mapped not in tool.m['entities']['incident']['columns']:
            raise ToolError('FILTER_COLUMN_UNAVAILABLE: ' + mapped)
        column = tool.col('incident', mapped, 'i')
        if key in scalar:
            if not isinstance(value, str) or not value.strip():
                raise ToolError('INVALID_SCALAR_FILTER')
            clauses.append(column + '=?'); params.append(value)
        elif key == 'title_terms':
            if not isinstance(value, list) or not value or any(not isinstance(v, str) or not v.strip() for v in value):
                raise ToolError('INVALID_TITLE_TERMS')
            for term in value:
                clauses.append('instr(qagent_fold(' + column + '),?)>0'); params.append(fold(term))
        elif key in arrays:
            if not isinstance(value, dict) or set(value) != {'mode', 'values'} or value['mode'] not in ('any', 'all', 'exact'):
                raise ToolError('INVALID_ARRAY_FILTER')
            values = value['values']
            if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v for v in values):
                raise ToolError('INVALID_ARRAY_VALUES')
            values = list(dict.fromkeys(values))
            # A JSON object/scalar is a source contract error, not an empty array.
            invalid = tool.db.execute('SELECT 1 FROM ' + tool.table('incident') + ' i WHERE ' + column +
                ' IS NOT NULL AND CASE WHEN json_valid(' + column + ') THEN json_type(' + column +
                ")!='array' ELSE 1 END LIMIT 1").fetchone()
            if invalid:
                raise ToolError('INVALID_SOURCE_ARRAY: ' + key)
            invalid_item = tool.db.execute('SELECT 1 FROM ' + tool.table('incident') + ' i, json_each(' +
                column + ") a WHERE a.type!='text' LIMIT 1").fetchone()
            if invalid_item:
                raise ToolError('INVALID_SOURCE_ARRAY_ELEMENT: ' + key)
            if value['mode'] == 'any':
                clauses.append('EXISTS (SELECT 1 FROM json_each(' + column + ') a WHERE a.value IN (' + ','.join('?' for _ in values) + '))')
                params.extend(values)
            else:
                for item in values:
                    clauses.append('EXISTS (SELECT 1 FROM json_each(' + column + ') a WHERE a.value=?)'); params.append(item)
                if value['mode'] == 'exact':
                    clauses.append('(SELECT COUNT(DISTINCT a.value) FROM json_each(' + column + ') a)=?'); params.append(len(values))
        else:
            if not isinstance(value, dict) or set(value) != {'gte', 'lt'}:
                raise ToolError('INVALID_TIME_RANGE')
            try:
                start, end = (datetime.fromisoformat(value[k]) for k in ('gte', 'lt'))
                if start.tzinfo is None or end.tzinfo is None or start >= end:
                    raise ValueError()
            except (ValueError, TypeError):
                raise ToolError('INVALID_TIME_RANGE') from None
            clauses.append('julianday(' + column + ')>=julianday(?) AND julianday(' + column + ')<julianday(?)')
            params.extend([value['gte'], value['lt']])
    return clauses, params
