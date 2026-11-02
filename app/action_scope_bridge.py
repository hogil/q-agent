"""Synthetic-only input boundary for the scoped action planner.

IncidentTools pages do not carry a shared snapshot identity. This bridge accepts
them only through an injected snapshot lease that guarantees one immutable read
snapshot for its lifetime. It grants no production action authority.
"""
from datetime import datetime, timezone


class ActionScopeBridgeError(ValueError):
    pass


def _fail(code):
    raise ActionScopeBridgeError(code)


def _utc_datetime(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace('Z', '+00:00'))
        except ValueError:
            _fail('INVALID_SNAPSHOT_AS_OF')
    if (not isinstance(value, datetime) or value.tzinfo is None or
            value.utcoffset() != timezone.utc.utcoffset(value)):
        _fail('INVALID_SNAPSHOT_AS_OF')
    return value.astimezone(timezone.utc)


def _coverage_signature(value):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        return (('invalid',),)
    return tuple(sorted((str(row.get('incident_id')), str(row.get('state')),
                         str(row.get('expected_lots', row.get('expected_wafers'))),
                         str(row.get('returned_total_lots', row.get('returned_total_wafers'))))
                        for row in value))


def _read_all(read_page, *, page_size, selected_ids, expected_scope_id, lease, kind):
    offset, rows, baseline = 0, [], None
    while True:
        page = read_page(page_size=page_size, offset=offset)
        if not isinstance(page, dict):
            _fail(f'{kind}_INVALID_PAGE')
        if page.get('status') != 'OK':
            _fail(f'{kind}_INCOMPLETE')
        if page.get('scope_id') != expected_scope_id:
            _fail(f'{kind}_SCOPE_MISMATCH')
        if (page.get('_snapshot_token') != lease.snapshot_token or
                page.get('_snapshot_revision') != lease.revision or
                page.get('_snapshot_as_of') != lease.as_of):
            _fail(f'{kind}_SNAPSHOT_BINDING_MISMATCH')
        if type(page.get('total_memberships')) is not int or page['total_memberships'] <= 0:
            _fail(f'{kind}_EMPTY_OR_INVALID_SCOPE')
        missing = page.get('lots_without_wafer_rows', [])
        if not isinstance(missing, list) or any(not isinstance(row, dict) for row in missing):
            _fail(f'{kind}_INVALID_PAGE_METADATA')
        signature = (page['scope_id'], page['total_memberships'], page.get('source_completeness'),
                     page.get('mapping_version'), page.get('wafer_scope'),
                     _coverage_signature(page.get('coverage')),
                     _coverage_signature(page.get('lot_coverage')),
                     tuple(sorted((str(row.get('incident_id')), str(row.get('lot_id'))) for row in missing)))
        if baseline is None:
            baseline = signature
        elif signature != baseline:
            _fail(f'{kind}_INCONSISTENT_PAGE_METADATA')
        if offset != page.get('offset', 0):
            _fail(f'{kind}_PAGE_OFFSET_MISMATCH')
        items = page.get('items')
        if not isinstance(items, list) or not items:
            _fail(f'{kind}_MISSING_PAGE')
        rows.extend(items)
        if len(rows) > page['total_memberships']:
            _fail(f'{kind}_PAGE_OVERFLOW')
        next_offset = page.get('next_offset')
        expected_next = offset + len(items)
        if next_offset is None:
            if len(rows) != page['total_memberships']:
                _fail(f'{kind}_PAGE_OMISSION')
            break
        if type(next_offset) is not int or next_offset != expected_next:
            _fail(f'{kind}_PAGE_GAP_OR_OVERLAP')
        offset = next_offset
    if not selected_ids:
        _fail('EMPTY_SELECTED_INCIDENT_SCOPE')
    return rows, baseline


def _require_complete_coverage(metadata, kind, selected_ids):
    if not isinstance(metadata, tuple) or metadata[2] != 'declared_complete':
        _fail(f'{kind}_SOURCE_NOT_DECLARED_COMPLETE')
    coverage_sets = (metadata[5], metadata[6]) if kind == 'WAFER' else (metadata[5],)
    expected_ids = set(map(str, selected_ids))
    for states in coverage_sets:
        if (not states or {row[0] for row in states if len(row) > 1} != expected_ids or
                any(len(row) < 2 or not row[1].endswith('complete_by_declared_source_and_count')
                    for row in states)):
            _fail(f'{kind}_COVERAGE_INCOMPLETE')
    if kind == 'WAFER' and metadata[7]:
        _fail('WAFER_LOT_COVERAGE_HAS_MISSING_WAFERS')


