"""People on Universal Credit by conditionality regime (DWP Stat-Xplore Open Data API).

Dataset written (site/data/dwp_uc.json):
  dwp_uc  UC_Monthly ("People on Universal Credit") by conditionality regime:
          LA / East of England / England monthly for 24 months,
          and LSOA21 (falling back to MSOA21) for the latest month.

Stat-Xplore needs a free API key sent in an `APIKey` header. The key is read
from (first found): env STATXPLORE_API_KEY, /etc/beds/statxplore.key,
~/.config/beds/statxplore.key. With no key the script prints one line and exits
0 without writing anything, so refresh scripts keep working.

    python3 fetch_dwp_uc.py              # fetch (needs key) and save
    python3 fetch_dwp_uc.py --dry-run    # print the exact /table query bodies, no network
    python3 fetch_dwp_uc.py --cached     # reuse responses saved in data/raw (default: live)
    python3 fetch_dwp_uc.py --schema     # print the field/valueset ids discovered from /schema

API docs: https://stat-xplore.dwp.gov.uk/webapi/online-help/Open-Data-API.html
(/schema GET for ids, /table POST with {database, measures, recodes, dimensions};
response: fields[].items[] {labels, uris} in dimension order and
cubes[<measure id>].values as nested arrays in the same order).

Field and value ids: the database, measure, month, geography (COA_CODE) and
conditionality field ids are the ones /schema publishes for UC_Monthly. Geography
value ids are built as <valueset id with str:valueset: -> str:value:>:<GSS code>,
the pattern in the documented example. Valueset ids are discovered from
/schema/<geography field> at run time by label; the constants below are only
fallbacks (used verbatim by --dry-run). Conditionality and month values are NOT
hard-coded: the conditionality field is returned in full and classified by
label, and the latest month is read from the LA response.

UNTESTED against the live API (no key was available when this was written); the
response parser is unit-tested in tests/test_dwp_uc.py against the documented shape.
"""
import hashlib
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

from common import COMPARATORS, LAS, OUT, RAW, UA, save

BASE = "https://stat-xplore.dwp.gov.uk/webapi/rest/v1"
KEY_ENV = "STATXPLORE_API_KEY"
KEY_FILES = [pathlib.Path("/etc/beds/statxplore.key"),
             pathlib.Path.home() / ".config" / "beds" / "statxplore.key"]
USE_CACHE = "--cached" in sys.argv  # monthly data: fetch live by default

DB = "str:database:UC_Monthly"
MEASURE = "str:count:UC_Monthly:V_F_UC_CASELOAD_FULL"
F_MONTH = "str:field:UC_Monthly:F_UC_DATE:DATE_NAME"
F_GEO = "str:field:UC_Monthly:V_F_UC_CASELOAD_FULL:COA_CODE"  # National - Regional - LA - OAs
F_COND = "str:field:UC_Monthly:V_F_UC_CASELOAD_FULL:CCCONDITIONALITY_REGIME"
# Fallback valueset ids (2021 Census geography hierarchy). LA_TO_REGION and
# MSOA_TO_LA are seen in published client code; the others follow the same naming
# and are replaced by the ids /schema reports whenever a key is available.
VALUESETS = {
    "la": "str:valueset:UC_Monthly:V_F_UC_CASELOAD_FULL:COA_CODE:V_C_MASTERGEOG21_LA_TO_REGION",
    "region": "str:valueset:UC_Monthly:V_F_UC_CASELOAD_FULL:COA_CODE:V_C_MASTERGEOG21_REGION_TO_COUNTRY",
    "country": "str:valueset:UC_Monthly:V_F_UC_CASELOAD_FULL:COA_CODE:V_C_MASTERGEOG21_COUNTRY_TO_GB",
    "lsoa": "str:valueset:UC_Monthly:V_F_UC_CASELOAD_FULL:COA_CODE:V_C_MASTERGEOG21_LSOA_TO_MSOA",
    "msoa": "str:valueset:UC_Monthly:V_F_UC_CASELOAD_FULL:COA_CODE:V_C_MASTERGEOG21_MSOA_TO_LA",
}
VALUESET_LABELS = {  # valueset label regex used to pick ids from /schema
    "la": r"local authorit",
    "region": r"^region",
    "country": r"^country",
    "lsoa": r"lower layer|\blsoa\b",
    "msoa": r"middle layer|\bmsoa\b",
}
GB = {"code": "K03000001", "name": "Great Britain", "level": "country"}
BEDS = {"code": "BEDS", "name": "Bedfordshire (3 UAs)", "level": "county"}
MONTHS = 24

