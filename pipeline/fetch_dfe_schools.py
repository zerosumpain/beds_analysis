"""DfE schools / 14-19 evidence for Bedfordshire.

Datasets written (see CONTRACT.md):
  providers               GIAS open providers relevant to 14-19 and adult skills (points)
  school_pipeline         pupils by NC year, FSM %, SEN % and a derived 16-18 cohort roll-forward
  dfe_ks4_la              KS4 headline measures by LA (time series)
  dfe_ks4_school          KS4 headline measures per secondary school (points)
  dfe_16_18_la            16-18 (KS5) attainment and retention by LA
  dfe_absence_exclusions  secondary persistent absence and suspension rates by LA

Sources: GIAS bulk CSV; EES public API (api.education.gov.uk/statistics/v1) data sets queried with
POST /data-sets/{id}/query; EES data-catalogue CSV for suspensions (not in the API).
"""
import csv
import datetime as dt
import hashlib
import io
import json
import urllib.request

from common import COMPARATORS, LAS, RAW, SITE, UA, fetch, save
from osgb import haversine_km, osgb_to_wgs84

EES = "https://api.education.gov.uk/statistics/v1"
EES_WEB = "https://explore-education-statistics.service.gov.uk"
OLD_LA = {"822": "E06000055", "823": "E06000056", "821": "E06000032"}
SUPPRESSED = {"c", "x", "z", "low", "u", ":", "~", "..", "", "ne", "na", "-"}
FE_RADIUS_KM = 25.0
BEDS = ("BEDS", "Bedfordshire (3 UAs)", "county")


# --------------------------------------------------------------------------------------------
# EES API helpers
# --------------------------------------------------------------------------------------------
def ees_meta(ds_id, version=None):
    q = f"?dataSetVersion={version}" if version else ""
    return json.loads(fetch(f"{EES}/data-sets/{ds_id}/meta{q}",
                            cache_name=f"ees_meta_{ds_id}_{version or 'latest'}.json"))


def _post(url, body, cache_name):
    p = RAW / cache_name
    if p.exists():
        return json.loads(p.read_text())
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"User-Agent": UA, "Content-Type": "application/json"})
    last = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as r:
                doc = json.loads(r.read())
            p.write_text(json.dumps(doc))
            return doc
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"EES query failed {url}: {last}")


def ees_query(ds_id, filters, indicators, levels=("LA", "REG", "NAT"), periods=None,
              school_las=False, version=None):
    """Query an EES API data set and return decoded rows.

    filters: {filter label: [option labels]} - every listed filter is ANDed; options within a
    filter are ORed. Filters not listed are unconstrained (so callers should pin "Total").
    indicators: list of indicator labels. levels: geographic level codes to return.
    Locations: the 3 Bedfordshire LAs, East of England, England. With school_las=True returns
    SCH-level rows whose parent LA is one of the 3 LAs.
    """
    meta = ees_meta(ds_id, version)
    fmap = {f["label"]: f for f in meta["filters"]}
    fid_label = {f["id"]: f["label"] for f in meta["filters"]}
    opt_label = {o["id"]: o["label"] for f in meta["filters"] for o in f["options"]}
    ind_by_label = {i["label"]: i["id"] for i in meta["indicators"]}
    ind_label = {v: k for k, v in ind_by_label.items()}
    loc = {}  # (level, id) -> option
    for lv in meta["locations"]:
        for o in lv["options"]:
            loc[(lv["level"]["code"], o["id"])] = o
    la_ids = [i for (lv, i), o in loc.items() if lv == "LA" and o.get("code") in LAS]
    reg_ids = [i for (lv, i), o in loc.items() if lv == "REG" and o.get("code") == "E12000006"]
    nat_ids = [i for (lv, i), o in loc.items() if lv == "NAT" and o.get("code") == "E92000001"]

    clauses = []
    for flabel, opts in filters.items():
        f = fmap[flabel]
        ids = [o["id"] for o in f["options"] if o["label"] in opts]
        if len(ids) != len(opts):
            raise KeyError(f"{ds_id}: filter {flabel} options {opts} not all found")
        clauses.append({"filters": {"in": ids}})
    geo = []
    if "LA" in levels:
        geo.append({"and": [{"geographicLevels": {"eq": "LA"}},
                            {"locations": {"in": [{"level": "LA", "id": i} for i in la_ids]}}]})
    if "REG" in levels and reg_ids:
        geo.append({"and": [{"geographicLevels": {"eq": "REG"}},
                            {"locations": {"in": [{"level": "REG", "id": i} for i in reg_ids]}}]})
    if "NAT" in levels and nat_ids:
        geo.append({"and": [{"geographicLevels": {"eq": "NAT"}},
                            {"locations": {"in": [{"level": "NAT", "id": i} for i in nat_ids]}}]})
    if school_las:
        geo = [{"and": [{"geographicLevels": {"eq": "SCH"}},
                        {"locations": {"in": [{"level": "LA", "id": i} for i in la_ids]}}]}]
    clauses.append({"or": geo})
    if periods:
        tp = [t for t in meta["timePeriods"] if t["label"] in periods]
        clauses.append({"timePeriods": {"in": [{"period": t["period"], "code": t["code"]} for t in tp]}})
    ind_ids = [ind_by_label[i] for i in indicators]
    out, page = [], 1
    while True:
        body = {"criteria": {"and": clauses}, "indicators": ind_ids, "page": page, "pageSize": 10000}
        key = hashlib.sha1(json.dumps([ds_id, version, body], sort_keys=True).encode()).hexdigest()[:16]
        q = f"?dataSetVersion={version}" if version else ""
        doc = _post(f"{EES}/data-sets/{ds_id}/query{q}", body, f"ees_q_{ds_id}_{key}.json")
        for r in doc.get("results", []):
            lv = r["geographicLevel"]
            o = loc.get((lv, r["locations"].get(lv)), {})
            code = o.get("code") or o.get("urn") or o.get("laEstab")
            if lv == "LA" and code not in LAS:
                continue
            per = r["timePeriod"]["period"]
            label = next((t["label"] for t in meta["timePeriods"] if t["period"] == per), per)
            parent_la = loc.get(("LA", r["locations"].get("LA")), {}).get("code")
            out.append({
                "level": lv, "code": code, "name": o.get("label"), "urn": o.get("urn"),
                "parent_la": parent_la, "period": label,
                "filters": {fid_label[k]: opt_label[v] for k, v in r["filters"].items()},
                "values": {ind_label[k]: v for k, v in r["values"].items()},
            })
        if page >= doc["paging"]["totalPages"]:
            break
        page += 1
    return out


def num(v):
    """Parse an EES / DfE CSV value. Returns (value, suppressed)."""
    if v is None:
        return None, True
    s = str(v).strip().replace(",", "")
    if s.lower() in SUPPRESSED:
        return None, True
    try:
        return float(s), False
    except ValueError:
        return None, True


LEVEL_MAP = {"LA": "LA", "REG": "region", "NAT": "country"}
GEO_NAME = {**LAS, **COMPARATORS}


