/* Labour balance: who could realistically fill the resort's local jobs.
   Joins cohort sizes, small-area travel times to the site and the engine's conversion
   assumptions into one chain: in cohort → can reach → engaged → trained → into work. */
(function () {
  'use strict';
  const BA = window.BA;
  const esc = BA.esc;

  // LSOA counts used to share each engine cohort across neighbourhoods.
  BA.REACH_WEIGHTS = {
    leavers: ['popsa_16_19'], neet: ['popsa_16_19'], cc1824: ['cc_16_24'], inact1824: ['popsa_18_24'],
    cc25: ['cc_25_49', 'cc_50plus'], inact25: ['census_inactive_home', 'census_inactive_ltsick', 'census_inactive_other'],
  };
  BA.REACH_DEFAULT = { mode: 'mixed', minutes: 45, late: false };
  BA.REACH_MODES = { mixed: 'Car if the household has one, otherwise public transport or cycling', pt: 'Public transport only', noncar: 'Public transport or cycling', car: 'Car' };

  let travelCache = null;
  // {lsoa: {pt, car, cycle, late, nocar}} or null when the travel dataset is absent.
  BA.travelLsoa = async function () {
    if (travelCache) return travelCache;
    if (!BA.has('travel_lsoa')) return null;
    const ds = await BA.dataset('travel_lsoa');
    const pick = (id) => { const rows = ds.rows.filter((r) => r.indicator === id && r.level === 'LSOA' && !r.breakdown); const lp = BA.latestPeriod(rows); const o = {}; rows.forEach((r) => { if (r.period === lp) o[r.code] = r.value; }); return o; };
    const pt = pick('tt_pt_am_min'), car = pick('tt_car_min'), cycle = pick('tt_cycle_min'), late = pick('tt_pt_late_min');
    let nocar = {};
    if (BA.indicators.cb_hh_nocar_pct) {
      const rows = await BA.rowsFor('cb_hh_nocar_pct', { level: 'LSOA' });
      rows.filter((r) => !r.breakdown).forEach((r) => (nocar[r.code] = r.value));
    }
    const out = {};
    Object.keys(BA.lsoaLookup || {}).concat(Object.keys(pt)).forEach((c) => {
      if (out[c]) return;
      out[c] = { pt: pt[c] ?? null, car: car[c] ?? null, cycle: cycle[c] ?? null, late: late[c] ?? null, nocar: nocar[c] ?? null };
    });
    travelCache = out;
    return out;
  };
  // Share (0-1) of an LSOA's residents who can reach a shift under opts.
  BA.reachFrac = function (t, opts) {
    if (!t) return null;
    const T = opts.minutes;
    const ptOK = t.pt != null && t.pt <= T && (!opts.late || t.late != null);
    const cyOK = t.cycle != null && t.cycle <= T;
    const carOK = t.car != null && t.car <= T;
    if (opts.mode === 'pt') return ptOK ? 1 : 0;
    if (opts.mode === 'car') return carOK ? 1 : 0;
    if (opts.mode === 'noncar') return ptOK || cyOK ? 1 : 0;
    const nc = t.nocar == null ? 0.25 : t.nocar / 100; // households without a car
    return (1 - nc) * (carOK ? 1 : 0) + nc * (ptOK || cyOK ? 1 : 0);
  };
  async function lsoaWeights(ids) {
    const w = {};
    for (const id of ids) {
      if (!BA.indicators[id]) continue;
      const rows = (await BA.rowsFor(id, { level: 'LSOA' })).filter((r) => !r.breakdown);
      const lp = BA.latestPeriod(rows);
      rows.forEach((r) => { if (r.period === lp && r.value != null) w[r.code] = (w[r.code] || 0) + r.value; });
    }
    return w;
  }
  BA.lsoaWeights = lsoaWeights;
  // {poolId: {share, note}} — population-weighted share of each cohort that can reach the site.
  BA.reachShares = async function (opts) {
    opts = Object.assign({}, BA.REACH_DEFAULT, opts || {});
    const tt = await BA.travelLsoa(); if (!tt) return null;
    const out = {};
    for (const [pid, ids] of Object.entries(BA.REACH_WEIGHTS)) {
      const w = await lsoaWeights(ids);
      let num = 0, den = 0;
      Object.entries(w).forEach(([c, v]) => { const f = BA.reachFrac(tt[c], opts); if (f == null) return; num += v * f; den += v; });
      out[pid] = { share: den ? num / den : null, note: `${Math.round(den ? 100 * num / den : 0)}% within ${opts.minutes} min (${BA.REACH_MODES[opts.mode].toLowerCase()}${opts.late ? ', with a bus home after a late shift' : ''})` };
    }
    return out;
  };

  // Engine state at its defaults, with cohort sizes from the data and reach from opts.
  BA.engineState = async function (reachOpts) {
    const s = {};
    BA.ENGINE_PARAMS.forEach((g) => g.items.forEach((p) => (s[p.id] = p.v)));
    if (BA.applyUnitCosts) BA.applyUnitCosts();
    await Promise.all(BA.ENGINE_POOLS.map(async (p) => {
      ['count', 'reach', 'engage', 'complete', 'job', 'cost', 'fiscal'].forEach((k) => (s[p.id + '_' + k] = p[k]));
      const f = BA.ENGINE_SOURCES[p.id];
      if (f) { try { const r = await f(); if (r && r.value != null) s[p.id + '_count'] = Math.round(r.value); } catch (e) { /* default */ } }
    }));
    const rs = await BA.reachShares(reachOpts);
    if (rs) BA.ENGINE_POOLS.forEach((p) => { if (rs[p.id] && rs[p.id].share != null) s[p.id + '_reach'] = Math.round(rs[p.id].share * 1000) / 10; });
    return { s, reach: rs };
  };

  const POOL_COLORS = ['#12436D', '#28A197', '#801650', '#F46A25', '#3D3D3D', '#A285D1'];

  BA.route(/^\/balance$/, async (app) => {
    const q = BA.query;
    const opts = { mode: q.get('mode') || BA.REACH_DEFAULT.mode, minutes: +(q.get('min') || BA.REACH_DEFAULT.minutes), late: q.get('late') === '1' };
    const hasTravel = BA.has('travel_lsoa');
    app.innerHTML = `<span class="govuk-caption-xl">Labour balance</span>
      <h1 class="govuk-heading-xl">Can Bedfordshire staff the resort?</h1>
      <p class="govuk-body-l">This page follows each target cohort from its size in the data, through whether people can physically get to a shift, to how many a skills programme could realistically move into work. It sets that against the local share of the resort's jobs.</p>
      ${hasTravel ? '' : '<div class="ba-callout ba-callout--warn"><p class="govuk-body govuk-!-margin-bottom-0">Travel-time data has not loaded, so everyone is treated as able to reach the site.</p></div>'}
      <div class="ba-filterbar ba-noprint">
        <div class="govuk-form-group"><label class="govuk-label govuk-label--s" for="bmode">How people travel</label><select class="govuk-select" id="bmode">${Object.entries(BA.REACH_MODES).map(([k, v]) => `<option value="${k}" ${k === opts.mode ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></div>
        <div class="govuk-form-group"><label class="govuk-label govuk-label--s" for="bmin">Longest acceptable journey</label><select class="govuk-select" id="bmin">${[30, 45, 60, 75, 90].map((m) => `<option value="${m}" ${m === opts.minutes ? 'selected' : ''}>${m} minutes</option>`).join('')}</select></div>
        <div class="govuk-form-group"><div class="govuk-checkboxes govuk-checkboxes--small"><div class="govuk-checkboxes__item"><input class="govuk-checkboxes__input" id="blate" type="checkbox" ${opts.late ? 'checked' : ''}><label class="govuk-label govuk-checkboxes__label" for="blate">Must get home by public transport after a shift ending 22:30</label></div></div></div>
      </div>
      <div class="ba-tiles" id="btiles"></div>
      <h2 class="govuk-heading-l">From cohort to job</h2>
      <p class="govuk-body">Each bar is the whole target population at one stage, split by cohort. Reach comes from journey times for each neighbourhood. Engagement, completion and job rates are the business case engine's assumptions, which you can change there.</p>
      <div class="ba-chart ba-chart--tall"><canvas id="c-fall" role="img" aria-label="Target cohorts at each stage from population to job, against local jobs to fill"></canvas></div>
      <ul class="ba-legend govuk-!-margin-top-2" id="fall-legend"></ul>
      <div id="ftable"></div>
      <div class="ba-two govuk-!-margin-top-6"><div><h2 class="govuk-heading-m">Which jobs could they fill?</h2><div class="ba-chart"><canvas id="c-level" role="img" aria-label="Local jobs by level against likely recruits"></canvas></div><p class="govuk-body-s" id="level-note"></p></div>
        <div><h2 class="govuk-heading-m">How far can people get?</h2><div class="ba-chart"><canvas id="c-curve" role="img" aria-label="Share of residents aged 16 to 64 who can reach the site within each journey time, by mode"></canvas></div><p class="govuk-body-s">Share of residents aged 16-64 living where the site is reachable within each journey time, arriving by 08:30 on a weekday. <a class="govuk-link" href="#/explore?ind=tt_pt_am_min">See the map</a>.</p></div></div>
      <h2 class="govuk-heading-l govuk-!-margin-top-6">Reach by cohort and area</h2><div id="reach"></div>
      <div id="compete"></div>
      <div id="bench"></div>
      <p class="govuk-body govuk-!-margin-top-6"><a class="govuk-link" id="tocase" href="#/case">Change the assumptions in the business case engine</a></p>`;

    const $ = (id) => document.getElementById(id);
    const sync = () => {
      const o = { mode: $('bmode').value, min: $('bmin').value, late: $('blate').checked ? '1' : '0' };
      BA.keepScroll = true; location.hash = '#/balance?' + new URLSearchParams(o).toString();
    };
    ['bmode', 'bmin', 'blate'].forEach((id) => $(id).addEventListener('change', sync));

    const { s } = await BA.engineState(opts);
    const m = BA.engineModel(s);
    const qs = new URLSearchParams(); Object.keys(s).forEach((k) => qs.set(k, s[k]));
    $('tocase').href = '#/case?' + qs.toString();
    const T = (n) => BA.fmt(Math.round(n), 'count');
    const localOps = m.demand.ops;
    const entryL2 = m.demand.byLevel.filter((x) => x.k === 'entry' || x.k === 'l2').reduce((a, x) => a + x.n, 0);
    const gap = Math.max(0, localOps - m.tot.jobs);
    $('btiles').innerHTML = `
      <div class="ba-tile"><p class="ba-tile__label">Local operational jobs to fill at opening</p><p class="ba-tile__value">${T(localOps)}</p><p class="ba-tile__sub">${s.ops_local}% of ${T(s.ops_jobs)} jobs, plus ${T(m.demand.replace)} a year to replace turnover</p></div>
      <div class="ba-tile ba-tile--good"><p class="ba-tile__label">Could come from the target cohorts</p><p class="ba-tile__value">${T(m.tot.jobs)}</p><p class="ba-tile__sub">${Math.round(100 * m.tot.jobs / Math.max(1, localOps))}% of local operational jobs · ${T(m.tot.engaged)} programme participants</p></div>
      <div class="ba-tile ba-tile--warn"><p class="ba-tile__label">Still to fill from elsewhere</p><p class="ba-tile__value">${T(gap)}</p><p class="ba-tile__sub">People already in work moving jobs, in-commuters, or a bigger programme</p></div>
      <div class="ba-tile"><p class="ba-tile__label">Target cohorts who can reach a shift</p><p class="ba-tile__value">${Math.round(100 * m.tot.reachable / Math.max(1, m.tot.count))}%</p><p class="ba-tile__sub">${T(m.tot.reachable)} of ${T(m.tot.count)} · within ${opts.minutes} min</p></div>`;

    // stacked stage chart
    const stages = [['In cohort', 'count'], ['Can reach a shift', 'reachable'], ['Engaged', 'engaged'], ['Complete training', 'trained'], ['Into work', 'jobs']];
    BA.chart($('c-fall'), { type: 'bar', data: { labels: stages.map((x) => x[0]).concat(['Local jobs to fill']), datasets: m.pools.map((x, i) => ({ label: x.p.label, data: stages.map((st) => x[st[1]]).concat([null]), backgroundColor: POOL_COLORS[i], borderColor: '#fff', borderWidth: 1, stack: 's' }))
      .concat([{ label: 'Local operational jobs', data: stages.map(() => null).concat([localOps]), backgroundColor: '#0b0c0c', stack: 's' }, { label: 'Local construction jobs (peak)', data: stages.map(() => null).concat([m.demand.constr]), backgroundColor: '#b1b4b6', stack: 's' }]) },
      options: { maintainAspectRatio: false, scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, grid: { color: '#e5e6e7' }, ticks: { callback: (v) => BA.big(v) } } }, plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${T(c.raw)}` } } } } });
    $('fall-legend').innerHTML = m.pools.map((x, i) => `<li><span class="ba-sw" style="background:${POOL_COLORS[i]}"></span>${esc(x.p.label)}</li>`).join('') + '<li><span class="ba-sw" style="background:#0b0c0c"></span>Local operational jobs</li><li><span class="ba-sw" style="background:#b1b4b6"></span>Local construction jobs at peak</li>';
    const th = (t, n) => `<th class="govuk-table__header${n ? ' govuk-table__header--numeric' : ''}" scope="col">${t}</th>`;
    const td = (t) => `<td class="govuk-table__cell govuk-table__cell--numeric">${t}</td>`;
    $('ftable').innerHTML = `<details class="govuk-details"><summary class="govuk-details__summary"><span class="govuk-details__summary-text">Show the figures as a table</span></summary><div class="govuk-details__text"><div class="ba-table-wrap"><table class="govuk-table"><thead class="govuk-table__head"><tr class="govuk-table__row">${th('Cohort')}${stages.map((x) => th(x[0], 1)).join('')}</tr></thead><tbody class="govuk-table__body">
      ${m.pools.map((x) => `<tr class="govuk-table__row"><th class="govuk-table__header" scope="row">${esc(x.p.label)}${x.p.years === 'perYear' ? ` <span class="ba-small">(× ${m.years} years)</span>` : ''}</th>${stages.map((st) => td(T(x[st[1]]))).join('')}</tr>`).join('')}
      <tr class="govuk-table__row"><th class="govuk-table__header" scope="row">Total</th>${stages.map((st) => td('<strong>' + T(m.tot[st[1]]) + '</strong>')).join('')}</tr></tbody></table></div></div></details>`;

    // job levels
    const lv = { entry: 'Entry level', l2: 'Level 2', l3: 'Level 3', l4: 'Level 4+' };
    BA.chart($('c-level'), { type: 'bar', data: { labels: m.demand.byLevel.map((x) => lv[x.k]), datasets: [{ label: 'Local jobs', data: m.demand.byLevel.map((x) => x.n), backgroundColor: '#12436D', borderRadius: 4 }, { label: 'Recruits from target cohorts', data: [Math.min(m.tot.jobs, m.demand.byLevel[0].n), Math.max(0, Math.min(m.tot.jobs - m.demand.byLevel[0].n, m.demand.byLevel[1].n)), 0, 0], backgroundColor: '#28A197', borderRadius: 4 }] },
      options: { maintainAspectRatio: false, plugins: { legend: { display: true, position: 'bottom' }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${T(c.raw)}` } } }, scales: { y: { grid: { color: '#e5e6e7' } }, x: { grid: { display: false } } } } });
    $('level-note').innerHTML = `Programme recruits go first to entry-level and Level 2 roles (${T(entryL2)} local jobs). ${m.tot.jobs >= entryL2 ? 'They could fill all of them.' : `That leaves ${T(entryL2 - m.tot.jobs)} entry and Level 2 roles open.`} The ${T(localOps - entryL2)} Level 3 and above roles need experienced hires or progression routes, which pre-employment programmes do not supply.`;

    // accessibility curve and reach table
    const tt = await BA.travelLsoa();
    if (tt) {
      const w = await lsoaWeights(['popsa_16_64']);
      const totalW = Object.values(w).reduce((a, v) => a + v, 0);
      const mins = []; for (let t = 10; t <= 120; t += 5) mins.push(t);
      const curve = (mode) => mins.map((t) => { let n = 0; Object.entries(w).forEach(([c, v]) => { n += v * (BA.reachFrac(tt[c], { mode, minutes: t, late: false }) || 0); }); return 100 * n / totalW; });
      const modes = [['car', 'Car', '#3D3D3D', [5, 4]], ['mixed', 'Car if available, else public transport or cycle', '#F46A25', []], ['noncar', 'Public transport or cycle', '#28A197', []], ['pt', 'Public transport only', '#12436D', []]];
      BA.chart($('c-curve'), { type: 'line', data: { labels: mins, datasets: modes.map(([k, l, c, d]) => ({ label: l, data: curve(k), borderColor: c, backgroundColor: c, borderWidth: 2, pointRadius: 0, borderDash: d })) },
        options: { maintainAspectRatio: false, interaction: { mode: 'index', intersect: false }, scales: { y: { min: 0, max: 100, grid: { color: '#e5e6e7' }, ticks: { callback: (v) => v + '%' } }, x: { title: { display: true, text: 'Journey time (minutes)' }, grid: { display: false }, ticks: { maxTicksLimit: 12 } } }, plugins: { legend: { display: true, position: 'bottom', labels: { boxWidth: 14 } }, tooltip: { callbacks: { title: (c) => c[0].label + ' minutes', label: (c) => `${c.dataset.label}: ${c.raw.toFixed(0)}%` } } } } });
      // reach by pool × mode, and by LA
      const rows = [];
      for (const [pid, ids] of Object.entries(BA.REACH_WEIGHTS)) {
        const pw = await lsoaWeights(ids); const pool = BA.ENGINE_POOLS.find((p) => p.id === pid);
        const share = (mode, la) => { let n = 0, d = 0; Object.entries(pw).forEach(([c, v]) => { if (la && (BA.lsoaLookup[c] || {}).la !== la) return; const f = BA.reachFrac(tt[c], Object.assign({}, opts, { mode })); if (f == null) return; n += v * f; d += v; }); return d ? Math.round(100 * n / d) + '%' : '–'; };
        rows.push(`<tr class="govuk-table__row"><th class="govuk-table__header" scope="row">${esc(pool.label)}</th>${['pt', 'noncar', 'mixed', 'car'].map((k) => td(share(k))).join('')}${Object.keys(BA.LAS).map((la) => td(share(opts.mode, la))).join('')}</tr>`);
      }
      $('reach').innerHTML = `<p class="govuk-body">Share of each cohort living where the site can be reached within <strong>${opts.minutes} minutes</strong>${opts.late ? ', with a public transport journey home after a 22:30 finish' : ''}. Cohorts are spread across neighbourhoods using the closest small-area count (for example claimants aged 16-24 for the 18-24 claimant cohort).</p>
        <div class="ba-table-wrap"><table class="govuk-table"><thead class="govuk-table__head"><tr class="govuk-table__row">${th('Cohort')}${th('Public transport', 1)}${th('Public transport or cycle', 1)}${th('Mixed (car where available)', 1)}${th('Car', 1)}${Object.values(BA.LAS).map((n) => th(esc(n) + '<br><span class="ba-small">' + esc(BA.REACH_MODES[opts.mode].split(',')[0]) + '</span>', 1)).join('')}</tr></thead><tbody class="govuk-table__body">${rows.join('')}</tbody></table></div>
        <p class="ba-small">${esc((BA.meta('travel_lsoa') || {}).limitations || '')}</p>`;
    } else {
      $('reach').innerHTML = '<p class="govuk-body">Travel-time data is not loaded.</p>';
    }

    // competing demand
    const comp = [['bres_emp_accom_food', 'Accommodation and food'], ['bres_emp_retail', 'Retail'], ['bres_emp_warehousing', 'Warehousing and logistics'], ['bres_emp_air', 'Air transport'], ['bres_emp_arts_rec', 'Arts, entertainment and recreation']].filter(([id]) => BA.indicators[id]);
    if (comp.length) {
      const vals = await Promise.all(comp.map(async ([id, l]) => { const r = await BA.value(id, 'BEDS'); return { l, v: r ? r.value : null, p: r ? r.period : '' }; }));
      $('compete').innerHTML = `<h2 class="govuk-heading-l govuk-!-margin-top-6">Who else is hiring the same people?</h2>
        <p class="govuk-body">The resort's ${T(s.ops_jobs)} operational jobs land in a county where these sectors already employ people in similar entry-level roles. Recruitment from them is displacement: it fills the resort but leaves a vacancy elsewhere. The engine's displacement assumption is <strong>${s.displacement}%</strong>.</p>
        <div class="ba-chart ba-chart--short"><canvas id="c-comp" role="img" aria-label="Employees in competing sectors in Bedfordshire against resort jobs"></canvas></div>`;
      const data = vals.filter((x) => x.v != null).concat([{ l: 'Universal resort (2031)', v: s.ops_jobs, p: 'promoter' }]);
      BA.chart($('c-comp'), { type: 'bar', data: { labels: data.map((x) => x.l), datasets: [{ data: data.map((x) => x.v), backgroundColor: data.map((x) => /resort/.test(x.l) ? '#F46A25' : '#12436D'), borderRadius: 4 }] },
        options: { indexAxis: 'y', maintainAspectRatio: false, scales: { x: { grid: { color: '#e5e6e7' } }, y: { grid: { display: false } } }, plugins: { tooltip: { callbacks: { label: (c) => `${T(c.raw)} employees (${data[c.dataIndex].p})` } } } } });
    }

    // local hire benchmarks
    const b = BA.hireBenchmarks;
    const list = Array.isArray(b) ? b : (b && (b.entries || b.items || b.benchmarks)) || [];
    if (list.length) {
      $('bench').innerHTML = `<h2 class="govuk-heading-l govuk-!-margin-top-6">Is ${s.ops_local}% local realistic?</h2>
        <p class="govuk-body">What other large developments set as local hiring targets, and what they achieved. Definitions of “local” differ a lot, so compare with care.</p>
        <div class="ba-table-wrap"><table class="govuk-table"><thead class="govuk-table__head"><tr class="govuk-table__row">${['Development', 'Opened', 'Jobs', '“Local” means', 'Target', 'Achieved', 'Source'].map((x) => th(x)).join('')}</tr></thead><tbody class="govuk-table__body">
        ${list.map((x) => `<tr class="govuk-table__row"><th class="govuk-table__header" scope="row">${esc(x.development)}<br><span class="ba-small">${esc(x.location || '')}</span></th><td class="govuk-table__cell">${esc(x.opened || '')}</td><td class="govuk-table__cell">${esc(x.jobs || '')}</td><td class="govuk-table__cell ba-small">${esc(x.local_definition || '')}</td><td class="govuk-table__cell ba-small">${esc(x.target || '')}</td><td class="govuk-table__cell ba-small"><strong>${esc(x.achieved || '')}</strong>${x.year_measured ? ' (' + esc(x.year_measured) + ')' : ''}</td><td class="govuk-table__cell ba-small">${BA.link(x.url, x.source_title || 'source')}</td></tr>`).join('')}</tbody></table></div>`;
    }
  });
})();
