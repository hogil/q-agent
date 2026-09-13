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
        if entity=='incident' and logical in ('expected_lot_count','affected_wafer_count') and logical not in columns:return 'NULL'
        return alias+'.'+ident(columns[logical])
    def validate(self):
        if self.m['dialect']!='sqlite':raise ToolError('UNSUPPORTED_DIALECT: implement a database adapter')
        required={'incident':{'incident_id','incident_number','title','city','line'},'lot_list':{'incident_ref','lot_id','product_code','status'}}
        if 'wafer_list' in self.m['entities']:
            wr=self.m['relationships'].get('incident_wafers')
            if not wr or wr.get('scope') not in ('incident_affected','lot_inventory'):raise ToolError('INVALID_WAFER_RELATION')
            if wr.get('parent_key') not in ('incident_id','incident_number','title') or wr.get('child_key')!='incident_ref' or wr.get('lot_key')!='lot_id':raise ToolError('INVALID_WAFER_JOIN_KEYS')
            if wr.get('source_completeness') not in ('unknown','partial','declared_complete'):raise ToolError('INVALID_WAFER_COVERAGE')
            required['wafer_list']={'lot_id','wafer_id','status'}
            if wr['scope']=='incident_affected':required['wafer_list'].add('incident_ref')
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
        if rel['parent_key'] not in ('incident_id','incident_number','title') or rel['child_key']!='incident_ref':raise ToolError('INVALID_JOIN_KEY')
        if rel['duplicate_policy']!='exact_rows_deduplicate_conflicts_error':raise ToolError('UNSUPPORTED_DUPLICATE_POLICY')
        if rel['source_completeness'] not in ('declared_complete','unknown','partial'):raise ToolError('INVALID_COVERAGE')
        pk=self.col('incident',rel['parent_key'],'i')
        if self.db.execute(f'SELECT {pk} FROM {self.table("incident")} i GROUP BY {pk} HAVING COUNT(*)>1 OR {pk} IS NULL LIMIT 1').fetchone():
            raise ToolError('NON_UNIQUE_PARENT_KEY: configure a composite-key view/adapter')
        # Independent internal identity must also be unique, even when display-number joins are used.
        internal=self.col('incident','incident_id','i')
        if self.db.execute(f'SELECT {internal} FROM {self.table("incident")} i GROUP BY {internal} HAVING COUNT(*)>1 OR {internal} IS NULL LIMIT 1').fetchone():raise ToolError('NON_UNIQUE_INCIDENT_ID')
        wr=self.m['relationships'].get('incident_wafers')
        if wr and wr['scope']=='incident_affected' and wr['parent_key']!=rel['parent_key']:
            key=self.col('incident',wr['parent_key'],'i')
            if self.db.execute(f'SELECT {key} FROM {self.table("incident")} i GROUP BY {key} HAVING COUNT(*)>1 OR {key} IS NULL LIMIT 1').fetchone():raise ToolError('NON_UNIQUE_WAFER_PARENT_KEY')
    def find_incidents(self,actor,incident_number=None,city=None,title=None,line=None,title_match='exact'):
        if all(value is None for value in (incident_number,city,title,line)):raise ToolError('FILTER_REQUIRED')
        if title_match not in ('exact','contains'):raise ToolError('INVALID_TITLE_MATCH')
        for value in (incident_number,city,title,line):
            if value is not None and (not isinstance(value,str) or not value.strip()):raise ToolError('INVALID_FILTER_VALUE')
        # actor binds scope only. It is NOT an access-control policy. Production requires DB/service ACL here.
        cols=['incident_id','incident_number','title','city','line','expected_lot_count']
        if 'occurred_at' in self.m['entities']['incident']['columns']:cols.append('occurred_at')
        sql='SELECT '+','.join(self.col('incident',k,'i')+' AS '+ident(k) for k in cols)
        sql+=' FROM '+self.table('incident')+' i WHERE 1=1';params=[]
        for name,value in [('incident_number',incident_number),('city',city),('line',line)]:
            if value is not None:sql+=' AND '+self.col('incident',name,'i')+'=?';params.append(value)
        if title is not None:
            column=self.col('incident','title','i')
            sql+=(' AND instr('+column+',?)>0') if title_match=='contains' else (' AND '+column+'=?')
            params.append(title)
        sql+=' ORDER BY '+self.col('incident','incident_id','i')+' LIMIT ?';params.append(self.m['limits']['max_scope_incidents']+1)
        rows=[dict(r) for r in self.db.execute(sql,params)]
        if len(rows)>self.m['limits']['max_scope_incidents']:raise ToolError('SCOPE_TOO_LARGE: use server-side query scope')
        now=time.monotonic()
        self.scopes={key:value for key,value in self.scopes.items() if value['expires_at']>now}
        selection_required=title is not None and len(rows)>1
        scope=secrets.token_hex(12);self.scopes[scope]={'actor':actor,'ids':tuple(r['incident_id'] for r in rows),'expires_at':now+self.scope_ttl_seconds,'requires_selection':selection_required}
        return {'status':'NEEDS_SELECTION' if selection_required else ('OK' if rows else 'NO_MATCH'),'scope_id':scope,'data':rows,'requires_selection':selection_required,'mapping_version':self.m['mapping_version']}

    def _scope(self,actor,scope_id,allow_candidates=False):
        scope=self.scopes.get(scope_id)
        if not scope or scope['expires_at']<=time.monotonic():
            self.scopes.pop(scope_id,None)
            raise ToolError('INCIDENT_LOOKUP_REQUIRED_OR_SCOPE_EXPIRED')
        if scope['actor']!=actor:raise ToolError('SCOPE_ACTOR_MISMATCH')
        if scope.get('requires_selection') and not allow_candidates:raise ToolError('INCIDENT_SELECTION_REQUIRED')
        return scope

    def select_incidents(self,actor,scope_id,incident_ids):
        old=self._scope(actor,scope_id,allow_candidates=True)
        if not isinstance(incident_ids,list) or not incident_ids or any(not isinstance(x,str) for x in incident_ids):raise ToolError('INVALID_INCIDENT_SELECTION')
        if not set(incident_ids).issubset(old['ids']):raise ToolError('INCIDENT_OUTSIDE_SEARCH_SCOPE')
        key=secrets.token_hex(12)
        self.scopes[key]={**old,'ids':tuple(x for x in old['ids'] if x in incident_ids),'requires_selection':False}
        return {'status':'OK','scope_id':key,'incident_ids':list(self.scopes[key]['ids'])}

    def _lot_base(self,ids):
        rel=self.m['relationships']['incident_lots'];ph=','.join('?' for _ in ids)
        join=self.col('incident',rel['parent_key'],'i')+'='+self.col('lot_list',rel['child_key'],'l')
        fields=[self.col('incident',k,'i')+' AS '+ident(k) for k in ('incident_id','incident_number','title')]+[self.col('lot_list',k,'l')+' AS '+ident(k) for k in ('lot_id','product_code','status')]
        return 'SELECT DISTINCT '+','.join(fields)+' FROM '+self.table('incident')+' i JOIN '+self.table('lot_list')+' l ON '+join+' WHERE '+self.col('incident','incident_id','i')+' IN ('+ph+')'
    def list_incident_lots(self,actor,scope_id,page_size=None,offset=0):
        scope=self._scope(actor,scope_id)
        size=self.m['limits']['default_page_size'] if page_size is None else page_size
        if type(size) is not int or not 1<=size<=self.m['limits']['max_page_size'] or type(offset) is not int or offset<0:raise ToolError('INVALID_PAGINATION')
        ids=scope['ids']
        if not ids:return {'status':'NO_MATCH','items':[],'total_memberships':0,'unique_lots':0,'next_offset':None,'completeness':'not_applicable_no_incidents'}
        rel=self.m['relationships']['incident_lots'];ph=','.join('?' for _ in ids)
        base=self._lot_base(ids)
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
        return {'status':('OK' if total else 'NO_MATCH') if complete else 'PARTIAL','scope_id':scope_id,'items':items,
                'total_memberships':total,'unique_lots':counts['unique_lots'],'offset':offset,'page_size':size,
                'next_offset':offset+len(items) if offset+len(items)<total else None,'coverage':coverage,
                'source_completeness':rel['source_completeness'],'mapping_version':self.m['mapping_version'],
                'source_ref':{'logical_entity':'lot_list','relation':'incident_lots'},
                'note':'Count agreement is a check, not proof that the lot identifiers are correct. Demo has no production snapshot/ACL.'}

    def list_incident_wafers(self,actor,scope_id,lot_ids=None,page_size=None,offset=0):
        scope=self._scope(actor,scope_id)
        if 'wafer_list' not in self.m['entities']:raise ToolError('WAFER_TABLE_NOT_CONFIGURED')
        size=self.m['limits']['default_page_size'] if page_size is None else page_size
        if type(size) is not int or not 1<=size<=self.m['limits']['max_page_size'] or type(offset) is not int or offset<0:raise ToolError('INVALID_PAGINATION')
        if lot_ids is not None and (not isinstance(lot_ids,list) or not lot_ids or any(not isinstance(x,str) or not x for x in lot_ids)):raise ToolError('INVALID_LOT_FILTER')
        ids=scope['ids'];wr=self.m['relationships']['incident_wafers']
        # This prerequisite validates the entire registered Lot scope, not only page 1.
        lot_result=self.list_incident_lots(actor,scope_id,page_size=1)
        if not ids:
            if lot_ids:raise ToolError('LOT_OUTSIDE_INCIDENT_SCOPE')
            return {'status':'NO_MATCH','scope_id':scope_id,'items':[],'total_memberships':0,'unique_wafers':0,'next_offset':None,'wafer_scope':wr['scope'],'coverage':[]}
        lot_base=self._lot_base(ids)
        members=[dict(r) for r in self.db.execute(lot_base,ids)]
        if lot_ids is not None and not set(lot_ids).issubset({r['lot_id'] for r in members}):raise ToolError('LOT_OUTSIDE_INCIDENT_SCOPE')
        selected=[r for r in members if lot_ids is None or r['lot_id'] in lot_ids]
        selected_pairs={(r['incident_id'],r['lot_id']) for r in selected}
        fields=['s.incident_id','s.incident_number','s.title','s.lot_id',self.col('wafer_list','wafer_id','w')+' AS wafer_id',self.col('wafer_list','status','w')+' AS status']
        join=self.col('wafer_list','lot_id','w')+'=s.lot_id'
        if wr['scope']=='incident_affected':join+=' AND '+self.col('wafer_list',wr['child_key'],'w')+'='+self.col('incident',wr['parent_key'],'i')
        base='SELECT DISTINCT '+','.join(fields)+' FROM ('+lot_base+') s JOIN '+self.table('incident')+' i ON '+self.col('incident','incident_id','i')+'=s.incident_id JOIN '+self.table('wafer_list')+' w ON '+join
        params=tuple(ids)
        if lot_ids is not None:
            base+=' WHERE s.lot_id IN ('+','.join('?' for _ in lot_ids)+')';params+=tuple(lot_ids)
        conflict=self.db.execute('SELECT incident_id,lot_id,wafer_id FROM ('+base+') GROUP BY incident_id,lot_id,wafer_id HAVING COUNT(*)>1 OR wafer_id IS NULL OR wafer_id=\'\' LIMIT 1',params).fetchone()
        if conflict:raise ToolError('CONFLICTING_OR_NULL_WAFER_RECORDS')
        total=self.db.execute('SELECT COUNT(*) FROM ('+base+')',params).fetchone()[0]
        unique=self.db.execute('SELECT COUNT(*) FROM (SELECT DISTINCT lot_id,wafer_id FROM ('+base+'))',params).fetchone()[0]
        items=[dict(r) for r in self.db.execute(base+' ORDER BY incident_id,lot_id,wafer_id LIMIT ? OFFSET ?',params+(size,offset))]
        per_counts={r['incident_id']:r['n'] for r in self.db.execute('SELECT incident_id,COUNT(*) n FROM ('+base+') GROUP BY incident_id',params)}
        linked_pairs={(r['incident_id'],r['lot_id']) for r in self.db.execute('SELECT DISTINCT incident_id,lot_id FROM ('+base+')',params)}
        missing_pairs=sorted(selected_pairs-linked_pairs)
        ph=','.join('?' for _ in ids)
        metadata=self.db.execute('SELECT '+self.col('incident','incident_id','i')+' id,'+self.col('incident','affected_wafer_count','i')+' expected FROM '+self.table('incident')+' i WHERE '+self.col('incident','incident_id','i')+' IN ('+ph+')',ids).fetchall()
        coverage=[]
        for row in metadata:
            if lot_ids is not None and not any(x['incident_id']==row['id'] for x in selected):continue
            expected=row['expected'] if wr['scope']=='incident_affected' and lot_ids is None else None
            actual=per_counts.get(row['id'],0)
            if expected is not None and expected!=actual:state='count_mismatch'
            elif wr['scope']=='lot_inventory':state='inventory_not_incident_impact'
            elif wr['source_completeness']!='declared_complete':state=wr['source_completeness']
            elif expected is None:state='unknown_expected_count'
            else:state='complete_by_declared_source_and_count'
            coverage.append({'incident_id':row['id'],'expected_wafers':expected,'returned_total_wafers':actual,'state':state})
        complete=bool(coverage) and not missing_pairs and all(r['state']=='complete_by_declared_source_and_count' for r in coverage) and lot_result['status']=='OK'
        return {'status':('OK' if total else 'NO_MATCH') if complete else 'PARTIAL','scope_id':scope_id,'items':items,
                'total_memberships':total,'unique_wafers':unique,'unique_wafer_key':['lot_id','wafer_id'],
                'page_size':size,'offset':offset,'next_offset':offset+len(items) if offset+len(items)<total else None,
                'wafer_scope':wr['scope'],'source_completeness':wr['source_completeness'],'coverage':coverage,
                'lot_coverage':lot_result.get('coverage',[]),'lots_without_wafer_rows':[{'incident_id':i,'lot_id':l} for i,l in missing_pairs],
                'mapping_version':self.m['mapping_version'],'source_ref':{'logical_entity':'wafer_list','relation':'incident_wafers'},
                'note':'Lot inventory is not proof of incident-affected wafers. Production ACL, composite Lot identity and snapshot adapter remain required.'}