def mkrow(code, level, indicator, value, period, suppressed=False, breakdown=None, nm=None,
          den=None, name=None, **extra):
    r = {"code": code, "name": name or GEO_NAME.get(code, code), "level": level,
         "indicator": indicator, "value": None if value is None else round(value, 3),
         "period": period, "ci": None, "num": nm, "den": den, "breakdown": breakdown}
    if suppressed or value is None:
        r["value"] = None
        r["suppressed"] = True
    r.update(extra)
    return r


def ees_url(ds_id, version=None):
    q = f"?dataSetVersion={version}" if version else ""
    return f"POST {EES}/data-sets/{ds_id}/query{q}"


def ees_page(ds_id):
    return f"{EES_WEB}/data-catalogue/data-set/{ds_id}"


# --------------------------------------------------------------------------------------------
# GIAS
# --------------------------------------------------------------------------------------------
GIAS_HOSTS = [
    "https://ea-edubasepublic.service.gov.uk/edubasepublicdata/public/edubasealldata{d}.csv",
    # Same file served by the GIAS application's own download endpoint (used when the public
    # CDN host above does not resolve).
    "https://ea-edubase-api-prod.azurewebsites.net/edubase/downloads/public/edubasealldata{d}.csv",
]
GIAS_PAGE = "https://get-information-schools.service.gov.uk/Downloads"


def load_gias():
    """Return (rows, url) for the most recent GIAS all-establishments extract (<= 14 days old)."""
    today = dt.date.today()
    for back in range(15):
        d = (today - dt.timedelta(days=back)).strftime("%Y%m%d")
        cache = RAW / f"gias_edubasealldata{d}.csv"
        src = RAW / f"gias_edubasealldata{d}.url"
        if cache.exists():
            url = src.read_text().strip() if src.exists() else GIAS_HOSTS[1].format(d=d)
            text = cache.read_bytes().decode("cp1252", errors="replace")
            return list(csv.DictReader(io.StringIO(text))), url
        for tmpl in GIAS_HOSTS:
            url = tmpl.format(d=d)
            try:
                body = fetch(url, retries=1, timeout=300)
            except RuntimeError:
                continue
            if not body.lstrip(b"\xef\xbb\xbf").startswith(b'"URN"'):
                continue
            cache.write_bytes(body)
            src.write_text(url)
            return list(csv.DictReader(io.StringIO(body.decode("cp1252", errors="replace")))), url
    raise RuntimeError("no GIAS extract found in the last 15 days")


def gias_latlon(r):
    try:
        e, n = float(r["Easting"]), float(r["Northing"])
    except (TypeError, ValueError):
        return None, None
    if e <= 0 or n <= 0:
        return None, None
    lat, lon = osgb_to_wgs84(e, n)
    return round(lat, 6), round(lon, 6)


def to_int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def classify(r):
    """Return a provider category for a GIAS record, or None to exclude."""
    t = r["TypeOfEstablishment (name)"]
    grp = r["EstablishmentTypeGroup (name)"]
    phase = r["PhaseOfEducation (name)"]
    hi = to_int(r["StatutoryHighAge"]) or 0
    if grp == "Colleges":
        ft = r["FurtherEducationType (name)"]
        return "Sixth form college" if "Sixth Form" in ft else "FE college"
    if grp == "Universities" or t == "Higher education institutions":
        return "Higher education institution"
    if t in ("University technical college", "Studio schools"):
        return "UTC / studio school"
    if t in ("Academy 16-19 converter", "Academy 16 to 19 sponsor led", "Free schools 16 to 19",
             "Academy 16-19 sponsor led", "Free schools 16-19") or phase == "16 plus":
        return "16-19 school / sixth form"
    if grp == "Special schools" or "special" in t.lower():
        return "Special school (post-16)" if hi > 16 else None
    if t in ("Pupil referral unit", "Academy alternative provision converter",
             "Academy alternative provision sponsor led", "Free schools alternative provision"):
        return "Alternative provision" if hi >= 15 else None
    if grp == "Independent schools":
        return "Independent school (16+)" if hi > 16 else None
    if phase == "All-through":
        return "All-through school"
    if phase == "Secondary":
        return "Secondary school"
    return None  # primary, nursery, middle (9-13) and other phases are out of scope


def build_providers(gias, gias_url):
    rows, la_counts = [], {}
    for r in gias:
        if r["EstablishmentStatus (name)"] not in ("Open", "Open, but proposed to close"):
            continue
        cat = classify(r)
        if not cat:
            continue
        lat, lon = gias_latlon(r)
        la_code = OLD_LA.get(r["LA (code)"])
        dist = round(haversine_km(lat, lon, SITE["lat"], SITE["lon"]), 2) if lat is not None else None
        if la_code is None:
            # Neighbouring LAs: FE / sixth-form colleges only, within FE_RADIUS_KM of the site.
            if cat not in ("FE college", "Sixth form college") or dist is None or dist > FE_RADIUS_KM:
                continue
        hi, lo = to_int(r["StatutoryHighAge"]), to_int(r["StatutoryLowAge"])
        post16 = (cat in ("FE college", "Sixth form college", "16-19 school / sixth form",
                          "Higher education institution")
                  or r["OfficialSixthForm (name)"] == "Has a sixth form" or (hi or 0) > 16)
        fsm, _ = num(r["PercentageFSM"])
        pupils = to_int(r["NumberOfPupils"])
        attrs = {
            "urn": r["URN"], "ukprn": r["UKPRN"] or None, "category": cat,
            "type": r["TypeOfEstablishment (name)"], "phase": r["PhaseOfEducation (name)"],
            "age_range": f"{lo}-{hi}" if lo is not None and hi is not None else None,
            "sixth_form": r["OfficialSixthForm (name)"] or None, "post16": post16,
            "independent": r["EstablishmentTypeGroup (name)"] == "Independent schools",
            "fe_type": r["FurtherEducationType (name)"] if r["FurtherEducationType (name)"] not in ("", "Not applicable") else None,
            "pupils": pupils, "pct_fsm": fsm, "census_date": r["CensusDate"] or None,
            "capacity": to_int(r["SchoolCapacity"]),
            "gender": r["Gender (name)"] or None, "admissions": r["AdmissionsPolicy (name)"] or None,
            "trust": r["Trusts (name)"] or None,
            "ofsted_rating": None,  # not published in the GIAS extract; see meta.limitations
            "last_inspection": r.get("DateOfLastInspectionVisit") or None,
            "la": r["LA (name)"], "la_code": la_code or r["GSSLACode (name)"] or None,
            "in_bedfordshire": la_code is not None,
            "postcode": r["Postcode"] or None, "town": r["Town"] or None,
            "website": r["SchoolWebsite"] or None, "status": r["EstablishmentStatus (name)"],
            "dist_km": dist,
        }
        base = {"code": r["URN"], "name": r["EstablishmentName"], "level": "point",
                "period": gias_url.rsplit("edubasealldata", 1)[-1][:8], "ci": None, "num": None,
                "den": None, "breakdown": cat, "lat": lat, "lon": lon, "attrs": attrs}
        rows.append({**base, "indicator": "providers_pupils", "value": pupils})
        rows.append({**base, "indicator": "providers_pct_fsm", "value": fsm})
        if la_code:
            la_counts.setdefault(la_code, {}).setdefault(cat, 0)
            la_counts[la_code][cat] += 1
    # LA-level counts by category (and a Bedfordshire total).
    snap = rows[0]["period"] if rows else None
    tot = {}
    for la, cats in la_counts.items():
        for cat, n in cats.items():
            rows.append(mkrow(la, "LA", "providers_count", n, snap, breakdown=cat))
            tot[cat] = tot.get(cat, 0) + n
    for cat, n in tot.items():
        rows.append(mkrow(BEDS[0], BEDS[2], "providers_count", n, snap, breakdown=cat, name=BEDS[1]))
    return rows, la_counts


