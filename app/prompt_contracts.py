"""Role output contract checks. No LLM calls, dispatch, ACL or semantic truth proof.

The structural validator intentionally supports only the schema keywords used
by this project's role schemas. Unknown validation keywords fail explicitly.
Runtime context must be supplied by trusted application code, not question text.
"""
from pathlib import Path
from skill_loader import read_role_reference

ROOT = Path(__file__).resolve().parent


def inspection_rows(plan):
    if plan is None:
        return []
    return ([{'kind': 'historical_match', **row} for row in plan['historical_matches']]
            + [{'kind': 'check', **row} for row in plan['checks']]
            + [{'kind': 'eds_followup', **plan['eds_followup']}])


def structure(value, schema, path='$'):
    supported={'type','enum','required','properties','additionalProperties','items','minimum','description','title','$schema'}
    if set(schema)-supported:raise ValueError('UNSUPPORTED_SCHEMA_KEYWORD')
    types=schema.get('type');types=types if isinstance(types,list) else [types] if types else []
    kinds={'object':dict,'array':list,'string':str,'integer':int,'number':(int,float),'boolean':bool,'null':type(None)}
    if types and not any(type(value) in (kinds[t] if isinstance(kinds[t],tuple) else (kinds[t],)) for t in types):
        actual=next((name for name,kind in kinds.items() if type(value) in (kind if isinstance(kind,tuple) else (kind,))),type(value).__name__)
        raise ValueError('TYPE: '+path+'; expected '+ '|'.join(types)+'; got '+actual)
    if 'enum' in schema and value not in schema['enum']:raise ValueError('ENUM: '+path)
    if 'minimum' in schema and value<schema['minimum']:raise ValueError('MINIMUM: '+path)
    if isinstance(value,dict):
        if set(schema.get('required',[]))-set(value):raise ValueError('REQUIRED: '+path)
        props=schema.get('properties',{})
        if schema.get('additionalProperties') is False and set(value)-set(props):raise ValueError('ADDITIONAL_PROPERTY: '+path)
        for key,item in value.items():
            if key in props:structure(item,props[key],path+'.'+key)
    if isinstance(value,list) and 'items' in schema:
        for i,item in enumerate(value):structure(item,schema['items'],f'{path}[{i}]')


