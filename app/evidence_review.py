"""Metadata correspondence and source lineage; not a semantic truth evaluator."""
from datetime import date, datetime, time, timedelta, timezone as datetime_timezone
import json
from zoneinfo import ZoneInfo

from incident_tools import ToolError
from mes_reference_contract import _parse_datetime as _parse_mes_datetime


def _after_cutoff(value, as_of, timezone):
    if value is None:
        return None
    try:
        if len(value) == 10:
            return date.fromisoformat(value) > date.fromisoformat(as_of)
        observed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if observed.tzinfo is None:
            # Legacy local timestamps use the configured business timezone.
            observed = observed.replace(tzinfo=ZoneInfo(timezone))
        cutoff = datetime.combine(date.fromisoformat(as_of) + timedelta(days=1), time.min, ZoneInfo(timezone))
        return observed >= cutoff
    except (AttributeError, TypeError, ValueError):
        return None


def _utc_instant(value):
    return value.astimezone(datetime_timezone.utc)


def validate_snapshot_scope(result, incident_ids, as_of, timezone):
    scope = result.get('scope')
    if scope is None:
        if result.get('sections', {}).get('maps', {}).get('assets'):
            raise ToolError('ENGINEERING_EVIDENCE_SCOPE_MISMATCH')
        return
    if not isinstance(scope, dict) or set(scope.get('incident_ids', [])) != set(incident_ids):
        raise ToolError('ENGINEERING_EVIDENCE_SCOPE_MISMATCH')
    if scope.get('as_of') is not None and scope['as_of'] != as_of:
        raise ToolError('ENGINEERING_EVIDENCE_CUTOFF_MISMATCH')
    pairs = {(row['lot_id'], row['wafer_id']) for row in scope.get('wafers', [])}
    for asset in result.get('sections', {}).get('maps', {}).get('assets', []):
        if (asset.get('lot_id'), asset.get('wafer_id')) not in pairs:
            raise ToolError('MAP_EVIDENCE_WAFER_MISMATCH')
        if scope.get('step') and asset.get('step') != scope['step']:
            raise ToolError('MAP_EVIDENCE_STEP_MISMATCH')
        if _after_cutoff(asset.get('timestamp'), as_of, timezone):
            raise ToolError('MAP_EVIDENCE_AFTER_CUTOFF')