# --------------------------------------------------------------------------------------------
# Main
# --------------------------------------------------------------------------------------------
T = "Total"
DS_PUPILS_YEAR = "019e7403-0e46-7122-9bc2-3252d775517c"
DS_FSM = "019e7404-df19-71ce-90a8-f2e3db7dd7fa"
DS_SEN = "019df85e-ab00-7458-a4ff-b381997776cb"
DS_KS4_GEO = "18e39901-b47f-4a75-9c4b-d529e590d916"
DS_KS4_CHAR = "b3e19901-5d2b-b676-bb4c-e60937d74725"
DS_KS4_SCH = "19e39901-a96c-be76-b9c2-6af54ae076d2"
DS_1618 = "019d9133-665e-77fc-8492-b8131d4b1f4f"
DS_RET = "019d9139-4416-70c8-9275-ed2def6c2eb9"
DS_RET_NAT = "019d9138-5da3-767e-a1b7-4c2c146370fe"
DS_ABS = "019d209c-08dc-74b6-9edb-52d521406fcf"
SUSP_CSV = ("https://content.explore-education-statistics.service.gov.uk/api/data-set-files/"
            "59d8b51e-fea6-40f5-911a-0d916679d206/download")
SUSP_PAGE = f"{EES_WEB}/data-catalogue/data-set/59d8b51e-fea6-40f5-911a-0d916679d206"
PUB = f"{EES_WEB}/find-statistics/"


def all_total(ds_id, version=None, **override):
    meta = ees_meta(ds_id, version)
    f = {x["label"]: [T] for x in meta["filters"] if any(o["label"] == T for o in x["options"])}
    f.update(override)
    return f


def geo_level(lv):
    return LEVEL_MAP[lv]


def school_pipeline():
    years = [f"year group {i}" for i in range(1, 14)]
    inds = [f"Count of pupils in {y}" for y in years] + ["Count of pupils of all ages"]
    periods = ["2021/22", "2022/23", "2023/24", "2024/25", "2025/26"]
    res = ees_query(DS_PUPILS_YEAR, all_total(DS_PUPILS_YEAR), inds, periods=periods)
    latest = max(r["period"] for r in res)
    rows, base = [], {}
    for r in res:
        lv, code, per = geo_level(r["level"]), r["code"], r["period"]
        vals = {k: num(v)[0] for k, v in r["values"].items()}
        y = {i: vals.get(f"Count of pupils in year group {i}") for i in range(1, 14)}
        y7_11 = sum(y[i] for i in range(7, 12)) if all(y[i] is not None for i in range(7, 12)) else None
        y12_13 = (y[12] + y[13]) if y[12] is not None and y[13] is not None else None
        rows.append(mkrow(code, lv, "pipeline_pupils_y7_11", y7_11, per))
        rows.append(mkrow(code, lv, "pipeline_pupils_y12_13", y12_13, per))
        if per == latest:
            for i in range(7, 14):
                v, sup = num(r["values"].get(f"Count of pupils in year group {i}"))
                rows.append(mkrow(code, lv, "pipeline_pupils_by_ncy", v, per, sup, breakdown=f"Y{i}"))
            base[code] = (lv, y)
    # Bedfordshire sums for counts.
    by = {}
    for r in rows:
        if r["level"] == "LA" and r["value"] is not None:
            k = (r["indicator"], r["period"], r["breakdown"])
            by[k] = by.get(k, 0) + r["value"]
    for (ind, per, bd), v in by.items():
        rows.append(mkrow(BEDS[0], BEDS[2], ind, v, per, breakdown=bd, name=BEDS[1]))
    # Derived cohort roll-forward. Base: Jan census of academic year latest (e.g. 2025/26).
    base_ay = int(latest[:4])  # 2025 for 2025/26
    beds_y = {i: sum(base[c][1][i] or 0 for c in LAS if c in base) for i in range(1, 14)}
    base[BEDS[0]] = (BEDS[2], beds_y)
    for code, (lv, y) in base.items():
        for target in range(2026, 2035):
            # NC year N in AY base_ay/+1 is aged N+4 on 31 Aug base_ay; aged 16 at start of AY
            # `target` when N = 12 - (target - base_ay).
            def ncy_for(age):
                return age - 4 - (target - base_ay)
            n16 = ncy_for(16)
            v16 = y.get(n16) if 1 <= n16 <= 13 else None
            rows.append(mkrow(code, lv, "pipeline_aged16_by_year", v16, str(target),
                              breakdown=f"{target}/{(target + 1) % 100:02d} (from {latest} Y{n16})",
                              name=BEDS[1] if code == BEDS[0] else None))
            ns = [ncy_for(a) for a in (16, 17, 18)]
            if all(1 <= n <= 11 and y.get(n) is not None for n in ns):  # Y12-13 exclude FE
                v = sum(y[n] for n in ns)
                rows.append(mkrow(code, lv, "pipeline_aged16_18_by_year", v, str(target),
                                  breakdown=f"{target}/{(target + 1) % 100:02d} (from {latest} "
                                            f"Y{min(ns)}-Y{max(ns)})",
                                  name=BEDS[1] if code == BEDS[0] else None))
    # FSM % (state-funded secondary) - history.
    fsm = ees_query(DS_FSM, {"School type": ["State-funded secondary"],
                             "Pupil eligibility for free school meals": ["FSM eligible"],
                             "Breakdown of free-school meals groupings": ["All pupils"]},
                    ["Number of pupils", "Percentage of pupils"], periods=periods)
    fsm_tot = ees_query(DS_FSM, {"School type": ["State-funded secondary"],
                                 "Pupil eligibility for free school meals": [T],
                                 "Breakdown of free-school meals groupings": ["All pupils"]},
                        ["Number of pupils"], periods=periods)
    den = {(r["code"], r["period"]): num(r["values"]["Number of pupils"])[0] for r in fsm_tot}
    sums = {}
    for r in fsm:
        v, sup = num(r["values"]["Percentage of pupils"])
        n = num(r["values"]["Number of pupils"])[0]
        d = den.get((r["code"], r["period"]))
        rows.append(mkrow(r["code"], geo_level(r["level"]), "pipeline_fsm_pct_secondary", v,
                          r["period"], sup, nm=n, den=d))
        if r["level"] == "LA" and n is not None and d:
            s = sums.setdefault(r["period"], [0, 0])
            s[0] += n
            s[1] += d
    for per, (n, d) in sums.items():
        rows.append(mkrow(BEDS[0], BEDS[2], "pipeline_fsm_pct_secondary", 100 * n / d, per,
                          nm=n, den=d, name=BEDS[1]))
    # SEN (state-funded secondary): SEN support and EHCP %.
    sen = ees_query(DS_SEN, {"Phase type of school": ["State-funded secondary"],
                             "Hospital school flag": [T], "School type (detailed)": [T]},
                    ["Headcount of pupils", "Percentage of pupils"], periods=periods)
    tots = {(r["code"], r["period"]): num(r["values"]["Headcount of pupils"])[0]
            for r in sen if r["filters"]["Pupil SEN provision"] == T}
    ssum = {}
    for r in sen:
        prov = r["filters"]["Pupil SEN provision"]
        ind = {"Education, health and care plan": "pipeline_ehcp_pct_secondary",
               "SEN support / SEN without an EHC plan": "pipeline_sen_support_pct_secondary"}.get(prov)
        if not ind:
            continue
        v, sup = num(r["values"]["Percentage of pupils"])
        n = num(r["values"]["Headcount of pupils"])[0]
        d = tots.get((r["code"], r["period"]))
        rows.append(mkrow(r["code"], geo_level(r["level"]), ind, v, r["period"], sup, nm=n, den=d))
        if r["level"] == "LA" and n is not None and d:
            s = ssum.setdefault((ind, r["period"]), [0, 0])
            s[0] += n
            s[1] += d
    for (ind, per), (n, d) in ssum.items():
        rows.append(mkrow(BEDS[0], BEDS[2], ind, 100 * n / d, per, nm=n, den=d, name=BEDS[1]))
    return rows, latest


