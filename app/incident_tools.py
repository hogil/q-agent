"""물리 스키마 교체 가능한 읽기 전용 SQLite Tool 예제.
Production ACL/connection/snapshot/LLM Tool 등록은 별도 구현 대상.
"""
import re, secrets, sqlite3, time

class ToolError(ValueError):
    pass

def ident(value):
    # Identifiers never come from a user's prompt. Mapping files are administrator-controlled.
    if not isinstance(value,str) or not re.fullmatch(r'[^\W\d]\w*',value):
        raise ToolError('INVALID_IDENTIFIER: simple Unicode identifier required by this adapter')
    return '"'+value+'"'

class IncidentTools:
    def __init__(self, connection, mapping, scope_ttl_seconds=1800):
        self.db=connection;self.db.row_factory=sqlite3.Row;self.m=mapping;self.scopes={}
        self.scope_ttl_seconds=scope_ttl_seconds
        self.validate()
    def table(self,entity):return ident(self.m['entities'][entity]['table'])
    def col(self,entity,logical,alias):
        columns=self.m['entities'][entity]['columns']
        if entity=='incident' and logical=='expected_lot_count' and logical not in columns:return 'NULL'
        return alias+'.'+ident(columns[logical])
    def validate(self):
        if self.m['dialect']!='sqlite':raise ToolError('UNSUPPORTED_DIALECT: implement a database adapter')
        required={'incident':{'incident_id','incident_number','title','city','line'},'lot_list':{'incident_ref','lot_id','product_code','status'}}
        for name,fields in required.items():
            ent=self.m['entities'][name]
            if not fields.issubset(ent['columns']):raise ToolError('MISSING_LOGICAL_MAPPING: '+name)
            t=self.table(name)
            info=self.db.execute('PRAGMA table_info('+t+')').fetchall()
            real={row['name'] for row in info}
            if not real:raise ToolError('TABLE_NOT_FOUND: '+name)
            for physical in ent['columns'].values():
                ident(physical)
                if physical not in real:raise ToolError('COLUMN_NOT_FOUND: '+name+'.'+physical)
        rel=self.m['relationships']['incident_lots']
        if rel['parent_entity']!='incident' or rel['child_entity']!='lot_list':raise ToolError('UNSUPPORTED_RELATION')
        if rel['parent_key'] not in ('incident_id','incident_number') or rel['child_key']!='incident_ref':raise ToolError('INVALID_JOIN_KEY')
        if rel['duplicate_policy']!='exact_rows_deduplicate_conflicts_error':raise ToolError('UNSUPPORTED_DUPLICATE_POLICY')
        if rel['source_completeness'] not in ('declared_complete','unknown','partial'):raise ToolError('INVALID_COVERAGE')
        pk=self.col('incident',rel['parent_key'],'i')
        if self.db.execute(f'SELECT {pk} FROM {self.table("incident")} i GROUP BY {pk} HAVING COUNT(*)>1 OR {pk} IS NULL LIMIT 1').fetchone():
            raise ToolError('NON_UNIQUE_PARENT_KEY: configure a composite-key view/adapter')
        # Independent internal identity must also be unique, even when display-number joins are used.
        internal=self.col('incident','incident_id','i')
        if self.db.execute(f'SELECT {internal} FROM {self.table("incident")} i GROUP BY {internal} HAVING COUNT(*)>1 OR {internal} IS NULL LIMIT 1').fetchone():raise ToolError('NON_UNIQUE_INCIDENT_ID')
    def find_incidents(self,actor,incident_number=None,city=None):
        if incident_number is None and city is None:raise ToolError('FILTER_REQUIRED')
        # actor binds scope only. It is NOT an access-control policy. Production requires DB/service ACL here.
        cols=['incident_id','incident_number','title','city','line','expected_lot_count']
        sql='SELECT '+','.join(self.col('incident',k,'i')+' AS '+ident(k) for k in cols)
        sql+=' FROM '+self.table('incident')+' i WHERE 1=1';params=[]
        for name,value in [('incident_number',incident_number),('city',city)]:
            if value is not None:sql+=' AND '+self.col('incident',name,'i')+'=?';params.append(value)
        sql+=' ORDER BY '+self.col('incident','incident_id','i')+' LIMIT ?';params.append(self.m['limits']['max_scope_incidents']+1)
        rows=[dict(r) for r in self.db.execute(sql,params)]
        if len(rows)>self.m['limits']['max_scope_incidents']:raise ToolError('SCOPE_TOO_LARGE: use server-side query scope')
        now=time.monotonic()
        self.scopes={key:value for key,value in self.scopes.items() if value['expires_at']>now}
        scope=secrets.token_hex(12);self.scopes[scope]={'actor':actor,'ids':tuple(r['incident_id'] for r in rows),'expires_at':now+self.scope_ttl_seconds}
        return {'status':'OK' if rows else 'NO_MATCH','scope_id':scope,'data':rows,'mapping_version':self.m['mapping_version']}
    def list_incident_lots(self,actor,scope_id,page_size=None,offset=0):
        scope=self.scopes.get(scope_id)
        if not scope or scope['expires_at']<=time.monotonic():
            self.scopes.pop(scope_id,None)
            raise ToolError('INCIDENT_LOOKUP_REQUIRED_OR_SCOPE_EXPIRED')
        if scope['actor']!=actor:raise ToolError('SCOPE_ACTOR_MISMATCH')
        size=self.m['limits']['default_page_size'] if page_size is None else page_size
        if type(size) is not int or not 1<=size<=self.m['limits']['max_page_size'] or type(offset) is not int or offset<0:raise ToolError('INVALID_PAGINATION')
        ids=scope['ids']
        if not ids:return {'status':'NO_MATCH','items':[],'total_memberships':0,'unique_lots':0,'next_offset':None,'completeness':'not_applicable_no_incidents'}
        rel=self.m['relationships']['incident_lots'];ph=','.join('?' for _ in ids)
        join=self.col('incident',rel['parent_key'],'i')+'='+self.col('lot_list',rel['child_key'],'l')
        fields=[self.col('incident','incident_id','i')+' AS incident_id',self.col('incident','incident_number','i')+' AS incident_number']+[self.col('lot_list',k,'l')+' AS '+ident(k) for k in ['lot_id','product_code','status']]
        base='SELECT DISTINCT '+','.join(fields)+' FROM '+self.table('incident')+' i JOIN '+self.table('lot_list')+' l ON '+join+' WHERE '+self.col('incident','incident_id','i')+' IN ('+ph+')'
        # Current-state view must resolve historical conflicts upstream, never pick arbitrary MAX(status).
        conflict=self.db.execute('SELECT incident_id,lot_id FROM ('+base+') GROUP BY incident_id,lot_id HAVING COUNT(*)>1 OR lot_id IS NULL LIMIT 1',ids).fetchone()
        if conflict:raise ToolError('CONFLICTING_OR_NULL_LOT_RECORDS: configure a validated current-state view')
        counts=self.db.execute('SELECT COUNT(*) memberships,COUNT(DISTINCT lot_id) unique_lots FROM ('+base+')',ids).fetchone()
        items=[dict(x) for x in self.db.execute(base+' ORDER BY incident_id,lot_id LIMIT ? OFFSET ?',ids+(size,offset))]
        per_counts={r['incident_id']:r['n'] for r in self.db.execute('SELECT incident_id,COUNT(*) n FROM ('+base+') GROUP BY incident_id',ids)}
        metadata=self.db.execute('SELECT '+self.col('incident','incident_id','i')+' id,'+self.col('incident','expected_lot_count','i')+' expected FROM '+self.table('incident')+' i WHERE '+self.col('incident','incident_id','i')+' IN ('+ph+')',ids).fetchall()
        coverage=[]
        for row in metadata:
            actual=per_counts.get(row['id'],0);expected=row['expected'];source=rel['source_completeness']
            if expected is not None and actual!=expected:state='count_mismatch'
            elif source!='declared_complete':state=source
            elif expected is None:state='unknown_expected_count'
            else:state='complete_by_declared_source_and_count'
            coverage.append({'incident_id':row['id'],'expected_lots':expected,'returned_total_lots':actual,'state':state})
        total=counts['memberships'];complete=all(x['state']=='complete_by_declared_source_and_count' for x in coverage)
        return {'status':('OK' if complete else 'PARTIAL') if total else 'NO_MATCH','scope_id':scope_id,'items':items,
                'total_memberships':total,'unique_lots':counts['unique_lots'],'offset':offset,'page_size':size,
                'next_offset':offset+len(items) if offset+len(items)<total else None,'coverage':coverage,
                'source_completeness':rel['source_completeness'],'mapping_version':self.m['mapping_version'],
                'source_ref':{'logical_entity':'lot_list','relation':'incident_lots'},
                'note':'Count agreement is a check, not proof that the lot identifiers are correct. Demo has no production snapshot/ACL.'}
