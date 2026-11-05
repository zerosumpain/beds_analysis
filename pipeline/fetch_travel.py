"""Travel time from every Bedfordshire LSOA (2021) to the proposed Universal resort site.

Batch OpenTripPlanner 2 run in Docker (one-off, not a service):

1. Download (cached in data/raw/travel/): Geofabrik Bedfordshire OSM extract, DfT Bus Open
   Data Service (BODS) regional GTFS (south_east, east_anglia, east_midlands), ONS LSOA 2021
   population-weighted centroids (ArcGIS geoportal).
2. Cut each BODS feed down to trips that run on the modelled day (or just after midnight) and
   call at least one stop near Bedfordshire; shapes are dropped.
3. Zip the hand-made rail GTFS in pipeline/travel/rail_gtfs/ (see make_rail_gtfs.py there).
4. `docker run --rm` OTP --build --save, then --load --serve on 127.0.0.1, query every LSOA
   centroid (GTFS GraphQL `plan`), stop the container.
5. Write site/data/travel_lsoa.json (LSOA rows + LA/county population-weighted shares).

Re-runnable: downloads, filtered feeds, the graph and every OTP answer are cached under
data/raw/travel/ and invalidated by a stamp over the inputs. `--refresh` re-downloads
the OSM/BODS inputs. Stdlib only; needs Docker.
"""
import concurrent.futures as cf
import csv
import datetime as dt
import hashlib
import io
import json
import math
import statistics
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile

from common import LAS, OUT, RAW, ROOT, UA, save

TRAVEL = RAW / "travel"
OTPDIR = TRAVEL / "otp"
RAIL_SRC = ROOT / "pipeline" / "travel" / "rail_gtfs"

OTP_IMAGE = "opentripplanner/opentripplanner:2.8.1"
OTP_PORT = 18089  # loopback only; the batch talks to it, nobody else does
CONTAINER = "beds-travel-otp"

# Proposed Universal resort site, Kempston Hardwick (brickworks site south of the A421).
# common.SITE (52.0870,-0.5160) is a map label point; routing uses the brief's coordinate.
DEST = {"lat": 52.0898, "lon": -0.4996}

# A typical weekday inside every feed's validity window (BODS feeds downloaded 5 Nov 2026
# start 5 Nov 2026; LNR Marston Vale timetable valid to 11 Dec 2026). Not a holiday.
TT_DATE = dt.date(2026, 11, 17)  # Tuesday
NEXT_DATE = TT_DATE + dt.timedelta(days=1)

OSM_URL = "https://download.geofabrik.de/europe/united-kingdom/england/bedfordshire-latest.osm.pbf"
BODS_URL = "https://data.bus-data.dft.gov.uk/timetable/download/gtfs-file/{}/"
BODS_REGIONS = ["south_east", "east_anglia", "east_midlands"]
PWC_URL = ("https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services/"
           "LSOA_PopCentroids_EW_2021_V4/FeatureServer/0/query")
LNR_MV_URL = "https://www.londonnorthwesternrailway.co.uk/media/44855/download"

# Keep bus trips that call anywhere in this box (Bedfordshire + ~5 km margin).
BBOX = (51.80, -0.80, 52.36, -0.10)  # lat_min, lon_min, lat_max, lon_max

AM_ARRIVE = "08:30"
AM_WINDOW_MIN = 60   # arrivals 07:30-08:30
LATE_DEPART = "22:30"
LATE_MAX_MIN = 120   # latest acceptable arrival 00:30
LATE_OK_MIN = 90     # "journey home exists within 90 min" -> home by 00:00
WALK_ONLY_CAP_MIN = 60  # a walk-only answer counts as the PT time only up to an hour


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- downloads
def download(url, dest, refresh=False):
    if dest.exists() and not refresh:
        return dest
    log(f"download {url}")
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req, timeout=600) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.rename(dest)
    return dest


def sha_file(p, n=16):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()[:n]


# ---------------------------------------------------------------- centroids
def polygon_centroid(geom):
    """Area-weighted centroid of a (Multi)Polygon's outer rings (lon/lat planar approx)."""
    polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
    A = cx = cy = 0.0
    for poly in polys:
        ring = poly[0]
        for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
            c = x1 * y2 - x2 * y1
            A += c
            cx += (x1 + x2) * c
            cy += (y1 + y2) * c
    A /= 2
    return cy / (6 * A), cx / (6 * A)


