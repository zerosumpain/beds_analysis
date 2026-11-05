"""LA-level labour supply and skills datasets from Nomis (plus ONS census APIs).

Writes nine datasets (see DATASETS at the bottom): pop_mye, pop_snpp, aps,
claimant, ashe_res, bres_sectors, jobs_density, census_age_activity, census_od.

Every Nomis call uses explicit GSS geography codes, `select=` columns and the
`.data.csv` endpoint. Dataset ids and dimension codes were looked up from
/api/v01/dataset/def.sdmx.json and /dataset/NM_x_1/<dim>.def.sdmx.json.

Raw responses are cached in data/raw/; pass --refresh to re-download.
"""
import csv
import hashlib
import io
import json
import sys
import urllib.parse
import zipfile

from common import COMPARATORS, LAS, RAW, fetch, save

NOMIS = "https://www.nomisweb.co.uk/api/v01/dataset/"
ONS_CUSTOM = "https://api.beta.ons.gov.uk/v1/population-types/UR/census-observations"
OD_ZIP = "https://www.nomisweb.co.uk/output/census/2021/odwp01ew.zip"
CENTROIDS_URL = (
    "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
    "LAD_DEC_2021_EW_BUC_RUC/FeatureServer/0/query?where=1%3D1"
    "&outFields=LAD21CD,LAD21NM,LAT,LONG&returnGeometry=false&f=json"
)
REFRESH = "--refresh" in sys.argv

GEOS = {**LAS, **COMPARATORS}
GEO_PARAM = ",".join(GEOS)
BEDS = {"code": "BEDS", "name": "Bedfordshire (3 UAs)", "level": "county"}
LEVEL = {"E06": "LA", "E07": "LA", "E08": "LA", "E09": "LA", "W06": "LA",
         "E12": "region", "E92": "country", "BEDS": "county"}
API_URLS = {}  # dataset id -> list of URLs fetched


def level_of(code):
    return LEVEL.get(code[:3], LEVEL.get(code, "LA"))


def name_of(code):
    return BEDS["name"] if code == "BEDS" else GEOS.get(code, code)


def get(url, ds_id, suffix="csv"):
    """Fetch with a content-addressed cache name and record the URL for lineage."""
    API_URLS.setdefault(ds_id, []).append(url)
    name = f"nomis_la_{hashlib.sha1(url.encode()).hexdigest()[:12]}.{suffix}"
    p = RAW / name
    if REFRESH and p.exists():
        p.unlink()
    return fetch(url, name)


def nomis(ds_id, nm, **params):
    """Query a Nomis dataset; returns list of dict rows (CSV)."""
    q = urllib.parse.urlencode(params, safe=",")
    url = f"{NOMIS}{nm}.data.csv?{q}"
    text = get(url, ds_id).decode("utf-8-sig", errors="replace")
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise RuntimeError(f"no rows from {url}")
    return rows


def num(v):
    if v in (None, ""):
        return None
    try:
        f = float(v)
    except ValueError:
        return None
    return int(f) if f.is_integer() else f


def row(code, indicator, value, period, **kw):
    r = {"code": code, "name": name_of(code), "level": level_of(code),
         "indicator": indicator, "value": value, "period": period,
         "ci": None, "num": None, "den": None, "breakdown": None}
    r.update(kw)
    if value is None:
        r["suppressed"] = True
    return r


def ind(i, label, unit, cohort, polarity, description):
    return {"id": i, "label": label, "unit": unit, "cohort": cohort,
            "polarity": polarity, "description": description}


def r1(x, nd=1):
    return None if x is None else round(x, nd)


# --------------------------------------------------------------------------
# 1. Mid-year population estimates (NM_2002_1)
# --------------------------------------------------------------------------
MYE_BANDS = {  # indicator -> list of c_age codes to sum
    "pop_16_17": ["204"], "pop_16_19": ["117", "118", "119", "120"],
    "pop_18_24": ["205"], "pop_16_24": ["250"], "pop_25_49": ["207"],
    "pop_25_64": ["207", "208"], "pop_16_64": ["203"], "pop_50_64": ["208"],
    "pop_65_plus": ["209"], "pop_total": ["200"],
}
SINGLE_AGES = {str(101 + a): a for a in range(14, 25)}  # c_age 115..125 = age 14..24


def load_mye():
    codes = sorted({c for v in MYE_BANDS.values() for c in v} | set(SINGLE_AGES), key=int)
    raw = nomis("pop_mye", "NM_2002_1", geography=GEO_PARAM, date="latestMINUS5-latest",
                gender="0", c_age=",".join(codes), measures="20100",
                select="date_name,geography_code,c_age,c_age_name,obs_value,obs_status")
    pop = {}  # (code, year, c_age) -> value
    for x in raw:
        pop[(x["GEOGRAPHY_CODE"], int(x["DATE_NAME"]), x["C_AGE"])] = num(x["OBS_VALUE"])
    years = sorted({k[1] for k in pop})
    return pop, years


def mye_band(pop, code, year, ind_id):
    vals = [pop.get((code, year, c)) for c in MYE_BANDS[ind_id]]
    return None if any(v is None for v in vals) else sum(vals)


def mye_band_beds(pop, year, ind_id):
    vals = [mye_band(pop, c, year, ind_id) for c in LAS]
    return None if any(v is None for v in vals) else sum(vals)


def build_pop_mye(pop, years):
    latest = years[-1]
    rows = []
    for year in years:
        for i in MYE_BANDS:
            for code in GEOS:
                rows.append(row(code, f"pop_mye_{i[4:]}", mye_band(pop, code, year, i),
                                f"mid-{year}", series="annual"))
            rows.append(row("BEDS", f"pop_mye_{i[4:]}", mye_band_beds(pop, year, i),
                            f"mid-{year}", series="annual"))
    for c_age, age in SINGLE_AGES.items():
        for code in GEOS:
            rows.append(row(code, "pop_single_age", pop.get((code, latest, c_age)),
                            f"mid-{latest}", breakdown=f"age {age}"))
        tot = sum(pop[(c, latest, c_age)] for c in LAS)
        rows.append(row("BEDS", "pop_single_age", tot, f"mid-{latest}", breakdown=f"age {age}"))
    labels = {"16_17": "16-17", "16_19": "16-19", "18_24": "18-24", "16_24": "16-24",
              "25_49": "25-49", "25_64": "25-64", "16_64": "16-64", "50_64": "50-64",
              "65_plus": "65+", "total": "all ages"}
    cohort = {"16_17": "16-19", "16_19": "16-19", "18_24": "18-24", "16_24": "16-19,18-24",
              "25_49": "25+ inactive", "25_64": "25+ inactive", "16_64": "context",
              "50_64": "25+ inactive", "65_plus": "context", "total": "context"}
    inds = [ind(f"pop_mye_{k}", f"Population aged {v}", "count", cohort[k], "neutral",
                f"ONS mid-year estimate of usual residents aged {v}.")
            for k, v in labels.items()]
    inds.append(ind("pop_single_age", "Population by single year of age (14-24)", "count",
                    "16-19,18-24", "neutral",
                    f"Mid-{latest} residents by single year of age 14-24 (breakdown 'age N'); "
                    "ages 14-15 show the cohort reaching 16 in the next two years."))
    meta = {
        "title": "Mid-year population estimates by age (local authority)",
        "publisher": "Office for National Statistics (via Nomis)",
        "source_url": "https://www.ons.gov.uk/peoplepopulationandcommunity/populationandmigration/populationestimates",
        "api_url": API_URLS["pop_mye"], "geography": "LA, region, England, Bedfordshire total",
        "cohort": "16-19, 18-24, 25+ inactive, context", "period": f"mid-{latest}",
        "latest_period": f"mid-{latest}", "frequency": "Annual",
        "next_update": f"Summer {latest + 2} (mid-{latest + 1} estimates)", "access": "API",
        "quality": "Accredited official statistics; mid-2022 onward rolled forward from Census 2021 "
                   "using admin data. International migration component is the largest source of "
                   "uncertainty and is revised as ONS improves admin-based migration estimates.",
        "limitations": "Point estimates with no published confidence intervals. Student-age (18-24) "
                       "counts depend on term-time address rules (students counted at term-time "
                       "address). Earlier years may be revised. 16-19 and 25-64 are sums of published "
                       "single-year/band counts.",
        "indicators": inds, "dataset_code": "NM_2002_1",
    }
    return meta, rows


