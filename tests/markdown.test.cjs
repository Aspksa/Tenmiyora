const assert = require('node:assert/strict');
const test = require('node:test');
const {parse} = require('../web/markdown.js');
test('headings, lists and fenced code become blocks', () => {
  const tree = parse('## План\n\n- один\n- **два**\n\n1. раз\n2. два\n\n```js\nconst a = 1;\n```');
  assert.deepEqual(tree.map((block) => block.t), ['heading', 'ul', 'ol', 'codeblock']);
  assert.equal(tree[1].items.length, 2);
  assert.equal(tree[1].items[1][0].t, 'strong');
  assert.equal(tree[3].lang, 'js');
  assert.equal(tree[3].v, 'const a = 1;');
});
test('tables are recognised', () => {
  const [table] = parse('| а | б |\n|---|---|\n| 1 | 2 |');
  assert.equal(table.t, 'table');
  assert.equal(table.head.length, 2);
  assert.equal(table.rows[0].length, 2);
});
test('only http links are kept and html stays text', () => {
  const [p] = parse('[x](javascript:alert(1)) <b>y</b> [ok](https://a.example/b)');
  assert.deepEqual(p.c.filter((node) => node.t === 'link').map((node) => node.href), ['https://a.example/b']);
  assert.ok(p.c.every((node) => node.t !== 'text' || !node.v.includes('<script')));
});
test('unclosed fence does not hang', () => {
  assert.equal(parse('```\nкод без конца')[0].t, 'codeblock');
});
