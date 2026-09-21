"""Bounded SELECTs over administrator-mapped views; never accept model-written SQL."""
from contextlib import closing
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
import copy
import json
import math
import os
from pathlib import Path
import sqlite3
import time as clock
from zoneinfo import ZoneInfo

from incident_tools import ToolError


def _time(value, zone=timezone.utc):
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return (result if result.tzinfo else result.replace(tzinfo=zone)).astimezone(timezone.utc)


def _iso(value):
    return value.isoformat().replace('+00:00', 'Z')


def _ident(value, dialect):
    return '[' + value + ']' if dialect == 'sqlserver' else '"' + value + '"'


class EnterpriseTools:
    def __init__(self, settings, incident_map, context):
        self.cfg = copy.deepcopy(settings.data['enterprise'])
        self.incident_map = incident_map
        self.context = copy.deepcopy(context)

    def query(self, actor, incident_ids, as_of):
        ctx = self.context
        incident = self.incident_map.get(ctx.get('incident_number'), {})
        if not actor or not incident or incident_ids != [incident['incident_id']]:
            raise ToolError('INCIDENT_SCOPE_MISMATCH')
        if not self.cfg['enabled']:
            return {'status': 'UNAVAILABLE', 'systems': [], 'limitations': ['ENTERPRISE_NOT_CONFIGURED']}
        try:
            start, stop = _time(ctx['from']), _time(ctx['to'])
            cutoff = datetime.combine(datetime.fromisoformat(as_of).date(), time.max, timezone.utc)
            if stop < start or stop - start > timedelta(days=self.cfg['max_window_days']):
                raise ValueError()
            if any(not isinstance(ctx.get(key), str) or not ctx[key].strip() or ctx[key] == 'all'
                   for key in ('equipment', 'step')):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise ToolError('ENTERPRISE_SCOPE_REQUIRED_OR_TOO_WIDE') from None
        stop = min(stop, cutoff)
        if stop < start:
            raise ToolError('ENTERPRISE_SCOPE_AFTER_CUTOFF')
        systems = [self._source(source, start, stop) for source in self.cfg['sources']]
        failed = any(source['status'] == 'UNAVAILABLE' for source in systems)
        partial = failed or any(source.get('truncated') or source.get('text_truncated') for source in systems)
        return {'status': 'UNAVAILABLE' if all(s['status'] == 'UNAVAILABLE' for s in systems)
                else 'PARTIAL' if partial else 'OK', 'systems': systems,
                'scope': {'incident_ids': incident_ids, 'equipment': ctx['equipment'], 'step': ctx['step'],
                          'from': _iso(start), 'to': _iso(stop), 'as_of': as_of},
                'limitations': ['CORRELATION_NOT_CAUSATION', 'DATABASE_ACCOUNT_ACCESS_NOT_PER_USER_ACL',
                                'EVENT_TIME_FILTER_NOT_HISTORICAL_DATABASE_SNAPSHOT']}

    def _statement(self, source, start, stop):
        dialect, columns = source['dialect'], source['columns']
        quote = lambda value: _ident(value, dialect)
        col = lambda key: quote(columns[key])
        view = '.'.join(quote(value) for value in (source['schema'], source['view']) if value)
        temporal = lambda key: f'julianday({col(key)})' if dialect == 'sqlite' else col(key)
        marker = 'julianday(?)' if dialect == 'sqlite' else '?'
        zone = ZoneInfo(source['timezone'])
        timestamp = lambda value: _iso(value) if dialect == 'sqlite' else value.astimezone(zone).replace(tzinfo=None)
        where = [f'{col("equipment")} = ?', f'{col("step")} = ?', f'{temporal("occurred_at")} <= {marker}']
        params = [self.context['equipment'], self.context['step'], timestamp(stop)]
        if 'ended_at' in columns:
            where.append(f'({temporal("ended_at")} >= {marker} OR {col("ended_at")} IS NULL)')
        else:
            where.append(f'{temporal("occurred_at")} >= {marker}')
        params.append(timestamp(start))
        lots = sorted({row['lot_id'] for row in self.context.get('wafers', [])})
        if 'lot_id' in columns and lots:
            where.append(f'{col("lot_id")} IN ({",".join("?" for _ in lots)})')
            params.extend(lots)
        limit = self.cfg['max_rows'] + 1
        top = f'TOP {limit} ' if dialect == 'sqlserver' else ''
        sql = f'SELECT {top}' + ', '.join(col(key) for key in columns)
        sql += f' FROM {view} WHERE ' + ' AND '.join(where)
        sql += f' ORDER BY {col("occurred_at")} DESC, {col("record_id")} DESC'
        if dialect in ('sqlite', 'postgresql'):
            sql += f' LIMIT {limit}'
        elif dialect == 'oracle':
            sql = f'SELECT * FROM ({sql}) WHERE ROWNUM <= {limit}'
        return sql, params

    def _connect(self, source):
        if source['dialect'] == 'sqlite':
            conn = sqlite3.connect(Path(source['sqlite_file']).resolve().as_uri() + '?mode=ro',
                                   uri=True, timeout=self.cfg['timeout_seconds'])
            try:
                conn.execute('PRAGMA query_only=ON')
                deadline = clock.monotonic() + self.cfg['timeout_seconds']
                conn.set_progress_handler(lambda: int(clock.monotonic() > deadline), 1000)
            except Exception:
                conn.close()
                raise
            return conn
        dsn = os.environ.get(source['dsn_env'])
        if not dsn:
            raise ToolError('ENTERPRISE_DSN_MISSING')
        try:
            import pyodbc
        except ImportError:
            raise ToolError('ENTERPRISE_ODBC_DRIVER_REQUIRED') from None
        conn = pyodbc.connect(dsn, readonly=True, timeout=self.cfg['timeout_seconds'], autocommit=False)
        try:
            conn.timeout = self.cfg['timeout_seconds']
        except Exception:
            conn.close()
            raise
        return conn

    def _source(self, source, start, stop):
        began = clock.monotonic()
        result = {'id': source['id'], 'system': source['system'], 'transport': 'sql',
                  'view': '.'.join(v for v in (source['schema'], source['view']) if v),
                  'synthetic': source['synthetic'], 'queried_at': _iso(datetime.now(timezone.utc)),
                  'source_timezone': source['timezone'], 'rows': [], 'row_count': 0,
                  'truncated': False, 'text_truncated': False, 'status': 'UNAVAILABLE'}
        try:
            sql, params = self._statement(source, start, stop)
            with closing(self._connect(source)) as conn, closing(conn.cursor()) as cursor:
                cursor.execute(sql, params)
                fetched = cursor.fetchmany(self.cfg['max_rows'] + 1)
            rows = [dict(zip(source['columns'], row)) for row in fetched[:self.cfg['max_rows']]]
            for row in rows:
                self._validate_row(row, source, start, stop)
                for key, value in row.items():
                    if isinstance(value, datetime):
                        row[key] = _iso(_time(value, ZoneInfo(source['timezone'])))
                    elif isinstance(value, Decimal):
                        row[key] = str(value)
                    elif isinstance(value, float) and not math.isfinite(value):
                        raise ValueError('nonfinite')
                    elif value is not None and type(value) not in (str, int, float, bool):
                        raise ValueError('unsupported column type')
                    if isinstance(row[key], str) and len(row[key]) > 2000:
                        row[key] = row[key][:2000]
                        result['text_truncated'] = True
            budget, kept = 24000 // len(self.cfg['sources']), []
            for row in rows:
                size = len(json.dumps(row, ensure_ascii=False))
                if size > budget:
                    break
                kept.append(row)
                budget -= size
            result.update(rows=kept, row_count=len(kept),
                          truncated=len(fetched) > self.cfg['max_rows'] or len(kept) < len(rows),
                          status='OK' if rows else 'NO_MATCH')
        except ToolError as exc:
            result['error'] = str(exc)
        except Exception:
            # Driver errors can include credentials, SQL and private network names.
            result['error'] = 'ENTERPRISE_QUERY_FAILED'
        result['elapsed_seconds'] = round(clock.monotonic() - began, 3)
        return result

    def _validate_row(self, row, source, start, stop):
        if row['record_id'] is None or row['equipment'] != self.context['equipment'] or row['step'] != self.context['step']:
            raise ValueError('scope mismatch')
        zone = ZoneInfo(source['timezone'])
        timestamp = _time(row['occurred_at'], zone)
        end = _time(row['ended_at'], zone) if row.get('ended_at') is not None else None
        if timestamp > stop or (end is not None and (end < start or end < timestamp)):
            raise ValueError('time mismatch')
        if 'ended_at' not in source['columns'] and timestamp < start:
            raise ValueError('time mismatch')
        lots = {item['lot_id'] for item in self.context.get('wafers', [])}
        if 'lot_id' in source['columns'] and lots and row['lot_id'] not in lots:
            raise ValueError('lot mismatch')
        row['occurred_at'] = _iso(timestamp)
        if end is not None:
            row['ended_at'] = _iso(min(end, stop))
            row['end_clipped'] = end > stop
