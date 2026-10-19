/* Headless tests for the pure functions of colshaft.js (Task 10, ruling 10-5).
 *
 *   node tests/js/test_colshaft_js.js                 -> runs the asserts
 *   node tests/js/test_colshaft_js.js --dump <path>   -> also writes the payload built
 *        from the sample 2-bent state (with the colshaft_2bent.txt paste) to <path>,
 *        which tests/test_colshaft_ui_static.py feeds into Api().run_colshaft.
 *
 * Plain Node asserts, no npm dependencies.
 */
'use strict';
const assert = require('assert');
const fs = require('fs');
const path = require('path');

const ROOT = path.resolve(__dirname, '..', '..');
const CS = require(path.join(ROOT, 'colshaft.js'));
const PASTE = fs.readFileSync(path.join(ROOT, 'tests', 'fixtures_csi', 'colshaft_2bent.txt'), 'utf8');

let n = 0;
function test(name, fn) {
  fn();
  n += 1;
  console.log('ok - ' + name);
}

// Sample state mirroring tests/test_colshaft_engine.py bent1 / bent2 (UI units: ft, in, ksi)
function sampleState() {
  const s = CS.defaultState();
  s.paste = PASTE;
  s.categories = { DEAD: 'Dead', 'Str-I': 'Strength', 'EQ-X': 'Extreme' };
  const b1 = CS.defaultBent(0);
  Object.assign(b1, { name: 'B1', col_frames: '101', shaft_frames: '102', shaft_basis: 'cantilever', L_eq_ft: 10 });
  Object.assign(b1.col, { D: 60, fc: 4, fy: 60, cover: 2 });
  Object.assign(b1.shaft, { D: 84, fc: 4, fy: 60, cover: 3 });
  const b2 = CS.defaultBent(1);
  Object.assign(b2, { name: 'B2', col_frames: '201', soil: 'Stiff clay over sand', L_embed_ft: 60 });
  Object.assign(b2.col, { D: 54, fc: 4, fy: 60, cover: 2 });
  Object.assign(b2.shaft, { D: 78, fc: 4, fy: 60, cover: 3 });
  s.bents = [b1, b2];
  const soil = CS.defaultSoil(0);
  soil.name = 'Stiff clay over sand';
  soil.layers = [
    { thickness_ft: 20, py_model: 'welch_stiff_clay', gamma_pcf: 125, su_top_ksf: 2.5, su_bot_ksf: 3.0,
      eps50: 0.005, phi_deg: '', k_pci: '', submerged: false },
    { thickness_ft: 60, py_model: 'api_sand', gamma_pcf: 125, su_top_ksf: '', su_bot_ksf: '', eps50: '',
      phi_deg: 36, k_pci: 90, submerged: true }];
  s.soils = [soil];
  return s;
}

