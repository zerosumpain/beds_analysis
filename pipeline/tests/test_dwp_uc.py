"""Unit tests for the Stat-Xplore response parser in fetch_dwp_uc.py.

Run from pipeline/:  python3 -m unittest            (or: python3 -m unittest tests.test_dwp_uc)

The sample below is hand-made in the /table response shape documented at
https://stat-xplore.dwp.gov.uk/webapi/online-help/Open-Data-API-Table.html
(fields[].items[] with labels/uris in dimension order; cubes keyed by measure id
holding nested `values`). It has NOT been checked against a live response.
"""
import os
import pathlib
import sys
import unittest
from unittest import mock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
import fetch_dwp_uc as uc  # noqa: E402

M = uc.MEASURE
GEO_VS = "str:value:UC_Monthly:V_F_UC_CASELOAD_FULL:COA_CODE:V_C_MASTERGEOG21_LA_TO_REGION:"
LSOA_VS = "str:value:UC_Monthly:V_F_UC_CASELOAD_FULL:COA_CODE:V_C_MASTERGEOG21_LSOA_TO_MSOA:"
MONTH = "str:value:UC_Monthly:F_UC_DATE:DATE_NAME:C_UC_DATE:"
COND = "str:value:UC_Monthly:V_F_UC_CASELOAD_FULL:CCCONDITIONALITY_REGIME:C_UC_CONDITIONALITY_REGIME:"
COND_ITEMS = [("Searching for work", "AA"), ("Working - with requirements", "AB"),
              ("No work requirements", "BC"), ("Planning for work", "BD"),
              ("Preparing for work", "CE"), ("Working - no requirements", "DF"),
              ("Unknown or missing", "ZZ")]


def item(label, uri):
    return {"type": "RecodeItem", "labels": [label], "uris": [uri], "annotationKeys": []}


def total_item():
    return {"type": "Total", "labels": ["Total"], "uris": [], "annotationKeys": []}


def cond_field():
    return {"uri": uc.F_COND, "label": "Conditionality Regime", "annotationKeys": [],
            "items": [item(lab, COND + c) for lab, c in COND_ITEMS] + [total_item()]}


def regime_values(base):
    """searching, working_req, nwr, planning, preparing, working_noreq, unknown, total."""
    parts = [base * 4, base * 2, base * 3, base, base, base * 2, 1]
    return parts + [sum(parts)]


def la_response():
    geos = [("Bedford", "E06000055"), ("Central Bedfordshire", "E06000056"),
            ("Luton", "E06000032"), ("East of England", "E12000006"), ("England", "E92000001")]
    months = [("August 2026", "202608"), ("September 2026", "202609")]
    values = [[regime_values(10 * (gi + 1) + mi) for mi in range(len(months))]
              for gi in range(len(geos))]
    return {
        "query": {"database": uc.DB, "measures": [M], "recodes": {}, "dimensions": []},
        "database": {"id": uc.DB, "annotationKeys": []},
        "fields": [
            {"uri": uc.F_GEO, "label": "National - Regional - LA - OAs", "annotationKeys": [],
             "items": [item(n, GEO_VS + c) for n, c in geos]},
            {"uri": uc.F_MONTH, "label": "Month", "annotationKeys": [],
             "items": [item(n, MONTH + c) for n, c in months]},
            cond_field(),
        ],
        "measures": [{"uri": M, "label": "People on Universal Credit"}],
        "cubes": {M: {"values": values, "precision": 0}},
        "annotationMap": {},
    }


def lsoa_response(codes):
    return {
        "database": {"id": uc.DB},
        "fields": [
            {"uri": uc.F_GEO, "label": "National - Regional - LA - OAs",
             "items": [item(c, LSOA_VS + c) for c in codes]},
            {"uri": uc.F_MONTH, "label": "Month",
             "items": [item("September 2026", MONTH + "202609")]},
            cond_field(),
        ],
        "measures": [{"uri": M, "label": "People on Universal Credit"}],
        "cubes": {M: {"values": [[regime_values(2)] for _ in codes]}},
    }


LSOAS = {"E01015693": {"la": "E06000032", "name": "Luton 007A", "msoa": "E02003264"},
         "E01017500": {"la": "E06000055", "name": "Bedford 001A", "msoa": "E02003250"}}
POP = {("E06000055", 2025): 120000, ("E06000056", 2025): 190000, ("E06000032", 2025): 150000,
       ("BEDS", 2025): 460000, ("E12000006", 2025): 4000000, ("E92000001", 2024): 36000000,
       ("E01015693", 2024): 1000}


class ParseTable(unittest.TestCase):
    def test_flatten_shape_and_totals(self):
        cells = uc.parse_table(la_response())
        self.assertEqual(len(cells), 5 * 2 * 8)
        first = cells[0]
        self.assertEqual(first["items"][0][2], GEO_VS + "E06000055")
        self.assertEqual(first["items"][2][1], "Searching for work")
        self.assertEqual(first["value"], 40)
        self.assertIsNone(cells[7]["items"][2][2])  # Total item has no uri

    def test_cubes_as_documented_array(self):
        resp = la_response()
        resp["cubes"] = [{"values": resp["cubes"][M]["values"]}]
        self.assertEqual(len(uc.parse_table(resp)), 80)

    def test_axis_mismatch_raises(self):
        resp = la_response()
        resp["fields"][1]["items"].pop()
        with self.assertRaises(ValueError):
            uc.parse_table(resp)

    def test_float_and_null_cells(self):
        resp = lsoa_response(["E01015693"])
        resp["cubes"][M]["values"][0][0][0] = 12.0
        resp["cubes"][M]["values"][0][0][1] = None
        cells = uc.parse_table(resp)
        self.assertEqual(cells[0]["value"], 12)
        self.assertIsInstance(cells[0]["value"], int)
        self.assertIsNone(cells[1]["value"])


