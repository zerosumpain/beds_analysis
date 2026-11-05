"""LSOA-level (2021 LSOAs) evidence for the three Bedfordshire UAs.

Datasets written (site/data/<id>.json):
  census_lsoa  Census 2021 TS066/TS067/TS039/TS038/TS007 via the Nomis API
  pop_lsoa     ONS small-area mid-year population estimates (Nomis NM_2014_1)
  claimant_lsoa  Claimant count by LSOA21, latest month (Nomis NM_162_1)
  imd2025      English Indices of Deprivation 2025 (MHCLG File 7 CSV)

LSOA rows are filtered to the LSOAs in site/data/geo/lookup_lsoa.json (built by
fetch_geo.py) or, failing that, the IMD file's LA column. LA rows come from the
source at LA level where it publishes them; BEDS rows sum the three LA counts
and percentages are recomputed from summed numerators/denominators.
"""
import csv
import io
import json
import urllib.parse

from common import COMPARATORS, LAS, OUT, fetch, save

NOMIS = "https://www.nomisweb.co.uk/api/v01/dataset"
IMD_CSV = ("https://assets.publishing.service.gov.uk/media/691ded56d140bbbaa59a2a7d/"
           "File_7_IoD2025_All_Ranks_Scores_Deciles_Population_Denominators.csv")
IMD_PAGE = "https://www.gov.uk/government/statistics/english-indices-of-deprivation-2025"
BEDS = {"code": "BEDS", "name": "Bedfordshire (3 UAs)", "level": "county"}
CHUNK = 140


# --------------------------------------------------------------------------
# helpers
def nomis_url(ds, params):
    return f"{NOMIS}/{ds}.data.csv?" + urllib.parse.urlencode(params, safe=",")


def nomis(ds, geos, params, tag, urls):
    """Fetch a Nomis CSV for a list of geography codes (chunked); return dict rows."""
    out = []
    for i in range(0, len(geos), CHUNK):
        p = dict(params, geography=",".join(geos[i:i + CHUNK]))
        url = nomis_url(ds, p)
        urls.append(url if len(geos) <= CHUNK else
                    nomis_url(ds, dict(params, geography=f"<{len(geos)} LSOA21 codes, {CHUNK}/request>")))
        text = fetch(url, f"nomis_{tag}_{i}.csv").decode("utf-8-sig")
        out += list(csv.DictReader(io.StringIO(text)))
    # one placeholder URL per dataset is enough for lineage
    seen, ded = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            ded.append(u)
    urls[:] = ded
    return out


def num(v):
    if v in (None, ""):
        return None
    return float(v) if "." in v else int(v)


def pct(n, d, dp=1):
    return round(100 * n / d, dp) if (n is not None and d) else None


def load_lsoas():
    """{lsoa_code: {name, la, la_name, ...}} for the three LAs."""
    p = OUT / "geo" / "lookup_lsoa.json"
    if p.exists():
        return json.loads(p.read_text())
    rows = csv.reader(io.StringIO(fetch(IMD_CSV, "imd2025_file7.csv").decode("utf-8-sig")))
    next(rows)
    return {r[0]: {"name": r[1], "la": r[2], "la_name": LAS[r[2]]} for r in rows if r[2] in LAS}


def geo_label(code, lsoas):
    if code in lsoas:
        return {"code": code, "name": lsoas[code]["name"], "level": "LSOA", "la": lsoas[code]["la"]}
    if code in LAS:
        return {"code": code, "name": LAS[code], "level": "LA"}
    if code == "E12000006":
        return {"code": code, "name": COMPARATORS[code], "level": "region"}
    if code == "E92000001":
        return {"code": code, "name": COMPARATORS[code], "level": "country"}
    raise KeyError(code)


def row(geo, ind, value, period, **kw):
    r = {"code": geo["code"], "name": geo["name"], "level": geo["level"],
         "indicator": ind, "value": value, "period": period}
    if geo.get("la"):
        r["la"] = geo["la"]
    for k, v in kw.items():
        if v is not None:
            r[k] = v
    if value is None:
        r["suppressed"] = True
    return r