def build_scoped_action_input(incident_tools, actor, scope_id, *, snapshot_lease_provider,
                              page_size=100):
    """Build planner-shaped data under a trusted synthetic snapshot lease.

    ``snapshot_lease_provider(tools, actor, scope_id)`` is an injected context
    manager yielding an adapter with ``atomic_snapshot is True``, nonempty
    ``snapshot_token`` and ``revision``, UTC ``as_of``, two paged list methods,
    and ``validate()``. The adapter contract must pin every read to one immutable
    snapshot and bind that snapshot metadata to each page. The bridge checks the
    binding but cannot independently prove the adapter's implementation or its
    revision-to-database binding. The returned attestation and eligibility apply
    only to the synthetic planner under this trusted-provider assumption.
    Plain IncidentTools has no such lease and is therefore rejected.
    """
    if type(page_size) is not int or page_size < 1:
        _fail('INVALID_PAGE_SIZE')
    selected = incident_tools._scope(actor, scope_id)
    selected_ids = tuple(selected.get('ids', ()))
    if (selected.get('requires_selection') or selected.get('summary_only') or
            not selected_ids or len(set(selected_ids)) != len(selected_ids)):
        _fail('SELECTED_INCIDENT_SCOPE_REQUIRED')

    with snapshot_lease_provider(incident_tools, actor, scope_id) as lease:
        if (getattr(lease, 'atomic_snapshot', None) is not True or not lease.snapshot_token or
                not isinstance(lease.revision, str) or not lease.revision.strip()):
            _fail('TRUSTED_SNAPSHOT_LEASE_REQUIRED')
        if lease.revision == scope_id:
            _fail('SNAPSHOT_REVISION_MUST_NOT_BE_SCOPE_ID')
        as_of = _utc_datetime(lease.as_of)
        lot_rows, lot_meta = _read_all(
            lambda **kw: lease.list_incident_lots(actor, scope_id, **kw),
            page_size=page_size, selected_ids=selected_ids, expected_scope_id=scope_id,
            lease=lease, kind='LOT')
        _require_complete_coverage(lot_meta, 'LOT', selected_ids)
        selected_lots, lot_memberships = set(), set()
        for row in lot_rows:
            if not isinstance(row, dict) or row.get('incident_id') not in selected_ids:
                _fail('LOT_OUTSIDE_SELECTED_INCIDENT_SCOPE')
            lot_id = row.get('lot_id')
            if not isinstance(lot_id, str) or not lot_id:
                _fail('INVALID_LOT_ID')
            membership = (row['incident_id'], lot_id)
            if membership in lot_memberships:
                _fail('DUPLICATE_LOT_MEMBERSHIP')
            lot_memberships.add(membership)
            selected_lots.add((row['incident_id'], lot_id))
        if not selected_lots:
            _fail('EMPTY_SELECTED_LOT_SCOPE')

        wafer_rows, wafer_meta = _read_all(
            lambda **kw: lease.list_incident_wafers(actor, scope_id, **kw),
            page_size=page_size, selected_ids=selected_ids, expected_scope_id=scope_id,
            lease=lease, kind='WAFER')
        _require_complete_coverage(wafer_meta, 'WAFER', selected_ids)
        if wafer_meta[4] != 'incident_affected':
            _fail('WAFER_SCOPE_IS_NOT_INCIDENT_AFFECTED')
        pairs, pairs_seen, seen_memberships = [], set(), set()
        for row in wafer_rows:
            if not isinstance(row, dict) or row.get('incident_id') not in selected_ids:
                _fail('WAFER_OUTSIDE_SELECTED_INCIDENT_SCOPE')
            lot_id, wafer_id = row.get('lot_id'), row.get('wafer_id')
            if (row['incident_id'], lot_id) not in selected_lots:
                _fail('WAFER_LOT_OUTSIDE_INCIDENT_SCOPE')
            if not isinstance(wafer_id, str) or not wafer_id:
                _fail('INVALID_WAFER_ID')
            membership, pair = (row['incident_id'], lot_id, wafer_id), (wafer_id, lot_id)
            if membership in seen_memberships:
                _fail('DUPLICATE_WAFER_LOT_PAIR')
            seen_memberships.add(membership)
            if pair not in pairs_seen:
                pairs_seen.add(pair)
                pairs.append(pair)
        if not pairs:
            _fail('EMPTY_AFFECTED_WAFER_SCOPE')
        if lease.validate() is not True:
            _fail('SNAPSHOT_LEASE_VALIDATION_FAILED')
        return {'scope': tuple(pairs), 'as_of': as_of, 'revision': lease.revision,
                'synthetic_only': True, 'snapshot_provider_attested': True,
                'synthetic_planner_input_eligible': True, 'execution_granted': False}
