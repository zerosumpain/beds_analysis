"""Housing affordability, childcare supply and FE/skills inspection context for Bedfordshire.

Datasets written (see CONTRACT.md):
  affordability  ONS house price to residence-based earnings ratios (median, lower quartile),
                 ONS Price Index of Private Rents (PIPR) average monthly rent by LA (overall and
                 by bedrooms), and a derived rent share of full-time National Living Wage pay
  childcare      Ofsted childcare providers and inspections MI: Early Years Register providers and
                 places by LA, plus places per 100 children aged 0-4 (ONS MYE via Nomis NM_2002_1)
  ofsted_fe      Ofsted further education and skills inspections MI: providers headquartered in the
                 three LAs (points where they match GIAS providers, else provider rows) and LA,
                 region and England counts by grade

Sources are discovered at run time: ONS dataset pages (latest .xlsx link) and the GOV.UK content API
for Ofsted's statistical-data-set pages (latest attachment by title). Spreadsheets are parsed with
zipfile + xml.etree (stdlib only).
"""
import csv
import datetime as dt
import io
import json
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile

from common import COMPARATORS, LAS, OUT, RAW, fetch, save

REFRESH = "--refresh" in sys.argv
ONS = "https://www.ons.gov.uk"
GOVUK_API = "https://www.gov.uk/api/content"
NOMIS = "https://www.nomisweb.co.uk/api/v01/dataset/"

AFF_PAGE = (f"{ONS}/peoplepopulationandcommunity/housing/datasets/"
            "ratioofhousepricetoresidencebasedearningslowerquartileandmedian")
PIPR_PAGE = (f"{ONS}/economy/inflationandpriceindices/datasets/"
             "priceindexofprivaterentsukmonthlypricestatistics")
CC_PATH = "/government/statistical-data-sets/childcare-providers-and-inspections-management-information"
FE_SERIES = ("/government/statistical-data-sets/further-education-and-skills-inspections-and-outcomes-"
             "management-information-from-november-2025-to-august-2026")

# Full-time National Living Wage pay used for the rent-share indicator (rate from 1 April 2026).
NLW_HOURLY = 12.71
NLW_HOURS = 37.5
NLW_ANNUAL = round(NLW_HOURLY * NLW_HOURS * 52, 2)  # 24,784.50

GEO_NAME = {**LAS, **COMPARATORS}
LA_BY_NAME = {v: k for k, v in LAS.items()}
BEDS = ("BEDS", "Bedfordshire (3 UAs)", "county")
ENGLISH_REGIONS = {"North East", "North West", "Yorkshire and The Humber", "East Midlands",
                   "West Midlands", "East of England", "London", "South East", "South West"}


def level_of(code):
    if code == "BEDS":
        return "county"
    return {"E12": "region", "E92": "country"}.get(code[:3], "LA")


def mkrow(code, indicator, value, period, breakdown=None, nm=None, den=None, nd=2, **extra):
    r = {"code": code, "name": BEDS[1] if code == "BEDS" else GEO_NAME.get(code, code),
         "level": level_of(code), "indicator": indicator,
         "value": None if value is None else round(value, nd), "period": period, "ci": None,
         "num": nm, "den": den, "breakdown": breakdown}
    if value is None:
        r["suppressed"] = True
    r.update(extra)
    return r


def ind(i, label, unit, cohort, polarity, description):
    return {"id": i, "label": label, "unit": unit, "cohort": cohort, "polarity": polarity,
            "description": description}


def get(url, cache_name):
    """Fetch through the data/raw cache; --refresh re-downloads."""
    p = RAW / cache_name
    if REFRESH and p.exists():
        p.unlink()
    return fetch(url, cache_name, timeout=300)


def num(v):
    if v is None:
        return None
    s = str(v).strip().replace(",", "")
    if s in ("", "-", "[x]", "[z]", "[c]", ":", "..", "x", "c"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


# --------------------------------------------------------------------------------------------
# Spreadsheet readers (stdlib)
# --------------------------------------------------------------------------------------------
XNS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}