# --------------------------------------------------------------------------
# 1. Census 2021
# Each spec: indicator stem -> (table key, numerator codes, denominator codes,
#            label, cohort, polarity, denominator label)
CENSUS_TABLES = {
    "ea": ("NM_2083_1", "C2021_EASTAT_20", "TS066 Economic activity status"),
    "hq": ("NM_2084_1", "C2021_HIQUAL_8", "TS067 Highest level of qualification"),
    "care": ("NM_2057_1", "C2021_CARER_7", "TS039 Provision of unpaid care"),
    "dis": ("NM_2056_1", "C2021_DISABILITY_5", "TS038 Disability"),
    "age": ("NM_2027_1", "C2021_AGE_102", "TS007 Age by single year"),
}
CENSUS_INDS = [
    # stem, table, numerator codes, denominator codes, label, cohort, polarity(count/pct), den label
    ("inactive", "ea", ["1011"], ["0"], "Economically inactive (16+)", "25+ inactive,context",
     "higher_is_worse", "usual residents aged 16+"),
    ("inactive_student", "ea", ["16"], ["0"], "Inactive: student", "16-19,18-24", "neutral",
     "usual residents aged 16+"),
    ("inactive_retired", "ea", ["15"], ["0"], "Inactive: retired", "context", "neutral",
     "usual residents aged 16+"),
    ("inactive_home", "ea", ["17"], ["0"], "Inactive: looking after home or family", "25+ inactive",
     "neutral", "usual residents aged 16+"),
    ("inactive_ltsick", "ea", ["18"], ["0"], "Inactive: long-term sick or disabled", "25+ inactive",
     "higher_is_worse", "usual residents aged 16+"),
    ("inactive_other", "ea", ["19"], ["0"], "Inactive: other reason", "25+ inactive",
     "higher_is_worse", "usual residents aged 16+"),
    ("inactive_non_student_non_retired", "ea", ["17", "18", "19"], ["0"],
     "Hidden-potential pool: inactive, not student or retired (LT sick + home/family + other)",
     "25+ inactive", "higher_is_worse", "usual residents aged 16+"),
    ("unemployed", "ea", ["7", "14"], ["0"], "Unemployed (incl. full-time students seeking work)",
     "18-24,25+ inactive,context", "higher_is_worse", "usual residents aged 16+"),
    ("unemp_rate", "ea", ["7", "14"], ["1001", "1006"],
     "Unemployment rate (unemployed / economically active incl. students)", "context",
     "higher_is_worse", "economically active residents aged 16+"),
    ("noqual", "hq", ["1"], ["0"], "No qualifications", "25+ inactive,context", "higher_is_worse",
     "usual residents aged 16+"),
    ("level3plus", "hq", ["5", "6"], ["0"], "Level 3+ highest qualification (L3 or L4+)", "context",
     "higher_is_better", "usual residents aged 16+"),
    ("level4plus", "hq", ["6"], ["0"], "Level 4+ highest qualification", "context",
     "higher_is_better", "usual residents aged 16+"),
    ("apprenticeship", "hq", ["4"], ["0"], "Apprenticeship as highest qualification", "context",
     "higher_is_better", "usual residents aged 16+"),
    ("care20plus", "care", ["102", "6"], ["0"], "Provides 20+ hours unpaid care a week",
     "25+ inactive", "higher_is_worse", "usual residents aged 5+"),
    ("disabled", "dis", ["1001"], ["0"], "Disabled under the Equality Act", "25+ inactive,context",
     "higher_is_worse", "all usual residents"),
]
CENSUS_AGE = [
    ("pop_16_19", ["1004"], "Census population aged 16-19", "16-19"),
    ("pop_18_24", ["19", "20", "1005"], "Census population aged 18-24", "18-24"),
]


