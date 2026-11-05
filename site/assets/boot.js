/* Wiring: headline tiles and business-case data sources, then start the router. */
(function () {
  'use strict';
  const BA = window.BA;
  const v = async (id, code, bd) => { const r = await BA.value(id, code || 'BEDS', bd === undefined ? null : bd); return r ? r.value : null; };
  const sum = async (ids, bd) => { let t = 0; for (const id of ids) { const x = await v(id, 'BEDS', bd); if (x == null) return null; t += x; } return t; };
  const atPeriod = async (id, period) => { const rows = await BA.rowsFor(id); const r = rows.find((x) => x.code === 'BEDS' && String(x.period) === String(period)); return r ? r.value : null; };
  const INACT_ACTIVE = ['census_inact_home_family', 'census_inact_lt_sick', 'census_inact_other'];
  // Headline tiles. ind = indicator id(s), first available wins; fn = custom.
  BA.TILES = [
    { label: 'Aged 16 to 19', ind: ['pop_mye_16_19', 'popsa_16_19'], code: 'BEDS', sub: 'Residents, ONS mid-year estimate', cohorts: ['16-19'] },
    { label: 'Aged 16 to 19 at opening (2031)', fn: async () => ({ v: await atPeriod('snpp_16_19', 2031), id: 'snpp_16_19', period: '2022-based projection' }), cohorts: ['16-19'] },
    { label: '16-17s NEET or activity not known', fn: async () => { let t = 0; for (const c of Object.keys(BA.LAS)) { const r = await BA.value('dfe_neet_n_neet_nk', c, 'age 16-17'); if (!r) return null; t += r.value; } return { v: t, id: 'dfe_neet_n_neet_nk' }; }, cohorts: ['16-19'], tone: 'warn' },
    { label: 'Aged 18 to 24', ind: ['pop_mye_18_24', 'popsa_18_24'], code: 'BEDS', sub: 'Residents, ONS mid-year estimate', cohorts: ['18-24'] },
    { label: 'Claimants aged 18 to 24', ind: ['claimant_count_18_24', 'cc_16_24'], code: 'BEDS', sub: 'Claimant count', cohorts: ['18-24'], tone: 'warn' },
    { label: 'Inactive 25-64: sick, caring, home or other', fn: async () => ({ v: await sum(INACT_ACTIVE, 'age 25-64'), id: 'census_inact_lt_sick', period: 'Census 2021' }), cohorts: ['25+ inactive'], tone: 'warn' },
    { label: 'Inactive 25-64: long-term sick or disabled', fn: async () => ({ v: await v('census_inact_lt_sick', 'BEDS', 'age 25-64'), id: 'census_inact_lt_sick', period: 'Census 2021' }), cohorts: ['25+ inactive'] },
    { label: 'Luton inactivity rate, 16-64', fn: async () => { const r = await BA.value('aps_inact_rate_16_64', 'E06000032'); return r && { v: r.value, id: 'aps_inact_rate_16_64', period: r.period }; }, unit: 'percent', sub: 'APS; England 20.5%', cohorts: ['25+ inactive'], tone: 'bad' },
    { label: 'Neighbourhoods in England\'s most deprived 10%', ind: ['imd25_imd_lsoas_top10'], code: 'BEDS', sub: 'IMD 2025', cohorts: ['context'] },
    { label: 'Hospitality and food jobs', ind: ['bres_emp_accom_food'], code: 'BEDS', sub: 'BRES employees', cohorts: ['context'] },
  ];
  BA.ENGINE_SOURCES = {
    leavers: async () => ({ value: await v('pop_single_age', 'BEDS', 'age 16'), note: 'ONS mid-2025: residents aged 16', dataset: 'pop_mye' }),
    neet: async () => { let t = 0; for (const c of Object.keys(BA.LAS)) { const r = await BA.value('dfe_neet_n_neet_nk', c, 'age 16-17'); if (!r) return null; t += r.value; } return { value: t, note: 'DfE: NEET or not known, 16-17', dataset: 'dfe_neet' }; },
    cc1824: async () => ({ value: await v('claimant_count_18_24'), note: 'Claimant count, latest month', dataset: 'claimant' }),
    inact1824: async () => ({ value: await sum(INACT_ACTIVE, 'age 18-24'), note: 'Census 2021: inactive 18-24, not students', dataset: 'census_age_activity' }),
    cc25: async () => { const a = await v('claimant_count_25_49'), b = await v('claimant_count_50_plus'); return { value: a != null && b != null ? a + b : null, note: 'Claimant count 25+, latest month', dataset: 'claimant' }; },
    inact25: async () => ({ value: await sum(INACT_ACTIVE, 'age 25-64'), note: 'Census 2021: inactive 25-64, sick/carer/home/other', dataset: 'census_age_activity' }),
  };
  // Census 2021 commuting: inflows into each Bedfordshire UA from other authorities.
  BA.odLines = (rows) => rows.filter((r) => r.indicator === 'od_inflow_by_residence' && BA.LAS[r.code] && r.attrs && !r.attrs.same_la && r.attrs.origin_lat != null && r.value > 0)
    .map((r) => ({ from: [r.attrs.origin_lat, r.attrs.origin_lon], to: [r.attrs.dest_lat, r.attrs.dest_lon], n: r.value, label: `${r.attrs.origin_name} → ${r.attrs.dest_name}` }));
  BA.ENGINE_DATASETS = ['pop_mye', 'dfe_neet', 'claimant', 'census_age_activity', 'pop_snpp', 'ashe_res', 'travel_lsoa', 'census_barriers', 'pop_lsoa', 'claimant_lsoa', 'census_lsoa'];

  BA.init().then(() => {
    const stamp = document.getElementById('build-stamp');
    const latest = BA.catalogue.map((m) => m.retrieved_at).sort().pop();
    if (stamp && latest) stamp.textContent = 'Data last refreshed ' + latest + '.';
    window.addEventListener('hashchange', BA.go);
    BA.go();
  }).catch((e) => { document.getElementById('app').innerHTML = '<p class="govuk-body">Could not load the data catalogue: ' + BA.esc(e.message) + '</p>'; });
})();
