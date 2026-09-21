import assert from 'node:assert/strict';
import test from 'node:test';
import {
  makeInformNotes,
  selectInformNotes,
  formatInformTimestamp,
  documentUrl,
  semRecord,
  filterSemWafers,
  wipLayerBounds,
  wipLayerOption,
} from '../src/investigationData.ts';
import { makeEngineeringData } from '../src/engineeringData.ts';

const workspace = {
  incident: {
    incident_number: 'SYN-2026-01',
    occurred_at: '2026-01-15T12:00:00Z',
  },
  lots: [
    { lot_id: 'L1', product_code: 'P1', status: 'HOLD' },
    { lot_id: 'L2', product_code: 'P2', status: 'RUN' },
  ],
  wafers: [
    { lot_id: 'L2', wafer_id: 'W01' },
    { lot_id: 'L1', wafer_id: 'W01' },
  ],
  meetings: [],
  synthetic: true,
};

test('Inform list is strictly filtered by step and equipment', () => {
  const notes = makeInformNotes(makeEngineeringData(workspace));
  assert.equal(notes.length, 4);
  assert.equal(selectInformNotes(notes, 'SYN-ETCH-10', 'SYN-EQP-01').length, 2);
  assert.deepEqual(
    selectInformNotes(notes, 'SYN-ETCH-10', 'SYN-EQP-01').map((n) => n.title),
    ['설비 점검 후 확인', 'Recipe 변경 검토'],
  );
  assert.ok(
    selectInformNotes(notes, 'SYN-ETCH-10', 'SYN-EQP-02').every(
      (n) => n.equipment === 'SYN-EQP-02' && n.body.includes('합성'),
    ),
  );
  assert.deepEqual(selectInformNotes(notes, 'unknown', ''), []);
  assert.deepEqual(selectInformNotes(notes, 'SYN-ETCH-10', 'unknown'), []);
  assert.deepEqual(selectInformNotes(notes, 'SYN-ETCH-10', ''), []);
  assert.equal(
    formatInformTimestamp('2026-01-15T12:34:56.000Z'),
    '2026-01-15 12:34 UTC',
  );
  assert.equal(
    new URL(
      documentUrl('SYN-2026-01', 'inform', 'note & 1'),
      'http://localhost',
    ).searchParams.get('document'),
    'note & 1',
  );
});

test('SEM fixture lookup uses full Lot/Wafer identity and never borrows a different image', () => {
  assert.equal(semRecord(workspace, 'L1', 'W01').id, 'SYN-SEM-01');
  assert.equal(semRecord(workspace, 'L2', 'W01').id, 'SYN-SEM-02');
  assert.notEqual(
    semRecord(workspace, 'L1', 'W01').src,
    semRecord(workspace, 'L2', 'W01').src,
  );
  assert.equal(semRecord(workspace, 'L1', 'unknown'), null);
  assert.equal(semRecord({ ...workspace, wafers: [] }, 'L1', 'W01'), null);
});

test('SEM search matches Lot and Wafer terms only without changing identities', () => {
  const rows = [
    { lotId: 'LOT-A', waferId: 'W01', equipment: 'EQP-99' },
    { lotId: 'LOT-A', waferId: 'W02', equipment: 'EQP-99' },
    { lotId: 'LOT-B', waferId: 'W01', equipment: 'EQP-88' },
  ];
  assert.deepEqual(filterSemWafers(rows, '  lot-a / w01 '), [rows[0]]);
  assert.deepEqual(filterSemWafers(rows, 'w01'), [rows[0], rows[2]]);
  assert.deepEqual(filterSemWafers(rows, 'lot-a'), rows.slice(0, 2));
  assert.deepEqual(filterSemWafers(rows, 'EQP-99'), []);
  assert.deepEqual(filterSemWafers(rows, 'unknown'), []);
  assert.deepEqual(filterSemWafers(rows, ' / '), rows);
  assert.equal(filterSemWafers(rows, 'lot-b')[0], rows[2]);
  assert.deepEqual(filterSemWafers([], 'W01'), []);
});

test('WIP uses product rows, numeric layer positions and clips route to occupied region', () => {
  const data = makeEngineeringData(workspace);
  const option = wipLayerOption(data.wip);
  assert.deepEqual(option.yAxis.data, ['P1', 'P2']);
  assert.equal(option.xAxis.type, 'value');
  assert.ok(option.xAxis.min > 0 && option.xAxis.max < 40);
  for (const row of data.wip) {
    assert.ok(row.layer >= option.xAxis.min && row.layer <= option.xAxis.max);
    assert.ok(row.layer <= row.endLayer);
  }
  assert.deepEqual(option.series[0].data, [
    [0, 0],
    [40, 0],
  ]);
  assert.equal(option.series.at(-1).type, 'scatter');
  assert.equal(option.series.at(-1).data.length, 2);
  assert.equal(wipLayerBounds([]), null);
  assert.ok(
    wipLayerBounds([data.wip[0]]).max > wipLayerBounds([data.wip[0]]).min,
  );
});