def ks4_la():
    inds = {
        "Average Attainment 8 score": "ks4_att8",
        "Percentage of pupils achieving grades 5 or above in English and maths GCSEs": "ks4_pct_em_5plus",
        "Percentage of pupils achieving grades 4 or above in English and maths GCSEs": "ks4_pct_em_4plus",
        "Number of pupils at the end of KS4": "ks4_pupils",
    }
    extra = ["Sum of Attainment 8 scores",
             "Number of pupils achieving grades 5 or above in English and maths GCSEs",
             "Number of pupils achieving grades 4 or above in English and maths GCSEs"]
    periods = ["2020/21", "2021/22", "2022/23", "2023/24", "2024/25", "2025/26"]
    res = ees_query(DS_KS4_GEO, {"School type": ["All state-funded"]}, list(inds) + extra,
                    periods=periods)
    rows, agg = [], {}
    for r in res:
        lv = geo_level(r["level"])
        v_ = {k: num(v) for k, v in r["values"].items()}
        pupils = v_["Number of pupils at the end of KS4"][0]
        numer = {"ks4_att8": v_["Sum of Attainment 8 scores"][0],
                 "ks4_pct_em_5plus": v_["Number of pupils achieving grades 5 or above in English and maths GCSEs"][0],
                 "ks4_pct_em_4plus": v_["Number of pupils achieving grades 4 or above in English and maths GCSEs"][0]}
        for lab, ind in inds.items():
            val, sup = v_[lab]
            extra_kw = {"note": "teacher-assessed grades; not comparable"} if r["period"] == "2020/21" else {}
            rows.append(mkrow(r["code"], lv, ind, val, r["period"], sup,
                              nm=numer.get(ind), den=pupils if ind in numer else None, **extra_kw))
        if r["level"] == "LA":
            a = agg.setdefault(r["period"], {"p": 0, "ks4_att8": 0, "ks4_pct_em_5plus": 0,
                                              "ks4_pct_em_4plus": 0, "ok": True})
            if pupils is None or any(x is None for x in numer.values()):
                a["ok"] = False
            else:
                a["p"] += pupils
                for k, x in numer.items():
                    a[k] += x
    for per, a in agg.items():
        if not a["ok"] or not a["p"]:
            continue
        rows.append(mkrow(BEDS[0], BEDS[2], "ks4_pupils", a["p"], per, name=BEDS[1]))
        rows.append(mkrow(BEDS[0], BEDS[2], "ks4_att8", a["ks4_att8"] / a["p"], per,
                          nm=a["ks4_att8"], den=a["p"], name=BEDS[1]))
        for k in ("ks4_pct_em_5plus", "ks4_pct_em_4plus"):
            rows.append(mkrow(BEDS[0], BEDS[2], k, 100 * a[k] / a["p"], per, nm=a[k], den=a["p"],
                              name=BEDS[1]))
    # EBacc entry: measure discontinued from 2025/26, so read the data set's v1.0.1 (to 2024/25).
    eb = ees_query(DS_KS4_GEO, {"School type": ["All state-funded"]},
                   ["Percentage of pupils entering the EBacc", "Number of pupils entering the EBacc",
                    "Number of pupils at the end of KS4"],
                   periods=periods[:-1], version="1.0.1")
    eagg = {}
    for r in eb:
        v, sup = num(r["values"]["Percentage of pupils entering the EBacc"])
        n = num(r["values"]["Number of pupils entering the EBacc"])[0]
        d = num(r["values"]["Number of pupils at the end of KS4"])[0]
        rows.append(mkrow(r["code"], geo_level(r["level"]), "ks4_pct_ebacc_entry", v, r["period"],
                          sup, nm=n, den=d))
        if r["level"] == "LA" and n is not None and d:
            s = eagg.setdefault(r["period"], [0, 0, 0])
            s[0] += n
            s[1] += d
            s[2] += 1
    for per, (n, d, k) in eagg.items():
        if k == 3:
            rows.append(mkrow(BEDS[0], BEDS[2], "ks4_pct_ebacc_entry", 100 * n / d, per, nm=n,
                              den=d, name=BEDS[1]))
    # Disadvantaged gap (A8 points): not-disadvantaged minus disadvantaged.
    f = all_total(DS_KS4_CHAR, **{"Disadvantaged status": ["Disadvantaged", "Not known to be disadvantaged"]})
    res = ees_query(DS_KS4_CHAR, f, ["Average Attainment 8 score", "Sum of Attainment 8 scores",
                                     "Number of pupils at the end of KS4"], periods=periods)
    grp = {}
    for r in res:
        k = (r["code"], r["level"], r["period"])
        st = "d" if r["filters"]["Disadvantaged status"] == "Disadvantaged" else "n"
        grp.setdefault(k, {})[st] = {x: num(v)[0] for x, v in r["values"].items()}
    bsum = {}
    for (code, lv, per), g in grp.items():
        if "d" not in g or "n" not in g:
            continue
        d, n = g["d"], g["n"]
        rows.append(mkrow(code, geo_level(lv), "ks4_att8_disadv", d["Average Attainment 8 score"], per,
                          nm=d["Sum of Attainment 8 scores"], den=d["Number of pupils at the end of KS4"]))
        rows.append(mkrow(code, geo_level(lv), "ks4_att8_nondisadv", n["Average Attainment 8 score"], per,
                          nm=n["Sum of Attainment 8 scores"], den=n["Number of pupils at the end of KS4"]))
        gap = (n["Average Attainment 8 score"] - d["Average Attainment 8 score"]
               if None not in (n["Average Attainment 8 score"], d["Average Attainment 8 score"]) else None)
        rows.append(mkrow(code, geo_level(lv), "ks4_att8_disadv_gap", gap, per))
        dp, tp = d["Number of pupils at the end of KS4"], n["Number of pupils at the end of KS4"]
        if dp is not None and tp is not None:
            rows.append(mkrow(code, geo_level(lv), "ks4_pct_disadvantaged", 100 * dp / (dp + tp), per,
                              nm=dp, den=dp + tp))
        if lv == "LA":
            b = bsum.setdefault(per, {"ds": 0, "dp": 0, "ns": 0, "np": 0, "k": 0})
            if None in (d["Sum of Attainment 8 scores"], dp, n["Sum of Attainment 8 scores"], tp):
                continue
            b["ds"] += d["Sum of Attainment 8 scores"]
            b["dp"] += dp
            b["ns"] += n["Sum of Attainment 8 scores"]
            b["np"] += tp
            b["k"] += 1
    for per, b in bsum.items():
        if b["k"] != 3:
            continue
        da, na = b["ds"] / b["dp"], b["ns"] / b["np"]
        rows.append(mkrow(BEDS[0], BEDS[2], "ks4_att8_disadv", da, per, nm=b["ds"], den=b["dp"], name=BEDS[1]))
        rows.append(mkrow(BEDS[0], BEDS[2], "ks4_att8_nondisadv", na, per, nm=b["ns"], den=b["np"], name=BEDS[1]))
        rows.append(mkrow(BEDS[0], BEDS[2], "ks4_att8_disadv_gap", na - da, per, name=BEDS[1]))
        rows.append(mkrow(BEDS[0], BEDS[2], "ks4_pct_disadvantaged", 100 * b["dp"] / (b["dp"] + b["np"]),
                          per, nm=b["dp"], den=b["dp"] + b["np"], name=BEDS[1]))
    for r in rows:
        if r["period"] == "2020/21":
            r["note"] = "teacher-assessed grades; not comparable with exam years"
    return rows


