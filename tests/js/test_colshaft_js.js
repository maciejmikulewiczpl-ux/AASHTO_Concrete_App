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
const ST = CS.SLENDER_STATUS;   // mirrors colshaft_slender (pinned by the pytest)
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
  assert.deepStrictEqual(b1.column, { D: 60, fc: 4, fy: 60, cover: 2, trans_type: 'hoop', hoop_closure: 'lap',
    bars_terminated: false });
  assert.deepStrictEqual(b1.shaft, { D: 84, fc: 4, fy: 60, cover: 3, trans_type: 'hoop', bars_terminated: false });
  assert.strictEqual(b1.L_eq_in, 120);            // ft -> in
  assert.strictEqual(b1.shaft_basis, 'cantilever');
  assert.strictEqual(b1.H_in, null);              // blank = auto
  assert.strictEqual(b1.lambda_mo, 1.2);
  assert.ok(!('mu_d' in b1), 'blank mu_d is omitted (engine default)');
  assert.ok(!('P_dead' in b1));
  assert.ok(!('override' in b1));
  assert.ok(!('soil' in b1));
  assert.deepStrictEqual(b1.slender['2'], { braced: false, K_source: 'default', end_condition: 'fixed-free', K: null, lu: null,
    K_braced_source: 'default', K_braced: null });
  assert.ok(!('sway_group' in b1), 'blank sway group is omitted (bent alone)');
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
  // 2026-10-19: K is not required with the default source
  assert.deepStrictEqual(CS.validateState(t), []);
  for (const b of t.bents) { b.slender['2'].K_source = 'analysis'; b.slender['3'].K_source = 'analysis'; }
  assert.ok(CS.validateState(t).some(x => /enter K > 0 from the buckling analysis/.test(x)));
  for (const b of t.bents) { b.slender['2'].K = 2.1; b.slender['3'].K = 0.8; }
  // unbraced K < 1.0 from analysis is a warning, not an error
  assert.deepStrictEqual(CS.validateState(t), []);
  assert.ok(CS.kInfoText(t.bents[0].slender['3']).indexOf('below the C5.6.4.3 floor') > 0);
  for (const b of t.bents) b.slender['3'].K = 0;
  assert.ok(CS.validateState(t).some(x => /axis 3: enter K > 0/.test(x)));
  // ruling M2: the braced K (delta_b) from analysis must be > 0
  const u = sampleState();
  u.settings.slenderness_on = true;
  u.bents[0].slender['2'].K_braced_source = 'analysis';
  assert.ok(CS.validateState(u).some(x => /axis 2: enter the braced K > 0/.test(x)));
  u.bents[0].slender['2'].K_braced = 0.9;
  assert.deepStrictEqual(CS.validateState(u), []);
});

test('status colour map and precedence', () => {
  assert.strictEqual(CS.statusColor('OK'), '#27ae60');
  assert.strictEqual(CS.statusColor('NG'), '#c0392b');
  assert.strictEqual(CS.statusColor('NO SOLUTION'), '#7b1010');
  assert.strictEqual(CS.statusColor('REFINED ANALYSIS REQUIRED'), '#e67e22');
  assert.strictEqual(CS.statusColor('???'), '#7f8c8d');
  assert.deepStrictEqual(Object.keys(CS.STATUS_COLORS).sort(),
    ['NG', 'NO SOLUTION', 'OK', 'REFINED ANALYSIS REQUIRED', 'UNSTABLE (Pu ≥ φK·Pe)']);
  assert.strictEqual(CS.worstStatus(['OK', 'NG']), 'NG');
  // ruling M10: NO SOLUTION > UNSTABLE > REFINED > NG > OK; dark red; fail class
  const U = CS.ST_UNSTABLE;
  assert.strictEqual(U, 'UNSTABLE (Pu ≥ φK·Pe)');
  assert.strictEqual(CS.worstStatus(['OK', 'REFINED ANALYSIS REQUIRED', U, 'NG']), U);
  assert.strictEqual(CS.worstStatus([U, 'NO SOLUTION']), 'NO SOLUTION');
  assert.strictEqual(CS.statusColor(U), '#922b21');
  assert.deepStrictEqual(['OK', U, 'NG', 'NO SOLUTION'].map(CS.statusClass),
    ['rpt-pass', 'rpt-fail', 'rpt-fail', 'rpt-fail']);
  assert.ok(!('ST_OK_PENDING' in CS));
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
            _case: 'Str-I', _frame: '101', _station: 0, _klr2: 40.2, _klr3: 55.5, _slender_status: ST.MAGNIFIED,
            _Pmin: -1100, _Pmax: -800, _flexP: -1100, flexStatus: 'OK', shearStatus: 'NR' },
          { Pu: -900, Mu: 30000, Vu: 100, Tu: 0, Mr: 33000, Vr2: 500, Tr: 1200, ratio: 0.91, ok: true,
            _case: 'Str-II', _frame: '101', _station: 240, _klr2: 20, _klr3: 21, _slender_status: ST.NEGLECT }] } },
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
  assert.strictEqual(r.slender, '55.5 (magnified)');
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

test('slenderness summary ranks the engine strings: refined > magnified > neglect', () => {
  assert.deepStrictEqual(ST, { NEGLECT: 'neglect', MAGNIFIED: 'magnified',
    REFINED: 'refined analysis required' });
  const on = { slenderness_on: true };
  const bent = rows => ({ lrfd: { col: { check_rows: rows } } });
  // reviewer repro: a neglect row first, then a refined row at K*lu/r = 120
  assert.strictEqual(CS.slenderSummary(bent([{ _klr2: 20, _klr3: 18, _slender_status: ST.NEGLECT },
    { _klr2: 120, _klr3: 90, _slender_status: ST.REFINED }]), on), '120.0 (refined analysis required)');
  assert.strictEqual(CS.slenderSummary(bent([{ _klr2: 120, _slender_status: ST.REFINED },
    { _klr2: 40, _slender_status: ST.MAGNIFIED }, { _klr2: 10, _slender_status: ST.NEGLECT }]), on),
  '120.0 (refined analysis required)');
  assert.strictEqual(CS.slenderSummary(bent([{ _klr2: 10, _slender_status: ST.NEGLECT },
    { _klr2: 40, _slender_status: ST.MAGNIFIED }]), on), '40.0 (magnified)');
  assert.strictEqual(CS.slenderSummary(bent([{ _klr2: 10, _slender_status: ST.NEGLECT }]), on), '10.0 (neglect)');
  assert.strictEqual(CS.slenderSummary(bent([]), { slenderness_on: false }), 'off');
});

