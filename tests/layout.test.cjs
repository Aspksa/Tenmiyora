const assert = require('node:assert/strict');
const test = require('node:test');
const {position, normalized} = require('../web/layout.js');
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