# Conditionality label (lower-case, normalised dashes) -> indicator id.
COND = {
    "searching for work": "uc_searching",
    "working - with requirements": "uc_working_req",
    "no work requirements": "uc_nwr",
    "planning for work": "uc_planning_preparing",
    "preparing for work": "uc_planning_preparing",
    "working - no requirements": "uc_working_noreq",
}
COND_OTHER = "uc_cond_unknown"  # "Unknown or missing" - kept only inside uc_people


# --------------------------------------------------------------------------
# key + HTTP
def api_key():
    k = os.environ.get(KEY_ENV, "").strip()
    if k:
        return k
    for p in KEY_FILES:
        try:
            k = p.read_text().strip()
        except OSError:
            continue
        if k:
            return k
    return None


def call(key, path, body=None):
    """GET (body None) or POST JSON to the API; save the response in data/raw."""
    url = BASE + path
    data = None if body is None else json.dumps(body, sort_keys=True).encode()
    tag = hashlib.sha1(url.encode() + (data or b"")).hexdigest()[:12]
    cache = RAW / f"statxplore_{tag}.json"
    if cache.exists() and USE_CACHE:
        return json.loads(cache.read_text())
    headers = {"APIKey": key, "User-Agent": UA, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers,
                                 method="GET" if data is None else "POST")
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            text = r.read().decode("utf-8")
            remaining = r.headers.get("X-RateLimit-Remaining")
    except urllib.error.HTTPError as e:
        msg = e.read().decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"Stat-Xplore {e.code} on {path}: {msg}") from None
    if remaining is not None and int(remaining) < 50:
        print(f"  warning: only {remaining} Stat-Xplore requests left in this rate-limit window")
    RAW.mkdir(parents=True, exist_ok=True)
    cache.write_text(text)
    return json.loads(text)


def discover_valuesets(key):
    """Map geography levels -> valueset ids from /schema/<F_GEO>, by label."""
    # A field's children are its valuesets (a handful, well under the 100-item page
    # size at which /schema paginates via the Link header).
    doc = call(key, "/schema/" + urllib.parse.quote(F_GEO, safe=""))
    kids = list(doc.get("children") or [])
    found = dict(VALUESETS)
    hit = set()
    for k in kids:
        lab = (k.get("label") or "").lower()
        for lvl, rx in VALUESET_LABELS.items():
            if lvl not in hit and re.search(rx, lab) and str(k.get("id", "")).startswith(
                    "str:valueset:"):
                found[lvl] = k["id"]
                hit.add(lvl)
    missing = set(VALUESETS) - hit
    if missing:
        print(f"  warning: /schema did not list valuesets for {sorted(missing)}; "
              f"using fallback ids. Children seen: {[k.get('label') for k in kids]}")
    return found, kids


def value_id(valueset_id, code):
    return valueset_id.replace("str:valueset:", "str:value:", 1) + ":" + code


# --------------------------------------------------------------------------
# queries
def la_query(vs):
    """All months x conditionality (all values + total) x LA/region/England.

    No geography total: with a map, a field total sums the mapped items (LAs + region +
    England), which would be meaningless, so Great Britain is not requested.
    """
    geo_map = ([[value_id(vs["la"], c)] for c in LAS]
               + [[value_id(vs["region"], "E12000006")], [value_id(vs["country"], "E92000001")]])
    return {
        "database": DB,
        "measures": [MEASURE],
        "recodes": {
            F_GEO: {"map": geo_map, "total": False},
            F_COND: {"total": True},
            F_MONTH: {"total": False},
        },
        "dimensions": [[F_GEO], [F_MONTH], [F_COND]],
    }


def small_area_query(vs, level, codes, month_uri):
    """Latest month x conditionality (+ total) for a list of LSOA/MSOA codes."""
    return {
        "database": DB,
        "measures": [MEASURE],
        "recodes": {
            F_GEO: {"map": [[value_id(vs[level], c)] for c in codes], "total": False},
            F_MONTH: {"map": [[month_uri]], "total": False},
            F_COND: {"total": True},
        },
        "dimensions": [[F_GEO], [F_MONTH], [F_COND]],
    }


# --------------------------------------------------------------------------
# response parsing (unit-tested)
def is_total(item):
    t = str(item.get("type", "")).lower()
    labels = item.get("labels") or []
    return t == "total" or not item.get("uris") or (len(labels) == 1 and labels[0] == "Total")