def ks4_school(gias_by_urn):
    inds = {
        "Average Attainment 8 score": "ks4s_att8",
        "Percentage of pupils achieving grades 5 or above in English and maths GCSEs": "ks4s_pct_em_5plus",
        "Percentage of pupils achieving grades 4 or above in English and maths GCSEs": "ks4s_pct_em_4plus",
        "Number of pupils at the end of KS4": "ks4s_pupils",
    }
    res = ees_query(DS_KS4_SCH, all_total(DS_KS4_SCH), list(inds), levels=(), school_las=True)
    rows, unmatched = [], []
    for r in res:
        g = gias_by_urn.get(str(r["urn"]))
        lat, lon = gias_latlon(g) if g else (None, None)
        if lat is None:
            unmatched.append(r["urn"])
        attrs = {"urn": r["urn"], "la": LAS.get(r["parent_la"]), "la_code": r["parent_la"],
                 "type": g["TypeOfEstablishment (name)"] if g else None,
                 "status": g["EstablishmentStatus (name)"] if g else None,
                 "postcode": g["Postcode"] if g else None,
                 "dist_km": round(haversine_km(lat, lon, SITE["lat"], SITE["lon"]), 2) if lat else None}
        for lab, ind in inds.items():
            v, sup = num(r["values"].get(lab))
            row = {"code": str(r["urn"]), "name": r["name"], "level": "point", "indicator": ind,
                   "value": v, "period": r["period"], "ci": None, "num": None, "den": None,
                   "breakdown": None, "lat": lat, "lon": lon, "attrs": attrs}
            if v is None:
                row["suppressed"] = True
            rows.append(row)
    return rows, unmatched


def ks5_la():
    cohorts = ["A level", "Applied general", "Tech level", "Technical certificate", "Level 3",
               "End of 16-18 study"]
    res = ees_query(DS_1618, {"Characteristic": ["All state-funded students"],
                              "Characteristic type": ["All Students"], "Exam cohort": cohorts},
                    ["APS per entry", "% achieving ≥ 2 substantial level 3 results",
                     "Number of students"])
    # England comes only as "All students" for some combos; fetch NAT state-funded explicitly too.
    rows = []
    for r in res:
        lv, co = geo_level(r["level"]), r["filters"]["Exam cohort"]
        aps, s1 = num(r["values"]["APS per entry"])
        sub, s2 = num(r["values"]["% achieving ≥ 2 substantial level 3 results"])
        n, s3 = num(r["values"]["Number of students"])
        if co in ("A level", "Applied general", "Tech level", "Technical certificate"):
            rows.append(mkrow(r["code"], lv, "ks5_aps_per_entry", aps, r["period"], s1, breakdown=co))
        if co in ("A level", "Level 3"):
            rows.append(mkrow(r["code"], lv, "ks5_pct_2_substantial_l3", sub, r["period"], s2,
                              breakdown=co))
        rows.append(mkrow(r["code"], lv, "ks5_students", n, r["period"], s3, breakdown=co))
    beds = {}
    for r in rows:
        if r["indicator"] == "ks5_students" and r["level"] == "LA" and r["value"] is not None:
            k = (r["period"], r["breakdown"])
            beds[k] = beds.get(k, 0) + r["value"]
    for (per, co), v in beds.items():
        rows.append(mkrow(BEDS[0], BEDS[2], "ks5_students", v, per, breakdown=co, name=BEDS[1]))
    # Retention (LA / region) + England from the national time series.
    ret = ees_query(DS_RET, {}, ["% retained", "% retained and assessed", "Number of students"])
    for r in ret:
        co = r["filters"]["Exam cohort"]
        if co == "Academic":
            continue
        bd = f'{co} ({r["filters"]["Qualification level"]})'
        v, sup = num(r["values"]["% retained and assessed"])
        rows.append(mkrow(r["code"], geo_level(r["level"]), "ks5_retained_assessed_pct", v,
                          r["period"], sup, breakdown=bd, den=num(r["values"]["Number of students"])[0]))
    retn = ees_query(DS_RET_NAT, {}, ["% retained and assessed", "Number of students"],
                     levels=("NAT",))
    for r in retn:
        co = r["filters"]["Exam cohort"]
        if co == "Academic" or r["period"] < "2020/21":
            continue
        bd = f'{co} ({r["filters"]["Qualification level"]})'
        v, sup = num(r["values"]["% retained and assessed"])
        rows.append(mkrow(r["code"], "country", "ks5_retained_assessed_pct", v, r["period"], sup,
                          breakdown=bd, den=num(r["values"]["Number of students"])[0]))
    for r in rows:
        if r["period"] in ("2020/21", "2021/22") and r["indicator"] != "ks5_retained_assessed_pct":
            r["note"] = ("2020/21 grades teacher-assessed; 2021/22 transitional grading - not "
                         "comparable with 2022/23 onwards")
    return rows


