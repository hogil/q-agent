"""Six registered saved-status summaries; no model, Tool, SQL or arbitrary file dispatch."""
from pathlib import Path
import json
import math

SCHEMA = 'qagent.latest_research_status_sources.v3'
SCHEMA_V4 = 'qagent.latest_research_status_sources.v4'
RECORDS = (
    ('typed_grounding_qlora_scope_withheld', 'QLoRA typed grounding · scope failure'),
    ('native_db_pattern_VAL_only', 'Native METRO · VAL only'),
    ('local_image_negative', 'Local image retrieval · negative result'),
    ('public_tspulse_nyc_negative', 'TSPulse · public NYC Taxi'),
    ('BLLM_V14_tool_return_judge_overflow', 'Actual B V14 · Judge input overflow'),
    ('metro_target_point_probe_and_running_build', 'METRO target-point producer · build complete'),
)
METRO_FINAL_RECORD = ('metro_target_point_int64_v5_weak_subgroup_no_promotion', 'METRO target-point · weak-subgroup regression')
METRO_FINAL_REF_KEYS = frozenset({'review','result','manual_recompute','score_controller','p1_gate','predict_failure','metadata_fix_review'})
METRO_FINAL_METRIC_KEYS = frozenset({
    'baseline_features','expanded_features','baseline_AP','expanded_AP',
    'baseline_TP','expanded_TP','observed_positive_denominator',
    'baseline_FP','expanded_FP','supported_normal_denominator',
    'baseline_unconditional_recall','expanded_unconditional_recall','unconditional_positive_denominator',
    'weak_baseline_TP','weak_expanded_TP','weak_observed_positive_denominator',
    'score_exit_code','predict_cli_exit_code','metadata_fix_review_exit_code','p1_conf_targets_read',
})
CONTRACTS = {
    RECORDS[0][0]: ('typed_record_claim_TEST', 'synthetic', 'training_metric_gain_deployment_withheld', {'TEST_count','baseline_correct','adapter_correct','baseline_accuracy_percent','adapter_accuracy_percent','scope_C_failed','scope_C_total'}),
    RECORDS[1][0]: ('model_selected_VAL_not_TEST', 'synthetic', 'VAL_only_not_independent_TEST', {'baseline_AP','trained_AP','baseline_TP','trained_TP','positive_denominator','baseline_control_alerts','trained_control_alerts','control_denominator'}),
    RECORDS[2][0]: ('fresh_CONF_retrieval_after_P1', 'synthetic', 'negative_local_retrieval', {'LOCAL_known_correct_accept','LOCAL_known_total'}),
    RECORDS[3][0]: ('single_public_NYC_causal_forecast_score', 'public', 'public_negative_no_FAB_transfer', {'TSPulse_AP_rounded','raw_patch_AP_rounded'}),
    RECORDS[4][0]: ('single_actual_integration_Tool_returns_only', 'synthetic', 'Tool_returns_only_Judge_Answer_not_reached', {'Router_returns','Tool_returns','Judge_input_tokens','Judge_cap_tokens','external_API_calls','MES_changes'}),
    RECORDS[5][0]: ('producer_build_only_source_audit_running_no_model_score', 'synthetic', 'full_build_complete_source_audit_running', {'probe_worlds','probe_Wafer_rows','point_slots_per_Wafer','probe_generation_seconds','probe_controller_seconds','probe_sampled_peak_RSS_bytes','planned_full_worlds','full_build_complete','full_build_controller_seconds','full_build_Wafer_rows'}),
}

BLOCKED_RAW_PROJECTION = ('raw_build_complete_projection_dtype_blocked_no_model', 'synthetic',
                          'raw_complete_projection_invalid_fit_blocked')

def contract(record_id):
    return CONTRACTS[record_id]


def _same_ref(left, right):
    return (isinstance(left, dict) and isinstance(right, dict)
            and set(left) == {'path','sha256'} and set(right) == {'path','sha256'}
            and Path(left['path']).resolve(strict=False) == Path(right['path']).resolve(strict=False)
            and isinstance(left['sha256'], str) and isinstance(right['sha256'], str)
            and left['sha256'].lower() == right['sha256'].lower())

