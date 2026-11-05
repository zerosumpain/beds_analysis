/* Pages: summary, cohorts, sources, lineage, dataset detail, analysis, method. */
(function () {
  'use strict';
  const BA = window.BA;
  const esc = BA.esc;

  /* What the brief asked for, mapped to the datasets that answer it.
     ceiling = the best achievable from open data (set by the research), status is then
     degraded at runtime if the datasets did not load. */
  BA.SPEC = [
    { cohort: '16-19', items: [
      { item: 'Population and demographic data', ds: ['pop_mye', 'pop_snpp', 'pop_lsoa', 'census_lsoa', 'school_pipeline'], ceiling: 'yes',
        note: 'Single-year-of-age estimates by LA, projections to 2040, LSOA counts and a school-roll cohort roll-forward to the opening year.' },
      { item: 'Participation in education and training', ds: ['dfe_neet', 'dfe_ks4_destinations'], ceiling: 'yes',
        note: 'DfE LA participation (16-17) and KS4 destinations. Age 18 participation is only published nationally.' },
      { item: 'Further education and technical education', ds: ['dfe_fe_skills', 'dfe_16_18_la', 'providers'], ceiling: 'partly',
        note: 'FE participation by learner home LA, 16-18 results by qualification type and a provider map. T Level take-up is not published by LA of residence.' },
      { item: 'Apprenticeships', ds: ['dfe_apprenticeships'], ceiling: 'yes', note: 'Starts and achievements by learner home LA, age, level and sector subject area. Small cells are rounded or suppressed.' },
      { item: 'NEET and at-risk-of-NEET populations', ds: ['dfe_neet', 'dfe_care_leavers', 'dfe_ehcp', 'dfe_absence_exclusions', 'imd2025'], ceiling: 'partly',
        note: 'NEET and "not known" are published by LA. "At risk of NEET" (RONI) scores are held locally, so the tool uses proxies: absence, SEND, care leavers and deprivation.' },
      { item: 'Qualifications, attainment and skills levels', ds: ['dfe_ks4_la', 'dfe_ks4_school', 'dfe_16_18_la', 'dfe_l2l3_19'], ceiling: 'yes',
        note: 'KS4 and 16-18 attainment by LA and school, and Level 2 and Level 3 by age 19, including the disadvantage gap.' },
    ] },
    { cohort: '18-24', items: [
      { item: 'Employment and unemployment', ds: ['aps', 'claimant', 'census_age_activity'], ceiling: 'partly',
        note: 'APS figures for 16-24 at LA level have wide confidence intervals and are often suppressed. Census 2021 by age is robust but dated and was taken during furlough.' },
      { item: 'Economic inactivity', ds: ['aps', 'census_age_activity'], ceiling: 'partly', note: 'Census gives inactivity by reason by age band. APS youth inactivity is unreliable at LA level.' },
      { item: 'Benefits or claimant data', ds: ['claimant', 'claimant_lsoa', 'dwp_uc'], ceiling: 'partly',
        note: 'Claimant count by age is monthly down to LSOA. The Universal Credit by conditionality fetcher (Stat-Xplore) is built and switches on once a free API key is added.' },
      { item: 'Participation in FE, adult skills and apprenticeships', ds: ['dfe_fe_skills', 'dfe_apprenticeships'], ceiling: 'yes', note: 'Age bands 19-24 by learner home LA.' },
      { item: 'Qualifications and skills', ds: ['dfe_l2l3_19', 'aps', 'census_lsoa'], ceiling: 'partly', note: 'L2 and L3 by 19 (to age 25). Census qualifications are for all ages 16+, not 18-24, below LA level.' },
    ] },
    { cohort: '25+ inactive', items: [
      { item: 'Size and characteristics of the inactive population', ds: ['census_age_activity', 'aps', 'census_lsoa', 'census_barriers', 'childcare'], ceiling: 'yes', note: 'Census 2021 by age band and reason (LA and LSOA), with APS for trend. Barriers by neighbourhood: car access, English, lone parenthood, health. Childcare places per child by LA.' },
      { item: 'Reasons for inactivity', ds: ['aps', 'census_age_activity', 'census_lsoa'], ceiling: 'yes', note: 'Student, retired, looking after home, long-term sick or disabled, other. APS reasons have wide CIs at LA level.' },
      { item: 'Skills and qualification levels', ds: ['aps', 'census_lsoa'], ceiling: 'partly', note: 'Open tables give quals for the whole population. Qualifications of the inactive only are not open at LA level and need a commissioned Census table or APS microdata.' },
      { item: 'Inactive people not claiming benefits', ds: [], ceiling: 'no',
        note: 'No open dataset counts them directly. The business case engine estimates them as the inactive population minus out-of-work benefit recipients, labelled as an estimate (see Gaps & linkage).' },
    ] },
  ];

  function specStatus(it) {
    if (!it.ds.length) return it.ceiling;
    const have = it.ds.filter(BA.has).length;
    if (!have) return 'no';
    if (it.ceiling === 'yes' && have < Math.ceil(it.ds.length / 2)) return 'partly';
    return it.ceiling;
  }
  BA.specStatus = specStatus;

  function coverageTable(filterCohort) {
    const groups = BA.SPEC.filter((g) => !filterCohort || g.cohort === filterCohort);
    let html = '<div class="ba-table-wrap"><table class="govuk-table"><thead class="govuk-table__head"><tr class="govuk-table__row">' +
      (filterCohort ? '' : '<th class="govuk-table__header" scope="col">Cohort</th>') +
      '<th class="govuk-table__header" scope="col">What the brief asked for</th><th class="govuk-table__header" scope="col">Status</th><th class="govuk-table__header" scope="col">How it is met, and the limits</th><th class="govuk-table__header" scope="col">Datasets</th></tr></thead><tbody class="govuk-table__body">';
    groups.forEach((g) => g.items.forEach((it, i) => {
      html += '<tr class="govuk-table__row">' +
        (filterCohort ? '' : i === 0 ? `<th class="govuk-table__header" scope="row" rowspan="${g.items.length}">${esc(BA.COHORTS[g.cohort].label)}</th>` : '') +
        `<td class="govuk-table__cell">${esc(it.item)}</td><td class="govuk-table__cell">${BA.status(specStatus(it))}</td><td class="govuk-table__cell ba-small">${esc(it.note)}</td>` +
        `<td class="govuk-table__cell">${it.ds.map((d) => BA.has(d) ? `<a class="govuk-link ba-pill" href="#/data/${d}">${esc(d)}</a>` : `<span class="ba-pill" title="not loaded">${esc(d)} ✕</span>`).join('') || '<span class="ba-small">estimate only</span>'}</td></tr>`;
    }));
    return html + '</tbody></table></div>';
  }
  BA.coverageTable = coverageTable;

  /* ---------- headline tiles ---------- */
  // Each tile: indicator id(s) tried in order; code BEDS = sum of the three LAs.
  BA.TILES = [];
  async function tileValue(t) {
    if (t.fn) return t.fn();
    for (const id of [].concat(t.ind)) {
      if (!BA.indicators[id]) continue;
      if (t.code === 'BEDS' && t.sum) { const v = await BA.sumLAs(id, t.breakdown ?? null); if (v != null) return { v, id }; }
      const r = await BA.value(id, t.code || 'BEDS', t.breakdown ?? null);
      if (r && r.value != null) return { v: r.value, id, period: r.period };
    }
    return null;
  }
  async function renderTiles(el, tiles) {
    const out = await Promise.all(tiles.map(async (t) => ({ t, r: await tileValue(t).catch(() => null) })));
    el.innerHTML = out.filter((x) => x.r).map(({ t, r }) => {
      const ind = BA.indicators[r.id];
      return `<div class="ba-tile ${t.tone ? 'ba-tile--' + t.tone : ''}"><p class="ba-tile__label">${esc(t.label)}</p><p class="ba-tile__value ba-num">${t.unit === 'percent' || ind.unit === 'percent' ? BA.fmt(r.v, 'percent') : BA.big(r.v)}</p><p class="ba-tile__sub">${esc(t.sub || '')}${r.period ? ' · ' + esc(r.period) : ''} · <a class="govuk-link" href="#/data/${ind.dataset}">source</a></p></div>`;
    }).join('') || '<p class="govuk-body ba-small">Headline figures appear once the data pipeline has run.</p>';
  }
  BA.renderTiles = renderTiles;

  /* ---------- summary ---------- */
  BA.route(/^\/$/, async (app) => {
    const a = BA.assessment || {}; const p = a.project || {};
    const counts = { yes: 0, partly: 0, no: 0 };
    BA.SPEC.forEach((g) => g.items.forEach((it) => counts[specStatus(it)]++));
    const latestFetch = BA.catalogue.map((m) => m.retrieved_at).sort().pop();
    app.innerHTML = `
      <span class="govuk-caption-xl">Bedfordshire: Bedford, Central Bedfordshire and Luton</span>
      <h1 class="govuk-heading-xl">Labour supply, skills and training evidence base</h1>
      <div class="govuk-grid-row"><div class="govuk-grid-column-two-thirds">
        <p class="govuk-body-l">A major leisure and infrastructure development, ${esc(p.name ? 'the Universal United Kingdom Resort' : 'a resort')}, is planned on the former brickworks at Kempston Hardwick, south-west of Bedford, and is due to open in 2031. This tool brings together the best publicly available data on the potential local workforce. Its purpose is an evidence-based case for investment in skills and training, across construction, pre-opening and operations.</p>
        <p class="govuk-body">It covers three cohorts: <strong>16 to 19 year olds</strong>, <strong>18 to 24 year olds</strong> and <strong>economically inactive adults aged 25 and over</strong>. Every figure is an aggregate from published statistics. The tool does not identify individuals.</p>
      </div><div class="govuk-grid-column-one-third">
        <div class="ba-callout"><p class="govuk-body govuk-!-margin-bottom-1"><strong>${BA.catalogue.length}</strong> datasets loaded, <strong>${Object.keys(BA.indicators).length}</strong> indicators</p>
        <p class="govuk-body govuk-!-margin-bottom-1"><strong>${BA.sources.length}</strong> sources assessed</p>
        <p class="govuk-body govuk-!-margin-bottom-0 ba-small">Data last fetched ${esc(latestFetch || '–')}</p></div>
      </div></div>

      <h2 class="govuk-heading-l">Key findings</h2>
      <div class="ba-findings" id="findings"><p class="govuk-body">Working out the findings from the latest data…</p></div>

      <h2 class="govuk-heading-l">Headline figures</h2>
      <div class="ba-tiles" id="tiles"></div>

      ${p.name ? projectBlock(p) : ''}

      <h2 class="govuk-heading-l" id="coverage">What the brief asked for, and what could be met</h2>
      <p class="govuk-body">Of ${counts.yes + counts.partly + counts.no} requirements, <strong>${counts.yes} met</strong>, <strong>${counts.partly} partly met</strong> and <strong>${counts.no} not met</strong> from open data. Partly met usually means one of three things: the data exists but not at a useful geography; it is a survey with wide confidence intervals; or it is held locally and not published.</p>
      ${coverageTable()}

      <h2 class="govuk-heading-l">Answers to the four questions</h2>
      <div class="ba-two">${qBlock('A. What can be answered from existing open data?', (a.can_answer || []).filter((x) => x.answerable !== 'no').slice(0, 8).map((x) => `${BA.status(x.answerable)} ${esc(x.question)}`), '#/analysis#a')}
      ${qBlock('B. Where are the important data gaps?', (a.gaps || []).slice(0, 8).map((x) => `<strong>${esc(x.gap)}</strong>: ${esc(x.who_is_invisible || '')}`), '#/analysis#b')}
      ${qBlock('C. What could be derived by linking datasets?', (a.linkage || []).slice(0, 8).map((x) => `<strong>${esc(x.analysis)}</strong>`), '#/analysis#c')}
      ${qBlock('D. What additional data would materially improve it?', (a.additional_data || []).slice(0, 8).map((x) => `<strong>${esc(x.data)}</strong> (${esc(x.likely_holder || '')})`), '#/analysis#d')}</div>

      <h2 class="govuk-heading-l" id="lineage">Data lineage at a glance</h2>
      <p class="govuk-body">Each feed, who publishes it, how often it updates and how far to trust it. Select a dataset for its full lineage: the exact URL fetched, the transformations, a checksum and the indicators it produces.</p>
      ${lineageTable()}

      <h2 class="govuk-heading-l">Risks and issues</h2>
      ${risksTable(a.risks_issues || [])}

      <h2 class="govuk-heading-l">Additional opportunities</h2>
      <div class="ba-cards">${(a.opportunities || []).map((o) => `<div class="ba-card"><h3 class="govuk-heading-s">${esc(o.title)}</h3><p class="govuk-body-s">${esc(o.description)}</p>${o.value ? `<p class="govuk-body-s ba-small"><strong>Value:</strong> ${esc(o.value)}</p>` : ''}</div>`).join('')}</div>

      <h2 class="govuk-heading-l govuk-!-margin-top-8">Recommended minimum dataset</h2>
      ${minDatasetTable(a.minimum_dataset || [])}
    `;
    renderTiles(document.getElementById('tiles'), BA.TILES);
    renderFindings(document.getElementById('findings')).catch((e) => { console.error(e); document.getElementById('findings').innerHTML = ''; });
  });

  // Findings are computed from the loaded data each time, so they follow every refresh.
  async function renderFindings(el) {
    const T = (n) => BA.fmt(Math.round(n), 'count');
    const pc = (n) => Math.round(n) + '%';
    const v = async (id, code, bd) => { if (!BA.indicators[id]) return null; const r = await BA.value(id, code || 'BEDS', bd === undefined ? null : bd); return r && r.value != null ? r : null; };
    const out = [];
    const add = (num, text, href, tone) => out.push({ num, text, href, tone });
    const { s } = await BA.engineState(BA.REACH_DEFAULT);
    const m = BA.engineModel(s);
    add(T(m.demand.ops), `of the resort's ${T(s.ops_jobs)} operational jobs at opening in ${s.open_year} are expected to go to local residents, on top of ${T(s.constr_peak)} construction workers on site at the peak.`, '#/case');
    add(pc(100 * m.tot.jobs / Math.max(1, m.demand.ops)), `of those local jobs (about ${T(m.tot.jobs)}) could realistically be filled from the three target cohorts on the central assumptions. The other ${T(Math.max(0, m.demand.ops - m.tot.jobs))} would come from people already in work, in-commuters or a bigger programme.`, '#/balance', 'warn');
    const tt = await BA.travelLsoa();
    if (tt) {
      const w = await BA.lsoaWeights(['popsa_16_64']); const tot = Object.values(w).reduce((a, x) => a + x, 0);
      const share = (o) => { let n = 0; Object.entries(w).forEach(([c, x]) => (n += x * (BA.reachFrac(tt[c], o) || 0))); return 100 * n / tot; };
      const pt = share({ mode: 'pt', minutes: 45 }), car = share({ mode: 'car', minutes: 45 }), late = share({ mode: 'pt', minutes: 90, late: true }), ptAny = share({ mode: 'pt', minutes: 90 });
      add(pc(pt), `of working-age residents can get to an 08:30 shift within 45 minutes by public transport, against ${pc(car)} by car in free-flowing traffic. Transport, not distance, is the binding constraint for people without a car.`, '#/balance?mode=pt', pt < 50 ? 'bad' : 'warn');
      if (ptAny > 0) add(pc(late), `of working-age residents could get home by public transport after a shift ending at 22:30 (${pc(ptAny)} can get there by public transport within 90 minutes). Late finishes need staff transport or shift design.`, '#/balance?mode=pt&late=1&min=90', 'bad');
    }
    const a25 = await v('snpp_16_19'); const rows = BA.indicators.snpp_16_19 ? (await BA.rowsFor('snpp_16_19')).filter((r) => r.code === 'BEDS') : [];
    const y0 = rows.find((r) => String(r.period) === '2025'), y1 = rows.find((r) => String(r.period) === String(s.open_year));
    if (a25 && y0 && y1) add((y1.value >= y0.value ? '+' : '') + T(y1.value - y0.value), `more 16 to 19 year olds in Bedfordshire by ${s.open_year} than in 2025 (${T(y0.value)} to ${T(y1.value)}, ONS projection). Today's secondary pupils are the opening-year intake.`, '#/cohort/16-19', 'good');
    const ia = ['census_inact_home_family', 'census_inact_lt_sick', 'census_inact_other'];
    const parts = await Promise.all(ia.map((id) => v(id, 'BEDS', 'age 25-64')));
    if (parts.every(Boolean)) add(T(parts.reduce((x, r) => x + r.value, 0)), `adults aged 25-64 were economically inactive for reasons other than study or retirement at the 2021 Census, ${T(parts[1].value)} of them long-term sick or disabled. Most are invisible in benefit data.`, '#/cohort/25-inactive');
    const lut = await v('aps_inact_rate_16_64', 'E06000032'), eng = await v('aps_inact_rate_16_64', 'E92000001');
    if (lut && eng) add(BA.fmt(lut.value, 'percent'), `of Luton's 16-64 population is economically inactive (England ${BA.fmt(eng.value, 'percent')}, ${esc(lut.period)}). Luton residents are not counted in the promoter's 69% local-jobs figure.`, '#/cohort/25-inactive', 'bad');
    let neet = 0, ok = true; for (const c of Object.keys(BA.LAS)) { const r = await v('dfe_neet_n_neet_nk', c, 'age 16-17'); if (!r) { ok = false; break; } neet += r.value; }
    if (ok) add(T(neet), `16 and 17 year olds are NEET or their activity is not known, the most direct target for pre-employment and apprenticeship routes.`, '#/cohort/16-19', 'warn');
    const wh = await v('bres_emp_warehousing'), af = await v('bres_emp_accom_food');
    if (wh && af) add(T(wh.value), `people already work in warehousing and logistics in Bedfordshire, and ${T(af.value)} in accommodation and food. The resort will compete with both for entry-level staff.`, '#/balance', 'warn');
    const rent = await v('aff_rent_share_nlw', 'E06000055');
    if (rent) add(BA.fmt(rent.value, 'percent'), `of a full-time National Living Wage worker's gross pay would go on the average private rent in Bedford. Pay and housing costs affect who can take the jobs.`, '#/data/affordability', 'warn');
    el.innerHTML = out.map((f) => `<a class="ba-finding ba-finding--${f.tone || 'info'}" href="${f.href}"><span class="ba-finding__num">${f.num}</span><span class="ba-finding__text">${f.text}</span></a>`).join('');
  }

  function projectBlock(p) {
    const status = String(p.status_as_of || '');
    const asOf = (status.match(/^As at ([^:]+):/) || [])[1];
    const steps = status.replace(/^As at [^:]+:\s*/, '').split(/\s*\(\d+\)\s*/).map((x) => x.trim().replace(/\.$/, '')).filter(Boolean);
    const jobs = (p.jobs_claims || []).map((j) => `<li><strong>${esc(j.figure)}</strong>: ${esc(j.what)}. ${BA.link(j.url, j.source_title)}${j.date ? ' (' + esc(j.date) + ')' : ''}</li>`).join('');
    const tl = (p.timeline || []).map((t) => `<tr class="govuk-table__row"><td class="govuk-table__cell"><strong>${esc(t.phase)}</strong></td><td class="govuk-table__cell">${esc(t.years)}</td><td class="govuk-table__cell ba-small">${esc(t.description)}</td></tr>`).join('');
    const key = (p.jobs_claims || []).filter((j) => /^(nearly 20,000|8,050|5,380|5,530)/.test(j.figure));
    return `<h2 class="govuk-heading-l">The development</h2>
      <p class="govuk-body">${esc(p.name)}. ${esc(p.visitors ? String(p.visitors).split(';')[0] + '.' : '')}</p>
      <div class="ba-tiles">${key.map((j) => `<div class="ba-tile"><p class="ba-tile__label">${esc(j.what.split(/[(;]/)[0])}${/^nearly/i.test(j.figure) ? ' (nearly)' : ''}</p><p class="ba-tile__value">${esc(j.figure.replace(/^(nearly|c\.|around|about|~)\s*/i, '').split(' ')[0])}</p><p class="ba-tile__sub">${BA.link(j.url, j.source_title.split(/[;:(]/)[0])}</p></div>`).join('')}</div>
      <div class="ba-two"><div><h3 class="govuk-heading-s">Milestones${asOf ? ' (as at ' + esc(asOf) + ')' : ''}</h3><ol class="govuk-list govuk-list--number govuk-body-s">${steps.map((x) => '<li>' + esc(x) + '</li>').join('')}</ol></div>
      <div>${tl ? '<table class="govuk-table"><caption class="govuk-table__caption govuk-table__caption--s">Phases</caption><tbody class="govuk-table__body">' + tl + '</tbody></table>' : ''}</div></div>
      ${jobs ? `<details class="govuk-details"><summary class="govuk-details__summary"><span class="govuk-details__summary-text">All ${(p.jobs_claims || []).length} published jobs and skills claims, with sources</span></summary><div class="govuk-details__text"><ul class="govuk-list govuk-list--bullet govuk-body-s">${jobs}</ul></div></details>` : ''}
      ${p.transport ? `<details class="govuk-details"><summary class="govuk-details__summary"><span class="govuk-details__summary-text">Transport and access</span></summary><div class="govuk-details__text govuk-body-s">${esc(p.transport)}</div></details>` : ''}`;
  }
  function qBlock(title, items, href) {
    return `<div><h3 class="govuk-heading-m">${esc(title)}</h3>${items.length ? '<ul class="govuk-list govuk-list--bullet govuk-body-s">' + items.map((i) => '<li>' + i + '</li>').join('') + '</ul>' : '<p class="govuk-body-s">Research pending.</p>'}<p class="govuk-body-s"><a class="govuk-link" href="${href}">Read the full answer</a></p></div>`;
  }
  const qualityDot = (q) => { q = String(q || '').toLowerCase(); const c = /accredited|national statistic/.test(q) ? '#00703c' : /official/.test(q) ? '#1d70b8' : /survey|estimate|in development|experimental|management/.test(q) ? '#f47738' : '#b1b4b6'; return `<span class="ba-quality" style="background:${c}"></span>`; };
  function lineageTable() {
    if (!BA.catalogue.length) return '<p class="govuk-body">No datasets loaded yet.</p>';
    return `<div class="ba-table-wrap"><table class="govuk-table"><thead class="govuk-table__head"><tr class="govuk-table__row">
      <th class="govuk-table__header">Dataset</th><th class="govuk-table__header">Provider</th><th class="govuk-table__header">Lowest geography</th><th class="govuk-table__header">Latest period</th><th class="govuk-table__header">Update frequency</th><th class="govuk-table__header">Access</th><th class="govuk-table__header">Quality</th></tr></thead><tbody class="govuk-table__body">
      ${BA.catalogue.map((m) => `<tr class="govuk-table__row"><td class="govuk-table__cell"><a class="govuk-link" href="#/data/${m.id}">${esc(m.title)}</a></td><td class="govuk-table__cell ba-small">${esc(m.publisher)}</td><td class="govuk-table__cell ba-small">${esc(m.geography)}</td><td class="govuk-table__cell ba-small">${esc(m.latest_period || m.period)}</td><td class="govuk-table__cell ba-small">${esc(m.frequency)}${m.next_update ? '<br>next: ' + esc(m.next_update) : ''}</td><td class="govuk-table__cell ba-small">${esc(m.access)}</td><td class="govuk-table__cell ba-small">${qualityDot(m.quality)}${esc(String(m.quality || '').slice(0, 140))}${String(m.quality || '').length > 140 ? '…' : ''}</td></tr>`).join('')}
      </tbody></table></div>`;
  }
  const lvl = (s) => { s = String(s || '').toLowerCase(); return s.startsWith('h') ? 3 : s.startsWith('m') ? 2 : s.startsWith('l') ? 1 : 0; };
  function risksTable(rs) {
    if (!rs.length) return '<p class="govuk-body">Research pending.</p>';
    rs = rs.slice().sort((x, y) => lvl(y.likelihood) * lvl(y.impact) - lvl(x.likelihood) * lvl(x.impact));
    const tag = (s) => `<strong class="govuk-tag govuk-tag--${lvl(s) === 3 ? 'red' : lvl(s) === 2 ? 'yellow' : 'green'}">${esc(s || '–')}</strong>`;
    return `<div class="ba-table-wrap"><table class="govuk-table"><thead class="govuk-table__head"><tr class="govuk-table__row"><th class="govuk-table__header">Risk or issue</th><th class="govuk-table__header">Type</th><th class="govuk-table__header">Likelihood</th><th class="govuk-table__header">Impact</th><th class="govuk-table__header">Mitigation</th></tr></thead><tbody class="govuk-table__body">
      ${rs.map((r) => `<tr class="govuk-table__row"><td class="govuk-table__cell"><strong>${esc(r.title)}</strong><br><span class="ba-small">${esc(r.description)}</span></td><td class="govuk-table__cell">${esc(r.type)}</td><td class="govuk-table__cell">${tag(r.likelihood)}</td><td class="govuk-table__cell">${tag(r.impact)}</td><td class="govuk-table__cell ba-small">${esc(r.mitigation)}</td></tr>`).join('')}</tbody></table></div>`;
  }
  function minDatasetTable(rows) {
    if (!rows.length) return '<p class="govuk-body">Research pending.</p>';
    return `<div class="ba-table-wrap"><table class="govuk-table"><thead class="govuk-table__head"><tr class="govuk-table__row"><th class="govuk-table__header">Source</th><th class="govuk-table__header">Measures</th><th class="govuk-table__header">Geography</th><th class="govuk-table__header">Frequency</th><th class="govuk-table__header">Role in the case</th></tr></thead><tbody class="govuk-table__body">
      ${rows.map((r) => `<tr class="govuk-table__row"><td class="govuk-table__cell"><strong>${esc(r.source)}</strong></td><td class="govuk-table__cell ba-small">${esc([].concat(r.measures).join('; '))}</td><td class="govuk-table__cell ba-small">${esc(r.geography)}</td><td class="govuk-table__cell ba-small">${esc(r.frequency)}</td><td class="govuk-table__cell ba-small">${esc(r.role_in_case)}</td></tr>`).join('')}</tbody></table></div>`;
  }
  BA.risksTable = risksTable; BA.minDatasetTable = minDatasetTable;

  /* ---------- cohort pages ---------- */
  const COHORT_INTRO = {
    '16-19': 'Young people moving from compulsory schooling into post-16 education, training and work. They are the core of the apprenticeship pipeline and of entry-level operational roles from opening. Today\'s secondary pupils will be this cohort when the resort opens.',
    '18-24': 'Young adults entering the labour market. Unemployment, inactivity and claimant rates are higher here, and many are at risk of scarring from early worklessness. Hospitality and leisure traditionally recruit heavily from this age group.',
    '25-inactive': 'Adults who are neither working nor looking for work: long-term sick or disabled people, carers, people looking after home and family, early retirees and discouraged workers. Many are invisible to benefit data. Flexible, part-time and seasonal roles could reach them.',
  };
  BA.route(/^\/cohort\/([\w+-]+)$/, async (app, slug) => {
    const key = Object.keys(BA.COHORTS).find((k) => BA.COHORTS[k].slug === slug);
    if (!key) throw new Error('Unknown cohort');
    const inds = Object.values(BA.indicators).filter((i) => BA.cohortsOf(i).includes(key));
    const byDs = {};
    inds.forEach((i) => (byDs[i.dataset] = byDs[i.dataset] || []).push(i));
    const ORDER = {
      '16-19': ['dfe_neet', 'school_pipeline', 'pop_mye', 'pop_snpp', 'dfe_apprenticeships', 'dfe_fe_skills', 'dfe_ks4_destinations', 'dfe_ks5_destinations', 'dfe_l2l3_19', 'dfe_ks4_la', 'dfe_16_18_la', 'dfe_care_leavers', 'dfe_ehcp', 'dfe_absence_exclusions'],
      '18-24': ['claimant', 'pop_mye', 'census_age_activity', 'aps', 'dfe_apprenticeships', 'dfe_fe_skills', 'dfe_l2l3_19', 'dfe_care_leavers', 'claimant_lsoa'],
      '25+ inactive': ['census_age_activity', 'aps', 'dwp_uc', 'census_barriers', 'census_lsoa', 'childcare', 'claimant', 'dfe_fe_skills', 'dfe_apprenticeships'],
    }[key] || [];
    const rank = (d) => { const i = ORDER.indexOf(d); return i < 0 ? 99 : i; };
    const dsIds = Object.keys(byDs).sort((a, b) => rank(a) - rank(b));
    const sel = BA.query.get('ds') || '';
    app.innerHTML = `
      <span class="govuk-caption-xl">Cohort</span>
      <h1 class="govuk-heading-xl">${esc(BA.COHORTS[key].label)}</h1>
      <p class="govuk-body-l">${esc(COHORT_INTRO[slug] || '')}</p>
      <div class="ba-tiles" id="tiles"></div>
      ${key === 'context' ? '' : `<h2 class="govuk-heading-l">Coverage against the brief</h2>${coverageTable(key)}`}
      <h2 class="govuk-heading-l">Indicators</h2>
      <p class="govuk-body">${inds.length} indicators from ${dsIds.length} datasets. The bars show the latest period. Black whiskers are 95% confidence intervals where the source is a survey. Switch to <em>Trend</em> for history, or open the dataset for its lineage and caveats.</p>
      <div class="ba-filterbar ba-noprint"><div class="govuk-form-group"><label class="govuk-label govuk-label--s" for="dsf">Dataset</label>
        <select class="govuk-select" id="dsf"><option value="">All datasets</option>${dsIds.map((d) => `<option value="${d}" ${d === sel ? 'selected' : ''}>${esc((BA.meta(d) || {}).title || d)}</option>`).join('')}</select></div>
        ${BA.legendHTML(BA.GEO_ORDER)}</div>
      <div id="cards"></div>`;
    renderTiles(document.getElementById('tiles'), BA.TILES.filter((t) => (t.cohorts || []).includes(key)));
    document.getElementById('dsf').addEventListener('change', (e) => { BA.keepScroll = true; location.hash = '#/cohort/' + slug + (e.target.value ? '?ds=' + e.target.value : ''); });
    const cards = document.getElementById('cards');
    for (const d of dsIds.filter((d) => !sel || d === sel)) {
      const m = BA.meta(d);
      const sec = BA.el(`<section><h3 class="govuk-heading-m govuk-!-margin-top-6">${esc(m.title)} <span class="ba-small">· ${esc(m.publisher)} · ${esc(m.latest_period || m.period)}</span></h3><div class="ba-cards"></div></section>`);
      cards.appendChild(sec);
      byDs[d].forEach((ind) => sec.querySelector('.ba-cards').appendChild(indicatorCard(ind)));
    }
  });

  // Lazily rendered indicator card.
  function indicatorCard(ind) {
    const card = BA.el(`<div class="ba-card"><h4 class="govuk-heading-s">${esc(ind.label)}</h4><p class="ba-card__meta">${esc(ind.description || '')}</p><div class="ba-chart"><canvas aria-label="${esc(ind.label)} by area" role="img"></canvas></div><p class="ba-card__foot"></p></div>`);
    const io = new IntersectionObserver((ents) => { if (ents.some((e) => e.isIntersecting)) { io.disconnect(); fillCard(card, ind).catch((e) => { card.querySelector('.ba-chart').innerHTML = '<p class="ba-small">' + esc(e.message) + '</p>'; }); } }, { rootMargin: '300px' });
    io.observe(card);
    return card;
  }
  async function fillCard(card, ind) {
    const all = await BA.rowsFor(ind.id);
    const rows = all.filter((r) => ['LA', 'county', 'region', 'country'].includes(r.level));
    const chartBox = card.querySelector('.ba-chart'); const foot = card.querySelector('.ba-card__foot');
    const smallArea = all.some((r) => ['LSOA', 'MSOA', 'ward', 'point', 'PCON'].includes(r.level));
    const mapLink = smallArea ? `<a class="govuk-link" href="#/explore?ind=${ind.id}">View on map</a>` : '';
    const dsLink = `<a class="govuk-link" href="#/data/${ind.dataset}">Lineage</a>`;
    if (!rows.length) {
      chartBox.outerHTML = `<p class="govuk-body-s">Small-area indicator: ${all.length} areas. ${mapLink}</p>`;
      foot.innerHTML = dsLink; return;
    }
    let plain = rows.filter((r) => !r.breakdown);
    let bdRows = rows.filter((r) => r.breakdown);
    const bds = [...new Set(bdRows.map((r) => r.breakdown))];
    // A single breakdown (e.g. every row is "age 16-17") is just the headline series.
    if (!plain.length && bds.length === 1) { plain = bdRows; bdRows = []; card.querySelector('.ba-card__meta').textContent += ' (' + bds[0] + ')'; }
    // Prefer an "all" style breakdown as the headline where one exists.
    if (!plain.length && bds.length > 1) {
      // Headline = an explicit "all/total" breakdown, else the one covering most areas, then the shortest label.
      const cover = (b) => new Set(bdRows.filter((r) => r.breakdown === b).map((r) => r.code)).size;
      const head = bds.find((b) => /^(all|total|all ages|age 16-64)\b/i.test(b)) || bds.slice().sort((a, b) => cover(b) - cover(a) || a.length - b.length)[0];
      plain = bdRows.filter((r) => r.breakdown === head);
      bdRows = bdRows.filter((r) => r.breakdown !== head);
      card.querySelector('.ba-card__meta').textContent += ' Headline: ' + head + '.';
    }
    const periods = [...new Set(plain.map((r) => r.period))];
    const lp = BA.latestPeriod(plain.length ? plain : bdRows);
    const canvas = card.querySelector('canvas');
    const modes = [];
    if (plain.length) modes.push('Latest');
    if (periods.length > 1) modes.push('Trend');
    if (bdRows.length) modes.push('Breakdown');
    modes.push('Table');
    const tableBox = BA.el('<div class="ba-cardtable" hidden></div>');
    chartBox.after(tableBox);
    const draw = (mode) => {
      const old = Chart.getChart(canvas); if (old) old.destroy();
      chartBox.hidden = mode === 'Table'; tableBox.hidden = mode !== 'Table';
      if (mode === 'Table') {
        const ord = (r) => { const i = BA.GEO_ORDER.indexOf(r.code); return i < 0 ? 99 : i; };
        const latest = plain.filter((r) => r.period === lp).concat(bdRows.filter((r) => r.period === BA.latestPeriod(bdRows))).sort((a, b) => ord(a) - ord(b));
        tableBox.innerHTML = BA.rowsTable(latest.length ? latest : all.slice(0, 40), ind.unit);
        return;
      }
      chartBox.classList.toggle('ba-chart--tall', mode === 'Breakdown');
      if (mode === 'Latest') BA.barGeo(canvas, plain.filter((r) => r.period === lp), ind.unit);
      else if (mode === 'Trend') BA.lineGeo(canvas, plain, ind.unit);
      else { const blp = BA.latestPeriod(bdRows); BA.barBreakdown(canvas, bdRows.filter((r) => r.period === blp), ind.unit); }
    };
    const tog = modes.length > 1 ? `<span class="ba-toggle ba-noprint" role="group" aria-label="Chart view">${modes.map((m, i) => `<button type="button" aria-pressed="${i === 0}" data-m="${m}">${m}</button>`).join(' ')}</span>` : '';
    foot.innerHTML = `${tog}<span>${esc(lp || '')}</span>${BA.ageTag(lp)}${dsLink}${mapLink}<a class="govuk-link ba-dl" href="#">CSV</a>`;
    foot.querySelectorAll('button').forEach((b) => b.addEventListener('click', () => { foot.querySelectorAll('button').forEach((x) => x.setAttribute('aria-pressed', x === b)); draw(b.dataset.m); }));
    foot.querySelector('.ba-dl').addEventListener('click', (e) => { e.preventDefault(); BA.downloadCSV(ind.id + '.csv', all); });
    draw(modes[0]);
  }
  BA.indicatorCard = indicatorCard;

  /* ---------- sources catalogue ---------- */
  BA.route(/^\/sources$/, async (app) => {
    const S = BA.sources;
    const uniq = (f) => [...new Set(S.flatMap((s) => [].concat(s[f] || [])))].filter(Boolean).sort();
    app.innerHTML = `<span class="govuk-caption-xl">Research</span><h1 class="govuk-heading-xl">Data sources assessed</h1>
      <p class="govuk-body-l">${S.length} sources were reviewed against the brief: who publishes each, at what geography, how often, and whether the underlying data can be downloaded or reached through an API rather than only viewed in a dashboard.</p>
      <div class="ba-filterbar ba-noprint">
        <div class="govuk-form-group"><label class="govuk-label govuk-label--s" for="q">Search</label><input class="govuk-input govuk-input--width-20" id="q" type="search"></div>
        ${sel('fc', 'Cohort', uniq('cohorts'))}${sel('fa', 'Access', uniq('access'))}${sel('fp', 'Priority', uniq('priority'))}${sel('ft', 'Provider', uniq('provider_type'))}
        <div class="govuk-form-group"><div class="govuk-checkboxes govuk-checkboxes--small"><div class="govuk-checkboxes__item"><input class="govuk-checkboxes__input" id="fu" type="checkbox"><label class="govuk-label govuk-checkboxes__label" for="fu">Used in this tool</label></div></div></div>
        <a href="#" class="govuk-link" id="dl">Download CSV</a>
      </div><p class="govuk-body" id="cnt"></p><div id="list"></div>`;
    function sel(id, label, opts) { return `<div class="govuk-form-group"><label class="govuk-label govuk-label--s" for="${id}">${label}</label><select class="govuk-select" id="${id}"><option value="">All</option>${opts.map((o) => `<option>${esc(o)}</option>`).join('')}</select></div>`; }
    const $ = (id) => document.getElementById(id);
    function render() {
      const q = $('q').value.toLowerCase();
      const f = S.filter((s) => (!q || JSON.stringify(s).toLowerCase().includes(q)) && (!$('fc').value || [].concat(s.cohorts).includes($('fc').value)) && (!$('fa').value || s.access === $('fa').value) && (!$('fp').value || s.priority === $('fp').value) && (!$('ft').value || s.provider_type === $('ft').value) && (!$('fu').checked || s.used_in_tool));
      $('cnt').textContent = `Showing ${f.length} of ${S.length} sources`;
      $('list').innerHTML = `<div class="ba-table-wrap"><table class="govuk-table"><thead class="govuk-table__head"><tr class="govuk-table__row"><th class="govuk-table__header">Source</th><th class="govuk-table__header">Geography</th><th class="govuk-table__header">Cohorts</th><th class="govuk-table__header">Frequency / latest</th><th class="govuk-table__header">Access</th></tr></thead><tbody class="govuk-table__body">${f.map((s) => `
        <tr class="govuk-table__row"><td class="govuk-table__cell"><details class="govuk-details govuk-!-margin-bottom-0"><summary class="govuk-details__summary"><span class="govuk-details__summary-text">${esc(s.name)}</span></summary><div class="govuk-details__text govuk-body-s">
          <dl class="ba-kv"><dt>Publisher</dt><dd>${esc(s.publisher)} (${esc(s.provider_type || '')})</dd><dt>URL</dt><dd>${BA.link(s.url)}</dd><dt>Quality</dt><dd>${esc(s.quality)}</dd><dt>Variables</dt><dd>${esc([].concat(s.variables || []).join('; '))}</dd><dt>Granularity</dt><dd>${esc([].concat(s.granularity || []).join(', '))}</dd><dt>API / download</dt><dd>${esc(s.api_notes || '')}</dd><dt>Limitations</dt><dd>${esc(s.limitations)}</dd><dt>Why it matters</dt><dd>${esc(s.why_it_matters || '')}</dd><dt>Next release</dt><dd>${esc(s.next_release || '')}</dd></dl></div></details>
          <span class="ba-small">${esc(s.publisher)}</span> ${s.used_in_tool ? '<strong class="govuk-tag govuk-tag--green">In tool</strong>' : ''} ${s.priority === 'core' ? '<strong class="govuk-tag govuk-tag--blue">Core</strong>' : ''}</td>
          <td class="govuk-table__cell ba-small">${esc(s.lowest_geography || '')}</td><td class="govuk-table__cell ba-small">${[].concat(s.cohorts || []).map((c) => `<span class="ba-pill">${esc(c)}</span>`).join('')}</td>
          <td class="govuk-table__cell ba-small">${esc(s.frequency)}<br>${esc(s.latest_period)}</td><td class="govuk-table__cell ba-small">${esc(s.access)}</td></tr>`).join('')}</tbody></table></div>`;
      BA.filteredSources = f;
    }
    ['q', 'fc', 'fa', 'fp', 'ft', 'fu'].forEach((id) => $(id).addEventListener('input', render));
    $('dl').addEventListener('click', (e) => { e.preventDefault(); BA.downloadCSV('bedfordshire-sources.csv', BA.filteredSources.map((s) => Object.assign({}, s, { granularity: [].concat(s.granularity || []).join('; '), cohorts: [].concat(s.cohorts || []).join('; '), variables: [].concat(s.variables || []).join('; ') }))); });
    render();
  });

  /* ---------- lineage ---------- */
  BA.route(/^\/lineage$/, async (app) => {
    app.innerHTML = `<span class="govuk-caption-xl">Transparency</span><h1 class="govuk-heading-xl">Data lineage</h1>
      <p class="govuk-body-l">Each feed's journey: publisher, the exact request, processing, and the indicators and pages it supplies.</p>
      <div class="ba-flow" id="flow"></div>
      <h2 class="govuk-heading-l govuk-!-margin-top-6">Every feed</h2>${lineageTable()}
      <h2 class="govuk-heading-m">How the pipeline works</h2>
      <ol class="govuk-list govuk-list--number">
        <li>One Python fetcher per publisher (standard library only) requests each source by exact URL or API query and caches the raw response.</li>
        <li>Rows are filtered to Bedford, Central Bedfordshire, Luton and their small areas, plus East of England and England comparators.</li>
        <li>Values are converted to one long format (area, indicator, period, value, confidence interval, numerator, denominator). Suppressed cells stay empty and flagged; they are never filled in.</li>
        <li>A Bedfordshire total is created only by summing counts. Rates are never averaged across areas.</li>
        <li>Every output records its source, retrieval time and a SHA-256 checksum. The catalogue that drives this page is <a class="govuk-link" href="data/catalogue.json">published as JSON</a>.</li>
      </ol>`;
    drawFlow(document.getElementById('flow'));
  });

  function drawFlow(el) {
    const cat = BA.catalogue.filter((m) => m.id !== 'geo_boundaries');
    if (!cat.length) return;
    const pubs = [...new Set(cat.map((m) => shortPub(m.publisher)))];
    const uses = ['16 to 19', '18 to 24', 'Inactive 25+', 'Map', 'Business case'];
    const useOf = (m) => {
      const inds = m.indicators || [];
      const u = new Set();
      inds.forEach((i) => BA.cohortsOf(i).forEach((c) => { if (c === '16-19') u.add('16 to 19'); if (c === '18-24') u.add('18 to 24'); if (c === '25+ inactive') u.add('Inactive 25+'); }));
      if (/LSOA|MSOA|point/i.test(m.geography || '')) u.add('Map');
      if (BA.ENGINE_DATASETS && BA.ENGINE_DATASETS.includes(m.id)) u.add('Business case');
      return [...u];
    };
    const rowH = 22, W = 1100, H = Math.max(cat.length, pubs.length * 2) * rowH + 40;
    const x0 = 10, x1 = 330, x2 = 860;
    const yP = (i) => 30 + (i + 0.5) * ((H - 40) / pubs.length);
    const yD = (i) => 30 + (i + 0.5) * rowH;
    const yU = (i) => 30 + (i + 0.5) * ((H - 40) / uses.length);
    const sorted = cat.slice().sort((a, b) => pubs.indexOf(shortPub(a.publisher)) - pubs.indexOf(shortPub(b.publisher)));
    let s = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="Lineage diagram from publishers to datasets to uses" style="min-width:760px">`;
    s += `<text x="${x0}" y="16" font-weight="700" font-size="13">Publisher</text><text x="${x1}" y="16" font-weight="700" font-size="13">Dataset (latest period)</text><text x="${x2}" y="16" font-weight="700" font-size="13">Used in</text>`;
    sorted.forEach((m, i) => {
      const yp = yP(pubs.indexOf(shortPub(m.publisher))), yd = yD(i);
      s += `<path d="M${x0 + 200},${yp} C${x0 + 270},${yp} ${x1 - 70},${yd} ${x1 - 6},${yd}" fill="none" stroke="#b1b4b6" stroke-width="1.5"/>`;
      useOf(m).forEach((u) => { const yu = yU(uses.indexOf(u)); s += `<path d="M${x1 + 400},${yd} C${x1 + 470},${yd} ${x2 - 70},${yu} ${x2 - 6},${yu}" fill="none" stroke="#9ec5e8" stroke-width="1.2"/>`; });
      s += `<a href="#/data/${m.id}"><text x="${x1}" y="${yd + 4}" font-size="12" fill="#1d70b8">${esc((m.title || m.id).slice(0, 52))} <tspan fill="#505a5f">(${esc(String(m.latest_period || m.period || '').slice(0, 18))})</tspan></text></a>`;
    });
    pubs.forEach((p, i) => (s += `<rect x="${x0}" y="${yP(i) - 11}" width="196" height="22" fill="#f3f2f1"/><text x="${x0 + 6}" y="${yP(i) + 4}" font-size="12" font-weight="700">${esc(p)}</text>`));
    uses.forEach((u, i) => (s += `<rect x="${x2}" y="${yU(i) - 11}" width="160" height="22" fill="#1d70b8"/><text x="${x2 + 8}" y="${yU(i) + 4}" font-size="12" fill="#fff" font-weight="700">${u}</text>`));
    el.innerHTML = s + '</svg>';
  }
  function shortPub(p) { p = String(p || 'Unknown'); return p.length > 30 ? p.replace(/\(.*?\)/g, '').slice(0, 30) : p; }

  /* ---------- dataset detail ---------- */
  BA.route(/^\/data\/([\w-]+)$/, async (app, id) => {
    const ds = await BA.dataset(id); const m = ds.meta;
    const src = BA.sources.find((s) => s.url && [].concat(m.api_url || []).concat(m.source_url || []).some((u) => String(u).includes(s.url))) || null;
    const levels = [...new Set(ds.rows.map((r) => r.level))];
    app.innerHTML = `<a href="#/lineage" class="govuk-back-link">All datasets</a>
      <span class="govuk-caption-xl">${esc(m.publisher)}</span><h1 class="govuk-heading-xl">${esc(m.title)}</h1>
      <div class="ba-lineage-step">
        <div><h4>1. Source</h4>${esc(m.publisher)}<br>${BA.link(m.source_url, 'Landing page')}<br><span class="ba-small">${esc(m.licence)}</span></div>
        <div><h4>2. Fetch</h4>${esc(m.access)}<br><span class="ba-small">Retrieved ${esc(m.retrieved_at)}</span><br>${[].concat(m.api_url || []).slice(0, 4).map((u) => `<code class="ba-small" style="word-break:break-all">${esc(String(u).slice(0, 160))}</code>`).join('<br>')}</div>
        <div><h4>3. Transform</h4>Filtered to Bedfordshire and comparators, then reshaped to long format.<br><span class="ba-small">Levels: ${esc(levels.join(', '))}</span><br><span class="ba-small">${m.row_count} rows · sha256 ${esc(m.sha256)}</span></div>
        <div><h4>4. Output</h4>${(m.indicators || []).length} indicators<br><a class="govuk-link" href="data/${id}.json">JSON</a> · <a class="govuk-link" href="#" id="dlcsv">CSV</a></div>
      </div>
      <dl class="ba-kv govuk-!-margin-bottom-6">
        <dt>Geography</dt><dd>${esc(m.geography)}</dd><dt>Cohort</dt><dd>${esc(m.cohort)}</dd>
        <dt>Latest period</dt><dd>${esc(m.latest_period || m.period)}</dd><dt>Frequency</dt><dd>${esc(m.frequency)}</dd><dt>Next update</dt><dd>${esc(m.next_update)}</dd>
        <dt>Quality</dt><dd>${esc(m.quality)}</dd><dt>Limitations</dt><dd>${esc(m.limitations)}</dd>
        ${src ? `<dt>Research note</dt><dd>${esc(src.why_it_matters || '')}</dd>` : ''}
      </dl>
      <h2 class="govuk-heading-l">Indicators</h2>
      <div class="ba-cards" id="cards"></div>
      <h2 class="govuk-heading-l govuk-!-margin-top-6">Rows</h2>
      <p class="govuk-body ba-small">The first 300 rows. Download the CSV for all ${m.row_count}.</p>
      <div class="ba-table-wrap"><table class="govuk-table"><thead class="govuk-table__head"><tr class="govuk-table__row">${['code', 'name', 'level', 'indicator', 'breakdown', 'period', 'value', 'ci'].map((c) => `<th class="govuk-table__header">${c}</th>`).join('')}</tr></thead><tbody class="govuk-table__body">
      ${ds.rows.slice(0, 300).map((r) => `<tr class="govuk-table__row">${['code', 'name', 'level', 'indicator', 'breakdown', 'period'].map((c) => `<td class="govuk-table__cell ba-small">${esc(r[c] ?? '')}</td>`).join('')}<td class="govuk-table__cell govuk-table__cell--numeric">${r.suppressed ? 'supp.' : esc(r.value ?? '')}</td><td class="govuk-table__cell govuk-table__cell--numeric">${esc(r.ci ?? '')}</td></tr>`).join('')}</tbody></table></div>`;
    const cards = document.getElementById('cards');
    (m.indicators || []).forEach((ind) => cards.appendChild(BA.indicatorCard(BA.indicators[ind.id] || Object.assign({ dataset: id }, ind))));
    document.getElementById('dlcsv').addEventListener('click', (e) => { e.preventDefault(); BA.downloadCSV(id + '.csv', ds.rows); });
  });

  /* ---------- analysis A-D ---------- */
  BA.route(/^\/analysis$/, async (app) => {
    const a = BA.assessment || {};
    const T = (cols, rows, f) => `<div class="ba-table-wrap"><table class="govuk-table"><thead class="govuk-table__head"><tr class="govuk-table__row">${cols.map((c) => `<th class="govuk-table__header">${c}</th>`).join('')}</tr></thead><tbody class="govuk-table__body">${rows.map((r) => `<tr class="govuk-table__row">${f(r).map((x) => `<td class="govuk-table__cell govuk-body-s">${x}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
    const ids = (xs) => [].concat(xs || []).map((x) => `<span class="ba-pill">${esc(x)}</span>`).join('');
    app.innerHTML = `<span class="govuk-caption-xl">Assessment</span><h1 class="govuk-heading-xl">Gaps, linkage and the minimum dataset</h1>
      <nav class="govuk-body"><a class="govuk-link" href="#/analysis" data-j="a">A. Answerable now</a> · <a class="govuk-link" href="#/analysis" data-j="b">B. Gaps</a> · <a class="govuk-link" href="#/analysis" data-j="c">C. Linkage</a> · <a class="govuk-link" href="#/analysis" data-j="d">D. Additional data</a> · <a class="govuk-link" href="#/analysis" data-j="m">Minimum dataset</a> · <a class="govuk-link" href="#/analysis" data-j="r">Risks</a></nav>
      <h2 class="govuk-heading-l" id="a">A. What can be answered from existing open data?</h2>
      ${T(['Question', 'Answerable', 'How', 'Geography', 'Sources'], a.can_answer || [], (r) => [`<strong>${esc(r.question)}</strong>`, BA.status(r.answerable), esc(r.how), esc(r.geography), ids(r.sources)])}
      <h2 class="govuk-heading-l" id="b">B. Where are the important data gaps?</h2>
      <div class="ba-callout ba-callout--warn"><p class="govuk-body govuk-!-margin-bottom-0">The biggest blind spot is <strong>economically inactive people who do not claim benefits</strong>. Examples are carers supported by a partner's income, people with health conditions who never claimed, early retirees and some migrants. They appear only in the Census (every ten years) and in survey estimates (APS, with wide confidence intervals). No administrative system records them.</p></div>
      ${T(['Gap', 'Who is invisible', 'Why', 'Impact', 'Mitigation'], a.gaps || [], (r) => [`<strong>${esc(r.gap)}</strong>`, esc(r.who_is_invisible), esc(r.why), esc(r.impact), esc(r.mitigation)])}
      <h2 class="govuk-heading-l" id="c">C. What could be derived by linking or combining datasets?</h2>
      ${T(['Analysis', 'Combine', 'Method', 'Output', 'Geography', 'Caveats'], a.linkage || [], (r) => [`<strong>${esc(r.analysis)}</strong>`, ids(r.combine), esc(r.method), esc(r.output), esc(r.geography), esc(r.caveats)])}
      <h2 class="govuk-heading-l" id="d">D. What additional data would materially improve the analysis?</h2>
      ${T(['Data', 'Likely holder', 'Granularity needed', 'Use', 'Route to access'], a.additional_data || [], (r) => [`<strong>${esc(r.data)}</strong>`, esc(r.likely_holder), esc(r.granularity_needed), esc(r.use), esc(r.route_to_access)])}
      <h2 class="govuk-heading-l" id="m">Recommended minimum dataset</h2>
      <p class="govuk-body">${esc(a.sources_notes || '')}</p>
      ${BA.minDatasetTable(a.minimum_dataset || [])}
      <h2 class="govuk-heading-l" id="r">Risks and issues</h2>${BA.risksTable(a.risks_issues || [])}
      <h2 class="govuk-heading-l">Phases and demand profile</h2>
      ${T(['Phase', 'Years', 'Demand profile', 'Typical occupations', 'Evidence'], a.phases || [], (r) => [`<strong>${esc(r.id)}</strong>`, esc(r.years), esc(r.demand_profile), esc([].concat(r.typical_occupations || []).join(', ')), esc(typeof r.evidence === 'string' ? r.evidence : [].concat(r.evidence || []).map((e) => typeof e === 'string' ? e : (e.title || e.source || '') + (e.url ? ' ' + e.url : '')).join('; ')).slice(0, 700)])}
      <h2 class="govuk-heading-l">Benchmarks used</h2>
      ${T(['Benchmark', 'Value', 'Note', 'Source'], a.benchmarks || [], (r) => [`<strong>${esc(r.benchmark)}</strong>`, esc(r.value), esc(r.note), BA.link(r.source, 'source')])}`;
    app.querySelectorAll('[data-j]').forEach((x) => x.addEventListener('click', (e) => { e.preventDefault(); document.getElementById(x.dataset.j).scrollIntoView(); }));
  });

  /* ---------- downloads ---------- */
  BA.route(/^\/downloads$/, async (app) => {
    const cat = BA.catalogue.slice().sort((a, b) => String(a.title).localeCompare(String(b.title)));
    app.innerHTML = `<span class="govuk-caption-xl">Open data</span><h1 class="govuk-heading-xl">Download the evidence base</h1>
      <div class="govuk-grid-row"><div class="govuk-grid-column-two-thirds">
      <p class="govuk-body-l">Everything on this site is published aggregate statistics, reshaped into one consistent format. Take it into Excel, R, Python or a BI tool.</p>
      <p class="govuk-body"><a class="govuk-button govuk-!-margin-bottom-2" href="data/downloads/bedfordshire-evidence-base.zip" download>Download everything (zip of CSVs)</a></p>
      <p class="govuk-body">The zip holds one CSV per dataset, an indicator dictionary, the full lineage catalogue and the sources assessed. Or take single files below.</p>
      <h2 class="govuk-heading-m">Format</h2>
      <p class="govuk-body">Every dataset is long format, one value per row: <code>code, name, level, indicator, breakdown, period, value, ci, num, den, suppressed, lat, lon, attrs</code>. Codes are ONS GSS codes; <code>BEDS</code> is the sum of the three unitary authorities, used for counts only. A blank value means suppressed or not published. <a class="govuk-link" href="data/downloads/indicators.csv">indicators.csv</a> gives each indicator's label, unit, cohort and whether higher is better.</p>
      <h2 class="govuk-heading-m">Machine-readable</h2>
      <ul class="govuk-list govuk-list--bullet"><li><a class="govuk-link" href="data/catalogue.json">catalogue.json</a>: the lineage record for every dataset (publisher, exact URLs, retrieval time, checksum, quality, limitations)</li><li><code>data/&lt;dataset&gt;.json</code>: each dataset with its lineage block</li><li><a class="govuk-link" href="data/changes.json">changes.json</a>: what changed at each refresh</li></ul>
      <h2 class="govuk-heading-m">Citing a fixed version</h2>
      <p class="govuk-body">Each published refresh is tagged <code>data-YYYY-MM-DD</code> in the <a class="govuk-link" href="https://github.com/zerosumpain/beds_analysis/tags">public repository</a>. To cite the data behind a business case, link to the tag; its <code>site/data</code> folder is the exact data used. The pipeline code is in the same repository, so any figure can be rebuilt from source.</p>
      </div></div>
      <h2 class="govuk-heading-l">Datasets</h2>
      <div class="ba-table-wrap"><table class="govuk-table"><thead class="govuk-table__head"><tr class="govuk-table__row"><th class="govuk-table__header" scope="col">Dataset</th><th class="govuk-table__header" scope="col">Latest period</th><th class="govuk-table__header govuk-table__header--numeric" scope="col">Rows</th><th class="govuk-table__header" scope="col">Files</th></tr></thead><tbody class="govuk-table__body">
      ${cat.map((m) => `<tr class="govuk-table__row"><th class="govuk-table__header" scope="row" style="font-weight:400"><a class="govuk-link" href="#/data/${m.id}">${esc(m.title)}</a><br><span class="ba-small">${esc(m.publisher)}</span></th><td class="govuk-table__cell ba-small">${esc(m.latest_period || m.period)} ${BA.ageTag(m.latest_period || m.period)}</td><td class="govuk-table__cell govuk-table__cell--numeric">${BA.fmt(m.row_count, 'count')}</td><td class="govuk-table__cell"><a class="govuk-link" href="data/downloads/csv/${m.id}.csv" download>CSV</a> · <a class="govuk-link" href="data/${m.id}.json">JSON</a></td></tr>`).join('')}</tbody></table></div>`;
  });

  /* ---------- changes ---------- */
  BA.route(/^\/changes$/, async (app) => {
    const log = (await BA.tryJson('data/changes.json')) || [];
    const due = BA.catalogue.filter((m) => m.next_update && !/unknown/i.test(m.next_update)).sort((a, b) => String(a.next_update).localeCompare(String(b.next_update)));
    app.innerHTML = `<span class="govuk-caption-xl">Transparency</span><h1 class="govuk-heading-xl">What has changed</h1>
      <p class="govuk-body-l">Every feed is checked weekly. A refresh is published only when a source has new or revised figures and the checks pass.</p>
      ${log.length ? log.map((e) => `<h2 class="govuk-heading-m">${esc(e.date)} <span class="ba-small">· <a class="govuk-link" href="https://github.com/zerosumpain/beds_analysis/tree/${esc(e.tag)}/site/data">${esc(e.tag)}</a></span></h2>
        <ul class="govuk-list govuk-list--bullet">${e.datasets.map((d) => `<li><a class="govuk-link" href="#/data/${esc(d.id)}">${esc(d.title || d.id)}</a>: ${d.change === 'new period' ? `new data, ${esc(d.from_period)} → <strong>${esc(d.to_period)}</strong>` : d.change === 'new dataset' ? `<strong>new dataset</strong> (${esc(d.to_period)})` : `figures revised (${esc(d.to_period)})`}${d.rows_before != null ? ` <span class="ba-small">${d.rows_before} → ${d.rows_after} rows</span>` : ''}</li>`).join('')}</ul>`).join('') : '<p class="govuk-body">No refreshes have been published since the change log started.</p>'}
      <h2 class="govuk-heading-l govuk-!-margin-top-6">Coming up</h2>
      <div class="ba-table-wrap"><table class="govuk-table"><thead class="govuk-table__head"><tr class="govuk-table__row"><th class="govuk-table__header" scope="col">Dataset</th><th class="govuk-table__header" scope="col">Current period</th><th class="govuk-table__header" scope="col">Frequency</th><th class="govuk-table__header" scope="col">Next update</th></tr></thead><tbody class="govuk-table__body">${due.map((m) => `<tr class="govuk-table__row"><td class="govuk-table__cell"><a class="govuk-link" href="#/data/${m.id}">${esc(m.title)}</a></td><td class="govuk-table__cell ba-small">${esc(m.latest_period || m.period)}</td><td class="govuk-table__cell ba-small">${esc(m.frequency)}</td><td class="govuk-table__cell ba-small">${esc(m.next_update)}</td></tr>`).join('')}</tbody></table></div>`;
  });

  /* ---------- method ---------- */
  BA.route(/^\/method$/, async (app) => {
    app.innerHTML = `<h1 class="govuk-heading-xl">Method and caveats</h1><div class="govuk-grid-row"><div class="govuk-grid-column-two-thirds">
      <h2 class="govuk-heading-m">Geography</h2><p class="govuk-body">Bedfordshire has had no county council since 2009. It means the three unitary authorities: Bedford (E06000055), Central Bedfordshire (E06000056) and Luton (E06000032). "Bedfordshire" totals in this tool are sums of the three, and only for counts. Small-area data uses 2021 LSOAs and MSOAs.</p>
      <h2 class="govuk-heading-m">Surveys versus administrative data</h2><p class="govuk-body">Annual Population Survey (APS) estimates for one local authority rest on a few hundred respondents. Youth and reason-for-inactivity estimates often have 95% confidence intervals of ±5 to 10 percentage points, or are suppressed. The tool shows those intervals as whiskers. Treat year-on-year changes inside them as noise.</p>
      <h2 class="govuk-heading-m">Census 2021</h2><p class="govuk-body">The Census was taken on 21 March 2021, during lockdown and the furlough scheme. Furloughed people were counted as employed. Students are counted at their term-time address. Small counts are perturbed by cell-key methods, so LSOA figures may not add up exactly.</p>
      <h2 class="govuk-heading-m">Claimant count</h2><p class="govuk-body">The claimant count includes Universal Credit claimants who must look for work, some of whom are in low-paid work. It is not a measure of unemployment, and it misses unemployed people who do not claim.</p>
      <h2 class="govuk-heading-m">Business case engine</h2><p class="govuk-body">The engine combines published cohort sizes with editable assumptions about demand, engagement, training costs and benefits. Every default is labelled with its source or marked illustrative. It is a planning model, not a forecast. Use it to test which assumptions the case is most sensitive to.</p>
      <h2 class="govuk-heading-m">Journey times to the site</h2><p class="govuk-body">Journey times run from each neighbourhood's centre to the site, arriving by 08:30 on a weekday. They are computed with OpenTripPlanner over current bus timetables (DfT Bus Open Data Service) and the OpenStreetMap road and path network. The <a class="govuk-link" href="#/data/travel_lsoa">travel-time dataset</a> records the timetable date and how rail is modelled. Car times assume free-flowing traffic. “Mixed” reach treats each neighbourhood's households without a car (Census 2021) as relying on public transport or cycling, and the rest as able to drive. Where car data is missing it assumes 25% of households have no car. That is a household measure; young people are less likely to drive than the figure implies.</p>
      <h2 class="govuk-heading-m">Labour balance</h2><p class="govuk-body">Each engine cohort is spread across neighbourhoods using the nearest small-area count, then weighted by the share of residents able to reach the site. Examples: residents aged 16-19 for school leavers and NEET young people; claimants by age; and Census inactive people who are sick, caring, looking after home or other. Engagement, completion and job rates then apply to people who can reach the site.</p>
      <h2 class="govuk-heading-m">Fiscal values</h2><p class="govuk-body">The fiscal benefit of each extra person in work comes from the GMCA Unit Cost Database. Values for claimants moving into full-time work are scaled to the resort's 0.74 FTE per head. For inactive adults aged 25+, half are assumed to claim a health-related benefit. NEET values use the database's NEET costs. The economic benefit counts a share of earnings, set in the engine.</p>
      <h2 class="govuk-heading-m">Uncertainty ranges</h2><p class="govuk-body">The engine's Monte Carlo varies each assumption on a triangular distribution with the current value as the mode. The ranges, as multiples of the current value, are: deadweight 0.5-1.5; displacement 0.5-1.6; persistence 0.67-1.67; drop-off 0.5-1.5; fiscal values 0.7-1.3; wage 0.9-1.1; share of earnings counted 0.6-1.3; reach 0.85-1.1; engagement 0.5-1.5; completion 0.8-1.15; job rate 0.7-1.25; cost 0.75-1.4. Rates are capped at their natural maximum. The seed is fixed, so the same inputs always give the same result.</p>
      <h2 class="govuk-heading-m">Area profiles</h2><p class="govuk-body">Profiles add up neighbourhood (LSOA) figures. Counts are summed. Percentages are recomputed from summed numerators and denominators. Scores, deciles and journey times show the median neighbourhood. Postcode search sends only the postcode to postcodes.io, which returns its location; the neighbourhood is then found in your browser.</p>
      <h2 class="govuk-heading-m">Refresh and checks</h2><p class="govuk-body">Every feed is re-fetched each week. Nothing is published if a dataset disappears, loses more than 30% of its rows or an indicator, or its latest period moves backwards. Each published refresh is tagged <code>data-YYYY-MM-DD</code> in the <a class="govuk-link" href="https://github.com/zerosumpain/beds_analysis/tags">source repository</a>, so a business case can cite the exact data it used. See <a class="govuk-link" href="#/changes">what has changed</a>.</p>
      <h2 class="govuk-heading-m">Privacy</h2><p class="govuk-body">Only published aggregate statistics are used. No personal data is collected, stored or inferred, and the site sets no cookies.</p>
    </div></div>`;
  });
})();