class Tabulate(unittest.TestCase):
    def test_regimes_mapped_and_merged(self):
        tab = uc.tabulate(uc.parse_table(la_response()))
        d = tab[("E06000055", "202609", "September 2026")]  # base 11
        self.assertEqual(d["uc_searching"], 44)
        self.assertEqual(d["uc_working_req"], 22)
        self.assertEqual(d["uc_nwr"], 33)
        self.assertEqual(d["uc_planning_preparing"], 22)  # planning + preparing
        self.assertEqual(d["uc_working_noreq"], 22)
        self.assertEqual(d["uc_cond_unknown"], 1)
        self.assertEqual(d["uc_people"], 44 + 22 + 33 + 11 + 11 + 22 + 1)

    def test_label_normalisation(self):
        self.assertEqual(uc.cond_indicator("Working – with requirements"), "uc_working_req")
        self.assertEqual(uc.cond_indicator(" No work requirements "), "uc_nwr")
        self.assertEqual(uc.cond_indicator("Unknown or missing"), uc.COND_OTHER)


class BuildRows(unittest.TestCase):
    def setUp(self):
        self.la = uc.tabulate(uc.parse_table(la_response()))
        self.small = uc.tabulate(uc.parse_table(lsoa_response(sorted(LSOAS))))
        self.rows, self.latest = uc.build_rows(self.la, self.small, LSOAS, POP)
        self.get = {(r["code"], r["indicator"], r["period"]): r for r in self.rows}

    def test_latest_and_levels(self):
        self.assertEqual(self.latest, "September 2026")
        levels = {r["level"] for r in self.rows}
        self.assertEqual(levels, {"LA", "region", "country", "county", "LSOA"})
        ids = {r["indicator"] for r in self.rows}
        self.assertTrue({"uc_people", "uc_nwr", "uc_searching", "uc_working_req",
                         "uc_planning_preparing", "uc_nwr_rate"} <= ids)
        self.assertNotIn(uc.COND_OTHER, ids)
        self.assertEqual({i["id"] for i in uc.INDICATORS}, ids)

    def test_beds_sums_counts_and_recomputes_rate(self):
        # Sept: bases 11, 21, 31 -> nwr 33 + 63 + 93
        r = self.get[("BEDS", "uc_nwr", "September 2026")]
        self.assertEqual(r["value"], 189)
        rate = self.get[("BEDS", "uc_nwr_rate", "September 2026")]
        self.assertEqual(rate["num"], 189)
        self.assertEqual(rate["den"], 460000)
        self.assertAlmostEqual(rate["value"], round(100 * 189 / 460000, 2))

    def test_rate_uses_nearest_earlier_population(self):
        r = self.get[("E92000001", "uc_nwr_rate", "September 2026")]
        self.assertEqual(r["den"], 36000000)  # only mid-2024 available

    def test_lsoa_rows(self):
        r = self.get[("E01015693", "uc_nwr", "September 2026")]
        self.assertEqual((r["value"], r["la"], r["name"]), (6, "E06000032", "Luton 007A"))
        self.assertIn(("E01015693", "uc_nwr_rate", "September 2026"), self.get)
        self.assertNotIn(("E01017500", "uc_nwr_rate", "September 2026"), self.get)  # no pop

    def test_month_window(self):
        old = uc.MONTHS
        try:
            uc.MONTHS = 1
            rows, _ = uc.build_rows(self.la, {}, LSOAS, POP)
            self.assertEqual({r["period"] for r in rows}, {"September 2026"})
        finally:
            uc.MONTHS = old


class KeyAndQueries(unittest.TestCase):
    def test_key_from_env(self):
        with mock.patch.dict(os.environ, {uc.KEY_ENV: "  abc  "}):
            self.assertEqual(uc.api_key(), "abc")

    def test_no_key(self):
        with mock.patch.dict(os.environ, {}, clear=True), \
                mock.patch.object(uc, "KEY_FILES", [pathlib.Path("/nonexistent/statxplore.key")]):
            self.assertIsNone(uc.api_key())

    def test_value_id_pattern_matches_documented_example(self):
        vs = "str:valueset:PIP_Monthly:V_F_PIP_MONTHLY:LA_code:V_C_GEOG05_REGION_TO_COUNTRY"
        self.assertEqual(uc.value_id(vs, "E12000007"),
                         "str:value:PIP_Monthly:V_F_PIP_MONTHLY:LA_code:"
                         "V_C_GEOG05_REGION_TO_COUNTRY:E12000007")

    def test_query_shape(self):
        q = uc.la_query(uc.VALUESETS)
        self.assertEqual(set(q), {"database", "measures", "recodes", "dimensions"})
        self.assertEqual(q["dimensions"], [[uc.F_GEO], [uc.F_MONTH], [uc.F_COND]])
        self.assertEqual(len(q["recodes"][uc.F_GEO]["map"]), 5)
        self.assertFalse(q["recodes"][uc.F_GEO]["total"])


if __name__ == "__main__":
    unittest.main()
