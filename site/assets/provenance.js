/* Provenance: where every figure on the site comes from, shown as a tag next to it.
   Classes are code-verified per indicator in research/provenance_*.json (built into
   data/research_provenance.json). Nothing on the site is invented test data; the classes
   separate what a publisher released from what this site calculated, modelled or assumed. */
(function () {
  'use strict';
  const BA = window.BA;
  const esc = BA.esc;

  BA.PROV = {
    published: { label: 'Published', tag: 'green', what: 'Exactly as the publisher released it. We only filtered it to Bedfordshire and its comparators and reshaped it.' },
    calculated: { label: 'Calculated', tag: 'blue', what: 'Calculated by this site from published figures: a rate with a denominator we chose, a sum (such as the Bedfordshire total), a share or a ratio. The method is given for each one.' },
    modelled: { label: 'Modelled', tag: 'purple', what: 'Output of a model built for this site, such as journey times or the business case. Not an official statistic. Its inputs and approximations are listed below.' },
    document: { label: 'From a document', tag: 'grey', what: 'Taken from a named report or guidance document (the promoter\'s Environmental Statement, the GMCA Unit Cost Database, HM Treasury guidance, case studies), not from a statistical dataset.' },
    assumption: { label: 'Assumption', tag: 'orange', what: 'A value chosen for the model, not measured. You can change it. Treat results that depend on it as illustrative until it is replaced with local evidence.' },
    live: { label: 'Live, your key', tag: 'turquoise', what: 'Fetched by your browser from the publisher\'s API with your own API key, at the time shown. Not stored on this site.' },
  };
  BA.provTag = function (cls, detail) {
    const c = BA.PROV[cls]; if (!c) return '';
    const t = (detail ? detail + ' ' : '') + c.what;
    return `<a class="govuk-tag govuk-tag--${c.tag} ba-prov" href="#/provenance?c=${cls}" title="${esc(t)}">${esc(c.label)}<span class="govuk-visually-hidden">: ${esc(detail || c.what)}</span></a>`;
  };

  const init = BA.init;
  BA.init = async function () {
    await init();
    BA.provenance = (await BA.tryJson('data/research_provenance.json')) || { datasets: {}, indicators: {} };
  };
  // Provenance of an indicator: {class, method, levels}
  BA.provOf = function (indId) {
    const ind = BA.indicators[indId] || {};
    const meta = BA.meta(ind.dataset) || {};
    if (meta.live) return { class: 'live', method: 'Fetched live from ' + meta.publisher + ' with your API key.', levels: {} };
    const P = BA.provenance || { datasets: {}, indicators: {} };
    const d = P.datasets[ind.dataset] || {}, i = P.indicators[indId] || {};
    return { class: i.class || d.class || null, method: i.method || d.note || '', levels: Object.assign({}, d.levels || {}, i.beds ? { BEDS: i.beds } : {}) };
  };
  const LEVEL_KEY = { county: 'BEDS', LA: 'LA', region: 'region', country: 'country' };
  // Provenance of one row: a Bedfordshire total we summed is "calculated" even when the LA rows are published.
  BA.provRow = function (r) {
    const p = BA.provOf(r.indicator);
    if (p.class !== 'published') return p.class;
    const k = r.code === 'BEDS' ? 'BEDS' : LEVEL_KEY[r.level] || 'small_area';
    return p.levels[k] === 'calculated' ? 'calculated' : 'published';
  };
  BA.provIndTag = function (indId) {
    const p = BA.provOf(indId);
    return p.class ? BA.provTag(p.class, p.method) : '';
  };
  BA.provBedsNote = function (indId) {
    const p = BA.provOf(indId);
    return p.class === 'published' && p.levels.BEDS === 'calculated' ? ' The Bedfordshire figure is calculated by this site by adding the three authorities.' : '';
  };

  /* ---------- the register ---------- */
  BA.route(/^\/provenance$/, async (app) => {
    const P = BA.provenance || { datasets: {}, indicators: {} };
    const inds = Object.values(BA.indicators);
    const by = {}; inds.forEach((i) => { const c = BA.provOf(i.id).class || 'unclassified'; (by[c] = by[c] || []).push(i); });
    const n = (c) => (by[c] || []).length;
    const params = [].concat(...(BA.ENGINE_PARAMS || []).map((g) => g.items.map((p) => Object.assign({ group: g.g }, p))));
    const tr = (cells) => `<tr class="govuk-table__row">${cells.map((c, i) => i ? `<td class="govuk-table__cell">${c}</td>` : `<th class="govuk-table__header" scope="row" style="font-weight:400">${c}</th>`).join('')}</tr>`;
    const table = (heads, rows) => `<div class="ba-table-wrap"><table class="govuk-table ba-mini"><thead class="govuk-table__head"><tr class="govuk-table__row">${heads.map((h) => `<th class="govuk-table__header" scope="col">${h}</th>`).join('')}</tr></thead><tbody class="govuk-table__body">${rows.join('')}</tbody></table></div>`;
    const indRows = (c) => (by[c] || []).sort((a, b) => a.dataset.localeCompare(b.dataset) || a.label.localeCompare(b.label))
      .map((i) => tr([`<a class="govuk-link" href="#/data/${i.dataset}">${esc(i.label)}</a>`, esc((BA.meta(i.dataset) || {}).title || i.dataset), esc(BA.provOf(i.id).method)]));
    const bedsCalc = Object.entries(P.datasets).filter(([id, d]) => BA.has(id) && d.levels && d.levels.BEDS === 'calculated').map(([id]) => (BA.meta(id) || {}).title || id);
    const POOL_KINDS = BA.ENGINE_POOL_KINDS || {};
    app.innerHTML = `<span class="govuk-caption-xl">Lineage</span><h1 class="govuk-heading-xl">Where each figure comes from</h1>
      <div class="govuk-grid-row"><div class="govuk-grid-column-two-thirds">
      <p class="govuk-body-l">Every figure on this site carries one of these tags. Nothing is invented or test data: a figure is either released by a publisher, calculated by this site from released figures, produced by a model built for this site, taken from a named document, or an assumption you can change.</p></div></div>
      <dl class="ba-provkey">${Object.entries(BA.PROV).map(([k, c]) => `<div id="prov-${k}"><dt>${BA.provTag(k)}</dt><dd>${esc(c.what)}${by[k] ? ` <span class="ba-small">(${n(k)} indicators)</span>` : ''}</dd></div>`).join('')}</dl>
      ${n('unclassified') ? `<div class="govuk-warning-text"><span class="govuk-warning-text__icon" aria-hidden="true">!</span><strong class="govuk-warning-text__text">${n('unclassified')} indicators have not yet been classified: ${esc(by.unclassified.map((i) => i.id).join(', '))}.</strong></div>` : ''}

      <h2 class="govuk-heading-l">Modelled by this site</h2>
      <p class="govuk-body">These are estimates, not statistics. Each depends on approximations, listed in full.</p>
      <h3 class="govuk-heading-m">Journey times to the site</h3>
      <ul class="govuk-list govuk-list--bullet">
        <li>Computed with OpenTripPlanner 2.8.1 from each neighbourhood's population-weighted centre to the site, departing to arrive for an 08:30 shift on Tuesday 17 November 2026.</li>
        <li><strong>Buses</strong>: real timetables from the Department for Transport's Bus Open Data Service.</li>
        <li><strong>Marston Vale line trains</strong>: copied by hand from the London Northwestern Railway timetable valid 18 May to 11 December 2026. After 11 December this is out of date.</li>
        <li><strong>Thameslink and East Midlands Railway trains are approximated</strong>: modelled as a regular train every 15 or 30 minutes with one fixed running time per direction, not their real departure times, because open rail timetables need a registered account. Peak-only fast trains are left out.</li>
        <li><strong>No East Coast Main Line trains</strong> (Sandy, Biggleswade, Arlesey) and no other rail lines, so public transport times from the east of Central Bedfordshire are longer than they would be with those trains.</li>
        <li><strong>Car times assume free-flowing traffic</strong>, so real peak journeys will be longer.</li>
        <li><strong>Cycling assumes a flat 18 km/h</strong> on OpenStreetMap routes; walking uses OpenStreetMap paths.</li>
        <li>One weekday only (Tuesday 17 November 2026). The authority and Bedfordshire figures are population-weighted shares of the neighbourhood times, calculated by this site.</li>
      </ul>
      <h3 class="govuk-heading-m">Who can reach the site</h3>
      <p class="govuk-body">The share of each cohort who can reach a shift combines the journey times with Census 2021 household car access (car if the household has one, otherwise public transport or cycling). <strong>Where the Census share without a car is missing, 25% is assumed.</strong> It uses household car ownership, so it overstates access for young people who do not drive.</p>
      <h3 class="govuk-heading-m">Labour balance and business case</h3>
      <p class="govuk-body">Every result on the <a class="govuk-link" href="#/balance">labour balance</a> and <a class="govuk-link" href="#/case">business case</a> pages is model output from the inputs listed below. The construction workforce profile by year (${esc(Object.entries((BA.PROFILE || {}).constr || {}).sort((a, b) => a[0] - b[0]).map(([k, v]) => (k > 0 ? '+' : '') + k + ' yrs ' + Math.round(v * 100) + '%').join(', '))} of the peak, relative to opening) and the ${Math.round(((BA.PROFILE || {}).preopen || 0) * 100)}% of operational hires made the year before opening are <strong>assumptions</strong>. The uncertainty range uses assumed spreads around each input, listed on the <a class="govuk-link" href="#/method">method page</a>.</p>

      <h2 class="govuk-heading-l">Assumptions and document figures in the business case</h2>
      <p class="govuk-body">The defaults the business case starts from. Change any of them on the <a class="govuk-link" href="#/case">business case page</a>.</p>
      ${table(['Input', 'Default', 'Provenance', 'Basis'], params.map((p) => tr([esc(p.label), esc(p.unit === 'year' ? String(p.v) : p.unit === '£' ? '£' + BA.fmt(p.v, 'count') : BA.fmt(p.v, 'count') + (p.unit === '%' ? '%' : p.unit === 'count' ? '' : ' ' + p.unit)), BA.provTag(p.kind), p.src])))}
      <h3 class="govuk-heading-m">For each cohort</h3>
      ${table(['Input', 'Provenance', 'Basis'], Object.values(POOL_KINDS).map((k) => tr([esc(k.label), BA.provTag(k.kind), esc(k.basis)])))}

      <h2 class="govuk-heading-l">Calculated by this site</h2>
      <p class="govuk-body">${n('calculated')} indicators are our arithmetic on published figures.${bedsCalc.length ? ` In addition, wherever a <strong>Bedfordshire total</strong> is shown for these datasets it is calculated by adding the three authorities (counts only; rates are recalculated from summed numerators and denominators, never averaged): ${esc(bedsCalc.join('; '))}.` : ''}</p>
      ${table(['Indicator', 'Dataset', 'How it is calculated'], indRows('calculated'))}
      ${n('modelled') ? `<h2 class="govuk-heading-l">Modelled indicators</h2>${table(['Indicator', 'Dataset', 'How it is made'], indRows('modelled'))}` : ''}
      ${n('live') ? `<h2 class="govuk-heading-l">Fetched live with your key</h2>${table(['Indicator', 'Dataset', 'How it is made'], indRows('live'))}` : ''}
      <h2 class="govuk-heading-l">Published as released</h2>
      <details class="govuk-details"><summary class="govuk-details__summary"><span class="govuk-details__summary-text">All ${n('published')} published indicators and their source series</span></summary><div class="govuk-details__text">${table(['Indicator', 'Dataset', 'Source'], indRows('published'))}</div></details>
      <p class="govuk-body">Each dataset's page gives the exact URL fetched, when, and a checksum: see <a class="govuk-link" href="#/lineage">data lineage</a>.</p>`;
    const h = BA.query.get('c'); if (h && document.getElementById('prov-' + h)) { BA.keepScroll = true; document.getElementById('prov-' + h).scrollIntoView(); }
  });
})();