def parse_table(resp, measure=MEASURE):
    """Flatten a /table response into a list of cells.

    Each cell: {"value": number|None, "items": [(field_uri, label, uri|None), ...]} with one
    item per dimension in response order; uri None marks a Total item.
    """
    fields = resp["fields"]
    cubes = resp["cubes"]
    if isinstance(cubes, dict):
        cube = cubes.get(measure) or next(iter(cubes.values()))
    else:  # documented as an array, one item per measure
        cube = cubes[0]
        if isinstance(cube, dict) and measure in cube:
            cube = cube[measure]
    values = cube["values"]
    axes = []
    for f in fields:
        axis = []
        for it in f["items"]:
            uri = None if is_total(it) else it["uris"][0]
            axis.append((f["uri"], " + ".join(it.get("labels") or []), uri))
        axes.append(axis)
    out = []

    def walk(v, depth, picked):
        if depth == len(axes):
            out.append({"value": None if v is None else (int(v) if float(v).is_integer() else v),
                        "items": list(picked)})
            return
        if len(v) != len(axes[depth]):
            raise ValueError(f"cube axis {depth} has {len(v)} cells, field has "
                             f"{len(axes[depth])} items")
        for i, sub in enumerate(v):
            walk(sub, depth + 1, picked + [axes[depth][i]])

    walk(values, 0, [])
    return out


def code_of(uri):
    """GSS / month code = last ':'-separated part of a value uri."""
    return uri.rsplit(":", 1)[-1]


def cond_indicator(label):
    lab = re.sub(r"\s*[-–—]\s*", " - ", label.strip().lower())
    return COND.get(lab, COND_OTHER)


def tabulate(cells):
    """cells -> {(geo_code|'GB', month_code, month_label): {indicator: value}}.

    uc_people is the conditionality Total; regimes are summed into their indicator
    (planning + preparing -> uc_planning_preparing).
    """
    out = {}
    for c in cells:
        (_, _, geo_uri), (_, month_label, month_uri), (_, cond_label, cond_uri) = c["items"]
        if month_uri is None:
            continue
        key = ("GB" if geo_uri is None else code_of(geo_uri), code_of(month_uri), month_label)
        d = out.setdefault(key, {})
        ind = "uc_people" if cond_uri is None else cond_indicator(cond_label)
        if c["value"] is None:
            d.setdefault(ind, None)
        elif d.get(ind) is None:
            d[ind] = c["value"]
        else:
            d[ind] += c["value"]
    return out


# --------------------------------------------------------------------------
# denominators
def load_pop():
    """{(code, year): pop 16-64} from pop_mye (LA/region/England/BEDS) and pop_lsoa (LSOA)."""
    pop = {}
    p = OUT / "pop_mye.json"
    if p.exists():
        for r in json.loads(p.read_text())["rows"]:
            if r["indicator"] == "pop_mye_16_64" and r["value"]:
                pop[(r["code"], int(r["period"][-4:]))] = r["value"]
    p = OUT / "pop_lsoa.json"
    if p.exists():
        for r in json.loads(p.read_text())["rows"]:
            if r["indicator"] == "popsa_16_64" and r["level"] in ("LSOA", "MSOA") and r["value"]:
                pop[(r["code"], int(r["period"][-4:]))] = r["value"]
    return pop


def pop_for(pop, code, year):
    yrs = sorted(y for (c, y) in pop if c == code)
    if not yrs:
        return None, None
    y = max([y for y in yrs if y <= year] or yrs[:1])
    return pop[(code, y)], y


# --------------------------------------------------------------------------
IND_ORDER = ["uc_people", "uc_searching", "uc_working_req", "uc_nwr", "uc_planning_preparing",
             "uc_working_noreq"]
