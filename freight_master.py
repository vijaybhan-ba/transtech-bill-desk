"""Freight-master lookups for invoice enrichment.

The freight matrix is part of the same workbook as the customer master.  Each
loading point occupies a three-column group: distance, slab, and freight rate.
Only the resulting freight rate is exposed to the application.
"""

import logging
import math
import re

import pandas as pd

from customer_master import find_mumc_customer_code_column, normalize_customer_code


LOGGER = logging.getLogger(__name__)

LOADING_POINTS = (
    "Thane",
    "Vasai",
    "Andheri",
    "Vidya Vihar",
    "Bhiwandi",
    "Kandivali",
    "PRPL",
    "Wada",
    "Mahul",
    "Khopoli",
    "Kamshet",
)

APPROVED_ROUNDED_FREIGHT_CHARGES = frozenset(
    {3844, 4509, 5073, 6509, 8748, 10160}
)
DELIVERY_CHALLAN_FREIGHT_CHARGE = 4327


def normalize_loading_point(value):
    """Return a known loading point, or ``None`` when the value is ambiguous."""
    if value is None or pd.isna(value):
        return None
    normalized = re.sub(r"[^A-Z0-9]", "", str(value).upper())
    aliases = {
        "THANE": "Thane",
        "VASAI": "Vasai",
        "ANDHERI": "Andheri",
        "VIDYAVIHAR": "Vidya Vihar",
        "BHIWANDI": "Bhiwandi",
        "KANDIVALI": "Kandivali",
        "KANDIWALI": "Kandivali",
        "PRPL": "PRPL",
        "WADA": "Wada",
        "MAHUL": "Mahul",
        "KHOPOLI": "Khopoli",
        "KAMSHET": "Kamshet",
    }
    exact_match = aliases.get(normalized)
    if exact_match:
        return exact_match

    # The Bhiwandi warehouse address also contains "Thane" as its district,
    # which would otherwise make the location appear ambiguous.
    if "RKLOGIWORLD" in normalized or "YEWAI" in normalized:
        return "Bhiwandi"

    # Gemini may preserve supporting source text such as "Thane Depot".  Accept
    # that only when it contains one, and exactly one, known depot identifier.
    matches = {point for alias, point in aliases.items() if alias in normalized}
    return matches.pop() if len(matches) == 1 else None


def short_origin(from_value, loading_point=None):
    """Prefer the normalized extraction origin while preserving unknown values."""
    normalized_origin = normalize_loading_point(loading_point)
    if normalized_origin is None:
        normalized_origin = normalize_loading_point(from_value)
    return normalized_origin or from_value


def _normalise_header(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).upper()


def _find_distance_column(master_data, loading_point):
    target = _normalise_header(f"Distance from {loading_point}")
    for index, column in enumerate(master_data.columns):
        if _normalise_header(column) == target:
            return index
    return None


def _is_valid_number(value):
    if value is None or pd.isna(value):
        return False
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _distance_matches_slab(distance, slab):
    """Validate the workbook's ``lower-upper`` slab for the given distance."""
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*", str(slab))
    if not match:
        return False
    lower, upper = map(float, match.groups())
    return lower <= float(distance) <= upper


def round_freight_charge(value):
    """Round standard master rates while leaving unrelated special rates intact."""
    if not _is_valid_number(value):
        return value
    rounded_value = int(round(float(value)))
    if rounded_value in APPROVED_ROUNDED_FREIGHT_CHARGES:
        return rounded_value
    return value


def build_freight_lookup(master_data):
    """Build ``customer code -> loading point -> freight charge`` from the matrix.

    A row is intentionally included only when its distance, slab, and calculated
    charge are all present.  This mirrors the workbook's distance -> slab ->
    freight calculation and prevents a stale rate from being used for missing
    distance data.
    """
    code_column = find_mumc_customer_code_column(master_data)
    distance_columns = {
        point: _find_distance_column(master_data, point) for point in LOADING_POINTS
    }
    lookup = {}

    for _, row in master_data.iterrows():
        customer_code = normalize_customer_code(row[code_column])
        if not customer_code.startswith("MUMC") or customer_code in lookup:
            continue

        routes = {}
        for point, distance_index in distance_columns.items():
            if distance_index is None:
                continue

            distance = row.iloc[distance_index]
            slab = row.iloc[distance_index + 1] if distance_index + 1 < len(row) else None
            charge = row.iloc[distance_index + 2] if distance_index + 2 < len(row) else None
            if (
                not _is_valid_number(distance)
                or not _distance_matches_slab(distance, slab)
                or not _is_valid_number(charge)
            ):
                continue
            routes[point] = float(charge)

        lookup[customer_code] = routes

    return lookup


def apply_freight_lookup(records, freight_lookup):
    """Add a display-only freight charge and remove internal loading-point data."""
    enriched_records = []
    for record in records:
        enriched_record = record.copy()
        enriched_record["Freight Charge"] = ""
        invoice_number = str(
            enriched_record.get(
                "Invoice No.",
                enriched_record.get("Invoice No", ""),
            )
            or ""
        ).strip().upper()
        customer_code = normalize_customer_code(enriched_record.get("Customer Code"))
        loading_point = normalize_loading_point(enriched_record.get("Loading Point"))

        if invoice_number.startswith("TON"):
            enriched_record["Freight Charge"] = DELIVERY_CHALLAN_FREIGHT_CHARGE
        elif customer_code not in freight_lookup:
            LOGGER.info("Freight lookup skipped for %s: customer not found", customer_code)
        elif not loading_point:
            LOGGER.info("Freight lookup skipped for %s: loading point not found", customer_code)
        else:
            charge = freight_lookup.get(customer_code, {}).get(loading_point)
            if charge is None:
                LOGGER.info(
                    "Freight lookup skipped for %s from %s: missing distance or invalid workbook data",
                    customer_code,
                    loading_point,
                )
            else:
                enriched_record["Freight Charge"] = round_freight_charge(charge)

        # Loading Point is extraction metadata and must never reach the UI/CSV.
        enriched_record.pop("Loading Point", None)
        enriched_records.append(enriched_record)
    return enriched_records