def absence_exclusions():
    rows = []
    periods = ["2020/21", "2021/22", "2022/23", "2023/24", "2024/25"]
    res = ees_query(DS_ABS, {"School type": ["State-funded secondary"],
                             "Absence type": ["Persistent absence", "Total pupils"]},
                    ["Count of pupil enrolments", "Percentage of pupil enrolments"], periods=periods)
    den = {(r["code"], r["period"]): num(r["values"]["Count of pupil enrolments"])[0]
           for r in res if r["filters"]["Absence type"] == "Total pupils"}
    agg = {}
    for r in res:
        if r["filters"]["Absence type"] != "Persistent absence":
            continue
        v, sup = num(r["values"]["Percentage of pupil enrolments"])
        n = num(r["values"]["Count of pupil enrolments"])[0]
        d = den.get((r["code"], r["period"]))
        rows.append(mkrow(r["code"], geo_level(r["level"]), "abs_persistent_pct_secondary", v,
                          r["period"], sup, nm=n, den=d))
        if r["level"] == "LA" and n is not None and d:
            a = agg.setdefault(r["period"], [0, 0, 0])
            a[0] += n
            a[1] += d
            a[2] += 1
    for per, (n, d, k) in agg.items():
        if k == 3:
            rows.append(mkrow(BEDS[0], BEDS[2], "abs_persistent_pct_secondary", 100 * n / d, per,
                              nm=n, den=d, name=BEDS[1]))
    # Suspensions (EES data-catalogue CSV; publication not in the API).
    text = fetch(SUSP_CSV, cache_name="ees_suspensions_by_geography.csv").decode("utf-8-sig")
    sagg = {}
    for r in csv.DictReader(io.StringIO(text)):
        if r["education_phase"] != "State-funded secondary":
            continue
        tp = r["time_period"]
        per = f"{tp[:4]}/{tp[4:]}"
        if per < "2020/21":
            continue
        gl = r["geographic_level"]
        if gl == "National":
            code, lv = r["country_code"], "country"
        elif gl == "Regional" and r["region_code"] == "E12000006":
            code, lv = r["region_code"], "region"
        elif gl == "Local authority" and r["new_la_code"] in LAS:
            code, lv = r["new_la_code"], "LA"
        else:
            continue
        hc = num(r["headcount"])[0]
        for col, ncol, ind in (("susp_rate", "suspension", "excl_suspension_rate_secondary"),
                               ("one_plus_susp_rate", "one_plus_susp", "excl_one_plus_susp_pct_secondary"),
                               ("perm_excl_rate", "perm_excl", "excl_perm_excl_rate_secondary")):
            v, sup = num(r[col])
            n = num(r[ncol])[0]
            rows.append(mkrow(code, lv, ind, v, per, sup, nm=n, den=hc))
            if lv == "LA" and n is not None and hc:
                a = sagg.setdefault((ind, per), [0, 0, 0])
                a[0] += n
                a[1] += hc
                a[2] += 1
    for (ind, per), (n, d, k) in sagg.items():
        if k == 3:
            rows.append(mkrow(BEDS[0], BEDS[2], ind, 100 * n / d, per, nm=n, den=d, name=BEDS[1]))
    return rows


def ind(id_, label, unit, polarity, description, cohort="16-19"):
    return {"id": id_, "label": label, "unit": unit, "cohort": cohort, "polarity": polarity,
            "description": description}


def latest_of(rows):
    ps = [r["period"] for r in rows if r.get("period")]
    return max(ps) if ps else None