def validate_output(role, output, context):
    if role not in ('router','judge','answer'):raise ValueError('UNKNOWN_ROLE')
    schema_root=Path(context.get('skills_root',ROOT/'skills'))
    schema=read_role_reference(role,'output.schema.json',schema_root,context.get('registry_file',ROOT/'skill_registry.json'))
    structure(output,schema)
    if role=='router':
        decision=output['decision'];plan=output['plan']
        request_scope=context.get('request_scope','incident')
        if request_scope not in ('auto','incident','independent'):raise ValueError('INVALID_REQUEST_SCOPE')
        if request_scope=='auto':
            if decision not in ('route','clarify','blocked'):raise ValueError('ROUTE_REQUIRED_BEFORE_TOOLS')
            if plan or output['filters'] or output['search_mode']!='none' or output['needs_skills']:raise ValueError('ROUTE_CANNOT_EXECUTE')
            if output['stage'] not in ('incident','independent'):raise ValueError('INVALID_ROUTE')
            if decision=='route' and output['clarification'] is not None:raise ValueError('UNRESOLVED_ROUTE')
        elif decision=='route':raise ValueError('REQUEST_SCOPE_ALREADY_FIXED')
        if request_scope=='independent':
            if output['stage']!='independent' or output['filters'] or output['search_mode']!='none':raise ValueError('INDEPENDENT_REQUEST_CANNOT_QUERY_INCIDENTS')
        elif request_scope=='incident' and output['stage']=='independent':raise ValueError('INCIDENT_REQUEST_CANNOT_SKIP_LOOKUP')
        if decision!='execute' and plan:raise ValueError('NON_EXECUTE_HAS_PLAN')
        if decision=='execute':
            if not plan:raise ValueError('EXECUTE_REQUIRES_PLAN')
            if context.get('budget_remaining',0)<len(plan):raise ValueError('TOOL_BUDGET_EXCEEDED')
            if output['clarification'] is not None or output['needs_skills']:raise ValueError('UNRESOLVED_EXECUTION: execute requires clarification=null (not an empty string) and needs_skills=[]; use clarify or load_skills separately')
            if output['stage']=='tools' and not context.get('scope_valid'):raise ValueError('INCIDENT_SCOPE_REQUIRED')
            for i,step in enumerate(plan):
                tool=context.get('available_tools',{}).get(step['tool'],{})
                if not tool.get('enabled'):raise ValueError('TOOL_UNAVAILABLE')
                if tool.get('stage')!=output['stage']:raise ValueError('TOOL_STAGE_MISMATCH')
                if output['stage']=='incident' and output['search_mode'] not in tool.get('search_modes',[]):raise ValueError('SEARCH_MODE_UNSUPPORTED')
                if output['stage']=='tools' and output['search_mode']!='none':raise ValueError('FOLLOWUP_SEARCH_MODE_MUST_BE_NONE')
                if any(j>=i for j in step['depends_on']):raise ValueError('DEPENDENCY_MUST_PRECEDE_STEP')
                if 'fields' in step['arguments'] and not set(step['arguments']['fields']).issubset(context.get('mapped_fields',[])):
                    raise ValueError('SEARCH_FIELD_UNAVAILABLE')
        if decision=='clarify' and (not output['clarification'] or not output['clarification'].strip()):raise ValueError('CLARIFICATION_REQUIRED')
        if decision=='blocked' and not output['limitations']:raise ValueError('BLOCK_REASON_REQUIRED')
        if decision=='load_skills' and not output['needs_skills']:raise ValueError('SKILL_REQUEST_REQUIRED')
        if decision=='ready_for_judge' and request_scope=='incident' and not context.get('incident_checked'):raise ValueError('INCIDENT_CHECK_REQUIRED')
    elif role=='judge':
        verdict=output['verdict']
        expected='router' if verdict in ('need_evidence','revise') else 'answer'
        if output['return_to']!=expected:raise ValueError('WRONG_JUDGE_DESTINATION')
        coverage=output['coverage'];requirements=[r['requirement'] for r in coverage]
        if len(requirements)!=len(set(requirements)) or set(requirements)!=set(context.get('requirements',[])):
            raise ValueError('REQUIREMENT_COVERAGE_MISMATCH')
        for row in [*coverage,*output['issues']]:
            if not set(row['evidence_ids']).issubset(context.get('evidence_ids',[])):raise ValueError('UNKNOWN_EVIDENCE')
        if verdict=='pass':
            if output['issues']:raise ValueError('PASS_HAS_UNRESOLVED_ISSUES')
            if context.get('code_gate')!='PASS':raise ValueError('CODE_GATE_NOT_PASSED')
            if not coverage or any(r['status']!='satisfied' or not r['evidence_ids'] for r in coverage):raise ValueError('MISSING_PASS_EVIDENCE')
        if verdict in ('need_evidence','revise') and context.get('budget_remaining',0)<=0:raise ValueError('NO_RETRIEVAL_BUDGET')
        if verdict!='pass' and not output['issues']:raise ValueError('ISSUE_REQUIRED')
    elif role=='answer':
        if not output['answer'].strip():raise ValueError('EMPTY_ANSWER')
        if any(not item.strip() for item in output['limitations']):raise ValueError('EMPTY_LIMITATION')
        if output['status'] in ('answered','partial') and not output['claims']:raise ValueError('CLAIMS_REQUIRED')
        verdict=context.get('judge_verdict')
        if verdict not in ('pass','abstain') and (output['status']!='unavailable' or output['claims']):raise ValueError('ANSWER_CALLED_BEFORE_JUDGE')
        if output['status']=='answered' and verdict!='pass':raise ValueError('ANSWERED_REQUIRES_JUDGE_PASS')
        if output['status']=='unavailable' and output['claims']:raise ValueError('UNAVAILABLE_HAS_CLAIMS')
        if output['status'] in ('partial','unavailable') and not output['limitations']:raise ValueError('LIMITATION_REQUIRED')
        ids=[]
        for claim in output['claims']:
            if not claim['claim_id'].strip() or not claim['text'].strip():raise ValueError('EMPTY_CLAIM')
            ids.append(claim['claim_id'])
            if not claim['evidence_ids'] or not set(claim['evidence_ids']).issubset(context.get('evidence_ids',[])):raise ValueError('UNKNOWN_EVIDENCE')
        if len(ids)!=len(set(ids)):raise ValueError('DUPLICATE_CLAIM_ID')
        inspections=inspection_rows(output.get('inspection_plan'))
        if len(inspections)>6:raise ValueError('INSPECTION_PLAN_TOO_LONG')
        if inspections and (verdict not in ('pass','abstain') or output['status']=='unavailable'):
            raise ValueError('INSPECTION_PLAN_WITHOUT_REVIEWED_EVIDENCE')
        if context.get('inspection_requested') and output['status'] in ('answered','partial'):
            kinds={row['kind'] for row in inspections}
            if not {'check','eds_followup'}.issubset(kinds):raise ValueError('INSPECTION_PLAN_REQUIRED')
            verified=set(context.get('verified_historical_reference_ids',[]))
            if verified and not any(row['kind']=='historical_match' and row['target'] in verified for row in inspections):
                raise ValueError('HISTORICAL_COMPARISON_REQUIRED')
        if sum(row['kind']=='check' for row in inspections)>3 or sum(row['kind']=='historical_match' for row in inspections)>2:
            raise ValueError('INSPECTION_KIND_LIMIT')
        for row in inspections:
            if any(not row[key].strip() for key in ('target','basis','comparison')):raise ValueError('EMPTY_INSPECTION_FIELD')
            if not row['evidence_ids'] or not set(row['evidence_ids']).issubset(context.get('evidence_ids',[])):
                raise ValueError('UNKNOWN_EVIDENCE')
            if row['kind']=='historical_match':
                reference=context.get('historical_reference_evidence',{}).get(row['target'],[])
                if not set(reference).intersection(row['evidence_ids']):raise ValueError('UNKNOWN_HISTORICAL_REFERENCE')
    else:raise ValueError('UNKNOWN_ROLE')
    return True