INDICATORS = [
    dict(id="uc_people", label="People on Universal Credit", unit="count",
         cohort="25+ inactive, 18-24", polarity="neutral",
         description="All people on UC on the count date (all conditionality regimes incl. "
                     "unknown/missing)."),
    dict(id="uc_searching", label="UC: Searching for work", unit="count",
         cohort="25+ inactive, 18-24", polarity="higher_is_worse",
         description="Not working or very low earnings; required to look for work (the UC part "
                     "of the claimant count)."),
    dict(id="uc_working_req", label="UC: Working - with requirements", unit="count",
         cohort="25+ inactive, 18-24", polarity="neutral",
         description="In work but could earn more, or not working with a low-earning partner."),
    dict(id="uc_nwr", label="UC: No work requirements", unit="count",
         cohort="25+ inactive, 18-24", polarity="higher_is_worse",
         description="Not expected to work at present (mainly limited capability for work-"
                     "related activity on health grounds, carers, child under 1, students, "
                     "over state pension age) - the 'economically inactive on UC' pool."),
    dict(id="uc_planning_preparing", label="UC: Planning for work + Preparing for work",
         unit="count", cohort="25+ inactive, 18-24", polarity="neutral",
         description="Expected to work in future: lone parent/lead carer of a child aged 1 "
                     "(planning) or aged 2, or limited capability for work (preparing)."),
    dict(id="uc_working_noreq", label="UC: Working - no requirements", unit="count",
         cohort="25+ inactive, 18-24", polarity="neutral",
         description="Individual or household earnings above the conditionality threshold."),
    dict(id="uc_nwr_rate", label="UC no work requirements per 100 residents aged 16-64",
         unit="rate", cohort="25+ inactive, 18-24", polarity="higher_is_worse",
         description="uc_nwr / ONS population aged 16-64 x 100 (pop_mye for LA/region/England/"
                     "BEDS, small-area pop_lsoa for LSOAs; nearest mid-year estimate at or "
                     "before the month). Numerator includes some people aged 65+."),
]


def geo_of(code, lsoas):
    if code == "GB":
        return GB
    if code in LAS:
        return {"code": code, "name": LAS[code], "level": "LA"}
    if code == "E12000006":
        return {"code": code, "name": COMPARATORS[code], "level": "region"}
    if code == "E92000001":
        return {"code": code, "name": COMPARATORS[code], "level": "country"}
    if code in lsoas:
        return {"code": code, "name": lsoas[code]["name"], "level": "LSOA", "la": lsoas[code]["la"]}
    for c, v in lsoas.items():  # MSOA fallback
        if v.get("msoa") == code:
            return {"code": code, "name": code, "level": "MSOA", "la": v["la"]}
    raise KeyError(code)


def make_row(geo, ind, value, period, **kw):
    r = {"code": geo["code"], "name": geo["name"], "level": geo["level"], "indicator": ind,
         "value": value, "period": period}
    if geo.get("la"):
        r["la"] = geo["la"]
    for k, v in kw.items():
        if v is not None:
            r[k] = v
    if value is None:
        r["suppressed"] = True
    return r


def build_rows(la_tab, small_tab, lsoas, pop):
    """Turn tabulated responses into contract rows (LA monthly + BEDS + small area latest)."""
    months = sorted({(m, lab) for (_, m, lab) in la_tab})[-MONTHS:]
    keep = {m for m, _ in months}
    latest_code, latest_label = months[-1]
    rows = []
    beds = {}
    for (g, m, lab), d in sorted(la_tab.items()):
        if m not in keep:
            continue
        geo = geo_of(g, lsoas)
        for ind in IND_ORDER:
            if ind in d:
                rows.append(make_row(geo, ind, d[ind], lab, series="monthly"))
                if g in LAS:
                    b = beds.setdefault((m, lab), {})
                    b[ind] = None if d[ind] is None or b.get(ind, 0) is None else b.get(ind, 0) + d[ind]
        rows += rate_rows(geo, d, m, lab, pop)
    for (m, lab), d in sorted(beds.items()):
        for ind in IND_ORDER:
            if ind in d:
                rows.append(make_row(BEDS, ind, d[ind], lab, series="monthly"))
        rows += rate_rows(BEDS, d, m, lab, pop)
    for (g, m, lab), d in sorted(small_tab.items()):
        if g == "GB":
            continue
        geo = geo_of(g, lsoas)
        for ind in IND_ORDER:
            if ind in d:
                rows.append(make_row(geo, ind, d[ind], lab))
        rows += rate_rows(geo, d, m, lab, pop)
    return rows, latest_label


def rate_rows(geo, d, month_code, label, pop):
    n = d.get("uc_nwr")
    den, y = pop_for(pop, geo["code"], int(month_code[:4]))
    if n is None or not den:
        return []
    return [make_row(geo, "uc_nwr_rate", round(100 * n / den, 2), label, num=n, den=den,
                     series="monthly" if geo["level"] not in ("LSOA", "MSOA") else None)]


# --------------------------------------------------------------------------
def load_lsoas():
    p = OUT / "geo" / "lookup_lsoa.json"
    return json.loads(p.read_text())


