import test from 'node:test';
import assert from 'node:assert/strict';
import { analysisBrief } from '../src/analysisBrief.ts';

const context = { item: 'QUEUE', step: 'S1', equipment: 'E1' };
const report = {
  trend: [{ unit: 'hours', onset_summary: { timestamp: '2026-03-28T05:05:00Z',
    before: { mean: 1.498492 }, after: { mean: 1.519894 }, delta: { value: 0.021402 } } }],
  historical_cases: [{ item: 'QUEUE', step: 'S1', equipment: 'E1', incident_number: 'PAST-1',
    date: '2025-12-10', cd: { unit: 'nm', measurements: [{ site: 'center', value: 48.6 }] },
    historical_eds: { yieldPct: 91.2, bin3Pct: 5.4 } }],
  inspection_plan: [{ kind: 'check', target: 'E1 PM', basis: 'saved observation', comparison: 'Compare logs' }],
};
test('saved observations expose actual values, case identity and checks without a model call', () => {
  const brief = analysisBrief(report, context);
  assert.match(brief.observations[0], /1.4985 → 1.5199 h/);
  assert.match(brief.observations[0], /\+0.0214 h/);
  assert.equal(brief.comparisons[0].id, 'PAST-1');
  assert.match(brief.comparisons[0].text, /91.2%/);
  assert.match(brief.comparisons[0].text, /확정된 것은 아닙니다/);
  assert.equal(brief.checks[0].comparison, 'Compare logs');
});
test('another Item or Step is never displayed as a matching case', () => {
  assert.equal(analysisBrief(report, { ...context, item: 'TEMP' }).comparisons.length, 0);
  assert.equal(analysisBrief(report, { ...context, step: 'OTHER' }).comparisons.length, 0);
});
test('missing values are not converted into zero or invented risk', () => {
  const empty = analysisBrief({ trend: [], historical_cases: [], inspection_plan: [] }, context);
  assert.deepEqual(empty, { observations: [], comparisons: [], checks: [], eds: [] });
  assert.equal(analysisBrief({ ...report, trend: [{ unit: 'h', onset_summary: {
    before: { mean: null }, after: { mean: 1 }, delta: null } }] }, context).observations.length, 0);
});

test('shorthand model plan fields are presented as explicit unexecuted checks', () => {
  const result = analysisBrief({ ...report, inspection_plan: [
    { kind: 'check', target: 'S1', basis: 'equipment_events', comparison: 'event_time' },
    { kind: 'eds_followup', target: 'LOT', basis: 'pending', comparison: 'yield' },
  ] }, context);
  assert.match(result.checks[0].comparison, /E1.*PM\/DOWN/);
  assert.match(result.eds[0].comparison, /판정은 대기/);
});
