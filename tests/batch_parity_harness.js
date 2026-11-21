// Parity harness: runs the app's own input-conversion JavaScript (index.html) against a stub DOM.
// Usage: node batch_parity_harness.js <index.html> <cases.json>
// cases.json: [{form:{<element id>: value|bool}, units:{force,length}, state?:<section state>}, ...]
// Prints a JSON list: [{gather:<gatherInputs()>, fromState:<buildInputsFromState(state)>|undefined}, ...]
'use strict';
const fs = require('fs');

const html = fs.readFileSync(process.argv[2], 'utf8');
const cases = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const src = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m => m[1]).join('\n');

function grabBlock(start) {
  const i = src.indexOf(start);
  if (i < 0) throw new Error('not found: ' + start);
  const j = src.indexOf('{', i);
  let depth = 0;
  for (let k = j; k < src.length; k++) {
    if (src[k] === '{') depth++;
    else if (src[k] === '}') { depth--; if (!depth) return src.slice(i, k + 1); }
  }
  throw new Error('unbalanced: ' + start);
}
const grabLine = start => { const i = src.indexOf(start); return src.slice(i, src.indexOf('\n', i)); };

const FUNCS = ['VE', 'setVE', 'unitFactor', 'fromEngine', 'toEngine', 'computeWc', 'computeEcAASHTO',
  'barsFromSpacing', 'clearWidthAt', 'widthAtDepth', 'circParamsFromDOM', 'circParamsFromState',
  'circPayload', 'resolveMRRows', 'isCircUI', 'gatherInputs', '_stateInputsToEngine', '_buildInputsExtras',
  'buildInputsFromState'];
const code = [grabLine('const V=id=>'), grabBlock('const BARS='), grabBlock('const INPUT_FIELD_KINDS'),
  grabBlock('const _STATE_INPUT_KINDS='),
  ...FUNCS.map(f => grabBlock('function ' + f + '('))].join(';\n');

let FORM = {};
const elements = {};
function el(id) {
  if (!elements[id]) {
    const has = Object.prototype.hasOwnProperty.call(FORM, id);
    const v = has ? FORM[id] : '';
    elements[id] = {
      id, value: typeof v === 'boolean' ? '' : String(v), checked: typeof v === 'boolean' ? v : false,
      readOnly: false, textContent: '', innerHTML: '',
      classList: { add() {}, remove() {} },
    };
  }
  return elements[id];
}
global.document = {
  getElementById: el,
  querySelectorAll(sel) {
    if (sel !== '.factor-ovr-cb') return [];
    return Object.keys(FORM).filter(k => k.endsWith('_ovr') && FORM[k + '_val'] !== undefined)
      .map(k => ({ checked: !!FORM[k], dataset: { factor: k.slice(0, -4) } }));
  },
};
global.window = {};
global.mrData = { top: null, bot: null };
global.displayUnits = { force: 'kip', length: 'in' };

// Evaluate the app code once in this scope; FORM / displayUnits are swapped per case.
const run = new Function('getCase', code + `;
  return getCase(gatherInputs, buildInputsFromState);`);

const out = cases.map(c => {
  FORM = c.form;
  for (const k of Object.keys(elements)) delete elements[k];
  global.displayUnits = c.units || { force: 'kip', length: 'in' };
  return run((gather, fromState) => ({
    gather: gather(),
    fromState: c.state ? fromState(c.state) : undefined,
  }));
});
process.stdout.write(JSON.stringify(out));
