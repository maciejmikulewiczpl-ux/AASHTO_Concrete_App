/* Column on Shaft tab (Task 10).
 *
 * Drives pywebview.api.parse_csi / run_colshaft (api.py).  Payload / result
 * schema: colshaft_engine.run_colshaft.  Everything here lives inside
 * #tab-colshaft and uses DOM ids prefixed "cs-"; the only globals are
 * window.ColShaft = {getState, setState} (project persistence hooks in
 * index.html) and an optional call to the app's markDirty().
 *
 * Units shown in this tab: kip, in, ft, ksi, kip-ft (engine moments are
 * kip-in and are divided by 12 for display only).  The app's global display
 * unit toggle does not apply here.
 *
 * The pure logic (state defaults / (de)serialisation, payload building,
 * validation, result formatting, status colours, SVG plots) is exported for
 * Node when `module` exists (tests/js/test_colshaft_js.js).
 */
(function () {
  'use strict';

  // ─── Constants ──────────────────────────────────────────────────────
  var CODES = [
    { key: 'SDC 2.1', label: 'Caltrans SDC 2.1' },
    { key: 'AASHTO SGS 3rd Ed.', label: 'AASHTO SGS 3rd Ed.' }
  ];
  var CATEGORIES = ['Strength', 'Extreme', 'Dead', 'Ignore'];
  var PY_MODELS = ['matlock_soft_clay', 'welch_stiff_clay', 'api_sand', 'elastic_subgrade'];
  var UNIT_OPTIONS = {
    force: ['kip', 'kN', 'lb'],
    moment: ['kip-ft', 'kip-in', 'kN-m'],
    length: ['ft', 'in', 'm']
  };
  // colshaft_lrfd.DEFAULT_PARAMS (Task 6 / 8 reports)
  var DEFAULT_PARAMS = {
    minBar: 8, maxBar: 14, minSpacing: 1.5,
    stirMin: 5, stirMax: 8, sMax: 6.0, sMin: 3.0, sStep: 0.25, maxLegs: 2
  };
  var PARAM_LABELS = [
    ['minBar', 'Longitudinal bar, min #', ''],
    ['maxBar', 'Longitudinal bar, max #', ''],
    ['minSpacing', 'Longitudinal clear spacing, min', 'in'],
    ['stirMin', 'Hoop/spiral bar, min #', ''],
    ['stirMax', 'Hoop/spiral bar, max #', ''],
    ['sMin', 'Hoop pitch, min', 'in'],
    ['sMax', 'Hoop pitch, max', 'in'],
    ['sStep', 'Hoop pitch step', 'in'],
    ['maxLegs', 'Cross-tie legs, max', '']
  ];
  var STATUS_COLORS = {
    'OK': '#27ae60',
    'NG': '#c0392b',
    'NO SOLUTION': '#7b1010',
    'REFINED ANALYSIS REQUIRED': '#e67e22'
  };
  // Ruling 8-9 precedence: NO SOLUTION > REFINED ANALYSIS REQUIRED > NG > OK
  var STATUS_RANK = { 'OK': 0, 'NG': 1, 'REFINED ANALYSIS REQUIRED': 2, 'NO SOLUTION': 3 };
  var OV_PARTS = ['col_long', 'col_trans', 'shaft_long', 'shaft_trans'];
  // colshaft_slender.ST_NEGLECT / ST_PENDING / ST_REFINED and _RANK (pinned equal by
  // tests/test_colshaft_ui_static.py)
  var SLENDER_STATUS = {
    NEGLECT: 'neglect',
    PENDING: 'magnification pending verification (S6)',
    REFINED: 'refined analysis required'
  };
  var SLENDER_RANK = {};
  SLENDER_RANK[SLENDER_STATUS.NEGLECT] = 0;
  SLENDER_RANK[SLENDER_STATUS.PENDING] = 1;
  SLENDER_RANK[SLENDER_STATUS.REFINED] = 2;
  // calc_engine.BARS sizes (pinned equal by the pytest)
  var BAR_SIZES = [2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 14, 18];

  // ─── Small helpers ─────────────────────────────────────────────────
  function isObj(o) { return o !== null && typeof o === 'object' && !Array.isArray(o); }
  function clone(o) { return JSON.parse(JSON.stringify(o)); }
  function isNum(v) { return typeof v === 'number' && isFinite(v); }
  function num(v) {
    // '' / null / undefined / non-numeric -> null; numbers and numeric strings -> number
    if (v === '' || v === null || v === undefined) return null;
    var x = typeof v === 'number' ? v : Number(String(v).trim());
    return isFinite(x) ? x : null;
  }
  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }
  function fmt(x, d) {
    if (!isNum(x)) return '—';
    return x.toFixed(d === undefined ? 1 : d);
  }
  function kft(x, d) { return isNum(x) ? fmt(x / 12.0, d === undefined ? 0 : d) : '—'; }
  function splitFrames(s) {
    if (Array.isArray(s)) return s.map(String).map(function (x) { return x.trim(); }).filter(Boolean);
    return String(s || '').split(/[,;\s]+/).map(function (x) { return x.trim(); }).filter(Boolean);
  }
  function setPath(obj, path, value) {
    var parts = String(path).split('.');
    var o = obj;
    for (var i = 0; i < parts.length - 1; i++) {
      var k = parts[i];
      if (o[k] === undefined || o[k] === null) o[k] = /^\d+$/.test(parts[i + 1]) ? [] : {};
      o = o[k];
    }
    o[parts[parts.length - 1]] = value;
    return obj;
  }
  function getPath(obj, path) {
    var parts = String(path).split('.');
    var o = obj;
    for (var i = 0; i < parts.length; i++) {
      if (o === null || o === undefined) return undefined;
      o = o[parts[i]];
    }
    return o;
  }
  // deep merge `src` onto a copy of `def` (only keys of def for objects; arrays replaced)
  function mergeDefaults(def, src) {
    if (!isObj(def)) return src === undefined ? def : src;
    var out = clone(def);
    if (!isObj(src)) return out;
    Object.keys(src).forEach(function (k) {
      if (isObj(def[k])) out[k] = mergeDefaults(def[k], src[k]);
      else if (src[k] !== undefined) out[k] = src[k];
    });
    return out;
  }

  // ─── State ─────────────────────────────────────────────────────────
  function defaultLayer() {
    return { thickness_ft: 20, py_model: 'welch_stiff_clay', gamma_pcf: 120, su_top_ksf: '',
      su_bot_ksf: '', eps50: '', phi_deg: '', k_pci: '', submerged: false };
  }
  function defaultSoil(i) {
    return { name: 'Profile ' + ((i || 0) + 1), J: 0.5, cyclic: true, bound_upper: 2.0,
      bound_lower: 0.5, layers: [defaultLayer()] };
  }
  function emptyOverride() {
    return {
      col_long: { bar: '', n: '', bundle: '' }, col_trans: { bar: '', s: '', ties: '' },
      shaft_long: { bar: '', n: '', bundle: '' }, shaft_trans: { bar: '', s: '', ties: '' }
    };
  }
  function defaultBent(i) {
    return {
      name: 'Bent ' + ((i || 0) + 1),
      col_frames: '', shaft_frames: '',
      col: { D: 48, fc: 4, fy: 60, cover: 2, trans_type: 'hoop', hoop_closure: 'lap' },
      shaft: { D: 72, fc: 4, fy: 60, cover: 3, trans_type: 'hoop' },
      end_long: 'fixed-free', end_trans: 'fixed-free',
      H_ft: '', base_end: 'auto', lambda_mo: 1.2, mu_d: '',
      shaft_basis: 'auto', L_eq_ft: '', soil: '', L_embed_ft: '', P_dead: '',
      slender: {
        '2': { braced: false, K: '', lu_ft: '' },
        '3': { braced: false, K: '', lu_ft: '' },
        beta_d: '', gamma_p: ''
      },
      override: emptyOverride()
    };
  }
  function defaultState() {
    return {
      v: 1,
      paste: '',
      units: { force: 'kip', moment: 'kip-ft', length: 'ft' },
      parse: null,
      categories: {},
      code: 'SDC 2.1',
      settings: { envelope_mode: 'station', slenderness_on: false },
      params: clone(DEFAULT_PARAMS),
      bents: [defaultBent(0)],
      soils: [],
      report: { project: '' }
    };
  }
  function normalizeState(obj) {
    var d = defaultState();
    if (!isObj(obj)) return d;
    var s = mergeDefaults(d, obj);
    s.v = 1;
    s.paste = typeof obj.paste === 'string' ? obj.paste : '';
    s.parse = isObj(obj.parse) ? clone(obj.parse) : null;
    if (s.parse) {
      ['frames', 'cases', 'warnings'].forEach(function (k) { if (!Array.isArray(s.parse[k])) s.parse[k] = []; });
      s.parse.frames = s.parse.frames.filter(isObj);
      s.parse.cases = s.parse.cases.filter(isObj);
      s.parse.warnings = s.parse.warnings.map(String);
    }
    s.categories = isObj(obj.categories) ? clone(obj.categories) : {};
    if (!CODES.some(function (c) { return c.key === s.code; })) s.code = d.code;
    if (['station', 'member'].indexOf(s.settings.envelope_mode) < 0) s.settings.envelope_mode = 'station';
    s.settings.slenderness_on = !!s.settings.slenderness_on;
    s.bents = Array.isArray(obj.bents) ? obj.bents.map(function (b, i) {
      return mergeDefaults(defaultBent(i), b);
    }) : d.bents;
    s.soils = Array.isArray(obj.soils) ? obj.soils.map(function (p, i) {
      var q = mergeDefaults(defaultSoil(i), p);
      q.layers = Array.isArray(p && p.layers) ? p.layers.map(function (l) {
        return mergeDefaults(defaultLayer(), l);
      }) : [];
      return q;
    }) : [];
    return s;
  }
  function serializeState(state) { return clone(state); }

  // ─── Derived values ────────────────────────────────────────────────
  function shaftBasis(b) {
    if (b.shaft_basis && b.shaft_basis !== 'auto') return b.shaft_basis;
    return b.soil ? 'soil' : 'cantilever';
  }
  function findSoil(state, name) {
    for (var i = 0; i < state.soils.length; i++) if (state.soils[i].name === name) return state.soils[i];
    return null;
  }
  // auto column height (ft) from the parse summary: sum of the frames' station spans
  function autoHeightFt(state, b) {
    if (!state.parse || !Array.isArray(state.parse.frames)) return null;
    var fr = splitFrames(b.col_frames);
    if (!fr.length) return null;
    var tot = 0;
    for (var i = 0; i < fr.length; i++) {
      var f = state.parse.frames.filter(function (x) { return String(x.name) === fr[i]; })[0];
      if (!f || !isNum(f.height_in)) return null;
      tot += f.height_in;
    }
    return tot / 12.0;
  }

  // ─── Validation (run before Design) ────────────────────────────────
  function overridePart(part, kind) {
    // -> {value|null, error|null}
    if (!part) return { value: null, error: null };
    var bar = num(part.bar);
    var isInt = function (x) { return Math.floor(x) === x; };
    var barErr = bar !== null && BAR_SIZES.indexOf(bar) < 0 ? 'bar must be one of #' + BAR_SIZES.join(', #') : null;
    if (kind === 'long') {
      var n = num(part.n), bun = num(part.bundle);
      if (bar === null && n === null && bun === null) return { value: null, error: null };
      if (bar === null || n === null) return { value: null, error: 'bar and n are both required' };
      if (barErr) return { value: null, error: barErr };
      if (!isInt(n) || n < 6) return { value: null, error: 'n must be a whole number >= 6' };
      if (bun !== null && (!isInt(bun) || bun < 1 || bun > 3)) return { value: null, error: 'bundle must be 1, 2 or 3' };
      return { value: { bar: bar, n: n, bundle: bun === null ? 1 : bun }, error: null };
    }
    var s = num(part.s), ties = num(part.ties);
    if (bar === null && s === null && ties === null) return { value: null, error: null };
    if (bar === null || s === null) return { value: null, error: 'bar and s are both required' };
    if (barErr) return { value: null, error: barErr };
    if (!(s > 0)) return { value: null, error: 's must be > 0' };
    if (ties !== null && (!isInt(ties) || ties < 0)) return { value: null, error: 'ties must be a whole number >= 0' };
    return { value: { bar: bar, s: s, ties: ties === null ? 0 : ties }, error: null };
  }
  function overrideErrors(b) {
    var out = [];
    OV_PARTS.forEach(function (part) {
      var r = overridePart(b.override && b.override[part], /long/.test(part) ? 'long' : 'trans');
      if (r.error) out.push(part.replace('_', ' ') + ': ' + r.error);
    });
    return out;
  }
  function validateState(state) {
    var errs = [];
    if (!String(state.paste || '').trim()) errs.push('Paste the CSiBridge "Element Forces - Frames" table first.');
    if (!state.bents.length) errs.push('Add at least one bent.');
    state.bents.forEach(function (b, i) {
      var who = 'Bent ' + (b.name || '#' + (i + 1));
      if (!String(b.name || '').trim()) errs.push('Bent #' + (i + 1) + ': enter a name.');
      if (!splitFrames(b.col_frames).length) errs.push(who + ': enter the column frame(s).');
      [['col', 'column'], ['shaft', 'shaft']].forEach(function (m) {
        ['D', 'fc', 'fy', 'cover'].forEach(function (k) {
          var x = num(b[m[0]][k]);
          if (x === null || !(x > 0)) errs.push(who + ': ' + m[1] + ' ' + k + ' must be > 0.');
        });
      });
      var basis = shaftBasis(b);
      var Leq = num(b.L_eq_ft);
      if (basis === 'cantilever' && (Leq === null || Leq < 0)) {
        errs.push(who + ': enter the pile equivalent cantilever length L_eq (ft); it is required ' +
          'when there is no soil profile.');
      }
      if (basis === 'soil') {
        var p = b.soil ? findSoil(state, b.soil) : null;
        if (!b.soil) errs.push(who + ': shaft basis "soil" needs a soil profile.');
        else if (!p) errs.push(who + ': soil profile "' + b.soil + '" does not exist.');
        else {
          if (!p.layers.length) errs.push(who + ': soil profile "' + p.name + '" has no strata.');
          p.layers.forEach(function (l, j) {
            if (!(num(l.thickness_ft) > 0) || !(num(l.gamma_pcf) > 0))
              errs.push('Soil profile "' + p.name + '" layer ' + (j + 1) + ': thickness and gamma must be > 0.');
          });
          if (!(num(b.L_embed_ft) > 0)) errs.push(who + ': enter the shaft embedded length (ft) for the soil basis.');
        }
      }
      if (num(b.H_ft) !== null && !(num(b.H_ft) > 0)) errs.push(who + ': H must be > 0 (or blank for auto).');
      if (state.settings.slenderness_on) {
        ['2', '3'].forEach(function (ax) {
          var a = b.slender[ax], K = num(a.K);
          if (K === null || !(K > 0)) errs.push(who + ': slenderness axis ' + ax + ': enter K.');
          else if (!a.braced && K < 1.0) errs.push(who + ': slenderness axis ' + ax + ': unbraced K must be >= 1.0.');
        });
      }
      overrideErrors(b).forEach(function (e) { errs.push(who + ': override ' + e + '.'); });
    });
    return errs;
  }

  // ─── Payload (run_colshaft schema, colshaft_engine docstring / Task 8 report) ──
  function memberPayload(m, isCol) {
    var out = { D: num(m.D), fc: num(m.fc), fy: num(m.fy), cover: num(m.cover),
      trans_type: m.trans_type === 'spiral' ? 'spiral' : 'hoop' };
    if (isCol && out.trans_type === 'hoop') out.hoop_closure = m.hoop_closure || 'lap';
    return out;
  }
  function soilPayload(p) {
    var layers = p.layers.map(function (l) {
      var o = { thickness_ft: num(l.thickness_ft), py_model: l.py_model, gamma_pcf: num(l.gamma_pcf) };
      ['su_top_ksf', 'su_bot_ksf', 'eps50', 'phi_deg', 'k_pci'].forEach(function (k) {
        var x = num(l[k]);
        if (x !== null) o[k] = x;
      });
      o.submerged = !!l.submerged;
      return o;
    });
    return { layers: layers, J: num(p.J) === null ? 0.5 : num(p.J), cyclic: !!p.cyclic };
  }
  function bentPayload(b, state) {
    var p = {
      name: String(b.name || ''),
      col_frames: splitFrames(b.col_frames),
      shaft_frames: splitFrames(b.shaft_frames),
      column: memberPayload(b.col, true),
      shaft: memberPayload(b.shaft, false),
      end_condition_long: b.end_long === 'fixed-fixed' ? 'fixed-fixed' : 'fixed-free',
      end_condition_trans: b.end_trans === 'fixed-fixed' ? 'fixed-fixed' : 'fixed-free',
      base_end: ['min', 'max'].indexOf(b.base_end) >= 0 ? b.base_end : 'auto',
      H_in: num(b.H_ft) === null ? null : num(b.H_ft) * 12.0
    };
    if (num(b.lambda_mo) !== null) p.lambda_mo = num(b.lambda_mo);
    if (num(b.mu_d) !== null) p.mu_d = num(b.mu_d);
    if (b.shaft_basis && b.shaft_basis !== 'auto') p.shaft_basis = b.shaft_basis;
    if (num(b.L_eq_ft) !== null) p.L_eq_in = num(b.L_eq_ft) * 12.0;
    var soil = b.soil ? findSoil(state, b.soil) : null;
    if (soil) {
      p.soil = soilPayload(soil);
      p.soil_bounds = [num(soil.bound_upper) === null ? 2.0 : num(soil.bound_upper),
        num(soil.bound_lower) === null ? 0.5 : num(soil.bound_lower)];
    }
    if (num(b.L_embed_ft) !== null) p.L_embed_in = num(b.L_embed_ft) * 12.0;
    if (num(b.P_dead) !== null) p.P_dead = num(b.P_dead);
    var sl = {};
    ['2', '3'].forEach(function (ax) {
      var a = b.slender[ax];
      sl[ax] = { braced: !!a.braced, K: num(a.K), lu: num(a.lu_ft) === null ? null : num(a.lu_ft) * 12.0 };
    });
    sl.beta_d = num(b.slender.beta_d);
    sl.gamma_p = num(b.slender.gamma_p);
    p.slender = sl;
    var ov = {};
    OV_PARTS.forEach(function (part) {
      var r = overridePart(b.override[part], /long/.test(part) ? 'long' : 'trans');
      if (r.value) ov[part] = r.value;
    });
    if (Object.keys(ov).length) p.override = ov;
    return p;
  }
  function buildPayload(state) {
    var params = {};
    Object.keys(DEFAULT_PARAMS).forEach(function (k) {
      var x = num(state.params[k]);
      params[k] = x === null ? DEFAULT_PARAMS[k] : x;
    });
    var cats = {};
    Object.keys(state.categories || {}).forEach(function (c) {
      if (CATEGORIES.indexOf(state.categories[c]) >= 0) cats[c] = state.categories[c];
    });
    return {
      paste: String(state.paste || ''),
      units: { force: state.units.force, moment: state.units.moment, length: state.units.length },
      categories: cats,
      code: state.code,
      params: params,
      settings: { envelope_mode: state.settings.envelope_mode, slenderness_on: !!state.settings.slenderness_on },
      bents: state.bents.map(function (b) { return bentPayload(b, state); })
    };
  }

  // after a parse: categories for the parsed cases (keep the user's choice when the case remains)
  function mergeCategories(old, cases) {
    var out = {};
    (cases || []).forEach(function (c) {
      var prev = old && old[c.name];
      out[c.name] = CATEGORIES.indexOf(prev) >= 0 ? prev : (c.default_category || 'Strength');
    });
    return out;
  }

  // ─── Result formatting ─────────────────────────────────────────────
  function statusColor(status) { return STATUS_COLORS[status] || '#7f8c8d'; }
  function worstStatus(list) {
    var w = 'OK';
    (list || []).forEach(function (s) { if ((STATUS_RANK[s] || 0) > STATUS_RANK[w]) w = s; });
    return w;
  }
  function longStr(c) {
    if (!c || !c.bar) return '—';
    return c.n + '-#' + c.bar + (c.bundle > 1 ? ' (bundles of ' + c.bundle + ')' : '');
  }
  function transStr(t) {
    if (!t || !t.bar) return '—';
    return '#' + t.bar + ' @ ' + fmt(t.s, 2) + ' in' + (t.ties ? ' + ' + t.ties + ' ties' : '');
  }
  function profileMax(profile, idx) {
    // -> {value, z} of the largest |profile[i][idx]| ; z in inches
    var best = null;
    (profile || []).forEach(function (p) {
      if (isNum(p[idx]) && (best === null || Math.abs(p[idx]) > Math.abs(best.value))) best = { value: p[idx], z: p[0] };
    });
    return best;
  }
  function findCheck(b, name) {
    return (b.final_checks || []).filter(function (c) { return c.name === name; })[0] || null;
  }
  function slenderSummary(b, settings) {
    if (!settings || !settings.slenderness_on) return 'off';
    var rows = (b.lrfd && b.lrfd.col && b.lrfd.col.check_rows) || [];
    var klr = null, st = null;
    var rk = function (x) { return SLENDER_RANK.hasOwnProperty(x) ? SLENDER_RANK[x] : -1; };
    rows.forEach(function (r) {
      [r._klr2, r._klr3].forEach(function (k) { if (isNum(k) && (klr === null || k > klr)) klr = k; });
      var s = r._slender_status;
      if (s && (st === null || rk(s) > rk(st))) st = s;
    });
    return (klr === null ? '—' : fmt(klr, 1)) + (st ? ' (' + st + ')' : '');
  }
  function resultRows(result) {
    if (!result || !Array.isArray(result.bents)) return [];
    return result.bents.map(function (b) {
      var S = b.seismic, L = b.lrfd || {}, F = b.final, src = b.final_source || {};
      var col = L.col || {};
      var req = S && S.required_transverse;
      var ovParts = Object.keys(src).filter(function (k) { return src[k] === 'Override'; });
      var mMax = S ? profileMax(S.shaft_profile, 1) : null;
      var vChk = findCheck(b, 'Shaft shear (capacity protection)');
      return {
        name: b.name,
        status: b.status,
        color: statusColor(b.status),
        lrfd_col: longStr(col.long) + ' / ' + transStr(col.trans),
        seismic_col: req ? (req.ok ? transStr(req) : 'none in range') : '—',
        override: ovParts.length ? ovParts.map(function (k) { return k.replace('_', ' '); }).join(', ') : '—',
        final: F ? ('Col ' + longStr(F.col_long) + ' (' + (src.col_long || '?') + '), ' + transStr(F.col_trans) +
          ' (' + (src.col_trans || '?') + '); Shaft ' + longStr(F.shaft_long) + ' (' + (src.shaft_long || '?') + '), ' +
          transStr(F.shaft_trans) + ' (' + (src.shaft_trans || '?') + ')') : '—',
        Mp: S ? kft(S.Mp) : '—',
        Mo: S ? kft(S.Mo) : '—',
        Vo: S ? fmt(S.Vo, 0) : '—',
        slender: slenderSummary(b, result.settings),
        shaft_M: S ? (kft(S.shaft_Mdemand) + (mMax ? ' (' + fmt(mMax.z / 12.0, 1) + ' ft)' : '') + ' / ' + kft(S.shaft_Mp)) : '—',
        shaft_V: vChk ? (fmt(vChk.demand, 0) + ' / ' + fmt(vChk.capacity, 0)) : '—'
      };
    });
  }
  // ruling 10-6: P_dead entered by the user is used only when there are no Dead rows
  function deadHint(resultBent) {
    var dc = resultBent && resultBent.axial && resultBent.axial.dead_cases;
    if (!isObj(dc) || !Object.keys(dc).length) return '';
    return 'from Dead cases: ' + Object.keys(dc).map(function (c) { return c + ' ' + fmt(dc[c], 0); }).join(', ') +
      ' kip (sum ' + fmt(resultBent.axial.P_dead, 0) + ' kip); the entered value is not used';
  }
  function rowWhere(r) {
    if (isNum(r._station)) return r._frame + ' @ ' + fmt(r._station / 12.0, 1) + ' ft';
    return r._source || r._frame || '';
  }
  function governingRows(checkRows) {
    // sorted by D/C (descending); moments in kip-ft
    return (checkRows || []).map(function (r, i) {
      return {
        i: i + 1, ratio: r.ratio,
        cells: [String(i + 1), r._case || '', rowWhere(r), r._bound || '', fmt(r.Pu, 0),
          (isNum(r._Pmin) && isNum(r._Pmax)) ? fmt(r._Pmin, 0) + ' .. ' + fmt(r._Pmax, 0) : '—',
          kft(r.Mu), kft(r.Mr), isNum(r._flexP) ? fmt(r._flexP, 0) : '—', r.flexStatus || '',
          fmt(r.Vu, 1), fmt(r.Vr2, 1), r.shearStatus || '', kft(r.Tu, 1), kft(r.Tr, 1),
          r.torsionConsider ? 'yes' : 'no', fmt(r.ratio, 3), r.ok ? 'OK' : 'NG']
      };
    }).sort(function (a, b) { return (b.ratio || 0) - (a.ratio || 0); });
  }
  var MOMENT_CHECKS = { 'Shaft flexure (capacity protection)': true };
  function checkRow(c) {
    var mom = MOMENT_CHECKS[c.name];
    var f = function (x) { return mom ? kft(x) : (isNum(x) ? (Math.abs(x) < 1 && x !== 0 ? fmt(x, 4) : fmt(x, 1)) : '—'); };
    return [c.group || '', c.name || '', f(c.demand), f(c.capacity),
      c.ratio_infinite ? '∞' : fmt(c.ratio, 3), c.ok ? 'OK' : 'NG', c.detail || '', c.ref || ''];
  }

  // ─── SVG polyline plot (no libraries) ──────────────────────────────
  var svgSeq = 0;
  function svgPlot(series, opts) {
    // series: {points [[x, y]], color, label, markers, dash (stroke-dasharray), width,
    // noScale (left out of the axis extents and clipped to the plot area, e.g. an
    // unstable p-y bound whose runaway values would flatten the other curves)}
    opts = opts || {};
    var W = opts.width || 360, H = opts.height || 260, m = { l: 62, r: 12, t: 22, b: 40 };
    var pts = [], all = [];
    series.forEach(function (s) {
      (s.points || []).forEach(function (p) {
        if (!(isNum(p[0]) && isNum(p[1]))) return;
        all.push(p);
        if (!s.noScale) pts.push(p);
      });
    });
    if (!pts.length) pts = all;
    if (!pts.length) return '<div class="circ-info">No data to plot.</div>';
    var clip = 'cs-clip-' + (++svgSeq);
    var xs = pts.map(function (p) { return p[0]; }), ys = pts.map(function (p) { return p[1]; });
    (opts.hlines || []).forEach(function (h) { if (isNum(h.y)) ys.push(h.y); });
    var x0 = Math.min.apply(null, xs.concat(opts.xZero ? [0] : [])), x1 = Math.max.apply(null, xs.concat(opts.xZero ? [0] : []));
    var y0 = Math.min.apply(null, ys), y1 = Math.max.apply(null, ys);
    if (x1 - x0 < 1e-9) { x0 -= 1; x1 += 1; }
    if (y1 - y0 < 1e-9) { y0 -= 1; y1 += 1; }
    var pw = W - m.l - m.r, ph = H - m.t - m.b;
    var sx = function (x) { return m.l + (x - x0) / (x1 - x0) * pw; };
    var sy = function (y) { return opts.invertY ? m.t + (y - y0) / (y1 - y0) * ph : m.t + (y1 - y) / (y1 - y0) * ph; };
    var o = ['<svg xmlns="http://www.w3.org/2000/svg" width="' + W + '" height="' + H + '" viewBox="0 0 ' + W + ' ' + H +
      '" style="background:#fff;border:1px solid #dce1e8;border-radius:4px;font-family:Segoe UI,sans-serif">'];
    o.push('<text x="' + (W / 2) + '" y="14" text-anchor="middle" font-size="12" font-weight="600" fill="#1a5276">' + esc(opts.title || '') + '</text>');
    o.push('<rect x="' + m.l + '" y="' + m.t + '" width="' + pw + '" height="' + ph + '" fill="none" stroke="#bbb"/>');
    o.push('<defs><clipPath id="' + clip + '"><rect x="' + m.l + '" y="' + m.t + '" width="' + pw + '" height="' + ph + '"/></clipPath></defs>');
    for (var i = 0; i <= 4; i++) {
      var xv = x0 + (x1 - x0) * i / 4, yv = y0 + (y1 - y0) * i / 4;
      o.push('<text x="' + sx(xv).toFixed(1) + '" y="' + (H - m.b + 14) + '" text-anchor="middle" font-size="10" fill="#555">' + esc(fmtTick(xv)) + '</text>');
      o.push('<text x="' + (m.l - 4) + '" y="' + (sy(yv) + 3).toFixed(1) + '" text-anchor="end" font-size="10" fill="#555">' + esc(fmtTick(yv)) + '</text>');
    }
    if (x0 < 0 && x1 > 0) o.push('<line x1="' + sx(0).toFixed(1) + '" y1="' + m.t + '" x2="' + sx(0).toFixed(1) + '" y2="' + (m.t + ph) + '" stroke="#999" stroke-dasharray="3,3"/>');
    o.push('<text x="' + (m.l + pw / 2) + '" y="' + (H - 6) + '" text-anchor="middle" font-size="11" fill="#333">' + esc(opts.xlabel || '') + '</text>');
    o.push('<text x="12" y="' + (m.t + ph / 2) + '" text-anchor="middle" font-size="11" fill="#333" transform="rotate(-90 12 ' + (m.t + ph / 2) + ')">' + esc(opts.ylabel || '') + '</text>');
    (opts.hlines || []).forEach(function (h) {
      if (!isNum(h.y)) return;
      var yy = sy(h.y).toFixed(1);
      o.push('<line x1="' + m.l + '" y1="' + yy + '" x2="' + (m.l + pw) + '" y2="' + yy + '" stroke="#e67e22" stroke-dasharray="5,3"/>');
      o.push('<text x="' + (m.l + pw - 2) + '" y="' + (yy - 3) + '" text-anchor="end" font-size="10" fill="#e67e22">' + esc(h.label || '') + '</text>');
    });
    series.forEach(function (s, k) {
      var p = (s.points || []).filter(function (q) { return isNum(q[0]) && isNum(q[1]); });
      if (!p.length) return;
      var d = p.map(function (q) { return sx(q[0]).toFixed(1) + ',' + sy(q[1]).toFixed(1); }).join(' ');
      var col = s.color || '#2980b9';
      o.push('<polyline fill="none" stroke="' + col + '" stroke-width="' + (isNum(s.width) ? s.width : 1.8) + '"' +
        (s.dash ? ' stroke-dasharray="' + esc(s.dash) + '"' : '') + ' clip-path="url(#' + clip + ')" points="' + d + '"/>');
      if (s.markers) p.forEach(function (q) { o.push('<circle cx="' + sx(q[0]).toFixed(1) + '" cy="' + sy(q[1]).toFixed(1) + '" r="2.5" fill="' + col + '"/>'); });
      if (s.label) {
        // opts.legend 'br' stacks the labels in the bottom-right corner (default: top-left)
        if (opts.legend === 'br') o.push('<text x="' + (m.l + pw - 6) + '" y="' + (m.t + ph - 8 - 12 * (series.length - 1 - k)) +
          '" text-anchor="end" font-size="10" fill="' + col + '">' + esc(s.label) + '</text>');
        else o.push('<text x="' + (m.l + 6) + '" y="' + (m.t + 14 + 12 * k) + '" font-size="10" fill="' + col + '">' + esc(s.label) + '</text>');
      }
    });
    (opts.points || []).forEach(function (q) {
      o.push('<circle cx="' + sx(q.x).toFixed(1) + '" cy="' + sy(q.y).toFixed(1) + '" r="4" fill="none" stroke="#c0392b" stroke-width="2"/>');
      // q.anchor 'end' puts the label left of the point, q.below under it (charts whose marks sit at an edge)
      if (q.label) o.push('<text x="' + (sx(q.x) + (q.anchor === 'end' ? -6 : 6)).toFixed(1) + '" y="' + (sy(q.y) + (q.below ? 16 : -6)).toFixed(1) +
        '"' + (q.anchor === 'end' ? ' text-anchor="end"' : '') + ' font-size="10" fill="#c0392b">' + esc(q.label) + '</text>');
    });
    o.push('</svg>');
    return o.join('');
  }
  function fmtTick(v) {
    var a = Math.abs(v);
    if (a >= 1000) return v.toFixed(0);
    if (a >= 10) return v.toFixed(1);
    return v.toFixed(2);
  }

  // ─── Charts shared by the drill-down and the report (Task 11) ──────
  // Column M-phi curve at the governing P (the one that set Mo); x = phi x 10^3 (1/in).
  function mphiChart(c, title) {
    if (!c || !Array.isArray(c.phi) || !c.phi.length) return '<div class="circ-info">No M-&phi; curve in the result.</div>';
    var pts = c.phi.map(function (f, i) { return [f * 1000.0, isNum(c.M[i]) ? c.M[i] / 12.0 : null]; });
    var marks = [];
    if (isNum(c.phi_y) && isNum(c.Mp)) marks.push({ x: c.phi_y * 1000.0, y: c.Mp / 12.0, label: 'φy, Mp', below: true });
    if (isNum(c.phi_u)) {
      var last = pts[pts.length - 1];
      marks.push({ x: c.phi_u * 1000.0, y: isNum(last[1]) ? last[1] : c.Mp / 12.0, label: 'φu', anchor: 'end', below: true });
    }
    return svgPlot([{ points: pts, color: '#2980b9' },
      { points: isNum(c.phi_y) && isNum(c.phi_u) && isNum(c.Mp) ? [[0, 0], [c.phi_y * 1000.0, c.Mp / 12.0], [c.phi_u * 1000.0, c.Mp / 12.0]] : [],
        color: '#7f8c8d', dash: '4,3', width: 1.2, label: 'bilinear: Mp = ' + kft(c.Mp) + ' kip-ft' }], {
      title: (title || 'M-φ') + ' at P = ' + fmt(c.P, 0) + ' kip', xlabel: 'φ (×10⁻³ 1/in)', ylabel: 'M (kip-ft)',
      points: marks, legend: 'br'
    });
  }
  // Shaft M(z) / V(z) / y(z): every soil bound (governing emphasised, unstable dashed grey
  // and labelled); the cantilever / interface bases plot shaft_profile.  z = depth below
  // the top of shaft (ft), the datum of shaft_profile / profiles_by_bound / Df_eq_gov.
  function shaftSeries(S, k) {
    var pr = S.pile && Array.isArray(S.pile.profiles_by_bound) ? S.pile.profiles_by_bound : [];
    var scale = k === 'M' ? 1 / 12.0 : 1;
    if (!pr.length) {
      var idx = { M: 1, V: 2 }[k];
      if (!idx) return [];
      return [{ points: (S.shaft_profile || []).map(function (q) { return [isNum(q[idx]) ? q[idx] * scale : null, q[0] / 12.0]; }), color: '#c0392b' }];
    }
    return pr.map(function (b) {
      var pts = (b.z || []).map(function (z, i) { var v = (b[k] || [])[i]; return [isNum(v) ? v * scale : null, z / 12.0]; });
      var lab = '×' + fmt(b.factor, 2).replace(/\.?0+$/, '');
      if (!b.stable) return { points: pts, color: '#aaaaaa', dash: '5,4', width: 1.2, noScale: true, label: lab + ' unstable (excluded)' };
      if (b.governing) return { points: pts, color: '#c0392b', width: 2.6, label: lab + ' (governing)' };
      return { points: pts, color: '#2980b9', width: 1.4, label: lab };
    });
  }
  function shaftCharts(S) {
    if (!S) return [];
    var dfl = S.pile && isNum(S.pile.Df_eq_gov) ? [{ y: S.pile.Df_eq_gov / 12.0, label: 'Df_eq' }] : [];
    var o = { ylabel: 'z below top of shaft (ft)', invertY: true, xZero: true, hlines: dfl, legend: 'br' };
    var out = [svgPlot(shaftSeries(S, 'M'), Object.assign({ title: 'Shaft M(z) (' + (S.shaft_basis || '') + ')', xlabel: 'M (kip-ft)' }, o)),
      svgPlot(shaftSeries(S, 'V'), Object.assign({ title: 'Shaft V(z)', xlabel: 'V (kip)' }, o))];
    var y = shaftSeries(S, 'y');
    if (y.length) out.push(svgPlot(y, Object.assign({ title: 'Shaft y(z)', xlabel: 'y (in)' }, o)));
    return out;
  }

  // ─── Printable report (Task 11) ────────────────────────────────────
  // Ported seismic provisions keep the seismic app's references, which are not yet
  // checked against the printed codes (OPEN_VERIFICATION_ITEMS.md section E).
  var UNVERIFIED_SUFFIX = '(unverified — see OPEN_VERIFICATION_ITEMS E)';
  // Open DECIDE rows of OPEN_VERIFICATION_ITEMS.md section E (pinned equal to the file
  // by tests/test_colshaft_ui_static.py).
  var OPEN_DECIDE_E = [
    ['E13', 'Soil stability: unstable soil bounds are dropped from the overstrength shaft demand envelope ' +
      '("Shaft p-y solve" is NG only when every bound is unstable); "Soil-pile stability (p-y)" is NG when any bound ' +
      'is unstable at the yield-level force (upstream split).'],
    ['E14', 'Df_eq for ℓu from a fixed-free solve at Mo/H on the softest stable bound (conservative); the shaft ' +
      'confinement and oversize checks carry no ported reference.'],
    ['E17', 'The p-y axial-ramp guard (ruling 8-16) is applied to the strength rows only; the seismic stability / ' +
      'demand path follows upstream.']
  ];
  var REPORT_SECTIONS = [
    ['inputs', '1. Inputs'], ['parse', '2. Parse summary'], ['lrfd', '3. LRFD strength design — governing rows'],
    ['slender', '4. Slenderness screen'], ['mphi', '5. Moment-curvature'], ['mo', '6. Overstrength moment and shear'],
    ['colshear', '7. Column seismic shear'], ['shaft', '8. Shaft demand and checks'], ['checks', '9. Final checks'],
    ['cage', '10. Final cage']
  ];
  function seismicRef(ref) { return ref ? ref + ' ' + UNVERIFIED_SUFFIX : '—'; }
  // Seismic-group refs are the ported ref_* strings; the LRFD groups carry none.
  function checkRef(c) { return c && c.group === 'Seismic' ? seismicRef(c.ref) : ((c && c.ref) || '—'); }
  function slenderAxes(checkRows) {
    // per CSiBridge axis: the row with the largest K*lu/r - limit; status per colshaft_slender
    var out = [];
    ['2', '3'].forEach(function (ax) {
      var best = null;
      (checkRows || []).forEach(function (r) {
        var k = r['_klr' + ax], lim = r['_slender_limit' + ax];
        if (!isNum(k) || !isNum(lim)) return;
        if (best === null || k - lim > best.klr - best.limit) best = { axis: ax, klr: k, limit: lim };
      });
      if (best) {
        best.status = best.klr >= 100.0 ? SLENDER_STATUS.REFINED : best.klr < best.limit ? SLENDER_STATUS.NEGLECT : SLENDER_STATUS.PENDING;
        out.push(best);
      }
    });
    return out;
  }
  function codeLabel(key) {
    var c = CODES.filter(function (x) { return x.key === key; })[0];
    return c ? c.label : String(key || '');
  }
  function memberStr(m) {
    if (!m) return '—';
    return 'D = ' + fmt(m.D, 1) + ' in, f\'c = ' + fmt(m.fc, 2) + ' ksi, fy = ' + fmt(m.fy, 0) + ' ksi, cover = ' +
      fmt(m.cover, 2) + ' in, ' + (m.trans_type || 'hoop') + (m.hoop_closure ? ' (' + m.hoop_closure + ')' : '');
  }
  function ovStr(ov) {
    if (!isObj(ov) || !Object.keys(ov).length) return 'none';
    return OV_PARTS.filter(function (k) { return ov[k]; }).map(function (k) {
      return k.replace('_', ' ') + ' ' + (/long/.test(k) ? longStr(ov[k]) : transStr(ov[k]));
    }).join('; ');
  }
  function rptKV(rows) {
    return rows.map(function (r) {
      return '<div class="rpt-row"><span class="rpt-lbl">' + esc(r[0]) + '</span><span class="rpt-val">' + esc(r[1]) + '</span></div>';
    }).join('');
  }
  function rptTable(hdr, rows, cls) {
    return '<table class="rpt-table' + (cls ? ' ' + cls : '') + '"><thead><tr>' + hdr.map(function (h) { return '<th>' + esc(h) + '</th>'; }).join('') +
      '</tr></thead><tbody>' + rows.map(function (r) {
        return '<tr>' + r.map(function (c) {
          var cl = c === 'OK' ? ' class="rpt-pass"' : c === 'NG' ? ' class="rpt-fail"' : '';
          return '<td' + cl + '>' + esc(c) + '</td>';
        }).join('') + '</tr>';
      }).join('') + '</tbody></table>';
  }
  function rptNote(t) { return '<div class="rpt-note">' + esc(t) + '</div>'; }
  function rptRef(t) { return '<div class="rpt-ref">' + esc(t) + '</div>'; }
  function rptEq(lines) { return '<div class="rpt-eq">' + lines.map(esc).join('<br>') + '</div>'; }
  function lrfdRowsTable(checkRows) {
    if (!checkRows || !checkRows.length) return rptNote('No LRFD rows.');
    var rows = checkRows.map(function (r, i) { return { r: r, i: i }; })
      .sort(function (a, b) { return (b.r.ratio || 0) - (a.r.ratio || 0); })
      .map(function (x) {
        var r = x.r;
        return [String(x.i + 1), r._case || '', rowWhere(r), fmt(r.Pu, 0), kft(r.Mu), fmt(r.Vu, 1), kft(r.Tu, 1),
          kft(r.Mr), fmt(r.Vr2, 1), kft(r.Tr, 1), fmt(r.ratio, 3), isNum(r._flexP) ? fmt(r._flexP, 0) : '—', r.ok ? 'OK' : 'NG'];
      });
    return rptTable(['#', 'Case', 'Where', 'Pu', 'Mu', 'Vu', 'Tu', 'Mr', 'Vr', 'Tr', 'D/C', 'P for flexure', ''], rows) +
      rptNote('Pu, Vu, Vr, P in kip (compression < 0); Mu, Mr, Tu, Tr in kip-ft. Sorted by D/C. "P for flexure" = the axial ' +
        'load in [P_min, P_max] at which the cage\'s flexural resistance is lowest (envelope rows). Checked with the app\'s ' +
        'AASHTO LRFD circular-section engine (unchanged).');
  }
  function reportBent(b, pb, result, k) {
    var S = b.seismic, ax = b.axial || {}, F = b.final, src = b.final_source || {}, refs = (S && S.refs) || {};
    var sec = {};
    var na = rptNote('Not available (no seismic result for this bent).');
    // 1. inputs
    var i1 = [];
    if (pb) {
      i1.push(['Column frames', (pb.col_frames || []).join(', ') || '—']);
      i1.push(['Shaft frames', (pb.shaft_frames || []).join(', ') || '(none)']);
      i1.push(['Column clear height H', fmt((b.H_in || 0) / 12.0, 2) + ' ft' + (pb.H_in === null || pb.H_in === undefined ? ' (auto, from the column frame stations)' : ' (entered)')]);
      i1.push(['End conditions', 'longitudinal ' + (pb.end_condition_long || 'fixed-free') + ', transverse ' + (pb.end_condition_trans || 'fixed-free') +
        (S ? ' (governing: ' + S.end_condition + ')' : '')]);
      i1.push(['Base end', pb.base_end || 'auto']);
      i1.push(['Column', memberStr(pb.column)]);
      i1.push(['Shaft', memberStr(pb.shaft)]);
      i1.push(['λmo', S ? fmt(S.lambda_mo, 2) : (isNum(pb.lambda_mo) ? fmt(pb.lambda_mo, 2) : '1.20 (default)')]);
      i1.push(['μD', S ? fmt(S.mu_d, 2) + (isNum(pb.mu_d) ? ' (entered)' : ' (code default)') : (isNum(pb.mu_d) ? fmt(pb.mu_d, 2) : 'code default')]);
      i1.push(['Shaft basis', b.shaft_basis || pb.shaft_basis || '—']);
      if (isNum(pb.L_eq_in)) i1.push(['Pile equivalent cantilever length L_eq', fmt(pb.L_eq_in / 12.0, 2) + ' ft']);
      if (isNum(pb.L_embed_in)) i1.push(['Shaft embedded length', fmt(pb.L_embed_in / 12.0, 2) + ' ft']);
      if (pb.soil_bounds) i1.push(['Soil-stiffness bounds', pb.soil_bounds.map(function (x) { return '×' + x; }).join(', ')]);
      i1.push(['P_dead entered (used only without Dead rows)', isNum(pb.P_dead) ? fmt(pb.P_dead, 0) + ' kip' : '—']);
      i1.push(['Overrides', ovStr(pb.override)]);
    }
    var h1 = pb ? rptKV(i1) : rptNote('Inputs not available.');
    if (pb && pb.soil && Array.isArray(pb.soil.layers)) {
      h1 += '<h4>Soil profile (top of shaft = ground surface; J = ' + esc(fmt(pb.soil.J, 2)) + ', ' + (pb.soil.cyclic ? 'cyclic' : 'static') + ')</h4>' +
        rptTable(['#', 'Thickness (ft)', 'p-y model', 'γ (pcf)', 'su top / bot (ksf)', 'ε50', 'φ′ (deg)', 'k (pci)', 'Submerged'],
          pb.soil.layers.map(function (l, j) {
            return [String(j + 1), fmt(l.thickness_ft, 1), l.py_model, fmt(l.gamma_pcf, 0),
              (isNum(l.su_top_ksf) || isNum(l.su_bot_ksf)) ? fmt(l.su_top_ksf, 2) + ' / ' + fmt(l.su_bot_ksf, 2) : '—',
              isNum(l.eps50) ? fmt(l.eps50, 4) : '—', isNum(l.phi_deg) ? fmt(l.phi_deg, 1) : '—', isNum(l.k_pci) ? fmt(l.k_pci, 0) : '—',
              l.submerged ? 'yes' : 'no'];
          }));
    }
    sec.inputs = h1;
    // 2. parse summary
    var P = result.parse || {};
    var u = P.units || {};
    var names = (result.bents || []).map(function (x) { return String(x.name) + ': '; });
    var gw = (P.warnings || []).filter(function (w) { return !names.some(function (nm) { return String(w).indexOf(nm) === 0; }); });
    var h2 = rptKV([['Units', [u.force, u.moment, u.length].filter(Boolean).join(', ') || '—'],
      ['Rows / envelope rows', fmt(P.n_rows, 0) + ' / ' + fmt(P.n_envelope, 0)],
      ['Load cases', Object.keys(P.categories || {}).map(function (c) { return c + ' = ' + P.categories[c]; }).join('; ') || '—'],
      ['P_dead', fmt(ax.P_dead, 0) + ' kip' + (isObj(ax.dead_cases) && Object.keys(ax.dead_cases).length ? ' (sum of Dead cases: ' +
        Object.keys(ax.dead_cases).map(function (c) { return c + ' ' + fmt(ax.dead_cases[c], 0); }).join(', ') + ')' : ' (entered)')],
      ['Extreme axial range', isNum(ax.P_ext_min) ? fmt(ax.P_ext_min, 0) + ' .. ' + fmt(ax.P_ext_max, 0) + ' kip' : '— (no Extreme rows)']]);
    if (P.n_envelope > 0) h2 += '<div class="rpt-eq">' + esc('Envelope output (Max/Min): every row is envelope-bounded (conservative). ' +
      'M = √(max|M2|² + max|M3|²) and V = √(max|V2|² + max|V3|²) combine maxima from different steps (conservative by up to √2).') + '</div>';
    var bw = (b.warnings || []);
    if (gw.length || bw.length) h2 += '<h4>Warnings</h4><ul class="cs-rpt-list">' + gw.concat(bw).map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('') + '</ul>';
    if ((b.no_solution || []).length) h2 += '<h4 class="rpt-fail">No solution</h4><ul class="cs-rpt-list">' + b.no_solution.map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('') + '</ul>';
    sec.parse = h2;
    // 3. LRFD rows
    var L = b.lrfd || {};
    var h3 = '<h4>Column (final cage)</h4>' + lrfdRowsTable(L.col && L.col.check_rows);
    if (L.shaft && L.shaft.check_rows) h3 += '<h4>Shaft (' + esc(L.shaft.source || '') + ')</h4>' + lrfdRowsTable(L.shaft.check_rows);
    sec.lrfd = h3;
    // 4. slenderness
    var on = result.settings && result.settings.slenderness_on;
    var h4;
    if (!on) h4 = rptNote('Slenderness screen off.');
    else {
      var axs = slenderAxes(L.col && L.col.check_rows);
      h4 = axs.length ? rptTable(['Axis', 'Kℓu/r', 'Limit', 'Status'], axs.map(function (a) {
        return [a.axis, fmt(a.klr, 1), fmt(a.limit, 1), a.status];
      })) : rptNote('No screened rows.');
      h4 += '<div class="rpt-eq">' + esc('S6: moment magnification is NOT applied — AASHTO Art. 4.5.3.2.2b and the §5.6.4.3 EI equations ' +
        'are not available (open item S6). Screen only: Kℓu/r is classified, the factored moments are not magnified.') + '</div>' +
        rptNote('r = 0.25·D; ℓu default = H + Df (Df = ' + (isNum(b.Df_for_lu) ? fmt(b.Df_for_lu / 12.0, 2) + ' ft' : '—') +
          '). Envelope rows use M1/M2 = +1 (single curvature).');
    }
    sec.slender = h4;
    // 5. M-phi
    if (S) {
      var mp = (S.Mp_by_P || []).slice().sort(function (a, c) { return a[0] - c[0]; });
      var h5 = rptTable(['P (kip)', 'Mp (kip-ft)', ''], mp.map(function (q) {
        return [fmt(q[0], 0), kft(q[1]), q[0] === S.Mp_P ? 'governs Mo' : (q[0] === ax.P_dead ? 'P_dead' : '')];
      }));
      var c = S.mphi || {}, cs2 = S.mphi_shaft || {};
      var ex = function (x) { return isNum(x) ? x.toExponential(3) : '—'; };
      h5 += rptTable(['Member', 'P (kip)', 'φy (1/in)', 'Mp (kip-ft)', 'φu (1/in)', 'Failure'], [
        ['Column (governing P)', fmt(S.Mp_P, 0), ex(c.phi_y), kft(S.Mp), ex(c.phi_u), c.failure_mode || '—'],
        ['Shaft (P_dead)', fmt(ax.P_dead, 0), ex(cs2.phi_y), kft(S.shaft_Mp), ex(cs2.phi_u), cs2.failure_mode || '—']]);
      h5 += '<div class="cs-rpt-charts">' + mphiChart(S.mphi, 'Column M-φ') + mphiChart(S.mphi_shaft, 'Shaft M-φ') + '</div>';
      h5 += rptNote('Expected material properties; Mp = idealised plastic moment of the bilinear fit.') + rptRef(seismicRef(refs.flexure));
      sec.mphi = h5;
      // 6. Mo / Vo
      var two = S.end_condition === 'fixed-fixed';
      var Hft = S.H / 12.0;
      sec.mo = rptEq(['Mo = λmo × Mp = ' + fmt(S.lambda_mo, 2) + ' × ' + kft(S.Mp, 1) + ' = ' + kft(S.Mo, 1) + ' kip-ft',
        'Vo = ' + (two ? '2·Mo / H = 2 × ' : 'Mo / H = ') + kft(S.Mo, 1) + ' / ' + fmt(Hft, 2) + ' = ' + fmt(S.Vo, 1) + ' kip  (' + S.end_condition + ')']) +
        rptRef(seismicRef(refs.overstrength)) +
        rptNote('Mo is applied at the top of the shaft (fixed-fixed: head moment +Mo with V = 2·Mo/H, ruling 3A-1).');
      // 7. column seismic shear
      var v = S.col_shear || [];
      var rq = S.required_transverse || {};
      sec.colshear = rptEq(['At P = ' + fmt(S.P_vc, 0) + ' kip (least compression of the Extreme rows), μD = ' + fmt(S.mu_d, 2) + ', inside the plastic hinge:',
        'Vc = ' + fmt(v[1], 1) + ' kip,  Vs = ' + fmt(v[2], 1) + ' kip,  φVn = ' + fmt(v[0], 1) + ' kip  vs  Vo = ' + fmt(S.Vo, 1) + ' kip  → ' +
          (isNum(v[0]) && v[0] >= S.Vo ? 'OK' : 'NG'),
        'ρs = ' + fmt(S.rho_s_col, 4) + '  vs  ρs,min = ' + fmt(S.rho_s_min, 4) +
          (isNum(S.s_max_detailing) ? ';  s,max (detailing) = ' + fmt(S.s_max_detailing, 2) + ' in' : '') +
          (S.min_trans_bar ? ';  min transverse bar #' + S.min_trans_bar : ''),
        'Lightest seismic transverse meeting φVn ≥ Vo, ρs,min and spacing: ' + (rq.ok ? transStr(rq) : 'none in the search range')]) +
        rptRef(seismicRef(refs.shear)) + rptRef(seismicRef(refs.transverse));
      // 8. shaft
      var h8 = rptKV([['Basis', S.shaft_basis || '—'],
        ['Shaft flexure demand (factor × max M(z))', kft(S.shaft_Mdemand) + ' kip-ft vs Mp,shaft = ' + kft(S.shaft_Mp) + ' kip-ft'],
        ['Shaft shear capacity φVn', fmt(S.shaft_phiVn, 1) + ' kip'],
        ['EI column / shaft (Mp/φy)', fmt(S.EI_col, 0) + ' / ' + fmt(S.EI_shaft, 0) + ' kip-in²'],
        ['Df (for ℓu)', isNum(S.Df) ? fmt(S.Df / 12.0, 2) + ' ft' : '—']]);
      if (S.pile && Array.isArray(S.pile.bounds)) {
        h8 += rptTable(['Bound', 'Stable', 'Df_eq (ft)', 'max M (kip-ft)', 'at z (ft)', 'max V (kip)'], S.pile.bounds.map(function (x) {
          return ['×' + x.factor, x.stable ? 'yes' : 'NO', isNum(x.Df_eq) ? fmt(x.Df_eq / 12.0, 2) : '—', kft(x.Mmax),
            isNum(x.z_Mmax) ? fmt(x.z_Mmax / 12.0, 2) : '—', fmt(x.Vmax, 1)];
        }));
        h8 += rptNote('z = depth below the top of shaft. Unstable bounds are drawn dashed grey and excluded from the demand envelope.');
      }
      h8 += '<div class="cs-rpt-charts">' + shaftCharts(S).join('') + '</div>';
      var shc = (b.final_checks || []).filter(function (x) { return x.group === 'Seismic' && /^(Shaft|Soil)/.test(x.name || ''); });
      if (shc.length) h8 += rptTable(['Check', 'Demand', 'Capacity', 'Ratio', '', 'Ref'], shc.map(function (x) {
        var cr = checkRow(x);
        return [cr[1], cr[2], cr[3], cr[4], cr[5], checkRef(x)];
      }));
      h8 += rptRef(seismicRef(refs.shaft_capacity));
      sec.shaft = h8;
    } else {
      sec.mphi = sec.mo = sec.colshear = sec.shaft = na;
    }
    // 9. final checks
    sec.checks = (b.final_checks || []).length ? rptTable(['Group', 'Check', 'Demand', 'Capacity', 'Ratio', '', 'Detail', 'Reference'],
      b.final_checks.map(function (x) { var cr = checkRow(x); cr[7] = checkRef(x); return cr; }), 'cs-rpt-checks') +
      rptNote('Shaft flexure demand/capacity in kip-ft; other values in the check\'s own units (kip, in, ratios); detail text may quote kip-in.')
      : rptNote('No final checks.');
    // 10. final cage
    sec.cage = F ? rptTable(['Part', 'Cage', 'Source', 'Steel'], [
      ['Column longitudinal', longStr(F.col_long), src.col_long || '—', 'Ast = ' + fmt(F.col_long && F.col_long.Ast, 2) + ' in², ρl = ' + fmt(F.col_long && F.col_long.rho_l, 4)],
      ['Column transverse', transStr(F.col_trans), src.col_trans || '—', 'ρs = ' + fmt(F.col_trans && F.col_trans.rho_s, 4)],
      ['Shaft longitudinal', longStr(F.shaft_long), src.shaft_long || '—', 'Ast = ' + fmt(F.shaft_long && F.shaft_long.Ast, 2) + ' in², ρl = ' + fmt(F.shaft_long && F.shaft_long.rho_l, 4)],
      ['Shaft transverse', transStr(F.shaft_trans), src.shaft_trans || '—', 'ρs = ' + fmt(F.shaft_trans && F.shaft_trans.rho_s, 4)]]) +
      rptNote('Source: LRFD, Seismic, LRFD+Seismic (merged cage re-walked, ruling 8-15) or Override (used as entered).')
      : rptNote('No final cage (no solution).');
    var h = '<div class="cs-rpt-bent' + (k ? ' cs-rpt-break' : '') + '"><h2>Bent ' + esc(b.name) + ' — <span class="' +
      (b.status === 'OK' ? 'rpt-pass' : 'rpt-fail') + '">' + esc(b.status) + '</span></h2>';
    REPORT_SECTIONS.forEach(function (s) { h += '<h3 data-sec="' + s[0] + '">' + esc(s[1]) + '</h3>' + sec[s[0]]; });
    return h + '</div>';
  }
  // Whole report.  result = run_colshaft output; payload = the buildPayload() sent for it
  // (bents index-aligned); meta = {project, date}.
  function reportHtml(result, payload, meta) {
    meta = meta || {};
    if (!result || !Array.isArray(result.bents)) return '<div class="rpt-note">Run Design first.</div>';
    var pbs = (payload && payload.bents) || [];
    var st = result.settings || {};
    var h = '<h1>Column on Shaft — Design Report</h1><div class="rpt-meta">' +
      (meta.project ? 'Project: <b>' + esc(meta.project) + '</b> · ' : '') + 'Bents: ' + esc(result.bents.map(function (b) { return b.name; }).join(', ')) +
      ' · Date: ' + esc(meta.date || '') + ' · Seismic code: ' + esc(codeLabel(result.code)) + ' · LRFD: AASHTO LRFD (app engine)' +
      ' · Envelope mode: ' + esc(st.envelope_mode || 'station') + ' · Slenderness screen: ' + (st.slenderness_on ? 'on' : 'off') + '</div>';
    var env = result.parse && result.parse.n_envelope > 0;
    h += '<div class="cs-rpt-box" data-sec="assumptions"><b>Assumptions &amp; open decisions</b><ul class="cs-rpt-list">' +
      '<li>' + esc(env ? 'Envelope bounding: the CSiBridge Max/Min rows are not concurrent, so every row is envelope-bounded (conservative): ' +
        'biaxial M and V from the envelope maxima (up to √2 conservative); shear, torsion and the longitudinal V+T check at P_max ' +
        '(least compression); flexure at the P in [P_min, P_max] with the lowest resistance.' : 'Concurrent rows used as given (no envelope rows).') + '</li>' +
      '<li>' + esc('S6: slenderness moment magnification is not applied (AASHTO Art. 4.5.3.2.2b and the §5.6.4.3 EI equations not ' +
        'available); the optional screen classifies Kℓu/r only.') + '</li>' +
      '<li>' + esc('Seismic capacity design ported from the Seismic Column app @ 9265d67: its references are not yet checked ' +
        'against the printed codes (OPEN_VERIFICATION_ITEMS E1–E11) and are marked ' + UNVERIFIED_SUFFIX + '.') + '</li>' +
      '<li>' + esc('Defaults: Extreme rows set only the axial range for M-φ and the seismic Vc (S2); shaft flexural capacity = M-φ ' +
        'expected Mp (S3); no service crack control (S4).') + '</li>' +
      '<li>' + esc('Open decisions (DECIDE):') + '<ul>' + OPEN_DECIDE_E.map(function (e) { return '<li><b>' + esc(e[0]) + '</b> ' + esc(e[1]) + '</li>'; }).join('') +
      '</ul></li></ul></div>';
    h += rptTable(['Bent', 'Status', 'Final cage (source)'], result.bents.map(function (b) {
      return [String(b.name), b.status, resultRows({ bents: [b], settings: st })[0].final];
    }));
    result.bents.forEach(function (b, k) {
      var pb = pbs[k] && pbs[k].name === b.name ? pbs[k] : pbs.filter(function (x) { return x && x.name === b.name; })[0];
      h += reportBent(b, pb || null, result, k);
    });
    return h;
  }

  var api = {
    CODES: CODES, CATEGORIES: CATEGORIES, PY_MODELS: PY_MODELS, DEFAULT_PARAMS: DEFAULT_PARAMS,
    STATUS_COLORS: STATUS_COLORS, STATUS_RANK: STATUS_RANK,
    num: num, esc: esc, fmt: fmt, splitFrames: splitFrames, setPath: setPath, getPath: getPath,
    defaultState: defaultState, defaultBent: defaultBent, defaultSoil: defaultSoil, defaultLayer: defaultLayer,
    normalizeState: normalizeState, serializeState: serializeState, autoHeightFt: autoHeightFt,
    shaftBasis: shaftBasis, validateState: validateState, buildPayload: buildPayload,
    mergeCategories: mergeCategories, statusColor: statusColor, worstStatus: worstStatus,
    longStr: longStr, transStr: transStr, resultRows: resultRows, governingRows: governingRows,
    checkRow: checkRow, svgPlot: svgPlot, profileMax: profileMax,
    SLENDER_STATUS: SLENDER_STATUS, SLENDER_RANK: SLENDER_RANK, BAR_SIZES: BAR_SIZES,
    slenderSummary: slenderSummary, deadHint: deadHint, overrideErrors: overrideErrors,
    UNVERIFIED_SUFFIX: UNVERIFIED_SUFFIX, OPEN_DECIDE_E: OPEN_DECIDE_E, REPORT_SECTIONS: REPORT_SECTIONS,
    seismicRef: seismicRef, checkRef: checkRef, slenderAxes: slenderAxes, mphiChart: mphiChart,
    shaftSeries: shaftSeries, shaftCharts: shaftCharts, reportHtml: reportHtml, codeLabel: codeLabel
  };
  if (typeof module !== 'undefined' && module.exports) module.exports = api;

  // ═══ DOM / rendering (browser only) ═══════════════════════════════
  if (typeof document === 'undefined') return;
  var panel = document.getElementById('tab-colshaft');
  if (!panel) return;

  var state = defaultState();
  var lastResult = null;
  var lastPayload = null;     // the payload sent for lastResult (report inputs, Task 11)
  var reportShown = false;
  var drillIdx = null;
  var busy = false;

  function markDirty() {
    try { if (typeof window.markDirty === 'function') window.markDirty(); } catch (e) { /* ignore */ }
  }
  function bridge() { return window.pywebview && window.pywebview.api; }

  // ── input builders (data-cs = state path, data-t = num|str|bool) ──
  function inp(path, t, attrs) {
    var v = getPath(state, path);
    if (t === 'bool') return '<input type="checkbox" data-cs="' + path + '" data-t="bool"' + (v ? ' checked' : '') + (attrs || '') + '>';
    return '<input type="' + (t === 'num' ? 'number' : 'text') + '"' + (t === 'num' ? ' step="any"' : '') +
      ' data-cs="' + path + '" data-t="' + t + '" value="' + esc(v === null || v === undefined ? '' : v) + '"' + (attrs || '') + '>';
  }
  function sel(path, options, attrs) {
    var v = getPath(state, path);
    return '<select data-cs="' + path + '" data-t="str"' + (attrs || '') + '>' + options.map(function (o) {
      var val = Array.isArray(o) ? o[0] : o, lab = Array.isArray(o) ? o[1] : o;
      return '<option value="' + esc(val) + '"' + (String(v) === String(val) ? ' selected' : '') + '>' + esc(lab) + '</option>';
    }).join('') + '</select>';
  }
  function field(label, html, unit) {
    return '<label style="display:flex;flex-direction:column;gap:2px;font-size:0.76rem;color:#2c3e50;">' +
      '<span>' + label + (unit ? ' <span style="color:#7f8c8d">(' + unit + ')</span>' : '') + '</span>' + html + '</label>';
  }
  function grid(items) {
    return '<div style="display:flex;flex-wrap:wrap;gap:8px 14px;align-items:flex-end;margin:6px 0;">' + items.join('') + '</div>';
  }
  function card(title, color, body, id) {
    return '<div class="card" style="margin-bottom:14px;"' + (id ? ' id="' + id + '"' : '') + '><div class="card-header ' + color + '">' + title +
      '</div><div class="card-body">' + body + '</div></div>';
  }
  function notice(kind, html) {
    var c = { amber: ['#fef5e7', '#e67e22', '#7e5109'], red: ['#fdedec', '#c0392b', '#922b21'], blue: ['#ebf5fb', '#2980b9', '#1a5276'] }[kind];
    return '<div style="background:' + c[0] + ';border-left:4px solid ' + c[1] + ';color:' + c[2] +
      ';padding:7px 10px;margin:6px 0;font-size:0.82rem;border-radius:3px;">' + html + '</div>';
  }
  function btn(label, act, extra, cls) {
    return '<button type="button" class="' + (cls || 'toggle-btn') + '" data-act="' + act + '"' + (extra || '') +
      ' style="' + (cls ? '' : 'background:#1a5276;') + 'margin:2px 4px 2px 0;">' + label + '</button>';
  }

  // ── sections ──
  function renderPaste() {
    var u = state.units;
    var html = '<div class="circ-info">Paste the CSiBridge "Element Forces - Frames" table (Frame, Station, OutputCase, P, V2, V3, T, M2, M3). ' +
      'This tab works in kip, in, ft, ksi and kip-ft; the app\'s global display-unit toggle does not apply here.</div>' +
      '<textarea id="cs-paste" data-cs="paste" data-t="raw" spellcheck="false" style="width:100%;height:140px;font-family:Consolas,monospace;font-size:0.75rem;">' +
      esc(state.paste) + '</textarea>' +
      grid([
        field('Force units (if no units row)', sel('units.force', UNIT_OPTIONS.force, ' id="cs-u-force"')),
        field('Moment units', sel('units.moment', UNIT_OPTIONS.moment, ' id="cs-u-moment"')),
        field('Length units', sel('units.length', UNIT_OPTIONS.length, ' id="cs-u-length"')),
        '<button type="button" class="calc-btn" id="cs-parse" data-act="parse">Parse</button>'
      ]) + '<div id="cs-parse-summary">' + parseSummaryHtml() + '</div>';
    return card('1. CSiBridge frame forces', 'blue', html, 'cs-card-paste');
  }
  function parseSummaryHtml() {
    var p = state.parse;
    if (!p) return '<div class="circ-info">Not parsed yet.</div>';
    var chips = [['Frames', (p.frames || []).length], ['Cases', (p.cases || []).length], ['Rows', p.n_rows], ['Envelope rows', p.n_envelope]];
    var h = '<div style="display:flex;gap:6px;flex-wrap:wrap;margin:6px 0;">' + chips.map(function (c) {
      return '<span class="badge badge-info">' + c[0] + ': ' + esc(c[1]) + '</span>';
    }).join('') + (p.units ? '<span class="badge badge-info">Units: ' + esc(p.units.force) + ', ' + esc(p.units.moment) + ', ' + esc(p.units.length) + '</span>' : '') + '</div>';
    var warns = p.warnings || [];
    if (warns.some(function (w) { return /No units row/i.test(w); })) {
      h += notice('red', '<b>Units ASSUMED:</b> the paste has no units row, so the unit dropdowns above were used (' +
        esc(state.units.force) + ', ' + esc(state.units.moment) + ', ' + esc(state.units.length) + '). Check them and Parse again if they are wrong.');
    }
    if (p.n_envelope > 0) {
      h += notice('amber', '<b>Envelope output (Max/Min): bounded conservatively — see report.</b> ' + esc(p.n_envelope) +
        ' envelope rows; results are envelope-bounded (conservative).');
    }
    if (warns.length) h += '<div style="font-size:0.78rem;"><b>Parse warnings:</b><ul style="margin:2px 0 0 18px;">' +
      warns.map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('') + '</ul></div>';
    if (p.frames && p.frames.length) h += '<div class="circ-info">Parsed frames: ' + p.frames.map(function (f) {
      return esc(f.name) + (isNum(f.height_in) ? ' (' + fmt(f.height_in / 12.0, 1) + ' ft)' : '');
    }).join(', ') + '</div>';
    return h;
  }
  function renderCases() {
    var p = state.parse;
    var body;
    if (!p || !(p.cases || []).length) body = '<div class="circ-info">Parse a table to list its load cases.</div>';
    else body = '<table class="data-table" id="cs-cases"><thead><tr><th>Case</th><th>Rows</th><th>Category</th></tr></thead><tbody>' +
      p.cases.map(function (c) {
        var v = state.categories[c.name] || c.default_category || 'Strength';
        return '<tr><td>' + esc(c.name) + '</td><td>' + esc(c.count) + '</td><td><select data-cat="' + esc(c.name) + '">' +
          CATEGORIES.map(function (k) { return '<option' + (k === v ? ' selected' : '') + '>' + k + '</option>'; }).join('') +
          '</select></td></tr>';
      }).join('') + '</tbody></table>';
    return card('2. Load cases', 'blue', body, 'cs-card-cases');
  }
  function renderSettings() {
    var h = grid([
      field('Seismic code', sel('code', CODES.map(function (c) { return [c.key, c.label]; }), ' id="cs-code"')),
      field('Envelope mode', sel('settings.envelope_mode', [['station', 'station (default)'], ['member', 'member (fastest, most conservative)']], ' id="cs-env-mode"')),
      field('Slenderness screen', inp('settings.slenderness_on', 'bool', ' id="cs-slender-on"'))
    ]) + '<div class="circ-info">Slenderness: magnification pending AASHTO Art. 4.5.3.2.2b (S6) — screen only (K&#8467;u/r classification, no magnified moments).</div>' +
      '<div style="font-weight:600;font-size:0.8rem;margin-top:8px;">Cage search</div>' +
      grid(PARAM_LABELS.map(function (p) { return field(p[1], inp('params.' + p[0], 'num', ' style="width:80px"'), p[2]); }));
    return card('3. Settings', 'blue', h, 'cs-card-settings');
  }
  function bentHtml(b, i) {
    var P = 'bents.' + i + '.';
    var w = ' style="width:80px"';
    var aH = autoHeightFt(state, b);
    var soilOpts = [['', '(none)']].concat(state.soils.map(function (s) { return [s.name, s.name]; }));
    var h = '<div style="border:1px solid #dce1e8;border-radius:6px;padding:8px 10px;margin-bottom:10px;">' +
      '<div style="display:flex;justify-content:space-between;align-items:center;"><b>Bent ' + (i + 1) + '</b>' +
      btn('Remove bent', 'rm-bent', ' data-i="' + i + '"') + '</div>' +
      grid([
        field('Name', inp(P + 'name', 'str', ' style="width:110px"')),
        field('Column frames (comma list)', inp(P + 'col_frames', 'str', ' style="width:150px" list="cs-frame-list"')),
        field('Shaft frames (optional)', inp(P + 'shaft_frames', 'str', ' style="width:150px" list="cs-frame-list"')),
        field('H', inp(P + 'H_ft', 'num', w) + '<span class="circ-info" id="cs-autoH-' + i + '">' + autoHText(aH) + '</span>', 'ft'),
        field('Base end', sel(P + 'base_end', ['auto', 'min', 'max'])),
        field('End cond. long', sel(P + 'end_long', ['fixed-free', 'fixed-fixed'])),
        field('End cond. trans', sel(P + 'end_trans', ['fixed-free', 'fixed-fixed']))
      ]) +
      '<div style="font-weight:600;font-size:0.78rem;">Column</div>' + grid([
        field('D', inp(P + 'col.D', 'num', w), 'in'), field("f'c", inp(P + 'col.fc', 'num', w), 'ksi'),
        field('fy', inp(P + 'col.fy', 'num', w), 'ksi'), field('Cover', inp(P + 'col.cover', 'num', w), 'in'),
        field('Transverse', sel(P + 'col.trans_type', ['hoop', 'spiral'])),
        field('Hoop closure', sel(P + 'col.hoop_closure', [['lap', 'Lap splice'], ['hooked', 'Welded / mechanical / hooked']])),
        field('&lambda;mo', inp(P + 'lambda_mo', 'num', w)),
        field('&mu;D (blank = code default)', inp(P + 'mu_d', 'num', w)),
        field('P_dead (used only if no Dead rows; kip, compression &minus;)', inp(P + 'P_dead', 'num', w) +
          '<span class="circ-info" id="cs-pdead-hint-' + i + '">' + esc(deadHint(resultBentFor(b))) + '</span>')
      ]) +
      '<div style="font-weight:600;font-size:0.78rem;">Shaft</div>' + grid([
        field('Ds', inp(P + 'shaft.D', 'num', w), 'in'), field("f'c", inp(P + 'shaft.fc', 'num', w), 'ksi'),
        field('fy', inp(P + 'shaft.fy', 'num', w), 'ksi'), field('Cover', inp(P + 'shaft.cover', 'num', w), 'in'),
        field('Transverse', sel(P + 'shaft.trans_type', ['hoop', 'spiral'])),
        field('Shaft basis', sel(P + 'shaft_basis', [['auto', 'auto'], ['soil', 'soil (p-y)'], ['cantilever', 'cantilever (L_eq)'], ['interface', 'interface only']])),
        field('<b>Pile equivalent cantilever length L_eq</b>', inp(P + 'L_eq_ft', 'num', w), 'ft'),
        field('Soil profile', sel(P + 'soil', soilOpts)),
        field('Embedded length', inp(P + 'L_embed_ft', 'num', w), 'ft')
      ]) + '<div class="circ-info">L_eq is required when the bent has no soil profile (shaft basis auto/cantilever).</div>' +
      '<div style="font-weight:600;font-size:0.78rem;">Slenderness (used only when the screen is on)</div>' + grid([
        field('Axis 2 braced', inp(P + 'slender.2.braced', 'bool')), field('K (axis 2)', inp(P + 'slender.2.K', 'num', w)),
        field('&#8467;u axis 2 (blank = H + Df)', inp(P + 'slender.2.lu_ft', 'num', w), 'ft'),
        field('Axis 3 braced', inp(P + 'slender.3.braced', 'bool')), field('K (axis 3)', inp(P + 'slender.3.K', 'num', w)),
        field('&#8467;u axis 3 (blank = H + Df)', inp(P + 'slender.3.lu_ft', 'num', w), 'ft'),
        field('&beta;d (blank = auto)', inp(P + 'slender.beta_d', 'num', w)),
        field('&gamma;p', inp(P + 'slender.gamma_p', 'num', w))
      ]) + '</div>';
    return h;
  }
  function renderBents() {
    var fl = state.parse && state.parse.frames ? state.parse.frames : [];
    var h = '<datalist id="cs-frame-list">' + fl.map(function (f) { return '<option value="' + esc(f.name) + '">'; }).join('') + '</datalist>' +
      state.bents.map(bentHtml).join('') + btn('+ Add bent', 'add-bent');
    return card('4. Bents', 'blue', h, 'cs-card-bents');
  }
  function soilHtml(p, i) {
    var P = 'soils.' + i + '.';
    var w = ' style="width:70px"';
    var h = '<div style="border:1px solid #dce1e8;border-radius:6px;padding:8px 10px;margin-bottom:10px;">' +
      grid([
        field('Profile name', inp(P + 'name', 'str', ' style="width:140px"')),
        field('J', inp(P + 'J', 'num', w)), field('Cyclic', inp(P + 'cyclic', 'bool')),
        field('Upper bound &times;', inp(P + 'bound_upper', 'num', w)), field('Lower bound &times;', inp(P + 'bound_lower', 'num', w)),
        btn('Remove profile', 'rm-soil', ' data-i="' + i + '"')
      ]) +
      '<table class="data-table"><thead><tr><th>#</th><th>Thickness (ft)</th><th>Model</th><th>&gamma; (pcf)</th><th>su top (ksf)</th>' +
      '<th>su bot (ksf)</th><th>&epsilon;50</th><th>&phi;&prime; (deg)</th><th>k (pci)</th><th>Submerged</th><th></th></tr></thead><tbody>' +
      p.layers.map(function (l, j) {
        var L = P + 'layers.' + j + '.';
        return '<tr><td>' + (j + 1) + '</td><td>' + inp(L + 'thickness_ft', 'num', w) + '</td><td>' + sel(L + 'py_model', PY_MODELS) + '</td><td>' +
          inp(L + 'gamma_pcf', 'num', w) + '</td><td>' + inp(L + 'su_top_ksf', 'num', w) + '</td><td>' + inp(L + 'su_bot_ksf', 'num', w) + '</td><td>' +
          inp(L + 'eps50', 'num', w) + '</td><td>' + inp(L + 'phi_deg', 'num', w) + '</td><td>' + inp(L + 'k_pci', 'num', w) + '</td><td>' +
          inp(L + 'submerged', 'bool') + '</td><td>' + btn('&times;', 'rm-layer', ' data-i="' + i + '" data-j="' + j + '"') + '</td></tr>';
      }).join('') + '</tbody></table>' + btn('+ Add stratum', 'add-layer', ' data-i="' + i + '"') + '</div>';
    return h;
  }
  function renderSoils() {
    var h = '<div class="circ-info">Named strata tables (top of shaft = ground surface). Each bent picks one profile and gives its embedded length. ' +
      'Blank cells use the p-y model defaults.</div>' + state.soils.map(soilHtml).join('') + btn('+ Add soil profile', 'add-soil');
    return card('5. Soil profiles', 'blue', h, 'cs-card-soils');
  }
  function renderRun() {
    var h = '<button type="button" class="calc-btn" id="cs-design" data-act="design"' + (busy ? ' disabled' : '') + '>' +
      (busy ? 'Running…' : 'Design') + '</button><div id="cs-run-status"></div>';
    return card('6. Design', 'green', h, 'cs-card-run');
  }
  function renderOverrides() {
    var w = ' style="width:56px"';
    var rows = state.bents.map(function (b, i) {
      var P = 'bents.' + i + '.override.';
      return '<tr><td id="cs-ov-name-' + i + '">' + esc(b.name) + '</td>' +
        '<td>#' + inp(P + 'col_long.bar', 'num', w) + ' n ' + inp(P + 'col_long.n', 'num', w) + ' bundle ' + inp(P + 'col_long.bundle', 'num', w) + '</td>' +
        '<td>#' + inp(P + 'col_trans.bar', 'num', w) + ' s ' + inp(P + 'col_trans.s', 'num', w) + ' ties ' + inp(P + 'col_trans.ties', 'num', w) + '</td>' +
        '<td>#' + inp(P + 'shaft_long.bar', 'num', w) + ' n ' + inp(P + 'shaft_long.n', 'num', w) + ' bundle ' + inp(P + 'shaft_long.bundle', 'num', w) + '</td>' +
        '<td>#' + inp(P + 'shaft_trans.bar', 'num', w) + ' s ' + inp(P + 'shaft_trans.s', 'num', w) + ' ties ' + inp(P + 'shaft_trans.ties', 'num', w) + '</td>' +
        '<td>' + btn('Clear override', 'clear-ov', ' data-i="' + i + '"') + '<div id="cs-ov-msg-' + i +
        '" style="color:#c0392b;font-size:0.74rem;white-space:normal;">' + esc(overrideErrors(b).join('; ')) + '</div></td></tr>';
    }).join('');
    var h = '<div class="circ-info">An override is used as entered (never "improved"); every check is re-run on it at the next Design. ' +
      'Blank = designed. Pitch s in inches.</div><table class="data-table" id="cs-overrides"><thead><tr><th>Bent</th><th>Column longitudinal</th>' +
      '<th>Column transverse</th><th>Shaft longitudinal</th><th>Shaft transverse</th><th></th></tr></thead><tbody>' + rows + '</tbody></table>';
    return card('9. Overrides', 'orange', h, 'cs-card-overrides');
  }
  function renderResults() {
    var el = document.getElementById('cs-results');
    if (!el) return;
    if (!lastResult) { el.innerHTML = ''; return; }
    var r = lastResult;
    var rows = resultRows(r);
    var gw = (r.parse && r.parse.warnings) || [];
    var h = '<div class="circ-info">Code: ' + esc(r.code) + ' · envelope mode: ' + esc(r.settings && r.settings.envelope_mode) +
      ' · slenderness: ' + (r.settings && r.settings.slenderness_on ? 'screen on' : 'off') + '. Moments in kip-ft, forces in kip. Click a row for details.</div>';
    if (r.parse && r.parse.n_envelope > 0) h += notice('amber', 'Envelope output (Max/Min): bounded conservatively — see report. All rows are envelope-bounded (conservative).');
    h += '<div style="overflow-x:auto;"><table class="data-table" id="cs-results-table"><thead><tr><th></th><th>Bent</th><th>Status</th><th>LRFD column cage</th>' +
      '<th>Seismic column transverse</th><th>Override</th><th>Final cage (source)</th><th>Mp</th><th>Mo</th><th>Vo (kip)</th>' +
      '<th>max K&#8467;u/r (&delta; status)</th><th>Shaft M demand (depth of Mmax) / Mp</th><th>Shaft V / &phi;Vn (kip)</th></tr></thead><tbody>' +
      rows.map(function (x, i) {
        return '<tr data-act="drill" data-i="' + i + '" style="cursor:pointer;' + (drillIdx === i ? 'background:#eaf2f8;' : '') + '">' +
          '<td><span title="' + esc(x.status) + '" style="display:inline-block;width:14px;height:14px;border-radius:50%;background:' + x.color + ';"></span></td>' +
          '<td>' + esc(x.name) + '</td><td style="color:' + x.color + ';font-weight:700;">' + esc(x.status) + '</td><td>' + esc(x.lrfd_col) + '</td><td>' +
          esc(x.seismic_col) + '</td><td>' + esc(x.override) + '</td><td style="white-space:normal;min-width:260px;">' + esc(x.final) + '</td><td>' + x.Mp + '</td><td>' + x.Mo +
          '</td><td>' + x.Vo + '</td><td>' + esc(x.slender) + '</td><td>' + esc(x.shaft_M) + '</td><td>' + esc(x.shaft_V) + '</td></tr>';
      }).join('') + '</tbody></table></div>';
    if (gw.length) h += '<div style="font-size:0.78rem;margin-top:6px;"><b>Warnings:</b><ul style="margin:2px 0 0 18px;">' +
      gw.map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('') + '</ul></div>';
    h += '<div id="cs-drill">' + drillHtml() + '</div>';
    el.innerHTML = card('7. Results', 'green', h);
  }
  function rowsTable(checkRows, id) {
    if (!checkRows || !checkRows.length) return '<div class="circ-info">No LRFD rows.</div>';
    var hdr = ['#', 'Case', 'Where', 'Bound', 'Pu', 'P range', 'Mu', 'Mr', 'P for flexure', 'Flexure', 'Vu', 'Vr', 'Shear',
      'Tu', 'Tr', 'Torsion', 'D/C', ''];
    return '<div style="overflow-x:auto;max-height:340px;overflow-y:auto;"><table class="data-table" id="' + id + '"><thead><tr>' +
      hdr.map(function (x) { return '<th>' + x + '</th>'; }).join('') + '</tr></thead><tbody>' +
      governingRows(checkRows).map(function (r) {
        return '<tr>' + r.cells.map(function (c, k) {
          var st = k === r.cells.length - 1 ? ' style="color:' + (c === 'OK' ? '#1e8449' : '#c0392b') + ';font-weight:700"' : '';
          return '<td' + st + '>' + esc(c) + '</td>';
        }).join('') + '</tr>';
      }).join('') + '</tbody></table></div><div class="circ-info">Pu, P range, Vu, Vr in kip; Mu, Mr, Tu, Tr in kip-ft. ' +
      '"P for flexure" = the axial load in [P_min, P_max] at which the cage\'s flexural resistance is lowest (envelope rows).</div>';
  }
  function drillHtml() {
    if (!lastResult || drillIdx === null || !lastResult.bents[drillIdx]) return '';
    var b = lastResult.bents[drillIdx], S = b.seismic, ax = b.axial || {};
    var h = '<h4 style="margin:14px 0 4px;color:#1a5276;">Bent ' + esc(b.name) + ' — <span style="color:' + statusColor(b.status) + '">' + esc(b.status) + '</span></h4>';
    if ((b.no_solution || []).length) h += notice('red', '<b>No solution:</b><ul style="margin:2px 0 0 18px;">' +
      b.no_solution.map(function (x) { return '<li>' + esc(x) + '</li>'; }).join('') + '</ul>');
    h += '<div class="circ-info">P_dead = ' + fmt(ax.P_dead, 0) + ' kip; Extreme P range ' + fmt(ax.P_ext_min, 0) + ' .. ' + fmt(ax.P_ext_max, 0) +
      ' kip; H = ' + fmt((b.H_in || 0) / 12.0, 2) + ' ft; shaft basis ' + esc(b.shaft_basis || '—') + '; Df for &#8467;u = ' +
      (isNum(b.Df_for_lu) ? fmt(b.Df_for_lu / 12.0, 2) + ' ft' : '—') + '.</div>';
    var col = b.lrfd && b.lrfd.col;
    h += '<div style="font-weight:600;margin-top:8px;">Column LRFD rows (final cage)</div>' + rowsTable(col && col.check_rows, 'cs-col-rows');
    var sh = b.lrfd && b.lrfd.shaft;
    if (sh && sh.check_rows) h += '<div style="font-weight:600;margin-top:8px;">Shaft LRFD rows (' + esc(sh.source || '') + ')</div>' + rowsTable(sh.check_rows, 'cs-shaft-rows');
    h += '<div style="font-weight:600;margin-top:8px;">Final checks</div><div style="overflow-x:auto;"><table class="data-table" id="cs-checks"><thead><tr>' +
      ['Group', 'Check', 'Demand', 'Capacity', 'Ratio', '', 'Detail', 'Reference'].map(function (x) { return '<th>' + x + '</th>'; }).join('') +
      '</tr></thead><tbody>' + (b.final_checks || []).map(function (c) {
        var cells = checkRow(c);
        cells[7] = checkRef(c);
        return '<tr>' + cells.map(function (x, k) {
          var st = k === 5 ? ' style="color:' + (x === 'OK' ? '#1e8449' : '#c0392b') + ';font-weight:700"' :
            (k >= 6 ? ' style="white-space:normal;font-family:inherit;min-width:160px;"' : '');
          return '<td' + st + '>' + esc(x) + '</td>';
        }).join('') + '</tr>';
      }).join('') + '</tbody></table></div><div class="circ-info">Shaft flexure demand/capacity in kip-ft; other check values in the check\'s own units (kip, in, ratios). Detail text from the engine may quote kip-in.</div>';
    if ((b.warnings || []).length) h += '<div style="font-size:0.78rem;margin-top:6px;"><b>Warnings:</b><ul style="margin:2px 0 0 18px;">' +
      b.warnings.map(function (w) { return '<li>' + esc(w) + '</li>'; }).join('') + '</ul></div>';
    if (S) {
      var charts = [mphiChart(S.mphi, 'Column M-φ')].concat(shaftCharts(S));
      h += '<div style="display:flex;flex-wrap:wrap;gap:10px;margin-top:10px;">' + charts.join('') + '</div>' +
        '<div class="circ-info">M-&phi;: the final column cage at the axial load that governs Mo (the bilinear idealisation dashed; Mp_by_P is listed in the report). ' +
        'Shaft diagrams: depth below the top of shaft; every soil bound for the p-y basis (governing bold, unstable bounds dashed grey and excluded).</div>';
    }
    return h;
  }

  function autoHText(aH) { return 'blank = auto' + (aH !== null ? ' (' + fmt(aH, 2) + ' ft)' : ''); }
  function resultBentFor(b) {
    if (!lastResult || !Array.isArray(lastResult.bents)) return null;
    return lastResult.bents.filter(function (x) { return x.name === b.name; })[0] || null;
  }
  function setText(id, txt) { var el = document.getElementById(id); if (el) el.textContent = txt; }
  function updateHints() {
    state.bents.forEach(function (b, i) { setText('cs-pdead-hint-' + i, deadHint(resultBentFor(b))); });
  }
  function renderSoilSelects() {
    state.bents.forEach(function (b, i) {
      var el = panel.querySelector('select[data-cs="bents.' + i + '.soil"]');
      if (!el) return;
      el.innerHTML = [['', '(none)']].concat(state.soils.map(function (q) { return [q.name, q.name]; })).map(function (o) {
        return '<option value="' + esc(o[0]) + '"' + (b.soil === o[0] ? ' selected' : '') + '>' + esc(o[1]) + '</option>';
      }).join('');
    });
  }
  // ── printable report (Task 11): reuses the Report tab's .report-preview classes and
  // print rule (body * hidden, .report-preview shown); the rules below, scoped to this
  // tab's own ids, keep the two reports from printing together and avoid clipping.
  var PRINT_CSS = [
    '#cs-report{max-width:1000px;}',
    '#cs-report h4{font-size:10pt;margin:10px 0 4px;color:#2c3e50;}',
    '#cs-report .cs-rpt-box{border:2px solid #e67e22;background:#fef5e7;padding:8px 12px;margin:10px 0 14px;font-size:9pt;}',
    '#cs-report .cs-rpt-list{margin:4px 0 4px 18px;padding:0;font-size:9pt;}',
    '#cs-report .rpt-table th,#cs-report .rpt-table td{white-space:normal;overflow-wrap:break-word;}',
    '#cs-report .rpt-table td.rpt-pass,#cs-report .rpt-table td.rpt-fail{white-space:nowrap;}',
    '#cs-report .cs-rpt-checks td:nth-child(n+7){text-align:left;font-family:inherit;}',
    '#cs-report .cs-rpt-charts{display:flex;flex-wrap:wrap;gap:8px;margin:8px 0;}',
    '#cs-report svg{max-width:100%;height:auto;}',
    '@media print{',
    'body:has(#cs-report.cs-printing) #reportPreview{display:none !important;}',
    'body:not(:has(#cs-report.cs-printing)) #cs-report{display:none !important;}',
    '#cs-report{font-size:8.5pt;}',
    '#cs-report .rpt-table{font-size:7pt;table-layout:auto;}',
    '#cs-report .rpt-table th,#cs-report .rpt-table td{padding:2px 3px;}',
    '#cs-report .rpt-table tr{page-break-inside:avoid;}',
    '#cs-report .cs-rpt-break{page-break-before:always;break-before:page;}',
    '#cs-report .cs-rpt-charts svg{width:48%;}',
    '#cs-report .cs-rpt-box,#cs-report .rpt-eq,#cs-report .rpt-table th{-webkit-print-color-adjust:exact;print-color-adjust:exact;}',
    '}'
  ].join(' ');
  function injectPrintCss() {
    if (document.getElementById('cs-print-style')) return;
    var st = document.createElement('style');
    st.id = 'cs-print-style';
    st.textContent = PRINT_CSS;
    (document.head || document.documentElement).appendChild(st);
  }
  function today() {
    var d = new Date();
    var p2 = function (x) { return (x < 10 ? '0' : '') + x; };
    return d.getFullYear() + '-' + p2(d.getMonth() + 1) + '-' + p2(d.getDate());
  }
  function reportBody() {
    return reportHtml(lastResult, lastPayload, { project: state.report && state.report.project, date: today() });
  }
  function renderReportCard() {
    var h = '<div class="circ-info">Per bent: inputs, parse summary, LRFD rows, slenderness, M-&phi;, Mo/Vo, column seismic shear, shaft, ' +
      'all checks and the final cage. Seismic references are the ported ones ' + esc(UNVERIFIED_SUFFIX) + '.</div>' +
      grid([field('Project', inp('report.project', 'str', ' id="cs-rpt-project" style="width:220px"')),
        '<button type="button" class="calc-btn" id="cs-rpt-gen" data-act="report">Generate report</button>',
        '<button type="button" class="calc-btn" id="cs-rpt-print" data-act="print" style="background:linear-gradient(135deg,#2980b9,#3498db);">Print report</button>']) +
      '<div id="cs-rpt-msg"></div><div id="cs-report" class="report-preview cs-report" style="' + (reportShown && lastResult ? '' : 'display:none;') +
      'margin-top:12px;">' + (reportShown && lastResult ? reportBody() : '') + '</div>';
    return card('8. Printable report', 'purple', h, 'cs-card-report');
  }
  function showReport() {
    var el = document.getElementById('cs-report');
    if (!lastResult) {
      var m = document.getElementById('cs-rpt-msg');
      if (m) m.innerHTML = notice('red', 'Run Design first: the report is built from the last results.');
      return null;
    }
    setText('cs-rpt-msg', '');
    reportShown = true;
    if (el) { el.innerHTML = reportBody(); el.style.display = ''; }
    return el;
  }
  function printReportCs() {
    var el = showReport();
    if (!el) return;
    el.classList.add('cs-printing');
    var off = function () { el.classList.remove('cs-printing'); window.removeEventListener('afterprint', off); };
    window.addEventListener('afterprint', off);
    window.print();
  }
  function renderAll() {
    panel.innerHTML = '<div style="padding:4px 0;">' + renderPaste() + renderCases() + renderSettings() + renderBents() + renderSoils() +
      renderRun() + '<div id="cs-results"></div>' + renderReportCard() + renderOverrides() + '</div>';
    renderResults();
  }
  function setRunStatus(html) { var el = document.getElementById('cs-run-status'); if (el) el.innerHTML = html; }

  // ── actions ──
  function doParse() {
    var ta = document.getElementById('cs-paste');
    if (ta) state.paste = ta.value;
    var a = bridge();
    if (!a || !a.parse_csi) { alert('Python backend not available (pywebview.api.parse_csi).'); return; }
    a.parse_csi(JSON.stringify({ paste: state.paste, units: state.units })).then(function (res) {
      var r;
      try { r = JSON.parse(res); } catch (e) { alert('Parse error: ' + e.message); return; }
      if (r.error) {
        state.parse = null;
        renderAll();
        var s = document.getElementById('cs-parse-summary');
        if (s) s.innerHTML = notice('red', '<b>Parse failed:</b> ' + esc(r.error));
        return;
      }
      state.parse = r;
      state.categories = mergeCategories(state.categories, r.cases);
      markDirty();
      renderAll();
    }, function (e) {
      var sm = document.getElementById('cs-parse-summary');
      if (sm) sm.innerHTML = notice('red', '<b>Parse failed:</b> ' + esc(String(e)));
    });
  }
  function doDesign() {
    if (busy) return;
    var ta = document.getElementById('cs-paste');
    if (ta) state.paste = ta.value;
    var errs = validateState(state);
    if (errs.length) {
      setRunStatus(notice('red', '<b>Fix before Design:</b><ul style="margin:2px 0 0 18px;">' + errs.map(function (e) { return '<li>' + esc(e) + '</li>'; }).join('') + '</ul>'));
      return;
    }
    var a = bridge();
    if (!a || !a.run_colshaft) { setRunStatus(notice('red', 'Python backend not available (pywebview.api.run_colshaft).')); return; }
    busy = true;
    var sent = buildPayload(state);
    var b = document.getElementById('cs-design');
    if (b) { b.disabled = true; b.textContent = 'Running…'; }
    setRunStatus('<div class="circ-info">Running the design (this can take several seconds per bent)…</div>');
    var done = function (res) {
      busy = false;
      var bt = document.getElementById('cs-design');
      if (bt) { bt.disabled = false; bt.textContent = 'Design'; }
      var r;
      try { r = JSON.parse(res); } catch (e) { setRunStatus(notice('red', '<b>Error:</b> ' + esc(e.message))); return; }
      if (r.error) { setRunStatus(notice('red', '<b>Error:</b> ' + esc(r.error))); return; }
      lastResult = r;
      lastPayload = sent;
      drillIdx = r.bents && r.bents.length ? 0 : null;
      updateHints();
      setRunStatus('<div class="circ-info">Done: ' + (r.bents || []).length + ' bent(s), overall ' +
        esc(worstStatus((r.bents || []).map(function (x) { return x.status; }))) + '.</div>');
      renderResults();
      if (reportShown) showReport();
    };
    a.run_colshaft(JSON.stringify(sent)).then(done, function (e) { done(JSON.stringify({ error: String(e) })); });
  }
  function onClick(ev) {
    var t = ev.target.closest ? ev.target.closest('[data-act]') : null;
    if (!t || !panel.contains(t)) return;
    var act = t.getAttribute('data-act'), i = Number(t.getAttribute('data-i')), j = Number(t.getAttribute('data-j'));
    var structural = true;
    if (act === 'parse') { doParse(); return; }
    if (act === 'design') { doDesign(); return; }
    if (act === 'drill') { drillIdx = i; renderResults(); return; }
    if (act === 'report') { showReport(); return; }
    if (act === 'print') { printReportCs(); return; }
    if (act === 'add-bent') state.bents.push(defaultBent(state.bents.length));
    else if (act === 'rm-bent') state.bents.splice(i, 1);
    else if (act === 'add-soil') state.soils.push(defaultSoil(state.soils.length));
    else if (act === 'rm-soil') {
      var nm = state.soils[i] && state.soils[i].name;
      state.soils.splice(i, 1);
      state.bents.forEach(function (b) { if (b.soil === nm) b.soil = ''; });
    } else if (act === 'add-layer') state.soils[i].layers.push(defaultLayer());
    else if (act === 'rm-layer') state.soils[i].layers.splice(j, 1);
    else if (act === 'clear-ov') state.bents[i].override = emptyOverride();
    else structural = false;
    if (structural) { markDirty(); renderAll(); }
  }
  function onChange(ev) {
    var el = ev.target;
    if (!panel.contains(el)) return;
    var cat = el.getAttribute('data-cat');
    if (cat !== null) { state.categories[cat] = el.value; markDirty(); return; }
    var path = el.getAttribute('data-cs');
    if (!path) return;
    var t = el.getAttribute('data-t');
    var old = getPath(state, path);
    var v = t === 'bool' ? !!el.checked : t === 'num' ? (el.value === '' ? '' : num(el.value)) : el.value;
    if (t === 'num' && v === null) v = '';
    setPath(state, path, v);
    markDirty();
    // a renamed soil profile keeps the bents that point at it
    var m = /^soils\.(\d+)\.name$/.exec(path);
    // targeted updates only (a full re-render would drop the focus the user just moved)
    if (m) {
      state.bents.forEach(function (b) { if (b.soil === old) b.soil = v; });
      renderSoilSelects();
    }
    var mb = /^bents\.(\d+)\.(col_frames|name|override\..*)$/.exec(path);
    if (mb) {
      var bi = Number(mb[1]), bb = state.bents[bi];
      if (mb[2] === 'name') { setText('cs-ov-name-' + bi, bb.name); setText('cs-pdead-hint-' + bi, deadHint(resultBentFor(bb))); }
      else if (mb[2] === 'col_frames') setText('cs-autoH-' + bi, autoHText(autoHeightFt(state, bb)));
      else setText('cs-ov-msg-' + bi, overrideErrors(bb).join('; '));
    }
  }
  panel.addEventListener('click', onClick);
  // keep this tab's edits away from the app's document-level change/input
  // listeners (they trigger the main section's auto-calculate)
  panel.addEventListener('change', function (ev) { onChange(ev); ev.stopPropagation(); });
  panel.addEventListener('input', function (ev) { ev.stopPropagation(); });

  injectPrintCss();
  window.ColShaft = {
    getState: function () { var ta = document.getElementById('cs-paste'); if (ta) state.paste = ta.value; return serializeState(state); },
    setState: function (obj) {
      // never let a malformed columnShaft abort the main project load
      lastResult = null; lastPayload = null; reportShown = false; drillIdx = null;
      try { state = normalizeState(obj); renderAll(); } catch (e) {
        try { console.warn('Column on Shaft: invalid saved state, tab reset (' + e + ')'); } catch (e2) { /* ignore */ }
        try { state = defaultState(); renderAll(); } catch (e3) { /* ignore */ }
      }
    }
  };
  renderAll();
})();
