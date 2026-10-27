const assert = require('node:assert/strict');
const test = require('node:test');
const {parse} = require('../web/markdown.js');
test('headings, lists and fenced code become blocks', () => {
  const tree = parse('## План\n\n- один\n- **два**\n\n1. раз\n2. два\n\n```js\nconst a = 1;\n```');
  assert.deepEqual(tree.map((block) => block.t), ['heading', 'ul', 'ol', 'codeblock']);
  assert.equal(tree[1].items.length, 2);
  assert.equal(tree[1].items[1].c[0].t, 'strong');
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
test('literal hashes stay in headings, list numbers and escaped pipes are kept', () => {
  assert.equal(parse('## Using C# and F#')[0].c[0].v, 'Using C# and F#');
  assert.equal(parse('## Title ##')[0].c[0].v, 'Title');
  assert.equal(parse('4. четыре\n5. пять')[0].start, 4);
  const [table] = parse('| Expression | Result |\n|---|---|\n| a \\| b | 3 |');
  assert.equal(table.rows[0].length, 2);
  assert.equal(table.rows[0][0][0].v, 'a | b');
});
test('unmatched delimiters parse in near-linear time', () => {
  const started = Date.now();
  for (const text of ['['.repeat(40000), '*'.repeat(40000), '`'.repeat(40000), '[a'.repeat(20000), '**a'.repeat(13000)]) parse(text);
  assert.ok(Date.now() - started < 1500);
});
test('links keep balanced parentheses and lists keep fenced code', () => {
  const [p] = parse('[Rust](https://en.wikipedia.org/wiki/Rust_(programming_language)) тут');
  assert.equal(p.c[0].href, 'https://en.wikipedia.org/wiki/Rust_(programming_language)');
  const tree = parse('1. Запустите:\n   ```python\n   if True:\n       print("ok")\n   ```\n2. Готово');
  assert.deepEqual(tree.map((block) => block.t), ['ol']);
  assert.equal(tree[0].items.length, 2);
  assert.equal(tree[0].items[0].children[0].t, 'codeblock');
  assert.equal(tree[0].items[0].children[0].v, 'if True:\n    print("ok")');
});
test('nested lists, long quote runs and blank lines inside list code', () => {
  const [list] = parse('1. Prepare\n   1. Install\n   2. Configure\n2. Deploy');
  assert.equal(list.items.length, 2);
  assert.equal(list.items[0].children[0].t, 'ol');
  assert.equal(list.items[0].children[0].items.length, 2);
  assert.doesNotThrow(() => parse('>'.repeat(20000) + ' text'));
  assert.doesNotThrow(() => parse('- a\n'.repeat(3) + ' '.repeat(2) + '- b'));
  const tree = parse('- шаг\n  ```\n  a\n\n  b\n  ```\n- дальше');
  assert.deepEqual(tree.map((block) => block.t), ['ul']);
  assert.equal(tree[0].items.length, 2);
  assert.equal(tree[0].items[0].children[0].v, 'a\n\nb');
});