def census(lsoas, urls):
    period = "Census 2021"
    geos_l = sorted(lsoas)
    geos_a = list(LAS) + list(COMPARATORS)
    data = {}  # table -> code -> cat -> value
    for key, (ds, dim, _) in CENSUS_TABLES.items():
        params = {"measures": "20100", "select": f"geography_code,{dim},obs_value"}
        recs = nomis(ds, geos_l, params, f"census_{key}_lsoa", urls)
        recs += nomis(ds, geos_a, params, f"census_{key}_la", urls)
        t = data.setdefault(key, {})
        for r in recs:
            t.setdefault(r["GEOGRAPHY_CODE"], {})[r[dim]] = num(r["OBS_VALUE"])

    rows, indicators = [], []
    all_geos = geos_l + geos_a
    for stem, tab, ncodes, dcodes, label, cohort, pol, denl in CENSUS_INDS:
        idn, idp = f"census_{stem}", f"census_{stem}_pct"
        if stem == "unemp_rate":
            indicators.append(dict(id=idp, label=label, unit="percent", cohort=cohort, polarity=pol,
                                   description=f"{label}; denominator: {denl}."))
        else:
            indicators.append(dict(id=idn, label=f"{label} (count)", unit="count", cohort=cohort,
                                   polarity=pol, description=f"Count of residents: {label.lower()}."))
            indicators.append(dict(id=idp, label=f"{label} (%)", unit="percent", cohort=cohort,
                                   polarity=pol,
                                   description=f"{label} as % of {denl}."))
        beds_n = beds_d = 0
        for g in all_geos:
            cells = data[tab].get(g)
            if cells is None:
                continue
            n = sum(cells[c] for c in ncodes)
            d = sum(cells[c] for c in dcodes)
            geo = geo_label(g, lsoas)
            if stem != "unemp_rate":
                rows.append(row(geo, idn, n, period))
            rows.append(row(geo, idp, pct(n, d), period, num=n, den=d))
            if g in LAS:
                beds_n += n
                beds_d += d
        if stem != "unemp_rate":
            rows.append(row(BEDS, idn, beds_n, period))
        rows.append(row(BEDS, idp, pct(beds_n, beds_d), period, num=beds_n, den=beds_d))

    for idn, codes, label, cohort in CENSUS_AGE:
        idn = f"census_{idn}"
        indicators.append(dict(id=idn, label=label, unit="count", cohort=cohort, polarity="neutral",
                               description=f"{label} (usual residents, TS007 single year of age)."))
        beds = 0
        for g in all_geos:
            cells = data["age"].get(g)
            if cells is None:
                continue
            n = sum(cells[c] for c in codes)
            rows.append(row(geo_label(g, lsoas), idn, n, period))
            if g in LAS:
                beds += n
        rows.append(row(BEDS, idn, beds, period))

    meta = {
        "title": "Census 2021 small-area labour-market, skills, care and disability profile",
        "publisher": "Office for National Statistics (via Nomis)",
        "source_url": "https://www.nomisweb.co.uk/sources/census_2021_ts",
        "api_url": list(urls),
        "geography": "LSOA21, LA, region, England",
        "cohort": "16-19, 18-24, 25+ inactive, context",
        "period": "Census 2021",
        "latest_period": "Census 2021 (21 March 2021)",
        "frequency": "Decennial",
        "next_update": "Census 2031 (results c. 2032-33)",
        "access": "API",
        "quality": ("Accredited official statistics (Census 2021, ~97% person response, estimates "
                    "adjusted for non-response). LA, region and England rows are the published "
                    "LA-level figures; BEDS sums the three LA counts and recomputes %."),
        "limitations": (
            "Census day 21 March 2021 fell in the third COVID-19 lockdown: furloughed people "
            "were counted as employed (temporarily away), labour-market activity may differ from "
            "normal, and students were counted at their term-time address (some were living "
            "elsewhere). Cell-key perturbation adds small noise to every cell, so LSOA counts do "
            "not sum exactly to LA totals and very small counts (<10) are unreliable; LSOA-to-LA "
            "sums differ slightly from LA rows. 2021 LSOAs differ from 2011 LSOAs (splits/merges), "
            "so direct comparison with 2011 needs the ONS LSOA11->LSOA21 lookup. Inactive/"
            "unemployed definitions use the ILO-style Census questions for the week before "
            "Census day; 'unemployed' includes full-time students seeking work. Hidden-potential "
            "pool = LT sick or disabled + looking after home/family + other (all 16+, incl. 65+)."),
        "indicators": indicators,
        "tables": [f"{v[2]} ({v[0]})" for v in CENSUS_TABLES.values()],
    }
    return meta, rows


