"""Bounded read-only milestoneV6 projection; V5 remains a separate historical artifact."""
from copy import deepcopy
from pathlib import Path
import hashlib,re
try:
    from .cohort_milestone_summary import _bounded,_count,_strings
except ImportError:
    from cohort_milestone_summary import _bounded,_count,_strings


def _false(value):
    if value is not False:raise ValueError('unestablished quality/production/completion must remain false')

def _proofs(proofs,root):
    if not isinstance(proofs,dict) or not 1<=len(proofs)<=32:raise ValueError('proof publication cap is32')
    for entry in proofs.values():
        if not isinstance(entry,dict) or set(entry)!={'path','sha256'}:raise ValueError('proof descriptor shape invalid')
        p=Path(entry['path']);digest=entry['sha256']
        if not p.is_absolute() or not p.resolve().is_relative_to(root.resolve()) or p.suffix.lower() not in {'.json','.md'}:raise ValueError('proof path outside approvedlabJSON/MD assets')
        if not isinstance(digest,str) or not re.fullmatch('[a-fA-F0-9]{64}',digest):raise ValueError('proof hash invalid')
        if not p.is_file() or p.stat().st_size>32*1024*1024:raise ValueError('missing or oversized proof')
        h=hashlib.sha256()
        with p.open('rb') as stream:
            for block in iter(lambda:stream.read(1048576),b''):h.update(block)
        if h.hexdigest()!=digest.lower():raise ValueError('proof hash mismatch')


