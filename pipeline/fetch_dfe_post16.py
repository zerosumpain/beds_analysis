"""DfE Explore Education Statistics (EES): post-16 participation, NEET,
apprenticeships, FE & skills, destinations, L2/L3 by 19, care leavers, EHCPs.

Sources (all DfE, OGL v3):
- EES public API (api.education.gov.uk/statistics/v1) where the data set is
  published there: KS4 + 16-18 destinations, EHC plans caseload.
- Otherwise EES data-catalogue CSV downloads (stable per data-set-file id,
  served from content.explore-education-statistics.service.gov.uk/api/
  data-set-files/<id>/download). Several are very large (100-500 MB), so they
  are streamed and filtered to Bedfordshire / East of England / England rows,
  and only the filtered extract is cached in data/raw/.

Run: cd pipeline && python3 fetch_dfe_post16.py
"""
import csv
import io
import json
import re
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict

from common import LAS, RAW, UA, save

EES = "https://explore-education-statistics.service.gov.uk"
CONTENT = "https://content.explore-education-statistics.service.gov.uk/api/data-set-files"
API = "https://api.education.gov.uk/statistics/v1"
REG = "E12000006"
ENG = "E92000001"
OLD_LA = {"822": "E06000055", "823": "E06000056", "821": "E06000032"}
BEDS = ("BEDS", "Bedfordshire (3 UAs)", "county")
PCON_RE = re.compile(r"bedford|luton", re.I)
SUPPRESS = {"c", "x", "low", "z", ":", "..", "u", "k", "*", "~", "-", ""}

csv.field_size_limit(10**8)


# --------------------------------------------------------------------------
# Download helpers
# --------------------------------------------------------------------------
def csv_url(file_id):
    return f"{CONTENT}/{file_id}/download"


def keep_geo(r):
    """Return (code, name, level) for rows we keep, else None."""
    gl = r.get("geographic_level", "")
    if gl == "National":
        return (ENG, "England", "country")
    if gl == "Regional":
        return (REG, "East of England", "region") if r.get("region_code") == REG else None
    if gl == "Local authority":
        code = r.get("new_la_code") or OLD_LA.get(r.get("old_la_code", ""))
        if code not in LAS:
            code = OLD_LA.get(r.get("old_la_code", ""))
        return (code, LAS[code], "LA") if code in LAS else None
    if gl == "Local authority district":
        code = r.get("lad_code")
        return (code, LAS[code], "LA") if code in LAS else None
    if gl == "Parliamentary constituency":
        name = r.get("pcon_name", "")
        return (r.get("pcon_code"), name, "PCON") if PCON_RE.search(name) else None
    return None


def filtered_csv(file_id, cache_name):
    """Stream an EES CSV, keep only our geographies, cache the extract."""
    RAW.mkdir(parents=True, exist_ok=True)
    p = RAW / cache_name
    if not p.exists():
        url = csv_url(file_id)
        print(f"  downloading {url} ...", flush=True)
        t0 = time.time()
        last = None
        for attempt in range(3):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": UA})
                with urllib.request.urlopen(req, timeout=600) as resp:
                    text = io.TextIOWrapper(resp, encoding="utf-8-sig", errors="replace", newline="")
                    rd = csv.DictReader(text)
                    tmp = p.with_suffix(".part")
                    n = k = 0
                    with tmp.open("w", newline="") as fh:
                        w = csv.DictWriter(fh, fieldnames=rd.fieldnames)
                        w.writeheader()
                        for r in rd:
                            n += 1
                            if keep_geo(r):
                                w.writerow(r)
                                k += 1
                    tmp.rename(p)
                print(f"  {cache_name}: kept {k}/{n} rows in {time.time()-t0:.0f}s", flush=True)
                break
            except Exception as e:  # noqa: BLE001
                last = e
                time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(f"download failed {url}: {last}")
    with p.open(newline="") as fh:
        return list(csv.DictReader(fh))


def api_query(ds_id, body, cache_name):
    """POST a query to the EES public API, following pagination."""
    p = RAW / cache_name
    if p.exists():
        return json.loads(p.read_text())
    url = f"{API}/data-sets/{ds_id}/query"
    out, page = [], 1
    while True:
        b = dict(body, page=page, pageSize=10000)
        req = urllib.request.Request(url, data=json.dumps(b).encode(), headers={
            "Content-Type": "application/json", "Accept": "application/json", "User-Agent": UA})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(req, timeout=300) as r:
                    d = json.load(r)
                break
            except urllib.error.HTTPError as e:
                msg = e.read().decode()[:800]
                if e.code < 500:
                    raise RuntimeError(f"API {e.code}: {msg}") from e
                time.sleep(5 * (attempt + 1))
        else:
            raise RuntimeError(f"API failed {url}")
        out.extend(d["results"])
        if page >= d["paging"]["totalPages"]:
            break
        page += 1
    RAW.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out))
    return out


