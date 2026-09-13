"""Build reproducible synthetic inputs and labelled-query regression cases.

The query runner never receives expected values. Oracles use canonical DB rows
and independently compare them in Python. This is not held-out LLM evaluation.
"""
import argparse
import calendar
import copy
import json
import sqlite3
from collections import Counter
from pathlib import Path

from config_loader import add_config_arguments, load_config
from incident_tools import ident

ROOT = Path(__file__).resolve().parent


def write_fixture(path, data):
    payload = json.dumps(data, ensure_ascii=False, indent=2) + '\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text() != payload:
        raise ValueError('FIXTURE_EXISTS_WITH_DIFFERENT_CONTENT: ' + str(path))
    path.write_text(payload)


def inputs():
    templates = json.loads((ROOT / 'data/incident_cases.json').read_text())
    extras = [
        ('평택','65L','IJKL','ETCH',['D1z','D20'],['SYNTH_EDS_RING_FAIL'], '식각 Chamber 부품 교체 후 Ring 형태 EDS Fail 증가', '부품 교체 시점별 처리 이력을 나누어 동일 제품과 Recipe의 Ring 패턴 분포를 비교했다. 합성 점검 기록에서 특정 Chamber의 Edge 조건 편차가 관찰됐다.', '의심 Chamber 처리군의 후속 진행을 관리하고 부품 체결 및 Edge 조건을 점검한다. 복원 전후 확인 Wafer와 기준군을 비교한 뒤 승인 범위에서 재개한다.'),
        ('화성','66L','EFGH','CMP',['V5','V6'],['SYNTH_FAB_SCRATCH'], 'CMP Pad 교체 이후 선형 Scratch와 FAB 검사 이상', 'Pad 사용 이력과 검사 좌표를 연결해 선형 Scratch 위치를 비교했다. 합성 자료에서는 교체 직후 처리군에 패턴이 집중되지만 인과관계는 추가 확인이 필요하다.', 'Pad와 세정 상태를 점검하고 확인용 Wafer의 Scratch 재발 여부를 평가한다. 판정 기준 충족과 담당 승인 후 적용하며 미확인 제품은 별도 평가한다.'),
        ('용인','67L','MNOP','DIFF',['FET'],['SYNTH_EDS_LEAKAGE'], '열처리 온도 편차 구간의 Leakage 증가', '온도 이력과 처리시각을 정렬하고 제품 및 공정조건을 맞춘 비교군을 설정했다. 합성 Leakage 변화와 온도 편차가 함께 관찰되어 가설로 등록했다.', '센서 점검과 온도 균일도 확인을 실시하고 영향 후보 Lot을 추적한다. 원인 확정 전 전 제품 공통 조치를 적용하지 않는다.'),
        ('평택','68L','QRST','CVD',['V7','V8'],['SYNTH_FAB_PARTICLE','SYNTH_EDS_RING_FAIL'], '증착 이후 Particle 집중과 EDS Ring 패턴 동반 관찰', '막 두께, Particle 위치 및 설비 정비 이력을 비교했다. 합성 이미지에서 공간적 중첩은 관찰되지만 Particle이 전기적 Fail의 원인인지는 확인되지 않았다.', '정비 이력과 오염 경로를 점검하고 동일 조건 확인군을 확보한다. 세정과 Recipe 변경의 효과를 분리해 평가한다.'),
        ('화성','65L','ABCD','PHOTO',['D1a','D1z'],['SYNTH_EDS_EDGE_FAIL'], '외곽 Shot Defocus 재발과 노광 보정 이력 조사', '보정 이력의 버전과 외곽 Focus 지표를 시간 정렬했다. 동일 위치 재발이 관찰됐지만 과거 사고의 원인을 그대로 적용하지 않고 기준군을 확보했다.', '영향 후보를 분리하고 보정 변경 조건과 평가 기록을 확인한다. 확인 Lot의 외곽 지표와 EDS 결과를 함께 검토한 뒤 적용한다.'),
        ('평택','66L','UVWX','METAL',['D20','FET'],['SYNTH_EDS_OPEN'], '배선 공정 이후 Open Fail 집중 발생', 'Wafer 좌표와 공정 이력을 연결하고 배선 검사 위치와 전기적 Open 위치를 비교했다. 합성 비교에서 특정 조건군의 차이를 관찰했다.', '대상 조건군의 검사 범위를 확대하고 배선 형상과 설비 이력을 재확인한다. 조치 전후 전기적 결과와 형상 평가를 함께 검증한다.'),
        ('용인','68L','QRST','EDS',['V5','V8'],['SYNTH_EDS_CONTACT'], 'Probe 교체 후 Contact Fail과 재측정 결과 불일치', 'Probe 교체와 검사 순서를 기준으로 재측정 결과를 비교했다. 합성 결과에서 측정 조건의 영향을 확인했으나 제품 불량 여부는 별도로 판정한다.', 'Probe 상태와 접촉 조건을 점검하고 기준 Wafer로 재현성을 확인한다. 재측정 이력과 최초 결과를 모두 보존하고 승인 기준으로 최종 판정한다.'),
        ('화성','67L','MNOP','ETCH',['D1a','D1z','D20','FET','V5','V6','V7','V8'],['SYNTH_FAB_PARTICLE'], '식각 후 Particle 관찰 및 상류 공정 영향 조사', '상류 공정과 식각 설비 이력을 나누어 비교하고 Particle 위치와 Lot 군집을 확인했다. 합성 이력만으로 발생 공정을 확정할 수 없어 다중 가설을 유지했다.', '상류와 식각 공정의 확인군을 분리해 검사하고 원본 이미지를 연결한다. 발생 공정 확인 뒤 해당 범위에 한해 재발 방지 조건을 적용한다.')
    ]
    for i, (city,line,alias,dept,gens,fails,title,analysis,action) in enumerate(extras,9):
        templates.append(dict(id=f'VAR-TEMPLATE-{i:03}',city=city,line_code=line,line_alias=alias,department=dept,
            product_generations=gens,fab_out_failure_codes=fails,title=title,
            incident_detail=f'합성 사고: {title}. 동일 제품 조건을 기준으로 5개 Lot, 60 Wafer를 영향 후보로 등록했다. 원장 등록 범위와 실제 영향 확정 여부는 구분한다.',
            analysis_detail=analysis,confirmed_cause='합성 조사 가설. 원인 확정에는 추가 확인 시험이 필요하다.',
            containment='영향 후보 목록과 처리 이력을 보존하고 승인된 절차로 후속 진행을 관리한다.',
            corrective_action=action,verification='합성 확인 시나리오. 실제 기준값과 운영 효과는 검증하지 않았다.',
            prevention='조건 변경, 확인 결과, 승인 기록과 원본 검사 자료를 연결해 재발 여부를 추적한다.',
            remaining='다른 제품, Layer 및 설비에 대한 적용 가능성은 별도 검증이 필요하다.',synthetic=True))
    write_fixture(ROOT/'data/variant_incident_templates.json',templates)
    fields={}
    def field(name,labels,entries):
        fields[name]={'labels':labels,'values':[]}
        for canonical,aliases in entries:
            fields[name]['values'].append({'canonical':canonical,'aliases':aliases,'approved':True,
                'source_id':f'SYNTH-DICT-{name}-{len(fields[name]["values"])+1:03}'})
    field('city',['도시','위치','사이트','싸이트','site','campus'],[
        ('화성',['화성시','Hwaseong','화 성','화셩']),('평택',['평택시','Pyeongtaek','평 택','평텍']),('용인',['용인시','Yongin','용 인','용잉'])])
    field('line_code',['라인','생산라인','라인코드'],[(f'{i}L',[f'{i}엘',f'{i}라인',f'{i} L']) for i in [65,66,67,68]])
    field('line_alias',['라인별칭','라인약칭'],[(s,[s.lower(),' '.join(s)]) for s in ['ABCD','EFGH','IJKL','MNOP','QRST','UVWX']])
    field('line',['라인명','라인표시명'],[(f'{r[0]} ({r[1]})',[]) for r in sorted({(t['line_code'],t['line_alias']) for t in templates})])
    field('department',['부서','사고부서','담당부서','부셔','dept','조직'],[
        ('PHOTO',['포토','포토팀','phpto']),('ETCH',['에치','에칭','식각팀','etchh']),
        ('CMP',['씨엠피','연마팀']),('DIFF',['디퓨전','확산팀']),('CVD',['씨브이디','증착팀']),
        ('METAL',['메탈','배선팀']),('EDS',['이디에스','검사팀']),('UNASSIGNED',['미지정','담당미정'])])
    for canonical,aliases,scope,extra in [
        ('PHOTO',['p기술팀','P 기술팀'],{'city':'화성'},{}),('ETCH',['p기술팀'],{'city':'평택'},{}),
        ('PHOTO',['공정기술팀'],{},{}),('ETCH',['공정기술팀'],{},{}),
        ('PHOTO',['구포토팀'],{}, {'valid_from':'2020-01-01','valid_to':'2025-01-01'}),
        ('PHOTO',['신포토팀'],{}, {'valid_from':'2027-01-01'}),
        ('PHOTO',['피팀'],{}, {'approved':False})]:
        fields['department']['values'].append({'canonical':canonical,'aliases':aliases,'canonical_match':False,
            'scope':scope,'approved':True,'source_id':f'SYNTH-SCOPED-{len(fields["department"]["values"]):03}',**extra})
    field('product_generations',['제품세대','세대','제품새대','generation','gen'],[
        ('D1a',['디원에이','D 1 a']),('D1z',['디원지','D 1 z']),('D20',['디이십']),('FET',['에프이티']),
        ('V5',['브이파이브','브이5']),('V6',['브이식스','브이6']),('V7',['브이세븐','브이7']),('V8',['브이에이트','브이8'])])
    field('fab_out_failure_codes',['FAB Out 불량','fabout','팹아웃','fab-out','출하불량'],[
        ('SYNTH_EDS_EDGE_FAIL',['외곽불량','엣지페일','edge fail']),('SYNTH_EDS_RING_FAIL',['링불량','ring fail']),
        ('SYNTH_FAB_SCRATCH',['스크래치','스크레치']),('SYNTH_EDS_LEAKAGE',['누설','리키지']),
        ('SYNTH_FAB_PARTICLE',['파티클','파티클불량','particle']),('SYNTH_EDS_OPEN',['오픈불량','open fail']),
        ('SYNTH_EDS_CONTACT',['컨택불량','컨텍페일'])])
    field('title_terms',['사고명','사건명','사고몀','사고내용','검색어'],[
        ('외곽 Shot',['외곽샷','엣지샷','외곽 shot']),('동일 Shot',['같은샷','동일샷']),
        ('Chamber',['챔버','챔바','chmaber']),('Overlay',['오버레이','오버래이']),('재검출',['재검츌']),
        ('전기적 Fail',['전기불량','전기적페일']),('잔류 패턴',['잔류패턴','잔류패턴불량']),('식각',['에칭사고']),
        ('Scratch',['스크래치사고']),('Leakage',['누설사고']),('Particle',['파티클사고']),('Open Fail',['오픈페일']),
        ('Contact Fail',['컨택페일사고']),('EDS Fail',['이디에스페일'])])
    field('generation_mode',['세대조건','세대연산'],[('any',['하나라도','또는','OR']),('all',['모두','동시','AND']),('exact',['정확히','이것만'])])
    field('failure_mode',['불량조건'],[('any',['하나라도','또는']),('all',['모두','동시']),('exact',['정확히','이것만'])])
    field('request',['요청','조회항목','보여줄것'],[('incidents',['사고목록','사고 리스트']),('lots',['랏목록','로트 리스트','LOT list','롯목록']),
        ('wafers',['랏과 웨이퍼 목록','로트 웨이퍼 리스트','LOT & WAFER','웨이펴목록','웨이퍼목록'])])
    field('incident_number',['사고번호','사건번호','accident_no'],[])
    field('lot_id',['랏번호','로트번호','lot'],[])
    field('occurred_at',['기간','발생월','발생기간'],[])
    dictionary={'synthetic':True,'notice':'합성 승인 사전. 실제 사내 조직/용어 승인이 아니다. p기술팀의 도시별 차이도 충돌 시험용 가상 설정이다.',
        'version':'synthetic-variants-v1','as_of':'2026-09-13','candidate_threshold':.76,'fields':fields}
    write_fixture(ROOT/'domain-data/variants.synthetic.json',dictionary)