def review_evidence(evidence, as_of, timezone):
    records, issues, images, maps = [], [], [], []

    def add(entry, kind, identity, group, row, observed_at, historical=False):
        if identity is None:
            group = f"unknown:{entry['id']}:{len(records)}"
        record = {'evidence_id': entry['id'], 'record_id': identity, 'kind': kind,
                  'source_group': group, 'observed_at': observed_at,
                  'available_at': row.get('available_at'), 'historical': historical,
                  'subject': {key: row.get(key) for key in ('incident_id', 'lot_id', 'wafer_id', 'chip_id', 'step', 'item', 'equipment', 'stage', 'unit')},
                  'coordinate_system': row.get('coordinate_system'), 'site': row.get('site')}
        for key in ('observed_at', 'available_at'):
            value = record[key]
            after_cutoff = _after_cutoff(value, as_of, timezone)
            if value is not None and after_cutoff is None:
                issues.append({'type': 'invalid_timestamp', 'evidence_id': entry['id'],
                               'record_id': identity, 'field': key})
                if key == 'available_at':
                    record['availability'] = 'invalid'
            elif after_cutoff:
                issues.append({'type': 'after_cutoff', 'evidence_id': entry['id'], 'record_id': identity, 'field': key})
        if record['available_at'] is None:
            record['availability'] = 'unknown'
        records.append(record)
        return record

    for entry in evidence:
        result = entry.get('result')
        if not isinstance(result, dict):
            continue
        source = entry['source']
        if source == 'search_meeting_minutes':
            for row in result.get('items', []):
                group = 'meeting:' + str(row.get('meeting_id')) + ':' + str(row.get('version'))
                if row.get('meeting_id') is None or row.get('version') is None:
                    group = 'unknown:' + entry['id'] + ':' + str(row.get('chunk_id'))
                add(entry, 'meeting', row.get('chunk_id'), group, row, row.get('meeting_date'), True)
        elif source == 'get_platform_evidence':
            for kind, section in result.get('sections', {}).items():
                for row in section.get('rows', []):
                    identity = row.get('record_id')
                    record = add(entry, kind, identity, 'platform:' + kind + ':' + str(identity),
                                 row, row.get('timestamp', row.get('occurred_at')))
                    if kind == 'sem':
                        images.append(record)
        elif source == 'search_platform_history':
            for row in result.get('items', []):
                identity = row.get('incident_id')
                add(entry, 'historical_incident', identity, 'incident:' + str(identity), row,
                    row.get('occurred_at'), True)
        elif source in ('search_engineer_notes', 'search_internal_documents'):
            expected_kind = 'engineer_notes' if source == 'search_engineer_notes' else 'internal_documents'
            if result.get('source_kind') != expected_kind or result.get('status') not in ('OK', 'NO_MATCH'):
                raise ValueError('document evidence response does not match its validated source contract')
            if 'items' not in result:
                raise ValueError('validated document response is missing items')
            items = result['items']
            if not isinstance(items, list):
                raise TypeError('validated document items must be a list')
            if (result['status'] == 'OK') != bool(items):
                raise ValueError('validated document response status and items do not agree')
            metadata_keys = ('source_reported_truncated', 'source_reported_candidate_count',
                             'retrieval_completeness', 'candidate_count_basis')
            present = [key in result for key in metadata_keys]
            if any(present) and not all(present):
                raise ValueError('document retrieval metadata is incomplete')
            if all(present):
                truncated = result['source_reported_truncated']
                candidate_count = result['source_reported_candidate_count']
                completeness = result['retrieval_completeness']
                basis = result['candidate_count_basis']
                if truncated is not None and type(truncated) is not bool:
                    raise ValueError('document source-reported truncated flag is malformed')
                if (candidate_count is not None and
                        (isinstance(candidate_count, bool) or not isinstance(candidate_count, int)
                         or candidate_count < 0)):
                    raise ValueError('document source-reported candidate count is malformed')
                expected_completeness = (
                    'source_reported_truncated' if truncated is True
                    else 'source_reported_not_truncated' if truncated is False else 'unknown')
                if completeness != expected_completeness or basis != 'source_reported_unverified':
                    raise ValueError('document retrieval metadata is inconsistent')
            else:
                truncated, candidate_count = None, None
                completeness, basis = 'unknown', 'source_reported_unverified'
            entry.setdefault('review_metadata', {})['document_retrieval'] = {
                'source_reported_truncated': truncated,
                'source_reported_candidate_count': candidate_count,
                'retrieval_completeness': completeness,
                'candidate_count_basis': basis,
            }
            for item in items:
                if not isinstance(item, dict):
                    raise TypeError('validated document item must be a dict')
                required_strings = ('document_id', 'chunk_id', 'version', 'source_ref', 'locator', 'relation',
                                    'applicability_status')
                if any(not isinstance(item.get(key), str) or not item[key].strip()
                       for key in required_strings):
                    raise ValueError('validated document item metadata is malformed')
                if item['applicability_status'] != 'unverified':
                    raise ValueError('validated document applicability status is malformed')
                if item['relation'] not in ('direct', 'historical_candidate'):
                    raise ValueError('validated document item relation is malformed')
                for key in ('available_at', 'observed_at'):
                    value = item.get(key)
                    if value is not None:
                        if not isinstance(value, str):
                            raise TypeError(f'validated document {key} must be a string')
                        try:
                            parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
                        except ValueError as exc:
                            raise ValueError(f'validated document {key} is malformed') from exc
                        if parsed.tzinfo is None or parsed.utcoffset() is None:
                            raise ValueError(f'validated document {key} must include a timezone')
                relation = item['relation']
                source_ref = item['source_ref']
                group = 'hybrid_document:' + json.dumps(
                    [source, item['document_id'], item['version'], source_ref],
                    ensure_ascii=True, separators=(',', ':'))
                record = add(entry, source, item['chunk_id'], group, item,
                             item.get('observed_at'), relation == 'historical_candidate')
                for key in ('document_id', 'chunk_id', 'version', 'source_ref', 'locator', 'relation',
                            'incident_ids', 'status', 'effective_from', 'effective_to', 'applicability',
                            'applicability_status'):
                    record[key] = item.get(key)
                record['source_id'] = source
                if relation == 'historical_candidate':
                    record['current_incident_applicability'] = 'unverified'
        elif source == 'search_mes_reference':
            status = result.get('status')
            items = result.get('items')
            if (status not in ('OK', 'NO_MATCH') or result.get('as_of') != as_of
                    or not isinstance(items, list)):
                raise ValueError('MES reference response is malformed')
            if (status == 'OK') != bool(items):
                raise ValueError('MES reference response status and items do not agree')
            truncated = result.get('truncated')
            candidate_count = result.get('candidate_count')
            if type(truncated) is not bool:
                raise ValueError('MES reference truncated flag is malformed')
            if (isinstance(candidate_count, bool) or not isinstance(candidate_count, int)
                    or candidate_count < len(items) or (candidate_count > len(items)) != truncated
                    or ((status == 'NO_MATCH') != (candidate_count == 0))):
                raise ValueError('MES reference candidate_count does not match truncation state')
            response_incidents = result.get('incident_ids')
            if (not isinstance(response_incidents, list)
                    or any(not isinstance(value, str) or not value.strip() for value in response_incidents)):
                raise ValueError('MES reference response incident_ids are malformed')
            if len(set(response_incidents)) != len(response_incidents):
                raise ValueError('MES reference response incident_ids contain duplicates')
            entry.setdefault('review_metadata', {})['mes_reference'] = {
                'truncated': truncated, 'candidate_count': candidate_count}
            for item in items:
                if not isinstance(item, dict):
                    raise TypeError('MES reference item must be a dict')
                required_strings = ('kind', 'record_id', 'version', 'source_ref', 'time_status',
                                    'applicability', 'scope_relation')
                if any(not isinstance(item.get(key), str) or not item[key].strip()
                       for key in required_strings):
                    raise ValueError('MES reference item metadata is malformed')
                if item['time_status'] not in ('active', 'future', 'expired', 'unknown'):
                    raise ValueError('MES reference time_status is malformed')
                if item['applicability'] not in ('confirmed', 'candidate', 'unknown'):
                    raise ValueError('MES reference applicability is malformed')
                if item['scope_relation'] not in ('current_scope', 'catalog_candidate'):
                    raise ValueError('MES reference scope_relation is malformed')
                item_incidents = item.get('incident_ids')
                if (not isinstance(item_incidents, list)
                        or any(not isinstance(value, str) or not value.strip() for value in item_incidents)):
                    raise ValueError('MES reference item incident_ids are malformed')
                if (len(set(item_incidents)) != len(item_incidents)
                        or not set(item_incidents).issubset(response_incidents)
                        or (item['scope_relation'] == 'current_scope' and not item_incidents)
                        or (item['scope_relation'] == 'catalog_candidate' and item_incidents)):
                    raise ValueError('MES reference item incident_ids do not match its scope relation')
                if 'available_at' not in item or item['available_at'] is None:
                    raise ValueError('MES reference available_at is required')
                available_at = item['available_at']
                if not isinstance(available_at, str):
                    raise TypeError('MES reference available_at must be a string')
                try:
                    parsed_available_at = _parse_mes_datetime(
                        available_at, 'available_at', ZoneInfo(timezone), required=True)
                except ValueError as exc:
                    raise ValueError('MES reference available_at is malformed or must include a timezone') from exc
                cutoff = datetime.combine(date.fromisoformat(as_of) + timedelta(days=1),
                                          time.min, ZoneInfo(timezone))
                if _utc_instant(parsed_available_at) >= _utc_instant(cutoff):
                    raise ValueError('MES_REFERENCE_AFTER_CUTOFF')
                effective = {}
                for key in ('effective_from', 'effective_to'):
                    value = item.get(key)
                    try:
                        effective[key] = _parse_mes_datetime(
                            value, key, ZoneInfo(timezone))
                    except ValueError as exc:
                        raise ValueError(f'MES reference {key} is malformed or must include a timezone') from exc
                start, end = effective['effective_from'], effective['effective_to']
                if (start is not None and end is not None
                        and _utc_instant(start) >= _utc_instant(end)):
                    raise ValueError('MES reference effective interval is malformed')
                cutoff_instant = _utc_instant(cutoff)
                if start is None and end is None:
                    expected_time_status = 'unknown'
                elif start is not None and _utc_instant(start) >= cutoff_instant:
                    expected_time_status = 'future'
                elif end is not None and _utc_instant(end) < cutoff_instant:
                    expected_time_status = 'expired'
                elif ((start is None or _utc_instant(start) < cutoff_instant)
                      and (end is None or _utc_instant(end) >= cutoff_instant)):
                    expected_time_status = 'active'
                else:
                    expected_time_status = 'unknown'
                if item['time_status'] != expected_time_status:
                    raise ValueError('MES reference time_status does not match effective interval')
                group = 'mes_reference:' + json.dumps(
                    [item['kind'], item['record_id'], item['version'], item['source_ref']],
                    ensure_ascii=True, separators=(',', ':'))
                record = add(entry, 'mes_reference', item['record_id'], group, item, None)
                for key in ('kind', 'record_id', 'version', 'source_ref', 'available_at',
                            'effective_from', 'effective_to', 'time_status', 'applicability',
                            'scope_relation', 'incident_ids'):
                    record[key] = item.get(key)
                record['source_id'] = source
                record['time_status_note'] = 'time_validity_only_not_applicability'
                record['current_incident_applicability'] = 'unverified'
        elif source == 'get_engineering_snapshot':
            sections = result.get('sections', {})
            for row in sections.get('inform', {}).get('rows', []):
                add(entry, 'inform', row.get('id'), 'inform:' + str(row.get('id')) + ':' + str(row.get('version')),
                    row, row.get('date'), True)
            for row in sections.get('maps', {}).get('assets', []):
                group = 'map:' + str(row.get('sha256') or row.get('id'))
                maps.append(add(entry, 'map', row.get('id'), group, row, row.get('timestamp')))
            for kind, section, key in (('fab', 'production', 'fab'), ('change', 'changes', None)):
                container = sections.get(section, {})
                rows = container.get(key, {}).get('rows', []) if key else container.get('rows', [])
                for row in rows:
                    subject = {**row, 'lot_id': row.get('lotId'), 'wafer_id': row.get('waferId')}
                    identity = row.get('id') or f"{row.get('lotId')}:{row.get('waferId')}:{row.get('timestamp')}"
                    add(entry, kind, identity, kind + ':' + str(identity), subject, row.get('timestamp'))
            for kind, key in (('equipment_state', 'equipmentStates'), ('downtime', 'downtime')):
                for row in sections.get('production', {}).get(key, {}).get('rows', []):
                    identity = row.get('id') or f"{row.get('equipment')}:{row.get('start')}:{row.get('state', row.get('code'))}"
                    add(entry, kind, identity, kind + ':' + str(identity), row, row.get('start'))
            enterprise = sections.get('enterprise', {})
            systems = enterprise.get('systems', []) if isinstance(enterprise, dict) else []
            if isinstance(systems, list):
                for system in systems:
                    if not isinstance(system, dict):
                        continue
                    source_id = system.get('id')
                    rows = system.get('rows', [])
                    if not isinstance(rows, list):
                        continue
                    for row in rows:
                        if not isinstance(row, dict):
                            continue
                        identity = row.get('record_id')
                        group = 'enterprise:' + str(source_id) + ':' + str(identity)
                        record = add(entry, 'enterprise_system', identity, group, row,
                                     row.get('occurred_at'))
                        record['source_id'] = source_id
                        record['occurred_at'] = row.get('occurred_at')
        elif source in ('list_comparison_assets', 'compare_sem_images', 'compare_overlay_maps'):
            rows = (result.get('assets', []) if source == 'list_comparison_assets'
                    else result.get('provenance', {}).get('validated_asset_metadata', []))
            for row in rows:
                images.append(add(entry, row.get('modality', 'image'), row.get('asset_id'),
                    'image:' + str(row.get('modality', 'image')) + ':' + str(row.get('asset_id')) + ':' + str(row.get('revision')), row, row.get('acquired_at')))
            if source.startswith('compare_') and not result.get('alignment_verified', False):
                issues.append({'type': 'physical_alignment_unverified', 'evidence_id': entry['id']})

    groups = {}
    for record in records:
        groups.setdefault(record['source_group'], set()).add(record['evidence_id'])
    duplicate_records = len(records) - len({(record['source_group'], record['record_id']) for record in records})
    correspondence, seen = [], set()
    for image in images:
        for metrology in maps:
            pair = (image['source_group'], metrology['source_group'])
            if pair in seen:
                continue
            a, b = image['subject'], metrology['subject']
            if not a['lot_id'] or not a['wafer_id'] or (a['lot_id'], a['wafer_id']) != (b['lot_id'], b['wafer_id']):
                continue
            seen.add(pair)
            missing = [key for key in ('step', 'item') if a[key] is None or b[key] is None]
            conflicts = [key for key in ('step', 'item') if a[key] is not None and b[key] is not None and a[key] != b[key]]
            if image['coordinate_system'] is None or metrology['coordinate_system'] is None:
                missing.append('coordinate_system')
            elif image['coordinate_system'] != metrology['coordinate_system']:
                conflicts.append('coordinate_system')
            if image['site'] is None or metrology['site'] is None:
                missing.append('site')
            elif image['site'] != metrology['site']:
                conflicts.append('site')
            correspondence.append({'image_id': image['record_id'], 'map_id': metrology['record_id'],
                'evidence_ids': sorted({image['evidence_id'], metrology['evidence_id']}),
                'status': 'conflict' if conflicts else 'unverified', 'conflicts': conflicts, 'missing': missing,
                'same_wafer': True, 'physical_alignment_verified': False,
                'time_relation': 'same_timestamp' if image['observed_at'] and image['observed_at'] == metrology['observed_at'] else 'not_same_timestamp'})
    return {'records': records, 'source_groups': [{'id': key, 'evidence_ids': sorted(values)} for key, values in groups.items()],
            'duplicate_records': duplicate_records, 'correspondence': correspondence, 'issues': issues,
            'limitations': ['METADATA_CHECKS_NOT_SEMANTIC_VERIFICATION', 'SOURCE_GROUPS_NOT_PROOF_OF_INDEPENDENCE',
                            'AVAILABILITY_TIME_UNKNOWN_WHEN_NOT_RECORDED'] +
                           (['HISTORICAL_CANDIDATE_APPLICABILITY_UNVERIFIED']
                            if any(record.get('relation') == 'historical_candidate' for record in records) else []) +
                           (['MES_TIME_STATUS_IS_NOT_APPLICABILITY', 'MES_SCOPE_RELATION_NOT_AUTHENTICATED']
                            if any(record.get('source_id') == 'search_mes_reference' for record in records) else []) +
                           (['MES_REFERENCE_RESULTS_TRUNCATED']
                            if any(entry.get('review_metadata', {}).get('mes_reference', {}).get('truncated')
                                   for entry in evidence if entry.get('source') == 'search_mes_reference') else []) +
                           (['DOCUMENT_RESULTS_SOURCE_REPORTED_TRUNCATED']
                            if any(entry.get('review_metadata', {}).get('document_retrieval', {}).get(
                                'source_reported_truncated') is True for entry in evidence
                                if entry.get('source') in ('search_engineer_notes', 'search_internal_documents')) else []) +
                           (['DOCUMENT_RETRIEVAL_COMPLETENESS_UNKNOWN']
                            if any(entry.get('review_metadata', {}).get('document_retrieval', {}).get(
                                'source_reported_truncated') is None for entry in evidence
                                if entry.get('source') in ('search_engineer_notes', 'search_internal_documents')) else [])}


def no_match_response(entry):
    result = entry['result']
    text = '사고 DB 조회는 성공했으며, 현재 검색 조건에 맞는 사고는 0건입니다.'
    return {'status': 'answered', 'answer': text,
            'claims': [{'claim_id': 'no-match-1', 'text': text, 'evidence_ids': [entry['id']]}],
            'limitations': ['현재 조건의 조회 결과이며 다른 조건의 사고나 관련 문서가 없다는 뜻은 아닙니다.'],
            'lookup_conditions': entry.get('arguments', {}), 'lookup_status': result['status']}
