import unittest

import pandas as pd

from freight_master import (
    apply_freight_lookup,
    build_freight_lookup,
    normalize_loading_point,
    round_freight_charge,
    short_origin,
)


def freight_master_frame(distance=22):
    return pd.DataFrame(
        {
            "Customer Code": ["D62138"],
            "Unnamed: 3": ["MUMC001"],
            "Name of the Distributor": ["Example Customer"],
            "Short Address": ["Example Address"],
            "Distance from Thane": [distance],
            "Unnamed: 12": ["21-30"],
            "Unnamed: 13": [4508.64],
        }
    )


def test_successful_freight_lookup_removes_loading_point_from_result():
    lookup = build_freight_lookup(freight_master_frame())

    result = apply_freight_lookup(
        [{"Customer Code": "mumc 001", "Loading Point": "THANE"}], lookup
    )

    assert result == [{"Customer Code": "mumc 001", "Freight Charge": 4509}]


def test_unknown_customer_leaves_freight_blank():
    result = apply_freight_lookup(
        [{"Customer Code": "MUMC999", "Loading Point": "Thane"}],
        build_freight_lookup(freight_master_frame()),
    )

    assert result[0]["Freight Charge"] == ""


def test_missing_loading_point_leaves_freight_blank():
    result = apply_freight_lookup(
        [{"Customer Code": "MUMC001", "Loading Point": None}],
        build_freight_lookup(freight_master_frame()),
    )

    assert result[0]["Freight Charge"] == ""


def test_missing_distance_is_not_backfilled_from_slab_or_charge():
    result = apply_freight_lookup(
        [{"Customer Code": "MUMC001", "Loading Point": "Thane"}],
        build_freight_lookup(freight_master_frame(distance=None)),
    )

    assert result[0]["Freight Charge"] == ""


def test_workbook_lookup_uses_the_loading_points_distance_triplet():
    lookup = build_freight_lookup(freight_master_frame())

    assert lookup["MUMC001"]["Thane"] == 4508.64


class OriginNormalizationTests(unittest.TestCase):
    def test_bhiwandi_yewai_warehouse_is_not_confused_with_thane_district(self):
        address = (
            "RK LOGI WORLD COMPOUND WAREHOUSE NO - F1, VILLAGE YEWAI, "
            "NEAR KHODIYAAR TEMPLE, TAL. BHIWANDI-YEWAI, BHIWANDI, "
            "DIST THANE, THANE 421302"
        )

        self.assertEqual(normalize_loading_point(address), "Bhiwandi")
        self.assertEqual(short_origin(address), "Bhiwandi")

    def test_normalized_loading_point_replaces_full_from_address(self):
        self.assertEqual(
            short_origin("Complete warehouse address", "Bhiwandi"),
            "Bhiwandi",
        )

    def test_unknown_from_value_is_preserved(self):
        self.assertEqual(
            short_origin("Unrecognized warehouse"),
            "Unrecognized warehouse",
        )


class FreightRoundingTests(unittest.TestCase):
    def test_approved_master_rates_use_required_rounded_figures(self):
        expected_rates = {
            3844.3574443810608: 3844,
            4508.6394748902885: 4509,
            5073.197604029787: 5073,
            6509.0: 6509,
            8747.856159438757: 8748,
            10159.810450732197: 10160,
        }

        for master_rate, expected in expected_rates.items():
            with self.subTest(master_rate=master_rate):
                self.assertEqual(round_freight_charge(master_rate), expected)

    def test_unrelated_special_rate_is_not_changed(self):
        self.assertEqual(round_freight_charge(4902.0), 4902.0)

    def test_standard_invoice_receives_rounded_lookup_rate(self):
        lookup = build_freight_lookup(freight_master_frame())

        result = apply_freight_lookup(
            [
                {
                    "Invoice No.": "MUMCIN270001",
                    "Customer Code": "MUMC001",
                    "Loading Point": "Thane",
                }
            ],
            lookup,
        )

        self.assertEqual(result[0]["Freight Charge"], 4509)

    def test_ton_delivery_challan_always_uses_fixed_rate(self):
        result = apply_freight_lookup(
            [
                {
                    "Invoice No.": " ton-001 ",
                    "Customer Code": "UNKNOWN",
                    "Loading Point": None,
                }
            ],
            {},
        )

        self.assertEqual(result[0]["Freight Charge"], 4327)
