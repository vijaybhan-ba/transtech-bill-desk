"""Reusable customer-master lookups for invoice enrichment.

The master workbook has a blank heading above the real customer-code column.
Those values consistently use the MUMC prefix, unlike the distributor-code
column, so the code column is identified by its values rather than its header.
"""

import logging
import os

import pandas as pd
import streamlit as st


LOGGER = logging.getLogger(__name__)
MASTER_DATABASE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data", "master_database.xlsx"
)
MASTER_NAME_COLUMN = "Name of the Distributor"
MASTER_SHORT_ADDRESS_COLUMN = "Short Address"


def normalize_customer_code(value):
    """Return a consistently formatted customer code for master matching."""
    if value is None or pd.isna(value):
        return ""
    return "".join(str(value).strip().upper().split())


def find_mumc_customer_code_column(master_data):
    """Find the column containing MUMC customer codes, never distributor IDs."""
    matching_columns = []
    for column in master_data.columns:
        normalized_codes = master_data[column].map(normalize_customer_code)
        mumc_count = normalized_codes.str.startswith("MUMC").sum()
        if mumc_count:
            matching_columns.append((mumc_count, column))

    if not matching_columns:
        raise ValueError("Customer master has no column containing MUMC customer codes.")

    # A MUMC column should dominate this workbook; this also copes with its blank header.
    return max(matching_columns, key=lambda item: item[0])[1]


@st.cache_data(show_spinner=False)
def load_customer_master():
    """Load the permanent customer master once per Streamlit cache lifecycle."""
    # Row 2 contains headers; row 1 is a set of address/reference values.
    return pd.read_excel(MASTER_DATABASE_PATH, header=1, dtype=str)


def build_customer_lookup(master_data):
    """Build a lookup keyed exclusively by MUMC customer code.

    This is intentionally separate from loading so future freight, distance,
    route, and transport lookups can reuse the same master dataframe.
    """
    missing_columns = {
        MASTER_NAME_COLUMN,
        MASTER_SHORT_ADDRESS_COLUMN,
    }.difference(master_data.columns)
    if missing_columns:
        raise ValueError(
            "Customer master is missing required column(s): "
            + ", ".join(sorted(missing_columns))
        )

    code_column = find_mumc_customer_code_column(master_data)
    lookup = {}
    for _, row in master_data.iterrows():
        customer_code = normalize_customer_code(row[code_column])
        # The source has placeholder values (notably ``0``) in this column;
        # only actual MUMC customer codes may participate in matching.
        if not customer_code.startswith("MUMC"):
            continue
        if customer_code in lookup:
            LOGGER.warning(
                "Duplicate customer code %s in customer master; using first occurrence.",
                customer_code,
            )
            continue
        lookup[customer_code] = {
            "Customer Name": row[MASTER_NAME_COLUMN],
            "To": row[MASTER_SHORT_ADDRESS_COLUMN],
        }

    # Future freight lookup belongs here, using this same MUMC-keyed master data.
    return lookup


def apply_customer_master_lookup(records, customer_lookup):
    """Enrich extracted invoice records without changing unmatched values."""
    enriched_records = []
    for record in records:
        enriched_record = record.copy()
        customer_code = normalize_customer_code(enriched_record.get("Customer Code"))
        master_customer = customer_lookup.get(customer_code)
        if master_customer:
            enriched_record["Customer Name"] = master_customer["Customer Name"]
            enriched_record["To"] = master_customer["To"]
            enriched_record["Lookup Status"] = "✅ Matched"
        else:
            enriched_record["Lookup Status"] = "⚠ Not Found"
        enriched_records.append(enriched_record)
    return enriched_records