def _col(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + ord(ch) - 64
    return n - 1


def xlsx_sheet(blob, name):
    """Return the rows (lists of strings) of one worksheet in an .xlsx file."""
    z = zipfile.ZipFile(io.BytesIO(blob))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target")
            for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    target = None
    for s in wb.find("m:sheets", XNS):
        if s.get("name") == name:
            target = rels[s.get("{%s}id" % XNS["r"])].lstrip("/")
            target = target if target.startswith("xl/") else "xl/" + target
    if not target:
        raise KeyError(f"sheet {name} not found")
    ss = []
    if "xl/sharedStrings.xml" in z.namelist():
        for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", XNS):
            ss.append("".join(t.text or "" for t in si.iter("{%s}t" % XNS["m"])))
    rows = []
    for _, el in ET.iterparse(z.open(target)):
        if el.tag != "{%s}row" % XNS["m"]:
            continue
        cells = {}
        for c in el.findall("m:c", XNS):
            v, t = c.find("m:v", XNS), c.get("t")
            if t == "inlineStr":
                val = "".join(x.text or "" for x in c.iter("{%s}t" % XNS["m"]))
            elif v is None:
                continue
            elif t == "s":
                val = ss[int(v.text)]
            else:
                val = v.text
            cells[_col(c.get("r"))] = val
        rows.append([cells.get(i, "") for i in range(max(cells) + 1)] if cells else [])
        el.clear()
    return rows


def excel_month(serial):
    d = dt.date(1899, 12, 30) + dt.timedelta(days=int(float(serial)))
    return d.strftime("%b %Y"), d


# --------------------------------------------------------------------------------------------
# 1. Affordability
# --------------------------------------------------------------------------------------------
def ons_latest_xlsx(page, cache):
    html = get(page, cache).decode("utf-8", errors="replace")
    links = re.findall(r'href="(/file\?uri=[^"]+\.xlsx)"', html)
    if not links:
        raise RuntimeError(f"no xlsx link on {page}")
    return ONS + links[0]


def ratio_table(blob, sheet, code_col, first_year_col, years):
    rows = xlsx_sheet(blob, sheet)
    hdr = next(r for r in rows if r and r[0] in ("Code", "Country/Region code"))
    out = {}
    for r in rows[rows.index(hdr) + 1:]:
        if len(r) <= code_col:
            continue
        code = r[code_col]
        if code not in GEO_NAME:
            continue
        for y in years:
            j = hdr.index(str(y))
            out[(code, y)] = num(r[j]) if j < len(r) else None
    return out, hdr


def build_affordability():
    api = []
    aff_url = (f"{ONS}/file?uri=/peoplepopulationandcommunity/housing/datasets/"
               "ratioofhousepricetoresidencebasedearningslowerquartileandmedian/current/"
               "aff2ratioofhousepricetoresidencebasedearnings.xlsx")
    aff = get(aff_url, "ons_aff2_ratio.xlsx")
    api.append(aff_url)
    hdr = next(r for r in xlsx_sheet(aff, "5c") if r and r[0] == "Country/Region code")
    all_years = [int(h) for h in hdr if str(h).isdigit()]
    years = all_years[-6:]
    latest_year = years[-1]
    rows = []
    for ind_id, la_sheet, nat_sheet in (("aff_hp_earn_ratio", "5c", "1c"),
                                        ("aff_lq_hp_earn_ratio", "6c", "2c")):
        la, _ = ratio_table(aff, la_sheet, 2, 4, years)
        nat, _ = ratio_table(aff, nat_sheet, 0, 2, years)
        for (code, y), v in sorted({**la, **nat}.items()):
            rows.append(mkrow(code, ind_id, v, str(y)))

    # PIPR monthly rents
    pipr_url = ons_latest_xlsx(PIPR_PAGE, "ons_pipr_page.html")
    api.append(pipr_url)
    tag = re.search(r"/(\d{1,2}[a-z]+\d{4})/", pipr_url)
    pipr = get(pipr_url, f"ons_pipr_{tag.group(1) if tag else 'latest'}.xlsx")
    t1 = xlsx_sheet(pipr, "Table 1")
    hdr = next(r for r in t1 if r and r[0] == "Time period")
    cols = {"": hdr.index("Rental price"), "1 bedroom": hdr.index("Rental price one bed"),
            "2 bedrooms": hdr.index("Rental price two bed"),
            "3 bedrooms": hdr.index("Rental price three bed"),
            "4 or more bedrooms": hdr.index("Rental price four or more bed")}
    sel = [r for r in t1[t1.index(hdr) + 1:] if len(r) > 2 and r[1] in GEO_NAME]
    months = sorted({int(float(r[0])) for r in sel})[-25:]
    latest_month = excel_month(months[-1])[0]
    rent = {}
    for r in sel:
        if int(float(r[0])) not in months:
            continue
        per = excel_month(r[0])[0]
        for bd, j in cols.items():
            v = num(r[j]) if j < len(r) else None
            rent[(r[1], per, bd)] = v
            rows.append(mkrow(r[1], "aff_rent_monthly", v, per, breakdown=bd or None, nd=0,
                              series=bd or "all"))
            share = None if v is None else 12 * v / NLW_ANNUAL * 100
            rows.append(mkrow(r[1], "aff_rent_share_nlw", share, per, breakdown=bd or None, nd=1,
                              nm=None if v is None else 12 * v, den=NLW_ANNUAL,
                              series=bd or "all"))

    cohort = "context, 18-24"
    inds = [
        ind("aff_hp_earn_ratio", "House price to residence-based earnings ratio (median)", "ratio",
            cohort, "higher_is_worse",
            "ONS: median house price (year ending September) divided by median gross annual "
            "earnings of full-time employees living in the area (ASHE, April). Table 5c (LA) and "
            "1c (region, England)."),
        ind("aff_lq_hp_earn_ratio",
            "House price to residence-based earnings ratio (lower quartile)", "ratio", cohort,
            "higher_is_worse",
            "ONS: lower-quartile house price divided by lower-quartile gross annual residence-based "
            "full-time earnings - the entry-level affordability measure. Tables 6c (LA) and 2c."),
        ind("aff_rent_monthly", "Average monthly private rent (PIPR)", "gbp", cohort,
            "higher_is_worse",
            "ONS Price Index of Private Rents: average monthly private rental price (stock of "
            "existing tenancies and new lets, rounded to the nearest pound). No breakdown = all "
            "property sizes; breakdown = number of bedrooms."),
        ind("aff_rent_share_nlw", "Rent as % of full-time National Living Wage pay", "percent",
            cohort, "higher_is_worse",
            f"Derived: 12 x average monthly private rent / annual gross pay of a full-time NLW "
            f"worker x 100, where annual NLW pay = GBP {NLW_HOURLY}/hour x {NLW_HOURS} hours x 52 "
            f"weeks = GBP {NLW_ANNUAL:,.2f} (NLW rate from 1 April 2026, age 21+). Gross pay "
            "before tax/NI; ignores Universal Credit housing support. num = annual rent, den = "
            "annual NLW pay. Breakdown = bedrooms (1 bedroom is the relevant comparator for a "
            "single new entrant)."),
    ]
    meta = {
        "title": "Housing affordability: house price to earnings ratios and private rents",
        "publisher": "Office for National Statistics",
        "source_url": f"{AFF_PAGE} ; {PIPR_PAGE}",
        "api_url": api,
        "geography": "LA, region, England",
        "cohort": cohort,
        "period": f"ratios {latest_year}; rents {latest_month}",
        "latest_period": latest_month,
        "frequency": "Annual (ratios), Monthly (rents)",
        "next_update": "Ratios: March 2027 (annual); rents: monthly with ONS consumer price inflation",
        "access": "Excel download",
        "quality": "Affordability ratios are official statistics combining HM Land Registry price "
                   "paid data with ASHE residence-based earnings (survey; LA earnings carry "
                   "sampling error so year-to-year moves of a few tenths are noise). PIPR is an "
                   "official statistic in development built from VOA, Valuation Office and "
                   "devolved administration rental data covering existing tenancies, not only "
                   "new lets.",
        "limitations": "Ratios use full-time workplace-independent residence earnings and median "
                       "or lower-quartile prices, not what an 18-24 year old earns. PIPR prices are "
                       "averages of the rental stock, so advertised new-let rents faced by a "
                       "newcomer are typically higher; the latest months are provisional and "
                       "revised. The NLW rent share is gross pay, single earner, before tax and "
                       "benefits, and uses the 21+ NLW rate (18-20 rate is lower). No Bedfordshire "
                       "total: averages and ratios cannot be summed.",
        "indicators": inds,
        "nlw_annual_gbp": NLW_ANNUAL,
    }
    return meta, rows


# --------------------------------------------------------------------------------------------
# 2. Childcare
# --------------------------------------------------------------------------------------------
def govuk_attachments(path):
    doc = json.loads(fetch(GOVUK_API + path))
    return doc, doc["details"].get("attachments", [])


def latest_attachment(atts, pattern):
    """Latest attachment whose title matches pattern, by the 'as at <date>' date in the title."""
    best = None
    for a in atts:
        t = a.get("title", "")
        if not re.search(pattern, t, re.I):
            continue
        m = re.findall(r"(\d{1,2} [A-Z][a-z]+ \d{4})", t)
        if not m:
            continue
        d = dt.datetime.strptime(m[-1], "%d %B %Y").date()
        if best is None or d > best[0]:
            best = (d, a)
    if not best:
        raise RuntimeError(f"no attachment matching {pattern}")
    return best


def load_pop_0_4():
    """ONS mid-year estimates, persons aged 0-4 (c_age 101-105), latest year, via Nomis."""
    q = urllib.parse.urlencode({
        "geography": ",".join(GEO_NAME), "date": "latest", "gender": "0",
        "c_age": "101,102,103,104,105", "measures": "20100",
        "select": "date_name,geography_code,c_age,obs_value"}, safe=",")
    url = f"{NOMIS}NM_2002_1.data.csv?{q}"
    text = get(url, "ctx_nomis_mye_0_4.csv").decode("utf-8-sig")
    pop, year = {}, None
    for x in csv.DictReader(io.StringIO(text)):
        pop[x["GEOGRAPHY_CODE"]] = pop.get(x["GEOGRAPHY_CODE"], 0) + int(float(x["OBS_VALUE"]))
        year = x["DATE_NAME"]
    return pop, year, url


def build_childcare():
    doc, atts = govuk_attachments(CC_PATH)
    as_at, att = latest_attachment(atts, r"childcare provider(s)? data as at")
    url = att["url"]
    text = get(url, f"ofsted_cc_providers_{as_at:%Y%m%d}.csv").decode("utf-8-sig",
                                                                      errors="replace")
    lines = list(csv.reader(io.StringIO(text)))
    hi = next(i for i, r in enumerate(lines) if r and r[0] == "Web link" and "Provider URN" in r)
    hdr = lines[hi]
    recs = [dict(zip(hdr, r)) for r in lines[hi + 1:] if len(r) > 2 and r[1]]
    eyr = [x for x in recs if x["Provider Early Years Register flag"] == "Y"
           and x["Provider status"] == "Active"]
    period = f"{as_at:%d %b %Y}"

    def geo_of(x):
        out = []
        if x["Local authority"] in LA_BY_NAME:
            out += [LA_BY_NAME[x["Local authority"]], "BEDS"]
        if x["Region"] == "East of England":
            out.append("E12000006")
        out.append("E92000001")  # the register file covers England only (incl. 'Not Recorded' region)
        return out

    def ptype(x):
        t = x["Provider type"]
        return "Childminders" if t.startswith("Childminder") else (
            "Nurseries and other non-domestic settings" if t == "Childcare on non-domestic premises"
            else "Childcare on domestic premises")

    prov, places = {}, {}
    for x in eyr:
        p = num(x["Places including estimates"]) or 0.0
        for g in geo_of(x):
            for bd in (None, ptype(x)):
                prov[(g, bd)] = prov.get((g, bd), 0) + 1
                places[(g, bd)] = places.get((g, bd), 0.0) + p
    pop, pop_year, pop_url = load_pop_0_4()
    pop["BEDS"] = sum(pop[c] for c in LAS)
    rows = []
    for (g, bd), n in sorted(prov.items(), key=lambda k: (k[0][0], k[0][1] or "")):
        rows.append(mkrow(g, "cc_providers", n, period, breakdown=bd, nd=0))
        rows.append(mkrow(g, "cc_places", round(places[(g, bd)]), period, breakdown=bd, nd=0))
        if bd is None:
            rows.append(mkrow(g, "cc_places_per_100_0_4", 100 * places[(g, bd)] / pop[g], period,
                              nm=round(places[(g, bd)]), den=pop[g], nd=1))
            rows.append(mkrow(g, "cc_pop_0_4", pop[g], f"mid-{pop_year}", nd=0))
    cohort = "25+ inactive"
    inds = [
        ind("cc_providers", "Registered early years childcare providers", "count", cohort,
            "higher_is_better",
            "Active providers on Ofsted's Early Years Register (childminders, nurseries/pre-"
            "schools/out-of-school clubs on non-domestic premises, childcare on domestic premises) "
            "by provider local authority. Breakdown = provider type."),
        ind("cc_places", "Registered early years childcare places", "count", cohort,
            "higher_is_better",
            "Sum of 'Places including estimates' for active Early Years Register providers "
            "(Ofsted uses averages for the few providers with no place number; reproduces "
            "Ofsted MI Table 2a 'EYR places at end', rounded to whole places)."),
        ind("cc_places_per_100_0_4", "Early years childcare places per 100 children aged 0-4",
            "rate", cohort, "higher_is_better",
            "cc_places / ONS mid-year population aged 0-4 x 100 (num = places, den = population "
            "0-4, Nomis NM_2002_1). A capacity proxy for parents (mostly mothers) returning to "
            "work; places are not full-time-equivalent and many serve 0-7s."),
        ind("cc_pop_0_4", "Population aged 0-4 (denominator)", "count", cohort, "neutral",
            "ONS mid-year population estimate, persons aged 0-4 (sum of single years 0-4)."),
    ]
    meta = {
        "title": "Childcare supply: Ofsted-registered early years providers and places",
        "publisher": "Ofsted (childcare MI); ONS mid-year estimates via Nomis",
        "source_url": "https://www.gov.uk" + CC_PATH,
        "api_url": [url, pop_url],
        "geography": "LA, region, England, Bedfordshire total",
        "cohort": cohort,
        "period": period,
        "latest_period": period,
        "frequency": "Quarterly",
        "next_update": "Quarterly (next quarter-end extract, typically published ~6 weeks later)",
        "access": "CSV download",
        "quality": "Ofsted management information (not official statistics; not reconciled "
                   "with the official statistics series) extracted from the live register. "
                   f"Provider-level file of {len(recs):,} active registered providers in England; "
                   "LA, region and England totals are summed from the complete file and match "
                   "Ofsted's published Table 2a.",
        "limitations": "Counts registered places, not vacancies, opening hours or prices; a place "
                       "can be used by more than one child. Excludes provision not on the Ofsted "
                       "register: maintained nursery schools and nursery classes in schools "
                       "(a large share of 3-4 year old funded hours), so places per 100 understates "
                       "total early education capacity. Home childcarers (nannies) and Childcare "
                       "Register-only providers have no places and are excluded. Childminder "
                       "addresses are redacted, so no point data. Denominator is mid-"
                       f"{pop_year} 0-4 population against a {period} register.",
        "indicators": inds,
    }
    return meta, rows


# --------------------------------------------------------------------------------------------
# 3. Ofsted FE and skills
# --------------------------------------------------------------------------------------------
GRADE = {"1": "Outstanding", "2": "Good", "3": "Requires improvement", "4": "Inadequate"}
RC_BELOW = {"Needs attention", "Urgent improvement"}


def load_points():
    p = OUT / "providers.json"
    pts = {}
    if p.exists():
        for r in json.loads(p.read_text())["rows"]:
            a = r.get("attrs") or {}
            if r.get("lat") is None:
                continue
            for k in ("urn", "ukprn"):
                if a.get(k):
                    pts[(k, str(a[k]))] = (r["lat"], r["lon"], r["name"])
    return pts


def build_ofsted_fe():
    doc, atts = govuk_attachments(FE_SERIES)
    as_at, a_state = latest_attachment(
        [a for a in atts if a.get("url", "").endswith(".csv")],
        r"further education and skills - as at")
    _, a_insp = latest_attachment(
        [a for a in atts if a.get("url", "").endswith(".csv")],
        r"further education and skills - 10 November 2025 to")
    state_text = get(a_state["url"], f"ofsted_fe_state_{as_at:%Y%m%d}.csv").decode("utf-8-sig")
    insp_text = get(a_insp["url"], f"ofsted_fe_reif_{as_at:%Y%m%d}.csv").decode("utf-8-sig")
    state = list(csv.DictReader(io.StringIO(state_text)))
    insp = {}
    for x in csv.DictReader(io.StringIO(insp_text)):
        if not x.get("Provider URN"):
            continue
        prev = insp.get(x["Provider URN"])
        d = dt.datetime.strptime(x["First day of inspection"], "%d/%m/%Y").date()
        if prev is None or d > prev[0]:
            insp[x["Provider URN"]] = (d, x)
    rc_cols = [c for c in (next(iter(insp.values()))[1].keys() if insp else [])
               if c and c not in ("Provider URN", "Provider UKPRN", "Provider name",
                                  "Provider type", "Provider group", "Local authority", "Region",
                                  "Ofsted region", "Inspection number", "First day of inspection",
                                  "Date published")]
    pts = load_points()
    period = f"{as_at:%d %b %Y}"
    oe_col = "Latest overall effectiveness before renewed EIF"
    rows, counts = [], {}
    for x in state:
        region = x["Region"]
        if region not in ENGLISH_REGIONS:
            continue
        g = x[oe_col].strip()
        urn = x["Provider URN"]
        rc = insp.get(urn)
        rc_grades = {c: rc[1][c] for c in rc_cols if rc[1].get(c)} if rc else None
        below = sum(1 for v in rc_grades.values() if v in RC_BELOW) if rc_grades else None
        geos = ["E92000001"] + (["E12000006"] if region == "East of England" else [])
        la_code = LA_BY_NAME.get(x["Local authority"])
        if la_code:
            geos += [la_code, "BEDS"]
        label = GRADE.get(g, "No graded inspection before renewed EIF")
        for geo in geos:
            for key in ("all", label, "rc" if rc else None):
                if key:
                    counts[(geo, key)] = counts.get((geo, key), 0) + 1
        if not la_code:
            continue
        attrs = {
            "urn": urn, "ukprn": x["Provider UKPRN"], "provider_type": x["Provider type"],
            "provider_group": x["Provider group"], "la": x["Local authority"],
            "la_code": la_code,
            "legacy_overall_effectiveness": GRADE.get(g),
            "legacy_inspection_date": x["First day of inspection of latest inspection before renewed EIF"],
            "legacy_quality_of_education": x["Latest quality of education before renewed EIF"],
            "legacy_leadership_management": x["Latest leadership and management before renewed EIF"],
            "legacy_skills_needs": x["Latest contribution to meeting skills needs before renewed EIF"],
            "renewed_eif_full_inspection": x["Has the provider received a full inspection under the renewed EIF?"],
            "new_provider_monitoring": x["Has the provider received a new provider monitoring inspection?"],
            "report_card_date": rc[0].isoformat() if rc else None,
            "report_card": rc_grades,
            "report_card_areas_below_expected": below,
        }
        pt = pts.get(("urn", urn)) or pts.get(("ukprn", x["Provider UKPRN"]))
        base = {"code": urn, "name": x["Provider name"], "ci": None, "num": None, "den": None,
                "breakdown": x["Provider type"], "attrs": attrs}
        if pt:
            base.update({"level": "point", "lat": pt[0], "lon": pt[1]})
        else:
            base.update({"level": "provider"})
        oe = num(g)
        ld = attrs["legacy_inspection_date"]
        ld = (dt.datetime.strptime(ld, "%d/%m/%Y").strftime("%d %b %Y")
              if re.match(r"\d\d/\d\d/\d{4}$", ld or "") else None)
        r = dict(base, indicator="ofsted_fe_overall", value=oe, period=ld if oe and ld else period)
        if oe is None:
            r["suppressed"] = True
        rows.append(r)
        if rc:
            rows.append(dict(base, indicator="ofsted_fe_rc_below_expected", value=below,
                             period=rc[0].strftime("%d %b %Y")))

    geos = list(LAS) + ["BEDS", "E12000006", "E92000001"]
    for geo in geos:
        total = counts.get((geo, "all"), 0)
        rows.append(mkrow(geo, "ofsted_fe_providers", total, period, nd=0))
        for label in list(GRADE.values()) + ["No graded inspection before renewed EIF"]:
            rows.append(mkrow(geo, "ofsted_fe_grade_count", counts.get((geo, label), 0), period,
                              breakdown=label, nd=0))
        graded = sum(counts.get((geo, lab), 0) for lab in GRADE.values())
        gp = counts.get((geo, "Outstanding"), 0) + counts.get((geo, "Good"), 0)
        rows.append(mkrow(geo, "ofsted_fe_pct_good_plus", 100 * gp / graded if graded else None,
                          period, nm=gp, den=graded, nd=1))
        rows.append(mkrow(geo, "ofsted_fe_rc_count", counts.get((geo, "rc"), 0), period, nd=0))

    cohort = "16-19, 18-24"
    inds = [
        ind("ofsted_fe_overall", "Ofsted overall effectiveness (latest before renewed EIF)",
            "score", cohort, "higher_is_worse",
            "Field 'Latest overall effectiveness before renewed EIF' (1 Outstanding, 2 Good, "
            "3 Requires improvement, 4 Inadequate) for each FE and skills provider whose Ofsted "
            "record places it in Bedford, Central Bedfordshire or Luton. Null = no graded "
            "inspection under the old framework (new providers). Report-card grades from "
            "inspections under the renewed EIF (from 10 Nov 2025; no single overall grade) are in "
            "attrs.report_card; the legacy grade may predate them."),
        ind("ofsted_fe_rc_below_expected",
            "Report-card evaluation areas below expected standard (renewed EIF)", "count", cohort,
            "higher_is_worse",
            "For providers inspected under the renewed EIF report-card format: number of graded "
            "evaluation areas judged 'Needs attention' or 'Urgent improvement' (scale: Exceptional, "
            "Strong standard, Expected standard, Needs attention, Urgent improvement). Full text "
            "grades in attrs.report_card."),
        ind("ofsted_fe_providers", "FE and skills providers in Ofsted's inspection remit", "count",
            cohort, "neutral",
            "Number of FE and skills providers (colleges, independent learning providers, employer "
            "providers, local authority providers, HEIs with apprenticeships, 16-19 academies, "
            "dance and drama colleges) recorded against the area in the Ofsted MI."),
        ind("ofsted_fe_grade_count", "FE and skills providers by latest legacy overall grade",
            "count", cohort, "neutral",
            "Count of providers by 'Latest overall effectiveness before renewed EIF'; breakdown = "
            "grade."),
        ind("ofsted_fe_pct_good_plus", "% of graded FE and skills providers good or outstanding",
            "percent", cohort, "higher_is_better",
            "Providers graded 1 or 2 / providers with a legacy overall grade x 100 (num/den given; "
            "Bedfordshire total recomputed from summed counts)."),
        ind("ofsted_fe_rc_count", "FE and skills providers with a renewed-EIF report card",
            "count", cohort, "neutral",
            "Providers with a full inspection under the renewed EIF (report card) published "
            "since 10 November 2025."),
    ]
    meta = {
        "title": "Ofsted further education and skills inspections (providers in Bedfordshire)",
        "publisher": "Ofsted",
        "source_url": "https://www.gov.uk" + FE_SERIES,
        "api_url": [a_state["url"], a_insp["url"]],
        "geography": "point / provider (Bedfordshire FE and skills providers); LA, region, "
                     "England, Bedfordshire total counts",
        "cohort": cohort,
        "period": period,
        "latest_period": period,
        "frequency": "Monthly",
        "next_update": "Monthly (new academic-year series from September 2026)",
        "access": "CSV download",
        "quality": "Ofsted management information, not official statistics; provider-level "
                   "extract of all FE and skills providers in remit with their latest inspection "
                   "outcomes. Point locations borrowed from GIAS (providers dataset) where URN or "
                   "UKPRN match; other providers are 'provider' rows without coordinates.",
        "limitations": "Location is Ofsted's recorded local authority for the provider (usually "
                       "head office), not where learners are taught: national apprenticeship "
                       "providers delivering in Bedfordshire but based elsewhere are not "
                       "captured, and a Bedfordshire-based provider may teach mostly elsewhere. "
                       "Since 10 Nov 2025 Ofsted grades providers on a report card with no "
                       "single overall judgement, so the 1-4 grade shown is the latest under the "
                       "previous framework and may be several years old; report-card outcomes "
                       "are in attrs and in ofsted_fe_rc_* indicators. Providers in Wales and "
                       "Scotland in the file are excluded from England counts.",
        "indicators": inds,
    }
    return meta, rows


def main():
    summary = {}
    for ds_id, fn in (("affordability", build_affordability), ("childcare", build_childcare),
                      ("ofsted_fe", build_ofsted_fe)):
        meta, rows = fn()
        save(ds_id, meta, rows)
        summary[ds_id] = (len(rows), meta["latest_period"])
    print("\nSummary:")
    for k, (n, p) in summary.items():
        print(f"  {k:14s} {n:6d} rows  latest {p}")


if __name__ == "__main__":
    main()