# --------------------------------------------------------------------------
# 2. Population estimates + claimant count
POP_INDS = [
    ("popsa_16_19", ["117", "118", "119", "120"], "Population aged 16-19", "16-19"),
    ("popsa_18_24", ["205"], "Population aged 18-24", "18-24"),
    ("popsa_16_24", ["250"], "Population aged 16-24", "16-19,18-24"),
    ("popsa_25_49", ["207"], "Population aged 25-49", "context"),
    ("popsa_25_64", ["207", "208"], "Population aged 25-64", "25+ inactive"),
    ("popsa_16_64", ["203"], "Population aged 16-64 (working age)", "context"),
    ("popsa_all", ["200"], "Total population (all ages)", "context"),
]


def population(lsoas, urls):
    ages = sorted({c for _, cs, _, _ in POP_INDS for c in cs}, key=int)
    params = {"date": "latest", "gender": "0", "c_age": ",".join(ages), "measures": "20100",
              "select": "date_name,geography_code,c_age,obs_value"}
    recs = nomis("NM_2014_1", sorted(lsoas), params, "pop_lsoa", urls)
    period = f"mid-{recs[0]['DATE_NAME']}"
    cells = {}
    for r in recs:
        cells.setdefault(r["GEOGRAPHY_CODE"], {})[r["C_AGE"]] = num(r["OBS_VALUE"])
    rows, indicators, popv = [], [], {}
    for idn, codes, label, cohort in POP_INDS:
        indicators.append(dict(id=idn, label=label, unit="count", cohort=cohort, polarity="neutral",
                               description=f"ONS small-area mid-year estimate: {label.lower()}."))
        la_tot = {c: 0 for c in LAS}
        for g in sorted(cells):
            v = sum(cells[g][c] for c in codes)
            popv.setdefault(g, {})[idn] = v
            la_tot[lsoas[g]["la"]] += v
            rows.append(row(geo_label(g, lsoas), idn, v, period))
        for c, v in la_tot.items():
            popv.setdefault(c, {})[idn] = v
            rows.append(row(geo_label(c, lsoas), idn, v, period))
        popv.setdefault("BEDS", {})[idn] = sum(la_tot.values())
        rows.append(row(BEDS, idn, sum(la_tot.values()), period))
    meta = {
        "title": "Small-area population estimates by age (LSOA 2021)",
        "publisher": "Office for National Statistics (via Nomis)",
        "source_url": ("https://www.ons.gov.uk/peoplepopulationandcommunity/populationandmigration/"
                       "populationestimates/datasets/lowersuperoutputareamidyearpopulationestimates"),
        "api_url": list(urls),
        "geography": "LSOA21, LA (sum of LSOAs), county",
        "cohort": "16-19, 18-24, 25+ inactive, context",
        "period": period,
        "latest_period": period,
        "frequency": "Annual",
        "next_update": "Autumn each year (next mid-year release c. Nov 2026 - check Nomis)",
        "access": "API",
        "quality": ("Official statistics (ONS small-area population estimates, Census-2021 based, "
                    "constrained to LA mid-year estimates, so LSOAs sum exactly to LA totals)."),
        "limitations": ("Modelled from administrative data (GP registrations, child benefit, "
                        "students) rolled forward from Census 2021; accuracy declines with time "
                        "since the census and for LSOAs with student halls, care homes or new "
                        "housing. Not rebased to any later census."),
        "indicators": indicators,
    }
    return meta, rows, popv, period


CC_AGES = {"0": ("all", "All claimants aged 16+", "popsa_16_64", "16-64", "context"),
           "2": ("16_24", "Claimants aged 16-24", "popsa_16_24", "16-24", "16-19,18-24"),
           "3": ("25_49", "Claimants aged 25-49", "popsa_25_49", "25-49", "context"),
           "4": ("50plus", "Claimants aged 50+", None, None, "25+ inactive")}


