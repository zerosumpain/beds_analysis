"""Census 2021 barrier-to-work measures for the three Bedfordshire UAs (LSOA21 + LA).

Dataset written (site/data/census_barriers.json):
  census_barriers  TS045 car/van availability, TS029 proficiency in English,
                   TS003 household composition, TS037 general health (Nomis API)

These complement census_lsoa (inactivity by reason, unemployment, qualifications,
unpaid care, disability), which this file deliberately does not duplicate.

LSOA rows are filtered to the LSOAs in site/data/geo/lookup_lsoa.json. LA, East of
England and England rows are the published Nomis figures; BEDS sums the three LA
counts and recomputes percentages from the summed numerators/denominators.

Dataset ids and category codes were looked up from
/api/v01/dataset/def.sdmx.json?search=*TS045* (etc.) and
/api/v01/dataset/NM_x_1/<dimension>.def.sdmx.json.
"""
from common import COMPARATORS, LAS, save
from fetch_small_area import BEDS, geo_label, load_lsoas, nomis, num, pct, row

# table key -> (Nomis dataset, category dimension, table label)
TABLES = {
    "car": ("NM_2063_1", "C2021_CARS_5", "TS045 Car or van availability"),
    "eng": ("NM_2048_1", "C2021_ENGPRF_6", "TS029 Proficiency in English"),
    "hh": ("NM_2023_1", "C2021_HHCOMP_15", "TS003 Household composition"),
    "health": ("NM_2055_1", "C2021_HEALTH_6", "TS037 General health"),
}
# stem, table, numerator codes, denominator codes, label, cohort, denominator label, extra note
INDS = [
    ("hh_nocar", "car", ["1"], ["0"], "Households with no car or van", "context, 25+ inactive",
     "all households", "TS045 category 1 'No cars or vans in household'."),
    ("eng_poor", "eng", ["4", "5"], ["0"], "Cannot speak English well or at all",
     "25+ inactive, 18-24", "usual residents aged 3+",
     "TS029 categories 4 'Cannot speak English well' + 5 'Cannot speak English' (main "
     "language not English; self/householder-reported)."),
    ("lone_parent_dep", "hh", ["10"], ["0"], "Lone-parent households with dependent children",
     "25+ inactive", "all households",
     "TS003 category 10 'Single family household: Lone parent family: With dependent "
     "children' (excludes lone parents living in multi-family/other households)."),
    ("bad_health", "health", ["4", "5"], ["0"], "General health bad or very bad",
     "25+ inactive", "all usual residents",
     "TS037 categories 4 'Bad health' + 5 'Very bad health' (all ages; not age-standardised)."),
]


def census_barriers(lsoas, urls):
    period = "Census 2021"
    geos_l = sorted(lsoas)
    geos_a = list(LAS) + list(COMPARATORS)
    data = {}  # table -> geography code -> category -> value
    for key, (ds, dim, _) in TABLES.items():
        params = {"measures": "20100", "select": f"geography_code,{dim},obs_value"}
        recs = nomis(ds, geos_l, params, f"cb_{key}_lsoa", urls)
        recs += nomis(ds, geos_a, params, f"cb_{key}_la", urls)
        t = data.setdefault(key, {})
        for r in recs:
            t.setdefault(r["GEOGRAPHY_CODE"], {})[r[dim]] = num(r["OBS_VALUE"])
        missing = [g for g in geos_l + geos_a if g not in t]
        assert not missing, f"{ds}: no data for {missing[:5]}"

    rows, indicators = [], []
    for stem, tab, ncodes, dcodes, label, cohort, denl, note in INDS:
        idn, idp = f"cb_{stem}", f"cb_{stem}_pct"
        indicators.append(dict(id=idn, label=f"{label} (count)", unit="count", cohort=cohort,
                               polarity="higher_is_worse",
                               description=f"Census 2021 count: {label.lower()}. {note}"))
        indicators.append(dict(id=idp, label=f"{label} (%)", unit="percent", cohort=cohort,
                               polarity="higher_is_worse",
                               description=f"{label} as % of {denl}. {note}"))
        beds_n = beds_d = 0
        for g in geos_l + geos_a:
            cells = data[tab][g]
            n = sum(cells[c] for c in ncodes)
            d = sum(cells[c] for c in dcodes)
            geo = geo_label(g, lsoas)
            rows.append(row(geo, idn, n, period))
            rows.append(row(geo, idp, pct(n, d), period, num=n, den=d))
            if g in LAS:
                beds_n += n
                beds_d += d
        rows.append(row(BEDS, idn, beds_n, period))
        rows.append(row(BEDS, idp, pct(beds_n, beds_d), period, num=beds_n, den=beds_d))

    meta = {
        "title": "Census 2021 barriers to work: no car, English proficiency, lone parents, "
                 "bad health",
        "publisher": "Office for National Statistics (via Nomis)",
        "source_url": "https://www.nomisweb.co.uk/sources/census_2021_ts",
        "api_url": list(urls),
        "geography": "LSOA21, LA, region, England, county",
        "cohort": "18-24, 25+ inactive, context",
        "period": period,
        "latest_period": "Census 2021 (21 March 2021)",
        "frequency": "Decennial",
        "next_update": "Census 2031 (results c. 2032-33)",
        "access": "API",
        "quality": ("Accredited official statistics (Census 2021, ~97% person response, estimates "
                    "adjusted for non-response). LA, region and England rows are the published "
                    "LA-level figures; BEDS sums the three LA counts and recomputes %."),
        "limitations": (
            "Census day 21 March 2021 fell in the third COVID-19 lockdown, which may have "
            "affected self-reported health and household arrangements (e.g. students at home). "
            "Cell-key perturbation adds small noise to every cell, so LSOA counts do not sum "
            "exactly to LA totals and small counts (<10, common for 'cannot speak English' and "
            "lone-parent cells) are unreliable. Car/van availability counts vehicles available "
            "to the household, not driving licences or individual access, and is a household "
            "(not person) measure. English proficiency is self- or householder-reported and only "
            "asked of people whose main language is not English. General health is not "
            "age-standardised, so older areas score worse (ONS TS037ASP gives age-standardised "
            "LA figures). Lone-parent count excludes lone parents in multi-family households. "
            "Measures are five years old and Luton's population in particular has grown since."),
        "indicators": indicators,
        "tables": [f"{v[2]} ({v[0]})" for v in TABLES.values()],
    }
    return meta, rows


def main():
    lsoas = load_lsoas()
    assert len(lsoas) > 400, f"only {len(lsoas)} LSOAs"
    print(f"{len(lsoas)} LSOAs in scope")
    meta, rows = census_barriers(lsoas, [])
    save("census_barriers", meta, rows)

    print("\nSummary (% of base)")
    get = {(r["code"], r["indicator"]): r["value"] for r in rows}
    stems = [s[0] for s in INDS]
    print(f"  {'area':24s} " + " ".join(f"{s:>16s}" for s in stems))
    for c, nm in list(LAS.items()) + [("BEDS", BEDS["name"])] + list(COMPARATORS.items()):
        print(f"  {nm:24s} " + " ".join(f"{get[(c, f'cb_{s}_pct')]:>16}" for s in stems))
    for s in stems:
        top = sorted((r for r in rows if r["level"] == "LSOA" and r["indicator"] == f"cb_{s}_pct"),
                     key=lambda r: -r["value"])[:3]
        print(f"  top LSOAs {s}: " + ", ".join(f"{r['name']} {r['value']}%" for r in top))


if __name__ == "__main__":
    main()