def project(record_id, title, refs, root, pin_reader, utc_value):
    if record_id not in CONTRACTS or not isinstance(refs, dict) or set(refs) != {'saved_status'}:
        raise ValueError('unregistered saved-status record/reference')
    reference = refs['saved_status']
    if not isinstance(reference, dict) or set(reference) != {'path','sha256'}:
        raise ValueError('invalid saved-status pin')
    path = Path(reference['path']).resolve()
    if not path.is_relative_to(root.resolve()) or not path.is_file() or path.stat().st_size > 1024*1024:
        raise ValueError('saved-status path/1MiB bound')
    saved, source_sha = pin_reader(reference, root, read_json=True)
    if saved.get('schema_id') != 'qagent.registered_saved_status.v5' or set(saved.get('records', {})) != set(CONTRACTS):
        raise ValueError('exact six saved-status records required')
    row = saved['records'][record_id]
    fields = {'id','status','status_label','summary','evaluation_scope','data_kind','not_production','limitations','metrics','sources','execution_started_utc','execution_ended_utc','root_reviewed_utc'}
    if not isinstance(row, dict) or set(row) != fields:
        raise ValueError('saved-status fields mismatch')
    scope, kind, status, keys = CONTRACTS[record_id]
    if record_id == RECORDS[-1][0] and (row['evaluation_scope'], row['data_kind'], row['status']) == BLOCKED_RAW_PROJECTION:
        scope, kind, status = BLOCKED_RAW_PROJECTION
    if (row['id'] != record_id or row['evaluation_scope'] != scope or row['data_kind'] != kind
            or row['status'] != status or row['not_production'] is not True):
        raise ValueError('saved-status scope/type/status mismatch')
    for key, cap in (('status_label',160),('summary',1600)):
        if not isinstance(row[key], str) or not row[key].strip() or len(row[key]) > cap:
            raise ValueError('bounded saved-status text required')
    limitations = row['limitations']
    if not isinstance(limitations,list) or not 1 <= len(limitations) <= 8 or any(not isinstance(x,str) or not x.strip() or len(x)>600 for x in limitations):
        raise ValueError('bounded explicit limitations required')
    metrics = row['metrics']
    if not isinstance(metrics,dict) or set(metrics) != keys:
        raise ValueError('registered metric keys required')
    for key, value in metrics.items():
        if key == 'full_build_complete':
            if value is not True: raise ValueError('build-complete record requires completed build')
        elif type(value) not in (int,float) or not math.isfinite(value) or value < 0:
            raise ValueError('finite nonnegative saved metric required')
    for numerator,denominator in (('baseline_correct','TEST_count'),('adapter_correct','TEST_count'),('scope_C_failed','scope_C_total'),('baseline_TP','positive_denominator'),('trained_TP','positive_denominator'),('baseline_control_alerts','control_denominator'),('trained_control_alerts','control_denominator'),('LOCAL_known_correct_accept','LOCAL_known_total')):
        if numerator in metrics and (metrics[denominator] <= 0 or metrics[numerator] > metrics[denominator]):
            raise ValueError('invalid saved support denominator')
    sources = row['sources']
    if not isinstance(sources,list) or not 1 <= len(sources) <= 8:
        raise ValueError('bounded saved source list required')
    for source in sources:
        pin_reader(source, root, read_json=False)
    times = {}
    for key in ('execution_started_utc','execution_ended_utc','root_reviewed_utc'):
        value = row[key]
        if value is not None and utc_value(value) is None: raise ValueError('invalid saved timestamp')
        times[key] = value
    label = '공개 데이터' if kind == 'public' else '합성 연구'
    return {'id':record_id,'title':title,'status':status,'status_label':row['status_label'],**times,
            'summary':label+' · '+row['summary'],
            'limitations':['생산 검증·실제 MES 권한·전체 플랫폼 품질 완료를 뜻하지 않습니다.']+limitations,
            'review_source_sha256':source_sha,'metrics':metrics,
            'evaluation_scope':scope,'source_refs':sources,'not_production':True}