test('payload keys match the run_colshaft schema', () => {
  const p = CS.buildPayload(sampleState());
  assert.deepStrictEqual(Object.keys(p).sort(),
    ['bents', 'categories', 'code', 'params', 'paste', 'settings', 'units']);
  assert.strictEqual(p.code, 'SDC 2.1');
  assert.deepStrictEqual(p.settings, { envelope_mode: 'station', slenderness_on: false });
  assert.deepStrictEqual(Object.keys(p.params).sort(),
    ['maxBar', 'maxLegs', 'minBar', 'minSpacing', 'sMax', 'sMin', 'sStep', 'stirMax', 'stirMin']);
  assert.deepStrictEqual(p.units, { force: 'kip', moment: 'kip-ft', length: 'ft' });
  const [b1, b2] = p.bents;
  for (const k of ['name', 'col_frames', 'shaft_frames', 'column', 'shaft', 'end_condition_long',
    'end_condition_trans', 'base_end', 'H_in', 'slender']) assert.ok(k in b1, k);
  assert.deepStrictEqual(b1.col_frames, ['101']);
  assert.deepStrictEqual(b1.shaft_frames, ['102']);
  assert.deepStrictEqual(b1.column, { D: 60, fc: 4, fy: 60, cover: 2, trans_type: 'hoop', hoop_closure: 'lap' });
  assert.deepStrictEqual(b1.shaft, { D: 84, fc: 4, fy: 60, cover: 3, trans_type: 'hoop' });
  assert.strictEqual(b1.L_eq_in, 120);            // ft -> in
  assert.strictEqual(b1.shaft_basis, 'cantilever');
  assert.strictEqual(b1.H_in, null);              // blank = auto
  assert.strictEqual(b1.lambda_mo, 1.2);
  assert.ok(!('mu_d' in b1), 'blank mu_d is omitted (engine default)');
  assert.ok(!('P_dead' in b1));
  assert.ok(!('override' in b1));
  assert.ok(!('soil' in b1));
  assert.deepStrictEqual(b1.slender['2'], { braced: false, K: null, lu: null });
  // bent 2: soil basis by default (auto), soil payload in engine units
  assert.ok(!('shaft_basis' in b2));
  assert.strictEqual(b2.L_embed_in, 720);
  assert.deepStrictEqual(b2.soil_bounds, [2.0, 0.5]);
  assert.strictEqual(b2.soil.J, 0.5);
  assert.strictEqual(b2.soil.cyclic, true);
  assert.deepStrictEqual(b2.soil.layers[0], { thickness_ft: 20, py_model: 'welch_stiff_clay', gamma_pcf: 125,
    su_top_ksf: 2.5, su_bot_ksf: 3.0, eps50: 0.005, submerged: false });
  assert.deepStrictEqual(b2.soil.layers[1], { thickness_ft: 60, py_model: 'api_sand', gamma_pcf: 125,
    phi_deg: 36, k_pci: 90, submerged: true });
  // spiral column -> no hoop_closure; H override in ft -> in
  const s = sampleState();
  s.bents[0].col.trans_type = 'spiral';
  s.bents[0].H_ft = 20;
  s.bents[0].mu_d = 4;
  const q = CS.buildPayload(s).bents[0];
  assert.ok(!('hoop_closure' in q.column));
  assert.strictEqual(q.H_in, 240);
  assert.strictEqual(q.mu_d, 4);
});

test('overrides: only filled parts are sent; partial ones are validation errors', () => {
  const s = sampleState();
  s.bents[0].override.col_long = { bar: 5, n: 6, bundle: '' };
  s.bents[0].override.shaft_trans = { bar: 4, s: 6, ties: '' };
  const ov = CS.buildPayload(s).bents[0].override;
  assert.deepStrictEqual(ov, { col_long: { bar: 5, n: 6, bundle: 1 }, shaft_trans: { bar: 4, s: 6, ties: 0 } });
  assert.deepStrictEqual(CS.validateState(s), []);
  s.bents[0].override.col_trans = { bar: 5, s: '', ties: '' };
  const e = CS.validateState(s);
  assert.strictEqual(e.length, 1);
  assert.ok(/override col trans/.test(e[0]), e[0]);
});

test('getState / setState round-trip (normalizeState + serializeState)', () => {
  const s = sampleState();
  s.bents[1].override.col_long = { bar: 10, n: 22, bundle: 1 };
  s.settings.slenderness_on = true;
  s.code = 'AASHTO SGS 3rd Ed.';
  s.parse = { cases: [{ name: 'DEAD', count: 3, default_category: 'Dead' }], frames: [], n_rows: 3, n_envelope: 0, warnings: [] };
  const saved = JSON.parse(JSON.stringify(CS.serializeState(s)));   // as written to the project file
  const back = CS.normalizeState(saved);
  assert.deepStrictEqual(back, CS.serializeState(s));
  assert.deepStrictEqual(CS.buildPayload(back), CS.buildPayload(s));
  // missing key / garbage -> empty default tab
  assert.deepStrictEqual(CS.normalizeState(null), CS.defaultState());
  assert.deepStrictEqual(CS.normalizeState(undefined), CS.defaultState());
  assert.deepStrictEqual(CS.normalizeState('x'), CS.defaultState());
  // partial / old object gets the defaults filled in; unknown code falls back
  const p = CS.normalizeState({ paste: 'abc', code: 'nope', bents: [{ name: 'X', col: { D: 66 } }] });
  assert.strictEqual(p.paste, 'abc');
  assert.strictEqual(p.code, 'SDC 2.1');
  assert.strictEqual(p.bents[0].col.D, 66);
  assert.strictEqual(p.bents[0].col.fc, 4);
  assert.strictEqual(p.bents[0].lambda_mo, 1.2);
  assert.deepStrictEqual(p.bents[0].override, CS.defaultBent(0).override);
  assert.deepStrictEqual(p.params, CS.DEFAULT_PARAMS);
  assert.strictEqual(p.settings.slenderness_on, false);
});

