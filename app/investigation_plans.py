"""Build scope-grounded investigation candidates from frozen Skill recipes."""
import json
from pathlib import Path


def build_investigations(settings, evidence):
    results = [entry for entry in evidence if entry.get('source') == 'get_platform_evidence']
    if not results:
        return []
    paths = settings.data['paths']
    registry = json.loads(Path(paths['registry_file']).read_text(encoding='utf-8'))
    files = [Path(paths['skills_root']) / folder / 'references/investigation-recipes.json'
             for folder in registry['topics']['platform']]
    files = [path for path in files if path.is_file()]
    if len(files) != 1:
        raise ValueError('INVESTIGATION_RECIPE_REFERENCE_REQUIRED')
    recipes = json.loads(files[0].read_text(encoding='utf-8'))['recipes']
    selected = {}
    for entry in results:
        result = entry['result']
        summaries = result.get('summaries', {})
        tabular = result.get('tabular_analysis', {})
        out_of_spec = result.get('cross_modal_alignment', {}).get('chip_counts', {}).get('legacy_measure_out_of_spec')
        cases = result.get('map_analysis', {}).get('cases', [])
        grains = [case.get('analysis', {}).get('grains', {}) for case in cases if case.get('status') == 'OK']
        repeat = any(grain.get('cross_chip_repeated_motif', {}).get('status') == 'candidate_repeated_motif' for grain in grains)
        local = any(grain.get('wafer_local_anomaly', {}).get('candidate_region_count', 0) > 0 for grain in grains)
        triggers = {
            'tabular_combination': tabular.get('status') == 'OK' and tabular.get('flagged_chip_count', 0) > 0 and out_of_spec == 0,
            'chip_repetition': repeat,
            'wafer_local': local,
            'bit_without_oos': any(row.get('chips', 0) > 0 for row in summaries.get('failbit', [])) and out_of_spec == 0,
            'trend_shift': any(row.get('modality') == 'trend' and row.get('status') == 'OK' and row.get('label') != 'normal'
                               for row in result.get('model_observations', [])),
            'mes_hold': any(row.get('status') == 'HOLD' and row.get('events', 0) > 0 for row in summaries.get('mes', [])),
            'inform_hypothesis': result.get('sections', {}).get('inform', {}).get('count', 0) > 0,
        }
        for recipe in recipes:
            if triggers.get(recipe['trigger']):
                item = selected.setdefault(recipe['id'], {**recipe, 'evidence_ids': [],
                    'provenance': 'offline_skill_recipe_selected_by_observed_conditions'})
                if entry['id'] not in item['evidence_ids']:
                    item['evidence_ids'].append(entry['id'])
    return list(selected.values())


def render_investigations(candidates, ranked_ids):
    by_id = {item['id']: item for item in candidates}
    if (not isinstance(ranked_ids, list) or any(not isinstance(item, str) for item in ranked_ids)
            or len(set(ranked_ids)) != len(ranked_ids) or set(ranked_ids) != set(by_id)):
        raise ValueError('INVESTIGATION_COVERAGE_REQUIRED')
    rows = []
    for identifier in ranked_ids:
        item = by_id[identifier]
        refs = ' '.join('[' + ref + ']' for ref in item['evidence_ids'])
        rows.append('검토 가설: ' + item['hypothesis'] + '\n반대 근거·제한: ' + item['counterevidence']
                    + '\n다음 점검: ' + item['next_check'] + ' ' + refs)
    return '\n\n'.join(rows)
