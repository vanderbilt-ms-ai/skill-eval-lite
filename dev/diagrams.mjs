#!/usr/bin/env node
// Skill Eval Lite's pictures as files: docs/diagrams/*.svg.
//
//   node dev/diagrams.mjs           write docs/diagrams/ (and remove pictures no longer drawn),
//                                   and the README's step lists
//   node dev/diagrams.mjs --check   change nothing; exit 1 if either is out of date
//
// The pictures are drawn by the code in wizard.html's <script id="diagrams">,
// which the wizard runs in the page (so that they follow its light and dark
// themes, and show each student's own folder names). This script runs the
// same code, with placeholder names, and writes each picture as a standalone
// SVG with its own light and dark colors, for the README and for other pages.
// Edit the drawing code in wizard.html, then run this script.
//
// The README's "Getting started, in pictures" holds two lists written from
// the same steps, between <!-- steps:first:begin --> and <!-- steps:first:end -->
// (and steps:group): the wizard, the pictures and the README say the same.
//
// Reads wizard.html and README.md. Writes docs/diagrams/ and those two lists.
// Needs Node.js 18 or later and nothing else. Made for AI 5500 (Vanderbilt, Fall 2026), October 2026.
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const html = fs.readFileSync(path.join(root, 'wizard.html'), 'utf8');
const m = html.match(/<script id="diagrams">\n([\s\S]*?)<\/script>/);
if (!m) { console.error('wizard.html has no <script id="diagrams"> block.'); process.exit(2); }
const DG = vm.runInNewContext(m[1] + '\nDG', {});
const want = DG.files();
const dir = path.join(root, 'docs', 'diagrams');
const have = new Set();
(function walk(d) {
  if (!fs.existsSync(d)) return;
  for (const e of fs.readdirSync(d, { withFileTypes: true })) {
    const p = path.join(d, e.name);
    if (e.isDirectory()) walk(p);
    else if (e.name.endsWith('.svg')) have.add(path.relative(dir, p).split(path.sep).join('/'));
  }
})(dir);

// The README's step lists, in Markdown, from the same steps as the wizard.
function stepsMarkdown(key) {
  const ctx = DG.DOC_CTX[key], steps = DG.visibleSteps(key, ctx);
  // `code` stays as it is; elsewhere < and > are escaped, so that <name> shows.
  const md = t => DG.F(t || '', ctx).split(/(`[^`]*`)/).map((x, i) => i % 2 ? x : x.replace(/</g, '&lt;').replace(/>/g, '&gt;')).join('');
  const code = c => '       ' + c;
  const where = { term: 'In the terminal', agent: 'In Claude Code', web: 'In the wizard', file: 'In your files' };
  return steps.map((st, i) => {
    const n = String(i + 1).padStart(2, '0'), out = [];
    out.push(`${i + 1}. **${md(st.title)}** *${where[st.where]}.*${st.body ? ' ' + md(st.body) : ''}`);
    if (st.how) out.push(`   On a Mac: ${st.how.mac} On Windows: ${st.how.win} On Linux: ${st.how.linux}`);
    if (st.cmd) {
      const mac = DG.F(st.cmd, Object.assign({}, ctx, { os: 'mac' })), win = DG.F(st.cmd, Object.assign({}, ctx, { os: 'win' })), lin = DG.F(st.cmd, Object.assign({}, ctx, { os: 'linux' }));
      if (st.where !== 'file') out.push(st.where === 'agent' ? '   Type this in Claude Code, then press Enter:' : '   Type this, then press Enter:');
      out.push(code(mac));
      if (lin !== mac) out.push('   On Linux:\n\n' + code(lin));
      if (win.replace(/^py /, 'python3 ') !== mac) out.push('   On Windows (PowerShell):\n\n' + code(win));
    }
    if (st.click) out.push(`   Click: ${md(st.click)}`);
    if (st.see) out.push(`   You should see: ${md(st.see)}`);
    if (st.ifnot) out.push(`   If not: ${md(st.ifnot)}`);
    out.push(`   <img src="docs/diagrams/steps/${key}-${n}.svg" alt="${DG.WHERE[st.where]}: ${md(st.title).replace(/[*`"]/g, '')}" width="420">`);
    return out.join('\n\n');
  }).join('\n\n') + '\n';
}
const readmePath = path.join(root, 'README.md');
let readme = fs.readFileSync(readmePath, 'utf8'), readmeNew = readme;
for (const key of ['first', 'group']) {
  const re = new RegExp(`(<!-- steps:${key}:begin[^>]*-->\n)[\\s\\S]*?(<!-- steps:${key}:end -->)`);
  if (re.test(readmeNew)) readmeNew = readmeNew.replace(re, (m, a, b) => a + '\n' + stepsMarkdown(key) + '\n' + b);
}
const readmeStale = readmeNew !== readme;

const stale = Object.keys(want).filter(n => !have.has(n) || fs.readFileSync(path.join(dir, n), 'utf8') !== want[n] + '\n');
const extra = [...have].filter(n => !(n in want));
if (process.argv.includes('--check')) {
  if (stale.length || extra.length || readmeStale) {
    console.log('docs/diagrams/ or the README\'s step lists are out of date. Run: node dev/diagrams.mjs');
    if (readmeStale) console.log('  to write:  README.md (the step lists)');
    stale.forEach(n => console.log('  to write:  ' + n));
    extra.forEach(n => console.log('  to remove: ' + n));
    process.exit(1);
  }
  console.log(`docs/diagrams/: ${Object.keys(want).length} pictures, all up to date.`);
  process.exit(0);
}
for (const n of stale) {
  fs.mkdirSync(path.dirname(path.join(dir, n)), { recursive: true });
  fs.writeFileSync(path.join(dir, n), want[n] + '\n');
}
for (const n of extra) fs.unlinkSync(path.join(dir, n));
if (readmeStale) fs.writeFileSync(readmePath, readmeNew);
console.log(`docs/diagrams/: wrote ${stale.length}, removed ${extra.length}, ${Object.keys(want).length} in all.` + (readmeStale ? ' README.md: the step lists rewritten.' : ''));