# --------------------------------------------------------------------------
# 2. Subnational population projections, 2022-based (NM_2006_1)
# --------------------------------------------------------------------------
def build_pop_snpp():
    years = ",".join(str(y) for y in range(2025, 2041))
    raw = nomis("pop_snpp", "NM_2006_1", geography=GEO_PARAM, projected_year=years,
                gender="0", c_age="117,118,119,120,205,203,250,200", measures="20100",
                select="date_name,projected_year_name,geography_code,c_age,obs_value,obs_status")
    base = {x["DATE_NAME"] for x in raw}
    v = {}
    for x in raw:
        v[(x["GEOGRAPHY_CODE"], int(x["PROJECTED_YEAR_NAME"]), x["C_AGE"])] = num(x["OBS_VALUE"])
    bands = {"snpp_16_19": ["117", "118", "119", "120"], "snpp_18_24": ["205"],
             "snpp_16_24": ["250"], "snpp_16_64": ["203"], "snpp_total": ["200"]}
    rows = []
    for y in range(2025, 2041):
        for i, cs in bands.items():
            for code in GEOS:
                vals = [v.get((code, y, c)) for c in cs]
                val = None if None in vals else sum(vals)
                rows.append(row(code, i, val, str(y), series="projection"))
            bvals = [v.get((c, y, a)) for c in LAS for a in cs]
            rows.append(row("BEDS", i, None if None in bvals else sum(bvals), str(y),
                            series="projection"))
    labels = {"snpp_16_19": ("16-19", "16-19"), "snpp_18_24": ("18-24", "18-24"),
              "snpp_16_24": ("16-24", "16-19,18-24"), "snpp_16_64": ("16-64", "context"),
              "snpp_total": ("all ages", "context")}
    inds = [ind(k, f"Projected population aged {a}", "count", c, "neutral",
                f"ONS 2022-based SNPP principal projection of residents aged {a}, by projection "
                "year (period = projection year, mid-year).") for k, (a, c) in labels.items()]
    meta = {
        "title": "Subnational population projections, 2022-based (principal)",
        "publisher": "Office for National Statistics (via Nomis)",
        "source_url": "https://www.ons.gov.uk/peoplepopulationandcommunity/populationandmigration/populationprojections/bulletins/subnationalpopulationprojectionsforengland/2022based",
        "api_url": API_URLS["pop_snpp"], "geography": "LA, region, England, Bedfordshire total",
        "cohort": "16-19, 18-24, context", "period": "2025-2040 (2022-based)",
        "latest_period": "2040", "frequency": "Ad hoc",
        "next_update": "Unknown (SNPP normally every 2 years; next likely 2024-based)",
        "access": "API",
        "quality": "Official statistics (ONS); projections, not forecasts. They assume recent trends in births, deaths and "
                   "migration continue and do not model local policy or development (e.g. housing "
                   "growth or a resort opening).",
        "limitations": f"Base year {', '.join(sorted(base))}; base pre-dates the mid-2023 to "
                       "mid-2025 MYEs so early projection years will not match published "
                       "estimates. Migration assumptions dominate at LA level and 18-24 counts are "
                       "sensitive to student migration. No uncertainty intervals at LA level.",
        "indicators": inds, "dataset_code": "NM_2006_1",
    }
    return meta, rows