def milestone_summary_v6(source,root:Path):
    if source is None:return None
    if not isinstance(source,dict) or source.get('schema_id')!='qagent.skip_research_milestone.v6':raise ValueError('unexpected V6milestone schema')
    _bounded(source)
    if source.get('fab_sample_origin')!='procedural_synthetic':raise ValueError('synthetic-only research required')
    for key in ('production_validation','production_execution','general_llm_quality_established'):_false(source.get(key))
    if source.get('new_actions')!=0 or type(source['new_actions']) is not int:raise ValueError('new actions prohibited')
    v=source['actual_v8'];history=source['quality_history'];world=source['full_world'];cf=source['CF4']
    if v['case_dataset']!='skip-world-v1' or v['citation_owner']!='validated_code_catalog' or v['number_owner']!='deterministic_source_projection' or v['raw_slots_owner']!='actual_local_llm':raise ValueError('V8dataset/ownership separation invalid')
    if v['model_calls']!=3 or v['tool_calls']!=20 or v['first_business_tool']!='search_incident_db' or v['connected_to_llm_roles'] is not True or v['read_only'] is not True:raise ValueError('V8actualgraph contract invalid')
    for key in ('free_citation_quality_measured','general_llm_quality_established','raw_output_automatically_repaired','compatible_numeric_model_inference'):_false(v[key])
    for key in ('receipt_count','new_actions'):
        _count(v[key])
        if v[key]!=0:raise ValueError('V8hasnoactionsorreceipts')
    _strings(v['limits'])
    for value in v['scope_counts'].values():_count(value)
    c=v['scope_counts']
    if c['current_outcome_queries']!=0 or c['current_event_intersection']>min(c['current_wafers'],c['independent_event_wafers']) or c['current_down_exposed_wafers']>c['current_wafers']:raise ValueError('scope/outcome boundary invalid')
    if type(v['future_yield_point']) not in (int,float) or not 0<=v['future_yield_point']<=1:raise ValueError('future rate must be a fraction')
    if v['numeric_mode']!='descriptive_only' or v['schema_status']!='ambiguous' or v['cause_status']!='unconfirmed' or v['normal_counterexample']!='not_established':raise ValueError('material gaps cannot be upgraded')
    slot_ids=['chronic','acute','history','image','trend'];assessments=['candidate','observed_exposure','context_only','pattern_signal','descriptive_only']
    if [(r['id'],r['assessment']) for r in v['raw_answer_slots']]!=list(zip(slot_ids,assessments)):raise ValueError('actual assessment slot shape invalid')
    claims=v['compiled_claims']
    if [r['id'] for r in claims]!=['H_CHRONIC','H_ACUTE','H_HISTORY','H_IMAGE','H_TREND']:raise ValueError('fivecodeclaimsrequired')
    for row in claims:
        for key in ('support_fact_ids','caution_fact_ids'):
            if not isinstance(row[key],list) or len(row[key])>32 or any(not isinstance(s,str) or not re.fullmatch(r'F(?:[1-9]|[12][0-9]|3[0-2])',s) for s in row[key]):raise ValueError('claim citations invalid')
    if len(v['image_views'])!=2 or {r['view'] for r in v['image_views']}!={'wafer_context','chip_crop'}:raise ValueError('both imageviews required')
    positives=set()
    for row in v['image_views']:
        if len(row['scores'])!=2 or len(row['thresholds'])!=2 or len(row['above'])!=2:raise ValueError('image target decisions incomplete')
        if any(type(x) not in (int,float) or not 0<=x<=1 for x in row['scores']+row['thresholds']):raise ValueError('image score invalid')
        if row['above']!=[s>=t for s,t in zip(row['scores'],row['thresholds'])] or row['annotation_time_qualified'] is not False:raise ValueError('image threshold/time boundary changed')
        if any(row['above']):positives.add(row['id'])
    if not set(claims[3]['support_fact_ids'])<=positives or not set(claims[4]['support_fact_ids'])<={'F21','F22'}:raise ValueError('image/trend evidence mixed')
    if history['v7_status']!='rejected_as_final_answer' or history['v7_raw_repaired'] is not False or history['legacy_v5_preserved'] is not True:raise ValueError('failed/history evidence must be preserved')
    _strings(history['v7_issues'])
    for key in ('v7_model_calls','v7_tool_calls','legacy_v6_MES_receipt_replays','legacy_v6_new_actions'):_count(history[key])
    if world['dataset']!='integrated-world-v2-full-v3' or world['weeks']!=96 or world['target_count']!=135 or world['target_groups']!={'Yield':1,'overlapping_signatures':6,'electrical_Measure_means':128}:raise ValueError('fullworld/135target units invalid')
    if world['target_units']!={'first7':'cohort_fraction','last128':'SYN_SEVERITY'}:raise ValueError('fraction vsMeasure units invalid')
    for group in ('counts','eligible_splits','supervised_rows'):
        for value in world[group].values():_count(value)
    for key in ('trainval_target_rows','whole_cohort_unknown_rows','confirmation_target_queries'):_count(world[key])
    if sum(world['eligible_splits'].values())!=world['counts']['eligible_rows'] or world['trainval_target_rows']!=world['eligible_splits']['train']+world['eligible_splits']['validation'] or sum(world['supervised_rows'].values())+world['whole_cohort_unknown_rows']!=world['trainval_target_rows']:raise ValueError('feature/supervised/unknown row denominators disagree')
    if world['original_memberships_preserved'] is not True or world['cutoffs_extended'] is not False or world['confirmation_target_queries']!=0:raise ValueError('membership/cutoff/confirmation boundary invalid')
    fit=world['fit_status']
    if fit['status']!='running' or fit['completed_fits'] is not None or fit['planned_nonfixture_fits']!=6:raise ValueError('onlysavedRUNNINGstatuspublished')
    for key in ('completion_established','performance_metrics_published','new_GPU_or_fit_launched_by_UI'):_false(fit[key])
    _strings(world['limits'])
    for key in ('worlds','rows','target_count'):_count(cf[key])
    delta=cf['normalized_macro_delta'];ci=cf['normalized_ci95']
    if type(delta) not in (int,float) or not isinstance(ci,list) or len(ci)!=2 or any(type(x) not in (int,float) for x in ci) or not ci[0]<=delta<=ci[1] or not ci[0]<=0<=ci[1] or cf['ci_includes_zero'] is not True:raise ValueError('CF4primaryCI mustretainzero')
    _false(cf['increment_established']);_false(cf['auto_promotion']);_strings(cf['regressing_families']);_strings(cf['limits']);_strings(source['pending'])
    if [r['id'] for r in source['analysis_tracks']]!=['future_cohort_forecast','observed_chip_diagnosis','acute_equipment_exposure']:raise ValueError('three tasktracksrequired')
    _proofs(source['proofs'],root)
    names=('schema_id','created_at_utc','fab_sample_origin','production_validation','production_execution','general_llm_quality_established','new_actions','goal_status','actual_v8','quality_history','full_world','CF4','analysis_tracks','pending')
    result={key:deepcopy(source[key]) for key in names};result['proof_count']=len(source['proofs'])
    # No filepaths/rawprompts/unfilteredsource objects are served.
    return result