def main():
    lsoas = load_lsoas()
    if "--dry-run" in sys.argv:
        vs = VALUESETS
        print("# 1. POST /table - LA/region/England, all months, all regimes")
        print(json.dumps(la_query(vs), indent=1))
        print("\n# 2. POST /table - LSOA21, latest month (month uri is taken from response 1; "
              "shown here as C_UC_DATE:<YYYYMM>)")
        q = small_area_query(vs, "lsoa", sorted(lsoas),
                             "str:value:UC_Monthly:F_UC_DATE:DATE_NAME:C_UC_DATE:<YYYYMM>")
        print(json.dumps(q, indent=1))
        print(f"\n# ({len(lsoas)} LSOA21 values; on HTTP error the script retries with "
              f"{len({v['msoa'] for v in lsoas.values()})} MSOA21 values via {vs['msoa']})")
        return

    key = api_key()
    if not key:
        print(f"fetch_dwp_uc: no Stat-Xplore API key ({KEY_ENV} or "
              f"{' / '.join(map(str, KEY_FILES))}); skipping, nothing written.")
        return

    vs, kids = discover_valuesets(key)
    if "--schema" in sys.argv:
        print(json.dumps({"geo_field_children": kids, "valuesets_used": vs}, indent=1))
        return

    api_urls = [f"{BASE}/schema/{urllib.parse.quote(F_GEO, safe='')}"]
    q1 = la_query(vs)
    la_tab = tabulate(parse_table(call(key, "/table", q1)))
    api_urls.append(f"POST {BASE}/table " + json.dumps(q1, separators=(",", ":")))
    months = sorted({(m, lab) for (_, m, lab) in la_tab})
    latest_code = months[-1][0]
    month_uri = f"str:value:UC_Monthly:F_UC_DATE:DATE_NAME:C_UC_DATE:{latest_code}"

    small_level = "LSOA21"
    try:
        q2 = small_area_query(vs, "lsoa", sorted(lsoas), month_uri)
        small_tab = tabulate(parse_table(call(key, "/table", q2)))
    except RuntimeError as e:
        print(f"  LSOA query failed ({e}); falling back to MSOA21")
        small_level = "MSOA21"
        q2 = small_area_query(vs, "msoa", sorted({v["msoa"] for v in lsoas.values()}), month_uri)
        small_tab = tabulate(parse_table(call(key, "/table", q2)))
    api_urls.append(f"POST {BASE}/table " + json.dumps(
        dict(q2, recodes=dict(q2["recodes"], **{F_GEO: {"map": f"<{len(q2['recodes'][F_GEO]['map'])} "
                                                       f"{small_level} values>"}})),
        separators=(",", ":")))

    rows, latest = build_rows(la_tab, small_tab, lsoas, load_pop())
    meta = {
        "title": "People on Universal Credit by conditionality regime",
        "publisher": "Department for Work and Pensions (Stat-Xplore)",
        "source_url": "https://stat-xplore.dwp.gov.uk/",
        "api_url": api_urls,
        "geography": f"LA, region, England, county (24 months); {small_level} "
                     "(latest month)",
        "cohort": "25+ inactive, 18-24",
        "period": latest,
        "latest_period": latest,
        "frequency": "Monthly",
        "next_update": "Monthly (DWP UC statistics, usually second Tuesday of the month)",
        "access": "API",
        "quality": ("Official statistics from DWP's UC administrative system; latest month is "
                    "provisional (expected within 2% of final). Rates are computed by this "
                    "pipeline from ONS mid-year / small-area population aged 16-64."),
        "limitations": (
            "Stat-Xplore applies statistical disclosure control (cell perturbation), so small "
            "LSOA cells are noisy and components may not sum exactly to totals; BEDS sums the "
            "three perturbed LA counts. Geography is claimant residence (postcode -> Census "
            "2021 output area). Conditionality reflects circumstances on the count date and "
            "can disagree with the employment indicator. 'No work requirements' mixes "
            "health-related limited capability for work and work-related activity, carers, "
            "parents of under-1s, students and people over state pension age; it is a proxy "
            "for the inactive-on-benefit pool, not a measure of capacity to work. Legacy "
            "benefits (ESA, income support, JSA) are excluded, so areas further from full "
            "UC migration under-count the benefit-inactive population."),
        "indicators": INDICATORS,
        "database": DB,
        "untested_note": "Fetcher written without a live API key; verify ids with --schema.",
    }
    save("dwp_uc", meta, rows)
    get = {(r["code"], r["indicator"], r["period"]): r["value"] for r in rows}
    print(f"\nSummary ({latest})")
    for g, nm in list(LAS.items()) + [("BEDS", BEDS["name"])]:
        print(f"  {nm:24s} UC people {get.get((g, 'uc_people', latest))}  NWR "
              f"{get.get((g, 'uc_nwr', latest))}  NWR per 100 16-64 "
              f"{get.get((g, 'uc_nwr_rate', latest))}")


if __name__ == "__main__":
    main()
