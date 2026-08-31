import pandas as pd

from customer_master import (
    apply_customer_master_lookup,
    build_customer_lookup,
    find_mumc_customer_code_column,
)


def master_frame():
    return pd.DataFrame(
        {
            "Customer Code": ["D62138", "D62139", "D62140"],
            "Unnamed: 3": ["MUMC001", "MUMC002", "MUMC001"],
            "Name of the Distributor": ["Master One", "Master Two", "Duplicate"],
            "Short Address": ["Address One", "Address Two", "Duplicate Address"],
        }
    )


def test_mumc_column_is_used_instead_of_distributor_code():
    master = master_frame()

    assert find_mumc_customer_code_column(master) == "Unnamed: 3"
    lookup = build_customer_lookup(master)

    assert lookup["MUMC001"]["Customer Name"] == "Master One"
    assert "D62138" not in lookup


def test_lookup_enriches_matched_record_and_preserves_not_found_values():
    lookup = build_customer_lookup(master_frame())
    records = [
        {"Customer Code": "mumc 001", "Customer Name": "Gemini Name", "To": "Gemini Address"},
        {"Customer Code": "MUMC999", "Customer Name": "Original Name", "To": "Original Address"},
    ]

    enriched = apply_customer_master_lookup(records, lookup)

    assert enriched[0] == {
        "Customer Code": "mumc 001",
        "Customer Name": "Master One",
        "To": "Address One",
        "Lookup Status": "✅ Matched",
    }
    assert enriched[1] == {
        "Customer Code": "MUMC999",
        "Customer Name": "Original Name",
        "To": "Original Address",
        "Lookup Status": "⚠ Not Found",
    }