# --------------------------------------------------------------------------
# 3. Annual Population Survey (NM_17_5) + model-based unemployment (NM_127_1)
# --------------------------------------------------------------------------
APS_VARS = {  # variable code -> (indicator, label, unit, cohort, polarity, description)
    "45": ("aps_emp_rate_16_64", "Employment rate 16-64", "percent", "context", "higher_is_better",
           "% of residents aged 16-64 in employment."),
    "84": ("aps_unemp_rate_16_64", "Unemployment rate 16-64 (APS direct)", "percent", "context",
           "higher_is_worse", "Unemployed as % of economically active 16-64 (direct survey "
           "estimate; often unreliable at LA level - prefer the model-based rate)."),
    "111": ("aps_inact_rate_16_64", "Economic inactivity rate 16-64", "percent",
            "25+ inactive,context", "higher_is_worse",
            "% of residents aged 16-64 economically inactive. num = inactive count (rounded)."),
    "1487": ("aps_inact_want_job_16_64", "Inactive 16-64 who want a job", "percent",
            "25+ inactive", "neutral",
            "% of economically inactive 16-64 who say they want a job (latent labour supply)."),
    "1493": ("aps_inact_reason_student", "Inactive: student", "percent", "25+ inactive,18-24",
             "neutral", "% of economically inactive 16-64 whose main reason is study."),
    "1494": ("aps_inact_reason_family_home", "Inactive: looking after family/home", "percent",
             "25+ inactive", "neutral",
             "% of economically inactive 16-64 looking after family or home."),
    "1495": ("aps_inact_reason_temp_sick", "Inactive: temporary sick", "percent",
             "25+ inactive", "neutral", "% of economically inactive 16-64 temporarily sick."),
    "1496": ("aps_inact_reason_lt_sick", "Inactive: long-term sick", "percent",
             "25+ inactive", "higher_is_worse",
             "% of economically inactive 16-64 who are long-term sick or disabled."),
    "1497": ("aps_inact_reason_discouraged", "Inactive: discouraged", "percent",
             "25+ inactive", "higher_is_worse",
             "% of economically inactive 16-64 who believe no jobs are available."),
    "1498": ("aps_inact_reason_retired", "Inactive: retired", "percent", "25+ inactive",
             "neutral", "% of economically inactive 16-64 who have retired (early retirement)."),
    "1499": ("aps_inact_reason_other", "Inactive: other reason", "percent", "25+ inactive",
             "neutral", "% of economically inactive 16-64 inactive for other reasons."),
    "1207": ("aps_emp_rate_16_24", "Employment rate 16-24", "percent", "16-19,18-24",
             "higher_is_better", "% of residents aged 16-24 in employment (includes students)."),
    "1213": ("aps_unemp_rate_16_24", "Unemployment rate 16-24", "percent", "16-19,18-24",
             "higher_is_worse", "Unemployed as % of economically active 16-24."),
    "1219": ("aps_inact_rate_16_24", "Economic inactivity rate 16-24", "percent", "16-19,18-24",
             "neutral", "% of residents aged 16-24 economically inactive (mostly full-time students)."),
    "46": ("aps_emp_rate_16_19", "Employment rate 16-19", "percent", "16-19", "neutral",
           "% of residents aged 16-19 in employment (most are in education)."),
    "112": ("aps_inact_rate_16_19", "Economic inactivity rate 16-19", "percent", "16-19",
            "neutral", "% of residents aged 16-19 economically inactive."),
    "47": ("aps_emp_rate_20_24", "Employment rate 20-24", "percent", "18-24", "higher_is_better",
           "% of residents aged 20-24 in employment."),
    "113": ("aps_inact_rate_20_24", "Economic inactivity rate 20-24", "percent", "18-24",
            "neutral", "% of residents aged 20-24 economically inactive."),
    "544": ("aps_pct_18_24_ft_education", "18-24 in full-time education", "percent", "18-24",
            "neutral", "% of residents aged 18-24 in full-time education."),
    "114": ("aps_inact_rate_25_34", "Economic inactivity rate 25-34", "percent", "25+ inactive",
            "higher_is_worse", "% of residents aged 25-34 economically inactive."),
    "115": ("aps_inact_rate_35_49", "Economic inactivity rate 35-49", "percent", "25+ inactive",
            "higher_is_worse", "% of residents aged 35-49 economically inactive."),
    "117": ("aps_inact_rate_50_64", "Economic inactivity rate 50-64", "percent", "25+ inactive",
            "higher_is_worse", "% of residents aged 50-64 economically inactive."),
}
APS_QUAL = {
    "1902": ("aps_qual_rqf4plus_16_64", "Qualified to RQF4+ (16-64)", "higher_is_better",
             "% of residents aged 16-64 with RQF level 4 or above (degree, HND, higher apprenticeship)."),
    "2010": ("aps_qual_rqf3plus_16_64", "Qualified to RQF3+ (16-64)", "higher_is_better",
             "% of residents aged 16-64 with RQF level 3 or above (A level / equivalent)."),
    "2011": ("aps_qual_rqf2plus_16_64", "Qualified to RQF2+ (16-64)", "higher_is_better",
             "% of residents aged 16-64 with RQF level 2 or above (5 GCSE 9-4 / equivalent)."),
    "1947": ("aps_qual_none_16_64", "No qualifications (16-64)", "higher_is_worse",
             "% of residents aged 16-64 with no qualifications."),
}
APS_SELECT = ("date_name,geography_code,variable,measures,obs_value,obs_status,obs_status_name")


def aps_parse(raw):
    """Group APS rows into {(geo, period, var): {measure: (value, status, status_name)}}."""
    out = {}
    order = []
    for x in raw:
        k = (x["GEOGRAPHY_CODE"], x["DATE_NAME"], x["VARIABLE"])
        if k not in out:
            out[k] = {}
            order.append(k)
        out[k][x["MEASURES"]] = (num(x["OBS_VALUE"]), x["OBS_STATUS"], x["OBS_STATUS_NAME"])
    return out, order


def aps_row(code, period, indicator, m):
    val, st, st_name = m.get("20599", (None, "Q", "missing"))
    ci, ci_st, _ = m.get("21003", (None, None, None))
    n, _, _ = m.get("21001", (None, None, None))
    d, _, _ = m.get("21002", (None, None, None))
    ok = st == "A" and val is not None
    # Nomis withholds the CI (status G/B) when the group sample is small (3-9): the
    # estimate is flagged unreliable ('*' in Nomis profiles). Per the contract it is
    # nulled and marked suppressed; the published figure is kept in attrs for reference.
    reliable = ok and ci_st == "A"
    r = row(code, indicator, val if reliable else None, period,
            ci=ci if reliable else None,
            num=n if reliable else None, den=d if reliable else None, series="annual")
    if not ok:
        r["attrs"] = {"status": st_name}
    elif not reliable:
        r["attrs"] = {"status": "Estimate unreliable: group sample size small (3-9); CI not "
                                "published", "unreliable_estimate": val, "unreliable_num": n}
    return r