def claimant(lsoas, popv, pop_period, urls):
    base = {"gender": "0", "age": ",".join(CC_AGES), "measure": "1", "measures": "20100",
            "select": "date,date_name,geography_code,age,obs_value"}
    recs_l = nomis("NM_162_1", sorted(lsoas), dict(base, date="latest"), "cc_lsoa", urls)
    recs_a = nomis("NM_162_1", list(LAS) + list(COMPARATORS),
                   dict(base, date="latestMINUS23-latest"), "cc_la", urls)
    latest = recs_l[0]["DATE"]
    latest_name = recs_l[0]["DATE_NAME"]
    rows, indicators = [], []
    for a, (stem, label, popk, popl, cohort) in CC_AGES.items():
        indicators.append(dict(id=f"cc_{stem}", label=f"{label} (count)", unit="count",
                               cohort=cohort, polarity="higher_is_worse",
                               description=f"Claimant count, {label.lower()} (JSA + UC searching "
                                           f"for work); LSOA values rounded to nearest 5."))
        if popk:
            indicators.append(dict(id=f"cc_{stem}_rate", label=f"{label} per resident aged {popl} (%)",
                                   unit="percent", cohort=cohort, polarity="higher_is_worse",
                                   description=f"Claimants ({label.lower()}) as % of residents aged "
                                               f"{popl} (ONS small-area estimate, {pop_period})."))
    for r in recs_l:
        stem, _, popk, _, _ = CC_AGES[r["AGE"]]
        g = r["GEOGRAPHY_CODE"]
        v = num(r["OBS_VALUE"])
        geo = geo_label(g, lsoas)
        rows.append(row(geo, f"cc_{stem}", v, latest_name))
        if popk:
            d = popv.get(g, {}).get(popk)
            rows.append(row(geo, f"cc_{stem}_rate", pct(v, d), latest_name, num=v, den=d))
    beds = {}
    for r in recs_a:
        stem, _, popk, _, _ = CC_AGES[r["AGE"]]
        g = r["GEOGRAPHY_CODE"]
        v = num(r["OBS_VALUE"])
        geo = geo_label(g, lsoas)
        rows.append(row(geo, f"cc_{stem}", v, r["DATE_NAME"]))
        if g in LAS and v is not None:
            beds[(r["DATE_NAME"], stem)] = beds.get((r["DATE_NAME"], stem), 0) + v
        if popk and r["DATE"] == latest and g in LAS:
            d = popv[g][popk]
            rows.append(row(geo, f"cc_{stem}_rate", pct(v, d), latest_name, num=v, den=d))
    for (period, stem), v in beds.items():
        rows.append(row(BEDS, f"cc_{stem}", v, period))
        popk = [x[2] for x in CC_AGES.values() if x[0] == stem][0]
        if popk and period == latest_name:
            d = popv["BEDS"][popk]
            rows.append(row(BEDS, f"cc_{stem}_rate", pct(v, d), period, num=v, den=d))
    meta = {
        "title": "Claimant count by LSOA (latest month) with LA trend",
        "publisher": "Office for National Statistics / DWP (via Nomis)",
        "source_url": "https://www.nomisweb.co.uk/sources/cc",
        "api_url": list(urls),
        "geography": "LSOA21 (latest month); LA, region, England, county (24 months)",
        "cohort": "16-19, 18-24, 25+ inactive, context",
        "period": latest_name,
        "latest_period": latest_name,
        "frequency": "Monthly",
        "next_update": "Monthly with the ONS labour market release (mid-month)",
        "access": "API",
        "quality": ("Official statistics (experimental status removed); administrative count of "
                    "people claiming JSA or UC with a 'searching for work' requirement on the "
                    "count date. Rates here are recomputed by this pipeline using ONS small-area "
                    f"population ({pop_period}), not Nomis's own 16-64 proportion."),
        "limitations": (
            "Counts are rounded to the nearest 5 at LSOA level (small cells 0/5 are highly "
            "uncertain); LA rows are the published LA figures, and LSOA sums do not equal them. "
            "Under Universal Credit the count includes some people in low-paid work required to "
            "seek more work, so it is not a pure unemployment measure and rose structurally "
            "with UC rollout; it excludes inactive people (e.g. LT sick on UC health) who are "
            "not searching for work. Population denominators lag the claimant month by up to "
            "two years. 50+ claimants have no matched denominator (rate omitted)."),
        "indicators": indicators,
    }
    return meta, rows


