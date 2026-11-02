"""Read-only first-confirmation publication from ROOT's bounded accepted proofs."""
from copy import deepcopy
from datetime import datetime,timedelta
import json,math
from pathlib import Path
try:
 from .cohort_milestone_summary import _bounded,_count
 from .cohort_milestone_summary_v6 import _proofs
except ImportError:
 from cohort_milestone_summary import _bounded,_count
 from cohort_milestone_summary_v6 import _proofs


def _number(value):
 if type(value) not in (int,float) or not math.isfinite(value):raise ValueError('finite confirmation metric required')
 return value


def _same_descriptor(left,right):
 return Path(left['path']).resolve()==Path(right['path']).resolve() and left['sha256']==right['sha256']


def milestone_summary_v6_2(source,root:Path):
 if source is None:return None
 if not isinstance(source,dict) or source.get('schema_id')!='qagent.skip_research_milestone.v6.2' or source.get('status')!='accepted_first_confirmation_limited':raise ValueError('unexpected confirmation publication schema/status')
 _bounded(source)
 for key in ('snapshot_is_live','production_validation','production_execution','full_world_end_to_end_LLM_connected','general_LLM_quality_established','observed14fits_changed'):
  if source.get(key) is not False:raise ValueError('unestablished quality/integration must remain false')
 if source.get('synthetic') is not True or type(source.get('new_actions')) is not int or source['new_actions']!=0:raise ValueError('synthetic read-only snapshot required')
 if source.get('target_grain')!='weekly_anchor_context_cohort_aggregate' or source.get('dataset')!='integrated-world-v2-full-v3' or source.get('v3_first_point_residual_bug_preserved') is not True or source.get('corrected_v4_is_separate_study') is not True:raise ValueError('cohort grain/v3 limitation must be explicit')
 if datetime.fromisoformat(source['created_at_utc']).utcoffset()!=timedelta(0):raise ValueError('UTC snapshot required')
 refs=source['proofs']
 if set(refs)!={'root_acceptance','scored_result','arithmetic_audit','selected_source_SQL_audit'}:raise ValueError('ROOT and both independent audits required')
 _proofs(refs,root)
 objects={key:json.loads(Path(ref['path']).read_text(encoding='utf-8')) for key,ref in refs.items()}
 accepted=objects['root_acceptance'];score=objects['scored_result'];audits=accepted['independent_audits']
 if accepted.get('status')!='ROOT_accepted_first_confirmation_arithmetic_and_selected_source_SQL' or len(audits)!=2:raise ValueError('limited ROOT acceptance required')
 if not _same_descriptor(accepted['scored_result'],refs['scored_result']) or any(not _same_descriptor(audits[i],refs[key]) for i,key in enumerate(('arithmetic_audit','selected_source_SQL_audit'))):raise ValueError('acceptance/proof descriptor mismatch')
 if objects['arithmetic_audit'].get('status')!='PASS_independent_cached_arithmetic' or objects['selected_source_SQL_audit'].get('status')!='PASS_selected_confirmation_targets_recomputed_from_source_SQL':raise ValueError('both independent audits must pass')
 population=accepted['population']
 if population!={'synthetic_worlds':1,'calendar_weeks':18,'cohort_views':3456,'targets':135,'whole_cohort_unknown_rows':0}:raise ValueError('one-world confirmation population/support required')
 for value in population.values():_count(value)
 for key in ('reselection_or_automatic_promotion','query_or_action_adapter_registered','site_production_or_LLM_validation'):
  if accepted.get(key) is not False:raise ValueError('no reselection/promotion/site integration')
 if accepted.get('validation_selected_model')!='MLP-full two fixed seed ensemble; unchanged':raise ValueError('validation MLP selection must remain fixed')
 if score['primary_block']!=4 or score['sensitivity_blocks']!=[3,6,8] or score['bootstrap_repetitions']!=2000 or score['seed']!=2026102601 or score['selected_MLP_immutable'] is not True or score['confirmation_reselection'] is not False:raise ValueError('fixed paired week bootstrap and selection required')
 methods=[]
 names=['MLP-full','NumericPatch-cross-item','NumericPatch-current-token','CatBoost-summary','train-mean']
 if list(accepted['methods'])!=names or list(score['method_metrics'])!=names:raise ValueError('all5 fixed methods required')
 for name in names:
  model=accepted['methods'][name];saved=score['method_metrics'][name]
  if _number(model['balanced_normalized_mae'])<0 or len(model['task_normalized_mae'])!=3:raise ValueError('balanced3task metrics required')
  if model['balanced_normalized_mae']!=saved['balanced_normalized_mae'] or model['task_normalized_mae']!=saved['task_normalized_mae']:raise ValueError('method metrics differ from score proof')
  for value in model['task_normalized_mae']:
   if _number(value)<0:raise ValueError('negative task error')
  if len(saved['target_observed_rows'])!=135 or any(type(n) is not int or n!=3456 for n in saved['target_observed_rows']):raise ValueError('complete135target support required; missing is not zero')
  for key in ('per_target_raw_mae','per_target_normalized_mae'):
   if len(saved[key])!=135 or any(_number(n)<0 for n in saved[key]):raise ValueError('all135 errors must be preserved')
  methods.append({'family':name,**deepcopy(model)})
 primary_name='NumericPatch-current-token_minus_NumericPatch-cross-item'
 if accepted['primary_comparison']!=primary_name or score['primary_comparison']!=primary_name:raise ValueError('prespecified primary comparison changed')
 comparisons=[]
 for name,row in accepted['comparisons'].items():
  saved=score['comparisons'][name];ci=row['B4_unadjusted_descriptive_ci95'];delta=_number(row['balanced_normalized_difference'])
  if delta!=saved['balanced_normalized_difference'] or ci!=saved['bootstrap']['4']['balanced']['ci95'] or row['regressing_targets']!=saved['regressing_targets']:raise ValueError('comparison differs from fixed score proof')
  if len(ci)!=2 or _number(ci[0])>_number(ci[1]):raise ValueError('ordered finite CI required')
  _count(row['regressing_targets_count'])
  if row['regressing_targets_count']!=len(row['regressing_targets']) or row['regressing_targets_count']>135 or row['unsupported_targets']:raise ValueError('regression/support accountability invalid')
  comparisons.append({'comparison':name,'role':row['role'],'difference':delta,'ci95':ci,'regressing_targets':row['regressing_targets_count']})
 primary=next(x for x in comparisons if x['comparison']==primary_name)
 if primary['difference']<=0 or primary['ci95'][0]<=0 or primary['role']!='primary_prespecified_ablation':raise ValueError('actual primary worsening direction must remain explicit')
 mlp=next(x for x in comparisons if x['comparison']=='MLP-full_minus_train-mean')
 if mlp['regressing_targets']!=55:raise ValueError('MLP per-target regressions cannot be hidden')
 order=accepted['stage_order']
 if order.get('predict_rootgate_labels_score_order_verified') is not True:raise ValueError('prediction gate before labels required')
 scope=objects['selected_source_SQL_audit']['scope']
 if scope['selected_rows']!=12 or scope['unique_member_wafers']!=268:raise ValueError('selected SQL audit scope must remain limited')
 result={k:deepcopy(v) for k,v in source.items() if k!='proofs'}
 result.update(population=deepcopy(population),methods=methods,primary=primary,comparisons=comparisons,
  selection_unchanged=True,MLP_regressing_targets_vs_mean=55,proof_count=len(refs),
  accepted_at_utc=accepted['created_at_utc'],limits=deepcopy(accepted['limits']),
  sql_audit_scope={'selected_cohorts':12,'unique_Wafers':268,'Chips':8576,'all135_targets':True,'every_cohort_independently_requeried':False},
  bootstrap={'primary_block':4,'sensitivity_blocks':[3,6,8],'draws':2000,'seed':2026102601,'unit':'whole_calendar_week_all_context_anchor_views','unadjusted_descriptive':True},
  historical_context={'old_world_V8_connected_Tools':20,'old_world_V8_local_LLM_calls':3,'new_full_world_end_to_end_LLM_connected':False,'observed14fits_retained':True})
 _bounded(result)
 return result
