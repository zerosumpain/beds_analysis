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
    const want = BA.query.get('ind') || 'census_inactive_non_student_non_retired_pct';
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
        <div class="govuk-form-group"><label class="govuk-label govuk-label--s" for="rad">Catchment radius from site: <span id="radv">15</span> km</label>
          <input type="range" id="rad" min="3" max="40" value="15" step="1" style="width:100%"></div>
        <div class="ba-info" id="catch"><p class="govuk-body-s">Loading…</p></div>
      </div><div><div id="map" role="region" aria-label="Map of Bedfordshire"></div>
        <div class="ba-two govuk-!-margin-top-4"><div><h2 class="govuk-heading-s">Selected area</h2><div class="ba-info" id="info"><p class="govuk-body-s">Select an area on the map.</p></div></div>
        <div><h2 class="govuk-heading-s">Highest 15 areas on this measure</h2><div class="ba-info" id="top"></div></div></div>
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
    let provLayer = null, ks4Layer = null, odLayer = null;
    const legend = L.control({ position: 'bottomright' }); legend.onAdd = () => L.DomUtil.create('div', 'ba-maplegend'); legend.addTo(map);

    const $ = (id) => document.getElementById(id);
    async function buildPoints() {
      if (!provLayer && BA.has('providers')) {
        const ds = await BA.dataset('providers');
        provLayer = L.layerGroup(ds.rows.filter((r) => r.level === 'point' && r.lat).filter((r, i, a) => a.findIndex((x) => x.code === r.code) === i).map((r) => {
          const a = r.attrs || {}; const t = providerType(a);
          return L.circleMarker([r.lat, r.lon], { radius: t === 'FE college' ? 8 : 5, color: '#fff', weight: 1.5, fillColor: PROVIDER_COLORS[t], fillOpacity: 1 })
            .bindPopup(`<strong>${esc(r.name)}</strong><br>${esc(a.category || t)} · ${esc(a.type || '')}<br>${a.sixth_form ? esc(a.sixth_form) + '<br>' : ''}${a.pupils || a.number_of_pupils ? 'Pupils: ' + esc(a.pupils || a.number_of_pupils) + '<br>' : ''}${a.pct_fsm != null ? 'Free school meals: ' + esc(a.pct_fsm) + '%<br>' : ''}${a.age_range ? 'Ages ' + esc(a.age_range) + '<br>' : ''}${a.dist_km != null ? esc(a.dist_km) + ' km from site' : ''}${a.website ? '<br>' + BA.link(String(a.website).startsWith('http') ? a.website : 'https://' + a.website, 'Website') : ''}`);
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
      legend.getContainer().innerHTML = `<strong>${esc(ind.label)}</strong><br><span class="ba-small">${esc(lp || '')}${bd ? ' · ' + esc(bd) : ''}</span><br>` +
        ramp.map((c, i) => `<i style="background:${c}"></i>${i === 0 ? '≤ ' + BA.fmt(brk[0], ind.unit) : i === 5 ? '> ' + BA.fmt(brk[4], ind.unit) : BA.fmt(brk[i - 1], ind.unit) + ' – ' + BA.fmt(brk[i], ind.unit)}`).join('<br>') + '<br><i style="background:#d9d9d9"></i>No data' +
        ($('l-prov').checked ? '<hr style="margin:6px 0">' + Object.keys(PROVIDER_COLORS).map((k) => `<i style="background:${PROVIDER_COLORS[k]};border-radius:50%;width:12px"></i>${PROVIDER_LABELS[k]}`).join('<br>') : '');
      const top = geo.features.filter(inLA).map((f) => ({ f, r: vals[f.properties.code] })).filter((x) => x.r && x.r.value != null).sort((a, b) => b.r.value - a.r.value).slice(0, 15);
      $('top').innerHTML = `<table><tbody>${top.map((x, i) => `<tr><td>${i + 1}. <a href="#" class="govuk-link" data-code="${x.f.properties.code}">${esc(x.f.properties.hcl_name || x.f.properties.name)}</a> <span class="ba-small">${esc(x.f.properties.la_name || BA.LAS[x.f.properties.la] || '')}</span></td><td>${BA.fmt(x.r.value, ind.unit)}</td></tr>`).join('')}</tbody></table>`;
      $('top').querySelectorAll('a').forEach((a) => a.addEventListener('click', (e) => { e.preventDefault(); const f = feats[a.dataset.code]; map.setView(f.properties._c, 13); showInfo(f); }));
      updateCatch();
      history.replaceState(null, '', '#/explore?ind=' + id);
    }

    async function showInfo(f) {
      const code = f.properties.code;
      const dsIds = [...new Set(smallInds.map((i) => i.dataset))];
      const rows = (await Promise.all(dsIds.map((d) => BA.dataset(d)))).flatMap((ds) => ds.rows.filter((r) => r.code === code));
      const latest = {};
      rows.forEach((r) => { const k = r.indicator + '|' + (r.breakdown || ''); if (!latest[k] || BA.periodCmp(r.period, latest[k].period) > 0) latest[k] = r; });
      const dist = km(site, f.properties._c);
      $('info').innerHTML = `<p class="govuk-body-s govuk-!-margin-bottom-1"><strong>${esc(f.properties.hcl_name || f.properties.name)}</strong> (${esc(code)})<br>${esc(f.properties.la_name || BA.LAS[f.properties.la] || '')} · ${dist.toFixed(1)} km from the site</p>
        <table><tbody>${Object.values(latest).map((r) => { const ind = BA.indicators[r.indicator] || {}; return `<tr><td>${esc(ind.label || r.indicator)}${r.breakdown ? ' <span class="ba-small">(' + esc(r.breakdown) + ')</span>' : ''}</td><td>${r.suppressed ? 'supp.' : BA.fmt(r.value, ind.unit)}</td></tr>`; }).join('')}</tbody></table>`;
    }

    async function updateCatch() {
      const rad = +$('rad').value; $('radv').textContent = rad; catchCircle.setRadius(rad * 1000);
      const inside = new Set(Object.values(feats).filter((f) => /^E01/.test(f.properties.code) && km(site, f.properties._c) <= rad).map((f) => f.properties.code));
      const countInds = smallInds.filter((i) => i.unit === 'count');
      const sums = await Promise.all(countInds.map(async (ind) => {
        const rows = (await BA.rowsFor(ind.id, { level: 'LSOA' })).filter((r) => !r.breakdown);
        const lp = BA.latestPeriod(rows);
        let s = 0, n = 0; rows.forEach((r) => { if (r.period === lp && inside.has(r.code) && r.value != null) { s += r.value; n++; } });
        return { ind, s, n };
      }));
      $('catch').innerHTML = `<p class="govuk-body-s govuk-!-margin-bottom-1"><strong>${inside.size}</strong> Bedfordshire neighbourhoods within ${rad} km of the site (by centroid). Neighbouring authorities are not included.</p><table><tbody>${sums.filter((x) => x.n).map((x) => `<tr><td>${esc(x.ind.label)}</td><td>${BA.fmt(x.s, 'count')}</td></tr>`).join('')}</tbody></table>`;
      BA.lastCatchment = { rad, sums };
    }

    $('ind').addEventListener('change', () => { $('bd').innerHTML = ''; drawChoro(); });
    $('bd').addEventListener('change', drawChoro);
    $('laf').addEventListener('change', drawChoro);
    let t; $('rad').addEventListener('input', () => { clearTimeout(t); t = setTimeout(updateCatch, 120); });
    document.querySelectorAll('.ba-panel input[type=checkbox]').forEach((c) => c.addEventListener('change', () => { syncLayers(); if (c.id === 'l-prov') drawChoro(); }));
    await syncLayers();
    await drawChoro();
  });

  function cb(id, label, on) { return `<div class="govuk-checkboxes__item"><input class="govuk-checkboxes__input" id="${id}" type="checkbox" ${on ? 'checked' : ''}><label class="govuk-label govuk-checkboxes__label" for="${id}">${label}</label></div>`; }
  function groupOptions(inds, want) {
    const groups = {};
    inds.forEach((i) => { const g = BA.cohortsOf(i)[0]; (groups[g] = groups[g] || []).push(i); });
    const order = ['25+ inactive', '18-24', '16-19', 'context'];
    return Object.keys(groups).sort((a, b) => order.indexOf(a) - order.indexOf(b)).map((g) => `<optgroup label="${esc((BA.COHORTS[g] || { label: g }).label)}">${groups[g].map((i) => `<option value="${i.id}" ${i.id === want ? 'selected' : ''}>${esc(i.label)}</option>`).join('')}</optgroup>`).join('');
  }
})();