test('L_eq validation: required without a soil profile', () => {
  const s = sampleState();
  assert.deepStrictEqual(CS.validateState(s), []);
  s.bents[0].L_eq_ft = '';
  let e = CS.validateState(s);
  assert.strictEqual(e.length, 1);
  assert.ok(/L_eq/.test(e[0]) && /B1/.test(e[0]), e[0]);
  // auto basis without soil -> cantilever -> L_eq required as well
  s.bents[0].shaft_basis = 'auto';
  assert.ok(/L_eq/.test(CS.validateState(s)[0]));
  // interface basis needs neither
  s.bents[0].shaft_basis = 'interface';
  assert.deepStrictEqual(CS.validateState(s), []);
  // a soil profile replaces L_eq (auto -> soil); then the embedded length is required
  s.bents[0].shaft_basis = 'auto';
  s.bents[0].soil = 'Stiff clay over sand';
  s.bents[0].L_embed_ft = '';
  e = CS.validateState(s);
  assert.strictEqual(e.length, 1);
  assert.ok(/embedded length/.test(e[0]), e[0]);
  s.bents[0].L_embed_ft = 50;
  assert.deepStrictEqual(CS.validateState(s), []);
  // explicit soil basis without a profile
  s.bents[0].soil = '';
  s.bents[0].shaft_basis = 'soil';
  assert.ok(/soil profile/.test(CS.validateState(s)[0]));
  // zero L_eq is allowed (engine accepts >= 0); negative is not
  s.bents[0].shaft_basis = 'cantilever';
  s.bents[0].L_eq_ft = 0;
  assert.deepStrictEqual(CS.validateState(s), []);
  s.bents[0].L_eq_ft = -1;
  assert.strictEqual(CS.validateState(s).length, 1);
});

test('other validation: paste, frames, slenderness K', () => {
  const s = sampleState();
  s.paste = '  ';
  s.bents[0].col_frames = '';
  const e = CS.validateState(s);
  assert.ok(e.some(x => /Paste/.test(x)));
  assert.ok(e.some(x => /column frame/.test(x)));
  const t = sampleState();
  t.settings.slenderness_on = true;
  assert.ok(CS.validateState(t).some(x => /enter K/.test(x)));
  for (const b of t.bents) { b.slender['2'].K = 2.1; b.slender['3'].K = 0.8; }
  assert.ok(CS.validateState(t).some(x => /unbraced K must be >= 1.0/.test(x)));
  for (const b of t.bents) b.slender['3'].braced = true;
  assert.deepStrictEqual(CS.validateState(t), []);
});

test('status colour map and precedence', () => {
  assert.strictEqual(CS.statusColor('OK'), '#27ae60');
  assert.strictEqual(CS.statusColor('NG'), '#c0392b');
  assert.strictEqual(CS.statusColor('NO SOLUTION'), '#7b1010');
  assert.strictEqual(CS.statusColor('REFINED ANALYSIS REQUIRED'), '#e67e22');
  assert.strictEqual(CS.statusColor('???'), '#7f8c8d');
  assert.deepStrictEqual(Object.keys(CS.STATUS_COLORS).sort(),
    ['NG', 'NO SOLUTION', 'OK', 'REFINED ANALYSIS REQUIRED']);
  assert.strictEqual(CS.worstStatus(['OK', 'NG']), 'NG');
  assert.strictEqual(CS.worstStatus(['NG', 'REFINED ANALYSIS REQUIRED', 'OK']), 'REFINED ANALYSIS REQUIRED');
  assert.strictEqual(CS.worstStatus(['REFINED ANALYSIS REQUIRED', 'NO SOLUTION']), 'NO SOLUTION');
  assert.strictEqual(CS.worstStatus([]), 'OK');
});

