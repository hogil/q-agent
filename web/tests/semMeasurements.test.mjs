import test from 'node:test';
import assert from 'node:assert/strict';
import {
  measurementAveragePx,
  measurementDistancePx,
  semMeasurementPreset,
} from '../src/semMeasurements.ts';

test('recognized synthetic SEM assets expose grounded manual measurement presets', () => {
  const preset = semMeasurementPreset('/assets/synthetic-sem-contact-v2.png');
  assert.equal(preset?.metricLabel, 'Contact 직경');
  assert.equal(preset?.measurements.length, 3);
  assert.ok(preset?.measurements.every((item) => item.start.y === item.end.y));
  assert.equal(semMeasurementPreset('/assets/unknown-sem.png'), null);
});

test('pixel distances and averages stay in image pixels without calibration', () => {
  const measurements = [
    { id: 'm1', start: { x: 0, y: 0 }, end: { x: 0.04, y: 0 } },
    { id: 'm2', start: { x: 0, y: 0 }, end: { x: 0.08, y: 0 } },
  ];
  assert.equal(measurementDistancePx(measurements[0], 1000), 40);
  assert.equal(measurementAveragePx(measurements, 1000), 60);
});

test('all seven pattern families provide independent three-region measurements', () => {
  for (const family of ['thin', 'contact', 'pillars', 'lineends', 'corners', 'slots', 'serpentine']) {
    const path = `/assets/synthetic-sem-${family}-v2.png`;
    const first = semMeasurementPreset(path);
    assert.equal(first.measurements.length, 3, family);
    for (const measurement of first.measurements) {
      assert.ok(measurementDistancePx(measurement) > 0);
      for (const point of [measurement.start, measurement.end]) {
        assert.ok(point.x >= 0 && point.x <= 1 && point.y >= 0 && point.y <= 1);
      }
    }
    first.measurements[0].start.x = -5;
    assert.ok(semMeasurementPreset(path).measurements[0].start.x >= 0);
  }
});

test('ROIs sit on visible edges and Line ends measures tip gaps', () => {
  const thin = semMeasurementPreset('/assets/synthetic-sem-thin-v2.png');
  assert.ok(Math.abs(thin.measurements[0].start.x - 22 / 1254) < 0.0001);
  assert.ok(Math.abs(thin.measurements[0].end.x - 63 / 1254) < 0.0001);
  assert.ok(thin.measurements[1].end.x - thin.measurements[1].start.x < 0.03);

  const lineEnds = semMeasurementPreset('/assets/synthetic-sem-lineends-v2.png');
  assert.equal(lineEnds.metricLabel, 'Tip-to-tip gap');
  assert.ok(lineEnds.measurements[0].start.x > 0.2);
  assert.ok(lineEnds.measurements[0].end.x - lineEnds.measurements[0].start.x < 0.1);
  assert.ok(
    lineEnds.measurements[1].end.x - lineEnds.measurements[1].start.x >
      lineEnds.measurements[0].end.x - lineEnds.measurements[0].start.x,
  );

  const abnormal = semMeasurementPreset('/assets/synthetic-sem-pillars-v2.png');
  const reference = semMeasurementPreset('/assets/synthetic-sem-pillars-reference-v2.png');
  assert.notDeepEqual(abnormal.measurements, reference.measurements);
});

test('native rectangular image dimensions control X and Y distance, not viewport size', () => {
  const m = { id: 'm', start: { x: 0, y: 0 }, end: { x: 0.3, y: 0.4 } };
  assert.equal(measurementDistancePx(m, { width: 1000, height: 2000 }), Math.hypot(300, 800));
  assert.equal(measurementAveragePx([], { width: 512, height: 512 }), null);
  assert.equal(measurementDistancePx({ ...m, end: { x: 0.5, y: 0 } }, 512), 256);
});