def api_meta(ds_id):
    p = RAW / f"ees_meta_{ds_id}.json"
    if not p.exists():
        req = urllib.request.Request(f"{API}/data-sets/{ds_id}/meta", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r:
            p.write_bytes(r.read())
    return json.loads(p.read_text())


# --------------------------------------------------------------------------
# Row helpers
# --------------------------------------------------------------------------
def num(v):
    """Parse an EES value; return (value, suppressed)."""
    s = (v or "").strip().replace(",", "")
    if s.lower() in SUPPRESS:
        return None, s != "" and s.lower() not in ("z",)
    try:
        f = float(s)
    except ValueError:
        return None, True
    return (int(f) if f.is_integer() and "." not in s else round(f, 2)), False


def ay(tp):
    """'202425' -> '2024/25'; '2024/2025' -> '2024/25'; '2025' -> '2025'."""
    tp = str(tp)
    if len(tp) == 6 and tp.isdigit():
        return f"{tp[:4]}/{tp[4:]}"
    m = re.match(r"^(\d{4})/(\d{2})(\d{2})$", tp)
    if m:
        return f"{m.group(1)}/{m.group(3)}"
    return tp


def mkrow(geo, ind, value, period, breakdown=None, suppressed=False, num_=None, den=None):
    code, name, level = geo
    r = {"code": code, "name": name, "level": level, "indicator": ind, "value": value,
         "period": period, "ci": None, "num": num_, "den": den, "breakdown": breakdown}
    if value is None:
        r["suppressed"] = bool(suppressed)
    return r


def add_beds_totals(rows, count_inds, rate_specs=()):
    """Append BEDS county rows: sums of counts across the 3 LAs (only when all
    three are present and unsuppressed), and rates recomputed from summed
    num/den for rate_specs = [(rate_ind, num_ind, den_ind, scale)]."""
    groups = defaultdict(dict)
    for r in rows:
        if r["level"] == "LA" and r["code"] in LAS:
            groups[(r["indicator"], r["period"], r["breakdown"])][r["code"]] = r["value"]
    out = []
    for (ind, per, bd), vals in groups.items():
        if ind in count_inds and len(vals) == 3 and all(v is not None for v in vals.values()):
            out.append(mkrow(BEDS, ind, sum(vals.values()), per, bd))
    for rate, n_ind, d_ind, scale in rate_specs:
        for (ind, per, bd), vals in groups.items():
            if ind != n_ind:
                continue
            dv = groups.get((d_ind, per, bd), {})
            if len(vals) == 3 and len(dv) == 3 and all(v is not None for v in list(vals.values()) + list(dv.values())):
                n, d = sum(vals.values()), sum(dv.values())
                if d:
                    out.append(mkrow(BEDS, rate, round(scale * n / d, 1), per, bd, num_=n, den=d))
    rows.extend(out)
    return rows


def ind(id_, label, unit, cohort, polarity, desc):
    return {"id": id_, "label": label, "unit": unit, "cohort": cohort,
            "polarity": polarity, "description": desc}


def latest(rows):
    pers = sorted({r["period"] for r in rows})
    return pers[-1] if pers else None


# --------------------------------------------------------------------------
# 1. NEET / participation age 16-17 by LA
# --------------------------------------------------------------------------
NEET_PUB = "participation-in-education-training-and-neet-age-16-to-17-by-local-authority"
NEET_FILES = {
    "type": "a9b8ebe6-1d51-41c3-babe-ee7d16ea5f78",   # Participation by type
    "neet": "a7bc111a-9503-40df-99fa-764fcb13a2e9",   # NEET by characteristics
    "part": "e1f4011a-ed67-408e-8b7b-076a44a6cc8c",   # Participation by characteristics
}


def neet_period(tp):
    # EES labels the end-of-year tracking with the calendar year of the
    # Dec-Feb averaging window's end: "2026" = average of Dec 2025, Jan & Feb 2026.
    y = int(tp)
    return f"end-{y-1} (Dec {y-1}-Feb {y} avg)"


def build_neet():
    rows = []
    t = filtered_csv(NEET_FILES["type"], "dfe_neet_participation_by_type.csv")
    years = sorted({int(r["time_period"]) for r in t})[-6:]
    type_map = {
        "Full-time education": "dfe_neet_pct_fte",
        "Apprenticeship": "dfe_neet_pct_apprenticeship",
        "Work based learning": "dfe_neet_pct_wbl",
        "Part-time education": "dfe_neet_pct_pte",
        "Employment combined with study": "dfe_neet_pct_emp_study",
        "Other participation type": "dfe_neet_pct_other_et",
        "TOTAL participating in education and training": "dfe_neet_pct_participating",
        "TOTAL meeting the duty to participate": "dfe_neet_pct_meeting_duty",
    }
    seen_types = defaultdict(int)
    for r in t:
        if int(r["time_period"]) not in years:
            continue
        seen_types[(r["participation_grouping"], r["participation_type"])] += 1
        pt = r["participation_type"]
        if r["participation_grouping"] == "Meeting the duty to participate" and pt != "TOTAL meeting the duty to participate":
            continue
        geo = keep_geo(r)
        per = neet_period(r["time_period"])
        if pt in type_map:
            v, s = num(r["percent"])
            c, _ = num(r["count"])
            rows.append(mkrow(geo, type_map[pt], v, per, "age 16-17", s, num_=c))
        elif pt == "cohort":
            v, s = num(r["count"])
            rows.append(mkrow(geo, "dfe_neet_cohort", v, per, "age 16-17", s))
    neet = filtered_csv(NEET_FILES["neet"], "dfe_neet_neet_characteristics.csv")
    for r in neet:
        if int(r["time_period"]) not in years:
            continue
        geo = keep_geo(r)
        per = neet_period(r["time_period"])
        grp, ch, age = r["characteristic_grouping"], r["characteristic"], r["age"]
        age_bd = "age 16-17" if age == "16 to 17" else f"age {age}"
        bd = age_bd if grp == "Total" else f"{age_bd}; {grp}: {ch}"
        # Keep all ages for Total; characteristic splits only for 16-17 combined.
        if grp != "Total" and age != "16 to 17":
            continue
        for col, iid in (("neet_nk_percent", "dfe_neet_pct_neet_nk"), ("neet_percent", "dfe_neet_pct_neet"),
                         ("nk_percent", "dfe_neet_pct_not_known")):
            v, s = num(r[col])
            rows.append(mkrow(geo, iid, v, per, bd, s))
        for col, iid in (("avg_neet_nk_count", "dfe_neet_n_neet_nk"), ("avg_neet_count", "dfe_neet_n_neet"),
                         ("avg_nk_count", "dfe_neet_n_not_known")):
            v, s = num(r[col])
            rows.append(mkrow(geo, iid, v, per, bd, s))
        if grp == "Total":
            v, s = num(r["avg_cohort_count"])
            rows.append(mkrow(geo, "dfe_neet_n_cohort_avg", v, per, bd, s))
    part = filtered_csv(NEET_FILES["part"], "dfe_neet_participation_characteristics.csv")
    for r in part:
        if int(r["time_period"]) not in years:
            continue
        grp, age = r["characteristic_grouping"], r["age"]
        if grp == "Total" and age == "16 to 17":
            continue  # already covered by participation-by-type headline
        if grp != "Total" and age != "16 to 17":
            continue
        age_bd = "age 16-17" if age == "16 to 17" else f"age {age}"
        bd = age_bd if grp == "Total" else f"{age_bd}; {grp}: {r['characteristic']}"
        v, s = num(r["total_in_education_and_training_percent"])
        c, _ = num(r["total_in_education_and_training_count"])
        rows.append(mkrow(keep_geo(r), "dfe_neet_pct_participating", v, neet_period(r["time_period"]), bd, s, num_=c))
    add_beds_totals(rows, {"dfe_neet_n_neet_nk", "dfe_neet_n_neet", "dfe_neet_n_not_known",
                           "dfe_neet_n_cohort_avg", "dfe_neet_cohort"},
                    [("dfe_neet_pct_neet_nk", "dfe_neet_n_neet_nk", "dfe_neet_n_cohort_avg", 100),
                     ("dfe_neet_pct_neet", "dfe_neet_n_neet", "dfe_neet_n_cohort_avg", 100),
                     ("dfe_neet_pct_not_known", "dfe_neet_n_not_known", "dfe_neet_n_cohort_avg", 100)])
    C = "16-19"
    meta = {
        "title": "Participation in education, training and NEET age 16 to 17 by local authority",
        "publisher": "Department for Education",
        "source_url": f"{EES}/find-statistics/{NEET_PUB}",
        "api_url": [csv_url(v) for v in NEET_FILES.values()],
        "geography": "LA, region, England (+ Bedfordshire 3-UA total for counts and recomputed rates)",
        "cohort": C,
        "period": latest(rows),
        "latest_period": latest(rows),
        "frequency": "Annual",
        "next_update": "Summer 2027 (end-2026 figures)",
        "access": "CSV download",
        "quality": ("Official statistics from local authority Client Caseload Information System (CCIS) "
                    "tracking of academic-age 16-17 residents; 'NEET' and 'not known' are averages of the "
                    "Dec, Jan and Feb monthly snapshots (so LA counts can be fractional), participation is at end of December. Census of "
                    "LA records (no sampling error) but quality depends on each LA's tracking."),
        "limitations": ("LA NEET rates are only comparable when 'activity not known' rates are similar: an LA "
                        "with weak tracking shows low NEET but high not-known, so the combined 'NEET or not "
                        "known' rate is the headline. National/regional counts are rounded to the nearest 10 by DfE; "
                        "LA figures are unrounded (percentages to 2 dp); small characteristic cells suppressed (null, suppressed=true). Covers young "
                        "people resident in the LA (academic age 16-17, i.e. Years 12-13), not where they "
                        "study. Characteristic breakdowns (sex, ethnicity, SEND) only for ages 16-17 combined. "
                        "Period label: EES time_period 2026 = end-2025 tracking. Bedfordshire rows sum the "
                        "three UAs' rounded counts."),
        "indicators": [
            ind("dfe_neet_pct_neet_nk", "NEET or activity not known (%)", "percent", C, "higher_is_worse",
                "% of academic-age 16-17 residents NEET or whose activity is not known (Dec-Feb average)."),
            ind("dfe_neet_pct_neet", "NEET (%)", "percent", C, "higher_is_worse",
                "% of 16-17 year olds known to be not in education, employment or training."),
            ind("dfe_neet_pct_not_known", "Activity not known (%)", "percent", C, "higher_is_worse",
                "% of 16-17 cohort whose current activity the LA does not know (tracking quality)."),
            ind("dfe_neet_n_neet_nk", "NEET or not known (number)", "count", C, "higher_is_worse",
                "Number of 16-17 year olds NEET or not known (Dec-Feb average, rounded to 10)."),
            ind("dfe_neet_n_neet", "NEET (number)", "count", C, "higher_is_worse", "Number of 16-17s NEET."),
            ind("dfe_neet_n_not_known", "Activity not known (number)", "count", C, "higher_is_worse",
                "Number of 16-17s whose activity is not known."),
            ind("dfe_neet_n_cohort_avg", "Cohort known to LA (Dec-Feb average)", "count", C, "neutral",
                "Denominator for NEET/not known rates: 16-17 year olds tracked by the LA."),
            ind("dfe_neet_cohort", "Participation cohort (end Dec)", "count", C, "neutral",
                "Denominator for participation rates: academic-age 16-17 residents at end of December."),
            ind("dfe_neet_pct_participating", "Participating in education or training (%)", "percent", C,
                "higher_is_better", "% of 16-17s meeting the duty to participate (all education/training routes)."),
            ind("dfe_neet_pct_meeting_duty", "Meeting the duty to participate (%)", "percent", C,
                "higher_is_better", "% of 16-17s meeting the statutory duty to participate (RPA) at end of December."),
            ind("dfe_neet_pct_fte", "Full-time education (%)", "percent", C, "neutral",
                "% of 16-17s in full-time education (school sixth form, college, etc.)."),
            ind("dfe_neet_pct_apprenticeship", "Apprenticeship (%)", "percent", C, "higher_is_better",
                "% of 16-17s in an apprenticeship."),
            ind("dfe_neet_pct_wbl", "Work-based learning (%)", "percent", C, "neutral",
                "% of 16-17s in work-based learning (excluding apprenticeships)."),
            ind("dfe_neet_pct_pte", "Part-time education (%)", "percent", C, "neutral",
                "% of 16-17s in part-time education."),
            ind("dfe_neet_pct_emp_study", "Employment combined with study (%)", "percent", C, "neutral",
                "% of 16-17s in employment with accredited study."),
            ind("dfe_neet_pct_other_et", "Other participation type (%)", "percent", C, "neutral",
                "% of 16-17s in other education or training (e.g. custodial, re-engagement)."),
        ],
    }
    known = {i["id"] for i in meta["indicators"]}
    rows = [r for r in rows if r["indicator"] in known]
    print("  participation types seen:", sorted({k[1] for k in seen_types}))
    return save("dfe_neet", meta, rows)


# --------------------------------------------------------------------------
# 2. Apprenticeships
# --------------------------------------------------------------------------
APPS_PUB = "apprenticeships"
APPS_FILES = {
    "pop": "a7743194-48bc-4e04-9102-4b0177ff4a84",   # Geography Region/LA/LAD/PCON: age x level
    "ssa": "8ea0da62-6f42-4477-a2af-de4c3f1a8d56",   # Region & LAD: SSA, level, sex, ethnicity (2025/26 in-year)
    # Same table, full-year final versions from the previous two releases (superseded releases' files).
    "ssa_2425": "da55facf-4480-4474-a2de-fcdf00e5e83c",
    "ssa_2324": "a1cca8cf-2b7f-473c-a4a0-559bd2cb6b9e",
}
SSA_FOCUS = {
    "Retail and Commercial Enterprise": "retail_commercial",
    "Leisure, Travel and Tourism": "leisure_travel_tourism",
    "Construction, Planning and the Built Environment": "construction",
    "Engineering and Manufacturing Technologies": "engineering_manufacturing",
    "Business, Administration and Law": "business_admin_law",
    "Health, Public Services and Care": "health_public_care",
    "Information and Communication Technology": "ict",
}
AGE_BD = {"Under 19": "age under 19", "19-24": "age 19-24", "25+": "age 25+", "Total": None}
LEVEL_BD = {"Intermediate Apprenticeship": "Intermediate (L2)", "Advanced Apprenticeship": "Advanced (L3)",
            "Higher Apprenticeship": "Higher (L4+)", "Intermediate": "Intermediate (L2)",
            "Advanced": "Advanced (L3)", "Higher": "Higher (L4+)", "Total": None}


def apps_period(tp, latest_tp):
    p = ay(tp)
    return f"{p} (Aug-Apr, provisional)" if tp == latest_tp else p


def build_apprenticeships():
    rows = []
    pop = filtered_csv(APPS_FILES["pop"], "dfe_apps_geography_population.csv")
    tps = sorted({r["time_period"] for r in pop})
    latest_tp = tps[-1]
    keep_tps = tps[-6:]
    levels_seen, ages_seen = set(), set()
    for r in pop:
        if r["time_period"] not in keep_tps:
            continue
        gl = r["geographic_level"]
        if gl == "Local authority district":
            continue  # LA rows are identical for our unitary authorities
        geo = keep_geo(r)
        levels_seen.add(r["apps_level"]); ages_seen.add(r["age_summary"])
        lv, ag = r["apps_level"], r["age_summary"]
        if lv not in LEVEL_BD or ag not in AGE_BD:
            continue
        parts = [x for x in (AGE_BD[ag], LEVEL_BD[lv]) if x]
        bd = "; ".join(parts) if parts else None
        per = apps_period(r["time_period"], latest_tp)
        for col, iid in (("starts", "dfe_apps_starts"), ("achievements", "dfe_apps_achievements"),
                         ("participation", "dfe_apps_participation"),
                         ("starts_rate_per_100000_population", "dfe_apps_starts_rate"),
                         ("population_estimate", "dfe_apps_population")):
            v, s = num(r[col])
            if iid == "dfe_apps_population" and (lv != "Total"):
                continue
            rows.append(mkrow(geo, iid, v, per, bd, s))
    ssa = []
    for key, cache in (("ssa", "dfe_apps_geography_ssa.csv"), ("ssa_2425", "dfe_apps_geography_ssa_202425.csv"),
                       ("ssa_2324", "dfe_apps_geography_ssa_202324.csv")):
        ssa.extend(filtered_csv(APPS_FILES[key], cache))
    for r in ssa:
        if r["sex"] != "Total" or r["ethnicity_major"] != "Total":
            continue
        ssa_tp = r["time_period"]
        lv = r["apps_level"]
        if lv not in LEVEL_BD:
            continue
        geo = keep_geo(r)
        bd = "; ".join(x for x in (f"SSA: {r['ssa_tier_1']}" if r["ssa_tier_1"] != "Total" else "SSA: all",
                                   LEVEL_BD[lv]) if x)
        per = apps_period(ssa_tp, latest_tp)
        for col, iid in (("starts", "dfe_apps_ssa_starts"), ("achievements", "dfe_apps_ssa_achievements")):
            v, s = num(r[col])
            rows.append(mkrow(geo, iid, v, per, bd, s))
    add_beds_totals(rows, {"dfe_apps_starts", "dfe_apps_achievements", "dfe_apps_participation",
                           "dfe_apps_population", "dfe_apps_ssa_starts", "dfe_apps_ssa_achievements"})
    # Starts rate for Bedfordshire recomputed from summed starts / population.
    pop_tot = {(r["period"], r["breakdown"]): r["value"] for r in rows
               if r["code"] == "BEDS" and r["indicator"] == "dfe_apps_population"}
    for r in list(rows):
        if r["code"] == "BEDS" and r["indicator"] == "dfe_apps_starts":
            age_bd = r["breakdown"] if (r["breakdown"] or "").startswith("age") and ";" not in (r["breakdown"] or "") else None
            if r["breakdown"] is None or age_bd:
                d = pop_tot.get((r["period"], r["breakdown"]))
                if d:
                    rows.append(mkrow(BEDS, "dfe_apps_starts_rate", round(r["value"] * 1e5 / d), r["period"],
                                      r["breakdown"], num_=r["value"], den=d))
    C = "16-19,18-24,25+ inactive"
    meta = {
        "title": "Apprenticeships: starts, achievements and participation by learner home location, age, level and sector subject area",
        "publisher": "Department for Education",
        "source_url": f"{EES}/find-statistics/{APPS_PUB}",
        "api_url": [csv_url(v) for v in APPS_FILES.values()],
        "geography": ("LA, PCON (2024 constituencies whose name contains Bedford/Luton: Bedford, Mid Bedfordshire, "
                      "North Bedfordshire, Luton North, Luton South and South Bedfordshire - Hitchin, which takes "
                      "part of Central Bedfordshire, is not included), region, England; Bedfordshire 3-UA total"),
        "cohort": C,
        "period": apps_period(latest_tp, latest_tp),
        "latest_period": apps_period(latest_tp, latest_tp),
        "latest_full_year": ay(tps[-2]),
        "frequency": "Quarterly (in-year) / Annual (final full year)",
        "next_update": "Late November 2026 (2025/26 full-year final data)",
        "access": "CSV download",
        "quality": ("Accredited official statistics from the Individualised Learner Record (ILR); a census of "
                    "funded apprenticeship learners. In-year figures (latest year, Aug-Apr) are provisional "
                    "and will rise when the full year is reported; earlier years are final full-year counts."),
        "limitations": ("Geography is the LEARNER'S HOME postcode (not provider or employer location). Volumes "
                        "rounded to the nearest 10 by DfE and cells below 5 shown as 'low' (null, suppressed=true), "
                        "so Bedfordshire sums and small SSA x level cells carry rounding error. Sector subject area "
                        "(SSA tier 1) x LA detail is published one year per release, so SSA rows cover 2023/24 and "
                        "2024/25 (full year, from the two previous releases) plus 2025/26 in-year only; hospitality sits within 'Retail and Commercial Enterprise' and "
                        "'Leisure, Travel and Tourism'. Starts counted per programme (one learner may start more "
                        "than one). Methodology breaks: 2017 apprenticeship levy/funding reform (starts fell "
                        "sharply in 2017/18); transition from frameworks to standards (all standards since "
                        "2020/21); COVID-19 depressed 2019/20-2020/21. Starts rates per 100,000 use ONS mid-year "
                        "population for the age band. Age = age at start."),
        "indicators": [
            ind("dfe_apps_starts", "Apprenticeship starts", "count", C, "higher_is_better",
                "Apprenticeship starts by learner home LA, breakdown by age at start and level."),
            ind("dfe_apps_achievements", "Apprenticeship achievements", "count", C, "higher_is_better",
                "Apprenticeship completions/achievements by learner home LA."),
            ind("dfe_apps_participation", "Apprenticeship participation", "count", C, "higher_is_better",
                "Learners on an apprenticeship at any point in the academic year."),
            ind("dfe_apps_starts_rate", "Starts per 100,000 population", "rate", C, "higher_is_better",
                "Starts per 100,000 residents of the matching age band (ONS mid-year estimates)."),
            ind("dfe_apps_population", "Population used for rates", "count", C, "neutral",
                "ONS mid-year population estimate for the age band, as used by DfE."),
            ind("dfe_apps_ssa_starts", "Starts by sector subject area", "count", C, "higher_is_better",
                "Apprenticeship starts by SSA tier 1 and level (2023/24, 2024/25 full year; 2025/26 Aug-Apr)."),
            ind("dfe_apps_ssa_achievements", "Achievements by sector subject area", "count", C, "higher_is_better",
                "Apprenticeship achievements by SSA tier 1 and level (2023/24, 2024/25 full year; 2025/26 Aug-Apr)."),
        ],
    }
    print("  apps levels:", sorted(levels_seen), "ages:", sorted(ages_seen))
    return save("dfe_apprenticeships", meta, rows)


# --------------------------------------------------------------------------
# 3. FE and skills
# --------------------------------------------------------------------------
FE_PUB = "further-education-and-skills"
FE_FILES = {
    "pop": "66fd40a0-74f2-4683-bdb8-5eb95012bcdc",   # Region/LA/LAD/PCON by provision type, level, age
    "ssa": "c7199761-f795-4732-aa83-020867770c4e",   # LAD: E&T enrolments by SSA x level
}


def build_fe():
    rows = []
    pop = filtered_csv(FE_FILES["pop"], "dfe_fe_geography_population.csv")
    tps = sorted({r["time_period"] for r in pop})
    latest_tp = tps[-1]
    keep_tps = tps[-6:]
    combos = defaultdict(int)
    for r in pop:
        if r["time_period"] not in keep_tps:
            continue
        if r["geographic_level"] in ("Local authority district", "Parliamentary constituency"):
            continue
        combos[(r["provision_type"], r["regulated_status"], r["level_or_type"], r["age_summary"])] += 1
    # Keep a compact set: every provision type x level/type x age, regulated_status Total only.
    for r in pop:
        if r["time_period"] not in keep_tps or r["regulated_status"] not in ("Total", ""):
            continue
        if r["geographic_level"] in ("Local authority district", "Parliamentary constituency"):
            continue
        geo = keep_geo(r)
        per = apps_period(r["time_period"], latest_tp)
        lt = r["level_or_type"]
        ag = r["age_summary"]
        if ag.lower().startswith("unknown"):
            continue
        bd = "; ".join(x for x in (lt, None if ag == "Total" else f"age {ag}") if x)
        for col, iid in (("participation", "dfe_fe_participation"), ("learner_achievements", "dfe_fe_achievements"),
                         ("starts", "dfe_fe_starts"),
                         ("participation_rate_per_100000_population", "dfe_fe_participation_rate"),
                         ("learner_achievements_rate_per_100000_population", "dfe_fe_achievements_rate")):
            if "rate" in iid and not lt.endswith(": Total"):
                continue  # keep rates for provision-type totals only (file size)
            v, s = num(r[col])
            if v is None and (r[col] or "").strip().lower() == "z":
                continue  # not applicable
            rows.append(mkrow(geo, iid, v, per, bd, s))
    ssa = filtered_csv(FE_FILES["ssa"], "dfe_fe_geography_ssa.csv")
    ssa_tp = sorted({r["time_period"] for r in ssa})[-1]
    for r in ssa:
        if (r["time_period"] != ssa_tp or r["sex"] != "Total" or r["ethnicity_major"] != "Total"
                or r["geographic_level"] not in ("National", "Regional", "Local authority district")):
            continue
        geo = keep_geo(r)
        if not geo or geo[2] == "PCON":
            continue
        lvl = r["notional_nvq_level"]
        bd = f"SSA: {r['ssa_tier_1'] if r['ssa_tier_1'] != 'Total' else 'all'}" + ("" if lvl == "Total" else f"; {lvl}")
        per = apps_period(ssa_tp, latest_tp)
        for col, iid in (("enrolments", "dfe_fe_ssa_enrolments"), ("aim_achievements", "dfe_fe_ssa_aim_achievements")):
            v, s = num(r[col])
            rows.append(mkrow(geo, iid, v, per, bd, s))
    add_beds_totals(rows, {"dfe_fe_participation", "dfe_fe_achievements", "dfe_fe_starts",
                           "dfe_fe_ssa_enrolments", "dfe_fe_ssa_aim_achievements"})
    C = "16-19,18-24,25+ inactive"
    meta = {
        "title": "Further education and skills: participation and achievements by learner home LA, provision type, level and age",
        "publisher": "Department for Education",
        "source_url": f"{EES}/find-statistics/{FE_PUB}",
        "api_url": [csv_url(v) for v in FE_FILES.values()],
        "geography": "LA, region, England; Bedfordshire 3-UA total for counts",
        "cohort": C,
        "period": apps_period(latest_tp, latest_tp),
        "latest_period": apps_period(latest_tp, latest_tp),
        "latest_full_year": ay(tps[-2]),
        "frequency": "Quarterly (in-year) / Annual (final full year)",
        "next_update": "Late November 2026 (2025/26 full-year final data)",
        "access": "CSV download",
        "quality": ("Accredited official statistics from the ILR (census of government-funded FE learners, "
                    "mainly aged 19+ plus apprentices of all ages). Latest year is in-year (Aug-Apr) and provisional."),
        "limitations": ("Learner HOME location, not provider location. Figures rounded to nearest 10; 'low' "
                        "(<5) and 'c' cells suppressed (null, suppressed=true). 'Further education and skills' "
                        "total includes apprenticeships; 'Education and training' and 'Community learning' / "
                        "'Tailored learning' are sub-types. Funding-stream renames: Adult Education Budget became "
                        "the Adult Skills Fund from 2024/25 and Community Learning was reclassified as 'Tailored "
                        "learning' - provision-type labels change across years so check breakdown strings. "
                        "Skills Bootcamps are NOT in these tables (separate publication, no home-LA split). "
                        "16-18 classroom learners in colleges/sixth forms are largely outside this publication "
                        "(see 16-19 performance). SSA x level enrolments by LA only for the latest in-year period; "
                        "rates per 100,000 use ONS mid-year population. Participation counts learners once per "
                        "provision type; totals across types are not additive."),
        "indicators": [
            ind("dfe_fe_participation", "FE & skills participation (learners)", "count", C, "higher_is_better",
                "Learners participating in government-funded FE and skills, by provision type/level and age."),
            ind("dfe_fe_achievements", "FE & skills learner achievements", "count", C, "higher_is_better",
                "Learners achieving at least one aim in the year."),
            ind("dfe_fe_starts", "FE & skills starts", "count", C, "higher_is_better",
                "Starts, where published (mainly apprenticeships)."),
            ind("dfe_fe_participation_rate", "Participation per 100,000 population", "rate", C, "higher_is_better",
                "FE & skills learners per 100,000 residents of the age band."),
            ind("dfe_fe_achievements_rate", "Achievements per 100,000 population", "rate", C, "higher_is_better",
                "FE & skills learner achievements per 100,000 residents of the age band."),
            ind("dfe_fe_ssa_enrolments", "Education & training enrolments by sector subject area", "count", C,
                "higher_is_better", "Adult education and training aim enrolments by SSA tier 1 and level (latest in-year)."),
            ind("dfe_fe_ssa_aim_achievements", "Education & training aim achievements by sector subject area",
                "count", C, "higher_is_better", "Aim achievements by SSA tier 1 and level (latest in-year)."),
        ],
    }
    print("  FE provision/level/age combos (LA/reg/nat):", len(combos))
    return save("dfe_fe_skills", meta, rows)


# --------------------------------------------------------------------------
# 4. Destinations (EES API)
# --------------------------------------------------------------------------
KS5_DS = "019d4e73-6440-7523-b60c-bfab1ad4a30d"
KS4_DS = "019d4f41-22d1-71b2-a1a7-f3b91026815b"
LOCS = [{"level": "LA", "code": c} for c in LAS] + [{"level": "REG", "code": REG}, {"level": "NAT", "code": ENG}]


def opt(meta, label, option):
    for f in meta["filters"]:
        if f["label"] == label:
            for o in f["options"]:
                if o["label"] == option:
                    return f["id"], o["id"]
    raise KeyError((label, option))


def geo_from_api(meta, rec):
    lvl = rec["geographicLevel"]
    oid = rec["locations"][lvl]
    for g in meta["locations"]:
        if g["level"]["code"] == lvl:
            for o in g["options"]:
                if o["id"] == oid:
                    code = o.get("code")
                    if lvl == "REG" and code != REG:
                        return None
                    if lvl == "LA":
                        if code not in LAS and o.get("oldCode") not in OLD_LA:
                            return None
                        code = code if code in LAS else OLD_LA.get(o.get("oldCode"))
                        return (code, LAS[code], "LA")
                    if lvl == "REG":
                        return (REG, "East of England", "region")
                    return (ENG, "England", "country")
    return None


DEST_MAP = {
    "Sustained education, employment & apprenticeships": "overall",
    "Sustained education destination": "education",
    "Sustained apprenticeships": "apprenticeship",
    "Sustained employment destination": "employment",
    "Not recorded as a sustained destination": "not_sustained",
    "Activity not captured": "not_captured",
    "Education or employment not sustained": "not_sustained_ee",
}


def query_dest(ds, meta, prefix, totals, extra_or, cache):
    """totals: list of (filter label, 'Total') to pin; extra_or: (label, [options]) to vary."""
    flt_and = []
    for lab, optname in totals:
        names = optname if isinstance(optname, list) else [optname]
        flt_and.append({"filters": {"in": [opt(meta, lab, o)[1] for o in names]}})
    lab, opts = extra_or
    flt_and.append({"filters": {"in": [opt(meta, lab, o)[1] for o in opts]}})
    grp_label = "Destination measure group"
    flt_and.append({"filters": {"in": [opt(meta, grp_label, "Headline destinations")[1],
                                        opt(meta, grp_label, "Overall destination")[1]]}})
    dm_label = "Destination measure"
    flt_and.append({"filters": {"in": [opt(meta, dm_label, k)[1] for k in DEST_MAP]}})
    body = {"criteria": {"and": [{"geographicLevels": {"in": ["LA", "REG", "NAT"]}},
                                 {"locations": {"in": LOCS}}] + flt_and},
            "indicators": [i["id"] for i in meta["indicators"]]}
    return api_query(ds, body, cache), body


def build_dest(which):
    ds = KS5_DS if which == "ks5" else KS4_DS
    meta = api_meta(ds)
    ind_by_label = {i["label"]: i["id"] for i in meta["indicators"]}
    pct_id = ind_by_label["Percentage of pupils sustaining a destination"]
    n_id = ind_by_label["Number of pupils sustaining a destination"]
    den_id = [i["id"] for i in meta["indicators"] if i["label"].startswith("Number of") and "completing" in i["label"]][0]
    lab = {f["id"]: {o["id"]: o["label"] for o in f["options"]} for f in meta["filters"]}
    flab = {f["id"]: f["label"] for f in meta["filters"]}
    dis_label = [f["label"] for f in meta["filters"] if f["label"].lower() == "disadvantage status"][0]
    pin = [f["label"] for f in meta["filters"]
           if f["label"] not in ("Destination measure", "Destination measure group", dis_label)]
    # LA rows have no all-establishment "Total" group: pin DfE's headline cohort.
    # (KS4 labels the same group differently at national vs LA/regional level.)
    est_group = (["State-funded mainstream schools and colleges"] if which == "ks5"
                 else ["State-funded mainstream and special", "Total state-funded mainstream and special"])
    totals = [(p_, est_group if p_ == "Establishment type group" else "Total") for p_ in pin]
    recs, body = query_dest(ds, meta, which, totals, (dis_label, ["Total", "Disadvantaged", "Not known to be disadvantaged"]),
                            f"dfe_{which}_dest_api.json")
    pers = sorted({r["timePeriod"]["period"] for r in recs})[-5:]
    rows = []
    pfx = "dfe_ks5d" if which == "ks5" else "dfe_ks4d"
    for rec in recs:
        if rec["timePeriod"]["period"] not in pers:
            continue
        f = {flab[k]: lab[k][v] for k, v in rec["filters"].items()}
        dm = f["Destination measure"]
        if dm not in DEST_MAP:
            continue
        geo = geo_from_api(meta, rec)
        if not geo:
            continue
        dis = f[dis_label]
        bd = None if dis == "Total" else dis
        per = f'{ay(rec["timePeriod"]["period"])} leavers'
        v, s = num(rec["values"].get(pct_id))
        n, _ = num(rec["values"].get(n_id))
        d, _ = num(rec["values"].get(den_id))
        rows.append(mkrow(geo, f"{pfx}_pct_{DEST_MAP[dm]}", v, per, bd, s, num_=n, den=d))
    # Bedfordshire: recompute from summed num/den.
    grp = defaultdict(dict)
    for r in rows:
        if r["level"] == "LA":
            grp[(r["indicator"], r["period"], r["breakdown"])][r["code"]] = r
    for (iid, per, bd), m in grp.items():
        if len(m) == 3 and all(x["num"] is not None and x["den"] for x in m.values()):
            n = sum(x["num"] for x in m.values()); d = sum(x["den"] for x in m.values())
            rows.append(mkrow(BEDS, iid, round(100 * n / d, 1), per, bd, num_=n, den=d))
    C = "16-19"
    stage = "16-18 (KS5) study leavers" if which == "ks5" else "Key stage 4 (Year 11) leavers"
    descs = {
        "overall": ("Sustained education, employment or apprenticeship (%)", "higher_is_better",
                    "% of {s} in a sustained education, apprenticeship or employment destination (2 terms / 6 months)."),
        "education": ("Sustained education (%)", "neutral", "% of {s} in sustained education (FE, school sixth form, HE etc.)."),
        "apprenticeship": ("Sustained apprenticeship (%)", "higher_is_better", "% of {s} in a sustained apprenticeship."),
        "employment": ("Sustained employment (%)", "neutral", "% of {s} in sustained employment."),
        "not_sustained": ("Not recorded as sustained destination (%)", "higher_is_worse",
                          "% of {s} with no sustained destination (not sustained + activity not captured)."),
        "not_sustained_ee": ("Education or employment not sustained (%)", "higher_is_worse",
                             "% of {s} whose education/employment was not sustained for the required period."),
        "not_captured": ("Activity not captured (%)", "higher_is_worse",
                         "% of {s} with no activity captured in any data source."),
    }
    present = {r["indicator"] for r in rows}
    inds = [ind(f"{pfx}_pct_{k}", v[0], "percent", C, v[1], v[2].format(s=stage) + " Breakdown = disadvantage status.")
            for k, v in descs.items() if f"{pfx}_pct_{k}" in present]
    if which == "ks5":
        title, slug = "16-18 destination measures (16-19 study leavers) by local authority", "16-19-destination-measures"
    else:
        title, slug = "Key stage 4 destination measures by local authority", "key-stage-4-destination-measures"
    m = {
        "title": title,
        "publisher": "Department for Education",
        "source_url": f"{EES}/find-statistics/{slug}",
        "api_url": [f"{API}/data-sets/{ds}/query (POST)", f"{API}/data-sets/{ds}/meta"],
        "api_query": body,
        "geography": "LA (of institution), region, England; Bedfordshire recomputed from summed num/den",
        "cohort_basis": ("State-funded mainstream schools and colleges" if which == "ks5"
                         else "State-funded mainstream and special schools"),
        "cohort": C,
        "period": latest(rows),
        "latest_period": latest(rows),
        "frequency": "Annual",
        "next_update": "Autumn 2027",
        "access": "API",
        "quality": ("Official statistics linking the National Pupil Database, ILR, HESA and DWP/HMRC "
                    "employment and benefit records (census, no sampling error). A destination counts when "
                    "sustained for two terms (education/apprenticeship) or 5 of 6 months (employment) in the "
                    "year after leaving."),
        "limitations": ("Period = the year the cohort LEFT "
                        f"{'16-18 study' if which == 'ks5' else 'KS4'} (EES time_period); destinations are measured in the "
                        "following academic year (e.g. '2023/24 leavers' = sustained destination during 2024/25, published "
                        "Oct 2026 as the 'Academic year 2024/25' release), so data are ~2 years old. LA geography is the "
                        "location of the school/college attended, not residence. Cohort = DfE headline basis "
                        "(KS5: state-funded mainstream schools and colleges; KS4: state-funded mainstream and special "
                        "schools); independent schools excluded. Disadvantage = FSM in last 6 years or "
                        "looked after. Small cohorts suppressed (null). Employment data have had linkage changes "
                        "(e.g. inclusion of self-employment, HMRC data) over time; COVID affected 2019/20-2020/21 cohorts."),
        "indicators": inds,
    }
    return save(f"dfe_{which}_destinations", m, rows)


# --------------------------------------------------------------------------
# 5. Level 2 and 3 attainment by 19
# --------------------------------------------------------------------------
L23_SLUG = "level-2-and-3-attainment-by-young-people-aged-19"
L23_FILE = "882297f8-d6da-42fd-ac3e-791d1936ad4b"


def build_l2l3():
    raw = filtered_csv(L23_FILE, "dfe_l2l3_la.csv")
    # Survey the filter space once to pick headline series.
    series = {
        ("Level 2", "Total", "Total Level 2"): "l2",
        ("Level 3", "Total", "Total Level 3"): "l3",
        ("Level 2", "Attained Level 2 English & Maths", "Total (GCSE and other equivalent)"): "l2_em",
    }
    # Future-dated cohort rows exist (blank values); keep periods with published by-19 England data.
    tps = sorted({r["time_period"] for r in raw if r["age"] == "by age 19" and r["geographic_level"] == "National"
                  and r["breakdown_topic"] == "Total" and (r["percentage"] or "").strip() not in SUPPRESS})
    keep_tps = tps[-6:]
    rows = []
    seen = defaultdict(set)
    for r in raw:
        for k in ("geography_basis", "breakdown_topic", "age", "qualification_level", "subject", "qualification_type"):
            seen[k].add(r[k])
    for r in raw:
        if r["age"] != "by age 19" or r["time_period"] not in keep_tps:
            continue
        key = series.get((r["qualification_level"], r["subject"], r["qualification_type"]))
        if not key:
            continue
        topic, bdv = r["breakdown_topic"], r["breakdown"]
        if topic == "Total":
            bd = None
        elif topic.startswith("FSM"):
            bd = bdv
        elif topic in ("Disadvantaged status", "Sex", "SEN (Special Educational Need)"):
            bd = f"{topic.split(' (')[0]}: {bdv}"
        else:
            continue
        if "gap" in bdv.lower():
            if topic == "Sex":
                continue
            gname = {"FSM": "fsm", "Disadvantaged status": "disadv", "SEN (Special Educational Need)": "sen"}
            gk = next(v for k, v in gname.items() if topic.startswith(k))
            v, s = num(r["percentage"])
            rows.append(mkrow(keep_geo(r), f"dfe_l23_gap_{gk}_{key}_by19", None if v is None else round(v, 1),
                              f"{ay(r['time_period'])} (age 19)", None, s))
            continue
        geo = keep_geo(r)
        per = f"{ay(r['time_period'])} (age 19)"
        v, s = num(r["percentage"])
        n, _ = num(r["number"])
        d, _ = num(r["number_in_ss_cohort"])
        if v is not None:
            v = round(v, 1)
        rows.append(mkrow(geo, f"dfe_l23_pct_{key}_by19", v, per, bd, s, num_=n, den=d))
    # Dedupe (several subject spellings may map to same key).
    uniq = {}
    for r in rows:
        uniq[(r["code"], r["indicator"], r["period"], r["breakdown"])] = r
    rows = list(uniq.values())
    grp = defaultdict(dict)
    for r in rows:
        if r["level"] == "LA" and "_pct_" in r["indicator"]:
            grp[(r["indicator"], r["period"], r["breakdown"])][r["code"]] = r
    for (iid, per, bd), m in grp.items():
        if len(m) == 3 and all(x["num"] is not None and x["den"] for x in m.values()):
            n = sum(x["num"] for x in m.values()); d = sum(x["den"] for x in m.values())
            rows.append(mkrow(BEDS, iid, round(100 * n / d, 1), per, bd, num_=n, den=d))
    C = "16-19,18-24"
    inds = []
    for key, lab in (("l2", "Level 2"), ("l3", "Level 3"), ("l2_em", "Level 2 in English and maths")):
        inds.append(ind(f"dfe_l23_pct_{key}_by19", f"Achieved {lab} by 19 (%)", "percent", C, "higher_is_better",
                        f"% of the state-school cohort (by LA of school at 15) achieving {lab} by age 19; breakdowns by FSM etc."))
        for gk, gl in (("fsm", "FSM-eligible vs not eligible"), ("disadv", "disadvantaged vs non-disadvantaged"),
                       ("sen", "identified SEN vs no SEN")):
            inds.append(ind(f"dfe_l23_gap_{gk}_{key}_by19", f"{lab} by 19 gap: {gl} (pp)", "percent", C,
                            "higher_is_worse", f"DfE-published percentage-point attainment gap in {lab} by 19, {gl}."))
    present = {r["indicator"] for r in rows}
    inds = [i for i in inds if i["id"] in present]
    m = {
        "title": "Level 2 and 3 attainment age 16 to 25 (by age 19) by local authority",
        "publisher": "Department for Education",
        "source_url": f"{EES}/find-statistics/{L23_SLUG}",
        "api_url": csv_url(L23_FILE),
        "geography": "LA (of school at age 15), region, England; Bedfordshire recomputed from summed num/den",
        "cohort": C,
        "period": latest(rows),
        "latest_period": latest(rows),
        "frequency": "Annual",
        "next_update": "April 2027",
        "access": "CSV download",
        "quality": ("Official statistics from matched NPD/ILR/awarding-body records for the cohort in state "
                    "schools at academic age 15, followed to age 19 (census, no sampling error)."),
        "limitations": ("Geography = LA of the school attended at age 15 (not current residence). Excludes "
                        "young people not in English state schools at 15. Level 2 = 5 GCSEs 9-4 or equivalent; "
                        "Level 3 = 2 A levels or equivalent. 2020 and 2021 GCSE/A level grades were centre/teacher "
                        "assessed, inflating attainment for cohorts aged 19 in 2021/22-2022/23. Counts rounded; "
                        "small cells suppressed (null). FSM = eligible for free school meals at age 15; disadvantaged = "
                        "FSM in last 6 years or looked after. Gap rows are DfE's published percentage-point gaps "
                        "(not recomputed for the Bedfordshire total)."),
        "indicators": inds,
    }
    print("  L2/3 qual levels:", sorted(seen["qualification_level"]), "\n  subjects:", sorted(seen["subject"])[:20],
          "\n  topics:", sorted(seen["breakdown_topic"]), "\n  basis:", sorted(seen["geography_basis"]),
          "\n  qual types:", sorted(seen["qualification_type"])[:10], "\n  ages:", sorted(seen["age"]))
    return save("dfe_l2l3_19", m, rows)


# --------------------------------------------------------------------------
# 6. Care leavers activity
# --------------------------------------------------------------------------
CLA_SLUG = "children-looked-after-in-england-including-adoptions"
CL_FILE = "5279794c-6b75-4187-86c1-0ed3789bbfd6"


def build_care_leavers():
    raw = filtered_csv(CL_FILE, "dfe_care_leavers_activity.csv")
    rows = []
    cats = set()
    for r in raw:
        cats.add(r["breakdown"])
        geo = keep_geo(r)
        age = r["care_leaver_age"]
        b = r["breakdown"]
        slug = re.sub(r"[^a-z0-9]+", "_", b.lower()).strip("_")[:40]
        bd = f"age {age.replace(' years', '')}" if age not in ("Total", "All ages") else "age 17-21"
        if r["care_leaver_count"].strip() == "z":
            continue
        v, s = num(r["care_leaver_percent"])
        c, _ = num(r["care_leaver_count"])
        if b == "Total":
            rows.append(mkrow(geo, "dfe_cl_n_total", c, r["time_period"], bd, s))
            continue
        rows.append(mkrow(geo, "dfe_cl_pct_activity", v, r["time_period"], f"{bd}; {b}", s, num_=c))
    # Headline derived EET / NEET: DfE publishes "Total in education, employment or training" and
    # "Total not in education, employment or training" breakdown lines.
    out = []
    for r in rows:
        if r["indicator"] != "dfe_cl_pct_activity":
            continue
        bdl = r["breakdown"].split("; ", 1)[1].lower()
        if bdl.startswith("total not in education") or bdl == "not in education, employment or training":
            out.append(dict(r, indicator="dfe_cl_pct_neet", breakdown=r["breakdown"].split("; ")[0]))
        elif bdl.startswith("total in education") or bdl == "in education, employment or training":
            out.append(dict(r, indicator="dfe_cl_pct_eet", breakdown=r["breakdown"].split("; ")[0]))
    rows.extend(out)
    # Bedfordshire recompute for EET/NEET and counts
    tot = {(r["code"], r["period"], r["breakdown"]): r["value"] for r in rows if r["indicator"] == "dfe_cl_n_total"}
    for iid in ("dfe_cl_pct_neet", "dfe_cl_pct_eet"):
        grp = defaultdict(dict)
        for r in rows:
            if r["indicator"] == iid and r["level"] == "LA":
                grp[(r["period"], r["breakdown"])][r["code"]] = r
        for (per, bd), m in grp.items():
            dens = [tot.get((c, per, bd)) for c in m]
            if len(m) == 3 and all(x["num"] is not None for x in m.values()) and all(dens):
                n = sum(x["num"] for x in m.values()); d = sum(dens)
                rows.append(mkrow(BEDS, iid, round(100 * n / d), per, bd, num_=n, den=d))
    add_beds_totals(rows, {"dfe_cl_n_total"})
    C = "16-19,18-24"
    m = {
        "title": "Care leavers aged 17-21: activity (education, employment, training) by local authority",
        "publisher": "Department for Education",
        "source_url": f"{EES}/find-statistics/{CLA_SLUG}",
        "api_url": csv_url(CL_FILE),
        "geography": "LA (responsible authority), region, England; Bedfordshire recomputed from summed counts",
        "cohort": C,
        "period": latest(rows),
        "latest_period": latest(rows),
        "frequency": "Annual",
        "next_update": "November 2026",
        "access": "CSV download",
        "quality": ("Accredited official statistics from the SSDA903 children looked after return; activity "
                    "recorded around the care leaver's 17th-21st birthday (census of eligible care leavers)."),
        "limitations": ("Very small LA numbers: counts rounded/suppressed ('c', 'low', 'x' -> null) and "
                        "percentages to whole numbers, so year-to-year LA changes are noisy. Responsible LA, which "
                        "may differ from where the young person lives. 'Activity not known' / 'no information' "
                        "categories reduce comparability. Reporting year = year ending 31 March."),
        "indicators": [
            ind("dfe_cl_pct_neet", "Care leavers NEET (%)", "percent", C, "higher_is_worse",
                "% of care leavers (17-18 or 19-21) not in education, employment or training."),
            ind("dfe_cl_pct_eet", "Care leavers in education, employment or training (%)", "percent", C,
                "higher_is_better", "% of care leavers in education, employment or training."),
            ind("dfe_cl_pct_activity", "Care leavers by activity (%)", "percent", C, "neutral",
                "% of care leavers in each activity category (breakdown names the activity)."),
            ind("dfe_cl_n_total", "Care leavers (number)", "count", C, "neutral",
                "Number of care leavers in the age group (denominator)."),
        ],
    }
    print("  care leaver categories:", sorted(cats))
    return save("dfe_care_leavers", m, rows)


# --------------------------------------------------------------------------
# 7. EHC plans (EES API)
# --------------------------------------------------------------------------
EHCP_DS = "01a0aa37-1008-7183-9271-35e3bcbb26c8"
EHCP_AGES = {"Age 16": "16-19", "Age 17": "16-19", "Age 18": "16-19", "Age 19": "16-19",
             "Age 20": "20-25", "Age 21": "20-25", "Age 22": "20-25", "Age 23": "20-25",
             "Age 24": "20-25", "Age 25": "20-25", "Age 20 and over": "20-25"}


def build_ehcp():
    meta = api_meta(EHCP_DS)
    flab = {f["id"]: f["label"] for f in meta["filters"]}
    lab = {f["id"]: {o["id"]: o["label"] for o in f["options"]} for f in meta["filters"]}
    topic_f, topic_age = opt(meta, "Characteristic breakdown topic of child or young person with EHC plan",
                             "Age at start of academic year")
    _, topic_all = opt(meta, "Characteristic breakdown topic of child or young person with EHC plan", "All EHC plans")
    set_label = "Type of setting named in EHC plan"
    setting_opts = [o["label"] for f in meta["filters"] if f["label"] == set_label for o in f["options"]]
    want_settings = [s for s in ("Total", "Not in employment, education or training", "General FE tertiary colleges")
                     if s in setting_opts]
    set_ids = [opt(meta, set_label, s)[1] for s in want_settings]
    n_id = [i["id"] for i in meta["indicators"] if i["label"] == "Number of EHC plans"][0]
    body = {"criteria": {"and": [
        {"geographicLevels": {"in": ["LA", "REG", "NAT"]}},
        {"locations": {"in": LOCS}},
        {"filters": {"in": [topic_age, topic_all]}},
        {"filters": {"in": set_ids}},
    ]}, "indicators": [n_id]}
    recs = api_query(EHCP_DS, body, "dfe_ehcp_api.json")
    pers = sorted({r["timePeriod"]["period"] for r in recs})[-6:]
    char_label = "Characteristics of child or young person with EHC plan"
    agg = defaultdict(lambda: [0, False, 0])
    for rec in recs:
        if rec["timePeriod"]["period"] not in pers:
            continue
        f = {flab[k]: lab[k][v] for k, v in rec["filters"].items()}
        ch = f.get(char_label)
        setting = f.get(set_label)
        band = "all ages" if ch == "All EHC plans" else EHCP_AGES.get(ch)
        if not band:
            continue
        geo = geo_from_api(meta, rec)
        if not geo:
            continue
        v, s = num(rec["values"].get(n_id))
        key = (geo, ay(rec["timePeriod"]["period"]), band, setting)
        a = agg[key]
        if v is None:
            a[1] = True
        else:
            a[0] += v
        a[2] += 1
    rows = []
    setting_ind = {"Total": "dfe_ehcp_n", "Not in employment, education or training": "dfe_ehcp_n_neet",
                   "General FE tertiary colleges": "dfe_ehcp_n_fe_college"}
    for (geo, per, band, setting), (v, sup, _) in agg.items():
        if setting not in setting_ind:
            continue
        # Caseload is at the January census: '2025/26' -> 'Jan 2026'.
        rows.append(mkrow(geo, setting_ind[setting], None if sup else v, f"Jan {per[:2]}{per[-2:]}", f"age {band}", sup))
    add_beds_totals(rows, {"dfe_ehcp_n", "dfe_ehcp_n_neet", "dfe_ehcp_n_fe_college"})
    C = "16-19,18-24"
    m = {
        "title": "Education, health and care plans as at January by age band and local authority",
        "publisher": "Department for Education",
        "source_url": f"{EES}/find-statistics/education-health-and-care-plans",
        "api_url": [f"{API}/data-sets/{EHCP_DS}/query (POST)", f"{API}/data-sets/{EHCP_DS}/meta"],
        "api_query": body,
        "geography": "LA (maintaining authority), region, England; Bedfordshire 3-UA sum",
        "cohort": C,
        "period": latest(rows),
        "latest_period": latest(rows),
        "frequency": "Annual",
        "next_update": "June 2027",
        "access": "API",
        "quality": ("Official statistics from the SEN2 statutory return (child-level since 2023); census of "
                    "EHC plans maintained by each LA at the January census date."),
        "limitations": ("Age = age at start of academic year (31 August); bands 16-19 (ages 16-19) and 20-25 "
                        "are summed here from single-year ages by this pipeline, and age detail is only published "
                        "from Jan 2024 (child-level SEN2); earlier years carry the all-ages total only. LA = authority maintaining the "
                        "plan, not necessarily where the young person is educated. SEN2 moved to child-level "
                        "collection in 2023, which affects comparability with earlier years. 'NEET' counts are "
                        "plans where the named setting is 'Not in employment, education or training' (an "
                        "administrative placement status, not the CCIS NEET measure). Small cells may be "
                        "suppressed (null)."),
        "indicators": [
            ind("dfe_ehcp_n", "EHC plans (number)", "count", C, "neutral",
                "Number of EHC plans maintained in January, by age band (all ages / 16-19 / 20-25)."),
            ind("dfe_ehcp_n_neet", "EHC plans with young person NEET (number)", "count", C, "higher_is_worse",
                "EHC plans whose named setting is 'Not in employment, education or training'."),
            ind("dfe_ehcp_n_fe_college", "EHC plans in general FE/tertiary colleges", "count", C, "neutral",
                "EHC plans naming a general FE or tertiary college as the setting."),
        ],
    }
    print("  EHCP settings requested:", want_settings)
    return save("dfe_ehcp", m, rows)


# --------------------------------------------------------------------------
def main():
    only = set(sys.argv[1:])
    steps = [("neet", build_neet), ("apps", build_apprenticeships), ("fe", build_fe),
             ("ks5", lambda: build_dest("ks5")), ("ks4", lambda: build_dest("ks4")),
             ("l2l3", build_l2l3), ("cl", build_care_leavers), ("ehcp", build_ehcp)]
    failed = []
    for name, fn in steps:
        if only and name not in only:
            continue
        print(f"[{name}]", flush=True)
        try:
            fn()
        except Exception as e:  # noqa: BLE001 - keep going, report at end
            import traceback
            traceback.print_exc()
            failed.append((name, str(e)[:300]))
    print("dfe_t_levels: skipped - EES has no LA-level T Level participation table (16 to 19 performance LA "
          "file has no T Level exam cohort; Provisional T Level results are provider-level only).")
    if failed:
        print("FAILED:", failed)
        sys.exit(1)


if __name__ == "__main__":
    main()