test('categories merge after a re-parse keeps user choices', () => {
  const m = CS.mergeCategories({ DEAD: 'Ignore', OLD: 'Dead' },
    [{ name: 'DEAD', default_category: 'Dead' }, { name: 'EQ', default_category: 'Extreme' }]);
  assert.deepStrictEqual(m, { DEAD: 'Ignore', EQ: 'Extreme' });
});

test('result formatting (grid rows, kip-in -> kip-ft, drill-down rows, checks)', () => {
  const res = {
    code: 'SDC 2.1', settings: { envelope_mode: 'station', slenderness_on: true },
    bents: [{
      name: 'B1', status: 'NG',
      lrfd: { col: { long: { bar: 11, n: 15, bundle: 1 }, trans: { bar: 5, s: 4, ties: 0 },
        check_rows: [
          { Pu: -800, Mu: 24000, Vu: 100, Tu: 120, Mr: 36000, Vr2: 500, Tr: 1200, ratio: 0.5, ok: true,
            _case: 'Str-I', _frame: '101', _station: 0, _klr2: 40.2, _klr3: 55.5, _slender_status: 'magnify',
            _Pmin: -1100, _Pmax: -800, _flexP: -1100, flexStatus: 'OK', shearStatus: 'NR' },
          { Pu: -900, Mu: 30000, Vu: 100, Tu: 0, Mr: 33000, Vr2: 500, Tr: 1200, ratio: 0.91, ok: true,
            _case: 'Str-II', _frame: '101', _station: 240, _klr2: 20, _klr3: 21, _slender_status: 'neglect' }] } },
      seismic: { Mp: 60000, Mo: 72000, Vo: 300, shaft_Mdemand: 84000, shaft_Mp: 120000,
        shaft_profile: [[0, 72000, 300], [120, 108000, 300]],
        required_transverse: { ok: true, bar: 6, s: 4.5, ties: 0 } },
      final: { col_long: { bar: 11, n: 15, bundle: 1 }, col_trans: { bar: 6, s: 4.5, ties: 0 },
        shaft_long: { bar: 14, n: 22, bundle: 2 }, shaft_trans: { bar: 5, s: 6, ties: 2 } },
      final_source: { col_long: 'Override', col_trans: 'Seismic', shaft_long: 'LRFD', shaft_trans: 'LRFD+Seismic' },
      final_checks: [
        { group: 'Seismic', name: 'Shaft shear (capacity protection)', demand: 300, capacity: 900, ratio: 0.333, ok: true, detail: '', ref: 'x' },
        { group: 'Seismic', name: 'Shaft flexure (capacity protection)', demand: 84000, capacity: 120000, ratio: 0.7, ok: true, detail: '', ref: 'y' },
        { group: 'Seismic', name: 'Inf', demand: 1, capacity: 0, ratio: null, ratio_infinite: true, ok: false, detail: '', ref: '' }]
    }, { name: 'B2', status: 'NO SOLUTION', lrfd: { col: { long: null, trans: null } }, seismic: null, final: null,
      final_source: { col_long: 'LRFD', col_trans: 'LRFD' }, final_checks: [] }]
  };
  const rows = CS.resultRows(res);
  assert.strictEqual(rows.length, 2);
  const r = rows[0];
  assert.strictEqual(r.color, '#c0392b');
  assert.strictEqual(r.lrfd_col, '15-#11 / #5 @ 4.00 in');
  assert.strictEqual(r.seismic_col, '#6 @ 4.50 in');
  assert.strictEqual(r.override, 'col long');
  assert.strictEqual(r.Mp, '5000');
  assert.strictEqual(r.Mo, '6000');
  assert.strictEqual(r.Vo, '300');
  assert.strictEqual(r.slender, '55.5 (magnify)');
  assert.strictEqual(r.shaft_M, '7000 (10.0 ft) / 10000');
  assert.strictEqual(r.shaft_V, '300 / 900');
  assert.ok(r.final.indexOf('Shaft 22-#14 (bundles of 2) (LRFD), #5 @ 6.00 in + 2 ties (LRFD+Seismic)') >= 0, r.final);
  assert.strictEqual(rows[1].color, '#7b1010');
  assert.strictEqual(rows[1].Mp, '—');
  assert.strictEqual(rows[1].final, '—');
  res.settings.slenderness_on = false;
  assert.strictEqual(CS.resultRows(res)[0].slender, 'off');
  const g = CS.governingRows(res.bents[0].lrfd.col.check_rows);
  assert.strictEqual(g[0].ratio, 0.91);                // sorted by D/C
  assert.strictEqual(g[0].cells[2], '101 @ 20.0 ft');
  assert.strictEqual(g[0].cells[6], '2500');            // Mu kip-ft
  assert.strictEqual(g[0].cells[7], '2750');            // Mr kip-ft
  assert.strictEqual(g[1].cells[8], '-1100');           // P governing flexure
  assert.strictEqual(g[1].cells[5], '-1100 .. -800');
  const c = res.bents[0].final_checks.map(CS.checkRow);
  assert.deepStrictEqual(c[1].slice(2, 6), ['7000', '10000', '0.700', 'OK']);
  assert.strictEqual(c[2][4], '∞');
  assert.strictEqual(c[2][5], 'NG');
});