def load_centroids(codes):
    """ONS LSOA21 population-weighted centroids; geometric centroid fallback per LSOA."""
    cache = TRAVEL / "lsoa21_pwc.json"
    pwc = {}
    if not cache.exists():
        where = "LSOA21CD IN (" + ",".join(f"'{c}'" for c in sorted(codes)) + ")"
        body = urllib.parse.urlencode({"where": where, "outFields": "LSOA21CD", "outSR": 4326,
                                       "f": "json", "resultRecordCount": 2000}).encode()
        req = urllib.request.Request(PWC_URL, data=body, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                doc = json.loads(r.read())
            cache.write_text(json.dumps(doc))
        except Exception as e:  # noqa: BLE001
            log(f"PWC fetch failed ({e}); using geometric centroids")
    if cache.exists():
        for f in json.loads(cache.read_text()).get("features", []):
            g = f["geometry"]
            pwc[f["attributes"]["LSOA21CD"]] = (round(g["y"], 6), round(g["x"], 6))
    geo = json.loads((OUT / "geo" / "lsoa.geojson").read_text())
    out = {}
    for feat in geo["features"]:
        c = feat["properties"]["code"]
        if c not in codes:
            continue
        if c in pwc:
            out[c] = (*pwc[c], "pwc")
        else:
            lat, lon = polygon_centroid(feat["geometry"])
            out[c] = (round(lat, 6), round(lon, 6), "geometric")
    return out


# ---------------------------------------------------------------- GTFS filtering
def active_services(z, dates):
    names = set(z.namelist())
    act = set()
    if "calendar.txt" in names:
        for r in csv.DictReader(io.TextIOWrapper(z.open("calendar.txt"), "utf-8-sig")):
            for d in dates:
                ds = d.strftime("%Y%m%d")
                day = d.strftime("%A").lower()
                if r["start_date"] <= ds <= r["end_date"] and r.get(day) == "1":
                    act.add((r["service_id"], ds))
    if "calendar_dates.txt" in names:
        dss = {d.strftime("%Y%m%d") for d in dates}
        for r in csv.DictReader(io.TextIOWrapper(z.open("calendar_dates.txt"), "utf-8-sig")):
            if r["date"] in dss:
                key = (r["service_id"], r["date"])
                if r["exception_type"] == "1":
                    act.add(key)
                elif r["exception_type"] == "2":
                    act.discard(key)
    return {s for s, _ in act}


def filter_gtfs(src, dest):
    """Write a small GTFS: trips active on TT_DATE/NEXT_DATE touching BBOX. No shapes."""
    z = zipfile.ZipFile(src)

    def rows(name):
        return csv.DictReader(io.TextIOWrapper(z.open(name), "utf-8-sig"))

    services = active_services(z, [TT_DATE, NEXT_DATE])
    stops = {r["stop_id"]: r for r in rows("stops.txt")}
    inbox = {s for s, r in stops.items() if r["stop_lat"] and BBOX[0] <= float(r["stop_lat"]) <= BBOX[2]
             and BBOX[1] <= float(r["stop_lon"]) <= BBOX[3]}
    trips = {r["trip_id"]: r for r in rows("trips.txt") if r["service_id"] in services}
    keep = set()
    for r in rows("stop_times.txt"):  # pass 1: which trips call in the box
        if r["stop_id"] in inbox and r["trip_id"] in trips:
            keep.add(r["trip_id"])
    used_stops, st_rows = set(), []
    st_fields = None
    rd = rows("stop_times.txt")
    for r in rd:  # pass 2: their full stop sequences
        if r["trip_id"] in keep:
            st_fields = st_fields or rd.fieldnames
            used_stops.add(r["stop_id"])
            st_rows.append(r)
    kt = [trips[t] for t in keep]
    used_routes = {t["route_id"] for t in kt}
    used_services = {t["service_id"] for t in kt}
    for t in kt:
        t["shape_id"] = ""
    parents = {stops[s].get("parent_station") for s in used_stops if s in stops} - {"", None}
    routes = [r for r in rows("routes.txt") if r["route_id"] in used_routes]
    agencies = {r.get("agency_id") for r in routes}
    tmp = dest.with_suffix(".part")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
        def put(name, fieldnames, data):
            buf = io.StringIO()
            w = csv.DictWriter(buf, fieldnames=fieldnames, lineterminator="\n", extrasaction="ignore")
            w.writeheader()
            w.writerows(data)
            out.writestr(name, buf.getvalue())

        ag = list(rows("agency.txt"))
        put("agency.txt", list(ag[0].keys()), [a for a in ag if a.get("agency_id") in agencies or not a.get("agency_id")])
        srow = [stops[s] for s in sorted(used_stops | parents) if s in stops]
        put("stops.txt", list(srow[0].keys()), srow)
        put("routes.txt", list(routes[0].keys()), routes)
        put("trips.txt", list(kt[0].keys()), kt)
        put("stop_times.txt", st_fields, st_rows)
        names = set(z.namelist())
        if "calendar.txt" in names:
            cal = [r for r in rows("calendar.txt") if r["service_id"] in used_services]
            if cal:
                put("calendar.txt", list(cal[0].keys()), cal)
        if "calendar_dates.txt" in names:
            cd = [r for r in rows("calendar_dates.txt") if r["service_id"] in used_services]
            if cd:
                put("calendar_dates.txt", list(cd[0].keys()), cd)
        if "feed_info.txt" in names:
            out.writestr("feed_info.txt", z.read("feed_info.txt"))
    tmp.rename(dest)
    log(f"  {src.name}: {len(keep)} trips, {len(used_stops)} stops, {len(routes)} routes kept")
    return {"trips": len(keep), "stops": len(used_stops), "routes": len(routes)}


def zip_rail(dest):
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(RAIL_SRC.glob("*.txt")):
            z.write(p, p.name)


def feed_validity(src):
    z = zipfile.ZipFile(src)
    try:
        info = next(csv.DictReader(io.TextIOWrapper(z.open("feed_info.txt"), "utf-8-sig")))
        return info.get("feed_start_date"), info.get("feed_end_date")
    except Exception:  # noqa: BLE001
        return None, None


# ---------------------------------------------------------------- OTP
def docker(*args, check=True, **kw):
    return subprocess.run(["docker", *args], check=check, **kw)


def otp_run_args(extra, detach=False, name=None, port=None, heap="8g"):
    a = ["run", "--rm", "--user", f"{_uid()}", "-e", f"JAVA_OPTS=-Xmx{heap}",
         "-v", f"{OTPDIR}:/var/opentripplanner"]
    if detach:
        a.append("-d")
    if name:
        a += ["--name", name]
    if port:
        a += ["-p", f"127.0.0.1:{port}:8080"]
    return a + [OTP_IMAGE, *extra]


def _uid():
    import os
    return f"{os.getuid()}:{os.getgid()}"


def write_otp_config(feeds):
    build = {
        "transitServiceStart": (TT_DATE - dt.timedelta(days=3)).isoformat(),
        "transitServiceEnd": (TT_DATE + dt.timedelta(days=4)).isoformat(),
        "osmDefaults": {"osmTagMapping": "uk"},
        "osm": [{"source": "bedfordshire.osm.pbf"}],
        "transitFeeds": [{"type": "gtfs", "feedId": fid, "source": fn} for fid, fn in feeds],
        "dataImportReport": False,
    }
    router = {
        "routingDefaults": {
            "walk": {"speed": 1.33},  # m/s (~4.8 km/h), OTP default
            "bike": {"speed": 5.0},   # m/s (18 km/h), OTP default
            "transferSlack": "2m",
            "numItineraries": 12,
            "accessEgress": {"maxDuration": "45m"},
        },
        "server": {"apiProcessingTimeout": "30s"},
    }
    (OTPDIR / "build-config.json").write_text(json.dumps(build, indent=1))
    (OTPDIR / "router-config.json").write_text(json.dumps(router, indent=1))
    (OTPDIR / "otp-config.json").write_text(json.dumps({}))


def gql(query):
    req = urllib.request.Request(f"http://127.0.0.1:{OTP_PORT}/otp/gtfs/v1",
                                 data=json.dumps({"query": query}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


def wait_ready(timeout=900):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            gql("{ feeds { feedId } }")
            return
        except Exception:  # noqa: BLE001
            time.sleep(5)
    raise RuntimeError("OTP did not come up")


ITIN = ("itineraries { startTime endTime duration walkTime waitingTime numberOfTransfers "
        "legs { mode startTime endTime from { name } to { name } route { shortName agency { name } } } }")


def plan_query(lat, lon, kind):
    o = f"from: {{lat: {lat}, lon: {lon}}}"
    d = f"to: {{lat: {DEST['lat']}, lon: {DEST['lon']}}}"
    day = TT_DATE.isoformat()
    if kind == "pt_am":
        args = (f'{o}, {d}, date: "{day}", time: "{AM_ARRIVE}", arriveBy: true, '
                f"searchWindow: {AM_WINDOW_MIN * 60}, numItineraries: 20, "
                "transportModes: [{mode: WALK}, {mode: TRANSIT}]")
    elif kind == "pt_late":  # home FROM the site
        o2 = f"from: {{lat: {DEST['lat']}, lon: {DEST['lon']}}}"
        d2 = f"to: {{lat: {lat}, lon: {lon}}}"
        args = (f'{o2}, {d2}, date: "{day}", time: "{LATE_DEPART}", arriveBy: false, '
                f"searchWindow: {LATE_MAX_MIN * 60}, numItineraries: 20, "
                "transportModes: [{mode: WALK}, {mode: TRANSIT}]")
    else:
        mode = {"car": "CAR", "bike": "BICYCLE", "walk": "WALK"}[kind]
        args = f'{o}, {d}, date: "{day}", time: "08:00", transportModes: [{{mode: {mode}}}]'
    return f"{{ plan({args}) {{ {ITIN} routingErrors {{ code }} }} }}"


def run_queries(centroids, stamp):
    cache_p = TRAVEL / "otp_results.json"
    cache = json.loads(cache_p.read_text()) if cache_p.exists() else {}
    todo = []
    for code, (lat, lon, _) in centroids.items():
        for kind in ("pt_am", "pt_late", "car", "bike", "walk"):
            key = f"{stamp}|{kind}|{code}|{lat},{lon}"
            if key not in cache:
                todo.append((key, lat, lon, kind))
    if not todo:
        return cache, 0
    log(f"OTP: {len(todo)} queries to run")
    if not (OTPDIR / "graph.obj").exists():
        raise RuntimeError("graph.obj missing")
    docker("rm", "-f", CONTAINER, check=False, capture_output=True)
    docker(*otp_run_args(["--load", "--serve"], detach=True, name=CONTAINER, port=OTP_PORT,
                         heap="6g"), capture_output=True)
    try:
        wait_ready()

        def one(item):
            key, lat, lon, kind = item
            for attempt in range(3):
                try:
                    res = gql(plan_query(lat, lon, kind))
                    if "errors" in res:
                        raise RuntimeError(res["errors"])
                    time.sleep(0.02)  # gentle throttle
                    return key, res["data"]["plan"]
                except Exception as e:  # noqa: BLE001
                    err = e
                    time.sleep(2 * (attempt + 1))
            raise RuntimeError(f"query failed {key}: {err}")

        done = 0
        with cf.ThreadPoolExecutor(max_workers=4) as ex:
            for key, plan in ex.map(one, todo):
                cache[key] = plan
                done += 1
                if done % 200 == 0:
                    log(f"  {done}/{len(todo)}")
                    cache_p.write_text(json.dumps(cache))
    finally:
        docker("stop", CONTAINER, check=False, capture_output=True)
    cache_p.write_text(json.dumps(cache))
    return cache, len(todo)


# ---------------------------------------------------------------- summarise answers
def epoch_ms(day, hhmm):
    h, m = map(int, hhmm.split(":"))
    t = dt.datetime(day.year, day.month, day.day, h, m, tzinfo=dt.timezone.utc)
    # Europe/London is GMT (UTC+0) in November; assert to avoid silent BST errors.
    assert not (3 < day.month < 11), "TT_DATE must be in GMT for this epoch shortcut"
    return int(t.timestamp() * 1000)


def hhmm(ms):
    return dt.datetime.fromtimestamp(ms / 1000, dt.timezone.utc).strftime("%H:%M")


def describe(it):
    legs = [lg for lg in it["legs"] if lg["mode"] != "WALK"]
    return {
        "depart": hhmm(it["startTime"]), "arrive": hhmm(it["endTime"]),
        "transfers": it.get("numberOfTransfers"),
        "walk_min": round(it["walkTime"] / 60), "wait_min": round(it["waitingTime"] / 60),
        "legs": " > ".join(f"{lg['mode'].lower()} {((lg.get('route') or {}).get('shortName') or '')}".strip()
                           for lg in legs) or "walk only",
    }


def is_walk_only(it):
    return all(lg["mode"] == "WALK" for lg in it["legs"])


def pt_ok(it):
    return not is_walk_only(it) or it["duration"] <= WALK_ONLY_CAP_MIN * 60


def best_am(plan):
    lo = epoch_ms(TT_DATE, AM_ARRIVE) - AM_WINDOW_MIN * 60000
    hi = epoch_ms(TT_DATE, AM_ARRIVE)
    its = [i for i in (plan or {}).get("itineraries", []) if lo <= i["endTime"] <= hi and pt_ok(i)]
    if not its:
        return None, None
    it = min(its, key=lambda i: (i["duration"], -i["endTime"]))
    a = describe(it)
    a["slack_at_site_min"] = round((hi - it["endTime"]) / 60000)
    return round(it["duration"] / 60), a


def best_late(plan):
    t0 = epoch_ms(TT_DATE, LATE_DEPART)
    lim = t0 + LATE_MAX_MIN * 60000
    its = [i for i in (plan or {}).get("itineraries", [])
           if i["startTime"] >= t0 - 60000 and i["endTime"] <= lim and pt_ok(i)]
    if not its:
        return None, None
    it = min(its, key=lambda i: (i["endTime"], i["duration"]))
    a = describe(it)
    a["in_journey_min"] = round(it["duration"] / 60)
    a["wait_at_site_min"] = round((it["startTime"] - t0) / 60000)
    return round((it["endTime"] - t0) / 60000), a


def best_street(plan):
    its = (plan or {}).get("itineraries", [])
    if not its:
        return None
    return round(min(i["duration"] for i in its) / 60, 1)


# ---------------------------------------------------------------- main
def main():
    refresh = "--refresh" in sys.argv
    TRAVEL.mkdir(parents=True, exist_ok=True)
    OTPDIR.mkdir(parents=True, exist_ok=True)

    lookup = json.loads((OUT / "geo" / "lookup_lsoa.json").read_text())
    codes = set(lookup)
    centroids = load_centroids(codes)
    n_pwc = sum(1 for v in centroids.values() if v[2] == "pwc")
    log(f"{len(centroids)} LSOA origins ({n_pwc} population-weighted centroids)")

    osm = download(OSM_URL, TRAVEL / "bedfordshire-latest.osm.pbf", refresh)
    bods = {r: download(BODS_URL.format(r), TRAVEL / f"bods_{r}_gtfs.zip", refresh) for r in BODS_REGIONS}

    # Inputs stamp: OSM + BODS + rail source + dates + config => graph & answers cache key.
    rail_hash = hashlib.sha256(b"".join(p.read_bytes() for p in sorted(RAIL_SRC.glob("*.txt")))).hexdigest()[:16]
    parts = [sha_file(osm)] + [sha_file(p) for p in bods.values()] + [rail_hash, TT_DATE.isoformat(),
                                                                       OTP_IMAGE, json.dumps(DEST), "v1"]
    stamp = hashlib.sha256("|".join(parts).encode()).hexdigest()[:12]
    stamp_p = OTPDIR / "STAMP"
    feeds = [("RAIL", "gtfs_rail_modelled.zip")] + [(r.upper().replace("_", ""), f"gtfs_bods_{r}.zip")
                                                     for r in BODS_REGIONS]
    filt_stats = {}
    stats_p = OTPDIR / "filter_stats.json"
    if not stamp_p.exists() or stamp_p.read_text() != stamp or not (OTPDIR / "graph.obj").exists():
        log("building inputs + graph (stamp changed)")
        for r, p in bods.items():
            filt_stats[r] = filter_gtfs(p, OTPDIR / f"gtfs_bods_{r}.zip")
            filt_stats[r]["feed_validity"] = feed_validity(p)
        stats_p.write_text(json.dumps(filt_stats))
        zip_rail(OTPDIR / "gtfs_rail_modelled.zip")
        (OTPDIR / "bedfordshire.osm.pbf").write_bytes(osm.read_bytes())
        write_otp_config(feeds)
        (OTPDIR / "graph.obj").unlink(missing_ok=True)
        t0 = time.time()
        r = docker(*otp_run_args(["--build", "--save"], heap="12g"), capture_output=True, text=True)
        (TRAVEL / "otp_build.log").write_text(r.stdout + r.stderr)
        if r.returncode or not (OTPDIR / "graph.obj").exists():
            raise RuntimeError("OTP build failed; see data/raw/travel/otp_build.log")
        log(f"graph built in {time.time() - t0:.0f}s")
        stamp_p.write_text(stamp)
    filt_stats = json.loads(stats_p.read_text()) if stats_p.exists() else {}

    cache, n_new = run_queries(centroids, stamp)
    log(f"OTP queries run this time: {n_new}")

    pop = {}
    pdoc = json.loads((OUT / "pop_lsoa.json").read_text())
    prow = [r for r in pdoc["rows"] if r["indicator"] == "popsa_16_64" and r["level"] == "LSOA"]
    pop_period = max(r["period"] for r in prow)
    for r in prow:
        if r["period"] == pop_period:
            pop[r["code"]] = r["value"]

    period = f"Timetables for Tue {TT_DATE:%d %b %Y}"
    rows, res = [], {}
    for code in sorted(centroids):
        lat, lon, ctype = centroids[code]
        g = lambda k: cache.get(f"{stamp}|{k}|{code}|{lat},{lon}")  # noqa: E731
        am, am_a = best_am(g("pt_am"))
        late, late_a = best_late(g("pt_late"))
        car, bike, walk = best_street(g("car")), best_street(g("bike")), best_street(g("walk"))
        late_ok = late is not None and late <= LATE_OK_MIN
        res[code] = {"am": am, "late": late, "late_ok": late_ok, "car": car}
        info = lookup[code]
        base = {"code": code, "name": info["name"], "level": "LSOA", "period": period, "la": info["la"],
                "ci": None, "num": None, "den": None, "breakdown": None}
        cattrs = {"origin": ctype, "origin_lat": lat, "origin_lon": lon}

        def add(ind, value, attrs=None):
            rows.append({**base, "indicator": ind, "value": value, "attrs": {**cattrs, **(attrs or {})}})

        add("tt_pt_am_min", am, am_a if am is not None else {"no_journey": True})
        add("tt_pt_late_min", late, late_a if late is not None else {"no_journey": True})
        add("tt_pt_late_ok_pct", 100 if late_ok else 0)
        add("tt_car_min", None if car is None else round(car))
        add("tt_cycle_min", None if bike is None else round(bike))
        add("tt_walk_min", None if walk is None else round(walk))

    # LA + county population-weighted shares
    groups = {la: [c for c in res if lookup[c]["la"] == la] for la in LAS}
    groups["BEDS"] = list(res)
    missing_pop = [c for c in res if c not in pop]
    for gcode, members in groups.items():
        den = sum(pop.get(c, 0) for c in members)
        tests = {
            "tt_pop1664_pt45_pct": lambda c: res[c]["am"] is not None and res[c]["am"] <= 45,
            "tt_pop1664_pt60_pct": lambda c: res[c]["am"] is not None and res[c]["am"] <= 60,
            "tt_pop1664_car30_pct": lambda c: res[c]["car"] is not None and res[c]["car"] <= 30,
            "tt_pt_late_ok_pct": lambda c: res[c]["late_ok"],
        }
        for ind, test in tests.items():
            num = sum(pop.get(c, 0) for c in members if test(c))
            rows.append({"code": gcode, "name": LAS.get(gcode, "Bedfordshire (3 UAs)"),
                         "level": "LA" if gcode in LAS else "county", "indicator": ind,
                         "value": round(100 * num / den, 1) if den else None, "period": period,
                         "ci": None, "num": num, "den": den, "breakdown": "residents aged 16-64",
                         "attrs": {"lsoas": len(members), "pop_period": pop_period}})

    rail_note = (
        "Rail is a hand-built GTFS (pipeline/travel/rail_gtfs/): Marston Vale line Bedford-Bletchley "
        "Mon-Fri trips transcribed train-by-train from London Northwestern Railway's timetable valid "
        "18 May-11 Dec 2026 (" + LNR_MV_URL + "; full hourly train service assumed running as published, "
        "after the 2022-24 suspension ended 19 Feb 2024 - no current suspension found, but East West Rail "
        "works can bring bus replacement at short notice). Thameslink Bedford-Flitwick-Harlington-Leagrave-"
        "Luton-Luton Airport Parkway (every 15 min ~05:15-22:00, then every 30 min; ~25 min end to end) and "
        "EMR Connect Bedford-Luton-Luton Airport Parkway (every 30 min, 15 min non-stop) are MODELLED as "
        "regular headways (frequencies.txt) from the Summer 2026 (to 12 Dec 2026) weekday pattern; real "
        "departures differ by a few minutes and peak-only fast Thameslink trains are omitted. No other rail."
    )
    vals = [r["value"] for r in rows if r["indicator"] == "tt_pt_am_min" and r["value"] is not None]
    meta = {
        "title": "Journey times from each LSOA to the proposed Universal resort site (Kempston Hardwick)",
        "publisher": "Derived: DfT Bus Open Data Service (BODS) timetables; OpenStreetMap contributors (ODbL); "
                     "rail modelled from London Northwestern Railway / Thameslink / EMR published timetables; "
                     "ONS LSOA 2021 population-weighted centroids; routed with OpenTripPlanner 2",
        "source_url": "https://data.bus-data.dft.gov.uk/timetable/download/",
        "api_url": [OSM_URL] + [BODS_URL.format(r) for r in BODS_REGIONS] + [
            PWC_URL + "?where=LSOA21CD IN (<417 Bedfordshire LSOAs>)&outSR=4326&f=json", LNR_MV_URL,
            "https://naptan.api.dft.gov.uk/v1/access-nodes?dataFormat=csv&atcoAreaCodes=910 (station coordinates)"],
        "geography": "LSOA21, LA",
        "cohort": "16-19, 18-24, 25+ inactive",
        "period": period,
        "latest_period": period,
        "frequency": "Ad hoc (re-run on refresh)",
        "next_update": "Re-run when BODS timetables or the Dec 2026 rail timetable change",
        "access": "API",
        "quality": (
            "Modelled journey times, not observed. Routed by OpenTripPlanner " + OTP_IMAGE.split(":")[1]
            + " (Docker, batch) over the Geofabrik Bedfordshire OSM extract and BODS GTFS (south_east, "
            "east_anglia, east_midlands regional feeds, cut to trips on the modelled day calling within "
            f"{BBOX}). Destination {DEST['lat']},{DEST['lon']} (Kempston Hardwick site; not common.SITE). "
            f"Origins: {n_pwc} of {len(centroids)} LSOAs use ONS LSOA 2021 population-weighted centroids, the rest "
            "geometric centroids. tt_pt_am_min = shortest public-transport+walk journey (leave origin -> reach "
            f"site) among itineraries arriving 07:30-08:30 (OTP arriveBy {AM_ARRIVE}, 60-min search window); "
            "the traveller leaves just in time, so it excludes waiting before the first departure and any "
            "early-arrival slack at the site (slack_at_site_min in attrs). tt_pt_late_min = minutes from "
            f"{LATE_DEPART} (shift end) until arrival home, earliest arrival, so it includes waiting at the site; "
            f"null if not home by 00:30. tt_pt_late_ok_pct = 100 if home within {LATE_OK_MIN} min (by 00:00). "
            f"Walk-only answers count as PT only up to {WALK_ONLY_CAP_MIN} min. Walk 1.33 m/s, cycle 5 m/s "
            "(18 km/h), 2-min transfer slack, access/egress walk <= 45 min."
        ),
        "limitations": (
            f"Single modelled weekday (Tue {TT_DATE:%d %b %Y}) - school-day timetables; Saturdays/Sundays, "
            "school holidays and real-time disruption are not modelled. Car times are free-flow from OSM road "
            "speeds and ignore congestion, junction delay and parking (so they understate peak driving times, "
            "especially Luton-A6/M1 and Bedford town). Cycle times ignore hills and route quality. One point "
            "per LSOA: residents far from the centroid may face longer walks. Demand-responsive transport, "
            "works shuttles, taxis and any future resort bus/rail link are excluded. Bus timetables are as "
            "registered in BODS (published schedules, not punctuality). " + rail_note
        ),
        "licence": "BODS timetable data: Open Government Licence v3.0; OpenStreetMap: Open Database Licence "
                   "(ODbL) 1.0, (c) OpenStreetMap contributors; ONS centroids & NaPTAN: OGL v3.0; "
                   "rail timetable facts from operators' published timetables",
        "rail_assumption": rail_note,
        "router": OTP_IMAGE,
        "destination": DEST,
        "inputs_stamp": stamp,
        "gtfs_filter": filt_stats,
        "indicators": [
            {"id": "tt_pt_am_min", "label": "Public transport to site, arrive by 08:30 (min)", "unit": "minutes",
             "cohort": "all", "polarity": "higher_is_worse",
             "description": "Shortest bus/rail + walk journey from the LSOA centroid arriving at the site between "
                            "07:30 and 08:30 on a typical weekday; null when no journey exists (attrs.no_journey)."},
            {"id": "tt_pt_late_min", "label": "Public transport home after 22:30 shift end (min)", "unit": "minutes",
             "cohort": "all", "polarity": "higher_is_worse",
             "description": "Minutes from 22:30 at the site until arrival at the LSOA centroid (earliest arrival, "
                            "includes waiting); null when not home by 00:30."},
            {"id": "tt_pt_late_ok_pct", "label": "Can get home by public transport within 90 min of a 22:30 finish",
             "unit": "percent", "cohort": "all", "polarity": "higher_is_better",
             "description": "LSOA: 100 or 0. LA/county: % of residents aged 16-64 living in LSOAs where it is "
                            "possible (population-weighted, num/den given)."},
            {"id": "tt_car_min", "label": "Car to site (min, free-flow)", "unit": "minutes", "cohort": "all",
             "polarity": "higher_is_worse", "description": "OTP car routing on OSM roads; no congestion."},
            {"id": "tt_cycle_min", "label": "Cycle to site (min)", "unit": "minutes", "cohort": "all",
             "polarity": "higher_is_worse", "description": "OTP bicycle routing at 18 km/h."},
            {"id": "tt_walk_min", "label": "Walk to site (min)", "unit": "minutes", "cohort": "all",
             "polarity": "higher_is_worse", "description": "OTP walk routing at 4.8 km/h (up to 4 h)."},
            {"id": "tt_pop1664_pt45_pct", "label": "16-64s within 45 min by public transport (am)",
             "unit": "percent", "cohort": "all", "polarity": "higher_is_better",
             "description": "% of residents aged 16-64 (ONS SAPE, " + pop_period + ") in LSOAs with tt_pt_am_min <= 45."},
            {"id": "tt_pop1664_pt60_pct", "label": "16-64s within 60 min by public transport (am)",
             "unit": "percent", "cohort": "all", "polarity": "higher_is_better",
             "description": "% of residents aged 16-64 in LSOAs with tt_pt_am_min <= 60."},
            {"id": "tt_pop1664_car30_pct", "label": "16-64s within 30 min by car", "unit": "percent",
             "cohort": "all", "polarity": "higher_is_better",
             "description": "% of residents aged 16-64 in LSOAs with tt_car_min <= 30 (free-flow)."},
        ],
    }
    save("travel_lsoa", meta, rows)

    # summary
    nulls = sum(1 for r in rows if r["indicator"] == "tt_pt_am_min" and r["value"] is None)
    log(f"LSOAs {len(res)}; missing pop {len(missing_pop)}")
    if vals:
        q = statistics.quantiles(vals, n=10)
        log(f"tt_pt_am_min: n={len(vals)} null={nulls} median={statistics.median(vals)} "
            f"p10={q[0]:.0f} p90={q[-1]:.0f} <=45: {sum(v <= 45 for v in vals)} <=60: {sum(v <= 60 for v in vals)}")
    for r in rows:
        if r["level"] != "LSOA":
            log(f"  {r['name']:<22} {r['indicator']:<22} {r['value']}  ({r['num']}/{r['den']})")


if __name__ == "__main__":
    main()
