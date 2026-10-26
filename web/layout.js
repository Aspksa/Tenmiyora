(function (root) {
  'use strict';
  const clamp = (value, min, max) => Math.min(max, Math.max(min, value));
  function bounds(width, height, viewportWidth, viewportHeight) {
    return {x: Math.max(0, viewportWidth - width - 8), y: Math.max(0, viewportHeight - height - 8)};
  }
  function position(saved, width, height, viewportWidth, viewportHeight, fallback) {
    const max = bounds(width, height, viewportWidth, viewportHeight);
    const x = saved ? clamp(saved.x, 0, 1) * max.x : fallback.x;
    const y = saved ? clamp(saved.y, 0, 1) * max.y : fallback.y;
    return {x: clamp(x, 8, Math.max(8, max.x)), y: clamp(y, 8, Math.max(8, max.y))};
  }
  function normalized(x, y, width, height, viewportWidth, viewportHeight) {
    const max = bounds(width, height, viewportWidth, viewportHeight);
    return {x: max.x ? clamp(x / max.x, 0, 1) : 0, y: max.y ? clamp(y / max.y, 0, 1) : 0};
  }
  const api = {clamp, bounds, position, normalized};
  root.TenmiyoraLayout = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window === 'undefined' ? globalThis : window);
