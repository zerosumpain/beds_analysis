"""Boundaries (GeoJSON, WGS84) and an LSOA21 lookup for the Bedfordshire maps.

Source: ONS Open Geography Portal hosted ArcGIS FeatureServers. Generalised
(BGC, 20 m) layers are queried with `where=` filters, `outSR=4326`,
`f=geojson`; coordinates are rounded to 5 dp (~1 m) and de-duplicated.

Writes site/data/geo/{la,la_context,lsoa,msoa,pcon,wards}.geojson,
site/data/geo/lookup_lsoa.json and the lineage dataset geo_boundaries.
"""
import json
import urllib.parse
import urllib.request

from common import LAS, OUT, RAW, UA, fetch, fetch_csv, save

ARC = "https://services1.arcgis.com/ESMARspQHYMw9BZ9/arcgis/rest/services"
GEO = OUT / "geo"
DP = 5

SVC = {
    "lad": "Local_Authority_Districts_DEC_2025_Boundaries_UK_BGC",
    "lsoa": "Lower_layer_Super_Output_Areas_December_2021_Boundaries_EW_BGC_V5",
    "msoa": "Middle_layer_Super_Output_Areas_December_2021_Boundaries_EW_BGC_V3",
    "pcon": "Westminster_Parliamentary_Constituencies_July_2024_Boundaries_UK_BGC",
    "ward": "Wards_December_2024_Boundaries_UK_BGC",
    "lu_ward": "LSOA21_WD25_LAD25_EW_LU_v2",
    "lu_pcon": "LSOA21_PCON24_LAD21_EW_LU",
}
HCL_MSOA = "https://houseofcommonslibrary.github.io/msoanames/MSOA-Names-Latest2.csv"
LA_IN = "('" + "','".join(LAS) + "')"
URLS = []  # every query URL actually used (lineage)


def qurl(svc, params):
    return f"{ARC}/{svc}/FeatureServer/0/query?" + urllib.parse.urlencode(params)


def arc_query(svc, where, fields, geometry=True, page=1000, tag=None):
    """Page through a FeatureServer query; return list of GeoJSON features."""
    feats, offset = [], 0
    while True:
        params = {
            "where": where, "outFields": fields, "outSR": 4326,
            "returnGeometry": "true" if geometry else "false",
            "resultOffset": offset, "resultRecordCount": page, "f": "geojson",
        }
        url = qurl(svc, params)
        if offset == 0:
            URLS.append(url)
        cache = f"geo_{tag or svc}_{offset}.json" if tag else None
        d = json.loads(fetch(url, cache))
        if "error" in d:
            raise RuntimeError(f"{svc}: {d['error']}")
        got = d.get("features", [])
        feats += got
        if len(got) < page and not d.get("properties", {}).get("exceededTransferLimit"):
            break
        offset += len(got)
    return feats


def arc_post(svc, params):
    """POST a query (for geometry filters too long for a GET)."""
    url = f"{ARC}/{svc}/FeatureServer/0/query"
    body = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as r:
        d = json.loads(r.read())
    if "error" in d:
        raise RuntimeError(f"{svc}: {d['error']}")
    URLS.append(url + " (POST: spatial intersects with Bedfordshire, distance 50 m)")
    return d


def round_ring(ring):
    out = []
    for x, y in ring:
        p = (round(x, DP), round(y, DP))
        if not out or p != out[-1]:
            out.append(p)
    if out and out[0] != out[-1]:
        out.append(out[0])
    return [list(p) for p in out] if len(out) >= 4 else None


def clean_geom(g):
    polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
    res = []
    for poly in polys:
        rings = [r for r in (round_ring(r) for r in poly) if r]
        if rings:
            res.append(rings)
    if len(res) == 1:
        return {"type": "Polygon", "coordinates": res[0]}
    return {"type": "MultiPolygon", "coordinates": res}


def write_fc(name, feats):
    GEO.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection", "features": feats}
    p = GEO / f"{name}.geojson"
    p.write_text(json.dumps(fc, separators=(",", ":")))
    size = p.stat().st_size
    print(f"  {p.name}: {len(feats)} features, {size/1024:.0f} KB")
    return size


def feat(props, geom):
    return {"type": "Feature", "properties": props, "geometry": clean_geom(geom)}


