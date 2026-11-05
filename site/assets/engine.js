/* Business case engine: local demand by phase vs supply from data-sized cohorts,
   training cost, fiscal and economic benefit, BCR and sensitivity. */
(function () {
  'use strict';
  const BA = window.BA;
  const esc = BA.esc;

  // Scalar assumptions. src = where the default comes from (shown under each input).
  BA.ENGINE_PARAMS = [
    { g: 'Demand: the development', items: [
      { id: 'start_year', label: 'Skills programme starts', v: 2026, unit: 'year', src: 'Assumption' },
      { id: 'open_year', label: 'Opening year', v: 2031, unit: 'year', src: 'Promoter\'s stated target' },
      { id: 'constr_peak', label: 'Construction workforce at peak (on site, winter 2029)', v: 5380, unit: 'count', src: '<a class="govuk-link" href="https://assets.publishing.service.gov.uk/media/685d759ef85b4b993fd75311/12_-_6.12.0_Employment___Skills_Plan.pdf" target="_blank" rel="noopener">Employment &amp; Skills Plan</a> para 4.3 (4,525 UK-hired, 855 from abroad). The “nearly 20,000” headline counts everyone over the whole build.' },
      { id: 'constr_local', label: 'Construction jobs filled by Bedfordshire residents', v: 35, unit: '%', src: 'Assumption. The ES assumes 71% of the peak (3,215) comes from the wider 60-minute catchment, so the Bedfordshire share is lower.' },
      { id: 'ops_jobs', label: 'Direct operational jobs at opening, 2031 (headcount)', v: 8050, unit: 'count', src: '<a class="govuk-link" href="https://assets.publishing.service.gov.uk/media/685d759ef85b4b993fd75311/12_-_6.12.0_Employment___Skills_Plan.pdf" target="_blank" rel="noopener">Employment &amp; Skills Plan</a>: 5,950 FTE (4,090 full-time, 3,960 part-time), rising to 10,000 by 2051' },
      { id: 'ops_local', label: 'Operational jobs filled by Bedfordshire residents', v: 69, unit: '%', src: 'ES: 5,530 of 8,050 jobs to Bedford and Central Bedfordshire residents. Luton is not counted in that figure.' },
      { id: 'turnover', label: 'Annual staff turnover in operations', v: 30, unit: '%', src: 'Assumption. Hospitality turnover is typically 30% or more a year; Alton Towers recruits 1,000+ seasonal staff a year.' },
    ] },
    { g: 'Operational job mix (share of roles)', items: [
      { id: 'mix_entry', label: 'Entry level (“limited skill”)', v: 57, unit: '%', src: 'Employment & Skills Plan career-level split (UDX taxonomy, not RQF)' },
      { id: 'mix_l2', label: 'Vocational, around Level 2 (e.g. hospitality team member, retail)', v: 24, unit: '%', src: 'Employment & Skills Plan (“vocational skill”)' },
      { id: 'mix_l3', label: 'Level 3 (supervisors, technicians, chefs)', v: 12, unit: '%', src: 'Assumption: splits the remaining 19%' },
      { id: 'mix_l4', label: 'Level 4+ (managers, engineers, specialists)', v: 7, unit: '%', src: 'Assumption: splits the remaining 19%' },
    ] },
    { g: 'Benefits and appraisal (HM Treasury Green Book)', items: [
      { id: 'wage', label: 'Annual earnings per new job (part-time adjusted)', v: 18300, unit: '£', src: 'National Living Wage £12.71/hr (Apr 2026) × 37.5 hrs × 52 weeks × 0.74 FTE per head (Employment & Skills Plan). The promoter commits to at least the NLW.' },
      { id: 'econ_share', label: 'Share of earnings counted as economic (GVA) gain', v: 60, unit: '%', src: 'Assumption, to avoid double counting with the fiscal benefit' },
      { id: 'persist', label: 'Years an outcome persists', v: 3, unit: 'years', src: 'Assumption (conservative)' },
      { id: 'decay', label: 'Annual drop-off in sustained employment', v: 20, unit: '%', src: 'Assumption' },
      { id: 'deadweight', label: 'Deadweight (would have found work anyway)', v: 30, unit: '%', src: 'Assumption, in line with employment programme evaluations' },
      { id: 'displacement', label: 'Displacement (jobs taken from other local employers)', v: 25, unit: '%', src: 'Assumption. Hospitality displacement can be high.' },
      { id: 'discount', label: 'Discount rate', v: 3.5, unit: '%', src: 'HM Treasury Green Book' },
    ] },
  ];

  // Supply cohorts. count is filled from data where possible (BA.ENGINE_SOURCES), else this default.
  BA.ENGINE_POOLS = [
    { id: 'leavers', reach: 100, fiscal: 0, label: 'Young people turning 16 each year (pipeline, per year)', cohort: '16-19', count: 7000, engage: 6, complete: 80, job: 70, cost: 6000, years: 'perYear', workless: false, path: 'Apprenticeship (L2/L3) or T Level placement' },
    { id: 'neet', reach: 100, fiscal: 800, label: '16-17 year olds NEET or activity not known', cohort: '16-19', count: 900, engage: 30, complete: 60, job: 55, cost: 4500, workless: true, path: 'Pre-employment programme, then L2 apprenticeship' },
    { id: 'cc1824', reach: 100, fiscal: 9000, label: '18-24 year olds claiming (claimant count)', cohort: '18-24', count: 2500, engage: 30, complete: 70, job: 60, cost: 2500, workless: true, path: 'Sector-based work academy (SWAP) or bootcamp' },
    { id: 'inact1824', reach: 100, fiscal: 6000, label: '18-24 year olds inactive and not students', cohort: '18-24', count: 3000, engage: 10, complete: 60, job: 50, cost: 4000, workless: true, path: 'Outreach, wraparound support and pre-employment' },
    { id: 'cc25', reach: 100, fiscal: 9000, label: 'Claimants aged 25+', cohort: '25+ inactive', count: 9000, engage: 15, complete: 70, job: 55, cost: 2500, workless: true, path: 'SWAP, bootcamp, construction entry (CSCS)' },
    { id: 'inact25', reach: 100, fiscal: 4500, label: 'Inactive 25-64: long-term sick, carers, looking after home, other', cohort: '25+ inactive', count: 40000, engage: 4, complete: 60, job: 45, cost: 5000, workless: true, path: 'Health and childcare wraparound, flexible-hours academy' },
  ];
  BA.ENGINE_SOURCES = {}; // pool id -> async () => ({ value, note, dataset })
  BA.ENGINE_DATASETS = [];
  const PRESETS = { cautious: 0.6, central: 1, ambitious: 1.5 };

  function readState() {
    const s = {}; const q = BA.query;
    BA.ENGINE_PARAMS.forEach((g) => g.items.forEach((p) => (s[p.id] = q.has(p.id) ? +q.get(p.id) : p.v)));
    BA.ENGINE_POOLS.forEach((p) => ['count', 'reach', 'engage', 'complete', 'job', 'cost', 'fiscal'].forEach((k) => { const key = p.id + '_' + k; s[key] = q.has(key) ? +q.get(key) : p[k]; }));
    return s;
  }

  function model(s) {
    const years = Math.max(1, s.open_year - s.start_year);
    const demand = {
      constr: s.constr_peak * s.constr_local / 100,
      ops: s.ops_jobs * s.ops_local / 100,
      replace: s.ops_jobs * s.ops_local / 100 * s.turnover / 100,
    };
    demand.byLevel = ['entry', 'l2', 'l3', 'l4'].map((k) => ({ k, n: demand.ops * s['mix_' + k] / 100 }));
    const pools = BA.ENGINE_POOLS.map((p) => {
      const mult = p.years === 'perYear' ? years : 1;
      const count = s[p.id + '_count'] * mult;
      const reachable = count * (s[p.id + '_reach'] == null ? 100 : s[p.id + '_reach']) / 100;
      const engaged = reachable * s[p.id + '_engage'] / 100;
      const trained = engaged * s[p.id + '_complete'] / 100;
      const jobs = trained * s[p.id + '_job'] / 100;
      const add = jobs * (1 - s.deadweight / 100) * (1 - s.displacement / 100);
      return { p, count, reachable, engaged, trained, jobs, add, fiscalPY: add * (s[p.id + '_fiscal'] || 0), cost: engaged * s[p.id + '_cost'] };
    });
    const tot = pools.reduce((a, x) => ({ count: a.count + x.count, reachable: a.reachable + x.reachable, engaged: a.engaged + x.engaged, trained: a.trained + x.trained, jobs: a.jobs + x.jobs, cost: a.cost + x.cost }), { count: 0, reachable: 0, engaged: 0, trained: 0, jobs: 0, cost: 0 });
    const worklessJobs = pools.filter((x) => x.p.workless).reduce((a, x) => a + x.jobs, 0);
    const additional = worklessJobs * (1 - s.deadweight / 100) * (1 - s.displacement / 100);
    const leaverAdditional = pools.filter((x) => !x.p.workless).reduce((a, x) => a + x.jobs, 0) * (1 - s.deadweight / 100) * (1 - s.displacement / 100);
    // benefits flow from opening year for `persist` years with decay; discount to start year.
    const flows = []; let pvF = 0, pvE = 0;
    for (let t = 0; t < s.persist; t++) {
      const survive = Math.pow(1 - s.decay / 100, t);
      const yr = s.open_year + t; const df = Math.pow(1 + s.discount / 100, -(yr - s.start_year));
      const f = pools.reduce((a, x) => a + x.fiscalPY, 0) * survive; const e = (additional + leaverAdditional) * survive * s.wage * s.econ_share / 100;
      pvF += f * df; pvE += e * df; flows.push({ yr, f, e });
    }
    // costs spread evenly over the programme years up to opening + 1.
    const costYears = []; let pvC = 0;
    const span = years + 1;
    for (let i = 0; i < span; i++) { const yr = s.start_year + i; const c = tot.cost / span; pvC += c * Math.pow(1 + s.discount / 100, -i); costYears.push({ yr, c }); }
    const demandOpen = demand.constr + demand.ops;
    // Year-by-year profile. Construction on-site shares by year relative to opening and the
    // pre-opening hiring split are assumptions (BA.PROFILE), shown on the page.
    const timeline = [];
    for (let yr = s.start_year; yr <= s.open_year + 2; yr++) {
      const off = yr - s.open_year;
      const ready = yr > s.start_year && yr <= s.open_year ? tot.jobs / years : 0;
      timeline.push({ yr, constr: demand.constr * (BA.PROFILE.constr[off] || 0), ops: off === -1 ? demand.ops * BA.PROFILE.preopen : off === 0 ? demand.ops * (1 - BA.PROFILE.preopen) : off > 0 ? demand.replace : 0, ready });
    }
    return { s, years, timeline, demand, demandOpen, pools, tot, additional, leaverAdditional, pvF, pvE, pvC, bcrF: pvF / pvC, bcr: (pvF + pvE) / pvC, cpj: tot.cost / Math.max(1, additional + leaverAdditional), coverage: tot.jobs / Math.max(1, demandOpen), flows, costYears };
  }
  BA.engineModel = model;
  // Per-cohort fiscal value of one more person in work, from the GMCA Unit Cost Database:
  // claimant values are for full-time work, so scaled to the resort's 0.74 FTE per head;
  // only an assumed share of inactive 25+ adults claim a health-related benefit.
  BA.FISCAL_MAP = {
    neet: { id: 'neet_per_year_fiscal_16_17', f: 1, why: 'GMCA: fiscal cost of a NEET 16-17 year old' },
    cc1824: { id: 'uc_jobseeker_into_work', f: 0.74, why: 'GMCA: UC claimant into full-time work × 0.74 FTE' },
    inact1824: { id: 'neet_per_year', f: 1, why: 'GMCA: fiscal cost of a NEET 18-24 year old' },
    cc25: { id: 'uc_jobseeker_into_work', f: 0.74, why: 'GMCA: UC claimant into full-time work × 0.74 FTE' },
    inact25: { id: 'health_claimant_into_work', f: 0.74 * 0.5, why: 'GMCA: ESA claimant into work × 0.74 FTE × 50% assumed to claim' },
  };
  BA.applyUnitCosts = function () {
    if (BA._ucApplied || !BA.unitCost) return; BA._ucApplied = true;
    BA.ENGINE_POOLS.forEach((p) => { const m = BA.FISCAL_MAP[p.id]; const u = m && BA.unitCost(m.id); if (u) { p.fiscal = Math.round(u.value * m.f); p.fiscalNote = m.why + ' (' + (BA.unitCosts.price_base || '').split(' (')[0] + ')'; } });
  };
  BA.PROFILE = { constr: { '-4': 0.3, '-3': 0.7, '-2': 1, '-1': 0.8, 0: 0.3 }, preopen: 0.35 };

  // Monte Carlo: vary every uncertain assumption on a triangular distribution around the
  // current value (seeded, so the same inputs always give the same picture).
  function rng(seed) { return function () { seed |= 0; seed = (seed + 0x6D2B79F5) | 0; let t = Math.imul(seed ^ (seed >>> 15), 1 | seed); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; }; }
  const tri = (r, a, c, b) => { const u = r(), f = (c - a) / (b - a || 1); return u < f ? a + Math.sqrt(u * (b - a) * (c - a)) : b - Math.sqrt((1 - u) * (b - a) * (b - c)); };
  BA.MC_RANGES = { deadweight: [0.5, 1.5, 90], displacement: [0.5, 1.6, 90], persist: [0.67, 1.67], decay: [0.5, 1.5, 90], _fiscal: [0.7, 1.3], wage: [0.9, 1.1], econ_share: [0.6, 1.3, 100],
    _engage: [0.5, 1.5, 100], _complete: [0.8, 1.15, 100], _job: [0.7, 1.25, 95], _cost: [0.75, 1.4], _reach: [0.85, 1.1, 100] };
  BA.monteCarlo = function (s, n) {
    const r = rng(20311); const out = [];
    for (let i = 0; i < (n || 1500); i++) {
      const d = Object.assign({}, s);
      Object.keys(s).forEach((k) => {
        const key = BA.MC_RANGES[k] ? k : Object.keys(BA.MC_RANGES).find((x) => x[0] === '_' && k.endsWith(x));
        if (!key) return; const [lo, hi, cap] = BA.MC_RANGES[key];
        let v = tri(r, s[k] * lo, s[k], s[k] * hi); if (cap != null) v = Math.min(cap, v); d[k] = v;
      });
      out.push(model(d).bcr);
    }
    out.sort((a, b) => a - b);
    const q = (p) => out[Math.floor(p * (out.length - 1))];
    return { draws: out, p10: q(0.1), p50: q(0.5), p90: q(0.9), pAbove1: out.filter((x) => x >= 1).length / out.length };
  };

  function commitments() {
    const p = (BA.assessment || {}).project || {};
    const js = (p.jobs_claims || []).filter((j) => /apprentice|catchment|Bedford|peak|opening year|2031/i.test(j.what)).slice(0, 7);
    if (!js.length) return '';
    return `<details class="govuk-details"><summary class="govuk-details__summary"><span class="govuk-details__summary-text">What the promoter has published on jobs and skills</span></summary><div class="govuk-details__text"><ul class="govuk-list govuk-list--bullet govuk-body-s">${js.map((j) => `<li><strong>${esc(j.figure)}</strong>: ${esc(j.what)} (${BA.link(j.url, j.source_title)}, ${esc(j.date || '')})</li>`).join('')}</ul></div></details>`;
  }

  BA.route(/^\/case$/, async (app) => {
    // fill data-driven defaults
    const notes = {};
    await Promise.all(BA.ENGINE_POOLS.map(async (p) => {
      const f = BA.ENGINE_SOURCES[p.id]; if (!f) return;
      try { const r = await f(); if (r && r.value != null) { p.count = Math.round(r.value); notes[p.id] = r; } } catch (e) { console.warn(p.id, e); }
    }));
    if (BA.ENGINE_DEFAULTS) await BA.ENGINE_DEFAULTS();
    if (BA.reachShares) {
      try {
        const rs = await BA.reachShares(BA.REACH_DEFAULT);
        if (rs) BA.ENGINE_POOLS.forEach((p) => { if (rs[p.id] && rs[p.id].share != null) { p.reach = Math.round(rs[p.id].share * 1000) / 10; notes[p.id + '_reach'] = rs[p.id]; } });
      } catch (e) { console.warn('reach', e); }
    }
    BA.applyUnitCosts();
    let s = readState();

    const inp = (id, label, v, unit, src) => `<div class="ba-inp"><label for="p-${id}">${esc(label)}${unit && unit !== 'count' && unit !== 'year' ? ' <span class="ba-small">(' + esc(unit) + ')</span>' : ''}</label><input id="p-${id}" data-k="${id}" type="number" inputmode="decimal" step="any" value="${v}">${src ? `<span class="ba-src">${src}</span>` : ''}</div>`;
    app.innerHTML = `<span class="govuk-caption-xl">Business case engine</span><h1 class="govuk-heading-xl">What would a skills programme need to deliver, and what is it worth?</h1>
      <p class="govuk-body-l">Start with cohort sizes taken from the data, then adjust the assumptions. The engine sizes local demand in each phase and how much of it the target cohorts could fill. It then costs the training and values the outcomes on Green Book principles.</p>
      <div class="ba-callout ba-callout--warn ba-noprint"><p class="govuk-body govuk-!-margin-bottom-0">Defaults marked <em>illustrative</em> are placeholders. Replace them with the promoter's workforce plan and local provider quotes before using results in a submission. The model is deliberately simple and transparent: each figure on the right can be reproduced from the inputs on the left.</p></div>
      ${commitments()}
      <div class="ba-filterbar ba-noprint"><div class="govuk-button-group govuk-!-margin-bottom-0">
        ${Object.keys(PRESETS).map((k) => `<button class="govuk-button govuk-button--secondary" data-preset="${k}">${k[0].toUpperCase() + k.slice(1)} scenario</button>`).join('')}
        <button class="govuk-button govuk-button--secondary" id="reset">Reset</button><button class="govuk-button" id="share">Copy link to this scenario</button>
        <button class="govuk-button govuk-button--secondary" id="csv">Download results (CSV)</button><button class="govuk-button govuk-button--secondary" onclick="window.print()">Print</button></div></div>
      <div class="ba-engine"><div class="ba-engine__inputs ba-noprint">
        ${BA.ENGINE_PARAMS.map((g, gi) => `<details class="govuk-details" ${gi === 0 ? 'open' : ''}><summary class="govuk-details__summary"><span class="govuk-details__summary-text">${esc(g.g)}</span></summary><div class="govuk-details__text">${g.items.map((p) => inp(p.id, p.label, s[p.id], p.unit, p.src)).join('')}</div></details>`).join('')}
        <details class="govuk-details" open><summary class="govuk-details__summary"><span class="govuk-details__summary-text">Supply cohorts (sized from the data)</span></summary><div class="govuk-details__text">
          ${BA.ENGINE_POOLS.map((p) => `<h3 class="govuk-heading-s govuk-!-margin-bottom-1 govuk-!-margin-top-4">${esc(p.label)}</h3><p class="ba-small govuk-!-margin-bottom-2">${esc(p.path)}${notes[p.id] ? ` · <a class="govuk-link" href="#/data/${notes[p.id].dataset}">${esc(notes[p.id].note)}</a>` : ' · default (data not loaded)'}</p>
            ${inp(p.id + '_count', p.years === 'perYear' ? 'Cohort size per year' : 'Cohort size', s[p.id + '_count'], 'count')}${inp(p.id + '_reach', 'Can reach the site for a shift', s[p.id + '_reach'], '%', notes[p.id + '_reach'] ? `<a class="govuk-link" href="#/balance">${esc(notes[p.id + '_reach'].note)}</a>` : 'No travel-time data loaded: 100% assumed')}${inp(p.id + '_engage', 'Engaged (of those who can reach it)', s[p.id + '_engage'], '%')}${inp(p.id + '_complete', 'Complete training', s[p.id + '_complete'], '%')}${inp(p.id + '_job', 'Move into a job', s[p.id + '_job'], '%')}${inp(p.id + '_cost', 'Cost per participant', s[p.id + '_cost'], '£', 'Illustrative')}${p.workless ? inp(p.id + '_fiscal', 'Annual fiscal benefit per extra person in work', s[p.id + '_fiscal'], '£', p.fiscalNote ? `${esc(p.fiscalNote)}, <a class="govuk-link" href="${esc(BA.unitCosts.url)}">Unit Cost Database</a>` : 'Illustrative') : ''}`).join('')}
        </div></details>
      </div><div><p class="govuk-visually-hidden" aria-live="polite" id="live"></p><div id="out"></div>
        <h2 class="govuk-heading-m govuk-!-margin-top-6">How confident can we be?</h2>
        <p class="govuk-body-s">1,500 runs of the model, each drawing every uncertain assumption (deadweight, displacement, persistence, drop-off, benefit values, reach, engagement, completion, job and cost rates for each cohort) from a triangular range around the value you have set. Ranges are listed in the <a class="govuk-link" href="#/method">method</a>.</p>
        <div id="mc"></div>
        <h2 class="govuk-heading-m govuk-!-margin-top-6">Compare scenarios</h2>
        <div id="cmp"></div></div></div>`;

    const out = document.getElementById('out');
    function render() {
      BA.destroyCharts();
      const m = model(s);
      BA.lastModel = m;
      const T = (n) => BA.fmt(Math.round(n), 'count');
      out.innerHTML = `
        <div class="ba-tiles">
          <div class="ba-tile"><p class="ba-tile__label">Local jobs to fill by opening</p><p class="ba-tile__value">${T(m.demandOpen)}</p><p class="ba-tile__sub">${T(m.demand.constr)} construction (peak) + ${T(m.demand.ops)} operations</p></div>
          <div class="ba-tile ${m.coverage < 0.5 ? 'ba-tile--warn' : 'ba-tile--good'}"><p class="ba-tile__label">Filled from target cohorts</p><p class="ba-tile__value">${T(m.tot.jobs)}</p><p class="ba-tile__sub">${Math.round(m.coverage * 100)}% of local demand · ${T(m.tot.engaged)} participants</p></div>
          <div class="ba-tile"><p class="ba-tile__label">Programme cost</p><p class="ba-tile__value">${BA.money(m.tot.cost)}</p><p class="ba-tile__sub">${BA.money(m.cpj)} per additional job</p></div>
          <div class="ba-tile ${m.bcr >= 2 ? 'ba-tile--good' : m.bcr >= 1 ? 'ba-tile--warn' : 'ba-tile--bad'}"><p class="ba-tile__label">Benefit–cost ratio</p><p class="ba-tile__value">${m.bcr.toFixed(2)}</p><p class="ba-tile__sub">Fiscal only ${m.bcrF.toFixed(2)} · PV benefits ${BA.money(m.pvF + m.pvE)}</p></div>
        </div>
        <h2 class="govuk-heading-m">From cohort to job</h2>
        <div class="ba-chart ba-chart--tall"><canvas id="c-funnel" role="img" aria-label="Participants, completers and job outcomes by cohort"></canvas></div>
        <ul class="ba-legend govuk-!-margin-top-2"><li><span class="ba-sw" style="background:#9ec5e8"></span>Engaged</li><li><span class="ba-sw" style="background:#1d70b8"></span>Complete training</li><li><span class="ba-sw" style="background:#0b3b66"></span>Into work</li></ul>
        <div class="ba-table-wrap"><table class="govuk-table ba-funnel"><thead class="govuk-table__head"><tr class="govuk-table__row"><th class="govuk-table__header">Cohort</th><th class="govuk-table__header govuk-table__header--numeric">Pool</th><th class="govuk-table__header govuk-table__header--numeric">Can reach</th><th class="govuk-table__header govuk-table__header--numeric">Engaged</th><th class="govuk-table__header govuk-table__header--numeric">Trained</th><th class="govuk-table__header govuk-table__header--numeric">Into work</th><th class="govuk-table__header govuk-table__header--numeric">Cost</th></tr></thead><tbody class="govuk-table__body">
          ${m.pools.map((x) => `<tr class="govuk-table__row"><td class="govuk-table__cell">${esc(x.p.label)}${x.p.years === 'perYear' ? ` <span class="ba-small">(× ${m.years} years)</span>` : ''}</td><td class="govuk-table__cell govuk-table__cell--numeric">${T(x.count)}</td><td class="govuk-table__cell govuk-table__cell--numeric">${T(x.reachable)}</td><td class="govuk-table__cell govuk-table__cell--numeric">${T(x.engaged)}</td><td class="govuk-table__cell govuk-table__cell--numeric">${T(x.trained)}</td><td class="govuk-table__cell govuk-table__cell--numeric">${T(x.jobs)}</td><td class="govuk-table__cell govuk-table__cell--numeric">${BA.money(x.cost)}</td></tr>`).join('')}
          <tr class="govuk-table__row"><th class="govuk-table__header">Total</th><th class="govuk-table__header govuk-table__header--numeric">${T(m.tot.count)}</th><th class="govuk-table__header govuk-table__header--numeric">${T(m.tot.reachable)}</th><th class="govuk-table__header govuk-table__header--numeric">${T(m.tot.engaged)}</th><th class="govuk-table__header govuk-table__header--numeric">${T(m.tot.trained)}</th><th class="govuk-table__header govuk-table__header--numeric">${T(m.tot.jobs)}</th><th class="govuk-table__header govuk-table__header--numeric">${BA.money(m.tot.cost)}</th></tr></tbody></table></div>
        <div class="ba-two"><div><h2 class="govuk-heading-m">Local demand by skill level</h2><div class="ba-chart"><canvas id="c-demand" role="img" aria-label="Local demand by skill level against supply"></canvas></div>
          <p class="ba-small">Operational roles to fill with local residents at opening, by level, plus construction at peak. A further <strong>${T(m.demand.replace)}</strong> local hires a year are needed to replace turnover.</p></div>
          <div><h2 class="govuk-heading-m">Costs and benefits by year</h2><div class="ba-chart"><canvas id="c-flow" role="img" aria-label="Annual costs and benefits"></canvas></div>
          <ul class="ba-legend govuk-!-margin-top-2"><li><span class="ba-sw" style="background:#d4351c"></span>Cost</li><li><span class="ba-sw" style="background:#12436D"></span>Fiscal benefit</li><li><span class="ba-sw" style="background:#28A197"></span>Economic benefit</li></ul></div></div>
        <h2 class="govuk-heading-m">Year by year</h2>
        <p class="govuk-body-s">Bars: local workforce on site for construction, and new operational hires (pre-opening, opening, then turnover replacement). Line: programme participants moving into work each year. Construction shares by year (${Object.entries(BA.PROFILE.constr).sort((a, b) => a[0] - b[0]).map(([k, v]) => (s.open_year + +k) + ' ' + Math.round(v * 100) + '%').join(', ')} of the local peak) and the ${Math.round(BA.PROFILE.preopen * 100)}% pre-opening hiring share are assumptions.</p>
        <div class="ba-chart ba-chart--tall"><canvas id="c-year" role="img" aria-label="Local demand and programme outcomes by year"></canvas></div>
        <ul class="ba-legend govuk-!-margin-top-2"><li><span class="ba-sw" style="background:#F46A25"></span>Construction (local, on site)</li><li><span class="ba-sw" style="background:#12436D"></span>Operational hires</li><li><span class="ba-sw" style="background:#28A197;height:3px"></span>Programme participants into work</li></ul>
        <h2 class="govuk-heading-m">Which assumptions matter most?</h2>
        <p class="govuk-body-s">How the benefit–cost ratio changes when each assumption is 25% lower (purple) or 25% higher (teal), all else equal. The longest bars are where local evidence would most improve the case.</p>
        <div class="ba-chart ba-chart--tall"><canvas id="c-tornado" role="img" aria-label="Sensitivity of the benefit cost ratio"></canvas></div>
        <h2 class="govuk-heading-m govuk-!-margin-top-6">Reading the result</h2>
        <ul class="govuk-list govuk-list--bullet govuk-body-s">
          <li>${T(m.additional + m.leaverAdditional)} <strong>additional</strong> people in work after deadweight (${s.deadweight}%) and displacement (${s.displacement}%), ${T(m.additional)} of them previously workless.</li>
          <li>Present value of costs ${BA.money(m.pvC)}; fiscal benefits ${BA.money(m.pvF)}; economic benefits ${BA.money(m.pvE)} (discounted at ${s.discount}% to ${s.start_year}).</li>
          <li>Target cohorts fill ${Math.round(m.coverage * 100)}% of local demand. ${m.coverage < 1 ? 'The rest would come from people already in work (job-to-job moves, a source of displacement), in-commuters, or a larger programme.' : 'Supply exceeds the local share of demand, so the programme could serve other employers too.'}</li>
        </ul>`;
      const st = { maintainAspectRatio: false };
      const grid = { color: '#e5e6e7' };
      BA.chart(document.getElementById('c-funnel'), { type: 'bar', data: { labels: m.pools.map((x) => x.p.label.length > 42 ? x.p.label.slice(0, 40) + '…' : x.p.label), datasets: [
        { label: 'Engaged', data: m.pools.map((x) => x.engaged), backgroundColor: '#9ec5e8', borderRadius: 3 },
        { label: 'Complete training', data: m.pools.map((x) => x.trained), backgroundColor: '#1d70b8', borderRadius: 3 },
        { label: 'Into work', data: m.pools.map((x) => x.jobs), backgroundColor: '#0b3b66', borderRadius: 3 }] },
        options: Object.assign({ indexAxis: 'y', scales: { x: { grid }, y: { grid: { display: false }, ticks: { font: { size: 11 } } } }, plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${T(c.raw)}` } } } }, st) });
      const lv = { entry: 'Entry level', l2: 'Level 2', l3: 'Level 3', l4: 'Level 4+' };
      BA.chart(document.getElementById('c-demand'), { type: 'bar', data: { labels: m.demand.byLevel.map((x) => lv[x.k]).concat(['Construction (peak)']), datasets: [{ data: m.demand.byLevel.map((x) => x.n).concat([m.demand.constr]), backgroundColor: ['#12436D', '#12436D', '#12436D', '#12436D', '#F46A25'], borderRadius: 4 }] },
        options: Object.assign({ scales: { y: { grid }, x: { grid: { display: false } } }, plugins: { tooltip: { callbacks: { label: (c) => T(c.raw) + ' local jobs' } } } }, st) });
      const yrs = [...new Set(m.costYears.map((x) => x.yr).concat(m.flows.map((x) => x.yr)))].sort();
      BA.chart(document.getElementById('c-flow'), { type: 'bar', data: { labels: yrs, datasets: [
        { label: 'Cost', data: yrs.map((y) => -((m.costYears.find((x) => x.yr === y) || {}).c || 0)), backgroundColor: '#d4351c', borderRadius: 3, stack: 's' },
        { label: 'Fiscal benefit', data: yrs.map((y) => (m.flows.find((x) => x.yr === y) || {}).f || 0), backgroundColor: '#12436D', borderRadius: 3, stack: 's' },
        { label: 'Economic benefit', data: yrs.map((y) => (m.flows.find((x) => x.yr === y) || {}).e || 0), backgroundColor: '#28A197', borderRadius: 3, stack: 's' }] },
        options: Object.assign({ scales: { y: { grid, ticks: { callback: (v) => BA.money(v) } }, x: { grid: { display: false } } }, plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${BA.money(Math.abs(c.raw))}` } } } }, st) });
      BA.chart(document.getElementById('c-year'), { data: { labels: m.timeline.map((x) => x.yr), datasets: [
        { type: 'line', label: 'Participants into work', data: m.timeline.map((x) => x.ready), borderColor: '#28A197', backgroundColor: '#28A197', borderWidth: 2, pointRadius: 3 },
        { type: 'bar', label: 'Construction (local, on site)', data: m.timeline.map((x) => x.constr), backgroundColor: '#F46A25', borderRadius: 3, stack: 'd' },
        { type: 'bar', label: 'Operational hires', data: m.timeline.map((x) => x.ops), backgroundColor: '#12436D', borderRadius: 3, stack: 'd' }] },
        options: Object.assign({ scales: { y: { stacked: true, grid }, x: { stacked: true, grid: { display: false } } }, plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${T(c.raw)}` } } } }, st) });
      document.getElementById('live').textContent = `Benefit–cost ratio ${m.bcr.toFixed(2)}. Target cohorts fill ${Math.round(m.coverage * 100)}% of local demand.`;
      clearTimeout(mcTimer); mcTimer = setTimeout(() => renderMC(s), 250);
      renderCompare();
      // tornado
      const keys = ['wage', 'deadweight', 'displacement', 'persist', 'decay'].concat(BA.ENGINE_POOLS.flatMap((p) => [p.id + '_job', p.id + '_cost', p.id + '_reach', p.id + '_fiscal'])).slice(0, 30);
      const label = (k) => { for (const g of BA.ENGINE_PARAMS) for (const p of g.items) if (p.id === k) return p.label; const [pid, f] = [k.slice(0, k.lastIndexOf('_')), k.slice(k.lastIndexOf('_') + 1)]; const pool = BA.ENGINE_POOLS.find((p) => p.id === pid); return (pool ? pool.label.split(' ').slice(0, 4).join(' ') + '…' : pid) + ' ' + ({ job: 'job rate', cost: 'cost', engage: 'engagement', reach: 'reach', fiscal: 'fiscal value' }[f] || f); };
      const sens = keys.map((k) => { const lo = model(Object.assign({}, s, { [k]: s[k] * 0.75 })).bcr - m.bcr; const hi = model(Object.assign({}, s, { [k]: s[k] * 1.25 })).bcr - m.bcr; return { k, lo, hi, span: Math.abs(hi - lo) }; }).sort((a, b) => b.span - a.span).slice(0, 10);
      BA.chart(document.getElementById('c-tornado'), { type: 'bar', data: { labels: sens.map((x) => label(x.k)), datasets: [
        { label: '−25%', data: sens.map((x) => x.lo), backgroundColor: '#801650', borderRadius: 3 }, { label: '+25%', data: sens.map((x) => x.hi), backgroundColor: '#28A197', borderRadius: 3 }] },
        options: Object.assign({ indexAxis: 'y', scales: { x: { stacked: true, grid, ticks: { callback: (v) => (v > 0 ? '+' : '') + v.toFixed(2) } }, y: { stacked: true, grid: { display: false }, ticks: { font: { size: 11 } } } }, plugins: { legend: { display: true, position: 'bottom' }, tooltip: { callbacks: { label: (c) => `${c.dataset.label}: BCR ${(m.bcr + c.raw).toFixed(2)}` } } } }, st) });
    }
    let mcTimer = null, mcChart = null;
    BA.onLeave = () => { if (mcChart) mcChart.destroy(); };
    function renderMC(st) {
      const r = BA.monteCarlo(st, 1500);
      const el = document.getElementById('mc'); if (!el) return;
      const lo = Math.max(0, r.draws[0]), hi = r.draws[r.draws.length - 1], bins = 30, w = (hi - lo) / bins || 1;
      const counts = Array(bins).fill(0); r.draws.forEach((v) => counts[Math.min(bins - 1, Math.max(0, Math.floor((v - lo) / w)))]++);
      el.innerHTML = `<div class="ba-tiles"><div class="ba-tile ${r.pAbove1 >= 0.8 ? 'ba-tile--good' : r.pAbove1 >= 0.5 ? 'ba-tile--warn' : 'ba-tile--bad'}"><p class="ba-tile__label">Chance the benefit–cost ratio is at least 1</p><p class="ba-tile__value">${r.pAbove1 > 0.99 && r.pAbove1 < 1 ? "over 99%" : r.pAbove1 < 0.01 && r.pAbove1 > 0 ? "under 1%" : Math.round(r.pAbove1 * 100) + "%"}</p></div>
        <div class="ba-tile"><p class="ba-tile__label">Likely range (10th to 90th percentile)</p><p class="ba-tile__value">${r.p10.toFixed(2)} – ${r.p90.toFixed(2)}</p><p class="ba-tile__sub">Median ${r.p50.toFixed(2)}</p></div></div>
        <div class="ba-chart"><canvas id="c-mc" role="img" aria-label="Distribution of the benefit cost ratio across 1,500 model runs: median ${r.p50.toFixed(2)}, 10th percentile ${r.p10.toFixed(2)}, 90th percentile ${r.p90.toFixed(2)}"></canvas></div>`;
      if (mcChart) mcChart.destroy();
      mcChart = new Chart(document.getElementById('c-mc'), { type: 'bar', data: { labels: counts.map((_, i) => (lo + (i + 0.5) * w).toFixed(2)), datasets: [{ data: counts, backgroundColor: counts.map((_, i) => lo + (i + 0.5) * w >= 1 ? '#28A197' : '#801650'), borderRadius: 2, barPercentage: 1, categoryPercentage: 0.95 }] },
        options: { maintainAspectRatio: false, scales: { x: { title: { display: true, text: 'Benefit–cost ratio (purple: below 1)' }, grid: { display: false }, ticks: { maxTicksLimit: 8 } }, y: { title: { display: true, text: 'Model runs' }, grid: { color: '#e5e6e7' } } }, plugins: { tooltip: { callbacks: { title: (c) => 'BCR ≈ ' + c[0].label, label: (c) => c.raw + ' runs' } } } } });
    }
    const SKEY = 'ba-scenarios';
    const loadSc = () => { try { return JSON.parse(localStorage.getItem(SKEY) || '[]'); } catch (e) { return []; } };
    const saveSc = (xs) => { try { localStorage.setItem(SKEY, JSON.stringify(xs)); return true; } catch (e) { return false; } };
    function renderCompare() {
      const el = document.getElementById('cmp'); if (!el) return;
      const scs = loadSc();
      const cols = [{ name: 'Current', s }].concat(scs.map((x) => ({ name: x.name, s: Object.assign({}, s, x.s), q: x.q })));
      const ms = cols.map((c) => model(c.s));
      const R = [['Local jobs to fill by opening', (m) => BA.fmt(Math.round(m.demandOpen), 'count')], ['Filled from target cohorts', (m) => BA.fmt(Math.round(m.tot.jobs), 'count')], ['Share of local demand', (m) => Math.round(m.coverage * 100) + '%'],
        ['Participants', (m) => BA.fmt(Math.round(m.tot.engaged), 'count')], ['Programme cost', (m) => BA.money(m.tot.cost)], ['Additional people in work', (m) => BA.fmt(Math.round(m.additional + m.leaverAdditional), 'count')],
        ['Cost per additional job', (m) => BA.money(m.cpj)], ['Benefit–cost ratio', (m) => m.bcr.toFixed(2)], ['Fiscal-only ratio', (m) => m.bcrF.toFixed(2)]];
      el.innerHTML = `<p class="govuk-body-s">Save the current inputs under a name to compare them side by side. Saved scenarios stay in this browser only; use <em>Copy link</em> to share one.</p>
        <div class="ba-filterbar ba-noprint"><div class="govuk-form-group"><label class="govuk-label govuk-label--s" for="scname">Scenario name</label><input class="govuk-input govuk-input--width-20" id="scname" type="text" maxlength="40"></div><button class="govuk-button govuk-button--secondary govuk-!-margin-bottom-0" id="scsave">Save scenario</button></div>
        ${scs.length ? `<div class="ba-table-wrap"><table class="govuk-table"><thead class="govuk-table__head"><tr class="govuk-table__row"><th class="govuk-table__header" scope="col">Measure</th>${cols.map((c, i) => `<th class="govuk-table__header govuk-table__header--numeric" scope="col">${esc(c.name)}${i ? ` <a class="govuk-link ba-small" href="#/case?${esc(c.q)}">open</a> <a class="govuk-link ba-small" href="#" data-del="${i - 1}">remove</a>` : ''}</th>`).join('')}</tr></thead><tbody class="govuk-table__body">${R.map(([l, f]) => `<tr class="govuk-table__row"><th class="govuk-table__header" scope="row">${l}</th>${ms.map((m) => `<td class="govuk-table__cell govuk-table__cell--numeric">${f(m)}</td>`).join('')}</tr>`).join('')}</tbody></table></div>` : ''}`;
      document.getElementById('scsave').addEventListener('click', () => {
        const name = document.getElementById('scname').value.trim() || 'Scenario ' + (scs.length + 1);
        const q = new URLSearchParams(); Object.keys(s).forEach((k) => q.set(k, s[k]));
        if (!saveSc(scs.concat([{ name, s: Object.assign({}, s), q: q.toString() }]).slice(-6))) document.getElementById('scsave').textContent = 'Browser storage unavailable';
        renderCompare();
      });
      el.querySelectorAll('[data-del]').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); scs.splice(+a.dataset.del, 1); saveSc(scs); renderCompare(); }));
    }
    function sync() {
      const q = new URLSearchParams();
      Object.keys(s).forEach((k) => q.set(k, s[k]));
      history.replaceState(null, '', '#/case?' + q.toString());
    }
    app.querySelectorAll('input[data-k]').forEach((el) => el.addEventListener('input', () => { const v = parseFloat(el.value); if (!isNaN(v)) { s[el.dataset.k] = v; render(); sync(); } }));
    app.querySelectorAll('[data-preset]').forEach((b) => b.addEventListener('click', () => {
      const f = PRESETS[b.dataset.preset];
      BA.ENGINE_POOLS.forEach((p) => { s[p.id + '_engage'] = +(p.engage * f).toFixed(1); s[p.id + '_job'] = Math.min(95, +(p.job * Math.sqrt(f)).toFixed(1)); });
      app.querySelectorAll('input[data-k]').forEach((el) => (el.value = s[el.dataset.k])); render(); sync();
    }));
    document.getElementById('reset').addEventListener('click', () => { location.hash = '#/case'; });
    document.getElementById('share').addEventListener('click', async (e) => { sync(); try { await navigator.clipboard.writeText(location.href); e.target.textContent = 'Link copied'; } catch (_) { e.target.textContent = 'Copy the address bar'; } });
    document.getElementById('csv').addEventListener('click', () => {
      const m = BA.lastModel;
      const rows = Object.entries(s).map(([k, v]) => ({ section: 'input', name: k, value: v }))
        .concat(m.pools.map((x) => ({ section: 'cohort', name: x.p.label, pool: Math.round(x.count), can_reach: Math.round(x.reachable), engaged: Math.round(x.engaged), trained: Math.round(x.trained), into_work: Math.round(x.jobs), cost: Math.round(x.cost) })))
        .concat([['local_demand_at_opening', m.demandOpen], ['additional_jobs', m.additional + m.leaverAdditional], ['pv_costs', m.pvC], ['pv_fiscal', m.pvF], ['pv_economic', m.pvE], ['bcr', m.bcr], ['bcr_fiscal', m.bcrF]].map(([n, v]) => ({ section: 'result', name: n, value: Math.round(v * 100) / 100 })));
      BA.downloadCSV('bedfordshire-skills-business-case.csv', rows);
    });
    render();
  });
})();