def canonical_rows(settings):
    table=settings.data['tables']['incident'];columns=table['columns']
    db=sqlite3.connect(Path(settings.data['database']['sqlite_file']).as_uri()+'?mode=ro',uri=True)
    db.row_factory=sqlite3.Row
    try:rows=[dict(r) for r in db.execute('SELECT '+','.join(ident(v)+' AS '+ident(k) for k,v in columns.items() if v)+' FROM '+ident(table['name'])+' ORDER BY '+ident(columns['incident_id']))]
    finally:db.close()
    for r in rows:
        for key in ['product_generations','fab_out_failure_codes']:
            if r[key] is not None:r[key]=json.loads(r[key])
    return rows


def build_cases(settings):
    rows=canonical_rows(settings)
    dictionary=json.loads(Path(settings.data['paths']['terminology_file']).read_text())
    cases=[];raw_rows=[]
    def add(category,question,expected,**extra):
        cases.append(dict(id=f'VAR-{len(cases)+1:04}',category=category,question=question,expected=expected,**extra))
    def surface(field,value,variant):
        entry=next(e for e in dictionary['fields'][field]['values'] if e['canonical']==value and e.get('canonical_match',True))
        choices=[value,value.lower(),*entry.get('aliases',[])]
        return choices[variant%len(choices)]
    for r in rows[:40]:
        for variant in range(4):
            raw={'사고번호':r['incident_number'].lower() if variant%2 else r['incident_number'],
                 ['도시','위치','싸이트','site'][variant]:surface('city',r['city'],variant+2),
                 ['라인','생산라인','line_code','라인코드'][variant]:surface('line_code',r['line_code'],variant+2),
                 ['부서','부셔','dept','사고부서'][variant]:surface('department',r['department'],variant+2)}
            expected_filters={k:r[k] for k in ['incident_number','city','line_code','department']}
            if r['product_generations']:
                raw[['세대','제품새대','gen','제품세대'][variant]]='{'+','.join(surface('product_generations',g,variant+2) for g in r['product_generations'])+'}'
                raw['세대조건']='모두'
                expected_filters['product_generations']={'mode':'all','values':r['product_generations']}
            if r['fab_out_failure_codes']:
                raw[['fabout','팹아웃','FAB Out 불량','fab-out'][variant]]=','.join(surface('fab_out_failure_codes',f,variant+2) for f in r['fab_out_failure_codes'])
                expected_filters['fab_out_failure_codes']={'mode':'any','values':r['fab_out_failure_codes']}
            raw['요청']=['랏과 웨이퍼 목록','로트 웨이퍼 리스트','LOT & WAFER','웨이펴목록'][variant]
            question='; '.join(k+'='+v for k,v in raw.items())
            add('multi_column_variants',question,{'status':'MATCHED','incident_ids':[r['incident_id']],
                'filters':expected_filters,'lot_count':settings.data['demo']['lots_per_incident'],
                'wafer_count':settings.data['demo']['lots_per_incident']*settings.data['demo']['wafers_per_lot']})
            if variant==3:raw_rows.append({'source_incident_id':r['incident_id'],'raw_columns':raw,'canonical_filters':expected_filters})
    for r in rows[:24]:
        wrong='PHOTO' if r['department']!='PHOTO' else 'ETCH'
        add('contradicting_filters',f'사고번호={r["incident_number"]}; 부서={wrong}; 요청=웨이퍼목록',{'status':'NO_MATCH','incident_ids':[]})
    for value,reason in [('photox','UNCONFIRMED_TYPO'),('공정기술팀','AMBIGUOUS_ALIAS'),('p기술팀','SCOPE_CONTEXT_REQUIRED'),
                          ('구포토팀','EXPIRED_ALIAS'),('신포토팀','ALIAS_NOT_YET_VALID'),('피팀','UNAPPROVED_ALIAS'),('노광','UNKNOWN_TERM'),('미확인조직','UNKNOWN_TERM')]:
        for label in ['부서','사고부서']:
            add('ambiguous_or_unverified',f'{label}={value}; 사고번호=SYN-2026-0001; 요청=웨이퍼목록',
                {'status':'NEEDS_CLARIFICATION','reason':reason,'no_business_tools':True})
    specials=[
        ('width_case','사고번호=ＳＹＮ－２０２６－０００１; 부서=ＰＨＯＴＯ; 세대=ｄ１ａ; 요청=랏목록','MATCHED'),
        ('scoped_alias','부서=p기술팀; 위치=화성시; 사고번호=SYN-2026-0001; 요청=웨이퍼목록','MATCHED'),
        ('scoped_alias','부서=p기술팀; 위치=평택시; 사고번호=SYN-2026-0009; 요청=웨이퍼목록','MATCHED'),
        ('wrong_scope','부서=p기술팀; 도시=용인; 사고번호=SYN-2026-0001','NEEDS_CLARIFICATION'),
        ('identifier_zero','사고번호=SYN-2026-OOO1; 요청=랏목록','NEEDS_CLARIFICATION'),
        ('identifier_zero','사고번호=SYN-2026-1; 요청=랏목록','NEEDS_CLARIFICATION'),
        ('generation_typo','사고번호=SYN-2026-0001; 세대=D1x','NEEDS_CLARIFICATION'),
        ('hangul_jamo','사고번호=SYN-2026-0001; 부ㅅㅓ=PHOTO','MATCHED'),
        ('unknown_filter','사고번호=SYN-2026-0001; 미등록컬럼=PHOTO','INVALID_REQUEST'),
        ('duplicate_filter','도시=화성; 위치=평택; 사고번호=SYN-2026-0001','INVALID_REQUEST'),
        ('unknown_request','사고번호=SYN-2026-0001; 요청=긴급조치실행','NEEDS_CLARIFICATION'),
        ('literal_sql','사고명=\' OR 1=1 --; 요청=사고목록','NO_MATCH'),
        ('literal_wildcard','사고명=%_; 요청=사고목록','NO_MATCH'),
        ('empty_array','사고번호=SYN-2026-0001; 세대={}','NEEDS_CLARIFICATION'),
        ('unknown_failure','사고번호=SYN-2026-0002; 팹아웃=정상','NEEDS_CLARIFICATION'),
        ('null_array','사고번호=SYN-2026-0011; 세대=FET','NO_MATCH'),
        ('empty_array_source','사고번호=SYN-2026-0013; 세대=D1a','NO_MATCH'),
        ('wrong_lot','사고번호=SYN-2026-0001; 랏번호=SYN-LOT-0009-001; 요청=웨이퍼목록','TOOL_ERROR'),
        ('lot_selection','사고번호=SYN-2026-0001; 랏번호=SYN-LOT-0001-001; 요청=웨이퍼목록','MATCHED'),
        ('month','사고번호=SYN-2026-0001; 발생월=2026년 1월','MATCHED'),
        ('wrong_month','사고번호=SYN-2026-0001; 기간=2026/02','NO_MATCH'),
        ('invalid_month','사고번호=SYN-2026-0001; 기간=2026-13','NEEDS_CLARIFICATION'),
        ('relative_month','사고번호=SYN-2026-0001; 기간=최근','NEEDS_CLARIFICATION'),
        ('title_alias','사고번호=SYN-2026-0001; 사고몀=외곽샷+이디에스페일','MATCHED'),
        ('title_typo','사고번호=SYN-2026-0003; 검색어=chmaber','MATCHED'),
        ('line_alias','사고번호=SYN-2026-0001; 라인명=65l (abcd); 라인별칭=a b c d','MATCHED'),
        ('line_alias_conflict','사고번호=SYN-2026-0001; 라인별칭=IJKL','NO_MATCH'),
        ('not_free_chat','화성 포토 사고 좀 찾아줘','INVALID_REQUEST'),
    ]
    for category,question,status in specials:
        expected={'status':status}
        if status in ('NEEDS_CLARIFICATION','INVALID_REQUEST'):expected['no_business_tools']=True
        if status=='NO_MATCH':expected['incident_ids']=[]
        if status=='MATCHED':
            n=9 if '0009' in question else 3 if '0003' in question else 1
            expected['incident_ids']=[f'synthetic-pk-{n:04}']
            if category=='lot_selection':expected['wafer_count']=settings.data['demo']['wafers_per_lot']
        add(category,question,expected)
    for mode in ['any','all','exact']:
        selected=[]
        want={'D1a','D1z'}
        for r in rows:
            got=set(r['product_generations'] or [])
            if (bool(got&want) if mode=='any' else want<=got if mode=='all' else got==want):selected.append(r['incident_id'])
        add('array_'+mode,f'세대=디원에이,디원지; 세대조건={mode}; 요청=사고목록',{'status':'MATCHED','incident_ids':selected})
    title_matches=[r['incident_id'] for r in rows if '외곽 Shot' in r['title']]
    add('multiple_incidents','사고명=외곽샷; 요청=웨이퍼목록',{'status':'NEEDS_SELECTION','incident_ids':title_matches})
    add('explicit_incident_selection','사고명=외곽샷; 요청=웨이퍼목록',{'status':'MATCHED','incident_ids':['synthetic-pk-0001'],'wafer_count':60},selected=['synthetic-pk-0001'])
    add('outside_selection','사고명=외곽샷; 요청=웨이퍼목록',{'status':'TOOL_ERROR'},selected=['synthetic-pk-0002'])
    corpus={'notice':'합성 한정 문법 회귀 세트. 정답은 실행 입력에 전달하지 않는다. 실제 LLM/자유 대화 정확도 평가가 아니다.',
            'required_overlay':'config/demo.variants.toml','dictionary_version':dictionary['version'],'cases':cases}
    write_fixture(Path(settings.data['paths']['variant_cases_file']),corpus)
    write_fixture(ROOT/'data/variant_raw_source_rows.json',{'notice':'원본 테이블을 변조하지 않은 별도 raw 표현 fixture. 검증 후 canonical 필터와 대조한다.','rows':raw_rows})
    profiles=[]
    for key in rows[0]:
        vals=[r[key] for r in rows];observed=sorted({json.dumps(v,ensure_ascii=False) for v in vals if v is not None})
        profiles.append({'column':key,'null_count':sum(v is None for v in vals),'distinct_count':len(observed),'sample_values':[json.loads(x) for x in observed[:8]]})
    write_fixture(ROOT.parent/'examples/generated/variants/column_profile.json',{'notice':'합성 SQLite 실제 조회 프로파일. 사내 컬럼 의미/공식값 검증이 아님.','incidents':len(rows),'columns':profiles})
    print(json.dumps({'cases':len(cases),'raw_source_rows':len(raw_rows),'categories':dict(Counter(c['category'] for c in cases))},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);add_config_arguments(parser)
    parser.add_argument('--inputs',action='store_true');parser.add_argument('--cases',action='store_true');args=parser.parse_args()
    if not (args.inputs or args.cases):parser.error('--inputs or --cases required')
    if args.inputs:inputs()
    if args.cases:build_cases(load_config(args.config,args.overlay))
