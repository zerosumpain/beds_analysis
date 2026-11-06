/* Core: data loading, indicator index, formatting, charts, routing. */
(function () {
  'use strict';
  const BA = (window.BA = {});

  BA.LAS = { E06000055: 'Bedford', E06000056: 'Central Bedfordshire', E06000032: 'Luton' };
  BA.GEO_ORDER = ['E06000055', 'E06000056', 'E06000032', 'BEDS', 'E12000006', 'E92000001'];
  BA.GEO_NAMES = Object.assign({}, BA.LAS, { BEDS: 'Bedfordshire', E12000006: 'East of England', E92000001: 'England' });
  // Government Analysis Function categorical palette; England is deliberately neutral grey.
  BA.GEO_COLORS = { E06000055: '#12436D', E06000056: '#28A197', E06000032: '#801650', BEDS: '#F46A25', E12000006: '#A285D1', E92000001: '#3D3D3D' };
  BA.COHORTS = {
    '16-19': { label: '16 to 19 year olds', slug: '16-19' },
    '18-24': { label: '18 to 24 year olds', slug: '18-24' },
    '25+ inactive': { label: 'Economically inactive adults aged 25+', slug: '25-inactive' },
    context: { label: 'Context: economy, deprivation and demand', slug: 'context' },
  };
  BA.SITE = { name: 'Proposed resort site, Kempston Hardwick', lat: 52.0870, lon: -0.5160 };

  const cache = {};
  BA.json = function (path) {
    if (!cache[path]) cache[path] = fetch(path + (window.BA_VERSION && window.BA_VERSION !== '__V__' ? (path.includes('?') ? '&' : '?') + 'v=' + window.BA_VERSION : '')).then((r) => { if (!r.ok) throw new Error(path + ' ' + r.status); return r.json(); });
    return cache[path];
  };
  // A provider (e.g. a live API the visitor has connected) replaces the published file for that dataset.
  BA.providers = {};
  BA.dataset = function (id) {
    if (!BA.providers[id]) return BA.json('data/' + id + '.json');
    const k = 'live:' + id;
    if (!cache[k]) cache[k] = BA.providers[id]().catch((e) => { delete cache[k]; throw e; });
    return cache[k];
  };
  BA.forget = (id) => { delete cache['live:' + id]; delete cache['data/' + id + '.json']; };
  BA.tryJson = (path) => BA.json(path).catch(() => null);

  BA.init = async function () {
    const [cat, sources, assessment, unitCosts, benchmarks] = await Promise.all([
      BA.tryJson('data/catalogue.json'), BA.tryJson('data/research_sources.json'), BA.tryJson('data/research_assessment.json'),
      BA.tryJson('data/research_unit_costs.json'), BA.tryJson('data/research_local_hire_benchmarks.json'),
    ]);
    BA.lsoaLookup = (await BA.tryJson('data/geo/lookup_lsoa.json')) || {};
    BA.unitCosts = unitCosts; BA.hireBenchmarks = benchmarks;
    BA.unitCost = (id) => (BA.unitCosts && (BA.unitCosts.items || []).find((x) => x.id === id && typeof x.value === 'number')) || null;
    BA.catalogue = (cat || []).filter((m) => m.id !== 'geo_boundaries' || true);
    BA.sources = sources || [];
    BA.assessment = assessment || {};
    if (BA.assessment.project && BA.assessment.project.lat) {
      BA.SITE = { name: BA.assessment.project.location_name || BA.SITE.name, lat: +BA.assessment.project.lat, lon: +BA.assessment.project.lon };
    }
    BA.indicators = {};
    BA.catalogue.forEach((m) => (m.indicators || []).forEach((ind) => {
      BA.indicators[ind.id] = Object.assign({ dataset: m.id, datasetTitle: m.title, levels: m.geography || '' }, ind);
    }));
  };
  BA.has = (datasetId) => BA.catalogue.some((m) => m.id === datasetId);
  BA.meta = (datasetId) => BA.catalogue.find((m) => m.id === datasetId);
  BA.cohortsOf = (ind) => String(ind.cohort || 'context').split(',').map((s) => s.trim()).filter(Boolean);

  /* ---------- row helpers ---------- */
  BA.latestPeriod = function (rows) {
    const ps = [...new Set(rows.map((r) => r.period).filter(Boolean))];
    if (!ps.length) return null;
    return ps.sort(BA.periodCmp).pop();
  };
  // Sort periods chronologically on the first 4-digit year, then month order, then string.
  const MONTHS = 'jan feb mar apr may jun jul aug sep oct nov dec'.split(' ');
  BA.periodKey = function (p) {
    p = String(p || '');
    const years = p.match(/(19|20)\d\d/g) || ['0'];
    const y = +years[years.length - 1];
    const lower = p.toLowerCase();
    let m = 0; MONTHS.forEach((mm, i) => { const k = lower.lastIndexOf(mm); if (k >= 0 && k > lower.length - 12) m = Math.max(m, i + 1); });
    const ay = p.match(/(20\d\d)\/(\d\d)/); // academic year 2023/24 -> 2024
    return ay ? +ay[1] * 100 + 13 : y * 100 + m;
  };
  BA.periodCmp = (a, b) => BA.periodKey(a) - BA.periodKey(b) || String(a).localeCompare(String(b));
  BA.rowsFor = async function (indId, opts) {
    opts = opts || {};
    const ind = BA.indicators[indId];
    if (!ind) return [];
    const ds = await BA.dataset(ind.dataset);
    return ds.rows.filter((r) => r.indicator === indId &&
      (opts.level ? (Array.isArray(opts.level) ? opts.level.includes(r.level) : r.level === opts.level) : true) &&
      (opts.breakdown === undefined ? true : (r.breakdown || null) === opts.breakdown));
  };
  // latest value for a geo code (breakdown null)
  BA.value = async function (indId, code, breakdown) {
    const rows = (await BA.rowsFor(indId)).filter((r) => r.code === code && (r.breakdown || null) === (breakdown === undefined ? null : breakdown));
    if (!rows.length) return null;
    const lp = BA.latestPeriod(rows);
    const r = rows.find((x) => x.period === lp) || rows[0];
    return r;
  };
  BA.sumLAs = async function (indId, breakdown) {
    const vals = await Promise.all(Object.keys(BA.LAS).map((c) => BA.value(indId, c, breakdown)));
    if (vals.some((v) => !v || v.value == null)) {
      const beds = await BA.value(indId, 'BEDS', breakdown);
      return beds ? beds.value : null;
    }
    return vals.reduce((s, v) => s + v.value, 0);
  };

  /* ---------- formatting ---------- */
  const nf0 = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 });
  const nf1 = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 1 });
  BA.fmt = function (v, unit) {
    if (v == null || Number.isNaN(v)) return '–';
    switch (unit) {
      case 'percent': return nf1.format(v) + '%';
      case 'gbp': return '£' + nf0.format(v);
      case 'minutes': return nf0.format(v) + ' min';
      case 'rate': case 'ratio': case 'score': return nf1.format(v);
      default: return Math.abs(v) >= 100 ? nf0.format(v) : nf1.format(v);
    }
  };
  BA.big = function (v) {
    if (v == null) return '–';
    if (Math.abs(v) >= 1e6) return (v / 1e6).toFixed(1) + 'm';
    if (Math.abs(v) >= 1e4) return nf0.format(Math.round(v / 100) * 100);
    return nf0.format(v);
  };
  BA.money = function (v) {
    if (v == null || !isFinite(v)) return '–';
    if (Math.abs(v) >= 1e9) return '£' + (v / 1e9).toFixed(2) + 'bn';
    if (Math.abs(v) >= 1e6) return '£' + (v / 1e6).toFixed(1) + 'm';
    if (Math.abs(v) >= 1e3) return '£' + nf0.format(Math.round(v / 1e3)) + 'k';
    return '£' + nf0.format(v);
  };
  BA.esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  BA.link = (url, text) => url ? `<a class="govuk-link" href="${BA.esc(url)}" rel="noopener" target="_blank">${BA.esc(text || url)}</a>` : BA.esc(text || '');
  BA.status = function (s) {
    const k = String(s || '').toLowerCase();
    const cls = k.startsWith('yes') || k === 'met' ? 'yes' : k.startsWith('part') ? 'partly' : k.startsWith('no') || k === 'gap' ? 'no' : 'na';
    const label = { yes: 'Met', partly: 'Partly', no: 'Not met', na: s || 'n/a' }[cls];
    return `<span class="ba-status ba-status--${cls}">${BA.esc(label)}</span>`;
  };
  // How old a period is, as a tag: amber when the figure is 3+ years old (e.g. Census 2021).
  BA.periodYear = function (p) { const ys = String(p || '').match(/(19|20)\d\d/g); return ys ? +ys[ys.length - 1] : null; };
  BA.ageTag = function (p) {
    const y = BA.periodYear(p); if (!y) return '';
    const age = new Date().getFullYear() - y;
    if (age < 3) return '';
    return `<strong class="govuk-tag govuk-tag--${age >= 4 ? 'orange' : 'yellow'} ba-age" title="Latest period ${BA.esc(p)}">${age} years old</strong>`;
  };
  // Plain accessible table for any set of rows (the alternative to each chart).
  BA.rowsTable = function (rows, unit, opts) {
    opts = opts || {};
    const hasCI = rows.some((r) => r.ci != null), hasBd = rows.some((r) => r.breakdown);
    return `<div class="ba-table-wrap govuk-!-margin-bottom-0"><table class="govuk-table ba-mini">${opts.caption ? `<caption class="govuk-table__caption govuk-table__caption--s">${BA.esc(opts.caption)}</caption>` : ''}<thead class="govuk-table__head"><tr class="govuk-table__row"><th class="govuk-table__header" scope="col">Area</th>${hasBd ? '<th class="govuk-table__header" scope="col">Breakdown</th>' : ''}<th class="govuk-table__header" scope="col">Period</th><th class="govuk-table__header govuk-table__header--numeric" scope="col">Value</th>${hasCI ? '<th class="govuk-table__header govuk-table__header--numeric" scope="col">± 95% CI</th>' : ''}</tr></thead><tbody class="govuk-table__body">${rows.map((r) => `<tr class="govuk-table__row"><th class="govuk-table__header" scope="row">${BA.esc(BA.GEO_NAMES[r.code] || r.name)}</th>${hasBd ? `<td class="govuk-table__cell">${BA.esc(r.breakdown || '')}</td>` : ''}<td class="govuk-table__cell">${BA.esc(r.period || '')}</td><td class="govuk-table__cell govuk-table__cell--numeric">${r.suppressed ? 'suppressed' : BA.fmt(r.value, unit)}</td>${hasCI ? `<td class="govuk-table__cell govuk-table__cell--numeric">${r.ci != null ? BA.fmt(r.ci, unit) : ''}</td>` : ''}</tr>`).join('')}</tbody></table></div>`;
  };
  BA.el = function (html) { const t = document.createElement('template'); t.innerHTML = html.trim(); return t.content.firstElementChild; };

  /* ---------- CSV download ---------- */
  BA.downloadCSV = function (filename, rows) {
    if (!rows.length) return;
    const cols = [...new Set(rows.flatMap((r) => Object.keys(r)))].filter((c) => typeof rows[0][c] !== 'object' || rows[0][c] === null);
    const q = (v) => { v = v == null ? '' : typeof v === 'object' ? JSON.stringify(v) : String(v); return /[",\n]/.test(v) ? '"' + v.replace(/"/g, '""') + '"' : v; };
    const csv = [cols.join(','), ...rows.map((r) => cols.map((c) => q(r[c])).join(','))].join('\n');
    const a = document.createElement('a');
    a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
    a.download = filename; a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  };

  /* ---------- charts (Chart.js) ---------- */
  Chart.defaults.font.family = 'arial, sans-serif';
  Chart.defaults.font.size = 13;
  Chart.defaults.color = '#505a5f';
  Chart.defaults.plugins.legend.display = false;
  Chart.defaults.animation.duration = 250;
  const charts = new Set();
  BA.destroyCharts = () => { charts.forEach((c) => c.destroy()); charts.clear(); };
  BA.chart = function (canvas, cfg) { const c = new Chart(canvas, cfg); charts.add(c); return c; };
  const grid = { color: '#e5e6e7', drawTicks: false };

  // Horizontal bars, one per geography; CI shown in tooltip and as whisker.
  BA.barGeo = function (canvas, rows, unit) {
    const ordered = BA.GEO_ORDER.map((c) => rows.find((r) => r.code === c)).filter(Boolean);
    const whisker = {
      id: 'whisker',
      afterDatasetsDraw(chart) {
        const { ctx } = chart; const meta = chart.getDatasetMeta(0);
        ctx.save(); ctx.strokeStyle = '#0b0c0c'; ctx.lineWidth = 1.5;
        ordered.forEach((r, i) => {
          if (r.ci == null || r.value == null) return;
          const x0 = chart.scales.x.getPixelForValue(r.value - r.ci), x1 = chart.scales.x.getPixelForValue(r.value + r.ci);
          const y = meta.data[i].y;
          ctx.beginPath(); ctx.moveTo(x0, y); ctx.lineTo(x1, y); ctx.moveTo(x0, y - 5); ctx.lineTo(x0, y + 5); ctx.moveTo(x1, y - 5); ctx.lineTo(x1, y + 5); ctx.stroke();
        });
        ctx.restore();
      },
    };
    const labelPlugin = {
      id: 'vals',
      afterDatasetsDraw(chart) {
        const { ctx } = chart; const meta = chart.getDatasetMeta(0);
        ctx.save(); ctx.font = '13px arial'; ctx.fillStyle = '#0b0c0c'; ctx.textBaseline = 'middle';
        ordered.forEach((r, i) => {
          const bar = meta.data[i]; if (!bar) return;
          const txt = r.suppressed ? 'suppressed' : BA.fmt(r.value, unit);
          const x = r.value == null ? chart.scales.x.getPixelForValue(0) + 4 : bar.x + 6 + (r.ci ? Math.max(0, chart.scales.x.getPixelForValue(r.value + r.ci) - bar.x) : 0);
          ctx.fillText(txt, Math.min(x, chart.chartArea.right - ctx.measureText(txt).width), bar.y);
        });
        ctx.restore();
      },
    };
    const max = Math.max(...ordered.map((r) => (r.value || 0) + (r.ci || 0)));
    return BA.chart(canvas, {
      type: 'bar',
      data: {
        labels: ordered.map((r) => BA.GEO_NAMES[r.code] || r.name),
        datasets: [{ data: ordered.map((r) => r.value), backgroundColor: ordered.map((r) => BA.GEO_COLORS[r.code] || '#1d70b8'), borderRadius: 4, borderSkipped: 'start', barPercentage: 0.7, categoryPercentage: 0.9 }],
      },
      options: {
        indexAxis: 'y', maintainAspectRatio: false, layout: { padding: { right: 8 } },
        scales: { x: { beginAtZero: true, suggestedMax: unit === 'percent' ? Math.min(100, max * 1.18) : max * 1.18, max: unit === 'percent' && max * 1.18 > 85 && max <= 100 ? 100 : undefined, grid, border: { display: false }, ticks: { callback: (v) => BA.fmt(v, unit) } }, y: { grid: { display: false }, border: { display: false }, ticks: { color: '#0b0c0c' } } },
        plugins: { tooltip: { callbacks: { label: (c) => { const r = ordered[c.dataIndex]; return `${BA.fmt(r.value, unit)}${r.ci ? ' ± ' + BA.fmt(r.ci, unit) + ' (95% CI)' : ''}${r.num != null ? ' · ' + BA.fmt(r.num, 'count') + ' of ' + BA.fmt(r.den, 'count') : ''} · ${r.period}`; } } } },
      },
      plugins: [whisker, labelPlugin],
    });
  };

  // Time series lines per geography.
  BA.lineGeo = function (canvas, rows, unit) {
    const periods = [...new Set(rows.map((r) => r.period))].sort(BA.periodCmp);
    const codes = BA.GEO_ORDER.filter((c) => rows.some((r) => r.code === c));
    return BA.chart(canvas, {
      type: 'line',
      data: {
        labels: periods,
        datasets: codes.map((c) => ({
          label: BA.GEO_NAMES[c], borderColor: BA.GEO_COLORS[c], backgroundColor: BA.GEO_COLORS[c], borderWidth: 2, pointRadius: periods.length > 24 ? 0 : 3, pointHoverRadius: 5,
          borderDash: c === 'E92000001' || c === 'E12000006' ? [5, 4] : [], spanGaps: true,
          data: periods.map((p) => { const r = rows.find((x) => x.code === c && x.period === p); return r ? r.value : null; }),
        })),
      },
      options: {
        maintainAspectRatio: false, interaction: { mode: 'index', intersect: false },
        scales: { y: { grid, border: { display: false }, ticks: { callback: (v) => BA.fmt(v, unit) } }, x: { grid: { display: false }, ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 6 } } },
        plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${BA.fmt(c.parsed.y, unit)}` } } },
      },
    });
  };

  // Grouped bars: categories = breakdown values, series = geos.
  BA.barBreakdown = function (canvas, rows, unit, codes) {
    codes = codes || BA.GEO_ORDER.filter((c) => rows.some((r) => r.code === c));
    const cats = [...new Set(rows.map((r) => r.breakdown))].slice(0, 14);
    return BA.chart(canvas, {
      type: 'bar',
      data: {
        labels: cats,
        datasets: codes.map((c) => ({ label: BA.GEO_NAMES[c], backgroundColor: BA.GEO_COLORS[c], borderRadius: 3, borderSkipped: 'start', data: cats.map((k) => { const r = rows.find((x) => x.code === c && x.breakdown === k); return r ? r.value : null; }) })),
      },
      options: {
        maintainAspectRatio: false, indexAxis: cats.length > 5 ? 'y' : 'x',
        scales: { x: { grid: cats.length > 5 ? grid : { display: false }, ticks: cats.length > 5 ? { callback: (v) => BA.fmt(v, unit) } : { maxRotation: 0, autoSkip: false, font: { size: 11 } } }, y: { grid: cats.length > 5 ? { display: false } : grid, ticks: cats.length > 5 ? { font: { size: 11 } } : { callback: (v) => BA.fmt(v, unit) } } },
        plugins: { tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${BA.fmt(c.raw, unit)}` } } },
      },
    });
  };
  BA.legendHTML = (codes) => '<ul class="ba-legend">' + codes.map((c) => `<li><span class="ba-sw" style="background:${BA.GEO_COLORS[c]}"></span>${BA.esc(BA.GEO_NAMES[c])}</li>`).join('') + '</ul>';

  /* ---------- router ---------- */
  BA.routes = [];
  BA.route = (re, fn) => BA.routes.push([re, fn]);
  BA.go = async function () {
    const hash = location.hash.replace(/^#/, '') || '/';
    const [path, qs] = hash.split('?');
    BA.query = new URLSearchParams(qs || '');
    BA.destroyCharts();
    if (BA.onLeave) { try { BA.onLeave(); } catch (e) { /* ignore */ } BA.onLeave = null; }
    const app = document.getElementById('app');
    document.querySelectorAll('#nav a').forEach((a) => {
      const href = a.getAttribute('href').slice(1);
      const active = href === '/' ? path === '/' : path.startsWith(href);
      a.parentElement.classList.toggle('govuk-service-navigation__item--active', active);
      if (active) a.setAttribute('aria-current', 'page'); else a.removeAttribute('aria-current');
    });
    for (const [re, fn] of BA.routes) {
      const m = path.match(re);
      if (m) {
        try { await fn(app, ...m.slice(1)); } catch (e) { console.error(e); app.innerHTML = `<div class="govuk-error-summary"><h2 class="govuk-error-summary__title">Something went wrong</h2><p class="govuk-body">${BA.esc(e.message)}</p></div>`; }
        if (!BA.keepScroll) window.scrollTo(0, 0);
        BA.keepScroll = false;
        return;
      }
    }
    app.innerHTML = '<h1 class="govuk-heading-xl">Page not found</h1><p class="govuk-body"><a class="govuk-link" href="#/">Go to the summary</a></p>';
  };
})();