def build_aps():
    measures = "20599,21001,21002,21003"
    dates = ",".join(["latest"] + [f"latestMINUS{n}" for n in (4, 8, 12, 16, 20)])
    raw = nomis("aps", "NM_17_5", geography=GEO_PARAM, date=dates,
                variable=",".join(APS_VARS), measures=measures, select=APS_SELECT)
    # Qualifications are published only for Jan-Dec periods since the 2022 RQF switch.
    rawq = nomis("aps", "NM_17_5", geography=GEO_PARAM, date="latestMINUS16-latest",
                 variable=",".join(APS_QUAL), measures=measures, select=APS_SELECT)
    rows = []
    g, order = aps_parse(raw)
    periods = []
    for k in order:
        code, period, var = k
        if period not in periods:
            periods.append(period)
        rows.append(aps_row(code, period, APS_VARS[var][0], g[k]))
    gq, orderq = aps_parse(rawq)
    qperiods = []
    for k in orderq:
        code, period, var = k
        if not period.startswith("Jan"):
            continue
        if period not in qperiods:
            qperiods.append(period)
        rows.append(aps_row(code, period, APS_QUAL[var][0], gq[k]))
    # Model-based unemployment (16+), NM_127_1: item 1 count, 2 rate; 20701 = CI.
    mb = nomis("aps", "NM_127_1", geography=GEO_PARAM, date=dates, item="1,2",
               measures="20100,20701",
               select="date_name,geography_code,item,measures,obs_value,obs_status")
    mbg = {}
    for x in mb:
        mbg.setdefault((x["GEOGRAPHY_CODE"], x["DATE_NAME"], x["ITEM"]), {})[x["MEASURES"]] = (
            num(x["OBS_VALUE"]), x["OBS_STATUS"])
    for (code, period, item), m in mbg.items():
        val, st = m.get("20100", (None, "Q"))
        ci, cst = m.get("20701", (None, None))
        indic = "aps_unemp_rate_model_16plus" if item == "2" else "aps_unemp_count_model_16plus"
        rows.append(row(code, indic, val if st == "A" else None, period,
                        ci=ci if cst == "A" else None, series="annual"))
    latest = periods[0]
    qlatest = sorted(qperiods, key=lambda p: p[-4:])[-1]
    inds = [ind(v[0], v[1], v[2], v[3], v[4], v[5]) for v in APS_VARS.values()]
    inds += [ind(v[0], v[1], "percent", "context,18-24,25+ inactive", v[2],
                 v[3] + " Published for Jan-Dec periods only.") for v in APS_QUAL.values()]
    inds += [
        ind("aps_unemp_rate_model_16plus", "Unemployment rate 16+ (model-based)", "percent",
            "context", "higher_is_worse",
            "ONS model-based LA unemployment rate (APS combined with claimant count); more "
            "reliable than the direct APS estimate at LA level."),
        ind("aps_unemp_count_model_16plus", "Unemployed 16+ (model-based count)", "count",
            "context", "higher_is_worse", "ONS model-based estimate of unemployed residents 16+."),
    ]
    sup = sum(1 for r in rows if r["value"] is None)
    meta = {
        "title": "Annual Population Survey: employment, inactivity and qualifications",
        "publisher": "Office for National Statistics (via Nomis)",
        "source_url": "https://www.nomisweb.co.uk/sources/aps",
        "api_url": API_URLS["aps"], "geography": "LA, region, England",
        "cohort": "16-19, 18-24, 25+ inactive, context", "period": latest,
        "latest_period": latest, "qualifications_period": qlatest, "frequency": "Quarterly",
        "next_update": "Quarterly (rolling 12-month periods, roughly Jan/Apr/Jul/Oct)",
        "access": "API",
        "quality": "APS is a household survey; LA estimates rest on a few hundred respondents per "
                   "LA (far fewer for 16-24 sub-groups). Nomis 95% CIs (`ci`, +/- percentage "
                   "points) are typically +/-4-6 pts for 16-64 rates and +/-10-20 pts for youth "
                   "rates or reasons for inactivity at LA level. LFS/APS is badged 'official "
                   "statistics in development' after 2023-24 response-rate problems and reweighting.",
        "limitations": "Values Nomis does not publish (sample size 0-2 / disclosive, '!') and "
                       "estimates Nomis flags unreliable (sample 3-9, CI withheld, '*') are null "
                       f"with suppressed=true ({sup} rows) and the Nomis status in attrs.status; "
                       "for '*' rows the published figure is kept in attrs.unreliable_estimate "
                       "for reference only. Temporary-sick and discouraged reasons are "
                       "suppressed for all three LAs. Annual points are the "
                       "same rolling 12-month window each year (Jul-Jun), not calendar years. Year-"
                       "to-year LA changes are usually within sampling error. Qualifications use "
                       "RQF levels from 2022 (not comparable with older NVQ series) and are only "
                       "released for Jan-Dec windows, so qualification rows have a different "
                       "period. Reasons for inactivity sum to ~100% of inactive 16-64. num/den are "
                       "survey-weighted counts rounded to the nearest 100. APS excludes most "
                       "communal establishments (e.g. many student halls).",
        "indicators": inds, "dataset_code": "NM_17_5 (variables), NM_127_1 (model-based unemployment)",
    }
    return meta, rows


# --------------------------------------------------------------------------
# 4. Claimant count by age (NM_162_1)
# --------------------------------------------------------------------------
def build_claimant(pop, mye_years):
    raw = nomis("claimant", "NM_162_1", geography=GEO_PARAM, date="latestMINUS35-latest",
                gender="0", age="0,10,11,3,4,20", measure="1", measures="20100",
                select="date,date_name,geography_code,age,obs_value,obs_status")
    v = {}
    months = []
    for x in raw:
        v[(x["GEOGRAPHY_CODE"], x["DATE"], x["AGE"])] = num(x["OBS_VALUE"])
        if (x["DATE"], x["DATE_NAME"]) not in months:
            months.append((x["DATE"], x["DATE_NAME"]))
    months.sort()
    # age code -> (indicator suffix, label, MYE band for rate denominator, cohort)
    ages = {"10": ("16_17", "16-17", "pop_16_17", "16-19"),
            "11": ("18_24", "18-24", "pop_18_24", "18-24"),
            "3": ("25_49", "25-49", "pop_25_49", "25+ inactive"),
            "4": ("50_plus", "50+", "pop_50_64", "25+ inactive"),
            "0": ("16_plus", "16+ (all)", "pop_16_64", "context")}
    rows = []
    for date, label in months:
        y = min(int(date[:4]), mye_years[-1])
        for age, (suf, _, band, _) in ages.items():
            tot_c, tot_p = 0, 0
            for code in GEOS:
                c = v.get((code, date, age))
                p = mye_band(pop, code, y, band)
                # 50+ rate: claimants aged 50-64 (50+ minus 65+) over residents 50-64.
                cr = c
                if age == "4" and c is not None:
                    o = v.get((code, date, "20"))
                    cr = None if o is None else c - o
                rate = r1(100 * cr / p) if cr is not None and p else None
                rows.append(row(code, f"claimant_count_{suf}", c, label, series="monthly"))
                rows.append(row(code, f"claimant_rate_{suf}", rate, label, num=cr, den=p,
                                series="monthly"))
                if code in LAS:
                    tot_c = None if tot_c is None or c is None else tot_c + c
                    tot_p = None if tot_p is None or p is None else tot_p + p
            rows.append(row("BEDS", f"claimant_count_{suf}", tot_c, label, series="monthly"))
            # BEDS rate recomputed from summed counts and summed populations.
            if age == "4" and tot_c is not None:
                o = sum(v.get((c, date, "20")) or 0 for c in LAS)
                bcr = tot_c - o
            else:
                bcr = tot_c
            brate = r1(100 * bcr / tot_p) if bcr is not None and tot_p else None
            rows.append(row("BEDS", f"claimant_rate_{suf}", brate, label, num=bcr, den=tot_p,
                            series="monthly"))
    inds = []
    for age, (suf, lab, band, coh) in ages.items():
        inds.append(ind(f"claimant_count_{suf}", f"Claimants aged {lab}", "count", coh,
                        "higher_is_worse", f"Claimant count (UC searching-for-work + JSA), aged {lab}."))
        den = "residents aged 16-64" if age == "0" else (
            "residents aged 50-64; numerator = claimants 50+ minus 65+" if age == "4"
            else f"residents aged {lab}")
        inds.append(ind(f"claimant_rate_{suf}", f"Claimant rate {lab}", "percent", coh,
                        "higher_is_worse",
                        f"Claimants as % of {den} (ONS mid-year estimate for that year, latest "
                        "available MYE for months after it). Computed here, not by ONS."))
    latest = months[-1][1]
    meta = {
        "title": "Claimant count by age (monthly)",
        "publisher": "DWP / ONS (via Nomis)",
        "source_url": "https://www.nomisweb.co.uk/sources/cc",
        "api_url": API_URLS["claimant"], "geography": "LA, region, England, Bedfordshire total",
        "cohort": "16-19, 18-24, 25+ inactive, context",
        "period": latest, "latest_period": latest, "frequency": "Monthly",
        "next_update": "Monthly (mid-month labour market release)", "access": "API",
        "quality": "Official statistics in development (ONS). Administrative count, not a survey: "
                   "no sampling error. Latest month is provisional and can be revised.",
        "limitations": "Since Universal Credit full service the count includes UC claimants "
                       "required to search for work, including some who are employed on low "
                       "earnings, so it is NOT a measure of unemployment and is not comparable with "
                       "pre-2013 JSA-only counts. Counts rounded to nearest 5 (so 16-17 is very "
                       "noisy). Rates are computed in this pipeline with ONS MYE denominators "
                       "(Nomis only publishes the all-age rate at LA level) and may differ "
                       "slightly from ONS-published rates. Not seasonally adjusted.",
        "indicators": inds, "dataset_code": "NM_162_1 (denominators NM_2002_1)",
    }
    return meta, rows


