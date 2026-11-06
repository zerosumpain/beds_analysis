/* Area profiles: one printable page for any neighbourhood, ward, MSOA, constituency or
   authority, built by aggregating LSOA data. Search by place name or postcode. */
(function () {
  'use strict';
  const BA = window.BA;
  const esc = BA.esc;
  const KIND = { E01: 'Neighbourhood (LSOA)', E02: 'Middle-layer area (MSOA)', E05: 'Ward', E14: 'Constituency', E06: 'Local authority', BEDS: 'County' };
  const KEY = { E02: 'msoa', E05: 'ward', E14: 'pcon', E06: 'la' };
  const kindOf = (code) => KIND[code === 'BEDS' ? 'BEDS' : code.slice(0, 3)] || 'Area';

  let msoaNames = null;
  async function names() {
    if (msoaNames) return msoaNames;
    const g = await BA.tryJson('data/geo/msoa.geojson');
    msoaNames = {}; (g ? g.features : []).forEach((f) => (msoaNames[f.properties.code] = f.properties.hcl_name ? `${f.properties.hcl_name} (${f.properties.name})` : f.properties.name));
    return msoaNames;
  }
  BA.lsoasFor = function (code) {
    const L = BA.lsoaLookup || {};
    if (code === 'BEDS') return Object.keys(L);
    if (/^E01/.test(code)) return L[code] ? [code] : [];
    const k = KEY[code.slice(0, 3)]; if (!k) return [];
    return Object.keys(L).filter((c) => L[c][k] === code);
  };
  async function areaName(code) {
    const L = BA.lsoaLookup || {};
    if (code === 'BEDS') return 'Bedfordshire (Bedford, Central Bedfordshire and Luton)';
    if (BA.LAS[code]) return BA.LAS[code];
    if (/^E01/.test(code)) return L[code] ? L[code].name : code;
    if (/^E02/.test(code)) return (await names())[code] || code;
    const first = Object.values(L).find((x) => x.ward === code || x.pcon === code);
    return first ? (/^E05/.test(code) ? first.ward_name : first.pcon_name) : code;
  }
  // Search index: every area with a name.
  async function searchIndex() {
    const L = BA.lsoaLookup || {}; const out = new Map();
    Object.entries(BA.LAS).forEach(([c, n]) => out.set(c, n));
    Object.entries(L).forEach(([c, x]) => { out.set(x.ward, x.ward_name + ' ward, ' + x.la_name); out.set(x.pcon, x.pcon_name + ' constituency'); out.set(c, x.name + ' (' + x.ward_name + ')'); });
    const mn = await names(); Object.entries(mn).forEach(([c, n]) => out.set(c, n));
    return [...out.entries()].map(([code, label]) => ({ code, label }));
  }
  // Point in polygon against LSOA boundaries.
  function inRing(pt, ring) { let inside = false; for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) { const [xi, yi] = ring[i], [xj, yj] = ring[j]; if ((yi > pt[1]) !== (yj > pt[1]) && pt[0] < ((xj - xi) * (pt[1] - yi)) / (yj - yi) + xi) inside = !inside; } return inside; }
  async function lsoaAt(lat, lon) {
    const g = await BA.tryJson('data/geo/lsoa.geojson'); if (!g) return null;
    const pt = [lon, lat];
    const f = g.features.find((ft) => { const polys = ft.geometry.type === 'Polygon' ? [ft.geometry.coordinates] : ft.geometry.coordinates; return polys.some((p) => inRing(pt, p[0]) && !p.slice(1).some((h) => inRing(pt, h))); });
    return f ? f.properties.code : null;
  }

  BA.route(/^\/area$/, async (app) => {
    app.innerHTML = `<span class="govuk-caption-xl">Area profiles</span><h1 class="govuk-heading-xl">Profile any part of Bedfordshire</h1>
      <p class="govuk-body-l">Get a one-page profile of a neighbourhood, ward, constituency or authority: its young people and inactive adults, barriers to work, deprivation, journey times to the site and the nearest schools and colleges.</p>
      <form id="sf" class="govuk-!-margin-bottom-6" novalidate><div class="govuk-form-group" id="sfg"><label class="govuk-label govuk-label--m" for="sq">Search by place, ward or postcode</label>
        <div class="govuk-hint" id="sq-hint">For example Kempston, Lewsey, Leighton Buzzard or MK42 7AB. Postcodes are looked up with postcodes.io; nothing else leaves your browser.</div>
        <p class="govuk-error-message" id="serr" hidden></p>
        <input class="govuk-input govuk-input--width-20" id="sq" type="search" autocomplete="off" aria-describedby="sq-hint" aria-controls="sres">
        <button class="govuk-button govuk-!-margin-left-2 govuk-!-margin-bottom-0" type="submit">Search</button></div></form>
      <div id="sres" aria-live="polite"></div>
      <h2 class="govuk-heading-m">Or start from an authority</h2>
      <ul class="govuk-list">${['BEDS'].concat(Object.keys(BA.LAS)).map((c) => `<li><a class="govuk-link" href="#/area/${c}">${esc(c === 'BEDS' ? 'All of Bedfordshire' : BA.LAS[c])}</a></li>`).join('')}</ul>
      <p class="govuk-body">You can also select any neighbourhood on the <a class="govuk-link" href="#/explore">map</a>.</p>`;
    const idx = await searchIndex();
    const $ = (id) => document.getElementById(id);
    const show = (hits) => { $('sres').innerHTML = hits.length ? `<ul class="govuk-list">${hits.slice(0, 25).map((h) => `<li><a class="govuk-link" href="#/area/${h.code}">${esc(h.label)}</a> <span class="ba-small">${esc(kindOf(h.code))}</span></li>`).join('')}</ul>` : '<p class="govuk-body">No matching areas in Bedfordshire.</p>'; };
    const err = (m) => { $('serr').hidden = !m; $('serr').innerHTML = m ? '<span class="govuk-visually-hidden">Error:</span> ' + esc(m) : ''; $('sfg').classList.toggle('govuk-form-group--error', !!m); };
    $('sq').addEventListener('input', () => { const v = $('sq').value.trim().toLowerCase(); err(''); if (v.length < 2 || /\d/.test(v)) { $('sres').innerHTML = ''; return; } show(idx.filter((h) => h.label.toLowerCase().includes(v)).sort((a, b) => a.label.toLowerCase().indexOf(v) - b.label.toLowerCase().indexOf(v) || a.label.length - b.label.length)); });
    $('sf').addEventListener('submit', async (e) => {
      e.preventDefault(); err('');
      const v = $('sq').value.trim();
      if (/^[a-z]{1,2}\d[a-z\d]?\s*\d[a-z]{2}$/i.test(v)) {
        try {
          const r = await fetch('https://api.postcodes.io/postcodes/' + encodeURIComponent(v.replace(/\s+/g, '')));
          const j = await r.json();
          if (!r.ok || !j.result) return err('We could not find that postcode.');
          const code = await lsoaAt(j.result.latitude, j.result.longitude);
          if (!code) return err('That postcode is outside Bedford, Central Bedfordshire and Luton.');
          location.hash = '#/area/' + code;
        } catch (x) { err('The postcode lookup is not available right now. Search by place name instead.'); }
        return;
      }
      const hits = idx.filter((h) => h.label.toLowerCase().includes(v.toLowerCase()));
      if (hits.length === 1) location.hash = '#/area/' + hits[0].code; else if (!v) err('Enter a place, ward or postcode.'); else show(hits);
    });
  });

  // Aggregate LSOA rows for a set of LSOAs. Counts sum; rates with num/den recompute;
  // anything else (scores, minutes, deciles) is summarised as the median neighbourhood.
  function aggregate(rows, set) {
    const by = {};
    rows.forEach((r) => { if (r.level !== 'LSOA' || r.breakdown || !set.has(r.code)) return; (by[r.indicator] = by[r.indicator] || []).push(r); });
    const out = {};
    Object.entries(by).forEach(([id, rs]) => {
      const lp = BA.latestPeriod(rs); rs = rs.filter((r) => r.period === lp);
      const ind = BA.indicators[id] || {}; const vals = rs.map((r) => r.value).filter((v) => v != null);
      if (!vals.length) return;
      let v, how;
      if (ind.unit === 'count') { v = vals.reduce((a, x) => a + x, 0); how = 'sum'; }
      else if (rs.every((r) => r.num != null && r.den)) { const n = rs.reduce((a, r) => a + r.num, 0), d = rs.reduce((a, r) => a + r.den, 0); v = d ? 100 * n / d : null; how = 'rate'; }
      else { vals.sort((a, b) => a - b); v = set.size === 1 ? vals[0] : vals[Math.floor((vals.length - 1) / 2)]; how = set.size === 1 ? 'value' : 'median'; }
      out[id] = { v, how, period: lp, n: rs.length, suppressed: rs.some((r) => r.suppressed) };
    });
    return out;
  }

  const SECTIONS = [
    ['Young people and working-age residents', ['popsa_16_19', 'popsa_18_24', 'popsa_25_64', 'popsa_16_64', 'popsa_all']],
    ['Work and worklessness', ['cc_all', 'cc_all_rate', 'cc_16_24', 'cc_16_24_rate', 'cc_25_49', 'cc_50plus', 'census_unemp_rate_pct', 'census_inactive_pct', 'census_inactive_non_student_non_retired', 'census_inactive_non_student_non_retired_pct', 'census_inactive_ltsick', 'census_inactive_home', 'census_inactive_other', 'uc_nwr', 'uc_searching']],
    ['Skills and qualifications', ['census_noqual_pct', 'census_level3plus_pct', 'census_level4plus_pct', 'census_apprenticeship_pct']],
    ['Barriers to work', ['cb_hh_nocar_pct', 'cb_eng_poor_pct', 'cb_lone_parent_dep_pct', 'cb_bad_health_pct', 'census_disabled_pct', 'census_care20plus_pct']],
    ['Deprivation (IMD 2025, 1 = most deprived 10% in England)', ['imd25_imd_decile', 'imd25_employment_decile', 'imd25_income_decile', 'imd25_education_decile', 'imd25_adultskills_decile']],
    ['Getting to the site', ['tt_pt_am_min', 'tt_pt_late_min', 'tt_cycle_min', 'tt_car_min']],
  ];

  BA.route(/^\/area\/([\w]+)$/, async (app, code) => {
    const lsoas = BA.lsoasFor(code);
    if (!lsoas.length) throw new Error('No Bedfordshire neighbourhoods found for ' + code);
    const set = new Set(lsoas), all = new Set(Object.keys(BA.lsoaLookup));
    const name = await areaName(code);
    const LK = BA.lsoaLookup;
    const parent = /^E01/.test(code) ? `${esc(LK[code].ward_name)} ward · ${esc(LK[code].la_name)} · <a class="govuk-link" href="#/area/${LK[code].msoa}">MSOA</a> · <a class="govuk-link" href="#/area/${LK[code].ward}">ward profile</a>` : `${lsoas.length} neighbourhoods${/^E0[25]/.test(code) ? ' · ' + esc(LK[lsoas[0]].la_name) : ''}`;
    app.innerHTML = `<a href="#/area" class="govuk-back-link ba-noprint">Search for another area</a>
      <span class="govuk-caption-xl">${esc(kindOf(code))} profile</span><h1 class="govuk-heading-xl">${esc(name)}</h1>
      <p class="govuk-body">${parent}</p>
      <div class="govuk-button-group ba-noprint"><button class="govuk-button govuk-button--secondary" onclick="window.print()">Print or save as PDF</button><button class="govuk-button govuk-button--secondary" id="acsv">Download (CSV)</button><a class="govuk-link" href="#/explore?area=${code}">Show on the map</a></div>
      <div class="ba-two"><div id="atiles" class="ba-tiles" style="grid-template-columns:repeat(auto-fill,minmax(180px,1fr))"></div><div id="amap" style="height:320px;border:1px solid #b1b4b6"></div></div>
      <div id="asec"></div>
      <h2 class="govuk-heading-l">Nearest schools and colleges with post-16 provision</h2><div id="aprov"></div>
      <p class="ba-small">Counts are sums of neighbourhood figures; percentages are recomputed from summed numerators and denominators; scores, deciles and journey times show the middle (median) neighbourhood. Census 2021 small-area counts are perturbed for disclosure control, so they may not add exactly. See <a class="govuk-link" href="#/method">method</a>.</p>`;

    const dsIds = [...new Set(Object.values(BA.indicators).filter((i) => /LSOA/i.test(i.levels)).map((i) => i.dataset))];
    const rows = (await Promise.all(dsIds.map((d) => BA.dataset(d)))).flatMap((ds) => ds.rows);
    const here = aggregate(rows, set), beds = code === 'BEDS' ? null : aggregate(rows, all);
    const fmtA = (id, a) => { const ind = BA.indicators[id] || {}; if (!a) return '–'; const u = a.how === 'rate' ? 'percent' : ind.unit; return BA.fmt(a.v, u); };
    const csv = [];
    const section = ([title, ids]) => {
      const present = ids.filter((id) => here[id]);
      if (!present.length) return '';
      return `<h2 class="govuk-heading-l govuk-!-margin-top-6">${esc(title)}</h2><div class="ba-table-wrap"><table class="govuk-table"><thead class="govuk-table__head"><tr class="govuk-table__row"><th class="govuk-table__header" scope="col">Measure</th><th class="govuk-table__header govuk-table__header--numeric" scope="col">${esc(name.length > 30 ? 'This area' : name)}</th>${beds ? '<th class="govuk-table__header govuk-table__header--numeric" scope="col">Bedfordshire</th>' : ''}<th class="govuk-table__header" scope="col">Period</th></tr></thead><tbody class="govuk-table__body">
        ${present.map((id) => { const ind = BA.indicators[id]; const a = here[id], b = beds && beds[id]; csv.push({ area_code: code, area: name, indicator: id, label: ind.label, value: a.v, method: a.how, bedfordshire: b ? b.v : '', period: a.period });
          return `<tr class="govuk-table__row"><th class="govuk-table__header" scope="row" style="font-weight:400">${esc(ind.label)} ${a.n > 1 && a.how !== 'value' ? BA.provTag('calculated', a.how === 'sum' ? 'Sum of ' + a.n + ' neighbourhoods.' : a.how === 'rate' ? 'Recalculated from the numerators and denominators of ' + a.n + ' neighbourhoods.' : 'Median of ' + a.n + ' neighbourhoods.') : BA.provIndTag(id)}${a.how === 'median' ? ' <span class="ba-small">(median area)</span>' : ''}${a.suppressed ? ' <span class="ba-small">(some suppressed)</span>' : ''}</th><td class="govuk-table__cell govuk-table__cell--numeric"><strong>${fmtA(id, a)}</strong></td>${beds ? `<td class="govuk-table__cell govuk-table__cell--numeric">${b && b.how !== 'sum' ? fmtA(id, b) : b ? '<span class="ba-small">' + fmtA(id, b) + '</span>' : '–'}</td>` : ''}<td class="govuk-table__cell ba-small">${esc(a.period)} ${BA.ageTag(a.period)}</td></tr>`; }).join('')}</tbody></table></div>`;
    };
    document.getElementById('asec').innerHTML = SECTIONS.map(section).join('');

    // headline tiles
    const tile = (label, id, sub) => here[id] ? `<div class="ba-tile"><p class="ba-tile__label">${esc(label)}</p><p class="ba-tile__value">${fmtA(id, here[id])}</p><p class="ba-tile__sub">${esc(sub || '')}</p></div>` : '';
    const tt = await BA.travelLsoa();
    let reachTile = '';
    if (tt) {
      const w = await BA.lsoaWeights(['popsa_16_64']); let n = 0, d = 0;
      lsoas.forEach((c) => { const f = BA.reachFrac(tt[c], BA.REACH_DEFAULT); if (f == null || !w[c]) return; n += w[c] * f; d += w[c]; });
      if (d) reachTile = `<div class="ba-tile ${n / d < 0.5 ? 'ba-tile--warn' : ''}"><p class="ba-tile__label">Residents 16-64 who can reach a shift in ${BA.REACH_DEFAULT.minutes} min</p><p class="ba-tile__value">${Math.round(100 * n / d)}%</p><p class="ba-tile__sub">Car where the household has one, else bus, rail or bike</p></div>`;
    }
    document.getElementById('atiles').innerHTML = tile('Aged 16 to 19', 'popsa_16_19', 'Residents') + tile('Aged 18 to 24', 'popsa_18_24', 'Residents') + tile('Inactive: sick, caring, home, other', 'census_inactive_non_student_non_retired', 'Census 2021, all ages 16+') + tile('Claimants', 'cc_all', 'Latest month') + reachTile + tile('Bus or rail to the site', 'tt_pt_am_min', 'Arriving by 08:30');

    // map
    const map = L.map('amap', { scrollWheelZoom: false, attributionControl: true });
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; OpenStreetMap contributors', maxZoom: 18, className: 'ba-basemap' }).addTo(map);
    BA.onLeave = () => map.remove();
    const g = await BA.tryJson('data/geo/lsoa.geojson');
    const layer = L.geoJSON({ type: 'FeatureCollection', features: (g ? g.features : []).filter((f) => set.has(f.properties.code)) }, { style: { color: '#1d70b8', weight: 1.5, fillColor: '#1d70b8', fillOpacity: 0.25 } }).addTo(map);
    L.marker([BA.SITE.lat, BA.SITE.lon], { icon: L.divIcon({ className: 'ba-site-icon', iconSize: [14, 14] }), title: BA.SITE.name }).addTo(map).bindTooltip('Resort site');
    const b = layer.getBounds(); if (b.isValid()) map.fitBounds(b.extend([BA.SITE.lat, BA.SITE.lon]), { padding: [16, 16] });
    const c = b.isValid() ? b.getCenter() : { lat: BA.SITE.lat, lng: BA.SITE.lon };

    // nearest providers
    if (BA.has('providers')) {
      const ds = await BA.dataset('providers');
      const ofs = BA.ofstedFE ? await BA.ofstedFE() : {};
      const seen = new Set();
      const pts = ds.rows.filter((r) => r.level === 'point' && r.lat && (r.attrs || {}).post16 !== false && !seen.has(r.code) && seen.add(r.code))
        .map((r) => ({ r, d: BA.km([c.lat, c.lng], [r.lat, r.lon]) })).sort((a, b2) => a.d - b2.d).slice(0, 8);
      document.getElementById('aprov').innerHTML = `<div class="ba-table-wrap"><table class="govuk-table"><thead class="govuk-table__head"><tr class="govuk-table__row"><th class="govuk-table__header" scope="col">Provider</th><th class="govuk-table__header" scope="col">Type</th><th class="govuk-table__header govuk-table__header--numeric" scope="col">Distance from the centre of this area</th></tr></thead><tbody class="govuk-table__body">${pts.map((x) => `<tr class="govuk-table__row"><th class="govuk-table__header" scope="row" style="font-weight:400">${esc(x.r.name)}<br><span class="ba-small">${esc((x.r.attrs || {}).town || '')}</span></th><td class="govuk-table__cell ba-small">${esc((x.r.attrs || {}).category || '')}${ofs[(x.r.attrs || {}).ukprn] ? ' · Ofsted FE: ' + esc(ofs[x.r.attrs.ukprn]) : ''}</td><td class="govuk-table__cell govuk-table__cell--numeric">${x.d.toFixed(1)} km</td></tr>`).join('')}</tbody></table></div>`;
    }
    document.getElementById('acsv').addEventListener('click', () => BA.downloadCSV('area-profile-' + code + '.csv', csv));
  });
})();
