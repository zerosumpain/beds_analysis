"""OSGB36 British National Grid easting/northing -> WGS84 lat/lon (pure Python).

Method (Ordnance Survey, "A guide to coordinate systems in Great Britain"):
1. Inverse Transverse Mercator on the Airy 1830 ellipsoid -> OSGB36 lat/lon.
2. Lat/lon -> cartesian XYZ on Airy 1830.
3. 7-parameter Helmert transform OSGB36 -> WGS84 (ETRS89).
4. XYZ -> lat/lon on the GRS80/WGS84 ellipsoid (iterative).
Accuracy is ~5 m (Helmert approximation), ample for mapping and distances.
"""
import math

# Airy 1830 ellipsoid and National Grid projection constants.
AIRY_A, AIRY_B = 6377563.396, 6356256.909
F0 = 0.9996012717
LAT0, LON0 = math.radians(49), math.radians(-2)
N0, E0 = -100000.0, 400000.0
# WGS84 / GRS80 ellipsoid.
WGS_A, WGS_B = 6378137.000, 6356752.3141
# Helmert OSGB36 -> WGS84 (metres, ppm, arc-seconds).
TX, TY, TZ = 446.448, -125.157, 542.060
S_PPM = -20.4894
RX, RY, RZ = 0.1502, 0.2470, 0.8421


def _osgb36_latlon(e, n):
    a, b = AIRY_A, AIRY_B
    e2 = 1 - (b * b) / (a * a)
    nn = (a - b) / (a + b)
    lat, m = LAT0, 0.0
    while True:
        lat = (n - N0 - m) / (a * F0) + lat
        ma = (1 + nn + 1.25 * nn ** 2 + 1.25 * nn ** 3) * (lat - LAT0)
        mb = (3 * nn + 3 * nn ** 2 + 2.625 * nn ** 3) * math.sin(lat - LAT0) * math.cos(lat + LAT0)
        mc = (1.875 * nn ** 2 + 1.875 * nn ** 3) * math.sin(2 * (lat - LAT0)) * math.cos(2 * (lat + LAT0))
        md = (35 / 24) * nn ** 3 * math.sin(3 * (lat - LAT0)) * math.cos(3 * (lat + LAT0))
        m = b * F0 * (ma - mb + mc - md)
        if abs(n - N0 - m) < 0.00001:
            break
    s, c, t = math.sin(lat), math.cos(lat), math.tan(lat)
    nu = a * F0 / math.sqrt(1 - e2 * s * s)
    rho = a * F0 * (1 - e2) / (1 - e2 * s * s) ** 1.5
    eta2 = nu / rho - 1
    vii = t / (2 * rho * nu)
    viii = t / (24 * rho * nu ** 3) * (5 + 3 * t * t + eta2 - 9 * t * t * eta2)
    ix = t / (720 * rho * nu ** 5) * (61 + 90 * t * t + 45 * t ** 4)
    x = 1 / (c * nu)
    xi = 1 / (c * 6 * nu ** 3) * (nu / rho + 2 * t * t)
    xii = 1 / (c * 120 * nu ** 5) * (5 + 28 * t * t + 24 * t ** 4)
    xiia = 1 / (c * 5040 * nu ** 7) * (61 + 662 * t * t + 1320 * t ** 4 + 720 * t ** 6)
    de = e - E0
    lat_out = lat - vii * de ** 2 + viii * de ** 4 - ix * de ** 6
    lon_out = LON0 + x * de - xi * de ** 3 + xii * de ** 5 - xiia * de ** 7
    return lat_out, lon_out


def _to_xyz(lat, lon, a, b, h=0.0):
    e2 = 1 - (b * b) / (a * a)
    nu = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
    return ((nu + h) * math.cos(lat) * math.cos(lon),
            (nu + h) * math.cos(lat) * math.sin(lon),
            ((1 - e2) * nu + h) * math.sin(lat))


def _from_xyz(x, y, z, a, b):
    e2 = 1 - (b * b) / (a * a)
    p = math.hypot(x, y)
    lat = math.atan2(z, p * (1 - e2))
    for _ in range(10):
        nu = a / math.sqrt(1 - e2 * math.sin(lat) ** 2)
        lat = math.atan2(z + e2 * nu * math.sin(lat), p)
    return lat, math.atan2(y, x)


def osgb_to_wgs84(easting, northing):
    """Return (lat, lon) in WGS84 decimal degrees for a BNG easting/northing."""
    lat, lon = _osgb36_latlon(float(easting), float(northing))
    x1, y1, z1 = _to_xyz(lat, lon, AIRY_A, AIRY_B)
    s = S_PPM * 1e-6
    rx, ry, rz = (math.radians(v / 3600) for v in (RX, RY, RZ))
    x2 = TX + (1 + s) * x1 - rz * y1 + ry * z1
    y2 = TY + rz * x1 + (1 + s) * y1 - rx * z1
    z2 = TZ - ry * x1 + rx * y1 + (1 + s) * z1
    lat2, lon2 = _from_xyz(x2, y2, z2, WGS_A, WGS_B)
    return math.degrees(lat2), math.degrees(lon2)


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _selftest(tol_m=5.0):
    """Check against OS worked example and OSTN15-derived postcode centroids.

    Truth values: OS guide (OSGB36 step) and postcodes.io / ONSPD lat/lon for the
    same easting/northing (OSTN15). Helmert agrees to ~2 m around Bedfordshire.
    """
    la, lo = _osgb36_latlon(651409.903, 313177.270)
    assert abs(math.degrees(la) - 52.6575703) < 1e-6 and abs(math.degrees(lo) - 1.7179216) < 1e-6
    cases = [
        (504898, 249177, 52.130964, -0.468919),  # MK42 9AU, Bedford
        (509441, 221157, 51.878258, -0.411514),  # LU1 3JU, Luton
        (495382, 242190, 52.069887, -0.609848),  # MK43 0BZ, Cranfield
        (530047, 179951, 51.503541, -0.127670),  # SW1A 2AA, London
    ]
    errs = []
    for e, n, la, lo in cases:
        g = osgb_to_wgs84(e, n)
        err = haversine_km(g[0], g[1], la, lo) * 1000
        assert err < tol_m, (e, n, g, err)
        errs.append(round(err, 2))
    return errs


if __name__ == "__main__":
    print("osgb self-test errors (m):", _selftest())