# --------------------------------------------------------------------------
# 5. ASHE resident (NM_30_1) and workplace (NM_99_1)
# --------------------------------------------------------------------------
ASHE_SERIES = [  # (sex code, pay code, suffix, label)
    ("8", "1", "wk_ft", "Median gross weekly pay, full-time"),
    ("8", "5", "hr_ft", "Median gross hourly pay, full-time"),
    ("8", "6", "hr_xot_ft", "Median hourly pay excl. overtime, full-time"),
    ("7", "1", "wk_all", "Median gross weekly pay, all employees"),
    ("7", "5", "hr_all", "Median gross hourly pay, all employees"),
]


def build_ashe():
    rows, inds, periods = [], [], set()
    for nm, basis, blabel in (("NM_30_1", "res", "place of residence"),
                              ("NM_99_1", "wp", "place of work")):
        for sex, pay, suf, label in ASHE_SERIES:
            raw = nomis("ashe_res", nm, geography=GEO_PARAM, date="latestMINUS5-latest",
                        sex=sex, item="2", pay=pay, measures="20100,20701",
                        select="date_name,geography_code,measures,obs_value,obs_status")
            g = {}
            for x in raw:
                g.setdefault((x["GEOGRAPHY_CODE"], x["DATE_NAME"]), {})[x["MEASURES"]] = (
                    num(x["OBS_VALUE"]), x["OBS_STATUS"])
            iid = f"ashe_{basis}_{suf}"
            for (code, year), m in sorted(g.items(), key=lambda kv: kv[0][1]):
                periods.add(year)
                val, st = m.get("20100", (None, "Q"))
                cv, cst = m.get("20701", (None, None))
                ok = st == "A" and val is not None
                ci = r1(1.96 * cv / 100 * val, 2) if ok and cv is not None and cst == "A" else None
                r = row(code, iid, val if ok else None, year, ci=ci, series="annual")
                if ok and cv is not None:
                    r["attrs"] = {"cv_pct": cv}
                rows.append(r)
            inds.append(ind(iid, f"{label} ({blabel})", "gbp", "context", "higher_is_better",
                            f"ASHE {label.lower()} (GBP, April each year), by {blabel}."))
    latest = max(periods)
    meta = {
        "title": "Annual Survey of Hours and Earnings: median pay by residence and workplace",
        "publisher": "Office for National Statistics (via Nomis)",
        "source_url": "https://www.ons.gov.uk/employmentandlabourmarket/peopleinwork/earningsandworkinghours/bulletins/annualsurveyofhoursandearnings/latest",
        "api_url": API_URLS["ashe_res"], "geography": "LA, region, England",
        "cohort": "context", "period": latest, "latest_period": latest, "frequency": "Annual",
        "next_update": "Oct/Nov each year (provisional), revised the following year",
        "access": "API",
        "quality": "Accredited official statistics from a 1% sample of HMRC PAYE records (employer-"
                   "reported). `ci` is an approximate 95% half-width derived from the Nomis "
                   "coefficient of variation (attrs.cv_pct): 1.96 x CV x value.",
        "limitations": "Latest year is provisional and revised a year later. Employees only (no "
                       "self-employed). Estimates with CV > 20% are suppressed by ONS (null, "
                       "suppressed). Residence vs workplace gap indicates commuting to higher-paid "
                       "jobs elsewhere (e.g. London). No BEDS total (medians cannot be summed).",
        "indicators": inds, "dataset_code": "NM_30_1 (resident), NM_99_1 (workplace)",
    }
    return meta, rows


# --------------------------------------------------------------------------
# 6. BRES employees by industry (NM_189_1) and 7. jobs density (NM_57_1)
# --------------------------------------------------------------------------
KEY_SECTORS = {  # indicator suffix -> (Nomis industry code, label)
    "accom_food": ("150994953", "Accommodation & food services (I)"),
    "arts_rec": ("150994962", "Arts, entertainment & recreation (R)"),
    "construction": ("150994950", "Construction (F)"),
    "retail": ("163577863", "Retail (part G)"),
    "transport": ("150994952", "Transport & storage (H)"),
    "sports_amuse": ("146800733", "Sports, amusement & recreation (division 93)"),
    "accommodation": ("146800695", "Accommodation (division 55)"),
    "food_bev": ("146800696", "Food & beverage service (division 56)"),
}
TOTAL_IND = "37748736"
BROAD = [str(163577857 + i) for i in range(18)]