def main():
    layers = {}

    # --- LAs -------------------------------------------------------------
    la = arc_query(SVC["lad"], f"LAD25CD IN {LA_IN}", "LAD25CD,LAD25NM", tag="lad_beds")
    la_feats = [feat({"code": f["properties"]["LAD25CD"], "name": f["properties"]["LAD25NM"]},
                     f["geometry"]) for f in la]
    assert {f["properties"]["code"] for f in la_feats} == set(LAS), "missing an LA"
    layers["la"] = la_feats

    # Neighbours: spatial intersects (50 m tolerance for generalisation gaps)
    # against the three Bedfordshire polygons, posted as Esri JSON rings.
    rings = []
    for f in la:
        g = f["geometry"]
        polys = [g["coordinates"]] if g["type"] == "Polygon" else g["coordinates"]
        for poly in polys:
            rings += poly
    cache = RAW / "geo_lad_neighbours.json"
    if cache.exists():
        nb = json.loads(cache.read_text())
        URLS.append(f"{ARC}/{SVC['lad']}/FeatureServer/0/query (POST: spatial intersects with Bedfordshire, distance 50 m)")
    else:
        nb = arc_post(SVC["lad"], {
            "where": f"LAD25CD NOT IN {LA_IN}", "outFields": "LAD25CD,LAD25NM",
            "geometry": json.dumps({"rings": rings, "spatialReference": {"wkid": 4326}}),
            "geometryType": "esriGeometryPolygon", "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects", "distance": 50,
            "units": "esriSRUnit_Meter", "returnGeometry": "false", "f": "json",
        })
        cache.write_text(json.dumps(nb))
    nb_codes = sorted(f["attributes"]["LAD25CD"] for f in nb["features"])
    ctx = arc_query(SVC["lad"], "LAD25CD IN ('" + "','".join(nb_codes) + "')",
                    "LAD25CD,LAD25NM", tag="lad_context")
    layers["la_context"] = [feat({"code": f["properties"]["LAD25CD"],
                                  "name": f["properties"]["LAD25NM"]}, f["geometry"])
                            for f in ctx]
    print("  neighbours:", ", ".join(f["properties"]["LAD25NM"] for f in ctx))

    # --- Lookups ---------------------------------------------------------
    lu_w = arc_query(SVC["lu_ward"], f"LAD25CD IN {LA_IN}",
                     "LSOA21CD,LSOA21NM,WD25CD,WD25NM,LAD25CD,LAD25NM",
                     geometry=False, tag="lu_ward")
    lsoa_info = {f["properties"]["LSOA21CD"]: f["properties"] for f in lu_w}
    codes = sorted(lsoa_info)
    # LAD21 codes are unchanged for the three UAs.
    lu_p = arc_query(SVC["lu_pcon"], f"LAD21CD IN {LA_IN}", "LSOA21CD,PCON24CD,PCON24NM",
                     geometry=False, tag="lu_pcon")
    pcon_of = {f["properties"]["LSOA21CD"]: f["properties"] for f in lu_p}

    # --- MSOAs (names: ONS + House of Commons Library) --------------------
    msoa_names = sorted({v["LSOA21NM"][:-1] for v in lsoa_info.values()})
    ms = arc_query(SVC["msoa"], "MSOA21NM IN ('" + "','".join(msoa_names) + "')",
                   "MSOA21CD,MSOA21NM", tag="msoa_beds")
    msoa_by_name = {f["properties"]["MSOA21NM"]: f["properties"]["MSOA21CD"] for f in ms}
    assert len(msoa_by_name) == len(msoa_names), "MSOA name match failed"
    try:
        hcl = {r["msoa21cd"]: r["msoa21hclnm"] for r in fetch_csv(HCL_MSOA, "hcl_msoa_names_2021.csv")}
        URLS.append(HCL_MSOA)
    except Exception as e:  # noqa: BLE001 - HCL names are optional
        print("  HCL MSOA names unavailable:", e)
        hcl = {}
    la_of_msoa = {}
    for v in lsoa_info.values():
        la_of_msoa[msoa_by_name[v["LSOA21NM"][:-1]]] = v["LAD25CD"]
    layers["msoa"] = [feat({"code": f["properties"]["MSOA21CD"], "name": f["properties"]["MSOA21NM"],
                            "hcl_name": hcl.get(f["properties"]["MSOA21CD"]),
                            "la": la_of_msoa[f["properties"]["MSOA21CD"]]}, f["geometry"])
                      for f in ms]

    # --- LSOAs -------------------------------------------------------------
    ls = []
    for i in range(0, len(codes), 60):
        chunk = "','".join(codes[i:i + 60])
        ls += arc_query(SVC["lsoa"], f"LSOA21CD IN ('{chunk}')", "LSOA21CD,LSOA21NM",
                        tag=f"lsoa_beds{i}")
    lsoa_feats = []
    lookup = {}
    for f in sorted(ls, key=lambda f: f["properties"]["LSOA21CD"]):
        c = f["properties"]["LSOA21CD"]
        info = lsoa_info[c]
        lsoa_feats.append(feat({"code": c, "name": f["properties"]["LSOA21NM"],
                                "la": info["LAD25CD"], "la_name": info["LAD25NM"]}, f["geometry"]))
        p = pcon_of.get(c, {})
        lookup[c] = {
            "name": info["LSOA21NM"],
            "msoa": msoa_by_name[info["LSOA21NM"][:-1]],
            "la": info["LAD25CD"], "la_name": info["LAD25NM"],
            "ward": info["WD25CD"], "ward_name": info["WD25NM"],
            "pcon": p.get("PCON24CD"), "pcon_name": p.get("PCON24NM"),
        }
    assert len(lsoa_feats) == len(codes), "LSOA geometry count mismatch"
    layers["lsoa"] = lsoa_feats

    # --- Constituencies ----------------------------------------------------
    pcons = sorted({v["pcon"] for v in lookup.values() if v["pcon"]})
    pc = arc_query(SVC["pcon"], "PCON24CD IN ('" + "','".join(pcons) + "')",
                   "PCON24CD,PCON24NM", tag="pcon_beds")
    layers["pcon"] = [feat({"code": f["properties"]["PCON24CD"], "name": f["properties"]["PCON24NM"]},
                           f["geometry"]) for f in pc]

    # --- Wards (Dec 2024 boundaries; codes checked against the WD25 lookup) -
    wd = arc_query(SVC["ward"], f"LAD24CD IN {LA_IN}", "WD24CD,WD24NM,LAD24CD", tag="ward_beds")
    wcodes = {f["properties"]["WD24CD"] for f in wd}
    lu_wcodes = {v["ward"] for v in lookup.values()}
    if wcodes != lu_wcodes:
        print("  WARNING: ward codes differ between Dec-2024 boundaries and WD25 lookup:",
              sorted(wcodes ^ lu_wcodes))
    layers["wards"] = [feat({"code": f["properties"]["WD24CD"], "name": f["properties"]["WD24NM"],
                             "la": f["properties"]["LAD24CD"]}, f["geometry"]) for f in wd]

    # --- Write ---------------------------------------------------------------
    sizes = {}
    for name, feats in layers.items():
        sizes[name] = write_fc(name, feats)
    assert sizes["lsoa"] < 2.5 * 1024 * 1024, "lsoa.geojson too large"
    (GEO / "lookup_lsoa.json").write_text(json.dumps(lookup, separators=(",", ":"), sort_keys=True))
    print(f"  lookup_lsoa.json: {len(lookup)} LSOAs")

    # --- Lineage dataset ---------------------------------------------------
    rows = []
    for name, feats in layers.items():
        by_la = {}
        for f in feats:
            by_la[f["properties"].get("la")] = by_la.get(f["properties"].get("la"), 0) + 1
        for code, la_name in LAS.items():
            if name in ("lsoa", "msoa", "wards"):
                rows.append({"code": code, "name": la_name, "level": "LA",
                             "indicator": "geo_feature_count", "value": by_la.get(code, 0),
                             "period": "2021 LSOA/MSOA; 2024 PCON/wards; Dec 2025 LAD",
                             "breakdown": f"{name}.geojson"})
        rows.append({"code": "BEDS", "name": "Bedfordshire (3 UAs)", "level": "county",
                     "indicator": "geo_feature_count", "value": len(feats),
                     "period": "2021 LSOA/MSOA; 2024 PCON/wards; Dec 2025 LAD",
                     "breakdown": f"{name}.geojson",
                     "file_kb": round(sizes[name] / 1024)})
    meta = {
        "title": "Map boundaries and LSOA lookup (ONS Open Geography Portal)",
        "publisher": "Office for National Statistics (Open Geography Portal)",
        "source_url": "https://geoportal.statistics.gov.uk/",
        "api_url": URLS,
        "geography": "LA (Dec 2025), LSOA21, MSOA21, PCON (Jul 2024), wards (Dec 2024 / May 2025 lookup)",
        "cohort": "context",
        "period": "LSOA/MSOA Dec 2021; PCON Jul 2024; wards Dec 2024; LAD Dec 2025",
        "frequency": "Ad hoc",
        "next_update": "Annual LAD/ward releases (Dec/May); LSOA/MSOA fixed until Census 2031",
        "access": "API",
        "quality": ("Official ONS boundary products, generalised to 20 m (BGC). Contains OS data "
                    "(c) Crown copyright and database right; source: ONS licensed under OGL v3."),
        "limitations": ("Generalised (20 m) boundaries rounded to 5 dp: for display, not area "
                        "measurement. LSOA->ward and LSOA->constituency lookups are best-fit "
                        "(LSOAs need not nest in 2024 constituencies or wards). Ward polygons are "
                        "Dec 2024; the lookup is May 2025 (codes identical for these LAs at build). "
                        "MSOA codes derived from LSOA names (MSOA name + letter), verified against "
                        "the MSOA layer. HCL MSOA names are informal neighbourhood names."),
        "licence": "Open Government Licence v3.0 (contains OS data (c) Crown copyright and database right)",
        "indicators": [{"id": "geo_feature_count", "label": "Boundary features per map layer",
                        "unit": "count", "cohort": "context", "polarity": "neutral",
                        "description": "Number of polygons in each site/data/geo layer (breakdown = file)."}],
        "files": {f"geo/{n}.geojson": {"features": len(f), "bytes": sizes[n]} for n, f in layers.items()},
    }
    save("geo_boundaries", meta, rows)
    print(f"LSOAs {len(lsoa_feats)}, MSOAs {len(layers['msoa'])}, PCON {len(pc)}, "
          f"wards {len(wd)}, context LAs {len(ctx)}")


if __name__ == "__main__":
    main()
