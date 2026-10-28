const assert = require('node:assert/strict');
const test = require('node:test');
const {position, normalized, crowded} = require('../web/layout.js');
test('restored windows stay inside small and large viewports', () => {
  for (const [vw, vh] of [[1366, 768], [390, 844], [320, 480]]) {
    const w = Math.min(430, vw - 16), h = Math.min(575, vh - 16);
    const point = position({x: 1, y: 1}, w, h, vw, vh, {x: 900, y: 900});
    assert.ok(point.x >= 8 && point.y >= 8);
    assert.ok(point.x + w <= vw - 8);
    assert.ok(point.y + h <= vh - 8);
  }
});
test('moving a window preserves its relative placement across viewport sizes', () => {
  const stored = normalized(400, 160, 430, 575, 1366, 900);
  const restored = position(stored, 430, 575, 1366, 900, {x: 0, y: 0});
  assert.equal(restored.x, 400);
  assert.equal(restored.y, 160);
  const narrow = position(stored, 374, 575, 390, 844, {x: 0, y: 0});
  assert.equal(narrow.x, 8);
  assert.ok(narrow.y >= 8 && narrow.y + 575 <= 836);
});
test('crowded map labels give way to the more important one', () => {
  const big = {rank: 0, x1: 0, x2: 100, y1: 0, y2: 12};
  const overlap = {rank: 5, x1: 90, x2: 160, y1: 4, y2: 16};
  const clear = {rank: 7, x1: 200, x2: 260, y1: 0, y2: 12};
  const hidden = crowded([overlap, big, clear]);
  assert.deepEqual([...hidden], [0]);
});
test('equally ranked labels keep the first and only touching ones are hidden', () => {
  const a = {rank: 1, x1: 0, x2: 50, y1: 0, y2: 10};
  const b = {rank: 1, x1: 49, x2: 90, y1: 0, y2: 10};
  const far = {rank: 1, x1: 60, x2: 90, y1: 40, y2: 50};
  const hidden = crowded([a, b, far]);
  assert.equal(hidden.has(0), false);
  assert.equal(hidden.has(1), true);
  assert.equal(hidden.has(2), false);
});