def build_bres():
    inds_param = ",".join([TOTAL_IND] + [v[0] for v in KEY_SECTORS.values()] + BROAD)
    raw = nomis("bres_sectors", "NM_189_1", geography=GEO_PARAM, date="latestMINUS4-latest",
                industry=inds_param, employment_status="1", measure="1", measures="20100",
                select="date_name,geography_code,industry,industry_name,obs_value,obs_status")
    v, names, years = {}, {}, set()
    for x in raw:
        v[(x["GEOGRAPHY_CODE"], x["DATE_NAME"], x["INDUSTRY"])] = num(x["OBS_VALUE"])
        names[x["INDUSTRY"]] = x["INDUSTRY_NAME"]
        years.add(x["DATE_NAME"])
    years = sorted(years)
    latest = years[-1]
    # sanity: check division codes resolved to the intended divisions
    for suf, (code, _) in KEY_SECTORS.items():
        if code not in names:
            raise RuntimeError(f"BRES industry {code} ({suf}) missing")
    for k in ("sports_amuse", "accommodation", "food_bev"):
        print(f"  BRES {k}: {names[KEY_SECTORS[k][0]]}")
    geos = list(GEOS) + ["BEDS"]

    def val(code, y, i):
        if code == "BEDS":
            vals = [v.get((c, y, i)) for c in LAS]
            return None if None in vals else sum(vals)
        return v.get((code, y, i))

    rows = []
    for y in years:
        eng_tot = val("E92000001", y, TOTAL_IND)
        for code in geos:
            tot = val(code, y, TOTAL_IND)
            rows.append(row(code, "bres_emp_total", tot, y, series="annual"))
            for suf, (ic, _) in KEY_SECTORS.items():
                c = val(code, y, ic)
                share = 100 * c / tot if c is not None and tot else None
                e = val("E92000001", y, ic)
                lq = (c / tot) / (e / eng_tot) if c is not None and tot and e and eng_tot else None
                rows.append(row(code, f"bres_emp_{suf}", c, y, series="annual"))
                rows.append(row(code, f"bres_share_{suf}", r1(share, 2), y, num=c, den=tot,
                                series="annual"))
                rows.append(row(code, f"bres_lq_{suf}", r1(lq, 2), y, series="annual"))
    for code in geos:  # full broad-group profile, latest year
        tot = val(code, latest, TOTAL_IND)
        eng_tot = val("E92000001", latest, TOTAL_IND)
        for ic in BROAD:
            c = val(code, latest, ic)
            e = val("E92000001", latest, ic)
            lq = (c / tot) / (e / eng_tot) if c is not None and tot and e else None
            b = names[ic]
            rows.append(row(code, "bres_emp_by_group", c, latest, breakdown=b))
            rows.append(row(code, "bres_lq_by_group", r1(lq, 2), latest, breakdown=b))
    inds = [ind("bres_emp_total", "Employees, all industries", "count", "context", "neutral",
                "BRES employee jobs located in the area (workplace-based), all industries.")]
    for suf, (_, lab) in KEY_SECTORS.items():
        inds += [
            ind(f"bres_emp_{suf}", f"Employees: {lab}", "count", "context", "neutral",
                f"BRES employee jobs in {lab}, workplace-based."),
            ind(f"bres_share_{suf}", f"Share of employees: {lab}", "percent", "context",
                "neutral", f"{lab} employees as % of all employees in the area."),
            ind(f"bres_lq_{suf}", f"Location quotient: {lab}", "ratio", "context", "neutral",
                f"Area share of employees in {lab} divided by England share (>1 = "
                "over-represented). Computed here from rounded counts."),
        ]
    inds += [
        ind("bres_emp_by_group", "Employees by broad industrial group", "count", "context",
            "neutral", "Latest-year BRES employees for each of the 18 ONS broad industrial "
            "groups (breakdown = group)."),
        ind("bres_lq_by_group", "Location quotient by broad industrial group", "ratio",
            "context", "neutral", "Area share / England share for each broad group (breakdown)."),
    ]
    meta = {
        "title": "Business Register and Employment Survey: employees by industry",
        "publisher": "Office for National Statistics (via Nomis)",
        "source_url": "https://www.nomisweb.co.uk/sources/bres",
        "api_url": API_URLS["bres_sectors"], "geography": "LA, region, England, Bedfordshire total",
        "cohort": "context", "period": latest, "latest_period": latest, "frequency": "Annual",
        "next_update": "Autumn each year (latest year provisional)", "access": "API",
        "quality": "Accredited official statistics from a business survey of ~80,000 units, "
                   "benchmarked to the IDBR; open-access LA figures are rounded (nearest 5 below "
                   "100, otherwise to the nearest 250 / 500 / 1,000 depending on size). Includes "
                   "units registered for PAYE only. Latest year provisional.",
        "limitations": "Employee jobs, not people; excludes self-employed (significant in "
                       "construction) and HM Forces. Location in which the job is recorded can "
                       "reflect head-office/reporting unit allocation. Rounding means small "
                       "sectors (e.g. division 93) and year-on-year changes are coarse; location "
                       "quotients and BEDS totals are computed from rounded counts. "
                       "'Retail' is a broad-group subset of section G.",
        "indicators": inds, "dataset_code": "NM_189_1",
    }
    return meta, rows


def build_jobs_density(pop, mye_years):
    raw = nomis("jobs_density", "NM_57_1", geography=GEO_PARAM, date="latestMINUS5-latest",
                item="1,3", measures="20100",
                select="date_name,geography_code,item,obs_value,obs_status")
    v = {(x["GEOGRAPHY_CODE"], x["DATE_NAME"], x["ITEM"]): num(x["OBS_VALUE"]) for x in raw}
    years = sorted({k[1] for k in v})
    rows = []
    for y in years:
        for code in GEOS:
            rows.append(row(code, "jobs_total", v.get((code, y, "1")), y, series="annual"))
            rows.append(row(code, "jobs_density", v.get((code, y, "3")), y, series="annual"))
        jobs = [v.get((c, y, "1")) for c in LAS]
        jt = None if None in jobs else sum(jobs)
        rows.append(row("BEDS", "jobs_total", jt, y, series="annual"))
        py = int(y)
        if py in mye_years and jt is not None:
            p = mye_band_beds(pop, py, "pop_16_64")
            rows.append(row("BEDS", "jobs_density", r1(jt / p, 2), y, num=jt, den=p,
                            series="annual"))
    latest = years[-1]
    inds = [
        ind("jobs_total", "Total jobs (workplace)", "count", "context", "neutral",
            "ONS total jobs located in the area: employees + self-employed + government-"
            "supported trainees + HM Forces."),
        ind("jobs_density", "Jobs density", "ratio", "context", "neutral",
            "Total jobs / resident population aged 16-64. <1 means fewer local jobs than "
            "working-age residents (net out-commuting). BEDS value computed here."),
    ]
    meta = {
        "title": "Jobs density and total jobs",
        "publisher": "Office for National Statistics (via Nomis)",
        "source_url": "https://www.nomisweb.co.uk/sources/jd",
        "api_url": API_URLS["jobs_density"], "geography": "LA, region, England, Bedfordshire total",
        "cohort": "context", "period": latest, "latest_period": latest, "frequency": "Annual",
        "next_update": "Annual (usually early in the year)", "access": "API",
        "quality": "Official statistics combining BRES, APS (self-employment), DWP and MoD data; "
                   "rounded to nearest 1,000 jobs.",
        "limitations": "Jobs are counted at the workplace, people may hold more than one job. "
                       "Self-employment component comes from APS and carries sampling error. "
                       "Denominator is the mid-year estimate of 16-64 population.",
        "indicators": inds, "dataset_code": "NM_57_1",
    }
    return meta, rows


# --------------------------------------------------------------------------
# 8. Census 2021 economic activity by age (ONS custom dataset API)
# --------------------------------------------------------------------------
CENSUS_CATS = {  # indicator suffix -> economic_activity_status_12a option ids
    "employed": ["1", "2", "3", "5"],
    "unemployed": ["4", "6"],
    "inact_retired": ["7"], "inact_student": ["8"], "inact_home_family": ["9"],
    "inact_lt_sick": ["10"], "inact_other": ["11"],
    "inact_total": ["7", "8", "9", "10", "11"],
    "pop": ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10", "11"],
}


def census_query(ds_id, age_dim):
    out = {}
    for atype, codes in (("ltla", list(LAS)), ("rgn", ["E12000006"]), ("ctry", ["E92000001"])):
        url = (f"{ONS_CUSTOM}?area-type={atype},{','.join(codes)}"
               f"&dimensions=economic_activity_status_12a,{age_dim}")
        j = json.loads(get(url, ds_id, "json"))
        if j.get("blocked_areas"):
            print(f"  WARNING census blocked areas: {j['blocked_areas']}")
        for o in j["observations"]:
            d = {x["dimension_id"]: (x["option_id"], x["option"]) for x in o["dimensions"]}
            area = d[atype][0]
            out[(area, d["economic_activity_status_12a"][0], d[age_dim][1])] = o["observation"]
    return out


