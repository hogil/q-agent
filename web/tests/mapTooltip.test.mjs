import assert from 'node:assert/strict';
import test from 'node:test';

import {
  adaptiveMapTooltipPosition,
  escapeMapTooltipText,
} from '../src/mapTooltip.ts';

const size = (contentSize, viewSize) => ({ contentSize, viewSize });

test('keeps a map tooltip offset from a pointer with room on the lower right', () => {
  assert.deepEqual(
    adaptiveMapTooltipPosition(
      [20, 20],
      null,
      null,
      null,
      size([80, 40], [300, 200]),
    ),
    [30, 30],
  );
});

test('moves to the opposite upper-left quadrant near the lower-right edge', () => {
  assert.deepEqual(
    adaptiveMapTooltipPosition(
      [280, 180],
      null,
      null,
      null,
      size([80, 40], [300, 200]),
    ),
    [190, 130],
  );
});

test('keeps the tooltip inside a small mobile viewport', () => {
  const [left, top] = adaptiveMapTooltipPosition(
    [58, 58],
    null,
    null,
    null,
    size([70, 50], [120, 100]),
  );
  assert.ok(left >= 0 && top >= 0);
  assert.ok(left + 70 <= 120);
  assert.ok(top + 50 <= 100);
});

test('keeps a tooltip off the pointer at all four viewport corners', () => {
  for (const point of [
    [15, 15],
    [985, 15],
    [15, 785],
    [985, 785],
  ]) {
    const [x, y] = adaptiveMapTooltipPosition(
      point,
      null,
      null,
      null,
      size([200, 150], [1000, 800]),
    );
    assert.ok(x >= 0 && y >= 0 && x + 200 <= 1000 && y + 150 <= 800);
    assert.ok(
      point[0] < x || point[0] > x + 200 || point[1] < y || point[1] > y + 150,
    );
  }
});

test('renders untrusted map labels as text in the HTML tooltip', () => {
  assert.equal(
    escapeMapTooltipText('<img src=x onerror="alert(1)">\nA&B'),
    '&lt;img src=x onerror=&quot;alert(1)&quot;&gt;\nA&amp;B',
  );
});