def project_metro_final(record_id, title, refs, root, pin_reader, utc_value):
    """Project one exact saved METRO comparison; no fallback or variable record schema."""
    if record_id != METRO_FINAL_RECORD[0] or not isinstance(refs, dict) or set(refs) != METRO_FINAL_REF_KEYS:
        raise ValueError('METRO final record/reference mismatch')

    loaded, actual = {}, {}
    for key in sorted(METRO_FINAL_REF_KEYS):
        loaded[key], actual[key] = pin_reader(refs[key], root, read_json=True)
        if not isinstance(loaded[key], dict):
            raise ValueError('METRO final pinned JSON required')

    review = loaded['review']
    if review.get('status') != 'ROOT_LIMITED_ACCEPTANCE_ONE_SYNTHETIC_PAIRED_RESULT_WEAK_REGRESSION_NO_PROMOTION':
        raise ValueError('METRO final review status mismatch')
    for review_key, ref_key in (('result','result'),('independent_numeric_recompute','manual_recompute'),
                                ('score_controller','score_controller'),('P1','p1_gate'),
                                ('predict_CLI_exit1_preserved','predict_failure')):
        if not _same_ref(review.get(review_key), refs[ref_key]):
            raise ValueError('METRO final review/reference binding mismatch')
    if (review.get('C100_weak_subgroup_promotable') is not False
            or review.get('model_Tool_runtime_or_MES_activation') is not False
            or review.get('full_platform_completed') is not False):
        raise ValueError('METRO final promotion/scope mismatch')

    result = loaded['result']
    manual = loaded['manual_recompute']
    controller = loaded['score_controller']
    p1 = loaded['p1_gate']
    failure = loaded['predict_failure']
    fix = loaded['metadata_fix_review']
    if result.get('status') != 'ONE_FRESH_CONF_SYNTHETIC_STUDY_NOT_PHYSICAL_OR_TOOL_VALIDATION':
        raise ValueError('METRO final result status mismatch')
    if (manual.get('status') != 'ROOT_INDEPENDENT_POST_P1_AP_AUC_COUNTS_RECOMPUTATION_PASS'
            or manual.get('quality_promotion') is not False
            or not _same_ref(manual.get('results'), refs['result'])
            or not _same_ref(manual.get('P1_before_private_reads'), refs['p1_gate'])
            or controller.get('status') != 'PASS' or controller.get('exit_code') != 0
            or controller.get('source_pins_unchanged') is not True
            or controller.get('surviving_owned_PIDs') not in ([], None)
            or controller.get('cleanup_uncertainty') not in (None, '', [])):
        raise ValueError('METRO final score/recompute controller mismatch')
    if (p1.get('status') != 'ROOT_ACCEPTED_TWO_PREDICTIONS_BEFORE_CONF_TARGETS'
            or p1.get('CONF_targets_read') != 0 or p1.get('quality_accepted') is not False
            or p1.get('prediction_worker_CLI_exit_code') != 1
            or not _same_ref(p1.get('preserved_predict_wrapper_failure'), refs['predict_failure'])):
        raise ValueError('METRO final P1/prediction-failure distinction mismatch')
    if (failure.get('child_exit_code') != 1 or failure.get('released') is not True
            or failure.get('surviving_observed_pids') != [] or failure.get('resource_abort') is not None
            or failure.get('wait_timed_out') is not False
            or failure.get('lineage_uncertainty') is not None):
        raise ValueError('METRO final preserved CLI failure mismatch')
    if (fix.get('status') != 'ROOT_REPORTING_METADATA_FIX_RED_TO_GREEN_VERIFIED_NO_SCIENTIFIC_CHANGE'
            or fix.get('exit_code') != 0 or fix.get('original_scientific_artifacts_unchanged') is not True
            or fix.get('future_actual_model_or_full_CLI_run_verified') is not False):
        raise ValueError('METRO reporting-fix scope mismatch')
    try:
        fix_stdout = json.loads(fix.get('stdout', ''))
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError('METRO reporting-fix summary invalid') from exc
    if fix_stdout.get('no_future_model_or_full_CLI_run_claim') is not True:
        raise ValueError('METRO reporting fix must not imply a full model rerun')

    rows = result.get('metrics')
    checks = manual.get('checks')
    strata = result.get('predeclared_strata')
    if not isinstance(rows, list) or len(rows) != 2 or not isinstance(checks, list) or len(checks) != 2 or not isinstance(strata, list) or len(strata) != 2:
        raise ValueError('METRO final two-arm metrics missing')
    by_channels = {row.get('actual_channels'): row for row in rows}
    manual_by_channels = {row.get('actual_channels'): row for row in checks}
    strata_by_channels = {row.get('actual_channels'): row for row in strata}
    if set(by_channels) != {40,100} or set(manual_by_channels) != {40,100} or set(strata_by_channels) != {40,100}:
        raise ValueError('METRO final channels mismatch')
    expected = {40: {'AP':0.9016470131637857,'TP':146,'FP':3,'weak_TP':4},
                100:{'AP':0.9440494516358272,'TP':156,'FP':1,'weak_TP':0}}
    for channels, values in expected.items():
        row, audit = by_channels[channels], manual_by_channels[channels]
        weak = strata_by_channels[channels].get('groups', {}).get('WEAK_1', {})
        if (row.get('source_features') != channels//2 or row.get('AP') != values['AP']
                or row.get('TP_observed_pattern') != values['TP'] or row.get('NO_ADDED_alerts') != values['FP']
                or row.get('observed_positive_denominator') != 231 or row.get('NO_ADDED_supported_denominator') != 248
                or row.get('unconditional_positive_denominator') != 256
                or audit.get('manual_tie_group_AP') != values['AP'] or audit.get('TP') != values['TP']
                or audit.get('FP') != values['FP'] or audit.get('CP975_upper') is None
                or weak.get('TP') != values['weak_TP'] or weak.get('observed_positive') != 38):
            raise ValueError('METRO final reported metrics do not match pinned evidence')
    if (review.get('overall_AP') != [expected[40]['AP'], expected[100]['AP']]
            or review.get('TP') != [146,156] or review.get('FP') != [3,1]
            or review.get('weak_TP') != [4,0] or review.get('weak_observed_positive') != 38):
        raise ValueError('METRO final review summary mismatch')

    metric_rows = {channels: by_channels[channels] for channels in (40,100)}
    metrics = {
        'baseline_features': metric_rows[40]['source_features'], 'expanded_features': metric_rows[100]['source_features'],
        'baseline_AP': metric_rows[40]['AP'], 'expanded_AP': metric_rows[100]['AP'],
        'baseline_TP': metric_rows[40]['TP_observed_pattern'], 'expanded_TP': metric_rows[100]['TP_observed_pattern'],
        'observed_positive_denominator': metric_rows[40]['observed_positive_denominator'],
        'baseline_FP': metric_rows[40]['NO_ADDED_alerts'], 'expanded_FP': metric_rows[100]['NO_ADDED_alerts'],
        'supported_normal_denominator': metric_rows[40]['NO_ADDED_supported_denominator'],
        'baseline_unconditional_recall': metric_rows[40]['unconditional_recall'],
        'expanded_unconditional_recall': metric_rows[100]['unconditional_recall'],
        'unconditional_positive_denominator': metric_rows[40]['unconditional_positive_denominator'],
        'weak_baseline_TP': expected[40]['weak_TP'], 'weak_expanded_TP': expected[100]['weak_TP'],
        'weak_observed_positive_denominator': 38,
        'score_exit_code': controller['exit_code'], 'predict_cli_exit_code': failure['child_exit_code'],
        'metadata_fix_review_exit_code': fix['exit_code'], 'p1_conf_targets_read': p1['CONF_targets_read'],
    }
    if set(metrics) != METRO_FINAL_METRIC_KEYS or any(type(v) not in (int,float) or not math.isfinite(v) or v < 0 for v in metrics.values()):
        raise ValueError('METRO final registered metric fields invalid')
    if (metrics['baseline_TP'] > metrics['observed_positive_denominator']
            or metrics['expanded_TP'] > metrics['observed_positive_denominator']
            or metrics['baseline_FP'] > metrics['supported_normal_denominator']
            or metrics['expanded_FP'] > metrics['supported_normal_denominator']
            or metrics['weak_baseline_TP'] > metrics['weak_observed_positive_denominator']
            or metrics['weak_expanded_TP'] > metrics['weak_observed_positive_denominator']):
        raise ValueError('METRO final count denominator invalid')

    source_refs = [refs[key] for key in ('review','result','manual_recompute','score_controller','p1_gate','predict_failure','metadata_fix_review')]
    return {
        'id': record_id, 'title': title, 'status': 'weak_subgroup_regression_no_promotion',
        'status_label': '전체 AP 상승 · weak 4/38→0/38 · 승격 보류',
        'execution_started_utc': None, 'execution_ended_utc': None,
        'root_reviewed_utc': utc_value(review.get('created_utc')),
        'summary': '한 synthetic CONF에서 20→50개 feature의 AP는 0.901647→0.944049, TP는 146→156/231, FP는 3→1/248이었습니다. Weak-pattern subgroup은 4/38→0/38로 악화되어 모델 승격은 보류합니다.',
        'limitations': [
            '20 대 50 feature 비교에서 입력 feature와 모델 head parameter 수가 함께 달라져 단일 요인의 인과효과로 볼 수 없습니다.',
            'Weak subgroup 38개 중 탐지가 4개에서 0개로 줄어 전체 AP 상승이 약한 subgroup 개선을 뜻하지 않습니다.',
            '예측 archive는 보존되었지만 원 predict CLI는 archive 작성 후 exit 1이었습니다. 별도 reporting metadata 수정은 검증됐으며 전체 모델 CLI 재실행을 뜻하지 않습니다.',
            '한 synthetic CONF와 고정 CAL 임계값 결과이며 실제 METRO 정상성, 일반화, 생산 FPR 보장이 아닙니다.',
        ],
        'review_source_sha256': actual['review'], 'metrics': metrics,
        'evaluation_scope': 'one_synthetic_CONF_two_feature_bundles_weak_subgroup_regression',
        'source_refs': source_refs, 'not_production': True,
    }