def build_census_age_activity():
    bands6 = {"Aged 16 to 24 years": "age 16-24", "Aged 25 to 34 years": "age 25-34",
              "Aged 35 to 49 years": "age 35-49", "Aged 50 to 64 years": "age 50-64"}
    bands7 = {"Aged 16 to 17 years": "age 16-17", "Aged 18 to 20 years": "age 18-20",
              "Aged 21 to 24 years": "age 21-24"}
    d6 = census_query("census_age_activity", "resident_age_6a")
    d7 = census_query("census_age_activity", "resident_age_7a")
    codes = list(GEOS)

    def cnt(d, code, opts, band_labels):
        if code == "BEDS":
            return sum(cnt(d, c, opts, band_labels) for c in LAS)
        return sum(d[(code, o, b)] for o in opts for b in band_labels)

    groups = [(d6, [k], lab) for k, lab in bands6.items()]
    groups.append((d6, ["Aged 25 to 34 years", "Aged 35 to 49 years", "Aged 50 to 64 years"],
                   "age 25-64"))
    groups.append((d6, list(bands6), "age 16-64"))
    groups += [(d7, [k], lab) for k, lab in bands7.items()]
    groups.append((d7, ["Aged 18 to 20 years", "Aged 21 to 24 years"], "age 18-24"))
    rows = []
    period = "Census 2021"
    for code in codes + ["BEDS"]:
        for d, bl, lab in groups:
            pop = cnt(d, code, CENSUS_CATS["pop"], bl)
            for suf, opts in CENSUS_CATS.items():
                c = cnt(d, code, opts, bl)
                rows.append(row(code, f"census_{suf}", c, period, breakdown=lab))
                if suf != "pop":
                    rows.append(row(code, f"census_{suf}_pct", r1(100 * c / pop), period,
                                    num=c, den=pop, breakdown=lab))
    labels = {
        "employed": ("In employment", "neutral", "context"),
        "unemployed": ("Unemployed (incl. full-time students seeking work)", "higher_is_worse",
                       "18-24,25+ inactive"),
        "inact_retired": ("Inactive: retired", "neutral", "25+ inactive"),
        "inact_student": ("Inactive: student", "neutral", "16-19,18-24"),
        "inact_home_family": ("Inactive: looking after home or family", "neutral", "25+ inactive"),
        "inact_lt_sick": ("Inactive: long-term sick or disabled", "higher_is_worse", "25+ inactive"),
        "inact_other": ("Inactive: other", "neutral", "25+ inactive"),
        "inact_total": ("Economically inactive (all reasons)", "neutral", "25+ inactive,18-24"),
    }
    inds = [ind("census_pop", "Usual residents in age band", "count", "context", "neutral",
                "Census 2021 usual residents in the age band (breakdown).")]
    for suf, (lab, pol, coh) in labels.items():
        inds.append(ind(f"census_{suf}", lab, "count", coh, pol,
                        f"Census 2021 residents: {lab.lower()}, by age band (breakdown)."))
        inds.append(ind(f"census_{suf}_pct", f"{lab} (% of age band)", "percent", coh, pol,
                        f"{lab} as % of all usual residents in the age band."))
    url_list = API_URLS["census_age_activity"]
    meta = {
        "title": "Census 2021: economic activity status by age (incl. reasons for inactivity)",
        "publisher": "Office for National Statistics (Create a custom dataset API)",
        "source_url": "https://www.ons.gov.uk/datasets/create",
        "api_url": url_list, "geography": "LA, region, England, Bedfordshire total",
        "cohort": "25+ inactive, 18-24, 16-19", "period": "Census 2021 (21 March 2021)",
        "latest_period": "Census 2021", "frequency": "Decennial",
        "next_update": "Next census 2031 (subject to ONS decision)", "access": "API",
        "quality": "Accredited official statistics; full population count (no sampling error) "
                   "with ~97% response. Cell-key perturbation adds small noise to each cell.",
        "limitations": "No Nomis table cross-classifies the 12-category economic activity status "
                       "(reasons for inactivity) by age at LA level (RM024 has only 7 statuses), so "
                       "this uses the ONS custom-dataset API (economic_activity_status_12a x "
                       "resident_age_6a / 7a). Taken on 21 March 2021 during a lockdown: furloughed "
                       "workers were counted as employed, students may have been at family homes, "
                       "and unemployment/inactivity patterns may differ from today. 'Unemployed' "
                       "includes full-time students looking for work. Bands sum cells, so small "
                       "perturbation noise accumulates; totals can differ slightly from other "
                       "Census tables.",
        "indicators": inds, "dataset_code": "ONS custom: economic_activity_status_12a x resident_age_6a, resident_age_7a",
    }
    return meta, rows


# --------------------------------------------------------------------------
# 9. Census 2021 origin-destination (ODWP01EW, LTLA)
# --------------------------------------------------------------------------
def load_centroids():
    j = json.loads(get(CENTROIDS_URL, "census_od", "json"))
    return {f["attributes"]["LAD21CD"]: (f["attributes"]["LAD21NM"],
                                         round(f["attributes"]["LAT"], 4),
                                         round(f["attributes"]["LONG"], 4))
            for f in j["features"]}