test('setState robustness: malformed saved objects normalise without throwing', () => {
  const bad = [
    { parse: { frames: 'x', cases: 5, warnings: null } },
    { parse: { frames: [null, 3, { name: '101', height_in: 240 }], cases: [{ name: 'D' }, 'y'], warnings: [1, 'w'] } },
    { bents: 'nope', soils: { a: 1 } },
    { bents: [null, 7], soils: [null, { layers: 'z' }] },
    { settings: null, params: 'q', units: 3, categories: [] }];
  for (const o of bad) {
    const st = CS.normalizeState(o);
    assert.ok(Array.isArray(st.bents) && Array.isArray(st.soils));
    if (st.parse) {
      for (const k of ['frames', 'cases', 'warnings']) assert.ok(Array.isArray(st.parse[k]), k);
      CS.autoHeightFt(st, CS.defaultBent(0));
    }
    CS.validateState(st);
    CS.buildPayload(st);
  }
  const p = CS.normalizeState(bad[1]).parse;
  assert.deepStrictEqual(p.frames, [{ name: '101', height_in: 240 }]);
  assert.deepStrictEqual(p.cases, [{ name: 'D' }]);
  assert.deepStrictEqual(p.warnings, ['1', 'w']);
  assert.deepStrictEqual(CS.normalizeState(bad[0]).parse, { frames: [], cases: [], warnings: [] });
});

test('override range checks', () => {
  const b = CS.defaultBent(0);
  assert.deepStrictEqual(CS.overrideErrors(b), []);
  const cases = [
    ['col_long', { bar: 12, n: 8, bundle: '' }, /bar must be one of/],
    ['col_long', { bar: 8, n: 5, bundle: '' }, /n must be a whole number >= 6/],
    ['col_long', { bar: 8, n: 7.5, bundle: '' }, /n must be a whole number >= 6/],
    ['col_long', { bar: 8, n: 8, bundle: 4 }, /bundle must be 1, 2 or 3/],
    ['shaft_long', { bar: 8, n: 8, bundle: 0 }, /bundle must be 1, 2 or 3/],
    ['col_trans', { bar: 5, s: 0, ties: '' }, /s must be > 0/],
    ['col_trans', { bar: 5, s: 4, ties: -1 }, /ties must be a whole number >= 0/],
    ['shaft_trans', { bar: 5, s: 4, ties: 1.5 }, /ties must be a whole number >= 0/],
    ['shaft_trans', { bar: 13, s: 4, ties: '' }, /bar must be one of/]];
  for (const [part, val, re] of cases) {
    const x = CS.defaultBent(0);
    x.override[part] = val;
    const e = CS.overrideErrors(x);
    assert.strictEqual(e.length, 1, JSON.stringify(val));
    assert.ok(re.test(e[0]) && e[0].startsWith(part.replace('_', ' ')), e[0]);
  }
  const ok = CS.defaultBent(0);
  ok.override = { col_long: { bar: 18, n: 6, bundle: 3 }, col_trans: { bar: 5, s: 0.5, ties: 0 },
    shaft_long: { bar: 2, n: 40, bundle: 1 }, shaft_trans: { bar: 8, s: 6, ties: 4 } };
  assert.deepStrictEqual(CS.overrideErrors(ok), []);
  assert.deepStrictEqual(CS.BAR_SIZES, [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 14, 18]);
});

