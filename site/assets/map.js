/* Map explorer: LSOA/MSOA choropleths, providers, commuting flows, catchment rings. */
(function () {
  'use strict';
  const BA = window.BA;
  const esc = BA.esc;
  const RAMP = ['#f1f6fb', '#c6dbef', '#8bb8dc', '#4a90c4', '#1d5f99', '#0b3b66'];
  const RAMP_BAD = ['#fdf3ee', '#f9d0bb', '#f2a17f', '#e06e4c', '#b8432a', '#7f2516'];
  const PROVIDER_COLORS = { 'FE college': '#801650', 'Sixth form': '#28A197', 'Secondary school': '#12436D', 'Special': '#A285D1', 'Independent': '#6f777b', 'Other': '#F46A25' };
  const PROVIDER_LABELS = { 'FE college': 'College or university', 'Sixth form': '16-19 school', 'Secondary school': 'Secondary school', 'Special': 'Special school (post-16)', 'Independent': 'Independent (16+)', 'Other': 'Alternative provision' };

  function centroid(geom) {
    let best = null, area = -1;
    const polys = geom.type === 'Polygon' ? [geom.coordinates] : geom.coordinates;
    polys.forEach((p) => { const r = p[0]; let a = 0; for (let i = 0; i < r.length - 1; i++) a += r[i][0] * r[i + 1][1] - r[i + 1][0] * r[i][1]; if (Math.abs(a) > area) { area = Math.abs(a); best = r; } });
    let x = 0, y = 0; best.forEach((c) => { x += c[0]; y += c[1]; });
    return [y / best.length, x / best.length];
  }
  function km(a, b) {
    const R = 6371, dLat = (b[0] - a[0]) * Math.PI / 180, dLon = (b[1] - a[1]) * Math.PI / 180;
    const s = Math.sin(dLat / 2) ** 2 + Math.cos(a[0] * Math.PI / 180) * Math.cos(b[0] * Math.PI / 180) * Math.sin(dLon / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(s));
  }
  BA.km = km;
  // ukprn -> latest Ofsted FE and skills judgement text (legacy grade or report card).
  BA.ofstedFE = async function () {
    if (BA._ofsted) return BA._ofsted;
    const o = {};
    if (BA.has('ofsted_fe')) (await BA.dataset('ofsted_fe')).rows.filter((r) => r.indicator === 'ofsted_fe_overall' && r.attrs && r.attrs.ukprn).forEach((r) => {
      const a = r.attrs; o[a.ukprn] = a.report_card ? 'report card ' + (a.report_card_date || '') : a.legacy_overall_effectiveness ? `${a.legacy_overall_effectiveness} (${r.period})` : null;
    });
    return (BA._ofsted = o);
  };
  function providerType(a) {
    const c = String(a.category || '');
    if (c) {
      if (/FE college|Sixth form college|Higher education/.test(c)) return 'FE college';
      if (/16-19/.test(c)) return 'Sixth form';
      if (/Special/.test(c)) return 'Special';
      if (/Independent/.test(c)) return 'Independent';
      if (/Secondary|All-through/.test(c)) return 'Secondary school';
      return 'Other';
    }
    const t = ((a.type || '') + ' ' + (a.phase || '') + ' ' + (a.group || '')).toLowerCase();
    if (/further education|fe college|general fe|college/.test(t) && !/sixth form college/.test(t)) return 'FE college';
    if (/sixth form/.test(t)) return 'Sixth form';
    if (/special/.test(t)) return 'Special';
    if (/independent/.test(t)) return 'Independent';
    if (/secondary|all-through|academy|free school|community|foundation|voluntary|studio|technical/.test(t)) return 'Secondary school';
    return 'Other';
  }

  BA.route(/^\/explore$/, async (app) => {
    const smallInds = Object.values(BA.indicators).filter((i) => /LSOA|MSOA/i.test(i.levels));
    const Q = BA.query;
    const want = Q.get('ind') || 'census_inactive_non_student_non_retired_pct';
    const wantLayers = Q.has('layers') ? new Set(Q.get('layers').split(',')) : null;
    wantLayersG = wantLayers;
    app.innerHTML = `<span class="govuk-caption-xl">Explore</span><h1 class="govuk-heading-xl">Where is the potential workforce?</h1>
      <p class="govuk-body">Shade neighbourhoods (2021 LSOAs, about 1,500 residents each) by any small-area indicator. Overlay schools, colleges and commuting flows, then draw a catchment around the site to total the cohorts within reach. Select an area for every indicator held for it.</p>
      <div class="ba-mapwrap"><div class="ba-panel">
        <div class="govuk-form-group"><label class="govuk-label govuk-label--s" for="ind">Shade areas by</label>
          <select class="govuk-select" id="ind">${groupOptions(smallInds, want)}</select></div>
        <div class="govuk-form-group" id="bdwrap" hidden><label class="govuk-label govuk-label--s" for="bd">Breakdown</label><select class="govuk-select" id="bd"></select></div>
        <div class="govuk-form-group"><label class="govuk-label govuk-label--s" for="laf">Local authority</label>
          <select class="govuk-select" id="laf"><option value="">All of Bedfordshire</option>${Object.entries(BA.LAS).map(([c, n]) => `<option value="${c}">${n}</option>`).join('')}</select></div>
        <div class="govuk-form-group"><fieldset class="govuk-fieldset"><legend class="govuk-fieldset__legend govuk-fieldset__legend--s">Layers</legend>
          <div class="govuk-checkboxes govuk-checkboxes--small">
            ${cb('l-la', 'Local authority boundaries', true)}${cb('l-pcon', 'Parliamentary constituencies (2024)', false)}
            ${cb('l-prov', 'Schools and colleges', false)}${cb('l-ks4', 'Schools shaded by GCSE attainment', false)}
            ${cb('l-od', 'Commuting into Bedfordshire (Census 2021)', false)}${cb('l-ring', 'Distance rings from the site', true)}
          </div></fieldset></div>
        <div class="govuk-form-group"><label class="govuk-label govuk-label--s" for="cmode">Catchment measured by</label>
          <select class="govuk-select" id="cmode"><option value="km">Straight-line distance</option><option value="mixed">Journey time: car if available, else bus, rail or bike</option><option value="pt">Journey time: public transport</option><option value="noncar">Journey time: public transport or cycle</option><option value="car">Journey time: car</option></select></div>
        <div class="govuk-form-group"><label class="govuk-label govuk-label--s" for="rad">Catchment: <span id="radv">15</span> <span id="radu">km</span></label>
          <input type="range" id="rad" min="3" max="40" value="15" step="1" style="width:100%"></div>
        <div class="ba-info" id="catch"><p class="govuk-body-s">Loading…</p></div>
      </div><div><div id="map" role="region" aria-label="Map of Bedfordshire"></div>
        <div class="ba-two govuk-!-margin-top-4"><div><h2 class="govuk-heading-s">Selected area</h2><div class="ba-info" id="info"><p class="govuk-body-s">Select an area on the map.</p></div></div>
        <div><h2 class="govuk-heading-s">Highest 15 areas on this measure</h2><div class="ba-info" id="top"></div></div></div>
        <details class="govuk-details govuk-!-margin-top-4"><summary class="govuk-details__summary"><span class="govuk-details__summary-text">View every area as a table</span></summary><div class="govuk-details__text" id="alltable"></div></details>
        <p class="ba-small govuk-!-margin-top-2">Shading uses quantiles (six equal-count classes) within the selected area. Suppressed or missing values are grey. LSOA figures carry Census perturbation and survey caveats. See <a class="govuk-link" href="#/method">method</a>.</p>
      </div></div>`;

    const map = L.map('map', { scrollWheelZoom: false, zoomSnap: 0.25 }).setView([BA.SITE.lat, BA.SITE.lon], 10);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors', maxZoom: 18, className: 'ba-basemap' }).addTo(map);
    map.on('click', () => map.scrollWheelZoom.enable());
    BA.onLeave = () => map.remove();

    const [lsoaGeo, laGeo, ctxGeo, pconGeo, msoaGeo] = await Promise.all(['lsoa', 'la', 'la_context', 'pcon', 'msoa'].map((n) => BA.tryJson('data/geo/' + n + '.geojson')));
    const site = [BA.SITE.lat, BA.SITE.lon];
    const feats = {};
    [lsoaGeo, msoaGeo].forEach((g) => g && g.features.forEach((f) => { f.properties._c = centroid(f.geometry); feats[f.properties.code] = f; }));

    if (ctxGeo) L.geoJSON(ctxGeo, { style: { color: '#6f777b', weight: 1, fillColor: '#f3f2f1', fillOpacity: 0.5, dashArray: '3 3' }, onEachFeature: (f, l) => l.bindTooltip(esc(f.properties.name)) }).addTo(map);
    let choro = null; const laLayer = laGeo ? L.geoJSON(laGeo, { style: { color: '#0b0c0c', weight: 2.5, fill: false }, interactive: false }) : null;
    const pconLayer = pconGeo ? L.geoJSON(pconGeo, { style: { color: '#801650', weight: 1.5, fill: false, dashArray: '6 4' }, onEachFeature: (f, l) => l.bindTooltip(esc(f.properties.name), { sticky: true }) }) : null;
    const ringLayer = L.layerGroup([5, 10, 20, 30].map((r) => L.circle(site, { radius: r * 1000, color: '#d4351c', weight: 1, fill: false, dashArray: '4 4', interactive: false }))
      .concat([L.marker(site, { icon: L.divIcon({ className: 'ba-site-icon', iconSize: [14, 14] }), title: BA.SITE.name }).bindPopup(`<strong>${esc(BA.SITE.name)}</strong>`)]));
    const catchCircle = L.circle(site, { radius: 15000, color: '#d4351c', weight: 2, fillColor: '#d4351c', fillOpacity: 0.04, interactive: false }).addTo(map);
    const catchLayer = L.layerGroup().addTo(map);
    let areaLayer = null;
    const travel = await BA.travelLsoa();
    if (!travel) [...document.getElementById('cmode').options].forEach((o) => { if (o.value !== 'km') o.disabled = true; });
    if (Q.get('cm') && travel) document.getElementById('cmode').value = Q.get('cm');
    let provLayer = null, ks4Layer = null, odLayer = null;
    const legend = L.control({ position: 'bottomright' }); legend.onAdd = () => L.DomUtil.create('div', 'ba-maplegend'); legend.addTo(map);

    const $ = (id) => document.getElementById(id);
    async function buildPoints() {
      if (!provLayer && BA.has('providers')) {
        const ds = await BA.dataset('providers');
        const ofs = await BA.ofstedFE();
        provLayer = L.layerGroup(ds.rows.filter((r) => r.level === 'point' && r.lat).filter((r, i, a) => a.findIndex((x) => x.code === r.code) === i).map((r) => {
          const a = r.attrs || {}; const t = providerType(a);
          return L.circleMarker([r.lat, r.lon], { radius: t === 'FE college' ? 8 : 5, color: '#fff', weight: 1.5, fillColor: PROVIDER_COLORS[t], fillOpacity: 1 })
            .bindPopup(`<strong>${esc(r.name)}</strong><br>${esc(a.category || t)} · ${esc(a.type || '')}<br>${a.sixth_form ? esc(a.sixth_form) + '<br>' : ''}${a.pupils || a.number_of_pupils ? 'Pupils: ' + esc(a.pupils || a.number_of_pupils) + '<br>' : ''}${a.pct_fsm != null ? 'Free school meals: ' + esc(a.pct_fsm) + '%<br>' : ''}${a.age_range ? 'Ages ' + esc(a.age_range) + '<br>' : ''}${ofs[a.ukprn] ? 'Ofsted (FE and skills): ' + esc(ofs[a.ukprn]) + '<br>' : ''}${a.dist_km != null ? esc(a.dist_km) + ' km from site' : ''}${a.website ? '<br>' + BA.link(String(a.website).startsWith('http') ? a.website : 'https://' + a.website, 'Website') : ''}`);
        }));
      }
      if (!ks4Layer && BA.has('dfe_ks4_school')) {
        const ds = await BA.dataset('dfe_ks4_school');
        const ind = (ds.meta.indicators || []).find((i) => /attainment.?8|a8/i.test(i.id + i.label)) || (ds.meta.indicators || [])[0];
        const rows = ds.rows.filter((r) => r.indicator === ind.id && r.lat && r.value != null);
        const lp = BA.latestPeriod(rows); const cur = rows.filter((r) => r.period === lp);
        const vals = cur.map((r) => r.value).sort((a, b) => a - b);
        const q = (p) => vals[Math.floor(p * (vals.length - 1))];
        const brk = [q(0.2), q(0.4), q(0.6), q(0.8)];
        ks4Layer = L.layerGroup(cur.map((r) => { const k = brk.filter((b) => r.value > b).length; return L.circleMarker([r.lat, r.lon], { radius: 7, color: '#0b0c0c', weight: 1, fillColor: RAMP[k + 1], fillOpacity: 1 }).bindPopup(`<strong>${esc(r.name)}</strong><br>${esc(ind.label)}: ${BA.fmt(r.value, ind.unit)} (${esc(lp)})`); }));
      }
      if (!odLayer && BA.has('census_od')) {
        const ds = await BA.dataset('census_od');
        odLayer = L.layerGroup(BA.odLines(ds.rows).map((f) => L.polyline([f.from, f.to], { color: '#801650', weight: Math.max(1, Math.sqrt(f.n) / 12), opacity: 0.55 }).bindTooltip(`${esc(f.label)}: ${BA.fmt(f.n, 'count')} workers`, { sticky: true })));
      }
    }
    // Adapter: turn census_od rows into flow lines {from:[lat,lon], to:[lat,lon], n, label}
    BA.odLines = BA.odLines || function (rows) {
      return rows.filter((r) => r.attrs && r.value > 0 && r.attrs.from_lat != null && r.attrs.to_lat != null && r.attrs.from_code !== r.attrs.to_code && /inflow|into|work/i.test(r.indicator))
        .map((r) => ({ from: [r.attrs.from_lat, r.attrs.from_lon], to: [r.attrs.to_lat, r.attrs.to_lon], n: r.value, label: `${r.attrs.from_name || r.name} → ${r.attrs.to_name || ''}` }));
    };

    async function syncLayers() {
      await buildPoints();
      [[laLayer, 'l-la'], [pconLayer, 'l-pcon'], [provLayer, 'l-prov'], [ks4Layer, 'l-ks4'], [odLayer, 'l-od'], [ringLayer, 'l-ring']].forEach(([layer, id]) => {
        const box = $(id); if (!layer) { box.disabled = true; box.parentElement.title = 'Data not loaded'; return; }
        if (box.checked) layer.addTo(map); else map.removeLayer(layer);
      });
      if (laLayer && $('l-la').checked) laLayer.bringToFront();
    }

    let cur = { vals: {}, ind: null };
    async function drawChoro() {
      const id = $('ind').value; const ind = BA.indicators[id];
      if (!ind) { $('catch').innerHTML = '<p class="govuk-body-s">No small-area data loaded yet.</p>'; return; }
      const all = await BA.rowsFor(id, { level: ['LSOA', 'MSOA'] });
      const bds = [...new Set(all.map((r) => r.breakdown || ''))];
      $('bdwrap').hidden = bds.length < 2;
      if (bds.length > 1 && ![...$('bd').options].some((o) => bds.includes(o.value))) $('bd').innerHTML = bds.map((b) => `<option value="${esc(b)}">${esc(b || 'All')}</option>`).join('');
      const bd = bds.length > 1 ? $('bd').value : bds[0];
      let rows = all.filter((r) => (r.breakdown || '') === bd);
      const lp = BA.latestPeriod(rows); rows = rows.filter((r) => r.period === lp);
      const la = $('laf').value;
      const level = rows[0] ? rows[0].level : 'LSOA';
      const geo = level === 'MSOA' ? msoaGeo : lsoaGeo;
      const vals = {}; rows.forEach((r) => (vals[r.code] = r));
      cur = { vals, ind, period: lp, level };
      const inLA = (f) => !la || f.properties.la === la || (f.properties.la_code === la);
      const nums = geo ? geo.features.filter(inLA).map((f) => vals[f.properties.code]).filter((r) => r && r.value != null).map((r) => r.value).sort((a, b) => a - b) : [];
      const brk = [1, 2, 3, 4, 5].map((k) => nums[Math.floor((k / 6) * (nums.length - 1))]);
      const ramp = ind.polarity === 'higher_is_worse' ? RAMP_BAD : RAMP;
      const color = (v) => (v == null ? '#d9d9d9' : ramp[brk.filter((b) => v > b).length]);
      if (choro) map.removeLayer(choro);
      if (!geo) return;
      choro = L.geoJSON({ type: 'FeatureCollection', features: geo.features.filter(inLA) }, {
        style: (f) => { const r = vals[f.properties.code]; return { color: '#ffffff', weight: 0.6, fillColor: color(r ? r.value : null), fillOpacity: 0.82 }; },
        onEachFeature: (f, l) => {
          const r = vals[f.properties.code];
          l.bindTooltip(`<strong>${esc(f.properties.hcl_name || f.properties.name)}</strong><br>${esc(ind.label)}: ${r ? (r.suppressed ? 'suppressed' : BA.fmt(r.value, ind.unit)) : 'no data'}`, { sticky: true });
          l.on('click', () => showInfo(f));
          l.on('mouseover', () => l.setStyle({ weight: 2.5, color: '#0b0c0c' })); l.on('mouseout', () => choro.resetStyle(l));
        },
      }).addTo(map);
      choro.bringToBack();
      if (la && choro.getBounds().isValid()) map.fitBounds(choro.getBounds(), { padding: [10, 10] });
      legend.getContainer().innerHTML = `<strong>${esc(ind.label)}</strong> ${BA.provIndTag(ind.id)}<br><span class="ba-small">${esc(lp || '')}${bd ? ' · ' + esc(bd) : ''}</span><br>` +
        ramp.map((c, i) => `<i style="background:${c}"></i>${i === 0 ? '≤ ' + BA.fmt(brk[0], ind.unit) : i === 5 ? '> ' + BA.fmt(brk[4], ind.unit) : BA.fmt(brk[i - 1], ind.unit) + ' – ' + BA.fmt(brk[i], ind.unit)}`).join('<br>') + '<br><i style="background:#d9d9d9"></i>No data' +
        ($('l-prov').checked ? '<hr style="margin:6px 0">' + Object.keys(PROVIDER_COLORS).map((k) => `<i style="background:${PROVIDER_COLORS[k]};border-radius:50%;width:12px"></i>${PROVIDER_LABELS[k]}`).join('<br>') : '');
      const top = geo.features.filter(inLA).map((f) => ({ f, r: vals[f.properties.code] })).filter((x) => x.r && x.r.value != null).sort((a, b) => b.r.value - a.r.value).slice(0, 15);
      $('top').innerHTML = `<table><tbody>${top.map((x, i) => `<tr><td>${i + 1}. <a href="#" class="govuk-link" data-code="${x.f.properties.code}">${esc(x.f.properties.hcl_name || x.f.properties.name)}</a> <span class="ba-small">${esc(x.f.properties.la_name || BA.LAS[x.f.properties.la] || '')}</span></td><td>${BA.fmt(x.r.value, ind.unit)}</td></tr>`).join('')}</tbody></table>`;
      $('top').querySelectorAll('a').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); const f = feats[a.dataset.code]; map.setView(f.properties._c, 13); showInfo(f); }));
      const allRows = geo.features.filter(inLA).map((f) => ({ f, r: vals[f.properties.code] })).sort((a, b) => ((b.r && b.r.value) ?? -Infinity) - ((a.r && a.r.value) ?? -Infinity));
      $('alltable').innerHTML = `<div class="ba-table-wrap" style="max-height:480px;overflow:auto"><table class="govuk-table ba-mini"><caption class="govuk-table__caption govuk-table__caption--s">${esc(ind.label)}${bd ? ' (' + esc(bd) + ')' : ''}, ${esc(lp || '')}: ${allRows.length} areas, highest first</caption><thead class="govuk-table__head"><tr class="govuk-table__row"><th class="govuk-table__header" scope="col">Rank</th><th class="govuk-table__header" scope="col">Area</th><th class="govuk-table__header" scope="col">Authority</th><th class="govuk-table__header govuk-table__header--numeric" scope="col">Value</th></tr></thead><tbody class="govuk-table__body">${allRows.map((x, i) => `<tr class="govuk-table__row"><td class="govuk-table__cell">${i + 1}</td><td class="govuk-table__cell"><a class="govuk-link" href="#/area/${x.f.properties.code}">${esc(x.f.properties.hcl_name || x.f.properties.name)}</a></td><td class="govuk-table__cell">${esc(BA.LAS[x.f.properties.la] || '')}</td><td class="govuk-table__cell govuk-table__cell--numeric">${x.r ? (x.r.suppressed ? 'suppressed' : BA.fmt(x.r.value, ind.unit)) : 'no data'}</td></tr>`).join('')}</tbody></table></div>`;
      updateCatch();
      syncURL();
    }
    function syncURL() {
      const q = new URLSearchParams({ ind: $('ind').value });
      if ($('bd').value && !$('bdwrap').hidden) q.set('bd', $('bd').value);
      if ($('laf').value) q.set('la', $('laf').value);
      q.set('layers', [...document.querySelectorAll('.ba-panel input[type=checkbox]')].filter((c) => c.checked).map((c) => c.id.slice(2)).join(','));
      q.set('cm', $('cmode').value); q.set('r', $('rad').value);
      if (Q.get('area')) q.set('area', Q.get('area'));
      history.replaceState(null, '', '#/explore?' + q.toString());
    }

    async function showInfo(f) {
      const code = f.properties.code;
      const dsIds = [...new Set(smallInds.map((i) => i.dataset))];
      const rows = (await Promise.all(dsIds.map((d) => BA.dataset(d)))).flatMap((ds) => ds.rows.filter((r) => r.code === code));
      const latest = {};
      rows.forEach((r) => { const k = r.indicator + '|' + (r.breakdown || ''); if (!latest[k] || BA.periodCmp(r.period, latest[k].period) > 0) latest[k] = r; });
      const dist = km(site, f.properties._c);
      const tt = travel && travel[code];
      $('info').innerHTML = `<p class="govuk-body-s govuk-!-margin-bottom-1"><strong>${esc(f.properties.hcl_name || f.properties.name)}</strong> (${esc(code)})<br>${esc(f.properties.la_name || BA.LAS[f.properties.la] || '')} · ${dist.toFixed(1)} km from the site${tt && tt.pt != null ? ' · ' + BA.fmt(tt.pt, 'minutes') + ' by public transport' : ''}<br><a class="govuk-link" href="#/area/${esc(code)}">Open the full area profile</a></p>
        <table><tbody>${Object.values(latest).map((r) => { const ind = BA.indicators[r.indicator] || {}; return `<tr><td>${esc(ind.label || r.indicator)}${r.breakdown ? ' <span class="ba-small">(' + esc(r.breakdown) + ')</span>' : ''}</td><td>${r.suppressed ? 'supp.' : BA.fmt(r.value, ind.unit)}</td></tr>`; }).join('')}</tbody></table>`;
    }

    function setSlider(mode, keep) {
      const r = $('rad');
      if (mode === 'km') { r.min = 3; r.max = 40; r.step = 1; if (!keep) r.value = 15; $('radu').textContent = 'km'; }
      else { r.min = 15; r.max = 90; r.step = 5; if (!keep) r.value = 45; $('radu').textContent = 'minutes'; }
    }
    async function updateCatch() {
      const mode = $('cmode').value; const rad = +$('rad').value; $('radv').textContent = rad;
      // weight per LSOA: 1 inside, 0 outside (distance), or the share of residents able to make the journey
      const weight = {};
      Object.values(feats).forEach((f) => { const c = f.properties.code; if (!/^E01/.test(c)) return;
        weight[c] = mode === 'km' ? (km(site, f.properties._c) <= rad ? 1 : 0) : (BA.reachFrac(travel && travel[c], { mode, minutes: rad, late: false }) || 0); });
      catchCircle.setRadius(mode === 'km' ? rad * 1000 : 0); catchCircle.setStyle({ opacity: mode === 'km' ? 1 : 0, fillOpacity: mode === 'km' ? 0.04 : 0 });
      catchLayer.clearLayers();
      if (mode !== 'km') Object.entries(weight).forEach(([c, w]) => { if (w >= 0.5 && feats[c]) catchLayer.addLayer(L.geoJSON(feats[c], { style: { color: '#d4351c', weight: 1.6, fill: false }, interactive: false })); });
      const countInds = smallInds.filter((i) => i.unit === 'count');
      const sums = await Promise.all(countInds.map(async (ind) => {
        const rows = (await BA.rowsFor(ind.id, { level: 'LSOA' })).filter((r) => !r.breakdown);
        const lp = BA.latestPeriod(rows);
        let s = 0, n = 0; rows.forEach((r) => { if (r.period === lp && weight[r.code] && r.value != null) { s += r.value * weight[r.code]; n++; } });
        return { ind, s, n };
      }));
      const nIn = Object.values(weight).filter((w) => w >= 0.5).length;
      $('catch').innerHTML = `<p class="govuk-body-s govuk-!-margin-bottom-1">${mode === 'km' ? '' : BA.provTag('modelled', 'Journey-time model.') + ' '}${mode === 'km' ? `<strong>${nIn}</strong> Bedfordshire neighbourhoods within ${rad} km of the site (by centroid).` : `People who can reach the site within <strong>${rad} minutes</strong> (${esc(BA.REACH_MODES[mode].toLowerCase())}), arriving by 08:30. Mostly reachable neighbourhoods are outlined in red.`} Neighbouring authorities are not included.</p><table><tbody>${sums.filter((x) => x.n).map((x) => `<tr><td>${esc(x.ind.label)}</td><td>${BA.fmt(Math.round(x.s), 'count')}</td></tr>`).join('')}</tbody></table>`;
      BA.lastCatchment = { mode, rad, sums };
      syncURL();
    }
    function showArea(code) {
      const set = new Set(BA.lsoasFor ? BA.lsoasFor(code) : [code]);
      if (areaLayer) map.removeLayer(areaLayer);
      areaLayer = L.geoJSON({ type: 'FeatureCollection', features: [...set].map((c) => feats[c]).filter(Boolean) }, { style: { color: '#0b0c0c', weight: 3, fill: false }, interactive: false }).addTo(map);
      if (areaLayer.getBounds().isValid()) map.fitBounds(areaLayer.getBounds(), { padding: [30, 30], maxZoom: 14 });
      if (/^E01/.test(code) && feats[code]) showInfo(feats[code]);
    }

    $('cmode').addEventListener('change', () => { setSlider($('cmode').value); updateCatch(); });
    setSlider($('cmode').value, false);
    if (Q.get('r')) $('rad').value = Q.get('r');
    if (Q.get('la')) $('laf').value = Q.get('la');
    $('ind').addEventListener('change', () => { $('bd').innerHTML = ''; drawChoro(); });
    $('bd').addEventListener('change', drawChoro);
    $('laf').addEventListener('change', drawChoro);
    let t; $('rad').addEventListener('input', () => { clearTimeout(t); t = setTimeout(updateCatch, 120); });
    document.querySelectorAll('.ba-panel input[type=checkbox]').forEach((c) => c.addEventListener('change', () => { syncLayers(); syncURL(); if (c.id === 'l-prov') drawChoro(); }));
    await syncLayers();
    if (Q.get('bd')) { await drawChoro(); $('bd').value = Q.get('bd'); }
    await drawChoro();
    if (Q.get('area')) showArea(Q.get('area'));
  });

  let wantLayersG = null;
  function cb(id, label, on) { if (wantLayersG) on = wantLayersG.has(id.slice(2)); return `<div class="govuk-checkboxes__item"><input class="govuk-checkboxes__input" id="${id}" type="checkbox" ${on ? 'checked' : ''}><label class="govuk-label govuk-checkboxes__label" for="${id}">${label}</label></div>`; }
  function groupOptions(inds, want) {
    const groups = {};
    inds.forEach((i) => { const g = BA.cohortsOf(i)[0]; (groups[g] = groups[g] || []).push(i); });
    const order = ['25+ inactive', '18-24', '16-19', 'context'];
    return Object.keys(groups).sort((a, b) => order.indexOf(a) - order.indexOf(b)).map((g) => `<optgroup label="${esc((BA.COHORTS[g] || { label: g }).label)}">${groups[g].map((i) => `<option value="${i.id}" ${i.id === want ? 'selected' : ''}>${esc(i.label)}</option>`).join('')}</optgroup>`).join('');
  }
})();