def build_census_od(top_n=25):
    API_URLS.setdefault("census_od", []).append(OD_ZIP)
    zbytes = fetch(OD_ZIP, "odwp01ew.zip")
    z = zipfile.ZipFile(io.BytesIO(zbytes))
    flows = {}  # (res, wp) -> commuters (category 3)
    home = {}   # res -> mainly home / no fixed place (category 1)
    names = {}
    with z.open("ODWP01EW_LTLA.csv") as f:
        for x in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig")):
            res, wp = x["Lower tier local authorities code"], x["LTLA of workplace code"]
            names[res] = x["Lower tier local authorities label"]
            cat, n = x["Place of work indicator (4 categories) code"], int(x["Count"])
            if cat == "3":
                flows[(res, wp)] = flows.get((res, wp), 0) + n
                names[wp] = x["LTLA of workplace label"]
            elif cat == "1":
                home[res] = home.get(res, 0) + n
    cent = load_centroids()
    used = set(LAS)
    rows = []

    def ll(c):
        _, lat, lon = cent.get(c, (None, None, None))
        return lat, lon

    def flow_row(focus, indicator, other, n, rank, direction, origin, dest):
        olat, olon = ll(origin)
        dlat, dlon = ll(dest)
        used.update(c for c in (origin, dest) if c != "BEDS")
        r = row(focus, indicator, n, "Census 2021",
                breakdown=("from " if direction == "in" else "to ") + names.get(other, other))
        r["attrs"] = {"rank": rank, "other_code": other, "other_name": names.get(other, other),
                      "origin_code": origin, "origin_name": names.get(origin, origin),
                      "origin_lat": olat, "origin_lon": olon, "dest_code": dest,
                      "dest_name": names.get(dest, dest), "dest_lat": dlat, "dest_lon": dlon,
                      "same_la": origin == dest}
        return r

    beds = set(LAS)
    for focus in list(LAS) + ["BEDS"]:
        targets = beds if focus == "BEDS" else {focus}
        # inflow: workers whose workplace is in focus, by residence LA
        inflow = {}
        for (res, wp), n in flows.items():
            if wp in targets:
                inflow[res] = inflow.get(res, 0) + n
        outflow = {}
        for (res, wp), n in flows.items():
            if res in targets and wp not in ("888888888", "999999999", "-8"):
                outflow[wp] = outflow.get(wp, 0) + n
        tin = sum(inflow.values())
        tout = sum(outflow.values())
        for direction, d, ind_id, tot in (("in", inflow, "od_inflow_by_residence", tin),
                                          ("out", outflow, "od_outflow_by_workplace", tout)):
            ranked = sorted(d.items(), key=lambda kv: -kv[1])[:top_n]
            shown = 0
            for rank, (other, n) in enumerate(ranked, 1):
                shown += n
                if focus == "BEDS":
                    o, de = (other, "BEDS") if direction == "in" else ("BEDS", other)
                else:
                    o, de = (other, focus) if direction == "in" else (focus, other)
                r = flow_row(focus, ind_id, other, n, rank, direction, o, de)
                r["den"] = tot
                if focus == "BEDS":  # BEDS end of the line: Kempston-ish centroid of 3 UAs
                    pts = [cent[c] for c in LAS]
                    lat = round(sum(p[1] for p in pts) / 3, 4)
                    lon = round(sum(p[2] for p in pts) / 3, 4)
                    key = "dest" if direction == "in" else "origin"
                    r["attrs"][f"{key}_lat"], r["attrs"][f"{key}_lon"] = lat, lon
                    r["attrs"][f"{key}_name"] = BEDS["name"]
                    r["attrs"]["same_la"] = other in beds
                rows.append(r)
            rest = tot - shown
            rr = row(focus, ind_id, rest, "Census 2021", breakdown="all other areas", den=tot)
            rr["attrs"] = {"rank": None, "other_code": None}
            rows.append(rr)
        same = sum(inflow.get(c, 0) for c in targets)
        hw = sum(home.get(c, 0) for c in targets)
        rows += [
            row(focus, "od_workplace_commuters", tin, "Census 2021"),
            row(focus, "od_resident_commuters", tout, "Census 2021"),
            row(focus, "od_home_or_no_fixed_place", hw, "Census 2021"),
            row(focus, "od_net_commuting", tin - tout, "Census 2021"),
            row(focus, "od_self_containment_pct", r1(100 * same / tout), "Census 2021",
                num=same, den=tout),
            row(focus, "od_jobs_filled_by_incommuters_pct", r1(100 * (tin - same) / tin),
                "Census 2021", num=tin - same, den=tin),
        ]
    # Comparator context for England/region is not meaningful for flows; LA rows only.
    centroids = {c: {"name": names.get(c, cent[c][0]), "lat": cent[c][1], "lon": cent[c][2]}
                 for c in sorted(used) if c in cent}
    missing = sorted(c for c in used if c not in cent)
    if missing:
        print(f"  WARNING no centroid for {missing}")
    inds = [
        ind("od_inflow_by_residence", "Workers commuting in, by home LA", "count",
            "context", "neutral",
            "People whose workplace is in the focus area, by LA of usual residence (top 25 + "
            "'all other areas'); includes those living and working in the same LA "
            "(attrs.same_la). Excludes home-workers. attrs give origin/dest lat/lon for flow maps."),
        ind("od_outflow_by_workplace", "Residents commuting out, by workplace LA", "count",
            "context", "neutral",
            "Employed residents of the focus area travelling to a workplace, by LA of workplace "
            "(top 25 + remainder); excludes home-workers, offshore and outside-UK."),
        ind("od_workplace_commuters", "Workers travelling to a workplace in the area", "count",
            "context", "neutral", "All people travelling to a workplace in the area (any origin)."),
        ind("od_resident_commuters", "Residents travelling to a workplace", "count", "context",
            "neutral", "Employed residents travelling to a UK workplace (any destination)."),
        ind("od_home_or_no_fixed_place", "Residents mainly working from home / no fixed place",
            "count", "context", "neutral",
            "Employed residents mainly working at or from home or with no fixed place (high in "
            "March 2021 lockdown)."),
        ind("od_net_commuting", "Net commuting (in minus out)", "count", "context", "neutral",
            "Workplace commuters minus resident commuters; negative = net out-commuting."),
        ind("od_self_containment_pct", "Self-containment", "percent", "context", "neutral",
            "% of resident commuters whose workplace is in the same area."),
        ind("od_jobs_filled_by_incommuters_pct", "Workplace filled by in-commuters", "percent",
            "context", "neutral", "% of people commuting to a workplace in the area who live "
            "outside it."),
    ]
    meta = {
        "title": "Census 2021 origin-destination: residence vs place of work (LA)",
        "publisher": "Office for National Statistics (Nomis bulk download)",
        "source_url": "https://www.nomisweb.co.uk/sources/census_2021_od",
        "api_url": API_URLS["census_od"], "geography": "LA (2021 LTLAs), Bedfordshire total",
        "cohort": "context", "period": "Census 2021 (21 March 2021)",
        "latest_period": "Census 2021", "frequency": "Decennial",
        "next_update": "Next census 2031 (subject to ONS decision)", "access": "CSV download",
        "quality": "Census 2021 table ODWP01EW (LTLA level), accredited official statistics; full "
                   "count with cell-key perturbation. Centroids are ONS Dec-2021 LAD BUC label "
                   "points (LAT/LONG) from the ONS Open Geography Portal.",
        "limitations": "Census day (21 March 2021) fell in a national lockdown with ~1/3 of "
                       "workers at home and many furloughed (furloughed workers still reported a "
                       "workplace): commuting volumes are understated vs today and home-workers are "
                       "excluded from flows. Small flows are noisy due to perturbation. LA codes "
                       "are 2021 LTLAs (pre-2023 Cumbria/Somerset/N Yorks reorganisation). BEDS "
                       "rows treat the three UAs as one area; its flow end uses the mean of the "
                       "three UA centroids.",
        "indicators": inds, "dataset_code": "ODWP01EW (LTLA)",
    }
    return meta, rows, {"centroids": centroids}


# --------------------------------------------------------------------------
def main():
    summary = {}

    def do(ds_id, built):
        meta, rows = built[0], built[1]
        extra = built[2] if len(built) > 2 else None
        save(ds_id, meta, rows, extra)
        summary[ds_id] = (len(rows), meta.get("latest_period"))

    pop, mye_years = load_mye()
    do("pop_mye", build_pop_mye(pop, mye_years))
    do("pop_snpp", build_pop_snpp())
    do("aps", build_aps())
    do("claimant", build_claimant(pop, mye_years))
    do("ashe_res", build_ashe())
    do("bres_sectors", build_bres())
    do("jobs_density", build_jobs_density(pop, mye_years))
    do("census_age_activity", build_census_age_activity())
    do("census_od", build_census_od())
    print("\nSummary:")
    for k, (n, p) in summary.items():
        print(f"  {k:22s} {n:6d} rows  latest {p}")


if __name__ == "__main__":
    main()
