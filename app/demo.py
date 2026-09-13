import json,sqlite3,copy
from pathlib import Path
from incident_tools import IncidentTools,ToolError,ident
P=Path(__file__).resolve().parent
mapping=json.loads((P/'mapping.example.json').read_text())

def seed(m):
 c=sqlite3.connect(':memory:')
 inc=m['entities']['incident'];lot=m['entities']['lot_list'];ic=inc['columns'];lc=lot['columns']
 c.execute('CREATE TABLE '+ident(inc['table'])+' ('+','.join(ident(v)+(' INTEGER' if k=='expected_lot_count' else ' TEXT') for k,v in ic.items())+')')
 c.execute('CREATE TABLE '+ident(lot['table'])+' ('+','.join(ident(v)+' TEXT' for v in lc.values())+')')
 c.executemany('INSERT INTO '+ident(inc['table'])+' VALUES (?,?,?,?,?,?)',[
 ('PK001','INC-001','외곽 Shot Fail','화성','65L (ABCD)',6),('PK002','INC-002','Shot 반복 Fail','화성','65L (ABCD)',4),('PK007','INC-007','현상 잔류 패턴','화성','65L (ABCD)',1),('PK009','INC-009','연결 누락 확인 예시','평택','67L (MNOP)',2)])
 r=[]
 for pk,ids in [('PK001',range(1,7)),('PK002',[6,7,8,9]),('PK007',[10])]:
  for n in ids:r.append((pk,f'LOT-{n:03}','PX_B' if n%2 else 'PX_C','REGISTERED'))
 r.append(r[0])  # exact duplicate source row; does not add another Lot
 if m['relationships']['incident_lots']['parent_key']=='incident_number':
  r=[('INC-'+x[0][-3:],)+x[1:] for x in r]
 c.executemany('INSERT INTO '+ident(lot['table'])+' VALUES (?,?,?,?)',r)
 c.commit();return c

checks=[]
def check(name,b):
 assert b,name;checks.append({'name':name,'passed':True})
def raises(name,fn):
 try:fn()
 except ToolError:check(name,True);return
 check(name,False)

c=seed(mapping);t=IncidentTools(c,mapping)
raises('선조회 없는 Lot 접근 차단',lambda:t.list_incident_lots('user','invalid'))
r=t.find_incidents('user',incident_number='INC-001');s=r['scope_id']
a=t.list_incident_lots('user',s);b=t.list_incident_lots('user',s,offset=a['next_offset'])
check('PK와 표시번호 분리 Join',a['total_memberships']==6)
check('중복 원본 Lot 행 제거',a['unique_lots']==6)
check('첫 페이지 3개',len(a['items'])==3 and a['next_offset']==3)
check('다음 페이지 완결',len(b['items'])==3 and b['next_offset'] is None)
check('6개 고유 Lot 정확',len({x['lot_id'] for x in a['items']+b['items']})==6)
check('선언한 완전성과 건수 일치',a['coverage'][0]['state']=='complete_by_declared_source_and_count')
raises('다른 사용자 scope 차단',lambda:t.list_incident_lots('other',s))
raises('page size 상한',lambda:t.list_incident_lots('user',s,page_size=1000))
empty=t.find_incidents('user',incident_number='MISSING');check('사고 미등록',t.list_incident_lots('user',empty['scope_id'])['status']=='NO_MATCH')
missing=t.find_incidents('user',incident_number='INC-009');check('등록 2개/연결 0개 차이 보존',t.list_incident_lots('user',missing['scope_id'])['coverage'][0]['state']=='count_mismatch')
all_r=t.find_incidents('user',city='화성');all_l=t.list_incident_lots('user',all_r['scope_id'],page_size=100)
check('여러 사고 membership 11/고유10',all_l['total_memberships']==11 and all_l['unique_lots']==10)
check('사용자 값 SQL 바인딩',t.find_incidents('user',incident_number="' OR 1=1 --")['status']=='NO_MATCH')
renamed=copy.deepcopy(mapping);renamed['mapping_version']='demo-renamed-0.4'
for idx,(name,ent) in enumerate(renamed['entities'].items()):
 ent['table']='corp_table_'+str(idx)
 ent['columns']={k:'corp_col_'+str(i) for i,k in enumerate(ent['columns'])}
t2=IncidentTools(seed(renamed),renamed);r2=t2.find_incidents('user',incident_number='INC-001');a2=t2.list_incident_lots('user',r2['scope_id'],page_size=100)
check('테이블/전컬럼 교체 후 동일 결과',a2['items']==a['items']+b['items'])
numberjoin=copy.deepcopy(mapping);numberjoin['relationships']['incident_lots']['parent_key']='incident_number';t3=IncidentTools(seed(numberjoin),numberjoin);r3=t3.find_incidents('user',incident_number='INC-001');check('사고 표시번호 Join 설정',t3.list_incident_lots('user',r3['scope_id'])['total_memberships']==6)
bad=copy.deepcopy(mapping);bad['entities']['lot_list']['columns']['lot_id']='nonexistent';raises('존재하지 않는 컬럼 검출',lambda:IncidentTools(c,bad))
bad=copy.deepcopy(mapping);bad['entities']['lot_list']['table']='x; DROP TABLE y';raises('식별자 SQL 삽입 차단',lambda:IncidentTools(c,bad))
unknown=copy.deepcopy(mapping);unknown['relationships']['incident_lots']['source_completeness']='unknown';ut=IncidentTools(seed(unknown),unknown);ur=ut.find_incidents('user',incident_number='INC-001');check('건수 같아도 완전성 미확정 유지',ut.list_incident_lots('user',ur['scope_id'])['status']=='PARTIAL')
l=mapping['entities']['lot_list'];c.execute('INSERT INTO '+ident(l['table'])+' VALUES (?,?,?,?)',('PK001','LOT-001','PX_B','DIFFERENT_STATUS'))
raises('동일 Lot 속성 충돌 차단',lambda:t.list_incident_lots('user',s))
# restore clean seed before export
c=seed(mapping)
(P/'mapping.renamed-demo.json').write_text(json.dumps(renamed,ensure_ascii=False,indent=2))
(P/'results.json').write_text(json.dumps({'notice':'합성 데이터. production ACL/snapshot/LLM 미구현.','first_page':a,'second_page':b,'multi_incident':all_l,'checks':checks},ensure_ascii=False,indent=2))
(P/'schema_seed.sql').write_text('\n'.join(c.iterdump()))
c.commit();out=sqlite3.connect(P/'demo.sqlite');c.backup(out);out.close()
print(json.dumps({'tests':len(checks),'lots':[x['lot_id'] for x in a['items']+b['items']],'multiple_incidents':{'memberships':11,'unique_lots':10}},ensure_ascii=False))
