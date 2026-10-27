(function (root) {
  'use strict';
  const INLINE = /`([^`\n]{1,300})`|\*\*([^*\n]{1,300}?)\*\*|__([^_\n]{1,300}?)__|\*([^*\s][^*\n]{0,299}?)\*|\[([^\]\n]{1,300})\]\((https?:\/\/(?:[^\s()]|\([^\s()]{0,200}\)){1,500})\)/g;
  function inline(text) {
    const out = [], pattern = new RegExp(INLINE.source, 'g'); let last = 0, match;
    while ((match = pattern.exec(text))) {
      if (match.index > last) out.push({t: 'text', v: text.slice(last, match.index)});
      if (match[1] !== undefined) out.push({t: 'code', v: match[1]});
      else if (match[2] !== undefined || match[3] !== undefined) out.push({t: 'strong', c: inline(match[2] ?? match[3])});
      else if (match[4] !== undefined) out.push({t: 'em', c: inline(match[4])});
      else out.push({t: 'link', href: match[6], c: inline(match[5])});
      last = pattern.lastIndex;
    }
    if (last < text.length) out.push({t: 'text', v: text.slice(last)});
    return out;
  }
  const splitRow = (line) => {
    const cells = []; let cell = '';
    for (const char of line.trim().replace(/^\|/, '').replace(/(^|[^\\])\|$/, '$1')) {
      if (char === '|' && !cell.endsWith('\\')) { cells.push(cell.trim()); cell = ''; }
      else cell += char;
    }
    cells.push(cell.trim());
    return cells.map((value) => value.replace(/\\\|/g, '|'));
  };
  const isRule = (line) => line.includes('-') && line.trim().replace(/^\|/, '').replace(/\|$/, '').split('|').every((cell) => /^:?-{2,}:?$/.test(cell.trim()));
  const LIST = /^\s*([-*+]|\d{1,3}[.)])\s+(.*)$/;
  const MAX_DEPTH = 6, indentOf = (line) => line.match(/^ */)[0].length;
  function blocks(source, depth = 0) {
    const lines = String(source).replace(/\r\n?/g, '\n').split('\n'), out = [];
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];
      if (!line.trim()) { i++; continue; }
      const fence = line.match(/^(\s*)```\s*([\w+#.-]*)\s*$/);
      if (fence) {
        const code = []; i++;
        while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) code.push(lines[i++].startsWith(fence[1]) ? lines[i - 1].slice(fence[1].length) : lines[i - 1]);
        i++;
        out.push({t: 'codeblock', lang: fence[2], v: code.join('\n')});
        continue;
      }
      const heading = line.match(/^\s{0,3}(#{1,4})\s+(.+?)(?:\s+#+)?\s*$/);
      if (heading) { out.push({t: 'heading', level: heading[1].length, c: inline(heading[2])}); i++; continue; }
      if (/^\s*([-*_])(\s*\1){2,}\s*$/.test(line)) { out.push({t: 'rule'}); i++; continue; }
      if (line.includes('|') && i + 1 < lines.length && isRule(lines[i + 1])) {
        const head = splitRow(line), rows = []; i += 2;
        while (i < lines.length && lines[i].includes('|') && lines[i].trim()) rows.push(splitRow(lines[i++]));
        out.push({t: 'table', head: head.map(inline), rows: rows.map((row) => row.map(inline))});
        continue;
      }
      if (/^\s*>/.test(line)) {
        const quote = [];
        while (i < lines.length && /^\s*>/.test(lines[i])) quote.push(lines[i++].replace(/^\s*>\s?/, ''));
        out.push(depth >= MAX_DEPTH ? {t: 'p', c: inline(quote.join('\n'))} : {t: 'quote', c: blocks(quote.join('\n'), depth + 1)});
        continue;
      }
      const item = line.match(LIST);
      if (item) {
        const ordered = /\d/.test(item[1]), start = ordered ? parseInt(item[1], 10) : 1, base = indentOf(line), items = [];
        while (i < lines.length) {
          const next = lines[i].match(LIST);
          if (!next || indentOf(lines[i]) !== base || /\d/.test(next[1]) !== ordered) break;
          const children = []; i++;
          while (i < lines.length) {
            let j = i;
            while (j < lines.length && !lines[j].trim()) j++;
            if (j >= lines.length || indentOf(lines[j]) <= base) break;
            while (i < j) children.push(lines[i++]);
            children.push(lines[i++]);
          }
          const cut = children.reduce((min, row) => row.trim() ? Math.min(min, indentOf(row)) : min, Infinity);
          const body = children.map((row) => row.slice(Math.min(cut, indentOf(row)))).join('\n');
          items.push({c: inline(next[2]), children: !children.length ? [] : depth >= MAX_DEPTH ? [{t: 'codeblock', lang: '', v: body}] : blocks(body, depth + 1)});
        }
        out.push({t: ordered ? 'ol' : 'ul', start, items});
        continue;
      }
      const paragraph = [];
      while (i < lines.length && lines[i].trim() && !/^\s*```/.test(lines[i]) && !/^\s{0,3}#{1,4}\s/.test(lines[i]) && !LIST.test(lines[i]) && !/^\s*>/.test(lines[i])) paragraph.push(lines[i++]);
      if (!paragraph.length) { paragraph.push(lines[i++]); }
      out.push({t: 'p', c: inline(paragraph.join('\n'))});
    }
    return out;
  }
  const api = {parse: blocks, inline};
  root.TenmiyoraMarkdown = api;
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
})(typeof window === 'undefined' ? globalThis : window);