test('P_dead hint (ruling 10-6)', () => {
  assert.strictEqual(CS.deadHint(null), '');
  assert.strictEqual(CS.deadHint({ axial: { P_dead: -2500, dead_cases: {} } }), '');
  assert.strictEqual(CS.deadHint({ axial: { P_dead: -1045, dead_cases: { DEAD: -990, DW: -55 } } }),
    'from Dead cases: DEAD -990, DW -55 kip (sum -1045 kip); the entered value is not used');
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

// ── Task 11: charts and the printable report ──
function reportFixture() {
  const ref = 'Caltrans SDC 2.1 §5.3.7.2 (concrete) & §5.3.7.3 (transverse)';
  return {
    code: 'SDC 2.1', settings: { envelope_mode: 'station', slenderness_on: true },
    parse: { n_rows: 12, n_envelope: 6, units: { force: 'kip', moment: 'kip-ft', length: 'ft' },
      categories: { DEAD: 'Dead', 'Str-I': 'Strength' }, warnings: ['No units row <assumed>', 'B<1>: frame 999 not found'] },
    bents: [{
      name: 'B<1>', status: 'OK', no_solution: [], warnings: ['frame 999 not found'], H_in: 240, Df_for_lu: 120,
      magnification: { beta_d: 0.0718, beta_d_source: 'gp', phi_K: 0.75, Ec: 3986.5, Es: 29000, Ig: 636172, Is: 10292,
        EI1: 7.5e8, EI2: 9.4e8, EI: 9.4e8, sway: null, axes: {
          '2': { braced: false, K_braced: 1.0, K_unbraced: 2.1, Pe_b: 72000, Pe_s: 16000, sPe_s: 16000, Cm: 1.0, db: 1.03, ds: 1.15, delta: 1.15, row: 1, case: 'Str-I', Pu: 1600, sPu: 1600, unstable: false },
          '3': { braced: false, K_braced: 1.0, K_unbraced: 2.1, Pe_b: 72000, Pe_s: 16000, sPe_s: 16000, Cm: 1.0, db: 1.03, ds: 1.15, delta: 1.15, row: 1, case: 'Str-I', Pu: 1600, sPu: 1600, unstable: false } } },
      shaft_basis: 'soil', axial: { P_dead: -950, dead_cases: { DEAD: -950 }, P_ext_min: -1400, P_ext_max: -500 },
      lrfd: { col: { check_rows: [
        { Pu: -800, Mu: 24000, Vu: 100, Tu: 120, Mr: 36000, Vr2: 500, Tr: 1200, ratio: 0.5, ok: true, _case: 'Str-I',
          _frame: '101', _station: 0, _klr2: 40, _klr3: 20, _slender_limit2: 22, _slender_limit3: 22, _slender_status: ST.MAGNIFIED },
        { Pu: -900, Mu: 30000, Vu: 90, Tu: 0, Mr: 33000, Vr2: 500, Tr: 1200, ratio: 0.91, ok: true, _case: 'Str-II',
          _frame: '101', _station: 240, _klr2: 120, _klr3: 10, _slender_limit2: 22, _slender_limit3: 22, _slender_status: ST.REFINED }] },
        shaft: { source: 'p-y strength', check_rows: [] } },
      seismic: {
        Mp_by_P: [[-950, 70000], [-1400, 76000], [-500, 60000]], Mp: 76000, Mp_P: -1400, Mo: 91200, Vo: 380, lambda_mo: 1.2,
        end_condition: 'fixed-free', H: 240, P_vc: -500, mu_d: 3, col_shear: [600, 200, 466.7], rho_s_col: 0.0081,
        rho_s_min: 0.006, s_max_detailing: 6.0, min_trans_bar: 0, shaft_basis: 'soil', shaft_profile: [[0, 91200, 380], [120, 99000, 300]],
        shaft_Mdemand: 99000, shaft_Mp: 160000, shaft_phiVn: 900, EI_col: 9e8, EI_shaft: 2e9, Df: 120,
        required_transverse: { ok: true, bar: 6, s: 4.5, ties: 0 },
        mphi: { P: -1400, phi: [0, 5e-5, 1e-4, 9e-4], M: [0, 50000, 76000, 79000], phi_y: 9e-5, Mp: 76000, phi_u: 9e-4, failure_mode: 'concrete' },
        mphi_shaft: { P: -950, phi: [0, 1e-4, 6e-4], M: [0, 150000, 162000], phi_y: 1e-4, Mp: 160000, phi_u: 6e-4, failure_mode: 'steel' },
        refs: { overstrength: 'Caltrans SDC 2.1 §4.4.2 (Mo = 1.2·Mp, A706)', flexure: 'Caltrans SDC 2.1 §5.3.6.2 (moment-curvature)',
          shear: ref, shaft_capacity: 'Caltrans SDC 2.1 §6.2.5.3', transverse: 'Caltrans SDC 2.1 §5.3.8.2' },
        pile: { Df_eq_gov: 120, bounds: [{ factor: 2, stable: true, Df_eq: 100, Mmax: 95000, z_Mmax: 60, Vmax: 380 },
          { factor: 0.5, stable: false, Df_eq: null, Mmax: null, z_Mmax: null, Vmax: null }],
        profiles_by_bound: [
          { factor: 2, stable: true, governing: true, z: [0, 60, 120], M: [91200, 95000, 0], V: [380, 0, -200], y: [0.5, 0.1, 0] },
          { factor: 0.5, stable: false, governing: false, z: [0, 60, 120], M: [1e9, 2e9, 3e9], V: [1e7, 0, 0], y: [99, 50, 0] }] }
      },
      final: { col_long: { bar: 11, n: 15, bundle: 1, Ast: 23.4, rho_l: 0.0105 }, col_trans: { bar: 6, s: 4.5, ties: 0, rho_s: 0.0081 },
        shaft_long: { bar: 14, n: 22, bundle: 1, Ast: 49.5, rho_l: 0.009 }, shaft_trans: { bar: 6, s: 6, ties: 0, rho_s: 0.005 } },
      final_source: { col_long: 'LRFD', col_trans: 'Seismic', shaft_long: 'Override', shaft_trans: 'LRFD+Seismic' },
      final_checks: [
        { group: 'Seismic', name: 'Column shear', demand: 380, capacity: 600, ratio: 0.633, ok: true, detail: 'Vo=380 <x>', ref: ref },
        { group: 'Seismic', name: 'Shaft flexure (capacity protection)', demand: 99000, capacity: 160000, ratio: 0.62, ok: true, detail: '', ref: 'Caltrans SDC 2.1 §6.2.5.3' },
        { group: 'Seismic', name: 'Shaft oversize', demand: 24, capacity: 24, ratio: 1, ok: true, detail: 'unverified', ref: '' },
        { group: 'Column LRFD', name: 'Row 1: Str-I (101 @ 0 ft)', demand: null, capacity: null, ratio: 0.5, ok: true, detail: '', ref: '' }]
    }, { name: 'B2', status: 'NO SOLUTION', no_solution: ['Column seismic transverse: none'], warnings: [], axial: {},
      lrfd: { col: { check_rows: [] } }, seismic: null, final: null, final_source: {}, final_checks: [] }]
  };
}
const RPT_PAYLOAD = { bents: [{ name: 'B<1>', col_frames: ['101'], shaft_frames: [],
  column: { D: 60, fc: 4, fy: 60, cover: 2, trans_type: 'hoop', hoop_closure: 'lap' },
  shaft: { D: 84, fc: 4, fy: 60, cover: 3, trans_type: 'hoop' }, end_condition_long: 'fixed-free', end_condition_trans: 'fixed-free',
  base_end: 'auto', H_in: null, L_embed_in: 720, soil_bounds: [2, 0.5], override: { shaft_long: { bar: 14, n: 22, bundle: 1 } },
  soil: { J: 0.5, cyclic: true, layers: [{ thickness_ft: 80, py_model: 'api_sand', gamma_pcf: 125, phi_deg: 36, k_pci: 90, submerged: true }] } },
{ name: 'B2' }] };

test('M-phi chart marks phi_y, Mp, phi_u; shaft charts draw every bound (unstable dashed, unscaled)', () => {
  const r = reportFixture(), S = r.bents[0].seismic;
  const m = CS.mphiChart(S.mphi, 'Column M-φ');
  assert.ok(m.startsWith('<svg') && m.indexOf('φy, Mp') > 0 && m.indexOf('φu') > 0 && m.indexOf('Mp = 6333') > 0, m);
  assert.ok(m.indexOf('P = -1400 kip') > 0);
  assert.ok(/No M-&phi; curve/.test(CS.mphiChart(null)));
  const ser = CS.shaftSeries(S, 'M');
  assert.strictEqual(ser.length, 2);
  assert.ok(ser[0].label.indexOf('governing') > 0 && ser[0].width > ser[1].width);
  assert.ok(ser[1].dash && ser[1].noScale && /unstable/.test(ser[1].label));
  assert.deepStrictEqual(ser[0].points[0], [91200 / 12, 0]);           // kip-ft vs depth (ft) below top of shaft
  const charts = CS.shaftCharts(S);
  assert.strictEqual(charts.length, 3);                                  // M, V, y
  assert.ok(charts[0].indexOf('stroke-dasharray="5,4"') > 0);
  // the unstable 1e9 values do not set the axis: the largest tick is the stable maximum
  assert.ok(charts[0].indexOf('>7917<') > 0 && charts[0].indexOf('166666667') < 0, charts[0]);
  // cantilever basis (no pile): shaft_profile, M and V only
  const cant = Object.assign({}, S, { pile: null });
  assert.strictEqual(CS.shaftCharts(cant).length, 2);
  assert.deepStrictEqual(CS.shaftSeries(cant, 'M')[0].points[1], [99000 / 12, 10]);
});

test('report: header, assumptions box, sections in order for every bent', () => {
  const r = reportFixture();
  const h = CS.reportHtml(r, RPT_PAYLOAD, { project: 'Bridge <1>', date: '2026-10-19' });
  assert.ok(h.indexOf('Column on Shaft — Design Report') >= 0);
  assert.ok(h.indexOf('Project: <b>Bridge &lt;1&gt;</b>') > 0 && h.indexOf('2026-10-19') > 0);
  assert.ok(h.indexOf('Seismic code: Caltrans SDC 2.1') > 0);
  // assumptions box: envelope bounding, magnification (rulings M5/M6/M9), every open E DECIDE id
  const a0 = h.indexOf('data-sec="assumptions"');
  const box = h.slice(a0, h.indexOf('</ul></li></ul></div>', a0));
  assert.ok(/envelope-bounded \(conservative\)/.test(box) && /max\(δb, δs\)·M2/.test(box) && /two-pass/.test(box), box);
  assert.ok(!/S6/.test(box), box);
  CS.OPEN_DECIDE_E.forEach(e => assert.ok(box.indexOf('<b>' + e[0] + '</b>') > 0, e[0]));
  // the 10 sections, in order, once per bent (including the NO SOLUTION bent)
  const keys = CS.REPORT_SECTIONS.map(s => s[0]);
  const seen = [...h.matchAll(/<h3 data-sec="([a-z]+)">/g)].map(x => x[1]);
  assert.deepStrictEqual(seen, keys.concat(keys));
  assert.ok(h.indexOf('Bent B&lt;1&gt; —') < h.indexOf('Bent B2 —'));
  const b1 = h.slice(h.indexOf('Bent B&lt;1&gt; —'), h.indexOf('Bent B2 —'));
  // parse summary: units, envelope notice, global + bent warnings (other bents' prefixed copies dropped)
  assert.ok(b1.indexOf('envelope-bounded (conservative)') > 0);
  assert.ok(b1.indexOf('No units row &lt;assumed&gt;') > 0 && b1.indexOf('B&lt;1&gt;: frame 999') < 0);
  assert.ok(b1.indexOf('frame 999 not found') > 0);
  // inputs / overrides / soil
  assert.ok(b1.indexOf('auto, from the column frame stations') > 0 && b1.indexOf('shaft long 22-#14') > 0 && b1.indexOf('api_sand') > 0);
  // slenderness per axis: axis 2 refined (120 >= 100), axis 3 neglect; magnification equations + table
  assert.deepStrictEqual(CS.slenderAxes(r.bents[0].lrfd.col.check_rows).map(a => [a.axis, a.klr, a.status]),
    [['2', 120, ST.REFINED], ['3', 20, ST.NEGLECT]]);
  assert.ok(b1.indexOf('NOT applied') < 0 && b1.indexOf('Eq. 4.5.3.2.2b-3') > 0 && b1.indexOf('Eq. 4.5.3.2.2b-4') > 0);
  assert.ok(b1.indexOf('Moment magnification (final cage, governing row per axis)') > 0);
  assert.ok(b1.indexOf('<td>1.150</td>') > 0 && b1.indexOf('βd = 0.072') > 0, 'magnification table');
  // M-phi table + Mo/Vo derivation + column shear breakdown
  assert.ok(b1.indexOf('governs Mo') > 0 && b1.indexOf('9.000e-5') > 0);
  assert.ok(b1.indexOf('Mo = λmo × Mp = 1.20 × 6333.3 = 7600.0 kip-ft') > 0, 'Mo line');
  assert.ok(b1.indexOf('Vo = Mo / H = 7600.0 / 20.00 = 380.0 kip  (fixed-free)') > 0, 'Vo line');
  assert.ok(b1.indexOf('Vc = 200.0 kip,  Vs = 466.7 kip,  φVn = 600.0 kip  vs  Vo = 380.0 kip  → OK') > 0);
  // final cage with sources
  assert.ok(b1.indexOf('Override') > 0 && b1.indexOf('LRFD+Seismic') > 0 && b1.indexOf('23.40') > 0);
  // NO SOLUTION bent: listed, sections present but not available
  const b2 = h.slice(h.indexOf('Bent B2 —'));
  assert.ok(b2.indexOf('Column seismic transverse: none') > 0 && b2.indexOf('No final cage') > 0);
  // fixed-fixed: Vo = 2*Mo/H
  r.bents[0].seismic.end_condition = 'fixed-fixed';
  assert.ok(CS.reportHtml(r, null, {}).indexOf('Vo = 2·Mo / H = 2 × 7600.0 / 20.00') > 0);
  // slenderness off: one line; no payload -> inputs not available
  r.settings.slenderness_on = false;
  const off = CS.reportHtml(r, null, {});
  assert.ok(off.indexOf('Slenderness screen off.') > 0 && off.indexOf('Inputs not available.') > 0);
  assert.ok(/Run Design first/.test(CS.reportHtml(null, null, {})));
});

test('report: seismic refs carry the unverified suffix; LRFD refs do not; user text escaped', () => {
  const r = reportFixture();
  const SUF = '(unverified — see OPEN_VERIFICATION_ITEMS E)';
  assert.strictEqual(CS.UNVERIFIED_SUFFIX, SUF);
  assert.strictEqual(CS.seismicRef('X §1'), 'X §1 ' + SUF);
  assert.strictEqual(CS.seismicRef(''), '—');
  assert.strictEqual(CS.checkRef(r.bents[0].final_checks[0]), r.bents[0].final_checks[0].ref + ' ' + SUF);
  assert.strictEqual(CS.checkRef(r.bents[0].final_checks[3]), '—');
  const h = CS.reportHtml(r, RPT_PAYLOAD, { project: '<script>alert(1)</script>' });
  // every occurrence of a ported ref string in the report is followed by the suffix
  const refs = Object.values(r.bents[0].seismic.refs).concat(r.bents[0].final_checks.map(c => c.ref).filter(Boolean));
  const ESUF = ' ' + CS.esc(SUF);
  refs.forEach(x => {
    const e = CS.esc(x);
    let i = h.indexOf(e), k = 0;
    while (i >= 0) {
      const followed = h.slice(i + e.length, i + e.length + ESUF.length) === ESUF;
      // a shorter ref inside a longer suffixed one (e.g. "§6.2.5.3" vs a longer text) is fine
      const inLonger = refs.some(y => y.length > x.length && y.indexOf(x) >= 0 && h.indexOf(CS.esc(y) + ESUF) >= 0);
      assert.ok(followed || inLonger, 'unsuffixed ref ' + x + ' @' + i);
      if (followed) k += 1;
      i = h.indexOf(e, i + 1);
    }
    assert.ok(k >= 1, 'ref not shown: ' + x);
  });
  assert.ok(h.split(CS.esc(SUF)).length - 1 >= 8);
  assert.ok(h.indexOf('<script') < 0 && h.indexOf('&lt;script&gt;alert(1)&lt;/script&gt;') > 0);
  assert.ok(h.indexOf('Vo=380 &lt;x&gt;') > 0 && h.indexOf('<x>') < 0);
  assert.ok(h.indexOf('B<1>') < 0);
});

test('governing rows: failing rows first, then D/C descending, null ratio worst (minor 7a)', () => {
  const rows = [
    { _case: 'a', ratio: 0.95, ok: true }, { _case: 'b', ratio: 0.4, ok: false },
    { _case: 'c', ratio: null, ok: true }, { _case: 'd', ratio: 1.2, ok: false },
    { _case: 'e', ratio: 0.2, ok: true }];
  assert.deepStrictEqual(CS.governingRows(rows).map(g => g.cells[1]), ['d', 'b', 'c', 'a', 'e']);
});

test('expected steel inputs (ruling F-1): payload, validation, hint, report echo', () => {
  assert.strictEqual(CS.EXPECTED_HINT, '(blank = A706 Gr60: 68/95/68)');
  assert.deepStrictEqual(CS.GR60_EXPECTED, { fye: 68, fue: 95, fyh: 68 });
  const s = sampleState();
  assert.deepStrictEqual(CS.validateState(s), []);
  s.bents[0].col.fy = 80;
  const e = CS.validateState(s);
  assert.strictEqual(e.length, 3, e.join('|'));
  assert.ok(e.every(x => /B1: column f(ye|ue|yh) must be entered for fy ≠ 60 ksi/.test(x)), e.join('|'));
  Object.assign(s.bents[0].col, { fye: 90, fue: 115, fyh: 68 });
  assert.deepStrictEqual(CS.validateState(s), []);
  const col = CS.buildPayload(s).bents[0].column;
  assert.deepStrictEqual([col.fye, col.fue, col.fyh], [90, 115, 68]);
  s.bents[0].shaft.fye = -1;
  assert.ok(/shaft fye must be > 0/.test(CS.validateState(s)[0]));
  assert.deepStrictEqual(CS.expectedErrors({ fy: 60, fye: '', fue: '', fyh: '' }), []);
  // report echo: the engine's values when present, else the payload / Gr60 defaults
  assert.strictEqual(CS.expectedStr({ fye: 68, fue: 95, fyh: 68, source: 'A706 Gr60 defaults' }, null),
    '68.0 / 95.0 / 68.0 ksi (A706 Gr60 defaults)');
  assert.strictEqual(CS.expectedStr(null, { fye: 90 }), '90.0 / Gr60 95 / Gr60 68 ksi');
  const r = reportFixture();
  r.bents[0].expected_steel = { column: { fye: 90, fue: 115, fyh: 68, source: 'entered' },
    shaft: { fye: 68, fue: 95, fyh: 68, source: 'A706 Gr60 defaults' } };
  const h = CS.reportHtml(r, RPT_PAYLOAD, {});
  assert.ok(h.indexOf('90.0 / 115.0 / 68.0 ksi (entered); 68.0 / 95.0 / 68.0 ksi (A706 Gr60 defaults)') > 0);
});

test('soil layer validation (minor 7d)', () => {
  const L = (o) => Object.assign({ thickness_ft: 10, gamma_pcf: 120, su_top_ksf: '', su_bot_ksf: '', eps50: '',
    phi_deg: '', k_pci: '', submerged: false }, o);
  assert.deepStrictEqual(CS.layerErrors(L({ py_model: 'welch_stiff_clay', su_top_ksf: 2 })), []);
  assert.deepStrictEqual(CS.layerErrors(L({ py_model: 'matlock_soft_clay' })), ['clay needs su top > 0']);
  assert.deepStrictEqual(CS.layerErrors(L({ py_model: 'matlock_soft_clay', su_top_ksf: 1, su_bot_ksf: 0 })),
    ['su bot must be > 0 (or blank = su top)']);
  assert.deepStrictEqual(CS.layerErrors(L({ py_model: 'api_sand', phi_deg: 34 })), ['sand needs k > 0']);
  assert.deepStrictEqual(CS.layerErrors(L({ py_model: 'api_sand' })), ['sand needs φ′ > 0', 'sand needs k > 0']);
  assert.deepStrictEqual(CS.layerErrors(L({ py_model: 'elastic_subgrade' })), ['elastic subgrade needs k > 0']);
  assert.deepStrictEqual(CS.layerErrors(L({ py_model: 'elastic_subgrade', k_pci: 5, gamma_pcf: 0 })),
    ['thickness and gamma must be > 0']);
  const s = sampleState();
  s.soils[0].layers[1].k_pci = '';
  const e = CS.validateState(s);
  assert.strictEqual(e.length, 1);
  assert.ok(/layer 2: sand needs k > 0/.test(e[0]), e[0]);
});

test('report: shaft row source line (ruling F-4), UNSTABLE status, stale message', () => {
  assert.ok(/\|V_base\|·L_eq/.test(CS.shaftSourceNote('cantilever strength')));
  assert.ok(/Mu = \|M_base\|, Vu = \|V_base\|/.test(CS.shaftSourceNote('interface strength')));
  assert.ok(/p-y soil model/.test(CS.shaftSourceNote('p-y strength')));
  assert.ok(/pasted shaft frames/.test(CS.shaftSourceNote('shaft frames')));
  const r = reportFixture();
  r.bents[0].status = CS.ST_UNSTABLE;
  r.bents[0].lrfd.shaft = { source: 'cantilever strength', check_rows: r.bents[0].lrfd.col.check_rows };
  const h = CS.reportHtml(r, RPT_PAYLOAD, {});
  assert.ok(h.indexOf('<span class="rpt-fail">UNSTABLE (Pu ≥ φK·Pe)</span>') > 0, 'header status');
  assert.ok(h.indexOf('<td class="rpt-fail">UNSTABLE (Pu ≥ φK·Pe)</td>') > 0, 'summary cell');
  assert.ok(h.indexOf('Shaft (cantilever strength)') > 0 && h.indexOf('taken down the equivalent cantilever') > 0);
  assert.ok(h.indexOf('least compression of the Extreme rows, else P_dead') > 0);
  assert.ok(/stale/.test(CS.STALE_MSG) && /re-run Design/.test(CS.STALE_MSG));
});

test('bars_terminated checkbox (2026-10-19): default false, payload, round-trip, label', () => {
  const s = sampleState();
  assert.strictEqual(s.bents[0].col.bars_terminated, false);
  assert.strictEqual(s.bents[0].shaft.bars_terminated, false);
  s.bents[0].col.bars_terminated = true;
  const p = CS.buildPayload(s);
  assert.strictEqual(p.bents[0].column.bars_terminated, true);
  assert.strictEqual(p.bents[0].shaft.bars_terminated, false);
  assert.strictEqual(p.bents[1].column.bars_terminated, false);
  const back = CS.normalizeState(JSON.parse(JSON.stringify(CS.serializeState(s))));
  assert.strictEqual(back.bents[0].col.bars_terminated, true);
  // an old saved state without the key -> false
  const old = CS.normalizeState({ bents: [{ name: 'X', col: { D: 60 } }] });
  assert.strictEqual(old.bents[0].col.bars_terminated, false);
  assert.strictEqual(old.bents[0].shaft.bars_terminated, false);
  assert.strictEqual(CS.BARS_TERMINATED_LABEL,
    'Longitudinal bars terminated/discontinuous within the member (apply Eq. 5.7.3.5-1)');
  assert.strictEqual(CS.LONG_NA, 'n/a: bars continuous (§5.7.3.5)');
});

test('K per axis (2026-10-19): defaults, analysis override, legacy state, payload fields', () => {
  assert.deepStrictEqual(CS.K_SOURCES, ['default', 'analysis']);
  assert.deepStrictEqual(CS.END_CONDITIONS, ['fixed-free', 'fixed-fixed']);
  let k = CS.kInfo({ braced: true, K_source: 'default', end_condition: 'fixed-free', K: '' });
  assert.strictEqual(k.K, 1.0); assert.strictEqual(k.warning, '');
  k = CS.kInfo({ braced: false, K_source: 'default', end_condition: 'fixed-free', K: '' });
  // ruling M1: Table C4.6.2.5-1 design values (e) 2.1 / (d) 1.2
  assert.strictEqual(k.K, 2.1);
  assert.strictEqual(k.label, 'K = 2.1 (Table C4.6.2.5-1 case (e) design value, fixed-free)');
  assert.strictEqual(k.warning, CS.DEFAULT_K_WARNING);
  assert.ok(!/Euler/.test(CS.DEFAULT_K_WARNING));
  assert.strictEqual(k.K_braced, 1.0); assert.strictEqual(k.K_unbraced, 2.1);
  k = CS.kInfo({ braced: false, K_source: 'default', end_condition: 'fixed-fixed', K: 0.5 });
  assert.strictEqual(k.K, 1.2); assert.ok(/case \(d\) design value, fixed-fixed/.test(k.label));
  k = CS.kInfo({ braced: false, K_source: 'analysis', end_condition: 'fixed-free', K: 1.6 });
  assert.strictEqual(k.K, 1.6); assert.strictEqual(k.warning, '');
  k = CS.kInfo({ braced: false, K_source: 'analysis', K: 0.8 });
  assert.strictEqual(k.K, 0.8); assert.strictEqual(k.warning, CS.UNBRACED_K_LT1_WARNING);
  assert.strictEqual(CS.kInfo({ braced: true, K_source: 'analysis', K: 0.8 }).warning, CS.BRACED_K_LT1_NOTE);
  assert.ok(CS.kInfo({ braced: false, K_source: 'analysis', K: -1 }).error);
  // legacy saved state: numeric K, no K_source -> analysis; blank K -> default
  const st = CS.normalizeState({ bents: [{ name: 'L', slender: { '2': { braced: false, K: 2.1, lu_ft: '' },
    '3': { braced: true, K: '', lu_ft: '' } } }] });
  assert.strictEqual(st.bents[0].slender['2'].K_source, 'analysis');
  assert.strictEqual(st.bents[0].slender['3'].K_source, 'default');
  assert.strictEqual(st.bents[0].slender['2'].end_condition, 'fixed-free');
  const pl = CS.buildPayload(Object.assign(sampleState(), { bents: st.bents.map(b => Object.assign(b, { col_frames: '101', L_eq_ft: 10 })) }));
  assert.deepStrictEqual(pl.bents[0].slender['2'], { braced: false, K_source: 'analysis', end_condition: 'fixed-free', K: 2.1, lu: null,
    K_braced_source: 'default', K_braced: null });
  assert.deepStrictEqual(pl.bents[0].slender['3'], { braced: true, K_source: 'default', end_condition: 'fixed-free', K: null, lu: null,
    K_braced_source: 'default', K_braced: null });
  // a garbage source / end condition normalises to the defaults
  const g = CS.normalizeState({ bents: [{ slender: { '2': { K_source: 'x', end_condition: 'y' } } }] });
  assert.strictEqual(g.bents[0].slender['2'].K_source, 'default');
  assert.strictEqual(g.bents[0].slender['2'].end_condition, 'fixed-free');
  // the payload carries the chosen end condition
  const s2 = sampleState();
  s2.bents[0].slender['3'].end_condition = 'fixed-fixed';
  assert.strictEqual(CS.buildPayload(s2).bents[0].slender['3'].end_condition, 'fixed-fixed');
});

test('report: per-axis K table and the per-member longitudinal V+T note (2026-10-19)', () => {
  const r = reportFixture();
  r.bents[0].slender_K = {
    '2': { K: 2.1, source: 'default', end_condition: 'fixed-free', braced: false,
      label: 'K = 2.1 (Table C4.6.2.5-1 case (e) design value, fixed-free)' },
    '3': { K: 0.8, source: 'analysis', end_condition: 'fixed-free', braced: false, label: 'K = 0.8 (buckling analysis)' } };
  r.bents[0].lrfd.col.long_check = { bars_terminated: false, enforced: 'none', n_rows: 2, n_torsion_rows: 0,
    note: 'not enforced, n/a: bars continuous (§5.7.3.5). §5.7.3.5: "Eq. 5.7.3.5-1 shall be evaluated where ... discontinuous."' };
  const h = CS.reportHtml(r, RPT_PAYLOAD, {});
  const sec4 = h.slice(h.indexOf('data-sec="slender"'), h.indexOf('data-sec="mphi"'));
  assert.ok(sec4.indexOf('<th>K used</th>') > 0 && sec4.indexOf('<th>K source</th>') > 0 && sec4.indexOf('<th>End condition</th>') > 0, sec4);
  assert.ok(sec4.indexOf('<td>Table C4.6.2.5-1 default</td>') > 0 && sec4.indexOf('<td>buckling analysis</td>') > 0);
  assert.ok(sec4.indexOf('K = 2.1 (Table C4.6.2.5-1 case (e) design value, fixed-free)') > 0);
  assert.ok(sec4.indexOf('<td>120.0</td>') > 0);
  const rows = CS.slenderKRows(r.bents[0], null);
  assert.deepStrictEqual(rows.map(a => [a.axis, a.K, a.source, a.status]),
    [['2', '2.1', 'Table C4.6.2.5-1 default', ST.REFINED], ['3', '0.8', 'buckling analysis', ST.NEGLECT]]);
  // braced default
  r.bents[0].slender_K['3'] = { K: 1.0, source: 'default', end_condition: 'fixed-free', braced: true, label: 'K = 1.0 (braced, C5.6.4.3)' };
  assert.strictEqual(CS.slenderKRows(r.bents[0], null)[1].source, 'braced default (C5.6.4.3)');
  // no engine K: fall back to the payload (legacy K -> analysis)
  delete r.bents[0].slender_K;
  const pk = CS.slenderKRows(r.bents[0], { slender: { '2': { braced: false, K: 2.1 }, '3': { braced: false, K_source: 'default' } } });
  assert.deepStrictEqual(pk.map(a => [a.K, a.source]), [['2.1', 'buckling analysis'], ['2.1', 'Table C4.6.2.5-1 default']]);
  // longitudinal V+T note per member in section 3, inputs echo the flags
  const sec3 = h.slice(h.indexOf('data-sec="lrfd"'), h.indexOf('data-sec="slender"'));
  assert.ok(sec3.indexOf('Longitudinal reinforcement for V+T (Eq. 5.7.3.5-1 / 5.7.3.6.3-1): not enforced, n/a: bars continuous (§5.7.3.5)') > 0, sec3);
  assert.ok(h.indexOf('Longitudinal bars terminated/discontinuous (Eq. 5.7.3.5-1)') > 0);
  assert.ok(/column no, shaft no/.test(h));
});

test('braced K / sway group (ruling M2 / M9): defaults, legacy migration, payload, round-trip', () => {
  let k = CS.kbInfo({});
  assert.strictEqual(k.K, 1.0); assert.strictEqual(k.source, 'default');
  k = CS.kbInfo({ K_braced_source: 'analysis', K_braced: 0.85 });
  assert.strictEqual(k.K, 0.85); assert.strictEqual(k.warning, CS.BRACED_K_LT1_NOTE);
  assert.ok(CS.kbInfo({ K_braced_source: 'analysis', K_braced: '' }).error);
  // braced axis: the screen K is the braced K
  k = CS.kInfo({ braced: true, K_source: 'analysis', K: 2.0, K_braced_source: 'analysis', K_braced: 0.9 });
  assert.strictEqual(k.K, 0.9); assert.strictEqual(k.K_braced, 0.9);
  // unbraced axis: both K values reported, the hint names both
  const t = CS.kInfoText({ braced: false, K_source: 'default', end_condition: 'fixed-fixed' });
  assert.ok(/unbraced \(δs\) K = 1.2/.test(t) && /braced \(δb\) K = 1.0/.test(t), t);
  // legacy state (no K_braced): unbraced -> default 1.0; braced with an analysis K -> kept as the braced K
  const st = CS.normalizeState({ bents: [{ slender: { '2': { braced: false, K: 2.1 }, '3': { braced: true, K: 0.8 } } }] });
  assert.strictEqual(st.bents[0].slender['2'].K_braced_source, 'default');
  assert.strictEqual(st.bents[0].slender['3'].K_braced_source, 'analysis');
  assert.strictEqual(st.bents[0].slender['3'].K_braced, 0.8);
  assert.strictEqual(CS.kInfo(st.bents[0].slender['3']).K, 0.8);
  assert.strictEqual(st.bents[0].sway_group, '');
  // payload: braced K and the sway group
  const s = sampleState();
  s.bents[0].slender['2'].K_braced_source = 'analysis';
  s.bents[0].slender['2'].K_braced = 0.9;
  s.bents[0].sway_group = ' G1 ';
  s.bents[1].sway_group = 'G1';
  const p = CS.buildPayload(s);
  assert.strictEqual(p.bents[0].slender['2'].K_braced_source, 'analysis');
  assert.strictEqual(p.bents[0].slender['2'].K_braced, 0.9);
  assert.strictEqual(p.bents[0].sway_group, 'G1');
  assert.strictEqual(p.bents[1].sway_group, 'G1');
  const back = CS.normalizeState(JSON.parse(JSON.stringify(CS.serializeState(s))));
  assert.strictEqual(back.bents[0].slender['2'].K_braced, 0.9);
  assert.strictEqual(back.bents[0].sway_group, ' G1 ');
  assert.deepStrictEqual(CS.TABLE_K, { 'fixed-free': 2.1, 'fixed-fixed': 1.2 });
});

test('magnification rows (ruling M12): per axis table cells and the EI / beta_d note', () => {
  const b = { magnification: { beta_d: 0.25, beta_d_source: 'user override', phi_K: 0.75, Ec: 3986.5, Es: 29000,
    Ig: 636172, Is: 10292, EI1: 7.5e8, EI2: 9.4e8, EI: 9.4e8,
    sway: { group: 'G', n_members: 2, Pe_others: { '2': 1000, '3': 1000 }, pass: 2 },
    axes: {
      '2': { braced: false, K_braced: 1.0, K_unbraced: 2.1, Pe_b: 72000, Pe_s: 16000, sPe_s: 32000, Cm: 1.0, db: 1.03,
        ds: 1.15, delta: 1.15, row: 1, case: 'Str-I', Pu: 1600, sPu: 3200, unstable: false },
      '3': { braced: true, K_braced: 1.0, K_unbraced: null, Pe_b: 72000, Pe_s: null, sPe_s: null, Cm: 0.6, db: null,
        ds: 1.0, delta: null, row: 2, case: 'Str-II', Pu: 9000, sPu: 9000, unstable: true } } } };
  const m = CS.magRows(b);
  assert.deepStrictEqual([m[0].K_unbraced, m[0].Pe_s, m[0].delta, m[0].Pu, m[0].row],
    ['2.10', '16000 (Σ 32000)', '1.150', '1600 (Σ 3200)', '1 (Str-I)']);
  assert.deepStrictEqual([m[1].K_unbraced, m[1].Pe_s, m[1].db, m[1].delta],
    ['braced', '—', 'unstable', CS.UNSTABLE_REASON]);
  const note = CS.magNote(b);
  assert.ok(/βd = 0.250 \(user override\)/.test(note) && /Eq. 5.6.4.3-1/.test(note) && /Sway group G \(2 bents, two-pass\)/.test(note), note);
  assert.deepStrictEqual(CS.magRows({}), []);
  // minor 6: a neglected axis whose delta would be unstable shows the note, not blank cells
  b.magnification.axes['2'] = { braced: false, K_braced: 1.0, K_unbraced: 1.0, Pe_b: 1, Pe_s: 1, sPe_s: 1, Cm: 1.0, db: 1.0,
    ds: null, delta: 1.0, row: 1, case: 'C', Pu: 10, sPu: 10, unstable: false,
    neglect_note: 'neglected per §5.6.4.3 screen (δ would be unstable)' };
  const n = CS.magRows(b)[0];
  assert.deepStrictEqual([n.ds, n.delta], ['n/a', '1.000 (neglected per §5.6.4.3 screen (δ would be unstable))']);
  // minor 4 documented in the report equations
  assert.ok(CS.MAG_EQ.some(x => /component maxima/.test(x)));
});

test('sway check-only source label (ruling MF-2): not shown as an override', () => {
  assert.strictEqual(CS.SRC_CHECK_ONLY, 'LRFD (sway check-only)');
  const res = { settings: { slenderness_on: true }, bents: [{ name: 'B', status: 'OK', lrfd: { col: {} }, seismic: null,
    final: { col_long: { bar: 11, n: 15, bundle: 1 }, col_trans: { bar: 5, s: 6, ties: 0 },
      shaft_long: { bar: 14, n: 22, bundle: 1 }, shaft_trans: { bar: 5, s: 6, ties: 0 } },
    final_source: { col_long: CS.SRC_CHECK_ONLY, col_trans: CS.SRC_CHECK_ONLY, shaft_long: 'LRFD', shaft_trans: 'LRFD' },
    final_checks: [] }] };
  const r = CS.resultRows(res)[0];
  assert.strictEqual(r.override, '—');
  assert.ok(r.final.indexOf('(LRFD (sway check-only))') > 0, r.final);
  const h = CS.reportHtml(Object.assign(reportFixture(), {}), RPT_PAYLOAD, {});
  assert.ok(h.indexOf('LRFD (sway check-only) (the LRFD column cage re-checked') > 0);
});

const di = process.argv.indexOf('--dump');
if (di > 0) {
  fs.writeFileSync(process.argv[di + 1], JSON.stringify(CS.buildPayload(sampleState())));
  console.log('payload written to ' + process.argv[di + 1]);
}
console.log('ALL ' + n + ' TESTS PASSED');