# --------------------------------------------------------------------------
# 3. IMD 2025
IMD_COLS = [  # stem, label, score col, rank col, decile col, cohort
    ("imd", "Index of Multiple Deprivation", 4, 5, 6, "context"),
    ("income", "Income domain", 7, 8, 9, "context"),
    ("employment", "Employment domain", 10, 11, 12, "25+ inactive"),
    ("education", "Education, Skills & Training domain", 13, 14, 15, "16-19,18-24,25+ inactive"),
    ("cyp", "Children & Young People sub-domain (education)", 37, 38, 39, "16-19"),
    ("adultskills", "Adult Skills sub-domain (education)", 40, 41, 42, "25+ inactive"),
]


def imd(lsoas, urls):
    url = IMD_CSV
    urls.append(url)
    rdr = csv.reader(io.StringIO(fetch(url, "imd2025_file7.csv").decode("utf-8-sig")))
    header = next(rdr)
    for stem, _, s, r_, d, _ in IMD_COLS:  # guard against column shifts
        assert "Score" in header[s] and "Rank" in header[r_] and "Decile" in header[d], stem
    recs = list(rdr)
    n_lsoa = len(recs)
    period = "IoD2025 (indicators mostly 2022/23)"
    rows, indicators = [], []
    for stem, label, *_rest, cohort in IMD_COLS:
        unit_s = "rate" if stem in ("income", "employment") else "score"
        indicators += [
            dict(id=f"imd25_{stem}_score", label=f"{label} score", unit=unit_s, cohort=cohort,
                 polarity="higher_is_worse",
                 description=f"IoD2025 {label} score (higher = more deprived)"
                             + (" - proportion of population deprived." if unit_s == "rate" else ".")),
            dict(id=f"imd25_{stem}_rank", label=f"{label} rank", unit="rank", cohort=cohort,
                 polarity="higher_is_better",
                 description=f"National rank of {n_lsoa} English LSOAs (1 = most deprived)."),
            dict(id=f"imd25_{stem}_decile", label=f"{label} decile", unit="decile", cohort=cohort,
                 polarity="higher_is_better",
                 description="National decile (1 = most deprived 10% of LSOAs in England)."),
        ]
    summ = {}
    found = set()
    for rec in recs:
        g = rec[0]
        if g not in lsoas:
            continue
        found.add(g)
        geo = geo_label(g, lsoas)
        la = lsoas[g]["la"]
        assert rec[2] == la, f"LA mismatch {g}"
        for stem, _, s, r_, d, _ in IMD_COLS:
            dec = int(rec[d])
            rows.append(row(geo, f"imd25_{stem}_score", float(rec[s]), period))
            rows.append(row(geo, f"imd25_{stem}_rank", int(rec[r_]), period))
            rows.append(row(geo, f"imd25_{stem}_decile", dec, period))
            for key in (la, "BEDS"):
                c = summ.setdefault((key, stem), [0, 0, 0])
                c[0] += 1
                c[1] += dec == 1
                c[2] += dec <= 2
    missing = set(lsoas) - found
    assert not missing, f"LSOAs missing from IMD: {sorted(missing)[:5]}"
    for stem, label, *_rest, cohort in IMD_COLS[:4]:
        for band, ix in (("10", 1), ("20", 2)):
            indicators += [
                dict(id=f"imd25_{stem}_lsoas_top{band}", label=f"LSOAs in England's most deprived "
                     f"{band}% ({label})", unit="count", cohort=cohort, polarity="higher_is_worse",
                     description=f"Number of LSOAs in national {label} decile "
                                 f"{'1' if band == '10' else '1-2'}."),
                dict(id=f"imd25_{stem}_lsoas_top{band}_pct", label=f"% of LSOAs in England's most "
                     f"deprived {band}% ({label})", unit="percent", cohort=cohort,
                     polarity="higher_is_worse",
                     description=f"Share of the area's LSOAs in national {label} decile "
                                 f"{'1' if band == '10' else '1-2'} (England = {band}% by design)."),
            ]
            for key in list(LAS) + ["BEDS"]:
                tot, d1, d12 = summ[(key, stem)]
                n = d1 if band == "10" else d12
                geo = BEDS if key == "BEDS" else geo_label(key, lsoas)
                rows.append(row(geo, f"imd25_{stem}_lsoas_top{band}", n, period))
                rows.append(row(geo, f"imd25_{stem}_lsoas_top{band}_pct", pct(n, tot), period,
                                num=n, den=tot))
    meta = {
        "title": "English Indices of Deprivation 2025 (LSOA 2021)",
        "publisher": "Ministry of Housing, Communities and Local Government",
        "source_url": IMD_PAGE,
        "api_url": list(urls),
        "geography": "LSOA21; LA and county summary counts",
        "cohort": "16-19, 18-24, 25+ inactive, context",
        "period": "IoD2025",
        "latest_period": "IoD2025 (published 2025; most indicators 2022/23, population mid-2022)",
        "frequency": "Ad hoc",
        "next_update": "Unknown (historically every 4-5 years)",
        "access": "CSV download",
        "quality": ("Accredited official statistics. First IoD on 2021 LSOAs; "
                    f"{n_lsoa} English LSOAs ranked. Education domain combines the Children & "
                    "Young People sub-domain (attainment, absence, staying on, HE entry) and "
                    "Adult Skills sub-domain (no/low qualifications, English proficiency, "
                    "working-age adults, Census 2021)."),
        "limitations": (
            "Ranks and deciles are relative: they show how an LSOA compares with others in "
            "England, not absolute levels, and a change of rank does not mean deprivation rose "
            "or fell. Not every person in a deprived LSOA is deprived. Not directly comparable "
            "with IoD2019 (2011 LSOAs, changed indicators). Domain scores (other than income "
            "and employment rates) are standardised composites without natural units. "
            "Indicator reference years vary (mostly 2022/23; Adult Skills uses Census 2021). "
            "LA summary rows here count LSOAs only; MHCLG's official LA summary measures "
            "(rank of average score etc.) are in File 10/11."),
        "indicators": indicators,
    }
    return meta, rows


