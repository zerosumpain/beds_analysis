/* Connected data: a visitor's own Stat-Xplore API key, kept in their browser only.
   With a key, Universal Credit by conditionality (DWP Stat-Xplore) is fetched live from
   the browser (Stat-Xplore allows cross-origin calls) and appears as the dwp_uc dataset.
   The key is never sent to this site's server. Port of pipeline/fetch_dwp_uc.py. */
(function () {
  'use strict';
  const BA = window.BA;
  const esc = BA.esc;
  const KEY = 'ba-statxplore-key', CACHE = 'ba-statxplore-cache', TTL = 12 * 3600 * 1000;
  const BASE = 'https://stat-xplore.dwp.gov.uk/webapi/rest/v1';
  const DB = 'str:database:UC_Monthly';
  const MEASURE = 'str:count:UC_Monthly:V_F_UC_CASELOAD_FULL';
  const F_MONTH = 'str:field:UC_Monthly:F_UC_DATE:DATE_NAME';
  const F_GEO = 'str:field:UC_Monthly:V_F_UC_CASELOAD_FULL:COA_CODE';
  const F_COND = 'str:field:UC_Monthly:V_F_UC_CASELOAD_FULL:CCCONDITIONALITY_REGIME';
  const VS = 'str:valueset:UC_Monthly:V_F_UC_CASELOAD_FULL:COA_CODE:V_C_MASTERGEOG21_';
  const VALUESETS = { la: VS + 'LA_TO_REGION', region: VS + 'REGION_TO_COUNTRY', country: VS + 'COUNTRY_TO_GB', lsoa: VS + 'LSOA_TO_MSOA', msoa: VS + 'MSOA_TO_LA' };
  const VALUESET_LABELS = { la: /local authorit/, region: /^region/, country: /^country/, lsoa: /lower layer|\blsoa\b/, msoa: /middle layer|\bmsoa\b/ };
  const COND = {
    'searching for work': 'uc_searching', 'working - with requirements': 'uc_working_req', 'no work requirements': 'uc_nwr',
    'planning for work': 'uc_planning_preparing', 'preparing for work': 'uc_planning_preparing', 'working - no requirements': 'uc_working_noreq',
  };
  const IND_ORDER = ['uc_people', 'uc_searching', 'uc_working_req', 'uc_nwr', 'uc_planning_preparing', 'uc_working_noreq'];
  const COH = '25+ inactive, 18-24';
  const INDICATORS = [
    { id: 'uc_people', label: 'People on Universal Credit', unit: 'count', cohort: COH, polarity: 'neutral', description: 'All people on UC on the count date (all conditionality regimes incl. unknown/missing).' },
    { id: 'uc_searching', label: 'UC: Searching for work', unit: 'count', cohort: COH, polarity: 'higher_is_worse', description: 'Not working or very low earnings; required to look for work (the UC part of the claimant count).' },
    { id: 'uc_working_req', label: 'UC: Working - with requirements', unit: 'count', cohort: COH, polarity: 'neutral', description: 'In work but could earn more, or not working with a low-earning partner.' },
    { id: 'uc_nwr', label: 'UC: No work requirements', unit: 'count', cohort: COH, polarity: 'higher_is_worse', description: "Not expected to work at present (mainly limited capability for work-related activity on health grounds, carers, child under 1, students, over state pension age) - the 'economically inactive on UC' pool." },
    { id: 'uc_planning_preparing', label: 'UC: Planning for work + Preparing for work', unit: 'count', cohort: COH, polarity: 'neutral', description: 'Expected to work in future: lone parent/lead carer of a child aged 1 (planning) or aged 2, or limited capability for work (preparing).' },
    { id: 'uc_working_noreq', label: 'UC: Working - no requirements', unit: 'count', cohort: COH, polarity: 'neutral', description: 'Individual or household earnings above the conditionality threshold.' },
    { id: 'uc_nwr_rate', label: 'UC no work requirements per 100 residents aged 16-64', unit: 'rate', cohort: COH, polarity: 'higher_is_worse', description: 'uc_nwr / ONS population aged 16-64 x 100 (nearest mid-year estimate at or before the month). Numerator includes some people aged 65+.' },
  ];
  const META = {
    id: 'dwp_uc', title: 'People on Universal Credit by conditionality regime', publisher: 'Department for Work and Pensions (Stat-Xplore)',
    source_url: 'https://stat-xplore.dwp.gov.uk/', geography: 'LA, region, England, county (24 months); LSOA21 (latest month)',
    cohort: COH, frequency: 'Monthly', next_update: 'Monthly (DWP UC statistics, usually second Tuesday of the month)', access: 'API',
    licence: 'Open Government Licence v3.0', indicators: INDICATORS, live: true,
    quality: 'Official statistics from DWP\'s UC administrative system; latest month is provisional. Fetched live in your browser with your own Stat-Xplore API key; rates use ONS population aged 16-64.',
    limitations: 'Stat-Xplore perturbs cells for disclosure control, so small LSOA cells are noisy and parts may not sum to totals. \'No work requirements\' mixes health-related limited capability for work, carers, parents of under-1s, students and people over state pension age: a proxy for the inactive-on-benefit pool, not capacity to work. Legacy benefits (ESA, income support, JSA) are excluded.',
  };

  /* ---------- key storage (this browser only) ---------- */
  const ls = {
    get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: (k, v) => { try { localStorage.setItem(k, v); return true; } catch (e) { return false; } },
    del: (k) => { try { localStorage.removeItem(k); } catch (e) { /* ignore */ } },
  };
  BA.SX = {
    key: () => (ls.get(KEY) || '').trim() || null,
    lastError: null,
  };

  /* ---------- API ---------- */
  async function call(key, path, body) {
    let r;
    try {
      r = await fetch(BASE + path, {
        method: body ? 'POST' : 'GET', credentials: 'omit', referrerPolicy: 'no-referrer',
        headers: Object.assign({ APIKey: key, Accept: 'application/json' }, body ? { 'Content-Type': 'application/json' } : {}),
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (e) { throw new Error('Could not reach Stat-Xplore (network error or blocked by the browser).'); }
    if (r.status === 401 || r.status === 403) throw new Error('Stat-Xplore rejected the API key (HTTP ' + r.status + '). Check it was copied in full.');
    if (r.status === 429) throw new Error('Stat-Xplore rate limit reached for this key. Try again in an hour.');
    if (!r.ok) throw Object.assign(new Error('Stat-Xplore returned HTTP ' + r.status + ' for ' + path), { status: r.status });
    return r.json();
  }
  async function discoverValuesets(key) {
    const doc = await call(key, '/schema/' + encodeURIComponent(F_GEO));
    const found = Object.assign({}, VALUESETS), hit = new Set();
    (doc.children || []).forEach((k) => {
      const lab = String(k.label || '').toLowerCase();
      Object.entries(VALUESET_LABELS).forEach(([lvl, rx]) => {
        if (!hit.has(lvl) && rx.test(lab) && String(k.id || '').startsWith('str:valueset:')) { found[lvl] = k.id; hit.add(lvl); }
      });
    });
    return found;
  }
  const valueId = (vs, code) => vs.replace('str:valueset:', 'str:value:') + ':' + code;
  const laQuery = (vs) => ({
    database: DB, measures: [MEASURE],
    recodes: {
      [F_GEO]: { map: Object.keys(BA.LAS).map((c) => [valueId(vs.la, c)]).concat([[valueId(vs.region, 'E12000006')], [valueId(vs.country, 'E92000001')]]), total: false },
      [F_COND]: { total: true }, [F_MONTH]: { total: false },
    },
    dimensions: [[F_GEO], [F_MONTH], [F_COND]],
  });
  const smallQuery = (vs, level, codes, monthUri) => ({
    database: DB, measures: [MEASURE],
    recodes: { [F_GEO]: { map: codes.map((c) => [valueId(vs[level], c)]), total: false }, [F_MONTH]: { map: [[monthUri]], total: false }, [F_COND]: { total: true } },
    dimensions: [[F_GEO], [F_MONTH], [F_COND]],
  });

  /* ---------- parsing (same logic as the unit-tested Python) ---------- */
  const isTotal = (it) => String(it.type || '').toLowerCase() === 'total' || !(it.uris && it.uris.length) || ((it.labels || []).length === 1 && it.labels[0] === 'Total');
  function parseTable(resp) {
    let cube = resp.cubes;
    if (Array.isArray(cube)) { cube = cube[0]; if (cube && cube[MEASURE]) cube = cube[MEASURE]; } else cube = cube[MEASURE] || Object.values(cube)[0];
    const axes = resp.fields.map((f) => f.items.map((it) => [(it.labels || []).join(' + '), isTotal(it) ? null : it.uris[0]]));
    const out = [];
    (function walk(v, d, picked) {
      if (d === axes.length) { out.push({ value: v == null ? null : +v, items: picked }); return; }
      if (v.length !== axes[d].length) throw new Error('Unexpected Stat-Xplore response shape');
      v.forEach((sub, i) => walk(sub, d + 1, picked.concat([axes[d][i]])));
    })(cube.values, 0, []);
    return out;
  }
  const codeOf = (uri) => uri.split(':').pop();
  const condInd = (label) => COND[label.trim().toLowerCase().replace(/\s*[-–—]\s*/g, ' - ')] || 'uc_cond_unknown';
  function tabulate(cells) {
    const out = new Map();
    cells.forEach((c) => {
      const [[, geoUri], [mLabel, mUri], [cLabel, cUri]] = c.items;
      if (!mUri) return;
      const k = [geoUri ? codeOf(geoUri) : 'GB', codeOf(mUri), mLabel].join('|');
      const d = out.get(k) || {}; out.set(k, d);
      const ind = cUri ? condInd(cLabel) : 'uc_people';
      if (c.value == null) { if (!(ind in d)) d[ind] = null; } else d[ind] = d[ind] == null ? c.value : d[ind] + c.value;
    });
    return out;
  }

  /* ---------- rows ---------- */
  async function loadPop() {
    const pop = {};
    const add = (ds, ind, levels) => (ds ? ds.rows : []).forEach((r) => {
      if (r.indicator === ind && r.value && (!levels || levels.includes(r.level))) { const y = +String(r.period).slice(-4); (pop[r.code] = pop[r.code] || {})[y] = r.value; }
    });
    const [mye, lsoa] = await Promise.all([BA.json('data/pop_mye.json').catch(() => null), BA.json('data/pop_lsoa.json').catch(() => null)]);
    add(mye, 'pop_mye_16_64'); add(lsoa, 'popsa_16_64', ['LSOA', 'MSOA']);
    return (code, year) => {
      const ys = Object.keys(pop[code] || {}).map(Number).sort((a, b) => a - b);
      if (!ys.length) return null;
      const le = ys.filter((y) => y <= year);
      return pop[code][le.length ? le[le.length - 1] : ys[0]];
    };
  }
  function geoOf(code) {
    if (BA.LAS[code]) return { code, name: BA.LAS[code], level: 'LA' };
    if (code === 'E12000006') return { code, name: 'East of England', level: 'region' };
    if (code === 'E92000001') return { code, name: 'England', level: 'country' };
    if (code === 'BEDS') return { code, name: 'Bedfordshire (3 UAs)', level: 'county' };
    const l = BA.lsoaLookup[code];
    if (l) return { code, name: l.name, level: 'LSOA', la: l.la };
    const m = Object.values(BA.lsoaLookup).find((v) => v.msoa === code);
    return m ? { code, name: code, level: 'MSOA', la: m.la } : null;
  }
  const row = (g, ind, value, period, extra) => Object.assign({ code: g.code, name: g.name, level: g.level, indicator: ind, value, period, breakdown: null },
    g.la ? { la: g.la } : {}, value == null ? { suppressed: true } : {}, extra || {});
  function emit(rows, g, d, month, label, popFor, series) {
    IND_ORDER.forEach((ind) => { if (ind in d) rows.push(row(g, ind, d[ind], label, series ? { series } : null)); });
    const n = d.uc_nwr, den = popFor(g.code, +month.slice(0, 4));
    if (n != null && den) rows.push(row(g, 'uc_nwr_rate', Math.round(10000 * n / den) / 100, label, Object.assign({ num: n, den }, series ? { series } : {})));
  }

  async function fetchLive(key) {
    const vs = await discoverValuesets(key);
    const laTab = tabulate(parseTable(await call(key, '/table', laQuery(vs))));
    const months = [...new Set([...laTab.keys()].map((k) => k.split('|').slice(1).join('|')))].sort().slice(-24);
    if (!months.length) throw new Error('Stat-Xplore returned no months');
    const keep = new Set(months.map((m) => m.split('|')[0]));
    const [latestCode, latestLabel] = months[months.length - 1].split('|');
    const monthUri = 'str:value:UC_Monthly:F_UC_DATE:DATE_NAME:C_UC_DATE:' + latestCode;
    let small, smallLevel = 'LSOA21';
    try { small = tabulate(parseTable(await call(key, '/table', smallQuery(vs, 'lsoa', Object.keys(BA.lsoaLookup).sort(), monthUri)))); } catch (e) {
      if (!e.status) throw e;
      smallLevel = 'MSOA21';
      small = tabulate(parseTable(await call(key, '/table', smallQuery(vs, 'msoa', [...new Set(Object.values(BA.lsoaLookup).map((v) => v.msoa))].sort(), monthUri))));
    }
    const popFor = await loadPop();
    const rows = [], beds = new Map();
    [...laTab.entries()].sort().forEach(([k, d]) => {
      const [g, m, lab] = k.split('|');
      if (!keep.has(m) || g === 'GB') return;
      emit(rows, geoOf(g), d, m, lab, popFor, 'monthly');
      if (BA.LAS[g]) {
        const b = beds.get(m + '|' + lab) || {}; beds.set(m + '|' + lab, b);
        IND_ORDER.forEach((ind) => { if (ind in d) b[ind] = d[ind] == null || b[ind] === null ? null : (b[ind] || 0) + d[ind]; });
      }
    });
    [...beds.entries()].sort().forEach(([k, d]) => { const [m, lab] = k.split('|'); emit(rows, geoOf('BEDS'), d, m, lab, popFor, 'monthly'); });
    small.forEach((d, k) => { const [g, m, lab] = k.split('|'); const geo = g !== 'GB' && geoOf(g); if (geo) emit(rows, geo, d, m, lab, popFor, null); });
    return { latest: latestLabel, smallLevel, rows, at: new Date().toISOString() };
  }

  // Cache the live pull in this browser for 12 hours (keyed to the key, never storing it in clear).
  const keyTag = (k) => k.length + ':' + k.slice(-4);
  async function liveDataset(force) {
    const key = BA.SX.key();
    if (!key) throw new Error('No Stat-Xplore key saved');
    let c = null;
    if (!force) { try { c = JSON.parse(ls.get(CACHE) || 'null'); } catch (e) { c = null; } }
    if (!c || c.tag !== keyTag(key) || Date.now() - Date.parse(c.at) > TTL) {
      c = Object.assign(await fetchLive(key), { tag: keyTag(key) });
      ls.set(CACHE, JSON.stringify(c));
    }
    BA.SX.lastError = null;
    const meta = Object.assign({}, META, { period: c.latest, latest_period: c.latest, retrieved_at: c.at.slice(0, 16) + 'Z', row_count: c.rows.length,
      geography: 'LA, region, England, county (24 months); ' + c.smallLevel + ' (latest month)', api_url: BASE + '/table (POST, from your browser)' });
    return { meta, rows: c.rows };
  }

  // Register the dataset when a key is saved. If the live pull fails, the page still
  // renders: the dataset comes back empty and the error is shown on the API keys page.
  function register() {
    if (!BA.SX.key()) return;
    BA.providers.dwp_uc = () => liveDataset(false).catch((e) => { BA.SX.lastError = e.message; return { meta: META, rows: [] }; });
    BA.catalogue = BA.catalogue.filter((m) => m.id !== 'dwp_uc');
    BA.catalogue.push(Object.assign({}, META, { period: 'Live', latest_period: 'Live from Stat-Xplore' }));
    INDICATORS.forEach((ind) => { BA.indicators[ind.id] = Object.assign({ dataset: 'dwp_uc', datasetTitle: META.title, levels: META.geography }, ind); });
  }
  function unregister() {
    delete BA.providers.dwp_uc; BA.forget('dwp_uc');
    if (BA._publishedUC) { BA.catalogue = BA.catalogue.filter((m) => m.id !== 'dwp_uc').concat([BA._publishedUC]); return; }
    BA.catalogue = BA.catalogue.filter((m) => m.id !== 'dwp_uc');
    INDICATORS.forEach((ind) => delete BA.indicators[ind.id]);
  }
  const init = BA.init;
  BA.init = async function () {
    await init();
    BA._publishedUC = BA.meta('dwp_uc') || null;
    register();
  };

  /* ---------- page ---------- */
  BA.route(/^\/connect$/, async (app) => {
    const key = BA.SX.key();
    let cached = null; try { cached = JSON.parse(ls.get(CACHE) || 'null'); } catch (e) { /* ignore */ }
    app.innerHTML = `
      <span class="govuk-caption-xl">Settings</span>
      <h1 class="govuk-heading-xl">API keys</h1>
      <p class="govuk-body-l">Some sources need a free personal API key. Add yours here and this site will fetch that data for you, live.</p>
      <h2 class="govuk-heading-l">DWP Stat-Xplore</h2>
      <p class="govuk-body">Adds <strong>people on Universal Credit by conditionality regime</strong>: monthly for the three authorities, East of England and England over two years, and by neighbourhood for the latest month. The <em>no work requirements</em> group is the best published proxy for people out of work on health or caring grounds, so it fills part of the gap on the <a class="govuk-link" href="#/cohort/25-inactive">inactive 25+</a> cohort.</p>
      <div id="sx-status">${key ? statusHTML(key, cached) : ''}</div>
      <div class="govuk-form-group" id="sx-group">
        <label class="govuk-label govuk-label--s" for="sx-key">${key ? 'Replace your API key' : 'Your API key'}</label>
        <div class="govuk-hint" id="sx-hint">Paste the key from your Stat-Xplore account page.</div>
        <p class="govuk-error-message" id="sx-err" hidden></p>
        <input class="govuk-input govuk-!-width-two-thirds" id="sx-key" type="password" autocomplete="off" spellcheck="false" aria-describedby="sx-hint">
      </div>
      <div class="govuk-button-group">
        <button class="govuk-button" id="sx-save" type="button">Save and test key</button>
        ${key ? '<button class="govuk-button govuk-button--secondary" id="sx-refresh" type="button">Refresh the data now</button><button class="govuk-button govuk-button--warning" id="sx-remove" type="button">Remove key</button>' : ''}
      </div>
      <details class="govuk-details"><summary class="govuk-details__summary"><span class="govuk-details__summary-text">How to get a free key</span></summary>
        <div class="govuk-details__text"><ol class="govuk-list govuk-list--number">
          <li>Register at ${BA.link('https://stat-xplore.dwp.gov.uk/', 'stat-xplore.dwp.gov.uk')} (free, about two minutes).</li>
          <li>Sign in, open <strong>Account</strong> (top right), then <strong>Open Data API Access</strong>.</li>
          <li>Copy the key and paste it above.</li></ol></div></details>
      <div class="govuk-inset-text"><strong>Where your key goes.</strong> It is saved only in this browser on this device and is sent only to DWP (stat-xplore.dwp.gov.uk), directly from your browser. It never reaches this site's server and is not in any link or download. Other visitors do not see your data or your key: each person adds their own. Remove it at any time with the button above or by clearing this site's data in your browser.</div>`;
    const err = (msg) => {
      const e = document.getElementById('sx-err'), g = document.getElementById('sx-group');
      e.hidden = !msg; e.innerHTML = msg ? '<span class="govuk-visually-hidden">Error:</span> ' + esc(msg) : '';
      g.classList.toggle('govuk-form-group--error', !!msg); document.getElementById('sx-key').classList.toggle('govuk-input--error', !!msg);
    };
    const run = async (btn, k, label) => {
      const st = document.getElementById('sx-status');
      btn.disabled = true; st.innerHTML = `<div class="govuk-inset-text" role="status">${esc(label)}&hellip; this can take up to a minute.</div>`;
      try {
        ls.set(KEY, k); ls.del(CACHE); unregister(); register();
        const ds = await liveDataset(true);
        BA.forget('dwp_uc');
        st.innerHTML = statusHTML(k, JSON.parse(ls.get(CACHE) || 'null') || { latest: ds.meta.latest_period, at: ds.meta.retrieved_at, rows: ds.rows });
        return true;
      } catch (e) {
        st.innerHTML = '';
        return e.message;
      } finally { btn.disabled = false; }
    };
    document.getElementById('sx-save').addEventListener('click', async (ev) => {
      const k = document.getElementById('sx-key').value.trim();
      if (!k) return err('Enter your Stat-Xplore API key');
      if (!/^[\w.\-+/=]{16,}$/.test(k)) return err('That does not look like an API key. Copy the whole key from your Stat-Xplore account page.');
      err('');
      const prev = BA.SX.key();
      const ok = await run(ev.currentTarget, k, 'Testing the key with Stat-Xplore');
      if (ok === true) { BA.go(); return; }
      if (prev) ls.set(KEY, prev); else ls.del(KEY);
      unregister(); register();
      err(ok + (prev ? ' Your previous key has been kept.' : ' The key was not saved.'));
    });
    const rf = document.getElementById('sx-refresh');
    if (rf) rf.addEventListener('click', async (ev) => { const ok = await run(ev.currentTarget, key, 'Fetching the latest data'); if (ok !== true) err(ok); });
    const rm = document.getElementById('sx-remove');
    if (rm) rm.addEventListener('click', () => { ls.del(KEY); ls.del(CACHE); unregister(); BA.go(); });
  });
  function statusHTML(key, c) {
    const n = c && c.rows ? c.rows.length : 0;
    const bad = BA.SX.lastError;
    return `<div class="govuk-notification-banner${bad ? '' : ' govuk-notification-banner--success'}" role="region" aria-labelledby="sx-banner"><div class="govuk-notification-banner__header"><h3 class="govuk-notification-banner__title" id="sx-banner">${bad ? 'Key saved, but the last fetch failed' : 'Connected'}</h3></div><div class="govuk-notification-banner__content">
      <p class="govuk-body">Key ending <strong>${esc(key.slice(-4))}</strong> is saved in this browser.${c && c.at ? ` Data for <strong>${esc(c.latest)}</strong> fetched ${esc(String(c.at).slice(0, 16).replace('T', ' '))} (${BA.big(n)} figures). It refreshes automatically every 12 hours.` : ''}</p>
      ${bad ? `<p class="govuk-body">${esc(bad)}</p>` : `<p class="govuk-body">See it on the <a class="govuk-link" href="#/cohort/25-inactive?ds=dwp_uc">inactive 25+ page</a>, the <a class="govuk-link" href="#/data/dwp_uc">dataset page</a> or the <a class="govuk-link" href="#/explore">map</a>.</p>`}
    </div></div>`;
  }
})();