test('svgPlot returns an inline SVG polyline and escapes text', () => {
  const s = CS.svgPlot([{ points: [[0, 0], [1, 2], [2, 1]], color: '#123456' }],
    { title: 'M<z>', xlabel: 'x', ylabel: 'y', invertY: true, hlines: [{ y: 1, label: 'Df' }] });
  assert.ok(s.startsWith('<svg'));
  assert.ok(s.indexOf('<polyline') > 0 && s.indexOf('#123456') > 0);
  assert.ok(s.indexOf('M&lt;z&gt;') > 0);
  assert.ok(s.indexOf('</script') < 0);
  assert.ok(/No data/.test(CS.svgPlot([{ points: [] }], {})));
});

test('helpers: splitFrames, setPath/getPath, esc, num', () => {
  assert.deepStrictEqual(CS.splitFrames(' 101, 102;103  104 '), ['101', '102', '103', '104']);
  assert.deepStrictEqual(CS.splitFrames(''), []);
  const o = {};
  CS.setPath(o, 'bents.0.col.D', 5);
  assert.deepStrictEqual(o, { bents: [{ col: { D: 5 } }] });
  assert.strictEqual(CS.getPath(o, 'bents.0.col.D'), 5);
  assert.strictEqual(CS.getPath(o, 'bents.3.col.D'), undefined);
  assert.strictEqual(CS.esc('<a href="x">&</a>'), '&lt;a href=&quot;x&quot;&gt;&amp;&lt;/a&gt;');
  assert.strictEqual(CS.num(''), null);
  assert.strictEqual(CS.num('2.5'), 2.5);
  assert.strictEqual(CS.num('abc'), null);
  assert.strictEqual(CS.num(0), 0);
});

test('auto H from the parse summary', () => {
  const s = sampleState();
  s.parse = { frames: [{ name: '101', height_in: 240 }, { name: '102', height_in: 120 }] };
  assert.strictEqual(CS.autoHeightFt(s, s.bents[0]), 20);
  s.bents[0].col_frames = '101, 102';
  assert.strictEqual(CS.autoHeightFt(s, s.bents[0]), 30);
  s.bents[0].col_frames = '999';
  assert.strictEqual(CS.autoHeightFt(s, s.bents[0]), null);
});

const di = process.argv.indexOf('--dump');
if (di > 0) {
  fs.writeFileSync(process.argv[di + 1], JSON.stringify(CS.buildPayload(sampleState())));
  console.log('payload written to ' + process.argv[di + 1]);
}
console.log('ALL ' + n + ' TESTS PASSED');