def main():
    # ---------------- providers ----------------
    gias, gias_url = load_gias()
    gias_by_urn = {r["URN"]: r for r in gias}
    prov_rows, la_counts = build_providers(gias, gias_url)
    snap = gias_url.rsplit("edubasealldata", 1)[-1][:8]
    snap_h = f"{snap[:4]}-{snap[4:6]}-{snap[6:]}"
    save("providers", {
        "title": "Education and training providers for 14-19 and adult skills (GIAS)",
        "publisher": "Department for Education - Get Information About Schools",
        "source_url": GIAS_PAGE, "api_url": [gias_url, GIAS_HOSTS[0].format(d=snap)],
        "geography": "point (providers); LA counts; Bedfordshire total",
        "cohort": "16-19, 14-16, adult",
        "period": f"GIAS extract {snap_h}", "latest_period": snap,
        "frequency": "Daily extract", "next_update": "Daily",
        "access": "CSV download",
        "quality": ("Administrative register maintained by DfE from establishments and LAs; "
                    "status, type and address are reliable, but pupil numbers and % FSM are copied "
                    "from the last school census (CensusDate attribute) and some fields are "
                    "self-reported by establishments."),
        "limitations": (
            "Open establishments in Bedford, Central Bedfordshire and Luton that are secondary, "
            "all-through, 16-19, UTC/studio, FE/sixth-form college, HEI, alternative provision "
            "(age 15+), special schools with post-16 (statutory high age >16) and independent "
            "schools with 16+ provision; plus FE and sixth-form colleges in neighbouring LAs "
            f"within {FE_RADIUS_KM:.0f} km of the site. Middle schools (9-13, Bedford/Central "
            "Bedfordshire three-tier system) and primaries are excluded. Pupil numbers and % FSM "
            "are blank for FE colleges, HEIs and many independents (not collected via the school "
            "census) and FE college counts are a single head-office record - campuses are not "
            "separate rows, so the point is the registered address. GIAS no longer publishes "
            "Ofsted grades (ofsted_rating is null; use Ofsted management information). "
            "Independent training providers and employer apprenticeship providers are NOT "
            "included: no open download links UKPRN to delivery location. Distances are "
            "straight-line from the site (52.087N, 0.516W); OSGB36->WGS84 by Helmert (~2 m)."),
        "indicators": [
            ind("providers_pupils", "Pupils on roll (school census)", "count", "neutral",
                "Number of pupils from the latest school census held in GIAS (NumberOfPupils); "
                "one point per provider with attrs (urn, type, phase, age range, sixth form, "
                "% FSM, LA, postcode, website, dist_km).", "16-19, 14-16"),
            ind("providers_pct_fsm", "% pupils eligible for free school meals", "percent",
                "higher_is_worse", "PercentageFSM from GIAS (census-based) - deprivation marker "
                "for the provider's intake.", "16-19, 14-16"),
            ind("providers_count", "Number of open providers by category", "count", "neutral",
                "Count of open providers in each Bedfordshire LA by category (breakdown).",
                "16-19, 14-16, adult"),
        ],
    }, prov_rows)

    # ---------------- school_pipeline ----------------
    pipe_rows, pipe_latest = school_pipeline()
    save("school_pipeline", {
        "title": "Future 16-19 cohort: pupils by national curriculum year, FSM and SEN",
        "publisher": "Department for Education",
        "source_url": [PUB + "school-pupils-and-their-characteristics",
                       PUB + "special-educational-needs-in-england"],
        "api_url": [ees_url(DS_PUPILS_YEAR), ees_url(DS_FSM), ees_url(DS_SEN)],
        "geography": "LA, region, England, Bedfordshire (3 UAs)",
        "cohort": "16-19", "period": pipe_latest, "latest_period": pipe_latest,
        "frequency": "Annual", "next_update": "June 2027",
        "access": "API",
        "quality": ("Accredited official statistics from the January school census (all schools "
                    "including independent for year-group counts); full count, no sampling error."),
        "limitations": (
            "Counts are by school location (LA where the school is), not pupil residence - Luton "
            "and Central Bedfordshire have material cross-border flows (Hertfordshire, Milton "
            "Keynes, Buckinghamshire). Excludes home-educated and children missing education. "
            "FSM % and SEN % are state-funded secondary schools only; in Bedfordshire's "
            "three-tier areas middle schools are counted as secondary. The derived "
            "pipeline_aged16_* indicators are a simple cohort roll-forward with NO adjustment for "
            "migration, mortality, or movement into/out of independent schools - they indicate "
            "scale, not a forecast. Suppressed values (c/x/z/low) are null."),
        "indicators": [
            ind("pipeline_pupils_by_ncy", "Pupils by national curriculum year (Y7-Y13)", "count",
                "neutral", "Headcount of pupils in each NC year group, all school types, latest "
                "January census (breakdown = year group)."),
            ind("pipeline_pupils_y7_11", "Pupils in Y7-Y11", "count", "neutral",
                "Sum of NC years 7-11, all school types (history 2021/22 onwards)."),
            ind("pipeline_pupils_y12_13", "Pupils in school sixth forms (Y12-Y13)", "count",
                "neutral", "Sum of NC years 12-13 in schools (excludes FE/sixth-form colleges)."),
            ind("pipeline_aged16_by_year", "Derived: pupils reaching age 16 by academic year",
                "count", "neutral",
                f"DERIVED indicator. Cohort roll-forward of the {pipe_latest} census: pupils in NC "
                "year N are aged N+4 at the start of that year, so they are aged 16 at the start of "
                f"academic year T when N = 12 - (T - {pipe_latest[:4]}). E.g. today's Y6 is the "
                "cohort aged 16 in 2031/32. period/breakdown = target year (start of academic "
                "year). No migration/mortality adjustment."),
            ind("pipeline_aged16_18_by_year", "Derived: 16-18 cohort size by academic year",
                "count", "neutral",
                "DERIVED indicator. Sum of the three single-year cohorts aged 16, 17 and 18 at the "
                "start of target academic year T (the 16-19 study cohort), rolled forward from the "
                "latest census as for pipeline_aged16_by_year. Only years whose three cohorts are all "
                "still in Y1-Y11 today (full school coverage) are given - earlier years would rely "
                "on school-only Y12-13 counts that omit FE colleges. No migration/mortality adjustment."),
            ind("pipeline_fsm_pct_secondary", "% eligible for FSM (state-funded secondary)",
                "percent", "higher_is_worse",
                "Percentage of pupils in state-funded secondary schools known to be eligible for "
                "free school meals (January census)."),
            ind("pipeline_sen_support_pct_secondary", "% with SEN support (state-funded secondary)",
                "percent", "neutral", "Percentage of pupils on SEN support (no EHC plan) in "
                "state-funded secondary schools - indicates support needs in the future cohort."),
            ind("pipeline_ehcp_pct_secondary", "% with an EHC plan (state-funded secondary)",
                "percent", "neutral", "Percentage of pupils with an education, health and care "
                "plan in state-funded secondary schools."),
        ],
    }, pipe_rows)

    # ---------------- KS4 LA ----------------
    k4 = ks4_la()
    save("dfe_ks4_la", {
        "title": "Key stage 4 (GCSE) performance by local authority",
        "publisher": "Department for Education",
        "source_url": PUB + "key-stage-4-performance",
        "api_url": [ees_url(DS_KS4_GEO), ees_url(DS_KS4_GEO, "1.0.1"), ees_url(DS_KS4_CHAR)],
        "geography": "LA, region, England, Bedfordshire (3 UAs)",
        "cohort": "16-19", "period": latest_of(k4), "latest_period": latest_of(k4),
        "frequency": "Annual", "next_update": "February 2027 (revised 2025/26); October 2027 (2026/27 provisional)",
        "access": "API",
        "quality": ("Accredited official statistics (state-funded schools, by school location). "
                    "The latest year is provisional (October release) and is revised in February."),
        "limitations": (
            "2019/20 not published; 2020/21 teacher-assessed grades and 2021/22 transitional "
            "grading are not comparable with 2022/23 onwards (2020/21 rows carry a note). "
            "EBacc entry is taken from data set version 1.0.1 because the EBacc measure was "
            "removed from the 2025/26 release. Progress 8 is not available for 2024/25-2025/26 "
            "(no KS2 baseline) so is omitted. Disadvantaged gap here is the simple difference in "
            "average A8 between not-disadvantaged and disadvantaged pupils, not DfE's national "
            "gap index. Bedfordshire figures recomputed from summed numerators/denominators. "
            "LA = school location, state-funded only (independent schools excluded)."),
        "indicators": [
            ind("ks4_att8", "Average Attainment 8 score", "score", "higher_is_better",
                "Mean Attainment 8 score per pupil at the end of KS4, state-funded schools."),
            ind("ks4_pct_em_5plus", "% grade 5+ in English and maths", "percent",
                "higher_is_better", "Percentage of pupils achieving grade 5 or above in both "
                "English and maths GCSEs (strong pass)."),
            ind("ks4_pct_em_4plus", "% grade 4+ in English and maths", "percent",
                "higher_is_better", "Percentage achieving grade 4+ in English and maths (standard "
                "pass; below this, maths/English resits are compulsory post-16)."),
            ind("ks4_pct_ebacc_entry", "% entering the EBacc", "percent", "higher_is_better",
                "Percentage of pupils entering all English Baccalaureate pillars (to 2024/25)."),
            ind("ks4_pupils", "Pupils at the end of KS4", "count", "neutral",
                "Number of pupils at the end of key stage 4 (state-funded) - annual flow into "
                "post-16 education and training."),
            ind("ks4_att8_disadv", "Average A8 - disadvantaged pupils", "score",
                "higher_is_better", "Attainment 8 for pupils eligible for FSM in the last six "
                "years or looked after."),
            ind("ks4_att8_nondisadv", "Average A8 - other pupils", "score", "higher_is_better",
                "Attainment 8 for pupils not known to be disadvantaged."),
            ind("ks4_att8_disadv_gap", "Disadvantage gap in Attainment 8 (points)", "score",
                "higher_is_worse", "Average A8 of non-disadvantaged minus disadvantaged pupils."),
            ind("ks4_pct_disadvantaged", "% of KS4 cohort disadvantaged", "percent",
                "higher_is_worse", "Disadvantaged pupils as a share of the end-of-KS4 cohort."),
        ],
    }, k4)

    # ---------------- KS4 school ----------------
    k4s, unmatched = ks4_school(gias_by_urn)
    save("dfe_ks4_school", {
        "title": "Key stage 4 headline measures by secondary school (Bedfordshire)",
        "publisher": "Department for Education",
        "source_url": PUB + "key-stage-4-performance",
        "api_url": [ees_url(DS_KS4_SCH), gias_url],
        "geography": "point (schools in Bedford, Central Bedfordshire, Luton)",
        "cohort": "16-19", "period": latest_of(k4s), "latest_period": latest_of(k4s),
        "frequency": "Annual", "next_update": "February 2027 (revised 2025/26)",
        "access": "API",
        "quality": ("School performance tables data (accredited official statistics); latest year "
                    "provisional. Coordinates from GIAS by URN."),
        "limitations": (
            "State-funded mainstream schools with KS4 cohorts only; independent schools are not "
            "in this data set. Small-cohort and disclosive values are suppressed (c/x/z/low -> "
            "null, suppressed:true). A URN changes when a school converts to an academy, so "
            "history for a site can sit under two URNs. Middle schools have no KS4 results. "
            f"{len(set(unmatched))} URN(s) could not be located in GIAS." if unmatched else
            "State-funded mainstream schools with KS4 cohorts only; independent schools are not "
            "in this data set. Small-cohort and disclosive values are suppressed (c/x/z/low -> "
            "null, suppressed:true). A URN changes when a school converts to an academy, so "
            "history for a site can sit under two URNs."),
        "indicators": [
            ind("ks4s_att8", "School average Attainment 8", "score", "higher_is_better",
                "Average Attainment 8 score for the school's end-of-KS4 cohort."),
            ind("ks4s_pct_em_5plus", "School % grade 5+ English and maths", "percent",
                "higher_is_better", "Percentage of the school's pupils achieving 5+ in English and maths."),
            ind("ks4s_pct_em_4plus", "School % grade 4+ English and maths", "percent",
                "higher_is_better", "Percentage achieving 4+ in English and maths."),
            ind("ks4s_pupils", "School end-of-KS4 cohort", "count", "neutral",
                "Number of pupils at the end of KS4 in the school."),
        ],
    }, k4s)

    # ---------------- 16-18 ----------------
    k5 = ks5_la()
    save("dfe_16_18_la", {
        "title": "16-18 (key stage 5) attainment and retention by local authority",
        "publisher": "Department for Education",
        "source_url": PUB + "16-to-19-performance",
        "api_url": [ees_url(DS_1618), ees_url(DS_RET), ees_url(DS_RET_NAT)],
        "geography": "LA, region, England, Bedfordshire (3 UAs, student counts only)",
        "cohort": "16-19", "period": latest_of(k5), "latest_period": latest_of(k5),
        "frequency": "Annual", "next_update": "Provisional Nov/Dec 2026; revised spring 2027",
        "access": "API",
        "quality": ("Accredited official statistics covering state-funded schools and colleges; "
                    "LA is the location of the institution, not student residence."),
        "limitations": (
            "Average point scores cannot be summed or averaged to a Bedfordshire figure (no "
            "entry counts published), so Bedfordshire rows exist only for student counts. T level "
            "results are not published at LA level in this data set (national only) - a gap. "
            "Bedford's figures are dominated by Bedford College, which draws students from a wide "
            "area. 2020/21 TAGs and 2021/22 transitional grading are not comparable with later "
            "years. Retention data cover students in two-year programmes; England figures come "
            "from the national cohort time series. Small-cohort suppression (c/x/z) -> null."),
        "indicators": [
            ind("ks5_aps_per_entry", "Average point score per entry", "score", "higher_is_better",
                "APS per entry by qualification cohort (breakdown: A level, Applied general, Tech "
                "level, Technical certificate)."),
            ind("ks5_pct_2_substantial_l3", "% achieving 2+ substantial level 3 qualifications",
                "percent", "higher_is_better", "Share of level 3 students (or A level students) "
                "achieving at least two substantial level 3 qualifications."),
            ind("ks5_students", "Students at end of 16-18 study", "count", "neutral",
                "Number of students in each exam cohort at the end of 16-18 study (by institution "
                "location)."),
            ind("ks5_retained_assessed_pct", "% retained and assessed", "percent",
                "higher_is_better", "Percentage of students on two-year programmes retained to the "
                "end and assessed, by cohort and level."),
        ],
    }, k5)

    # ---------------- absence / exclusions ----------------
    ae = absence_exclusions()
    save("dfe_absence_exclusions", {
        "title": "Secondary persistent absence and suspensions by local authority",
        "publisher": "Department for Education",
        "source_url": [PUB + "pupil-absence-in-schools-in-england",
                       PUB + "suspensions-and-permanent-exclusions-in-england"],
        "api_url": [ees_url(DS_ABS), SUSP_CSV],
        "geography": "LA, region, England, Bedfordshire (3 UAs)",
        "cohort": "16-19", "period": latest_of(ae), "latest_period": latest_of(ae),
        "frequency": "Annual", "next_update": "March 2027 (absence); July 2027 (suspensions)",
        "access": "API and CSV download",
        "quality": ("Accredited official statistics from the school census (full academic year). "
                    "Rates are per 100 pupils enrolled."),
        "limitations": (
            "State-funded secondary schools only (excludes AP/PRUs, where at-risk pupils "
            "concentrate). Persistent absence = missing 10%+ of sessions. Suspension rate counts "
            "suspensions (events) per 100 pupils; one_plus counts pupils. 2020/21 affected by "
            "COVID-19 restrictions. The suspensions publication is not on the EES API so the "
            "data-catalogue CSV is used. Suppressed values (c/x/z/low) -> null."),
        "indicators": [
            ind("abs_persistent_pct_secondary", "% persistently absent (secondary)", "percent",
                "higher_is_worse", "Percentage of enrolments missing 10% or more of possible "
                "sessions - a leading indicator of NEET risk."),
            ind("excl_suspension_rate_secondary", "Suspension rate (secondary)", "rate",
                "higher_is_worse", "Suspensions per 100 pupils in state-funded secondary schools."),
            ind("excl_one_plus_susp_pct_secondary", "% pupils with 1+ suspension (secondary)",
                "percent", "higher_is_worse", "Pupils with at least one suspension per 100 pupils."),
            ind("excl_perm_excl_rate_secondary", "Permanent exclusion rate (secondary)", "rate",
                "higher_is_worse", "Permanent exclusions per 100 pupils."),
        ],
    }, ae)

    # ---------------- summary ----------------
    print("\nProviders by LA and category:")
    for la, cats in la_counts.items():
        print(f"  {LAS[la]}: " + ", ".join(f"{k} {v}" for k, v in sorted(cats.items())))
    nb = [r for r in prov_rows if r["indicator"] == "providers_pupils"
          and not r["attrs"]["in_bedfordshire"]]
    print("  neighbouring FE within radius:", [(r["name"], r["attrs"]["dist_km"]) for r in nb])
    for r in pipe_rows:
        if r["indicator"] == "pipeline_pupils_y7_11" and r["period"] == pipe_latest:
            print(f"  Y7-11 {r['name']}: {r['value']}")
        if r["indicator"] == "pipeline_aged16_18_by_year" and r["period"] == "2031":
            print(f"  16-18 cohort 2031/32 {r['name']}: {r['value']} ({r['breakdown']})")
    lk = latest_of(k4)
    for r in k4:
        if r["indicator"] in ("ks4_att8", "ks4_pct_em_5plus", "ks4_att8_disadv_gap") and r["period"] == lk:
            print(f"  {r['indicator']} {lk} {r['name']}: {r['value']}")
    if unmatched:
        print("  KS4 school URNs without GIAS coordinates:", sorted(set(map(str, unmatched))))


if __name__ == "__main__":
    main()