# --------------------------------------------------------------------------
def main():
    lsoas = load_lsoas()
    assert len(lsoas) > 400, f"only {len(lsoas)} LSOAs"
    print(f"{len(lsoas)} LSOAs in scope")

    u = []
    meta, rows = census(lsoas, u)
    save("census_lsoa", meta, rows)
    census_rows = rows

    u = []
    meta, rows, popv, pop_period = population(lsoas, u)
    save("pop_lsoa", meta, rows)

    u = []
    meta, rows = claimant(lsoas, popv, pop_period, u)
    save("claimant_lsoa", meta, rows)
    cc_period = meta["period"]

    u = []
    meta, rows = imd(lsoas, u)
    save("imd2025", meta, rows)
    imd_rows = rows

    # ---- summary -----------------------------------------------------------
    print("\nSummary")
    get = {(r["code"], r["indicator"]): r for r in census_rows}
    for c in list(LAS) + ["BEDS"]:
        lt = get[(c, "census_inactive_ltsick")]["value"]
        hp = get[(c, "census_inactive_non_student_non_retired")]
        print(f"  {c:10s} LT-sick {lt:>7,}  hidden pool {hp['value']:>7,} "
              f"({get[(c, 'census_inactive_non_student_non_retired_pct')]['value']}% of 16+)  "
              f"no quals {get[(c, 'census_noqual_pct')]['value']}%  L4+ "
              f"{get[(c, 'census_level4plus_pct')]['value']}%")
    for r in imd_rows:
        if r["indicator"] in ("imd25_imd_lsoas_top10", "imd25_imd_lsoas_top20") and r["level"] != "LSOA":
            print(f"  {r['name']:22s} {r['indicator']}: {r['value']}")
    top = sorted((r for r in census_rows if r["level"] == "LSOA"
                  and r["indicator"] == "census_inactive_non_student_non_retired"),
                 key=lambda r: -r["value"])[:5]
    print("  Top 5 LSOAs by hidden-potential pool:")
    for r in top:
        p = get[(r["code"], "census_inactive_non_student_non_retired_pct")]["value"]
        print(f"    {r['code']} {r['name']:24s} {r['value']:>4} ({p}% of 16+)")
    print(f"  claimant period {cc_period}")


if __name__ == "__main__":
    main()
