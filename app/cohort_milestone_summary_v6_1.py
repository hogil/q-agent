"""Bounded read-only completion snapshot; historical V6/V5 projections stay separate."""
from copy import deepcopy
from datetime import datetime,timedelta
from pathlib import Path
import math
try:
 from .cohort_milestone_summary import _bounded,_count,_strings
 from .cohort_milestone_summary_v6 import _proofs
except ImportError:
 from cohort_milestone_summary import _bounded,_count,_strings
 from cohort_milestone_summary_v6 import _proofs

def _false(value):
 if value is not False:raise ValueError('unestablished integration/quality/action must stay false')
def _metric(value,upper=10):
 if type(value) not in (int,float) or not math.isfinite(value) or not 0<=value<=upper:raise ValueError('finite metric with correct units required')

def milestone_summary_v6_1(source,root:Path):
 if source is None:return None
 if not isinstance(source,dict) or source.get('schema_id')!='qagent.skip_research_milestone.v6.1' or source.get('status')!='completed_standalone_components_validation_only':raise ValueError('unexpected completion schema/status')
 _bounded(source)
 for key in ('snapshot_is_live','production_validation','production_execution','full_world_end_to_end_LLM_connected','general_LLM_quality_established'):_false(source.get(key))
 if source.get('synthetic') is not True:raise ValueError('synthetic snapshot required')
 _count(source.get('new_actions'))
 if source['new_actions']!=0:raise ValueError('new actions prohibited')
 if datetime.fromisoformat(source['created_at_utc']).utcoffset()!=timedelta(0):raise ValueError('UTC snapshot timestamp required')
 f=source['future_135'];o=source['observed_chip'];cf=source['confirmation'];e=source['equipment'];r=source['RAG'];profile=source['schema_profile'];w=source['full_world']
 if f['status']!='completed' or f['nonfixture_fits']!=8 or f['fixed6_fits']!=6 or f['ablation_fits']!=2 or f['validation_informed_search'] is not True or f['seeds']!=[17,29] or f['target_count']!=135:raise ValueError('fixed8fit/135target completion contract required')
 for k in ('nonfixture_fits','fixed6_fits','ablation_fits','target_count','validation_rows','observed_rows_per_target','all_target_unknown_validation_rows'):_count(f.get(k))
 if f['observed_rows_per_target']+f['all_target_unknown_validation_rows']!=f['validation_rows'] or f['selected_family']!='MLP-full' or f['selection_status']!='validation_selected_immutable' or f['arithmetic_audit_status']!='accepted_cached_arithmetic_only':raise ValueError('validation denominator/selection/audit invalid')
 for k in ('serving_promotion','current_token_improved'):_false(f[k])
 if f['all135_errors_preserved_in_proof'] is not True:raise ValueError('all135 error accountability required')
 names=['MLP-full','NumericPatch-cross-item','NumericPatch-current-token','CatBoost-summary','train_mean_center_tiled']
 if [m['family'] for m in f['models']]!=names:raise ValueError('all fixed model and baseline results required')
 scores={}
 for model in f['models']:
  _metric(model['balanced_normalized_mae']);scores[model['family']]=model['balanced_normalized_mae']
  if len(model['task_normalized_mae'])!=3:raise ValueError('three task metrics required')
  for v in model['task_normalized_mae']:_metric(v)
  if model['nonfixture_fits']!=(0 if model['family']==names[-1] else 2):raise ValueError('baseline is not another fit')
 if scores['MLP-full']>min(scores[n] for n in names[:-1])+1e-4 or scores['NumericPatch-current-token']<=scores['NumericPatch-cross-item']:raise ValueError('validation selection/failed ablation changed')
 if [a['comparator'] for a in f['regressions']]!=[names[1],names[0],names[3],names[4]]:raise ValueError('all comparator regression summaries required')
 for row in f['regressions']:
  for k in ('worse','better','ties'):_count(row.get(k))
  if row['worse']+row['better']+row['ties']!=135:raise ValueError('regression counts must account for135targets')
 if o['status']!='completed' or o['nonfixture_fits']!=14 or o['CatBoost_binary_fits']!=12 or o['TabM_fits']!=2 or o['seeds']!=[17,29] or o['task']!='known_configured_Rule_emulation' or o['arithmetic_audit_status']!='accepted_cached_arithmetic_only':raise ValueError('observed Rule-emulation completion contract invalid')
 for k in ('physical_discovery','unseen_defect_recognition_established','Yield_in_encoder'):_false(o[k])
 if o['exact_Rule_Tool_remains_authority'] is not True or o['binary_Yield_role']!='report_only' or o['raw_measure_count']!=128 or o['encoded_feature_count']!=256 or o['target_signatures']!=6:raise ValueError('Measure/Rule/Yield units or authority changed')
 for k in ('validation_rows','known_entries','unknown_entries','all_known_rows','zero_known_rows','all_negative_Yield0_rows'):_count(o.get(k))
 if o['known_entries']+o['unknown_entries']!=o['validation_rows']*6 or o['all_known_rows']+o['zero_known_rows']>o['validation_rows']:raise ValueError('known/Unknown support inconsistent')
 _metric(o['CatBoost_macro_AP'],1);_metric(o['TabM_macro_AP'],1)
 if profile['status']!='completed_train_only_profile' or profile['table_count']!=13 or profile['column_count']!=262 or profile['train_weeks']!=[0,57]:raise ValueError('training-only13table/262column profile required')
 _false(profile['sampling_policy_availability_verified']);_false(profile['fault_scope_end_availability_verified'])
 for key in ('indexed_chunks','indexed_documents','truncated_passages','Korean_queries'):_count(r.get(key))
 if r['indexed_chunks']!=152 or r['Korean_queries']!=2 or r['original_formats_read']!=['docx','pptx'] or r['source_case_world']!='skip-world-v1_history':raise ValueError('isolated RAG source scope invalid')
 _false(r['full_world_LLM_connected']);_false(r['cause_confirmed'])
 for key in ('candidates','strata_total','supported_strata','unsupported_strata','independently_recomputed_supported_strata','acute_policy_overlap_Wafers','production_actions'):_count(e.get(key))
 if e['dataset']!='integrated-world-v2-full-v3' or e['train_weeks']!=[0,57] or e['candidates']!=64 or e['supported_strata']+e['unsupported_strata']!=e['strata_total'] or e['independently_recomputed_supported_strata']>e['supported_strata'] or e['production_actions']!=0:raise ValueError('descriptive equipment scope/support invalid')
 _false(e['causal_discovery'])
 if cf['status'] not in {'SEALED_IN_THIS_SNAPSHOT','PREDICTIONS_ACCEPTED_SCORE_PENDING'} or cf['CPU_v1_replay']!='FAIL' or cf['original_CUDA_single_checkpoint']!='PASS' or cf['CPU_failure_family']!='NumericPatch-cross-item' or cf['CPU_failure_seed']!=17 or cf['CPU_failure_cells']!=4 or cf['original_CUDA_single_rows']!=1152 or cf['original_CUDA_single_max_abs']!=0 or cf['tolerance']!=2e-5 or cf['CPU_failure_max_abs']<=cf['tolerance']:raise ValueError('failed CPU/full-gate scope must be preserved')
 for k in ('confirmation_metrics_published','exact_GPU_operator_cause_verified'):_false(cf[k])
 if cf['status']=='SEALED_IN_THIS_SNAPSHOT':_false(cf['full8_checkpoint4_ensemble_gate_published'])
 else:
  if cf['full8_checkpoint4_ensemble_gate_published'] is not True or cf.get('ROOT_all5_gate_accepted') is not True or cf.get('full_replay_max_abs')!=0 or cf.get('prediction_archives')!=5 or cf.get('prediction_rows')!=3456 or cf.get('prediction_targets')!=135:raise ValueError('full replay/all5 gate snapshot incomplete')
  if not {'confirmation_full_replay_acceptance','confirmation_all5_ROOT_gate','confirmation_source_freeze','confirmation_prediction_manifest'}.issubset(source['proofs']):raise ValueError('full replay/all5 proof pins required')
 if cf['status_as_of_utc']!=source['created_at_utc']:raise ValueError('confirmation state must share immutable snapshot asof')
 if w['dataset']!='integrated-world-v2-full-v3' or w['target_count']!=135 or w['whole_cohort_unknown_rows']!=10:raise ValueError('fullworld denominator provenance invalid')
 h=source['history_preserved']
 if h!={'V8_old_case_dataset':'skip-world-v1','V8_connected_Tools':20,'V8_local_LLM_calls':3,'V8_citations_numbers_owner':'code','V7_failed_Answer_preserved':True,'CF4_CI_includes_zero':True,'V5_1_and_legacy13_preserved':True}:raise ValueError('prior case/quality/history must remain separate')
 _strings(source['limits']);_proofs(source['proofs'],root)
 keep=('schema_id','created_at_utc','status','snapshot_is_live','synthetic','production_validation','production_execution','new_actions','full_world_end_to_end_LLM_connected','general_LLM_quality_established','full_world','future_135','observed_chip','schema_profile','RAG','equipment','confirmation','history_preserved','limits')
 result={k:deepcopy(source[k]) for k in keep};result['proof_count']=len(source['proofs']);return result
